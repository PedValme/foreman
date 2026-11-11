# Issue for NousResearch/hermes-agent

Opened 2026-11-11: https://github.com/NousResearch/hermes-agent/issues/153841

**Title:** [Feature]: Plugin API: seams a test-integrity plugin needed (terminal cwd, approval for dispatched commands,
owner notifications with choices, button captions, auxiliary model picker)

Hi, and thanks for the plugin surface: hooks, `ctx.dispatch_tool`, `ctx.ask_choice` and `ctx.llm` covered almost
everything [Foreman](https://github.com/PedValme/foreman) needed. It is a plugin that blocks a coding agent from
rigging its own check (skipped or deleted tests, a changed check, secrets) and leaves merges to the user. Following
the catalog guide ("open an issue describing it: we would rather add the seam than list a patch"), here are the four
places where we found no public seam, each with the workaround we ship today, then four things we saw on a real setup
and one more seam for plugin settings. Foreman line numbers are at commit
[`c15453c`](https://github.com/PedValme/foreman/tree/c15453cb2fc07fa674d6f7b548a553b3ce9e6f5d) (the one submitted to the
catalog); Hermes line numbers are v0.23.0.

## 1. Read the terminal's current working directory for a session

**What.** A public accessor for the directory the terminal tool is in for a given session, after the agent's `cd`
commands, not the session's launch directory.

**Why.** A `pre_tool_call` hook on `terminal` that inspects `git commit` must know which repository the command runs
in when the command has no `workdir` and no `cd`. `ctx.session_cwd()` returns the recorded workspace or the profile's
terminal cwd (`hermes_cli/plugin_session.py:33-40`); in the CLI it is the launch directory
(`hermes_cli/plugin_session.py:48-50`). After `cd ~/src/other-repo` in an earlier terminal call, only
`tools.terminal_tool.get_session_cwd(task_id)` knows where the next command runs.

**Consumer.** `plugin/foreman/gate.py:661` imports `tools.terminal_tool.get_session_cwd` inside `try/except` and
falls back to `ctx.session_cwd()` and `agent.runtime_cwd.resolve_agent_cwd()`. It is the one warning `hermes plugins
validate` reports for Foreman (catalog rule 9). The same directory is what `/foreman` (a slash command) needs to find
the user's repository; when a CLI hands a slash command to a running gateway before the terminal has been used, there
is no recorded directory at all and Foreman has to ask.

**Sketch.**

```python
ctx.terminal_cwd(session_key: str | None = None) -> str
# The directory the terminal tool will use for this session's next command ("" when unknown).
# Default: the calling session. Read-only; never the gateway process's own cwd.
```

## 2. Let a plugin ask Hermes's own approval before an irreversible command

**What.** Either (a) `ctx.dispatch_tool("terminal", …)` calls pass through the same approval path (dangerous-command
detection, `pre_tool_call` hooks, the user's approval mode) as a model's tool call, or (b) a documented
`ctx.request_approval(...)` that shows Hermes's own approval prompt and returns the answer.

**Why.** `ctx.dispatch_tool` goes straight to `registry.dispatch` (`hermes_cli/plugins.py:676-685`): in v0.23.0 no
approval prompt appears for a command dispatched by a plugin. Foreman runs `gh pr merge` this way after the user
confirms with `ctx.ask_choice` (`plugin/foreman/board.py:1169-1180` for the question, `board.py:1083-1090` for the
dispatch, `board.py:1237` for the command). That works, but it is Foreman's own confirmation, not Hermes's: it does
not follow the user's approval settings, is not logged as an approval, and every plugin that runs an irreversible
command re-invents it. `ask_choice` also only works from a sync slash-command handler, so a tool or hook cannot ask.

**Consumer.** `/foreman merge` (`gh pr merge --match-head-commit`), `/foreman reject --close` (`gh pr close`,
`board.py:1557`), and `hermes send` for notifications (`plugin/foreman/notify.py:256`).

**Sketch.**

```python
answer = ctx.request_approval(
    command="gh pr merge 7 --squash --delete-branch --match-head-commit abc123…",
    reason="Merge PR #7 into main (Foreman verdict: CLEAN)",
    choices=("once", "deny"),          # no "always" for irreversible actions
    timeout=120,
)  # -> "once" | "deny" | "timeout" | "unavailable" (cron, no person); never raises
```

Under cron or with nobody to ask it returns `"unavailable"` and the plugin does nothing (catalog rule 12). Whether
YOLO auto-approves it should be Hermes's call, consistently with model tool calls.

## 3. Notify the owner's home channel with choices that answer back to the plugin

**What.** A public, opt-in way for a plugin to send one message to a messaging target the user configured (a
platform's home channel, or `platform:chat`), outside the turn that invoked the plugin, with a few choices rendered as
the platform's native buttons; a press runs the plugin's own slash command in that chat, as if the user had typed it,
under the same authorisation as a typed command.

**Why.** Today a plugin can:

- post into the conversation that invoked it (`ctx.post_message`), never another one
  (`hermes_cli/plugin_messages.py:1-8`, `website/docs/user-guide/features/plugins.md:1026-1030`);
- not dispatch `send_message`, which is deliberately not a registered tool (`tools/send_message_tool.py:28-30`,
  `website/docs/user-guide/features/hooks.md:1426`);
- ask with buttons only from a sync slash-command handler, in the chat where the command was typed
  (`hermes_cli/plugin_choices.py:81-96`);
- use `ctx.platform_actions` for reactions and thread titles only (`plugins.md:669-691`);
- wire native handlers with `register_platform_handler` (`developer-guide/plugins/index.md:2026-2070`), but sending a
  message from there means holding the bot client, reading the home channel from gateway internals and checking the
  presser against the allowlist by hand, which catalog rules 9 and 11 rightly discourage.

So a plugin that wants to tell its owner "this is ready, decide" can only shell out to `hermes send` through the
terminal tool (plain text, no buttons) and ask the owner to type the command back.

**Consumer.** `plugin/foreman/notify.py:242-266`: when a pull request is CLEAN and mergeable, Foreman sends the owner
a message with `/foreman merge 6 --repo acme/widgets` to copy. With this seam the owner would tap **Merge**, which runs
`/foreman merge 6`: a fresh verdict, then Hermes's own confirmation. The button is the person's decision, never an
automatic merge.

**Sketch.**

```python
result = ctx.notify(
    target="telegram",                       # hermes send target syntax; home channel when bare
    text="PR #6 in acme/widgets is ready",   # plain text, clamped
    choices=[{"label": "Merge", "command": "/foreman merge 6 --repo acme/widgets"},
             {"label": "Reject", "command": "/foreman reject 6 --repo acme/widgets"}],
)  # -> {"ok": bool, "error": str | None}, never raises
```

- Gated by a capability (e.g. `gateway.notify`), off until the user grants it, and logged like `post_message`.
- A press dispatches the command through the gateway's normal plugin-command path for the chat where it was pressed:
  the allowlist and slash access policy apply, the handler gets the usual `session_key` / `platform` / `source`
  keywords, and `ctx.ask_choice` works inside it. Only commands of the plugin that sent the message are accepted; the
  plugin never receives raw callback data or SDK objects.
- Without a live gateway (CLI only, cron with a bot-token platform) the text is delivered like `hermes send` and the
  choices are rendered as text commands.

## 4. A short button caption on a choice

**What.** Let a choice passed to `ctx.ask_choice` carry an optional short `button` caption that messaging adapters use
as the button text.

**Why.** Telegram always renders numeric buttons ("1", "2") and prints each choice above them as
`<n>. <label> — <description>` (`plugins/platforms/telegram/adapter.py:4290` `send_clarify`; the text is built in
`hermes_cli/plugin_choices.py:58-70`). A plugin can only keep its labels short; it cannot make the buttons say
"Merge" and "Cancel".

**Consumer.** `plugin/foreman/board.py:1169` `_confirm` would pass
`{"value": "merge", "label": "Merge PR #2", "button": "Merge"}`; today it can only keep the label short.

## 5. Two things seen on a real setup (Hermes 0.23.0)

- **A plugin's model call with no override does not use the main model.** `ctx.llm.complete_structured()` without
  `model`/`provider` goes through `agent.auxiliary_client.call_llm`. On a profile whose main provider is
  `openai-codex`, the auxiliary client logged "openai-codex requested but no Codex OAuth token found" (the agent
  itself used Codex fine) and fell back to the first `fallback_providers` entry. The result's attribution then
  mixes the two: `provider=openai-codex model=<the fallback provider's model>`. A plugin cannot tell which model answered, nor
  ask for "the model the agent uses".
- **The capability consent prompt hides its answers.** `hermes_cli/plugins_cmd_capabilities.py:88` asks
  `"  Grant these capabilities? [y/N] "` through Rich's `console.input`, which reads `[y/N]` as markup and drops it:
  the user sees "Grant these capabilities?" with no hint that `y` is the answer. Escaping it (`\\[y/N]` or
  `rich.markup.escape`) shows it.
- **Disabling a plugin does not unload it from a running gateway.** Enabling one in Desktop (Capabilities → Plugins)
  takes effect at once, but disabling it only writes `plugins.disabled`: the gateway keeps running the plugin's hooks,
  commands and tools until it restarts. A gate plugin that the user turned off keeps blocking. Foreman now reads
  `plugins.disabled` itself on each gated call; a plugin should not have to.
- **Desktop keeps the spinner after a plugin's question.** After a slash command that called `ctx.ask_choice` and
  returned its reply, the chat keeps the busy spinner until the user sends another message.

## 6. Let a plugin's settings pick the model for its own auxiliary task with the native picker

A plugin that calls `ctx.register_auxiliary_task("foreman_review", …)` gets a row in Settings → Models → Auxiliary,
but its own Settings → Plugins page cannot offer the same choice: `config.set` refuses `auxiliary.*` keys
(`tui_gateway/methods_config_set.py`), `POST /api/model/set` is reachable from a desktop plugin only through the raw
`window.hermesDesktop` bridge that catalog rule 8 forbids, and a free-text `config_schema` field duplicates the choice
and needs `llm.model_override`. Either would do: (1) a `config_schema` field type `auxiliary_model` with a `task:` key
naming a task the same plugin registered, rendered with the Auxiliary row's provider/model select and saved through
`/api/model/set {scope: "auxiliary", task}`; or (2) a gateway method `model.assign_auxiliary` plus an SDK verb
`ctx.models.setAuxiliary(task, route)` that refuses tasks the calling plugin did not register. Please also list
`ModelCatalogMenu` / `ModelMenuController` in the SDK docs' export table (exported in `sdk/index.ts`, used by the
bundled kanban plugin).

Happy to test any of these against Foreman, or to send a PR for the first one if you agree on its shape.
