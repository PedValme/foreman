# Foreman for any harness

> Exists while the feature is in progress. On closing: durable rules go to PRODUCTO.md or DECISIONES.md and this file is deleted. Evidence goes in commits, not here.

## Goal
A developer who uses Claude Code, Codex, pi or OpenCode gets Foreman's gate, and on pi and OpenCode the whole line,
from the same core the Hermes plugin runs.

## Why
The owner's decisions of 2026-11-24 (DECISIONES.md): the four harnesses in one campaign, the reviewer as a fresh
session that did not write the code, the Hermes plugin untouched until one substantial catalog update.

## Scope
- Includes: an adapter per harness under `adapters/`; the gate (before `git commit`, `git push`, `gh pr create`,
  `gh pr merge`, before a write that switches off a test, and at the end of a coding turn); the person's commands;
  the reviewer in the four; `/foreman` complete on pi and OpenCode v2.
- Excludes: phone notifications and the Desktop panel (Hermes-only); OpenCode's v1 plugin API; Gemini CLI (Google is
  moving it to Antigravity CLI, another format), Cursor and Copilot (both read Claude Code's hooks: try the Claude
  adapter on them later, untested); package names and where each is published (the owner's, T7).

## How it is built (PRODUCTO.md rules 22 to 26; `adapters/README.md` says what each file is)
- `plugin/foreman/` is the core and is not edited for an adapter: every Hermes import in it is lazy and guarded, so
  `gate.on_pre_tool_call` and `gate.on_pre_verify` run outside Hermes as they are. Outside Hermes its state lives in
  `~/.foreman`.
- `adapters/foreman_hosts/core.py` is the host-neutral half; `hosts.py` lists the harnesses; a harness that runs a
  command hook with JSON has a Python dialect (`claude_code.py`, `codex.py`); one whose extension is code has a thin
  TypeScript extension that speaks `neutral.py`'s protocol to `adapters/hook.py`, plus its Python dialect (`pi.py`,
  `opencode.py`). `neutral.py`'s docstring pins what every extension must do alike.
