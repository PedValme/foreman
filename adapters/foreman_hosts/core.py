"""The host-neutral half of every adapter.

A harness tells its adapter five things: the agent is about to run a shell command, the agent is about to write a
file, a turn starts, a turn is about to end, and the person typed one of Foreman's commands. Each function here turns
one of them into the gate's own call (``foreman.gate``, the code the Hermes plugin runs) and the gate's answer into
one of four decisions: nothing (allow), ``block``, ``ask`` (a person must decide) or ``continue`` (send the agent
back before it finishes).

An adapter adds no gate rule and loosens none (docs/rules.md, rule 22). What it adds is what the gate gets from Hermes and
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
class Session:
    """What a harness says about the session that asked for a review; "" where it does not say."""
    model: str = ""    # the model writing the code
    effort: str = ""   # its effort level, one of the harness's own names


@dataclass(frozen=True)
class Answer:
    """What a fresh session of the harness gave back: the object the schema asked for, when it gave one."""
    parsed: Optional[dict] = None
    text: str = ""
    model: str = ""      # the model that answered, as the harness names it
    provider: str = ""


def _no_session() -> Session:
    return Session()


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
    # The reviewer (reviewer.py): a fresh session of this same harness, started without tools.
    # fresh_session(system prompt, prompt, JSON schema, model, effort, seconds) -> Answer; it raises RuntimeError
    # with the reason when the session could not answer. None: this harness has no reviewer yet.
    fresh_session: Optional[Callable[..., "Answer"]] = None
    efforts: tuple = ()                              # the harness's effort levels, lowest first; () when it has none
    session: Callable[[], Session] = _no_session     # the model and effort of the session that asked
    # One sentence every review in this harness carries under its "Reviewer:" line: what its reviewer's session can
    # still do or see that the others' cannot (a limit the harness leaves no way to close). "" when there is none.
    reviewer_caveat: str = ""
    # The board's subcommands this harness answers (standin.py): "board", "verdict", "use"… () when it has none.
    # Only a harness whose own command mechanism runs Foreman's command with no model turn lists any.
    board: tuple = ()
    # The harness's end-of-turn hook waits long enough for a review (minutes): only then can the person turn on
    # the review at the end of every turn. Where it does not, that review would be started and cut off each turn:
    # a session paid for and never read.
    turn_review: bool = False
    # Where the person goes to type a command that needs them there, as the end of "Type `…` in …" (no final full
    # stop). "" says "an interactive <label> session" (attend_here).
    attended_where: str = ""


def attend_here(host: "Host") -> str:
    """Where a command that needs a person attending can be typed in this harness."""
    return host.attended_where or "an interactive %s session" % host.label


class Asking(BaseException):
    """A command needs the person to pick one of a few options, and this program cannot ask: it answers one request
    and ends. The harness's extension asks through its own dialog and sends the command again with the answer
    (``neutral.py``). ``question`` is {"id", "question", "options": [{"value", "label"}]}.

    Not an ``Exception``: the board reads any exception from its question as "nobody answered", and this is neither
    a failure nor an answer."""

    def __init__(self, question: dict):
        super().__init__(question.get("question", ""))
        self.question = question


HOSTS = tuple(MODULES)  # what `adapters/hook.py <host>` accepts
# The board's subcommands that write nothing outside Foreman's own record (`use` keeps the pinned repository).
BOARD_READS = ("board", "verdict", "pipeline", "prs", "issues", "use")
# The two that write to GitHub, as the person: only with someone attending, and never typed by the agent.
BOARD_WRITES = ("merge", "reject")
REVIEWER_ENV = "FOREMAN_REVIEWER"  # in the reviewer's own session: the token of the review running (reviewer_session)


# ─── Words ───────────────────────────────────────────────────────────────────

_MERGE_HINT = re.compile(r"Ask them to run `/foreman merge ?([^`]*)`\.")
_SUBCOMMAND = re.compile(r"/foreman (allow|status|help|reviewer|review)\b")
_PLAIN = (
    ("Re-run it with `workdir` set to the repository, or as", "Re-run it from the repository's directory, or as"),
    ("does not exist on the Hermes host (a remote terminal backend?)", "does not exist on this machine"),
    ("Foreman blocked this write_file:", "Foreman blocked this write:"),
    ("Foreman blocked this patch:", "Foreman blocked this edit:"),
    ("Foreman: Hermes's approval denied", "Foreman did not run"),  # the board, when its own gh was not started
    # The review at the end of a turn: in Hermes the agent calls a tool for it; here Foreman runs it itself.
    ("Foreman reviews the new diff (call `foreman_review`).", "Foreman reviews the new diff."),
    ("(run `foreman_review` to see them)", "(the user's `/foreman review` shows them)"),
)
# In Hermes the review is "the second-model review". Here the reviewer is a fresh session that, with nothing chosen,
# runs on the model that wrote the code: the review never names itself a second model (rule 25). A line the core
# folded between the two words is read too.
_SECOND_MODEL = re.compile(r"\b([Ss])econd-model\s+review")


def reword(host: Host, message: str) -> str:
    """The gate's message in this harness's words: the gate writes for Hermes (its ``workdir`` argument, its tool
    names, its ``/foreman`` command, its second model)."""
    def merge(m):
        target = m.group(1).strip()
        if "merge" in host.board:  # this harness has the person's own merge command
            return "Ask them to run `%s`." % host.person("merge" + (" " + target if target else ""))
        return ("Ask them to merge it themselves (for example `gh pr merge%s` in their own terminal)."
                % (" " + target if target else ""))
    text = _MERGE_HINT.sub(merge, message or "")
    for old, new in _PLAIN:
        text = text.replace(old, new)
    text = _SECOND_MODEL.sub(lambda m: "Review" if m.group(1) == "S" else "review", text)
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
_PERSON_WRITES = ("Foreman blocked this command: merging or rejecting a pull request with Foreman is the user's "
                  "decision, typed by them (%s). Tell them what you found instead.")

# `.foreman` as a whole path component: the state directory outside Hermes (~/.foreman), never `.foreman.json`.
_STATE_DIR = re.compile(r"(?:^|[\s\"'=:/\\~])\.foreman(?=$|[/\\\s\"'])")
_ALLOW_WORDS = re.compile(r"(?i)\bforeman\W{1,3}allow\b")
_WRITE_WORDS = re.compile(r"(?i)\bforeman\W{1,3}(?:%s)\b" % "|".join(BOARD_WRITES))
_EACH_TURN_WORDS = re.compile(r"(?i)\bforeman\W{1,3}reviewer\W{1,3}every-turn\b")
_PERSON_WHEN = ("Foreman blocked this command: whether Foreman reviews at the end of every turn is the user's "
                "decision, typed by them (%s). If the review is in the way, tell the user why.")


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


class MovedHome:
    """A harness's home moved by an environment variable (``CLAUDE_CONFIG_DIR``, ``CODEX_HOME``): its settings files
    and plugins folder there, which the guards that know only ``~/.claude`` and ``~/.codex`` would not see. Empty
    (nothing matches) when the variable is unset, or relative: the harness resolves that from where it started,
    which a hook cannot know, and guarding the wrong folder would refuse a project's own files."""

    _CD = ("cd", "pushd", "chdir", "set-location", "sl")

    def __init__(self, env, var: Optional[str], files: tuple, path: str = ""):
        home = path or (env or {}).get(var or "") or ""
        self.files = ()
        self.text = self.home = self.bare = None
        home = os.path.expanduser(home.strip())
        if not home or not os.path.isabs(home):
            return
        self.files = tuple(os.path.normcase(os.path.realpath(os.path.join(home, f))) for f in files)
        spellings = {home.replace("\\", "/")}
        user = os.path.expanduser("~").replace("\\", "/")
        if user and home.replace("\\", "/").startswith(user + "/"):
            spellings.add("~" + home.replace("\\", "/")[len(user):])
        refs = [re.escape(s.rstrip("/")).replace("/", r"[/\\]+") for s in spellings if s.strip("/")]
        if var:
            refs += [r"\$\{?%s\}?" % var, r"%%%s%%" % var, r"\$env:%s" % var]
        names = "|".join(re.escape(f) for f in files) + "|plugins"
        refs, edge = "|".join(refs), r"(?![\w.\-])"
        # the home as a path of its own, not inside another (`/repo/opt/moved/…` is not `/opt/moved`)
        self.text = re.compile(r"(?i)(?<![\w.\-])(?:%s)[/\\]+(?:%s)%s" % (refs, names, edge))
        self.home = re.compile(r"(?i)^[\"']?(?:%s)[/\\]*[\"']?$" % refs)
        self.bare = re.compile(r"(?i)(?<![\w.\-/\\])(?:%s)%s" % (names, edge))

    def is_file(self, path: str) -> bool:
        """``path`` is one of the moved home's settings files."""
        if not self.files or not path:
            return False
        try:
            return os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(path)))) in self.files
        except (OSError, ValueError):
            return False

    def named_in(self, text: str) -> bool:
        """``text`` (one simple command) names one of those files or the plugins folder."""
        return bool(self.text and self.text.search(text or ""))

    def entered(self, command: str) -> bool:
        """``command`` moves into the home (`cd "$CODEX_HOME" && …`), after which a bare file name is one of its."""
        if not self.home:
            return False
        return any(prog in self._CD and any(self.home.match(w) for w in words[1:])
                   for prog, words in programs(command or ""))

    def names_bare(self, text: str) -> bool:
        """``text`` names one of the settings files or the plugins folder by its name alone (`sed … config.toml`)."""
        return bool(self.bare and self.bare.search(text or ""))


