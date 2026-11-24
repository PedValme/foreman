#!/usr/bin/env python3
"""The one entry point of Foreman's adapters: ``python3 -I adapters/hook.py <host>``.

The harness's hook calls it with its own JSON on standard input and reads the answer from standard output. Run it
with ``-I`` (isolated): Python then ignores ``PYTHON*`` variables and the user's site directory, and the only
directories added to the import path are the two below, both inside Foreman's own installation.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))            # adapters/
CORE = os.path.join(os.path.dirname(HERE), "plugin")         # the Hermes plugin: the single source of the gate
for _path in (CORE, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

MIN_PYTHON = (3, 9)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if sys.version_info < MIN_PYTHON:
        sys.stderr.write("Foreman needs Python %d.%d or newer; this is %s.\n"
                         % (MIN_PYTHON[0], MIN_PYTHON[1], sys.version.split()[0]))
        return 1
    host = argv[0] if argv else ""
    if host == "claude-code":
        from foreman_hosts import claude_code
        return claude_code.main()
    sys.stderr.write("Foreman: unknown host %r. Known: claude-code.\n" % host)
    return 1


if __name__ == "__main__":
    sys.exit(main())
