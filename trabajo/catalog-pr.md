# Draft catalog pull request for NousResearch/hermes-agent (not opened)

Before opening: replace `c15453cb2fc07fa674d6f7b548a553b3ce9e6f5d` below and `REPLACE_WITH_40_CHAR_COMMIT_SHA_OF_PEDVALME_FOREMAN` in
`trabajo/catalog/foreman.yaml` (the `sha` and every `screenshots` URL)
with the full 40-character commit of PedValme/foreman being listed; run `hermes plugins validate plugin
--install-deps` on a checkout at that commit and `python scripts/validate_plugin_catalog.py plugin-catalog/foreman.yaml`
in the Hermes checkout; the PR adds one file, `plugin-catalog/foreman.yaml`. Commit it in the Hermes fork with the
owner's GitHub noreply address (`git -c user.email=82127492+PedValme@users.noreply.github.com commit …`): Hermes's
Contributor Attribution check fails on an email it cannot map, and the noreply address keeps the personal one out.
Open the Hermes issue (`trabajo/hermes-issue-seams.md`) first and put its link where this text asks for it: it is
the answer to the one validator warning (catalog rule 9). Then remove the "DRAFT" header and the placeholder comments
from the entry.

**Title:** `plugin-catalog: add foreman (test-integrity gate for coding agents)`

---

## Foreman

