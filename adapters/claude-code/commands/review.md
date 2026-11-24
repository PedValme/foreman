---
description: "Foreman: a fresh session that did not write the code reviews the change (advisory)"
argument-hint: "[pull request|branch] [--fresh]"
disable-model-invocation: true
---
Foreman's hook answers this command before it reaches you, and it did not: Foreman's hooks are not running in this
session (the plugin is turned off, or `python3` is missing). Tell the user exactly that, in one sentence, and do
nothing else. Do not review the change yourself in its place: the review is a session that did not write the code.
