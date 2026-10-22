# CHANGES — fl_toolkit v2 (2026-10-22)

From `fl_toolkit.zip` sha256 `9577a72473c69cce3f51cc2c447f7250f02b73509eef1af2e6b0b990f2310982` (41/41 tests green on arrival).
Built and checked with Python 3.11 and ephem 4.2.1; the goldens are tied to that ephem build.

## The short version
- **A default run now differs from v1 in exactly two ways:** the P1 bug fixes (below), and the last step — **A is time-free** (the mean of her 119 possible charts, 00:00–19:40; `--a-time noon` gives the old noon stand-in, with the P1 fixes).
- Everything else is **new keys** (the old keys keep their meaning) or **flags that are off by default**. Besides the keys named item by item below, every run prints `a_chart` (which A chart was used), and a run with any non-default option prints `options`.
- Your time-free check values all reproduce **exactly** under your v1 conventions — see `robustness/time_free_check.md`.
- Tests: 41 → **146** (41 + 105 new: 88 date-free in `pure_math/code`, 58 date-level beside daily.py). Goldens for the five days, in both A-chart modes.

## What changed in a default run, and why
| change | item | effect on the book's numbers |
|---|---|---|
| Pull samples the BaZi day, 23:00 the evening before → 22:50 (was the calendar day 00:00 → 23:50); the 子 block gets all 12 samples | P1.1 | pull and block pulls move a little (mostly ±0.1); A's 子 block on 10-21: 1.0 → 1.1 with `--a-time noon` (1.4 by default, time-free) |
| Daylight saving: a missing wall time is skipped, a repeated one is sampled at both instants, ½ weight each | P1.5 | only 2026-11-01 and 2027-03-14 type days |
| The reference caches are rebuilt with the new sampling (else a deleted cache would rebuild to different numbers); old-format caches are never trusted | P1.1/P1.5, item 9 | every window's cut points moved (table below), so pull scales and flags move with them |
| Saturn-station points enter A with C exactly as A with B | P1.2 | A with C moves only on A's station days: 2027-08-07 … 08-11 (+8) |
| Chemistry scale capped at 10.0; `above_window_max`; raw always printed | P1.3 | 2026-09-08: 14.3 → 10.0 (raw 5.29 noon A / 5.32 time-free, flag true) |
| Chemistry read at local noon (was 16:00 UTC = 11:00 EST in winter); the window's pair_top likewise | P1.4 | winter days only, e.g. 2026-11-01 raw 0.31 → 0.29 (noon A; 0.32 time-free) |
| Round half up for every score (`rescale`, every scale) | P1.6 | none on these days (an integer S never lands on a half); matters for weighted / color terms |
| **A time-free** (last step): pull, block pulls, chemistry = mean over her 119 charts; charges share-weighted by luck pillar; exact transits / door / Saturn station from her averaged chart; Moon times as earliest–latest | last step | A's pull and chemistry move (10-21: A pull 1.8 → 2.1); her charge moves on 30 days of the 2026-10-20 window (v2 sampling; 33 under your v1 conventions) |

### Reference cut points (old → new)
| cache | A top · 🔥 · ✅ | B top · 🔥 · ✅ | pair_top |
|---|---|---|---|
| v1 `ref_2026-10-20.json` (as shipped) | 3.276371 · 1.861061 · 1.299644 | 3.450551 · 2.265253 · 1.581427 | 3.703836 |
| v3 `ref_2026-10-20.json` (noon A) | 3.333705 · 1.835568 · 1.288482 | 3.457041 · 2.303756 · 1.572269 | 3.703836 |
| v3 `ref_2026-10-20_tf.json` (time-free A, default) | 3.222058 · 1.874358 · 1.292993 | same | 3.695634 |
| v3 `ref_2027-10-20.json` / `_tf` | 4.644118 · 2.205301 · 1.609454 / 4.674484 · 2.236156 · 1.616628 | 3.822733 · 2.623027 · 2.173420 | 4.088542 / 4.116191 |
| v3 `ref_2028-10-19.json` / `_tf` | 3.589453 · 1.817595 · 1.288890 / 3.635873 · 1.790361 · 1.258486 | 4.397910 · 2.626939 · 1.671342 | 3.878901 / 3.938989 |

