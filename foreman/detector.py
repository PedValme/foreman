"""Foreman's detector: deterministic, no model, only Python's standard library and git.

It reads the real git diff and reports blockers:

- secrets in the added lines, and in every commit of a range (a secret added and later removed is still in the
  history that gets pushed);
- skipped or isolated tests (skip, only, xfail markers);
- deleted test files, and test files renamed out of the tests;
- a change to a file the check command runs (its entry point), so a red check is not "fixed" by editing the check.

False positives: a line marked with ``foreman:allow`` and a commit-message line ``foreman:allow <path>: <reason>``
(for a deleted, moved or check file) do not make a finding disappear. They turn it into an *allowed* finding, which
the gate escalates to a person: the agent cannot wave itself through.

CI usage::

    python -m foreman.detector <base> [<head>] [--check "<check command>"] [--json] [--repo <path>]

The exit status is 1 when there is at least one blocker that is not allowed.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Iterable, Optional

MARKER = "foreman:allow"
CONFIG_FILE = ".foreman.json"

# What Python generates (__pycache__/, .pyc) is never a test: deleting it is not deleting tests.
TEST_PATH = re.compile(
    r"^(?!(?:.*/)?__pycache__/)(?!.*\.py[co]$).*?(?:(^|/)(tests?|__tests__|e2e|spec)/|(_test|\.test|\.spec)\.[A-Za-z]+$|"
    r"(^|/)(test_[^/]+\.py|conftest\.py)$)")

SECRETS = tuple(re.compile(x) for x in (
    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"\bgh[pousr]_[A-Za-z0-9]{36,}",
    r"\bgithub_pat_[A-Za-z0-9_]{40,}",
    r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{24,}",
    r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
    r"\bAIza[0-9A-Za-z_-]{35}",
    r"\b[rs]k_live_[0-9A-Za-z]{20,}",
    r"\bgl(?:pat|rt|dt|ptt)-[0-9A-Za-z_-]{20,}",
    r"\bnpm_[A-Za-z0-9]{36}\b",
    r"\bsb_secret_[0-9A-Za-z_-]{20,}", r"\bwhsec_[0-9A-Za-z+/=]{24,}", r"\bxapp-\d-[A-Za-z0-9-]{20,}",
    r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/(?!X+\b)[A-Za-z0-9]{20,}",  # XXXX is the docs example
    r"(?i)authorization:\s*bearer\s+[A-Za-z0-9._~+/-]{20,}",
    r"(?i)(password|passwd|contrase(?:ñ|n)a|secret|api_?key|token)\w{0,80}[\"']?\s*[:=]\s*[\"'](?P<value>[^\"'\s]{8,})[\"']",
    r"\b[a-z][a-z0-9+.-]*://[^\s:/@\"']+:[^\s@/\"']+@(?!(?:localhost|127\.0\.0\.1)(?:[:/\"'\s]|$))[^\s/\"']+",
))
# Only in YAML files: in code, "token: string" is a type annotation.
SECRET_YAML = re.compile(
    r"(?i)^\+\s*[\w.-]{0,80}(password|passwd|secret|api_?key|token)[\w.-]{0,80}\s*:\s*[^\s'\"#{}\[\]$<|>&*!%@`][^#\n]{7,}?\s*(#.*)?$")
IS_YAML = re.compile(r"\.ya?ml$", re.I)
# properties, ini, conf, toml, .env: key=value or key: value, unquoted.
SECRET_CONFIG = re.compile(
    r"(?i)^\+\s*[\w.-]{0,80}(password|passwd|secret|api_?key|token)[\w.-]{0,80}\s*[=:]\s*[^\s'\"#;${<][^\s#;]{7,}")
IS_CONFIG = re.compile(r"(?i)\.(properties|ini|conf|cfg|toml)$|(^|/)\.env(\.[^/]*)?$")
# NAME=value with no quotes and no $: shell, Dockerfile, extensionless scripts and compose `environment` lists.
# Names that point to a secret (TOKEN_FILE, SECRET_NAME) and values that are code (args.token) or a path do not count;
# the quantifiers are bounded so a long line cannot hang the hook.
_NAME = (r"[\w.-]{0,80}(password|passwd|secret|api_?key|token)\w{0,80}"
         r"(?<!_file)(?<!_path)(?<!_dir)(?<!_name)(?<!_url)(?<!_header)(?<!_id)")
_VALUE = r"(?![A-Za-z_]\w*(?:\.\w+)+(?:[\s;]|$))(?!/)[A-Za-z0-9_./+=!@%^&*:,~-]{8,}(?:[\s;]|$)"
SECRET_SHELL = re.compile(r"(?i)^\+\s*(?:(?:export|local|readonly|ARG|ENV)\s+|declare\s+-x\s+)?" + _NAME + "=" + _VALUE
                          + r"|^\+\s*ENV\s+" + _NAME + r"\s+" + _VALUE)
SECRET_LIST = re.compile(r"(?i)^\+\s*-\s*" + _NAME + "=" + _VALUE)  # compose: `- POSTGRES_PASSWORD=value`
IS_SHELL = re.compile(r"(?i)\.(sh|bash|zsh)$|(^|/)\.envrc$|(^|/)[^/.]+$|(^|/)Dockerfile[^/]*$|\.dockerfile$")
# A JWT in a test is a fixture; outside the tests it is a session or a service key.
JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
SKIPPED_TEST = tuple(re.compile(x) for x in (
    r"\b(?:it|test|describe|context)\.(?:skip|only)\s*\(",
    r"\b(?:xit|xdescribe|fit|fdescribe)\s*\(",
    r"\bpytest\.mark\.(?:skip\w*|xfail)\b", r"\bpytest\.skip\s*\(",
    r"@unittest\.(?:skip\w*|expectedFailure)\b",
))
# In a test file a made-up value is not a secret, but only for `key: "value"`; real credential formats
# (AKIA, ghp_, sk-, private keys) count everywhere.
FICTITIOUS = re.compile(r"(?i)(synthetic|fake|dummy|example)[-_]")
ENV_FILE = re.compile(r"(^|/)\.env(\.[^/]*)?$")
ENV_TEMPLATE = re.compile(r"\.(example|sample|template)$")

FIXES = {
    "secret": ("possible secret in an added line",
               "Remove the value and read it from the environment or a secret store; rotate it if it was ever "
               "committed. If it is not a secret, add `" + MARKER + "` to the line: a person will be asked to approve."),
    "secret-history": ("possible secret in a commit of the range that would be published",
                       "Rewrite the branch so that no commit contains it (a later commit that deletes it is not "
                       "enough), and rotate it."),
    "env-file": (".env file with values",
                 "Do not commit .env files: commit a .env.example with placeholders and add .env to .gitignore."),
    "test-skipped": ("test skipped or isolated (skip/only/xfail marker)",
                     "Remove the marker and make the test pass by fixing the code under test, not the test."),
    "test-deleted": ("test file deleted",
                     "Restore the file. If an equivalent test replaces it, add the line `" + MARKER
                     + " <path>: <reason>` to the commit message: a person will be asked to approve."),
    "test-moved": ("test file moved out of the tests",
                   "Move it back under the tests. If the move is intended, add the line `" + MARKER
                   + " <path>: <reason>` to the commit message: a person will be asked to approve."),
    "check-changed": ("this change edits a file that the check command runs",
                      "Revert the change to the check's entry point and fix the code instead. If the change is "
                      "intended, add the line `" + MARKER + " <path>: <reason>` to the commit message: a person "
                      "will be asked to approve."),
}


@dataclass
class Finding:
    rule: str
    file: str
    line: int
    message: str
    fix: str
    severity: str = "blocker"
    allowed: bool = False

    @property
    def location(self) -> str:
        return "%s:%d" % (self.file, self.line) if self.line else (self.file or "?")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["location"] = self.location
        return d


def finding(rule: str, path: str, line: int, detail: str = "", allowed: bool = False) -> Finding:
    message, fix = FIXES[rule]
    return Finding(rule, path or "", line, message + (" (%s)" % detail if detail else ""), fix, allowed=allowed)


# ─── Line rules ──────────────────────────────────────────────────────────────

def _matches_secret(regex, text: str, path: Optional[str]) -> bool:
    for m in regex.finditer(text):
        value = m.groupdict().get("value")
        if value and FICTITIOUS.match(value) and path and TEST_PATH.search(path):
            continue
        return True
    return False


def _jwt_secret(text: str) -> bool:
    """A JWT outside the tests, except Supabase's anon key: it is public by design and ships in the frontend."""
    for m in JWT.finditer(text):
        payload = m.group(0).split(".")[1]
        try:
            role = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("role")
        except (ValueError, AttributeError):
            role = None
        if role != "anon":
            return True
    return False


