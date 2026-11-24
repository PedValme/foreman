# Foreman for OpenCode

Not published yet. A plugin for OpenCode's v2 plugin API (`foreman.ts`), seen working on OpenCode 2.3.2 on macOS. It
is thin: for each thing OpenCode tells it, it runs `python3 -I <this clone>/adapters/hook.py opencode` with one
request (`../foreman_hosts/neutral.py`) and does what the answer says. OpenCode's own words for Foreman live in
`../foreman_hosts/opencode.py`.

Needs Python 3.9 or newer as `python3` on the PATH OpenCode runs with, and git. No npm package, no build step.

## Try it from a clone

Use a clone you are not working in (Foreman keeps the agent out of the clone's `adapters/` and `plugin/`). In the
project where you want Foreman, link the plugin into OpenCode's project plugin folder:

```
mkdir -p .opencode/plugins
ln -s /path/to/foreman/adapters/opencode/foreman.ts .opencode/plugins/foreman.ts
opencode
```

OpenCode loads every `.ts` file in `.opencode/plugins` of the project. A plugin named in `opencode.json`'s `"plugins"`
must be a folder, not a file, so the link is the simple way. The plugin finds `hook.py` through the link, next to its
real file. To keep your own global plugins out of a trial, add to the project's `opencode.json`:

```
{ "plugins": ["-*", "opencode.*", "foreman"] }
```

(`-*` turns every plugin off, `opencode.*` turns OpenCode's built-in ones back on, `foreman` this one. MCP servers
from your global configuration still load.)

## What it does, each seen in a real session

Seen with `opencode run --standalone` and the TUI (`opencode --standalone`, driven through tmux), in a throwaway copy
of `examples/cart` with the link above:

- **Before the agent's shell command.** `git commit`, `git push` and `gh pr create` are inspected and refused with
  the file and line when the change skips, deletes or moves tests, edits what the check runs, bypasses hooks or
  carries a secret; the model reads Foreman's message as the tool's error. An agent-run `gh pr merge` is always
  refused. Seen: a `sed` that added `@unittest.skip` and then `git add -A && git commit -m wip` was refused with
  `[test-skipped] tests/test_cart.py:10` and no commit was made; `gh pr merge 7` was refused.
- **Before a write.** `write`, `edit` and `patch` that switch off a test are refused. Seen: an `edit` that added the
  skip.
- **Before the agent finishes.** When the session is about to go idle and the run changed the working tree and left
  one of those in it, Foreman sends the agent back once with what to undo. Seen: after the refused commit above, the
  agent reported and stopped, Foreman sent it back, it removed the skip. A run that only answered "hello", with a skip
  the person had left in the tree, was not sent back.
- **Your command**, `/foreman status [path]`, `/foreman allow [id]`, `/foreman help`: code, no model turn. OpenCode
  lets a plugin command answer only through an error notice, so the reply appears as one (on a new session its
  title reads "Failed to set up session"; the text is Foreman's). `/foreman allow <id>` first asks you through
  OpenCode's permission prompt; the finding is allowed only when a person approves it there. Seen in the TUI:
  approve allowed it, reject did not.
- **When Foreman must ask you** (it could not inspect a command), the call waits on OpenCode's permission prompt.
  Seen: approved in the TUI, the call ran; under `opencode run` OpenCode rejected it and the model read Foreman's
  message.

## Limits to know

- **The end-of-turn nudge uses OpenCode's `experimental.idle` hook.** OpenCode marks it experimental: its name and
  shape may change in a later version.
- **Nobody attending means refused.** `opencode run` rejects every permission question, so Foreman's ask is refused
  there. `opencode run --auto` approves every question itself, within milliseconds (seen); Foreman counts a yes that
  came sooner than one second after its question as nobody attending and refuses the call. A person who answers in
  under a second is refused too and can run the command again.
- **OpenCode's permission prompt shows "Call tool foreman", not Foreman's message** (2.3.2 renders no text for a
  plugin's own question). The model gets the message when the call is refused; `/foreman status` shows the verdict.
- **`/foreman` only works where OpenCode runs commands** (its TUI and apps). `opencode run "/foreman status"` sends
  the text to the model as an ordinary prompt (seen), so Foreman's commands do nothing there.
- **When the plugin cannot run Python** (no `python3`, an error, no answer within 30 seconds), the agent keeps
  working: a shell command that names git or gh with commit, push, pr or config goes to you as an ask (refused with
  nobody there), every other call runs, and the error is shown once per session, when the run ends, as a failed
  session hook.
- **Turns.** OpenCode gives a session id (`ses_…`) and an id to each message (`msg_…`), but none to one run of the
  agent. The plugin counts a run from your prompt (its message id); OpenCode's own input to the agent does not start
  a new one.
- **The agent's shell starts in the session's directory each time.** A `cd` in one call does not carry to the next,
  and the plugin judges each call in the directory OpenCode runs it in (the `workdir` argument against the session's
  directory).
- The gate runs on the agent's own machine. The independent control is still the required check in CI
  (`examples/foreman-check.yml`). Foreman's plugin file and state are files: the dialect refuses the plain attempts
  to remove or rewrite them (`opencode plugin remove foreman`, `"-foreman"` in `opencode.json`, deleting the
  plugin file, starting a nested OpenCode with `OPENCODE_DISABLE_PROJECT_CONFIG` or another configuration), not a
  disguised one.
- Not seen yet: Windows; OpenCode's background service (all runs above used `--standalone`); OpenCode's desktop and
  web apps.

What it does not do yet: the second-model review, the board, merge and reject with reasons (Foreman on Hermes Agent
has them).
