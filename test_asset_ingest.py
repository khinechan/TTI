#!/usr/bin/env python3
"""Tests for asset_ingest.py + its shared modules (MC FLEET B3,
T1-T16 plus lint/config/zip cases).

pytest is specced but not installed in this environment (flagged
deviation, D-394) — unittest-style, which pytest collects unchanged.

Every fixture is synthetic and lives in a temp dir; no CF asset, no
vault path, no network. Receipts are redirected into the temp dir so
the repo never grows a receipts file from a test run.
"""

import io
import json
import os
import shutil
import tempfile
import unittest
import unicodedata
import zipfile
from unittest import mock

from PIL import Image, ImageDraw

import asset_index_lint as ail
import asset_ingest as ai
import play_schema
import recolor


PRODUCT = "4242"
HEADER = ("| Asset (path under `Merch/Design Assets/`) | License | "
          "Style | Niche tags | Colors | Recolor | Used in |")
SEPARATOR = "|---|---|---|---|---|---|---|"


def make_sheet(path, boxes, size=(800, 200), alpha=255):
    """Transparent RGBA sheet with opaque rectangles at the given
    (left, top, right, bottom) boxes."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for box in boxes:
        draw.rectangle(box, fill=(120, 40, 40, alpha))
    img.save(path)
    img.close()


class IngestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ai_test_")
        self.addCleanup(shutil.rmtree, self.tmp)
        self.index_root = os.path.join(self.tmp, "design-assets")
        self.assets_dir = os.path.join(self.index_root, "ingested")
        self.license_dir = os.path.join(self.tmp, "licenses")
        os.makedirs(self.assets_dir)
        os.makedirs(self.license_dir)
        self.index_file = os.path.join(self.index_root,
                                       ai.INDEX_NAME)
        with open(self.index_file, "w", encoding="utf-8") as fh:
            fh.write(HEADER + "\n" + SEPARATOR + "\n")
        self.config_path = os.path.join(self.tmp, "config.json")
        self.write_config()
        self.input_dir = os.path.join(self.tmp,
                                      "Test-Bundle-%s" % PRODUCT)
        os.makedirs(self.input_dir)
        # receipts land in the temp dir, never in the repo
        patcher = mock.patch.object(ai, "BASE_DIR", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_config(self, cf_subscription="valid"):
        """F3: licensing default is a valid CF subscription in the
        config (D-082) — no per-folder record file anywhere."""
        cfg = {"index_root": self.index_root,
               "assets_dir": self.assets_dir,
               "license_dir": self.license_dir}
        if cf_subscription == "valid":
            cf_subscription = {"status": "verified",
                               "valid_through": "2030-01-01",
                               "record_path": "vault/cf-record.md"}
        if cf_subscription is not None:
            cfg["cf_subscription"] = cf_subscription
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh)

    def grant_folder_override(self):
        with open(os.path.join(self.input_dir,
                               ai.LICENSE_RECORD_NAME), "w",
                  encoding="utf-8") as fh:
            fh.write("CF Subscription, verified\n")

    def run_tool(self, *flags):
        with mock.patch("sys.stdout", io.StringIO()), \
                mock.patch("sys.stderr", io.StringIO()):
            return ai.main(["--config", self.config_path, *flags])

    def ingest_report(self, *flags):
        config = ai.load_config(self.config_path)
        opts = {"confirm": None, "confirm_file": None,
                "reingest": "--reingest" in flags, "apply": False,
                "min_size": ai.DEFAULT_MIN_SIZE,
                "gap_close": 0,
                "alpha_threshold": ai.DEFAULT_ALPHA_THRESHOLD,
                "style": "pending", "tags": "pending",
                "colors": "pending", "recolor_mode": "pending"}
        for flag in flags:
            if flag.startswith("gap_close="):
                opts["gap_close"] = int(flag.split("=")[1])
            if flag.startswith("alpha_threshold="):
                opts["alpha_threshold"] = int(flag.split("=")[1])
            if flag == "prefer_vector":
                opts["prefer_vector"] = True
        report = ai.run_ingest(config, self.input_dir, opts)
        ai.append_receipt(report)
        return report

    def out_dir(self):
        return ai.product_out_dir(ai.load_config(self.config_path),
                                  PRODUCT)

    def receipts(self):
        path = os.path.join(self.tmp, ai.RECEIPTS_NAME)
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def index_rows(self):
        with open(self.index_file, encoding="utf-8") as fh:
            return [line for line in fh.read().split("\n")
                    if line.strip()]

    def total_proposals(self, report):
        return [p for s in report["sources"] for p in s["proposals"]]


class T01Proposals(IngestCase):
    def test_separated_14_touching_1_no_autocatalog(self):
        """T1: 14 separated -> 14 proposals; touching -> 1; refuses
        to auto-catalog in BOTH cases (W1)."""
        make_sheet(os.path.join(self.input_dir, "sheet.png"),
                   [(10 + i * 55, 10, 10 + i * 55 + 29, 39)
                    for i in range(14)])
        report = self.ingest_report()
        self.assertEqual(report["exit_code"], 1)
        self.assertEqual(len(self.total_proposals(report)), 14)
        # contact sheet with every box exists
        self.assertTrue(os.path.exists(os.path.join(
            self.out_dir(), report["sources"][0]["contact_sheet"])))
        # NOTHING cataloged: no rows, no pieces, no sidecar
        self.assertEqual(len(self.index_rows()), 2)  # header + sep
        self.assertFalse(os.path.exists(
            os.path.join(self.out_dir(), ai.PIECES_DIRNAME)))
        self.assertFalse(os.path.exists(
            ai.sidecar_path(ai.load_config(self.config_path))))
        # touching squares -> ONE proposal, still nothing cataloged
        make_sheet(os.path.join(self.input_dir, "sheet.png"),
                   [(10 + i * 30, 10, 10 + i * 30 + 30, 40)
                    for i in range(14)])
        report = self.ingest_report()
        self.assertEqual(len(self.total_proposals(report)), 1)
        self.assertEqual(len(self.index_rows()), 2)


class T02LikelyMerge(IngestCase):
    def test_two_pieces_overlapping_flagged(self):
        """T2: two diamonds overlapping ~2px -> ONE proposal, flagged
        likely-merge."""
        img = Image.new("RGBA", (220, 120), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        for cx in (60, 138):
            draw.polygon([(cx, 20), (cx + 40, 60), (cx, 100),
                          (cx - 40, 60)], fill=(20, 20, 20, 255))
        img.save(os.path.join(self.input_dir, "pair.png"))
        img.close()
        report = self.ingest_report()
        proposals = self.total_proposals(report)
        self.assertEqual(len(proposals), 1)
        self.assertTrue(proposals[0]["likely_merge"])

    def test_separated_pieces_not_flagged(self):
        make_sheet(os.path.join(self.input_dir, "two.png"),
                   [(10, 10, 40, 40), (100, 10, 130, 40)])
        report = self.ingest_report()
        proposals = self.total_proposals(report)
        self.assertEqual(len(proposals), 2)
        self.assertFalse(any(p["likely_merge"] for p in proposals))


class T03GapAndThreshold(IngestCase):
    def test_gap_close_reruns_as_one_piece(self):
        """T3: 3px gap -> 2 pieces by default, 1 with --gap-close 2."""
        make_sheet(os.path.join(self.input_dir, "gappy.png"),
                   [(10, 10, 39, 39), (43, 10, 72, 39)])
        report = self.ingest_report()
        self.assertEqual(len(self.total_proposals(report)), 2)
        report = self.ingest_report("gap_close=2")
        self.assertEqual(len(self.total_proposals(report)), 1)

    def test_alpha_threshold_changes_count(self):
        """T3b: an alpha-60 bridge joins at threshold 0, splits at
        128; both runs report their counts."""
        img = Image.new("RGBA", (160, 60), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle((10, 10, 49, 49), fill=(0, 0, 0, 255))
        draw.rectangle((80, 10, 119, 49), fill=(0, 0, 0, 255))
        draw.rectangle((50, 25, 79, 34), fill=(0, 0, 0, 60))
        img.save(os.path.join(self.input_dir, "bridge.png"))
        img.close()
        at_zero = self.ingest_report("alpha_threshold=0")
        at_128 = self.ingest_report("alpha_threshold=128")
        self.assertEqual(len(self.total_proposals(at_zero)), 1)
        self.assertEqual(len(self.total_proposals(at_128)), 2)
        self.assertEqual(at_zero["counts"]["proposed"], 1)
        self.assertEqual(at_128["counts"]["proposed"], 2)


class T04T05T06License(IngestCase):
    def test_jpeg_only_with_license_is_held_not_refused(self):
        """T4: JPEG-only folder WITH a license record -> NEEDS_HUMAN,
        held, exit 1, never NOT_LICENSED."""
        img = Image.new("RGB", (200, 100), (250, 250, 250))
        img.save(os.path.join(self.input_dir, "preview.jpg"))
        img.close()
        report = self.ingest_report()
        self.assertEqual(report["exit_code"], 1)
        self.assertEqual(len(report["needs_human"]), 1)
        reasons = report["needs_human"][0]["reasons"]
        self.assertTrue(any("JPEG-only" in r for r in reasons))
        self.assertEqual(report["sources"], [])   # held, no proposals
        self.assertEqual(report["refusals"], [])

    def test_no_license_record_is_hard_refusal(self):
        """T5 (+T15): no subscription in config AND no folder
        override -> NOT_LICENSED_ASSET, exit 2, receipt still
        written."""
        self.write_config(cf_subscription=None)
        make_sheet(os.path.join(self.input_dir, "art.png"),
                   [(10, 10, 60, 60)])
        before = len(self.receipts())
        code = self.run_tool(self.input_dir)
        self.assertEqual(code, 2)
        receipts = self.receipts()
        self.assertEqual(len(receipts), before + 1)
        self.assertEqual(receipts[-1]["refusals"][0]["kind"],
                         "NOT_LICENSED_ASSET")

    def test_transparent_cutout_with_license_accepted(self):
        """T6: transparent PNG cut-out + license -> accepted (its
        identical transparent corners are NOT a preview hint)."""
        make_sheet(os.path.join(self.input_dir, "cutout.png"),
                   [(20, 20, 90, 90)])
        report = self.ingest_report()
        self.assertEqual(report["needs_human"], [])
        self.assertEqual(len(self.total_proposals(report)), 1)


class T07CantConvert(IngestCase):
    def test_no_converter_is_loud_never_a_skip(self):
        """T7: EPS with no converter -> CANT_CONVERT recorded with the
        reason; counts NOT inflated."""
        with open(os.path.join(self.input_dir, "vector.eps"),
                  "wb") as fh:
            fh.write(b"%!PS-Adobe-3.0 EPSF-3.0\n")
        with mock.patch.object(
                ai, "probe_converters",
                lambda: {"gs": None, "inkscape": None}):
            report = self.ingest_report()
        self.assertEqual(report["counts"]["converted"], 0)
        self.assertEqual(report["counts"]["cant_convert"], 1)
        self.assertEqual(len(report["cant_convert"]), 1)
        self.assertIn("no converter available",
                      report["cant_convert"][0]["reason"])
        self.assertEqual(report["counts"]["inventoried"], 1)


class T08Duplicate(IngestCase):
    def _catalog_one(self):
        make_sheet(os.path.join(self.input_dir, "art.png"),
                   [(10, 10, 80, 80)])
        self.assertEqual(self.run_tool(self.input_dir), 1)
        self.assertEqual(
            self.run_tool(self.input_dir, "--confirm", "all"), 1)

    def test_duplicate_refused_without_reingest(self):
        """T8: same product id again -> refused; --reingest allows."""
        self._catalog_one()
        code = self.run_tool(self.input_dir)
        self.assertEqual(code, 2)
        self.assertEqual(self.receipts()[-1]["refusals"][0]["kind"],
                         "DUPLICATE_PRODUCT_ID")
        code = self.run_tool(self.input_dir, "--reingest")
        self.assertEqual(code, 1)


class T09Nfc(unittest.TestCase):
    def test_nfd_and_nfc_names_same_product_id(self):
        """T9: NFD folder name -> same product id as its NFC twin."""
        nfd = unicodedata.normalize("NFD", "Café-Bundle-777")
        nfc = unicodedata.normalize("NFC", "Café-Bundle-777")
        self.assertNotEqual(nfd, nfc)
        self.assertEqual(ai.parse_product_id(nfd), "777")
        self.assertEqual(ai.parse_product_id(nfc), "777")
        self.assertEqual(ai.parse_product_id("/x/" + nfd),
                         ai.parse_product_id("/y/" + nfc))

    def test_no_trailing_digits_is_none(self):
        self.assertIsNone(ai.parse_product_id("no-id-here"))


class T10LintAndRows(IngestCase):
    def test_lint_rules(self):
        good = ("| `a/b.png` | CF Subscription, verified | cartoon | "
                "dog | tonal | flat | Product 28 |")
        self.assertEqual(ail.lint_row(good), [])
        self.assertTrue(any("L2" in f for f in ail.lint_row(
            "| `a.png` | x | y | z | c | r |")))
        self.assertTrue(any("L4" in f for f in ail.lint_row(
            "| `a.png` | x |  | z | c | r | u |")))
        self.assertTrue(any("L3" in f for f in ail.lint_row(
            "| a.png | x | y | z | c | r | u |")))
        self.assertEqual(ail.asset_path(good), "a/b.png")

    def test_backticked_pipes_do_not_split_cells(self):
        row = ("| `a.png` | lives in `Sessions/x.md` Parts `5|7` | y "
               "| z | c | r | u |")
        self.assertEqual(ail.lint_row(row), [])
        cells = ail.split_cells(row)
        self.assertEqual(len(cells), 7)
        self.assertIn("`5|7`", cells[1])

    def test_header_and_separator_recognized(self):
        self.assertTrue(ail.is_header_row(HEADER))
        self.assertTrue(ail.is_separator_row(SEPARATOR))
        self.assertFalse(ail.is_separator_row(HEADER))

    def test_failing_row_never_appended_table_stays_7(self):
        """T10: an empty cell (forced via --style '') is rejected
        BEFORE append; the index file does not change."""
        make_sheet(os.path.join(self.input_dir, "art.png"),
                   [(10, 10, 80, 80)])
        self.run_tool(self.input_dir)
        code = self.run_tool(self.input_dir, "--confirm", "all",
                             "--style", "")
        self.assertEqual(code, 1)          # piece saved, row rejected
        self.assertEqual(len(self.index_rows()), 2)
        # valid confirm appends a row that passes the lint
        self.run_tool(self.input_dir, "--confirm", "all")
        rows = self.index_rows()
        self.assertEqual(len(rows), 3)
        self.assertEqual(ail.lint_row(rows[-1]), [])
        self.assertEqual(len(ail.split_cells(rows[-1])), 7)


class T11T12Sidecar(IngestCase):
    def test_sidecar_entry_written_keyed_by_path(self):
        """T11: sha256 + product id + date, keyed by the row's path
        cell."""
        make_sheet(os.path.join(self.input_dir, "art.png"),
                   [(10, 10, 80, 80)])
        self.run_tool(self.input_dir)
        self.run_tool(self.input_dir, "--confirm", "all")
        rows = self.index_rows()
        key = ail.asset_path(rows[-1])
        with open(ai.sidecar_path(
                ai.load_config(self.config_path)),
                encoding="utf-8") as fh:
            sidecar = json.load(fh)
        entry = sidecar["entries"][key]
        piece_abs = os.path.join(self.index_root, *key.split("/"))
        self.assertEqual(entry["sha256"], ai.hash_file(piece_abs))
        self.assertEqual(entry["product_id"], PRODUCT)
        self.assertTrue(entry["ingested_utc"].startswith("20"))

    def test_backfill_proposes_writes_only_with_apply(self):
        """T12: --backfill proposes N entries, writes nothing without
        --apply."""
        for name in ("old1.png", "old2.png"):
            make_sheet(os.path.join(self.index_root, name),
                       [(0, 0, 30, 30)], size=(40, 40))
            ai.append_index_line(
                self.index_file,
                ail.format_row(("`%s`" % name, "CF Subscription, "
                                "verified", "cartoon", "dog", "tonal",
                                "flat", "Product 1")))
        sidecar_file = ai.sidecar_path(
            ai.load_config(self.config_path))
        code = self.run_tool("--backfill")
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(sidecar_file))
        code = self.run_tool("--backfill", "--apply")
        self.assertEqual(code, 1)
        with open(sidecar_file, encoding="utf-8") as fh:
            entries = json.load(fh)["entries"]
        self.assertEqual(sorted(entries), ["old1.png", "old2.png"])
        self.assertEqual(entries["old1.png"]["sha256"],
                         ai.hash_file(os.path.join(self.index_root,
                                                   "old1.png")))


class T13Recolor(unittest.TestCase):
    def test_recolor_preserves_antialiasing_kills_old_hue(self):
        """T13: alpha byte-identical; zero old-hue pixels remain."""
        big = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
        ImageDraw.Draw(big).ellipse((20, 20, 180, 180),
                                    fill=(200, 30, 30, 255))
        img = big.resize((50, 50))       # resampling makes the fringe
        big.close()
        alpha_before = img.getchannel("A").tobytes()
        fringe = sum(1 for a in alpha_before if 0 < a < 255)
        self.assertGreater(fringe, 0)    # the fixture really is soft
        out = recolor.recolor(img, "#D9A441")
        self.assertEqual(out.getchannel("A").tobytes(), alpha_before)
        for band, value in zip("RGB", (0xD9, 0xA4, 0x41)):
            self.assertEqual(out.getchannel(band).getextrema(),
                             (value, value))
        img.close()
        out.close()

    def test_parse_hex_fails_closed(self):
        self.assertEqual(recolor.parse_hex("#D9A441"),
                         (0xD9, 0xA4, 0x41))
        for bad in ("D9A441", "#D9A44", "#GGGGGG", None, 7):
            with self.assertRaises(ValueError):
                recolor.parse_hex(bad)


class T14Memory(IngestCase):
    def test_never_more_than_one_open_image(self):
        """T14: a 10-piece bundle ingested AND confirmed with at most
        ONE file-backed image open at any moment (W4)."""
        make_sheet(os.path.join(self.input_dir, "sheet.png"),
                   [(10 + i * 55, 10, 10 + i * 55 + 29, 39)
                    for i in range(10)])
        state = {"open": 0, "max": 0, "total": 0}
        real_open = ai._open_image

        def tracking(path):
            img = real_open(path)
            state["open"] += 1
            state["total"] += 1
            state["max"] = max(state["max"], state["open"])
            original_close = img.close
            done = []

            def close():
                if not done:
                    done.append(True)
                    state["open"] -= 1
                original_close()
            img.close = close
            return img

        with mock.patch.object(ai, "_open_image", tracking):
            self.assertEqual(self.run_tool(self.input_dir), 1)
            self.assertEqual(
                self.run_tool(self.input_dir, "--confirm", "all"), 1)
        self.assertGreaterEqual(state["total"], 3)
        self.assertEqual(state["max"], 1)
        self.assertEqual(state["open"], 0)   # nothing left open
        pieces = os.listdir(os.path.join(self.out_dir(),
                                         ai.PIECES_DIRNAME))
        self.assertEqual(len(pieces), 10)


class T15Receipts(IngestCase):
    def test_receipt_on_every_run(self):
        """T15: ingest, confirm, and refused runs each append one
        receipt line."""
        make_sheet(os.path.join(self.input_dir, "art.png"),
                   [(10, 10, 80, 80)])
        self.run_tool(self.input_dir)
        self.run_tool(self.input_dir, "--confirm", "all")
        self.run_tool(self.input_dir)          # duplicate -> refused
        receipts = self.receipts()
        self.assertEqual([r["run"] for r in receipts],
                         ["INGEST", "CONFIRM", "INGEST"])
        self.assertEqual([r["exit_code"] for r in receipts],
                         [1, 1, 2])


class T16PlaySchema(unittest.TestCase):
    def sample(self):
        return {
            "play_id": "2026-09-01-mail-not-my-call",
            "line": {"setup": "CAN'T LEAVE IT NEXT DOOR.",
                     "punch": "NOT MY CALL."},
            "named_feeling": "deadpan judgment",
            "unknown_top_level": "ignored",
            "variants": [{
                "id": 1, "garment": "Black",
                "font_pair": {"hero": "Baseball Athlete Jersey",
                              "support": "Vorn"},
                "color_path": "outline_path", "layout": "text_hero",
                "fill_hex": "#7A9CB0", "outline_hex": "#D9A441",
                "elements": [{
                    "asset_id": "CF Sourced 2026-08-30/"
                                "Mailbox-SVG-835842/",
                    "note": "post-mailbox piece — bundle path only",
                    "recolor_hex": "#D9A441",
                    "size_fraction": 0.20,
                    "position": "between"}],
            }],
        }

    def test_unknown_fields_ignored(self):
        """T16: 'note' and other unknown fields ignored, never
        errors; normalized output carries known fields only."""
        play = play_schema.validate_play(self.sample())
        self.assertNotIn("unknown_top_level", play)
        self.assertNotIn("note", play["variants"][0]["elements"][0])
        self.assertEqual(play["variants"][0]["layout"], "text_hero")

    def test_missing_required_rejected(self):
        for path in (("play_id",), ("line", "punch"),
                     ("variants", 0, "layout"),
                     ("variants", 0, "font_pair", "support"),
                     ("variants", 0, "elements", 0, "recolor_hex")):
            data = self.sample()
            target = data
            for step in path[:-1]:
                target = target[step]
            del target[path[-1]]
            with self.assertRaises(play_schema.PlayError):
                play_schema.validate_play(data)

    def test_closed_layout_registry_and_hexes(self):
        data = self.sample()
        data["variants"][0]["layout"] = "banner"
        with self.assertRaises(play_schema.PlayError):
            play_schema.validate_play(data)
        data = self.sample()
        data["variants"][0]["fill_hex"] = "7A9CB0"
        with self.assertRaises(play_schema.PlayError):
            play_schema.validate_play(data)
        data = self.sample()
        data["variants"][0]["outline_hex"] = None   # nullable — ok
        play_schema.validate_play(data)
        data["variants"][0]["elements"][0]["size_fraction"] = 0
        with self.assertRaises(play_schema.PlayError):
            play_schema.validate_play(data)

    def test_load_play_file(self):
        tmp = tempfile.mkdtemp(prefix="play_")
        self.addCleanup(shutil.rmtree, tmp)
        path = os.path.join(tmp, "play.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.sample(), fh)
        self.assertEqual(play_schema.load_play(path)["play_id"],
                         "2026-09-01-mail-not-my-call")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{broken")
        with self.assertRaises(play_schema.PlayError):
            play_schema.load_play(path)


class T17ContactSheetOpaque(IngestCase):
    def test_sheet_has_zero_transparent_pixels(self):
        """T17 (F1): the contact sheet composites onto an opaque
        checkerboard — black-on-alpha art must be visible."""
        make_sheet(os.path.join(self.input_dir, "dark.png"),
                   [(10, 10, 80, 80)])   # dark art on transparency
        report = self.ingest_report()
        sheet_path = os.path.join(
            self.out_dir(), report["sources"][0]["contact_sheet"])
        with Image.open(sheet_path) as sheet:
            self.assertNotIn("A", sheet.getbands())
            colors = {sheet.getpixel((0, 0)),
                      sheet.getpixel((ai.CHECKER_TILE_PX,
                                      0))}
        # both checker shades present in the top row of tiles
        self.assertEqual(colors,
                         {ai.CHECKER_LIGHT, ai.CHECKER_DARK})


class T18MaskCrop(IngestCase):
    def test_piece_contains_only_its_own_pixels(self):
        """T18 (F2): overlapping BBOXES, separate components — each
        piece carries exactly its own component's pixels, nothing of
        the neighbour."""
        img = Image.new("RGBA", (140, 140), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # staircase shape: bbox (10,10)-(80,80)
        draw.rectangle((10, 10, 45, 45), fill=(30, 30, 30, 255))
        draw.rectangle((35, 35, 80, 80), fill=(30, 30, 30, 255))
        # separate square INSIDE the staircase's bbox
        draw.rectangle((55, 8, 78, 28), fill=(200, 40, 40, 255))
        img.save(os.path.join(self.input_dir, "pair.png"))
        img.close()
        report = self.ingest_report()
        proposals = self.total_proposals(report)
        self.assertEqual(len(proposals), 2)
        boxes = {p["id"]: p["bbox"] for p in proposals}
        overlap = (max(boxes[1][0], boxes[2][0])
                   <= min(boxes[1][2], boxes[2][2])
                   and max(boxes[1][1], boxes[2][1])
                   <= min(boxes[1][3], boxes[2][3]))
        self.assertTrue(overlap)          # the fixture really is evil
        self.assertEqual(
            self.run_tool(self.input_dir, "--confirm", "all"), 1)
        pixels = {p["id"]: p["pixels"] for p in proposals}
        for piece_id in (1, 2):
            path = os.path.join(self.out_dir(), ai.PIECES_DIRNAME,
                                ai.PIECE_NAME_FMT % piece_id)
            with Image.open(path) as piece:
                opaque = sum(1 for a in
                             piece.getchannel("A").tobytes() if a)
            self.assertEqual(opaque, pixels[piece_id],
                             "piece %d carries foreign pixels"
                             % piece_id)


class T19SubscriptionLicense(IngestCase):
    def test_subscription_licenses_without_record_file(self):
        """T19 (F3): valid subscription, no record file anywhere ->
        accepted and proposed."""
        make_sheet(os.path.join(self.input_dir, "art.png"),
                   [(10, 10, 80, 80)])
        report = self.ingest_report()
        self.assertEqual(report["license_state"], "LICENSED")
        self.assertIn("CF Subscription, verified", report["license"])
        self.assertEqual(len(self.total_proposals(report)), 1)

    def test_expired_subscription_holds_needs_human(self):
        """T19 (F3): expired -> NEEDS_HUMAN, never silently licensed,
        never a hard refusal."""
        self.write_config(cf_subscription={
            "status": "verified", "valid_through": "2020-01-01",
            "record_path": "vault/cf-record.md"})
        make_sheet(os.path.join(self.input_dir, "art.png"),
                   [(10, 10, 80, 80)])
        report = self.ingest_report()
        self.assertEqual(report["exit_code"], 1)
        self.assertEqual(report["refusals"], [])
        self.assertEqual(report["sources"], [])   # nothing proposed
        self.assertEqual(len(report["needs_human"]), 1)
        self.assertTrue(any("EXPIRED" in r for r in
                            report["needs_human"][0]["reasons"]))

    def test_folder_record_is_an_override(self):
        """No subscription in config, but a per-folder record ->
        licensed via the override."""
        self.write_config(cf_subscription=None)
        self.grant_folder_override()
        make_sheet(os.path.join(self.input_dir, "art.png"),
                   [(10, 10, 80, 80)])
        report = self.ingest_report()
        self.assertEqual(report["license_state"], "LICENSED")
        self.assertIn("override", report["license"])


class T20Cairosvg(IngestCase):
    def test_cairosvg_preferred_when_present(self):
        """T20 (F4): with cairosvg importable, .svg converts through
        it and the converter is reported per file."""
        import sys
        import types
        with open(os.path.join(self.input_dir, "art.svg"), "w",
                  encoding="utf-8") as fh:
            fh.write("<svg xmlns='http://www.w3.org/2000/svg'/>")
        fake = types.ModuleType("cairosvg")

        def svg2png(url=None, write_to=None, output_width=None):
            img = Image.new("RGBA", (output_width, 80), (0, 0, 0, 0))
            ImageDraw.Draw(img).rectangle((10, 10, 70, 70),
                                          fill=(0, 0, 0, 255))
            img.save(write_to)
            img.close()

        fake.svg2png = svg2png
        with mock.patch.dict(sys.modules, {"cairosvg": fake}):
            report = self.ingest_report()
        self.assertEqual(report["counts"]["converted"], 1)
        self.assertEqual(report["converted_files"],
                         [{"file": "art.svg",
                           "converter": "cairosvg"}])
        self.assertEqual(report["converters"]["cairosvg"], "present")
        self.assertEqual(len(self.total_proposals(report)), 1)


class T21BackfillMissing(IngestCase):
    def test_missing_file_recorded_never_null(self):
        """T21 (F6): a row whose file is gone records MISSING_FILE
        and is counted — never a null hash."""
        import asset_index_lint as lint
        ai.append_index_line(
            self.index_file,
            lint.format_row(("`ghost.png`", "CF Subscription, "
                             "verified", "cartoon", "dog", "tonal",
                             "flat", "Product 1")))
        config = ai.load_config(self.config_path)
        report = ai.run_backfill(config, {"apply": False})
        self.assertEqual(report["counts"]["missing_files"], 1)
        entry = report["proposed_entries"]["ghost.png"]
        self.assertEqual(entry["sha256"], ai.MISSING_FILE_MARK)
        report = ai.run_backfill(config, {"apply": True})
        with open(ai.sidecar_path(config), encoding="utf-8") as fh:
            stored = json.load(fh)["entries"]["ghost.png"]
        self.assertEqual(stored["sha256"], ai.MISSING_FILE_MARK)
        self.assertNotIn(None, stored.values())


class T22StemDedupe(IngestCase):
    def test_three_formats_one_proposal_set_two_skips(self):
        """F7: art.png + art.eps + art.ai -> ONE proposal set from
        the PNG, two SKIPPED_DUPLICATE_STEM records, and the losers
        never even reach the converter. (The png clears the F9b
        4000px floor so this stays a pure dedupe test.)"""
        make_sheet(os.path.join(self.input_dir, "art.png"),
                   [(10, 10, 60, 60), (100, 10, 150, 60)],
                   size=(4000, 120))
        for name in ("art.eps", "art.ai"):
            with open(os.path.join(self.input_dir, name), "wb") as fh:
                fh.write(b"%!PS-Adobe-3.0\n")
        with mock.patch.object(
                ai, "probe_converters",
                lambda: {"gs": None, "inkscape": None,
                         "cairosvg": None}):
            report = self.ingest_report()
        self.assertEqual(len(self.total_proposals(report)), 2)
        self.assertEqual(report["counts"]["skipped_duplicate_stem"],
                         2)
        skipped = sorted(item["file"] for item
                         in report["skipped_duplicate_stem"])
        self.assertEqual(skipped, ["art.ai", "art.eps"])
        self.assertTrue(all(item["kept"] == "art.png" for item
                            in report["skipped_duplicate_stem"]))
        # the losers were skipped, not failed: no CANT_CONVERT
        self.assertEqual(report["cant_convert"], [])
        self.assertEqual(report["counts"]["converted"], 0)
        receipt = self.receipts()[-1]
        self.assertEqual(len(receipt["skipped_duplicate_stem"]), 2)

    def test_different_stems_untouched(self):
        """Two different stems in mixed formats: no dedupe."""
        make_sheet(os.path.join(self.input_dir, "one.png"),
                   [(10, 10, 60, 60)])
        make_sheet(os.path.join(self.input_dir, "two.png"),
                   [(10, 10, 60, 60)])
        report = self.ingest_report()
        self.assertEqual(report["counts"]["skipped_duplicate_stem"],
                         0)
        self.assertEqual(len(report["sources"]), 2)


class T23AvailabilityAwareStem(IngestCase):
    def _vector_stem(self):
        for name in ("art.svg", "art.pdf", "art.eps"):
            with open(os.path.join(self.input_dir, name), "wb") as fh:
                fh.write(b"placeholder vector bytes\n")

    def test_gs_only_probe_pdf_wins(self):
        """T23 (F8): {svg,pdf,eps} stem on a gs-only box -> pdf wins;
        the svg's skip record says WHY it lost despite outranking."""
        self._vector_stem()
        with mock.patch.object(
                ai, "probe_converters",
                lambda: {"gs": "/fake/gs", "inkscape": None,
                         "cairosvg": None}):
            report = self.ingest_report()
        skips = {item["file"]: item for item
                 in report["skipped_duplicate_stem"]}
        self.assertEqual(sorted(skips), ["art.eps", "art.svg"])
        self.assertEqual(skips["art.svg"]["kept"], "art.pdf")
        self.assertIn("needs cairosvg|inkscape (absent)",
                      skips["art.svg"]["reason"])
        self.assertIn("lower stem priority",
                      skips["art.eps"]["reason"])
        # the pdf was the one actually sent to the converter (the
        # fake gs then fails loudly, W3 — but never the svg)
        self.assertEqual(len(report["cant_convert"]), 1)
        self.assertEqual(report["cant_convert"][0]["file"],
                         "art.pdf")

    def test_no_probe_cant_convert_as_before(self):
        """T23 (F8): nothing convertible -> raw priority proceeds and
        fails as CANT_CONVERT, never a silent zero."""
        self._vector_stem()
        with mock.patch.object(
                ai, "probe_converters",
                lambda: {"gs": None, "inkscape": None,
                         "cairosvg": None}):
            report = self.ingest_report()
        self.assertEqual(len(report["cant_convert"]), 1)
        self.assertEqual(report["cant_convert"][0]["file"],
                         "art.svg")
        self.assertIn("no converter available",
                      report["cant_convert"][0]["reason"])
        self.assertEqual(report["counts"]["skipped_duplicate_stem"],
                         2)


