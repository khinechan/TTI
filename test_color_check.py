#!/usr/bin/env python3
"""Test suite for color_check.py — stdlib unittest only.

Tests 1-7 are the original spec. Tests 8-22 each exist because they are a
way this gate could be wrong while looking right. Test 18 audits the RULE
DATA rather than the code: if someone adds a colour to a palette that fails
the contrast floor, the suite catches it forever.
"""

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock
from itertools import combinations

import color_check as cc


PASS, FAIL, ERROR = cc.EXIT_PASS, cc.EXIT_FAIL, cc.EXIT_ERROR


def run(argv):
    """Invoke the CLI. Returns (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = cc.main(argv)
        except SystemExit as exc:  # argparse usage errors exit directly
            code = exc.code if isinstance(exc.code, int) else cc.EXIT_ERROR
    return code, out.getvalue(), err.getvalue()


class BaseCase(unittest.TestCase):
    def assertVerdict(self, argv, expected_code, expected_verdict=None):
        code, out, err = run(argv)
        self.assertEqual(
            code, expected_code,
            "argv=%r expected exit %d, got %d\nSTDOUT:\n%s\nSTDERR:\n%s"
            % (argv, expected_code, code, out, err),
        )
        if expected_verdict is not None:
            self.assertIn("VERDICT: %s" % expected_verdict, out)
        return out, err


# ── 1-7: the original spec ─────────────────────────────────────────────

class TestOriginalSpec(BaseCase):

    def test_01_passing_dark_design(self):
        """gold + dusty blue on black -> PASS, exit 0."""
        out, _ = self.assertVerdict(
            ["black", "#D9A441", "#7A9CB0"], PASS, "PASS")
        self.assertIn("8.19:1", out)
        self.assertIn("6.32:1", out)

    def test_02_passing_light_design(self):
        """forest + burgundy on sport grey -> PASS, exit 0."""
        out, _ = self.assertVerdict(
            ["sport grey", "#3E5C46", "#5C1F2E"], PASS, "PASS")
        self.assertIn("forest", out)
        self.assertIn("burgundy", out)

    def test_03_brick_red_on_sport_grey_names_the_explicit_bar(self):
        """The reason must be the explicit bar and 2.46:1, never generic."""
        out, _ = self.assertVerdict(["sport grey", "#A34730"], FAIL, "FAIL")
        self.assertIn("explicitly barred on sport grey", out)
        self.assertIn("2.46", out)
        self.assertIn("brick red", out)
        self.assertNotIn("not on the light-garment allowlist", out)

    def test_04_three_design_colors_names_the_max_rule(self):
        out, _ = self.assertVerdict(
            ["black", "#D9A441", "#7A9CB0", "#9CAF88"], FAIL, "FAIL")
        self.assertIn("3 of max 2", out)
        self.assertIn("RULE 1 VIOLATED", out)
        self.assertIn("max is 2", out)

    def test_05_unknown_garment_lists_known_garments(self):
        out, _ = self.assertVerdict(["navy", "#D9A441"], FAIL, "FAIL")
        self.assertIn("unknown garment 'navy'", out)
        for name in cc.GARMENTS:
            self.assertIn(name, out)

    def test_06_below_contrast_fails_with_the_computed_ratio(self):
        """A colour that clears the floor on black and fails on a lighter
        garment. Contrast is computed against the SPECIFIC garment hex."""
        garment_hex = cc.GARMENTS["dark heather"]["hex"]
        offender = None
        for hex_color in cc.PALETTES["dark"]:
            if cc.contrast_ratio(hex_color, garment_hex) < cc.THRESHOLDS["MIN_CONTRAST"]:
                offender = hex_color
                break
        if offender is None:
            # No palette colour fails today, so prove the rule with a
            # temporary palette entry rather than skipping the check.
            offender = "#4A4846"
            cc.PALETTES["dark"][offender] = "test only"
            self.addCleanup(cc.PALETTES["dark"].pop, offender, None)
        ratio = cc.contrast_ratio(offender, garment_hex)
        out, _ = self.assertVerdict(["dark heather", offender], FAIL, "FAIL")
        self.assertIn("%.2f:1" % ratio, out)
        self.assertIn("below the 3.0:1 floor", out)

    def test_07_outline_on_dark_passes_and_is_not_counted(self):
        """RULING UPDATE D-341/D-342/D-343: black's ruled outline is
        gold #D9A441 (was #0C0C0C), and it now clears 3.0:1 by design."""
        out, _ = self.assertVerdict(
            ["black", "#7A9CB0", "--outline", "#D9A441"], PASS, "PASS")
        self.assertIn("DESIGN COLORS: 1 of max 2", out)
        self.assertIn("outline role, not counted", out)
        self.assertIn("8.19:1", out)


