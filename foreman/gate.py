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
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from . import detector
from .detector import MARKER, Finding, GitError, Repo

logger = logging.getLogger(__name__)

TERMINAL_TOOLS = {"terminal"}
WRITE_TOOLS = {"write_file", "patch"}
# Hermes abandons a pre_tool_call callback after plugins.hook_callback_timeout (30 s by default) and blocks the
# tool; Foreman stays well inside that and asks a person instead when it runs out of time.
HOOK_BUDGET_SECONDS = 20.0
MAX_LISTED = 15
_MAX_READ_BYTES = 2 * 1024 * 1024

# Cheap prefilter: the command must mention git or gh together with a gated verb.
_QUICK = re.compile(r"\b(?:git|gh)(?:\.exe)?\b[\s\S]*\b(?:commit|push|pr)\b", re.I)
_SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "fish"}
_POWERSHELLS = {"powershell", "pwsh"}
_WRAPPERS = {"sudo", "env", "command", "time", "nohup", "exec", "builtin", "nice"}
_CD = {"cd", "pushd", "set-location", "sl", "chdir"}


# ─── Command parsing (best effort) ───────────────────────────────────────────

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


class _Op(str):
    """An operator token, distinguishable from a quoted word with the same text."""


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


@dataclass
class Action:
    """One gated invocation found in a command line."""
    kind: str  # commit, push, pr-create, pr-merge
    cwd: str
    args: list
    hooks_bypassed: bool = False
    after_git_add: bool = False
    bypass_flag: str = ""
    extra: dict = field(default_factory=dict)


def _resolve(cwd: str, path: str) -> str:
    path = os.path.expanduser(path)
    return os.path.normpath(path if os.path.isabs(path) else os.path.join(cwd, path))


def parse_actions(command: str, cwd: str, _depth: int = 0) -> list:
    """Gated actions in ``command`` run from ``cwd``, following ``cd`` and ``git -C``."""
    actions, git_add_seen = [], False
    for words in segments(command):
        while words and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]) or _prog(words[0]) in _WRAPPERS):
            words = words[1:]
        if not words:
            continue
        prog = _prog(words[0])
        if prog in _CD:
            target = next((w for w in words[1:] if not w.startswith("-")), None)
            cwd = _resolve(cwd, target) if target else os.path.expanduser("~")
            continue
        if prog in _SHELLS and _depth < 3:  # bash -c "git commit ..."
            idx = next((k for k, w in enumerate(words[1:], 1) if re.match(r"^-[a-z]*c$", w)), None)
            if idx is not None and idx + 1 < len(words):
                actions += parse_actions(words[idx + 1], cwd, _depth + 1)
            continue
        if prog in _POWERSHELLS and _depth < 3:  # pwsh -Command git commit ...
            idx = next((k for k, w in enumerate(words[1:], 1) if w.lower() in ("-c", "-command")), None)
            if idx is not None and idx + 1 < len(words):
                actions += parse_actions(" ".join(_requote(w) for w in words[idx + 1:]), cwd, _depth + 1)
            continue
        if prog == "git":
            act, added = _parse_git(words[1:], cwd, git_add_seen)
            git_add_seen = git_add_seen or added
            if act:
                actions.append(act)
        elif prog == "gh":
            act = _parse_gh(words[1:], cwd)
            if act:
                actions.append(act)
    return actions


def _requote(word: str) -> str:
    return word if word and not re.search(r"\s", word) else '"%s"' % word


def _parse_git(words: list, cwd: str, git_add_seen: bool):
    hooks_bypassed, bypass, i = False, "", 0
    while i < len(words):
        w = words[i]
        if w == "-C" and i + 1 < len(words):
            cwd = _resolve(cwd, words[i + 1])
            i += 2
        elif w == "-c" and i + 1 < len(words):
            if words[i + 1].lower().startswith("core.hookspath"):
                hooks_bypassed, bypass = True, "-c " + words[i + 1]
            i += 2
        elif w.startswith("--git-dir=") or w.startswith("--work-tree="):
            if w.startswith("--work-tree="):
                cwd = _resolve(cwd, w.split("=", 1)[1])
            i += 1
        elif w in ("--git-dir", "--work-tree", "--namespace", "--exec-path") and i + 1 < len(words):
            if w == "--work-tree":
                cwd = _resolve(cwd, words[i + 1])
            i += 2
        elif w.startswith("-"):
            i += 1
        else:
            break
    if i >= len(words):
        return None, False
    sub, rest = words[i], words[i + 1:]
    if sub == "add":
        return None, True
    if sub == "commit":
        flag = _commit_no_verify(rest)
        return Action("commit", cwd, rest, hooks_bypassed or bool(flag), git_add_seen, bypass or flag), False
    if sub == "push":
        flag = "--no-verify" if "--no-verify" in rest else ""
        return Action("push", cwd, rest, hooks_bypassed or bool(flag), git_add_seen, bypass or flag), False
    return None, False


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


