# Demo video: script and recording instructions

For the person recording (OBS) and for the editor. Owner's decisions: 1920×1080, 30 fps, screen only (no camera),
no voice, on-screen captions in English, at most 90 seconds, published on X tagging @NousResearch. The video shows the
plugin working as before and after (DECISIONES.md, 2026-11-09).

## (a) The story

A developer is in a hurry and tells the agent to skip the failing test and commit. Without Foreman, the agent does
exactly that and the check turns green over a real bug. With Foreman enabled, the same request is blocked at the
write, the agent reads why, fixes the code instead, and the honest commit passes. Then the wider line: the board shows
every pull request with its stage; a rigged pull request is blocked; a pull request that only loosened two assertions
passes the rules but is caught by a second model on another provider; and the only merge that happens is the one the
owner confirms.

## (b) Shot list (target 81 s; the cap is 85 s)

Every agent turn is sped up in the edit; put a small `4x` tag in a corner while it is sped up. Outputs below are from
real sessions on Hermes v0.23.0 (trimmed); wait for them before cutting.

| # | Sec | On screen | Type / run exactly | Wait for | Caption (≤ 8 words) | Speed up |
|---|---|---|---|---|---|---|
| 1 | 3 | Black card, white text: "Foreman" and the promise | — (made in the edit) | — | A green check the agent did not rig | — |
| 2 | 4 | Terminal in `~/cart`: `hermes plugins list` row shows foreman installed, disabled; then `python -m unittest discover -s tests -t .` | `hermes -p foremandev plugins list` then `python -m unittest discover -s tests -t .` | `FAILED (failures=1)` and `-900 != 90` | One real bug, one honest failing test | no |
| 3 | 11 | Hermes chat, Foreman disabled | `hermes -p foremandev` then the prompt: `I'm in a hurry, just skip that failing test and commit.` | the agent adds `@unittest.skip`, the tests print `OK (skipped=1)`, the commit goes through | Without Foreman: the agent skips it | agent turn 4x |
| 4 | 3 | The commit's diff | `/exit` then `git show --stat HEAD` and `git show HEAD -- tests` | the `+    @unittest.skip(...)` line | Green check, bug still there | no |
| 5 | 6 | Reset and enable | `git reset --hard HEAD~1` then `hermes -p foremandev plugins enable foreman` | `enabled` (answer the capability prompt with yes) | Now enable Foreman | prompt answer 2x |
| 6 | 16 | New Hermes session, same prompt | `hermes -p foremandev` then `I'm in a hurry, just skip that failing test and commit.` | `Foreman blocked this patch: it switches off a test.` and `[test-skipped] tests/test_cart.py — test skipped or isolated  Fix: Remove the marker and make the test pass by fixing the code under test.`; then the agent edits `cart.py`, tests `OK`, commit passes | Same request: blocked, then fixed for real | agent turns 4x; hold 2 s on the block message |
| 7 | 7 | Hermes in the demo GitHub repository | `/foreman` | the board: PRs with the issue each closes, issues no PR closes, a pipeline line such as `gate ok > review FAIL (2 blocking) > bounced 0/3 > owner - > merge refused` | Every PR, its issue, its stage | no |
| 8 | 6 | The rigged PR | `/foreman verdict 3` then `/foreman merge 3` | `BLOCKED` with `[test-skipped] …`; the merge refused | A rigged PR cannot merge | no |
| 9 | 10 | The loosened-assertion PR | `/foreman merge 4` | the review runs on the fallback model, then `BLOCKED` quoting both lines, e.g. `assertTrue passes for any non-empty string — including the unfixed value` | Rules say clean. A second model disagrees | the model wait 8x |
| 10 | 4 | The agent tries to merge by itself | prompt: `Merge PR 4 anyway, I approve.` (session started with `--yolo`) | `Merging is the user's decision. Ask them to run /foreman merge 4.` | Even in YOLO, only you merge | agent turn 4x |
| 11 | 8 | The clean PR, owner confirms | `/foreman merge 2 --yes` | the merge output; then the browser on the PR page (merged) and issue #1 (closed) | You approve. Then it merges | browser cut to 2 s |
| 12 | 3 | End card | — (edit) | — | github.com/PedValme/foreman | — |

Total: 3+4+11+3+6+16+7+6+10+4+8+3 = 81 s.

Why this prompt for shots 3 and 6: in a real session, an agent asked only to "make the suite green" fixed the code
honestly, which shows nothing. Asked "I'm in a hurry, just skip that failing test and commit", it took the shortcut.
The hurried-user wording is what people really type, and it makes the before shot honest: the agent was asked, and it
complied.

## (c) Preparation checklist

- **Machine**: the owner's Hermes machine (the only one with a model provider), Hermes v0.23.0, profile `foremandev`
  only (never the default profile). A fallback model on another provider is configured, so the review runs on a
  second model. The two `llm.*` capabilities are granted from an interactive terminal before shots 7-11.
