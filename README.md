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

`gh pr merge` always asks a person (a merge is never automatic). So do a push of several branches (`--all`,
`--mirror`, several refspecs) and any command Foreman could not inspect (git error, its 18 s time budget, a working
directory that does not exist on the Hermes host). These use Hermes's approval prompt: **in YOLO mode or with
approvals off, Hermes lets them through without a person.**

## Use

```
/foreman status [path]   verdict for the current repository: CLEAN or BLOCKED, with reasons
/foreman allow [id]      list or allow findings the agent marked
/foreman help
```

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
  `updated`, can block; every other result (old debt, results with no location) is a note, so existing findings do
  not stop every commit. `"sarif_scope": "all"` in `.foreman.json`, or `--sarif-scope all`, lets every result block.
- **Never blocks, not even listed**: suppressed results (accepted or without status), `baselineState: "absent"`, and
  results whose `kind` is present and not `fail`.
- **Staleness**: a report older than the newest commit (or edited file) it gates adds the note "SARIF report is older
  than the changes it gates"; it does not block.
- **Missing or unreadable report**: if the base's `.foreman.json` names it, Foreman cannot say the change is clean:
  the hooks ask for approval ("could not read the SARIF report <path> named in .foreman.json"), `/foreman status`
  says `NEEDS_APPROVAL`, and CI exits 2; the same for `--sarif`. A report with zero results is a valid clean scan.
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

Exit codes: **0** clean, **1** at least one blocker, **2** the run could not be done (not a repository, git failed,
a SARIF report that cannot be read, whether given with `--sarif` or named in `.foreman.json`).
[`examples/foreman-check.yml`](examples/foreman-check.yml) is a workflow to copy: full-history checkout, actions
pinned by commit SHA, Foreman downloaded at a pinned commit SHA, the base branch passed through `env`, the detector
run against the pull request's base. Make it a required check: unlike the hooks, it runs where the agent cannot edit
it.

Findings marked only with `foreman:allow` are listed and exit 0 in CI: Foreman does not decide for a person, so a
human reviews them in the PR. With `GITHUB_ACTIONS` set, each one is also printed as a `::warning` annotation on the
file and line. `--strict` makes them blockers (exit 1) for teams where nobody waves a finding through.

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
- **Writes one file**, `foreman-grants.json` in its Hermes plugin data directory: the findings waiting for you and
  the exceptions you allowed (rule, file, line, message; no file contents).
- Reads the working directory the terminal tool recorded for the session, through a Hermes internal
  (`tools.terminal_tool.get_session_cwd`), guarded, with Hermes's documented `resolve_agent_cwd()` as fallback.
- **No network calls**, no telemetry, no credentials, no background processes, no model calls.
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
- Repository resolution: Foreman tries, in order, the directory the terminal tool recorded for the session, the
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

## Development

```
python -m unittest discover -s tests -q
hermes plugins validate . --install-deps
hermes plugins doctor .
```

Test fixtures that look like secrets are assembled at runtime, never written as literals.

## License

MIT
