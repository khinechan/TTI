# PLAN — play_forge.py (MC FLEET B2, court riders Fable 2026-09-02)

Written 2026-09-02 BEFORE any code (Section 5). Build on 09fda95.

Stop-gate passed in-session. Pre-edit hashes: play_schema.py
2dda5b3d… (WILL be edited: optional family/kind), recolor.py
de8eaca5… (read-only import), asset_index_lint.py 00290eed…
(read-only import), color_check.py 630e7ae3… (read-only data),
thumb_check.py 45f54eae… (read-only, subprocess gate), CLAUDE.md
a28b2411…, .gitignore 288f8b92…. NEW files confirmed absent:
play_forge.py, test_play_forge.py, play_forge.config.example.json,
PLAN_play_forge.md.

Collision check (Section 7): `ls batch_renderer.py spec_renderer.py
render_qc.py` → ALL ABSENT from this repo (vault-side only —
render_qc lives at Merch/Design Assets/renderer-proof/ per brandkit).
`grep -lniE "batch_renderer|spec_renderer|render_qc|play_forge"` →
only prose mentions. So the court's "reuse batch_renderer/
spec_renderer" cannot literally apply HERE (rider R1: never build
against imagined absent files): play_forge carries the renderer
itself — that is not a fork, there is no first copy in this repo.
FLAGGED. render_qc is imported lazily; absent ⇒ the eyes verdict
records EYES_UNAVAILABLE (recorded, never hidden, never faked).

