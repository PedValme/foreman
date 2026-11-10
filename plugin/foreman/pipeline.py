"""The pipeline: one state per change (a pull request or a branch), from the gate to the merge.

write -> gate -> second-model review -> bounce back to the agent -> ready -> the owner approves -> merge

The state lives in the plugin data directory as ``pipeline.json`` (written atomically; a missing or damaged file
starts empty; nothing here ever raises into a hook). Its shape is a contract with the messaging notifier and the
Desktop panel::

    {"version": 1, "items": [{
      "id": "owner/repo#pr:6" | "owner/repo#branch:feat/x" | "local/<dirname>#branch:x",
      "repo": "owner/repo", "root": "/abs/path",
      "target": {"kind": "pr" | "branch", "number": 6 | null, "branch": "feat/x", "title": "...", "url": "..." | null},
      "head": "<full sha>" | null,
      "stage": "gate|review|bounced|ready|awaiting_owner|merged|rejected",
      "stages": [{"name": "gate", "status": "pass|fail|pending|skipped", "detail": "...", "at": "<ISO UTC>"},
                 {"name": "review", "status": "pass|notes|fail|pending|skipped|error", "detail": "...",
                  "model": "provider/model" | null, "at": "..."},
                 {"name": "owner", "status": "pending|approved|rejected|skipped", "detail": "", "at": "..."},
                 {"name": "merge", "status": "pending|done|refused|skipped", "detail": "squash", "at": "..."}],
      "bounces": 1, "max_bounces": 3, "updated": "<ISO UTC>",
      "events": [{"at": "...", "text": "..."}]}]}            # newest last, at most 50

Bookkeeping that is not part of that contract (notifications already sent, which diff a turn was nudged for,
which reviews counted as a bounce) lives next to it in ``pipeline-meta.json``. Both files are Foreman's store: the
agent cannot write them (``gate.STORE_FILES``).
"""
from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time
from typing import Any, Callable, Optional

from . import grants

logger = logging.getLogger(__name__)

PIPELINE_FILE = "pipeline.json"
META_FILE = "pipeline-meta.json"
VERSION = 1
MAX_ITEMS = 200
MAX_EVENTS = 50
MAX_NOTIFIED = 2000
MAX_PENDING = 100
MAX_SEND_PER_CALL = 3
STAGES = ("gate", "review", "bounced", "ready", "awaiting_owner", "merged", "rejected")
STATUSES = {"gate": ("pass", "fail", "pending", "skipped"),
            "review": ("pass", "notes", "fail", "pending", "skipped", "error"),
            "owner": ("pending", "approved", "rejected", "skipped"),
            "merge": ("pending", "done", "refused", "skipped")}
DONE = ("merged", "rejected")
LEVELS = ("merge", "finish", "off")
DEFAULT_LEVEL = "merge"
DEFAULT_MAX_BOUNCES = 3
NOTIFY_KINDS = ("ready", "needs_owner", "merged", "rejected")

# Tests replace these: the clock (epoch seconds), the settings and the notifier.
CLOCK: Callable[[], float] = time.time
SETTINGS_OVERRIDE: Optional[dict] = None
NOTIFIER: Optional[Callable[[dict], Any]] = None

_lock = threading.Lock()


# ─── Settings ────────────────────────────────────────────────────────────────

def _ctx():
    from . import review
    return review._CTX


def setting(key: str, default: Any = None) -> Any:
    if SETTINGS_OVERRIDE is not None:
        return SETTINGS_OVERRIDE.get(key, default)
    ctx = _ctx()
    try:
        value = ctx.get_config(key, default) if ctx is not None else default
    except Exception:
        return default
    return default if value is None else value


def level() -> str:
    """``auto_review``: merge (the default), finish or off. Anything else counts as merge."""
    raw = setting("auto_review", DEFAULT_LEVEL)
    if raw is False:  # YAML 1.1 reads an unquoted `off` as false
        return "off"
    value = str(raw or DEFAULT_LEVEL).strip().lower()
    return value if value in LEVELS else DEFAULT_LEVEL


def hermes_nudge_bound() -> int:
    """Hermes's own bound on consecutive pre_verify nudges in one turn (``agent.max_verify_nudges``, default 3)."""
    try:
        from . import review
        agent = review.hermes_config().get("agent")
        value = agent.get("max_verify_nudges") if isinstance(agent, dict) else None
        return max(1, int(value)) if value is not None else 3
    except Exception:
        return 3


def max_bounces() -> int:
    """``max_bounces`` (default 3), at least 1 and never more than Hermes's own nudge bound."""
    try:
        wanted = int(setting("max_bounces", DEFAULT_MAX_BOUNCES))
    except (TypeError, ValueError):
        wanted = DEFAULT_MAX_BOUNCES
    return max(1, min(wanted, hermes_nudge_bound()))


