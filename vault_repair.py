#!/usr/bin/env python3
"""vault_repair.py — STATE.md split-row repair. A DIFFERENT PROGRAM
from vault_lint, which stays read-only forever ("there is no --fix flag
and there never will be one" remains true).

Scope is the "broken" class only: rows split across physical lines.
Nothing else. Detection runs live through vault_lint's pure detect() —
one source of truth for what "broken" means — while this tool does its
OWN strict read: vault_lint reads with errors='replace' (correct for a
read-only reporter; a replace round-trip VERIFIABLY grew an 86-byte
file to 88 and destroyed byte 0xe9), and this tool must never repair a
file it cannot faithfully reproduce.

Nothing is written without --apply AND an interactive approval. Dry-run
performs zero filesystem writes of any kind. --json plus --apply is
refused (no terminal, no human, no write). There is no --yes, no
--force, no batch mode.

Built from the PM FORGE hardened spec (forged 2026-08-20; the document
header's "2026-08-13" is a recurring template quirk).

Exit codes:
    0 = nothing to repair (clean file, or idempotent re-run)
    1 = repairs proposed (dry-run) or applied (fully or partially)
    2 = tool error / abort — decode error, hash mismatch, backup
        failure, --json+--apply, unknown flag, missing file

Standard library only; vault_lint is imported for detection only.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

import vault_lint as vl

# ═══════════════════════════════════════════════════════════════════════
# RULE DATA.
# ═══════════════════════════════════════════════════════════════════════

MAX_CONTINUATION_LINES = 3
# A row may wrap onto a few physical lines; a longer run is more likely
# a parse artifact than one wrapped cell — skip it.

JOIN_SEPARATOR = " "
# Inserted at a seam only when neither side already carries whitespace
# there; the diff shows every seam explicitly so the human sees the
# exact inserted character ("someone"+"pasted" -> "someonepasted"
# otherwise).

BACKUP_SUFFIX = ".vault_repair.%s.bak"
TEMP_SUFFIX = ".vault_repair.tmp"

HEADING_PREFIX = vl.HEADING_PREFIX
FENCE_MARKERS = vl.FENCE_MARKERS
HTML_COMMENT_OPEN = vl.HTML_COMMENT_OPEN

_ROW_RE = re.compile(vl.ROW_PATTERN)
_ROW_LAX_RE = re.compile(vl.ROW_START_LAX)

# ═══════════════════════════════════════════════════════════════════════
# END OF RULE DATA.
# ═══════════════════════════════════════════════════════════════════════

EXIT_NOTHING = 0
EXIT_REPAIRS = 1
EXIT_ERROR = 2


class RepairError(Exception):
    """Tool error or abort. Exit 2. Nothing has been written unless the
    message says otherwise."""


# ─────────────────────────── line discipline ───────────────────────────

def split_lines_keepends(content):
    """Split ONLY on "\\n", keepends. W5: NEVER str.splitlines().
    splitlines() also breaks on 0x0B 0x0C 0x1C 0x1D 0x1E 0x85 U+2028
    U+2029 — a single U+2028 shifts every subsequent line number (a
    repair lands on the WRONG ROW) and re-joining converts it into a
    real newline (an untouched byte, mangled). That one function call is
    attack class (b) and (c) at once. LEAVE THIS COMMENT IN THE CODE.
    A "\\r" before the "\\n" stays attached to its line; U+2028 etc.
    never split. "".join(result) == content, always."""
    parts = content.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1] != "":
        lines.append(parts[-1])   # no final newline: preserved as-is
    return lines


def split_terminator(line):
    """(body, terminator) where terminator is "\\r\\n", "\\n", or ""."""
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    return line, ""


# ──────────────────────────── strict reading ───────────────────────────

def read_strict(path):
    """W4: strict decode or abort — never repair a file you cannot
    faithfully reproduce. W11: newline="" (universal newlines VERIFIABLY
    eats every CRLF on write-back), plain utf-8 never utf-8-sig (sig
    strips the BOM and write-back deletes it)."""
    if os.path.islink(path):
        raise RepairError(
            "%s is a symlink — refusing: os.replace would destroy the "
            "link and leave a regular file in its place. Run against "
            "the real path: %s" % (path, os.path.realpath(path)))
    if not os.path.isfile(path):
        raise RepairError("file not found: %s" % path)
    try:
        with open(path, "r", encoding="utf-8", errors="strict",
                  newline="") as handle:
            return handle.read()
    except UnicodeDecodeError:
        with open(path, "rb") as handle:
            data = handle.read()
        try:
            data.decode("utf-8")
            offset, lineno = -1, -1
        except UnicodeDecodeError as exc:
            offset = exc.start
            lineno = data[:offset].count(b"\n") + 1
        raise RepairError(
            "%s is not valid UTF-8 (bad byte at offset %d, line %d) — "
            "aborting: a repair through errors='replace' would destroy "
            "the original byte permanently" % (path, offset, lineno))
    except OSError as exc:
        raise RepairError("cannot read %s: %s" % (path, exc))


def file_fingerprint(path):
    stat = os.stat(path)
    with open(path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    return {"sha256": digest, "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns}


# ─────────────────────── candidates and the rejoin ─────────────────────

def _identity(findings):
    """W-verified: every repair removes a line, so every downstream
    finding's line number shifts — a (check, line) diff reports
    unchanged findings as brand new. Identity is (check, D-label)."""
    return {(f["check"], f["dlabel"]) for f in findings}


def _consumable(body):
    """Why a line may NOT be consumed as a continuation, or None."""
    stripped = body.strip()
    rst = body.rstrip()
    if stripped == "":
        return "continuation is blank"
    if stripped.startswith(HEADING_PREFIX):
        return "continuation is a heading"
    if stripped.startswith(FENCE_MARKERS):
        return "continuation is a code-fence marker"
    if stripped.startswith(HTML_COMMENT_OPEN):
        return "continuation is an HTML comment"
    if _ROW_RE.match(rst):
        return ("next line is itself a row — rejoining would merge two "
                "decisions and erase one (W6)")
    if _ROW_LAX_RE.match(rst):
        return ("next line begins another D-row — rejoining would merge "
                "two decisions (W6)")
    return None


def build_candidates(lines, det):
    """Turn vault_lint's live broken findings into proposals or named
    skips. Every skip names its failing condition; nothing is guessed.

    The dominant column shape is learned from CLOSED rows only:
    vault_lint's shape statistics include unclosed (broken) rows, so in
    a small file the very rows being repaired would erode the
    confidence needed to validate their own repair."""
    from collections import Counter
    closed = Counter(r["pipes"] for r in det["scan"]["rows"]
                     if r["closed"])
    dominant, confident = None, False
    if closed:
        dominant, dom_n = sorted(closed.items(),
                                 key=lambda kv: (-kv[1], kv[0]))[0]
        confident = (dom_n / sum(closed.values())) >= vl.DOMINANT_MAJORITY
    broken = [f for f in det["findings"] if f["check"] == "broken"]
    proposals, skipped = [], []

    def skip(finding, reason):
        skipped.append({"dnum": finding["dnum"],
                        "dlabel": finding["dlabel"],
                        "line": finding["line"], "reason": reason})

    for finding in sorted(broken, key=lambda f: f["line"]):
        if not confident or dominant is None:
            skip(finding, "no dominant column shape to validate the "
                          "rejoined row against")
            continue
        start_idx = finding["line"] - 1
        base_body, _base_term = split_terminator(lines[start_idx])

        consumed = []
        reason = None
        idx = start_idx + 1
        while True:
            if idx >= len(lines):
                reason = "run reaches end of file without a line ending in '|'"
                break
            body, term = split_terminator(lines[idx])
            why = _consumable(body)
            if why is not None:
                reason = why
                break
            consumed.append((idx, body, term))
            if body.rstrip().endswith("|"):
                break
            if len(consumed) >= MAX_CONTINUATION_LINES:
                reason = ("run exceeds MAX_CONTINUATION_LINES (%d) "
                          "without terminating in '|'"
                          % MAX_CONTINUATION_LINES)
                break
            idx += 1
        if reason is not None:
            skip(finding, reason)
            continue

        joined = base_body
        seams = []
        for _idx, body, _term in consumed:
            if joined and (joined[-1].isspace() or (body and body[0].isspace())):
                seams.append({"inserted": None,
                              "note": "joined as-is (whitespace already "
                                      "present at the seam)"})
            else:
                seams.append({"inserted": JOIN_SEPARATOR,
                              "note": "inserted %r" % JOIN_SEPARATOR})
                joined += JOIN_SEPARATOR
            joined += body

        joined_rst = joined.rstrip()
        match = _ROW_RE.match(joined_rst)
        if not match:
            skip(finding, "rejoined text does not parse as a D-row")
            continue
        if int(match.group(1)) != finding["dnum"]:
            skip(finding, "rejoined row parses as D-%s, expected %s"
                          % (match.group(1), finding["dlabel"]))
            continue
        pipes = joined_rst.count("|")
        if pipes != dominant:
            skip(finding, "rejoined row has %d pipes, dominant is %d"
                          % (pipes, dominant))
            continue

        # Rider 3: the repaired row carries the terminator of the LAST
        # consumed continuation line — a CRLF file's repaired row still
        # ends \r\n.
        last_term = consumed[-1][2]
        proposals.append({
            "dnum": finding["dnum"], "dlabel": finding["dlabel"],
            "line": finding["line"],
            "last_line": consumed[-1][0] + 1,
            "consumed": [c[0] for c in consumed],
            "original": [lines[start_idx]] + [lines[c[0]] for c in consumed],
            "proposed_body": joined,
            "proposed_line": joined + last_term,
            "seams": seams,
            "pipes": pipes,
        })

    # DRY-VERIFY IN MEMORY, per candidate, before anything is offered:
    # apply just this candidate to a copy, detect(), compare BY IDENTITY.
    # Catching a bad proposal before touching disk makes the post-apply
    # verification a second net, not the only one.
    pre_identity = _identity(det["findings"])
    verified = []
    for cand in proposals:
        trial = apply_to_lines(lines, [cand])
        post = vl.detect(trial)
        fresh = _identity(post["findings"]) - pre_identity
        if fresh:
            names = sorted("%s %s" % (check, dlabel or "(file-wide)")
                           for check, dlabel in fresh)
            skipped.append({
                "dnum": cand["dnum"], "dlabel": cand["dlabel"],
                "line": cand["line"],
                "reason": "repair would create new finding(s): %s — "
                          "refused before any write" % ", ".join(names),
            })
        else:
            verified.append(cand)

    verified.sort(key=lambda c: (c["line"], c["dnum"]))
    skipped.sort(key=lambda s: (s["line"], s["dnum"] or 0))
    return verified, skipped


def apply_to_lines(lines, candidates):
    """W7: strictly DESCENDING line order — each join deletes lines, so
    every later index slides up. VERIFIED: ascending apply silently
    joined the wrong two lines on repair #2 and threw IndexError on
    repair #3; the crash is the lucky case."""
    out = list(lines)
    for cand in sorted(candidates, key=lambda c: c["line"], reverse=True):
        idx = cand["line"] - 1
        out[idx] = cand["proposed_line"]
        del out[idx + 1:idx + 1 + len(cand["consumed"])]
    return out


