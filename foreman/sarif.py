"""SARIF 2.1.0 as a source of findings. Standard library only; Foreman never runs the scanner, it only reads a file.

A result becomes a Foreman finding with the rule id ``sarif:<tool>/<ruleId>``. It blocks when its severity reaches the
threshold (default 7.0, i.e. an ``error`` or a CVSS-like ``security-severity`` of 7.0 or more); below it, it is listed
as a note and does not block.

Severity of one result, first match wins:

1. ``properties["security-severity"]`` on the result (a number, or a numeric string);
2. ``properties["severity"]`` on the result when it is a named level (critical, high, medium, low, informational):
   hermes-security writes it, and its rule-level score is the maximum over all the rule's findings, so the result's
   own level is the precise one;
3. ``properties["security-severity"]`` on the rule;
4. the result's ``level``; then the rule's ``defaultConfiguration.level``; then SARIF's default, ``warning``.

Suppressed results (an accepted or status-less suppression) and results whose ``baselineState`` is ``absent`` never
block and are not listed.

``collect`` never raises: anything it cannot read becomes one non-blocking "could not read SARIF" note. ``parse_file``
raises ``SarifError`` for the caller that asked for the file explicitly (the CLI), so CI does not pass silently.
"""
from __future__ import annotations

import json
import os
import posixpath
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import unquote

from .detector import Finding, fingerprint

MAX_BYTES = 20 * 1024 * 1024
MAX_NOTES = 25  # below-threshold results listed one by one; the rest are counted
DEFAULT_THRESHOLD = 7.0
NAMED_THRESHOLDS = {"error": 7.0, "warning": 4.0}
LEVEL_SCORE = {"error": 8.0, "warning": 5.0, "note": 2.0, "none": 0.0}
NAMED_SCORE = {"critical": 9.5, "high": 8.0, "medium": 5.0, "low": 2.0, "informational": 0.0}
STALE = "SARIF report is older than the changes it gates"
FIX = "Fix what the scanner reports; to dismiss it, suppress it in the scanner and export the report again."


class SarifError(Exception):
    pass


@dataclass
class SarifResult:
    blockers: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def parse_threshold(value) -> float:
    """``error`` (7.0), ``warning`` (4.0) or a number from 0 to 10. Raises ValueError for anything else."""
    if isinstance(value, bool):
        raise ValueError("invalid SARIF threshold: %r" % (value,))
    if isinstance(value, str) and value.strip().lower() in NAMED_THRESHOLDS:
        return NAMED_THRESHOLDS[value.strip().lower()]
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("invalid SARIF threshold %r: use error, warning or a number from 0 to 10" % (value,))
    if not 0 <= number <= 10:  # also false for NaN
        raise ValueError("invalid SARIF threshold %r: use error, warning or a number from 0 to 10" % (value,))
    return number


def _dict(x) -> dict:
    return x if isinstance(x, dict) else {}


def _list(x) -> list:
    return x if isinstance(x, list) else []


def _score(value) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if 0 <= number <= 10 else None


def _level(value) -> Optional[str]:
    return value.strip().lower() if isinstance(value, str) and value.strip().lower() in LEVEL_SCORE else None


def severity_of(result: dict, rule: dict) -> tuple:
    """(score, label) of one result; the label says where the score came from."""
    props, rule_props = _dict(result.get("properties")), _dict(rule.get("properties"))
    score = _score(props.get("security-severity"))
    if score is not None:
        return score, "severity %.1f" % score
    named = props.get("severity")
    if isinstance(named, str) and named.strip().lower() in NAMED_SCORE:
        named = named.strip().lower()
        return NAMED_SCORE[named], "severity %s" % named
    score = _score(rule_props.get("security-severity"))
    if score is not None:
        return score, "severity %.1f" % score
    level = (_level(result.get("level")) or _level(_dict(rule.get("defaultConfiguration")).get("level")) or "warning")
    return LEVEL_SCORE[level], "level " + level


# ─── Paths ───────────────────────────────────────────────────────────────────

_DRIVE = re.compile(r"^[A-Za-z]:/")


