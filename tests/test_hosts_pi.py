"""pi's adapter: its dialect (``adapters/foreman_hosts/pi.py``), the entry point as the extension runs it, and the
extension itself (``adapters/pi/foreman.ts``) driven without pi where ``node`` can load TypeScript."""
import io
import json
import os
import shutil
import subprocess
import sys
import unittest

from tests_support import ROOT, GitRepoCase

from foreman import grants
from foreman.detector import MARKER
from foreman_hosts import core, neutral, pi

# Built from parts, as in the other tests: Foreman reads its own test files, and a literal marker here would be
# a finding in this repository's pull requests.
SKIP = "@pytest.mark." + "skip"
SKIPPED = "import pytest\n\n\n" + SKIP + "\ndef test_total():\n    assert 1 + 1 == 2\n"
MARKED = ("import pytest\n\n\n" + SKIP + "  # " + MARKER + " flaky upstream\ndef test_total():\n"
          "    assert 1 + 1 == 2\n")
# Words that are Hermes's or another harness's. `/foreman merge` is not one of them: pi has that command.
HERMES_WORDS = ("Hermes", "workdir", "write_file", "/foreman:")


class PiCase(GitRepoCase):
    def setUp(self):
        super().setUp()
        self.write("tests/test_cart.py", "def test_total():\n    assert 1 + 1 == 2\n")
        self.write("cart.py", "def total():\n    return 2\n")
        self.commit("base")

    def ask(self, event, env=None, **more):
        request = {"event": event, "cwd": self.root, "session": "pi-session", "turn": "run-1"}
        request.update(more)
        return neutral.answer(pi.host(request, env if env is not None else {}), request)

    def assertPiWords(self, text):
        for word in HERMES_WORDS:
            self.assertNotIn(word, text)


class TheHost(PiCase):
    def test_the_person_types_a_spaced_command(self):
        h = pi.host({})
        self.assertEqual(h.person("allow 3f2a"), "/foreman allow 3f2a")
        self.assertEqual(h.label, "pi")
        self.assertEqual(h.cli, ("pi", "pi-coding-agent"))

    def test_attended_is_only_the_requests_own_true(self):
        self.assertTrue(pi.host({"attended": True}).attended())
        for value in (False, "true", 1, None):
            self.assertFalse(pi.host({"attended": value}).attended(), value)
        self.assertFalse(pi.host(None).attended())

    def test_a_clone_keeps_only_its_code_and_an_installed_copy_is_whole(self):
        clone = os.path.join(self.tmp, "src", "foreman")
        self.assertEqual(pi._program_dirs((clone,)), (os.path.join(clone, "adapters"), os.path.join(clone, "plugin")))
        installed = os.path.join(self.tmp, ".pi", "agent", "git", "github.com", "x", "foreman")
        self.assertEqual(pi._program_dirs((installed,))[0], installed)