# ─── Time ────────────────────────────────────────────────────────────────────

def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(CLOCK()))


# ─── Store ───────────────────────────────────────────────────────────────────

def _path(name: str) -> str:
    return os.path.join(grants.store_dir(), name)


def _read(name: str) -> Any:
    try:
        with open(_path(name), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write(name: str, data: Any) -> None:
    path = _path(name)
    fd, tmp = tempfile.mkstemp(prefix=".pipeline-", dir=os.path.dirname(path))
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


def _valid_item(item: Any) -> bool:
    return (isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("target"), dict)
            and isinstance(item.get("stages"), list) and isinstance(item.get("events"), list))


def _load() -> dict:
    data = _read(PIPELINE_FILE)
    if not isinstance(data, dict) or data.get("version") != VERSION or not isinstance(data.get("items"), list):
        return {"version": VERSION, "items": []}
    return {"version": VERSION, "items": [i for i in data["items"] if _valid_item(i)]}


def _load_meta() -> dict:
    data = _read(META_FILE)
    data = data if isinstance(data, dict) else {}
    notified = data.get("notified")
    nudged = data.get("nudged")
    counted = data.get("counted")
    pending = data.get("pending_notifications")
    calls = data.get("model_calls")
    return {"notified": [n for n in notified if isinstance(n, str)] if isinstance(notified, list) else [],
            "nudged": {k: v for k, v in nudged.items() if isinstance(k, str) and isinstance(v, str)}
            if isinstance(nudged, dict) else {},
            "counted": {k: [x for x in v if isinstance(x, str)] for k, v in counted.items()
                        if isinstance(k, str) and isinstance(v, list)} if isinstance(counted, dict) else {},
            "pending_notifications": [e for e in pending if isinstance(e, dict)][-MAX_PENDING:]
            if isinstance(pending, list) else [],
            "model_calls": {k: v for k, v in calls.items() if isinstance(k, str) and isinstance(v, int)
                            and not isinstance(v, bool)} if isinstance(calls, dict) else {}}


def _prune(data: dict, meta: dict) -> None:
    items = data["items"]
    if len(items) > MAX_ITEMS:
        # the oldest finished items go first, then the oldest of the rest
        order = sorted(range(len(items)), key=lambda i: (items[i].get("stage") not in DONE,
                                                          str(items[i].get("updated") or "")))
        drop = set(order[:len(items) - MAX_ITEMS])
        data["items"] = [it for i, it in enumerate(items) if i not in drop]
    meta["nudged"] = dict(list(meta["nudged"].items())[-MAX_ITEMS * 2:])
    ids = {i["id"] for i in data["items"]}
    meta["counted"] = {k: v[-20:] for k, v in meta["counted"].items() if k in ids}
    budgets = {_budget_key(i) for i in data["items"]}
    meta["model_calls"] = {k: v for k, v in meta["model_calls"].items() if k in budgets}
    meta["notified"] = meta["notified"][-MAX_NOTIFIED:]
    if len(meta["pending_notifications"]) > MAX_PENDING:
        logger.warning("foreman: %d queued notification(s) dropped (more than %d waiting)",
                       len(meta["pending_notifications"]) - MAX_PENDING, MAX_PENDING)
        meta["pending_notifications"] = meta["pending_notifications"][-MAX_PENDING:]


# ─── Inside a hook ───────────────────────────────────────────────────────────

# Set by the hook wrappers (gate.on_pre_tool_call, gate.on_pre_verify) for the duration of the hook call. Inside a
# hook nothing is sent: a notification runs `hermes send` (up to 60 s) and Hermes gives a hook callback about 30 s.
_IN_HOOK: contextvars.ContextVar = contextvars.ContextVar("foreman_in_hook", default=False)


@contextlib.contextmanager
def hook_context():
    token = _IN_HOOK.set(True)
    try:
        yield
    finally:
        _IN_HOOK.reset(token)


def in_hook() -> bool:
    return bool(_IN_HOOK.get())


def flush_notifications() -> None:
    """Send the notifications queued inside hooks. Called from non-hook entry points (every /foreman command, the
    tool handlers) and by every non-hook update. Never raises; does nothing inside a hook."""
    if in_hook():
        return
    try:
        with _lock:
            waiting = bool(_load_meta()["pending_notifications"])
    except Exception:
        return
    if waiting:
        _mutate(lambda data, meta: None)


def snapshot() -> dict:
    """The whole state, in the contract's shape."""
    with _lock:
        return _load()


