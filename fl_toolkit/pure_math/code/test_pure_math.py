"""Tests for the pure math. No dates are written anywhere in this file: calendar checks use Julian Day
Numbers drawn at random and the formulas' own inverse; sky checks compare two independent formulas at
random moments. Run: python3 -m unittest test_pure_math -v"""
import datetime as dt
import math
import random
import unittest
import ephem
import astro_core as A
import bazi_core as Z
import pair_core as P

UTC = dt.timezone.utc
RNG = random.Random(12)
J2000_JD = 2451545            # the astronomers' reference day number (a constant)
EPHEM_ZERO_JD = 2415020.0     # ephem counts days from this Julian Date


def moment_from_jd(jd):
    """A Julian Date → an aware UTC datetime (via ephem's own day count)."""
    return ephem.Date(jd - EPHEM_ZERO_JD).datetime().replace(tzinfo=UTC)


def random_jdn():
    return RNG.randrange(2_000_000, 2_600_000)


def meeus_sun(jd):
    """Meeus' low-precision apparent solar longitude (an independent formula, ~0.01°)."""
    T = (jd - J2000_JD) / 36525.0
    L0 = 280.46646 + 36000.76983 * T + 0.0003032 * T * T
    M = math.radians(357.52911 + 35999.05029 * T - 0.0001537 * T * T)
    C = ((1.914602 - 0.004817 * T - 0.000014 * T * T) * math.sin(M)
         + (0.019993 - 0.000101 * T) * math.sin(2 * M) + 0.000289 * math.sin(3 * M))
    om = math.radians(125.04 - 1934.136 * T)
    return (L0 + C - 0.00569 - 0.00478 * math.sin(om)) % 360


# the classical tables, written out the long way (the formulas in bazi_core must reproduce them)
CLASH = {frozenset(p) for p in ["子午", "丑未", "寅申", "卯酉", "辰戌", "巳亥"]}
COMB = {frozenset(p) for p in ["子丑", "寅亥", "卯戌", "辰酉", "巳申", "午未"]}
HARM = {frozenset(p) for p in ["子未", "丑午", "寅巳", "卯辰", "申亥", "酉戌"]}
PEN = {frozenset(p) for p in ["寅巳", "巳申", "申寅", "丑戌", "戌未", "未丑", "子卯"]}


class Calendar(unittest.TestCase):
    def test_jdn_round_trip(self):
        for _ in range(3000):
            J = random_jdn(); self.assertEqual(Z.jdn(*Z.civil_from_jdn(J)), J)

    def test_reference_day_pillar(self):          # the J2000 reference day is a 戊午 day
        self.assertEqual(Z.pillar_name(Z.day_index(*Z.civil_from_jdn(J2000_JD))), "戊午")

    def test_day_index_steps_and_cycles(self):
        for _ in range(500):
            J = random_jdn(); g = Z.day_index(*Z.civil_from_jdn(J))
            self.assertEqual(Z.day_index(*Z.civil_from_jdn(J + 1)), (g + 1) % 60)
            self.assertEqual(Z.day_index(*Z.civil_from_jdn(J + 60)), g)

    def test_day_flips_at_23(self):
        for _ in range(200):
            y, m, d = Z.civil_from_jdn(random_jdn())
            self.assertEqual(Z.day_index(y, m, d, 23.5), (Z.day_index(y, m, d) + 1) % 60)
            self.assertEqual(Z.day_index(y, m, d, 22.9), Z.day_index(y, m, d))

    def test_hour_branches(self):
        want = {0: "子", 0.5: "子", 1: "丑", 7: "辰", 9: "巳", 11: "午", 13: "未", 15: "申", 17: "酉", 23: "子"}
        for h, b in want.items(): self.assertEqual(Z.hour_branch(h), b, h)


class Branches(unittest.TestCase):
    def test_formulas_match_tables(self):
        for a in Z.BRANCHES:
            for b in Z.BRANCHES:
                if a == b: continue
                r = set(Z.relations(a, b)); p = frozenset(a + b)
                self.assertEqual("冲" in r, p in CLASH, a + b)
                self.assertEqual("合" in r, p in COMB, a + b)
                self.assertEqual("害" in r, p in HARM, a + b)
                self.assertEqual("刑" in r, p in PEN, a + b)

    def test_same_and_self_penalty(self):
        for b in Z.BRANCHES:
            self.assertEqual(Z.relations(b, b), ["自刑" if b in "辰午酉亥" else "same"])

    def test_double_relations(self):
        self.assertEqual(sorted(Z.relations("巳", "申")), sorted(["合", "刑"]))
        self.assertEqual(sorted(Z.relations("寅", "巳")), sorted(["害", "刑"]))


class Stems(unittest.TestCase):
    def test_ten_gods_for_a_wood_day_master(self):
        want = {"甲": "比肩", "乙": "劫財", "丙": "食神", "丁": "傷官", "戊": "偏財", "己": "正財",
                "庚": "七殺", "辛": "正官", "壬": "偏印", "癸": "正印"}
        for s, g in want.items(): self.assertEqual(Z.ten_god("甲", s), g, s)

    def test_ten_gods_for_a_water_day_master(self):
        want = {"壬": "比肩", "癸": "劫財", "甲": "食神", "乙": "傷官", "丙": "偏財", "丁": "正財",
                "戊": "七殺", "己": "正官", "庚": "偏印", "辛": "正印"}
        for s, g in want.items(): self.assertEqual(Z.ten_god("壬", s), g, s)

    def test_combine_pairs(self):
        for a, b in ("甲己", "乙庚", "丙辛", "丁壬", "戊癸"):
            self.assertEqual(Z.combine_partner(a), b); self.assertEqual(Z.combine_partner(b), a)

    def test_stem_bonus_shape(self):
        # for any day master: two stems at +10 (combine partner, 七殺), three at +5 (傷官, 偏印, 正印)
        for dm in Z.STEMS:
            self.assertEqual(sorted(Z.stem_bonus(dm, s) for s in Z.STEMS), [0] * 5 + [5] * 3 + [10] * 2, dm)


