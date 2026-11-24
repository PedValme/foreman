# Foreman's adapters

Foreman's gate lives in `plugin/foreman/`, the Hermes Agent plugin. An adapter brings that same gate to another
harness: it translates what the harness sends into the gate's calls and the gate's answer into what the harness
understands. It adds no rule and loosens none (PRODUCTO.md, rules 22 to 26).

| Path | What it is |
|---|---|
| `hook.py` | The one entry point: `python3 -I adapters/hook.py <host>`, the harness's JSON on standard input |
| `foreman_hosts/core.py` | The host-neutral half: shell command, write, turn start, end of turn, the person's command |
| `foreman_hosts/hosts.py` | The harnesses there is an adapter for, and the module of each |
| `foreman_hosts/claude_code.py` | Claude Code's dialect |
| `foreman_hosts/neutral.py` | The request and answer for a harness whose extension is code (pi, OpenCode) |
| `claude-code/` | Claude Code's hooks and commands, named by `.claude-plugin/plugin.json` at the repository root |

A new harness is one dialect module (its `core.Host` and a `main`), its own folder here with what the harness loads,
and its tests. A harness that runs a command hook with JSON reads `claude_code.py` as its model; one whose extension
is code sends `neutral.py`'s requests from the thinnest extension the harness allows.

Needs Python 3.9 or newer as `python3`, and git. No other dependency. Outside Hermes, Foreman keeps its state
(what you allowed, each session's turn) in `~/.foreman`.

## Claude Code

Not published yet. To try it from a clone:

```
claude --plugin-dir /path/to/foreman
```

Use a clone you are not working in: Foreman keeps the agent out of its own code (`adapters/`, `plugin/`,
`.claude-plugin/` of the clone it runs from), so an agent asked to change Foreman from that same clone is denied.

What it does there, each seen in a real session on Claude Code 2.1.331:

- **Before the agent's shell command.** `git commit`, `git push` and `gh pr create` are inspected (the real diff,
  not the command text) and denied with the file and line when the change skips, deletes or moves tests, edits what
  the check runs, bypasses hooks or carries a secret. An agent-run `gh pr merge` is always denied. The denial holds
  in every permission mode, `bypassPermissions` included.
- **Before a write.** A `Write` or `Edit` that switches off a test is denied.
- **Before the agent finishes.** A turn in which the agent changed the working tree and left one of those in it is
  sent back once with what to undo. What counts as the agent's change: a file it wrote with `Write` or `Edit`, and,
  when it used the shell, any difference in the repository the shell ran in. A turn that only talked is never sent
  back. Not seen at this point (the commit gate still sees it): a shell edit in another repository reached with
  `cd` inside one command, and a change inside a folder git already listed as untracked.
- **Your commands**, answered by the hook with no model turn: `/foreman:status [path]`, `/foreman:allow [id]`,
  `/foreman:help`. Allowing a finding needs you at an interactive session: with `-p` it does nothing.

What it does not do yet: the second-model review, the board, merge and reject with reasons (Foreman on Hermes Agent
has them).

Limits to know:

- The gate runs on the agent's own machine. The independent control is still the required check in CI
  (`examples/foreman-check.yml`).
- Foreman's hooks and state are files. The adapter denies what names them (its installation, `~/.foreman`,
  `claude plugin disable foreman`, a settings write that disables hooks, its entry point run by hand), which stops
  the plain attempt, not a disguised one. "A person is at the session" tells an interactive session from `-p` and no
  more: it is that guard, not the session being interactive, that keeps the agent's shell from `allow`.
- When the hook cannot run at all (no `python3` on the PATH, a Python older than 3.9, a damaged installation), it
  fails as any hook error does: Claude Code shows the error and goes on without the gate. When the hook runs and
  cannot inspect a commit, push or pull request, the call goes to you instead.