# ── 8-17: ways the gate could be wrong while looking right ─────────────

class TestGateIntegrity(BaseCase):

    def test_08_wrong_outline_for_the_garment_fails(self):
        """RULING UPDATE D-341/D-342/D-343: outlines are per-garment.
        #0C0C0C on sport grey now PASSES (it is the ruled outline); the
        FAIL case is using another garment's outline."""
        out, _ = self.assertVerdict(
            ["sport grey", "#3E5C46", "--outline", "#0C0C0C"], PASS, "PASS")
        self.assertIn("outline role, not counted", out)
        out, _ = self.assertVerdict(
            ["sport grey", "#3E5C46", "--outline", "#D9A441"], FAIL, "FAIL")
        self.assertIn("not sport grey's ruled outline", out)
        out, _ = self.assertVerdict(
            ["black", "#7A9CB0", "--outline", "#0C0C0C"], FAIL, "FAIL")
        self.assertIn("not black's ruled outline", out)

    def test_08b_outline_ratio_always_reported(self):
        """Even on the FAIL path, the outline's real ratio is in the
        report. RULING UPDATE: per-garment outlines and their measured
        ratios — black/gold 8.19, sport grey/black 8.02; dark heather
        is unruled (refused) yet the measured 1.78 still prints."""
        cases = ((["black", "#7A9CB0", "--outline", "#D9A441"], "8.19:1"),
                 (["sport grey", "#3E5C46", "--outline", "#0C0C0C"], "8.02:1"),
                 (["dark heather", "#D9A441", "--outline", "#0C0C0C"], "1.78:1"))
        for argv, expected in cases:
            _, out, _ = run(argv)
            self.assertIn(expected, out, "outline ratio missing: %r" % argv)

    def test_08c_dark_heather_has_no_ruled_outline(self):
        """RULING UPDATE D-341/D-342/D-343: the rulings name black and
        sport grey only. Dark heather's outline path is refused, fail
        closed — and the old visible-ring warning is gone with the old
        invisibility semantics."""
        out, _ = self.assertVerdict(
            ["dark heather", "#D9A441", "--outline", "#0C0C0C"], FAIL, "FAIL")
        self.assertIn("no outline is ruled for dark heather", out)
        self.assertNotIn("visible ring", out)

    def test_09_two_colors_plus_outline_passes(self):
        """Three hexes on the command line, two counted."""
        out, _ = self.assertVerdict(
            ["black", "#9CAF88", "#7A9CB0", "--outline", "#D9A441"],
            PASS, "PASS")
        self.assertIn("DESIGN COLORS: 2 of max 2", out)

    def test_10_duplicate_color_is_deduped(self):
        out, _ = self.assertVerdict(
            ["black", "#D9A441", "#D9A441"], PASS, "PASS")
        self.assertIn("DESIGN COLORS: 1 of max 2", out)
        self.assertIn("DEDUPE", out)

    def test_10b_dedupe_is_case_insensitive(self):
        out, _ = self.assertVerdict(
            ["black", "#D9A441", "#d9a441", "#7A9CB0"], PASS, "PASS")
        self.assertIn("DESIGN COLORS: 2 of max 2", out)

    def test_11_case_and_format_variants_are_identical(self):
        variants = ["#d9a441", "D9A441", " #D9A441 ", "#D9a441", " d9a441 "]
        baseline = None
        for variant in variants:
            code, out, _ = run(["black", variant])
            self.assertEqual(code, PASS, "variant %r did not pass" % variant)
            if baseline is None:
                baseline = out
            else:
                self.assertEqual(out, baseline,
                                 "variant %r produced a different report" % variant)

    def test_11b_garment_name_is_whitespace_and_case_tolerant(self):
        for name in ["black", "BLACK", " Black ", "sport grey", "SPORT  GREY"]:
            code, _, _ = run([name, "#D9A441" if "black" in name.lower()
                              else "#3E5C46"])
            self.assertEqual(code, PASS, "garment %r did not resolve" % name)

    def test_12_malformed_input_is_exit_2(self):
        for bad in ["#GGGGGG", "#12345", "blue", "", "#", "12345678901"]:
            code, _, err = run(["black", bad])
            self.assertEqual(code, ERROR, "%r should be ERROR, got %d" % (bad, code))
            self.assertIn("ERROR", err)

    def test_13_eight_digit_alpha_hex_is_exit_2(self):
        code, _, err = run(["black", "#D9A441FF"])
        self.assertEqual(code, ERROR)
        self.assertIn("alpha", err)

    def test_13b_malformed_outline_is_exit_2(self):
        code, _, _ = run(["black", "#D9A441", "--outline", "#ZZZZZZ"])
        self.assertEqual(code, ERROR)

    def test_14_three_digit_hex_expands_then_normal_rules_apply(self):
        self.assertEqual(cc.normalize_hex("#FFF"), "#FFFFFF")
        self.assertEqual(cc.normalize_hex("#fff"), "#FFFFFF")
        # Expansion is lossless, and #FFFFFF is not allowlisted -> FAIL, not ERROR.
        out, _ = self.assertVerdict(["black", "#FFF"], FAIL, "FAIL")
        self.assertIn("#FFFFFF", out)
        self.assertIn("not on the dark-garment allowlist", out)
        self.assertIn(":1", out)

    def test_14b_three_digit_shorthand_of_an_allowed_color_passes(self):
        short = None
        for hex_color in cc.PALETTES["dark"]:
            body = hex_color.lstrip("#")
            if body[0] == body[1] and body[2] == body[3] and body[4] == body[5]:
                short = "#" + body[0] + body[2] + body[4]
                break
        if short is None:
            self.assertEqual(cc.normalize_hex("#0CC"), "#00CCCC")
        else:
            self.assertEqual(run(["black", short])[0], PASS)

    def test_15_empty_color_list_fails(self):
        out, _ = self.assertVerdict(["black"], FAIL, "FAIL")
        self.assertIn("empty design cannot pass", out)

    def test_15b_all_duplicates_still_counts_as_one(self):
        self.assertEqual(run(["black", "#D9A441", "#D9A441", "#D9A441"])[0], PASS)

    def test_16_near_miss_suggests_but_still_fails(self):
        out, _ = self.assertVerdict(["black", "#D9A442"], FAIL, "FAIL")
        self.assertIn("did you mean gold #D9A441?", out)
        self.assertIn("VERDICT: FAIL", out)
        self.assertNotIn("VERDICT: PASS", out)

    def test_16b_distant_color_gets_no_bogus_suggestion(self):
        _, out, _ = run(["black", "#00FF00"])
        self.assertNotIn("did you mean", out)

    def test_16c_outline_hex_without_the_flag_fails_and_says_why(self):
        """The role is never inferred from the hex. RULING UPDATE: the
        hint is per-garment — #0C0C0C plain hints on sport grey (its
        ruled outline); on black it is just a non-allowlisted hex."""
        out, _ = self.assertVerdict(["sport grey", "#0C0C0C"], FAIL, "FAIL")
        self.assertIn("--outline", out)
        out, _ = self.assertVerdict(["black", "#0C0C0C"], FAIL, "FAIL")
        self.assertNotIn("--outline #0C0C0C", out)

    def test_17_exit_codes_are_distinct_per_class(self):
        cases = [
            (PASS,  ["black", "#D9A441"]),
            (FAIL,  ["black", "#D9A441", "#7A9CB0", "#9CAF88"]),
            (FAIL,  ["navy", "#D9A441"]),
            (FAIL,  ["sport grey", "#A34730"]),
            (FAIL,  ["black"]),
            (ERROR, ["black", "not-a-hex"]),
            (ERROR, ["black", "#D9A441FF"]),
        ]
        for expected, argv in cases:
            self.assertEqual(run(argv)[0], expected, "argv=%r" % argv)
        self.assertEqual(len({PASS, FAIL, ERROR}), 3)

    def test_17b_no_warn_and_pass_path_exists(self):
        """Every warning-producing input either PASSes cleanly or FAILs.
        A verdict is never softened into a pass by a warning."""
        argvs = [
            ["dark heather", "#C67B5C"],       # MARGINAL 3.34 (ruling
                                               # update: heather has no
                                               # ruled outline any more)
            ["black", "#D9A441", "#9CAF88"],
            ["sport grey", "#3E5C46"],
        ]
        for argv in argvs:
            code, out, _ = run(argv)
            self.assertIn("WARN", out, "expected a warning for %r" % argv)
            self.assertEqual(code, PASS, "argv=%r" % argv)
            self.assertIn("VERDICT: PASS", out)
        # And a warning never appears alongside a softened FAIL.
        # (RULING UPDATE: the FAIL case is now the WRONG outline.)
        code, out, _ = run(["sport grey", "#3E5C46", "--outline", "#D9A441"])
        self.assertEqual(code, FAIL)
        self.assertIn("VERDICT: FAIL", out)