def _mutate(fn: Callable[[dict, dict], Any]) -> Any:
    """Apply ``fn(data, meta)`` under the lock and save both files; send the notifications it queued after saving.
    Never raises: the pipeline is a record, and a failure to keep it must not break a hook or a command."""
    try:
        with _lock:
            data, meta = _load(), _load_meta()
            meta["_outbox"] = []
            result = fn(data, meta)
            outbox = meta.pop("_outbox")
            if in_hook():  # queued, sent later from outside the hook (each event was de-duplicated when queued)
                meta["pending_notifications"].extend(outbox)
                outbox = []
            else:  # a few at a time, so one command never waits on a long backlog of `hermes send`
                waiting = meta["pending_notifications"] + outbox
                outbox, meta["pending_notifications"] = waiting[:MAX_SEND_PER_CALL], waiting[MAX_SEND_PER_CALL:]
            _prune(data, meta)
            _write(PIPELINE_FILE, data)
            _write(META_FILE, meta)
    except Exception:
        logger.warning("foreman: cannot update the pipeline", exc_info=True)
        return None
    _panel_changed()
    for event in outbox:
        _send(event)
    return result


def _panel_changed() -> None:
    """Tell an open Desktop panel that ``pipeline.json`` changed (it polls anyway). Never raises."""
    try:
        from . import panel_api
        panel_api.notify_changed()
    except Exception:
        logger.debug("foreman: cannot tell the panel", exc_info=True)


def _send(event: dict) -> None:
    sender = NOTIFIER
    if sender is None:
        try:
            from . import notify  # written by another slice; may not exist
            sender = getattr(notify, "send", None)
        except Exception:
            sender = None
    if not callable(sender):
        return
    try:
        sender(event)
    except Exception:
        logger.warning("foreman: the notifier failed", exc_info=True)


# ─── Items ───────────────────────────────────────────────────────────────────

class Ref:
    """Which change: a pull request or a branch of a repository."""

    def __init__(self, slug: str, root: str, kind: str = "branch", number: Optional[int] = None,
                 branch: str = "", title: str = "", url: Optional[str] = None, head: Optional[str] = None):
        self.slug, self.root, self.kind, self.number = slug or "local/unknown", root or "", kind, number
        self.branch, self.title, self.url, self.head = branch or "", title or "", url, head or None

    @property
    def id(self) -> str:
        if self.kind == "pr":
            return "%s#pr:%d" % (self.slug, self.number)
        return "%s#branch:%s" % (self.slug, self.branch)


def item_id(slug: str, kind: str, ref) -> str:
    return "%s#pr:%s" % (slug, ref) if kind == "pr" else "%s#branch:%s" % (slug, ref)


def _stages(at: str) -> list:
    return [{"name": "gate", "status": "pending", "detail": "", "at": at},
            {"name": "review", "status": "pending", "detail": "", "model": None, "at": at},
            {"name": "owner", "status": "pending", "detail": "", "at": at},
            {"name": "merge", "status": "pending", "detail": "", "at": at}]


def _new_item(ref: Ref, at: str) -> dict:
    return {"id": ref.id, "repo": ref.slug, "root": ref.root,
            "target": {"kind": ref.kind, "number": ref.number if ref.kind == "pr" else None, "branch": ref.branch,
                       "title": ref.title, "url": ref.url if ref.kind == "pr" else None},
            "head": ref.head, "stage": "gate", "stages": _stages(at), "bounces": 0, "max_bounces": max_bounces(),
            "updated": at, "events": []}


def stage_of(item: dict, name: str) -> dict:
    for s in item["stages"]:
        if isinstance(s, dict) and s.get("name") == name:
            return s
    s = {"name": name, "status": "pending", "detail": "", "at": item.get("updated") or now_iso()}
    if name == "review":
        s["model"] = None
    item["stages"].append(s)
    return s


def _find(data: dict, ref: Ref) -> Optional[dict]:
    """The item for ``ref``. A branch with an open pull request item is that item; a pull request takes over an
    active item of its branch (same repository), so one change keeps one line."""
    items = data["items"]
    by_id = next((i for i in items if i["id"] == ref.id), None)
    if by_id is not None:
        return by_id
    if ref.kind == "branch" and ref.branch:
        return next((i for i in reversed(items) if i.get("repo") == ref.slug and i["target"].get("kind") == "pr"
                     and i["target"].get("branch") == ref.branch and i.get("stage") not in DONE), None)
    if ref.kind == "pr" and ref.branch:
        own = next((i for i in items if i.get("repo") == ref.slug and i["target"].get("kind") == "branch"
                    and i["target"].get("branch") == ref.branch and i.get("stage") not in DONE), None)
        if own is not None:
            own["id"] = ref.id
            own["target"].update(kind="pr", number=ref.number, url=ref.url)
            return own
    return None


