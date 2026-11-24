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

import json
import os
import re
import tempfile

from foreman import gate

from . import core, neutral, reviewer

NAME = "opencode"
CLI = ("opencode", "opencode2", "opencode-ai")  # the commands the npm package installs, and its older package name
PLUGIN_ID = "foreman"                             # the id `adapters/opencode/foreman.ts` gives Plugin.define
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # the clone the plugin runs from

_PLUGIN_OFF = re.compile(r"(?i)\bplugins?\s+(?:remove|rm|uninstall|disable)\b")
_FOREMAN = re.compile(r"(?i)\bforeman\b")
_CONFIG_FILE = re.compile(r"(?i)(?:^|[/\\\s\"'=])opencode\.jsonc?\b")
_PLUGIN_DIR = re.compile(r"(?i)(?:\.opencode|opencode)[/\\]plugins?\b")
_OWN_PLUGIN = re.compile(r"(?i)(?:\.opencode|opencode)[/\\]plugins?[/\\][^/\\\s\"']*foreman")  # Foreman's own file
_CONFIG_ENV = re.compile(r"\bOPENCODE_(?:DISABLE_PROJECT_CONFIG|CONFIG_PROJECT_DISABLE|CONFIG|CONFIG_DIR|CONFIG_CONTENT)\b")
_REMOVES = re.compile(r"[\"']-(?:\*|%s)[\"']" % re.escape(PLUGIN_ID))
_REMOVERS = {"rm", "rmdir", "unlink", "mv", "trash", "srm", "shred"}
_COPIERS = {"mv", "cp", "install", "rsync"}   # their last word is where they write
_IN_PLACE = {"sed", "perl", "ruby"}           # with -i they write the files they are given
# Where OpenCode finds plugins, as a command names the folder: the project's `.opencode` and its plugin folder,
# the user's configuration directory (`~/.config/opencode`, or `$XDG_CONFIG_HOME/opencode`) and its plugin folder.
_HOME = r"(?:~|\$home|\$\{home\})"
_XDG = r"(?:\$xdg_config_home|\$\{xdg_config_home\})"
_PLUGIN_HOMES = re.compile(r"(?:(?:^|/)\.opencode|^%s/\.config/opencode|^%s/opencode|^%s/\.config)(?:/plugins?)?$"
                           % (_HOME, _XDG, _HOME))
_DEFINES = re.compile(r"\bid\s*:\s*[\"']%s[\"']" % re.escape(PLUGIN_ID))


def _user_dirs() -> list:
    """The user's OpenCode configuration directory as an absolute path, lower case with forward slashes."""
    out = []
    xdg = os.environ.get("XDG_CONFIG_HOME")
    home = os.path.expanduser("~")
    for base in dict.fromkeys(b for b in (xdg, os.path.join(home, ".config")) if b):
        for p in dict.fromkeys((os.path.abspath(base), os.path.realpath(base))):
            out.append(p.replace("\\", "/").rstrip("/").lower())
    return out


def _folder(word: str) -> str:
    """The folder a removal really targets: `.opencode/*` and `.opencode/plugins/*.ts` empty the folder itself."""
    path = word.replace("\\", "/").rstrip("/").lower()
    while path and re.search(r"[*?\[]", path.rsplit("/", 1)[-1]):
        path = path.rsplit("/", 1)[0] if "/" in path else ""
        path = path.rstrip("/")
    while path.endswith("/."):
        path = path[:-2]
    return path


def _is_plugin_home(word: str) -> bool:
    """`word` names a folder where OpenCode finds plugins (or the user's `.config` holding one), or a glob over it."""
    path = _folder(word)
    if not path:
        return False
    if _PLUGIN_HOMES.search(path):
        return True
    for base in _user_dirs():
        if path in (base, base + "/opencode", base + "/opencode/plugin", base + "/opencode/plugins"):
            return True
    return False


def _operands(words: list) -> list:
    """The words after the program that are not options (all of them after `--`)."""
    out, options = [], True
    for w in words[1:]:
        if isinstance(w, (gate._Redir, gate._Op)):
            continue
        if options and w == "--":
            options = False
        elif options and w.startswith("-") and w != "-":
            continue
        else:
            out.append(w)
    return out


