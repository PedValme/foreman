---
description: "Foreman: who reviews (show it, set a model and an effort, or go back to the default)"
argument-hint: "[model] [effort] | default"
disable-model-invocation: true
---
Foreman's hook answers this command before it reaches you, and it did not: Foreman's hooks are not running in this
session (the plugin is turned off, or `python3` is missing). Tell the user exactly that, in one sentence, and do
nothing else. You cannot choose Foreman's reviewer: only the user can, with Foreman running.
