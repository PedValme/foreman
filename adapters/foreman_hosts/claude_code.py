"""Claude Code's dialect: its hook events in, its hook answers out.

Claude Code runs a command hook with one JSON object on standard input and reads one from standard output
(checked on Claude Code 2.1.331):

- ``PreToolUse``: ``hookSpecificOutput.permissionDecision`` ``deny`` blocks the call in every permission mode and
  the model reads ``permissionDecisionReason``; ``ask`` puts the call in front of the person (with nobody there,
  ``-p``, Claude Code refuses it).
- ``Stop``: ``{"decision": "block", "reason": …}`` keeps the agent working with the reason as its next instruction.
- ``UserPromptSubmit``: ``{"decision": "block", "reason": …}`` shows the reason to the person and no model turn
  happens. Only the person's typing fires it, so it is where Foreman's commands live: the plugin's
  ``/foreman:status``, ``/foreman:allow`` and ``/foreman:help`` are answered here before they reach the model.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Optional

from . import core

NAME = "claude-code"
CLI = ("claude", "claude-code")  # the command, and its npm package as `npx @anthropic-ai/claude-code` runs it
SHELL_TOOLS = {"Bash", "PowerShell"}
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the installed plugin

_PLUGIN_OFF = re.compile(r"(?i)\bplugins?\s+(?:disable|uninstall|remove|rm)\b")
_FOREMAN = re.compile(r"(?i)\bforeman\b")
_SETTINGS = re.compile(r"(?i)\.claude[/\\](?:managed-)?settings(?:\.local)?\.json")
_PLUGINS_DIR = re.compile(r"(?i)\.claude[/\\]plugins\b")
_HOOKS_WORD = re.compile(r"(?i)disableAllHooks")
_HOOKS_OFF = re.compile(r"(?i)[\"']disableAllHooks[\"']\s*:\s*true")
_PLUGIN_FALSE = re.compile(r"(?i)foreman[^\"'\n]*[\"']\s*:\s*false")


def _switches_off(command: str) -> bool:
    """`claude plugin disable foreman`, or a command that rewrites Claude Code's settings or its plugins folder to
    switch hooks or this plugin off. Each simple command on its own; one that only reads (`cat`, `grep`) is not
    one."""
    for prog, words in core.programs(command):
        text = " ".join(words)
        if prog in CLI and _PLUGIN_OFF.search(text) and _FOREMAN.search(text):
            return True
        if prog == "git" or core.only_reads(prog, words):  # git records a path or a message: it edits no settings
            continue
        if _SETTINGS.search(text) and (_HOOKS_WORD.search(text) or _FOREMAN.search(text)):
            return True
        if _PLUGINS_DIR.search(text) and _FOREMAN.search(text):
            return True
    return False


def _is_config(path: str) -> bool:
    return bool(_SETTINGS.search(path.replace("\\", "/")))


def _config_off(before: str, after: str) -> bool:
    """A settings file that, once written, disables every hook or this plugin in one more place than before."""
    return any(len(rule.findall(after or "")) > len(rule.findall(before or "")) for rule in (_HOOKS_OFF, _PLUGIN_FALSE))


def _program_dirs(roots) -> tuple:
    """Where the plugin's code is. A copy Claude Code installed (under its plugins folder) is Foreman's whole; in a
    clone loaded with --plugin-dir only the folders with code are, so the rest of that repository stays workable."""
    out = []
    for root in roots:
        if _PLUGINS_DIR.search(root.replace("\\", "/")):
            out.append(root)
        out += [os.path.join(root, d) for d in ("adapters", ".claude-plugin", "plugin")]
    return tuple(out)


EFFORTS = ("low", "medium", "high", "xhigh", "max")  # `claude --effort`, lowest first


def _effort(data: dict) -> str:
    """The session's effort as this hook input states it (`effort.level`; not every event carries it)."""
    effort = data.get("effort") if isinstance(data, dict) else None
    level = effort.get("level") if isinstance(effort, dict) else None
    return level if level in EFFORTS else ""


def _short(text: str, limit: int = 300) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _fresh_session(env):
    """Claude Code's own headless mode as the reviewer: one prompt, no tools, no session kept, the JSON the schema
    asks for. It starts in an empty directory and reads only that directory's local settings, so neither the
    project's instructions nor anyone's hooks or plugins are part of it; it uses the login Claude Code already has."""
    def run(system: str, prompt: str, schema: dict, model: str, effort: str, seconds: float) -> core.Answer:
        import tempfile
        argv = [env.get("CLAUDE_CODE_EXECPATH") or "claude", "-p", "--output-format", "json",
                "--json-schema", json.dumps(schema), "--tools", "", "--no-session-persistence",
                "--setting-sources", "local", "--system-prompt", system]
        if model:
            argv += ["--model", model]
        if effort:
            argv += ["--effort", effort]
        with tempfile.TemporaryDirectory(prefix="foreman-review-") as empty:
            code, out, err = core.run_session(argv, prompt, seconds, env, cwd=empty)
        try:
            data = json.loads(out)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            raise RuntimeError("Claude Code gave no result (exit code %d): %s" % (code, _short(err or out) or "nothing"))
        if data.get("is_error") or data.get("subtype") != "success":
            status = data.get("api_error_status")
            raise RuntimeError("Claude Code could not answer%s: %s" % (
                " (%s)" % status if status else "", _short(str(data.get("result") or data.get("subtype") or err))))
        parsed = data.get("structured_output")
        if not isinstance(parsed, dict):
            try:
                parsed = json.loads(data.get("result") or "")
            except (ValueError, TypeError):
                parsed = None
        usage = data.get("modelUsage") if isinstance(data.get("modelUsage"), dict) else {}
        ran = max(usage, key=lambda m: (usage[m] or {}).get("outputTokens", 0) if isinstance(usage[m], dict) else 0,
                  default="")
        return core.Answer(parsed=parsed if isinstance(parsed, dict) else None, text=str(data.get("result") or ""),
                           model=str(ran))
    return run


