"""SARIF as a source: severity, threshold, suppressions, paths, unreadable files, and where the reports come from.

The hermes-security fixture is built in code, mirroring the shape its SARIF renderer emits (``reports/sarif.py``):
rule-level ``security-severity`` as a string holding the MAXIMUM over the rule's findings, a result ``level`` and a
named ``properties.severity``, and percent-encoded relative URIs.
"""
import contextlib
import io
import json
import os
import time
import unittest
from unittest import mock

from foreman import commands, detector, gate, sarif
from tests_support import GitRepoCase

SKIP = "@pytest.mark." + "skip"


def doc(results, rules=None, tool="scanner", **run):
    driver = {"name": tool}
    if rules is not None:
        driver["rules"] = rules
    return {"version": "2.1.0", "runs": [dict({"tool": {"driver": driver}, "results": results}, **run)]}


def result(rule="R1", text="a problem", uri="app/x.py", line=3, **extra):
    r = {"ruleId": rule, "message": {"text": text},
         "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}, "region": {"startLine": line}}}]}
    r.update(extra)
    return r


def hermes_security(findings):
    """What hermes-security's ``render_sarif`` emits for [(ruleId, severity level, path, line, summary)]."""
    levels = {"critical": "error", "high": "error", "medium": "warning", "low": "note", "informational": "note"}
    scores = {"critical": 9.5, "high": 8.0, "medium": 5.0, "low": 2.0, "informational": 0.0}
    rule_ids = sorted({f[0] for f in findings})
    rules = [{"id": rid, "shortDescription": {"text": "title of " + rid},
              "properties": {"tags": ["security", "security-severity"],
                             "security-severity": str(max(scores[f[1]] for f in findings if f[0] == rid))}}
             for rid in rule_ids]
    results = [{"ruleId": rid, "ruleIndex": rule_ids.index(rid), "level": levels[sev], "message": {"text": text},
                "locations": [{"physicalLocation": {"artifactLocation": {"uri": path.replace(" ", "%20")},
                                                    "region": {"startLine": line, "endLine": line}}}],
                "partialFingerprints": {"hermesSecurity/v1": "abc"},
                "properties": {"evidenceState": "CONFIRMED", "findingId": "F-1", "severity": sev}}
               for rid, sev, path, line, text in findings]
    return {"$schema": "https://docs.oasis-open.org/sarif/sarif/v2.1.0/os/schemas/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [{"tool": {"driver": {"name": "hermes-security", "version": "0.1.0", "rules": rules}},
                      "results": results, "properties": {"scanId": "S-1", "status": "complete"}}]}


class SarifCase(GitRepoCase):
    def sarif_file(self, document, name="report.sarif", raw=None):
        path = self.write(name, raw if raw is not None else json.dumps(document))
        return path

    def parse(self, document, threshold=sarif.DEFAULT_THRESHOLD):
        path = self.sarif_file(document)
        return sarif.parse_file(path, self.root, threshold)


