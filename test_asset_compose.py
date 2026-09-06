#!/usr/bin/env python3
"""Tests for asset_compose.py — MC FLEET B5.

pytest is specced across this repo but not installed here (flagged
deviation, D-394) — unittest-style, which pytest collects unchanged.

The fixture builds a REAL tiny index: two source PNGs, a lint-clean
ASSET_INDEX row each, and a real asset_ingest sidecar. Sources are
small (200px) because every wall here is about provenance, thresholds
and geometry, not about resolution — the one place size matters
(upsample cap) sets its own numbers.
"""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from PIL import Image

import asset_compose as ac
import asset_index_lint as ail
import asset_ingest as ai
import play_forge as pf
import play_new as pn
import play_schema

CLEAN, FINDINGS, ERROR = ac.EXIT_CLEAN, ac.EXIT_FINDINGS, ac.EXIT_ERROR
STYLE = "subject, composite -- beard silhouette with a cuffed beanie"


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = ac.main(argv)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else ERROR
    return code, out.getvalue(), err.getvalue()


class ComposeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="asset_compose_test_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.index_root = os.path.join(self.tmp, "assets")
        os.makedirs(os.path.join(self.index_root, "CF", "pieces"))
        self.entries = {}
        self.rows = []
        self.make_source("CF/pieces/beard.png", grey=20)
        self.make_source("CF/pieces/beanie.png", grey=200)
        self.write_index()
        self.config_path = os.path.join(self.tmp, "config.json")
        self.write_config()
        patcher = mock.patch.object(ac, "RECEIPTS_NAME",
                                    os.path.join(self.tmp,
                                                 "receipts.jsonl"))
        patcher.start()
        self.addCleanup(patcher.stop)

    # ── fixture helpers ────────────────────────────────────────────
    def make_source(self, rel, grey, size=(200, 200), box=None,
                    license_cell=None):
        """A source piece: an opaque grey square on transparency, plus
        its sidecar entry and a lint-clean FILE row."""
        path = os.path.join(self.index_root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        image = Image.new("RGBA", size, (0, 0, 0, 0))
        box = box or (40, 40, size[0] - 40, size[1] - 40)
        image.paste((grey, grey, grey, 255), box)
        image.save(path)
        image.close()
        with open(path, "rb") as handle:
            digest = ac.sha256_bytes(handle.read())
        self.entries[rel] = {"sha256": digest, "product_id": "1",
                             "ingested_utc": "2026-09-06",
                             "tool": ai.TOOL_NAME}
        self.rows.append(ail.format_row(
            ["`%s`" % rel,
             license_cell or ai.CF_LICENSE_LITERAL,
             "flat cut-file", "hipster", "tonal", "flat",
             ai.USED_IN_FMT % "2026-09-06"]))
        return path

    def write_index(self, extra_rows=()):
        header = "| " + " | ".join(ail.HEADER_CELLS) + " |"
        sep = "|" + "---|" * ail.COLUMN_COUNT
        with open(os.path.join(self.index_root, ai.INDEX_NAME), "w",
                  encoding="utf-8") as handle:
            handle.write("\n".join([header, sep] + self.rows
                                   + list(extra_rows)) + "\n")
        with open(os.path.join(self.index_root, ai.SIDECAR_NAME), "w",
                  encoding="utf-8") as handle:
            json.dump({"version": ai.SIDECAR_VERSION,
                       "tool": ai.TOOL_NAME,
                       "entries": self.entries}, handle)

    def write_config(self, **extra):
        cfg = {"index_root": self.index_root}
        cfg.update(extra)
        with open(self.config_path, "w", encoding="utf-8") as handle:
            json.dump(cfg, handle)

    # ── the recipe ─────────────────────────────────────────────────
    def recipe(self, **over):
        data = {
            "schema": 1,
            "output": {
                "path": "CF/pieces/hipster.png",
                "kind": "subject",
                "style": STYLE,
                "niche_tags": "hipster",
                "colors": "mono",
                "recolor": "flat",
                "expect_components": 2,
                "compress_level": 6,
            },
            "canvas": {
                "resample": "LANCZOS",
                "alpha_floor": 16,
                "max_layer_upsample": 4.0,
                "min_stroke_px": 3,
                "min_stroke_survival": 0.0,
            },
            "layers": [
                {"id": "beard",
                 "source_asset_id": "CF/pieces/beard.png",
                 "ops": [{"op": "solid"}],
                 "placement": {"align": "center",
                               "scale": {"mode": "px", "width": 400}}},
                {"id": "beanie",
                 "source_asset_id": "CF/pieces/beanie.png",
                 "ops": [{"op": "solid"}],
                 "placement": {
                     "align": "center",
                     "scale": {"mode": "width_rel_to_layer",
                               "layer": "beard", "factor": 1.2},
                     "squash": {"h_factor": 0.78},
                     "gap": {"rel_to_own_height": 0.05,
                             "from": "beard", "edge": "top"}}},
            ],
        }
        for key, value in over.items():
            data[key] = value
        return data

    def write_recipe(self, data=None, name="recipe.json", raw=None):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(raw if raw is not None
                         else json.dumps(data or self.recipe(),
                                         indent=1))
        return path

    def run_tool(self, recipe_path=None, *flags):
        return run([recipe_path or self.write_recipe(),
                    "--config", self.config_path, *flags])

    def out_path(self, rel="CF/pieces/hipster.png"):
        return os.path.join(self.index_root, *rel.split("/"))

    def receipts(self):
        path = ac.RECEIPTS_NAME
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return [json.loads(l) for l in handle if l.strip()]

    def sidecar(self):
        with open(os.path.join(self.index_root, ai.SIDECAR_NAME),
                  encoding="utf-8") as handle:
            return json.load(handle)


class HappyPath(ComposeCase):
    def test_dry_run_writes_nothing_but_a_receipt(self):
        """W12. Dry run is the default and it still measures
        everything — the receipt carries the numbers."""
        before = sorted(os.listdir(os.path.join(self.index_root, "CF",
                                                "pieces")))
        code, out, _ = self.run_tool()
        self.assertEqual(code, CLEAN)
        self.assertFalse(os.path.exists(self.out_path()))
        self.assertEqual(sorted(os.listdir(os.path.join(
            self.index_root, "CF", "pieces"))), before)
        self.assertIn("DRY RUN", out)
        receipt = self.receipts()[-1]
        self.assertFalse(receipt["applied"])
        self.assertEqual(receipt["measured"]["components"], 2)

    def test_apply_writes_piece_row_and_sidecar_entry(self):
        code, _, _ = self.run_tool(None, "--apply")
        self.assertEqual(code, CLEAN)
        self.assertTrue(os.path.exists(self.out_path()))
        with open(os.path.join(self.index_root, ai.INDEX_NAME),
                  encoding="utf-8") as handle:
            rows = [l for l in handle.read().split("\n")
                    if "hipster.png" in l]
        self.assertEqual(len(rows), 1)
        self.assertEqual(ail.lint_row(rows[0]), [])
        entry = self.sidecar()["entries"]["CF/pieces/hipster.png"]
        self.assertEqual(entry["tool"], ac.TOOL_NAME)
        self.assertEqual(entry["kind"], "subject")
        self.assertEqual(len(entry["derived_from"]), 2)
        self.assertEqual([d["layer"] for d in entry["derived_from"]],
                         ["beard", "beanie"])

    def test_the_output_is_alpha_only(self):
        """W3: colour is a render-time decision, never baked in."""
        self.assertEqual(self.run_tool(None, "--apply")[0], CLEAN)
        image = Image.open(self.out_path())
        red, green, blue, alpha = image.split()
        for channel in (red, green, blue):
            self.assertEqual(channel.getbbox(), None)
        self.assertIsNotNone(alpha.getbbox())
        image.close()

    def test_recipe_hash_is_canonical_not_textual(self):
        """A reformat of the file must not change its identity."""
        pretty = self.write_recipe(name="pretty.json")
        ugly = self.write_recipe(
            name="ugly.json",
            raw=json.dumps(self.recipe(), separators=(",", ":")))
        self.assertEqual(self.run_tool(pretty)[0], CLEAN)
        first = self.receipts()[-1]["recipe_sha256"]
        self.assertEqual(self.run_tool(ugly)[0], CLEAN)
        self.assertEqual(self.receipts()[-1]["recipe_sha256"], first)


class RecipeDiscipline(ComposeCase):
    def test_duplicate_key_is_refused(self):
        raw = ('{"schema": 1, "schema": 1, "output": {}, '
               '"canvas": {}, "layers": []}')
        code, _, err = self.run_tool(self.write_recipe(raw=raw))
        self.assertEqual(code, ERROR)
        self.assertIn("DUPLICATE_KEY", err)
        self.assertIn("schema", err)

    def test_unknown_key_is_refused_at_every_level(self):
        for mutate in (
                lambda r: r.update({"extra": 1}),
                lambda r: r["output"].update({"extra": 1}),
                lambda r: r["canvas"].update({"extra": 1}),
                lambda r: r["layers"][0].update({"extra": 1}),
                lambda r: r["layers"][0]["placement"].update(
                    {"extra": 1})):
            data = self.recipe()
            mutate(data)
            code, _, err = self.run_tool(self.write_recipe(data))
            self.assertEqual(code, ERROR)
            self.assertIn("UNKNOWN_KEY", err)

    def test_missing_key_is_refused_never_defaulted(self):
        data = self.recipe()
        del data["canvas"]["alpha_floor"]
        code, _, err = self.run_tool(self.write_recipe(data))
        self.assertEqual(code, ERROR)
        self.assertIn("MISSING_KEY", err)
        self.assertIn("no defaults", err)

    def test_wrong_schema_is_refused(self):
        data = self.recipe()
        data["schema"] = 2
        code, _, err = self.run_tool(self.write_recipe(data))
        self.assertEqual(code, ERROR)
        self.assertIn("SCHEMA_UNSUPPORTED", err)

    def test_forward_reference_is_refused(self):
        """Placement resolves in ONE forward pass against frozen
        geometry, so a later layer's size does not exist yet."""
        data = self.recipe()
        data["layers"][0]["placement"]["scale"] = {
            "mode": "width_rel_to_layer", "layer": "beanie",
            "factor": 1.0}
        code, _, err = self.run_tool(self.write_recipe(data))
        self.assertEqual(code, ERROR)
        self.assertIn("FORWARD_REFERENCE", err)
        self.assertIn("beanie", err)

    def test_unknown_op_is_refused(self):
        data = self.recipe()
        data["layers"][0]["ops"] = [{"op": "posterise"}]
        code, _, err = self.run_tool(self.write_recipe(data))
        self.assertEqual(code, ERROR)
        self.assertIn("UNKNOWN_OP", err)

    def test_overlapping_luminance_ranges_are_refused(self):
        """RULE CHANGED 2026-09-06 (Fable): luminance is 0..1 in a
        recipe. These were 120 / 100..200 on the old 0..255 scale."""
        data = self.recipe()
        data["layers"][0]["ops"] = [
            {"op": "ink_layer", "luminance": "rec709", "lum_max": 0.47},
            {"op": "mid_layer", "luminance": "rec709", "lum_min": 0.39,
             "lum_max": 0.78}]
        code, _, err = self.run_tool(self.write_recipe(data))
        self.assertEqual(code, ERROR)
        self.assertIn("RANGE_OVERLAP", err)

    def test_allow_overlap_makes_it_deliberate(self):
        data = self.recipe()
        data["layers"][0]["ops"] = [
            {"op": "ink_layer", "luminance": "rec709", "lum_max": 0.47},
            {"op": "mid_layer", "luminance": "rec709", "lum_min": 0.39,
             "lum_max": 0.78, "allow_overlap": True}]
        data["output"]["expect_components"] = 2
        self.assertIn(self.run_tool(self.write_recipe(data))[0],
                      (CLEAN, FINDINGS, ERROR))   # not RANGE_OVERLAP
        for receipt in self.receipts():
            for refusal in receipt.get("refusals", []):
                self.assertNotEqual(refusal["kind"], "RANGE_OVERLAP")


class LicenceWall(ComposeCase):
    def test_five_spellings_that_must_fail(self):
        """W1's allowlist is CLOSED. These are near-misses, not
        variants: each is a different licence claim."""
        for spelling in ("CF Subscription",
                         "CF Subscription, unverified",
                         "CF Subscription verified",
                         "Public domain",
                         "AI-generated"):
            case = ComposeCase("run")
            case.setUp()
            case.rows = []
            case.entries = {}
            case.make_source("CF/pieces/beard.png", grey=20,
                             license_cell=spelling)
            case.make_source("CF/pieces/beanie.png", grey=200)
            case.write_index()
            code, _, err = case.run_tool()
            self.assertEqual(code, ERROR, spelling)
            self.assertIn("NOT_LICENSED_SOURCE", err)

    def test_case_and_whitespace_and_nfd_all_pass(self):
        """NFC -> strip -> casefold means the same claim spelled three
        ways is still the same claim."""
        import unicodedata
        for variant in ("  cf subscription, VERIFIED  ",
                        "CF SUBSCRIPTION, VERIFIED",
                        unicodedata.normalize(
                            "NFD", ai.CF_LICENSE_LITERAL)):
            self.assertIn(ac.license_key(variant),
                          ac.license_allowlist(), variant)

    def test_the_ai_row_basis_string_is_deliberately_absent(self):
        """The B5 spec says quote it from the live file via Sonnet and
        do NOT guess. Until it lands the allowlist holds exactly one
        form, and this test is what makes its absence visible instead
        of silent."""
        self.assertEqual(ac.LICENSE_ALLOWLIST_VERBATIM,
                         (ai.CF_LICENSE_LITERAL,))

    def test_an_unindexed_file_can_never_be_a_source(self):
        path = os.path.join(self.index_root, "CF", "pieces",
                            "mock.png")
        Image.new("RGBA", (50, 50), (0, 0, 0, 255)).save(path)
        data = self.recipe()
        data["layers"][0]["source_asset_id"] = "CF/pieces/mock.png"
        code, _, err = self.run_tool(self.write_recipe(data))
        self.assertEqual(code, ERROR)
        self.assertIn("SOURCE_NOT_INDEXED", err)

    def test_a_compound_row_cannot_be_a_source(self):
        self.rows.append(ail.format_row(
            ["`CF/pieces/a.png` + `CF/pieces/b.png`",
             ai.CF_LICENSE_LITERAL, "flat", "x", "tonal", "flat",
             "Product 1"]))
        self.entries["CF/pieces/a.png"] = {"sha256": "a" * 64,
                                           "product_id": "1",
                                           "ingested_utc": "2026-09-06"}
        self.write_index()
        data = self.recipe()
        data["layers"][0]["source_asset_id"] = "CF/pieces/a.png"
        code, _, err = self.run_tool(self.write_recipe(data))
        self.assertEqual(code, ERROR)
        self.assertIn("SOURCE_MULTI_PATH", err)

    def test_a_changed_file_is_a_provenance_mismatch(self):
        path = os.path.join(self.index_root, "CF", "pieces",
                            "beard.png")
        image = Image.open(path)
        edited = image.copy()
        image.close()
        edited.putpixel((0, 0), (9, 9, 9, 255))
        edited.save(path)
        edited.close()
        code, _, err = self.run_tool()
        self.assertEqual(code, ERROR)
        self.assertIn("PROVENANCE_MISMATCH", err)


class ReadOnce(ComposeCase):
    def test_a_file_swapped_after_the_check_cannot_get_in(self):
        """W2, TOCTOU: the bytes that were hashed are the bytes that
        get decoded. A swap after open() reaches nothing, because the
        path is never reopened."""
        path = os.path.join(self.index_root, "CF", "pieces",
                            "beard.png")
        real = open

        def swapping_open(target, *args, **kwargs):
            mode = args[0] if args else kwargs.get("mode", "r")
            handle = real(target, *args, **kwargs)
            if target == path and mode == "rb":
                data = handle.read()
                handle.close()
                Image.new("RGBA", (200, 200),
                          (255, 0, 0, 255)).save(path)
                return io.BytesIO(data)
            return handle

        with mock.patch("builtins.open", swapping_open):
            code, _, _ = self.run_tool(None, "--apply")
        self.assertEqual(code, CLEAN)
        receipt = self.receipts()[-1]
        beard = [l for l in receipt["layers"] if l["id"] == "beard"][0]
        self.assertEqual(beard["sha256_at_compose"],
                         self.entries["CF/pieces/beard.png"]["sha256"])


class Ops(ComposeCase):
    def test_ink_layer_masks_alpha_before_thresholding(self):
        """A transparent BLACK pixel is not ink. Without the a>0 mask
        every transparent pixel reads luminance 0 and the whole canvas
        becomes the ink layer."""
        image = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
        image.paste((10, 10, 10, 255), (2, 2, 5, 5))
        alpha = ac.luminance_band(
            image, ac.LUMINANCE_COEFFS["rec709"], 0.0, 0.47)
        self.assertEqual(alpha.getbbox(), (2, 2, 5, 5))
        image.close()

    def test_outline_thicken_grows_the_alpha(self):
        """Same footprint the MaxFilter gave: grow 3 px on every side.
        """
        image = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        image.paste((0, 0, 0, 255), (40, 40, 60, 60))
        before = image.split()[3].getbbox()
        grown = ac.apply_op(image, {"op": "outline_thicken",
                                    "mode": "px", "amount": 3})
        after = grown.split()[3].getbbox()
        self.assertEqual(before, (40, 40, 60, 60))
        self.assertEqual(after, (37, 37, 63, 63))
        image.close()
        grown.close()


class LuminanceScale(ComposeCase):
    """Fable bench, the one that mattered. Every document in this
    system writes "lum < 0.35"; the first build range-checked 0..255,
    so 0.35 passed, matched only pure black, emptied the beanie layer
    and went GREEN with the beard's own two parts. Wrong AND passing."""

    def test_a_0_to_255_value_is_refused_by_range(self):
        data = self.recipe()
        data["layers"][0]["ops"] = [
            {"op": "ink_layer", "luminance": "rec709", "lum_max": 89}]
        code, _, err = self.run_tool(self.write_recipe(data))
        self.assertEqual(code, ERROR)
        self.assertIn("RECIPE_RANGE", err)
        self.assertIn("0..1", err)

    def test_the_scale_is_applied_once_inside_the_band(self):
        """0.35 must mean 35% of full luminance, not 'darker than
        0.35/255'. The beanie grey here is 200 -> 0.784."""
        image = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
        image.paste((200, 200, 200, 255), (2, 2, 6, 6))
        dark = ac.luminance_band(image, ac.LUMINANCE_COEFFS["rec709"],
                                 0.0, 0.35)
        light = ac.luminance_band(image, ac.LUMINANCE_COEFFS["rec709"],
                                  0.35, 1.0)
        self.assertIsNone(dark.getbbox())
        self.assertEqual(light.getbbox(), (2, 2, 6, 6))
        image.close()
        self.assertEqual(ac.LUM_MAX, 1.0)
        self.assertEqual(ac.LUMINANCE_SCALE, 255.0)


class EmptyLayer(ComposeCase):
    def test_a_layer_that_matches_nothing_refuses(self):
        """The green-by-coincidence run, as a mechanism. The beard is
        grey 20 (lum 0.078); nothing is darker than 0.01."""
        data = self.recipe()
        data["layers"][0]["ops"] = [
            {"op": "ink_layer", "luminance": "rec709", "lum_max": 0.01}]
        code, _, err = self.run_tool(self.write_recipe(data))
        self.assertEqual(code, ERROR)
        self.assertIn("EMPTY_LAYER", err)
        self.assertIn("beard", err)
        self.assertIn("ink_layer", err)

    def test_the_op_chain_is_named_in_the_refusal(self):
        data = self.recipe()
        data["layers"][1]["ops"] = [
            {"op": "solid"},
            {"op": "ink_layer", "luminance": "rec601", "lum_max": 0.0}]
        code, _, err = self.run_tool(self.write_recipe(data))
        self.assertEqual(code, ERROR)
        self.assertIn("EMPTY_LAYER", err)
        self.assertIn("solid -> ink_layer", err)


class ThickenKernel(ComposeCase):
    def test_dilate_is_byte_identical_to_max_filter(self):
        """W-perf. A square max is separable, so this dilates in
        doubling steps instead of running an O(k^2) MaxFilter. Equality
        asserted on the GREY channel, not just the footprint."""
        from PIL import ImageChops, ImageFilter
        alpha = Image.new("L", (300, 300), 0)
        for x in range(20, 280, 47):
            alpha.paste(255, (x, 40, x + 3, 260))
        alpha.paste(255, (150, 150, 151, 151))      # one lone pixel
        alpha.paste(128, (60, 60, 90, 90))          # a soft patch
        for radius in (0, 1, 3, 8, 20):
            mine = ac.dilate_alpha(alpha, radius)
            theirs = alpha.filter(
                ImageFilter.MaxFilter(2 * radius + 1)) if radius \
                else alpha
            diff = ImageChops.difference(mine, theirs)
            self.assertEqual(sum(diff.histogram()[1:]), 0,
                             "radius %d differs" % radius)
        alpha.close()

    def test_a_lone_pixel_survives_the_grow(self):
        """The exact case a box-blur-then-threshold loses: one opaque
        pixel averaged over a 41x41 box rounds to 0 in uint8."""
        alpha = Image.new("L", (100, 100), 0)
        alpha.paste(255, (50, 50, 51, 51))
        grown = ac.dilate_alpha(alpha, 20)
        self.assertEqual(grown.getbbox(), (30, 30, 71, 71))
        alpha.close()


class EdgesAndMeasurement(ComposeCase):
    def _measure_at_floor(self, floor):
        data = self.recipe()
        data["canvas"]["alpha_floor"] = floor
        recipe = ac.load_recipe(self.write_recipe(data))
        rows = ac.index_rows(self.index_root)
        entries = ai.load_sidecar(
            os.path.join(self.index_root, ai.SIDECAR_NAME))["entries"]
        sources = {layer["id"]: ac.read_source(
            layer["source_asset_id"], self.index_root, rows, entries)
            for layer in recipe["layers"]}
        image = ac.compose(recipe, sources, {})
        measured = ac.measure_output(image, recipe["canvas"])
        image.close()
        for source in sources.values():
            source["image"].close()
        return measured

    def test_alpha_floor_cuts_the_halo_edge_unmoved(self):
        """W9, measured not asserted-by-hope. play_forge's OVERLAP wall
        binarizes at a>0, so LANCZOS ringing is NOT harmless: at floor
        0 this composite measures TEN components — eight of them are
        halo. The sweep takes it to the real two.

        MEASURED on this fixture (120px source -> 400px, LANCZOS), not
        guessed: bbox [90, 70, 390, 718] at floor 0 becomes
        [95, 74, 385, 714] at floor 16 — the edge moves 5/4/5/4 px, and
        ink drops 128088 -> 124100. Fable measured a 19px halo at
        50 -> 400px; a gentler upsample gives a gentler halo, and the
        VISIBLE edge is unmoved either way."""
        loose = self._measure_at_floor(0)
        swept = self._measure_at_floor(16)
        self.assertEqual(loose["components"], 10)
        self.assertEqual(swept["components"], 2)
        self.assertEqual(loose["footprint_bbox"], [90, 70, 390, 718])
        self.assertEqual(swept["footprint_bbox"], [95, 74, 385, 714])
        self.assertEqual(loose["ink_px"], 128088)
        self.assertEqual(swept["ink_px"], 124100)

    def test_upsample_cap_names_the_ratio(self):
        data = self.recipe()
        data["canvas"]["max_layer_upsample"] = 1.5
        data["layers"][0]["placement"]["scale"] = {"mode": "px",
                                                   "width": 4000}
        code, _, err = self.run_tool(self.write_recipe(data))
        self.assertEqual(code, ERROR)
        self.assertIn("UPSAMPLE_EXCEEDED", err)
        self.assertIn("20.000x", err)

    def test_component_mismatch_names_both_numbers(self):
        data = self.recipe()
        data["output"]["expect_components"] = 5
        code, _, err = self.run_tool(self.write_recipe(data))
        self.assertEqual(code, ERROR)
        self.assertIn("COMPONENT_MISMATCH", err)
        self.assertIn("2 component", err)
        self.assertIn("expects 5", err)

    def test_thin_stroke_is_a_finding_not_a_refusal(self):
        """W10. The piece still writes; the number is in the receipt
        and Khai's eye decides."""
        data = self.recipe()
        data["canvas"]["min_stroke_px"] = 400
        data["canvas"]["min_stroke_survival"] = 0.9
        code, out, _ = self.run_tool(self.write_recipe(data), "--apply")
        self.assertEqual(code, FINDINGS)
        self.assertIn("W10 STROKE", out)
        self.assertTrue(os.path.exists(self.out_path()))

    def test_the_stroke_kernel_is_play_forges_own(self):
        """W10 says import it, never retype. My first draft retyped it
        WRONG (2*n+1 instead of round-up-to-odd); this is the
        mechanism that would have caught it."""
        with open(ac.__file__, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("pf.stroke_kernel(", source)
        self.assertEqual(pf.stroke_kernel(3), 3)
        self.assertEqual(pf.stroke_kernel(4), 5)


class KindRoundTrip(ComposeCase):
    def test_red_on_the_colon_form(self):
        """Fable's bench string: 'composite:subject — cartoon …' has
        two kinds in its head clause and infers nothing."""
        data = self.recipe()
        data["output"]["style"] = ("composite:subject — cartoon beard "
                                   "and beanie")
        code, _, err = self.run_tool(self.write_recipe(data))
        self.assertEqual(code, ERROR)
        self.assertIn("KIND_MISMATCH", err)
        self.assertIsNone(pn.infer_kind(data["output"]["style"])[0])

    def test_green_on_the_comma_form(self):
        self.assertEqual(pn.infer_kind(STYLE), ("subject", "subject"))
        self.assertEqual(self.run_tool()[0], CLEAN)

    def test_a_style_that_infers_a_different_kind_refuses(self):
        data = self.recipe()
        data["output"]["kind"] = "ornament"
        code, _, err = self.run_tool(self.write_recipe(data))
        self.assertEqual(code, ERROR)
        self.assertIn("KIND_MISMATCH", err)


class RowAndSidecar(ComposeCase):
    def test_the_row_has_one_path_and_a_used_in_value(self):
        self.assertEqual(self.run_tool(None, "--apply")[0], CLEAN)
        row = self.receipts()[-1] and None
        with open(os.path.join(self.index_root, ai.INDEX_NAME),
                  encoding="utf-8") as handle:
            line = [l for l in handle.read().split("\n")
                    if "hipster.png" in l][0]
        self.assertEqual(ail.asset_paths(line), ["CF/pieces/hipster.png"])
        self.assertEqual(ail.lint_row(line), [])
        self.assertIn("composed ", ail.split_cells(line)[6])

    def test_used_in_is_a_sibling_of_asset_ingests_own(self):
        """Never invented per run: the same shape, a different verb."""
        self.assertTrue(ac.USED_IN_FMT.endswith("— not yet used"))
        self.assertTrue(ai.USED_IN_FMT.endswith("— not yet used"))
        self.assertNotEqual(ac.USED_IN_FMT, ai.USED_IN_FMT)

    def test_derived_from_records_one_entry_per_layer(self):
        """The same source twice gives TWO records — a layer is the
        unit, not a source."""
        data = self.recipe()
        data["layers"][1]["source_asset_id"] = "CF/pieces/beard.png"
        data["output"]["expect_components"] = 2
        self.assertIn(self.run_tool(self.write_recipe(data),
                                    "--apply")[0], (CLEAN, FINDINGS))
        entry = self.sidecar()["entries"]["CF/pieces/hipster.png"]
        self.assertEqual([d["asset_id"] for d in entry["derived_from"]],
                         ["CF/pieces/beard.png", "CF/pieces/beard.png"])

    def test_a_compose_entry_without_provenance_is_refused(self):
        """Fail-closed on re-read: an entry claiming this tool and
        carrying no derived_from is a lie about where a piece came
        from."""
        self.entries["CF/pieces/ghost.png"] = {
            "sha256": "b" * 64, "product_id": "1",
            "ingested_utc": "2026-09-06", "tool": ac.TOOL_NAME}
        self.write_index()
        code, _, err = self.run_tool()
        self.assertEqual(code, ERROR)
        self.assertIn("SIDECAR_NO_PROVENANCE", err)

    def test_asset_ingest_entries_need_no_derived_from(self):
        """The rule applies to THIS tool's entries only."""
        self.assertEqual(self.run_tool()[0], CLEAN)


class SidecarVersion(ComposeCase):
    def test_version_is_2_and_entries_name_their_tool(self):
        self.assertEqual(ai.SIDECAR_VERSION, 2)
        self.assertEqual(self.run_tool(None, "--apply")[0], CLEAN)
        data = self.sidecar()
        self.assertEqual(data["version"], 2)
        self.assertEqual(
            data["entries"]["CF/pieces/hipster.png"]["tool"],
            ac.TOOL_NAME)

    def test_a_version_1_sidecar_is_still_readable(self):
        path = os.path.join(self.index_root, ai.SIDECAR_NAME)
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        data["version"] = 1
        for entry in data["entries"].values():
            entry.pop("tool", None)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        self.assertEqual(ai.load_sidecar(path)["version"], 1)
        self.assertEqual(self.run_tool()[0], CLEAN)

    def test_play_new_and_play_forge_read_a_v2_sidecar(self):
        """The other two loaders must not care about the bump."""
        self.assertEqual(self.run_tool(None, "--apply")[0], CLEAN)
        entries = pn.load_sidecar(self.index_root)
        self.assertIn("CF/pieces/hipster.png", entries)
        forge = pf.load_sidecar(self.index_root)
        self.assertIn("CF/pieces/hipster.png", forge)


class Writes(ComposeCase):
    def test_an_existing_output_refuses_without_overwrite(self):
        self.assertEqual(self.run_tool(None, "--apply")[0], CLEAN)
        code, _, err = self.run_tool(None, "--apply")
        self.assertEqual(code, ERROR)
        self.assertIn("OUTPUT_EXISTS", err)

    def test_overwrite_makes_it_deliberate(self):
        self.assertEqual(self.run_tool(None, "--apply")[0], CLEAN)
        self.assertEqual(self.run_tool(None, "--apply",
                                       "--overwrite")[0], CLEAN)

    def test_an_output_outside_pieces_is_refused(self):
        data = self.recipe()
        data["output"]["path"] = "CF/renders/hipster.png"
        code, _, err = self.run_tool(self.write_recipe(data))
        self.assertEqual(code, ERROR)
        self.assertIn("OUTPUT_NOT_IN_PIECES", err)

    def test_two_runs_are_byte_identical(self):
        """W11: BOTH hashes asserted, and the report says which. Pixel
        equality alone would miss a compress_level change; file
        equality alone would miss nothing here but says less."""
        self.assertEqual(self.run_tool(None, "--apply")[0], CLEAN)
        with open(self.out_path(), "rb") as handle:
            first_file = ac.sha256_bytes(handle.read())
        first_pixels = Image.open(self.out_path()).tobytes()
        self.assertEqual(self.run_tool(None, "--apply",
                                       "--overwrite")[0], CLEAN)
        with open(self.out_path(), "rb") as handle:
            self.assertEqual(ac.sha256_bytes(handle.read()),
                             first_file, "FILE hash differs")
        self.assertEqual(Image.open(self.out_path()).tobytes(),
                         first_pixels, "PIXEL hash differs")

    def test_compress_level_is_the_recipes(self):
        data = self.recipe()
        data["output"]["compress_level"] = 0
        self.assertEqual(self.run_tool(self.write_recipe(data),
                                       "--apply")[0], CLEAN)
        loose = os.path.getsize(self.out_path())
        data["output"]["compress_level"] = 9
        self.assertEqual(self.run_tool(self.write_recipe(data),
                                       "--apply", "--overwrite")[0],
                         CLEAN)
        self.assertLess(os.path.getsize(self.out_path()), loose)


class HouseStyle(ComposeCase):
    def test_json_parity_from_one_dict(self):
        code, out, _ = self.run_tool(None, "--json")
        self.assertEqual(code, CLEAN)
        payload = json.loads(out)
        self.assertEqual(payload["measured"]["components"], 2)
        self.assertEqual(payload["note"], ac.NO_TASTE_NOTE)

    def test_unknown_flag_is_exit_2(self):
        with mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                ac.main(["--bogus"])
        self.assertEqual(caught.exception.code, ERROR)

    def test_config_fails_closed(self):
        for mutate in ({"unknown_key": 1},
                       {"index_root": ""}):
            self.write_config(**mutate)
            code, _, err = self.run_tool()
            self.assertEqual(code, ERROR)
            self.assertIn("CONFIG", err)
        os.remove(self.config_path)
        self.assertEqual(self.run_tool()[0], ERROR)

    def test_explain_says_a_green_run_is_not_a_good_piece(self):
        code, out, _ = run(["--explain"])
        self.assertEqual(code, CLEAN)
        self.assertIn(ac.NO_TASTE_NOTE.upper(), out)

    def test_every_refusal_names_its_rule(self):
        data = self.recipe()
        del data["canvas"]["alpha_floor"]
        code, out, _ = self.run_tool(self.write_recipe(data), "--json")
        self.assertEqual(code, ERROR)
        refusal = json.loads(out)["refusals"][0]
        self.assertTrue(refusal["kind"])
        self.assertIn("alpha_floor", refusal["reason"])

    def test_a_receipt_lands_on_every_terminating_path(self):
        self.assertEqual(self.run_tool()[0], CLEAN)
        data = self.recipe()
        data["schema"] = 99
        self.assertEqual(self.run_tool(self.write_recipe(data))[0],
                         ERROR)
        kinds = [r["refusals"][0]["kind"] if r["refusals"] else "OK"
                 for r in self.receipts()]
        self.assertIn("OK", kinds)
        self.assertIn("SCHEMA_UNSUPPORTED", kinds)

    def test_crash_floor_is_exit_2(self):
        with mock.patch.object(ac, "run_compose",
                               side_effect=RuntimeError("injected")):
            code, _, err = self.run_tool()
        self.assertEqual(code, ERROR)
        self.assertIn("CRASH (RuntimeError): injected", err)

    def test_dep_missing_refuses(self):
        with mock.patch.object(ac, "FLEET_IMPORT_ERROR",
                               "ModuleNotFoundError: PIL"):
            code, _, err = self.run_tool()
        self.assertEqual(code, ERROR)
        self.assertIn("DEP_MISSING", err)


if __name__ == "__main__":
    unittest.main()
