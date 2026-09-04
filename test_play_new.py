#!/usr/bin/env python3
"""Tests for play_new.py (FLEET B4, T1-T20).

pytest is specced but is not installed in this environment (flagged
deviation, D-394) — these are unittest-style, which pytest collects
and runs unchanged.

T10 is the fixture every other test stands on: a tiny 7-column
ASSET_INDEX, its sidecar, and Liberation fonts renamed to the roster
names. Real licensed fonts and real CF assets are NEVER committed
(W11).
"""

import importlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import asset_index_lint as ail
import color_check as cc
import play_forge as pf
import play_new as pn
import play_schema


LIBERATION = ("/usr/share/fonts/truetype/liberation/"
              "LiberationSans-Regular.ttf")
HEADER = ("| Asset (path under `Merch/Design Assets/`) | License | "
          "Style | Niche tags | Colors | Recolor | Used in |")
SEPARATOR = "|---|---|---|---|---|---|---|"
TAG = "mail carrier"
SETUP = "CAN'T LEAVE IT NEXT DOOR."
PUNCH = "NOT MY CALL."


class PlayNewCase(unittest.TestCase):
    """T10 — the fixture."""

    ROWS = (("cf/mailbox.png", "mail carrier, generic"),
            ("cf/laurel.png", "mail carrier, ornament"),
            ("cf/folder-pack/", "mail carrier, pack"),
            ("cf/other.png", "trucker, generic"))

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pn_test_")
        self.addCleanup(shutil.rmtree, self.tmp)
        self.index_root = os.path.join(self.tmp, "index")
        self.fonts_dir = os.path.join(self.tmp, "fonts")
        self.out_dir = os.path.join(self.tmp, "out")
        for path in (self.index_root, self.fonts_dir, self.out_dir):
            os.makedirs(path)
        for base in pf.FONT_ROSTER.values():
            shutil.copy(LIBERATION,
                        os.path.join(self.fonts_dir, base + ".ttf"))
        self.write_index(self.ROWS)
        self.config_path = os.path.join(self.tmp, "config.json")
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump({"index_root": self.index_root,
                       "fonts_dir": self.fonts_dir,
                       "out_dir": self.out_dir}, fh)
        patcher = mock.patch.object(pn, "BASE_DIR", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_index(self, rows):
        lines, entries = [], {}
        for path, tags in rows:
            lines.append(ail.format_row(
                ["`%s`" % path, "CF Subscription, verified", "flat",
                 tags, "tonal", "flat", "Product X"]))
            if not path.endswith("/"):
                entries[path] = {"sha256": "a" * 64,
                                 "product_id": "1",
                                 "ingested_utc": "2026-09-04"}
        with open(os.path.join(self.index_root, "ASSET_INDEX.md"),
                  "w", encoding="utf-8") as fh:
            fh.write(HEADER + "\n" + SEPARATOR + "\n"
                     + "\n".join(lines) + "\n")
        with open(os.path.join(self.index_root,
                               "ASSET_INDEX.hashes.json"),
                  "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "tool": "asset_ingest",
                       "entries": entries}, fh)

    def run_tool(self, *flags, **kw):
        argv = ["--setup", kw.get("setup", SETUP),
                "--punch", kw.get("punch", PUNCH),
                "--feeling", kw.get("feeling", "deadpan judgment"),
                "--tag", kw.get("tag", TAG),
                "--config", self.config_path,
                "--date", kw.get("date", "2026-09-04")]
        argv.extend(flags)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", out), \
                mock.patch("sys.stderr", err):
            code = pn.main(argv)
        return code, out.getvalue(), err.getvalue()

    def out_path(self, play_id="not-my-call-2026-09-04"):
        return os.path.join(self.out_dir, play_id + pn.OUT_SUFFIX)

    def play(self, play_id="not-my-call-2026-09-04"):
        with open(self.out_path(play_id), encoding="utf-8") as fh:
            return json.load(fh)

    def receipts(self):
        path = os.path.join(self.tmp, pn.RECEIPTS_NAME)
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]


class T01ExistingFile(PlayNewCase):
    def test_refuses_naming_the_existing_punch_then_overwrites(self):
        self.assertIn(self.run_tool()[0], (0, 1))
        # a DIFFERENT line that slugs identically
        code, _, err = self.run_tool(punch="not my call")
        self.assertEqual(code, 2)
        self.assertIn("OUT_FILE_EXISTS", err)
        self.assertIn(PUNCH, err)          # names the EXISTING punch
        code, _, _ = self.run_tool("--overwrite", punch="not my call")
        self.assertIn(code, (0, 1))
        self.assertEqual(self.play()["line"]["punch"], "not my call")


