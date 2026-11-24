"""The harnesses Foreman has an adapter for: the name `adapters/hook.py <host>` takes, and its dialect module.

Kept apart from ``core`` so the entry point can refuse an unknown name without loading the gate. A name listed here
whose module is not in this installation yet is answered as "not available", never as a stack trace.
"""

MODULES = {
    "claude-code": "claude_code",
    "codex": "codex",
    "pi": "pi",
    "opencode": "opencode",
}

# The harnesses whose own extension speaks neutral.py's protocol: they are always answered with one JSON object.
NEUTRAL = ("pi", "opencode")
