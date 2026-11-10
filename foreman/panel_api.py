"""The Desktop panel's reader: Foreman's pipeline snapshot (``pipeline.json``), read-only.

The agent half keeps ``pipeline.json`` in Foreman's data directory (``<hermes home>/plugin-data/foreman/``): one item
per change (a pull request or a branch) and where it stands on the line gate -> review -> owner -> merge. This module
only reads it. ``dashboard/plugin_api.py`` serves :func:`read_snapshot` at ``GET /api/plugins/foreman/pipeline``, the
route the Desktop half (``desktop/plugin.js``) reaches through ``ctx.rest``.

Everything in the file is treated as untrusted text: titles, branch names, paths and event lines come from pull
requests and from the agent. The reader never interprets them; it keeps the documented fields, drops what does not
fit the shape, caps every string and strips control and bidirectional-override characters. A missing, unreadable,
oversized or malformed file reads as "no items", with ``problem`` saying why, and never raises.

Standard library only, and no imports from the rest of the package: ``dashboard/plugin_api.py`` loads this file on
its own, by path.
"""
from __future__ import annotations

import json
import os
import re
import stat
from typing import Any, Optional

PIPELINE_FILE = "pipeline.json"
SNAPSHOT_VERSION = 1
MAX_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 100
MAX_EVENTS = 20
MAX_TEXT = 500
MAX_TITLE = 300
MAX_SHORT = 200

STAGES = ("gate", "review", "bounced", "ready", "awaiting_owner", "merged", "rejected")
TARGET_KINDS = ("pr", "branch")
STATION_NAMES = ("gate", "review", "owner", "merge")
STATION_STATUS = {
    "gate": ("pass", "fail", "pending", "skipped"),
    "review": ("pass", "notes", "fail", "pending", "skipped", "error"),
    "owner": ("pending", "approved", "rejected", "skipped"),
    "merge": ("pending", "done", "refused", "skipped"),
}

# Tests point this at a file of their own.
PATH_OVERRIDE: Optional[str] = None

# C0/C1 controls, line/paragraph separators, lone surrogates (JSON allows them; the route could not encode them),
# and the bidirectional overrides and isolates that can make text read differently from what it is.
_UNSAFE_RANGES = ((0x00, 0x08), (0x0B, 0x1F), (0x7F, 0x9F), (0x200B, 0x200F), (0x202A, 0x202E), (0x2066, 0x2069),
                  (0x2028, 0x2029), (0xD800, 0xDFFF), (0xFEFF, 0xFEFF))
_UNSAFE_CHARS = re.compile("[%s]" % "".join("%s-%s" % (re.escape(chr(a)), re.escape(chr(b))) for a, b in _UNSAFE_RANGES))
ELLIPSIS = chr(0x2026)
_SPACES = re.compile(r"[\t\n\r]+")
_SHA = re.compile(r"^[0-9a-fA-F]{7,64}$")


def data_dir() -> str:
    """Foreman's data directory for the active profile, the same one the agent half writes to."""
    try:
        from plugins.plugin_storage import plugin_data_dir
        return str(plugin_data_dir("foreman"))
    except Exception:
        return os.path.join(os.path.expanduser("~"), ".foreman")


def pipeline_path() -> str:
    return PATH_OVERRIDE or os.path.join(data_dir(), PIPELINE_FILE)


def empty(problem: Optional[str] = None) -> dict:
    return {"version": SNAPSHOT_VERSION, "items": [], "problem": problem}


def read_snapshot(path: Optional[str] = None) -> dict:
    """``{"version": 1, "items": [...], "problem": None | "missing" | "unreadable" | "too_large" | "unsupported"}``.

    Never raises. Items keep the documented shape (see ``normalize_item``); anything else is dropped."""
    path = path or pipeline_path()
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return empty("missing")
    except OSError:
        return empty("unreadable")
    if not stat.S_ISREG(st.st_mode):  # a FIFO or a device would block the reading thread
        return empty("unreadable")
    if st.st_size > MAX_BYTES:
        return empty("too_large")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read(MAX_BYTES + 1)
    except (OSError, UnicodeDecodeError):
        return empty("unreadable")
    if len(raw) > MAX_BYTES:
        return empty("too_large")
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        return empty("unreadable")
    return normalize(data)


