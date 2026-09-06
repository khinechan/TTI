#!/usr/bin/env python3
"""vault_backup.py — vault -> Drive-folder mirror (MC BUILD 1, court
riders Fable 2026-09-01; built 2026-09-02).

Mirrors vault_dir into destination_dir (Khai's Drive desktop sync
folder — a LOCAL directory; this tool never talks to any API, holds no
credentials, and opens no network connection). Per-file sha256
manifest.json lives in the destination; only changed files are
rewritten; deletions are moved into a dated _trash/YYYY-MM-DD/ inside
the destination, never hard-deleted. File contents are hashed and
copied, never opened for display and never printed.

Dry-run is the default and performs zero filesystem writes of any
kind; --apply writes. --check-age is the gate stage: it reads
completed_utc from INSIDE manifest.json (mtime is touched by sync and
proves nothing) and fails when the last completed backup is older than
max_age_days.

Walls (each has a test behind it):
  W0 --apply into a non-empty destination with no valid manifest is
     refused, exit 2 (mirror mode pointed at the wrong folder would
     _trash/ everything in it). This build refuses in dry-run too —
     fail closed. An empty/missing destination is INITIAL_FULL.
  W1 manifest KEYS are NFC-normalized (unicodedata); every actual
     file operation uses the raw OS name, kept in raw_name.
  W2 copy order fixed: staging tmp -> fsync -> os.replace -> THEN the
     manifest entry; the manifest itself is tmp+fsync+os.replace and
     is rewritten after every completed file, so an interrupted run
     leaves a valid partial manifest (completed_utc stays that of the
     last COMPLETED run; --check-age catches the gap).
  W3 unreadable manifest = exit 2, zero copies. There is no
     empty-dict fallback anywhere in this file.
  W4 os.path.islink() before ANY stat or hash; symlinks recorded
     SKIPPED_SYMLINK, never followed, never copied.
  W5 hash -> copy -> re-hash the staged bytes; mismatch retries once,
     then the file is recorded UNSTABLE and NO manifest entry is
     written for bytes that were not written.
  W6 destination paths get the \\\\?\\ prefix on Windows, and every
     planned destination path is length-checked up front; >240 chars
     is warned before a byte is copied.
  W7 PermissionError (Drive syncing the file) retries x3 with backoff
     then records LOCKED_SKIPPED and CONTINUES. All tmp files live in
     one _staging/ dir inside the destination. Failed tmps are left
     there (house doctrine: mark, never delete) and counted.
  W8 the vault is read-only to this tool: the only writes are inside
     the destination directory (manifest, staging, trash, receipt).
  W9 no credentials, no network; _ensure_utf8_console for Windows.

Exit codes:
    0 = clean (no drift / backup fresh)
    1 = drift found or applied, or a finding (UNSTABLE, LOCKED,
        stale backup)
    2 = tool or input error (bad config, unreadable manifest, W0
        refusal, unknown flag)

Scheduler (Khai installs by hand — this tool never installs itself):
    schtasks /Create /TN "KCT Vault Backup" /TR "\"C:\\Path\\to\\python.exe\" \"C:\\Path\\to\\vault_backup.py\" --apply --config \"C:\\Path\\to\\vault_backup.config.json\"" /SC DAILY /ST 03:30

Standard library only.
"""

import argparse
import fnmatch
import hashlib
import json
import os
import sys
import time
import unicodedata
import uuid
from datetime import datetime, timezone

# ═══════════════════════════════════════════════════════════════════════
# RULE DATA.
# ═══════════════════════════════════════════════════════════════════════

TOOL_NAME = "vault_backup"
MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
RECEIPTS_NAME = "backup_receipts.jsonl"
STAGING_DIRNAME = "_staging"
TRASH_DIRNAME = "_trash"

DEFAULT_CONFIG_NAME = "vault_backup.config.json"
REQUIRED_CONFIG_KEYS = ("vault_dir", "destination_dir")
KNOWN_CONFIG_KEYS = ("vault_dir", "destination_dir", "excludes",
                     "max_age_days")

