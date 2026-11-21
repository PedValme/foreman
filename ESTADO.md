# Foreman state — 2026-11-20

> Rewritten in full, never appended; kept short.

<!-- pic-method: next-session -->
## Next session
- Foreman won 1st place in the Hermes Agent Plugin Hackathon (nearly 1,000 entries; Nous's post:
  https://x.com/NousResearch/status/2123882434173559007). Both READMEs say so since 2026-11-20; the one in `plugin/`
  reaches the catalog page only with the next SHA-bump pull request. How the prize is paid is unknown: Nous has not
  written yet, and no official rules were found.
- Before: the catalog listing, now done. Foreman is in the Hermes catalog: NousResearch/hermes-agent#153851,
  approved and merged by the maintainer on 2026-11-13 at the pin ce9b01a after both asks were fixed; its page is
  https://hermes-agent.nousresearch.com/marketplace/foreman. The hackathon submission was complete on 2026-11-11
  (video on X, form received); Nous posts the winners on X.
- Tried: the seams issue NousResearch/hermes-agent#153841 was closed as "not planned" (2026-11-14) with the advice to
  propose each seam as its own focused issue or PR against `hermes_cli/data/plugin_api.json`; until a cwd accessor
  exists the guarded private import stays, as told to the maintainer.
- Next action: post-hackathon work in "Next steps"; any plugin change now reaches users only through a SHA-bump pull
  request to the catalog (rule 4), re-reviewed. The unpushed local branch `claude/minimal-child-env` can be deleted.
- The owner's Hermes (default profile) runs ce9b01a since 2026-11-14, installed pinned from the repo (Hermes v0.23.0's
  bundled catalog predates the listing, so `hermes plugins install foreman` by name works only after a Hermes
  update; then reinstall by name to get catalog updates). Settings and capability grants kept, gateway restarted, a
  direct hook call verified (`gh pr merge` blocked, child env without provider keys); backup in
  `~/.hermes/backups/foreman-a-ce9b01a-20261114-191153`. `notify` is the string `on` since the owner typed
  `/foreman notify on` (2026-11-14; `hermes config set` stores either a boolean or the quotes, never the string).
- What waits for Pedro lives in OmniBrain: `omnibrain_esperas` with repo `foreman`, or «Te espera» in the panel
  (none open on 2026-11-17).

## Delivered
- The plugin, version 0.1.0, in `plugin/`: 376 tests, CI on Linux, macOS and Windows, `hermes plugins validate
  plugin` passing with one guarded private-import warning; the catalog entry draft passing Hermes's validator
  (short description, category `automation`, a real-app capture first).
- `PedValme/foreman-demo` (public) as the demo repository; the README as one page with the real capture.
- End-to-end verification in real sessions, the owner's sitting included (`trabajo/pruebas-punta-a-punta.md`).

## In progress
- Nothing: the plugin is listed in the Hermes catalog at ce9b01a.

## Next steps
1. Propose the seams one by one (Hermes's advice on #153841): first the terminal cwd accessor, which removes
   the guarded private import; each as its own issue or PR against `hermes_cli/data/plugin_api.json`.
2. The native model picker in Foreman's settings (`trabajo/model-picker.md`), after the hackathon. With the next
   plugin change: the README says to turn notifications on with `/foreman notify on`, since `hermes config set
   …notify on` stores a boolean and Hermes then warns "should be str (got bool)" on every load (seen on the owner's
   machine, 2026-11-12; harmless, `notify.py` reads `True` as on).
3. Clean up the hackathon's throwaways: `~/cart`, `~/foreman-demo` and `/tmp/fm-battery*` on the owner's machine;
   the throwaway PRs #6-#14 and branches `t/*` in `foreman-demo`. The `foremandev` profile stays: every new version
   is tried there on the real Hermes before it is pinned in the catalog and installed in the default profile
   (owner's yes, 2026-11-14).
4. After the submission: whether the private voice-plugins test repository becomes a project; whether only the
   owner merges here from then on; register `foreman-demo` in the owner's environment as outside the factory.

## Known issues
- Unresolved: the Desktop pane can disappear from the app's layout and not return until the app is reloaded and the
  Desktop switch is toggled; cause not proven (#22).
- Unresolved: with a running gateway, a slash command typed first in a CLI session cannot tell the repository and
  asks for it; `/foreman use <path>` is the way around.
- Unresolved: one guarded private import (`tools.terminal_tool.get_session_cwd`) makes `hermes plugins validate`
  warn; a pushed notification cannot carry buttons, Hermes shows no approval prompt for a plugin's command, and
  Telegram's choice buttons show only numbers. All four were in Hermes issue #153841 (closed: to be proposed one by one).
- Unresolved (debt from the reviews): state files are plain files behind a best-effort guard; a SARIF report
  replaced by a separate command is not noticed; `include`d makefiles and a new `GNUmakefile` are not covered; a
  merge through `gh api` or a direct push to the base branch is not blocked; the real-panel behaviour test runs only
  where node, React and jsdom are installed (CI skips it).
- Unresolved: the deterministic detector does not see a loosened assertion or an emptied test; only the
  second-model review does.
- Unresolved: a change bounced by the review whose agent ends the turn without changing it stays "bounced 1/3",
  with no notice to the owner (the notice comes only at the limit).
