# Foreman — product

**Promise:** a green check the agent did not rig. Other plugins prove the check ran; Foreman proves the agent did
not skip, delete or weaken the tests, change what the check runs, or commit a secret to get there.

**User:** a developer who lets a coding agent write code in a git repository. Hermes Agent has the whole line (the
plugin in `plugin/`, listed in its catalog); Claude Code, Codex, pi and OpenCode get it through adapters (rules 22
to 25; ESTADO.md says which ones exist today). Rules 1 to 21 are written for Hermes and hold there as they are.

## Rules
1. **Deterministic first.** The blockers come from a detector with no model: skipped or isolated tests, deleted
   test files or files moved out of the tests, a changed check entry point, secrets in the diff or in the pushed
   history. It needs only Python's standard library and git.
2. **Hard things block, they do not ask.** A blocker returns `block` from `pre_tool_call`; an approval request is
   used only where a person must decide (a false-positive marker, a merge).
3. **The agent cannot wave itself through.** A false-positive marker (`foreman:allow`) escalates to the user's
   approval; it never passes alone.
4. **Two moments.** Before `git commit`, `git push`, `gh pr create` and `gh pr merge` (the real diff is inspected,
   not the command text), and before the agent finishes a turn in which it edited code (`pre_verify`, bounded).
5. **One command.** Everything lives under `/foreman`; no other slash command is registered. Native Hermes commands
   (`/review`, `/branch`, `/diff`, `/status`, `/approve`…) are never shadowed.
6. **UX in the chat, any surface.** `/foreman` finds the repository, shows the branch against the base, the open
   pull requests and the issue each one closes, and gives each a verdict (mergeable or blocked) with the reasons and
   the exact line. It works the same in the terminal, Desktop and messaging. A Desktop panel is optional.
7. **Merge and reject with reasons.** A merge runs through Hermes's terminal tool after the person confirms (rule
   14; Hermes itself shows no approval prompt for it, checked in v0.23.0); a rejection leaves its reasons as a
   comment on the pull request. Never an automatic merge.
8. **The reviewer is a second model.** An optional model review of the diff through `ctx.llm` (host-owned
   credentials), on a model different from the main one: by default the user's configured fallback model. If only
   the main model is available, the verdict says the reviewer is the same model. It never runs inside a hook.
9. **Other sources.** A SARIF 2.1.0 file (hermes-security exports one) can add blockers by severity.
10. **CI mode.** The same detector runs as a command for a required check, where independence is real: as a
    GitHub Action (`action.yml` at the root) or as the workflow to copy (`examples/foreman-check.yml`).
11. **Works without GitHub.** Without `gh` or a remote, everything that only needs local git still works.
12. **Catalog rules are product rules.** Public surfaces only, credentials only through Hermes, approvals never
    bypassed, clean failure when unattended, every risky behaviour disclosed in the README, declared capabilities
    equal to registered ones. No telemetry. The gate itself makes no network call; two things reach the network,
    both only on an explicit command and both disclosed: the user's own `gh` (the board, verdicts, merge, reject)
    and the model call of `/foreman review`.
13. **Clean is not ready.** Foreman says CLEAN or BLOCKED about rigging; whether a pull request can merge
    (conflicts, draft, GitHub still computing) is said apart. CI is shown and never decides.
14. **A merge needs a person.** `/foreman merge` asks before merging; with nobody to ask it merges nothing and
    prints the command to confirm by typing it. Refusals (BLOCKED, conflicts, draft) cannot be overridden.

15. **One line for every change.** write → gate → second-model review → bounce → the owner approves → merge. Each
    change has one persisted state with its stages and events; the board, `/foreman pipeline`, the notifications
    and the Desktop panel all read that same state.
