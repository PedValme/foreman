"""action.yml: Foreman as a GitHub Action.

The action is one script inside a YAML file. These tests read that file as text (the standard library has no YAML
reader), check how its inputs reach the script, and run the script itself with bash against real repositories.
CI runs the action for real too (`uses: ./`, the job "action" in .github/workflows/ci.yml).
"""
import os
import re
import shutil
import subprocess
import unittest

from tests_support import ROOT, GitRepoCase  # first: it puts plugin/ on sys.path
from foreman import detector

ACTION = os.path.join(ROOT, "action.yml")
SKIP = "@pytest.mark." + "skip"


def text() -> str:
    with open(ACTION, encoding="utf-8") as fh:
        return fh.read()


def inputs() -> list:
    """The names under `inputs:`."""
    block = text().split("\ninputs:\n", 1)[1].split("\nruns:\n", 1)[0]
    return re.findall(r"(?m)^  ([a-z][a-z-]*):$", block)


def environment() -> dict:
    """The step's `env:` as {NAME: expression}."""
    block = text().split("\n      env:\n", 1)[1].split("\n      run: |\n", 1)[0]
    return dict(re.findall(r"(?m)^        ([A-Z_]+): \$\{\{ (.+?) \}\}$", block))


def script() -> str:
    """The step's `run:` block, as bash gets it."""
    block = text().split("\n      run: |\n", 1)[1]
    lines = []
    for line in block.splitlines():
        if line.strip() and not line.startswith("        "):
            break
        lines.append(line[8:])
    return "\n".join(lines) + "\n"


class HowInputsReachTheScript(unittest.TestCase):
    def test_nothing_is_pasted_into_the_script(self):
        # An expression in the script would be shell once GitHub filled it in: a branch name could run a command.
        self.assertNotIn("${{", script())
        self.assertIn("exit 2", script())

    def test_every_input_is_declared_and_used(self):
        used = {m for expr in environment().values() for m in re.findall(r"inputs\.([a-z-]+)", expr)}
        self.assertEqual(sorted(used), sorted(inputs()))
        for name in environment():
            self.assertIn("$" + name, script(), name)

    def test_the_detector_is_loaded_isolated_from_the_actions_own_checkout(self):
        self.assertEqual(environment()["FOREMAN_HOME"], "github.action_path")
        self.assertIn('"$python" -I -c', script())
        self.assertNotIn("-m foreman", script())  # `python -m` puts the pull request's own folder first


class TheWorkflowToCopy(unittest.TestCase):
    """examples/foreman-check.yml runs the detector with `python -m`, which loads a folder named `foreman` from
    where it runs first: so it must run from Foreman's own download, and be told where the repository is."""

    def test_it_does_not_run_the_detector_from_the_checkout(self):
        with open(os.path.join(ROOT, "examples", "foreman-check.yml"), encoding="utf-8") as fh:
            lines = [line for line in fh.read().splitlines() if not line.lstrip().startswith("#")]
        step = "\n".join(lines).split("- name: Foreman\n", 1)[1]
        self.assertIn("working-directory: ${{ runner.temp }}/foreman/plugin", step)
        self.assertIn('run: python -m foreman.detector "origin/$BASE" HEAD --repo "$GITHUB_WORKSPACE"', step)
        self.assertNotIn("PYTHONPATH", step)


BASH = None if os.name == "nt" else shutil.which("bash")  # on Windows `bash` may be WSL's launcher, not Git's


