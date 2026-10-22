"""Forbidden love: one day's math for A and B (and A with C), from Khai's pure_math pack.
Usage:  python3 daily.py YYYY-MM-DD      (a local Frederick, MD date)
Prints JSON. Same rules as the book's Chart work tab:
  * A and C have no birth time: noon charts, Moon left out of radar, A's attraction score is PARTIAL
    (no ASC/DSC axis term, Moon bonus = Libra only, door kept).
  * Year and month pillars: STD (year turns at the Sun's 315 degrees, months at each jie, month stem by wu hu dun).
  * Flags, pull scale and chemistry scale are relative to a 365-day reference window that starts on
    Oct 20, 2026 (and on each Oct 20 after it).
"""
import sys, os, json, datetime as dt
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "pure_math", "code"))
import astro_core as A, bazi_core as Z, radar_core as R, attraction_core as T, pair_core as P

UTC = dt.timezone.utc; NY = ZoneInfo("America/New_York"); YEAR = 365.2425
LAT, LON = 39.4143, -77.4105                      # Frederick, MD: where A and B live and work
BODIES = list(A.BODY)
CH = {
    "A": dict(sex="F", y=1980, m=8, d=27, hm=None, tz="America/Indiana/Indianapolis", lat=40.8831, lon=-85.4975),
    "B": dict(sex="M", y=1989, m=9, d=11, hm=(6, 10), tz="Asia/Yangon", lat=16.8409, lon=96.1735),
    "C": dict(sex="M", y=1977, m=2, d=14, hm=None, tz="America/Indiana/Indianapolis", lat=40.8831, lon=-85.4975),
}


def loc(y, m, d, h=0, mi=0, tz="America/New_York"):
    return dt.datetime(y, m, d, h, mi, tzinfo=ZoneInfo(tz))