class T24SkipsAreBusy(IngestCase):
    def test_blank_winner_with_skips_is_never_a_clean_pass(self):
        """T24 (F9a): Sonnet's repro — blank art.png wins the stem,
        siblings skipped, zero proposals. gate_run reads only the
        exit code, so this must be exit 1, never 0. (F10b: the png
        clears the F9b floor so ONLY the busy fix produces the 1 —
        verified red on the reverted line.)"""
        make_sheet(os.path.join(self.input_dir, "art.png"), [],
                   size=(4000, 200))
        for name in ("art.eps", "art.ai"):
            with open(os.path.join(self.input_dir, name), "wb") as fh:
                fh.write(b"%!PS-Adobe-3.0\n")
        with mock.patch.object(
                ai, "probe_converters",
                lambda: {"gs": None, "inkscape": None,
                         "cairosvg": None}):
            report = self.ingest_report()
        self.assertEqual(len(self.total_proposals(report)), 0)
        self.assertEqual(report["counts"]["skipped_duplicate_stem"],
                         2)
        self.assertEqual(report["exit_code"], 1)


class T26ProductIdRefusal(IngestCase):
    def test_no_digits_refused_with_receipt(self):
        """T26 (F10a): a folder with no trailing digits ->
        PRODUCT_ID_UNRESOLVED refusal, receipt written, exit 2 —
        never an uncaught NameError with no receipt."""
        bad_dir = os.path.join(self.tmp, "no-digits-here")
        os.makedirs(bad_dir)
        make_sheet(os.path.join(bad_dir, "art.png"),
                   [(10, 10, 60, 60)])
        before = len(self.receipts())
        with mock.patch("sys.stdout", io.StringIO()), \
                mock.patch("sys.stderr", io.StringIO()):
            code = ai.main(["--config", self.config_path, bad_dir])
        self.assertEqual(code, 2)
        receipts = self.receipts()
        self.assertEqual(len(receipts), before + 1)
        self.assertEqual(receipts[-1]["refusals"][0]["kind"],
                         "PRODUCT_ID_UNRESOLVED")