def _written(prog: str, words: list) -> list:
    """The files a simple command writes, as far as its words show: a redirection's target, `tee`'s files, the
    destination of `mv`/`cp`, the files of `sed -i`."""
    out = [words[i + 1] for i, w in enumerate(words[:-1]) if isinstance(w, gate._Redir) and "&" not in w]
    operands = _operands([w for w in words if not isinstance(w, gate._Redir)])
    if prog == "tee":
        out += operands
    elif prog in _COPIERS and len(operands) > 1:
        out.append(operands[-1])
    elif prog in _IN_PLACE and any(w.startswith("-i") or w in ("--in-place", "-pi") for w in words[1:]):
        out += operands[1:] if prog == "sed" else operands
    return [w for w in out if isinstance(w, str)]


def _switches_off(command: str) -> bool:
    """`opencode plugin remove foreman`, an OpenCode started with its configuration replaced or the project's
    skipped, a command that touches OpenCode's configuration naming Foreman or touches Foreman's own plugin file, one
    that deletes, moves or empties (a glob) a folder where OpenCode finds plugins (the project's `.opencode` and its
    plugin folder, the user's `~/.config/opencode` or `$XDG_CONFIG_HOME/opencode` and its plugin folder), or a
    line whose command writes OpenCode's configuration file (redirection, `tee`, `mv`/`cp` destination, `sed -i`)
    while the line holds an entry removing plugins (`"-*"`). One that only reads (`cat`, `grep`) or git (which
    records a path or a message) is not one.

    Not judged: one other named file in a plugin folder (a project's own plugins), and a plain copy of another file
    over the configuration (`cp mine.json opencode.json`), whose content the command does not show; refusing every
    such copy would block ordinary work on a project's own settings, and the required check in CI stays the
    independent control. Refused although harmless: removing another project's `.opencode` (`rm -rf
    examples/app/.opencode`), and a line that deletes a `"-*"` entry from the configuration."""
    programs = core.programs(command)
    writes_config = False
    for prog, words in programs:
        text = " ".join(w for w in words if isinstance(w, str))
        if prog in CLI and _PLUGIN_OFF.search(text) and _FOREMAN.search(text):
            return True
        if prog == "git" or core.only_reads(prog, words):
            continue
        # Foreman named as a word, not as part of a folder's path (a clone or a project may be called foreman).
        named = any(_FOREMAN.search(w) for w in words[1:] if isinstance(w, str) and not re.search(r"[/\\]", w))
        if (_CONFIG_FILE.search(text) and named) or _OWN_PLUGIN.search(text):
            return True
        if prog in _REMOVERS:
            operands = _operands(words)
            targets = operands[:-1] if prog == "mv" else operands
            # The folder itself or a glob over it, not one other named file inside it (a project's own plugins).
            if any(_is_plugin_home(w) for w in targets):
                return True
        if any(_CONFIG_FILE.search("/" + w.replace("\\", "/")) for w in _written(prog, words)):
            writes_config = True
    # A line that writes OpenCode's configuration file with an entry that removes plugins, wherever the entry sits
    # in the line (`jq '.plugins += ["-*"]' opencode.json > t && mv t opencode.json`).
    if writes_config and _REMOVES.search(command or ""):
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


def _short(text: str, limit: int = 300) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


PROGRAM = "opencode"  # the command; tests replace this name (a Windows npm install is `opencode.cmd`: `which` finds it)

# One sentence under every review's "Reviewer:" line: what its session still does that the others' do not.
CAVEAT = ("OpenCode's own managed settings (an administrator's) load after Foreman's and could still override its "
          "denial, and your global OpenCode instructions, MCP servers and plugin modules still load in that session.")


