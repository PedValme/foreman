# Foreman

**A green check the agent did not rig.** Foreman is a [Hermes Agent](https://github.com/NousResearch/hermes-agent)
plugin. Other tools prove the check ran; Foreman proves the coding agent did not skip, delete or weaken the tests,
change what the check runs, or commit a secret to get there.

Its detector is deterministic: no model, only Python's standard library and git. It reads the real diff, not the
command text.

## What it blocks

| Rule | What it catches |
|---|---|
| `test-skipped` | skip, only and xfail markers added to tests (pytest, unittest, Jest, Mocha, Jasmine, Vitest) |
| `test-deleted` | a test file deleted |
| `test-moved` | a test file renamed out of the tests |
| `check-changed` | a change to a file the check command runs (its entry point), or to `.foreman.json` |
| `secret`, `env-file` | credentials in added lines (cloud, GitHub, model APIs, Slack, Stripe, private keys, passwords in config, shell, YAML, `.env`) |
| `secret-history` | a secret in any commit of what is pushed, even if a later commit removed it |
| `hooks-bypassed` | `git commit --no-verify` / `-n`, `git push --no-verify`, `git -c core.hooksPath=…` |

## When it acts

- **Before a publishing command** (`pre_tool_call`): `git commit`, `git push`, `gh pr create`, `gh pr merge` run by
  the agent's terminal tool, also inside `cd x && …`, `git -C x …` and `bash -c "…"`. A blocker returns `block` with
  each finding (file:line, rule, how to fix it for real). `gh pr merge` always asks a person.
- **Before a test file is written** (`write_file`, `patch`): adding a skip/only/xfail marker to a test is refused.
- **Before the agent finishes a coding turn** (`pre_verify`, once per turn): if the uncommitted changes would rig the
  check, the agent is told exactly what to undo.

A false positive is marked on its line with `foreman:allow`, or, for a deleted, moved or check file, with a commit
message line `foreman:allow <path>: <reason>`. The marker never passes alone: Foreman asks a person through Hermes's
approval prompt. With no person present (cron, unattended runs), Hermes refuses the call.

If Foreman cannot inspect a publishing command (git error, time budget of 20 s exhausted, a working directory that
does not exist on the Hermes host), it asks a person instead of letting it through silently.

## Use

```
/foreman status [path]   verdict for the current repository: CLEAN or BLOCKED, with reasons
/foreman help
```

The agent can call the `foreman_check` tool for the same verdict as JSON.

The check command comes from `.foreman.json` **at the base** (the branch's merge-base, or `HEAD` for a commit), so a
change cannot redefine its own check:

```json
{"check": "bash scripts/check.sh"}
```

### CI mode

```
python -m foreman.detector <base> [<head>] [--check "<command>"] [--json]
```

Exits 1 when there is a blocker. Findings marked `foreman:allow` are listed for the reviewer and do not fail.

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
  file a `write_file` would replace, and a commit message file given with `-F`.
- **No network calls**, no telemetry, no credentials, no background processes, no model calls.
- It registers two hooks (`pre_tool_call`, `pre_verify`), one slash command (`/foreman`) and one tool
  (`foreman_check`).

## Development

```
python -m unittest discover -s tests -q
hermes plugins validate . --install-deps
hermes plugins doctor .
```

Test fixtures that look like secrets are assembled at runtime, never written as literals.

## License

MIT