class T25RasterFloor(IngestCase):
    def _fixture(self):
        make_sheet(os.path.join(self.input_dir, "art.png"),
                   [(100, 50, 900, 250)], size=(1800, 300))
        with open(os.path.join(self.input_dir, "art.eps"),
                  "wb") as fh:
            fh.write(b"%!PS-Adobe-3.0 EPSF-3.0\n")

    def _gs_probe(self):
        return mock.patch.object(
            ai, "probe_converters",
            lambda: {"gs": "/fake/gs", "inkscape": None,
                     "cairosvg": None})

    def test_small_raster_over_vector_held_with_hint(self):
        """T25 (F9b): 1800px png beats an eps -> dimensions in the
        receipt, held NEEDS_HUMAN with the --prefer-vector hint."""
        self._fixture()
        with self._gs_probe():
            report = self.ingest_report()
        self.assertEqual(report["raster_over_vector"],
                         [{"file": "art.png", "width": 1800,
                           "height": 300,
                           "vector_sibling": "art.eps"}])
        self.assertEqual(len(report["needs_human"]), 1)
        reason = report["needs_human"][0]["reasons"][0]
        self.assertIn("RASTER_BELOW_FLOOR: art.png 1800px", reason)
        self.assertIn("--prefer-vector", reason)
        self.assertEqual(report["sources"], [])   # held, not proposed
        receipt = self.receipts()[-1]
        self.assertEqual(receipt["raster_over_vector"][0]["width"],
                         1800)

    def test_prefer_vector_makes_the_eps_win(self):
        """T25 (F9b): --prefer-vector -> the eps wins the stem and is
        the file sent to the converter."""
        self._fixture()
        with self._gs_probe():
            report = self.ingest_report("prefer_vector")
        skips = {item["file"]: item for item
                 in report["skipped_duplicate_stem"]}
        self.assertEqual(list(skips), ["art.png"])
        self.assertEqual(skips["art.png"]["kept"], "art.eps")
        self.assertIn("--prefer-vector", skips["art.png"]["reason"])
        # the eps reached the converter (the fake gs then fails, W3)
        self.assertEqual(len(report["cant_convert"]), 1)
        self.assertEqual(report["cant_convert"][0]["file"],
                         "art.eps")
        self.assertEqual(report["raster_over_vector"], [])


