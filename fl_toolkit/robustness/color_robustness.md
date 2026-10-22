# §13 outfit color — robustness grid (A-chart mode: tf)

Each cell: (A's day-pull change, B's charge change) when B wears the outfit; charge = the 0–100 S′ (rounded half up), pull = the unrounded 0–10 day pull. 27 cells per example. Robust = the same sign in every cell.

## Summary

| example | day | outfit | A's pull | B's charge | brief expected | robust? |
|---|---|---|---|---|---|---|
| 2 | 2026-10-21 | top green + bottom silver | up | down | up / down | yes |
| 3 | 2026-10-23 | dark brown top + bottom, red peek | up | up | up / up | yes |
| 4 | 2026-10-26 | forest green top + bottom | up | down | up / down | yes |
| 5 | 2026-10-26 | silver top + bottom (control) | mixed: flat in 9, down in 18 | up | down, or flat at ALPHA = 0.5 / up | no |

## Example 2 — 2026-10-21, top green + bottom silver

| ALPHA \ K_VIEW, K_SELF | 0.15, 5 | 0.15, 10 | 0.15, 15 | 0.25, 5 | 0.25, 10 | 0.25, 15 | 0.35, 5 | 0.35, 10 | 0.35, 15 |
|---|---|---|---|---|---|---|---|---|---|
| 0.5 | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ |
| 0.7 | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ |
| 0.9 | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ |

## Example 3 — 2026-10-23, dark brown top + bottom, red peek

| ALPHA \ K_VIEW, K_SELF | 0.15, 5 | 0.15, 10 | 0.15, 15 | 0.25, 5 | 0.25, 10 | 0.25, 15 | 0.35, 5 | 0.35, 10 | 0.35, 15 |
|---|---|---|---|---|---|---|---|---|---|
| 0.5 | ↑ ↑ | ↑ ↑ | ↑ ↑ | ↑ ↑ | ↑ ↑ | ↑ ↑ | ↑ ↑ | ↑ ↑ | ↑ ↑ |
| 0.7 | ↑ ↑ | ↑ ↑ | ↑ ↑ | ↑ ↑ | ↑ ↑ | ↑ ↑ | ↑ ↑ | ↑ ↑ | ↑ ↑ |
| 0.9 | ↑ ↑ | ↑ ↑ | ↑ ↑ | ↑ ↑ | ↑ ↑ | ↑ ↑ | ↑ ↑ | ↑ ↑ | ↑ ↑ |

## Example 4 — 2026-10-26, forest green top + bottom

| ALPHA \ K_VIEW, K_SELF | 0.15, 5 | 0.15, 10 | 0.15, 15 | 0.25, 5 | 0.25, 10 | 0.25, 15 | 0.35, 5 | 0.35, 10 | 0.35, 15 |
|---|---|---|---|---|---|---|---|---|---|
| 0.5 | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ |
| 0.7 | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ |
| 0.9 | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ | ↑ ↓ |

## Example 5 — 2026-10-26, silver top + bottom (control)

| ALPHA \ K_VIEW, K_SELF | 0.15, 5 | 0.15, 10 | 0.15, 15 | 0.25, 5 | 0.25, 10 | 0.25, 15 | 0.35, 5 | 0.35, 10 | 0.35, 15 |
|---|---|---|---|---|---|---|---|---|---|
| 0.5 | = ↑ | = ↑ | = ↑ | = ↑ | = ↑ | = ↑ | = ↑ | = ↑ | = ↑ |
| 0.7 | ↓ ↑ | ↓ ↑ | ↓ ↑ | ↓ ↑ | ↓ ↑ | ↓ ↑ | ↓ ↑ | ↓ ↑ | ↓ ↑ |
| 0.9 | ↓ ↑ | ↓ ↑ | ↓ ↑ | ↓ ↑ | ↓ ↑ | ↓ ↑ | ↓ ↑ | ↓ ↑ | ↓ ↑ |

