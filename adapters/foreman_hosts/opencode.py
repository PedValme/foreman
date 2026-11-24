"""OpenCode's dialect: its plugin (``adapters/opencode/foreman.ts``) speaks ``neutral.py``'s protocol.

OpenCode (checked on 2.3.2, its v2 plugin API) runs plugins inside its own server, so Foreman's plugin there is
TypeScript that sends one ``neutral`` request per event and does what the answer says. This module is what differs
for OpenCode on the Python side: how the person types Foreman's command, OpenCode's own command names, and what turns
a plugin off there.

How OpenCode turns a plugin off (its source, 2.3.2: ``config/plugin/source.ts`` and ``plugin/supervisor.ts``):

- ``"plugins": ["-foreman"]`` (or ``"-*"``) in any ``opencode.json`` / ``opencode.jsonc`` it reads removes the plugin
  with that id, even one installed globally: explicit configuration is applied last.
- A plugin file auto-discovered in a ``plugin``/``plugins`` folder of a configuration directory (``.opencode/plugins``
  in a project, ``~/.config/opencode/plugins``) is off once that file is deleted or rewritten.
- ``OPENCODE_DISABLE_PROJECT_CONFIG`` (or ``OPENCODE_CONFIG_PROJECT_DISABLE``) skips the project's configuration, and
  ``OPENCODE_CONFIG``, ``OPENCODE_CONFIG_DIR`` and ``OPENCODE_CONFIG_CONTENT`` replace or add to it, for an OpenCode
  started with them: from the agent's shell, a nested session without Foreman.
- ``opencode plugin remove …`` edits the global configuration.
"""
from __future__ import annotations

import os
import re

from . import core, neutral

NAME = "opencode"
CLI = ("opencode", "opencode2", "opencode-ai")  # the commands the npm package installs, and its older package name
PLUGIN_ID = "foreman"                             # the id `adapters/opencode/foreman.ts` gives Plugin.define
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the clone the plugin runs from

_PLUGIN_OFF = re.compile(r"(?i)\bplugins?\s+(?:remove|rm|uninstall|disable)\b")
_FOREMAN = re.compile(r"(?i)\bforeman\b")
_CONFIG_FILE = re.compile(r"(?i)(?:^|[/\\\s\"'=])opencode\.jsonc?\b")
_PLUGIN_DIR = re.compile(r"(?i)(?:\.opencode|opencode)[/\\]plugins?\b")
_CONFIG_ENV = re.compile(r"\bOPENCODE_(?:DISABLE_PROJECT_CONFIG|CONFIG_PROJECT_DISABLE|CONFIG|CONFIG_DIR|CONFIG_CONTENT)\b")
_REMOVES = re.compile(r"[\"']-(?:\*|%s)[\"']" % re.escape(PLUGIN_ID))
_DEFINES = re.compile(r"\bid\s*:\s*[\"']%s[\"']" % re.escape(PLUGIN_ID))


def _switches_off(command: str) -> bool:
    """`opencode plugin remove foreman`, an OpenCode started with its configuration replaced or the project's
    skipped, or a command that rewrites OpenCode's configuration or its plugin folder where Foreman is named. Each
    simple command on its own; one that only reads (`cat`, `grep`) or git (which records a path or a message) is
    not one."""
    for prog, words in core.programs(command):
        text = " ".join(words)
        if prog in CLI and _PLUGIN_OFF.search(text) and _FOREMAN.search(text):
            return True
        if prog == "git" or core.only_reads(prog, words):
            continue
        if (_CONFIG_FILE.search(text) or _PLUGIN_DIR.search(text)) and _FOREMAN.search(text):
            return True
    # The variables go before the program (`OPENCODE_DISABLE_PROJECT_CONFIG=1 opencode run …`), where programs()
    # skips them, or through `env`/`export`: judge the line as a whole once it starts OpenCode.
    return bool(_CONFIG_ENV.search(command or "")) and any(prog in CLI for prog, _words in core.programs(command))


def _is_config(path: str) -> bool:
    """An OpenCode configuration file, or a Foreman plugin file in one of OpenCode's plugin folders."""
    p = path.replace("\\", "/")
    name = p.rsplit("/", 1)[-1].lower()
    if name in ("opencode.json", "opencode.jsonc"):
        return True
    return bool(_PLUGIN_DIR.search(p)) and _FOREMAN.search(name) is not None


def _config_off(before: str, after: str) -> bool:
    """Once written, the file removes Foreman in one more place than before (`"-foreman"`, `"-*"`), or it was the
    plugin file that defines Foreman and no longer does (rewritten or deleted)."""
    before, after = before or "", after or ""
    if len(_REMOVES.findall(after)) > len(_REMOVES.findall(before)):
        return True
    return bool(_DEFINES.search(before)) and not _DEFINES.search(after)


def _program_dirs() -> tuple:
    """The clone's folders with code: OpenCode loads the plugin from `adapters/opencode`, which runs
    `adapters/hook.py`, which runs `plugin/foreman`. The rest of that repository stays workable."""
    return tuple(os.path.join(ROOT, d) for d in ("adapters", "plugin"))


def host(request=None) -> core.Host:
    request = request if isinstance(request, dict) else {}
    return core.Host(
        name=NAME, label="OpenCode", person=lambda sub: "/foreman " + sub, program_dirs=_program_dirs(),
        cli=CLI, switches_off=_switches_off, is_config=_is_config, config_off=_config_off,
        # The plugin says true only from the /foreman command's own handler, after the person answered OpenCode's
        # own question in its interface.
        attended=lambda: neutral.attended(request),
    )


def main(stdin=None, stdout=None) -> int:
    return neutral.main(host, stdin=stdin, stdout=stdout)
