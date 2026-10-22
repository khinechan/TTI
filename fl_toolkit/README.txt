Forbidden love toolkit (Khai's pure_math pack + daily.py), v2. Fiction: characters A, B, C; no real person in the data.
1. python3 -m pip install --break-system-packages ephem
2. cd pure_math/code && python3 -m unittest test_pure_math test_monthly_core test_strength_core test_color_core test_v2_core
   (the 41 original tests + the v2 core tests; none uses a date)
3. cd ../.. && python3 -m unittest test_daily test_daily_color test_audit_book      (date-level tests, a few minutes)
4. python3 daily.py YYYY-MM-DD   (local Frederick date) -> JSON for that day
   Options (all off by default): --a-time noon (A's v1 noon stand-in; default is time-free A) · --luck-repeat-weight W
   · --year-month-terms (STD) · --solar-time (STD) · --outfit-A JSON / --outfit-B JSON / --seen 辰,巳,午,未,申 (§13, STD)
   Example: python3 daily.py 2026-10-21 --outfit-B '[{"slot":"top","color":"green"},{"slot":"bottom","color":"silver"}]'
Reference caches (rebuilt automatically if missing or in the old format; shipped so a day runs in seconds):
   ref_<window start>.json (noon A) and ref_<window start>_tf.json (time-free A) for 2026-10-20, 2027-10-20, 2028-10-19;
   ref_longrun_2020-01-01_2040-12-31[_tf].json (the fixed long-run percentiles).
Reports (robustness/): birth_time_sweep.py, null_reports.py, time_free_check.py, color_robustness.py write them.
Book audit: python3 audit_book.py DAYS_EXPORT.md [--json] [--a-time tf|noon]  (exit 0 clean, 1 mismatches, 2 input error;
   rows written before v2 used A's noon chart: compare them with --a-time noon).
CHANGES.md lists every number v2 moved. pure_math/THE_MATH.md has every formula (§13 outfit color, §14 time-free A).
