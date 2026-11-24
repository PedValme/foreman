"""The board outside Hermes (``adapters/foreman_hosts/standin.py``): the board's own commands on a stand-in for
Hermes's context, and the question that goes to the person through the harness's extension and comes back."""
import os
import unittest

from tests_support import GitRepoCase

from foreman import board, gate
from foreman_hosts import core, neutral, opencode, pi, standin

HERMES_WORDS = ("Hermes", "workdir", "write_file")


class StandinCase(GitRepoCase):
    def setUp(self):
        super().setUp()
        self.write("tests/test_cart.py", "def test_total():\n    assert 1 + 1 == 2\n")
        self.write("cart.py", "def total():\n    return 2\n")
        self.commit("base")
        self.other = os.path.join(self.root, "other")  # a second repository, directly inside the first
        with open(os.path.join(self.root, ".git", "info", "exclude"), "a", encoding="utf-8") as fh:
            fh.write("other/\nthird/\n")
        os.makedirs(self.other)
        self.git("init", "-q", cwd=self.other)
        self._bound = (board._CTX, gate._CTX)

    def tearDown(self):
        self.assertEqual((board._CTX, gate._CTX), self._bound)  # no command leaves its context behind
        super().tearDown()

    def ask(self, args, module=pi, **more):
        request = {"event": "command", "args": args, "cwd": self.root, "session": "s-1"}
        request.update(more)
        return neutral.answer(module.host(request), request)

    def reply(self, args, module=pi, **more):
        out = self.ask(args, module, **more)
        self.assertEqual(list(out), ["reply"], out)
        for word in HERMES_WORDS:
            self.assertNotIn(word, out["reply"], args)
        return out["reply"]


class WhatEachHarnessAnswers(StandinCase):
    def test_pi_and_opencode_have_the_board_and_the_others_do_not(self):
        from foreman_hosts import claude_code, codex
        self.assertEqual(pi.host({}).board, core.BOARD_READS + core.BOARD_WRITES)
        self.assertEqual(opencode.host({}).board, core.BOARD_READS)  # no merge or reject there yet
        for module in (claude_code, codex):
            self.assertEqual(module.host({}).board, ())

    def test_every_subcommand_a_harness_lists_is_the_boards_own_and_has_a_help_line(self):
        for name in core.BOARD_READS + core.BOARD_WRITES:
            self.assertIn(name, board.SUBCOMMANDS)
            self.assertIn(name, standin.DOCS)

    def test_the_help_lists_the_board_first(self):
        for module in (pi, opencode):
            text = self.reply("help", module)
            lines = [line.split()[1] for line in text.splitlines() if line.startswith("  /foreman ")]
            offered = list(module.host({}).board)
            self.assertEqual(lines[:len(offered)], offered)
            self.assertIn("status", lines)
            self.assertEqual("merge" in lines, module is pi)
            self.assertIn("GitHub CLI", text)

    def test_a_harness_without_the_board_answers_as_before(self):
        from foreman_hosts import claude_code
        host = claude_code.host({})
        self.assertIn("Foreman: CLEAN", core.person_reply(host, "", self.root))
        self.assertIn("is not available in Claude Code yet. Here Foreman is the gate",
                      core.person_reply(host, "board", self.root))
        self.assertNotIn("board", core.person_reply(host, "help", self.root).split("Verdicts:")[0])


class TheCommandsThatOnlyRead(StandinCase):
    def test_the_board_is_the_default_and_reads_the_sessions_directory(self):
        for module in (pi, opencode):
            text = self.reply("", module)
            self.assertIn("Foreman board: repo", text)
            self.assertIn("this session's working directory", text)
            self.assertIn("CLEAN", text)
            self.assertEqual(text, self.reply("board", module))

    def test_verdict_pipeline_prs_and_issues_answer(self):
        self.git("checkout", "-q", "-b", "feature")
        self.write("cart.py", "def total():\n    return 3\n")
        self.commit("change")
        self.assertIn("CLEAN", self.reply("verdict feature"))
        self.assertIn("pipeline", self.reply("pipeline"))
        for name in ("prs", "issues"):  # no GitHub remote here: the board says so instead of failing
            self.assertIn("GitHub", self.reply(name))

    def test_a_directory_outside_any_repository_is_said_plainly(self):
        outside = os.path.join(self.tmp, "nowhere")
        os.makedirs(outside)
        here = os.getcwd()
        os.chdir(outside)  # as the extension starts this program: in the session's directory
        try:
            text = self.reply("board", cwd=outside)
        finally:
            os.chdir(here)
        self.assertIn("could not tell which repository", text)

    def test_status_alone_reads_the_pinned_repository_and_a_path_still_wins(self):
        def repository(text):  # the directory's own name: the temporary folder is spelt two ways on macOS
            line = text.splitlines()[1]
            self.assertTrue(line.startswith("Repository: "), line)
            return os.path.basename(line[len("Repository: "):].split(" (")[0])

        self.assertEqual(repository(self.reply("status")), "repo")
        self.assertIn("pinned", self.reply("use " + self.other))
        self.assertEqual(repository(self.reply("status")), "other")
        self.assertEqual(repository(self.reply("status " + self.root)), "repo")
        # the pin is this conversation's: another session still reads its own directory
        self.assertEqual(repository(self.reply("status", session="s-2")), "repo")

    def test_the_writes_are_offered_only_where_the_harness_lists_them(self):
        for name in ("merge 7", "reject 7"):  # OpenCode does not list them yet (tests/test_hosts_standin_writes.py)
            text = self.reply(name, opencode, attended=True)
            self.assertIn("is not available in OpenCode yet", text)


