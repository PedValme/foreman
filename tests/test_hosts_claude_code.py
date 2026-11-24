"""Claude Code's adapter: its hook JSON in, its hook JSON out (``adapters/foreman_hosts/claude_code.py``), the
entry point as Claude Code runs it, and the plugin's files."""
import io
import json
import os
import subprocess
import sys
import unittest

from tests_support import ROOT, GitRepoCase

from foreman import grants
from foreman.detector import MARKER
from foreman_hosts import claude_code, core

# Built from parts, as in the other tests: Foreman reads its own test files, and a literal marker here would be
# a finding in this repository's pull requests.
SKIP = "@pytest.mark." + "skip"
SKIPPED = "import pytest\n\n\n" + SKIP + "\ndef test_total():\n    assert 1 + 1 == 2\n"
SKIP_EDIT = SKIP + "\ndef test_total():"
MARKED = ("import pytest\n\n\n" + SKIP + "  # " + MARKER + " flaky upstream\ndef test_total():\n"
          "    assert 1 + 1 == 2\n")
ATTENDED = {"CLAUDE_CODE_SESSION_ATTENDED": "1"}
UNATTENDED = {"CLAUDE_CODE_SESSION_ATTENDED": "0"}


class ClaudeCase(GitRepoCase):
    def setUp(self):
        super().setUp()
        self.write("tests/test_cart.py", "def test_total():\n    assert 1 + 1 == 2\n")
        self.write("cart.py", "def total():\n    return 2\n")
        self.commit("base")

    def payload(self, event, **more):
        data = {"session_id": "sess-1", "cwd": self.root, "prompt_id": "turn-1", "permission_mode": "default",
                "hook_event_name": event}
        data.update(more)
        return data

    def tool(self, name, env=ATTENDED, **tool_input):
        return claude_code.answer(self.payload("PreToolUse", tool_name=name, tool_input=tool_input), env)

    def prompt(self, text, env=ATTENDED, turn="turn-1"):
        return claude_code.answer(self.payload("UserPromptSubmit", prompt=text, prompt_id=turn), env)

    def stop(self, turn="turn-1"):
        return claude_code.answer(self.payload("Stop", stop_hook_active=False, prompt_id=turn), ATTENDED)

    def decision(self, out):
        return out["hookSpecificOutput"]["permissionDecision"], out["hookSpecificOutput"]["permissionDecisionReason"]


