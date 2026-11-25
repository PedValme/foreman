# Foreman state — 2026-11-24

> Rewritten in full, never appended; kept short.

<!-- pic-method: next-session -->
## Next session
- Done this session (the owner: «vamos con T6 y demás pendientes»): T6 and T6b of `trabajo/agnostico.md`, in four
  pull requests, each reviewed by an agent that did not write it and with CI green on Linux, macOS and Windows.
  Nothing under `plugin/` changed.
  - #74: `/foreman` alone is the board on pi and OpenCode, with `verdict`, `pipeline`, `prs`, `issues` and `use`:
    the Hermes plugin's own `board.py`, run on a stand-in for Hermes's context (`adapters/foreman_hosts/standin.py`).
  - #75: `/foreman merge` and `/foreman reject` on pi, with the review before the merge. Seen in pi's terminal UI:
    throwaway pull request #19 of the demo repository reviewed, confirmed in pi's selector and merged; #20 rejected
    and closed; both refused with nobody attending.
  - #76: the review at the end of every turn, only where the person turns it on (`reviewer every-turn on`): Claude
    Code, Codex and pi. Seen on pi: a loosened assertion was sent back once and the agent restored it.
  - #77: OpenCode's TUI plugin (`adapters/opencode/tui.ts`, installed as a folder): `/foreman` typed in the TUI,
    replies in a dialog, merge and reject there only. Seen: throwaway pull request #21 merged from the TUI.
- Next action: T7, which starts with the owner's answers (names of the packages, where each adapter is published,
  what the root README says); then the one Hermes catalog update. `trabajo/agnostico.md`, "Next step", lists both
  and what an agent can do meanwhile without him.