def normalize(data: Any) -> dict:
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return empty("unreadable")
    if data.get("version") != SNAPSHOT_VERSION:
        return empty("unsupported")
    items, seen = [], set()
    for raw in data["items"]:
        item = normalize_item(raw)
        if item is not None and item["id"] not in seen:
            seen.add(item["id"])
            items.append(item)
        if len(items) >= MAX_ITEMS:
            break
    return {"version": SNAPSHOT_VERSION, "items": items, "problem": None}


def normalize_item(raw: Any) -> Optional[dict]:
    """One change, in the documented shape, or None when it has no usable id or stage."""
    if not isinstance(raw, dict):
        return None
    item_id = text(raw.get("id"), MAX_SHORT)
    stage = raw.get("stage")
    if not item_id or stage not in STAGES:
        return None
    target = raw.get("target") if isinstance(raw.get("target"), dict) else {}
    kind = target.get("kind")
    return {
        "id": item_id,
        "repo": text(raw.get("repo"), MAX_SHORT),
        "root": text(raw.get("root"), MAX_TEXT),
        "target": {
            "kind": kind if kind in TARGET_KINDS else None,
            "number": count(target.get("number"), 1, 10 ** 9),
            "branch": text(target.get("branch"), MAX_SHORT),
            "title": text(target.get("title"), MAX_TITLE),
            "url": https_url(target.get("url")),
        },
        "head": raw["head"] if isinstance(raw.get("head"), str) and _SHA.match(raw["head"]) else None,
        "stage": stage,
        "stages": stations(raw.get("stages")),
        "bounces": count(raw.get("bounces"), 0, 999) or 0,
        "max_bounces": count(raw.get("max_bounces"), 1, 999),
        "updated": text(raw.get("updated"), 40),
        "events": events(raw.get("events")),
    }


def stations(raw: Any) -> list:
    """The four stations in line order; a missing one is pending, an unknown status is None (shown as unknown)."""
    given = {}
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict) and entry.get("name") in STATION_NAMES and entry["name"] not in given:
                given[entry["name"]] = entry
    out = []
    for name in STATION_NAMES:
        entry = given.get(name)
        if entry is None:
            out.append({"name": name, "status": "pending", "detail": "", "at": None})
            continue
        status = entry.get("status")
        station = {
            "name": name,
            "status": status if status in STATION_STATUS[name] else None,
            "detail": text(entry.get("detail"), MAX_TEXT),
            "at": text(entry.get("at"), 40),
        }
        if name == "review":
            station["model"] = text(entry.get("model"), MAX_SHORT)
        out.append(station)
    return out


def events(raw: Any) -> list:
    if not isinstance(raw, list):
        return []
    out = []
    for entry in raw[-MAX_EVENTS:]:
        if isinstance(entry, dict):
            line = text(entry.get("text"), MAX_TEXT)
            if line:
                out.append({"at": text(entry.get("at"), 40), "text": line})
    return out


def text(value: Any, limit: int) -> Optional[str]:
    """A string as plain, single-line text: unsafe characters removed, capped at ``limit``. None for a non-string."""
    if not isinstance(value, str):
        return None
    value = _SPACES.sub(" ", _UNSAFE_CHARS.sub("", value)).strip()
    if len(value) > limit:
        value = value[: limit - 1].rstrip() + ELLIPSIS
    return value


def count(value: Any, low: int, high: int) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        return None
    return value


def https_url(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.startswith("https://") and len(value) <= MAX_TEXT \
            and not _UNSAFE_CHARS.search(value) and not any(c.isspace() for c in value):
        return value
    return None


def notify_changed() -> bool:
    """Tell an open Desktop panel that ``pipeline.json`` changed, so it refreshes now instead of at its next poll.

    For the code that writes the file; safe anywhere. True when Hermes's event bridge took the event (it delivers
    only to Desktop windows connected to this process: from the CLI or cron nobody hears it); False without Hermes
    (the tests, CI). The panel also polls, so a lost event costs at most a few seconds."""
    try:
        from hermes_cli.plugin_events import broadcast_plugin_event
        broadcast_plugin_event("foreman", "pipeline.updated", {})
        return True
    except Exception:
        return False
