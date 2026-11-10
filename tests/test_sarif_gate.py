"""SARIF in the gate: scope, unreadable reports, protection of the report from the agent, CI flags, compact notes."""
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


def doc(results, tool="scanner"):
    return {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": tool}}, "results": results}]}


def result(rule="R1", uri="app.py", line=1, **extra):
    r = {"ruleId": rule, "message": {"text": "problem in " + uri},
         "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri}, "region": {"startLine": line}}}]}
    r.update(extra)
    return r


def terminal(command, workdir):
    return gate.on_pre_tool_call(tool_name="terminal", args={"command": command, "workdir": workdir}, task_id="t1")


class Base(GitRepoCase):
    def setup_repo(self, **config):
        self.write("app.py", "x = 1\n")
        self.write("other.py", "y = 1\n")
        self.write(detector.CONFIG_FILE, json.dumps(config))
        self.commit("base")
        return self.git("rev-parse", "HEAD").strip()

    def report(self, results, name="results.sarif"):
        path = self.write(name, json.dumps(doc(results)))
        os.utime(path, (4_000_000_000, 4_000_000_000))  # never stale: no test here reads the clock
        return path

    def scan(self, base):
        return detector.scan_range(detector.Repo(self.root), base)


class Scope(Base):
    def test_only_results_in_changed_files_or_new_ones_block(self):
        base = self.setup_repo(sarif=["results.sarif"])
        self.report([result("OLD", "other.py", level="error"),
                     result("OLD2", "other.py", level="error", baselineState="unchanged"),
                     result("NEW", "other.py", level="error", baselineState="new"),
                     result("UPD", "other.py", level="error", baselineState="updated"),
                     result("MINE", "app.py", level="error"),
                     {"ruleId": "NOLOC", "level": "error", "message": {"text": "no location"}}])
        self.write("app.py", "x = 2\n")
        self.commit("change app")
        report = self.scan(base)
        self.assertEqual(sorted(f.rule.split("/")[-1] for f in report.blockers), ["MINE", "NEW", "NOLOC", "UPD"])  # no location: cannot be scoped to a file
        self.assertEqual(sorted(f.rule.split("/")[-1] for f in report.notes if f.rule.startswith("sarif:scanner")),
                         ["OLD", "OLD2"])
        self.assertTrue(all("outside the change" in f.message for f in report.notes if "OLD" in f.rule))

    def test_the_scope_all_in_the_base_config_lets_old_debt_block(self):
        base = self.setup_repo(sarif=["results.sarif"], sarif_scope="all")
        self.report([result("OLD", "other.py", level="error")])
        self.write("app.py", "x = 2\n")
        self.commit("change")
        self.assertEqual(len(self.scan(base).blockers), 1)

    def test_a_bad_scope_falls_back_to_changed(self):
        base = self.setup_repo(sarif=["results.sarif"], sarif_scope="everything")
        self.report([result("OLD", "other.py", level="error")])
        self.write("app.py", "x = 2\n")
        self.commit("change")
        self.assertEqual(self.scan(base).blockers, [])

    def test_the_worktree_scope_is_what_is_uncommitted(self):
        self.setup_repo(sarif=["results.sarif"])
        self.report([result("A", "app.py", level="error"), result("B", "other.py", level="error")])
        self.write("app.py", "x = 3\n")
        report = detector.scan_worktree(detector.Repo(self.root))
        self.assertEqual([f.rule.split("/")[-1] for f in report.blockers], ["A"])

    def test_cli_flag(self):
        base = self.setup_repo()
        path = self.report([result("OLD", "other.py", level="error")])
        self.write("app.py", "x = 2\n")
        self.commit("change")
        self.assertEqual(run_cli(self.root, base, "--sarif", path)[0], 0)
        self.assertEqual(run_cli(self.root, base, "--sarif", path, "--sarif-scope", "all")[0], 1)
        self.assertEqual(run_cli(self.root, base, "--sarif", path, "--sarif-scope", "nope")[0], 2)

    def test_results_that_are_not_failures_are_ignored(self):
        path = self.report([result("P", level="error", kind="pass"), result("I", level="error", kind="informational"),
                            result("F", level="error", kind="fail"), result("D", level="error")])
        out = sarif.parse_file(path, self.root)
        self.assertEqual(sorted(f.rule[-1] for f in out.blockers), ["D", "F"])

    def test_the_deadline_is_checked_while_parsing(self):
        many = [result("R%d" % i, level="note") for i in range(sarif._DEADLINE_EVERY + 1)]
        path = self.report(many)
        past = time.monotonic() - 1
        with self.assertRaises(detector.GitTimeout) as caught:
            sarif.parse_file(path, self.root, deadline=past)
        self.assertIn("reading the SARIF report", str(caught.exception))
        self.assertNotIn("the diff", str(caught.exception))
        with self.assertRaises(detector.GitTimeout):  # collect never swallows the hook's time budget
            sarif.collect([path], self.root, deadline=past)
        self.assertEqual(sarif.parse_file(path, self.root, deadline=time.monotonic() + 600).blockers, [])
        few = self.report([result(level="note")], "few.sarif")
        self.assertEqual(sarif.parse_file(few, self.root, deadline=past).blockers, [])  # under the interval


class UnreadableIsNotClean(Base):
    def test_status_and_check_do_not_say_clean(self):
        self.setup_repo(sarif="results.sarif")  # the generated report is absent
        v = commands.verdict(self.root)
        self.assertEqual(v["verdict"], "NEEDS_APPROVAL")
        self.assertIn("could not read the SARIF report", v["errors"][0])
        text = commands.format_verdict(v)
        self.assertIn("Foreman: NEEDS_APPROVAL", text)
        self.assertIn("results.sarif", text)
        self.assertNotIn("No skipped, deleted", text)
        self.assertEqual(json.loads(commands.foreman_check_tool({"path": self.root}))["verdict"], "NEEDS_APPROVAL")

    def test_the_hook_asks_instead_of_passing(self):
        self.setup_repo(sarif="results.sarif")
        self.write("app.py", "x = 2\n")
        self.git("add", "-A")
        d = terminal("git commit -m x", self.root)
        self.assertEqual(d["action"], "approve")
        self.assertIn("could not inspect", d["message"].lower())
        self.assertIn("could not read the SARIF report", d["message"])
        self.assertIn("named in .foreman.json", d["message"])

    def test_ci_exits_2(self):
        base = self.setup_repo(sarif="results.sarif")
        self.write("app.py", "x = 2\n")
        self.commit("change")
        code, out, err = run_cli(self.root, base)
        self.assertEqual(code, 2)
        self.assertIn("could not read the SARIF report", err)
        self.assertNotIn("CLEAN", out)
        self.write("results.sarif", "{")  # unreadable is the same as missing
        self.assertEqual(run_cli(self.root, base)[0], 2)

    def test_an_empty_report_is_a_valid_clean_scan(self):
        base = self.setup_repo(sarif="results.sarif")
        self.write("results.sarif", json.dumps({"version": "2.1.0", "runs": []}))
        self.write("app.py", "x = 2\n")
        self.commit("change")
        self.assertEqual(run_cli(self.root, base)[0], 0)
        self.assertEqual(commands.verdict(self.root)["verdict"], "CLEAN")


class ReportIsProtected(Base):
    def test_the_write_gate_blocks_the_reports_the_base_names(self):
        self.setup_repo(sarif=["reports/results.sarif", "other.sarif"])
        target = os.path.join(self.root, "reports", "results.sarif")
        empty = json.dumps({"version": "2.1.0", "runs": []})
        d = gate.on_pre_tool_call(tool_name="write_file", args={"path": target, "content": empty})
        self.assertEqual(d["action"], "block")
        self.assertIn("SARIF report", d["message"])
        patch = {"path": os.path.join(self.root, "other.sarif"), "old_string": "a", "new_string": "b"}
        self.assertEqual(gate.on_pre_tool_call(tool_name="patch", args=patch)["action"], "block")
        v4a = "*** Begin Patch\n*** Update File: %s\n@@\n-a\n+b\n*** End Patch\n" % os.path.join(self.root, "reports", "results.sarif")
        d = gate.on_pre_tool_call(tool_name="patch", args={"mode": "patch", "patch": v4a})
        self.assertEqual(d["action"], "block")
        dotted = os.path.join(self.root, "reports", "..", "reports", "results.sarif")  # however the path is spelt
        self.assertEqual(gate.on_pre_tool_call(tool_name="write_file", args={"path": dotted, "content": "x"})["action"], "block")

    def test_other_writes_pass_and_so_does_a_repository_without_the_key(self):
        self.setup_repo(sarif=["results.sarif"])
        free = os.path.join(self.root, "src", "new.py")
        self.assertIsNone(gate.on_pre_tool_call(tool_name="write_file", args={"path": free, "content": "x = 1\n"}))
        sibling = os.path.join(self.root, "results.sarif.md")
        self.assertIsNone(gate.on_pre_tool_call(tool_name="write_file", args={"path": sibling, "content": "x"}))

    def test_no_configuration_no_guard(self):
        self.write("app.py", "x = 1\n")
        self.commit("base")
        path = os.path.join(self.root, "results.sarif")
        self.assertIsNone(gate.on_pre_tool_call(tool_name="write_file", args={"path": path, "content": "{}"}))

    def test_the_guard_reads_the_base_not_the_working_tree(self):
        self.setup_repo(sarif=["results.sarif"])
        self.write(detector.CONFIG_FILE, "{}")  # the agent drops the key in the working tree...
        path = os.path.join(self.root, "results.sarif")
        d = gate.on_pre_tool_call(tool_name="write_file", args={"path": path, "content": "{}"})
        self.assertEqual(d["action"], "block")  # ...and the report stays protected by the committed config

    def test_a_redirect_into_a_report_before_a_gated_command_is_an_unsafe_segment(self):
        self.setup_repo(sarif=["results.sarif"])
        for command in ("echo '{}' > results.sarif && git commit -m x",
                        "printf x > results.sarif; git commit -m x",
                        "python gen.py --output results.sarif && git push"):
            d = terminal(command, self.root)
            self.assertEqual(d["action"], "block", command)
            self.assertIn("own command", d["message"])


class Annotations(Base):
    def marked_range(self):
        base = self.setup_repo()
        self.write("tests/test_a.py", SKIP + "  # " + detector.MARKER + " needs a GPU\ndef test_a():\n    pass\n")
        self.commit("marked")
        return base

    def test_marked_findings_are_annotated_in_github_actions(self):
        base = self.marked_range()
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            code, out, _ = run_cli(self.root, base)
        self.assertEqual(code, 0)
        line = next(l for l in out.splitlines() if l.startswith("::warning "))
        self.assertIn("file=tests/test_a.py,line=1,", line)
        self.assertIn("title=foreman%3A test-skipped", line)
        self.assertIn("marked foreman:allow", line)
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": ""}):
            self.assertNotIn("::warning", run_cli(self.root, base)[1])

    def test_annotation_escaping(self):
        f = detector.Finding("r", "a,b:c.py", 3, "50%\nsecond", "fix")
        text = detector.annotation("warning", f)
        self.assertTrue(text.startswith("::warning file=a%2Cb%3Ac.py,line=3,"))
        self.assertNotIn("\n", text)
        self.assertIn("50%25%0Asecond", text)

    def test_strict_makes_marked_findings_blockers(self):
        base = self.marked_range()
        self.assertEqual(run_cli(self.root, base)[0], 0)
        code, out, _ = run_cli(self.root, base, "--strict")
        self.assertEqual(code, 1)
        self.assertIn("BLOCKED (1 blocker(s), 0 marked", out)
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            self.assertIn("::error ", run_cli(self.root, base, "--strict")[1])
        data = json.loads(run_cli(self.root, base, "--strict", "--json")[1])
        self.assertTrue(data["strict"])


class CompactNotes(Base):
    def three_notes(self):
        return [result("N%d" % i, "app.py", i + 1, level="warning") for i in range(3)]

    def test_status_shows_one_line_with_the_first_two(self):
        self.setup_repo(sarif=["results.sarif"])
        self.write("app.py", "x = 2\n")
        self.report(self.three_notes())  # written last: not stale
        text = commands.format_verdict(commands.verdict(self.root))
        lines = [l for l in text.splitlines() if l.startswith("SARIF:")]
        self.assertEqual(len(lines), 1)
        self.assertIn("3 note(s), not blocking", lines[0])
        self.assertIn("(+1 more)", lines[0])
        self.assertEqual(text.count("problem in app.py"), 2)

    def test_the_hook_message_has_the_line_too(self):
        self.setup_repo(sarif=["results.sarif"])
        self.write("tests/test_a.py", SKIP + "\ndef test_a():\n    pass\n")
        self.git("add", "-A")
        self.report(self.three_notes())  # written last and untracked: not stale, not part of the commit
        d = terminal("git commit -m x", self.root)
        self.assertEqual(d["action"], "block")
        self.assertIn("SARIF: 3 note(s), not blocking", d["message"])
        self.assertEqual(detector.compact_notes([]), "")


def run_cli(root, base, *args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = detector.main([base, "--repo", root, *args])
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


if __name__ == "__main__":
    unittest.main()
