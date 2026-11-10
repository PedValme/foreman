"""Foreman, a Hermes Agent plugin: a green check the agent did not rig.

Registers two hooks (``pre_tool_call``, ``pre_verify``), one slash command (``/foreman``) and two tools
(``foreman_check``, ``foreman_review``). The detector lives in ``foreman/detector.py`` and also runs on its own in
CI. ``/foreman review`` asks a second model through ``ctx.llm`` (``foreman/review.py``); with ``auto_review`` set to
``merge`` (the default) ``/foreman merge`` runs it first, and with ``finish`` the agent's ``foreman_review`` tool runs
it inside the turn (``foreman/finish.py``). The board, merge and reject live in ``foreman/board.py``; the state of
each change, from the gate to the merge, in ``foreman/pipeline.py``.
"""
from .foreman import board, commands, finish, gate, review


def register(ctx):
    board.bind(ctx)   # ask_choice and dispatch_tool, from /foreman use, merge and reject only
    review.bind(ctx)  # ctx.llm: /foreman review, /foreman merge (auto_review: merge) and foreman_review (finish)
    ctx.register_hook("pre_tool_call", gate.on_pre_tool_call)
    ctx.register_hook("pre_verify", gate.on_pre_verify)
    ctx.register_command(
        "foreman",
        commands.handle_slash,
        description="Foreman: the board, the pipeline, verdicts, review, merge and reject with reasons (board, use, "
                    "prs, issues, pipeline, verdict, review, merge, reject, status, allow, help)",
        args_hint="[board|use|prs|issues|pipeline|verdict|review|merge|reject|status|allow|help]",
    )
    ctx.register_tool(
        name="foreman_check",
        toolset="foreman",
        schema=commands.TOOL_SCHEMA,
        handler=commands.foreman_check_tool,
        description="Foreman's verdict for a git repository",
        emoji="",
    )
    ctx.register_tool(
        name="foreman_review",
        toolset="foreman",
        schema=finish.TOOL_SCHEMA,
        handler=finish.foreman_review_tool,
        description="Foreman's second-model review of the current change (advisory)",
        emoji="",
    )