kct-brandkit v5.2 read fresh this session: 4-font roster
(Baseball Athlete Jersey=boast, Vorn=deadpan, Midtown Script=
sentimental/Title-Case-only, Mango Dream=light), 4500×5400 canvas,
150px margin, 2-color law across type+elements (D-053/D-409),
per-garment outline hexes, no-ranking law (MULTI-VARIANT PLAYS #5).

Verified against color_check DATA (W8): fill pool per garment =
PALETTES[GARMENTS[g]["class"]] + BASE_FILLS.get(g). Gold #D9A441 IS
in the dark pool (sample variant 4 is legal fill); #0C0C0C is NOT in
the light pool ⇒ genuinely outline-only on sport grey (T10 case).
Gate CLIs: `color_check.py <garment> <hexes…> [--outline HEX] --json`
and `thumb_check.py <png> <garment> --json`.

## Files

| file | action |
|---|---|
| play_forge.py | NEW — the machine (Pillow; W7-doctrine image-family tool) |
| play_schema.py | EDIT — optional `family` (closed registry straight/arc/badge; C=arc, D=badge per W12) on variants; optional `kind` (character/ornament/subject) on elements. Both validated when present, defaulted when absent; everything else untouched |
| test_play_forge.py | NEW — T1-T17 + schema-extension + config cases |
| play_forge.config.example.json | NEW — placeholders only (W11) |
| .gitignore | + play_forge.config.json, play_forge_receipts.jsonl |
| CLAUDE.md | map rows + baseline |

## Design locked

- Config (fail closed): index_root (ASSET_INDEX.md + sidecar +
  asset files live under it), fonts_dir, out_dir, cluster_distance
  (default 10.0), min_stroke_px (default 5 — PROVISIONAL, Khai's wash
  rule, NO D-number cited, per the court's own wording).
- FONT_ROSTER rule data: name → basename; pre-flight resolves
  <base>.otf then <base>.ttf in fonts_dir; any of the four missing ⇒
  refusal BEFORE variant 1 (W3). No try/except around truetype();
  load_default is never called (T3 proves with a bomb patch).
  Exact vault filenames PROVISIONAL — Sonnet confirms; flagged.
- Structure gates, in order, ALL before any render; any failure ⇒
  spec REJECTED, receipt written (T15), exit 2:
  1. play_schema.load_play (W11).
  2. Per variant: garment known to color_check; flat_pool ⇒
     outline_hex null; outline_path ⇒ garment has an OUTLINES entry
     AND outline_hex equals it (W8); the garment's outline-only hex
     (OUTLINES hex not in its fill pool) used as fill_hex or any
     element recolor ⇒ refuse (T10).
  3. W2: per-variant hexes (fill + outline-if-any + all element
     recolors; garment excluded) clustered by RGB distance ≤
     cluster_distance (union-find); clusters printed in the spec
     sheet; >2 clusters ⇒ spec rejected (T2).
  4. W6: every pair of variants differs on ≥2 of (font_pair,
     color_path, layout); AND no two variants share both the resolved
     element set and the clustered colour set (T6/T7).
  5. W7: each element's asset_id resolves in ASSET_INDEX.hashes.json
     (exact key, else unique prefix — ambiguity refuses), has a
     linted ASSET_INDEX row with that path, file exists under
     index_root, sha256 matches the sidecar. Any miss ⇒ refuse
     (T8/T9). Never crops a bundle itself.
- Render (W5): natively 4500×5400 RGBA; elements loaded one at a
  time, recolored ONLY via recolor.recolor (W1), scaled to
  size_fraction×4500 longest side, composited at POSITION_ANCHORS;
  text after art. Squint = full.resize((220, 264), LANCZOS) — a
  downsample, never a second draw (T5/T12).
- W4: binary-search font size until textlength ≤ layout's
  width-fraction × (4500 − 2×150). Min-stroke measurement: render
  the fitted line's mask, erode by MinFilter sized to min_stroke_px;
  survival < 1% of ink ⇒ variant rejected "W4 MIN_STROKE …" (named,
  per-variant, exit 1 for the run; other variants continue). This is
  a real measurement, not a size floor.
- Families (W12): straight | arc (C) | badge (D), closed registry in
  play_schema. Arc = per-character placement rotated along a circle;
  badge = ring + arc top line + straight hero center. outline_hex
  stroke flows through every family (stroke_width = size/28 min 2).
  LAYOUT_SPECS registry maps the five layouts to concrete
  compositions, each with a one-line hierarchy doc; extending either
  registry = code + test + doc line.
- Gates after render (W9): color_check subprocess (garment + declared
  fill/element hexes, --outline on outline_path), thumb_check
  subprocess (the lossless full PNG), render_qc.check_thumbnail_eyes
  ONLY when an element is kind:"character" (else EYES_N/A; module
  absent ⇒ EYES_UNAVAILABLE). Verdicts attached to spec sheets and
  the receipt; a FAIL variant gets a badge drawn on its contact tile,
  never hidden, never auto-fixed (T11/T16).
- Outputs per variant: variant_NN.png (lossless 4500×5400),
  variant_NN_squint.png (220px), variant_NN_spec.json + .md. Per run:
  contact_fulls.png + contact_squints.png, tiles strictly in number
  order, a rejected variant's tile is a labeled placeholder — number
  order never re-flows (W10/T13). No ranking word anywhere (T13
  greps).
- Receipt (BASE_DIR/play_forge_receipts.jsonl, gitignored): play_id,
  totals, rejected [{id, reason}], gate fails, refusals, duration,
  completed_utc — written on EVERY run including rejections.
- Exit codes: 0 all rendered + all gates green · 1 rendered with
  findings (gate FAIL, variant rejected) · 2 refusal (spec rejected,
  provenance, fonts, config, unknown flag).

## Deviations to flag (D-394)

1. batch_renderer/spec_renderer absent HERE ⇒ renderer written inside
   play_forge (R1; not a fork — no first copy exists in this repo).
2. render_qc absent HERE ⇒ lazy import; EYES_UNAVAILABLE verdict when
   missing (never a fake PASS/FAIL).
3. Roster font FILENAMES are my normalization of the roster names —
   Sonnet must confirm the vault's actual Merch/Fonts filenames.
4. min_stroke measurement is erosion-survival on the rendered mask —
   the honest measurable proxy for "stroke below Npx"; the constant
   stays PROVISIONAL per the court's wording.
5. Family/kind become KNOWN optional play.json fields (closed
   registries) — a deliberate schema extension with tests, per W12;
   unknown OTHER fields stay ignored.
6. pytest still absent ⇒ unittest-style tests.
7. Midtown Script's "Title Case only, never ALL CAPS" register rule
   (brandkit) is NOT enforced by this tool — noticed, reported, not
   wired without a court order.

## FABLE BENCH FIXES (F1-F5, 2026-09-02, applied on 31b1601)

F1 the survival floor is REAL now: min_stroke_survival is rule data
AND a config key beside min_stroke_px (both PROVISIONAL, court
wording kept). Default 0.50 — the bench measured Baseball/Vorn
0.80-0.89, Mango 0.44-0.62, Midtown 0.38-0.58 at a 5px kernel, so
0.50 bites the thin scripts in tight layouts. The old 0.01 could
never fire: prose. Local calibration (Liberation, kernel 5): fitted
486px → 0.886 survival, fitted 75px → 0.365 — the red→green fixture
is built from those measurements and flips on the config knob alone.

F5 OVERLAP WALL (closes F2/F3 structurally): every element, every
text line, and the badge ring renders on its own layer; ANY pixel
intersection between layers rejects the variant with
"OVERLAP: <a> x <b>, N px". F2: the arc family now MEASURES its
rendered extent and places the support below it (ARC_SUPPORT_GAP_PX),
overflow past the margin is its own named rejection. F3: badge text
fits to the ring's inner chord (BADGE_TEXT_CHORD_FRAC), never the
layout's hero_frac; badge element anchors are ring-aware (clear
above/below, inset left/right). Fallout, deliberate and recorded:
frame's hero_frac 0.58→0.46 / support 0.42→0.36 (the old widths ran
under the framing art — unrenderable once the wall went live) and
text_hero support_cy 0.24→0.22; the test laurel fixture became a
thin strip because a fat blob beside frame text overlaps exactly the
way a fat laurel would.

F4 out_dir clobber: a non-empty out_dir/<play_id> now REFUSES
(OUT_DIR_NOT_EMPTY, exit 2, receipted) unless --overwrite; the
receipt records out_dir_mode FRESH|OVERWRITE.

Not fixed on purpose: Midtown uppercase (deviation 7 above — Khai's
one-line order, per the bench's own call list).

F6 (re-bench of 2c9b635): the wall was right, the anchor was wrong —
above_hero was a fixed fraction blind to the element's own height, so
a legal small accent collided with the retuned support line and any
element taller than ~650px could never render at that position. Now
TEXT LAYERS RENDER FIRST and above_hero / below_support / between
anchor off the MEASURED text masks: the element's INK edge sits
ELEMENT_GAP_PX from the nearest text edge; no room within margin /
floor / ceiling ⇒ named rejection "ELEMENT_NO_ROOM: <position>,
needs N px, has M px" — never a bare OVERLAP. left/right keep the
line midgap; badge anchors stay ring-aware (F3). Verified by eye on
the real-shaped case (0.18 accent above_hero on text_hero) and
byte-identical sample output across the compositing reorder
(disjoint layers commute — variant_02 deea44b7… unchanged).
