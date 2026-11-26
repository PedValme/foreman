"""Foreman's adapters for harnesses other than Hermes Agent (docs/rules.md, rules 22 to 26).

``core`` is the host-neutral half; each other module is one harness's dialect. They import the gate from the
``foreman`` package in ``plugin/`` (``adapters/hook.py`` and the tests put it on the import path); ``plugin/`` never
imports anything from here.
"""
