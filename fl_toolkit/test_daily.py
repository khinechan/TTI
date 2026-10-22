"""Tests for daily.py v2: the audit's P1 fixes, P2/P3 keys, the options, time-free A, and the golden days.
These tests use dates (the pure_math tests do not). Run from this folder: python3 -m unittest test_daily -v
The goldens in goldens/ are tied to the ephem build that wrote them (4.2.1); see CHANGES.md."""
import copy
import datetime as dt
import json
import os
import random
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import daily as D

GOLDEN_DAYS = ("2026-09-08", "2026-10-20", "2026-10-21", "2026-11-01", "2027-03-14")
NOON = dict(D.DEFAULT_OPT, a_time="noon")
TF = dict(D.DEFAULT_OPT, a_time="tf")
V1_TOP_A = 3.276370515630749          # the v1 ref_2026-10-20.json (calendar-day sampling), verbatim
_RUNS = {}


def run(day, **opt):
    """D.main through a JSON round trip (as printed), memoised so each (day, options) runs once."""
    key = (day, tuple(sorted(opt.items())))
    if key not in _RUNS: _RUNS[key] = json.loads(json.dumps(D.main(dt.date.fromisoformat(day), dict(D.DEFAULT_OPT, **opt)), ensure_ascii=False))
    return _RUNS[key]


def jload(path):
    with open(path, encoding="utf-8") as fh: return json.load(fh)


def golden_path(day, a_time):
    return os.path.join(HERE, "goldens", "golden_%s%s.json" % (day, "" if a_time == D.DEFAULT_OPT["a_time"] else "_" + a_time))


class Goldens(unittest.TestCase):
    """P4 item 17: the five book days, default output and the noon comparison, byte for byte."""

    def test_golden_days(self):
        for day in GOLDEN_DAYS:
            for at in ("tf", "noon"):
                with self.subTest(day=day, a_time=at):
                    self.assertEqual(run(day, a_time=at), jload(golden_path(day, at)))

    def test_cli_prints_the_golden(self):
        import subprocess
        out = subprocess.run([sys.executable, os.path.join(HERE, "daily.py"), "2026-10-21"], capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(out), jload(golden_path("2026-10-21", D.DEFAULT_OPT["a_time"])))
        self.assertNotIn("outfit", json.loads(out))          # §13: no outfit, no key