class MigrateLegacyRows(IngestCase):
    """Fable order 2026-09-02, amended by Sonnet's cert of 00fd755:
    legacy rows come to the 7-column D-419 shape, EXCEPT the shapes
    the cert put on hold. Dry-run default, backup before write,
    untouched rows byte-faithful, every migrated row through
    asset_index_lint BEFORE it is written."""

    GOOD = ("| `a/good.png` | CF Subscription, verified | cartoon | "
            "dog | tonal | flat | Product 28 |")
    LEGACY5 = ("| `b/legacy.png` | CF Subscription, verified | flat "
               "badge | raccoon | Sourced for Family N per D-046 |")
    OLDPATH = ("| Merch/Design Assets/c/old.png | CF Subscription, "
               "verified | cartoon | owl | grey | tonal | Product 3 |")
    UNKNOWN = "| `d/weird.png` | only | three |"
    LEGACY_HEADER = ("| Asset (path under `Merch/Design Assets/`) | "
                     "License | Style | Niche tags | Notes |")
    LEGACY_SEP = "|---|---|---|---|---|"

    def write_index(self, body_lines):
        text = (HEADER + "\n" + SEPARATOR + "\n"
                + "\n".join(body_lines) + "\n")
        with open(self.index_file, "w", encoding="utf-8") as fh:
            fh.write(text)
        return text

    def migrate(self, apply=False):
        config = ai.load_config(self.config_path)
        report = ai.run_migrate(config, {"apply": apply})
        ai.append_receipt(report)
        return report

    def test_dry_run_proposes_and_writes_nothing(self):
        before = self.write_index([self.GOOD, self.OLDPATH])
        report = self.migrate()
        self.assertEqual(report["exit_code"], 1)
        self.assertEqual(report["counts"]["rows_migrated"], 1)
        self.assertFalse(report["applied"])
        with open(self.index_file, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), before)   # byte-identical

    def test_apply_migrates_and_leaves_good_rows_byte_faithful(self):
        self.write_index([self.GOOD, self.OLDPATH])
        report = self.migrate(apply=True)
        self.assertTrue(report["applied"])
        rows = self.index_rows()
        self.assertIn(self.GOOD, rows)            # untouched, verbatim
        for row in rows[2:]:
            self.assertEqual(ail.lint_row(row), [], row)
            self.assertEqual(len(ail.split_cells(row)), 7)
        oldpath = [r for r in rows if "old.png" in r][0]
        self.assertEqual(ail.asset_path(oldpath), "c/old.png")
        cells = ail.split_cells(oldpath)
        self.assertEqual(cells[1:], ["CF Subscription, verified",
                                     "cartoon", "owl", "grey",
                                     "tonal", "Product 3"])

    def test_backup_written_and_matches_the_original(self):
        before = self.write_index([self.OLDPATH])
        report = self.migrate(apply=True)
        self.assertTrue(os.path.isfile(report["backup"]))
        with open(report["backup"], encoding="utf-8") as fh:
            self.assertEqual(fh.read(), before)
        self.assertEqual(self.receipts()[-1]["backup"],
                         report["backup"])

    def test_unknown_shape_is_reported_never_guessed(self):
        before = self.write_index([self.GOOD, self.UNKNOWN])
        report = self.migrate(apply=True)
        self.assertEqual(report["counts"]["unmigratable"], 1)
        self.assertEqual(report["counts"]["rows_migrated"], 0)
        self.assertIn("no LEGACY_COLUMN_MAPS rule",
                      report["unmigratable"][0]["detail"])
        self.assertFalse(report["applied"])       # nothing to write
        with open(self.index_file, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), before)

    def test_legacy_notes_land_in_used_in_per_D429(self):
        """D-429 (Khai's ruling, via Sonnet cert D-430): a legacy
        5-column row's NOTES text goes to "Used in"; Colors and
        Recolor are pending. Nothing dropped."""
        self.write_index([self.GOOD, self.LEGACY5])
        report = self.migrate(apply=True)
        self.assertEqual(report["counts"]["rows_migrated"], 1)
        self.assertEqual(report["counts"]["unmigratable"], 0)
        row = [r for r in self.index_rows() if "legacy.png" in r][0]
        cells = ail.split_cells(row)
        self.assertEqual(cells, [
            "`b/legacy.png`", "CF Subscription, verified",
            "flat badge", "raccoon",
            ai.PENDING_CELL, ai.PENDING_CELL,
            "Sourced for Family N per D-046"])
        self.assertEqual(ail.lint_row(row), [])

    def test_six_column_shape_is_still_held(self):
        """Only the 5-column hold was lifted — the 6-column map was
        inferred and has never been read from the live file."""
        six = ("| `e/six.png` | CF Subscription, verified | cartoon "
               "| cat | grey | flat |")
        self.write_index([self.GOOD, six])
        report = self.migrate(apply=True)
        self.assertEqual(report["counts"]["rows_migrated"], 0)
        self.assertIn("HELD", report["unmigratable"][0]["detail"])
        self.assertFalse(report["applied"])

    def test_legacy_header_is_never_padded_as_data(self):
        """Sonnet cert of 00fd755: a 5-column SECTION HEADER is not a
        data row. It is recognised structurally (the row above a
        separator), reported, and left exactly as it is."""
        before = self.write_index([self.GOOD, "", "## Bootleg Parts",
                                   self.LEGACY_HEADER,
                                   self.LEGACY_SEP, self.OLDPATH])
        report = self.migrate(apply=True)
        self.assertEqual(report["counts"]["legacy_headers"], 1)
        header = report["legacy_headers"][0]
        self.assertEqual(header["section"], "Bootleg Parts")
        self.assertEqual(header["cells"][-1], "Notes")
        # the header is untouched and NOT among the migrated rows
        rows = self.index_rows()
        self.assertIn(self.LEGACY_HEADER, rows)
        self.assertFalse(any("pending" in r for r in rows
                             if "Niche tags" in r))
        self.assertNotIn(self.LEGACY_HEADER,
                         [p["before"] for p in report["proposals"]])
        self.assertEqual(self.receipts()[-1]["legacy_headers"][0][
            "line"], header["line"])
        del before

    def test_backfill_also_skips_legacy_headers(self):
        """The same bug hit --backfill: a legacy header was linted as
        a data row and reported as a bad row."""
        self.write_index([self.GOOD, "", "## Bootleg Parts",
                          self.LEGACY_HEADER, self.LEGACY_SEP])
        config = ai.load_config(self.config_path)
        report = ai.run_backfill(config, {"apply": False})
        self.assertEqual(report["bad_rows"], [])

    def test_clean_index_is_exit_0_and_untouched(self):
        before = self.write_index([self.GOOD])
        report = self.migrate(apply=True)
        self.assertEqual(report["exit_code"], 0)
        self.assertFalse(report["applied"])
        with open(self.index_file, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), before)

    def test_idempotent(self):
        self.write_index([self.GOOD, self.OLDPATH])
        self.migrate(apply=True)
        with open(self.index_file, encoding="utf-8") as fh:
            after_first = fh.read()
        second = self.migrate(apply=True)
        self.assertEqual(second["exit_code"], 0)
        self.assertEqual(second["counts"]["rows_migrated"], 0)
        with open(self.index_file, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), after_first)

    def test_cli_flags_fail_closed(self):
        self.write_index([self.OLDPATH])
        with mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(
                self.run_tool("--migrate", "--backfill"), 2)
            self.assertEqual(
                self.run_tool("--migrate", self.input_dir), 2)
        self.assertEqual(self.run_tool("--migrate"), 1)   # dry-run


