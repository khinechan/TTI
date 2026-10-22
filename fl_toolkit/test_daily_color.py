"""§13 outfit color on real days: the color brief's acceptance examples. Run: python3 -m unittest test_daily_color -v

The brief's numbers were made by a reference implementation on the v1 pack (calendar-day pull, the v1 reference, the
noon chart), so LegacyAcceptance rebuilds exactly those inputs and checks every number to the brief's ±0.005. V2 checks
the same outfits through daily.py as shipped (the brief's §5 item 6: no outfit → no key, nothing else moves)."""
import datetime as dt
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import daily as D
import color_core as C

V1_REF = {"A": {"top": 3.276370515630749, "fire": 1.8610606950505333, "ok": 1.2996442183606707},
          "B": {"top": 3.4505511082601554, "fire": 2.2652526728213394, "ok": 1.581426523312876}}   # v1 ref_2026-10-20.json
NOON = dict(D.DEFAULT_OPT, a_time="noon")
EX = {   # the brief's §5 examples 2–5: day, B's outfit
    2: ("2026-10-21", [{"slot": "top", "color": "green"}, {"slot": "bottom", "color": "silver"}]),
    3: ("2026-10-23", [{"slot": "top", "color": "dark brown"}, {"slot": "bottom", "color": "dark brown"}, {"slot": "peek", "color": "red"}]),
    4: ("2026-10-26", [{"slot": "top", "color": "forest green"}, {"slot": "bottom", "color": "forest green"}]),
    5: ("2026-10-26", [{"slot": "top", "color": "silver"}, {"slot": "bottom", "color": "silver"}]),
}
F = {w: C.SC.chart_strength(D.ch[w]["pillars"]) for w in ("A", "B")}


