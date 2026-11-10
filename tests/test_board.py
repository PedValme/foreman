"""The board, verdicts for pull requests, merge and reject: a fake gh runner and temporary git repositories, never
the network. Markers and secret-looking values are assembled at runtime."""
import json
import os
import unittest

from foreman import board, commands, detector, gate, grants, pipeline
from tests_support import GitRepoCase

SKIP = "@pytest.mark." + "skip"
OID = "f" * 40
KEYS = ("session-1",)


class FakeGh:
    """Answers gh calls by argument prefix; records every call."""

    def __init__(self, responses=None, missing=False):
        self.responses = list(responses or [])
        self.missing = missing
        self.calls = []

    def add(self, prefix, out="", rc=0, err=""):
        self.responses.append((tuple(prefix), (rc, out if isinstance(out, str) else json.dumps(out), err)))

    def __call__(self, args, cwd, timeout):
        self.calls.append(list(args))
        if self.missing:
            raise FileNotFoundError("gh")
        for prefix, result in self.responses:
            if tuple(args[:len(prefix)]) == prefix:
                return result
        return 1, "", "unexpected gh call: %s" % " ".join(args)


class FakeCtx:
    """dispatch_tool records the terminal calls (and the comment body while its file exists)."""

    def __init__(self, result=None, choice=None, can_ask=True):
        self.result = result if result is not None else {"output": "ok", "exit_code": 0, "error": None}
        self.dispatched, self.bodies = [], []
        self._choice = choice
        if can_ask:
            self.ask_choice = self._ask
        self.asked = []

    def _ask(self, question, choices):
        self.asked.append((question, choices))
        return self._choice(choices) if callable(self._choice) else self._choice

    def dispatch_tool(self, name, args, **kwargs):
        self.dispatched.append((name, dict(args)))
        if "--body-file" in args.get("command", ""):
            path = args["command"].split("--body-file", 1)[1].strip().strip('"')
            with open(path, encoding="utf-8") as fh:
                self.bodies.append(fh.read())
        return json.dumps(self.result)


def pr_item(number, title, head, closes=(), repo="acme/widgets", draft=False, checks=()):
    return {"number": number, "title": title, "headRefName": head, "isDraft": draft,
            "author": {"login": "someone"}, "url": "https://github.com/%s/pull/%d" % (repo, number),
            "closingIssuesReferences": [{"number": n, "url": "https://github.com/%s/issues/%d" % (repo, n)}
                                        for n in closes],
            "statusCheckRollup": list(checks), "mergeable": "MERGEABLE", "updatedAt": "2026-11-09T10:00:00Z"}


def pr_view(number, closes=(), files=(), head=OID, title="Change things"):
    item = pr_item(number, title, "feature", closes)
    item.update(state="OPEN", headRefOid=head, baseRefName="main",
                commits=[{"oid": head, "messageHeadline": "Change things", "messageBody": ""}],
                files=list(files))
    return item


def diff_adding_skip():
    return ("diff --git a/tests/test_x.py b/tests/test_x.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/tests/test_x.py\n"
            "+++ b/tests/test_x.py\n"
            "@@ -1,2 +1,3 @@\n"
            " import pytest\n"
            "+" + SKIP + "\n"
            " def test_x(): assert True\n")


def clean_diff():
    return ("diff --git a/app.py b/app.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/app.py\n"
            "+++ b/app.py\n"
            "@@ -1 +1,2 @@\n"
            " x = 1\n"
            "+y = 2\n")


class BoardCase(GitRepoCase):
    def setUp(self):
        super().setUp()
        self.write("app.py", "x = 1\n")
        self.write("tests/test_x.py", "import pytest\ndef test_x(): assert True\n")
        self.commit("base")
        self.gh = FakeGh()
        self._old = (board.GH_RUNNER, board._CTX, pipeline.SETTINGS_OVERRIDE)
        board.GH_RUNNER = self.gh
        board.bind(FakeCtx())
        board.pin(self.root, KEYS)
        # These tests cover merge without the second model (auto_review: off, the behaviour before the pipeline);
        # tests/test_pipeline.py covers the default level, merge.
        pipeline.SETTINGS_OVERRIDE = {"auto_review": "off"}

    def tearDown(self):
        board.GH_RUNNER, board._CTX, pipeline.SETTINGS_OVERRIDE = self._old
        super().tearDown()

    def run_cmd(self, text):
        return commands.handle_slash(text, session_key=KEYS[0])

    def github(self):
        self.git("remote", "add", "origin", "https://github.com/acme/widgets.git")
        self.gh.add(["repo", "view"], {"nameWithOwner": "acme/widgets", "defaultBranchRef": {"name": "main"}})


