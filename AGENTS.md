# Foreman — for agents and contributors

Foreman stops a coding agent from rigging its own green check. It is a plugin for Hermes Agent
(NousResearch/hermes-agent), listed in its catalog, plus adapters that bring the same gate to Claude Code, Codex, pi
and OpenCode (under construction). What the product must do is in [docs/rules.md](docs/rules.md); why it is built
this way, in [docs/decisions/](docs/decisions/). Code, documents, commits and messages are in English.

## Layout
- `plugin/` is the Hermes plugin and the only part Hermes installs (catalog `subdir: plugin`): `plugin.yaml`,
  `__init__.py` (registration), the `foreman/` package (detector, gate, review, board), `desktop/`, `dashboard/`,
  its `README.md` (the full one) and `LICENSE`. Python 3.11+, standard library only, plus git. Nothing in it reads
  outside `plugin/`. Requires Hermes >= 0.22.6.
- `adapters/` holds the other harnesses' adapters (its README says what each file is): `foreman_hosts/core.py` is
  the host-neutral half, one module per harness is its dialect, `neutral.py` is the protocol a harness's own
  extension speaks when it is code (pi's and OpenCode's `.ts` files), `reviewer.py` is the review as a fresh session
  of the harness, `standin.py` runs the Hermes plugin's board, merge and reject on a stand-in for Hermes's context,
  and `hook.py` is the entry point they all run (`python3 -I`, Python 3.9+). They import the gate from
  `plugin/foreman/`; `plugin/` never imports them.
- The repository root is also the package other harnesses install (`.claude-plugin/`, `.codex-plugin/`,
  `package.json`), so nothing binary, generated or private is committed anywhere in it.
- `action.yml` is the check in CI as a GitHub Action; `examples/` has the workflow to copy, the cart example and the
  panel preview; `tests/` holds every test.

## Check
From the root, before every commit:
- `python -m unittest discover -s tests -q` (`tests/tests_support.py` puts `plugin/` and `adapters/` on `sys.path`;
  import it before `foreman`).
- `hermes plugins validate plugin --install-deps`, where Hermes is installed.
- `claude plugin validate .` when the Claude Code plugin's files change.
Never weaken a test or the check to make a change pass. The detector, the adapters and their tests are the product's
controls: a change to them gets a second reviewer before it merges.

## Pitfalls
- Foreman's own check reads this repository's test files, so a fixture builds a skip marker from parts
  (`"@pytest.mark." + "skip"`, `detector.MARKER`), never literally (docs/decisions/0006.md).
- A new conditional skip (`skipIf` for a platform) goes in a new test file: added to an existing one it is a finding
  of Foreman's own check, by design.
- CI runs on Linux, macOS and Windows: a test never compares a Unix-only path as a string (build paths from the
  test's temporary directory).
- Outside Hermes the adapters bind the core's contexts for one command (`standin.py`, `reviewer.bound`): a test must
  leave `board._CTX`, `gate._CTX` and `review._CTX` as it found them. A change to the context calls
  (`foreman_host_label`, `foreman_review_before_merge`, `foreman_finish_review`), to the board's text or to
  `finish.py`'s messages is checked against the adapters' tests.
- `hermes plugins install --ref` needs the full 40-character commit. With a gateway running, a slash command runs
  inside the gateway process, whose directory is the Hermes home, not the user's.
- Claude Code's prompt rejects a `/foreman` that is not a real command before any hook sees it, so the person's
  commands there are plugin commands (`/foreman:status`). Outside Hermes Foreman's state is `~/.foreman`: remove
  what a manual test leaves there.
- The real-panel test (`test_desktop_panel_sequences`) is skipped where Hermes's `node_modules` is not flat (every
  pnpm install): set `FOREMAN_NODE_MODULES` to a folder that links `react`, `react-dom`, `scheduler` and `jsdom`.

## Trying it without installing
- Hermes: `hermes plugins doctor plugin` (a temporary HERMES_HOME), or a dedicated profile (`hermes -p <profile> …`);
  never your default profile.
- Other harnesses, in a throwaway repository and from a clone other than the one being edited (each guide under
  `adapters/` has the exact command): `claude --plugin-dir <clone>`, `pi -ne -e <clone>/adapters/pi/foreman.ts`,
  `codex -c hooks.…` with `--dangerously-bypass-hook-trust`, and for OpenCode a link in the throwaway repository's
  `.opencode/plugins`. Do not write into your own harness configuration for a test. A terminal UI can be driven
  through tmux (`send-keys`, `capture-pane`).

## Contributing
A branch per change and a pull request to `main`, with the tests green; `main` is protected. Commits, pull requests,
issues and comments carry only what the change is and why, technically: nothing about how the project is managed or
planned, nobody's private setup, machines or accounts. Hermes's plugin documentation is in NousResearch/hermes-agent
(`website/docs/developer-guide/plugins/`, `website/docs/user-guide/features/hooks.md`, and the catalog's admission
rules in `plugin-catalog/README.md`). See also [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).
