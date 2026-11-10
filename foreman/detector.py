"""Foreman's detector: deterministic, no model, only Python's standard library and git.

It reads the real git diff and reports blockers:

- secrets in the added lines, and in every commit of a range (a secret added and later removed is still in the
  history that gets pushed);
- skipped or isolated tests (skip, only, xfail markers);
- deleted test files, and test files renamed out of the tests;
- a change to a file the check command runs (its entry point), so a red check is not "fixed" by editing the check.

False positives: a line marked with ``foreman:allow`` and a commit-message line ``foreman:allow <path>: <reason>``
(for a deleted, moved or check file) do not make a finding disappear. They turn it into a *marked* finding: inside
Hermes it stays blocked until a person runs ``/foreman allow <id>``; in CI it is listed for the reviewer and does not
fail the run. The agent cannot wave itself through.

CI usage::

    python -m foreman.detector <base> [<head>] [--check "<check command>"] [--json] [--repo <path>]
        [--sarif FILE]... [--sarif-threshold error|warning|<number>] [--sarif-scope changed|all] [--strict]

SARIF 2.1.0 reports (see ``foreman.sarif``) are a second source of blockers: given with ``--sarif``, or listed in the
``sarif`` key of .foreman.json at the base.

The exit status is 1 when there is at least one blocker that is not allowed, 2 when the run could not be done
(not a repository, git failed, a SARIF report that cannot be read, whether given with ``--sarif`` or named in
.foreman.json). With ``GITHUB_ACTIONS`` set, every marked finding is also printed as a ``::warning`` annotation;
``--strict`` makes marked findings blockers.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import posixpath
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

# Real credential formats: they count everywhere, tests included.
SECRET_FORMATS = tuple(re.compile(x) for x in (
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
))
# The rules below are pattern guesses: they apply outside the tests only, and their values are filtered.
BEARER = re.compile(r"(?i)authorization:\s*bearer\s+[A-Za-z0-9._~+/-]{20,}")
SECRET_KEY_VALUE = re.compile(
    r"(?i)(password|passwd|contrase(?:ñ|n)a|secret|api_?key|token)\w{0,80}[\"']?\s*[:=]\s*[\"'](?P<value>[^\"'\s]{8,})[\"']")
CREDENTIAL_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://(?P<user>[^\s:/@\"']+):(?P<value>[^\s@/\"']+)@(?P<host>[^\s/\"':?#]+)")
# Only in YAML files: in code, "token: string" is a type annotation.
SECRET_YAML = re.compile(
    r"(?i)^\+\s*[\w.-]{0,80}(password|passwd|secret|api_?key|token)[\w.-]{0,80}\s*:\s*"
    r"(?P<value>[^\s'\"#{}\[\]$<|>&*!%@`][^#\n]{7,}?)\s*(#.*)?$")
IS_YAML = re.compile(r"\.ya?ml$", re.I)
# properties, ini, conf, toml, .env: key=value or key: value, unquoted.
SECRET_CONFIG = re.compile(
    r"(?i)^\+\s*[\w.-]{0,80}(password|passwd|secret|api_?key|token)[\w.-]{0,80}\s*[=:]\s*(?P<value>[^\s'\"#;${<][^\s#;]{7,})")
IS_CONFIG = re.compile(r"(?i)\.(properties|ini|conf|cfg|toml)$|(^|/)\.env(\.[^/]*)?$")
# NAME=value with no quotes and no $: shell, Dockerfile, extensionless scripts and compose `environment` lists.
# Names that point to a secret (TOKEN_FILE, SECRET_NAME) and values that are code (args.token) or a path do not count;
# the quantifiers are bounded so a long line cannot hang the hook.
_NAME = (r"[\w.-]{0,80}(password|passwd|secret|api_?key|token)\w{0,80}"
         r"(?<!_file)(?<!_path)(?<!_dir)(?<!_name)(?<!_url)(?<!_header)(?<!_id)")
_VALUE = r"(?![A-Za-z_]\w*(?:\.\w+)+(?:[\s;]|$))(?!/)(?P<value>[A-Za-z0-9_./+=!@%^&*:,~-]{8,})(?:[\s;]|$)"
SECRET_SHELL = (
    re.compile(r"(?i)^\+\s*(?:(?:export|local|readonly|ARG|ENV)\s+|declare\s+-x\s+)?" + _NAME + "=" + _VALUE),
    re.compile(r"(?i)^\+\s*ENV\s+" + _NAME + r"\s+" + _VALUE),
)
SECRET_LIST = re.compile(r"(?i)^\+\s*-\s*" + _NAME + "=" + _VALUE)  # compose: `- POSTGRES_PASSWORD=value`
IS_SHELL = re.compile(r"(?i)\.(sh|bash|zsh)$|(^|/)\.envrc$|(^|/)[^/.]+$|(^|/)Dockerfile[^/]*$|\.dockerfile$")
# A JWT in a test is a fixture; outside the tests it is a session or a service key.
JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
PLACEHOLDER = re.compile(r"(?i)replace|your|changeme|change_me|xxx|example|placeholder|^<.*>$|\$\{|\{\{|%\(")
UUID = re.compile(r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
EXAMPLE_HOST = re.compile(r"(?i)(^|\.)example(\.|$)|^(localhost|127\.0\.0\.1|0\.0\.0\.0)$")

SKIPPED_TEST = tuple(re.compile(x) for x in (
    r"\b(?:it|test|describe|context)(?:\.concurrent)?\.(?:skip|only)(?:\.each)?\s*[(`]",
    r"\b(?:xit|xtest|xdescribe|fit|fdescribe)\s*\(",
    r"\bpytest\.mark\.(?:skip|xfail)\b", r"\bpytest\.(?:skip|xfail)\s*\(",
    r"@unittest\.(?:skip|expectedFailure)\b", r"\bself\.skipTest\s*\(",
    r"\bthis\.skip\s*\(\s*\)",
    r"\bt\.Skip(?:f|Now)?\s*\(",          # Go
    r"#\[ignore\b",                       # Rust
    r"@(?:Disabled|Ignore)\b",            # JUnit
    # A "conditional" skip whose condition is a constant is unconditional.
    r"\b(?:skipif|skipIf)\s*\(\s*(?:True|true|1)\s*[,)]", r"\bskipUnless\s*\(\s*(?:False|false|0)\s*[,)]",
))
# A conditional skip in a test file that is new in this change is legitimate (a platform-only test); added to an
# existing test it switches that test off.
CONDITIONAL_SKIP = tuple(re.compile(x) for x in (
    r"\bpytest\.mark\.skipif\b", r"@unittest\.skip(?:If|Unless)\b",
    r"\b(?:it|test|describe)(?:\.concurrent)?\.skipIf\s*\(",
))
# Documentation names markers without switching anything off.
DOCS = re.compile(r"(?i)\.(md|markdown|rst|txt|adoc)$")
ENV_FILE = re.compile(r"(^|/)\.env(\.[^/]*)?$")
ENV_TEMPLATE = re.compile(r"\.(example|sample|template)$")
# Deleting or moving these counts as deleting a test; snapshots, JSON and fixtures do not.
TEST_CODE = re.compile(r"(?i)\.(py|pyw|js|jsx|mjs|cjs|ts|tsx|mts|cts|go|rs|java|kt|kts|scala|groovy|rb|php|cs|fs|vb|"
                       r"swift|m|mm|c|cc|cpp|cxx|h|hpp|ex|exs|erl|clj|cljs|dart|lua|pl|r|jl|sh|bash|bats|ps1|vue|"
                       r"svelte|feature)$")
NOT_TEST_CODE = re.compile(r"(?i)(^|/)(fixtures?|__fixtures__|__snapshots__|snapshots|testdata|__mocks__)/")
# Lines that neutralise a check, in well-known places only.
WORKFLOW = re.compile(r"(^|/)\.github/workflows/[^/]+\.ya?ml$", re.I)
WORKFLOW_SOFT = re.compile(r"\|\|\s*true\b|\bcontinue-on-error:\s*true\b")
TEST_RUNNER = re.compile(r"(?i)\b(?:pytest|py\.test|jest|vitest|mocha|tox|nox|unittest|(?:npm|yarn|pnpm)\s+(?:run\s+)?"
                         r"test|go\s+test|cargo\s+test|make\s+(?:test|check))\b")
PYTEST_CONFIG = re.compile(r"(^|/)(pytest\.ini|setup\.cfg|pyproject\.toml|tox\.ini)$", re.I)
PYTEST_DROP = re.compile(r"--(?:deselect|ignore|ignore-glob)(?:=|\s+)([^\s\"',\]]+)")
JS_TEST_CONFIG = re.compile(r"(^|/)(jest|vitest)\.config\.[cm]?[jt]s$", re.I)
JS_TEST_DROP = re.compile(r"\btestPathIgnorePatterns\b|\bexclude\s*:")
_STEP_WINDOW = 8  # at most this many new-side lines around a workflow line, within the same step
STEP_START = re.compile(r"^\s*-\s")                         # a new step (or list item) in the YAML
SINGLE_LINE_RUN = re.compile(r"^\s*(?:-\s+)?run:\s*[^|>\s]")  # `run: cmd`, not the `run: |` block opener

FIXES = {
    "secret": ("possible secret in an added line",
               "Remove the value, read it from the environment or a secret store, and rotate it if it was ever committed."),
    "secret-history": ("possible secret in a commit of the range that would be published",
                       "Rewrite the branch so no commit contains it (a later deleting commit is not enough), and rotate it."),
    "env-file": (".env file with a secret value",
                 "Do not commit it: keep a .env.example with placeholders and add .env to .gitignore."),
    "test-skipped": ("test skipped or isolated",
                     "Remove the marker and make the test pass by fixing the code under test."),
    "test-deleted": ("test file deleted", "Restore the test file and fix the code it tests."),
    "test-moved": ("test file moved out of the tests", "Move it back under the tests."),
    "check-changed": ("change to a file the check command runs",
                      "Revert the change to the check's entry point and fix the code instead."),
    "check-weakened": ("line that neutralises the check (|| true, continue-on-error, deselected or ignored tests)",
                       "Remove it and fix the failing step or tests instead."),
}
# Findings that are the same problem for a person granting an exception.
_FAMILY = {"secret-history": "secret", "env-file": "secret"}


@dataclass
class Finding:
    rule: str
    file: str
    line: int
    message: str
    fix: str
    severity: str = "blocker"
    allowed: bool = False
    fingerprint: str = ""

    @property
    def location(self) -> str:
        return "%s:%d" % (self.file, self.line) if self.line else (self.file or "?")

    @property
    def short_id(self) -> str:
        return self.fingerprint[:8]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["location"] = self.location
        d["id"] = self.short_id
        return d


def _norm(text: Optional[str]) -> str:
    return " ".join((text or "").split())


def fingerprint(rule: str, path: str, content: str = "", following: str = "", version: str = "") -> str:
    """Identity of a finding for a one-time exception, never its line number:

    - a line finding: the rule family, the file, the marked line and the next non-empty line (normally the test it
      skips), so the same marked line placed above another test needs its own exception;
    - a file finding: the rule, the file and ``version``, the id of the file's new content (or "deleted"), so an
      exception for one change does not cover later changes to the same file."""
    raw = "\0".join((_FAMILY.get(rule, rule), path or "", _norm(content), _norm(following), version or ""))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def finding(rule: str, path: str, line: int, detail: str = "", allowed: bool = False, content: str = "",
            following: str = "", version: str = "") -> Finding:
    message, fix = FIXES[rule]
    return Finding(rule, path or "", line, message + (" (%s)" % detail if detail else ""), fix, allowed=allowed,
                   fingerprint=fingerprint(rule, path, content or detail, following, version))


# ─── Line rules ──────────────────────────────────────────────────────────────

def plausible_secret(value: str, allow_spaces: bool = False) -> bool:
    """False for values that are clearly not secrets: identifiers, placeholders, UUIDs, references."""
    value = (value or "").strip()
    if not value or re.fullmatch(r"[a-z_]+", value) or UUID.match(value) or PLACEHOLDER.search(value):
        return False
    if not allow_spaces and (re.search(r"\s", value) or ":" in value):
        return False
    return True


FICTITIOUS = re.compile(r"(?i)(synthetic|fake|dummy|example)[-_]")


def _generated_looking(value: str) -> bool:
    return (plausible_secret(value) and not FICTITIOUS.match(value) and len(value) >= 16
            and bool(re.search(r"[a-z]", value))
            and bool(re.search(r"[A-Z]", value)) and bool(re.search(r"\d", value)))


def _url_secret(text: str) -> bool:
    for m in CREDENTIAL_URL.finditer(text):
        user, value, host = m.group("user"), m.group("value"), m.group("host")
        if EXAMPLE_HOST.search(host) or value.startswith("$") or PLACEHOLDER.search(value):
            continue
        if value.lower() in ("password", "pass", "passwd", "secret", "pwd") or (user.lower(), value.lower()) == ("user", "password"):
            continue
        return True
    return False


def _value_rule(regex, text: str, allow_spaces: bool = True) -> bool:
    return any(plausible_secret(m.group("value"), allow_spaces) for m in regex.finditer(text))


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
    """``text`` is an added diff line, with its leading ``+``. In test files only real credential formats count."""
    if any(r.search(text) for r in SECRET_FORMATS):
        return True
    if path and TEST_PATH.search(path):
        # Fixtures are full of made-up passwords; only a long, mixed value that looks generated counts here.
        return any(_generated_looking(m.group("value")) for m in SECRET_KEY_VALUE.finditer(text))
    return (bool(BEARER.search(text))
            or _value_rule(SECRET_KEY_VALUE, text, allow_spaces=False)
            or _url_secret(text)
            or bool(path and IS_YAML.search(path) and (_value_rule(SECRET_YAML, text) or _value_rule(SECRET_LIST, text)))
            or bool(path and IS_CONFIG.search(path) and _value_rule(SECRET_CONFIG, text))
            or bool(path and IS_SHELL.search(path) and any(_value_rule(r, text) for r in SECRET_SHELL))
            or _jwt_secret(text))


def has_skip_marker(text: str) -> Optional[str]:
    """"skip" for a marker that switches a test off, "conditional" for a conditional skip, else None."""
    if any(r.search(text) for r in SKIPPED_TEST):
        return "skip"
    if any(r.search(text) for r in CONDITIONAL_SKIP):
        return "conditional"
    return None


def weakens_check(text: str, path: Optional[str], before: Iterable[str] = (), after: Iterable[str] = ()) -> bool:
    """``text`` neutralises a check. ``before``/``after`` are the new-side lines around it in the same hunk (nearest
    first), used to tell a test step from any other step and a test block from a coverage block."""
    if not path:
        return False
    before, after = list(before), list(after)
    if WORKFLOW.search(path):
        if not WORKFLOW_SOFT.search(text):
            return False
        if TEST_RUNNER.search(text):
            return True
        if SINGLE_LINE_RUN.search(text):
            return False  # `- run: docker rm -f old || true`: that line is the whole command
        # continue-on-error, or a line inside a `run: |` block: look at the rest of the same step only.
        step = []
        for t in before[:_STEP_WINDOW]:
            step.append(t)
            if STEP_START.match(t):
                break
        if not STEP_START.match(text):
            for t in after[:_STEP_WINDOW]:
                if STEP_START.match(t):
                    break
                step.append(t)
        return any(TEST_RUNNER.search(t) for t in step)
    if PYTEST_CONFIG.search(path):
        return any(TEST_PATH.search(v.strip("'\"")) or "test" in v.lower() for v in PYTEST_DROP.findall(text))
    if JS_TEST_CONFIG.search(path):
        if not JS_TEST_DROP.search(text) or re.search(r"(?i)coverage", text):
            return False
        for t in before[:8]:  # the nearest enclosing key decides: coverage { exclude } is not about tests
            if re.search(r"(?i)\bcoverage\b", t):
                return False
            if re.search(r"\btest\s*:", t):
                break
        return True
    return False


def is_test_path(path: str) -> bool:
    return bool(TEST_PATH.search((path or "").replace("\\", "/")))


def is_test_code(path: str) -> bool:
    """A test file whose deletion switches tests off: code under the tests, not snapshots, JSON or fixtures."""
    path = (path or "").replace("\\", "/")
    return bool(TEST_PATH.search(path) and TEST_CODE.search(path) and not NOT_TEST_CODE.search(path))


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


_CHECK_EVERY = 2000  # lines between two looks at the clock


def _check_deadline(deadline: Optional[float]) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise GitTimeout("time budget exhausted while reading the diff")


def _iter_new_side(diff: str, deadline: Optional[float] = None):
    """Yield (path, line number in the new file, text with a one-character prefix, added?, hunk number) for every
    line of the new side: added lines (prefix +) and context lines (prefix space).

    Hunk lengths are tracked, so an added line whose content starts with "++ " is never taken for a file header.
    Combined diffs of merges (``--cc``, ``@@@`` hunks) carry one prefix column per parent."""
    path, line, new_left, old_left, ncols, hunk = None, 0, 0, 0, 1, 0
    for count, text in enumerate(diff.splitlines()):
        if count % _CHECK_EVERY == 0:
            _check_deadline(deadline)
        if (new_left > 0 or old_left > 0) and text[:1] in (" ", "+", "-", "\\", ""):
            if text.startswith("\\"):  # "\ No newline at end of file"
                continue
            prefix, body = text[:ncols], text[ncols:]
            if "-" in prefix:
                old_left -= 1
                continue
            added = "+" in prefix
            if not added:
                old_left -= 1
            yield path, line, ("+" if added else " ") + body, added, hunk
            new_left -= 1
            line += 1
            continue
        new_left = old_left = 0
        if text.startswith("+++ "):
            path = _diff_path(text)
            continue
        m = _HUNK.match(text)
        if m:
            hunk += 1
            ncols = len(m.group(1)) - 1
            for sign, start, count in re.findall(r"([-+])(\d+)(?:,(\d+))?", m.group(2)):
                n = int(count) if count else 1
                if sign == "+":
                    line, new_left = int(start), n
                elif ncols == 1:
                    old_left = n


def added_from_name_status(name_status: str) -> list:
    """Paths that ``git diff --name-status`` reports as added (new files)."""
    out = []
    for row in name_status.splitlines():
        parts = row.split("\t")
        if len(parts) >= 2 and parts[0] == "A":
            out.append(unquote_path(parts[1]))
    return out


def _iter_added(diff: str, deadline: Optional[float] = None):
    """Yield (path, line number in the new file, added text with a single leading +)."""
    for path, line, text, added, _hunk in _iter_new_side(diff, deadline):
        if added:
            yield path, line, text


def next_nonempty(lines: Iterable[str]) -> str:
    """The first non-blank line of ``lines`` (the test a marker sits on), normalised."""
    for l in lines:
        if l.strip():
            return _norm(l)
    return ""


def _line_finding(path, line, text, history: bool = False, new_files=frozenset(), before=(), after=(),
                  version_of: Optional[Callable[[str], str]] = None) -> Optional[Finding]:
    allowed, content = MARKER in text, text[1:]
    if has_secret(text, path):
        rule = "secret-history" if history else ("env-file" if _is_env_file(path) else "secret")
        return finding(rule, path, line, allowed=allowed, content=content)
    if history:
        return None
    kind = None if path and DOCS.search(path) else has_skip_marker(text)
    if kind == "skip" or (kind == "conditional" and path not in new_files):
        return finding("test-skipped", path, line, allowed=allowed, content=content, following=next_nonempty(after))
    if weakens_check(text, path, before, after):
        return finding("check-weakened", path, line, allowed=allowed, content=content,
                       version=version_of(path) if version_of else "")
    return None


def history_secrets(history_diff: str, deadline: Optional[float] = None) -> list:
    """Secrets in the per-commit patches of a range (``git log -p --cc``)."""
    found = []
    for path, line, text in _iter_added(history_diff, deadline):
        f = _line_finding(path, line, text, history=True)
        if f:
            found.append(f)
    return found


def detect(diff: str, deleted: Iterable[str] = (), history: str = "", renamed: Iterable = (),
           allowed_paths: Iterable[str] = (), new_files: Iterable[str] = (),
           version_of: Optional[Callable[[str], str]] = None, deadline: Optional[float] = None) -> list:
    """Blockers in a unified diff, the deleted and renamed paths and, optionally, the per-commit history.
    ``new_files`` are files the change adds (a conditional skip in a new test file is legitimate);
    ``version_of(path)`` identifies a file's new content for file-level exceptions."""
    allowed_paths, new_files = set(allowed_paths or ()), frozenset(new_files or ())
    version = version_of or (lambda p: "")
    rows = list(_iter_new_side(diff, deadline))
    found = []
    for i, (path, line, text, added, hunk) in enumerate(rows):
        if i % _CHECK_EVERY == 0:
            _check_deadline(deadline)
        if not added:
            continue
        before = [r[2][1:] for r in reversed(rows[max(0, i - 8):i]) if r[4] == hunk]
        after = [r[2][1:] for r in rows[i + 1:i + 9] if r[4] == hunk]
        f = _line_finding(path, line, text, new_files=new_files, before=before, after=after, version_of=version)
        if f:
            found.append(f)
    for path in deleted:
        if is_test_code(path):
            found.append(finding("test-deleted", path, 0, allowed=path in allowed_paths, version="deleted"))
    for old, new in renamed:
        if is_test_code(old) and not TEST_PATH.search(new):
            found.append(finding("test-moved", old, 0, "to %s" % new, allowed=old in allowed_paths,
                                 version=new + "@" + version(new)))
    # A secret in the history is reported even when the final diff already has another finding at that place.
    seen = {(f.file, f.line) for f in found if f.rule in ("secret", "env-file")}
    found += [f for f in history_secrets(history, deadline) if (f.file, f.line) not in seen]
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