class SwitchingOff(PiCase):
    def test_the_agent_cannot_remove_or_reconfigure_the_extension(self):
        for command in ("pi remove git:github.com/someone/foreman", "pi uninstall ./foreman",
                        "npx @earendil-works/pi-coding-agent remove npm:foreman-pi", "pi config",
                        "pi config --local",
                        "jq '.extensions = []' ~/.pi/agent/settings.json > /tmp/s && mv /tmp/s ~/.pi/agent/settings.json",
                        "sed -i '' 's#/src/foreman/adapters/pi/foreman.ts#-x#' .pi/settings.json"):
            out = self.ask("shell", command=command)
            self.assertEqual(out.get("action"), "block", command)
            self.assertIn("user's decision", out["message"])

    def test_reading_pis_settings_and_other_pi_commands_are_ordinary_work(self):
        for command in ("pi list", "pi --version", "cat ~/.pi/agent/settings.json", "jq .extensions .pi/settings.json",
                        "pi remove npm:some-other-package", "git commit --allow-empty -m 'pi config is blocked'",
                        "grep -n packages ~/.pi/agent/settings.json"):
            self.assertEqual(self.ask("shell", command=command), {}, command)

    def test_a_settings_write_that_drops_or_excludes_foreman_is_blocked(self):
        settings = self.write(".pi/settings.json", '{"extensions": ["/src/foreman/adapters/pi/foreman.ts"]}')
        for content in ('{"extensions": []}', '{"extensions": ["-/src/foreman/adapters/pi/foreman.ts"]}'):
            out = self.ask("write", path=settings, content=content)
            self.assertEqual(out.get("action"), "block", content)
        out = self.ask("write", path=settings, old='"/src/foreman', new='"!/src/foreman')
        self.assertEqual(out.get("action"), "block")
        self.assertEqual(self.ask("write", path=settings,
                                  content='{"extensions": ["/src/foreman/adapters/pi/foreman.ts"], "theme": "x"}'), {})

    def test_what_the_person_excluded_themselves_can_still_be_edited(self):
        settings = self.write(".pi/settings.json", '{"extensions": ["!**/foreman.ts"], "theme": "a"}')
        self.assertEqual(self.ask("write", path=settings, old='"a"', new='"b"'), {})

    def test_a_moved_agent_directory_is_still_pis_settings(self):
        agent = os.path.join(self.tmp, "pi-agent")
        env = {"PI_CODING_AGENT_DIR": agent}
        self.assertTrue(pi.host({}, env).is_config(os.path.join(agent, "settings.json")))
        out = self.ask("shell", env=env, command="echo '{\"packages\": []}' > %s/settings.json" % agent)
        self.assertEqual(out.get("action"), "block")

    def test_the_agent_cannot_type_the_persons_allow_through_a_nested_pi(self):
        for command in ("pi -p '/foreman allow 3f2a'",
                        "echo '{\"type\":\"prompt\",\"message\":\"/foreman allow 3f2a\"}' | pi --mode rpc"):
            out = self.ask("shell", command=command)
            self.assertEqual(out.get("action"), "block", command)
            self.assertIn("/foreman allow <id>", out["message"])

    def test_the_agent_cannot_touch_the_extension_or_run_the_entry_point(self):
        extension = os.path.join(ROOT, "adapters", "pi", "foreman.ts")
        self.assertEqual(self.ask("write", path=extension, content="export default () => {}")["action"], "block")
        self.assertEqual(self.ask("shell", command="rm %s" % extension)["action"], "block")
        self.assertEqual(self.ask("shell", command="python3 -I adapters/hook.py pi < forged.json")["action"], "block")


class TheGate(PiCase):
    def test_a_rigged_commit_and_a_merge_are_blocked_in_pis_words(self):
        self.write("tests/test_cart.py", SKIPPED)
        self.git("add", "-A")
        out = self.ask("shell", command="git commit -m green")
        self.assertEqual(out["action"], "block")
        self.assertIn("tests/test_cart.py:4", out["message"])
        self.assertPiWords(out["message"])
        merge = self.ask("shell", command="gh pr merge 7")
        self.assertEqual(merge["action"], "block")
        self.assertPiWords(merge["message"])
        self.assertIn("Ask them to run `/foreman merge 7`", merge["message"])  # the person's own command, in pi

    def test_the_persons_commands_in_pis_words(self):
        help_text = self.ask("command", args="help")["reply"]
        self.assertIn("In pi:", help_text)
        self.assertIn("/foreman status", help_text)
        self.assertPiWords(help_text)
        self.assertIn("Foreman: CLEAN", self.ask("command", args="status")["reply"])
        self.assertIn("Foreman board: repo", self.ask("command", args="")["reply"])  # the board is the default
        reply = self.ask("command", args="notify on")["reply"]  # phone notices are Hermes's
        self.assertIn("not available in pi yet", reply)
        self.assertIn("/foreman help", reply)
        for name in ("merge 7", "reject 7"):  # pi has them, and with nobody at its interface they do nothing
            self.assertIn("nobody is attending", self.ask("command", args=name)["reply"], name)

    def test_allow_needs_a_person_at_pis_interface(self):
        self.write("tests/test_cart.py", MARKED)
        self.git("add", "-A")
        self.assertEqual(self.ask("shell", command="git commit -m green")["action"], "block")
        short_id = grants.pending()[0]["id"]
        refused = self.ask("command", args="allow " + short_id, attended=False)["reply"]
        self.assertIn("nobody is attending", refused)
        self.assertIn("interactive pi session", refused)
        self.assertIn("allowed " + short_id, self.ask("command", args="allow " + short_id, attended=True)["reply"])
        self.assertEqual(self.ask("shell", command="git commit -m green"), {})


