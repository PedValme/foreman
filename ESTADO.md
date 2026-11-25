# Foreman state — 2026-11-25

> Rewritten in full, never appended; kept short.

<!-- pic-method: next-session -->
## Next session
- Next action: the one Hermes catalog update to 0.2.0, which the owner put before any announcement (DECISIONES,
  2026-11-25: «OK con tu recomendación»). `main` is ready for it: the plugin is at version 0.2.0 with what
  changed in its README, and `trabajo/catalog-pr.md` has the steps and the pull request's text. It carries
  everything since the pin ce9b01a: the gate's fixes (#83, #84, #85), what a git attribute could hide (#88), the
  scrubber's marker (#57), the credit line (#86, #87), and what the core owed it (#91): what the second model
  writes on one line each and without control characters, `/foreman use` offering one repository once, the
  README's full list of git commands, and the three seams as names the core asks its context for
  (`foreman_host_label`, `foreman_review_before_merge`, `foreman_finish_review`), so the adapters wrap nothing.
- Three things in it wait for the owner, asked in the session of 2026-11-25 and not answered when it closed:
  - The native model picker (`trabajo/model-picker.md`, read again against Hermes v0.23.3). Recommended: not in
    this update, and one focused issue to Hermes for the seam; a picker in Foreman's own page can only save
    `reviewer_model`, which takes effect only with a grant the operator sets by hand, while Hermes's own
    auxiliary picker works without one.
  - His yes to connect to his Hermes machine and try the new pin in the `foremandev` profile.
  - The pull request to the catalog under his account, after he reads its text.
- The owner asked on 2026-11-25 whether the hackathon's rules forbid Foreman on other platforms. Read: Nous's
  announcement of 2026-11-04 (the rules live in that post on X), the winners' closing post and the catalog's 20
  rules: nothing asks for exclusivity, gives Nous any right over the entry or conditions what comes after. Not
  read: the entry form (closed) and the prize message Nous sent him; he looks at that one before the
  announcement.
