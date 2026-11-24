"""Codex's adapter: its hook JSON in, its hook JSON out (``adapters/foreman_hosts/codex.py``), the entry point as
Codex runs it, and the hooks file."""
import io
import json
import os
import subprocess
import sys
import unittest

from tests_support import ROOT, GitRepoCase

from foreman import grants
from foreman.detector import MARKER
from foreman_hosts import codex, core

# Built from parts, as in the other tests: Foreman reads its own test files, and a literal marker here would be
# a finding in this repository's pull requests.
SKIP = "@pytest.mark." + "skip"
SKIPPED = "import pytest\n\n\n" + SKIP + "\ndef test_total():\n    assert 1 + 1 == 2\n"
MARKED = ("import pytest\n\n\n" + SKIP + "  # " + MARKER + " flaky upstream\ndef test_total():\n"
          "    assert 1 + 1 == 2\n")
SKIP_PATCH = ("*** Begin Patch\n*** Update File: tests/test_cart.py\n@@\n-def test_total():\n+" + SKIP +
              "\n+def test_total():\n*** End Patch\n")
PLAIN_PATCH = "*** Begin Patch\n*** Update File: cart.py\n@@\n-    return 2\n+    return 1 + 1\n*** End Patch\n"
HERMES_WORDS = ("workdir", "Hermes", "write_file", "/foreman merge", "/foreman allow", "/foreman status")


class CodexCase(GitRepoCase):
    def setUp(self):
        super().setUp()
        self.write("tests/test_cart.py", "def test_total():\n    assert 1 + 1 == 2\n")
        self.write("cart.py", "def total():\n    return 2\n")
        self.commit("base")

    def payload(self, event, **more):
        data = {"session_id": "sess-1", "turn_id": "turn-1", "cwd": self.root, "hook_event_name": event,
                "model": "gpt-test", "permission_mode": "bypassPermissions",
                "transcript_path": os.path.join(self.tmp, "rollout.jsonl")}
        data.update(more)
        return data

    def tool(self, name, **tool_input):
        return codex.answer(self.payload("PreToolUse", tool_name=name, tool_use_id="call-1", tool_input=tool_input), {})

    def prompt(self, text, turn="turn-1"):
        return codex.answer(self.payload("UserPromptSubmit", prompt=text, turn_id=turn), {})

    def stop(self, turn="turn-1", active=False):
        return codex.answer(self.payload("Stop", turn_id=turn, stop_hook_active=active,
                                         last_assistant_message="done"), {})

    def decision(self, out):
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "PreToolUse")
        return hso["permissionDecision"], hso["permissionDecisionReason"]

    def assertCodexWords(self, text):
        for word in HERMES_WORDS:
            self.assertNotIn(word, text)