def _ensure(data: dict, ref: Ref, at: str) -> dict:
    item = _find(data, ref)
    if item is not None and ref.kind == "branch" and item["target"].get("kind") == "pr":
        # the local branch of an open pull request: its HEAD is not the pull request's head on GitHub
        ref = Ref(ref.slug, ref.root, "branch", branch=ref.branch, title=ref.title)
    if item is None:
        item = _new_item(ref, at)
        data["items"].append(item)
    elif item.get("stage") in DONE and ref.head and ref.head != item.get("head"):
        # a finished change whose branch moved on: a new round on the same line
        fresh = _new_item(ref, at)
        fresh["events"] = item["events"]
        item.clear()
        item.update(fresh)
    elif ref.head and item.get("head") and ref.head != item["head"] and item.get("stage") not in DONE:
        # new commits: what was reviewed and approved was another head
        for name in ("review", "owner", "merge"):
            s = stage_of(item, name)
            if s.get("status") != "pending":
                s.update(status="pending", detail="", at=at)
        if item.get("stage") in ("ready", "awaiting_owner", "review", "bounced"):
            item["stage"] = "gate" if stage_of(item, "gate").get("status") != "pass" else "review"
    t = item["target"]
    if ref.title:
        t["title"] = ref.title
    if ref.kind == "pr" and ref.url:
        t["url"] = ref.url
    if ref.branch and not t.get("branch"):
        t["branch"] = ref.branch
    if ref.root:
        item["root"] = ref.root
    if ref.head:
        item["head"] = ref.head
    item["max_bounces"] = max_bounces()
    item["updated"] = at
    return item


def _event(item: dict, text: str, at: str) -> None:
    item["events"].append({"at": at, "text": _one_line(text, 300)})
    del item["events"][:-MAX_EVENTS]


def _one_line(text: str, limit: int) -> str:
    one = " ".join(str(text or "").split())
    return one if len(one) <= limit else one[:limit - 3].rstrip() + "..."


def _label(item: dict) -> str:
    t = item["target"]
    return "PR #%s" % t.get("number") if t.get("kind") == "pr" else "branch %s" % t.get("branch")


def _actions(item: dict, kind: str) -> list:
    t = item["target"]
    if t.get("kind") == "pr":
        n = t.get("number")
        if kind == "ready":
            return [{"label": "Merge", "command": "/foreman merge %s --yes" % n},
                    {"label": "Reject", "command": "/foreman reject %s" % n}]
        if kind == "needs_owner":
            return [{"label": "Details", "command": "/foreman pipeline %s" % n},
                    {"label": "Reject", "command": "/foreman reject %s" % n}]
        return []
    if kind in ("ready", "needs_owner"):
        return [{"label": "Details", "command": "/foreman pipeline %s" % t.get("branch")}]
    return []


def _queue(meta: dict, item: dict, kind: str, summary: str, notes: bool = False) -> None:
    """Queue one notification of ``kind`` for this item and head, at most once. A "ready" with review notes offers
    the merge without ``--yes``, so the notes are in the question a person answers."""
    key = "%s|%s|%s" % (kind, item["id"], item.get("head") or "")
    if key in meta["notified"]:
        return
    meta["notified"].append(key)
    actions = _actions(item, kind)
    if notes:
        actions = [dict(a, command=a["command"].replace(" --yes", "")) for a in actions]
    meta["_outbox"].append({"kind": kind, "id": item["id"], "repo": item.get("repo"), "root": item.get("root"),
                            "target": dict(item["target"]), "head": item.get("head"),
                            "summary": _one_line(summary, 200), "actions": actions})


# ─── Recording ───────────────────────────────────────────────────────────────

def record_gate(ref: Ref, status: str, detail: str = "", event: str = "") -> None:
    """The deterministic gate's verdict: pass, fail or pending (INCOMPLETE, or marked findings waiting)."""
    if status not in STATUSES["gate"]:
        return

    def apply(data, meta):
        at = now_iso()
        item = _ensure(data, ref, at)
        s = stage_of(item, "gate")
        same = s.get("status") == status and s.get("detail") == _one_line(detail, 200)
        s.update(status=status, detail=_one_line(detail, 200), at=at)
        if item["stage"] not in DONE:
            if status != "pass":
                item["stage"] = "gate"
            elif item["stage"] == "gate":
                item["stage"] = "review"
        last = item["events"][-1].get("text") if item["events"] else None
        if event and not (same and (status == "pass" or last == _one_line(event, 300))):  # no repeated lines
            _event(item, event, at)
    _mutate(apply)


