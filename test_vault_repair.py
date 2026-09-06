#!/usr/bin/env python3
"""Test suite for vault_repair.py — stdlib unittest, temp-dir fixtures.

Tests 1-9 are the original set; 10-27 each encode a PROVEN failure from
the PM FORGE war-game (splitlines over-splitting, ascending-apply
corruption, healthy-row erasure, CRLF/BOM/no-final-newline mangling,
line-shifted verification false positives), not a hypothetical.
"""

import ast
import hashlib
import io
import json
import os
import shutil
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import vault_lint as vl
import vault_repair as vr

NOTHING, REPAIRS, ERROR = vr.EXIT_NOTHING, vr.EXIT_REPAIRS, vr.EXIT_ERROR

HEADER = (
    "# STATE\n"
    "\n"
    "| ID | Date | Decision | Status |\n"
    "|----|------|----------|--------|\n"
)


def row(n, text="Did a thing", status="FILED", date="2026-01-01"):
    return "| D-%s | %s | %s | %s |\n" % (n, date, text, status)


def broken_row(n, head="wrapped", tail="text | FILED |", date="2026-01-05"):
    """An unclosed row plus its continuation — two physical lines."""
    return "| D-%s | %s | %s\n%s\n" % (n, date, head, tail)


def run(argv, keys=None):
    """Invoke the CLI; `keys` scripts the [y/n/a/q] prompt."""
    script = list(keys or [])

    def scripted(prompt):
        if not script:
            raise EOFError
        item = script.pop(0)
        if isinstance(item, BaseException) or (
                isinstance(item, type) and issubclass(item, BaseException)):
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
        self.dir = tempfile.mkdtemp(prefix="vault_repair_test_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def write(self, name, text, newline=""):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8", newline=newline) as handle:
            handle.write(text)
        return path

    def write_bytes(self, name, data):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def standard(self, name="STATE.md", extra=""):
        return self.write(name, HEADER + row(100) + row(101) +
                          broken_row(105) + row(106) + extra)


# ── 1-9: the original set ──────────────────────────────────────────────

