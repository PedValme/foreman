"""The Desktop panel run for real (React 19 in jsdom, the preview's SDK stand-in) through the sequences that hid it in
Hermes Desktop: see desktop_panel_sequences.cjs. Needs node and a node_modules with react, react-dom, scheduler and
jsdom (Hermes's own install has them); where they are missing (CI runners) the test is skipped, not faked."""
import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests_support import PLUGIN_DIR, ROOT

PREVIEW = Path(ROOT) / "examples" / "panel-preview"
SCRIPT = Path(__file__).resolve().parent / "desktop_panel_sequences.cjs"


def _build():
    spec = importlib.util.spec_from_file_location("panel_preview_build", str(PREVIEW / "build.py"))
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    return build


def _node_modules():
    try:
        found = _build().find_react(os.environ.get("FOREMAN_NODE_MODULES"))
    except SystemExit:
        return None
    return found if (found / "jsdom" / "package.json").is_file() else None


NODE = shutil.which("node")
NODE_MODULES = _node_modules() if NODE else None


class DesktopPanelSequencesCase(unittest.TestCase):
    @unittest.skipUnless(NODE and NODE_MODULES, "needs node with react, react-dom and jsdom installed")
    def test_real_app_sequences(self):
        build = _build()
        with tempfile.TemporaryDirectory(prefix="foreman-panel-") as out:
            source = Path(PLUGIN_DIR, "desktop", "plugin.js").read_text(encoding="utf-8")
            Path(out, "plugin.classic.js").write_text(build.classic(source), encoding="utf-8")
            Path(out, "react.js").write_text(build.react_bundle(NODE_MODULES), encoding="utf-8")
            run = subprocess.run([NODE, str(SCRIPT), str(NODE_MODULES), out, str(PREVIEW / "shim.js")],
                                 capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("ok", run.stdout)


if __name__ == "__main__":
    unittest.main()
