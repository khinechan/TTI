#!/usr/bin/env python3
"""asset_index_lint.py — the ONE source of truth for a valid
ASSET_INDEX.md row (MC FLEET B3, W9; row shape filed as D-419).

ASSET_INDEX.md is a human table that stays EXACTLY 7 columns in every
section, forever (W8). This module is the importable lint that both
asset_ingest (before every append — a failing row is never written)
and B2's provenance check use. It follows vault_lint.py's discipline:
the row shape lives in module-level pattern data, the functions are
pure, and nothing here touches the filesystem.

Cells may quote pipes inside backtick pairs (the vault has form on
this — D-382); splitting respects backtick spans, pairs only, an
unpaired backtick stays a literal.

Standard library only — importable without Pillow.
"""

import re

# ═══════════════════════════════════════════════════════════════════════
# RULE DATA.
# ═══════════════════════════════════════════════════════════════════════

COLUMN_COUNT = 7

# The 7 headers, verbatim from the live file (Sonnet, D-419,
# 2026-09-02). Sections are lifecycle stages, never a schema change.
HEADER_CELLS = (
    "Asset (path under `Merch/Design Assets/`)",
    "License",
    "Style",
    "Niche tags",
    "Colors",
    "Recolor",
    "Used in",
)

# Column 1: a backtick-quoted path, relative (no leading slash), no
# backslashes, non-empty between the backticks.
ASSET_CELL_PATTERN = re.compile(r"^`([^`\\]+)`$")

# Backtick-paired spans are prose quoting, not cell structure (same
# rule vault_repair v1.1 ratified in D-382): pipes inside them do not
# split cells. Pairs only — an unpaired backtick is a literal.
BACKTICK_SPAN = re.compile(r"`[^`]*`")

SEPARATOR_CELL_PATTERN = re.compile(r"^:?-{3,}:?$")

# ═══════════════════════════════════════════════════════════════════════
# END OF RULE DATA.
# ═══════════════════════════════════════════════════════════════════════


def split_cells(line):
    """Split a table row into cells, honouring backtick spans. Returns
    a list of stripped cell strings, or None when the line is not a
    table row (must start and end with '|'). Pure."""
    stripped = line.rstrip("\r\n")
    body = stripped.strip()
    if len(body) < 2 or not body.startswith("|") or not body.endswith("|"):
        return None
    inner = body[1:-1]
    cells = []
    current = []
    in_span = False
    span_start = None
    for index, char in enumerate(inner):
        if char == "`":
            if in_span:
                in_span = False
            else:
                in_span = True
                span_start = index
            current.append(char)
        elif char == "|" and not in_span:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if in_span:
        # unpaired backtick: everything after it was literal — resplit
        # the tail on bare pipes (the span never closed, so it is not
        # a span at all)
        parts = "".join(current).split("|")
        for part in parts:
            cells.append(part.strip())
    else:
        cells.append("".join(current).strip())
    return cells


def is_separator_row(line):
    """True for |---|---|... alignment rows (any column count — the
    lint for column count applies to content rows and headers)."""
    cells = split_cells(line)
    if cells is None or not cells:
        return False
    return all(SEPARATOR_CELL_PATTERN.match(cell) for cell in cells)


def is_header_row(line):
    """True for the CANONICAL 7-column header only. Line-local, so it
    cannot see a legacy header — use find_header_lines() when you have
    the whole file."""
    cells = split_cells(line)
    return cells is not None and tuple(cells) == HEADER_CELLS


def find_header_lines(lines):
    """Indices of every table HEADER row, identified STRUCTURALLY: a
    table row immediately followed by a separator row — markdown's own
    definition of a header.

    Sonnet's cert of 00fd755 caught the reason this exists: the older
    sections of the live ASSET_INDEX carry 5-column headers ending in
    "Notes", which are not the canonical 7-column HEADER_CELLS, so an
    equality check called them data rows and every consumer treated
    them as such — the migrator padded them with "pending" cells that
    should have read Colors/Recolor/Used in. A vocabulary list of
    known header spellings would just go stale again; the position
    above the separator cannot.
    """
    headers = set()
    for index in range(len(lines) - 1):
        if split_cells(lines[index]) is None:
            continue
        if is_separator_row(lines[index]):
            continue
        if is_separator_row(lines[index + 1]):
            headers.add(index)
    return headers


def lint_row(line):
    """Lint ONE content row. Returns a list of findings, each naming
    the rule; an empty list means the row is valid. Separator and
    header rows should not be passed here (use the predicates above);
    if one is, it fails L3/L4 loudly rather than silently passing."""
    findings = []
    cells = split_cells(line)
    if cells is None:
        return ["L1: not a table row (must start and end with '|')"]
    if len(cells) != COLUMN_COUNT:
        findings.append("L2: %d columns, the table is EXACTLY %d "
                        "(W8 — no schema change to the human table)"
                        % (len(cells), COLUMN_COUNT))
        return findings
    match = ASSET_CELL_PATTERN.match(cells[0])
    if not match or not match.group(1).strip():
        findings.append("L3: Asset cell must be a backtick-quoted "
                        "relative path (got %r)" % cells[0][:80])
    elif match.group(1).startswith("/"):
        findings.append("L3: Asset path must be relative to "
                        "'Merch/Design Assets/', not absolute")
    for number, cell in enumerate(cells, start=1):
        if not cell:
            findings.append("L4: column %d is empty — every cell "
                            "carries a value" % number)
    return findings


def asset_path(line):
    """The path inside the Asset cell's backticks, or None. This is
    the sidecar key (W8)."""
    cells = split_cells(line)
    if not cells:
        return None
    match = ASSET_CELL_PATTERN.match(cells[0])
    return match.group(1) if match else None


def format_row(cells):
    """Build a row line from 7 cell strings and PROVE it passes this
    lint before returning it. Raises ValueError with the findings
    otherwise — a failing row is never handed back to be written."""
    line = "| " + " | ".join(str(cell) for cell in cells) + " |"
    findings = lint_row(line)
    if findings:
        raise ValueError("row fails its own lint: %s"
                         % "; ".join(findings))
    return line