class Severity(SarifCase):
    def test_level_maps_to_a_score(self):
        out = self.parse(doc([result("E", level="error"), result("W", level="warning"), result("N", level="note")]))
        self.assertEqual([f.rule for f in out.blockers], ["sarif:scanner/E"])
        self.assertEqual(sorted(f.rule for f in out.notes), ["sarif:scanner/N", "sarif:scanner/W"])
        self.assertTrue(all(f.severity == "blocker" for f in out.blockers))
        self.assertTrue(all(f.severity == "note" for f in out.notes))

    def test_security_severity_on_the_result_wins_over_level(self):
        high = result("H", level="note", properties={"security-severity": "9.1"})
        low = result("L", level="error", properties={"security-severity": 3.0})
        out = self.parse(doc([high, low]))
        self.assertEqual([f.rule for f in out.blockers], ["sarif:scanner/H"])
        self.assertEqual([f.rule for f in out.notes], ["sarif:scanner/L"])

    def test_security_severity_on_the_rule_beats_level(self):
        rules = [{"id": "R1", "properties": {"security-severity": "7.5"}}, {"id": "R2", "properties": {"security-severity": "4.0"}}]
        out = self.parse(doc([result("R1", level="note"), result("R2", level="error")], rules))
        self.assertEqual([f.rule for f in out.blockers], ["sarif:scanner/R1"])

    def test_the_rules_default_level_then_sarifs_default(self):
        rules = [{"id": "R1", "defaultConfiguration": {"level": "error"}}, {"id": "R2"}]
        out = self.parse(doc([result("R1"), result("R2")], rules))
        self.assertEqual([f.rule for f in out.blockers], ["sarif:scanner/R1"])
        self.assertEqual([f.rule for f in out.notes], ["sarif:scanner/R2"])  # warning by default: below 7.0

    def test_rule_found_by_index_or_by_id(self):
        rules = [{"id": "A", "properties": {"security-severity": "1.0"}}, {"id": "B", "properties": {"security-severity": "9.0"}}]
        by_index = result("whatever", ruleIndex=1)
        by_nested = {"rule": {"id": "B"}, "message": {"text": "m"}}
        out = self.parse(doc([by_index, by_nested], rules))
        self.assertEqual(len(out.blockers), 2)

    def test_garbage_scores_are_ignored(self):
        out = self.parse(doc([result("A", level="error", properties={"security-severity": "high"}),
                              result("B", level="error", properties={"security-severity": 99}),
                              result("C", level="error", properties={"security-severity": True})]))
        self.assertEqual(len(out.blockers), 3)  # all fall back to level error

    def test_threshold(self):
        results = [result("E", level="error"), result("W", level="warning"), result("S", properties={"security-severity": "6.9"})]
        self.assertEqual(len(self.parse(doc(results)).blockers), 1)
        self.assertEqual(len(self.parse(doc(results), sarif.parse_threshold("warning")).blockers), 3)
        self.assertEqual(len(self.parse(doc(results), sarif.parse_threshold("6.9")).blockers), 2)
        self.assertEqual(len(self.parse(doc(results), sarif.parse_threshold(9)).blockers), 0)
        for bad in ("fatal", "11", "-1", "nan", None, True, ""):
            with self.assertRaises(ValueError):
                sarif.parse_threshold(bad)

    def test_suppressions_and_absent_baseline_never_block(self):
        results = [result("A", level="error", suppressions=[{"kind": "inSource", "status": "accepted"}]),
                   result("B", level="error", suppressions=[{"kind": "external"}]),
                   result("C", level="error", baselineState="absent"),
                   result("D", level="error", suppressions=[{"kind": "external", "status": "rejected"}]),
                   result("E", level="error", suppressions=[], baselineState="unchanged"),
                   result("F", level="error", baselineState="new")]
        out = self.parse(doc(results))
        self.assertEqual(sorted(f.rule[-1] for f in out.blockers), ["D", "E", "F"])
        self.assertEqual(out.notes, [])  # suppressed or fixed results are not even listed

    def test_message_is_one_line_and_has_fallbacks(self):
        out = self.parse(doc([result("A", text="first\n  second\t\tthird " + "x" * 400, level="error"),
                              {"ruleId": "B", "level": "error", "message": {}}], [{"id": "B", "shortDescription": {"text": "from the rule"}}]))
        a, b = out.blockers
        self.assertNotIn("\n", a.message)
        self.assertLess(len(a.message), 300)
        self.assertTrue(a.message.startswith("first second third"))
        self.assertTrue(b.message.startswith("from the rule"))
        self.assertEqual((a.file, a.line), ("app/x.py", 3))
        self.assertEqual((b.file, b.line), ("", 0))  # no location is not a crash

    def test_identity_is_stable_and_distinct(self):
        one = self.parse(doc([result("A", level="error")])).blockers[0]
        again = self.parse(doc([result("A", level="error")])).blockers[0]
        other = self.parse(doc([result("A", level="error", line=4)])).blockers[0]
        self.assertEqual(one.fingerprint, again.fingerprint)
        self.assertNotEqual(one.fingerprint, other.fingerprint)
        self.assertFalse(one.allowed)


