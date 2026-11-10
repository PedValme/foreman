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
        from foreman import grants
        self._old_store = grants.STORE_DIR_OVERRIDE
        grants.STORE_DIR_OVERRIDE = os.path.join(self.tmp, "store")

    def tearDown(self):
        from foreman import grants
        grants.STORE_DIR_OVERRIDE = self._old_store
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args, cwd=None, env=None):
        r = subprocess.run(["git", *args], cwd=cwd or self.root, capture_output=True,
                           env=dict(os.environ, **env) if env else None)
        if r.returncode:
            raise AssertionError("git %s failed: %s" % (" ".join(args), r.stderr.decode("utf-8", "replace")))
        return r.stdout.decode("utf-8", "replace")

    def write(self, rel, text):
        path = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return path

    EPOCH = 1_700_000_000  # commits get fixed dates, so no test depends on the real clock

    def commit(self, message, when=None):
        """Commit everything. ``when`` is the commit's time in epoch seconds; by default each commit is 10 s after
        the previous one, starting at EPOCH."""
        self._commits = getattr(self, "_commits", 0) + 1
        stamp = "@%d +0000" % (when if when is not None else self.EPOCH + 10 * self._commits)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message, env={"GIT_COMMITTER_DATE": stamp, "GIT_AUTHOR_DATE": stamp})
