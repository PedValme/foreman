"""pi's extension asking the person a question for a command (``adapters/pi/foreman.ts``): pi's own selector shows
it, and the command runs again with what they picked. Driven without pi, each step running the real entry point."""
import os
import unittest

import test_hosts_pi as base

QUESTION = ('{"question": {"id": "q", "question": "Pick one?", "options": [{"value": "a", "label": "A"}, '
            '{"value": "b", "label": "B"}]}}')


@unittest.skipIf(base.NODE_SKIP, base.NODE_SKIP)
class Questions(base.PiCase):
    drive = base.TheExtension.drive
    fake_python = base.TheExtension.fake_python

    def setUp(self):
        super().setUp()
        with open(os.path.join(self.root, ".git", "info", "exclude"), "a", encoding="utf-8") as fh:
            fh.write("other/\n")
        os.makedirs(os.path.join(self.root, "other"))
        self.git("init", "-q", cwd=os.path.join(self.root, "other"))

    def test_the_selector_asks_and_the_command_runs_again_with_the_pick(self):
        out = self.drive("question")
        self.assertIn("Foreman board: repo", out["board"]["printed"])  # `/foreman` alone is the board
        # nobody attending: no selector, the list and what to type
        self.assertIn("repositories you can pin", out["unattended"]["printed"])
        self.assertEqual(out["unattended"]["shown"], [])
        # the selector closed without a choice: asked once, nothing pinned
        kinds = [entry[0] for entry in out["dismissed"]["shown"]]
        self.assertEqual(kinds, ["select", "info"])
        self.assertIn("repositories you can pin", out["dismissed"]["shown"][1][1])
        # a pick: asked once, with one line per repository, and the reply says it is pinned
        select, reply = out["picked"]["shown"]
        self.assertEqual(select[0], "select")
        self.assertIn("Which repository", select[1])
        self.assertEqual(len(select[2]), 2)
        self.assertEqual(len(set(select[2])), 2)
        self.assertEqual(reply[0], "info")
        self.assertIn("pinned", reply[1])
        self.assertIn("other", reply[1])
        self.assertIn("other", out["status"]["printed"].splitlines()[1])  # the pinned repository's verdict

    def test_two_options_with_the_same_label_stay_two_lines(self):
        out = self.drive("question")
        self.assertEqual(out["lines"], ["1. x", "2. x", "3. y"])  # every line numbered: none can equal another
        self.assertEqual(out["not_a_question"], [None, None, None])

    @unittest.skipIf(os.name == "nt", "the stand-in interpreter is a POSIX shell script")
    def test_a_question_that_never_settles_is_asked_three_times_and_no_more(self):
        out = self.drive("question", FAKE_PYTHON=self.fake_python("echo '%s'" % QUESTION))
        shown = out["endless"]["shown"]
        self.assertEqual([entry[0] for entry in shown], ["select", "select", "select", "info"])
        self.assertIn("nothing was done", shown[-1][1])


if __name__ == "__main__":
    unittest.main()