class HermesSecurityShape(SarifCase):
    FINDINGS = [("HS-SQLI", "critical", "src/db/query.py", 41, "SQL built from request data"),
                ("HS-XSS", "high", "web/my page.js", 7, "Unescaped output"),
                ("HS-XSS", "medium", "web/other.js", 9, "Unescaped output, lower confidence"),
                ("HS-HDR", "low", "src/app.py", 12, "Missing header")]

    def test_levels_and_the_per_result_severity(self):
        out = self.parse(hermes_security(self.FINDINGS))
        blocking = sorted((f.file, f.line) for f in out.blockers)
        # The rule HS-XSS carries the MAX score (8.0) for both of its results; the medium one must not block.
        self.assertEqual(blocking, [("src/db/query.py", 41), ("web/my page.js", 7)])
        self.assertEqual(sorted((f.file, f.line) for f in out.notes), [("src/app.py", 12), ("web/other.js", 9)])
        self.assertTrue(all(f.rule.startswith("sarif:hermes-security/HS-") for f in out.blockers + out.notes))
        self.assertIn("severity critical", [f for f in out.blockers if f.line == 41][0].message)

    def test_a_lowered_threshold_blocks_the_medium_one(self):
        out = self.parse(hermes_security(self.FINDINGS), sarif.parse_threshold("warning"))
        self.assertEqual(len(out.blockers), 3)

    def test_collect_reads_it_like_parse_file(self):
        path = self.sarif_file(hermes_security(self.FINDINGS))
        out = sarif.collect([path], self.root)
        self.assertEqual(len(out.blockers), 2)


class Paths(unittest.TestCase):
    """Pure string logic: the same results on every platform, for both styles of root."""

    def path(self, uri, root, base_id=None, run=None):
        return sarif.repo_path(uri, base_id, run or {}, root)

    def test_relative(self):
        self.assertEqual(self.path("src/a.py", "/home/u/repo"), "src/a.py")
        self.assertEqual(self.path("./src/../src/a.py", "/home/u/repo"), "src/a.py")
        self.assertEqual(self.path("src\\win\\a.py", "C:\\Users\\u\\repo"), "src/win/a.py")
        self.assertEqual(self.path("my%20dir/a%2Bb.py", "/r"), "my dir/a+b.py")

    def test_file_uris_on_posix(self):
        self.assertEqual(self.path("file:///home/u/repo/src/a.py", "/home/u/repo"), "src/a.py")
        self.assertEqual(self.path("file://localhost/home/u/repo/src/a.py", "/home/u/repo"), "src/a.py")
        self.assertEqual(self.path("/home/u/repo/src/a.py", "/home/u/repo"), "src/a.py")
        self.assertEqual(self.path("/elsewhere/a.py", "/home/u/repo"), "/elsewhere/a.py")  # outside: kept as is
        self.assertEqual(self.path("/home/u/repo-two/a.py", "/home/u/repo"), "/home/u/repo-two/a.py")

    def test_file_uris_on_windows(self):
        root = "C:\\Users\\u\\repo"
        self.assertEqual(self.path("file:///C:/Users/u/repo/src/a.py", root), "src/a.py")
        self.assertEqual(self.path("file:///c:/users/U/repo/src/a.py", root), "src/a.py")  # drive and case
        self.assertEqual(self.path("C:\\Users\\u\\repo\\src\\a.py", root), "src/a.py")
        self.assertEqual(self.path("file:///C:/Users/u/repo/my%20dir/a.py", root), "my dir/a.py")
        self.assertEqual(self.path("file:///D:/other/a.py", root), "D:/other/a.py")

    def test_uri_base_id(self):
        run = {"originalUriBaseIds": {"SRCROOT": {"uri": "file:///home/u/repo/"},
                                      "SUB": {"uri": "file:///home/u/repo/services/api/"},
                                      "CI": {"uri": "file:///runner/work/x/x/"}}}
        self.assertEqual(self.path("a.py", "/home/u/repo", "SRCROOT", run), "a.py")
        self.assertEqual(self.path("a.py", "/home/u/repo", "SUB", run), "services/api/a.py")
        self.assertEqual(self.path("a.py", "/home/u/repo", "CI", run), "a.py")  # another machine's root
        self.assertEqual(self.path("a.py", "/home/u/repo", "%SRCROOT%", run), "a.py")  # undefined id
        win = {"originalUriBaseIds": {"SRCROOT": {"uri": "file:///C:/Users/u/repo/"}}}
        self.assertEqual(self.path("src/a.py", "C:\\Users\\u\\repo", "SRCROOT", win), "src/a.py")
        self.assertEqual(self.path("a.py", "C:\\Users\\u\\repo", "SRCROOT", {"originalUriBaseIds": "junk"}), "a.py")

    def test_nothing_raises_on_odd_input(self):
        for uri in ("", "file:", "file://", "file:///", "////", "%", ".", ".."):
            self.assertIsInstance(self.path(uri, "/r"), str)


