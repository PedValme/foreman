"""The hooks, called the way Hermes calls them, on temporary git repositories."""
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import types
import unittest
from unittest import mock

from tests_support import PLUGIN_DIR, GitRepoCase  # first: it puts plugin/ on sys.path
from foreman import commands, detector, gate, grants

SKIP = "@pytest.mark." + "skip"
GHP = "ghp_"


class _Both:
    """Two context managers entered as one."""

    def __init__(self, first, second):
        self.first, self.second = first, second

    def __enter__(self):
        self.first.__enter__()
        self.second.__enter__()
        return self

    def __exit__(self, *exc):
        self.second.__exit__(*exc)
        return self.first.__exit__(*exc)


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

    def test_a_push_foreman_cannot_resolve_asks_a_person(self):
        # Found in the final review: each of these published a rigged branch while the clean current one was read.
        for command in ("git push origin 'refs/heads/*:refs/heads/*'", "git push origin 'refs/heads/rig*:refs/heads/main*'"):
            d = terminal(command, self.root)
            self.assertEqual(d["action"], "approve", command)
            self.assertIn("cannot resolve", d["message"])
        self.git("config", "remote.origin.push", "refs/heads/rig:refs/heads/rig")
        d = terminal("git push origin", self.root)
        self.assertEqual(d["action"], "approve")
        self.assertIn("what the configuration adds", d["message"])
        self.git("config", "--unset", "remote.origin.push")
        self.git("config", "push.default", "matching")
        self.assertEqual(terminal("git push", self.root)["action"], "approve")
        self.git("config", "--unset", "push.default")
        self.git("config", "remote.origin.mirror", "true")
        self.assertEqual(terminal("git push origin", self.root)["action"], "approve")
        self.git("config", "--unset", "remote.origin.mirror")
        # Found in the review of that change: the same settings given inline with `git -c`.
        for command in ("git -c remote.origin.push=refs/heads/rig:refs/heads/main push origin",
                        "git -c push.default=matching push origin"):
            self.assertEqual(terminal(command, self.root)["action"], "approve", command)
        # Deleting a remote branch publishes nothing, even when the local one is gone.
        self.assertIsNone(terminal("git push origin --delete gone", self.root))

    def test_a_local_branch_as_upstream_is_not_the_base(self):
        # Found in the final review: `git branch -u rig2` at HEAD made the pushed range empty.
        self.git("checkout", "-q", "-b", "rig")
        self.write("tests/test_app.py", SKIP + "\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "rig", "--no-verify")
        self.git("branch", "rig2")
        self.git("branch", "-u", "rig2")
        d = terminal("git push origin HEAD", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("test-skipped", d["message"])

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

    def test_pr_merge_by_the_agent_is_always_refused(self):
        # Never `approve`: an "always" or session answer, or YOLO, would let every later merge through.
        self.git("checkout", "-q", "-b", "feature")
        self.write("app.py", "x = 5\n")
        self.commit("change")
        for command, n in (("gh pr merge --squash", "<n>"), ("gh pr merge 42", "42"),
                           ("gh pr merge -t title --squash #42", "42"),
                           ("gh -R acme/w pr merge https://github.com/acme/w/pull/9 --auto", "9"),
                           ("bash -c 'gh pr merge 42'", "42"), ("git push && gh pr merge 42", "42"),
                           ('pwsh -Command "gh pr merge 42"', "42"), ('pwsh -NoProfile -Command "cd x; gh pr merge 42"',
                                                                       "42"),
                           ('cmd /c "gh pr merge 42"', "42"), ('cmd /s /c "gh pr merge 42"', "42"),
                           ("timeout 60 gh pr merge 42", "42"), ("timeout -k 5 60 gh pr merge 42", "42"),
                           ("nice -n 5 gh pr merge 42", "42"), ("sudo -u me gh pr merge 42", "42"),
                           ("env -i PATH=/bin gh pr merge 42", "42"), ("echo 42 | xargs -n 1 gh pr merge", "<n>"),
                           ("gh pr -R o/r merge 42", "42"), ("gh pr --repo o/r merge 42", "42"),
                           ("eval gh pr merge 42", "42"), ("eval 'gh pr merge 42'", "42"),
                           ("some-wrapper --flag gh pr merge 42", "42")):
            d = terminal(command, self.root)
            self.assertEqual(d, {"action": "block", "message": "Merging is the user's decision. Ask them to run "
                                                               "`/foreman merge %s`." % n}, command)
        self.assertNotIn("rule_key", terminal("gh pr merge 42"))  # no workdir, no repository: still refused

    def test_braces_group_at_a_words_start_and_are_text_inside_one(self):
        for command in ("{ git commit -m x; }", "{git commit -m x}", "x && {git commit -m x;}"):
            self.assertEqual([a.kind for a in gate.parse_actions(command, self.root)], ["commit"], command)
        self.assertEqual(gate.segments("gh api repos/{owner}/{repo}/pulls/7 a{b}c ${HOME}"),
                         [["gh", "api", "repos/{owner}/{repo}/pulls/7", "a{b}c", "${HOME}"]])

    def test_a_merge_through_gh_api_is_refused_like_gh_pr_merge(self):
        with open(os.path.join(self.root, "q.graphql"), "w", encoding="utf-8") as fh:
            fh.write("mutation { mergePullRequest(input: {pullRequestId: \"x\"}) { clientMutationId } }")
        with open(os.path.join(self.root, "read.graphql"), "w", encoding="utf-8") as fh:
            fh.write("query { viewer { login } }")
        with open(os.path.join(self.root, "body.json"), "w", encoding="utf-8") as fh:
            fh.write('{"query": "mutation { merge\\u0050ullRequest(input: {}) { x } }"}')
        with open(os.path.join(self.root, "deep.json"), "w", encoding="utf-8") as fh:
            fh.write("[" * 100000 + "]" * 100000)
        with open(os.path.join(self.root, "read.json"), "w", encoding="utf-8") as fh:
            fh.write('{"query": "query { viewer { login } }"}')
        with open(os.path.join(self.root, "big.graphql"), "w", encoding="utf-8") as fh:
            fh.write("#" * (1 << 20) + "\nmutation { mergePullRequest(input: {}) { x } }")
        for command, n in (("gh api -X PUT repos/acme/w/pulls/42/merge", "42"),
                           ("gh api --method PUT /repos/acme/w/pulls/42/merge -f merge_method=squash", "42"),
                           ("gh api -XPUT repos/{owner}/{repo}/pulls/42/merge", "42"),
                           ("gh api --method=put https://api.github.com/repos/acme/w/pulls/42/merge", "42"),
                           ("gh api repos/acme/w/pulls/42/merge -f commit_title=x", "42"),  # a field makes it POST
                           ("gh api -X POST repos/acme/w/merges -f base=main -f head=feature", "<n>"),
                           ("gh api graphql -f query='mutation { mergePullRequest(input: {}) { x } }'", "<n>"),
                           ("gh api graphql -F query=@q.graphql", "<n>"),
                           ("gh api graphql -f query='mutation { enablePullRequestAutoMerge(input: {}) { x } }'",
                            "<n>"),
                           ("gh api graphql --input -", "<n>"),  # a query Foreman cannot see
                           ("gh api graphql -F query=@missing.graphql", "<n>"),
                           ("bash -c 'gh api -X PUT repos/a/b/pulls/7/merge'", "7"),
                           ("gh api -X PUT https://h.example/repos/o/r/pulls/42/merge-async", "42"),  # or queued
                           ("gh api -iX PUT https://h.example/repos/o/r/pulls/42/merge", "42"),  # switches combined
                           ("gh api -X=PUT repos/o/r/pulls/42/merge", "42"),
                           ("gh api graphql --input body.json", "<n>"),  # the mutation's name escaped in JSON
                           ("gh api https://h.example/api/graphql --input body.json", "<n>"),  # GHES's path
                           ("gh api graphql -F query=@big.graphql", "<n>"),  # past what Foreman reads
                           ("cd / && gh api graphql -F query=@q.graphql", "<n>"),  # not there: unseen
                           ("gh api -i=f -X PUT https://h.example/repos/o/r/pulls/42/merge", "42"),  # a switch's value
                           ("{gh api -X PUT https://h.example/repos/o/r/pulls/42/merge}", "42"),  # zsh drops the }
                           ("(cd plugin); gh api graphql -F query=@q.graphql", "<n>"),  # after a subshell: unseen
                           ("gh api HTTPS://h.example/graphql --input -", "<n>"),
                           ("gh api graphql --input deep.json", "<n>"),  # too deep to decode: unseen
                           ("{gh pr merge 42}", "42"), ("{gh api -X PUT repos/o/r/pulls/42/merge}", "42"),  # zsh
                           ("gh api </dev/null -X PUT https://h.example/repos/o/r/pulls/42/merge", "42"),
                           ("false && cd plugin; gh api graphql -F query=@q.graphql", "<n>"),  # a cd that may not run
                           ("gh api -X PUT https://h.example/repos/o/r/pulls/42/\\merge", "42"),
                           ("gh -R acme/w api -X PUT repos/acme/w/pulls/42/merge", "42")):
            d = terminal(command, self.root)
            self.assertEqual(d, {"action": "block", "message": "Merging is the user's decision. Ask them to run "
                                                               "`/foreman merge %s`." % n}, command)
        for command in ("gh api repos/acme/w/pulls/42/merge",  # GET: is it merged?
                        "gh api repos/acme/w/pulls/42", "gh api -X PATCH repos/acme/w/pulls/42 -f title=x",
                        "gh api graphql -f query='query { viewer { login } }'", "gh api graphql -F query=@read.graphql",
                        "gh api repos/acme/w/merges",
                        "gh api graphql -f query=@q.graphql",  # -f is literal: the text "@q.graphql", no file
                        "gh api graphql --input missing.json --input read.json"):  # gh reads the last one
            d = terminal(command, self.root)
            self.assertNotEqual((d or {}).get("message", "")[:30], "Merging is the user's decision", command)

    def test_push_of_several_branches_is_approved_only_for_those_commits(self):
        d = terminal("git push --all origin", self.root)
        self.assertEqual(d["action"], "approve")
        self.assertEqual(terminal("git push --all origin", self.root)["rule_key"], d["rule_key"])
        self.git("checkout", "-q", "-b", "other")
        self.write("app.py", "x = 6\n")
        self.commit("other branch moves")
        self.git("checkout", "-q", "main")
        moved = terminal("git push --all origin", self.root)
        self.assertEqual(moved["message"], d["message"])
        self.assertNotEqual(moved["rule_key"], d["rule_key"])  # "always" covered the earlier state only
        two = terminal("git push origin main other", self.root)
        self.git("checkout", "-q", "other")
        self.write("app.py", "x = 7\n")
        self.commit("again")
        self.git("checkout", "-q", "main")
        self.assertNotEqual(terminal("git push origin main other", self.root)["rule_key"], two["rule_key"])

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


class _PushedBranch(GitRepoCase):
    """A repository with a remote: the base branch pushed, and a branch `feature` with one commit, pushed too."""

    BASE = "main"

    def setUp(self):
        super().setUp()
        self.remote = os.path.join(self.tmp, "remote.git")
        self.git("init", "-q", "--bare", self.remote, cwd=self.tmp)
        self.git("remote", "add", "origin", self.remote)
        if self.BASE != "main":
            self.git("branch", "-m", self.BASE)
        self.write("app.py", "x = 1\n")
        self.write("tests/test_app.py", "def test_x():\n    assert True\n")
        self.commit("base")
        self.git("push", "-q", "-u", "origin", self.BASE)
        self.git("checkout", "-q", "-b", "feature")
        self.write("app.py", "x = 2\n")
        self.commit("feature: its own change")
        self.git("push", "-q", "-u", "origin", "feature")

    def someone_else_changes_a_test_on_the_base(self, back_to="feature"):
        self.git("checkout", "-q", self.BASE)
        self.write("tests/test_other.py", SKIP + "\ndef test_y():\n    assert True\n")
        self.commit("someone else's test, already on the base branch")
        self.git("push", "-q", "origin", self.BASE)
        self.git("checkout", "-q", back_to)

    def rig(self):
        self.write("tests/test_app.py", SKIP + "\ndef test_x():\n    assert True\n")

    def rig_pushed_by_hand(self):
        self.rig()
        self.git("add", "-A")
        self.git("commit", "-qm", "a rig, pushed by hand")
        self.git("push", "-q", "origin", "feature")


class PushAfterTheBaseCameIn(_PushedBranch):
    """A push is read for what the branch itself changes. Found on 2026-11-25: the range ran from the branch's old
    tip on the remote, so once the base branch had come into the branch (a rebase, a merge) with someone else's
    change to a test, the push was refused for that change and the agent was told to undo another person's line."""

    def test_a_rebased_branch_is_not_refused_for_what_came_with_the_base(self):
        self.someone_else_changes_a_test_on_the_base()
        self.git("rebase", "-q", self.BASE)
        for command in ("git push --force-with-lease origin feature", "git push --force-with-lease", "git push -f"):
            self.assertIsNone(terminal(command, self.root), command)

    def test_a_branch_the_base_was_merged_into_is_not_refused_for_what_came_with_it(self):
        self.someone_else_changes_a_test_on_the_base()
        self.git("merge", "-q", "--no-edit", self.BASE)
        for command in ("git push origin feature", "git push"):
            self.assertIsNone(terminal(command, self.root), command)

    def test_what_the_branch_itself_rigs_is_still_refused_after_a_rebase_or_a_merge(self):
        self.someone_else_changes_a_test_on_the_base()
        self.rig()
        self.commit("rig")
        self.git("rebase", "-q", self.BASE)
        d = terminal("git push --force-with-lease origin feature", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("tests/test_app.py", d["message"])
        self.assertNotIn("tests/test_other.py", d["message"])  # the other person's line is not the branch's
        self.git("reset", "-q", "--hard", "origin/feature")
        self.git("merge", "-q", "--no-edit", self.BASE)
        self.rig()
        self.commit("rig after the merge")
        d = terminal("git push origin feature", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("tests/test_app.py", d["message"])
        self.assertNotIn("tests/test_other.py", d["message"])

    def test_a_rig_already_pushed_and_carried_through_a_rebase_is_refused(self):
        # The whole branch is new commits after a rebase: what it changed before the rebase counts again.
        self.rig_pushed_by_hand()
        self.someone_else_changes_a_test_on_the_base()
        self.git("rebase", "-q", self.BASE)
        d = terminal("git push --force-with-lease origin feature", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("tests/test_app.py", d["message"])

    def test_a_plain_push_still_reads_only_the_commits_the_remote_does_not_have(self):
        self.rig_pushed_by_hand()
        self.write("app.py", "x = 3\n")
        self.commit("the agent's clean commit")
        self.assertIsNone(terminal("git push origin feature", self.root))
        self.rig()
        self.write("tests/test_more.py", SKIP + "\ndef test_z():\n    assert True\n")
        self.commit("the agent's rig")
        d = terminal("git push", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("tests/test_more.py", d["message"])

    def a_test_the_branch_already_pushed(self):
        self.write("tests/test_new.py", "def test_new():\n    assert True\n")
        self.commit("feature: a new test")
        self.git("push", "-q", "origin", "feature")

    # Found in the review of this fix: reading from where the branch leaves the base whenever its history was
    # rewritten let these three through, because that tree never had what the branch pushed before.

    def test_a_pushed_test_dropped_by_rewriting_history_is_refused(self):
        self.a_test_the_branch_already_pushed()
        self.git("reset", "-q", "--hard", "HEAD~1")
        self.write("app.py", "x = 5\n")
        self.commit("feature: the same change, without the test")
        d = terminal("git push -f origin feature", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("tests/test_new.py", d["message"])

    def test_the_base_branch_pushed_over_someone_elses_commit_is_refused(self):
        self.someone_else_changes_a_test_on_the_base(back_to=self.BASE)
        self.write("tests/test_theirs.py", "def test_theirs():\n    assert True\n")
        self.commit("someone else's second test")
        self.git("push", "-q", "origin", self.BASE)
        self.git("reset", "-q", "--hard", "HEAD~1")
        self.write("app.py", "x = 6\n")
        self.commit("the agent's commit in its place")
        d = terminal("git push -f origin " + self.BASE, self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("tests/test_theirs.py", d["message"])

    def test_a_pushed_test_dropped_while_rebasing_onto_the_moved_base_is_refused(self):
        self.a_test_the_branch_already_pushed()
        self.someone_else_changes_a_test_on_the_base()
        self.git("reset", "-q", "--hard", "HEAD~1")  # leaves the new test's commit behind
        self.git("rebase", "-q", self.BASE)
        self.assertFalse(os.path.exists(os.path.join(self.root, "tests", "test_new.py")))
        self.write("app.py", "x = 7\n")
        self.commit("feature: goes on")
        d = terminal("git push --force-with-lease origin feature", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("tests/test_new.py", d["message"])
        self.assertNotIn("tests/test_other.py", d["message"])

    def test_rewriting_history_does_not_bring_back_what_was_already_on_the_remote(self):
        self.rig_pushed_by_hand()
        self.write("app.py", "x = 8\n")
        self.git("add", "-A")
        self.git("commit", "-q", "--amend", "-m", "a rig, pushed by hand, and one more line of code")
        self.assertIsNone(terminal("git push -f origin feature", self.root))

    def test_a_branch_that_follows_the_base_is_read_against_the_bases_tip(self):
        # `git checkout -b topic origin/main` follows origin/main. Pushed onto the base branch itself, what the
        # base has and the branch lacks would be gone from the remote, so the base's tip stays the base of the
        # reading, whichever way the command names the destination (found in the review of this fix: reading where
        # the push goes from the command let `topic:heads/main` and a flag with a value through).
        self.git("checkout", "-q", "-b", "topic", "origin/" + self.BASE)
        self.assertEqual(self.git("rev-parse", "--abbrev-ref", "topic@{upstream}").strip(), "origin/" + self.BASE)
        self.write("app.py", "x = 9\n")
        self.commit("topic: its own change")
        self.someone_else_changes_a_test_on_the_base(back_to="topic")
        for command in ("git push -f origin topic:" + self.BASE, "git push -f origin HEAD:refs/heads/" + self.BASE,
                        "git push -f origin topic:heads/" + self.BASE):
            d = terminal(command, self.root)
            self.assertEqual(d["action"], "block", command)
            self.assertIn("tests/test_other.py", d["message"], command)
        self.git("config", "push.default", "upstream")
        for command in ("git push -f", "git push -f -o ci.skip origin"):
            d = terminal(command, self.root)
            self.assertEqual(d["action"], "block", command)
            self.assertIn("tests/test_other.py", d["message"], command)


class PushWithNoBaseBranchToName(_PushedBranch):
    """The remote's default branch is not `main` or `master` and the clone has no `origin/HEAD` (a repository made
    with `git init` and `git remote add`): Foreman cannot name the base branch, so it reads the push as before,
    from the branch's old tip on the remote."""

    BASE = "trunk"

    def test_the_old_range_stands_so_what_came_with_the_base_is_still_refused(self):
        self.someone_else_changes_a_test_on_the_base()
        self.git("rebase", "-q", self.BASE)
        self.assertEqual(terminal("git push --force-with-lease origin feature", self.root)["action"], "block")

    def test_what_the_branch_itself_rigs_is_refused(self):
        self.someone_else_changes_a_test_on_the_base()
        self.rig()
        self.commit("rig")
        self.git("rebase", "-q", self.BASE)
        d = terminal("git push --force-with-lease origin feature", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("tests/test_app.py", d["message"])

    def test_a_local_main_moved_onto_rewritten_history_is_not_the_base(self):
        self.rig()
        self.git("add", "-A")
        self.git("commit", "-q", "--amend", "-m", "feature: rewritten, with a rig")
        self.git("branch", "-f", "main", "HEAD")
        d = terminal("git push --force-with-lease origin feature", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("tests/test_app.py", d["message"])

    def test_with_the_remotes_head_known_the_base_is_found(self):
        self.git("remote", "set-head", "origin", self.BASE)
        self.someone_else_changes_a_test_on_the_base()
        self.git("rebase", "-q", self.BASE)
        self.assertIsNone(terminal("git push --force-with-lease origin feature", self.root))


class CommitThatConcludesAMerge(_PushedBranch):
    """The commit that concludes a merge is read for what the resolution itself does. Found on 2026-11-25: the
    staged tree was read against the branch's side only, so a merge of the base branch that stopped on a conflict
    was refused, at its `git commit`, for the base branch's own change to a test."""

    def the_base_moves(self, test="tests/test_other.py"):
        """Someone else, on the base branch: a line of code the branch also changed, and a change to a test."""
        self.git("checkout", "-q", self.BASE)
        self.write("app.py", "x = 100\n")
        self.write(test, SKIP + "\ndef test_y():\n    assert True\n")
        self.commit("someone else: the code and a test, already on the base branch")
        self.git("push", "-q", "origin", self.BASE)
        self.git("checkout", "-q", "feature")

    def merge_stops_on_the_conflict(self, other=None):
        with self.assertRaises(AssertionError):
            self.git("merge", "--no-edit", other or self.BASE)
        self.write("app.py", "x = 102\n")  # the resolution
        self.git("add", "-A")

    def test_what_came_with_the_base_branch_is_not_the_commits_doing(self):
        self.the_base_moves()
        self.merge_stops_on_the_conflict()
        for command in ("git commit --no-edit", "git commit -m merged", "git commit -a --no-edit"):
            self.assertIsNone(terminal(command, self.root), command)

    def test_what_the_resolution_itself_rigs_is_refused(self):
        self.the_base_moves()
        self.merge_stops_on_the_conflict()
        self.write("tests/test_app.py", SKIP + "\ndef test_x():\n    assert True\n")
        self.git("add", "-A")
        d = terminal("git commit --no-edit", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("tests/test_app.py", d["message"])
        self.assertNotIn("tests/test_other.py", d["message"])

    def test_a_test_of_the_branch_dropped_in_the_resolution_is_refused(self):
        self.write("tests/test_new.py", "def test_new():\n    assert True\n")
        self.commit("feature: a new test")
        self.the_base_moves()
        self.merge_stops_on_the_conflict()
        self.git("rm", "-q", "tests/test_new.py")
        d = terminal("git commit --no-edit", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("tests/test_new.py", d["message"])

    def test_a_test_of_the_base_branch_dropped_in_the_resolution_is_refused(self):
        self.the_base_moves()
        self.merge_stops_on_the_conflict()
        self.git("rm", "-qf", "tests/test_other.py")
        d = terminal("git commit --no-edit", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("tests/test_other.py", d["message"])

    def test_a_file_both_sides_changed_counts_only_for_what_the_resolution_adds(self):
        self.write("tests/test_app.py", "def test_x():\n    assert True\n\n\ndef test_mine():\n    assert True\n")
        self.commit("feature: one more test")
        self.the_base_moves(test="tests/test_app.py")  # the base rewrites the same file, with a skipped test
        self.merge_stops_on_the_conflict()
        both = SKIP + "\ndef test_y():\n    assert True\n\n\ndef test_mine():\n    assert True\n"
        self.write("tests/test_app.py", both)  # the base's lines and the branch's: the marker is the base's
        self.git("add", "-A")
        self.assertIsNone(terminal("git commit --no-edit", self.root))
        self.write("tests/test_app.py", both + "\n\n" + SKIP + "\ndef test_more():\n    assert True\n")
        self.git("add", "-A")
        d = terminal("git commit --no-edit", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("tests/test_app.py:%d" % (both.count("\n") + 3), d["message"])  # the resolution's own marker
        self.assertNotIn("tests/test_app.py:1 ", d["message"])  # not the base's

    def test_a_merge_of_commits_no_remote_has_is_read_as_before(self):
        # What comes in is taken as someone else's only when a remote already has it: a local branch can carry a
        # rig made where the gate did not see it (a script), and a merge must not be the way to bring it in.
        self.git("checkout", "-q", "-b", "side", self.BASE)
        self.write("app.py", "x = 100\n")
        self.write("tests/test_other.py", SKIP + "\ndef test_y():\n    assert True\n")
        self.commit("a rig on a local branch")
        self.git("checkout", "-q", "feature")
        self.merge_stops_on_the_conflict(other="side")
        d = terminal("git commit --no-edit", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("tests/test_other.py", d["message"])

    def test_a_commit_that_concludes_no_merge_is_read_as_before(self):
        self.the_base_moves()
        self.write("tests/test_other.py", SKIP + "\ndef test_y():\n    assert True\n")  # the same line, by hand
        self.git("add", "-A")
        d = terminal("git commit -m x", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("tests/test_other.py", d["message"])


class BranchThatFollowsTheBase(_PushedBranch):
    """`git checkout -b topic origin/main` makes a branch that follows the base branch itself. Found on 2026-11-25:
    its push was read against the base's tip, so once the base moved, what the base had gained read as the
    branch's doing (someone's new test as a test the branch deleted). Pushed to a branch of its own, it is read
    against that branch on the remote, or from where it leaves the base when the remote has none; whenever the
    command leaves a doubt about where the push goes, the base's tip stays the reading."""

    def setUp(self):
        super().setUp()
        self.git("checkout", "-q", "-b", "topic", "origin/" + self.BASE)
        self.assertEqual(self.git("rev-parse", "--abbrev-ref", "topic@{upstream}").strip(), "origin/" + self.BASE)
        self.write("app.py", "x = 20\n")
        self.commit("topic: its own change")

    def the_base_moves(self):
        self.someone_else_changes_a_test_on_the_base(back_to="topic")

    def test_pushed_to_a_branch_of_its_own_it_is_not_refused_for_what_the_base_gained(self):
        self.the_base_moves()
        for command in ("git push origin topic", "git push -u origin topic", "git push origin HEAD",
                        "git push origin topic:topic", "git push origin refs/heads/topic:refs/heads/topic",
                        "git push --set-upstream origin topic"):
            self.assertIsNone(terminal(command, self.root), command)
        self.git("config", "push.default", "current")
        self.assertIsNone(terminal("git push", self.root))
        self.assertIsNone(terminal("git push origin", self.root))

    def test_what_the_branch_itself_rigs_is_refused(self):
        self.the_base_moves()
        self.git("rm", "-q", "tests/test_app.py")
        self.commit("topic: deletes a test")
        for command in ("git push origin topic", "git push -u origin topic", "git push origin HEAD"):
            d = terminal(command, self.root)
            self.assertEqual(d["action"], "block", command)
            self.assertIn("tests/test_app.py", d["message"], command)
            self.assertNotIn("tests/test_other.py", d["message"], command)

    def test_pushed_onto_the_base_branch_it_is_read_against_the_bases_tip(self):
        self.the_base_moves()
        base = self.BASE
        for command in ("git push -f origin topic:" + base, "git push origin topic:" + base,
                        "git push -f origin HEAD:refs/heads/" + base, "git push -f origin topic:heads/" + base,
                        "git push -f origin +topic:" + base, "git push origin +HEAD:" + base,
                        "git push origin topic:refs/heads/" + base, "git -c push.default=upstream push -f",
                        "git -c push.default=tracking push"):
            d = terminal(command, self.root)
            self.assertIn(d["action"], ("block", "approve"), command)
            self.assertIn("tests/test_other.py", d["message"], command)
        self.git("config", "push.default", "upstream")
        for command in ("git push -f", "git push", "git push origin", "git push -f -o ci.skip origin"):
            d = terminal(command, self.root)
            self.assertEqual(d["action"], "block", command)
            self.assertIn("tests/test_other.py", d["message"], command)

    def test_a_command_that_leaves_a_doubt_is_read_against_the_bases_tip(self):
        self.the_base_moves()
        for command in ("git push -f origin topic",             # forced, and the remote has no such branch to force
                        "git push --force-with-lease origin topic", "git push origin +topic",
                        "git push origin topic:heads/topic",     # a destination git expands by its own rules
                        "git push origin topic:refs/for/topic",  # not a branch
                        "git push origin topic:",                # no destination at all
                        "git push --repo origin",                # the remote given by a flag
                        "git -c push.default=current push",      # where it goes, set for this one command
                        "git push --tags origin topic",          # a flag this reading does not know
                        "git push --push-option=ci.skip origin topic"):
            d = terminal(command, self.root)
            self.assertIsNotNone(d, command)
            self.assertIn("tests/test_other.py", d["message"], command)
        for command in ("git push -o ci.skip origin topic", "git push origin topic other"):
            self.assertIsNotNone(terminal(command, self.root), command)  # as before: a person, or a refusal

    def test_with_the_branch_already_on_the_remote_it_is_read_against_its_own_tip(self):
        self.write("tests/test_new.py", "def test_new():\n    assert True\n")
        self.commit("topic: a new test")
        self.git("push", "-q", "origin", "topic")  # by hand: the branch still follows the base
        self.assertEqual(self.git("rev-parse", "--abbrev-ref", "topic@{upstream}").strip(), "origin/" + self.BASE)
        self.the_base_moves()
        self.write("app.py", "x = 21\n")
        self.commit("topic: goes on")
        self.assertIsNone(terminal("git push origin topic", self.root))
        self.git("reset", "-q", "--hard", "HEAD~2")
        self.write("app.py", "x = 22\n")
        self.commit("topic: the same, without its test")
        for command in ("git push -f origin topic", "git push --force-with-lease origin topic"):
            d = terminal(command, self.root)
            self.assertEqual(d["action"], "block", command)
            self.assertIn("tests/test_new.py", d["message"], command)
            self.assertNotIn("tests/test_other.py", d["message"], command)

    def test_a_setting_that_sends_the_named_branch_onto_the_base_is_a_doubt(self):
        # Found in the review of this fix: with push.default=upstream, `git push -f origin topic` writes the
        # branch its upstream names, the base branch, and a configured remote.<name>.push maps it there too.
        self.git("push", "-q", "origin", "topic:topic")
        self.the_base_moves()
        self.write("app.py", "x = 23\n")
        self.commit("topic: goes on")
        base = self.BASE
        for key, value in (("push.default", "upstream"), ("push.default", "tracking"), ("push.default", "nothing"),
                           ("remote.origin.push", "refs/heads/topic:refs/heads/" + base),
                           ("remote.origin.mirror", "true")):
            self.git("config", key, value)
            for command in ("git push -f origin topic", "git push origin topic", "git push origin HEAD"):
                d = terminal(command, self.root)
                self.assertEqual(d["action"], "block", (key, value, command))
                self.assertIn("tests/test_other.py", d["message"], (key, value, command))
            self.git("config", "--unset", key)
        self.assertIsNone(terminal("git push origin topic", self.root))  # with none of them, read as its own
        for name in (base.upper(), base.capitalize()):  # a remote that folds case writes the base branch
            d = terminal("git push -f origin topic:" + name, self.root)
            self.assertIsNotNone(d, name)
            self.assertIn("tests/test_other.py", d["message"], name)

    def test_pushed_to_a_remote_given_by_its_address_it_is_read_from_where_it_leaves_the_base(self):
        self.the_base_moves()
        address = self.remote.replace(os.sep, "/")
        self.assertIsNone(terminal('git push "%s" topic' % address, self.root))
        self.git("rm", "-q", "tests/test_app.py")
        self.commit("topic: deletes a test")
        d = terminal('git push "%s" topic' % address, self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("tests/test_app.py", d["message"])

    def test_the_base_branch_itself_is_read_as_before(self):
        self.git("checkout", "-q", self.BASE)
        self.write("tests/test_app.py", SKIP + "\ndef test_x():\n    assert True\n")
        self.commit("a rig on the base branch")
        d = terminal("git push origin " + self.BASE, self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("tests/test_app.py", d["message"])


class SessionDirectory(GitRepoCase):
    """Real sessions: the process runs in the user's repository, Hermes's configured directory is the home folder
    or the Hermes home, and the Hermes home may itself be a git repository."""

    def setUp(self):
        super().setUp()
        self.write("app.py", "x = 1\n")
        self.commit("base")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        # A root Hermes home that is a git repository (with a dirty skip so picking it would show) and a profile
        # home under it, as on the machine where the defect was seen.
        self.hermes = os.path.join(self.tmp, "hermes-home")
        self.profile = os.path.join(self.hermes, "profiles", "dev")
        os.makedirs(os.path.join(self.hermes, "tests"))
        os.makedirs(self.profile)
        self.git("init", "-q", cwd=self.hermes)
        with open(os.path.join(self.hermes, "tests", "test_h.py"), "w", encoding="utf-8") as fh:
            fh.write(SKIP + "\n")

    def fake_hermes(self, configured, recorded=None, session=""):
        """Hermes's modules, and the plugin context with the public ``ctx.session_cwd()``."""
        runtime = types.ModuleType("agent.runtime_cwd")
        runtime.resolve_agent_cwd = lambda: configured
        constants = types.ModuleType("hermes_constants")
        constants.get_hermes_home = lambda: self.hermes
        terminal_tool = types.ModuleType("tools.terminal_tool")
        terminal_tool.get_session_cwd = lambda key: recorded if key == "s1" else None
        modules = mock.patch.dict(sys.modules, {"agent": types.ModuleType("agent"), "agent.runtime_cwd": runtime,
                                                "hermes_constants": constants, "tools": types.ModuleType("tools"),
                                                "tools.terminal_tool": terminal_tool})
        ctx = mock.patch.object(gate, "_CTX", types.SimpleNamespace(session_cwd=lambda: session))
        return _Both(modules, ctx)

    def norm(self, p):
        return os.path.normpath(p)

    def real(self, p):
        """What git reports as the repository's root: symlinks (/private/var) and 8.3 names resolved."""
        return os.path.normpath(os.path.realpath(p))

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
        self.assertEqual(out, gate.NO_REPOSITORY_HERE)

    def fake_gateway(self, session):
        """The gateway process: cwd is the root Hermes home (a git repository), the active home is a profile under
        it, Hermes's configured directory is the user's home, and the session cwd carries the caller's directory."""
        patch = self.fake_hermes(self.home, session=session)
        constants = types.ModuleType("hermes_constants")
        constants.get_hermes_home = lambda: self.profile
        constants.get_default_hermes_root = lambda: self.hermes
        return patch, mock.patch.dict(sys.modules, {"hermes_constants": constants}), \
            mock.patch.object(gate.os, "getcwd", return_value=self.hermes)

    def test_in_the_gateway_process_the_session_cwd_is_used(self):
        a, b, c = self.fake_gateway(session=self.root)
        with a, b, c:
            out = commands.handle_slash("status", session_id="s1", platform="cli")
        self.assertIn("Repository: %s (from this session's working directory)" % self.real(self.root), out)
        self.assertNotIn(self.norm(self.hermes) + "\n", out)

    def test_in_the_gateway_process_without_a_session_cwd_foreman_says_so(self):
        a, b, c = self.fake_gateway(session="")
        with a, b, c:
            out = commands.handle_slash("status", session_id="s1", platform="cli")
            self.assertEqual(out, gate.NO_REPOSITORY_HERE)
            self.assertEqual(json.loads(commands.foreman_check_tool({}))["verdict"], "NO_REPOSITORY")
            # The hook never guesses either: an unlocated gated command is blocked with the workdir hint.
            d = terminal("git commit -m x")
            self.assertEqual(d["action"], "block")
            self.assertIn("workdir", d["message"])

    def test_a_typed_command_finds_the_repository_the_agent_committed_in_this_session(self):
        # Found in a real session (Desktop): the agent committed in a repository, then `/foreman review t/live`
        # typed in the same chat could not tell the repository.
        # Hermes calls the slash command with its arguments only; the session is in its session environment
        # (HERMES_SESSION_KEY: the chat; HERMES_SESSION_ID: the agent's live id, new after context compression).
        gate._GATED_REPOS.clear()
        env = {}
        with self.fake_hermes(self.home), mock.patch.object(gate.os, "getcwd", return_value=self.home), \
                mock.patch.object(gate, "_session_env", lambda name: env.get(name, "")):
            env.update(HERMES_SESSION_KEY="chat-1", HERMES_SESSION_ID="agent-1")
            self.assertEqual(commands.handle_slash("status", platform="desktop"), gate.NO_REPOSITORY_HERE)
            self.write("NOTES.md", "x\n")
            self.git("add", "NOTES.md")
            gate.on_pre_tool_call(tool_name="terminal", args={"command": "git commit -m notes", "workdir": self.root},
                                  task_id="task-9", session_id="agent-1")
            out = commands.handle_slash("status", platform="desktop")
            self.assertIn("Repository: %s" % self.real(self.root), out)
            self.assertIn("the repository of the agent's last git command in this session", out)
            env["HERMES_SESSION_ID"] = "agent-2"  # compressed: a new agent id, the same chat
            self.assertIn("Repository: %s" % self.real(self.root), commands.handle_slash("status", platform="desktop"))
            env.update(HERMES_SESSION_KEY="chat-2", HERMES_SESSION_ID="agent-3")  # another chat inherits nothing
            self.assertEqual(commands.handle_slash("status", platform="desktop"), gate.NO_REPOSITORY_HERE)
        gate._GATED_REPOS.clear()

    def test_on_a_messaging_platform_the_process_directory_is_ignored(self):
        with self.fake_hermes(self.home), mock.patch.object(gate.os, "getcwd", return_value=self.root):
            self.assertEqual([p for p, _ in gate.cwd_candidates(platform="telegram")], [self.norm(self.home)])
            self.assertEqual(commands.handle_slash("status", platform="telegram"), gate.NO_REPOSITORY_HERE)

    def test_the_recorded_terminal_directory_wins_and_needs_no_hint(self):
        other = os.path.join(self.tmp, "other")
        os.makedirs(other)
        self.git("init", "-q", cwd=other)
        with self.fake_hermes(self.home, recorded=self.root), mock.patch.object(gate.os, "getcwd", return_value=other):
            out = commands.handle_slash("status", session_id="s1", platform="cli")
        self.assertIn("Repository: %s\n" % self.real(self.root), out)

    def test_a_relative_path_is_never_resolved_against_the_gateway_directory(self):
        parent = os.path.dirname(self.root)
        relative = os.path.basename(self.root)
        missing = os.path.join(self.tmp, "no-such-dir")
        with self.fake_hermes(missing), mock.patch.object(gate.os, "getcwd", return_value=parent):
            self.assertEqual(commands.handle_slash("status " + relative, platform="telegram"), gate.NO_REPOSITORY_HERE)
        with self.fake_hermes(missing), mock.patch.object(gate.os, "getcwd", return_value=parent):
            self.assertIn("Foreman: CLEAN", commands.handle_slash("status " + relative, platform="cli"))

    def test_an_explicit_path_is_accepted(self):
        with self.fake_hermes(self.home), mock.patch.object(gate.os, "getcwd", return_value=self.home):
            out = commands.handle_slash("status " + self.root, platform="cli")
        self.assertIn("Foreman: CLEAN", out)
        self.assertNotIn("(from", out)


class TurnedOff(GitRepoCase):
    """Found in a real session: Foreman disabled in Desktop kept blocking until the gateway restarted (Hermes keeps a
    disabled plugin's hooks loaded). Foreman reads the switch itself and stands down at once."""

    def setUp(self):
        super().setUp()
        self.write("tests/test_app.py", "def test_x():\n    assert True\n")
        self.commit("base")
        self.write("tests/test_app.py", SKIP + "\ndef test_x():\n    assert True\n")
        self.git("add", "-A")

    def config(self, disabled):
        module = types.ModuleType("hermes_cli.config")
        module.load_config_readonly = lambda: {"plugins": {"disabled": disabled}}
        return mock.patch.dict(sys.modules, {"hermes_cli": types.ModuleType("hermes_cli"), "hermes_cli.config": module})

    def test_turned_off_it_blocks_nothing_and_says_so(self):
        with self.config(["foreman"]):
            self.assertTrue(gate.turned_off())
            self.assertIsNone(terminal("git commit -m x", self.root))
            self.assertIsNone(gate.on_pre_tool_call(tool_name="write_file", args={
                "path": os.path.join(self.root, "tests", "test_b.py"), "content": SKIP + "\ndef test_b():\n    pass\n"}))
            self.assertIsNone(gate.on_pre_verify(coding=True, attempt=0, changed_paths=[
                os.path.join(self.root, "tests", "test_app.py")]))
            self.assertIn("Foreman is turned off", commands.handle_slash("status " + self.root))
            self.assertEqual(json.loads(commands.foreman_check_tool({"path": self.root}))["verdict"], "OFF")

    def test_turned_on_or_unreadable_it_blocks_as_always(self):
        with self.config(["some-other-plugin"]):
            self.assertFalse(gate.turned_off())
            self.assertEqual(terminal("git commit -m x", self.root)["action"], "block")
        with mock.patch.dict(sys.modules, {"hermes_cli": None, "hermes_cli.config": None}):
            self.assertFalse(gate.turned_off())  # no Hermes config reader: never off by accident
            self.assertEqual(terminal("git commit -m x", self.root)["action"], "block")

    def test_the_agent_cannot_turn_foreman_off(self):
        # Found in review: turned off takes effect at once, so an agent could switch the gate off and commit next.
        for command in ("hermes plugins disable foreman", "hermes -p default plugins remove foreman",
                        "hermes plugins uninstall Foreman", "echo ok && hermes plugins disable foreman",
                        "hermes config set plugins.disabled '[foreman]'", "hermes config unset plugins.enabled"):
            d = gate.on_pre_tool_call(tool_name="terminal", args={"command": command, "workdir": self.root})
            self.assertEqual(d["action"], "block", command)
            self.assertIn("user's decision", d["message"])
        for command in ("hermes plugins list", "hermes plugins disable some-other-plugin", "hermes config get model",
                        "echo foreman"):
            self.assertIsNone(gate.on_pre_tool_call(tool_name="terminal", args={"command": command,
                                                                                  "workdir": self.root}), command)


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

    def test_an_imported_skip_is_blocked_at_the_write(self):
        # Found in the final review: `from unittest import skip` + `@skip('x')` through write_file passed.
        d = self.write_file(self.test_file, "from unittest import skip\n\n\n@" + "skip('x')\ndef test_x():\n    assert True\n")
        self.assertEqual(d["action"], "block")
        self.assertIn("test-skipped", d["message"])

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

    def test_an_ignored_changed_file_does_not_pull_its_repository_in(self):
        # Found in a real session: another plugin wrote scratch files under an ignored folder of a Hermes home that
        # is itself a git repository, and Foreman asked the agent to undo findings it never made there.
        self.write(".gitignore", "plugin-data/\n")
        self.commit("ignore plugin data")
        self.write("tests/test_app.py", SKIP + "\n")  # someone else's uncommitted change in that repository
        scratch = self.write("plugin-data/scan/work.py", "x = 1\n")
        self.assertIsNone(gate.on_pre_verify(coding=True, attempt=0, changed_paths=[scratch]))
        d = gate.on_pre_verify(coding=True, attempt=0, changed_paths=[scratch, self.test_file])
        self.assertEqual(d["action"], "continue")  # a real change in the same repository is still scanned
        self.assertIn("tests/test_app.py:1", d["message"])

    def test_a_tracked_test_inside_an_ignored_folder_is_still_scanned(self):
        self.write(".gitignore", "plugin-data/\n")
        forced = self.write("plugin-data/tests/test_x.py", "def test_x():\n    assert True\n")
        self.git("add", "-f", forced)
        self.commit("force-add a test under an ignored folder")
        self.write("plugin-data/tests/test_x.py", SKIP + "\ndef test_x():\n    assert True\n")
        d = gate.on_pre_verify(coding=True, attempt=0, changed_paths=[forced])
        self.assertEqual(d["action"], "continue")
        self.assertIn("plugin-data/tests/test_x.py:1", d["message"])

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
        self.assertIn("Unknown subcommand", commands.handle_slash("frobnicate"))  # `review` is a subcommand now
        with mock.patch.object(commands, "locate", return_value=(self.root, gate.RECORDED)):
            self.assertIn("Foreman: BLOCKED", commands.handle_slash("status"))

    def test_tool_returns_json(self):
        self.write("tests/test_a.py", SKIP + "\n")
        data = json.loads(commands.foreman_check_tool({"path": self.root}))
        self.assertEqual(data["verdict"], "BLOCKED")
        self.assertEqual(data["blockers"][0]["rule"], "test-skipped")
        data = json.loads(commands.foreman_check_tool({"path": os.path.join(self.tmp)}))
        self.assertEqual(data["verdict"], "NO_REPOSITORY")


class HookBypasses(GitRepoCase):
    """Good-faith shortcuts around the repository's hooks."""

    def setUp(self):
        super().setUp()
        self.write("app.py", "x = 1\n")
        self.commit("base")
        self.write("app.py", "x = 2\n")
        self.git("add", "-A")

    def test_hook_disabling_variables_in_front_of_a_commit_or_push(self):
        for command in ("HUSKY=0 git commit -m x", "SKIP=flake8,mypy git commit -m x",
                        "PRE_COMMIT_ALLOW_NO_CONFIG=1 git commit -m x", "env HUSKY=0 git commit -m x",
                        "HUSKY_SKIP_HOOKS=1 git push", "LEFTHOOK=0 git commit -m x", "FOO=1 SKIP=lint git commit -m x",
                        "GIT_CONFIG_PARAMETERS=\"'core.hooksPath=/dev/null'\" git commit -m x"):
            d = terminal(command, self.root)
            self.assertEqual(d and d["action"], "block", command)
            self.assertIn("skips the repository's git hooks", d["message"], command)
        for command in ("HUSKY=1 git commit -m x", "LANG=C git commit -m x", "SKIP= git commit -m x"):
            self.assertIsNone(terminal(command, self.root), command)
        d = terminal("HUSKY=0 bash -c 'git commit -m x'", self.root)
        self.assertIn("skips the repository's git hooks", d["message"])

    def test_exporting_a_hook_disabling_variable_is_refused(self):
        # The terminal keeps exported variables between calls: every later commit would skip the hooks.
        for command in ("export HUSKY=0", "export SKIP=flake8", "export LEFTHOOK=0 && npm test", "$env:HUSKY = 0",
                        "$env:SKIP='lint'", "setx HUSKY 0", "set PRE_COMMIT_ALLOW_NO_CONFIG=1"):
            d = terminal(command, self.root)
            self.assertEqual(d and d["action"], "block", command)
        for command in ("export HUSKY=1", "export PATH=$PATH:/x", "echo SKIP the intro", "export SKIP_TESTS_DOC=1",
                        "grep -n 'git commit' notes.md", "man git commit"):
            self.assertIsNone(terminal(command, self.root), command)

    def test_wrapped_commits_are_still_inspected(self):
        self.write("tests/test_app.py", SKIP + "\n")
        self.git("add", "-A")
        for command in ("timeout 60 git commit -m x", 'pwsh -Command "git commit -m x"', 'cmd /c "git commit -m x"',
                        "nice -n 5 git commit -m x"):
            d = terminal(command, self.root)
            self.assertEqual(d and d["action"], "block", command)
            self.assertIn("test-skipped", d["message"], command)

    def test_git_config_core_hooks_path_is_refused(self):
        for command in ("git config core.hooksPath .nohooks", "git config --unset core.hooksPath",
                        "git config core.hooksPath /dev/null", "git config --local core.hookspath x",
                        "git -C . config --global core.hooksPath ''", "git config unset core.hooksPath",
                        "git config set core.hooksPath x"):
            d = terminal(command, self.root)
            self.assertEqual(d and d["action"], "block", command)
            self.assertIn("core.hooksPath", d["message"], command)
            self.assertNotIn("rule_key", d)
        for command in ("git config core.hooksPath", "git config --get core.hooksPath", "git config user.name x"):
            self.assertIsNone(terminal(command, self.root), command)


class AttributesThatHideADiff(GitRepoCase):
    """git prints "Binary files differ" for a file its attributes mark as having no diff, and Foreman read that as a
    change with nothing in it. Found on 2026-11-25 by a review: a `.gitattributes` line in the same change (or one
    in `.git/info/attributes`) hid a test switched off, and a secret, from every reading of the diff."""

    def setUp(self):
        super().setUp()
        self.write("app.py", "x = 1\n")
        self.write("tests/test_app.py", "def test_x():\n    assert True\n")
        self.commit("base")
        self.git("checkout", "-q", "-b", "feature")

    def rig(self):
        self.write("tests/test_app.py", SKIP + "\ndef test_x():\n    assert True\n")

    def test_a_commit_that_marks_its_tests_as_having_no_diff_is_still_read(self):
        self.git("config", "diff.hidden.binary", "true")
        for attributes in ("tests/** -diff\n", "tests/** binary\n", "*.py -diff -text\n", "tests/** diff=hidden\n",
                           "[attr]quiet -diff\ntests/** quiet\n"):
            self.write(".gitattributes", attributes)
            self.rig()
            self.git("add", "-A")
            for command in ("git commit -m x", "git commit -am x"):
                d = terminal(command, self.root)
                self.assertEqual(d["action"], "block", (attributes, command))
                self.assertIn("[test-skipped] tests/test_app.py", d["message"], (attributes, command))
                self.assertIn("[check-changed] .gitattributes", d["message"], (attributes, command))
            self.git("reset", "-q", "--hard")

    def test_a_push_and_a_pull_request_are_still_read(self):
        self.write(".gitattributes", "tests/** -diff\n")
        self.rig()
        self.commit("a rig, and its tests marked as having no diff")
        for command in ("git push -u origin feature", "gh pr create --fill --base main"):
            d = terminal(command, self.root)
            self.assertEqual(d["action"], "block", command)
            self.assertIn("[test-skipped] tests/test_app.py", d["message"], command)
        report = detector.scan_range(detector.Repo(self.root), "main", "HEAD")  # the check in CI
        self.assertEqual(sorted((f.rule, f.file) for f in report.blockers),
                         [("check-changed", ".gitattributes"), ("test-skipped", "tests/test_app.py")])

    def test_attributes_kept_outside_the_tree_do_not_hide_a_test_either(self):
        with open(os.path.join(self.root, ".git", "info", "attributes"), "w", encoding="utf-8") as fh:
            fh.write("tests/** -diff\n")
        self.rig()
        self.git("add", "-A")
        d = terminal("git commit -m x", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("[test-skipped] tests/test_app.py", d["message"])

    def test_an_attribute_that_hides_or_transforms_files_is_a_finding_itself(self):
        # A clean filter (what git-lfs uses) stores something other than the file: the commit holds a pointer and
        # whoever checks out with the filter gets the real content, skip included.
        for line in ("*.cfg binary", "* -diff", "tests/** filter=lfs diff=lfs merge=lfs -text",
                     "src/** working-tree-encoding=UTF-16", "sub/*.py filter=mine", "*.lock -diff", "*.min.js -diff",
                     "*.svg binary", "*.ipynb filter=nbstripout", "settings.[c]fg -diff"):
            self.write(".gitattributes", line + "\n")
            self.git("add", "-A")
            d = terminal("git commit -m x", self.root)
            self.assertEqual(d["action"], "block", line)
            self.assertIn("[check-changed] .gitattributes", d["message"], line)
        self.write("docs/.gitattributes", "*.md -diff\n")  # at any depth
        self.git("add", "-A")
        self.assertIn("docs/.gitattributes", terminal("git commit -m x", self.root)["message"])

    def test_the_attributes_a_repository_commonly_sets_are_no_finding(self):
        self.write(".gitattributes", "# line endings and what is binary\n* text=auto\n*.sh text eol=lf\n"
                   "*.png binary\n*.PDF binary\nassets/**/*.woff2 -diff\n*.psd filter=lfs diff=lfs merge=lfs -text\n"
                   "*.py diff=python\n*.md diff=markdown\ndocs/* linguist-documentation\n")
        self.git("add", "-A")
        self.assertIsNone(terminal("git commit -m x", self.root))

    def test_a_person_can_allow_the_attribute_as_any_other_change_to_the_check(self):
        self.write(".gitattributes", "*.lock -diff\n")
        self.git("add", "-A")
        d = terminal('git commit -m "lock files are noise in a diff" -m "%s .gitattributes: generated files"'
                     % detector.MARKER, self.root)
        self.assertEqual(d["action"], "block")  # marked: it waits for the person, it does not pass alone
        self.assertIn("marked `%s`" % detector.MARKER, d["message"])
        self.assertIn("/foreman allow", d["message"])

    def secret(self, path="app.cfg"):
        self.write(path, "K = '" + GHP + "c" * 36 + "'\n")
        self.git("add", "-A")

    def test_a_secret_is_read_whatever_hides_its_file(self):
        # Attributes the change does not bring: the base's own, a macro the base defined, one of git's own drivers
        # made binary in the configuration, attributes kept outside the tree.
        self.git("checkout", "-q", "main")
        self.write(".gitattributes", "*.cfg -diff\n[attr]quiet -diff\n")
        self.commit("the base hides its configuration files from the diff")
        self.git("checkout", "-q", "-b", "later")
        self.secret()
        d = terminal("git commit -m x", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("[secret] app.cfg", d["message"])
        self.git("reset", "-q", "--hard")
        self.write(".gitattributes", "*.cfg -diff\n[attr]quiet -diff\n*.ini quiet\n*.toml diff=python\n")
        self.git("config", "diff.python.binary", "true")
        with open(os.path.join(self.root, ".git", "info", "attributes"), "w", encoding="utf-8") as fh:
            fh.write("*.env.sample -diff\n")
        for path in ("app.ini", "app.toml", "x.env.sample"):
            self.secret(path)
            d = terminal("git commit -m x", self.root)
            self.assertEqual(d["action"], "block", path)
            self.assertIn(path, d["message"], path)

    def test_a_secret_added_and_removed_again_in_a_hidden_file_is_still_in_the_history(self):
        self.git("checkout", "-q", "main")
        self.write(".gitattributes", "*.cfg -diff\n")
        self.commit("the base hides its configuration files from the diff")
        self.git("checkout", "-q", "-b", "later")
        self.secret()
        self.commit("a secret")
        self.git("rm", "-q", "app.cfg")
        self.commit("and its removal")
        d = terminal("git push -u origin later", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("secret-history", d["message"])
        self.assertIn("app.cfg", d["message"])

    def test_a_gitattributes_moved_to_another_folder_is_a_finding(self):
        self.git("checkout", "-q", "main")
        self.write("assets/.gitattributes", "* -diff\n")
        self.write("assets/notes.txt", "notes\n")
        self.commit("the base keeps its assets out of the diff")
        self.git("checkout", "-q", "-b", "later")
        os.makedirs(os.path.join(self.root, "config"))
        self.git("mv", "assets/.gitattributes", "config/.gitattributes")
        self.secret("config/app.cfg")
        d = terminal("git commit -m x", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("[check-changed] config/.gitattributes", d["message"])
        self.assertIn("[secret] config/app.cfg", d["message"])

    def test_a_file_that_is_really_binary_is_no_finding(self):
        block, data = b"foreman", bytearray()
        while len(data) < 1 << 20:  # one megabyte with no pattern to it, the same on every run
            block = hashlib.sha256(block).digest()
            data += block
        for name in ("logo.bin", "blob", os.path.join("tests", "fixture.bin")):
            with open(os.path.join(self.root, name), "wb") as fh:
                fh.write(data)
        self.git("add", "-A")
        self.assertIsNone(terminal("git commit -m x", self.root))
        self.commit("binary files")
        self.assertIsNone(terminal("git push -u origin feature", self.root))

    def test_a_replaced_commit_is_read_as_it_is(self):
        # `git replace` shows another object's content in place of a commit's, locally; a push sends the real one.
        self.rig()
        self.commit("a rig")
        clean = self.git("commit-tree", "main^{tree}", "-p", "main", "-m", "looks clean").strip()
        self.git("replace", "HEAD", clean)
        d = terminal("git push -u origin feature", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("[test-skipped] tests/test_app.py", d["message"])


class Performance(GitRepoCase):
    """The hook runs on every tool call: an ordinary write costs no git, and no input makes it super-linear."""

    def setUp(self):
        super().setUp()
        self.write("app.py", "x = 1\n")
        self.commit("base")

    def count_git(self):
        calls = []
        real = detector.subprocess.run

        def counting(args, *a, **k):
            if args and args[0] == "git":
                calls.append(list(args))
            return real(args, *a, **k)
        return calls, mock.patch.object(detector.subprocess, "run", side_effect=counting)

    def test_an_ordinary_write_runs_no_git(self):
        calls, patch = self.count_git()
        with patch:
            for i in range(5):
                self.assertIsNone(gate.on_pre_tool_call(tool_name="write_file", args={
                    "path": os.path.join(self.root, "app.py"), "content": "x = %d\n" % i}))
            self.assertIsNone(gate.on_pre_tool_call(tool_name="patch", args={
                "mode": "patch", "patch": "*** Begin Patch\n*** Update File: %s\n@@\n-x = 1\n+x = 2\n*** End Patch\n"
                % os.path.join(self.root, "app.py")}))
        self.assertEqual(calls, [])

    def test_a_config_that_names_reports_is_resolved_once_per_head(self):
        self.write(detector.CONFIG_FILE, json.dumps({"sarif": ["reports/r.json"]}))
        self.commit("config")
        calls, patch = self.count_git()
        target = os.path.join(self.root, "reports", "r.json")
        with patch:
            first = gate.on_pre_tool_call(tool_name="write_file", args={"path": target, "content": "{}"})
            n = len(calls)
            again = gate.on_pre_tool_call(tool_name="write_file", args={"path": target, "content": "{}"})
        self.assertEqual(first["action"], "block")
        self.assertEqual(again["action"], "block")
        self.assertLess(len(calls) - n, n)  # the base is not resolved again for the same HEAD
        self.write("app.py", "x = 2\n")
        self.commit("move HEAD")
        self.write(detector.CONFIG_FILE, json.dumps({"sarif": ["reports/r.json", "reports/s.json"]}))
        self.commit("another report")
        d = gate.on_pre_tool_call(tool_name="write_file", args={"path": os.path.join(self.root, "reports", "s.json"),
                                                               "content": "{}"})
        self.assertEqual(d and d["action"], "block")  # a new HEAD is resolved again

    def test_a_long_command_naming_git_without_a_verb_is_fast(self):
        heredoc = "cat > notes.txt <<'EOF'\n" + ("use git here\n" * 23000) + "EOF"  # about 300 KB
        self.assertGreater(len(heredoc), 290_000)
        start = time.perf_counter()
        self.assertIsNone(terminal(heredoc, self.root))
        self.assertLess(time.perf_counter() - start, 3.0)  # was quadratic: 106 s for 253 KB

    def test_adversarial_inputs_stay_linear(self):
        """Every regex applied to whole commands, diffs, diff lines or messages, on 300 KB inputs built to make a
        backtracking pattern quadratic. Each must finish well inside the hook's budget."""
        from foreman import review
        n = 300_000
        cases = {
            "command of >": lambda: gate.parse_actions("git commit " + ">" * n, os.sep),
            "command of gh pr": lambda: gate.on_pre_tool_call(tool_name="terminal", args={
                "command": "gh pr " * (n // 6), "workdir": self.root}),
            "command of quotes": lambda: gate.on_pre_tool_call(tool_name="terminal", args={
                "command": "git commit -m '" + "'\"" * (n // 2), "workdir": self.root}),
            "unknown runner of gh words": lambda: gate.parse_actions("runner " + "gh pr view " * (n // 11), os.sep),
            "eval of quoted git words": lambda: gate.parse_actions("eval " + "'git log push' " * (n // 15), os.sep),
            "exports of hook names": lambda: gate.on_pre_tool_call(tool_name="terminal", args={
                "command": "export SKIP " * (n // 12)}),
            "makefile of continuations": lambda: detector.default_check_changes(
                "Makefile", "test:\n\tx \\\n" + "  y \\\n" * (n // 6), "test:\n\tz\n"),
            "yaml value then spaces": lambda: detector.has_secret("+token: abcdefghij" + " " * n + "x", "c.yaml"),
            "dotted run": lambda: detector.has_secret("+" + "a." * (n // 2) + "x", "app.py"),
            "url-ish run": lambda: detector.has_secret("+" + "a-" * (n // 2) + "://u:p", "app.py"),
            "jwt-ish run": lambda: detector.has_secret("+" + "eyJ-" * (n // 4) + "x", "app.py"),
            "jwt-ish segments": lambda: detector.has_secret("+" + "eyJaaaaaaaaaaaa." * (n // 16), "app.py"),
            "message of newlines": lambda: detector.allowed_paths_in(detector.MARKER + " " + "\n" * n),
            "diff header of b/": lambda: detector.name_status_from_diff("diff --git a/" + "x b/" * (n // 4) + "\n"),
            "diff header of quotes": lambda: review.split_diff("diff --git " + '"a" ' * (n // 4) + "x\n"),
            "makefile line": lambda: detector.default_check_changes("Makefile", "test:\n\techo\n",
                                                                     "a" + " " * n + "x\n"),
            "long added line": lambda: detector.detect("+++ b/tests/test_a.py\n@@ -0,0 +1 @@\n+" + "x" * n + "\n"),
            "test renames": lambda: detector.detect("+++ b/tests/test_a.py\n@@ -1,%d +1,%d @@\n%s%s" % (
                n // 40, n // 40, "".join("-def test_%d():\n" % i for i in range(n // 40)),
                "".join("+def _test_%d():\n" % i for i in range(n // 40)))),
        }
        for name, fn in cases.items():
            start = time.perf_counter()
            fn()
            self.assertLess(time.perf_counter() - start, 3.0, name)


class Registration(unittest.TestCase):
    """register(ctx) registers exactly what plugin.yaml declares, and only the /foreman command."""

    def test_register_matches_the_manifest(self):
        spec = importlib.util.spec_from_file_location("foreman_plugin_under_test",
                                                      os.path.join(PLUGIN_DIR, "__init__.py"),
                                                      submodule_search_locations=[PLUGIN_DIR])
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
        with open(os.path.join(PLUGIN_DIR, "plugin.yaml"), encoding="utf-8") as fh:
            manifest = fh.read()

        def declared(key):
            block = re.search(r"(?m)^%s:\n((?:  - .+\n)+)" % key, manifest)
            return sorted(re.findall(r"- (\S+)", block.group(1))) if block else []

        self.assertEqual(sorted(recorded["hooks"]), declared("provides_hooks"))
        self.assertEqual(sorted(recorded["tools"]), declared("provides_tools"))
        self.assertEqual(recorded["commands"], ["foreman"])


if __name__ == "__main__":
    unittest.main()
