# THE MATH — every formula, with no charts inside
Pure calculation: no names, no dates, no birth data, no operating rules. Each section gives the equations first, then **↔ astrology**, which says what each piece of the math means in the tradition. The code in `code/` implements exactly these lines (41 tests, none of which uses a date).

## Symbols
| symbol | meaning |
|---|---|
| λ | ecliptic longitude in degrees, 0 ≤ λ < 360 (0 = 0° Aries) |
| t | a moment (UTC) |
| v | speed dλ/dt, degrees per day |
| δ | the angle between two longitudes, 0–180 |
| A | an aspect angle: 0, 60, 90, 120, 180 |
| o | orb = distance from an exact aspect |
| s, i | stem index 0–9 (甲 … 癸), branch index 0–11 (子 … 亥) |
| g | sexagenary index 0–59 (甲子 = 0) |
| e, p | element ⌊s/2⌋ (wood, fire, earth, metal, water) and polarity s mod 2 (yang 0, yin 1) |

---

## 1. Where the planets are
- λ_b(t): apparent geocentric ecliptic longitude of date, from the ephemeris (pyephem).
- v = [λ(t + ¼ d) − λ(t − ¼ d)] / ½ d (wrapped).
- Obliquity: ε = 23.439291° − 0.0130042° · T, with T = Julian centuries from J2000.
- Angles, from the local sidereal time θ and latitude φ:
  - MC = atan2(sin θ, cos θ · cos ε)
  - ASC = atan2(cos θ, −(sin ε · tan φ + cos ε · sin θ))
  - DSC = ASC + 180° · IC = MC + 180°
- Whole-sign houses: house(λ) = (⌊λ/30⌋ − ⌊ASC/30⌋) mod 12 + 1.

**↔ astrology:** λ is a planet's zodiac position — sign = ⌊λ/30⌋, degree = λ mod 30. v < 0 is retrograde; v = 0 is a station. The four angles are the chart's hinges: ASC (self, body), MC (career, public), DSC (partners), IC (home).

