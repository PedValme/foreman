"""The detector: line rules, diff parsing, the check's entry point, and real git ranges.

Every secret-looking fixture is assembled at runtime (this repository is public and scanned for secrets, and Foreman
checks its own changes): never write one as a single literal.
"""
import base64
import json
import os
import time
import unittest

from foreman import detector
from tests_support import GitRepoCase

GHP = "ghp_"  # a GitHub token prefix, completed at runtime
SKIP = "@pytest.mark." + "skip"


def one(line, path="app/c.py"):
    """Findings for a single added line."""
    return detector.detect("+++ b/" + path + "\n@@ -0,0 +1 @@\n+" + line + "\n")


class LineRules(unittest.TestCase):
    DIFF = (
        "diff --git a/app/x.py b/app/x.py\n--- a/app/x.py\n+++ b/app/x.py\n@@ -1,2 +10,3 @@\n context\n"
        "+TOKEN = '" + GHP + "a" * 36 + "'\n"
        "+ok = 1  # " + GHP + "b" * 36 + " " + detector.MARKER + "\n"
        "diff --git a/tests/test_x.py b/tests/test_x.py\n--- a/tests/test_x.py\n+++ b/tests/test_x.py\n@@ -5 +5,2 @@\n"
        "+" + SKIP + "\n"
        "-    assert x == 1\n"
    )

    def test_secrets_and_skipped_tests_without_a_model(self):
        fs = detector.detect(self.DIFF, deleted=["tests/test_old.py", "app/old.py"])
        self.assertTrue(all(f.severity == "blocker" for f in fs))
        blockers = {(f.file, f.line) for f in fs if not f.allowed}
        allowed = {(f.file, f.line) for f in fs if f.allowed}
        self.assertIn(("app/x.py", 11), blockers)           # the secret, with its line in the new file
        self.assertIn(("app/x.py", 12), allowed)            # marked: escalated, not dropped
        self.assertNotIn(("app/x.py", 12), blockers)
        self.assertIn(("tests/test_x.py", 5), blockers)     # a skipped test
        self.assertIn(("tests/test_old.py", 0), blockers)   # a deleted test file
        self.assertNotIn(("app/old.py", 0), blockers)       # deleting code is not deleting a test
        self.assertEqual(detector.detect("", deleted=[]), [])

    def test_line_patterns(self):
        self.assertTrue(one("DB_PASS" + "WORD = " + "'s3cr3t-long-value'"))
        self.assertTrue(one("    item.add_marker(pytest.mark." + "skip(reason='x'))"))
        self.assertTrue(one("pytest." + "skip('off')"))
        self.assertFalse(one("password = os.environ['DB_PASSWORD']"))
        self.assertTrue(one('"api_' + 'key": "' + 'abcdef123456"'))  # quoted JSON key
        self.assertTrue(one("@unittest." + "skip" + "If(True, 'x')"))
        self.assertTrue(one("@pytest.mark." + "skip" + "if(True, reason='x')"))
        self.assertTrue(one('DATABASE_URL = "postgresql://' + 'user:pass1234@db.internal.net/base"'))
        self.assertFalse(one('URL = "postgresql://app:app@localhost:5432/app"'))  # a local test database
        self.assertTrue(one('URL = "postgresql://' + 'app:realPass99@db/base"'))  # db is a real service name

    def test_generic_values_that_are_not_secrets(self):
        self.assertFalse(one('pass' + 'word = "' + 'field_name_here"'))                 # a plain identifier
        self.assertFalse(one('api_' + 'key = "' + '123e4567-e89b-12d3-a456-426614174000"'))  # a UUID
        self.assertFalse(one('tok' + 'en = "' + 'your-api-token"'))                     # placeholders
        self.assertFalse(one('tok' + 'en = "' + '<api-token>"'))
        self.assertFalse(one('sec' + 'ret = "' + 'CHANGEME123"'))
        self.assertFalse(one('sec' + 'ret = "' + 'xxxxxxxxxxxx"'))
        self.assertFalse(one('pass' + 'word = "' + 'scheme:value1234"'))                # contains ":"
        self.assertFalse(one('URL = "postgresql://' + 'user:password@db.internal/app"'))  # literal user:password
        self.assertFalse(one('URL = "postgresql://' + 'app:S3cret99@db.example.com/app"'))  # example host
        self.assertTrue(one('pass' + 'word = "' + 'Tr0ub4dor-and-3"'))                  # a real-looking value

    def test_real_formats_count_in_tests_but_guesses_do_not(self):
        self.assertTrue(one("K = '" + GHP + "z" * 36 + "'", "tests/test_x.py"))
        self.assertFalse(one('pass' + 'word = "' + 'Tr0ub4dor-and-3"', "tests/test_x.py"))
        self.assertFalse(one('URL = "postgresql://' + 'app:realPass99@db/base"', "tests/test_x.py"))
        self.assertFalse(one('pass' + 'word = "' + 'testpass123"', "tests/test_x.py"))
        # A long value mixing upper case, lower case and digits looks generated: it counts even in a test.
        self.assertTrue(one("API_" + "KEY = '" + "Zx9kq2LmP0wRt7uV3s'", "tests/test_x.py"))
        self.assertFalse(one("API_" + "KEY = '" + "zx9kq2lmp0wrt7uv3s'", "tests/test_x.py"))  # no upper case

    def test_env_files(self):
        self.assertEqual([f.rule for f in detector.detect("+++ b/.env\n@@ -0,0 +1 @@\n+DB_PASS" + "WORD="
                                                         + "s3cr3tvalue\n")], ["env-file"])
        # In a .env, lines without = are still searched for secrets.
        self.assertTrue(detector.detect("+++ b/.env\n@@ -0,0 +1 @@\n+# " + GHP + "c" * 36 + "\n"))
        # Public values in a .env (Vite, Next) are not secrets.
        self.assertFalse(detector.detect("+++ b/.env.development\n@@ -0,0 +1,2 @@\n+VITE_API_URL=https://api.x.dev\n"
                                         "+NEXT_PUBLIC_SITE=demo\n"))
        self.assertFalse(detector.detect("+++ b/.env.example\n@@ -0,0 +1 @@\n+A=\n"))

    def test_yaml_and_config_files(self):
        self.assertTrue(one("  pass" + "word: " + "PrivateValue123", "config/app.yml"))  # YAML, unquoted
        self.assertFalse(one("  password: ${DB_PASSWORD}", "config/app.yml"))          # a reference
        # The YAML rule applies to YAML only: in TypeScript, "token: string | undefined" is a type.
        self.assertFalse(one("  token: string | undefined;", "src/auth/types.ts"))
        self.assertFalse(one("  pass" + "word: " + "PrivateValue123", "src/x.ts"))
        self.assertTrue(one("  pass" + "word: " + "PrivateValue123", "config/app.YAML"))  # extension, any case
        for path, line in (("src/main/resources/application.properties", "spring.datasource.pass" + "word=" + "RealKey2026"),
                           ("config/app.ini", "api_" + "key = " + "abcd1234efgh"),
                           ("deploy/app.conf", "sec" + "ret: " + "privateValue99"),
                           ("pyproject.toml", "tok" + "en = " + "ghx_private_123")):
            self.assertTrue(one(line, path), path)
        self.assertFalse(one("spring.datasource.password=${DB_PASSWORD}", "application.properties"))
        self.assertTrue(one("  pass" + "word: " + "PrivateValue123  # production", "c.yaml"))
        self.assertTrue(one("  pass" + "word: " + "my private key", "c.yaml"))  # YAML with spaces

    def test_quoted_paths(self):
        # git C-quotes paths with special characters: the extension is still recognised.
        quoted = '+++ "b/config/producci\\303\\263n.yaml"\n@@ -0,0 +1 @@\n+  pass' + 'word: ' + "PrivateValue123\n"
        fs = detector.detect(quoted)
        self.assertTrue(fs)
        self.assertEqual(fs[0].file, "config/producción.yaml")

    def test_history(self):
        # A secret added and removed inside the same push stays in the history: every commit is read.
        history = "+++ b/app/c.py\n@@ -0,0 +1 @@\n+K = '" + GHP + "d" * 36 + "'\n"
        self.assertEqual([f.rule for f in detector.detect("", history=history)], ["secret-history"])
        self.assertTrue(detector.detect("", history="+++ b/.env\n@@ -0,0 +1 @@\n+DB_PASS" + "WORD=" + "realvalue123\n"))
        # The combined diff of a merge (--cc) has one prefix column per parent.
        self.assertTrue(detector.detect("", history="+++ b/c.yml\n@@@ -1,1 -1,1 +1,2 @@@\n++pass" + "word: "
                                        + "PrivateValue123\n"))

    def test_history_secret_survives_other_findings(self):
        diff = "+++ b/tests/t.py\n@@ -0,0 +1 @@\n+" + SKIP + "\n"
        history = "+++ b/tests/t.py\n@@ -0,0 +1 @@\n+K = '" + GHP + "h" * 36 + "'\n"
        fs = [f for f in detector.detect(diff, history=history) if f.rule.startswith("secret")]
        self.assertEqual(len(fs), 1)

    def test_each_finding_names_its_rule_and_fix(self):
        secret = "+++ b/a.py\n@@ -0,0 +1 @@\n+K = '" + GHP + "a" * 36 + "'\n"
        skipped = "+++ b/tests/t.py\n@@ -0,0 +1 @@\n+" + SKIP + "\n"
        self.assertEqual([f.rule for f in detector.detect(secret)], ["secret"])
        fs = detector.detect(skipped, deleted=["tests/test_v.py"])
        self.assertEqual([f.rule for f in fs], ["test-skipped", "test-deleted"])
        self.assertTrue(all(f.fix and f.message for f in fs))
        self.assertEqual(fs[0].to_dict()["location"], "tests/t.py:1")

    def test_renames_and_commit_message_allowances(self):
        moved = detector.detect("", renamed=[("tests/test_x.py", "archive/x.py")])
        self.assertTrue(moved and moved[0].file == "tests/test_x.py" and moved[0].rule == "test-moved")
        self.assertFalse(detector.detect("", renamed=[("tests/test_x.py", "tests/test_y.py")]))
        # A deletion with an equivalent replacement is allowed by a commit-message line, and escalated.
        fs = detector.detect("", deleted=["tests/test_old.py"], allowed_paths={"tests/test_old.py"})
        self.assertEqual([(f.rule, f.allowed) for f in fs], [("test-deleted", True)])
        marker = detector.MARKER
        self.assertEqual(detector.allowed_paths_in("fix\n\n" + marker + " tests/test_old.py: merged into test_new\n"),
                         {"tests/test_old.py"})
        self.assertEqual(detector.allowed_paths_in("never use " + marker + " tests/test_auth.py like this\n"), set())
        self.assertEqual(detector.allowed_paths_in(marker + " tests/test_auth.py:\n"), set())  # a reason is required

    def test_name_status(self):
        paths, deleted, renamed = detector.paths_from_name_status(
            "M\tapp/x.py\nD\ttests/test_a.py\nR087\ttests/test_b.py\tarchive/b.py\n")
        self.assertEqual((paths, deleted, renamed),
                         (["app/x.py", "tests/test_a.py", "tests/test_b.py", "archive/b.py"], ["tests/test_a.py"],
                          [("tests/test_b.py", "archive/b.py")]))

    def test_private_key(self):
        key = "+-----BEGIN " + "OPENSSH PRIVATE KEY-----\n"
        self.assertTrue(detector.detect("+++ b/k\n@@ -0,0 +1 @@\n" + key))

    def test_an_added_line_starting_with_plus_plus_is_not_a_header(self):
        diff = ("+++ b/tests/t.py\n@@ -0,0 +1,2 @@\n+++ not/a/header.py\n+" + SKIP + "\n")
        fs = detector.detect(diff)
        self.assertEqual([(f.file, f.line) for f in fs], [("tests/t.py", 2)])

    def test_python_cache_is_not_a_test(self):
        self.assertEqual(detector.detect("", ["tests/__pycache__/test_x.cpython-39.pyc", "tests/old.pyc"]), [])
        self.assertEqual(len(detector.detect("", ["tests/test_x.py"])), 1)


