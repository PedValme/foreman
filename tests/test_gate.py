"""The hooks, called the way Hermes calls them, on temporary git repositories."""
import importlib.util
import json
import os
import re
import sys
import time
import types
import unittest
from unittest import mock

from foreman import commands, detector, gate, grants
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

    def test_deleted_test_is_blocked_and_the_allow_line_waits_for_the_user(self):
        self.git("rm", "-q", "tests/test_app.py")
        d = terminal("git commit -m 'drop test'", self.root)
        self.assertEqual(d["action"], "block")
        self.assertNotIn(detector.MARKER, d["message"])  # the marker is not advertised on ordinary blocks
        msg = "replace\n\n" + detector.MARKER + " tests/test_app.py: merged into test_new.py"
        d = terminal("git commit -m '%s'" % msg, self.root)
        self.assertEqual(d["action"], "block")
        short_id = re.search(r"id ([0-9a-f]{8})", d["message"]).group(1)
        self.assertIn("/foreman allow", d["message"])
        self.assertIn(short_id, commands.handle_slash("allow"))
        self.assertIn("allowed", commands.handle_slash("allow " + short_id))
        self.assertIsNone(terminal("git commit -m '%s'" % msg, self.root))

    def test_marker_never_passes_alone_in_any_approval_mode(self):
        marked = SKIP + "  # " + detector.MARKER + " flaky upstream"
        self.write("tests/test_app.py", marked + "\n")
        self.git("add", "-A")
        d = terminal("git commit -m x", self.root)
        self.assertEqual(d["action"], "block")  # not "approve": YOLO or approvals off would pass that alone
        short_id = re.search(r"id ([0-9a-f]{8})", d["message"]).group(1)
        self.assertIn("You cannot allow it yourself", d["message"])
        commands.handle_slash("allow " + short_id)
        self.assertIsNone(terminal("git commit -m x", self.root))
        # The grant covers that exact line: changing it is checked again.
        self.write("tests/test_app.py", marked + " and more\n")
        self.git("add", "-A")
        self.assertEqual(terminal("git commit -m x", self.root)["action"], "block")
        # With another blocker it blocks either way.
        self.write("tests/test_app.py", marked + "\n")
        self.write("app.py", "K = '" + GHP + "f" * 36 + "'\n")
        self.git("add", "-A")
        self.assertEqual(terminal("git commit -m x", self.root)["action"], "block")

    def test_grants_expire(self):
        self.write("tests/test_app.py", SKIP + "  # " + detector.MARKER + " flaky\n")
        self.git("add", "-A")
        short_id = re.search(r"id ([0-9a-f]{8})", terminal("git commit -m x", self.root)["message"]).group(1)
        commands.handle_slash("allow " + short_id)
        later = time.time() + grants.GRANT_TTL_SECONDS + 60
        with mock.patch.object(grants.time, "time", return_value=later):
            self.assertEqual(terminal("git commit -m x", self.root)["action"], "block")

    def test_unknown_or_short_ids_are_refused(self):
        self.assertIn("No pending", commands.handle_slash("allow deadbeef"))
        self.assertIn("at least 4", commands.handle_slash("allow ab"))
        self.assertIn("nothing is waiting", commands.handle_slash("allow"))

    def test_the_exception_store_is_off_limits(self):
        store = grants.store_path()
        self.assertEqual(gate.on_pre_tool_call(tool_name="write_file", args={"path": store, "content": "{}"})["action"],
                         "block")
        self.assertEqual(terminal("echo {} > %s" % store, self.root)["action"], "block")

    def test_no_verify_is_blocked_even_when_clean(self):
        self.write("app.py", "x = 3\n")
        self.git("add", "-A")
        d = terminal("git commit --no-verify -m x", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("skips the repository's git hooks", d["message"])

    def test_block_messages_are_short(self):
        self.write("tests/test_app.py", SKIP + "\n")
        self.git("add", "-A")
        d = terminal("git commit -m x", self.root)
        lines = d["message"].splitlines()
        self.assertEqual(lines[0], "Foreman blocked `git commit`.")
        self.assertEqual(len(lines), 3)  # headline, finding, its fix

    def test_earlier_segments_that_change_the_tree_are_refused(self):
        for command in ("git rm -q tests/test_app.py && git commit -m x",
                        "git mv tests/test_app.py archive.py && git commit -m x",
                        "rm tests/test_app.py && git commit -am x",
                        "sed -i s/True/False/ tests/test_app.py && git commit -am x",
                        "python fix.py; git push",
                        "git commit -am x && git push",
                        'bash -c "rm -f app.py && git commit -am x"'):
            d = terminal(command, self.root)
            self.assertEqual(d["action"], "block", command)
            self.assertIn("as its own command", d["message"], command)
        for command in ("git add -A && git commit -m x", "cd . && git status && git commit -m x",
                        "echo go; git diff --stat; git commit -m x", "FOO=1 git commit -m x",
                        "git commit -m x && echo done"):
            self.write("app.py", "x = %d\n" % len(command))
            self.git("add", "-A")
            self.assertIsNone(terminal(command, self.root), command)

    def test_push_of_several_branches_asks_a_person(self):
        d = terminal("git push --all origin", self.root)
        self.assertEqual(d["action"], "approve")
        self.assertIn("more than one branch", d["message"])

    def test_cmd_c_is_followed(self):
        self.write("tests/test_app.py", SKIP + "\n")
        self.git("add", "-A")
        self.assertEqual(terminal("cmd /c git commit -m x", self.root)["action"], "block")

    def test_an_unlocated_command_outside_a_repository_is_blocked(self):
        outside = os.path.join(self.tmp, "plain")
        os.makedirs(outside)
        with mock.patch.object(gate, "session_cwd", return_value=outside):
            d = terminal("git commit -m x")
        self.assertEqual(d["action"], "block")
        self.assertIn("workdir", d["message"])

    def test_the_terminal_recorded_session_directory_is_used(self):
        fake = types.ModuleType("tools.terminal_tool")
        fake.get_session_cwd = lambda key: self.root if key == "task-7" else None
        with mock.patch.dict(sys.modules, {"tools.terminal_tool": fake, "tools": types.ModuleType("tools")}):
            self.assertEqual(gate.session_cwd("task-7"), self.root)
            self.write("tests/test_app.py", SKIP + "\n")
            self.git("add", "-A")
            d = gate.on_pre_tool_call(tool_name="terminal", args={"command": "git commit -m x"}, task_id="task-7")
            self.assertEqual(d["action"], "block")
            self.assertIn("Foreman: BLOCKED", commands.handle_slash("status", session_key="task-7"))

    def test_output_redirection_makes_a_safe_segment_unsafe(self):
        for command in ("git status > tests/test_app.py && git commit -m x",
                        "echo x >> tests/test_app.py; git commit -am x",
                        "git diff --output=p.diff && git commit -m x"):
            self.assertIn("as its own command", terminal(command, self.root)["message"], command)
        self.write("app.py", "x = 11\n")
        self.git("add", "-A")
        for command in ("git status > /dev/null && git commit -m x", "git log -1 2>&1 && git commit -m x",
                        'echo "a > b" && git commit -m x'):
            self.assertIsNone(terminal(command, self.root), command)

    def test_an_absolute_workdir_is_never_replaced(self):
        outside = os.path.join(self.tmp, "plain")
        os.makedirs(outside)
        with mock.patch.object(gate, "session_cwd", side_effect=AssertionError("must not be consulted")):
            self.assertIsNone(terminal("git commit -m x", outside))

    def test_grants_for_a_file_do_not_cover_later_changes(self):
        self.write("scripts/check.sh", "python -m unittest\n")
        self.write(detector.CONFIG_FILE, json.dumps({"check": "bash scripts/check.sh"}))
        self.commit("check")
        self.write("scripts/check.sh", "python -m unittest -q\n")
        self.git("add", "-A")
        msg = "tune\n\n" + detector.MARKER + " scripts/check.sh: quieter output"
        d = terminal("git commit -m '%s'" % msg, self.root)
        commands.handle_slash("allow " + re.search(r"id ([0-9a-f]{8})", d["message"]).group(1))
        self.assertIsNone(terminal("git commit -m '%s'" % msg, self.root))
        self.write("scripts/check.sh", "exit 0\n")
        self.git("add", "-A")
        self.assertEqual(terminal("git commit -m '%s'" % msg, self.root)["action"], "block")

    def test_a_grant_does_not_follow_the_marker_to_another_test(self):
        marked = SKIP + "  # " + detector.MARKER + " flaky"
        self.write("tests/test_app.py", marked + "\ndef test_x():\n    assert True\n")
        self.git("add", "-A")
        d = terminal("git commit -m x", self.root)
        commands.handle_slash("allow " + re.search(r"id ([0-9a-f]{8})", d["message"]).group(1))
        self.assertIsNone(terminal("git commit -m x", self.root))
        self.write("tests/test_app.py", "def test_x():\n    assert True\n\n\n" + marked + "\ndef test_y():\n    pass\n")
        self.git("add", "-A")
        self.assertEqual(terminal("git commit -m x", self.root)["action"], "block")

    def test_a_damaged_store_never_grants_or_raises(self):
        for content in ('{"granted": [], "pending": "x"}', '{"granted": {"abc": "str"}}', "[1, 2]", "not json"):
            os.makedirs(grants.store_dir(), exist_ok=True)
            with open(grants.store_path(), "w", encoding="utf-8") as fh:
                fh.write(content)
            self.write("tests/test_app.py", SKIP + "  # " + detector.MARKER + "\n")
            self.git("add", "-A")
            d = terminal("git commit -m x", self.root)
            self.assertEqual(d["action"], "block", content)
            listing = commands.handle_slash("allow")
            self.assertNotIn("Foreman failed", listing)
            self.assertIn("tests/test_app.py", listing)

    def test_store_guard_spellings(self):
        store = grants.store_path()
        for spelling in ("Foreman-Grants.JSON. ", "foreman-grants.json" + os.sep + ".", "foreman-grants.json\\. ",
                         "foreman-grants.json/"):
            path = os.path.join(os.path.dirname(store), spelling)
            d = gate.on_pre_tool_call(tool_name="write_file", args={"path": path, "content": "{}"})
            self.assertEqual(d and d["action"], "block", spelling)
        self.assertEqual(terminal("cat FOREMAN-GRANTS.json", self.root)["action"], "block")

    def test_the_hook_deadline_covers_the_repository_lookup(self):
        self.write("app.py", "x = 9\n")
        self.git("add", "-A")
        with mock.patch.object(gate, "HOOK_BUDGET_SECONDS", -1):
            d = terminal("git commit -m x", self.root)
        self.assertEqual(d["action"], "approve")
        self.assertIn("time budget", d["message"])

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


class SessionDirectory(GitRepoCase):
    """Real sessions: the process runs in the user's repository, Hermes's configured directory is the home folder
    or the Hermes home, and the Hermes home may itself be a git repository."""

    def setUp(self):
        super().setUp()
        self.write("app.py", "x = 1\n")
        self.commit("base")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        # A Hermes home that is a git repository, with a dirty skip so picking it would show.
        self.hermes = os.path.join(self.tmp, "hermes-home")
        os.makedirs(os.path.join(self.hermes, "tests"))
        self.git("init", "-q", cwd=self.hermes)
        with open(os.path.join(self.hermes, "tests", "test_h.py"), "w", encoding="utf-8") as fh:
            fh.write(SKIP + "\n")

    def fake_hermes(self, configured, recorded=None):
        runtime = types.ModuleType("agent.runtime_cwd")
        runtime.resolve_agent_cwd = lambda: configured
        constants = types.ModuleType("hermes_constants")
        constants.get_hermes_home = lambda: self.hermes
        terminal_tool = types.ModuleType("tools.terminal_tool")
        terminal_tool.get_session_cwd = lambda key: recorded if key == "s1" else None
        return mock.patch.dict(sys.modules, {"agent": types.ModuleType("agent"), "agent.runtime_cwd": runtime,
                                             "hermes_constants": constants, "tools": types.ModuleType("tools"),
                                             "tools.terminal_tool": terminal_tool})

    def norm(self, p):
        return os.path.normpath(p)

    def test_on_the_cli_the_process_directory_comes_before_the_configured_one(self):
        with self.fake_hermes(self.home), mock.patch.object(gate.os, "getcwd", return_value=self.root):
            self.assertEqual([p for p, _ in gate.cwd_candidates(platform="cli")],
                             [self.norm(self.root), self.norm(self.home)])
            out = commands.handle_slash("status", session_id="s1", platform="cli")
            self.assertIn("Foreman: CLEAN", out)
            self.assertIn("(from the current directory)", out)
            self.assertEqual(json.loads(commands.foreman_check_tool({}))["verdict"], "CLEAN")

    def test_the_hermes_home_is_never_picked_even_when_it_is_a_repository(self):
        inside = os.path.join(self.hermes, "tests")
        with self.fake_hermes(inside), mock.patch.object(gate.os, "getcwd", return_value=self.root):
            self.assertEqual(gate.session_cwd(platform="cli"), self.norm(self.root))
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.makedirs(elsewhere)
        with self.fake_hermes(self.hermes), mock.patch.object(gate.os, "getcwd", return_value=elsewhere):
            out = commands.handle_slash("status", platform="cli")
        self.assertIn("not inside a git repository", out)
        self.assertIn(self.norm(elsewhere), out)
        self.assertNotIn(self.norm(self.hermes), out)

    def test_on_a_messaging_platform_the_process_directory_is_ignored(self):
        with self.fake_hermes(self.home), mock.patch.object(gate.os, "getcwd", return_value=self.root):
            self.assertEqual([p for p, _ in gate.cwd_candidates(platform="telegram")], [self.norm(self.home)])
            self.assertIn("not inside a git repository", commands.handle_slash("status", platform="telegram"))

    def test_the_recorded_terminal_directory_wins_and_needs_no_hint(self):
        other = os.path.join(self.tmp, "other")
        os.makedirs(other)
        self.git("init", "-q", cwd=other)
        with self.fake_hermes(self.home, recorded=self.root), mock.patch.object(gate.os, "getcwd", return_value=other):
            out = commands.handle_slash("status", session_id="s1", platform="cli")
        self.assertIn("Repository: %s\n" % self.norm(self.root), out)

    def test_an_explicit_path_is_accepted(self):
        with self.fake_hermes(self.home), mock.patch.object(gate.os, "getcwd", return_value=self.home):
            out = commands.handle_slash("status " + self.root, platform="cli")
        self.assertIn("Foreman: CLEAN", out)
        self.assertNotIn("(from", out)


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

    def test_marked_write_waits_for_the_user(self):
        content = SKIP + "  # " + detector.MARKER + " needs a GPU\n"
        d = self.write_file(self.test_file, content)
        self.assertEqual(d["action"], "block")
        short_id = re.search(r"id ([0-9a-f]{8})", d["message"]).group(1)
        commands.handle_slash("allow " + short_id)
        self.assertIsNone(self.write_file(self.test_file, content))
        # The same exception then covers the commit of that line.
        self.write("tests/test_app.py", content)
        self.git("add", "-A")
        self.assertIsNone(terminal("git commit -m x", self.root))

    def test_conditional_skip_in_a_new_test_file_passes(self):
        cond = "@pytest.mark." + "skipif(sys.platform == 'win32', reason='posix')\n"
        new = os.path.join(self.root, "tests", "test_posix.py")
        self.assertIsNone(self.write_file(new, cond + "def test_p():\n    assert True\n"))
        self.assertEqual(self.write_file(self.test_file, cond + "def test_x():\n    assert True\n")["action"], "block")
        constant = "@pytest.mark." + "skip" + "if(True, reason='later')\n"
        newer = os.path.join(self.root, "tests", "test_later.py")
        self.assertEqual(self.write_file(newer, constant + "def test_l():\n    assert True\n")["action"], "block")

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
        with mock.patch.object(commands, "locate", return_value=(self.root, gate.RECORDED)):
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
