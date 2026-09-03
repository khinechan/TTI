#!/usr/bin/env python3
"""Test suite for gate_run.py — the tests get tested. T1-T28 per the
hardened spec. Fixtures are tiny generated scripts in a temp dir —
never the real fleet, never the real vault, never a credentialed tool
(amendment A7)."""

import ast
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import gate_run as gr

PASS, FAIL = gr.EXIT_PASS, gr.EXIT_FAIL
BAD, INTERNAL, PARTIAL = (gr.EXIT_BAD_INVOCATION, gr.EXIT_INTERNAL,
                          gr.EXIT_PARTIAL)


def sha(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def snapshot(root):
    files = {}
    for path in Path(root).rglob("*"):
        if path.is_file():
            files[str(path.relative_to(root))] = sha(path)
    return files


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="gate_run_test_"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def tool(self, name, body):
        path = self.dir / name
        path.write_text("import sys\n" + body + "\n", encoding="utf-8")
        return path

    def entry(self, name, filename, args=None, timeout=10, depends=None,
              **extra):
        e = {"name": name, "path": filename, "args": args or [],
             "timeout_s": timeout, "depends_on": depends or []}
        e.update(extra)
        return e

    def ok_fleet(self, n=3):
        fleet = []
        for i in range(n):
            self.tool("ok%d.py" % i, "sys.exit(0)")
            fleet.append(self.entry("ok%d" % i, "ok%d.py" % i))
        return fleet

    def run_gate(self, **kwargs):
        kwargs.setdefault("base_dir", self.dir)
        return gr.run_gate(**kwargs)

    def receipts(self):
        path = self.dir / gr.RECEIPTS_NAME
        if not path.is_file():
            return []
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def run_cli(self, argv, fleet, environ=None):
        """CLI-level run against a fixture fleet in the temp dir."""
        old_fleet, old_base = gr.FLEET, gr.BASE_DIR
        gr.FLEET, gr.BASE_DIR = fleet, self.dir
        out, err = io.StringIO(), io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    code = gr.main(argv)
                except SystemExit as exc:
                    code = exc.code if isinstance(exc.code, int) else BAD
        finally:
            gr.FLEET, gr.BASE_DIR = old_fleet, old_base
        return code, out.getvalue(), err.getvalue()


class TestGateRun(Fixture):

    def test_T01_all_pass(self):
        report = self.run_gate(fleet=self.ok_fleet())
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report["exit_code"], PASS)
        self.assertEqual(len(self.receipts()), 1)

    def test_T02_receipt_on_pass_exists(self):
        """W11's whole point: a night with no receipt means the runner
        did not run — it never means nothing was wrong."""
        self.run_gate(fleet=self.ok_fleet())
        receipts = self.receipts()
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["verdict"], "PASS")
        self.assertTrue((self.dir / gr.RECEIPTS_NAME).is_file())

    def test_T03_one_failure_others_still_ran(self):
        fleet = self.ok_fleet(2)
        self.tool("bad.py", "sys.exit(1)")
        fleet.insert(1, self.entry("bad", "bad.py"))
        report = self.run_gate(fleet=fleet)
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(report["exit_code"], FAIL)
        statuses = {s["name"]: s["status"] for s in report["stages"]}
        self.assertEqual(statuses,
                         {"ok0": "PASS", "bad": "FAIL", "ok1": "PASS"})

    def test_T04_hung_stage(self):
        """W5: on timeout there is NO returncode to read — synthesize
        HUNG with returncode null, and the RUN CONTINUES."""
        fleet = [self.entry("sleepy", "sleepy.py", timeout=1),
                 self.entry("after", "after.py")]
        self.tool("sleepy.py", "import time\ntime.sleep(30)")
        self.tool("after.py", "sys.exit(0)")
        start = time.monotonic()
        report = self.run_gate(fleet=fleet)
        elapsed = time.monotonic() - start
        sleepy = report["stages"][0]
        self.assertEqual(sleepy["status"], "HUNG")
        self.assertIsNone(sleepy["returncode"])
        self.assertEqual(report["stages"][1]["status"], "PASS")
        self.assertEqual(report["verdict"], "FAIL")
        self.assertLess(elapsed, 10, "cleanup blocked the fleet")

    def test_T05_cant_start_preflight_reports_all_missing_at_once(self):
        fleet = self.ok_fleet(1)
        fleet.append(self.entry("ghost1", "ghost1.py"))
        fleet.append(self.entry("ghost2", "ghost2.py"))
        report = self.run_gate(fleet=fleet)
        self.assertEqual(report["verdict"], "FAIL")
        by = {s["name"]: s for s in report["stages"]}
        self.assertEqual(by["ghost1"]["status"], "CANT_START")
        self.assertEqual(by["ghost2"]["status"], "CANT_START")
        self.assertIsNone(by["ghost1"]["returncode"])
        self.assertIn("not found", by["ghost1"]["stderr_text"])
        self.assertEqual(by["ok0"]["status"], "PASS")   # still ran

    def test_T05b_missing_env_is_cant_start_with_clear_reason(self):
        """Amendment A5: sku_check requires PRINTIFY_TOKEN."""
        fleet = self.ok_fleet(1)
        self.tool("sku.py", "sys.exit(0)")
        fleet.append(self.entry("sku", "sku.py",
                                requires_env=["PRINTIFY_TOKEN"]))
        report = self.run_gate(fleet=fleet, environ={})
        by = {s["name"]: s for s in report["stages"]}
        self.assertEqual(by["sku"]["status"], "CANT_START")
        self.assertIn("PRINTIFY_TOKEN", by["sku"]["stderr_text"])
        report = self.run_gate(fleet=fleet,
                               environ={"PRINTIFY_TOKEN": "x"})
        by = {s["name"]: s for s in report["stages"]}
        self.assertEqual(by["sku"]["status"], "PASS")

    def test_T29_missing_state_md_config_is_cant_start(self):
        """Fable cleanup 2026-09-02: a {STATE_MD} stage with no
        GATE_RUN_STATE_MD set and no default STATE.md on disk is
        CANT_START, named — never a FAIL that masquerades as the
        linter's own verdict (exit precedence per R5 unchanged)."""
        fleet = self.ok_fleet(1)
        self.tool("lint.py", "sys.exit(0)")
        fleet.append(self.entry("lint", "lint.py",
                                args=[gr.STATE_MD_PLACEHOLDER]))
        report = self.run_gate(fleet=fleet, environ={})
        by = {s["name"]: s for s in report["stages"]}
        self.assertEqual(by["lint"]["status"], "CANT_START")
        self.assertIn(gr.STATE_MD_ENV, by["lint"]["stderr_text"])
        self.assertEqual(report["exit_code"], gr.EXIT_FAIL)
        # env pointing at a missing file: still CANT_START, named
        report = self.run_gate(
            fleet=fleet,
            environ={gr.STATE_MD_ENV: str(self.dir / "ghost.md")})
        by = {s["name"]: s for s in report["stages"]}
        self.assertEqual(by["lint"]["status"], "CANT_START")
        self.assertIn("missing file", by["lint"]["stderr_text"])
        # a real file: the stage runs
        state = self.dir / "STATE.md"
        state.write_text("| D-1 |\n", encoding="utf-8")
        report = self.run_gate(fleet=fleet,
                               environ={gr.STATE_MD_ENV: str(state)})
        by = {s["name"]: s for s in report["stages"]}
        self.assertEqual(by["lint"]["status"], "PASS")

    def test_T06_empty_fleet_exit_2(self):
        with self.assertRaises(gr.InvocationError):
            self.run_gate(fleet=[])
        code, _, err = self.run_cli([], [])
        self.assertEqual(code, BAD)
        self.assertIn("empty", err)

    def test_T07_exit_code_fidelity(self):
        """Regression lock on the pipe bug: a tool exiting 7, piped to
        head, returns 0 — the failure INVERTS. The receipt must carry
        the real 7."""
        fleet = [self.entry("seven", "seven.py")]
        self.tool("seven.py", "sys.exit(7)")
        report = self.run_gate(fleet=fleet)
        self.assertEqual(report["stages"][0]["returncode"], 7)
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(self.receipts()[0]["stages"][0]["returncode"], 7)

    def test_T08_no_piping_source_scan(self):
        with open(gr.__file__, encoding="utf-8") as handle:
            source = handle.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and \
                        isinstance(func.value, ast.Name) and \
                        func.value.id == "os":
                    self.assertNotIn(func.attr, ("system", "popen"))
                for kw in node.keywords:
                    self.assertNotEqual(kw.arg, "shell",
                                        "shell= kwarg found")
        self.assertNotIn("shell=True", source)
        self.assertNotIn("| head", source)
        self.assertNotIn("2>&1", source)
        # every subprocess call's command is a list literal
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and \
                    isinstance(node.func, ast.Attribute) and \
                    isinstance(node.func.value, ast.Name) and \
                    node.func.value.id == "subprocess" and \
                    node.func.attr in ("Popen", "run", "call"):
                self.assertNotIsInstance(node.args[0], ast.Constant,
                                         "string command found")

    def test_T09_arbitrary_return_code(self):
        """W7: only == 0 is pass — never a range check. POSIX itself
        masks exit codes to 8 bits, so sys.exit(300) arrives here as
        44 (and as 300 on Windows). Whatever arrives, it is not 0, and
        the stage is FAIL."""
        fleet = [self.entry("weird", "weird.py")]
        self.tool("weird.py", "sys.exit(300)")
        report = self.run_gate(fleet=fleet)
        stage = report["stages"][0]
        self.assertEqual(stage["status"], "FAIL")
        self.assertNotEqual(stage["returncode"], 0)
        self.assertEqual(stage["returncode"],
                         300 & 0xFF if os.name == "posix" else 300)
        self.assertEqual(report["verdict"], "FAIL")

    def test_T10_only_unknown_name_exit_2_zero_stages(self):
        fleet = self.ok_fleet()
        code, _, err = self.run_cli(["--only", "borken"], fleet)
        self.assertEqual(code, BAD)
        self.assertIn("borken", err)
        self.assertIn("Refusing", err)
        self.assertEqual(self.receipts(), [])   # no run, no receipt

    def test_T11_only_valid_is_partial_exit_4(self):
        fleet = self.ok_fleet()
        report = self.run_gate(fleet=fleet, only=["ok0"])
        self.assertEqual(report["mode"], "PARTIAL")
        self.assertEqual(report["verdict"], "PARTIAL")
        self.assertEqual(report["exit_code"], PARTIAL)
        statuses = [s["status"] for s in report["stages"]]
        self.assertEqual(statuses, ["PASS", "EXCLUDED", "EXCLUDED"])

    def test_T12_only_with_failing_stage_exits_1_not_4(self):
        """Precedence 3 > 2 > 1 > 4 > 0: a failure is a failure
        regardless of scope."""
        fleet = self.ok_fleet(1)
        self.tool("bad.py", "sys.exit(1)")
        fleet.append(self.entry("bad", "bad.py"))
        report = self.run_gate(fleet=fleet, only=["bad"])
        self.assertEqual(report["mode"], "PARTIAL")
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(report["exit_code"], FAIL)

    def test_T13_skip_records_excluded_in_receipt(self):
        fleet = self.ok_fleet()
        self.run_gate(fleet=fleet, skip=["ok1"])
        receipt = self.receipts()[0]
        self.assertEqual(receipt["excluded"],
                         [{"name": "ok1", "by": "--skip"}])
        self.assertEqual(receipt["mode"], "PARTIAL")

    def test_T14_only_and_skip_together_exit_2(self):
        fleet = self.ok_fleet()
        with self.assertRaises(gr.InvocationError):
            self.run_gate(fleet=fleet, only=["ok0"], skip=["ok1"])
        code, _, _ = self.run_cli(["--only", "ok0", "--skip", "ok1"],
                                  fleet)
        self.assertEqual(code, BAD)

    def test_T15_stdout_lies_fail_exit_0_is_pass(self):
        """The runner reads only the code."""
        fleet = [self.entry("liar", "liar.py")]
        self.tool("liar.py", 'print("FAIL FAIL FAIL")\nsys.exit(0)')
        report = self.run_gate(fleet=fleet)
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report["stages"][0]["status"], "PASS")

    def test_T16_stdout_lies_fine_exit_1_is_fail(self):
        fleet = [self.entry("liar2", "liar2.py")]
        self.tool("liar2.py", 'print("everything is fine")\nsys.exit(1)')
        report = self.run_gate(fleet=fleet)
        self.assertEqual(report["verdict"], "FAIL")

    def test_T17_utf8_output_survives(self):
        """W14: bytes captured, UTF-8 decoded explicitly — cp1252 would
        SUCCEED and produce mojibake, which is worse than a crash."""
        fleet = [self.entry("emoji", "emoji.py")]
        self.tool("emoji.py",
                  'print("café 🎨 — décision")\nsys.exit(0)')
        report = self.run_gate(fleet=fleet)
        stage = report["stages"][0]
        self.assertEqual(stage["status"], "PASS")
        self.assertIn("café 🎨 — décision", stage["stdout_text"])
        report_text = Path(stage["output_ref"]).read_text(encoding="utf-8")
        self.assertIn("café 🎨 — décision", report_text)
        self.assertEqual(stage["stdout_bytes"],
                         len("café 🎨 — décision".encode("utf-8")) + 1)

    def test_T18_grandchild_never_blocks_cleanup(self):
        """A grandchild survives a naive kill and can hold the inherited
        pipe open. The process-group kill plus the short secondary
        communicate() means cleanup never blocks the fleet."""
        fleet = [self.entry("nest", "nest.py", timeout=1),
                 self.entry("after", "after.py")]
        self.tool("nest.py",
                  "import subprocess, time\n"
                  "subprocess.Popen([sys.executable, '-c', "
                  "'import time; time.sleep(30)'])\n"
                  "time.sleep(30)")
        self.tool("after.py", "sys.exit(0)")
        start = time.monotonic()
        report = self.run_gate(fleet=fleet)
        elapsed = time.monotonic() - start
        self.assertEqual(report["stages"][0]["status"], "HUNG")
        self.assertEqual(report["stages"][1]["status"], "PASS")
        self.assertLess(elapsed, 12, "grandchild blocked the fleet")

    def test_T19_determinism(self):
        """Two identical passing runs differ ONLY in run_id, timestamps,
        durations, and the run_id-derived report path."""
        fleet = self.ok_fleet()
        a = self.run_gate(fleet=fleet)
        b = self.run_gate(fleet=fleet)

        def normalize(rep):
            rep = json.loads(json.dumps(rep))
            for key in ("run_id", "started_utc", "finished_utc",
                        "duration_s", "report_path"):
                rep[key] = "X"
            for stage in rep["stages"]:
                stage["duration_s"] = 0
                stage["output_ref"] = "X"
            return rep
        self.assertEqual(normalize(a), normalize(b))

    def test_T20_json_matches_human_from_one_dict(self):
        fleet = self.ok_fleet(2)
        self.tool("bad.py", "sys.exit(1)")
        fleet.append(self.entry("bad", "bad.py"))
        code_h, human, _ = self.run_cli([], fleet)
        code_j, jout, _ = self.run_cli(["--json"], fleet)
        self.assertEqual(code_h, code_j)
        report = json.loads(jout)
        self.assertEqual(report["exit_code"], code_h)
        self.assertIn("VERDICT: %s" % report["verdict"],
                      gr.format_report(report))
        for stage in report["stages"]:
            self.assertIn(stage["name"], human)
        self.assertIn("VERDICT: %s" % report["verdict"], human)

    def test_T21_receipt_schema(self):
        fleet = self.ok_fleet(1)
        self.run_gate(fleet=fleet, skip=None)
        receipt = self.receipts()[0]
        for field in ("run_id", "started_utc", "finished_utc", "host",
                      "pid", "runner_version", "fleet_hash", "mode",
                      "excluded", "verdict", "exit_code", "duration_s",
                      "stages"):
            self.assertIn(field, receipt)
        stage = receipt["stages"][0]
        for field in ("name", "path", "status", "returncode",
                      "duration_s", "stdout_bytes", "stderr_bytes",
                      "output_ref", "depends_on", "downstream_note"):
            self.assertIn(field, stage)
        self.assertNotIn("stdout_text", stage)   # lengths, not content
        self.assertNotIn("stderr_text", stage)
        self.assertIn("+00:00", receipt["started_utc"])   # offset present

    def test_T22_fleet_order_respected(self):
        """W8: never filesystem order. A deliberately anti-alphabetical
        fleet must run in fleet order."""
        names = ["zeta", "alpha", "mid", "beta"]
        fleet = []
        for name in names:
            self.tool(name + ".py", "sys.exit(0)")
            fleet.append(self.entry(name, name + ".py"))
        report = self.run_gate(fleet=fleet)
        self.assertEqual([s["name"] for s in report["stages"]], names)

    def test_T23_no_identity_pattern_in_source(self):
        pattern = re.compile(r"\b\d{2}-\d{7}\b")
        for path in (gr.__file__, __file__):
            with open(path, encoding="utf-8") as handle:
                self.assertIsNone(pattern.search(handle.read()), path)

    def test_T24_read_only_over_the_fleet(self):
        fleet = self.ok_fleet()
        self.tool("bad.py", "sys.exit(1)")
        fleet.append(self.entry("bad", "bad.py"))
        before = {e["name"]: sha(self.dir / e["path"]) for e in fleet}
        self.run_gate(fleet=fleet)
        after = {e["name"]: sha(self.dir / e["path"]) for e in fleet}
        self.assertEqual(before, after)

    def test_T25_write_surfaces_exactly_two(self):
        """Snapshot diff: after a run, the ONLY new files are the
        receipts ledger and the report file."""
        fleet = self.ok_fleet()
        before = snapshot(self.dir)
        report = self.run_gate(fleet=fleet)
        after = snapshot(self.dir)
        self.assertEqual(set(before) - set(after), set())   # nothing lost
        new = set(after) - set(before)
        expected = {
            gr.RECEIPTS_NAME,
            str(Path(gr.REPORTS_DIRNAME) /
                ("gate_run_%s.txt" % report["run_id"])),
        }
        self.assertEqual(new, expected)
        changed = {k for k in before if before[k] != after[k]}
        self.assertEqual(changed, set())     # fixtures untouched

    def test_T26_unwritable_receipt_is_exit_3_not_1(self):
        fleet = self.ok_fleet(1)
        (self.dir / gr.RECEIPTS_NAME).mkdir()   # a dir where the file goes
        report = self.run_gate(fleet=fleet)
        self.assertEqual(report["exit_code"], INTERNAL)
        self.assertTrue(any("receipt" in n for n in report["notes"]))
        # precedence: even with a FAILING stage, receipt failure wins
        self.tool("bad.py", "sys.exit(1)")
        fleet.append(self.entry("bad", "bad.py"))
        report = self.run_gate(fleet=fleet)
        self.assertEqual(report["exit_code"], INTERNAL)

    def test_T27_help_exit_table_matches_constants(self):
        code, out, err = self.run_cli(["--help"], self.ok_fleet())
        help_text = out + err
        for line in gr.exit_code_table().split("\n"):
            self.assertIn(line, help_text)
        for value, name, _ in gr.EXIT_TABLE:
            self.assertIn("%d  %-22s" % (value, name) if False
                          else str(value), help_text)
        self.assertIn(gr.EXIT_PRECEDENCE, help_text)

    def test_T28_depends_on_annotates_and_dependent_still_ran(self):
        fleet = [self.entry("colorish", "colorish.py"),
                 self.entry("thumbish", "thumbish.py",
                            depends=["colorish"])]
        self.tool("colorish.py", "sys.exit(1)")
        self.tool("thumbish.py", "sys.exit(1)")
        report = self.run_gate(fleet=fleet)
        thumbish = report["stages"][1]
        self.assertEqual(thumbish["status"], "FAIL")     # it RAN
        self.assertGreater(thumbish["duration_s"], 0)
        self.assertEqual(thumbish["downstream_note"],
                         "may be downstream of colorish FAIL")
        self.assertIsNone(report["stages"][0]["downstream_note"])
        _, human, _ = self.run_cli([], fleet)
        self.assertIn("may be downstream of colorish FAIL", human)


if __name__ == "__main__":
    unittest.main(verbosity=2)
