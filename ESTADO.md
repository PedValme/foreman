# Foreman state — 2026-11-10

> Rewritten in full, never appended; kept short.

<!-- pic-method: next-session -->
## Next session
- Was doing: the whole line is on `main` — gate (#2, hardened in #14), second-model review (#7, #10), board with
  merge and reject (#6, #8), SARIF source and CI (#4, #11), pipeline with review levels and one verdict vocabulary
  (#15), notifications (#12), Desktop panel (#13), the plugin moved to `plugin/` (#16). `main` is protected (pull
  request and seven CI checks required). In flight: one agent rewriting the README as a single page, adding
  `examples/cart/`, `trabajo/demo-video.md` and the submission drafts (branch `claude/readme-demo`).
- Tried, in real sessions on Hermes v0.23.0 (macOS), dedicated profile: write gate and commit gate (also under
  `--yolo`); a marked exception blocks and is listed; the honest path passes; an agent-run `gh pr merge` under
  `--yolo` is blocked; board, verdicts, refused merge, real rejection comment, real confirmed merge; the review at
  merge time on the fallback model refused a pull request whose only change was two loosened assertions; the
  `finish` loop bounced a loosened assertion once inside one 68-second turn and passed after the fix; a reinstall
  from `plugin/` installed only the plugin files and kept the stored state.
- Not verified in a real session: notifications to a real chat and the Merge / Cancel buttons there; the panel
  inside the real Desktop app or the web app (seen only in the browser preview); `/foreman allow <id>` followed by
  the commit; `--no-verify` (the model declined to run it); SARIF with a real hermes-security export; enabling the
  plugin in the middle of a session.
- Next action: merge the README and demo pull request; then, with the owner: the Telegram checklist, the panel in
  the real app, the texts, the video; pin the commit, validate, open the catalog pull request.
- Waits for the owner: try the notifications on his Telegram (install Foreman in his real Hermes profile for that test, then the 8-step checklist in the notifications pull request #12) · Recommended: install it there only for the test and remove it after
- Waits for the owner: read `trabajo/catalog-pr.md`, `trabajo/catalog/foreman.yaml` and `trabajo/hermes-issue-seams.md` and say yes to opening them with his account · Verified by: the pull request and the issue open in NousResearch/hermes-agent
- Waits for the owner: record the demo video following `trabajo/demo-video.md` and publish it on X tagging @NousResearch · Verified by: the X link in the submission form
- Waits for the owner: submit the hackathon form with the catalog PR link and the video link

## Delivered
- The plugin, version 0.1.0: 345 tests, CI on Linux, macOS and Windows, `hermes plugins validate plugin` passing
  with one guarded private-import warning.

## In progress
- README as one page, the cart example, the video script, the submission drafts.

## Next steps
1. Real-app screenshots of the panel to replace the preview ones; the remaining real-session checks above.
2. Pin the commit, `hermes plugins validate` at that commit, catalog pull request open by 2026-11-11 12:00 (Lima).
3. Edit the video; the X post; the form.
4. Remove the `foremandev` profile and the temporary clones from the owner's machine when testing ends.
5. After the submission: ask the owner whether the private Token Plan repository becomes a project; whether only
   he merges in this repository from then on.

## Known issues
- Unresolved: when the CLI hands a slash command to a running gateway before the agent has used the terminal in
  that session, Foreman cannot tell the repository and asks for it; `/foreman use <path>` is the way around.
- Unresolved: one guarded private import (`tools.terminal_tool.get_session_cwd`) makes `hermes plugins validate`
  warn; Hermes has no public way to read the terminal's directory. Requested upstream (draft).
- Unresolved: a pushed notification cannot carry buttons and Hermes shows no approval prompt for a command a plugin
  runs; the buttons appear when the person sends the command back. Requested upstream (draft).
- Unresolved (debt from the reviews): the state files are protected by a best-effort guard, not signed; a SARIF
  report replaced by a separate command is not noticed; `include`d makefiles and a new `GNUmakefile` are not
  covered by the check protection.
- Unresolved: the deterministic detector does not see a loosened assertion or an emptied test; only the
  second-model review does.