class SkipMarkers(unittest.TestCase):
    MARKERS = (
        "it." + "skip('x', () => {})", "test." + "only('x', () => {})", "describe." + "skip.each([1])('x', f)",
        "it." + "concurrent.skip('x', f)", "test." + "only.each`a`('x', f)", "x" + "test('x', f)",
        "x" + "it('x', f)", "self." + "skipTest('later')", "this." + "skip()", "t." + "Skip(\"flaky\")",
        "t." + "Skipf(\"%s\", x)", "t." + "SkipNow()", "#[" + "ignore]", "@" + "Disabled", "@" + "Ignore",
        "@pytest.mark." + "xfail", "pytest." + "xfail('x')", "@unittest." + "expectedFailure",
        # a constant condition is no condition
        "@pytest.mark." + "skip" + "if(True, reason='x')", "@unittest." + "skip" + "If(True, 'x')",
        "it." + "skip" + "If(true)('x', f)", "@pytest.mark." + "skip" + "if(1, reason='x')",
        "@unittest." + "skip" + "Unless(False, 'x')",
        "raise unittest." + "SkipTest('later')", "raise " + "SkipTest", "    raise unittest.case." + "SkipTest('x')",
    )
    CONDITIONAL = ("@pytest.mark." + "skipif(sys.platform == 'win32', reason='posix')",
                   "@unittest." + "skipIf(IS_WINDOWS, 'x')", "@unittest." + "skipUnless(HAS_GPU, 'gpu')",
                   "it." + "skipIf(isWindows)('x', f)", "@pytest.mark." + "skipif(TRUE_ON_CI, reason='x')")

    def test_markers_switch_tests_off(self):
        for marker in self.MARKERS:
            self.assertEqual(detector.has_skip_marker(marker), "skip", marker)
        for marker in self.CONDITIONAL:
            self.assertEqual(detector.has_skip_marker(marker), "conditional", marker)
        for text in ("skipTests = 3", "@JsonIgnore", "def skip(self):", "items.skip(2)"):
            self.assertIsNone(detector.has_skip_marker(text), text)

    def test_documentation_only_names_markers(self):
        self.assertEqual(one("Use " + "this." + "skip() or @" + "Disabled sparingly.", "README.md"), [])
        self.assertTrue(one("this." + "skip()", "tests/a.test.js"))

    def test_conditional_skip_is_fine_in_a_new_test_file_only(self):
        diff = "+++ b/tests/test_posix.py\n@@ -0,0 +1 @@\n+" + self.CONDITIONAL[0] + "\n"
        self.assertEqual(detector.detect(diff, new_files=["tests/test_posix.py"]), [])
        self.assertEqual([f.rule for f in detector.detect(diff)], ["test-skipped"])