def v1_rows(day, who):
    """v1 sampling: 144 steps from local midnight; v1 blocks: 子 = steps 0–5, block i = steps (2i−1)·6 … (2i+1)·6 − 1,
       steps 138–143 (23:00–23:50) belong to no block (they are never in a seen block)."""
    d0 = D.loc(day.year, day.month, day.day)
    grid = [((d0 + dt.timedelta(minutes=10 * k)).astimezone(D.UTC), 1.0, k) for k in range(144)]
    rows = D.samples(day, who, grid, "noon")
    blk = lambda k: "子" if k < 6 or k >= 138 else D.Z.BRANCHES[(k - 6) // 12 + 1]
    return [v for v, _, _ in rows], [w for _, w, _ in rows], [blk(k) for _, _, k in rows]


def v1_case(n):
    day_s, outfit = EX[n]; day = dt.date.fromisoformat(day_s); E = C.outfit_vector(outfit)
    s, w, b = v1_rows(day, "B"); fl, sc = D.flag_scale(sum(s) / 144, V1_REF["B"])
    raw = D.day_charge(day, "B", "A", fl, sc, D.R.saturn_station(D.natB, D.noon(day))[0], NOON)[0]
    we = C.wearer_effect(E, F["B"]["F"], raw)
    s, w, b = v1_rows(day, "A")
    ve = C.viewer_effect(E, F["A"]["F"], C.taste(outfit, "Cancer"), s, w, b, V1_REF["A"]["top"])
    return E, we, ve, C.role_tag(E, F["A"]["dm_element"])[0], C.role_tag(E, F["B"]["dm_element"])[0]


class LegacyAcceptance(unittest.TestCase):
    def check(self, n, E=None, W=None, raw=None, charge=None, T=None, V=None, pull=None, block=None, roles=None):
        e, we, ve, ra, rb = v1_case(n)
        if E: self.assertEqual({k: round(v, 4) for k, v in e.items() if v}, E)
        if W is not None: self.assertAlmostEqual(we["W"], W, places=4)
        if raw: self.assertEqual((we["raw_before"], round(we["raw_after"], 3)), raw)
        if charge: self.assertEqual((we["charge_before"], we["charge_after"], we["tier_after"]), charge)
        if T is not None: self.assertAlmostEqual(ve["T"], T, places=4)
        if V is not None: self.assertAlmostEqual(ve["V"], V, places=4)
        if pull: self.assertAlmostEqual(ve["day_pull_before"], pull[0], delta=0.005); self.assertAlmostEqual(ve["day_pull_after"], pull[1], delta=0.005)
        if block:
            b0, b1 = ve["blocks"][block[0]]
            self.assertAlmostEqual(b0, block[1], delta=0.005); self.assertAlmostEqual(b1, block[2], delta=0.005)
        if roles: self.assertEqual((ra, rb), roles)

    def test_example_2(self):
        self.check(2, E={"wood": 0.6471, "metal": 0.3529}, W=0.2941, raw=(77, 74.059), charge=(57, 51, "🟡"),
                   T=0.3529, V=0.3118, pull=(1.919, 1.982), block=("辰", 2.110, 2.274), roles=("output", "peer"))

    def test_example_3(self):
        self.check(3, E={"earth": 0.8947, "fire": 0.1053}, W=-0.9474, raw=(65, 74.474), charge=(31, 52, "🟡"),
                   V=0.70, pull=(1.129, 1.198), block=("午", 0.910, 1.069), roles=("officer", "wealth"))

    def test_example_4(self):
        self.check(4, W=1.0, raw=(84, 74.0), charge=(73, 51, "🟡"), V=0.70, pull=(7.113, 7.618), block=("申", 7.371, 8.661),
                   roles=("output", "peer"))

    def test_example_5_control(self):
        self.check(5, W=-1.0, charge=(73, 95, "🔴"), V=-0.40, pull=(7.113, 6.825), roles=("resource", "officer"))

    def test_chart_pillars_come_from_daily(self):
        self.assertEqual(D.ch["A"]["pillars"], ["庚申", "甲申", "壬申", None])
        self.assertEqual(D.ch["B"]["pillars"], ["己巳", "癸酉", "甲戌", "丁卯"])
        self.assertEqual((D.A.SIGNS[int(D.pA["Venus"] // 30)], D.A.SIGNS[int(D.pB["Venus"] // 30)]), ("Can", "Lib"))


class V2(unittest.TestCase):
    """The same outfits through daily.main as shipped (both A-chart modes)."""

    @classmethod
    def setUpClass(cls):
        cls.r = {(n, at): json.loads(json.dumps(D.main(dt.date.fromisoformat(EX[n][0]), dict(D.DEFAULT_OPT, a_time=at),
                                                       {"B": EX[n][1]}), ensure_ascii=False))
                 for n in EX for at in ("tf", "noon")}
        cls.plain = {(n, at): json.loads(json.dumps(D.main(dt.date.fromisoformat(EX[n][0]), dict(D.DEFAULT_OPT, a_time=at)), ensure_ascii=False))
                     for n in EX for at in ("tf", "noon")}

    def test_outfit_never_moves_the_headline_keys(self):
        for k, r in self.r.items():
            self.assertEqual({x: v for x, v in r.items() if x != "outfit"}, self.plain[k])
            self.assertNotIn("outfit", self.plain[k])

    def test_before_equals_the_headline(self):
        for (n, at), r in self.r.items():
            o = r["outfit"]["B"]
            self.assertEqual(o["wearer"]["charge"][0], r["B"]["charge"]); self.assertEqual(o["wearer"]["raw"][0], r["B"]["raw"])
            self.assertEqual(D.rhu(o["viewer"]["day_pull"][0], 1), r["A"]["pull"])

    def test_directions_hold(self):                         # the brief's robust signs: ex2–4 pull up; ex2, 4 charge down; ex3 up
        for at in ("tf", "noon"):
            sign = lambda n: (self.r[(n, at)]["outfit"]["B"]["viewer"]["day_pull"], self.r[(n, at)]["outfit"]["B"]["wearer"]["charge"])
            for n, (pu, cu) in {2: (1, -1), 3: (1, 1), 4: (1, -1), 5: (-1, 1)}.items():
                p, c = sign(n)
                self.assertEqual((p[1] > p[0]) - (p[1] < p[0]), pu, (n, at)); self.assertEqual((c[1] > c[0]) - (c[1] < c[0]), cu, (n, at))

    def test_seen_override_and_cap(self):
        r = D.main(dt.date(2026, 10, 26), NOON, {"B": EX[4][1]}, seen="申")
        self.assertEqual(list(r["outfit"]["B"]["viewer"]["blocks"]), ["申"]); self.assertEqual(r["outfit"]["params"]["SEEN"], "申")
        self.assertLessEqual(r["outfit"]["B"]["viewer"]["day_pull"][1], 10.0)

    def test_A_as_wearer(self):
        r = D.main(dt.date(2026, 10, 21), NOON, {"A": [{"slot": "top", "color": "red"}]})
        o = r["outfit"]["A"]; self.assertEqual((o["worn_by"], o["seen_by"], o["viewer"]["venus"]), ("A", "B", "Lib"))
        self.assertEqual(o["wearer"]["W"], 1.0); self.assertEqual(o["wearer"]["raw"], [r["A"]["raw"], r["A"]["raw"] - 10.0])

    def test_cli_rejects_bad_outfits(self):
        import subprocess
        for args in (["--outfit-B", '[{"slot": "top", "color": "mauve"}]'], ["--outfit-B", "not json"],
                     ["--seen", "辰"], ["--outfit-B", '[{"slot": "hat", "color": "red"}]']):
            p = subprocess.run([sys.executable, os.path.join(HERE, "daily.py"), "2026-10-21"] + args, capture_output=True, text=True)
            self.assertEqual(p.returncode, 2, args)


if __name__ == "__main__":
    unittest.main()