class WithoutGitHub(BoardCase):
    def test_board_shows_local_branches_and_what_is_missing(self):
        self.git("checkout", "-q", "-b", "feature")
        self.write("tests/test_x.py", "import pytest\n" + SKIP + "\ndef test_x(): assert True\n")
        self.commit("switch it off")
        self.git("checkout", "-q", "main")
        out = self.run_cmd("")
        self.assertIn("GitHub: this repository has no remote; showing local branches only.", out)
        self.assertRegex(out, r"feature\s+1 ahead  BLOCKED 1")
        self.assertEqual(self.gh.calls, [])  # no remote: gh is never run
        self.assertTrue(all(len(l) <= 80 for l in out.splitlines()), out)

    def test_gh_not_installed(self):
        self.git("remote", "add", "origin", "https://github.com/acme/widgets.git")
        board.GH_RUNNER = FakeGh(missing=True)
        out = self.run_cmd("")
        self.assertIn("GitHub: gh (the GitHub CLI) is not installed; showing local branches only.", out)

    def test_gh_not_logged_in(self):
        self.git("remote", "add", "origin", "https://github.com/acme/widgets.git")
        self.gh.responses = [((), (4, "", "To get started with GitHub CLI, please run:  gh auth login"))]
        self.assertIn("gh is not logged in", self.run_cmd(""))

    def test_verdict_for_a_branch_works(self):
        self.git("checkout", "-q", "-b", "feature")
        self.write("tests/test_x.py", "import pytest\n" + SKIP + "\ndef test_x(): assert True\n")
        self.commit("switch it off")
        self.git("checkout", "-q", "main")
        out = self.run_cmd("verdict feature")
        self.assertIn("Foreman verdict for branch feature: BLOCKED", out)
        self.assertIn("[test-skipped] tests/test_x.py:2", out)
        self.assertIn("GitHub: this repository has no remote.", out)

    def test_merge_and_reject_explain_what_they_need(self):
        for verb in ("merge 3", "reject 3 nope"):
            out = self.run_cmd(verb)
            self.assertIn("needs GitHub", out)
        self.assertEqual(board._CTX.dispatched, [])


class Board(BoardCase):
    def test_pull_request_closing_two_issues(self):
        self.github()
        self.gh.add(["pr", "list"], [pr_item(7, "Fix the parser", "fix/parser", closes=(3, 5),
                                             checks=[{"__typename": "CheckRun", "status": "COMPLETED",
                                                      "conclusion": "FAILURE"},
                                                     {"__typename": "StatusContext", "state": "SUCCESS"}])])
        self.gh.add(["issue", "list"], [{"number": n, "title": "Issue %d" % n, "labels": [{"name": "bug"}],
                                         "updatedAt": "2026-11-0%dT00:00:00Z" % n} for n in (3, 5, 9)])
        out = self.run_cmd("")
        self.assertIn("Foreman board: acme/widgets", out)
        self.assertIn("#7    Fix the parser", out)
        self.assertIn("fix/parser · CI failing (1 of 2) · closes #3, #5", out)
        self.assertIn("Issues no open PR closes (1):", out)
        self.assertIn("#9    Issue 9  [bug]", out)
        self.assertNotIn("#3    Issue 3", out)
        self.assertIn("/foreman verdict 7", out)
        self.assertTrue(all(len(l) <= 80 for l in out.splitlines()), out)
        issues = self.run_cmd("issues")
        self.assertIn("#3    Issue 3  [bug]  <- PR #7", issues)

    def test_slow_gh_degrades_to_one_line(self):
        self.github()
        import subprocess

        def slow(args, cwd, timeout):
            raise subprocess.TimeoutExpired(args, timeout)
        board.GH_RUNNER = slow
        out = self.run_cmd("")
        self.assertIn("did not answer within", out)
        self.assertIn("Local branches", out)


