# Foreman state — 2026-11-10

> Rewritten in full, never appended; kept short.

<!-- pic-method: next-session -->
## Next session
- Was doing: everything planned is on `main` and nothing is in flight. The candidate commit for the catalog is
  8f3f469 (#19), which passed a second independent release review ("fit to pin, with text fixes", all applied in
  #19) and a last real-session pass. `main` is protected (pull request and seven CI checks required).
- Tried, in real sessions on Hermes v0.23.0 (macOS), dedicated profile: write gate and commit gate (also under
  `--yolo`); a marked exception blocks, is listed, and after `/foreman allow <id>` the same commit passes while the
  same marked line above another test needs its own approval; the honest path passes; an agent-run `gh pr merge`
  under `--yolo` is blocked; board, verdicts, refused merge, real rejection comment, real confirmed merge; the
  review at merge time on the fallback model refused a pull request whose only change was two loosened
  assertions, and asking again returned the stored review without calling the model; the `finish` loop bounced a
  loosened assertion once inside one 68-second turn and passed after the fix; an install from `plugin/` at the
  candidate commit installed only the plugin files and kept the stored state.
- Not verified in a real session: notifications to a real chat and the Merge / Cancel buttons there; the panel
  inside the real Desktop app or the web app (seen only in the browser preview; the web app is built and serving
  on the development PC, but the automated browser could not open it); `--no-verify` (the model declined to run
  it); SARIF with a real hermes-security export; enabling the plugin in the middle of a session.
- Next action, with the owner: decide the repository for the video's pull requests; the Telegram checklist; the
  panel in the real app (then real screenshots); read the three drafts; record the video. Then pin the commit in
  `trabajo/catalog/foreman.yaml`, validate, open the catalog pull request and the issue with his account.
- Waits for the owner: choose the GitHub repository for the video's board and merge shots · Recommended: a small public `PedValme/foreman-demo` made from `examples/cart`
- Waits for the owner: try the notifications on his Telegram (install Foreman in his real Hermes profile for that test, then the 8-step checklist in pull request #12) · Recommended: install it there only for the test and remove it after
- Waits for the owner: look at the panel in Hermes Desktop or the web app on the development PC (`hermes webapp`, then Capabilities → Plugins → Foreman → Desktop)
- Waits for the owner: read `trabajo/catalog-pr.md`, `trabajo/catalog/foreman.yaml` and `trabajo/hermes-issue-seams.md` and say yes to opening them with his account · Verified by: the pull request and the issue open in NousResearch/hermes-agent
- Waits for the owner: keep or change the credit line "Built by AQP Intelligence" in both READMEs · Recommended: keep it
- Waits for the owner: record the demo video following `trabajo/demo-video.md` and publish it on X tagging @NousResearch · Verified by: the X link in the submission form
- Waits for the owner: submit the hackathon form with the catalog PR link and the video link

## Delivered
- The plugin, version 0.1.0, in `plugin/`: 351 tests, CI on Linux, macOS and Windows, `hermes plugins validate
  plugin` passing with one guarded private-import warning, the catalog entry draft passing Hermes's validator.
- The README as one page, `examples/cart/`, the video script and the submission drafts in `trabajo/`.

## In progress
- Nothing.

## Next steps
1. With the owner: the pending items above, in that order.
2. Real-app screenshots of the panel to replace the preview ones (a later SHA bump if they come after the pin).
3. Pin the commit, validate at that commit, catalog pull request open by 2026-11-11 12:00 (Lima).
4. Edit the video; the X post; the form.
5. Clean up: the `foremandev` profile and the temporary clones on the owner's machine; on the development PC the
   web app was turned on (`webapp.enabled`) and a `foremandev` profile created for the panel check.
6. After the submission: ask the owner whether the private voice-plugins test repository becomes a project, and
   whether only he merges in this repository from then on.

## Known issues
- Unresolved: when the CLI hands a slash command to a running gateway before the agent has used the terminal in
  that session, Foreman cannot tell the repository and asks for it; `/foreman use <path>` is the way around.
- Unresolved: one guarded private import (`tools.terminal_tool.get_session_cwd`) makes `hermes plugins validate`
  warn; Hermes has no public way to read the terminal's directory. Requested upstream (draft).
- Unresolved: a pushed notification cannot carry buttons and Hermes shows no approval prompt for a command a plugin
  runs; the buttons appear when the person sends the command back. Requested upstream (draft).
- Unresolved (debt from the reviews): the state files are plain files behind a best-effort guard, so a deliberate
  write could forge a stored review; a SARIF report replaced by a separate command is not noticed; `include`d
  makefiles and a new `GNUmakefile` are not covered by the check protection; two Hermes processes sharing the
  data directory could send one notification twice; a merge through `gh api` or a direct push to the base branch
  is not blocked (protect the base branch on GitHub).
- Unresolved: the deterministic detector does not see a loosened assertion or an emptied test; only the
  second-model review does.
