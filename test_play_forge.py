#!/usr/bin/env python3
"""Tests for play_forge.py (MC FLEET B2, T1-T17) + the play_schema
family/kind extension + config fail-closed cases.

pytest is specced but not installed here (flagged deviation, D-394) —
unittest-style, which pytest collects unchanged.

Fixtures: Liberation fonts stand in for the roster (the real vault
fonts are never committed, W11); assets/sidecar/index are synthetic
and live in a temp dir. Everything renders at the real 4500x5400 —
W5 says author natively, and the tests hold the tool to it.
"""

import copy
import io
import json
import os
import shutil
import sys
import types
import tempfile
import unittest
from unittest import mock

from PIL import Image, ImageChops, ImageDraw, ImageFont

import asset_index_lint as ail
import play_forge as pf
import play_schema


LIBERATION = ("/usr/share/fonts/truetype/liberation/"
              "LiberationSans-Regular.ttf")
MAILBOX_ID = "CF Sourced 2026-08-30/Mailbox-SVG-835842/"
LAUREL_ID = "CF Sourced 2026-08-30/Laurel-Wreath-SVG-15-69432028/"
MAILBOX_KEY = MAILBOX_ID + "pieces/piece_01.png"
LAUREL_KEY = LAUREL_ID + "pieces/piece_01.png"
OLD_HUE = (200, 30, 30)          # every fixture piece is this red


def has_near(image, rgb, tol):
    """True when any (visible) pixel sits within tol of rgb — done
    with C-level channel masks; a 4500x5400 getdata() set is an OOM."""
    channels = image.split()
    combined = None
    for chan, target in zip(channels[:3], rgb):
        mask = chan.point(
            lambda v, t=target: 255 if abs(v - t) <= tol else 0)
        combined = mask if combined is None \
            else ImageChops.darker(combined, mask)
    if image.mode == "RGBA":
        combined = ImageChops.darker(
            combined, channels[3].point(lambda v: 255 if v else 0))
    return combined.getbbox() is not None


def soft_blob(path, shape="blob"):
    """'blob' = fat centered circle (the mailbox stand-in); 'strip' =
    thin centered vertical bar (the laurel stand-in — a fat blob
    beside frame text trips the F5 overlap wall, exactly as a fat
    laurel would in real life)."""
    big = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    if shape == "strip":
        ImageDraw.Draw(big).ellipse((160, 20, 240, 380),
                                    fill=OLD_HUE + (255,))
    else:
        ImageDraw.Draw(big).ellipse((30, 30, 370, 370),
                                    fill=OLD_HUE + (255,))
    small = big.resize((300, 300))    # resampling makes a soft edge
    big.close()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    small.save(path)
    small.close()


class ForgeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pf_test_")
        self.addCleanup(shutil.rmtree, self.tmp)
        self.index_root = os.path.join(self.tmp, "design-assets")
        self.fonts_dir = os.path.join(self.tmp, "fonts")
        self.out_dir = os.path.join(self.tmp, "out")
        os.makedirs(self.index_root)
        os.makedirs(self.fonts_dir)
        for base in pf.FONT_ROSTER.values():
            shutil.copy(LIBERATION,
                        os.path.join(self.fonts_dir, base + ".ttf"))
        self.entries = {}
        rows = []
        for key in (MAILBOX_KEY, LAUREL_KEY):
            path = os.path.join(self.index_root, *key.split("/"))
            soft_blob(path, shape=("strip" if key == LAUREL_KEY
                                   else "blob"))
            self.entries[key] = {"sha256": pf.hash_file(path),
                                 "product_id": "835842",
                                 "ingested_utc": "2026-09-02"}
            rows.append(ail.format_row(
                ("`%s`" % key, "CF Subscription, verified", "cartoon",
                 "mail", "tonal", "flat", "Product test")))
        header = ("| Asset (path under `Merch/Design Assets/`) | "
                  "License | Style | Niche tags | Colors | Recolor | "
                  "Used in |")
        with open(os.path.join(self.index_root, "ASSET_INDEX.md"),
                  "w", encoding="utf-8") as fh:
            fh.write(header + "\n|---|---|---|---|---|---|---|\n"
                     + "\n".join(rows) + "\n")
        self.write_sidecar()
        self.config_path = os.path.join(self.tmp, "config.json")
        self.write_config()
        patcher = mock.patch.object(pf, "BASE_DIR", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_sidecar(self):
        with open(os.path.join(self.index_root,
                               "ASSET_INDEX.hashes.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"version": 1, "tool": "asset_ingest",
                       "entries": self.entries}, fh)

    def write_config(self, **extra):
        cfg = {"index_root": self.index_root,
               "fonts_dir": self.fonts_dir,
               "out_dir": self.out_dir}
        cfg.update(extra)
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh)

    def base_variants(self):
        return [
            {"id": 1, "garment": "Black",
             "font_pair": {"hero": "Baseball Athlete Jersey",
                           "support": "Vorn"},
             "color_path": "outline_path", "layout": "text_hero",
             "fill_hex": "#7A9CB0", "outline_hex": "#D9A441",
             "elements": [{"asset_id": MAILBOX_ID,
                           "recolor_hex": "#D9A441",
                           "size_fraction": 0.20,
                           "position": "between"}]},
            {"id": 2, "garment": "Black",
             "font_pair": {"hero": "Vorn", "support": "Vorn"},
             "color_path": "flat_pool", "layout": "frame",
             "fill_hex": "#F5F0E1", "outline_hex": None,
             "elements": [{"asset_id": LAUREL_ID,
                           "recolor_hex": "#D9A441",
                           "size_fraction": 0.30,
                           "position": "left"}]},
        ]

    def write_play(self, variants=None):
        play = {"play_id": "2026-09-02-test-play",
                "line": {"setup": "CAN'T LEAVE IT NEXT DOOR.",
                         "punch": "NOT MY CALL."},
                "named_feeling": "deadpan judgment",
                "variants": (self.base_variants()
                             if variants is None else variants)}
        path = os.path.join(self.tmp, "play.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(play, fh)
        return path

    def run_tool(self, play_path, *flags):
        with mock.patch("sys.stdout", io.StringIO()) as out, \
                mock.patch("sys.stderr", io.StringIO()) as err:
            code = pf.main([play_path, "--config", self.config_path,
                            *flags])
        return code, out.getvalue(), err.getvalue()

    def receipts(self):
        path = os.path.join(self.tmp, pf.RECEIPTS_NAME)
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def play_out(self):
        return os.path.join(self.out_dir, "2026-09-02-test-play")


class T01T05T12T13GoodRun(ForgeCase):
    def _run(self):
        code, out, _ = self.run_tool(self.write_play())
        self.assertIn(code, (0, 1))      # gate verdicts may FAIL;
        return code, out                 # never a refusal

    def test_t1_recolor_via_module_zero_old_hue(self):
        """T1 (W1): elements recolored ONLY through recolor.py — no
        local copy in the source, zero old-hue pixels in the render."""
        with open(pf.__file__, encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn("def recolor", source)
        self._run()
        with Image.open(os.path.join(self.play_out(),
                                     "variant_01.png")) as full:
            self.assertFalse(has_near(full, OLD_HUE, tol=12),
                             "old-hue pixel survived the recolor")

    def test_t5_squint_is_a_downsample(self):
        """T5 (W5): the squint equals an independent LANCZOS resize
        of the full render — never a second draw pass."""
        self._run()
        with Image.open(os.path.join(self.play_out(),
                                     "variant_01.png")) as full:
            independent = full.resize((pf.SQUINT_W, pf.SQUINT_H),
                                      pf.RESAMPLE)
        with Image.open(os.path.join(
                self.play_out(), "variant_01_squint.png")) as squint:
            self.assertEqual(squint.tobytes(), independent.tobytes())
        independent.close()

    def test_t12_lossless_dimensions(self):
        """T12: full is lossless PNG at 4500x5400 RGBA; squint 220px."""
        self._run()
        with Image.open(os.path.join(self.play_out(),
                                     "variant_02.png")) as full:
            self.assertEqual(full.format, "PNG")
            self.assertEqual(full.size, (4500, 5400))
            self.assertEqual(full.mode, "RGBA")
        with Image.open(os.path.join(
                self.play_out(), "variant_02_squint.png")) as squint:
            self.assertEqual(squint.width, 220)

    def test_t13_number_order_no_ranking_language(self):
        """T13 (W10): number order everywhere; no ranking word in any
        output this tool writes."""
        _, out = self._run()
        texts = [out]
        for name in os.listdir(self.play_out()):
            if name.endswith(".md") or name.endswith(".json"):
                with open(os.path.join(self.play_out(), name),
                          encoding="utf-8") as fh:
                    texts.append(fh.read())
        import re
        for text in texts:
            self.assertIsNone(
                re.search(r"recommend|favou?rite|\brank|\bbest\b",
                          text, re.I), "ranking language found")
        one = out.index("variant 1")
        two = out.index("variant 2")
        self.assertLess(one, two)
        self.assertTrue(os.path.exists(os.path.join(
            self.play_out(), pf.CONTACT_FULLS_NAME)))
        self.assertTrue(os.path.exists(os.path.join(
            self.play_out(), pf.CONTACT_SQUINTS_NAME)))


class T02Clusters(ForgeCase):
    def test_near_pair_is_one_cluster(self):
        self.assertEqual(
            pf.cluster_hexes(["#D9A441", "#D9A442"], 10.0),
            [["#D9A441", "#D9A442"]])

    def test_three_clusters_rejected_and_receipted(self):
        """T2 (W2) + T15: near-pair counts as ONE; a third colour
        makes 3 clusters -> spec REJECTED, receipt still written."""
        variants = self.base_variants()
        variants[1]["elements"] = [
            {"asset_id": LAUREL_ID, "recolor_hex": "#D9A442",
             "size_fraction": 0.30, "position": "left"},
            {"asset_id": MAILBOX_ID, "recolor_hex": "#7A9CB0",
             "size_fraction": 0.20, "position": "right"},
            {"asset_id": MAILBOX_ID, "recolor_hex": "#2A1810",
             "size_fraction": 0.20, "position": "center"}]
        variants[1]["fill_hex"] = "#D9A441"
        before = len(self.receipts())
        code, _, err = self.run_tool(self.write_play(variants))
        self.assertEqual(code, 2)
        self.assertIn("W2", err)
        receipts = self.receipts()
        self.assertEqual(len(receipts), before + 1)   # T15
        self.assertEqual(receipts[-1]["refusals"][0]["kind"],
                         "SPEC_REJECTED")


class T03Fonts(ForgeCase):
    def test_missing_roster_font_hard_fail(self):
        """T3 (W3): missing roster font -> refusal before variant 1;
        load_default is NEVER called."""
        os.remove(os.path.join(self.fonts_dir, "Vorn.ttf"))

        def bomb(*args, **kwargs):
            raise AssertionError("load_default called — W3 breach")

        with mock.patch.object(ImageFont, "load_default", bomb):
            code, _, err = self.run_tool(self.write_play())
        self.assertEqual(code, 2)
        self.assertIn("W3 FONT PRE-FLIGHT", err)
        self.assertFalse(os.path.exists(self.play_out()))


class T04MinStroke(ForgeCase):
    def test_too_thin_line_rejected_named(self):
        """T4 (W4): with the wash floor set high, the fitted line's
        strokes do not survive erosion -> variant rejected, named."""
        self.write_config(min_stroke_px=220)
        code, out, _ = self.run_tool(self.write_play())
        self.assertEqual(code, 1)
        receipt = self.receipts()[-1]
        self.assertEqual(len(receipt["rejected"]), 2)
        self.assertIn("W4 MIN_STROKE", receipt["rejected"][0]["reason"])
        self.assertIn("REJECTED", out)
        # rejected tiles still hold their numbers on the sheet
        self.assertTrue(os.path.exists(os.path.join(
            self.play_out(), pf.CONTACT_FULLS_NAME)))


class BenchF1SurvivalBites(ForgeCase):
    """Bench F1: the survival floor must actually fire on a real
    font at the DEFAULT config. Calibration (Liberation Sans,
    kernel 5, measured 2026-09-02): fitted 486px -> survival 0.886;
    fitted 75px (an ~80-char line) -> 0.365. Default floor 0.50
    separates them."""

    LONG_PUNCH = ("NOT MY CALL. NOT MY CALL. NOT MY CALL. NOT MY "
                  "CALL. NOT MY CALL. NOT MY CALL.")

    def _long_play(self):
        play = {"play_id": "2026-09-02-long-play",
                "line": {"setup": "CAN'T LEAVE IT NEXT DOOR.",
                         "punch": self.LONG_PUNCH},
                "named_feeling": "deadpan judgment",
                "variants": [self.base_variants()[0]]}
        path = os.path.join(self.tmp, "long.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(play, fh)
        return path

    def test_default_floor_rejects_thin_named_with_measurement(self):
        code, out, _ = self.run_tool(self._long_play())
        self.assertEqual(code, 1)
        receipt = self.receipts()[-1]
        self.assertEqual(len(receipt["rejected"]), 1)
        reason = receipt["rejected"][0]["reason"]
        self.assertIn("W4 MIN_STROKE", reason)
        self.assertIn("of its ink survives", reason)   # measured

    def test_red_goes_green_on_the_config_knob(self):
        """The SAME play renders when the floor is lowered — the
        rejection comes from the survival mechanism, nothing else."""
        self.write_config(min_stroke_survival=0.05)
        code, _, _ = self.run_tool(self._long_play())
        receipt = self.receipts()[-1]
        self.assertEqual(receipt["rejected"], [])
        self.assertEqual(receipt["rendered"], 1)

    def test_normal_line_passes_the_default_floor(self):
        variants = [self.base_variants()[0]]
        code, _, _ = self.run_tool(self.write_play(variants))
        self.assertIn(code, (0, 1))
        self.assertEqual(self.receipts()[-1]["rejected"], [])


class BenchF5Overlap(ForgeCase):
    def test_element_parked_on_the_hero_line_goes_red(self):
        """Bench F5: any pixel intersection between layers rejects
        the variant by name — gates can't see overlap, the wall can."""
        variants = [self.base_variants()[0]]
        variants[0]["elements"] = [
            {"asset_id": MAILBOX_ID, "recolor_hex": "#D9A441",
             "size_fraction": 0.55, "position": "center"}]
        code, _, _ = self.run_tool(self.write_play(variants))
        self.assertEqual(code, 1)
        receipt = self.receipts()[-1]
        self.assertEqual(len(receipt["rejected"]), 1)
        self.assertIn("OVERLAP", receipt["rejected"][0]["reason"])
        self.assertIn(" x ", receipt["rejected"][0]["reason"])


class BenchF2F3Families(ForgeCase):
    def test_arc_support_clears_the_measured_arc(self):
        """Bench F2: the arc variant that collided on the bench now
        renders with zero layer intersection (the F5 wall would have
        rejected it otherwise)."""
        variants = [{
            "id": 1, "garment": "Black",
            "font_pair": {"hero": "Vorn", "support": "Mango Dream"},
            "color_path": "outline_path", "layout": "art_hero",
            "family": "arc", "fill_hex": "#7A9CB0",
            "outline_hex": "#D9A441", "elements": []}]
        code, _, _ = self.run_tool(self.write_play(variants))
        self.assertIn(code, (0, 1))
        receipt = self.receipts()[-1]
        self.assertEqual(receipt["rejected"], [])
        self.assertEqual(receipt["rendered"], 1)

    def test_badge_caps_text_to_the_ring_chord(self):
        """Bench F3: text_dominant's 0.86 hero_frac broke the ring on
        the bench; the chord cap + ring layer make it render clean."""
        variants = [{
            "id": 1, "garment": "Black",
            "font_pair": {"hero": "Mango Dream", "support": "Vorn"},
            "color_path": "flat_pool", "layout": "text_dominant",
            "family": "badge", "fill_hex": "#F5F0E1",
            "outline_hex": None,
            "elements": [{"asset_id": MAILBOX_ID,
                          "recolor_hex": "#F5F0E1",
                          "size_fraction": 0.12,
                          "position": "below_support"}]}]
        code, _, _ = self.run_tool(self.write_play(variants))
        self.assertIn(code, (0, 1))
        receipt = self.receipts()[-1]
        self.assertEqual(receipt["rejected"], [])
        self.assertEqual(receipt["rendered"], 1)
        # the hero really was capped tighter than the layout fraction
        with open(os.path.join(self.play_out(),
                               "variant_01_spec.json"),
                  encoding="utf-8") as fh:
            spec = json.load(fh)
        chord = (2 * (int(4500 * pf.BADGE_RING_FRAC)
                      - max(6, int(4500 * pf.BADGE_RING_WIDTH_FRAC))
                      - 40) * pf.BADGE_TEXT_CHORD_FRAC)
        font = ImageFont.truetype(
            os.path.join(self.fonts_dir, "Mango Dream.ttf"),
            spec["fitted_sizes"]["hero"])
        self.assertLessEqual(font.getlength("NOT MY CALL."),
                             chord + 1)


class BenchF6MeasuredAnchors(ForgeCase):
    def _one_variant(self, size_fraction):
        variant = self.base_variants()[0]
        variant["elements"] = [
            {"asset_id": MAILBOX_ID, "recolor_hex": "#D9A441",
             "size_fraction": size_fraction,
             "position": "above_hero"}]
        return [variant]

    def test_tall_element_above_hero_renders(self):
        """Bench F6: a legal tall accent at above_hero on text_hero
        renders with zero intersection — the anchor comes off the
        MEASURED text mask, not a fixed fraction blind to the
        element's height."""
        code, _, _ = self.run_tool(
            self.write_play(self._one_variant(0.18)))
        self.assertIn(code, (0, 1))
        receipt = self.receipts()[-1]
        self.assertEqual(receipt["rejected"], [])
        self.assertEqual(receipt["rendered"], 1)

    def test_impossible_element_rejected_by_name(self):
        """Bench F6: an element that cannot fit goes red as
        ELEMENT_NO_ROOM with needs/has — never as a bare OVERLAP."""
        code, _, _ = self.run_tool(
            self.write_play(self._one_variant(0.60)))
        self.assertEqual(code, 1)
        receipt = self.receipts()[-1]
        self.assertEqual(len(receipt["rejected"]), 1)
        reason = receipt["rejected"][0]["reason"]
        self.assertIn("ELEMENT_NO_ROOM", reason)
        self.assertIn("above_hero", reason)
        self.assertIn("needs", reason)
        self.assertNotIn("OVERLAP", reason)


class MidtownRegister(ForgeCase):
    def _midtown_play(self, setup):
        variant = self.base_variants()[0]
        variant["font_pair"] = {"hero": "Baseball Athlete Jersey",
                                "support": "Midtown Script"}
        play = {"play_id": "2026-09-02-register",
                "line": {"setup": setup, "punch": "NOT MY CALL."},
                "named_feeling": "deadpan judgment",
                "variants": [variant]}
        path = os.path.join(self.tmp, "register.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(play, fh)
        return path

    def test_all_caps_in_midtown_rejected_by_name(self):
        """Brandkit register rule: Midtown Script is Title Case only
        — an ALL-CAPS line in it rejects the variant by name."""
        code, _, _ = self.run_tool(
            self._midtown_play("CAN'T LEAVE IT NEXT DOOR."))
        self.assertEqual(code, 1)
        receipt = self.receipts()[-1]
        self.assertEqual(len(receipt["rejected"]), 1)
        reason = receipt["rejected"][0]["reason"]
        self.assertIn("REGISTER: Midtown Script is Title Case only",
                      reason)
        self.assertIn("CAN'T LEAVE IT NEXT DOOR.", reason)

    def test_title_case_in_midtown_renders(self):
        """Same play, Title Case setup -> renders (red goes green on
        the case alone)."""
        code, _, _ = self.run_tool(
            self._midtown_play("Can't Leave It Next Door."))
        self.assertIn(code, (0, 1))
        receipt = self.receipts()[-1]
        self.assertEqual(receipt["rejected"], [])
        self.assertEqual(receipt["rendered"], 1)


class BadgeMeasuredAnchors(ForgeCase):
    """Fable live-run fix: the F5 wall fired on a real badge variant
    ("element x ring, 619 px") because badge anchors were a fixed
    fraction off the ring radius — F6 had covered straight/arc only.
    Badge above/below now measure the ring mask and the element's own
    ink, same as every other family."""

    def _badge_play(self, size_fraction, position="below_support"):
        variant = {
            "id": 1, "garment": "Black",
            "font_pair": {"hero": "Vorn", "support": "Vorn"},
            "color_path": "flat_pool", "layout": "text_dominant",
            "family": "badge", "fill_hex": "#F5F0E1",
            "outline_hex": None,
            "elements": [{"asset_id": MAILBOX_ID,
                          "recolor_hex": "#F5F0E1",
                          "size_fraction": size_fraction,
                          "position": position}]}
        return self.write_play([variant])

    def test_tall_element_below_support_renders(self):
        """A tall element on a badge renders with zero intersection —
        the anchor comes off the MEASURED ring, not a constant."""
        code, _, _ = self.run_tool(self._badge_play(0.28))
        self.assertIn(code, (0, 1))
        receipt = self.receipts()[-1]
        self.assertEqual(receipt["rejected"], [])
        self.assertEqual(receipt["rendered"], 1)

    def test_impossible_element_is_named_not_overlap(self):
        """An element that cannot clear the ring goes red as
        ELEMENT_NO_ROOM with needs/has — never a bare OVERLAP."""
        code, _, _ = self.run_tool(self._badge_play(0.45))
        self.assertEqual(code, 1)
        reason = self.receipts()[-1]["rejected"][0]["reason"]
        self.assertIn("ELEMENT_NO_ROOM", reason)
        self.assertIn("below_support", reason)
        self.assertNotIn("OVERLAP", reason)

    def test_above_hero_on_badge_also_measured(self):
        """The same holds above the ring."""
        code, _, _ = self.run_tool(
            self._badge_play(0.45, position="above_hero"))
        self.assertEqual(code, 1)
        reason = self.receipts()[-1]["rejected"][0]["reason"]
        self.assertIn("ELEMENT_NO_ROOM", reason)
        self.assertIn("above_hero", reason)


class BenchF4OutDir(ForgeCase):
    def test_second_run_refused_unless_overwrite(self):
        """Bench F4: a non-empty out_dir/<play_id> refuses; the
        receipt names the mode when --overwrite is deliberate."""
        play = self.write_play()
        self.assertIn(self.run_tool(play)[0], (0, 1))
        code, _, err = self.run_tool(play)
        self.assertEqual(code, 2)
        self.assertIn("OUT_DIR", err)
        self.assertEqual(self.receipts()[-1]["refusals"][0]["kind"],
                         "OUT_DIR_NOT_EMPTY")
        code, _, _ = self.run_tool(play, "--overwrite")
        self.assertIn(code, (0, 1))
        self.assertEqual(self.receipts()[-1]["out_dir_mode"],
                         "OVERWRITE")


class T06T07Structure(ForgeCase):
    def test_one_axis_difference_rejected(self):
        """T6 (W6): a pair differing on ONE axis rejects the spec."""
        variants = self.base_variants()
        clone = copy.deepcopy(variants[0])
        clone["id"] = 2
        clone["layout"] = "frame"        # only layout differs
        variants[1] = clone
        code, _, err = self.run_tool(self.write_play(variants))
        self.assertEqual(code, 2)
        self.assertIn("W6", err)

    def test_identical_elements_and_clusters_rejected(self):
        """T7 (W6): axis labels differ on 2 axes but the element set
        and colour clusters are identical -> rejected."""
        variants = self.base_variants()
        variants[0]["color_path"] = "flat_pool"
        variants[0]["outline_hex"] = None
        variants[0]["fill_hex"] = "#D9A441"
        variants[1] = {
            "id": 2, "garment": "Black",
            "font_pair": {"hero": "Mango Dream",
                          "support": "Mango Dream"},
            "color_path": "flat_pool", "layout": "art_top",
            "fill_hex": "#D9A441", "outline_hex": None,
            "elements": copy.deepcopy(variants[0]["elements"])}
        code, _, err = self.run_tool(self.write_play(variants))
        self.assertEqual(code, 2)
        self.assertIn("axis labels", err)


class T08T09Provenance(ForgeCase):
    def test_no_index_row_refused(self):
        """T8 (W7): sidecar entry exists but the ASSET_INDEX row is
        gone -> refuse."""
        index = os.path.join(self.index_root, "ASSET_INDEX.md")
        with open(index, encoding="utf-8") as fh:
            lines = [l for l in fh.read().split("\n")
                     if MAILBOX_KEY not in l]
        with open(index, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        code, _, err = self.run_tool(self.write_play())
        self.assertEqual(code, 2)
        self.assertIn("NO ASSET_INDEX row", err)

    def test_hash_mismatch_and_missing_entry_refused(self):
        """T9 (W7): tampered bytes -> refuse; missing sidecar entry
        -> refuse."""
        target = os.path.join(self.index_root,
                              *MAILBOX_KEY.split("/"))
        with open(target, "ab") as fh:
            fh.write(b"tamper")
        code, _, err = self.run_tool(self.write_play())
        self.assertEqual(code, 2)
        self.assertIn("sha256 mismatch", err)
        del self.entries[LAUREL_KEY]
        self.write_sidecar()
        variants = [self.base_variants()[1]]
        variants[0]["id"] = 1
        code, _, err = self.run_tool(self.write_play(variants))
        self.assertEqual(code, 2)
        self.assertIn("no sidecar entry", err)


class T10OutlineLaw(ForgeCase):
    def test_outline_only_hex_never_a_fill(self):
        """T10 (W8): #0C0C0C is outline-only on sport grey -> fill
        use refuses; and outline_path must use the garment's own
        OUTLINES hex."""
        variants = self.base_variants()
        variants[1] = {
            "id": 2, "garment": "Sport Grey",
            "font_pair": {"hero": "Vorn", "support": "Mango Dream"},
            "color_path": "flat_pool", "layout": "art_top",
            "fill_hex": "#0C0C0C", "outline_hex": None,
            "elements": []}
        code, _, err = self.run_tool(self.write_play(variants))
        self.assertEqual(code, 2)
        self.assertIn("OUTLINE-ONLY", err)
        variants[1] = dict(variants[1], fill_hex="#2A1810",
                           color_path="outline_path",
                           outline_hex="#D9A441")   # wrong garment's
        code, _, err = self.run_tool(self.write_play(variants))
        self.assertEqual(code, 2)
        self.assertIn("W8", err)


class T11FailBadge(ForgeCase):
    def test_gate_fail_is_badged_never_hidden(self):
        """T11 (W9): an off-pool flat fill fails color_check; the
        variant stays on the sheet with a badge, PNG intact."""
        variants = self.base_variants()
        variants[1]["fill_hex"] = "#123456"
        code, _, _ = self.run_tool(self.write_play(variants))
        self.assertEqual(code, 1)
        receipt = self.receipts()[-1]
        self.assertIn(2, receipt["gate_fails"])
        self.assertTrue(os.path.exists(os.path.join(
            self.play_out(), "variant_02.png")))
        with Image.open(os.path.join(
                self.play_out(), pf.CONTACT_FULLS_NAME)) as sheet:
            # variant 2 is the second tile; its badge strip is at the
            # tile bottom
            pixel = sheet.getpixel((pf.CONTACT_TILE_W + 20,
                                    pf.CONTACT_TILE_H - 30))
        self.assertEqual(pixel, pf.FAIL_BADGE_COLOR[:3])


class T14Families(ForgeCase):
    def test_arc_and_badge_render_with_outline_everywhere(self):
        """T14 (W12): straight, arc, and badge all render, and the
        outline path's stroke shows up in every family."""
        gold = (0xD9, 0xA4, 0x41, 255)
        variants = []
        specs = [("straight", "text_hero",
                  ("Baseball Athlete Jersey", "Vorn"), "#7A9CB0"),
                 ("arc", "art_top", ("Vorn", "Mango Dream"),
                  "#F5F0E1"),
                 ("badge", "frame",
                  ("Mango Dream", "Baseball Athlete Jersey"),
                  "#9CAF88")]
        for number, (family, layout, fonts, fill) in enumerate(
                specs, start=1):
            variants.append({
                "id": number, "garment": "Black",
                "font_pair": {"hero": fonts[0], "support": fonts[1]},
                "color_path": "outline_path", "layout": layout,
                "family": family, "fill_hex": fill,
                "outline_hex": "#D9A441", "elements": []})
        code, _, _ = self.run_tool(self.write_play(variants))
        self.assertIn(code, (0, 1))
        for number in (1, 2, 3):
            path = os.path.join(self.play_out(),
                                pf.FULL_NAME_FMT % number)
            with Image.open(path) as full:
                self.assertTrue(has_near(full, gold[:3], tol=2),
                                "no outline stroke in variant %d"
                                % number)


class T16Eyes(ForgeCase):
    def test_character_checked_ornament_na_absent_unavailable(self):
        """T16 (W9 court rider): eyes gate runs ONLY on character
        elements; ornament-only records EYES_N/A; a missing render_qc
        records EYES_UNAVAILABLE, never a fake verdict."""
        variants = self.base_variants()
        variants[0]["elements"][0]["kind"] = "character"
        variants[1]["elements"][0]["kind"] = "ornament"
        calls = []
        fake = types.ModuleType("render_qc")
        fake.check_thumbnail_eyes = lambda p: calls.append(p) or True
        with mock.patch.dict(sys.modules, {"render_qc": fake}):
            code, _, _ = self.run_tool(self.write_play(variants))
        self.assertIn(code, (0, 1))
        self.assertEqual(len(calls), 1)
        with open(os.path.join(self.play_out(),
                               "variant_01_spec.json"),
                  encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["gates"]["eyes"]["verdict"],
                             "PASS")
        with open(os.path.join(self.play_out(),
                               "variant_02_spec.json"),
                  encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["gates"]["eyes"]["verdict"],
                             pf.EYES_NA)
        # absent module (this repo's reality): recorded, not faked
        # (--overwrite because the F4 guard now refuses the reuse of
        # a non-empty out_dir — which is itself the guard working)
        sys.modules.pop("render_qc", None)
        code, _, _ = self.run_tool(self.write_play(variants),
                                   "--overwrite")
        with open(os.path.join(self.play_out(),
                               "variant_01_spec.json"),
                  encoding="utf-8") as fh:
            verdict = json.load(fh)["gates"]["eyes"]["verdict"]
        self.assertIn("EYES_UNAVAILABLE", verdict)


class T17SamplePlay(ForgeCase):
    def test_d419_sample_renders_end_to_end(self):
        """T17: the D-419 sample play (notes, bundle-path asset_ids,
        both garments) renders all 5 variants with fixture fonts,
        assets, and sidecar."""
        sample = {
            "play_id": "2026-09-01-mail-not-my-call",
            "line": {"setup": "CAN'T LEAVE IT NEXT DOOR.",
                     "punch": "NOT MY CALL."},
            "named_feeling": "deadpan judgment",
            "variants": [
                {"id": 1, "garment": "Black",
                 "font_pair": {"hero": "Baseball Athlete Jersey",
                               "support": "Vorn"},
                 "color_path": "outline_path", "layout": "text_hero",
                 "fill_hex": "#7A9CB0", "outline_hex": "#D9A441",
                 "elements": [{"asset_id": MAILBOX_ID,
                               "note": "post-mailbox piece",
                               "recolor_hex": "#D9A441",
                               "size_fraction": 0.20,
                               "position": "between"}]},
                {"id": 2, "garment": "Black",
                 "font_pair": {"hero": "Vorn", "support": "Vorn"},
                 "color_path": "flat_pool", "layout": "frame",
                 "fill_hex": "#F5F0E1", "outline_hex": None,
                 "elements": [
                     {"asset_id": LAUREL_ID,
                      "recolor_hex": "#D9A441",
                      "size_fraction": 0.47, "position": "left"},
                     {"asset_id": LAUREL_ID,
                      "recolor_hex": "#D9A441",
                      "size_fraction": 0.47, "position": "right"}]},
                {"id": 3, "garment": "Sport Grey",
                 "font_pair": {"hero": "Baseball Athlete Jersey",
                               "support": "Vorn"},
                 "color_path": "flat_pool", "layout": "art_top",
                 "fill_hex": "#2A1810", "outline_hex": None,
                 "elements": [{"asset_id": MAILBOX_ID,
                               "note": "open-door piece",
                               "recolor_hex": "#2A1810",
                               "size_fraction": 0.43,
                               "position": "above_hero"}]},
                {"id": 4, "garment": "Black",
                 "font_pair": {"hero": "Mango Dream",
                               "support": "Mango Dream"},
                 "color_path": "flat_pool", "layout": "art_hero",
                 "fill_hex": "#D9A441", "outline_hex": None,
                 "elements": [{"asset_id": MAILBOX_ID,
                               "recolor_hex": "#C98A8A",
                               "size_fraction": 0.40,
                               "position": "above_hero"}]},
                {"id": 5, "garment": "Sport Grey",
                 "font_pair": {"hero": "Vorn",
                               "support": "Mango Dream"},
                 "color_path": "flat_pool", "layout": "text_dominant",
                 "fill_hex": "#2A1810", "outline_hex": None,
                 "elements": [{"asset_id": MAILBOX_ID,
                               "recolor_hex": "#3E5C46",
                               "size_fraction": 0.13,
                               "position": "below_support"}]},
            ],
        }
        path = os.path.join(self.tmp, "sample.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(sample, fh)
        code, _, _ = self.run_tool(path)
        self.assertIn(code, (0, 1))
        out = os.path.join(self.out_dir, sample["play_id"])
        for number in range(1, 6):
            for fmt in (pf.FULL_NAME_FMT, pf.SQUINT_NAME_FMT,
                        pf.SPEC_JSON_FMT, pf.SPEC_MD_FMT):
                self.assertTrue(
                    os.path.exists(os.path.join(out, fmt % number)),
                    fmt % number)
        receipt = self.receipts()[-1]
        self.assertEqual(receipt["rendered"], 5)
        self.assertEqual(receipt["rejected"], [])


class SchemaExtension(unittest.TestCase):
    def sample_variant(self):
        return {"id": 1, "garment": "Black",
                "font_pair": {"hero": "Vorn", "support": "Vorn"},
                "color_path": "flat_pool", "layout": "text_hero",
                "fill_hex": "#D9A441", "outline_hex": None,
                "elements": []}

    def test_family_default_and_closed_registry(self):
        variant = play_schema.validate_variant(self.sample_variant(),
                                               "v")
        self.assertEqual(variant["family"], "straight")
        bad = dict(self.sample_variant(), family="banner")
        with self.assertRaises(play_schema.PlayError):
            play_schema.validate_variant(bad, "v")
        ok = dict(self.sample_variant(), family="badge")
        self.assertEqual(play_schema.validate_variant(ok,
                                                      "v")["family"],
                         "badge")

    def test_kind_optional_and_closed(self):
        element = {"asset_id": "a", "recolor_hex": "#D9A441",
                   "size_fraction": 0.2, "position": "left"}
        self.assertIsNone(
            play_schema.validate_element(element, "e")["kind"])
        element["kind"] = "character"
        self.assertEqual(
            play_schema.validate_element(element, "e")["kind"],
            "character")
        element["kind"] = "mascotte"
        with self.assertRaises(play_schema.PlayError):
            play_schema.validate_element(element, "e")


class ConfigFailClosed(ForgeCase):
    def test_unknown_key_and_flag(self):
        self.write_config(surprise=1)
        code, _, _ = self.run_tool(self.write_play())
        self.assertEqual(code, 2)
        with mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                pf.main(["--bogus"])
        self.assertEqual(caught.exception.code, 2)

    def test_explain_prints_registries(self):
        with mock.patch("sys.stdout", io.StringIO()) as out:
            code = pf.main(["--explain"])
        self.assertEqual(code, 0)
        for layout in play_schema.LAYOUTS:
            self.assertIn(layout, out.getvalue())
        for family in play_schema.FAMILIES:
            self.assertIn(family, out.getvalue())


if __name__ == "__main__":
    unittest.main()