class CompoundAssetPaths(IngestCase):
    """Sonnet cert D-430: 14 live rows use the established
    primary-plus-derivatives convention. Every distinct shape in that
    block is here VERBATIM — the fix is built against the real
    variety, not one example."""

    REAL_CELLS = [
        # (+ `path` prose) — Product 39 bells
        "`product39-dispatcher-hohohold/character-art/bells_source"
        ".png` (+ `bells_navybrick.png` recolor)",
        # (+ prose only, no paths) — Product 41 electrician
        "`product41-electrician-halloween/character-art/electrician_"
        "source_native.png` (+ light/dark variants)",
        # (+ `path`) — Product 43 boxes
        "`product43-mailcarrier-holidaycardio/character-art/boxes_"
        "dark_variant.png` (+ `boxes_light_variant_halo.png`)",
        # multi-path annotation with parens INSIDE a backticked path
        "`product49-trucker-fourwheelers/character-art/truck_source"
        ".png` (+ `truck_cream.png`, `truck_navy.png`; two untouched "
        "extra derivatives at `Ten Minutes Late - The Whole Block "
        "Knows (5-variant play)/character-art/truck_ink_mono.png` + "
        "`truck_burgundy.png`, built for that exercise's V3/V5 but "
        "not currently used)",
        # top-level "+"-joined paths + annotation — the 5-item pack
        "`Merry Christmas - Now Whats Your Emergency (pending gate)/"
        "character-art/item-holly-berries.png` + `item-berry-sprig"
        ".png` + `item-snowflake.png` + `item-candy-cane.png` + "
        "`item-tree-star.png` (5 items, extracted from one source "
        "file `christmas-items-5pack_source.png`)",
        # FOLDER path + "(N frames)" — Bootleg Parts
        "`Bootleg Parts/vintage-photo-frames/` (10 frames)",
        # two "+"-joined FOLDER paths, no annotation — Semi-Truck
        "`CF Sourced 2026-08-30/Semi-Truck-Trucker-18-Wheeler-"
        "13786326/` + `CF Sourced 2026-08-30/Silhouette-of-a-"
        "semitruck-46652476/`",
        # annotation opening with "+3" — Police-Siren
        "`CF Sourced 2026-08-31/Police-Siren-Svg-Light-Bulb-31841802/"
        "PNG/svg-police-siren.png` (+3 style variants, +AI/EPS/SVG/"
        "JPG formats, full bundle kept)",
    ]

    def test_every_real_shape_passes_L3(self):
        for cell in self.REAL_CELLS:
            self.assertEqual(ail.asset_cell_findings(cell), [], cell)
            row = ail.format_row([cell, "CF Subscription, verified",
                                  "flat", "tag", "tonal", "flat",
                                  "Product X"])
            self.assertEqual(ail.lint_row(row), [], cell)

    def test_primary_path_is_the_sidecar_key(self):
        """asset_path() still returns ONE path — the primary — so the
        sidecar key is unchanged for every row that already had one."""
        row = ail.format_row([self.REAL_CELLS[0], "L", "S", "N", "C",
                              "R", "U"])
        self.assertEqual(
            ail.asset_path(row),
            "product39-dispatcher-hohohold/character-art/"
            "bells_source.png")

    def test_declared_paths_exclude_annotation_prose(self):
        """The 5-item pack declares 5 paths; the source file named
        inside the annotation is prose, not a declared asset."""
        row = ail.format_row([self.REAL_CELLS[4], "L", "S", "N", "C",
                              "R", "U"])
        paths = ail.asset_paths(row)
        self.assertEqual(len(paths), 5)
        self.assertTrue(paths[0].endswith("item-holly-berries.png"))
        self.assertFalse(any("5pack_source" in p for p in paths))
        # the path containing parentheses stayed ONE path
        row = ail.format_row([self.REAL_CELLS[3], "L", "S", "N", "C",
                              "R", "U"])
        self.assertEqual(ail.asset_paths(row),
                         ["product49-trucker-fourwheelers/"
                          "character-art/truck_source.png"])

    def test_malformed_cells_still_fail(self):
        for bad in ("not-backticked.png",
                    "`a.png` trailing prose without parens",
                    "`a.png` + not-backticked.png",
                    "`/absolute/a.png`",
                    "`a\\b.png`",
                    "`unclosed.png"):
            self.assertNotEqual(ail.asset_cell_findings(bad), [], bad)

    def test_compound_row_migrates_untouched_when_already_7_col(self):
        """A 7-column row whose only problem WAS the compound cell is
        now simply valid — nothing to migrate."""
        row = ail.format_row([self.REAL_CELLS[5], "CF Subscription, "
                              "verified", "vintage", "bootleg",
                              "tonal", "flat", "Queued"])
        with open(self.index_file, "w", encoding="utf-8") as fh:
            fh.write(HEADER + "\n" + SEPARATOR + "\n" + row + "\n")
        config = ai.load_config(self.config_path)
        report = ai.run_migrate(config, {"apply": True})
        self.assertEqual(report["exit_code"], 0)
        self.assertFalse(report["applied"])


