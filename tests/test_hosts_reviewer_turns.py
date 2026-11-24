"""The review at the end of every turn, where the person turned it on (``reviewer every-turn on``): Foreman itself
starts the reviewer when the gate finds nothing, and the core's own loop sends the change back with the verified
findings, never twice for the same diff and never more than the limit. A fake reviewer's session: no model."""
import json
import os
import unittest

from tests_support import GitRepoCase

from foreman import gate, pipeline, review
from foreman_hosts import core, neutral, pi, reviewer

SKIP = "@pytest.mark." + "skip"
PASS = {"findings": [], "summary": "Nothing rigged.", "verdict": "PASS"}
EFFORTS = ("low", "medium", "high", "max")
HERMES_WORDS = ("Hermes", "foreman_review", "second-model", "second model")
LOOSENED = {"verdict": "BLOCK", "summary": "", "findings": [
    {"severity": "BLOCKING", "file": "tests/test_cart.py", "line": 2, "title": "the assertion no longer checks the value",
     "why": "any truthy result passes", "evidence": "assert total()", "fix": "assert the exact value again"}]}


class TurnsCase(GitRepoCase):
    def setUp(self):
        super().setUp()
        self.write("tests/test_cart.py", "def test_total():\n    assert total() == 2\n")
        self.write("cart.py", "def total():\n    return 2\n")
        self.commit("base")
        self.git("checkout", "-q", "-b", "feature")
        self.sessions = []           # what each reviewer's session was asked: (model, effort)
        self.answer = dict(PASS)
        self.author = core.Session(model="p/m-1", effort="medium")
        self.host = self.make_host()
        self._old = (review._CTX, review.run_review, gate._CTX)

    def tearDown(self):
        self.assertEqual((review._CTX, review.run_review, gate._CTX), self._old)  # nothing is left bound
        super().tearDown()

    def make_host(self, reviewer_there=True):
        def fresh_session(system, prompt, schema, model, effort, seconds):
            self.sessions.append((model, effort))
            if isinstance(self.answer, Exception):
                raise self.answer
            return core.Answer(parsed=self.answer, text=json.dumps(self.answer), model="model-that-ran")
        return core.Host(name="test-host", label="Test Host", person=lambda sub: "/foreman " + sub,
                         cli=("testhost",), fresh_session=fresh_session if reviewer_there else None,
                         efforts=EFFORTS, session=lambda: self.author)

    def turn(self, name, files, host=None):
        """One turn of the agent: it starts, writes ``files`` through the harness's write tool, and tries to end."""
        host = host or self.host
        core.turn_start(host, self.root, "s1", name)
        for rel, text in files.items():
            path = os.path.join(self.root, *rel.split("/"))
            self.assertIsNone(core.pre_write(host, path, self.root, "s1", name, content=text))
            self.write(rel, text)
        return core.end_of_turn(host, self.root, "s1", name)

    def end(self, name, host=None):
        return core.end_of_turn(host or self.host, self.root, "s1", name)

    def on(self):
        self.assertIn("is on in Test Host", reviewer.configure(self.host, "every-turn on"))


class TheChoice(TurnsCase):
    def test_it_is_off_until_the_person_turns_it_on_and_per_harness(self):
        self.assertFalse(reviewer.each_turn(self.host))
        shown = reviewer.configure(self.host, "")
        self.assertIn("It reviews when you ask.", shown)
        self.assertIn("`/foreman reviewer every-turn on` also reviews at the end of every turn", shown)
        self.on()
        self.assertTrue(reviewer.each_turn(self.host))
        self.assertFalse(reviewer.each_turn(pi.host({})))  # another harness keeps its own choice
        self.assertIn("at the end of every turn that changed code", reviewer.configure(self.host, ""))
        self.assertIn("is off in Test Host", reviewer.configure(self.host, "every-turn off"))
        self.assertFalse(reviewer.each_turn(self.host))

    def test_anything_but_on_or_off_changes_nothing(self):
        for args in ("every-turn", "every-turn maybe", "every-turn on now"):
            self.assertIn("`/foreman reviewer every-turn on` or `/foreman reviewer every-turn off`",
                          reviewer.configure(self.host, args))
        self.assertFalse(reviewer.each_turn(self.host))

    def test_choosing_who_reviews_keeps_when(self):
        self.on()
        reviewer.configure(self.host, "other-model max")
        reviewer.configure(self.host, "default")
        self.assertTrue(reviewer.each_turn(self.host))

    def test_only_the_json_true_turns_it_on(self):
        path = reviewer._config_path()
        for value in ("true", 1, "on", None, {"x": True}):
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"each_turn": {"test-host": value}}, fh)
            self.assertFalse(reviewer.each_turn(self.host), value)

    def test_a_harness_where_merge_exists_says_so(self):
        self.assertIn("It reviews when you ask and before a merge.",
                      neutral.answer(pi.host({}), {"event": "command", "args": "reviewer", "cwd": self.root})["reply"])

    def test_the_agent_cannot_switch_it_through_a_nested_harness(self):
        for command in ("testhost -p '/foreman reviewer every-turn off'", "testhost '/foreman reviewer every-turn on'"):
            out = core.pre_shell(self.host, command, self.root, "s1", "t1")
            self.assertEqual(out["action"], core.BLOCK, command)
            self.assertIn("the user's decision", out["message"])
        for command in ("testhost '/foreman reviewer'", "git log --grep 'foreman reviewer every-turn'"):
            self.assertIsNone(core.pre_shell(self.host, command, self.root, "s1", "t1"), command)