def _parse_gh(words: list, cwd: str):
    ws = [w for w in words]
    i = 0
    while i < len(ws) and ws[i].startswith("-"):
        i += 2 if ws[i] in ("-R", "--repo") else 1
    if i + 1 < len(ws) and ws[i] == "pr" and ws[i + 1] in ("create", "merge"):
        return Action("pr-" + ws[i + 1], cwd, ws[i + 2:])
    return None


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


# ─── Evaluating an action ────────────────────────────────────────────────────

@dataclass
class Outcome:
    findings: list = field(default_factory=list)
    notes: list = field(default_factory=list)  # reasons a person must approve, besides allowed findings
    errors: list = field(default_factory=list)


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
    words = list(_commit_words(act.args))
    all_flag, pathspec = False, False
    for kind, a in words:
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


def _bypass_finding(act: Action) -> Finding:
    return Finding("hooks-bypassed", "", 0, "`%s` skips the repository's git hooks" % act.bypass_flag,
                   "Run the command without it. If a hook fails, fix what it reports.")


def evaluate(act: Action, budget: float = HOOK_BUDGET_SECONDS) -> Outcome:
    out = Outcome()
    if act.hooks_bypassed:
        out.findings.append(_bypass_finding(act))
    if not os.path.isdir(act.cwd):
        out.errors.append("the working directory %s does not exist on the Hermes host (a remote terminal backend?)"
                          % act.cwd)
        return out
    root = detector.find_repo(act.cwd)
    if not root:
        return out  # not a repository: git or gh will fail on its own, nothing would be published
    repo = Repo(root, budget=budget)
    try:
        if act.kind == "commit":
            staged_only, untracked = _commit_scope(act)
            report = detector.scan_worktree(repo, staged_only=staged_only, include_untracked=untracked,
                                            extra_messages=_commit_message(act), scope="commit")
        elif act.kind == "push":
            report = _push_report(repo, act)
        elif act.kind == "pr-create":
            report = _pr_create_report(repo, act)
        else:
            report = _pr_merge_report(repo, act, out)
        if report is not None:
            out.findings += report.findings
    except GitError as e:
        out.errors.append(str(e))
    return out


def _push_report(repo: Repo, act: Action):
    positional = [a for a in act.args if not a.startswith("-")]
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

_GUIDANCE = ("Fix the cause in the code. Do not skip, isolate, delete or move tests, edit what the check runs, or "
             "bypass hooks to get a green check. If a finding is a false positive, mark the line with `%s` (or, for "
             "a file, add `%s <path>: <reason>` to the commit message): a person will be asked to approve it."
             % (MARKER, MARKER))


def _dedupe(findings: list) -> list:
    seen, out = set(), []
    for f in findings:
        key = (f.rule, f.file, f.line, f.allowed)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def _list(findings: list) -> str:
    lines = []
    for f in findings[:MAX_LISTED]:
        lines.append("- [%s] %s: %s\n  Fix: %s" % (f.rule, f.location or "(command)", f.message, f.fix))
    if len(findings) > MAX_LISTED:
        lines.append("- ... and %d more (run `/foreman status`)" % (len(findings) - MAX_LISTED))
    return "\n".join(lines)


def _approve(message: str) -> dict:
    # A rule key per message: "always allow" then covers this exact case, never every terminal call.
    key = "foreman:" + hashlib.sha256(message.encode("utf-8")).hexdigest()[:16]
    return {"action": "approve", "message": message, "rule_key": key}


