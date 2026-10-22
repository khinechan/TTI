"""monthly_core — THE ONE FORMULA v1.5 (the monthly formula), as pure math.

Inputs (all supplied by the caller; nothing is built in):
  rows        the coefficient table (tables/coefficients_v1.5.csv): id, family, signal, area, sign, w0, grade
  x[i][τ]     share of month τ (0 ≤ τ < 1080) that row i is active, in [0, 1]
  size[a][τ]  summed size (1–3 each) of area a's logged events in month τ
  log_months  the months covered by the event log
Output per area and month: fire step (⬇️ ➖ 🔥 🔥🔥 🔥🔥🔥), flavor (✅ 🛡️ ⚡), voices.
"""
import bisect
import csv
import math
import statistics

AREAS = ("career", "money_through_others", "relationship", "home_family",
         "health_body", "travel_move", "loss_theft", "voice_output")
FAMILIES = ("western_transits", "secondary_progressions", "annual_profections", "vedic_dasha",
            "bazi", "zi_wei", "mahabote", "numbers", "western_aspects")
BETA, KAPPA, U_CLIP, U_HALF = 0.5, 12.0, 1.0, 0.5
D_F = {f: 1.0 for f in FAMILIES}
STEPS = (0.25, 0.50, 0.75, 0.90)
STEP_ICON = ("⬇️", "➖", "🔥", "🔥🔥", "🔥🔥🔥")
FLAVOR_SUPPORT_MIN, FLAVOR_PRESSURE_MAX = 2.0 / 3.0, 1.0 / 3.0
FLAVOR_ICON = {"support": "✅", "pressure": "🛡️", "mixed": "⚡"}
REF_MONTHS = 1080
W0_ALLOWED, A_CAP = (0.10, 0.05, 0.025), 0.05


# ---------- the coefficient table ----------
def load_table(path):
    rows = []
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            w0 = float(r["w0"])
            if r["family"] not in FAMILIES: raise ValueError("unknown family %s" % r["family"])
            if r["area"] not in AREAS: raise ValueError("unknown area %s" % r["area"])
            if min(abs(w0 - a) for a in W0_ALLOWED) > 1e-9: raise ValueError("w0 %s not allowed" % r["w0"])
            if r["grade"] == "A" and w0 > A_CAP + 1e-9: raise ValueError("A row above the cap")
            rows.append(dict(id=r["id"], family=r["family"], signal=r["signal"], area=r["area"],
                             sign=1 if r["sign"] == "+" else -1, w0=w0, grade=r["grade"]))
    return rows


def rows_for_sex(rows, sex):
    """Drop the rows marked for the other sex ('[♀ only]' / '[♂ only]'). sex = 'M' or 'F'."""
    other = "[♂ only]" if sex == "F" else "[♀ only]"
    return [r for r in rows if other not in r["signal"]]


# ---------- Layer 2: life history ----------
def u_of(n1, s1, n0, s0, kappa=KAPPA):
    """u = clip( n₁/(n₁+κ) · log₁₀(r̄₁/r̄₀)/log₁₀2 , ±1 ),  r̄₁ = (S₁+½)/(n₁+1),  r̄₀ = (S₀+½)/(n₀+1)."""
    r1 = (s1 + U_HALF) / (n1 + 1.0)
    r0 = (s0 + U_HALF) / (n0 + 1.0)
    u = (n1 / (n1 + kappa)) * math.log10(r1 / r0) / math.log10(2.0)
    return max(-U_CLIP, min(U_CLIP, u))


def layer2_weights(rows, x, size, log_months, t):
    """w = w⁰ · (1 + β·u), with u fitted on the logged months strictly before t.
       n₁ = Σ x, S₁ = Σ x·size, n₀ = Σ (1−x), S₀ = Σ (1−x)·size over those months."""
    train = [tau for tau in log_months if tau < t]
    out = []
    for i, r in enumerate(rows):
        sz = size.get(r["area"], {})
        n1 = s1 = n0 = s0 = 0.0
        for tau in train:
            xi, si = x[i][tau], sz.get(tau, 0)
            n1 += xi; s1 += xi * si; n0 += 1.0 - xi; s0 += (1.0 - xi) * si
        out.append(r["w0"] * (1.0 + BETA * u_of(n1, s1, n0, s0)))
    return out


