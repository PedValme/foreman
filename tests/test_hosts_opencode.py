"""OpenCode's adapter: its dialect (``adapters/foreman_hosts/opencode.py``), the entry point as the plugin runs it,
and the plugin itself (``adapters/opencode/foreman.ts``) driven by node or bun where one is installed."""
import io
import json
import os
import shutil
import subprocess
import sys
import unittest

from tests_support import ROOT, GitRepoCase

from foreman import grants
from foreman.detector import MARKER
from foreman_hosts import neutral, opencode

# Built from parts, as in the other tests: Foreman reads its own test files, and a literal marker here would be
# a finding in this repository's pull requests.
SKIP = "@pytest.mark." + "skip"
SKIPPED = "import pytest\n\n\n" + SKIP + "\ndef test_total():\n    assert 1 + 1 == 2\n"
MARKED = ("import pytest\n\n\n" + SKIP + "  # " + MARKER + " flaky upstream\ndef test_total():\n"
          "    assert 1 + 1 == 2\n")
PLUGIN_FILE = "import x\nexport default { id: \"foreman\", setup: async () => {} }\n"


class OpenCodeCase(GitRepoCase):
    def setUp(self):
        super().setUp()
        self.write("tests/test_cart.py", "def test_total():\n    assert 1 + 1 == 2\n")
        self.write("cart.py", "def total():\n    return 2\n")
        self.commit("base")

    def ask(self, event, **more):
        request = {"event": event, "cwd": self.root, "session": "ses_1", "turn": "msg_1"}
        request.update(more)
        return neutral.answer(opencode.host(request), request)