def directive(what: str, outcome: Outcome) -> Optional[dict]:
    findings = _dedupe(outcome.findings)
    blockers = [f for f in findings if not f.allowed]
    allowed = [f for f in findings if f.allowed]
    if blockers:
        return {"action": "block", "message": "Foreman blocked %s: %d blocker(s).\n%s\n%s"
                                              % (what, len(blockers), _list(blockers), _GUIDANCE)}
    parts = []
    if outcome.errors:
        parts.append("Foreman could not inspect %s: %s. Approve only if you have checked the change yourself."
                     % (what, "; ".join(outcome.errors)))
    if allowed:
        parts.append("The agent marked these findings in %s as false positives with `%s`; approve only if you "
                     "agree:\n%s" % (what, MARKER, _list(allowed)))
    parts += outcome.notes
    return _approve("\n\n".join(parts)) if parts else None


# ─── pre_tool_call ───────────────────────────────────────────────────────────

def session_cwd() -> str:
    """The session's working directory (not the gateway's), through Hermes's documented helper."""
    try:
        from agent.runtime_cwd import resolve_agent_cwd
        return str(resolve_agent_cwd())
    except Exception:
        return os.getcwd()


def on_pre_tool_call(tool_name: str = "", args=None, **kwargs) -> Optional[dict]:
    if tool_name not in TERMINAL_TOOLS and tool_name not in WRITE_TOOLS:
        return None
    if not isinstance(args, dict):
        return None
    if tool_name in TERMINAL_TOOLS:
        command = args.get("command")
        if not isinstance(command, str) or not _QUICK.search(command):
            return None
        try:
            return gate_command(command, args.get("workdir") if isinstance(args.get("workdir"), str) else None)
        except Exception as e:  # never raise: Hermes would block the tool with a stack trace instead
            logger.warning("foreman: pre_tool_call failed", exc_info=True)
            return _approve("Foreman could not inspect `%s`: %s: %s. Approve only if you have checked the change "
                            "yourself." % (_short(command), type(e).__name__, e))
    try:
        return gate_write(tool_name, args)
    except Exception:
        logger.warning("foreman: write gate failed", exc_info=True)
        return None


def _short(command: str, limit: int = 120) -> str:
    one = " ".join(command.split())
    return one if len(one) <= limit else one[:limit - 3] + "..."


_LABELS = {"commit": "`git commit`", "push": "`git push`", "pr-create": "`gh pr create`", "pr-merge": "`gh pr merge`"}


def gate_command(command: str, workdir: Optional[str] = None) -> Optional[dict]:
    base = session_cwd()
    cwd = _resolve(base, workdir) if workdir else base
    actions = parse_actions(command, cwd)
    if not actions:
        return None
    total = Outcome()
    for act in actions:
        try:
            o = evaluate(act)
        except Exception as e:
            o = Outcome(errors=["%s: %s" % (type(e).__name__, e)])
        total.findings += o.findings
        total.notes += o.notes
        total.errors += ["%s in %s: %s" % (_LABELS[act.kind], act.cwd, err) for err in o.errors]
    what = ", ".join(dict.fromkeys(_LABELS[a.kind] for a in actions))
    return directive(what, total)


# ─── Writes to test files ────────────────────────────────────────────────────

def _new_marker_lines(old_text: str, new_text: str) -> list:
    """Lines of ``new_text`` with a skip marker that ``old_text`` did not already have."""
    before = Counter(l.strip() for l in (old_text or "").splitlines() if detector.has_skip_marker(l))
    added = []
    for l in (new_text or "").splitlines():
        if detector.has_skip_marker(l):
            key = l.strip()
            if before[key] > 0:
                before[key] -= 1
            else:
                added.append(key)
    return added


def _read(path: str) -> str:
    try:
        if os.path.getsize(path) > _MAX_READ_BYTES:
            return ""
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _repo_relative(path: str) -> str:
    root = detector.find_repo(os.path.dirname(path) or ".")
    if root:
        try:
            return os.path.relpath(path, root).replace("\\", "/")
        except ValueError:
            pass
    return path.replace("\\", "/")


