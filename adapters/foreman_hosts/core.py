"""The host-neutral half of every adapter.

A harness tells its adapter five things: the agent is about to run a shell command, the agent is about to write a
file, a turn starts, a turn is about to end, and the person typed one of Foreman's commands. Each function here turns
one of them into the gate's own call (``foreman.gate``, the code the Hermes plugin runs) and the gate's answer into
one of four decisions: nothing (allow), ``block``, ``ask`` (a person must decide) or ``continue`` (send the agent
back before it finishes).

An adapter adds no rule and loosens none (PRODUCTO.md, rule 22). What it adds is what the gate gets from Hermes and
another harness does not give: which files the turn changed (the gate's end-of-turn scan needs them), words that fit
the harness, and a guard around Foreman's own program and state, which outside Hermes are plain files the agent's
shell can reach.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass
from typing import Callable, Optional

from foreman import detector, gate, grants
from foreman.detector import GitError, Repo

logger = logging.getLogger(__name__)

BLOCK, ASK, CONTINUE = "block", "ask", "continue"

TURN_BUDGET_SECONDS = 5.0       # the turn-start and end-of-turn bookkeeping, apart from the gate's own budget
SESSION_TTL_SECONDS = 7 * 24 * 3600
MAX_TOUCHED = 200
MAX_DIRTY_PASSED = 50           # the gate reads at most 50 changed paths


def _never(*_args) -> bool:
    return False


@dataclass(frozen=True)
class Host:
    """What differs from one harness to the next."""
    name: str                                    # "claude-code"
    label: str                                   # "Claude Code"
    person: Callable[[str], str]                 # how the person types a Foreman subcommand here: "/foreman:allow"
    program_dirs: tuple = ()                     # where Foreman is installed: not the agent's to run or edit
    cli: tuple = ()                              # the harness's own command names ("claude"): see _person_only
    switches_off: Callable[[str], bool] = _never        # a shell command that turns Foreman off in this harness
    config_off: Callable[[str, str], bool] = _never     # (path, new text): a write that turns Foreman off
    attended: Callable[[], bool] = _never        # a person is at this session (only then can a finding be allowed)


# ─── Words ───────────────────────────────────────────────────────────────────

_MERGE_HINT = re.compile(r"Ask them to run `/foreman merge ?([^`]*)`\.")
_SUBCOMMAND = re.compile(r"/foreman (allow|status|help)\b")
_PLAIN = (
    ("Re-run it with `workdir` set to the repository, or as", "Re-run it from the repository's directory, or as"),
    ("does not exist on the Hermes host (a remote terminal backend?)", "does not exist on this machine"),
    ("Foreman blocked this write_file:", "Foreman blocked this write:"),
    ("Foreman blocked this patch:", "Foreman blocked this edit:"),
)


def reword(host: Host, message: str) -> str:
    """The gate's message in this harness's words: the gate writes for Hermes (its ``workdir`` argument, its tool
    names, its ``/foreman`` command)."""
    def merge(m):
        target = m.group(1).strip()
        return ("Ask them to merge it themselves (for example `gh pr merge%s` in their own terminal)."
                % (" " + target if target else ""))
    text = _MERGE_HINT.sub(merge, message or "")
    for old, new in _PLAIN:
        text = text.replace(old, new)
    return _SUBCOMMAND.sub(lambda m: host.person(m.group(1)), text)


def _decision(host: Host, out) -> Optional[dict]:
    if not isinstance(out, dict):
        return None
    action, message = out.get("action"), reword(host, str(out.get("message") or ""))
    if action == "block":
        return {"action": BLOCK, "message": message}
    if action == "continue":
        return {"action": CONTINUE, "message": message}
    # "approve" is the gate asking for a person. Anything this adapter does not know is also the person's to
    # decide, never a silent pass.
    return {"action": ASK, "message": message or "Foreman needs a person to decide this call."}


# ─── Foreman's own program and state ─────────────────────────────────────────

_OWN = ("Foreman blocked this call: Foreman's own program and state (its hooks, its exceptions, its record of each "
        "session) are the user's, not the agent's. If Foreman is in the way, tell the user why.")
_OFF = ("Foreman blocked this call: turning Foreman off or changing its hooks is the user's decision. If Foreman is "
        "in the way, tell the user why.")
_PERSON_ONLY = ("Foreman blocked this command: allowing a finding is the user's decision, typed by them (%s). "
                "Ask them to review it.")

# `.foreman` as a whole path component: the state directory outside Hermes (~/.foreman), never `.foreman.json`.
_STATE_DIR = re.compile(r"(?:^|[\s\"'=:/\\~])\.foreman(?=$|[/\\\s\"'])")
_ALLOW_WORDS = re.compile(r"(?i)\bforeman\W{1,3}allow\b")


def _spellings(path: str) -> list:
    """How a directory may be written in a command: as given, resolved, and under ``~`` or ``$HOME``; lower case,
    forward slashes."""
    out = []
    home = os.path.expanduser("~")
    for p in dict.fromkeys((os.path.abspath(path), os.path.realpath(path))):
        low = p.replace("\\", "/").rstrip("/").lower()
        if len(low) < 4:
            continue
        out.append(low)
        for h in dict.fromkeys((home, os.path.realpath(home))):
            h = h.replace("\\", "/").rstrip("/").lower()
            if h and low.startswith(h + "/"):
                rest = low[len(h):]
                out += ["~" + rest, "$home" + rest, "${home}" + rest]
    return list(dict.fromkeys(out))


def _state_dir() -> Optional[str]:
    try:
        return grants.store_dir()
    except Exception:
        return None


def _names_own(host: Host, text: str) -> bool:
    """True when a command names Foreman's installation or its state directory."""
    low = (text or "").lower().replace("\\", "/")
    if _STATE_DIR.search(low):
        return True
    dirs = list(host.program_dirs)
    state = _state_dir()
    if state:
        dirs.append(state)
    return any(spelt in low for d in dirs for spelt in _spellings(d))


