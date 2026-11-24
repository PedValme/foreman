"""Codex's side of the reviewer (``adapters/foreman_hosts/codex.py``): the headless session it starts, the person's
commands that reach it, and what the hook input says about the session."""
import json
import os
import stat
import sys
import unittest

from tests_support import ROOT, GitRepoCase

from foreman import grants, review
from foreman_hosts import codex, core, reviewer

PASS = {"findings": [], "summary": "Nothing rigged.", "verdict": "PASS"}
POSIX = unittest.skipIf(os.name == "nt", "the stand-in for `codex` is a POSIX shell script")


def events(*items):
    return "\n".join(json.dumps(i) for i in items)


def said(text):
    return events({"type": "thread.started", "thread_id": "t"}, {"type": "turn.started"},
                  {"type": "item.completed", "item": {"id": "i", "type": "agent_message", "text": text}},
                  {"type": "turn.completed", "usage": {}})


class CodexCase(GitRepoCase):
    def program(self, stdout, code=0, stderr=""):
        """A `codex` that records how it was called and prints ``stdout``; returns the environment to find it by."""
        directory = os.path.join(self.tmp, "bin")
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "codex")
        with open(path, "w") as fh:
            fh.write("#!/bin/sh\nprintf '%%s\\n' \"$@\" > '%s/argv'\ncat > '%s/stdin'\npwd > '%s/cwd'\n"
                     "printf '%%s' \"$FOREMAN_REVIEWER\" > '%s/env'\n"
                     "for last; do :; done\n"
                     "i=0; for a; do i=$((i+1)); if [ \"$a\" = --output-schema ]; then n=$((i+1)); fi; done\n"
                     "eval \"s=\\${$n}\"; cp \"$s\" '%s/schema' 2>/dev/null\n"
                     "for a; do case \"$a\" in model_instructions_file=*) f=${a#model_instructions_file=}; f=${f#\\\"}; "
                     "f=${f%%\\\"}; cp \"$f\" '%s/rules';; esac; done\n"
                     "cat <<'EOF'\n%s\nEOF\ncat >&2 <<'EOF'\n%s\nEOF\nexit %d\n"
                     % (self.tmp, self.tmp, self.tmp, self.tmp, self.tmp, self.tmp, stdout, stderr, code))
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        return {"PATH": directory + os.pathsep + os.environ.get("PATH", "")}

    def read(self, name):
        with open(os.path.join(self.tmp, name)) as fh:
            return fh.read()


