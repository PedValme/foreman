"""`/foreman use` when one repository is reachable under two spellings: through a link here, and on Windows also
under a folder's short name (`RUNNER~1`, how CI found it). It is offered once, and remembered once."""
import os
import shutil
import tempfile
import unittest

from tests_support import GitRepoCase  # first: it puts plugin/ on sys.path
from foreman import board, gate

KEYS = ("session-1",)


def _can_link() -> bool:
    """Whether this user may create a link to a directory here (Windows refuses without the privilege)."""
    where = tempfile.mkdtemp(prefix="foreman-link-")
    try:
        os.mkdir(os.path.join(where, "real"))
        os.symlink(os.path.join(where, "real"), os.path.join(where, "link"), target_is_directory=True)
        return os.path.isdir(os.path.join(where, "link"))
    except (OSError, NotImplementedError, AttributeError):
        return False
    finally:
        shutil.rmtree(where, ignore_errors=True)


class Session:
    """The part of Hermes's context `/foreman use` reads: the session's directory, and nobody to ask."""

    def __init__(self, cwd):
        self.cwd = cwd

    def session_cwd(self):
        return self.cwd


def canon(path):
    return os.path.normcase(os.path.realpath(path))


@unittest.skipUnless(_can_link(), "needs a file system where this user can link to a directory")
class OneRepositoryUnderTwoSpellings(GitRepoCase):
    def setUp(self):
        super().setUp()
        self.write("app.py", "x = 1\n")
        self.commit("base")
        self.elsewhere = tempfile.mkdtemp(prefix="foreman-test-link-")
        self.link = os.path.join(self.elsewhere, "projects")  # the folder that holds the repository, by another name
        os.symlink(self.tmp, self.link, target_is_directory=True)
        self._old = (board._CTX, gate._CTX)
        session = Session(self.link)
        board.bind(session)
        gate.bind(session)

    def tearDown(self):
        board._CTX, gate._CTX = self._old
        shutil.rmtree(self.elsewhere, ignore_errors=True)
        super().tearDown()

    def offered(self):
        return [root for root, _why in board.candidates(KEYS, platform="telegram")]

    def test_it_is_offered_once(self):
        board.pin(self.root, ("an-earlier-session",))  # a recent repository, spelt as it was pinned
        roots = self.offered()
        self.assertEqual([canon(r) for r in roots].count(canon(self.root)), 1, roots)
        self.assertEqual(len(roots), len({canon(r) for r in roots}), roots)

    def test_it_is_remembered_once(self):
        through_the_link = os.path.join(self.link, "repo")
        board.pin(self.root, KEYS)
        board.pin(through_the_link, KEYS)
        board.remember(self.root)
        self.assertEqual([canon(r) for r in board.recent()], [canon(self.root)])
        self.assertEqual(board.recent(), [self.root])  # as it was named last

    def test_the_list_marks_it_as_pinned_whatever_its_spelling(self):
        board.pin(os.path.join(self.link, "repo"), KEYS)
        out = board.cmd_use("", KEYS, "telegram")
        self.assertEqual(out.count("<- pinned now"), 1, out)


if __name__ == "__main__":
    unittest.main()