class PullRequestVerdicts(BoardCase):
    def setUp(self):
        super().setUp()
        self.github()

    def blocked_pr(self):
        self.gh.add(["pr", "view", "7"], pr_view(7, closes=(3, 5)))
        self.gh.add(["pr", "diff", "7"], diff_adding_skip())

    def test_blocked_pull_request_from_its_diff(self):
        self.blocked_pr()
        out = self.run_cmd("verdict 7")
        self.assertIn("Foreman verdict for PR #7: BLOCKED", out)
        self.assertIn("[test-skipped] tests/test_x.py:2", out)
        self.assertIn("Closes: #3, #5", out)
        self.assertIn("a secret added and removed again in an earlier commit is not seen", " ".join(out.split()))
        self.assertIn("/foreman reject 7", out)

    def test_deleted_test_file_from_the_diff_headers(self):
        self.gh.add(["pr", "view", "8"], pr_view(8, files=[{"path": "tests/test_x.py", "changeType": "DELETED"}]))
        self.gh.add(["pr", "diff", "8"], "diff --git a/tests/test_x.py b/tests/test_x.py\ndeleted file mode 100644\n"
                                         "--- a/tests/test_x.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-import pytest\n"
                                         "-def test_x(): assert True\n")
        out = self.run_cmd("verdict #8")
        self.assertIn("[test-deleted] tests/test_x.py", out)

    def test_head_that_moves_while_reading_is_unknown(self):
        heads = iter([pr_view(7), {"headRefOid": "e" * 40}])
        self.gh.add(["pr", "diff", "7"], clean_diff())
        real = board.GH_RUNNER

        def runner(args, cwd, timeout):
            if args[:3] == ["pr", "view", "7"]:
                return 0, json.dumps(next(heads)), ""
            return real(args, cwd, timeout)
        board.GH_RUNNER = runner
        out = self.run_cmd("merge 7")
        self.assertIn("changed while Foreman read it", out)
        self.assertEqual(board._CTX.dispatched, [])

    def test_a_file_github_lists_counts_even_if_the_diff_hides_it(self):
        self.write(".foreman.json", '{"check": "bash scripts/check.sh"}\n')
        self.write("scripts/check.sh", "pytest\n")
        self.commit("check")
        base = self.git("rev-parse", "HEAD").strip()
        view = pr_view(7, files=[{"path": "scripts/check.sh", "changeType": "MODIFIED"}])
        view["baseRefOid"] = base
        self.gh.add(["pr", "view", "7"], view)
        self.gh.add(["pr", "diff", "7"], clean_diff())
        self.assertIn("[check-changed] scripts/check.sh", self.run_cmd("verdict 7"))

    def test_merge_refused_when_blocked(self):
        self.blocked_pr()
        out = self.run_cmd("merge 7")
        self.assertIn("Foreman will not merge PR #7: it is BLOCKED.", out)
        self.assertIn("[test-skipped] tests/test_x.py:2", out)
        self.assertIn("/foreman reject 7", out)
        self.assertEqual(board._CTX.dispatched, [])

    def test_merge_refused_when_the_verdict_cannot_be_computed(self):
        self.gh.add(["pr", "view", "7"], pr_view(7))
        self.gh.add(["pr", "diff", "7"], "", rc=1, err="HTTP 406: diff too large")
        out = self.run_cmd("merge 7")
        self.assertIn("Foreman will not merge PR #7: it cannot compute a verdict", out)
        self.assertEqual(board._CTX.dispatched, [])

    def mergeable(self):
        self.gh.add(["pr", "view", "7"], pr_view(7, closes=(3,)))
        self.gh.add(["pr", "diff", "7"], clean_diff())

    def test_clean_and_ready_versus_clean_but_not_mergeable(self):
        self.mergeable()
        out = self.run_cmd("verdict 7")
        self.assertIn("Foreman verdict for PR #7: CLEAN — ready to merge", out)
        self.assertIn("Look at the CI first (no CI checks)", " ".join(out.split()))
        self.assertNotIn("MERGEABLE", out)
        view = pr_view(8)
        view.update(mergeable="CONFLICTING", isDraft=True, statusCheckRollup=[])
        self.gh.add(["pr", "view", "8"], view)
        self.gh.add(["pr", "diff", "8"], clean_diff())
        out = self.run_cmd("verdict 8")
        self.assertIn("Foreman verdict for PR #8: CLEAN — but not mergeable yet", out)
        self.assertIn("CI: no CI checks (none run while it conflicts)", out)
        self.assertIn("it is a draft: mark it ready for review", out)
        self.assertIn("it conflicts with main: update the branch", out)
        self.assertNotIn("/foreman merge 8", out)

    def test_conflicts_draft_or_unknown_refuse_even_with_yes(self):
        for n, change, reason in ((8, {"mergeable": "CONFLICTING"}, "conflicts with main"),
                                  (9, {"isDraft": True}, "it is a draft"),
                                  (10, {"mergeable": "UNKNOWN"}, "try again in a moment")):
            view = pr_view(n)
            view.update(change)
            self.gh.add(["pr", "view", str(n)], view)
            self.gh.add(["pr", "diff", str(n)], clean_diff())
            board.bind(FakeCtx(choice="merge"))
            out = self.run_cmd("merge %d --yes" % n)
            self.assertIn("Foreman finds it CLEAN, but it is not mergeable yet", out)
            self.assertIn(reason, " ".join(out.split()))
            self.assertEqual(board._CTX.dispatched, [])
            self.assertEqual(board._CTX.asked, [])

    def test_failing_ci_is_shown_in_the_question_but_does_not_refuse(self):
        view = pr_view(7)
        view["statusCheckRollup"] = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE"}]
        self.gh.add(["pr", "view", "7"], view)
        self.gh.add(["pr", "diff", "7"], clean_diff())
        board.bind(FakeCtx(choice="merge"))
        self.assertIn("merged PR #7", self.run_cmd("merge 7"))
        self.assertTrue(board._CTX.asked[0][0].startswith("WARNING: CI failing (1 of 1)."))

    def test_ci_that_could_not_be_read_is_not_no_ci(self):
        self.assertEqual(board.ci_summary(None), "CI unknown (checks not read)")
        self.assertEqual(board.ci_summary([]), "no CI checks")

    def test_merge_asks_and_cancel_merges_nothing(self):
        self.mergeable()
        board.bind(FakeCtx(choice="cancel"))
        out = self.run_cmd("merge 7")
        self.assertIn("cancelled; PR #7 was not merged", out)
        question, choices = board._CTX.asked[0]
        self.assertIn("Merge PR #7 (fffffff, squash) into main?", question)
        self.assertIn("Closes: #3 · no CI checks", question)
        self.assertTrue(question.startswith("WARNING: no CI checks."), question)
        self.assertIn("Change things", question)
        self.assertEqual([c["label"] for c in choices], ["Merge", "Cancel"])
        self.assertEqual(board._CTX.dispatched, [])

    def test_merge_without_an_answer_does_not_merge(self):
        self.mergeable()
        for ctx in (FakeCtx(can_ask=False), FakeCtx(choice=None)):  # unavailable, or nobody answered
            board.bind(ctx)
            out = self.run_cmd("merge 7 --rebase")
            self.assertIn("PR #7 was not merged", out)
            self.assertIn("/foreman merge 7 --rebase --yes", out)
            self.assertEqual(ctx.dispatched, [])

    def test_yes_skips_the_question_but_not_the_verdict(self):
        self.blocked_pr()
        board.bind(FakeCtx(can_ask=False))
        self.assertIn("will not merge PR #7: it is BLOCKED", self.run_cmd("merge 7 --yes"))
        self.assertEqual(board._CTX.dispatched, [])

    def test_merge_with_yes_runs_without_asking(self):
        self.mergeable()
        board.bind(FakeCtx(can_ask=False))
        self.assertIn("merged PR #7 (squash)", self.run_cmd("merge 7 --yes"))
        self.assertEqual(len(board._CTX.dispatched), 1)

    def test_reject_close_asks_first(self):
        self.blocked_pr()
        board.bind(FakeCtx(can_ask=False))
        out = self.run_cmd("reject 7 --close bad")
        self.assertIn("nothing was posted on PR #7", out)
        self.assertIn("/foreman reject 7 --close --yes bad", out)
        self.assertEqual(board._CTX.dispatched, [])
        board.bind(FakeCtx(choice="comment"))
        self.run_cmd("reject 7 --close bad")
        self.assertEqual([a["command"].split(" --")[0] for _n, a in board._CTX.dispatched], ["gh pr comment 7"])

    def test_merge_runs_through_the_terminal_tool(self):
        self.gh.add(["pr", "view", "7"], pr_view(7))
        self.gh.add(["pr", "diff", "7"], clean_diff())
        board.bind(FakeCtx(choice="merge"))
        out = self.run_cmd("merge 7 --rebase")
        name, args = board._CTX.dispatched[0]
        self.assertEqual(name, "terminal")
        self.assertEqual(args["command"], "gh pr merge 7 --rebase --delete-branch --match-head-commit " + OID)
        canon = lambda p: os.path.normcase(os.path.realpath(p))
        self.assertEqual(canon(args["workdir"]), canon(self.root))
        self.assertIn("merged PR #7 (rebase) in acme/widgets", out)
        self.assertFalse(any(c[:2] == ["pr", "merge"] for c in self.gh.calls))  # never a bare subprocess

    def test_merge_denied_and_timed_out(self):
        self.gh.add(["pr", "view", "7"], pr_view(7))
        self.gh.add(["pr", "diff", "7"], clean_diff())
        board.bind(FakeCtx(result={"output": "", "exit_code": -1, "error": "Command denied by user",
                                   "status": "blocked"}, choice="merge"))
        self.assertIn("approval denied", self.run_cmd("merge 7"))
        board.bind(FakeCtx(result={"output": "", "exit_code": 124, "error": "Command timed out after 180s"},
                           choice="merge"))
        self.assertIn("timed out", self.run_cmd("merge 7"))

    def test_reject_posts_one_comment_with_the_reasons_and_the_saved_review(self):
        self.blocked_pr()
        reviews = os.path.join(grants.store_dir(), "reviews")
        os.makedirs(reviews)
        from foreman import review
        with open(review.review_path("acme/widgets", "pr", "7"), "w", encoding="utf-8") as fh:
            json.dump({"schema": review.SCHEMA_VERSION, "head": OID,
                       "findings": [{"severity": "high", "file": "app.py", "line": 4,
                                     "title": "ask @someone about the empty catch"}, "plain finding"]}, fh)
        board.bind(FakeCtx(choice="close"))
        out = self.run_cmd("reject 7 --close please fix the tests")
        ctx = board._CTX
        commands_run = [a["command"] for _n, a in ctx.dispatched]
        self.assertTrue(commands_run[0].startswith("gh pr comment 7 --body-file "))
        self.assertEqual(commands_run[1], "gh pr close 7")
        body = ctx.bodies[0]
        self.assertIn("### Foreman: changes requested", body)
        self.assertIn("- **test-skipped** `tests/test_x.py:2`: test skipped or isolated.", body)
        self.assertIn("  Fix: Remove the marker", body)
        self.assertIn("#### Model review", body)
        self.assertIn("- **high** `app.py:4` ask @\u200bsomeone about the empty catch", body)
        self.assertIn("- plain finding", body)
        self.assertIn("#### Note from the reviewer\n\nplease fix the tests", body)
        self.assertIn(body, out)  # the exact text is shown in the chat
        self.assertIn("closed PR #7", out)
        self.assertEqual(os.listdir(os.path.join(grants.store_dir(), "outbox")), [])

    def test_hostile_file_names_cannot_mention_link_or_break_out(self):
        # git C-quotes a name with line breaks; Foreman decodes it back to the real name.
        name = "tests/test_a\\n\\n@victim x #12 https://evil.example/p.py"
        diff = ('diff --git "a/%s" "b/%s"\nnew file mode 100644\n--- /dev/null\n+++ "b/%s"\n'
                "@@ -0,0 +1 @@\n+%s\n" % (name, name, name, SKIP))
        self.gh.add(["pr", "view", "7"], pr_view(7))
        self.gh.add(["pr", "diff", "7"], diff)
        self.run_cmd("reject 7")
        body = board._CTX.bodies[0]
        findings = [l for l in body.splitlines() if l.startswith("- **")]
        self.assertEqual(len(findings), 1)  # the file name stayed on its line
        self.assertNotRegex(body, r"(?<![\w])@victim")
        self.assertIn("@\u200bvictim", findings[0])
        self.assertIn("#\u200b12", findings[0])
        self.assertIn("https:\u200b//evil", findings[0])

    def test_no_mentions_keeps_code_spans_closed(self):
        self.assertEqual(board._no_mentions("`cc @octocat` and @org/team, GH-4, #9, mail a@b.io"),
                         "`cc @\u200boctocat` and @\u200borg/team, GH\u200b-4, #\u200b9, mail a@\u200bb.io")
        self.assertEqual(board._no_mentions("o/r#12 caf\u00e9@x _https://e.io_ &#64;u [a](//e) <b>"),
                         "o/r#\u200b12 caf\u00e9@\u200bx _https:\u200b//e.io_ &amp;#\u200b64;u \\[a\\](//e) &lt;b&gt;")
        self.assertEqual(board._no_mentions("a/[b] & @c", code=True), "a/[b] & @\u200bc")
        self.assertEqual(board._no_mentions("a\r\nb\x00c\u2028d"), "a b c d")
        self.assertEqual(board._no_mentions("see www.x.io and http://y"), "see www\u200b.x.io and http:\u200b//y")

    def test_a_stale_saved_review_is_not_posted_and_a_branch_review_is(self):
        self.blocked_pr()
        from foreman import review
        os.makedirs(os.path.join(grants.store_dir(), "reviews"))

        def save(kind, ref, head, text, root=""):
            with open(review.review_path("acme/widgets", kind, ref, root), "w", encoding="utf-8") as fh:
                json.dump({"schema": review.SCHEMA_VERSION, "head": head, "findings": [text]}, fh)
        save("pr", "7", "e" * 40, "from an older commit")
        self.run_cmd("reject 7")
        self.assertNotIn("older commit", board._CTX.bodies[0])
        self.assertNotIn("#### Model review", board._CTX.bodies[0])
        save("branch", "feature", OID, "reviewed on the branch", root=detector.find_repo(self.root))
        board.bind(FakeCtx())
        self.run_cmd("reject 7")
        self.assertIn("- reviewed on the branch", board._CTX.bodies[0])

    def test_a_merge_moved_to_the_background_is_not_reported_failed(self):
        self.gh.add(["pr", "view", "7"], pr_view(7))
        self.gh.add(["pr", "diff", "7"], clean_diff())
        board.bind(FakeCtx(result={"output": "", "exit_code": None, "error": None,
                                   "status": "yielded_to_background", "session_id": "proc_1"}))
        out = self.run_cmd("merge 7 --yes")
        self.assertNotIn("failed", out)
        self.assertNotIn("nothing was changed", out)
        self.assertIn("still running", out)
        self.assertIn("`/foreman verdict 7` shows MERGED", out)

    def test_reject_of_a_mergeable_pull_request_needs_a_note(self):
        self.gh.add(["pr", "view", "7"], pr_view(7))
        self.gh.add(["pr", "diff", "7"], clean_diff())
        self.assertIn("say why: `/foreman reject 7 <note>`", self.run_cmd("reject 7"))
        self.assertEqual(board._CTX.dispatched, [])
        self.run_cmd("reject 7 wrong approach")
        self.assertIn("found no blockers at `fffffff`; the reviewer rejects it", board._CTX.bodies[0])

    def test_reject_not_posted_shows_the_text(self):
        self.blocked_pr()
        board.bind(FakeCtx(result={"output": "", "exit_code": -1, "error": "denied", "status": "blocked"}))
        out = self.run_cmd("reject 7")
        self.assertIn("The comment was NOT posted on PR #7 (acme/widgets)", out)
        self.assertIn("### Foreman: changes requested", out)

    def test_local_head_uses_the_full_check(self):
        self.git("checkout", "-q", "-b", "feature")
        self.write("tests/test_x.py", "import pytest\n" + SKIP + "\ndef test_x(): assert True\n")
        self.commit("switch it off")
        head = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-q", "main")
        self.gh.add(["pr", "view", "7"], pr_view(7, head=head))
        out = self.run_cmd("verdict 7")
        self.assertIn("BLOCKED", out)
        self.assertNotIn("Inspected from GitHub's diff", out)
        self.assertFalse(any(c[:2] == ["pr", "diff"] for c in self.gh.calls))


