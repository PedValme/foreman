# Foreman for Codex

Not published yet, and not a Codex plugin yet: Codex's plugin manifest could not be tried here without installing
it, so this folder ships only the hooks.

Needs Python 3.9 or newer as `python3`, and git. Outside Hermes, Foreman keeps its state (what waits for you,
each session's turn) in `~/.foreman`.

## Try it from a clone

Nothing is installed and nothing under `~/.codex` changes: the hooks are given for one session on the command line.
From the repository you want to work in:

```
FOREMAN=/path/to/foreman
HOOK="python3 -I $FOREMAN/adapters/hook.py codex || exit 1"
codex --dangerously-bypass-hook-trust \
  -c "hooks.PreToolUse=[{matcher=\"^(Bash|apply_patch|Edit|Write)\$\",hooks=[{type=\"command\",command=\"$HOOK\",timeout=30}]}]" \
  -c "hooks.UserPromptSubmit=[{hooks=[{type=\"command\",command=\"$HOOK\",timeout=600}]}]" \
  -c "hooks.Stop=[{hooks=[{type=\"command\",command=\"$HOOK\",timeout=600}]}]"
```

The same flags work with `codex exec`. `--dangerously-bypass-hook-trust` is there because Codex runs a hook only
after you trust it, by its hash, and a hook given with `-c` has no stored trust. The path must have no spaces.

To keep it, put `hooks.json` from this folder in `~/.codex/` (every repository) or in a trusted project's `.codex/`
(next to a `config.toml`, which Codex requires), with `/path/to/foreman` replaced, and trust the hooks once with
`/hooks` in Codex. If that file already has hooks, add Foreman's entries to them.

Use a clone you are not working in: Foreman keeps the agent out of its own code (`adapters/`, `plugin/`,
`.claude-plugin/` of the clone it runs from).

## What it does

Seen in real `codex exec` sessions on Codex CLI 0.171.0 (macOS), in `--dangerously-bypass-approvals-and-sandbox` and
in `-s workspace-write`:

- **Before the agent's shell command.** `git commit`, `git push` and `gh pr create` are inspected (the real diff, not
  the command text) and refused with the file and line when the change skips, deletes or moves tests, edits what the
  check runs, bypasses hooks or carries a secret. An agent-run `gh pr merge` is always refused.
  The command is inspected where it runs: when the model gives the shell tool a working directory, Codex 0.171.0
  hands the hook that directory as its `cwd` and no `workdir` in the tool's input (measured); a `workdir` that does
  come in the input is used instead.
- **Before a patch.** An `apply_patch` that switches off a test is refused.
- **Before the agent finishes.** A turn in which the agent changed the working tree and left one of those in it is
  sent back once with what to undo. A turn that only talked is never sent back.
