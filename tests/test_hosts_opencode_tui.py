"""Foreman's TUI part for OpenCode (``adapters/opencode/tui.ts``): the person's ``/foreman`` typed at the prompt of
OpenCode's terminal interface, every reply in a dialog, a question in the select dialog, and merge and reject there
only. Driven by node or bun with a stand-in for OpenCode's TUI plugin context (``tests/opencode_tui.mjs``) against
the real Python side; for merge and reject, an entry point of the test's own puts the board's fake gh and a fake
reviewer in front of it (no network, no model). What OpenCode itself does with the plugin was seen in a real session
(adapters/opencode/README.md)."""
import json
import os
import subprocess
import sys
import unittest

import test_board as tb
import test_hosts_opencode as base
from tests_support import ROOT

from foreman_hosts import core, neutral, opencode

TESTS = os.path.dirname(os.path.abspath(__file__))
MERGE = ["pr", "merge", "7", "--squash", "--delete-branch", "--match-head-commit", tb.OID]

# The test's own entry point: the board's fake gh (each call logged), a reviewer that answers PASS, then OpenCode's
# dialect as `adapters/hook.py opencode` runs it.
FAKE_HOOK = """\
import dataclasses, json, os, sys
sys.path.insert(0, {tests!r})
import tests_support  # noqa: F401  (plugin/ and adapters/ on sys.path)
import test_board as tb
from foreman import board
from foreman_hosts import core, opencode

LOG = {log!r}


def note(entry):
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\\n")


class Gh(tb.FakeGh):
    def __call__(self, args, cwd, timeout):
        note(["gh"] + list(args))
        return super().__call__(args, cwd, timeout)


gh = Gh()
gh.add(["repo", "view"], {{"nameWithOwner": "acme/widgets", "defaultBranchRef": {{"name": "main"}}}})
gh.add(["pr", "view", "7"], tb.pr_view(7, closes=(3,)))
gh.add(["pr", "diff", "7"], tb.diff_adding_skip() if os.environ.get("FAKE_PR") == "blocked" else tb.clean_diff())
gh.add(["pr", "merge"], "", err="Squashed and merged pull request #7")
gh.add(["pr", "comment"], "https://github.com/acme/widgets/pull/7#issuecomment-1")
gh.add(["pr", "close"], "", err="Closed pull request #7")
board.GH_RUNNER = gh
PASS = {{"findings": [], "summary": "Nothing rigged.", "verdict": "PASS"}}


def fresh_session(system, prompt, schema, model, effort, seconds):
    note(["review", model, effort])
    return core.Answer(parsed=PASS, text=json.dumps(PASS), model="model-that-ran")


real = opencode.host
opencode.host = lambda request=None: dataclasses.replace(real(request), fresh_session=fresh_session)
sys.exit(opencode.main())
"""

# An entry point whose question never settles: each run asks another one.
ENDLESS_HOOK = """\
import json, sys, uuid
sys.stdin.read()
print(json.dumps({"question": {"id": uuid.uuid4().hex, "question": "Pick one?",
                               "options": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}]}}))
"""

# An entry point that answers after two seconds.
SLOW_HOOK = """\
import json, sys, time
sys.stdin.read()
time.sleep(2)
print(json.dumps({"reply": "late"}))
"""


def kinds(shown):
    """What the TUI showed, without the dialog's size: ["select", "alert", …]."""
    return [entry[0] for entry in shown if entry[0] != "set"]


def alerts(shown):
    return [entry[2] for entry in shown if entry[0] == "alert"]


@unittest.skipUnless(base.RUNTIME, "needs bun, or node 22.6 or newer, to run the plugin's TypeScript")
class TuiCase(base.OpenCodeCase):
    def drive(self, scenario, hook=None, **env):
        home = os.path.join(self.tmp, "home")
        os.makedirs(home, exist_ok=True)
        extra = [hook, sys.executable] if hook else []
        r = subprocess.run(base.RUNTIME + [os.path.join(TESTS, "opencode_tui.mjs"), self.root, scenario, *extra],
                           capture_output=True, env=dict(os.environ, HOME=home, USERPROFILE=home, **env),
                           cwd=self.root, timeout=180)  # the TUI started in the project, as a person starts it
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        return json.loads(r.stdout.decode())

    def hook(self, text, **values):
        path = os.path.join(self.tmp, "entry", "hook.py")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.format(**values) if values else text)
        return path


