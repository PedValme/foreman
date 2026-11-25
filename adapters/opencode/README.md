# Foreman for OpenCode

Not published yet. A plugin for OpenCode's v2 plugin API, seen working on OpenCode 2.3.2 on macOS, in two parts:

- **The server part** (`foreman.ts`; `server.ts` is the same code for the folder install): it runs inside OpenCode's
  server. The gate (the agent's shell commands and writes, the end of a turn) and `/foreman` as a server command,
  which the apps, the HTTP API, the SDK and a TUI without the TUI part reach.
- **The TUI part** (`tui.ts`): it runs inside OpenCode's terminal interface. `/foreman` typed at the TUI's prompt,
  with every reply in a dialog, a question in the TUI's select dialog, and `merge`, `reject` and `allow` for the
  person who typed them.

Both are thin: for each thing OpenCode tells them, they run `python3 -I <this clone>/adapters/hook.py opencode` with
one request (`../foreman_hosts/neutral.py`) and do what the answer says. OpenCode's own words for Foreman live in
`../foreman_hosts/opencode.py`.

Needs Python 3.9 or newer as `python3` on the PATH OpenCode runs with, and git. No npm package, no build step.

## Install it

Use a clone you are not working in (Foreman keeps the agent out of the clone's `adapters/` and `plugin/`). There are
two forms; use one of them, not both (both load the server part twice under one id).

**The folder (both parts; the one to use).** OpenCode's TUI loads a plugin's TUI part only from a folder in a
`plugins` folder (it takes `tui.ts` from it, and OpenCode's server takes `server.ts`), so link the clone's
`adapters/opencode` folder under the name `foreman`. For your user, covering every project and every worktree a
session moves to:

```
mkdir -p ~/.config/opencode/plugins
ln -s /path/to/foreman/adapters/opencode ~/.config/opencode/plugins/foreman
```

For one project:

```
mkdir -p .opencode/plugins
ln -s /path/to/foreman/adapters/opencode .opencode/plugins/foreman
opencode
```

**The file (the server part only).** The form earlier versions described, and it keeps working: the gate and the
server command, but no TUI part, so `/foreman` replies as an error notice and `merge` and `reject` answer "nobody is
attending" everywhere.

```
ln -s /path/to/foreman/adapters/opencode/foreman.ts ~/.config/opencode/plugins/foreman.ts   # your user
ln -s /path/to/foreman/adapters/opencode/foreman.ts .opencode/plugins/foreman.ts            # one project
```

To move from the file to the folder, remove the file's link first. With `XDG_CONFIG_HOME` set, OpenCode's user
folder is `$XDG_CONFIG_HOME/opencode` instead: link into `$XDG_CONFIG_HOME/opencode/plugins`. The user forms were read
in OpenCode's source (2.3.2), not seen running: the trials below never wrote to a user's OpenCode configuration. The
plugin finds `hook.py` through the link, next to its real files.

**To try it from a clone without touching your own configuration**, use the project form in a throwaway git
repository, linking a copy of the clone you are not editing, and add to that repository's `opencode.json`:

```
{ "plugins": ["-*", "opencode.*", "foreman"] }
```

(`-*` turns every server plugin off, `opencode.*` turns OpenCode's built-in ones back on, `foreman` this one.) It
does not keep everything of yours out: MCP servers from your global configuration still load, and so does a TUI
plugin you installed for your user, because the TUI reads its own plugin list (seen: a user-level TUI plugin loaded
in a trial with this `opencode.json`). Remove what a trial leaves in `~/.foreman` if it was not there before.

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
- **Your command through the server part** (the apps, the HTTP API, the SDK, a TUI without the TUI part):
  `/foreman` (the board), `verdict`, `pipeline`, `prs`, `issues`, `use`, `status [path]`, `allow [id]`, `review`,
  `reviewer`, `help`: code, no model turn. A server command answers only through an error notice, so the reply
  appears as one (on a new session its title reads "Failed to set up session"; the text is Foreman's). A server
  command cannot tell who sent it, so it never counts as a person there, with one exception: `/foreman allow <id>`
  first asks you through OpenCode's permission prompt, and the finding is allowed only when that is approved (seen in
  the TUI before the TUI part existed: approve allowed it, reject did not). `use` prints the list and what to type,
  and `merge` and `reject` answer "nobody is attending" (seen in the TUI with the file install: `/foreman merge 7`).

## Your command in the TUI (the TUI part)

With the folder install, `/foreman …` typed at the prompt of OpenCode's terminal interface runs in the TUI part, not
the server command. OpenCode's TUI runs a TUI plugin's slash command before it looks for a server command of that
name (both are listed when you type `/foreman`; the TUI part's runs), in the TUI process and only for what was typed
at that prompt. The model's tools run in OpenCode's server, and OpenCode 2.3.2 gives them no way to type into the
TUI (its TUI listens for "append to the prompt" and "run a command" events that nothing in 2.3.2's server sends; read
in the source, to check again on each OpenCode upgrade). No auto-approve mode answers its dialogs, which are not
permission requests (`--auto`, the TUI's "auto accept" and the app's auto-approve answer permission requests only).
So the TUI part counts as a person there; what that does not cover is under "Limits to know" (keys typed into the
terminal, a plugin the agent plants):

- **Every reply in a dialog**, wide and centred, closed with Enter or Escape: the board, verdicts, the pipeline,
  status, help, a review. Not an error notice, and nothing that enters the model's context. Seen: the demo
  repository's board, eight open pull requests and the pipeline, in one dialog on a 50-line terminal. A reply longer
  than the terminal is cut at its bottom edge (the dialog does not scroll); a review ends with `Saved: <path>`, where
  the whole of it is.
- **A question in the select dialog** (which repository for `use`, confirm a merge, close a pull request): the
  command runs again with your pick, at most three questions for one command; closing the dialog with Escape is no
  pick. Seen: `use` with two repositories, picked and pinned; the same dialog stayed open in a TUI started with
  `--auto`.
- **Merge and reject**: `/foreman merge <pr>` and `/foreman reject <pr> [--close] [note]`, as on pi (see
  `../README.md`): the review first, then your confirmation in the select dialog, then exactly `gh pr merge <pr>
  --squash --delete-branch --match-head-commit <the commit inspected>`. Seen on the demo repository: `/foreman reject
  3 --close` asked "Post the comment and close PR #3?" with its three options, and Escape posted nothing; `/foreman
  merge 3` refused a BLOCKED pull request before any review; `/foreman merge 21`, on a throwaway pull request,
  started the review (an OpenCode session of its own; about a minute with only the "Foreman is working" notice),
  asked "Merge PR #21 of PedValme/foreman-demo (8ef72a5, squash) into main?" in the select dialog and, on Merge,
  merged it by squash and showed the review's verdict and who reviewed. Only tested, not seen: a rejection carried
  out (no comment was posted from OpenCode), with a fake `gh`.
- **Allow**: `/foreman allow <id>` asks you to confirm that finding's id in a dialog first; only tested, not seen.
- **On the home screen** (no session open), a repository pinned with `use` is kept for that TUI's run only, not for
  a session (tested).
- **The prompt stays yours while Foreman works**: the command returns at once and its dialogs come when they are
  ready; an answer slower than a second and a half shows a notice that Foreman is working (a review takes minutes).
  When the Python side cannot run, the dialog says why (both tested).
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
- **What it runs**: `opencode run --standalone --archived --format json --agent foreman-reviewer-<random> [-m
  <model>]`, the prompt on standard input (never on the command line), in an empty temporary directory, so it reads
  neither the repository nor its project settings. It is a private server (`--standalone`) so that the configuration
  below reaches it, and it is never started with `--auto`. `--archived` keeps its session out of your session lists;
  OpenCode still stores it, the diff included, in its own database.
- **It cannot change anything.** OpenCode applies the last matching permission rule, and the rules in your own
  `agents.build` come after the top-level ones, so a top-level "deny everything" alone would not be total. Foreman
  passes, in `OPENCODE_CONFIG_CONTENT` (read after your configuration files), an agent of its own under a name nobody
  else's configuration knows, whose own rules deny every permission and come last in its list, runs the session as
  that agent, and turns off every plugin but OpenCode's built-in ones. `OPENCODE_DISABLE_CLAUDE_CODE=1` leaves your
  Claude Code instructions out; the token of this review in `FOREMAN_REVIEWER` makes Foreman's own hook (`hook.py`)
  answer nothing inside that session. Seen: told to create a file and run `ls`, the session answered that it has no
  tools, and the file did not exist. What can still undo it: OpenCode's managed settings (an administrator's) load
  after Foreman's.
- **What of your OpenCode setup still reaches it**: your global configuration directory still applies. Its MCP
  servers start (their tools are denied, the servers still run), its global `AGENTS.md` still reaches the model
  (OpenCode has no setting to leave it out), and your plugin modules are imported before `-*` turns them off. Foreman
  cannot close these from the configuration it passes; each review says so in one line under its "Reviewer:" line.
- **Who reviews by default**: the model this session runs on, when OpenCode's record of the session names it (the
  plugin sends it), in a clean context and with nothing raised: OpenCode has no effort to raise. With no model in the
  record it is OpenCode's default model. Either way it is the model that wrote the code: choose another to get a
  second opinion. Each review says who it was.
- **Seen** (OpenCode 2.3.2, macOS, an OpenCode Go model, a throwaway copy of `examples/cart`): an assertion loosened
  from an exact value to "is true", which the gate cannot see (CLEAN), came back BLOCKED with the line quoted. The same
  diff again was answered from the stored result without a call. The Python side was called as the plugin does
  (`adapters/hook.py opencode` with the `command` request), not through `/foreman` typed in OpenCode's interface.
- **Where you read it.** OpenCode shows a command's reply as an error notice, which is not made for a long text:
  the reply ends with `Saved: <path>`, the stored record of the review (JSON, in Foreman's state directory,
  `~/.foreman/reviews/` unless OpenCode's plugin storage says otherwise). The whole review is in that file.
- **Limits.** It takes as long as the model takes, up to ten minutes, with nothing shown meanwhile (the plugin gives a
  command ten minutes instead of thirty seconds). OpenCode's JSON output never names the model that ran, so the
  review does not say which one answered. OpenCode has no flag that makes a model answer with a given JSON schema:
  Foreman puts the schema in what it sends, with a random seal that the diff's author cannot know, and reads only the
  object that carries the seal (a fenced block or text around it is fine; an object written inside the diff is
  never taken for the answer); a reply with no sealed object is a review that could not run. A failed run (a
  model's usage limit, an unknown model) comes back with its reason and the HTTP status when OpenCode gives one; a
  rate limit (429) or a server error (5xx) is retried. The reviewer sees the diff and your global instructions: it has
  no tools and no repository. Foreman's rules for it are the agent's own system text, apart from the diff.

## Limits to know

- **The project-level link is for trying it.** It is an untracked file: `git clean -fdx`, `git stash -u` or a
  disguised removal takes it away and Foreman with it (the dialect refuses the plain `rm`/`mv` of `.opencode` or its
  plugin folder, not those), and OpenCode watches its plugin folders, so that may unload Foreman mid-session (not
  seen). A session that moves to a git worktree (`opencode run --worktree`, the model's own `worktree_create` and
  `session_move` tools) lands where OpenCode's configuration search does not find the project's `.opencode`, so its
  commits there are not gated (read in the source, not seen). The user-level link has neither limit.
- **The end-of-turn nudge uses OpenCode's `experimental.idle` hook.** OpenCode marks it experimental. If a later
  version renames or drops it, the plugin still loads and the gate still works, but the nudge stops without notice.
- **Nobody attending means refused, on the server part.** `opencode run` rejects every permission question, so
  Foreman's ask is refused there. An auto-approve mode answers every question itself within milliseconds: `opencode
  run --auto` (seen), the TUI's autoaccept permissions and the app's auto-approve (read, not seen). Foreman counts a
  yes that came sooner than one second after its question as nobody attending and refuses the call. What this is
  not: a yes that an automatic mode gives late (the TUI's autoaccept answers a session's requests only while that
  session is open, so a question approved when the person switches back to it; the app's retries) is not detected and
  passes; and in an autoaccept mode a person approving `/foreman allow <id>` through the server command is refused
  too, because that yes also arrives in milliseconds. In the TUI with the TUI part, `allow` does not use this prompt.
  A person who answers in under a second is refused and can run the command again.
- **Keys typed into the terminal by another program** (read, not seen). The TUI part trusts what reaches the TUI's
  prompt and its dialogs. A program that types into the terminal the TUI runs in (`tmux send-keys` into its pane,
  a macOS script that sends keystrokes) looks to the TUI like a person, and the agent's own shell can run such a
  program. Foreman does not guard against it; keep the agent's shell away from the terminal multiplexer the TUI runs
  in.
- **A plugin the agent plants** (read, not seen). OpenCode loads and reloads every plugin in a project's
  `.opencode/plugins`, server and TUI parts alike, and the agent's `write` tool can create one there (another
  plugin's file stays ordinary work for Foreman, as before). Such code runs with OpenCode's powers outside the gate:
  it could call the TUI part's code with answers of its own, or simply run `gh` itself, without Foreman. This was so
  before the TUI part (a planted server plugin could do the same); the required check in CI stays the independent
  control.
- **The desktop and web apps are not covered by the TUI part** (read, not seen). OpenCode's desktop app has its own
  plugin kind, not used here, so there `/foreman` is the server command: merge and reject answer "nobody is
  attending", and allowing a finding goes through the permission prompt.
- **With OpenCode's background service, the agent's shell can reach the server** (read in the source, not seen).
  Without `--standalone`, OpenCode runs a background service whose password is kept in a file of the user's, and
  `opencode api` (OpenCode's own command for HTTP requests to it) reads it. From the agent's shell that can answer a
  permission question (Foreman's `/foreman allow <id>` prompt through the server part included) or run the server
  command. Merge and reject are not reachable that way (the server command never counts as a person), and a typed
  `opencode run '/foreman …'` is refused, but `allow` through the server part is weaker there than it looks. The TUI
  part's `allow` does not go through the server.
- **OpenCode's permission prompt shows "Call tool foreman", not Foreman's message** (2.3.2 renders no text for a
  plugin's own question). The model gets the message when the call is refused; `/foreman status` shows the verdict.
- **`/foreman` only works where OpenCode runs commands** (its TUI and apps). `opencode run "/foreman status"` sends
  the text to the model as an ordinary prompt (seen), so Foreman's commands, the review included, do nothing there;
  the agent's `opencode run '/foreman merge 7'` is refused anyway.
- **Two `/foreman` in the TUI's list.** With the folder install, typing `/foreman` lists the server command and the
  TUI part's command under one name (seen); whichever you pick, the TUI part runs.
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
  (`examples/foreman-check.yml`). Foreman's plugin files and state are files: the dialect refuses the plain attempts
  to remove or rewrite them (`opencode plugin remove foreman`, `"-foreman"` or `"-*"` written to `opencode.json` or
  to the TUI's own `~/.config/opencode/cli.json`, deleting Foreman's plugin file or folder or a file in that folder,
  deleting, moving or emptying a plugin folder: the project's `.opencode` and its
  `plugins`, `~/.config/opencode` or `$XDG_CONFIG_HOME/opencode` and its `plugins`; starting a nested OpenCode with
  `OPENCODE_DISABLE_PROJECT_CONFIG` or another configuration), not a disguised one. One other named file in a
  plugin folder (`rm .opencode/plugins/mine.ts`) stays ordinary work, and so does a plain copy over the
  configuration (`cp mine.json opencode.json`), whose content the command does not show. Refused although harmless:
  removing another project's `.opencode` (`rm -rf examples/app/.opencode`), and a command that deletes a `"-*"`
  entry from `opencode.json` (the line still holds the entry): edit the file with the agent's edit tool instead, or
  do it yourself.
- Not seen yet: Windows; OpenCode's background service (all runs above used `--standalone`); OpenCode's desktop and
  web apps.

What it does not do yet: the review on every turn (it runs when you ask, and before a merge).