def scripts_of(package_json: Optional[str]):
    """The ``scripts`` of a package.json text, or None when it cannot be read."""
    try:
        data = json.loads(package_json or "")
    except ValueError:
        return None
    return data.get("scripts") if isinstance(data, dict) else None


def check_changed(command: Optional[str], paths: Iterable[str], is_file: Callable[[str], bool],
                  allowed_paths: Iterable[str] = (), protected: Iterable[str] = (),
                  contents: Optional[Callable[[str], tuple]] = None,
                  version_of: Optional[Callable[[str], str]] = None, labels: Optional[dict] = None) -> list:
    """One blocker per file the base's check runs (plus ``protected`` ones) that the change touches. For
    package.json only its ``scripts`` count; ``contents(path)`` returns (base text, new text) to compare them."""
    paths, allowed_paths = set(paths), set(allowed_paths or ())
    targets = sorted(set(check_files(command, is_file)) | set(protected))

    def touched(p):
        if p not in paths:
            return False
        if p.rsplit("/", 1)[-1] == "package.json" and contents is not None:
            old, new = contents(p)
            before, after = scripts_of(old), scripts_of(new)
            return before is None or after is None or before != after
        return True

    def detail(p):
        if p in (labels or {}):
            return labels[p]
        return "Foreman's own configuration" if p == CONFIG_FILE else "check: `%s`" % command

    return [finding("check-changed", p, 0, detail(p), allowed=p in allowed_paths,
                    version=version_of(p) if version_of else "") for p in targets if touched(p)]