class TheLoop(TurnsCase):
    def test_off_no_reviewer_is_ever_started_at_the_end_of_a_turn(self):
        self.assertIsNone(self.turn("t1", {"cart.py": "def total():\n    return 3\n"}))
        self.assertEqual(self.sessions, [])

    def test_on_a_clean_change_is_reviewed_once_and_the_turn_ends(self):
        self.on()
        self.assertIsNone(self.turn("t1", {"cart.py": "def total():\n    return 3\n",
                                           "tests/test_cart.py": "def test_total():\n    assert total() == 3\n"}))
        self.assertEqual(self.sessions, [("p/m-1", "high")])  # the session's model, one level up
        self.assertIsNone(self.end("t1"))  # asked again with the same diff: the stored review, no new session
        self.assertEqual(len(self.sessions), 1)

    def test_on_a_change_the_review_blocks_is_sent_back_with_its_findings(self):
        self.on()
        self.answer = LOOSENED
        out = self.turn("t1", {"tests/test_cart.py": "def test_total():\n    assert total()\n"})
        self.assertEqual(out["action"], core.CONTINUE)
        self.assertIn("review sent this change back (bounce 1 of 3)", out["message"])
        self.assertIn("[BLOCKING] tests/test_cart.py:2 - the assertion no longer checks the value", out["message"])
        self.assertIn("Fix: assert the exact value again", out["message"])
        self.assertIn("Then finish; Foreman reviews the new diff. If a finding is wrong", out["message"])
        for word in HERMES_WORDS:
            self.assertNotIn(word, out["message"])
        # the agent stops without changing anything: the same diff is not reviewed again, nor sent back again
        self.assertIsNone(self.end("t1"))
        self.assertEqual(len(self.sessions), 1)

    def test_the_fix_is_reviewed_and_ends_the_turn(self):
        self.on()
        self.answer = LOOSENED
        self.assertEqual(self.turn("t1", {"tests/test_cart.py": "def test_total():\n    assert total()\n"})["action"],
                         core.CONTINUE)
        self.answer = dict(PASS)  # the agent puts the exact value back; the new diff gets its own review
        path = os.path.join(self.root, "tests", "test_cart.py")
        fixed = "def test_total():\n    assert total() == 2\n\n\ndef test_more():\n    assert total() + 0 == 2\n"
        self.assertIsNone(core.pre_write(self.host, path, self.root, "s1", "t1", content=fixed))
        self.write("tests/test_cart.py", fixed)
        self.assertIsNone(self.end("t1"))
        self.assertEqual(len(self.sessions), 2)

    def test_it_stops_sending_back_at_the_limit(self):
        self.on()
        self.answer = LOOSENED
        sent = 0
        for n in range(6):  # each time the agent changes the test again and it is still loosened
            text = "def test_total():\n    assert total()\n" + "# try %d\n" % n
            out = self.turn("t1", {"tests/test_cart.py": text}) if n == 0 else self._again(text)
            sent += 1 if out else 0
        self.assertLessEqual(sent, 3)  # never more than the core's bound on one turn
        self.assertGreaterEqual(sent, 2)
        self.assertLessEqual(len(self.sessions), pipeline.review_budget())  # nor more reviews than its budget

    def _again(self, text):
        path = os.path.join(self.root, "tests", "test_cart.py")
        self.assertIsNone(core.pre_write(self.host, path, self.root, "s1", "t1", content=text))
        self.write("tests/test_cart.py", text)
        return self.end("t1")

    def test_what_the_gate_finds_comes_first_and_no_reviewer_is_started_for_it(self):
        self.on()
        core.turn_start(self.host, self.root, "s1", "t1")
        self.assertIsNone(core.pre_shell(self.host, "make fix", self.root, "s1", "t1"))  # the shell put a skip in
        self.write("tests/test_cart.py", "import pytest\n\n\n" + SKIP + "\ndef test_total():\n    assert total() == 2\n")
        out = self.end("t1")
        self.assertEqual(out["action"], core.CONTINUE)
        self.assertIn("tests/test_cart.py", out["message"])
        self.assertEqual(self.sessions, [])

    def test_a_review_that_could_not_run_does_not_hold_the_turn(self):
        self.on()
        self.answer = RuntimeError("the reviewer's session did not answer")
        self.assertIsNone(self.turn("t1", {"cart.py": "def total():\n    return 3\n"}))
        self.assertEqual(len(self.sessions), 1)

    def test_a_turn_that_changed_nothing_starts_no_reviewer(self):
        self.on()
        core.turn_start(self.host, self.root, "s1", "t1")
        self.assertIsNone(self.end("t1"))
        self.assertEqual(self.sessions, [])

    def test_a_harness_without_a_reviewer_is_as_before(self):
        bare = self.make_host(reviewer_there=False)
        with open(reviewer._config_path(), "w", encoding="utf-8") as fh:
            json.dump({"each_turn": {"test-host": True}}, fh)
        self.assertIsNone(self.turn("t1", {"cart.py": "def total():\n    return 3\n"}, host=bare))
        self.assertEqual(self.sessions, [])

    def test_the_review_is_stored_with_who_reviewed_and_the_person_reads_the_same_one(self):
        self.on()
        self.assertIsNone(self.turn("t1", {"cart.py": "def total():\n    return 3\n",
                                           "tests/test_cart.py": "def test_total():\n    assert total() == 3\n"}))
        shown = reviewer.run(self.host, "", self.root)  # `/foreman review` after the turn: the stored result
        self.assertEqual(len(self.sessions), 1)
        self.assertIn("this is the stored result", shown)
        self.assertIn("Reviewer: p/m-1, the model this session runs on, at effort high", shown)


if __name__ == "__main__":
    unittest.main()