class TestOriginal(Fixture):

    def test_01_dry_run_is_provably_write_free(self):
        path = self.standard()
        before_hash, before_mtime = sha(path), os.path.getmtime(path)
        listing = sorted(os.listdir(self.dir))
        code, out, _ = run([path])
        self.assertEqual(code, REPAIRS)
        self.assertIn("PROPOSAL", out)
        self.assertEqual(sha(path), before_hash)
        self.assertEqual(os.path.getmtime(path), before_mtime)
        self.assertEqual(sorted(os.listdir(self.dir)), listing)  # no backup, no temp, nothing

    def test_02_apply_fixes_and_backup_verifies(self):
        path = self.standard()
        original = raw(path)
        code, out, _ = run([path, "--apply"], keys=["y"])
        self.assertEqual(code, REPAIRS)
        self.assertIn("applied 1 of 1", out)
        with open(path, "r", encoding="utf-8") as handle:
            self.assertIn("| D-105 | 2026-01-05 | wrapped text | FILED |",
                          handle.read())
        backups = [n for n in os.listdir(self.dir) if n.endswith(".bak")]
        self.assertEqual(len(backups), 1)
        self.assertEqual(raw(os.path.join(self.dir, backups[0])), original)

    def test_03_hash_mismatch_aborts_before_write(self):
        path = self.standard()

        def mutate_then_yes(prompt):
            with open(path, "a", encoding="utf-8") as handle:
                handle.write("| D-200 | x | y | FILED |\n")
            return "y"

        original_key = vr.read_key
        vr.read_key = mutate_then_yes
        out, err = io.StringIO(), io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = vr.main([path, "--apply"])
        finally:
            vr.read_key = original_key
        self.assertEqual(code, ERROR)
        self.assertIn("changed between scan and write", err.getvalue())
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("| D-105 | 2026-01-05 | wrapped\n", content)  # unrepaired
        self.assertEqual([n for n in os.listdir(self.dir)
                          if n.endswith(".bak")], [])

    def test_04_ambiguous_is_skipped_with_reason_not_failed(self):
        path = self.write("STATE.md", HEADER + row(100) + row(101) +
                          "| D-105 | 2026-01-05 | wrapped\n" +
                          row(106) + row(107))     # next line is a row
        code, out, _ = run([path])
        self.assertEqual(code, NOTHING)             # nothing proposable
        self.assertIn("SKIPPED", out)
        self.assertIn("W6", out)
        self.assertIn("merge two decisions", out)

    def test_05_idempotency(self):
        path = self.standard()
        run([path, "--apply"], keys=["y"])
        code, out, _ = run([path])
        self.assertEqual(code, NOTHING)
        self.assertIn("nothing to repair", out)
        code, _, _ = run([path, "--apply"], keys=[])
        self.assertEqual(code, NOTHING)

    def test_06_round_trip_fidelity(self):
        """CRLF + emoji + NBSP in prose; only the broken rows differ,
        every other line byte-identical."""
        content = (HEADER + row(100, "kept — with emoji 🎨") +
                   "prose with an\xa0NBSP inside\n" +
                   broken_row(105) + row(106, "café row"))
        crlf = content.replace("\n", "\r\n")
        path = self.write("STATE.md", crlf)
        before_lines = raw(path).split(b"\n")
        code, _, _ = run([path, "--apply"], keys=["y"])
        self.assertEqual(code, REPAIRS)
        after_lines = raw(path).split(b"\n")
        self.assertEqual(len(after_lines), len(before_lines) - 1)
        touched = "| D-105"
        for line in after_lines:
            if line.startswith(touched.encode()):
                continue
            self.assertIn(line, before_lines)       # untouched = identical

    def test_07_invalid_utf8_aborts_with_offset(self):
        data = (HEADER + row(100)).encode() + b"| D-101 | caf\xe9 | x | F |\n"
        path = self.write_bytes("STATE.md", data)
        before = raw(path)
        code, _, err = run([path])
        self.assertEqual(code, ERROR)
        self.assertIn("not valid UTF-8", err)
        self.assertIn("offset", err)
        self.assertIn("line 6", err)
        self.assertEqual(raw(path), before)

    def test_08_applied_file_passes_vault_lint_for_broken(self):
        path = self.standard()
        run([path, "--apply"], keys=["y"])
        scan = vl.scan_file(path)
        with open(path, encoding="utf-8") as fh:
            det = vl.detect(fh.readlines())
        self.assertEqual([f for f in det["findings"]
                          if f["check"] == "broken"], [])

    def test_09_interrupt_safety_original_never_half_written(self):
        """A crash at the replace boundary leaves the original intact —
        the temp+rename design means there is no half-written state."""
        path = self.standard()
        before = raw(path)
        original_replace = os.replace

        def exploding_replace(src, dst):
            raise OSError("simulated crash at the rename")

        os.replace = exploding_replace
        try:
            code, _, err = run([path, "--apply"], keys=["y"])
        finally:
            os.replace = original_replace
        self.assertEqual(code, ERROR)
        self.assertEqual(raw(path), before)
        self.assertEqual([n for n in os.listdir(self.dir)
                          if ".tmp" in n], [])      # temp cleaned up


# ── 10-27: proven failures, closed ─────────────────────────────────────

