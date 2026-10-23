"""Tests for daily.py v3: the percentile headline, the receipt's percentages, --seasons (on by default, Khai's call) and
the engine key. Run from this folder: python3 -m unittest test_daily_v3 -v
The v3 spec's tests: (a) is test_daily.Goldens (--no-seasons gives every v2.0.1 golden byte for byte); (b) SixtyDayLoop;
(c) Saturation; (d) TimeFreeSplit. GoldensV3 pins the v3 default for the five book days and one split day."""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import daily as D

V3 = dict(D.DEFAULT_OPT)                      # the v3 default: time-free A, seasons on
V2 = dict(D.DEFAULT_OPT, seasons=False)
GOLDEN_DAYS = ("2026-09-08", "2026-10-20", "2026-10-21", "2026-11-01", "2027-03-14", "2027-05-12")
START = dt.date(2026, 10, 20)
_RUNS = {}


def run(day, **opt):
    key = (day, tuple(sorted(opt.items())))
    if key not in _RUNS:
        _RUNS[key] = json.loads(json.dumps(D.main(dt.date.fromisoformat(day), dict(V3, **opt)), ensure_ascii=False))
    return _RUNS[key]


def gpath(day, a_time):
    return os.path.join(HERE, "goldens", "v3", "golden_%s%s.json" % (day, "" if a_time == "tf" else "_" + a_time))


def window_day(i, who, opt):
    """(day, raw, S′, parts) of one window day, from the cached means and Saturn points (as window_dists does)."""
    ref = D.reference(START, opt["a_time"]); d = START + dt.timedelta(days=i); oth = "A" if who == "B" else "B"
    raw, sc, parts = D.day_charge(d, who, oth, *D.flag_scale(ref[who]["mean"][i], ref[who]), ref[who]["station"][i], opt)
    return d, raw, sc, parts


def season_points(parts, season):
    return sum(v for n, v in parts if "(" in n and n[n.index("(") + 1:].split(", ")[-1].startswith(season + " "))


class GoldensV3(unittest.TestCase):
    def test_v3_goldens(self):
        for day in GOLDEN_DAYS:
            for at in ("tf", "noon"):
                with self.subTest(day=day, a_time=at), open(gpath(day, at), encoding="utf-8") as fh:
                    self.assertEqual(json.dumps(run(day, a_time=at), ensure_ascii=False, indent=1) + "\n", fh.read())

    def test_cli_default_is_v3(self):
        out = subprocess.run([sys.executable, os.path.join(HERE, "daily.py"), "2026-10-21"], capture_output=True, text=True, check=True).stdout
        with open(gpath("2026-10-21", "tf"), encoding="utf-8") as fh: self.assertEqual(out, fh.read())
        off = json.loads(subprocess.run([sys.executable, os.path.join(HERE, "daily.py"), "2026-10-21", "--no-seasons"],
                                        capture_output=True, text=True, check=True).stdout)
        self.assertNotIn("seasons", off); self.assertEqual(off["options"]["seasons"], False)
        self.assertEqual(off["engine"], "fl_toolkit v3.0 · seasons off · A time-free")


class Headline(unittest.TestCase):
    def test_charge_pct_tier_sits_next_to_charge(self):
        for day in ("2026-10-21", "2027-05-12"):
            for k in ("A", "B", "A_with_C"):
                r = run(day)[k]
                self.assertEqual(list(r)[:3], ["charge", "tier", "charge_pct_tier"])
                self.assertEqual(r["charge_pct_tier"], D.tier_pct(r["charge_pct"])); self.assertEqual(r["charge_pct_tier"], r["tier_pct"])

    def test_receipt_carries_both_percentages(self):
        for day, opt in (("2026-10-21", {}), ("2026-09-08", {}), ("2026-10-21", dict(seasons=False)), ("2026-10-21", dict(a_time="noon"))):
            r = run(day, **opt)
            m = re.fullmatch(r"Math: (\S+) · chemistry (\S+) · A charge (\d+) (\S+) \[(\d+)%\], pull (\S+?)(🔥|✅)? \((\d+)%\)"
                             r" · B charge (\d+) (\S+) \[(\d+)%\], pull (\S+?)(🔥|✅)? \((\d+)%\)", r["receipt"])
            self.assertIsNotNone(m, r["receipt"])
            for off, w in ((2, "A"), (8, "B")):
                g = m.groups()[off:off + 6]
                self.assertEqual((int(g[0]), g[1], int(g[2]), float(g[3]), g[4] or "", int(g[5])),
                                 (r[w]["charge"], r[w]["tier"], D.pct100(r[w]["charge_pct"]), r[w]["pull"], r[w]["flag"],
                                  D.pct100(r[w]["pull_pct_longrun"])))

    def test_pct100_rounds_the_printed_value_half_up(self):
        self.assertEqual([D.pct100(p) for p in (0.285, 0.284, 0.0, 1.0, 0.515)], [29, 28, 0, 100, 52])