# ─── Git ─────────────────────────────────────────────────────────────────────

class GitError(RuntimeError):
    pass


class GitTimeout(GitError):
    pass


_DIFF_OPTS = ("--no-color", "--no-ext-diff", "--no-textconv", "--src-prefix=a/", "--dst-prefix=b/")
_MAX_UNTRACKED_FILES = 500
_MAX_UNTRACKED_BYTES = 512 * 1024


class Repo:
    """A git working tree, with an optional deadline shared by every git call (the hook has a time budget)."""

    def __init__(self, root: str, budget: Optional[float] = None, deadline: Optional[float] = None):
        """``deadline`` is a ``time.monotonic()`` instant shared with other work; ``budget`` starts a new one."""
        self.root = root
        self.deadline = deadline if deadline is not None else (time.monotonic() + budget if budget else None)
        self._empty_tree = None

    def git(self, *args: str, ok_codes=(0,), stdin: bytes = b"") -> str:
        timeout = None
        if self.deadline is not None:
            timeout = self.deadline - time.monotonic()
            if timeout <= 0:
                raise GitTimeout("time budget exhausted before `git %s`" % args[0])
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", LC_ALL="C")
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            r = subprocess.run(["git", "-c", "core.quotePath=false", "-c", "log.showSignature=false",
                                "-c", "color.ui=false", *args], cwd=self.root, input=stdin,
                               capture_output=True, timeout=timeout, env=env, **kwargs)
        except subprocess.TimeoutExpired:
            raise GitTimeout("`git %s` timed out" % args[0])
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