@POSIX
class CodexFreshSession(CodexCase):
    def test_it_asks_in_a_read_only_empty_session_and_reads_the_last_message(self):
        env = self.program(events(
            {"type": "thread.started", "thread_id": "t"},
            {"type": "item.completed", "item": {"type": "error", "message": "a warning, not a failure"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "thinking aloud"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(PASS)}},
            {"type": "turn.completed"}))
        schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}, "b": {"type": "object",
                  "properties": {"c": {"type": "integer"}}}}}
        answer = codex._fresh_session(env)("SYSTEM", "THE PROMPT", schema, "model-b", "high", 30)
        self.assertEqual(answer.parsed, PASS)
        argv = self.read("argv").split("\n")
        self.assertEqual(argv[0], "exec")
        for flag in ("--ephemeral", "--ignore-user-config", "--skip-git-repo-check", "--json"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
        self.assertEqual(argv[argv.index("--model") + 1], "model-b")
        configs = [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]
        self.assertIn("model_reasoning_effort=high", configs)
        self.assertTrue(any(c.startswith("model_instructions_file=\"") for c in configs))
        for tool in ("shell_tool", "unified_exec", "view_image"):  # no shell or command tool at all
            self.assertEqual(argv[argv.index(tool) - 1], "--disable")
        self.assertEqual(argv[-2], "-")  # the prompt is read from standard input
        self.assertNotIn("THE PROMPT", argv)
        self.assertNotIn("SYSTEM", argv)
        self.assertEqual(self.read("stdin"), "THE PROMPT")  # only the diff's prompt; the rules are the instructions
        self.assertEqual(self.read("rules"), "SYSTEM")
        self.assertRegex(self.read("env"), r"^[0-9a-f]{32}$")  # this review's own token
        self.assertNotEqual(os.path.realpath(self.read("cwd").strip()), os.path.realpath(self.root))
        sent = json.loads(self.read("schema"))  # every object closed and every property required, as the API wants
        self.assertEqual(sent["additionalProperties"], False)
        self.assertEqual(sent["required"], ["a", "b"])
        self.assertEqual(sent["properties"]["b"]["additionalProperties"], False)
        self.assertEqual(sent["properties"]["b"]["required"], ["c"])
        self.assertNotIn("additionalProperties", schema)  # the caller's schema is not touched

    def test_no_model_and_no_effort_means_no_such_flags(self):
        answer = codex._fresh_session(self.program(said(json.dumps(PASS))))("", "P", {}, "", "", 30)
        self.assertEqual(answer.parsed, PASS)
        argv = self.read("argv").split("\n")
        self.assertNotIn("--model", argv)
        self.assertNotIn("-m", argv)
        self.assertNotIn("-c", argv)
        self.assertEqual(self.read("stdin"), "P")
        self.assertFalse(any("model_instructions_file" in a for a in argv))  # no rules, no file

    def test_the_model_that_answered_is_not_invented(self):
        answer = codex._fresh_session(self.program(said(json.dumps(PASS))))("S", "P", {}, "asked-for", "low", 30)
        self.assertEqual(answer.model, "")  # Codex does not say it

    def test_a_failed_turn_names_its_reason_and_status(self):
        env = self.program(events({"type": "turn.started"}, ) + "\n" + json.dumps(
            {"type": "turn.failed", "error": {"message": "unexpected status 429 Too Many Requests: slow down"}}), 1)
        with self.assertRaises(RuntimeError) as caught:
            codex._fresh_session(env)("S", "P", {}, "", "", 30)
        self.assertIn("(429)", str(caught.exception))
        self.assertIn("slow down", str(caught.exception))
        env = self.program(json.dumps({"type": "error", "message": "stream disconnected: 503 Service Unavailable"}), 1)
        with self.assertRaises(RuntimeError) as caught:
            codex._fresh_session(env)("S", "P", {}, "", "", 30)
        self.assertIn("(503)", str(caught.exception))

    def test_no_result_is_a_reason_not_a_pass(self):
        for stdout, code, stderr in (("not json at all", 3, "boom"), ("", 0, ""), ("[]", 2, "")):
            if code == 0:
                answer = codex._fresh_session(self.program(stdout, code, stderr))("S", "P", {}, "", "", 30)
                self.assertIsNone(answer.parsed)  # exit 0 and no message: no object, the review says it could not run
                continue
            with self.assertRaises(RuntimeError) as caught:
                codex._fresh_session(self.program(stdout, code, stderr))("S", "P", {}, "", "", 30)
            self.assertIn("Codex could not answer", str(caught.exception))
        with self.assertRaises(RuntimeError):
            codex._fresh_session({"PATH": os.path.join(self.tmp, "nowhere")})("S", "P", {}, "", "", 30)

    def test_an_answer_that_is_not_an_object_is_no_answer(self):
        answer = codex._fresh_session(self.program(said("I would rather not.")))("S", "P", {}, "", "", 30)
        self.assertIsNone(answer.parsed)
        self.assertEqual(answer.text, "I would rather not.")


class CodexReviewer(CodexCase):
    def setUp(self):
        super().setUp()
        self.write("tests/test_cart.py", "def test_total():\n    assert total() == 2\n")
        self.write("cart.py", "def total():\n    return 2\n")
        self.commit("base")
        self.write("tests/test_cart.py", "def test_total():\n    assert total()\n")

    def hook(self, prompt, env=None, **more):
        data = {"session_id": "sess-1", "turn_id": "turn-1", "cwd": self.root, "hook_event_name": "UserPromptSubmit",
                "prompt": prompt, "model": "author-model"}
        data.update(more)
        return codex.answer(data, env or {})

    def test_the_efforts_are_codexs_own_levels(self):
        h = codex.host({})
        for level in ("low", "medium", "high", "xhigh", "max", "ultra"):  # what a review can really be given
            self.set_reviewer("m-1", level)
            self.assertEqual(reviewer.setting(h), ("m-1", level))
            self.assertIn("effort %s" % level, reviewer.configure(h, "m-1 " + level))
        self.assertIn("is not an effort level of Codex", reviewer.configure(h, "m-1 turbo"))
        self.assertIn("is not an effort level of Codex", reviewer.configure(h, "m-1 minimal"))
        self.assertIsNotNone(h.fresh_session)
        self.assertEqual(core.person_subcommands(h).keys() >= {"review", "reviewer"}, True)

    def set_reviewer(self, model, effort):
        reviewer._save_setting(codex.host({}), model, effort)

    def test_the_session_names_its_model_and_not_its_effort(self):
        self.assertEqual(codex.host({}, {"model": "gpt-x"}).session(), core.Session(model="gpt-x", effort=""))
        self.assertEqual(codex.host({}, {}).session(), core.Session())
        self.assertEqual(codex.host({}, {"model": 5}).session(), core.Session())

    def test_the_exact_command_forms_are_commands(self):
        for text in ("foreman review", "foreman review --fresh", "foreman review main", "foreman review 42 --fresh",
                     "foreman review --fresh 42", "/foreman review", "  FOREMAN review  ",
                     "foreman reviewer", "foreman reviewer default", "foreman reviewer high",
                     "foreman reviewer gpt-6-luna", "foreman reviewer gpt-6-luna low", "foreman reviewer o3 xhigh"):
            self.assertTrue(codex._PERSON_COMMAND.fullmatch(text), text)

    def test_every_other_prompt_still_goes_to_the_model(self):
        for text in ("foreman review this diff please", "foreman review the cart\nthen fix it", "foreman review a b",
                     "foreman review a --fresh b", "foreman review --fresh --fresh", "foreman review -x",
                     "foreman reviewer is slow", "foreman reviewer please", "foreman reviewer gpt-6-luna fast",
                     "foreman reviewer a b c", "foreman reviewer default low", "foreman reviewer\nhigh",
                     "foreman reviewers", "foreman reviewing", "please run foreman review", "foreman: review",
                     "foreman review --fresh\nand rebase"):
            self.assertIsNone(self.hook(text), text)

    def test_the_help_lists_them_as_typed_in_codex(self):
        reason = self.hook("foreman help")["reason"]
        self.assertIn("foreman review ", reason)
        self.assertIn("foreman reviewer ", reason)
        self.assertNotIn("/foreman", reason)

    def test_the_reviewer_can_be_shown_but_not_set_from_a_codex_prompt(self):
        self.assertIn("author-model, the model this session runs on", self.hook("foreman reviewer")["reason"])
        for text in ("foreman reviewer gpt-6-luna low", "foreman reviewer high", "foreman reviewer default",
                     "/foreman reviewer o3"):
            out = self.hook(text)
            self.assertEqual(out["decision"], "block", text)
            self.assertIn("cannot be set from a Codex prompt", out["reason"])
            self.assertIn('{"reviewer": {"codex": {"model": "<model>", "effort": "<low|medium', out["reason"])
            self.assertIn("config.json", out["reason"])
            self.assertEqual(reviewer.setting(codex.host({})), ("", ""), text)  # nothing was saved
        self.set_reviewer("gpt-6-luna", "low")  # what the person writes in the file is what the review reports
        shown = self.hook("foreman reviewer")["reason"]
        self.assertIn("reviewer in Codex: gpt-6-luna at effort low", shown)
        self.assertNotIn("reviewer <model> [effort]", shown)  # no advice Codex refuses
        self.assertNotIn("goes back to the default", shown)
        self.assertIn("setting it is not available in Codex", self.hook("foreman help")["reason"])
        self.assertNotIn("set it, or", self.hook("foreman help")["reason"])

    def test_when_codex_names_the_sessions_model_the_review_says_so(self):
        self.set_reviewer("author-model", "low")
        shown = self.hook("foreman reviewer")["reason"]
        self.assertIn("It is the same model that wrote the code", shown)
        self.set_reviewer("", "")
        nameless = self.hook("foreman reviewer", model="")["reason"]
        self.assertIn("Codex's default model at its default effort", nameless)
        self.assertIn("Codex has not told Foreman this session's effort", nameless)
        self.assertNotIn("one level above", nameless)

    @POSIX
    def test_a_review_runs_through_the_hook_and_is_stored(self):
        env = self.program(said(json.dumps(PASS)))
        out = self.hook("foreman review", env)
        self.assertEqual(out["decision"], "block")
        self.assertIn("Foreman review: PASS", out["reason"])
        self.assertIn("Reviewer: author-model, the model this session runs on, at its default effort", out["reason"])
        self.assertIn("Codex has not told Foreman this session's effort", out["reason"])
        self.assertEqual(self.read("argv").split("\n")[self.read("argv").split("\n").index("--model") + 1],
                         "author-model")
        self.assertNotIn("`/foreman", out["reason"])
        self.assertIn("-    assert total() == 2", self.read("stdin"))
        self.assertIn("FOREMAN-UNTRUSTED-", self.read("stdin"))
        os.unlink(os.path.join(self.tmp, "argv"))
        again = self.hook("foreman review", env)["reason"]
        self.assertIn("this is the stored result", again)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "argv")))  # no second session
        self.assertIn("`foreman review --fresh` runs it again", again)
        self.set_reviewer("gpt-6-luna", "low")
        self.hook("foreman review", env)
        argv = self.read("argv").split("\n")
        self.assertEqual(argv[argv.index("--model") + 1], "gpt-6-luna")
        self.assertIn("model_reasoning_effort=low", [argv[i + 1] for i, a in enumerate(argv) if a == "-c"])

    @POSIX
    def test_a_failed_session_is_a_review_that_could_not_run(self):
        env = self.program(json.dumps({"type": "error", "message": "unexpected status 500 oops"}), 1)
        out = self.hook("foreman review", env)["reason"]
        self.assertIn("Foreman review: COULD NOT RUN", out)
        self.assertIn("oops", out)

    def test_the_hooks_wait_for_a_review(self):
        with open(os.path.join(ROOT, "adapters", "codex", "hooks.json"), encoding="utf-8") as fh:
            hooks = json.load(fh)["hooks"]
        self.assertEqual(hooks["UserPromptSubmit"][0]["hooks"][0]["timeout"], 600)
        self.assertGreater(hooks["UserPromptSubmit"][0]["hooks"][0]["timeout"], reviewer.REVIEW_BUDGET_SECONDS)
        with open(os.path.join(ROOT, "adapters", "codex", "README.md"), encoding="utf-8") as fh:
            self.assertIn("UserPromptSubmit=[{hooks=[{type=\\\"command\\\",command=\\\"$HOOK\\\",timeout=600}]}]",
                          fh.read())


if __name__ == "__main__":
    unittest.main()
