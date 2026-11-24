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
  adapter on them later, untested); package names and where each is published (to the owner when the first adapter
  works).

## How it is built (PRODUCTO.md rules 22 to 26)
- `plugin/foreman/` is the core and is not edited for an adapter: every Hermes import in it is lazy and guarded, so
  `gate.on_pre_tool_call("terminal", {"command", "workdir"})` and `gate.on_pre_verify(...)` run outside Hermes as they
  are (measured 2026-11-24: 25 ms to import, about 80 ms per gated git command). Outside Hermes its state lives in
  `~/.foreman`.
- `adapters/foreman_hosts/core.py` is the host-neutral half: shell command, write, turn start, end of turn and the
  person's command in; `allow`, `block`, `ask` or `continue` with a message out. Each harness adds a dialect: a
  Python module for the harnesses that run a command hook with JSON on stdin (Claude Code, Codex), a thin TypeScript
  extension that calls `adapters/hook.py neutral` for the ones with a plugin API (pi, OpenCode).
- The repository root is the package each harness installs (`.claude-plugin/` today), so nothing is copied; Hermes
  still installs only `plugin/`.
- A change the core does need (wording such as `/foreman merge`, the reviewer's effort setting) lands on `main` with
  the tests green and waits for the one catalog update.

## What each harness offers (official documentation read on 2026-11-24; "measured" where run here)
- Claude Code 2.1.331, measured: `PreToolUse` deny blocks under `bypassPermissions` and its reason reaches the model;
  `ask` in `-p` is refused with the reason; `Stop` with `decision: block` continues the turn (`stop_hook_active` on the
  next one; Claude Code's own cap is 8); `UserPromptSubmit` with `decision: block` prints the reason with no model
  turn (0 tokens), which is how the person's `/foreman …` works. The payload has `session_id`, `cwd`, `prompt_id`
  (one per turn), `permission_mode`, `effort.level`; no model name. The hook's environment has
  `CLAUDE_CODE_SESSION_ATTENDED` (1 interactive, 0 in `-p`), and so does the agent's own shell in an interactive
  session. Also measured: the interactive prompt rejects an unknown `/foreman` before any hook, while a plugin
  command (`/foreman:status`) fires `UserPromptSubmit` first; the hook's `cwd` follows a `cd` made in an earlier
  Bash call (and Claude Code resets a `cd` out of the project, which the hook's `cwd` reflects); a subagent's tool
  calls carry the session's `session_id` and `prompt_id` plus an `agent_id`; `python3 <missing file>` exits 2,
  which Claude Code reads as "block" (hence `|| exit 1` in `hooks.json`).
- Codex CLI 0.171.0 (read): `PreToolUse` on `Bash` and `apply_patch`, the same field names as Claude Code, `Stop`
  continues with the reason; no `ask` (the call proceeds); a hook runs only after the person trusts it, by hash; its
  documentation calls hooks "not a complete enforcement boundary". Not verified: `codex exec` and the no-approval
  flags. The payload carries `model`.
- pi 1.5.0 (read, local docs): `tool_call` returns `{block, reason}`; `agent_before_settle` returns `continue`;
  `registerCommand` runs code with no model turn; `ctx.ui.select/confirm`, `pi.exec`, `ctx.modelRegistry.complete`
  (model call with the user's credentials and a reasoning level), `ctx.ui.setWidget`. Package
  `@earendil-works/pi-coding-agent`.
- OpenCode 2.3.2 (read; the owner's own plugins use them): `ctx.tool.hook("execute.before")` blocks by throwing,
  `ctx.session.hook("experimental.idle")` continues, `ctx.command` adds a command that runs code, `ctx.permission`,
  `ctx.model`. The idle hook and the model call are marked experimental.
- Headless sessions for the reviewer (flags read in each `--help`): `claude -p --model --effort --json-schema
  --tools ""`; `codex exec -m -c … --output-schema --sandbox`; `pi -p --model <id>:<level> --no-tools`;
  `opencode run -m provider/model#variant --format json`.

## Acceptance criteria
- [x] Claude Code, real session (2026-11-24, 2.1.331, macOS, `bypassPermissions`): an agent's commit that skips a
  test is blocked with the file and line; its `gh pr merge` is blocked; an `Edit` that skips a test is blocked; a
  turn that leaves a skipped test is sent back once and a turn that only talked is not; `/foreman:status`,
  `/foreman:allow` and `/foreman:help` answer the person without a model turn; `allow` does nothing with nobody
  attending and works typed in an interactive session. Not seen yet: Windows; an installation through the
  marketplace (it goes into the owner's own Claude Code: his to try).
- [ ] Codex, pi and OpenCode: the same gate, each seen in a real session.
- [ ] The reviewer in the four: a fresh session launched by Foreman, its model and effort the user's choice, each
  finding verified against the diff.
- [ ] pi and OpenCode: `/foreman` board, verdict, review, merge, reject, allow and pipeline.
- [ ] `plugin/` unchanged by the adapters; `hermes plugins validate plugin` and the tests green throughout.

## Open questions and risks
- The agent can reach the hook's configuration and Foreman's state as files (same debt as Hermes's state guard):
  the adapter blocks what names them, the required check in CI stays the independent control. Agent settles it.
- Claude Code on Windows may lack `python3`. Agent settles it (document, or a launcher).
- The reviewer session loads Foreman's own hooks (recursion): needs a guard; `claude --bare` skips hooks but does
  not read a subscription login. Agent settles it.
- Whether the Hermes catalog's scanner reads outside `subdir`: unknown; nothing binary is committed anywhere.
- Names and distribution (marketplace, npm): the owner, when the first adapter works.

## Tasks
- [x] T1 The neutral half and the Claude Code adapter with the gate and the person's commands; real session
  (pull request #61, reviewed by an agent that did not write it: nothing blocking, its findings fixed).
- [ ] T2 Codex adapter (the same command hook, its dialect); real session, `codex exec` and no-approval modes.
- [ ] T3 pi extension with the gate; real session.
- [ ] T4 OpenCode v2 plugin with the gate; real session.
- [ ] T5 The reviewer as a fresh session, in the four.
- [ ] T6 `/foreman` complete on pi and OpenCode.
- [ ] T7 READMEs, names and publication (owner's yes); the one Hermes catalog update with what the core needed.

## Next step
T2, T3 and T4, one agent each, in parallel: each adds a dialect next to `foreman_hosts/claude_code.py` (pi and
OpenCode: a thin TypeScript extension that calls `adapters/hook.py` with a neutral JSON, plus that dialect in
Python), its tests, and its own real-session run. `core.py` is shared: a change to it is one pull request of its
own, before the three.
