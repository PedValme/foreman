# Foreman's adapters

Foreman's gate lives in `plugin/foreman/`, the Hermes Agent plugin. An adapter brings that same gate to another
harness: it translates what the harness sends into the gate's calls and the gate's answer into what the harness
understands. It adds no rule and loosens none (PRODUCTO.md, rules 22 to 26).

| Path | What it is |
|---|---|
| `hook.py` | The one entry point: `python3 -I adapters/hook.py <host>`, the harness's JSON on standard input |
| `foreman_hosts/core.py` | The host-neutral half: shell command, write, turn start, end of turn, the person's command |
| `foreman_hosts/hosts.py` | The harnesses there is an adapter for, and the module of each |
| `foreman_hosts/claude_code.py`, `codex.py` | The dialects of the harnesses that run a command hook with JSON |
| `foreman_hosts/neutral.py` | The request and answer for a harness whose extension is code (pi, OpenCode) |
| `foreman_hosts/reviewer.py` | The review outside Hermes: a fresh session of the harness, and who it is |
| `foreman_hosts/standin.py` | The board outside Hermes: `plugin/foreman/board.py` on a stand-in for Hermes's context |
| `foreman_hosts/pi.py`, `opencode.py` | The dialects of those two: their guards and their words |
| `claude-code/` | Claude Code's hooks and commands, named by `.claude-plugin/plugin.json` at the repository root |
| `codex/` | Codex's `hooks.json` (installed by hand), `plugin-hooks.json` (named by `.codex-plugin/plugin.json` at the repository root) and its [README](codex/README.md) |
| `pi/` | pi's extension (`foreman.ts`) and its [README](pi/README.md) |
| `opencode/` | OpenCode's plugin: its server part (`foreman.ts`, `server.ts`), its TUI part (`tui.ts`) and its [README](opencode/README.md) |

A new harness is one dialect module (its `core.Host` and a `main`), its own folder here with what the harness loads,
and its tests. A harness that runs a command hook with JSON reads `claude_code.py` as its model; one whose extension
is code sends `neutral.py`'s requests from the thinnest extension the harness allows.

