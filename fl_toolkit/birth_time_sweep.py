"""birth_time_sweep — audit item 14 + the cover's "A's birth time": which A–B facts would move if A's unknown birth
time were known. REPORTS ONLY: no chart changes and no birth time is added to the data (it measures against A's noon chart; the book's default is time-free A, THE_MATH §14).

Sweep: A born 1980-08-27 at hh:mm America/Indiana/Indianapolis, hh:mm = 00:00, 00:10, …, 23:50 (144 steps);
each step is A = daily.build(dict(CH["A"], hm=(h, m))) (that also adds ASC/MC and an hour branch: "if known" extras only).
  orbs      o = astro_core.orb: A Mars ☌ B Venus (0°) · A Venus ☍ B Moon (180°) · B Mars ☍ A Moon (180°)
  family    pair_core.attraction_family, 1° orb. A→B = (chart_b = A, chart_a = B): A's Venus/Mars to B's points;
            B→A = (chart_b = B, chart_a = A). Book = A's bodies without Moon and angles; +Moon / +ASC,DSC (DSC = ASC + 180)
  spots     28.6 Lib = midpoint(B Venus, A Mars), a family hot spot only while that ☌ ≤ 1°;
            18.7 Can = midpoint(A Venus, B Moon + 180), only while that ☍ ≤ 1°
  crossing  the birth minute where o(A Mars ☌ B Venus) passes 1.0°: bisection between steps, to the minute and second
  chemistry P(day) = pair_core.pair_score(qualifying spots, t_day), 2026-10-20 .. 2027-10-19 (365 days), under
            v2: t = local noon America/New_York (new default) · v1: t = 16:00 UTC (old; the cover's numbers)
            scale = P / run top × 10 · windows = runs of consecutive days with P ≥ 50% of the run top (pair_core.timeline)
            vs the noon chart: max_day |scale − scale_noon|, (i) each run by its own top, (ii) both by the noon run's top
  luck      己卯 starts on the first day X with (X 12:00 UTC − birth UTC) / 365.2425 d ≥ its start age (daily.luck_branch)
  day       BaZi day pillar = bazi_core.day_index(1980, 8, 27, h + m/60) (the day turns at 23:00)
Usage: cd fl_toolkit && python3 birth_time_sweep.py   → robustness/birth_time_sweep.md + robustness/birth_time_sweep.json
"""
import sys, os, json, time, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "pure_math", "code")]
import daily as D
A, Z, P = D.A, D.Z, D.P

BDAY = (1980, 8, 27)                               # A's birth date; zone and place from daily.CH["A"]
STEP_MIN = 10                                      # sweep step: 144 births 00:00 .. 23:50 local
FAM_ORB = 1.0                                      # attraction-family orb (THE_MATH §10, pair_core default)
WIN0, NDAYS = dt.date(2026, 10, 20), 365           # chemistry reference window 2026-10-20 .. 2027-10-19
WIN_FRAC = 0.5                                     # window = consecutive days with P ≥ 50% of the run top (pair_core.timeline)
V2_LOCAL_HOUR, V1_UTC_HOUR = 12, 16                # headline instants: v2 local noon New York (new) · v1 16:00 UTC (old)
HEAD = {"v2": "local noon America/New_York (new default)", "v1": "16:00 UTC (old; the cover's numbers)"}
YEAR = 365.2425                                    # days per luck-pillar year (daily.YEAR)
LUCK_NEXT = "己卯"                                 # A's luck pillar after 庚辰
DAY_FLIP_MIN = 23 * 60                             # the BaZi day turns at 23:00 (bazi_core.day_index)
ZERO_DAYS = ("2026-10-27", "2026-12-01", "2027-05-13")   # cover: chemistry 0.0 / raw 0 once 28.6 Lib drops
LATE_PEAK = ("2027-09-28", "2027-09-30")           # cover: the new peak once 28.6 Lib drops
S286, S187 = "28.6 Lib (B Venus ☌ A Mars)", "18.7 Can (A Venus ☍ B Moon, axis)"   # daily.py's spot labels
SYM = {0: "☌", 90: "□", 180: "☍"}
EXP = dict(mv=(0.47, 1.11), vm=(0.00, 0.67), audit_cross="20:00", cross="19:45", step_past="19:50", fam=(2, 1),
           windows=12, peak="2027-05-13", dmax=0.84, edge=1, luck_noon="2027-06-07",
           luck_range=("2027-04-06", "2027-07-16"), slope=5.0, moon=("07:40", "10:50"), pillars=("壬申", "癸酉"))
TOL = dict(about_min=30, luck_days=3, slope=0.5)   # how "about" is judged: ±30 min · ±3 days · ±0.5 day/hour
OUT = os.path.join(HERE, "robustness")
TZ = D.CH["A"]["tz"]
RND = getattr(Z, "round_half_up", round)           # the 0–10 scale rounds as pair_core.timeline does (half up, audit item 6)


def hm(x):
    return "%02d:%02d" % divmod(int(x), 60)


