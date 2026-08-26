#!/usr/bin/env python3
"""vault_lint.py — read-only integrity linter for STATE.md decision logs.

WHY THIS EXISTS: a decision row was present in the file and invisible to
search because its formatting was broken. Formatting is metadata — a
correctly-worded decision with a broken row is a decision that does not
exist as far as any tool or future session is concerned. This linter
finds what grep cannot.

WHAT IT NEVER DOES: it never modifies any inspected file. Not to fix,
not to normalize, not to back up. It reports; a human decides. There is
no --fix flag and there never will be one. The only write paths in this
module are write_baseline() (explicit --write-baseline, to its own JSON
file) and append_heartbeat() (to the runlog constant, never an input).

Exit codes:
    0 = clean, or only findings below the fail threshold
    1 = findings at or above the fail threshold
    2 = tool/input error — file missing, unreadable, ROW_PATTERN matched
        nothing, bad CLI argument

Windows console encoding is handled: stdout/stderr are reconfigured to
UTF-8 (errors="replace") at startup, so the ══ banners below never raise
UnicodeEncodeError on a cp1252 console (STATE.md D-378 class). Display
only -- never touches what gets written to STATE.md/RUNLOG/JSON.

Standard library only.
"""

import argparse
import glob as _glob
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone

# ═══════════════════════════════════════════════════════════════════════
# RULES ARE DATA.
# Every pattern, threshold, and severity lives here. Detection code
# below never contains an inline pattern. Tune these to fit the real
# file without touching a line of logic.
# ═══════════════════════════════════════════════════════════════════════

# ⚠ USE \s, NEVER A LITERAL SPACE. Python's \s is Unicode-aware and
# matches \xa0 (non-breaking space) and tabs. That is precisely how this
# tool finds rows that a literal search for "| D-316 |" cannot.
# VERIFIED: a row containing '| D-316\xa0|' matches this pattern and
# does not match the literal string. Do not "simplify" this pattern —
# simplifying it deletes the tool's reason to exist.
# (Note: zero-width characters are NOT matched by \s, so an ID cell
# containing one fails this pattern and is caught by the malformed
# check instead — same alarm, higher precedence.)
#
# Group 2 (optional) admits the vault's two historical sub-decision-ID
# conventions — found D-359 (2026-08-19), taught here per D-376
# (2026-08-23, court ruling "B — teach vault_lint the old formats"):
#   - a single lowercase letter directly after the digits: "D-102b"
#   - the word "addendum" after a run of \s (still Unicode-aware, so
#     \xa0 works here too): "D-144 addendum"
# Both shapes land in the SAME group so digits (group 1) stays pure
# numeric — int(group(1)) must never see a letter. A row matched via
# group 2 is flagged is_addendum=True downstream and excluded from the
# padding and order checks: an addendum legitimately reuses its
# parent's number out of sequence, and reuses it on purpose — that is
# not a defect. Anything that doesn't cleanly fit one of these two
# exact shapes ("D-102bb", "D-144addendum" with no space) is
# deliberately left UNMATCHED so it still falls through to the
# malformed check — this pattern stays strict, it just now recognizes
# two more strict shapes instead of going loose in general.
ROW_PATTERN = r"^\|\s*D-(\d+)(\s+addendum|[a-z])?\s*\|"

# A laxer prefix used only to salvage a D-number from a damaged row for
# reporting (e.g. "| D-316" with no closing pipe). Never used to admit a
# row into the index as healthy.
ROW_START_LAX = r"^\|\s*D-(\d+)"

# A line whose first cell contains something D-shaped: the trigger for
# the broken/malformed classifiers when ROW_PATTERN has already refused.
MALFORMED_HINT = r"^\s*\|[^|]*D\s*-"

# Loose extractor for naming the intended ID in a malformed-row report.
MALFORMED_ID_HINT = r"D\s*-\s*([0-9A-Za-z]+)"

PROSE_MENTION = r"\bD-(\d+)\b"
FENCE_MARKERS = ("```", "~~~")
HTML_COMMENT_OPEN = "<!--"
HTML_COMMENT_CLOSE = "-->"
HEADING_PREFIX = "#"

DOMINANT_MAJORITY = 0.80

# Rendered identically to a normal space (or to nothing) yet fatal to
# every literal search. Defined with escape sequences only — never
# pasted literal glyphs. NBSP, zero-width space, ZWNJ, ZWJ, BOM, tab.
INVISIBLE_CHARS = "\xa0\u200b\u200c\u200d\ufeff\t"

NEGATION_CONTEXT = ("no D-", "not D-", "never D-", "there is no")
RANGE_PATTERN = r"D-(\d+)\s*(?:through|to|–|—|-)\s*D-(\d+)"
RANGE_EXPANSION_LIMIT = 10000   # refuse to expand absurd ranges

SEVERITIES = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}

# One problem, one finding. A D-number reported by a check earlier in
# this list is suppressed from every later one.
PRECEDENCE = [
    "malformed", "broken", "invisible", "dupes", "ghosts",
    "columns", "stub", "padding", "gaps", "order",
]