def has_secret(text: str, path: Optional[str]) -> bool:
    """``text`` is an added diff line, with its leading ``+``."""
    return (any(_matches_secret(r, text, path) for r in SECRETS)
            or bool(path and IS_YAML.search(path) and (SECRET_YAML.search(text) or SECRET_LIST.search(text)))
            or bool(path and IS_CONFIG.search(path) and SECRET_CONFIG.search(text))
            or bool(path and IS_SHELL.search(path) and SECRET_SHELL.search(text))
            or bool(not (path and TEST_PATH.search(path)) and _jwt_secret(text)))


def has_skip_marker(text: str) -> bool:
    return any(r.search(text) for r in SKIPPED_TEST)


def is_test_path(path: str) -> bool:
    return bool(TEST_PATH.search((path or "").replace("\\", "/")))


def _is_env_file(path: Optional[str]) -> bool:
    return bool(path and ENV_FILE.search(path) and not ENV_TEMPLATE.search(path))


# ─── Diff parsing ────────────────────────────────────────────────────────────

def unquote_path(raw: str) -> str:
    """Git C-quotes paths with special characters: ``"b/producci\\303\\263n.yaml"``."""
    raw = raw.strip()
    if len(raw) < 2 or raw[0] != '"' or raw[-1] != '"':
        return raw
    body, out, i = raw[1:-1], bytearray(), 0
    simple = {"n": b"\n", "t": b"\t", '"': b'"', "\\": b"\\", "a": b"\a", "b": b"\b", "f": b"\f", "r": b"\r",
              "v": b"\v"}
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in "01234567" and re.match(r"[0-7]{3}", body[i + 1:i + 4]):
                out.append(int(body[i + 1:i + 4], 8))
                i += 4
                continue
            out += simple.get(nxt, nxt.encode("utf-8"))
            i += 2
            continue
        out += c.encode("utf-8")
        i += 1
    return out.decode("utf-8", "replace")


