# Null reports — audit items 15 and 16

`python3 null_reports.py --n 4000 --seed 20261021` · partners 1960-01-01 to 2000-01-01 UTC · seed sensitivity at 1, 2, 3, 4 · draw check 20000/20000.

## Claims

| | source | claim | measured |
|---|---|---|---|
| ✓ | task | A→B family count = 2 (holds for births before 7:45 PM) | 2 |
| ✓ | task | all A–B contacts = 17 | 17 with A's noon Moon in (16 with it out) |
| ✓ | task | tight A–B contacts (≤ 1°) = 4 | 4 |
| ✓ | task | A–C contacts, bodies only = 2 | 2 |
| ✗ | audit 15 | A→B family: percentile 0.950 | 0.9795 (expected 0.9500; +8.6 SE) |
| ✗ | audit 15 | A→B family: p ≈ 0.050 (births before 7:45 PM) | 0.0207 (expected 0.0500; -8.5 SE) |
| ✓ | audit 15 | B→A family: p ≈ 0.125 (births before 7:45 PM) | 0.1267 (expected 0.1250; +0.3 SE) |
| ✓ | audit 15 | all contacts 17 ≈ 62nd percentile | 0.6163 (expected 0.6200; -0.5 SE) |
| ✓ | audit 15 | all contacts p ≈ 0.38 | 0.3839 (expected 0.3800; +0.5 SE) |
| ✓ | audit 15 | tight contacts 4 ≈ 22nd percentile | 0.2218 (expected 0.2200; +0.3 SE) |
| ✓ | audit 15 | A→B p does not clear the Bonferroni line 0.0125 | p = 0.0207 |
| ✗ | audit 15 | "about a 1-in-20 result" | 1 in 48 (1/p = 48.2) |
| ✓ | audit 15 | the family hits are what is unusual, not the overall contact count | p: family 0.0207 · all 0.3839 · tight 0.7783 |
| ✗ | audit 16 | A–C random-partner mean ≈ 12.6 | 12.727 (sd 3.617; +2.2 SE) |
| ✓ | audit 16 | A–C share of random partners ≤ 2 ≈ 0.0008 | 0.00025 (expected 0.00080; -1.2 SE) |
| ✓ | audit 16 | "fewer ties than 99.9% of random pairs" | share with more ties = 0.99975 |

## Real values under each point-set convention (book: 17 all · 4 tight · 2 A→B · 2 A–C)

| A | B | all A–B | tight A–B | A→B family | B→A family |
|---|---|---|---|---|---|
| Moon out (natA) | bodies + ASC + MC (natB) | 16 | **4 ✓** | **2 ✓** | 1 |
| Moon out (natA) | bodies only | 12 | 3 | **2 ✓** | 1 |
| Moon out (natA) | + DSC + IC | 21 | 5 | **2 ✓** | 1 |
| noon Moon in (pA) | bodies + ASC + MC (natB) | **17 ✓** | **4 ✓** | **2 ✓** | 1 |
| noon Moon in (pA) | bodies only | 13 | 3 | **2 ✓** | 1 |
| noon Moon in (pA) | + DSC + IC | 22 | 5 | **2 ✓** | 1 |

| A | C | A–C contacts |
|---|---|---|
| Moon out (natA) | noon, Moon in (pC) | **2 ✓** |
| Moon out (natA) | noon, Moon out | **2 ✓** |
| noon Moon in (pA) | noon, Moon in (pC) | **2 ✓** |
| noon Moon in (pA) | noon, Moon out | **2 ✓** |

The convention that reproduces 17 / 4 / 2 is A's noon chart **with** its noon Moon for contact counts (B as natB, C as its noon chart; C's Moon in or out gives 2 either way). The family counts do not depend on A's Moon for A→B; B→A is 1 either way. Used below: family on natA (as briefed), contacts on pA.

## A–B null (item 15) — seed 20261021, N = 4000

| test | real | percentile | p | null mean | brief |
|---|---|---|---|---|---|
| A→B family | 2 | 0.9795 | 0.0207 | 0.218 | pct 0.950, p ≈ 0.050 |
| B→A family | 1 | 0.8735 | 0.1267 | 0.131 | p ≈ 0.125 |
| all A–B contacts | 17 | 0.6163 | 0.3839 | 15.333 | ≈ 62nd pct, p ≈ 0.38 |
| tight A–B (≤ 1°) | 4 | 0.2218 | 0.7783 | 5.422 | ≈ 22nd pct |