class Stars(unittest.TestCase):
    def test_peach_blossom(self):
        want = {"申": "酉", "子": "酉", "辰": "酉", "巳": "午", "酉": "午", "丑": "午",
                "寅": "卯", "午": "卯", "戌": "卯", "亥": "子", "卯": "子", "未": "子"}
        for y, p in want.items(): self.assertEqual(Z.peach_blossom(y), p, y)

    def test_luck_direction(self):
        self.assertTrue(Z.luck_forward(True, "甲")); self.assertTrue(Z.luck_forward(False, "乙"))
        self.assertFalse(Z.luck_forward(True, "乙")); self.assertFalse(Z.luck_forward(False, "甲"))

    def test_luck_pillar_steps(self):
        self.assertEqual(Z.luck_pillar(9, 4, False), 5); self.assertEqual(Z.luck_pillar(9, 3, True), 12)
        self.assertAlmostEqual(Z.luck_start_years(3.3), 1.1)


class Scores(unittest.TestCase):
    def test_rescale_and_tiers(self):
        self.assertEqual(Z.rescale(60), 20); self.assertEqual(Z.rescale(90), 86); self.assertEqual(Z.rescale(10), 5)
        self.assertEqual([Z.tier(x) for x in (85, 84, 65, 64, 45, 44)], ["🔴", "🟠", "🟠", "🟡", "🟡", "🟢"])

    def test_day_score_by_hand(self):
        # synthetic sets: own {子, 午}, other {卯}; day 丙子, day master 甲, year branch 子 (peach 酉)
        raw, scaled, parts = Z.day_score("丙", "子", ["子", "午"], ["卯"], "甲", "子")
        self.assertEqual(raw, 35 + 6 + 20 + 12)      # same 子子 6 · 冲 子午 20 · 刑 子卯 (other) 12 · 丙 = 食神 → 0
        self.assertEqual(scaled, Z.rescale(73))

    def test_luck_branch_counts_on_its_own(self):
        # a luck branch that repeats a natal branch adds its relations a second time
        one, _ = Z.hour_score("申", "子", ["巳"], [], "子")
        two, _ = Z.hour_score("申", "子", ["巳", "巳"], [], "子")
        self.assertEqual(two - one, 25)              # 合 10 + 刑 15 again

    def test_hour_score_by_hand(self):
        tot, parts = Z.hour_score("酉", "辰", ["子"], ["卯"], "子")
        self.assertEqual(tot, 15 + 10 + 8)           # 酉卯 冲 (other) 15 · day 辰 vs 酉 合 10 · 酉 = peach 8


class Sky(unittest.TestCase):
    def test_sep_and_orb(self):
        self.assertAlmostEqual(A.sep(10, 350), 20); self.assertAlmostEqual(A.sep(350, 10), -20)
        self.assertAlmostEqual(A.orb(0, 91, 90), 1.0); self.assertAlmostEqual(A.distance(359, 1), 2)

    def test_sun_agrees_with_an_independent_formula(self):
        for _ in range(40):
            jd = J2000_JD + RNG.uniform(-30000, 30000)
            self.assertLess(A.distance(A.lon('Sun', moment_from_jd(jd)), meeus_sun(jd)), 0.02)

    def test_angles_on_the_equator(self):
        for _ in range(20):
            asc, mc = A.angles(moment_from_jd(J2000_JD + RNG.uniform(-3000, 3000)), 0.0, 0.0)
            self.assertTrue(60 <= (asc - mc) % 360 <= 120)


class Pair(unittest.TestCase):
    def test_family_expectation(self):
        p, lam = P.family_expected(12, 1.0)
        self.assertAlmostEqual(p, 8 / 360); self.assertAlmostEqual(lam, 12 * 8 / 360)

    def test_family_count_synthetic(self):
        a = {'Sun': 30.0, 'Moon': 100.0, 'Venus': 200.0, 'Mars': 300.0, 'ASC': 50.0, 'DSC': 230.0}
        b = {'Venus': 280.5, 'Mars': 200.8}       # Venus ☍ Moon 0.5° · Mars ☌ Venus 0.8°
        hits = P.attraction_family(b, a)
        self.assertEqual(sorted((f, ang, t) for f, ang, t, o in hits), [('Mars', 0, 'Venus'), ('Venus', 180, 'Moon')])

    def test_midpoint_wraps(self):
        self.assertAlmostEqual(P.midpoint(350, 10), 0.0); self.assertAlmostEqual(P.midpoint(10, 350), 0.0)

    def test_binomial(self):
        self.assertAlmostEqual(P.binomial_tail(2, 7, 1 / 3), 1 - (2 / 3) ** 7 - 7 * (1 / 3) * (2 / 3) ** 6)

    def test_null_pvalue(self):
        below, p = P.null_percentile(5, [1, 2, 3, 4, 5, 6])
        self.assertAlmostEqual(below, 4 / 6); self.assertAlmostEqual(p, (1 + 2) / 7)


if __name__ == '__main__':
    unittest.main()