class Saturation(unittest.TestCase):
    """(c) Days pinned at 100 separate by raw and by percentile."""

    def test_days_at_100_separate(self):
        for opt in (dict(V2), dict(V3)):
            for who in ("A", "B"):
                days = [window_day(i, who, opt) for i in range(365)]
                top = sorted((raw, d) for d, raw, sc, _ in days if sc == 100)
                lo, hi = top[0], top[-1]
                self.assertLess(lo[0], hi[0])
                dist = D.window_dists(START, D.reference(START, opt["a_time"]), opt)[who]
                self.assertLess(D.pct(lo[0], dist), D.pct(hi[0], dist))
        a, b = run("2026-10-21"), run("2026-11-02")                       # two printed days, both A at 100 (raw 102 vs 97)
        self.assertEqual((a["A"]["charge"], b["A"]["charge"]), (100, 100))
        self.assertNotEqual(a["A"]["charge_pct"], b["A"]["charge_pct"]); self.assertNotEqual(a["A"]["raw"], b["A"]["raw"])


class Seasons(unittest.TestCase):
    def test_block_matches_the_parts_and_the_formula(self):
        r = run("2026-10-21"); blk = {(p["season"], p["pillar"]): p for p in r["seasons"]["pillars"]}
        self.assertEqual([p["season"] for p in r["seasons"]["pillars"]], ["流年", "流月", "大運 A", "大運 B", "大運 C"])
        self.assertEqual((blk[("流年", "丙午")]["ten_god"], blk[("流月", "戊戌")]["ten_god"]["A"]),
                         ({"A": "偏財", "B": "食神", "C": "偏財"}, "七殺"))
        for k in ("A", "B", "A_with_C"):
            for (season, pillar), p in blk.items():
                self.assertAlmostEqual(p["points"][k], season_points(r[k]["parts"], season + " " + pillar.split()[0])
                                       if season.startswith("大運") else season_points(r[k]["parts"], season), places=3)
            self.assertAlmostEqual(r["seasons"]["total"][k], sum(p["points"][k] for p in blk.values()), places=3)
        # 2026-10-21 is a 戊辰 day in a 戊戌 month: 辰戌冲 at ½ · W_other 15 = 7.5 for every charge
        self.assertEqual([blk[("流月", "戊戌")]["points"][k] for k in ("A", "B", "A_with_C")], [7.5, 7.5, 7.5])
        # B's own decade 己巳: 己 is 甲's combine partner, ½ · 10; A's decade 庚辰 in B's other: 辰辰自刑 ½ · 10
        self.assertEqual((blk[("大運 B", "己巳")]["points"]["B"], blk[("大運 A", "庚辰")]["points"]["B"]), (5.0, 5.0))

    def test_seasons_off_is_v2_and_on_adds_exactly_the_block(self):
        for day in ("2026-10-21", "2027-05-12"):
            on, off = run(day), run(day, seasons=False)
            for k in ("B",):
                self.assertAlmostEqual(on[k]["raw"] - off[k]["raw"], on["seasons"]["total"][k], places=9)
            self.assertNotIn("seasons", off)

    def test_year_month_terms_are_inside_seasons(self):
        a, b = run("2026-10-21"), run("2026-10-21", ym=True)
        self.assertEqual({k: v for k, v in a.items() if k != "options"}, {k: v for k, v in b.items() if k != "options"})

    def test_own_decade_switch(self):
        d = dt.date(2026, 10, 21)
        tags = lambda: [m[2] for m in D.members(d, "A", "B", dict(V3))[1] if not isinstance(m, str)]
        self.assertEqual(tags(), ["流年 丙午 ×0.5", "流月 戊戌 ×0.5", "大運 B 己巳 ×0.5"])     # her own decade stays in own only
        old = D.SEASON_OWN_DECADE; D.SEASON_OWN_DECADE = True
        try:
            self.assertEqual(tags()[-1], "大運 A 庚辰 ×0.5")                                    # the literal draft: counted twice
            parts = D.day_charge(d, "A", "B", "", 1.0, 0, dict(V3))[2]
            self.assertIn(["辰辰自刑 (other, 大運 A 庚辰 ×0.5)", 5.0], [list(p) for p in parts])
        finally:
            D.SEASON_OWN_DECADE = old

    def test_outfit_before_is_the_v3_headline(self):
        r = D.main(dt.date(2026, 10, 21), dict(V3), {"B": [{"slot": "top", "color": "green"}, {"slot": "bottom", "color": "silver"}]})
        self.assertEqual((r["outfit"]["B"]["wearer"]["charge"][0], r["outfit"]["B"]["wearer"]["raw"][0]), (r["B"]["charge"], r["B"]["raw"]))

    def test_c_decade_does_not_depend_on_his_time_before_mid_2030(self):
        c, o = D.CH["C"], D.ch["C"]
        for h, mi in ((0, 0), (12, 0), (22, 59)):
            tu = D.loc(c["y"], c["m"], c["d"], h, mi, c["tz"]).astimezone(D.UTC)
            a0 = D.Z.luck_start_years(((o["jie"][1] - tu) if o["fwd"] else (tu - o["jie"][0])).total_seconds() / 86400)
            self.assertGreater(tu + dt.timedelta(days=(a0 + 50) * D.YEAR), dt.datetime(2030, 7, 1, tzinfo=D.UTC))
        self.assertEqual(D.lucks("C", dt.date(2030, 6, 30), V3), [("丁酉", 1)])


