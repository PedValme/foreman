"""The host-neutral half of the adapters (``adapters/foreman_hosts/core.py``): the gate's decisions reach another
harness unchanged, in its words, and Foreman's own program and state stay out of the agent's reach."""
import json
import os
import unittest

from tests_support import GitRepoCase

from foreman import grants
from foreman.detector import MARKER
from foreman_hosts import core

# Built from parts, as in the other tests: Foreman reads its own test files, and a literal marker here would be
# a finding in this repository's pull requests.
SKIP = "@pytest.mark." + "skip"
SKIPPED = "import pytest\n\n\n" + SKIP + "\ndef test_total():\n    assert 1 + 1 == 2\n"
SKIP_EDIT = SKIP + "\ndef test_total():"
CLEAN_TEST = "def test_total():\n    assert 1 + 1 == 2\n"
MARKED = ("import pytest\n\n\n" + SKIP + "  # " + MARKER + " flaky upstream\ndef test_total():\n"
          "    assert 1 + 1 == 2\n")
HERMES_WORDS = ("workdir", "write_file", "this patch", "Hermes", "/foreman ")


class HostCase(GitRepoCase):
    def setUp(self):
        super().setUp()
        self.program = os.path.join(self.tmp, "installed")
        os.makedirs(os.path.join(self.program, "adapters"))
        self.present = True
        self.host = core.Host(
            name="test-host", label="Test Host", person=lambda sub: "/foreman:" + sub,
            program_dirs=(os.path.join(self.program, "adapters"),), cli=("claude",),
            switches_off=lambda command: "TURN-FOREMAN-OFF" in command,
            is_config=lambda path: path.endswith("settings.json"),
            config_off=lambda before, after: "HOOKS-OFF" in after and "HOOKS-OFF" not in before,
            attended=lambda: self.present)
        self.write("tests/test_cart.py", CLEAN_TEST)
        self.write("cart.py", "def total():\n    return 2\n")
        self.commit("base")

    def shell(self, command, cwd=None, turn="t1"):
        return core.pre_shell(self.host, command, cwd or self.root, "s1", turn)

    def assertNoHermesWords(self, message):
        for word in HERMES_WORDS:
            self.assertNotIn(word, message)


class PreShell(HostCase):
    def test_a_command_the_gate_does_not_inspect_passes(self):
        self.assertIsNone(self.shell("ls -la"))

    def test_a_clean_commit_passes(self):
        self.write("cart.py", "def total():\n    return 3\n")
        self.git("add", "-A")
        self.assertIsNone(self.shell("git commit -m change"))

    def test_a_commit_that_skips_a_test_is_blocked_with_file_and_line(self):
        self.write("tests/test_cart.py", SKIPPED)
        self.git("add", "-A")
        d = self.shell("git commit -m green")
        self.assertEqual(d["action"], core.BLOCK)
        self.assertIn("tests/test_cart.py:4", d["message"])
        self.assertIn("test-skipped", d["message"])
        self.assertNoHermesWords(d["message"])

    def test_the_commit_is_inspected_in_the_directory_the_harness_gave(self):
        self.write("tests/test_cart.py", SKIPPED)
        self.git("add", "-A")
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.makedirs(elsewhere)
        self.assertEqual(self.shell("git -C %s commit -m green" % self.root, cwd=elsewhere)["action"], core.BLOCK)

    def test_no_verify_is_blocked(self):
        self.write("cart.py", "def total():\n    return 3\n")
        self.git("add", "-A")
        d = self.shell("git commit --no-verify -m change")
        self.assertEqual(d["action"], core.BLOCK)
        self.assertIn("--no-verify", d["message"])

    def test_an_agent_run_merge_is_blocked_in_the_harness_words(self):
        d = self.shell("gh pr merge 3 --squash")
        self.assertEqual(d["action"], core.BLOCK)
        self.assertIn("Merging is the user's decision", d["message"])
        self.assertIn("gh pr merge 3", d["message"])
        self.assertNoHermesWords(d["message"])

    def test_a_commit_outside_any_repository_is_left_to_git(self):
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        self.assertIsNone(self.shell("git commit -m x", cwd=outside))  # git fails on its own: nothing to inspect

    def test_a_directory_that_does_not_exist_goes_to_a_person_without_hermes_words(self):
        d = self.shell("git commit -m x", cwd=os.path.join(self.tmp, "gone"))
        self.assertEqual(d["action"], core.ASK)
        self.assertIn("does not exist on this machine", d["message"])
        self.assertNoHermesWords(d["message"])

    def test_a_marked_finding_waits_for_the_person_in_the_harness_words(self):
        self.write("tests/test_cart.py", MARKED)
        self.git("add", "-A")
        d = self.shell("git commit -m green")
        self.assertEqual(d["action"], core.BLOCK)
        self.assertIn("/foreman:allow <id>", d["message"])
        self.assertNoHermesWords(d["message"])

    def test_an_answer_this_adapter_does_not_know_goes_to_a_person_never_through(self):
        self.assertEqual(core._decision(self.host, {"action": "something-new", "message": "m"})["action"], core.ASK)
        self.assertEqual(core._decision(self.host, {"action": "approve", "message": "m"})["action"], core.ASK)
        self.assertIsNone(core._decision(self.host, None))