def _diff_path(header: str) -> str:
    """``+++ b/x`` or, when git quoted it, ``+++ "b/x"``."""
    path = unquote_path(header[4:].rstrip("\n"))
    return path[2:] if path.startswith("b/") else path


def paths_from_name_status(name_status: str):
    """From ``git diff --name-status -M``: every touched path (both sides of a rename), deletions and renames."""
    paths, deleted, renamed = [], [], []
    for row in name_status.splitlines():
        parts = [unquote_path(p) for p in row.split("\t")]
        if len(parts) < 2:
            continue
        if parts[0].startswith(("R", "C")) and len(parts) >= 3:
            paths += [parts[1], parts[2]]
            if parts[0].startswith("R"):
                renamed.append((parts[1], parts[2]))
        else:
            paths.append(parts[1])
            if parts[0] == "D":
                deleted.append(parts[1])
    return paths, deleted, renamed


def allowed_paths_in(messages: Optional[str]) -> set:
    """Paths a commit message allows to delete, move or change: a line ``foreman:allow <path>: <reason>``."""
    return {m.group(1) for m in re.finditer(r"(?m)^\s*%s\s+(\S+?):\s+\S" % re.escape(MARKER), messages or "")}


_HUNK = re.compile(r"^(@{2,}) (.*?) @{2,}")