def build(c):
    h, mi = c["hm"] if c["hm"] else (12, 0)
    tu = loc(c["y"], c["m"], c["d"], h, mi, c["tz"]).astimezone(UTC)
    pts = {b: A.lon(b, tu) for b in BODIES}
    if c["hm"]:
        asc, mc = A.angles(tu, c["lat"], c["lon"]); pts.update(ASC=asc, MC=mc)
    sun = pts["Sun"]
    lichun = A.roots(lambda t: A.sep(A.lon("Sun", t), 315.0), dt.datetime(c["y"], 1, 20, tzinfo=UTC),
                     dt.datetime(c["y"], 2, 25, tzinfo=UTC), step_min=720)[0]
    sy = c["y"] if tu >= lichun else c["y"] - 1; g_year = (sy - 4) % 60
    mi_idx = int(((sun - 315.0) % 360) // 30); m_branch = (2 + mi_idx) % 12
    m_stem = (2 * ((g_year % 10) % 5) + 2 + mi_idx) % 10
    g_month = next(g for g in range(60) if g % 10 == m_stem and g % 12 == m_branch)
    g_day = Z.day_index(c["y"], c["m"], c["d"], h + mi / 60)
    prev_t, next_t = (315.0 + 30 * mi_idx) % 360, (315.0 + 30 * (mi_idx + 1)) % 360
    t_prev = A.roots(lambda t: A.sep(A.lon("Sun", t), prev_t), tu - dt.timedelta(days=40), tu, step_min=360)[-1]
    t_next = A.roots(lambda t: A.sep(A.lon("Sun", t), next_t), tu, tu + dt.timedelta(days=40), step_min=360)[0]
    fwd = Z.luck_forward(c["sex"] == "M", Z.STEMS[g_year % 10])
    start = Z.luck_start_years(((t_next - tu) if fwd else (tu - t_prev)).total_seconds() / 86400)
    lucks = [(start + 10 * (k - 1), Z.pillar_name(Z.luck_pillar(g_month, k, fwd))) for k in range(1, 10)]
    pil = [Z.pillar_name(g_year), Z.pillar_name(g_month), Z.pillar_name(g_day)]
    br = [p[1] for p in pil] + ([Z.hour_branch(h + mi / 60)] if c["hm"] else [])
    return dict(t=tu, pts=pts, dm=pil[2][0], year_branch=pil[0][1], branches=sorted(set(br)), lucks=lucks)


def luck_branch(o, day):
    age = ((dt.datetime(day.year, day.month, day.day, 12, tzinfo=UTC) - o["t"]).total_seconds() / 86400) / YEAR
    cur = None
    for a0, name in o["lucks"]:
        if a0 <= age < a0 + 10: cur = name
    return cur


ch = {k: build(c) for k, c in CH.items()}
pA, pB, pC = ch["A"]["pts"], ch["B"]["pts"], ch["C"]["pts"]
natA = {k: v for k, v in pA.items() if k != "Moon"}
natB = dict(pB)
spots = {"28.6 Lib (B Venus ☌ A Mars)": P.midpoint(pB["Venus"], pA["Mars"]),
         "18.7 Can (A Venus ☍ B Moon, axis)": P.midpoint(pA["Venus"], (pB["Moon"] + 180) % 360)}


def moment_A(t, Pm=T.PARAMS):
    tot = 0.0
    for body, bw in Pm["body_w"].items():
        l = A.lon(body, t)
        for tg in T.SINGLE: tot += bw * Pm["target_w"][tg] * T._contact(l, pA[tg], body, Pm)
        if body == "Moon" and int(l // 30) == 6: tot += Pm["moon_sign_bonus"]
    if A.distance(A.angles(t, LAT, LON)[0], pA["Venus"]) <= Pm["door_orb"]: tot += Pm["door_bump"]
    return tot


def samples(day, who):
    d0 = loc(day.year, day.month, day.day)
    f = (lambda t: moment_A(t)) if who == "A" else (lambda t: T.moment(natB, t, LAT, LON))
    return [f((d0 + dt.timedelta(minutes=10 * i)).astimezone(UTC)) for i in range(144)]


def window_for(day):
    start = dt.date(2026, 10, 20)
    while day >= start + dt.timedelta(days=365): start += dt.timedelta(days=365)
    return start


def reference(start):
    cache = os.path.join(HERE, "ref_%s.json" % start.isoformat())
    if os.path.exists(cache): return json.load(open(cache))
    days = [start + dt.timedelta(days=i) for i in range(365)]
    out = {}
    for who in ("A", "B"):
        vals = sorted((sum(samples(d, who)) / 144 for d in days), reverse=True)
        out[who] = dict(top=vals[0], fire=vals[25], ok=vals[72])
    t0 = dt.datetime(start.year, start.month, start.day, tzinfo=UTC)
    out["pair_top"] = max(s for _, s, _ in P.timeline(spots, t0, 365)[0])
    json.dump(out, open(cache, "w")); return out


def main(day):
    ref = reference(window_for(day))
    g = Z.day_index(day.year, day.month, day.day); ds, db = Z.STEMS[g % 10], Z.BRANCHES[g % 12]
    res = dict(date=day.isoformat(), weekday=day.strftime("%A"), pillar=Z.pillar_name(g), window_start=window_for(day).isoformat())
    noon = loc(day.year, day.month, day.day, 12).astimezone(UTC)
    s, why = P.pair_score(spots, dt.datetime(day.year, day.month, day.day, 16, tzinfo=UTC))
    res["chemistry"] = dict(scale=round(s / ref["pair_top"] * 10, 1), raw=round(s, 2), lit_by=[(b, ang, nm, o) for v, b, ang, nm, o in why[:3]])
    vals = {who: samples(day, who) for who in ("A", "B")}
    for who, other_key in (("A", "B"), ("B", "A")):
        o, oth = ch[who], ch[other_key]
        mean = sum(vals[who]) / 144; r = ref[who]
        flag = "🔥" if mean >= r["fire"] else "✅" if mean >= r["ok"] else ""; scale = round(mean / r["top"] * 10, 1)
        lb = luck_branch(o, day); own = o["branches"] + ([lb[1]] if lb else []); other = oth["branches"]
        nat = natA if who == "A" else natB
        stp, _ = R.saturn_station(nat, noon)
        raw, sc, parts = Z.day_score(ds, db, own, other, o["dm"], o["year_branch"], T.daily_points(flag, scale), stp)
        hours = []
        for i, hb in enumerate(Z.BRANCHES):
            H, hp = Z.hour_score(hb, db, own, other, o["year_branch"])
            idx = list(range(0, 6)) if i == 0 else list(range((2 * i - 1) * 6, (2 * i + 1) * 6))
            lab = "00:00-00:59 (+23:00 the night before)" if i == 0 else "%02d:00-%02d:59" % (2 * i - 1, 2 * i)
            hours.append(dict(block=hb, hours=lab, charge=H, pull=round(sum(vals[who][j] for j in idx) / len(idx) / r["top"] * 10, 1),
                              terms=[n for n, _ in hp]))
        d0 = loc(day.year, day.month, day.day).astimezone(UTC); d1 = d0 + dt.timedelta(days=1)
        H = R.hits(nat, noon); tone, how = R.tone(H)
        res[who] = dict(charge=sc, tier=Z.tier(sc), raw=raw, parts=parts, luck=lb, pull=scale, flag=flag,
                        tone=(dict(tone) if tone else None, how),
                        exact=[f"{h['body']} {h['aspect']} {h['point']} {h['orb']}° {h['flavor']} {h['tag']}" for h in H if h["phase"] == "exact"],
                        hours=hours,
                        moon_times=[(x.astimezone(NY).strftime("%H:%M"), a, p, f, tg) for x, a, p, f, tg in
                                    R.moon_times({k: v for k, v in nat.items() if k != "MC"}, d0, d1)],
                        door=[x.astimezone(NY).strftime("%H:%M") for x, p, ang, dr in
                              R.angle_crossings({"Venus": nat["Venus"]}, d0, d1, LAT, LON) if dr])
    lbA = luck_branch(ch["A"], day)
    rawc, scc, partsc = Z.day_score(ds, db, ch["A"]["branches"] + ([lbA[1]] if lbA else []), ch["C"]["branches"], ch["A"]["dm"],
                                    ch["A"]["year_branch"], T.daily_points(res["A"]["flag"], res["A"]["pull"]), 0)
    res["A_with_C"] = dict(charge=scc, tier=Z.tier(scc), parts=partsc)
    res["receipt"] = ("Math: %s · chemistry %s · A charge %s %s, pull %s%s · B charge %s %s, pull %s%s" %
                      (res["pillar"], res["chemistry"]["scale"], res["A"]["charge"], res["A"]["tier"], res["A"]["pull"], res["A"]["flag"],
                       res["B"]["charge"], res["B"]["tier"], res["B"]["pull"], res["B"]["flag"]))
    return res


if __name__ == "__main__":
    day = dt.date.fromisoformat(sys.argv[1])
    print(json.dumps(main(day), ensure_ascii=False, indent=1))
