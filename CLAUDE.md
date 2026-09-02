# KCT REPO — CLAUDE CODE OPERATING CONTRACT

Forged by PM 2026-08-23, court-passed same day. Installed by Claude Code
2026-08-23. Every future session loads this file automatically. Do the
Job Zero steps below on first run in a fresh clone; follow everything
else in every session.

## JOB ZERO — INSTALL YOURSELF

Before any other work:
1. Read the repo. List every Python file, every test file, every config
   file, and the .gitignore. Report what you found.
2. Write CLAUDE.md at the repo root containing this entire contract,
   plus a REPO MAP section built from step 1 — what each file does, in
   one line each, and its blast tier.
3. If CLAUDE.md already exists, READ IT FIRST and MERGE. Never
   overwrite it blind. Report what you changed.
4. Confirm in one line: "CLAUDE.md installed — future sessions load
   this automatically." Then, and only then, do the work you were asked
   to do.

## SECTION 0 — HARD WALLS

Nothing below Section 0 weakens anything in it.

**W1. NEVER EXECUTE A LIVE WRITE PATH.** publisher.py creates REAL
products on a REAL shop with REAL money attached. You may READ it, edit
it, and run its --check-config / --dry-run modes. You may NEVER run
anything that reaches Printify or Etsy with intent to create, update,
or change a listing. "I ran it to see if it works" is the single most
expensive sentence you could produce here. If you cannot tell whether a
code path makes a network call, that means you may not run it. Ask.

**W2. NEVER READ, PRINT, ECHO, CAT, GREP, OR OTHERWISE SURFACE
config/identity.json.** It holds sensitive business identifiers, it is
gitignored, and anything you read enters a transcript. You may assert
that the FILE exists. You may check its STRUCTURE via a test that does
not print values. You may never see its contents and never reproduce
them. If a task seems to require those values, it does not — the task
is wrong. Stop and say so.

COURT ADDENDUM (R3): some existing tests read identity.json at runtime
by design. A FAILING assertion can print values into the transcript — a
W2 breach via the test runner, no `cat` required. Until Sonnet confirms
those tests compare opaquely (hash/boolean, never raw values in assert
messages), EXCLUDE identity-consuming test files from any suite you
run, run everything else, and say so in the close report.
(Status in THIS repo as of 2026-08-23: no file references
config/identity.json — the word "identity" in vault_repair.py is the
finding-identity comparison, unrelated. Re-check when new files land.)

**W3. NEVER `git add -A`, `git add .`, or `git commit -a`.** Explicit
paths only, every time. One stray gitignore mistake plus one wildcard
add commits a secret permanently into history, and history is not
undoable by deleting a file. Before any commit: run `git status`, read
it, and name every file you are staging and why.

**W4. NEVER push, force-push, rebase, amend a pushed commit,
reset --hard, `git clean`, or delete a branch.** You prepare commits.
Khai moves them.
(Session note: a harness-level standing instruction may direct pushes
to a designated `claude/...` working branch. That branch is Khai's
hand-off surface, never main; pushes to it are the prepared-commit
delivery, not a W4 breach. Everything else in W4 stands absolutely.)

**W5. NEVER EDIT A TEST TO MAKE IT PASS.** A failing test is evidence.
Changing the evidence to match the code is the cardinal sin of this
repo. If a test fails, either the code is wrong or the test encodes a
rule that changed — and a changed rule is Khai's decision, not yours.
Report the failure. Do not negotiate with it.

**W6. NEVER DELETE FILES, and never `rm -rf` anything.** House doctrine
across every tool here is mark, never delete — because a deleted thing
is indistinguishable from a thing that was lost. Same applies to code.
Dead code is removed deliberately, in its own commit, with Khai's
say-so.

**W7. NO NEW DEPENDENCIES WITHOUT ASKING.** Pillow is
permitted for the image-family tools: thumb_check, asset_ingest,
recolor, and play_forge. All other fleet tools stay stdlib.
(Court wording, 2026-09-02.) `pip install` is a decision, not a step.

