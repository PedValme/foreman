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
  with no model turn, also in `pi -p` (on standard output there; with `--mode json`, on standard error, so pi's
  event stream stays clean). Allowing a finding needs you at pi's interface (its terminal UI, or a client
  on its RPC mode): with `-p` or `--mode json` it does nothing. Seen: `pi -p "/foreman allow 328d40c6"` answered
  "nobody is attending"; the same command typed in pi's terminal UI allowed it, and the agent's next commit passed.
- **When Foreman needs you** (the gate could not inspect a commit, for example its directory is gone), pi asks you
  with its own dialog; with nobody there (`-p`), the call is refused with the reason.

- **The review**, `/foreman review [pull request|branch] [--fresh]`: Foreman starts a fresh pi session that did not
  write the code (`pi --mode json --no-tools --no-extensions --no-session`, started in an empty temporary folder so
  it reads neither your repository nor its instructions, with your own pi login), gives it the diff and checks that
  every finding it returns quotes a line of that diff. It is advisory: it grants, merges and unblocks nothing. The
  same diff by the same reviewer is never sent twice (`--fresh` asks again). Seen on pi 1.5.0: an assertion loosened
  from an exact value to "is true", which the gate cannot see (CLEAN), came back BLOCKED with the line quoted; the
  same review again answered from the stored result without calling the model.
- **Who reviews is yours**, `/foreman reviewer [model] [effort]` (`default` to go back): any model pi knows
  (`pi --list-models`; `provider/id` when two providers offer it) and any of pi's thinking levels: off, minimal,
  low, medium, high, xhigh, max. With nothing chosen it is pi's default model one thinking level above the
  session's. pi tells Foreman both the session's model and its thinking level, so the review states exactly what
  that is, for example "at effort high, one level above this session's medium", and says plainly that it is the
  model that wrote the code, with more thinking and a clean context, unless you chose another. When you choose a
  model, it says whether it is the same as the session's. It takes as long as that model takes: up to a few
  minutes with nothing shown meanwhile.

What it does not do yet: the review when someone asks to merge and on every turn (it runs when you ask), the board,
merge and reject with reasons (Foreman on Hermes Agent has them).

## Limits to know

- **The review's limits in pi.** pi has no switch that forces a JSON schema, so Foreman puts the schema in what it
  sends and reads the object out of the final text (plain, in a fenced block or among prose); a model that answers
  with no object leaves the review without a verdict, and Foreman says so. Any model pi offers can be chosen, and a
  small one may miss a rigged line or quote one wrongly (the quote is checked against the diff, a miss is not).
  A model that does not support the thinking level you chose gets the nearest one it does (pi clamps it). The
  review needs `pi` on the PATH (`FOREMAN_PI` names another), it uses whatever login pi has for the model, and it
  is skipped inside its own session: `FOREMAN_REVIEWER=1` makes the extension do nothing there, so the reviewer
  cannot call Foreman.

- The gate runs on the agent's own machine. The independent control is still the required check in CI
  (`examples/foreman-check.yml`).
- **When Python cannot answer** (no `python3`, an error, no answer within 30 seconds): a shell command that names
  `git` or `gh` together with `commit`, `push`, `pr` or `config`, anywhere in it (the gate's own quick filter),
  goes to you, or is refused with nobody there; it never passes unseen. Every other call goes on, and pi shows the error once per session ("Foreman could
  not …: until this is fixed Foreman is not checking this session"); in `-p` it goes to standard error. `/foreman`
  shows its error each time.
- Foreman's extension and state are files. It refuses what names them (the clone's `adapters/` and `plugin/`,
  `~/.foreman`, `adapters/hook.py pi` run by hand), `pi remove` of Foreman, `pi config` (pi's screen that switches
  extensions off), a nested `pi` given `/foreman allow`, and a write to pi's settings (`~/.pi/agent/settings.json`,
  `.pi/settings.json`, `$PI_CODING_AGENT_DIR/settings.json`) that drops Foreman from them or excludes it. That
  stops the plain attempt, not a disguised one. Loaded with `-e`, Foreman is in no settings file: the agent's way to
  lose it is to start another pi without it, which does not change your session.
- Only pi's own shell tools (`bash`, `powershell`) reach the gate. A tool from another extension or an MCP server
  that runs commands is not inspected (one that names a file meets only the guard around Foreman's own files),
  and a pi started with `--no-extensions` (`-ne`; a subagent launcher may start one so) runs without Foreman.
- Keep `foreman.ts` inside its clone: it finds `hook.py` and the gate from its own location (`../hook.py`), so a
  copy of the file alone in pi's extensions folder cannot run.
- Paths are read as pi's own tools read them (a leading `@` dropped, `~/` expanded, relative to the session's
  directory).
- "A person is at the interface" is pi's `ctx.hasUI`: true in the terminal UI and in RPC mode, false in `-p` and
  `--mode json`. A program driving pi's RPC mode counts as a person; the guard above, not this flag, is what keeps
  the agent's own shell from `/foreman allow`.
- pi gives no id for one run of the agent, so Foreman starts a run at `before_agent_start` (once per prompt; a
  continuation does not fire it) and sends the agent back at most once until the next prompt.
- pi runs each `bash` call in the session's directory: a `cd` does not carry to the next call, and Foreman inspects
  the session's directory.
- Not seen: Windows (`powershell`, `python3` may be missing there: set `FOREMAN_PYTHON`), a pi package
  installation (`pi install`), and the dialog for an `ask` in a real session (it is exercised by the tests).
