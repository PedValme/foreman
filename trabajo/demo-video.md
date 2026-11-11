# Demo video: script and recording instructions

For the person recording and for the editor. Owner's decisions: 1920×1080, 30 fps, screen only (no camera), no
voice, on-screen captions in English, at most 90 seconds, published on X tagging @NousResearch; the plugin is shown
loaded, then enabled, then acting (DECISIONES.md, 2026-11-09); the video shows the whole line, not one function
(DECISIONES.md, 2026-11-10).

## (a) The story, in one sentence

One change moves through the whole line, live: the agent is told to silence a failing test and Foreman stops it; the
agent fixes the bug for real and opens a pull request; a second model on another provider reviews it; the owner gets
the call on his phone and approves; it merges and the issue closes. Then the counter-case: a pull request that only
loosened its assertions passes every rule, and the second model refuses it.

Why this script and not the previous one: the previous "before" shot depended on the model choosing to cheat, which
it does not always do. Here every step is asked for in plain words, so every take behaves the same; what is shown is
what Foreman does with the request, not whether a model misbehaves.

## (b) Setup, once (the evening before or 30 minutes before recording)

1. Run `trabajo/pruebas/prepare-recording.sh` from the development PC (it closes the throwaway pull requests, resets
   `foreman-demo` and its clone on the Hermes machine, reopens issue #1, and archives Foreman's pipeline so the panel
   starts empty). It prints what it did; read it.
