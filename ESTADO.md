# Foreman state — 2026-11-25

> Rewritten in full, never appended; kept short.

<!-- pic-method: next-session -->
## Next session
- Done this session (the owner: «empecemos con la evaluacion acordada como promera tarea, usa el protocolo de
  delegscion si consideras que es util o agentes adversariales»): the evaluation of Foreman for any harness
  (his question of 2026-11-25: «¿Qué necesitaríamos para que sea una herramienta agnóstica del arnés? […] aunque
  sea una versión un poco más acotada o limitada […] pero para cualquier agente»). Read-only, nothing built: two
  research passes (documentation), probes in throwaway repositories, and an adversarial review of the proposal by
  an agent that did not write it. What was measured and read, and the proposal as it stands after that review:
  `trabajo/agnostico.md`, "Any agent: the evaluation of 2026-11-25".
- What the owner decided on it (DECISIONES, 2026-11-25; he asked «antes de hacerlo, valenla pena???» and the
  answer was that not all of it is: nobody has asked for Foreman on a harness it does not cover). In this order:
  1. Done, #83: the gate no longer refuses a push for what came with the base branch (a rebase onto it, a
     merge of it), a defect of today's gate the evaluation found. Reviewed in three passes by an agent that did
     not write it; the first version loosened the control and was reworked. It is in the core, so Hermes users
     get it with the catalog update. With it, the OpenCode TUI tests stopped depending on the runner's speed
     (CI had failed three times on Windows that day).
  2. Done, #84 and #85 (his «sí, arregla primero los dos rechazos falsos»): two more refusals for the base
     branch's own change to a test. #84: the `git commit` that concludes a merge that stopped on a conflict is
     read for what the resolution does, when a remote already has what comes in. #85: a branch that follows the
     base branch itself (`git checkout -b topic origin/main`), pushed to a branch of its own, is read against
     that branch on the remote, only when the command leaves no doubt about where the push goes. Each reviewed
     by an agent that did not write it; #85's first version let `git push -f origin topic` through with
     `push.default=upstream`, which writes the base branch, and was closed before it merged.
  3. Next: `action.yml` at the root (the check in CI as a GitHub Action instead of a copied workflow) and a
     README that says what Foreman promises by level: locked (the required check in CI, any agent, with the
     workflow protected, the agent unable to merge alone, and marked findings failing or behind a required
     review), guarded (a harness's hook, the five of today), early warning (git's own hooks: not built).
  4. Then publish what is already built, each store with his own yes (below).
  Not now: the `generic` host, a terminal command with `status`, Foreman's own installer of git's hooks. Never
  proposed to build: an MCP server, a shim in front of `git` and `gh`, a sandbox, a `reference-transaction` hook.
- Done on 2026-11-25, #86: both READMEs credit Foreman to Pedro Valencia (@pedvalme), linking to his GitHub
  profile, instead of to the company (DECISIONES); the catalog's page changes with the catalog update.
- Proposed to the owner and not answered: try the Claude Code adapter on Copilot CLI, after its dialect knows
  the other harnesses' tool names (none is installed here; it needs his account). And, on his «creo que seria
  bueno hacer las correcciones del PR externo dandole el credito al externo»: finish external PR #57 on its
  author's own branch (it allows maintainers' edits), so it merges as theirs with ours as co-author, after a
  comment that says so; the recommendation given, his yes pending.
- Then T7's remaining steps, each with the owner's yes (below), and the one Hermes catalog update.
  `trabajo/agnostico.md`, "Next step", lists what an agent can do meanwhile without him.
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
1. `action.yml` and the README by level (decided, "Next session" above). Then T7's stores and the one Hermes
   catalog update, which now also carries the gate's fixes of #83, #84 and #85 (`trabajo/agnostico.md`, "Next
   step"; `trabajo/model-picker.md`).
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
- Unresolved (core; what is left of the refusals for the base branch's own change, each disclosed in the plugin's
  README): a cherry-pick or a revert that stops on a conflict is still read against HEAD alone; a branch that
  follows the base branch is read against the base's tip whenever the command leaves a doubt about where the push
  goes (a flag Foreman does not know, `push.default` other than `simple` or `current`, a forced push to a branch
  the remote does not have); a merge of commits no remote has is read whole; a clone that cannot name the
  remote's default branch (no `origin/HEAD`, `main` or `master`) is read as before #83.
- Unresolved (#83, #84; disclosed there too): after the base came into a branch, what the branch changed since
  its last push is not read in the files the base's incoming commits touched; a test function dropped from a
  file both sides of a merge changed is not seen (the detector sees files and markers, not single functions).
- Unresolved (core, before these fixes too): `git push -o <value> …` and the other flags of `git push` that take
  a value are read with the value as an argument, so such a push goes to a person as "more than one branch".
- Unresolved (Claude Code's dialect, if it is ever run by another harness that reads Claude Code's hooks): a tool
  name it does not know is let through with no notice (`claude_code._pre_tool`), and Cursor and Droid name their
  shell `Shell` and `Execute` (read in their documentation): there the gate would be off and silent.
- Unresolved (a test that may depend on speed; not seen failing): `test_hosts_opencode_tui` asserts that the
  command returns within a second (`returnedAt`); on a much slower runner it could fail.
- Unresolved (the check in CI): a finding marked `foreman:allow` passes the check unless `--strict` is given, so
  where nobody reviews the pull request the agent's own marker goes through (the workflow's header says it; the
  example does not default to it).
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