class Guards(OpenCodeCase):
    def test_the_agent_cannot_turn_foreman_off(self):
        for command in ("opencode plugin remove foreman", "opencode2 plugin rm foreman",
                        "npx opencode-ai plugin remove foreman",
                        "echo '{\"plugins\": [\"-foreman\"]}' > opencode.json",
                        "rm .opencode/plugins/foreman.ts", "rm ~/.config/opencode/plugins/foreman.ts",
                        "OPENCODE_DISABLE_PROJECT_CONFIG=1 opencode run 'commit it'",
                        "env OPENCODE_CONFIG_CONTENT='{}' opencode run x",
                        # the folder a plugin link lives in, removed or emptied: the project's and the user's
                        "rm -rf .opencode", "rm -rf ./.opencode/", "mv .opencode elsewhere", "rmdir .opencode/plugins",
                        "rm -rf .opencode/*", "rm -rf .opencode/plugins/*", "rm .opencode/plugins/*.ts",
                        "rm -rf ~/.config/opencode/plugins", "rm -rf ~/.config/opencode", "mv ~/.config/opencode ~/x",
                        "rm -rf ~/.config/opencode/plugins/*", "rm -rf $HOME/.config/opencode",
                        "rm -rf $XDG_CONFIG_HOME/opencode/plugins", "rm -rf \"${XDG_CONFIG_HOME}/opencode\"",
                        "rm -rf ~/.config",
                        # a plugin-removing entry written to the configuration without naming Foreman
                        "echo '{\"plugins\": [\"-*\"]}' > opencode.json",
                        "jq '.plugins += [\"-*\"]' opencode.json > t && mv t opencode.json",
                        "printf '%s' '{\"plugins\":[\"-*\"]}' | tee .opencode/opencode.jsonc",
                        "sed -i '' 's/\"plugins\": \\[/\"plugins\": [\"-*\", /' opencode.json"):
            self.assertEqual(self.ask("shell", command=command).get("action"), "block", command)

    def test_the_users_folder_by_its_absolute_path(self):
        xdg = os.path.join(self.tmp, "xdg")
        old = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = xdg
        try:
            for target in (os.path.join(xdg, "opencode"), os.path.join(xdg, "opencode", "plugins")):
                self.assertEqual(self.ask("shell", command='rm -rf "%s"' % target).get("action"), "block", target)
            other = os.path.join(xdg, "opencode", "plugins", "mine.ts")
            self.assertNotEqual(self.ask("shell", command='rm "%s"' % other).get("action"), "block")
        finally:
            if old is None:
                del os.environ["XDG_CONFIG_HOME"]
            else:
                os.environ["XDG_CONFIG_HOME"] = old

    def test_ordinary_work_near_opencodes_files_is_not_refused(self):
        for command in ("rm -rf .opencode-cache node_modules", "rm -rf build/.opencode.bak", "ls .opencode",
                        # one other named plugin of the project's own, removed or renamed
                        "rm .opencode/plugins/mine.ts", "unlink .opencode/plugin/f.ts",
                        "mv .opencode/plugins/old.ts .opencode/plugins/new.ts",
                        "rm ~/.config/opencode/plugins/mine.ts",
                        # the config file named in what is written elsewhere
                        "echo 'see \"-*\" in opencode.json' >> NOTES.md",
                        "grep -n '\"-*\"' opencode.json", "jq .plugins opencode.json",
                        "git commit --allow-empty -m 'drop \"-*\" from opencode.json'",
                        "echo '{\"model\": \"a/b\"}' > opencode.json",
                        # a plain copy over the configuration: its content is not in the command (see _switches_off)
                        "cp opencode.example.json opencode.json"):
            self.assertNotEqual(self.ask("shell", command=command).get("action"), "block", command)

    def test_reading_opencodes_settings_is_ordinary_work(self):
        for command in ("opencode plugin list", "cat opencode.json", "grep foreman .opencode/plugins/foreman.ts",
                        "ls .opencode/plugins", "opencode run 'say hi'",
                        "git commit --allow-empty -m 'opencode plugin remove foreman is blocked'",
                        "git add opencode.json .opencode/plugins/foreman.ts"):
            self.assertNotEqual(self.ask("shell", command=command).get("action"), "block", command)

    def test_a_config_write_that_removes_foreman_is_blocked(self):
        config = os.path.join(self.root, "opencode.json")
        out = self.ask("write", path=config, content='{"plugins": ["-foreman"]}')
        self.assertEqual(out["action"], "block")
        self.assertIn("user's decision", out["message"])
        self.assertEqual(self.ask("write", path=config, content='{"plugins": ["-*"]}')["action"], "block")
        self.assertEqual(self.ask("write", path=config, content='{"model": "x/y"}'), {})
        self.assertEqual(self.ask("write", path=config, content='{"plugins": ["-other"]}'), {})
        self.write("opencode.json", '{"plugins": ["foreman"]}')
        self.assertEqual(self.ask("write", path=config, old='"foreman"', new='"-foreman"')["action"], "block")

    def test_dropping_the_package_entry_opencode_plugin_add_wrote_is_blocked(self):
        config = os.path.join(self.root, "opencode.json")
        for entry in ("foreman-gate", "foreman-gate@0.1.0", "git+https://github.com/PedValme/foreman.git",
                      "git+https://github.com/PedValme/foreman.git#v0.1.0", "github:PedValme/foreman"):
            listed = '{"plugins": ["other", "%s"], "model": "a"}' % entry
            self.write("opencode.json", listed)
            out = self.ask("write", path=config, content='{"plugins": ["other"], "model": "a"}')
            self.assertEqual(out["action"], "block", entry)
            self.assertEqual(self.ask("write", path=config, old='"a"', new='"b"'), {}, entry)
        self.assertTrue(opencode._config_off('["foreman-gate"]', ""))  # the file deleted
        self.assertFalse(opencode._config_off('["foreman-gate"]', '["foreman-gate", "other"]'))
        for command in ("opencode plugin remove foreman-gate",
                        "opencode plugin remove git+https://github.com/PedValme/foreman.git"):
            self.assertEqual(self.ask("shell", command=command)["action"], "block", command)

    def test_a_package_opencode_installed_is_foremans_whole(self):
        # `opencode plugin add` installs into <cache>/opencode/npm/<key>/<generation>/node_modules/foreman-gate, and
        # its package.json names the server and TUI parts: rewriting it switches Foreman off.
        copy = os.path.join(self.tmp, "cache", "opencode", "npm", "git-foreman-1a2b", "17", "node_modules",
                            "foreman-gate")
        self.assertEqual(opencode._program_dirs(copy)[0], copy)
        clone = os.path.join(self.tmp, "src", "foreman")
        self.assertEqual(opencode._program_dirs(clone),
                         (os.path.join(clone, "adapters"), os.path.join(clone, "plugin")))

    def test_what_the_person_switched_off_themselves_can_still_be_edited(self):
        self.write("opencode.jsonc", '{"plugins": ["-foreman"], "model": "a"}')
        config = os.path.join(self.root, "opencode.jsonc")
        self.assertEqual(self.ask("write", path=config, old='"a"', new='"b"'), {})

    def test_the_plugin_file_cannot_be_rewritten_or_deleted(self):
        self.write(".opencode/plugins/foreman.ts", PLUGIN_FILE)
        path = os.path.join(self.root, ".opencode", "plugins", "foreman.ts")
        self.assertEqual(self.ask("write", path=path, content="export default {}\n")["action"], "block")
        out = self.ask("patch", patch="*** Begin Patch\n*** Delete File: .opencode/plugins/foreman.ts\n*** End Patch\n")
        self.assertEqual(out["action"], "block")
        other = os.path.join(self.root, ".opencode", "plugins", "mine.ts")
        self.assertEqual(self.ask("write", path=other, content="export default {}\n"), {})

    def test_the_agent_cannot_touch_this_clone_or_run_its_entry_point(self):
        hook = os.path.join(ROOT, "adapters", "hook.py")
        self.assertEqual(self.ask("shell", command="python3 %s opencode < fake.json" % hook)["action"], "block")
        self.assertEqual(self.ask("write", path=os.path.join(ROOT, "adapters", "opencode", "foreman.ts"),
                                  content="x")["action"], "block")
        self.assertEqual(self.ask("write", path=os.path.join(ROOT, "plugin", "foreman", "gate.py"))["action"],
                         "block")

    def test_the_agent_cannot_type_the_persons_allow_through_a_nested_opencode(self):
        # (`opencode run` sends it to the model as a prompt anyway; an `opencode api` call that reaches the command
        # still meets OpenCode's question to the person, which only a person answers.)
        for command in ("opencode run '/foreman allow 3f2a'", "echo '/foreman allow 3f2a' | opencode run"):
            self.assertEqual(self.ask("shell", command=command)["action"], "block", command)


