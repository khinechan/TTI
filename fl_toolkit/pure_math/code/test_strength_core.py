"""Tests for strength_core (STD chart strength and favorability). No dates anywhere: the pillars are written out
as strings, and the classical cycles are checked against the pack's own modular arithmetic.
Run: python3 -m unittest test_strength_core -v"""
import itertools
import unittest
from unittest import mock
import bazi_core as Z
import strength_core as S

PILLARS_A = ["庚申", "甲申", "壬申", None]           # no birth time → partial
PILLARS_B = ["己巳", "癸酉", "甲戌", "丁卯"]
FAM_BY_STEP = {0: "peer", 1: "output", 2: "wealth", 3: "officer", 4: "resource"}   # d = (e − e_DM) mod 5, as in §5


class Expectations(unittest.TestCase):
    def check(self, pillars, totals, S_, verdict, F, partial, dm, dme):
        r = S.chart_strength(pillars)
        self.assertEqual(set(r["totals"]), set(Z.ELEMENTS))
        for e, v in totals.items(): self.assertAlmostEqual(r["totals"][e], v, delta=1e-9, msg=e)
        self.assertEqual(round(r["S"], 4), S_); self.assertEqual(r["verdict"], verdict)
        self.assertEqual(r["F"], F); self.assertIs(r["partial"], partial)
        self.assertEqual((r["dm"], r["dm_element"]), (dm, dme))

    def test_A(self):
        self.check(PILLARS_A, dict(wood=1.0, fire=0.0, earth=0.4, metal=3.4, water=1.2), 0.7667, "strong",
                   dict(wood=1.0, fire=1.0, earth=1.0, metal=-1.0, water=-1.0), True, "壬", "water")

    def test_B(self):
        self.check(PILLARS_B, dict(wood=1.0, fire=1.7, earth=1.7, metal=2.6, water=1.0), 0.25, "weak",
                   dict(wood=1.0, water=1.0, fire=-0.5, earth=-1.0, metal=-1.0), False, "甲", "wood")

    def test_functions_agree_with_chart_strength(self):
        T, partial = S.element_totals(PILLARS_B)
        self.assertFalse(partial)
        self.assertEqual(S.strength(T, "wood"), S.chart_strength(PILLARS_B)["S"])
        self.assertEqual(S.favorability("wood", S.strength(T, "wood"), "酉"), S.chart_strength(PILLARS_B)["F"])


class HiddenStems(unittest.TestCase):
    def test_table_covers_all_12_branches(self):
        self.assertEqual(sorted(S.HIDDEN, key=Z.BRANCHES.index), list(Z.BRANCHES))
        brief = "子癸 丑己癸辛 寅甲丙戊 卯乙 辰戊乙癸 巳丙庚戊 午丁己 未己丁乙 申庚壬戊 酉辛 戌戊辛丁 亥壬甲".split()
        self.assertEqual(S.HIDDEN, {w[0]: w[1:] for w in brief})
        for b, hs in S.HIDDEN.items():
            self.assertTrue(set(hs) <= set(Z.STEMS), b)
            self.assertAlmostEqual(sum(S.HIDDEN_W[len(hs)]), 1.0, places=12)

    def test_each_branch_adds_exactly_its_weight(self):
        # a lone branch moved around the chart: 1 in year/day/hour, MONTH_W in the month
        for b in Z.BRANCHES:
            for k in range(4):
                p = ["甲子"] * 4; p[k] = "甲" + b
                base = sum(S.element_totals(["甲子"] * 4)[0].values()); tot = sum(S.element_totals(p)[0].values())
                self.assertAlmostEqual(tot, base, places=12)   # every branch weighs 1 (or 2 in the month)
            T, _ = S.element_totals(["甲" + b, "甲子", "甲子", "甲子"])
            self.assertAlmostEqual(sum(T.values()), 3 * S.VISIBLE_W + 3 + S.MONTH_W, places=12)   # 3 stems, 4 branches

    def test_month_branch_doubles_but_month_stem_does_not(self):
        T1, _ = S.element_totals(["甲子", "庚申", "甲子", "甲子"])   # 庚申 as the month
        T0, _ = S.element_totals(["庚申", "甲子", "甲子", "甲子"])   # 庚申 as the year
        diff = {e: round(T1[e] - T0[e], 12) for e in Z.ELEMENTS}
        # moving 申 into the month adds one more copy of 申 and drops one copy of 子; the stems are the same set
        self.assertEqual(diff, dict(wood=0.0, fire=0.0, earth=0.1, metal=0.6, water=round(0.3 - 1.0, 12)))

    def test_day_master_excluded_and_hour_skipped(self):
        T, partial = S.element_totals(["甲子", "甲子", "庚子", None])
        self.assertTrue(partial)
        self.assertEqual(T, dict(wood=2.0, fire=0.0, earth=0.0, metal=0.0, water=4.0))   # 庚 is the DM: not counted
        T2, partial2 = S.element_totals(["甲子", "甲子", "庚子", "丙午"])
        self.assertFalse(partial2)
        self.assertAlmostEqual(T2["fire"], 1.0 + 0.7, places=12); self.assertAlmostEqual(T2["earth"], 0.3, places=12)

    def test_bad_pillars_refused(self):
        for bad in (["庚申", "甲申", None, None], ["庚X", "甲申", "壬申", None], ["庚申", "甲申", "壬申"],
                    ["庚申", "甲申", "壬申", "丁"], [None, "甲申", "壬申", None]):
            with self.assertRaises(ValueError, msg=bad): S.element_totals(bad)


