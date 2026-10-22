"""Tests for the v2 additions to the core modules (rounding, the stem-bonus table, weighted set members, sub-scores, the
hour pillar, the love overlay, the equation of time). Like test_pure_math: no dates are written here — the equation of
time is checked against an independent formula at random Julian Dates. Run: python3 -m unittest test_v2_core -v"""
import math
import random
import unittest
import astro_core as A
import bazi_core as Z
import radar_core as R
from test_pure_math import moment_from_jd, J2000_JD

RNG = random.Random(21)


def meeus_eot(jd):
    """Meeus' equation of time (Astronomical Algorithms, ch. 28, low precision), minutes — an independent formula."""
    T = (jd - J2000_JD) / 36525.0
    L0 = math.radians((280.46646 + 36000.76983 * T) % 360); M = math.radians(357.52911 + 35999.05029 * T)
    e = 0.016708634 - 0.000042037 * T; eps = math.radians(23.439291 - 0.0130042 * T); y = math.tan(eps / 2) ** 2
    E = (y * math.sin(2 * L0) - 2 * e * math.sin(M) + 4 * e * y * math.sin(M) * math.cos(2 * L0)
         - 0.5 * y * y * math.sin(4 * L0) - 1.25 * e * e * math.sin(2 * M))
    return math.degrees(E) * 4.0


class Rounding(unittest.TestCase):
    def test_half_up_where_python_rounds_to_even(self):
        self.assertEqual(round(24.5), 24); self.assertEqual(Z.round_half_up(24.5), 25)
        self.assertEqual(round(0.25, 1), 0.2); self.assertEqual(Z.round_half_up(0.25, 1), 0.3)
        self.assertEqual(round(2.675, 2), 2.67); self.assertEqual(Z.round_half_up(2.675, 2), 2.68)
        self.assertEqual(Z.round_half_up(1.849, 1), 1.8); self.assertEqual(Z.round_half_up(7, 0), 7)

    def test_rescale_half_up_and_unchanged_on_integers(self):
        self.assertEqual(Z.rescale(67.5), 37)                 # (7.5 · 2.2) + 20 = 36.5 → 37 (round() would give 36)
        for raw in range(0, 200):                               # an integer S never lands on a half: v1 values unchanged
            self.assertEqual(Z.rescale(raw), max(5, min(100, round((raw - 60) * 2.2 + 20))), raw)


class StemBonus(unittest.TestCase):
    def test_table_values_and_kinds(self):
        self.assertEqual({k: v for k, v in Z.STEM_BONUS.items()},
                         {"combine": (10, "bond"), "七殺": (10, "friction"), "傷官": (5, "friction"),
                          "偏印": (5, "bond"), "正印": (5, "bond")})
        for dm in Z.STEMS:                                      # the combine partner is never also 七殺/傷官/印
            self.assertIn(Z.ten_god(dm, Z.combine_partner(dm)), ("正財", "正官"))


class WeightedMembers(unittest.TestCase):
    def test_plain_and_weighted_members(self):
        raw1, _, p1 = Z.day_score("己", "巳", ["巳", "酉", "巳"], ["申"], "甲", "巳")
        raw2, _, p2 = Z.day_score("己", "巳", ["巳", "酉", ("巳", 0.5, "luck ×0.5")], ["申"], "甲", "巳")
        self.assertEqual(raw1 - raw2, 3.0)                      # the repeated 巳巳 same (6) at half weight
        self.assertIn(("巳巳same (own, luck ×0.5)", 3.0), p2)
        h1, _ = Z.hour_score("申", "子", ["巳", "巳"], [], "子")
        h2, _ = Z.hour_score("申", "子", ["巳", ("巳", 0.5, "luck ×0.5")], [], "子")
        self.assertEqual(h1 - h2, 12.5)                         # 合 10 + 刑 15, halved

    def test_sub_scores_add_up_for_every_day_pillar(self):
        for _ in range(400):
            g = RNG.randrange(60); dm = RNG.choice(Z.STEMS); yb = RNG.choice(Z.BRANCHES)
            own = RNG.sample(Z.BRANCHES, RNG.randrange(1, 5)); other = RNG.sample(Z.BRANCHES, RNG.randrange(1, 5))
            if RNG.random() < 0.5: own.append((RNG.choice(Z.BRANCHES), 0.5, "luck ×0.5"))
            att, stp = RNG.choice((0, 5, 10, 12)), RNG.choice((0, 8, 10))
            raw, _, parts = Z.day_score(Z.STEMS[g % 10], Z.BRANCHES[g % 12], own, other, dm, yb, att, stp)
            s = Z.sub_scores(parts, dm)
            self.assertAlmostEqual(s["friction"] + s["bond"] + s["attraction_points"], raw - 35 - stp)
            self.assertEqual(s["attraction_points"], att)

    def test_unknown_part_fails_closed(self):
        with self.assertRaises(ValueError): Z.sub_scores([("子丑zzz (own)", 3)], "甲")


class HourPillar(unittest.TestCase):
    def test_five_rats(self):                                   # 五鼠遁: 甲己 → 甲子, 乙庚 → 丙子, 丙辛 → 戊子, 丁壬 → 庚子, 戊癸 → 壬子
        for day, zi in zip("甲乙丙丁戊己庚辛壬癸", "甲丙戊庚壬甲丙戊庚壬"):
            self.assertEqual(Z.hour_pillar(day, "子"), zi + "子")
        self.assertEqual(Z.hour_pillar("甲", "卯"), "丁卯")


class Sky(unittest.TestCase):
    def test_equation_of_time_agrees_with_meeus(self):
        for _ in range(60):
            jd = J2000_JD + RNG.uniform(-20000, 20000)
            self.assertLess(abs(A.equation_of_time(moment_from_jd(jd)) - meeus_eot(jd)), 0.1)   # minutes

    def test_love_overlay_picks_venus_mars_only(self):
        H = [dict(body="Venus", point="Mars"), dict(body="Mars", point="Venus"), dict(body="Venus", point="Venus"),
             dict(body="Mars", point="Sun"), dict(body="Sun", point="Mars")]
        self.assertEqual(R.love_overlay(H), H[:2])


if __name__ == '__main__':
    unittest.main()