def review_status(record: dict) -> tuple:
    """(status, detail, model) of a stored review record."""
    verdict = record.get("verdict")
    counts = {}
    for f in record.get("findings") or []:
        if isinstance(f, dict):
            counts[f.get("severity")] = counts.get(f.get("severity"), 0) + 1
    parts = ["%d %s" % (counts[k], k.lower()) for k in ("BLOCKING", "HIGH", "MEDIUM") if counts.get(k)]
    if record.get("dropped_unverified"):
        parts.append("%d unverified" % record["dropped_unverified"])
    cov = record.get("coverage") or {}
    if cov and not cov.get("complete", True):
        parts.append("partial")
    m = record.get("model") or {}
    model = "/".join(p for p in (m.get("provider"), m.get("model")) if p) or None
    if verdict == "NOTHING TO REVIEW" or (record.get("error") or "").startswith("nothing to review"):
        return "skipped", "nothing to review", model
    if verdict == "COULD NOT RUN" or record.get("error"):
        return "error", "could not run: %s" % (record.get("error") or "?"), model
    if counts.get("BLOCKING") or counts.get("HIGH"):
        return "fail", ", ".join(parts), model
    if verdict not in ("PASS", "PASS WITH NOTES"):  # the deterministic gate blocks; the review waits on it
        return "pending", ", ".join(["the gate blocks"] + parts), model
    if parts:
        return "notes", ", ".join(parts), model
    return "pass", "no findings", model


def blocking_findings(record: dict) -> list:
    """The verified BLOCKING and HIGH findings of a review record: what the agent must fix."""
    return [f for f in record.get("findings") or [] if isinstance(f, dict) and f.get("severity") in ("BLOCKING", "HIGH")]


def record_review(ref: Ref, record: dict, then: str = "ready", bounce: bool = False) -> dict:
    """A review result. ``then`` is the stage a passing review leads to (ready, or awaiting_owner inside a merge).
    ``bounce`` counts a failing review as one bounce back to the agent (the finish loop), once per reviewed diff.
    Returns {"bounces", "max_bounces", "limit"} after the update."""
    status, detail, model = review_status(record)
    key = str(record.get("cache_key") or "")

    def apply(data, meta):
        at = now_iso()
        item = _ensure(data, ref, at)
        s = stage_of(item, "review")
        s.update(status=status, detail=_one_line(detail, 200), model=model, at=at)
        limit = False
        if item["stage"] not in DONE:
            gate_ok = stage_of(item, "gate").get("status") in ("pass", "pending")
            if status == "fail":
                counted = meta["counted"].setdefault(item["id"], [])
                if bounce and key not in counted:
                    counted.append(key)
                    item["bounces"] = int(item.get("bounces") or 0) + 1
                # "bounced" means the finish loop sent the change back to the agent; a review that fails anywhere
                # else (a merge, a review a person asked for) leaves it at the review, which reads "Review failed"
                item["stage"] = "bounced" if bounce and int(item.get("bounces") or 0) > 0 else "review"
                limit = bounce and item["bounces"] >= item["max_bounces"]
                _event(item, "Review sent it back (%s)%s" % (detail, ", bounce %d/%d" % (
                    item["bounces"], item["max_bounces"]) if bounce else ""), at)
                if limit:
                    _queue(meta, item, "needs_owner", "%s: the reviewer still finds problems after %d bounce(s); "
                           "it needs you" % (_label(item), item["bounces"]))
            elif status in ("pass", "notes") and gate_ok:
                # bounces stay: they count every time this change went back (the line shows "bounced 1/3")
                worktree_on_pr = ref.kind == "branch" and item["target"].get("kind") == "pr"
                # a review of the local working tree says nothing about the pull request's head on GitHub
                item["stage"] = "review" if worktree_on_pr and then == "ready" else then
                _event(item, "Review %s (%s)%s" % ("passed" if status == "pass" else "passed with notes", detail,
                                                   " on the local changes" if worktree_on_pr else ""), at)
                if then == "ready" and not worktree_on_pr:
                    _queue(meta, item, "ready", "%s is ready for you: gate %s, review %s" % (
                        _label(item), stage_of(item, "gate").get("status"), detail), notes=status == "notes")
            else:
                if item["stage"] in ("gate", "bounced", "ready"):
                    item["stage"] = "review" if gate_ok else "gate"
                _event(item, "Review: %s" % detail, at)
        return {"bounces": item["bounces"], "max_bounces": item["max_bounces"], "limit": limit}
    return _mutate(apply) or {"bounces": 0, "max_bounces": max_bounces(), "limit": False}


def record_waiting(ref: Ref, detail: str = "") -> None:
    """A person is being asked to approve the merge."""
    def apply(data, meta):
        at = now_iso()
        item = _ensure(data, ref, at)
        if item["stage"] in DONE:
            return
        item["stage"] = "awaiting_owner"
        stage_of(item, "owner").update(status="pending", detail=_one_line(detail, 200), at=at)
        _event(item, "Waiting for your merge decision%s" % (": " + detail if detail else ""), at)
    _mutate(apply)