def _iter_added(diff: str):
    """Yield (path, line number in the new file, added text with a single leading +).

    Hunk lengths are tracked, so an added line whose content starts with "++ " is never taken for a file header.
    Combined diffs of merges (``--cc``, ``@@@`` hunks) carry one prefix column per parent."""
    path, line, new_left, old_left, ncols = None, 0, 0, 0, 1
    for text in diff.splitlines():
        if (new_left > 0 or old_left > 0) and text[:1] in (" ", "+", "-", "\\", ""):
            if text.startswith("\\"):  # "\ No newline at end of file"
                continue
            prefix, body = text[:ncols], text[ncols:]
            if "-" in prefix:
                old_left -= 1
                continue
            if "+" in prefix:
                yield path, line, "+" + body
            else:
                old_left -= 1
            new_left -= 1
            line += 1
            continue
        new_left = old_left = 0
        if text.startswith("+++ "):
            path = _diff_path(text)
            continue
        m = _HUNK.match(text)
        if m:
            ncols = len(m.group(1)) - 1
            for sign, start, count in re.findall(r"([-+])(\d+)(?:,(\d+))?", m.group(2)):
                n = int(count) if count else 1
                if sign == "+":
                    line, new_left = int(start), n
                elif ncols == 1:
                    old_left = n


def _line_finding(path, line, text, history: bool = False) -> Optional[Finding]:
    allowed = MARKER in text
    if _is_env_file(path) and "=" in text:
        return finding("secret-history" if history else "env-file", path, line, allowed=allowed)
    if has_secret(text, path):
        return finding("secret-history" if history else "secret", path, line, allowed=allowed)
    if not history and has_skip_marker(text):
        return finding("test-skipped", path, line, allowed=allowed)
    return None


def history_secrets(history_diff: str) -> list:
    """Secrets in the per-commit patches of a range (``git log -p --cc``)."""
    found = []
    for path, line, text in _iter_added(history_diff):
        f = _line_finding(path, line, text, history=True)
        if f:
            found.append(f)
    return found


def detect(diff: str, deleted: Iterable[str] = (), history: str = "", renamed: Iterable = (),
           allowed_paths: Iterable[str] = ()) -> list:
    """Blockers in a unified diff, the deleted and renamed paths and, optionally, the per-commit history."""
    allowed_paths = set(allowed_paths or ())
    found = []
    for path, line, text in _iter_added(diff):
        f = _line_finding(path, line, text)
        if f:
            found.append(f)
    for path in deleted:
        if TEST_PATH.search(path):
            found.append(finding("test-deleted", path, 0, allowed=path in allowed_paths))
    for old, new in renamed:
        if TEST_PATH.search(old) and not TEST_PATH.search(new):
            found.append(finding("test-moved", old, 0, "to %s" % new, allowed=old in allowed_paths))
    # A secret in the history is reported even when the final diff already has another finding at that place.
    seen = {(f.file, f.line) for f in found if f.rule in ("secret", "env-file")}
    found += [f for f in history_secrets(history) if (f.file, f.line) not in seen]
    return found


# ─── The check's entry point ─────────────────────────────────────────────────

LAUNCHERS = {"npm": "package.json", "pnpm": "package.json", "yarn": "package.json", "make": "Makefile"}