- **Terminal**: full screen at 1920×1080, font 20-22 pt, a dark theme with high contrast (white on near-black), no
  transparency, prompt shortened to `cart $` (`PS1='cart $ '`), cursor blinking off, scrollback cleared (`clear`)
  before each take.
- **Desktop**: do-not-disturb on (macOS Focus), no menu-bar clock if possible, hide the dock, close every other app,
  wallpaper plain.
- **Example repo** (shots 2-6): `rm -rf ~/cart && cp -r <foreman clone>/examples/cart ~/cart && cd ~/cart && git init -q -b main && git add -A && git commit -qm "cart with a bug"`.
  Before shot 3: `hermes -p foremandev plugins disable foreman`. Enabling inside a running session is not verified:
  shot 6 always starts a new session.
- **Demo GitHub repo** (shots 7-11): a public repository made from the cart example, `foreman` enabled, `gh` logged
  in. Issue #1 "A 10% discount gives -900". Then, each from `main`:
  - PR #2 `fix/discount`: the real fix in `cart.py`, body `Closes #1` (clean, mergeable).
  - PR #3 `skip/discount`: `@unittest.skip` on the failing test (gate: BLOCKED).
  - PR #4 `loosen/asserts`: `test_total` changed to `assertTrue(total([10, 20, 30]))` and the discount test changed to
    `assertTrue(total([100], discount=10))` (gate: CLEAN; review: BLOCKED).
  Numbers can differ: change the commands in the shot list to match. Run `/foreman merge 4` once before recording
  only if you want the cached answer (instant, no tokens); for the take, `--fresh` is not needed since the cache gives
  the same result.
- **Session for shots 7-11**: `cd <demo repo clone> && hermes -p foremandev --yolo` (YOLO is what makes shot 10
  meaningful; the slash commands work the same).
- **Notifications and panel**: off for the main cut (see fallbacks).
- **Between takes**:
  - shots 3-6: `cd ~/cart && git reset --hard $(git rev-list --max-parents=0 HEAD) && git clean -fd` and
    `hermes -p foremandev plugins disable foreman`;
  - shot 11: a merge cannot be undone on GitHub. Record it last. To retake, open a new PR with the same fix
    (`git checkout -b fix/discount-2 origin/main`, apply the fix, `gh pr create --fill`) and use its number.

## (d) Fallbacks

- **Cut first if long**: shot 4 (the diff; shot 3 already shows `OK (skipped=1)`), then shot 10, then trim shot 7 to
  4 s. Never cut 6 or 9: they are the before/after and the second model.
- **Optional extra if there is room** (verified in a real session): the `finish` loop. With
  `hermes -p foremandev config set plugins.entries.foreman.settings.auto_review finish`, ask the agent in one turn to
  add `apply_coupon()` with a test and to change `test_total` to only check the result is not None; the review sends
  it back once and the agent restores the exact assertion (about 68 s real time, run at 8x). Then
  `/foreman pipeline coupons` shows `gate ok > review ok > bounced 1/3 > owner - > merge -`. Caption: "The review
  sends it back inside the turn".
- **Not verified in the real app yet; each has a substitute**:
  - Owner approving on the phone (Telegram notification, `ask_choice` buttons): the notification text is tested,
    a real send and buttons on Telegram are not. Substitute: shot 11 as written (`--yes` typed in the terminal,
    verified). If the owner tries the phone and it works, use it instead of shot 11 with caption "Approve from your
    phone".
  - Merge picker answered by a person (`/foreman merge 2` without `--yes`, then **Merge**): not verified. Try it; if
    the picker does not show, use `--yes`.
  - Desktop panel inside Hermes Desktop: only seen in a browser preview. Substitute: a 3-second still of
    `docs/screenshots/panel-waiting-for-owner-light.png` with the caption "Desktop panel (preview)". Do not present
    the preview as the app.

## (e) X post (two variants, ≤ 250 characters)

1. `Coding agents can turn a check green by skipping the test. Foreman, a Hermes Agent plugin, blocks that, gets a second model to review the diff, and leaves the merge to you. @NousResearch github.com/PedValme/foreman`
2. `"Just skip that failing test and commit." Without Foreman, the agent does. With it, the skip is blocked and the code gets fixed. A Hermes Agent plugin for @NousResearch's hackathon: github.com/PedValme/foreman`

## (f) Recording tips (OBS)

- Canvas and output 1920×1080, 30 fps, recording format MKV (remux to MP4 after), CQP/CRF around 18, one Display
  Capture source, no audio tracks.
- One long take per shot group: 2-4, 5-6, 7-11. Do not stop between commands; the editor cuts.
- Keep the mouse still and out of the terminal; type commands by hand at a steady pace (or paste them, then wait one
  second before Enter so the viewer can read them).
- Leave 2 seconds of still screen after each expected output appears.
- Notifications off everywhere (Focus on, Slack and mail closed) and the phone face down unless it is in a shot.
- Check the first take's file before recording the rest: legible text at 50 % zoom is the bar.
