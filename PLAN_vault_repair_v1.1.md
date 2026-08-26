# PLAN — vault_repair.py v1.1 --close-only batch mode

TIER 0 build (writing tool). PM spec forged 2026-08-25 (header's 08-13
is the recurring template quirk); court amendments + V1-V5 answered
2026-08-26. This plan survives compaction; update as work lands.

## Goal
A batch mode for exactly one repair class: rows whose full content
(decision text + status cell + supersedes cell) sits complete on one
line, missing only the single closing pipe. One confirmation for the
whole class. Everything else stays on the v1.0 interactive path.

## The class (V1, verbatim source: "Vault Repair - 33 Rows for Fable
Review.md", 2026-08-20)
"Full content already present ... just missing the single closing |.
Nothing to rejoin, no paragraph to merge, no editorial call."
Predicate is_close_only(candidate) -> (bool, reason), pure, versioned
CLOSE_ONLY_CLASS_VERSION = "1.0". Conditions (constants above the
rule-data banner):
  C1 line matches ROW_PATTERN (ID cell intact)          — else the
     split-row / unclosed-ID class (D-314/315/316/349/350 shape)
  C2 plain numeric ID: no addendum/letter suffix        — the class
     was derived from D-363, all plain IDs (T3 guard)
  C3 rstripped line does not end with "|"               — broken class
  C4 pipes >= dominant - 1                              — every cell
     separator present; excludes D-325 (cells gone) and every
     multi-paragraph first line. >= not == so D-097 (8 pipes, 3 in
     backticks) CLASSIFIES close-only; its pipes-vs-dominant VERIFY
     failure is then W-H's honest skip, exactly per the court note.

## Touched files
- vault_repair.py: two behavior-preserving extractions
  (_closed_dominant, _dry_verify_new_findings) so batch and v1.0 use
  the SAME verify primitives (W-A: identical code path, not a copy);
  new constants; is_close_only(); run_close_only(); --close-only flag;
  gate-marker refusal on --apply; help/explain text. v1.0 flow
  otherwise untouched; 33 tests unedited.
- test_vault_repair_close.py: NEW file, T1-T24.
- .gitignore: vault_repair_receipts.jsonl (apply-mode receipt, the one
  new write surface; dry-run stays zero-write).
- CLAUDE.md: repo map rows.

## Batch flow
classify (predicate) -> validate+dry-verify per candidate (shared
primitives) -> DRY-RUN report is the approval artifact -> --apply asks
EXACTLY ONCE "Apply N close-only fixes?  (class v1.0)  [y/N]" via
read_key, EOF/anything-but-y = abort exit 2 -> W8 re-fingerprint ->
apply_to_lines (descending, shared) -> verified backup -> atomic_write
-> post-detect identity check -> receipt line appended -> staleness
warning whenever candidates remain. collect_approvals() is never
entered (T7 proves by monkeypatch-trap).

## Exit codes (V4, preserved)
0 no close-only candidates · 1 proposed/applied · 2 error/abort/
declined confirmation. Difference documented in --help: interactive
decline stays 1 (v1.0), batch decline is 2 (court rider).

## V2 canary (operational, for Sonnet's first live run)
Live count today = 0. If --close-only matches ANYTHING in today's
STATE.md, the predicate is wider than the class: stop, report, never
apply.

## Status
- [x] vault_lint 51-test sync committed (9179706)
- [x] baseline recorded: 187 green before first edit
- [x] v1.1 code + tests
- [x] full suite green (33 unedited + 24 new + rest)
- [x] CLAUDE.md updated, committed

## D-382 (2026-08-26, court-ordered)
Live canary caught v1.0 of the class counting backticked decoy
pipes (the D-316 shape). Fix: classification counts pipes on a
backtick-stripped copy (BACKTICK_SPAN eats pairs only); verify's
raw comparison unchanged. CLOSE_ONLY_CLASS_VERSION -> 1.1.
T1 still exact 33/6 (D-097 stripped count = 5 = the bar).