class P1Fixes(unittest.TestCase):
    def test_bazi_day_grid(self):                           # item 1: 23:00 the evening before … 22:50, 子 = 12 samples
        g = D.wall_grid(dt.date(2026, 10, 21))
        self.assertEqual(len(g), 144)
        self.assertEqual(g[0][0].astimezone(D.NY).strftime("%m-%d %H:%M"), "10-20 23:00")
        self.assertEqual(g[-1][0].astimezone(D.NY).strftime("%m-%d %H:%M"), "10-21 22:50")
        self.assertEqual([D.block_of(k) for k in (0, 11, 12, 23, 132, 143)], [0, 0, 1, 1, 11, 11])

    def test_zi_block_is_fully_sampled(self):               # item 1: A's 子 block on 2026-10-21 = 1.1 (1.08 on the v1 top)
        day = dt.date(2026, 10, 21)
        zi = D.wmean(D.samples(day, "A", a_time="noon"), keep=lambda k: D.block_of(k) == 0)
        self.assertAlmostEqual(zi / V1_TOP_A * 10, 1.08, places=2)
        self.assertEqual(run("2026-10-21", a_time="noon")["A"]["hours"][0]["pull"], 1.1)

    def test_saturn_station_reaches_A_with_C(self):         # item 2: 2027-08-09 A has +8; A with C now has it too
        r = run("2027-08-09", a_time="noon")
        self.assertIn(["Saturn station", 8], r["A"]["parts"]); self.assertIn(["Saturn station", 8], r["A_with_C"]["parts"])

    def test_chemistry_cap(self):                           # item 3: 2026-09-08 → 10.0, raw 5.29, flag true
        c = run("2026-09-08", a_time="noon")["chemistry"]
        self.assertEqual((c["scale"], c["raw"], c["above_window_max"]), (10.0, 5.29, True))
        self.assertFalse(run("2026-10-21", a_time="noon")["chemistry"]["above_window_max"])

    def test_chemistry_at_local_noon(self):                 # item 4: 17:00 UTC in EST, 16:00 UTC in EDT
        for day, hour in (("2026-11-01", 17), ("2026-10-21", 16)):
            d = dt.date.fromisoformat(day)
            want = D.P.pair_score(D.spots, dt.datetime(d.year, d.month, d.day, hour, tzinfo=D.UTC))[0]
            self.assertEqual(run(day, a_time="noon")["chemistry"]["raw"], D.rhu(want, 2))
            dm = run(day, a_time="noon")["chemistry"]["day_max"]
            self.assertGreaterEqual(dm["raw"], run(day, a_time="noon")["chemistry"]["raw"])   # noon is one of the 24 instants

    def test_dst_days(self):                                # item 5: fall back doubles 01:00–01:50 at ½; spring forward skips 02:00–02:50
        s = run("2026-11-01")["sampling"]
        self.assertEqual((s["instants"], s["effective"], s["repeated"], s["skipped"]), (150, 144.0, 6, 0))
        s = run("2027-03-14")["sampling"]
        # The audit asked for "144 effective samples" here too; a 23-hour day has 138 under its own skip rule (CHANGES.md).
        self.assertEqual((s["instants"], s["effective"], s["repeated"], s["skipped"]), (138, 138.0, 0, 6))
        g = D.wall_grid(dt.date(2026, 11, 1)); halves = [u for u, w, k in g if w == 0.5]
        self.assertEqual(len(halves), 12); self.assertEqual((halves[1] - halves[0]).total_seconds(), 3600)
        g = D.wall_grid(dt.date(2027, 3, 14)); self.assertEqual(len({u for u, _, _ in g}), 138)

    def test_round_half_up_in_scales(self):                 # item 6
        self.assertEqual(D.rhu(0.25, 1), 0.3); self.assertEqual(D.rhu(24.5), 25)


class P2Calibration(unittest.TestCase):
    def test_percentile_keys(self):                         # item 7
        r = run("2026-10-21")
        for k in ("A", "B", "A_with_C"):
            self.assertTrue(0 <= r[k]["charge_pct"] <= 1); self.assertEqual(r[k]["tier_pct"], D.tier_pct(r[k]["charge_pct"]))
        self.assertEqual([D.tier_pct(p) for p in (0.9, 0.8999, 0.75, 0.7499, 0.5, 0.4999)], ["🔴", "🟠", "🟠", "🟡", "🟡", "🟢"])

    def test_saturation_counts(self):                       # item 7: v1 audit counted A 49/75, B 50/32 (this ephem: A 49/76)
        start = dt.date(2026, 10, 20); out = {}
        for at, opt in (("noon", NOON), ("tf", TF)):
            ref = D.reference(start, at)
            for who, oth in (("A", "B"), ("B", "A")):
                sc = [D.day_charge(start + dt.timedelta(days=i), who, oth, *D.flag_scale(ref[who]["mean"][i], ref[who]),
                                   ref[who]["station"][i], opt)[1] for i in range(365)]
                out[(at, who)] = (sc.count(100), sc.count(5))
        self.assertEqual(out, {("noon", "A"): (49, 76), ("noon", "B"): (50, 32), ("tf", "A"): (50, 72), ("tf", "B"): (50, 32)})

    def test_hour_points(self):                             # item 8
        for h in run("2026-10-21")["A"]["hours"]:
            self.assertEqual(h["points"], h["charge"]); self.assertTrue(0 <= h["points_pct"] <= 1)

    def test_caches_rebuild_to_the_same_numbers(self):      # item 9: a deleted cache rebuilds identically (spot check)
        start = dt.date(2026, 10, 20); ref = D.reference(start, "noon")
        for i in (0, 100, 364):
            d = start + dt.timedelta(days=i)
            self.assertEqual(D.wmean(D.samples(d, "A")), ref["A"]["mean"][i])
            self.assertEqual(D.chem(D.noon(d), "noon")[0], ref["chem"][i])

    def test_stale_cache_is_rebuilt(self):                  # item 9: a v1 cache (no "v") is never trusted
        with tempfile.TemporaryDirectory() as tmp:
            old = D.HERE; D.HERE = tmp
            try:
                D._LOADED.pop(os.path.join(tmp, "ref_x.json"), None)
                with open(os.path.join(tmp, "ref_x.json"), "w") as fh: json.dump({"A": {"top": 1}}, fh)
                got = D._cached("ref_x", "noon", lambda: {"v": D.REF_V, "rebuilt": True})
                self.assertTrue(got["rebuilt"]); self.assertTrue(jload(os.path.join(tmp, "ref_x.json"))["rebuilt"])
            finally:
                D.HERE = old

    def test_shipped_caches(self):
        for start in ("2026-10-20", "2027-10-20", "2028-10-19"):
            for suf in ("", "_tf"):
                ref = jload(os.path.join(HERE, "ref_%s%s.json" % (start, suf)))
                self.assertEqual((ref["v"], ref["start"], ref["days"], len(ref["A"]["mean"]), len(ref["chem"])), (D.REF_V, start, 365, 365, 365))
        for suf in ("", "_tf"):
            lr = jload(os.path.join(HERE, "ref_longrun_2020-01-01_2040-12-31%s.json" % suf))
            self.assertEqual((lr["days"], len(lr["pull_A"]), len(lr["pull_B"]), len(lr["chem"])), (7671,) * 4)
        self.assertEqual(D.window_for(dt.date(2028, 10, 19)), dt.date(2028, 10, 19))   # the drift CHANGES.md flags


