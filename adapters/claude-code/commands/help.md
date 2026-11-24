---
description: "Foreman: what it blocks and its commands"
disable-model-invocation: true
---
Foreman's hook answers this command before it reaches you, and it did not: Foreman's hooks are not running in this
session (the plugin is turned off, or `python3` is missing). Tell the user exactly that, in one sentence, and do
nothing else.