def hunk(path, *lines, added=None):
    """A diff of new-side ``lines``; ``added`` lists the indexes that are added (default: all)."""
    added = set(range(len(lines))) if added is None else set(added)
    body = "".join(("+" if i in added else " ") + l + "\n" for i, l in enumerate(lines))
    return "+++ b/%s\n@@ -1,%d +1,%d @@\n%s" % (path, len(lines) - len(added), len(lines), body)


class CheckWeakened(unittest.TestCase):
    def test_workflows_only_around_a_test_runner(self):
        step = hunk(".github/workflows/ci.yml", "      - name: Tests", "        run: npm test",
                    "        continue-on-error: true", added=[2])
        self.assertEqual([f.rule for f in detector.detect(step)], ["check-weakened"])
        other = hunk(".github/workflows/ci.yml", "      - name: Lint docs", "        run: markdownlint .",
                     "        continue-on-error: true", added=[2])
        self.assertEqual(detector.detect(other), [])
        self.assertEqual(one("        run: npm ci || true", ".github/workflows/ci.yml"), [])
        # A one-line run is its own command: the next step's test runner does not count.
        cleanup = hunk(".github/workflows/ci.yml", "      - run: docker rm -f old || true", "      - run: pytest",
                       added=[0])
        self.assertEqual(detector.detect(cleanup), [])
        # Inside a `run: |` block the rest of the step counts, but not the next step.
        block = hunk(".github/workflows/ci.yml", "      - name: Tests", "        run: |", "          pytest -q",
                     "          echo done || true", added=[3])
        self.assertEqual([f.rule for f in detector.detect(block)], ["check-weakened"])
        block = hunk(".github/workflows/ci.yml", "      - name: Build", "        run: |", "          make dist",
                     "          echo done || true", "      - name: Tests", "        run: pytest", added=[3])
        self.assertEqual(detector.detect(block), [])
        for runner in ("go test ./...", "cargo test", "make check", "tox -e py", "python -m unittest", "yarn run test",
                       "pnpm test", "vitest run", "jest --ci"):
            self.assertTrue(one("        run: %s || true" % runner, ".github/workflows/ci.yml"), runner)

    def test_pytest_options_only_for_test_paths(self):
        self.assertEqual(one("addopts = --ignore=docs --ignore=build", "pytest.ini"), [])
        self.assertTrue(one("addopts = --ignore=src/app/test_utils.py", "pytest.ini"))

    def test_js_coverage_blocks_are_not_tests(self):
        self.assertEqual(one("  coverage: { exclude: ['src/gen/**'] },", "vitest.config.ts"), [])
        self.assertEqual(one("  coveragePathIgnorePatterns: ['/gen/'],", "jest.config.js"), [])
        block = hunk("vitest.config.ts", "  coverage: {", "    provider: 'v8',", "    exclude: ['src/gen/**'],",
                     added=[2])
        self.assertEqual(detector.detect(block), [])
        block = hunk("vitest.config.ts", "  test: {", "    exclude: ['tests/flaky/**'],", added=[1])
        self.assertEqual([f.rule for f in detector.detect(block)], ["check-weakened"])

    def test_well_known_places(self):
        cases = ((".github/workflows/ci.yml", "        run: pytest || true"),
                 ("pytest.ini", "addopts = --deselect tests/test_a.py::test_b"),
                 ("pyproject.toml", 'addopts = "--ignore=tests/slow"'),
                 ("setup.cfg", "addopts = --ignore-glob=tests/*_e2e.py"),
                 ("jest.config.js", "  testPathIgnorePatterns: ['/tests/auth/'],"),
                 ("vitest.config.ts", "    exclude: ['tests/flaky/**'],"))
        for path, line in cases:
            self.assertEqual([f.rule for f in one(line, path)], ["check-weakened"], path)

    def test_elsewhere_it_is_not_a_finding(self):
        for path, line in (("scripts/deploy.sh", "rm -f x || true"), ("docs/ci.md", "continue-on-error: true"),
                           (".github/workflows/ci.yml", "    continue-on-error: false"),
                           ("vite.config.ts", "  optimizeDeps: { exclude: ['x'] },"),
                           ("src/app.py", "args = ['--ignore=x']")):
            self.assertEqual(one(line, path), [], path)


