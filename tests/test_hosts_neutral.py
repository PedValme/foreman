"""The protocol for harnesses whose extensions run inside the harness (``adapters/foreman_hosts/neutral.py``), the
patch entry of the host-neutral half, and the entry point's choice of adapter."""
import io
import json
import os
import sys

from tests_support import GitRepoCase

from foreman import grants
from foreman.detector import MARKER
from foreman_hosts import core, hosts, neutral

# Built from parts: Foreman reads its own test files, and a literal marker here would be a finding in this
# repository's pull requests.
SKIP = "@pytest.mark." + "skip"
SKIPPED = "import pytest\n\n\n" + SKIP + "\ndef test_total():\n    assert 1 + 1 == 2\n"
MARKED = ("import pytest\n\n\n" + SKIP + "  # " + MARKER + " flaky upstream\ndef test_total():\n"
          "    assert 1 + 1 == 2\n")


def host_for(request: dict) -> core.Host:
    return core.Host(name="test-host", label="Test Host", person=lambda sub: "/foreman " + sub, cli=("testh",),
                     is_config=lambda path: path.endswith("settings.json"),
                     config_off=lambda before, after: after.count("HOOKS-OFF") > before.count("HOOKS-OFF"),
                     attended=lambda: request.get("attended") is True)


class NeutralCase(GitRepoCase):
    def setUp(self):
        super().setUp()
        self.write("tests/test_cart.py", "def test_total():\n    assert 1 + 1 == 2\n")
        self.write("cart.py", "def total():\n    return 2\n")
        self.commit("base")

    def ask(self, event, **more):
        request = {"event": event, "cwd": self.root, "session": "s1", "turn": "t1"}
        request.update(more)
        return neutral.answer(host_for(request), request)