def _person_only(host: Host, command: str, words=_ALLOW_WORDS) -> bool:
    """The agent starting its own harness to type the person's command (`claude -p "/foreman:allow 3f2a"`, or the
    words piped into it; with ``_WRITE_WORDS``, `pi "/foreman merge 7"`). The harness must be a program that runs
    in the line: a commit message or a grep that only mentions the words is not one."""
    if not host.cli or not words.search(command or ""):
        return False
    return any(prog in host.cli for prog, _words in programs(command))


_PYTHON = re.compile(r"^(?:python[\d.]*|pypy[\d.]*|py|hook\.py)$")


def _without_redirections(words: list) -> list:
    """The words the program really receives: output redirections (the gate's own reading) and input ones
    (`< file`, `<file`, `<<< text`) removed with their targets."""
    words = [w for i, w in enumerate(words)  # the descriptor number of `2>file` is its own word to the tokenizer
             if not (w.isdigit() and i + 1 < len(words) and isinstance(words[i + 1], gate._Redir))]
    words, _writes = gate._strip_redirs(words)
    out, i = [], 0
    while i < len(words):
        word = words[i]
        if not isinstance(word, gate._Op) and re.match(r"^\d*<{1,3}$", word):
            i += 2
            continue
        if re.match(r"^\d*<{1,3}[^<]", word) and len(out) > 0:
            i += 1
            continue
        out.append(word)
        i += 1
    return out


