"""The hooks, called the way Hermes calls them, on temporary git repositories."""
import importlib.util
import json
import os
import re
import unittest
from unittest import mock

from foreman import commands, detector, gate
from tests_support import GitRepoCase

SKIP = "@pytest.mark." + "skip"
GHP = "ghp_"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def terminal(command, workdir=None, **extra):
    args = {"command": command}
    if workdir:
        args["workdir"] = workdir
    return gate.on_pre_tool_call(tool_name="terminal", args=args, task_id="t1", session_id="s1", **extra)


class Parsing(unittest.TestCase):
    def kinds(self, command, cwd=os.sep + "w"):
        return [(a.kind, a.cwd, a.hooks_bypassed) for a in gate.parse_actions(command, cwd)]

    def test_segments_and_quotes(self):
        self.assertEqual(gate.segments('cd sub && git commit -m "a b; c" | cat'),
                         [["cd", "sub"], ["git", "commit", "-m", "a b; c"], ["cat"]])
        self.assertEqual(gate.segments(r"cd C:\repo\sub; git push"), [["cd", r"C:\repo\sub"], ["git", "push"]])

    def test_actions(self):
        w = os.sep + "w"
        sub = os.path.join(w, "sub")
        self.assertEqual(self.kinds("git status && git log"), [])
        self.assertEqual(self.kinds("cd sub && git commit -m x"), [("commit", sub, False)])
        self.assertEqual(self.kinds("git -C sub push origin HEAD"), [("push", sub, False)])
        self.assertEqual(self.kinds('bash -c "cd sub && git push"'), [("push", sub, False)])
        self.assertEqual(self.kinds("GIT_TRACE=1 git commit -q"), [("commit", w, False)])
        self.assertEqual(self.kinds("gh pr create --fill; gh pr merge 3 --squash"),
                         [("pr-create", w, False), ("pr-merge", w, False)])
        self.assertEqual(self.kinds("gh pr view 3"), [])
        self.assertEqual(self.kinds("git.exe commit -m x"), [("commit", w, False)])

    def test_hook_bypasses(self):
        self.assertTrue(self.kinds("git commit --no-verify -m x")[0][2])
        self.assertTrue(self.kinds("git commit -n -m x")[0][2])
        self.assertTrue(self.kinds('git commit -anm "x"')[0][2])
        self.assertTrue(self.kinds("git push --no-verify")[0][2])
        self.assertTrue(self.kinds("git -c core.hooksPath=/dev/null commit -m x")[0][2])
        self.assertFalse(self.kinds('git commit -m "-n"')[0][2])        # a message, not a flag
        self.assertFalse(self.kinds("git commit -mn")[0][2])            # message "n"
        self.assertFalse(self.kinds("git push -n")[0][2])               # on push, -n is --dry-run

    def test_commit_scope(self):
        scope = lambda c: gate._commit_scope(gate.parse_actions(c, os.sep + "w")[0])
        self.assertEqual(scope("git commit -m x"), (True, False))          # staged only
        self.assertEqual(scope("git commit -am x"), (False, False))        # tracked changes
        self.assertEqual(scope("git commit -m x app.py"), (False, False))  # pathspec
        self.assertEqual(scope("git add -A && git commit -m x"), (False, True))