def host(env=None, data=None) -> core.Host:
    env = os.environ if env is None else env
    data = data if isinstance(data, dict) else {}
    roots = dict.fromkeys(r for r in (ROOT, env.get("CLAUDE_PLUGIN_ROOT")) if r)

    def session() -> core.Session:
        # Claude Code states the effort on tool and stop events, not on the prompt the person's command arrives
        # with: the last one it stated for this session stands in. It does not tell a hook the model.
        return core.Session(effort=_effort(data) or core.noted(h, _text(data.get("session_id")), "effort"))

    h = core.Host(
        name=NAME, label="Claude Code", person=lambda sub: "/foreman:" + sub, program_dirs=_program_dirs(roots),
        cli=CLI, switches_off=_switches_off, is_config=_is_config, config_off=_config_off,
        # Claude Code sets it for its hooks: "1" in an interactive session, "0" with -p or the SDK.
        attended=lambda: env.get("CLAUDE_CODE_SESSION_ATTENDED") == "1",
        fresh_session=_fresh_session(env), efforts=EFFORTS, session=session,
    )
    return h


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def _pre_tool(h: core.Host, data: dict) -> Optional[dict]:
    tool, args = data.get("tool_name"), data.get("tool_input")
    if not isinstance(args, dict):
        return None
    cwd, session, turn = _text(data.get("cwd")), _text(data.get("session_id")), _text(data.get("prompt_id"))
    if tool in SHELL_TOOLS:
        return core.pre_shell(h, args.get("command"), cwd, session, turn)
    if tool == "Write":
        return core.pre_write(h, args.get("file_path"), cwd, session, turn, content=_text(args.get("content")))
    if tool == "Edit":
        return core.pre_write(h, args.get("file_path"), cwd, session, turn, old=_text(args.get("old_string")),
                              new=_text(args.get("new_string")), replace_all=bool(args.get("replace_all")))
    if tool == "MultiEdit":
        edits = args.get("edits") if isinstance(args.get("edits"), list) else []
        asked = None
        for edit in edits or [{}]:
            edit = edit if isinstance(edit, dict) else {}
            d = core.pre_write(h, args.get("file_path"), cwd, session, turn, old=_text(edit.get("old_string")),
                               new=_text(edit.get("new_string")), replace_all=bool(edit.get("replace_all")))
            if d and d["action"] == core.BLOCK:
                return d
            asked = asked or d
        return asked
    if tool == "NotebookEdit":  # guards only: a notebook cell is not a test file the gate reads
        return core.pre_write(h, args.get("notebook_path"), cwd, session, turn)
    return None


def _pre_tool_answer(decision: Optional[dict]) -> Optional[dict]:
    if not decision:
        return None
    verdict = "deny" if decision["action"] == core.BLOCK else "ask"
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": verdict,
                                   "permissionDecisionReason": decision["message"]}}


def answer(data: dict, env=None) -> Optional[dict]:
    """What Claude Code should read back for this hook input, or None for nothing (the call goes on)."""
    h = host(env, data)
    event = data.get("hook_event_name")
    cwd, session, turn = _text(data.get("cwd")), _text(data.get("session_id")), _text(data.get("prompt_id"))
    if _effort(data):
        core.note(h, session, "effort", _effort(data))  # for the reviewer's default: one level above the session's
    if event == "PreToolUse":
        return _pre_tool_answer(_pre_tool(h, data))
    if event == "UserPromptSubmit":
        reply = core.person_command(h, data.get("prompt"), cwd, session)
        if reply is not None:
            return {"decision": "block", "reason": reply}
        core.turn_start(h, cwd, session, turn)
        return None
    if event == "Stop":
        decision = core.end_of_turn(h, cwd, session, turn)
        if decision and decision["action"] == core.CONTINUE:
            return {"decision": "block", "reason": decision["message"]}
    return None


def _failed(data: dict, error: Exception) -> Optional[dict]:
    """The adapter itself failed. A command the gate would have inspected goes to the person; nothing else is
    held up by Foreman's own fault."""
    if not isinstance(data, dict) or data.get("hook_event_name") != "PreToolUse":
        return None
    args = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    if data.get("tool_name") in SHELL_TOOLS and core.looks_gated(args.get("command")):
        return _pre_tool_answer({"action": core.ASK, "message":
                                 "Foreman could not inspect this command: %s: %s. Approve only if you have checked "
                                 "the change yourself." % (type(error).__name__, error)})
    return None


def main(stdin=None, stdout=None, env=None) -> int:
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    raw = stdin.buffer.read() if hasattr(stdin, "buffer") else stdin.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig", "replace")
    try:
        data = json.loads(raw.lstrip("﻿") or "{}")
    except ValueError:
        sys.stderr.write("Foreman: the hook input is not JSON.\n")
        return 1
    if not isinstance(data, dict):
        return 0
    try:
        out = answer(data, env)
    except Exception as e:  # never a stack trace instead of a decision
        sys.stderr.write("Foreman: %s: %s\n" % (type(e).__name__, e))
        out = _failed(data, e)
        if out is None:
            return 1
    if out is not None:
        stdout.write(json.dumps(out))
    return 0
