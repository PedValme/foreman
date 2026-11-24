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
  -c "hooks.UserPromptSubmit=[{hooks=[{type=\"command\",command=\"$HOOK\",timeout=70}]}]" \
  -c "hooks.Stop=[{hooks=[{type=\"command\",command=\"$HOOK\",timeout=30}]}]"
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
  `foreman status [path]`, `foreman allow`, `foreman help`. A prompt that is exactly one of these lines (a leading
  `/` is accepted) is taken as a command; any other prompt, `foreman status looks wrong, why?` included, goes to the
  model. They are plain words, not `/foreman`, because Codex's interactive prompt refuses a slash command it does not
  know before any hook runs (read in Codex's program, not seen).
- **Allowing a finding (`foreman allow <id>`) is not available in Codex yet.** Codex tells a hook nothing shown to
  separate your own prompt in an interactive session from a prompt the agent writes for a subagent, or from a
  session resumed with `codex exec resume`, and allowing must stay out of the agent's reach. `foreman allow` still
  lists what waits; to get past a marked finding, fix it, or commit the change yourself in your own terminal.

Codex has no way for a hook to ask you. When Foreman would ask (it could not inspect a command, or the working
directory does not exist), the call is refused with the reason; run it yourself if you have checked the change.

What it does not do yet: the second-model review, the board, merge and reject with reasons (Foreman on Hermes Agent
has them).

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
