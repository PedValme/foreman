"""The pipeline: its state file, every transition, the review cache, merge with the review (auto_review: merge), the
finish loop and the foreman_review tool, the single verdict vocabulary. Fakes only: no model, no network, and a
fixed clock (no test depends on real time)."""
import json
import os
import re
import types
import unittest
from unittest import mock

from tests_support import GitRepoCase  # first: it puts plugin/ on sys.path
from foreman import board, commands, finish, gate, grants, pipeline, review, verdicts

SKIP = "@pytest.mark." + "skip"
KEYS = ("session-1",)
NOW = 1_700_000_000
MAIN = {"model": {"provider": "mainprov", "default": "main-model"}}
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class FakeLlm:
    def __init__(self, parsed=None, exc=None):
        self.parsed, self.exc, self.calls = parsed, exc, []

    def complete_structured(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return types.SimpleNamespace(text=json.dumps(self.parsed), parsed=self.parsed, provider="mainprov",
                                     model="main-model")


class FakeCtx:
    """ctx.llm for the reviewer, ask_choice and dispatch_tool for merge."""

    def __init__(self, llm=None, choice=None, can_ask=True):
        self.llm, self._choice, self.asked, self.dispatched = llm, choice, [], []
        if can_ask:
            self.ask_choice = self._ask

    def _ask(self, question, choices):
        self.asked.append((question, choices))
        return self._choice

    def has_capability(self, capability):
        return False

    def get_config(self, key, default=None):
        return default

    def dispatch_tool(self, name, args, **kwargs):
        self.dispatched.append((name, dict(args)))
        return json.dumps({"output": "ok", "exit_code": 0, "error": None})


def answer(findings=(), verdict="PASS"):
    return {"findings": list(findings), "summary": "s", "verdict": verdict}


def finding(severity, file, evidence, title="Problem", line=1):
    return {"severity": severity, "file": file, "line": line, "title": title, "why": "because",
            "evidence": evidence, "fix": "do it right"}


class PipelineCase(GitRepoCase):
    def setUp(self):
        super().setUp()
        self._saved = (pipeline.CLOCK, pipeline.SETTINGS_OVERRIDE, pipeline.NOTIFIER, review.CLOCK, review._CTX,
                       board._CTX, board.GH_RUNNER)
        self.clock = [NOW]
        pipeline.CLOCK = lambda: self.clock[0]
        review.CLOCK = lambda: self.clock[0]
        self.settings = {"auto_review": "merge"}
        pipeline.SETTINGS_OVERRIDE = self.settings
        self.sent = []
        pipeline.NOTIFIER = self.sent.append
        self.cfg = mock.patch.object(review, "hermes_config", return_value=MAIN)
        self.cfg.start()

    def tearDown(self):
        self.cfg.stop()
        (pipeline.CLOCK, pipeline.SETTINGS_OVERRIDE, pipeline.NOTIFIER, review.CLOCK, review._CTX, board._CTX,
         board.GH_RUNNER) = self._saved
        super().tearDown()

    def tick(self, seconds=60):
        self.clock[0] += seconds

    def ref(self, kind="pr", number=6, branch="feat/x", head="a" * 40):
        return pipeline.Ref("acme/widgets", self.root, kind, number if kind == "pr" else None, branch=branch,
                            title="Fix the parser", url="https://github.com/acme/widgets/pull/6" if kind == "pr"
                            else None, head=head)


# ─── The state file ──────────────────────────────────────────────────────────

class Shape(PipelineCase):
    def check_shape(self, data):
        self.assertEqual(set(data), {"version", "items"})
        self.assertEqual(data["version"], 1)
        for item in data["items"]:
            self.assertEqual(set(item), {"id", "repo", "root", "target", "head", "stage", "stages", "bounces",
                                         "max_bounces", "updated", "events"})
            self.assertRegex(item["id"], r"^[^#]+#(pr:\d+|branch:.+)$")
            t = item["target"]
            self.assertEqual(set(t), {"kind", "number", "branch", "title", "url"})
            self.assertIn(t["kind"], ("pr", "branch"))
            if t["kind"] == "branch":
                self.assertIsNone(t["number"])
                self.assertIsNone(t["url"])
            else:
                self.assertIsInstance(t["number"], int)
            self.assertIn(item["stage"], pipeline.STAGES)
            self.assertEqual([s["name"] for s in item["stages"]], ["gate", "review", "owner", "merge"])
            for s in item["stages"]:
                keys = {"name", "status", "detail", "at"} | ({"model"} if s["name"] == "review" else set())
                self.assertEqual(set(s), keys)
                self.assertIn(s["status"], pipeline.STATUSES[s["name"]])
                self.assertRegex(s["at"], ISO)
            self.assertIsInstance(item["bounces"], int)
            self.assertIsInstance(item["max_bounces"], int)
            self.assertRegex(item["updated"], ISO)
            self.assertLessEqual(len(item["events"]), pipeline.MAX_EVENTS)
            for e in item["events"]:
                self.assertEqual(set(e), {"at", "text"})
                self.assertRegex(e["at"], ISO)

    def test_the_file_has_the_contract_s_shape(self):
        pipeline.record_gate(self.ref(), "fail", "1 blocker(s): test-skipped", "Gate blocked the commit")
        pipeline.record_gate(self.ref("branch", branch="other"), "pass", "CLEAN", "Gate passed")
        with open(os.path.join(grants.store_dir(), "pipeline.json"), encoding="utf-8") as fh:
            on_disk = json.load(fh)
        self.check_shape(on_disk)
        self.assertEqual(on_disk, pipeline.snapshot())
        branch = next(i for i in on_disk["items"] if i["target"]["kind"] == "branch")
        self.assertEqual(branch["id"], "acme/widgets#branch:other")
        self.assertEqual(branch["updated"], "2023-11-14T22:13:20Z")

    def test_every_transition(self):
        ref = self.ref()
        pipeline.record_gate(ref, "fail", "1 blocker(s): test-skipped", "Gate blocked the commit")
        self.assertEqual(pipeline.get(ref.id)["stage"], "gate")
        pipeline.record_gate(ref, "pass", "CLEAN", "Gate passed")
        self.assertEqual(pipeline.get(ref.id)["stage"], "review")
        bad = {"verdict": "BLOCKED", "findings": [finding("BLOCKING", "a.py", "x"), finding("HIGH", "a.py", "y")],
               "cache_key": "k1", "model": {"provider": "p", "model": "m"}}
        pipeline.record_review(ref, bad, bounce=True)
        item = pipeline.get(ref.id)
        self.assertEqual((item["stage"], item["bounces"]), ("bounced", 1))
        self.assertEqual(pipeline.stage_of(item, "review")["model"], "p/m")
        self.assertEqual(pipeline.stage_of(item, "review")["detail"], "1 blocking, 1 high")
        pipeline.record_review(ref, bad, bounce=True)  # the same diff never counts twice
        self.assertEqual(pipeline.get(ref.id)["bounces"], 1)
        pipeline.record_review(ref, {"verdict": "PASS", "findings": [], "cache_key": "k2"})
        item = pipeline.get(ref.id)
        self.assertEqual((item["stage"], item["bounces"]), ("ready", 1))  # the history of bounces stays
        pipeline.record_waiting(ref)
        self.assertEqual(pipeline.get(ref.id)["stage"], "awaiting_owner")
        pipeline.record_merge_refused(ref, "`gh pr merge` denied")
        self.assertEqual(pipeline.stage_of(pipeline.get(ref.id), "merge")["status"], "refused")
        pipeline.record_merged(ref, "squash")
        item = pipeline.get(ref.id)
        self.assertEqual(item["stage"], "merged")
        self.assertEqual([pipeline.stage_of(item, n)["status"] for n in ("owner", "merge")], ["approved", "done"])
        self.assertEqual([e["kind"] for e in self.sent], ["ready", "merged"])
        other = self.ref(number=7, branch="feat/y")
        pipeline.record_rejected(other, "tests rigged", closed=True)
        item = pipeline.get(other.id)
        self.assertEqual((item["stage"], pipeline.stage_of(item, "owner")["status"]), ("rejected", "rejected"))
        self.assertEqual(self.sent[-1]["kind"], "rejected")
        self.assertIn("Rejected and closed: tests rigged", item["events"][-1]["text"])

    def test_notification_event_and_once_per_head(self):
        ref = self.ref()
        pipeline.record_gate(ref, "pass", "CLEAN")
        ok = {"verdict": "PASS", "findings": [], "cache_key": "k"}
        pipeline.record_review(ref, ok)
        pipeline.record_review(ref, ok)
        self.assertEqual(len(self.sent), 1)
        e = self.sent[0]
        self.assertEqual(set(e), {"kind", "id", "repo", "root", "target", "head", "summary", "actions"})
        self.assertEqual((e["kind"], e["id"], e["repo"], e["head"]), ("ready", "acme/widgets#pr:6", "acme/widgets",
                                                                     "a" * 40))
        self.assertEqual(e["actions"], [{"label": "Merge", "command": "/foreman merge 6 --yes"},
                                        {"label": "Reject", "command": "/foreman reject 6"}])
        new_head = self.ref(head="b" * 40)
        pipeline.record_gate(new_head, "pass", "CLEAN")
        self.assertEqual(pipeline.stage_of(pipeline.get(ref.id), "review")["status"], "pending")  # another head
        pipeline.record_review(new_head, ok)
        self.assertEqual([e["head"] for e in self.sent], ["a" * 40, "b" * 40])

    def test_without_a_notifier_module_nothing_fails(self):
        pipeline.NOTIFIER = None
        ref = self.ref()
        pipeline.record_gate(ref, "pass", "CLEAN")
        pipeline.record_review(ref, {"verdict": "PASS", "findings": []})  # foreman.notify may not exist
        self.assertEqual(pipeline.get(ref.id)["stage"], "ready")

    def test_a_branch_and_its_pull_request_are_one_line(self):
        pipeline.record_gate(self.ref("branch", branch="feat/x"), "fail", "1 blocker(s): secret", "blocked")
        pipeline.record_gate(self.ref("pr"), "pass", "CLEAN", "PR clean")
        pipeline.record_gate(self.ref("branch", branch="feat/x"), "pass", "CLEAN", "commit ok")
        items = pipeline.snapshot()["items"]
        self.assertEqual([i["id"] for i in items], ["acme/widgets#pr:6"])
        self.assertEqual(items[0]["target"]["url"], "https://github.com/acme/widgets/pull/6")
        self.assertEqual(items[0]["events"][0]["text"], "blocked")

    def test_corrupt_or_missing_file_starts_empty(self):
        path = os.path.join(grants.store_dir(), "pipeline.json")
        for junk in ("{not json", "[1, 2]", json.dumps({"version": 9, "items": []}),
                     json.dumps({"version": 1, "items": [{"id": 3}, "x"]})):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(junk)
            self.assertEqual(pipeline.snapshot(), {"version": 1, "items": []})
        with open(os.path.join(grants.store_dir(), "pipeline-meta.json"), "w", encoding="utf-8") as fh:
            fh.write("garbage")
        pipeline.record_gate(self.ref(), "pass", "CLEAN")
        self.assertEqual(len(pipeline.snapshot()["items"]), 1)

    def test_a_store_that_cannot_be_written_never_raises(self):
        with mock.patch.object(pipeline, "_write", side_effect=OSError("disk full")):
            pipeline.record_gate(self.ref(), "fail", "x", "y")
            self.assertIsNone(pipeline.nudge_mark("i", "k") or None)

    def test_caps_events_and_items_dropping_finished_ones_first(self):
        ref = self.ref()
        for i in range(60):
            pipeline.record_event(ref, "event %d" % i)
        events = pipeline.get(ref.id)["events"]
        self.assertEqual(len(events), pipeline.MAX_EVENTS)
        self.assertEqual(events[-1]["text"], "event 59")
        with mock.patch.object(pipeline, "MAX_ITEMS", 5):
            for n in range(1, 4):
                self.tick()
                pipeline.record_merged(self.ref(number=100 + n, branch="m%d" % n), "squash")
            for n in range(1, 4):
                self.tick()
                pipeline.record_gate(self.ref(number=200 + n, branch="o%d" % n), "pass", "CLEAN")
        ids = [i["id"] for i in pipeline.snapshot()["items"]]
        self.assertEqual(len(ids), 5)
        # the two oldest finished ones go, even though an active one (pr:6) is older
        self.assertEqual(sorted(ids), ["acme/widgets#pr:103", "acme/widgets#pr:201", "acme/widgets#pr:202",
                                       "acme/widgets#pr:203", "acme/widgets#pr:6"])

    def test_views_fit_80_columns_and_are_ascii(self):
        ref = self.ref()
        pipeline.record_gate(ref, "fail", "1 blocker(s): test-skipped",
                             "Gate blocked `git commit`: test skipped in tests/test_x.py:9")
        pipeline.record_gate(ref, "pass", "CLEAN", "Gate passed")
        pipeline.record_review(ref, {"verdict": "BLOCKED", "cache_key": "k", "findings": [
            finding("BLOCKING", "a.py", "x"), finding("BLOCKING", "a.py", "y"), finding("HIGH", "a.py", "z")]},
            bounce=True)
        item = pipeline.get(ref.id)
        self.assertEqual(pipeline.line(item),
                         "gate ok > review FAIL (2 blocking, 1 high) > bounced 1/3 > owner - > merge -")
        text = pipeline.format_item(item) + "\n" + "\n".join(pipeline.board_lines("acme/widgets", self.root))
        for l in text.splitlines():
            self.assertLessEqual(len(l), 80, l)
        text.encode("ascii")
        self.assertNotIn("\x1b", text)
        self.assertIn("Review sent it back (2 blocking, 1 high), bounce 1/3", text)


class PanelAndNotifier(PipelineCase):
    """The two consumers: the Desktop panel reads pipeline.json through panel_api; the notifier gets one event."""

    def test_gate_review_fail_bounce_review_pass_ready(self):
        from foreman import panel_api
        changed = []
        with mock.patch.object(panel_api, "notify_changed", side_effect=lambda: changed.append(1) or True):
            ref = self.ref()
            pipeline.record_gate(ref, "pass", "CLEAN", "Gate passed `git push`")
            self.tick()
            bad = {"verdict": "BLOCKED", "cache_key": "k1", "model": {"provider": "p", "model": "m"},
                   "findings": [finding("BLOCKING", "a.py", "x"), finding("HIGH", "a.py", "y")]}
            pipeline.record_review(ref, bad, bounce=True)
            self.tick()
            pipeline.record_review(ref, {"verdict": "PASS", "findings": [], "cache_key": "k2",
                                         "model": {"provider": "p", "model": "m"}}, bounce=True)
        self.assertEqual(len(changed), 3)  # the panel is told after each write
        snap = panel_api.read_snapshot(os.path.join(grants.store_dir(), "pipeline.json"))
        self.assertIsNone(snap["problem"])
        [item] = snap["items"]
        self.assertEqual((item["id"], item["stage"], item["bounces"], item["max_bounces"]),
                         ("acme/widgets#pr:6", "ready", 1, 3))
        self.assertEqual([(s["name"], s["status"]) for s in item["stages"]],
                         [("gate", "pass"), ("review", "pass"), ("owner", "pending"), ("merge", "pending")])
        self.assertEqual(item["stages"][1]["model"], "p/m")
        self.assertEqual(item["head"], "a" * 40)
        self.assertEqual(item["target"]["url"], "https://github.com/acme/widgets/pull/6")
        self.assertEqual([e["text"] for e in item["events"]],
                         ["Gate passed `git push`", "Review sent it back (1 blocking, 1 high), bounce 1/3",
                          "Review passed (no findings)"])
        ready = [e for e in self.sent if e["kind"] == "ready"]
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0]["root"], self.root)
        self.assertEqual(ready[0]["target"]["number"], 6)


