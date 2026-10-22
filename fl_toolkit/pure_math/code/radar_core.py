"""radar_core — transits to a chart's natal points: weights, phases, tone, Moon timing, angle crossings,
the door, and the Saturn-station term. The natal chart, place and time are inputs.

natal = {point: longitude} with any of Sun..Pluto, ASC, MC (DSC/IC are derived)."""
import datetime as dt
import astro_core as A

BODIES = ['Sun', 'Mercury', 'Venus', 'Mars', 'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']   # Moon handled apart
SLOW = {'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto'}
RANK = {'Saturn': 5, 'Uranus': 4, 'Neptune': 4, 'Pluto': 4, 'Jupiter': 3, 'Mars': 2, 'Sun': 1, 'Mercury': 1, 'Venus': 1}
ASPECT_W = {'☌': 1.0, '☍': 0.9, '□': 0.9, '△': 0.6, '⚹': 0.5}
PHASE_F = {'exact': 1.0, 'applying': 0.5, 'fading': 0.25}
ORB = 3.0
TAG = {'Sun': 'work', 'MC': 'work', 'IC': 'work', 'Mercury': 'work', 'Uranus': 'work',
       'Venus': 'love', 'DSC': 'love', 'Jupiter': 'money',
       'Moon': 'body', 'Mars': 'body', 'ASC': 'body',
       'Saturn': 'loss', 'Neptune': 'loss', 'Pluto': 'loss'}
HARD_BODIES = {'Mars', 'Saturn', 'Uranus', 'Neptune', 'Pluto'}


def flavor(body, asp, point):
    """△ ⚹ → ✅ · □ ☍ → ⚠️ · ☌: slow bodies Jupiter ✅ / others ⚠️; fast bodies ⚠️ if Mars, Saturn
       or an outer planet is on either side, else ✅."""
    if asp in ('△', '⚹'): return '✅'
    if asp in ('□', '☍'): return '⚠️'
    if body in SLOW: return '✅' if body == 'Jupiter' else '⚠️'
    return '⚠️' if (body in HARD_BODIES or point in HARD_BODIES) else '✅'


def _label(point, asp):
    """An opposition to ASC/MC is a conjunction to DSC/IC."""
    if point == 'ASC' and asp == '☍': return 'DSC', '☌'
    if point == 'MC' and asp == '☍': return 'IC', '☌'
    return point, asp


def hits(natal, t):
    """Every non-Moon transit within 3° of a natal point at time t, heaviest first.
       weight = RANK(body) · ASPECT_W(aspect) · PHASE_F(phase) · (1 − ½ · orb/3)
       phase: exact ≤1° · applying 1–3° (closing) · fading 1–3° (opening)."""
    out = []
    for b in BODIES:
        l, v = A.lon(b, t), A.speed(b, t)
        for p, pl in natal.items():
            if p in ('DSC', 'IC'): continue
            for asp, ang in A.ASPECTS.items():
                o = A.orb(l, pl, ang)
                if o > ORB: continue
                closing = A.orb(l + v * 0.01, pl, ang) < o
                phase = 'exact' if o <= 1.0 else ('applying' if closing else 'fading')
                pt, a2 = _label(p, asp)
                w = RANK[b] * ASPECT_W[asp] * PHASE_F[phase] * (1.0 - 0.5 * o / ORB)
                out.append(dict(body=b, aspect=a2, point=pt, orb=round(o, 2), phase=phase, weight=round(w, 3),
                                tag=TAG.get(pt, ''), flavor=flavor(b, a2, pt)))
    order = {'exact': 0, 'applying': 1, 'fading': 2}
    out.sort(key=lambda h: (-RANK[h['body']], order[h['phase']], h['orb']))
    return out


def tone(H):
    """The heaviest EXACT hit; if none, the heaviest applying slow hit ('building'); fading never counts."""
    for h in H:
        if h['phase'] == 'exact': return h, 'exact'
    for h in H:
        if h['phase'] == 'applying' and h['body'] in SLOW: return h, 'building'
    return None, None


def love_overlay(H):
    """💗 overlay: every Venus–Mars contact among the hits (transiting Venus to natal Mars, or transiting Mars to natal
       Venus), any aspect and phase within the radar orb. It sits beside the ✅/⚠️ flavor and never changes it."""
    return [h for h in H if {h['body'], h['point']} == {'Venus', 'Mars'}]


def moon_times(natal, t0, t1):
    """Exact Moon aspects to natal points in [t0, t1) — the Moon times hours, it never sets the tone."""
    out = []
    for p, pl in natal.items():
        if p in ('DSC', 'IC'): continue
        for asp, ang in A.ASPECTS.items():
            for x in A.exact_times('Moon', pl, ang, t0, t1, step_min=10):
                pt, a2 = _label(p, asp)
                out.append((x, a2, pt, flavor('Moon', a2, pt), TAG.get(pt, '')))
    return sorted(set(out))


def angle_crossings(natal, t0, t1, lat, lon_east):
    """Times in [t0, t1) when a natal point sits exactly on the local ASC or MC.
       Natal Venus on the local ASC is flagged 🚪 (the 'door')."""
    out = []
    for p, pl in natal.items():
        if p in ('ASC', 'MC', 'DSC', 'IC'): continue
        for i, ang in ((0, 'ASC'), (1, 'MC')):
            for x in A.roots(lambda t: A.sep(A.angles(t, lat, lon_east)[i], pl), t0, t1, step_min=5):
                out.append((x, p, ang, '🚪' if (p == 'Venus' and ang == 'ASC') else ''))
    return sorted(out)


def saturn_station(natal, t, window_days=2, search_days=40):
    """Saturn-station points: find the speed sign change nearest t (±search_days). If the station longitude
       sits ≤1° from an exact aspect to a natal point → 10, ≤3° → 8, and t is within ±window_days of it."""
    best = None; a = t - dt.timedelta(days=search_days); va = A.speed('Saturn', a)
    while a < t + dt.timedelta(days=search_days):
        b = a + dt.timedelta(days=1); vb = A.speed('Saturn', b)
        if va * vb < 0:
            lo, hi = a, b
            for _ in range(25):
                m = lo + (hi - lo) / 2
                if A.speed('Saturn', lo) * A.speed('Saturn', m) <= 0: hi = m
                else: lo = m
            best = lo
        a, va = b, vb
    if best is None: return 0, None
    l = A.lon('Saturn', best); near = None
    for p, pl in natal.items():
        if p in ('DSC', 'IC'): continue
        for asp, ang in A.ASPECTS.items():
            o = A.orb(l, pl, ang)
            if o <= 3.0 and (near is None or o < near[0]): near = (o, asp, p)
    days = abs((best - t).total_seconds()) / 86400
    info = dict(time=best, lon=l, nearest=near, days_from=days)
    if near is None or days > window_days + 0.5: return 0, info
    return (10 if near[0] <= 1.0 else 8), info
