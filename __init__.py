"""Foreman, a Hermes Agent plugin: a green check the agent did not rig.

Registers two hooks (``pre_tool_call``, ``pre_verify``), one slash command (``/foreman``) and one tool
(``foreman_check``). The detector lives in ``foreman/detector.py`` and also runs on its own in CI.
"""
from .foreman import board, commands, gate


def register(ctx):
    board.bind(ctx)
    ctx.register_hook("pre_tool_call", gate.on_pre_tool_call)
    ctx.register_hook("pre_verify", gate.on_pre_verify)
    ctx.register_command(
        "foreman",
        commands.handle_slash,
        description="Foreman: the board, verdicts, merge and reject with reasons (board, use, prs, issues, verdict, "
                    "merge, reject, status, allow, help)",
        args_hint="[board|use|prs|issues|verdict|merge|reject|status|allow|help]",
    )
    ctx.register_tool(
        name="foreman_check",
        toolset="foreman",
        schema=commands.TOOL_SCHEMA,
        handler=commands.foreman_check_tool,
        description="Foreman's verdict for a git repository",
        emoji="",
    )