# Court rider: ALL of config/ stays out of a cloud mirror — a wider
# blast radius for no benefit. config/identity.json is listed on its
# own as well, so the protection survives someone narrowing "config".
# Config-file excludes are ADDITIVE: these defaults always apply.
DEFAULT_EXCLUDES = (
    ".obsidian/workspace*",
    "*.bak",
    "__pycache__",
    "config/identity.json",
    "config",
    "config/*",
)

DEFAULT_MAX_AGE_DAYS = 3        # the court's own default (backup_age)
MTIME_SKEW_ALLOW_S = 86400      # manifest mtime vs completed_utc may
                                # legitimately differ (sync touches
                                # mtime); a full day apart is a finding

LONG_PATH_WARN = 240            # W6: warn on destination paths longer
                                # than this, before any copy
WIN_LONGPATH_PREFIX = "\\\\?\\"

RETRY_BACKOFF_S = (0.2, 0.5, 1.0)   # W7: three retries, then LOCKED
UNSTABLE_RETRIES = 1                # W5: one re-stage, then UNSTABLE

HASH_CHUNK = 1 << 20            # bytes per read while hashing/copying

TRASH_DATE_FMT = "%Y-%m-%d"     # UTC date, deterministic across boxes

EXIT_CLEAN = 0
EXIT_DRIFT = 1
EXIT_ERROR = 2

# ═══════════════════════════════════════════════════════════════════════
# END OF RULE DATA.
# ═══════════════════════════════════════════════════════════════════════


_sleep = time.sleep     # injectable for tests (W7 backoff)


