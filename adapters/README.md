# Foreman's adapters

Foreman's gate lives in `plugin/foreman/`, the Hermes Agent plugin. An adapter brings that same gate to another
harness: it translates what the harness sends into the gate's calls and the gate's answer into what the harness
understands. It adds no rule and loosens none (PRODUCTO.md, rules 22 to 26).

| Path | What it is |
|---|---|
| `hook.py` | The one entry point: `python3 -I adapters/hook.py <host>`, the harness's JSON on standard input |
| `foreman_hosts/core.py` | The host-neutral half: shell command, write, turn start, end of turn, the person's command |
| `foreman_hosts/claude_code.py` | Claude Code's dialect |
| `claude-code/` | Claude Code's hooks and commands, named by `.claude-plugin/plugin.json` at the repository root |

Needs Python 3.9 or newer as `python3`, and git. No other dependency. Outside Hermes, Foreman keeps its state
(what you allowed, each session's turn) in `~/.foreman`.

## Claude Code

Not published yet. To try it from a clone:

```
claude --plugin-dir /path/to/foreman
```

What it does there, each seen in a real session on Claude Code 2.1.331:

- **Before the agent's shell command.** `git commit`, `git push` and `gh pr create` are inspected (the real diff,
  not the command text) and denied with the file and line when the change skips, deletes or moves tests, edits what
  the check runs, bypasses hooks or carries a secret. An agent-run `gh pr merge` is always denied. The denial holds
  in every permission mode, `bypassPermissions` included.
- **Before a write.** A `Write` or `Edit` that switches off a test is denied.
- **Before the agent finishes.** A turn that left one of those in the working tree, by any tool, is sent back once
  with what to undo.
- **Your commands**, answered by the hook with no model turn: `/foreman:status [path]`, `/foreman:allow [id]`,
  `/foreman:help`. Allowing a finding needs you at an interactive session: with `-p` it does nothing.

What it does not do yet: the second-model review, the board, merge and reject with reasons (Foreman on Hermes Agent
has them).

Limits to know:

- The gate runs on the agent's own machine. The independent control is still the required check in CI
  (`examples/foreman-check.yml`).
- Foreman's hooks and state are files. The adapter denies what names them (its installation, `~/.foreman`,
  `claude plugin disable foreman`, a settings write that disables hooks), which stops the plain attempt, not a
  disguised one.
- Without `python3` on the PATH the hooks fail and Claude Code goes on without the gate, showing the hook's error.