## Item by item
**P1 — fixes** (all tested in `test_daily.py`)
1. BaZi-day sampling — A's 子 block on 2026-10-21 = 1.1 with `--a-time noon` (the noon chart the audit meant; 1.4 by default); the same mean over the v1 top = 1.08 ✓.
2. Saturn points in A with C — 2027-08-09: A and A-with-C both carry `Saturn station 8` ✓.
3. Chemistry cap — 2026-09-08 with `--a-time noon`: scale 10.0, raw 5.29, `above_window_max` true ✓ (time-free: 10.0, 5.32, true).
4. Local-noon chemistry + `day_max` {raw, scale, local time; null time when the day has no chemistry} over the BaZi day's 24 hourly instants. Golden diffs: 2026-11-01 only (an EST day).
5. DST — 2026-11-01: 150 instants, 144 effective ✓. **2027-03-14: 138 effective, not 144** — skipping the six missing wall times (the rule asked for) leaves 138 on a 23-hour day; the audit's "144 on both days" cannot hold under its own rule. A `sampling` key reports instants / effective / skipped / repeated.
6. Round half up — `bazi_core.round_half_up` (decimal of the printed value) in `rescale` (exact decimal arithmetic), every scale in daily.py, `attraction_core.flags` and `pair_core.timeline`.