class StoreGuard(PipelineCase):
    def test_the_agent_cannot_write_the_pipeline_but_a_ci_pipeline_json_is_fine(self):
        store = grants.store_dir()
        for name in ("pipeline.json", "pipeline-meta.json"):
            path = os.path.join(store, name)
            self.assertTrue(gate._is_store_path(path))
            d = gate.on_pre_tool_call("write_file", {"path": path, "content": "{}"})
            self.assertEqual(d["action"], "block")
            d = gate.on_pre_tool_call("terminal", {"command": 'echo {} > "%s"' % path})
            self.assertEqual(d["action"], "block")
        self.assertFalse(gate._is_store_path(os.path.join(self.root, "ci", "pipeline.json")))
        self.assertIsNone(gate.on_pre_tool_call("terminal", {"command": "cat ci/pipeline.json"}))


# ─── The review cache ────────────────────────────────────────────────────────

class ReviewCache(PipelineCase):
    def setUp(self):
        super().setUp()
        self.write("app/calc.py", "def add(a, b):\n    return a + b\n")
        self.write("tests/test_calc.py", "from app.calc import add\n\n\ndef test_add():\n    assert add(2, 2) == 4\n")
        self.commit("base")
        self.git("checkout", "-q", "-b", "feature")
        self.write("app/calc.py", "def add(a, b):\n    return a + b + 1\n")

    def run_review(self, llm, **kw):
        return review.run_review("", ctx=FakeCtx(llm), where=self.root, **kw)

    def test_same_diff_is_never_reviewed_twice(self):
        first = FakeLlm(parsed=answer())
        r1 = self.run_review(first)
        self.assertEqual((r1["verdict"], r1["cached"], len(first.calls)), ("PASS", False, 1))
        self.assertRegex(r1["diff_sha"], r"^[0-9a-f]{64}$")
        second = FakeLlm(parsed=answer([finding("BLOCKING", "app/calc.py", "return a + b + 1")], "BLOCK"))
        r2 = self.run_review(second)
        self.assertEqual(second.calls, [])
        self.assertEqual((r2["verdict"], r2["cached"]), ("PASS", True))
        self.assertIn("the model was not called again", review.format_review(r2))
        r3 = self.run_review(second, fresh=True)  # a person's --fresh
        self.assertEqual((len(second.calls), r3["verdict"]), (1, "BLOCKED"))
        self.write("app/calc.py", "def add(a, b):\n    return a + b + 2\n")  # a changed diff
        third = FakeLlm(parsed=answer())
        self.assertFalse(self.run_review(third)["cached"])
        self.assertEqual(len(third.calls), 1)

    def test_going_back_to_a_reviewed_diff_is_not_a_re_roll(self):
        llm = FakeLlm(parsed=answer())
        self.run_review(llm)                                                   # diff A
        self.write("app/calc.py", "def add(a, b):\n    return a + b + 9\n")
        self.run_review(llm)                                                   # diff B
        self.write("app/calc.py", "def add(a, b):\n    return a + b + 1\n")
        self.assertTrue(self.run_review(llm)["cached"])                        # A again
        self.assertEqual(len(llm.calls), 2)

    def test_without_permission_the_model_is_never_called(self):
        llm = FakeLlm(parsed=answer())
        r = self.run_review(llm, allow_model=False)
        self.assertEqual((r["verdict"], llm.calls), (review.NOT_REVIEWED, []))
        self.assertNotIn("saved", r)

    def test_a_failed_call_is_not_cached(self):
        self.assertEqual(self.run_review(FakeLlm(exc=TimeoutError("slow")))["verdict"], "COULD NOT RUN")
        llm = FakeLlm(parsed=answer())
        self.assertEqual(self.run_review(llm)["verdict"], "PASS")
        self.assertEqual(len(llm.calls), 1)

    def test_slash_fresh_is_parsed(self):
        review._CTX = FakeCtx(FakeLlm(parsed=answer()))
        board.pin(self.root)
        review.cmd_review("")
        out = review.cmd_review("--fresh")
        self.assertEqual(len(review._CTX.llm.calls), 2)
        self.assertNotIn("stored result", out)
        self.assertEqual(pipeline.items_for(root=self.root)[0]["stage"], "ready")


