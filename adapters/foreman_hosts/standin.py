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
- **Hermes's terminal tool**, which the board uses for the three commands that write to GitHub (``gh pr merge``,
  ``gh pr comment``, ``gh pr close``), is Foreman's own ``gh`` process here: no shell, gh's own login, and only for
  those three. In Hermes that tool sits behind Hermes's approval; here what stands in its place is that ``merge``
  and ``reject`` run only for a command the person typed with someone attending (PRODUCTO.md, rule 24), and that a
  merge is confirmed in the harness's dialog. The agent's own ``gh pr merge`` stays refused by the gate.
- **The review before a merge** is the board's own step (rule 16), with this harness's reviewer: a fresh session
  that did not write the code (``reviewer.py``). The board's two sentences about "the second model" are Hermes's;
  here they say who really reviewed, in the words every review in this harness uses (rule 25).

Everything the board prints is its own text, put into the harness's words by ``core.reword``.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shlex
import subprocess
from typing import Optional

from foreman import board, gate, review

from . import core, reviewer

# The board's subcommands as this module can run them, with the line each gets in the harness's help.
DOCS = {
    "board": "the branch, its verdict, open pull requests and the issues they close (the default)",
    "verdict": "[pr|branch] [--repo r]  the verdict of a pull request or a branch, with reasons",
    "pipeline": "[pr|branch] [--repo r]  a change's stages: gate, review, bounces, you, merge",
    "prs": "open pull requests: head, CI, the issues each one closes",
    "issues": "open issues and the pull request that closes each",
    "use": "[path|n]  pin the repository for this session",
    "merge": "<pr> [--merge|--rebase] [--repo r]  if CLEAN and ready: the review first, then you confirm",
    "reject": "<pr> [--close] [--repo r] [note]  post the reasons on the pull request",
}
# What Foreman's own gh may be started for: the board's three writes, and nothing else it might be handed.
GH_WRITES = (("pr", "merge"), ("pr", "comment"), ("pr", "close"))
FOOTER = "<sub>Posted with `/foreman reject` from Hermes Agent.</sub>"  # the board's, at the end of its comment
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

    def dispatch_tool(self, name: str, args: dict, **_hermes_only) -> dict:
        """Hermes's terminal tool as the board calls it: ``gh pr merge``, ``gh pr comment`` or ``gh pr close``, run
        as Foreman's own gh process (the board's runner: no shell, gh's own login). Anything else is not run."""
        args = args if isinstance(args, dict) else {}
        try:
            argv = shlex.split(str(args.get("command") or "")) if name == "terminal" else []
        except ValueError:
            argv = []
        if not self.host.attended():
            return {"status": "denied", "error": "nobody is attending this session"}
        if argv[:1] != ["gh"] or tuple(argv[1:3]) not in GH_WRITES:
            return {"status": "denied", "error": "it is not one of Foreman's own GitHub commands"}
        runner = board.GH_RUNNER or board._default_runner
        try:
            seconds = float(args.get("timeout") or board.MERGE_TIMEOUT)
        except (TypeError, ValueError):
            seconds = float(board.MERGE_TIMEOUT)
        try:
            code, out, err = runner(argv[1:], str(args.get("workdir") or self.cwd), seconds)
        except FileNotFoundError:
            return {"exit_code": 127, "output": "gh (the GitHub CLI) is not installed"}
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "output": ""}
        except OSError as e:
            return {"exit_code": 126, "output": "cannot run gh: %s" % e}
        return {"exit_code": code, "output": "\n".join(t.strip() for t in (out, err) if t and t.strip())}


def _merge_review(host: core.Host, p: reviewer.Plan, original):
    """The board's review before a merge (``board._review_for_merge``), in this harness. The step is the board's:
    this runs it, with the record finished as every review here is (its findings on one line each, who reviewed
    kept with it), and then replaces the sentences in which the board names its reviewer in Hermes's words."""
    def run(root, number, v, keys, platform):
        seen = []
        inner = review.run_review

        def run_review(*args, **kwargs):
            record = inner(*args, **kwargs)
            reviewer.finish(host, p, record)
            seen.append(record)
            return record

        review.run_review = run_review
        try:
            out = original(root, number, v, keys, platform)
        finally:
            review.run_review = inner
        record = seen[-1] if seen else {}
        out["notes"] = [n for n in out.get("notes") or [] if n.strip() not in reviewer.HERMES_NOTES]
        if out.get("pre"):  # the board's one line naming "the second model" and how Hermes routed it
            head = str(v.get("head_oid") or "")[:7]
            verdict = record.get("verdict")
            if record.get("error"):  # it could not run, or there was nothing to review: nobody reviewed
                first = "The review of PR #%d at %s: %s." % (number, head, verdict)
            elif record.get("cached"):
                first = ("Review of PR #%d at %s: %s (the stored review of this exact diff, %s; the reviewer was not "
                         "started again)." % (number, head, verdict, record.get("time") or "earlier"))
            else:
                first = "Foreman reviewed PR #%d at %s before the merge: %s." % (number, head, verdict)
            # who reviewed, only when a reviewer's session answered for this diff
            said = reviewer.who(host, p, record) if isinstance(record.get("model"), dict) \
                and not record.get("error") else []
            out["pre"] = [board.wrap(first)] + said + out["pre"][1:]
        return out
    return run


def _comment(host: core.Host, original):
    """The comment ``reject`` posts (``board.reject_comment``), signed with this harness's name instead of Hermes's."""
    def run(*args, **kwargs):
        return original(*args, **kwargs).replace(FOOTER, FOOTER.replace("Hermes Agent", host.label))
    return run


@contextlib.contextmanager
def _bound(host: core.Host, ctx: _Context):
    """The board, the gate and the review on this harness for one command; what they had before comes back after
    it (a test process runs many, and Hermes's own binding is never this module's to keep)."""
    before = (board._CTX, gate._CTX, review._CTX, board._review_for_merge, board.reject_comment)
    try:
        board.bind(ctx)
        gate.bind(ctx)
        board.reject_comment = _comment(host, before[4])
        if host.fresh_session is not None:
            # The review reads its reviewer from its context: the one `/foreman review` uses here, so a pull
            # request reviewed with it is not sent to a model again at merge time.
            p = reviewer.plan(host)
            review.bind(reviewer.context(host, p))
            board._review_for_merge = _merge_review(host, p, before[3])
        yield
    finally:
        board._CTX, gate._CTX, review._CTX, board._review_for_merge, board.reject_comment = before


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
    if name in core.BOARD_WRITES and not host.attended():
        # Rule 24: with nobody attending they do nothing, whatever the command says (`--yes` included).
        number = next((w.lstrip("#") for w in rest.split() if w.lstrip("#").isdigit()), "<pr>")
        return ("Foreman: `%s` writes to GitHub as you, so it needs you at the session, and nobody is attending "
                "this one. Type `%s` in an interactive %s session. `%s` shows its verdict from anywhere."
                % (name, host.person("%s %s" % (name, number)), host.label, host.person("verdict %s" % number)))
    if name == "merge" and host.fresh_session is None:
        return "Foreman: `merge` is not available in %s yet: it has no reviewer here." % host.label
    command = board.SUBCOMMANDS[name][0]
    with _bound(host, _Context(host, cwd, answer)):
        return command(rest, _keys(session), None)