class PreToolUse(ClaudeCase):
    def test_other_tools_and_ordinary_commands_get_no_answer(self):
        self.assertIsNone(self.tool("Read", file_path=os.path.join(self.root, "cart.py")))
        self.assertIsNone(self.tool("Bash", command="ls -la", description="list"))
        self.assertIsNone(claude_code.answer(self.payload("PreToolUse", tool_name="Bash", tool_input="oops")))

    def test_a_commit_that_skips_a_test_is_denied_with_the_reason(self):
        self.write("tests/test_cart.py", SKIPPED)
        self.git("add", "-A")
        out = self.tool("Bash", command="git commit -m green")
        verdict, reason = self.decision(out)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PreToolUse")
        self.assertEqual(verdict, "deny")
        self.assertIn("tests/test_cart.py:4", reason)

    def test_powershell_is_a_shell_too(self):
        verdict, reason = self.decision(self.tool("PowerShell", command="gh pr merge 5"))
        self.assertEqual(verdict, "deny")
        self.assertIn("Merging is the user's decision", reason)

    def test_what_the_gate_cannot_inspect_asks_the_person(self):
        out = claude_code.answer(self.payload("PreToolUse", tool_name="Bash", cwd=os.path.join(self.tmp, "gone"),
                                              tool_input={"command": "git commit -m x"}), ATTENDED)
        self.assertEqual(self.decision(out)[0], "ask")

    def test_write_edit_and_multiedit_that_skip_a_test_are_denied(self):
        path = os.path.join(self.root, "tests", "test_cart.py")
        self.assertEqual(self.decision(self.tool("Write", file_path=path, content=SKIPPED))[0], "deny")
        self.assertEqual(self.decision(self.tool("Edit", file_path=path, old_string="def test_total():",
                                                 new_string=SKIP_EDIT))[0], "deny")
        edits = [{"old_string": "1 + 1", "new_string": "2 + 0"},
                 {"old_string": "def test_total():", "new_string": SKIP_EDIT}]
        self.assertEqual(self.decision(self.tool("MultiEdit", file_path=path, edits=edits))[0], "deny")
        self.assertIsNone(self.tool("MultiEdit", file_path=path, edits=edits[:1]))
        self.assertIsNone(self.tool("Write", file_path=os.path.join(self.root, "cart.py"), content="x = 1\n"))

    def test_the_agent_cannot_turn_foreman_off(self):
        for command in ("claude plugin disable foreman", "claude plugins uninstall foreman@foreman --scope user",
                        "jq '.disableAllHooks = true' ~/.claude/settings.json > /tmp/s && mv /tmp/s ~/.claude/settings.json",
                        "sed -i '' 's/\"foreman@foreman\": true/\"foreman@foreman\": false/' .claude/settings.local.json"):
            self.assertEqual(self.decision(self.tool("Bash", command=command))[0], "deny", command)
        for command in ("rm -rf ~/.claude/plugins/cache/foreman",
                        "cd ~/.claude/plugins/cache/foreman/foreman/0.1.0 && ls"):
            self.assertEqual(self.decision(self.tool("Bash", command=command))[0], "deny", command)

    def test_reading_claude_codes_settings_is_ordinary_work(self):
        for command in ("claude plugin list", "cat ~/.claude/settings.json", "grep foreman ~/.claude/settings.json",
                        "jq .enabledPlugins ~/.claude/settings.json 2>/dev/null", "ls ~/.claude/plugins/cache/foreman",
                        "git commit --allow-empty -m 'claude plugin disable foreman is blocked'"):
            self.assertIsNone(self.tool("Bash", command=command), command)

    def test_a_settings_write_that_turns_foreman_off_is_denied(self):
        settings = os.path.join(self.root, ".claude", "settings.json")
        self.assertEqual(self.decision(self.tool("Write", file_path=settings, content='{"disableAllHooks": true}'))[0],
                         "deny")
        self.assertEqual(self.decision(self.tool("Edit", file_path=settings, old_string='"foreman@foreman": true',
                                                 new_string='"foreman@foreman": false'))[0], "deny")
        self.assertIsNone(self.tool("Write", file_path=settings, content='{"model": "sonnet"}'))
        self.assertIsNone(self.tool("Write", file_path=settings, content='{"disableAllHooks": false}'))
        self.write(".claude/settings.json", '{"enabledPlugins": {"foreman@foreman": true}, "model": "a"}')
        verdict, reason = self.decision(self.tool("Edit", file_path=settings, old_string="true", new_string="false"))
        self.assertEqual(verdict, "deny")  # the fragment alone says nothing: the file as it will be does
        self.assertIn("user's decision", reason)
        self.assertIsNone(self.tool("Edit", file_path=settings, old_string='"a"', new_string='"b"'))

    def test_what_the_person_switched_off_themselves_can_still_be_edited(self):
        settings = os.path.join(self.root, ".claude", "settings.json")
        self.write(".claude/settings.json", '{"disableAllHooks": true, "model": "a"}')
        self.assertIsNone(self.tool("Edit", file_path=settings, old_string='"a"', new_string='"b"'))

    def test_the_agent_cannot_touch_the_installed_plugin(self):
        hook = os.path.join(ROOT, "adapters", "hook.py")
        self.assertEqual(self.decision(self.tool("Bash", command="python3 %s claude-code < fake.json" % hook))[0], "deny")
        self.assertEqual(self.decision(self.tool("Edit", file_path=hook, old_string="a", new_string="b"))[0], "deny")
        self.assertEqual(self.decision(self.tool("NotebookEdit", notebook_path=os.path.join(ROOT, "plugin", "x.ipynb"),
                                                 new_source="1"))[0], "deny")
        other = {"CLAUDE_PLUGIN_ROOT": os.path.join(self.tmp, "cache", "foreman")}
        target = os.path.join(self.tmp, "cache", "foreman", ".claude-plugin", "plugin.json")
        self.assertEqual(self.decision(self.tool("Write", env=other, file_path=target, content="{}"))[0], "deny")

    def test_a_copy_claude_code_installed_is_foremans_whole_and_a_clone_is_not(self):
        installed = os.path.join(self.tmp, ".claude", "plugins", "cache", "foreman", "foreman", "0.1.0")
        env = {"CLAUDE_PLUGIN_ROOT": installed}
        self.assertEqual(self.decision(self.tool("Write", env=env, file_path=os.path.join(installed, "README.md"),
                                                 content="x"))[0], "deny")
        self.assertEqual(self.decision(self.tool("Bash", env=env, command="ls %s" % installed))[0], "deny")
        # In a clone loaded with --plugin-dir, only the folders with code are Foreman's: its documents stay editable.
        self.assertIsNone(self.tool("Write", file_path=os.path.join(ROOT, "docs", "notes-for-a-test.md"), content="x"))

    def test_the_entry_point_run_by_hand_is_denied(self):
        out = self.tool("Bash", command="cd /somewhere && python3 adapters/hook.py claude-code < forged.json")
        self.assertEqual(self.decision(out)[0], "deny")

    def test_the_agent_cannot_type_the_persons_allow_through_a_nested_session(self):
        out = self.tool("Bash", command="claude -p '/foreman:allow 3f2a'")
        self.assertEqual(self.decision(out)[0], "deny")


