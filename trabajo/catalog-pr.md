# Catalog pull request for NousResearch/hermes-agent

Foreman is listed since https://github.com/NousResearch/hermes-agent/pull/153851 (opened 2026-11-11, fork
PedValme/hermes-agent, branch add-foreman-plugin), at the pin `ce9b01a2904edb2aadefcb4ae7111d5dc97622c8`, version
0.1.0. The text of that first submission, with its full disclosure, is in this file's history
(`git show 38736f5:trabajo/catalog-pr.md`). Below is the update to 0.2.0, the one substantial update the owner
decided on 2026-11-24.

## Steps, in order
Done on 2026-11-25: steps 1 and 2 with the commit `c0aa24d99ac45b6f04dd66caf5d74b3148a7765e` (installed in
`foremandev`, with the owner's yes; what was seen is under "Validation" below). An adversarial review of this
pull request then asked for changes inside `plugin/` (the regex of control characters written with escapes, two
lines of its README), so the commit to pin is a later one and step 2 is repeated on it. In step 3 the catalog's
validator needs Hermes's own environment: `scripts/run-in-hermes-env python3 scripts/validate_plugin_catalog.py …`.
1. The commit to pin is on `main` with CI green, and has `version: "0.2.0"` in `plugin/plugin.yaml`.
2. Tried on the owner's Hermes machine, in the `foremandev` profile (DECISIONES, 2026-11-14), with the owner's yes
   for that connection: `hermes -p foremandev plugins install` at the full 40-character commit, then a short real
   session (a commit blocked for a skipped test, `/foreman review`, `/foreman use`, the board).
3. `hermes plugins validate plugin --install-deps` on a checkout at that commit, and
   `python scripts/validate_plugin_catalog.py plugin-catalog/foreman.yaml` in the Hermes checkout.
4. In the Hermes fork, a new branch from upstream `main`; `plugin-catalog/foreman.yaml` gets the new `sha`, the
   new `version` and the five `screenshots` URLs re-pinned to the same commit (`trabajo/catalog/foreman.yaml` is
   the entry, with `REPLACE_WITH_40_CHAR_COMMIT_SHA_OF_PEDVALME_FOREMAN` where the commit goes). Nothing else in
   the entry changes: same description, same capabilities, same `requires_hermes`.
5. Commit with the owner's GitHub noreply address (`git -c user.email=82127492+PedValme@users.noreply.github.com
   commit …`): Hermes's Contributor Attribution check fails on an address it cannot map.
6. The pull request goes out under the owner's account, after he has read the text below (DECISIONES, 2026-11-09
   and 2026-11-25).7. When it merges: `hermes plugins update foreman` in the owner's default profile (DECISIONES, 2026-11-14).
**Title:** `plugin-catalog: bump foreman to 0.2.0`

---

## Foreman 0.2.0

Pin `ce9b01a2904edb2aadefcb4ae7111d5dc97622c8` → `REPLACE_WITH_40_CHAR_COMMIT_SHA_OF_PEDVALME_FOREMAN`, version
`0.1.0` → `0.2.0`. Submitted by the repository's owner (rule 5). The range to read:
https://github.com/PedValme/foreman/compare/ce9b01a2904edb2aadefcb4ae7111d5dc97622c8...REPLACE_WITH_40_CHAR_COMMIT_SHA_OF_PEDVALME_FOREMAN

What Hermes installs is `plugin/` only (`subdir: plugin`): `git diff ce9b01a2904edb2aadefcb4ae7111d5dc97622c8
REPLACE_WITH_40_CHAR_COMMIT_SHA_OF_PEDVALME_FOREMAN -- plugin/` is 7 files, about +480/−55 (`foreman/gate.py`,
`foreman/detector.py`, `foreman/review.py`, `foreman/board.py`, `README.md`, and the version in `plugin.yaml` and
`dashboard/manifest.json`; the exact count is filled in with the commit). The rest of the range (tests, the
`adapters/` folder, documents) is not installed.

### What changes for users
- **Fewer refusals for someone else's change.** The gate refused a push after the base branch came into the
  branch (a rebase, a merge), the commit that concludes a merge of the base branch that stopped on a conflict,
  and the push of a branch that follows the base branch, for a change to a test that the base branch brought.
  The agent was told to undo another person's line. Each is now read for what the branch itself does, when a
  remote already has the base branch's commits; the cases still read the old way are in the README's *Known
  limits*.
- **A git attribute no longer hides a skipped test or a secret.** A `.gitattributes` line in the same change
  (`tests/** -diff`) hid them from every reading. A file git shows as binary is now read again as text unless its
  name says it is binary, and a line that hides files from the diff is itself a finding; what still follows the
  attributes is in the README's *Known limits*.
- **A history scrubber's marker is not a secret** (`***REMOVED***`): the first pull request from outside,
  contributed by [sys-dev-git](https://github.com/sys-dev-git)
  ([PedValme/foreman#57](https://github.com/PedValme/foreman/pull/57)).
- **The second model cannot write a line of Foreman's own.** What it writes is shown on one line each and
  without control characters, so a diff that steers the reviewer cannot make `/foreman review` show "Foreman
  review: PASS" or redraw the terminal.
- **`/foreman use` offers one repository once**, also through a link or under a Windows short name.
- The README: what changed in 0.2.0, the award, a 9-second GIF, CI mode run from Foreman's own folder.

### What does not change
- The surfaces it uses: the same two hooks (`pre_tool_call`, `pre_verify`), the one slash command, the two
  tools, `ctx.llm`, `ctx.ask_choice`, `ctx.dispatch_tool`, the Desktop pane and its read-only route. No new
  capability, setting, network path, background process or file written outside its data directory.
- `requires_hermes: ">=0.22.6"`. Standard library only.
- The one `hermes plugins validate` warning: the guarded, read-only import of
  `tools.terminal_tool.get_session_cwd` (now at `foreman/gate.py:666`), asked for as a seam in
  https://github.com/NousResearch/hermes-agent/issues/153841.

### Disclosure (rule 13): two corrections and one addition
- The README's list of the read-only `git` commands it runs lacked two that ran since the first pin:
  `config --get` (and `--get-all`: where a push goes) and `check-ignore` (whether a `.env` is ignored). They are
  in the list now.
- New in this range: `show-ref --verify` (whether a branch exists), and git is run with
  `--no-replace-objects`. During a merge in progress it reads `.git/MERGE_HEAD` to learn the incoming commit.
- The core now looks up three optional names on its own registration context: `foreman_host_label` (a string)
  and `foreman_review_before_merge` and `foreman_finish_review` (callables it would call with the review's
  record). Hermes's `PluginContext` defines none of them, in-process or in the plugin host, so in Hermes these
  lookups return None and nothing is called. They exist for adapters to other harnesses that are under
  construction in the repository's `adapters/` folder, which Hermes does not install.

### Validation
- `hermes plugins validate plugin --install-deps` (Hermes v0.23.4) at the new pin: passed; security scan safe;
  desktop surface and no core override passed; the one warning above.
- `scripts/validate_plugin_catalog.py plugin-catalog/foreman.yaml`: `OK: 1 file(s) valid`.
- The plugin's own CI: unit tests on Linux, macOS and Windows, and Foreman on its own pull requests.
- Tried in real Hermes v0.23.4 sessions at the new pin, in a dedicated profile, before this pull request: an edit
  that adds `@unittest.skip` was blocked and nothing was written; `git commit` with a skip already in the tree was
  blocked and nothing was committed; `/foreman use` listed a repository pinned through a link once, marked as
  pinned; the board; and `/foreman review` of a branch that loosened an assertion answered BLOCKED with the
  finding on one line each, the reviewer picked in Hermes's auxiliary models.