Holds for births before 7:45 PM: after it A's Mars–B's Venus tie passes the 1° family orb, so A→B drops to 1 and B→A to 0 (robustness/birth_time_sweep.md), and the 17 contacts also need A's noon Moon (A has no birth time). Multiple testing (STD): 4 tests were run on the same pair (A→B, B→A, all, tight), so a Bonferroni line is 0.05/4 = 0.0125; the A→B p = 0.0207 does not clear it (the brief's p ≈ 0.05 does not). Honest wording: "about a 1-in-48 result" under this null (the brief's ≈ 0.05 / 1-in-20 is close to what a partner that also carries a DSC key gives: p = 0.0600 here, 0.0535–0.0600 over the 5 seeds) — and what is unusual is the attraction-family hits, not the overall contact count.

### Point-set checks (diagnostic, same partners)

| test | point set | real | percentile | p | null mean |
|---|---|---|---|---|---|
| A→B family | partner bodies only | 2 | 0.9868 | 0.0135 | 0.172 |
| A→B family | partner + ASC + MC (headline) | 2 | 0.9795 | 0.0207 | 0.218 |
| A→B family | partner + ASC + MC + DSC + IC | 2 | 0.9403 | 0.0600 | 0.265 |
| B→A family | A's noon Moon in | 1 | 0.8363 | 0.1640 | 0.172 |
| all A–B contacts | A's Moon out | 16 | 0.6860 | 0.3142 | 13.747 |
| tight A–B | A's Moon out | 4 | 0.2908 | 0.7093 | 4.864 |

A DSC key on the partner counts every axis contact twice (☌ DSC = ☍ ASC, □ DSC = □ ASC, ☍ DSC = ☌ ASC), which raises the null's share of ≥ 2 hits; B carries no DSC key, so the headline partner carries none either.

## A–C null (item 16) — seed 20261021, N = 4000

| real | null mean | sd | share ≤ real | share > real | percentile | p | p_low (STD) |
|---|---|---|---|---|---|---|---|
| 2 | 12.727 | 3.617 | 0.00025 | 0.99975 | 0.0000 | 1.0000 | 0.00050 |

Method: bodies only (C has no birth time, so no angles on either side of the null); the random partner replaces C; statistic = all synastry contacts with A (3° orbs, ⚹ 2.5°). A small count is the unusual direction here, so the readout is the lower tail (share ≤ real); pair_core's upper-tail p is ≈ 1 by design. With A's Moon out: null mean 11.393, share ≤ 2 = 0.00075.

## Seed sensitivity (headline = seed 20261021)

| seed | A→B pct | A→B p | B→A p | all pct | all p | tight pct | A–C mean | A–C share ≤ 2 | A→B p with DSC |
|---|---|---|---|---|---|---|---|---|---|
| 20261021 | 0.9795 | 0.0207 | 0.1267 | 0.6163 | 0.3839 | 0.2218 | 12.727 | 0.00025 | 0.0600 |
| 1 | 0.9815 | 0.0187 | 0.1330 | 0.6288 | 0.3714 | 0.2165 | 12.726 | 0.00075 | 0.0535 |
| 2 | 0.9810 | 0.0192 | 0.1470 | 0.6345 | 0.3657 | 0.2195 | 12.667 | 0.00050 | 0.0545 |
| 3 | 0.9835 | 0.0167 | 0.1257 | 0.6138 | 0.3864 | 0.2230 | 12.713 | 0.00075 | 0.0550 |
| 4 | 0.9813 | 0.0190 | 0.1327 | 0.6220 | 0.3782 | 0.2120 | 12.762 | 0.00025 | 0.0537 |
| **range** | 0.9795–0.9835 | 0.0167–0.0207 | 0.1257–0.1470 | 0.6138–0.6345 | 0.3657–0.3864 | 0.2120–0.2230 | 12.667–12.762 | 0.00025–0.00075 | 0.0535–0.0600 |

## Method

- Partners: N = 4000 moments uniform in [1960-01-01, 2000-01-01) UTC, t = T0 + u·(T1 − T0), u = random.Random(20261021).random() — pair_core.random_chart's draw; draw check: at every seed (20261021, 1, 2, 3, 4), 20000 of 5 × 4000 partners identical to random_chart's own bodies.
- A–B partner = 10 bodies + ASC + MC at Frederick (39.4143, -77.4105; astro_core.angles), as B has; no DSC key (B has none).
- A–C partner = pair_core.random_chart (10 bodies, no angles: C has no birth time).
- Family uses A = natA (noon bodies, Moon left out: the book's rule); contact counts use A = pA (the noon chart WITH its noon Moon), the point set that reproduces 17/4/2. A has no birth time, so the Moon part is a noon convention: the extra contact it adds is A Moon ☍ B Mars 1.71°.
- percentile = share strictly below (pair_core.null_percentile) · p = (1 + #≥ real)/(N + 1) · STD p_low = (1 + #≤ real)/(N + 1) · ✓ = within 2 Monte-Carlo SE of the brief's number at N.
- Files carry no timestamp and no runtime, so a rerun is byte-identical; the runtime is printed on the console.