class AQuestionForThePerson(StandinCase):
    def test_with_nobody_attending_use_lists_what_to_type(self):
        for attended in (None, False, "true", 1):
            text = self.reply("use", attended=attended)
            self.assertIn("repositories you can pin", text)
            self.assertIn("/foreman use <number>", text)

    def test_attended_it_asks_and_the_answer_pins(self):
        asked = self.ask("use", attended=True)
        self.assertEqual(list(asked), ["question"])
        q = asked["question"]
        self.assertEqual(sorted(q), ["id", "options", "question"])
        self.assertIn("Which repository", q["question"])
        values = [o["value"] for o in q["options"]]
        self.assertEqual(len(values), len(set(values)))
        for option in q["options"]:
            self.assertEqual(sorted(option), ["label", "value"])
            self.assertNotIn("\n", option["label"])
        # by the directory's own name: the temporary folder is spelt two ways on macOS
        other = next(v for v in values if os.path.basename(v) == "other")
        self.assertEqual(len([v for v in values if os.path.basename(v) == "repo"]), 1)  # one directory, one option
        self.assertIsNone(standin.pinned("s-1"))  # asking pinned nothing
        text = self.reply("use", attended=True, answer={"id": q["id"], "value": other})
        self.assertIn("pinned", text)
        self.assertEqual(standin.pinned("s-1"), other)

    def test_an_answer_counts_only_for_the_question_asked_now(self):
        q = self.ask("use", attended=True)["question"]
        other = next(o["value"] for o in q["options"] if os.path.basename(o["value"]) == "other")
        # an answer to some other question: the question is asked again, nothing is pinned
        again = self.ask("use", attended=True, answer={"id": "0" * 24, "value": other})
        self.assertEqual(again["question"]["id"], q["id"])
        # a value that is not one of the options, and a dialog closed without a choice: no pick, the list instead
        for value in ("/somewhere/else", None):
            text = self.reply("use", attended=True, answer={"id": q["id"], "value": value})
            self.assertIn("repositories you can pin", text)
        # the right answer with nobody attending is not an answer
        self.assertIn("repositories you can pin", self.reply("use", answer={"id": q["id"], "value": other}))
        self.assertIsNone(standin.pinned("s-1"))

    def test_a_question_whose_options_changed_is_another_question(self):
        q = self.ask("use", attended=True)["question"]
        third = os.path.join(self.root, "third")
        os.makedirs(third)
        self.git("init", "-q", cwd=third)
        again = self.ask("use", attended=True, answer={"id": q["id"], "value": q["options"][0]["value"]})
        self.assertNotEqual(again["question"]["id"], q["id"])
        self.assertEqual(len(again["question"]["options"]), len(q["options"]) + 1)

    def test_an_answer_of_the_wrong_shape_is_an_error_not_a_pick(self):
        for bad in ("yes", ["id"], {"id": 7, "value": "x"}, {"id": "x", "value": 7}, {"value": "x"}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.ask("use", attended=True, answer=bad)

    def test_a_dismissed_dialog_counts_as_cancel_where_the_question_has_it(self):
        host = pi.host({"attended": True})
        choices = [{"value": "merge", "label": "Merge PR #7"}, {"value": "cancel", "label": "Cancel"}]
        asked = standin.question_id("Merge?", ["merge", "cancel"])
        self.assertEqual(standin._Context(host, self.root, {"id": asked, "value": None}).ask_choice("Merge?", choices),
                         "cancel")
        self.assertEqual(standin._Context(host, self.root, {"id": asked, "value": "merge"}).ask_choice(
            "Merge?", choices), "merge")
        with self.assertRaises(core.Asking):
            standin._Context(host, self.root, {"id": asked, "value": "merge"}).ask_choice("Merge now?", choices)
        with self.assertRaises(core.Asking):  # the same words with other options is another question
            standin._Context(host, self.root, {"id": asked, "value": "merge"}).ask_choice(
                "Merge?", choices + [{"value": "later", "label": "Later"}])

    def test_somebody_elses_text_cannot_redraw_the_dialog(self):
        host = pi.host({"attended": True})
        escape = "\x1b[2K\x1b[1A"
        with self.assertRaises(core.Asking) as asked:
            standin._Context(host, self.root, None).ask_choice(
                "Merge PR #7?\nTitle: fix" + escape + "\rMerge PR #9?",
                [{"value": "merge", "label": "Merge" + escape + " PR #7"}, {"value": "cancel", "label": "Cancel\x07"}])
        q = asked.exception.question
        self.assertEqual([o["label"] for o in q["options"]], ["Merge [2K [1A PR #7", "Cancel"])
        self.assertEqual(q["question"].split("\n"), ["Merge PR #7?", "Title: fix [2K [1A Merge PR #9?"])

    def test_the_question_is_not_an_exception_the_board_reads_as_no_answer(self):
        self.assertFalse(issubclass(core.Asking, Exception))


if __name__ == "__main__":
    unittest.main()