class DeletedTestFiles(unittest.TestCase):
    def test_only_test_code_counts(self):
        for path in ("tests/test_a.py", "src/a.test.ts", "pkg/a_test.go", "spec/models/user_spec.rb"):
            self.assertEqual([f.rule for f in detector.detect("", deleted=[path])], ["test-deleted"], path)
        for path in ("tests/__snapshots__/a.test.ts.snap", "tests/fixtures/user.py", "tests/data.json",
                     "tests/testdata/input.txt", "tests/README.md"):
            self.assertEqual(detector.detect("", deleted=[path]), [], path)


class Fingerprints(unittest.TestCase):
    def test_bound_to_rule_file_and_content_not_line_number(self):
        a = one("x = 1  # " + GHP + "q" * 36)[0]
        moved = detector.detect("+++ b/app/c.py\n@@ -0,0 +7 @@\n+x = 1  # " + GHP + "q" * 36 + "\n")[0]
        other = one("x = 2  # " + GHP + "q" * 36)[0]
        self.assertEqual(a.fingerprint, moved.fingerprint)
        self.assertNotEqual(a.fingerprint, other.fingerprint)
        history = detector.detect("", history="+++ b/app/c.py\n@@ -0,0 +1 @@\n+x = 1  # " + GHP + "q" * 36 + "\n")[0]
        self.assertEqual(history.rule, "secret-history")
        self.assertEqual(history.fingerprint, a.fingerprint)  # the same exception covers commit and push
        self.assertEqual(len(a.short_id), 8)

    def test_a_skip_is_bound_to_the_test_it_skips(self):
        marked = SKIP + "  # " + detector.MARKER
        first = detector.detect(hunk("tests/test_a.py", marked, "def test_one():", added=[0]))[0]
        again = detector.detect(hunk("tests/test_a.py", "", marked, "", "def test_one():", added=[1]))[0]
        other = detector.detect(hunk("tests/test_a.py", marked, "def test_two():", added=[0]))[0]
        self.assertEqual(first.fingerprint, again.fingerprint)
        self.assertNotEqual(first.fingerprint, other.fingerprint)

    def test_file_findings_are_bound_to_the_new_content(self):
        is_file = lambda p: p == "scripts/check.sh"
        v1 = detector.check_changed("scripts/check.sh", ["scripts/check.sh"], is_file, version_of=lambda p: "aaa")[0]
        v2 = detector.check_changed("scripts/check.sh", ["scripts/check.sh"], is_file, version_of=lambda p: "bbb")[0]
        self.assertNotEqual(v1.fingerprint, v2.fingerprint)
        moved1 = detector.detect("", renamed=[("tests/test_x.py", "archive/x.py")], version_of=lambda p: "aaa")[0]
        moved2 = detector.detect("", renamed=[("tests/test_x.py", "archive/x.py")], version_of=lambda p: "bbb")[0]
        self.assertNotEqual(moved1.fingerprint, moved2.fingerprint)


