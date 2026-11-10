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
        self.assertTrue(one("@unittest." + "skipIf(True, 'x')"))
        self.assertTrue(one("@pytest.mark." + "skipif(True, reason='x')"))
        self.assertTrue(one('DATABASE_URL = "postgresql://' + 'user:pass1234@db.example.com/base"'))
        self.assertFalse(one('URL = "postgresql://app:app@localhost:5432/app"'))  # a local test database
        self.assertTrue(one('URL = "postgresql://' + 'app:realPass99@db/base"'))  # db is a real service name

    def test_env_files(self):
        self.assertTrue(detector.detect("+++ b/.env\n@@ -0,0 +1 @@\n+DB_PASSWORD=" + "s3cr3tvalue\n"))
        # In a .env, lines without = are still searched for secrets.
        self.assertTrue(detector.detect("+++ b/.env\n@@ -0,0 +1 @@\n+# " + GHP + "c" * 36 + "\n"))
        self.assertEqual([f.rule for f in detector.detect("+++ b/.env\n@@ -0,0 +1 @@\n+A=" + "value\n")], ["env-file"])
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
        self.assertTrue(detector.detect("", history="+++ b/.env\n@@ -0,0 +1 @@\n+DB_PASS=" + "value\n"))
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
        self.assertTrue(detector.has_secret('+  sec' + 'ret: "' + 's3cr3t-for-real-99"', "tests/x.test.ts"))
        self.assertTrue(detector.has_secret('+  pass' + 'word: "' + 'Test-Staging-2026!"', "e2e/config.ts"))
        self.assertTrue(detector.has_secret('+  pass' + 'word: "' + 'fakebook2026pass"', "tests/x.test.ts"))
        self.assertTrue(detector.has_secret('+  tok' + 'en: "synthetic"  # ' + GHP + "a" * 36, "tests/x.test.ts"))
        self.assertTrue(detector.has_secret('+  a: "synthetic-1", pass' + 'word: "' + 'real-password-1"',
                                            "tests/x.test.ts"))

    def test_current_credential_formats(self):
        for line, path in (("const k = '" + "AIza" + "Sy" + "A" * 33 + "';", "src/firebase.js"),
                           ("STRIPE = " + "sk_" + "live_" + "4eC39HqLyjWDarjtT1zdp7dc", "src/pay.py"),
                           ("token: " + "glpat-" + "x" * 20, "src/ci.ts"),
                           ("//registry.npmjs.org/:_authToken=" + "npm_" + "a1" * 18, ".npmrc"),
                           ("url = 'https://hooks.slack.com/services/" + "T0ABC123/B0DEF456/" + "abcDEF123456ghiJKL7890'",
                            "app/notify.py"),
                           ("export AWS_SECRET_ACCESS_" + "KEY=" + "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
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