class SixtyDayLoop(unittest.TestCase):
    """(b) Same day pillar 60 days apart, different month: B's 流月 points follow the month branch, and so does B's charge."""

    def test_same_pillar_different_month(self):
        moved = raw_moved = charge_moved = 0
        for i in range(60):
            d1, d2 = START + dt.timedelta(days=i), START + dt.timedelta(days=i + 60)
            self.assertEqual(D.Z.day_index(d1.year, d1.month, d1.day), D.Z.day_index(d2.year, d2.month, d2.day))
            day_b = D.Z.BRANCHES[D.Z.day_index(d1.year, d1.month, d1.day) % 12]
            rows = {}
            for d, j in ((d1, i), (d2, i + 60)):
                mb = D.year_month_pillars(d)[1][1]
                want = D.SEASON_W * sum(D.Z.W_OTHER[r] for r in D.Z.relations(day_b, mb))
                _, raw_on, sc_on, parts = window_day(j, "B", dict(V3))
                _, raw_off, sc_off, _ = window_day(j, "B", dict(V2))
                self.assertEqual(season_points(parts, "流月"), want)         # the month branch, at half weight
                rows[d] = (mb, want, raw_on - raw_off, sc_on, sc_off, D.year_month_pillars(d)[0])
            (m1, w1, s1, c1, o1, y1), (m2, w2, s2, c2, o2, y2) = rows[d1], rows[d2]
            if m1 != m2 and w1 != w2 and y1 == y2:                            # same year, decades unchanged in this span
                moved += 1; raw_moved += s1 != s2
                charge_moved += (c1 - o1) != (c2 - o2)
        self.assertGreaterEqual(moved, 20)
        self.assertEqual(raw_moved, moved)                                    # B's seasons raw differs whenever 流月 differs
        self.assertGreater(charge_moved, 0)                                   # and it reaches the printed charge


class TimeFreeSplit(unittest.TestCase):
    """(d) On A's split days her decades weigh by chart count: the shares sum to 1."""

    def test_shares_sum_to_one(self):
        split = 0
        for i in range(400):
            d = START + dt.timedelta(days=i); lk = D.lucks("A", d, V3)
            self.assertEqual(sum(n for _, n in lk), D.TF_N)
            if len(lk) > 1:
                split += 1
                other = D.members(d, "B", "A", dict(V3))[1]
                ws = [m[1] for m in other if not isinstance(m, str) and m[2].startswith("大運 A")]
                self.assertAlmostEqual(sum(ws), D.SEASON_W, places=12)
        self.assertEqual(split, 100)                                          # 2027-04-07 … 2027-07-15
        r = run("2027-05-12")
        sh = [p["share"] for p in r["seasons"]["pillars"] if p["season"] == "大運 A"]
        self.assertEqual(sh, [0.647, 0.353]); self.assertAlmostEqual(sum(sh), 1.0, places=12)

    def test_b_on_a_split_day_is_the_mean_over_her_charts(self):
        d = dt.date(2027, 5, 12); ref = D.reference(START, "tf"); i = (d - START).days
        f, s = D.flag_scale(ref["B"]["mean"][i], ref["B"]); stp = ref["B"]["station"][i]; g = D.Z.day_index(d.year, d.month, d.day)
        per = []
        for c in D.tf()["charts"]:
            own, other, st = D.members(d, "B", "A", dict(V3), fix_a=D.luck_branch(c, d))
            per.append(D.Z.rescale(D.Z.day_score(D.Z.STEMS[g % 10], D.Z.BRANCHES[g % 12], own, other, D.ch["B"]["dm"],
                                                 D.ch["B"]["year_branch"], D.T.daily_points(f, s), stp, st)[0]))
        self.assertEqual(run("2027-05-12")["B"]["charge"], D.rhu(sum(per) / len(per)))


if __name__ == "__main__":
    unittest.main()
