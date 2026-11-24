# Foreman state — 2026-11-24

> Rewritten in full, never appended; kept short.

<!-- pic-method: next-session -->
## Next session
- Doing: Foreman for any harness (DECISIONES, 2026-11-24; the plan, the facts read about each harness and the task
  list are in `trabajo/agnostico.md`). Its first task, the host-neutral half plus the Claude Code adapter, is pull
  request #61, a draft: 460 tests green here on Python 3.9 and 3.12, and seen in real Claude Code 2.1.331 sessions
  with `bypassPermissions` (a rigged commit, an agent-run merge and an edit that skips a test denied; a turn that left
  a skipped test sent back once; `/foreman:status`, `/foreman:allow` and `/foreman:help` answered with no model turn;
  `allow` refused with `-p` and accepted typed in an interactive session). Nothing under `plugin/` changed.
- Tried: `/foreman` as a bare command does not work in Claude Code's interactive prompt (it rejects an unknown
  command before any hook), so the person's commands are the plugin's own (`/foreman:status`), which the
  `UserPromptSubmit` hook answers before the model sees them.
- Next action: #61 waits for the review by an agent that did not write it (launched 2026-11-24) and for CI, which
  now also runs Python 3.9. Fix what blocks, mark it ready, merge it by squash. Then T2 to T4 (Codex, pi and
  OpenCode with the gate; independent, one agent each), T5 (the reviewer as a fresh session) and T6 (`/foreman`
  complete on pi and OpenCode). Each harness is published only after its own real-session test.
- External PR #57 (`***REDACTED***` as a placeholder in the detector): read in full, nothing malicious seen, not run.
  Changes asked on 2026-11-23: git-filter-repo's default marker is `***REMOVED***`, which it leaves blocked. Next:
  when the author pushes the fix, re-read the whole diff, approve its held CI run (the owner chose to wait for the
  fix), then decide the merge. Unverified by a run: by reading, `KEY=***REDACTED***#value` in a `.env` would pass.
- Hermes: Foreman is in its catalog at the pin ce9b01a (NousResearch/hermes-agent#153851;
  https://hermes-agent.nousresearch.com/marketplace/foreman) and the owner's default profile runs that pin. A plugin
  change reaches users only through a SHA-bump pull request to the catalog, tried first in the `foremandev` profile;
  the next one is the single substantial update (DECISIONES, 2026-11-22 and 2026-11-24). The seams issue #153841 was
  closed as "not planned": propose each seam on its own.
- Foreman won 1st place in the Hermes Agent Plugin Hackathon (Nous's post:
  https://x.com/NousResearch/status/2123882434173559007); how the prizes are paid is unknown. Promotion is another
  project's (DECISIONES, 2026-11-23).
- What waits for Pedro lives in OmniBrain: `omnibrain_esperas` with repo `foreman`, or «Te espera» in the panel.

## Delivered
- The Hermes plugin, version 0.1.0, in `plugin/`, listed in the Hermes catalog; CI on Linux, macOS and Windows.
- `PedValme/foreman-demo` (public) as the demo repository; the README as one page with the real capture and the GIF.

## In progress
- Foreman for any harness: pull request #61 (the neutral half and Claude Code), in review.

## Next steps
1. `trabajo/agnostico.md`, T2 to T7. Names of the packages and where each adapter is published: to the owner when
   the first adapter is merged and tried by him (T7); the root README does not mention the adapters until then.
2. The one Hermes catalog update: what the adapters needed from the core, the native model picker
   (`trabajo/model-picker.md`), the README's award and GIF, and `/foreman notify on` in the README (`hermes config
   set …notify on` stores a boolean and Hermes then warns on every load).
3. Propose the Hermes seams one by one (#153841's advice): first the terminal cwd accessor, which removes the
   guarded private import.
4. Clean up the hackathon's throwaways: `~/cart`, `~/foreman-demo` and `/tmp/fm-battery*` on the owner's machine;
   the throwaway PRs #6-#14 and branches `t/*` in `foreman-demo`; the unpushed local branch
   `claude/minimal-child-env`.
5. Whether the private voice-plugins test repository becomes a project; whether only the owner merges here;
   register `foreman-demo` in the owner's environment as outside the factory.

## Known issues
- Unresolved (adapters): outside Hermes, Foreman's hooks and state are files the agent's shell can reach; the
  adapter blocks what names them plainly, not a disguised attempt (a path built at run time, a script the agent
  writes). The required check in CI stays the independent control.
- Unresolved (Claude Code adapter): without `python3` on the PATH its hooks fail and Claude Code goes on without the
  gate, showing the error; not tried on Windows in a real session; its answers to the person's commands carry
  Claude Code's own frame ("UserPromptSubmit operation blocked by hook").
- Unresolved: the Desktop pane can disappear from the app's layout and not return until the app is reloaded and the
  Desktop switch is toggled; cause not proven (#22).
- Unresolved: with a running gateway, a slash command typed first in a CLI session cannot tell the repository and
  asks for it; `/foreman use <path>` is the way around.
- Unresolved: one guarded private import (`tools.terminal_tool.get_session_cwd`) makes `hermes plugins validate`
  warn; a pushed notification cannot carry buttons, Hermes shows no approval prompt for a plugin's command, and
  Telegram's choice buttons show only numbers.
- Unresolved (debt from the reviews): state files are plain files behind a best-effort guard; a SARIF report
  replaced by a separate command is not noticed; `include`d makefiles and a new `GNUmakefile` are not covered; a
  merge through `gh api` or a direct push to the base branch is not blocked; the real-panel behaviour test runs only
  where node, React and jsdom are installed (CI skips it).
- Unresolved: the deterministic detector does not see a loosened assertion or an emptied test; only the
  second-model review does.
- Unresolved: a change bounced by the review whose agent ends the turn without changing it stays "bounced 1/3",
  with no notice to the owner (the notice comes only at the limit).
