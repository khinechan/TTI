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
        out, _ = self.assertVerdict(
            ["black", "#D9A441", "--outline", "#0C0C0C"], PASS, "PASS")
        self.assertIn("DESIGN COLORS: 1 of max 2", out)
        self.assertIn("outline role, not counted", out)
        self.assertIn("1.06:1", out)


# ── 8-17: ways the gate could be wrong while looking right ─────────────

class TestGateIntegrity(BaseCase):

    def test_08_outline_on_light_garment_fails(self):
        out, _ = self.assertVerdict(
            ["sport grey", "#3E5C46", "--outline", "#0C0C0C"], FAIL, "FAIL")
        self.assertIn("not permitted on sport grey", out)
        self.assertIn("dark-only", out)

    def test_08b_outline_ratio_always_reported(self):
        """Even on the FAIL path, the outline's real ratio is in the report."""
        for garment, expected in (("black", "1.06:1"),
                                  ("dark heather", "1.78:1"),
                                  ("sport grey", "8.02:1")):
            _, out, _ = run([garment, "--outline", "#0C0C0C", "#D9A441"]
                            if garment != "sport grey"
                            else [garment, "#3E5C46", "--outline", "#0C0C0C"])
            self.assertIn(expected, out, "outline ratio missing for %s" % garment)

    def test_08c_outline_visibility_warning_on_dark_heather(self):
        """1.78:1 exceeds OUTLINE_VISIBILITY_WARN -> visible-ring warning."""
        _, out, _ = run(["dark heather", "#D9A441", "--outline", "#0C0C0C"])
        self.assertIn("visible ring", out)
        _, black_out, _ = run(["black", "#D9A441", "--outline", "#0C0C0C"])
        self.assertNotIn("visible ring", black_out)

    def test_09_two_colors_plus_outline_passes(self):
        """Three hexes on the command line, two counted."""
        out, _ = self.assertVerdict(
            ["black", "#D9A441", "#7A9CB0", "--outline", "#0C0C0C"],
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
        """The role is never inferred from the hex."""
        out, _ = self.assertVerdict(["black", "#0C0C0C"], FAIL, "FAIL")
        self.assertIn("--outline", out)

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
            ["dark heather", "#D9A441", "--outline", "#0C0C0C"],
            ["black", "#D9A441", "#9CAF88"],
            ["sport grey", "#3E5C46"],
        ]
        for argv in argvs:
            code, out, _ = run(argv)
            self.assertIn("WARN", out, "expected a warning for %r" % argv)
            self.assertEqual(code, PASS, "argv=%r" % argv)
            self.assertIn("VERDICT: PASS", out)
        # And a warning never appears alongside a softened FAIL.
        code, out, _ = run(["sport grey", "#3E5C46", "--outline", "#0C0C0C"])
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
            ["black", "#D9A441", "--outline", "#0C0C0C"],
            ["sport grey", "#3E5C46", "--outline", "#0C0C0C"],
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
        _, out, _ = run(["black", "#D9A441", "--outline", "#0C0C0C", "--json"])
        payload = json.loads(out)
        by_role = {e["role"]: e for e in payload["entries"]}
        self.assertEqual(by_role["design"]["ratio"], 8.19)
        self.assertEqual(by_role["outline"]["ratio"], 1.06)
        self.assertFalse(by_role["outline"]["counted"])
        self.assertEqual(payload["design_color_count"], 1)

    def test_22d_every_fail_names_a_rule_and_a_number(self):
        argvs = [
            ["sport grey", "#A34730"],
            ["black", "#D9A441", "#7A9CB0", "#9CAF88"],
            ["navy", "#D9A441"],
            ["sport grey", "#3E5C46", "--outline", "#0C0C0C"],
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