Needs Python 3.9 or newer as `python3`, and git. No other dependency. Outside Hermes, Foreman keeps its state
(what you allowed, each session's turn) in `~/.foreman`.

## The four harnesses side by side

None is published yet. Each was seen in real sessions on macOS (Claude Code 2.1.331, Codex CLI 0.171.0, pi 1.5.0,
OpenCode 2.3.2); each harness's own README says exactly what was seen, what was only read, and its limits.

## Install from the repository

The public name is `foreman-gate` everywhere it is installed; `foreman` stays as the command and the plugin's own
name. The repository root is the package: `package.json` (pi and OpenCode), `.claude-plugin/` (Claude Code's
marketplace and plugin) and `.codex-plugin/` (Codex's plugin, in the same marketplace).

| Harness | Install from git |
|---|---|
| Claude Code | `claude plugin marketplace add PedValme/foreman`, then `claude plugin install foreman@foreman-gate` |
| Codex | `codex plugin marketplace add PedValme/foreman`, then `codex plugin add foreman@foreman-gate`, then trust its hooks with `/hooks` in Codex |
| pi | `pi install git:github.com/PedValme/foreman` (`-l` for one project) |
| OpenCode | `opencode plugin add git+https://github.com/PedValme/foreman.git` |

Seen on macOS on 2026-11-24 (Claude Code 2.1.332, Codex CLI 0.171.0, pi 1.5.0, OpenCode 2.3.2), each in a
temporary configuration directory, from a copy of this repository served as a git remote on the machine itself
(the same commands with that URL in place of GitHub's; nothing was pushed): each harness cloned it, installed it
and listed it; pi answered `/foreman help` and `/foreman` with no model turn; OpenCode's TUI showed both parts
(`/foreman help` and the board in its dialog); Codex blocked the prompt `foreman help` before any model turn,
with its own dialect. Claude Code was not started (a session needs a login). Then, with these files on GitHub, the
commands as written above were run against it, again into temporary configuration directories: pi installed and
listed `git:github.com/PedValme/foreman` and answered `/foreman help`; Claude Code added the marketplace
`foreman-gate` and installed `foreman@foreman-gate`; Codex added the marketplace and listed the plugin "installed,
enabled"; OpenCode installed `git+https://github.com/PedValme/foreman.git` into its package cache as
`foreman-gate`. Each harness's README has the details.

| | Claude Code | Codex | pi | OpenCode |
|---|---|---|---|---|
| A rigged commit, push or pull request; an agent-run merge | refused | refused | refused | refused |
| A write that switches off a test | `Write`, `Edit` | `apply_patch` | `write`, `edit` | `write`, `edit`, `patch` |
| A turn that left one behind is sent back once | `Stop` | `Stop` | `agent_before_settle` | `experimental.idle` |
| Your commands, no model turn | `/foreman:status` | `foreman status` as a prompt | `/foreman status` | `/foreman status` (TUI, apps) |
| The board (`/foreman`, `verdict`, `pipeline`, `prs`, `issues`, `use`) | no | no | yes | yes: in a dialog in the TUI (its TUI part), as an error notice elsewhere |
| Merge and reject with reasons (`/foreman merge`, `reject`) | no | no | yes, confirmed in pi's selector | in the TUI only (its TUI part), confirmed in its select dialog |
| Allowing a marked finding | typed in an interactive session | not available yet | at pi's interface | confirmed in a TUI dialog (tested, not seen); elsewhere, approved in OpenCode's permission prompt |
| When Foreman must ask you | the permission prompt | refused with the reason | pi's dialog | the permission prompt |
| With nobody attending | refused | refused | refused | refused |
| To try it from a clone | `claude --plugin-dir` | `codex -c hooks.…` | `pi -e` | a link in `.opencode/plugins` (to the folder, for the TUI part) |

The same everywhere: the gate is the Hermes plugin's, on the agent's own machine, so the independent control stays
the required check in CI (`examples/foreman-check.yml`); Foreman's hooks and state are files, guarded against the
plain attempt and not a disguised one.

## The board, on pi and OpenCode

`/foreman` alone is the board there, as in Hermes: the branch and its verdict, the open pull requests and the
issues they close, each change's stages. With it come `verdict [pr|branch]`, `pipeline`, `prs`, `issues` and `use`
(pin the repository for the conversation). It is `plugin/foreman/board.py` as it is, run on a stand-in for Hermes's
context (`foreman_hosts/standin.py`). When a command needs you to choose (which repository), Foreman's program
cannot ask, because it answers one request and ends: it answers with the question, the harness's extension shows it
in its own dialog and sends the command again with your pick (`neutral.py`, "question"). pi has that dialog, and so
has OpenCode's TUI through Foreman's TUI part (`opencode/tui.ts`); OpenCode's server command has none, so there the
command prints the list and what to type. Seen on pi 1.5.0 in real sessions: without a model turn (`pi -p
"/foreman"`, `verdict`, `pipeline`, `use`), on a repository without a GitHub remote and on one with ten open pull
requests. Seen in OpenCode 2.3.2's TUI: the board of the demo repository (eight open pull requests) in a dialog, and
`use` in its select dialog. Claude Code and Codex have no board.

## Merge and reject, on pi and in OpenCode's TUI

`/foreman merge <pr>` and `/foreman reject <pr> [--close] [note]` are the board's own commands too, and they write
to GitHub as you. What Hermes gives the board for that is its terminal tool behind its approval; here it is
Foreman's own `gh` process (no shell, gh's own login, only `gh pr merge`, `gh pr comment` and `gh pr close`),
started only for a command you typed with you at the session. With nobody attending they do nothing, whatever the
command says; the agent's own `gh pr merge` stays refused by the gate, and so does a nested harness started from
the agent's shell to type `/foreman merge`.

A merge goes as in Hermes: the verdict must be CLEAN and GitHub must call the pull request mergeable (neither can
be overridden); then the review, by a fresh session that did not write the code (the one `/foreman review` uses,
so a pull request already reviewed is not sent to a model again), whose verified blocking findings refuse the
merge; then you confirm in the harness's dialog, and GitHub merges exactly the commit Foreman inspected
(`--match-head-commit`) or nothing. Because Foreman's program answers one request and ends, the command runs twice,
once to ask and once with your answer: the second run computes the verdict again and reads the stored review (a
review that failed on the first run is tried once more on the second, which can take minutes again), and
your answer counts only if the question is still the same one (the same commit, the same CI state, the same review
notes). So each merge leaves its gate, review and "waiting for your decision" lines twice in `/foreman pipeline`.

Seen on pi 1.5.0 in its terminal UI, on throwaway pull requests of the demo repository: `/foreman merge 19` reviewed
it, asked in pi's selector with the commit and the command it would run, and merged it by squash; `/foreman reject
20 --close <note>` asked first (closing the selector with Escape posted nothing), then posted the reasons signed
"from pi" and closed it; with `-p` both answered "nobody is attending" and did nothing.

In OpenCode they live in its TUI only: a TUI plugin's slash command runs in the TUI process for what a person typed
at its prompt, and no auto-approve mode answers its dialogs, while OpenCode's server command cannot tell a person
from the HTTP API, the SDK or `opencode api`; through it both answer "nobody is attending". Seen in OpenCode 2.3.2's
TUI on the demo repository: `/foreman reject 3 --close` asked in the select dialog (closed with Escape: nothing
posted), `/foreman merge 3` refused a BLOCKED pull request before any review, and through the server command
`/foreman merge 7` answered "nobody is attending". And a merge carried out to the end: `/foreman merge 21` on a
throwaway pull request reviewed it (PASS, by OpenCode's default model, said as such), asked in the select dialog and
merged it by squash. A rejection carried out to the end was only tested, with a fake `gh`
(`tests/test_hosts_opencode_tui.py`); see [opencode/README.md](opencode/README.md).

## The review in the four

Outside Hermes the review is a fresh session of the harness itself, started by Foreman and never by the agent that
wrote the code (`foreman_hosts/reviewer.py`): no tools, the diff in, one answer out, every finding checked against
the diff. It runs when you ask for it (and, on pi, before a merge); it is advice and unblocks nothing. Each was seen
in a real session: an assertion loosened from an exact value to "is true", which the gate cannot see, came back
BLOCKED with the line quoted, and the same review asked again returned the stored result with no model call.

**At the end of every turn, only if you turn it on** (`reviewer every-turn on`; off by default, per harness; in
Codex it is set in Foreman's `config.json`, like the reviewer itself). Then, when the agent is about to finish a
turn that changed code and the gate finds nothing, Foreman itself starts the reviewer on the change, and a
verified BLOCKING or HIGH finding sends the agent back with it: never twice for the same diff, and in one turn at
most twice besides the gate's own once (the core's own loop and limits, `plugin/foreman/finish.py`). For one
change it stops after three send-backs or four reviews: from then on that change is not reviewed at the end of a
turn, `reviewer` says so, and your own `review` reviews it and gives the four reviews back (on pi, `pipeline`
shows the change waiting for you). A review that could not run does not hold the turn. It costs one more session
of the harness on each such turn, on your account, and the turn waits for it (minutes, with nothing shown). The
agent cannot switch it through a nested harness. Seen on pi 1.5.0: the agent loosened an assertion, the review
sent it back once and the agent put the exact value back. In Claude Code and Codex it was run in the tests,
through their `Stop` hooks, and not seen in a session. OpenCode does not offer it: its plugin stops waiting for
the end of a turn after thirty seconds, so a review started there would be paid for and never read.

| | Claude Code | Codex | pi | OpenCode |
|---|---|---|---|---|
| You ask with | `/foreman:review` | `foreman review` | `/foreman review` | `/foreman review` |
| You choose who reviews with | `/foreman:reviewer` | a file (not from a prompt) | `/foreman reviewer` | `/foreman reviewer` |
| At the end of every turn | `/foreman:reviewer every-turn on` (tested, not seen) | the same file (tested, not seen) | `/foreman reviewer every-turn on` (seen) | not yet |
| With nothing chosen | the default model, one effort level up once the session's effort is known | the session's model | the session's model, one thinking level up | the session's model |
| Does the harness say which model wrote the code | no | yes | yes | yes |
| The answer's form is held by | the harness (a schema) | the harness (a schema) | a seal made for that request | a seal made for that request |
| What the session can still see | nothing of yours | your global instructions; a few tools with no switch | maybe your own appended system text | your global instructions; your MCP servers start |

The review says, in every case, who reviewed and what Foreman does and does not know about it: it never calls the
reviewer "the model that wrote the code" unless the harness named that model, and never "another model" at all.
Where a harness leaves something its session can still see or do, every review there carries a sentence saying so.
Each harness's README has the exact command line of its session and what was measured.

## Claude Code

Not published yet. To install it from the repository, as a marketplace named `foreman-gate` holding the plugin
`foreman` (so its commands stay `/foreman:status` and the rest):

```
claude plugin marketplace add PedValme/foreman
claude plugin install foreman@foreman-gate
```

Seen on Claude Code 2.1.332 with a temporary `CLAUDE_CONFIG_DIR`, from a copy of this repository served as a git
remote on the machine itself: "Successfully added marketplace: foreman-gate", "Successfully installed plugin:
foreman@foreman-gate (scope: user)", and `claude plugin list` showed it enabled at version 0.1.0, copied to
`plugins/cache/foreman-gate/foreman/0.1.0`. The installed copy's hook answered `/foreman:help` when run by hand; a
session was not started (it needs a login). `claude plugin marketplace remove foreman-gate` uninstalls the plugin
with it, so Foreman refuses it to the agent. The `owner/repo` form was run against GitHub too: `claude plugin
marketplace add PedValme/foreman` answered "Successfully added marketplace: foreman-gate", and `claude plugin
install foreman@foreman-gate` installed version 0.1.0.

To try it from a clone instead:

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
- **The review**, `/foreman:review [pull request|branch] [--fresh]`: Foreman starts a fresh Claude Code session that
  did not write the code (`claude -p`, no tools, no project settings, your own login), gives it the diff and checks
  that every finding it returns quotes a line of that diff. It is advisory: it grants, merges and unblocks nothing.
  The same diff by the same reviewer is never sent twice (`--fresh` asks again). Seen: an assertion loosened from
  an exact value to "is true", which the gate cannot see (CLEAN), came back BLOCKED with the line quoted.
- **Who reviews is yours**, `/foreman:reviewer [model] [effort]` (`default` to go back): any model and effort
  `claude` accepts. With nothing chosen it is Claude Code's default model one effort level above the session that
  asked, and the review says in plain words what that is: the model that wrote the code unless you switched model in
  the session, with more effort and a clean context. Claude Code tells a hook the session's effort only on tool and
  stop events and never its model; before the first of them (and always with `-p`) the effort is not raised, and the
  review says so. It takes as long as that model takes: up to a few minutes with nothing shown meanwhile.

- **The review at the end of every turn**, `/foreman:reviewer every-turn on` (off by default): see "The review in
  the four". The `Stop` hook waits up to ten minutes for it. Run in the tests, not seen in a session.

What it does not do: the board, merge and reject with reasons (Foreman on Hermes Agent and on pi have them).

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
