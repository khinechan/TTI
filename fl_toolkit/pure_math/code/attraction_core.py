"""attraction_core — the single-chart attraction calendar. The natal chart, the place and the time zone
are inputs.

moment score M(t) = Σ_bodies [ Σ_single targets B·T·c  +  B·T_axis·max_axis c ]
                    + 0.25·[Moon in a bonus sign] + 0.5·[natal Venus within 1° of the local ASC]
   c = max over aspects of F(aspect) · (1 − orb/orb_max)       (0 outside the orb)
day score = mean of M over the local day, sampled every 10 minutes
flags     = 🔥 top 7% / ✅ top 20% of days in a reference window · scale = day / window max × 10"""
import datetime as dt
import math
import astro_core as A
from bazi_core import round_half_up

PARAMS = {
    'body_w':   {'Venus': 3.0, 'Mars': 2.0, 'Jupiter': 2.0, 'Sun': 1.0, 'Moon': 0.5},
    'target_w': {'Venus': 1.0, 'AXIS': 1.0, 'Mars': 0.8, 'Sun': 0.6, 'Jupiter': 0.6},
    'aspect_f': {'☌': 1.0, '△': 0.8, '⚹': 0.6, '☍': 0.6, '□': 0.4},
    'orb':      {'Venus': 2.0, 'Mars': 2.0, 'Jupiter': 2.0, 'Sun': 2.0, 'Moon': 3.0},
    'moon_sign_bonus': 0.25,
    'door_bump': 0.5, 'door_orb': 1.0,
    'sample_min': 10,
}
SINGLE = ('Venus', 'Mars', 'Sun', 'Jupiter')


def bonus_signs(natal):
    """Moon-sign bonus signs: the chart's 1st, 5th and 7th whole-sign houses + Libra."""
    a = int(natal['ASC'] // 30)
    return {a % 12, (a + 4) % 12, (a + 6) % 12, 6}


def axis_points(natal, lat=None, lon_east=None, chart_t=None):
    """The relationship axis: natal ASC and DSC (+ the DSC recast for another place, if given)."""
    pts = {'ASC': natal['ASC'], 'DSC': (natal['ASC'] + 180) % 360}
    if chart_t is not None and lat is not None:
        pts['local-DSC'] = (A.angles(chart_t, lat, lon_east)[0] + 180) % 360
    return pts


def _contact(tr, point, body, P):
    best = 0.0; ob = P['orb'][body]
    for a, ang in A.ASPECTS.items():
        o = A.orb(tr, point, ang)
        if o <= ob: best = max(best, P['aspect_f'][a] * (1.0 - o / ob))
    return best


def moment(natal, t, lat, lon_east, axis=None, P=PARAMS):
    axis = axis or axis_points(natal); bs = bonus_signs(natal); total = 0.0
    for body, bw in P['body_w'].items():
        l = A.lon(body, t)
        for tg in SINGLE:
            total += bw * P['target_w'][tg] * _contact(l, natal[tg], body, P)
        total += bw * P['target_w']['AXIS'] * max(_contact(l, pt, body, P) for pt in axis.values())   # axis counts once
        if body == 'Moon' and int(l // 30) in bs: total += P['moon_sign_bonus']
    if A.distance(A.angles(t, lat, lon_east)[0], natal['Venus']) <= P['door_orb']: total += P['door_bump']
    return total


def day_score(natal, day_start, lat, lon_east, axis=None, P=PARAMS):
    """Mean moment score over 24 h from day_start (an aware datetime at local midnight)."""
    step = dt.timedelta(minutes=P['sample_min']); t = day_start; v = []
    while t < day_start + dt.timedelta(days=1):
        v.append(moment(natal, t, lat, lon_east, axis, P)); t += step
    return sum(v) / len(v)


def flags(cal):
    """cal = {day: score}. 🔥 = top 7% · ✅ = top 20% · scale = score / max × 10."""
    vals = sorted(cal.values(), reverse=True); n = len(vals)
    fire = vals[max(0, math.ceil(0.07 * n) - 1)]; ok = vals[max(0, math.ceil(0.20 * n) - 1)]; top = vals[0] or 1.0
    return {d: ('🔥' if v >= fire else '✅' if v >= ok else '', round_half_up(v / top * 10, 1)) for d, v in cal.items()}


def daily_points(flag, scale):
    """Points the daily friction score takes: 🔥 → +10 (+12 on the top day, scale ≥ 9.5) · ✅ → +5."""
    if flag == '🔥': return 12 if scale >= 9.5 else 10
    return 5 if flag == '✅' else 0