class PreToolUse(CodexCase):
    def test_other_tools_and_ordinary_commands_get_no_answer(self):
        self.assertIsNone(self.tool("Bash", command="ls -la"))
        self.assertIsNone(self.tool("mcp__filesystem__read_file", path="cart.py"))
        self.assertIsNone(self.tool("update_plan", plan=[]))
        self.assertIsNone(codex.answer(self.payload("PreToolUse", tool_name="Bash", tool_input="oops"), {}))

    def test_a_commit_that_skips_a_test_is_denied_with_the_file_and_line(self):
        self.write("tests/test_cart.py", SKIPPED)
        self.git("add", "-A")
        verdict, reason = self.decision(self.tool("Bash", command="git add -A && git commit -m wip ."))
        self.assertEqual(verdict, "deny")
        self.assertIn("tests/test_cart.py:4", reason)
        self.assertCodexWords(reason)

    def test_an_argv_command_is_read_as_its_shell_line(self):
        self.write("tests/test_cart.py", SKIPPED)
        self.git("add", "-A")
        self.assertEqual(self.decision(self.tool("Bash", command=["bash", "-lc", "git commit -m wip"]))[0], "deny")
        self.assertEqual(self.decision(self.tool("Bash", command=["gh", "pr", "merge", "7"]))[0], "deny")

    def test_an_agent_run_merge_is_always_denied(self):
        verdict, reason = self.decision(self.tool("Bash", command="gh pr merge 7"))
        self.assertEqual(verdict, "deny")
        self.assertIn("Merging is the user's decision", reason)
        self.assertIn("`gh pr merge 7`", reason)
        self.assertCodexWords(reason)

    def test_what_needs_a_person_is_refused_because_codex_cannot_ask(self):
        out = codex.answer(self.payload("PreToolUse", tool_name="Bash", cwd=os.path.join(self.tmp, "gone"),
                                        tool_input={"command": "git commit -m x"}), {})
        verdict, reason = self.decision(out)
        self.assertEqual(verdict, "deny")  # never "ask": Codex lets the call through on an `ask`
        self.assertIn("Codex cannot ask", reason)
        self.assertIn("could not inspect", reason)

    def test_a_patch_that_skips_a_test_is_denied(self):
        verdict, reason = self.decision(self.tool("apply_patch", command=SKIP_PATCH))
        self.assertEqual(verdict, "deny")
        self.assertIn("tests/test_cart.py", reason)
        self.assertIn("Foreman blocked this edit", reason)
        self.assertCodexWords(reason)
        absolute = SKIP_PATCH.replace("tests/test_cart.py", os.path.join(self.root, "tests", "test_cart.py"))
        self.assertEqual(self.decision(self.tool("apply_patch", command=absolute))[0], "deny")
        self.assertIsNone(self.tool("apply_patch", command=PLAIN_PATCH))

    def test_a_workdir_in_the_call_is_where_the_command_is_inspected(self):
        # Codex 0.171.0 was measured passing the workdir as the hook's `cwd` and none in tool_input; a `workdir`
        # that does come in tool_input is where the command runs, so the gate reads that repository.
        clean = os.path.join(self.tmp, "clean")
        os.makedirs(clean)
        self.write("tests/test_cart.py", SKIPPED)
        self.git("add", "-A")
        for workdir in (self.root, os.path.relpath(self.root, clean)):
            out = codex.answer(self.payload("PreToolUse", tool_name="Bash", cwd=clean,
                                            tool_input={"command": "git commit -m x", "workdir": workdir}), {})
            verdict, reason = self.decision(out)
            self.assertEqual(verdict, "deny", workdir)
            self.assertIn("tests/test_cart.py:4", reason)
        # real paths of this machine: what is absolute differs between systems
        self.assertEqual(codex._where(clean, {"workdir": "c"}), os.path.join(clean, "c"))
        self.assertEqual(codex._where(clean, {"workdir": self.root}), os.path.normpath(self.root))
        self.assertEqual(codex._where(clean, {"workdir": 3}), clean)
        self.assertEqual(codex._where(clean, {}), clean)

    def test_edit_and_write_carrying_a_patch_are_read_as_patches(self):
        for name in ("Edit", "Write"):
            self.assertEqual(self.decision(self.tool(name, command=SKIP_PATCH))[0], "deny", name)
            self.assertIsNone(self.tool(name, command=PLAIN_PATCH), name)
            self.assertIsNone(self.tool(name, file_path="tests/test_cart.py", content="x = 1\n"), name)

    def test_edit_and_write_without_a_patch_get_the_writes_own_checks(self):
        hook = os.path.join(ROOT, "adapters", "hook.py")
        for name in ("Write", "Edit"):
            verdict, reason = self.decision(self.tool(name, file_path=hook, content="x"))
            self.assertEqual(verdict, "deny", name)
            self.assertIn("Foreman's own program", reason)
        self.assertEqual(self.decision(self.tool("Write", path=hook))[0], "deny")  # nothing readable: guards only
        self.assertEqual(self.decision(self.tool("Write", file_path="tests/test_cart.py", content=SKIPPED))[0],
                         "deny")
        self.assertEqual(self.decision(self.tool("Edit", file_path="tests/test_cart.py", old_string="def test_total():",
                                                 new_string=SKIP + "\ndef test_total():"))[0], "deny")
        self.assertEqual(self.decision(self.tool("Write", file_path=".codex/config.toml",
                                                 content="[features]\nhooks = false\n"))[0], "deny")
        # a value that is not a string is "not given", never a crash
        self.assertIsNone(self.tool("Edit", file_path="cart.py", old_string=3, new_string=None))
        self.assertIsNone(self.tool("Write", file_path=7, content="x"))

    def test_a_relative_workdir_with_no_cwd_is_not_inspected_blind(self):
        out = codex.answer(self.payload("PreToolUse", tool_name="Bash", cwd="",
                                        tool_input={"command": "git commit -m x", "workdir": "repo"}), {})
        verdict, reason = self.decision(out)
        self.assertEqual(verdict, "deny")
        self.assertIn("could not inspect", reason)
        self.assertIsNone(codex._where("", {"workdir": "repo"}))
        self.assertIsNone(codex.answer(self.payload("PreToolUse", tool_name="Bash", cwd="",
                                                    tool_input={"command": "ls", "workdir": "repo"}), {}))

    def test_a_patch_in_a_directory_that_does_not_exist_is_refused(self):
        out = codex.answer(self.payload("PreToolUse", tool_name="apply_patch", cwd=os.path.join(self.tmp, "gone"),
                                        tool_input={"command": PLAIN_PATCH}), {})
        self.assertEqual(self.decision(out)[0], "deny")

    def test_the_agent_cannot_turn_foreman_off(self):
        for command in ("codex features disable hooks", "codex --disable hooks exec 'git commit -m x'",
                        "codex exec -c features.hooks=false 'hi'", "codex plugin remove foreman",
                        "npx @openai/codex features disable hooks",
                        "sed -i '' '/hook.py/d' ~/.codex/hooks.json",
                        "printf '[features]\\nhooks = false\\n' >> ~/.codex/config.toml",
                        "rm -rf ~/.codex/plugins/cache/local/foreman"):
            self.assertEqual(self.decision(self.tool("Bash", command=command))[0], "deny", command)

    def test_reading_codex_settings_is_ordinary_work(self):
        for command in ("codex features list", "cat ~/.codex/config.toml", "grep hooks ~/.codex/hooks.json",
                        "jq . .codex/hooks.json", "codex --version",
                        "git commit --allow-empty -m 'codex features disable hooks is blocked'",
                        "git add .codex/hooks.json"):
            self.assertIsNone(self.tool("Bash", command=command), command)

    def test_a_patch_that_switches_hooks_off_in_codex_settings_is_denied(self):
        add = "*** Begin Patch\n*** Add File: .codex/config.toml\n+[features]\n+hooks = false\n*** End Patch\n"
        verdict, reason = self.decision(self.tool("apply_patch", command=add))
        self.assertEqual(verdict, "deny")
        self.assertIn("user's decision", reason)
        ok = "*** Begin Patch\n*** Add File: .codex/config.toml\n+model = \"x\"\n*** End Patch\n"
        self.assertIsNone(self.tool("apply_patch", command=ok))

    def test_a_patch_that_drops_or_deletes_foremans_hook_is_denied(self):
        hooks = json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command":
                                                           'python3 -I "/x/adapters/hook.py" codex || exit 1'}]}]}},
                           indent=1)
        self.write(".codex/hooks.json", hooks)
        line = next(l for l in hooks.splitlines() if "hook.py" in l)
        drop = "*** Begin Patch\n*** Update File: .codex/hooks.json\n@@\n-%s\n+%s\n*** End Patch\n" % (
            line, line.replace("hook.py", "nothing.py"))
        self.assertEqual(self.decision(self.tool("apply_patch", command=drop))[0], "deny")
        delete = "*** Begin Patch\n*** Delete File: .codex/hooks.json\n*** End Patch\n"
        self.assertEqual(self.decision(self.tool("apply_patch", command=delete))[0], "deny")

    def test_config_off_means_one_more_way_off_than_before(self):
        own = 'command = "python3 -I /x/adapters/hook.py codex || exit 1"'
        self.assertTrue(codex._config_off("", "[features]\nhooks = false\n"))
        self.assertTrue(codex._config_off("", "features.codex_hooks = false\n"))
        self.assertTrue(codex._config_off("", "allow_managed_hooks_only = true\n"))
        self.assertTrue(codex._config_off("", '[hooks.state."/a/hooks.json:stop:0:0"]\nenabled = false\n'))
        self.assertTrue(codex._config_off("", '[plugins."foreman@local"]\nenabled = false\n'))
        self.assertTrue(codex._config_off(own, ""))           # deleted
        self.assertTrue(codex._config_off(own, "model = 1"))  # dropped
        self.assertFalse(codex._config_off("[features]\nhooks = false\n", "[features]\nhooks = false\nx = 1\n"))
        self.assertFalse(codex._config_off("", '[mcp_servers.x]\nenabled = false\n'))
        self.assertFalse(codex._config_off(own, own + "\nmodel = 1"))
        self.assertFalse(codex._config_off("", ""))

    def test_settings_paths(self):
        for path in ("/home/u/.codex/config.toml", "/repo/.codex/hooks.json", "/etc/codex/requirements.toml",
                     "C:\\Users\\u\\.codex\\hooks.json"):
            self.assertTrue(codex._is_config(path), path)
        for path in ("/repo/codex/config.toml", "/repo/.codex/AGENTS.md", "/repo/hooks.json"):
            self.assertFalse(codex._is_config(path), path)

    def test_the_agent_cannot_touch_foremans_own_files(self):
        hook = os.path.join(ROOT, "adapters", "hook.py")
        self.assertEqual(self.decision(self.tool("Bash", command="python3 %s codex < fake.json" % hook))[0], "deny")
        self.assertEqual(self.decision(self.tool("Bash", command="cd /x && python3 adapters/hook.py codex"))[0], "deny")
        patch = "*** Begin Patch\n*** Update File: %s\n@@\n-a\n+b\n*** End Patch\n" % hook
        self.assertEqual(self.decision(self.tool("apply_patch", command=patch))[0], "deny")
        self.assertEqual(self.decision(self.tool("Bash", command="cat ~/.foreman/foreman-grants.json"))[0], "deny")

    def test_a_copy_installed_as_a_plugin_is_foremans_whole(self):
        installed = os.path.join(self.tmp, ".codex", "plugins", "cache", "local", "foreman", "local")
        h = codex.host({"PLUGIN_ROOT": installed})
        self.assertIn(installed, h.program_dirs)
        self.assertNotIn(ROOT, codex.host({}).program_dirs)  # a clone: only its code folders

    def test_the_agent_cannot_type_the_persons_allow_through_a_nested_session(self):
        self.assertEqual(self.decision(self.tool("Bash", command="codex exec 'foreman allow 3f2a'"))[0], "deny")
        self.assertEqual(self.decision(self.tool("Bash", command="echo 'foreman allow 3f2a' | codex exec -"))[0],
                         "deny")


