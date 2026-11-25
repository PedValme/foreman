# Catalog pull request for NousResearch/hermes-agent

Foreman is listed since https://github.com/NousResearch/hermes-agent/pull/153851 (opened 2026-11-11, fork
PedValme/hermes-agent, branch add-foreman-plugin), at the pin `ce9b01a2904edb2aadefcb4ae7111d5dc97622c8`, version
0.1.0. The text of that first submission, with its full disclosure, is in this file's history
(`git show 38736f5:trabajo/catalog-pr.md`). Below is the update to 0.2.0, the one substantial update the owner
decided on 2026-11-24.

## Steps, in order
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
   and 2026-11-25). A first-time contributor's CI there waits for a maintainer.
7. When it merges: `hermes plugins update foreman` in the owner's default profile (DECISIONES, 2026-11-14), and
   only then the announcement (DECISIONES, 2026-11-25).

**Title:** `plugin-catalog: bump foreman to 0.2.0`

---

## Foreman 0.2.0

Pin `ce9b01a2904edb2aadefcb4ae7111d5dc97622c8` → `REPLACE_WITH_40_CHAR_COMMIT_SHA_OF_PEDVALME_FOREMAN`, version
`0.1.0` → `0.2.0`. Submitted by the repository's owner (rule 5). The range to read:
https://github.com/PedValme/foreman/compare/ce9b01a2904edb2aadefcb4ae7111d5dc97622c8...REPLACE_WITH_40_CHAR_COMMIT_SHA_OF_PEDVALME_FOREMAN
(only `plugin/` is installed, `subdir: plugin`; in that folder the range changes `foreman/gate.py`,
`foreman/detector.py`, `foreman/review.py`, `foreman/board.py`, `README.md`, and the version in `plugin.yaml` and
`dashboard/manifest.json`).

### What changes for users
- **Fewer refusals for someone else's change.** The gate refused a push after the base branch came into the
  branch (a rebase, a merge), the commit that concludes a merge of the base branch that stopped on a conflict,
  and the push of a branch that follows the base branch, for a change to a test that the base branch brought.
  The agent was told to undo another person's line. Each is now read for what the branch itself does.
- **A git attribute cannot hide a change.** A `.gitattributes` line in the same change (`tests/** -diff`) hid a
  test switched off, or a secret, from every reading. A file git shows as binary is read again as text unless
  its name says it is binary, and a line that hides files from the diff is itself a finding.
- **A history scrubber's marker is not a secret** (`***REMOVED***`): the first pull request from outside.
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
  `--no-replace-objects`.
- The core now reads three optional attributes of the context it was registered with
  (`foreman_host_label`, `foreman_review_before_merge`, `foreman_finish_review`). Hermes's context has none of
  them, so in Hermes they do nothing; they are how the same core runs in other harnesses from the repository's
  `adapters/` folder, which Hermes does not install.

### Validation
- `hermes plugins validate plugin --install-deps` at the new pin: passed; security scan safe; the one warning
  above.
- `scripts/validate_plugin_catalog.py plugin-catalog/foreman.yaml`: OK.
- The plugin's own CI: unit tests on Linux, macOS and Windows, and Foreman on its own pull requests.
- Tried in a real Hermes session at the new pin before this pull request: <what was seen, filled in at step 2>.
