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
- The board outside Hermes is `plugin/foreman/board.py` as it is, on a stand-in for Hermes's context
  (`foreman_hosts/standin.py`). Foreman's program answers one request and ends, so a question to the person is an
  answer (`question`): the extension asks in the harness's own dialog and sends the command again with the pick,
  which counts only for the same question (`neutral.py`). Hermes's terminal tool is Foreman's own `gh` there, only
  for `gh pr merge`, `comment` and `close`, only attended. What only the host knows the core asks its
  context for, by names Hermes's own context does not have (since the catalog update of 2026-11-25; until then
  the stand-in wrapped three functions of the core): who reviewed before a merge, in the host's words
  (`foreman_review_before_merge`); the name that signs the reject comment (`foreman_host_label`); and who
  reviewed, added to a review's record before it is stored (`foreman_finish_review`).
- The review at the end of every turn is the core's own `finish` loop (`plugin/foreman/finish.py`): Foreman calls
  what in Hermes is the agent's `foreman_review` tool, then the gate's end of turn reads the stored review
  (`reviewer.turn_end`). Only where `Host.turn_review` says the end-of-turn hook waits minutes.

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
- The reviewer's session in each (measured; the exact command lines are in each harness's README): Claude Code
  `claude -p --json-schema … --tools "" --strict-mcp-config --setting-sources local` in an empty directory carries
  about 1,300 tokens of context and one tool, the structured answer; it tells no hook the session's model, and its
  effort only on tool and stop events. Codex `codex exec --sandbox read-only` reads any file unless its shell tools
  are switched off (`--disable shell_tool unified_exec view_image …`, seen with a marker file); its API needs a
  closed schema; its global instructions file loads whatever is passed; its output never names the model. pi and
  OpenCode cannot hold a model to a schema: the answer is the one object carrying a per-request seal
  (`reviewer.sealed`). OpenCode needs `--standalone`, `PWD` set to the empty directory and a dedicated agent with
  deny-all permissions in `OPENCODE_CONFIG_CONTENT` (a person's own agent rules outrank top-level ones); its free
  models hit their usage limit.

## Acceptance criteria
- [x] Claude Code, Codex, pi and OpenCode, each in real sessions on macOS: an agent's commit that skips a test is
  refused with the file and line; its `gh pr merge` is refused; a write that skips a test is refused; a turn that
  leaves a skipped test is sent back once and a turn that only talked is not; the person's commands answer without
  a model turn; allowing a finding does nothing with nobody attending. Each harness's README lists what was seen
  and what was not (Windows nowhere; the person's commands in Codex's interactive terminal; a marketplace or
  package installation of any of them).
- [x] The reviewer in the four, when the person asks: a fresh session launched by Foreman, its model and effort the
  user's choice, each finding verified against the diff; seen in a real session in each (a loosened assertion the
  gate calls CLEAN came back BLOCKED with the line quoted; the second time, the stored result).
