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

- Batteries of 2026-11-10 evening (`trabajo/pruebas/gate-battery-2.sh`, `commands-battery.sh`, `review-battery.sh`,
  `bounce-battery.sh`, `bounce-limit-battery.sh`), all as expected unless noted:
  - Gate: `secret-history` (added then removed in the pushed range) and `.env` blocked; `gh pr create` blocked on a
    rigged branch and passed on a clean one; `pre_verify` at level `merge` made the agent undo a changed check
    script.
  - Commands: `help`, `prs`, `issues`, `verdict #8` and `verdict 8.`, `review` of a branch and of a pull request,
    the stored review reused, `review --fresh`; `merge` refused for conflicts, for a draft and while GitHub was still
    computing; `--merge` and `--rebase` merged; `reject --close` with no way to ask says how to confirm, and with
    `--yes` posts and closes.
  - Review: `reviewer_model`/`reviewer_provider` by hand named as the source; without the consent the same-model
    notice; an unreachable model gives COULD NOT RUN and `merge --yes` does not merge; `auto_review: off` merges with
    no model call.
  - Finish loop: a failing review bounces the change; with `max_bounces: 1` the limit is reached at 1/1, the
    `needs_owner` notice is queued, one model call in all. A competent model fixes the finding at the first bounce,
    so three real bounces in one turn were not seen (unit tests cover them).
  - SARIF: hermes-security 0.1.0 (official) installed in `foremandev`, a real scan of a branch with a shell
    injection, SARIF exported; with no report the verdict is INCOMPLETE, with it the finding blocks.
  - CI: `examples/foreman-check.yml` on `PedValme/foreman-demo` (base `t/base`): a deleted test red (#12), a clean
    change green (#13), a marked skip green with its annotation (#14). Not made a required check (needs the
    owner's admin account); the pinned actions warn that Node 20 is deprecated.
  - No GitHub remote: board, verdict of a branch, `prs`, `issues`, `merge`, `reject` all say so clearly.

## Not yet verified in a real session
Commands
- [ ] the confirmation card on Telegram (short choices, #21), and `reject --close` asking there.
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
Environments
- [ ] no `gh` at all: not testable from the CLI on the owner's machine, because slash commands run in the gateway
      process, whose PATH has `gh` (unit tests cover the message).
- [ ] a real session on Linux or Windows as the backend (only macOS so far; unit tests run on the three).

## Defects found on 2026-11-10 evening, fixed in the pull request `claude/verdict-remote-branch`
- `/foreman verdict <branch>` did not find a branch that exists only as `origin/<branch>`.
- With the review unable to run, `merge --yes` refused and then said "To confirm, type: … --yes".
- `pre_verify` scanned a whole unrelated repository (the Hermes home, which is a git repository) because another
  plugin wrote ignored scratch files there, and asked the agent to undo findings in Foreman's own source.
- `/foreman status` showed a blocking SARIF result twice: as the blocker and as a note "outside the change".

- A skip marker quoted or commented in a file that is not a test (Foreman's own `detector.py`, a battery script)
  was reported as a skipped test: fixed by the owner's decision of 2026-11-10 (pull request
  `claude/skip-markers-tests-only`).

## The owner's sitting, 2026-11-10 night (Telegram, his real profile, Foreman at 3cba39b)
- `/foreman review 15` answered COULD NOT RUN (HTTP 429), then PASS WITH NOTES on `--fresh`; `/foreman review 13`
  429 again. Cause: Hermes routes a plugin's call with no override through its auxiliary client, which on his
  machine cannot use Codex ("no Codex OAuth token found") and falls back to opencode-go, overloaded that night.
  `/foreman notify test` and a hand-run `hermes send` of the exact ready text both arrived; the automatic ready
  notice was logged as sent (exit 0 under `--quiet`) but did not arrive, cause not found.
- Fixed in the pull request `claude/review-resilience`: a busy provider is tried three times before "could not
  run"; the model that answered is named when Hermes routed the review elsewhere, and never claimed independent;
  the saved review's path is no longer printed in messaging (Telegram attached the JSON file); `hermes send` runs
  without `--quiet` and its answer (the chat id) is kept and shown by `/foreman notify`.
- Still to do in the sitting: the ready notice again, the confirmation card (`merge 15` → Cancel), `reject 13
  --close` → Post only, then the Desktop panel.

## Defects found while testing, still open
- Unresolved: on the owner's real profile, the automatic "ready" notice for PR #15 was logged as sent and did
  not arrive (the test notice and hand-run sends did); the next one keeps Hermes's answer to tell where it went.
- A change bounced by the review whose agent ends the turn without changing it stays "bounced 1/3": no notice to
  the owner until the limit, which a refusing agent never reaches.
- The Desktop pane can disappear from the layout and not return until the app is reloaded and the switch toggled;
  the cause was not proven (#22 hardened the plugin; see that pull request's analysis).
- With a running gateway, a slash command typed as the first thing in a CLI session cannot tell the repository and
  asks for it (`/foreman use <path>`).

## Test places (all throwaway)
- `PedValme/foreman-demo` (public): issue #1 open, PR #15 clean fix, PR #3 skipped test, PR #4 loosened assertions.
  PR #2 (morning test) and PR #5 (by mistake, in the evening "no gh" test) were merged and reverted on `main`.
  PRs #6, #7, #12-#14 and branch `t/base` (with the CI workflow) are the evening's throwaway cases.
- A private repository with the owner's voice plugins: PR #6 (skip) and PR #7 (loosened assertions) open.
- On the owner's Hermes machine: profile `foremandev` (English persona and interface set for the video, old persona
  saved beside it; `auto_review: merge`; the two `llm.*` capabilities granted), `~/cart`, `~/foreman-demo`,
  `/tmp/fm-battery*`. Foreman is also installed in the owner's real profile since the Telegram test, with
  notifications on.
- On the development PC: `desktop-plugins/foreman/plugin.js` copied by hand into the Desktop app's folder.