# ── 18-20: the rule audits and the regression lock ─────────────────────

class TestRuleData(BaseCase):

    def test_18_rule_audit_every_color_on_every_garment_of_its_class(self):
        """THE RULE AUDIT. Tests the RULES, not the code. If someone adds a
        colour to an allowlist that fails the floor, this catches it forever."""
        floor = cc.THRESHOLDS["MIN_CONTRAST"]
        failures = []
        for garment_name, spec in cc.GARMENTS.items():
            garment_hex = cc.normalize_hex(spec["hex"])
            for hex_color, color_name in cc.PALETTES[spec["class"]].items():
                ratio = cc.contrast_ratio(cc.normalize_hex(hex_color), garment_hex)
                if ratio < floor:
                    failures.append(
                        "%s %s on %s %s = %.2f:1 (floor %.1f)"
                        % (color_name, hex_color, garment_name,
                           garment_hex, ratio, floor))
        self.assertEqual(failures, [], "palette violates the contrast floor:\n"
                                       + "\n".join(failures))

    def test_18b_audit_rules_mode_agrees_and_exits_zero_today(self):
        code, out, _ = run(["--audit-rules"])
        self.assertEqual(code, PASS)
        self.assertIn("VERDICT: PASS", out)

    def test_18c_audit_rules_catches_a_bad_palette_edit(self):
        """Proves test 18 has teeth: add a floor-violating colour and the
        audit must go red."""
        cc.PALETTES["light"]["#9E9E9C"] = "bad edit"
        self.addCleanup(cc.PALETTES["light"].pop, "#9E9E9C", None)
        self.assertEqual(run(["--audit-rules"])[0], FAIL)
        with self.assertRaises(AssertionError):
            self.test_18_rule_audit_every_color_on_every_garment_of_its_class()

    def test_19_inter_color_audit_reports_every_allowed_pair(self):
        """Print the mutual ratio of every allowed pair so palette expansion
        can never silently add a mud pair."""
        floor = cc.THRESHOLDS["MIN_INTER_COLOR"]
        lines, pair_count = [], 0
        for cls, palette in sorted(cc.PALETTES.items()):
            normalized = {cc.normalize_hex(h): n for h, n in palette.items()}
            for a, b in combinations(sorted(normalized), 2):
                ratio = cc.contrast_ratio(a, b)
                pair_count += 1
                lines.append("  %-6s %-14s vs %-14s %.2f:1%s"
                             % (cls, normalized[a], normalized[b], ratio,
                                "   MUD PAIR" if ratio < floor else ""))
        print("\n══ INTER-COLOUR AUDIT ══")
        print("\n".join(lines))
        expected = sum(len(p) * (len(p) - 1) // 2 for p in cc.PALETTES.values())
        self.assertEqual(pair_count, expected)
        code, out, _ = run(["--audit-rules"])
        self.assertEqual(code, PASS)
        self.assertIn("INTER-COLOUR AUDIT", out)

    def test_20_regression_lock_on_known_values(self):
        """Pins the math against any future refactor. If a refactor moves
        these numbers, the refactor is wrong."""
        locked = [
            ("#2A1810", "#A6A6A4", 6.96, "chocolate ink on sport grey, vault-measured D-311"),
            ("#A34730", "#A6A6A4", 2.46, "brick red on sport grey, the barring rationale"),
            ("#0C0C0C", "#141414", 1.06, "outline on black, invisible as intended"),
            ("#0C0C0C", "#3E3C3A", 1.78, "outline on dark heather, visibly different"),
            ("#3E5C46", "#A6A6A4", 3.05, "forest on sport grey, the thin one"),
        ]
        for a, b, expected, why in locked:
            actual = round(cc.contrast_ratio(a, b), 2)
            self.assertEqual(actual, expected,
                             "%s: %s vs %s = %.4f, locked at %.2f"
                             % (why, a, b, cc.contrast_ratio(a, b), expected))

    def test_20b_luminance_endpoints(self):
        self.assertAlmostEqual(cc.relative_luminance("#FFFFFF"), 1.0, places=6)
        self.assertAlmostEqual(cc.relative_luminance("#000000"), 0.0, places=6)
        self.assertAlmostEqual(cc.contrast_ratio("#FFFFFF", "#000000"), 21.0, places=6)
        self.assertAlmostEqual(cc.contrast_ratio("#D9A441", "#D9A441"), 1.0, places=6)

    def test_20c_config_validates(self):
        cc.validate_config()

    def test_20d_broken_config_is_exit_2(self):
        original = cc.GARMENTS["black"]["hex"]
        cc.GARMENTS["black"]["hex"] = "#NOPE"
        self.addCleanup(cc.GARMENTS["black"].__setitem__, "hex", original)
        code, _, err = run(["black", "#D9A441"])
        self.assertEqual(code, ERROR)
        self.assertIn("CONFIG", err)


# ── 21-22: provisional surfacing and the two output modes ──────────────

class TestOutputModes(BaseCase):

    def test_21_dark_heather_provisional_warning_in_human_mode(self):
        for argv in (["dark heather", "#D9A441"],
                     ["dark heather", "#D9A441", "--outline", "#0C0C0C"],
                     ["dark heather", "#FFFFFF"],
                     ["dark heather"]):
            _, out, _ = run(argv)
            self.assertIn("PROVISIONAL", out, "argv=%r" % argv)
            self.assertIn("unmeasured (approx)", out, "argv=%r" % argv)

    def test_21b_dark_heather_provisional_warning_in_json_mode(self):
        for argv in (["dark heather", "#D9A441", "--json"],
                     ["dark heather", "#FFFFFF", "--json"]):
            _, out, _ = run(argv)
            payload = json.loads(out)
            self.assertTrue(payload["provisional"])
            self.assertIn("unmeasured (approx)", payload["provisional_warning"])
            self.assertTrue(any("unmeasured" in w for w in payload["warnings"]))

    def test_21c_non_provisional_garments_do_not_warn(self):
        for garment, color in (("black", "#D9A441"), ("sport grey", "#3E5C46")):
            _, out, _ = run([garment, color])
            self.assertNotIn("PROVISIONAL", out)

    def test_22_json_parses_and_verdict_matches_human_mode(self):
        argvs = [
            ["black", "#D9A441", "#7A9CB0"],
            ["sport grey", "#3E5C46", "#5C1F2E"],
            ["sport grey", "#A34730"],
            ["black", "#D9A441", "#7A9CB0", "#9CAF88"],
            ["navy", "#D9A441"],
            ["black", "#7A9CB0", "--outline", "#D9A441"],
            ["sport grey", "#3E5C46", "--outline", "#0C0C0C"],
            ["dark heather", "#D9A441", "--outline", "#0C0C0C"],
            ["dark heather", "#C67B5C"],
            ["black", "#D9A442"],
            ["black"],
        ]
        for argv in argvs:
            human_code, human_out, _ = run(argv)
            json_code, json_out, _ = run(argv + ["--json"])
            payload = json.loads(json_out)
            self.assertEqual(human_code, json_code, "argv=%r" % argv)
            self.assertEqual(payload["exit_code"], human_code, "argv=%r" % argv)
            self.assertIn("VERDICT: %s" % payload["verdict"], human_out,
                          "argv=%r" % argv)

    def test_22b_json_error_path_is_valid_json_and_exit_2(self):
        code, out, _ = run(["black", "#GGGGGG", "--json"])
        self.assertEqual(code, ERROR)
        payload = json.loads(out)
        self.assertEqual(payload["verdict"], "ERROR")
        self.assertEqual(payload["exit_code"], ERROR)

    def test_22c_json_carries_per_color_ratios_and_rules(self):
        _, out, _ = run(["black", "#7A9CB0", "--outline", "#D9A441", "--json"])
        payload = json.loads(out)
        by_role = {e["role"]: e for e in payload["entries"]}
        self.assertEqual(by_role["design"]["ratio"], 6.32)
        self.assertEqual(by_role["outline"]["ratio"], 8.19)
        self.assertFalse(by_role["outline"]["counted"])
        self.assertEqual(payload["design_color_count"], 1)

    def test_22d_every_fail_names_a_rule_and_a_number(self):
        argvs = [
            ["sport grey", "#A34730"],
            ["black", "#D9A441", "#7A9CB0", "#9CAF88"],
            ["navy", "#D9A441"],
            ["dark heather", "#C67B5C", "--outline", "#0C0C0C"],
            ["black", "#D9A442"],
            ["black"],
        ]
        for argv in argvs:
            _, out, _ = run(argv + ["--json"])
            payload = json.loads(out)
            self.assertEqual(payload["verdict"], "FAIL", "argv=%r" % argv)
            self.assertTrue(payload["violations"], "argv=%r" % argv)
            for violation in payload["violations"]:
                self.assertIn(violation["rule"], cc.RULES, "argv=%r" % argv)
                self.assertTrue(violation["message"].strip(), "argv=%r" % argv)

    def test_22e_footer_and_help_state_file_level_scope(self):
        _, out, _ = run(["black", "#D9A441"])
        self.assertIn("file-level check only", out)
        _, json_out, _ = run(["black", "#D9A441", "--json"])
        self.assertIn("file-level", json.loads(json_out)["disclaimer"])
        help_text = cc.build_parser().format_help()
        self.assertIn("DESIGN FILE", help_text)
        self.assertIn("file-level PASS only", help_text)

    def test_22f_list_garments_mode(self):
        code, out, _ = run(["--list-garments"])
        self.assertEqual(code, PASS)
        for name in cc.GARMENTS:
            self.assertIn(name, out)
        code, json_out, _ = run(["--list-garments", "--json"])
        self.assertEqual(code, PASS)
        payload = json.loads(json_out)
        self.assertEqual(len(payload), len(cc.GARMENTS))


# ── 24: per-garment outlines (D-341/D-342/D-343) ───────────────────────

class TestPerGarmentOutlines(BaseCase):
    """The rulings: outlines are PER-GARMENT (black -> gold #D9A441,
    sport grey -> #0C0C0C), the outline must clear 3.0:1 against the
    garment on the outline path, and the fill underneath is
    unconstrained. Flat-pool checks unchanged."""

    def test_24_each_ruled_outline_accepted_and_crosses_refused(self):
        self.assertEqual(run(["black", "#7A9CB0", "--outline",
                              "#D9A441"])[0], PASS)
        self.assertEqual(run(["sport grey", "#3E5C46", "--outline",
                              "#0C0C0C"])[0], PASS)
        for argv in (["black", "#7A9CB0", "--outline", "#0C0C0C"],
                     ["sport grey", "#3E5C46", "--outline", "#D9A441"]):
            code, out, _ = run(argv)
            self.assertEqual(code, FAIL, argv)
            self.assertIn("ruled outline", out)

    def test_24b_outline_below_floor_is_a_wired_fail(self):
        """R8 is a mechanism, not prose: an outline that cannot clear
        3.0:1 fails with the rule and the number, proven by temporarily
        ruling a low-contrast outline."""
        cc.OUTLINES["dark heather"] = {"hex": "#0C0C0C",
                                       "name": "test outline"}
        self.addCleanup(cc.OUTLINES.pop, "dark heather", None)
        out, _ = self.assertVerdict(
            ["dark heather", "#D9A441", "--outline", "#0C0C0C"],
            FAIL, "FAIL")
        self.assertIn("R8", out)
        self.assertIn("1.78:1", out)
        self.assertIn("below the 3.0:1 floor", out)

    def test_24c_fill_is_unconstrained_on_the_outline_path(self):
        """A fill that FAILS the flat-pool floor passes under an
        outline — the outline carries the legibility. Proven with a
        temporary low-contrast palette entry."""
        cc.PALETTES["dark"]["#2A2A2A"] = "test shadow"
        self.addCleanup(cc.PALETTES["dark"].pop, "#2A2A2A", None)
        code, out, _ = run(["black", "#2A2A2A"])          # flat path
        self.assertEqual(code, FAIL)
        self.assertIn("below the 3.0:1 floor", out)
        code, out, _ = run(["black", "#2A2A2A",           # outline path
                            "--outline", "#D9A441"])
        self.assertEqual(code, PASS, out)
        self.assertIn("floor not applied", out)
        self.assertIn("outline carries legibility", out)

    def test_24d_flat_pool_checks_unchanged(self):
        """No outline declared -> the old floor still bites."""
        cc.PALETTES["dark"]["#2A2A2A"] = "test shadow"
        self.addCleanup(cc.PALETTES["dark"].pop, "#2A2A2A", None)
        self.assertEqual(run(["black", "#2A2A2A"])[0], FAIL)
        self.assertEqual(run(["black", "#D9A441", "#7A9CB0"])[0], PASS)

    def test_24e_rule_audit_covers_the_ruled_outlines(self):
        """The audit now judges outline data like any colour: today
        both ruled outlines clear the floor; a bad ruling would go red."""
        code, out, _ = run(["--audit-rules"])
        self.assertEqual(code, PASS)
        self.assertIn("outline gold", out)
        self.assertIn("outline black", out)
        self.assertNotIn("EXEMPT", out)
        cc.OUTLINES["black"] = {"hex": "#0C0C0C", "name": "bad ruling"}
        self.addCleanup(cc.OUTLINES.__setitem__, "black",
                        {"hex": "#D9A441", "name": "outline gold"})
        self.assertEqual(run(["--audit-rules"])[0], FAIL)

    def test_24f_list_garments_names_the_per_garment_outline(self):
        _, out, _ = run(["--list-garments"])
        self.assertIn("outline gold", out)
        self.assertIn("outline black", out)
        self.assertIn("no outline ruled", out)   # dark heather


# ── 25: D-401 input doctrine ───────────────────────────────────────────

class TestInputDoctrine(BaseCase):
    """D-401: gates are certified for lossless PNG only. This tool
    receives hex values, not files, so there is nothing to detect here
    — the doctrine is stamped on every report and in --help instead;
    format DETECTION lives in thumb_check, which opens the image."""

    def test_25_doctrine_in_every_report_both_modes(self):
        _, out, _ = run(["black", "#D9A441"])
        self.assertIn("D-401", out)
        self.assertIn("lossless PNG only", out)
        self.assertIn("never from a JPEG export", out)
        _, json_out, _ = run(["black", "#D9A441", "--json"])
        payload = json.loads(json_out)
        self.assertIn("358,458", payload["input_doctrine"])

    def test_25b_doctrine_in_help(self):
        help_text = cc.build_parser().format_help()
        self.assertIn("D-401", help_text)
        self.assertIn("lossless PNG only", help_text)
        self.assertIn("in thumb_check, which opens the image", help_text)

    def test_25c_exit_codes_untouched_by_the_doctrine(self):
        self.assertEqual(run(["black", "#D9A441"])[0], PASS)
        self.assertEqual(run(["sport grey", "#A34730"])[0], FAIL)
        self.assertEqual(run(["black", "#GGGGGG"])[0], ERROR)


# ── 23: Windows console-encoding fix (STATE.md D-378) ──────────────────

class TestCrashFloor(BaseCase):
    """Fleet crash floor: a Python traceback exits 1, which this tool's
    contract reads as FAIL — a real verdict on a real design. Exit 2 is
    what tells a wrapper the tool broke instead."""

    def test_uncaught_exception_is_exit_2_and_names_the_type(self):
        with mock.patch.object(cc, "run_check",
                               side_effect=RuntimeError("injected")):
            code, out, err = run(["black", "#FFFFFF"])
        self.assertEqual(code, cc.EXIT_ERROR)
        self.assertIn("CRASH (RuntimeError): injected", err)
        self.assertEqual(out, "")

    def test_crash_json_parity(self):
        with mock.patch.object(cc, "run_check",
                               side_effect=RuntimeError("injected")):
            code, out, _ = run(["black", "#FFFFFF", "--json"])
        self.assertEqual(code, cc.EXIT_ERROR)
        payload = json.loads(out)
        self.assertEqual(payload["verdict"], "CRASH")
        self.assertEqual(payload["exit_code"], cc.EXIT_ERROR)
        self.assertIn("RuntimeError: injected", payload["error"])


class TestConsoleEncoding(BaseCase):
    """color_check.py crashed with UnicodeEncodeError on a real Windows
    cp1252 console the first time --audit-rules ran natively (STATE.md
    D-378) -- the ══ banner text isn't representable in that codepage.
    Fixed by reconfiguring stdout/stderr to UTF-8 (errors="replace") at
    the top of main(). These tests exist because the fix itself is a way
    this suite could quietly stop testing anything: every test above
    runs main() under redirect_stdout(io.StringIO()), and io.StringIO
    has no .reconfigure -- a careless fix would have broken all 44 tests
    the instant it landed, not just the Windows crash it was meant to
    close.
    """

    def test_23_reconfigure_is_a_noop_on_a_plain_stringio(self):
        """io.StringIO has no .reconfigure -- the same shape every test
        above's own run() helper swaps in. If this raised, the whole
        suite would already be red; this names the reason it isn't."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            cc._ensure_utf8_console()  # must not raise AttributeError

    def test_23b_reconfigure_is_called_with_utf8_replace_when_supported(self):
        """When the stream DOES support .reconfigure (the real case on
        a live console), confirm the fix calls it with the right args --
        not just that it's safe to call when it's absent."""
        calls = []

        class FakeStream:
            def reconfigure(self, **kwargs):
                calls.append(kwargs)

        with redirect_stdout(FakeStream()), redirect_stderr(FakeStream()):
            cc._ensure_utf8_console()
        self.assertEqual(calls, [{"encoding": "utf-8", "errors": "replace"}] * 2)

    def test_23c_audit_rules_banner_survives_the_fix(self):
        """The exact crash site from D-378: --audit-rules prints the
        ══ RULE AUDIT ══ banner. Confirms the banner text still comes
        through whole post-fix, not just that the PASS/FAIL verdict
        still resolves (test 18b already covers that half)."""
        code, out, _ = run(["--audit-rules"])
        self.assertEqual(code, PASS)
        self.assertIn("RULE AUDIT", out)
        self.assertIn("INTER-COLOUR AUDIT", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
