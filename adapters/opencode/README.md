# Foreman for OpenCode

Not published yet. A plugin for OpenCode's v2 plugin API (`foreman.ts`), seen working on OpenCode 2.3.2 on macOS. It
is thin: for each thing OpenCode tells it, it runs `python3 -I <this clone>/adapters/hook.py opencode` with one
request (`../foreman_hosts/neutral.py`) and does what the answer says. OpenCode's own words for Foreman live in
`../foreman_hosts/opencode.py`.

Needs Python 3.9 or newer as `python3` on the PATH OpenCode runs with, and git. No npm package, no build step.

## Install it

Use a clone you are not working in (Foreman keeps the agent out of the clone's `adapters/` and `plugin/`).

**For real use, link it into your user plugin folder**, so it covers every project and every worktree a session
moves to:

```
mkdir -p ~/.config/opencode/plugins
ln -s /path/to/foreman/adapters/opencode/foreman.ts ~/.config/opencode/plugins/foreman.ts
```

With `XDG_CONFIG_HOME` set, OpenCode's user folder is `$XDG_CONFIG_HOME/opencode` instead: link it into
`$XDG_CONFIG_HOME/opencode/plugins`. OpenCode loads every `.ts` file in the `plugins` folder of its configuration
directories, the user's included. This
form was read in OpenCode's documentation and source (2.3.2), not seen running: the trials below never wrote to a
user's OpenCode configuration.

**To try it in one project**, link it into that project's plugin folder instead (this is what the trials below
used):

```
mkdir -p .opencode/plugins
ln -s /path/to/foreman/adapters/opencode/foreman.ts .opencode/plugins/foreman.ts
opencode
```