def _runs_entry(command: str) -> bool:
    """The adapters' entry point run by hand, wherever it is named from (`cd <plugin> && python3 adapters/hook.py
    claude-code`): the way to hand Foreman a made-up "the person typed this". Naming the file (`git add
    adapters/hook.py`) is not running it."""
    for prog, words in programs(command):
        if not _PYTHON.match(prog):
            continue
        words = _without_redirections(words)  # `hook.py < forged.json pi` still runs `hook.py pi`
        for i, word in enumerate(words[:-1]):
            # the entry point takes the harness's name as its one argument: `…/hook.py pi`, not a `hook.py` that
            # merely lives under a folder called `pi` or is given some other word
            if gate._prog(word) == "hook.py" and words[i + 1] in HOSTS:
                return True
    return False


_SETS_REVIEWER = re.compile(r"\b%s\s*=" % REVIEWER_ENV)


def _guard_command(host: Host, command: str) -> Optional[dict]:
    if _names_own(host, command) or _runs_entry(command):
        return {"action": BLOCK, "message": _OWN}
    if _SETS_REVIEWER.search(command or ""):  # a harness started as "the reviewer" runs without the gate
        return {"action": BLOCK, "message": _OFF}
    try:
        if host.switches_off(command):
            return {"action": BLOCK, "message": _OFF}
    except Exception:
        logger.warning("foreman: the host's switch-off check failed", exc_info=True)
    if _person_only(host, command):
        return {"action": BLOCK, "message": _PERSON_ONLY % host.person("allow <id>")}
    if any(name in host.board for name in BOARD_WRITES) and _person_only(host, command, _WRITE_WORDS):
        return {"action": BLOCK, "message": _PERSON_WRITES % host.person("merge <pr>")}
    if host.fresh_session is not None and _person_only(host, command, _EACH_TURN_WORDS):
        return {"action": BLOCK, "message": _PERSON_WHEN % host.person("reviewer every-turn on|off")}
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
_PATCH_HEADER = re.compile(r"^\*\*\* (Update File|Add File|Delete File|Move to):\s*(.+?)\s*$")