class PersonCommands(CodexCase):
    def test_a_normal_prompt_gets_no_answer_and_starts_the_turn(self):
        self.assertIsNone(self.prompt("please fix the cart"))
        self.assertIsNone(self.prompt("foreman is blocking my commit, why?"))
        self.assertIsNone(self.prompt("foremanship"))
        self.assertEqual(core._load(codex.host(), "sess-1")["turn"], "turn-1")

    def test_only_the_exact_one_line_forms_are_commands(self):
        for text in ("foreman status looks wrong, why?", "foreman help me fix the failing commit",
                     "foreman allow me to explain", "foreman review this diff please", "foreman\nstatus",
                     "foreman status\nand also fix it", "foreman: status", "foreman status a b",
                     "please run foreman status", "foreman board"):
            self.assertIsNone(self.prompt(text), text)
        for text in ("foreman", "foreman status", "foreman status tests", "/foreman help", "  FOREMAN help  ",
                     "foreman allow", "foreman allow 3f2a"):
            self.assertEqual(self.prompt(text)["decision"], "block", text)

    def test_status_is_answered_without_the_model(self):
        out = self.prompt("foreman status")
        self.assertEqual(out["decision"], "block")
        self.assertIn("Foreman: CLEAN", out["reason"])
        self.assertEqual(core._load(codex.host(), "sess-1"), {})  # the person's command is not a turn
        self.assertIn("Foreman: CLEAN", self.prompt("foreman")["reason"])
        self.assertIn("Foreman: CLEAN", self.prompt("  /foreman status")["reason"])

    def test_help_names_the_commands_as_typed_in_codex(self):
        reason = self.prompt("foreman help")["reason"]
        self.assertIn("In Codex:", reason)
        self.assertIn("foreman status", reason)
        self.assertIn("not available in Codex yet", reason)
        self.assertCodexWords(reason)

    def test_a_hermes_only_subcommand_goes_to_the_model(self):
        self.assertIsNone(self.prompt("foreman board"))  # not one of Codex's forms: the model gets it
        self.assertIsNone(self.prompt("foreman merge"))

    def test_allowing_a_finding_is_not_available_in_codex(self):
        self.write("tests/test_cart.py", MARKED)
        self.git("add", "-A")
        self.assertEqual(self.decision(self.tool("Bash", command="git commit -m green"))[0], "deny")
        short_id = grants.pending()[0]["id"]
        for text in ("foreman allow %s" % short_id, "/foreman allow %s" % short_id):
            refused = self.prompt(text)["reason"]
            self.assertIn("not available in Codex yet", refused)
            self.assertNotIn("allowed", refused)
        self.assertEqual([e["id"] for e in grants.pending()], [short_id])
        self.assertEqual(self.decision(self.tool("Bash", command="git commit -m green"))[0], "deny")
        listing = self.prompt("foreman allow")["reason"]  # listing what waits stays
        self.assertIn(short_id, listing)
        self.assertIn("not available in Codex yet", listing)

    def test_no_codex_answer_advises_allowing_by_id(self):
        self.prompt("make the tests pass")
        self.assertIsNone(self.tool("Bash", command="python3 ../mark.py"))
        self.write("tests/test_cart.py", MARKED)  # what that command did
        self.git("add", "-A")
        texts = [self.decision(self.tool("Bash", command="git commit -m green"))[1],
                 self.decision(self.tool("Bash", command="codex exec 'foreman allow 3f2a'"))[1],
                 self.prompt("foreman status")["reason"], self.prompt("foreman help")["reason"],
                 self.prompt("foreman allow")["reason"], self.prompt("foreman allow 3f2a")["reason"]]
        self.prompt("go on")
        self.assertIsNone(self.tool("Bash", command="python3 ../mark.py"))
        self.write("tests/test_cart.py", MARKED + "\n")
        stop = self.stop(turn="turn-1")
        if stop:
            texts.append(stop["reason"])
        texts.append(codex.codex_words(core.reword(codex.host(), core._PERSON_ONLY % "/foreman allow <id>")))
        self.assertTrue(any("NEEDS YOUR OK" in t or "Marked" in t for t in texts))
        for text in texts:
            self.assertNotRegex(text, r"allow\s*<id>|allow \[id\]", text)
            self.assertCodexWords(text)

    def test_listing_with_nothing_waiting(self):
        self.assertIn("nothing is waiting", self.prompt("foreman allow")["reason"])


