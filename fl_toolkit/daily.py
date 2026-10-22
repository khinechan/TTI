"""Forbidden love: one day's math for A and B (and A with C), from Khai's pure_math pack.
Usage:  python3 daily.py YYYY-MM-DD [options]      (a local Frederick, MD date)
Prints JSON. Same rules as the book's Chart work tab:
  * A and C have no birth time. A is time-free by default (v2, THE_MATH §14: the mean of her 119 possible charts);
    --a-time noon gives the v1 noon stand-in. C is a noon chart (no book number depends on his time). Moon left out of
    A's radar; A's attraction score is PARTIAL (no ASC/DSC axis term, Moon bonus = Libra only, door kept).
  * Year and month pillars: STD (year turns at the Sun's 315 degrees, months at each jie, month stem by wu hu dun).
  * Flags, pull scale and chemistry scale are relative to a 365-day reference window that starts on
    Oct 20, 2026 (and on each Oct 20 after it).
  * v2 (CHANGES.md): pull samples the BaZi day, 23:00 the evening before to 22:50, on local wall-clock time (a DST gap
    is skipped, a repeated hour is sampled at both instants, ½ weight each); chemistry is read at local noon and capped
    at 10; every score rounds half up. New keys only add; the old keys keep their meaning.
Options (all off by default; with none of them the output is the v2 default):
  --luck-repeat-weight W   a luck branch that repeats a natal branch counts W (default 1.0, as in DAILY v0.1)
  --year-month-terms       STD: today's 流年 / 流月 branches join the §7 "other" set at half weight
  --solar-time             STD: hour-block edges on true solar time at Frederick (block pulls and labels only)
  --a-time noon|tf         A's chart: tf = time-free, the mean of her 119 possible charts 00:00-19:40 (Khai's call:
                           born before 7:45 PM); noon = the v1 noon stand-in, kept for comparison
  --outfit-A JSON, --outfit-B JSON, --seen 辰,巳,午,未,申
                           §13 outfit color (STD): an outfit acts on its wearer's charge and on the other person's
                           pull in the seen blocks; the JSON gains an "outfit" key only when an outfit is passed
"""
import sys, os, json, math, argparse, datetime as dt
from bisect import bisect_left, bisect_right
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "pure_math", "code"))
import astro_core as A, bazi_core as Z, radar_core as R, attraction_core as T, pair_core as P, monthly_core as M
import color_core as C

UTC = dt.timezone.utc; NY = ZoneInfo("America/New_York"); YEAR = 365.2425
LAT, LON = 39.4143, -77.4105                      # Frederick, MD: where A and B live and work
BODIES = list(A.BODY)
CH = {
    "A": dict(sex="F", y=1980, m=8, d=27, hm=None, tz="America/Indiana/Indianapolis", lat=40.8831, lon=-85.4975),
    "B": dict(sex="M", y=1989, m=9, d=11, hm=(6, 10), tz="Asia/Yangon", lat=16.8409, lon=96.1735),
    "C": dict(sex="M", y=1977, m=2, d=14, hm=None, tz="America/Indiana/Indianapolis", lat=40.8831, lon=-85.4975),
}
STEP_MIN = 10                         # pull: one sample every 10 minutes of local wall-clock time
DAY_START_MIN = -60                   # the BaZi day starts at 23:00 the evening before (§3): −60 min from midnight
BLOCK_MIN = 120                       # an hour branch is a two-hour block (子 = 23:00–00:59 … 亥 = 21:00–22:59)
CHEM_CAP = 10.0                       # the chemistry scale stops at 10; raw is always printed
REF_V = 3                             # reference-cache format; an older cache is rebuilt (v1: calendar-day sampling,
                                      # v2: time-free chemistry summed 3-dp terms instead of the exact mean)
LONGRUN = (dt.date(2020, 1, 1), dt.date(2040, 12, 31))   # fixed long-run reference: pull hourly, chemistry at noon
PCT_TIERS = ((0.90, "🔴"), (0.75, "🟠"), (0.50, "🟡"))   # tier_pct: cut → tier; below the last cut → 🟢
YM_WEIGHT = 0.5                       # --year-month-terms: 流年 and 流月 count half (STD)
TF_STEP_MIN, TF_N = 10, 119           # time-free A: one chart every 10 min, 00:00 … 19:40 local on her birth date
DEFAULT_OPT = dict(luck_w=1.0, ym=False, solar=False, a_time="tf")
rhu = Z.round_half_up


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
    hour = Z.hour_pillar(pil[2][0], br[3]) if c["hm"] else None
    return dict(t=tu, pts=pts, dm=pil[2][0], year_branch=pil[0][1], branches=sorted(set(br)), lucks=lucks,
                pillars=pil + [hour], jie=(t_prev, t_next), fwd=fwd)


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


