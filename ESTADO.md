# Foreman state — 2026-11-11

> Rewritten in full, never appended; kept short.

<!-- pic-method: next-session -->
## Next session
- Was doing: the overnight final review (DECISIONES.md, 2026-11-11): five reviewers (catalog rules, an adversarial
  attack on the gate, docs against code, verification coverage, fresh install and privacy), each finding verified and
  fixed in #33 (merged), its gate and detector changes reviewed twice by another agent. Foreman d6fb66b is installed
  in the real profile (settings kept) and `foremandev`; the catalog entry is pinned to d6fb66b (#34; Hermes's
  catalog validator OK, the screenshots 200). The deadline is 2026-11-11 17:00 (Lima).
- Tried: both gate batteries re-run on d6fb66b (18/18), the detector CLI by hand, a real merge and reject with the
  merged/rejected notices. The new video script is `trabajo/demo-video.md` (one change through the whole line,
  every step asked in plain words so each take behaves the same), with `trabajo/pruebas/prepare-recording.sh` (dry
  run by default) to reset `foreman-demo` and the panel before each take.
- Next action (morning, with the owner): he grants the two capabilities with `hermes plugins enable foreman` in a
  terminal on the Hermes machine; `prepare-recording.sh --go`; rehearse the script once (section (e)); record; then
  open the Hermes issue, the catalog pull request (noreply email, steps at the top of `trabajo/catalog-pr.md`), the
  X post, the form. If anything in the plugin changes before submitting, pin the entry again.
- Waits for the owner: say yes to opening `trabajo/catalog-pr.md`, `trabajo/catalog/foreman.yaml` and `trabajo/hermes-issue-seams.md` with his account, after everything is verified (he read the summaries and approved the four changes to the entry) · Verified by: the pull request and the issue open in NousResearch/hermes-agent
- Waits for the owner: record the video once the plugin is fully verified, then publish it on X tagging @NousResearch and submit the form
- Waits for the owner: his personal email is the author of commits in the public history of `PedValme/foreman` and `foreman-demo` (rewriting shared history is not allowed here) · Recommended: accept it for the existing commits and set the GitHub noreply address for future ones (and "Block command line pushes that expose my email" on GitHub)
- Waits for the owner: DECISIONES.md quotes his words with the names of his private tooling (the factory, its guardian) · Recommended: keep them (they are words, not hosts or secrets; the hostname and accounts were already redacted)

## Delivered
- The plugin, version 0.1.0, in `plugin/`: 376 tests, CI on Linux, macOS and Windows, `hermes plugins validate
  plugin` passing with one guarded private-import warning; the catalog entry draft passing Hermes's validator
  (short description, category `automation`, a real-app capture first).
- `PedValme/foreman-demo` (public) as the demo repository; the README as one page with the real capture.
- End-to-end verification in real sessions, the owner's sitting included (`trabajo/pruebas-punta-a-punta.md`).

## In progress
- The video (script ready), then the catalog submission.

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