def _read_config(path: str) -> str:
    try:
        if os.path.getsize(path) <= _MAX_CONFIG_BYTES:
            with open(path, encoding="utf-8", errors="replace") as fh:
                return fh.read()
    except OSError:
        pass
    return ""


def _patch_switches_off(host: Host, patch: str, full: Callable[[str], str]) -> bool:
    """A patch that leaves one of the harness's settings files switching Foreman off: by changing it, by deleting
    it, or by moving another file over it."""
    try:
        sides = {full(path): (old, new) for path, old, new, _is_new in gate._v4a_files(patch)}
    except Exception:
        logger.warning("foreman: cannot read the patch's files", exc_info=True)
        return False
    source = None
    for line in detector.lines_of(patch):
        m = _PATCH_HEADER.match(line)
        if not m:
            continue
        try:  # one file's failed check never skips the next file's
            kind, path = m.group(1), full(m.group(2))
            if kind == "Move to":
                if source is None:
                    continue
                # The gate files a moved file's lines under the name it had. Where it lands it is the file on
                # disk plus what the patch adds; where it leaves from, it is gone.
                landed = _read_config(source) + "\n" + sides.get(source, ("", ""))[1]
                if host.is_config(path) and host.config_off(_read_config(path), landed):
                    return True
                if host.is_config(source) and host.config_off(_read_config(source), ""):
                    return True
                continue
            source = path
            if not host.is_config(path):
                continue
            if kind == "Delete File":
                if host.config_off(_read_config(path), ""):
                    return True
            elif host.config_off(*sides.get(path, ("", ""))):
                return True
        except Exception:
            logger.warning("foreman: the host's config check failed", exc_info=True)
    return False


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
    if not os.path.isdir(base):
        return {"action": ASK, "message": "Foreman could not inspect this patch: the working directory %s does not "
                                          "exist on this machine. Approve only if you have checked the change "
                                          "yourself." % base}
    if _patch_switches_off(host, patch, full):
        return {"action": BLOCK, "message": _OFF}
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


def note(host: Host, session: str, key: str, value: str) -> None:
    """Remember one thing about a session that outlives its turns (its effort level, as the harness last said
    it): a small file of its own, so a turn's start does not wipe it."""
    path = _session_file(host, session, ".meta.json")
    if not path or not isinstance(value, str):
        return
    try:
        data = {}
        try:
            with open(path, encoding="utf-8") as fh:
                loaded = json.load(fh)
            data = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            pass
        if data.get(key) == value:
            return
        data[key] = value
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
    except OSError:
        logger.warning("foreman: cannot note the session's %s", key, exc_info=True)


def noted(host: Host, session: str, key: str) -> str:
    path = _session_file(host, session, ".meta.json")
    try:
        with open(path, encoding="utf-8") as fh:
            value = json.load(fh).get(key)
        return value if isinstance(value, str) else ""
    except (OSError, ValueError, TypeError, AttributeError):
        return ""


REVIEWER_DIR = "reviewer"            # in the state directory: one file per review running now, named by its token
REVIEWER_TOKEN_SECONDS = 3600
REVIEWER_CLOCK_SLACK_SECONDS = 5
_TOKEN = re.compile(r"^[0-9a-f]{32}$")


def _reviewer_tokens() -> Optional[str]:
    state = _state_dir()
    return os.path.join(state, REVIEWER_DIR) if state else None


def reviewer_session(env) -> bool:
    """True inside a session Foreman itself started to review a change: ``REVIEWER_ENV`` holds the token of a
    review that is running now. The variable alone is not enough: a repository's settings can set a variable for
    every session opened in it, and that must not be a way to switch the gate off. The token is random, lives only
    while its review runs, and its file is in Foreman's state directory, which the agent's shell is kept out of."""
    token = (env or {}).get(REVIEWER_ENV)
    directory = _reviewer_tokens()
    if not isinstance(token, str) or not _TOKEN.match(token) or not directory:
        return False
    try:
        return _token_is_live(os.path.join(directory, token))
    except OSError:
        return False


