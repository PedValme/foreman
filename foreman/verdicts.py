"""Foreman's one vocabulary for the deterministic verdict, used by every view (status, board, verdict, merge,
review, the ``foreman_check`` tool, the pipeline's gate stage) and by the CI text.

=============  ==============================================================================================
CLEAN          nothing found, and everything Foreman was told to inspect was inspected
BLOCKED        a blocker: a skipped, deleted or moved test, a change to the check, a secret, a SARIF result
INCOMPLETE     something Foreman was told to inspect could not be (an unreadable SARIF report, a git error,
               the time budget); not a pass
NEEDS YOUR OK  only findings the agent marked ``foreman:allow``, waiting for ``/foreman allow <id>``
=============  ==============================================================================================

Order when several apply: BLOCKED, then INCOMPLETE, then NEEDS YOUR OK. Readiness (draft, conflicts, GitHub still
computing) and CI are separate facts, never part of this verdict.
"""
from __future__ import annotations

CLEAN = "CLEAN"
BLOCKED = "BLOCKED"
INCOMPLETE = "INCOMPLETE"
NEEDS_OK = "NEEDS YOUR OK"
ALL = (CLEAN, BLOCKED, INCOMPLETE, NEEDS_OK)

MEANING = {
    CLEAN: "nothing found; everything Foreman was told to inspect was inspected",
    BLOCKED: "a skipped, deleted or moved test, a change to the check, a secret or a blocking SARIF result",
    INCOMPLETE: "something Foreman was told to inspect could not be (unreadable SARIF report, git error, time "
                "budget); not a pass",
    NEEDS_OK: "only findings the agent marked `foreman:allow`, waiting for `/foreman allow <id>`",
}


def _n(x) -> int:
    if x is None:
        return 0
    if isinstance(x, bool):
        return int(x)
    if isinstance(x, int):
        return x
    return len(x)


def verdict_of(findings=(), errors=(), marked=()) -> str:
    """The verdict from the blocking findings (not marked, or marked and refused), the inspection errors and the
    marked findings still waiting for a person. Each argument is a sequence or a count."""
    if _n(findings):
        return BLOCKED
    if _n(errors):
        return INCOMPLETE
    if _n(marked):
        return NEEDS_OK
    return CLEAN


def table() -> str:
    """The vocabulary as plain text at 78 columns, for help."""
    import textwrap
    return "\n".join(textwrap.fill(MEANING[k], width=78, initial_indent="  %-14s " % k, subsequent_indent=" " * 17)
                     for k in ALL)
