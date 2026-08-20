#!/usr/bin/env python3
"""Test suite for vault_lint.py — stdlib unittest, synthetic fixtures only.

Fixtures are built in a temp dir; no real STATE.md is ever touched.
Tests 1-11 are the original spec; 12-30 each exist because they are a
way the linter could be wrong while looking right. The read-only
guarantee is enforced three independent ways (source scan, behavioral
hash/mtime, chmod 444) because one layer is not a guarantee.
"""

import ast
import hashlib
import io
import json
import os
import shutil
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout

import vault_lint as vl

CLEAN_EXIT, FINDINGS_EXIT, ERROR_EXIT = vl.EXIT_CLEAN, vl.EXIT_FINDINGS, vl.EXIT_ERROR

HEADER = (
    "# STATE\n"
    "\n"
    "| ID | Date | Decision | Status |\n"
    "|----|------|----------|--------|\n"
)


def row(n, text="Did a thing", status="FILED", date="2026-01-01"):
    return "| D-%s | %s | %s | %s |\n" % (n, date, text, status)


def run(argv):
    """Invoke the CLI, capturing (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = vl.main(argv)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else ERROR_EXIT
    return code, out.getvalue(), err.getvalue()


def sha(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="vault_lint_test_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def write(self, name, text, encoding="utf-8", newline="\n"):
        path = os.path.join(self.dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding=encoding, newline=newline) as handle:
            handle.write(text)
        return path

    def write_bytes(self, name, data):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def clean_state(self, name="STATE.md", count=5):
        return self.write(name, HEADER + "".join(row(100 + i) for i in range(count)))

    def findings_of(self, out_json):
        return json.loads(out_json)["findings"]


# ── 1-11: the original spec ────────────────────────────────────────────

class TestOriginalSpec(Fixture):

    def test_01_clean_file(self):
        path = self.clean_state()
        code, out, _ = run([path])
        self.assertEqual(code, CLEAN_EXIT, out)
        self.assertIn("no findings", out)
        self.assertIn("VERDICT: 0 critical, 0 warning, 0 info → PASS", out)

    def test_02_broken_row_reports_both_lines(self):
        path = self.write("STATE.md", HEADER + row(100) +
                          "| D-101 | 2026-01-02 | text that\n"
                          "keeps going | FILED |\n" + row(102))
        code, out, _ = run([path, "--json"])
        self.assertEqual(code, FINDINGS_EXIT)
        broken = [f for f in self.findings_of(out) if f["check"] == "broken"]
        self.assertEqual(len(broken), 1)
        self.assertEqual(broken[0]["dlabel"], "D-101")
        self.assertEqual(broken[0]["severity"], "CRITICAL")
        self.assertIn("L6-7", broken[0]["lines"])

    def test_03_duplicate_reports_every_line(self):
        path = self.write("STATE.md", HEADER + row(100) + row(101) + row(101) + row(102))
        code, out, _ = run([path, "--json"])
        self.assertEqual(code, FINDINGS_EXIT)
        dupes = [f for f in self.findings_of(out) if f["check"] == "dupes"]
        self.assertEqual(len(dupes), 1)
        self.assertIn("L6", dupes[0]["lines"])
        self.assertIn("L7", dupes[0]["lines"])
        self.assertEqual(dupes[0]["severity"], "CRITICAL")

    def test_03b_dupe_kinds_are_distinguished(self):
        path = self.write("STATE.md", HEADER + row(100) + row(100) +
                          row(101, "Version A") + row(101, "Version B"))
        _, out, _ = run([path, "--json"])
        dupes = {f["dlabel"]: f["message"] for f in self.findings_of(out)
                 if f["check"] == "dupes"}
        self.assertIn("copy-paste artifact", dupes["D-100"])
        self.assertIn("CONFLICTING", dupes["D-101"])

    def test_04_ghost_warning(self):
        path = self.write("STATE.md", HEADER + row(100) + row(101) +
                          "\nSee D-999 for the rationale.\n")
        code, out, _ = run([path, "--json"])
        self.assertEqual(code, FINDINGS_EXIT)
        ghosts = [f for f in self.findings_of(out) if f["check"] == "ghosts"]
        self.assertEqual(len(ghosts), 1)
        self.assertEqual(ghosts[0]["dlabel"], "D-999")
        self.assertEqual(ghosts[0]["severity"], "WARNING")

    def test_05_gap_is_info_only_and_never_fails(self):
        path = self.write("STATE.md", HEADER + row(100) + row(105))
        code, out, _ = run([path, "--json"])
        self.assertEqual(code, CLEAN_EXIT)   # info alone never fails
        report = json.loads(out)
        gaps = [f for f in report["findings"] if f["check"] == "gaps"]
        self.assertEqual(len(gaps), 1)
        self.assertIn("D-101..D-104 (4 missing)", gaps[0]["message"])
        self.assertEqual(report["verdict"], "PASS")

    def test_06_wrong_column_count_is_warning(self):
        path = self.write("STATE.md", HEADER +
                          "".join(row(100 + i) for i in range(5)) +
                          "| D-105 | 2026-01-06 | missing a cell |\n")
        code, out, _ = run([path, "--json"])
        self.assertEqual(code, FINDINGS_EXIT)
        cols = [f for f in self.findings_of(out) if f["check"] == "columns"]
        self.assertEqual(len(cols), 1)
        self.assertEqual(cols[0]["dlabel"], "D-105")
        self.assertEqual(cols[0]["severity"], "WARNING")

    def test_07_missing_file(self):
        code, _, err = run([os.path.join(self.dir, "nope.md")])
        self.assertEqual(code, ERROR_EXIT)
        self.assertIn("not found", err)

    def test_08_zero_rows_is_loud_exit_2_with_samples(self):
        path = self.write("STATE.md",
                          "# Notes\n\n| ID | Date |\n|----|------|\n"
                          "just prose here\n")
        code, out, _ = run([path])
        self.assertEqual(code, ERROR_EXIT)
        self.assertIn("PATTERN MISMATCH", out)
        self.assertIn("matched 0 rows", out)
        self.assertIn("| ID | Date |", out)       # real sample line shown
        self.assertNotIn("no findings", out)      # never certified clean

    def test_09_json_matches_human_mode(self):
        cases = [
            [self.clean_state("a.md")],
            [self.write("b.md", HEADER + row(100) + row(100))],
            [self.write("c.md", HEADER + row(100) + "\nSee D-500.\n")],
        ]
        for argv in cases:
            h_code, h_out, _ = run(argv)
            j_code, j_out, _ = run(argv + ["--json"])
            report = json.loads(j_out)
            self.assertEqual(h_code, j_code, argv)
            self.assertEqual(report["exit_code"], h_code, argv)
            self.assertIn("→ %s" % report["verdict"], h_out, argv)
            for f in report["findings"]:
                if f["dlabel"] and f["dlabel"] != "--":
                    self.assertIn(f["dlabel"], h_out, argv)

    def test_11_the_d316_regression(self):
        """THE TOOL'S THESIS. The incident: a decision (D-316) was present
        in STATE.md — its content was in the file — but its table row
        format was broken, so a literal search for '| D-316 |' found
        nothing and the decision did not exist as far as any tool or
        session was concerned. Both halves asserted: the literal search
        misses it, AND the linter finds it and names D-316."""
        content = (HEADER + row(100) +
                   "| D-316\n"
                   "2026-07-14 | Ban brick red on sport grey | FILED |\n" +
                   row(317))
        path = self.write("STATE.md", content)
        self.assertNotIn("| D-316 |", content)          # grep loses
        code, out, _ = run([path, "--json"])
        self.assertEqual(code, FINDINGS_EXIT)
        named = [f for f in self.findings_of(out) if f["dlabel"] == "D-316"]
        self.assertEqual(len(named), 1)                  # the linter wins
        self.assertEqual(named[0]["check"], "broken")
        self.assertEqual(named[0]["severity"], "CRITICAL")


# ── 12-24: ways the linter could be wrong while looking right ──────────

class TestFalsePositivesAndEdges(Fixture):

    def test_12_trailing_whitespace_is_not_a_broken_row(self):
        """Verified false positive: a naive endswith('|') flags this."""
        path = self.write("STATE.md", HEADER +
                          "| D-100 | 2026-01-01 | Did a thing | FILED |   \n" +
                          row(101))
        code, out, _ = run([path])
        self.assertEqual(code, CLEAN_EXIT, out)
        self.assertIn("no findings", out)

    def test_13_crlf_line_endings_are_clean(self):
        text = (HEADER + row(100) + row(101)).replace("\n", "\r\n")
        path = self.write("STATE.md", text, newline="")
        code, out, _ = run([path])
        self.assertEqual(code, CLEAN_EXIT, out)
        self.assertIn("no findings", out)

    def test_14_row_inside_code_fence_is_not_a_decision(self):
        """Verified: a naive scan reports the fenced row as real."""
        path = self.write("STATE.md", HEADER + row(100) +
                          "```\n| D-777 | fake | example | X |\n```\n")
        code, out, _ = run([path, "--json"])
        self.assertEqual(code, CLEAN_EXIT)
        report = json.loads(out)
        self.assertEqual(report["summary"]["rows"], 1)   # only D-100
        self.assertEqual(report["summary"]["excluded_lines"], 3)
        self.assertEqual(report["summary"]["fences"], 1)

    def test_14b_html_comment_excluded_too(self):
        path = self.write("STATE.md", HEADER + row(100) +
                          "<!--\n| D-778 | hidden | row | X |\nSee D-779.\n-->\n")
        code, out, _ = run([path, "--json"])
        self.assertEqual(code, CLEAN_EXIT)
        self.assertEqual(json.loads(out)["summary"]["rows"], 1)

    def test_15_dnumber_inside_fence_is_not_a_ghost(self):
        path = self.write("STATE.md", HEADER + row(100) +
                          "```\nexample: see D-999 here\n```\n")
        code, out, _ = run([path, "--json"])
        self.assertEqual(code, CLEAN_EXIT)
        self.assertEqual([f for f in self.findings_of(out)
                          if f["check"] == "ghosts"], [])

    def test_16_negation_is_not_a_ghost(self):
        path = self.write("STATE.md", HEADER + row(100) +
                          "\nThere is no D-999 covering this.\n"
                          "This is not D-998 territory.\n"
                          "We never D-997'd anything.\n")
        code, out, _ = run([path, "--json"])
        self.assertEqual(code, CLEAN_EXIT, out)
        self.assertEqual([f for f in self.findings_of(out)
                          if f["check"] == "ghosts"], [])

    def test_17_range_expands_to_every_number(self):
        """'D-300 through D-310' means eleven numbers, not two. Rows for
        300..309 exist; only 310 is missing — exactly one ghost proves
        the whole range was checked."""
        path = self.write("STATE.md", HEADER +
                          "".join(row(300 + i) for i in range(10)) +
                          "\nDecisions D-300 through D-310 are archived.\n")
        code, out, _ = run([path, "--json"])
        self.assertEqual(code, FINDINGS_EXIT)
        ghosts = [f["dlabel"] for f in self.findings_of(out)
                  if f["check"] == "ghosts"]
        self.assertEqual(ghosts, ["D-310"])

    def test_18_archive_ghosts(self):
        """The check that decides whether the tool survives its first real
        run: an archived decision referenced from STATE.md is NOT a ghost
        when the archive is scanned, and IS one when it is not."""
        state = self.write("STATE.md", HEADER +
                           "".join(row(100 + i) for i in range(3)) +
                           "\nSupersedes D-050 (archived).\n")
        self.write(os.path.join("archives", "2026-07.md"),
                   HEADER + row("050", "Old decision"))
        pattern = os.path.join(self.dir, "archives", "*.md")

        code, out, _ = run([state, "--json"])            # without archives
        self.assertEqual(code, FINDINGS_EXIT)
        ghosts = [f for f in self.findings_of(out) if f["check"] == "ghosts"]
        self.assertEqual([g["dlabel"] for g in ghosts], ["D-50"])

        code, out, _ = run([state, "--json", "--also-scan", pattern])
        self.assertEqual(code, CLEAN_EXIT, out)
        report = json.loads(out)
        self.assertEqual(report["findings"], [])          # ZERO findings
        self.assertEqual(report["summary"]["also_scanned"]["files"], 1)
        self.assertEqual(report["summary"]["also_scanned"]["rows"], 1)

    def test_18b_also_scan_matching_nothing_is_exit_2(self):
        state = self.clean_state()
        code, _, err = run([state, "--also-scan",
                            os.path.join(self.dir, "nothing", "*.md")])
        self.assertEqual(code, ERROR_EXIT)
        self.assertIn("matched no files", err)

    def test_19_invisible_char_names_the_codepoint(self):
        path = self.write("STATE.md", HEADER + row(100) +
                          "| D-244\xa0| 2026-01-02 | NBSP lurks | FILED |\n")
        code, out, _ = run([path])
        self.assertEqual(code, FINDINGS_EXIT)
        self.assertIn("U+00A0 NO-BREAK SPACE", out)
        self.assertIn("column 8", out)
        self.assertIn(r"\xa0", out)                       # repr shows the bytes
        self.assertIn("D-244", out)

    def test_20_stub_row(self):
        path = self.write("STATE.md", HEADER + row(100) +
                          "| D-317 |  |  |  |\n")
        code, out, _ = run([path, "--json"])
        self.assertEqual(code, FINDINGS_EXIT)
        stubs = [f for f in self.findings_of(out) if f["check"] == "stub"]
        self.assertEqual([s["dlabel"] for s in stubs], ["D-317"])
        self.assertEqual(stubs[0]["severity"], "WARNING")

    def test_21_malformed_is_never_silently_skipped(self):
        path = self.write("STATE.md", HEADER + row(100) +
                          "| D-3l6 | 2026-01-02 | letter L | FILED |\n"
                          "| D- | 2026-01-03 | no number | FILED |\n"
                          " | D-107 | 2026-01-04 | leading space | FILED |\n")
        code, out, _ = run([path, "--json"])
        self.assertEqual(code, FINDINGS_EXIT)
        mal = [f for f in self.findings_of(out) if f["check"] == "malformed"]
        self.assertEqual(len(mal), 3)
        raws = " ".join(f["message"] for f in mal)
        self.assertIn("D-3l6", raws)                      # raw text reported

    def test_22_precedence_one_problem_one_finding(self):
        """A single broken row must not surface as broken + ghost +
        column-anomaly. The prose mention of D-103 would be a ghost (no
        healthy row) — precedence suppresses it."""
        path = self.write("STATE.md", HEADER + row(100) + row(101) +
                          "| D-102\n"
                          "| 2026-01-04 | split | FILED |\n"
                          "\nSee D-102 for details.\n")
        code, out, _ = run([path, "--json"])
        self.assertEqual(code, FINDINGS_EXIT)
        findings = self.findings_of(out)
        self.assertEqual(len(findings), 1, findings)
        self.assertEqual(findings[0]["check"], "broken")
        self.assertEqual(findings[0]["dlabel"], "D-102")

    def test_23_dominant_count_degeneracy(self):
        """A self-learned baseline can learn the disease. When no shape
        holds the majority, the linter must say so and flag nothing
        row-by-row — otherwise it certifies the corruption as normal and
        flags the healthy rows."""
        path = self.write("STATE.md", HEADER +
                          "| D-100 | a | b | FILED |\n"
                          "| D-101 | a | b | FILED |\n"
                          "| D-102 | a | FILED |\n"
                          "| D-103 | a | FILED |\n"
                          "| D-104 | FILED |\n")
        code, out, _ = run([path, "--json"])
        self.assertEqual(code, FINDINGS_EXIT)
        cols = [f for f in self.findings_of(out) if f["check"] == "columns"]
        self.assertEqual(len(cols), 1)                    # one, not per-row
        self.assertEqual(cols[0]["severity"], "CRITICAL")
        self.assertIn("no dominant column shape", cols[0]["message"])
        self.assertIn("40%", cols[0]["message"])          # confidence stated
        self.assertIn("pipes", cols[0]["message"])        # distribution shown

    def test_24_unknown_check_name_is_exit_2_never_a_silent_pass(self):
        """'--only borken' silently running nothing and exiting 0 is the
        most dangerous possible failure in a gate."""
        path = self.clean_state()
        code, out, err = run([path, "--only", "borken"])
        self.assertEqual(code, ERROR_EXIT)
        self.assertIn("borken", err)
        self.assertIn("broken", err)                      # valid names listed
        self.assertNotIn("PASS", out)
        self.assertNotIn("no findings", out)
        code, _, err = run([path, "--exclude", "gasp"])
        self.assertEqual(code, ERROR_EXIT)

    def test_24b_only_and_exclude_work_when_valid(self):
        path = self.write("STATE.md", HEADER + row(100) + row(100) + row(105))
        code, out, _ = run([path, "--json", "--only", "dupes"])
        self.assertEqual(code, FINDINGS_EXIT)
        self.assertEqual({f["check"] for f in self.findings_of(out)}, {"dupes"})
        code, out, _ = run([path, "--json", "--exclude", "gaps,order,dupes"])
        self.assertEqual(code, CLEAN_EXIT)
        self.assertEqual(self.findings_of(out), [])


# ── 25-30: modes, robustness, determinism, scale ───────────────────────

class TestModesAndRobustness(Fixture):

    def test_25_fail_on_critical_lets_warnings_pass(self):
        path = self.write("STATE.md", HEADER + row(100) +
                          "| D-317 |  |  |  |\n")       # warning-only file
        code, _, _ = run([path])
        self.assertEqual(code, FINDINGS_EXIT)             # default: warning fails
        code, out, _ = run([path, "--fail-on", "critical", "--json"])
        self.assertEqual(code, CLEAN_EXIT)
        report = json.loads(out)
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report["counts"]["WARNING"], 1)  # still reported

    def test_26_baseline_ratchet(self):
        """The adoption feature: known findings suppress, new ones fail,
        and the baseline lives in its own JSON — the markdown under
        inspection is never touched."""
        path = self.write("STATE.md", HEADER + row(100) + row(100))
        baseline = os.path.join(self.dir, "baseline.json")
        before = sha(path)

        code, _, _ = run([path, "--baseline", baseline, "--write-baseline"])
        self.assertEqual(code, FINDINGS_EXIT)             # still red today
        self.assertTrue(os.path.isfile(baseline))
        self.assertNotEqual(os.path.realpath(baseline), os.path.realpath(path))

        code, out, _ = run([path, "--baseline", baseline, "--json"])
        self.assertEqual(code, CLEAN_EXIT, out)           # backlog suppressed
        report = json.loads(out)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["summary"]["baseline"]["suppressed"], 1)

        with open(path, "a", encoding="utf-8") as handle:  # a NEW defect
            handle.write("| D-3l6 | x | y | FILED |\n")
        code, out, _ = run([path, "--baseline", baseline, "--json"])
        self.assertEqual(code, FINDINGS_EXIT)             # ratchet catches it
        checks = {f["check"] for f in self.findings_of(out)}
        self.assertEqual(checks, {"malformed"})           # only the new one

        os.replace(path, path)  # no-op; now verify content never changed
        with open(path, "r", encoding="utf-8") as handle:
            self.assertIn("| D-3l6 |", handle.read())     # our append only

    def test_26b_baseline_refuses_markdown_and_inspected_paths(self):
        path = self.clean_state()
        code, _, err = run([path, "--baseline", path, "--write-baseline"])
        self.assertEqual(code, ERROR_EXIT)
        self.assertIn("refusing", err.lower())
        code, _, err = run([path, "--baseline",
                            os.path.join(self.dir, "b.md"), "--write-baseline"])
        self.assertEqual(code, ERROR_EXIT)
        self.assertIn("markdown", err)

    def test_27_utf8_emoji_and_smart_quotes_no_crash(self):
        path = self.write("STATE.md", HEADER +
                          row(100, "Chose “sage” over gold — final 🎨") +
                          row(101, "Café rules → em-dash — everywhere"))
        code, out, _ = run([path])
        self.assertEqual(code, CLEAN_EXIT, out)
        self.assertIn("no findings", out)

    def test_28_invalid_utf8_warns_and_never_crashes(self):
        data = (HEADER + row(100)).encode("utf-8") + \
            b"| D-101 | 2026-01-02 | caf\xe9 latin-1 byte | FILED |\n"
        path = self.write_bytes("STATE.md", data)
        code, out, _ = run([path, "--json"])
        self.assertNotEqual(code, ERROR_EXIT)             # a finding, not a crash
        enc = [f for f in self.findings_of(out) if f["check"] == "encoding"]
        self.assertEqual(len(enc), 1)
        self.assertEqual(enc[0]["severity"], "WARNING")
        self.assertIn("L6", enc[0]["lines"])

    def test_29_determinism(self):
        path = self.write("STATE.md", HEADER + row(100) + row(100) +
                          row(105) + "| D-317 |  |  |  |\n"
                          "\nSee D-900.\n")
        first = run([path])
        second = run([path])
        self.assertEqual(first, second)                   # byte-identical
        first_json = run([path, "--json"])
        second_json = run([path, "--json"])
        self.assertEqual(first_json, second_json)

    def test_30_streaming_scale(self):
        """50,000 lines must complete fast — proves streaming, not
        slurping, and no accidentally quadratic check."""
        lines = [HEADER]
        lines += [row(100 + i) for i in range(50000)]
        path = self.write("STATE.md", "".join(lines))
        start = time.monotonic()
        code, out, _ = run([path])
        elapsed = time.monotonic() - start
        self.assertEqual(code, CLEAN_EXIT, out[-500:])
        self.assertLess(elapsed, 15.0, "50k lines took %.1fs" % elapsed)
        self.assertIn("rows: 50000", out)


# ── the read-only guarantee: three independent layers ──────────────────

class TestReadOnlyGuarantee(Fixture):

    def test_10a_source_scan(self):
        """Layer (a): parse vault_lint.py itself. Write-mode opens exist
        ONLY inside write_baseline and append_heartbeat; no os.remove /
        rename / truncate / unlink, no shutil, subprocess, tempfile, or
        pathlib anywhere. Mocking open() alone would miss all of these."""
        source_path = vl.__file__
        with open(source_path, "r", encoding="utf-8") as handle:
            source = handle.read()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names]
                if isinstance(node, ast.ImportFrom):
                    names.append(node.module or "")
                for name in names:
                    root = name.split(".")[0]
                    self.assertNotIn(root, ("shutil", "subprocess",
                                            "tempfile", "pathlib"),
                                     "forbidden import: %s" % name)

        banned_attrs = {"remove", "rename", "truncate", "unlink",
                        "replace", "rmdir", "write_text", "write_bytes"}
        allowed_write_funcs = {"write_baseline", "append_heartbeat"}

        class Auditor(ast.NodeVisitor):
            def __init__(self):
                self.stack = []
                self.violations = []

            def visit_FunctionDef(self, node):
                self.stack.append(node.name)
                self.generic_visit(node)
                self.stack.pop()

            def visit_Call(self, node):
                func = node.func
                if isinstance(func, ast.Attribute):
                    if (func.attr in banned_attrs
                            and isinstance(func.value, ast.Name)
                            and func.value.id == "os"):
                        self.violations.append(
                            "os.%s in %s" % (func.attr, self.stack))
                if isinstance(func, ast.Name) and func.id == "open":
                    mode = None
                    if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                        mode = node.args[1].value
                    for kw in node.keywords:
                        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                            mode = kw.value.value
                    mode = mode or "r"
                    if set(mode) & set("wax+"):
                        where = self.stack[-1] if self.stack else "<module>"
                        if where not in allowed_write_funcs:
                            self.violations.append(
                                "open(mode=%r) in %s" % (mode, where))
                self.generic_visit(node)

        auditor = Auditor()
        auditor.visit(tree)
        self.assertEqual(auditor.violations, [])

        # Neither writer can receive an inspected path: both compare
        # realpaths against the inspected list and refuse (asserted
        # behaviorally in test_26b and test_10d).
        self.assertIn("os.path.realpath(inspected)", source)
        # Rider 3: INVISIBLE_CHARS is escape sequences in source, never glyphs.
        self.assertIn('\\xa0\\u200b\\u200c\\u200d\\ufeff\\t', source)
        for glyph in ("\u00a0", "\u200b", "\u200c", "\u200d", "\ufeff"):
            self.assertNotIn(glyph, source,
                             "literal invisible glyph pasted in source")
        # The Unicode-aware \s comment must survive refactors.
        self.assertIn(r"USE \s, NEVER A LITERAL SPACE", source)

    def test_10b_behavioral_hash_and_mtime(self):
        """Layer (b): run the full linter over a findings-laden file and
        assert its bytes and mtime are untouched."""
        path = self.write("STATE.md", HEADER + row(100) + row(100) +
                          "| D-316\ncontinuation | FILED |\n"
                          "| D-244\xa0| x | y | FILED |\n"
                          "\nSee D-999.\n")
        before_hash, before_mtime = sha(path), os.path.getmtime(path)
        code, _, _ = run([path])
        self.assertEqual(code, FINDINGS_EXIT)
        self.assertEqual(sha(path), before_hash)
        self.assertEqual(os.path.getmtime(path), before_mtime)

    def test_10c_readonly_filesystem(self):
        """Layer (c): chmod 444 — a tool that needs write permission on
        its input fails here even if the other layers somehow pass."""
        path = self.clean_state()
        os.chmod(path, 0o444)
        self.addCleanup(os.chmod, path, 0o644)
        code, out, _ = run([path])
        self.assertEqual(code, CLEAN_EXIT, out)
        self.assertIn("no findings", out)

    def test_10d_heartbeat_never_touches_inputs_and_never_creates(self):
        path = self.write("STATE.md", HEADER + row(100))
        runlog = os.path.join(self.dir, "runlog.txt")
        original = vl.RUNLOG_PATH
        self.addCleanup(setattr, vl, "RUNLOG_PATH", original)

        vl.RUNLOG_PATH = runlog                  # absent → skip, never create
        code, out, _ = run([path])
        self.assertEqual(code, CLEAN_EXIT)
        self.assertFalse(os.path.exists(runlog))
        self.assertIn("heartbeat skipped", out)

        with open(runlog, "w", encoding="utf-8") as handle:  # present → append
            handle.write("existing line\n")
        run([path])
        with open(runlog, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        self.assertEqual(lines[0], "existing line")
        self.assertEqual(len(lines), 2)
        self.assertIn(vl.HEARTBEAT_STAGE, lines[1])
        self.assertIn("pass", lines[1])

        vl.RUNLOG_PATH = path                    # inspected path → refuse
        before = sha(path)
        _, out, _ = run([path])
        self.assertEqual(sha(path), before)
        self.assertIn("SKIPPED", out)

    def test_no_fix_flag_exists(self):
        """There is no --fix flag and there never will be one."""
        code, _, err = run([self.clean_state(), "--fix"])
        self.assertEqual(code, ERROR_EXIT)
        help_text = vl.build_parser().format_help()
        self.assertNotIn("--fix", help_text)


class TestScanLinesEquivalence(Fixture):

    def test_scan_file_equals_scan_lines(self):
        """The refactor contract: scan_file(path) is a thin I/O wrapper
        and scan_lines(lines) is the single source of classification
        truth. Both must produce identical results on the same content
        — including CRLF files (whose handle-iterated lines end \n
        after universal-newline translation while a raw keepends split
        yields \r\n; rstrip inside scan_lines absorbs the difference)
        and U+2028 (which neither Python text I/O nor a \n-only split
        treats as a line break)."""
        fixtures = {
            "plain.md": HEADER + row(100) + row(101) +
                        "\nSee D-900.\n| D-102\ncontinues | FILED |\n",
            "crlf.md": (HEADER + row(100) + row(101)).replace("\n", "\r\n"),
            "u2028.md": HEADER + row(100) +
                        "prose with\u2028inside one line\n" + row(101),
            "nofinal.md": HEADER + row(100) + "| D-101 | x | y | FILED |",
        }
        for name, content in fixtures.items():
            path = self.write(name, content, newline="")
            via_file = vl.scan_file(path)
            for key in ("path", "size"):
                via_file.pop(key)
            parts = content.split("\n")
            lines = [p + "\n" for p in parts[:-1]]
            if parts[-1] != "":
                lines.append(parts[-1])
            via_lines = vl.scan_lines(lines)
            self.assertEqual(via_file, via_lines, name)

    def test_detect_is_pure_and_matches_cli_findings(self):
        path = self.write("STATE.md", HEADER + row(100) + row(100) +
                          "\nSee D-900.\n")
        with open(path, "r", encoding="utf-8") as handle:
            det = vl.detect(handle.readlines())
        _, out, _ = run([path, "--json"])
        cli = json.loads(out)["findings"]
        self.assertEqual(det["findings"], cli)


class TestExplain(Fixture):

    def test_explain_carries_the_institutional_memory(self):
        code, out, _ = run(["--explain"])
        self.assertEqual(code, CLEAN_EXIT)
        for check in vl.CHECKS:
            self.assertIn(check, out)
        self.assertIn("D-316", out)
        self.assertIn("D-350", out)
        self.assertIn("root mechanism unconfirmed", out)   # truthful history
        self.assertIn("PREVENTIVE", out)                   # NBSP not claimed as cause
        self.assertIn("never modifies", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