# ─── /foreman merge with the review (auto_review: merge) ─────────────────────

OID = "f" * 40


def pr_view(number=7, head=OID):
    return {"number": number, "title": "Change things", "headRefName": "feature", "isDraft": False,
            "url": "https://github.com/acme/widgets/pull/%d" % number, "closingIssuesReferences": [],
            "statusCheckRollup": [], "mergeable": "MERGEABLE", "state": "OPEN", "headRefOid": head,
            "baseRefName": "main", "commits": [], "files": []}


DIFF = ("diff --git a/app.py b/app.py\nindex 1111111..2222222 100644\n--- a/app.py\n+++ b/app.py\n"
        "@@ -1 +1,2 @@\n x = 1\n+value = compute_total(1, 2)\n")


class FakeGh:
    def __init__(self, view):
        self.view, self.calls = view, []

    def __call__(self, args, cwd, timeout):
        self.calls.append(list(args))
        if args[:2] == ["repo", "view"]:
            return 0, json.dumps({"nameWithOwner": "acme/widgets"}), ""
        if args[:2] == ["pr", "view"]:
            return 0, json.dumps(self.view), ""
        if args[:2] == ["pr", "diff"]:
            return 0, DIFF, ""
        if args[:2] in (["pr", "list"], ["issue", "list"]):
            return 0, "[]", ""
        return 1, "", "unexpected"