class Unreadable(SarifCase):
    def test_collect_turns_every_problem_into_one_note(self):
        missing = os.path.join(self.root, "nope.sarif")
        bad_json = self.sarif_file(None, "bad.sarif", raw="{not json")
        wrong_version = self.sarif_file({"version": "2.0.0", "runs": []}, "v.sarif")
        not_object = self.sarif_file(None, "list.sarif", raw="[1, 2]")
        no_runs = self.sarif_file({"version": "2.1.0"}, "noruns.sarif")
        binary = os.path.join(self.root, "bin.sarif")
        with open(binary, "wb") as fh:
            fh.write(b"\xff\xfe\x00\x01")
        folder = os.path.join(self.root, "dir.sarif")
        os.makedirs(folder)
        out = sarif.collect([missing, bad_json, wrong_version, not_object, no_runs, binary, folder], self.root)
        self.assertEqual(out.blockers, [])
        self.assertEqual(len(out.notes), 7)
        for note in out.notes:
            self.assertEqual(note.severity, "note")
            self.assertIn("could not read SARIF:", note.message)
            self.assertFalse(note.allowed)

    def test_huge_file(self):
        path = self.sarif_file(doc([result(level="error")]))
        with mock.patch.object(sarif, "MAX_BYTES", 10):
            out = sarif.collect([path], self.root)
            with self.assertRaises(sarif.SarifError):
                sarif.parse_file(path, self.root)
        self.assertEqual(out.blockers, [])
        self.assertIn("limit", out.notes[0].message)

    def test_unexpected_shapes_never_raise(self):
        shapes = [{"runs": [None, 5, "x", [], {"tool": 3, "results": "no"}]},
                  {"runs": [{"tool": {"driver": {"name": 7, "rules": {"a": 1}}}, "results": [None, 1, {}, {"message": 4}]}]},
                  {"runs": [{"results": [{"ruleId": 1, "level": ["error"], "ruleIndex": "0", "locations": [None, 3],
                                          "message": {"text": {"x": 1}}, "suppressions": "yes", "properties": []}]}]},
                  {"runs": [{"results": [{"locations": [{"physicalLocation": {"artifactLocation": {"uri": 5},
                                                                               "region": {"startLine": "9"}}}],
                                          "level": "error"}]}]}]
        for shape in shapes:
            shape["version"] = "2.1.0"
            out = sarif.collect([self.sarif_file(shape)], self.root)
            self.assertIsInstance(out.blockers, list)  # whatever it found, it returned
        deep = "[" * 100000 + "]" * 100000
        out = sarif.collect([self.sarif_file(None, "deep.sarif", raw=deep)], self.root)
        self.assertEqual(out.blockers, [])
        self.assertEqual(len(out.notes), 1)

    def test_a_bom_is_fine(self):
        path = self.sarif_file(None, "bom.sarif", raw="\ufeff" + json.dumps(doc([result(level="error")])))
        self.assertEqual(len(sarif.collect([path], self.root).blockers), 1)

    def test_many_notes_are_counted_not_flooded(self):
        out = self.parse_many(60)
        self.assertEqual(out.blockers, [])
        self.assertEqual(len(out.notes), sarif.MAX_NOTES + 1)
        self.assertIn("35 more", out.notes[-1].message)

    def parse_many(self, n):
        return sarif.parse_file(self.sarif_file(doc([result("R%d" % i, level="note") for i in range(n)])), self.root)


