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
  low, medium, high, xhigh, max. With nothing chosen it is the session's own model one thinking level above
  the session's. pi tells Foreman both, so the review states exactly what that is, for example "Reviewer: <model>,
  the model this session runs on, at effort high, one level above this session's medium", and says plainly that it
  is the model that wrote the code: more effort and a clean context, not another model. When you choose a model,
  it says whether it is the same as the session's. It takes as long as that model takes: up to a few
  minutes with nothing shown meanwhile.

- **The board**, `/foreman` alone: the branch and its verdict, open pull requests (through `gh`, with its own
  login) and the issues they close, each change's stages. With it, `/foreman verdict [pr|branch]`, `/foreman
  pipeline`, `/foreman prs`, `/foreman issues` and `/foreman use [path|n]`, which pins the repository for this pi
  session (`/foreman status` and `/foreman review` then read the pinned one). `/foreman use` alone asks you which
  repository in pi's own selector; with nobody at the interface it prints the list and what to type. Seen on pi
  1.5.0 with `-p` and no model turn: the board, `verdict`, `pipeline`, `prs`, `use` and `use .` on a repository
  without a GitHub remote ("GitHub is not available here"), and the board and `verdict <pr>` on one with ten open
  pull requests. `/foreman use` alone in the selector was run in the tests, not seen in a session.
- **Merge**, `/foreman merge <pr> [--merge|--rebase]`: only for you at pi's interface. The verdict must be CLEAN and
  GitHub must call it mergeable; then a fresh pi session that did not write the code reviews that exact commit
  (the stored review when `/foreman review <pr>` already did), and a verified blocking finding refuses the merge;
  then pi's selector asks you, naming the repository, the commit and the command; then Foreman's own `gh` merges
  that commit or nothing (`--match-head-commit`). `--yes` skips the selector, never the verdict or the review, and
  does nothing with nobody attending. Seen in pi's terminal UI on a throwaway pull request: reviewed (PASS, with
  who reviewed in plain words), asked, merged by squash; `pi -p "/foreman merge 19 --yes"` answered "nobody is
  attending" and merged nothing.
- **Reject**, `/foreman reject <pr> [--close] [note]`: posts the verdict's reasons and your note on the pull request
  as a comment signed "from pi"; `--close` asks you first (post and close, post only, or cancel). Seen in pi's
  terminal UI: Escape in the selector posted nothing; the second time the comment was posted and the pull request
  closed. With `-p`, nothing is posted.

- **The review at the end of every turn**, only if you turn it on: `/foreman reviewer every-turn on` (`off` to
  stop; off by default). When the agent is about to settle after a run that changed code and the gate finds
  nothing, Foreman starts the reviewer on the change itself, and a verified BLOCKING or HIGH finding sends the
  agent back with it: never twice for the same diff, at most three times in one run. It costs one more pi session
  on each such run, on your account, and the run waits for it. Seen on pi 1.5.0 with `-p`: asked to loosen
  `assert total() == 2` to `assert total()`, the agent did; the review sent the change back (`/foreman pipeline`:
  "Review sent it back (1 blocking), bounce 1/3"), and the agent put the exact value back before it finished.

## Limits to know

- **The review's limits in pi.** pi cannot hold its model to a schema, so Foreman puts the schema in what it sends
  together with a seal made for that request, which the author of the diff cannot know. The answer is the one
  object that carries that seal: an object quoted from the diff, or one without the seal, is never the answer. A
  review with no such object, or with two different ones, is "could not run", never a pass. The system text goes to
  pi as a file, so it survives `pi.cmd` on Windows. Any model pi offers can be chosen, and a
  small one may miss a rigged line or quote one wrongly (the quote is checked against the diff, a miss is not).
  A model that does not support the thinking level you chose gets the nearest one it does (pi clamps it). The
  review needs `pi` on the PATH and uses whatever login pi has for the model. The reviewer's session starts no MCP
  server (`--no-mcp`: pi would otherwise connect every enabled one, `--no-tools` or not). The repository's
  instructions are not read, but pi's documentation does not say whether a global `APPEND_SYSTEM.md` is still
  appended when `--system-prompt` is given: that is not known, so your own appended system text may reach the
  reviewer. The session is started with `--no-extensions`, so Foreman's extension is not loaded in it; Foreman's own hook also stands down for the
  token of a review that is running, and `FOREMAN_REVIEWER` set by anything else switches nothing off.

- The gate runs on the agent's own machine. The independent control is still the required check in CI
  (`examples/foreman-check.yml`).
- **When Python cannot answer** (no `python3`, an error, no answer within 30 seconds): a shell command that names
  `git` or `gh` together with `commit`, `push`, `pr` or `config`, anywhere in it (the gate's own quick filter),
  goes to you, or is refused with nobody there; it never passes unseen. Every other call goes on, and pi shows the error once per session ("Foreman could
  not …: until this is fixed Foreman is not checking this session"); in `-p` it goes to standard error. `/foreman`
  shows its error each time.
- Foreman's extension and state are files. It refuses what names them (the clone's `adapters/` and `plugin/`,
  `~/.foreman`, `adapters/hook.py pi` run by hand), `pi remove` of Foreman, `pi config` (pi's screen that switches
  extensions off), a nested `pi` given `/foreman allow`, `/foreman merge` or `/foreman reject`, and a write to
  pi's settings (`~/.pi/agent/settings.json`,
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
  `--mode json`. A program driving pi's RPC mode counts as a person, for `/foreman allow` and for `/foreman merge`
  and its selector alike; the guard above, not this flag, is what keeps the agent's own shell from them.
- **A merge runs the command twice**, once to ask you and once with your answer (Foreman's program answers one
  request and ends). The second run checks everything again and your answer counts only for the same question, so
  a pull request that got a new commit or a new CI state while the selector was open is asked again (at most
  three times). `/foreman pipeline` shows that merge's gate, review and "waiting for your decision" lines twice.
  A review that could not run on the first run is tried once more on the second (minutes again); if it then
  answers, you are asked the new question. The selector shows the review's notes and "could not run"; its verdict
  line and who reviewed come with the reply, after the merge (`/foreman review <pr>` shows them before).
- pi gives no id for one run of the agent, so Foreman starts a run at `before_agent_start` (once per prompt; a
  continuation does not fire it) and sends the agent back at most once until the next prompt for what the gate
  finds, and at most three times in all where the review at the end of every turn is on.
- pi runs each `bash` call in the session's directory: a `cd` does not carry to the next call, and Foreman inspects
  the session's directory.
- Not seen: Windows (`powershell`, `python3` may be missing there: set `FOREMAN_PYTHON`), a pi package
  installation (`pi install`), and the dialog for an `ask` in a real session (it is exercised by the tests).
