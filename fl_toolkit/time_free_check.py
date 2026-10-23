"""Time-free A: Khai's check values next to ours. Usage: python3 time_free_check.py → robustness/time_free_check.md (+ .json)

Khai's values were made with the v1 conventions (his noon run matched the shipped v1 ref_2026-10-20.json exactly):
pull sampled over the calendar day 00:00–23:50 (wall clock, no DST rule) and chemistry read at 16:00 UTC. So every
check is computed twice: under v1 conventions (to test that our time-free math is his), and under the v2 defaults
this pack now ships (BaZi-day pull, local-noon chemistry), read straight from the shipped reference caches.
Window: 2026-10-20 + 365 days. Deterministic: no timestamps in the output."""
import os, sys, json, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.argv = sys.argv[:1]
import daily as D

UTC, P, R, Z, rhu = D.UTC, D.P, D.R, D.Z, D.rhu
START = dt.date(2026, 10, 20)
DAYS = [START + dt.timedelta(days=i) for i in range(365)]
OUT = os.path.join(HERE, "robustness")
KHAI = {                                            # the cover note's check values, verbatim
    "tf_top": 3.214513, "tf_fire": 1.881009, "tf_ok": 1.284722, "tf_pair_top": 3.695634,
    "1021_pull_tf": 2.1, "1021_pull_noon": 1.9, "1021_charge_tf": 90, "1021_chem_tf": 2.4,
    "chem_windows": "12, same as noon", "chem_peak": "2027-05-13", "chem_max_move": "≤ 0.2",
    "pull_max_move": "≤ 0.6", "flags_flipped": "12 (first 2026-12-01: ✅ → 🔥)", "charges_changed": "33 (first 2026-12-09: 88 → 99)",
    "share_first": "1/119 on 2027-04-07 (0 through 04-06)", "share_60": "60/119 on 2027-05-27", "share_all": "119/119 from 2027-07-16",
    "0512": "庚辰 0.647 · 己卯 0.353; charge 79 → 74", "top_pull": "2027-07-18 (noon) → 2027-07-17 (10.0); 07-18 is 9.8",
}
OPT = {at: dict(D.DEFAULT_OPT, a_time=at, seasons=False) for at in ("noon", "tf")}   # Khai's checks are v2-era: seasons off


def v1_grid(day):
    """v1 sampling: 144 wall-clock steps from local midnight by aware-datetime arithmetic (what v1 daily.py did)."""
    d0 = D.loc(day.year, day.month, day.day)
    return [((d0 + dt.timedelta(minutes=10 * i)).astimezone(UTC), 1.0, i) for i in range(144)]


def v1_series():
    """Per day, per A-chart mode: pull mean (v1 grid) and chemistry raw at 16:00 UTC; plus B's mean for B's flags."""
    out = {}
    for at in ("noon", "tf"):
        out[at] = dict(mean=[D.wmean(D.samples(d, "A", v1_grid(d), at)) for d in DAYS],
                       chem=[D.chem(dt.datetime(d.year, d.month, d.day, 16, tzinfo=UTC), at)[0] for d in DAYS])
    return out


def v2_series():
    out = {}
    for at in ("noon", "tf"):
        ref = D.reference(START, at); out[at] = dict(mean=ref["A"]["mean"], chem=ref["chem"])
    return out


def cuts(mean):
    v = sorted(mean, reverse=True); return dict(top=v[0], fire=v[25], ok=v[72])


def windows(raw):
    """pair_core.timeline's windows: runs of consecutive days with raw ≥ 50% of the run's top → [(first, last, peak)]."""
    top = max(raw); out = []; cur = None
    for d, s in zip(DAYS, raw):
        if s >= 0.5 * top:
            if cur and (d - cur[1]).days == 1: cur[1] = d
            else: cur = [d, d]; out.append(cur)
        else: cur = None
    return [(a, b) for a, b in out]


