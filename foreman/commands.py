"""The ``/foreman`` slash command and the ``foreman_check`` agent tool.

One slash command with subcommands; later slices add more entries to ``SUBCOMMANDS``.
"""
from __future__ import annotations

import json
import logging
from typing import Callable, Optional

from . import detector
from .detector import GitError, Repo
from .gate import session_cwd

logger = logging.getLogger(__name__)

STATUS_BUDGET_SECONDS = 60.0


def _dedupe(findings: list) -> list:
    seen, out = set(), []
    for f in findings:
        key = (f.rule, f.file, f.line, f.allowed)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def verdict(path: Optional[str] = None) -> dict:
    """The verdict for the repository that contains ``path`` (default: the session's directory): the branch against
    its base plus the uncommitted changes."""
    where = path or session_cwd()
    root = detector.find_repo(where)
    if not root:
        return {"verdict": "NO_REPOSITORY", "path": where,
                "message": "%s is not inside a git repository." % where}
    repo = Repo(root, budget=STATUS_BUDGET_SECONDS)
    try:
        branch = detector.scan_branch(repo)
        worktree = detector.scan_worktree(repo)
    except GitError as e:
        return {"verdict": "ERROR", "repo": root, "message": str(e)}
    findings = _dedupe(branch.findings + worktree.findings)
    blockers = [f for f in findings if not f.allowed]
    allowed = [f for f in findings if f.allowed]
    ahead = None
    if branch.base:
        count = repo.try_git("rev-list", "--count", "%s..HEAD" % branch.base)
        ahead = int(count) if count and count.isdigit() else None
    dirty = repo.try_git("status", "--porcelain")
    return {
        "verdict": "BLOCKED" if blockers else ("NEEDS_APPROVAL" if allowed else "CLEAN"),
        "repo": root,
        "branch": repo.branch(),
        "base": branch.base_label,
        "base_sha": branch.base,
        "commits_ahead": ahead,
        "uncommitted_files": len(dirty.splitlines()) if dirty else 0,
        "check": branch.check or worktree.check,
        "blockers": [f.to_dict() for f in blockers],
        "allowed": [f.to_dict() for f in allowed],
    }


def _format_finding(d: dict) -> str:
    return "  [%s] %s  %s\n      fix: %s" % (d["rule"], d["location"], d["message"], d["fix"])


def format_verdict(v: dict) -> str:
    if v["verdict"] in ("NO_REPOSITORY", "ERROR"):
        return "Foreman: %s. %s" % (v["verdict"].replace("_", " ").lower(), v.get("message", ""))
    lines = ["Foreman: %s" % v["verdict"], "Repository: %s" % v["repo"]]
    if v.get("base"):
        ahead = v.get("commits_ahead")
        lines.append("Branch: %s vs %s%s" % (v["branch"], v["base"],
                                             "" if ahead is None else " (%d commit(s) ahead)" % ahead))
    else:
        lines.append("Branch: %s (no base branch found; only uncommitted changes are checked)" % v["branch"])
    lines.append("Uncommitted files: %d" % v.get("uncommitted_files", 0))
    if v.get("check"):
        lines.append("Check command (from the base): %s" % v["check"])
    if v["blockers"]:
        lines.append("Blockers:")
        lines += [_format_finding(d) for d in v["blockers"]]
    if v["allowed"]:
        lines.append("Marked `%s` (a person must approve):" % detector.MARKER)
        lines += [_format_finding(d) for d in v["allowed"]]
    if v["verdict"] == "CLEAN":
        lines.append("No skipped, deleted or moved tests, no change to the check, no secrets.")
    return "\n".join(lines)


# ─── /foreman ────────────────────────────────────────────────────────────────

def cmd_status(args: str) -> str:
    return format_verdict(verdict(args.strip() or None))


def cmd_help(args: str = "") -> str:
    lines = ["Foreman: a green check the agent did not rig.", "", "Usage: /foreman <subcommand>"]
    lines += ["  %-8s %s" % (name, doc) for name, (_fn, doc) in SUBCOMMANDS.items()]
    lines += ["", "Foreman blocks git commit, git push, gh pr create and gh pr merge when the change skips, deletes or "
              "moves tests, edits what the check runs, bypasses hooks or carries a secret."]
    return "\n".join(lines)


SUBCOMMANDS: dict = {
    "status": (cmd_status, "verdict for the current repository [path]: CLEAN or BLOCKED, with reasons"),
    "help": (cmd_help, "this help"),
}


def handle_slash(raw_args: str = "", **kwargs) -> str:
    try:
        parts = (raw_args or "").strip().split(None, 1)
        name = parts[0].lower() if parts else "status"
        rest = parts[1] if len(parts) > 1 else ""
        entry = SUBCOMMANDS.get(name)
        if entry is None:
            return "Unknown subcommand `%s`.\n\n%s" % (name, cmd_help())
        fn: Callable[[str], str] = entry[0]
        return fn(rest)
    except Exception as e:
        logger.warning("foreman: /foreman failed", exc_info=True)
        return "Foreman failed: %s: %s" % (type(e).__name__, e)


# ─── foreman_check tool ──────────────────────────────────────────────────────

TOOL_SCHEMA = {
    "name": "foreman_check",
    "description": (
        "Foreman's deterministic verdict for a git repository: whether the current branch (against its base) and "
        "the uncommitted changes skip, isolate, delete or move tests, change what the check command runs, or add "
        "secrets. Returns JSON with verdict CLEAN, BLOCKED or NEEDS_APPROVAL, and each finding's file, line, rule "
        "and how to fix it. Call it before committing or opening a pull request."),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string",
                     "description": "A path inside the repository; default: the session's working directory."},
        },
        "required": [],
    },
}


def foreman_check_tool(args: dict = None, **kwargs) -> str:
    try:
        path = (args or {}).get("path")
        return json.dumps(verdict(path if isinstance(path, str) and path.strip() else None))
    except Exception as e:
        return json.dumps({"verdict": "ERROR", "message": "%s: %s" % (type(e).__name__, e)})
