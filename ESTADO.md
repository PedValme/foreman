# Foreman state — 2026-11-11

> Rewritten in full, never appended; kept short.

<!-- pic-method: next-session -->
## Next session
- Was doing: the hackathon submission, now complete (2026-11-11, before the deadline): the demo video (85 s) posted
  on X (https://x.com/PedValme/status/2120610382024970591), the Hermes issue
  https://github.com/NousResearch/hermes-agent/issues/153841, the catalog pull request
  https://github.com/NousResearch/hermes-agent/pull/153851 (fork `PedValme/hermes-agent`, branch
  `add-foreman-plugin`, pinned to c15453c, the video linked in its body), and the hackathon form (received). Nous
  posts the winners on X after the close.
- Tried: Hermes's catalog validator could not run on the Windows PC this time (auto mode refused running downloaded
  code); it passed on the same entry before, and the only change is the removed DRAFT comment header. The pull
  request's CI had not started (first-time contributor workflows wait for a maintainer).
- Next action: watch the catalog pull request (its CI, once a maintainer approves it, and review comments) and the
  issue; answer them. A change to the plugin needs a new pin (a SHA-bump pull request, rule 4). Then the clean-up and
  the post-hackathon items in "Next steps".
- Waits for the owner: his personal email is the author of commits in the public history of `PedValme/foreman` and `foreman-demo` (rewriting shared history is not allowed here) · Recommended: accept it for the existing commits and set the GitHub noreply address for future ones (and "Block command line pushes that expose my email" on GitHub)
- Waits for the owner: DECISIONES.md quotes his words with the names of his private tooling (the factory, its guardian) · Recommended: keep them (they are words, not hosts or secrets; the hostname and accounts were already redacted)
- Waits for the owner: keep or remove Foreman in his real Hermes profile on his Hermes machine · Recommended: keep it until the catalog review ends, then decide

## Delivered
- The plugin, version 0.1.0, in `plugin/`: 376 tests, CI on Linux, macOS and Windows, `hermes plugins validate
  plugin` passing with one guarded private-import warning; the catalog entry draft passing Hermes's validator
  (short description, category `automation`, a real-app capture first).
- `PedValme/foreman-demo` (public) as the demo repository; the README as one page with the real capture.
- End-to-end verification in real sessions, the owner's sitting included (`trabajo/pruebas-punta-a-punta.md`).

## In progress
- The catalog review: pull request #153851 and issue #153841 open in NousResearch/hermes-agent.

## Next steps
1. Follow the catalog pull request's checks and review until it merges.
2. The native model picker in Foreman's settings (`trabajo/model-picker.md`), after the hackathon.
3. Clean up: the `foremandev` profile, `~/cart`, `~/foreman-demo` and `/tmp/fm-battery*` on the owner's machine;
   the throwaway PRs #6-#14 and branches `t/*` in `foreman-demo`.
4. After the submission: whether the private voice-plugins test repository becomes a project; whether only the
   owner merges here from then on; register `foreman-demo` in the owner's environment as outside the factory.

## Known issues
- Unresolved: the Desktop pane can disappear from the app's layout and not return until the app is reloaded and the
  Desktop switch is toggled; cause not proven (#22).
- Unresolved: with a running gateway, a slash command typed first in a CLI session cannot tell the repository and
  asks for it; `/foreman use <path>` is the way around.
- Unresolved: one guarded private import (`tools.terminal_tool.get_session_cwd`) makes `hermes plugins validate`
  warn; a pushed notification cannot carry buttons, Hermes shows no approval prompt for a plugin's command, and
  Telegram's choice buttons show only numbers. All four are in Hermes issue #153841.
- Unresolved (debt from the reviews): state files are plain files behind a best-effort guard; a SARIF report
  replaced by a separate command is not noticed; `include`d makefiles and a new `GNUmakefile` are not covered; a
  merge through `gh api` or a direct push to the base branch is not blocked; the real-panel behaviour test runs only
  where node, React and jsdom are installed (CI skips it).
- Unresolved: the deterministic detector does not see a loosened assertion or an emptied test; only the
  second-model review does.
- Unresolved: a change bounced by the review whose agent ends the turn without changing it stays "bounced 1/3",
  with no notice to the owner (the notice comes only at the limit).