class Use(BoardCase):
    def test_pick_falls_back_to_a_numbered_list(self):
        board.bind(FakeCtx(can_ask=False))
        out = self.run_cmd("use")
        self.assertRegex(out, r"1\. .*repo\n")
        self.assertIn("Type `/foreman use <number>` or `/foreman use <path>`.", out)
        self.assertIn("pinned", self.run_cmd("use 1"))

    def test_pick_with_hermes_choice(self):
        other = os.path.join(self.tmp, "other")
        os.makedirs(other)
        self.git("init", "-q", cwd=other)
        board.pin(other, ("old-session",))  # makes it a recent repository
        picked = []

        def choose(choices):
            picked.append(next(c["value"] for c in choices if c["label"] == "other"))
            return picked[0]
        board.bind(FakeCtx(choice=choose))
        out = self.run_cmd("use")
        self.assertIn("pinned %s" % picked[0], out)
        self.assertEqual(board.pinned(KEYS), picked[0])
        self.assertIn("Which repository", board._CTX.asked[0][0])

    def test_use_a_path_that_is_not_a_repository(self):
        self.assertIn("is not inside a git repository", self.run_cmd("use " + self.tmp))

    def test_status_uses_the_pinned_repository(self):
        out = self.run_cmd("status")
        self.assertRegex(out, r"Repository: .*repo \(from the repository pinned with /foreman use\)")

    def test_nothing_resolved_hints_at_use(self):
        old_locate, old_pinned = gate.locate, board.pinned
        gate.locate = lambda *a, **k: (None, None)
        board.pinned = lambda keys=(): None
        try:
            out = self.run_cmd("")
        finally:
            gate.locate, board.pinned = old_locate, old_pinned
        self.assertIn(gate.NO_REPOSITORY_HERE, out)
        self.assertIn("/foreman use", out)