16. **Review levels.** `auto_review`: `merge` (default — the second model reviews when someone asks to merge),
    `finish` (the loop inside the agent's turn: review, bounce, fix, re-review, at most `max_bounces`), `off`.
    A review is bound to the exact diff: the same diff never calls the model twice. Verified blocking findings
    refuse a merge and cannot be overridden.
17. **One vocabulary.** CLEAN, BLOCKED, INCOMPLETE (something it was told to inspect could not be read) and NEEDS
    YOUR OK (waiting for `/foreman allow`), the same in every view, the tool and CI.
18. **The agent never merges.** An agent-run `gh pr merge` is blocked in every approval mode; only a person's
    `/foreman merge` merges.
19. **Notices are off until asked for.** A notification is plain text through the user's own Hermes gateway, sent
    only after `/foreman notify on`; the commands in it pass every check again.
20. **The panel only shows and submits.** The Desktop panel reads Foreman's own state and its buttons send the
    same `/foreman` commands a person would type; it never calls `gh` or merges.
21. **Only the plugin is installed.** The plugin lives in `plugin/`; the method documents, tests and examples
    stay in the repository and never reach a user's machine.
22. **One core, an adapter per harness.** The detector and the gate live in `plugin/foreman/`, the single source.
    An adapter (`adapters/`) only translates: what its harness sends becomes the gate's own calls, and the gate's
    answer becomes what that harness understands. An adapter adds no gate rule and loosens none; what it adds is
    the guard around Foreman's own program and state, which outside Hermes are files the agent's shell can reach.
    `plugin/` never reads outside itself.
23. **The Hermes plugin changes only with a catalog update.** Changes to the core land on `main` with the tests
    green and reach Hermes users together, in one substantial update tried first in the `foremandev` profile.
24. **What a person decides stays out of the agent's reach, in every harness.** `allow` and `merge` exist only where
    the model cannot type them (a command the person types; never a tool, never the agent's shell), an agent that
    runs them is blocked, and with nobody attending they do nothing. A harness that gives no sound sign that a
    person typed the command does not offer `allow` at all (Codex today): the finding is fixed, or the person
    commits it themselves. Outside Hermes a merge, a comment or a close is Foreman's own `gh` process (no shell,
    those three commands only), started only for such a command; a question to the person goes through the
    harness's own dialog, and an answer counts only for the very question asked.
25. **Outside Hermes the reviewer is a fresh session that did not write the code.** Foreman launches it (never the
    writing agent), without tools, with the diff, and verifies its answer as rule 8's review does. The user picks
    its model and effort; with nothing picked, the same model one effort level up, and the verdict says so. It
    reviews when someone asks to merge; on every turn only if the user turns it on (off by default, per harness,
    with rule 16's limits), and only where the harness's end-of-turn hook waits for a review: one started and cut
    off is paid for and never read. Here it is "the review", never "the second model". What the review says about its
    own reviewer is part of the verdict's truth: it names the session's model only when the harness names it, never
    claims another model, and states what its session could still see or do where the harness leaves no way to
    close it. Nothing the author of the diff controls can become the answer (a schema the harness enforces, or a
    seal made for that one request).
26. **Full where the harness allows it.** pi and OpenCode (its v2 plugin API) get the gate, `/foreman` and the
    reviewer; Claude Code and Codex get the gate, the person's commands and the reviewer. Phone notifications and
    the Desktop panel are Hermes's. Outside Hermes `/foreman` is the Hermes plugin's own board, run unchanged on a
    stand-in for Hermes's context, so the two cannot drift apart.

27. **Said by where it holds.** Foreman says what it promises by where it runs, not by a list of agents. In the
    agent (a harness's hook) it stops the shortcut at the moment it is tried, and it is made of files the agent's
    shell can reach. In CI (the required check) it is the one control the agent cannot move, once the check is
    required, the workflows are protected, the rules bind the agent's own account and Foreman runs in a job of
    its own. A harness is named only after its own test in a real session. The check in CI never loads the
    detector from the repository it checks (a pull request could bring its own), and in the action a marked
    finding fails unless the user turns that off.

## Out of this delivery
Publishing GitHub checks from the agent, the owner's decisions and pending items, rework metrics. Buttons on the
pushed notification itself and Hermes's own approval prompt for a plugin's commands need seams Hermes does not
offer yet (requested upstream).
