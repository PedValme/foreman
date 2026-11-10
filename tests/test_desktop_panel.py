"""The Desktop half (desktop/plugin.js) as a file: it imports only what the Desktop loader resolves, never renders
text as HTML, never reaches the network or the app's internals, and stays loadable by the browser preview."""
import importlib.util
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "desktop", "plugin.js")


def source():
    with open(PLUGIN, encoding="utf-8") as fh:
        return fh.read()


class DesktopPanelFileCase(unittest.TestCase):
    def test_imports_only_what_the_desktop_loader_resolves(self):
        modules = re.findall(r"^import\s[^;]*?from\s*'([^']+)'", source(), re.MULTILINE | re.DOTALL)
        self.assertTrue(modules)
        self.assertLessEqual(set(modules), {"@hermes/plugin-sdk", "react", "react/jsx-runtime"})

    def test_no_html_injection_network_or_dynamic_code(self):
        text = source()
        for pattern in (r"dangerouslySetInnerHTML", r"\.innerHTML\b", r"\.outerHTML\b", r"insertAdjacentHTML",
                        r"\beval\(", r"new\s+Function\(", r"\bimport\(", r"\bfetch\(", r"XMLHttpRequest",
                        r"new\s+WebSocket\(", r"hermesDesktop", r"createElement\(\s*['\"]script",
                        r"querySelector", r"localStorage", r"sessionStorage"):
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, text))

    def test_buttons_only_build_foreman_commands(self):
        commands = re.findall(r"command:\s*[`'](/[^`'$ ]+)", source())
        self.assertTrue(commands)
        self.assertTrue(all(c == "/foreman" for c in commands), commands)

    def test_preview_can_rewrite_it_as_a_classic_script(self):
        spec = importlib.util.spec_from_file_location("panel_preview_build",
                                                      os.path.join(ROOT, "examples", "panel-preview", "build.py"))
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        out = build.classic(source())
        self.assertNotRegex(out, r"(?m)^\s*(import|export)\b")
        self.assertIn("window.__FOREMAN_PLUGIN__ = {", out)


if __name__ == "__main__":
    unittest.main()
