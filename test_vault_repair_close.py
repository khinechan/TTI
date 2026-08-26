#!/usr/bin/env python3
"""Tests for vault_repair.py v1.1 --close-only batch mode. NEW file —
the 33 v1.0 tests in test_vault_repair.py are not touched (W-I).

T1 is the most important test in this build: the predicate must
reproduce the human's own D-363 classification exactly — 33 approved
in, 6 excluded out. Fixtures are structural ground truth (sanitized,
middles elided); the predicate never depends on content bytes."""

import ast
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

import vault_lint as vl
import vault_repair as vr

NOTHING, REPAIRS, ERROR = vr.EXIT_NOTHING, vr.EXIT_REPAIRS, vr.EXIT_ERROR

HEADER6 = (
    "# STATE\n"
    "\n"
    "| ID | Date | Decision | Status | Supersedes |\n"
    "|----|------|----------|--------|------------|\n"
)


def row6(n, text="fine row", status="ACTIVE", refs="-"):
    return "| D-%s | 2026-01-01 | %s | %s | %s |\n" % (n, text, status, refs)


def close_only_row(n, text="complete text", status="ACTIVE", refs="D-050"):
    """Content complete on one line, missing only the closing pipe."""
    return "| D-%s | 2026-01-01 | %s | %s | %s\n" % (n, text, status, refs)


# ── D-363 GROUND TRUTH (sanitized; structural). The 33 the human
# approved carry every cell on the line; D-097 additionally carries
# three pipes inside a backtick-quoted RUNLOG example. The 6 the human
# excluded: five multi-paragraph rows whose closing cells sit on a
# later physical line, and D-325 whose closing cells are gone. ──

APPROVED = [
    (46, "DOCTRINE", "D-045"), (47, "ACTIVE", "D-026, D-036"),
    (48, "ACTIVE", "D-043, D-045"), (49, "ACTIVE", "-"),
    (50, "ACTIVE", "D-026, D-037, D-049"),
    (51, "ACTIVE", "D-020, D-046, D-048, D-050"),
    (52, "ACTIVE", "D-048, D-051"), (53, "ACTIVE", "D-051"),
    (54, "DOCTRINE", "D-051, D-053"),
    (55, "DOCTRINE", "D-026, D-037, D-048, D-049, D-051"),
    (58, "ACTIVE", "D-024, D-056, D-057"),
    (59, "ACTIVE", "D-014, D-016, D-026, D-037"),
    (60, "ACTIVE", "D-059"), (61, "ACTIVE", "D-036, D-039"),
    (63, "ACTIVE", "D-037, D-051, D-062"),
    (64, "ACTIVE", "D-053, D-062, D-063"),
    (65, "ACTIVE", "D-044, D-045, D-046, D-053, D-064"),
    (67, "ACTIVE", "D-064, D-065, D-066"),
    (68, "ACTIVE", "D-065, D-066, D-067"),
    (69, "ACTIVE", "D-065, D-066, D-067, D-068, D-061"),
    (70, "ACTIVE", "D-024, D-053, D-062, D-063"),
    (71, "ACTIVE", "D-070, D-065, D-066, D-067, D-068, D-069"),
    (72, "ACTIVE", "-"), (73, "ACTIVE", "D-016, D-028, D-059"),
    (76, "ACTIVE", "D-062, D-063, D-064, D-072"),
    (86, "ACTIVE", "D-081, D-084, D-085"), (84, "ACTIVE", "D-081"),
    (81, "ACTIVE", "D-026"), (80, "ACTIVE", "-"),
    (74, "ACTIVE", "D-073, D-059, D-025"),
    (75, "ACTIVE", "D-038, D-051, D-063"),
    (100, "ACTIVE", "D-025, D-037, D-058"),
    (97, "DOCTRINE", "D-090, D-026"),   # 8 pipes: 3 inside backticks
]

DOMINANT = 6   # a finished vault row: | id | date | text | status | refs |


def approved_body(num, status, refs):
    text = "...elided decision text"
    if num == 97:
        text = "...no fact `RUNLOG|OK|line|example` refines D-090, D-026"
    return "| D-%03d | 2026-01-01 | %s | %s | %s" % (num, text, status, refs)


EXCLUDED = {
    314: "| D-314 | 2026-01-01 | first paragraph of a multi-paragraph decision",
    315: "| D-315 | 2026-01-01 | first paragraph, closing cells 10+ lines down",
    316: "| D-316",
    349: "| D-349 | 2026-01-01 | multi-paragraph, cells on the last line",
    350: "| D-350 | 2026-01-01 | multi-paragraph, cells on the last line",
    325: "| D-325 | 2026-01-01 | complete sentence but closing cells GONE",
}


