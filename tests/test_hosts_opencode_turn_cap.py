"""OpenCode's plugin at the end of a turn, against a Python side that always sends the agent back: the plugin keeps
its own bound of three send-backs per run, and the request carries the session's model.

In a file of its own because the stand-in is a script on PATH named ``python3``, which only a POSIX system runs as a
program (tests/test_hosts_opencode.py drives the plugin against the real Python side everywhere)."""

import json
import os
import stat
import subprocess
import sys
import unittest

from tests_support import ROOT, GitRepoCase
from test_hosts_opencode import RUNTIME

STANDIN = """#!%s
import json, os, sys
request = json.loads(sys.stdin.read())
with open(os.environ["FOREMAN_TEST_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(request) + "\\n")
print(json.dumps({"action": "continue", "message": "go back"} if request.get("event") == "turn_end" else {}))
"""


@unittest.skipUnless(RUNTIME and os.name == "posix", "needs a POSIX system and bun or node 22.6+")
class TurnCap(GitRepoCase):
    def test_a_run_is_sent_back_at_most_three_times_and_the_end_carries_the_model(self):
        bin_dir = os.path.join(self.tmp, "bin")
        os.makedirs(bin_dir)
        fake = os.path.join(bin_dir, "python3")
        with open(fake, "w", encoding="utf-8") as fh:
            fh.write(STANDIN % sys.executable)
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR)
        log = os.path.join(self.tmp, "requests.jsonl")
        env = dict(os.environ, PATH=bin_dir + os.pathsep + os.environ.get("PATH", ""), FOREMAN_TEST_LOG=log,
                   HOME=self.tmp)
        r = subprocess.run(RUNTIME + [os.path.join(ROOT, "tests", "opencode_plugin.mjs"), self.root, "turn-cap", log],
                           capture_output=True, env=env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        out = json.loads(r.stdout.decode())
        self.assertEqual(out["synthetic"], 3)       # four ends of the same run, three send-backs
        self.assertEqual(out["afterNewRun"], 4)     # a new run is sent back again
        self.assertEqual(len(out["ends"]), 4)       # past the bound the Python side is not even asked
        self.assertEqual({e.get("model") for e in out["ends"]}, {"p/m#high"})


if __name__ == "__main__":
    unittest.main()