class TerminalGate(GitRepoCase):
    def setUp(self):
        super().setUp()
        self.write("app.py", "x = 1\n")
        self.write("tests/test_app.py", "def test_x():\n    assert True\n")
        self.commit("base")

    def test_irrelevant_calls_return_none(self):
        self.assertIsNone(gate.on_pre_tool_call(tool_name="read_file", args={"path": "x"}))
        self.assertIsNone(terminal("ls -la", self.root))
        self.assertIsNone(terminal("git status", self.root))
        self.assertIsNone(gate.on_pre_tool_call(tool_name="terminal", args=None))

    def test_clean_commit_passes(self):
        self.write("app.py", "x = 2\n")
        self.git("add", "-A")
        self.assertIsNone(terminal("git commit -m 'change'", self.root))

    def test_commit_with_a_skipped_test_is_blocked(self):
        self.write("tests/test_app.py", SKIP + "\ndef test_x():\n    assert True\n")
        self.git("add", "-A")
        d = terminal("git commit -m 'skip it'", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("tests/test_app.py:1", d["message"])
        self.assertIn("[test-skipped]", d["message"])
        self.assertIn("Fix:", d["message"])

    def test_unstaged_changes_are_not_part_of_a_plain_commit(self):
        self.write("tests/test_app.py", SKIP + "\n")
        self.assertIsNone(terminal("git commit -m x", self.root))
        d = terminal("git add -A && git commit -m x", self.root)
        self.assertEqual(d["action"], "block")
        d = terminal("git commit -am x", self.root)
        self.assertEqual(d["action"], "block")

    def test_cd_and_workdir_are_followed(self):
        self.write("tests/test_app.py", SKIP + "\n")
        self.git("add", "-A")
        parent = os.path.dirname(self.root)
        self.assertEqual(terminal("cd repo && git commit -m x", parent)["action"], "block")
        self.assertEqual(terminal("git -C repo commit -m x", parent)["action"], "block")
        with mock.patch.object(gate, "session_cwd", return_value=self.root):
            self.assertEqual(terminal("git commit -m x")["action"], "block")

    def test_deleted_test_is_blocked_and_the_allow_line_escalates(self):
        self.git("rm", "-q", "tests/test_app.py")
        self.assertEqual(terminal("git commit -m 'drop test'", self.root)["action"], "block")
        msg = "replace\n\n" + detector.MARKER + " tests/test_app.py: merged into test_new.py"
        d = terminal("git commit -m '%s'" % msg, self.root)
        self.assertEqual(d["action"], "approve")
        self.assertIn("tests/test_app.py", d["message"])
        self.assertTrue(d["rule_key"].startswith("foreman:"))

    def test_marker_never_passes_alone(self):
        self.write("tests/test_app.py", SKIP + "  # " + detector.MARKER + " flaky upstream\n")
        self.git("add", "-A")
        d = terminal("git commit -m x", self.root)
        self.assertEqual(d["action"], "approve")
        self.write("app.py", "K = '" + GHP + "f" * 36 + "'\n")
        self.git("add", "-A")
        self.assertEqual(terminal("git commit -m x", self.root)["action"], "block")  # with a blocker, it blocks

    def test_no_verify_is_blocked_even_when_clean(self):
        self.write("app.py", "x = 3\n")
        self.git("add", "-A")
        d = terminal("git commit --no-verify -m x", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("hooks-bypassed", d["message"])

    def test_push_inspects_the_history(self):
        self.git("checkout", "-q", "-b", "feature")
        self.write("app.py", "K = '" + GHP + "g" * 36 + "'\n")
        self.commit("add")
        self.write("app.py", "x = 4\n")
        self.commit("remove")
        d = terminal("git push -u origin feature", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("secret-history", d["message"])

    def test_pr_merge_always_asks_a_person(self):
        self.git("checkout", "-q", "-b", "feature")
        self.write("app.py", "x = 5\n")
        self.commit("change")
        d = terminal("gh pr merge --squash", self.root)
        self.assertEqual(d["action"], "approve")
        self.assertIn("no blockers", d["message"])
        d = terminal("gh pr merge 42", self.root)
        self.assertEqual(d["action"], "approve")
        self.assertIn("cannot inspect", d["message"])

    def test_pr_create_blocks_on_the_branch(self):
        self.git("checkout", "-q", "-b", "feature")
        self.write("tests/test_app.py", "def test_x():\n    assert True\n" + "@pytest.mark." + "xfail\n")
        self.commit("xfail")
        self.assertEqual(terminal("gh pr create --fill --base main", self.root)["action"], "block")

    def test_check_entry_point(self):
        self.write("scripts/check.sh", "python -m unittest\n")
        self.write(detector.CONFIG_FILE, json.dumps({"check": "bash scripts/check.sh"}))
        self.commit("check")
        self.write("scripts/check.sh", "exit 0\n")
        self.git("add", "-A")
        d = terminal("git commit -m x", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("scripts/check.sh", d["message"])
        self.assertIn("check-changed", d["message"])

    def test_internal_errors_ask_a_person(self):
        with mock.patch.object(gate, "parse_actions", side_effect=RuntimeError("boom")), \
                self.assertLogs(gate.logger.name, "WARNING"):
            d = terminal("git commit -m x", self.root)
        self.assertEqual(d["action"], "approve")
        self.assertIn("boom", d["message"])
        with mock.patch.object(detector, "scan_worktree", side_effect=detector.GitError("git exploded")):
            d = terminal("git commit -m x", self.root)
        self.assertEqual(d["action"], "approve")
        self.assertIn("git exploded", d["message"])
        missing = os.path.join(self.tmp, "does-not-exist")
        d = terminal("git commit -m x", missing)
        self.assertEqual(d["action"], "approve")

    def test_outside_a_repository_nothing_is_published(self):
        outside = os.path.join(self.tmp, "plain")
        os.makedirs(outside)
        self.assertIsNone(terminal("git commit -m x", outside))


class WriteGate(GitRepoCase):
    def setUp(self):
        super().setUp()
        self.test_file = self.write("tests/test_app.py", "def test_x():\n    assert True\n")
        self.commit("base")

    def write_file(self, path, content):
        return gate.on_pre_tool_call(tool_name="write_file", args={"path": path, "content": content})

    def test_adding_a_skip_to_a_test_file_is_blocked(self):
        d = self.write_file(self.test_file, SKIP + "\ndef test_x():\n    assert True\n")
        self.assertEqual(d["action"], "block")
        self.assertIn("tests/test_app.py", d["message"])

    def test_existing_markers_and_non_test_files_pass(self):
        self.write("tests/test_app.py", SKIP + "\ndef test_x():\n    assert True\n")
        self.assertIsNone(self.write_file(self.test_file, SKIP + "\ndef test_x():\n    assert 1\n"))
        app = os.path.join(self.root, "app", "skips.py")
        self.assertIsNone(self.write_file(app, "# " + SKIP + "\n"))

    def test_relative_paths_resolve_against_the_session(self):
        with mock.patch.object(gate, "session_cwd", return_value=self.root):
            d = self.write_file("tests/test_new.py", "it." + "only('x', () => {})\n")
        self.assertEqual(d["action"], "block")

    def test_marked_write_asks_a_person(self):
        d = self.write_file(self.test_file, SKIP + "  # " + detector.MARKER + " needs a GPU\n")
        self.assertEqual(d["action"], "approve")

    def test_patch_replace_and_v4a(self):
        d = gate.on_pre_tool_call(tool_name="patch", args={
            "path": self.test_file, "old_string": "def test_x():", "new_string": SKIP + "\ndef test_x():"})
        self.assertEqual(d["action"], "block")
        v4a = ("*** Begin Patch\n*** Update File: %s\n@@\n-def test_x():\n+%s\n+def test_x():\n*** End Patch\n"
               % (self.test_file, "@unittest." + "skip('later')"))
        d = gate.on_pre_tool_call(tool_name="patch", args={"mode": "patch", "patch": v4a})
        self.assertEqual(d["action"], "block")
        self.assertIsNone(gate.on_pre_tool_call(tool_name="patch", args={
            "path": self.test_file, "old_string": "assert True", "new_string": "assert 1 == 1"}))


class PreVerify(GitRepoCase):
    def setUp(self):
        super().setUp()
        self.test_file = self.write("tests/test_app.py", "def test_x():\n    assert True\n")
        self.commit("base")

    def test_only_on_the_first_coding_attempt(self):
        self.write("tests/test_app.py", SKIP + "\n")
        self.assertIsNone(gate.on_pre_verify(coding=False, attempt=0, changed_paths=[self.test_file]))
        self.assertIsNone(gate.on_pre_verify(coding=True, attempt=1, changed_paths=[self.test_file]))
        d = gate.on_pre_verify(session_id="s", platform="cli", model="m", coding=True, attempt=0,
                               final_response="done", changed_paths=[self.test_file])
        self.assertEqual(d["action"], "continue")
        self.assertIn("tests/test_app.py:1", d["message"])

    def test_clean_tree_finishes(self):
        self.write("tests/test_app.py", "def test_x():\n    assert 2 > 1\n")
        self.assertIsNone(gate.on_pre_verify(coding=True, attempt=0, changed_paths=[self.test_file]))

    def test_deleted_test_files_are_reported(self):
        os.remove(self.test_file)
        d = gate.on_pre_verify(coding=True, attempt=0, changed_paths=[self.test_file])
        self.assertEqual(d["action"], "continue")
        self.assertIn("test-deleted", d["message"])


class SlashCommandAndTool(GitRepoCase):
    def setUp(self):
        super().setUp()
        self.write("app.py", "x = 1\n")
        self.commit("base")

    def test_status_and_help(self):
        out = commands.handle_slash("status " + self.root)
        self.assertIn("Foreman: CLEAN", out)
        self.write("tests/test_a.py", SKIP + "\n")
        out = commands.handle_slash("status " + self.root)
        self.assertIn("Foreman: BLOCKED", out)
        self.assertIn("tests/test_a.py:1", out)
        self.assertIn("/foreman", commands.handle_slash("help"))
        self.assertIn("Unknown subcommand", commands.handle_slash("review"))
        with mock.patch.object(commands, "session_cwd", return_value=self.root):
            self.assertIn("Foreman: BLOCKED", commands.handle_slash(""))

    def test_tool_returns_json(self):
        self.write("tests/test_a.py", SKIP + "\n")
        data = json.loads(commands.foreman_check_tool({"path": self.root}))
        self.assertEqual(data["verdict"], "BLOCKED")
        self.assertEqual(data["blockers"][0]["rule"], "test-skipped")
        data = json.loads(commands.foreman_check_tool({"path": os.path.join(self.tmp)}))
        self.assertEqual(data["verdict"], "NO_REPOSITORY")


class Registration(unittest.TestCase):
    """register(ctx) registers exactly what plugin.yaml declares, and only the /foreman command."""

    def test_register_matches_the_manifest(self):
        spec = importlib.util.spec_from_file_location("foreman_plugin_under_test", os.path.join(ROOT, "__init__.py"),
                                                      submodule_search_locations=[ROOT])
        module = importlib.util.module_from_spec(spec)
        import sys
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
            recorded = {"hooks": [], "tools": [], "commands": []}
            ctx = mock.Mock()
            ctx.register_hook.side_effect = lambda name, cb, **kw: recorded["hooks"].append(name)
            ctx.register_tool.side_effect = lambda **kw: recorded["tools"].append(kw["name"])
            ctx.register_command.side_effect = lambda name, *a, **kw: recorded["commands"].append(name)
            module.register(ctx)
        finally:
            sys.modules.pop(spec.name, None)
        with open(os.path.join(ROOT, "plugin.yaml"), encoding="utf-8") as fh:
            manifest = fh.read()

        def declared(key):
            block = re.search(r"(?m)^%s:\n((?:  - .+\n)+)" % key, manifest)
            return sorted(re.findall(r"- (\S+)", block.group(1))) if block else []

        self.assertEqual(sorted(recorded["hooks"]), declared("provides_hooks"))
        self.assertEqual(sorted(recorded["tools"]), declared("provides_tools"))
        self.assertEqual(recorded["commands"], ["foreman"])


if __name__ == "__main__":
    unittest.main()
