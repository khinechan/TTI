#!/usr/bin/env python3
"""Test suite for thumb_check.py — unittest, Pillow-generated fixtures.

Every fixture is generated in a temp dir; no real art is required and
nothing is written outside the temp dir. Tests 1-14 are the original
set (with the spec's three corrections applied); 15-24 each exist
because they are a way this gate could be wrong while looking right,
and each was verified against a real fixture on this machine.
"""

import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from PIL import Image

import thumb_check as tc
import color_check as cc

PASS, FAIL, ERROR = tc.EXIT_PASS, tc.EXIT_FAIL, tc.EXIT_ERROR

GOLD = (0xD9, 0xA4, 0x41)
DBLUE = (0x7A, 0x9C, 0xB0)
SAGE = (0x9C, 0xAF, 0x88)
OUTLINE = (0x0C, 0x0C, 0x0C)
FOREST = (0x3E, 0x5C, 0x46)
CHOCOLATE = (0x2A, 0x18, 0x10)
BURGUNDY = (0x5C, 0x1F, 0x2E)
PLUM = (0x4A, 0x25, 0x45)


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = tc.main(argv)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else ERROR
    return code, out.getvalue(), err.getvalue()


def sha(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="thumb_check_test_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def canvas(self, size=(1400, 1400)):
        return Image.new("RGBA", size, (0, 0, 0, 0))

    def rect(self, img, box, rgb, alpha=255):
        img.paste(rgb + (alpha,), box)

    def save(self, img, name="design.png"):
        path = os.path.join(self.dir, name)
        img.save(path)
        return path

    def touching_pair(self, left, right, name="design.png"):
        """Two large rectangles sharing a vertical center edge."""
        img = self.canvas()
        self.rect(img, (200, 300, 700, 1100), left)
        self.rect(img, (700, 300, 1200, 1100), right)
        return self.save(img, name)

    def report_of(self, out_json):
        return json.loads(out_json)

    def findings(self, report, check_prefix=""):
        return [f for f in report["findings"]
                if f["check"].startswith(check_prefix)]


# ── 1-14: the original set, corrections applied ────────────────────────

class TestOriginal(Fixture):

    def test_01_single_color_passes_with_clean_buckets(self):
        img = self.canvas()
        self.rect(img, (400, 400, 1000, 1000), GOLD)
        path = self.save(img)
        code, out, _ = run([path, "black", "--json"])
        self.assertEqual(code, PASS, out)
        report = self.report_of(out)
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report["findings"], [])
        # Edge blends are genuine LANCZOS behavior: at 45px the rect is
        # ~19px and its 1px blend perimeter alone is ~3.8% of the tile.
        for size_rep in report["sizes"].values():
            self.assertLess(size_rep["off_pct_tile"], 5.0)

    def test_02_low_ratio_touching_pair_fails(self):
        """Spec correction: gold/dusty-blue is 1.30 — a WARN under the
        two tiers. The genuine FAIL fixture is gold + sage at 1.05."""
        path = self.touching_pair(GOLD, SAGE)
        code, out, _ = run([path, "black", "--json"])
        self.assertEqual(code, FAIL)
        report = self.report_of(out)
        fails = self.findings(report, "blob")
        fails = [f for f in fails if f["severity"] == "FAIL"]
        self.assertTrue(fails)
        f = fails[0]
        self.assertEqual(f["name"], "gold / sage")
        self.assertIn("1.05", f["message"])
        self.assertIn("adjacent pairs", f["message"])
        self.assertIn("% of ink", f["message"])
        pair = report["sizes"]["140"]["pairs"][0]
        self.assertGreaterEqual(pair["touch"], pair["touch_min"])

    def test_02b_gold_dusty_blue_is_a_warn_not_a_fail(self):
        path = self.touching_pair(GOLD, DBLUE)
        code, out, _ = run([path, "black", "--json"])
        self.assertEqual(code, PASS)
        report = self.report_of(out)
        bands = self.findings(report, "blob-band")
        self.assertTrue(bands)
        self.assertIn("1.30", bands[0]["message"])
        self.assertFalse([f for f in report["findings"]
                          if f["severity"] == "FAIL"])

    def test_03_far_apart_pair_passes(self):
        img = self.canvas()
        self.rect(img, (100, 100, 500, 500), GOLD)
        self.rect(img, (900, 900, 1300, 1300), SAGE)
        path = self.save(img)
        code, out, _ = run([path, "black", "--json"])
        self.assertEqual(code, PASS)
        self.assertEqual(self.findings(self.report_of(out), "blob"), [])

    def test_04_tiny_accent_warns_never_fails(self):
        img = self.canvas((560, 560))
        self.rect(img, (0, 0, 560, 552), GOLD)
        self.rect(img, (0, 552, 560, 560), DBLUE)   # 1.4% of ink
        path = self.save(img)
        code, out, _ = run([path, "black", "--json"])
        self.assertEqual(code, PASS, out)
        report = self.report_of(out)
        accents = self.findings(report, "blob-accent")
        self.assertTrue(accents)
        self.assertIn("accents never fail", accents[0]["message"])
        self.assertFalse([f for f in report["findings"]
                          if f["severity"] == "FAIL"])

    def test_05_noise_is_exit_2_with_top_unrecognized_colors(self):
        import random
        rng = random.Random(42)
        img = Image.new("RGBA", (300, 300))
        img.putdata([(rng.randrange(256), rng.randrange(256),
                      rng.randrange(256), 255) for _ in range(300 * 300)])
        path = self.save(img)
        code, _, err = run([path, "black"])
        self.assertEqual(code, ERROR)
        self.assertIn("off-palette", err)
        self.assertIn("Top unrecognized colors", err)
        self.assertGreaterEqual(err.count("#"), 5)

    def test_06_unknown_garment_lists_known(self):
        path = self.save(self.canvas((100, 100)))
        code, out, _ = run([path, "navy"])
        self.assertEqual(code, FAIL)
        self.assertIn("unknown garment 'navy'", out)
        for name in cc.GARMENTS:
            self.assertIn(name, out)

    def test_07_missing_and_corrupt_files(self):
        code, _, err = run([os.path.join(self.dir, "nope.png"), "black"])
        self.assertEqual(code, ERROR)
        self.assertIn("not found", err)
        bad = os.path.join(self.dir, "bad.png")
        with open(bad, "w") as handle:
            handle.write("this is not a png")
        code, _, err = run([bad, "black"])
        self.assertEqual(code, ERROR)
        self.assertIn("cannot read", err)

    def test_08_thin_lines_survival_warns_at_every_size(self):
        """VERIFIED: 1px lines give ~0% survival at 140 AND 75 — the
        warn must fire at every size, not only the smallest."""
        img = self.canvas((900, 900))
        for y in range(30, 900, 30):
            self.rect(img, (50, y, 850, y + 1), GOLD)
        path = self.save(img)
        code, out, _ = run([path, "black", "--json"])
        self.assertIn(code, (PASS, FAIL))
        report = self.report_of(out)
        surv = self.findings(report, "survival")
        gold_sizes = {f["size"] for f in surv if f["name"] == "gold"}
        self.assertEqual(gold_sizes, set(tc.THUMB_SIZES))

    def test_09_regression_lock_contrast_math(self):
        """Any refactor that moves these is wrong."""
        locked = [
            ("#D9A441", "#7A9CB0", 1.30), ("#D9A441", "#C67B5C", 1.46),
            ("#D9A441", "#9CAF88", 1.05), ("#7A9CB0", "#C98A8A", 1.04),
            ("#5C1F2E", "#4A2545", 1.03), ("#2A1810", "#A6A6A4", 6.96),
            ("#A34730", "#A6A6A4", 2.46),
        ]
        for a, b, expected in locked:
            self.assertEqual(round(tc.contrast_ratio(a, b), 2), expected,
                             "%s vs %s" % (a, b))

    def test_10_determinism_both_modes(self):
        path = self.touching_pair(GOLD, DBLUE)
        self.assertEqual(run([path, "black"]), run([path, "black"]))
        self.assertEqual(run([path, "black", "--json"]),
                         run([path, "black", "--json"]))

    def test_11_json_parses_and_matches_human(self):
        path = self.touching_pair(GOLD, SAGE)
        h_code, h_out, _ = run([path, "black"])
        j_code, j_out, _ = run([path, "black", "--json"])
        report = self.report_of(j_out)
        self.assertEqual(h_code, j_code)
        self.assertEqual(report["exit_code"], h_code)
        self.assertIn("VERDICT: %s" % report["verdict"], h_out)
        for f in report["findings"]:
            self.assertIn(f["name"], h_out)
        self.assertIn("Pillow %s" % report["pillow"], h_out)

    def test_12_read_only_on_the_input(self):
        path = self.touching_pair(GOLD, SAGE)
        before_hash, before_mtime = sha(path), os.path.getmtime(path)
        code, _, _ = run([path, "black"])
        self.assertEqual(code, FAIL)
        self.assertEqual(sha(path), before_hash)
        self.assertEqual(os.path.getmtime(path), before_mtime)

    def test_13_antialiased_edges_stay_under_the_error_threshold(self):
        from PIL import ImageDraw
        img = self.canvas((800, 800))
        ImageDraw.Draw(img).ellipse((150, 150, 650, 650), fill=GOLD + (255,))
        path = self.save(img)
        code, out, _ = run([path, "black", "--json"])
        self.assertNotEqual(code, ERROR)
        report = self.report_of(out)
        for size_rep in report["sizes"].values():
            self.assertLess(size_rep["off_pct_tile"], tc.OFF_PALETTE_ERROR_PCT)

    def test_14_outline_ring_is_exempt_from_blob_verdicts(self):
        img = self.canvas((800, 800))
        self.rect(img, (188, 188, 612, 612), OUTLINE)   # ring under...
        self.rect(img, (200, 200, 600, 600), GOLD)      # ...the gold field
        path = self.save(img)
        code, out, _ = run([path, "black", "--json"])
        report = self.report_of(out)
        self.assertNotEqual(report["verdict"], "FAIL")
        self.assertTrue(report["outline_declared"])
        exempt = [p for s in report["sizes"].values() for p in s["pairs"]
                  if "outline" in (p["a"], p["b"])]
        self.assertTrue(exempt)
        for p in exempt:
            self.assertIn("EXEMPT", p["verdict"])
        for s in report["sizes"].values():   # bucket reported, no caveat
            for row in s["buckets"]:
                if row["name"] == "outline":
                    self.assertIsNone(row["caveat"])