def _is_own_path(host: Host, path: str) -> bool:
    """True when a file the agent wants to write is inside Foreman's installation or its state directory."""
    dirs = [d for d in (*host.program_dirs, _state_dir()) if d]
    return any(gate._inside(path, gate._canon(d)) for d in dirs)


def _person_only(host: Host, command: str) -> bool:
    """The agent starting its own harness to type the person's command (`claude -p "/foreman:allow 3f2a"`). A
    command that only mentions the words (a commit message, a grep) is not one: each part of the line on its own
    needs the harness's command name too."""
    if not host.cli:
        return False
    names = re.compile(r"(?i)\b(?:%s)(?:\.exe)?\b" % "|".join(re.escape(n) for n in host.cli))
    for part in re.split(r"[;&|\n]+", command or ""):
        if names.search(part) and _ALLOW_WORDS.search(part):
            return True
    return False


def _guard_command(host: Host, command: str) -> Optional[dict]:
    if _names_own(host, command):
        return {"action": BLOCK, "message": _OWN}
    try:
        if host.switches_off(command):
            return {"action": BLOCK, "message": _OFF}
    except Exception:
        logger.warning("foreman: the host's switch-off check failed", exc_info=True)
    if _person_only(host, command):
        return {"action": BLOCK, "message": _PERSON_ONLY % host.person("allow <id>")}
    return None


# ─── Before a shell command ──────────────────────────────────────────────────

def pre_shell(host: Host, command, cwd: str = "", session: str = "") -> Optional[dict]:
    """Before the agent runs ``command`` in ``cwd``: the gate's decision, or None to let it run."""
    if not isinstance(command, str) or not command.strip():
        return None
    guard = _guard_command(host, command)
    if guard:
        return guard
    args = {"command": command}
    if isinstance(cwd, str) and cwd and os.path.isabs(cwd):
        args["workdir"] = cwd  # explicit: the gate then never guesses the session's directory
    out = gate.on_pre_tool_call("terminal", args, task_id=session or "", session_id=session or "")
    return _decision(host, out)


def looks_gated(command) -> bool:
    """True when ``command`` may be one the gate inspects (its own quick filter): what an adapter asks a person
    about when the inspection itself failed."""
    return isinstance(command, str) and bool(gate._quick(command))


# ─── Before a write ──────────────────────────────────────────────────────────

def pre_write(host: Host, path, cwd: str = "", session: str = "", turn: str = "", content=None, old=None,
              new=None, replace_all: bool = False) -> Optional[dict]:
    """Before the agent writes ``path``: a whole file (``content``) or a replacement (``old`` -> ``new``). With
    neither, only the guards run (a tool whose change this adapter cannot read)."""
    if not isinstance(path, str) or not path:
        return None
    full = os.path.normpath(path if os.path.isabs(path) else os.path.join(cwd or os.getcwd(), path))
    if _is_own_path(host, full):
        return {"action": BLOCK, "message": _OWN}
    text = content if isinstance(content, str) else new if isinstance(new, str) else ""
    try:
        if host.config_off(full, text):
            return {"action": BLOCK, "message": _OFF}
    except Exception:
        logger.warning("foreman: the host's config check failed", exc_info=True)
    if isinstance(content, str):
        out = gate.on_pre_tool_call("write_file", {"path": full, "content": content},
                                    task_id=session or "", session_id=session or "")
    elif isinstance(new, str):
        out = gate.on_pre_tool_call("patch", {"path": full, "old_string": old if isinstance(old, str) else "",
                                              "new_string": new, "replace_all": bool(replace_all)},
                                    task_id=session or "", session_id=session or "")
    else:
        out = gate.on_pre_tool_call("write_file", {"path": full}, task_id=session or "", session_id=session or "")
    decision = _decision(host, out)
    if decision is None or decision["action"] != BLOCK:
        _touch(host, session, turn, full)
    return decision