class Reads(TuiCase):
    def setUp(self):
        super().setUp()
        with open(os.path.join(self.root, ".git", "info", "exclude"), "a", encoding="utf-8") as fh:
            fh.write("other/\n")
        os.makedirs(os.path.join(self.root, "other"))
        self.git("init", "-q", cwd=os.path.join(self.root, "other"))

    def test_the_command_is_a_tui_slash_command_and_every_reply_is_a_dialog(self):
        out = self.drive("reads")
        self.assertEqual(out["layer"], [{"mode": "global", "commands": [
            {"id": "foreman.command", "slash": {"name": "foreman", "arguments": True}}]}])
        # `/foreman` alone is the board, in an alert dialog made wide: never an error notice, never the model's context
        self.assertEqual(kinds(out["board"]), ["alert"])
        self.assertIn("Foreman board: repo", alerts(out["board"])[0])
        self.assertIn(["set", {"size": "xlarge", "centered": True}], out["board"])
        help_text = alerts(out["help"])[0]
        self.assertIn("/foreman merge ", help_text)
        self.assertIn("work only in OpenCode's terminal interface", help_text)
        self.assertEqual(kinds(out["home"]), ["alert"])  # on the home screen too
        # the registered command does not hold the TUI's prompt while Foreman works: its dialog comes after
        self.assertLess(out["returnedAt"], 1000)
        self.assertEqual(out["immediately"], 0)
        self.assertIn("In OpenCode:", alerts(out["registered"])[0])

    def test_a_pin_on_the_home_screen_is_not_a_sessions(self):
        out = self.drive("reads")
        self.assertIn("pinned", alerts(out["homePin"])[0])
        self.assertNotIn("other", alerts(out["sessionAfterHomePin"])[0].splitlines()[1])

    def test_use_asks_in_the_select_dialog_and_pins_the_pick(self):
        out = self.drive("reads")
        self.assertEqual(kinds(out["dismissed"]), ["select", "alert"])  # closed: asked once, nothing pinned
        self.assertIn("repositories you can pin", alerts(out["dismissed"])[0])
        select = out["picked"][0]
        self.assertEqual(select[0], "select")
        self.assertIn("Which repository", select[1])
        self.assertEqual(len(select[2]), 2, select[2])
        self.assertIn("pinned", alerts(out["picked"])[0])
        self.assertIn("other", alerts(out["picked"])[0])
        self.assertIn("other", alerts(out["status"])[0].splitlines()[1])  # the pinned repository's verdict
        self.assertEqual([o["title"] for o in out["options"]], ["1. x", "2. x", "3. y"])
        self.assertEqual(out["limit"], 720_000)  # neutral.py: twelve minutes where the command can merge

    def test_a_question_that_never_settles_is_asked_three_times_and_no_more(self):
        out = self.drive("endless", self.hook(ENDLESS_HOOK))
        self.assertEqual(kinds(out["endless"]), ["select", "select", "select", "alert"])
        self.assertIn("nothing was done", alerts(out["endless"])[0])

    def test_a_slow_answer_shows_that_foreman_is_working(self):
        out = self.drive("slow", self.hook(SLOW_HOOK))
        self.assertEqual(kinds(out["slow"]), ["toast", "alert"])
        self.assertIn("Foreman is working on /foreman status", out["slow"][0][1])
        self.assertEqual(alerts(out["slow"]), ["late"])

    def test_when_python_cannot_answer_the_person_reads_why(self):
        out = self.drive("broken")
        self.assertEqual(kinds(out["broken"]), ["alert"])
        self.assertIn("Foreman could not run", alerts(out["broken"])[0])


class Allow(TuiCase):
    def test_allow_asks_the_person_to_confirm_the_findings_id(self):
        self.write("tests/test_cart.py", base.MARKED)
        self.git("add", "-A")
        out = self.drive("allow")
        self.assertTrue(out["id"])
        self.assertEqual(kinds(out["cancelled"]), ["confirm", "alert"])
        self.assertIn(out["id"], out["cancelled"][0][1])           # the dialog names the finding
        self.assertIn("not allowed", alerts(out["cancelled"])[0])
        self.assertEqual(out["still"]["action"], "block")          # cancelled: still waiting
        self.assertIn("allowed " + out["id"], alerts(out["allowed"])[0])
        self.assertEqual(out["after"], {})