- [x] The review when someone asks to merge (pi #75, OpenCode's TUI #77: both seen) and on every turn when the user
  turns it on (#76: seen on pi; Claude Code and Codex tested through their `Stop` hooks, not seen in a session).
  The review at the end of every turn is not offered in OpenCode: its end-of-turn hook stops waiting after 30
  seconds.
- [x] pi: `/foreman` board, verdict, review, merge, reject, allow and pipeline (#74, #75; a throwaway pull request
  of the demo repository merged by Foreman from pi's terminal UI, another rejected and closed).
- [x] OpenCode: the same line through its TUI plugin (#77): the board in a dialog, `use` in the select, a
  throwaway pull request merged by Foreman from the TUI; a rejection carried out and `allow` through the TUI were
  tested, not seen. Through the server command (apps, HTTP API) merge and reject answer "nobody is attending".
- [x] `plugin/` unchanged by the adapters; `hermes plugins validate plugin` and the tests green throughout.

## Open questions and risks
- Allowing a finding in Codex is not available: nothing shown separates the person's own prompt from one the agent
  writes for a subagent or from a resumed session. Settling it needs an interactive Codex session in a folder Codex
  trusts, which writes to the owner's `~/.codex`: the owner's to try, or to allow.
- OpenCode decides "a person approved" by a permission prompt and time (a yes within a second is nobody); a late
  automatic yes is not detected. Its end-of-turn nudge depends on a hook OpenCode marks experimental. Measured on
  2026-11-24 (OpenCode 2.3.2's source, and two short runs): every auto mode answers a permission request as a
  client, after the plugin's `evaluate` hook, and the reply says nothing about who answered; a server command's
  `execute` cannot tell a typed command from one sent through the HTTP API, the SDK or `opencode api`. The sound
  sign of a person is a TUI plugin (a folder with `tui.ts`: its own slash command, registered with `mode: "global"`,
  runs in the TUI before any server command, and its `dialog.select` and `dialog.prompt` are answered by no auto
  mode and have no route from the model). Read, not seen: with OpenCode's background service (its default) the
  agent's shell can reach `opencode api`, whose password is in a readable state file, and so answer a permission
  prompt or call the server `/foreman`: that weakens today's `allow` there. A `{"plugins": ["-*", …]}` project
  configuration does not keep a user-level TUI plugin out of a trial.
- In every harness the hooks and Foreman's state are files (same debt as Hermes's state guard), and a second agent
  started without Foreman (`pi -ne`, a harness run with its hooks off) is outside the gate: CI stays the control.
- The reviewer in Claude Code is the account's default model, not necessarily the session's: Claude Code names the
  model to no hook. In Codex the choice of reviewer is a file, and the session still sees the person's global
  instructions and declares a few tools with no switch. None of the four was tried on Windows.
- The Hermes plugin's own review keeps line breaks in a finding's text (ESTADO, known issues): one line in
  `review.verify`, for the catalog update.
- T6 on OpenCode: a server command can answer only through an error notice; the TUI plugin has dialogs and toasts.
- A merge outside Hermes runs the command twice (ask, then answer), so its gate, review and "waiting" lines are
  twice in the pipeline; a review that failed on the first run is tried once more on the second.
- The review at the end of every turn stops for one change after three send-backs or four reviews, and in Claude
  Code and Codex nothing shows that change waiting (they have no `pipeline`); only `reviewer` states the limits.
- Whether the Hermes catalog's scanner reads outside `subdir`: unknown; nothing binary is committed anywhere.
- Names and distribution (marketplace, npm, how Codex's hooks are installed): the owner, T7.

## Any agent: the evaluation of 2026-11-25
The owner's question: what Foreman needs to be usable whatever the harness, even in a narrower form. What he
decided of the proposal below (DECISIONES, 2026-11-25): the gate's false refusal after a rebase first (#83), then
`action.yml` and a README by level, then publishing what is built; the `generic` host, the terminal command and
the installer of git's hooks, not now.
- Measured, in throwaway repositories on macOS, with the detector imported by a probe that was not kept:
  - As git's `pre-commit` hook (`detector.scan_worktree`, staged only) it refuses a commit that switches a test
    off, with the file and line on git's own error output, in about 60 ms; as `pre-push` (`detector.scan_range`)
    it refuses the push of such a commit in about 95 ms; a clean commit and push pass.
  - As a `reference-transaction` hook it also refuses `git commit-tree` with `git update-ref`, and it runs on
    every change of a branch, a pull included.
  - `adapters/hook.py pi`, given `neutral.py`'s requests from a plain shell with no harness running, blocks the
    rigged `git commit` and `gh pr merge` and answers `status`: the protocol needs no harness, only a host's name.
  - A push range taken from the branch's old tip on the remote refuses a rebased branch for a change that came
    with the base branch; today's gate does the same (ESTADO, known issues).
  - Not measured: the flag that skips git's hooks (this machine's agent permissions refuse it; git documents it).
- Read, in documentation, nothing run:
  - Every client-side git hook can be skipped by whoever has a shell (a flag, `core.hooksPath`, another git,
    GitHub's API); only what GitHub enforces cannot. Aider commits skipping hooks unless told otherwise.
  - A required check is matched by its name, and a pull request runs its own copy of a workflow: the check
    counts only with the workflow's folder protected, and an agent on the person's own token is the person.
  - Copilot CLI, Cursor, VS Code's agent mode, Droid, Qwen Code and Junie copy Claude Code's hooks, each with
    differences (tool names, a hook that times out lets the call through); Gemini CLI, Goose, Devin, Kiro,
    Crush, Amp and Cline have their own; Aider and Zed have none; cloud agents never run on the person's
    machine. None of them is installed on this machine.
  - No standard to aim at once: the published plugin specification leaves hooks out, and an MCP server cannot
    gate a harness's own tools, nor is its question to the user a sound sign of a person.
  - No other tool was found that reads the real diff for a rigged test.
- The proposal, after the review by an agent that did not write it (its findings are in what follows):
  - Three levels, named by what each can promise. **Locked**: the required check in CI, for any agent; it means
    the workflow protected, the agent unable to merge alone, and marked findings either failing (`--strict`) or
    behind a required review. **Guarded**: a harness's hook; a harness is named only after its own test in a
    real session (DECISIONES, 2026-11-24). **Early warning**: git's `pre-commit` and `pre-push`; a marked finding
    is listed there and does not block, and a missing Foreman lets the commit through with a loud line.
  - To build, outside `plugin/`: one terminal command (the detector's `check`, `status` saying which level the
    repository really has as yes, no or unknown, and installing the git hooks; run from git first, a store
    only with the owner's yes); `action.yml` and `.pre-commit-hooks.yaml` at the root; a `generic` host that
    answers the gate's events and `status`, refuses where it would ask, and has no `allow` and no `merge`.
  - The hooks leave a person's own work alone: the push range is the commits no remote has yet, and a merge, a
    cherry-pick or a rebase in progress is not inspected at commit time.
  - Not to build: an MCP server, a shim in front of `git` and `gh`, a sandbox, the `reference-transaction` hook.

## Tasks
- [x] T1 The neutral half and the Claude Code adapter (pull request #61).
- [x] T2 Codex adapter (#64), on the shared base (#62).
- [x] T3 pi extension (#63).
- [x] T4 OpenCode v2 plugin (#65).
- [x] T5 The reviewer as a fresh session, in the four, when the person asks (#67 the neutral half and Claude Code,
  #68 Codex, #69 pi, #70 OpenCode).
- [x] T6 `/foreman` complete on pi and OpenCode, and with `/foreman merge` the review at merge time (the plan the
  owner agreed to on 2026-11-24, «ok»; before the Hermes catalog update, so that there is only one):
  - [x] T6.1 The shared base (#74): a stand-in for Hermes's context so `plugin/foreman/board.py` runs unchanged,
    and the commands that only read (`board`, `verdict`, `pipeline`, `prs`, `issues`, `use`) on pi and OpenCode.
  - [x] T6.2 pi: `merge` and `reject`, asked through pi's own selector, with the review before the merge (#75).
  - [x] T6.3 OpenCode (#77). Measured: a sound sign of a person exists, through a TUI plugin only (above). So the
    full line there is that plugin (`adapters/opencode/tui.ts`, installed as a folder with `server.ts`): `/foreman`
    typed in the TUI is handled by it (replies in a dialog, questions in its select, `attended` true), while the
    server command keeps refusing `merge` and `reject`. Left open, in its README's limits: plugin code the agent
    plants in a plugin folder is loaded by OpenCode with the same powers (guarding the folders would block a
    project's own plugin work); a reply longer than the terminal is cut off (the dialog does not scroll).
  - [x] T6.4 Each piece reviewed by an agent that did not write it before it merged: #74 (nothing blocking), #75
    (one blocking finding, the "second-model" wording on pi; fixed), #76 (one, OpenCode's short end-of-turn wait;
    fixed by not offering the option there).
  - [x] T6.5 Seen in a real session: throwaway pull request #19 of the demo repository merged by Foreman from pi's
    terminal UI, #20 rejected and closed.
- [x] T6b The review on every turn, where the user turns it on (#76): Claude Code, Codex and pi.
- [ ] T7 READMEs, names and publication (owner's yes); the one Hermes catalog update with what the core needed.

## Next step
T7, which starts with the owner: the names of the packages, where each adapter is published (Claude Code's
marketplace, npm for pi and OpenCode, how Codex's hooks are installed) and what the root README says about them.
Until then nothing is published and the root README does not mention the adapters. With his answers: the READMEs,
the publication of each harness whose end-to-end test passed (Claude Code, Codex, pi and OpenCode all have one;
Windows nowhere), and the one Hermes catalog update with what waits for it: the one line in `review.verify`
(a finding's words on one line), the three seams the stand-in wraps today (above, "How it is built"), the native
model picker (`trabajo/model-picker.md`), the README's award, GIF and `/foreman notify on`.

What an agent can do before that without the owner: see the per-turn review in a real Claude Code and a real Codex
session (one short session each, in a throwaway repository, `claude --plugin-dir` and `codex -c hooks.…`); give
OpenCode's end of turn the long wait and its session's model, so the per-turn review can be offered there
(`Host.turn_review`); see a rejection and `allow` through OpenCode's TUI.
