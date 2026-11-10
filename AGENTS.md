<!-- pic-method: 1 -->
# Foreman — how we work

Foreman is a plugin for Hermes Agent (NousResearch/hermes-agent) that stops a coding agent from rigging its own
green check; it is our entry to the Hermes Agent Plugin Hackathon (closes 2026-11-11 17:00 EST). Pedro owns it and
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
  - Nothing of the owner's private stack (fábrica, guardia's prompts, names, hosts) enters this public repository —
    fábrica is private and unlicensed.
- Operation: see "This repository".
- Known pitfalls: the Hermes on the Windows development PC has no model provider, so a real session can only run
  on the owner's Hermes machine; `hermes plugins install --ref` needs the full 40-character commit; with a gateway running, a slash
  command runs inside the gateway process, whose directory is the Hermes home, not the user's.

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
  the repository root: `plugin.yaml`, `__init__.py` (registration) and the `foreman/` package. Requires Hermes
  >= 0.22.6. The user-facing README, messages and command output are in English.
- Check: `python -m unittest discover -s tests -q` and `hermes plugins validate . --install-deps`. Both run before
  every commit. The detector and its tests are the product's controls: a change to them is reviewed by an agent that
  did not write it.
- Try it without touching the owner's Hermes setup: `hermes plugins doctor .` (temporary HERMES_HOME), or a
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
environment (DECISIONES.md, 2026-11-10). The owner approved its use for testing this plugin (DECISIONES.md,
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