class Sources(SarifCase):
    """Where the reports come from: the base's .foreman.json, and the command line."""

    def base_with_config(self, **config):
        self.write("app.py", "x = 1\n")
        self.write(detector.CONFIG_FILE, json.dumps(config))
        self.commit("base")
        return self.git("rev-parse", "HEAD").strip()

    def blocking_report(self, name="report.sarif", level="error"):
        return self.sarif_file(doc([result("SQLI", "SQL injection", "app.py", 1, level=level)]), name)

    def test_config_report_gates_every_entry_point(self):
        base = self.base_with_config(sarif=["report.sarif"])
        self.blocking_report()
        self.git("checkout", "-q", "-b", "feature")
        self.write("app.py", "x = 2\n")
        self.commit("change")
        repo = detector.Repo(self.root)
        for report in (detector.scan_range(repo, base), detector.scan_branch(repo)):
            self.assertEqual([f.rule for f in report.blockers], ["sarif:scanner/SQLI"])
            self.assertEqual(report.verdict, "BLOCKED")
        self.write("app.py", "x = 3\n")  # an uncommitted change: the worktree scan reads it too
        worktree = detector.scan_worktree(repo)
        self.assertEqual([f.rule for f in worktree.blockers], ["sarif:scanner/SQLI"])
        self.assertEqual(worktree.blockers[0].location, "app.py:1")

    def test_below_the_threshold_is_a_note(self):
        base = self.base_with_config(sarif=["report.sarif"])
        self.blocking_report(level="warning")
        self.write("app.py", "x = 2\n")
        self.commit("change")
        report = detector.scan_range(detector.Repo(self.root), base)
        self.assertEqual(report.blockers, [])
        self.assertEqual(report.verdict, "CLEAN")
        self.assertEqual([f.rule for f in report.notes], ["sarif:scanner/SQLI"])
        self.assertEqual(report.to_dict()["notes"][0]["rule"], "sarif:scanner/SQLI")

    def test_config_threshold(self):
        base = self.base_with_config(sarif="report.sarif", sarif_threshold="warning")  # a single string works too
        self.blocking_report(level="warning")
        self.write("app.py", "x = 2\n")
        self.commit("change")
        self.assertEqual(len(detector.scan_range(detector.Repo(self.root), base).blockers), 1)

    def test_bad_config_threshold_is_a_note_and_the_default_applies(self):
        base = self.base_with_config(sarif=["report.sarif"], sarif_threshold="fatal")
        self.blocking_report()
        self.write("app.py", "x = 2\n")
        self.commit("change")
        report = detector.scan_range(detector.Repo(self.root), base)
        self.assertEqual(len(report.blockers), 1)
        self.assertTrue(any("sarif_threshold" in n.message for n in report.notes))

    def test_a_missing_or_broken_configured_report_is_an_error_not_a_clean_pass(self):
        base = self.base_with_config(sarif=["gone.sarif", "broken.sarif", "../escape.sarif", "/abs/x.sarif", "C:\\x.sarif", 7])
        self.sarif_file(None, "broken.sarif", raw="{")
        self.write("app.py", "x = 2\n")
        self.commit("change")
        report = detector.scan_range(detector.Repo(self.root), base)
        self.assertEqual(report.blockers, [])
        self.assertEqual(len(report.errors), 5)
        self.assertTrue(all("could not read the SARIF report" in e and detector.CONFIG_FILE in e for e in report.errors))
        self.assertEqual(report.to_dict()["errors"], report.errors)

    def test_config_is_read_at_the_base_so_a_change_cannot_point_it_elsewhere(self):
        base = self.base_with_config(sarif=["report.sarif"])
        self.blocking_report()
        self.git("checkout", "-q", "-b", "feature")
        self.write(detector.CONFIG_FILE, json.dumps({"sarif": ["clean.sarif"], "sarif_threshold": 10}))
        self.sarif_file(doc([]), "clean.sarif")
        self.write("app.py", "x = 9\n")  # the base's report points at app.py: a change to it is gated
        self.commit("point the gate at an empty report")
        report = detector.scan_range(detector.Repo(self.root), base)
        rules = sorted(f.rule for f in report.blockers)
        self.assertEqual(rules, ["check-changed", "sarif:scanner/SQLI"])  # still gated by the base's report
        changed = [f for f in report.blockers if f.rule == "check-changed"][0]
        self.assertEqual(changed.file, detector.CONFIG_FILE)

    def test_deleting_the_keys_is_a_change_too(self):
        base = self.base_with_config(sarif=["report.sarif"])
        self.blocking_report()
        self.write(detector.CONFIG_FILE, "{}")
        self.write("app.py", "x = 9\n")
        self.commit("drop the sarif key")
        report = detector.scan_range(detector.Repo(self.root), base)
        self.assertEqual(sorted(f.rule for f in report.blockers), ["check-changed", "sarif:scanner/SQLI"])

    def test_a_config_added_by_the_change_is_ignored(self):
        self.write("app.py", "x = 1\n")
        self.commit("base without configuration")
        base = self.git("rev-parse", "HEAD").strip()
        self.write(detector.CONFIG_FILE, json.dumps({"sarif": ["report.sarif"]}))
        self.blocking_report()
        self.commit("add configuration")
        report = detector.scan_range(detector.Repo(self.root), base)
        self.assertEqual(report.blockers, [])
        self.assertEqual(report.notes, [])

    def test_editing_a_tracked_report_the_base_points_to_is_a_blocker(self):
        self.write("report.sarif", json.dumps(doc([result("SQLI", level="error")])))
        base = self.base_with_config(sarif=["report.sarif"])
        self.write("report.sarif", json.dumps(doc([result("SQLI", level="error", suppressions=[{"kind": "external"}])])))
        self.commit("suppress it")
        report = detector.scan_range(detector.Repo(self.root), base)
        self.assertEqual([f.rule for f in report.blockers], ["check-changed"])
        self.assertEqual(report.blockers[0].file, "report.sarif")
        self.assertIn("SARIF report", report.blockers[0].message)

    def test_staleness_is_a_note_that_does_not_block(self):
        base = self.base_with_config(sarif=["report.sarif"])
        path = self.blocking_report(level="note")
        old = time.time() - 3600
        os.utime(path, (old, old))
        self.write("app.py", "x = 2\n")
        self.commit("change")
        report = detector.scan_range(detector.Repo(self.root), base)
        self.assertEqual(report.verdict, "CLEAN")
        self.assertIn(sarif.STALE, [n.message for n in report.notes])
        fresh = time.time() + 3600
        os.utime(path, (fresh, fresh))
        report = detector.scan_range(detector.Repo(self.root), base)
        self.assertNotIn(sarif.STALE, [n.message for n in report.notes])

    def test_staleness_in_the_worktree_counts_edited_files_but_not_the_report(self):
        self.base_with_config(sarif=["report.sarif"])
        path = self.blocking_report(level="note")
        old = time.time() - 3600
        os.utime(path, (old, old))
        repo = detector.Repo(self.root)
        self.assertIn(sarif.STALE, [n.message for n in detector.scan_worktree(repo).notes])  # older than the commit
        os.utime(path, None)
        self.assertNotIn(sarif.STALE, [n.message for n in detector.scan_worktree(repo).notes])
        edited = self.write("app.py", "x = 2\n")
        later = time.time() + 3600
        os.utime(edited, (later, later))
        self.assertIn(sarif.STALE, [n.message for n in detector.scan_worktree(repo).notes])