A green check the agent did not rig. Foreman reads the real diff before `git commit`, `git push`, `gh pr create` and
`gh pr merge` and blocks a coding agent that skips, deletes or moves tests, edits or weakens what the check runs,
bypasses git hooks or commits a secret. A second model (by default the user's Hermes fallback model) reviews what
rules cannot see, such as a loosened assertion. Only a person allows an exception, and Foreman never merges for the
agent: a plain agent-run `gh pr merge` is blocked (a merge through `gh api` or a direct push to the base branch is
not; the README says to protect the base branch and the CI workflow on GitHub). It guards against the shortcuts an
agent takes in the open, not against one that hides its commands; the README's *Known limits* list what it does not
follow.

- Repository: https://github.com/PedValme/foreman (public, MIT), plugin in `plugin/` (`subdir: plugin`)
- Pinned commit: `c15453cb2fc07fa674d6f7b548a553b3ce9e6f5d`, version `0.1.0`, `requires_hermes: ">=0.22.6"` (also in `plugin.yaml`)
- README (renders on the plugin page): `plugin/README.md` at the pinned commit
- Submitted by the repository owner (rule 5). **Plugin Hackathon entry.**

## Hermes surfaces it uses

- Hooks: `pre_tool_call` (terminal, `write_file`, `patch`: blocks rigging commands and writes) and `pre_verify` (before
  a coding turn ends: tells the agent what to undo; with `auto_review: finish`, reads stored reviews).
- One slash command, `/foreman`, with subcommands (no built-in name is shadowed).
- Two tools: `foreman_check` (the verdict as JSON) and `foreman_review` (the second-model review, advisory).
- `ctx.llm` for the review, with the capabilities `llm.model_override` and `llm.provider_override` so the reviewer can
  be another model; `ctx.ask_choice` for the merge confirmation and the repository picker; `ctx.dispatch_tool
  ("terminal", …)` for `gh pr merge`, `gh pr comment`, `gh pr close` and `hermes send`; `ctx.session_cwd()`;
  `plugin_data_dir` for its state; `config_schema` settings.
- Desktop: `desktop/plugin.js` (a pane and a status-bar chip, SDK only, switched off until the user enables it) and a
  dashboard backend route, `GET /api/plugins/foreman/pipeline`, read-only, returning Foreman's own state file.

## Disclosure (rule 13)

- **Shell commands.** Read-only `git` subprocesses in the repository the agent works in (`diff`, `diff-tree`, `log`,
  `ls-files`, `rev-parse`, `rev-list`, `merge-base`, `cat-file`, `show`, `status`, `remote`, `symbolic-ref`,
  `for-each-ref`, `hash-object` without `-w`). The GitHub CLI only when the user types a `/foreman` subcommand: reads
  (`gh repo view`, `gh pr list`, `gh issue list`, `gh pr view`, `gh pr diff`) as a subprocess with `gh`'s own login;
  writes (`gh pr merge --match-head-commit`, `gh pr comment`, `gh pr close`) only on `/foreman merge` and `/foreman
  reject`, merge and close after the user's confirmation, through Hermes's terminal tool. `gh pr merge
  --delete-branch` deletes the merged branch on GitHub and locally.
- **Reads outside its own data.** Files of the repository the agent works in (untracked files up to 500 × 512 KB,
  `package.json`, `Makefile`, `tox.ini`, `.foreman.json`, named SARIF reports, a commit message file); a non-ignored
  `.env` only to warn before it is committed, values never printed or stored. Through Hermes's config reader: the
  user's main model and provider, the first fallback's provider and model names (and whether a fallback entry sets a
  `base_url`, value unused), and `agent.max_verify_nudges`; through
  `ctx.get_config`, its own plugin settings. `/foreman use` lists the directories directly inside the session's
  directories to find git repositories.
- **Config writes.** Only `/foreman notify on|to|off`, typed by the user, saves the plugin's own `notify` and
  `notify_to` settings with `ctx.set_config` (Hermes writes them under `plugins.entries.foreman.settings` in
  `config.yaml`). Nothing else changes the user's config. It registers one auxiliary task, **Foreman review**
  (`ctx.register_auxiliary_task`, default: the user's first fallback model), so the reviewer is picked in Hermes's own
  model pickers; and it reads `plugins.disabled` so that turning it off takes effect at once in a running gateway.
- **Network.** No calls of its own and no telemetry. Three paths, all user-initiated or user-enabled: the user's own
  `gh` (above); the review's model call through `ctx.llm` (the bounded diff, title, commit subjects and detector
  findings go to the user's configured provider; it spends tokens, once per exact diff, on `/foreman review`, before
  `/foreman merge` by default, or inside the turn with `auto_review: finish`); notifications with `hermes send`, off
  until the user runs `/foreman notify on`.
- **File writes.** In its plugin data directory: pending findings and exceptions, the pinned repository, stored
  reviews (up to 300 cached), the pipeline state (at most 200 changes) with notifications queued from hooks, the
  notification log, and short-lived reject comment and message files. Outside it only a temporary copy of a SARIF
  report committed in a pull request that is not checked out (system temp directory, deleted after reading).
- **Credentials.** None stored or read; models through `ctx.llm`, GitHub through `gh`'s own login, messages through
  the user's Hermes and bot.
- **Background processes.** None. The Desktop pane polls the read-only route every 2 s while visible, 15 s otherwise.
- **Approvals (rule 12).** It never auto-approves. A merge or close needs a person's confirmation or typed `--yes`;
  with nobody to ask (cron, a chat without choices, a timeout) nothing merges. An agent-run `gh pr merge` is
  blocked; other ways to merge (`gh api`, a direct push to the base branch) are not, and the README says so. A command
  Foreman cannot inspect goes to Hermes's approval prompt. No notification is sent from inside a hook.

### The one `hermes plugins validate` warning

```
⚠ private core imports (catalog rule 9 …): foreman/gate.py:661 tools.terminal_tool.get_session_cwd.
```

The `pre_tool_call` hook must know which repository a `git commit` without `workdir` runs in, which is the terminal's
directory after the agent's earlier `cd`. No public accessor gives that today: `ctx.session_cwd()` returns the
session's recorded workspace or launch directory. The import is inside `try/except`, read-only (it calls the function,
never rebinds anything), and if it fails or moves Foreman falls back to `ctx.session_cwd()` and
`agent.runtime_cwd.resolve_agent_cwd()`; when none names a repository the gate blocks with a hint to pass `workdir`,
so a missing seam never lets a commit through unchecked. The issue asking for the seam (with two others):
`<link to the issue, from trabajo/hermes-issue-seams.md>`.

## Validation

- `hermes plugins validate plugin --install-deps` at `c15453cb2fc07fa674d6f7b548a553b3ce9e6f5d`: passed; security scan safe; the one warning above.
- `scripts/validate_plugin_catalog.py plugin-catalog/foreman.yaml`: OK.
- The plugin's own CI: unit tests on Linux, macOS and Windows (Python 3.11 and 3.13), and Foreman on its own pull
  requests.

## Screenshots

The first image is a real capture of Foreman's panel in Hermes Desktop v0.23.0, with real data from the demo
repository `PedValme/foreman-demo`. The others are browser previews with scripted data (the real `desktop/plugin.js`
against a stand-in SDK).

- `docs/screenshots/panel-real-app.png`: real app; a pull request the review refused, one blocked at the gate, one
  merged after the owner's approval.
- `docs/screenshots/panel-several-changes-light.png`: browser preview; several changes on the line.
- `docs/screenshots/panel-bounced-dark.png`: browser preview; a change the review sent back to the agent.
- `docs/screenshots/panel-narrow-360-dark.png`: browser preview; the pane at 360 px.
- `docs/screenshots/panel-waiting-for-owner-light.png`: browser preview; a pull request past the gate and the review,
  waiting for the owner.

Demo video (under 90 s): `<link to the X post>`.