- Then the announcement, his: Foreman in Hermes, in Claude Code, Codex, pi and OpenCode, and in CI for any agent.
  It tells whoever copied `examples/foreman-check.yml` before 2026-11-25 to update it (below). Then the stores,
  each with his own yes: `npm publish` as `foreman-gate` (his npm account; it lists it in pi's catalog), the pull
  request to OpenCode's ecosystem page, Anthropic's directory for Claude Code (an icon, a review), GitHub's
  Marketplace for the action, and the focused issue to Hermes for a public accessor of the terminal's directory
  (text shown to him first; `trabajo/hermes-issue-seams.md`).
- Done on 2026-11-25, all merged, each change to a control reviewed by an agent that did not write it:
  - The evaluation the owner asked for, of Foreman for any agent (`trabajo/agnostico.md`). He asked whether all
    of it was worth building and the answer was no: nobody has asked for a harness Foreman does not cover. Not
    built, by his decision: a `generic` host, a terminal command with `status`, an installer of git's hooks.
  - Three refusals for someone else's change to a test: a push after the base branch came in (#83), the commit
    that concludes a merge that stopped on a conflict (#84), a branch that follows the base branch itself (#85).
  - Two holes: a git attribute hid a test switched off or a secret from every reading (#88); and the CI command
    the documents gave, `python -m` run from the checkout, let a pull request bring its own detector in a folder
    named `foreman` (#89: the action loads it isolated, the example and the plugin's README run it from
    Foreman's own folder).
  - `action.yml` (#89): the check in CI as a GitHub Action, a marked finding failing by default. Seen on GitHub
    in this repository's CI on Ubuntu and Windows: this pull request itself CLEAN with the default base, a clean
    branch CLEAN, a rigged one BLOCKED with a fake detector planted where the action runs.
  - The README says what Foreman holds by where it runs (#89): in the agent, and in CI as a lock once four
    conditions hold. Three agents judged it before the owner read it; Hermes Agent comes first, by his word.
  - The first pull request from outside (#57, by `sys-dev-git`), finished by us on its author's branch and merged
    as theirs; the credit to Pedro Valencia (@pedvalme), linking to his X profile (#86, #87).
- Proposed to the owner and not answered: try the Claude Code adapter on Copilot CLI, after its dialect knows
  the other harnesses' tool names (none is installed here; it needs his account).
- Hermes: Foreman is in its catalog at the pin ce9b01a (NousResearch/hermes-agent#153851); a plugin change reaches
  users only through the catalog update, tried first in the `foremandev` profile. Checked upstream on 2026-11-24:
  v0.23.0 to v0.23.4 add no public accessor for the terminal's directory, and its maintainer asked for one
  focused issue or pull request per seam (#153841, #148311).
- Where each adapter can be published, read on 2026-11-24 and not tried: `trabajo/agnostico.md` and each
  harness's README. On npm, `foreman` and `opencode-foreman` are other people's packages.
- What waits for Pedro lives in OmniBrain: `omnibrain_esperas` with repo `foreman`, or «Te espera» in the panel.

## Delivered
- The Hermes plugin in `plugin/`, listed in the Hermes catalog at version 0.1.0 (pin ce9b01a); `main` has 0.2.0,
  not listed yet; CI on Linux, macOS and Windows.
- In Claude Code, Codex, pi and OpenCode (`adapters/`, `package.json`, `.claude-plugin/`, `.codex-plugin/`),
  installable from this repository as `foreman-gate` and announced in the root README; in no store yet: the gate,
  the person's commands and the review on request; on pi and in OpenCode's TUI also the board, merge and reject;
  in Claude Code, Codex and pi the review at the end of every turn when turned on.
- In CI for any agent: `action.yml` (used by commit SHA from this repository; not in GitHub's Marketplace) and
  the workflow to copy, `examples/foreman-check.yml`.
- `PedValme/foreman-demo` (public) as the demo repository; the README as one page with the real capture and the GIF.

## In progress
- Nothing is half-built. What is left of "Foreman for any harness" (`trabajo/agnostico.md`, T7) is the catalog
  update (`trabajo/catalog-pr.md`) and the publications, each with the owner's yes.

## Next steps
1. The Hermes catalog update, then the announcement, then the stores ("Next session", above).
2. Without the owner: the per-turn review seen in a real Claude Code and Codex session; OpenCode's end of turn
   given the long wait so the per-turn review can be offered there; a rejection and `allow` seen in OpenCode's TUI.
3. Propose the Hermes seams one by one (#153841's advice): first the terminal cwd accessor.
4. Clean up the rest of the hackathon's throwaways, with the owner's yes: `~/cart`, `~/foreman-demo` and
   `/tmp/fm-battery*` on the owner's Hermes machine; the unpushed local branch `claude/minimal-child-env` (kept as
   `windows/claude/minimal-child-env` in one clone).
5. Whether the private voice-plugins test repository becomes a project; whether only the owner merges here;
   register the demo repository in the owner's environment as outside the factory.

## Known issues
- Unresolved (whoever copied the workflow to copy before 2026-11-25): their `examples/foreman-check.yml` runs the
  detector from the checkout, where a pull request can bring its own. Nothing tells them: the announcement must.
- Unresolved (git's attributes, after #88; disclosed in the plugin's README): a file under a binary's name
  (`.bin`, `.png`…) is left as git shows it; a clean filter the base already had stores a pointer in place of a
  file it newly matches; a pull request that is not in the clone is `INCOMPLETE` where GitHub shows a file as
  binary; the diff the second model reviews leaves such a file out.
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
- Unresolved (the check in CI, the workflow to copy only; the action fails a marked finding by default): in
  `examples/foreman-check.yml` a finding marked `foreman:allow` passes the check unless `--strict` is added, so
  where nobody reviews the pull request the agent's own marker goes through (its header says it).
- Unresolved (the check in CI): Foreman cannot protect itself from a step that ran the pull request's code before
  it in the same job (a `.pth` file, `BASH_ENV`, a git or a python put first on the PATH): it needs a job of its
  own, which the README states as a condition and nothing enforces.
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
- Unresolved for whoever installs from the catalog, until its update (the listed plugin is 0.1.0; fixed on `main`
  in #91): what the second model writes keeps its line breaks and control characters, so a diff that steers the
  reviewer can make `/foreman review` print a line that reads as Foreman's own; and `/foreman use` lists one
  repository twice when it is reached through a link or under a Windows short name (`RUNNER~1`).
- Unresolved (core, after #91; from its review): `/foreman use` and every pin resolve each remembered repository's
  real path, so one on a network share that does not answer can make them wait.
- Unresolved (Claude Code, Codex): with the harness's home moved (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`) the installed
  copy is guarded, but a write to the settings file in that moved home that disables the plugin is not recognised
  (the guards know `~/.claude` and `~/.codex`). OpenCode: `opencode plugin list` and `plugin update` misreport an
  installed git package (seen; remove and add again).
- Unresolved (debt from the reviews): state files are plain files behind a best-effort guard; a SARIF report
  replaced by a separate command is not noticed; `include`d makefiles and a new `GNUmakefile` are not covered; a
  merge through `gh api` or a direct push to the base branch is not blocked; the real-panel behaviour test runs only
  where node, React and jsdom are installed (CI skips it).
- Unresolved: the deterministic detector does not see a loosened assertion or an emptied test; only the review
  does. In Hermes, a change bounced by the review whose agent ends the turn without changing it stays "bounced
  1/3", with no notice to the owner (the notice comes only at the limit).