class CommandLine(SarifCase):
    def setUp(self):
        super().setUp()
        self.write("app.py", "x = 1\n")
        self.commit("base")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.write("app.py", "x = 2\n")
        self.commit("change")

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = detector.main([self.base, "--repo", self.root, *args])
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_a_blocking_report_fails_the_run(self):
        path = self.sarif_file(doc([result("SQLI", "SQL injection", "app.py", 1, level="error")]))
        code, out, _ = self.run_cli("--sarif", path)
        self.assertEqual(code, 1)
        self.assertIn("sarif:scanner/SQLI", out)
        code, out, _ = self.run_cli("--sarif", path, "--json")
        self.assertEqual(json.loads(out)["blockers"][0]["rule"], "sarif:scanner/SQLI")

    def test_below_the_threshold_exits_zero_and_lists_the_note(self):
        path = self.sarif_file(doc([result("MINOR", uri="app.py", level="warning")]))
        code, out, _ = self.run_cli("--sarif", path)
        self.assertEqual(code, 0)
        self.assertIn("Notes (they do not block)", out)
        self.assertIn("sarif:scanner/MINOR", out)
        code, _, _ = self.run_cli("--sarif", path, "--sarif-threshold", "warning")
        self.assertEqual(code, 1)
        code, _, _ = self.run_cli("--sarif", path, "--sarif-threshold", "5")
        self.assertEqual(code, 1)

    def test_several_reports_and_a_clean_one(self):
        a = self.sarif_file(doc([]), "a.sarif")
        b = self.sarif_file(doc([result("X", uri="app.py", level="error")]), "b.sarif")
        self.assertEqual(self.run_cli("--sarif", a)[0], 0)
        self.assertEqual(self.run_cli("--sarif", a, "--sarif", b)[0], 1)

    def test_an_unreadable_report_asked_for_on_the_command_line_is_exit_2(self):
        broken = self.sarif_file(None, "broken.sarif", raw="{")
        wrong = self.sarif_file({"version": "1.0", "runs": []}, "old.sarif")
        for path in (os.path.join(self.root, "missing.sarif"), broken, wrong):
            code, out, err = self.run_cli("--sarif", path)
            self.assertEqual(code, 2)
            self.assertIn("could not read the SARIF report", err)
            self.assertNotIn("CLEAN", out)  # nothing was reported as passing

    def test_bad_threshold_is_a_usage_error(self):
        path = self.sarif_file(doc([]))
        for bad in ("fatal", "12"):
            code, _, err = self.run_cli("--sarif", path, "--sarif-threshold", bad)
            self.assertEqual(code, 2)
            self.assertIn("threshold", err)

    def test_the_cli_threshold_overrides_the_config_and_reads_config_reports_too(self):
        # base carries the configuration; the change leaves it alone
        self.git("checkout", "-q", "-b", "other", self.base)
        self.write(detector.CONFIG_FILE, json.dumps({"sarif": ["report.sarif"], "sarif_threshold": 10}))
        self.sarif_file(doc([result("W", uri="app.py", level="warning")]))
        self.commit("config")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.write("app.py", "x = 5\n")
        self.commit("change")
        self.assertEqual(self.run_cli()[0], 0)  # config threshold 10: nothing blocks
        self.assertEqual(self.run_cli("--sarif-threshold", "warning")[0], 1)  # the command line wins

    def test_a_report_that_names_a_missing_file_still_gates(self):
        path = self.sarif_file(doc([result("X", uri="file:///no/such/place.py", level="error")]))
        self.assertEqual(self.run_cli("--sarif", path)[0], 0)  # not in a file the change touches: a note
        self.assertEqual(self.run_cli("--sarif", path, "--sarif-scope", "all")[0], 1)


if __name__ == "__main__":
    unittest.main()