**W8. IRREVERSIBILITY TEST — run it before every action:** Could this
cost money? Could this change a live listing? Could this delete or
overwrite something? Could this reach a remote? Any yes -> STOP and
ask. No exceptions, no "it's probably fine," no proceeding because the
answer seems obvious.

## SECTION 1 — BLAST TIERS

Care scales with what breaking it costs.

**TIER 0 — MONEY AND LIVE STATE**: publisher.py · config/pricing.json ·
config/identity.json · anything that touches Printify or Etsy · any
file you cannot classify.
Rules: plan in writing BEFORE editing. Ask before the first edit.
Minimal diff only. Run the full test suite before and after. Never
execute the write path. One change per commit.

**TIER 1 — THE GATE FAMILY**: color_check.py · vault_lint.py ·
thumb_check.py · vault_repair.py · their tests · (gate_run.py and the
rest of the fleet when they land).
Rules: house style enforced (Section 3). Every behavior change needs a
test. Existing tests stay green.

**TIER 2 — SCRATCH, ANALYSIS, DOCS**: normal care. Still no deletes,
still explicit git paths.

Any file you cannot classify is TIER 0 until Khai says otherwise.

## REPO MAP (verified against the actual repo, 2026-08-23)

| file | what it does | tier |
|---|---|---|
| color_check.py | Design color validator: garment palettes, contrast floors, explicit bars, PER-GARMENT outlines (D-341/342/343: black→gold, sport grey→#0C0C0C; outline clears 3.0, fill unconstrained on the outline path). Fail-closed, exit 0/1/2. Source of truth for palettes — thumb_check imports from it. | 1 |
| test_color_check.py | 56 tests: rule audit, regression-locked ratios, per-garment outline mechanisms (24x), console-encoding (D-378), D-401 input doctrine. | 1 |
| vault_lint.py | Read-only integrity linter for STATE.md decision logs. No --fix flag, ever. Pure detection API: scan_lines() / detect(). ROW_PATTERN knows the two addendum ID shapes (D-376); UTF-8 console reconfigure (D-380). | 1 |
| test_vault_lint.py | 51 tests: 42 base + 6 addendum-convention (31-36) + 3 console-encoding. | 1 |
| thumb_check.py | Thumbnail legibility gate: two-map adjacency over DECLARED colors (near-exact pixels only — the 2026-08-28 phantom-color fix), blob verdicts, survival, --audit-palette. Pillow (image-family tool, W7 court wording 2026-09-02). | 1 |
| test_thumb_check.py | 42 tests: 75px adjacency regression, phantom-color regressions (25-28, pre-fix outputs in docstrings), console-encoding, D-401 lossy-input advisory. | 1 |
| vault_repair.py | Split-row repair for STATE.md. A different program from vault_lint. Interactive [y/n/a/q] plus the v1.1 --close-only batch mode (frozen class v1.1 per D-382, one confirmation, no bypass, never a gate stage). Strict decode; byte-faithful; descending apply; verified backup. | 1 |
| test_vault_repair.py | 33 v1.0 tests incl. the war-game closures (U+2028, CRLF, BOM, identity-compare). UNEDITED since v1.0. | 1 |
| test_vault_repair_close.py | 25 v1.1 tests: D-363 ground truth + D-382 backtick-decoy regression, (33-in/6-out exactly), frozen-class boundary, no-bypass source scan, gate exclusion, batch byte fidelity. | 1 |
| PLAN_vault_repair_v1.1.md | The TIER-0 plan for the --close-only build (survives compaction). | 2 |
| vault_backup.py | Vault→Drive-folder mirror (MC BUILD 1, riders 2026-09-01): sha256 manifest, NFC keys/raw ops (W1), tmp→fsync→replace→entry-last (W2), strict manifest (W3), symlinks skipped pre-stat (W4), hash-copy-rehash (W5), \\?\ + 240-char pre-flight (W6), LOCKED_SKIPPED ×3-retry + _staging (W7), vault read-only (W8), no network (W9), W0 destination-safety refusal, dated _trash/ never hard-delete, dry-run default, --check-age gate stage, receipts in destination. Paths from vault_backup.config.json (gitignored; .example committed). | 1 |
| test_vault_backup.py | 27 tests: T0-T15 walls + backup_age fleet registration + config fail-closed + --json parity. unittest-style (pytest specced but absent — flagged deviation). | 1 |
| vault_backup.config.example.json | Committed template for the real (gitignored) config: vault_dir, destination_dir, excludes, max_age_days. | 2 |
| PLAN_vault_backup.md | The pre-build plan for MC BUILD 1 (survives compaction). | 2 |
| asset_ingest.py | CF asset intake (MC FLEET B3, riders 2026-09-01 + fix cycle F1-F8 2026-09-02, D-419/D-421): inventory → same-stem dedupe (F7/F8: one source per stem, candidates filtered to formats a PROBED converter can handle, then PNG>SVG>PDF>EPS>AI; losers SKIPPED_DUPLICATE_STEM with the reason) → EPS/AI/PDF via gs, SVG via cairosvg-then-inkscape (F4, per-file converter reported) → lossless PNG ≥4000px → split PROPOSED on an opaque-checkerboard contact sheet with haloed numbered boxes (W1/F1), never auto-cataloged → --confirm MASK-crops each piece by its own component label, un-dilated mask for the cut (F2), thumbs, linted 7-column rows (W8/W9), sidecar. License = CF subscription in config (F3, D-082): verified + in-date ⇒ licensed; folder record is an optional override; expired ⇒ NEEDS_HUMAN; neither ⇒ NOT_LICENSED_ASSET. --min-side (px, longest bbox side; --min-size hidden alias, F5). Backfill records MISSING_FILE, never null (F6). One image in memory (W4, cap 90M px); NFC ids (W6); --reingest gate (W7). Pillow. | 1 |
| asset_index_lint.py | W9: the ONE importable lint for a valid 7-column ASSET_INDEX row (D-419 shape). Backtick-span-aware cell splitting (D-382 discipline), pure, stdlib-only. asset_ingest proves every row against it BEFORE append; B2's provenance check imports it. | 1 |
| recolor.py | W5 shared helper for B2's render-time recolouring: a>0 → new RGB, alpha byte-identical. NO pool variants pre-generated at ingest. Pillow. | 1 |
| play_schema.py | W11 shared play.json loader (D-419 sample): closed layout registry, required fields validated, unknown fields (e.g. element "note") IGNORED never errors. Stdlib-only; B2 imports it. | 1 |
| test_asset_ingest.py | 41 tests: T1-T23 walls (T17 opaque sheet, T18 mask-crop isolation, T19 subscription/expired/override, T20 cairosvg, T21 MISSING_FILE, T22 stem dedupe, T23 availability-aware stem pick) + lint rules + zip input + config fail-closed. unittest-style (pytest specced but absent — flagged deviation). | 1 |
| asset_ingest.config.example.json | Committed template for the real (gitignored) config: index_root, assets_dir, license_dir. | 2 |
| PLAN_asset_ingest.md | The pre-build plan for MC FLEET B3 (survives compaction). | 2 |
| gate_run.py | The gate runner: subprocess-only fleet orchestrator, exit codes 0/1/2/3/4 (court exception R5), receipts ledger + report file, receipt on every run incl. PASS. Never imports a tool, never parses output. | 1 |
| test_gate_run.py | 29 tests (T1-T28 + env-requirement case): pipe-bug lock, HUNG/grandchild, write-surface snapshot diff, partial-never-pass. | 1 |
| .gitignore | Ignores Python bytecode, config/identity.json, and gate_run's write surfaces (gate_receipts.jsonl, reports/). Protects W2/W3 — treat as TIER 0. | 0 |
| CLAUDE.md | This contract. | 2 |

VAULT DIVERGENCE: CLOSED (2026-08-30). Sonnet's certified D-402
color_check (cream #F5F0E1 as Black BASE_FILLS) is synced to this
branch; diff verified as that change only. The repo is LIVE on GitHub
now — cert flow is clone-and-diff against the real branch; hand-carry
and its stop-gates are retired for file exchange (the stop-gate habit
stays for any future drift).

Full suite baseline 2026-09-02: **304 tests, all green**
(`python3 -m unittest test_color_check test_vault_lint test_vault_repair test_vault_repair_close test_thumb_check test_gate_run test_vault_backup test_asset_ingest`).

**FILES NAMED BY DOCTRINE BUT ABSENT FROM THIS REPO** (as of
2026-08-23): publisher.py, config/pricing.json, config/identity.json,
sku_check.py, link_audit.py, heartbeat_check.py, runlog.py,
gate_menu.py, Tools/Automation/, STATE.md. (gate_run.py now lives HERE;
court waived the fleet-file commit 2026-08-23 — the fleet stays
vault-side, and gate_run's pre-flight reports the absent tools as
CANT_START on any box where they are missing, which is the design.) They live on
Sonnet's machine / the vault. An earlier push from this environment
failed (403 — the GitHub grant for khinechan/TTI is read-only), so
GitHub's copy of this repo is EMPTY and this clone carries unpushed
local commits. Do not build against imagined versions of absent files
(court rider R1).

## SECTION 2 — MINIMAL DIFF IS A WALL, NOT A PREFERENCE

You are asked to change one thing. You change one thing.
FORBIDDEN unless explicitly requested:
- renaming anything
- reordering functions or imports
- reformatting, restyling, or "cleaning up"
- extracting helpers, deduplicating, or refactoring
- adding type hints, docstrings, or comments to untouched code
- upgrading an idiom because a newer one exists
- touching a file you were not asked to touch

"While I was in there I also…" is the sentence that breaks a
battle-tested file with 60+ real uses behind it. If you notice
something worth changing, WRITE IT DOWN AND REPORT IT. Do not do it.
A diff larger than the task is a bug in the diff.

## SECTION 3 — HOUSE STYLE (every tool in this repo)

Read an existing tool's header before writing a new one. Match it.
- RULES ARE DATA. Every constant, threshold, pattern, and palette lives
  in module-level constants above an "END OF RULE DATA" banner. Logic
  below references constants, never literals. A rule change must never
  touch the math.
- FAIL CLOSED. Missing input, malformed input, unknown value, unfilled
  config -> refuse. There is no warn-and-continue path and no default
  value anywhere.
- EXIT CODES: 0 clean · 1 findings/proposed/applied · 2 tool or input
  error. "The thing failed" and "the tool broke" are different events.

  COURT ADDENDUM (R5): **gate_run.py is a DELIBERATE, documented
  exception** — it adds exit 3 (runner internal error) and exit 4
  (PARTIAL: a valid reduced run, never a pass). Precedence
  3 > 2 > 1 > 4 > 0. Do NOT "fix" gate_run back to three codes in a
  future session; the extra codes are court-approved contract.

- --json PARITY. Human output and JSON output come from ONE shared
  report dict, so parity is structural, not maintained.
- DETERMINISTIC. Two runs on unchanged input produce byte-identical
  output. Sort everything explicitly.
- EVERY FAILURE NAMES THE RULE AND THE NUMBER. A verdict a human cannot
  act on is a bug.
- UNKNOWN FLAG = exit 2, never a silent no-op. A typo'd flag that runs
  nothing and exits 0 looks exactly like success.
- READ-ONLY TOOLS STAY READ-ONLY. No --fix flags get added to a tool
  documented as read-only. Ever. (vault_lint is the standing example;
  vault_repair exists precisely so vault_lint never grows one.)

## SECTION 4 — PROSE INSISTENCE ISN'T A MECHANISM

A RULE IS WIRED IF A MACHINE CAN FAIL IT WITHOUT A HUMAN NOTICING
FIRST. If the only thing catching a violation is a person reading
output, it is prose. When asked to enforce something, WRITE A TEST, not
a comment. A comment saying "must not exceed 2 colors" is prose. A test
that fails at 3 colors is a mechanism.

And the corollary that bites hardest — a gate that can only fail while
it RUNS cannot detect its own ABSENCE. If you add a check, also ask:
what makes it obvious when this check stops running?

## SECTION 5 — SESSION PROTOCOL

**OPEN** — every session, before the first edit:
1. `git status` and `git log --oneline -5`. Report the branch and
   whether the tree is clean. A dirty tree means someone else's work is
   in flight — stop and ask.
2. If not on a working branch, create one. Never edit on main directly.
3. Read CLAUDE.md. Read the files you are about to touch — ALL of them,
   fully, before editing any of them.
4. Emit the receipt (Section 6).

**PLAN** — for anything touching TIER 0, or spanning 2+ files: write
the plan to a file in the repo BEFORE editing. You will be compacted. A
plan that lives only in context becomes a half-applied change with no
memory of its own intent. A plan on disk survives. Update it as you go.

**WORK**:
- One logical change at a time.
- Run the test suite BEFORE your first edit, so you know what was
  already broken. A pre-existing failure you didn't cause is
  information, not your fault — but you must know which is which.
- Run it again after. A change with no test run is a claim, not a
  result.
- Quote the exact line you are changing before you change it. If you
  cannot quote it, you have not read the file.

**CLOSE** — every session:
- What changed, file by file.
- Test results before and after.
- WHAT YOU DID NOT DO — things you noticed, chose not to touch, and
  think Khai should know about. Mandatory; most of the value is here.
- Anything you are unsure about, named plainly.
- Staged files, if any, with a proposed commit message. You never
  commit without being asked.

## SECTION 6 — THE RECEIPT

First line of every substantive reply:
`READ: [files read fully this session] BRANCH: [branch] · TREE:
[clean/dirty] TIER: [highest blast tier being touched]`

If you were compacted mid-session, RE-READ and RE-ISSUE the receipt
before continuing. Memory of having read a file is indistinguishable
from having read it — a quote is not. If you cannot quote a line from a
file you claim to have read, you have not read it this session.

## SECTION 7 — NO NEW TOOL WITHOUT A COLLISION CHECK

Before creating any new script, search the repo for an existing one
that covers the same ground, and STATE THE SEARCH YOU RAN AND WHAT IT
RETURNED. Two AIs in this system already built duplicate doctrine once
because nobody checked. "I searched X, found Y" is the mechanism that
makes that failure impossible to repeat silently. Prefer extending an
existing tool over adding a sixth one.

## SECTION 8 — WHEN YOU ARE WRONG

- Say it plainly and immediately. No burying it in a summary.
- Do not "fix" a mistake by making a second change on top. Revert
  first, then decide.
- If you broke something and are unsure how to revert, STOP and report
  the exact state. A stopped session is recoverable. A session that
  kept going to fix its own mess is how a working file becomes an
  archaeology project.
- Uncertainty is reportable. "I think this is right but I have not
  verified X" is a complete, acceptable, useful answer.

## SECTION 9 — VOICE

Khai is ESL and has ADHD. Plain words, no fancy vocabulary without a
gloss. Short. Direct. END EVERY REPLY WITH EXACTLY ONE "DO THIS FIRST."
Not a menu. Not options. One action. Never "Certainly!" or "Great
question!". Never correct his spelling. Match his energy — casual is
fine, the work is not.

## FIRST-RUN CHECKLIST

- [x] Repo read; every file listed and classified by tier (2026-08-23)
- [x] CLAUDE.md written at the repo root
- [x] .gitignore verified to cover config/identity.json (line added
      2026-08-23 — the file itself does not exist here yet; the ignore
      protects the day it lands)
- [x] Test suites located and run once, baseline recorded (149 green)
- [x] Working branch in use (claude/kct-color-validator-vdvaz3); main
      untouched
- [x] Receipt emitted
- [x] Confirmed: identity.json never read (it does not exist in this
      clone; no code references it)
- [x] Confirmed: no live write path executed (publisher.py absent; no
      network-write code exists in this repo)