class Answers(NeutralCase):
    def test_a_call_that_goes_on_is_an_empty_object(self):
        self.assertEqual(self.ask("shell", command="ls -la"), {})
        self.assertEqual(self.ask("write", path=os.path.join(self.root, "cart.py"), content="x = 1\n"), {})
        self.assertEqual(self.ask("turn_start"), {})
        self.assertEqual(self.ask("turn_end"), {})

    def test_a_rigged_commit_and_an_agent_run_merge_are_blocked(self):
        self.write("tests/test_cart.py", SKIPPED)
        self.git("add", "-A")
        out = self.ask("shell", command="git commit -m green")
        self.assertEqual(out["action"], "block")
        self.assertIn("tests/test_cart.py:4", out["message"])
        self.assertEqual(self.ask("shell", command="gh pr merge 3")["action"], "block")

    def test_what_the_gate_cannot_inspect_is_the_persons(self):
        out = self.ask("shell", command="git commit -m x", cwd=os.path.join(self.tmp, "gone"))
        self.assertEqual(out["action"], "ask")

    def test_writes_in_their_three_forms(self):
        path = os.path.join(self.root, "tests", "test_cart.py")
        self.assertEqual(self.ask("write", path=path, content=SKIPPED)["action"], "block")
        self.assertEqual(self.ask("write", path=path, old="def test_total():",
                                  new=SKIP + "\ndef test_total():")["action"], "block")
        self.assertEqual(self.ask("write", path=path), {})  # a change the extension cannot read: guards only
        state = os.path.join(grants.store_dir(), "sessions", "x.json")
        self.assertEqual(self.ask("write", path=state)["action"], "block")

    def test_a_patch_is_read_by_the_gate(self):
        patch = ("*** Begin Patch\n*** Update File: tests/test_cart.py\n@@\n+" + SKIP + "\n def test_total():\n"
                 "*** End Patch\n")
        out = self.ask("patch", patch=patch)
        self.assertEqual(out["action"], "block")
        self.assertIn("test-skipped", out["message"])

    def test_a_turn_that_left_a_skipped_test_is_sent_back_once(self):
        self.ask("turn_start")
        self.ask("shell", command="make fix")
        self.write("tests/test_cart.py", SKIPPED)
        out = self.ask("turn_end")
        self.assertEqual(out["action"], "continue")
        self.assertIn("tests/test_cart.py:4", out["message"])
        self.assertEqual(self.ask("turn_end"), {})

    def test_a_harness_without_turn_ids_still_gets_one_nudge_per_turn(self):
        self.ask("turn_start", turn="")
        self.ask("shell", command="make fix", turn="")
        self.write("tests/test_cart.py", SKIPPED)
        self.assertEqual(self.ask("turn_end", turn="")["action"], "continue")
        self.assertEqual(self.ask("turn_end", turn=""), {})
        self.ask("turn_start", turn="")
        self.ask("shell", command="make more", turn="")
        self.write("cart.py", "def total():\n    return 9\n")
        self.assertEqual(self.ask("turn_end", turn="")["action"], "continue")

    def test_the_persons_command_is_answered_in_the_harness_words(self):
        self.assertIn("Foreman: CLEAN", self.ask("command", args="")["reply"])
        self.assertIn("Foreman: CLEAN", self.ask("command", args="status")["reply"])
        self.assertIn("/foreman allow", self.ask("command", args="help")["reply"])
        self.assertIn("Unknown subcommand `frobnicate`", self.ask("command", args="frobnicate now")["reply"])
        self.assertIn("not available in Test Host yet", self.ask("command", args="merge 3")["reply"])

    def test_allow_needs_a_person_at_the_interface(self):
        self.write("tests/test_cart.py", MARKED)
        self.git("add", "-A")
        self.assertEqual(self.ask("shell", command="git commit -m green")["action"], "block")
        short_id = grants.pending()[0]["id"]
        self.assertIn("nobody is attending", self.ask("command", args="allow " + short_id)["reply"])
        self.assertIn("nobody is attending", self.ask("command", args="allow " + short_id, attended="yes")["reply"])
        self.assertEqual(self.ask("shell", command="git commit -m green")["action"], "block")
        self.assertIn("allowed " + short_id, self.ask("command", args="allow " + short_id, attended=True)["reply"])
        self.assertEqual(self.ask("shell", command="git commit -m green"), {})

    def test_an_unknown_event_is_an_error_not_a_pass(self):
        with self.assertRaises(ValueError):
            self.ask("pre_tool")

    def test_the_agent_cannot_run_the_entry_point_for_any_host(self):
        for name in hosts.MODULES:
            out = self.ask("shell", command="echo '{}' | python3 adapters/hook.py %s" % name)
            self.assertEqual(out.get("action"), "block", name)


class Main(NeutralCase):
    def run_main(self, raw):
        stdout = io.StringIO()
        code = neutral.main(host_for, stdin=io.StringIO(raw) if isinstance(raw, str) else io.BytesIO(raw),
                            stdout=stdout)
        return code, stdout.getvalue()

    def test_one_request_one_answer(self):
        code, out = self.run_main(json.dumps({"event": "shell", "command": "ls", "cwd": self.root}))
        self.assertEqual((code, json.loads(out)), (0, {}))
        code, out = self.run_main(b"\xef\xbb\xbf" + json.dumps({"event": "shell", "command": "gh pr merge 1",
                                                               "cwd": self.root}).encode())
        self.assertEqual((code, json.loads(out)["action"]), (0, "block"))

    def test_what_is_not_a_request_is_an_error_with_no_answer(self):
        for raw in ("", "{not json", "[]", '"shell"'):
            self.assertEqual(self.run_main(raw), (1, ""), raw)
        self.assertEqual(self.run_main(json.dumps({"event": "nope"})), (1, ""))

    def test_when_the_adapter_fails_a_gated_command_goes_to_the_person(self):
        old = core.pre_shell
        core.pre_shell = lambda *a, **k: 1 / 0
        try:
            code, out = self.run_main(json.dumps({"event": "shell", "command": "git push", "cwd": self.root}))
            self.assertEqual((code, json.loads(out)["action"]), (0, "ask"))
            self.assertEqual(self.run_main(json.dumps({"event": "shell", "command": "ls", "cwd": self.root})), (1, ""))
        finally:
            core.pre_shell = old


