# Contributing to Foreman

Thanks for helping. Foreman is small on purpose: a deterministic gate, an optional review, and a board, with no
runtime dependencies.

## Before you start
- For a bug, open an issue with what you ran, what Foreman said and what you expected. For a false refusal, the
  smallest diff that reproduces it is the most useful thing you can send.
- For a new feature, open an issue first: what the product must do is in [docs/rules.md](docs/rules.md), and a
  change to a rule is discussed before it is built.

## Making a change
1. Fork, then work on a branch.
2. Keep the plugin to Python's standard library and git, and keep `plugin/` self-contained (it never reads outside
   itself). Adapters go in `adapters/` and never need an edit in `plugin/`.
3. Add or update tests in `tests/`. Do not weaken or skip an existing test to make a change pass; Foreman's own check
   on your pull request will flag it.
4. Run the check from the root: `python -m unittest discover -s tests -q`, and `hermes plugins validate plugin
   --install-deps` if you have Hermes.
5. Open a pull request to `main` saying what changes and why. CI runs the tests on Linux, macOS and Windows and
   Foreman's own check on the diff.

[AGENTS.md](AGENTS.md) has the layout and the pitfalls (written for coding agents, useful for people too).

## Licence
By contributing you agree that your contribution is licensed under the MIT licence of this repository.