def record_merge_refused(ref: Ref, detail: str, event: str = "") -> None:
    """Foreman or Hermes's approval refused the merge; the change stays where it is."""
    def apply(data, meta):
        at = now_iso()
        item = _ensure(data, ref, at)
        stage_of(item, "merge").update(status="refused", detail=_one_line(detail, 200), at=at)
        _event(item, event or "Merge refused: %s" % detail, at)
    _mutate(apply)


def record_merged(ref: Ref, method: str) -> None:
    def apply(data, meta):
        at = now_iso()
        item = _ensure(data, ref, at)
        stage_of(item, "owner").update(status="approved", at=at)
        stage_of(item, "merge").update(status="done", detail=method, at=at)
        item["stage"] = "merged"
        meta["model_calls"].pop(_budget_key(item), None)
        _event(item, "Merged (%s) after your approval" % method, at)
        _queue(meta, item, "merged", "%s merged (%s)" % (_label(item), method))
    _mutate(apply)


def record_rejected(ref: Ref, note: str = "", closed: bool = False) -> None:
    def apply(data, meta):
        at = now_iso()
        item = _ensure(data, ref, at)
        stage_of(item, "owner").update(status="rejected", detail=_one_line(note, 200), at=at)
        stage_of(item, "merge").update(status="skipped", detail="", at=at)
        item["stage"] = "rejected"
        meta["model_calls"].pop(_budget_key(item), None)
        _event(item, "Rejected%s%s" % (" and closed" if closed else "", ": " + note if note else ""), at)
        _queue(meta, item, "rejected", "%s rejected%s" % (_label(item), ": " + note if note else ""))
    _mutate(apply)


def record_event(ref: Ref, text: str) -> None:
    def apply(data, meta):
        at = now_iso()
        _event(_ensure(data, ref, at), text, at)
    _mutate(apply)


def record_needs_owner(ref: Ref, summary: str) -> None:
    def apply(data, meta):
        at = now_iso()
        item = _ensure(data, ref, at)
        if item["stage"] in DONE:
            return
        if int(item.get("bounces") or 0) > 0:
            item["stage"] = "bounced"
        elif item["stage"] in ("ready", "awaiting_owner"):  # never "bounced 0/3", and never "ready" for unreviewed work
            item["stage"] = "review"
        _event(item, summary, at)
        _queue(meta, item, "needs_owner", "%s: %s" % (_label(item), summary))
    _mutate(apply)


def event_in_repo(root: str, text: str) -> None:
    """An event on every active item of the repository at ``root`` (``/foreman allow``)."""
    def apply(data, meta):
        at = now_iso()
        key = _same_path(root or "")
        for item in data["items"]:
            if item.get("stage") not in DONE and _same_path(item.get("root") or "") == key:
                _event(item, text, at)
    if root:
        _mutate(apply)


# ─── The agent's review budget (auto_review: finish) ─────────────────────────
# Every model call the agent's foreman_review tool makes for a change counts, passing or failing. Only a person
# resets it: a merge, a rejection, or a review they type (/foreman review). Editing files, committing or a passing
# review does not, so the agent cannot buy more calls.

def review_budget() -> int:
    return max_bounces() + 1


def _budget_key(item: dict) -> str:
    """The budget belongs to the change's branch, so it survives the branch item becoming its pull request's."""
    branch = item["target"].get("branch") or ""
    return "%s#branch:%s" % (item.get("repo"), branch) if branch else item["id"]


def _ref_budget_key(ref: Ref) -> str:
    return "%s#branch:%s" % (ref.slug, ref.branch) if ref.branch else ref.id


def model_calls(ref: Ref) -> int:
    item = find(ref)
    try:
        with _lock:
            calls = _load_meta()["model_calls"]
    except Exception:
        return 0
    return int(calls.get(_budget_key(item) if item else _ref_budget_key(ref), 0))


def count_model_call(ref: Ref) -> int:
    def apply(data, meta):
        key = _budget_key(_ensure(data, ref, now_iso()))
        meta["model_calls"][key] = meta["model_calls"].get(key, 0) + 1
        return meta["model_calls"][key]
    return _mutate(apply) or 0


def reset_model_calls(ref: Ref) -> None:
    def apply(data, meta):
        item = _find(data, ref)
        meta["model_calls"].pop(_budget_key(item) if item else _ref_budget_key(ref), None)
    _mutate(apply)