class Writes(TuiCase):
    def setUp(self):
        super().setUp()
        self.git("remote", "add", "origin", "https://github.com/acme/widgets.git")
        self.log = os.path.join(self.tmp, "calls.jsonl")

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def writes(self):
        return [c[1:] for c in self.calls() if c[0] == "gh" and tuple(c[1:3]) in (("pr", "merge"), ("pr", "comment"),
                                                                                    ("pr", "close"))]

    def test_merge_asks_and_only_the_pick_starts_the_merge_of_the_commit_reviewed(self):
        out = self.drive("writes", self.hook(FAKE_HOOK, tests=TESTS, log=self.log), FAKE_PR="clean")
        # closed without a pick, or Cancel: asked, nothing merged
        for name in ("dismissed", "cancelled"):
            self.assertEqual(kinds(out[name]), ["select", "alert"], name)
            self.assertIn("PR #7 was not merged", alerts(out[name])[0])
        select = out["merged"][0]
        self.assertEqual(select[0], "select")
        self.assertIn("Merge PR #7 of acme/widgets", select[1])
        self.assertEqual([o["value"] for o in select[2]], ["merge", "cancel"])
        self.assertIn("merged PR #7 (squash) in acme/widgets", alerts(out["merged"])[0])
        self.assertEqual(self.writes(), [MERGE])                    # exactly one gh write, pinned to the commit
        reviews = [c for c in self.calls() if c[0] == "review"]
        self.assertEqual(reviews[0][1], "p/m-1")                    # the session's model, as OpenCode records it
        self.assertEqual(len(reviews), 1)                           # reviewed once, then the stored review

    def test_reject_close_asks_first_and_a_closed_dialog_posts_nothing(self):
        out = self.drive("reject", self.hook(FAKE_HOOK, tests=TESTS, log=self.log), FAKE_PR="blocked")
        self.assertEqual(kinds(out["dismissed"]), ["select", "alert"])
        self.assertIn("cancelled; nothing was posted", alerts(out["dismissed"])[0])
        self.assertEqual([o["value"] for o in out["closed"][0][2]], ["close", "post", "cancel"])
        self.assertIn("closed PR #7", alerts(out["closed"])[0])
        self.assertEqual([w[:2] for w in self.writes()], [["pr", "comment"], ["pr", "close"]])
        self.assertIn("Posted with `/foreman reject` from OpenCode.", alerts(out["closed"])[0])


@unittest.skipUnless(base.RUNTIME, "needs bun, or node 22.6 or newer, to run the plugin's TypeScript")
class ServerCommand(base.OpenCodeCase):
    """The server part's `/foreman` (apps, HTTP API, SDK, `opencode api`): merge and reject find nobody there."""

    def test_merge_and_reject_answer_nobody_is_attending_and_allow_never_unlocks_them(self):
        out = base.Plugin.drive(self, "server-writes")
        for name in ("merge", "mergeYes", "reject"):
            self.assertFalse(out[name]["ok"])
            self.assertIn("nobody is attending", out[name]["error"], name)
            self.assertIn("OpenCode's terminal interface (the TUI)", out[name]["error"], name)
        self.assertEqual(out["askedForWrites"], 0)  # no question for them: the permission prompt is not their sign
        self.assertEqual(out["asked"], [["merge"]])  # `allow merge 7` asks about a finding called "merge"…
        self.assertNotIn("merged", out["allowNamedMerge"]["error"])  # …and allows nothing else