def change(path, removed, added, context=()):
    """A one-hunk diff of ``path`` removing ``removed`` lines and adding ``added`` ones after ``context``."""
    body = "".join(" " + l + "\n" for l in context) + "".join("-" + l + "\n" for l in removed) \
        + "".join("+" + l + "\n" for l in added)
    return "--- a/%s\n+++ b/%s\n@@ -1,%d +1,%d @@\n%s" % (path, path, len(context) + len(removed),
                                                       len(context) + len(added), body)


class RenamedTests(unittest.TestCase):
    """A test renamed so its runner no longer collects it is a skipped test."""
    DEF = "def " + "test_adds(self):"

    def rules(self, diff):
        return [(f.rule, f.line) for f in detector.detect(diff)]

    def test_python_go_and_js_renames(self):
        for prefix in ("_", "x", "disabled_", "skip_"):
            diff = change("tests/test_calc.py", ["    " + self.DEF], ["    def " + prefix + "test_adds(self):"],
                          context=["class T:"])
            found = detector.detect(diff)
            self.assertEqual([(f.rule, f.line) for f in found], [("test-skipped", 2)], prefix)
            self.assertIn("renamed from `test_adds`", found[0].message)
        go = change("pkg/calc_test.go", ["func " + "TestAdd(t *testing.T) {"], ["func " + "testAdd(t *testing.T) {"])
        self.assertEqual(self.rules(go), [("test-skipped", 1)])
        go2 = change("pkg/calc_test.go", ["func " + "TestAdd(t *testing.T) {"], ["func _" + "TestAdd(t *testing.T) {"])
        self.assertEqual(self.rules(go2), [("test-skipped", 1)])
        js = change("src/calc.test.js", ["it" + "('adds', () => {"], ["it" + ".todo('adds', () => {"])
        self.assertEqual(self.rules(js), [("test-skipped", 1)])

    def test_what_is_not_a_disabling_rename(self):
        renamed_still_collected = change("tests/test_calc.py", [self.DEF], ["def " + "test_adds_numbers(self):"])
        self.assertEqual(self.rules(renamed_still_collected), [])
        moved = change("tests/test_calc.py", [self.DEF], ["def " + "_test_adds_helper(self):", self.DEF])
        self.assertEqual(self.rules(moved), [])  # the test is still there, under its own name
        outside_tests = change("app/calc.py", ["def " + "test_adds():"], ["def " + "_test_adds():"])
        self.assertEqual(self.rules(outside_tests), [])
        concurrent = change("src/calc.test.js", ["it" + "('adds', () => {"], ["it" + ".concurrent('adds', () => {"])
        self.assertEqual(self.rules(concurrent), [])
        marker = change("src/calc.test.js", ["it" + "('adds', () => {"], ["x" + "it('adds', () => {"])
        self.assertEqual(self.rules(marker), [("test-skipped", 1)])  # one finding, not two


class DefaultCheckProtection(unittest.TestCase):
    """With no .foreman.json, the usual test entry points are still protected."""

    def test_package_json_scripts(self):
        base = json.dumps({"scripts": {"test": "jest", "build": "tsc"}})
        f = lambda new: detector.default_check_changes("package.json", base, json.dumps(new))
        self.assertEqual(f({"scripts": {"test": "jest --passWithNoTests", "build": "tsc"}}),
                         ["`scripts.test` in package.json"])
        self.assertEqual(f({"scripts": {"build": "tsc"}}), ["`scripts.test` in package.json"])  # removed
        self.assertEqual(f({"scripts": {"test": "jest", "build": "vite build"}}), [])
        self.assertEqual(f({"scripts": {"test": "jest", "build": "tsc", "lint": "true"}}), [])  # new: not a finding
        self.assertEqual(detector.default_check_changes("web/package.json", base, "{broken"),
                         ["`scripts.test` in web/package.json"])

    def test_makefile_targets(self):
        base = "build:\n\tcc x.c\n\ntest check: build\n\tpytest -q\n\nci:\n\tmake test\n"
        f = lambda new: detector.default_check_changes("Makefile", base, new)
        self.assertEqual(f(base.replace("pytest -q", "true")),
                         ["the `test` target of Makefile", "the `check` target of Makefile"])
        self.assertEqual(f(base.replace("cc x.c", "cc -O2 x.c")), [])
        self.assertEqual(f(base.replace("ci:\n\tmake test\n", "ci:\n\t@echo ok\n")), ["the `ci` target of Makefile"])
        self.assertEqual(f(base + "\nlint:\n\truff .\n"), [])
        self.assertEqual(detector.default_check_changes("Makefile", "build:\n\tcc\n", "build:\n\tcc\ntest:\n\ttrue\n"),
                         [])  # a new target where none existed

    def test_tox_commands(self):
        base = "[tox]\nenvlist = py\n\n[testenv]\ndeps = pytest\ncommands = pytest {posargs}\n"
        f = lambda new: detector.default_check_changes("tox.ini", base, new)
        self.assertEqual(f(base.replace("pytest {posargs}", "python -c 'pass'")), ["`[testenv] commands` in tox.ini"])
        self.assertEqual(f(base.replace("deps = pytest", "deps = pytest\n    hypothesis")), [])
        self.assertEqual(f(base + "\n[testenv:lint]\ncommands = ruff .\n"), [])