def candidate(body, num):
    return {"body": body, "pipes": body.rstrip().count("|"),
            "dominant": DOMINANT, "dnum": num}


def run(argv, keys=None):
    script = list(keys or [])

    def scripted(prompt):
        if not script:
            raise EOFError
        item = script.pop(0)
        if isinstance(item, type) and issubclass(item, BaseException):
            raise item
        return item

    original = vr.read_key
    vr.read_key = scripted
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = vr.main(argv)
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else ERROR
    finally:
        vr.read_key = original
    return code, out.getvalue(), err.getvalue()


def sha(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def raw(path):
    with open(path, "rb") as handle:
        return handle.read()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="vault_repair_close_test_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def write(self, name, text, newline=""):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8", newline=newline) as handle:
            handle.write(text)
        return path

    def mixed(self, name="STATE.md", healthy=12, close=("112", "113"),
              hard="| D-314 | 2026-01-01 | multi-paragraph starts\n"
                   "more prose of the same decision\n"):
        return self.write(name, HEADER6 +
                          "".join(row6(100 + i) for i in range(healthy)) +
                          "".join(close_only_row(n) for n in close) +
                          hard + row6(140))


class TestPredicate(Fixture):

    def test_T01_ground_truth_exactly_33_in_6_out(self):
        """THE MOST IMPORTANT TEST IN THIS BUILD. If the predicate
        cannot reproduce the human's own classification on the data the
        class was derived from, it is a recollection of the class, and
        it is about to write to STATE.md."""
        matched, excluded = set(), set()
        for num, status, refs in APPROVED:
            ok, reason = vr.is_close_only(
                candidate(approved_body(num, status, refs), num))
            (matched if ok else excluded).add(num)
        for num, body in EXCLUDED.items():
            ok, reason = vr.is_close_only(candidate(body, num))
            (matched if ok else excluded).add(num)
        self.assertEqual(matched, {n for n, _, _ in APPROVED})   # exactly 33
        self.assertEqual(len(matched), 33)
        self.assertEqual(excluded, set(EXCLUDED))                # exactly 6
        self.assertEqual(len(excluded), 6)

    def test_T02_frozen_class_boundary(self):
        """The predicate's behaviour is frozen by fixture: the 5-pipe /
        4-pipe boundary and the D-097 >= rule are locked. Any widening
        edit fails here."""
        five = "| D-200 | 2026-01-01 | text | ACTIVE | D-100"
        four = "| D-201 | 2026-01-01 | text | ACTIVE"
        self.assertTrue(vr.is_close_only(candidate(five, 200))[0])
        ok, reason = vr.is_close_only(candidate(four, 201))
        self.assertFalse(ok)
        self.assertIn("4 of the 5 separators", reason)
        eight = approved_body(97, "DOCTRINE", "D-090, D-026")
        self.assertEqual(eight.rstrip().count("|"), 8)
        self.assertTrue(vr.is_close_only(candidate(eight, 97))[0])
        # class v1.1 (D-382): backticked pipes no longer count toward
        # the separator bar. D-097's STRIPPED count is exactly the bar
        # (5), so it still classifies — the raw 8 never mattered.
        self.assertEqual(vr.CLOSE_ONLY_CLASS_VERSION, "1.1")

    def test_T02b_d382_backticked_decoy_pipes_do_not_classify(self):
        """D-382 regression, caught by the live canary: a row whose
        backtick-quoted pipes push its RAW count to the threshold must
        NOT classify. The real-world case is the D-316 shape — its
        prose contains '| D-316 |' inside backticks, the row literally
        describing this bug class. Verify caught the v1.0 escape before
        any write; this test keeps the predicate honest forever."""
        body = ("| D-316 | 2026-01-01 | the row `| D-316 |` describes "
                "this bug class")
        self.assertEqual(body.count("|"), 5)          # raw hits the bar
        ok, reason = vr.is_close_only(candidate(body, 316))
        self.assertFalse(ok)
        self.assertIn("backtick-quoted pipes excluded", reason)
        self.assertIn("D-382", reason)
        # an UNPAIRED backtick stays literal — the regex eats pairs only
        unpaired = "| D-200 | 2026-01-01 | text with one ` mark | ACTIVE | D-100"
        self.assertTrue(vr.is_close_only(candidate(unpaired, 200))[0])

    def test_T03_addendum_format_row_is_not_close_only(self):
        """Upstream-coupling guard: ROW_PATTERN was widened in D-376 to
        know addendum IDs. That widening must never silently widen this
        class — the D-363 set was all plain-numeric."""
        for body in ("| D-144 addendum | 2026-01-01 | text | ACTIVE | -",
                     "| D-102b | 2026-01-01 | text | ACTIVE | -"):
            ok, reason = vr.is_close_only(candidate(body, 144))
            self.assertFalse(ok, body)
            self.assertIn("addendum", reason)

    def test_T04_each_hard_row_excluded_with_a_named_reason(self):
        expects = {
            314: "continue on later lines", 315: "continue on later lines",
            349: "continue on later lines", 350: "continue on later lines",
            316: "unclosed ID cell",
            325: "cells are missing or continue",
        }
        for num, keyword in expects.items():
            ok, reason = vr.is_close_only(candidate(EXCLUDED[num], num))
            self.assertFalse(ok, "D-%d" % num)
            self.assertIn(keyword, reason, "D-%d: %s" % (num, reason))