class PersonCommands(OpenCodeCase):
    def test_status_and_help_in_opencodes_words(self):
        self.assertIn("Foreman: CLEAN", self.ask("command", args="status")["reply"])
        reply = self.ask("command", args="help")["reply"]
        self.assertIn("In OpenCode:", reply)
        self.assertIn("/foreman allow", reply)
        for word in ("Hermes", "workdir", "write_file"):
            self.assertNotIn(word, reply)

    def test_allow_needs_the_json_true(self):
        self.write("tests/test_cart.py", MARKED)
        self.git("add", "-A")
        self.assertEqual(self.ask("shell", command="git commit -m green")["action"], "block")
        short_id = grants.pending()[0]["id"]
        for attended in (None, False, "true", 1):
            self.assertIn("nobody is attending", self.ask("command", args="allow " + short_id,
                                                          attended=attended)["reply"])
        self.assertIn("/foreman allow " + short_id, self.ask("command", args="allow " + short_id)["reply"])
        self.assertIn("allowed " + short_id, self.ask("command", args="allow " + short_id, attended=True)["reply"])
        self.assertEqual(self.ask("shell", command="git commit -m green"), {})

    def test_the_gates_messages_name_opencodes_command(self):
        self.write("tests/test_cart.py", MARKED)
        self.git("add", "-A")
        message = self.ask("shell", command="git commit -m green")["message"]
        self.assertIn("/foreman allow", message)
        self.assertNotIn("Hermes", message)