# ─────────────────────────── the apply machinery ───────────────────────

def read_key(prompt):
    """Isolated so tests can script it. EOF/interrupt are handled by the
    caller as 'q' — never as approval."""
    return input(prompt)


def collect_approvals(proposals, render_candidate):
    """One prompt, four keys, per D-347 walkthrough protocol. 'a'
    applies only candidates already on the repairable list — ambiguous
    ones were filtered out before this loop ever sees them."""
    approved, declined = [], []
    apply_all = False
    quit_now = False
    for cand in proposals:
        if quit_now:
            declined.append(cand)
            continue
        if apply_all:
            approved.append(cand)
            continue
        print(render_candidate(cand))
        while True:
            try:
                key = read_key("apply %s? [y/n/a/q] " % cand["dlabel"])
            except (EOFError, KeyboardInterrupt):
                key = "q"
            key = key.strip().lower()
            if key in ("y", "n", "a", "q"):
                break
        if key == "y":
            approved.append(cand)
        elif key == "n":
            declined.append(cand)
        elif key == "a":
            apply_all = True
            approved.append(cand)
        else:
            quit_now = True
            declined.append(cand)
    return approved, declined


def _fsync_dir(directory):
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_backup(path, content, backup_dir):
    """W10: backup before the original is touched, into the chosen
    directory, re-read and hash-compared. A name collision is an abort,
    never an overwrite."""
    stamp = _backup_stamp()
    backup = os.path.join(backup_dir,
                          os.path.basename(path) + (BACKUP_SUFFIX % stamp))
    if os.path.exists(backup):
        raise RepairError("backup path already exists: %s — refusing to "
                          "overwrite an existing backup" % backup)
    with open(backup, "w", encoding="utf-8", newline="") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    with open(backup, "r", encoding="utf-8", errors="strict",
              newline="") as handle:
        if handle.read() != content:
            raise RepairError("backup verification FAILED: %s does not "
                              "match the in-memory original — aborting, "
                              "nothing written to the target" % backup)
    return backup


