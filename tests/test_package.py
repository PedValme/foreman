"""The root ``package.json``: the package pi and OpenCode install from this repository, under the public name
``foreman-gate`` (docs/decisions/0010.md). It names only files that exist, and nothing outside the adapters and the
gate they run."""
import json
import os
import re
import unittest

from tests_support import ROOT


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


class PackageJson(unittest.TestCase):
    def setUp(self):
        self.package = json.loads(read("package.json"))

    def test_the_public_name_and_who_it_is(self):
        p = self.package
        self.assertEqual(p["name"], "foreman-gate")
        self.assertEqual(p["license"], "MIT")
        self.assertIn("github.com/PedValme/foreman", p["repository"]["url"])
        self.assertIn("pi-package", p["keywords"])  # pi's package gallery lists it by this keyword
        self.assertNotIn("private", p)  # publishable later

    def test_the_version_is_the_projects(self):
        plugin = json.loads(read(".claude-plugin", "plugin.json"))["version"]
        hermes = re.search(r'(?m)^version:\s*"?([^"\s]+)"?', read("plugin", "plugin.yaml")).group(1)
        self.assertEqual(self.package["version"], plugin)
        self.assertEqual(self.package["version"], hermes)

    def test_no_dependency_of_any_kind(self):
        for field in ("dependencies", "peerDependencies", "devDependencies", "optionalDependencies",
                      "bundleDependencies", "scripts"):
            self.assertNotIn(field, self.package, field)

    def test_it_carries_the_adapters_and_the_gate_and_nothing_else(self):
        files = self.package["files"]
        kept = [f for f in files if not f.startswith("!")]
        self.assertEqual(kept, ["adapters/", "plugin/foreman/"])
        for entry in kept:
            self.assertTrue(os.path.isdir(os.path.join(ROOT, entry)), entry)
        # Python's caches, which a working tree may hold, never go into the package.
        self.assertEqual([f for f in files if f.startswith("!")], ["!**/__pycache__/", "!**/*.py[co]"])

    def inside_files(self, path):
        self.assertTrue(path.startswith("./"), path)
        rel = path[2:]
        self.assertTrue(os.path.isfile(os.path.join(ROOT, *rel.split("/"))), path)
        self.assertTrue(any(rel.startswith(f) for f in self.package["files"] if not f.startswith("!")), path)

    def test_pi_loads_its_extension_from_the_package(self):
        self.assertEqual(self.package["pi"], {"extensions": ["./adapters/pi/foreman.ts"]})
        for path in self.package["pi"]["extensions"]:
            self.inside_files(path)

    def test_opencode_finds_its_server_and_tui_parts(self):
        # OpenCode 2.3.2 resolves `<name>/server` (or the package itself) and `<name>/tui` through `exports`.
        exports = self.package["exports"]
        self.assertEqual(exports, {"./server": "./adapters/opencode/server.ts", "./tui": "./adapters/opencode/tui.ts"})
        for path in exports.values():
            self.inside_files(path)
            self.assertRegex(read(*path[2:].split("/")), r'export default \{\s*id: "foreman"')

    def test_the_extensions_find_the_entry_point_next_to_them(self):
        # Both find `adapters/hook.py` from their own file, so the package keeps the repository's layout.
        self.assertIn('join(HERE, "..", "hook.py")', read("adapters", "pi", "foreman.ts"))
        self.assertIn('join(dirname(here), "..", "hook.py")', read("adapters", "opencode", "foreman.ts"))
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "adapters", "hook.py")))


if __name__ == "__main__":
    unittest.main()
