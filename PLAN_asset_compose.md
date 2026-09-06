# PLAN — MC FLEET B5: asset_compose.py

Spans 5 files -> plan on disk per CLAUDE.md §5. Base: 2d8f7bd, 473
green. Tier 1, new file. Written BEFORE any tool code.

## STEP 0 — DONE, probe exits 0

`tools/probe_imports.py` WANT extended with play_new / asset_ingest /
recolor, plus asset_index_lint constants and
play_forge.measure_stroke_survival. Every surface present, `missing:
[]`, exit 0. Bench facts re-verified here, not taken on trust:

- `play_new.KIND_CLAUSE_DELIMITERS == (' -- ', ',')`
- `infer_kind('composite:subject — cartoon …')` -> `(None, "keywords
  disagree (character<-'cartoon', subject<-'subject')")`
- `infer_kind('subject, composite -- …')` -> `('subject', 'subject')`
- empty `Used in` -> `L4: column 7 is empty`
- `asset_ingest.USED_IN_FMT` at :99, `label_components` at :702,
  `load_sidecar` refuses `tool != "asset_ingest"`,
  `play_forge.measure_stroke_survival` called once at :767
- a `+` joined Asset cell lints CLEAN, `asset_paths()` -> all three
- `grep derived_from` -> nothing

## THE ONE BLOCKING HOLE — W1's allowlist

The spec says the License allowlist starts with two forms: the exact
casefolded `"CF Subscription, verified"` AND "the AI-row basis string
from ASSET_INDEX's header note — quote it from the live file via
Sonnet, do not guess."

That string is NOT in this repo. `grep` finds only the CF literal,
which asset_ingest already owns as `CF_LICENSE_LITERAL` (D-082,
verbatim). So:

- the allowlist is built from `asset_ingest.CF_LICENSE_LITERAL`,
  IMPORTED not retyped;
- the AI-row slot is a NAMED EMPTY in rule data with the comment
  saying what it awaits. Fail-closed consequence, stated out loud:
  **an AI-row source refuses NOT_LICENSED_SOURCE until Sonnet quotes
  the string.** That is the correct behaviour for a wall, and it is
  reported, never guessed.

## WHAT COMPOSE OWNS vs WHAT IT IMPORTS

Imported, never restated: `asset_index_lint.lint_row / asset_path /
asset_paths / COLUMN_COUNT / HEADER_CELLS / ASSET_PATH_JOIN` ·
`play_new.infer_kind` · `play_forge.measure_stroke_survival` ·
`asset_ingest.label_components / load_sidecar / write_sidecar /
append_index_line / SIDECAR_NAME / SIDECAR_VERSION / CF_LICENSE_LITERAL
/ USED_IN_FMT` · `recolor.recolor` is NOT needed (W3 forces RGB to 0
directly; recolor replaces RGB with a colour, which is the render-time
job, not this one) — noted so the omission is deliberate, not a miss.

Config: `index_root` only. Paths in the index are relative to it
(verified against `play_forge.resolve_element`). No second config key
is invented.

## ORDER OF WORK (one logical thing at a time)

1. Recipe loader: duplicate-key hook, closed key sets at every level,
   no defaults. Refusals: RECIPE_UNREADABLE / DUPLICATE_KEY /
   UNKNOWN_KEY / MISSING_KEY / SCHEMA_UNSUPPORTED.
2. Source resolution (W1 + W2): row must exist, be a FILE, carry
   exactly ONE path, License in the allowlist after NFC->strip->
   casefold; read bytes ONCE, hash THOSE bytes, decode from BytesIO.
   Never reopen. Refusals: SOURCE_NOT_INDEXED / SOURCE_IS_FOLDER /
   SOURCE_MULTI_PATH / NOT_LICENSED_SOURCE / PROVENANCE_MISMATCH.
3. Ops (closed registry): ink_layer / mid_layer / solid /
   outline_thicken. Mask to a>0 BEFORE any threshold. ink/mid ranges
   must not overlap unless allow_overlap. outline_thicken before any
   resample.
4. Placement in one pass over frozen geometry; layer N may reference
   only ids < N (FORWARD_REFERENCE).
5. Compose -> alpha sweep (W9) -> measure components (W8), stroke
   (W10), footprint bbox.
6. Row + sidecar + receipt; dry-run default, --apply writes (W12).

## THE asset_ingest CROSS-FILE CHANGE (spec-authorised, kept tiny)

Exactly three things, nothing else: `SIDECAR_VERSION = 2`; entries
written by asset_ingest gain `"tool": "asset_ingest"`; readers accept
version 1 AND 2. `load_sidecar`'s top-level `tool` check stays as it
is — compose writes THROUGH asset_ingest's writer, so the file's
top-level tool stays "asset_ingest" and only the ENTRY says
"asset_compose".

## FLAGGED D-394 IN THE REPORT

- W7 wording: Pillow added to the image-family list in CLAUDE.md.
- kind is written in BOTH the Style cell and the sidecar entry
  (Sonnet's ruling 2 outstanding).
- the composite Style head-clause convention (Sonnet's ruling 1).
- the AI-row basis string hole above.
- REAL-ASSET ACCEPTANCE cannot run here: the live ingested pieces are
  vault-side. Fable/Sonnet run it.