- **Your commands**, typed as a prompt and answered by the hook with no model turn: `foreman`,
  `foreman status [path]`, `foreman allow`, `foreman help`, and the review's (below): `foreman review [target]
  [--fresh]`, `foreman reviewer` (shows who reviews). A prompt that is exactly one of these lines (a leading
  `/` is accepted) is taken as a command; any other prompt, `foreman status looks wrong, why?` included, goes to the
  model. They are plain words, not `/foreman`, because Codex's interactive prompt refuses a slash command it does not
  know before any hook runs (read in Codex's program, not seen).
- **Allowing a finding (`foreman allow <id>`) is not available in Codex yet.** Codex tells a hook nothing shown to
  separate your own prompt in an interactive session from a prompt the agent writes for a subagent, or from a
  session resumed with `codex exec resume`, and allowing must stay out of the agent's reach. `foreman allow` still
  lists what waits; to get past a marked finding, fix it, or commit the change yourself in your own terminal.

Codex has no way for a hook to ask you. When Foreman would ask (it could not inspect a command, or the working
directory does not exist), the call is refused with the reason; run it yourself if you have checked the change.

The review at the end of every turn is off unless you turn it on, in Foreman's `config.json` like the reviewer
itself (`{"each_turn": {"codex": true}}`; `foreman reviewer` shows whether it is on): then a turn that changed code
and passed the gate is reviewed before it ends, and a verified BLOCKING or HIGH finding sends the agent back with
it. The `Stop` hook waits up to ten minutes for it. Run in the tests, not seen in a session.

What it does not do: the board, merge and reject with reasons (Foreman on Hermes Agent and on pi have them).

## The review

`foreman review [pull request|branch] [--fresh]`, typed as a prompt like your other commands, has Foreman start a
fresh `codex exec` session that did not write the code. It reads the diff and answers one JSON object; Foreman checks
that every finding quotes a line of the diff, prints a verdict (PASS, CONCERNS or BLOCK), and keeps the result. The
same diff by the same reviewer is never sent twice (`--fresh` asks again). It is advice: it grants, merges and
unblocks nothing, and Foreman's own gate decides what it decides without it.

The session is `codex exec --ephemeral --ignore-user-config --sandbox read-only`, started by Foreman in an empty
temporary directory, with the diff on standard input and Foreman's fixed rules as its instructions
(`-c model_instructions_file=<file>`; the diff never goes in that file). Codex's read-only sandbox blocks writes and
the network, not reads, so what the session can reach is decided by its tools. Foreman switches off what Codex lets it
(`--disable shell_tool unified_exec view_image apps plugins image_generation multi_agent multi_agent_v2` and
`-c web_search="disabled"`); the names were checked to exist on 0.171.0.

What was found, by `codex debug prompt-input` with an empty Codex home (it calls no model): by default Codex declares a
JavaScript `exec` tool whose nested tools include `exec_command`, `write_stdin`, `view_image`, `apply_patch` and the
MCP resource tools; with the switches above `exec_command`, `write_stdin` and `view_image` are gone from that list.
Still declared: `apply_patch` (it writes, and the read-only sandbox is what stops it; not tried), the MCP resource
readers (with `--ignore-user-config` and an empty directory no MCP server is configured, so they have nothing to
read), a clock, `request_user_input` and the sub-agent tools (the last two have no one to ask, and there is no
switch for them that took effect in that list). Not shown by that command, so not verified: the web search tool and
anything the login adds (apps, connectors); they are switched off by the flags above but a real session's tool list
was not read. Measured with a real session, before the extra switches: with the shell on, a session asked to read a
file outside its directory did; with the first three off it said it had no tool to do so.
Codex's login is the one you already have.

Who started it is not fully known. `foreman review` is a prompt, and nothing Codex tells its hooks was shown to
separate your own prompt from one the agent writes for a subagent, so a review the agent asked for in that way
cannot be told from yours. What it can do is small: it costs a model call and shows a verdict, which is advice.

**Who reviews** is shown by `foreman reviewer`. Setting it is not available from a Codex prompt, for the reason
`foreman allow <id>` is not: a choice saved by an agent's prompt would be reported by every later review as yours.
You set it yourself in `config.json` in Foreman's state directory (`~/.foreman/config.json`), in this shape (either
field may be left out):

```
{"reviewer": {"codex": {"model": "gpt-6-luna", "effort": "medium"}}}
```

With nothing chosen it is the model this session runs on (the hook input names it), in a clean context and no more:
not another model, and the review says so in plain words. For an independent look, choose another. Effort levels,
lowest first, are the ones in Codex 0.171.0's own model catalog (`codex debug models --bundled`): `low`, `medium`,
`high`, `xhigh`, `max`, `ultra`. Not every model takes every level (the catalog gives `gpt-5.5` up to `xhigh`);
Codex refuses one the model lacks and the review says why.

Seen on Codex CLI 0.171.0 (macOS) with `gpt-6-luna` at `low`, in a throwaway repository: an `assertEqual` loosened to
`assertTrue` came back as BLOCKED, with the new line quoted as evidence. The second `foreman review` printed the
stored result and called no model. A review took about 8 seconds.

Limits in Codex:

- **`codex exec` shows nothing of a blocked prompt's reason**, and a review is a blocked prompt. In `codex exec` the
  review runs, but you read it only in the file it saves (`~/.foreman/reviews/`, the path is the last line of the
  result), not on screen. Use the interactive terminal. Not seen: the interactive terminal and the desktop app.
- **The session's effort is not known.** Codex's hook input names the session's model (`model`) and no effort, so the
  default reviewer is not raised a level above the session as it is in Claude Code, and the review says so.
- **Codex does not say which model answered**, so the review names the one you chose, or none.
- **The reviewer is not fully clean.** `--ignore-user-config` skips your `config.toml`, but Codex still loads your
  global instructions file from its home, and the reviewer sees it. Every review in Codex says so under its
  "Reviewer:" line, with the tools that could not be switched off.
  Neither `-c project_doc_max_bytes=0` (it only silenced the warning) nor `-c model_instructions_file=` (the warning
  and the global file stayed) removed it. The file is not Foreman's, and the session has no tool to act on it.
- **It takes as long as the model takes**, up to 7 minutes (retries included) with nothing shown meanwhile; the hook's
  timeout above is 600 seconds for that. A rate limit (429) or a server error (5xx) is retried by the review.

## Limits to know

- **In `codex exec`, Codex does not print a blocked prompt's reason.** `foreman status` there is answered and the
  model never runs, but you see only `hook: UserPromptSubmit Blocked`. Use the interactive terminal for your
  commands. Not seen yet: the commands in the interactive terminal and the desktop app (trying them needs a folder
  Codex trusts, and trusting one writes to `~/.codex`).
- **A command typed into a running interactive shell skips the gate.** Codex's documentation says `write_stdin` (the
  agent typing into a shell it started with a terminal) does not run `PreToolUse` again. Not tried here: the models
  asked to do it declined. The commit gate in CI still sees what it commits.
- **Subagents are not verified**: whether a subagent's prompt fires `UserPromptSubmit`, and what its hooks receive,
  was not tried.
- The gate runs on the agent's own machine. The independent control is still the required check in CI
  (`examples/foreman-check.yml`). Codex's own documentation calls hooks "a useful guardrail, not a complete
  enforcement boundary".
- Foreman's hooks and state are files. The adapter refuses what names them (its installation, `~/.foreman`, Codex's
  `config.toml`, `hooks.json` or `requirements.toml` rewritten to switch hooks off or drop Foreman's,
  `codex features disable hooks`, its entry point run by hand), which stops the plain attempt, not a disguised one.
- When the hook cannot run at all (no `python3` on the PATH, a Python older than 3.9, a damaged installation), it
  fails as any hook error does: Codex reports it and goes on without the gate (`|| exit 1` keeps it from being read
  as a refusal of every call). When the hook runs and cannot inspect a commit, push or pull request, the call is
  refused.