def review_config(agent: str, system: str = "") -> dict:
    """The reviewer's configuration (OpenCode 2.3.2, v2; passed as ``OPENCODE_CONFIG_CONTENT``, read after every
    configuration file). OpenCode applies the last matching permission rule, and a person's own ``agents.build``
    rules are appended after the top-level ones, so a top-level denial alone is not total: the session runs as an
    agent defined here, under a name nobody else's configuration knows, whose own rules (appended last to its list)
    deny every permission. No plugin but OpenCode's built-in ones is loaded."""
    return {"permissions": [{"action": "*", "resource": "*", "effect": "deny"}], "plugins": ["-*", "opencode.*"],
            "agents": {agent: {"mode": "primary", "system": system or "You review a code change. You have no tools.",
                               "permissions": [{"action": "*", "resource": "*", "effect": "deny"}]}}}


def _fresh_session(env=None):
    """OpenCode's own headless command as the reviewer: one prompt on standard input, JSON events out, a private
    server (``--standalone``, so the configuration reaches it), no ``--auto``, a session kept out of the person's
    session lists (``--archived``), every permission denied. It starts in an empty directory, and ``PWD`` points there
    too: ``opencode run`` takes its directory from ``PWD`` before the process's own."""
    def run(system: str, prompt: str, schema: dict, model: str, effort: str, seconds: float) -> core.Answer:
        import secrets
        import shutil
        base = dict(os.environ if env is None else env)
        program = shutil.which(PROGRAM, path=base.get("PATH")) or PROGRAM
        agent = "foreman-reviewer-" + secrets.token_hex(4)
        argv = [program, "run", "--standalone", "--archived", "--format", "json", "--agent", agent]
        if model:
            argv += ["-m", model]
        # OpenCode has no flag that makes a model answer in a JSON schema: the schema goes in words, with a seal the
        # change's author cannot know, and only the object that carries it is read (reviewer.read_sealed).
        asked, seal = reviewer.sealed(schema or {})
        message = "\n\n".join(part for part in (system, asked, prompt) if part)
        with tempfile.TemporaryDirectory(prefix="foreman-review-") as empty:
            child = dict(base, PWD=empty, OPENCODE_CONFIG_CONTENT=json.dumps(review_config(agent)),
                         OPENCODE_DISABLE_CLAUDE_CODE="1")
            code, out, err = core.run_session(argv, message, seconds, child, cwd=empty)
        texts, errors = {}, []
        for line in out.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "text" and isinstance(event.get("part"), dict):
                part = event["part"]
                texts.setdefault(str(part.get("messageID") or ""), []).append(str(part.get("text") or ""))
            elif event.get("type") == "error":
                detail = event.get("error")
                if isinstance(detail, dict):
                    status = detail.get("status")
                    errors.append("%s%s" % ("(HTTP %s) " % status if isinstance(status, int) else "",
                                            detail.get("message") or detail.get("type") or ""))
                else:
                    errors.append(str(detail))
        if errors or code != 0 or not texts:
            raise RuntimeError("OpenCode could not answer (exit code %d): %s"
                               % (code, _short(" ".join(errors) or err or out) or "nothing"))
        final = "".join(texts[list(texts)[-1]])  # the last assistant message
        # OpenCode's JSON events never name the model that ran, so none is claimed.
        return core.Answer(parsed=reviewer.read_sealed(final, seal), text=final, model="")
    return run


def host(request=None) -> core.Host:
    request = request if isinstance(request, dict) else {}
    return core.Host(
        name=NAME, label="OpenCode", person=lambda sub: "/foreman " + sub, program_dirs=_program_dirs(),
        cli=CLI, switches_off=_switches_off, is_config=_is_config, config_off=_config_off,
        # The plugin says true only from the /foreman command's own handler, after the person answered OpenCode's
        # own question in its interface.
        attended=lambda: neutral.attended(request),
        # No effort levels: OpenCode names reasoning levels per model (a ``#variant``), so the person names it as
        # part of the model: ``/foreman reviewer provider/model#variant``.
        fresh_session=_fresh_session(), efforts=(), session=lambda: neutral.session(request),
        reviewer_caveat=CAVEAT,
    )


def main(stdin=None, stdout=None) -> int:
    return neutral.main(host, stdin=stdin, stdout=stdout)