A plugin named in `opencode.json`'s `"plugins"` must be a folder, not a file, so a link is the simple way. The
plugin finds `hook.py` through the link, next to its real file. To keep your own global plugins out of a trial, add
to the project's `opencode.json`:

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
- **Your command**, `/foreman status [path]`, `/foreman allow [id]`, `/foreman review`, `/foreman reviewer`,
  `/foreman help` (the review has its own section below): code, no model turn. OpenCode
  lets a plugin command answer only through an error notice, so the reply appears as one (on a new session its
  title reads "Failed to set up session"; the text is Foreman's). `/foreman allow <id>` first asks you through
  OpenCode's permission prompt; the finding is allowed only when a person approves it there. Seen in the TUI:
  approve allowed it, reject did not.
- **When Foreman must ask you** (it could not inspect a command), the call waits on OpenCode's permission prompt.
  Seen: approved in the TUI, the call ran; under `opencode run` OpenCode rejected it and the model read Foreman's
  message.

## The review

`/foreman review [pull request|branch] [--fresh]`: Foreman starts a fresh OpenCode session that did not write the
code, gives it the diff and checks that every finding it returns quotes a line of that diff. It is advisory: it
grants, merges and unblocks nothing. The same diff by the same reviewer is never sent twice (`--fresh` asks again).
Who reviews is yours: `/foreman reviewer [model]` (`default` to go back), a model as `opencode models` lists it,
`provider/model`.

- **A variant is part of the model.** OpenCode has no effort setting. A model may have variants (named options,
  usually a reasoning level or a thinking budget), written `provider/model#variant`, and the names belong to each
  model (its catalog entry or your `variants`), not to a fixed ladder: `#high` exists for one model and not for
  another. So Foreman has no effort levels here: name the variant in the model, `/foreman reviewer
  openai/gpt-6.1-sol#high`. An unknown variant is an error from OpenCode and the review says so.
- **What it runs**: `opencode run --standalone --format json [-m <model>]`, the prompt on standard input (never on the
  command line), in an empty temporary directory, so it reads neither the repository nor its settings. It is a
  private server (`--standalone`) so that the configuration below reaches it, and it is never started with `--auto`.
- **It cannot change anything.** Foreman passes it, in `OPENCODE_CONFIG_CONTENT` (read after your configuration
  files), a rule denying every permission and no plugin but OpenCode's built-in ones, and
  `OPENCODE_DISABLE_CLAUDE_CODE=1` so that your Claude Code instructions are not read; `FOREMAN_REVIEWER=1` makes
  Foreman's own plugin do nothing inside it. Seen: told to create a file and run `ls`, the session answered that it
  has no write or shell tool, and the file did not exist.
- **Who reviews by default**: OpenCode's default model, with a clean context and nothing raised: OpenCode does not
  tell a plugin an effort, so the review says it is the model that wrote the code unless this session uses another
  one. Choose another model to get a second opinion. Each review says who it was, and the model of this session when
  OpenCode's record of it says so.
- **Seen** (OpenCode 2.3.2, macOS, an OpenCode Go model, a throwaway copy of `examples/cart`): an assertion loosened
  from an exact value to "is true", which the gate cannot see (CLEAN), came back BLOCKED with the line quoted. The same
  diff again was answered from the stored result without a call. The Python side was called as the plugin does
  (`adapters/hook.py opencode` with the `command` request), not through `/foreman` typed in OpenCode's interface.
- **Where you read it.** OpenCode shows a command's reply as an error notice, which is not made for a long text:
  the reply ends with `Saved: <path>`, the stored record of the review (JSON, in Foreman's state directory,
  `~/.foreman/reviews/` unless OpenCode's plugin storage says otherwise). The whole review is in that file.
- **Limits.** It takes as long as the model takes, up to ten minutes, with nothing shown meanwhile (the plugin gives a
  command ten minutes instead of thirty seconds). OpenCode's JSON output does not name the model that ran, so the
  review names the one you chose; with none chosen it names none. OpenCode has no flag that makes a model answer
  with a given JSON schema: Foreman puts the schema in what it sends and reads the object out of the answer (a
  fenced block or text around it is fine); a reply with no object is a review that could not run. A failed run
  (a model's usage limit, an unknown model) comes back with its reason and the HTTP status when OpenCode gives one;
  a rate limit (429) or a server error (5xx) is retried. The reviewer sees the diff only: it has no tools and no
  repository. A permission rule loaded after Foreman's (OpenCode's managed settings, which an administrator
  controls) could in theory still apply.

## Limits to know

- **The project-level link is for trying it.** It is an untracked file: `git clean -fdx`, `git stash -u` or a
  disguised removal takes it away and Foreman with it (the dialect refuses the plain `rm`/`mv` of `.opencode` or its
  plugin folder, not those), and OpenCode watches its plugin folders, so that may unload Foreman mid-session (not
  seen). A session that moves to a git worktree (`opencode run --worktree`, the model's own `worktree_create` and
  `session_move` tools) lands where OpenCode's configuration search does not find the project's `.opencode`, so its
  commits there are not gated (read in the source, not seen). The user-level link has neither limit.
- **The end-of-turn nudge uses OpenCode's `experimental.idle` hook.** OpenCode marks it experimental. If a later
  version renames or drops it, the plugin still loads and the gate still works, but the nudge stops without notice.
- **Nobody attending means refused.** `opencode run` rejects every permission question, so Foreman's ask is refused
  there. An auto-approve mode answers every question itself within milliseconds: `opencode run --auto` (seen), the
  TUI's autoaccept permissions and the app's auto-approve (read, not seen). Foreman counts a yes that came sooner than
  one second after its question as nobody attending and refuses the call. What this is not: a yes that an automatic
  mode gives late (a question approved when the person switches back to that session, the app's retries) is not
  detected and passes; and in an autoaccept mode a person typing `/foreman allow <id>` is refused too, because that
  yes also arrives in milliseconds (turn autoaccept off to allow a finding). A person who answers in under a second
  is refused and can run the command again.
- **OpenCode's permission prompt shows "Call tool foreman", not Foreman's message** (2.3.2 renders no text for a
  plugin's own question). The model gets the message when the call is refused; `/foreman status` shows the verdict.
- **`/foreman` only works where OpenCode runs commands** (its TUI and apps). `opencode run "/foreman status"` sends
  the text to the model as an ordinary prompt (seen), so Foreman's commands, the review included, do nothing there.
- **When the plugin cannot run Python** (no `python3`, an error, no answer within 30 seconds), the agent keeps
  working: a shell command that names git or gh with commit, push, pr or config goes to you as an ask (refused with
  nobody there), every other call runs, and the error is shown once per session, when the run ends, as a failed
  session hook.
- **Turns.** OpenCode gives a session id (`ses_…`) and an id to each message (`msg_…`), but none to one run of the
  agent. The plugin counts a run from your prompt to a session at rest (its message id); a message you send while
  the agent works, and OpenCode's own input to the agent, do not start a new one. "At rest" is OpenCode's own record
  of the session; after an interruption it does not record (OpenCode leaves some without a reason), your next prompt
  may be taken as mid-run for that one run, so that run keeps the earlier one's notes (read in the source, not seen).
- **The agent's shell starts in the session's directory each time.** A `cd` in one call does not carry to the next,
  and the plugin judges each call in the directory OpenCode runs it in (the `workdir` argument against the session's
  directory).
- The gate runs on the agent's own machine. The independent control is still the required check in CI
  (`examples/foreman-check.yml`). Foreman's plugin file and state are files: the dialect refuses the plain attempts
  to remove or rewrite them (`opencode plugin remove foreman`, `"-foreman"` or `"-*"` written to `opencode.json`,
  deleting Foreman's plugin file, deleting, moving or emptying a plugin folder: the project's `.opencode` and its
  `plugins`, `~/.config/opencode` or `$XDG_CONFIG_HOME/opencode` and its `plugins`; starting a nested OpenCode with
  `OPENCODE_DISABLE_PROJECT_CONFIG` or another configuration), not a disguised one. One other named file in a
  plugin folder (`rm .opencode/plugins/mine.ts`) stays ordinary work, and so does a plain copy over the
  configuration (`cp mine.json opencode.json`), whose content the command does not show. Refused although harmless:
  removing another project's `.opencode` (`rm -rf examples/app/.opencode`), and a command that deletes a `"-*"`
  entry from `opencode.json` (the line still holds the entry): edit the file with the agent's edit tool instead, or
  do it yourself.
- Not seen yet: Windows; OpenCode's background service (all runs above used `--standalone`); OpenCode's desktop and
  web apps.

What it does not do yet: the review when someone asks to merge and on every turn (it runs when you ask), the board,
merge and reject with reasons (Foreman on Hermes Agent has them).