def nudge_mark(item: str, key: str) -> bool:
    """Remember that ``item`` was nudged for ``key`` (a turn and a diff); False when it already was."""
    def apply(data, meta):
        if meta["nudged"].get(item) == key:
            return False
        meta["nudged"][item] = key
        return True
    return bool(_mutate(apply))


def nudge_clear(prefix: str) -> None:
    """Forget the nudge marks whose name starts with ``prefix`` (a new turn of a session)."""
    def apply(data, meta):
        meta["nudged"] = {k: v for k, v in meta["nudged"].items() if not k.startswith(prefix)}
    _mutate(apply)


def get(item: str) -> Optional[dict]:
    return next((i for i in snapshot()["items"] if i["id"] == item), None)


def find(ref: Ref) -> Optional[dict]:
    """The item ``ref`` would update (a branch's open pull request included), without creating it."""
    try:
        data = snapshot()
        items = [dict(i, target=dict(i["target"])) for i in data["items"]]
        return _find({"items": items}, ref)
    except Exception:
        return None


# ─── Building a Ref ──────────────────────────────────────────────────────────

def local_ref(root: str, deadline: Optional[float] = None) -> Ref:
    """The current branch of the repository at ``root``."""
    from . import review
    from .detector import Repo
    repo = Repo(root, budget=None if deadline else 10, deadline=deadline)
    head = repo.try_git("rev-parse", "--verify", "-q", "HEAD^{commit}")
    return Ref(review.slug_of(repo), root, "branch", branch=repo.branch(), head=head)


def pr_ref(root: str, v: dict) -> Ref:
    """A pull request from a ``board.pr_verdict`` result."""
    from . import review
    from .detector import Repo
    slug = v.get("name") or review.slug_of(Repo(root, budget=5))
    return Ref(slug, root, "pr", int(v["number"]), branch=v.get("head") or "", title=v.get("title") or "",
               url=v.get("url") or None, head=v.get("head_oid") or None)


def gate_from_verdict(v: dict) -> tuple:
    """(status, detail) of the gate stage from a verdict dict (status, board or pull request)."""
    from .verdicts import BLOCKED, CLEAN, INCOMPLETE, NEEDS_OK
    verdict = v.get("verdict")
    blockers, marked, errors = v.get("blockers") or [], v.get("marked") or [], v.get("errors") or []
    notes = v.get("sarif_notes")
    if notes is None:
        notes = [n for n in v.get("notes") or [] if isinstance(n, dict)]
    tail = "; %d SARIF note(s)" % len(notes) if notes else ""
    if v.get("error"):
        return "pending", "INCOMPLETE: %s" % v["error"]
    if verdict == BLOCKED:
        rules = ", ".join(dict.fromkeys(d.get("rule", "?") for d in blockers))
        return "fail", "%d blocker(s): %s%s" % (len(blockers), rules, tail)
    if verdict == INCOMPLETE:
        return "pending", "INCOMPLETE: %s%s" % (errors[0] if errors else "could not inspect", tail)
    if verdict == NEEDS_OK:
        return "pending", "NEEDS YOUR OK: %d marked finding(s)%s" % (len(marked), tail)
    if verdict == CLEAN:
        return "pass", "CLEAN%s" % tail
    return "pending", str(verdict or "?")


# ─── Text views ──────────────────────────────────────────────────────────────

_WORDS = {"gate": {"pass": "ok", "fail": "FAIL", "pending": "-", "skipped": "skip"},
          "review": {"pass": "ok", "notes": "notes", "fail": "FAIL", "pending": "-", "skipped": "skip",
                     "error": "could not run"},
          "owner": {"pending": "-", "approved": "ok", "rejected": "REJECTED", "skipped": "skip"},
          "merge": {"pending": "-", "done": "done", "refused": "refused", "skipped": "skip"}}


def _short_detail(detail: str) -> str:
    """``1 blocker(s): test-skipped`` -> ``1 blocker``; ``2 blocking, 1 high, 1 medium`` -> ``2 blocking, 1 high``."""
    head = (detail or "").split(":")[0]
    m = re.match(r"(\d+) blocker\(s\)$", head)
    if m:
        return "%s blocker%s" % (m.group(1), "" if m.group(1) == "1" else "s")
    parts = [p.strip() for p in head.split(",") if re.match(r"\s*\d+ (blocking|high)$", p)]
    return ", ".join(parts)


def shown_stage(item: dict) -> str:
    """The stage as the views name it. A state file written before a merge-time review stopped counting as a bounce
    can hold ``bounced`` with no bounce; that is a failed review, as the Desktop panel shows it."""
    stage = str(item.get("stage") or "?")
    return "review" if stage == "bounced" and not int(item.get("bounces") or 0) else stage