# ---------- Layer 1: the reading ----------
def family_parts(rows, x, w, months):
    """P[f][a][k] = Σ x·w over rows of family f, area a, sign + ; N likewise for sign −."""
    nf, na, nt = len(FAMILIES), len(AREAS), len(months)
    p = [[[0.0] * nt for _ in range(na)] for _ in range(nf)]
    n = [[[0.0] * nt for _ in range(na)] for _ in range(nf)]
    for i, r in enumerate(rows):
        f, a = FAMILIES.index(r["family"]), AREAS.index(r["area"])
        tgt = (p if r["sign"] > 0 else n)[f][a]
        for k, tau in enumerate(months):
            if x[i][tau]: tgt[k] += x[i][tau] * w[i]
    return p, n


def family_sd(p, n):
    """σ_f = population SD of (P_f + N_f) over all areas × all reference months; 0 → 1."""
    out = []
    for f in range(len(p)):
        vals = [p[f][a][k] + n[f][a][k] for a in range(len(p[f])) for k in range(len(p[f][a]))]
        sd = statistics.pstdev(vals)
        out.append(sd if sd > 0 else 1.0)
    return out


def reading(p, n, sd, d=None):
    """R⁺ = Σ_f d_f·P_f/σ_f · R⁻ = Σ_f d_f·N_f/σ_f."""
    d = d or D_F; dv = [d[f] for f in FAMILIES]
    na, nt = len(p[0]), len(p[0][0])
    rp = [[sum(dv[f] * p[f][a][k] / sd[f] for f in range(len(p))) for k in range(nt)] for a in range(na)]
    rn = [[sum(dv[f] * n[f][a][k] / sd[f] for f in range(len(p))) for k in range(nt)] for a in range(na)]
    return rp, rn


# ---------- master line ----------
def percentile_midrank(v, ref_sorted):
    """(#less + ½·#equal) / n."""
    lo, hi = bisect.bisect_left(ref_sorted, v), bisect.bisect_right(ref_sorted, v)
    return (lo + 0.5 * (hi - lo)) / float(len(ref_sorted))


def fire_step(p):
    """0..4 = ⬇️ ➖ 🔥 🔥🔥 🔥🔥🔥: one step for each cut p is strictly above."""
    return sum(1 for c in STEPS if p > c)


def flavor_of(rp, rn):
    """φ = R⁺/(R⁺+R⁻): ≥ ⅔ support · ≤ ⅓ pressure · else mixed; Act = 0 → none."""
    if rp + rn == 0: return None
    phi = rp / (rp + rn)
    if phi >= FLAVOR_SUPPORT_MIN: return "support"
    if phi <= FLAVOR_PRESSURE_MAX: return "pressure"
    return "mixed"


def voice_counts(p, n, a, k):
    """Per family: support (P > N) · pressure (N > P) · split (P = N > 0) · silent (P = N = 0)."""
    s = sum(1 for f in range(len(p)) if p[f][a][k] > n[f][a][k])
    q = sum(1 for f in range(len(p)) if n[f][a][k] > p[f][a][k])
    z = sum(1 for f in range(len(p)) if p[f][a][k] == 0 and n[f][a][k] == 0)
    return s, q, len(p) - s - q - z, z


class Table:
    """One fit: the weights in force at month t applied to every reference month."""

    def __init__(self, rows, x, size, log_months, t, d=None):
        self.rows, self.x = rows, x
        self.w = layer2_weights(rows, x, size, log_months, t)
        months = list(range(REF_MONTHS))
        self.p, self.n = family_parts(rows, x, self.w, months)
        self.sd = family_sd(self.p, self.n)
        self.rp, self.rn = reading(self.p, self.n, self.sd, d)
        self.act = [[self.rp[a][k] + self.rn[a][k] for k in months] for a in range(len(AREAS))]
        self.ref = [sorted(row) for row in self.act]

    def area(self, a, t):
        p = percentile_midrank(self.act[a][t], self.ref[a])
        fl = flavor_of(self.rp[a][t], self.rn[a][t])
        return dict(step=fire_step(p), icon=STEP_ICON[fire_step(p)], flavor=fl,
                    voices=voice_counts(self.p, self.n, a, t), p=p, act=self.act[a][t])