class T02T03Candidates(PlayNewCase):
    def test_no_match_refuses_and_no_art_writes_empty_elements(self):
        code, _, err = self.run_tool(tag="nobody has this tag")
        self.assertEqual(code, 2)
        self.assertIn("NO_ART_FOR_TAG", err)
        self.assertFalse(os.path.exists(self.out_path()))
        code, _, _ = self.run_tool("--no-art")
        self.assertEqual(code, 1)
        for variant in self.play()["variants"]:
            self.assertEqual(variant["elements"], [])
            self.assertEqual(variant["element_count"], 0)

    def test_folder_rows_and_other_tags_excluded(self):
        code, out, _ = self.run_tool()
        self.assertIn(code, (0, 1))
        chosen = {element["asset_id"]
                  for variant in self.play()["variants"]
                  for element in variant["elements"]}
        self.assertEqual(chosen, {"cf/mailbox.png", "cf/laurel.png"})
        self.assertNotIn("cf/folder-pack/", out)
        self.assertNotIn("cf/other.png", out)

    def test_tag_match_is_whole_tag_never_substring(self):
        self.assertTrue(pn.tag_matches("mail carrier, generic",
                                       "mail carrier"))
        self.assertFalse(pn.tag_matches("air carrier, generic",
                                        "carrier"))
        self.assertTrue(pn.tag_matches("Mail Carrier", "mail carrier"))


class T04T13Register(PlayNewCase):
    def test_title_case_only_font_never_on_an_all_caps_line(self):
        code, _, _ = self.run_tool()
        self.assertIn(code, (0, 1))
        for variant in self.play()["variants"]:
            for role in ("hero", "support"):
                self.assertNotIn(variant["font_pair"][role],
                                 pf.TITLE_CASE_ONLY_FONTS)

    def test_title_case_line_is_not_read_as_all_caps(self):
        """T13: 'I' and 'A' are single uppercase letters; the rule is
        whole-line, so a Title Case line is NOT all-caps."""
        self.assertFalse(
            pf.line_is_all_caps("I Can't Leave It Next Door"))
        self.assertTrue(pf.line_is_all_caps(PUNCH))
        pairs = pn.usable_font_pairs("Not My Call.",
                                     "I Can't Leave It Next Door")
        self.assertTrue(any("Midtown Script" in pair
                            for pair in pairs))


class T05T06Axes(PlayNewCase):
    def test_every_pair_differs_on_two_axes_via_check_structure(self):
        """T5: asserted through play_forge's OWN rule, never a
        re-implementation."""
        self.assertIn(self.run_tool()[0], (0, 1))
        loaded = play_schema.load_play(self.out_path())
        config = pf.load_config(self.config_path)
        failures, _clusters = pf.check_structure(loaded, config)
        self.assertEqual(failures, [])

    def test_outline_variants_carry_the_garments_outline_hex(self):
        self.assertIn(self.run_tool()[0], (0, 1))
        seen_outline = False
        for variant in self.play()["variants"]:
            garment = variant["garment"].lower()
            if variant["color_path"] == "outline_path":
                seen_outline = True
                self.assertEqual(variant["outline_hex"],
                                 cc.OUTLINES[garment]["hex"])
            else:
                self.assertIsNone(variant["outline_hex"])
        self.assertTrue(seen_outline)


class T07ValidatorRedGreen(PlayNewCase):
    def test_failing_validator_writes_nothing(self):
        with mock.patch.object(play_schema, "load_play",
                               side_effect=play_schema.PlayError(
                                   "injected schema failure")):
            code, _, err = self.run_tool()
        self.assertEqual(code, 2)
        self.assertIn("SCHEMA_REJECTED", err)
        self.assertIn("injected schema failure", err)
        self.assertFalse(os.path.exists(self.out_path()))
        self.assertEqual(
            [n for n in os.listdir(self.out_dir)], [])   # no temp left

    def test_overwrite_leaves_the_existing_play_byte_identical(self):
        """W13: open(path,'w') truncates AT OPEN. Without the temp
        file this failure would leave 0 bytes where a good play was."""
        self.assertIn(self.run_tool()[0], (0, 1))
        with open(self.out_path(), "rb") as fh:
            before = fh.read()
        self.assertGreater(len(before), 0)
        with mock.patch.object(play_schema, "load_play",
                               side_effect=play_schema.PlayError(
                                   "injected schema failure")):
            code, _, _ = self.run_tool("--overwrite")
        self.assertEqual(code, 2)
        with open(self.out_path(), "rb") as fh:
            self.assertEqual(fh.read(), before)

    def test_structure_failure_also_writes_nothing(self):
        with mock.patch.object(pf, "check_structure",
                               return_value=(["injected structure "
                                              "failure"], {})):
            code, _, err = self.run_tool()
        self.assertEqual(code, 2)
        self.assertIn("STRUCTURE_REJECTED", err)
        self.assertIn("injected structure failure", err)
        self.assertFalse(os.path.exists(self.out_path()))