class ConfirmGroups(IngestCase):
    """Fable 2026-09-02: outline art splits into loops — a ring and
    the counter inside it are TWO components but ONE object. Ids
    joined with '+' cut one piece from the merged masks."""

    def _nested_loops(self):
        """A ring plus a separate dot inside it: two components whose
        bboxes nest, which is exactly the outline-art shape."""
        img = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse((40, 40, 260, 260), outline=(20, 20, 20, 255),
                     width=22)
        draw.ellipse((130, 130, 170, 170), fill=(20, 20, 20, 255))
        img.save(os.path.join(self.input_dir, "loops.png"))
        img.close()

    def test_group_makes_one_piece_from_merged_masks(self):
        """'1+2' -> ONE piece carrying BOTH components' pixels, one
        row, one sidecar entry."""
        self._nested_loops()
        report = self.ingest_report()
        proposals = self.total_proposals(report)
        self.assertEqual(len(proposals), 2)
        expected = sum(p["pixels"] for p in proposals)
        self.assertEqual(self.run_tool(self.input_dir, "--confirm",
                                       "1+2"), 1)
        piece = os.path.join(self.out_dir(), ai.PIECES_DIRNAME,
                             "piece_01+02.png")
        self.assertTrue(os.path.exists(piece))
        self.assertTrue(os.path.exists(os.path.join(
            self.out_dir(), ai.THUMBS_DIRNAME,
            "piece_01+02_thumb.png")))
        with Image.open(piece) as img:
            opaque = sum(1 for a in img.getchannel("A").tobytes()
                         if a)
        self.assertEqual(opaque, expected)   # both loops, nothing else
        rows = self.index_rows()
        self.assertEqual(len(rows), 3)       # header + sep + ONE row
        self.assertEqual(ail.lint_row(rows[-1]), [])
        config = ai.load_config(self.config_path)
        with open(ai.sidecar_path(config), encoding="utf-8") as fh:
            entries = json.load(fh)["entries"]
        self.assertEqual(len(entries), 1)
        self.assertIn("piece_01+02.png", list(entries)[0])

    def test_separate_ids_still_make_separate_pieces(self):
        """The same fixture confirmed as '1,2' -> TWO pieces, each
        carrying only its own component (the group is opt-in)."""
        self._nested_loops()
        report = self.ingest_report()
        sizes = {p["id"]: p["pixels"]
                 for p in self.total_proposals(report)}
        self.assertEqual(self.run_tool(self.input_dir, "--confirm",
                                       "1,2"), 1)
        for piece_id in (1, 2):
            path = os.path.join(self.out_dir(), ai.PIECES_DIRNAME,
                                ai.PIECE_NAME_FMT % piece_id)
            with Image.open(path) as img:
                opaque = sum(1 for a in img.getchannel("A").tobytes()
                             if a)
            self.assertEqual(opaque, sizes[piece_id])
        self.assertEqual(len(self.index_rows()), 4)   # two rows

    def test_bad_group_syntax_and_reuse_refused(self):
        self._nested_loops()
        self.run_tool(self.input_dir)
        with mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(
                self.run_tool(self.input_dir, "--confirm", "1+x"), 2)
            self.assertEqual(
                self.run_tool(self.input_dir, "--confirm", "1,1+2"),
                2)


