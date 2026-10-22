Forbidden love toolkit (Khai's pure_math pack + daily.py).
1. python3 -m pip install --break-system-packages ephem
2. cd pure_math/code && python3 -m unittest test_pure_math test_monthly_core   (41 tests must pass)
3. cd ../.. && python3 daily.py YYYY-MM-DD   (local Frederick date) -> JSON for that day
ref_2026-10-20.json caches the reference window; it is rebuilt automatically if missing.
