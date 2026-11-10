"""Foreman, a Hermes Agent plugin: a green check the agent did not rig.

Registers two hooks (``pre_tool_call``, ``pre_verify``), one slash command (``/foreman``) and one tool
(``foreman_check``). The detector lives in ``foreman/detector.py`` and also runs on its own in CI. ``/foreman
review`` asks a second model through ``ctx.llm``, only when the user runs it (``foreman/review.py``). The board,
merge and reject live in ``foreman/board.py``.
"""
from .foreman import board, commands, gate, review


def register(ctx):
    board.bind(ctx)   # ask_choice and dispatch_tool, from /foreman use, merge and reject only
    gate.bind(ctx)    # ctx.session_cwd(), to find the session's repository
    review.bind(ctx)  # ctx.llm is used later, from /foreman review only
    ctx.register_hook("pre_tool_call", gate.on_pre_tool_call)
    ctx.register_hook("pre_verify", gate.on_pre_verify)
    ctx.register_command(
        "foreman",
        commands.handle_slash,
        description="Foreman: the board, verdicts, merge and reject with reasons (board, use, prs, issues, verdict, "
                    "merge, reject, review, status, allow, notify, help)",
        args_hint="[board|use|prs|issues|verdict|merge|reject|review|status|allow|notify|help]",
    )
    ctx.register_tool(
        name="foreman_check",
        toolset="foreman",
        schema=commands.TOOL_SCHEMA,
        handler=commands.foreman_check_tool,
        description="Foreman's verdict for a git repository",
        emoji="",
    )