def moment_A(t, Pm=T.PARAMS, pts=None):
    pts = pts or pA; tot = 0.0
    for body, bw in Pm["body_w"].items():
        l = A.lon(body, t)
        for tg in T.SINGLE: tot += bw * Pm["target_w"][tg] * T._contact(l, pts[tg], body, Pm)
        if body == "Moon" and int(l // 30) == 6: tot += Pm["moon_sign_bonus"]
    if A.distance(A.angles(t, LAT, LON)[0], pts["Venus"]) <= Pm["door_orb"]: tot += Pm["door_bump"]
    return tot


# ---------- time-free A: her 119 possible charts (Khai's call: born before 7:45 PM; no time is ever pinned) ----------
def circ_mean(lons):
    """Circular mean of longitudes: atan2(Σ sin λ, Σ cos λ)."""
    return math.degrees(math.atan2(sum(math.sin(math.radians(l)) for l in lons),
                                   sum(math.cos(math.radians(l)) for l in lons))) % 360.0


class PointSet:
    """One natal point over A's 119 charts, unwrapped around its circular mean and sorted, with prefix sums, so the mean
       §9 contact over all charts is exact: Σ_k max(0, 1 − |u_k − c|/orb) in O(log n) by bisection."""

    def __init__(self, lons):
        self.mu = circ_mean(lons); self.n = len(lons)
        self.u = sorted(self.mu + A.sep(l, self.mu) for l in lons); self.pre = [0.0]
        for x in self.u: self.pre.append(self.pre[-1] + x)

    def _at(self, c):
        return self.mu + A.sep(c % 360.0, self.mu)

    def tent(self, c, ob):
        """mean over k of max(0, 1 − |λ_k − c| / ob)."""
        c = self._at(c); u, pre = self.u, self.pre
        i0, i1, i2 = bisect_left(u, c - ob), bisect_right(u, c), bisect_right(u, c + ob)
        nl, nr = i1 - i0, i2 - i1
        return (nl - (nl * c - (pre[i1] - pre[i0])) / ob + nr - ((pre[i2] - pre[i1]) - nr * c) / ob) / self.n

    def share_within(self, c, r):
        c = self._at(c); return (bisect_right(self.u, c + r) - bisect_left(self.u, c - r)) / self.n


def contact_mean(l, ps, ob, Pm):
    """Mean over the charts of §9's c(b, n) = max over aspects of F·(1 − o/orb). With orbs ≤ 3° no two aspects (≥ 30°
       apart) are in orb at once, so the max is a sum of tents centred on λ_b ± A."""
    return sum(Pm["aspect_f"][a] * ps.tent(l + sg * ang, ob)
               for a, ang in A.ASPECTS.items() for sg in ((1,) if ang in (0, 180) else (1, -1)))


_TF = {}


def tf():
    """Time-free A: the 119 charts 00:00 … 19:40 local (America/Indiana/Indianapolis). Each keeps its own body
       longitudes and its own luck-pillar start; her pillars, luck names and the jie the start counts from are the
       noon chart's (asserted: no jie and no 23:00 day flip inside the window). No Moon, ASC or hour pillar (PARTIAL).
       avg = the averaged chart (circular mean of each planet) for exact transits, the door and the Saturn station."""
    if _TF: return _TF
    c, o = CH["A"], ch["A"]; charts = []
    for k in range(TF_N):
        h, mi = divmod(TF_STEP_MIN * k, 60)
        tu = loc(c["y"], c["m"], c["d"], h, mi, c["tz"]).astimezone(UTC)
        assert o["jie"][0] <= tu < o["jie"][1] and Z.day_index(c["y"], c["m"], c["d"], h + mi / 60) == \
            Z.day_index(c["y"], c["m"], c["d"])
        start = Z.luck_start_years(((o["jie"][1] - tu) if o["fwd"] else (tu - o["jie"][0])).total_seconds() / 86400)
        charts.append(dict(t=tu, pts={b: A.lon(b, tu) for b in BODIES if b != "Moon"},
                           lucks=[(start + 10 * j, name) for j, (_, name) in enumerate(o["lucks"])]))
    avg = {b: circ_mean([x["pts"][b] for x in charts]) for b in charts[0]["pts"]}
    _TF.update(charts=charts, avg=avg, sets={tg: PointSet([x["pts"][tg] for x in charts]) for tg in T.SINGLE},
               spots=[{"28.6 Lib (B Venus ☌ A Mars)": P.midpoint(pB["Venus"], x["pts"]["Mars"]),
                       "18.7 Can (A Venus ☍ B Moon, axis)": P.midpoint(x["pts"]["Venus"], (pB["Moon"] + 180) % 360)}
                      for x in charts])
    return _TF


def moment_A_tf(t, Pm=T.PARAMS):
    """M(t) for time-free A = the mean of moment_A over her 119 charts, computed exactly from the sorted point sets."""
    sets = tf()["sets"]; tot = 0.0
    for body, bw in Pm["body_w"].items():
        l = A.lon(body, t)
        for tg in T.SINGLE: tot += bw * Pm["target_w"][tg] * contact_mean(l, sets[tg], Pm["orb"][body], Pm)
        if body == "Moon" and int(l // 30) == 6: tot += Pm["moon_sign_bonus"]
    return tot + Pm["door_bump"] * sets["Venus"].share_within(A.angles(t, LAT, LON)[0], Pm["door_orb"])


def chem(t, a_time):
    """§10 pair score at t: (raw, why). Time-free: the mean over A's 119 charts' hot spots, and why = each
       (body, aspect, spot)'s mean contribution with its orb on the averaged chart's spots."""
    if a_time == "noon": return P.pair_score(spots, t)
    acc = {}; tot = 0.0
    for sp in tf()["spots"]:
        s, why = P.pair_score(sp, t); tot += s                     # the exact mean comes from the unrounded totals;
        for v, b, ang, nm, o in why: acc[(b, ang, nm)] = acc.get((b, ang, nm), 0.0) + v   # why's terms are 3-dp, display only
    avg = tf()["avg"]
    sp = {"28.6 Lib (B Venus ☌ A Mars)": P.midpoint(pB["Venus"], avg["Mars"]),
          "18.7 Can (A Venus ☍ B Moon, axis)": P.midpoint(avg["Venus"], (pB["Moon"] + 180) % 360)}
    lon = {b: A.lon(b, t) for b in {k[0] for k in acc}}
    why = [(round(v / TF_N, 3), b, ang, nm, round(abs(A.distance(lon[b], sp[nm]) - ang), 2)) for (b, ang, nm), v in acc.items()]
    return tot / TF_N, sorted(why, reverse=True)


def noon(day):
    return loc(day.year, day.month, day.day, 12).astimezone(UTC)


def wall_grid(day, step_min=STEP_MIN, start_min=DAY_START_MIN, n=None):
    """The day's sample instants: local wall-clock slots every step_min, from start_min minutes after local midnight
       (−60 = 23:00 the evening before, the BaZi day), n slots (default 24 h). DST: a wall time that does not exist
       (spring forward) is skipped; a wall time that happens twice (fall back) is sampled at both instants, ½ weight
       each. → [(utc instant, weight, slot)]"""
    w0 = dt.datetime(day.year, day.month, day.day) + dt.timedelta(minutes=start_min); out = []
    for k in range(n or 1440 // step_min):
        w = w0 + dt.timedelta(minutes=step_min * k)
        u0, u1 = (w.replace(tzinfo=NY, fold=f).astimezone(UTC) for f in (0, 1))
        if u0.astimezone(NY).replace(tzinfo=None) != w: continue
        out += [(u0, 1.0, k)] if u0 == u1 else [(u0, 0.5, k), (u1, 0.5, k)]
    return out


def solar_grid(day, step_min=STEP_MIN):
    """--solar-time: the same 144 slots on true (apparent) solar time at Frederick. The instant of solar time τ is
       UTC = τ − LON/15 h − EoT (EoT at local noon; it moves < 30 s in a day). Solar time never jumps, so no DST rule."""
    w0 = dt.datetime(day.year, day.month, day.day, tzinfo=UTC) + dt.timedelta(
        minutes=DAY_START_MIN - LON * 4 - A.equation_of_time(noon(day)))
    return [(w0 + dt.timedelta(minutes=step_min * k), 1.0, k) for k in range(1440 // step_min)]


def block_of(slot, step_min=STEP_MIN, start_min=DAY_START_MIN):
    """Hour-branch index of a slot: minutes since 23:00 // 120, so 子 = slots 0–11 (23:00–00:50), 丑 = 12–23, …"""
    return ((start_min + 60 + slot * step_min) // BLOCK_MIN) % 12


def samples(day, who, grid=None, a_time="noon"):
    """[(moment score M, weight, slot)] over the BaZi day's grid (§9). Time-free A: M averaged over her 119 charts."""
    f = (moment_A_tf if a_time == "tf" else (lambda t: moment_A(t))) if who == "A" else (lambda t: T.moment(natB, t, LAT, LON))
    return [(f(u), w, k) for u, w, k in (grid or wall_grid(day))]


def wmean(rows, keep=None):
    """Weighted mean Σ w·M / Σ w over the rows whose slot passes keep (None if there are none)."""
    rows = [r for r in rows if keep is None or keep(r[2])]
    den = sum(w for _, w, _ in rows)
    return sum(v * w for v, w, _ in rows) / den if den else None


def window_for(day):
    start = dt.date(2026, 10, 20)
    while day >= start + dt.timedelta(days=365): start += dt.timedelta(days=365)
    return start


def _write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh: json.dump(obj, fh)
    os.replace(tmp, path)


def nat_of(who, a_time):
    """The natal points radar, Moon times, the door and the Saturn station read: A's averaged chart when time-free."""
    return natB if who == "B" else (tf()["avg"] if a_time == "tf" else natA)


_LOADED = {}


def _cached(name, a_time, build_fn):
    """A reference cache: read it (once per process) if it is the current format for this A-chart mode, else build and
       write it. A v1 cache (no "v") or the other mode's file is never trusted."""
    cache = os.path.join(HERE, name + ("_tf" if a_time == "tf" else "") + ".json")
    if cache in _LOADED: return _LOADED[cache]
    if os.path.exists(cache):
        with open(cache, encoding="utf-8") as fh: ref = json.load(fh)
        if ref.get("v") == REF_V and ref.get("a_time", "noon") == a_time:
            _LOADED[cache] = ref; return ref
    out = build_fn(); out["a_time"] = a_time
    _write(cache, out); _LOADED[cache] = out; return out


def reference(start, a_time="noon"):
    """The window's reference, cached as ref_<start>.json (time-free A: ref_<start>_tf.json): per day the BaZi-day pull
       mean and the Saturn-station points (A, B) and the noon chemistry; from them the cut points (top, 🔥 = 26th,
       ✅ = 73rd of 365) and pair_top. A time-free reference is built the same way from the time-free values."""
    def build_ref():
        days = [start + dt.timedelta(days=i) for i in range(365)]
        out = dict(v=REF_V, start=start.isoformat(), days=len(days))
        for who in ("A", "B"):
            mean = [wmean(samples(d, who, a_time=a_time)) for d in days]
            vals = sorted(mean, reverse=True)
            out[who] = dict(top=vals[0], fire=vals[25], ok=vals[72], mean=mean,
                            station=[R.saturn_station(nat_of(who, a_time), noon(d))[0] for d in days])
        out["chem"] = [chem(noon(d), a_time)[0] for d in days]
        out["pair_top"] = max(out["chem"])
        return out
    return _cached("ref_%s" % start.isoformat(), a_time, build_ref)


def longrun(a_time="noon"):
    """The fixed long-run reference, every day of LONGRUN: pull = the BaZi day's 24 hourly samples (the on-the-hour
       slots of the 10-minute grid, same DST rule), chemistry = the noon raw score. Cached as ref_longrun_*.json."""
    first, last = LONGRUN

    def build_lr():
        days = [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]
        out = dict(v=REF_V, first=first.isoformat(), last=last.isoformat(), days=len(days))
        for who in ("A", "B"):
            out["pull_" + who] = [wmean(samples(d, who, wall_grid(d, 60), a_time)) for d in days]
        out["chem"] = [chem(noon(d), a_time)[0] for d in days]
        return out
    return _cached("ref_longrun_%s_%s" % (first.isoformat(), last.isoformat()), a_time, build_lr)


def pct(v, ref_sorted):
    """Mid-rank percentile (#less + ½·#equal) / n, as in §11, to 3 decimals."""
    return rhu(M.percentile_midrank(v, ref_sorted), 3)


def tier_pct(p):
    return next((t for c, t in PCT_TIERS if p >= c), "🟢")


def year_month_branches(day):
    """流年 / 流月 (STD) in force at local noon: the month turns at each jie (the Sun at 315° + 30k), the year at 立春
       (315°) — so January and early February before 立春 (the Sun's months 10–11 from 寅) still belong to last year."""
    mi = int(((A.lon("Sun", noon(day)) - 315.0) % 360) // 30)
    sy = day.year - 1 if (day.month <= 2 and mi >= 10) else day.year
    return Z.BRANCHES[(sy - 4) % 12], Z.BRANCHES[(2 + mi) % 12]


def lucks(who, day, opt):
    """[(luck pillar, number of charts)] in force on the day: one pillar for a timed (or noon) chart; time-free A counts
       her 119 charts per pillar, in luck order."""
    if who != "A" or opt["a_time"] != "tf":
        lb = luck_branch(ch[who], day); return [(lb, 1)] if lb else []
    n = {}
    for c in tf()["charts"]:
        lb = luck_branch(c, day)
        if lb: n[lb] = n.get(lb, 0) + 1
    order = [name for _, name in ch["A"]["lucks"]]
    return sorted(n.items(), key=lambda kv: order.index(kv[0]))


def own_set(o, lk, opt):
    """own = the chart's distinct natal branches + its luck branch. A luck branch counts at its share of the charts
       (time-free A on a pillar-change day) times opt luck_w when it repeats a natal branch."""
    own = list(o["branches"]); tot = sum(n for _, n in lk)
    for name, n in lk:
        rep = name[1] in o["branches"] and opt["luck_w"] != 1.0
        w = n / tot * (opt["luck_w"] if rep else 1.0)
        tag = "luck" + (" %s %d/%d" % (name, n, tot) if n < tot else "") + (" ×%g" % opt["luck_w"] if rep else "")
        own.append(name[1] if w == 1.0 else (name[1], w, tag))
    return own


def other_set(oth, day, opt):
    """other = the other chart's distinct natal branches (+ 流年 and 流月 at YM_WEIGHT with --year-month-terms)."""
    other = list(oth["branches"])
    if opt["ym"]:
        yb, mb = year_month_branches(day)
        other += [(yb, YM_WEIGHT, "流年 ×%g" % YM_WEIGHT), (mb, YM_WEIGHT, "流月 ×%g" % YM_WEIGHT)]
    return other


def flag_scale(mean, r):
    return ("🔥" if mean >= r["fire"] else "✅" if mean >= r["ok"] else ""), rhu(mean / r["top"] * 10, 1)


def day_charge(day, who, other_key, flag, scale, stp, opt, shift=0):
    """§7 day score of one chart against another: (raw S, S', parts). When time-free A's charts split between two luck
       pillars, raw and parts carry each pillar's luck terms at its share, and S' = the share-weighted mean of the
       per-pillar S', rounded half up. shift moves raw before rescaling (the §13 wearer term, −K_SELF·W)."""
    g = Z.day_index(day.year, day.month, day.day); o = ch[who]; other = other_set(ch[other_key], day, opt)
    run = lambda own: Z.day_score(Z.STEMS[g % 10], Z.BRANCHES[g % 12], own, other, o["dm"], o["year_branch"],
                                  T.daily_points(flag, scale), stp)
    lk = lucks(who, day, opt); raw, sc, parts = run(own_set(o, lk, opt))
    if shift: raw = raw + shift; sc = Z.rescale(raw)
    if len(lk) > 1:
        tot = sum(n for _, n in lk)
        sc = rhu(sum(n * Z.rescale(run(own_set(o, [(name, 1)], opt))[0] + shift) for name, n in lk) / tot)
    return raw, sc, parts


def hour_points(day, who, other_key, opt):
    """§7 hour scores for the 12 blocks: [(H, parts)] in 子..亥 order (time-free split: the share-weighted H, rounded
       half up)."""
    g = Z.day_index(day.year, day.month, day.day); o = ch[who]; lk = lucks(who, day, opt)
    own, other = own_set(o, lk, opt), other_set(ch[other_key], day, opt)
    out = [Z.hour_score(hb, Z.BRANCHES[g % 12], own, other, o["year_branch"]) for hb in Z.BRANCHES]
    return [(rhu(H), hp) for H, hp in out] if len(lk) > 1 else out


def window_dists(start, ref, opt):
    """The window's raw S for each of its 365 days (A with B, B with A, A with C) and its 365 × 12 hour points per
       person, built from the cached per-day means and station points with the same functions as the day itself."""
    out = {k: [] for k in ("A", "B", "A_with_C", "hours_A", "hours_B")}
    for i in range(ref["days"]):
        d = start + dt.timedelta(days=i)
        fs = {who: flag_scale(ref[who]["mean"][i], ref[who]) for who in ("A", "B")}
        for key, who, oth in (("A", "A", "B"), ("B", "B", "A"), ("A_with_C", "A", "C")):
            out[key].append(day_charge(d, who, oth, *fs[who], ref[who]["station"][i], opt)[0])
        for who, oth in (("A", "B"), ("B", "A")):
            out["hours_" + who] += [H for H, _ in hour_points(d, who, oth, opt)]
    return {k: sorted(v) for k, v in out.items()}


def chem_day_max(day, top, a_time="noon"):
    """The chemistry peak over the BaZi day's hourly wall-clock instants (23:00 the evening before … 22:00, DST as for
       pull). The earliest instant wins a tie; a day with no chemistry has no peak time."""
    best = None
    for u, w, k in wall_grid(day, 60):
        s = chem(u, a_time)[0]
        if best is None or s > best[0]: best = (s, u, w)
    s, u, w = best; lt = u.astimezone(NY)
    when = lt.strftime("%H:%M") + (" " + lt.tzname() if w < 1 else "") + (" (the evening before)" if lt.date() < day else "")
    return dict(raw=rhu(s, 2), scale=min(CHEM_CAP, rhu(s / top * 10, 1)), time=when if s > 0 else None)


def moon_times_tf(d0, d1, step_min=10):
    """Time-free A's Moon times: radar_core.moon_times run on each of her 119 charts (same root finder: a 10-min scan,
       bisection to 30 s), grouped by (aspect, point) → "earliest-latest" local time, plus "(n/119)" when the exact
       time falls inside the day for only n charts. The Moon's longitude is shared between charts (memoised)."""
    memo = {}

    def moon(t):
        if t not in memo: memo[t] = A.lon("Moon", t)
        return memo[t]
    m0 = moon(d0); arc = (moon(d1) - m0) % 360 + 0.5        # the Moon only moves forward: targets outside its arc never hit
    found = {}
    for c in tf()["charts"]:
        for p, pl in c["pts"].items():
            for asp, ang in A.ASPECTS.items():
                for target in {(pl + ang) % 360, (pl - ang) % 360}:
                    if (target - m0) % 360 > arc: continue
                    for x in A.roots(lambda t: A.sep(moon(t), target), d0, d1, step_min=step_min):
                        pt, a2 = R._label(p, asp)
                        found.setdefault((a2, pt, R.flavor("Moon", a2, pt), R.TAG.get(pt, "")), []).append(x)
    out = []
    for (a2, pt, fl, tg), xs in found.items():
        lo, hi = (min(xs).astimezone(NY).strftime("%H:%M"), max(xs).astimezone(NY).strftime("%H:%M"))
        out.append((min(xs), (lo if lo == hi else "%s-%s" % (lo, hi)) + ("" if len(xs) == TF_N else " (%d/%d)" % (len(xs), TF_N)),
                    a2, pt, fl, tg))
    return [row[1:] for row in sorted(out)]


def outfit_report(day, wearer, outfit, opt=None, seen=None, params=None):
    """§13 outfit color (STD) for one outfit worn by `wearer`: on the wearer's §7 day charge (raw′ = raw − K_SELF·W, then
       the same rescale and tier — share-weighted per luck pillar on a time-free split day) and on the other person's
       §9 pull (samples in the seen blocks × (1 + K_VIEW·V), capped at 10). The headline keys never change."""
    opt = dict(DEFAULT_OPT, **(opt or {})); at = opt["a_time"]; params = dict(C.COLOR_PARAMS, **(params or {}))
    seen = params["SEEN"] if seen is None else seen
    viewer = "A" if wearer == "B" else "B"; ref = reference(window_for(day), at); t_noon = noon(day)
    E = C.outfit_vector(outfit); sw, sv = (C.SC.chart_strength(ch[x]["pillars"]) for x in (wearer, viewer))
    flag, scale = flag_scale(wmean(samples(day, wearer, None, at)), ref[wearer])
    stp = R.saturn_station(nat_of(wearer, at), t_noon)[0]
    raw, sc, _ = day_charge(day, wearer, viewer, flag, scale, stp, opt)
    we = C.wearer_effect(E, sw["F"], raw, params)
    sc2 = day_charge(day, wearer, viewer, flag, scale, stp, opt, shift=-params["K_SELF"] * we["W"])[1]
    venus = A.SIGNS[int(nat_of(viewer, at)["Venus"] // 30)]; taste = C.taste(outfit, venus)

    def view(rows, blocks):
        return C.viewer_effect(E, sv["F"], taste, [v for v, _, _ in rows], [w for _, w, _ in rows], blocks,
                               ref[viewer]["top"], seen, params)
    grid = wall_grid(day); rows = samples(day, viewer, grid, at)
    if opt["solar"]:            # the day pull stays on the clock grid, but "seen" follows the solar blocks
        sg = solar_grid(day); s0 = sg[0][0]
        ve = view(rows, [Z.BRANCHES[int((u - s0).total_seconds() // 60 // BLOCK_MIN) % 12] for u, _, _ in grid])
        blocks = view(samples(day, viewer, sg, at), [Z.BRANCHES[block_of(k)] for _, _, k in sg])["blocks"]
    else:
        ve = view(rows, [Z.BRANCHES[block_of(k)] for _, _, k in rows]); blocks = ve["blocks"]
    r4, r3 = (lambda x: rhu(x, 4)), (lambda x: rhu(x, 3))
    return dict(worn_by=wearer, seen_by=viewer, outfit=outfit, E={e: r4(v) for e, v in E.items() if v},
                wearer=dict(W=r4(we["W"]), raw=[raw, r3(we["raw_after"])], charge=[sc, sc2], tier=[Z.tier(sc), Z.tier(sc2)],
                            strength=dict(S=r4(sw["S"]), verdict=sw["verdict"], F=sw["F"], partial=sw["partial"])),
                viewer=dict(V=r4(ve["V"]), T=r4(ve["T"]), venus=venus, day_pull=[r3(ve["day_pull_before"]), r3(ve["day_pull_after"])],
                            blocks={b: [r3(x), r3(y)] for b, (x, y) in blocks.items()},
                            strength=dict(S=r4(sv["S"]), verdict=sv["verdict"], F=sv["F"], partial=sv["partial"])),
                role={"for_" + viewer: list(C.role_tag(E, sv["dm_element"])), "for_" + wearer: list(C.role_tag(E, sw["dm_element"]))})


def main(day, opt=None, outfits=None, seen=None):
    opt = dict(DEFAULT_OPT, **(opt or {})); at = opt["a_time"]
    start = window_for(day); ref = reference(start, at); lr = longrun(at); dists = window_dists(start, ref, opt)
    g = Z.day_index(day.year, day.month, day.day); ds, db = Z.STEMS[g % 10], Z.BRANCHES[g % 12]
    res = dict(date=day.isoformat(), weekday=day.strftime("%A"), pillar=Z.pillar_name(g), window_start=start.isoformat())
    t_noon = noon(day)
    s, why = chem(t_noon, at); top = ref["pair_top"]
    res["chemistry"] = dict(scale=min(CHEM_CAP, rhu(s / top * 10, 1)), raw=rhu(s, 2),
                            lit_by=[(b, ang, nm, o) for v, b, ang, nm, o in why[:3]],
                            above_window_max=s > top, day_max=chem_day_max(day, top, at),
                            chem_pct_longrun=pct(s, sorted(lr["chem"])))
    grid = wall_grid(day)
    vals = {who: samples(day, who, grid, at) for who in ("A", "B")}
    sgrid = solar_grid(day) if opt["solar"] else None
    bvals = {who: samples(day, who, sgrid, at) for who in ("A", "B")} if sgrid else vals
    stp = {}
    for who, other_key in (("A", "B"), ("B", "A")):
        o = ch[who]; r = ref[who]
        mean = wmean(vals[who]); flag, scale = flag_scale(mean, r)
        lk = lucks(who, day, opt); lb = max(lk, key=lambda kv: kv[1])[0] if lk else None
        nat = nat_of(who, at)
        stp[who], _ = R.saturn_station(nat, t_noon)
        raw, sc, parts = day_charge(day, who, other_key, flag, scale, stp[who], opt)
        hours = []
        for i, (H, hp) in enumerate(hour_points(day, who, other_key, opt)):
            if sgrid:
                b0 = sgrid[12 * i][0].astimezone(NY)
                b1 = (sgrid[12 * i + 11][0] + dt.timedelta(minutes=STEP_MIN - 1)).astimezone(NY)   # in UTC: DST-safe
                lab = "%s-%s (true solar time)" % (b0.strftime("%H:%M"), b1.strftime("%H:%M"))
            else:
                lab = "00:00-00:59 (+23:00 the night before)" if i == 0 else "%02d:00-%02d:59" % (2 * i - 1, 2 * i)
            bp = wmean(bvals[who], keep=lambda k, i=i: block_of(k) == i)
            hours.append(dict(block=Z.BRANCHES[i], hours=lab, charge=H, pull=rhu(bp / r["top"] * 10, 1),
                              terms=[n for n, _ in hp], points=H, points_pct=pct(H, dists["hours_" + who])))
        d0 = loc(day.year, day.month, day.day).astimezone(UTC); d1 = d0 + dt.timedelta(days=1)
        H = R.hits(nat, t_noon); tone, how = R.tone(H)
        cp = pct(raw, dists[who])
        mt = (moon_times_tf(d0, d1) if who == "A" and at == "tf" else
              [(x.astimezone(NY).strftime("%H:%M"), a, p, f, tg) for x, a, p, f, tg in
               R.moon_times({k: v for k, v in nat.items() if k != "MC"}, d0, d1)])
        res[who] = dict(charge=sc, tier=Z.tier(sc), raw=raw, parts=parts, luck=lb, pull=scale, flag=flag,
                        tone=(dict(tone) if tone else None, how),
                        exact=[f"{h['body']} {h['aspect']} {h['point']} {h['orb']}° {h['flavor']} {h['tag']}" for h in H if h["phase"] == "exact"],
                        hours=hours, moon_times=mt,
                        door=[x.astimezone(NY).strftime("%H:%M") for x, p, ang, dr in
                              R.angle_crossings({"Venus": nat["Venus"]}, d0, d1, LAT, LON) if dr],
                        charge_pct=cp, tier_pct=tier_pct(cp), **Z.sub_scores(parts, o["dm"]),
                        pull_pct_longrun=pct(wmean(vals[who], keep=lambda k: k % 6 == 0), sorted(lr["pull_" + who])),
                        love_overlay=[f"💗 {h['body']} {h['aspect']} {h['point']} {h['orb']}° {h['phase']} {h['flavor']}"
                                      for h in R.love_overlay(H)])
        if who == "A" and at == "tf":
            tot = sum(n for _, n in lk)
            res[who]["luck_shares"] = {name: [n, rhu(n / tot, 3)] for name, n in lk}
    rawc, scc, partsc = day_charge(day, "A", "C", res["A"]["flag"], res["A"]["pull"], stp["A"], opt)
    cpc = pct(rawc, dists["A_with_C"])
    res["A_with_C"] = dict(charge=scc, tier=Z.tier(scc), parts=partsc, charge_pct=cpc, tier_pct=tier_pct(cpc),
                           **Z.sub_scores(partsc, ch["A"]["dm"]))
    res["receipt"] = ("Math: %s · chemistry %s · A charge %s %s, pull %s%s · B charge %s %s, pull %s%s" %
                      (res["pillar"], res["chemistry"]["scale"], res["A"]["charge"], res["A"]["tier"], res["A"]["pull"], res["A"]["flag"],
                       res["B"]["charge"], res["B"]["tier"], res["B"]["pull"], res["B"]["flag"]))
    slots = {k for _, _, k in grid}
    res["sampling"] = dict(grid="BaZi day: 23:00 the evening before to 22:50, every 10 min of local wall-clock time",
                           slots=1440 // STEP_MIN, instants=len(grid), effective=sum(w for _, w, _ in grid),
                           skipped=1440 // STEP_MIN - len(slots), repeated=len(grid) - len(slots))
    res["a_chart"] = ("time-free: the mean of A's %d charts 00:00-19:40 local (no birth time pinned); exact transits, "
                      "the door and the Saturn station use their averaged chart" % TF_N if at == "tf" else
                      "noon stand-in (v1), kept for comparison")
    if sgrid:
        e = A.equation_of_time(t_noon); off = t_noon.astimezone(NY).utcoffset().total_seconds() / 60
        res["solar_time"] = dict(at="local noon (on a DST day the early blocks differ by the hour; their labels are exact)",
                                 eot_min=rhu(e, 1), mean_time_minus_clock_min=rhu(LON * 4 - off, 1),
                                 clock_minus_solar_min=rhu(off - LON * 4 - e, 1))
    if outfits:
        res["outfit"] = {w: outfit_report(day, w, outfits[w], opt, seen) for w in sorted(outfits)}
        res["outfit"]["params"] = dict(C.COLOR_PARAMS, SEEN=C.COLOR_PARAMS["SEEN"] if seen is None else seen)
    if opt != DEFAULT_OPT: res["options"] = opt
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="One day's math for A and B (and A with C).")
    ap.add_argument("date", type=dt.date.fromisoformat, help="YYYY-MM-DD, a local Frederick, MD date")
    ap.add_argument("--luck-repeat-weight", type=float, default=1.0, help="weight of a luck branch that repeats a natal one")
    ap.add_argument("--year-month-terms", action="store_true", help="STD: 流年/流月 branches in the other set at ½ weight")
    ap.add_argument("--solar-time", action="store_true", help="STD: hour-block edges on true solar time")
    ap.add_argument("--a-time", choices=("tf", "noon"), default=DEFAULT_OPT["a_time"],
                    help="A's chart: tf = time-free (her 119 possible charts), noon = the v1 noon stand-in")
    ap.add_argument("--outfit-A", help='§13: A\'s outfit, JSON list of {"slot": ..., "color": ...}')
    ap.add_argument("--outfit-B", help='§13: B\'s outfit, JSON list of {"slot": ..., "color": ...}')
    ap.add_argument("--seen", help="§13: the blocks when the viewer sees the wearer, e.g. 辰,巳,午,未,申 (default)")
    a = ap.parse_args()
    if not (math.isfinite(a.luck_repeat_weight) and a.luck_repeat_weight >= 0): ap.error("--luck-repeat-weight must be a number ≥ 0")
    outfits = {}
    for w, txt in (("A", a.outfit_A), ("B", a.outfit_B)):
        if txt is None: continue
        try:
            outfits[w] = json.loads(txt); C.outfit_vector(outfits[w])
        except (ValueError, TypeError, AttributeError) as e:
            ap.error("--outfit-%s: %s" % (w, e))
    seen = None
    if a.seen is not None:
        seen = "".join(x.strip() for x in a.seen.split(","))
        if not seen or any(b not in Z.BRANCHES for b in seen): ap.error("--seen: hour branches from %s, e.g. 辰,巳,午" % Z.BRANCHES)
        if not outfits: ap.error("--seen needs --outfit-A or --outfit-B")
    print(json.dumps(main(a.date, dict(luck_w=a.luck_repeat_weight, ym=a.year_month_terms, solar=a.solar_time,
                                       a_time=a.a_time), outfits or None, seen), ensure_ascii=False, indent=1))