def words(command: Optional[str]) -> list:
    """The words of a shell command, unquoted, without operators (&&, ;, |, redirections). With an unclosed quote it
    falls back to splitting on spaces and operators and stripping quotes, so paths are still recognised."""
    try:
        lex = shlex.shlex(command or "", posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        return [t for t in lex if t and not set(t) <= set("();<>|&")]
    except ValueError:
        return [t.strip("'\"") for t in re.split(r"[\s;&|()<>]+", command or "") if t.strip("'\"")]


def check_files(command: Optional[str], is_file: Callable[[str], bool]) -> list:
    """The files of the base that the check command runs: words that are files (scripts/check.sh), and package.json
    or Makefile when the command uses them. A directory (tests) does not count: tests change in every change. This
    protects the check's entry point, not everything it runs; skipped and deleted tests cover the rest."""
    out, ws = set(), words(command)
    for i, word in enumerate(ws):
        if word == "-m" and i + 1 < len(ws):  # python -m package.module: its file, or the package's __main__
            stem = ws[i + 1].replace(".", "/")
            out.update(p for p in (stem + ".py", stem + "/__main__.py") if is_file(p))
        if not word or word.startswith("-"):
            continue
        path = word[2:] if word.startswith("./") else word
        if path in LAUNCHERS and is_file(LAUNCHERS[path]):
            out.add(LAUNCHERS[path])
        elif is_file(path):
            out.add(path)
    return sorted(out)


def check_changed(command: Optional[str], paths: Iterable[str], is_file: Callable[[str], bool],
                  allowed_paths: Iterable[str] = (), protected: Iterable[str] = ()) -> list:
    """One blocker per file the base's check runs (plus ``protected`` ones) that the change touches."""
    paths, allowed_paths = set(paths), set(allowed_paths or ())
    targets = sorted(set(check_files(command, is_file)) | set(protected))
    def detail(p):
        return "Foreman's own configuration" if p == CONFIG_FILE else "check: `%s`" % command

    return [finding("check-changed", p, 0, detail(p), allowed=p in allowed_paths) for p in targets if p in paths]


# ─── Git ─────────────────────────────────────────────────────────────────────

class GitError(RuntimeError):
    pass


_DIFF_OPTS = ("--no-color", "--no-ext-diff", "--no-textconv", "--src-prefix=a/", "--dst-prefix=b/")
_MAX_UNTRACKED_FILES = 500
_MAX_UNTRACKED_BYTES = 512 * 1024


class Repo:
    """A git working tree, with an optional deadline shared by every git call (the hook has a time budget)."""

    def __init__(self, root: str, budget: Optional[float] = None):
        self.root = root
        self.deadline = time.monotonic() + budget if budget else None
        self._empty_tree = None

    def git(self, *args: str, ok_codes=(0,), stdin: bytes = b"") -> str:
        timeout = None
        if self.deadline is not None:
            timeout = self.deadline - time.monotonic()
            if timeout <= 0:
                raise GitError("time budget exhausted before `git %s`" % args[0])
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", LC_ALL="C")
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            r = subprocess.run(["git", "-c", "core.quotePath=false", "-c", "log.showSignature=false",
                                "-c", "color.ui=false", *args], cwd=self.root, input=stdin,
                               capture_output=True, timeout=timeout, env=env, **kwargs)
        except subprocess.TimeoutExpired:
            raise GitError("`git %s` timed out" % args[0])
        except OSError as e:
            raise GitError("cannot run git: %s" % e)
        if r.returncode not in ok_codes:
            raise GitError("`git %s` failed: %s" % (args[0], r.stderr.decode("utf-8", "replace").strip()[-300:]))
        return r.stdout.decode("utf-8", "replace")

    def try_git(self, *args: str) -> Optional[str]:
        try:
            return self.git(*args).strip()
        except GitError:
            return None

    @property
    def empty_tree(self) -> str:
        if self._empty_tree is None:
            self._empty_tree = self.git("hash-object", "-t", "tree", "--stdin").strip()
        return self._empty_tree

    def has_head(self) -> bool:
        return self.try_git("rev-parse", "--verify", "-q", "HEAD^{commit}") is not None

    def branch(self) -> str:
        return self.try_git("rev-parse", "--abbrev-ref", "HEAD") or "(no commits)"

    def is_file_at(self, rev: str) -> Callable[[str], bool]:
        def is_file(path: str) -> bool:
            return self.try_git("cat-file", "-t", "%s:%s" % (rev, path)) == "blob"
        return is_file

    def show(self, rev: str, path: str) -> Optional[str]:
        return self.try_git("show", "%s:%s" % (rev, path))

    def upstream(self) -> Optional[str]:
        return self.try_git("rev-parse", "--verify", "-q", "@{upstream}^{commit}")

    def base_ref(self, head: str = "HEAD") -> tuple:
        """(merge-base sha, label) with the remote's default branch; falls back to a local main/master. (None, None)
        when there is no base: a repository with no remote and no main branch, or no commits."""
        remotes = (self.try_git("remote") or "").split()
        remotes.sort(key=lambda r: r != "origin")
        candidates = []
        for remote in remotes:
            head_ref = self.try_git("symbolic-ref", "-q", "refs/remotes/%s/HEAD" % remote)
            if head_ref:
                candidates.append(head_ref)
            candidates += ["refs/remotes/%s/main" % remote, "refs/remotes/%s/master" % remote]
        candidates += ["refs/heads/main", "refs/heads/master"]
        for ref in candidates:
            sha = self.try_git("merge-base", head, ref)
            if sha:
                label = ref.replace("refs/remotes/", "").replace("refs/heads/", "")
                return sha, label
        return None, None


def find_repo(path: str) -> Optional[str]:
    """The top level of the git working tree that contains ``path`` (a file or a directory), or None."""
    p = os.path.abspath(path or ".")
    while p and not os.path.isdir(p):
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent
    top = Repo(p, budget=5).try_git("rev-parse", "--show-toplevel")
    return os.path.normpath(top) if top else None


@dataclass
class Report:
    repo: str
    scope: str
    base: Optional[str] = None
    base_label: Optional[str] = None
    head: Optional[str] = None
    check: Optional[str] = None
    findings: list = field(default_factory=list)

    @property
    def blockers(self) -> list:
        return [f for f in self.findings if not f.allowed]

    @property
    def allowed(self) -> list:
        return [f for f in self.findings if f.allowed]

    @property
    def verdict(self) -> str:
        if self.blockers:
            return "BLOCKED"
        return "NEEDS_APPROVAL" if self.allowed else "CLEAN"

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "repo": self.repo, "scope": self.scope, "base": self.base,
                "base_label": self.base_label, "head": self.head, "check": self.check,
                "blockers": [f.to_dict() for f in self.blockers], "allowed": [f.to_dict() for f in self.allowed]}


