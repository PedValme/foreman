# Foreman state — 2026-11-11

> Rewritten in full, never appended; kept short.

<!-- pic-method: next-session -->
## Next session
- Was doing: end-to-end verification before the video (DECISIONES.md, 2026-11-10). Done: every CLI case and the
  owner's sitting on Telegram and Desktop (2026-11-10/11 night) all work; the list is `trabajo/pruebas-punta-a-punta.md`.
  The deadline is 2026-11-11 17:00 (Lima).
- Tried: the real sessions found ten defects, all fixed and merged (#26, #29, #30, and the remembered-repository
  pull request `claude/gated-repo`); what remains open is Hermes's (numbered Telegram buttons, the Desktop spinner
  after a plugin question, plugin model calls through the auxiliary client) and two small items in the list.
  Foreman on the owner's real profile was reinstalled from the Desktop app (his settings restored: notify on to
  telegram, auto_review merge); `foremandev` runs d5e6f6f. `foreman-demo`: the video's clean fix is PR #15.
- Next action: rewrite the video script around one change moving through the whole line (`trabajo/demo-video.md`
  no longer holds), rehearse, record; then pin the commit, the catalog pull request and the issue with the owner's
  account, the X post, the form. #31 is merged and installed at 2bed849 in the real profile and `foremandev`; the
  Hermes findings are in `trabajo/hermes-issue-seams.md` (section 5).
- Waits for the owner: say yes to opening `trabajo/catalog-pr.md`, `trabajo/catalog/foreman.yaml` and `trabajo/hermes-issue-seams.md` with his account, after everything is verified (he read the summaries and approved the four changes to the entry) · Verified by: the pull request and the issue open in NousResearch/hermes-agent
- Waits for the owner: record the video once the plugin is fully verified, then publish it on X tagging @NousResearch and submit the form

## Delivered
- The plugin, version 0.1.0, in `plugin/`: 370 tests, CI on Linux, macOS and Windows, `hermes plugins validate
  plugin` passing with one guarded private-import warning; the catalog entry draft passing Hermes's validator
  (short description, category `automation`, a real-app capture first).
- `PedValme/foreman-demo` (public) as the demo repository; the README as one page with the real capture.
- End-to-end verification in real sessions, the owner's sitting included (`trabajo/pruebas-punta-a-punta.md`).

## In progress
- The video.

## Next steps
1. The video script rewritten (one change through the whole line: gate, second model, bounce, notification,
   approval, merge, with the panel alongside), rehearsed, then recorded and edited.
2. Pin the commit, validate, open the catalog pull request and the issue; the X post; the form.
3. Clean up: the `foremandev` profile, `~/cart`, `~/foreman-demo` and `/tmp/fm-battery*` on the owner's machine;
   Foreman in the owner's real profile (ask him: keep or remove); the throwaway PRs #6-#14 and branches `t/*` in `foreman-demo`.
4. After the submission: whether the private voice-plugins test repository becomes a project; whether only the
   owner merges here from then on; register `foreman-demo` in the owner's environment as outside the factory.

## Known issues
- Unresolved: the Desktop pane can disappear from the app's layout and not return until the app is reloaded and the
  Desktop switch is toggled; cause not proven (#22).
- Unresolved: with a running gateway, a slash command typed first in a CLI session cannot tell the repository and
  asks for it; `/foreman use <path>` is the way around.
- Unresolved: one guarded private import (`tools.terminal_tool.get_session_cwd`) makes `hermes plugins validate`
  warn; a pushed notification cannot carry buttons, Hermes shows no approval prompt for a plugin's command, and
  Telegram's choice buttons show only numbers. All four are in the draft request to Hermes.
- Unresolved (debt from the reviews): state files are plain files behind a best-effort guard; a SARIF report
  replaced by a separate command is not noticed; `include`d makefiles and a new `GNUmakefile` are not covered; a
  merge through `gh api` or a direct push to the base branch is not blocked; the real-panel behaviour test runs only
  where node, React and jsdom are installed (CI skips it).
- Unresolved: the deterministic detector does not see a loosened assertion or an emptied test; only the
  second-model review does.
- Unresolved: a change bounced by the review whose agent ends the turn without changing it stays "bounced 1/3",
  with no notice to the owner (the notice comes only at the limit).
