# Foreman

**A green check the agent did not rig.** Foreman is a [Hermes Agent](https://github.com/NousResearch/hermes-agent)
plugin. Other tools prove the check ran; Foreman proves the coding agent did not skip, delete or weaken the tests,
change what the check runs, or commit a secret to get there.

Its detector is deterministic: no model, only Python's standard library and git. It reads the real diff, not the
command text.

## What it blocks

| Rule | What it catches |
|---|---|
| `test-skipped` | skip, only, ignore and expected-failure markers added to tests (see *Known limits* for the list) |
| `test-deleted` | a test code file deleted (snapshots, JSON and fixtures do not count) |
| `test-moved` | a test code file renamed out of the tests |
| `check-changed` | with no configuration: a change to the `test`/`check`/`lint` scripts of a `package.json` (with `test:*` and the scripts they run), the `test`/`check`/`ci` targets of a `Makefile` (with the test targets and variables they use), or tox's `envlist` and `commands`/`setenv` of `[testenv*]` (only what exists at the base); plus, with `.foreman.json`, any change to a file its check command runs, or to `.foreman.json` itself |
| `check-weakened` | `\|\| true` or `continue-on-error: true` in `.github/workflows/*` next to a test runner; `--deselect` / `--ignore=` pointing at tests in pytest config; `testPathIgnorePatterns` / `exclude` in jest or vitest config (not in coverage settings) |
| `secret`, `env-file` | real credential formats (cloud, GitHub, model APIs, Slack, Stripe, private keys…) everywhere; key/value guesses (passwords in code, config, shell, YAML, `.env`) outside the tests, and in tests only long values mixing upper case, lower case and digits |
| `secret-history` | a secret in any commit of what is pushed, even if a later commit removed it |

It also refuses `git commit --no-verify` / `-n`, `git push --no-verify`, `git -c core.hooksPath=…`, hook-disabling
variables in front of a commit or push or exported for later calls (`HUSKY=0`, `SKIP=…`, `PRE_COMMIT_ALLOW_NO_CONFIG=1`,
`LEFTHOOK=0`, …) and `git config core.hooksPath …` (set or unset).

## When it acts

- **Before a publishing command** (`pre_tool_call`): `git commit`, `git push`, `gh pr create` and `gh pr merge` run
  by the agent's terminal tool, also inside `cd x && …`, `git -C x …`, `bash -c "…"` and `cmd /c …`. A blocker
  returns `block` with each finding (file:line, rule, the real fix). The gated command must run on its own: when an
  earlier part of the same line could change what it records (`git rm x && git commit`, `sed -i … && git commit`,
  `git commit && git push`), Foreman asks the agent to run it separately. `git add`, `cd`, `echo` and read-only git
  commands may come first.
- **Before a test file is written** (`write_file`, `patch`): adding a marker that switches a test off is refused.
- **Before the agent finishes a coding turn** (`pre_verify`, once per turn): if the uncommitted changes would rig the
  check, the agent is told exactly what to undo.

### False positives: only you can allow them

The agent marks a false positive on its line with `foreman:allow`, or, for a deleted, moved or check file, with a
commit-message line `foreman:allow <path>: <reason>`. The mark never passes alone: the finding stays blocked with a
short id, and the agent is told to ask you. You review it and run:

```
/foreman allow           list what is waiting
/foreman allow <id>      allow that exact finding for 24 hours
```

An exception covers exactly what you reviewed. For a marked line: that line's content and the next non-empty line
(the test it skips), so the same line copied above another test needs its own decision. For a file (a changed or
weakened check, a moved or deleted test): that version of the file, so any later change to it is checked again. Slash commands are typed by you; the model has no tool that runs them. This works the same in every approval
mode, YOLO included.

### When Foreman asks for approval instead

`gh pr merge` run by the agent is always refused: merging is your decision, through `/foreman merge` (see *Use*);
no approval answer or YOLO lets the agent merge. A push of several branches (`--all`, `--mirror`, several refspecs)
and any command Foreman could not inspect (git error, its 18 s time budget, a working directory that does not exist
on the Hermes host) ask a person instead, with Hermes's approval prompt; an "always" answer for a push of several
branches covers only those exact commits. **In YOLO mode or with approvals off, Hermes lets these through without a
person.**

## Use

```
/foreman                     the board: branch vs base, open pull requests, the issues they close
/foreman use [path|n]        pin the repository for this session (no argument: pick one)
/foreman prs | issues        focused views of the open pull requests or issues
/foreman verdict [pr|branch] the verdict (table below), each reason as [rule] file:line and its fix
/foreman merge <pr> [--merge|--rebase] [--yes]   merge it, only if CLEAN, ready, reviewed and you confirm
/foreman reject <pr> [--close [--yes]] [note]    post the reasons as one comment on the pull request
/foreman status [path]       the verdict for the current repository, with reasons
/foreman allow [id]          list or allow findings the agent marked
/foreman review [pr|branch] [--fresh]  a second model reviews the diff (see below)
/foreman pipeline [pr|branch] a change's stages: gate, review, bounces, owner, merge
/foreman notify [on [target]|off|test]   tell you on your phone when a PR waits for you (off by default)
/foreman help
```

The board is plain text, one screen, the same in a terminal, the Desktop app and messaging:

```
Foreman board: acme/widgets
Repository: /home/me/src/widgets
  (the repository pinned with /foreman use)
Branch: fix/parser  vs origin/main · 2 ahead · 0 uncommitted · CLEAN

Pull requests (1 open):
  #7    Fix the parser
       fix/parser · CI failing (1 of 2) · closes #3, #5

Issues no open PR closes (1):
  #9    Crash on empty input  [bug]

Next:
  /foreman verdict 7       clean or blocked, and why
  /foreman issues          every open issue and its PR
```

**Which repository.** `/foreman use <path>` pins one for the session; `/foreman use` offers recently used
repositories and the git repositories around the session's directory with Hermes's picker (in a chat without
buttons, or where Hermes cannot ask, it prints a numbered list: `/foreman use 2`). Without a pin, Foreman resolves the
repository as described in *Known limits*.

**Pull request verdicts.** When the clone has the pull request's head commit, `/foreman verdict <pr>` runs the full
check on it, history included. Otherwise it reads GitHub's diff (`gh pr diff`) without touching your working tree;
a secret added and removed again in an earlier commit is then not seen, and the output says so.

Foreman's verdict is about rigging, with one vocabulary everywhere (status, board, verdict, merge, review, the
`foreman_check` tool, the pipeline and CI):

