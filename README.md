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
| `check-changed` | a change to a file the check command runs, or to `.foreman.json`; for `package.json`, only its `scripts` |
| `check-weakened` | `\|\| true` or `continue-on-error: true` in `.github/workflows/*` next to a test runner; `--deselect` / `--ignore=` pointing at tests in pytest config; `testPathIgnorePatterns` / `exclude` in jest or vitest config (not in coverage settings) |
| `secret`, `env-file` | real credential formats (cloud, GitHub, model APIs, Slack, Stripe, private keys…) everywhere; key/value guesses (passwords in code, config, shell, YAML, `.env`) outside the tests, and in tests only long values mixing upper case, lower case and digits |
| `secret-history` | a secret in any commit of what is pushed, even if a later commit removed it |

It also refuses `git commit --no-verify` / `-n`, `git push --no-verify` and `git -c core.hooksPath=…`.

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

`gh pr merge` run by the agent always asks a person (a merge is never automatic; `/foreman merge` asks you in its
own way, see *Use*). So do a push of several branches (`--all`,
`--mirror`, several refspecs) and any command Foreman could not inspect (git error, its 18 s time budget, a working
directory that does not exist on the Hermes host). These use Hermes's approval prompt: **in YOLO mode or with
approvals off, Hermes lets them through without a person.**

## Use

```
/foreman                     the board: branch vs base, open pull requests, the issues they close
/foreman use [path|n]        pin the repository for this session (no argument: pick one)
/foreman prs | issues        focused views of the open pull requests or issues
/foreman verdict [pr|branch] MERGEABLE or BLOCKED, each reason as [rule] file:line and its fix
/foreman merge <pr> [--merge|--rebase] [--yes]   merge it, only if MERGEABLE and you confirm
/foreman reject <pr> [--close [--yes]] [note]    post the reasons as one comment on the pull request
/foreman status [path]       verdict for the current repository: CLEAN or BLOCKED, with reasons
/foreman allow [id]          list or allow findings the agent marked
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
  /foreman verdict 7       mergeable or blocked, and why
  /foreman issues          every open issue and its PR
```

**Which repository.** `/foreman use <path>` pins one for the session; `/foreman use` offers recently used
repositories and the git repositories around the session's directory with Hermes's picker (in a chat without
buttons, or where Hermes cannot ask, it prints a numbered list: `/foreman use 2`). Without a pin, Foreman resolves the
repository as described in *Known limits*.

**Pull request verdicts.** When the clone has the pull request's head commit, `/foreman verdict <pr>` runs the full
check on it, history included. Otherwise it reads GitHub's diff (`gh pr diff`) without touching your working tree;
a secret added and removed again in an earlier commit is then not seen, and the output says so.

**Merge and reject.** `/foreman merge <pr>` refuses when the verdict is BLOCKED or cannot be computed. When it is
MERGEABLE, Foreman asks you with Hermes's picker: *Merge PR #7 (abc1234, squash) into main?*, with the title, the
linked issues and the CI state, and only **Merge** goes on. Where Hermes cannot ask (a cron job, a chat without
choices) or nobody answers in time, nothing is merged and Foreman prints the command to confirm by typing it:
`/foreman merge 7 --yes`. `--yes` skips the question, never the verdict. The merge runs `gh pr merge <pr> --squash
--delete-branch --match-head-commit <sha>` (so only the commit it inspected is merged) through Hermes's own terminal
tool, never from its own subprocess.
`/foreman reject <pr>` posts one Markdown comment with the reasons (and a saved model review, if there is one, and
your note) with `gh pr comment`, the same way, and shows you the exact text. A comment can be answered or deleted,
so it is posted without a question; `--close` also closes the pull request and asks first, the same way as a merge.
A pull request with no blocker is rejected only with a note.

**Without GitHub** (no `gh`, not logged in, or no GitHub remote) the board lists the local branches with their
verdict and says what is missing; `/foreman verdict <branch>` still works.

The agent can call the `foreman_check` tool for the same verdict as JSON.

`check-changed` needs to know the check command. It comes from `.foreman.json` **at the base** (the branch's
merge-base, or `HEAD` for a commit), so a change cannot redefine its own check. Without that file, `check-changed`
is off (in CI, pass `--check`):

```json
{"check": "bash scripts/check.sh"}
```

### CI mode

```
python -m foreman.detector <base> [<head>] [--check "<command>"] [--json]
```