class StoreGuard(BoardCase):
    def test_the_agent_cannot_touch_the_pin_file_the_outbox_or_the_reviews(self):
        store = grants.store_dir()
        paths = [os.path.join(store, board.STORE_FILE), os.path.join(store, "outbox", "reject-7-x.md"),
                 os.path.join(store, "reviews", "acme__widgets__7.json"),
                 "/home/u/.hermes/plugin-data/foreman/reviews/a.json"]
        for path in paths:
            d = gate.on_pre_tool_call(tool_name="write_file", args={"path": path, "content": "{}"})
            self.assertEqual(d and d["action"], "block", path)
            d = gate.on_pre_tool_call(tool_name="terminal", args={"command": 'rm "%s"' % path})
            self.assertEqual(d and d["action"], "block", path)
        patch = "*** Begin Patch\n*** Add File: %s\n+{}\n*** End Patch\n" % paths[0]
        self.assertEqual(gate.on_pre_tool_call(tool_name="patch", args={"mode": "patch", "patch": patch})["action"],
                         "block")

    def test_the_agent_cannot_post_an_outbox_file_either(self):
        # /foreman reject's own `gh pr comment` runs through ctx.dispatch_tool, which does not fire pre_tool_call
        # (tools.registry.dispatch calls the handler directly), so it needs no exemption; the same command from the
        # agent names Foreman's store and is refused.
        path = os.path.join(grants.store_dir(), "outbox", "reject-7-abc_12.md").replace("\\", "/")
        d = gate.on_pre_tool_call(tool_name="terminal", args={"command": 'gh pr comment 7 --body-file "%s"' % path})
        self.assertEqual(d and d["action"], "block")

    def test_an_ordinary_reviews_folder_is_not_protected(self):
        d = gate.on_pre_tool_call(tool_name="write_file",
                                  args={"path": os.path.join(self.root, "reviews", "a.md"), "content": "x"})
        self.assertIsNone(d)