class TestWarGame(Fixture):

    def test_10_u2028_never_shifts_a_repair(self):
        """VERIFIED: bare splitlines() turns 3 newlines into 4 lines —
        one U+2028 shifts every later line number and the repair lands
        on the wrong row; re-joining converts it to a real newline."""
        content = (HEADER + row(100) +
                   "prose with a line separator inside\n" +
                   broken_row(105) + row(106))
        path = self.write("STATE.md", content)
        code, _, _ = run([path, "--apply"], keys=["y"])
        self.assertEqual(code, REPAIRS)
        after = raw(path)
        self.assertIn(" ".encode("utf-8"), after)      # byte survives
        self.assertIn(b"| D-105 | 2026-01-05 | wrapped text | FILED |",
                      after)                                 # right row fixed
        self.assertIn(b"prose with\xe2\x80\xa8a line separator inside\n",
                      after)

    def test_11_descending_apply_fixes_all_three(self):
        """VERIFIED war-game result for ten lines with repairs at
        (3,4), (6,7), (9,10):
          ascending:  ['L1','L2','L3 L4','L5','L6','L7 L8','L9','L10']
                      — repair #2 joined the WRONG pair, #3 IndexError'd
          descending: ['L1','L2','L3 L4','L5','L6 L7','L8','L9 L10']
        Three broken rows in one file must all join correctly."""
        path = self.write("STATE.md", HEADER + row(100) +
                          broken_row(101, "first") +
                          broken_row(102, "second") +
                          broken_row(103, "third") + row(104))
        code, out, _ = run([path, "--apply"], keys=["a"])
        self.assertEqual(code, REPAIRS)
        self.assertIn("applied 3 of 3", out)
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        for n, word in ((101, "first"), (102, "second"), (103, "third")):
            self.assertIn("| D-%d | 2026-01-05 | %s text | FILED |"
                          % (n, word), content)

    def test_12_healthy_row_is_never_consumed(self):
        """VERIFIED: naive rejoin merges two decisions and ERASES one."""
        path = self.write("STATE.md", HEADER + row(100) +
                          "| D-105 | 2026-01-05 | broken and continues\n" +
                          row(106, "a HEALTHY row") + row(107))
        before_106 = row(106, "a HEALTHY row").encode()
        code, out, _ = run([path, "--apply"], keys=["a"])
        self.assertIn("SKIPPED", out)
        self.assertIn("W6", out)
        self.assertIn(before_106.rstrip(b"\n"), raw(path))   # untouched

    def test_13_crlf_round_trip_and_repaired_terminator(self):
        """VERIFIED: default text mode converts every CRLF to LF. Also
        rider 3: the repaired row carries the terminator of the LAST
        consumed continuation line — still \\r\\n in a CRLF file."""
        content = (HEADER + row(100) + broken_row(105) + row(106)
                   ).replace("\n", "\r\n")
        path = self.write("STATE.md", content)
        code, _, _ = run([path, "--apply"], keys=["y"])
        self.assertEqual(code, REPAIRS)
        after = raw(path)
        self.assertNotIn(b"\n\n", after.replace(b"\r\n", b""))  # sanity
        for line in after.split(b"\r\n")[:-1]:
            self.assertNotIn(b"\n", line)            # every line CRLF
        self.assertIn(b"| D-105 | 2026-01-05 | wrapped text | FILED |\r\n",
                      after)

    def test_14_bom_survives(self):
        """VERIFIED: utf-8-sig strips the BOM and write-back deletes it."""
        content = "﻿" + HEADER + row(100) + broken_row(105) + row(106)
        path = self.write("STATE.md", content)
        code, _, _ = run([path, "--apply"], keys=["y"])
        self.assertEqual(code, REPAIRS)
        self.assertTrue(raw(path).startswith(b"\xef\xbb\xbf"))

    def test_15_no_final_newline_none_added(self):
        content = HEADER + row(100) + broken_row(105) + \
            "| D-106 | 2026-01-06 | last | FILED |"       # no trailing \n
        path = self.write("STATE.md", content)
        code, _, _ = run([path, "--apply"], keys=["y"])
        self.assertEqual(code, REPAIRS)
        self.assertFalse(raw(path).endswith(b"\n"))

    def test_15b_broken_row_at_eof_keeps_missing_newline(self):
        content = HEADER + row(100) + \
            "| D-105 | 2026-01-05 | wrapped\ntext | FILED |"  # EOF, no \n
        path = self.write("STATE.md", content)
        code, _, _ = run([path, "--apply"], keys=["y"])
        self.assertEqual(code, REPAIRS)
        after = raw(path)
        self.assertTrue(after.endswith(b"| D-105 | 2026-01-05 | wrapped "
                                       b"text | FILED |"))
        self.assertFalse(after.endswith(b"\n"))

    def test_16_verification_compares_by_identity_not_line(self):
        """VERIFIED: every repair removes a line, so a (check, line)
        diff reports unchanged downstream findings as brand new and the
        verification would scream on a perfect repair. A ghost and a
        dupe below the repair shift lines but are NOT new."""
        path = self.write("STATE.md", HEADER + row(100) +
                          broken_row(105) +
                          row(200, "dupe A") + row(200, "dupe B") +
                          "\nSee D-999 for the ghost.\n")
        code, out, _ = run([path, "--apply"], keys=["y"])
        self.assertEqual(code, REPAIRS)
        self.assertIn("0 new findings by identity", out)
        self.assertNotIn("VERIFICATION FAILED", out)

    def test_17_json_plus_apply_refused(self):
        path = self.standard()
        before = raw(path)
        code, out, _ = run([path, "--json", "--apply"], keys=["y"])
        self.assertEqual(code, ERROR)
        payload = json.loads(out)          # error arrives as JSON, stdout
        self.assertEqual(payload["exit_code"], ERROR)
        self.assertIn("W3", payload["error"])
        self.assertIn("Nothing was written", payload["error"])
        self.assertEqual(raw(path), before)
        self.assertEqual([n for n in os.listdir(self.dir)
                          if n.endswith(".bak")], [])

    def test_17b_no_yes_or_force_flag_exists(self):
        help_text = vr.build_parser().format_help()
        for forbidden in ("--yes", "--force", "--batch"):
            self.assertNotIn(forbidden, help_text)
        code, _, _ = run([self.standard(), "--yes"])
        self.assertEqual(code, ERROR)                # unknown flag, exit 2

    def test_18_a_cannot_approve_an_ambiguous_candidate(self):
        """'a' applies only candidates already on the repairable list —
        the ambiguous row was filtered in Section 2 and the prompt loop
        never sees it."""
        path = self.write("STATE.md", HEADER + row(100) +
                          broken_row(101, "fixable one") +
                          "| D-102 | 2026-01-05 | ambiguous\n" +
                          row(103, "healthy follower") +
                          broken_row(104, "fixable two") + row(106))
        code, out, _ = run([path, "--apply"], keys=["a"])
        self.assertEqual(code, REPAIRS)
        self.assertIn("applied 2 of 2", out)
        self.assertIn("SKIPPED ── D-102", out)
        content = raw(path)
        self.assertIn(b"| D-102 | 2026-01-05 | ambiguous\n", content)  # untouched

    def test_19_q_and_eof_write_nothing(self):
        path = self.standard()
        before = raw(path)
        code, out, _ = run([path, "--apply"], keys=["q"])
        self.assertEqual(code, REPAIRS)              # proposed, none applied
        self.assertIn("0 of 1 applied — nothing written", out)
        self.assertEqual(raw(path), before)
        code, _, _ = run([path, "--apply"], keys=[])          # EOF
        self.assertEqual(raw(path), before)
        code, _, _ = run([path, "--apply"], keys=[KeyboardInterrupt])
        self.assertEqual(raw(path), before)
        self.assertEqual([n for n in os.listdir(self.dir)
                          if n.endswith(".bak")], [])

    def test_20_dry_verify_refuses_a_bad_proposal_before_any_write(self):
        """A rejoin that would create a duplicate D-number is refused
        BEFORE any write — the post-apply verification is a second net,
        not the only one."""
        path = self.write("STATE.md", HEADER +
                          row(100, "the original D-100") + row(101) +
                          "| D-100\n"
                          "| 2026-01-05 | imposter | FILED |\n" + row(102))
        before = raw(path)
        code, out, _ = run([path])
        self.assertEqual(code, NOTHING)              # nothing proposable
        self.assertIn("would create new finding", out)
        self.assertIn("dupes D-100", out)
        self.assertIn("refused before any write", out)
        self.assertEqual(raw(path), before)

    def test_21_backup_collision_aborts(self):
        path = self.standard()
        before = raw(path)
        original_stamp = vr._backup_stamp
        vr._backup_stamp = lambda: "FIXEDSTAMP"
        self.addCleanup(setattr, vr, "_backup_stamp", original_stamp)
        collision = path + vr.BACKUP_SUFFIX % "FIXEDSTAMP"
        with open(collision, "w") as handle:
            handle.write("pre-existing backup")
        code, _, err = run([path, "--apply"], keys=["y"])
        self.assertEqual(code, ERROR)
        self.assertIn("refusing to overwrite an existing backup", err)
        self.assertEqual(raw(path), before)
        with open(collision) as handle:
            self.assertEqual(handle.read(), "pre-existing backup")

    def test_22_temp_file_lives_in_the_targets_directory(self):
        path = self.standard()
        seen = {}
        original_replace = os.replace

        def recording_replace(src, dst):
            seen["src_dir"] = os.path.dirname(os.path.abspath(src))
            seen["dst_dir"] = os.path.dirname(os.path.abspath(dst))
            return original_replace(src, dst)

        os.replace = recording_replace
        try:
            code, _, _ = run([path, "--apply"], keys=["y"])
        finally:
            os.replace = original_replace
        self.assertEqual(code, REPAIRS)
        self.assertEqual(seen["src_dir"], seen["dst_dir"])
        self.assertEqual(seen["src_dir"], self.dir)
        self.assertNotEqual(seen["src_dir"], tempfile.gettempdir())

    def test_23_mode_survives_the_replace(self):
        """Without the explicit stat copy the file inherits the TEMP
        file's mode after os.replace."""
        path = self.standard()
        os.chmod(path, 0o600)
        code, _, _ = run([path, "--apply"], keys=["y"])
        self.assertEqual(code, REPAIRS)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_24_multi_line_runs_and_the_cap(self):
        path = self.write("STATE.md", HEADER + row(100) +
                          "| D-105 | 2026-01-05 | wrapped\n"
                          "across two\n"
                          "lines | FILED |\n" + row(106))
        code, out, _ = run([path, "--apply"], keys=["y"])
        self.assertEqual(code, REPAIRS)
        self.assertIn(b"| D-105 | 2026-01-05 | wrapped across two lines "
                      b"| FILED |", raw(path))

        path2 = self.write("LONG.md", HEADER + row(100) +
                           "| D-105 | 2026-01-05 | wrapped\n"
                           "one\ntwo\nthree\nfour | FILED |\n" + row(106))
        code, out, _ = run([path2])
        self.assertEqual(code, NOTHING)
        self.assertIn("MAX_CONTINUATION_LINES", out)

    def test_25_symlink_is_refused_and_survives(self):
        real = self.standard("real.md")
        link = os.path.join(self.dir, "STATE.md")
        os.symlink(real, link)
        code, _, err = run([link, "--apply"], keys=["y"])
        self.assertEqual(code, ERROR)
        self.assertIn("symlink", err)
        self.assertIn("real path", err)
        self.assertTrue(os.path.islink(link))        # not replaced

    def test_26_partial_apply(self):
        # A healthy majority keeps vault_lint's own column-shape stats
        # confident: with 5 broken and only 1 healthy row, the dominant
        # shape degenerates mid-trial and dry-verify (correctly)
        # refuses every candidate.
        path = self.write("STATE.md", HEADER +
                          "".join(row(71 + i) for i in range(25)) +
                          "".join(broken_row(101 + i, "part%d" % i)
                                  for i in range(5)) + row(200))
        before = raw(path)
        code, out, _ = run([path, "--apply"], keys=["y", "y", "q"])
        self.assertEqual(code, REPAIRS)
        self.assertIn("applied: 2 | declined: 3", out)
        self.assertIn("applied 2 of 5", out)
        after = raw(path)
        for i in (2, 3, 4):                          # unapplied: untouched
            self.assertIn(("| D-%d | 2026-01-05 | part%d\n"
                           % (101 + i, i)).encode(), after)

    def test_27_determinism_dry_run_both_modes(self):
        path = self.standard()
        self.assertEqual(run([path]), run([path]))
        first = run([path, "--json"])
        second = run([path, "--json"])
        self.assertEqual(first, second)
        json.loads(first[1])                          # parses