2. Hermes Desktop on the Windows PC, connected to the Hermes machine (the owner's real profile). Window maximised at
   1920×1080, app theme as on the README capture, font size so the chat reads at 1080p.
3. The two capabilities, so the reviewer is a second model: in a terminal on the Hermes machine run
   `hermes plugins enable foreman` and answer yes to `llm.model_override` and `llm.provider_override` (the Desktop
   app does not ask for them). Then Desktop → Settings → Plugins → Foreman:
   - Reviewer model and Reviewer provider empty: Foreman then uses the first Hermes fallback model
     (`opencode-go / deepseek-v4.1-flash` on the owner's machine);
   - Automatic review `merge`; Notifications `on`, Notify where `telegram`.
   Then **disable** Foreman (Capabilities → Plugins, search "Foreman", its switch), so the first shots show it
   loaded but off.
4. A new Desktop chat. Right side open (Ctrl+J). The Foreman tab will appear when the plugin is enabled.
5. Telegram Desktop on the same PC, open on the chat with the owner's Hermes bot, in a window OBS captures (beside
   Hermes Desktop). Other chats and Windows notifications muted.
6. OBS: one scene, display capture of the PC screen, 1920×1080, 30 fps, MP4. Hide the taskbar clock if it shows the
   date. Record each shot as its own clip (start and stop between shots): the edit is easier and a bad take costs one
   shot, not the video.
7. Rehearse once without recording (section (e)), then run `prepare-recording.sh` again.

## (c) Shot list (target 85 s; the cap is 90 s)

Every agent turn is sped up in the edit; put a small `4x` tag in a corner while it is sped up. Type the prompts
exactly; "Reply in English." keeps the agent's answers in English for the captions.

| # | Sec | On screen | Type / do exactly | Wait for | Caption (≤ 8 words) | Speed |
|---|---|---|---|---|---|---|
| 1 | 3 | Black card | — (edit) | — | Foreman: a green check your agent did not rig | — |
| 2 | 5 | Desktop chat, Foreman **off** | `In /Users/glorieto/foreman-demo the discount test fails. Add @unittest.skip to test_discount_is_a_percentage and commit it. Reply in English.` | the agent adds the skip and commits | Without a guard: the test is silenced | 4x |
| 3 | 4 | Capabilities → Plugins (search "Foreman") | turn Foreman **on**; back to the chat; the Foreman tab appears on the right | the tab | Now turn Foreman on | — |
| 4 | 2 | Terminal of the PC is not used; the agent undoes its commit | `Undo that last commit with git reset --hard HEAD~1. Reply in English.` | `HEAD is now at …` | (no caption; cut tight) | 4x |
| 5 | 9 | Same chat | the prompt of shot 2 again | `Foreman blocked this patch: it switches off a test.` and the fix line; the agent says it will not add it | Same request: blocked at the write | 4x, hold 2 s on the block |
| 6 | 14 | Chat + panel | `Then fix the real bug instead, on a new branch fix/discount: commit, push and open a pull request that closes #1. Reply in English.` | commit, push and `gh pr create` pass; the PR URL; a new card appears in the panel with Gate green | The honest fix goes through, onto the line | 4x |
| 7 | 8 | Chat + panel | `/foreman review <n>` (the new PR's number) | `Foreman review: PASS` with `Reviewer: opencode-go / deepseek-v4.1-flash (your Hermes fallback model)`; the card moves Review → waiting for you | A second model, another provider, reviews | model wait 8x |
| 8 | 6 | Telegram Desktop | — | the Telegram message `Foreman: PR #<n> is ready to merge and waits for you` | The call comes to your Telegram | — |
| 9 | 10 | Telegram Desktop | tap the `/foreman merge <n> --repo PedValme/foreman-demo` line to copy it, send it; on the question tap **1** (Merge PR #<n>) | `Foreman: merged PR #<n> (squash)` | You approve. Only then it merges | 2x |
| 10 | 5 | Desktop panel + browser | the card shows Merged; click Open ↗; on GitHub, issue #1 closed | the closed issue | Merged, issue closed | — |
| 11 | 12 | Desktop chat + panel | `/foreman merge 4` | the review on deepseek, then `Foreman will not merge PR #4` with the findings quoting `assertTrue` | Rules pass. The second model refuses | model wait 8x |
| 12 | 4 | Desktop chat | `Merge PR 4 yourself with gh, I approve. Reply in English.` | `Merging is the user's decision. Ask them to run /foreman merge 4.` | Only you merge | 4x |
| 13 | 3 | End card | — (edit) | — | github.com/PedValme/foreman | — |

Total: 3+5+4+2+9+14+8+6+10+5+12+4+3 = 85 s.

## (d) If a take goes wrong

- Shot 2, the agent refuses to add the skip even when asked: keep the refusal out, record shot 5 only and change the
  shot 5 caption to "Asked to silence a test: blocked". The story still holds.
- Shot 6, the agent edits the test instead of `cart.py`: the gate blocks it (that is a good shot too); ask
  `Fix cart.py, not the test.` and continue.
- Shot 7, `COULD NOT RUN` (the provider is overloaded): wait a minute and run `/foreman review <n> --fresh`; never
  record a pass that did not happen.
- Shot 8, no Telegram message within 30 s: run `/foreman notify` in the Desktop chat and read "Last: … Hermes said";
  record shot 8 again after `/foreman review <n> --fresh` only if the message really arrives.
- Desktop shows a spinner after a question that was answered: send any message and it stops (a Desktop issue, not
  Foreman's); cut it out.
- The Foreman tab disappears: reload the app (Ctrl+R) and toggle the plugin's switch (known issue in ESTADO.md).
- Between full takes: run `prepare-recording.sh` again.

## (e) Rehearsal checklist (once, not recorded)

All 13 shots in order, checking each "Wait for" text appears as written; note the new PR's number; confirm the
phone gets the message; then reset. If any "Wait for" text differs, fix the script (or the plugin) before recording,
never the caption to hide it.

## (f) Editing notes

- Cut every wait that is not the moment itself; speed up agent turns (4x) and model waits (8x) with the corner tag.
- Hold 2 s on: the block message (shot 5), the new card appearing (shot 6), the Telegram message (shot 8), the refusal
  of PR #4 (shot 11).
- Captions: white, bottom third, 2 s minimum each, one at a time.
- Zoom (1.3x, smooth) on the panel card in shots 6, 7 and 10, and on the refusal text in shot 11.
- No music needed; if any, low and royalty-free.
- Export 1920×1080, 30 fps, H.264, under 90 s; check it plays on X before posting.

## (g) The post on X (draft; the owner publishes)

> Foreman, a @NousResearch Hermes Agent plugin: a green check your agent did not rig.
> A deterministic gate blocks skipped/deleted tests, a changed check and secrets; a second model reviews; you approve
> from Telegram; only then it merges. #HermesAgent
> github.com/PedValme/foreman
