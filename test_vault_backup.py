#!/usr/bin/env python3
"""Tests for vault_backup.py — MC BUILD 1 walls T0-T15 plus
registration and config fail-closed cases.

The court specced pytest; pytest is not installed in this environment
(flagged deviation, D-394), so these are unittest-style tests — which
pytest collects and runs unchanged the day it lands.

Every wall test builds a real vault and destination inside a temp dir
and drives the tool in-process through main()/run_backup(), never
against Khai's real folders.
"""

import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import unicodedata
from datetime import datetime, timedelta, timezone
from unittest import mock

import vault_backup as vb


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def snapshot_tree(root):
    """(relpath, size, sha256, mtime_ns) for every regular file, plus
    the sorted set of dirs — enough to prove zero change (W8/T9/T10)."""
    files = []
    dirs = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        filenames.sort()
        for name in dirnames:
            dirs.append(os.path.relpath(os.path.join(dirpath, name),
                                        root))
        for name in filenames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                files.append((os.path.relpath(full, root), "symlink",
                              os.readlink(full)))
                continue
            stat = os.lstat(full)
            with open(full, "rb") as fh:
                digest = sha256_bytes(fh.read())
            files.append((os.path.relpath(full, root), stat.st_size,
                          digest, stat.st_mtime_ns))
    return sorted(dirs), sorted(files)