class TestSourceDiscipline(Fixture):

    def test_no_bare_splitlines_and_strict_reads(self):
        """W5 asserted at the source level: no .splitlines() call
        anywhere in vault_repair; no errors='replace'; every text open
        passes newline=''."""
        with open(vr.__file__, encoding="utf-8") as handle:
            source = handle.read()
        tree = ast.parse(source)
        opens_without_newline = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and \
                        func.attr == "splitlines":
                    self.fail("bare splitlines() call found (W5)")
                if isinstance(func, ast.Name) and func.id == "open":
                    kwargs = {k.arg: k for k in node.keywords}
                    modes = [a.value for a in node.args[1:2]
                             if isinstance(a, ast.Constant)]
                    mode = kwargs.get("mode")
                    if mode is not None and isinstance(mode.value, ast.Constant):
                        modes.append(mode.value.value)
                    mode_str = modes[0] if modes else "r"
                    if "b" in mode_str:
                        continue
                    if "newline" not in kwargs:
                        opens_without_newline.append(ast.dump(func))
        self.assertEqual(opens_without_newline, [])
        # utf-8-sig may be MENTIONED in docs (the institutional memory);
        # it must never be an encoding argument.
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and \
                    isinstance(node.func, ast.Name) and \
                    node.func.id == "open":
                for kw in node.keywords:
                    if kw.arg == "encoding" and \
                            isinstance(kw.value, ast.Constant):
                        self.assertEqual(kw.value.value, "utf-8")
                    if kw.arg == "errors" and \
                            isinstance(kw.value, ast.Constant):
                        self.assertEqual(kw.value.value, "strict")
        self.assertIn('errors="strict"', source)
        self.assertIn("os.replace", source)
        self.assertNotIn("os.rename(", source)
        self.assertIn("NEVER str.splitlines()", source)   # the comment survives

    def test_split_lines_keepends_contract(self):
        """Rider 2: breaks ONLY on \\n with keepends; \\r before \\n
        stays attached; U+2028 never splits; no-final-newline preserved;
        join is the exact inverse."""
        cases = [
            "a\r\nb\r\nc\r\n",                    # CRLF
            "a\rstill same line\nb\n",            # lone \r inside a line
            "one logical line\ntwo\n",       # U+2028
            "no final newline",                   # no trailing \n
            "",                                    # empty
            "\n\n",                                # blank lines
        ]
        for content in cases:
            lines = vr.split_lines_keepends(content)
            self.assertEqual("".join(lines), content, repr(content))
            for line in lines[:-1]:
                self.assertTrue(line.endswith("\n"), repr(line))
            self.assertEqual(
                len(lines), content.count("\n") +
                (0 if content.endswith("\n") or content == "" else 1),
                repr(content))
        self.assertEqual(vr.split_lines_keepends("a\r\nb\r\n"),
                         ["a\r\n", "b\r\n"])
        self.assertEqual(vr.split_lines_keepends("x y\n"), ["x y\n"])

    def test_explain_and_unknown_flag(self):
        code, out, _ = run(["--explain"])
        self.assertEqual(code, NOTHING)
        for wall in ("W1", "W5", "W6", "W7", "W10", "identity"):
            self.assertIn(wall, out)
        code, _, _ = run(["--frobnicate"])
        self.assertEqual(code, ERROR)

    def test_backup_dir_option(self):
        path = self.standard()
        alt = os.path.join(self.dir, "backups")
        os.makedirs(alt)
        code, out, _ = run([path, "--apply", "--backup-dir", alt],
                           keys=["y"])
        self.assertEqual(code, REPAIRS)
        self.assertTrue([n for n in os.listdir(alt) if n.endswith(".bak")])
        code, _, err = run([path, "--backup-dir",
                            os.path.join(self.dir, "missing")])
        self.assertEqual(code, ERROR)


