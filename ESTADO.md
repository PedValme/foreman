# Foreman state — 2026-11-09

> Rewritten in full, never appended; kept short.

<!-- pic-method: next-session -->
## Next session
- Was doing: every planned slice is on `main` — the gate (#2), the second-model review (#7), the board with
  merge and reject (#6, #8), the SARIF source and CI (#4). `main` is protected (pull request and the seven CI
  checks required). A small fix is in flight: `/foreman review` must use the repository pinned with `/foreman use`.
- Tried, in real sessions on Hermes v0.23.0 (macOS) in a dedicated profile: the write gate and the commit gate
  block a skipped test (also under `--yolo`); a `foreman:allow` marker blocks and shows in `/foreman allow`; the
  honest path passes; `/foreman review` with a real model caught a loosened assertion and a swallowed exception;
  on a private test repository the board, both verdicts, a refused merge, a real rejection comment and a real
  confirmed merge (which closed its issue) all worked.
- Not verified in a real session: `--no-verify` (the model declined to run it), `pre_verify`, `/foreman allow <id>`
  followed by the commit, the review on a second model (the capability is granted only from an interactive
  terminal), the pick question of `/foreman merge` answered by a person, the SARIF path with a real hermes-security
  export, enabling the plugin in the middle of a session.
- Next action: the final independent review of the whole plugin, then README polish, the demo example and
  `trabajo/demo-video.md`, the issue to Hermes, `hermes plugins validate` at the pinned commit and the catalog
  pull request.
- Waits for the owner: grant the second-model capability on his Hermes machine from an interactive terminal (`hermes -p foremandev plugins enable foreman`), to try the review on his fallback model
- Waits for the owner: record the demo video with the script and instructions in `trabajo/demo-video.md` (not written yet), and publish it on X tagging @NousResearch · Verified by: the X link in the submission form
- Waits for the owner: submit the hackathon form with the catalog PR link and the video link

## Delivered
- The gate, the board (use, prs, issues, verdict, merge, reject), the second-model review, the SARIF source, CI
  mode and this repository's CI on Linux, macOS and Windows.

## In progress
- `/foreman review` using the pinned repository (pull request open by its author agent).

## Next steps
1. Final review of all the code by an agent that did not write it; fix what it finds.
2. README: one coherent pass (it grew by slices), screenshots, the before-and-after example.
3. `examples/cart/`: the small failing-test project for the video; `trabajo/demo-video.md` with the script, the
   exact commands and the recording instructions. Check that the gate acts in the same session after
   `hermes plugins install`.
4. Issue in NousResearch/hermes-agent asking for a public way to read the terminal's and the session's working
   directory from a plugin, and for an approval prompt a plugin can request.
5. `hermes plugins validate` at the commit to pin; catalog pull request open by 2026-11-11 12:00 (Lima); the form.
6. Remove the `foremandev` profile and the temporary clones from the owner's machine when testing ends.
7. After the submission, ask the owner whether the private Token Plan repository becomes a project of its own.

## Known issues
- Unresolved: when the CLI hands a slash command to a running gateway before the agent has used the terminal in
  that session, Foreman cannot tell the repository and asks for it; `/foreman use <path>` is the way around.
- Unresolved: `hermes plugins validate` warns about two guarded private imports in `foreman/gate.py`. The second
  (`agent.runtime_cwd.scoped_session_cwd`) did not help in the real session where it was tried.
- Unresolved (debt from the reviews): the grants and pin files are protected by a best-effort guard, not signed;
  a SARIF report replaced by a separate command is not noticed; a SARIF result with no location is only a note
  under the default scope; the message on a SARIF timeout says "reading the diff".
- Unresolved: the deterministic detector does not see a loosened assertion or an emptied test; only
  `/foreman review` does. It is stated in the README's known limits.
