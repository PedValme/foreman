"""Codex's dialect: its hook events in, its hook answers out.

Codex CLI runs a command hook with one JSON object on standard input and reads one from standard output, with nearly
the field names of Claude Code (checked on Codex CLI 0.171.0, in ``codex exec``):

- ``PreToolUse``: ``tool_name`` is ``Bash`` for a shell command and ``apply_patch`` for a file edit; in both,
  ``tool_input.command`` is a string: the command line, or the ``*** Begin Patch`` text.
  ``hookSpecificOutput.permissionDecision`` ``deny`` refuses the call and the model reads
  ``permissionDecisionReason``. Codex has no ``ask``: a hook that answers it fails and the call goes on, so a
  decision that needs a person is a refusal here, with the message saying why.
- ``Stop``: ``{"decision": "block", "reason": …}`` keeps the agent working with the reason as its next prompt.
- ``UserPromptSubmit``: ``{"decision": "block", "reason": …}`` drops the prompt before any model turn. Only the
  person's typing fires it, so it is where Foreman's commands live. Codex's interactive prompt refuses an unknown
  ``/name`` before any hook (read in its binary, not seen), so here they are typed as plain words, and only as
  these exact one-line prompts: ``foreman``, ``foreman status [path]``, ``foreman allow``, ``foreman help``. Any
  other prompt goes to the model.

Allowing a finding (``foreman allow <id>``) is not available in Codex yet: nothing Codex gives a hook was shown to
tell the person's prompt in an interactive session from a prompt the model writes for a subagent or a resumed
session, and with nobody attending ``allow`` must do nothing (PRODUCTO.md, rule 24). Listing what waits stays.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from typing import Optional

from . import core

NAME = "codex"
CLI = ("codex",)  # the command, and its npm package (`npx @openai/codex`) as core.programs names it
SHELL_TOOLS = {"Bash"}
PATCH_TOOLS = {"apply_patch", "Edit", "Write"}  # Codex reports `apply_patch`; its documentation also names these
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # Foreman's clone or package

# Codex's settings: config.toml, hooks.json and requirements.toml in a `.codex` folder (the user's, a project's)
# or in the system folder (/etc/codex).
_SETTINGS = re.compile(r"(?i)(?:\.codex|/etc/codex)[/\\](?:config\.toml|hooks\.json|requirements\.toml)\b")
_PLUGINS_DIR = re.compile(r"(?i)\.codex[/\\]plugins\b")
_FOREMAN = re.compile(r"(?i)\bforeman\b")
_HOOKS_WORD = re.compile(r"(?i)hooks?\b|allow_managed_hooks_only")  # no leading \b: `printf '…\nhooks = false'`
# In a settings file: every hook off, only managed hooks, or one hook entry switched off by the person's /hooks.
_HOOKS_OFF = re.compile(r"(?im)(?:^|[\s.{,])(?:codex_)?hooks\s*=\s*false\b")
_MANAGED_ONLY = re.compile(r"(?im)\ballow_managed_hooks_only\s*=\s*true\b")
_STATE_OFF = re.compile(r"(?is)\[hooks\.state\.[^\]\n]*\][^\[]*?\benabled\s*=\s*false\b")
_PLUGIN_OFF_TOML = re.compile(r"(?is)\[plugins\.\"?foreman[^\]\n]*\][^\[]*?\benabled\s*=\s*false\b")
# Foreman's own hook, as hooks.json or an inline [hooks] table names it: `adapters/hook.py codex`.
_OWN_HOOK = re.compile(r"(?i)hook\.py[\\\"']*\s+codex\b")
_FEATURE_OFF = re.compile(r"(?i)(?:\bfeatures\s+disable\s+(?:codex_)?hooks\b|--disable[=\s]+(?:codex_)?hooks\b"
                          r"|features\.(?:codex_)?hooks\s*=\s*false)")
_PLUGIN_REMOVE = re.compile(r"(?i)\bplugins?\s+(?:remove|uninstall|rm|disable)\b")


def _switches_off(command: str) -> bool:
    """A command that turns Foreman off in Codex: Codex's hooks feature switched off (`codex features disable
    hooks`, a `codex --disable hooks` session), Foreman's plugin removed, or Codex's settings rewritten to drop or
    disable its hooks. Each simple command on its own; one that only reads (`cat`, `grep`) is not one."""
    for prog, words in core.programs(command):
        text = " ".join(words)
        if prog in CLI and (_FEATURE_OFF.search(text) or (_PLUGIN_REMOVE.search(text) and _FOREMAN.search(text))):
            return True
        if prog == "git" or core.only_reads(prog, words):  # git records a path or a message: it edits no settings
            continue
        if _SETTINGS.search(text) and (_HOOKS_WORD.search(text) or _FOREMAN.search(text)):
            return True
        if _PLUGINS_DIR.search(text) and _FOREMAN.search(text):
            return True
    return False


def _is_config(path: str) -> bool:
    return bool(_SETTINGS.search((path or "").replace("\\", "/")))


def _config_off(before: str, after: str) -> bool:
    """Codex's settings file, once written (``after`` is ``""`` for a deletion), leaves Foreman's hooks off in one
    more way than before: hooks off, only managed hooks, a hook entry or Foreman's plugin disabled, or fewer
    references to Foreman's own hook."""
    before, after = before or "", after or ""
    for rule in (_HOOKS_OFF, _MANAGED_ONLY, _STATE_OFF, _PLUGIN_OFF_TOML):
        if len(rule.findall(after)) > len(rule.findall(before)):
            return True
    return len(_OWN_HOOK.findall(after)) < len(_OWN_HOOK.findall(before))


def _program_dirs(roots) -> tuple:
    """Where Foreman's code is. A copy Codex installed as a plugin (under its plugins folder) is Foreman's whole; in
    a clone only the folders with code are, so the rest of that repository stays workable."""
    out = []
    for root in roots:
        if _PLUGINS_DIR.search(root.replace("\\", "/")):
            out.append(root)
        out += [os.path.join(root, d) for d in ("adapters", ".claude-plugin", "plugin")]
    return tuple(out)


def host(env=None) -> core.Host:
    env = os.environ if env is None else env
    roots = dict.fromkeys(r for r in (ROOT, env.get("PLUGIN_ROOT")) if r)
    # Never attended (the module's docstring says why): allowing a finding is answered before core is asked.
    return core.Host(
        name=NAME, label="Codex", person=lambda sub: "foreman " + sub, program_dirs=_program_dirs(roots),
        cli=CLI, switches_off=_switches_off, is_config=_is_config, config_off=_config_off,
    )


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def _command(args: dict):
    """The command line of a ``Bash`` call: a string, or (in older Codex) an argv list."""
    command = args.get("command")
    if isinstance(command, list) and all(isinstance(w, str) for w in command):
        if len(command) >= 3 and os.path.basename(command[0]) in ("bash", "sh", "zsh") and command[1] in ("-c", "-lc"):
            return command[2]
        return " ".join(shlex.quote(w) for w in command)
    return command


def _where(cwd: str, args: dict) -> str:
    """Where the shell command runs: the call's own ``workdir`` when it gives one (resolved against the session's
    directory), else the hook's ``cwd``."""
    workdir = args.get("workdir")
    if isinstance(workdir, str) and workdir.strip():
        workdir = os.path.expanduser(workdir.strip())
        if os.path.isabs(workdir):
            return os.path.normpath(workdir)
        if cwd:
            return os.path.normpath(os.path.join(cwd, workdir))
    return cwd


def _pre_tool(h: core.Host, data: dict) -> Optional[dict]:
    tool, args = data.get("tool_name"), data.get("tool_input")
    if not isinstance(args, dict):
        return None
    cwd, session, turn = _text(data.get("cwd")), _text(data.get("session_id")), _text(data.get("turn_id"))
    if tool in SHELL_TOOLS:
        return core.pre_shell(h, _command(args), _where(cwd, args), session, turn)
    if tool in PATCH_TOOLS:
        patch = next((args[k] for k in ("command", "patch", "input") if isinstance(args.get(k), str)), None)
        if tool != "apply_patch" and not (patch or "").lstrip().startswith("*** Begin Patch"):
            return None  # an `Edit` or `Write` whose input is not a patch this adapter can read
        return core.pre_patch(h, patch, cwd, session, turn)
    return None


_NEEDS_PERSON = ("Foreman refused this call because it needs a person to decide, and Codex cannot ask from a hook. "
                 "If the user has checked the change, they can run it themselves.\n\n")


def _pre_tool_answer(decision: Optional[dict]) -> Optional[dict]:
    if not decision:
        return None
    message = decision["message"]
    if decision["action"] != core.BLOCK:  # `ask`: Codex would let the call through; refuse it with the reason
        message = _NEEDS_PERSON + message
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": message}}


# The person's commands, only as these exact one-line prompts; anything else is a prompt for the model.
_PERSON_COMMAND = re.compile(r"[ \t]*/?foreman(?:[ \t]+(?:status(?:[ \t]+\S+)?|allow(?:[ \t]+\S+)?|help))?[ \t]*",
                             re.I)
_ALLOW_ID = re.compile(r"[ \t]*/?foreman[ \t]+allow[ \t]+\S+[ \t]*", re.I)
NO_ALLOW = ("Foreman: allowing a finding is not available in Codex yet. Nothing Codex tells its hooks was shown to "
            "tell your own prompt in an interactive session from a prompt the agent writes for a subagent or a "
            "resumed session, and allowing must stay out of the agent's reach. To let a marked finding through, "
            "fix it instead, or commit the change yourself in your own terminal.")


def person_reply(h: core.Host, prompt, cwd: str = "") -> Optional[str]:
    """Foreman's answer when ``prompt`` is exactly one of its commands, else None (the prompt goes to the model)."""
    if not isinstance(prompt, str) or not _PERSON_COMMAND.fullmatch(prompt):
        return None
    if _ALLOW_ID.fullmatch(prompt):
        return NO_ALLOW
    words = prompt.strip().lstrip("/").split(None, 1)
    args = words[1] if len(words) > 1 else ""
    reply = core.person_reply(h, args, cwd)
    if args.lower() in ("allow", "help"):
        reply += "\n\n" + NO_ALLOW
    return reply


def answer(data: dict, env=None) -> Optional[dict]:
    """What Codex should read back for this hook input, or None for nothing (the call goes on)."""
    h = host(env)
    event = data.get("hook_event_name")
    cwd, session, turn = _text(data.get("cwd")), _text(data.get("session_id")), _text(data.get("turn_id"))
    if event == "PreToolUse":
        return _pre_tool_answer(_pre_tool(h, data))
    if event == "UserPromptSubmit":
        reply = person_reply(h, data.get("prompt"), cwd)
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
    """The adapter itself failed. A command the gate would have inspected is refused (Codex cannot ask); nothing
    else is held up by Foreman's own fault."""
    if not isinstance(data, dict) or data.get("hook_event_name") != "PreToolUse":
        return None
    args = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    if data.get("tool_name") in SHELL_TOOLS and core.looks_gated(_command(args)):
        return _pre_tool_answer({"action": core.ASK, "message":
                                 "Foreman could not inspect this command: %s: %s." % (type(error).__name__, error)})
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