def _token_is_live(path: str) -> bool:
    """A token file written within the last hour. One dated in the future is not live either: nothing of
    Foreman's writes such a file, and it would otherwise never expire. A few seconds ahead is still now: a file's
    time and the clock do not tick together (seen on Windows: a file just written read as a moment in the future)."""
    return -REVIEWER_CLOCK_SLACK_SECONDS <= time.time() - os.path.getmtime(path) < REVIEWER_TOKEN_SECONDS


def run_session(argv: list, prompt: str, seconds: float, env=None, cwd: Optional[str] = None,
                drop: tuple = ()) -> tuple:
    """Run a harness's own headless command for the reviewer: (exit code, standard output, standard error). The
    prompt goes in on standard input, never on the command line (a diff is too long for one, and it is written by
    the author under review). The child carries the token of this review in ``REVIEWER_ENV``, so Foreman's own hooks
    stand down inside it (``reviewer_session``); ``drop`` names variables of the asking session it must not inherit.
    Raises RuntimeError when it cannot start or does not finish in time."""
    import secrets
    import subprocess
    child = {k: v for k, v in dict(os.environ if env is None else env).items() if k not in drop}
    token, marker = secrets.token_hex(16), None
    directory = _reviewer_tokens()
    try:
        if directory:
            os.makedirs(directory, exist_ok=True)
            for name in os.listdir(directory):  # what an interrupted review left behind
                try:  # each on its own: another review ending now removes its file under this loop
                    if not _token_is_live(os.path.join(directory, name)):
                        os.unlink(os.path.join(directory, name))
                except OSError:
                    pass
            marker = os.path.join(directory, token)
            with open(marker, "w", encoding="utf-8") as fh:
                fh.write(str(int(time.time())))
    except OSError:
        marker = None  # without it the child's own Foreman hooks run as in any session: slower, not wrong
    child[REVIEWER_ENV] = token
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        r = subprocess.run([str(a) for a in argv], input=(prompt or "").encode("utf-8"), capture_output=True,
                           timeout=max(1.0, float(seconds)), env=child, cwd=cwd, **kwargs)
    except subprocess.TimeoutExpired:
        raise RuntimeError("the reviewer's session did not answer within %d seconds" % int(seconds))
    except OSError as e:
        raise RuntimeError("cannot start the reviewer's session (%s): %s" % (argv[0] if argv else "?", e))
    finally:
        if marker:
            try:
                os.unlink(marker)
            except OSError:
                pass
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


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
    each_turn = False
    if changed and host.fresh_session is not None:
        from . import reviewer  # late: it loads the review
        each_turn = reviewer.each_turn(host)  # the person turned on the review at the end of every turn
    if each_turn:
        out = reviewer.turn_end(host, changed, session, nudges)  # the gate first, then the review, then the loop
    else:
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
    "review": "[pr|branch] [--fresh]  a fresh session that did not write the code reviews the change (advisory)",
    "reviewer": "[model] [effort]  who reviews: show it, set it, or `default`; `every-turn on|off` for when",
    "help": "this help",
}
REVIEW_SUBCOMMANDS = ("review", "reviewer")  # listed and answered only where the harness has a reviewer


def person_subcommands(host: Host) -> dict:
    """The subcommands this harness answers, the board's first where it has them."""
    out = {}
    if host.board:
        from . import standin  # late: it loads the board
        out.update({name: standin.DOCS[name] for name in standin.DOCS if name in host.board})
    out.update({name: doc for name, doc in PERSON_SUBCOMMANDS.items()
                if host.fresh_session is not None or name not in REVIEW_SUBCOMMANDS})
    return out


def default_subcommand(host: Host) -> str:
    """What ``/foreman`` alone answers: the board where the harness has it (as in Hermes), else the verdict."""
    return "board" if "board" in host.board else "status"


def person_command(host: Host, text, cwd: str = "", session: str = "") -> Optional[str]:
    """What Foreman answers to a command the person typed (``/foreman:status``, ``/foreman allow 3f2a``), or None
    when ``text`` is not one of Foreman's commands. Only the harness's own "the user typed this" event may reach it:
    the model cannot type."""
    m = _PERSON_COMMAND.match(text) if isinstance(text, str) else None
    if not m:
        return None
    parts = (m.group(1) or "").strip().split(None, 1)
    name = parts[0].lower() if parts else default_subcommand(host)
    spaced = not re.match(r"^\s*/foreman:", text, re.I)
    if spaced and parts and name not in PERSON_SUBCOMMANDS and name not in _hermes_subcommands():
        return None  # "/foreman is blocking my commit, why?" is a question for the model, not a command
    return person_reply(host, m.group(1) or "", cwd, session)


