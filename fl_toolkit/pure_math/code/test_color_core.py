"""Tests for color_core (§13 outfit color, STD story mechanic). No dates anywhere: the charts are their pillars,
the raw §7 scores of the brief's worked examples are passed in as plain numbers, and the pull math runs on
synthetic sample arrays. Run: python3 -m unittest test_color_core -v"""
import itertools
import random
import unittest
from fractions import Fraction
from unittest import mock
import bazi_core as Z
import color_core as C
import strength_core as S

F_A = S.chart_strength(["庚申", "甲申", "壬申", None])["F"]      # A: day master 壬 (water), strong
F_B = S.chart_strength(["己巳", "癸酉", "甲戌", "丁卯"])["F"]    # B: day master 甲 (wood), weak
VENUS_A, VENUS_B, DM_A, DM_B = "Cancer", "Libra", "water", "wood"
BLOCK_OF = [Z.BRANCHES[i // 12] for i in range(144)]          # a BaZi day: 子 = samples 0–11, then 12 per block
RNG = random.Random(13)


def outfit(*pairs):
    return [{"slot": s, "color": c} for s, c in pairs]


def V_of(E, F, T):
    return C.viewer_effect(E, F, T, [1.0] * 144, [1.0] * 144, BLOCK_OF, 1.0)["V"]


class Table(unittest.TestCase):
    def test_rows_sum_to_one(self):
        self.assertEqual(len(C.COLORS), 37)
        for c, w in C.COLORS.items():
            self.assertAlmostEqual(sum(w.values()), 1.0, places=12, msg=c)
            self.assertTrue(set(w) <= set(Z.ELEMENTS), c); self.assertEqual(C.norm_color(c), c)
        self.assertAlmostEqual(sum(C.SLOT_W.values()), 1.05, places=12)

    def test_E_sums_to_one_for_every_slot_subset(self):
        tokens = sorted(C.COLORS); n = 0
        for r in range(1, 6):
            for slots in itertools.combinations(C.SLOT_W, r):
                for off in range(len(tokens)):
                    E = C.outfit_vector(outfit(*[(s, tokens[(off + 7 * i) % len(tokens)]) for i, s in enumerate(slots)]))
                    self.assertEqual(list(E), Z.ELEMENTS); self.assertAlmostEqual(sum(E.values()), 1.0, places=12); n += 1
        self.assertEqual(n, 31 * 37)

    def test_slots_may_repeat(self):
        E = C.outfit_vector(outfit(("accessory", "gold"), ("accessory", "black"), ("top", "red")))
        self.assertAlmostEqual(E["metal"], 0.05 / 0.65, places=12); self.assertAlmostEqual(E["water"], 0.05 / 0.65, places=12)
        self.assertAlmostEqual(E["fire"], 0.55 / 0.65, places=12)

    def test_unknown_color_lists_every_token(self):
        with self.assertRaises(ValueError) as cm: C.outfit_vector(outfit(("top", "chartreuse")))
        msg = str(cm.exception)
        self.assertIn("chartreuse", msg); self.assertIn(", ".join(sorted(C.COLORS)), msg)
        for bad in ("orange red", "gray", "", None):
            with self.assertRaises(ValueError): C.outfit_vector(outfit(("top", bad)))

    def test_unknown_slot_and_empty_outfit(self):
        with self.assertRaises(ValueError) as cm: C.outfit_vector(outfit(("hat", "red")))
        for s in C.SLOT_W: self.assertIn(s, str(cm.exception))
        with self.assertRaises(ValueError): C.outfit_vector([])
        with self.assertRaises(ValueError): C.taste([], VENUS_A)

    def test_normalization(self):
        self.assertEqual(C.outfit_vector(outfit(("top", "  Forest \t GREEN "))), C.outfit_vector(outfit(("top", "forest green"))))
        self.assertEqual(C.outfit_vector(outfit(("top", "Orange-Red")))["fire"], 1.0)

    def test_palettes(self):
        self.assertEqual(len(C.VENUS_PALETTE), 12)
        for sign, pal in C.VENUS_PALETTE.items():
            self.assertTrue(set(pal) <= set(C.COLORS), sign)
        for ab, full in C.SIGN_FULL.items(): self.assertEqual(full[:3], ab)
        o = outfit(("top", "pink"), ("bottom", "navy"))
        self.assertEqual(C.taste(o, "Lib"), C.taste(o, "Libra")); self.assertAlmostEqual(C.taste(o, "Libra"), 0.55 / 0.85, places=12)
        self.assertEqual(C.taste(o, "Aries"), 0.0)
        with self.assertRaises(ValueError): C.taste(o, "Ophiuchus")

    def test_reexports(self):
        for name in ("element_totals", "strength", "favorability"): self.assertIs(getattr(C, name), getattr(S, name))
        for name in ("outfit_vector", "wearer_effect", "viewer_effect", "role_tag"): self.assertTrue(callable(getattr(C, name)))


class WorkedExamples(unittest.TestCase):
    """The brief's §5 examples 2–5, the date-free parts (raw §7 scores passed in)."""

    def r4(self, d):
        return {e: round(v, 4) for e, v in d.items() if round(v, 4)}

    def test_ex2_green_top_silver_bottom(self):
        o = outfit(("top", "green"), ("bottom", "silver")); E = C.outfit_vector(o)
        self.assertEqual(self.r4(E), {"wood": 0.6471, "metal": 0.3529})
        w = C.wearer_effect(E, F_B, 77)
        self.assertEqual(round(w["W"], 4), 0.2941); self.assertEqual(round(w["raw_after"], 3), 74.059)
        self.assertEqual((w["charge_before"], w["charge_after"], w["tier_after"]), (57, 51, "🟡"))
        T = C.taste(o, VENUS_A); self.assertEqual(round(T, 4), 0.3529)
        self.assertEqual(round(V_of(E, F_A, T), 4), 0.3118)
        self.assertEqual(C.role_tag(E, DM_A), ("output", "play, enjoyment")); self.assertEqual(C.role_tag(E, DM_B)[0], "peer")

    def test_ex3_dark_brown_with_red_peek(self):
        o = outfit(("top", "dark brown"), ("bottom", "dark brown"), ("peek", "red")); E = C.outfit_vector(o)
        self.assertEqual(self.r4(E), {"earth": 0.8947, "fire": 0.1053})
        w = C.wearer_effect(E, F_B, 65)
        self.assertEqual(round(w["W"], 4), -0.9474); self.assertEqual(round(w["raw_after"], 3), 74.474)
        self.assertEqual((w["charge_before"], w["charge_after"], w["tier_after"]), (31, 52, "🟡"))
        self.assertEqual(round(V_of(E, F_A, C.taste(o, VENUS_A)), 4), 0.70)
        self.assertEqual(C.role_tag(E, DM_A)[0], "officer"); self.assertEqual(C.role_tag(E, DM_B)[0], "wealth")

    def test_ex4_forest_green(self):
        o = outfit(("top", "forest green"), ("bottom", "forest green")); E = C.outfit_vector(o)
        w = C.wearer_effect(E, F_B, 84)
        self.assertEqual(round(w["W"], 4), 1.0); self.assertEqual(round(w["raw_after"], 3), 74.0)
        self.assertEqual((w["charge_before"], w["charge_after"], w["tier_after"]), (73, 51, "🟡"))
        self.assertEqual(round(V_of(E, F_A, C.taste(o, VENUS_A)), 4), 0.70)
        self.assertEqual(C.role_tag(E, DM_A)[0], "output")

    def test_ex5_silver_control(self):
        o = outfit(("top", "silver"), ("bottom", "silver")); E = C.outfit_vector(o)
        w = C.wearer_effect(E, F_B, 84)
        self.assertEqual(round(w["W"], 4), -1.0)
        self.assertEqual((w["charge_before"], w["charge_after"], w["tier_after"]), (73, 95, "🔴"))
        self.assertEqual(round(V_of(E, F_A, C.taste(o, VENUS_A)), 4), -0.40)
        self.assertEqual(C.role_tag(E, DM_A)[0], "resource"); self.assertEqual(C.role_tag(E, DM_B)[0], "officer")

    def test_wearer_uses_bazi_rescale_and_tier(self):
        E = C.outfit_vector(outfit(("top", "green")))
        with mock.patch.object(Z, "rescale", side_effect=lambda r: 42), mock.patch.object(Z, "tier", side_effect=lambda s: "T"):
            w = C.wearer_effect(E, F_B, 77)
        self.assertEqual((w["charge_before"], w["charge_after"], w["tier_before"], w["tier_after"]), (42, 42, "T", "T"))
        self.assertEqual(C.wearer_effect(E, F_B, 77, dict(C.COLOR_PARAMS, K_SELF=5.0))["raw_after"], 72.0)

    def test_role_tie_break(self):
        self.assertEqual(C.role_tag(C.outfit_vector(outfit(("top", "olive"))), "water")[0], "output")    # wood = earth → wood
        self.assertEqual(C.role_tag(C.outfit_vector(outfit(("top", "cream"))), "water")[0], "officer")   # earth = metal → earth

    def test_role_tie_survives_float_noise(self):
        # wood = metal = 0.33/0.95 exactly, but the float sums put metal 1 ulp ahead: the tie rule must still pick wood
        o = outfit(("top", "charcoal"), ("bottom", "green"), ("peek", "olive brown"))
        self.assertEqual(C.role_tag(C.outfit_vector(o), "water")[0], "output")
        W = {k: {e: Fraction(repr(v)) for e, v in w.items()} for k, w in C.COLORS.items()}
        c = {s: Fraction(repr(v)) for s, v in C.SLOT_W.items()}
        for t, b, p in itertools.product(sorted(C.COLORS), repeat=3):     # every top/bottom/peek outfit, exact arithmetic
            ex = {e: c["top"] * W[t].get(e, 0) + c["bottom"] * W[b].get(e, 0) + c["peek"] * W[p].get(e, 0) for e in Z.ELEMENTS}
            dom = next(e for e in Z.ELEMENTS if ex[e] == max(ex.values()))
            got = C.role_tag(C.outfit_vector(outfit(("top", t), ("bottom", b), ("peek", p))), "water")[0]
            self.assertEqual(got, S.family("water", dom), (t, b, p))


class Viewer(unittest.TestCase):
    """viewer_effect on synthetic days."""
    E = C.outfit_vector(outfit(("top", "forest green")))     # with F_A: V = 0.7, m = 1.175

    def day(self, scale=1.0):
        return [scale * RNG.random() for _ in range(144)], [1.0] * 144

    def test_multiplier_touches_only_seen_blocks(self):
        s, w = self.day(); seen = C.COLOR_PARAMS["SEEN"]
        r = C.viewer_effect(self.E, F_A, 0.0, s, w, BLOCK_OF, 2.0)
        m = r["multiplier"]; self.assertAlmostEqual(m, 1 + 0.25 * 0.7, places=12)
        inside = sum(x for x, b in zip(s, BLOCK_OF) if b in seen); outside = sum(x for x, b in zip(s, BLOCK_OF) if b not in seen)
        self.assertAlmostEqual(r["day_pull_before"], (inside + outside) / 144 / 2.0 * 10, places=12)
        self.assertAlmostEqual(r["day_pull_after"], (m * inside + outside) / 144 / 2.0 * 10, places=12)
        self.assertEqual(list(r["blocks"]), [b for b in Z.BRANCHES if b in seen])
        none = C.viewer_effect(self.E, F_A, 0.0, s, w, BLOCK_OF, 2.0, seen="")
        self.assertEqual((none["blocks"], none["day_pull_after"]), ({}, none["day_pull_before"]))
        flat = C.viewer_effect(C.outfit_vector(outfit(("top", "cream"))), {e: 0.0 for e in Z.ELEMENTS}, 0.0, s, w, BLOCK_OF, 2.0)
        self.assertEqual((flat["V"], flat["multiplier"]), (0.0, 1.0)); self.assertEqual(flat["day_pull_after"], flat["day_pull_before"])

    def test_cap_at_ten(self):
        s, w = [5.0] * 144, [1.0] * 144
        r = C.viewer_effect(self.E, F_A, 0.0, s, w, BLOCK_OF, 1.0, seen=Z.BRANCHES)
        self.assertAlmostEqual(r["day_pull_before"], 50.0, places=12)    # before is today's value: not capped
        self.assertEqual(r["day_pull_after"], 10.0)
        self.assertTrue(all(a == 10.0 and b > 10.0 for b, a in r["blocks"].values()))
        hi = dict(C.COLOR_PARAMS, PULL_CAP=100.0)
        self.assertAlmostEqual(C.viewer_effect(self.E, F_A, 0.0, s, w, BLOCK_OF, 1.0, seen=Z.BRANCHES, params=hi)["day_pull_after"],
                               50.0 * 1.175, places=9)

    def test_half_weight_pair_equals_one_sample_of_their_mean(self):
        s, w = self.day()
        one = C.viewer_effect(self.E, F_A, 0.3, s, w, BLOCK_OF, 1.5)
        j = 60                                                     # a 巳 sample (seen)
        a, b = s[j] - 0.2, s[j] + 0.2
        s2, w2, bo2 = s[:j] + [a, b] + s[j + 1:], w[:j] + [0.5, 0.5] + w[j + 1:], BLOCK_OF[:j] + [BLOCK_OF[j]] * 2 + BLOCK_OF[j + 1:]
        two = C.viewer_effect(self.E, F_A, 0.3, s2, w2, bo2, 1.5)
        for k in ("V", "multiplier", "day_pull_before", "day_pull_after"): self.assertAlmostEqual(one[k], two[k], places=12)
        for br in one["blocks"]:
            for x, y in zip(one["blocks"][br], two["blocks"][br]): self.assertAlmostEqual(x, y, places=12)
        dup = C.viewer_effect(self.E, F_A, 0.3, s[:j] + [s[j], s[j]] + s[j + 1:], w2, bo2, 1.5)   # a doubled sample at ½ weight
        self.assertAlmostEqual(dup["day_pull_before"], one["day_pull_before"], places=12)

    def test_zero_pull_stays_zero(self):
        for E, F, T in ((self.E, F_A, 1.0), (C.outfit_vector(outfit(("top", "silver"))), F_A, 0.0)):
            r = C.viewer_effect(E, F, T, [0.0] * 144, [1.0] * 144, BLOCK_OF, 3.0)
            self.assertEqual((r["day_pull_before"], r["day_pull_after"]), (0.0, 0.0))
            self.assertTrue(all(v == (0.0, 0.0) for v in r["blocks"].values()))

    def test_blocks_after_is_min_ten_before_times_m(self):
        for _ in range(50):
            s, w = self.day(scale=RNG.choice((0.5, 3.0, 9.0))); w = [RNG.choice((0.5, 1.0)) for _ in w]
            seen = "".join(b for b in Z.BRANCHES if RNG.random() < 0.5)
            E = C.outfit_vector(outfit(("top", RNG.choice(sorted(C.COLORS))), ("bottom", RNG.choice(sorted(C.COLORS)))))
            r = C.viewer_effect(E, F_A, RNG.random(), s, w, BLOCK_OF, 1.0, seen=seen)
            self.assertEqual(list(r["blocks"]), [b for b in Z.BRANCHES if b in seen])
            for br, (before, after) in r["blocks"].items():
                idx = [i for i, b in enumerate(BLOCK_OF) if b == br]
                self.assertAlmostEqual(before, sum(w[i] * s[i] for i in idx) / sum(w[i] for i in idx) * 10, places=9)
                self.assertEqual(after, min(10.0, before * r["multiplier"]))

    def test_empty_block_omitted_and_bad_input_refused(self):
        bo = [b if b != "辰" else "卯" for b in BLOCK_OF]
        r = C.viewer_effect(self.E, F_A, 0.0, [1.0] * 144, [1.0] * 144, bo, 1.0)
        self.assertEqual(list(r["blocks"]), list("巳午未申"))
        for args in (([1.0] * 143, [1.0] * 144, BLOCK_OF), ([1.0] * 144, [1.0] * 144, ["X"] * 144),
                     ([1.0] * 144, [-1.0] * 144, BLOCK_OF), ([], [], [])):
            with self.assertRaises(ValueError): C.viewer_effect(self.E, F_A, 0.0, *args, 1.0)
        with self.assertRaises(ValueError): C.viewer_effect(self.E, F_A, 0.0, [1.0] * 144, [1.0] * 144, BLOCK_OF, 1.0, seen="辰,巳")
        with self.assertRaises(ValueError): C.viewer_effect(self.E, F_A, 0.0, [1.0] * 144, [1.0] * 144, BLOCK_OF, 0.0)

    def test_branch_check_is_per_character(self):
        # a branch is ONE character: '辰巳…' or '' must not pass as a substring of 子丑…亥 and then silently match nothing
        for seen in (["辰巳午未申"], ["辰", ""]):
            with self.assertRaises(ValueError): C.viewer_effect(self.E, F_A, 0.0, [1.0] * 144, [1.0] * 144, BLOCK_OF, 1.0, seen=seen)
        for tail in ("", "子丑", None):
            with self.assertRaises(ValueError): C.viewer_effect(self.E, F_A, 0.0, [1.0] * 144, [1.0] * 144, BLOCK_OF[:-1] + [tail], 1.0)


if __name__ == "__main__":
    unittest.main()