def _as_path(uri: str) -> str:
    """A URI or path as a forward-slash path: ``file://`` removed, percent-escapes decoded, no leading slash before a
    Windows drive letter."""
    u = (uri or "").strip()
    if re.match(r"(?i)file:", u):
        rest = u[5:]
        if rest.startswith("//"):
            rest = rest[2:]
            rest = rest[rest.find("/"):] if "/" in rest else "/" + rest  # drop the host, if any
        u = rest
    u = unquote(u).replace("\\", "/")
    if re.match(r"^/[A-Za-z]:(/|$)", u):
        u = u[1:]
    return u


def _is_absolute(path: str) -> bool:
    return path.startswith("/") or bool(_DRIVE.match(path))


def _relative_to(path: str, root: str) -> Optional[str]:
    """``path`` relative to ``root`` (both forward-slash, absolute), or None when it is not inside. Drive letters
    compare without case, as Windows does."""
    root = root.rstrip("/")
    fold = bool(_DRIVE.match(root + "/"))
    a, b = (path.lower(), root.lower()) if fold else (path, root)
    if a == b:
        return ""
    return path[len(root) + 1:] if a.startswith(b + "/") else None


def repo_path(uri: str, base_id: Optional[str], run: dict, root: str) -> str:
    """The path of a result's artifact inside the repository, with forward slashes. Absolute paths and ``file://``
    URIs inside the repository are made relative to it; a relative one is resolved against its ``uriBaseId`` (when the
    run defines it and it points inside the repository) and otherwise taken as relative to the repository."""
    root = _as_path(root).rstrip("/")
    path = _as_path(uri)
    if not path:
        return ""
    if not _is_absolute(path):
        base = ""
        bases = _dict(run.get("originalUriBaseIds"))
        if base_id and isinstance(base_id, str):
            entry = _dict(bases.get(base_id)).get("uri")
            if isinstance(entry, str) and entry:
                base_path = _as_path(entry)
                base = _relative_to(base_path.rstrip("/"), root) if _is_absolute(base_path) else base_path
                base = (base or "").strip("/")
        path = posixpath.join(base, path) if base else path
    elif root:
        rel = _relative_to(path, root)
        if rel is not None:
            path = rel
    out = posixpath.normpath(path)
    return "" if out == "." else out


# ─── Reading ─────────────────────────────────────────────────────────────────

def _one_line(text, limit: int = 240) -> str:
    out = " ".join(str(text).split())
    return out if len(out) <= limit else out[:limit - 3] + "..."


def _message(result: dict, rule: dict, rule_id: str) -> str:
    msg = _dict(result.get("message"))
    for text in (msg.get("text"), msg.get("markdown"), _dict(rule.get("shortDescription")).get("text")):
        if isinstance(text, str) and text.strip():
            return _one_line(text)
    return rule_id


def _suppressed(result: dict) -> bool:
    return any(isinstance(s, dict) and s.get("status") in (None, "accepted") for s in _list(result.get("suppressions")))


def _make(rule: str, file: str, line: int, message: str, severity: str, key: str = "") -> Finding:
    return Finding(rule, file, line, message, FIX, severity=severity,
                   fingerprint=fingerprint(rule, file, message, "", "%s:%d" % (key, line)))


def note(rule: str, file: str, message: str) -> Finding:
    """A non-blocking finding about the SARIF source itself (unreadable, stale)."""
    return _make(rule, file, 0, message, "note")


def _tool_name(run: dict) -> str:
    name = _dict(_dict(run.get("tool")).get("driver")).get("name")
    return _one_line(name, 60).replace(" ", "-") if isinstance(name, str) and name.strip() else "unknown"


def _rule_for(result: dict, rules: list) -> dict:
    index = result.get("ruleIndex")
    if not isinstance(index, int) or isinstance(index, bool):
        index = _dict(result.get("rule")).get("index")
    if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(rules):
        return _dict(rules[index])
    wanted = result.get("ruleId") or _dict(result.get("rule")).get("id")
    for r in rules:
        if isinstance(r, dict) and wanted and r.get("id") == wanted:
            return r
    return {}