| Verdict | Meaning | Merge |
|---|---|---|
| **CLEAN** | nothing found, and everything Foreman was told to inspect was inspected | allowed, after you confirm |
| **BLOCKED** | a skipped, deleted or moved test, a change to the check, a secret, a blocking SARIF result | refused |
| **INCOMPLETE** | something it was told to inspect could not be (an unreadable SARIF report, a git error, the time budget) | refused |
| **NEEDS YOUR OK** | only findings the agent marked `foreman:allow`, waiting for `/foreman allow <id>` | refused until you allow them |

Whether GitHub can merge the pull request now is a separate fact, and the verdict says both:

```
Foreman verdict for PR #4: CLEAN — but not mergeable yet
  SARIF source and CI mode
  claude/sarif-ci -> main · conflicts
  CI: no CI checks (none run while it conflicts)
  Closes: no issue
No skipped, deleted or moved tests, no change to the check, no secrets.
Not mergeable yet:
  - it conflicts with main: update the branch (merge or rebase main into it,
    resolve, push).
Next: fix what is listed above, then `/foreman verdict 4` again.
```

A pull request is ready to merge when Foreman finds it CLEAN, GitHub reports no conflict, and it is not a draft.
CI is shown but does not decide: failing, running or absent CI makes the hint cautious and is the first line of the
merge question. "no CI checks" means GitHub reported none (it runs no `pull_request` checks while a pull request
conflicts); "CI unknown" means Foreman could not read them.

**Merge and reject.** `/foreman merge <pr>` refuses when the verdict is BLOCKED or cannot be computed, and when the
pull request conflicts, is a draft, or GitHub is still computing whether it can merge (it says what to do; `--yes`
does not override any of these). When it is ready, Foreman asks you with Hermes's picker: *Merge PR #7 (abc1234,
squash) into main?*, with the title, the linked issues and the CI state (a warning first when CI is not passing),
and only **Merge** goes on. Where Hermes cannot ask (a cron job, a chat without choices) or nobody answers in time,
nothing is merged and Foreman prints the command to confirm by typing it: `/foreman merge 7 --yes`. `--yes` skips
the question, never the verdict. The merge runs `gh pr merge <pr> --squash
--delete-branch --match-head-commit <sha>` (so only the commit it inspected is merged) through Hermes's own terminal
tool, never from its own subprocess.
`/foreman reject <pr>` posts one Markdown comment with the reasons (and a saved model review, if there is one, and
your note) with `gh pr comment`, the same way, and shows you the exact text. A comment can be answered or deleted,
so it is posted without a question; `--close` also closes the pull request and asks first, the same way as a merge.
A pull request with no blocker is rejected only with a note.

