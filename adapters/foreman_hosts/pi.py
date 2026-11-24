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
"""
from __future__ import annotations

import os
import re
from typing import Optional

from . import core, neutral

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


def host(request: Optional[dict] = None, env=None) -> core.Host:
    env = os.environ if env is None else env
    request = request if isinstance(request, dict) else {}
    return core.Host(
        name=NAME, label="pi", person=lambda sub: "/foreman " + sub, program_dirs=_program_dirs((ROOT,)),
        cli=CLI, switches_off=_switches_off(env), is_config=lambda path: _is_settings(path, env),
        config_off=_config_off,
        # The extension sends pi's ctx.hasUI. Only a real true counts.
        attended=lambda: neutral.attended(request),
    )


def main(stdin=None, stdout=None, env=None) -> int:
    return neutral.main(lambda request: host(request, env), stdin=stdin, stdout=stdout)