class MergeWithReview(PipelineCase):
    def setUp(self):
        super().setUp()
        self.write("app.py", "x = 1\n")
        self.write("tests/test_x.py", "def test_x(): assert True\n")
        self.commit("base")
        self.git("remote", "add", "origin", "https://github.com/acme/widgets.git")
        board.pin(self.root, KEYS)
        board.GH_RUNNER = FakeGh(pr_view())

    def merge(self, llm, args="merge 7", choice="merge", can_ask=True):
        ctx = FakeCtx(llm, choice=choice, can_ask=can_ask)
        review._CTX = ctx
        board.bind(ctx)
        return ctx, commands.handle_slash(args, session_key=KEYS[0])

    def test_verified_blocking_finding_refuses_even_with_yes(self):
        llm = FakeLlm(parsed=answer([finding("BLOCKING", "app.py", "value = compute_total(1, 2)",
                                             "Wrong total")], "BLOCK"))
        ctx, out = self.merge(llm, "merge 7 --yes")
        self.assertIn("Foreman will not merge PR #7: the second-model review found blocking problems", out)
        self.assertIn("BLOCKING app.py:1 — Wrong total", out)
        self.assertEqual(ctx.dispatched, [])
        self.assertEqual(len(llm.calls), 1)
        item = pipeline.get("acme/widgets#pr:7")
        self.assertEqual((item["stage"], pipeline.stage_of(item, "merge")["status"]), ("bounced", "refused"))
        ctx, _out = self.merge(llm, "merge 7 --yes")  # asked again, same head: the stored review, no new call
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(ctx.dispatched, [])

    def test_notes_are_in_the_question(self):
        llm = FakeLlm(parsed=answer([finding("HIGH", "app.py", "value = compute_total(1, 2)", "Overflow")],
                                    "CONCERNS"))
        ctx, out = self.merge(llm, choice="merge")
        question = ctx.asked[0][0]
        self.assertTrue(question.startswith("Review notes:\n"), question)
        self.assertIn("\n  HIGH app.py:1 — Overflow\n", question)
        self.assertIn(review.SAME_MODEL, question)  # the fake ctx grants no other model
        self.assertIn("merged PR #7", out)
        self.assertIn("reviewed PR #7 at fffffff with the second model first", " ".join(out.split()))
        self.assertEqual(pipeline.get("acme/widgets#pr:7")["stage"], "merged")
        self.assertEqual([e["kind"] for e in self.sent], ["merged"])

    def test_could_not_run_is_the_first_line_and_a_person_decides(self):
        ctx, out = self.merge(FakeLlm(exc=TimeoutError("timed out")), choice="cancel")
        self.assertTrue(ctx.asked[0][0].startswith("The second-model review could not run (TimeoutError: timed "
                                                   "out). A person decides"), ctx.asked[0][0])
        self.assertIn("cancelled", out)
        self.assertEqual(ctx.dispatched, [])
        ctx, out = self.merge(FakeLlm(exc=TimeoutError("timed out")), choice="merge")
        self.assertEqual(len(ctx.dispatched), 1)

    def test_unattended_could_not_run_merges_nothing_even_with_yes(self):
        ctx, out = self.merge(FakeLlm(exc=TimeoutError("timed out")), "merge 7 --yes", can_ask=False)
        self.assertEqual(ctx.dispatched, [])
        self.assertIn("PR #7 was not merged: the second-model review could not run", " ".join(out.split()))

    def test_clean_review_with_yes_merges_without_asking(self):
        ctx, out = self.merge(FakeLlm(parsed=answer()), "merge 7 --yes", can_ask=False)
        self.assertEqual(len(ctx.dispatched), 1)
        self.assertIn("merged PR #7 (squash)", out)

    def test_the_same_diff_at_a_new_head_needs_no_new_review(self):
        llm = FakeLlm(parsed=answer())
        ctx, _out = self.merge(llm, choice="cancel")
        board.GH_RUNNER = FakeGh(pr_view(head="e" * 40))  # GitHub's "Update branch": same diff, new head
        ctx, out = self.merge(llm, "merge 7 --yes", can_ask=False)
        self.assertEqual(len(llm.calls), 1)
        self.assertIn("stored review of this exact diff", " ".join(out.split()))
        self.assertEqual(ctx.dispatched[0][1]["command"].split()[-1], "e" * 40)

    def test_off_does_not_review(self):
        self.settings["auto_review"] = "off"
        llm = FakeLlm(parsed=answer())
        ctx, out = self.merge(llm, "merge 7 --yes", can_ask=False)
        self.assertEqual(llm.calls, [])
        self.assertEqual(len(ctx.dispatched), 1)

    def test_review_of_another_head_refuses(self):
        llm = FakeLlm(parsed=answer())
        with mock.patch.object(review, "run_review", return_value={
                "verdict": "PASS", "head": "e" * 40, "findings": [], "target": {"kind": "pr", "ref": "7"}}):
            ctx, out = self.merge(llm, "merge 7 --yes", can_ask=False)
        self.assertIn("not of the pull request's head", " ".join(out.split()))
        self.assertEqual(ctx.dispatched, [])