def _backup_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


def atomic_write(path, new_content):
    """W9 one write at the end; steps 6-9 of the apply order. Temp file
    in the TARGET'S OWN directory (os.replace is atomic only within one
    filesystem; /tmp may be another mount), original's stat copied onto
    the temp (after replace the file carries the TEMP file's mode),
    fsync(file) then fsync(dir) (without both, a crash can leave a
    zero-length file where the rename looked successful), then
    os.replace — never os.rename."""
    directory = os.path.dirname(os.path.abspath(path))
    orig_stat = os.stat(path)
    temp = os.path.join(directory,
                        "." + os.path.basename(path) + TEMP_SUFFIX)
    try:
        with open(temp, "w", encoding="utf-8", newline="") as handle:
            handle.write(new_content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, orig_stat.st_mode)
        try:
            os.chown(temp, orig_stat.st_uid, orig_stat.st_gid)
        except (PermissionError, OSError):
            pass
        _fsync_dir(directory)
        os.replace(temp, path)
        _fsync_dir(directory)
    except RepairError:
        raise
    except Exception as exc:
        if os.path.exists(temp):
            os.remove(temp)
        raise RepairError(
            "atomic replace failed: %s — the original file is untouched "
            "and the temp file was removed" % exc)


# ───────────────────────────── rendering ───────────────────────────────