**Without GitHub** (no `gh`, not logged in, or no GitHub remote) the board lists the local branches with their
verdict and says what is missing; `/foreman verdict <branch>` still works.

The agent can call the `foreman_check` tool for the same verdict as JSON.

`check-changed` protects the usual test entry points with no configuration (see the table). To protect the exact
check you run, name it in `.foreman.json` **at the base** (the branch's merge-base, or `HEAD` for a commit), so a
change cannot redefine its own check (in CI you can also pass `--check`):

```json
{"check": "bash scripts/check.sh"}
```

## Use a SARIF report as a source

Foreman can read a [SARIF 2.1.0](https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html) report from a
scanner and add its results to the blockers. **Foreman never runs the scanner**: it only reads the file you point it
at, so the report must be produced beforehand (and a stale one is only flagged, see below).

Example with the official `hermes-security` plugin, which exports SARIF
(`tool.driver.name` = `hermes-security`):

```
hermes security-review export --scan <scan-id> --format sarif --out results.sarif
python -m foreman.detector origin/main HEAD --sarif results.sarif
```

or list the report in `.foreman.json`, read **at the base** like `check`, so `/foreman status`, the hooks and CI all
see it and a change cannot point it elsewhere (editing these keys, or a tracked report they name, is a
`check-changed` blocker):

```json
{"sarif": ["reports/results.sarif"], "sarif_threshold": "error"}
```

- **Rule id** `sarif:<tool>/<ruleId>`, with the file and line of the first location.
- **Severity** of a result: its `security-severity` (0-10), else the named `properties.severity` that
  hermes-security writes (its rule-level score is the maximum over the rule's findings), else the rule's
  `security-severity`, else `level`, else the rule's default level, else `warning`.
- **Threshold**: results at or above it block; the rest are listed as notes. `error` (7.0, the default), `warning`
  (4.0) or a number 0-10, with `--sarif-threshold` or `sarif_threshold`.
- **Scope**: by default only results located in files the change touches, or with `baselineState` `new` or
  `updated`, can block; every other result (old debt) is a note; a result with no location cannot be scoped to a file and always blocks, so existing findings do
  not stop every commit. `"sarif_scope": "all"` in `.foreman.json`, or `--sarif-scope all`, lets every result block.
- **Never blocks, not even listed**: suppressed results (accepted or without status), `baselineState: "absent"`, and
  results whose `kind` is present and not `fail`.
- **Staleness** means code changed after the scan: in the working tree, a changed (or untracked) file more than 2
  seconds newer than the report; in a push, pull request or CI range, a head commit more than 120 seconds newer than
  the report that touches files other than the report. It adds the note "SARIF report is older than the changes it
  gates" and does not block.
- **Missing or unreadable report**: if the base's `.foreman.json` names it, Foreman cannot say the change is clean:
  the hooks ask for approval ("could not read the SARIF report <path> named in .foreman.json"), `/foreman status`
  says `INCOMPLETE` (and so do the board, `/foreman verdict` and `/foreman merge`, which refuses), and CI exits 2; the same for `--sarif`. A report with zero results is a valid clean scan.
  Reports over 20 MB are not read.
- **The agent cannot edit the report**: `write_file` and `patch` on a path listed under `sarif` in the base's
  `.foreman.json` are blocked (regenerate it with the scanner), and a command that redirects output into it before a
  `git commit` or `git push` in the same line is blocked as an unsafe segment. A report generated by a separate
  command the agent runs is outside what Foreman can see: in CI, generate it in a step the agent cannot edit.
- **Notes** (below the threshold, outside the scope, stale) show as one line in `/foreman status` and in the hook
  messages: the count and the first two.

## CI mode: a required check

```
python -m foreman.detector origin/<base> HEAD [--check "<command>"] [--sarif FILE] [--strict] [--json]
```

The `foreman` package is in the `plugin/` folder of the repository: run the detector with that folder on
`PYTHONPATH` (`PYTHONPATH=<foreman checkout>/plugin python -m foreman.detector …`), from the repository you check.
The same holds for the `python -m foreman.detector` lines above.

Exit codes: **0** clean, **1** at least one blocker, **2** the run could not be done (not a repository, git failed,
a SARIF report that cannot be read, whether given with `--sarif` or named in `.foreman.json`).
[`examples/foreman-check.yml`](https://github.com/PedValme/foreman/blob/main/examples/foreman-check.yml) is a workflow to copy: full-history checkout, actions
pinned by commit SHA, Foreman downloaded at a pinned commit SHA, the base branch passed through `env`, the detector
run against the pull request's base. Make it a required check: unlike the hooks, it runs where the agent cannot edit
it.

Findings marked only with `foreman:allow` are listed and exit 0 in CI: Foreman does not decide for a person, so a
human reviews them in the PR. With `GITHUB_ACTIONS` set, each one is also printed as a `::warning` annotation on the
file and line. `--strict` makes them blockers (exit 1) for teams where nobody waves a finding through.

## Second-model review

`/foreman review` asks a model **other than the one that wrote the code** to read the diff and look for what the
detector cannot see: emptied tests, removed or loosened assertions, tests rewritten to assert the bug,
commented-out tests, mocks that replace the code under test, checks made non-blocking, swallowed errors,
hardcoded expected values, secrets, destructive or irreversible changes, auth and permission changes, and bugs the
change introduces.

```
/foreman review          the current branch against its base, plus uncommitted changes
/foreman review 42       pull request #42 (read-only `gh pr diff`; needs the GitHub CLI)
/foreman review my-feat  a local branch against its base
```

- **When it runs.** When you type the command, and as *The pipeline* below sets it (`auto_review`); never inside a
  hook. Each run is one model call and **costs tokens** on your provider (up to about 30k tokens of diff plus the
  answer); the same diff is never reviewed twice unless you type `/foreman review --fresh`.
- **What leaves your machine:** the diff (bounded, see below), the branch or pull request title and commit subjects,
  and the detector's findings go to the model provider you configured in Hermes, through Hermes (`ctx.llm`; Foreman
  never sees your keys). Nothing else is sent, and Foreman makes no network call of its own (`gh` talks to GitHub
  for a pull request number).
- **Which model:** the `reviewer_model` setting (Desktop: Settings → Plugins → foreman; or `config.yaml`, below);
  without it, the first model of your Hermes fallback chain (`fallback_providers`); without one, your active model.
  Choosing a model needs the `llm.model_override` capability (and `llm.provider_override` when it lives on another
  provider), which Hermes asks you to grant when you enable the plugin. Without the grant the review runs on your
  active model. The output always names the model that reviewed, and says so when it is the same one that wrote the
  code: *"Reviewed by the same model that wrote the code — set `reviewer_model` for an independent review."*

  ```yaml
  plugins:
    entries:
      foreman:
        settings:
          reviewer_model: anthropic/claude-haiku-4.5   # as your provider names it
          reviewer_provider: openrouter                 # only when not your active provider
  ```
- **Verdict.** `BLOCKED` when the detector blocks or the model reports a verified BLOCKING finding (a rigged test or
  check, a secret, harm to data or production, a loosened control); `PASS WITH NOTES` for verified HIGH/MEDIUM
  findings, unverified findings or a partly reviewed diff; `PASS` only when the detector found nothing and the model
  reported nothing. Every finding must quote the diff verbatim: a quote that is not in that file's diff is dropped and
  counted as unverified, so a model's claim alone never blocks, and a dropped claim still keeps the verdict off
  `PASS`. `PASS` means "no verified findings", not "approved": a model can miss things, or be steered by the diff.
  A model error, refusal, timeout or malformed answer gives *review could not run*, never a pass.
- **Advisory.** The review grants, merges and unblocks nothing; the gate and `/foreman allow` work exactly as without
  it. Text in the diff that tries to steer the reviewer (telling it to approve, or to drop its rules) is treated as data:
  the prompt fences the diff with a random token and tells the model never to follow it.
- **Bounded, and honest about it.** Lockfiles, generated and binary files are left out; tests and check files go
  first; each file is cut at 30,000 characters and the whole diff at 120,000. The output lists what was left out or
  cut and never reports full coverage when it was not.
- **Stored.** The last review of each repository and target is kept in Foreman's data directory
  (`reviews/<owner>__<repo>__pr<N>.json`, or `…__branch-<name>-<hash>.json` / `…__worktree-<name>-<hash>.json`):
  model, time, verdict, verified findings and coverage.
- A fallback on a custom endpoint (`base_url`) cannot be selected by a plugin; Foreman says so and uses your active
  model.
- **Limits.** A model can miss issues, and a quote that exists can still back a wrong conclusion: read the findings.
  The same-model check compares with the main model in your config; a model you switched to inside the session is
  not visible to plugins. For a pull request number the detector sees only the PR's diff (`check-changed` and
  `secret-history` need the branch checked out: run `/foreman status` there).

## The pipeline

Each change (a pull request, or a branch before it has one) moves along a small line:
**write -> gate -> second-model review -> bounce back to the agent -> ready -> you approve -> merge.**
`/foreman` shows one line per change, and `/foreman pipeline [<pr>|<branch>]` its stages and last events:

```
Pipeline (1 change):
  #6  bounced
    gate ok > review FAIL (2 blocking) > bounced 1/3 > owner - > merge -
```

The setting `auto_review` decides when the second model reviews (and so when it spends tokens):

| `auto_review` | When the model is called | What happens |
|---|---|---|
| `merge` (default) | when you run `/foreman merge <pr>` and the pull request's exact diff has no stored review | verified BLOCKING findings refuse the merge (`--yes` does not override); notes go in the merge question; if the review could not run, the question says so first and you decide |
| `finish` | inside the agent's coding turn, through its `foreman_review` tool, once per new diff | the change is sent back with each BLOCKING and HIGH finding (file:line, why, fix) until the review is clean or the bounce limit is hit |
| `off` | only when you type `/foreman review` | merge works as without the reviewer |

- **No re-rolling.** A review is stored with a hash of the exact diff and the reviewer; the same diff returns the
  stored result and never calls the model again. Only a changed diff, or your `/foreman review --fresh`, runs it again.
  The agent's `foreman_review` tool calls a model only with `finish`; at other levels it returns the stored review or
  tells the agent to ask you. It is advisory: it never grants, merges, approves or unblocks anything.
- **The bounce limit.** `max_bounces` (default 3, never more than Hermes's own `agent.max_verify_nudges`) bounds how
  many times a change goes back to the agent; then Foreman stops, marks it as needing you, and calls the reviewer no
  more for it. The end-of-turn hook only reads stored reviews: the model runs in the tool, never in a hook.
- **A person always merges.** No level merges anything: `/foreman merge` asks you (or takes your typed `--yes`), and
  where nobody can be asked, nothing merges.
- **Where it lives.** `pipeline.json` in Foreman's data directory (one entry per change, at most 200, with its last
  50 events), next to `pipeline-meta.json` (which notifications were sent, which diffs were counted).
- **Repositories without tests.** The board and `/foreman status` say it once: the gate can then catch only secrets
  and hook bypasses, and the second-model review is the main check.

```yaml
plugins:
  entries:
    foreman:
      settings:
        auto_review: merge   # merge | finish | off
        max_bounces: 3
```

## Desktop panel

Hermes Desktop (and the Webapp it serves) can show each change on Foreman's line, **Gate → Review → Owner →
Merge**: one card per pull request or branch, with a marker at the station where it is now, the bounces back to the
agent (`1/3`), each station's detail and the latest events. Changes waiting for you come first; finished ones fold
away. A status-bar chip says `Foreman · 2 waiting for you`.

To turn it on, after installing and enabling Foreman (below): in Hermes Desktop open **Capabilities → Plugins**, find
**Foreman** and switch on its **Desktop** column (a plugin's Desktop half ships switched off; click **Rescan** if the
row does not show it yet). The **Foreman** pane opens beside the chat; **Ctrl/⌘ K → Foreman: show the line** brings it
back.

- It reads only Foreman's own state file (`pipeline.json` in its plugin data directory), through a read-only route
  Hermes mounts for enabled plugins (`GET /api/plugins/foreman/pipeline`, `dashboard/plugin_api.py`). It polls that
  route every 2 s while the pane is on screen and every 15 s otherwise, never while the window is hidden; no network
  calls, nothing written.
- Its buttons only put a Foreman command into the chat, the same text you would type: **Merge #6** sends
  `/foreman merge 6` (which checks the verdict again and asks you to confirm), **Reject…** and **Review again…** put
  the command in the chat box for you to finish (never over text you are typing), **Show verdict** sends
  `/foreman verdict …`. If the chat box is not available, the command is copied to the clipboard for you to paste;
  **Open ↗** opens the pull request in your browser. Merge, reject and verdict name the card's repository
  (`/foreman merge 6 --repo acme/widgets`; `--repo` takes only a repository Foreman already knows). The panel offers
  no command it cannot point at the right repository.
  The panel never runs `gh` or merges by itself.
- Titles, branch names and event lines are shown as plain text, never as HTML or Markdown.

To look at it without Hermes, in a clone of the repository: `python examples/panel-preview/build.py`, then open
`examples/panel-preview/index.html` (scripted scenarios, light and dark, reduced motion).

## Notifications

Off by default: nothing is sent anywhere until you type `/foreman notify on <target>` (or ask for a sample with
`/foreman notify test`). The target is where Hermes's
own `hermes send` would deliver: `telegram` (your Telegram home channel, the chat where you ran `/sethome`),
`telegram:<chat id>`, `discord:#channel`, `slack:<channel id>`, and the other platforms your Hermes is set up for.
Typed in a chat, `/foreman notify on` uses that platform's home channel. `/foreman notify test` sends a sample now,
`/foreman notify` shows the state and the last message, `/foreman notify off` stops them. The same two settings
(`notify`, `notify_to`) are on the plugin's page in the Desktop.

**What is sent.** One short plain-text message each time Foreman's pipeline reports that a pull request is ready
for you or needs your decision (or was merged or rejected), once per pull request head: the repository, the pull request's number and
title, its branch and head commit, the one-line verdict, the link, and the commands to act on it. On Telegram:

```
Foreman: PR #6 is ready to merge and waits for you
Repository: acme/widgets
Title: Retry the upload on a timeout
Change: branch feat/retry-upload · head 1a2b3c4
Verdict: CLEAN: no skipped, deleted or moved tests, no change to the check, no secrets. CI passing.
https://github.com/acme/widgets/pull/6

Merge (Foreman checks it again, then asks you with Merge / Cancel buttons):
/foreman merge 6 --repo acme/widgets
Reject (add your reason at the end; Foreman posts it with its findings):
/foreman reject 6 --repo acme/widgets
Tap a command to copy it, then send it to this chat. Nothing is merged until you confirm there.
```

The title, branch and verdict are made inert first: no Markdown or HTML, no @mentions, no clickable links, and no
Hermes media directive, so a crafted pull request title cannot ping people, add a link or make Hermes attach a file.

**A message is never a confirmation.** Hermes gives plugins no public way to put buttons on a message that answer
back to the plugin, so the message carries commands, not buttons. When you send `/foreman merge 6 --repo
acme/widgets` in the chat, it is exactly the command described in *Merge and reject*: a fresh verdict, refused when
BLOCKED, conflicting, a draft or still being computed, and then Hermes's own **Merge** / **Cancel** buttons (on
Telegram, Discord and Slack; a numbered list elsewhere). `--repo` accepts only a repository you already used on this
machine (pinned with `/foreman use`, or reported with its path by Foreman's pipeline), by its remote's `owner/name`
or its exact path; any other value is refused before Foreman opens it, so a command copied from a message only acts
on repositories you already work with.

**The network path.** Foreman runs `hermes send --to <target> --file <message> --quiet` through Hermes's own
terminal tool. Your Hermes and your own bot deliver it; Foreman never reads a token or a credential file. The
message file lives in Foreman's data directory for the moment the command runs. With a Docker or remote terminal
backend `hermes` is not there, and the message is not sent (the reason is returned and shown by `/foreman notify`).
A send waits for `hermes send` for at most 60 s; one that fails or times out is reported, never retried. The
message file and the log of sends are Foreman's state: the agent's commands and writes that name them are blocked,
like the rest of its data directory.

## Install

```
hermes plugins install PedValme/foreman/plugin
hermes plugins enable foreman
```

The plugin is the repository's `plugin/` folder, so that is all Hermes copies. Add `--ref <40-character commit SHA>`
to install exactly the commit you reviewed.

Requires Hermes Agent >= 0.22.6 and git on the PATH.

## What it does on your machine (disclosure)

- **Runs `git`** as a subprocess (read-only commands: `diff`, `diff-tree`, `log`, `ls-files`, `rev-parse`,
  `rev-list`, `merge-base`, `cat-file`, `show`, `status`, `remote`, `symbolic-ref`, `for-each-ref`, `hash-object`
  without `-w`) in the repository the agent works in. It never commits,
  pushes, merges or changes your repository.
- **Reads files** of that repository: untracked files (up to 500, 512 KB each) to look for secrets and markers, the
  file a `write_file` would replace, `package.json` to compare its scripts, and a commit message file given with
  `-F`. It may read a non-ignored `.env` only to warn before it is committed; values are never printed or stored.
- **Writes in its Hermes plugin data directory** only: `foreman-grants.json` (the findings waiting for you and the
  exceptions you allowed: rule, file, line, message; no file contents), `foreman-board.json` (the repository pinned
  per session and the last ten you used: paths only), `reviews/*.json` (the last `/foreman review` of each target;
  its findings quote lines of the diff, and `/foreman reject` includes them; `reviews/cache/` keeps up to 300 of
  them by diff), `pipeline.json` and `pipeline-meta.json` (each change's stages and events: repository, branch, pull
  request number and title, short finding summaries), and, for a moment, the text of a
  `/foreman reject` comment in `outbox/` (deleted once `gh pr comment` has read it), and, with notifications on,
  `foreman-notify.json` and, for a moment, a message in `notify/`. Foreman blocks the agent's
  `write_file`, `patch` and terminal commands that name these files or directories. This guard is best effort: it
  matches text, so a glob, a relative path after `cd`, or Hermes's `execute_code` gets past it.
- **Runs the GitHub CLI (`gh`) only when you type a `/foreman` subcommand**, as a subprocess with its own login, in
  the repository's directory. These calls contact GitHub and only read: `gh repo view`, `gh pr list`, `gh issue list`,
  `gh pr view` and `gh pr diff`. Foreman never reads `gh`'s token or configuration files, nor any other credential.
- **Writes to GitHub only on your explicit command**: `/foreman merge <pr>` runs `gh pr merge`, and `/foreman reject
  <pr>` runs `gh pr comment` (and `gh pr close` with `--close`). They run through Hermes's terminal tool
  (`ctx.dispatch_tool("terminal", …)`). A merge and a close wait for your confirmation in Hermes's picker (or your
  typed `--yes`); a comment is posted on the command you typed. Nothing is merged, commented or closed otherwise, and
  never by the agent. `gh pr merge --delete-branch` also deletes the pull
  request's branch on GitHub and the local branch, switching to the base branch if it was checked out.