def hms(x):
    s = int(round(x * 60)); return "%02d:%02d:%02d" % (s // 3600, s // 60 % 60, s % 60)


def t_birth(x):
    """Birth instant (UTC) for x minutes after local midnight (no DST in Indianapolis in 1980)."""
    return (D.loc(*BDAY, 0, 0, TZ) + dt.timedelta(minutes=x)).astimezone(D.UTC)


def orb_mv(x): return A.orb(A.lon("Mars", t_birth(x)), D.pB["Venus"], 0)
def orb_mm(x): return A.orb(A.lon("Moon", t_birth(x)), D.pB["Mars"], 180)


def edges(f, mins, lim=FAM_ORB):
    """Each change of [f ≤ lim] between sweep steps, bisected to the whole minute, then to the second."""
    out = []
    for a, b in zip(mins, mins[1:]):
        ia = f(a) <= lim
        if ia == (f(b) <= lim): continue
        lo, hi = a, b
        while hi - lo > 1:
            m = (lo + hi) // 2
            if (f(m) <= lim) == ia: lo = m
            else: hi = m
        x0, x1 = float(lo), float(hi)
        while (x1 - x0) * 60 > 1:
            xm = (x0 + x1) / 2
            if (f(xm) <= lim) == ia: x0 = xm
            else: x1 = xm
        out.append(dict(going="out" if ia else "in", last_minute_before=hm(lo), orb_before=round(f(lo), 4),
                        first_minute_after=hm(hi), orb_after=round(f(hi), 4), exact=hms(x1), minute=hi))
    return out


def fam(cb, ca, wb, wa):
    return ["%s %s %s %s %s %.2f" % (wb, f, SYM[g], wa, t, o) for f, g, t, o in P.attraction_family(cb, ca, FAM_ORB)]


def luck_start(o):
    """First day X with (X 12:00 UTC − birth) / YEAR ≥ a0(己卯) — daily.luck_branch's age — and the exact instant."""
    a0 = next(a for a, n in o["lucks"] if n == LUCK_NEXT); exact = o["t"] + dt.timedelta(days=a0 * YEAR)
    age = lambda x: (dt.datetime(x.year, x.month, x.day, 12, tzinfo=D.UTC) - o["t"]).total_seconds() / 86400 / YEAR
    x = (exact - dt.timedelta(days=2)).date()
    while age(x) < a0: x += dt.timedelta(days=1)
    return x, exact, a0


def step(mi):
    h, m = divmod(mi, 60); o = D.build(dict(D.CH["A"], hm=(h, m))); p = o["pts"]
    book = {k: p[k] for k in A.BODY if k != "Moon"}
    var = dict(book=book, moon=dict(book, Moon=p["Moon"]), angles=dict(book, ASC=p["ASC"], DSC=(p["ASC"] + 180) % 360))
    mv, vm, mm = A.orb(p["Mars"], D.pB["Venus"], 0), A.orb(p["Venus"], D.pB["Moon"], 180), A.orb(p["Moon"], D.pB["Mars"], 180)
    ab = fam(book, D.natB, "A", "B"); ba = {k: fam(D.natB, c, "B", "A") for k, c in var.items()}
    q286, q187 = any(x.startswith("A Mars ☌ B Venus") for x in ab), any(x.startswith("A Venus ☍ B Moon") for x in ab)
    assert q286 == (mv <= FAM_ORB) and q187 == (vm <= FAM_ORB)
    s286, s187 = P.midpoint(D.pB["Venus"], p["Mars"]), P.midpoint(p["Venus"], (D.pB["Moon"] + 180) % 360)
    spots = {k: v for k, v, q in ((S286, s286, q286), (S187, s187, q187)) if q}
    lday, lexact, a0 = luck_start(o); g = Z.day_index(*BDAY, h + m / 60)
    return dict(time=hm(mi), minute=mi, orb_mars_venus=round(mv, 4), orb_venus_moon=round(vm, 4), orb_moon_mars=round(mm, 4),
                fam_AB=ab, fam_BA=ba, n_AB=len(ab), n_BA={k: len(v) for k, v in ba.items()},
                spot_286=dict(lon=round(s286, 4), fmt=A.fmt(s286), qualifies=q286),
                spot_187=dict(lon=round(s187, 4), fmt=A.fmt(s187), qualifies=q187),
                day_pillar=Z.pillar_name(g), luck_start_age=round(a0, 4), luck_start=lday.isoformat(),
                luck_exact_utc=lexact.strftime("%Y-%m-%d %H:%M"),
                if_known=dict(ASC=A.fmt(p["ASC"]), MC=A.fmt(p["MC"]), hour_branch=Z.hour_branch(h + m / 60), Moon=A.fmt(p["Moon"]))
                ), spots, o


# ---------- chemistry: the sky does not depend on A's birth time, so each day's longitudes are computed once ----------
DAYS = [WIN0 + dt.timedelta(days=i) for i in range(NDAYS)]
INST = {"v2": [D.loc(d.year, d.month, d.day, V2_LOCAL_HOUR).astimezone(D.UTC) for d in DAYS],
        "v1": [dt.datetime(d.year, d.month, d.day, V1_UTC_HOUR, tzinfo=D.UTC) for d in DAYS]}
_SKY = {}


def _sky_lon(body, t, _lon=A.lon):
    """astro_core.lon behind a dict memo (same values; pair_core.pair_score itself is called unchanged)."""
    k = (body, t)
    if k not in _SKY: _SKY[k] = _lon(body, t)
    return _SKY[k]


def chem(spots, conv):
    raw = [P.pair_score(spots, t)[0] for t in INST[conv]]; top = max(raw) or 1.0
    sc = [RND(s / top * 10, 1) for s in raw]; wins, cur = [], None
    for i, s in enumerate(raw):
        if s >= WIN_FRAC * top:
            if cur and cur[1] == i - 1: cur[1] = i; cur[2] = max(cur[2], sc[i])
            else: cur = [i, i, sc[i]]; wins.append(cur)
        else:
            cur = None
    inw = {i for w in wins for i in range(w[0], w[1] + 1)}
    return dict(raw=raw, top=top, sc=sc, wins=wins, inw=inw, itop=raw.index(max(raw)))


def versus(r, n):
    own = [abs(a / r["top"] - b / n["top"]) * 10 for a, b in zip(r["raw"], n["raw"])]
    ntop = [abs(a - b) / n["top"] * 10 for a, b in zip(r["raw"], n["raw"])]
    if len(r["wins"]) == len(n["wins"]):
        sh = [abs(x[j] - y[j]) for x, y in zip(r["wins"], n["wins"]) for j in (0, 1)]; emax, emoved = max(sh), sum(1 for s in sh if s)
    else:
        emax = emoved = None
    io = own.index(max(own))
    return dict(dmax_own=round(max(own), 4), dmax_own_day=DAYS[io].isoformat(), dmax_noontop=round(max(ntop), 4),
                edge_shift_max_days=emax, edges_moved=emoved, days_in_window_changed=len(r["inw"] ^ n["inw"]))


def summarize(r):
    iso = lambda i: DAYS[i].isoformat(); t = r["itop"]
    pw = next((w for w in r["wins"] if w[0] <= t <= w[1]), None)
    return dict(top_day=iso(t), top_raw=round(r["raw"][t], 4), n_windows=len(r["wins"]),
                windows=[[iso(a), iso(b), c] for a, b, c in r["wins"]], peak_window=[iso(pw[0]), iso(pw[1])] if pw else None,
                zero_days={d: [round(r["raw"][(dt.date.fromisoformat(d) - WIN0).days], 4),
                               r["sc"][(dt.date.fromisoformat(d) - WIN0).days]] for d in ZERO_DAYS})


def runs(mins):
    """Contiguous runs of sweep minutes → ['hh:mm–hh:mm', …]."""
    out, cur = [], None
    for x in sorted(mins):
        if cur and x == cur[1] + STEP_MIN: cur[1] = x
        else: cur = [x, x]; out.append(cur)
    return ["%s–%s" % (hm(a), hm(b)) if b > a else hm(a) for a, b in out]


def main():
    t_start = time.time()
    mins = list(range(0, 24 * 60, STEP_MIN))
    rows, spots_by, objs = [], {}, {}
    for mi in mins:
        r, s, o = step(mi); rows.append(r); spots_by[mi] = s; objs[mi] = o
    # the book's noon chart, built exactly as daily.py builds it
    noon = D.ch["A"]; noon_spots = {S286: P.midpoint(D.pB["Venus"], D.pA["Mars"]),
                                     S187: P.midpoint(D.pA["Venus"], (D.pB["Moon"] + 180) % 360)}
    noon_same = all(objs[720]["pts"][k] == D.pA[k] for k in A.BODY) and spots_by[720] == noon_spots
    cross = edges(orb_mv, mins); moon_edges = edges(orb_mm, mins)
    lb = getattr(D, "luck_branch", None); luck_ok = None
    if lb:
        luck_ok = all(lb(objs[mi], dt.date.fromisoformat(r["luck_start"])) == LUCK_NEXT and
                      lb(objs[mi], dt.date.fromisoformat(r["luck_start"]) - dt.timedelta(days=1)) != LUCK_NEXT
                      for mi, r in zip(mins, rows))
    noon_luck = luck_start(noon)
    # minute-level scan of the angle contacts (ASC moves ~0.25°/min, so a 1° contact lives ~8 minutes)
    ang_min = {}
    for x in range(24 * 60):
        asc = A.angles(t_birth(x), D.CH["A"]["lat"], D.CH["A"]["lon"])[0]
        for c in fam(D.natB, {"ASC": asc, "DSC": (asc + 180) % 360}, "B", "A"):
            ang_min.setdefault(c.rsplit(" ", 1)[0], []).append(x)
    ang_runs = {k: ["%s–%s" % (hm(a), hm(b)) for a, b in _minute_runs(v)] for k, v in sorted(ang_min.items())}
    B_asc_min = min(A.orb(D.pB["ASC"], p, g) for r in rows for p in (objs[r["minute"]]["pts"]["Venus"], objs[r["minute"]]["pts"]["Mars"])
                    for g in (0, 90, 180))

    A.lon = _sky_lon
    try:
        for conv in INST:
            for t in INST[conv]:
                for b in P.PAIR_BODIES: _sky_lon(b, t)
        ref = {conv: chem(noon_spots, conv) for conv in INST}
        sc_tl, win_tl = P.timeline(noon_spots, dt.datetime(WIN0.year, WIN0.month, WIN0.day, tzinfo=D.UTC), NDAYS, V1_UTC_HOUR)
        tl_ok = ([x[2] for x in sc_tl] == ref["v1"]["sc"] and
                 [[(a.date() - WIN0).days, (b.date() - WIN0).days, c] for a, b, c in win_tl] == ref["v1"]["wins"])
        for mi, r in zip(mins, rows):
            r["chem"] = {}
            for conv in INST:
                c = chem(spots_by[mi], conv); r["chem"][conv] = dict(summarize(c), **versus(c, ref[conv]))
    finally:
        A.lon = _sky_lon.__defaults__[0]
    gaps = {conv: sorted(DAYS[i + 1].isoformat() for i in range(NDAYS - 1)
                         if (INST[conv][i + 1] - INST[conv][i]) != dt.timedelta(days=1)) for conv in INST}
    span = lambda ws, conv: {"%s..%s" % (w[0], w[1]) for w in ws if any(w[0] < d <= w[1] for d in gaps[conv])}
    dst_split = {conv: sorted(span(summarize(ref[conv])["windows"], conv).union(*(span(r["chem"][conv]["windows"], conv) for r in rows)))
                 for conv in INST}                     # windows (noon chart or any birth) that cross a non-24 h gap

    rep = build_report(mins, rows, ref, noon_spots, noon_luck, noon_same, cross, moon_edges, luck_ok, tl_ok, ang_runs, B_asc_min,
                       gaps, dst_split)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "birth_time_sweep.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(rep["json"], f, ensure_ascii=False, indent=1); f.write("\n")
    with open(os.path.join(OUT, "birth_time_sweep.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(rep["md"])
    for line in rep["console"]: print(line)
    print("runtime %.1f s" % (time.time() - t_start))


def _minute_runs(v):
    out = []
    for x in sorted(v):
        if out and x == out[-1][1] + 1: out[-1][1] = x
        else: out.append([x, x])
    return out


def build_report(mins, rows, ref, noon_spots, noon_luck, noon_same, cross, moon_edges, luck_ok, tl_ok, ang_runs, B_asc_min,
                 gaps, dst_split):
    ok = lambda b: "✓" if b else "✗"
    cl = []                                                   # (mark, source, claim, measured)
    out_edges = [e for e in cross if e["going"] == "out"]
    cmin = out_edges[0]["minute"] if out_edges else 24 * 60   # first whole minute past 1°
    past = next((r for r in rows if r["minute"] >= cmin), None)
    b1 = [r for r in rows if r["minute"] < cmin]
    b2 = [r for r in rows if cmin <= r["minute"] < DAY_FLIP_MIN]
    b3 = [r for r in rows if r["minute"] >= DAY_FLIP_MIN]
    after = b2 + b3
    mvs, vms = [r["orb_mars_venus"] for r in rows], [r["orb_venus_moon"] for r in rows]
    cnt = lambda xs: ", ".join("%s ×%d" % (k, xs.count(k)) for k in sorted(set(xs), key=str))
    # audit item 14
    cl.append((ok((round(min(mvs), 2), round(max(mvs), 2)) == EXP["mv"]), "audit 14", "A Mars ☌ B Venus runs 0.47°–1.11° over the day",
               "%.2f°–%.2f° (%.4f–%.4f)" % (min(mvs), max(mvs), min(mvs), max(mvs))))
    cd = abs(cmin - int(EXP["audit_cross"][:2]) * 60) if out_edges else None
    cl.append((ok(cd is not None and cd <= TOL["about_min"]), "audit 14", "it passes the 1° family orb after about 20:00 (±%d min)" % TOL["about_min"],
               "first minute past 1°: %s (exact %s)" % (hm(cmin), out_edges[0]["exact"]) if out_edges else "no crossing"))
    nab1, nab2 = [r["n_AB"] for r in b1], [r["n_AB"] for r in after]
    cl.append((ok(set(nab1) == {EXP["fam"][0]} and set(nab2) == {EXP["fam"][1]}), "audit 14",
               "A→B family = 2 before the crossing and drops to 1 after it (so the '2 hits, p = 0.050' claim fails after it)",
               "before: %s · after: %s" % (cnt(nab1), cnt(nab2))))
    cl.append((ok(all(r["spot_286"]["qualifies"] for r in b1) and not any(r["spot_286"]["qualifies"] for r in after)), "audit 14",
               "28.6 Lib is a family hot spot before the crossing and no longer after it",
               "qualifies on %d/%d steps before, %d/%d after" % (sum(r["spot_286"]["qualifies"] for r in b1), len(b1),
                                                                sum(r["spot_286"]["qualifies"] for r in after), len(after))))
    cl.append((ok((round(min(vms), 2), round(max(vms), 2)) == EXP["vm"]), "audit 14", "A Venus ☍ B Moon runs 0.00°–0.67° (robust all day)",
               "%.2f°–%.2f° (%.4f–%.4f); ≤ 1° on %d/144 steps" % (min(vms), max(vms), min(vms), max(vms), sum(v <= FAM_ORB for v in vms))))
    # cover: the line
    cl.append((ok(out_edges and hm(cmin) == EXP["cross"]), "cover", "the Mars–Venus orb passes 1° at 7:45 PM",
               "%s ≤ 1° at %s (%.4f°), > 1° from %s (%.4f°); exact %s; crossings found: %d" %
               (("orb",) + (out_edges[0]["last_minute_before"], out_edges[0]["orb_before"], out_edges[0]["first_minute_after"],
                            out_edges[0]["orb_after"], out_edges[0]["exact"], len(cross))) if out_edges else "no crossing"))
    cl.append((ok(past and past["time"] == EXP["step_past"]), "cover", "the first 10-minute step past it is 19:50",
               "%s (orb %.4f°)" % (past["time"], past["orb_mars_venus"]) if past else "none"))
    # cover band 1
    cl.append((ok(all(r["spot_286"]["qualifies"] and r["spot_187"]["qualifies"] for r in b1)), "cover · before 7:45 PM",
               "both ties hold (28.6 Lib and 18.7 Can)", "both qualify on %d/%d steps (00:00–%s); max orbs %.4f° / %.4f°" %
               (sum(r["spot_286"]["qualifies"] and r["spot_187"]["qualifies"] for r in b1), len(b1), b1[-1]["time"] if b1 else "-",
                max(r["orb_mars_venus"] for r in b1), max(r["orb_venus_moon"] for r in b1))))
    for conv in ("v1", "v2"):
        nw = [r["chem"][conv]["n_windows"] for r in b1]; pk = [r["chem"][conv]["top_day"] for r in b1]
        cl.append((ok(set(nw) == {EXP["windows"]}), "cover · before 7:45 PM [%s]" % conv, "12 chemistry windows stay", "window counts: %s" % cnt(nw)))
        cl.append((ok(set(pk) == {EXP["peak"]}), "cover · before 7:45 PM [%s]" % conv, "the peak stays 2027-05-13", "top days: %s" % cnt(pk)))
        for way, key in (("each run by its own top", "dmax_own"), ("both by the noon run's top", "dmax_noontop")):
            x = max(r["chem"][conv][key] for r in b1); at = max(b1, key=lambda r: r["chem"][conv][key])
            cl.append((ok(round(x, 2) <= EXP["dmax"]), "cover · before 7:45 PM [%s]" % conv,
                       "a day's chemistry moves at most 0.84 from noon (0–10 scale; %s)" % way, "max |Δ| = %.4f (birth %s)" % (x, at["time"])))
        es = [r["chem"][conv]["edge_shift_max_days"] for r in b1]
        mv_steps = sum(1 for r in b1 if r["chem"][conv]["edges_moved"])
        cl.append((ok(None not in es and max(es) <= EXP["edge"]), "cover · before 7:45 PM [%s]" % conv, "a window's edge can shift a day",
                   "max edge shift %s day(s); steps with any edge moved: %d/%d; days whose in-window status changes: max %d" %
                   (max(e for e in es if e is not None) if any(e is not None for e in es) else "n/a", mv_steps, len(b1),
                    max(r["chem"][conv]["days_in_window_changed"] for r in b1))))
    # cover bands 2 and 3
    for name, band in (("7:45–11 PM", b2), ("after 11 PM", b3)):
        cl.append((ok(band and not any(r["spot_286"]["qualifies"] for r in band)), "cover · %s" % name, "the 28.6 Lib tie drops out",
                   "qualifies on %d/%d steps (%s)" % (sum(r["spot_286"]["qualifies"] for r in band), len(band),
                                                      "%s–%s" % (band[0]["time"], band[-1]["time"]) if band else "-")))
        for conv in ("v1", "v2"):
            zr = [v[0] for r in band for v in r["chem"][conv]["zero_days"].values()]
            zs = [v[1] for r in band for v in r["chem"][conv]["zero_days"].values()]
            cl.append((ok(band and max(zr) == 0 and max(zs) == 0.0), "cover · %s [%s]" % (name, conv),
                       "2026-10-27, 2026-12-01, 2027-05-13 fall to chemistry 0.0 (raw 0)", "max raw %s, max scale %s over those 3 days × %d steps" %
                       (max(zr) if zr else "-", max(zs) if zs else "-", len(band))))
            pk = [r["chem"][conv]["top_day"] for r in band]; pw = [tuple(r["chem"][conv]["peak_window"] or ()) for r in band]
            cl.append((ok(band and all(LATE_PEAK[0] <= p <= LATE_PEAK[1] for p in pk)), "cover · %s [%s]" % (name, conv),
                       "2027-09-28..30 becomes the year's peak", "top days: %s · peak windows: %s · window counts: %s" %
                       (cnt(pk), cnt(["%s..%s" % w if w else "none" for w in pw]), cnt([r["chem"][conv]["n_windows"] for r in band]))))
    pil_lo = [r["day_pillar"] for r in rows if r["minute"] < DAY_FLIP_MIN]; pil_hi = [r["day_pillar"] for r in b3]
    cl.append((ok(set(pil_lo) == {EXP["pillars"][0]} and set(pil_hi) == {EXP["pillars"][1]}), "cover · after 11 PM",
               "her BaZi day pillar flips 壬申 → 癸酉 at 23:00", "00:00–22:50: %s · 23:00–23:50: %s" % (cnt(pil_lo), cnt(pil_hi))))
    # cover: luck pillar
    cl.append((ok(noon_luck[0].isoformat() == EXP["luck_noon"]), "cover · luck", "己卯 starts 2027-06-07 for the noon chart",
               "%s (start age %.4f y, exact %s UTC)" % (noon_luck[0].isoformat(), noon_luck[2], noon_luck[1].strftime("%Y-%m-%d %H:%M"))))
    ld = [dt.date.fromisoformat(r["luck_start"]) for r in b1]
    lo_ok = abs((min(ld) - dt.date.fromisoformat(EXP["luck_range"][0])).days) <= TOL["luck_days"]
    hi_ok = abs((max(ld) - dt.date.fromisoformat(EXP["luck_range"][1])).days) <= TOL["luck_days"]
    cl.append((ok(lo_ok and hi_ok), "cover · luck", "for births before 7:45 PM it falls about 2027-04-06 .. 2027-07-16 (±%d days)" % TOL["luck_days"],
               "%s (births %s) .. %s (births %s)" % (min(ld).isoformat(), ", ".join(runs([r["minute"] for r, x in zip(b1, ld) if x == min(ld)])),
                                                     max(ld).isoformat(), ", ".join(runs([r["minute"] for r, x in zip(b1, ld) if x == max(ld)])))))
    xs = [r["minute"] / 60 for r in b1]
    ys = [(dt.datetime.strptime(r["luck_exact_utc"], "%Y-%m-%d %H:%M") - dt.datetime(2027, 1, 1)).total_seconds() / 86400 for r in b1]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    cl.append((ok(abs(slope - EXP["slope"]) <= TOL["slope"]), "cover · luck", "about 5 days per hour of birth time (±%.1f)" % TOL["slope"],
               "%.3f days/hour (least squares on the exact start instant, %d steps)" % (slope, len(b1))))
    # cover: Moon
    mm_in = [r["minute"] for r in rows if r["orb_moon_mars"] <= FAM_ORB]
    mr = runs(mm_in)
    cl.append((ok(mr == ["%s–%s" % EXP["moon"]]), "cover · Moon", "B Mars ☍ A Moon ≤ 1° for births 07:40–10:50",
               "10-min steps: %s; to the minute: %s; min orb at the 10-min steps %.4f°" % (", ".join(mr) or "none",
                                                                     "; ".join("%s %s (exact %s)" % ("in from" if e["going"] == "in" else "out from",
                                                                               e["first_minute_after"], e["exact"]) for e in moon_edges) or "none",
                                                                     min(r["orb_moon_mars"] for r in rows))))
    new_moon = {}
    for r in rows:
        base = {x.rsplit(" ", 1)[0] for x in r["fam_BA"]["book"]}
        for x in r["fam_BA"]["moon"]:
            k = x.rsplit(" ", 1)[0]
            if k not in base: new_moon.setdefault(k, []).append(r["minute"])
    cl.append((ok(list(new_moon) == ["B Mars ☍ A Moon"]), "cover · Moon", "the Moon adds one family tie (a third tie): B Mars ☍ A Moon",
               "; ".join("%s at %s" % (k, ", ".join(runs(v))) for k, v in sorted(new_moon.items())) or "none"))
    holds = bool(out_edges) and hm(cmin) == EXP["cross"]
    # ---------- JSON ----------
    noon_chem = {conv: summarize(ref[conv]) for conv in INST}
    js = dict(
        tool="birth_time_sweep.py", report_only=True,
        method=dict(birth="A born 1980-08-27 %s, 00:00..23:50 every %d min (144 steps); A = daily.build(dict(CH['A'], hm=(h, m)))" % (TZ, STEP_MIN),
                    book_convention="A's bodies without Moon and without angles (measured on her noon chart; the book's default is time-free A)",
                    family="pair_core.attraction_family, orb %.1f°; A→B = (chart_b=A, chart_a=daily.natB); B→A = (chart_b=daily.natB, chart_a=A)" % FAM_ORB,
                    window="%s .. %s (%d days)" % (DAYS[0], DAYS[-1], NDAYS), headline=HEAD,
                    windows="runs of consecutive calendar days with P ≥ %.0f%% of the run's top (pair_core.timeline's rule)" % (WIN_FRAC * 100),
                    luck="first day X with (X 12:00 UTC − birth UTC)/%s d ≥ start age of %s" % (YEAR, LUCK_NEXT),
                    checks=dict(step_1200_equals_book_noon_chart=noon_same, v1_windows_match_pair_core_timeline=tl_ok,
                                luck_start_matches_daily_luck_branch=luck_ok,
                                min_orb_A_venus_mars_to_B_ASC_0_90_180=round(B_asc_min, 4)),
                    dst=dict(days_after_a_non_24h_gap=gaps, noon_windows_spanning_such_a_gap=dst_split)),
        expected=EXP, tolerance=TOL,
        claims=[dict(mark=m, source=s, claim=c, measured=x) for m, s, c, x in cl],
        holds_for_births_before=hm(cmin) if out_edges else None,
        crossing_mars_venus=cross, moon_mars_edges=moon_edges,
        moon_new_family=dict(sorted((k, runs(v)) for k, v in new_moon.items())),
        angles_new_family_minute_scan=ang_runs,
        noon=dict(orb_mars_venus=round(A.orb(D.pA["Mars"], D.pB["Venus"], 0), 4), orb_venus_moon=round(A.orb(D.pA["Venus"], D.pB["Moon"], 180), 4),
                  fam_AB=fam(D.natA, D.natB, "A", "B"), fam_BA=fam(D.natB, D.natA, "B", "A"),
                  spots={k: A.fmt(v) for k, v in noon_spots.items()}, day_pillar=Z.pillar_name(Z.day_index(*BDAY)),
                  luck_start=noon_luck[0].isoformat(), chem=noon_chem),
        steps=[{k: v for k, v in r.items() if k != "minute"} for r in rows])
    # ---------- Markdown ----------
    L = ["# A's birth time — sweep (audit item 14 + the cover's \"A's birth time\")", "",
         "REPORT ONLY. The sweep measures against A's noon chart; the book's default is time-free A (THE_MATH §14), and no birth time is added to the data. "
         "Made by `python3 birth_time_sweep.py` (deterministic: same files every run).", ""]
    if holds: L += ["**Holds for births before 7:45 PM.** (A Mars ☌ B Venus is ≤ 1° up to %s and > 1° from %s.)" %
                    (out_edges[0]["last_minute_before"], out_edges[0]["first_minute_after"]), ""]
    else: L += ["**The 7:45 PM line is NOT confirmed:** measured first minute past 1° = %s." % (hm(cmin) if out_edges else "none"), ""]
    L += ["## Summary", "", "| | source | claim | measured |", "|---|---|---|---|"]
    L += ["| %s | %s | %s | %s |" % tuple(x.replace("|", "\\|") for x in c) for c in cl]
    n1, n2 = noon_chem["v1"], noon_chem["v2"]
    L += ["", "## The book's noon chart (the reference every Δ is measured against)", "",
          "- A Mars ☌ B Venus %.4f° · A Venus ☍ B Moon %.4f° · spots %s · day pillar %s · 己卯 starts %s" %
          (js["noon"]["orb_mars_venus"], js["noon"]["orb_venus_moon"], " + ".join(js["noon"]["spots"].values()), js["noon"]["day_pillar"], js["noon"]["luck_start"]),
          "- A→B: %s · B→A: %s" % ("; ".join(js["noon"]["fam_AB"]), "; ".join(js["noon"]["fam_BA"])),
          "- chemistry v2 (%s): top %s raw %.4f · %d windows" % (HEAD["v2"], n2["top_day"], n2["top_raw"], n2["n_windows"]),
          "- chemistry v1 (%s): top %s raw %.4f · %d windows" % (HEAD["v1"], n1["top_day"], n1["top_raw"], n1["n_windows"]),
          "- v2 windows: " + ", ".join("%s..%s (%s)" % tuple(w) for w in n2["windows"]),
          "- v1 windows: " + ", ".join("%s..%s (%s)" % tuple(w) for w in n1["windows"]),
          "", "## If her time were known (extras, not in the book)", "",
          "- B→A with her Moon: " + ("; ".join("%s at %s" % (k, ", ".join(v)) for k, v in js["moon_new_family"].items()) or "nothing new"),
          "- B→A with her ASC/DSC (1-minute scan; ASC moves about 0.25°/min): " +
          ("; ".join("%s at %s" % (k, ", ".join(v)) for k, v in ang_runs.items()) or "nothing"),
          "- A→B reads only A's Venus and Mars, so neither extra can change it. `daily.natB` has B's ASC but no DSC; "
          "for ☌ □ ☍ a DSC contact is the mirror of an ASC contact, and A's Venus/Mars never come within %.2f° of ☌□☍ B's ASC." % B_asc_min,
          "", "## All 144 births", "",
          "Orbs in degrees. A→B / B→A = family counts (B→A shown as book / +Moon / +ASC,DSC). A tie to her ASC is always also a tie to "
          "her DSC (☌ ↔ ☍, □ ↔ □), so `pair_core.attraction_family` counts each angle tie twice. max|Δ| = v2, each run by its own top. "
          "Peak = the run's top day.", "",
          "| birth | Mars☌Venus | Venus☍Moon | A→B | B→A | 28.6 Lib | spot | win v2 | peak v2 | max\\|Δ\\| v2 | win v1 | peak v1 | day | 己卯 starts | Moon☍Mars |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        c2, c1 = r["chem"]["v2"], r["chem"]["v1"]
        L.append("| %s | %.3f | %.2f | %d | %d / %d / %d | %s | %s | %d | %s | %.2f | %d | %s | %s | %s | %.2f |" %
                 (r["time"], r["orb_mars_venus"], r["orb_venus_moon"], r["n_AB"], r["n_BA"]["book"], r["n_BA"]["moon"], r["n_BA"]["angles"],
                  "yes" if r["spot_286"]["qualifies"] else "no", r["spot_286"]["fmt"], c2["n_windows"], c2["top_day"], c2["dmax_own"],
                  c1["n_windows"], c1["top_day"], r["day_pillar"], r["luck_start"], r["orb_moon_mars"]))
    L += ["", "## Method notes", "",
          "- Births: 1980-08-27 %s (Huntington, IN: %.4f, %.4f), 00:00..23:50 every %d minutes; each A = `daily.build(dict(CH['A'], hm=(h, m)))`. "
          "Indianapolis kept standard time all year in 1980, so every step is a real, unique instant." % (TZ, D.CH["A"]["lat"], D.CH["A"]["lon"], STEP_MIN),
          "- Book convention = A's bodies without Moon and without angles (the noon chart's rule). The 12:00 step equals the book's noon chart: %s." % ("yes" if noon_same else "NO"),
          "- Family: `pair_core.attraction_family`, 1° orb, ☌ □ ☍. A→B = A's Venus/Mars to B's points (`chart_b=A, chart_a=daily.natB`); B→A = B's Venus/Mars to A's.",
          "- 28.6 Lib = midpoint(B Venus, A Mars) counts as a hot spot only while that ☌ is ≤ 1°; 18.7 Can = midpoint(A Venus, B Moon + 180) only while that ☍ is ≤ 1°. "
          "Chemistry at each birth uses only the spots that qualify there.",
          "- Crossing: the 10-minute steps are bisected to the whole minute (\"first minute past 1°\") and then to the second (\"exact\").",
          "- Chemistry: P = `pair_core.pair_score(spots, t)` for each of the %d days %s .. %s. v2 headline = %s; v1 headline = %s. "
          "Scale = P / the run's top × 10 (shown rounded half up to 0.1, as `pair_core.timeline` does; every Δ is unrounded); "
          "windows = runs of consecutive calendar days with P ≥ 50%% of the run's top. "
          "Each day's sky longitudes are computed once (a memo around `astro_core.lon`) because the sky does not depend on A's birth time. "
          "v1 windows match `pair_core.timeline` on the noon chart: %s." % (NDAYS, DAYS[0], DAYS[-1], HEAD["v2"], HEAD["v1"], "yes" if tl_ok else "NO"),
          "- max|Δ| = max over the 365 days of |scale(birth) − scale(noon)|, unrounded: (i) each run divided by its own top, (ii) both divided by the noon run's top. "
          "Edge shift = the largest move of a window's start or end, in days, when the window count matches noon (n/a otherwise).",
          "- v2 note: local noon is 23 h or 25 h after the previous local noon across a DST change (%s). Windows here join consecutive calendar days. "
          "`pair_core.timeline`'s own test `(t − prev).days == 1` would split a window at a 23 h gap; v2 windows that span such a gap "
          "(noon chart and all 144 births): %s." % (", ".join(gaps["v2"]) or "none", ", ".join(dst_split["v2"]) or "none"),
          "- Luck: 己卯 (the pillar after 庚辰) starts on the first day X with (X 12:00 UTC − birth UTC) / %s d ≥ its start age (from `build`'s lucks). "
          "Matches `daily.luck_branch` on the start day and the day before at all 144 steps: %s. Slope = least squares of the exact start instant on birth hour, births before the crossing." %
          (YEAR, {True: "yes", False: "NO", None: "not checked (daily.luck_branch missing)"}[luck_ok]),
          "- Day pillar: `bazi_core.day_index(1980, 8, 27, h + m/60)`; the BaZi day turns at 23:00.",
          "- \"About\" in the briefs is judged as: ±%d min for a time, ±%d days for a date, ±%.1f day/hour for the slope. No number was tuned to match a brief." %
          (TOL["about_min"], TOL["luck_days"], TOL["slope"]), ""]
    con = ["%s %s | %s | %s" % c for c in cl]
    return dict(json=js, md="\n".join(L), console=con)


if __name__ == "__main__":
    main()