**P2 — calibration (new keys)**
7. `charge_pct` + `tier_pct` for A, B and A_with_C (mid-rank among the window's 365 raw S, same options). Saturation on the 2026-10-20 window: v1 code A 49 at 100 / **76** at 5 (the audit said 75 — the untouched v1 code gives 76 with ephem 4.2.1 too, so this is not a v2 change), B 50 / 32 ✓. v2 noon: A 49 / 76, B 50 / 32. v2 default (time-free): A 50 / 72, B 50 / 32. A with C: 70 / 171 (noon), 71 / 166 (time-free).
8. Hours: `points` (= the old hour `charge`, which stays) and `points_pct` (among the window's 365 × 12 blocks).
9. Caches shipped: `ref_2026-10-20`, `ref_2027-10-20`, `ref_2028-10-19` (each noon and `_tf`), and the fixed long-run `ref_longrun_2020-01-01_2040-12-31` (noon and `_tf`; 7,671 days, pull hourly, chemistry at noon) → `pull_pct_longrun` (A, B) and `chem_pct_longrun`. **Flag: the third window starts 2028-10-19, not 10-20** — `window_for` adds 365 days, so after the 2028 leap day the windows drift a day. Not changed (outside the work list); the cache shipped is the one the code reads. One-line fix if you want Oct 20 forever: step `start` by calendar year instead of 365 days.

**P3 — meaning (new keys)**
10. `friction`, `bond`, `attraction_points` on A, B, A_with_C; they sum to S − 35 − Saturn points (tested on every golden day, both modes, and on 400 random synthetic days).
11. `--luck-repeat-weight` (default 1.0). B: 2026-10-21 raw 77 / charge 57 at both 1.0 and 0.5 (no 巳 relation on a 辰 day; only his 寅 申 巳 亥 hours drop: 81 → 67.5, 60 → 47.5, 34 → 31, 50 → 40); 2026-10-22 raw 79 → 76, charge 62 → 55 at 0.5.
12. `STEM_BONUS` table in bazi_core + the rationale in THE_MATH §7. Values unchanged (the old shape test still passes).
13. `love_overlay` 💗 — e.g. 2026-10-22 A: `💗 Venus ☌ Mars 2.71° applying ⚠️` (2.65° with `--a-time noon`; ⚠️ unchanged).

**P4 — robustness** (scripts + reports in `robustness/`)
14. `birth_time_sweep.py` — orb 0.47–1.11° ✓, crossing **19:44:44** (first 10-min step past: 19:50) ✓, family 2 before / 1 after ✓, 28.6 Lib drops after ✓, Venus–Moon 0.00–0.67° ✓, 12 windows + peak 2027-05-13 before the line ✓, the 7:45–11 PM band ✓ (Sep 28–30, 2027 becomes the peak), 癸酉 from 23:00 ✓, 己卯 start Apr 7 – Jul 16, 2027 (5.1 days/hour) ✓, Moon tie 07:40–10:50 ✓. **"At most 0.84" holds only under v1 with both charts on the noon chart's top (0.8356)**; under v2 it is 0.91 (0.99 with each chart on its own top). Also: B→A drops from 1 to 0 after 7:45 PM, so audit item 15's B→A claim also needs "births before 7:45 PM".
15. `null_reports.py` (N = 4,000, seed 20261021, 1960–2000, partners get ASC + MC at Frederick): B→A p 0.127 ✓ · all contacts 17 at the 62nd percentile, p 0.384 ✓ · tight 4 at the 22nd ✓. **A→B: p = 0.021, not 0.050.** The 0.05 only comes back when the partner also carries a DSC key, which makes `attraction_family` count every axis tie twice (☌ ASC and ☍ DSC): p 0.054–0.060 over five seeds (that convention also matches THE_MATH §10's "≈ 5.3%"). B's chart has no DSC key, so the headline uses none. Either way it fails the 4-test Bonferroni line (0.0125). Honest wording: "between about 1-in-17 and 1-in-48, depending on whether an axis tie counts once or twice". Also: the 17 contacts need A's **noon Moon** (A Moon ☍ B Mars 1.71°); without it, 16.
16. A–C null: real 2 ✓, share ≤ 2 = 0.00025 ✓ ("fewer ties than 99.9%" holds), random mean **12.73** (brief 12.6; 12.67–12.76 over five seeds).
17. Goldens: `goldens/golden_<day>.json` (default) and `golden_<day>_noon.json` for 2026-09-08, 10-20, 10-21, 11-01, 2027-03-14 — compared key by key in `test_daily.py`.

**P5 — additions**
18. `strength_core.py` (STD) — A S = 0.7667 strong, B S = 0.25 weak, F exactly as expected.
19. `audit_book.py` — reads the Days tab's Daily log tables from a Markdown export (any column order; six date formats; tiers/flags compared only when written), reruns daily.py per date, prints mismatches; exit 0 / 1 / 2, `--json`. No real export was available, so the format is a guess — send one and I'll pin it. Rows written before v2 differ mostly because A is now time-free: `--a-time noon` reruns them on her noon chart (the v2 fixes can still move a pull by 0.1).
20. `--year-month-terms` (STD) — 流年/流月 at ½ weight in the other set, day and hours; 2026-10-21 adds `辰戌冲 (other, 流月 ×0.5)` 7.5.
21. `--solar-time` (STD) — hour-block edges on true solar time (EoT from ephem, checked against Meeus to 0.1 min). **In daylight time the edges move about an hour** (clock − solar = 54.2 min on 2026-10-21), not "≤ 25 min": the audit's estimate left out daylight saving. Only block edges move (the labels give each block's clock times, DST-safe; an outfit's "seen" follows the solar blocks); the day's pull, flags and charge stay on the clock. The run prints `solar_time` {at, eot_min, mean_time_minus_clock_min, clock_minus_solar_min}, read at local noon.

**§13 outfit color (second job)** — `color_core.py` + `strength_core.py`; `--outfit-A`, `--outfit-B`, `--seen`; the JSON gains `outfit` only when one is passed, and no headline key moves (tested).
- The brief's examples 2–5 reproduce **exactly** on the inputs they were made from (v1 sampling, v1 reference, noon A): 1.919 → 1.982, 辰 2.110 → 2.274; 1.129 → 1.198, 午 0.910 → 1.069; 7.113 → 7.618, 申 7.371 → 8.661; 7.113 → 6.825; every E, W, T, V, charge and role ✓ (`test_daily_color.py`).
- On the shipped v2 defaults the pulls are different numbers (new sampling, new reference, time-free A); the directions are the same (tested).
- Robustness grid (`color_robustness.py`, 27 cells per example): examples 2, 3, 4 robust in every cell; the silver control is down in 18 cells and flat in the 9 ALPHA = 0.5 cells — exactly the brief's table.

**Last step: time-free A** — see THE_MATH §14 and `robustness/time_free_check.md` (your values next to ours, under your v1 conventions and under v2).

## Fixed after the final review (three independent reviewers: code, spec, docs)
- Time-free chemistry summed per-term values that pair_core had already rounded to 3 decimals; it is now the exact mean of the 119 charts' scores. This is what closed the last gap to your check values (pair_top 3.695639 → **3.695634**, yours). Over 2020–2040 the printed raw moved by 0.01 on 10 days (e.g. 2027-02-26: 1.93 → 1.94); none of the five golden days moved. Cache format bumped to **v3** so no older cache is ever reused.
- `--solar-time`: block labels on a DST day are now computed in UTC (they used to overlap or leave a gap by an hour); with an outfit, "seen" follows the solar blocks for the day pull too.
- `--luck-repeat-weight nan` / `inf` now exit 2 like any bad flag.
- `audit_book.py --a-time noon`, so rows written on her noon chart can be checked against it; the family claims in the null report now say "holds for births before 7:45 PM"; several doc lines that quoted noon values as defaults are corrected.

## Noticed, not changed (your call)
- Time-free A's **Saturn station** uses her averaged chart (as THE_MATH §14 says). On A's station days the 119 charts disagree (74 get +8, 45 get +10), so a per-chart mean would print 2 more on 2027-08-07 (5 → 7), 08-08 (9 → 11), 08-09 (55 → 57) and 08-11 (71 → 73). Your "33 charges change" matches the averaged chart (per-chart gives 37), so I kept it.
- The 🔥 +12 bonus goes to every 🔥 day whose pull scale is ≥ 9.5 (the code's rule since v1), not only "the window's top day" as THE_MATH used to say; time-free A gets it on 2027-07-17 and 07-18. THE_MATH now states the code's rule; no number moved.
- `window_for` drift (2028-10-19, above).
- The pull scale is not capped: 2026-09-08 (before the first window) prints A pull 12.4 noon / 13.1 time-free. Only chemistry was asked.
- Moon times and the door still search 24 absolute hours from local midnight, so on DST days the window is an hour off; the item list only covered pull sampling.
- `pair_core.attraction_family` counts an ASC/DSC tie twice when a chart carries both keys (see 15).
- `pair_core.timeline` joins windows by `(t − prev).days == 1`, which a 23-hour spring-forward gap would break for local-noon instants; daily.py never calls it that way, and no window crosses one.
- C: nothing in the book depends on his birth time (THE_MATH §14) — unless he was born 23:00 or later, which would flip his day pillar to 癸卯.

## Changed default numbers on the five golden days
v1 = the pack as received; v2 noon = `--a-time noon` (the P1 fixes only); v2 default = time-free A. New keys are not listed; every old key whose value moved is.

### 2026-09-08

| key | v1 | v2 `--a-time noon` (P1 fixes) | v2 default (time-free A) |
|---|---|---|---|
| chemistry.scale | 14.3 | 10.0 | 10.0 |
| chemistry.raw | 5.29 | 5.29 | 5.32 |
| chemistry.lit_by | [["Venus", 0, "28.6 Lib (B Venus ☌ A Mars)", 0.27], ["Mars", 0, "18.7 Can (A Venus ☍ B Moon, axis)", 0.48], ["Sun", 60, "18.7 Can (A Venus ☍ B Moon, axis)", 2.67]] | [["Venus", 0, "28.6 Lib (B Venus ☌ A Mars)", 0.27], ["Mars", 0, "18.7 Can (A Venus ☍ B Moon, axis)", 0.48], ["Sun", 60, "18.7 Can (A Venus ☍ B Moon, axis)", 2.67]] | [["Venus", 0, "28.6 Lib (B Venus ☌ A Mars)", 0.3], ["Mars", 0, "18.7 Can (A Venus ☍ B Moon, axis)", 0.44], ["Sun", 60, "18.7 Can (A Venus ☍ B Moon, axis)", 2.63]] |
| A.pull | 12.8 | 12.4 | 13.1 |
| A.tone | [{"body": "Uranus", "aspect": "□", "point": "Mercury", "orb": 0.06, "phase": "exact", "weight": 3.565, "tag": "work", "flavor": "⚠️"}, "exact"] | [{"body": "Uranus", "aspect": "□", "point": "Mercury", "orb": 0.06, "phase": "exact", "weight": 3.565, "tag": "work", "flavor": "⚠️"}, "exact"] | [{"body": "Uranus", "aspect": "□", "point": "Mercury", "orb": 0.12, "phase": "exact", "weight": 3.53, "tag": "work", "flavor": "⚠️"}, "exact"] |
| A.exact | ["Uranus □ Mercury 0.06° ⚠️ work", "Mars ☌ Venus 0.57° ⚠️ love", "Venus ☌ Mars 0.13° ⚠️ body", "Mercury ☌ Saturn 0.43° ⚠️ loss"] | ["Uranus □ Mercury 0.06° ⚠️ work", "Mars ☌ Venus 0.57° ⚠️ love", "Venus ☌ Mars 0.13° ⚠️ body", "Mercury ☌ Saturn 0.43° ⚠️ loss"] | ["Uranus □ Mercury 0.12° ⚠️ work", "Mars ☌ Venus 0.48° ⚠️ love", "Venus ☌ Mars 0.07° ⚠️ body", "Mercury ☌ Saturn 0.42° ⚠️ loss"] |
| A.hours[子].pull | 10.8 | 10.5 | 11.4 |
| A.hours[丑].pull | 11.2 | 11.0 | 11.9 |
| A.hours[寅].pull | 11.5 | 11.3 | 12.2 |
| A.hours[卯].pull | 11.9 | 11.7 | 12.6 |
| A.hours[辰].pull | 12.3 | 12.1 | 12.9 |
| A.hours[巳].pull | 12.6 | 12.4 | 13.2 |
| A.hours[午].pull | 13.0 | 12.8 | 13.5 |
| A.hours[未].pull | 13.4 | 13.2 | 13.7 |
| A.hours[申].pull | 13.8 | 13.6 | 13.8 |
| A.hours[酉].pull | 13.9 | 13.6 | 13.9 |
| A.hours[戌].pull | 13.8 | 13.6 | 14.0 |
| A.hours[亥].pull | 13.8 | 13.6 | 14.0 |
| A.moon_times | [["22:23", "△", "Neptune", "✅", "loss"], ["22:25", "⚹", "Pluto", "✅", "loss"]] | [["22:23", "△", "Neptune", "✅", "loss"], ["22:25", "⚹", "Pluto", "✅", "loss"]] | [["22:23", "△", "Neptune", "✅", "loss"], ["22:24-22:26", "⚹", "Pluto", "✅", "loss"]] |
| B.pull | 7.8 | 7.9 | 7.9 |
| B.hours[丑].pull | 8.9 | 8.8 | 8.8 |

Receipt — v1: `Math: 乙酉 · chemistry 14.3 · A charge 100 🔴, pull 12.8🔥 · B charge 84 🟠, pull 7.8🔥` · v2 noon: `Math: 乙酉 · chemistry 10.0 · A charge 100 🔴, pull 12.4🔥 · B charge 84 🟠, pull 7.9🔥` · v2 default: `Math: 乙酉 · chemistry 10.0 · A charge 100 🔴, pull 13.1🔥 · B charge 84 🟠, pull 7.9🔥`

### 2026-10-20

| key | v1 | v2 `--a-time noon` (P1 fixes) | v2 default (time-free A) |
|---|---|---|---|
| chemistry.raw | 0.56 | 0.56 | 0.57 |
| chemistry.lit_by | [["Sun", 0, "28.6 Lib (B Venus ☌ A Mars)", 1.33]] | [["Sun", 0, "28.6 Lib (B Venus ☌ A Mars)", 1.33]] | [["Sun", 0, "28.6 Lib (B Venus ☌ A Mars)", 1.3]] |
| A.pull | 0.9 | 0.9 | 1.1 |
| A.tone | [{"body": "Uranus", "aspect": "□", "point": "Sun", "orb": 0.5, "phase": "exact", "weight": 3.299, "tag": "work", "flavor": "⚠️"}, "exact"] | [{"body": "Uranus", "aspect": "□", "point": "Sun", "orb": 0.5, "phase": "exact", "weight": 3.299, "tag": "work", "flavor": "⚠️"}, "exact"] | [{"body": "Uranus", "aspect": "□", "point": "Mercury", "orb": 0.52, "phase": "exact", "weight": 3.287, "tag": "work", "flavor": "⚠️"}, "exact"] |
| A.exact | ["Uranus □ Sun 0.5° ⚠️ work", "Uranus □ Mercury 0.7° ⚠️ work", "Jupiter □ Uranus 0.96° ⚠️ work"] | ["Uranus □ Sun 0.5° ⚠️ work", "Uranus □ Mercury 0.7° ⚠️ work", "Jupiter □ Uranus 0.96° ⚠️ work"] | ["Uranus □ Mercury 0.52° ⚠️ work", "Uranus □ Sun 0.59° ⚠️ work", "Jupiter □ Uranus 0.96° ⚠️ work"] |
| A.hours[子].pull | 1.0 | 1.1 | 1.3 |
| A.hours[丑].pull | 0.9 | 0.9 | 1.1 |
| A.hours[寅].pull | 0.8 | 0.8 | 1.1 |
| A.hours[卯].pull | 0.8 | 0.8 | 1.0 |
| A.hours[辰].pull | 0.8 | 0.8 | 1.0 |
| A.hours[巳].pull | 0.8 | 0.8 | 1.0 |
| A.hours[午].pull | 0.8 | 0.8 | 1.1 |
| A.hours[未].pull | 0.8 | 0.8 | 1.1 |
| A.hours[申].pull | 0.9 | 0.9 | 1.1 |
| A.hours[酉].pull | 0.9 | 0.9 | 1.1 |
| A.hours[戌].pull | 0.9 | 0.9 | 1.2 |
| A.hours[亥].pull | 0.9 | 0.9 | 1.2 |
| A.moon_times | [["13:06", "⚹", "Neptune", "✅", "loss"], ["13:09", "△", "Pluto", "✅", "loss"], ["16:52", "□", "Uranus", "⚠️", "work"]] | [["13:06", "⚹", "Neptune", "✅", "loss"], ["13:09", "△", "Pluto", "✅", "loss"], ["16:52", "□", "Uranus", "⚠️", "work"]] | [["13:06", "⚹", "Neptune", "✅", "loss"], ["13:07-13:10", "△", "Pluto", "✅", "loss"], ["16:51-16:53", "□", "Uranus", "⚠️", "work"]] |
| B.pull | 1.6 | 1.5 | 1.5 |
| B.hours[子].pull | 0.9 | 0.8 | 0.8 |

Receipt — v1: `Math: 丁卯 · chemistry 1.5 · A charge 90 🔴, pull 0.9 · B charge 55 🟡, pull 1.6` · v2 noon: `Math: 丁卯 · chemistry 1.5 · A charge 90 🔴, pull 0.9 · B charge 55 🟡, pull 1.5` · v2 default: `Math: 丁卯 · chemistry 1.5 · A charge 90 🔴, pull 1.1 · B charge 55 🟡, pull 1.5`

### 2026-10-21

| key | v1 | v2 `--a-time noon` (P1 fixes) | v2 default (time-free A) |
|---|---|---|---|
| chemistry.raw | 0.89 | 0.89 | 0.9 |
| chemistry.lit_by | [["Sun", 0, "28.6 Lib (B Venus ☌ A Mars)", 0.34]] | [["Sun", 0, "28.6 Lib (B Venus ☌ A Mars)", 0.34]] | [["Sun", 0, "28.6 Lib (B Venus ☌ A Mars)", 0.31]] |
| A.pull | 1.9 | 1.8 | 2.1 |
| A.tone | [{"body": "Uranus", "aspect": "□", "point": "Sun", "orb": 0.47, "phase": "exact", "weight": 3.317, "tag": "work", "flavor": "⚠️"}, "exact"] | [{"body": "Uranus", "aspect": "□", "point": "Sun", "orb": 0.47, "phase": "exact", "weight": 3.317, "tag": "work", "flavor": "⚠️"}, "exact"] | [{"body": "Uranus", "aspect": "□", "point": "Mercury", "orb": 0.55, "phase": "exact", "weight": 3.269, "tag": "work", "flavor": "⚠️"}, "exact"] |
| A.exact | ["Uranus □ Sun 0.47° ⚠️ work", "Uranus □ Mercury 0.73° ⚠️ work", "Sun ☌ Mars 0.73° ⚠️ body"] | ["Uranus □ Sun 0.47° ⚠️ work", "Uranus □ Mercury 0.73° ⚠️ work", "Sun ☌ Mars 0.73° ⚠️ body"] | ["Uranus □ Mercury 0.55° ⚠️ work", "Uranus □ Sun 0.56° ⚠️ work", "Sun ☌ Mars 0.67° ⚠️ body"] |
| A.hours[子].pull | 1.0 | 1.1 | 1.4 |
| A.hours[丑].pull | 1.2 | 1.2 | 1.5 |
| A.hours[寅].pull | 1.6 | 1.6 | 1.9 |
| A.hours[卯].pull | 2.1 | 2.0 | 2.3 |
| A.hours[辰].pull | 2.1 | 2.1 | 2.3 |
| A.hours[巳].pull | 1.9 | 1.8 | 2.0 |
| A.hours[午].pull | 1.7 | 1.7 | 1.8 |
| A.hours[未].pull | 1.9 | 1.8 | 2.0 |
| A.hours[申].pull | 2.2 | 2.1 | 2.3 |
| A.hours[酉].pull | 2.3 | 2.3 | 2.4 |
| A.hours[戌].pull | 2.2 | 2.2 | 2.3 |
| A.hours[亥].pull | 2.1 | 2.1 | 2.2 |
| A.moon_times | [["06:41", "△", "Mars", "✅", "body"], ["17:14", "☍", "Sun", "⚠️", "work"], ["19:29", "☍", "Mercury", "⚠️", "work"]] | [["06:41", "△", "Mars", "✅", "body"], ["17:14", "☍", "Sun", "⚠️", "work"], ["19:29", "☍", "Mercury", "⚠️", "work"]] | [["06:03-07:04", "△", "Mars", "✅", "body"], ["16:19-17:48", "☍", "Sun", "⚠️", "work"], ["17:39-20:39", "☍", "Mercury", "⚠️", "work"]] |
| B.pull | 3.4 | 3.3 | 3.3 |
| B.hours[子].pull | 2.5 | 2.4 | 2.4 |
| B.hours[亥].pull | 3.6 | 3.5 | 3.5 |

Receipt — v1: `Math: 戊辰 · chemistry 2.4 · A charge 90 🔴, pull 1.9 · B charge 57 🟡, pull 3.4` · v2 noon: `Math: 戊辰 · chemistry 2.4 · A charge 90 🔴, pull 1.8 · B charge 57 🟡, pull 3.3` · v2 default: `Math: 戊辰 · chemistry 2.4 · A charge 90 🔴, pull 2.1 · B charge 57 🟡, pull 3.3`

### 2026-11-01

| key | v1 | v2 `--a-time noon` (P1 fixes) | v2 default (time-free A) |
|---|---|---|---|
| chemistry.scale | 0.8 | 0.8 | 0.9 |
| chemistry.raw | 0.31 | 0.29 | 0.32 |
| chemistry.lit_by | [["Venus", 0, "28.6 Lib (B Venus ☌ A Mars)", 2.69]] | [["Venus", 0, "28.6 Lib (B Venus ☌ A Mars)", 2.71]] | [["Venus", 0, "28.6 Lib (B Venus ☌ A Mars)", 2.68]] |
| A.tone | [{"body": "Uranus", "aspect": "□", "point": "Sun", "orb": 0.1, "phase": "exact", "weight": 3.543, "tag": "work", "flavor": "⚠️"}, "exact"] | [{"body": "Uranus", "aspect": "□", "point": "Sun", "orb": 0.1, "phase": "exact", "weight": 3.543, "tag": "work", "flavor": "⚠️"}, "exact"] | [{"body": "Uranus", "aspect": "□", "point": "Sun", "orb": 0.18, "phase": "exact", "weight": 3.49, "tag": "work", "flavor": "⚠️"}, "exact"] |
| A.exact | ["Uranus □ Sun 0.1° ⚠️ work", "Mars △ Neptune 0.93° ✅ loss", "Mars ⚹ Pluto 0.95° ✅ loss"] | ["Uranus □ Sun 0.1° ⚠️ work", "Mars △ Neptune 0.93° ✅ loss", "Mars ⚹ Pluto 0.95° ✅ loss"] | ["Uranus □ Sun 0.18° ⚠️ work", "Uranus □ Mercury 0.93° ⚠️ work", "Mars △ Neptune 0.93° ✅ loss", "Mars ⚹ Pluto 0.95° ✅ loss"] |
| A.hours[子].pull | 0.3 | 0.4 | 0.4 |
| B.pull | 0.1 | 0.2 | 0.2 |
| B.hours[子].pull | 0.6 | 0.7 | 0.7 |

Receipt — v1: `Math: 己卯 · chemistry 0.8 · A charge 68 🟠, pull 0.0 · B charge 66 🟠, pull 0.1` · v2 noon: `Math: 己卯 · chemistry 0.8 · A charge 68 🟠, pull 0.0 · B charge 66 🟠, pull 0.2` · v2 default: `Math: 己卯 · chemistry 0.9 · A charge 68 🟠, pull 0.0 · B charge 66 🟠, pull 0.2`

### 2027-03-14

| key | v1 | v2 `--a-time noon` (P1 fixes) | v2 default (time-free A) |
|---|---|---|---|
| A.tone | [{"body": "Uranus", "aspect": "□", "point": "Sun", "orb": 2.36, "phase": "applying", "weight": 1.091, "tag": "work", "flavor": "⚠️"}, "building"] | [{"body": "Uranus", "aspect": "□", "point": "Sun", "orb": 2.36, "phase": "applying", "weight": 1.091, "tag": "work", "flavor": "⚠️"}, "building"] | [{"body": "Uranus", "aspect": "□", "point": "Sun", "orb": 2.28, "phase": "applying", "weight": 1.117, "tag": "work", "flavor": "⚠️"}, "building"] |
| A.hours[卯].pull | 0.1 | 0.1 | 0.0 |
| A.moon_times | [["00:26", "□", "Sun", "⚠️", "work"], ["03:31", "□", "Mercury", "⚠️", "work"], ["23:13", "□", "Jupiter", "⚠️", "money"]] | [["00:26", "□", "Sun", "⚠️", "work"], ["03:31", "□", "Mercury", "⚠️", "work"], ["23:13", "□", "Jupiter", "⚠️", "money"]] | [["00:00-00:58 (84/119)", "□", "Sun", "⚠️", "work"], ["00:50-04:36", "□", "Mercury", "⚠️", "work"], ["23:02-23:20", "□", "Jupiter", "⚠️", "money"]] |
| A.door | ["13:44"] | ["13:44"] | ["13:43"] |
| B.hours[丑].pull | 0.7 | 0.8 | 0.8 |

Receipt — v1: `Math: 壬辰 · chemistry 0.0 · A charge 68 🟠, pull 0.1 · B charge 68 🟠, pull 1.0` · v2 noon: `Math: 壬辰 · chemistry 0.0 · A charge 68 🟠, pull 0.1 · B charge 68 🟠, pull 1.0` · v2 default: `Math: 壬辰 · chemistry 0.0 · A charge 68 🟠, pull 0.1 · B charge 68 🟠, pull 1.0`
