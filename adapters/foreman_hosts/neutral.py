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

Answer (always one JSON object)::

    {}                                            go on
    {"action": "block", "message": "..."}         refuse the call; the model must read the message
    {"action": "ask", "message": "..."}           a person must decide; with nobody to ask, refuse with the message
    {"action": "continue", "message": "..."}      (turn_end) send the agent back with the message, once
    {"reply": "..."}                              (command) show it to the person

What every extension must get right, so the harnesses behave alike:

- **The request's shape is checked.** A ``shell`` without a string ``command``, a ``patch`` without a string
  ``patch``, a ``write`` without a string ``path`` (or whose ``content``, ``old`` or ``new`` is given and is not a
  string) is an error, not a pass: a misspelt key must never switch the gate off quietly.
- **``session`` is required for the end-of-turn nudge**: it identifies the conversation, and without it
  ``turn_start`` and ``turn_end`` do nothing. ``turn`` identifies one run of the agent inside it; send ``""`` when
  the harness has no such id.
- **``command`` only from the person.** It is sent from the harness's own "the person typed /foreman" handler and
  from nowhere else: never from a tool the model can call, never from a command the harness implements as a prompt
  the model then runs. A harness with no handler that runs without the model does not send ``command`` at all
  (allowing a finding then stays out of that harness).
- **``attended``** is ``true`` only when a person is at the harness's interface right now; anything else, a missing
  key or the string ``"true"`` included, is "nobody" (``attended()`` below). Only then can a finding be allowed.
- **``ask``**: show the message through the harness's own question to the person only when someone is attending;
  otherwise refuse the call with the message. Never let it through unanswered.
- **When this program cannot answer** (exit code other than 0, nothing or no JSON on standard output, or no answer
  within 30 seconds; the gate's own budget is 18): the extension goes on as the harness does after any failed hook
  and shows the error text to the person once per session. It never turns that into a silent pass of a call it
  knows the gate inspects without the person seeing the error.
- **Where Foreman is**: the extension runs ``hook.py`` by the absolute path of its own installation (next to the
  extension's file), never a path taken from the agent's working directory.
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
                                  replace_all=bool(request.get("replace_all")))
    elif event == "patch":
        decision = core.pre_patch(host, _required(request, "patch"), cwd, session, turn)
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