class EntryPoint(PiCase):
    """``python3 -I adapters/hook.py pi``, as the extension runs it."""

    def run_hook(self, raw):
        home = os.path.join(self.tmp, "home")
        os.makedirs(home, exist_ok=True)
        env = dict(os.environ, HOME=home, USERPROFILE=home, PYTHONPATH=os.path.join(self.tmp, "planted"))
        r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "adapters", "hook.py"), "pi"],
                           input=raw.encode(), capture_output=True, env=env, cwd=self.root, timeout=60)
        return r.returncode, r.stdout.decode(), r.stderr.decode(), home

    def test_it_blocks_a_rigged_commit_and_keeps_its_state_in_the_home_directory(self):
        self.write("tests/test_cart.py", SKIPPED)
        self.git("add", "-A")
        code, out, err, home = self.run_hook(json.dumps({"event": "shell", "command": "git commit -m green",
                                                         "cwd": self.root, "session": "s", "turn": "t"}))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["action"], "block")
        self.assertTrue(os.path.isdir(os.path.join(home, ".foreman")))

    def test_what_is_not_a_request_is_exit_code_1_with_no_answer(self):
        code, out, err, _home = self.run_hook("not json")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("not a JSON object", err)

    def test_main_reads_one_request_and_writes_one_answer(self):
        stdout = io.StringIO()
        code = pi.main(stdin=io.StringIO(json.dumps({"event": "command", "args": "help", "cwd": self.root})),
                       stdout=stdout, env={})
        self.assertEqual(code, 0)
        self.assertIn("In pi:", json.loads(stdout.getvalue())["reply"])



class TheReviewersHost(PiCase):
    def test_pi_has_a_reviewer_its_thinking_levels_and_the_sessions_own_state(self):
        h = pi.host({"model": "p/m", "effort": "high", "event": "command"})
        self.assertIsNotNone(h.fresh_session)
        self.assertEqual(h.efforts, ("off", "minimal", "low", "medium", "high", "xhigh", "max"))
        self.assertEqual((h.session().model, h.session().effort), ("p/m", "high"))
        self.assertEqual(pi.host({}).session(), core.Session())
        self.assertEqual(pi.host({"model": 7, "effort": None}).session(), core.Session())

    def test_the_help_lists_the_review_in_pis_words(self):
        reply = self.ask("command", args="help")["reply"]
        self.assertIn("/foreman review ", reply)
        self.assertIn("/foreman reviewer", reply)
        self.assertPiWords(reply)

    def test_the_review_is_one_level_above_the_sessions_exact_thinking_level(self):
        reply = self.ask("command", args="reviewer", model="p/m-1", effort="medium")["reply"]
        self.assertIn("p/m-1, the model this session runs on, at effort high, one level above this session's medium",
                      reply)
        self.assertIn("That is the model that wrote the code: more effort and a clean context", reply)
        self.assertIn("Effort levels: off, minimal, low, medium, high, xhigh, max", reply)
        top = self.ask("command", args="reviewer", effort="max")["reply"]
        self.assertIn("the highest there is and the same as this session's", top)
        self.assertIn("pi has not told Foreman this session's effort", self.ask("command", args="reviewer")["reply"])
        self.assertPiWords(reply)

    def test_choosing_a_reviewer_is_kept_and_checked_against_pis_levels(self):
        self.assertIn("reviewer set", self.ask("command", args="reviewer some-model low")["reply"])
        shown = self.ask("command", args="reviewer", model="other/model", effort="medium")["reply"]
        self.assertIn("some-model at effort low", shown)
        self.assertIn("is not an effort level of pi", self.ask("command", args="reviewer some-model fast")["reply"])
        self.assertIn("back to the default", self.ask("command", args="reviewer default")["reply"])



