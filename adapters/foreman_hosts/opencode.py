"""OpenCode's dialect: its plugins (``adapters/opencode/``) speak ``neutral.py``'s protocol.

OpenCode (checked on 2.3.2, its v2 plugin API) runs a plugin's server part inside its own server
(``adapters/opencode/foreman.ts``: the gate, and ``/foreman`` as a server command) and a plugin's TUI part inside its
terminal interface (``adapters/opencode/tui.ts``: ``/foreman`` typed there). Both are TypeScript that send one
``neutral`` request per event and do what the answer says. This module is what differs for OpenCode on the Python
side: how the person types Foreman's command, OpenCode's own command names, and what turns a plugin off there.

Who is attending (``attended``): the TUI part sends ``true`` for every ``/foreman`` it handles. A TUI plugin's slash
command runs in the TUI process only for what a person typed at its prompt; no auto-approve mode answers its dialogs
and OpenCode 2.3.2 gives the model's tools no way to type into it (read in the source, seen in a session). What
remains (adapters/opencode/README.md): keys typed into the terminal from the agent's own shell, and plugin code the
agent writes into a plugin folder, which OpenCode loads and which needs no Foreman to run gh. The server part sends ``true`` only for
``allow <id>``, after a person answered OpenCode's permission prompt: a server command cannot tell a person's TUI from
the HTTP API, the SDK or ``opencode api``, so through it ``merge`` and ``reject`` find nobody attending.

How OpenCode turns a plugin off (its source, 2.3.2: ``config/plugin/source.ts``, ``plugin/supervisor.ts`` and the TUI's
``plugin/context.tsx``):

- ``"plugins": ["-foreman"]`` (or ``"-*"``) in any ``opencode.json`` / ``opencode.jsonc`` it reads removes the server
  plugin with that id, even one installed globally: explicit configuration is applied last. The TUI reads its own
  ``plugins`` list, in the user's ``cli.json`` (``~/.config/opencode/cli.json``), and a ``"-foreman"`` there removes
  the TUI part.
- A plugin file auto-discovered in a ``plugin``/``plugins`` folder of a configuration directory (``.opencode/plugins``
  in a project, ``~/.config/opencode/plugins``) is off once that file is deleted or rewritten; a plugin folder there
  (the form the TUI part needs) once the folder or its files are.
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
# OpenCode's configuration files: a project's or the user's `opencode.json(c)`, and the TUI's own `opencode/cli.json`.
_CONFIG_FILE = re.compile(r"(?i)(?:(?:^|[/\\\s\"'=])opencode\.jsonc?|opencode[/\\]cli\.json)\b")
_CLI_CONFIG = re.compile(r"(?i)(?:^|/)opencode/cli\.json$")
_PLUGIN_DIR = re.compile(r"(?i)(?:\.opencode|opencode)[/\\]plugins?\b")
# Foreman's own file or folder in a plugin folder (`.opencode/plugins/foreman.ts`, `.opencode/plugins/foreman/`)
_OWN_PLUGIN = re.compile(r"(?i)(?:\.opencode|opencode)[/\\]plugins?[/\\][^/\\\s\"']*foreman")
_IN_OWN_FOLDER = re.compile(r"(?i)(?:\.opencode|opencode)/plugins?/[^/]*foreman[^/]*/")  # a file inside that folder
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
# A package specifier that loads Foreman, as `opencode plugin add` writes it: npm's name (with a version or not)
# or the repository's git URL. Only those forms: a path that merely ends in `foreman` (another program's binary in
# an MCP entry, a folder in an instructions path) is somebody's ordinary configuration.
_PACKAGE_ENTRY = re.compile(
    r"[\"'](?:foreman-gate(?:@[^\"'\s]*)?"
    r"|(?:git\+|github:|https?://|ssh://|git@)[^\"'\s]*[/:]foreman(?:\.git)?(?:#[^\"'\s]*)?)[\"']", re.I)
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
    """An OpenCode configuration file (the TUI's `cli.json` included), a Foreman plugin file in one of OpenCode's
    plugin folders, or a file inside Foreman's own plugin folder there (the folder form the TUI part needs)."""
    p = path.replace("\\", "/")
    name = p.rsplit("/", 1)[-1].lower()
    if name in ("opencode.json", "opencode.jsonc") or _CLI_CONFIG.search(p):
        return True
    if _IN_OWN_FOLDER.search(p):
        return True
    return bool(_PLUGIN_DIR.search(p)) and _FOREMAN.search(name) is not None


def _config_off(before: str, after: str) -> bool:
    """Once written, the file removes Foreman in one more place than before (`"-foreman"`, `"-*"`), or it was the
    plugin file that defines Foreman and no longer does (rewritten or deleted)."""
    before, after = before or "", after or ""
    if len(_REMOVES.findall(after)) > len(_REMOVES.findall(before)):
        return True
    # The entry `opencode plugin add` wrote (`"foreman-gate"`, `"git+https://github.com/PedValme/foreman.git"`)
    # dropped from the list: the package is no longer loaded.
    if len(_PACKAGE_ENTRY.findall(after)) < len(_PACKAGE_ENTRY.findall(before)):
        return True
    return bool(_DEFINES.search(before)) and not _DEFINES.search(after)


_PACKAGE_COPY = re.compile(r"(?i)/node_modules/foreman-gate/?$")


def _program_dirs(root: str = None) -> tuple:
    """Where Foreman's code is. A package OpenCode installed (`opencode plugin add`, under its cache's
    `npm/…/node_modules/foreman-gate`) is Foreman's whole: its `package.json` names the server and TUI parts OpenCode
    loads. In a clone only the folders with code are: OpenCode loads the plugin from `adapters/opencode`, which runs
    `adapters/hook.py`, which runs `plugin/foreman`; the rest of that repository stays workable."""
    root = ROOT if root is None else root
    whole = (root,) if _PACKAGE_COPY.search(root.replace("\\", "/")) else ()
    return whole + tuple(os.path.join(root, d) for d in ("adapters", "plugin"))


def _short(text: str, limit: int = 300) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


ATTENDED_WHERE = "OpenCode's terminal interface (the TUI) with Foreman's TUI plugin installed"

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
        # Foreman's rules are the agent's own system text (in the configuration); only the sealed instruction and the
        # review's prompt, the untrusted diff included, go in as the message.
        message = "\n\n".join(part for part in (asked, prompt) if part)
        with tempfile.TemporaryDirectory(prefix="foreman-review-") as empty:
            child = dict(base, PWD=empty, OPENCODE_CONFIG_CONTENT=json.dumps(review_config(agent, system)),
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
        # The TUI part says true for what a person typed at the TUI's prompt; the server part only for `allow <id>`,
        # after the person answered OpenCode's own permission prompt (the module's docstring).
        attended=lambda: neutral.attended(request),
        # No effort levels: OpenCode names reasoning levels per model (a ``#variant``), so the person names it as
        # part of the model: ``/foreman reviewer provider/model#variant``.
        fresh_session=_fresh_session(), efforts=(), session=lambda: neutral.session(request),
        # Merge and reject too, for the person at the TUI; through the server command they find nobody attending.
        reviewer_caveat=CAVEAT, board=core.BOARD_READS + core.BOARD_WRITES, attended_where=ATTENDED_WHERE,
        turn_review=True,  # the plugin gives the end of a turn a command's time (adapters/opencode/foreman.ts)
    )


def main(stdin=None, stdout=None) -> int:
    return neutral.main(host, stdin=stdin, stdout=stdout)