def person_reply(host: Host, args, cwd: str = "", session: str = "", answer: Optional[dict] = None) -> str:
    """Foreman's answer to its command with these arguments (``"status src"``, ``"allow 3f2a"``, ``""`` for the
    board or the verdict), for a harness whose own command mechanism already established that the person typed
    ``/foreman``. ``session`` is the conversation's id (a pinned repository is kept per session); ``answer`` is the
    person's answer to the question this same command asked a moment ago (``Asking``, which it raises)."""
    parts = (args if isinstance(args, str) else "").strip().split(None, 1)
    name = parts[0].lower() if parts else default_subcommand(host)
    rest = parts[1].strip() if len(parts) > 1 else ""
    try:
        return reword(host, _run_person(host, name, rest, cwd, session, answer))
    except Exception as e:  # the person asked: always an answer, never a stack trace
        logger.warning("foreman: the person's command failed", exc_info=True)
        return "Foreman failed: %s: %s" % (type(e).__name__, e)


def _hermes_subcommands() -> set:
    try:
        from foreman import commands
        return set(commands.SUBCOMMANDS)
    except Exception:
        return set()


def _run_person(host: Host, name: str, rest: str, cwd: str, session: str = "",
                answer: Optional[dict] = None) -> str:
    from foreman import commands  # late: it loads the board, the review and the notifications
    if name in host.board or (name == "status" and not rest and host.board):
        from . import standin  # the board as it is, on a stand-in for Hermes's context; `status` for the pinned one
        return standin.run(host, name, rest, cwd, session, answer)
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
                    "Type `%s` in %s." % (host.person("allow " + rest.split()[0]), attend_here(host)))
        return commands.cmd_allow(rest)
    if name == "help":
        return _help(host)
    if name in REVIEW_SUBCOMMANDS and host.fresh_session is not None:
        from . import reviewer  # late: it loads the review
        if name == "reviewer":
            return reviewer.configure(host, rest)
        where = cwd
        if host.board:  # the repository pinned with `use` comes first, as for every board subcommand
            from . import standin
            where = standin.pinned(session) or cwd
        return reviewer.run(host, rest, where)
    if (name in commands.SUBCOMMANDS or name in REVIEW_SUBCOMMANDS) and host.board:
        return "Foreman: `%s` is not available in %s yet. `%s` lists what is." % (name, host.label,
                                                                                host.person("help"))
    if name in commands.SUBCOMMANDS or name in REVIEW_SUBCOMMANDS:
        return ("Foreman: `%s` is not available in %s yet. Here Foreman is the gate (it blocks a rigged commit, "
                "push or pull request, and an agent-run merge) plus `%s` and `%s`."
                % (name, host.label, host.person("status"), host.person("allow")))
    return "Unknown subcommand `%s`.\n\n%s" % (name, _help(host))


def _help(host: Host) -> str:
    from foreman import verdicts
    from foreman.detector import MARKER
    lines = ["Foreman: a green check the agent did not rig.", "", "In %s:" % host.label]
    lines += ["  %-18s %s" % (host.person(name), doc) for name, doc in person_subcommands(host).items()]
    writes = [host.person(n + " <pr>") for n in BOARD_WRITES if n in host.board]
    if host.attended_where and writes:
        lines += ["", "%s work only in %s." % (" and ".join(writes), host.attended_where)]
    lines += ["", "Verdicts:", verdicts.table(), "",
              "Foreman blocks git commit, git push and gh pr create when the change skips, deletes or moves tests, "
              "edits or weakens what the check runs, bypasses hooks or carries a secret; an agent-run gh pr merge is "
              "always blocked (merging is yours%s)." % (": `%s`" % host.person("merge <pr>")
                                                        if "merge" in host.board else ""),
              "A false positive is marked on its line with `%s` (or, for a file, a commit-message line `%s <path>: "
              "<reason>`). The mark never passes alone: it waits until you run `%s`."
              % (MARKER, MARKER, host.person("allow <id>"))]
    if host.board:
        lines.append("Pull requests and issues come from the GitHub CLI (`gh`) with its own login; without it the "
                     "board shows the local branches.")
    return "\n".join(lines)