# ─── A session's turns ───────────────────────────────────────────────────────
# Hermes tells the gate which paths a turn changed; another harness does not. Two sources stand in for it: the
# files that went through pre_write, and whether the repository the turn started in looks different at its end
# (HEAD, and the size and time of every file git reports as changed), which also sees edits made from the shell.

def _session_file(host: Host, session: str, suffix: str) -> Optional[str]:
    state = _state_dir()
    if not state or not session:
        return None
    directory = os.path.join(state, "sessions")
    os.makedirs(directory, exist_ok=True)
    key = hashlib.sha256(("%s\0%s" % (host.name, session)).encode("utf-8", "replace")).hexdigest()[:24]
    return os.path.join(directory, key + suffix)


def _load(host: Host, session: str) -> dict:
    path = _session_file(host, session, ".json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _save(host: Host, session: str, data: dict) -> None:
    path = _session_file(host, session, ".json")
    if not path:
        return
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _touch(host: Host, session: str, turn: str, path: str) -> None:
    """Remember that this turn wrote ``path``: one appended line, so parallel tool calls cannot lose each other's."""
    target = _session_file(host, session, ".touched")
    if not target:
        return
    try:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(json.dumps([turn or "", path]) + "\n")
    except OSError:
        logger.warning("foreman: cannot record a changed file", exc_info=True)


def _touched(host: Host, session: str, turn: str) -> list:
    target = _session_file(host, session, ".touched")
    out = []
    try:
        with open(target, encoding="utf-8") as fh:
            for line in fh:
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if isinstance(item, list) and len(item) == 2 and item[0] == (turn or "") and isinstance(item[1], str):
                    out.append(item[1])
    except (OSError, TypeError):
        pass
    return list(dict.fromkeys(out))[:MAX_TOUCHED]


def _dirty(repo: Repo) -> list:
    """[(status code, absolute path)] of what git reports as changed or untracked in the working tree."""
    tokens = repo.git("status", "--porcelain=v1", "-z").split("\0")
    out, i = [], 0
    while i < len(tokens):
        token = tokens[i]
        i += 1
        if len(token) < 4:
            continue
        code, rel = token[:2], token[3:]
        if code[0] in "RC":
            i += 1  # a rename or copy: the path it came from follows
        out.append((code, os.path.join(repo.root, *rel.split("/"))))
    return out


def _signature(root: str, deadline: float) -> Optional[str]:
    """What the working tree looks like now, or None when git cannot tell (then nothing is concluded from it)."""
    try:
        repo = Repo(root, deadline=deadline)
        head = repo.try_git("rev-parse", "-q", "--verify", "HEAD") or ""
        entries = _dirty(repo)
    except GitError:
        return None
    digest = hashlib.sha256(head.encode("utf-8"))
    for code, path in sorted(entries):
        try:
            st = os.lstat(path)
            stamp = "%d:%d" % (st.st_size, st.st_mtime_ns)
        except OSError:
            stamp = "gone"
        digest.update(("\0%s\0%s\0%s" % (code, path, stamp)).encode("utf-8", "surrogateescape"))
    return digest.hexdigest()


def _prune_sessions() -> None:
    state = _state_dir()
    directory = os.path.join(state, "sessions") if state else None
    try:
        limit = time.time() - SESSION_TTL_SECONDS
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            if os.path.getmtime(path) < limit:
                os.unlink(path)
    except (OSError, TypeError):
        pass


def turn_start(host: Host, cwd: str = "", session: str = "", turn: str = "") -> None:
    """A turn starts: remember what the repository in ``cwd`` looks like, and forget the last turn's writes."""
    if not session:
        return
    deadline = time.monotonic() + TURN_BUDGET_SECONDS
    roots = {}
    try:
        root = detector.find_repo(cwd, deadline=deadline) if cwd and os.path.isdir(cwd) else None
        if root:
            roots[root] = _signature(root, deadline)
    except GitError:
        pass
    _save(host, session, {"turn": turn or "", "at": time.time(), "nudges": 0, "roots": roots})
    touched = _session_file(host, session, ".touched")
    try:
        os.unlink(touched)
    except (OSError, TypeError):
        pass
    _prune_sessions()


def end_of_turn(host: Host, cwd: str = "", session: str = "", turn: str = "") -> Optional[dict]:
    """The agent is about to finish: ``continue`` with what to undo when this turn left a blocker in the working
    tree, else None. One nudge per turn, the gate's own rule; a turn this adapter did not see start is left alone."""
    if not session:
        return None
    state = _load(host, session)
    if not state or (turn and state.get("turn") != turn):
        return None
    turn = turn or str(state.get("turn") or "")
    changed = _touched(host, session, turn)
    deadline = time.monotonic() + TURN_BUDGET_SECONDS
    roots = state.get("roots") if isinstance(state.get("roots"), dict) else {}
    for root, before in roots.items():
        if not isinstance(before, str) or not os.path.isdir(root):
            continue
        now = _signature(root, deadline)
        if now is None or now == before:
            continue
        try:
            changed += [path for _code, path in _dirty(Repo(root, deadline=deadline))][:MAX_DIRTY_PASSED]
        except GitError:
            pass
    nudges = state.get("nudges") if isinstance(state.get("nudges"), int) else 0
    out = gate.on_pre_verify(coding=bool(changed), attempt=nudges, changed_paths=changed, session_id=session)
    if isinstance(out, dict) and out.get("action") == "continue":
        state["nudges"] = nudges + 1
        _save(host, session, state)
        return {"action": CONTINUE, "message": reword(host, str(out.get("message") or ""))}
    return None


# ─── The person's commands ───────────────────────────────────────────────────

_PERSON_COMMAND = re.compile(r"^\s*/foreman(?:[:\s]\s*(.*))?$", re.S | re.I)
PERSON_SUBCOMMANDS = {
    "status": "[path]  this repository's verdict (CLEAN, BLOCKED, INCOMPLETE, NEEDS YOUR OK)",
    "allow": "[id]  list findings the agent marked, or allow one of them (you only)",
    "help": "this help",
}


def person_command(host: Host, text, cwd: str = "", session: str = "") -> Optional[str]:
    """What Foreman answers to a command the person typed (``/foreman:status``, ``/foreman allow 3f2a``), or None
    when ``text`` is not one of Foreman's commands. Only the harness's own "the user typed this" event may reach it:
    the model cannot type."""
    m = _PERSON_COMMAND.match(text) if isinstance(text, str) else None
    if not m:
        return None
    parts = (m.group(1) or "").strip().split(None, 1)
    name = parts[0].lower() if parts else "status"
    rest = parts[1].strip() if len(parts) > 1 else ""
    try:
        return reword(host, _run_person(host, name, rest, cwd))
    except Exception as e:  # the person asked: always an answer, never a stack trace
        logger.warning("foreman: the person's command failed", exc_info=True)
        return "Foreman failed: %s: %s" % (type(e).__name__, e)


def _run_person(host: Host, name: str, rest: str, cwd: str) -> str:
    from foreman import commands  # late: it loads the board, the review and the notifications
    if name == "status":
        where = os.path.expanduser(rest) if rest else cwd
        if where and not os.path.isabs(where):
            where = os.path.join(cwd or os.getcwd(), where)
        return commands.cmd_status(os.path.normpath(where) if where else "")
    if name == "allow":
        if rest and not host.attended():
            return ("Foreman: allowing a finding needs a person at the session, and nobody is attending this one. "
                    "Type `%s` in an interactive %s session." % (host.person("allow " + rest.split()[0]), host.label))
        return commands.cmd_allow(rest)
    if name == "help":
        return _help(host)
    if name in commands.SUBCOMMANDS:
        return ("Foreman: `%s` is not available in %s yet. Here Foreman is the gate (it blocks a rigged commit, "
                "push or pull request, and an agent-run merge) plus `%s` and `%s`."
                % (name, host.label, host.person("status"), host.person("allow")))
    return "Unknown subcommand `%s`.\n\n%s" % (name, _help(host))


def _help(host: Host) -> str:
    from foreman import verdicts
    from foreman.detector import MARKER
    lines = ["Foreman: a green check the agent did not rig.", "", "In %s:" % host.label]
    lines += ["  %-18s %s" % (host.person(name), doc) for name, doc in PERSON_SUBCOMMANDS.items()]
    lines += ["", "Verdicts:", verdicts.table(), "",
              "Foreman blocks git commit, git push and gh pr create when the change skips, deletes or moves tests, "
              "edits or weakens what the check runs, bypasses hooks or carries a secret; an agent-run gh pr merge is "
              "always blocked (merging is yours).",
              "A false positive is marked on its line with `%s` (or, for a file, a commit-message line `%s <path>: "
              "<reason>`). The mark never passes alone: it waits until you run `%s`."
              % (MARKER, MARKER, host.person("allow <id>"))]
    return "\n".join(lines)