def find_repo(path: str, deadline: Optional[float] = None) -> Optional[str]:
    """The top level of the git working tree that contains ``path`` (a file or a directory), or None."""
    p = os.path.abspath(path or ".")
    while p and not os.path.isdir(p):
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent
    try:
        top = Repo(p, budget=5, deadline=deadline).git("rev-parse", "--show-toplevel").strip()
    except GitTimeout:
        raise  # out of time is not "not a repository"
    except GitError:
        return None
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
    notes: list = field(default_factory=list)  # non-blocking: SARIF results below the threshold, stale reports
    errors: list = field(default_factory=list)  # a SARIF report the base's config names that cannot be read: no verdict

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
                "blockers": [f.to_dict() for f in self.blockers], "allowed": [f.to_dict() for f in self.allowed],
                "notes": [f.to_dict() for f in self.notes], "errors": list(self.errors)}


def format_findings(findings: Iterable[Finding], indent: str = "  ") -> str:
    lines = []
    for f in findings:
        lines.append("%s[%s] %s  %s" % (indent, f.rule, f.location, f.message))
        lines.append("%s    fix: %s" % (indent, f.fix))
    return "\n".join(lines)


def config_at(repo: Repo, rev: Optional[str]) -> dict:
    """The parsed .foreman.json *at the base* (empty when absent or unreadable), so a change cannot redefine what
    gates it."""
    raw = repo.show(rev, CONFIG_FILE) if rev else None
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def check_command_at(repo: Repo, rev: Optional[str], explicit: Optional[str] = None) -> Optional[str]:
    """The check command: the explicit one, else the ``check`` key of .foreman.json *at the base*, so a change
    cannot redefine its own check."""
    if explicit:
        return explicit
    value = config_at(repo, rev).get("check")
    return value if isinstance(value, str) and value.strip() else None