def analyse(ser):
    """Every check on one convention's series."""
    c = {at: cuts(ser[at]["mean"]) for at in ser}
    ptop = {at: max(ser[at]["chem"]) for at in ser}
    scale = {at: [rhu(m / c[at]["top"] * 10, 1) for m in ser[at]["mean"]] for at in ser}
    flag = {at: ["🔥" if m >= c[at]["fire"] else "✅" if m >= c[at]["ok"] else "" for m in ser[at]["mean"]] for at in ser}
    chs = {at: [rhu(s / ptop[at] * 10, 1) for s in ser[at]["chem"]] for at in ser}
    charge = {}
    for at in ser:
        nat = D.nat_of("A", at); charge[at] = []
        for i, d in enumerate(DAYS):
            stp = R.saturn_station(nat, D.noon(d))[0]
            charge[at].append(D.day_charge(d, "A", "B", flag[at][i], scale[at][i], stp, OPT[at])[1])
    i1021 = DAYS.index(dt.date(2026, 10, 21)); i0512 = DAYS.index(dt.date(2027, 5, 12))
    wn, wt = windows(ser["noon"]["chem"]), windows(ser["tf"]["chem"])
    peak = {at: DAYS[max(range(365), key=lambda i: (ser[at]["chem"][i], -i))] for at in ser}
    flips = [(DAYS[i], flag["noon"][i], flag["tf"][i]) for i in range(365) if flag["noon"][i] != flag["tf"][i]]
    moved = [(DAYS[i], charge["noon"][i], charge["tf"][i]) for i in range(365) if charge["noon"][i] != charge["tf"][i]]
    topd = {at: DAYS[max(range(365), key=lambda i: (ser[at]["mean"][i], -i))] for at in ser}
    jul18 = DAYS.index(dt.date(2027, 7, 18))
    return {
        "tf_top": round(c["tf"]["top"], 6), "tf_fire": round(c["tf"]["fire"], 6), "tf_ok": round(c["tf"]["ok"], 6),
        "tf_pair_top": round(ptop["tf"], 6),
        "noon_cuts": {k: round(v, 6) for k, v in c["noon"].items()}, "noon_pair_top": round(ptop["noon"], 6),
        "1021_pull_tf": scale["tf"][i1021], "1021_pull_noon": scale["noon"][i1021],
        "1021_charge_tf": charge["tf"][i1021], "1021_chem_tf": chs["tf"][i1021],
        "chem_windows": "%d tf vs %d noon, %s" % (len(wt), len(wn), "same dates" if wt == wn else "dates differ: tf %s" % [(a.isoformat(), b.isoformat()) for a, b in wt]),
        "chem_peak": "%s tf · %s noon" % (peak["tf"], peak["noon"]),
        "chem_max_move": rhu(max(abs(a - b) for a, b in zip(chs["tf"], chs["noon"])), 1),
        "pull_max_move": rhu(max(abs(a - b) for a, b in zip(scale["tf"], scale["noon"])), 1),
        "flags_flipped": "%d (first %s: %s → %s)" % ((len(flips),) + ((flips[0][0].isoformat(), flips[0][1] or "·", flips[0][2] or "·") if flips else ("-", "-", "-"))),
        "charges_changed": "%d (first %s: %s → %s)" % ((len(moved),) + ((moved[0][0].isoformat(), moved[0][1], moved[0][2]) if moved else ("-", "-", "-"))),
        "0512_charge": "%s → %s" % (charge["noon"][i0512], charge["tf"][i0512]),
        "top_pull": "%s (noon) → %s (%s); 07-18 is %s" % (topd["noon"], topd["tf"], scale["tf"][DAYS.index(topd["tf"])], scale["tf"][jul18]),
    }