def format_findings(findings: Iterable[Finding], indent: str = "  ") -> str:
    lines = []
    for f in findings:
        lines.append("%s[%s] %s  %s" % (indent, f.rule, f.location, f.message))
        lines.append("%s    fix: %s" % (indent, f.fix))
    return "\n".join(lines)


def check_command_at(repo: Repo, rev: Optional[str], explicit: Optional[str] = None) -> Optional[str]:
    """The check command: the explicit one, else the ``check`` key of .foreman.json *at the base*, so a change
    cannot redefine its own check."""
    if explicit:
        return explicit
    if not rev:
        return None
    raw = repo.show(rev, CONFIG_FILE)
    if not raw:
        return None
    try:
        value = json.loads(raw).get("check")
    except (ValueError, AttributeError):
        return None
    return value if isinstance(value, str) and value.strip() else None


def _check_findings(repo: Repo, base_rev: Optional[str], check: Optional[str], paths, allowed_paths) -> list:
    if not base_rev:
        return []
    is_file = repo.is_file_at(base_rev)
    protected = [CONFIG_FILE] if is_file(CONFIG_FILE) else []
    if not check and not protected:
        return []
    return check_changed(check, paths, is_file, allowed_paths, protected)


def scan_range(repo: Repo, base: Optional[str], head: str = "HEAD", check: Optional[str] = None,
               extra_messages: str = "", scope: str = "range", base_label: Optional[str] = None) -> Report:
    """What publishing ``base..head`` would publish: the final diff, plus every commit's patch for secrets. Without a
    base (a branch with no ancestor on the remote), the whole history of ``head``."""
    rev_range = "%s..%s" % (base, head) if base else head
    diff_from = base or repo.empty_tree
    paths, deleted, renamed = paths_from_name_status(repo.git("diff", "--name-status", "-M", *_DIFF_OPTS, diff_from, head))
    messages = repo.git("log", "--format=%B", rev_range) + "\n" + (extra_messages or "")
    allowed_paths = allowed_paths_in(messages)
    findings = detect(repo.git("diff", "-M", *_DIFF_OPTS, diff_from, head), deleted,
                      history=repo.git("log", "-p", "--cc", *_DIFF_OPTS, "--format=", rev_range),
                      renamed=renamed, allowed_paths=allowed_paths)
    check = check_command_at(repo, base, check)
    findings += _check_findings(repo, base, check, paths, allowed_paths)
    return Report(repo.root, scope, base, base_label, repo.try_git("rev-parse", head), check, findings)