# ── 15-24: ways this gate could be wrong while looking right ───────────

class TestGateIntegrity(Fixture):

    def test_15_the_adjacency_regression(self):
        """THE REASON THE ADJACENCY MAP EXISTS. Two large rectangles
        share a center edge. With a QUANT_TOLERANCE map the LANCZOS
        blend band quantizes to an off-palette one-pixel wall and the
        touching pair is invisible below 140px. A no-tolerance map over
        the FULL palette still misses: the band quantizes to SAGE — an
        intermediate PALETTE color (measured on this machine: 43 sage
        px at 75px, 25 at 45px; unrestricted adjacency 80 / 0 / 0).
        The restricted candidate set {garment + colors present at full
        res} dissolves the wall: measured 80 / 45 / 27 touching pairs
        at 140 / 75 / 45 (rider-verified 74 / 46 / 30 on another
        machine — order of magnitude, ≥20 at every size, is the
        contract)."""
        path = self.touching_pair(GOLD, DBLUE)
        code, out, _ = run([path, "black", "--json"])
        self.assertEqual(code, PASS)
        report = self.report_of(out)
        for size in tc.THUMB_SIZES:
            pairs = [p for p in report["sizes"][str(size)]["pairs"]
                     if {p["a"], p["b"]} == {"gold", "dusty blue"}]
            self.assertEqual(len(pairs), 1, "no pair at %dpx" % size)
            self.assertGreaterEqual(pairs[0]["touch"], 20,
                                    "adjacency too weak at %dpx" % size)

    def test_15b_real_sage_stays_in_the_candidate_set(self):
        """A design with real sage keeps sage as a legitimate separator
        — only artifacts dissolve."""
        img = self.canvas()
        self.rect(img, (200, 300, 600, 1100), GOLD)
        self.rect(img, (600, 300, 800, 1100), SAGE)
        self.rect(img, (800, 300, 1200, 1100), DBLUE)
        path = self.save(img)
        _, out, _ = run([path, "black", "--json"])
        report = self.report_of(out)
        self.assertIn("sage", report["full_res"]["detected"])
        pairs45 = {frozenset((p["a"], p["b"]))
                   for p in report["sizes"]["45"]["pairs"]}
        self.assertIn(frozenset(("gold", "sage")), pairs45)
        self.assertNotIn(frozenset(("gold", "dusty blue")), pairs45)

    def test_16_blend_pollution_is_caveated_never_fact(self):
        """VERIFIED: on an outline-free fixture the outline bucket picks
        up design-vs-GARMENT edge blends passing near #0C0C0C on dark
        garments (this machine: 1.5% of the 75px tile, 5.7% at 45px).
        The bucket must be zero or explicitly caveated."""
        path = self.touching_pair(GOLD, DBLUE)
        _, out, _ = run([path, "black", "--json"])
        report = self.report_of(out)
        self.assertFalse(report["outline_declared"])
        caveated = 0
        for size_rep in report["sizes"].values():
            for row in size_rep["buckets"]:
                if row["name"] == "outline" and row["px"] > 0:
                    self.assertIsNotNone(row["caveat"], row)
                    caveated += 1
        self.assertGreater(caveated, 0)   # the pollution actually occurs
        _, human, _ = run([path, "black"])
        self.assertIn("CAVEAT", human)

    def test_17_palette_audit_locks_todays_reality(self):
        """The rule-audit idea from color_check test 18: this asserts
        today's numbers (0 of 10 clear 1.5, 5 of 10 clear 1.2 — both
        computed by the tool, verified independently). If a future
        palette edit changes them, this test says so."""
        code, out, _ = run(["--audit-palette", "black"])
        self.assertEqual(code, PASS)
        self.assertIn("0 of 10 pairs clear WARN_INTER (1.5)", out)
        self.assertIn("5 of 10 clear FAIL_INTER (1.2)", out)
        self.assertIn("HEADLINE", out)
        self.assertIn("PERCEPTION LAW 2", out)
        code, out, _ = run(["--audit-palette", "black", "--json"])
        payload = json.loads(out)
        self.assertEqual(payload["clear_warn_inter"], 0)
        self.assertEqual(payload["clear_fail_inter"], 5)
        self.assertEqual(payload["total"], 10)
        self.assertEqual(len(payload["pairs"]), 10)

    def test_17b_audit_unknown_garment(self):
        code, out, _ = run(["--audit-palette", "navy"])
        self.assertEqual(code, FAIL)
        self.assertIn("known garments", out)

    def test_18_full_res_gradient_detector(self):
        """A smooth gradient trips FLAT_STYLE_WARN_PCT; a flat two-tone
        design does not. The ramp runs gold -> garment black: the dark
        palette is so dense (the PERCEPTION LAW 2 finding) that any
        palette-to-palette ramp buckets to intermediate PALETTE colors
        — gold->terracotta never leaves tolerance (~53 apart), and
        gold->dusty blue passes within 40 of sage — so a shading ramp
        toward the garment is the honest gradient fixture."""
        garment = (0x14, 0x14, 0x14)
        img = self.canvas((800, 800))
        for i in range(500):
            t = i / 499.0
            rgb = tuple(round(GOLD[c] + (garment[c] - GOLD[c]) * t)
                        for c in range(3))
            self.rect(img, (150 + i, 275, 151 + i, 525), rgb)
        path = self.save(img)
        code, out, _ = run([path, "black", "--json"])
        self.assertNotEqual(code, ERROR)
        report = self.report_of(out)
        self.assertTrue(self.findings(report, "flat-style"))
        self.assertGreater(report["full_res"]["off_pct_tile"],
                           tc.FLAT_STYLE_WARN_PCT)

        flat = self.touching_pair(GOLD, DBLUE, "flat.png")
        _, out, _ = run([flat, "black", "--json"])
        self.assertEqual(self.findings(self.report_of(out), "flat-style"), [])

    def test_19_semi_transparent_alpha_composites_sanely(self):
        img = self.canvas((700, 700))
        self.rect(img, (225, 225, 475, 475), GOLD, alpha=128)
        path = self.save(img)
        code, out, _ = run([path, "black", "--json"])
        self.assertNotEqual(code, ERROR)          # no off-palette spike past
        report = self.report_of(out)              # the error threshold
        for size_rep in report["sizes"].values():
            self.assertLess(size_rep["off_pct_tile"], tc.OFF_PALETTE_ERROR_PCT)

    def test_20_min_area_denominator_is_ink_not_tile(self):
        """A fixture where the two denominators give opposite verdicts:
        sage is 11% of ink (≥ 2 -> both-large -> FAIL at 1.05) but only
        1% of the tile (< 2 -> would be a never-failing accent). The
        gate must FAIL — the ink denominator is the specified one."""
        img = self.canvas((1000, 1000))
        self.rect(img, (350, 350, 650, 617), GOLD)
        self.rect(img, (350, 617, 650, 650), SAGE)
        path = self.save(img)
        code, out, _ = run([path, "black", "--json"])
        self.assertEqual(code, FAIL, out)
        report = self.report_of(out)
        fails = [f for f in report["findings"] if f["severity"] == "FAIL"]
        self.assertTrue(any(f["name"] == "gold / sage" for f in fails))

    def test_21_debug_dir_is_the_only_write_path(self):
        path = self.touching_pair(GOLD, SAGE)
        input_dir_before = sorted(os.listdir(self.dir))
        before = sha(path)
        debug = os.path.join(self.dir, "debug_out")
        code, _, _ = run([path, "black", "--debug-dir", debug])
        self.assertEqual(code, FAIL)
        self.assertEqual(sha(path), before)
        written = os.listdir(debug)
        self.assertTrue(written)
        self.assertTrue(any("contacts" in name for name in written))
        after = sorted(n for n in os.listdir(self.dir) if n != "debug_out")
        self.assertEqual(after, input_dir_before)

    def test_22_sport_grey_paths(self):
        path = self.touching_pair(FOREST, CHOCOLATE, "ok.png")
        code, out, _ = run([path, "sport grey", "--json"])
        self.assertEqual(code, PASS, out)
        report = self.report_of(out)
        pair = report["sizes"]["140"]["pairs"][0]
        self.assertEqual(pair["ratio"], 2.28)
        self.assertEqual(pair["verdict"], "OK")

        path = self.touching_pair(BURGUNDY, PLUM, "bad.png")
        code, out, _ = run([path, "sport grey", "--json"])
        self.assertEqual(code, FAIL)
        fails = [f for f in self.report_of(out)["findings"]
                 if f["severity"] == "FAIL"]
        self.assertTrue(any("1.03" in f["message"] for f in fails))

    def test_23_dark_heather_provisional_in_both_modes(self):
        img = self.canvas((700, 700))
        self.rect(img, (200, 200, 500, 500), GOLD)
        path = self.save(img)
        code, human, _ = run([path, "dark heather"])
        self.assertIn("unmeasured (approx)", human)
        _, j_out, _ = run([path, "dark heather", "--json"])
        report = self.report_of(j_out)
        self.assertTrue(report["garment"]["provisional"])
        self.assertTrue(any("unmeasured" in n for n in report["footer"]))

    def test_24_no_artifacts_outside_the_temp_dir(self):
        """The suite generates everything under its temp dir; the repo
        working directory must stay untouched by fixtures."""
        repo_listing = sorted(os.listdir(os.getcwd()))
        path = self.touching_pair(GOLD, DBLUE)
        run([path, "black"])
        run(["--audit-palette", "black"])
        run(["--explain"])
        cleaned = [n for n in sorted(os.listdir(os.getcwd()))
                   if n != "__pycache__"]
        base = [n for n in repo_listing if n != "__pycache__"]
        self.assertEqual(cleaned, base)

    def test_palette_agrees_with_color_check(self):
        """thumb_check imports its palette from color_check; assert the
        wiring is live, not a stale copy."""
        self.assertIs(tc.GARMENTS, cc.GARMENTS)
        self.assertIs(tc.PALETTES, cc.PALETTES)
        self.assertIs(tc.OUTLINE, cc.OUTLINE)

    def test_explain_carries_the_verified_numbers(self):
        code, out, _ = run(["--explain"])
        self.assertEqual(code, PASS)
        self.assertIn("TWO MAPS", out)
        self.assertIn("ZERO at 75px", out)
        self.assertIn("sage wall", out)
        self.assertIn("80 / 45 / 27", out)
        self.assertIn("0 of 10", out)
        self.assertIn("D-311", out)

    def test_footer_and_help_state_simulation_scope(self):
        path = self.touching_pair(GOLD, DBLUE)
        _, out, _ = run([path, "black"])
        self.assertIn("file-level simulation", out)
        self.assertIn("NON-GARMENT (ink)", out)
        help_text = tc.build_parser().format_help()
        self.assertIn("not a promise", help_text)
        self.assertIn("DTG ink", help_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