class Patches(NeutralCase):
    HOST = None

    def setUp(self):
        super().setUp()
        self.host = host_for({})

    def patch(self, body, cwd=None):
        return core.pre_patch(self.host, "*** Begin Patch\n" + body + "*** End Patch\n", cwd or self.root, "s1", "t1")

    def test_an_ordinary_patch_passes_and_its_files_are_remembered(self):
        self.assertIsNone(self.patch("*** Update File: cart.py\n@@\n-    return 2\n+    return 3\n"))
        self.assertEqual(core._touched(self.host, "s1", "t1"), [os.path.join(self.root, "cart.py")])

    def test_relative_paths_are_read_from_the_directory_the_harness_gave(self):
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.makedirs(elsewhere)
        before = os.getcwd()
        body = "*** Add File: tests/test_new.py\n+" + SKIP + "\n+def test_new():\n+    assert True\n"
        inside = self.patch(body)
        self.assertEqual(inside["action"], core.BLOCK)
        self.assertIn("] tests/test_new.py", inside["message"])          # found in the repository the harness is in
        outside = self.patch(body, cwd=elsewhere)
        self.assertEqual(outside["action"], core.BLOCK)
        self.assertIn(os.path.join("elsewhere", "tests", "test_new.py"), outside["message"])  # ...not in this process's
        self.assertEqual(os.getcwd(), before)

    def test_a_patch_cannot_reach_foremans_state_or_switch_it_off(self):
        state = os.path.join(grants.store_dir(), "sessions", "x.json")
        for verb in ("Update", "Add", "Delete"):
            d = self.patch("*** %s File: %s\n+x\n" % (verb, state))
            self.assertEqual(d["action"], core.BLOCK, verb)
            self.assertIn("own program and state", d["message"])
        d = self.patch("*** Update File: cart.py\n*** Move to: %s\n@@\n-a\n+b\n" % state)
        self.assertEqual(d["action"], core.BLOCK)
        settings = os.path.join(self.tmp, ".claude", "settings.json")
        d = self.patch("*** Update File: %s\n@@\n-HOOKS-ON\n+HOOKS-OFF\n" % settings)
        self.assertIn("user's decision", d["message"])
        self.assertIsNone(self.patch("*** Update File: %s\n@@\n-model a\n+model b\n" % settings))

    def test_what_is_not_a_patch_is_let_through(self):
        for value in (None, "", "   ", 7):
            self.assertIsNone(core.pre_patch(self.host, value, self.root, "s1", "t1"))


class EntryPointChoice(NeutralCase):
    def run_hook(self, argv):
        import hook
        old = sys.stderr
        sys.stderr = io.StringIO()
        try:
            return hook.main(argv), sys.stderr.getvalue()
        finally:
            sys.stderr = old

    def test_an_unknown_host_names_the_known_ones(self):
        code, err = self.run_hook(["nope"])
        self.assertEqual(code, 1)
        for name in hosts.MODULES:
            self.assertIn(name, err)
        self.assertEqual(self.run_hook([])[0], 1)

    def test_a_listed_host_whose_adapter_is_not_installed_says_so(self):
        hosts.MODULES["ghost"] = "ghost_not_there"
        try:
            code, err = self.run_hook(["ghost"])
        finally:
            del hosts.MODULES["ghost"]
        self.assertEqual(code, 1)
        self.assertIn("not part of this installation", err)

    def test_every_adapter_module_that_exists_has_a_main(self):
        import importlib
        import importlib.util
        present = [m for m in hosts.MODULES.values() if importlib.util.find_spec("foreman_hosts." + m)]
        self.assertIn("claude_code", present)
        for module in present:
            self.assertTrue(callable(importlib.import_module("foreman_hosts." + module).main), module)