- The repository root is the package a harness installs (`.claude-plugin/` today); Hermes installs only `plugin/`.
- A change the core does need (wording such as `/foreman merge`, the reviewer's effort setting) lands on `main` with
  the tests green and waits for the one catalog update. None was needed so far.

## What each harness gives (measured in real sessions on 2026-11-24 unless marked "read")
- **Claude Code 2.1.331.** `PreToolUse` deny holds under `bypassPermissions` and its reason reaches the model;
  `ask` in `-p` is refused; `Stop` continues the turn; `UserPromptSubmit` that blocks prints its reason with no model
  turn, and fires for a plugin command (`/foreman:status`) before the model sees it, while the interactive prompt
  rejects an unknown `/foreman`. Payload: `session_id`, `cwd` (follows a `cd` made in an earlier call), `prompt_id`
  (one per turn, shared by a subagent's calls). `CLAUDE_CODE_SESSION_ATTENDED` is 1 interactive and 0 with `-p`, and
  the agent's own shell inherits it. `python3 <missing file>` exits 2, which Claude Code reads as "block".
- **Codex CLI 0.171.0.** Hooks fire under `codex exec`, with `--dangerously-bypass-approvals-and-sandbox` and with
  `-s workspace-write` (`--full-auto` does not exist). Payload: `session_id`, `turn_id`, `transcript_path`, `cwd`
  (where the command runs: a working directory the model gives arrives as `cwd`, not in `tool_input`), `model`,
  `permission_mode`; `tool_input.command` holds the patch text for `apply_patch`. No `ask`. A blocked
  `UserPromptSubmit` runs no model turn, but `codex exec` prints nothing of its reason. Hooks can be given for one
  run with `-c hooks.…=[…]` and `--dangerously-bypass-hook-trust`. Read, not seen: the interactive prompt rejects
  an unknown slash command; `write_stdin` into a running shell skips `PreToolUse`; subagent hooks use the parent's
  session id.
- **pi 1.5.0.** Handlers fire in print mode (`hasUI` false; true in the terminal UI and in RPC mode). The session id
  is `ctx.sessionManager.getSessionId()`; there is no id for one run of the agent. Each `bash` call runs in the
  session's directory. A continuation from `agent_before_settle` returns to `agent_start` without firing
  `before_agent_start`. A `tool_call` handler that throws blocks that call. pi's tools drop a leading `@` and expand
  `~` in a path. `pi -e <file>` loads an extension for one run; `-ne` leaves the others out.
- **OpenCode 2.3.2.** Plugin hooks fire under `opencode run` and `run --auto`. A plugin command's `execute` is code
  with no model turn, but it can answer only through an error notice; `opencode run "/foreman …"` sends the text to
  the model. Plain `run` rejects every permission question and `--auto` approves in about 4 ms. Ids: `ses_…` and one
  `msg_…` per message, none for a run. Each shell call starts in the session's directory unless `workdir` is given.
  A plugin cannot show a notice to the person. There is no `--pure`: a project `opencode.json` with
  `{"plugins": ["-*", "opencode.*", "foreman"]}` leaves the user's global plugins out (global MCP servers still
  load). Read, not seen: the user-level plugins folder; a session moved to a worktree leaves a project-level plugin
  behind; the TUI's autoaccept and the app's auto-approve.
- Headless sessions for the reviewer (flags read in each `--help`): `claude -p --model --effort --json-schema
  --tools ""`; `codex exec -m -c … --output-schema --sandbox`; `pi -p --model <id>:<level> --no-tools`;
  `opencode run -m provider/model#variant --format json`.

## Acceptance criteria
- [x] Claude Code, Codex, pi and OpenCode, each in real sessions on macOS: an agent's commit that skips a test is
  refused with the file and line; its `gh pr merge` is refused; a write that skips a test is refused; a turn that
  leaves a skipped test is sent back once and a turn that only talked is not; the person's commands answer without
  a model turn; allowing a finding does nothing with nobody attending. Each harness's README lists what was seen
  and what was not (Windows nowhere; the person's commands in Codex's interactive terminal; a marketplace or
  package installation of any of them).
- [ ] The reviewer in the four: a fresh session launched by Foreman, its model and effort the user's choice, each
  finding verified against the diff.
- [ ] pi and OpenCode: `/foreman` board, verdict, review, merge, reject, allow and pipeline.
- [x] `plugin/` unchanged by the adapters; `hermes plugins validate plugin` and the tests green throughout.

## Open questions and risks
- Allowing a finding in Codex is not available: nothing shown separates the person's own prompt from one the agent
  writes for a subagent or from a resumed session. Settling it needs an interactive Codex session in a folder Codex
  trusts, which writes to the owner's `~/.codex`: the owner's to try, or to allow.
- OpenCode decides "a person approved" by a permission prompt and time (a yes within a second is nobody); a late
  automatic yes is not detected. Its end-of-turn nudge depends on a hook OpenCode marks experimental.
- In every harness the hooks and Foreman's state are files (same debt as Hermes's state guard), and a second agent
  started without Foreman (`pi -ne`, a harness run with its hooks off) is outside the gate: CI stays the control.
- T5: the reviewer session loads Foreman's own hooks (recursion): needs a guard; `claude --bare` skips hooks but
  does not read a subscription login. T6 on OpenCode: a command can answer only through an error notice, so the
  board needs another surface there.
- Whether the Hermes catalog's scanner reads outside `subdir`: unknown; nothing binary is committed anywhere.
- Names and distribution (marketplace, npm, how Codex's hooks are installed): the owner, T7.

## Tasks
- [x] T1 The neutral half and the Claude Code adapter (pull request #61).
- [x] T2 Codex adapter (#64), on the shared base (#62).
- [x] T3 pi extension (#63).
- [x] T4 OpenCode v2 plugin (#65).
- [ ] T5 The reviewer as a fresh session, in the four.
- [ ] T6 `/foreman` complete on pi and OpenCode.
- [ ] T7 READMEs, names and publication (owner's yes); the one Hermes catalog update with what the core needed.

## Next step
T5. Start in `core.py`: a host-neutral "review this diff in a fresh session" that each dialect implements with its
harness's headless command (the flags above), reusing `plugin/foreman/review.py` through the context it already
takes (`review.bind(ctx)`: a stand-in with `llm.complete_structured`), so nothing under `plugin/` changes. Decide
the recursion guard first.
