<!-- pic-method: 1 -->
# Foreman — how we work

Foreman stops a coding agent from rigging its own green check. It is a plugin for Hermes Agent
(NousResearch/hermes-agent), listed in its catalog and first place in the Hermes Agent Plugin Hackathon, and from
2026-11-24 the same gate for other harnesses through adapters (PRODUCTO.md, rules 22 to 26). Pedro owns it and
decides what the product does. Talk to the owner in their language (Spanish). Project files are in English.

<!-- pic-method: first-action -->
## First action of a session
Read the index below, then ESTADO.md, its "Next session" first (where the last session stopped), and DECISIONES.md
(what is already decided). If `trabajo/` has a file for your task, read it too. PRODUCTO.md holds the product's rules.

<!-- pic-method: index -->
## Index (kept current at every session close)
- Handoff: ESTADO.md, its "Next session" block.
- The owner's rules and preferences for this repository, each with its why and its source; those for several
  repositories live in the owner's global instructions and are not copied here:
  - UX in the chat and terminal comes first, a Desktop panel is optional — the owner wants ease of use, not a
    panel that competes with existing ones (DECISIONES.md, 2026-11-09).
  - One slash command, `/foreman`; never a name Hermes already uses — Hermes silently rejects a colliding name
    (DECISIONES.md, 2026-11-09).
  - Every catalog admission rule is a requirement — a broken rule is a declined entry (DECISIONES.md, 2026-11-09).
  - Nothing of the owner's private stack (his private tooling and its prompts, names, hosts, accounts) enters this
    public repository — it is private and unlicensed.
  - An adapter never needs an edit in `plugin/`; what the core does need lands on `main` and reaches Hermes in one
    substantial catalog update — the listed plugin is what Hermes users run, and each update is re-reviewed by
    Hermes's maintainer (DECISIONES.md, 2026-11-24).
  - Each harness's adapter is published when its own end-to-end test in a real session passes, and its name and
    where it is published are the owner's — a gate announced before it was seen working is a promise the product
    does not keep (DECISIONES.md, 2026-11-24 and 2026-11-10).
- Operation: see "This repository".
- Known pitfalls: the Hermes on the Windows development PC has no model provider, so a real session can only run
  on the owner's Hermes machine; `hermes plugins install --ref` needs the full 40-character commit; with a gateway running, a slash
  command runs inside the gateway process, whose directory is the Hermes home, not the user's. Claude Code's
  interactive prompt rejects a `/foreman` that is not a real command before any hook sees it, so the person's
  commands are plugin commands (`/foreman:status`); outside Hermes Foreman's state is `~/.foreman`, on this machine
  too: remove what a real-session test leaves there. Foreman's own check reads this repository's test files, so a
  fixture builds a skip marker from parts (`"@pytest.mark." + "skip"`, `detector.MARKER`), never literally; CI runs
  on Windows, so a test never compares a Unix-only path as a string (build paths from the test's temp directory).
  A new conditional skip (`skipIf` for a platform) goes in a new test file: added to an existing one it is a
  finding of Foreman's own check, by design (there it could be switching off tests that already ran). Outside
  Hermes the adapters bind the core's contexts and wrap three of its functions for the length of one command
  (`standin.py`, `reviewer.bound`): a test must find `board._CTX`, `gate._CTX`, `review._CTX` and those functions
  as it left them, and a change to `board._review_for_merge`, `board.reject_comment` or `finish.py`'s messages is
  checked against the adapters' tests. A harness's terminal UI can be driven for a real-session test through
  tmux (`tmux send-keys`, `capture-pane`): that is how pi's selector and its merge were seen.

## Where things are: one document per question
| Question | Document | Who writes it |
|---|---|---|
| What was decided? | [DECISIONES.md](DECISIONES.md) | The owner decides; the agent writes it down |
| Where do things stand? | [ESTADO.md](ESTADO.md) | The agent, rewritten when work closes |
| What is the product? | [PRODUCTO.md](PRODUCTO.md) | The agent, from the owner's decisions |
| How do we work here? | This file | The owner |
| A feature that spans sessions | `trabajo/<feature>.md`, deleted when it closes | The agent |
Code and tests are what the system really does; when a document and the code disagree, check the code.

## This repository
- A native Hermes plugin in Python 3.11+, standard library only (no runtime dependencies), plus git. The plugin is
  the `plugin/` folder, the only part Hermes installs (catalog `subdir: plugin`): `plugin.yaml`, `__init__.py`
  (registration), the `foreman/` package, `desktop/`, `dashboard/`, `README.md` (the full one) and `LICENSE`. Nothing
  in it reads outside `plugin/`. The root keeps the tests, examples and working documents. Requires Hermes
  >= 0.22.6. The user-facing README, messages and command output are in English.
- The adapters for other harnesses are in `adapters/` (its README says what each file is): `foreman_hosts/core.py`
  is the host-neutral half, one module per harness is its dialect (Claude Code, Codex, pi, OpenCode), `neutral.py`
  is the protocol a harness's own extension speaks when it is code (pi's `foreman.ts`; OpenCode's `foreman.ts` for
  its server and `tui.ts` for its terminal interface, the only place where OpenCode shows a person typed), `reviewer.py`
  is the review as a fresh session of the harness, `standin.py` runs the Hermes plugin's board, merge and reject
  on a stand-in for Hermes's context, and `hook.py`
  is the entry point they all run (`python3 -I`, Python 3.9+). They import the gate from `plugin/foreman/`;
  `plugin/` never imports them. The repository root is the package another harness installs (`.claude-plugin/` for Claude Code), so
  nothing binary, generated or private is committed anywhere in it.
