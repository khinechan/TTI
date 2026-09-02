# PLAN — asset_ingest.py (MC FLEET B3, court riders Fable 2026-09-01)

Written 2026-09-02 BEFORE any code (Section 5). Naming note from the
court: this is FLEET B3 (Sept series); the August "Build 1-4" is a
different topic. B1 = vault_backup (done, certified 62b4339). B3
before B2; two modules built here are B2's imports later.

Stop-gate passed in-session: CLAUDE.md 5bed54c6…, .gitignore
cd3530b7…; asset_ingest.py / asset_index_lint.py / recolor.py /
play_schema.py / test_asset_ingest.py / asset_ingest.config.example.json /
PLAN_asset_ingest.md all confirmed NEW. Collision check (Section 7):
`grep -lniE "asset_index|ingest|recolor|contact.?sheet|play\.json|connected.?component" *.py *.md`
→ no matches. Converter probe on this box: gs absent, inkscape absent.
Baseline: 263 green.

## Files

| file | action |
|---|---|
| asset_ingest.py | NEW — the ingest tool (Pillow) |
| asset_index_lint.py | NEW — W9 importable 7-column row lint, stdlib-only, ROW discipline per vault_lint; ONE source of truth, B2 imports it |
| recolor.py | NEW — W5 alpha-preserving recolor helper (shared with B2); NO variant pre-generation |
| play_schema.py | NEW — W11 play.json loader (shared with B2): unknown fields ignored, required fields validated, closed layout registry |
| test_asset_ingest.py | NEW — T1-T16 + lint/config cases |
| asset_ingest.config.example.json | NEW — committed template; real config gitignored |
| .gitignore | + asset_ingest.config.json, asset_ingest_receipts.jsonl |
| CLAUDE.md | map rows + baseline update |

gate_run.py NOT touched — the spec registers no gate stage for B3.

## Design locked

- Config (fail closed, unknown key = exit 2): index_root (dir that
  "Merch/Design Assets/" means), assets_dir (must live INSIDE
  index_root so Asset cells relativize), license_dir. index file =
  index_root/ASSET_INDEX.md (must exist — this tool never invents the
  human table); sidecar = index_root/ASSET_INDEX.hashes.json (W8).
- Flow (INGEST): NFC folder/zip name (W6) → product id = trailing
  digits → license resolve (W2: input folder license-record.md, else
  license_dir/*<id>*.md; neither → NOT_LICENSED_ASSET, exit 2) →
  duplicate id in sidecar → refuse unless --reingest (W7, exit 2) →
  inventory by extension → convert EPS/AI/PDF via gs-or-inkscape and
  SVG via inkscape to lossless PNG ≥4000px longest side, every
  failure/absence a CANT_CONVERT record (W3) → preview heuristics
  (W2: no alpha / fully-opaque alpha / identical corners on OPAQUE
  images only / JPEG-only folder → NEEDS_HUMAN, held) → connected
  components over alpha>threshold (gap-close = MaxFilter dilation;
  min-size drops crumbs; 2px-erosion probe marks likely_merge) →
  numbered contact sheet + split_proposal.json → exit 1. NOTHING is
  cataloged without --confirm (W1).
- CONFIRM: same input path + --confirm ids/--confirm-file/all; source
  sha verified against proposal; one piece in memory at a time (W4:
  reopen source per piece through _open_image, crop.load(), close,
  save piece + thumbnail, close); row built → asset_index_lint must
  pass BEFORE append (W9, failing row never written) → sidecar entry
  {sha256, product_id, ingested_utc} keyed by the row's path cell
  (W8), atomic tmp+replace.
- BACKFILL (W8): parse existing rows, propose sidecar entries for
  rows missing one (hash file when resolvable under index_root, else
  null + note). Dry-run default; --apply writes; non-destructive
  (only adds keys).
- Row content: Asset backticked relpath; License literal
  "CF Subscription, verified" (D-082); Style/Niche/Colors default
  "pending" (flags --style/--tags/--colors override); Recolor default
  "pending"; Used in = "ingested <date> — not yet used" (index rule
  says row-on-first-use; the court's step list orders a row at
  ingest — the CF Grab-Run "Pending Build" section is the lifecycle
  home; flagged).
- W4: Image.MAX_IMAGE_PIXELS = 90_000_000 (documented cap ≈ 9486² —
  8000×8000 RGBA is 244MB, this bounds the worst case ~343MB and
  turns anything larger into a loud CANT_OPEN, never an OOM).
- Receipts: asset_ingest_receipts.jsonl beside the tool (gate
  pattern), appended on EVERY run including refusals (T15).
- Exit codes: 0 clean/nothing-to-do · 1 proposed/held/cataloged/
  backfill-proposals · 2 error or refusal (NOT_LICENSED_ASSET,
  duplicate id, bad config/flags, unreadable sidecar/proposal).
- recolor.py: recolor(img, hex) → RGBA with solid new-RGB channels +
  original alpha (a>0 shows new hue; zero old-hue pixels anywhere;
  ~30%-blended-edge anti-aliasing preserved byte-for-byte in alpha).
- play_schema.py: LAYOUTS closed registry; required fields from the
  D-419 sample; "note" and any unknown field ignored, never an error.

## Deviations to flag (D-394)

1. Pillow used beyond thumb_check (house text calls Pillow
   thumb_check's single exception) — image ingest is impossible
   stdlib-only; the spec's thumbnails/contact sheets/components
   require it. No NEW dependency installed (W7 house).
2. pytest still not installed → unittest-style tests.
3. SVG added to the convertible set (via Inkscape only) — spec text
   says EPS/AI/PDF but the real CF bundles are SVG and the spec
   probes Inkscape; flagged, not silent.
4. License-record resolution mechanism is my interpretation (folder
   license-record.md, else license_dir/*<id>*.md) — Sonnet should
   confirm the vault-side shape.
5. Taste columns stamped "pending" unless flags given (tool cannot
   know style/niche/colors).
6. Exit-code mapping for refusals (=2) chosen per house 0/1/2; the
   spec named no codes.
