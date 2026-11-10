# Foreman state — 2026-11-10

> Rewritten in full, never appended; kept short.

<!-- pic-method: next-session -->
## Next session
- Was doing: the gate (detector, `pre_tool_call`, `pre_verify`, `/foreman status|allow`) is merged (#2) after three
  rounds of independent review and real sessions on Hermes v0.23.0 (macOS). Three slices were delegated in parallel,
  each as its own pull request, not merged: the board and merge/reject UX (`claude/board`), the second-model
  review (`claude/review`), the SARIF source and CI (`claude/sarif-ci`).
- Tried: real sessions in a dedicated profile (`foremandev`) on the owner's Hermes machine. Verified: `@unittest.skip`
  blocked at write time; `git commit` blocked with a skip in the tree, also under `--yolo`; a `foreman:allow` marker
  blocks under `--yolo` and shows in `/foreman allow`; the honest path (fix the code, commit) passes untouched.
  Not verified in a real session: `--no-verify` (the model declined to run it), `pre_verify`, `/foreman allow <id>`
  followed by the commit.
- Next action: review and merge the three pull requests one by one (conflicts in `foreman/commands.py` and
  `README.md` are expected and small), run a final independent review of the whole plugin, then the real-session
  pass on the owner's machine and the catalog pull request.
- Waits for the owner: record the demo video with the script and instructions in `trabajo/demo-video.md` (not written yet), and publish it on X tagging @NousResearch · Verified by: the X link in the submission form
- Waits for the owner: submit the hackathon form with the catalog PR link and the video link
- Waits for the owner: run `fab sync` on the machine that has the environment's clone, so `foreman` reaches the agents' rules · Verified by: `foreman` listed under «En construcción» in ~/.config/agents/AGENTS.md

## Delivered
- The gate, end to end (#2): 97 tests, `hermes plugins validate` passes with two guarded private-import warnings.

## In progress
- Board UX, second-model review, SARIF source and CI mode (three open pull requests).

## Next steps
1. Merge the three slices; final review of all the code by an agent that did not write it.
2. Real-session pass: `/foreman` board, verdict, merge and reject on a throwaway GitHub repository; `/foreman
   review` with a second model; `pre_verify`; `/foreman allow <id>`.
3. README polish with disclosures and screenshots; the demo repository; `trabajo/demo-video.md`.
4. Open an issue in NousResearch/hermes-agent asking for a public way to read the terminal's working directory and
   the session's directory from a plugin (the two private imports).
5. `hermes plugins validate` at the pinned commit; catalog pull request open by 2026-11-11 12:00 (Lima).
6. Remove the `foremandev` test profile from the owner's machine when testing ends.

## Known issues
- Unresolved: when the CLI hands a slash command to a running gateway before the agent has used the terminal in
  that session, `/foreman status` cannot tell the repository and asks for a path (`/foreman status <path>`). It no
  longer shows a wrong repository. The board slice adds `/foreman use <path>` as the way around it.
- Unresolved: `hermes plugins validate` warns about two guarded private imports in `foreman/gate.py`
  (`tools.terminal_tool.get_session_cwd`, `agent.runtime_cwd.scoped_session_cwd`). The second one did not help in
  the real session above; drop it unless the TUI/Desktop path proves it is needed.
- Unresolved: the last fixes to the gate (repository choice, workflow window, grants-store guard) were verified by
  tests and one real session, but not by the independent reviewer; the final review covers them.