class BackupCase(unittest.TestCase):
    """Shared fixture: fresh vault + destination + config per test."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="vb_test_")
        self.addCleanup(shutil.rmtree, self.tmp)
        self.vault = os.path.join(self.tmp, "vault")
        self.dest = os.path.join(self.tmp, "dest")
        os.makedirs(self.vault)
        self.config_path = os.path.join(self.tmp, "config.json")
        self.write_config()
        # W7 backoff sleeps are pointless in tests
        self._old_sleep = vb._sleep
        vb._sleep = lambda s: None
        self.addCleanup(self._restore_sleep)

    def _restore_sleep(self):
        vb._sleep = self._old_sleep

    def write_config(self, **extra):
        cfg = {"vault_dir": self.vault, "destination_dir": self.dest}
        cfg.update(extra)
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh)

    def put(self, rel, data=b"content\n"):
        full = os.path.join(self.vault, *rel.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(data)
        return full

    def run_tool(self, *flags):
        return vb.main(["--config", self.config_path, *flags])

    def manifest(self):
        with open(os.path.join(self.dest, vb.MANIFEST_NAME),
                  encoding="utf-8") as fh:
            return json.load(fh)

    def receipts(self):
        path = os.path.join(self.dest, vb.RECEIPTS_NAME)
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]


class T00DestinationSafety(BackupCase):
    def test_apply_nonempty_no_manifest_refused(self):
        """T0: --apply into non-empty dir w/o manifest -> 2, 0 writes."""
        self.put("note.md")
        os.makedirs(self.dest)
        stranger = os.path.join(self.dest, "unrelated.txt")
        with open(stranger, "wb") as fh:
            fh.write(b"not ours")
        before = snapshot_tree(self.dest)
        with mock.patch("sys.stderr"):
            code = self.run_tool("--apply")
        self.assertEqual(code, 2)
        self.assertEqual(snapshot_tree(self.dest), before)
        self.assertFalse(
            os.path.exists(os.path.join(self.dest, vb.MANIFEST_NAME)))

    def test_empty_destination_is_initial_full(self):
        self.put("note.md")
        os.makedirs(self.dest)
        with mock.patch("sys.stdout"):
            code = self.run_tool("--apply")
        self.assertEqual(code, 1)
        self.assertEqual(self.receipts()[0]["mode"], "INITIAL_FULL")


class T01NfcRoundTrip(BackupCase):
    def test_nfd_then_nfc_one_entry_no_trash(self):
        """T1: NFC/NFD round-trip -> ONE manifest entry, no _trash."""
        nfd = unicodedata.normalize("NFD", "Café.md")
        nfc = unicodedata.normalize("NFC", "Café.md")
        self.assertNotEqual(nfd, nfc)
        self.put(nfd, b"note body\n")
        with mock.patch("sys.stdout"):
            self.assertEqual(self.run_tool("--apply"), 1)
        # the OS may store either spelling; simulate the sync
        # round-trip by re-spelling the source name the other way
        src_names = os.listdir(self.vault)
        self.assertEqual(len(src_names), 1)
        os.rename(os.path.join(self.vault, src_names[0]),
                  os.path.join(self.vault, nfc))
        if os.listdir(self.vault) == src_names:
            self.skipTest("filesystem normalizes names itself")
        with mock.patch("sys.stdout"):
            self.run_tool("--apply")
        manifest = self.manifest()
        self.assertEqual(len(manifest["files"]), 1)
        self.assertEqual(list(manifest["files"]), [nfc])
        trash = os.path.join(self.dest, vb.TRASH_DIRNAME)
        self.assertFalse(os.path.isdir(trash) and
                         any(files for _, _, files in os.walk(trash)))
        receipts = self.receipts()
        self.assertEqual(receipts[-1]["trashed"], 0)


class T02EmojiFilename(BackupCase):
    def test_emoji_name_survives_cycle(self):
        """T2: emoji filename survives a full cycle, raw name on disk."""
        name = "🏠 Café.md"
        body = b"emoji note\n"
        self.put(name, body)
        with mock.patch("sys.stdout"):
            self.assertEqual(self.run_tool("--apply"), 1)
        dest_names = [n for n in os.listdir(self.dest)
                      if n not in (vb.MANIFEST_NAME, vb.RECEIPTS_NAME,
                                   vb.STAGING_DIRNAME, vb.TRASH_DIRNAME)]
        self.assertEqual(dest_names, [name])
        with open(os.path.join(self.dest, name), "rb") as fh:
            self.assertEqual(fh.read(), body)
        key = unicodedata.normalize("NFC", name)
        entry = self.manifest()["files"][key]
        self.assertEqual(entry["raw_name"], name)
        self.assertEqual(entry["sha256"], sha256_bytes(body))
        with mock.patch("sys.stdout"):
            self.assertEqual(self.run_tool("--apply"), 0)  # stable


class T03InterruptedCopy(BackupCase):
    def test_no_manifest_entry_for_interrupted_file(self):
        """T3: interrupted copy -> no manifest entry for that file."""
        self.put("a.md", b"first\n")
        self.put("z.md", b"last\n")
        real = vb.stage_copy

        def exploding(src_abs, staging_dir):
            if src_abs.endswith("z.md"):
                raise RuntimeError("simulated crash mid-copy")
            return real(src_abs, staging_dir)

        with mock.patch.object(vb, "stage_copy", exploding):
            with self.assertRaises(RuntimeError):
                vb.run_backup(vb.load_config(self.config_path),
                              apply=True)
        manifest = self.manifest()   # written after a.md (W2 per-file)
        self.assertIn("a.md", manifest["files"])
        self.assertNotIn("z.md", manifest["files"])
        self.assertIsNone(manifest["completed_utc"])


class T04TruncatedManifest(BackupCase):
    def test_truncated_manifest_exit2_zero_copies(self):
        """T4: truncated manifest -> exit 2, ZERO files copied."""
        self.put("note.md")
        os.makedirs(self.dest)
        with open(os.path.join(self.dest, vb.MANIFEST_NAME), "w",
                  encoding="utf-8") as fh:
            fh.write('{"version": 1, "tool": "vault_ba')
        before = snapshot_tree(self.dest)
        with mock.patch("sys.stderr"):
            self.assertEqual(self.run_tool("--apply"), 2)
            self.assertEqual(self.run_tool(), 2)   # dry-run too (W3)
        self.assertEqual(snapshot_tree(self.dest), before)


class T05T06Symlinks(BackupCase):
    def test_dangling_symlink_skipped_run_completes(self):
        """T5: dangling symlink -> SKIPPED_SYMLINK, run completes."""
        self.put("real.md")
        os.symlink(os.path.join(self.vault, "gone.md"),
                   os.path.join(self.vault, "dangling.md"))
        with mock.patch("sys.stdout"):
            self.assertEqual(self.run_tool("--apply"), 1)
        receipt = self.receipts()[-1]
        self.assertEqual(receipt["symlinks"], 1)
        self.assertEqual(receipt["copied"], 1)
        self.assertNotIn(
            "dangling.md",
            [e["raw_name"] for e in self.manifest()["files"].values()])

    def test_valid_symlink_not_followed_not_copied(self):
        """T6: valid symlink -> not followed, not copied."""
        self.put("target.md", b"real bytes\n")
        os.symlink(os.path.join(self.vault, "target.md"),
                   os.path.join(self.vault, "link.md"))
        sub = os.path.join(self.vault, "sub")
        os.makedirs(sub)
        os.symlink(self.vault, os.path.join(sub, "loop"))
        with mock.patch("sys.stdout"):
            self.assertEqual(self.run_tool("--apply"), 1)
        receipt = self.receipts()[-1]
        self.assertEqual(receipt["symlinks"], 2)
        self.assertEqual(receipt["copied"], 1)
        self.assertFalse(os.path.exists(os.path.join(self.dest,
                                                     "link.md")))


class T07Unstable(BackupCase):
    def test_mutation_between_hash_and_copy(self):
        """T7: file mutated between hash and copy -> UNSTABLE after
        exactly one retry, no manifest entry."""
        self.put("stable.md", b"calm\n")
        self.put("twitchy.md", b"v1\n")
        calls = {"n": 0}
        real = vb.stage_copy

        def corrupting(src_abs, staging_dir):
            staged = real(src_abs, staging_dir)
            if src_abs.endswith("twitchy.md"):
                calls["n"] += 1
                with open(staged, "ab") as fh:   # autosave mid-copy
                    fh.write(b"mutated\n")
            return staged

        with mock.patch.object(vb, "stage_copy", corrupting), \
                mock.patch("sys.stdout"):
            self.assertEqual(self.run_tool("--apply"), 1)
        self.assertEqual(calls["n"], 2)          # initial + ONE retry
        manifest = self.manifest()
        self.assertIn("stable.md", manifest["files"])
        self.assertNotIn("twitchy.md", manifest["files"])
        receipt = self.receipts()[-1]
        self.assertEqual(receipt["unstable"], 1)
        self.assertIsNotNone(receipt["completed_utc"])


class T08Trash(BackupCase):
    def test_deletion_lands_in_dated_trash(self):
        """T8: deletion -> _trash/<date>/, source untouched."""
        self.put("keep.md", b"stays\n")
        doomed = self.put("sub/doomed.md", b"bye\n")
        with mock.patch("sys.stdout"):
            self.run_tool("--apply")
        os.rename(doomed, os.path.join(self.tmp, "doomed.moved"))
        vault_before = snapshot_tree(self.vault)
        with mock.patch("sys.stdout"):
            self.assertEqual(self.run_tool("--apply"), 1)
        self.assertEqual(snapshot_tree(self.vault), vault_before)
        day = datetime.now(timezone.utc).strftime(vb.TRASH_DATE_FMT)
        trashed = os.path.join(self.dest, vb.TRASH_DIRNAME, day,
                               "sub", "doomed.md")
        with open(trashed, "rb") as fh:
            self.assertEqual(fh.read(), b"bye\n")
        self.assertFalse(os.path.exists(
            os.path.join(self.dest, "sub", "doomed.md")))
        self.assertNotIn("sub/doomed.md", self.manifest()["files"])


class T09DryRunZeroWrites(BackupCase):
    def test_dry_run_writes_nothing(self):
        """T9: dry-run -> zero writes anywhere (snapshot diff)."""
        self.put("a.md")
        self.put("b/c.md")
        vault_before = snapshot_tree(self.vault)
        with mock.patch("sys.stdout"):
            code = self.run_tool()
        self.assertEqual(code, 1)                 # drift found
        self.assertEqual(snapshot_tree(self.vault), vault_before)
        self.assertFalse(os.path.exists(self.dest))   # not even mkdir
        # and against an existing backup with drift:
        with mock.patch("sys.stdout"):
            self.run_tool("--apply")
        self.put("d.md")
        dest_before = snapshot_tree(self.dest)
        with mock.patch("sys.stdout"):
            self.assertEqual(self.run_tool(), 1)
        self.assertEqual(snapshot_tree(self.dest), dest_before)


class T10VaultReadOnly(BackupCase):
    def test_vault_byte_identical_after_apply(self):
        """T10/W8: vault byte-identical (incl. mtimes) after --apply."""
        self.put("a.md", b"alpha\n")
        self.put("deep/b.md", b"beta\n")
        os.symlink(os.path.join(self.vault, "a.md"),
                   os.path.join(self.vault, "link.md"))
        before = snapshot_tree(self.vault)
        with mock.patch("sys.stdout"):
            self.run_tool("--apply")
        self.assertEqual(snapshot_tree(self.vault), before)


class T11Excludes(BackupCase):
    def test_default_excludes_never_copied_and_counted(self):
        """T11: default excludes (incl. config/identity.json and all
        of config/) never copied, COUNTED in the receipt."""
        self.put("real.md")
        self.put("config/identity.json", b"{}")
        self.put("config/pricing.json", b"{}")
        self.put("old.bak")
        self.put(".obsidian/workspace.json", b"{}")
        self.put(".obsidian/app.json", b"{}")     # NOT excluded
        self.put("__pycache__/x.pyc", b"\x00")
        with mock.patch("sys.stdout"):
            self.assertEqual(self.run_tool("--apply"), 1)
        copied = sorted(e["raw_name"]
                        for e in self.manifest()["files"].values())
        self.assertEqual(copied, [".obsidian/app.json", "real.md"])
        self.assertFalse(os.path.exists(os.path.join(self.dest,
                                                     "config")))
        receipt = self.receipts()[-1]
        # old.bak + workspace.json + config dir + __pycache__ dir
        self.assertGreaterEqual(receipt["excluded"], 4)

    def test_config_excludes_are_additive(self):
        self.put("real.md")
        self.put("secret.pem", b"x")
        self.write_config(excludes=["*.pem"])
        with mock.patch("sys.stdout"):
            self.run_tool("--apply")
        self.assertEqual(
            [e["raw_name"] for e in self.manifest()["files"].values()],
            ["real.md"])


class T12BackupAge(BackupCase):
    def _manifest_completed(self, days_ago):
        os.makedirs(self.dest, exist_ok=True)
        done = datetime.now(timezone.utc) - timedelta(days=days_ago)
        manifest = {"version": 1, "tool": "vault_backup",
                    "completed_utc":
                        done.isoformat(timespec="seconds"),
                    "files": {}}
        path = os.path.join(self.dest, vb.MANIFEST_NAME)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh)
        os.utime(path, (done.timestamp(), done.timestamp()))
        return path

    def test_fails_past_limit_passes_inside_it(self):
        """T12: fails at N+1 days, passes at N-1 (default N=3)."""
        self._manifest_completed(days_ago=4)
        with mock.patch("sys.stdout"):
            self.assertEqual(self.run_tool("--check-age"), 1)
        self._manifest_completed(days_ago=2)
        with mock.patch("sys.stdout"):
            self.assertEqual(self.run_tool("--check-age"), 0)

    def test_reads_completed_utc_not_mtime(self):
        """A fresh mtime (sync touched it) must NOT rescue a stale
        backup — and the skew is its own finding."""
        path = self._manifest_completed(days_ago=10)
        now = datetime.now(timezone.utc).timestamp()
        os.utime(path, (now, now))
        report = vb.check_age(vb.load_config(self.config_path))
        self.assertEqual(report["exit_code"], 1)
        self.assertTrue(any("backup_age FAIL" in f
                            for f in report["findings"]))
        self.assertTrue(any("disagree" in f
                            for f in report["findings"]))

    def test_missing_manifest_is_exit_2(self):
        os.makedirs(self.dest)
        with mock.patch("sys.stderr"):
            self.assertEqual(self.run_tool("--check-age"), 2)

    def test_never_completed_is_a_finding(self):
        os.makedirs(self.dest, exist_ok=True)
        with open(os.path.join(self.dest, vb.MANIFEST_NAME), "w",
                  encoding="utf-8") as fh:
            json.dump({"version": 1, "tool": "vault_backup",
                       "completed_utc": None, "files": {}}, fh)
        with mock.patch("sys.stdout"):
            self.assertEqual(self.run_tool("--check-age"), 1)


class T13SecondRunStable(BackupCase):
    def test_no_changes_zero_copied_exit0_receipt_written(self):
        """T13: second run, no changes -> 0 copied, exit 0, receipt."""
        self.put("a.md")
        self.put("b/c.md")
        with mock.patch("sys.stdout"):
            self.assertEqual(self.run_tool("--apply"), 1)
            self.assertEqual(self.run_tool("--apply"), 0)
        receipts = self.receipts()
        self.assertEqual(len(receipts), 2)
        self.assertEqual(receipts[1]["copied"], 0)
        self.assertEqual(receipts[1]["mode"], "MIRROR")
        self.assertEqual(receipts[1]["scanned"], 2)


class T14LockedFile(BackupCase):
    def test_permission_error_locked_skipped_run_completes(self):
        """T14: PermissionError on one file -> LOCKED_SKIPPED after 3
        retries, everything else still copied."""
        self.put("free.md", b"ok\n")
        self.put("locked.md", b"drive is syncing me\n")
        attempts = {"n": 0}
        real = vb._open_for_read

        def locked_open(path):
            if path.endswith("locked.md"):
                attempts["n"] += 1
                raise PermissionError("simulated Drive lock")
            return real(path)

        with mock.patch.object(vb, "_open_for_read", locked_open), \
                mock.patch("sys.stdout"):
            self.assertEqual(self.run_tool("--apply"), 1)
        self.assertEqual(attempts["n"], 1 + len(vb.RETRY_BACKOFF_S))
        manifest = self.manifest()
        self.assertIn("free.md", manifest["files"])
        self.assertNotIn("locked.md", manifest["files"])
        receipt = self.receipts()[-1]
        self.assertEqual(receipt["locked"], 1)
        self.assertEqual(receipt["copied"], 1)


class T15LongPath(BackupCase):
    def test_long_destination_path_warned_up_front(self):
        """T15: destination path over 240 chars -> pre-flight warning."""
        segments = ["d" * 40] * 6                 # >240 total
        rel = "/".join(segments) + "/note.md"
        self.put(rel, b"deep\n")
        report = vb.run_backup(vb.load_config(self.config_path),
                               apply=False)
        self.assertTrue(any("W6 LONG PATH" in w
                            for w in report["warnings"]))
        # the warning names a length over the limit
        self.assertTrue(any(str(vb.LONG_PATH_WARN) in w
                            for w in report["warnings"]))


class GateRegistration(unittest.TestCase):
    def test_backup_age_registered_in_fleet(self):
        """The backup_age stage is a real gate_run FLEET entry."""
        import gate_run
        stages = {s["name"]: s for s in gate_run.FLEET}
        self.assertIn("backup_age", stages)
        stage = stages["backup_age"]
        self.assertEqual(stage["path"], "vault_backup.py")
        self.assertEqual(stage["args"], ["--check-age"])


class CrashFloor(BackupCase):
    """Fleet crash floor: a Python traceback exits 1, which this
    tool's contract reads as "findings". Exit 2 is what tells a
    wrapper the tool broke. The receipt is best effort BY DESIGN —
    this ledger lives in the destination folder."""

    def test_uncaught_exception_is_exit_2_with_a_receipt(self):
        self.put("a.txt")
        self.assertIn(self.run_tool("--apply"), (0, 1))
        with mock.patch.object(vb, "run_backup",
                               side_effect=RuntimeError("injected")):
            with mock.patch("sys.stderr", io.StringIO()) as err:
                code = self.run_tool("--apply")
        self.assertEqual(code, 2)
        self.assertIn("CRASH (RuntimeError): injected", err.getvalue())
        receipt = self.receipts()[-1]
        self.assertEqual(receipt["kind"], "CRASH")
        self.assertEqual(receipt["exit_code"], 2)
        with mock.patch.object(vb, "run_backup",
                               side_effect=RuntimeError("injected")):
            with mock.patch("sys.stdout", io.StringIO()) as out:
                self.assertEqual(self.run_tool("--apply", "--json"), 2)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["kind"], "CRASH")
        self.assertEqual(payload["exit_code"], 2)
        self.assertTrue(payload["receipt_written"])

    def test_no_destination_yet_means_no_receipt_not_a_silent_one(self):
        """Fable's ruling: an honest "no destination" beats a receipt
        that silently is not written. Two ways to have none — the
        config never loaded, and a folder this tool has never written
        to (which is what W0 protects)."""
        with mock.patch.object(vb, "run_backup",
                               side_effect=RuntimeError("injected")):
            with mock.patch("sys.stderr", io.StringIO()) as err:
                code = self.run_tool("--apply")
        self.assertEqual(code, 2)
        self.assertIn("CRASH (RuntimeError): injected", err.getvalue())
        self.assertEqual(self.receipts(), [])
        self.assertFalse(os.path.exists(self.dest))

        with mock.patch.object(vb, "load_config",
                               side_effect=RuntimeError("injected")):
            with mock.patch("sys.stderr", io.StringIO()) as err:
                code = self.run_tool("--apply")
        self.assertEqual(code, 2)
        self.assertIn("CRASH (RuntimeError): injected", err.getvalue())
        self.assertEqual(self.receipts(), [])

    def test_argparse_exit_is_not_swallowed(self):
        with mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                vb.main(["--config", self.config_path, "--bogus"])
        self.assertEqual(caught.exception.code, 2)


class ConfigFailClosed(BackupCase):
    def test_missing_config_exit_2(self):
        with mock.patch("sys.stderr"):
            self.assertEqual(
                vb.main(["--config",
                         os.path.join(self.tmp, "nope.json")]), 2)

    def test_unknown_config_key_exit_2(self):
        self.write_config(surprise=True)
        with mock.patch("sys.stderr"):
            self.assertEqual(self.run_tool(), 2)

    def test_hardcoded_paths_refused(self):
        """vault_dir must exist — a config pointing nowhere is exit 2,
        never a silently-created empty mirror."""
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump({"vault_dir": os.path.join(self.tmp, "ghost"),
                       "destination_dir": self.dest}, fh)
        with mock.patch("sys.stderr"):
            self.assertEqual(self.run_tool(), 2)

    def test_apply_plus_check_age_refused(self):
        self.put("a.md")
        with mock.patch("sys.stderr"):
            self.assertEqual(self.run_tool("--apply", "--check-age"), 2)

    def test_json_parity_same_dict(self):
        """--json output is the report dict itself."""
        self.put("a.md")
        import io
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            code = self.run_tool("--json")
        payload = json.loads(buf.getvalue())
        self.assertEqual(code, payload["exit_code"])
        self.assertEqual(payload["counts"]["scanned"], 1)


if __name__ == "__main__":
    unittest.main()