- Reads the working directory the terminal tool recorded for the session, through a Hermes internal
  (`tools.terminal_tool.get_session_cwd`), guarded, then the public `ctx.session_cwd()`, with Hermes's documented
  `resolve_agent_cwd()` as fallback.
  `/foreman use` also lists the directories directly inside the session's directories to find git repositories.
- **Model calls only when you run `/foreman review`, or as `auto_review` sets it** (`/foreman merge` with `merge`,
  the default; the agent's `foreman_review` tool with `finish`; see *The pipeline*), at most once per exact diff:
  one call through Hermes (`ctx.llm`) with the diff, the title and the detector's findings; it spends tokens on your
  provider. For a pull request number it runs `gh pr
  view` and `gh pr diff` (read-only). To pick the reviewer it reads, through Hermes's config reader, your main model
  and the provider and model names of the first fallback entry; nothing else of your config.
- **Notifications, only after you turn them on** (`/foreman notify on <target>`): one `hermes send` per pull request
  event, through Hermes's terminal tool, to the target you chose (see *Notifications*). It records the last 30 sends
  (kind, pull request id, target, outcome) in `foreman-notify.json` in its data directory.
- **No network calls of its own** (only the `gh` commands above, the review's model call, and the notifications you
  turned on, sent by Hermes), no telemetry, no credentials, no background processes.
- It registers two hooks (`pre_tool_call`, `pre_verify`), one slash command (`/foreman`) and two tools
  (`foreman_check`, `foreman_review`), and declares two capabilities, `llm.model_override` and
  `llm.provider_override`, used only by the second-model review to run on a model other than your active one.

## Known limits

- A SARIF report replaced by a separate command (for example `cp empty.sarif results.sarif`) is not noticed:
  generate it in a CI step the agent cannot edit.
- It sees the tree as it is **before** the gated command runs; that is why it asks for the gated command on its own.
- Commits made by an interpreter (a Python or Node script calling git, Hermes's `execute_code`), by git aliases or
  by other tools are not inspected at that moment; the next `git push` or `gh pr create` still sees what they
  committed. Foreman also does not model `GIT_INDEX_FILE` or `GIT_DIR` set in the environment of a git command.
- The detector does not detect emptied test bodies, removed asserts, commented-out tests, or a test function deleted
  from a file that still exists: only markers, whole-file deletions and moves, and changes to the check.
  `/foreman review` looks for those with a model, advisory only.
- Tests switched off by selection are not detected: `-k 'not x'` in pytest `addopts`, or a `jest` section with
  `testPathIgnorePatterns` inside `package.json`.
- Markers covered: pytest (`skip`, `xfail`, `skipif`), unittest (`skip*`, `expectedFailure`, `skipTest`),
  Jest/Vitest/Mocha/Jasmine (`.skip`, `.only`, `.concurrent`, `.each`, `.skipIf`, `xit`, `xtest`, `xdescribe`,
  `fit`, `fdescribe`, `this.skip()`), Go (`t.Skip*`), Rust (`#[ignore]`), JUnit (`@Disabled`, `@Ignore`), and
  `raise SkipTest` / `raise unittest.SkipTest` / `raise pytest.skip.Exception`. A conditional skip in a new test file is allowed; added to an
  existing test it is blocked. A test renamed so the runner stops collecting it (`def test_x` to `def _test_x`,
  `class TestX` to `class _TestX`, `func TestX` to `func _TestX`, `it("x", …)` to `it.todo`/`xit`/`_it` in the same
  file) counts as skipped.
- Check protection covers the entry point named in `.foreman.json` (not everything it runs), the default entry
  points in the table, and the narrow `check-weakened` patterns above. A `noxfile.py`, or a test command in
  `pyproject.toml` or `setup.cfg`, is not protected without `.foreman.json`.
- Hook-disabling variables are seen in front of the gated command and when exported in a terminal call; one set in
  the shell's profile, by a script, or a hook manager's own config file switching hooks off, is not.
- A test switched off by a rename Foreman does not know (`test_x` to `tst_x`), by a `return` at its top, or by a
  decorator Foreman does not know is not detected; `/foreman review` may see it. A gated command run through a
  program Foreman does not follow is refused until it runs on its own; one hidden inside a script file is not seen.
- In a shared chat, any member Hermes authorises can type `/foreman merge … --yes`; Foreman does not check who typed
  it — restrict who can talk to your Hermes.
- Secrets are found by pattern: real credential formats reliably, key/value guesses with false negatives (and none
  inside test files).
- Repository resolution: for `/foreman` subcommands, a repository pinned with `/foreman use` comes first. Then
  Foreman tries, in order, the directory the terminal tool recorded for the session, the
  session's working directory from Hermes's public `ctx.session_cwd()`, then (in
  the CLI and TUI only) the process directory, then Hermes's `resolve_agent_cwd()`, and uses the first one inside a
  git repository. Hermes's own data is never picked unless the terminal recorded it: nothing inside a Hermes home
  (the profile home or the root that holds the profiles), and no repository whose root contains one. The first is
  read from a Hermes internal, guarded: if Hermes moves it, Foreman falls back to the others. A relative path is
  resolved against the same candidates, never against the gateway's own directory; with none, Foreman says it cannot
  tell. When nothing
  qualifies, `/foreman status` says it cannot tell instead of guessing, and a gated command that does not say where
  it runs is blocked with a `workdir` hint. `/foreman status` names how it chose when it did not use the terminal's
  directory. An explicit path, `workdir`, `cd` or `git -C` always wins. When a command does not say where
  it runs and no candidate is a repository, Foreman asks the agent to re-run it with `workdir` or `git -C`.
- With a remote terminal backend (Docker, SSH, …) the repository is not on the Hermes host: Foreman asks for
  approval on every gated command.
- In YOLO mode or with approvals off, the cases in *When Foreman asks for approval instead* pass without a person.
- With a remote terminal backend (Docker, SSH, …), the verdict is computed on the Hermes host but `gh pr merge` runs
  on the backend, in the host's path, where it may fail or find another clone; `--match-head-commit` still keeps
  it from merging any commit but the inspected one. `/foreman reject` cannot hand the comment file to `gh` there; it
  then says the comment was not posted and shows its text.

## Development

In a clone of the repository, from its root (the tests live outside `plugin/`, so they are not installed):

```
python -m unittest discover -s tests -q
hermes plugins validate plugin --install-deps
hermes plugins doctor plugin
```

Test fixtures that look like secrets are assembled at runtime, never written as literals.

## License

MIT