- Check, from the root: `python -m unittest discover -s tests -q` (`tests/tests_support.py` puts `plugin/` and
  `adapters/` on `sys.path`; import it before `foreman`) and `hermes plugins validate plugin --install-deps`. Both
  run before every commit; `claude plugin validate .` when the Claude Code plugin's files change. The detector, the
  adapters and their tests are the product's controls: a change to them is reviewed by an agent that did not write
  it.
- Try an adapter without installing it, in a throwaway repository and from a clone other than the one being
  edited (each harness's README under `adapters/` has the exact command): `claude --plugin-dir <clone>` (`-p
  --setting-sources project,local` leaves the owner's own hooks out), `pi -ne -e <clone>/adapters/pi/foreman.ts`,
  `codex -c hooks.…` with `--dangerously-bypass-hook-trust`, and for OpenCode a link in the throwaway repository's
  `.opencode/plugins` with a project `opencode.json` that turns the other plugins off. Never write into the owner's
  own harness configuration (`~/.claude`, `~/.codex`, `~/.pi`, `~/.config/opencode`) for a test; a real session
  spends the owner's quota on that harness's provider and may be recorded by his own global hooks: few and short.
- Try it without touching the owner's Hermes setup: `hermes plugins doctor plugin` (temporary HERMES_HOME), or a
  dedicated profile (`hermes -p foreman-dev …`). Never install it into the default profile.
- Hermes's plugin documentation, read before using a surface: `website/docs/developer-guide/plugins/` and
  `website/docs/user-guide/features/hooks.md` in NousResearch/hermes-agent; the admission rules are in
  `plugin-catalog/README.md` there.
- Evals: none. Sessions on a real Hermes to try the plugin spend the owner's model quota: keep them short; a batch
  that compares models or prompts needs the owner's yes to its size and cost.

<!-- pic-method: core -->
## Core rules
1. **What is decided is not asked again.** Look in DECISIONES.md and ESTADO.md before asking the owner anything; ask
   only what is really theirs, with your recommendation first. Why: the owner's time is the scarcest resource here.
2. **Work from the agreed queue; a question only reads.** The queue is ESTADO.md's next steps and what the owner asks
   in the session. Finishing or fixing what is in it, or a small defect on the task's path (it changes neither the
   agreed result nor another project nor a risky area), you do and report. What changes the agreed scope (a new task,
   a project the request does not cover, a new spend or a new test campaign; normal work is not one) you propose
   first, with why, and do only with the owner's yes. A question, a review or an investigation only reads; its findings, defects included, are reported.
   Why: unrequested work is how a task's cost multiplies and decisions get lost.
3. **Never discard work you did not make.** Uncommitted changes, stashes, branches and worktrees that are not yours
   stay, even if they look abandoned. Why: work lost this way cannot be recovered.
4. **Risky changes get a second pair of eyes.** Security, permissions, real data, money, deploys and the checks
   themselves are reviewed by someone (or an agent) who did not write them, before they merge. Why: the author misses
   the same thing twice.
5. **Write it down as it happens.** An owner's decision goes to DECISIONES.md the moment it is taken, with their own
   words; when a piece of work closes, rewrite ESTADO.md; a correction the owner had to give twice goes to the index's
   known pitfalls. Why: sessions get cut, and what is not in the repository did not happen.
6. **The check stays green and honest.** Never weaken a check or a test to make it pass; fix the cause or say why it
   fails. Why: a check that lies is worse than none.

<!-- pic-method: close -->
## Closing a session
When a piece of work closes, when you stop to wait for the owner, or when the owner says they are stopping, and the
session changed something or leaves something pending (never in a paused repository unless the owner asks), one short
step before your reply:
1. Rewrite ESTADO.md's "Next session": what you were doing, what you tried, the next action, what waits for the owner.
2. Check that every decision the owner took in the session is in DECISIONES.md with their words, every pending item
   is in ESTADO.md or `trabajo/`, and the index above still holds (a decision amended is amended there too).
3. Commit it with the session's work, the way this repository brings changes to `main`; a documents-only change only
   when nothing else is pending and the block changed. A memory tool may keep a copy; the handoff lives here, where
   any agent reads it first.

<!-- pic-method: never -->
## Never
- Print, paste or commit secrets (keys, tokens, passwords). Test fixtures use obviously fake values.
- Skip hooks (`--no-verify`), push to `main` directly, force-push, or rewrite shared history.
- Deploy, migrate, delete data or run anything on production without the owner's explicit approval for that action.

## Remote hosts
One: the owner's own Hermes machine, the only one with a model provider configured (role: production, it is his
live agent). This repository is public, so how to reach it is not written here: it is in the owner's private
environment (DECISIONES.md, 2026-11-09). The owner approved its use for testing this plugin (DECISIONES.md,
2026-11-09). A host with no role is production. Every connection, deploy or command on a production or client host
needs the owner's approval, reading included. On it, the plugin is installed only into the dedicated profile
`foremandev`, never the default one; the Hermes home there is itself a git repository: never commit in it.

## How a change reaches `main`
If `.fabrica.json` has an `integracion` field, it says how (a value you do not know: ask the owner). Otherwise: a
branch, `check` green, and a pull request; it is ready to integrate when it is not a draft. Before the first push, install the
hooks the repository declares.

## Method
This repository follows pic's method: the skills `kickoff`, `adopt` and `slice` hold the procedure, and
`pic method check` validates these documents.