class DiffFindings(unittest.TestCase):
    def test_name_status_from_the_diff_headers(self):
        diff = ("diff --git a/tests/test_a.py b/tests/test_a.py\ndeleted file mode 100644\n--- a/tests/test_a.py\n"
                "+++ /dev/null\n"
                "diff --git a/tests/test_b.py b/lib/b.py\nsimilarity index 100%\nrename from tests/test_b.py\n"
                "rename to lib/b.py\n"
                "diff --git a/new.py b/new.py\nnew file mode 100644\n--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+x\n")
        self.assertEqual(detector.name_status_from_diff(diff).splitlines(),
                         ["D\ttests/test_a.py", "R100\ttests/test_b.py\tlib/b.py", "A\tnew.py"])
        rules = sorted(f.rule for f in detector.findings_from_diff(diff))
        self.assertEqual(rules, ["test-deleted", "test-moved"])

    def test_content_lines_that_look_like_headers_do_not_rename_the_file(self):
        # A changed check script whose new content holds the line "++ b/README.md": in the diff it reads
        # "+++ b/README.md", which must not be taken for a header.
        diff = ("diff --git a/scripts/check.sh b/scripts/check.sh\n--- a/scripts/check.sh\n+++ b/scripts/check.sh\n"
                "@@ -1 +1,4 @@\n-pytest\n+exit 0\n+cat <<EOF\n+++ b/README.md\n+-- a/x\n")
        self.assertEqual(detector.name_status_from_diff(diff), "M\tscripts/check.sh")
        rules = [f.rule for f in detector.findings_from_diff(
            diff, check="bash scripts/check.sh", base_is_file=lambda p: p == "scripts/check.sh",
            base_text=lambda p: "pytest\n")]
        self.assertEqual(rules, ["check-changed"])

    def test_apply_file_diff(self):
        old = "a\nb\nc\n"
        diff = "--- a/f\n+++ b/f\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n"
        self.assertEqual(detector.apply_file_diff(old, diff), "a\nB\nc\n")
        self.assertIsNone(detector.apply_file_diff("x\n", diff))

    def test_package_json_only_its_scripts_count(self):
        base = '{\n  "scripts": {"test": "jest"},\n  "dependencies": {"a": "1"}\n}\n'
        deps = ("diff --git a/package.json b/package.json\n--- a/package.json\n+++ b/package.json\n"
                "@@ -1,4 +1,4 @@\n {\n   \"scripts\": {\"test\": \"jest\"},\n-  \"dependencies\": {\"a\": \"1\"}\n"
                "+  \"dependencies\": {\"a\": \"2\"}\n }\n")
        scripts = ("diff --git a/package.json b/package.json\n--- a/package.json\n+++ b/package.json\n"
                   "@@ -1,4 +1,4 @@\n {\n-  \"scripts\": {\"test\": \"jest\"},\n+  \"scripts\": {\"test\": \"true\"},\n"
                   "   \"dependencies\": {\"a\": \"1\"}\n }\n")
        self.assertIn('"test": "true"', detector.apply_file_diff(base, scripts))
        kw = dict(check="npm test", base_is_file=lambda p: p == "package.json", base_text=lambda p: base)
        self.assertEqual(detector.findings_from_diff(deps, **kw), [])
        self.assertEqual([f.rule for f in detector.findings_from_diff(scripts, **kw)], ["check-changed"])

    def test_secret_in_a_remote_diff(self):
        token = "gh" + "p_" + "A1b2C3d4" * 5
        diff = "diff --git a/c.py b/c.py\n--- a/c.py\n+++ b/c.py\n@@ -0,0 +1 @@\n+T = '%s'\n" % token
        self.assertEqual([f.rule for f in detector.findings_from_diff(diff)], ["secret"])


if __name__ == "__main__":
    unittest.main()
