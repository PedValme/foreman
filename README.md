# Foreman

**A green check the agent did not rig.** Foreman is a [Hermes Agent](https://github.com/NousResearch/hermes-agent)
plugin. Other tools prove the check ran; Foreman proves the coding agent did not skip, delete or weaken the tests,
change what the check runs, or commit a secret to get there.

- A deterministic gate (no model, only Python's standard library and git) that reads the real diff before
  `git commit`, `git push`, `gh pr create` and `gh pr merge`, and blocks skipped, deleted or moved tests, a changed
  or weakened check, bypassed hooks and secrets.
- Before the agent finishes a coding turn, it tells the agent exactly what to undo.
- False positives pass only when you allow them; the agent cannot wave itself through.
- `/foreman`: a board of branches and pull requests, verdicts, a second-model review on demand, and merges that wait
  for you.
- A CI mode to run the same detector as a required check, and an optional Hermes Desktop panel.

**Full documentation, install and disclosure: [`plugin/README.md`](plugin/README.md).**

```
hermes plugins install PedValme/foreman/plugin
hermes plugins enable foreman
```

The installable plugin is the [`plugin/`](plugin/) folder; the rest of this repository (tests, examples, working
documents, CI) stays here and is not installed. MIT licence.