def render_candidate(cand):
    out = ["── PROPOSAL ── %s  L%d-%d  (%d lines -> 1)"
           % (cand["dlabel"], cand["line"], cand["last_line"],
              1 + len(cand["consumed"]))]
    for i, line in enumerate(cand["original"]):
        body, term = split_terminator(line)
        out.append("  - L%d: %s%s"
                   % (cand["line"] + i, body,
                      "  [ends %r]" % term if term != "\n" else ""))
    body, term = split_terminator(cand["proposed_line"])
    out.append("  + %s%s"
               % (body, "  [ends %r]" % term if term != "\n" else ""))
    for i, seam in enumerate(cand["seams"], 1):
        out.append("    seam %d: %s" % (i, seam["note"]))
    out.append("    pipes: %d (= dominant)" % cand["pipes"])
    return "\n".join(out)


def render_report(report):
    out = ["══ VAULT REPAIR ══ %s (%s)"
           % (report["file"], report["mode"])]
    out.append("broken findings: %d | proposals: %d | skipped: %d"
               % (report["broken_total"], len(report["proposals"]),
                  len(report["skipped"])))
    if report["mode"] == "dry-run":
        for cand in report["proposals"]:
            out.append("")
            out.append(render_candidate(cand))
    for item in report["skipped"]:
        out.append("── SKIPPED ── %s L%d: %s"
                   % (item["dlabel"], item["line"], item["reason"]))
    if report["mode"] == "dry-run":
        out.append("")
        out.append("DRY-RUN: zero filesystem writes performed. Re-run "
                   "with --apply to repair interactively.")
    else:
        out.append("")
        out.append("applied: %d | declined: %d | skipped: %d"
                   % (len(report["applied"]), len(report["declined"]),
                      len(report["skipped"])))
        if report.get("backup"):
            out.append("backup: %s" % report["backup"])
        if report.get("verification"):
            out.append(report["verification"])
    out.append("VERDICT: %s" % report["verdict"])
    return "\n".join(out)