class Stop(CodexCase):
    def test_a_turn_that_left_a_skipped_test_is_sent_back_once(self):
        self.prompt("make the tests pass")
        self.assertIsNone(self.tool("Bash", command="python3 ../skip.py"))
        self.write("tests/test_cart.py", SKIPPED)  # what that command did
        out = self.stop()
        self.assertEqual(out["decision"], "block")
        self.assertIn("tests/test_cart.py:4", out["reason"])
        self.assertCodexWords(out["reason"])
        self.assertIsNone(self.stop(active=True))

    def test_a_turn_that_only_talked_and_an_unknown_event_get_no_answer(self):
        self.write("tests/test_cart.py", SKIPPED)  # the person's own work, and they keep editing
        self.prompt("say hello")
        self.write("cart.py", "x = 2\n")
        self.assertIsNone(self.stop())
        for event in ("SessionStart", "PostToolUse", "PermissionRequest", "SessionEnd"):
            self.assertIsNone(codex.answer(self.payload(event), {}), event)

    def test_a_file_written_through_a_patch_counts_for_the_turn(self):
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.makedirs(elsewhere)
        codex.answer(self.payload("UserPromptSubmit", prompt="go", cwd=elsewhere), {})
        self.write("tests/test_cart.py", SKIPPED)
        self.assertIsNone(codex.answer(self.payload("Stop", cwd=elsewhere), {}))
        patch = "*** Begin Patch\n*** Update File: %s\n@@\n-    return 2\n+    return 1\n*** End Patch\n" % (
            os.path.join(self.root, "cart.py"))
        self.assertIsNone(codex.answer(self.payload("PreToolUse", tool_name="apply_patch", cwd=elsewhere,
                                                    tool_input={"command": patch}), {}))
        self.write("cart.py", "def total():\n    return 1\n")  # the tool then writes it
        self.assertEqual(codex.answer(self.payload("Stop", cwd=elsewhere), {})["decision"], "block")


