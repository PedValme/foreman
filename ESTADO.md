# Foreman state — 2026-11-10

> Rewritten in full, never appended; kept short.

<!-- pic-method: next-session -->
## Next session
- Was doing: the plugin is complete on `main` (a51184d and later documents) and the catalog entry, README and
  drafts are ready, but the owner stopped the video: nothing is recorded or submitted until every function has been
  tried end to end in a real session and works (DECISIONES.md, 2026-11-10). The full list, with what is verified and
  what is not, is `trabajo/pruebas-punta-a-punta.md`. The deadline is 2026-11-11 17:00 (Lima).
- Tried: a first real-session battery for the gate was started at 18:10 (`trabajo/pruebas/gate-battery.sh`); its
  first five cases blocked as they should, the rest had not finished when the session closed. The video was
  rehearsed twice: the "before" shot depends on the model agreeing to skip a test, which it does not always do, so
  that script (`trabajo/demo-video.md`) no longer holds; the owner wants the video to show the whole line.
- Next action: work through `trabajo/pruebas-punta-a-punta.md` top to bottom. Rerun the gate battery whole first,
  then the commands, review and pipeline cases from the CLI, then SARIF with a real hermes-security export and the
  example workflow in `PedValme/foreman-demo`. Fix what fails by pull request (seven CI checks, a reviewer that did
  not write it). Then, with the owner: the automatic notification on Telegram, the panel's buttons and live motion,
  installing from the app. Only then: rewrite the video script around one change moving through the whole line,
  record, pin the commit, open the catalog pull request and the issue with his account, the form.
- Waits for the owner: the cases only he can do (Telegram automatic notification, the panel's Merge and Reject buttons, the panel live, installing from the app), when the CLI cases are green · Recommended: in that order, in one sitting
- Waits for the owner: say yes to opening `trabajo/catalog-pr.md`, `trabajo/catalog/foreman.yaml` and `trabajo/hermes-issue-seams.md` with his account, after everything is verified (he read the summaries and approved the four changes to the entry) · Verified by: the pull request and the issue open in NousResearch/hermes-agent
- Waits for the owner: record the video once the plugin is fully verified, then publish it on X tagging @NousResearch and submit the form

## Delivered
- The plugin, version 0.1.0, in `plugin/`: 359 tests, CI on Linux, macOS and Windows, `hermes plugins validate
  plugin` passing with one guarded private-import warning; the catalog entry draft passing Hermes's validator
  (short description, category `automation`, a real-app capture first).
- `PedValme/foreman-demo` (public) as the demo repository; the README as one page with the real capture.

## In progress
- End-to-end verification (`trabajo/pruebas-punta-a-punta.md`).

## Next steps
1. The verification list, then the fixes it asks for.
2. The video script rewritten (one change through the whole line: gate, second model, bounce, notification,
   approval, merge, with the panel alongside), rehearsed, then recorded and edited.
3. Pin the commit, validate, open the catalog pull request and the issue; the X post; the form.
4. Clean up: the `foremandev` profile, `~/cart`, `~/foreman-demo` and `/tmp/fm-battery*` on the owner's machine;
   Foreman in the owner's real profile (ask him: keep or remove); the hand-copied Desktop half on the development PC.
5. After the submission: whether the private voice-plugins test repository becomes a project; whether only the
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