class ConversionNote(IngestCase):
    def test_receipt_names_why_nothing_ran(self):
        """Fable cleanup: dedupe skips say 'duplicate', but when zero
        files converted the receipt carries one line naming WHY."""
        for name in ("art.svg", "art.eps"):
            with open(os.path.join(self.input_dir, name), "wb") as fh:
                fh.write(b"vector bytes\n")
        with mock.patch.object(
                ai, "probe_converters",
                lambda: {"gs": None, "inkscape": None,
                         "cairosvg": None}):
            report = self.ingest_report()
        note = ("all candidates skipped: no converter for .eps/.svg "
                "on this box")
        self.assertIn(note, report["findings"])
        self.assertIn(note, self.receipts()[-1]["findings"])

    def test_no_note_when_something_converted(self):
        """A successful conversion means the note stays silent."""
        import sys
        import types
        with open(os.path.join(self.input_dir, "art.svg"), "w",
                  encoding="utf-8") as fh:
            fh.write("<svg xmlns='http://www.w3.org/2000/svg'/>")
        fake = types.ModuleType("cairosvg")

        def svg2png(url=None, write_to=None, output_width=None):
            img = Image.new("RGBA", (output_width, 80), (0, 0, 0, 0))
            ImageDraw.Draw(img).rectangle((10, 10, 70, 70),
                                          fill=(0, 0, 0, 255))
            img.save(write_to)
            img.close()

        fake.svg2png = svg2png
        with mock.patch.dict(sys.modules, {"cairosvg": fake}):
            report = self.ingest_report()
        self.assertFalse(any("no converter" in f
                             for f in report["findings"]))