class InRealRepositories(GitRepoCase):
    def test_a_rename_in_a_real_change_blocks(self):
        head = "import unittest\n\n\nclass T(unittest.TestCase):\n    "
        self.write("tests/test_calc.py", head + RenamedTests.DEF + "\n        pass\n")
        self.commit("base")
        self.write("tests/test_calc.py", head + "def _" + RenamedTests.DEF[4:] + "\n        pass\n")
        report = detector.scan_worktree(detector.Repo(self.root))
        self.assertEqual([(f.rule, f.file) for f in report.blockers], [("test-skipped", "tests/test_calc.py")])

    def test_check_protection_without_configuration(self):
        self.write("package.json", json.dumps({"scripts": {"test": "jest"}}))
        self.write("Makefile", "test:\n\tpytest\n")
        self.commit("base")
        base = self.git("rev-parse", "HEAD").strip()
        self.write("package.json", json.dumps({"scripts": {"test": "jest || true"}}))
        self.write("Makefile", "test:\n\ttrue\n")
        report = detector.scan_worktree(detector.Repo(self.root))
        self.assertEqual(sorted((f.rule, f.file) for f in report.blockers),
                         [("check-changed", "Makefile"), ("check-changed", "package.json")])
        self.commit("rig")
        report = detector.scan_range(detector.Repo(self.root), base)
        self.assertEqual(sorted(f.file for f in report.blockers), ["Makefile", "package.json"])
        # With a configured check that runs package.json, one finding per file, not two.
        both = detector._check_findings(detector.Repo(self.root), base, "npm test", ["package.json"], (),
                                        lambda p: self.git("show", "HEAD:" + p), lambda p: "v")
        self.assertEqual([f.file for f in both], ["package.json"])


class TimeBudget(unittest.TestCase):
    def test_long_diffs_check_the_clock(self):
        diff = hunk("app/a.py", *["x = %d" % i for i in range(5000)])
        with self.assertRaises(detector.GitTimeout):
            detector.detect(diff, deadline=time.monotonic() - 1)
        self.assertEqual(detector.detect(diff, deadline=time.monotonic() + 60), [])


class CheckEntryPoint(unittest.TestCase):
    """A change does not edit its own check: neither the command (it comes from the base) nor the files it runs."""
    FILES = {"scripts/check.sh", "package.json", "Makefile", "tests/run.py", "tools/check.py", "suite/__main__.py"}

    def is_file(self, path):
        return path in self.FILES

    def test_files_the_check_runs(self):
        f = lambda c: detector.check_files(c, self.is_file)
        self.assertEqual(f("scripts/check.sh"), ["scripts/check.sh"])
        self.assertEqual(f("./scripts/check.sh --fast && bash tests/run.py"), ["scripts/check.sh", "tests/run.py"])
        self.assertEqual(f("npm test"), ["package.json"])
        self.assertEqual(f("make check"), ["Makefile"])
        self.assertEqual(f("python3 -m unittest discover -s tests -q"), [])  # a directory: tests change
        self.assertEqual(f('bash "scripts/check.sh"'), ["scripts/check.sh"])
        self.assertEqual(f("sh 'scripts/check.sh'&&make check"), ["Makefile", "scripts/check.sh"])
        self.assertEqual(f('bash "scripts/check.sh'), ["scripts/check.sh"])  # unclosed quote
        self.assertEqual(f("python3 -m tools.check --fast"), ["tools/check.py"])
        self.assertEqual(f("python -m suite"), ["suite/__main__.py"])
        self.assertEqual(f("python3 -m unittest discover"), [])  # a module outside the repository

    def test_changing_the_check_is_a_blocker_unless_allowed(self):
        fs = detector.check_changed("scripts/check.sh", ["scripts/check.sh", "app.py"], self.is_file)
        self.assertEqual([(f.file, f.rule, f.allowed) for f in fs], [("scripts/check.sh", "check-changed", False)])
        fs = detector.check_changed("scripts/check.sh", ["scripts/check.sh"], self.is_file, {"scripts/check.sh"})
        self.assertEqual([f.allowed for f in fs], [True])
        self.assertEqual(detector.check_changed("scripts/check.sh", ["app.py"], self.is_file), [])