class OwnGuard(HostCase):
    def test_the_agent_cannot_run_or_touch_foremans_program_from_the_shell(self):
        d = self.shell("python3 %s/adapters/hook.py claude-code" % self.program)
        self.assertEqual(d["action"], core.BLOCK)
        self.assertIn("own program and state", d["message"])
        self.assertEqual(self.shell("rm -rf '%s/adapters'" % self.program.upper())["action"], core.BLOCK)

    def test_the_agent_cannot_reach_foremans_state_from_the_shell(self):
        for command in ("cat ~/.foreman/foreman-grants.json", "ls $HOME/.foreman", "rm -rf /home/u/.foreman/sessions",
                        "ls '%s'" % grants.store_dir()):
            self.assertEqual(self.shell(command)["action"], core.BLOCK, command)

    def test_the_repositorys_own_foreman_json_is_not_foremans_state(self):
        self.assertIsNone(self.shell("cat .foreman.json"))

    def test_a_command_that_turns_foreman_off_is_blocked(self):
        d = self.shell("echo TURN-FOREMAN-OFF")
        self.assertEqual(d["action"], core.BLOCK)
        self.assertIn("user's decision", d["message"])

    def test_the_agent_cannot_start_its_harness_to_type_the_persons_allow(self):
        for command in ("claude -p '/foreman:allow 3f2a'", 'claude -p "/foreman allow 3f2a"',
                        "cd /tmp && claude.exe --print 'foreman allow x'"):
            d = self.shell(command)
            self.assertEqual(d["action"], core.BLOCK, command)
            self.assertIn("/foreman:allow <id>", d["message"])

    def test_the_harness_started_inside_a_shell_is_still_the_harness(self):
        for command in ("bash -c \"claude -p '/foreman:allow 3f2a'\"", "sudo -u me claude -p '/foreman:allow 3f2a'",
                        "FOO=1 claude -p '/foreman allow 3f2a'"):
            self.assertEqual(self.shell(command)["action"], core.BLOCK, command)

    def test_words_about_allow_are_not_the_persons_command(self):
        self.write("cart.py", "def total():\n    return 3\n")
        self.git("add", "-A")
        for command in ("grep -rn 'foreman allow' adapters/claude-code/", "rg 'foreman:allow' ~/.claude/projects",
                        "git commit -m 'claude: document /foreman:allow'",
                        "git commit -m 'docs: explain /foreman allow'"):
            self.assertIsNone(self.shell(command), command)

    def test_the_entry_point_run_by_hand_is_blocked_wherever_it_is_named_from(self):
        for command in ("cd /somewhere && python3 adapters/hook.py claude-code < forged.json",
                        "cat forged.json | python3 -I ./hook.py claude-code"):
            d = self.shell(command)
            self.assertEqual(d["action"], core.BLOCK, command)
            self.assertIn("own program and state", d["message"])
        for command in ("git add adapters/hook.py", "python3 scripts/hook.py --install", "ls claude-code"):
            self.assertIsNone(self.shell(command), command)

    def test_the_agent_cannot_write_into_foremans_program_or_state(self):
        for path in (os.path.join(self.program, "adapters", "hook.py"),
                     os.path.join(grants.store_dir(), "sessions", "x.json"),
                     os.path.join(grants.store_dir(), grants.GRANTS_FILE)):
            d = core.pre_write(self.host, path, self.root, "s1", "t1", content="x")
            self.assertEqual(d["action"], core.BLOCK, path)

    def test_a_write_that_switches_the_hooks_off_is_blocked(self):
        path = os.path.join(self.tmp, ".claude", "settings.json")
        d = core.pre_write(self.host, path, self.root, "s1", "t1", content="HOOKS-OFF")
        self.assertEqual(d["action"], core.BLOCK)
        self.assertIn("user's decision", d["message"])
        self.assertIsNone(core.pre_write(self.host, path, self.root, "s1", "t1", content='{"model": "x"}'))
        self.assertIsNone(core.pre_write(self.host, os.path.join(self.root, "notes.txt"), self.root, "s1", "t1",
                                         content="HOOKS-OFF"))  # not a settings file

    def test_a_settings_edit_is_judged_by_the_file_as_it_will_be(self):
        path = os.path.join(self.tmp, ".claude", "settings.json")
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as fh:
            fh.write("HOOKS-ON model=a")
        d = core.pre_write(self.host, path, self.root, "s1", "t1", old="ON", new="OFF")  # the fragment says nothing
        self.assertEqual(d["action"], core.BLOCK)
        self.assertIsNone(core.pre_write(self.host, path, self.root, "s1", "t1", old="model=a", new="model=b"))

    def test_what_the_person_already_switched_off_stays_theirs(self):
        path = os.path.join(self.tmp, ".claude", "settings.json")
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as fh:
            fh.write("HOOKS-OFF model=a")
        self.assertIsNone(core.pre_write(self.host, path, self.root, "s1", "t1", old="model=a", new="model=b"))
        self.assertIsNone(core.pre_write(self.host, path, self.root, "s1", "t1", content="HOOKS-OFF model=c"))