def _ensure_utf8_console():
    """Reconfigure stdout/stderr for UTF-8 display, substituting any
    character the console codepage can't render instead of crashing
    (fleet copy — STATE.md D-378/D-380). Display only; bytes written
    to the manifest/receipt stay real UTF-8 regardless. No-op when the
    stream has no .reconfigure (test harness StringIO).
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _winpath(path):
    """W6: absolute path with the \\\\?\\ long-path prefix on Windows.
    On POSIX, returns the path unchanged. Every open/stat/replace on a
    DESTINATION path goes through this."""
    if os.name != "nt":
        return path
    abspath = os.path.abspath(path)
    if abspath.startswith(WIN_LONGPATH_PREFIX):
        return abspath
    return WIN_LONGPATH_PREFIX + abspath


class ToolError(Exception):
    """Config/manifest/invocation problem. Exit 2. Fail closed."""


def _open_for_read(path):
    """Single choke point for reading source bytes — injectable so a
    test can raise PermissionError (T14) without touching the OS."""
    return open(path, "rb")


def hash_file(path):
    """sha256 of a file's bytes. Never decodes, never prints content."""
    digest = hashlib.sha256()
    with _open_for_read(path) as handle:
        while True:
            chunk = handle.read(HASH_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _with_retries(operation, what, findings):
    """W7: run operation(); on PermissionError retry len(RETRY_BACKOFF_S)
    times with backoff. Returns (ok, result). On final failure appends
    a LOCKED finding and returns (False, None) — the run continues."""
    delays = (0,) + RETRY_BACKOFF_S
    last_error = None
    for attempt, delay in enumerate(delays):
        if delay:
            _sleep(delay)
        try:
            return True, operation()
        except PermissionError as err:
            last_error = err
    findings.append("LOCKED_SKIPPED: %s (PermissionError after %d "
                    "retries: %s)" % (what, len(RETRY_BACKOFF_S),
                                      last_error))
    return False, None


# ── config ─────────────────────────────────────────────────────────────

def load_config(path):
    """Strict config load. Missing file, bad JSON, unknown key, missing
    required key, non-directory vault_dir: all exit 2. No defaults for
    the paths; max_age_days defaults to the court's 3."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        raise ToolError("config not found: %s (paths come from config, "
                        "never hardcoded — copy "
                        "vault_backup.config.example.json)" % path)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as err:
        raise ToolError("config unreadable: %s (%s)" % (path, err))
    if not isinstance(raw, dict):
        raise ToolError("config must be a JSON object: %s" % path)
    for key in sorted(raw):
        if key not in KNOWN_CONFIG_KEYS:
            raise ToolError("unknown config key %r (known: %s) — "
                            "refusing, fail closed"
                            % (key, ", ".join(KNOWN_CONFIG_KEYS)))
    for key in REQUIRED_CONFIG_KEYS:
        if key not in raw or not isinstance(raw[key], str) or not raw[key]:
            raise ToolError("config key %r missing or not a non-empty "
                            "string" % key)
    excludes = raw.get("excludes", [])
    if (not isinstance(excludes, list)
            or any(not isinstance(p, str) or not p for p in excludes)):
        raise ToolError("config key 'excludes' must be a list of "
                        "non-empty strings")
    max_age = raw.get("max_age_days", DEFAULT_MAX_AGE_DAYS)
    if not isinstance(max_age, int) or isinstance(max_age, bool) \
            or max_age < 1:
        raise ToolError("config key 'max_age_days' must be a positive "
                        "integer")
    vault_dir = os.path.abspath(raw["vault_dir"])
    if not os.path.isdir(vault_dir):
        raise ToolError("vault_dir is not a directory: %s" % vault_dir)
    return {
        "vault_dir": vault_dir,
        "destination_dir": os.path.abspath(raw["destination_dir"]),
        "excludes": list(DEFAULT_EXCLUDES) + sorted(excludes),
        "max_age_days": max_age,
    }


# ── exclusion ──────────────────────────────────────────────────────────

def is_excluded(rel_posix, patterns):
    """True when the NFC relative posix path matches any pattern, as
    itself, at any depth, or as anything under a matched directory."""
    for pattern in patterns:
        for shape in (pattern, "*/" + pattern, pattern + "/*",
                      "*/" + pattern + "/*"):
            if fnmatch.fnmatch(rel_posix, shape):
                return True
    return False


# ── scan (W1/W4: NFC keys, raw ops, islink first) ─────────────────────

def scan_vault(vault_dir, patterns, counts):
    """Walk the vault deterministically. Returns a dict
    {nfc_key: {"raw_rel", "abs_path"}}. Symlinks (file OR dir) are
    counted and skipped BEFORE any stat; excluded entries are counted
    and pruned. Never opens a file."""
    inventory = {}
    for dirpath, dirnames, filenames in os.walk(vault_dir,
                                                followlinks=False):
        dirnames.sort()
        filenames.sort()
        kept = []
        for name in dirnames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full):                      # W4 first
                counts["symlinks"] += 1
                continue
            rel = os.path.relpath(full, vault_dir).replace(os.sep, "/")
            if is_excluded(unicodedata.normalize("NFC", rel), patterns):
                counts["excluded"] += 1
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full):                      # W4 first
                counts["symlinks"] += 1
                continue
            rel = os.path.relpath(full, vault_dir).replace(os.sep, "/")
            nfc = unicodedata.normalize("NFC", rel)
            if is_excluded(nfc, patterns):
                counts["excluded"] += 1
                continue
            counts["scanned"] += 1
            inventory[nfc] = {"raw_rel": rel, "abs_path": full}
    return inventory


# ── manifest (W1/W2/W3) ────────────────────────────────────────────────

def load_manifest(destination_dir):
    """Strict manifest load. Returns (manifest_dict_or_None, mode).
    mode is INITIAL_FULL when the destination is empty or absent.
    A non-empty destination without a manifest, or an unreadable /
    wrong-shape manifest, raises ToolError (W0/W3) — there is no
    empty-dict fallback."""
    manifest_path = os.path.join(destination_dir, MANIFEST_NAME)
    if not os.path.isdir(_winpath(destination_dir)):
        return None, "INITIAL_FULL"
    entries = sorted(os.listdir(_winpath(destination_dir)))
    if not os.path.exists(_winpath(manifest_path)):
        if not entries:
            return None, "INITIAL_FULL"
        raise ToolError(
            "W0 REFUSAL: destination %s is non-empty (%d entries) and "
            "has no %s written by this tool. Mirroring into the wrong "
            "folder would _trash/ everything in it. Point at an empty "
            "folder or the existing backup." %
            (destination_dir, len(entries), MANIFEST_NAME))
    try:
        with open(_winpath(manifest_path), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as err:
        raise ToolError("W3: manifest unreadable (%s) — exit 2, zero "
                        "files copied. No empty-dict fallback exists. "
                        "Path: %s" % (err, manifest_path))
    if (not isinstance(data, dict)
            or data.get("tool") != TOOL_NAME
            or data.get("version") != MANIFEST_VERSION
            or not isinstance(data.get("files"), dict)):
        raise ToolError("W3: manifest at %s was not written by %s v%d "
                        "— refusing." % (manifest_path, TOOL_NAME,
                                         MANIFEST_VERSION))
    return data, "MIRROR"


def write_manifest(destination_dir, staging_dir, manifest):
    """W2: tmp in _staging -> fsync -> os.replace over manifest.json."""
    tmp = os.path.join(staging_dir, "manifest.%s.tmp" % uuid.uuid4().hex)
    payload = json.dumps(manifest, sort_keys=True, ensure_ascii=False,
                         indent=1)
    with open(_winpath(tmp), "w", encoding="utf-8") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(_winpath(tmp),
               _winpath(os.path.join(destination_dir, MANIFEST_NAME)))


# ── staging copy (W2/W5/W7) ────────────────────────────────────────────

def stage_copy(src_abs, staging_dir):
    """Copy source bytes into a fresh tmp inside _staging, fsync it,
    return the tmp path. Raw byte copy — never decoded, never shown."""
    tmp = os.path.join(staging_dir, "file.%s.tmp" % uuid.uuid4().hex)
    with _open_for_read(src_abs) as src, \
            open(_winpath(tmp), "wb") as out:
        while True:
            chunk = src.read(HASH_CHUNK)
            if not chunk:
                break
            out.write(chunk)
        out.flush()
        os.fsync(out.fileno())
    return tmp


# ── planning ───────────────────────────────────────────────────────────

def build_plan(inventory, manifest_files, destination_dir, counts,
               findings):
    """Compare source inventory to manifest. Pure decision — no writes.
    Returns an ordered list of action dicts. Hashing of source files
    happens here (drift detection needs it); W7 wraps each hash so a
    locked source file cannot end the run."""
    plan = []
    for key in sorted(inventory):
        rec = inventory[key]
        ok, src_hash = _with_retries(
            lambda p=rec["abs_path"]: hash_file(p),
            "hash source %s" % rec["raw_rel"], findings)
        if not ok:
            counts["locked"] += 1
            continue
        rec["sha256"] = src_hash
        try:
            rec["size"] = os.path.getsize(rec["abs_path"])
        except OSError:
            rec["size"] = None
        entry = manifest_files.get(key)
        if entry is None:
            plan.append({"action": "COPY_NEW", "key": key, "rec": rec})
        elif entry.get("sha256") != src_hash:
            plan.append({"action": "COPY_CHANGED", "key": key,
                         "rec": rec})
        else:
            dest_file = os.path.join(
                destination_dir, *entry["raw_name"].split("/"))
            if not os.path.exists(_winpath(dest_file)) \
                    and not os.path.islink(dest_file):
                # Manifest says current but the destination copy is
                # gone (sync-side deletion). Without this, the loss is
                # invisible forever. Flagged as a build deviation.
                plan.append({"action": "RESTORED", "key": key,
                             "rec": rec})
            elif entry.get("raw_name") != rec["raw_rel"]:
                plan.append({"action": "RENAMED", "key": key,
                             "rec": rec,
                             "old_raw": entry["raw_name"]})
            else:
                counts["skipped"] += 1
    for key in sorted(manifest_files):
        if key not in inventory:
            plan.append({"action": "TRASH", "key": key,
                         "entry": manifest_files[key]})
    return plan


def preflight_long_paths(plan, destination_dir, warnings):
    """W6: length-check every planned destination path BEFORE any copy."""
    for item in plan:
        if item["action"] in ("COPY_NEW", "COPY_CHANGED", "RESTORED",
                              "RENAMED"):
            raw = item["rec"]["raw_rel"]
        else:
            raw = item["entry"]["raw_name"]
        dest = os.path.abspath(
            os.path.join(destination_dir, *raw.split("/")))
        if len(dest) > LONG_PATH_WARN:
            warnings.append("W6 LONG PATH (%d > %d chars): %s"
                            % (len(dest), LONG_PATH_WARN, dest))


# ── apply ──────────────────────────────────────────────────────────────

def _copy_one(item, destination_dir, staging_dir, counts, findings):
    """W2/W5/W7 copy of one file. Returns the manifest entry dict on
    success, None on UNSTABLE/LOCKED (in which case NO entry may be
    recorded — never a hash for bytes not written)."""
    rec = item["rec"]
    src_abs = rec["abs_path"]
    expected = rec["sha256"]
    staged = None
    for attempt in range(1 + UNSTABLE_RETRIES):
        if attempt:
            ok, expected = _with_retries(
                lambda: hash_file(src_abs),
                "re-hash source %s" % rec["raw_rel"], findings)
            if not ok:
                counts["locked"] += 1
                return None
        ok, staged = _with_retries(
            lambda: stage_copy(src_abs, staging_dir),
            "stage %s" % rec["raw_rel"], findings)
        if not ok:
            counts["locked"] += 1
            return None
        staged_hash = hash_file(staged)      # our own bytes: no retry
        if staged_hash == expected:
            break
        staged = None
    if staged is None:
        counts["unstable"] += 1
        findings.append("UNSTABLE: %s changed between hash and copy "
                        "twice — no manifest entry written (W5)"
                        % rec["raw_rel"])
        return None
    dest_file = os.path.join(destination_dir,
                             *rec["raw_rel"].split("/"))
    os.makedirs(_winpath(os.path.dirname(dest_file)), exist_ok=True)
    ok, _ = _with_retries(
        lambda: os.replace(_winpath(staged), _winpath(dest_file)),
        "replace %s" % rec["raw_rel"], findings)
    if not ok:
        counts["locked"] += 1
        return None
    counts["copied"] += 1
    counts["bytes_copied"] += rec["size"] or 0
    return {"sha256": expected, "size": rec["size"],
            "raw_name": rec["raw_rel"]}


def _trash_one(item, destination_dir, trash_day_dir, counts, findings):
    """Move the destination copy into _trash/YYYY-MM-DD/, keeping its
    relative path; numeric suffix on collision. Never hard-deletes."""
    raw = item["entry"]["raw_name"]
    dest_file = os.path.join(destination_dir, *raw.split("/"))
    if not os.path.exists(_winpath(dest_file)) \
            and not os.path.islink(dest_file):
        findings.append("TRASH_MISSING: %s was already gone from the "
                        "destination — manifest entry dropped, nothing "
                        "to move" % raw)
        return True
    target = os.path.join(trash_day_dir, *raw.split("/"))
    suffix = 0
    while os.path.exists(_winpath(target)):
        suffix += 1
        target = os.path.join(trash_day_dir,
                              *("%s.%d" % (raw, suffix)).split("/"))
    os.makedirs(_winpath(os.path.dirname(target)), exist_ok=True)
    ok, _ = _with_retries(
        lambda: os.replace(_winpath(dest_file), _winpath(target)),
        "trash %s" % raw, findings)
    if not ok:
        counts["locked"] += 1
        return False
    counts["trashed"] += 1
    return True


def _rename_one(item, destination_dir, counts, findings):
    """Same NFC key, same hash, raw spelling changed (W1: NFD->NFC
    round-trip). Rename in place — no trash churn, one manifest entry."""
    old = os.path.join(destination_dir, *item["old_raw"].split("/"))
    new = os.path.join(destination_dir,
                       *item["rec"]["raw_rel"].split("/"))
    os.makedirs(_winpath(os.path.dirname(new)), exist_ok=True)
    if os.path.exists(_winpath(old)) or os.path.islink(old):
        ok, _ = _with_retries(
            lambda: os.replace(_winpath(old), _winpath(new)),
            "rename %s" % item["old_raw"], findings)
        if not ok:
            counts["locked"] += 1
            return None
    counts["renamed"] += 1
    rec = item["rec"]
    return {"sha256": rec["sha256"], "size": rec["size"],
            "raw_name": rec["raw_rel"]}


def apply_plan(plan, destination_dir, manifest, counts, findings):
    """Execute the plan. Manifest is rewritten after EVERY completed
    file (W2: entries last, per file) and stamped completed_utc only
    at the very end."""
    staging_dir = os.path.join(destination_dir, STAGING_DIRNAME)
    os.makedirs(_winpath(staging_dir), exist_ok=True)
    trash_day_dir = os.path.join(
        destination_dir, TRASH_DIRNAME,
        datetime.now(timezone.utc).strftime(TRASH_DATE_FMT))
    files = manifest["files"]
    for item in plan:
        action = item["action"]
        if action in ("COPY_NEW", "COPY_CHANGED", "RESTORED"):
            entry = _copy_one(item, destination_dir, staging_dir,
                              counts, findings)
            if entry is None:
                continue
            files[item["key"]] = entry
        elif action == "RENAMED":
            entry = _rename_one(item, destination_dir, counts, findings)
            if entry is None:
                continue
            files[item["key"]] = entry
        elif action == "TRASH":
            if not _trash_one(item, destination_dir, trash_day_dir,
                              counts, findings):
                continue
            del files[item["key"]]
        write_manifest(destination_dir, staging_dir, manifest)
    manifest["completed_utc"] = datetime.now(
        timezone.utc).isoformat(timespec="seconds")
    write_manifest(destination_dir, staging_dir, manifest)


def _tree_bytes(root):
    """Total size of regular files under root (receipt: _trash size).
    Symlink-safe: lstat only."""
    total = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        filenames.sort()
        for name in filenames:
            full = os.path.join(dirpath, name)
            if not os.path.islink(full):
                try:
                    total += os.lstat(full).st_size
                except OSError:
                    pass
    return total


def append_receipt(destination_dir, receipt):
    path = os.path.join(destination_dir, RECEIPTS_NAME)
    with open(_winpath(path), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(receipt, sort_keys=True,
                            ensure_ascii=False) + "\n")


# ── check-age (gate stage) ─────────────────────────────────────────────

def check_age(config, now=None):
    """backup_age gate stage. Reads completed_utc from INSIDE the
    manifest, never mtime. Returns the shared report dict; exit code
    is in report["exit_code"]. Missing/unreadable manifest = exit 2
    (a gate that can't find its backup must not look green)."""
    now = now or datetime.now(timezone.utc)
    destination_dir = config["destination_dir"]
    manifest_path = os.path.join(destination_dir, MANIFEST_NAME)
    manifest, mode = load_manifest(destination_dir)
    if manifest is None:
        raise ToolError("backup_age: no %s in %s — no backup has ever "
                        "completed here" % (MANIFEST_NAME,
                                            destination_dir))
    findings = []
    completed = manifest.get("completed_utc")
    age_days = None
    if completed is None:
        findings.append("backup_age: manifest exists but no run has "
                        "ever COMPLETED (completed_utc is null) — an "
                        "interrupted first run, not a backup")
    else:
        try:
            done = datetime.fromisoformat(completed)
        except (TypeError, ValueError):
            raise ToolError("backup_age: completed_utc %r is not a "
                            "parseable timestamp" % completed)
        age_days = (now - done).total_seconds() / 86400.0
        if age_days > config["max_age_days"]:
            findings.append(
                "backup_age FAIL: last completed backup is %.1f days "
                "old, limit is %d days (max_age_days)"
                % (age_days, config["max_age_days"]))
        mtime = datetime.fromtimestamp(
            os.lstat(_winpath(manifest_path)).st_mtime, timezone.utc)
        skew = abs((mtime - done).total_seconds())
        if skew > MTIME_SKEW_ALLOW_S:
            findings.append(
                "backup_age NOTE: manifest mtime and completed_utc "
                "disagree by %.1f days — something other than this "
                "tool touched the manifest (sync?), reported as its "
                "own finding" % (skew / 86400.0))
    return {
        "tool": TOOL_NAME,
        "mode": "CHECK_AGE",
        "destination_dir": destination_dir,
        "completed_utc": completed,
        "age_days": None if age_days is None else round(age_days, 2),
        "max_age_days": config["max_age_days"],
        "findings": findings,
        "exit_code": EXIT_DRIFT if findings else EXIT_CLEAN,
    }


# ── mirror run ─────────────────────────────────────────────────────────

def run_backup(config, apply=False):
    """Dry-run (default, zero writes) or --apply mirror. Returns the
    shared report dict."""
    started = time.monotonic()
    counts = {"scanned": 0, "copied": 0, "skipped": 0, "trashed": 0,
              "renamed": 0, "unstable": 0, "locked": 0, "symlinks": 0,
              "excluded": 0, "bytes_copied": 0}
    findings = []
    warnings = []
    destination_dir = config["destination_dir"]
    manifest, mode = load_manifest(destination_dir)     # W0/W3 gate
    manifest_files = {} if manifest is None else manifest["files"]
    inventory = scan_vault(config["vault_dir"], config["excludes"],
                           counts)
    plan = build_plan(inventory, manifest_files, destination_dir,
                      counts, findings)
    preflight_long_paths(plan, destination_dir, warnings)   # W6 first
    if apply:
        if manifest is None:
            manifest = {"version": MANIFEST_VERSION, "tool": TOOL_NAME,
                        "completed_utc": None, "files": {}}
            os.makedirs(_winpath(destination_dir), exist_ok=True)
        apply_plan(plan, destination_dir, manifest, counts, findings)
    drift = [{"action": p["action"],
              "file": (p["rec"]["raw_rel"] if "rec" in p
                       else p["entry"]["raw_name"])} for p in plan]
    exit_code = EXIT_DRIFT if (drift or counts["unstable"]
                               or counts["locked"]) else EXIT_CLEAN
    report = {
        "tool": TOOL_NAME,
        "mode": mode,
        "apply": apply,
        "vault_dir": config["vault_dir"],
        "destination_dir": destination_dir,
        "counts": counts,
        "drift": drift,
        "warnings": warnings,
        "findings": findings,
        "duration_s": round(time.monotonic() - started, 3),
        "exit_code": exit_code,
    }
    if apply:
        manifest_path = os.path.join(destination_dir, MANIFEST_NAME)
        trash_dir = os.path.join(destination_dir, TRASH_DIRNAME)
        receipt = {
            "tool": TOOL_NAME,
            "mode": mode,
            "scanned": counts["scanned"],
            "copied": counts["copied"],
            "skipped": counts["skipped"],
            "trashed": counts["trashed"],
            "renamed": counts["renamed"],
            "unstable": counts["unstable"],
            "locked": counts["locked"],
            "symlinks": counts["symlinks"],
            "excluded": counts["excluded"],
            "bytes_copied": counts["bytes_copied"],
            "trash_total_bytes": (_tree_bytes(trash_dir)
                                  if os.path.isdir(trash_dir) else 0),
            "duration_s": report["duration_s"],
            "manifest_sha256": hash_file(manifest_path),
            "completed_utc": manifest["completed_utc"],
        }
        append_receipt(destination_dir, receipt)
        report["receipt"] = receipt
    return report


# ── output (one dict, two renderings) ──────────────────────────────────

def format_report(report):
    lines = []
    if report["mode"] == "CHECK_AGE":
        lines.append("vault_backup --check-age  (backup_age gate stage)")
        lines.append("  destination : %s" % report["destination_dir"])
        lines.append("  completed_utc: %s" % report["completed_utc"])
        lines.append("  age_days    : %s (limit %d)"
                     % (report["age_days"], report["max_age_days"]))
        for finding in report["findings"]:
            lines.append("  FINDING: %s" % finding)
        lines.append("VERDICT: %s"
                     % ("FRESH" if report["exit_code"] == EXIT_CLEAN
                        else "STALE / FINDINGS"))
        return "\n".join(lines)
    counts = report["counts"]
    lines.append("vault_backup %s  mode=%s"
                 % ("--apply" if report["apply"]
                    else "(dry-run — zero writes)", report["mode"]))
    lines.append("  vault       : %s" % report["vault_dir"])
    lines.append("  destination : %s" % report["destination_dir"])
    for warning in report["warnings"]:
        lines.append("  WARNING: %s" % warning)
    for item in report["drift"]:
        lines.append("  %-12s %s" % (item["action"], item["file"]))
    for finding in report["findings"]:
        lines.append("  FINDING: %s" % finding)
    lines.append("  scanned=%d copied=%d skipped=%d trashed=%d "
                 "renamed=%d unstable=%d locked=%d symlinks=%d "
                 "excluded=%d bytes=%d"
                 % (counts["scanned"], counts["copied"],
                    counts["skipped"], counts["trashed"],
                    counts["renamed"], counts["unstable"],
                    counts["locked"], counts["symlinks"],
                    counts["excluded"], counts["bytes_copied"]))
    lines.append("VERDICT: %s"
                 % ("CLEAN — nothing to do"
                    if report["exit_code"] == EXIT_CLEAN
                    else ("DRIFT APPLIED" if report["apply"]
                          else "DRIFT FOUND (dry-run; --apply writes)"))
                 )
    return "\n".join(lines)


def _main(argv=None):
    _ensure_utf8_console()
    parser = argparse.ArgumentParser(
        prog="vault_backup.py",
        description="Vault -> Drive-folder mirror. Dry-run by default; "
                    "--apply writes. --check-age is the backup_age "
                    "gate stage.")
    parser.add_argument("--config", default=DEFAULT_CONFIG_NAME,
                        help="config JSON (default %(default)s)")
    parser.add_argument("--apply", action="store_true",
                        help="perform the mirror (default is dry-run, "
                             "zero writes)")
    parser.add_argument("--check-age", action="store_true",
                        dest="check_age_flag",
                        help="gate stage: fail if the last completed "
                             "backup is older than max_age_days")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable report (same dict as "
                             "the human output)")
    args = parser.parse_args(argv)
    try:
        if args.apply and args.check_age_flag:
            raise ToolError("--apply and --check-age are different "
                            "runs — pick one")
        config = load_config(args.config)
        if args.check_age_flag:
            report = check_age(config)
        else:
            report = run_backup(config, apply=args.apply)
    except ToolError as err:
        message = "ERROR: %s" % err
        if args.json:
            print(json.dumps({"tool": TOOL_NAME, "error": str(err),
                              "exit_code": EXIT_ERROR},
                             sort_keys=True, ensure_ascii=False))
        else:
            print(message, file=sys.stderr)
        return EXIT_ERROR
    if args.json:
        print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    else:
        print(format_report(report))
    return report["exit_code"]


def _crash_receipt_dir(argv):
    """Where a CRASH receipt may go, or None — and None is the honest
    answer more often than not. A crash before the config loads has no
    destination at all. A destination this tool has never written to
    is exactly what W0 exists to protect: dropping a receipts file
    into the wrong folder is the mistake, not the record. Both cases
    get the CRASH line and no receipt."""
    source = sys.argv[1:] if argv is None else list(argv)
    config_path = DEFAULT_CONFIG_NAME
    for index, item in enumerate(source):
        if item == "--config" and index + 1 < len(source):
            config_path = source[index + 1]
        elif item.startswith("--config="):
            config_path = item.split("=", 1)[1]
    try:
        destination = load_config(config_path)["destination_dir"]
    except Exception:
        return None
    for name in (MANIFEST_NAME, RECEIPTS_NAME):
        if os.path.exists(_winpath(os.path.join(destination, name))):
            return destination
    return None


def main(argv=None):
    """CRASH FLOOR. A bare traceback exits 1, and this tool's contract
    reads 1 as "findings" — so without this guard a crash and a real
    run are the same integer to gate_run and to any wrapper. SystemExit
    and KeyboardInterrupt are NOT caught: argparse owns exit 2 for a
    bad flag and must stay untouched.

    The receipt is BEST EFFORT and says so: this tool's ledger lives
    in the destination folder, so a crash before the config loads —
    or one aimed at a folder this tool has never written to — prints
    the CRASH line and exits 2 with NO receipt. An honest "no
    destination yet" beats a receipt that silently is not written."""
    try:
        return _main(argv)
    except Exception as err:
        reason = "%s: %s" % (type(err).__name__, err)
        destination = _crash_receipt_dir(argv)
        if destination is not None:
            try:
                append_receipt(destination, {"tool": TOOL_NAME,
                                             "kind": "CRASH",
                                             "reason": reason,
                                             "exit_code": EXIT_ERROR})
            except Exception:
                pass                  # a receipt must never mask this
        source = sys.argv[1:] if argv is None else list(argv)
        if "--json" in source:
            print(json.dumps({"tool": TOOL_NAME, "kind": "CRASH",
                              "reason": reason,
                              "receipt_written": destination is not None,
                              "exit_code": EXIT_ERROR},
                             sort_keys=True, ensure_ascii=False))
        else:
            print("CRASH (%s): %s" % (type(err).__name__, err),
                  file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
