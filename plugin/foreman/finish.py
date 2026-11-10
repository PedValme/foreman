"""``auto_review: finish``: the review loop inside the agent's turn, and the ``foreman_review`` agent tool.

The loop never calls a model from a hook. ``pre_verify`` (``step``) only reads: when the deterministic gate is
CLEAN and the change has no stored review for its exact diff, it asks the agent to call ``foreman_review``; when the
stored review of that diff has BLOCKING or HIGH findings, it sends the change back with them (one bounce). It stops
at ``max_bounces`` (never more than Hermes's own nudge bound) and hands the change to the owner.

``foreman_review`` is advisory: it never grants, merges, approves or unblocks. It calls the reviewer model only
when ``auto_review`` is ``finish`` and the bounce limit is not reached; at any other level it returns the stored
review of this exact diff, or says to ask the user to run ``/foreman review``. A stored review of the same diff by
the same reviewer is never re-run (``review.run_review`` cache), so the agent cannot re-roll a verdict.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

from . import detector, pipeline, review
from .detector import Repo
from .gate import NO_REPOSITORY_HERE, locate

logger = logging.getLogger(__name__)

TOOL_ADVISORY = ("Advisory only: this review never grants an exception, merges, approves or unblocks anything; "
                 "only the user does that.")
MAX_LISTED = 10


def _finding_lines(findings: list) -> list:
    out = []
    for f in findings[:MAX_LISTED]:
        where = "%s:%d" % (f.get("file"), f["line"]) if f.get("line") else str(f.get("file"))
        out.append("- [%s] %s - %s" % (f.get("severity"), where, f.get("title")))
        if f.get("why"):
            out.append("  Why: %s" % f["why"])
        if f.get("fix"):
            out.append("  Fix: %s" % f["fix"])
    if len(findings) > MAX_LISTED:
        out.append("- ... and %d more (run `foreman_review` to see them)" % (len(findings) - MAX_LISTED))
    return out


def fix_message(findings: list, bounces: int, limit: int) -> str:
    return "\n".join(
        ["Foreman's second-model review sent this change back (bounce %d of %d). Fix each BLOCKING and HIGH "
         "finding before you finish:" % (bounces, limit)]
        + _finding_lines(findings)
        + ["Then finish; Foreman reviews the new diff (call `foreman_review`). If a finding is wrong, tell the user "
           "why instead of working around it. The review is advisory: it grants, merges and unblocks nothing."])


REVIEW_FIRST = ("Foreman (auto_review: finish): this change has no second-model review yet. Call the "
                "`foreman_review` tool now, then fix every BLOCKING and HIGH finding it reports before you finish. "
                "If a finding is wrong, tell the user why instead of working around it.")


def step(root: str, session_id: str, attempt: int, deadline: Optional[float] = None) -> Optional[dict]:
    """The finish loop's decision at ``pre_verify`` for the repository at ``root``, whose deterministic gate is
    CLEAN. None lets the turn finish."""
    if pipeline.level() != "finish":
        return None
    if attempt >= pipeline.hermes_nudge_bound():
        return None  # Hermes stops calling anyway
    repo = Repo(root, deadline=deadline)
    diff, _label, _omitted = review.worktree_diff(repo)
    if not diff.strip():
        return None
    key = review.current_cache_key(diff)
    ref = pipeline.local_ref(root, deadline=deadline)
    turn = "turn:%s|%s" % (session_id, ref.id)  # cleared by gate.on_pre_verify at each new turn (attempt 0)
    stored = review.cache_load(key)
    limit = pipeline.max_bounces()
    if stored and stored.get("error") and int(stored.get("failures") or 0) >= review.MAX_AUTO_TRIES:
        pipeline.record_review(ref, stored)
        return None  # the review cannot run on this diff: the tool would not call it again; the user decides
    if stored and not stored.get("error"):
        bad = pipeline.blocking_findings(stored)
        if not bad:
            pipeline.record_review(ref, stored, then="ready")  # ready only on PASS / PASS WITH NOTES
            return None
        state = pipeline.record_review(ref, stored, bounce=True)
        if state["bounces"] >= state["max_bounces"]:
            return None  # the limit: the owner was notified; no more nudges
        if not pipeline.nudge_mark(turn, key):
            return None  # this turn was already nudged for this exact diff
        return {"action": "continue", "message": fix_message(bad, state["bounces"], state["max_bounces"])}
    item = pipeline.find(ref)
    bounces = int((item or {}).get("bounces") or 0)
    if bounces >= limit:
        pipeline.record_needs_owner(ref, "bounce limit reached (%d of %d): the latest changes are not reviewed; "
                                         "Foreman stops sending it back" % (bounces, limit))
        return None
    calls, budget = pipeline.model_calls(ref), pipeline.review_budget()
    if calls >= budget:
        pipeline.record_needs_owner(ref, "review budget used up (%d model calls): the latest changes are not "
                                         "reviewed; `/foreman review --fresh` reviews them" % calls)
        return None
    if not pipeline.nudge_mark(turn, key):
        return None  # this turn was already nudged for this exact diff; the agent did not call the tool
    return {"action": "continue", "message": REVIEW_FIRST}


# ─── foreman_review tool ─────────────────────────────────────────────────────

TOOL_SCHEMA = {
    "name": "foreman_review",
    "description": (
        "Foreman's second-model review of the current branch and its uncommitted changes, against the base. "
        "Returns JSON: verdict (PASS, PASS WITH NOTES, BLOCKED, COULD NOT RUN, NOTHING TO REVIEW or NOT REVIEWED), "
        "the verified findings (severity BLOCKING, HIGH or MEDIUM; file, line, why, fix) and what to do next. Fix "
        "every BLOCKING and HIGH finding before you finish. The result for the same diff is stored and returned "
        "again: calling it twice does not produce a new review. It calls a model only when the user set "
        "auto_review to finish. Advisory: it never grants, merges, approves or unblocks anything."),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string",
                     "description": "A path inside the repository; default: the session's working directory."},
        },
        "required": [],
    },
}


def _summary(rec: dict) -> dict:
    keep = ("severity", "file", "line", "title", "why", "fix")
    return {"verdict": rec.get("verdict"), "cached": bool(rec.get("cached")),
            "reviewed_at": rec.get("time"), "head": rec.get("head"),
            "findings": [{k: f.get(k) for k in keep} for f in rec.get("findings") or []],
            "dropped_unverified": rec.get("dropped_unverified", 0),
            "coverage": (rec.get("coverage") or {}).get("note"),
            "gate": (rec.get("deterministic") or {}).get("verdict"),
            "gate_findings": (rec.get("deterministic") or {}).get("findings") or [],
            "model": rec.get("model"), "error": rec.get("error"), "summary": rec.get("summary", "")}


def foreman_review_tool(args: dict = None, task_id: str = "", **kwargs) -> str:
    pipeline.flush_notifications()  # outside any hook: send what hooks queued
    try:
        return json.dumps(_tool(args or {}, task_id if isinstance(task_id, str) else ""))
    except Exception as e:  # noqa: BLE001 — a tool result, never a crash
        logger.warning("foreman: foreman_review failed", exc_info=True)
        return json.dumps({"verdict": "ERROR", "message": "%s: %s" % (type(e).__name__, e),
                           "advisory": TOOL_ADVISORY})


def _tool(args: dict, task_id: str) -> dict:
    keys = (task_id,) if task_id else ()
    path = args.get("path") if isinstance(args.get("path"), str) and args.get("path").strip() else None
    if path and os.path.isabs(os.path.expanduser(path)):
        where = os.path.expanduser(path)
    else:
        where, _how = locate(*keys)
        if where and path:
            where = os.path.join(where, path)
    root = detector.find_repo(where) if where else None
    if not root:
        return {"verdict": "NO_REPOSITORY", "message": NO_REPOSITORY_HERE, "advisory": TOOL_ADVISORY}
    lvl = pipeline.level()
    allow, limit_note = lvl == "finish", ""
    ref = pipeline.local_ref(root)
    if allow:
        item = pipeline.find(ref)
        bounces, limit = int((item or {}).get("bounces") or 0), pipeline.max_bounces()
        calls, budget = pipeline.model_calls(ref), pipeline.review_budget()
        if bounces >= limit:
            allow = False
            limit_note = ("The bounce limit is reached (%d of %d): Foreman will not call the reviewer again for this "
                          "change. Tell the user; they decide." % (bounces, limit))
        elif calls >= budget:
            allow = False
            limit_note = ("The review budget for this change is used up (%d model calls): Foreman will not call the "
                          "reviewer again for it. Tell the user; they can run `/foreman review --fresh`." % calls)
    rec = review.run_review("", keys, where=root, allow_model=allow)
    if rec.get("verdict") in ("NO_REPOSITORY", "ERROR"):
        return {"verdict": rec["verdict"], "message": rec.get("message", ""), "advisory": TOOL_ADVISORY}
    if allow and not rec.get("cached") and rec.get("model") is not None:
        pipeline.count_model_call(ref)  # a model call was made for this change
    last_review = None
    if rec["verdict"] == review.NOT_REVIEWED and limit_note:
        last = review.load(rec.get("slug") or ref.slug, "worktree", ref.branch, root)
        if last and not last.get("error"):  # the last stored result, of an earlier diff of this change
            last_review = dict(_summary(last), note="the last stored review, of an earlier diff of this change; "
                                                    "the current diff is not reviewed")
    state = review.record_in_pipeline(rec, bounce=lvl == "finish") or {}
    out = _summary(rec)
    if last_review:
        out["last_review"] = last_review
    out["auto_review"] = lvl
    out["advisory"] = TOOL_ADVISORY
    bad = pipeline.blocking_findings(rec)
    if rec["verdict"] == review.NOT_REVIEWED:
        out["next"] = limit_note or (
            "No stored review of this exact diff, and auto_review is `%s`: Foreman calls no model from this tool. "
            "Ask the user to run `/foreman review` if they want one." % lvl)
    elif bad:
        n = state.get("bounces")
        out["bounce"] = "%s of %s" % (n, state.get("max_bounces")) if n else None
        out["next"] = ("Fix every BLOCKING and HIGH finding before you finish; if one is wrong, tell the user why. "
                       + (limit_note or ("This was the last bounce: the user decides now."
                                         if state.get("limit") else "")))
    elif rec["verdict"] == "COULD NOT RUN":
        out["next"] = "The review could not run; tell the user (they can run `/foreman review`)."
    elif rec["verdict"] == "BLOCKED":
        out["next"] = "The deterministic gate blocks this change: fix what `foreman_check` reports."
    else:
        out["next"] = "No BLOCKING or HIGH findings. Finish and tell the user; a person merges."
    if rec.get("cached"):
        out["cached_note"] = "Same diff as a stored review: the model was not called again."
    return out
