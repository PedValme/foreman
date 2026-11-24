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
    {"event": "turn_end",   "cwd": "...", "session": "...", "turn": "..."}
    {"event": "command",    "args": "allow 3f2a", "cwd": "...", "attended": true}

``session`` identifies the conversation and ``turn`` one run of the agent inside it (empty when the harness has no
such id). ``command`` is sent only from the harness's own "the person typed /foreman" handler, never from a tool the
model can call; ``attended`` says a person is at the harness's interface (only then can a finding be allowed).

Answer (always one JSON object)::

    {}                                            go on
    {"action": "block", "message": "..."}         refuse the call; the model must read the message
    {"action": "ask", "message": "..."}           a person must decide; with nobody to ask, refuse with the message
    {"action": "continue", "message": "..."}      (turn_end) send the agent back with the message, once
    {"reply": "..."}                              (command) show it to the person
"""
from __future__ import annotations

import json
import sys
from typing import Callable, Optional

from . import core

EVENTS = ("shell", "write", "patch", "turn_start", "turn_end", "command")


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def answer(host: core.Host, request: dict) -> dict:
    """The answer to one request. Raises ValueError for an event this protocol does not have."""
    event = request.get("event")
    cwd, session, turn = _text(request.get("cwd")), _text(request.get("session")), _text(request.get("turn"))
    if event == "shell":
        decision = core.pre_shell(host, request.get("command"), cwd, session, turn)
    elif event == "write":
        content, new = request.get("content"), request.get("new")
        decision = core.pre_write(host, request.get("path"), cwd, session, turn,
                                  content=content if isinstance(content, str) else None,
                                  old=_text(request.get("old")), new=new if isinstance(new, str) else None,
                                  replace_all=bool(request.get("replace_all")))
    elif event == "patch":
        decision = core.pre_patch(host, request.get("patch"), cwd, session, turn)
    elif event == "turn_start":
        core.turn_start(host, cwd, session, turn)
        decision = None
    elif event == "turn_end":
        decision = core.end_of_turn(host, cwd, session, turn)
    elif event == "command":
        return {"reply": core.person_reply(host, request.get("args"), cwd)}
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