def _check_findings(repo: Repo, base_rev: Optional[str], check: Optional[str], paths, allowed_paths,
                    new_text: Callable[[str], Optional[str]], version_of: Callable[[str], str]) -> list:
    if not base_rev:
        return []
    is_file = repo.is_file_at(base_rev)
    protected = [CONFIG_FILE] if is_file(CONFIG_FILE) else []
    # A report the base's configuration points to is part of the gate: editing it (adding a suppression) is rigging.
    reports = [p for p in _config_sarif_paths(config_at(repo, base_rev)) if p not in protected and is_file(p)]
    protected += reports
    if not check and not protected:
        return []
    return check_changed(check, paths, is_file, allowed_paths, protected,
                         contents=lambda p: (repo.show(base_rev, p), new_text(p)), version_of=version_of,
                         labels={p: "SARIF report that gates the change" for p in reports})


# ─── SARIF sources ───────────────────────────────────────────────────────────

def _config_sarif_paths(config: dict, outside: Optional[list] = None) -> list:
    """The repository-relative, forward-slash paths of the ``sarif`` key (a string or a list of strings). A path that
    leaves the repository (absolute, ``..``) is dropped, and appended to ``outside`` when the caller wants it."""
    value = config.get("sarif")
    value = [value] if isinstance(value, str) else value
    out = []
    for p in value if isinstance(value, list) else []:
        if not (isinstance(p, str) and p.strip()):
            continue
        norm = posixpath.normpath(p.strip().replace("\\", "/"))
        if norm.startswith("/") or norm == ".." or norm.startswith("../") or re.match(r"^[A-Za-z]:", norm):
            if outside is not None:
                outside.append(p.strip()[:120])
        else:
            out.append(norm)
    return out


