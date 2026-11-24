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
import shutil
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


# `model_reasoning_effort` as Codex 0.171.0's own model catalog (`codex debug models --bundled`) lists it, lowest
# first. Not every model takes every level (gpt-5.5 stops at xhigh, the luna models at max): Codex says so itself
# when one is refused, and the review shows its reason.
EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")

# What every review in Codex says under its "Reviewer:" line: the limits Codex leaves no way to close
# (adapters/codex/README.md has the measurements).
REVIEWER_CAVEAT = ("In Codex the reviewer's session has no shell and a read-only sandbox, but Codex still gives it "
                   "your global instructions and a few tools Foreman found no switch for (a patch tool the sandbox "
                   "stops, sub-agents): what those could read was not verified.")
_STATUS = re.compile(r"(?<!\d)([45]\d\d)(?!\d)")


def _short(text: str, limit: int = 300) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _event_message(event: dict) -> str:
    error = event.get("error")
    for value in (event.get("message"), error.get("message") if isinstance(error, dict) else error):
        if isinstance(value, str) and value.strip():
            return value
    return ""


# Features switched off in the reviewer's session: whatever can run a command, read the person's files or data,
# reach the network or start other agents. Each name exists in Codex 0.171.0 (`--disable` refuses an unknown one).
# Read with `codex debug prompt-input` (no model call): the shell and command tools are declared by default and
# gone with the first three; the tools Codex still declares are in the README.
TOOLS_OFF = ("shell_tool", "unified_exec", "view_image", "apps", "plugins", "image_generation", "multi_agent",
             "multi_agent_v2")