# ─── auto_review: finish ─────────────────────────────────────────────────────

class FinishBase(PipelineCase):
    def setUp(self):
        super().setUp()
        self.settings["auto_review"] = "finish"
        self.write("app/calc.py", "def add(a, b):\n    return a + b\n")
        self.write("tests/test_calc.py", "from app.calc import add\n\n\ndef test_add():\n    assert add(2, 2) == 4\n")
        self.commit("base")
        self.git("checkout", "-q", "-b", "feature")
        self.path = self.write("app/calc.py", "def add(a, b):\n    return a + b + 1\n")

    def verify(self, attempt):
        return gate.on_pre_verify(coding=True, attempt=attempt, changed_paths=[self.path], session_id="s1")

    def tool(self, llm):
        review._CTX = FakeCtx(llm)
        return json.loads(finish.foreman_review_tool({"path": self.root}, task_id="s1"))

    def bad(self, text):
        return FakeLlm(parsed=answer([finding("BLOCKING", "app/calc.py", text, "Off by one", 2)], "BLOCK"))


class FinishLoop(FinishBase):
    def test_loop_through_the_bounce_limit(self):
        d = self.verify(0)
        self.assertEqual(d["action"], "continue")
        self.assertIn("Call the `foreman_review` tool now", d["message"])
        self.assertIsNone(self.verify(1))  # the agent did not call it: never twice for the same diff
        llm = self.bad("return a + b + 1")
        out = self.tool(llm)
        self.assertEqual((out["verdict"], out["bounce"], len(llm.calls)), ("BLOCKED", "1 of 3", 1))
        self.assertIn("never grants", out["advisory"])
        out = self.tool(llm)  # asked again for the same diff: the stored result, no re-roll
        self.assertEqual((out["cached"], len(llm.calls)), (True, 1))
        self.assertIsNone(self.verify(1))  # same diff, same turn: never nudged twice (the tool result said it)
        d = self.verify(0)  # the next turn, the diff unchanged: sent back with the findings
        self.assertEqual(d["action"], "continue")
        self.assertIn("bounce 1 of 3", d["message"])  # the same reviewed diff never counts twice
        self.assertIn("[BLOCKING] app/calc.py:2 - Off by one", d["message"])
        self.assertIn("Fix: do it right", d["message"])
        self.assertIsNone(self.verify(1))
        for n, text in ((2, "return a + b + 2"), (3, "return a + b + 3")):
            self.write("app/calc.py", "def add(a, b):\n    %s\n" % text)
            out = self.tool(self.bad(text))
            self.assertEqual(out["bounce"], "%d of 3" % n)
        self.assertIsNone(self.verify(0))  # the limit: no more nudges
        item = pipeline.items_for(root=self.root)[0]
        self.assertEqual((item["stage"], item["bounces"]), ("bounced", 3))
        self.assertEqual([e["kind"] for e in self.sent], ["needs_owner"])
        self.assertEqual(self.sent[0]["actions"], [{"label": "Details", "command": "/foreman pipeline feature"}])
        self.write("app/calc.py", "def add(a, b):\n    return a + b + 4\n")
        llm = self.bad("return a + b + 4")
        out = self.tool(llm)  # past the limit the tool calls no model
        self.assertEqual((out["verdict"], llm.calls), (review.NOT_REVIEWED, []))
        self.assertIn("bounce limit is reached", out["next"])
        self.assertIsNone(self.verify(0))

    def test_a_review_that_cannot_run_is_retried_once_then_left_to_the_user(self):
        llm = FakeLlm(exc=TimeoutError("slow"))
        for _ in range(3):
            out = self.tool(llm)
            self.assertEqual(out["verdict"], "COULD NOT RUN")
        self.assertEqual(len(llm.calls), 2)  # bounded spend on one diff
        self.assertIsNone(self.verify(0))
        item = pipeline.items_for(root=self.root)[0]
        self.assertEqual(pipeline.stage_of(item, "review")["status"], "error")
        self.assertEqual(self.sent, [])  # never announced ready

    def test_a_gate_blocked_review_is_not_ready(self):
        rec = {"verdict": "BLOCKED", "findings": [], "cache_key": "k",
               "deterministic": {"blocked": True, "verdict": "NEEDS YOUR OK"}}
        ref = pipeline.local_ref(self.root)
        pipeline.record_review(ref, rec, bounce=True)
        item = pipeline.items_for(root=self.root)[0]
        self.assertEqual((pipeline.stage_of(item, "review")["status"], item["bounces"]), ("pending", 0))
        self.assertNotEqual(item["stage"], "ready")
        self.assertEqual(self.sent, [])

    def test_a_local_review_never_makes_the_pull_request_ready(self):
        pipeline.record_gate(pipeline.Ref(review.slug_of(gate.Repo(self.root)), self.root, "pr", 9,
                                          branch="feature", head="c" * 40), "pass", "CLEAN")
        self.verify(0)
        self.tool(FakeLlm(parsed=answer()))
        self.assertIsNone(self.verify(1))
        item = pipeline.items_for(root=self.root)[0]
        self.assertEqual((item["id"].endswith("#pr:9"), item["head"], item["stage"]), (True, "c" * 40, "review"))
        self.assertEqual(self.sent, [])

    def test_a_clean_review_ends_the_loop_ready(self):
        self.verify(0)
        self.tool(FakeLlm(parsed=answer()))
        self.assertIsNone(self.verify(1))
        item = pipeline.items_for(root=self.root)[0]
        self.assertEqual(item["stage"], "ready")
        self.assertEqual([e["kind"] for e in self.sent], ["ready"])

    def test_the_bound_never_exceeds_hermes_s_own(self):
        self.settings["max_bounces"] = 10
        self.assertEqual(pipeline.max_bounces(), 3)
        with mock.patch.object(review, "hermes_config", return_value=dict(MAIN, agent={"max_verify_nudges": 2})):
            self.assertEqual(pipeline.max_bounces(), 2)
            self.assertIsNone(finish.step(self.root, "s1", 2))

    def test_a_deterministic_blocker_comes_first_and_the_hook_never_calls_a_model(self):
        llm = FakeLlm(parsed=answer())
        review._CTX = FakeCtx(llm)
        test = self.write("tests/test_calc.py", "from app.calc import add\n\n\n" + SKIP +
                          "\ndef test_add():\n    assert add(2, 2) == 4\n")
        d = gate.on_pre_verify(coding=True, attempt=0, changed_paths=[test], session_id="s1")
        self.assertIn("undo these", d["message"])
        self.assertIsNone(gate.on_pre_verify(coding=True, attempt=1, changed_paths=[test], session_id="s1"))
        self.assertEqual(llm.calls, [])
        self.assertEqual(pipeline.items_for(root=self.root)[0]["stage"], "gate")