class PersonCommands(ClaudeCase):
    def test_a_normal_prompt_gets_no_answer_and_starts_the_turn(self):
        self.assertIsNone(self.prompt("please fix the cart"))
        self.assertEqual(core._load(claude_code.host(ATTENDED), "sess-1")["turn"], "turn-1")

    def test_status_is_answered_without_the_model(self):
        out = self.prompt("/foreman:status")
        self.assertEqual(out["decision"], "block")
        self.assertIn("Foreman: CLEAN", out["reason"])
        self.assertEqual(core._load(claude_code.host(ATTENDED), "sess-1"), {})  # the person's command is not a turn

    def test_the_person_allows_a_marked_finding_only_in_an_attended_session(self):
        self.write("tests/test_cart.py", MARKED)
        self.git("add", "-A")
        self.assertEqual(self.decision(self.tool("Bash", command="git commit -m green"))[0], "deny")
        short_id = grants.pending()[0]["id"]
        refused = self.prompt("/foreman:allow %s" % short_id, env=UNATTENDED)
        self.assertIn("nobody is attending", refused["reason"])
        self.assertEqual(self.decision(self.tool("Bash", command="git commit -m green"))[0], "deny")
        self.assertIn("allowed %s" % short_id, self.prompt("/foreman:allow %s" % short_id)["reason"])
        self.assertIsNone(self.tool("Bash", command="git commit -m green"))

    def test_help_names_the_plugin_commands(self):
        reason = self.prompt("/foreman:help")["reason"]
        self.assertIn("/foreman:status", reason)
        self.assertIn("In Claude Code:", reason)


class Stop(ClaudeCase):
    def test_a_turn_that_left_a_skipped_test_is_sent_back_once(self):
        self.prompt("make the tests pass")
        self.assertIsNone(self.tool("Bash", command="perl -pi -e s/x/y/ tests/test_cart.py"))
        self.write("tests/test_cart.py", SKIPPED)  # what that command did
        out = self.stop()
        self.assertEqual(out["decision"], "block")
        self.assertIn("tests/test_cart.py:4", out["reason"])
        self.assertIsNone(self.stop())

    def test_a_turn_that_only_talked_and_an_unknown_event_get_no_answer(self):
        self.write("tests/test_cart.py", SKIPPED)  # the person's own work, and they keep editing
        self.prompt("say hello")
        self.write("cart.py", "x = 2\n")
        self.assertIsNone(self.stop())
        self.assertIsNone(claude_code.answer(self.payload("SessionStart"), ATTENDED))

    def test_a_file_written_through_the_edit_tool_counts_for_the_turn(self):
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.makedirs(elsewhere)
        claude_code.answer(self.payload("UserPromptSubmit", prompt="go", cwd=elsewhere), ATTENDED)
        self.write("tests/test_cart.py", SKIPPED)
        self.assertIsNone(claude_code.answer(self.payload("Stop", cwd=elsewhere), ATTENDED))
        self.assertIsNone(claude_code.answer(self.payload("PreToolUse", tool_name="Write", cwd=elsewhere, tool_input={
            "file_path": os.path.join(self.root, "cart.py"), "content": "x = 1\n"}), ATTENDED))
        self.write("cart.py", "x = 1\n")  # the tool then writes it
        out = claude_code.answer(self.payload("Stop", cwd=elsewhere), ATTENDED)
        self.assertEqual(out["decision"], "block")


