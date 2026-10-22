# PLAN — fl_toolkit v2 (Forbidden love math pack: audit P1–P5, then §13 outfit color)

Written 2026-10-22 BEFORE the first edit (Section 5: spans many files).
Source: fl_toolkit.zip sha256 9577a72473c69cce3f51cc2c447f7250f02b73509eef1af2e6b0b990f2310982
(verified on arrival). Briefs: cover_prompt, formula_audit_and_prompt (job 1), color_term_prompt (job 2).

Tier: 2 for this repo (a separate novel-writing pack; no network, no shop, no money).
Lives ONLY in `fl_toolkit/`. No fleet file is touched. CLAUDE.md gets one REPO MAP row.
Dependency: ephem (Khai's own pack rule, named in both briefs). Not a fleet tool.

## Baseline (frozen before any edit)
- 41/41 pack tests green (ephem 4.2.1, Python 3.11).
- Goldens from the ORIGINAL code: scratchpad golden_pre/ for 2026-09-08, 10-20, 10-21, 11-01, 2027-03-14.
- Audit claims re-checked on the original code: A 子 block 10-21 = 1.08 ✓ · A day pull 10-21 = 1.9191 ✓ ·
  chem 09-08 raw 5.29 / top 3.70 ✓ · saturation A 49 at 100 ✓, A at 5 = **76 (audit says 75)** ✗ ·
  B 50 / 32 ✓. A's Saturn-station days: 2027-08-07..11 (+8) — the P1.2 test date.

## Decisions taken (and why) — say each in CHANGES.md
1. DST rule (P1.5): wall-clock grid; nonexistent slots skipped; repeated slots sampled at both instants, ½ each.
   Effective samples = Σ weights → 144 on 2026-11-01 but **138 on 2027-03-14** (a 23-hour day).
   The audit's "144 on both" cannot hold under "skip" — follow the rule, flag the number.
2. Reference caches are rebuilt with the NEW sampling (BaZi day, local-noon chemistry), so a deleted cache
   rebuilds to the same numbers (determinism). Cache gets "v": 2; a v1 cache is treated as stale.
   Old vs new top/fire/ok/pair_top listed in CHANGES.md.
3. Window starts: window_for() adds 365 days, so the 3rd window starts 2028-10-19, not 10-20 (leap day).
   NOT fixed (Section 2: report, don't widen). Ship the cache the code actually reads (ref_2028-10-19.json)
   and flag the drift + one-line fix for Khai.
4. Color acceptance numbers (§5 of the color brief) were computed on the PRE-fix sampling. Tests prove the
   color math on that legacy sampling + the v1 reference (exact spec numbers), and pin the post-fix numbers
   separately. The outfit never changes existing keys; it adds the "outfit" key only.
5. --solar-time: true apparent solar time (ephem hour angle). Moves hour-block edges only (block pulls +
   labels); day pull/flags stay on the clock BaZi day. During EDT the edge shift is ~53–84 min, not "≤25"
   (the audit ignored DST) — flag it.
6. Round-half-up = Decimal(repr(x)) ROUND_HALF_UP, used by rescale and every scale/raw score in daily.py.
7. "reports/" is gitignored repo-wide → reports go to fl_toolkit/robustness/.

## Work list (status)
P1 fixes (daily.py, bazi_core.py, attraction_core.py)
- [ ] 1 BaZi-day sampling 23:00 D−1..22:50 D; 子 block 12 samples; test A 子 10-21 = 1.1 (1.08)
- [ ] 2 Saturn-station points into A_with_C; test 2027-08-09
- [ ] 3 chemistry cap 10.0 + above_window_max; test 09-08 → 10.0 / 5.29 / true
- [ ] 4 chemistry at local noon + day_max (24 hourly, BaZi day) with local time
- [ ] 5 DST fold handling + "sampling" key; tests 11-01 and 2027-03-14
- [ ] 6 round_half_up everywhere a score is rounded
P2 calibrate
- [ ] 7 charge_pct / tier_pct (A, B, A_with_C) from cached per-day primitives; saturation counts in CHANGES
- [ ] 8 hours[].points + points_pct (window's 365×12 blocks per person); keep hours[].charge
- [ ] 9 caches: ref_2026-10-20 (v2), ref_2027-10-20, ref_2028-10-19; long-run 2020-01-01..2040-12-31 hourly
      → pull_pct_longrun (A, B), chem_pct_longrun
P3 meaning
- [ ] 10 friction / bond / attraction_points (sum = S − 35 − Saturn)
- [ ] 11 --luck-repeat-weight (default 1.0); report B 10-21, 10-22 at 1.0 and 0.5
- [ ] 12 STEM_BONUS table + §7 rationale (values unchanged)
- [ ] 13 love_overlay 💗 (Venus–Mars either direction, radar orb)
P4 robustness (robustness/)
- [ ] 14 birth_time_sweep.py + report   - [ ] 15 A–B null   - [ ] 16 A–C null   - [ ] 17 golden tests (5 dates)
P5 additions
- [ ] 18 strength_core.py (STD)  - [ ] 19 audit_book.py  - [ ] 20 --year-month-terms (STD)  - [ ] 21 --solar-time
Job 2 (§13)
- [ ] color_core.py + tests; daily.py --outfit-A/--outfit-B/--seen; THE_MATH §13; robustness grid script
Close
- [ ] THE_MATH.md updates, README, CHANGES.md, deterministic zip + sha256 + sha256 of base64 text
- [ ] adversarial review pass; fleet suite before/after (untouched); commit explicit paths; push to claude/ branch