class TestBatchMode(Fixture):

    def test_T05_dry_run_zero_writes(self):
        path = self.mixed()
        before_hash, before_mtime = sha(path), os.path.getmtime(path)
        listing = sorted(os.listdir(self.dir))
        code, out, _ = run([path, "--close-only"])
        self.assertEqual(code, REPAIRS)
        self.assertEqual(sha(path), before_hash)
        self.assertEqual(os.path.getmtime(path), before_mtime)
        self.assertEqual(sorted(os.listdir(self.dir)), listing)

    def test_T06_confirmation_n_writes_nothing_exit_2(self):
        path = self.mixed()
        before = raw(path)
        code, _, err = run([path, "--close-only", "--apply"], keys=["n"])
        self.assertEqual(code, ERROR)
        self.assertIn("declined", err)
        self.assertEqual(raw(path), before)
        self.assertEqual([f for f in os.listdir(self.dir)
                          if f.endswith((".bak", ".jsonl"))], [])

    def test_T07_prompt_loop_is_never_entered(self):
        """W-E: batch mode must not reach collect_approvals at all — a
        leaked prompt loop is detectable exactly here. EOF at the single
        confirmation aborts cleanly, never hangs."""
        path = self.mixed()

        def trap(*args, **kwargs):
            raise AssertionError("interactive prompt loop entered in "
                                 "batch mode (W-E breach)")

        original = vr.collect_approvals
        vr.collect_approvals = trap
        try:
            code, _, err = run([path, "--close-only", "--apply"], keys=[])
        finally:
            vr.collect_approvals = original
        self.assertEqual(code, ERROR)           # EOF -> declined -> abort
        self.assertIn("declined", err)

    def test_T08_no_bypass_exists(self):
        """No --yes / --force / --non-interactive option is defined, and
        the only environment read in the module is the gate-run marker
        REFUSAL — an env var that blocks, never one that skips."""
        with open(vr.__file__, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        option_strings, environ_uses = [], 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and \
                    isinstance(node.func, ast.Attribute) and \
                    node.func.attr == "add_argument":
                for arg in node.args:
                    if isinstance(arg, ast.Constant):
                        option_strings.append(arg.value)
            if isinstance(node, ast.Attribute) and node.attr == "environ":
                environ_uses += 1
        for forbidden in ("--yes", "--force", "--non-interactive"):
            self.assertNotIn(forbidden, option_strings)
        self.assertEqual(environ_uses, 1)       # the W-F refusal, only

    def test_T09_verify_failure_is_skipped_and_named(self):
        """A close-only-classified candidate whose closure would create
        a duplicate D-number is skipped with the condition, not applied."""
        path = self.write("STATE.md", HEADER6 +
                          "".join(row6(100 + i) for i in range(12)) +
                          close_only_row(112) +
                          close_only_row(105) +      # dup of healthy D-105
                          row6(140))
        code, out, _ = run([path, "--close-only", "--apply"], keys=["y"])
        self.assertEqual(code, REPAIRS)
        self.assertIn("VERIFY FAILED ── D-105", out)
        self.assertIn("dupes D-105", out)
        content = raw(path)
        self.assertIn(b"| D-112 | 2026-01-01 | complete text | ACTIVE | "
                      b"D-050 |", content)             # applied
        self.assertIn(b"| D-105 | 2026-01-01 | complete text | ACTIVE | "
                      b"D-050\n", content)             # untouched

    def test_T10_mixed_run_counts_stated_not_derived(self):
        close = [str(200 + i) for i in range(12)]
        dupes = ["100", "101", "102"]               # will fail verify
        path = self.write("STATE.md", HEADER6 +
                          "".join(row6(100 + i) for i in range(40)) +
                          "".join(close_only_row(n) for n in close) +
                          "".join(close_only_row(n) for n in dupes) +
                          row6(300))
        code, out, _ = run([path, "--close-only", "--apply"], keys=["y"])
        self.assertEqual(code, REPAIRS)
        self.assertIn("verify_passed: 12", out)
        self.assertIn("verify_failed: 3", out)
        self.assertIn("applied: 12", out)
        self.assertIn("candidates_total: 15", out)
        self.assertIn("classified_close_only: 15", out)
        self.assertIn("classified_other: 0", out)

    def test_T11_backup_exists_and_verifies(self):
        path = self.mixed()
        original = raw(path)
        code, _, _ = run([path, "--close-only", "--apply"], keys=["y"])
        self.assertEqual(code, REPAIRS)
        backups = [f for f in os.listdir(self.dir) if f.endswith(".bak")]
        self.assertEqual(len(backups), 1)
        self.assertEqual(raw(os.path.join(self.dir, backups[0])), original)

    def test_T12_toctou_hash_mismatch_aborts(self):
        path = self.mixed()

        def mutate_then_yes(prompt):
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(row6(999))
            return "y"

        original = vr.read_key
        vr.read_key = mutate_then_yes
        out, err = io.StringIO(), io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = vr.main([path, "--close-only", "--apply"])
        finally:
            vr.read_key = original
        self.assertEqual(code, ERROR)
        self.assertIn("changed between classify and write", err.getvalue())
        self.assertIn(b"| ACTIVE | D-050\n", raw(path))   # unrepaired

    def test_T13_descending_order_in_batch(self):
        """Three close-only rows; every one must land on its own line —
        an ascending apply would drift (v1.0's proven failure)."""
        path = self.write("STATE.md", HEADER6 +
                          "".join(row6(100 + i) for i in range(12)) +
                          close_only_row(112, "first") +
                          close_only_row(113, "second") +
                          close_only_row(114, "third") + row6(140))
        code, out, _ = run([path, "--close-only", "--apply"], keys=["y"])
        self.assertEqual(code, REPAIRS)
        content = raw(path).decode("utf-8")
        for n, word in ((112, "first"), (113, "second"), (114, "third")):
            self.assertIn("| D-%d | 2026-01-01 | %s | ACTIVE | D-050 |"
                          % (n, word), content)
        self.assertIn("verified: broken count 3 -> 0", out)

    def test_T14_never_consumes_a_row_line_including_addendum(self):
        """Close-only consumes nothing by construction; the addendum
        row that follows must be byte-identical after apply."""
        addendum = "| D-112 addendum | 2026-01-02 | extra | ACTIVE | - |\n"
        path = self.write("STATE.md", HEADER6 +
                          "".join(row6(100 + i) for i in range(12)) +
                          close_only_row(112) + addendum + row6(140))
        code, _, _ = run([path, "--close-only", "--apply"], keys=["y"])
        self.assertEqual(code, REPAIRS)
        content = raw(path)
        self.assertIn(addendum.encode(), content)
        self.assertIn(b"| D-112 | 2026-01-01 | complete text | ACTIVE | "
                      b"D-050 |", content)

    def test_T15_byte_fidelity_in_batch(self):
        content = ("﻿" + HEADER6 +
                   row6(100, "kept — emoji 🎨") +
                   "prose with an\xa0NBSP inside\n" +
                   "".join(row6(101 + i) for i in range(11)) +
                   close_only_row(140) +
                   "| D-141 | 2026-01-01 | last | ACTIVE | - |")  # no \n
        crlf = content.replace("\n", "\r\n")
        path = self.write("STATE.md", crlf)
        before_lines = raw(path).split(b"\r\n")
        code, _, _ = run([path, "--close-only", "--apply"], keys=["y"])
        self.assertEqual(code, REPAIRS)
        after = raw(path)
        self.assertTrue(after.startswith(b"\xef\xbb\xbf"))       # BOM
        self.assertFalse(after.endswith(b"\n"))                  # no new EOL
        after_lines = after.split(b"\r\n")
        self.assertEqual(len(after_lines), len(before_lines))
        for line in after_lines:
            if line.startswith(b"| D-140"):
                self.assertTrue(line.endswith(b"|"))             # repaired,
                continue                                         # still CRLF
            self.assertIn(line, before_lines)                    # untouched

    def test_T16_staleness_warning_when_candidates_remain(self):
        path = self.mixed()          # 2 close-only + 1 multi-paragraph
        code, out, _ = run([path, "--close-only", "--apply"], keys=["y"])
        self.assertEqual(code, REPAIRS)
        self.assertIn("remain for the interactive path", out)
        self.assertIn("STALE", out)
        self.assertIn("Do not reuse this finding list", out)

    def test_T17_idempotence(self):
        path = self.write("STATE.md", HEADER6 +
                          "".join(row6(100 + i) for i in range(12)) +
                          close_only_row(112) + row6(140))
        run([path, "--close-only", "--apply"], keys=["y"])
        code, out, _ = run([path, "--close-only"])
        self.assertEqual(code, NOTHING)
        self.assertIn("no close-only candidates", out)

    def test_T18_receipt_carries_class_version_and_every_count(self):
        path = self.mixed()
        code, _, _ = run([path, "--close-only", "--apply"], keys=["y"])
        self.assertEqual(code, REPAIRS)
        receipts = os.path.join(self.dir, vr.RECEIPTS_NAME)
        with open(receipts, encoding="utf-8") as handle:
            receipt = json.loads(handle.readline())
        self.assertEqual(receipt["class_version"],
                         vr.CLOSE_ONLY_CLASS_VERSION)
        for field in ("candidates_total", "classified_close_only",
                      "classified_other", "verify_passed",
                      "verify_failed", "applied", "skipped"):
            self.assertIn(field, receipt["counts"])
        for field in ("run_id", "backup_path", "sha_before", "sha_after"):
            self.assertIn(field, receipt)

    def test_T19_gate_exclusion_proven_not_policy(self):
        import gate_run
        self.assertNotIn("vault_repair",
                         [e["name"] for e in gate_run.FLEET])
        with open(gate_run.__file__, encoding="utf-8") as handle:
            self.assertNotIn("vault_repair", handle.read())

    def test_T20_gate_run_marker_refuses_apply(self):
        path = self.mixed()
        before = raw(path)
        os.environ[vr.GATE_RUN_MARKER_ENV] = "1"
        self.addCleanup(os.environ.pop, vr.GATE_RUN_MARKER_ENV, None)
        code, _, err = run([path, "--close-only", "--apply"], keys=["y"])
        self.assertEqual(code, ERROR)
        self.assertIn(vr.GATE_RUN_MARKER_ENV, err)
        self.assertIn("never a gate stage", err)
        self.assertEqual(raw(path), before)
        code, _, err = run([path, "--apply"], keys=["y"])   # interactive too
        self.assertEqual(code, ERROR)
        self.assertEqual(raw(path), before)

    def test_T21_zero_candidates_exit_0_nothing_written(self):
        path = self.write("STATE.md", HEADER6 +
                          "".join(row6(100 + i) for i in range(12)) +
                          "| D-314 | 2026-01-01 | multi-paragraph\n"
                          "prose continues\n" + row6(140))
        listing = sorted(os.listdir(self.dir))
        code, out, _ = run([path, "--close-only"])
        self.assertEqual(code, NOTHING)
        self.assertIn("no close-only candidates", out)
        self.assertIn("NOT CLOSE-ONLY ── D-314", out)   # still reported
        self.assertEqual(sorted(os.listdir(self.dir)), listing)

    def test_T22_unknown_flag_is_exit_2(self):
        path = self.mixed()
        code, _, _ = run([path, "--close-only", "--frobnicate"])
        self.assertEqual(code, ERROR)

    def test_T23_v10_interactive_mode_unchanged(self):
        path = self.write("STATE.md", HEADER6 +
                          "".join(row6(100 + i) for i in range(12)) +
                          "| D-112 | 2026-01-01 | wrapped\n"
                          "text | ACTIVE | - |\n" + row6(140))
        code, out, _ = run([path])
        self.assertEqual(code, REPAIRS)
        self.assertIn("── PROPOSAL ──", out)            # v1.0 shape
        self.assertIn("VERDICT:", out)
        self.assertNotIn("CLOSE-ONLY", out)             # no v1.1 bleed
        self.assertNotIn("class v", out)

    def test_T24_dry_run_determinism_both_modes(self):
        path = self.mixed()
        self.assertEqual(run([path, "--close-only"]),
                         run([path, "--close-only"]))
        first = run([path, "--close-only", "--json"])
        second = run([path, "--close-only", "--json"])
        self.assertEqual(first, second)
        json.loads(first[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