Exits 1 when there is a blocker. Findings marked `foreman:allow` do not fail the run; they are listed for the
reviewer.

## Install

```
hermes plugins install PedValme/foreman
hermes plugins enable foreman
```

Requires Hermes Agent >= 0.22.6 and git on the PATH.

## What it does on your machine (disclosure)

- **Runs `git`** as a subprocess (read-only commands: `diff`, `log`, `ls-files`, `rev-parse`, `merge-base`,
  `cat-file`, `show`, `status`, `hash-object --stdin`) in the repository the agent works in. It never commits,
  pushes, merges or changes your repository.
- **Reads files** of that repository: untracked files (up to 500, 512 KB each) to look for secrets and markers, the
  file a `write_file` would replace, `package.json` to compare its scripts, and a commit message file given with
  `-F`. It may read a non-ignored `.env` only to warn before it is committed; values are never printed or stored.
- **Writes in its Hermes plugin data directory** only: `foreman-grants.json` (the findings waiting for you and the
  exceptions you allowed: rule, file, line, message; no file contents), `foreman-board.json` (the repository pinned
  per session and the last ten you used: paths only), and, for a moment, the text of a `/foreman reject` comment
  in `outbox/` (deleted once `gh pr comment` has read it). It reads `reviews/<owner>__<repo>__<pr>.json` there when a
  saved model review exists. The agent cannot change any of these: its writes and terminal commands naming them are
  blocked, like the grants file.
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
  (`tools.terminal_tool.get_session_cwd`), guarded, with Hermes's documented `resolve_agent_cwd()` as fallback.
  `/foreman use` also lists the directories directly inside the session's directories to find git repositories.
- **No network calls of its own** (only the `gh` commands above, when you ask), no telemetry, no credentials, no
  background processes, no model calls.
- It registers two hooks (`pre_tool_call`, `pre_verify`), one slash command (`/foreman`) and one tool
  (`foreman_check`).

## Known limits

- It sees the tree as it is **before** the gated command runs; that is why it asks for the gated command on its own.
- Commits made by an interpreter (a Python or Node script calling git, Hermes's `execute_code`), by git aliases or
  by other tools are not inspected at that moment; the next `git push` or `gh pr create` still sees what they
  committed. Foreman also does not model `GIT_INDEX_FILE` or `GIT_DIR` set in the environment of a git command.
- It does not detect emptied test bodies, removed asserts, commented-out tests, or a test function deleted from a
  file that still exists: only markers, whole-file deletions and moves, and changes to the check.
- Tests switched off by selection are not detected: `-k 'not x'` in pytest `addopts`, or a `jest` section with
  `testPathIgnorePatterns` inside `package.json`.
- Markers covered: pytest (`skip`, `xfail`, `skipif`), unittest (`skip*`, `expectedFailure`, `skipTest`),
  Jest/Vitest/Mocha/Jasmine (`.skip`, `.only`, `.concurrent`, `.each`, `.skipIf`, `xit`, `xtest`, `xdescribe`,
  `fit`, `fdescribe`, `this.skip()`), Go (`t.Skip*`), Rust (`#[ignore]`), JUnit (`@Disabled`, `@Ignore`). A
  conditional skip in a new test file is allowed; added to an existing test it is blocked.
- Check protection covers the entry point named in `.foreman.json` (not everything it runs) and the narrow
  `check-weakened` patterns above.
- Secrets are found by pattern: real credential formats reliably, key/value guesses with false negatives (and none
  inside test files).
- Repository resolution: for `/foreman` subcommands, a repository pinned with `/foreman use` comes first. Then
  Foreman tries, in order, the directory the terminal tool recorded for the session, the
  session's working directory that Hermes binds for a local session's command (`scoped_session_cwd()`), then (in
  the CLI and TUI only) the process directory, then Hermes's `resolve_agent_cwd()`, and uses the first one inside a
  git repository. Hermes's own data is never picked unless the terminal recorded it: nothing inside a Hermes home
  (the profile home or the root that holds the profiles), and no repository whose root contains one. The first two
  are read from Hermes internals, guarded: if Hermes moves them, Foreman falls back to the others. When nothing
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

```
python -m unittest discover -s tests -q
hermes plugins validate . --install-deps
hermes plugins doctor .
```

Test fixtures that look like secrets are assembled at runtime, never written as literals.

## License

MIT
