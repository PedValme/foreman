"""Foreman's hooks inside the Hermes agent loop.

``pre_tool_call`` runs on every tool call, so it returns at once for anything that is not a git commit or push, a
``gh pr create`` or ``gh pr merge``, or a write to a test file. It never raises: a callback that raises or times out
makes Hermes fail closed for that tool. ``pre_verify`` runs when the agent is about to finish a turn in which it
edited code, and asks it to undo what would rig the check.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Optional

from . import detector, grants
from .detector import MARKER, Finding, GitError, Repo

logger = logging.getLogger(__name__)

TERMINAL_TOOLS = {"terminal"}
WRITE_TOOLS = {"write_file", "patch"}
# One deadline for the whole hook call. Hermes abandons a pre_tool_call callback after
# plugins.hook_callback_timeout (30 s by default) and blocks the tool; Foreman stays well inside that.
HOOK_BUDGET_SECONDS = 18.0
MAX_LISTED = 15
_MAX_READ_BYTES = 2 * 1024 * 1024

# Cheap prefilter: the command must mention git or gh together with a gated verb.
_QUICK = re.compile(r"\b(?:git|gh)(?:\.exe)?\b[\s\S]*\b(?:commit|push|pr)\b", re.I)
_SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "fish"}
_POWERSHELLS = {"powershell", "pwsh"}
_WRAPPERS = {"sudo", "env", "command", "time", "nohup", "exec", "builtin", "nice"}
_CD = {"cd", "pushd", "set-location", "sl", "chdir"}
# What may run before a gated command in the same line: it cannot change what the command records.
_SAFE_PROGS = {"echo"}
_SAFE_GIT = {"add", "status", "diff", "log", "show", "branch"}
_SAFE_GH = {"view", "list", "status", "checks", "diff"}

_LABELS = {"commit": "`git commit`", "push": "`git push`", "pr-create": "`gh pr create`", "pr-merge": "`gh pr merge`"}


# ─── Command parsing (best effort) ───────────────────────────────────────────

class _Op(str):
    """An operator token, distinguishable from a quoted word with the same text."""


class _Redir(str):
    """An unquoted output redirection (``>``, ``>>``, ``>&2``); its target, if any, is the next word."""


def tokenize(command: str) -> list:
    """Split a shell command into words and operator tokens. Quotes are removed, backslashes are kept literally
    except before a quote, a space or another backslash, so Windows paths survive."""
    tokens, buf, quote, has_word, i = [], [], None, False, 0
    n = len(command)

    def flush():
        nonlocal buf, has_word
        if has_word:
            tokens.append("".join(buf))
        buf, has_word = [], False

    while i < n:
        c = command[i]
        if quote:
            if c == quote:
                quote = None
            elif c == "\\" and quote == '"' and i + 1 < n and command[i + 1] in '"\\$`':
                buf.append(command[i + 1])
                i += 1
            else:
                buf.append(c)
            i += 1
            continue
        if c in "'\"":
            quote, has_word = c, True
        elif c == "\\" and i + 1 < n and command[i + 1] in "'\" \\\n":
            if command[i + 1] != "\n":
                buf.append(command[i + 1])
                has_word = True
            i += 1
        elif c in " \t\r":
            flush()
        elif c == ">":
            flush()
            m = re.match(r">>?(?:&(?:\d+|-))?", command[i:])
            tokens.append(_Redir(m.group(0)))
            i += len(m.group(0))
            continue
        elif c == "\n" or c in ";|&(){}":
            flush()
            op = command[i:i + 2] if command[i:i + 2] in ("&&", "||") else c
            tokens.append(_Op(op))
            i += len(op)
            continue
        else:
            buf.append(c)
            has_word = True
        i += 1
    flush()
    return tokens


def segments(command: str) -> list:
    """The simple commands of a command line, each a list of words."""
    out, cur = [], []
    for tok in tokenize(command or ""):
        if isinstance(tok, _Op):
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append(tok)
    if cur:
        out.append(cur)
    return out


def _prog(word: str) -> str:
    name = word.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def _resolve(cwd: str, path: str) -> str:
    path = os.path.expanduser(path)
    return os.path.normpath(path if os.path.isabs(path) else os.path.join(cwd, path))


def _short(command: str, limit: int = 80) -> str:
    one = " ".join(command.split())
    return one if len(one) <= limit else one[:limit - 3] + "..."


@dataclass
class Action:
    """One gated invocation found in a command line."""
    kind: str  # commit, push, pr-create, pr-merge
    cwd: str
    args: list
    hooks_bypassed: bool = False
    after_git_add: bool = False
    bypass_flag: str = ""
    located: bool = False      # the command itself says where it runs (workdir, cd, git -C)
    preceded_by: str = ""      # an earlier part of the same command line that may change what this one records


def parse_actions(command: str, cwd: str, located: bool = False, _depth: int = 0, _state: Optional[dict] = None) -> list:
    """Gated actions in ``command`` run from ``cwd``, following ``cd``, ``pushd``/``popd`` and ``git -C``."""
    state = _state if _state is not None else {"unsafe": "", "git_add": False, "gated": ""}
    actions, stack = [], []

    def unsafe(words):
        state["unsafe"] = state["unsafe"] or _short(" ".join(words))

    for words in segments(command):
        original = list(words)
        words, writes_file = _strip_redirs(words)
        while words and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]) or _prog(words[0]) in _WRAPPERS):
            words = words[1:]
        if not words:
            continue
        prog = _prog(words[0])
        if prog in _CD:
            target = next((w for w in words[1:] if not w.startswith("-")), None)
            if prog == "pushd":
                stack.append(cwd)
            cwd = _resolve(cwd, target) if target else os.path.expanduser("~")
            located = True
            continue
        if prog == "popd":
            cwd = stack.pop() if stack else cwd
            continue
        if prog in _SAFE_PROGS:
            if writes_file:  # echo x > tests/test_a.py rewrites a file
                unsafe(original)
            continue
        inner = None
        if prog in _SHELLS:  # bash -c "git commit ..."
            idx = next((k for k, w in enumerate(words[1:], 1) if re.match(r"^-[a-z]*c$", w)), None)
            inner = words[idx + 1] if idx is not None and idx + 1 < len(words) else None
        elif prog in _POWERSHELLS:  # pwsh -Command git commit ...
            idx = next((k for k, w in enumerate(words[1:], 1) if w.lower() in ("-c", "-command")), None)
            inner = " ".join(_requote(w) for w in words[idx + 1:]) if idx is not None else None
        elif prog == "cmd":  # cmd /c git commit ...
            idx = next((k for k, w in enumerate(words[1:], 1) if w.lower() in ("/c", "/k")), None)
            inner = " ".join(_requote(w) for w in words[idx + 1:]) if idx is not None else None
        if prog in _SHELLS | _POWERSHELLS | {"cmd"}:
            if inner is not None and _depth < 3:
                actions += parse_actions(inner, cwd, located, _depth + 1, state)
            else:
                unsafe(original)
            continue
        act, sub = None, ""
        if prog == "git":
            act, sub = _parse_git(words[1:], cwd, state["git_add"], located)
            if act is None:
                if sub == "add" and not writes_file:
                    state["git_add"] = True
                elif sub not in _SAFE_GIT or writes_file:
                    unsafe(original)
                continue
        elif prog == "gh":
            act, sub = _parse_gh(words[1:], cwd, located)
            if act is None:
                if sub not in _SAFE_GH or writes_file:
                    unsafe(original)
                continue
        else:
            unsafe(original)
            continue
        if state["gated"]:
            act.preceded_by = state["gated"]
        elif state["unsafe"]:
            act.preceded_by = "`%s`" % state["unsafe"]
        state["gated"] = _LABELS[act.kind]
        actions.append(act)
    return actions


_HARMLESS_TARGETS = {"/dev/null", "nul", "$null"}


def _strip_redirs(words: list) -> tuple:
    """(words without redirections, True when a redirection or ``--output`` writes a file)."""
    clean, writes, i = [], False, 0
    while i < len(words):
        w = words[i]
        if isinstance(w, _Redir):
            if "&" not in w:  # >&2 duplicates a descriptor; > file writes one
                target = words[i + 1] if i + 1 < len(words) else ""
                writes = writes or target.lower() not in _HARMLESS_TARGETS
                i += 1
            i += 1
            continue
        if w.startswith("--output"):
            writes = True
        clean.append(w)
        i += 1
    return clean, writes


def _requote(word: str) -> str:
    return word if word and not re.search(r"\s", word) else '"%s"' % word


def _parse_git(words: list, cwd: str, git_add_seen: bool, located: bool):
    hooks_bypassed, bypass, i = False, "", 0
    while i < len(words):
        w = words[i]
        if w == "-C" and i + 1 < len(words):
            cwd, located = _resolve(cwd, words[i + 1]), True
            i += 2
        elif w == "-c" and i + 1 < len(words):
            if words[i + 1].lower().startswith("core.hookspath"):
                hooks_bypassed, bypass = True, "-c " + words[i + 1]
            i += 2
        elif w.startswith("--work-tree="):
            cwd, located = _resolve(cwd, w.split("=", 1)[1]), True
            i += 1
        elif w in ("--git-dir", "--work-tree", "--namespace", "--exec-path") and i + 1 < len(words):
            if w == "--work-tree":
                cwd, located = _resolve(cwd, words[i + 1]), True
            i += 2
        elif w.startswith("-"):
            i += 1
        else:
            break
    if i >= len(words):
        return None, ""
    sub, rest = words[i], words[i + 1:]
    if sub == "commit":
        flag = _commit_no_verify(rest)
        return Action("commit", cwd, rest, hooks_bypassed or bool(flag), git_add_seen, bypass or flag, located), sub
    if sub == "push":
        flag = "--no-verify" if "--no-verify" in rest else ""
        return Action("push", cwd, rest, hooks_bypassed or bool(flag), git_add_seen, bypass or flag, located), sub
    return None, sub


# git commit options that take the next word as their value
_COMMIT_VALUE_OPTS = {"-m", "--message", "-F", "--file", "-C", "-c", "--author", "--date", "-t", "--template",
                      "--fixup", "--squash", "--reuse-message", "--reedit-message", "--cleanup", "--trailer",
                      "--pathspec-from-file"}
_COMMIT_VALUE_LETTERS = "mFCct"


def _commit_words(args: list):
    """Yield (kind, word) for ``git commit`` arguments: 'flag', 'value' (an option's value) or 'path'."""
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            for p in args[i + 1:]:
                yield "path", p
            return
        if a in _COMMIT_VALUE_OPTS:
            yield "flag", a
            if i + 1 < len(args):
                yield "value", args[i + 1]
            i += 2
            continue
        if re.match(r"^-[A-Za-z]+$", a):
            yield "flag", a
            letters = a[1:]
            taker = next((k for k, ch in enumerate(letters) if ch in _COMMIT_VALUE_LETTERS), None)
            if taker is not None and taker == len(letters) - 1 and i + 1 < len(args):
                yield "value", args[i + 1]  # -am "message"
                i += 2
                continue
            i += 1
            continue
        yield ("flag" if a.startswith("-") else "path"), a
        i += 1


def _commit_no_verify(args: list) -> str:
    """``--no-verify`` or ``-n`` (also inside a cluster such as ``-anm``) on ``git commit``."""
    for kind, a in _commit_words(args):
        if kind != "flag":
            continue
        if a == "--no-verify":
            return a
        if re.match(r"^-[A-Za-z]+$", a):
            for ch in a[1:]:
                if ch == "n":
                    return a
                if ch in _COMMIT_VALUE_LETTERS:  # the rest of the cluster is that option's value
                    break
    return ""


def _parse_gh(words: list, cwd: str, located: bool):
    i = 0
    while i < len(words) and words[i].startswith("-"):
        i += 2 if words[i] in ("-R", "--repo") else 1
    if i + 1 < len(words) and words[i] == "pr" and words[i + 1] in ("create", "merge"):
        return Action("pr-" + words[i + 1], cwd, words[i + 2:], located=located), words[i + 1]
    return None, words[i + 1] if i + 1 < len(words) else ""


def _option_values(args: list, short: str, long: str) -> list:
    """Values of ``-m x``, ``-mx``, ``--message x`` and ``--message=x``."""
    out, i = [], 0
    while i < len(args):
        a = args[i]
        if a in (short, long) and i + 1 < len(args):
            out.append(args[i + 1])
            i += 2
            continue
        if a.startswith(long + "="):
            out.append(a.split("=", 1)[1])
        elif short and a.startswith(short) and len(a) > len(short) and not a.startswith("--"):
            out.append(a[len(short):])
        elif re.match(r"^-[A-Za-z]+$", a) and short and short[1] in a and a.index(short[1]) == len(a) - 1 \
                and i + 1 < len(args):  # cluster ending with the option: -am "msg"
            out.append(args[i + 1])
            i += 2
            continue
        i += 1
    return out


# ─── Where the session runs ──────────────────────────────────────────────────

# Surfaces where the Hermes process was started by the user in a directory, so that directory means something.
# Messaging platforms and the Desktop app start from wherever the service or the app was launched.
LOCAL_PLATFORMS = {"", "cli", "tui", "local"}
RECORDED, SESSION, PROCESS, CONFIGURED = "recorded", "session", "process", "configured"
HOW = {RECORDED: "the terminal's directory for this session", SESSION: "this session's working directory",
       PROCESS: "the current directory", CONFIGURED: "Hermes's working directory", "given": "the given path"}
NO_REPOSITORY_HERE = ("Foreman could not tell which repository you mean from here. Pick one with `/foreman use` (or "
                      "`/foreman use <path>`), run `/foreman status <path>`, or run it after the agent has used the "
                      "terminal in this session.")


def _session_env(name: str) -> str:
    try:
        from gateway.session_context import get_session_env
        return get_session_env(name, "") or ""
    except Exception:
        return ""


def _canon(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def hermes_homes() -> list:
    """The Hermes homes to keep out of the picture: the active (profile) home, the process home and the root that
    holds the profiles, all through ``hermes_constants`` (public)."""
    homes = []
    try:
        import hermes_constants as hc
        for name in ("get_hermes_home", "get_process_hermes_home", "get_default_hermes_root"):
            fn = getattr(hc, name, None)
            if fn is None:
                continue
            try:
                homes.append(_canon(str(fn())))
            except Exception:
                pass
    except Exception:
        pass
    return list(dict.fromkeys(h for h in homes if h))


def hermes_home() -> Optional[str]:
    homes = hermes_homes()
    return homes[0] if homes else None


def _inside(path: str, home: Optional[str]) -> bool:
    if not home or not path:
        return False
    p = _canon(path)
    return p == home or p.startswith(home.rstrip(os.sep) + os.sep)


def _hermes_data(path: str, root: Optional[str], homes: list) -> bool:
    """True when ``path`` is Hermes's own data: inside a Hermes home, or in a repository whose root is a Hermes home
    or one of its ancestors (the gateway runs from the root home, and a home may itself be a git repository)."""
    for home in homes:
        if _inside(path, home) or (root and _inside(home, _canon(root))):
            return True
    return False


def cwd_candidates(*keys: str, platform: Optional[str] = None) -> list:
    """(directory, how it was found) in order of trust for the surface, existing directories only:

    1. the directory the terminal tool recorded for this session's keys (it follows ``cd`` between calls) — a Hermes
       internal, read guarded;
    2. this session's working directory: the caller's directory, which the gateway binds for a local session's
       slash command (``agent.runtime_cwd.scoped_session_cwd()``);
    3. on local surfaces (CLI, TUI), the process directory;
    4. Hermes's documented ``resolve_agent_cwd()`` (the configured terminal directory).
    Anything inside a Hermes home is dropped unless the terminal recorded it."""
    if platform is None:
        platform = _session_env("HERMES_SESSION_PLATFORM")
    keys_in_order = [k for k in (*keys, _session_env("HERMES_SESSION_KEY")) if isinstance(k, str) and k]
    out = []
    try:
        from tools.terminal_tool import get_session_cwd  # not a documented plugin surface: guarded
        for key in dict.fromkeys(keys_in_order):
            out.append((get_session_cwd(key), RECORDED))
    except Exception:
        pass
    try:
        from agent.runtime_cwd import scoped_session_cwd  # the session's declared cwd, empty when none is bound
        out.append((scoped_session_cwd(), SESSION))
    except Exception:
        pass
    process = None
    try:
        process = os.getcwd()
    except OSError:
        pass
    if str(platform or "").lower() in LOCAL_PLATFORMS:
        out.append((process, PROCESS))
    try:
        from agent.runtime_cwd import resolve_agent_cwd
        out.append((str(resolve_agent_cwd()), CONFIGURED))
    except Exception:
        pass
    homes, seen, result = hermes_homes(), set(), []
    for path, how in out:
        if not isinstance(path, str) or not path or not os.path.isdir(path):
            continue
        path = os.path.normpath(path)
        if path in seen or (how != RECORDED and _hermes_data(path, None, homes)):
            continue
        seen.add(path)
        result.append((path, how))
    return result


def locate(*keys: str, platform: Optional[str] = None, deadline: Optional[float] = None) -> tuple:
    """(directory, how) of the first candidate inside a git repository that is not Hermes's own data, or
    (None, None) when none qualifies: never a guessed repository."""
    homes = hermes_homes()
    for path, how in cwd_candidates(*keys, platform=platform):
        try:
            root = detector.find_repo(path, deadline=deadline)
        except GitError:
            break
        if root and (how == RECORDED or not _hermes_data(path, root, homes)):
            return path, how
    return None, None


# A placeholder base for commands whose directory Foreman could not determine; it never exists.
_UNKNOWN_DIR = os.path.abspath(os.path.join(os.sep, "__foreman_unknown_directory__"))


def session_cwd(*keys: str, platform: Optional[str] = None, deadline: Optional[float] = None) -> str:
    """The located directory, or "" when Foreman cannot tell."""
    return locate(*keys, platform=platform, deadline=deadline)[0] or ""


# ─── Evaluating an action ────────────────────────────────────────────────────

@dataclass
class Outcome:
    findings: list = field(default_factory=list)
    reasons: list = field(default_factory=list)  # blocking reasons that are not detector findings
    notes: list = field(default_factory=list)    # reasons a person must approve
    errors: list = field(default_factory=list)
    repos: list = field(default_factory=list)


def _commit_message(act: Action) -> str:
    parts = _option_values(act.args, "-m", "--message")
    for path in _option_values(act.args, "-F", "--file"):
        try:
            with open(_resolve(act.cwd, path), "r", encoding="utf-8", errors="replace") as fh:
                parts.append(fh.read(64 * 1024))
        except OSError:
            pass
    return "\n".join(parts)


def _commit_scope(act: Action) -> tuple:
    """(staged_only, include_untracked) for what this commit would record."""
    all_flag, pathspec = False, False
    for kind, a in _commit_words(act.args):
        if kind == "path":
            pathspec = True
        elif kind == "flag" and (a in ("--all", "--include", "--only", "-i", "-o") or a.startswith("--pathspec")):
            all_flag = True
        elif kind == "flag" and re.match(r"^-[A-Za-z]+$", a):
            letters = a[1:]
            cut = next((k for k, ch in enumerate(letters) if ch in _COMMIT_VALUE_LETTERS), len(letters))
            all_flag = all_flag or "a" in letters[:cut]
    if act.after_git_add:
        return False, True
    if all_flag or pathspec:
        return False, False
    return True, False


def evaluate(act: Action, deadline: Optional[float] = None) -> Outcome:
    out = Outcome()
    if deadline is None:
        deadline = time.monotonic() + HOOK_BUDGET_SECONDS
    if act.hooks_bypassed:
        out.reasons.append("`%s` skips the repository's git hooks. Run the command without it; if a hook fails, fix "
                           "what it reports." % act.bypass_flag)
    if not os.path.isdir(act.cwd):
        out.errors.append("the working directory %s does not exist on the Hermes host (a remote terminal backend?)"
                          % act.cwd)
        return out
    try:
        root = detector.find_repo(act.cwd, deadline=deadline)
    except GitError as e:
        out.errors.append(str(e))
        return out
    if not root:
        if not act.located:
            out.reasons.append("Foreman cannot tell which repository this runs in: the session directory %s is not a "
                               "git repository. Re-run it with `workdir` set to the repository, or as `git -C <repo> "
                               "...`." % act.cwd)
        return out  # the command names a place that is not a repository: git or gh fails on its own
    out.repos.append(root)
    repo = Repo(root, deadline=deadline)
    try:
        if act.kind == "commit":
            staged_only, untracked = _commit_scope(act)
            report = detector.scan_worktree(repo, staged_only=staged_only, include_untracked=untracked,
                                            extra_messages=_commit_message(act), scope="commit")
        elif act.kind == "push":
            report = _push_report(repo, act, out)
        elif act.kind == "pr-create":
            report = _pr_create_report(repo, act)
        else:
            report = _pr_merge_report(repo, act, out)
        if report is not None:
            out.findings += report.findings
    except GitError as e:
        out.errors.append(str(e))
    return out


def _push_report(repo: Repo, act: Action, out: Outcome):
    positional = [a for a in act.args if not a.startswith("-")]
    if any(a in ("--all", "--mirror", "--branches") for a in act.args) or len(positional) > 2:
        out.notes.append("`git push %s` publishes more than one branch; Foreman inspects only the current one. Push "
                         "each branch on its own, or approve if you have checked them." % " ".join(act.args))
    head = "HEAD"
    if len(positional) >= 2:
        src = positional[1].lstrip("+").split(":", 1)[0]
        if src and repo.try_git("rev-parse", "--verify", "-q", src + "^{commit}"):
            head = src
    if not repo.try_git("rev-parse", "--verify", "-q", head + "^{commit}"):
        return None  # nothing to push
    upstream = repo.try_git("rev-parse", "--verify", "-q", head + "@{upstream}^{commit}")
    if upstream:
        return detector.scan_range(repo, upstream, head, scope="push", base_label=head + "@{upstream}")
    base, label = repo.base_ref(head)
    return detector.scan_range(repo, base, head, scope="push", base_label=label)


def _pr_create_report(repo: Repo, act: Action):
    if not repo.has_head():
        return None
    base_names = _option_values(act.args, "-B", "--base")
    if base_names:
        for ref in ("refs/remotes/origin/" + base_names[0], base_names[0]):
            sha = repo.try_git("merge-base", "HEAD", ref)
            if sha:
                return detector.scan_range(repo, sha, "HEAD", scope="pull request", base_label=base_names[0])
    return detector.scan_branch(repo)


def _pr_merge_report(repo: Repo, act: Action, out: Outcome):
    """A merge always goes to a person (it is never automatic); Foreman adds what it found on the branch."""
    target = next((a for a in act.args if not a.startswith("-")), None)
    branch = repo.branch()
    if target and target != branch:
        out.notes.append("`gh pr merge %s`: Foreman cannot inspect that pull request from the local checkout; "
                         "review it (or check it out and run `/foreman status`) before approving." % target)
        return None
    report = detector.scan_branch(repo)
    if not report.blockers:
        out.notes.append("Merging %s into %s: Foreman found no blockers on the branch; a merge always needs a person."
                         % (branch, report.base_label or "its base"))
    return report


# ─── Directives ──────────────────────────────────────────────────────────────

def _dedupe(findings: Iterable) -> list:
    seen, out = set(), []
    for f in findings:
        key = (f.rule, f.file, f.line, f.allowed, f.fingerprint)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def _line(f: Finding) -> str:
    text = "- [%s] %s — %s" % (f.rule, f.location or "(command)", f.message)
    if f.allowed:
        return text + " (marked `%s`; id %s)" % (MARKER, f.short_id)
    return text + "\n  Fix: " + f.fix


def _list(findings: list) -> str:
    lines = [_line(f) for f in findings[:MAX_LISTED]]
    if len(findings) > MAX_LISTED:
        lines.append("- ... and %d more (run `/foreman status`)" % (len(findings) - MAX_LISTED))
    return "\n".join(lines)


_ASK_USER = ("Marked findings need the user: ask them to review each one and run `/foreman allow <id>` if they "
             "agree. You cannot allow it yourself.")


def _approve(message: str) -> dict:
    # A rule key per message: "always allow" then covers this exact case, never every terminal call.
    key = "foreman:" + hashlib.sha256(message.encode("utf-8")).hexdigest()[:16]
    return {"action": "approve", "message": message, "rule_key": key}


def split_marked(findings: Iterable, repo: str = "") -> tuple:
    """(blocking findings, marked ones still waiting for a person). Marked findings the user already allowed are
    dropped; the others are recorded as pending."""
    blocking, waiting = [], []
    for f in _dedupe(findings):
        if not f.allowed:
            blocking.append(f)
        elif not grants.is_granted(f.fingerprint):
            waiting.append(f)
    if waiting:
        try:
            grants.record_pending(waiting, repo)
        except Exception:
            logger.warning("foreman: cannot record pending findings", exc_info=True)
    return blocking, waiting


def directive(what: str, outcome: Outcome) -> Optional[dict]:
    blocking, waiting = split_marked(outcome.findings, outcome.repos[0] if outcome.repos else "")
    if outcome.reasons or blocking or waiting:
        parts = ["Foreman blocked %s." % what] + outcome.reasons
        if blocking or waiting:
            parts.append(_list(blocking + waiting))
        if waiting:
            parts.append(_ASK_USER)
        return {"action": "block", "message": "\n".join(parts)}
    parts = []
    if outcome.errors:
        parts.append("Foreman could not inspect %s: %s. Approve only if you have checked the change yourself."
                     % (what, "; ".join(outcome.errors)))
    parts += outcome.notes
    return _approve("\n\n".join(parts)) if parts else None


# ─── pre_tool_call ───────────────────────────────────────────────────────────

def on_pre_tool_call(tool_name: str = "", args=None, task_id: str = "", **kwargs) -> Optional[dict]:
    if tool_name not in TERMINAL_TOOLS and tool_name not in WRITE_TOOLS:
        return None
    if not isinstance(args, dict):
        return None
    if tool_name in TERMINAL_TOOLS:
        command = args.get("command")
        if not isinstance(command, str):
            return None
        if _names_store(command) and not _OWN_COMMENT.match(command.strip()):
            return _store_guard()
        if not _QUICK.search(command):
            return None
        try:
            workdir = args.get("workdir") if isinstance(args.get("workdir"), str) else None
            return gate_command(command, workdir, task_id=task_id if isinstance(task_id, str) else "")
        except Exception as e:  # never raise: Hermes would block the tool with a stack trace instead
            logger.warning("foreman: pre_tool_call failed", exc_info=True)
            return _approve("Foreman could not inspect `%s`: %s: %s. Approve only if you have checked the change "
                            "yourself." % (_short(command, 120), type(e).__name__, e))
    try:
        return gate_write(tool_name, args, task_id=task_id if isinstance(task_id, str) else "")
    except Exception:
        logger.warning("foreman: write gate failed", exc_info=True)
        return None


# Foreman's own state in its data directory: the exceptions the user granted, the repository pinned per session,
# the reject comments waiting for `gh`, and saved model reviews. Only the user's /foreman commands change them.
STORE_FILES = (grants.GRANTS_FILE, "foreman-board.json")
STORE_DIRS = ("outbox", "reviews")
_STORE_DIR_TEXT = re.compile(r"(?:plugin-data/foreman|\.foreman)/(?:%s)(?:/|$|[\s\"'])" % "|".join(STORE_DIRS))
# What /foreman reject itself runs: gh reading the comment file it wrote.
_OWN_COMMENT = re.compile(r'^gh pr comment \d+ --body-file "[^"$`]*/outbox/reject-\d+-[A-Za-z0-9_]+\.md"$')


def _store_dirs_text() -> list:
    """The store directories as they are spelt on this machine (lower case, forward slashes)."""
    try:
        base = grants.store_dir().replace("\\", "/").rstrip("/").lower()
    except Exception:
        return []
    return [base + "/" + d for d in STORE_DIRS]


def _names_store(text: str) -> bool:
    """True when ``text`` (a command, a patch or a path) names one of Foreman's store files or directories."""
    low = (text or "").lower().replace("\\", "/")
    return (any(name in low for name in STORE_FILES) or bool(_STORE_DIR_TEXT.search(low + " "))
            or any(d in low for d in _store_dirs_text()))


def _is_store_path(path) -> bool:
    """Foreman's store, however the path is spelt (case, trailing dots or spaces that Windows drops)."""
    if not isinstance(path, str) or not path:
        return False
    clean = path.replace("\\", "/").rstrip("/ ")
    name = os.path.basename(os.path.normpath(clean)).rstrip(". ")
    if os.path.normcase(name).lower() in STORE_FILES:
        return True
    return _names_store(os.path.abspath(os.path.expanduser(clean)) + "/")


def _store_guard() -> dict:
    return {"action": "block", "message": "Foreman blocked this call: Foreman's own state (its exceptions, the "
                                          "pinned repository, reject comments, saved reviews) changes only through "
                                          "the user's `/foreman` commands."}


def gate_command(command: str, workdir: Optional[str] = None, task_id: str = "") -> Optional[dict]:
    deadline = time.monotonic() + HOOK_BUDGET_SECONDS
    if not parse_actions(command, os.sep):  # nothing gated: skip resolving the session directory
        return None
    if workdir and os.path.isabs(os.path.expanduser(workdir)):
        cwd = os.path.normpath(os.path.expanduser(workdir))  # explicit: never replaced by another candidate
    else:
        base = session_cwd(task_id, deadline=deadline) or _UNKNOWN_DIR
        cwd = _resolve(base, workdir) if workdir else base
    actions = parse_actions(command, cwd, located=bool(workdir))
    if not actions:
        return None
    unknown = [a for a in actions if _inside(a.cwd, _canon(_UNKNOWN_DIR))]
    if unknown:  # the command depends on a directory Foreman could not determine
        return {"action": "block", "message": "Foreman blocked %s: it cannot tell which repository this runs in. "
                "Re-run it with `workdir` set to the repository, or as `git -C <repo> ...`."
                % _LABELS[unknown[0].kind]}
    what = ", ".join(dict.fromkeys(_LABELS[a.kind] for a in actions))
    combined = next((a for a in actions if a.preceded_by), None)
    if combined is not None:
        return {"action": "block", "message": "Foreman blocked %s: run %s as its own command (not after %s in the same "
                "line) so Foreman can inspect what it records." % (what, _LABELS[combined.kind], combined.preceded_by)}
    total = Outcome()
    for act in actions:
        try:
            o = evaluate(act, deadline)
        except Exception as e:
            o = Outcome(errors=["%s: %s" % (type(e).__name__, e)])
        total.findings += o.findings
        total.reasons += o.reasons
        total.notes += o.notes
        total.repos += o.repos
        total.errors += ["%s in %s: %s" % (_LABELS[act.kind], act.cwd, err) for err in o.errors]
    return directive(what, total)


# ─── Writes to test files ────────────────────────────────────────────────────

def _new_marker_lines(old_text: str, new_text: str, new_file: bool = False) -> list:
    """(line, next non-empty line) for each line of ``new_text`` with a skip marker that ``old_text`` did not already
    have. In a new file a conditional skip is legitimate."""
    def counts(kind):
        return kind == "skip" or (kind == "conditional" and not new_file)

    before = Counter(" ".join(l.split()) for l in (old_text or "").splitlines() if detector.has_skip_marker(l))
    lines = (new_text or "").splitlines()
    added = []
    for i, l in enumerate(lines):
        if counts(detector.has_skip_marker(l)):
            key = " ".join(l.split())
            if before[key] > 0:
                before[key] -= 1
            else:
                added.append((l.strip(), detector.next_nonempty(lines[i + 1:])))
    return added


def _read(path: str) -> str:
    try:
        if os.path.getsize(path) > _MAX_READ_BYTES:
            return ""
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _repo_relative(path: str) -> tuple:
    """(repository root or None, path relative to it with forward slashes)."""
    root = detector.find_repo(os.path.dirname(path) or ".")
    if root:
        try:
            return root, os.path.relpath(path, root).replace("\\", "/")
        except ValueError:
            pass
    return None, path.replace("\\", "/")


def _v4a_files(patch: str) -> list:
    """(path, old side, new side, is new file) per file of a V4A patch; each side keeps the context lines."""
    files, cur = [], None
    for line in patch.splitlines():
        m = re.match(r"^\*\*\* (Update|Add) File:\s*(.+?)\s*$", line)
        if m:
            cur = [m.group(2), [], [], m.group(1) == "Add"]
            files.append(cur)
            continue
        if line.startswith("*** "):
            cur = None if not line.startswith("*** Move to:") else cur
            continue
        if cur is None or line.startswith("@@"):
            continue
        if line.startswith("+"):
            cur[2].append(line[1:])
        elif line.startswith("-"):
            cur[1].append(line[1:])
        else:  # context
            cur[1].append(line[1:])
            cur[2].append(line[1:])
    return [(p, "\n".join(r), "\n".join(a), new) for p, r, a, new in files]


def gate_write(tool_name: str, args: dict, task_id: str = "") -> Optional[dict]:
    edits = []  # (path, old text or None to read it, new text or None to build it, new file or None to check)
    if _is_store_path(args.get("path")):
        return _store_guard()
    if tool_name == "write_file":
        path, content = args.get("path"), args.get("content")
        if isinstance(path, str) and isinstance(content, str) and detector.has_skip_marker(content):
            edits.append((path, None, content, None))
    else:
        patch = args.get("patch")
        if isinstance(patch, str) and (args.get("mode") == "patch" or not args.get("old_string")):
            if _names_store(patch):
                return _store_guard()
            edits += [(p, old, new, is_new) for p, old, new, is_new in _v4a_files(patch)
                      if detector.has_skip_marker(new)]
        new = args.get("new_string")
        if isinstance(args.get("path"), str) and isinstance(new, str) and detector.has_skip_marker(new):
            edits.append((args["path"], ("replace", args.get("old_string") or "", bool(args.get("replace_all"))),
                          new, False))
    if not edits:
        return None
    cwd = session_cwd(task_id) or os.getcwd()  # only to resolve a relative path; Foreman then finds its repository
    findings, root = [], None
    for path, old, new, is_new in edits:
        full = _resolve(cwd, path)
        root, rel = _repo_relative(full)
        if not detector.is_test_path(rel):
            continue
        if is_new is None:
            is_new = not os.path.exists(full)
        if isinstance(old, tuple):  # patch replace: rebuild the file as it will be, to know the test that follows
            _kind, old_string, replace_all = old
            current = _read(full)
            if old_string and old_string in current:
                old, new = current, current.replace(old_string, new, -1 if replace_all else 1)
            else:
                old = old_string
        elif old is None:
            old = _read(full)
        for line, following in _new_marker_lines(old, new, new_file=is_new):
            findings.append(detector.finding("test-skipped", rel, 0, allowed=MARKER in line, content=line,
                                             following=following))
    blocking, waiting = split_marked(findings, root or "")
    if not (blocking or waiting):
        return None
    parts = ["Foreman blocked this %s: it switches off a test." % tool_name, _list(blocking + waiting)]
    if waiting:
        parts.append(_ASK_USER)
    return {"action": "block", "message": "\n".join(parts)}


# ─── pre_verify ──────────────────────────────────────────────────────────────

def on_pre_verify(coding: bool = False, attempt: int = 0, changed_paths=None, session_id: str = "",
                  **kwargs) -> Optional[dict]:
    try:
        if not coding or attempt:
            return None
        return verify_worktrees(changed_paths or [], session_id=session_id if isinstance(session_id, str) else "")
    except Exception:
        logger.warning("foreman: pre_verify failed", exc_info=True)
        return None


def verify_worktrees(changed_paths: list, budget: float = HOOK_BUDGET_SECONDS, session_id: str = "") -> Optional[dict]:
    deadline = time.monotonic() + budget
    cwd = session_cwd(session_id) or os.getcwd()
    roots = []
    for p in list(changed_paths)[:50]:
        if not isinstance(p, str):
            continue
        try:
            root = detector.find_repo(os.path.dirname(_resolve(cwd, p)), deadline=deadline)
        except GitError:
            break
        if root and root not in roots:
            roots.append(root)
        if len(roots) >= 3:
            break
    blockers = []
    for root in roots:
        try:
            report = detector.scan_worktree(Repo(root, deadline=deadline))
        except GitError:
            continue
        blockers += [(root, f) for f in report.blockers]
    if not blockers:
        return None
    many = len(roots) > 1
    lines = []
    for root, f in blockers[:MAX_LISTED]:
        where = os.path.join(root, f.location) if many else f.location
        lines.append("- [%s] %s — %s\n  Fix: %s" % (f.rule, where, f.message, f.fix))
    if len(blockers) > MAX_LISTED:
        lines.append("- ... and %d more" % (len(blockers) - MAX_LISTED))
    return {"action": "continue", "message":
            "Foreman: undo these before you finish, or the commit will be blocked (if you did not make one of them, "
            "tell the user instead):\n" + "\n".join(lines)}