def _strict(schema):
    """The schema as Codex's API takes it (seen: a 400 without it): every object closed with
    ``additionalProperties: false`` and every property required."""
    if isinstance(schema, list):
        return [_strict(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out = {k: _strict(v) for k, v in schema.items()}
    if out.get("type") == "object" and isinstance(out.get("properties"), dict):
        out["additionalProperties"] = False
        out["required"] = list(out["properties"])
    return out


def _fresh_session(env):
    """Codex's own headless mode as the reviewer: one prompt, no shell or command tool, a read-only sandbox, no session kept, the JSON the
    schema asks for. It starts in an empty directory (so it reads neither the repository under review nor its
    instructions), without the user's config.toml (their hooks, servers and model settings), and uses the login
    Codex already has. Its events come back as JSON lines: the answer is the last agent message."""
    def run(system: str, prompt: str, schema: dict, model: str, effort: str, seconds: float) -> core.Answer:
        import tempfile
        with tempfile.TemporaryDirectory(prefix="foreman-review-") as empty:
            schema_file = os.path.join(empty, "schema.json")
            with open(schema_file, "w", encoding="utf-8") as fh:
                json.dump(_strict(schema or {}), fh)
            work = os.path.join(empty, "work")
            os.mkdir(work)
            # The shell, command and image tools are switched off: the read-only sandbox stops writes and the
            # network, not reads, so a session with a shell could read any file of the person's (seen).
            argv = [shutil.which("codex", path=env.get("PATH")) or "codex", "exec", "--ephemeral", "--ignore-user-config",
                    "--skip-git-repo-check", "--sandbox", "read-only", "--color", "never", "--json",
                    "--output-schema", schema_file, "-c", 'web_search="disabled"']
            for feature in TOOLS_OFF:
                argv += ["--disable", feature]
            if system:  # Foreman's fixed rules (never the diff) as the session's own instructions
                rules = os.path.join(empty, "instructions.md")
                with open(rules, "w", encoding="utf-8") as fh:
                    fh.write(system)
                argv += ["-c", "model_instructions_file=%s" % json.dumps(rules)]  # a TOML string, also on Windows
            if model:
                argv += ["--model", model]
            if effort:
                argv += ["-c", "model_reasoning_effort=%s" % effort]
            argv.append("-")  # the prompt comes from standard input
            code, out, err = core.run_session(argv, prompt, seconds, env, cwd=work)
        text, failure = "", ""
        for line in out.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            kind, item = event.get("type"), event.get("item")
            if kind == "item.completed" and isinstance(item, dict) and item.get("type") == "agent_message":
                text = item.get("text") if isinstance(item.get("text"), str) else text
            elif kind in ("error", "turn.failed"):
                failure = _event_message(event) or failure
        if failure or (code != 0 and not text):
            reason = failure or err or out
            status = _STATUS.search(reason)
            raise RuntimeError("Codex could not answer%s: %s" % (
                " (%s)" % status.group(1) if status else "", _short(reason) or "exit code %d" % code))
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        # Codex does not say which model answered: the review then names the one asked for, or none.
        return core.Answer(parsed=parsed if isinstance(parsed, dict) else None, text=text)
    return run


def _model(data: dict) -> str:
    model = data.get("model") if isinstance(data, dict) else None
    return model if isinstance(model, str) else ""


def host(env=None, data=None) -> core.Host:
    env = os.environ if env is None else env
    data = data if isinstance(data, dict) else {}
    roots = dict.fromkeys(r for r in (ROOT, env.get("PLUGIN_ROOT")) if r)

    def session() -> core.Session:
        # The hook input names the session's model; Codex does not give a hook the reasoning effort, so the
        # reviewer's default is not raised a level.
        return core.Session(model=_model(data))

    # Never attended (the module's docstring says why): allowing a finding is answered before core is asked.
    return core.Host(
        name=NAME, label="Codex", person=lambda sub: "foreman " + sub, program_dirs=_program_dirs(roots),
        cli=CLI, switches_off=_switches_off, is_config=_is_config, config_off=_config_off,
        fresh_session=_fresh_session(env), efforts=EFFORTS, session=session, reviewer_caveat=REVIEWER_CAVEAT,
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


def _where(cwd: str, args: dict) -> Optional[str]:
    """Where the shell command runs: the call's own ``workdir`` when it gives one (resolved against the session's
    directory), else the hook's ``cwd``. None when the workdir is relative and there is no directory to resolve it
    against: then nobody knows where the command runs."""
    workdir = args.get("workdir")
    if isinstance(workdir, str) and workdir.strip():
        workdir = os.path.expanduser(workdir.strip())
        if os.path.isabs(workdir):
            return os.path.normpath(workdir)
        if cwd and os.path.isabs(cwd):
            return os.path.normpath(os.path.join(cwd, workdir))
        return None
    return cwd


def _shell(h: core.Host, args: dict, cwd: str, session: str, turn: str) -> Optional[dict]:
    command, where = _command(args), _where(cwd, args)
    if where is None:
        if core.looks_gated(command):
            return {"action": core.ASK, "message": "Foreman could not inspect this command: its working directory "
                                                   "%r is relative and Codex gave no directory to resolve it "
                                                   "against." % args.get("workdir")}
        where = ""  # the guards still run; the gate has nothing to inspect here
    return core.pre_shell(h, command, where, session, turn)


def _string(args: dict, *keys):
    """The first of ``keys`` whose value is a string, else None ("not given")."""
    return next((args[k] for k in keys if isinstance(args.get(k), str)), None)


def _pre_tool(h: core.Host, data: dict) -> Optional[dict]:
    tool, args = data.get("tool_name"), data.get("tool_input")
    if not isinstance(args, dict):
        return None
    cwd, session, turn = _text(data.get("cwd")), _text(data.get("session_id")), _text(data.get("turn_id"))
    if tool in SHELL_TOOLS:
        return _shell(h, args, cwd, session, turn)
    if tool in PATCH_TOOLS:
        patch = _string(args, "command", "patch", "input")
        if tool == "apply_patch" or (patch or "").lstrip().startswith("*** Begin Patch"):
            return core.pre_patch(h, patch, cwd, session, turn)
        # An `Edit` or `Write` that carries a file and its change instead of a patch: the write's own checks.
        return core.pre_write(h, _string(args, "file_path", "path"), cwd, session, turn,
                              content=_string(args, "content"), old=_string(args, "old_string", "old"),
                              new=_string(args, "new_string", "new"), replace_all=args.get("replace_all") is True)
    return None


_NEEDS_PERSON = ("Foreman refused this call because it needs a person to decide, and Codex cannot ask from a hook. "
                 "If the user has checked the change, they can run it themselves.\n\n")


# The gate's sentences that point at allowing a finding by id, after core.reword, and what to do in Codex instead,
# where allowing is not available (NO_ALLOW below).
_YOURSELF = "fix them, or commit the change yourself in your own terminal; allowing is not available in Codex"
_NO_ALLOW_WORDS = (
    (re.compile(r"ask them to review each one and run `foreman allow <id>` if they agree\."),
     "ask them to review each one: allowing is not available in Codex, so they fix the finding or commit the change "
     "themselves in their own terminal."),
    (re.compile(r"waiting for you \(`foreman allow <id>` if you agree\):"), "waiting for you (%s):" % _YOURSELF),
    (re.compile(r"`foreman allow <id>` if you agree with each one\."), _YOURSELF + "."),
    (re.compile(r"Review each one; `foreman allow <id>` lets that exact finding through for 24 hours:"),
     "Review each one, then %s:" % _YOURSELF),
    (re.compile(r"it waits until you run `foreman allow <id>`\."), "it waits for you: " + _YOURSELF + "."),
    (re.compile(r"waiting for `foreman allow <id>`"), "waiting for you: " + _YOURSELF),
    (re.compile(r"(foreman allow\s+)\[id\](\s+)list findings the agent marked, or allow one of them \(you only\)"),
     r"\1    \2list the findings the agent marked"),
    (re.compile(r"is the user's decision, typed by them \(foreman allow <id>\)\. Ask them to review it\."),
     "is the user's decision, and not available in Codex: ask them to review it, then fix the finding or commit "
     "the change themselves."),
    # anything else that still names it
    (re.compile(r"`?foreman allow <id>`?"), "a fix, or a commit the user makes themselves (allowing is not "
                                             "available in Codex)"),
)


def codex_words(text: str) -> str:
    """The gate's text as it applies in Codex: no advice to run `foreman allow <id>`, which Codex refuses."""
    for pattern, new in _NO_ALLOW_WORDS:
        text = pattern.sub(new, text)
    # The reviewer cannot be set from a Codex prompt: no advice to run `foreman reviewer <model> [effort]` or `default`.
    elsewhere = "in Foreman's config.json (`foreman reviewer <model>` says how)"
    for old, new in ((" `foreman reviewer default` goes back to the default.", ""),
                     ("Choose another with `foreman reviewer <model> [effort]`.", "Choose another " + elsewhere + "."),
                     ("Choose a reviewer with `foreman reviewer <model> [effort]`.", "Choose a reviewer " + elsewhere + ".")):
        text = text.replace(old, new)
    return text


def _pre_tool_answer(decision: Optional[dict]) -> Optional[dict]:
    if not decision:
        return None
    message = codex_words(decision["message"])
    if decision["action"] != core.BLOCK:  # `ask`: Codex would let the call through; refuse it with the reason
        message = _NEEDS_PERSON + message
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": message}}


# The person's commands, only as these exact one-line prompts; anything else is a prompt for the model.
# `review` takes one target and `--fresh`, in either order. `reviewer` takes `default`, an effort, or a model name
# with an optional effort: a lone word has to look like a model name (a dash, dot, digit...), so that
# "foreman reviewer please look" and "foreman reviewer is slow" still reach the model.
_EFFORT_WORD = "(?:%s)" % "|".join(EFFORTS)
_MODEL_WORD = r"[A-Za-z0-9][A-Za-z0-9._:/@#+-]{0,119}"
_MODEL_LIKE = r"(?=[^\s]*[-._:/@0-9])" + _MODEL_WORD
_PERSON_COMMAND = re.compile(
    r"[ \t]*/?foreman(?:[ \t]+(?:status(?:[ \t]+\S+)?|allow(?:[ \t]+\S+)?|help"
    r"|review(?:[ \t]+--fresh(?:[ \t]+[^\s-]\S*)?|[ \t]+[^\s-]\S*(?:[ \t]+--fresh)?)?"
    r"|reviewer(?:[ \t]+(?:default|%s|%s(?:[ \t]+%s)?))?))?[ \t]*" % (_EFFORT_WORD, _MODEL_LIKE, _EFFORT_WORD),
    re.I)
_ALLOW_ID = re.compile(r"[ \t]*/?foreman[ \t]+allow[ \t]+\S+[ \t]*", re.I)
NO_ALLOW = ("Foreman: allowing a finding is not available in Codex yet. Nothing Codex tells its hooks was shown to "
            "tell your own prompt in an interactive session from a prompt the agent writes for a subagent or a "
            "resumed session, and allowing must stay out of the agent's reach. To let a marked finding through, "
            "fix it instead, or commit the change yourself in your own terminal.")


_SET_REVIEWER = re.compile(r"[ \t]*/?foreman[ \t]+reviewer[ \t]+\S.*", re.I)


def no_set_reviewer() -> str:
    from foreman import grants
    return ("Foreman: the reviewer cannot be set from a Codex prompt. Nothing Codex tells its hooks was shown to tell "
            "your own prompt from one the agent writes for a subagent, and a choice saved here is reported by every "
            "later review as yours. Set it yourself in %s, as {\"reviewer\": {\"codex\": {\"model\": \"<model>\", "
            "\"effort\": \"<%s>\"}}} (either may be left out or empty), or delete the file's `codex` entry to go "
            "back to the default. `foreman reviewer` shows who reviews." % (
                os.path.join(grants.store_dir(), "config.json"), "|".join(EFFORTS)))


def person_reply(h: core.Host, prompt, cwd: str = "") -> Optional[str]:
    """Foreman's answer when ``prompt`` is exactly one of its commands, else None (the prompt goes to the model)."""
    if not isinstance(prompt, str) or not _PERSON_COMMAND.fullmatch(prompt):
        return None
    if _ALLOW_ID.fullmatch(prompt):
        return NO_ALLOW
    if _SET_REVIEWER.fullmatch(prompt):
        return no_set_reviewer()
    words = prompt.strip().lstrip("/").split(None, 1)
    args = words[1] if len(words) > 1 else ""
    reply = codex_words(core.person_reply(h, args, cwd)).replace(
        "who reviews: show it, set it, or `default`", "who reviews: show it (setting it is not available in Codex)")
    if args.lower() in ("allow", "help"):
        reply += "\n\n" + NO_ALLOW
    return reply


def answer(data: dict, env=None) -> Optional[dict]:
    """What Codex should read back for this hook input, or None for nothing (the call goes on)."""
    h = host(env, data)
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
            return {"decision": "block", "reason": codex_words(decision["message"])}
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