class EntryPoint(OpenCodeCase):
    """``python3 -I adapters/hook.py opencode``, as the plugin runs it."""

    def run_hook(self, request):
        home = os.path.join(self.tmp, "home")
        os.makedirs(home, exist_ok=True)
        env = dict(os.environ, HOME=home, USERPROFILE=home, PYTHONPATH=os.path.join(self.tmp, "planted"))
        r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "adapters", "hook.py"), "opencode"],
                           input=json.dumps(request).encode(), capture_output=True, env=env, cwd=self.root,
                           timeout=60)
        return r.returncode, r.stdout.decode(), r.stderr.decode(), home

    def test_it_blocks_a_rigged_commit_and_keeps_its_state_in_the_home_directory(self):
        self.write("tests/test_cart.py", SKIPPED)
        self.git("add", "-A")
        code, out, err, home = self.run_hook({"event": "shell", "command": "git commit -m green", "cwd": self.root,
                                              "session": "ses_1", "turn": ""})
        self.assertEqual((code, err), (0, ""))
        answer = json.loads(out)
        self.assertEqual(answer["action"], "block")
        self.assertIn("tests/test_cart.py:4", answer["message"])
        self.assertTrue(os.path.isdir(os.path.join(home, ".foreman")))

    def test_a_request_with_the_wrong_shape_is_an_error(self):
        code, out, err, _home = self.run_hook({"event": "shell", "cmd": "git commit -m x", "cwd": self.root})
        self.assertEqual((code, out), (1, ""))
        self.assertIn("command", err)

    def test_main_reads_one_request(self):
        stdout = io.StringIO()
        code = opencode.main(stdin=io.StringIO(json.dumps({"event": "shell", "command": "gh pr merge 1",
                                                           "cwd": self.root})), stdout=stdout)
        self.assertEqual((code, json.loads(stdout.getvalue())["action"]), (0, "block"))


def _runtime():
    """[program, flags…] that runs the plugin's TypeScript as it is, or None: bun, or a node that strips types."""
    if shutil.which("bun"):
        return [shutil.which("bun")]
    node = shutil.which("node")
    if not node:
        return None
    try:
        version = subprocess.run([node, "--version"], capture_output=True, timeout=10).stdout.decode()
        major, minor = (int(x) for x in version.strip().lstrip("v").split(".")[:2])
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if (major, minor) >= (23, 6):
        return [node, "--disable-warning=ExperimentalWarning"]
    if (major, minor) >= (22, 6):
        return [node, "--experimental-strip-types", "--disable-warning=ExperimentalWarning"]
    return None


RUNTIME = _runtime()


