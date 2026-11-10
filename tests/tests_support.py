"""Temporary git repositories for the tests (stdlib only)."""
import os
import shutil
import subprocess
import tempfile
import unittest


class GitRepoCase(unittest.TestCase):
    """Each test gets a fresh repository on branch main, isolated from the user's git hooks and signing."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="foreman-test-")
        self.root = os.path.join(self.tmp, "repo")
        os.makedirs(self.root)
        hooks = os.path.join(self.tmp, "no-hooks")
        os.makedirs(hooks)
        self.git("init", "-q")
        self.git("symbolic-ref", "HEAD", "refs/heads/main")
        for key, value in (("user.name", "Foreman Test"), ("user.email", "test@example.invalid"),
                           ("commit.gpgsign", "false"), ("core.hooksPath", hooks), ("core.autocrlf", "false")):
            self.git("config", key, value)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args, cwd=None):
        r = subprocess.run(["git", *args], cwd=cwd or self.root, capture_output=True)
        if r.returncode:
            raise AssertionError("git %s failed: %s" % (" ".join(args), r.stderr.decode("utf-8", "replace")))
        return r.stdout.decode("utf-8", "replace")

    def write(self, rel, text):
        path = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return path

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