class Families(unittest.TestCase):
    def test_all_25_pairs(self):
        for d, e in itertools.product(Z.ELEMENTS, repeat=2):
            step = (Z.ELEMENTS.index(e) - Z.ELEMENTS.index(d)) % 5
            self.assertEqual(S.family(d, e), FAM_BY_STEP[step], (d, e))

    def test_cycles_are_the_briefs(self):
        order = ["wood", "fire", "earth", "metal", "water"]
        self.assertEqual(S.GEN, {order[i]: order[(i + 1) % 5] for i in range(5)})
        ctl = ["wood", "earth", "water", "fire", "metal"]
        self.assertEqual(S.CTL, {ctl[i]: ctl[(i + 1) % 5] for i in range(5)})

    def test_agrees_with_ten_gods(self):
        names = {"peer": ("比肩", "劫財"), "output": ("食神", "傷官"), "wealth": ("偏財", "正財"),
                 "officer": ("七殺", "正官"), "resource": ("偏印", "正印")}
        for dm, st in itertools.product(Z.STEMS, repeat=2):
            self.assertIn(Z.ten_god(dm, st), names[S.family(S.element_of(dm), S.element_of(st))])


class Favorability(unittest.TestCase):
    def test_rules_and_season(self):
        for d, b in itertools.product(Z.ELEMENTS, Z.BRANCHES):
            for S_, v in ((0.2, "weak"), (0.5, "balanced"), (0.8, "strong"), (0.45, "balanced"), (0.55, "balanced")):
                F = S.favorability(d, S_, b)
                for e in Z.ELEMENTS:
                    sup = S.family(d, e) in S.SUPPORT
                    base = 0.0 if v == "balanced" else (1.0 if sup == (v == "weak") else -1.0)
                    bump = S.SEASON_BUMP if (e == "fire" and b in S.SEASON_FIRE) or (e == "water" and b in S.SEASON_WATER) else 0.0
                    self.assertEqual(F[e], max(-1.0, min(1.0, base + bump)), (d, S_, b, e))
        self.assertEqual(set(S.SEASON_FIRE) | set(S.SEASON_WATER), set(Z.BRANCHES) - set("寅卯辰"))

    def test_clip_top(self):          # A: strong, fire +1, autumn month → 1.5 clipped to 1
        self.assertEqual(S.favorability("water", 0.7667, "申")["fire"], 1.0)
        self.assertEqual(S.favorability("fire", 0.2, "午")["water"], -0.5)   # weak fire: water −1 + 0.5

    def test_clip_both_ends(self):
        with mock.patch.object(S, "SEASON_BUMP", -0.5):    # a negative bump must hit the floor, not pass −1
            self.assertEqual(S.favorability("wood", 0.2, "申")["fire"], -1.0)
        with mock.patch.object(S, "SEASON_BUMP", 3.0):
            self.assertEqual(S.favorability("wood", 0.2, "申")["fire"], 1.0)

    def test_bad_month_branch(self):
        for bad in ("", "申酉", "X", None):
            with self.assertRaises(ValueError): S.favorability("wood", 0.2, bad)

    def test_strength_scale_free(self):
        T, _ = S.element_totals(PILLARS_A)
        self.assertAlmostEqual(S.strength({e: 3 * v for e, v in T.items()}, "water"), S.strength(T, "water"), places=12)


if __name__ == "__main__":
    unittest.main()
