"""pi's dialect: the pi coding agent (``@earendil-works/pi-coding-agent``).

pi's extensions are TypeScript modules that run inside pi, so Foreman's extension there (``adapters/pi/foreman.ts``)
speaks ``neutral.py``'s protocol: it runs ``python3 -I adapters/hook.py pi`` with one request and does what the
answer says. This module adds what is pi's own (pi 1.5.0, its documentation and a real session):

- The person types ``/foreman <subcommand>``: a command the extension registers, which pi runs with no model turn.
- pi is started as ``pi`` (or its npm package, ``npx @earendil-works/pi-coding-agent``).
- What turns an extension off: ``pi remove`` (``uninstall``) of its source, ``pi config`` (pi's screen that enables
  and disables resources), and a settings file (``~/.pi/agent/settings.json``, a project's ``.pi/settings.json``)
  whose ``extensions`` or ``packages`` stop listing it or exclude it (``-path``, ``!pattern``).
- ``attended``: the request's own flag, which the extension takes from pi's ``ctx.hasUI`` (true in pi's terminal
  interface and its RPC mode, false with ``-p`` and ``--mode json``).
- The reviewer (``fresh_session``): pi's own headless run. pi has no flag that enforces a JSON schema, so the schema
  goes into what is sent and the object is read out of the final text. ``--mode json`` is used rather than ``-p``
  because its events say which model answered and why a call failed (``stopReason`` ``error`` and ``errorMessage``);
  standard input alone is the prompt (pi 1.5.0 reads it with no message on the command line).
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from . import core, neutral, reviewer

NAME = "pi"
CLI = ("pi", "pi-coding-agent")  # the command, and its npm package as `npx @earendil-works/pi-coding-agent` runs it
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the clone or package

_FOREMAN = re.compile(r"(?i)foreman")
_REMOVE = {"remove", "uninstall", "rm"}
_SETTINGS = re.compile(r"(?i)(?:^|[/\\\s\"'=~])\.pi[/\\](?:agent[/\\])?settings\.json")
_RESOURCES = re.compile(r"(?i)\b(?:extensions|packages)\b")
_PI_DIR = re.compile(r"[/\\]\.pi[/\\]")
_QUOTED = re.compile(r"\"((?:[^\"\\]|\\.)*)\"")


def _agent_dir(env) -> Optional[str]:
    """``PI_CODING_AGENT_DIR``, where pi keeps its user settings when it is not ``~/.pi/agent``."""
    value = env.get("PI_CODING_AGENT_DIR") if env else None
    return os.path.expanduser(value) if value else None


def _is_settings(text: str, env) -> bool:
    low = text.replace("\\", "/")
    if _SETTINGS.search(low):
        return True
    agent = _agent_dir(env)
    if agent:
        target = (os.path.join(agent, "settings.json")).replace("\\", "/").lower()
        return target in low.lower()
    return False


def _switches_off(env):
    def check(command: str) -> bool:
        """`pi remove <foreman>`, `pi config`, or a command that rewrites pi's settings where it lists its
        extensions or packages. Each simple command on its own; one that only reads (`cat`, `jq .x`) is not one."""
        for prog, words in core.programs(command):
            text = " ".join(words)
            if prog in CLI:
                verbs = [w.lower() for w in words[1:] if not w.startswith("-")]
                if verbs and verbs[0] in _REMOVE and _FOREMAN.search(text):
                    return True
                if verbs and verbs[0] == "config":  # pi's own screen for switching extensions on and off
                    return True
            if prog == "git" or core.only_reads(prog, words):  # git records a path or a message: no settings
                continue
            if _is_settings(text, env) and (_FOREMAN.search(text) or _RESOURCES.search(text)):
                return True
        return False
    return check


def _entries(text: str) -> tuple:
    """(entries that load Foreman, entries that exclude it) among the quoted strings of a settings file."""
    loads = excludes = 0
    for raw in _QUOTED.findall(text or ""):
        if not _FOREMAN.search(raw):
            continue
        if raw.startswith(("-", "!")):
            excludes += 1
        else:
            loads += 1
    return loads, excludes


def _config_off(before: str, after: str) -> bool:
    """A settings file that, once written, lists Foreman in fewer places or excludes it in more than before."""
    loads_before, excludes_before = _entries(before)
    loads_after, excludes_after = _entries(after)
    return loads_after < loads_before or excludes_after > excludes_before


def _program_dirs(roots) -> tuple:
    """Where Foreman's code is. A copy pi installed (under a ``.pi`` folder) is Foreman's whole; in a clone loaded
    with ``pi -e`` only the folders with code are, so the rest of that repository stays workable."""
    out = []
    for root in roots:
        if _PI_DIR.search(root.replace("\\", "/") + "/"):
            out.append(root)
        out += [os.path.join(root, d) for d in ("adapters", "plugin")]
    return tuple(out)


# pi's thinking levels, lowest first (`pi --help`: --thinking; docs/cli.md); a model clamps one it does not support.
PROGRAM = "pi"  # what the reviewer runs; a module name so that tests can replace it, never an environment variable
EFFORTS = ("off", "minimal", "low", "medium", "high", "xhigh", "max")

def _short(text: str, limit: int = 300) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _events(out: str) -> list:
    events = []
    for line in out.split("\n"):
        line = line.strip()
        if line.startswith("{"):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def _fresh_session(env):
    """pi's own headless mode as the reviewer: one prompt on standard input, no tools, no extensions, no skills, no
    context files, no session kept. It starts in an empty directory, so it reads neither the repository under review
    nor its instructions; it uses the login pi already has."""
    def run(system: str, prompt: str, schema: dict, model: str, effort: str, seconds: float) -> core.Answer:
        import shutil
        import tempfile
        program = shutil.which(PROGRAM, path=env.get("PATH")) or PROGRAM  # Windows: `pi` is `pi.cmd`
        # pi cannot hold its model to a schema: the answer is the one object that carries a seal made for this request
        how, seal = reviewer.sealed(schema)
        ask = "%s\n\n%s\n" % (prompt, how)
        with tempfile.TemporaryDirectory(prefix="foreman-review-") as empty, \
                tempfile.TemporaryDirectory(prefix="foreman-review-system-") as holder:
            # The system text goes in a file (pi takes a path for --system-prompt): through pi.cmd on Windows a
            # multi-line value is cut at its first line, and the flags after it with it. Model and thinking come first.
            system_file = os.path.join(holder, "system.md")
            with open(system_file, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(system)
            argv = [program, "--mode", "json", "--no-tools", "--no-extensions", "--no-session", "--no-context-files",
                    "--no-skills", "--no-prompt-templates", "--no-themes", "--no-mcp"]
            if model:
                argv += ["--model", model]
            if effort:
                argv += ["--thinking", effort]
            argv += ["--system-prompt", system_file]
            code, out, err = core.run_session(argv, ask, seconds, env, cwd=empty)
        replies = [e["message"] for e in _events(out)
                   if e.get("type") == "message_end" and isinstance(e.get("message"), dict)
                   and e["message"].get("role") == "assistant"]
        if not replies:
            raise RuntimeError("pi gave no result (exit code %d): %s" % (code, _short(err or out) or "nothing"))
        last = replies[-1]
        if last.get("stopReason") in ("error", "aborted"):
            raise RuntimeError("pi could not answer: %s"
                               % (_short(str(last.get("errorMessage") or err)) or str(last.get("stopReason"))))
        blocks = last.get("content") if isinstance(last.get("content"), list) else []
        final = "".join(b.get("text", "") for b in blocks
                        if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
        return core.Answer(parsed=reviewer.read_sealed(final, seal), text=final, model=str(last.get("model") or ""),
                           provider=str(last.get("provider") or ""))
    return run


def host(request: Optional[dict] = None, env=None) -> core.Host:
    env = os.environ if env is None else env
    request = request if isinstance(request, dict) else {}
    return core.Host(
        name=NAME, label="pi", person=lambda sub: "/foreman " + sub, program_dirs=_program_dirs((ROOT,)),
        cli=CLI, switches_off=_switches_off(env), is_config=lambda path: _is_settings(path, env),
        config_off=_config_off,
        # The extension sends pi's ctx.hasUI. Only a real true counts.
        attended=lambda: neutral.attended(request),
        fresh_session=_fresh_session(env), efforts=EFFORTS, session=lambda: neutral.session(request),
        # Merge and reject too: pi runs the person's command with no model turn, and its own selector asks them.
        board=core.BOARD_READS + core.BOARD_WRITES,
        turn_review=True,  # the extension gives the end of a run a command's time
    )


def main(stdin=None, stdout=None, env=None) -> int:
    return neutral.main(lambda request: host(request, env), stdin=stdin, stdout=stdout)