def _untracked_diff(repo: Repo) -> tuple:
    """Untracked (not ignored) files as a synthetic diff of additions, and their paths."""
    out = repo.git("ls-files", "--others", "--exclude-standard", "-z")
    files = [p for p in out.split("\0") if p][:_MAX_UNTRACKED_FILES]
    parts = []
    for path in files:
        full = os.path.join(repo.root, *path.split("/"))
        try:
            if os.path.getsize(full) > _MAX_UNTRACKED_BYTES:
                continue
            with open(full, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue  # binary
        lines = data.decode("utf-8", "replace").splitlines()
        if not lines:
            continue
        parts.append("+++ b/%s\n@@ -0,0 +1,%d @@\n%s\n" % (path, len(lines), "\n".join("+" + l for l in lines)))
    return "".join(parts), files


def scan_worktree(repo: Repo, staged_only: bool = False, include_untracked: bool = True, check: Optional[str] = None,
                  extra_messages: str = "", scope: str = "worktree") -> Report:
    """The uncommitted changes against HEAD: staged and unstaged (or only staged), plus untracked files."""
    has_head = repo.has_head()
    base = "HEAD" if has_head else repo.empty_tree
    cached = ("--cached",) if staged_only else ()
    paths, deleted, renamed = paths_from_name_status(repo.git("diff", "--name-status", "-M", *cached, *_DIFF_OPTS, base))
    diff = repo.git("diff", "-M", *cached, *_DIFF_OPTS, base)
    if include_untracked and not staged_only:
        extra, files = _untracked_diff(repo)
        diff += "\n" + extra
        paths += files
    allowed_paths = allowed_paths_in(extra_messages)
    findings = detect(diff, deleted, renamed=renamed, allowed_paths=allowed_paths)
    head_rev = "HEAD" if has_head else None
    check = check_command_at(repo, head_rev, check)
    findings += _check_findings(repo, head_rev, check, paths, allowed_paths)
    return Report(repo.root, scope, repo.try_git("rev-parse", "HEAD") if has_head else None, "HEAD",
                  None, check, findings)


def scan_branch(repo: Repo, check: Optional[str] = None) -> Report:
    """The current branch against the merge-base with the remote's default branch (or a local main/master)."""
    if not repo.has_head():
        return Report(repo.root, "branch", findings=[])
    base, label = repo.base_ref()
    if not base:
        return Report(repo.root, "branch", head=repo.try_git("rev-parse", "HEAD"), findings=[])
    return scan_range(repo, base, "HEAD", check=check, scope="branch", base_label=label)


# ─── CI entry point ──────────────────────────────────────────────────────────

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m foreman.detector",
                                     description="Deterministic test-integrity and secret check for a git range.")
    parser.add_argument("base", help="base revision (for a pull request: the merge-base with the target branch)")
    parser.add_argument("head", nargs="?", default="HEAD", help="head revision (default: HEAD)")
    parser.add_argument("--check", help="the check command of the base; default: `check` in the base's .foreman.json")
    parser.add_argument("--repo", default=".", help="path inside the repository (default: the current directory)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    root = find_repo(args.repo)
    if not root:
        print("foreman: %s is not inside a git repository" % args.repo, file=sys.stderr)
        return 2
    try:
        report = scan_range(Repo(root), args.base, args.head, check=args.check)
    except GitError as e:
        print("foreman: %s" % e, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print("foreman: %s (%d blocker(s), %d allowed by marker)" % (report.verdict, len(report.blockers),
                                                                    len(report.allowed)))
        if report.blockers:
            print(format_findings(report.blockers))
        if report.allowed:
            print("Allowed by a %s marker; a person must review these:" % MARKER)
            print(format_findings(report.allowed))
    return 1 if report.blockers else 0


if __name__ == "__main__":
    sys.exit(main())