class P3Meaning(unittest.TestCase):
    def test_sub_scores_sum(self):                          # item 10: friction + bond + attraction = S − 35 − Saturn
        for day in GOLDEN_DAYS + ("2027-08-09",):
            for at in ("tf", "noon"):
                r = run(day, a_time=at)
                for k in ("A", "B", "A_with_C"):
                    st = sum(v for n, v in r[k]["parts"] if n == "Saturn station")
                    raw = sum(v for _, v in r[k]["parts"])
                    self.assertAlmostEqual(r[k]["friction"] + r[k]["bond"] + r[k]["attraction_points"], raw - 35 - st)

    def test_luck_repeat_weight(self):                      # item 11: B on 2026-10-21 / 10-22 at 1.0 and 0.5
        got = {(d, w): (run(d, a_time="noon", luck_w=w)["B"]["raw"], run(d, a_time="noon", luck_w=w)["B"]["charge"])
               for d in ("2026-10-21", "2026-10-22") for w in (1.0, 0.5)}
        self.assertEqual(got, {("2026-10-21", 1.0): (77, 57), ("2026-10-21", 0.5): (77, 57),
                               ("2026-10-22", 1.0): (79, 62), ("2026-10-22", 0.5): (76.0, 55)})
        self.assertIn(["巳巳same (own, luck ×0.5)", 3.0], run("2026-10-22", a_time="noon", luck_w=0.5)["B"]["parts"])
        self.assertNotIn("options", run("2026-10-22"))

    def test_love_overlay(self):                            # item 13: transiting Venus ☌ A's natal Mars, ⚠️ unchanged
        A = run("2026-10-22", a_time="noon")["A"]
        self.assertEqual(A["love_overlay"], ["💗 Venus ☌ Mars 2.65° applying ⚠️"])
        self.assertEqual(run("2026-10-21")["A"]["love_overlay"], [])


