#!/usr/bin/env python3
"""Tests for pack_check.py — the pack gate.

pytest is specced across this repo but not installed here (flagged
deviation, D-394) — unittest-style, which pytest collects unchanged.

Most tests write a synthetic play_forge ledger rather than running
play_forge: this tool's job is to read a ledger and hash files, and a
4500x5400 render per test would cost minutes to prove nothing extra.
EndToEnd runs the real play_forge once and checks its real out_dir, so
the two tools cannot drift apart silently — a receipt-shape change in
play_forge fails here, not in the vault.
"""

import ast
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import pack_check as pc
import play_forge as pf
from test_play_forge import ForgeCase

CLEAN, FINDINGS, ERROR = pc.EXIT_CLEAN, pc.EXIT_FINDINGS, pc.EXIT_ERROR


def run(argv):
    """Invoke the CLI, capturing (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = pc.main(argv)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else ERROR
    return code, out.getvalue(), err.getvalue()


def tree_state(root):
    """Every file under root, with its sha256. The read-only sweep
    compares this before and after a run."""
    state = {}
    for base, _dirs, files in os.walk(root):
        for name in sorted(files):
            path = os.path.join(base, name)
            state[os.path.relpath(path, root)] = pc.hash_file(path)
    return state


class PackCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pack_check_test_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.pack = os.path.join(self.tmp, "pack")
        os.makedirs(self.pack)
        self.ledger = os.path.join(self.tmp, pf.RECEIPTS_NAME)

    def png(self, name, data=b"\x89PNG\r\n\x1a\nfake-render"):
        path = os.path.join(self.pack, name)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def write_ledger(self, receipts):
        with open(self.ledger, "w", encoding="utf-8") as handle:
            for receipt in receipts:
                handle.write(json.dumps(receipt, sort_keys=True) + "\n")

    def receipt(self, files, play_id="2026-09-06-test-play",
                completed="2026-09-06T10:00:00+00:00"):
        return {"tool": pf.TOOL_NAME, "play_id": play_id,
                "completed_utc": completed, "exit_code": 0,
                "renders": [{"variant": number, "file": name,
                             "sha256": pc.hash_file(
                                 os.path.join(self.pack, name))}
                            for number, name in files]}

    def run_tool(self, *flags):
        return run([self.pack, "--ledger", self.ledger, *flags])


class VerifiedPack(PackCase):
    def test_every_png_in_the_ledger_is_exit_0(self):
        self.png("variant_01.png")
        self.png("variant_02.png", b"\x89PNG\r\n\x1a\nsecond")
        self.write_ledger([self.receipt([(1, "variant_01.png"),
                                         (2, "variant_02.png")])])
        code, out, _ = self.run_tool()
        self.assertEqual(code, CLEAN)
        self.assertEqual(out.count(pc.VERDICT_VERIFIED), 2)
        self.assertIn("2026-09-06-test-play", out)
        self.assertIn("2026-09-06T10:00:00+00:00", out)

    def test_a_sha_found_in_any_receipt_counts(self):
        """The ledger is append-only and spans many runs — the match
        is against the whole file, not just the last line."""
        self.png("variant_01.png")
        old = self.receipt([(1, "variant_01.png")], play_id="older")
        self.png("variant_01.png", b"\x89PNG\r\n\x1a\nfake-render")
        self.write_ledger([old, {"tool": pf.TOOL_NAME,
                                 "play_id": "newer", "renders": []}])
        code, out, _ = self.run_tool()
        self.assertEqual(code, CLEAN)
        self.assertIn("older", out)

    def test_receipts_without_a_renders_list_are_simply_ignored(self):
        """Receipts written before play_forge recorded hashes have no
        renders key. That is not an error; it just proves nothing."""
        self.png("variant_01.png")
        good = self.receipt([(1, "variant_01.png")])
        self.write_ledger([{"tool": pf.TOOL_NAME, "play_id": "ancient",
                            "exit_code": 0}, good])
        self.assertEqual(self.run_tool()[0], CLEAN)


class HandEditedPng(PackCase):
    def test_one_changed_byte_is_not_a_forge_render(self):
        """The 2026-09-06 incident, as a mechanism: colour patched
        back into a rendered PNG makes it a different file, and the
        ledger has never seen it."""
        self.png("variant_01.png")
        self.write_ledger([self.receipt([(1, "variant_01.png")])])
        self.assertEqual(self.run_tool()[0], CLEAN)
        self.png("variant_01.png", b"\x89PNG\r\n\x1a\nfake-rendeX")
        code, out, _ = self.run_tool()
        self.assertEqual(code, FINDINGS)
        self.assertIn(pc.FINDING_NOT_A_RENDER, out)
        self.assertIn("variant_01.png", out)
        self.assertIn(pc.DOCTRINE, out)

    def test_a_stranger_png_is_named_by_file(self):
        self.png("variant_01.png")
        self.write_ledger([self.receipt([(1, "variant_01.png")])])
        self.png("someone_elses.png", b"\x89PNG\r\n\x1a\nnot ours")
        code, out, _ = self.run_tool()
        self.assertEqual(code, FINDINGS)
        self.assertIn("someone_elses.png", out)
        self.assertIn("variant_01.png: %s" % pc.VERDICT_VERIFIED, out)

    def test_findings_name_the_rule_and_the_hash(self):
        self.png("mystery.png", b"\x89PNG\r\n\x1a\nmystery")
        self.write_ledger([{"tool": pf.TOOL_NAME, "play_id": "p",
                            "renders": []}])
        report = pc.run_check(self.pack, self.ledger)
        self.assertEqual(len(report["findings"]), 1)
        finding = report["findings"][0]
        self.assertTrue(finding.startswith(pc.FINDING_NOT_A_RENDER))
        self.assertIn("mystery.png", finding)
        self.assertIn(report["checked"][0]["sha256"], finding)


class FailClosed(PackCase):
    def test_missing_ledger_is_exit_2(self):
        self.png("variant_01.png")
        code, _, err = self.run_tool()
        self.assertEqual(code, ERROR)
        self.assertIn("LEDGER_MISSING", err)

    def test_unreadable_ledger_is_exit_2_naming_the_line(self):
        self.png("variant_01.png")
        with open(self.ledger, "w", encoding="utf-8") as handle:
            handle.write('{"tool": "play_forge"}\nnot json at all\n')
        code, _, err = self.run_tool()
        self.assertEqual(code, ERROR)
        self.assertIn("LEDGER_UNREADABLE", err)
        self.assertIn("line 2", err)

    def test_missing_folder_is_exit_2(self):
        self.write_ledger([])
        code, _, err = run([os.path.join(self.tmp, "nope"),
                            "--ledger", self.ledger])
        self.assertEqual(code, ERROR)
        self.assertIn("FOLDER_MISSING", err)

    def test_a_folder_with_no_pngs_is_exit_2_not_a_pass(self):
        """A pack with nothing in it must never look like a clean
        pack. Fail closed."""
        self.write_ledger([])
        code, _, err = self.run_tool()
        self.assertEqual(code, ERROR)
        self.assertIn("EMPTY_PACK", err)

    def test_no_folder_argument_is_exit_2(self):
        code, _, err = run(["--ledger", self.ledger])
        self.assertEqual(code, ERROR)
        self.assertIn("usage", err)

    def test_unknown_flag_is_exit_2(self):
        with mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                pc.main([self.pack, "--bogus"])
        self.assertEqual(caught.exception.code, ERROR)

    def test_subfolders_are_not_walked(self):
        """Only PNGs DIRECTLY inside the pack. A working subfolder is
        not part of the pack, and must not raise findings about it."""
        self.png("variant_01.png")
        deep = os.path.join(self.pack, "scratch")
        os.makedirs(deep)
        with open(os.path.join(deep, "junk.png"), "wb") as handle:
            handle.write(b"\x89PNG\r\n\x1a\njunk")
        self.write_ledger([self.receipt([(1, "variant_01.png")])])
        code, out, _ = self.run_tool()
        self.assertEqual(code, CLEAN)
        self.assertNotIn("junk.png", out)


class ReadOnly(PackCase):
    def test_it_writes_nothing_anywhere(self):
        """vault_lint's guarantee, same shape: sweep every file under
        the temp root, hash them all, run the tool both clean and with
        findings, sweep again. Byte-identical, and no new file."""
        self.png("variant_01.png")
        self.png("stranger.png", b"\x89PNG\r\n\x1a\nstranger")
        self.write_ledger([self.receipt([(1, "variant_01.png")])])
        before = tree_state(self.tmp)
        self.assertEqual(self.run_tool()[0], FINDINGS)
        self.assertEqual(self.run_tool("--json")[0], FINDINGS)
        self.assertEqual(tree_state(self.tmp), before)

    def test_there_is_no_fix_flag_and_no_write_call(self):
        """Section 4: the docstring saying "read-only" is prose. This
        walks the SYNTAX TREE — every open() must be a read mode, no
        filesystem-mutating call may appear, and no argument may be
        named --fix. A grep would have matched the docstring sentence
        that says there is no --fix flag; this cannot."""
        with open(pc.__file__, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        banned = {("os", "makedirs"), ("os", "mkdir"), ("os", "remove"),
                  ("os", "replace"), ("os", "rename"), ("os", "unlink"),
                  ("shutil", "copy"), ("shutil", "copy2"),
                  ("shutil", "move"), ("shutil", "rmtree")}
        opens = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) \
                    and isinstance(node.value, str):
                self.assertNotEqual(node.value, "--fix")
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) \
                    and isinstance(func.value, ast.Name):
                self.assertNotIn((func.value.id, func.attr), banned,
                                 "%s.%s writes; this tool is read-only"
                                 % (func.value.id, func.attr))
            if isinstance(func, ast.Name) and func.id == "open":
                opens += 1
                mode = None
                if len(node.args) > 1:
                    mode = node.args[1].value
                for keyword in node.keywords:
                    if keyword.arg == "mode":
                        mode = keyword.value.value
                self.assertIn(mode, (None, "r", "rb"),
                              "open(mode=%r) is a write" % mode)
        self.assertGreater(opens, 0)      # the scan actually ran


class JsonParity(PackCase):
    def test_human_and_json_come_from_one_dict(self):
        self.png("variant_01.png")
        self.png("stranger.png", b"\x89PNG\r\n\x1a\nstranger")
        self.write_ledger([self.receipt([(1, "variant_01.png")])])
        report = pc.run_check(self.pack, self.ledger)
        code, out, _ = self.run_tool("--json")
        self.assertEqual(code, FINDINGS)
        payload = json.loads(out)
        payload.pop("folder"), report.pop("folder")
        payload.pop("ledger"), report.pop("ledger")
        self.assertEqual(payload, report)

    def test_json_is_deterministic(self):
        self.png("variant_01.png")
        self.write_ledger([self.receipt([(1, "variant_01.png")])])
        first = self.run_tool("--json")[1]
        second = self.run_tool("--json")[1]
        self.assertEqual(first, second)

    def test_explain_states_the_doctrine_line(self):
        code, out, _ = run(["--explain"])
        self.assertEqual(code, CLEAN)
        self.assertIn(pc.DOCTRINE, out)


class CrashFloor(PackCase):
    def test_uncaught_exception_is_exit_2_not_1(self):
        self.png("variant_01.png")
        self.write_ledger([self.receipt([(1, "variant_01.png")])])
        with mock.patch.object(pc, "run_check",
                               side_effect=RuntimeError("injected")):
            code, out, err = self.run_tool()
        self.assertEqual(code, ERROR)
        self.assertIn("CRASH (RuntimeError): injected", err)
        self.assertEqual(out, "")

    def test_crash_json_parity(self):
        self.png("variant_01.png")
        self.write_ledger([self.receipt([(1, "variant_01.png")])])
        with mock.patch.object(pc, "run_check",
                               side_effect=RuntimeError("injected")):
            code, out, _ = self.run_tool("--json")
        self.assertEqual(code, ERROR)
        payload = json.loads(out)
        self.assertEqual(payload["verdict"], "CRASH")
        self.assertEqual(payload["exit_code"], ERROR)


class LedgerLocation(PackCase):
    def test_the_default_ledger_is_play_forges_own(self):
        """Imported, never restated — a duplicated constant drifts."""
        self.assertEqual(pc.default_ledger(),
                         os.path.join(str(pf.BASE_DIR),
                                      pf.RECEIPTS_NAME))

    def test_a_missing_play_forge_refuses_dep_missing(self):
        self.png("variant_01.png")
        with mock.patch.object(pc, "FLEET_IMPORT_ERROR",
                               "ModuleNotFoundError: No module named "
                               "'PIL'"):
            code, _, err = self.run_tool()
        self.assertEqual(code, ERROR)
        self.assertIn("DEP_MISSING", err)


class EndToEnd(ForgeCase):
    """The two tools, wired together for real. Borrows play_forge's own
    fixture (fonts, index, sidecar, config) rather than rebuilding it —
    Section 7: reuse what exists."""

    def test_a_real_forge_out_dir_verifies_its_variants(self):
        code, _, _ = self.run_tool(self.write_play())
        self.assertIn(code, (0, 1))
        ledger = os.path.join(self.tmp, pf.RECEIPTS_NAME)
        report = pc.run_check(self.play_out(), ledger)
        by_file = {item["file"]: item for item in report["checked"]}
        for number in (1, 2):
            for fmt in (pf.FULL_NAME_FMT, pf.SQUINT_NAME_FMT):
                item = by_file[fmt % number]
                self.assertEqual(item["verdict"], pc.VERDICT_VERIFIED)
                self.assertEqual(item["play_id"],
                                 "2026-09-02-test-play")

    def test_the_contact_sheets_are_not_in_the_ledger(self):
        """FLAGGED, not fixed: play_forge writes contact_fulls.png and
        contact_squints.png into the same out_dir but does NOT list
        them in renders[], so a raw out_dir is never exit 0. A PACK is
        a curated folder of chosen variants; this test pins the real
        behaviour so it cannot surprise anyone later."""
        self.assertIn(self.run_tool(self.write_play())[0], (0, 1))
        ledger = os.path.join(self.tmp, pf.RECEIPTS_NAME)
        report = pc.run_check(self.play_out(), ledger)
        unverified = {item["file"] for item in report["checked"]
                      if item["verdict"] == pc.FINDING_NOT_A_RENDER}
        self.assertEqual(unverified, {pf.CONTACT_FULLS_NAME,
                                      pf.CONTACT_SQUINTS_NAME})
        self.assertEqual(report["exit_code"], pc.EXIT_FINDINGS)

    def test_a_curated_pack_of_chosen_variants_is_exit_0(self):
        """What a pack actually is: copy the chosen renders out, run
        the gate on that."""
        self.assertIn(self.run_tool(self.write_play())[0], (0, 1))
        pack = os.path.join(self.tmp, "pack")
        os.makedirs(pack)
        for number in (1, 2):
            name = pf.FULL_NAME_FMT % number
            shutil.copy(os.path.join(self.play_out(), name),
                        os.path.join(pack, name))
        ledger = os.path.join(self.tmp, pf.RECEIPTS_NAME)
        self.assertEqual(pc.run_check(pack, ledger)["exit_code"],
                         pc.EXIT_CLEAN)


if __name__ == "__main__":
    unittest.main()