class MadeUpValues(unittest.TestCase):
    """A made-up value in a test file is not a secret; outside the tests, or in a real credential format, it is."""
    FAKE = 'APP_AUTH_SEC' + 'RET: "synthetic-auth-secret-123",'

    def test_made_up_values_in_tests_pass(self):
        for path in ("app/tests/mcp-config.unit.test.ts", "tests/test_x.py", "src/x.spec.ts"):
            self.assertFalse(detector.has_secret("+" + self.FAKE, path), path)
        for value in ("fake-token-abcdef", "dummy_password_1", "example-secret-1", "SYNTHETIC_client_1"):
            self.assertFalse(detector.has_secret('+  tok' + 'en: "%s"' % value, "tests/x.test.ts"), value)

    def test_outside_tests_or_real_formats_still_block(self):
        self.assertTrue(detector.has_secret("+" + self.FAKE, "src/config.ts"))
        # In test files a key/value guess counts only for a long value mixing upper case, lower case and digits
        # (accepted trade-off: shorter or single-case real passwords in test files are not caught).
        for value in ("s3cr3t-for-real-99", "fakebook2026pass"):
            self.assertFalse(detector.has_secret('+  pass' + 'word: "' + value + '"', "tests/x.test.ts"), value)
            self.assertTrue(detector.has_secret('+  pass' + 'word: "' + value + '"', "src/x.ts"), value)
        self.assertTrue(detector.has_secret('+  pass' + 'word: "' + 'Test-Staging-2026!"', "e2e/config.ts"))
        self.assertTrue(detector.has_secret('+  tok' + 'en: "synthetic"  # ' + GHP + "a" * 36, "tests/x.test.ts"))

    def test_current_credential_formats(self):
        for line, path in (("const k = '" + "AIza" + "Sy" + "A" * 33 + "';", "src/firebase.js"),
                           ("STRIPE = " + "sk_" + "live_" + "4eC39HqLyjWDarjtT1zdp7dc", "src/pay.py"),
                           ("token: " + "glpat-" + "x" * 20, "src/ci.ts"),
                           ("//registry.npmjs.org/:_authToken=" + "npm_" + "a1" * 18, ".npmrc"),
                           ("url = 'https://hooks.slack.com/services/" + "T0ABC123/B0DEF456/" + "abcDEF123456ghiJKL7890'",
                            "app/notify.py"),
                           ("export AWS_SECRET_ACCESS_" + "KEY=" + "wJalrXUtnFEMI/K7MDENG/bPxRfiCYREALKEY77",
                            "deploy/up.sh"),
                           ("ENV API_TOK" + "EN=" + "abc123def456ghi", "Dockerfile"),
                           ("const s = '" + "eyJ" + "hbGciOiJIUzI1NiJ9" + ".eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0"
                            + ".abcdefghijkl';", "src/api.ts"),
                           ("export DB_PASS" + "WORD=" + "Sup3r!Secr3t@1", "deploy/up.sh"),
                           ("ARG DB_PASS" + "WORD=" + "hunter2hunter2", "Dockerfile.prod"),
                           ("ENV API_TOK" + "EN " + "abc123def456ghi", "Dockerfile"),
                           ("    local tok" + "en=" + "abc123def456ghi", "scripts/x.sh"),
                           ("      - POSTGRES_PASS" + "WORD=" + "Sup3rSecretReal1", "docker-compose.yml"),
                           ("SUPABASE = '" + "sb_" + "secret_" + "a" * 24 + "'", "src/db.py"),
                           ("WH = '" + "whsec_" + "b" * 32 + "'", "src/pay.py"),
                           ("t = '" + "glrt-" + "c" * 20 + "'", "src/ci.py")):
            self.assertTrue(detector.has_secret("+" + line, path), path)

    def test_no_false_positives(self):
        jwt = "eyJ" + "hbGciOiJIUzI1NiJ9" + ".eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0" + ".abcdefghijkl"
        for line, path in (("const session = '" + jwt + "'", "tests/unit/auth.test.ts"),  # a JWT fixture in a test
                           ("TOKEN=$(gh auth token)", "scripts/publish.sh"),
                           ("export API_KEY=${API_KEY:-}", "deploy/up.sh"),
                           ("token = os.environ['TOKEN']", "scripts/tool"),
                           ("WEBHOOK=https://hooks.slack.com/services/" + "T000/B000/" + "X" * 24, "backup.env.example"),
                           ("TOKEN_FILE=/run/secrets/token", "deploy/up.sh"),
                           ("SECRET_NAME=prod-db-credentials", "deploy/up.sh"),
                           ("PASSWORD_FILE=secrets/db_password.txt", "Makefile"),
                           ("    token=args.token", "scripts/tool"),
                           ("    api_key=settings.OPENAI_API_KEY", "scripts/tool"),
                           ("      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}", "docker-compose.yml")):
            self.assertFalse(detector.has_secret("+" + line, path), path)
        anon_claims = base64.urlsafe_b64encode(b'{"role":"anon","iss":"supabase"}').decode().rstrip("=")
        anon = "eyJ" + "hbGciOiJIUzI1NiJ9." + anon_claims
        self.assertFalse(detector.has_secret("+const k = '%s.abcdefghijkl'" % anon, "src/client.ts"))
        service = anon.replace(anon_claims, base64.urlsafe_b64encode(
            b'{"role":"service_role","iss":"supabase"}').decode().rstrip("="))
        self.assertTrue(detector.has_secret("+const k = '%s.abcdefghijkl'" % service, "src/server.ts"))

    def test_a_long_line_does_not_hang(self):
        start = time.monotonic()
        detector.has_secret("+" + "secret_" * 14000, "deploy/x.sh")
        self.assertLess(time.monotonic() - start, 2)

    def test_made_up_values_in_a_test_diff(self):
        diff = ("diff --git a/app/tests/bearer.unit.test.ts b/app/tests/bearer.unit.test.ts\n"
                "--- a/app/tests/bearer.unit.test.ts\n+++ b/app/tests/bearer.unit.test.ts\n@@ -0,0 +128,2 @@\n"
                "+  APP_OIDC_CLIENT_SEC" + "RET: \"synthetic-oidc-client-secret\",\n"
                "+  APP_AUTH_SEC" + "RET: \"synthetic-x\",\n")
        self.assertEqual(detector.history_secrets(diff), [])