@unittest.skipUnless(BASH, "needs bash (the action's own shell); on Windows the job `action` in CI runs it")
class TheScript(GitRepoCase):
    def setUp(self):
        super().setUp()
        self.write("app.py", "x = 1\n")
        self.write("tests/test_app.py", "def test_x():\n    assert True\n")
        self.commit("base")
        self.git("checkout", "-q", "-b", "feature")

    def run_action(self, **env):
        given = {"FOREMAN_HOME": ROOT, "FOREMAN_BASE": "main", "FOREMAN_BASE_REF": "", "FOREMAN_HEAD": "HEAD",
                 "FOREMAN_STRICT": "true", "FOREMAN_CHECK": "", "FOREMAN_SARIF": "", "FOREMAN_SARIF_THRESHOLD": "",
                 "FOREMAN_SARIF_SCOPE": "", "FOREMAN_REPO": "."}
        given.update(env)
        r = subprocess.run([BASH, "-c", script()], cwd=self.root, capture_output=True,
                           env=dict({k: v for k, v in os.environ.items() if k != "GITHUB_ACTIONS"}, **given))
        return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")

    def rig(self, marked=False):
        self.write("tests/test_app.py", SKIP + ("  # " + detector.MARKER if marked else "")
                   + "\ndef test_x():\n    assert True\n")
        self.commit("switch a test off")

    def test_a_clean_change_passes_and_a_rigged_one_fails(self):
        self.write("app.py", "x = 2\n")
        self.commit("a change")
        code, out = self.run_action()
        self.assertEqual((code, "CLEAN" in out), (0, True), out)
        self.rig()
        code, out = self.run_action()
        self.assertEqual(code, 1, out)
        self.assertIn("tests/test_app.py", out)

    def test_a_pull_request_cannot_bring_its_own_detector(self):
        # Found on 2026-11-25: run as `python -m foreman.detector` from the checkout, a folder named `foreman` in
        # the pull request was imported in the detector's place and answered CLEAN.
        self.rig()
        self.write("foreman/__init__.py", "")
        self.write("foreman/detector.py", "import sys\nprint('foreman: CLEAN')\nsys.exit(0)\n")
        self.write("sitecustomize.py", "import os\nos._exit(0)\n")
        self.commit("and a folder named foreman")
        # What this cannot cover: a step that ran the pull request's code before the action (a .pth file in
        # site-packages, BASH_ENV through GITHUB_ENV, a git or a python put first on the PATH). That is why Foreman
        # gets a job of its own (README.md, the fourth condition).
        for env in ({}, {"PYTHONPATH": self.root}, {"PYTHONHOME": self.root, "PYTHONPATH": self.root}):
            code, out = self.run_action(**env)
            self.assertEqual(code, 1, (env, out))
            self.assertIn("tests/test_app.py", out)

    def test_a_marked_finding_fails_unless_strict_is_turned_off(self):
        self.rig(marked=True)
        code, out = self.run_action()
        self.assertEqual(code, 1, out)
        code, out = self.run_action(FOREMAN_STRICT="false")
        self.assertEqual(code, 0, out)
        self.assertIn(detector.MARKER, out)
        code, out = self.run_action(FOREMAN_STRICT="yes")
        self.assertEqual(code, 2, out)

    def test_the_base_is_the_pull_requests_base_branch(self):
        self.rig()
        self.git("update-ref", "refs/remotes/origin/main", "main")
        code, out = self.run_action(FOREMAN_BASE="", FOREMAN_BASE_REF="main")
        self.assertEqual(code, 1, out)
        code, out = self.run_action(FOREMAN_BASE="", FOREMAN_BASE_REF="")
        self.assertEqual(code, 2, out)
        self.assertIn("nothing to compare with", out)
        code, out = self.run_action(FOREMAN_BASE="no-such-branch")
        self.assertEqual(code, 2, out)  # a check that could not run does not pass

    def test_a_branch_name_is_never_shell(self):
        marker = os.path.join(self.tmp, "ran")
        code, out = self.run_action(FOREMAN_BASE='main"; touch "%s"; echo "' % marker)
        self.assertEqual(code, 2, out)
        self.assertFalse(os.path.exists(marker))

    def test_the_other_inputs_reach_the_detector(self):
        self.write("app.py", "x = 3\n")
        self.commit("a change")
        code, out = self.run_action(FOREMAN_SARIF="\nmissing-one.sarif\r\nmissing-two.sarif\n")
        self.assertEqual(code, 2, out)
        self.assertIn("missing-one.sarif", out)
        self.assertIn("missing-two.sarif", out)
        self.assertNotIn("\r", out)
        code, out = self.run_action(FOREMAN_SARIF_THRESHOLD="nonsense")
        self.assertEqual(code, 2, out)
        self.write("scripts/check.sh", "python -m unittest\n")
        self.commit("the check")
        self.git("branch", "-f", "main", "HEAD")
        self.write("scripts/check.sh", "exit 0\n")
        self.commit("the check, emptied")
        code, out = self.run_action(FOREMAN_CHECK="bash scripts/check.sh")
        self.assertEqual(code, 1, out)
        self.assertIn("scripts/check.sh", out)
        outside = os.path.join(self.tmp, "elsewhere")
        os.makedirs(outside)
        r = subprocess.run([BASH, "-c", script()], cwd=outside, capture_output=True, env=dict(
            os.environ, FOREMAN_HOME=ROOT, FOREMAN_BASE="main", FOREMAN_BASE_REF="", FOREMAN_HEAD="HEAD",
            FOREMAN_STRICT="true", FOREMAN_CHECK="bash scripts/check.sh", FOREMAN_SARIF="",
            FOREMAN_SARIF_THRESHOLD="", FOREMAN_SARIF_SCOPE="", FOREMAN_REPO=self.root))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)  # `repo` says where the repository is
