# Foreman state — 2026-11-24

> Rewritten in full, never appended; kept short.

<!-- pic-method: next-session -->
## Next session
- Doing: Foreman for any harness (DECISIONES, 2026-11-24; plan, what each harness gives and the task list in
  `trabajo/agnostico.md`). The gate now runs in Claude Code, Codex, pi and OpenCode from the same core as the Hermes
  plugin: pull requests #61 (the host-neutral half and Claude Code), #62 (one entry point, the protocol for a
  harness whose extension is code, patches), #63 (pi), #64 (Codex) and #65 (OpenCode), each seen in real sessions
  on macOS and reviewed twice by agents that did not write it, with nothing blocking in any pass. Nothing under
  `plugin/` changed. `adapters/README.md` compares the four; each harness's README says what was seen, what was only
  read and its limits.
- The reviewer is in the four too (the owner, 2026-11-24: «sigue con el revisor en los cuatro»): #67 (the
  host-neutral half, `foreman_hosts/reviewer.py`: the plugin's `review.py` unchanged, its model call replaced by a
  fresh session of the harness itself, started by Foreman; and Claude Code), #68 (Codex), #69 (pi), #70 (OpenCode).
  Each seen in a real session: a loosened assertion the gate calls CLEAN came back BLOCKED with the line quoted,
  and asked again it returned the stored result. It runs when the person asks (`review`), on the model and effort
  the person chooses (`reviewer`); `adapters/README.md`, "The review in the four", says what differs in each.
- Next action: T6, `/foreman` complete on pi and OpenCode (`trabajo/agnostico.md`, "Next step" says where to
  start), and with its `/foreman merge` the review at merge time; then the per-turn loop where the user turns it on
  (both are the owner's decision of 2026-11-24 and are not built outside Hermes yet). T7 (READMEs, names,
  publication and the one Hermes catalog update) is with the owner.
- For the owner, his call: trying an adapter in his own harness. It goes into his own setup, and installed for
  every project the gate also refuses his agents' own `gh pr merge`, which his other repositories rely on: per
  project, or loaded for one session (`claude --plugin-dir`, `pi -e`, `codex -c hooks.…`, a link in one project's
  `.opencode/plugins`), first. Allowing a finding in Codex stays unavailable until someone tries its interactive
  terminal in a folder Codex trusts, which writes to `~/.codex`.
- External PR #57 (`***REDACTED***` as a placeholder in the detector): read in full, nothing malicious seen, not run.
  Changes asked on 2026-11-23: git-filter-repo's default marker is `***REMOVED***`, which it leaves blocked. Next:
  when the author pushes the fix, re-read the whole diff, approve its held CI run (the owner chose to wait for the
  fix), then decide the merge. Unverified by a run: by reading, `KEY=***REDACTED***#value` in a `.env` would pass.
