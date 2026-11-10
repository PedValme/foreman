"""Notifications: tell the owner on their phone when a pull request waits for them.

Off by default: nothing is sent anywhere until the user types ``/foreman notify on``. When it is on, ``send(event)``
pushes one plain-text message to the messaging target the user chose (``telegram`` is the Telegram home channel set
with ``/sethome``; ``telegram:<chat>``, ``discord:#ops``, ``slack:C0123`` name one chat). It goes out through Hermes's
own documented ``hermes send`` command, run by Hermes's terminal tool (``ctx.dispatch_tool("terminal")``): the
user's own Hermes and bot deliver it, Foreman never sees a token.

What the message cannot do: carry buttons whose press comes back to Foreman. Hermes 0.23 has no public way for a
plugin to post a message with buttons outside a slash command (``send_message`` is deliberately not a tool, and
``ctx.post_message`` only reaches the conversation that called the plugin). So the message carries the exact
command to send back; ``/foreman merge <n> --repo <owner/name>`` then re-checks the pull request and asks with
Hermes's own buttons (``ctx.ask_choice``: Merge / Cancel on Telegram, Discord and Slack). A notification is never a
confirmation: the merge is decided in the chat, by the person, after a fresh verdict.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
from typing import Optional

from . import board, grants

logger = logging.getLogger(__name__)

SEND_TIMEOUT = 60           # the terminal tool's timeout for `hermes send`
LOG_FILE = "foreman-notify.json"
MAX_LOG = 30
KINDS = ("ready", "needs_owner", "merged", "rejected")
CODE_PLATFORMS = {"telegram", "discord", "slack"}   # render `code`; Telegram copies it with one tap
LOCAL_SURFACES = {"", "cli", "tui", "desktop", "local", "acp", "api_server", "webhook"}

_lock = threading.Lock()

# ─── Settings (plugins.entries.foreman.settings.*) ───────────────────────────


def _ctx():
    return board._CTX


def _setting(key: str):
    get = getattr(_ctx(), "get_config", None)
    if not callable(get):
        return None
    try:
        return get(key, None)
    except Exception:
        logger.warning("foreman: cannot read setting %s", key, exc_info=True)
        return None


def enabled() -> bool:
    value = _setting("notify")
    if value is True:          # YAML reads a bare `on` as true
        return True
    return isinstance(value, str) and value.strip().lower() in ("on", "true", "yes")


_TARGET = re.compile(r"^[a-z][a-z0-9_]{1,31}(?::[^\s\"'`$;&|<>\\%!]{1,200})?$")


def destination() -> str:
    value = _setting("notify_to")
    return value.strip() if isinstance(value, str) else ""


def valid_target(target: str) -> bool:
    return bool(_TARGET.match(target or "")) and target.split(":", 1)[0] not in LOCAL_SURFACES


def _set(key: str, value) -> Optional[str]:
    """None when saved, else why not."""
    put = getattr(_ctx(), "set_config", None)
    if not callable(put):
        return "this Hermes cannot save plugin settings from a command"
    try:
        put(key, value)
        return None
    except Exception as e:
        logger.warning("foreman: cannot save setting %s", key, exc_info=True)
        return "%s: %s" % (type(e).__name__, e)


# ─── The message ─────────────────────────────────────────────────────────────

_INVISIBLE = re.compile("[\u0000-\u0008\u000b-\u001f\u007f\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]")
_MARKUP = re.compile(r"[*`~|<>\[\]\\{}]")
ZWSP = "\u200b"


def clean(text, width: int) -> str:
    """Third-party text (a PR title, a branch, a model's words) made inert on every platform: one line, no markup
    (Markdown, HTML), no Hermes media directive, no @mention, no link a chat would make clickable."""
    t = _INVISIBLE.sub("", " ".join(str(text or "").split()))
    t = re.sub(r"(?i)media\s*:", "media ", t)              # `MEDIA:<path>` would make Hermes attach a local file
    t = _MARKUP.sub(" ", t)
    t = re.sub(r"(?<![A-Za-z0-9])_|_(?![A-Za-z0-9])", " ", t)  # _italic_, but keep snake_case words
    t = " ".join(t.split())
    if len(t) > width:
        t = t[:max(1, width - 3)].rstrip() + "..."
    t = t.replace("@", "@" + ZWSP)                          # @name, @everyone, @here notify nobody
    t = t.replace("://", ":" + ZWSP + "//")                # no scheme link
    return re.sub(r"\.(?=[A-Za-z])", "." + ZWSP, t)         # no bare domain link (evil.com)


_REPO = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_SHA = re.compile(r"^[0-9a-f]{7,40}$")
_ACTION = re.compile(r"^/foreman (merge|reject|verdict) #?(\d+)((?: --(?:yes|squash|merge|rebase|close))*)$")
_WHAT = {
    "merge": "Foreman checks it again, then asks you with Merge / Cancel buttons",
    "reject": "add your reason at the end; Foreman posts it with its findings",
    "verdict": "the full reasons",
}
_DEFAULT_ACTIONS = {
    "ready": [("Merge", "merge"), ("Reject", "reject")],
    "needs_owner": [("Reasons", "verdict"), ("Reject", "reject")],
}


def _actions(event: dict, number: int, repo: Optional[str]) -> list:
    """[(label, verb, command)]: only Foreman's own merge, reject and verdict for this pull request. ``--yes`` is
    dropped so the chat asks with its buttons; ``--repo`` is added so the command works in any chat."""
    raw = event.get("actions")
    pairs = []
    if isinstance(raw, list) and raw:
        for a in raw:
            if not isinstance(a, dict) or not isinstance(a.get("command"), str):
                continue
            m = _ACTION.match(" ".join(a["command"].split()))
            if not m or int(m.group(2)) != number:
                continue
            flags = [f for f in m.group(3).split() if f != "--yes"]
            if m.group(1) != "merge":
                flags = [f for f in flags if f == "--close"] if m.group(1) == "reject" else []
            label = clean(a.get("label") or m.group(1).title(), 20) or m.group(1).title()
            pairs.append((label, m.group(1), flags))
    else:
        pairs = [(label, verb, []) for label, verb in _DEFAULT_ACTIONS.get(event.get("kind"), [])]
    out = []
    for label, verb, flags in pairs[:4]:
        command = " ".join(["/foreman", verb, str(number)] + flags + (["--repo", repo] if repo else []))
        out.append((label, verb, command))
    return out


def render(event: dict, platform: str = "") -> str:
    """The message for ``event``. Raises ValueError when the event is not one Foreman can describe."""
    if not isinstance(event, dict):
        raise ValueError("the event is not a dict")
    kind = event.get("kind")
    if kind not in KINDS:
        raise ValueError("unknown event kind %r" % (kind,))
    target = event.get("target") if isinstance(event.get("target"), dict) else {}
    number = target.get("number")
    if target.get("kind", "pr") != "pr" or not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise ValueError("the event names no pull request number")
    repo = event.get("repo") if isinstance(event.get("repo"), str) and _REPO.match(event["repo"]) else None
    code = platform in CODE_PLATFORMS
    head = {"ready": "Foreman: PR #%d is ready to merge and waits for you",
            "needs_owner": "Foreman: PR #%d needs your decision",
            "merged": "Foreman: PR #%d was merged",
            "rejected": "Foreman: PR #%d was rejected"}[kind] % number
    lines = [head]
    lines.append("Repository: %s" % (clean(repo, 100) if repo else "unknown"))
    if target.get("title"):
        lines.append("Title: %s" % clean(target["title"], 120))
    facts = []
    if target.get("branch"):
        facts.append("branch %s" % clean(target["branch"], 60))
    sha = event.get("head")
    if isinstance(sha, str) and _SHA.match(sha):
        facts.append("head %s" % sha[:7])
    if facts:
        lines.append("Change: %s" % " · ".join(facts))
    if event.get("summary"):
        lines.append("Verdict: %s" % clean(event["summary"], 300))
    url = target.get("url")
    if repo and isinstance(url, str) and re.fullmatch(r"https://github\.com/%s/pull/%d" % (re.escape(repo), number),
                                                   url, flags=re.IGNORECASE):
        lines.append(url)
    if kind in ("ready", "needs_owner"):
        actions = _actions(event, number, repo)
        if not repo:
            lines += ["", "Foreman cannot name the repository here: open /foreman where it is pinned to act."]
        elif actions:
            lines.append("")
            for label, verb, command in actions:
                lines.append("%s (%s):" % (label, _WHAT[verb]))
                lines.append("`%s`" % command if code else command)
            lines.append(("Tap a command to copy it, then send it to this chat." if platform == "telegram"
                          else "Copy a command and send it to this chat.")
                         + " Nothing is merged until you confirm there.")
    text = "\n".join(lines)
    return text if len(text) <= 3500 else text[:3497] + "..."


# ─── Sending ─────────────────────────────────────────────────────────────────


def _log_path() -> str:
    return os.path.join(grants.store_dir(), LOG_FILE)


def _load_log() -> list:
    try:
        with open(_log_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []


def _append_log(entry: dict) -> None:
    try:
        with _lock:
            data = (_load_log() + [entry])[-MAX_LOG:]
            path = _log_path()
            fd, tmp = tempfile.mkstemp(prefix=".notify-", dir=os.path.dirname(path))
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=1)
            os.replace(tmp, path)
    except Exception:
        logger.warning("foreman: cannot record the notification", exc_info=True)


def _key(event: dict) -> str:
    """What makes an event new: its kind, repository, pull request and head (never the caller's free-form id)."""
    target = event.get("target") if isinstance(event.get("target"), dict) else {}
    return "%s|%s|%s|%s" % (event.get("kind"), str(event.get("repo") or "").lower(), target.get("number"),
                            event.get("head"))


def _deliver(text: str, target: str) -> tuple:
    """(sent, why_not) for one message through `hermes send`, run by Hermes's terminal tool."""
    folder = os.path.join(grants.store_dir(), "notify")
    os.makedirs(folder, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix="msg-", suffix=".txt", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        quoted = board._quote_path(path)
        if quoted is None:
            return False, "Foreman's data directory has a character a shell would expand: %s" % folder
        command = 'hermes send --to "%s" --file %s --quiet' % (target, quoted)
        state, detail = board._terminal(command, folder, timeout=SEND_TIMEOUT)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if state == "done":
        return True, None
    detail = " ".join(detail.split())[-300:]
    if state == "failed" and ("not found" in detail.lower() or "exit 127" in detail):
        return False, ("`hermes` is not on the PATH of Hermes's terminal (a Docker or remote terminal backend "
                       "cannot reach your bot)%s" % (": " + detail if detail else ""))
    reasons = {"denied": "Hermes's approval denied `hermes send`", "waiting": "Hermes is waiting for an approval",
               "timeout": "`hermes send` did not finish within %d s" % SEND_TIMEOUT,
               "unavailable": "Hermes's terminal tool is not reachable from here"}
    why = reasons.get(state, "`hermes send` failed")
    return False, why + (": " + detail if detail else "")


def _remember_root(event: dict, repo: Optional[str]) -> None:
    """The pipeline may say where the repository lives (``event["root"]``): Foreman then knows it, so the
    ``--repo owner/name`` in the message resolves in a chat with no pinned repository."""
    root = event.get("root")
    if not isinstance(root, str) or not repo or not os.path.isdir(root):
        return
    try:
        from . import detector
        found = detector.find_repo(root)
        if found and repo.lower() in board.remote_names(found):
            board.remember(os.path.normpath(found))
    except Exception:
        logger.warning("foreman: cannot remember the repository", exc_info=True)


def send(event: dict) -> dict:
    """Push ``event`` to the owner's chat. Never raises; ``{"sent": bool, "where": str|None, "why_not": str|None}``.
    Nothing is sent while notifications are off, without a destination, or for an event already sent."""
    try:
        if not enabled():
            return {"sent": False, "where": None, "why_not": "notifications are off (`/foreman notify on` turns them on)"}
        target = destination()
        if not target:
            return {"sent": False, "where": None,
                    "why_not": "no destination: `/foreman notify on telegram` (or another platform) sets one"}
        if not valid_target(target):
            return {"sent": False, "where": target, "why_not": "the destination %r is not a messaging target" % target}
        try:
            text = render(event, target.split(":", 1)[0])
        except ValueError as e:
            return {"sent": False, "where": target, "why_not": "Foreman cannot describe this event: %s" % e}
        key = _key(event)
        if any(e.get("key") == key and e.get("sent") for e in _load_log()):
            return {"sent": False, "where": target, "why_not": "already sent"}
        _remember_root(event, event.get("repo") if isinstance(event.get("repo"), str) else None)
        sent, why = _deliver(text, target)
        _append_log({"key": key, "kind": event.get("kind"), "id": str(event.get("id") or "")[:200],
                     "at": int(time.time()), "sent": sent, "where": target, "why_not": why})
        return {"sent": sent, "where": target, "why_not": why}
    except Exception as e:
        logger.warning("foreman: notification failed", exc_info=True)
        return {"sent": False, "where": None, "why_not": "%s: %s" % (type(e).__name__, e)}


# ─── /foreman notify ─────────────────────────────────────────────────────────

SAMPLE = {
    "kind": "ready", "id": "example/repo#pr:6", "repo": "example/repo",
    "target": {"kind": "pr", "number": 6, "branch": "feat/retry-upload", "title": "Retry the upload on a timeout",
               "url": "https://github.com/example/repo/pull/6"},
    "head": "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
    "summary": "CLEAN: no skipped, deleted or moved tests, no change to the check, no secrets. CI passing.",
    "actions": [{"label": "Merge", "command": "/foreman merge 6 --yes"},
                {"label": "Reject", "command": "/foreman reject 6"}],
}

_HOW = ("It goes out with `hermes send` through Hermes's terminal tool: your own Hermes and bot deliver it; "
        "Foreman never reads a token.")


def _describe(target: str) -> str:
    if not target:
        return "not set"
    platform, _, chat = target.partition(":")
    return "%s (%s)" % (target, "chat %s" % chat if chat else "your %s home channel, set with /sethome there"
                        % platform.title())


def cmd_notify(args: str = "", keys: tuple = (), platform: Optional[str] = None) -> str:
    words = args.split()
    sub = words[0].lower() if words else ""
    target = destination()
    if sub == "":
        last = [e for e in _load_log() if e.get("key") != "test"][-1:]
        lines = ["Foreman notifications: %s" % ("ON" if enabled() else "OFF (nothing is sent anywhere)"),
                 "Destination: %s" % _describe(target),
                 board.wrap("What is sent: one message when a pull request is ready for you or needs your decision, "
                            "with the commands to merge or reject it. " + _HOW)]
        if last:
            e = last[0]
            lines.append("Last: %s %s, %s" % (e.get("kind"), e.get("id"), "sent" if e.get("sent")
                                              else "not sent (%s)" % e.get("why_not")))
        lines.append("Usage: /foreman notify on [telegram|discord:#ops|...] · to <target> · off · test")
        return "\n".join(lines)
    if sub == "off":
        problem = _set("notify", "off")
        return "Foreman: notifications are off." if problem is None else "Foreman: cannot save it: %s" % problem
    if sub in ("on", "to"):
        here = (platform or "").lower()
        new = words[1] if len(words) > 1 else (here if valid_target(here) else target)
        head, sep, chat = new.partition(":")
        new = head.lower() + sep + chat
        if not valid_target(new):
            return ("Foreman: say where to send them: `/foreman notify %s telegram` (your Telegram home channel), "
                    "`telegram:<chat id>`, `discord:#channel`, `slack:<channel id>`." % sub)
        problem = _set("notify_to", new) or (_set("notify", "on") if sub == "on" else None)
        if problem:
            return "Foreman: cannot save it: %s" % problem
        state = "on" if sub == "on" or enabled() else "still off (`/foreman notify on`)"
        return board.wrap("Foreman: notifications are %s, to %s. `/foreman notify test` sends a sample now. %s"
                          % (state, _describe(new), _HOW))
    if sub == "test":
        if not valid_target(target):
            return "Foreman: no destination yet: `/foreman notify on telegram` first."
        text = "(Test message: the pull request below is an example.)\n" + render(SAMPLE, target.split(":", 1)[0])
        sent, why = _deliver(text, target)
        _append_log({"key": "test", "kind": "test", "id": "", "at": int(time.time()), "sent": sent,
                     "where": target, "why_not": why})
        if sent:
            return "Foreman: sent this to %s:\n%s\n%s\n%s" % (target, "-" * 40, text, "-" * 40)
        return "Foreman: the test was NOT sent to %s: %s" % (target, why)
    return "Usage: /foreman notify [on [target] | to <target> | off | test]"


SUBCOMMANDS: dict = {
    "notify": (cmd_notify, "[on [target]|off|test]  tell you on your phone when a PR waits for you"),
}
