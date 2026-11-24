---
description: "Foreman: list the findings the agent marked, or allow one of them (you only)"
argument-hint: "[id]"
disable-model-invocation: true
---
Foreman's hook answers this command before it reaches you, and it did not: Foreman's hooks are not running in this
session (the plugin is turned off, or `python3` is missing). Tell the user exactly that, in one sentence, and do
nothing else. You cannot allow a finding: only the user can, with Foreman running.