class P5Options(unittest.TestCase):
    def test_year_month_terms(self):                        # item 20: 2026 丙午 year, 戌 month on 2026-10-21
        self.assertEqual(D.year_month_branches(dt.date(2026, 10, 21)), ("午", "戌"))
        self.assertEqual(D.year_month_branches(dt.date(2027, 1, 15)), ("午", "丑"))      # before 立春: still 丙午
        self.assertEqual(D.year_month_branches(dt.date(2027, 2, 10)), ("未", "寅"))
        r = run("2026-10-21", a_time="noon", ym=True)
        self.assertIn(["辰戌冲 (other, 流月 ×0.5)", 7.5], r["A"]["parts"])
        self.assertEqual(r["A"]["raw"], run("2026-10-21", a_time="noon")["A"]["raw"] + 7.5)

    def test_solar_time(self):                              # item 21: edges move by clock − solar (EDT: ~54 min on 10-21)
        r = run("2026-10-21", a_time="noon", solar=True)
        self.assertEqual(r["solar_time"]["clock_minus_solar_min"], 54.2)
        self.assertTrue(r["A"]["hours"][0]["hours"].startswith("23:54-01:53"))
        self.assertEqual([h["charge"] for h in r["A"]["hours"]], [h["charge"] for h in run("2026-10-21", a_time="noon")["A"]["hours"]])
        self.assertEqual(r["A"]["pull"], run("2026-10-21", a_time="noon")["A"]["pull"])   # the day pull stays on the clock


class TimeFree(unittest.TestCase):
    def test_exact_mean_of_119_charts(self):
        rng = random.Random(3); tf = D.tf()
        for _ in range(60):
            t = dt.datetime(2026, 10, 20, tzinfo=D.UTC) + dt.timedelta(minutes=rng.randrange(0, 365 * 1440))
            naive = sum(D.moment_A(t, pts=c["pts"]) for c in tf["charts"]) / D.TF_N
            self.assertAlmostEqual(D.moment_A_tf(t), naive, places=12)

    def test_charts(self):
        tf = D.tf(); self.assertEqual(len(tf["charts"]), 119)
        local = [c["t"].astimezone(D.ZoneInfo("America/Indiana/Indianapolis")).strftime("%H:%M") for c in tf["charts"]]
        self.assertEqual((local[0], local[72], local[-1]), ("00:00", "12:00", "19:40"))
        self.assertNotIn("Moon", tf["avg"]); self.assertEqual(tf["charts"][72]["pts"], {k: v for k, v in D.pA.items() if k != "Moon"})

    def test_luck_shares(self):                             # Khai's check values
        n = lambda d: dict(D.lucks("A", dt.date.fromisoformat(d), TF)).get("己卯", 0)
        self.assertEqual([n(d) for d in ("2027-04-06", "2027-04-07", "2027-05-27", "2027-07-16")], [0, 1, 60, 119])
        self.assertLess(n("2027-07-15"), 119)
        r = run("2027-05-12")["A"]
        self.assertEqual(r["luck_shares"], {"庚辰": [77, 0.647], "己卯": [42, 0.353]})
        self.assertEqual((run("2027-05-12", a_time="noon")["A"]["charge"], r["charge"]), (79, 74))

    def test_1021(self):                                    # Khai: A pull 2.1 (noon 1.9 in v1), charge 90, chemistry 2.4
        r = run("2026-10-21")
        self.assertEqual((r["A"]["pull"], r["A"]["charge"], r["chemistry"]["scale"]), (2.1, 90, 2.4))

    def test_B_does_not_depend_on_A_time(self):
        for day in ("2026-10-21", "2027-05-12"):
            self.assertEqual(run(day, a_time="tf")["B"], run(day, a_time="noon")["B"])

    def test_v1_reference_matches_khai(self):              # his vectorised run, v1 conventions: top/fire/ok to 6 dp
        start = dt.date(2026, 10, 20); means = []
        for i in range(365):
            d = start + dt.timedelta(days=i); d0 = D.loc(d.year, d.month, d.day)
            grid = [((d0 + dt.timedelta(minutes=10 * k)).astimezone(D.UTC), 1.0, k) for k in range(144)]
            means.append(D.wmean(D.samples(d, "A", grid, "tf")))
        v = sorted(means, reverse=True)
        self.assertEqual([round(v[0], 6), round(v[25], 6), round(v[72], 6)], [3.214513, 1.881009, 1.284722])


if __name__ == "__main__":
    unittest.main()
