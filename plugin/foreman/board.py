"""The board: ``/foreman`` with no arguments, and the ``use``, ``prs``, ``issues``, ``verdict``, ``merge`` and
``reject`` subcommands.

Pull requests and issues come from the GitHub CLI (``gh``), run as a subprocess with its own login: Foreman never
reads its token or its files. Without ``gh``, a login or a GitHub remote, the board shows the local branches and
``verdict <branch>`` still works. A merge or a comment is written only when the user types ``/foreman merge`` or
``/foreman reject``, and it runs through Hermes's own terminal tool (``ctx.dispatch_tool``), never from a bare
subprocess. Everything here is plain text that reads the same in a terminal, the Desktop app and messaging.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from . import detector, gate, grants
from .detector import MARKER, GitError, GitTimeout, Repo
from .verdicts import BLOCKED, CLEAN, INCOMPLETE, NEEDS_OK, verdict_of

logger = logging.getLogger(__name__)

GH_TIMEOUT = 20.0           # one read-only gh call
GH_DIFF_TIMEOUT = 40.0      # gh pr diff of a large pull request
MERGE_TIMEOUT = 180         # the terminal tool's timeout for gh pr merge / comment / close
BOARD_BUDGET_SECONDS = 60.0
MAX_PRS = 8
MAX_ISSUES = 8
MAX_BRANCHES = 8
MAX_LISTED_REASONS = 15
WIDTH = 78                  # a line of the board never goes past this
STORE_FILE = "foreman-board.json"
PIN_TTL_SECONDS = 30 * 24 * 3600
MAX_RECENT = 10
PINNED = "pinned"

gate.HOW.setdefault(PINNED, "the repository pinned with /foreman use")

USE_HINT = "Pick a repository with `/foreman use` (or `/foreman use <path>`)."
PR_FIELDS = "number,title,headRefName,isDraft,author,url,closingIssuesReferences,statusCheckRollup,mergeable,updatedAt"
ISSUE_FIELDS = "number,title,labels,updatedAt"
VIEW_FIELDS = ("number,title,url,state,isDraft,headRefName,headRefOid,baseRefName,baseRefOid,closingIssuesReferences,"
               "statusCheckRollup,mergeable,commits,files")

# ─── Hermes context (bound in register) ──────────────────────────────────────

_CTX = None


def bind(ctx) -> None:
    """Keep the plugin context: ``ask_choice`` for ``/foreman use`` and ``dispatch_tool`` for merge and reject."""
    global _CTX
    _CTX = ctx


# ─── gh, as a subprocess with its own login ──────────────────────────────────

# Tests replace this with a fake: fn(args: list, cwd: str, timeout: float) -> (returncode, stdout, stderr).
GH_RUNNER: Optional[Callable] = None


class GhError(Exception):
    """``gh`` could not answer. ``missing`` is True when GitHub is not usable here at all (no gh, no login, no
    GitHub remote), False for a failure of one call (a timeout, an unknown pull request)."""

    def __init__(self, reason: str, missing: bool = False):
        super().__init__(reason)
        self.reason, self.missing = reason, missing


def _default_runner(args: list, cwd: str, timeout: float) -> tuple:
    exe = shutil.which("gh")
    if not exe:
        raise FileNotFoundError("gh")
    env = dict(os.environ, GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1", GH_SPINNER_DISABLED="1",
               NO_COLOR="1", CLICOLOR="0")
    kwargs = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {}
    r = subprocess.run([exe, *args], cwd=cwd, capture_output=True, timeout=timeout, env=env,
                       stdin=subprocess.DEVNULL, **kwargs)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def _classify(message: str, args: list) -> GhError:
    low = (message or "").lower()
    if "auth login" in low or "not logged" in low or "authentication" in low:
        return GhError("gh is not logged in to GitHub (run `gh auth login` in a terminal)", missing=True)
    if any(s in low for s in ("no git remote", "none of the git remotes", "not a git repository",
                              "could not determine base repo", "unable to determine", "no default remote")):
        return GhError("this repository has no GitHub remote", missing=True)
    last = next((l.strip() for l in reversed((message or "").splitlines()) if l.strip()), "no output")
    return GhError("`gh %s` failed: %s" % (" ".join(args[:2]), last[:200]))


def gh(args: list, cwd: str, timeout: float = GH_TIMEOUT) -> str:
    runner = GH_RUNNER or _default_runner
    try:
        rc, out, err = runner(list(args), cwd, timeout)
    except FileNotFoundError:
        raise GhError("gh (the GitHub CLI) is not installed", missing=True)
    except subprocess.TimeoutExpired:
        raise GhError("`gh %s` did not answer within %d s" % (" ".join(args[:2]), timeout))
    except OSError as e:
        raise GhError("cannot run gh: %s" % e, missing=True)
    if rc != 0:
        raise _classify(err or out, list(args))
    return out


def gh_json(args: list, cwd: str, timeout: float = GH_TIMEOUT):
    out = gh(args, cwd, timeout)
    try:
        return json.loads(out or "null")
    except ValueError:
        raise GhError("`gh %s` did not return JSON" % " ".join(args[:2]))


# ─── Text helpers ────────────────────────────────────────────────────────────

def trim(text, width: int) -> str:
    one = " ".join(str(text or "").split())
    return one if len(one) <= width else one[:max(1, width - 3)].rstrip() + "..."


def trim_path(path: str, width: int) -> str:
    """A path that fits ``width``, keeping its end (the repository's own name)."""
    return path if len(path) <= width else "..." + path[-(width - 3):]


def _repo_of_url(url: str) -> str:
    m = re.match(r"https?://[^/]+/([^/]+/[^/]+)/(?:pull|issues)/\d+", url or "")
    return m.group(1) if m else ""


def closing_refs(pr: dict, name_with_owner: str = "") -> list:
    """The issues a pull request closes, as ``#4`` (same repository) or ``owner/repo#4``."""
    out = []
    for ref in pr.get("closingIssuesReferences") or []:
        if not isinstance(ref, dict) or not isinstance(ref.get("number"), int):
            continue
        where = _repo_of_url(ref.get("url", ""))
        if where and name_with_owner and where.lower() != name_with_owner.lower():
            out.append("%s#%d" % (where, ref["number"]))
        else:
            out.append("#%d" % ref["number"])
    return out


def _closed_numbers(prs: list, name_with_owner: str) -> dict:
    """Issue number (this repository) -> the open pull requests that close it."""
    out = {}
    for pr in prs:
        for ref in pr.get("closingIssuesReferences") or []:
            if not isinstance(ref, dict) or not isinstance(ref.get("number"), int):
                continue
            where = _repo_of_url(ref.get("url", ""))
            if not where or not name_with_owner or where.lower() == name_with_owner.lower():
                out.setdefault(ref["number"], []).append(pr.get("number"))
    return out


_PASSED = {"SUCCESS", "NEUTRAL", "SKIPPED"}


def ci_summary(rollup, conflicting: bool = False) -> str:
    """One phrase for a ``statusCheckRollup``: CI passing, failing (n of m), running, no checks, or unknown when
    GitHub's answer had no rollup at all. A pull request that conflicts gets no ``pull_request`` checks from GitHub
    (there is no merge commit to test), which is said."""
    if not isinstance(rollup, list):
        return "CI unknown (checks not read)"
    passed = failed = pending = 0
    for c in rollup:
        if not isinstance(c, dict):
            continue
        if c.get("__typename") == "StatusContext" or ("state" in c and "conclusion" not in c):
            state = str(c.get("state") or "").upper()
            if state == "SUCCESS":
                passed += 1
            elif state in ("PENDING", "EXPECTED", ""):
                pending += 1
            else:
                failed += 1
        elif str(c.get("status") or "").upper() != "COMPLETED":
            pending += 1
        elif str(c.get("conclusion") or "").upper() in _PASSED:
            passed += 1
        else:
            failed += 1
    total = passed + failed + pending
    if not total:
        return "no CI checks (none run while it conflicts)" if conflicting else "no CI checks"
    if failed:
        return "CI failing (%d of %d)" % (failed, total)
    if pending:
        return "CI running (%d of %d done)" % (passed, total)
    return "CI passing"


def _pr_lines(pr: dict, name_with_owner: str) -> list:
    head = "  #%-5s%s" % (pr.get("number", "?"), trim(pr.get("title"), WIDTH - 9))
    facts = [trim(pr.get("headRefName") or "?", 30)]
    if pr.get("isDraft"):
        facts.append("draft")
    conflicting = str(pr.get("mergeable") or "").upper() == "CONFLICTING"
    if conflicting:
        facts.append("conflicts")
    ci = ci_summary(pr.get("statusCheckRollup"))
    facts.append("no CI checks" if conflicting and ci.startswith("no CI") else ci)
    closes = closing_refs(pr, name_with_owner)
    facts.append("closes " + ", ".join(closes) if closes else "closes no issue")
    return [head, "       " + trim(" · ".join(facts), WIDTH - 7)]


def _issue_line(issue: dict, extra: str = "") -> str:
    labels = [l.get("name") for l in issue.get("labels") or [] if isinstance(l, dict) and l.get("name")]
    tail = ("  [%s]" % ", ".join(labels[:2]) if labels else "") + extra
    room = max(20, WIDTH - 9 - len(tail))
    return "  #%-5s%s%s" % (issue.get("number", "?"), trim(issue.get("title"), room), tail)


def _by_update(items: list) -> list:
    return sorted((i for i in items or [] if isinstance(i, dict)), key=lambda i: str(i.get("updatedAt") or ""),
                  reverse=True)


# ─── Which repository: pinned per session, then Foreman's usual resolution ───

_lock = threading.Lock()


def _store_path() -> str:
    return os.path.join(grants.store_dir(), STORE_FILE)


def _load_store() -> dict:
    try:
        with open(_store_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    pins = data.get("pins") if isinstance(data.get("pins"), dict) else {}
    recent = data.get("recent") if isinstance(data.get("recent"), list) else []
    return {"pins": {k: v for k, v in pins.items() if isinstance(k, str) and isinstance(v, dict)
                     and isinstance(v.get("path"), str)},
            "recent": [r for r in recent if isinstance(r, str)]}


def _save_store(data: dict) -> None:
    path = _store_path()
    fd, tmp = tempfile.mkstemp(prefix=".board-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _session(keys: tuple) -> str:
    return next((k for k in keys if isinstance(k, str) and k), "_")


def pinned(keys: tuple = ()) -> Optional[str]:
    with _lock:
        entry = _load_store()["pins"].get(_session(keys))
    if not entry or (entry.get("at") or 0) + PIN_TTL_SECONDS < time.time():
        return None
    return entry["path"]


def pin(root: str, keys: tuple = ()) -> None:
    with _lock:
        data, now = _load_store(), time.time()
        data["pins"] = {k: v for k, v in data["pins"].items() if (v.get("at") or 0) + PIN_TTL_SECONDS > now}
        data["pins"][_session(keys)] = {"path": root, "at": now}
        data["recent"] = [root] + [r for r in data["recent"] if os.path.normcase(r) != os.path.normcase(root)]
        data["recent"] = data["recent"][:MAX_RECENT]
        _save_store(data)


def recent() -> list:
    with _lock:
        return list(_load_store()["recent"])


def remember(root: str) -> None:
    """Add ``root`` to the recently used repositories without pinning it for any session."""
    with _lock:
        data = _load_store()
        data["recent"] = [root] + [r for r in data["recent"] if os.path.normcase(r) != os.path.normcase(root)]
        data["recent"] = data["recent"][:MAX_RECENT]
        _save_store(data)


# ─── --repo: a repository named in the command, only one Foreman already knows ───

_REPO_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_REMOTE_NAME = re.compile(r"[:/]([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$")


def remote_names(root: str) -> set:
    """``owner/name`` (lower case) of every remote of ``root``, read from the local git config: no network."""
    out = Repo(root, budget=5).try_git("remote", "-v") or ""
    names = set()
    for line in out.splitlines():
        parts = line.split()
        m = _REMOTE_NAME.search(parts[1]) if len(parts) >= 2 else None
        if m:
            names.add(m.group(1).lower())
    return names


def take_repo_option(words: list) -> tuple:
    """(the words without ``--repo X``, X or None, a usage problem or None)."""
    out, value, i = [], None, 0
    while i < len(words):
        w = words[i]
        if w == "--repo":
            if i + 1 >= len(words):
                return words, None, "Usage: --repo <owner/name or path of a repository you used with /foreman use>"
            value, i = words[i + 1], i + 2
            continue
        if w.startswith("--repo="):
            value, i = w[len("--repo="):], i + 1
            continue
        out.append(w)
        i += 1
    return out, value, None


def known_repository(value: str) -> tuple:
    """(root, None) for ``--repo <value>``, else (None, the reason). Only a repository Foreman already knows counts:
    one of the recently used ones (``/foreman use`` adds it), matched by its path or by its remote's
    ``owner/name``. A command that arrives from a chat can never point Foreman at any other directory."""
    value = (value or "").strip().strip('"').strip("'")
    known, spellings = [], {}  # a root as git gives it, and also as it was pinned (8.3 names, symlinked temp dirs)
    for r in recent():
        if os.path.isdir(r):
            root = detector.find_repo(r)
            if root:
                known.append(os.path.normpath(root))
                for spelt in (r, root):
                    spellings[os.path.normcase(os.path.normpath(spelt))] = os.path.normpath(root)
    refuse = ("Foreman: `--repo %s` is not a repository Foreman knows on this machine. Pin it once with "
              "`/foreman use <path>` where it lives; then `--repo` can name it." % trim(value, 60))
    if not value:
        return None, refuse
    path = os.path.expanduser(value)
    if os.path.isabs(path):  # compared as text first: a typed path is never opened unless it is a known root
        match = spellings.get(os.path.normcase(os.path.normpath(path)))
        return (match, None) if match else (None, refuse)
    if not _REPO_NAME.match(value):
        return None, refuse
    matches = [k for k in known if value.lower() in remote_names(k)]
    if len(matches) > 1:
        return None, ("Foreman: several known repositories have the remote %s; use `--repo <path>` instead: %s"
                      % (value, ", ".join(matches)))
    return (matches[0], None) if matches else (None, refuse)


def root_for(args: str, keys: tuple = (), platform: Optional[str] = None) -> tuple:
    """(the words without ``--repo X``, the repository root or None, the problem text or None): ``--repo`` through
    the validated resolver (only a repository Foreman already knows), else the session's repository."""
    words, repo_arg, problem = take_repo_option((args or "").split())
    if problem:
        return words, None, problem
    if repo_arg is not None:
        root, problem = known_repository(repo_arg)
        return words, root, problem
    root, _how_ = resolve(keys, platform)
    return words, root, None if root else _no_repository()


def _repo_suffix(args: str) -> str:
    """`` --repo X`` when the command named one, so a hint Foreman prints can be run as it is."""
    _words, value, _problem = take_repo_option((args or "").split())
    return " --repo %s" % value if value else ""


def resolve(keys: tuple = (), platform: Optional[str] = None) -> tuple:
    """(repository root, how it was chosen): the repository pinned for this session, else the first of Foreman's
    usual candidates (gate.locate) inside a repository; (None, None) when nothing qualifies."""
    p = pinned(keys)
    if p and os.path.isdir(p):
        root = detector.find_repo(p)
        if root:
            return root, PINNED
    where, how = gate.locate(*keys, platform=platform)
    if where:
        root = detector.find_repo(where)
        if root:
            return root, how
    return None, None


def _no_repository() -> str:
    return gate.NO_REPOSITORY_HERE


def _how(how: Optional[str]) -> str:
    return gate.HOW.get(how or "", how or "?")


# ─── /foreman use ────────────────────────────────────────────────────────────

def candidates(keys: tuple = (), platform: Optional[str] = None) -> list:
    """(root, why) of repositories worth offering: recently used ones, the repository around each of Foreman's
    candidate directories, and git repositories directly inside them. Never Hermes's own data."""
    homes, seen, out = gate.hermes_homes(), set(), []

    def add(root: Optional[str], why: str):
        if not root:
            return
        key = os.path.normcase(os.path.normpath(root))
        if key in seen or gate._hermes_data(root, root, homes):
            return
        seen.add(key)
        out.append((os.path.normpath(root), why))

    deadline = time.monotonic() + 15
    for r in recent():
        if os.path.isdir(r):
            try:
                add(detector.find_repo(r, deadline=deadline), "recent")
            except GitError:
                break
    for path, how in gate.cwd_candidates(*keys, platform=platform):
        try:
            add(detector.find_repo(path, deadline=deadline), "around " + _how(how))
        except GitError:
            break
        try:
            entries = sorted(os.scandir(path), key=lambda e: e.name.lower())[:300]
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_dir() and not e.name.startswith(".") and os.path.exists(os.path.join(e.path, ".git")):
                    add(e.path, "inside " + path)
            except OSError:
                continue
            if len(out) >= 15:
                return out
    return out[:15]


def cmd_use(args: str, keys: tuple = (), platform: Optional[str] = None) -> str:
    arg = args.strip().strip('"').strip("'")
    if arg and not (arg.isdigit() and not os.path.exists(arg)):
        path = os.path.expanduser(arg)
        if not os.path.isabs(path):
            where, _how_ = gate.locate(*keys, platform=platform)
            if not where:
                return "Foreman: give an absolute path: `/foreman use <path>`."
            path = os.path.join(where, path)
        root = detector.find_repo(path) if os.path.exists(path) else None
        if not root:
            return "Foreman: %s is not inside a git repository." % os.path.normpath(path)
        pin(root, keys)
        return _pinned_message(root)
    options = candidates(keys, platform)
    if not options:
        return "Foreman found no repository to offer here. Pin one with `/foreman use <path>`."
    current = pinned(keys)
    if arg:  # /foreman use 2: the second entry of the list Foreman printed
        n = int(arg)
        if not 1 <= n <= len(options):
            return "Foreman: there is no repository number %d. Run `/foreman use` to list them." % n
        pin(options[n - 1][0], keys)
        return _pinned_message(options[n - 1][0])
    ask = getattr(_CTX, "ask_choice", None)
    picked = None
    if callable(ask):
        choices = [{"value": root, "label": os.path.basename(root) or root,
                    "description": "%s (%s%s)" % (root, why, ", pinned now" if current and
                                                  os.path.normcase(current) == os.path.normcase(root) else "")}
                   for root, why in options]
        try:
            picked = ask("Which repository should Foreman use in this session?", choices)
        except Exception:
            logger.warning("foreman: ask_choice failed", exc_info=True)
            picked = None
    if picked and any(picked == root for root, _ in options):
        pin(picked, keys)
        return _pinned_message(picked)
    lines = ["Foreman: repositories you can pin for this session:"]
    for i, (root, why) in enumerate(options, 1):
        mark = "  <- pinned now" if current and os.path.normcase(current) == os.path.normcase(root) else ""
        lines.append("  %d. %s" % (i, root))
        lines.append("     %s%s" % (trim(why, WIDTH - 20), mark))
    lines.append("Type `/foreman use <number>` or `/foreman use <path>`.")
    return "\n".join(lines)


def _pinned_message(root: str) -> str:
    return ("Foreman: pinned %s for this session. `/foreman` shows its board; `/foreman use` picks another."
            % root)


# ─── GitHub snapshot ─────────────────────────────────────────────────────────

def snapshot(root: str) -> dict:
    """The repository's name, open pull requests and open issues, from three read-only gh calls in parallel."""
    calls = {
        "repo": ["repo", "view", "--json", "nameWithOwner,defaultBranchRef"],
        "prs": ["pr", "list", "--state", "open", "--limit", "50", "--json", PR_FIELDS],
        "issues": ["issue", "list", "--state", "open", "--limit", "100", "--json", ISSUE_FIELDS],
    }
    results, errors = {}, []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {name: pool.submit(gh_json, args, root) for name, args in calls.items()}
        for name, fut in futures.items():
            try:
                results[name] = fut.result()
            except GhError as e:
                errors.append(e)
    if errors:
        raise next((e for e in errors if e.missing), errors[0])
    repo = results["repo"] if isinstance(results["repo"], dict) else {}
    return {"name": repo.get("nameWithOwner") or "",
            "default_branch": (repo.get("defaultBranchRef") or {}).get("name") or "",
            "prs": _by_update(results["prs"] if isinstance(results["prs"], list) else []),
            "issues": _by_update(results["issues"] if isinstance(results["issues"], list) else [])}


def _local_has_github(root: str) -> Optional[str]:
    """A reason GitHub cannot be used, found without the network: no remote at all."""
    remotes = Repo(root, budget=5).try_git("remote")
    return None if remotes else "this repository has no remote"


# ─── Verdicts ────────────────────────────────────────────────────────────────

def _split(findings: list, repo_root: str) -> tuple:
    """(blockers, marked and waiting for a person, allowed by the person) as dicts; waiting ones are recorded."""
    findings = gate._dedupe(findings)
    blockers = [f for f in findings if not f.allowed]
    marked = [f for f in findings if f.allowed and not grants.is_granted(f.fingerprint)]
    granted = [f for f in findings if f.allowed and grants.is_granted(f.fingerprint)]
    if marked:
        try:
            grants.record_pending(marked, repo_root)
        except Exception:
            logger.warning("foreman: cannot record pending findings", exc_info=True)
    return ([f.to_dict() for f in blockers], [f.to_dict() for f in marked], [f.to_dict() for f in granted])


_OID = re.compile(r"[0-9a-f]{40}")


def _base_rev(repo: Repo, base_name: str) -> tuple:
    """(revision, label) of a pull request's base branch in the local clone, or (None, None)."""
    for ref in ("refs/remotes/origin/%s" % base_name, "refs/heads/%s" % base_name):
        if base_name and repo.try_git("rev-parse", "--verify", "-q", ref + "^{commit}"):
            return ref, ref.replace("refs/remotes/", "").replace("refs/heads/", "")
    return None, None


def pr_verdict(root: str, number: int) -> dict:
    """Foreman's verdict for pull request ``number``: from the local commits when the clone has its head (the full
    check, history included), else from GitHub's diff without touching the working tree."""
    v = {"kind": "pr", "number": number, "verdict": "UNKNOWN", "notes": [], "blockers": [], "marked": [],
         "allowed_by_user": [], "repo": root}
    try:
        view = gh_json(["pr", "view", str(number), "--json", VIEW_FIELDS], root)
    except GhError as e:
        v["error"], v["missing"] = e.reason, e.missing
        return v
    if not isinstance(view, dict):
        v["error"] = "gh returned no pull request"
        return v
    name = _repo_of_url(view.get("url", ""))
    v.update(title=view.get("title") or "", url=view.get("url") or "", name=name, state=view.get("state") or "",
             draft=bool(view.get("isDraft")), head=view.get("headRefName") or "", base=view.get("baseRefName") or "",
             head_oid=view.get("headRefOid") or "", closes=closing_refs(view, name),
             mergeable=str(view.get("mergeable") or "UNKNOWN").upper(),
             conflicts=str(view.get("mergeable") or "").upper() == "CONFLICTING")
    v["ci"] = ci_summary(view.get("statusCheckRollup"), conflicting=v["conflicts"])
    repo = Repo(root, budget=BOARD_BUDGET_SECONDS)
    oid = v["head_oid"]
    if not _OID.fullmatch(oid):
        v["error"] = "GitHub did not give the pull request's head commit"
        return v
    base_oid = view.get("baseRefOid") or ""
    try:
        if _OID.fullmatch(base_oid) and repo.try_git("cat-file", "-e", base_oid + "^{commit}") is not None:
            base_rev, base_label = base_oid, v["base"]  # GitHub's base, exactly
        else:
            base_rev, base_label = _base_rev(repo, v["base"])
            if base_rev:
                v["notes"].append("GitHub's latest `%s` is not in the local clone; the check command was read from "
                                  "the local `%s`, which may be older." % (v["base"], base_label))
        if base_rev and repo.try_git("cat-file", "-e", oid + "^{commit}") is not None:
            merge_base = repo.try_git("merge-base", oid, base_rev)
            if merge_base:
                report = detector.scan_range(repo, merge_base, oid, scope="pull request", base_label=base_label,
                                             sarif_at_head=True)
                v["how"], v["merge_base"] = "local", merge_base
                v["blockers"], v["marked"], v["allowed_by_user"] = _split(report.findings, root)
                v["check"] = report.check
                v["errors"] = list(dict.fromkeys(report.errors))
                v["sarif_notes"] = [n.to_dict() for n in report.notes]
                v["verdict"] = verdict_of(v["blockers"], v["errors"], v["marked"])
                return v
        try:
            diff = gh(["pr", "diff", str(number), "--color", "never"], root, timeout=GH_DIFF_TIMEOUT)
        except GhError as e:
            v["error"] = "cannot read the pull request's diff: %s" % e.reason
            return v
        try:  # the diff must belong to the commit that a merge would pin
            again = gh_json(["pr", "view", str(number), "--json", "headRefOid"], root)
        except GhError as e:
            v["error"] = "cannot confirm the pull request's head: %s" % e.reason
            return v
        if not isinstance(again, dict) or again.get("headRefOid") != oid:
            v["error"] = "the pull request changed while Foreman read it; run the command again"
            return v
        name_status = detector.name_status_from_diff(diff)
        listed = {p for row in name_status.splitlines() for p in row.split("\t")[1:]}
        # Every file GitHub lists counts, even if the diff text did not show it.
        extra = ["%s\t%s" % ("D" if f.get("changeType") == "DELETED" else "M", f["path"])
                 for f in view.get("files") or []
                 if isinstance(f, dict) and isinstance(f.get("path"), str) and f["path"] not in listed]
        name_status = "\n".join([name_status] + extra) if extra else name_status
        messages = "\n".join("%s\n%s" % (c.get("messageHeadline") or "", c.get("messageBody") or "")
                             for c in view.get("commits") or [] if isinstance(c, dict))
        reports = detector._config_sarif_paths(detector.config_at(repo, base_rev)) if base_rev else []
        v["errors"] = ["could not read the SARIF report %s named in %s: the pull request's head is not in the local "
                       "clone (fetch it)" % (p, detector.CONFIG_FILE) for p in reports]
        if base_rev:
            check = detector.check_command_at(repo, base_rev)
            findings = detector.findings_from_diff(diff, name_status, check=check, base_is_file=repo.is_file_at(base_rev),
                                                   base_text=lambda p: repo.show(base_rev, p), messages=messages,
                                                   deadline=repo.deadline)
            v["check"] = check
        else:
            findings = detector.findings_from_diff(diff, name_status, messages=messages, deadline=repo.deadline)
            v["notes"].append("The base branch `%s` is not in the local clone, so changes to the check were not "
                              "checked." % v["base"])
        v["notes"].append("Inspected from GitHub's diff (the head is not in the local clone): a secret added and "
                          "removed again in an earlier commit is not seen. Fetch the branch and run `/foreman "
                          "verdict %d` again for the full check." % number)
        v["how"], v["diff"] = "remote", diff
    except GitError as e:
        v["error"] = str(e)
        return v
    v["blockers"], v["marked"], v["allowed_by_user"] = _split(findings, root)
    v["verdict"] = verdict_of(v["blockers"], v.get("errors"), v["marked"])
    return v


def pr_diff(root: str, v: dict) -> str:
    """The unified diff of the pull request ``pr_verdict`` inspected, for exactly the same head: from the local
    commits when it was inspected locally, else the diff GitHub gave (whose head was re-checked)."""
    if v.get("how") == "local" and v.get("merge_base"):
        return Repo(root, budget=BOARD_BUDGET_SECONDS).git("diff", "-M", *detector._DIFF_OPTS, v["merge_base"],
                                                           v["head_oid"])
    if isinstance(v.get("diff"), str):
        return v["diff"]
    raise GhError("the pull request's diff was not read")


def branch_verdict(root: str, branch: str, keys: tuple = ()) -> dict:
    """Foreman's verdict for a local branch (the current one includes the uncommitted changes)."""
    from . import commands
    repo = Repo(root, budget=BOARD_BUDGET_SECONDS)
    current = repo.branch()
    if not branch or branch == current:
        v = commands.verdict(root, *keys)
        v.update(kind="branch", name_branch=current, current=True)
        return v
    v = {"kind": "branch", "name_branch": branch, "repo": root, "current": False, "notes": [], "blockers": [],
         "marked": [], "allowed_by_user": [], "verdict": "UNKNOWN"}
    if branch.startswith("-"):
        v["error"] = "`%s` is not a branch name" % branch
        return v
    # A branch fetched but never checked out exists only as origin/<name>, as `/foreman review <branch>` accepts.
    rev = next((r for r in ("refs/heads/" + branch, "refs/remotes/origin/" + branch, "refs/remotes/" + branch, branch)
                if repo.try_git("rev-parse", "--verify", "-q", r + "^{commit}")), None)
    if not rev:
        v["error"] = "no branch or commit named `%s` in %s" % (branch, root)
        return v
    try:
        base, label = repo.base_ref(rev)
        if not base:
            v["error"] = "`%s` has no base branch (no main or master to compare with)" % branch
            return v
        report = detector.scan_range(repo, base, rev, scope="branch", base_label=label, sarif_at_head=True)
    except GitError as e:
        v["error"] = str(e)
        return v
    count = repo.try_git("rev-list", "--count", "%s..%s" % (base, rev))
    v.update(base=label, commits_ahead=int(count) if count and count.isdigit() else None, check=report.check)
    v["blockers"], v["marked"], v["allowed_by_user"] = _split(report.findings, root)
    v["errors"] = list(dict.fromkeys(report.errors))
    v["sarif_notes"] = [n.to_dict() for n in report.notes]
    v["verdict"] = verdict_of(v["blockers"], v["errors"], v["marked"])
    return v


def wrap(text: str, indent: str = "", first: str = "") -> str:
    """``text`` folded at the board's width: ``first`` starts the first line, ``indent`` the others."""
    return textwrap.fill(" ".join(str(text).split()), width=WIDTH, initial_indent=first, subsequent_indent=indent,
                         break_long_words=False, break_on_hyphens=False)


def _reason(d: dict) -> str:
    return "%s\n%s" % (wrap("%s — %s" % (d["location"], d["message"]), "      ", "  [%s] " % d["rule"]),
                       wrap(d["fix"], "      ", "      fix: "))


def _reasons(v: dict) -> list:
    lines = []
    if v.get("blockers"):
        lines.append("Reasons:")
        lines += [_reason(d) for d in v["blockers"][:MAX_LISTED_REASONS]]
        if len(v["blockers"]) > MAX_LISTED_REASONS:
            lines.append("  ... and %d more" % (len(v["blockers"]) - MAX_LISTED_REASONS))
    if v.get("marked"):
        lines.append(wrap("Marked `%s` by the agent, waiting for you (`/foreman allow <id>` if you agree):" % MARKER))
        lines += [wrap("%s — %s (id %s)" % (d["location"], d["message"], d["id"]), "      ", "  [%s] " % d["rule"])
                  for d in v["marked"]]
    if v.get("allowed_by_user"):
        lines.append("Allowed by you:")
        lines += [wrap("%s — %s (id %s)" % (d["location"], d["message"], d["id"]), "      ", "  [%s] " % d["rule"])
                  for d in v["allowed_by_user"]]
    if v.get("errors"):
        lines.append("Could not inspect (INCOMPLETE is not a pass):")
        lines += [wrap(e, "    ", "  - ") for e in v["errors"]]
    notes = sarif_notes(v)
    if notes:
        lines.append(wrap(notes))
    return lines


def sarif_notes(v: dict) -> str:
    """One compact line for the non-blocking SARIF notes of a verdict, or ""."""
    notes = v.get("sarif_notes")
    if notes is None:  # the current branch's verdict (commands.verdict) keeps them under "notes"
        notes = [n for n in v.get("notes") or [] if isinstance(n, dict)]
    if not notes:
        return ""
    shown = "; ".join("%s: %s" % (n.get("location"), n.get("message")) for n in notes[:2])
    return "SARIF: %d note(s), not blocking: %s%s" % (len(notes), shown,
                                                       " (+%d more)" % (len(notes) - 2) if len(notes) > 2 else "")


def format_pr_verdict(v: dict) -> str:
    n = v["number"]
    if v.get("error"):
        lines = ["Foreman cannot give a verdict for PR #%d: %s." % (n, v["error"].rstrip("."))]
        if v.get("missing"):
            lines.append("`/foreman verdict <branch>` still works on local branches.")
        return "\n".join(lines)
    open_pr = not v.get("state") or v["state"] == "OPEN"
    hold = not_ready(v) if open_pr else []
    head = "Foreman verdict for PR #%d: %s" % (n, v["verdict"])
    if v["verdict"] == "CLEAN" and open_pr:
        head += " — but not mergeable yet" if hold else " — ready to merge"
    lines = [head, "  " + trim(v.get("title"), WIDTH - 2)]
    facts = ["%s -> %s" % (v.get("head") or "?", v.get("base") or "?")]
    if v.get("draft"):
        facts.append("draft")
    if v.get("conflicts"):
        facts.append("conflicts")
    if v.get("state") and v["state"] != "OPEN":
        facts.append(v["state"].lower())
    lines.append("  " + trim(" · ".join(facts), WIDTH - 2))
    ci = str(v.get("ci") or "CI unknown")
    lines.append("  CI: %s" % (ci[3:] if ci.startswith("CI ") else ci))
    lines.append("  Closes: %s" % (", ".join(v.get("closes") or []) or "no issue"))
    lines += _reasons(v)
    if v["verdict"] == "CLEAN":
        lines.append("No skipped, deleted or moved tests, no change to the check, no secrets.")
    if hold and v["verdict"] == "CLEAN":
        lines.append("Not mergeable yet:")
        lines += [wrap(h, "    ", "  - ") for h in hold]
    lines += [wrap(note, "  ", "Note: ") for note in v.get("notes") or []]
    if not open_pr:
        pass
    elif v["verdict"] == "CLEAN" and not hold:
        caution = "" if v.get("ci") == "CI passing" else " Look at the CI first (%s)." % v.get("ci")
        lines.append(wrap("`/foreman merge %d` (squash; add --merge or --rebase to change), or `/foreman reject %d "
                          "<note>`.%s" % (n, n, caution), "  ", "Next: "))
    elif v["verdict"] == CLEAN:
        lines.append(wrap("fix what is listed above, then `/foreman verdict %d` again." % n, "  ", "Next: "))
    elif v["verdict"] == NEEDS_OK:
        lines.append(wrap("`/foreman allow <id>` for each marked finding you agree with, then `/foreman verdict %d` "
                          "again; or `/foreman reject %d [note]`." % (n, n), "  ", "Next: "))
    elif v["verdict"] == INCOMPLETE:
        lines.append(wrap("fix what could not be inspected, then `/foreman verdict %d` again." % n, "  ", "Next: "))
    else:
        lines.append(wrap("`/foreman reject %d [note]` posts these reasons on the pull request." % n, "  ", "Next: "))
    return "\n".join(lines)


def not_ready(v: dict) -> list:
    """Why GitHub cannot merge the pull request now, with what to do; [] when it can. Foreman's own CLEAN or
    BLOCKED is separate: this is the pull request's state on GitHub."""
    out = []
    base = v.get("base") or "the base branch"
    if v.get("draft"):
        out.append("it is a draft: mark it ready for review (`gh pr ready %d`)." % v["number"])
    if v.get("mergeable") == "CONFLICTING":
        out.append("it conflicts with %s: update the branch (merge or rebase %s into it, resolve, push)." % (base, base))
    elif v.get("mergeable") not in ("MERGEABLE",):
        out.append("GitHub is still working out whether it can be merged: try again in a moment.")
    return out


def format_branch_verdict(v: dict, pr: Optional[dict] = None, gh_note: str = "") -> str:
    branch = v.get("name_branch") or v.get("branch") or "?"
    if v.get("verdict") in ("NO_REPOSITORY", "ERROR") or v.get("error"):
        return "Foreman cannot give a verdict for `%s`: %s" % (branch, v.get("error") or v.get("message", ""))
    lines = ["Foreman verdict for branch %s: %s" % (branch, v["verdict"])]
    if v.get("base"):
        ahead = v.get("commits_ahead")
        lines.append("  vs %s%s%s" % (v["base"], "" if ahead is None else ", %d commit(s) ahead" % ahead,
                                      ", with the uncommitted changes" if v.get("current") else ""))
    else:
        lines.append("  no base branch found; only uncommitted changes are checked")
    if pr:
        lines.append("  PR #%s · %s · closes %s" % (pr.get("number"), ci_summary(pr.get("statusCheckRollup")),
                                                     ", ".join(closing_refs(pr)) or "no issue"))
    elif gh_note:
        lines.append("  " + gh_note)
    lines += _reasons(v)
    if v["verdict"] == "CLEAN":
        lines.append("No skipped, deleted or moved tests, no change to the check, no secrets.")
    return "\n".join(lines)


# ─── The board ───────────────────────────────────────────────────────────────

def _verdict_word(v: dict) -> str:
    """The verdict with its count: BLOCKED 2, NEEDS YOUR OK 1, INCOMPLETE, CLEAN."""
    word = v.get("verdict") or "?"
    if word == BLOCKED:
        return "BLOCKED %d" % len(v.get("blockers") or [])
    if word == NEEDS_OK:
        return "NEEDS YOUR OK %d" % len(v.get("marked") or [])
    return word


def _branch_line(v: dict) -> str:
    if v.get("verdict") in ("ERROR", "NO_REPOSITORY"):
        return "Branch: could not be checked (%s)" % trim(v.get("message", ""), 50)
    facts = []
    base_tail = str(v.get("base") or "").rsplit("/", 1)[-1]
    if v.get("base") and base_tail == v.get("branch") and not v.get("commits_ahead"):
        facts.append("the base branch")
    elif v.get("base"):
        facts.append("vs %s" % v["base"])
        if v.get("commits_ahead") is not None:
            facts.append("%d ahead" % v["commits_ahead"])
    else:
        facts.append("no base branch")
    facts.append("%d uncommitted" % v.get("uncommitted_files", 0))
    facts.append(_verdict_word(v))
    return "Branch: %s  %s" % (trim(v.get("branch"), 30), " · ".join(facts))


def local_branches(root: str, deadline: float) -> list:
    """One line per local branch (most recent first): commits ahead of its base and its verdict."""
    repo = Repo(root, deadline=deadline)
    raw = repo.try_git("for-each-ref", "--sort=-committerdate", "--format=%(refname:short)", "refs/heads")
    names = [n for n in (raw or "").splitlines() if n.strip()]
    lines, shown, skipped, base_label = [], 0, 0, None
    for name in names:
        if shown >= MAX_BRANCHES:
            break
        try:
            base, label = repo.base_ref("refs/heads/" + name)
            if label and (label == name or label.endswith("/" + name)):
                skipped += 1
                continue  # the base branch itself
            shown += 1
            if not base:
                lines.append("  %-28s no base branch" % trim(name, 28))
                continue
            base_label = base_label or label
            count = repo.try_git("rev-list", "--count", "%s..refs/heads/%s" % (base, name))
            report = detector.scan_range(repo, base, "refs/heads/" + name, scope="branch", base_label=label,
                                         sarif_at_head=True)
            blockers = [f for f in report.findings if not f.allowed]
            marked = [f for f in report.findings if f.allowed and not grants.is_granted(f.fingerprint)]
            verdict = _verdict_word({"verdict": verdict_of(blockers, report.errors, marked),
                                     "blockers": blockers, "marked": marked})
            lines.append("  %-28s %4s ahead  %s" % (trim(name, 28), count or "?", verdict))
        except GitTimeout:
            lines.append("  %-28s not checked (out of time)" % trim(name, 28))
            break
        except GitError as e:
            lines.append("  %-28s error: %s" % (trim(name, 28), trim(str(e), 40)))
    if not lines:
        return ["Local branches: none besides the base branch."]
    more = len(names) - shown - skipped
    head = "Local branches (vs %s):" % base_label if base_label else "Local branches:"
    return [head] + lines + (["  ... and %d more" % more] if more > 0 else [])


def cmd_board(args: str = "", keys: tuple = (), platform: Optional[str] = None) -> str:
    from . import commands
    root, how = resolve(keys, platform)
    if not root:
        return _no_repository()
    deadline = time.monotonic() + BOARD_BUDGET_SECONDS
    v = commands.verdict(root, *keys)
    reason = _local_has_github(root)
    snap = None
    if reason is None:
        try:
            snap = snapshot(root)
        except GhError as e:
            reason = e.reason
    title = snap["name"] if snap and snap.get("name") else os.path.basename(root)
    lines = ["Foreman board: %s" % title,
             "Repository: %s" % trim_path(root, WIDTH - 12),
             "  (%s)" % trim(_how(how), WIDTH - 4),
             _branch_line(v), ""]
    next_cmds = []
    if snap is None:
        lines.append("GitHub: %s; showing local branches only." % reason)
        lines += local_branches(root, deadline)
        if v.get("verdict") == "BLOCKED":
            next_cmds.append(("/foreman status", "why the current branch is blocked"))
        next_cmds.append(("/foreman verdict <branch>", "reasons for one branch"))
    else:
        prs, issues, name = snap["prs"], snap["issues"], snap["name"]
        lines.append("Pull requests (%d open):" % len(prs) if prs else "Pull requests: none open.")
        for pr in prs[:MAX_PRS]:
            lines += _pr_lines(pr, name)
        if len(prs) > MAX_PRS:
            lines.append("  ... and %d more (`/foreman prs`)" % (len(prs) - MAX_PRS))
        closed = _closed_numbers(prs, name)
        free = [i for i in issues if i.get("number") not in closed]
        lines.append("")
        lines.append("Issues no open PR closes (%d):" % len(free) if free else "Issues no open PR closes: none.")
        lines += [_issue_line(i) for i in free[:MAX_ISSUES]]
        if len(free) > MAX_ISSUES:
            lines.append("  ... and %d more (`/foreman issues`)" % (len(free) - MAX_ISSUES))
        if prs:
            next_cmds.append(("/foreman verdict %s" % prs[0].get("number"), "clean or blocked, and why"))
        if v.get("verdict") == "BLOCKED":
            next_cmds.append(("/foreman status", "why the current branch is blocked"))
        if free:
            next_cmds.append(("/foreman issues", "every open issue and its PR"))
    try:
        from . import pipeline, review
        if v.get("verdict") in (CLEAN, BLOCKED, INCOMPLETE, NEEDS_OK) and v.get("commits_ahead"):
            # the current branch's change, with the verdict just computed (the base branch itself is no change)
            status, detail = pipeline.gate_from_verdict(v)
            pipeline.record_gate(pipeline.local_ref(root), status, detail, "Gate on the board: %s" % detail)
        flow = pipeline.board_lines(snap["name"] if snap and snap.get("name") else
                                    review.slug_of(Repo(root, budget=5)), root, WIDTH)
    except Exception:
        logger.warning("foreman: cannot read the pipeline", exc_info=True)
        flow = []
    if flow:
        lines += [""] + flow
    if v.get("no_tests"):
        lines += ["", wrap(commands.NO_TESTS)]
    if how != PINNED:
        next_cmds.append(("/foreman use", "work on another repository"))
    lines += ["", "Next:"] + ["  %-24s %s" % c for c in next_cmds[:3]]
    return "\n".join(lines)


def _snapshot_or_reason(keys: tuple, platform: Optional[str]) -> tuple:
    root, how = resolve(keys, platform)
    if not root:
        return None, None, _no_repository()
    reason = _local_has_github(root)
    if reason:
        return root, None, "Foreman: GitHub is not available here: %s. `/foreman` shows the local branches." % reason
    try:
        return root, snapshot(root), None
    except GhError as e:
        return root, None, "Foreman: GitHub is not available here: %s. `/foreman` shows the local branches." % e.reason


def cmd_prs(args: str = "", keys: tuple = (), platform: Optional[str] = None) -> str:
    root, snap, problem = _snapshot_or_reason(keys, platform)
    if problem:
        return problem
    prs = snap["prs"]
    if not prs:
        return "Foreman: %s has no open pull requests." % (snap["name"] or root)
    lines = ["Open pull requests in %s (%d):" % (snap["name"] or root, len(prs))]
    for pr in prs[:30]:
        lines += _pr_lines(pr, snap["name"])
    if len(prs) > 30:
        lines.append("  ... and %d more" % (len(prs) - 30))
    lines.append("Next: `/foreman verdict <number>` for one of them.")
    return "\n".join(lines)


def cmd_issues(args: str = "", keys: tuple = (), platform: Optional[str] = None) -> str:
    root, snap, problem = _snapshot_or_reason(keys, platform)
    if problem:
        return problem
    issues = snap["issues"]
    if not issues:
        return "Foreman: %s has no open issues." % (snap["name"] or root)
    closed = _closed_numbers(snap["prs"], snap["name"])
    lines = ["Open issues in %s (%d):" % (snap["name"] or root, len(issues))]
    for i in issues[:30]:
        by = closed.get(i.get("number"))
        lines.append(_issue_line(i, "  <- PR %s" % ", ".join("#%s" % n for n in by) if by else ""))
    if len(issues) > 30:
        lines.append("  ... and %d more" % (len(issues) - 30))
    return "\n".join(lines)


# ─── /foreman verdict ────────────────────────────────────────────────────────

_PR_ARG = re.compile(r"^#?(\d+)[.,;:!?]?$")  # a phone keyboard adds a stray full stop


def _pr_number(token: str) -> Optional[int]:
    m = _PR_ARG.match(token or "")
    if m:
        return int(m.group(1))
    m = re.match(r"^https?://[^/]+/[^/]+/[^/]+/pull/(\d+)/?$", token or "")
    return int(m.group(1)) if m else None


def cmd_verdict(args: str = "", keys: tuple = (), platform: Optional[str] = None) -> str:
    words, repo_arg, problem = take_repo_option(args.split())
    if problem:
        return problem
    if repo_arg is not None:
        root, problem = known_repository(repo_arg)
        if problem:
            return problem
    else:
        root, how = resolve(keys, platform)
    if not root:
        return _no_repository()
    target = words[0] if words else ""
    number = _pr_number(target)
    if number is not None:
        reason = _local_has_github(root)
        if reason:
            return ("Foreman cannot give a verdict for PR #%d: %s. `/foreman verdict <branch>` works on local "
                    "branches." % (number, reason))
        v = pr_verdict(root, number)
        _pipeline_pr(root, v)
        return format_pr_verdict(v)
    v = branch_verdict(root, target, keys)
    pr, note = None, ""
    branch = v.get("name_branch")
    if branch and not v.get("error") and v.get("verdict") not in ("ERROR", "NO_REPOSITORY"):
        reason = _local_has_github(root)
        if reason:
            note = "GitHub: %s." % reason
        else:
            try:
                found = gh_json(["pr", "list", "--head", branch, "--state", "open", "--json",
                                 "number,closingIssuesReferences,statusCheckRollup"], root)
                pr = found[0] if isinstance(found, list) and found and isinstance(found[0], dict) else None
                note = "" if pr else "No open pull request for this branch."
            except GhError as e:
                note = "GitHub: %s." % e.reason
    return format_branch_verdict(v, pr, note)


# ─── Merge and reject, through Hermes's terminal tool ────────────────────────

def _terminal(command: str, root: str, timeout: int = MERGE_TIMEOUT) -> tuple:
    """Run ``command`` with Hermes's own terminal tool (``ctx.dispatch_tool``). (state, detail) where state is
    done, denied, waiting, timeout, failed or unavailable."""
    dispatch = getattr(_CTX, "dispatch_tool", None)
    if not callable(dispatch):
        return "unavailable", "Hermes's terminal tool is not reachable from here"
    try:
        raw = dispatch("terminal", {"command": command, "workdir": root, "timeout": timeout})
    except Exception as e:
        logger.warning("foreman: terminal dispatch failed", exc_info=True)
        return "failed", "%s: %s" % (type(e).__name__, e)
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except ValueError:
            data = {"output": raw}
    if not isinstance(data, dict):
        data = {"output": str(raw)}
    status = str(data.get("status") or "").lower()
    error = str(data.get("error") or "")
    output = str(data.get("output") or "")
    tail = "\n".join(l for l in (output + "\n" + error).strip().splitlines()[-8:])
    exit_code = data.get("exit_code")
    if status in ("blocked", "denied") or "denied" in error.lower():
        return "denied", tail
    if status == "pending_approval" or data.get("approval_pending"):
        return "waiting", tail
    if status == "yielded_to_background":  # Hermes moved a long command to the background: no exit status yet
        return "background", tail
    if status in ("timeout", "timed_out") or "timed out" in error.lower() or exit_code == 124:
        return "timeout", tail
    if exit_code == 0 and not error:
        return "done", tail
    return "failed", ("exit %s: " % exit_code if exit_code not in (None, "") else "") + tail


def _outcome_text(state: str, detail: str, what: str, command: str) -> str:
    detail = detail.strip()
    if state == "done":
        return "Foreman: %s.%s" % (what, "\n" + detail if detail else "")
    if state == "denied":
        return "Foreman: Hermes's approval denied `%s`; nothing was changed.%s" % (command, "\n" + detail if detail
                                                                                    else "")
    if state == "waiting":
        return "Foreman: Hermes is waiting for your approval of `%s`; approve or deny it there." % command
    if state == "background":
        m = re.match(r"gh pr \w+ (\d+)", command)
        check = ("`/foreman verdict %s` shows MERGED when it is done" % m.group(1) if m and " merge " in command
                 else "check the pull request on GitHub")
        return ("Foreman: `%s` is still running (Hermes moved it to the background), so its result is not known yet. "
                "Do not run it again: %s." % (command, check))
    if state == "timeout":
        return ("Foreman: `%s` timed out; check the pull request on GitHub before you try again.%s"
                % (command, "\n" + detail if detail else ""))
    if state == "unavailable":
        return "Foreman: %s, so `%s` was not run. You can run it yourself in a terminal." % (detail, command)
    return "Foreman: `%s` failed; nothing was changed by Foreman.%s" % (command, "\n" + detail if detail else "")


def _prepare_pr(args: str, keys: tuple, platform: Optional[str], verb: str) -> tuple:
    """(root, number, words without the number, problem text)."""
    words, repo_arg, problem = take_repo_option(args.split())
    if problem:
        return None, None, words, problem
    numbers = [w for w in words if _pr_number(w) is not None]
    if not numbers:
        return None, None, words, "Usage: /foreman %s <pr-number>%s [--repo <owner/name>]" % (
            verb, " [--merge|--rebase] [--yes]" if verb == "merge" else " [--close [--yes]] [note]")
    if repo_arg is not None:
        root, problem = known_repository(repo_arg)
        if problem:
            return None, None, words, problem
    else:
        root, how = resolve(keys, platform)
    if not root:
        return None, None, words, _no_repository()
    reason = _local_has_github(root)
    if reason:
        return root, None, words, ("Foreman: `/foreman %s` needs GitHub: the GitHub CLI (`gh`), logged in, and a "
                                   "GitHub remote. Here: %s." % (verb, reason))
    rest = list(words)
    rest.remove(numbers[0])
    return root, _pr_number(numbers[0]), rest, None


def _confirm(question: str, options: list) -> Optional[str]:
    """The value the person picked with Hermes's documented ``ctx.ask_choice``, or None when nothing can ask here
    (an older Hermes, a cron job, a chat that cannot ask) or nobody answered."""
    ask = getattr(_CTX, "ask_choice", None)
    if not callable(ask):
        return None
    try:
        # No description: Telegram prints "<n>. <label> — <description>" above bare numbered buttons, so the
        # label says the action and the detail lives in the question.
        return ask(question, [{"value": v, "label": l} for v, l in options])
    except Exception:
        logger.warning("foreman: ask_choice failed", exc_info=True)
        return None


def _no_answer(what: str, rerun: str) -> str:
    return wrap("Foreman: %s. It needs your confirmation, and Hermes could not ask here or nobody answered (an "
                "unattended run, a chat without choices, or the question timed out). To confirm, type:" % what) \
        + "\n  " + rerun


def cmd_merge(args: str = "", keys: tuple = (), platform: Optional[str] = None) -> str:
    root, number, rest, problem = _prepare_pr(args, keys, platform, "merge")
    if problem:
        return problem
    yes = "--yes" in rest
    rest = [w for w in rest if w != "--yes"]
    methods = [w for w in rest if w in ("--squash", "--merge", "--rebase")]
    unknown = [w for w in rest if w not in ("--squash", "--merge", "--rebase")]
    if unknown or len(methods) > 1:
        return "Usage: /foreman merge <pr-number> [--merge|--rebase] [--yes] [--repo <owner/name>]   (default: squash)"
    method = methods[0][2:] if methods else "squash"
    v = pr_verdict(root, number)
    ref = _pipeline_pr(root, v)
    if v.get("error"):
        _pipeline_refused(ref, "no verdict: %s" % v["error"])
        return ("Foreman will not merge PR #%d: it cannot compute a verdict (%s)."
                % (number, v["error"].rstrip(".")))
    if v.get("state") and v["state"] != "OPEN":
        return "Foreman: PR #%d is %s; there is nothing to merge." % (number, v["state"].lower())
    if v["verdict"] != CLEAN:  # --yes never overrides the verdict
        why = {BLOCKED: "it is BLOCKED.",
               INCOMPLETE: "its verdict is INCOMPLETE: Foreman could not inspect everything it was told to.",
               NEEDS_OK: "it NEEDS YOUR OK: the agent marked findings that wait for `/foreman allow <id>`."}
        nxt = {BLOCKED: "Next: `/foreman reject %d [note]` posts these reasons on the pull request." % number,
               INCOMPLETE: "Next: fix what could not be inspected, then `/foreman merge %d` again." % number,
               NEEDS_OK: "Next: `/foreman allow <id>` for each one you agree with, then `/foreman merge %d` again."
                         % number}
        _pipeline_refused(ref, "the verdict is %s" % v["verdict"])
        return "\n".join([wrap("Foreman will not merge PR #%d: %s" % (number, why.get(v["verdict"], v["verdict"])))]
                         + _reasons(v) + [wrap(nxt.get(v["verdict"], ""))])
    hold = not_ready(v)
    if hold:  # --yes never overrides this: GitHub's own state
        return "\n".join(["Foreman will not merge PR #%d: Foreman finds it CLEAN, but it is not mergeable yet:"
                          % number] + [wrap(h, "    ", "  - ") for h in hold]
                         + ["Next: fix that, then `/foreman merge %d` again." % number])
    if not _OID.fullmatch(v.get("head_oid") or ""):
        return "Foreman will not merge PR #%d: GitHub did not give its head commit." % number
    # The second model's review of this exact head (auto_review merge or finish); off: as before.
    pre, notes, unreviewed = [], [], ""
    from . import pipeline
    if pipeline.level() != "off":
        outcome = _review_for_merge(root, number, v, keys, platform)
        pre, notes, unreviewed = outcome["pre"], outcome["notes"], outcome["unreviewed"]
        if outcome.get("refuse"):
            _pipeline_refused(ref, outcome["refuse_detail"])
            return "\n".join(pre + outcome["refuse"])
    # --match-head-commit: GitHub merges exactly the commit Foreman inspected, or nothing.
    command = "gh pr merge %d --%s --delete-branch --match-head-commit %s" % (number, method, v["head_oid"])
    if not yes or unreviewed:  # --yes was typed before anyone knew the review could not run
        rerun = "/foreman merge %d%s%s --yes" % (number, "" if method == "squash" else " --" + method,
                                                 _repo_suffix(args))
        ci = v.get("ci") or "CI unknown"
        warn = "" if ci == "CI passing" else "WARNING: %s.\n" % ci
        first = ("The second-model review could not run (%s). A person decides: merge without it?\n"
                 % trim(unreviewed, 160)) if unreviewed else ""
        noted = ("Review notes:\n%s\n" % "\n".join("- " + n.strip() for n in notes)) if notes else ""
        label = "Merge PR #%d" % number
        question = ("%s%s%sMerge PR #%d (%s, %s) into %s?\n%s\nCloses: %s · %s\n"
                    "Will run: gh pr merge %d --%s --delete-branch (pinned to %s)\n"
                    "Choose %s to merge, or Cancel.") % (
            first, noted, warn, number, v["head_oid"][:7], method, v.get("base") or "its base",
            trim(v.get("title"), WIDTH), ", ".join(v.get("closes") or []) or "no issue", ci,
            number, method, v["head_oid"][:7], label)
        _pipeline_call(pipeline.record_waiting, ref, "merge question asked")
        answer = _confirm(question, [("merge", label), ("cancel", "Cancel")])
        if answer == "cancel":
            _pipeline_call(pipeline.record_event, ref, "You cancelled the merge")
            return "\n".join(pre + ["Foreman: cancelled; PR #%d was not merged." % number])
        if answer != "merge":
            _pipeline_call(pipeline.record_event, ref, "Merge question not answered; nothing merged")
            if unreviewed:  # --yes does not cover this, so never offer it as the way through
                return "\n".join(pre + [wrap(
                    "Foreman: PR #%d was not merged: the second-model review could not run (%s). `--yes` does not "
                    "cover that: a person decides it in a chat where Hermes can ask (the CLI, or a messaging app "
                    "with buttons). Or run `/foreman review %d --fresh` once the reviewer model is reachable."
                    % (number, trim(unreviewed, 120), number))])
            return "\n".join(pre + [_no_answer("PR #%d was not merged" % number, rerun)])
    state, detail = _terminal(command, root)
    where = " in %s" % v["name"] if v.get("name") else ""
    if state == "done":
        _pipeline_call(pipeline.record_merged, ref, method)
    else:
        _pipeline_refused(ref, "`gh pr merge` %s" % state)
    lines = pre + (["Review notes (you merged with them):"] + notes if notes and yes else []) + [
        "Foreman verdict for PR #%d: CLEAN (%s)." % (number, v.get("ci") or "CI unknown"),
        _outcome_text(state, detail, "merged PR #%d (%s)%s" % (number, method, where), command)]
    return "\n".join(lines)


def _review_line(f: dict) -> str:
    return "  %s %s%s — %s" % (f.get("severity"), f.get("file"), ":%d" % f["line"] if f.get("line") else "",
                               trim(f.get("title"), 50))


def _review_for_merge(root: str, number: int, v: dict, keys: tuple, platform: Optional[str]) -> dict:
    """The second model's review of the pull request's exact head, from the store when the same diff was reviewed
    by the same reviewer, else run now. {"pre": lines to show first, "notes": lines for the question, "unreviewed":
    why the review could not run or "", "refuse": lines when verified BLOCKING findings refuse the merge}."""
    from . import review
    out = {"pre": [], "notes": [], "unreviewed": "", "refuse": None, "refuse_detail": ""}
    try:
        rec = review.run_review(str(number), keys, platform, where=root, pr_view=v)
    except Exception as e:  # noqa: BLE001 — a review that breaks is a review that could not run
        logger.warning("foreman: review before merge failed", exc_info=True)
        rec = {"verdict": "ERROR", "message": "%s: %s" % (type(e).__name__, e)}
    verdict = rec.get("verdict")
    if verdict in ("ERROR", "NO_REPOSITORY"):
        out["unreviewed"] = rec.get("message") or verdict
        return out
    if rec.get("head") != v.get("head_oid"):
        out["refuse"] = [wrap("Foreman will not merge PR #%d: the review is of %s, not of the pull request's head %s; "
                              "it changed while Foreman read it. Run `/foreman merge %d` again."
                              % (number, (rec.get("head") or "?")[:7], v["head_oid"][:7], number))]
        out["refuse_detail"] = "the head moved during the review"
        return out
    review.record_in_pipeline(rec, then="awaiting_owner")
    m = rec.get("model") or {}
    who = review._label(m.get("provider") or None, m.get("model")) if m and m.get("model") else \
        "the host's default model"
    if rec.get("cached"):
        out["pre"].append(wrap("Second-model review of %s: %s (stored review of this exact diff, %s; the model was "
                               "not called again)." % (v["head_oid"][:7], verdict, rec.get("time") or "earlier")))
    else:
        out["pre"].append(wrap("Foreman reviewed PR #%d at %s with the second model first (%s): %s."
                               % (number, v["head_oid"][:7], who, verdict)))
    if m and m.get("same_as_author") is True and not rec.get("error"):
        out["notes"].append("  " + review.SAME_MODEL)
    if verdict == "COULD NOT RUN":
        out["unreviewed"] = rec.get("error") or "unknown reason"
        return out
    blocking = [f for f in rec.get("findings") or [] if f.get("severity") == "BLOCKING"]
    if verdict == "BLOCKED":
        lines = [wrap("Foreman will not merge PR #%d: the second-model review found blocking problems (each "
                      "quote checked against the diff; --yes does not override this):" % number)]
        for f in blocking:
            lines.append(_review_line(f))
            lines.append(wrap(f.get("why") or "", "      ", "      why: "))
            lines.append(wrap(f.get("fix") or "", "      ", "      fix: "))
        if not blocking:
            lines += ["  [%s] %s — %s" % (d["rule"], d["location"], d["message"])
                      for d in (rec.get("deterministic") or {}).get("findings") or []]
        lines.append(wrap("Next: `/foreman reject %d [note]` posts these reasons on the pull request; the agent "
                          "fixes them and you merge again." % number))
        out["refuse"], out["refuse_detail"] = lines, "the review found blocking problems"
        return out
    notes = [_review_line(f) for f in (rec.get("findings") or [])[:4]]
    if len(rec.get("findings") or []) > 4:
        notes.append("  ... and %d more (`/foreman review %d`)" % (len(rec["findings"]) - 4, number))
    if rec.get("dropped_unverified"):
        notes.append("  %d finding(s) dropped: their quote is not in the diff" % rec["dropped_unverified"])
    cov = rec.get("coverage") or {}
    if cov and not cov.get("complete", True):
        notes.append("  partly reviewed: %s" % trim(cov.get("note"), WIDTH - 20))
    if verdict == "NOTHING TO REVIEW":
        notes.append("  the pull request's diff is empty")
    out["notes"] += notes
    return out


def _pipeline_pr(root: str, v: dict):
    """The pipeline Ref of a pull request verdict, recording its gate stage; None when it cannot."""
    try:
        from . import pipeline
        if not isinstance(v.get("number"), int):
            return None
        ref = pipeline.pr_ref(root, v)
        status, detail = pipeline.gate_from_verdict(v)
        pipeline.record_gate(ref, status, detail, "Gate on PR #%d: %s" % (v["number"], detail))
        return ref
    except Exception:
        logger.warning("foreman: cannot record the pull request on the pipeline", exc_info=True)
        return None


def _pipeline_call(fn, ref, *args) -> None:
    if ref is None:
        return
    try:
        fn(ref, *args)
    except Exception:
        logger.warning("foreman: cannot update the pipeline", exc_info=True)


def _pipeline_refused(ref, detail: str) -> None:
    from . import pipeline
    _pipeline_call(pipeline.record_merge_refused, ref, detail)


# ─── Saved model review (written by Foreman's reviewer, if any) ──────────────

MAX_REVIEW_FINDINGS = 20


def saved_review(name_with_owner: str, number: int, head_oid: str = "", head_branch: str = "",
                 root: str = "") -> list:
    """Findings of the last ``/foreman review`` of this pull request, or of its head branch (``review.load``), as
    Markdown bullet texts; [] when there is none. A review of another commit than ``head_oid`` (or one that does not
    say which commit it read) is stale and is not used."""
    if "/" not in (name_with_owner or "") or not _OID.fullmatch(head_oid or ""):
        return []
    data = None
    try:
        from . import review
        wanted = [("pr", str(number), "")] + ([("branch", head_branch, root)] if head_branch else [])
        for kind, ref, where in wanted:
            found = review.load(name_with_owner, kind, ref, where, head=head_oid)
            if isinstance(found, dict) and found.get("head") == head_oid:
                data = found
                break
    except Exception:
        logger.warning("foreman: cannot read the saved review", exc_info=True)
        return []
    findings = data.get("findings") if isinstance(data, dict) else None
    out = []
    for f in findings if isinstance(findings, list) else []:
        if isinstance(f, str):
            text = f
        elif isinstance(f, dict):
            where = f.get("location") or f.get("file") or f.get("path") or ""
            if where and f.get("line") and ":" not in str(where):
                where = "%s:%s" % (where, f["line"])
            sev = f.get("severity") or f.get("level") or ""
            msg = f.get("message") or f.get("title") or f.get("description") or ""
            if f.get("why"):
                msg = "%s: %s" % (msg, f["why"]) if msg else f["why"]
            fix = f.get("fix") or f.get("suggestion") or ""
            text = "".join(("**%s** " % sev if sev else "", "`%s` " % where if where else "", str(msg),
                            " Fix: %s" % fix if fix else ""))
        else:
            continue
        text = _no_mentions(" ".join(str(text).split()))[:500]
        if text:
            out.append(text)
        if len(out) >= MAX_REVIEW_FINDINGS:
            break
    return out


_ZWSP = "\u200b"  # zero-width space, written as an escape: never a literal invisible character in the source
_CONTROL = re.compile(r"[\x00-\x1f\x7f\x85\u2028\u2029]+")
# No lookbehind anywhere: GitHub's own rules differ from Python's \w (Unicode letters, "_", owner/repo#12), so
# every "@", every "#" and every scheme or "www." gets the zero-width space.
_MENTION = re.compile(r"@")
_ISSUE_REF = re.compile(r"#|(?i:gh)-(?=\d)")
_URL = re.compile(r"(?i)(://|www\.)")


def _no_mentions(text: str, code: bool = False) -> str:
    """Third-party words (file names from the pull request, a model's findings, gh's errors) put into a comment the
    user's account posts: on one line, and unable to notify anyone or link anything. Every control character and
    line break becomes a space (a blank line would end a code span and start a new paragraph); ``@name``,
    ``#123``, ``GH-123`` and URLs get a zero-width space after ``@``, ``#``, ``GH`` or the scheme, which GitHub
    does not autolink or notify. Inserting, never wrapping in backticks: a backtick added next to the author's own
    would break an existing code span open."""
    text = _CONTROL.sub(" ", str(text or ""))
    text = _MENTION.sub("@" + _ZWSP, text)
    text = _ISSUE_REF.sub(lambda m: m.group(0)[:-1] + _ZWSP + "-" if m.group(0).endswith("-")
                          else m.group(0) + _ZWSP, text)
    text = _URL.sub(lambda m: ":" + _ZWSP + "//" if m.group(1) == "://" else m.group(1)[:-1] + _ZWSP + ".", text)
    if code:
        return text  # inside a code span GitHub decodes no entity and renders no link
    # Outside one: no HTML (an entity like &#64; becomes "@" after the filters above), no link syntax.
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([\[\]\\])", r"\\\1", text)


def reject_comment(v: dict, note: str = "", review: Optional[list] = None) -> str:
    """The Markdown comment ``/foreman reject`` posts: the verdict's reasons, the saved review, the note."""
    head = (v.get("head_oid") or "")[:7]
    lines = ["### Foreman: changes requested", ""]
    findings = (v.get("blockers") or []) + (v.get("marked") or [])
    if v.get("error"):
        lines.append("Foreman could not compute a verdict for this pull request (%s)."
                     % _no_mentions(v["error"]).rstrip("."))
    elif findings:
        lines.append("Foreman's deterministic check found %d blocker(s)%s:" % (
            len(findings), " at `%s`" % head if head else ""))
        lines.append("")
        for d in findings:
            marked = " (marked `%s` by the author, not allowed by the reviewer)" % MARKER if d.get("allowed") else ""
            lines.append("- **%s** `%s`: %s%s." % (_no_mentions(d["rule"]).replace("`", "'"),
                                                    _no_mentions(d["location"], code=True).replace("`", "'"),
                                                    _no_mentions(d["message"]).rstrip("."), marked))
            lines.append("  Fix: %s" % _no_mentions(d["fix"]))
    else:
        lines.append("Foreman's deterministic check found no blockers%s; the reviewer rejects it for the reason "
                     "below." % (" at `%s`" % head if head else ""))
    if v.get("how") == "remote" and not v.get("error"):
        lines += ["", "_Checked from GitHub's diff; secrets in earlier commits of the branch were not checked._"]
    if review:
        lines += ["", "#### Model review", ""] + ["- %s" % r for r in review]
    if note.strip():
        lines += ["", "#### Note from the reviewer", "", note.strip()]
    lines += ["", "<sub>Posted with `/foreman reject` from Hermes Agent.</sub>"]
    return "\n".join(lines)


def _quote_path(path: str) -> Optional[str]:
    """The path in double quotes for any shell the terminal uses, or None when it holds a character a shell would
    expand or end the quotes on."""
    path = path.replace("\\", "/")
    return None if re.search(r'["$`!%\n\r]', path) else '"%s"' % path


def cmd_reject(args: str = "", keys: tuple = (), platform: Optional[str] = None) -> str:
    root, number, rest, problem = _prepare_pr(args, keys, platform, "reject")
    if problem:
        return problem
    close, yes = "--close" in rest, "--yes" in rest
    note = " ".join(w for w in rest if w not in ("--close", "--yes")).strip()
    v = pr_verdict(root, number)
    if v.get("error") and not note:
        return ("Foreman cannot compute a verdict for PR #%d (%s). To reject it anyway, say why: `/foreman reject "
                "%d <note>`." % (number, v["error"].rstrip("."), number))
    if v.get("verdict") == "CLEAN" and not note:
        return ("Foreman found no blockers in PR #%d. To reject it, say why: `/foreman reject %d <note>`."
                % (number, number))
    name = v.get("name") or ""
    body = reject_comment(v, note, saved_review(name, number, v.get("head_oid") or "", v.get("head") or "", root))
    if close and not yes:  # closing is the part that needs a confirmation; it is asked before anything is posted
        rerun = "/foreman reject %d%s --close --yes%s" % (number, _repo_suffix(args), " " + note if note else "")
        label = "Post and close PR #%d" % number
        answer = _confirm("Post the comment and close PR #%d?\n%s\n"
                          "Will run: gh pr comment %d, then gh pr close %d\n"
                          "Choose %s, Post only (leave it open), or Cancel."
                          % (number, trim(v.get("title"), WIDTH), number, number, label),
                          [("close", label), ("post", "Post only"), ("cancel", "Cancel")])
        if answer == "cancel":
            return "Foreman: cancelled; nothing was posted on PR #%d." % number
        if answer == "post":
            close = False
        elif answer != "close":
            return _no_answer("nothing was posted on PR #%d and it was not closed" % number, rerun)
    outbox = os.path.join(grants.store_dir(), "outbox")
    os.makedirs(outbox, exist_ok=True)
    fd, body_path = tempfile.mkstemp(prefix="reject-%d-" % number, suffix=".md", dir=outbox)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
        quoted = _quote_path(body_path)
        command = "gh pr comment %d --body-file %s" % (number, quoted)
        if quoted is None:
            state, detail = "failed", "Foreman's data directory has a character a shell would expand: %s" % outbox
        else:
            state, detail = _terminal(command, root)
    finally:
        try:
            os.unlink(body_path)
        except OSError:
            pass
    rule = "-" * 40
    where = " (%s)" % name if name else ""
    if state == "background":
        return "\n".join([_outcome_text(state, detail, "", command),
                          "The comment may still be posted on PR #%d%s. Its text:" % (number, where), rule, body, rule])
    if state != "done":
        return "\n".join([_outcome_text(state, detail, "", command),
                          "The comment was NOT posted on PR #%d%s. Its text:" % (number, where), rule, body, rule])
    lines = ["Foreman: posted this comment on PR #%d%s:" % (number, where), rule, body, rule]
    closed = False
    if close:
        close_cmd = "gh pr close %d" % number
        state, detail = _terminal(close_cmd, root)
        closed = state == "done"
        lines.append(_outcome_text(state, detail, "closed PR #%d" % number, close_cmd))
    try:
        from . import pipeline
        if isinstance(v.get("number"), int) and not v.get("error"):
            pipeline.record_rejected(pipeline.pr_ref(root, v), note or "reasons posted", closed)
        else:
            from . import review
            pipeline.record_rejected(pipeline.Ref(name or review.slug_of(Repo(root, budget=5)), root, "pr", number),
                                     note or "reasons posted", closed)
    except Exception:
        logger.warning("foreman: cannot record the rejection on the pipeline", exc_info=True)
    return "\n".join(lines)


# ─── /foreman status, with the pinned repository first ───────────────────────

def cmd_status(args: str = "", keys: tuple = (), platform: Optional[str] = None) -> str:
    from . import commands
    if not args.strip():
        p = pinned(keys)
        root = detector.find_repo(p) if p and os.path.isdir(p) else None
        if root:
            v = commands.verdict(root, *keys, platform=platform)
            if v.get("chosen_from") == "given":
                v["chosen_from"] = PINNED
            return commands.format_verdict(v)
    return commands.cmd_status(args, keys, platform)


def cmd_pipeline(args: str = "", keys: tuple = (), platform: Optional[str] = None) -> str:
    """``/foreman pipeline [<pr>|<branch>]``: one change's stages and its last events; without an argument, the
    current branch's change (or its pull request), else every change of the repository."""
    from . import pipeline, review
    words, root, problem = root_for(args, keys, platform)
    if problem:
        return problem
    repo = Repo(root, budget=10)
    slug = review.slug_of(repo)
    items = pipeline.items_for(slug, root)
    arg = words[0] if words else ""
    number = _pr_number(arg) if arg else None
    if arg:
        found = [i for i in items if (number is not None and i["target"].get("number") == number)
                 or (number is None and i["target"].get("branch") == arg)]
    else:
        branch = repo.branch()
        found = [i for i in items if i["target"].get("branch") == branch]
    if found:
        return pipeline.format_item(found[0], WIDTH)
    if not items:
        return wrap("Foreman: nothing on the pipeline for %s yet. It fills as the gate checks commits and pushes, "
                    "and as `/foreman verdict`, `review`, `merge` and `reject` run." % slug)
    lines = ["Foreman: %s is not on the pipeline. Changes in %s:" % (("`%s`" % arg) if arg else "this branch", slug)]
    lines += pipeline.board_lines(slug, root, WIDTH, limit=20)[1:]
    return "\n".join(lines)


SUBCOMMANDS: dict = {
    "board": (cmd_board, "branch, open PRs, issues they close (the default)"),
    "pipeline": (cmd_pipeline, "[pr|branch] [--repo r]  a change's stages: gate, review, bounces, owner, merge"),
    "use": (cmd_use, "[path|n]  pin the repository for this session"),
    "prs": (cmd_prs, "open PRs: head, CI, the issues each one closes"),
    "issues": (cmd_issues, "open issues and the PR that closes each"),
    "verdict": (cmd_verdict, "[pr|branch] [--repo r]  the verdict, with reasons"),
    "merge": (cmd_merge, "<pr> [--merge|--rebase] [--yes] [--repo r]  if CLEAN and ready, after you confirm; "
                         "with auto_review on, the review must not block it"),
    "reject": (cmd_reject, "<pr> [--close [--yes]] [--repo r] [note]  post the reasons on the PR"),
    "status": (cmd_status, "[path]  this repository's verdict (CLEAN, BLOCKED, INCOMPLETE, NEEDS YOUR OK)"),
}