class PreWrite(HostCase):
    def test_a_write_that_skips_a_test_is_blocked(self):
        d = core.pre_write(self.host, os.path.join(self.root, "tests", "test_cart.py"), self.root, "s1", "t1",
                           content=SKIPPED)
        self.assertEqual(d["action"], core.BLOCK)
        self.assertIn("Foreman blocked this write:", d["message"])
        self.assertNoHermesWords(d["message"])

    def test_an_edit_that_skips_a_test_is_blocked(self):
        d = core.pre_write(self.host, "tests/test_cart.py", self.root, "s1", "t1", old="def test_total():",
                           new=SKIP_EDIT)
        self.assertEqual(d["action"], core.BLOCK)
        self.assertIn("Foreman blocked this edit:", d["message"])

    def test_an_ordinary_write_passes_and_is_remembered_for_the_turn(self):
        path = os.path.join(self.root, "cart.py")
        self.assertIsNone(core.pre_write(self.host, path, self.root, "s1", "t1", content="def total():\n    return 3\n"))
        self.assertEqual(core._touched(self.host, "s1", "t1"), [path])
        self.assertEqual(core._touched(self.host, "s1", "another-turn"), [])

    def test_a_blocked_write_is_not_remembered(self):
        core.pre_write(self.host, os.path.join(self.root, "tests", "test_cart.py"), self.root, "s1", "t1",
                       content=SKIPPED)
        self.assertEqual(core._touched(self.host, "s1", "t1"), [])

    def test_a_tool_whose_change_cannot_be_read_still_meets_the_guards(self):
        self.assertIsNone(core.pre_write(self.host, os.path.join(self.root, "notes.ipynb"), self.root, "s1", "t1"))
        d = core.pre_write(self.host, os.path.join(self.program, "adapters", "x.ipynb"), self.root, "s1", "t1")
        self.assertEqual(d["action"], core.BLOCK)


