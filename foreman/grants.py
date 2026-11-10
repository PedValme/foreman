"""One-time exceptions a person grants with ``/foreman allow <id>``.

A finding marked ``foreman:allow`` by the agent stays blocked and is recorded here as *pending*. Only a person can
turn it into a *grant*: slash commands are typed by the user, never called by the model. A grant is bound to the
finding's fingerprint (rule, file and the marked line's content), so an unrelated change cannot reuse it, and it
expires after 24 hours.

The store is a JSON file in the plugin's data directory (``plugin_data_dir``), outside the repository.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from typing import Iterable, Optional

GRANTS_FILE = "foreman-grants.json"
GRANT_TTL_SECONDS = 24 * 3600
PENDING_TTL_SECONDS = 7 * 24 * 3600
MAX_PENDING = 200

# Tests point this at a temporary directory.
STORE_DIR_OVERRIDE: Optional[str] = None

_lock = threading.Lock()


def store_dir() -> str:
    if STORE_DIR_OVERRIDE:
        os.makedirs(STORE_DIR_OVERRIDE, exist_ok=True)
        return STORE_DIR_OVERRIDE
    try:
        from plugins.plugin_storage import plugin_data_dir
        return str(plugin_data_dir("foreman"))
    except Exception:
        path = os.path.join(os.path.expanduser("~"), ".foreman")
        os.makedirs(path, exist_ok=True)
        return path


def store_path() -> str:
    return os.path.join(store_dir(), GRANTS_FILE)


def _load() -> dict:
    try:
        with open(store_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            data.setdefault("pending", {})
            data.setdefault("granted", {})
            return data
    except (OSError, ValueError):
        pass
    return {"pending": {}, "granted": {}}


def _save(data: dict) -> None:
    path = store_path()
    fd, tmp = tempfile.mkstemp(prefix=".grants-", dir=os.path.dirname(path))
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


def _prune(data: dict, now: float) -> None:
    data["granted"] = {k: v for k, v in data["granted"].items() if v.get("expires", 0) > now}
    pending = {k: v for k, v in data["pending"].items() if v.get("created", 0) + PENDING_TTL_SECONDS > now}
    if len(pending) > MAX_PENDING:
        newest = sorted(pending.items(), key=lambda kv: kv[1].get("created", 0))[-MAX_PENDING:]
        pending = dict(newest)
    data["pending"] = pending


def is_granted(fingerprint: str) -> bool:
    if not fingerprint:
        return False
    with _lock:
        grant = _load()["granted"].get(fingerprint)
    return bool(grant and grant.get("expires", 0) > time.time())


def record_pending(findings: Iterable, repo: str = "") -> None:
    """Remember marked findings so the user can list and allow them."""
    findings = [f for f in findings if getattr(f, "fingerprint", "")]
    if not findings:
        return
    with _lock:
        data, now = _load(), time.time()
        _prune(data, now)
        for f in findings:
            if f.fingerprint in data["granted"]:
                continue
            data["pending"][f.fingerprint] = {"id": f.short_id, "rule": f.rule, "location": f.location,
                                              "message": f.message, "repo": repo, "created": now}
        _save(data)


def pending() -> list:
    with _lock:
        data = _load()
        _prune(data, time.time())
    return sorted(data["pending"].values(), key=lambda v: v.get("created", 0))


def grant(short_id: str) -> tuple:
    """(True, entry) when ``short_id`` names one pending finding, else (False, reason)."""
    short_id = (short_id or "").strip().lower()
    if len(short_id) < 4:
        return False, "Give the id Foreman printed (at least 4 characters)."
    with _lock:
        data, now = _load(), time.time()
        _prune(data, now)
        matches = [fp for fp in data["pending"] if fp.startswith(short_id)]
        if not matches:
            return False, "No pending finding with id `%s`." % short_id
        if len(matches) > 1:
            return False, "Id `%s` is ambiguous; give more characters." % short_id
        fp = matches[0]
        entry = data["pending"].pop(fp)
        entry.update(granted_at=now, expires=now + GRANT_TTL_SECONDS)
        data["granted"][fp] = entry
        _save(data)
    return True, entry
