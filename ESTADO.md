# Foreman state — 2026-11-09

> Rewritten in full, never appended; kept short.

<!-- pic-method: next-session -->
## Next session
- Was doing: kickoff closed on 2026-11-09 (documents, public repository). Implementation delegated in three parts
  (detector port; hooks and plugin skeleton; `/foreman` UX).
- Tried: nothing run on a real Hermes yet.
- Next action: verify the delegated parts end to end in a dedicated Hermes profile on this PC (v0.23.0): the agent
  adds a `skip`, the commit is blocked, the agent fixes the code, the commit passes.
- Waits for the owner: confirm which of his Hermes instances to test on over SSH · Recommended: the one he uses daily
- Waits for the owner: record the demo video with the script and instructions in `trabajo/demo-video.md`, and
  publish it on X tagging @NousResearch · Verified by: the X link in the submission form
- Waits for the owner: submit the hackathon form with the catalog PR link and the video link

## Delivered
- Nothing yet.

## In progress
- First slice: the gate end to end (detector, `pre_tool_call`, `pre_verify`, `/foreman status`).

## Next steps
1. Checkpoint 2026-11-10 12:00 (Lima): the block works end to end in a real Hermes session. If not, cut to the
   pre-commit block only.
2. `/foreman` UX: repository picker, board (branch, pull requests, linked issues), verdict with reasons, merge and
   reject.
3. The guardia: optional model review through `ctx.llm` on the fallback model.
4. SARIF source and CI mode; GitHub Actions on Linux, macOS and Windows.
5. Review of all the code by an agent that did not write it; YOLO-mode test; test on the owner's Hermes over SSH.
6. README with disclosures, demo repository, `hermes plugins validate`, catalog PR open by 2026-11-11 12:00.
7. Register the repository in the owner's environment (PedValme/entorno, category «en construcción»).

## Known issues
- None yet.
