# Foreman for pi

Foreman's gate in the [pi coding agent](https://pi.dev) (`@earendil-works/pi-coding-agent`). `foreman.ts` is a pi
extension and nothing more: for each thing pi tells it, it runs `python3 -I adapters/hook.py pi` from the clone it
lives in, with one request on standard input (`../foreman_hosts/neutral.py`), and does what the answer says. The
gate itself is the Hermes plugin's (`plugin/foreman/`); pi's own words and guards are `../foreman_hosts/pi.py`.

Needs pi 1.5.0 or newer, Python 3.9 or newer as `python3` (another interpreter: set `FOREMAN_PYTHON` before you
start pi), and git. No npm dependency and no build step: pi loads the TypeScript file as it is.

## Try it

Not published yet. From a clone, without installing anything into pi:

```
pi -e /path/to/foreman/adapters/pi/foreman.ts
```

Use a clone you are not working in: Foreman keeps the agent out of its own code (`adapters/` and `plugin/` of the
clone it runs from), so an agent asked to change Foreman from that same clone is refused.

## What it does

Each of these was seen in a real session on pi 1.5.0 (macOS, the default model, 2026-11-24):

- **Before the agent's shell command** (`bash`, and `powershell` on Windows). `git commit`, `git push` and
  `gh pr create` are inspected (the real diff, not the command text) and refused with the file and line when the
  change skips, deletes or moves tests, edits what the check runs, bypasses hooks or carries a secret. An agent-run
  `gh pr merge` is always refused. The model reads the reason as the tool's result. Seen:
  `Foreman blocked git commit. - [test-skipped] tests/test_cart.py:10 — test skipped or isolated`, and no commit.
- **Before a write.** pi's `write` and `edit` (each of an edit's replacements) that switch off a test are refused.
  Another tool that names a file (an extension's, an MCP server's) meets only the guard around Foreman's own files.
- **Before the agent settles.** At pi's `agent_before_settle`, a run in which the agent changed the working tree and
  left one of those in it is sent back once, with what to undo, as a message the model reads and you see. A run
  that only talked is never sent back. Seen: a skip copied in with `cp` from the shell was sent back once; the agent
  removed it and fixed the code, and the second settle passed.
- **Your command**, `/foreman status [path]`, `/foreman allow [id]`, `/foreman help`, answered by the extension
  with no model turn, also in `pi -p`. Allowing a finding needs you at pi's interface (its terminal UI, or a client
  on its RPC mode): with `-p` or `--mode json` it does nothing. Seen: `pi -p "/foreman allow 328d40c6"` answered
  "nobody is attending"; the same command typed in pi's terminal UI allowed it, and the agent's next commit passed.
- **When Foreman needs you** (the gate could not inspect a commit, for example its directory is gone), pi asks you
  with its own dialog; with nobody there (`-p`), the call is refused with the reason.

What it does not do yet: the second-model review, the board, merge and reject with reasons (Foreman on Hermes Agent
has them).

## Limits to know

- The gate runs on the agent's own machine. The independent control is still the required check in CI
  (`examples/foreman-check.yml`).
- **When Python cannot answer** (no `python3`, an error, no answer within 30 seconds): a shell command Foreman
  would inspect (`git commit`, `git push`, `gh pr create`, `gh pr merge`) goes to you, or is refused with nobody
  there; it never passes unseen. Every other call goes on, and pi shows the error once per session ("Foreman could
  not …: until this is fixed Foreman is not checking this session"); in `-p` it goes to standard error. `/foreman`
  shows its error each time.
- Foreman's extension and state are files. It refuses what names them (the clone's `adapters/` and `plugin/`,
  `~/.foreman`, `adapters/hook.py pi` run by hand), `pi remove` of Foreman, `pi config` (pi's screen that switches
  extensions off), a nested `pi` given `/foreman allow`, and a write to pi's settings (`~/.pi/agent/settings.json`,
  `.pi/settings.json`, `$PI_CODING_AGENT_DIR/settings.json`) that drops Foreman from them or excludes it. That
  stops the plain attempt, not a disguised one. Loaded with `-e`, Foreman is in no settings file: the agent's way to
  lose it is to start another pi without it, which does not change your session.
- "A person is at the interface" is pi's `ctx.hasUI`: true in the terminal UI and in RPC mode, false in `-p` and
  `--mode json`. A program driving pi's RPC mode counts as a person; the guard above, not this flag, is what keeps
  the agent's own shell from `/foreman allow`.
- pi gives no id for one run of the agent, so Foreman starts a run at `before_agent_start` (once per prompt; a
  continuation does not fire it) and sends the agent back at most once until the next prompt.
- pi runs each `bash` call in the session's directory: a `cd` does not carry to the next call, and Foreman inspects
  the session's directory.
- Not seen: Windows (`powershell`, `python3` may be missing there: set `FOREMAN_PYTHON`), a pi package
  installation (`pi install`), and the dialog for an `ask` in a real session (it is exercised by the tests).
