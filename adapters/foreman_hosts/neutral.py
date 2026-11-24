"""The protocol for harnesses whose extensions run inside the harness (pi, OpenCode).

Such a harness has no command hook that speaks JSON: its extension is code. Foreman's extension there is kept as
thin as the harness allows: for each thing the harness tells it, it runs ``python3 -I adapters/hook.py <host>`` with
one request on standard input and does what the one answer on standard output says. All of Foreman's judgment stays
in Python, where it is tested.

Request (a JSON object; ``event`` decides which other keys are read)::

    {"event": "shell",      "command": "...", "cwd": "...", "session": "...", "turn": "..."}
    {"event": "write",      "path": "...", "content": "...", ...}                 a whole file
    {"event": "write",      "path": "...", "old": "...", "new": "...", "replace_all": false, ...}   a replacement
    {"event": "write",      "path": "...", ...}                                   a change the extension cannot read
    {"event": "patch",      "patch": "*** Begin Patch ...", ...}
    {"event": "turn_start", "cwd": "...", "session": "...", "turn": "..."}
    {"event": "turn_end",   "cwd": "...", "session": "...", "turn": "...",
                            "model": "...", "effort": "..."}       the session's own, when the harness knows them
    {"event": "command",   "args": "allow 3f2a", "cwd": "...", "session": "...", "attended": true,
                            "model": "...", "effort": "...",       the session's own, when the harness knows them
                            "answer": {"id": "...", "value": "..."}}   only when answering a question (below)

Answer (always one JSON object)::

    {}                                            go on
    {"action": "block", "message": "..."}         refuse the call; the model must read the message
    {"action": "ask", "message": "..."}           a person must decide; with nobody to ask, refuse with the message
    {"action": "continue", "message": "..."}      (turn_end) send the agent back with the message
    {"reply": "..."}                              (command) show it to the person
    {"question": {"id": "...", "question": "...", "options": [{"value": "...", "label": "..."}]}}
                                                  (command) the person picks one option; then the command again

What every extension must get right, so the harnesses behave alike:

- **The request's shape is checked.** A ``shell`` without a string ``command``, a ``patch`` without a string
  ``patch``, a ``write`` without a string ``path`` (or whose ``content``, ``old`` or ``new`` is given and is not a
  string) is an error, not a pass: a misspelt key must never switch the gate off quietly. ``replace_all`` and
  ``attended`` are the JSON booleans; the string ``"true"`` is not one.
- **``session`` is required for the end-of-turn nudge**: it identifies the conversation, and without it
  ``turn_start`` and ``turn_end`` do nothing. ``turn`` identifies one run of the agent inside it; send ``""`` when
  the harness has no such id.
- **The end of a turn can take minutes, and can send the agent back more than once.** This program counts: once
  for what the gate finds, and, where the person turned on the review at the end of every turn (``reviewer
  every-turn on``), once more for each review that sends the change back, three in all at most. That review starts
  a session of the harness and waits for it, so a ``turn_end`` gets a command's time, not thirty seconds, and
  carries the session's ``model`` and ``effort`` like a command. The extension keeps its own bound too: it sends
  one run back at most three times, whatever this program answers.
- **``command`` only from the person.** It is sent from the harness's own "the person typed /foreman" handler and
  from nowhere else: never from a tool the model can call, never from a command the harness implements as a prompt
  the model then runs. A harness with no handler that runs without the model does not send ``command`` at all
  (allowing a finding then stays out of that harness).
- **``attended``** is ``true`` only when a person is at the harness's interface right now; anything else, a missing
  key or the string ``"true"`` included, is "nobody" (``attended()`` below). Only then can a finding be allowed.
- **``ask``**: show the message through the harness's own question to the person only when someone is attending;
  otherwise refuse the call with the message. Never let it through unanswered.
- **``question``** (the answer to a ``command`` that needs the person to choose: which repository, confirm a merge):
  this program answers one request and ends, so it cannot wait for a person. The extension shows the question and
  its options' labels in the harness's own dialog, from the command's handler and nowhere else, and sends the same
  ``command`` request again with ``answer``: the question's ``id`` and the ``value`` of the option picked, or JSON
  ``null`` as the value when the person closed the dialog without picking. It never answers by itself, never passes
  the question to the model, and asks at most three questions for one command (the question can change between the
  two runs, when what it is about changed; then it is asked again). A ``question`` arrives only when the request
  said ``attended``; an extension that gets one with nobody there shows its text and sends nothing more.
- **When this program cannot answer** (exit code other than 0, nothing or no JSON on standard output, or no answer
  within 30 seconds; the gate's own budget is 18): Foreman's own fault must not stop the agent from working, and
  must not open the gate quietly either. A shell command that names git or gh together with commit, push or pr
  (the gate's own quick filter, ``core.looks_gated``: the one check an extension repeats on its side) goes to the
  person as an ``ask`` would, refused with nobody attending; every other call runs. The error text is shown to
  the person once per session.
- **Where Foreman is**: the extension runs ``hook.py`` by the absolute path of its own installation (next to the
  extension's file), never a path taken from the agent's working directory.
- **The review** (``command`` with ``review`` or ``reviewer``) starts a session of the harness and waits for it:
  the extension gives a ``command`` request ten minutes, not thirty seconds, and twelve where the command can
  merge (the review's seven and three for gh, with room: this program must never be stopped while gh may still be
  merging, or the person reads a failure for a merge that happened). It sends the session's ``model`` and
  ``effort`` as the harness names them, or leaves them out when it does not know them (``session()`` below): they
  only decide what the review says about its own reviewer and its default effort. Inside the reviewer's own
  session the extension behaves as in any other and every request is answered ``{}``: this program knows that
  session by the token of the review that is running. The extension never reads ``FOREMAN_REVIEWER`` itself: the
  variable alone proves nothing, because a project's configuration can set one for every session.
"""
from __future__ import annotations