class Main(ClaudeCase):
    def run_main(self, data, env=ATTENDED):
        raw = data if isinstance(data, (bytes, str)) else json.dumps(data)
        stdin = io.BytesIO(raw) if isinstance(raw, bytes) else io.StringIO(raw)
        stdout = io.StringIO()
        code = claude_code.main(stdin=stdin, stdout=stdout, env=env)
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

    def test_when_the_adapter_fails_a_gated_command_goes_to_the_person(self):
        old = core.pre_shell
        core.pre_shell = lambda *a, **k: 1 / 0
        try:
            code, out = self.run_main(self.payload("PreToolUse", tool_name="Bash",
                                                   tool_input={"command": "git commit -m x"}))
            self.assertEqual(code, 0)
            answer = json.loads(out)["hookSpecificOutput"]
            self.assertEqual(answer["permissionDecision"], "ask")
            self.assertIn("could not inspect", answer["permissionDecisionReason"])
            self.assertEqual(self.run_main(self.payload("PreToolUse", tool_name="Bash",
                                                        tool_input={"command": "ls"})), (1, ""))
        finally:
            core.pre_shell = old


class EntryPoint(ClaudeCase):
    """``python3 -I adapters/hook.py claude-code``, as the plugin's hooks.json runs it."""

    def run_hook(self, data, host="claude-code"):
        home = os.path.join(self.tmp, "home")
        os.makedirs(home, exist_ok=True)
        env = dict(os.environ, HOME=home, USERPROFILE=home, CLAUDE_CODE_SESSION_ATTENDED="0",
                   PYTHONPATH=os.path.join(self.tmp, "planted"))
        r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "adapters", "hook.py"), host],
                           input=json.dumps(data).encode(), capture_output=True, env=env, cwd=self.root, timeout=60)
        return r.returncode, r.stdout.decode(), r.stderr.decode(), home

    def test_it_blocks_a_rigged_commit_and_keeps_its_state_in_the_home_directory(self):
        self.write("tests/test_cart.py", SKIPPED)
        self.git("add", "-A")
        code, out, err, home = self.run_hook(self.payload("PreToolUse", tool_name="Bash",
                                                          tool_input={"command": "git commit -m green"}))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertTrue(os.path.isdir(os.path.join(home, ".foreman")))

    def test_a_planted_module_on_pythonpath_is_not_imported(self):
        planted = os.path.join(self.tmp, "planted")
        os.makedirs(planted)
        with open(os.path.join(planted, "json.py"), "w") as fh:
            fh.write("raise SystemExit('planted json imported')\n")
        code, out, err, _home = self.run_hook(self.payload("PreToolUse", tool_name="Bash",
                                                           tool_input={"command": "gh pr merge 2"}))
        self.assertEqual(code, 0, err)
        self.assertIn("deny", out)

    def test_an_unknown_host_is_an_error_that_blocks_nothing(self):
        code, out, err, _home = self.run_hook({}, host="nope")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("unknown host", err)


class PluginFiles(unittest.TestCase):
    def read(self, *parts):
        with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_the_manifest_points_at_files_that_exist(self):
        manifest = json.loads(self.read(".claude-plugin", "plugin.json"))
        self.assertEqual(manifest["name"], "foreman")
        self.assertTrue(os.path.isfile(os.path.join(ROOT, manifest["hooks"])))
        self.assertTrue(os.path.isdir(os.path.join(ROOT, manifest["commands"])))

    def test_every_hook_runs_the_entry_point_isolated(self):
        hooks = json.loads(self.read("adapters", "claude-code", "hooks.json"))["hooks"]
        self.assertEqual(set(hooks), {"PreToolUse", "UserPromptSubmit", "Stop"})
        for event, groups in hooks.items():
            for group in groups:
                for hook in group["hooks"]:
                    # `|| exit 1`: Python answers a missing script with exit code 2, which Claude Code reads as
                    # "block"; a broken installation must fail like any other hook error, not deny every call.
                    self.assertEqual(hook["command"],
                                     'python3 -I "${CLAUDE_PLUGIN_ROOT}/adapters/hook.py" claude-code || exit 1', event)
        matcher = hooks["PreToolUse"][0]["matcher"].split("|")
        self.assertEqual(set(matcher), claude_code.SHELL_TOOLS | {"Write", "Edit", "MultiEdit", "NotebookEdit"})

    def test_each_person_command_has_its_plugin_command_file(self):
        for name in core.PERSON_SUBCOMMANDS:
            text = self.read("adapters", "claude-code", "commands", name + ".md")
            self.assertIn("disable-model-invocation: true", text)

    def test_the_hermes_plugin_never_reads_the_adapters(self):
        for folder, _dirs, files in os.walk(os.path.join(ROOT, "plugin")):
            for name in files:
                if name.endswith((".py", ".yaml", ".json", ".js")):
                    text = self.read(os.path.relpath(os.path.join(folder, name), ROOT))
                    self.assertNotIn("foreman_hosts", text, name)
                    self.assertNotIn("adapters", text, name)


if __name__ == "__main__":
    unittest.main()