CHECKS = {
    "malformed": {
        "severity": "CRITICAL",
        "title": "looks like a row, number won't parse",
        "explain": "A line starting with '|' containing something D-shaped "
                   "that ROW_PATTERN rejects ('| D- |', '| D-3l6 |', "
                   "' | D-107 |'). These rows are invisible to the linter "
                   "itself, which makes them the most dangerous class. "
                   "Reported raw, never repaired.",
        "motivation": "Preventive. A row the linter cannot parse is a row "
                      "no tool can see — the same failure mode as D-316, "
                      "one step earlier.",
    },
    "broken": {
        "severity": "CRITICAL",
        "title": "row split across physical lines",
        "explain": "A table row whose content continues onto the next "
                   "line, or that never closes its pipes. rstrip() runs "
                   "before every end-of-line test so a healthy row with "
                   "trailing whitespace is never flagged.",
        "motivation": "D-350: a row split across multiple lines. Also "
                      "D-316: decision content present in the file but its "
                      "table row format broken/absent, invisible to "
                      "format-based search (root mechanism unconfirmed).",
    },
    "invisible": {
        "severity": "CRITICAL",
        "title": "invisible characters in the ID cell",
        "explain": "Any character from INVISIBLE_CHARS inside the "
                   "'| D-nnn |' cell. These render identically to a normal "
                   "space and defeat every literal search. The finding "
                   "names the codepoint and shows the repr — a finding a "
                   "human cannot see is a finding they cannot fix.",
        "motivation": "PREVENTIVE — a plausible cause class for "
                      "format-invisible rows (an NBSP renders like a space "
                      "and defeats a literal '| D-316 |' search), not "
                      "confirmed history of any past incident.",
    },
    "dupes": {
        "severity": "CRITICAL",
        "title": "duplicate D-numbers",
        "explain": "The same ID on two or more rows. Identical content is "
                   "a copy-paste artifact; differing content is two "
                   "decisions fighting for one ID, and any lookup silently "
                   "loses one of them. The finding says which kind.",
        "motivation": "Preventive. An append-only log accumulates "
                      "copy-paste; a conflicting dupe is silent data loss.",
    },
    "ghosts": {
        "severity": "WARNING",
        "title": "referenced but no row",
        "explain": "A D-number in prose with no row in the index. The "
                   "index is this file PLUS every --also-scan file — a "
                   "decision correctly moved to an archive is NOT a ghost. "
                   "Negations ('there is no D-999') and ranges ('D-300 "
                   "through D-310', which means eleven numbers) are "
                   "handled; fenced and commented text is excluded.",
        "motivation": "STATE.md was split into CURRENT plus append-only "
                      "archives. Without --also-scan this check would "
                      "report the split working correctly as hundreds of "
                      "errors, and the tool would be red forever.",
    },
    "columns": {
        "severity": "WARNING",
        "title": "column count anomaly",
        "explain": "Rows whose pipe count differs from the dominant count, "
                   "learned from the data. If the top shape holds under "
                   "{pct:.0%} of rows the check escalates to CRITICAL and "
                   "flags nothing row-by-row: a self-learned baseline can "
                   "learn the disease, and if most rows are broken the "
                   "mode IS the corruption.".format(pct=DOMINANT_MAJORITY),
        "motivation": "Preventive. A hand-edited table drifts one cell at "
                      "a time.",
    },
    "stub": {
        "severity": "WARNING",
        "title": "row exists, content empty",
        "explain": "A row whose non-ID cells are all empty. It passes "
                   "every other check — a decision that was filed and "
                   "never written.",
        "motivation": "The exact 'ruled but not wired' failure this "
                      "system keeps hitting.",
    },
    "padding": {
        "severity": "WARNING",
        "title": "inconsistent zero-padding",
        "explain": "Both 'D-050' and 'D-50' present. Treated as DISTINCT "
                   "numbers — silently merging two IDs would hide a "
                   "duplicate — with a warning that the file mixes "
                   "conventions.",
        "motivation": "Fail closed: two spellings of one number is a "
                      "lookup that only works sometimes.",
    },
    "gaps": {
        "severity": "INFO",
        "title": "missing numbers in sequence",
        "explain": "Missing IDs between the min and max in this file, "
                   "reported as ranges ('D-100..D-299 (200 missing)'), "
                   "never one finding per number. Gaps are frequently "
                   "legitimate and never affect the exit code on their own.",
        "motivation": "Informational: a gap can be an archive split, a "
                      "renumber, or a deletion — a human decides which.",
    },
    "order": {
        "severity": "INFO",
        "title": "rows out of sequence",
        "explain": "A row whose number is below the maximum already seen "
                   "suggests an insertion error. Informational only.",
        "motivation": "Preventive. Append-only logs should ascend; an "
                      "out-of-order row is usually a paste into the wrong "
                      "spot.",
    },
    "encoding": {
        "severity": "WARNING",
        "title": "bytes that are not valid UTF-8",
        "explain": "The file is read with errors='replace'; every line "
                   "where replacement occurred is reported. Never a crash "
                   "— a decode error is the likeliest crash in a "
                   "hand-edited file full of em-dashes and emoji.",
        "motivation": "'Never crashes' is a success criterion.",
    },
}

DEFAULT_FAIL_ON = "WARNING"

# The heartbeat runlog. A constant, structurally distinct from any input
# path; append_heartbeat refuses to touch a path that resolves to an
# inspected file, and skips with a notice if this file does not exist.
RUNLOG_PATH = "runlog.txt"
HEARTBEAT_STAGE = "vault_lint"