def shares():
    """己卯's share of A's 119 charts through the window (independent of the sampling conventions)."""
    row = []
    for d in DAYS:
        n = dict(D.lucks("A", d, OPT["tf"])); row.append((d, n.get("己卯", 0)))
    first = next(d for d, n in row if n > 0)
    s60 = next(d for d, n in row if n >= 60)
    full = next(d for d, n in row if n == D.TF_N)
    n0512 = dict(D.lucks("A", dt.date(2027, 5, 12), OPT["tf"]))
    return {"share_first": "%d/119 on %s (0 through %s)" % (dict(row)[first], first, first - dt.timedelta(days=1)),
            "share_60": "%d/119 on %s (first day ≥ 60)" % (dict(row)[s60], s60),
            "share_all": "119/119 from %s" % full,
            "0512_shares": " · ".join("%s %.3f" % (k, v / D.TF_N) for k, v in n0512.items())}


if __name__ == "__main__":
    v1, v2, sh = analyse(v1_series()), analyse(v2_series()), shares()
    rows = [("time-free ref top", "tf_top"), ("time-free ref fire (🔥 cut)", "tf_fire"), ("time-free ref ok (✅ cut)", "tf_ok"),
            ("time-free chemistry pair_top", "tf_pair_top"), ("2026-10-21 A pull, time-free", "1021_pull_tf"),
            ("2026-10-21 A pull, noon", "1021_pull_noon"), ("2026-10-21 A charge, time-free", "1021_charge_tf"),
            ("2026-10-21 chemistry, time-free", "1021_chem_tf"), ("chemistry windows", "chem_windows"),
            ("chemistry peak", "chem_peak"), ("chemistry: largest daily move tf vs noon", "chem_max_move"),
            ("A pull: largest daily move tf vs noon", "pull_max_move"), ("A flags that flip", "flags_flipped"),
            ("A charges that change", "charges_changed"), ("top pull day", "top_pull")]
    md = ["# Time-free A — Khai's check values next to ours", "",
          "Window 2026-10-20 + 365 days. **v1 conventions** = Khai's (calendar-day pull 00:00–23:50, chemistry at 16:00 UTC; "
          "his noon run matched the shipped v1 reference). **v2 shipped** = this pack's defaults (BaZi-day pull 23:00–22:50 with "
          "the DST rule, chemistry at local noon), read from the shipped `ref_2026-10-20*.json` caches.", "",
          "| check | Khai | ours, v1 conventions | ours, v2 shipped |", "|---|---|---|---|"]
    for label, k in rows:
        md.append("| %s | %s | %s | %s |" % (label, KHAI[k], v1[k], v2[k]))
    md += ["| 己卯 share starts | %s | %s | same (shares do not depend on sampling) |" % (KHAI["share_first"], sh["share_first"]),
           "| 己卯 share reaches 60 | %s | %s | same |" % (KHAI["share_60"], sh["share_60"]),
           "| 己卯 share complete | %s | %s | same |" % (KHAI["share_all"], sh["share_all"]),
           "| 2027-05-12 shares; A charge noon → tf | %s | %s; %s | %s; %s |" % (KHAI["0512"], sh["0512_shares"], v1["0512_charge"], sh["0512_shares"], v2["0512_charge"]),
           "", "Noon reference under v1 conventions (must equal the shipped v1 cache: top 3.276371, fire 1.861061, ok 1.299644, "
           "pair_top 3.703836): %s, pair_top %s." % (v1["noon_cuts"], v1["noon_pair_top"]),
           "", "Method: the time-free pull is the exact mean of §9's moment score over A's 119 charts (00:00–19:40, one every "
           "10 min), computed from sorted point sets (checked against the naive 119-chart mean to 1e-12 in test_daily.py); "
           "time-free chemistry is the mean of §10's pair score over the 119 charts' hot spots; charges use the share-weighted "
           "mean of the per-luck-pillar S′ (rounded half up) and the Saturn station of the averaged chart."]
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, "time_free_check.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    json.dump(dict(khai=KHAI, v1=v1, v2=v2, shares=sh), open(os.path.join(OUT, "time_free_check.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, sort_keys=True, default=str)
    print("\n".join(md))
