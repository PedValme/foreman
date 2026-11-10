"""Foreman's backend route for the Desktop panel: ``GET /api/plugins/foreman/pipeline``.

Hermes mounts this router (declared in ``dashboard/manifest.json``) only when Foreman is in ``plugins.enabled``. The
route is read-only: it returns Foreman's own pipeline snapshot from its data directory and nothing else. Hermes loads
this file on its own, by path, so the reader (``foreman/panel_api.py``, standard library only) is loaded by path too.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from fastapi import APIRouter

_READER = Path(__file__).resolve().parent.parent / "foreman" / "panel_api.py"
_spec = importlib.util.spec_from_file_location("foreman_panel_api", _READER)
panel_api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(panel_api)

router = APIRouter()


@router.get("/pipeline")
def pipeline() -> dict:
    return panel_api.read_snapshot()
