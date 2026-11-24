#!/usr/bin/env python3
"""The one entry point of Foreman's adapters: ``python3 -I adapters/hook.py <host>``.

The harness's hook (or its extension) calls it with JSON on standard input and reads the answer from standard
output. Run it with ``-I`` (isolated): Python then ignores ``PYTHON*`` variables and the user's site directory, and
the only directories added to the import path are the two below, both inside Foreman's own installation.

It never answers through its exit code: a decision is JSON on standard output with exit code 0, and exit code 1 means
the adapter could not run (the harness then goes on as with any failed hook).
"""
import importlib
import importlib.util
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
    from foreman_hosts import hosts
    host = argv[0] if argv else ""
    module = hosts.MODULES.get(host)
    if not module:
        sys.stderr.write("Foreman: unknown host %r. Known: %s.\n" % (host, ", ".join(sorted(hosts.MODULES))))
        return 1
    if os.environ.get("FOREMAN_REVIEWER"):
        from foreman_hosts import core
        if core.reviewer_session(os.environ):
            # The session Foreman itself started to review a change (foreman_hosts/reviewer.py): it has no tools
            # to gate, and it must not review its own review. The variable alone proves nothing (a repository's
            # settings can set one): it must name a review Foreman is running right now.
            if host in hosts.NEUTRAL:
                sys.stdout.write("{}")
            return 0
    name = "foreman_hosts." + module
    if importlib.util.find_spec(name) is None:
        sys.stderr.write("Foreman: the adapter for %s is not part of this installation.\n" % host)
        return 1
    return int(importlib.import_module(name).main() or 0)


if __name__ == "__main__":
    sys.exit(main())
