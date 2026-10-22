# THE MATH — every formula, with no charts inside
Pure calculation: no names, no dates, no birth data, no operating rules. Each section gives the equations first, then **↔ astrology**, which says what each piece of the math means in the tradition. The code in `code/` implements exactly these lines (TESTS_CODE tests, none of which uses a date; `daily.py`'s date-level tests sit beside it: TESTS_DAILY more).

**v2 (2026-10-22).** The audit's fixes and additions are written into the sections they touch, each marked **v2**; anything outside the original math is marked **STD**. New sections: §13 outfit color (STD) and §14 time-free A. `CHANGES.md` lists every number that moved.

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
- Equation of time (**STD**, for the optional true-solar-time blocks of §3): EoT(t) = apparent − mean solar time = (GAST − α_☉ + 12 h) − UT, wrapped to ±12 h, in minutes.

**↔ astrology:** λ is a planet's zodiac position — sign = ⌊λ/30⌋, degree = λ mod 30. v < 0 is retrograde; v = 0 is a station. The four angles are the chart's hinges: ASC (self, body), MC (career, public), DSC (partners), IC (home). EoT is how far a sundial runs ahead of the clock (about −14 to +16 minutes over the year).

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
- Hour pillar (**STD**, 五鼠遁): hour stem = (2 · (s_day mod 5) + i_hour) mod 10 — a 甲 or 己 day's 子 hour is 甲子, 乙/庚 → 丙子, 丙/辛 → 戊子, 丁/壬 → 庚子, 戊/癸 → 壬子.
- **The day as `daily.py` samples it (v2).** Local wall-clock slots every 10 min from 23:00 on the evening before to 22:50: 144 slots, slot k at 23:00 + 10k min. Hour block i = slots 12i … 12i + 11 (子 = slots 0–11 = 23:00–00:59). Daylight saving: a wall time that never happens (spring forward) is **skipped**; a wall time that happens twice (fall back) is sampled at **both** instants with weight **½** each. Every mean is Σ w·M / Σ w. So a fall-back day has 150 instants and 144 effective samples, and a spring-forward day has 138 of each (it is 23 hours long). v1 sampled the calendar day 00:00–23:50, so the day was an hour late and the 子 block saw only 00:00–00:59 (6 samples).
- True solar time (**STD**, `--solar-time`, off by default): τ = UT + λ_E/15 h + EoT. The hour blocks are cut on τ (子 = τ 23:00–00:59); the instant of τ is UT = τ − λ_E/15 − EoT (EoT taken at local noon; it moves under 30 s in a day). At Frederick (λ_E = −77.41°) the clock runs 9.6 min − EoT ahead of τ in standard time and 69.6 min − EoT ahead in daylight time — so in summer the edges move about an hour, not the "≤ 25 min" the audit estimated without daylight time. Only the hour-block edges move (block pulls and their labels); the day's pull, flags and charge stay on the clock day above.

**↔ astrology:** the 60-day cycle (甲子 … 癸亥). Ten stems = five elements × yin/yang; twelve branches = the twelve animals, which also name the twelve two-hour blocks of the day. The Chinese day turns at 23:00, the start of the 子 hour, so the night's 子 block belongs to the next day. Classical practice reads the hour on the sun, not the clock — that is the true-solar-time option.

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

- **Day:** S = 35 + Σ_{b ∈ own} ω_b·W_own(day, b) + Σ_{b ∈ other} ω_b·W_other(day, b) + 20·[day = peach] + 6·[day ∈ peach frame] + stem bonus + attraction points + Saturn-station points
  - own = the chart's distinct natal branches + its current luck-pillar branch (the luck branch counts on its own, even when it repeats a natal branch) · other = the other chart's distinct natal branches
  - ω_b = 1, except (all **v2**): with `--luck-repeat-weight w` a luck branch that repeats a natal branch has ω = w (default 1 = v0.1) · time-free A on a day her charts split between two luck pillars: each pillar's branch has ω = its share of the charts (§14) · with `--year-month-terms` (**STD**, off by default) today's 流年 and 流月 branches join *other* with ω = ½ (read at local noon: the month turns at each jie, the year at 立春)
  - stem bonus — the table `STEM_BONUS` (values unchanged since v0.1):

    | today's stem, as seen by the DM | points | sub-score |
    |---|---|---|
    | its 五合 combine partner | +10 | bond |
    | 七殺 | +10 | friction |
    | 傷官 | +5 | friction |
    | 偏印, 正印 | +5 | bond |
    | 食神, 偏財, 正財, 正官, 比肩, 劫財 | 0 | — |

    Why these values: the bonus scores how hard today's stem works on the day master. The combine partner binds it and 七殺 attacks it unchecked — the two strongest pulls (+10). 傷官 (output that defies the officer) and the two 印 (resource stems that feed the DM) stir it less (+5). The rest the DM deals with on its own terms (0). 印 adding charge reads as being held or fed — involvement, not conflict — which is why the split below files it under bond. These are DAILY v0.1 design choices, not a classical table.
  - attraction points: 🔥 +10 (+12 on the window's top day) · ✅ +5 · Saturn station: +10 / +8
- **Rescale:** S′ = clip(round_half_up((S − 60) · 2.2 + 20), 5, 100), computed on the decimal value (**v2**: v1 used Python's round-half-to-even; an integer S never lands on a half, so no v1 value moves — the rule matters for the non-integer S that the weights ω and §13 can make). **Tiers:** 🔴 ≥ 85 · 🟠 65–84 · 🟡 45–64 · 🟢 < 45.
- **Split (v2):** friction = Σ 冲 刑 害 自刑 points + the 七殺 / 傷官 bonus · bond = Σ 合 and same points + 咸池 day and frame + the combine / 印 bonus · attraction_points. friction + bond + attraction_points = S − 35 − Saturn points.
- **Percentile tiers (v2):** charge_pct = the mid-rank percentile (#less + ½·#equal)/n of today's raw S among the window's 365 days, computed with the same options; tier_pct = 🔴 ≥ 0.90 · 🟠 0.75–0.90 · 🟡 0.50–0.75 · 🟢 < 0.50. S′ and its tier are unchanged. (S′ saturates: over the 2026-10-20 window A sits at 100 on 50 days and at 5 on 72 — time-free default; 49 and 76 with `--a-time noon` — and B on 50 and 32.)
- **Hour:** H = Σ_own ω·W_own(hour, b) + Σ_other ω·W_other(hour, b) + W_own(day, hour) + 8·[hour = peach]. H is raw points — no base and no rescale — so **v2** also prints it as `points`, with points_pct = its percentile among all 365 × 12 hour blocks of the window. (The old `charge` key of an hour keeps the same number.)

**↔ astrology:** how charged a day (or hour) is between two charts. Each relation between today's branch and a chart's branches adds its weight; a clash on your own chart counts more than one on the other person's. The peach term adds charm; the stem bonus is how today's stem treats the day master (combine = pull, 七殺 = pressure, 傷官 = voice, 印 = support). The split says which kind of charge it is: friction (clash, penalty, harm, pressure) or bond (combine, sameness, charm, support). 流年 / 流月 are the year's and month's own branches — the "weather" of the year and month.

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
- **Saturn station:** the nearest speed sign change; +10 if the station is ≤ 1° from an exact aspect to a natal point, +8 if ≤ 3°, within ±2 days of it. (**v2:** these points now enter A's charge with C exactly as they enter A's charge with B — it is the same chart's property; v1 passed 0 for A with C.)
- **Love overlay 💗 (v2):** every hit whose (transiting body, natal point) is {Venus, Mars}, either direction, any aspect and phase within the 3° orb. It sits beside ✅/⚠️ and never changes them: transiting Venus ☌ natal Mars stays ⚠️ (intense) and is also 💗.

**↔ astrology:** slow planets are the long weather (Saturn heaviest); the Moon is hour-by-hour color; the door is the chart's own Venus rising over the horizon that day.

## 9. Attraction calendar (one chart)
- Moment score: M(t) = Σ_b [ Σ_{n ∈ Venus, Mars, Sun, Jupiter} B(b) · T(n) · c(b, n) + B(b) · T_axis · max_{n ∈ ASC/DSC axis} c(b, n) ] + 0.25·[Moon in a bonus sign] + 0.5·[natal Venus within 1° of the local ASC]
  - c(b, n) = max over aspects of F(A) · (1 − o/orb_b), 0 outside the orb
  - B: Venus 3 · Mars 2 · Jupiter 2 · Sun 1 · Moon 0.5 · T: Venus 1 · axis 1 · Mars 0.8 · Sun 0.6 · Jupiter 0.6
  - F: ☌ 1 · △ 0.8 · ⚹ 0.6 · ☍ 0.6 · □ 0.4 · orb 2° (Moon 3°)
  - bonus signs: the chart's 1st, 5th and 7th whole-sign houses + Libra
- Day score = the mean of M over the day, sampled every 10 minutes (144 samples). **v2:** over the BaZi day of §3 (23:00 the evening before to 22:50), Σ w·M / Σ w with the daylight-saving weights; a block's pull is the same mean over its own slots.
- Flags within a reference window: 🔥 top 7% · ✅ top 20%. Scale = day / window max × 10, rounded half up to 0.1.
- **Reference (v2):** the window's 365 day scores are cached per window (`ref_<start>.json`, format v2: each day's score and Saturn points, the cut points, the chemistry); a cache in the old format is rebuilt, so a deleted cache rebuilds to the same numbers.
- **Long-run percentile (v2):** pull_pct_longrun = the mid-rank percentile of today's hourly mean (the 24 on-the-hour slots of today's grid) among the hourly means of every day 2020-01-01 … 2040-12-31. It never resets on Oct 20, so it compares across years.

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
- **The day's chemistry (v2):** P at local noon (America/New_York) — v1 read 16:00 UTC, which is 11:00 in standard time. scale = min(10, round_half_up(P / window top × 10, 1)), `above_window_max` = [P > window top], raw always printed. day_max = the largest P at the BaZi day's 24 hourly wall-clock instants (daylight saving as in §3; the earliest wins a tie), with its local time. chem_pct_longrun = the percentile of the noon P among the noon P of every day 2020–2040.
- **Random-chart null:** draw N random moments in a date range, compute the same count for each, and report the percentile (share below the real value) and p = (1 + #{random ≥ real}) / (N + 1).

**↔ astrology:** synastry is how two charts touch; the family is the classic "chemistry" set; a hot spot is a degree that lights up again whenever a planet in the sky passes over it. Noon is the honest single reading for a day; day_max says when the hot spot burns brightest.

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

## 13. Outfit color (STD)
A story mechanic, off unless an outfit is passed. It is built on standard five-element color rules, and it moves the numbers only because this model defines it to — so it can never show that colors "really" matter. Code: `code/strength_core.py` (13.3–13.4, shared with the readings) and `code/color_core.py`.

### 13.1 Colors → elements (`COLORS`, editable; every row sums to 1)
| element | colors |
|---|---|
| wood 1.0 | green, forest green, dark green |
| wood/water | sea green (0.7 wood, 0.3 water) · teal (0.6, 0.4) |
| wood/earth | olive (0.5, 0.5) · olive brown (0.3 wood, 0.7 earth) |
| fire 1.0 | red, orange, orange-red, pink, purple |
| fire mixes | burgundy (0.7 fire, 0.3 water) · russet brown (0.7 earth, 0.3 fire) |
| earth 1.0 | brown, dark brown, khaki, tan, beige, camel, yellow, mustard |
| earth/metal | cream (0.5, 0.5) · ivory (0.8 metal, 0.2 earth) |
| metal 1.0 | white, pearl, silver, grey, gold |
| metal/water | charcoal (0.6 metal, 0.4 water) |
| water 1.0 | black, navy, dark blue, royal blue, blue, denim |
| water/wood | light blue (0.6 water, 0.4 wood) |

An unknown color (or slot) is an error that lists the known tokens.

### 13.2 Outfit vector
- Slot coverage c: top 0.55 · bottom 0.30 · peek (an under-layer that shows) 0.10 · shoes 0.05 · accessory 0.05.
- E[e] = Σ_g c_g · w(color_g, e) / Σ_g c_g, so Σ_e E[e] = 1.

### 13.3 Element totals of a chart (hidden stems)
- Visible stems count 1.0 to their element (e = ⌊s/2⌋), the day master itself excluded.
- Branches count through their hidden stems: 子 癸 · 丑 己癸辛 · 寅 甲丙戊 · 卯 乙 · 辰 戊乙癸 · 巳 丙庚戊 · 午 丁己 · 未 己丁乙 · 申 庚壬戊 · 酉 辛 · 戌 戊辛丁 · 亥 壬甲, weighted 1 → [1.0], 2 → [0.7, 0.3], 3 → [0.6, 0.3, 0.1].
- The month branch counts × 2.0 (season). A missing hour pillar is skipped and the result is PARTIAL.

### 13.4 Strength and favorability
- Families relative to the day master's element d: peer = d · resource generates d · output = what d generates · wealth = what d controls · officer controls d (generating wood→fire→earth→metal→water→wood, control wood→earth→water→fire→metal→wood).
- S = (peer + resource) / Σ totals. Weak S < 0.45: F = +1 for peer and resource, −1 for output, wealth, officer · strong S > 0.55: the reverse · balanced: 0.
- Season: month branch ∈ 申酉戌亥子丑 → F[fire] + 0.5 · ∈ 巳午未 → F[water] + 0.5. Clip F to [−1, 1].
- The pack's charts: A (庚申 · 甲申 · 壬申, no hour, PARTIAL) — totals wood 1.0 · fire 0 · earth 0.4 · metal 3.4 · water 1.2, S = 0.7667 strong, F = wood +1, fire +1, earth +1, metal −1, water −1. B (己巳 · 癸酉 · 甲戌 · 丁卯) — wood 1.0 · fire 1.7 · earth 1.7 · metal 2.6 · water 1.0, S = 0.25 weak, F = wood +1, water +1, fire −0.5, earth −1, metal −1.

### 13.5 Wearer
- W = Σ_e E[e] · F_wearer[e] ∈ [−1, 1] · raw′ = raw − K_SELF · W (K_SELF = 10) · charge′ = the §7 rescale of raw′ and its tier (time-free split day: the share-weighted per-pillar S′, §14).

### 13.6 Viewer
- Taste: T = the coverage share of garments in the palette of the viewer's natal Venus sign (Aries red · Taurus green, pink · Gemini yellow, light blue · Cancer silver, white, pearl, cream, sea green · Leo gold, orange · Virgo navy, brown, green · Libra pink, light blue · Scorpio black, burgundy · Sagittarius purple · Capricorn brown, black, grey · Aquarius teal, royal blue · Pisces sea green, purple).
- V = ALPHA · Σ_e E[e] · F_viewer[e] + (1 − ALPHA) · T (ALPHA = 0.7); m = 1 + K_VIEW · V (K_VIEW = 0.25).
- Seen blocks (default 辰巳午未申, 07:00–16:59; `--seen` overrides): a block's pull′ = min(10, pull · m); the day pull′ = min(10, Σ w·M·(m in a seen block, else 1) / Σ w / top × 10) over the §3 slots. Other blocks do not change; a zero-pull day stays zero.

### 13.7 Role tag (a label, no number)
The dominant element of E (a tie goes to the earlier of wood, fire, earth, metal, water), as its family relative to the viewer's and to the wearer's day master: output = play, enjoyment · wealth = warmth, desire · officer = duty, husband (for a woman), rules · resource = comfort, care · peer = sameness, rivalry.

**↔ astrology:** clothes as elements — green is wood, red is fire, and so on. A color the wearer's chart "wants" (a favorable element) calms their own charge; a color the viewer's chart wants, or one their Venus sign likes, warms the viewer's pull while they can see the wearer. The role tag says what the color means between them.

## 14. Time-free A (v2 default)
A has no birth time, and none is pinned: every A number is the mean over the hours she could have been born in.
- Her possible charts: t_k = 00:00 + 10k min local (America/Indiana/Indianapolis) on her birth date, k = 0 … 118 (00:00–19:40; the window stops before 7:45 PM, where her Mars–B's Venus orb passes the 1° family orb). Each chart has its own body longitudes λ_b(t_k) — no Moon, ASC or hour pillar (PARTIAL) — and its own luck start a₀(k) = (t_k − the previous jie)/3 days (her luck runs backward). Her pillars and luck names are the same for every k: no jie and no 23:00 day flip falls inside the window.
- Pull: M̄(t) = (1/119) Σ_k M_k(t), computed exactly: with orbs ≤ 3° no two aspects are in orb at once, so c(b, n) = Σ_A F(A) · max(0, 1 − |n − (λ_b ± A)|/orb), and the mean of each tent over the sorted λ_k is a prefix-sum lookup. The door term is the share of charts whose Venus is within 1° of the local ASC.
- Chemistry: P̄(t) = (1/119) Σ_k P(t; the hot spots of chart k).
- Flags, scales and percentiles compare against references built the same way (`ref_<start>_tf.json`, `ref_longrun_…_tf.json`).
- Luck: s_p = #{k : chart k is in pillar p on the day} / 119. S′ = round_half_up(Σ_p s_p · S′_p) — for her charge with B and with C; raw S and its parts carry each pillar's luck terms at weight s_p (§7's ω); an hour's H = round_half_up(Σ_p s_p · H_p). The shares are printed (`luck_shares`).
- The averaged chart λ̄_b = atan2(Σ_k sin λ_b(t_k), Σ_k cos λ_b(t_k)) — the circular mean of each planet — is used for exact transits (radar hits, tone, love overlay), the door and the Saturn station.
- Moon times: for each (aspect, point), the earliest–latest exact time over the 119 charts, with (n/119) when only n of them fall inside the day.
- `--a-time noon` keeps the v1 noon stand-in for comparison.
- C: none of the book's numbers depend on C's birth time. C enters only through his year, month and day branches (the *other* set of A with C); his date sits far from a jie (立春 on Feb 4, 驚蟄 on Mar 6), so any birth time before 23:00 gives the same three pillars (丁巳 · 壬寅 · 壬寅). Only a birth at 23:00 or later would flip his day pillar to 癸卯. His planets are never read.

**↔ astrology:** without a birth time the honest chart is a range, not a point. Averaging over her possible hours keeps every number true to what the chart can actually claim; on the days her ten-year luck pillar changes, the change arrives gradually, as a share of the possible charts.

---

## Code map
| file | what it implements |
|---|---|
| `code/astro_core.py` | §1–2: longitudes, speed, obliquity, ASC/MC, separation, orbs, applying test, exact-time roots, chart points, equation of time |
| `code/bazi_core.py` | §3–7: JDN, day/hour pillars, branch relations, ten gods, combine, peach blossom, luck pillars, STEM_BONUS, daily day/hour scores, rescale (half up), tiers, the friction/bond split |
| `code/radar_core.py` | §8: hits, tone, flavor, love overlay, Moon times, angle crossings, door, Saturn station |
| `code/attraction_core.py` | §9: moment score, day score, flags, daily points |
| `code/pair_core.py` | §10, §12: synastry, attraction family, expectation, hot spots, pair timeline, random-chart null, binomial, Wilson |
| `code/test_pure_math.py` | 27 tests: the formulas reproduce the classical tables, the calendar formula against its own inverse at random day numbers, the Sun against an independent formula at random moments, and hand-worked synthetic cases |
| `code/demo.py` | every formula once, on two synthetic charts (random longitudes), with transits taken when you run it |
| `code/monthly_core.py` | §11: the coefficient table loader, Layer 2, Layer 1, master line, flavor, voices, the aspect family, and the honesty decision (p-value, Brier skill, verdict, power bound) |
| `code/test_monthly_core.py` | 14 tests on synthetic firing and a random toy log |
| `code/strength_core.py` | §13.3–13.4 (STD): hidden-stem element totals, strength, favorability |
| `code/color_core.py` | §13 (STD): color table, outfit vector, taste, wearer and viewer effects, role tag |
| `code/test_strength_core.py`, `code/test_color_core.py` | the §13 math on synthetic inputs and the pack's two pillar sets |
| `code/test_v2_core.py` | v2 core additions: round half up, STEM_BONUS, weighted members, sub-scores, hour pillar, love overlay, EoT vs Meeus |
| `tables/coefficients_v1.5.csv` | the 345-row coefficient table: id, family, signal, area, sign, w⁰, grade |

Run:
```
cd code && python3 -m unittest test_pure_math test_monthly_core test_strength_core test_color_core test_v2_core && python3 demo.py
cd ../.. && python3 -m unittest test_daily test_daily_color test_audit_book      (date-level: daily.py, §13, the book audit)
```
Needs Python 3 + `pip install ephem`.

**Notes.** The pair timeline here uses the same apparent longitude as the radar; an older script used pyephem's astrometric-of-date position (day scores differ by at most ~0.004). `monthly_core.py` is a clean rewrite of the full monthly engine's formula functions; on synthetic inputs it gives exactly the engine's numbers (40 area-months, 0 differences; aspect firing identical on 200 random days).