SAMPLE_PIPE_LINES = 3      # shown in the pattern-mismatch report
CONTINUATION_PREVIEW = 60  # chars of a continuation line shown in a finding

# ═══════════════════════════════════════════════════════════════════════
# END OF RULE DATA.
# ═══════════════════════════════════════════════════════════════════════

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2

_ROW_RE = re.compile(ROW_PATTERN)
_ROW_LAX_RE = re.compile(ROW_START_LAX)
_MALFORMED_RE = re.compile(MALFORMED_HINT)
_MALFORMED_ID_RE = re.compile(MALFORMED_ID_HINT)
_MENTION_RE = re.compile(PROSE_MENTION)
_RANGE_RE = re.compile(RANGE_PATTERN)


class ToolError(Exception):
    """The tool could not do its job. Exit 2 — distinct from findings."""


def char_name(ch):
    try:
        return "U+%04X %s" % (ord(ch), unicodedata.name(ch))
    except ValueError:
        return "U+%04X (control character)" % ord(ch)


# ─────────────────────────── the streaming scan ────────────────────────

def scan_file(path, rows_only=False):
    """Thin I/O wrapper around scan_lines(). Opens with errors="replace"
    — this tool is read-only and must never crash on a hand-edited file
    — and delegates every classification decision to scan_lines().
    Callers with a different read policy (vault_repair strict-decodes)
    do their own read and call scan_lines()/detect() directly: one
    source of truth for DETECTION, two policies for READING."""
    if not os.path.isfile(path):
        raise ToolError("file not found: %s" % path)
    try:
        size = os.path.getsize(path)
        handle = open(path, "r", encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ToolError("cannot read %s: %s" % (path, exc))
    with handle:
        scan = scan_lines(handle, rows_only=rows_only)
    scan["path"] = path
    scan["size"] = size
    return scan


def scan_lines(lines, rows_only=False):
    """One pass, line by line — never slurps. PURE: no I/O; `lines` is
    any iterable of lines in the shape a text-handle iteration yields
    (terminators attached; rstrip happens here). Classifies every line
    as CODE_FENCE, HTML_COMMENT, TABLE_ROW, or PROSE; fenced and
    commented lines are excluded from row parsing and prose scanning (a
    pasted example table must never become a phantom decision).

    Returns a dict of everything the checks need. rows_only=True is the
    light mode used for --also-scan archives (index building only).
    """
    scan = {
        "lines": 0,
        "rows": [], "broken": [], "malformed": [],
        "mentions": [], "ranges": [], "decode_lines": [],
        "excluded_lines": 0, "fences": 0, "comments": 0,
        "pipe_samples": [],
    }

    in_fence = False
    in_comment = False
    pending = None   # last row/broken record awaiting next-line info

    def attach_next(lineno, raw, stripped, excluded, is_row):
        nonlocal pending
        if pending is not None:
            pending["next"] = {
                "line": lineno,
                "blank": stripped == "",
                "heading": stripped.startswith(HEADING_PREFIX),
                "starts_pipe": stripped.startswith("|"),
                "is_row": is_row,
                "excluded": excluded,
                "preview": raw.strip()[:CONTINUATION_PREVIEW],
            }
            pending = None

    for lineno, line in enumerate(lines, 1):
        scan["lines"] = lineno
        raw = line.rstrip("\r\n")     # explicit: CRLF-safe before any test
        rst = raw.rstrip()            # rstrip() before every end-of-line test
        stripped = raw.strip()

        if "\ufffd" in raw and not rows_only:
            scan["decode_lines"].append(lineno)

        # ── structure pre-pass: fences and comments exclude a line
        # from every check. Counted, never silently skipped.
        if in_fence:
            scan["excluded_lines"] += 1
            if stripped.startswith(FENCE_MARKERS):
                in_fence = False
            attach_next(lineno, raw, stripped, True, False)
            continue
        if stripped.startswith(FENCE_MARKERS):
            in_fence = True
            scan["fences"] += 1
            scan["excluded_lines"] += 1
            attach_next(lineno, raw, stripped, True, False)
            continue
        if in_comment:
            scan["excluded_lines"] += 1
            if HTML_COMMENT_CLOSE in raw:
                in_comment = False
            attach_next(lineno, raw, stripped, True, False)
            continue
        if stripped.startswith(HTML_COMMENT_OPEN):
            scan["comments"] += 1
            scan["excluded_lines"] += 1
            if HTML_COMMENT_CLOSE not in stripped[len(HTML_COMMENT_OPEN):]:
                in_comment = True
            attach_next(lineno, raw, stripped, True, False)
            continue

        if stripped.startswith("|") and len(scan["pipe_samples"]) < SAMPLE_PIPE_LINES:
            scan["pipe_samples"].append((lineno, raw[:80]))

        # ── row classification
        match = _ROW_RE.match(rst)
        if match:
            attach_next(lineno, raw, stripped, False, True)
            base_digits = match.group(1)
            suffix = match.group(2) or ""
            digits = base_digits + suffix
            parts = rst.split("|")
            cells = parts[1:-1] if rst.endswith("|") else parts[1:]
            record = {
                "line": lineno, "raw": rst, "digits": digits,
                "num": int(base_digits), "pipes": rst.count("|"),
                "cells": cells, "id_cell": parts[1] if len(parts) > 1 else "",
                "closed": rst.endswith("|"), "next": None,
                "is_addendum": bool(suffix),
            }
            scan["rows"].append(record)
            pending = record
            continue

        if not rows_only and _MALFORMED_RE.match(rst):
            attach_next(lineno, raw, stripped, False, False)
            lax = _ROW_LAX_RE.match(rst)
            if lax and not rst.endswith("|"):
                record = {"line": lineno, "raw": rst,
                          "digits": lax.group(1), "num": int(lax.group(1)),
                          "next": None}
                scan["broken"].append(record)
                pending = record
            else:
                hint = _MALFORMED_ID_RE.search(rst)
                scan["malformed"].append({
                    "line": lineno, "raw": rst,
                    "hint": hint.group(0) if hint else None,
                    "num": (int(hint.group(1))
                            if hint and hint.group(1).isdigit() else None),
                })
            continue

        attach_next(lineno, raw, stripped, False, False)

        # ── prose scan (anything not rowish, headings included)
        if rows_only or stripped.startswith("|"):
            continue
        spans = []
        for rmatch in _RANGE_RE.finditer(raw):
            spans.append((rmatch.start(), rmatch.end()))
            lo, hi = int(rmatch.group(1)), int(rmatch.group(2))
            if lo <= hi and hi - lo <= RANGE_EXPANSION_LIMIT:
                scan["ranges"].append({"line": lineno, "lo": lo, "hi": hi})
        for mmatch in _MENTION_RE.finditer(raw):
            if any(lo <= mmatch.start() < hi for lo, hi in spans):
                continue   # endpoint of a range — the expansion covers it
            if _is_negated(raw, mmatch.start()):
                continue
            scan["mentions"].append({
                "line": lineno, "digits": mmatch.group(1),
                "num": int(mmatch.group(1)),
            })

    return scan


def _is_negated(line, mention_start):
    """True if a NEGATION_CONTEXT phrase governs this mention.
    'there is no D-999' is a statement of absence, not a reference."""
    preceding = line[:mention_start].lower()
    for phrase in NEGATION_CONTEXT:
        phrase = phrase.lower()
        if phrase.endswith("d-"):
            if preceding.endswith(phrase[:-2]):
                return True
        elif phrase in preceding[-40:]:
            return True
    return False


# ───────────────────────────── the checks ──────────────────────────────

def _is_continuation(nxt, allow_pipe):
    if nxt is None or nxt["excluded"] or nxt["blank"] or nxt["heading"] or nxt["is_row"]:
        return False
    if not allow_pipe and nxt["starts_pipe"]:
        return False
    return True


def run_checks(scan, index_nums, selected):
    """Pure function over scan data. Returns unsorted findings plus the
    column-shape summary. Never touches the filesystem."""
    findings = []

    def add(check, num, line, lines_label, message):
        findings.append({
            "check": check,
            "severity": CHECKS[check]["severity"],
            "dnum": num,
            "dlabel": ("D-%s" % num) if num is not None else None,
            "line": line,
            "lines": lines_label,
            "message": message,
        })

    rows = scan["rows"]

    # dominant column shape — learned from the data, confidence reported
    shape = Counter(r["pipes"] for r in rows)
    dominant, dom_n, confident = None, 0, False
    if shape:
        dominant, dom_n = sorted(shape.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        confident = (dom_n / len(rows)) >= DOMINANT_MAJORITY
    shape_info = {
        "dominant_pipes": dominant,
        "dominant_fraction": (dom_n / len(rows)) if rows else 0.0,
        "distribution": dict(sorted(shape.items())),
        "confident": confident,
    }

    if "encoding" in selected:
        for lineno in scan["decode_lines"]:
            add("encoding", None, lineno, "L%d" % lineno,
                "bytes on this line are not valid UTF-8 (shown as U+FFFD "
                "replacement); the original bytes need a human eye")

    if "malformed" in selected:
        for rec in scan["malformed"]:
            add("malformed", rec["num"], rec["line"], "L%d" % rec["line"],
                "looks like a row but ROW_PATTERN rejects it%s — raw: %r"
                % ((" (intended %s?)" % rec["hint"]) if rec["hint"] else "",
                   rec["raw"][:100]))

    if "broken" in selected:
        for rec in scan["broken"]:
            nxt = rec["next"]
            cont = _is_continuation(nxt, allow_pipe=True)
            label = ("L%d-%d" % (rec["line"], nxt["line"])) if cont else "L%d" % rec["line"]
            extra = (("; continues: %r" % nxt["preview"]) if cont else "")
            add("broken", rec["num"], rec["line"], label,
                "row never closes its ID cell — invisible to a literal "
                "'| D-%s |' search%s" % (rec["digits"], extra))
        for rec in rows:
            if not rec["closed"]:
                nxt = rec["next"]
                cont = _is_continuation(nxt, allow_pipe=True)
                label = ("L%d-%d" % (rec["line"], nxt["line"])) if cont else "L%d" % rec["line"]
                add("broken", rec["num"], rec["line"], label,
                    "row does not end with '|' — content continues onto "
                    "the next line%s"
                    % ((": %r" % nxt["preview"]) if cont else ""))
            elif (confident and rec["pipes"] < dominant
                  and _is_continuation(rec["next"], allow_pipe=False)):
                nxt = rec["next"]
                add("broken", rec["num"], rec["line"],
                    "L%d-%d" % (rec["line"], nxt["line"]),
                    "row has %d pipes (dominant %d) and the next line "
                    "reads as its continuation: %r"
                    % (rec["pipes"], dominant, nxt["preview"]))

    if "invisible" in selected:
        for rec in rows:
            bad = [(i, ch) for i, ch in enumerate(rec["raw"])
                   if ch in INVISIBLE_CHARS and i <= rec["raw"].index("|", 1)]
            if bad:
                detail = "; ".join("%s at column %d" % (char_name(ch), i + 1)
                                   for i, ch in bad)
                id_cell = rec["raw"][:rec["raw"].index("|", 1) + 1]
                add("invisible", rec["num"], rec["line"], "L%d" % rec["line"],
                    "%s in the ID cell %r — renders as a space, fatal to "
                    "every literal search" % (detail, id_cell))

    if "dupes" in selected:
        by_digits = {}
        for rec in rows:
            by_digits.setdefault(rec["digits"], []).append(rec)
        for digits, group in by_digits.items():
            if len(group) < 2:
                continue
            lines_label = ", ".join("L%d" % r["line"] for r in group)
            contents = {r["raw"].strip() for r in group}
            kind = ("identical content — copy-paste artifact"
                    if len(contents) == 1 else
                    "CONFLICTING content — two decisions fighting for one "
                    "ID; any lookup silently loses one")
            add("dupes", group[0]["num"], group[0]["line"], lines_label,
                "D-%s appears on %d rows (%s): %s"
                % (digits, len(group), lines_label, kind))

    if "ghosts" in selected:
        referenced = {}   # num -> first line
        for m in scan["mentions"]:
            referenced.setdefault(m["num"], m["line"])
        for r in scan["ranges"]:
            for num in range(r["lo"], r["hi"] + 1):
                referenced.setdefault(num, r["line"])
        for num in sorted(referenced):
            if num not in index_nums:
                line = referenced[num]
                add("ghosts", num, line, "L%d" % line,
                    "referenced here but no row exists in this file or "
                    "any --also-scan file")

    if "columns" in selected and rows:
        if not confident:
            dist = ", ".join("%d pipes ×%d" % (p, n)
                             for p, n in sorted(shape.items()))
            f = {
                "check": "columns", "severity": "CRITICAL", "dnum": None,
                "dlabel": None, "line": rows[0]["line"], "lines": "--",
                "message": "no dominant column shape (top shape only %d%% "
                           "of rows, need %d%%) — the file may be "
                           "substantially malformed, or ROW_PATTERN is "
                           "wrong. Distribution: %s. Flagging nothing "
                           "row-by-row: a baseline learned from corrupted "
                           "data would flag the healthy rows."
                           % (round(shape_info["dominant_fraction"] * 100),
                              round(DOMINANT_MAJORITY * 100), dist),
            }
            findings.append(f)
        else:
            for rec in rows:
                if rec["pipes"] != dominant and rec["closed"]:
                    add("columns", rec["num"], rec["line"], "L%d" % rec["line"],
                        "%d pipes where the dominant shape is %d "
                        "(%d%% of rows)"
                        % (rec["pipes"], dominant,
                           round(shape_info["dominant_fraction"] * 100)))

    if "stub" in selected:
        for rec in rows:
            body = rec["cells"][1:]
            if rec["closed"] and body and all(c.strip() == "" for c in body):
                add("stub", rec["num"], rec["line"], "L%d" % rec["line"],
                    "row is filed but every non-ID cell is empty — a "
                    "decision that was ruled and never written")

    if "padding" in selected:
        forms = {}
        for rec in rows:
            if rec["is_addendum"]:
                continue   # a "D-144 addendum"/"D-102b" row legitimately
                           # reuses its parent's number — not a padding
                           # collision, so it never enters this comparison
            forms.setdefault(rec["num"], set()).add(rec["digits"])
        for num in sorted(forms):
            if len(forms[num]) > 1:
                variants = ", ".join("D-%s" % d for d in sorted(forms[num]))
                lines_label = ", ".join(
                    "L%d" % r["line"] for r in rows if r["num"] == num)
                add("padding", num, min(r["line"] for r in rows
                                        if r["num"] == num), lines_label,
                    "both %s present — treated as DISTINCT IDs (never "
                    "silently merged); the file mixes padding conventions"
                    % variants)

    if "gaps" in selected and rows:
        # A broken or malformed row's number is damaged, not missing —
        # it must not appear inside a gap range.
        damaged = ({r["num"] for r in scan["broken"]}
                   | {m["num"] for m in scan["malformed"]
                      if m["num"] is not None})
        present = sorted({r["num"] for r in rows} | damaged)
        lo, hi = present[0], present[-1]
        run_start = None
        gaps = []
        present_set = set(present)
        for num in range(lo, hi + 1):
            if num not in present_set:
                if run_start is None:
                    run_start = num
            elif run_start is not None:
                gaps.append((run_start, num - 1))
                run_start = None
        for start, end in gaps:   # always ranges, never one line per number
            count = end - start + 1
            label = ("D-%d..D-%d (%d missing)" % (start, end, count)
                     if count > 1 else "D-%d (1 missing)" % start)
            findings.append({
                "check": "gaps", "severity": "INFO", "dnum": None,
                "dlabel": "--", "line": None, "lines": "--",
                "message": label + " — gaps are frequently legitimate "
                           "(archive splits, renumbers); informational only",
            })

    if "order" in selected:
        max_seen = None
        for rec in rows:
            if rec["is_addendum"]:
                continue   # addenda don't participate in the ascending
                           # walk and never advance max_seen — they're
                           # expected to sit out of sequence, by design
            if max_seen is not None and rec["num"] < max_seen:
                add("order", rec["num"], rec["line"], "L%d" % rec["line"],
                    "D-%s appears after D-%d — out of ascending order; "
                    "possible insertion error" % (rec["digits"], max_seen))
            else:
                max_seen = rec["num"]

    return findings, shape_info


def apply_precedence(findings):
    """One problem, one finding. A D-number already reported by a
    higher-precedence check is suppressed from every lower one."""
    order = {name: i for i, name in enumerate(PRECEDENCE)}
    reported = {}
    kept = []
    for f in sorted(findings, key=lambda f: order.get(f["check"], -1)):
        num = f["dnum"]
        if num is not None:
            prior = reported.get(num)
            mine = order.get(f["check"], -1)
            if prior is not None and prior < mine:
                continue
            reported.setdefault(num, mine)
        kept.append(f)
    return kept


def sort_findings(findings):
    """Deterministic: (severity, line, check, D-number) — always."""
    return sorted(findings, key=lambda f: (
        SEVERITIES[f["severity"]],
        f["line"] if f["line"] is not None else 10 ** 9,
        f["check"],
        f["dnum"] if f["dnum"] is not None else -1,
    ))


def detect(lines):
    """Pure detection over in-memory lines: scan + every check +
    precedence + deterministic sort, no I/O anywhere. This is the API
    repair tooling calls after doing its OWN strict read — one source
    of truth for what 'broken' (and every other class) means, two
    policies for reading (this tool's CLI reads with errors="replace";
    vault_repair must strict-decode or abort)."""
    scan = scan_lines(lines)
    index_nums = {r["num"] for r in scan["rows"]}
    findings, shape = run_checks(scan, index_nums, set(CHECKS))
    return {"scan": scan, "shape": shape,
            "findings": sort_findings(apply_precedence(findings))}


# ───────────────────── baseline ratchet (adoption) ─────────────────────

def finding_key(f):
    tail = f["dlabel"] or ("L%s" % f["line"] if f["line"] else f["message"][:40])
    return "%s|%s|%s" % (f["check"], f["severity"], tail)


def load_baseline(path):
    if not os.path.isfile(path):
        raise ToolError("baseline file not found: %s" % path)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return set(data["keys"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ToolError("baseline %s is unreadable: %s" % (path, exc))


def write_baseline(path, findings, inspected_paths):
    """The ONLY function that writes the baseline, and it never writes to
    an inspected file or to any markdown file. Explicit --write-baseline
    only."""
    real = os.path.realpath(path)
    for inspected in inspected_paths:
        if real == os.path.realpath(inspected):
            raise ToolError(
                "refusing to write baseline over inspected file %s" % inspected)
    if real.lower().endswith((".md", ".markdown")):
        raise ToolError(
            "refusing to write baseline to a markdown file: %s" % path)
    payload = {"version": 1, "keys": sorted({finding_key(f) for f in findings})}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


# ───────────────────────────── heartbeat ───────────────────────────────

def append_heartbeat(result, counts, target, inspected_paths):
    """Per standing doctrine: a gate that can only fail while running
    cannot detect its own absence. Appends one line to RUNLOG_PATH — a
    constant, never an input path. Skipped with a notice if the runlog
    does not exist; refuses outright if it resolves to an inspected file.
    Returns the notice string for the report."""
    real = os.path.realpath(RUNLOG_PATH)
    for inspected in inspected_paths:
        if real == os.path.realpath(inspected):
            return ("heartbeat SKIPPED: runlog path resolves to inspected "
                    "file %s — never writing to an inspected file" % inspected)
    if not os.path.isfile(RUNLOG_PATH):
        return ("heartbeat skipped: runlog %s does not exist (create it to "
                "enable the heartbeat)" % RUNLOG_PATH)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    line = "%s | %s | %s | critical=%d warning=%d info=%d | %s\n" % (
        HEARTBEAT_STAGE, stamp, result,
        counts.get("CRITICAL", 0), counts.get("WARNING", 0),
        counts.get("INFO", 0), target)
    try:
        with open(RUNLOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(line)
        return "heartbeat: appended to %s" % RUNLOG_PATH
    except OSError as exc:
        return "heartbeat FAILED (non-fatal): %s" % exc


# ───────────────────────────── rendering ───────────────────────────────

def render_human(report):
    out = []
    s = report["summary"]
    out.append("══ VAULT LINT ══ %s (%dKB, %s lines)"
               % (s["file"], s["size_kb"], "{:,}".format(s["lines"])))
    if s["rows"]:
        out.append("rows: %d | D-%d..D-%d | dominant columns: %s"
                   % (s["rows"], s["min"], s["max"], s["dominant"]))
    else:
        out.append("rows: 0")
    out.append("excluded: %d lines in %d code fences, %d HTML comments"
               % (s["excluded_lines"], s["fences"], s["comments"]))
    if s.get("also_scanned"):
        a = s["also_scanned"]
        out.append("also-scanned: %s (%d files, %d rows)"
                   % (", ".join(a["patterns"]), a["files"], a["rows"]))
    if s.get("baseline"):
        out.append("baseline: %s (%d known findings suppressed)"
                   % (s["baseline"]["path"], s["baseline"]["suppressed"]))
    out.append("")
    for f in report["findings"]:
        out.append("%-9s %-10s %-8s %-14s %s"
                   % (f["severity"], f["check"], f["dlabel"] or "--",
                      f["lines"], f["message"]))
    if not report["findings"]:
        out.append("no findings")
    out.append("")
    c = report["counts"]
    out.append("VERDICT: %d critical, %d warning, %d info → %s (--fail-on %s)"
               % (c.get("CRITICAL", 0), c.get("WARNING", 0), c.get("INFO", 0),
                  report["verdict"], report["fail_on"].lower()))
    for note in report["notes"]:
        out.append("NOTE: %s" % note)
    return "\n".join(out)


def render_pattern_mismatch(scan):
    out = []
    out.append("══ PATTERN MISMATCH ══")
    out.append("ROW_PATTERN matched 0 rows in a %dKB file (%s lines)."
               % (max(1, scan["size"] // 1024), "{:,}".format(scan["lines"])))
    out.append("This almost certainly means the pattern does not fit this "
               "file, not that the log is empty. Certifying an unread file "
               "as healthy would be worse than any crash.")
    if scan["pipe_samples"]:
        out.append("First %d lines beginning with '|':" % len(scan["pipe_samples"]))
        for lineno, text in scan["pipe_samples"]:
            out.append("  L%-5d %s" % (lineno, text))
    else:
        out.append("No lines beginning with '|' were found at all.")
    out.append("Adjust ROW_PATTERN at the top of vault_lint.py.")
    return "\n".join(out)


def render_explain():
    out = ["══ VAULT LINT — THE CHECKS ══",
           "",
           "Institutional memory lives here so nobody deletes a check "
           "later thinking it is noise.",
           ""]
    for name in PRECEDENCE + ["encoding"]:
        spec = CHECKS[name]
        out.append("%s  %s — %s" % (spec["severity"], name, spec["title"]))
        out.append("  what: %s" % spec["explain"])
        out.append("  why:  %s" % spec["motivation"])
        out.append("")
    out.append("Precedence (one problem, one finding): %s"
               % " > ".join(PRECEDENCE))
    out.append("")
    out.append("This tool never modifies any inspected file. There is no "
               "--fix flag and there never will be one.")
    return "\n".join(out)


# ─────────────────────────────── the CLI ───────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(
        prog="vault_lint.py",
        description="Read-only integrity linter for STATE.md decision "
                    "logs. Reports; never modifies. A human decides.",
        epilog="exit codes: 0 clean / 1 findings at or above --fail-on / "
               "2 tool or input error (missing file, zero rows matched, "
               "unknown check name)",
    )
    parser.add_argument("path", nargs="?", help="the STATE.md file to lint")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable output; identical verdict")
    parser.add_argument("--only", metavar="CHECKS",
                        help="comma-separated checks to run (unknown name "
                             "= exit 2, never a silent no-op)")
    parser.add_argument("--exclude", metavar="CHECKS",
                        help="comma-separated checks to skip (unknown name "
                             "= exit 2)")
    parser.add_argument("--also-scan", action="append", default=[],
                        metavar="GLOB",
                        help="glob of archive files whose rows join the "
                             "index — a decision moved to an archive is "
                             "not a ghost")
    parser.add_argument("--fail-on", choices=["critical", "warning", "info"],
                        default=DEFAULT_FAIL_ON.lower(),
                        help="lowest severity that turns the exit code red "
                             "(default: warning)")
    parser.add_argument("--baseline", metavar="JSON",
                        help="suppress findings recorded in this baseline; "
                             "fail only on NEW ones (the adoption ratchet)")
    parser.add_argument("--write-baseline", action="store_true",
                        help="record today's findings to --baseline (the "
                             "only way the baseline is ever written; never "
                             "touches the markdown)")
    parser.add_argument("--explain", action="store_true",
                        help="print each check, what it catches, and the "
                             "incident that motivated it")
    return parser


def _parse_check_list(text, flag):
    names = [n.strip() for n in text.split(",") if n.strip()]
    unknown = [n for n in names if n not in CHECKS]
    if unknown:
        raise ToolError(
            "unknown check name%s in %s: %s — valid: %s. Refusing to run "
            "a partial gate: a typo silently running zero checks would "
            "look exactly like success."
            % ("s" if len(unknown) > 1 else "", flag, ", ".join(unknown),
               ", ".join(sorted(CHECKS))))
    if not names:
        raise ToolError("%s given with no check names" % flag)
    return names


def _emit_error(message, as_json):
    if as_json:
        print(json.dumps({"verdict": "ERROR", "exit_code": EXIT_ERROR,
                          "error": message}, indent=2, sort_keys=True))
    else:
        sys.stderr.write("ERROR: %s\n" % message)


def _ensure_utf8_console():
    """Reconfigure stdout/stderr for UTF-8 display, substituting any
    character the console codepage can't render instead of crashing.
    Windows consoles default to the system codepage (cp1252 etc.), not
    UTF-8 -- the ══ VAULT LINT ══ banner below raised UnicodeEncodeError
    there (STATE.md D-378 class -- same bug, third file: color_check.py
    and thumb_check.py first, this one unmasked once the separate
    GATE_RUN_STATE_MD path fix let vault_lint actually reach its own
    render_human() print instead of dying on file-not-found first).
    Display only -- this never touches what gets written to
    STATE.md/RUNLOG/JSON, which stay real UTF-8 bytes regardless (same
    display-vs-stored split as gate_run.py's own W14 stdout_text/
    stderr_text decode). No-op if the stream doesn't support
    .reconfigure (e.g. a test harness's captured StringIO) -- the fix
    itself must never become a new crash site.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main(argv=None):
    _ensure_utf8_console()
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
            return EXIT_CLEAN

        if not args.path:
            raise ToolError("no file given — usage: vault_lint.py STATE.md")
        if args.write_baseline and not args.baseline:
            raise ToolError("--write-baseline requires --baseline PATH")

        selected = set(CHECKS)
        if args.only:
            selected = set(_parse_check_list(args.only, "--only"))
        if args.exclude:
            selected -= set(_parse_check_list(args.exclude, "--exclude"))
        if not selected:
            raise ToolError("check selection left zero checks to run — "
                            "refusing to certify an unchecked file")

        scan = scan_file(args.path)

        # also-scan: build the archive side of the index
        archive_files, archive_rows = [], 0
        archive_nums = set()
        for pattern in args.also_scan:
            matches = sorted(_glob.glob(pattern))
            matches = [m for m in matches
                       if os.path.realpath(m) != os.path.realpath(args.path)]
            if not matches:
                raise ToolError("--also-scan pattern matched no files: %s "
                                "(a silently empty archive set would turn "
                                "every archived decision into a ghost)"
                                % pattern)
            for filename in matches:
                sub = scan_file(filename, rows_only=True)
                archive_files.append(filename)
                archive_rows += len(sub["rows"])
                archive_nums.update(r["num"] for r in sub["rows"])
        inspected = [args.path] + archive_files

        # zero rows: the tool learned nothing — never certify that.
        if not scan["rows"]:
            counts = {}
            note = append_heartbeat("error", counts, args.path, inspected)
            if args.json:
                print(json.dumps({
                    "verdict": "ERROR", "exit_code": EXIT_ERROR,
                    "error": "ROW_PATTERN matched 0 rows",
                    "size_kb": max(1, scan["size"] // 1024),
                    "lines": scan["lines"],
                    "pipe_samples": [
                        {"line": n, "text": t} for n, t in scan["pipe_samples"]],
                    "notes": [note],
                }, indent=2, sort_keys=True))
            else:
                print(render_pattern_mismatch(scan))
                print("NOTE: %s" % note)
            return EXIT_ERROR

        index_nums = {r["num"] for r in scan["rows"]} | archive_nums

        findings, shape_info = run_checks(scan, index_nums, selected)
        findings = apply_precedence(findings)
        findings = sort_findings(findings)

        # baseline ratchet: known findings suppress; new ones fail
        suppressed = 0
        baseline_note = None
        if args.baseline and not args.write_baseline:
            known = load_baseline(args.baseline)
            fresh = [f for f in findings if finding_key(f) not in known]
            suppressed = len(findings) - len(fresh)
            findings = fresh
            baseline_note = {"path": args.baseline, "suppressed": suppressed}

        counts = Counter(f["severity"] for f in findings)
        threshold = SEVERITIES[args.fail_on.upper()]
        fails = any(SEVERITIES[f["severity"]] <= threshold for f in findings)
        verdict = "FAIL" if fails else "PASS"
        exit_code = EXIT_FINDINGS if fails else EXIT_CLEAN

        notes = []
        if args.write_baseline:
            write_baseline(args.baseline, findings, inspected)
            notes.append("baseline written to %s (%d findings recorded); "
                         "future runs with --baseline fail only on NEW "
                         "findings" % (args.baseline, len(findings)))
        notes.append(append_heartbeat(verdict.lower(), counts,
                                      args.path, inspected))

        dominant_label = "--"
        if shape_info["dominant_pipes"] is not None:
            dominant_label = "%d (%d%% of rows)" % (
                max(0, shape_info["dominant_pipes"] - 1),
                round(shape_info["dominant_fraction"] * 100))

        nums = [r["num"] for r in scan["rows"]]
        report = {
            "verdict": verdict,
            "exit_code": exit_code,
            "fail_on": args.fail_on.upper(),
            "summary": {
                "file": args.path,
                "size_kb": max(1, scan["size"] // 1024),
                "lines": scan["lines"],
                "rows": len(scan["rows"]),
                "min": min(nums), "max": max(nums),
                "dominant": dominant_label,
                "shape": shape_info,
                "excluded_lines": scan["excluded_lines"],
                "fences": scan["fences"],
                "comments": scan["comments"],
                "also_scanned": ({"patterns": args.also_scan,
                                  "files": len(archive_files),
                                  "rows": archive_rows}
                                 if args.also_scan else None),
                "baseline": baseline_note,
            },
            "counts": {k: counts.get(k, 0) for k in SEVERITIES},
            "findings": findings,
            "notes": notes,
        }

        print(json.dumps(report, indent=2, sort_keys=True) if args.json
              else render_human(report))
        return exit_code

    except ToolError as exc:
        _emit_error(str(exc), args.json if hasattr(args, "json") else False)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