# ── Windows console-encoding fix (STATE.md D-378 class) ────────────────

class TestCrashFloor(Fixture):
    """Fleet crash floor: a Python traceback exits 1, which this tool's
    contract reads as "proposed / applied". Exit 2 is what tells a
    wrapper the tool broke instead. The CRASH receipt obeys the v1.0
    wall — dry-run writes nothing, ever."""

    def test_dry_run_crash_is_exit_2_and_writes_nothing(self):
        path = self.standard()
        before, listing = sha(path), sorted(os.listdir(self.dir))
        with mock.patch.object(vr, "read_strict",
                               side_effect=RuntimeError("injected")):
            code, out, err = run([path])
        self.assertEqual(code, ERROR)
        self.assertIn("CRASH (RuntimeError): injected", err)
        self.assertEqual(sha(path), before)
        self.assertEqual(sorted(os.listdir(self.dir)), listing)
        self.assertNotIn(vr.RECEIPTS_NAME, listing)

    def test_close_only_apply_crash_leaves_a_crash_receipt(self):
        path = self.standard()
        with mock.patch.object(vr, "run_close_only",
                               side_effect=RuntimeError("injected")):
            code, out, err = run([path, "--close-only", "--apply"])
        self.assertEqual(code, ERROR)
        self.assertIn("CRASH (RuntimeError): injected", err)
        receipts = os.path.join(self.dir, vr.RECEIPTS_NAME)
        with open(receipts, encoding="utf-8") as handle:
            lines = [json.loads(line) for line in handle if line.strip()]
        self.assertEqual(lines[-1]["kind"], "CRASH")
        self.assertEqual(lines[-1]["exit_code"], ERROR)
        self.assertIn("RuntimeError: injected", lines[-1]["reason"])

    def test_close_only_without_apply_is_a_dry_run_and_writes_nothing(self):
        """Fable bench: --close-only is a MODE, --apply is the
        PERMISSION. run_close_only returns at its own "if not
        args.apply" before the receipt block, so this mode has never
        written the ledger and a crash in it must not either."""
        path = self.standard()
        before, listing = sha(path), sorted(os.listdir(self.dir))
        with mock.patch.object(vr, "run_close_only",
                               side_effect=RuntimeError("injected")):
            code, out, err = run([path, "--close-only", "--json"])
        self.assertEqual(code, ERROR)
        self.assertFalse(json.loads(out)["receipt_written"])
        self.assertEqual(sha(path), before)
        self.assertEqual(sorted(os.listdir(self.dir)), listing)
        self.assertNotIn(vr.RECEIPTS_NAME, os.listdir(self.dir))

    def test_crash_json_parity_reports_receipt_written(self):
        path = self.standard()
        with mock.patch.object(vr, "read_strict",
                               side_effect=RuntimeError("injected")):
            code, out, _ = run([path, "--json"])
        self.assertEqual(code, ERROR)
        payload = json.loads(out)
        self.assertEqual(payload["verdict"], "CRASH")
        self.assertEqual(payload["exit_code"], ERROR)
        self.assertFalse(payload["receipt_written"])


