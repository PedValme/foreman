# End-to-end verification before the video and the catalog pull request

The owner's instruction (DECISIONES.md, 2026-11-10): nothing is recorded or submitted until EVERY function has been
tried end to end in a real Hermes session and works. This file is the list. Deleted when it is all green.

"Real" means: a real Hermes v0.23.0 session with a model, on the owner's Hermes machine, in the dedicated profile
`foremandev` (the development PC's Hermes has no model provider). Unit tests and CI do not count here.

How to run a real case: over SSH to the owner's Hermes machine (how to reach it is in his private environment),
`hermes -p foremandev chat --yolo -q "Run exactly this one terminal command … : <command>"` and then read what git
says happened. `trabajo/pruebas/gate-battery.sh` does that for the gate (13 cases, about 10 minutes); copy it to the
machine and run it with bash. Slash commands need a repository: `/foreman use <path>` first, and for several
commands in one session capture the session id from the first call and use `--resume <id>` (without `--max-turns`).

## Verified in a real session
- Write gate: `@unittest.skip` through the edit tool is blocked; file untouched. Also under `--yolo`.
- Commit gate: a skip already in the tree blocks `git commit`. Also under `--yolo`.
- Exception: a `foreman:allow` marker blocks with an id; `/foreman allow` lists it; `/foreman allow <id>` lets that
  commit pass; the same marked line above another test needs its own id.
- Agent-run `gh pr merge` under `--yolo`: blocked ("Merging is the user's decision").
- `/foreman use`, the board, `/foreman verdict <pr>`, `/foreman pipeline <pr|branch>`, `/foreman status <path>`.
- `/foreman merge`: refuses a BLOCKED pull request; refuses on the second-model review (two loosened assertions,
  reviewer on the fallback model of another provider); the stored review is reused without a model call; on
  Telegram the Merge / Cancel choice works both ways; `--yes` merges and GitHub closes the linked issue.
- `/foreman reject <pr> <note>`: one real comment on the pull request.
- `finish` loop, once, from the CLI: one bounce inside a 68-second turn, then a passing review.
- `/foreman notify on` and `/foreman notify test` on Telegram (the owner's real profile): the message arrives.
- Desktop panel in the real app (Windows client, remote backend): renders real data, the chip brings the pane
  forward, "Show verdict" sends the command, a merge refused by the review reads "Review failed". Known rough edge:
  on first enable, and once after it vanished, it needed an app reload and the Desktop switch off and on.
- Settings form for Foreman shows in Desktop → Settings → Plugins.
- Install from Git at a commit with `PedValme/foreman/plugin --ref <sha>`: only the plugin files land.
- Gate battery of 2026-11-10 18:10 (`trabajo/pruebas/gate-battery.sh`), cases 1-11, each blocked with the right
  rule and nothing committed or pushed: deleted test file; test moved out of the tests; changed check script named
  in `.foreman.json`; changed `scripts.test` in `package.json` with no `.foreman.json`; a workflow test step with
  `|| true`; a secret in the diff; `--no-verify`; `HUSKY=0`; `git config core.hooksPath`; `git rm … && git commit`
  in one line; `git push` of a branch whose commit deleted a test. Case 12: an honest commit passed untouched.
  Case 13: a commit with no repository in sight was blocked with the `workdir` hint. All 13 as expected.

## Not yet verified in a real session
Gate
- [ ] a secret that was added and removed in an earlier commit of the pushed range (`secret-history`); a `.env`.
- [ ] `gh pr create` on a rigged branch (blocked) and on a clean branch (passes).
- [ ] `pre_verify` alone (level `merge`): the agent ends a turn with a rigged tree and is told to undo it.
Commands
- [ ] `/foreman prs`, `/foreman issues`, `/foreman verdict <branch>`, `/foreman review` on a branch and on a pull
      request, `/foreman review --fresh`, `/foreman help`.
- [ ] `/foreman merge` refused by conflicts, by a draft, and while GitHub is still computing; `--merge`, `--rebase`.
- [ ] `/foreman reject <pr> --close` (asks; "Post and close", "Post only", "Cancel").
- [ ] a pull request number typed as `2.` and `#2` (fixed in #21, never tried in a chat).
- [ ] the new confirmation card on Telegram (short choices, #21).
Review and pipeline
- [ ] `auto_review: off`; `reviewer_model` and `reviewer_provider` set by hand; the same-model notice on a profile
      without the capabilities (seen once on the owner's real profile, not re-checked after #15).
- [ ] the bounce limit: three failing reviews, then "needs the owner" and the tool stops calling the model.
- [ ] the review budget (`max_bounces + 1` model calls per change).
- [ ] "could not run" (no model reachable) at merge time: the question says so and nothing merges unattended.
Notifications
- [ ] the automatic message when a pull request becomes ready (only `notify test` was seen).
- [ ] the message when the bounce limit is reached; the queue when the event happens inside a hook.
- [ ] `/foreman notify off`, `/foreman notify to <target>`.
Desktop
- [ ] the Merge and Reject… buttons, the Open link, and a command sent with no chat on screen (clipboard toast).
- [ ] the pane updating live while an agent turn moves a change through the line (never seen).
- [ ] installing from the app ("Install from Git") so the app copies the Desktop half itself: one row, pane placed
      without reloading. The half was copied by hand so far.
- [ ] changing a setting from the Settings form and seeing it take effect.
SARIF and CI
- [ ] a real hermes-security export: install the official plugin in `foremandev`, scan the cart example, export
      SARIF, name it in `.foreman.json`, see a finding block and a missing report give INCOMPLETE.
- [ ] `examples/foreman-check.yml` as a required check in another repository (`PedValme/foreman-demo` is the place):
      a rigged pull request goes red, a clean one green, a marked one shows the annotation.
Environments
- [ ] no `gh` on PATH and a repository with no GitHub remote: board, verdict of a branch, and clear messages.
- [ ] a real session on Linux or Windows as the backend (only macOS so far; unit tests run on the three).

## Defects found while testing, still open
- A skip marker is flagged in a file that is not a test: Foreman's own CI check blocked this repository's pull
  request #25 because `trabajo/pruebas/gate-battery.sh` (a shell script that writes a skip marker into a fixture)
  contained the literal `@unittest.skip(...)`. Worked around by building the marker in the script; decide whether
  skip markers should only count in test files.
- The Desktop pane can disappear from the layout and not return until the app is reloaded and the switch toggled;
  the cause was not proven (#22 hardened the plugin; see that pull request's analysis).
- With a running gateway, a slash command typed as the first thing in a CLI session cannot tell the repository and
  asks for it (`/foreman use <path>`).

## Test places (all throwaway)
- `PedValme/foreman-demo` (public): issue #1 open, PR #5 clean fix, PR #3 skipped test, PR #4 loosened assertions.
  PR #2 was merged in the morning test and reverted on `main`.
- A private repository with the owner's voice plugins: PR #6 (skip) and PR #7 (loosened assertions) open.
- On the owner's Hermes machine: profile `foremandev` (English persona and interface set for the video, old persona
  saved beside it; `auto_review: merge`; the two `llm.*` capabilities granted), `~/cart`, `~/foreman-demo`,
  `/tmp/fm-battery*`. Foreman is also installed in the owner's real profile since the Telegram test, with
  notifications on.
- On the development PC: `desktop-plugins/foreman/plugin.js` copied by hand into the Desktop app's folder.