@unittest.skipUnless(RUNTIME, "needs bun, or node 22.6 or newer, to run the plugin's TypeScript")
class Plugin(OpenCodeCase):
    """The plugin with a stand-in for OpenCode's context (``tests/opencode_plugin.mjs``) and the real Python side.
    What OpenCode itself does with the plugin was seen in a real session (adapters/opencode/README.md)."""

    def drive(self, scenario, *args):
        home = os.path.join(self.tmp, "home")
        os.makedirs(home, exist_ok=True)
        env = dict(os.environ, HOME=home, USERPROFILE=home)
        r = subprocess.run(RUNTIME + [os.path.join(ROOT, "tests", "opencode_plugin.mjs"), self.root, scenario,
                                      *args], capture_output=True, env=env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        return json.loads(r.stdout.decode())

    def test_block_reaches_the_model_as_the_tools_error(self):
        out = self.drive("gate", "def test_total():", SKIP + "\ndef test_total():", SKIPPED)
        self.assertEqual(out["registered"], ["permission.evaluate", "session.experimental.idle", "session.prompt",
                                             "tool.execute.before"])
        self.assertFalse(out["merge"]["ok"])
        self.assertIn("Merging is the user's decision", out["merge"]["error"])
        self.assertTrue(out["ls"]["ok"])
        self.assertFalse(out["edit"]["ok"])
        self.assertIn("test-skipped", out["edit"]["error"])
        self.assertTrue(out["read"]["ok"])  # reading is never Foreman's to judge
        self.assertFalse(out["write"]["ok"])
        self.assertIn("test-skipped", out["write"]["error"])
        self.assertFalse(out["patch"]["ok"])  # the hunk after a file's own end line is still read
        self.assertIn("test-skipped", out["patch"]["error"])
        self.assertTrue(out["plainPatch"]["ok"])
        self.assertTrue(out["misspelt"]["ok"])  # Foreman's own failure does not hold the call up...
        self.assertFalse(out["misspeltIdle"]["ok"])  # ...and the person sees it when the run ends
        self.assertIn("Foreman could not run", out["misspeltIdle"]["error"])
        self.assertEqual(out["evaluated"]["effect"], "ask")  # a saved "always" never answers Foreman's question
        self.assertEqual(out["evaluated"]["message"], "why")

    def test_ask_goes_to_a_person_and_never_passes_without_one(self):
        out = self.drive("ask")
        self.assertFalse(out["unattended"]["ok"])
        self.assertIn("could not inspect", out["unattended"]["error"])
        self.assertFalse(out["automatic"]["ok"])
        self.assertIn("nobody is attending", out["automatic"]["error"])
        self.assertTrue(out["person"]["ok"])
        self.assertEqual([a["action"] for a in out["asked"]], ["foreman"] * 3)
        self.assertIn("could not inspect", out["asked"][0]["message"])
        self.assertTrue(out["idle"]["ok"])  # Foreman itself ran: nothing to show when the run ends

    def test_python_failing_on_a_gated_command_first_is_still_shown_once(self):
        out = self.drive("broken-git")
        self.assertFalse(out["commit"]["ok"])  # it went to the person, and nobody was there
        self.assertIn("Foreman could not run", out["commit"]["error"])
        self.assertEqual(out["asked"], 1)
        self.assertFalse(out["first"]["ok"])  # OpenCode's question does not show the text: the end of the run does
        self.assertIn("Foreman could not run", out["first"]["error"])
        self.assertTrue(out["second"]["ok"])

    def test_a_run_that_left_a_skipped_test_is_sent_back_once(self):
        out = self.drive("turn", "tests/test_cart.py", SKIPPED)
        self.assertTrue(out["shell"]["ok"])
        self.assertTrue(out["first"]["ok"])
        self.assertTrue(out["second"]["ok"])
        self.assertEqual(len(out["synthetic"]), 1)  # once: the Python side counts, the plugin adds no loop
        self.assertEqual(out["synthetic"][0]["sessionID"], "s1")
        self.assertIn("tests/test_cart.py:4", out["synthetic"][0]["text"])

    def test_a_message_the_person_sends_mid_run_keeps_the_runs_nudge(self):
        out = self.drive("steer", "tests/test_cart.py", SKIPPED)
        self.assertTrue(out["shell"]["ok"])
        self.assertEqual(len(out["synthetic"]), 1)
        self.assertIn("tests/test_cart.py:4", out["synthetic"][0]["text"])

    def test_the_directory_of_a_shell_call(self):
        out = self.drive("requests")
        self.assertEqual(out["relative"], os.path.join(self.root, "sub", "dir"))
        self.assertEqual(out["home"], os.path.join(self.tmp, "home", "work"))
        self.assertEqual(out["absolute"], os.path.join(self.tmp, "elsewhere"))
        self.assertEqual(out["none"], self.root)
        self.assertEqual(out["todo"], [])
        self.assertEqual([(r["event"], r["path"]) for r in out["mcp"]], [("write", "y.txt")])

    def test_a_run_that_only_talked_is_not_sent_back(self):
        self.write("tests/test_cart.py", SKIPPED)  # the person's own work
        out = self.drive("talk")
        self.assertTrue(out["first"]["ok"])
        self.assertEqual(out["synthetic"], [])

    def test_the_persons_command_runs_as_code_and_allow_needs_a_person(self):
        self.write("tests/test_cart.py", MARKED)
        self.git("add", "-A")
        out = self.drive("command")
        self.assertIn("(marked `%s`; id " % MARKER, out["commit"]["error"])
        self.assertIn("NEEDS YOUR OK", out["status"]["error"])
        self.assertIn("In OpenCode:", out["help"]["error"])
        self.assertIn("nobody is attending", out["refused"]["error"])
        self.assertIn("allowed " + out["id"], out["allowed"]["error"])
        self.assertEqual(out["asked"], 2)  # only `allow <id>` asks, once each time
        self.assertTrue(out["after"]["ok"])
        self.assertIn("Foreman board: repo", out["board"]["error"])  # `/foreman` alone is the board
        self.assertIn("repositories you can pin", out["use"]["error"])  # no dialog of options here: the list
        self.assertIn("pinned", out["pin"]["error"])
        self.assertEqual(out["askedAfterBoard"], 2)  # none of them asks through the permission prompt

    def test_the_review_command_waits_ten_minutes_and_carries_the_sessions_model(self):
        out = self.drive("review")
        self.assertEqual(out["shellDelay"], 30_000)      # every other request keeps the protocol's limit
        self.assertEqual(out["unknownDelay"], 600_000)   # a command may start a session of OpenCode and wait for it
        self.assertIn("does not tell Foreman which model wrote the code", out["unknownShown"])  # no model stated
        self.assertIn("It is the same model that wrote the code", out["sameShown"])             # `p/m` stated
        self.assertNotIn("only the effort differs", out["sameShown"])
        # a variant is part of the model name: `p/m#high` as the session's own and as the person's choice agree
        self.assertIn("same model", out["variantAgain"])
        self.assertEqual(out["modelOf"], ["a/b#max", "a/b", None, None, None])

    def test_the_variable_alone_switches_nothing_off_in_the_plugin(self):
        # Foreman stands down in hook.py, for the token of a review that is running; a project's configuration
        # can set the variable for every session, so the plugin does not read it.
        home = os.path.join(self.tmp, "home")
        os.makedirs(home, exist_ok=True)
        env = dict(os.environ, HOME=home, USERPROFILE=home, FOREMAN_REVIEWER="1")
        r = subprocess.run(RUNTIME + [os.path.join(ROOT, "tests", "opencode_plugin.mjs"), self.root, "reviewer-env"],
                           capture_output=True, env=env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        out = json.loads(r.stdout.decode())
        self.assertEqual(out["commands"], ["foreman"])
        self.assertIn("tool.execute.before", out["registered"])

    def test_when_python_cannot_answer_the_agent_keeps_working_and_git_goes_to_the_person(self):
        out = self.drive("broken")
        self.assertTrue(out["ls"]["ok"])
        self.assertTrue(out["write"]["ok"])
        self.assertFalse(out["first"]["ok"])  # shown once per session, when the run ends
        self.assertIn("Foreman could not run", out["first"]["error"])
        self.assertTrue(out["second"]["ok"])
        self.assertFalse(out["commit"]["ok"])  # nobody to approve it here
        self.assertEqual(len(out["asked"]), 1)
        self.assertIn("Foreman could not run", out["asked"][0])
        self.assertFalse(out["command"]["ok"])
        self.assertIn("Foreman could not run", out["command"]["error"])


class PluginFile(unittest.TestCase):
    def read(self, *parts):
        with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_the_plugin_imports_nothing_but_nodes_built_ins(self):
        text = self.read("adapters", "opencode", "foreman.ts")
        for line in text.splitlines():
            if line.startswith("import "):
                self.assertIn('from "node:', line)
        self.assertIn('id: "foreman"', text)
        self.assertIn('"opencode"]', text)  # it names its host to the entry point

    def test_its_quick_filter_is_the_gates(self):
        from foreman import gate
        text = self.read("adapters", "opencode", "foreman.ts")
        self.assertIn("/%s/i" % gate._QUICK_TOOL.pattern, text)
        self.assertIn("/%s/i" % gate._QUICK_VERB.pattern, text)

    def test_the_plugin_id_is_what_the_dialect_guards(self):
        self.assertIn('id: "%s"' % opencode.PLUGIN_ID, self.read("adapters", "opencode", "foreman.ts"))


if __name__ == "__main__":
    unittest.main()
