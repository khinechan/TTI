"""pair_core — two-chart math: synastry, hot spots, the pair timeline, the attraction family, random-chart
nulls, and the chance math used to judge hit rates. Both charts are inputs ({point: longitude})."""
import datetime as dt
import math
import random
import astro_core as A
from bazi_core import round_half_up

SYN_ORBS = {'☌': 3.0, '☍': 3.0, '□': 3.0, '△': 3.0, '⚹': 2.5}


def synastry(chart_a, chart_b, orbs=SYN_ORBS):
    """Every (point in A, point in B) pair whose separation is within an aspect's orb, tightest first."""
    rows = []
    for pa, la in chart_a.items():
        for pb, lb in chart_b.items():
            for s, ang in A.ASPECTS.items():
                o = A.orb(la, lb, ang)
                if o <= orbs[s]: rows.append((round(o, 2), pa, s, pb))
    return sorted(rows)


def contact_counts(chart_a, chart_b, orbs=SYN_ORBS, tight=1.0):
    """(all contacts, contacts ≤ tight degrees)."""
    rows = synastry(chart_a, chart_b, orbs)
    return len(rows), sum(1 for r in rows if r[0] <= tight)


# ---------- attraction family ----------
FAM_FROM = ('Venus', 'Mars')
FAM_TO = ('Sun', 'Moon', 'Venus', 'Mars', 'ASC', 'DSC')
FAM_ASPECTS = (0, 90, 180)


def attraction_family(chart_b, chart_a, orb=1.0):
    """B's Venus/Mars in ☌ □ ☍ within 1° of A's Sun/Moon/Venus/Mars/ASC/DSC."""
    out = []
    for f in FAM_FROM:
        for t in FAM_TO:
            if f in chart_b and t in chart_a:
                d = A.distance(chart_b[f], chart_a[t])
                for ang in FAM_ASPECTS:
                    if abs(d - ang) <= orb: out.append((f, ang, t, round(abs(d - ang), 2)))
    return out


def family_expected(n_pairs=12, orb=1.0):
    """Expected count if longitudes were independent and uniform:
       P(one pair hits) = Σ_aspects (number of exact angles) · 2·orb / 360 = (1 + 2 + 1)·2·orb/360
       → 8/360 = 2.22% at 1°;  λ = n_pairs · that  → 0.267 for 12 pairs."""
    p = 4 * 2 * orb / 360.0
    return p, n_pairs * p


def poisson_tail(k, lam):
    """P(X ≥ k) for X ~ Poisson(λ) — the independent-planets approximation."""
    return 1.0 - sum(math.exp(-lam) * lam ** i / math.factorial(i) for i in range(k))


# ---------- random-chart null ----------
def random_chart(rng, start, end, bodies=('Sun', 'Moon', 'Mercury', 'Venus', 'Mars', 'Jupiter', 'Saturn',
                                          'Uranus', 'Neptune', 'Pluto')):
    """Planet longitudes at a random moment drawn uniformly between two aware datetimes."""
    t = start + dt.timedelta(seconds=rng.random() * (end - start).total_seconds())
    return {b: A.lon(b, t) for b in bodies}


def null_percentile(real_value, sample_values):
    """Share of the null sample strictly below the real value (percentile) and share ≥ it (p-value)."""
    n = len(sample_values)
    below = sum(1 for v in sample_values if v < real_value) / n
    p = (1 + sum(1 for v in sample_values if v >= real_value)) / (n + 1)
    return below, p


# ---------- hot spots and the pair timeline ----------
def midpoint(a, b):
    """Shorter-arc midpoint of two longitudes."""
    return (b + A.sep(a, b) / 2.0) % 360


def hot_spots(chart_a, chart_b, family_orb=1.0):
    """A hot spot = the midpoint of each tight attraction-family contact (☌ or ☍; for ☍ the axis point
       on B's side). Returns {label: longitude}."""
    spots = {}
    for f, ang, t, o in attraction_family(chart_b, chart_a, family_orb):
        if ang == 0:
            spots["B %s ☌ A %s" % (f, t)] = midpoint(chart_b[f], chart_a[t])
        elif ang == 180:
            spots["B %s ☍ A %s (axis)" % (f, t)] = midpoint(chart_b[f], (chart_a[t] + 180) % 360)
    return spots


PAIR_BODIES = {'Sun': (1.0, 3.0), 'Venus': (3.0, 3.0), 'Mars': (3.0, 3.0), 'Jupiter': (2.0, 2.0)}   # weight, orb
PAIR_ASPECTS = [(0, 1.0), (180, 1.0), (90, 0.7), (120, 0.5), (60, 0.4)]


def pair_score(spots, t):
    """P(t) = Σ_bodies Σ_spots Σ_aspects w_body · f_aspect · max(0, 1 − orb/orb_body)
       (an axis spot counts ☌ and ☍ alike)."""
    s = 0.0; why = []
    for b, (w, ob) in PAIR_BODIES.items():
        l = A.lon(b, t)
        for name, pl in spots.items():
            d = A.distance(l, pl)
            for ang, f in PAIR_ASPECTS:
                o = abs(d - ang)
                if o <= ob:
                    v = w * f * (1 - o / ob); s += v; why.append((round(v, 3), b, ang, name, round(o, 2)))
    return s, sorted(why, reverse=True)


def timeline(spots, t0, days, hour_utc=16):
    """Daily pair scores, scaled so the top day of the run = 10; windows = runs of days ≥ 50% of the top."""
    rows = []
    for i in range(days):
        t = (t0 + dt.timedelta(days=i)).replace(hour=hour_utc, minute=0)
        rows.append((t, pair_score(spots, t)[0]))
    top = max(s for _, s in rows) or 1.0
    scaled = [(t, s, round_half_up(s / top * 10, 1)) for t, s in rows]
    windows, cur = [], None
    for t, s, sc in scaled:
        if s >= 0.5 * top:
            if cur and (t - cur[1]).days == 1: cur[1] = t; cur[2] = max(cur[2], sc)
            else: cur = [t, t, sc]; windows.append(cur)
        else:
            cur = None
    return scaled, windows


# ---------- chance math for scoring calls ----------
def binomial_tail(k, n, p):
    """P(X ≥ k) for X ~ Binomial(n, p): the chance of k or more hits by luck alone."""
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def wilson(k, n, z=1.959963984540054):
    """95% Wilson interval for a hit rate k/n."""
    if n == 0: return (0.0, 1.0)
    ph = k / n; den = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / den; h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))
