"""The host-neutral half of every adapter.

A harness tells its adapter five things: the agent is about to run a shell command, the agent is about to write a
file, a turn starts, a turn is about to end, and the person typed one of Foreman's commands. Each function here turns
one of them into the gate's own call (``foreman.gate``, the code the Hermes plugin runs) and the gate's answer into
one of four decisions: nothing (allow), ``block``, ``ask`` (a person must decide) or ``continue`` (send the agent
back before it finishes).

An adapter adds no gate rule and loosens none (PRODUCTO.md, rule 22). What it adds is what the gate gets from Hermes and
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

from .hosts import MODULES

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
    is_config: Callable[[str], bool] = _never           # a path that is one of the harness's settings files
    config_off: Callable[[str, str], bool] = _never     # (its text before, after): the write turns Foreman off
    # An interactive session, as opposed to an unattended one. It tells the two apart and no more: the agent's own
    # shell inherits it, so what keeps the agent from the person's commands is the guard below, not this.
    attended: Callable[[], bool] = _never


HOSTS = tuple(MODULES)  # what `adapters/hook.py <host>` accepts


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


def programs(command: str, _depth: int = 0) -> list:
    """[(program name, its words)] for each simple command of a line, as the gate's own tokenizer reads it: wrappers
    (`sudo`, `env`…) and leading `VAR=value` skipped, and the script handed to a shell or a runner (`bash -c "…"`,
    `eval "…"`) read as a line of its own. So `claude` is the program of `claude -p x`, and not of a grep, a path
    or a commit message that only contains the word."""
    out = []
    for words in gate.segments(command or ""):
        words = list(words)
        for _ in range(8):  # `FOO=1 sudo -u me env BAR=2 claude …`: assignments and wrappers in any order
            if words and gate._ASSIGNMENT.match(words[0]):
                words = words[1:]
            elif len(words) > 1 and gate._prog(words[0]) in gate._WRAPPERS:
                words = gate._skip_wrapper(words)
            else:
                break
        if not words:
            continue
        prog = gate._prog(words[0])
        out.append((prog, words))
        packaged = _packaged(prog, words)
        if packaged:
            out.append(packaged)
        if _depth < 3 and prog in (gate._SHELLS | gate._POWERSHELLS | gate._RUNNERS):
            for word in words[1:]:
                if re.search(r"\s", word):
                    out += programs(word, _depth + 1)
            rest = [w for w in words[1:]]
            while rest and rest[0].startswith("-"):  # `pwsh -Command claude -p …`: the script given unquoted
                rest = rest[1:]
            if len(rest) > 1:
                out += programs(" ".join(gate._requote(w) for w in rest), _depth + 1)
    return out


_PACKAGE_RUNNERS = {"npx", "bunx", "pnpx"}
_PACKAGE_MANAGERS = {"npm": {"exec", "x"}, "pnpm": {"dlx", "exec"}, "yarn": {"dlx", "exec"}, "bun": {"x"}}


def _packaged(prog: str, words: list) -> Optional[tuple]:
    """`npx @anthropic-ai/claude-code -p …`, `pnpm dlx …`, `npm exec -- claude …`: the program is the package the
    launcher runs, named without its scope and version (`claude-code`)."""
    rest = words[1:]
    if prog in _PACKAGE_MANAGERS:
        while rest and rest[0].startswith("-"):
            rest = rest[1:]
        if not rest or rest[0].lower() not in _PACKAGE_MANAGERS[prog]:
            return None
        rest = rest[1:]
    elif prog not in _PACKAGE_RUNNERS:
        return None
    while rest and rest[0].startswith("-"):
        rest = rest[1:]
    if not rest:
        return None
    name = rest[0].replace("\\", "/").rsplit("/", 1)[-1].lower().split("@", 1)[0]
    return (name, rest) if name else None


def only_reads(prog: str, words: list) -> bool:
    """True for a program that only prints (`cat`, `grep`, `jq`…) with no redirection to a file and no in-place
    edit: reading a settings file is ordinary work."""
    if prog not in gate._READERS and prog not in ("ls", "stat", "file", "wc", "bat"):
        return False
    _clean, writes = gate._strip_redirs(words)
    return not writes and not any(w.startswith("-i") or w == "--in-place" for w in words[1:])


def _person_only(host: Host, command: str) -> bool:
    """The agent starting its own harness to type the person's command (`claude -p "/foreman:allow 3f2a"`, or the
    words piped into it). The harness must be a program that runs in the line: a commit message or a grep that only
    mentions the words is not one."""
    if not host.cli or not _ALLOW_WORDS.search(command or ""):
        return False
    return any(prog in host.cli for prog, _words in programs(command))


_PYTHON = re.compile(r"^(?:python[\d.]*|pypy[\d.]*|py|hook\.py)$")


def _runs_entry(command: str) -> bool:
    """The adapters' entry point run by hand, wherever it is named from (`cd <plugin> && python3 adapters/hook.py
    claude-code`): the way to hand Foreman a made-up "the person typed this". Naming the file (`git add
    adapters/hook.py`) is not running it."""
    for prog, words in programs(command):
        text = " ".join(words)
        if _PYTHON.match(prog) and re.search(r"\bhook\.py\b", text) and any(
                re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(h), text) for h in HOSTS):
            return True
    return False


def _guard_command(host: Host, command: str) -> Optional[dict]:
    if _names_own(host, command) or _runs_entry(command):
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

def pre_shell(host: Host, command, cwd: str = "", session: str = "", turn: str = "") -> Optional[dict]:
    """Before the agent runs ``command`` in ``cwd``: the gate's decision, or None to let it run."""
    if not isinstance(command, str) or not command.strip():
        return None
    guard = _guard_command(host, command)
    if guard:
        return guard
    _note_shell(host, cwd, session, turn)
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

_MAX_CONFIG_BYTES = 2 * 1024 * 1024


def _config_write_off(host: Host, full: str, content, old, new, replace_all) -> bool:
    """True when this write would leave one of the harness's settings files switching Foreman off and the file does
    not do so already (what the person set there themselves stays theirs). The file is judged as it will be, not
    by the replaced fragment alone: `true` -> `false` says nothing on its own."""
    try:
        if not host.is_config(full):
            return False
        before = ""
        try:
            if os.path.getsize(full) <= _MAX_CONFIG_BYTES:
                with open(full, encoding="utf-8", errors="replace") as fh:
                    before = fh.read()
        except OSError:
            pass
        if isinstance(content, str):
            after = content
        elif isinstance(new, str):
            old = old if isinstance(old, str) else ""
            after = before.replace(old, new, -1 if replace_all else 1) if old and old in before else new
        else:
            return False
        return bool(host.config_off(before, after))
    except Exception:
        logger.warning("foreman: the host's config check failed", exc_info=True)
        return False


def pre_write(host: Host, path, cwd: str = "", session: str = "", turn: str = "", content=None, old=None,
              new=None, replace_all: bool = False) -> Optional[dict]:
    """Before the agent writes ``path``: a whole file (``content``) or a replacement (``old`` -> ``new``). With
    neither, only the guards run (a tool whose change this adapter cannot read)."""
    if not isinstance(path, str) or not path:
        return None
    full = os.path.normpath(path if os.path.isabs(path) else os.path.join(cwd or os.getcwd(), path))
    if _is_own_path(host, full):
        return {"action": BLOCK, "message": _OWN}
    if _config_write_off(host, full, content, old, new, replace_all):
        return {"action": BLOCK, "message": _OFF}
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


_PATCH_PATHS = re.compile(r"(?m)^\*\*\* (?:(?:Update|Add|Delete) File|Move to):\s*(.+?)\s*$")


def pre_patch(host: Host, patch, cwd: str = "", session: str = "", turn: str = "") -> Optional[dict]:
    """Before the agent applies a patch in the ``*** Begin Patch`` format (the one the gate already reads for
    Hermes's patch tool, and the one Codex's ``apply_patch`` sends): every file it names meets the guards, then
    the gate reads the patch."""
    if not isinstance(patch, str) or not patch.strip():
        return None
    base = cwd if isinstance(cwd, str) and cwd and os.path.isabs(cwd) else os.getcwd()

    def full(path: str) -> str:
        path = os.path.expanduser(path)
        return os.path.normpath(path if os.path.isabs(path) else os.path.join(base, path))

    paths = list(dict.fromkeys(full(p) for p in _PATCH_PATHS.findall(patch)))
    if any(_is_own_path(host, p) for p in paths):
        return {"action": BLOCK, "message": _OWN}
    for path, old, new, _is_new in gate._v4a_files(patch):
        try:
            if host.is_config(full(path)) and host.config_off(old, new):
                return {"action": BLOCK, "message": _OFF}
        except Exception:
            logger.warning("foreman: the host's config check failed", exc_info=True)
    # The gate resolves a patch's relative paths against the session's directory, which outside Hermes it takes
    # from the process: stand in it while the gate reads.
    here = None
    try:
        here = os.getcwd()
    except OSError:
        pass
    try:
        if os.path.isdir(base):
            os.chdir(base)
        out = gate.on_pre_tool_call("patch", {"mode": "patch", "patch": patch},
                                    task_id=session or "", session_id=session or "")
    finally:
        if here:
            try:
                os.chdir(here)
            except OSError:
                pass
    decision = _decision(host, out)
    if decision is None or decision["action"] != BLOCK:
        for path in paths:
            _touch(host, session, turn, path)
    return decision


# ─── A session's turns ───────────────────────────────────────────────────────
# Hermes tells the gate which paths a turn changed; another harness does not. Two sources stand in for it: the
# files that went through pre_write and exist changed since the turn began, and, when the agent used the shell,
# whether the repository it ran in looks different at the end (HEAD, and the size and time of every file git
# reports as changed) from how it looked before the turn's first command there. A turn that only talked is
# therefore never sent back, and a prompt costs no git call.

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


def _new_turn(turn: str) -> dict:
    return {"turn": turn or "", "at": time.time(), "nudges": 0, "roots": {}, "cwds": {}}


def turn_start(host: Host, cwd: str = "", session: str = "", turn: str = "") -> None:
    """A turn starts: forget the last one's writes and nudges. No git call: this runs on every prompt."""
    if not session:
        return
    _save(host, session, _new_turn(turn))
    touched = _session_file(host, session, ".touched")
    try:
        os.unlink(touched)
    except (OSError, TypeError):
        pass
    _prune_sessions()


def _note_shell(host: Host, cwd: str, session: str, turn: str) -> None:
    """The agent is about to run a shell command in ``cwd``: the first time this turn it does so in a repository,
    remember how that repository looks now, before the command. Later commands there cost one small file read."""
    if not session or not isinstance(cwd, str) or not cwd:
        return
    try:
        state = _load(host, session)
        if not state or state.get("turn") != (turn or ""):
            state = _new_turn(turn)  # a turn whose start this adapter did not see
        cwds = state["cwds"] if isinstance(state.get("cwds"), dict) else {}
        roots = state["roots"] if isinstance(state.get("roots"), dict) else {}
        if cwd in cwds:
            return
        deadline = time.monotonic() + TURN_BUDGET_SECONDS
        root = (detector.find_repo(cwd, deadline=deadline) if os.path.isdir(cwd) else None) or ""
        signed = _signature(root, deadline) if root and root not in roots else None
        latest = _load(host, session)  # another call of this turn may have written meanwhile: keep what it noted
        if latest.get("turn") == state["turn"]:
            for key, mine in (("cwds", cwds), ("roots", roots)):
                theirs = latest.get(key) if isinstance(latest.get(key), dict) else {}
                for k, v in theirs.items():
                    mine.setdefault(k, v)
            state["nudges"] = latest.get("nudges", state.get("nudges", 0))
        cwds[cwd] = root
        if root and root not in roots:
            roots[root] = signed
        state["cwds"], state["roots"] = cwds, roots
        _save(host, session, state)
    except Exception:  # bookkeeping for the end-of-turn nudge: never in the way of the gate itself
        logger.warning("foreman: cannot note the shell's repository", exc_info=True)


def _written_since(paths: list, since) -> list:
    """The remembered writes that happened: the file exists and changed after the turn began. A write the person
    refused at the harness's prompt was remembered too, and left the file as it was."""
    if not isinstance(since, (int, float)):
        return paths
    out = []
    for path in paths:
        try:
            if os.path.getmtime(path) >= since - 2:
                out.append(path)
        except OSError:
            pass
    return out


def end_of_turn(host: Host, cwd: str = "", session: str = "", turn: str = "") -> Optional[dict]:
    """The agent is about to finish: ``continue`` with what to undo when this turn left a blocker in the working
    tree, else None. One nudge per turn, the gate's own rule; a turn this adapter did not see start is left alone."""
    if not session:
        return None
    state = _load(host, session)
    if turn and state.get("turn") != turn:
        state = dict(_new_turn(turn), at=None)  # its start was not seen: only this turn's own writes can count
    elif not state:
        return None
    turn = turn or str(state.get("turn") or "")
    changed = _written_since(_touched(host, session, turn), state.get("at"))
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
    spaced = not re.match(r"^\s*/foreman:", text, re.I)
    if spaced and parts and name not in PERSON_SUBCOMMANDS and name not in _hermes_subcommands():
        return None  # "/foreman is blocking my commit, why?" is a question for the model, not a command
    return person_reply(host, m.group(1) or "", cwd)


def person_reply(host: Host, args, cwd: str = "") -> str:
    """Foreman's answer to its command with these arguments (``"status src"``, ``"allow 3f2a"``, ``""`` for the
    verdict), for a harness whose own command mechanism already established that the person typed ``/foreman``."""
    parts = (args if isinstance(args, str) else "").strip().split(None, 1)
    name = parts[0].lower() if parts else "status"
    rest = parts[1].strip() if len(parts) > 1 else ""
    try:
        return reword(host, _run_person(host, name, rest, cwd))
    except Exception as e:  # the person asked: always an answer, never a stack trace
        logger.warning("foreman: the person's command failed", exc_info=True)
        return "Foreman failed: %s: %s" % (type(e).__name__, e)


def _hermes_subcommands() -> set:
    try:
        from foreman import commands
        return set(commands.SUBCOMMANDS)
    except Exception:
        return set()


def _run_person(host: Host, name: str, rest: str, cwd: str) -> str:
    from foreman import commands  # late: it loads the board, the review and the notifications
    if name == "status":
        where = os.path.expanduser(rest) if rest else cwd
        if not where or not (os.path.isabs(where) or cwd):
            return "Foreman: this session has no working directory. Give a path: `%s <path>`." % host.person("status")
        if not os.path.isabs(where):
            where = os.path.join(cwd, where)
        return commands.cmd_status(os.path.normpath(where))
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