def _sarif_paths(repo: Repo, base_rev: Optional[str], explicit=()) -> list:
    """Absolute paths of every SARIF report this scan reads (configured at the base, plus explicit)."""
    return ([os.path.join(repo.root, *p.split("/")) for p in _config_sarif_paths(config_at(repo, base_rev))]
            + [os.path.abspath(p) for p in explicit])


def sarif_scope_of(config: dict) -> str:
    return config["sarif_scope"] if config.get("sarif_scope") in ("changed", "all") else "changed"


def sarif_findings(repo: Repo, base_rev: Optional[str], explicit=(), threshold: Optional[float] = None,
                   newest: Optional[float] = None, scope: Optional[str] = None, changed=None) -> tuple:
    """(blockers, notes, errors) from SARIF reports: the ``sarif`` / ``sarif_threshold`` / ``sarif_scope`` keys of
    .foreman.json at the base (files read from the working tree, relative to the repository), plus ``explicit`` paths.
    With the scope ``changed`` (the default) only results in ``changed`` files, or new or updated ones, can block.
    A report that cannot be read is an *error* (the caller must not report CLEAN), not a note, and so is a path that
    leaves the repository. A bad ``sarif_threshold`` is a note and the default applies. A hit of the time budget raises
    GitTimeout, like every other step."""
    from . import sarif
    config, outside = config_at(repo, base_rev), []
    named = [os.path.join(repo.root, *p.split("/")) for p in _config_sarif_paths(config, outside)]
    errors = ["could not read the SARIF report %s named in %s: the path leaves the repository" % (p, CONFIG_FILE)
              for p in outside]
    given = [os.path.abspath(p) for p in explicit]
    notes = []
    if not (named or given):
        return [], notes, errors
    if threshold is None:
        threshold = sarif.DEFAULT_THRESHOLD
        if "sarif_threshold" in config:
            try:
                threshold = sarif.parse_threshold(config["sarif_threshold"])
            except ValueError as e:
                notes.append(sarif.note("sarif:unreadable", CONFIG_FILE,
                                        "ignoring sarif_threshold, using %s: %s" % (threshold, e)))
    scope = scope or sarif_scope_of(config)
    scoped = None if scope == "all" else (changed if changed is not None else ())
    _check_deadline(repo.deadline)
    blockers, seen = [], set()
    for paths, where in ((named, " named in " + CONFIG_FILE), (given, "")):
        paths = [p for p in dict.fromkeys(paths) if p not in seen]
        seen.update(paths)
        result = sarif.collect(paths, repo.root, threshold, newest, scoped, repo.deadline, unreadable="error")
        blockers += result.blockers
        notes += result.notes
        errors += ["could not read the SARIF report %s%s: %s" % (label, where, reason)
                   for label, reason in result.errors]
    return blockers, notes, errors


def compact_notes(notes) -> str:
    """One line for the non-blocking SARIF notes: how many, and the first two."""
    notes = list(notes or [])
    if not notes:
        return ""
    shown = "; ".join("%s: %s" % (n.location, n.message) for n in notes[:2])
    more = " (+%d more)" % (len(notes) - 2) if len(notes) > 2 else ""
    return "SARIF: %d note(s), not blocking: %s%s" % (len(notes), shown, more)