class Main(CodexCase):
    def run_main(self, data):
        raw = data if isinstance(data, (bytes, str)) else json.dumps(data)
        stdin = io.BytesIO(raw) if isinstance(raw, bytes) else io.StringIO(raw)
        stdout = io.StringIO()
        code = codex.main(stdin=stdin, stdout=stdout, env={})
        return code, stdout.getvalue()

    def test_no_decision_prints_nothing(self):
        self.assertEqual(self.run_main(self.payload("PreToolUse", tool_name="Bash", tool_input={"command": "ls"})),
                         (0, ""))
        self.assertEqual(self.run_main("[]"), (0, ""))
        self.assertEqual(self.run_main(""), (0, ""))

    def test_a_decision_is_one_json_object(self):
        code, out = self.run_main(self.payload("PreToolUse", tool_name="Bash", tool_input={"command": "gh pr merge 1"}))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_a_byte_order_mark_is_tolerated(self):
        raw = b"\xef\xbb\xbf" + json.dumps(self.payload("PreToolUse", tool_name="Bash",
                                                        tool_input={"command": "gh pr merge 1"})).encode()
        self.assertIn("deny", self.run_main(raw)[1])

    def test_input_that_is_not_json_is_an_error_that_blocks_nothing(self):
        self.assertEqual(self.run_main("{not json"), (1, ""))

    def test_when_the_adapter_fails_a_gated_command_is_refused(self):
        old = core.pre_shell
        core.pre_shell = lambda *a, **k: 1 / 0
        try:
            code, out = self.run_main(self.payload("PreToolUse", tool_name="Bash",
                                                   tool_input={"command": "git commit -m x"}))
            self.assertEqual(code, 0)
            answer = json.loads(out)["hookSpecificOutput"]
            self.assertEqual(answer["permissionDecision"], "deny")
            self.assertIn("could not inspect", answer["permissionDecisionReason"])
            self.assertEqual(self.run_main(self.payload("PreToolUse", tool_name="Bash",
                                                        tool_input={"command": "ls"})), (1, ""))
        finally:
            core.pre_shell = old