def render_explain():
    return """\
══ VAULT REPAIR — WALLS AND WHY ══

W1  Scope is the "broken" class only — rows split across physical
    lines. vault_lint stays read-only forever; this is a different
    program.
W2  Nothing is written without --apply AND an interactive approval.
    Dry-run performs ZERO filesystem writes — no backup, no temp, no
    log.
W3  --json + --apply is refused (exit 2): no terminal means no human
    approval. There is no --yes, no --force, no batch mode.
W4  Strict decode or abort. VERIFIED: an errors='replace' round-trip
    grew an 86-byte file to 88 and destroyed byte 0xe9 permanently.
W5  Never str.splitlines() — it also breaks on VT, FF, FS/GS/RS, NEL,
    U+2028, U+2029. VERIFIED: one U+2028 shifts every later line
    number and a re-join converts it into a real newline. split("\\n")
    only.
W6  Never consume a line matching ROW_PATTERN. VERIFIED: rejoining a
    broken row with a following healthy row merges two decisions and
    ERASES one.
W7  Apply strictly descending. VERIFIED: ascending apply silently
    joined the wrong two lines on repair #2 and IndexError'd on #3.
W8  Hash lock re-verified immediately before the write, in the same
    code path as the write.
W9  One write, at the end — never per approval.
W10 Verified backup before the original is touched; a name collision
    aborts, never overwrites.
W11 Untouched lines survive byte-for-byte: newline="" both ways, plain
    utf-8 never utf-8-sig, no final newline added.
W12 Skipped is not failed: every ambiguous candidate is reported with
    the failing condition named. Never guessed.

Detection is vault_lint's own detect(lines) — one source of truth for
what "broken" means, two policies for reading (lint replaces, repair
strict-decodes). Proposals are dry-verified IN MEMORY before being
offered: the full rejoin is applied to a copy and any NEW finding
(compared by identity — (check, D-number), never by line, because every
repair shifts every later line) refuses the candidate before any write.
Post-apply verification is therefore a second net, not the only one.
A failed post-apply verification reports loudly and prints the backup
path; restoring is a single copy. It never auto-reverts — an automatic
revert is another unapproved write.
"""


# ─────────────────────────────── the CLI ───────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(
        prog="vault_repair.py",
        description="STATE.md split-row repair: propose -> diff -> "
                    "approve -> apply. Dry-run by default; nothing is "
                    "written without --apply and an interactive y.",
        epilog="exit codes: 0 nothing to repair / 1 repairs proposed or "
               "applied / 2 tool error or abort")
    parser.add_argument("path", nargs="?", help="the STATE.md file")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable dry-run (refused with "
                             "--apply: a JSON apply would be a write "
                             "without interactive approval)")
    parser.add_argument("--apply", action="store_true",
                        help="interactive repair: [y/n/a/q] per proposal")
    parser.add_argument("--backup-dir", metavar="DIR",
                        help="write the backup here instead of the "
                             "target's directory (must exist)")
    parser.add_argument("--explain", action="store_true",
                        help="the walls and the verified failures "
                             "behind them")
    return parser