def month_reading(rows, x, size, log_months, t, d=None):
    T = Table(rows, x, size, log_months, t, d)
    return {AREAS[a]: T.area(a, t) for a in range(len(AREAS))}


# ---------- v1.5: the aspect family ----------
ASPECT_DEG = {"☌": 0, "⚹": 60, "□": 90, "△": 120, "☍": 180}
ASPECT_ORB, BUILDING_ORB, BUILDING_WEIGHT = 1.0, 3.0, 0.5


def parse_signal(sig):
    """'tr Uranus|Neptune|Pluto ☌|□|☍ natal Sun|MC' → (bodies, aspects, points)."""
    head, pts = sig.split(" natal ")
    _, bodies, asps = head.split(" ")
    return bodies.split("|"), asps.split("|"), pts.split("|")


def aspect_index(rows):
    """(body, aspect, point) → row id; every combination exactly once."""
    idx = {}
    for r in rows:
        if r["family"] != "western_aspects": continue
        b_, a_, p_ = parse_signal(r["signal"])
        for b in b_:
            for a in a_:
                for p in p_:
                    if (b, a, p) in idx: raise ValueError("combo %s covered twice" % ((b, a, p),))
                    idx[(b, a, p)] = r["id"]
    return idx


def fire_aspects(idx, natal, transits):
    """One day. natal = {point: λ}; transits = {body: (λ, speed)}.
       weight 1 inside 1° (applying or separating) · ½ for 1–3° while applying · else 0; a row keeps its max."""
    out = {}
    for b, (lon, spd) in transits.items():
        for p, nl in natal.items():
            for sym, deg in ASPECT_DEG.items():
                rid = idx.get((b, sym, p))
                if rid is None: continue
                d = abs(lon - nl) % 360.0; d = min(d, 360.0 - d); o = abs(d - deg)
                if o <= ASPECT_ORB:
                    w = 1.0
                elif o <= BUILDING_ORB:
                    d2 = abs(lon + spd * 0.01 - nl) % 360.0; d2 = min(d2, 360.0 - d2)
                    if abs(d2 - deg) >= o: continue
                    w = BUILDING_WEIGHT
                else:
                    continue
                out[rid] = max(out.get(rid, 0.0), w)
    return out


# ---------- Layer 3: the honesty decision ----------
ALPHA, POWER_TARGET = 0.05, 0.80


def p_value(real, nulls):
    """p = (1 + #{null ≥ real}) / (N + 1)."""
    return (1 + sum(1 for v in nulls if v >= real)) / (len(nulls) + 1.0)


def brier_skill(rows):
    """BSS = 1 − Σ(p − o)² / Σ(q − o)²; rows = (engine probability p, outcome o, base-rate probability q)."""
    be = sum((p - o) ** 2 for p, o, _ in rows)
    bb = sum((q - o) ** 2 for _, o, q in rows)
    return 1 - be / bb if bb > 0 else 0.0


def verdict(p_chart, p_dates, bss, power_2x, p_age):
    """✅ iff all three p ≤ α and BSS > 0 · ❌ iff some p > α and power (95% lower bound) ≥ 0.80 · else ⬜."""
    if p_chart <= ALPHA and p_dates <= ALPHA and p_age <= ALPHA and bss > 0: return "✅"
    if (p_chart > ALPHA or p_dates > ALPHA or p_age > ALPHA) and power_2x is not None and power_2x >= POWER_TARGET:
        return "❌"
    return "⬜"


def power_lower_bound(wins, n, alpha=0.05):
    """Exact one-sided (1 − α) lower bound on a success share (Clopper–Pearson), by bisection."""
    if wins == 0: return 0.0
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        tail = sum(math.comb(n, i) * mid ** i * (1 - mid) ** (n - i) for i in range(wins, n + 1))
        if tail > alpha: hi = mid
        else: lo = mid
    return 0.5 * (lo + hi)