class ZipInput(IngestCase):
    def test_zip_ingest_parses_stem_product_id(self):
        png = os.path.join(self.tmp, "art.png")
        make_sheet(png, [(10, 10, 80, 80)])
        zip_path = os.path.join(self.tmp, "Zip-Bundle-777.zip")
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.write(png, "art.png")
        code = self.run_tool(zip_path)
        self.assertEqual(code, 1)
        receipt = self.receipts()[-1]
        self.assertEqual(receipt["product_id"], "777")
        self.assertTrue(os.path.isdir(os.path.join(
            self.assets_dir, ai.STAGING_DIRNAME, "Zip-Bundle-777")))


class CrashFloor(IngestCase):
    """Fleet crash floor: a Python traceback exits 1, which this
    tool's contract reads as "proposed / applied". Exit 2 and a CRASH
    receipt are what tell a wrapper the tool broke.
    (test_unknown_flag_exits_2 below is the other half: argparse's
    SystemExit still gets through the guard untouched.)"""

    def test_uncaught_exception_is_exit_2_with_a_receipt(self):
        with mock.patch.object(ai, "run_ingest",
                               side_effect=RuntimeError("injected")):
            with mock.patch("sys.stdout", io.StringIO()), \
                    mock.patch("sys.stderr", io.StringIO()) as err:
                code = ai.main(["--config", self.config_path,
                                self.input_dir])
        self.assertEqual(code, 2)
        self.assertIn("CRASH (RuntimeError): injected", err.getvalue())
        receipt = self.receipts()[-1]
        self.assertEqual(receipt["refusals"][0]["kind"], "CRASH")
        self.assertEqual(receipt["exit_code"], 2)
        self.assertFalse(os.path.exists(self.out_dir()))


class ConfigFailClosed(IngestCase):
    def test_unknown_key_missing_file_bad_layout(self):
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump({"index_root": self.index_root,
                       "assets_dir": self.assets_dir,
                       "license_dir": self.license_dir,
                       "surprise": 1}, fh)
        self.assertEqual(self.run_tool(self.input_dir), 2)
        # assets_dir outside index_root refused
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump({"index_root": self.index_root,
                       "assets_dir": self.tmp,
                       "license_dir": self.license_dir}, fh)
        self.assertEqual(self.run_tool(self.input_dir), 2)
        os.remove(self.config_path)
        self.assertEqual(self.run_tool(self.input_dir), 2)

    def test_unknown_flag_exits_2(self):
        with mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                ai.main(["--config", self.config_path, "--bogus"])
        self.assertEqual(caught.exception.code, 2)

    def test_apply_without_backfill_refused(self):
        self.assertEqual(self.run_tool(self.input_dir, "--apply"), 2)


if __name__ == "__main__":
    unittest.main()
