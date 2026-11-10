# Foreman — product

**Promise:** a green check the agent did not rig. Other plugins prove the check ran; Foreman proves the agent did
not skip, delete or weaken the tests, change what the check runs, or commit a secret to get there.

**User:** a developer who lets Hermes Agent write code in a git repository.

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
8. **The guardia is a second model.** An optional model review of the diff through `ctx.llm` (host-owned
   credentials), on a model different from the main one: by default the user's configured fallback model. If only
   the main model is available, the verdict says the reviewer is the same model. It never runs inside a hook.
9. **Other sources.** A SARIF 2.1.0 file (hermes-security exports one) can add blockers by severity.
10. **CI mode.** The same detector runs as a command for a required check, where independence is real.
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

## Out of this delivery
Publishing GitHub checks from the agent, the owner's decisions and pending items, rework metrics, a Desktop panel
(unless the core is done early).