- Decided on 2026-11-24 (DECISIONES): the public name in every store is `foreman-gate`, and `foreman` stays as the
  command, the plugin's name inside Claude Code, OpenCode's plugin id and the Hermes catalog entry. Done for it,
  with nothing published: a root `package.json` under that name (pi's manifest, OpenCode's entrypoints), the Claude
  Code marketplace renamed, a Codex plugin manifest (`.codex-plugin/`: Codex 0.171.0 also reads `.claude-plugin/`
  and was installing Claude Code's hooks). Each installation was seen from a local git server into a redirected
  configuration directory: pi (`pi install git:…`, the board with no model turn), OpenCode (`opencode plugin add
  git+https://…`, both parts and the TUI dialog), Claude Code (marketplace add, install, enabled; no session, it
  needs a login) and Codex (installed, and `foreman help` answered by its dialect). Then the same commands were
  run against GitHub (#80 merged), each into a temporary configuration directory: the four installed it. The root
  README announces the adapters since the owner's «ok al readme» (#81). Each harness's README has what was seen.
- Next for publication, each with the owner's yes and none given yet: `npm publish` as `foreman-gate` (his npm
  account), which lists it in pi's catalog; the pull request to OpenCode's ecosystem page; Anthropic's directory
  for Claude Code (it wants an icon and has a review); the focused issue to Hermes for a public accessor of the
  terminal's directory (text shown to him first).
- With the owner, open (asked on 2026-11-24; he wanted both evaluated before deciding, and they were, read-only):
  - Where to publish. Read in each harness's documentation and help, not tried: pi installs from git with a root
    `package.json` (`pi install git:…`) and lists in its catalog any npm package with the keyword `pi-package`;
    OpenCode has no store, `opencode plugin add github:…` (the entrypoints a `package.json` must name were not
    confirmed) and an ecosystem page kept by pull request; Claude Code: this repository is already its own
    marketplace (`.claude-plugin/marketplace.json`), and Anthropic's directory takes submissions with a review;
    Codex has git marketplaces, but its public directory excludes plugins with hooks. On npm, `foreman` and
    `opencode-foreman` are other people's packages. His to decide: the name, npm or not, each submission.
  - The first Hermes seam (a public accessor for the terminal's directory). Checked upstream: v0.23.0 to v0.23.4
    do not add it, the private function is unchanged, no roadmap was found; #153841's "not planned" was a triage
    of its security label, and its maintainer asked for one focused issue or a pull request against
    `hermes_cli/data/plugin_api.json` per seam (#148311, the same kind of request, was completed). Foreman still
    needs it: it is the only source that follows the agent's `cd` between terminal calls.
- External PR #57 (`***REDACTED***` as a placeholder in the detector): no push from its author since the changes
  asked on 2026-11-23. When it comes: re-read the whole diff, approve its held CI run, then decide the merge.
- Hermes: Foreman is in its catalog at the pin ce9b01a (NousResearch/hermes-agent#153851); a plugin change reaches
  users only through the one substantial catalog update, tried first in the `foremandev` profile (DECISIONES,
  2026-11-22 and 2026-11-24). First place in the Hermes Agent Plugin Hackathon; promotion is another project's.
- What waits for Pedro lives in OmniBrain: `omnibrain_esperas` with repo `foreman`, or «Te espera» in the panel.

## Delivered
- The Hermes plugin, version 0.1.0, in `plugin/`, listed in the Hermes catalog; CI on Linux, macOS and Windows.
- In Claude Code, Codex, pi and OpenCode (`adapters/`, `package.json`, `.claude-plugin/`, `.codex-plugin/`),
  installable from this repository as `foreman-gate` and announced in the root README; in no store yet: the gate,
  the person's commands and the review on request; on pi and in OpenCode's TUI also the board, merge and reject;
  in Claude Code, Codex and pi the review at the end of every turn when turned on.
- `PedValme/foreman-demo` (public) as the demo repository; the README as one page with the real capture and the GIF.

## In progress
- Foreman for any harness: of T7, the name, the packaging and the README are done; the stores (npm, OpenCode's
  page, Anthropic's directory) and the one Hermes catalog update are left, each with the owner's yes.

## Next steps
1. T7 and the one Hermes catalog update (`trabajo/agnostico.md`, "Next step"; `trabajo/model-picker.md`).
2. Without the owner: the per-turn review seen in a real Claude Code and Codex session; OpenCode's end of turn
   given the long wait so the per-turn review can be offered there; a rejection and `allow` seen in OpenCode's TUI.
3. Propose the Hermes seams one by one (#153841's advice): first the terminal cwd accessor.
4. Clean up the rest of the hackathon's throwaways, with the owner's yes: `~/cart`, `~/foreman-demo` and
   `/tmp/fm-battery*` on the owner's Hermes machine; the unpushed local branch `claude/minimal-child-env` (kept as
   `windows/claude/minimal-child-env` in one clone). Done on 2026-11-24 with his «ok»: the demo repository's
   pull requests #6, #7, #12, #13, #14 closed and its `t/*` branches deleted (it keeps #3, #4 and #15).
5. Whether the private voice-plugins test repository becomes a project; whether only the owner merges here;
   register the demo repository in the owner's environment as outside the factory.

## Known issues
- Unresolved (adapters, every harness): Foreman's hooks and state are files the agent's shell can reach, guarded
  against the plain attempt and not a disguised one; a second agent started without Foreman is outside the gate;
  when the adapter cannot run (no `python3`) the harness goes on without the gate and shows the error. The required
  check in CI stays the independent control. Not tried on Windows in a real session in any of the four.
- Unresolved (adapters): the end-of-turn nudge lists every blocker in the working tree, the person's own
  uncommitted ones included, as the Hermes gate does.
- Unresolved (merge outside Hermes): the command runs twice (ask, then answer), so that merge's gate, review and
  "waiting" lines are twice in the pipeline, and a review that failed on the first run is tried once more on the
  second (minutes again). A program driving pi's RPC mode counts as a person, for merge too.
- Unresolved (the review at the end of every turn): it stops for one change after three send-backs or four reviews
  and, in Claude Code and Codex, nothing shows that change waiting (only `reviewer` states the limits); when the
  gate's own nudge came first, the third review's result is recorded as a bounce the agent never receives; seen
  only on pi; not offered in OpenCode (its end-of-turn hook stops waiting after 30 seconds).
- Unresolved (OpenCode): plugin code the agent plants in a plugin folder is loaded with the TUI plugin's powers
  (read, not seen); keys typed into the terminal from the agent's shell look like a person's; the desktop app is
  not covered by the TUI plugin; with OpenCode's background service the agent's shell can reach `opencode api` and
  so answer a permission prompt or call the server `/foreman`, which weakens the server path's `allow` (read, not
  seen); a reply longer than the terminal is cut off in the dialog; the end-of-turn nudge depends on a hook
  OpenCode marks experimental; a rejection and `allow` through the TUI were tested, not seen.
- Unresolved (Claude Code): the person's commands carry Claude Code's own frame ("UserPromptSubmit operation
  blocked by hook"); an installation through the marketplace was not tried; the default reviewer is the account's
  default model, which may not be the session's.
- Unresolved (Codex): allowing a finding is not available, and the reviewer and the per-turn review are set in a
  file, not from a prompt; `codex exec` prints nothing when the hook answers the person's command, and the
  interactive terminal was not tried; subagents not verified; no Codex plugin yet, the hooks are installed by hand.
- Unresolved (pi): a tool from another extension or an MCP server that runs commands is not inspected. pi and
  OpenCode cannot hold a model to a schema: a review's answer without that request's seal is "could not run".
- Unresolved (Hermes): the Desktop pane can disappear from the app's layout until the app is reloaded (#22); with a
  running gateway, a slash command typed first in a CLI session cannot tell the repository (`/foreman use <path>`
  is the way around); one guarded private import makes `hermes plugins validate` warn; a pushed notification cannot
  carry buttons, Hermes shows no approval prompt for a plugin's command.
- Unresolved (Hermes plugin; fixed in the adapters, not in `plugin/`): a finding the review verified keeps the line
  breaks of its `title`, `why` and `fix`, so a diff that steers the reviewer can make `/foreman review` print a
  line that reads as Foreman's own. One line in `review.verify`, for the catalog update.
- Unresolved (Claude Code, Codex): with the harness's home moved (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`) the installed
  copy is guarded, but a write to the settings file in that moved home that disables the plugin is not recognised
  (the guards know `~/.claude` and `~/.codex`). OpenCode: `opencode plugin list` and `plugin update` misreport an
  installed git package (seen; remove and add again).
- Unresolved (core, Windows; found by CI on 2026-11-24): `board.candidates` compares directories by spelling, so a
  process started in a folder under its short name (`RUNNER~1`) lists one repository twice in `/foreman use`.
  Compare canonical paths, at the catalog update.
- Unresolved (debt from the reviews): state files are plain files behind a best-effort guard; a SARIF report
  replaced by a separate command is not noticed; `include`d makefiles and a new `GNUmakefile` are not covered; a
  merge through `gh api` or a direct push to the base branch is not blocked; the real-panel behaviour test runs only
  where node, React and jsdom are installed (CI skips it).
- Unresolved: the deterministic detector does not see a loosened assertion or an emptied test; only the review
  does. In Hermes, a change bounced by the review whose agent ends the turn without changing it stays "bounced
  1/3", with no notice to the owner (the notice comes only at the limit).