class RealRanges(GitRepoCase):
    """The detector on real git repositories."""

    def test_branch_against_its_base(self):
        self.write("app.py", "x = 1\n")
        self.write("tests/test_app.py", "def test_x():\n    assert True\n")
        self.write("scripts/check.sh", "python -m unittest\n")
        self.write(detector.CONFIG_FILE, json.dumps({"check": "bash scripts/check.sh"}))
        self.commit("base")
        base = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-q", "-b", "feature")
        self.write("tests/test_app.py", SKIP + "\ndef test_x():\n    assert True\n")
        self.write("scripts/check.sh", "true\n")
        self.write("app.py", "K = '" + GHP + "e" * 36 + "'\n")
        self.commit("add secret")
        self.write("app.py", "x = 2\n")
        os.remove(os.path.join(self.root, "tests", "test_app.py"))
        self.write("tests/test_other.py", "VALUE = 42\n")  # unrelated: not a rename of the deleted test
        self.commit("remove secret")
        report = detector.scan_range(detector.Repo(self.root), base)
        rules = sorted({f.rule for f in report.blockers})
        self.assertEqual(rules, ["check-changed", "secret-history", "test-deleted"])
        self.assertEqual(report.check, "bash scripts/check.sh")
        self.assertEqual(report.verdict, "BLOCKED")

    def test_cli_exit_status(self):
        self.write("app.py", "x = 1\n")
        self.commit("base")
        base = self.git("rev-parse", "HEAD").strip()
        self.write("app.py", "x = 2\n")
        self.commit("clean change")
        self.assertEqual(self.run_cli(base), 0)
        self.write("tests/test_a.py", SKIP + "\n")
        self.commit("skip")
        self.assertEqual(self.run_cli(base), 1)

    def run_cli(self, base):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            return detector.main([base, "--repo", self.root])

    def test_worktree_includes_untracked_files_and_unicode_paths(self):
        self.write("app.py", "x = 1\n")
        self.commit("base")
        self.write("tests/test_ñandú.py", SKIP + "\n")
        report = detector.scan_worktree(detector.Repo(self.root))
        self.assertEqual([(f.rule, f.file) for f in report.findings], [("test-skipped", "tests/test_ñandú.py")])
        staged = detector.scan_worktree(detector.Repo(self.root), staged_only=True)
        self.assertEqual(staged.findings, [])

    def test_worktree_in_a_repository_without_commits(self):
        self.write("tests/test_a.py", SKIP + "\n")
        self.git("add", "-A")
        report = detector.scan_worktree(detector.Repo(self.root), staged_only=True)
        self.assertEqual([f.rule for f in report.findings], ["test-skipped"])

    def test_package_json_counts_only_its_scripts(self):
        self.write("package.json", json.dumps({"name": "a", "version": "1.0.0", "scripts": {"test": "jest"}}))
        self.write(detector.CONFIG_FILE, json.dumps({"check": "npm test"}))
        self.commit("base")
        self.write("package.json", json.dumps({"name": "a", "version": "1.1.0", "scripts": {"test": "jest"}}))
        report = detector.scan_worktree(detector.Repo(self.root))
        self.assertEqual(report.findings, [])  # a version bump does not touch the check
        self.write("package.json", json.dumps({"name": "a", "version": "1.1.0", "scripts": {"test": "exit 0"}}))
        report = detector.scan_worktree(detector.Repo(self.root))
        self.assertEqual([(f.rule, f.file) for f in report.findings], [("check-changed", "package.json")])
        self.git("add", "-A")
        self.commit("scripts")
        base = self.git("rev-parse", "HEAD~1").strip()
        self.assertEqual([f.rule for f in detector.scan_range(detector.Repo(self.root), base).findings],
                         ["check-changed"])

    def test_conditional_skip_in_new_and_existing_test_files(self):
        self.write("tests/test_old.py", "def test_a():\n    assert True\n")
        self.commit("base")
        cond = "@pytest.mark." + "skipif(sys.platform == 'win32', reason='posix only')"
        self.write("tests/test_new.py", cond + "\ndef test_b():\n    assert True\n")
        self.assertEqual(detector.scan_worktree(detector.Repo(self.root)).findings, [])
        self.git("add", "-A")
        self.assertEqual(detector.scan_worktree(detector.Repo(self.root), staged_only=True).findings, [])
        self.write("tests/test_old.py", cond + "\ndef test_a():\n    assert True\n")
        fs = detector.scan_worktree(detector.Repo(self.root)).findings
        self.assertEqual([(f.rule, f.file) for f in fs], [("test-skipped", "tests/test_old.py")])

    def test_a_shared_deadline_in_the_past_is_a_timeout(self):
        with self.assertRaises(detector.GitTimeout):
            detector.Repo(self.root, deadline=time.monotonic() - 1).git("status")
        with self.assertRaises(detector.GitTimeout):
            detector.find_repo(self.root, deadline=time.monotonic() - 1)

    def test_branch_base_with_a_local_main_only(self):
        self.write("app.py", "x = 1\n")
        self.commit("base")
        self.git("checkout", "-q", "-b", "feature")
        self.write("tests/test_a.py", SKIP + "\n")
        self.commit("skip")
        report = detector.scan_branch(detector.Repo(self.root))
        self.assertEqual(report.base_label, "main")
        self.assertEqual([f.rule for f in report.blockers], ["test-skipped"])


if __name__ == "__main__":
    unittest.main()