class TestConsoleEncoding(Fixture):
    """vault_repair.py carries the identical UnicodeEncodeError risk
    vault_lint.py hit on a real Windows cp1252 console (STATE.md D-378
    class) -- same ══ VAULT REPAIR ══ banner shape, same crash waiting
    to happen the first time this tool runs natively. Fixed pre-emptively
    here, same session, so the two tools stay in agreement (the standing
    rule that they must -- vault_lint and vault_repair share ROW_PATTERN
    detection for the same reason). These tests exist because the fix
    itself is a way this suite could quietly stop testing anything:
    every test above runs main() under redirect_stdout(io.StringIO()),
    and io.StringIO has no .reconfigure -- a careless fix would have
    broken the whole suite the instant it landed.
    """

    def test_reconfigure_is_a_noop_on_a_plain_stringio(self):
        """io.StringIO has no .reconfigure -- the same shape every test
        above's own run() helper swaps in. If this raised, the whole
        suite would already be red; this names the reason it isn't."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            vr._ensure_utf8_console()  # must not raise AttributeError

    def test_reconfigure_is_called_with_utf8_replace_when_supported(self):
        """When the stream DOES support .reconfigure (the real case on
        a live console), confirm the fix calls it with the right args --
        not just that it's safe to call when it's absent."""
        calls = []

        class FakeStream:
            def reconfigure(self, **kwargs):
                calls.append(kwargs)

        with redirect_stdout(FakeStream()), redirect_stderr(FakeStream()):
            vr._ensure_utf8_console()
        self.assertEqual(calls, [{"encoding": "utf-8", "errors": "replace"}] * 2)

    def test_report_banner_survives_the_fix(self):
        """The exact crash-site shape: a dry-run report prints the
        ══ VAULT REPAIR ══ banner through render_report(). Confirms it
        still comes through whole post-fix."""
        path = self.standard()
        code, out, _ = run([path])
        self.assertEqual(code, REPAIRS, out)
        self.assertIn("VAULT REPAIR", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