def _read_json(path: str) -> dict:
    try:
        size = os.path.getsize(path)
    except OSError as e:
        raise SarifError("cannot read the file (%s)" % (e.strerror or e.__class__.__name__))
    if size > MAX_BYTES:
        raise SarifError("the file is %d MB, over the %d MB limit" % (size // (1024 * 1024), MAX_BYTES // (1024 * 1024)))
    try:
        with open(path, "rb") as fh:
            data = fh.read(MAX_BYTES + 1)
        doc = json.loads(data.decode("utf-8-sig"))
    except OSError as e:
        raise SarifError("cannot read the file (%s)" % (e.strerror or e.__class__.__name__))
    except (ValueError, RecursionError) as e:  # UnicodeDecodeError and JSONDecodeError are ValueErrors
        raise SarifError("not valid JSON (%s)" % _one_line(e, 80))
    if not isinstance(doc, dict):
        raise SarifError("not a SARIF document (the top level is not an object)")
    if doc.get("version") != "2.1.0":
        raise SarifError("unsupported SARIF version %s (need 2.1.0)" % _one_line(repr(doc.get("version")), 30))
    if not isinstance(doc.get("runs"), list):
        raise SarifError("not a SARIF document (no runs)")
    return doc


def parse_file(path: str, root: str = "", threshold: float = DEFAULT_THRESHOLD, label: Optional[str] = None) -> SarifResult:
    """Findings of one SARIF file. Raises SarifError when the file cannot be read as SARIF 2.1.0."""
    name = label or path
    doc = _read_json(path)
    out, below = SarifResult(), []
    for run in doc["runs"]:
        run = _dict(run)
        tool = _tool_name(run)
        rules = _list(_dict(_dict(run.get("tool")).get("driver")).get("rules"))
        for raw in _list(run.get("results")):
            result = _dict(raw)
            if not result or _suppressed(result) or result.get("baselineState") == "absent":
                continue
            rule = _rule_for(result, rules)
            rule_id = next((x for x in (result.get("ruleId"), _dict(result.get("rule")).get("id"), rule.get("id"))
                            if isinstance(x, str) and x.strip()), "unknown").strip()
            score, why = severity_of(result, rule)
            loc = _dict(_dict(next(iter(_list(result.get("locations"))), None)).get("physicalLocation"))
            art = _dict(loc.get("artifactLocation"))
            uri = art.get("uri")
            file = repo_path(uri, art.get("uriBaseId"), run, root) if isinstance(uri, str) else ""
            start = _dict(loc.get("region")).get("startLine")
            line = start if isinstance(start, int) and not isinstance(start, bool) and start > 0 else 0
            blocks = score >= threshold
            message = "%s (%s)" % (_message(result, rule, rule_id), why)
            f = _make("sarif:%s/%s" % (tool, rule_id), file, line, message, "blocker" if blocks else "note", name)
            if blocks:
                out.blockers.append(f)
            else:
                below.append((score, f))
    below.sort(key=lambda pair: -pair[0])
    out.notes += [f for _, f in below[:MAX_NOTES]]
    if len(below) > MAX_NOTES:
        out.notes.append(_make("sarif:summary", name, 0,
                               "and %d more result(s) below the threshold" % (len(below) - MAX_NOTES), "note", name))
    return out


def collect(paths, root: str = "", threshold: float = DEFAULT_THRESHOLD, newest: Optional[float] = None) -> SarifResult:
    """Findings of several SARIF files, never raising: an unreadable file is one non-blocking note. ``newest`` is the
    timestamp of the newest change the reports gate; a report last written before it gets a staleness note."""
    total = SarifResult()
    for path in paths:
        label = _one_line(path, 120)
        try:
            part = parse_file(path, root, threshold, label)
            total.blockers += part.blockers
            total.notes += part.notes
            if newest is not None and os.path.getmtime(path) < newest:
                total.notes.append(note("sarif:stale", label, STALE))
        except SarifError as e:
            total.notes.append(note("sarif:unreadable", label, "could not read SARIF: %s" % e))
        except Exception as e:  # a malformed file must never take the gate down
            total.notes.append(note("sarif:unreadable", label,
                                     "could not read SARIF: unexpected shape (%s)" % e.__class__.__name__))
    return total
