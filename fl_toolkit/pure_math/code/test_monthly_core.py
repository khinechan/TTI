"""Tests for the monthly formula. Synthetic inputs only (random firing, a random toy log); no dates.
Run: python3 -m unittest test_monthly_core -v"""
import os
import random
import statistics
import unittest
import monthly_core as M

TABLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tables", "coefficients_v1.5.csv")


def synthetic(rows, seed=3, share=0.15):
    rng = random.Random(seed)
    x = [[(rng.random() if rng.random() < share else 0.0) for _ in range(M.REF_MONTHS)] for _ in rows]
    log = list(range(240, 480))
    size = {a: {t: rng.choice((1, 2, 3)) for t in log if rng.random() < 0.03} for a in M.AREAS}
    return x, size, log


class Table(unittest.TestCase):
    def test_loads(self):
        rows = M.load_table(TABLE)
        self.assertEqual(len(rows), 345)
        count = {f: sum(1 for r in rows if r["family"] == f) for f in M.FAMILIES}
        self.assertEqual(count, {"western_transits": 50, "secondary_progressions": 10, "annual_profections": 20,
                                 "vedic_dasha": 20, "bazi": 57, "zi_wei": 102, "mahabote": 14, "numbers": 22,
                                 "western_aspects": 50})
        self.assertEqual(len(M.rows_for_sex(rows, "M")), 340); self.assertEqual(len(M.rows_for_sex(rows, "F")), 340)

    def test_aspect_index_covers_every_combo_once(self):
        idx = M.aspect_index(M.load_table(TABLE))
        self.assertEqual(len(idx), 5 * 5 * 9)


class Layer2(unittest.TestCase):
    def test_u_known_values(self):
        self.assertAlmostEqual(M.u_of(24, 10, 456, 60), 1.00, places=2)
        self.assertAlmostEqual(M.u_of(6, 0, 474, 70), -0.35, places=2)

    def test_weight_bounds(self):
        rows = M.rows_for_sex(M.load_table(TABLE), "M"); x, size, log = synthetic(rows)
        w = M.layer2_weights(rows, x, size, log, 500)
        ratios = [wi / r["w0"] for wi, r in zip(w, rows)]
        self.assertGreaterEqual(min(ratios), 0.5 - 1e-12); self.assertLessEqual(max(ratios), 1.5 + 1e-12)

    def test_fits_only_on_the_past(self):
        rows = M.rows_for_sex(M.load_table(TABLE), "M"); x, size, log = synthetic(rows)
        a = M.layer2_weights(rows, x, size, log, 300)
        size2 = {k: dict(v) for k, v in size.items()}; size2["career"][300] = 3      # an event AT t changes nothing
        self.assertEqual(a, M.layer2_weights(rows, x, size2, log, 300))


class Layer1(unittest.TestCase):
    def test_each_family_scaled_to_sd_one(self):
        rows = M.rows_for_sex(M.load_table(TABLE), "M"); x, size, log = synthetic(rows)
        T = M.Table(rows, x, size, log, 500)
        for f in range(len(M.FAMILIES)):
            vals = [(T.p[f][a][k] + T.n[f][a][k]) / T.sd[f] for a in range(len(M.AREAS)) for k in range(M.REF_MONTHS)]
            if T.sd[f] != 1.0: self.assertAlmostEqual(statistics.pstdev(vals), 1.0, places=9)

    def test_every_area_month_gets_a_line_and_voices_add_to_nine(self):
        rows = M.rows_for_sex(M.load_table(TABLE), "M"); x, size, log = synthetic(rows)
        out = M.month_reading(rows, x, size, log, 600)
        for a, r in out.items():
            self.assertIn(r["step"], range(5)); self.assertEqual(sum(r["voices"]), 9)


class MasterLine(unittest.TestCase):
    def test_fire_steps(self):
        self.assertEqual([M.fire_step(p) for p in (0.2, 0.25, 0.3, 0.5, 0.6, 0.75, 0.8, 0.9, 0.95)],
                         [0, 0, 1, 1, 2, 2, 3, 3, 4])

    def test_flavor_cuts(self):
        self.assertEqual(M.flavor_of(2, 1), "support"); self.assertEqual(M.flavor_of(1, 2), "pressure")
        self.assertEqual(M.flavor_of(1, 1), "mixed"); self.assertIsNone(M.flavor_of(0, 0))

    def test_midrank(self):
        self.assertAlmostEqual(M.percentile_midrank(2, [1, 2, 2, 3]), (1 + 0.5 * 2) / 4)


class Aspects(unittest.TestCase):
    def test_orb_rules(self):
        idx = {("Saturn", "□", "Sun"): "R1"}
        natal = {"Sun": 100.0}
        self.assertEqual(M.fire_aspects(idx, natal, {"Saturn": (190.5, 0.05)}), {"R1": 1.0})     # 0.5° → full
        self.assertEqual(M.fire_aspects(idx, natal, {"Saturn": (192.0, -0.05)}), {"R1": 0.5})    # 2° closing → ½
        self.assertEqual(M.fire_aspects(idx, natal, {"Saturn": (192.0, 0.05)}), {})              # 2° opening → 0
        self.assertEqual(M.fire_aspects(idx, natal, {"Saturn": (194.0, -0.05)}), {})             # past 3° → 0


class Honesty(unittest.TestCase):
    def test_verdict_table(self):
        self.assertEqual(M.verdict(0.01, 0.01, 0.1, None, 0.01), "✅")
        self.assertEqual(M.verdict(0.04, 0.06, 0.1, 0.80, 0.01), "❌")
        self.assertEqual(M.verdict(0.04, 0.06, 0.1, 0.79, 0.01), "⬜")
        self.assertEqual(M.verdict(0.01, 0.01, -0.1, None, 0.01), "⬜")

    def test_power_bound(self):                      # 100 synthetic logs: ≥ 0.80 needs 87 wins
        self.assertGreaterEqual(M.power_lower_bound(87, 100), 0.80)
        self.assertLess(M.power_lower_bound(86, 100), 0.80)

    def test_p_value_and_brier(self):
        self.assertAlmostEqual(M.p_value(5, [1, 5, 6, 2]), 3 / 5)
        self.assertAlmostEqual(M.brier_skill([(0.9, 1, 0.5), (0.1, 0, 0.5)]), 1 - 0.02 / 0.5)


if __name__ == '__main__':
    unittest.main()