class Turns(HostCase):
    def end(self, turn="t1", session="s1"):
        return core.end_of_turn(self.host, self.root, session, turn)

    def start(self, turn="t1", cwd=None):
        core.turn_start(self.host, cwd or self.root, "s1", turn)

    def tool_writes(self, rel, text, turn="t1", cwd=None):
        """A write tool call the person let through: the hook first, then the file changes."""
        path = os.path.join(self.root, *rel.split("/"))
        self.assertIsNone(core.pre_write(self.host, path, cwd or self.root, "s1", turn, content=text))
        self.write(rel, text)

    def test_a_turn_that_changed_nothing_is_not_sent_back(self):
        self.start()
        self.assertIsNone(self.shell("ls"))
        self.assertIsNone(self.end())

    def test_a_prompt_costs_no_git_call(self):
        self.start()
        self.assertEqual(core._load(self.host, "s1")["roots"], {})
        self.shell("ls")
        signed = [os.path.realpath(root) for root in core._load(self.host, "s1")["roots"]]
        self.assertEqual(signed, [os.path.realpath(self.root)])

    def test_a_skip_left_by_the_shell_sends_the_agent_back_once(self):
        self.start()
        self.assertIsNone(self.shell("perl -pi -e s/x/y/ tests/test_cart.py"))  # the hook runs before the command
        self.write("tests/test_cart.py", SKIPPED)                               # ...which then edits the file
        d = self.end()
        self.assertEqual(d["action"], core.CONTINUE)
        self.assertIn("tests/test_cart.py:4", d["message"])
        self.assertIn("undo these before you finish", d["message"])
        self.assertIsNone(self.end())  # one nudge per turn

    def test_the_next_turn_can_be_sent_back_again(self):
        self.start()
        self.shell("make fix")
        self.write("tests/test_cart.py", SKIPPED)
        self.assertIsNotNone(self.end())
        self.start("t2")
        self.shell("make more", turn="t2")
        self.write("cart.py", "def total():\n    return 4\n")
        self.assertEqual(self.end("t2")["action"], core.CONTINUE)

    def test_a_turn_that_only_talked_is_never_sent_back(self):
        self.write("tests/test_cart.py", SKIPPED)  # the person's own uncommitted work
        self.start()
        self.write("cart.py", "def total():\n    return 5\n")  # ...and they keep editing while the agent answers
        self.assertIsNone(self.end())

    def test_a_skip_that_was_already_there_does_not_send_back_a_turn_that_changed_nothing(self):
        self.write("tests/test_cart.py", SKIPPED)
        self.start()
        self.shell("git status")
        self.assertIsNone(self.end())

    def test_a_tool_write_counts_in_a_repository_the_shell_never_ran_in(self):
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.makedirs(elsewhere)
        self.start(cwd=elsewhere)
        self.write("tests/test_cart.py", SKIPPED)
        self.assertIsNone(core.end_of_turn(self.host, elsewhere, "s1", "t1"))  # nothing ties the turn to it yet
        self.tool_writes("cart.py", "def total():\n    return 3\n", cwd=elsewhere)
        self.assertEqual(core.end_of_turn(self.host, elsewhere, "s1", "t1")["action"], core.CONTINUE)

    def test_a_write_the_person_refused_does_not_count(self):
        self.write("tests/test_cart.py", SKIPPED)
        old = os.path.getmtime(os.path.join(self.root, "cart.py")) - 3600
        os.utime(os.path.join(self.root, "cart.py"), (old, old))
        self.start()
        path = os.path.join(self.root, "cart.py")
        self.assertIsNone(core.pre_write(self.host, path, self.root, "s1", "t1", content="x = 1\n"))  # hook passes
        self.assertIsNone(self.end())  # ...the person said no at the prompt: the file never changed

    def test_the_shell_in_a_second_repository_is_followed_too(self):
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.makedirs(elsewhere)
        self.start(cwd=elsewhere)
        self.assertIsNone(self.shell("ls", cwd=elsewhere))
        self.assertIsNone(self.shell("make fix", cwd=os.path.join(self.root, "tests")))
        self.write("tests/test_cart.py", SKIPPED)
        self.assertEqual(core.end_of_turn(self.host, elsewhere, "s1", "t1")["action"], core.CONTINUE)

    def test_a_turn_whose_start_was_not_seen(self):
        self.write("tests/test_cart.py", SKIPPED)
        self.assertIsNone(self.end())  # nothing known about this session
        self.start()
        self.shell("make fix")
        self.write("cart.py", "def total():\n    return 4\n")
        self.assertIsNone(self.end("some-other-turn"))  # what turn t1 saw says nothing about another turn
        self.tool_writes("cart.py", "def total():\n    return 6\n", turn="t9")
        self.assertEqual(self.end("t9")["action"], core.CONTINUE)  # its own writes still count
        self.shell("make again", turn="t10")  # a shell call starts the bookkeeping by itself
        self.write("cart.py", "def total():\n    return 7\n")
        self.assertEqual(self.end("t10")["action"], core.CONTINUE)

    def test_a_commit_made_in_the_turn_with_a_clean_tree_is_not_sent_back(self):
        self.start()
        self.shell("make fix")
        self.write("cart.py", "def total():\n    return 4\n")
        self.commit("change")
        self.assertIsNone(self.end())

    def test_sessions_do_not_share_their_turns(self):
        self.start()
        self.shell("make fix")
        self.write("tests/test_cart.py", SKIPPED)
        self.assertIsNone(self.end(session="s2"))
        self.assertIsNone(core.end_of_turn(self.host, self.root, "", "t1"))

    def test_old_session_files_are_pruned(self):
        core.turn_start(self.host, self.root, "old", "t1")
        path = core._session_file(self.host, "old", ".json")
        os.utime(path, (1, 1))
        core.turn_start(self.host, self.root, "s1", "t1")
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.exists(core._session_file(self.host, "s1", ".json")))

    def test_a_rename_is_read_as_one_changed_path(self):
        from foreman.detector import Repo
        self.git("mv", "cart.py", "basket.py")
        paths = [p for _code, p in core._dirty(Repo(self.root))]
        self.assertEqual(paths, [os.path.join(self.root, "basket.py")])