class EntryPoint(CodexCase):
    """``python3 -I adapters/hook.py codex``, as Codex's hooks.json runs it."""

    def run_hook(self, data):
        home = os.path.join(self.tmp, "home")
        os.makedirs(home, exist_ok=True)
        env = dict(os.environ, HOME=home, USERPROFILE=home, PYTHONPATH=os.path.join(self.tmp, "planted"))
        r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "adapters", "hook.py"), "codex"],
                           input=json.dumps(data).encode(), capture_output=True, env=env, cwd=self.root, timeout=60)
        return r.returncode, r.stdout.decode(), r.stderr.decode(), home

    def test_it_blocks_a_rigged_commit_and_keeps_its_state_in_the_home_directory(self):
        self.write("tests/test_cart.py", SKIPPED)
        self.git("add", "-A")
        code, out, err, home = self.run_hook(self.payload("PreToolUse", tool_name="Bash",
                                                          tool_input={"command": "git commit -m wip"}))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertTrue(os.path.isdir(os.path.join(home, ".foreman")))

    def test_a_person_command_is_answered(self):
        code, out, err, _home = self.run_hook(self.payload("UserPromptSubmit", prompt="foreman help"))
        self.assertEqual((code, err), (0, ""))
        self.assertIn("In Codex:", json.loads(out)["reason"])


class HooksFile(unittest.TestCase):
    def read(self, *parts):
        with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_every_hook_runs_the_entry_point_isolated(self):
        hooks = json.loads(self.read("adapters", "codex", "hooks.json"))
        self.assertEqual(set(hooks), {"hooks"})  # nothing Codex might not accept next to it
        hooks = hooks["hooks"]
        self.assertEqual(set(hooks), {"PreToolUse", "UserPromptSubmit", "Stop"})
        for event, groups in hooks.items():
            for group in groups:
                for hook in group["hooks"]:
                    # `|| exit 1`: Python answers a missing script with exit code 2, which Codex reads as "block";
                    # a broken installation must fail like any other hook error, not refuse every call.
                    self.assertEqual(hook["command"],
                                     'python3 -I "/path/to/foreman/adapters/hook.py" codex || exit 1', event)
                    self.assertEqual(hook["type"], "command")
        matcher = hooks["PreToolUse"][0]["matcher"]
        self.assertEqual(matcher, "^(Bash|apply_patch|Edit|Write)$")
        self.assertEqual(set(matcher[2:-2].split("|")), codex.SHELL_TOOLS | codex.PATCH_TOOLS)

    def test_the_readme_try_command_matches_the_hooks_file(self):
        readme = self.read("adapters", "codex", "README.md")
        self.assertIn("^(Bash|apply_patch|Edit|Write)\\$", readme)
        self.assertIn("adapters/hook.py codex || exit 1", readme)
        self.assertIn("--dangerously-bypass-hook-trust", readme)


if __name__ == "__main__":
    unittest.main()