def _node_skip_reason() -> str:
    """Why the extension's tests cannot run here, or "" when they can."""
    node = shutil.which("node")
    if not node:
        return "no node on the PATH: these tests need node 22.18 or newer (it loads TypeScript as it is)"
    probe = subprocess.run([node, "-e", "import(process.argv[1]).then(() => process.exit(0), () => process.exit(3))",
                            os.path.join(ROOT, "adapters", "pi", "foreman.ts")], capture_output=True, timeout=60)
    if probe.returncode == 0:
        return ""
    version = subprocess.run([node, "--version"], capture_output=True, timeout=60).stdout.decode().strip()
    return "node %s cannot load TypeScript: these tests need node 22.18 or newer" % (version or "(unknown version)")


NODE_SKIP = _node_skip_reason()
# Commands for the quick filter's copy: the TypeScript must answer as `gate._quick` does on each.
QUICK_COMMANDS = ["git commit -m x", "git push", "gh pr create", "gh pr merge 7", "gh pr edit 3", "gh pr ready 3",
                  "git config core.hooksPath /dev/null", "GIT.EXE COMMIT", "cd x && git -C y push origin", "ls -la",
                  "git status", "gh issue list", "echo commit", "github push", "make pr", "git.exe log", "gh-pr",
                  "pushd x && git log", "git log --pretty=format:%s | grep commit"]