class PersonCommand(HostCase):
    def ask(self, text):
        return core.person_command(self.host, text, self.root, "s1")

    def test_ordinary_prompts_are_not_foremans(self):
        for text in ("fix the foreman bug", "foreman status", "what does /foreman:status do?", "/foremanx", "", None,
                     "/foreman is blocking my commit, why?", "/foreman\nplease explain what you blocked"):
            self.assertIsNone(self.ask(text), text)

    def test_status_without_a_directory_asks_for_a_path(self):
        out = core.person_command(self.host, "/foreman:status", "", "s1")
        self.assertIn("Give a path: `/foreman:status <path>`", out)
        self.assertIn("Foreman: CLEAN", core.person_command(self.host, "/foreman:status %s" % self.root, "", "s1"))

    def test_status_gives_the_verdict_of_the_session_directory(self):
        for text in ("/foreman:status", "/foreman status", "/foreman", "  /FOREMAN:STATUS  "):
            out = self.ask(text)
            self.assertIn("Foreman: CLEAN", out, text)
            self.assertIn(os.path.basename(self.root), out)

    def test_status_shows_a_blocker(self):
        self.write("tests/test_cart.py", SKIPPED)
        out = self.ask("/foreman:status")
        self.assertIn("Foreman: BLOCKED", out)
        self.assertIn("tests/test_cart.py:4", out)

    def test_status_takes_a_path(self):
        self.assertIn("is not inside a git repository", self.ask("/foreman:status %s" % self.tmp))
        self.assertIn("Foreman: CLEAN", self.ask("/foreman:status tests"))

    def test_the_person_allows_a_marked_finding_and_the_commit_then_passes(self):
        self.write("tests/test_cart.py", MARKED)
        self.git("add", "-A")
        self.assertEqual(self.shell("git commit -m green")["action"], core.BLOCK)
        listing = self.ask("/foreman:allow")
        self.assertIn("/foreman:allow <id>", listing)
        short_id = grants.pending()[0]["id"]
        self.assertIn(short_id, listing)
        self.assertIn("allowed %s" % short_id, self.ask("/foreman:allow %s" % short_id))
        self.assertIsNone(self.shell("git commit -m green"))

    def test_with_nobody_attending_nothing_is_allowed(self):
        self.write("tests/test_cart.py", MARKED)
        self.git("add", "-A")
        self.shell("git commit -m green")
        short_id = grants.pending()[0]["id"]
        self.present = False
        out = self.ask("/foreman:allow %s" % short_id)
        self.assertIn("nobody is attending", out)
        self.assertEqual(self.shell("git commit -m green")["action"], core.BLOCK)
        self.assertIn(short_id, self.ask("/foreman:allow"))  # listing needs nobody

    def test_help_lists_this_harness_commands_only(self):
        out = self.ask("/foreman:help")
        for name in core.PERSON_SUBCOMMANDS:
            self.assertIn("/foreman:" + name, out)
        self.assertNotIn("/foreman merge", out)
        self.assertNotIn("Hermes", out)

    def test_a_hermes_only_subcommand_says_so_and_an_unknown_one_gets_the_help(self):
        self.assertIn("not available in Test Host yet", self.ask("/foreman:merge 3"))
        self.assertIn("not available in Test Host yet", self.ask("/foreman merge 3"))
        self.assertIn("Unknown subcommand `frobnicate`", self.ask("/foreman:frobnicate"))

    def test_a_failure_is_an_answer_not_a_stack_trace(self):
        broken = core.Host(name="x", label="X", person=lambda sub: 1 / 0)
        self.assertIn("Foreman failed: ZeroDivisionError", core.person_command(broken, "/foreman:help", self.root))