import json
import sys
from typing import Callable, Optional

from . import core

EVENTS = ("shell", "write", "patch", "turn_start", "turn_end", "command")


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def attended(request: dict) -> bool:
    """A person is at the harness's interface: the request says so with the JSON value ``true`` and nothing else."""
    return isinstance(request, dict) and request.get("attended") is True


def session(request: dict) -> core.Session:
    """The model and effort of the session that sent the request, as the extension stated them; "" for what it did
    not state or stated as something other than a string."""
    request = request if isinstance(request, dict) else {}
    return core.Session(model=_text(request.get("model")).strip(), effort=_text(request.get("effort")).strip())


def _required(request: dict, key: str) -> str:
    value = request.get(key)
    if not isinstance(value, str):
        raise ValueError("a %r request needs %r as a string" % (request.get("event"), key))
    return value


def _optional(request: dict, key: str) -> Optional[str]:
    value = request.get(key)
    if value is not None and not isinstance(value, str):
        raise ValueError("%r, when given, is a string" % key)
    return value


def _answer(request: dict) -> Optional[dict]:
    """The person's answer to a question, as the extension sent it back: {"id", "value"}, where ``value`` is the
    option picked or None for a dialog closed without picking. Anything shaped otherwise is an error."""
    given = request.get("answer")
    if given is None:
        return None
    if not isinstance(given, dict) or not isinstance(given.get("id"), str) \
            or not (given.get("value") is None or isinstance(given.get("value"), str)):
        raise ValueError("'answer', when given, is {\"id\": a string, \"value\": a string or null}")
    return {"id": given["id"], "value": given.get("value")}


def answer(host: core.Host, request: dict) -> dict:
    """The answer to one request. Raises ValueError for an event this protocol does not have and for a request
    that is not shaped as the protocol says."""
    event = request.get("event")
    cwd, session, turn = _text(request.get("cwd")), _text(request.get("session")), _text(request.get("turn"))
    if event == "shell":
        decision = core.pre_shell(host, _required(request, "command"), cwd, session, turn)
    elif event == "write":
        path = _required(request, "path")
        if not path.strip():
            raise ValueError("a 'write' request needs a path")
        decision = core.pre_write(host, path, cwd, session, turn, content=_optional(request, "content"),
                                  old=_optional(request, "old") or "", new=_optional(request, "new"),
                                  replace_all=request.get("replace_all") is True)
    elif event == "patch":
        decision = core.pre_patch(host, _required(request, "patch"), cwd, session, turn)
    elif event == "turn_start":
        core.turn_start(host, cwd, session, turn)
        decision = None
    elif event == "turn_end":
        decision = core.end_of_turn(host, cwd, session, turn)
    elif event == "command":
        try:
            return {"reply": core.person_reply(host, request.get("args"), cwd, session, _answer(request))}
        except core.Asking as asking:
            return {"question": asking.question}
    else:
        raise ValueError("unknown event %r (known: %s)" % (event, ", ".join(EVENTS)))
    return dict(decision) if decision else {}


def _failed(request, error: Exception) -> Optional[dict]:
    """The adapter itself failed. A command the gate would have inspected goes to the person; nothing else is
    held up by Foreman's own fault."""
    if isinstance(request, dict) and request.get("event") == "shell" and core.looks_gated(request.get("command")):
        return {"action": core.ASK, "message": "Foreman could not inspect this command: %s: %s. Approve only if you "
                                               "have checked the change yourself." % (type(error).__name__, error)}
    return None


def main(make_host: Callable[[dict], core.Host], stdin=None, stdout=None) -> int:
    """Read one request, write one answer. ``make_host(request)`` builds the harness's ``core.Host`` (the request
    carries ``attended``). Exit code 1, with nothing on standard output, when no answer could be given."""
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    raw = stdin.buffer.read() if hasattr(stdin, "buffer") else stdin.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig", "replace")
    try:
        request = json.loads(raw.lstrip("﻿") or "null")
    except ValueError:
        request = None
    if not isinstance(request, dict):
        sys.stderr.write("Foreman: the request is not a JSON object.\n")
        return 1
    try:
        out = answer(make_host(request), request)
    except Exception as e:  # never a stack trace instead of a decision
        sys.stderr.write("Foreman: %s: %s\n" % (type(e).__name__, e))
        out = _failed(request, e)
        if out is None:
            return 1
    stdout.write(json.dumps(out))
    return 0
