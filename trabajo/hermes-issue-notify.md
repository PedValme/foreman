# Draft issue for NousResearch/hermes-agent (not opened)

**Title:** Plugin API: notify the owner's home channel with choices that answer back to the plugin

## What we need

A public, opt-in way for a plugin to send one message to a messaging target the user configured (a platform's home
channel, or `platform:chat`), outside the turn that invoked the plugin, with a few choices rendered as the platform's
native buttons; a press runs the plugin's own slash command in that chat, as if the user had typed it, under the
same authorisation as a typed command.

Sketch:

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
  the gateway's allowlist and slash access policy apply, the handler gets the usual `session_key` / `platform` /
  `source` keywords, and `ctx.ask_choice` works inside it. Only commands of the plugin that sent the message are
  accepted; the plugin never receives raw callback data or SDK objects.
- Without a live gateway (CLI only, cron with a bot-token platform) the text is delivered like `hermes send` and the
  choices are rendered as text commands.

## Why

Today (v0.23.0) a plugin can:

- post into the conversation that invoked it (`ctx.post_message`), never another one
  (`hermes_cli/plugin_messages.py:1-8`, `website/docs/user-guide/features/plugins.md:1026-1030`);
- not dispatch `send_message`, which is deliberately not a registered tool
  (`tools/send_message_tool.py:28-30`, `website/docs/user-guide/features/hooks.md:1426`);
- ask with buttons only from a sync slash-command handler, in the chat where the command was typed
  (`hermes_cli/plugin_choices.py:81-96`);
- use `ctx.platform_actions` for reactions and thread titles only (`plugins.md:669-691`);
- wire native handlers with `register_platform_handler` (`developer-guide/plugins/index.md:2026-2070`), but sending
  a message from there means holding the bot client, reading the home channel from gateway internals, and checking
  the presser against the allowlist by hand, which the catalog rules (9, 11) rightly discourage.

So a plugin that wants to tell its owner "this is ready, decide" can only shell out to `hermes send` through the
terminal tool (plain text, no buttons) and ask the owner to type the command back.

## Concrete consumer

Foreman (github.com/PedValme/foreman), a test-integrity gate. When a pull request is CLEAN and mergeable it tells the
owner on Telegram; the owner should be able to tap **Merge**, which runs `/foreman merge 6`: a fresh verdict, then
Hermes's own confirmation. The button is the person's decision, never an automatic merge.
