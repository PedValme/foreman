"""The ``/foreman`` slash command and the ``foreman_check`` agent tool.

One slash command with subcommands; later slices add more entries to ``SUBCOMMANDS``. Slash commands are typed by
the user: the model has no tool that runs them, which is why ``/foreman allow`` is the place where a person grants
an exception.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Callable, Optional

from . import detector, grants, review
from .detector import MARKER, GitError, Repo
from .gate import HOW, NO_REPOSITORY_HERE, RECORDED, locate

logger = logging.getLogger(__name__)

STATUS_BUDGET_SECONDS = 60.0


def _dedupe(findings: list) -> list:
    seen, out = set(), []
    for f in findings:
        key = (f.rule, f.file, f.line, f.allowed, f.fingerprint)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def verdict(path: Optional[str] = None, *keys: str, platform: Optional[str] = None) -> dict:
    """The verdict for the repository that contains ``path`` (default: the session's directory): the branch against
    its base plus the uncommitted changes. ``chosen_from`` says how the repository was found."""
    if path and os.path.isabs(os.path.expanduser(path)):
        where, how = os.path.expanduser(path), "given"
    else:
        where, how = locate(*keys, platform=platform)
        if where is None:
            if not path:
                return {"verdict": "NO_REPOSITORY", "path": None, "chosen_from": None, "message": NO_REPOSITORY_HERE}
            where = os.getcwd()
        if path:
            where, how = os.path.normpath(os.path.join(where, path)), "given"
    root = detector.find_repo(where)
    if not root:
        return {"verdict": "NO_REPOSITORY", "path": where, "chosen_from": how,
                "message": "%s (%s) is not inside a git repository. Give a path: `/foreman status <path>`."
                           % (where, HOW.get(how, how))}
    repo = Repo(root, budget=STATUS_BUDGET_SECONDS)
    try:
        branch = detector.scan_branch(repo)
        worktree = detector.scan_worktree(repo)
    except GitError as e:
        return {"verdict": "ERROR", "repo": root, "message": str(e)}
    findings = _dedupe(branch.findings + worktree.findings)
    blockers = [f for f in findings if not f.allowed]
    marked = [f for f in findings if f.allowed and not grants.is_granted(f.fingerprint)]
    granted = [f for f in findings if f.allowed and grants.is_granted(f.fingerprint)]
    if marked:
        try:
            grants.record_pending(marked, root)
        except Exception:
            logger.warning("foreman: cannot record pending findings", exc_info=True)
    ahead = None
    if branch.base:
        count = repo.try_git("rev-list", "--count", "%s..HEAD" % branch.base)
        ahead = int(count) if count and count.isdigit() else None
    dirty = repo.try_git("status", "--porcelain")
    return {
        "verdict": "BLOCKED" if blockers or marked else "CLEAN",
        "repo": root,
        "chosen_from": how,
        "branch": repo.branch(),
        "base": branch.base_label,
        "base_sha": branch.base,
        "commits_ahead": ahead,
        "uncommitted_files": len(dirty.splitlines()) if dirty else 0,
        "check": branch.check or worktree.check,
        "blockers": [f.to_dict() for f in blockers],
        "marked": [f.to_dict() for f in marked],
        "allowed_by_user": [f.to_dict() for f in granted],
    }


def _format_finding(d: dict, with_id: bool = False) -> str:
    head = "  [%s] %s — %s" % (d["rule"], d["location"], d["message"])
    return head + (" (id %s)" % d["id"] if with_id else "\n      fix: %s" % d["fix"])


def format_verdict(v: dict) -> str:
    if v["verdict"] == "NO_REPOSITORY" and v.get("path") is None:
        return v.get("message", NO_REPOSITORY_HERE)
    if v["verdict"] in ("NO_REPOSITORY", "ERROR"):
        return "Foreman: %s. %s" % (v["verdict"].replace("_", " ").lower(), v.get("message", ""))
    hint = "" if v.get("chosen_from") in (None, RECORDED, "given") else " (from %s)" % HOW.get(v["chosen_from"], "?")
    lines = ["Foreman: %s" % v["verdict"], "Repository: %s%s" % (v["repo"], hint)]
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
    if v["marked"]:
        lines.append("Marked `%s` by the agent, waiting for you (`/foreman allow <id>` if you agree):" % MARKER)
        lines += [_format_finding(d, with_id=True) for d in v["marked"]]
    if v.get("allowed_by_user"):
        lines.append("Allowed by you:")
        lines += [_format_finding(d, with_id=True) for d in v["allowed_by_user"]]
    if v["verdict"] == "CLEAN":
        lines.append("No skipped, deleted or moved tests, no change to the check, no secrets.")
    return "\n".join(lines)


# ─── /foreman ────────────────────────────────────────────────────────────────

def cmd_status(args: str, keys: tuple = (), platform: Optional[str] = None) -> str:
    return format_verdict(verdict(args.strip() or None, *keys, platform=platform))


def cmd_allow(args: str, keys: tuple = (), platform: Optional[str] = None) -> str:
    short_id = args.strip().split()[0] if args.strip() else ""
    if not short_id:
        items = grants.pending()
        if not items:
            return "Foreman: nothing is waiting for your approval."
        lines = ["Marked `%s` by the agent and waiting for you. Review each one; `/foreman allow <id>` lets that "
                 "exact finding through for 24 hours:" % MARKER]
        for e in items:
            age = int((time.time() - (e.get("created") or time.time())) // 60)
            lines.append("  %s  [%s] %s — %s (%d min ago%s)" % (e.get("id", "?"), e.get("rule", "?"),
                                                              e.get("location", "?"), e.get("message", ""), age,
                                                              ", " + str(e["repo"]) if e.get("repo") else ""))
        return "\n".join(lines)
    ok, entry = grants.grant(short_id)
    if not ok:
        return "Foreman: %s Run `/foreman allow` to list what is waiting." % entry
    return "Foreman: allowed %s [%s] %s for 24 hours. %s" % (entry.get("id", short_id), entry.get("rule", "?"),
                                                            entry.get("location", "?"), _covers(entry.get("rule", "")))


_FILE_RULES = {"check-changed", "check-weakened", "test-moved", "test-deleted"}


def _covers(rule: str) -> str:
    """What a grant really covers, said plainly."""
    if rule in ("test-deleted",):
        return "It covers deleting that file only."
    if rule in _FILE_RULES:
        return ("It covers this version of that file only: any further change to the file is checked again and "
                "needs a new decision.")
    if rule == "test-skipped":
        return ("It covers that marked line above that same test only: the line changed, or copied above another "
                "test, is checked again.")
    return "It covers that exact line only: any change to it is checked again."


def cmd_help(args: str = "", keys: tuple = (), platform: Optional[str] = None) -> str:
    lines = ["Foreman: a green check the agent did not rig.", "", "Usage: /foreman <subcommand>"]
    lines += ["  %-14s %s" % (name, doc) for name, (_fn, doc) in SUBCOMMANDS.items()]
    lines += ["",
              "Foreman blocks git commit, git push, gh pr create and gh pr merge when the change skips, deletes or "
              "moves tests, edits or weakens what the check runs, bypasses hooks or carries a secret.",
              "A false positive is marked on its line with `%s` (or, for a file, a commit-message line `%s <path>: "
              "<reason>`). The mark never passes alone: it waits until you run `/foreman allow <id>`." % (MARKER, MARKER),
              "Pull requests and issues come from the GitHub CLI (`gh`) with its own login. `/foreman merge` and "
              "`/foreman reject` write to GitHub only when you type them, through Hermes's terminal tool."]
    return "\n".join(lines)


SUBCOMMANDS: dict = {
    "status": (cmd_status, "[path]  verdict for the current repository: CLEAN or BLOCKED, with reasons"),
    "allow": (cmd_allow, "[id]  list findings the agent marked, or allow one of them (you only)"),
    **review.SUBCOMMANDS,
    "help": (cmd_help, "this help"),
}

from . import board as _board  # noqa: E402  (board.py imports this module lazily)

SUBCOMMANDS.update(_board.SUBCOMMANDS)


def handle_slash(raw_args: str = "", session_id: str = "", session_key: str = "", **kwargs) -> str:
    try:
        parts = (raw_args or "").strip().split(None, 1)
        name = parts[0].lower() if parts else "board"
        rest = parts[1] if len(parts) > 1 else ""
        entry = SUBCOMMANDS.get(name)
        if entry is None:
            return "Unknown subcommand `%s`.\n\n%s" % (name, cmd_help())
        fn: Callable[..., str] = entry[0]
        keys = tuple(k for k in (session_key, session_id) if isinstance(k, str) and k)
        platform = kwargs.get("platform")
        return fn(rest, keys, platform if isinstance(platform, str) else None)
    except Exception as e:
        logger.warning("foreman: /foreman failed", exc_info=True)
        return "Foreman failed: %s: %s" % (type(e).__name__, e)


# ─── foreman_check tool ──────────────────────────────────────────────────────

TOOL_SCHEMA = {
    "name": "foreman_check",
    "description": (
        "Foreman's deterministic verdict for a git repository: whether the current branch (against its base) and "
        "the uncommitted changes skip, isolate, delete or move tests, change or weaken what the check runs, or add "
        "secrets. Returns JSON with verdict CLEAN or BLOCKED, and each finding's file, line, rule and how to fix "
        "it. Call it before committing or opening a pull request."),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string",
                     "description": "A path inside the repository; default: the session's working directory."},
        },
        "required": [],
    },
}


def foreman_check_tool(args: dict = None, task_id: str = "", **kwargs) -> str:
    try:
        path = (args or {}).get("path")
        keys = (task_id,) if isinstance(task_id, str) and task_id else ()
        return json.dumps(verdict(path if isinstance(path, str) and path.strip() else None, *keys))
    except Exception as e:
        return json.dumps({"verdict": "ERROR", "message": "%s: %s" % (type(e).__name__, e)})