## 2. How two points relate (aspects)
- sep(a, b) = ((a − b + 180) mod 360) − 180 · δ = |sep(a, b)|
- o = |δ − A|, A ∈ {0 ☌, 60 ⚹, 90 □, 120 △, 180 ☍}
- applying ⇔ o(λ + v · 0.01 d) < o(λ) (the gap is closing at the body's own speed); otherwise separating.
- exact time = the root of f(t) = sep(λ(t), target), found by bisection on a sign change (to 30 s).

**↔ astrology:** ☌ conjunction = fusion · ⚹ sextile = opportunity · □ square = friction · △ trine = ease · ☍ opposition = polarity. A small orb is felt strongly. Applying means building; separating means fading.

## 3. The BaZi calendar
- Julian Day Number: a = ⌊(14 − m)/12⌋, y′ = y + 4800 − a, m′ = m + 12a − 3,
  JDN = d + ⌊(153m′ + 2)/5⌋ + 365y′ + ⌊y′/4⌋ − ⌊y′/100⌋ + ⌊y′/400⌋ − 32045
- Day pillar: g = (JDN + 49) mod 60 · stem = g mod 10 · branch = g mod 12. The day starts at 23:00 local.
- Hour branch: i = ⌊(h + 1)/2⌋ mod 12 (子 = 23:00–00:59, 丑 = 01:00–02:59, …).

**↔ astrology:** the 60-day cycle (甲子 … 癸亥). Ten stems = five elements × yin/yang; twelve branches = the twelve animals, which also name the twelve two-hour blocks of the day.

## 4. Branch relations — pure modular arithmetic
| relation | condition on branch indices i ≠ j |
|---|---|
| 冲 clash | i − j ≡ 6 (mod 12) |
| 合 six-combine | i + j ≡ 1 (mod 12) |
| 害 harm | i + j ≡ 7 (mod 12) |
| 刑 penalty | {i, j} inside {2, 5, 8} or {1, 7, 10}, or {i, j} = {0, 3} |
| 自刑 self-penalty | i = j ∈ {4, 6, 9, 11}; any other i = j is "same" |

More than one can hold at once (巳申 = 合 + 刑 · 寅巳 = 害 + 刑). Tested against the classical tables on all 132 ordered pairs.

**↔ astrology:** 冲 = a jolt (opposite animals) · 合 = a pull (harmony pair) · 害 = a rub · 刑 = a grind · 自刑 = tripping over your own stuff.

## 5. Stems against the day master (the ten gods)
- d = (e_stem − e_DM) mod 5; same polarity → the first name, opposite → the second:

| d | meaning | same polarity | opposite |
|---|---|---|---|
| 0 | same element | 比肩 | 劫財 |
| 1 | the DM produces it | 食神 | 傷官 |
| 2 | the DM controls it | 偏財 | 正財 |
| 3 | it controls the DM | 七殺 | 正官 |
| 4 | it produces the DM | 偏印 | 正印 |

- Stem combine (五合): s ↔ (s + 5) mod 10 → 甲己 · 乙庚 · 丙辛 · 丁壬 · 戊癸.

**↔ astrology:** the role a stem plays for a person — peers (0), output and expression (1), wealth (2), officer and pressure (3), resources and support (4).

## 6. Stars and luck pillars
- 咸池 (peach blossom) from the year branch: k = i_year mod 4 → peach = (9 − 3k) mod 12 → 申子辰 → 酉 · 巳酉丑 → 午 · 寅午戌 → 卯 · 亥卯未 → 子. Its frame = the other two branches of its trine: {peach + 4, peach + 8} (mod 12).
- Luck direction: forward ⇔ (male and yang year stem) or (female and yin year stem); otherwise backward.
- Start age (years) = days from the chart's moment to the nearest 節 (the Sun at 315°, 345°, 15°, …, every 30°) in the luck direction ÷ 3.
- The k-th luck pillar = g_month ± k (+ forward, − backward), each lasting 10 years.

**↔ astrology:** peach blossom = the charm / romance star. Luck pillars (大運) = the ten-year chapters of a life.

## 7. The daily friction score (DAILY v0.1)
Weights:

| relation | own chart | other chart |
|---|---|---|
| 冲 clash | 20 | 15 |
| 刑 penalty | 15 | 12 |
| 害 harm | 12 | 10 |
| 合 combine | 10 | 10 |
| 自刑 self-penalty | 12 | 10 |
| same | 6 | 10 |

- **Day:** S = 35 + Σ_{b ∈ own} W_own(day, b) + Σ_{b ∈ other} W_other(day, b) + 20·[day = peach] + 6·[day ∈ peach frame] + stem bonus + attraction points + Saturn-station points
  - own = the chart's distinct natal branches + its current luck-pillar branch (the luck branch counts on its own, even when it repeats a natal branch) · other = the other chart's distinct natal branches
  - stem bonus: +10 for the DM's combine partner and its 七殺 · +5 for 傷官, 偏印, 正印 · otherwise 0
  - attraction points: 🔥 +10 (+12 on the window's top day) · ✅ +5 · Saturn station: +10 / +8
- **Rescale:** S′ = clip(round((S − 60) · 2.2 + 20), 5, 100). **Tiers:** 🔴 ≥ 85 · 🟠 65–84 · 🟡 45–64 · 🟢 < 45.
- **Hour:** H = Σ_own W_own(hour, b) + Σ_other W_other(hour, b) + W_own(day, hour) + 8·[hour = peach].

**↔ astrology:** how charged a day (or hour) is between two charts. Each relation between today's branch and a chart's branches adds its weight; a clash on your own chart counts more than one on the other person's. The peach term adds charm; the stem bonus is how today's stem treats the day master (combine = pull, 七殺 = pressure, 傷官 = voice, 印 = support).

## 8. Radar — transits to one chart
- For every transiting body b (Sun..Pluto, Moon apart), natal point n, aspect A with o ≤ 3°:
  weight = R(b) · W(A) · F(phase) · (1 − ½ · o/3)
  - R: Saturn 5 · Uranus, Neptune, Pluto 4 · Jupiter 3 · Mars 2 · Sun, Mercury, Venus 1
  - W: ☌ 1 · ☍ 0.9 · □ 0.9 · △ 0.6 · ⚹ 0.5
  - F: exact (o ≤ 1°) 1 · applying (1–3°) ½ · fading (1–3°) ¼
- **Tone** = the heaviest exact hit; if none, the heaviest applying slow hit ("building"). Fading hits never set it.
- **✅ / ⚠️:** △ ⚹ ✅ · □ ☍ ⚠️ · ☌: Jupiter ✅, other slow bodies ⚠️; fast bodies ⚠️ if Mars, Saturn or an outer planet is on either side, else ✅.
- **Tags:** work (Sun, MC/IC, Mercury, Uranus) · love (Venus, DSC) · money (Jupiter) · body (Moon, Mars, ASC) · loss (Saturn, Neptune, Pluto).
- **Moon:** exact times to natal points (it colors hours, never the tone).
- **Angle crossings:** times a natal point sits exactly on the local ASC or MC; natal Venus on the local ASC = "door".
- **Saturn station:** the nearest speed sign change; +10 if the station is ≤ 1° from an exact aspect to a natal point, +8 if ≤ 3°, within ±2 days of it.

**↔ astrology:** slow planets are the long weather (Saturn heaviest); the Moon is hour-by-hour color; the door is the chart's own Venus rising over the horizon that day.

## 9. Attraction calendar (one chart)
- Moment score: M(t) = Σ_b [ Σ_{n ∈ Venus, Mars, Sun, Jupiter} B(b) · T(n) · c(b, n) + B(b) · T_axis · max_{n ∈ ASC/DSC axis} c(b, n) ] + 0.25·[Moon in a bonus sign] + 0.5·[natal Venus within 1° of the local ASC]
  - c(b, n) = max over aspects of F(A) · (1 − o/orb_b), 0 outside the orb
  - B: Venus 3 · Mars 2 · Jupiter 2 · Sun 1 · Moon 0.5 · T: Venus 1 · axis 1 · Mars 0.8 · Sun 0.6 · Jupiter 0.6
  - F: ☌ 1 · △ 0.8 · ⚹ 0.6 · ☍ 0.6 · □ 0.4 · orb 2° (Moon 3°)
  - bonus signs: the chart's 1st, 5th and 7th whole-sign houses + Libra
- Day score = the mean of M over the day, sampled every 10 minutes (144 samples).
- Flags within a reference window: 🔥 top 7% · ✅ top 20%. Scale = day / window max × 10.

**↔ astrology:** "pull" days — the love planets in the sky (Venus, Mars, plus Jupiter, the Sun and the Moon) touching the chart's Venus, Mars, Sun, Jupiter and its partnership axis.

## 10. Two charts
- **Synastry:** every pair (point in A, point in B) with o ≤ 3° (⚹ ≤ 2.5°).
- **Attraction family:** B's Venus or Mars in ☌ □ ☍ within 1° of A's Sun, Moon, Venus, Mars, ASC or DSC (2 × 6 = 12 pairs).
  - If longitudes were independent and uniform: P(one pair hits) = (1 + 2 + 1) exact angles × 2° / 360° = 8/360 ≈ 2.2% → expected count λ = 12 × 8/360 ≈ 0.267 → P(≥ 2) = 1 − e^(−λ)(1 + λ) ≈ 3.0%.
  - With real planet positions (Venus, Mars and the Sun are not independent), simulation over 4,000 random charts gives about 5.3% for ≥ 2.
- **Hot spots:** the midpoint of each tight ☌ (or ☍, taken as an axis) contact in the family.
- **Pair timeline:** P(t) = Σ_b Σ_spots Σ_A w_b · f_A · max(0, 1 − o/orb_b)
  - w, orb: Sun 1, 3° · Venus 3, 3° · Mars 3, 3° · Jupiter 2, 2°
  - f: ☌ and ☍ 1.0 · □ 0.7 · △ 0.5 · ⚹ 0.4
  - scale: day / the run's top day × 10 · windows: runs of days ≥ 50% of the top.
- **Random-chart null:** draw N random moments in a date range, compute the same count for each, and report the percentile (share below the real value) and p = (1 + #{random ≥ real}) / (N + 1).

**↔ astrology:** synastry is how two charts touch; the family is the classic "chemistry" set; a hot spot is a degree that lights up again whenever a planet in the sky passes over it.

## 11. The monthly engine (THE ONE FORMULA v1.5)
- k = map row (signal × area) · a = area (8) · t = month · f = family (9)
- x_k(t) ∈ [0, 1]: the share of month t that row k is active.
- **Layer 2 (life history):** w(k, a) = w⁰(k, a) · (1 + β · u(k, a)), β = 0.5 (so w/w⁰ ∈ [0.5, 1.5])
  - u = clip( n₁/(n₁ + κ) · log₁₀(r̄₁/r̄₀) / log₁₀ 2, −1, 1 ), κ = 12
  - r̄₁ = (S₁ + ½)/(n₁ + 1), r̄₀ = (S₀ + ½)/(n₀ + 1), over months τ < t
  - n₁ = Σ x_k(τ), S₁ = Σ x_k(τ) · size_a(τ), n₀ = Σ (1 − x_k(τ)), S₀ = Σ (1 − x_k(τ)) · size_a(τ)
- **Layer 1 (reading):** P_f(a, t) = Σ_{k ∈ f, sign +} x_k(t) · w(k, a) · N_f(a, t) = Σ_{k ∈ f, sign −} x_k(t) · w(k, a)
  - σ_f = SD of (P_f + N_f) over the 8 areas × 1,080 reference months (σ_f = 0 → 1)
  - R⁺ = Σ_f d_f · P_f / σ_f · R⁻ = Σ_f d_f · N_f / σ_f · d_f = 1
- **Master line:** Act = R⁺ + R⁻
  - p = mid-rank percentile of Act(a, t) among Act(a, τ) for the 1,080 reference months: (#less + ½ · #equal) / n
  - step = #{c ∈ (0.25, 0.50, 0.75, 0.90) : p > c} → ⬇️ ➖ 🔥 🔥🔥 🔥🔥🔥
  - flavor φ = R⁺ / (R⁺ + R⁻): ≥ ⅔ ✅ · ≤ ⅓ 🛡️ · else ⚡ · Act = 0 → no icon
  - voices per family: support (P > N) · pressure (N > P) · split (P = N > 0) · silent (P = N = 0)
- **v1.5's aspect family:** for the slow five (Jupiter–Pluto) × 5 aspects × 9 natal points: firing 1 at o ≤ 1° (applying or separating), ½ at 1–3° applying, 0 otherwise.
- **Map:** 345 rows (Zi Wei 102 · BaZi 57 · Western transits 50 · Western aspects 50 · numbers 22 · annual profections 20 · Vedic dasha 20 · Mahabote 14 · secondary progressions 10); w⁰ ∈ {0.10, 0.05, 0.025}.
- **Layer 3 (honesty test):**
  - nulls: random charts · the event log shuffled across months · random charts close in age
  - p = (1 + #{null score ≥ real score}) / (N + 1) for each null; score = the walk-forward log score (fit on earlier data only, predict the next period)
  - BSS = 1 − Brier(engine) / Brier(base rate)
  - ✅ iff p_chart, p_dates and p_age are all ≤ 0.05 and BSS > 0 · ❌ iff some p > 0.05 and the power to detect a planted 2× effect (95% lower bound) ≥ 0.80 · otherwise ⬜

Code: `code/monthly_core.py` · table: `tables/coefficients_v1.5.csv`.

**↔ astrology:** each map row is one tradition's claim — "signal X supports (or pressures) life area Y, weight w⁰." Layer 2 checks each claim against the person's own past and lets it move by up to ±50%, shrunk toward the tradition when there's little history (κ). Layer 1 adds the claims up across nine traditions, each scaled to the same spread so no single system shouts. The fire says how busy a month is compared with the rest of that same life. The honesty test asks whether the whole machine beats random charts and shuffled dates.

## 12. Judging fit — chance math
- Hit rate vs luck: P(X ≥ k) = Σ_{i=k..n} C(n, i) · pⁱ · (1 − p)^(n−i).
  - Worked example: 2 hits in 7 calls when luck gives 1 in 3 → P(≥ 2) = 1 − (2/3)⁷ − 7 · (1/3) · (2/3)⁶ ≈ 0.737 — luck alone does this about 74% of the time.
- 95% Wilson interval for k/n: (p̂ + z²/2n ± z · √(p̂(1 − p̂)/n + z²/4n²)) / (1 + z²/n), z = 1.96 → 2/7 gives 8%–64%.
- Null percentile and p-value: as in §10.

**↔ astrology:** a formula only "fits" if it beats what luck or random charts would do. Story readings always seem to fit, which is why they are never scored.

---

## Code map
| file | what it implements |
|---|---|
| `code/astro_core.py` | §1–2: longitudes, speed, obliquity, ASC/MC, separation, orbs, applying test, exact-time roots, chart points |
| `code/bazi_core.py` | §3–7: JDN, day/hour pillars, branch relations, ten gods, combine, peach blossom, luck pillars, daily day/hour scores, rescale, tiers |
| `code/radar_core.py` | §8: hits, tone, flavor, Moon times, angle crossings, door, Saturn station |
| `code/attraction_core.py` | §9: moment score, day score, flags, daily points |
| `code/pair_core.py` | §10, §12: synastry, attraction family, expectation, hot spots, pair timeline, random-chart null, binomial, Wilson |
| `code/test_pure_math.py` | 27 tests: the formulas reproduce the classical tables, the calendar formula against its own inverse at random day numbers, the Sun against an independent formula at random moments, and hand-worked synthetic cases |
| `code/demo.py` | every formula once, on two synthetic charts (random longitudes), with transits taken when you run it |
| `code/monthly_core.py` | §11: the coefficient table loader, Layer 2, Layer 1, master line, flavor, voices, the aspect family, and the honesty decision (p-value, Brier skill, verdict, power bound) |
| `code/test_monthly_core.py` | 14 tests on synthetic firing and a random toy log |
| `tables/coefficients_v1.5.csv` | the 345-row coefficient table: id, family, signal, area, sign, w⁰, grade |

Run:
```
cd code && python3 -m unittest test_pure_math -v && python3 demo.py
cd code && python3 -m unittest test_monthly_core -v
```
Needs Python 3 + `pip install ephem`.

**Notes.** The pair timeline here uses the same apparent longitude as the radar; an older script used pyephem's astrometric-of-date position (day scores differ by at most ~0.004). `monthly_core.py` is a clean rewrite of the full monthly engine's formula functions; on synthetic inputs it gives exactly the engine's numbers (40 area-months, 0 differences; aspect firing identical on 200 random days).