class T08JsonParity(PlayNewCase):
    def test_json_is_the_same_report_dict(self):
        code, out, _ = self.run_tool("--json")
        payload = json.loads(out)
        self.assertEqual(payload["exit_code"], code)
        self.assertEqual(payload["variant_count"], 5)
        self.assertTrue(payload["written"])
        self.assertEqual(payload["play_id"], "not-my-call-2026-09-04")
        self.assertEqual(len(payload["candidates"]), 2)


class T09Determinism(PlayNewCase):
    def test_two_runs_byte_identical(self):
        self.assertIn(self.run_tool()[0], (0, 1))
        with open(self.out_path(), "rb") as fh:
            first = fh.read()
        self.assertIn(self.run_tool("--overwrite")[0], (0, 1))
        with open(self.out_path(), "rb") as fh:
            self.assertEqual(fh.read(), first)

    def test_identical_under_different_hash_seeds(self):
        """The test that catches a set leaking ordering into the
        play: PYTHONHASHSEED randomizes set iteration per process."""
        outputs = []
        for seed in ("1", "2"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            result = subprocess.run(
                [sys.executable, "play_new.py",
                 "--setup", SETUP, "--punch", PUNCH,
                 "--feeling", "deadpan judgment", "--tag", TAG,
                 "--config", self.config_path, "--date", "2026-09-04",
                 "--overwrite"],
                capture_output=True, env=env, cwd=os.path.dirname(
                    os.path.abspath(pn.__file__)))
            self.assertIn(result.returncode, (0, 1), result.stderr)
            with open(self.out_path(), "rb") as fh:
                outputs.append(fh.read())
        self.assertEqual(outputs[0], outputs[1])


class T11T12Feasibility(PlayNewCase):
    def test_no_art_ceiling_is_four_and_names_the_numbers(self):
        code, out, _ = self.run_tool("--no-art")
        self.assertEqual(code, 1)
        self.assertEqual(len(self.play()["variants"]), 4)
        self.assertIn("ceiling is 2*min(2,3)=4 variants, not 5", out)
        self.assertIn("2 layouts", out)

    def test_mono_font_ceiling_is_two(self):
        with mock.patch.object(pf, "FONT_ROSTER",
                               {"Vorn": "Vorn"}):
            code, out, _ = self.run_tool()
        self.assertEqual(code, 1)
        self.assertEqual(len(self.play()["variants"]), 2)
        self.assertIn("ceiling is 2*min(5,1)=2 variants, not 5", out)

    def test_ceiling_matches_the_projection_bound(self):
        self.assertEqual(pn.feasibility(("a", "b"), (1, 2, 3)), 4)
        self.assertEqual(pn.feasibility(("a",) * 5, (1,)), 2)
        self.assertEqual(pn.feasibility(("a",) * 5, (1, 2, 3)), 6)


class T14Slug(PlayNewCase):
    def test_nfc_and_nfd_give_the_same_play_id(self):
        import unicodedata
        nfc = unicodedata.normalize("NFC", "CAFÉ RULES.")
        nfd = unicodedata.normalize("NFD", "CAFÉ RULES.")
        self.assertNotEqual(nfc, nfd)
        self.assertEqual(pn.slug(nfc), pn.slug(nfd))

    def test_empty_slug_refuses(self):
        for punch in ("!_!", "...", "   "):
            code, _, err = self.run_tool(punch=punch)
            self.assertEqual(code, 2, punch)
            self.assertIn("EMPTY_SLUG", err)

    def test_slug_is_length_capped(self):
        self.assertLessEqual(len(pn.slug("word " * 100)),
                             pn.SLUG_MAX_LEN)


class T15ColorLaw(PlayNewCase):
    def test_three_ink_hexes_is_refused_by_check_structure(self):
        """The 2-colour law is play_forge's rule (bench W2) and is NOT
        duplicated here — this proves the W5 hook catches a violation
        rather than that play_new re-counts it."""
        real_build = pn.build_play

        def third_colour(*a, **kw):
            play = real_build(*a, **kw)
            for variant in play["variants"]:
                if variant["elements"] and variant["garment"] == "Black":
                    # fill + outline + a third on the element = 3
                    variant["color_path"] = "outline_path"
                    variant["outline_hex"] = cc.OUTLINES["black"]["hex"]
                    variant["fill_hex"] = "#7A9CB0"
                    variant["elements"][0]["recolor_hex"] = "#9CAF88"
                    break
            return play

        with mock.patch.object(pn, "build_play", third_colour):
            code, _, err = self.run_tool()
        self.assertEqual(code, 2)
        self.assertIn("STRUCTURE_REJECTED", err)
        self.assertIn("W2", err)
        self.assertFalse(os.path.exists(self.out_path()))


class T16Garment(PlayNewCase):
    def test_dark_heather_refuses_by_name_never_keyerror(self):
        code, _, err = self.run_tool("--garment", "Dark Heather")
        self.assertEqual(code, 2)
        self.assertIn("GARMENT_NOT_LIVE", err)
        self.assertIn("SECTION A item 2", err)

    def test_both_splits_three_two_first_garment_first(self):
        self.assertIn(self.run_tool()[0], (0, 1))
        garments = [v["garment"].lower()
                    for v in self.play()["variants"]]
        first_live = pn.live_garments()[0]
        self.assertEqual(garments.count(first_live), 3)
        self.assertEqual(len(set(garments)), 2)

    def test_fixed_garment_pins_every_variant(self):
        self.assertIn(self.run_tool("--garment", "Black")[0], (0, 1))
        self.assertEqual({v["garment"].lower()
                          for v in self.play()["variants"]},
                         {"black"})


class T17BootAssertion(unittest.TestCase):
    def test_registry_layout_without_defaults_exits_2_at_import(self):
        widened = tuple(play_schema.LAYOUTS) + ("brand_new_layout",)
        with mock.patch.object(play_schema, "LAYOUTS", widened):
            with self.assertRaises(SystemExit) as caught:
                importlib.reload(pn)
        self.assertEqual(caught.exception.code, 2)
        importlib.reload(pn)          # leave the module sane
        self.assertEqual(
            sorted(pn.ELEMENT_DEFAULTS),
            sorted(play_schema.LAYOUTS))


class T18CrashFloor(PlayNewCase):
    def test_uncaught_exception_is_exit_2_with_a_crash_receipt(self):
        """A traceback exits 1, and 1 means 'written with findings'
        here — the floor is what keeps a crash from looking like a
        successful write to a caller."""
        with mock.patch.object(pn, "build_play",
                               side_effect=RuntimeError("injected")):
            code, _, err = self.run_tool()
        self.assertEqual(code, 2)
        self.assertIn("CRASH", err)
        self.assertIn("injected", err)
        receipt = self.receipts()[-1]
        self.assertEqual(receipt["refusals"][0]["kind"], "CRASH")
        self.assertEqual(receipt["exit_code"], 2)

    def test_receipt_on_every_terminating_path(self):
        self.run_tool()                                   # exit 0/1
        self.run_tool(tag="nothing matches this")         # exit 2
        kinds = [r["exit_code"] for r in self.receipts()]
        self.assertIn(2, kinds)
        self.assertTrue(any(k in (0, 1) for k in kinds))
        self.assertTrue(all("sidecar" in r for r in self.receipts()))


class T19FrameSingleCandidate(PlayNewCase):
    def test_one_candidate_goes_left_and_is_not_duplicated(self):
        self.write_index((("cf/only.png", "mail carrier, generic"),))
        self.assertIn(self.run_tool()[0], (0, 1))
        frames = [v for v in self.play()["variants"]
                  if v["layout"] == "frame"]
        self.assertTrue(frames)
        for variant in frames:
            self.assertEqual(variant["element_count"], 1)
            self.assertEqual(variant["elements"][0]["position"],
                             pn.SINGLE_CANDIDATE_POSITION)


class T20PlayContents(PlayNewCase):
    def test_play_carries_feeling_axes_counts_and_hashes(self):
        self.assertIn(self.run_tool(feeling="smug pride")[0], (0, 1))
        play = self.play()
        self.assertEqual(play["named_feeling"], "smug pride")
        self.assertEqual(play["draft_note"], pn.DRAFT_NOTE)
        for variant in play["variants"]:
            self.assertEqual(
                sorted(variant["axes"]),
                ["color_path", "family", "font_pair", "garment",
                 "layout"])
            self.assertEqual(variant["element_count"],
                             len(variant["elements"]))
            for element in variant["elements"]:
                self.assertEqual(element["expected_sha256"], "a" * 64)

    def test_line_text_is_verbatim(self):
        odd = "  CAN'T   Leave it  NEXT door.  "
        self.assertIn(self.run_tool(setup=odd)[0], (0, 1))
        self.assertEqual(self.play()["line"]["setup"], odd)


if __name__ == "__main__":
    unittest.main()
