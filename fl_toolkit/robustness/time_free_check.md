# Time-free A — Khai's check values next to ours

Window 2026-10-20 + 365 days. **v1 conventions** = Khai's (calendar-day pull 00:00–23:50, chemistry at 16:00 UTC; his noon run matched the shipped v1 reference). **v2 shipped** = this pack's defaults (BaZi-day pull 23:00–22:50 with the DST rule, chemistry at local noon), read from the shipped `ref_2026-10-20*.json` caches.

| check | Khai | ours, v1 conventions | ours, v2 shipped |
|---|---|---|---|
| time-free ref top | 3.214513 | 3.214513 | 3.222058 |
| time-free ref fire (🔥 cut) | 1.881009 | 1.881009 | 1.874358 |
| time-free ref ok (✅ cut) | 1.284722 | 1.284722 | 1.292993 |
| time-free chemistry pair_top | 3.695634 | 3.695639 | 3.695639 |
| 2026-10-21 A pull, time-free | 2.1 | 2.1 | 2.1 |
| 2026-10-21 A pull, noon | 1.9 | 1.9 | 1.8 |
| 2026-10-21 A charge, time-free | 90 | 90 | 90 |
| 2026-10-21 chemistry, time-free | 2.4 | 2.4 | 2.4 |
| chemistry windows | 12, same as noon | 12 tf vs 12 noon, same dates | 12 tf vs 12 noon, same dates |
| chemistry peak | 2027-05-13 | 2027-05-13 tf · 2027-05-13 noon | 2027-05-13 tf · 2027-05-13 noon |
| chemistry: largest daily move tf vs noon | ≤ 0.2 | 0.2 | 0.3 |
| A pull: largest daily move tf vs noon | ≤ 0.6 | 0.6 | 0.8 |
| A flags that flip | 12 (first 2026-12-01: ✅ → 🔥) | 12 (first 2026-12-01: ✅ → 🔥) | 8 (first 2026-12-10: 🔥 → ✅) |
| A charges that change | 33 (first 2026-12-09: 88 → 99) | 33 (first 2026-12-09: 88 → 99) | 30 (first 2026-12-10: 9 → 5) |
| top pull day | 2027-07-18 (noon) → 2027-07-17 (10.0); 07-18 is 9.8 | 2027-07-18 (noon) → 2027-07-17 (10.0); 07-18 is 9.8 | 2027-07-18 (noon) → 2027-07-18 (10.0); 07-18 is 10.0 |
| 己卯 share starts | 1/119 on 2027-04-07 (0 through 04-06) | 1/119 on 2027-04-07 (0 through 2027-04-06) | same (shares do not depend on sampling) |
| 己卯 share reaches 60 | 60/119 on 2027-05-27 | 60/119 on 2027-05-27 (first day ≥ 60) | same |
| 己卯 share complete | 119/119 from 2027-07-16 | 119/119 from 2027-07-16 | same |
| 2027-05-12 shares; A charge noon → tf | 庚辰 0.647 · 己卯 0.353; charge 79 → 74 | 庚辰 0.647 · 己卯 0.353; 79 → 74 | 庚辰 0.647 · 己卯 0.353; 79 → 74 |

Noon reference under v1 conventions (must equal the shipped v1 cache: top 3.276371, fire 1.861061, ok 1.299644, pair_top 3.703836): {'top': 3.276371, 'fire': 1.861061, 'ok': 1.299644}, pair_top 3.703836.

Method: the time-free pull is the exact mean of §9's moment score over A's 119 charts (00:00–19:40, one every 10 min), computed from sorted point sets (checked against the naive 119-chart mean to 1e-12 in test_daily.py); time-free chemistry is the mean of §10's pair score over the 119 charts' hot spots; charges use the share-weighted mean of the per-luck-pillar S′ (rounded half up) and the Saturn station of the averaged chart.