class Words(unittest.TestCase):
    HOST = core.Host(name="x", label="X", person=lambda sub: "/foreman:" + sub)

    def test_the_gate_messages_that_name_hermes_things_are_all_reworded(self):
        # The two the tests above cannot reach through the gate are checked against its source: if the gate words
        # them differently one day, this fails and the rewording is updated, instead of Hermes's words leaking.
        from foreman import gate
        with open(gate.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for old, new in core._PLAIN[:2]:
            self.assertIn(old, source, "the gate no longer says: %s" % old)
            self.assertEqual(core.reword(self.HOST, "x %s y" % old), "x %s y" % new)
        merge = "Merging is the user's decision. Ask them to run `/foreman merge %s`."
        self.assertIn(merge, source)
        self.assertNotIn("/foreman", core.reword(self.HOST, merge % "12"))
        self.assertIn("`gh pr merge`", core.reword(self.HOST, merge % ""))

    def test_subcommands_take_the_harness_form(self):
        self.assertEqual(core.reword(self.HOST, "run `/foreman allow <id>` or `/foreman status`"),
                         "run `/foreman:allow <id>` or `/foreman:status`")
        self.assertEqual(json.loads(json.dumps(core.reword(self.HOST, ""))), "")


if __name__ == "__main__":
    unittest.main()