def main(argv=None):
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_ERROR

    try:
        if args.explain:
            print(render_explain())
            return EXIT_NOTHING
        if not args.path:
            raise RepairError("no file given — usage: vault_repair.py "
                              "STATE.md [--apply]")
        if args.json and args.apply:
            raise RepairError(
                "--json with --apply is refused (W3): there is no "
                "terminal to prompt on, so a JSON apply would be a "
                "write without interactive approval. There is no --yes "
                "and no --force. Nothing was written.")
        if args.backup_dir and not os.path.isdir(args.backup_dir):
            raise RepairError("--backup-dir does not exist: %s"
                              % args.backup_dir)

        # SECTION 1: fresh scan, never stale — live detection at
        # execution time, own strict read.
        content = read_strict(args.path)
        fingerprint = file_fingerprint(args.path)
        lines = split_lines_keepends(content)
        det = vl.detect(lines)
        broken_total = sum(1 for f in det["findings"]
                           if f["check"] == "broken")
        proposals, skipped = build_candidates(lines, det)

        report = {
            "file": args.path,
            "mode": "apply" if args.apply else "dry-run",
            "broken_total": broken_total,
            "proposals": proposals,
            "skipped": skipped,
        }

        if not args.apply:
            report["verdict"] = ("%d repair%s proposed"
                                 % (len(proposals),
                                    "" if len(proposals) == 1 else "s")
                                 if proposals else "nothing to repair")
            code = EXIT_REPAIRS if proposals else EXIT_NOTHING
            report["exit_code"] = code
            if args.json:
                slim = dict(report)
                print(json.dumps(slim, indent=2, sort_keys=True))
            else:
                print(render_report(report))
            return code

        # ── apply mode ──
        if not proposals:
            report["verdict"] = "nothing to repair"
            report["applied"] = []
            report["declined"] = []
            report["exit_code"] = EXIT_NOTHING
            print(render_report(report))
            return EXIT_NOTHING

        approved, declined = collect_approvals(proposals, render_candidate)
        report["declined"] = declined
        report["applied"] = approved

        if not approved:
            report["verdict"] = ("0 of %d applied — nothing written"
                                 % len(proposals))
            report["exit_code"] = EXIT_REPAIRS
            print(render_report(report))
            return EXIT_REPAIRS

        # APPLY — exact order, no step skipped.
        # 1. W8 hash lock: re-verify in the SAME code path as the write.
        now = file_fingerprint(args.path)
        if now != fingerprint:
            raise RepairError(
                "file changed between scan and write (sha/size/mtime "
                "mismatch) — aborting, nothing written. Re-run to scan "
                "the current content.")
        # 2-3. descending sort lives in apply_to_lines (W7).
        new_lines = apply_to_lines(lines, approved)
        new_content = "".join(new_lines)
        # 4-5. verified backup before the original is touched (W10).
        backup_dir = args.backup_dir or os.path.dirname(
            os.path.abspath(args.path))
        report["backup"] = write_backup(args.path, content, backup_dir)
        # 6-9. atomic replace (W9, one write).
        atomic_write(args.path, new_content)
        # 10. re-read, re-detect, delta by identity.
        post_content = read_strict(args.path)
        post = vl.detect(split_lines_keepends(post_content))
        post_broken = sum(1 for f in post["findings"]
                          if f["check"] == "broken")
        fresh = _identity(post["findings"]) - _identity(det["findings"])
        expected = broken_total - len(approved)
        if fresh or post_broken != expected:
            report["verification"] = (
                "VERIFICATION FAILED: %s. The backup is intact at %s — "
                "restoring it is a single copy command (cp %s %s). Not "
                "auto-reverting: an automatic revert is another "
                "unapproved write."
                % ("new finding(s): %s" % ", ".join(
                       sorted("%s %s" % p for p in fresh))
                   if fresh else
                   "broken count is %d, expected %d"
                   % (post_broken, expected),
                   report["backup"], report["backup"], args.path))
            report["verdict"] = "applied %d of %d — VERIFY FAILED" % (
                len(approved), len(proposals))
            report["exit_code"] = EXIT_ERROR
            print(render_report(report))
            return EXIT_ERROR
        report["verification"] = (
            "verified: broken count %d -> %d (dropped by exactly the "
            "applied count), 0 new findings by identity"
            % (broken_total, post_broken))
        report["verdict"] = "applied %d of %d proposal%s" % (
            len(approved), len(proposals),
            "" if len(proposals) == 1 else "s")
        report["exit_code"] = EXIT_REPAIRS
        print(render_report(report))
        return EXIT_REPAIRS

    except RepairError as exc:
        if getattr(args, "json", False):
            print(json.dumps({"verdict": "ERROR", "exit_code": EXIT_ERROR,
                              "error": str(exc)}, indent=2,
                             sort_keys=True))
        else:
            sys.stderr.write("ERROR: %s\n" % exc)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
