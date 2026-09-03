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

# Column 1: one or more backtick-quoted paths, relative (no leading
# slash), no backslashes, non-empty between the backticks. A path may
# name a FOLDER (trailing "/") — the Bootleg Parts sections do.
ASSET_CELL_PATTERN = re.compile(r"^`([^`\\]+)`$")

# COMPOUND ASSET CELLS (Sonnet cert D-430, built from the real
# 14-row block, not one example). The live convention is a primary
# file plus related derivatives:
#     `path`
#     `path` + `path2` + `path3`
#     `path` (+ `recolor.png` recolor)
#     `path` (+ light/dark variants)
#     `Bootleg Parts/frames/` (10 frames)
#     `path` (+3 style variants, +AI/EPS/SVG/JPG formats)
# Grammar: PATH ("+" PATH)* [ "(" annotation ")" ]. The annotation is
# PROSE — it may mention paths (a source file, an unused derivative)
# and may itself contain parentheses inside a backticked path, which
# is why the cell is parsed structurally instead of by one regex.
ASSET_PATH_JOIN = "+"

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


def parse_asset_cell(cell):
    """Split an Asset cell into (paths, annotation, error).

    paths     the row's DECLARED assets: the primary plus any
              "+"-joined siblings. Paths named inside the annotation
              are prose references (a source file, an unused
              derivative) and are deliberately NOT included.
    annotation the trailing "(...)" note, or None.
    error     None when the cell is well-formed; otherwise why it is
              not, for L3 to report.

    Pure. Backtick spans are read literally, so a path containing
    parentheses — `Ten Minutes Late (5-variant play)/art/x.png` — is
    one path, not a path plus an annotation.
    """
    text = cell.strip()
    paths = []
    index = 0
    length = len(text)
    while True:
        while index < length and text[index].isspace():
            index += 1
        if index >= length or text[index] != "`":
            return (paths, None,
                    "expected a backtick-quoted path%s"
                    % (" after a '%s'" % ASSET_PATH_JOIN
                       if paths else ""))
        close = text.find("`", index + 1)
        if close == -1:
            return paths, None, "unclosed backtick around a path"
        paths.append(text[index + 1:close])
        index = close + 1
        while index < length and text[index].isspace():
            index += 1
        if index < length and text[index] == ASSET_PATH_JOIN:
            index += 1
            continue
        break
    annotation = text[index:].strip()
    if annotation and not (annotation.startswith("(")
                           and annotation.endswith(")")):
        return (paths, None,
                "trailing text is not a parenthesised annotation: %r"
                % annotation[:60])
    return paths, annotation or None, None


def asset_cell_findings(cell):
    """L3 for one Asset cell. Empty list means valid."""
    paths, _annotation, error = parse_asset_cell(cell)
    if error:
        return ["L3: Asset cell must be a backtick-quoted relative "
                "path, optionally '%s'-joined with more and followed "
                "by a (...) note — %s (got %r)"
                % (ASSET_PATH_JOIN, error, cell[:80])]
    findings = []
    for path in paths:
        if not path.strip():
            findings.append("L3: empty path in the Asset cell")
        elif not ASSET_CELL_PATTERN.match("`%s`" % path):
            findings.append("L3: %r is not a usable path (no "
                            "backslashes, no nested backticks)"
                            % path[:60])
        elif path.startswith("/"):
            findings.append("L3: Asset path must be relative to "
                            "'Merch/Design Assets/', not absolute "
                            "(%r)" % path[:60])
    return findings


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
    findings.extend(asset_cell_findings(cells[0]))
    for number, cell in enumerate(cells, start=1):
        if not cell:
            findings.append("L4: column %d is empty — every cell "
                            "carries a value" % number)
    return findings


def asset_path(line):
    """The row's PRIMARY asset path — the sidecar key (W8) — or None.
    On a compound cell this is the first path, the file the row is
    about; use asset_paths() for every declared path."""
    paths = asset_paths(line)
    return paths[0] if paths else None


def asset_paths(line):
    """Every path the row DECLARES: the primary plus its "+"-joined
    siblings. Paths mentioned inside the annotation are prose and are
    not returned. Empty list when the cell does not parse."""
    cells = split_cells(line)
    if not cells:
        return []
    paths, _annotation, error = parse_asset_cell(cells[0])
    if error:
        return []
    return [p for p in paths if p.strip()]


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