- Hermes: Foreman is in its catalog at the pin ce9b01a (NousResearch/hermes-agent#153851;
  https://hermes-agent.nousresearch.com/marketplace/foreman) and the owner's default profile runs that pin. A plugin
  change reaches users only through a SHA-bump pull request to the catalog, tried first in the `foremandev` profile;
  the next one is the single substantial update (DECISIONES, 2026-11-22 and 2026-11-24). The seams issue #153841 was
  closed as "not planned": propose each seam on its own.
- Foreman won 1st place in the Hermes Agent Plugin Hackathon (Nous's post:
  https://x.com/NousResearch/status/2123882434173559007); how the prizes are paid is unknown. Promotion is another
  project's (DECISIONES, 2026-11-23).
- What waits for Pedro lives in OmniBrain: `omnibrain_esperas` with repo `foreman`, or «Te espera» in the panel.

## Delivered
- The Hermes plugin, version 0.1.0, in `plugin/`, listed in the Hermes catalog; CI on Linux, macOS and Windows.
- The gate, the person's commands and the review on request in Claude Code, Codex, pi and OpenCode (`adapters/`,
  `.claude-plugin/`), not published and not announced in the root README yet.
- `PedValme/foreman-demo` (public) as the demo repository; the README as one page with the real capture and the GIF.

## In progress
- Foreman for any harness: `/foreman` complete on pi and OpenCode (T6) is next.

## Next steps
1. `trabajo/agnostico.md`, T5 to T7. Names of the packages, where each adapter is published and how Codex's hooks
   are installed: to the owner at T7; the root README does not mention the adapters until then.
2. The one Hermes catalog update: what the adapters need from the core (nothing so far), the native model picker
   (`trabajo/model-picker.md`), the README's award and GIF, and `/foreman notify on` in the README (`hermes config
   set …notify on` stores a boolean and Hermes then warns on every load).
3. Propose the Hermes seams one by one (#153841's advice): first the terminal cwd accessor, which removes the
   guarded private import.
4. Clean up the hackathon's throwaways: `~/cart`, `~/foreman-demo` and `/tmp/fm-battery*` on the owner's machine;
   the throwaway PRs #6-#14 and branches `t/*` in `foreman-demo`; the unpushed local branch
   `claude/minimal-child-env`.
5. Whether the private voice-plugins test repository becomes a project; whether only the owner merges here;
   register `foreman-demo` in the owner's environment as outside the factory.

## Known issues
- Unresolved (adapters, every harness): Foreman's hooks and state are files the agent's shell can reach, guarded
  against the plain attempt and not a disguised one; a second agent started without Foreman is outside the gate;
  when the adapter cannot run (no `python3`) the harness goes on without the gate and shows the error. The required
  check in CI stays the independent control. Not tried on Windows in a real session in any of the four.
- Unresolved (adapters): at the end of a turn in which the agent changed anything in a repository, the nudge lists
  every blocker in that working tree, the person's own uncommitted ones included, as the Hermes gate does.
- Unresolved (Claude Code): the person's commands carry Claude Code's own frame ("UserPromptSubmit operation
  blocked by hook"); an installation through the marketplace was not tried.
- Unresolved (Codex): allowing a finding is not available; `codex exec` prints nothing when the hook answers the
  person's command, and the interactive terminal was not tried; Codex's documentation says a command typed into a
  running interactive shell skips the hook (not tried); subagents not verified; no Codex plugin yet, the hooks are
  installed by hand.
- Unresolved (pi): a program driving pi's RPC mode counts as a person at the interface; a tool from another
  extension or an MCP server that runs commands is not inspected.
- Unresolved (OpenCode): "a person approved" is a permission prompt plus time (a yes within a second is nobody), so
  a late automatic yes passes; the end-of-turn nudge depends on a hook OpenCode marks experimental; a command's
  answer shows as an error notice; the recommended user-level installation was read, not seen.
- Unresolved (Hermes): the Desktop pane can disappear from the app's layout until the app is reloaded and the
  Desktop switch is toggled, cause not proven (#22); with a running gateway, a slash command typed first in a CLI
  session cannot tell the repository (`/foreman use <path>` is the way around); one guarded private import
  (`tools.terminal_tool.get_session_cwd`) makes `hermes plugins validate` warn; a pushed notification cannot carry
  buttons, Hermes shows no approval prompt for a plugin's command, and Telegram's choice buttons show only numbers.
- Unresolved (debt from the reviews): state files are plain files behind a best-effort guard; a SARIF report
  replaced by a separate command is not noticed; `include`d makefiles and a new `GNUmakefile` are not covered; a
  merge through `gh api` or a direct push to the base branch is not blocked; the real-panel behaviour test runs only
  where node, React and jsdom are installed (CI skips it).
- Unresolved (the review outside Hermes): it runs only when the person asks; at merge time and per turn it is not
  built. In Claude Code the default reviewer is the account's default model, which may not be the session's (Claude
  Code names the model to no hook). In Codex the reviewer is chosen in a file, not from a prompt; its session still
  sees the person's global instructions and declares a patch tool and sub-agent tools with no switch (what those
  can read was not verified); `codex exec` shows the review only in the file it saves. In OpenCode the person's
  global configuration reaches the session (instructions, MCP servers) and managed settings could undo its deny-all
  agent. pi and OpenCode cannot hold a model to a schema: an answer without that request's seal is "could not run".
- Unresolved (Hermes plugin, found 2026-11-24 reviewing the adapters; fixed there, not in `plugin/`): a finding the
  review verified keeps the line breaks of its `title`, `why` and `fix`, so a diff that steers the reviewer can make
  `/foreman review` print a line that reads as Foreman's own (a second "Foreman review: PASS" under the real
  verdict; the real first line and the verdict itself are not changed). The fix is one line in `review.verify`
  (collapse whitespace in those fields) and belongs in the one catalog update.
- Unresolved: the deterministic detector does not see a loosened assertion or an emptied test; only the
  second-model review does. A change bounced by the review whose agent ends the turn without changing it stays
  "bounced 1/3", with no notice to the owner (the notice comes only at the limit).
