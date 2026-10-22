"""demo — every formula run once on two SYNTHETIC charts (random longitudes from a fixed seed; no dates,
no places). Transits are taken at the moment you run it. Run: python3 demo.py"""
import datetime as dt
import random
import astro_core as A
import bazi_core as Z
import radar_core as R
import attraction_core as T
import pair_core as P

rng = random.Random(7)
POINTS = ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars', 'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto', 'ASC', 'MC']
chart_a = {p: rng.uniform(0, 360) for p in POINTS}
chart_b = {p: rng.uniform(0, 360) for p in POINTS}
chart_a['DSC'] = (chart_a['ASC'] + 180) % 360; chart_b['DSC'] = (chart_b['ASC'] + 180) % 360
chart_b['Mars'] = (chart_a['Venus'] + 0.6) % 360           # plant one tight contact so the pair math has a hot spot
LAT, LON = 0.0, 0.0                                         # a neutral place for the local angles
now = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)

print("== SKY (chart A, now) ==")
H = R.hits(chart_a, now)
h, how = R.tone(H)
print("tone:", (h['body'], h['aspect'], h['point'], h['orb'], h['flavor'], how) if h else "none")
for x in H[:6]: print("  ", x['flavor'], x['body'], x['aspect'], x['point'], x['orb'], x['phase'], x['weight'])

print("\n== ATTRACTION (chart A, this moment) ==")
print("moment score:", round(T.moment(chart_a, now, LAT, LON), 3))

print("\n== PAIR (A × B) ==")
print("contacts (all, ≤1°):", P.contact_counts(chart_a, chart_b))
print("attraction family (B → A):", P.attraction_family(chart_b, chart_a))
spots = P.hot_spots(chart_a, chart_b)
print("hot spots:", {k: A.fmt(v) for k, v in spots.items()})
if spots:
    scaled, windows = P.timeline(spots, now, 60)
    print("next 60 days, top 3 by scale:", [(t.date().isoformat(), sc) for t, s, sc in sorted(scaled, key=lambda r: -r[1])[:3]])
p, lam = P.family_expected()
print("family under independence: p per pair %.4f · expected %.3f · P(≥2) %.4f" % (p, lam, P.poisson_tail(2, lam)))

print("\n== BAZI (today's day pillar, synthetic branch sets) ==")
g = Z.day_index(now.year, now.month, now.day, now.hour + now.minute / 60)
stem, branch = Z.STEMS[g % 10], Z.BRANCHES[g % 12]
own, other = ['子', '午', '卯', '酉'], ['寅', '申']
raw, sc, parts = Z.day_score(stem, branch, own, other, '甲', '子')
print("day", Z.pillar_name(g), "| raw", raw, "→", sc, Z.tier(sc))
for hb in "辰巳午未申":
    t, pts = Z.hour_score(hb, branch, own, other, '子')
    print("  hour", hb, t)

print("\n== CHANCE ==")
print("2 hits in 7 calls at p = 1/3 → P(≥2 by luck) = %.3f · Wilson 95%% CI for 2/7 = %s"
      % (P.binomial_tail(2, 7, 1 / 3), tuple(round(x, 3) for x in P.wilson(2, 7))))
