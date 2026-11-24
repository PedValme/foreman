"""The board outside Hermes: ``plugin/foreman/board.py`` as it is, on a stand-in for Hermes's plugin context.

In Hermes the board keeps the context the plugin was registered with and asks it for a question to the person
(``ask_choice``: which repository, confirm a merge) and, through the gate, for the session's directory. Another
harness has no such context, and Foreman's program there answers one request and ends. So this module gives the
board the part of that context it uses, for the length of one command:

- **The session's directory** is the one the harness's extension sent with the command.
- **A question** cannot be asked from here: this program has no interface. The stand-in raises ``core.Asking`` with
  the question; the harness's extension shows it in its own dialog and sends the same command again with the
  answer, and this time the stand-in hands that answer to the board. An answer counts only for the very question
  the board asks on that second run (its id is a digest of the question and its options): if the pull request moved
  in between, the question is another one and is asked again. With nobody attending nothing is asked, and the board
  says what to type instead.
- **The pinned repository** (``use``) is kept per conversation, under the session id the extension sends.

Everything the board prints is its own text, put into the harness's words by ``core.reword``.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
from typing import Optional

from foreman import board, gate

from . import core

# The board's subcommands as this module can run them, with the line each gets in the harness's help.
DOCS = {
    "board": "the branch, its verdict, open pull requests and the issues they close (the default)",
    "verdict": "[pr|branch] [--repo r]  the verdict of a pull request or a branch, with reasons",
    "pipeline": "[pr|branch] [--repo r]  a change's stages: gate, review, bounces, you, merge",
    "prs": "open pull requests: head, CI, the issues each one closes",
    "issues": "open issues and the pull request that closes each",
    "use": "[path|n]  pin the repository for this session",
}
MAX_OPTIONS = 20
_DISMISSED = "cancel"  # the option a dismissed dialog counts as, where the question has it


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")


def _plain(text: str) -> str:
    """One line of a dialog: a directory's name or a pull request's title is somebody else's text, and a control
    character in it (an escape sequence) must not redraw what the person is choosing between."""
    return " ".join(_CONTROL.sub(" ", text).split())


def question_id(question: str, values: list) -> str:
    """A name for one question: the same text with the same options, and nothing else, gives the same name."""
    return hashlib.sha256(json.dumps([question, values]).encode("utf-8")).hexdigest()[:24]


class _Context:
    """The part of Hermes's plugin context the board and the gate use."""

    def __init__(self, host: core.Host, cwd: str, answer: Optional[dict]):
        self.host, self.cwd = host, cwd
        self.answer = answer if isinstance(answer, dict) else {}

    def session_cwd(self) -> str:
        # Spelt as the system spells this program's own directory (the extension starts it there), so that one
        # directory reached through a link is one candidate and not two.
        return os.path.realpath(self.cwd) if self.cwd and os.path.isdir(self.cwd) else ""

    def ask_choice(self, question: str, choices: list) -> Optional[str]:
        """The value the person picked, when this run of the command carries their answer to this same question;
        None with nobody to ask; else ``core.Asking``, for the harness's extension to ask."""
        if not self.host.attended():
            return None
        options = []
        for choice in (choices or [])[:MAX_OPTIONS]:
            if isinstance(choice, dict) and isinstance(choice.get("value"), str) and choice["value"]:
                label = _plain(str(choice.get("label") or choice["value"]))
                detail = _plain(str(choice.get("description") or ""))
                options.append({"value": choice["value"], "label": "%s — %s" % (label, detail) if detail else label})
        if not options:
            return None
        values = [o["value"] for o in options]
        asked = question_id(str(question), values)
        if self.answer.get("id") == asked:
            picked = self.answer.get("value")
            if isinstance(picked, str) and picked in values:
                return picked
            return _DISMISSED if _DISMISSED in values else None  # the dialog was closed without a choice
        shown = "\n".join(_plain(line) for line in core.reword(self.host, str(question)).split("\n"))
        raise core.Asking({"id": asked, "question": shown, "options": options})


@contextlib.contextmanager
def _bound(ctx: _Context):
    """The board and the gate on this context for one command; what they had before comes back after it (a test
    process runs many, and Hermes's own binding is never this module's to keep)."""
    before = (board._CTX, gate._CTX)
    board.bind(ctx)
    gate.bind(ctx)
    try:
        yield
    finally:
        board._CTX, gate._CTX = before


def _keys(session: str) -> tuple:
    return (session,) if isinstance(session, str) and session else ()


def pinned(session: str) -> Optional[str]:
    """The repository the person pinned for this conversation with ``use``, or None."""
    return board.pinned(_keys(session))


def run(host: core.Host, name: str, rest: str, cwd: str, session: str = "", answer: Optional[dict] = None) -> str:
    """One of the board's subcommands (or ``status``, which reads the pinned repository first), run by the board
    itself. Raises ``core.Asking`` when it needs the person to pick something."""
    if name != "status" and name not in host.board:
        return "Foreman: `%s` is not available in %s yet." % (name, host.label)
    command = board.SUBCOMMANDS[name][0]
    with _bound(_Context(host, cwd, answer)):
        return command(rest, _keys(session), None)