def sarif_paths_at_base(repo: Repo) -> list:
    """The repository-relative paths of the reports the base's .foreman.json names (the base is the merge-base with
    the default branch, else HEAD): the files an agent must not write."""
    base, _label = repo.base_ref()
    return _config_sarif_paths(config_at(repo, base or ("HEAD" if repo.has_head() else None)))


def _commit_time(repo: Repo, *revs: str) -> Optional[float]:
    out = repo.try_git("log", "-1", "--format=%ct", *revs)
    return float(out) if out and out.isdigit() else None


def _versions(repo: Repo, rev: Optional[str] = None, staged: bool = False) -> Callable[[str], str]:
    """``version(path)``: the git blob id of a file's new content (at ``rev``, in the index, or in the working
    tree), or "deleted". The same content gives the same id at commit and at push."""
    def version(path: str) -> str:
        if rev:
            blob = repo.try_git("rev-parse", "--verify", "-q", "%s:%s" % (rev, path))
        elif staged:
            blob = repo.try_git("rev-parse", "--verify", "-q", ":" + path)
        else:
            full = os.path.join(repo.root, *path.split("/"))
            blob = repo.try_git("hash-object", "--", path) if os.path.isfile(full) else None
        return blob or "deleted"
    return version


def _read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(_MAX_UNTRACKED_BYTES)
    except OSError:
        return None


def scan_range(repo: Repo, base: Optional[str], head: str = "HEAD", check: Optional[str] = None,
               extra_messages: str = "", scope: str = "range", base_label: Optional[str] = None,
               sarif=(), sarif_threshold: Optional[float] = None, sarif_scope: Optional[str] = None) -> Report:
    """What publishing ``base..head`` would publish: the final diff, plus every commit's patch for secrets. Without a
    base (a branch with no ancestor on the remote), the whole history of ``head``. SARIF reports (the base's
    .foreman.json ``sarif`` key, plus the explicit ``sarif`` paths) add their blockers and notes."""
    rev_range = "%s..%s" % (base, head) if base else head
    diff_from = base or repo.empty_tree
    name_status = repo.git("diff", "--name-status", "-M", *_DIFF_OPTS, diff_from, head)
    paths, deleted, renamed = paths_from_name_status(name_status)
    messages = repo.git("log", "--format=%B", rev_range) + "\n" + (extra_messages or "")
    allowed_paths = allowed_paths_in(messages)
    version_of = _versions(repo, rev=head)
    findings = detect(repo.git("diff", "-M", *_DIFF_OPTS, diff_from, head), deleted,
                      history=repo.git("log", "-p", "--cc", *_DIFF_OPTS, "--format=", rev_range),
                      renamed=renamed, allowed_paths=allowed_paths, new_files=added_from_name_status(name_status),
                      version_of=version_of, deadline=repo.deadline)
    check = check_command_at(repo, base, check)
    findings += _check_findings(repo, base, check, paths, allowed_paths, lambda p: repo.show(head, p), version_of)
    blockers, notes, errors = sarif_findings(repo, base, sarif, sarif_threshold, _commit_time(repo, rev_range),
                                             sarif_scope, paths)
    report = Report(repo.root, scope, base, base_label, repo.try_git("rev-parse", head), check, findings + blockers)
    report.notes, report.errors = notes, errors
    return report


def _untracked_diff(repo: Repo) -> tuple:
    """Untracked (not ignored) files as a synthetic diff of additions, and their paths."""
    out = repo.git("ls-files", "--others", "--exclude-standard", "-z")
    files = [p for p in out.split("\0") if p][:_MAX_UNTRACKED_FILES]
    parts = []
    for path in files:
        _check_deadline(repo.deadline)
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
                  extra_messages: str = "", scope: str = "worktree", sarif=(),
                  sarif_threshold: Optional[float] = None, sarif_scope: Optional[str] = None) -> Report:
    """The uncommitted changes against HEAD: staged and unstaged (or only staged), plus untracked files."""
    has_head = repo.has_head()
    base = "HEAD" if has_head else repo.empty_tree
    cached = ("--cached",) if staged_only else ()
    name_status = repo.git("diff", "--name-status", "-M", *cached, *_DIFF_OPTS, base)
    paths, deleted, renamed = paths_from_name_status(name_status)
    new_files = added_from_name_status(name_status)
    diff = repo.git("diff", "-M", *cached, *_DIFF_OPTS, base)
    if include_untracked and not staged_only:
        extra, files = _untracked_diff(repo)
        diff += "\n" + extra
        paths += files
        new_files += files
    allowed_paths = allowed_paths_in(extra_messages)
    version_of = _versions(repo, staged=staged_only)
    findings = detect(diff, deleted, renamed=renamed, allowed_paths=allowed_paths, new_files=new_files,
                      version_of=version_of, deadline=repo.deadline)
    head_rev = "HEAD" if has_head else None
    check = check_command_at(repo, head_rev, check)
    if staged_only:
        new_text = lambda p: repo.try_git("show", ":" + p)
    else:
        new_text = lambda p: _read_text(os.path.join(repo.root, *p.split("/")))
    findings += _check_findings(repo, head_rev, check, paths, allowed_paths, new_text, version_of)
    # The newest change is the last commit or the newest edited file, whichever is later (the reports themselves
    # do not count: an untracked report is not a change it gates).
    newest = _commit_time(repo, "HEAD") if has_head else None
    reports = {os.path.normcase(os.path.abspath(p)) for p in _sarif_paths(repo, head_rev, sarif)}
    for p in paths:
        full = os.path.join(repo.root, *p.split("/"))
        try:
            if os.path.normcase(os.path.abspath(full)) not in reports:
                newest = max(newest or 0, os.path.getmtime(full))
        except OSError:
            pass  # deleted
    blockers, notes, errors = sarif_findings(repo, head_rev, sarif, sarif_threshold, newest, sarif_scope, paths)
    report = Report(repo.root, scope, repo.try_git("rev-parse", "HEAD") if has_head else None, "HEAD",
                    None, check, findings + blockers)
    report.notes, report.errors = notes, errors
    return report


