# PLAN — vault_backup.py (MC BUILD 1, court riders Fable 2026-09-01)

Written 2026-09-02, BEFORE any code, per CLAUDE.md Section 5.
Stop-gate already passed: pre-edit hashes reported in-session
(gate_run.py a81ddfce… · CLAUDE.md 33995c8f… · .gitignore 9d423ed9…;
vault_backup.py / test_vault_backup.py / vault_backup.config.example.json
confirmed NEW).

Collision check (Section 7): `grep -lniE "backup|mirror|copytree|shutil.copy" *.py`
→ only vault_repair.py + test files (shutil use inside tests). No existing
backup/mirror tool. Building new is justified.

## Files

| file | action |
|---|---|
| vault_backup.py | NEW — the tool |
| test_vault_backup.py | NEW — T0–T15 + registration/config tests |
| vault_backup.config.example.json | NEW — committed example; real config gitignored |
| gate_run.py | +1 FLEET entry `backup_age` (args `["--check-age"]`) |
| .gitignore | + `vault_backup.config.json` |
| CLAUDE.md | repo map rows for the three new files |

## Design locked

- Config JSON (`--config`, default `vault_backup.config.json`): keys
  `vault_dir` (required), `destination_dir` (required), `excludes`
  (optional, ADDITIVE to defaults), `max_age_days` (optional, default 3
  — the court's own default). Unknown key / missing file / missing
  required key / vault_dir not a dir → exit 2. Fail closed.
- DEFAULT_EXCLUDES: `.obsidian/workspace*`, `*.bak`, `__pycache__`,
  `config/identity.json`, `config`, `config/*` (court rider: ALL of
  config/). Pattern matches relpath, `*/pat`, `pat/*`, `*/pat/*`
  (fnmatch `*` crosses `/`, so `*.bak` already matches at depth).
- Manifest `manifest.json` in destination:
  `{"version":1,"tool":"vault_backup","completed_utc":<iso|null>,
  "files":{<NFC relpath>:{"sha256","size","raw_name"}}}`.
  W1: keys NFC-normalized; ALL file ops use raw OS names; raw kept in
  `raw_name`.
- W0: destination non-empty with no manifest → exit 2 (dry-run AND
  apply — fail closed goes further than the wall, deliberately).
  Empty/missing destination → INITIAL_FULL.
- W2: per file: hash src → copy to `_staging/` tmp → fsync → re-hash
  STAGED bytes (W5; mismatch retry ONCE then UNSTABLE, no manifest
  entry) → `os.replace` into place → manifest entry added and
  manifest REWRITTEN (tmp in _staging + fsync + os.replace) — entries
  last, per file. Interrupted run therefore leaves a valid partial
  manifest with `completed_utc` of the last COMPLETED run (null on
  first) — next run resumes as MIRROR; `--check-age` catches the
  never-completed state.
- W3: manifest unreadable/invalid/wrong tool/version → exit 2, zero
  copies. No empty-dict fallback exists.
- W4: `os.path.islink()` before ANY stat/hash, files and dirs; count
  SKIPPED_SYMLINK; `os.walk(followlinks=False)`, dirnames/filenames
  sorted in place (deterministic).
- W6: `_winpath()` adds `\\?\` on nt only; pre-flight computes every
  planned destination path and warns >240 chars before any copy.
- W7: PermissionError → 3 retries, backoff (0.2, 0.5, 1.0)s
  (`_sleep` injectable) → LOCKED_SKIPPED, run continues. All tmp in
  `_staging/` inside destination. Failed tmps are LEFT in _staging
  (house W6: never delete), counted + reported.
- W8: only writes are inside destination (+ its receipt). Test proves
  by vault snapshot (name+size+sha256+mtime_ns) before/after.
- Deletions: manifest key absent from source → move dest file to
  `_trash/YYYY-MM-DD/<relpath>` (UTC date, collision suffix `.N`),
  drop entry. Never hard-delete.
- Drift classes: COPY_NEW, COPY_CHANGED, RESTORED (dest file missing
  though manifest matches — judgment addition, flagged as deviation),
  RENAMED (same NFC key + hash, raw name changed — no trash churn,
  T1), TRASH, UNSTABLE, LOCKED_SKIPPED. Any of these → exit 1.
- Dry-run (default): zero writes, no receipt; same report dict.
- Receipt: `backup_receipts.jsonl` appended in destination on every
  --apply incl. no-op: mode, scanned/copied/skipped/trashed/unstable/
  locked/symlinks/excluded, bytes_copied, trash_total_bytes,
  duration_s, manifest_sha256, completed_utc.
- `--check-age`: strict manifest load (exit 2 if missing/unreadable);
  `completed_utc` null → finding exit 1; age > max_age_days → finding
  exit 1; manifest-file mtime vs completed_utc apart > 1 day → its own
  finding (sync touches mtime — the disagreement is reportable). Reads
  the JSON field, never mtime, for age.
- `--json` parity from the ONE report dict. Unknown flag → argparse
  exit 2. `--apply` + `--check-age` together → exit 2.
- W9: no network, no credentials; `_ensure_utf8_console` (fleet copy).
- gate_run FLEET += `{"name": "backup_age", "path": "vault_backup.py",
  "args": ["--check-age"], "timeout_s": None, "depends_on": []}` —
  CANT_START on boxes without the tool/config is the designed
  behavior (same as the vault-side fleet files).
- Scheduler (hand-install only, NOT run by me):
  `schtasks /Create /TN "KCT Vault Backup" /TR "\"C:\Path\to\python.exe\" \"C:\Path\to\vault_backup.py\" --apply --config \"C:\Path\to\vault_backup.config.json\"" /SC DAILY /ST 03:30`

## Tests (unittest-style; pytest runs them — pytest NOT installed here,
flagged deviation)

T0–T15 exactly as specced, plus: backup_age registered in
gate_run.FLEET; config fail-closed (missing file, unknown key);
--apply+--check-age refusal. Injection points for tests:
`hash_file`, `stage_copy`, `_open_for_read`, `_sleep` (module-level,
patchable).

## Deviations to flag (D-394)

1. pytest specced, not installed here → unittest-style tests
   (pytest-compatible), run via `python3 -m unittest`.
2. W0 refusal applied to dry-run too, not just --apply (fail closed).
3. RESTORED class added (manifest says current but dest file is gone
   → re-copy): without it a sync-side deletion exits 0 forever.
4. UNSTABLE/failed tmps left in `_staging/` (house W6 no-delete) —
   counted and reported, cleanup is Khai's call.