def line(item: dict) -> str:
    """One line: ``gate ok > review FAIL (2 blocking) > bounced 1/3 > owner - > merge -``; the bounce part only when
    the change went back to the agent at least once."""
    parts = []
    for name in ("gate", "review"):
        s = stage_of(item, name)
        word = _WORDS[name].get(s.get("status"), s.get("status") or "?")
        if name == "gate" and s.get("status") == "pending" and str(s.get("detail") or "").startswith(
                ("INCOMPLETE", "NEEDS YOUR OK")):
            word = s["detail"].split(":")[0]
        extra = _short_detail(s.get("detail") or "") if s.get("status") == "fail" else ""
        parts.append("%s %s%s" % (name, word, " (%s)" % extra if extra else ""))
    if int(item.get("bounces") or 0) > 0:
        parts.append("bounced %d/%d" % (int(item.get("bounces") or 0), int(item.get("max_bounces") or 0)))
    owner = stage_of(item, "owner")
    word = "waiting" if item.get("stage") == "awaiting_owner" and owner.get("status") == "pending" else \
        _WORDS["owner"].get(owner.get("status"), "?")
    parts.append("owner %s" % word)
    parts.append("merge %s" % _WORDS["merge"].get(stage_of(item, "merge").get("status"), "?"))
    return " > ".join(parts)


def _same_path(path: str) -> str:
    try:
        return os.path.normcase(os.path.realpath(path))
    except (OSError, ValueError):
        return os.path.normcase(os.path.normpath(path))


def items_for(slug: str = "", root: str = "") -> list:
    """Items of one repository (by slug or by local root), most recently updated first."""
    key = _same_path(root) if root else ""
    out = [i for i in snapshot()["items"]
           if (slug and i.get("repo") == slug) or (key and _same_path(i.get("root") or "") == key)]
    return sorted(out, key=lambda i: str(i.get("updated") or ""), reverse=True)


def board_lines(slug: str, root: str, width: int = 78, limit: int = 6) -> list:
    """The board's pipeline block: one title line and one stage line per change."""
    items = items_for(slug, root)
    if not items:
        return []
    out = ["Pipeline (%d change%s):" % (len(items), "" if len(items) == 1 else "s")]
    for item in items[:limit]:
        t = item["target"]
        name = "#%s" % t.get("number") if t.get("kind") == "pr" else str(t.get("branch") or "?")
        head = "  %s  %s" % (name, shown_stage(item))
        out.append(head if len(head) <= width else head[:width - 3] + "...")
        text = "    " + line(item)
        out.append(text if len(text) <= width else text[:width - 3] + "...")
    if len(items) > limit:
        out.append("  ... and %d more (`/foreman pipeline`)" % (len(items) - limit))
    return out


def _when(at: str) -> str:
    m = re.match(r"\d{4}-(\d{2}-\d{2})T(\d{2}:\d{2})", at or "")
    return "%s %s" % (m.group(1), m.group(2)) if m else (at or "?")[:11]


def format_item(item: dict, width: int = 78, events: int = 8) -> str:
    import textwrap
    t = item["target"]
    name = "PR #%s" % t.get("number") if t.get("kind") == "pr" else "branch %s" % t.get("branch")
    lines = ["Pipeline: %s %s" % (item.get("repo"), name)]
    if t.get("kind") == "pr" and t.get("branch"):
        lines[0] += " (%s)" % t["branch"]
    if t.get("title"):
        lines.append("  " + _one_line(t["title"], width - 2))
    lines.append("  stage: %s, head %s, updated %s UTC" % (shown_stage(item), (item.get("head") or "-")[:7],
                                                           _when(item.get("updated"))))
    lines.append("  " + line(item))
    for name_ in ("gate", "review", "owner", "merge"):
        s = stage_of(item, name_)
        detail = s.get("detail") or ""
        if name_ == "review" and s.get("model"):
            detail = (detail + " " if detail else "") + "[%s]" % s["model"]
        lines.append(textwrap.fill("%-7s %-8s %s" % (name_, s.get("status"), detail), width=width,
                                   initial_indent="  ", subsequent_indent=" " * 19, break_long_words=True))
    lines.append("  bounces %d of %d" % (int(item.get("bounces") or 0), int(item.get("max_bounces") or 0)))
    evs = item.get("events") or []
    if evs:
        lines.append("Last events:")
        for e in evs[-events:]:
            lines.append(textwrap.fill(str(e.get("text") or ""), width=width, initial_indent="  %s  " % _when(
                e.get("at")), subsequent_indent=" " * 15, break_long_words=True))
    if t.get("kind") == "pr" and item.get("stage") not in DONE:
        lines.append("Next: `/foreman merge %s` or `/foreman reject %s [note]`." % (t.get("number"), t.get("number")))
    return "\n".join(lines)


def diff_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