def scan_branch(repo: Repo, check: Optional[str] = None, sarif=(), sarif_threshold: Optional[float] = None,
                sarif_scope: Optional[str] = None) -> Report:
    """The current branch against the merge-base with the remote's default branch (or a local main/master)."""
    if not repo.has_head():
        return Report(repo.root, "branch", findings=[])
    base, label = repo.base_ref()
    if not base:
        return Report(repo.root, "branch", head=repo.try_git("rev-parse", "HEAD"), findings=[])
    return scan_range(repo, base, "HEAD", check=check, scope="branch", base_label=label, sarif=sarif,
                      sarif_threshold=sarif_threshold, sarif_scope=sarif_scope)


# ─── CI entry point ──────────────────────────────────────────────────────────

def _threshold_arg(value: str) -> float:
    from . import sarif
    try:
        return sarif.parse_threshold(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m foreman.detector",
                                     description="Deterministic test-integrity and secret check for a git range.")
    parser.add_argument("base", help="base revision (for a pull request: the merge-base with the target branch)")
    parser.add_argument("head", nargs="?", default="HEAD", help="head revision (default: HEAD)")
    parser.add_argument("--check", help="the check command of the base; default: `check` in the base's .foreman.json")
    parser.add_argument("--repo", default=".", help="path inside the repository (default: the current directory)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--sarif", action="append", default=[], metavar="FILE",
                        help="a SARIF 2.1.0 report to read as a source of findings (repeatable); unreadable = exit 2")
    parser.add_argument("--sarif-threshold", metavar="LEVEL", type=_threshold_arg,
                        help="error (default, 7.0), warning (4.0) or a number 0-10: results at or above it block")
    parser.add_argument("--sarif-scope", choices=("changed", "all"),
                        help="changed (default): only results in files the change touches, or new ones, block; "
                             "all: every result can block")
    parser.add_argument("--strict", action="store_true",
                        help="findings marked %s count as blockers (exit 1) instead of being listed for review" % MARKER)
    args = parser.parse_args(argv)
    root = find_repo(args.repo)
    if not root:
        print("foreman: %s is not inside a git repository" % args.repo, file=sys.stderr)
        return 2
    try:
        report = scan_range(Repo(root), args.base, args.head, check=args.check,
                            sarif=[os.path.abspath(p) for p in args.sarif], sarif_threshold=args.sarif_threshold,
                            sarif_scope=args.sarif_scope)
    except GitError as e:
        print("foreman: %s" % e, file=sys.stderr)
        return 2
    blocking = report.blockers + (report.allowed if args.strict else [])
    marked = [] if args.strict else report.allowed
    for err in report.errors:  # a report that was asked for and cannot be read: the run says so and fails
        print("foreman: %s" % err, file=sys.stderr)
    out = sys.stderr if args.json else sys.stdout
    if os.environ.get("GITHUB_ACTIONS"):
        for f in report.allowed:
            print(annotation("error" if args.strict else "warning", f), file=out)
    if args.json:
        print(json.dumps(dict(report.to_dict(), strict=args.strict), indent=2))
    else:
        label = "INCOMPLETE" if report.errors and not blocking else ("BLOCKED" if blocking else report.verdict)
        print("foreman: %s (%d blocker(s), %d marked %s)" % (label, len(blocking), len(marked), MARKER))
        if blocking:
            print(format_findings(blocking))
        if marked:
            print("Marked %s by the author; they do not fail this run, review them (or use --strict):" % MARKER)
            print(format_findings(marked))
        if report.notes:
            print("Notes (they do not block):")
            for n in report.notes:
                print("  [%s] %s  %s" % (n.rule, n.location, n.message))
    return 2 if report.errors else (1 if blocking else 0)


def _escape_annotation(text: str, prop: bool = False) -> str:
    text = text.replace("%", "%25").replace(chr(13), "%0D").replace(chr(10), "%0A")
    return text.replace(":", "%3A").replace(",", "%2C") if prop else text


def annotation(level: str, f: Finding) -> str:
    """A GitHub Actions workflow command that shows the finding on the pull request's files."""
    props = []
    if f.file:
        props.append("file=" + _escape_annotation(f.file, True))
        if f.line:
            props.append("line=%d" % f.line)
    props.append("title=" + _escape_annotation("foreman: " + f.rule, True))
    text = "%s (marked %s; a person must review it)" % (f.message, MARKER)
    return "::%s %s::%s" % (level, ",".join(props), _escape_annotation(text))


if __name__ == "__main__":
    sys.exit(main())