class Dialect(base.OpenCodeCase):
    def test_merge_and_reject_are_listed_and_need_the_json_true(self):
        self.assertEqual(opencode.host({}).board, core.BOARD_READS + core.BOARD_WRITES)
        for attended in (None, False, "true", 1):
            request = {"event": "command", "args": "merge 7", "cwd": self.root, "session": "s", "attended": attended}
            reply = neutral.answer(opencode.host(request), request)["reply"]
            self.assertIn("nobody is attending", reply)
            self.assertIn("Type `/foreman merge 7` in OpenCode's terminal interface (the TUI)", reply)

    def test_allows_message_names_the_tui_too(self):
        self.write("tests/test_cart.py", base.MARKED)
        self.git("add", "-A")
        self.assertEqual(self.ask("shell", command="git commit -m green")["action"], "block")
        from foreman import grants
        short_id = grants.pending()[0]["id"]
        self.assertIn("OpenCode's terminal interface", self.ask("command", args="allow " + short_id)["reply"])

    def test_the_agent_cannot_type_the_persons_merge_through_a_nested_opencode(self):
        for command in ("opencode run '/foreman merge 7'", "opencode run '/foreman reject 7 --close --yes'",
                        "echo '/foreman merge 7 --yes' | opencode run"):
            out = self.ask("shell", command=command)
            self.assertEqual(out["action"], "block", command)
            self.assertIn("/foreman merge <pr>", out["message"])
        self.assertIn("/foreman merge 7", self.ask("shell", command="gh pr merge 7")["message"])


class Guards(base.OpenCodeCase):
    """The folder form (the TUI part needs it) and the TUI's own configuration, as far as the plain attempts go."""

    def test_the_folder_and_the_tuis_configuration(self):
        for command in ("rm -rf .opencode/plugins/foreman", "rm .opencode/plugins/foreman/tui.ts",
                        "mv .opencode/plugins/foreman /tmp/x", "rm -rf ~/.config/opencode/plugins/foreman",
                        "echo '{\"plugins\": [\"-foreman\"]}' > ~/.config/opencode/cli.json",
                        "echo '{\"plugins\": [\"-*\"]}' > ~/.config/opencode/cli.json",
                        "jq '.plugins += [\"-*\"]' ~/.config/opencode/cli.json > t && mv t ~/.config/opencode/cli.json"):
            self.assertEqual(self.ask("shell", command=command).get("action"), "block", command)
        for command in ("cat ~/.config/opencode/cli.json", "echo '{\"theme\": {}}' > ~/.config/opencode/cli.json",
                        "rm -rf build/cli.json", "echo '{\"plugins\": [\"-*\"]}' > tools/cli.json"):
            self.assertNotEqual(self.ask("shell", command=command).get("action"), "block", command)

    def test_a_copied_folders_files_cannot_be_rewritten_and_the_cli_config_cannot_drop_it(self):
        folder = os.path.join(self.root, ".opencode", "plugins", "foreman")
        self.write(".opencode/plugins/foreman/tui.ts", base.PLUGIN_FILE)
        self.write(".opencode/plugins/foreman/server.ts", base.PLUGIN_FILE)
        for name in ("tui.ts", "server.ts"):
            path = os.path.join(folder, name)
            self.assertEqual(self.ask("write", path=path, content="export default {}\n")["action"], "block", name)
        out = self.ask("patch", patch="*** Begin Patch\n*** Delete File: .opencode/plugins/foreman/tui.ts\n"
                                      "*** End Patch\n")
        self.assertEqual(out["action"], "block")
        home = os.path.join(self.tmp, "config", "opencode")
        cli = os.path.join(home, "cli.json")
        self.assertTrue(opencode._is_config(cli))
        self.assertEqual(self.ask("write", path=cli, content='{"plugins": ["-foreman"]}')["action"], "block")
        self.assertEqual(self.ask("write", path=cli, content='{"theme": {"name": "x"}}'), {})
        self.assertFalse(opencode._is_config(os.path.join(self.root, "tools", "cli.json")))

    def test_the_shipped_files_define_foreman_so_rewriting_them_is_switching_it_off(self):
        for name in ("tui.ts", "server.ts", "foreman.ts"):
            with open(os.path.join(ROOT, "adapters", "opencode", name), encoding="utf-8") as fh:
                text = fh.read()
            self.assertTrue(opencode._DEFINES.search(text), name)
            self.assertTrue(opencode._config_off(text, ""), name)


class Files(unittest.TestCase):
    def read(self, name):
        with open(os.path.join(ROOT, "adapters", "opencode", name), encoding="utf-8") as fh:
            return fh.read()

    def test_the_tui_part_imports_nothing_but_nodes_built_ins_and_the_server_parts_file(self):
        for name in ("tui.ts", "server.ts"):
            for line in self.read(name).splitlines():
                if line.startswith("import "):
                    self.assertTrue('from "node:' in line or line.endswith('from "./foreman.ts"'), line)


if __name__ == "__main__":
    unittest.main()