@unittest.skipIf(NODE_SKIP, NODE_SKIP)
class TheExtension(PiCase):
    """The extension's handlers, called as pi calls them, each running the real entry point."""

    def drive(self, scenario, **env_more):
        home = os.path.join(self.tmp, "home")
        os.makedirs(home, exist_ok=True)
        env = dict(os.environ, HOME=home, USERPROFILE=home, **env_more)
        env.pop("FOREMAN_PYTHON", None)
        r = subprocess.run([shutil.which("node"), os.path.join(ROOT, "tests", "pi_extension_driver.mjs"), self.root,
                            scenario], capture_output=True, env=env, timeout=240)
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        return json.loads(r.stdout.decode())

    def fake_python(self, body):
        """A stand-in for python3 that ignores its request and runs ``body`` (a POSIX shell script)."""
        path = os.path.join(self.tmp, "fake-python")
        with open(path, "w") as fh:
            fh.write("#!/bin/sh\ncat > /dev/null\n" + body + "\n")
        os.chmod(path, 0o755)
        return path

    def test_the_quick_filter_is_the_gates_own(self):
        out = self.drive("quick", QUICK_COMMANDS=json.dumps(QUICK_COMMANDS))
        self.assertEqual(dict(zip(QUICK_COMMANDS, out["gated"])),
                         {c: core.looks_gated(c) for c in QUICK_COMMANDS})

    def test_paths_are_read_as_pis_own_tools_read_them(self):
        out = self.drive("paths")
        for key in ("win_drive", "win_mnt", "win_cygdrive"):
            self.assertEqual(out[key], "C:\\Users\\me\\repo\\tests\\test_a.py", key)
        self.assertEqual(out["win_at_drive"], "C:\\Users\\me\\repo")
        self.assertEqual(out["posix_drive_like"], "/c/Users/me/repo")
        self.assertEqual(out["unicode_spaces"], "/repo/tests/test a b c.py")
        self.assertEqual(out["bad_url"], "file://host/x")  # pi cannot resolve it either: sent as given
        self.assertEqual(out["bad_url_request"], [{"cwd": "/repo", "session": "s", "turn": "", "event": "write",
                                                   "path": "file://host/x"}])

    @unittest.skipIf(os.name == "nt", "the stand-in interpreter is a POSIX shell script")
    def test_the_extension_sends_the_agent_back_at_most_once_per_run_on_its_own(self):
        out = self.drive("always-continue",
                         FAKE_PYTHON=self.fake_python("""echo '{"action": "continue", "message": "undo it"}'"""))
        self.assertTrue(out["first"]["continue"])
        self.assertIsNone(out["second"])
        self.assertTrue(out["next_run"]["continue"])

    @unittest.skipIf(os.name == "nt", "the stand-in interpreter is a POSIX shell script")
    def test_no_answer_in_time_is_no_answer(self):
        out = self.drive("timeout", FAKE_PYTHON=self.fake_python("sleep 5; echo '{}'"))
        self.assertIn("no answer within 0.3 seconds", out["timeout"])

    def test_it_registers_what_it_needs_and_gates_the_tools(self):
        self.write("tests/test_cart.py", SKIPPED)
        self.write(".pi/settings.json", '{"extensions": ["/src/foreman/adapters/pi/foreman.ts"]}')
        self.git("add", "-A")
        out = self.drive("gate")
        self.assertEqual(out["registered"], {"events": ["agent_before_settle", "before_agent_start", "tool_call"],
                                             "commands": ["foreman"]})
        for key in ("commit", "merge", "powershell_merge", "edit", "legacy_edit", "write", "other_tool_on_state",
                    "two_edits", "tilde_state", "at_settings", "at_test"):
            self.assertTrue((out[key] or {}).get("block"), key)
        self.assertIn("tests/test_cart.py:4", out["commit"]["reason"])
        self.assertIn("own program and state", out["tilde_state"]["reason"])
        self.assertIn("user's decision", out["at_settings"]["reason"])
        for key in ("ordinary_write", "ls", "read", "one_harmless_edit"):
            self.assertIsNone(out[key], key)
        self.assertIn("In pi:", out["help"]["printed"])
        self.assertIn("Foreman: BLOCKED", out["status"]["printed"])
        self.assertEqual(out["help_json"]["printed"], "")  # never mixed into pi's JSON event stream
        self.assertIn("In pi:", out["help_json"]["stderr"])


    def test_the_variable_alone_switches_nothing_off(self):
        # a project's settings can set it for every session: standing down is hook.py's, for a live token only
        for value in ("1", "0" * 32, ""):
            out = self.drive("stood-down", FOREMAN_REVIEWER=value)
            self.assertEqual(out["registered"]["commands"], ["foreman"], value)
            self.assertEqual(out["registered"]["events"], ["agent_before_settle", "before_agent_start", "tool_call"])

    def test_a_turn_is_sent_back_once_and_a_turn_that_talked_is_not(self):
        out = self.drive("turn")
        self.assertIsNone(out["talk_only"])
        self.assertIsNone(out["shell"])
        self.assertTrue(out["first"]["continue"])
        entry = out["first"]["entries"][0]
        self.assertEqual((entry["type"], entry["customType"], entry["display"]), ("custom_message", "foreman", True))
        self.assertIn("tests/test_cart.py", entry["content"])
        self.assertIsNone(out["second"])
        self.assertIsNone(out["shell_again"])
        self.assertTrue(out["third"]["continue"])  # the next prompt is a new run: nudged again

    def test_ask_goes_to_the_person_and_with_nobody_there_is_refused(self):
        out = self.drive("ask")
        self.assertTrue(out["nobody"]["block"])
        self.assertTrue(out["declined"]["block"])
        self.assertIsNone(out["approved"])
        self.assertEqual([kind for kind, _message in out["shown"]], ["confirm", "confirm"])

    def test_allow_works_only_with_a_person_at_the_interface(self):
        self.write("tests/test_cart.py", MARKED)
        self.git("add", "-A")
        out = self.drive("allow")
        self.assertTrue(out["blocked"]["block"])
        self.assertTrue(out["id"])
        self.assertIn("nobody is attending", out["unattended"]["printed"])
        self.assertTrue(out["still_blocked"]["block"])
        self.assertIn("allowed " + out["id"], out["attended"]["shown"][0][1])
        self.assertIsNone(out["passes"])

    def test_without_python_a_gated_command_never_passes_silently(self):
        out = self.drive("no-python")
        self.assertTrue(out["gated_nobody"]["block"])
        self.assertIn("could not run", out["gated_nobody"]["reason"])
        self.assertTrue(out["gated_person"]["block"])  # the person was asked and declined
        self.assertIsNone(out["ordinary"])
        self.assertIsNone(out["write"])
        self.assertIsNone(out["settle"])
        self.assertEqual(out["help"]["printed"], "")  # the person's command shows its error instead
        self.assertIn("Foreman could not run: cannot run", out["help"]["stderr"])
        # a failed check reaches the person once per session, not on every call
        self.assertEqual(out["stderr"].count("not checking this session"), 1, out["stderr"])
        self.assertIn("could not inspect a bash call", out["stderr"])


if __name__ == "__main__":
    unittest.main()