def _v4a_files(patch: str) -> list:
    """(path, removed text, added text) per file of a V4A patch."""
    files, cur = [], None
    for line in patch.splitlines():
        m = re.match(r"^\*\*\* (Update|Add) File:\s*(.+?)\s*$", line)
        if m:
            cur = [m.group(2), [], []]
            files.append(cur)
            continue
        if line.startswith("*** "):
            cur = None if not line.startswith("*** Move to:") else cur
            continue
        if cur is None:
            continue
        if line.startswith("+"):
            cur[2].append(line[1:])
        elif line.startswith("-"):
            cur[1].append(line[1:])
    return [(p, "\n".join(r), "\n".join(a)) for p, r, a in files]


def gate_write(tool_name: str, args: dict) -> Optional[dict]:
    edits = []  # (path, old text, new text)
    if tool_name == "write_file":
        path, content = args.get("path"), args.get("content")
        if isinstance(path, str) and isinstance(content, str) and detector.has_skip_marker(content):
            edits.append((path, None, content))
    else:
        patch = args.get("patch")
        if isinstance(patch, str) and (args.get("mode") == "patch" or not args.get("old_string")):
            edits += [(p, old, new) for p, old, new in _v4a_files(patch) if detector.has_skip_marker(new)]
        new = args.get("new_string")
        if isinstance(args.get("path"), str) and isinstance(new, str) and detector.has_skip_marker(new):
            edits.append((args["path"], args.get("old_string") or "", new))
    if not edits:
        return None
    cwd = session_cwd()
    blocked, allowed = [], []
    for path, old, new in edits:
        full = _resolve(cwd, path)
        rel = _repo_relative(full)
        if not detector.is_test_path(rel):
            continue
        if old is None:
            old = _read(full)
        for line in _new_marker_lines(old, new):
            (allowed if MARKER in line else blocked).append((rel, line))
    if blocked:
        listing = "\n".join("- %s: `%s`" % (p, l[:160]) for p, l in blocked[:MAX_LISTED])
        return {"action": "block", "message": "Foreman blocked this %s: it adds a skip/only/xfail marker to a test.\n"
                "%s\nMake the test pass by fixing the code under test instead of switching the test off. %s"
                % (tool_name, listing, _GUIDANCE)}
    if allowed:
        listing = "\n".join("- %s: `%s`" % (p, l[:160]) for p, l in allowed[:MAX_LISTED])
        return _approve("The agent wants to switch off a test and marked it with `%s`; approve only if you agree:\n%s"
                        % (MARKER, listing))
    return None


# ─── pre_verify ──────────────────────────────────────────────────────────────

def on_pre_verify(coding: bool = False, attempt: int = 0, changed_paths=None, **kwargs) -> Optional[dict]:
    try:
        if not coding or attempt:
            return None
        return verify_worktrees(changed_paths or [])
    except Exception:
        logger.warning("foreman: pre_verify failed", exc_info=True)
        return None


def verify_worktrees(changed_paths: list, budget: float = HOOK_BUDGET_SECONDS) -> Optional[dict]:
    cwd = session_cwd()
    roots = []
    for p in list(changed_paths)[:50]:
        if not isinstance(p, str):
            continue
        root = detector.find_repo(os.path.dirname(_resolve(cwd, p)))
        if root and root not in roots:
            roots.append(root)
        if len(roots) >= 3:
            break
    blockers = []
    for root in roots:
        try:
            report = detector.scan_worktree(Repo(root, budget=budget))
        except GitError:
            continue
        blockers += [(root, f) for f in report.blockers]
    if not blockers:
        return None
    many = len(roots) > 1
    lines = []
    for root, f in blockers[:MAX_LISTED]:
        where = os.path.join(root, f.location) if many else f.location
        lines.append("- [%s] %s: %s\n  Fix: %s" % (f.rule, where, f.message, f.fix))
    if len(blockers) > MAX_LISTED:
        lines.append("- ... and %d more" % (len(blockers) - MAX_LISTED))
    return {"action": "continue", "message":
            "Foreman: before you finish, the uncommitted changes would rig the check (%d blocker(s)):\n%s\n"
            "Undo each of these and fix the cause in the code instead; the commit will be blocked otherwise. If you "
            "did not make one of these changes, tell the user instead of undoing it." % (len(blockers), "\n".join(lines))}