class ToolOutsideFinish(FinishBase):
    def test_the_tool_never_calls_a_model_outside_finish(self):
        for lvl in ("merge", "off"):
            self.settings["auto_review"] = lvl
            llm = FakeLlm(parsed=answer())
            out = self.tool(llm)
            self.assertEqual((out["verdict"], llm.calls), (review.NOT_REVIEWED, []))
            self.assertIn("Ask the user to run `/foreman review`", out["next"])
            self.assertIsNone(self.verify(0))  # and pre_verify does not loop
        review.run_review("", ctx=FakeCtx(FakeLlm(parsed=answer())), where=self.root)  # a person's review
        llm = FakeLlm(parsed=answer())
        out = self.tool(llm)
        self.assertEqual((out["verdict"], out["cached"], llm.calls), ("PASS", True, []))


# ─── One verdict vocabulary (a missing SARIF report) ─────────────────────────

class Incomplete(PipelineCase):
    def setUp(self):
        super().setUp()
        self.settings["auto_review"] = "off"
        self.write("app.py", "x = 1\n")
        self.write("tests/test_x.py", "def test_x(): assert True\n")
        self.write(".foreman.json", '{"sarif": "reports/scan.sarif"}\n')
        self.commit("base")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-q", "-b", "feature")
        self.write("app.py", "x = 2\n")
        self.commit("change")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.git("remote", "add", "origin", "https://github.com/acme/widgets.git")
        board.pin(self.root, KEYS)
        view = pr_view(head=self.head)
        view["baseRefOid"] = self.base
        board.GH_RUNNER = FakeGh(view)
        self.ctx = FakeCtx(FakeLlm(parsed=answer()), choice="merge")
        board.bind(self.ctx)

    def run_cmd(self, text):
        return commands.handle_slash(text, session_key=KEYS[0])

    def test_status_board_verdict_and_merge_all_say_incomplete(self):
        self.assertEqual(verdicts.verdict_of([], ["x"], ["y"]), verdicts.INCOMPLETE)
        self.assertEqual(commands.verdict(self.root)["verdict"], "INCOMPLETE")
        self.assertIn("Foreman: INCOMPLETE", self.run_cmd("status"))
        board_text = self.run_cmd("")
        self.assertRegex(board_text, r"Branch: feature .* INCOMPLETE")
        self.assertIn("gate INCOMPLETE", board_text)
        out = self.run_cmd("verdict 7")
        self.assertIn("Foreman verdict for PR #7: INCOMPLETE", out)
        self.assertIn("scan.sarif", out)
        self.assertNotIn("ready to merge", out)
        out = self.run_cmd("merge 7 --yes")
        self.assertIn("Foreman will not merge PR #7: its verdict is INCOMPLETE", " ".join(out.split()))
        self.assertEqual(self.ctx.dispatched, [])
        self.assertEqual(json.loads(commands.foreman_check_tool({"path": self.root}))["verdict"], "INCOMPLETE")
        item = pipeline.get("acme/widgets#pr:7")
        self.assertEqual(pipeline.stage_of(item, "gate")["status"], "pending")
        self.assertTrue(pipeline.stage_of(item, "gate")["detail"].startswith("INCOMPLETE: could not read the SARIF"))

    def test_the_review_runs_and_reports_the_gate_incomplete(self):
        r = review.run_review("", ctx=FakeCtx(FakeLlm(parsed=answer())), where=self.root)
        self.assertEqual(r["deterministic"]["verdict"], "INCOMPLETE")
        self.assertEqual(r["verdict"], "PASS WITH NOTES")
        self.assertIn("Deterministic gate: INCOMPLETE", review.format_review(r))

    def test_a_pull_request_reads_the_report_committed_in_its_head(self):
        self.write("reports/scan.sarif", json.dumps({"version": "2.1.0", "runs": []}))
        self.commit("add the scan")
        view = pr_view(head=self.git("rev-parse", "HEAD").strip())
        view["baseRefOid"] = self.base
        board.GH_RUNNER = FakeGh(view)
        self.git("checkout", "-q", "main")  # the checkout is another commit, without the report
        v = board.pr_verdict(self.root, 7)
        self.assertEqual((v["verdict"], v["errors"]), ("CLEAN", []))


class NoTests(PipelineCase):
    def test_board_and_status_say_it_once(self):
        self.write("app.py", "x = 1\n")
        self.commit("base")
        board.pin(self.root, KEYS)
        board.bind(FakeCtx())
        for text in (commands.handle_slash("status", session_key=KEYS[0]),
                     commands.handle_slash("", session_key=KEYS[0])):
            self.assertEqual(" ".join(text.split()).count("No tests found here"), 1)


if __name__ == "__main__":
    unittest.main()
