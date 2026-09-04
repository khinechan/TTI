#!/usr/bin/env python3
"""play_new.py — FLEET B4. One written line in, one valid play.json
out. The input side play_forge lacks.

A SCAFFOLDER. It does not render, does not rank, and holds no design
taste of its own: wherever taste matters it cites kct-brandkit v5.2 by
name and imports the rule from the module that owns it. Fills,
outlines and garments come from color_check's data; the layout
registry, the font roster and the register predicate come from
play_forge; the schema comes from play_schema. Nothing is retyped
here, because a duplicated rule drifts.

    play_new.py --setup "CAN'T LEAVE IT NEXT DOOR."
                --punch "NOT MY CALL."
                --feeling "deadpan judgment"
                --tag   "mail carrier"
               [--garment Black|Sport Grey|both]
               [--no-art] [--overwrite] [--date YYYY-MM-DD] [--json]
    -> <out_dir>/<play_id>.play.json

DRAFT, NOT FINAL (Fable ruling, 2026-09-04): the play.json is a
hand-editable draft that passes Khai's eye before play_forge renders
it. Font pairs are rotated by rule, NOT chosen by register, so the
file and this tool's report both say so in as many words. There is no
register map in this build.

Walls (each has a test behind it):
  W0  feasibility pre-flight. kct-brandkit v5.2 MULTI-VARIANT PLAYS
      item 2 makes the three axes a length-3 code of minimum Hamming
      distance 2, so every 2-axis projection must be injective and
      N <= 2 * min(layouts, font_pairs). Counted AFTER --no-art,
      --garment and the register rule; a shortfall is stated BY NUMBER
      and exactly that many variants are built.
  W1  reads ASSET_INDEX.md, its sidecar, and fonts_dir. Writes exactly
      one file. Reuses play_forge.config.json — no second config.
  W2  art candidates: tag matched NFC -> casefold -> split on commas
      -> strip -> EXACT on a whole tag (never substring: "carrier"
      would match "air carrier"; casefold not lower, so MASSE and maße
      compare equal). Sidecar entry required, row must pass
      asset_index_lint, folder rows excluded. The hash is carried into
      the play but NOT verified here — W1 forbids reading assets_dir —
      so the receipt says "sidecar: PRESENT, NOT VERIFIED".
  W3  axes are assigned deterministically, never chosen. The register
      rule is play_forge.line_is_all_caps, IMPORTED.
  W4  element placement is looked up, never computed (1.0-0.43-0.18 is
      0.39000000000000007 and json.dumps writes every digit). A
      boot-time assertion fails exit 2 if a registry layout has no
      entry, so a new layout cannot fail only on the run that happens
      to rotate onto it.
  W5  never write a broken play: the serialized file must pass
      play_schema.load_play AND play_forge.check_structure with the
      real config before it reaches its final path.
  W6  line text verbatim, NFC-normalized once at entry. play_id is
      slug(punch)-DATE with the slug as rule data; an empty slug
      refuses.
  W7  rules as data, --json parity from one report dict, receipt on
      every terminating path including the crash floor.
  W8  fonts_dir pre-flight via play_forge.preflight_fonts.
  W9  determinism: no set may carry ordering into the play, json is
      written with fixed options and one trailing newline, no clock
      except the pinned --date.
  W12 crash floor: one top-level guard. A Python traceback exits 1,
      and 1 means "written with findings" here — without the floor a
      crash and a good write are the same integer to any caller.
  W13 atomic write: serialize to a temp file in the SAME directory,
      validate it, then os.replace on pass or os.unlink on fail.
      open(path, "w") truncates AT OPEN, so without this an
      --overwrite that failed W5 would leave 0 bytes where a good play
      used to be.

Exit codes:
    0 = written clean
    1 = written with findings (fewer variants than the target, or a
        register gap worth naming)
    2 = refused, or the crash floor

argparse handles an unknown flag and a missing required argument
itself, exiting 2 with text on stderr — so --json prints nothing on
that path, by design.

play_new's OWN imports are stdlib. Importing play_forge pulls Pillow
in transitively; that is expected, and a missing Pillow is refused as
DEP_MISSING at exit 2 rather than crashing at module scope.
"""

import argparse
import datetime
import json
import os
import sys
import unicodedata
import uuid

# W12: the fleet imports are guarded so a missing Pillow refuses by
# name instead of raising at module scope and exiting 1.
FLEET_IMPORT_ERROR = None
try:
    import asset_index_lint as ail
    import color_check as cc
    import play_forge as pf
    import play_schema
except BaseException as _err:            # noqa: BLE001 - deliberate
    FLEET_IMPORT_ERROR = "%s: %s" % (type(_err).__name__, _err)

# ═══════════════════════════════════════════════════════════════════════
# RULE DATA.
# ═══════════════════════════════════════════════════════════════════════

TOOL_NAME = "play_new"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RECEIPTS_NAME = "play_new_receipts.jsonl"
DEFAULT_CONFIG_NAME = "play_forge.config.json"   # W1: no second config

OUT_SUFFIX = ".play.json"
TMP_SUFFIX = ".tmp"

# kct-brandkit v5.2 MULTI-VARIANT PLAYS: one line, N treatments.
TARGET_VARIANTS = 5

# The colour path axis is pinned at two by doctrine (flat pool vs the
# outline path — kct-brandkit v5.2 SECTION B item 6).
COLOR_PATH_CYCLE = ("flat_pool", "outline_path")

# Family is play_forge's W12 registry; three straights then the two
# newer families, so a play exercises them without leading with them.
FAMILY_CYCLE = ("straight", "straight", "straight", "arc", "badge")

# Layouts that still mean something with no art at all. The other
# three are art-led by their own registry hierarchy lines ("art sits
# above", "the ART is the biggest element", framing elements), so
# --no-art leaves these two.
ART_FREE_LAYOUTS = ("text_hero", "text_dominant")

# W4 — placement per layout. LOOKED UP, NEVER COMPUTED.
ELEMENT_DEFAULTS = {
    "text_hero":     {"size_fraction": 0.18, "positions": ("above_hero",)},
    "art_top":       {"size_fraction": 0.43, "positions": ("above_hero",)},
    "art_hero":      {"size_fraction": 0.40, "positions": ("above_hero",)},
    "frame":         {"size_fraction": 0.20, "positions": ("left", "right")},
    "text_dominant": {"size_fraction": 0.15, "positions": ("below_support",)},
}
# The badge family carries its own placement whatever the layout says:
# play_forge anchors badge elements off the ring.
FAMILY_ELEMENT_DEFAULTS = {
    "badge": {"size_fraction": 0.15, "positions": ("below_support",)},
}
# frame wants two assets; with exactly one candidate it goes LEFT.
SINGLE_CANDIDATE_POSITION = "left"

SLUG_KEEP = "abcdefghijklmnopqrstuvwxyz0123456789"
SLUG_SEPARATOR = "-"
SLUG_MAX_LEN = 60

TAG_SEPARATOR = ","
NICHE_TAGS_COLUMN = 3          # the D-419 7-column shape
SIDECAR_NAME = "ASSET_INDEX.hashes.json"
INDEX_NAME = "ASSET_INDEX.md"

SIDECAR_NOTE = "sidecar: PRESENT, NOT VERIFIED"
DRAFT_NOTE = ("DRAFT: font_pair rotated by rule, not by register — "
              "edit before render.")
REGISTER_GAP_NOTE = (
    "REGISTER GAP: the line is ALL CAPS, so kct-brandkit v5.2's only "
    "Title-Case-only font is excluded and the warm/sentimental "
    "register is unreachable by this tool. Reported, not designed "
    "around.")

DATE_FORMAT = "%Y-%m-%d"

JSON_DUMP = {"ensure_ascii": False, "sort_keys": True, "indent": 1,
             "separators": (",", ": ")}

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2

# ═══════════════════════════════════════════════════════════════════════
# END OF RULE DATA.
# ═══════════════════════════════════════════════════════════════════════


class NewPlayError(Exception):
    """A refusal. Exit 2. `kind` names the class."""

    def __init__(self, message, kind="ERROR"):
        super().__init__(message)
        self.kind = kind


def _ensure_utf8_console():
    """Fleet copy (D-378/D-380): display only, never a crash site."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _assert_element_defaults_complete():
    """W4 boot-time completeness. A layout added to play_forge's
    registry with no placement here must fail NOW, not on the one run
    that happens to land on it."""
    missing = [name for name in play_schema.LAYOUTS
               if name not in ELEMENT_DEFAULTS]
    if missing:
        sys.stderr.write(
            "REFUSED (ELEMENT_DEFAULTS_INCOMPLETE): layout(s) %s are "
            "in the registry with no W4 placement entry in %s\n"
            % (sorted(missing), TOOL_NAME))
        sys.exit(EXIT_ERROR)


if FLEET_IMPORT_ERROR is None:
    _assert_element_defaults_complete()


def nfc(text):
    """W6/W9: one normalization, at entry, before anything else."""
    return unicodedata.normalize("NFC", text)


def slug(text):
    """RULE DATA shape: NFC first (without it the same visible punch
    yields two ids), ASCII alphanumerics only, single separators,
    length-capped."""
    kept = []
    previous_sep = True
    for char in nfc(text).lower():
        if char in SLUG_KEEP:
            kept.append(char)
            previous_sep = False
        elif not previous_sep:
            kept.append(SLUG_SEPARATOR)
            previous_sep = True
    result = "".join(kept).strip(SLUG_SEPARATOR)[:SLUG_MAX_LEN]
    return result.strip(SLUG_SEPARATOR)


# ── config, fonts, garments ────────────────────────────────────────────

def load_config(path):
    """W1: play_forge's own loader, so there is one config contract."""
    try:
        return pf.load_config(path)
    except pf.ForgeError as err:
        raise NewPlayError(str(err), kind="CONFIG")


def live_garments():
    """kct-brandkit v5.2 SECTION A item 2: only three garment colours
    exist and Dark Heather is still unlocked (no hex, pending the
    physical sample). Live ones keep color_check's own order, which is
    what pins the 3/2 split."""
    return tuple(name for name, info in cc.GARMENTS.items()
                 if not info["provisional"])


def resolve_garment_argument(value):
    """--garment Black | Sport Grey | both. Dark Heather refuses by
    name, never a KeyError."""
    if value is None or value.strip().lower() == "both":
        return None
    wanted = value.strip().lower()
    if wanted not in cc.GARMENTS:
        raise NewPlayError(
            "unknown garment %r (color_check knows %s)"
            % (value, sorted(cc.GARMENTS)), kind="GARMENT_UNKNOWN")
    if wanted not in live_garments():
        raise NewPlayError(
            "garment %r is not live — kct-brandkit v5.2 SECTION A "
            "item 2: unlocked, no hex, pending the physical sample"
            % value, kind="GARMENT_NOT_LIVE")
    return wanted


def garment_sequence(count, fixed):
    """W3: garment alternates, or is fixed. It is NOT one of the three
    gate axes and never counts toward the >=2-of-3 budget. Over an odd
    count the FIRST live garment in color_check order takes the extra,
    pinned so two machines cannot disagree."""
    if fixed:
        return tuple([fixed] * count)
    live = live_garments()
    return tuple(live[index % len(live)] for index in range(count))


def fill_pool(garment):
    """W3/W8 of play_forge: the garment's legal fills, from
    color_check's DATA. Sorted, so no set ordering reaches the play."""
    info = cc.GARMENTS[garment]
    pool = set(cc.PALETTES[info["class"]])
    pool.update(cc.BASE_FILLS.get(garment, {}))
    return tuple(sorted(pool))


# ── W3 axis spaces ─────────────────────────────────────────────────────

def usable_font_pairs(punch, setup):
    """Every (hero, support) pair the register rule allows for THESE
    lines. The predicate is play_forge.line_is_all_caps — imported, so
    play_new predicts play_forge instead of keeping a second copy.
    Roster order is preserved; a single usable font gives the mono-font
    pair kct-brandkit v5.2 allows."""
    roster = tuple(pf.FONT_ROSTER)
    punch_caps = pf.line_is_all_caps(punch)
    setup_caps = pf.line_is_all_caps(setup)
    pairs = []
    for hero_index, hero in enumerate(roster):
        for support in roster[hero_index + 1:]:
            if hero in pf.TITLE_CASE_ONLY_FONTS and punch_caps:
                continue
            if support in pf.TITLE_CASE_ONLY_FONTS and setup_caps:
                continue
            pairs.append((hero, support))
    if pairs:
        return tuple(pairs)
    mono = [font for font in roster
            if not (font in pf.TITLE_CASE_ONLY_FONTS
                    and (punch_caps or setup_caps))]
    return tuple((font, font) for font in mono[:1])


def feasibility(layouts, pairs):
    """W0. The three axes form a length-3 code of minimum distance 2,
    so every 2-axis projection must be injective and the ceiling is
    the smallest of the three projection sizes. colour path is pinned
    at 2 by doctrine, so that is 2 * min(layouts, font_pairs)."""
    return len(COLOR_PATH_CYCLE) * min(len(layouts), len(pairs))


def _distance_ok(one, other):
    return sum(1 for a, b in zip(one, other) if a != b) >= 2


def assign_axes(layouts, pairs, count):
    """W3, deterministic. The plain rotation is tried FIRST and used
    whenever it satisfies the >=2-of-3 rule. It does not always: with
    two layouts and four variants, rotation puts variants 0 and 2 on
    the same layout AND the same colour path, differing on font alone
    — measured, and it is exactly the --no-art case. So the fallback
    is a deterministic search over the axis product in registry order,
    taking the first valid set. No randomness, no taste, same answer
    on every machine."""
    rotation = [(layouts[index % len(layouts)],
                 COLOR_PATH_CYCLE[index % len(COLOR_PATH_CYCLE)],
                 pairs[index % len(pairs)])
                for index in range(count)]
    if all(_distance_ok(rotation[a], rotation[b])
           for a in range(count) for b in range(a + 1, count)):
        return tuple(rotation), "rotation"
    combos = [(layout, color, pair)
              for layout in layouts
              for color in COLOR_PATH_CYCLE
              for pair in pairs]
    chosen = []

    def walk(start):
        if len(chosen) == count:
            return True
        for index in range(start, len(combos)):
            candidate = combos[index]
            if all(_distance_ok(candidate, taken) for taken in chosen):
                chosen.append(candidate)
                if walk(index + 1):
                    return True
                chosen.pop()
        return False

    if not walk(0):
        raise NewPlayError(
            "no assignment of %d variants satisfies the >=2-of-3 axis "
            "rule over %d layouts and %d font pairs"
            % (count, len(layouts), len(pairs)), kind="AXES_INFEASIBLE")
    return tuple(chosen), "search"


# ── W2 art candidates ──────────────────────────────────────────────────

def load_sidecar(index_root):
    path = os.path.join(index_root, SIDECAR_NAME)
    if not os.path.isfile(path):
        raise NewPlayError("no %s in %s — provenance cannot be carried"
                           % (SIDECAR_NAME, index_root),
                           kind="SIDECAR_MISSING")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as err:
        raise NewPlayError("sidecar unreadable: %s" % err,
                           kind="SIDECAR_UNREADABLE")
    entries = data.get("entries")
    if not isinstance(entries, dict):
        raise NewPlayError("sidecar has no entries dict",
                           kind="SIDECAR_UNREADABLE")
    return entries


def tag_matches(cell, wanted):
    """W2, receipted matching rule: NFC -> casefold -> split on commas
    -> strip -> EXACT on a whole tag. Never substring."""
    tags = [part.strip().casefold()
            for part in nfc(cell).split(TAG_SEPARATOR)]
    return nfc(wanted).strip().casefold() in tags


def art_candidates(index_root, tag):
    """Rows that carry the tag, have a sidecar entry, pass the row
    lint, and name a FILE. In INDEX ORDER."""
    index_path = os.path.join(index_root, INDEX_NAME)
    if not os.path.isfile(index_path):
        raise NewPlayError("no %s in %s" % (INDEX_NAME, index_root),
                           kind="INDEX_MISSING")
    with open(index_path, "r", encoding="utf-8") as handle:
        lines = handle.read().split("\n")
    entries = load_sidecar(index_root)
    headers = ail.find_header_lines(lines)
    candidates = []
    for number, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        if ail.is_separator_row(line) or number in headers:
            continue
        if ail.lint_row(line):
            continue
        cells = ail.split_cells(line)
        if not tag_matches(cells[NICHE_TAGS_COLUMN], tag):
            continue
        path = ail.asset_path(line)
        if not path or path.endswith("/"):
            continue                      # folder rows are not renderable
        entry = entries.get(path)
        if not entry or not entry.get("sha256"):
            continue
        candidates.append({"asset_id": path,
                           "expected_sha256": entry["sha256"],
                           "index_line": number + 1})
    return candidates


# ── build ──────────────────────────────────────────────────────────────

def placement_for(layout, family):
    spec = FAMILY_ELEMENT_DEFAULTS.get(family) or ELEMENT_DEFAULTS[layout]
    return spec["size_fraction"], spec["positions"]


def build_play(args, candidates, axes, garments, date_text):
    """Assemble the play dict. Fills rotate WITHIN each
    (garment, colour path) group so no two variants can share both an
    element set and a colour cluster set — play_forge's W6 rejects
    that regardless of axis labels."""
    variants = []
    group_counter = {}
    pointer = 0
    for index, (layout, color_path, pair) in enumerate(axes):
        garment = garments[index]
        family = FAMILY_CYCLE[index % len(FAMILY_CYCLE)]
        pool = fill_pool(garment)
        key = (garment, color_path)
        taken = group_counter.get(key, 0)
        group_counter[key] = taken + 1
        fill_hex = pool[taken % len(pool)]
        outline_hex = None
        if color_path == "outline_path":
            entry = cc.OUTLINES.get(garment)
            if entry is None:
                raise NewPlayError(
                    "garment %r has no OUTLINES entry, so the outline "
                    "path is not available for it" % garment,
                    kind="NO_OUTLINE_FOR_GARMENT")
            outline_hex = entry["hex"]
        elements = []
        if candidates:
            size_fraction, positions = placement_for(layout, family)
            if len(candidates) == 1 and len(positions) > 1:
                # frame wants two assets; with exactly one candidate it
                # goes LEFT and is never duplicated left AND right
                positions = (SINGLE_CANDIDATE_POSITION,)
            for position in positions:
                asset = candidates[pointer % len(candidates)]
                if len(candidates) > 1:
                    pointer += 1        # advance by assets CONSUMED
                elements.append({
                    "asset_id": asset["asset_id"],
                    "expected_sha256": asset["expected_sha256"],
                    "recolor_hex": fill_hex,
                    "size_fraction": size_fraction,
                    "position": position,
                })
        variants.append({
            "id": index + 1,
            "garment": garment.title(),
            "font_pair": {"hero": pair[0], "support": pair[1]},
            "color_path": color_path,
            "layout": layout,
            "family": family,
            "fill_hex": fill_hex,
            "outline_hex": outline_hex,
            "elements": elements,
            "element_count": len(elements),
            "axes": {"layout": layout, "color_path": color_path,
                     "font_pair": "%s + %s" % pair,
                     "family": family, "garment": garment.title()},
        })
    return {
        "play_id": "%s%s%s" % (slug(args.punch), SLUG_SEPARATOR,
                               date_text),
        "line": {"setup": args.setup, "punch": args.punch},
        "named_feeling": args.feeling,
        "draft_note": DRAFT_NOTE,
        "variants": variants,
    }


# ── W13 atomic write + W5 validation ───────────────────────────────────

def write_validated(play, out_path, config):
    """W13 then W5. The bytes are written to a temp file in the SAME
    directory, both validators run against it, and only a pass earns
    os.replace. A failure unlinks the temp and leaves the target
    exactly as it was — including a good play that --overwrite would
    otherwise have truncated to 0 bytes at open()."""
    tmp_path = out_path + "." + uuid.uuid4().hex + TMP_SUFFIX
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(play, handle, **JSON_DUMP)
        handle.write("\n")
    try:
        loaded = play_schema.load_play(tmp_path)
    except BaseException as err:
        os.unlink(tmp_path)
        raise NewPlayError("play_schema rejected the play: %s" % err,
                           kind="SCHEMA_REJECTED")
    try:
        failures, _clusters = pf.check_structure(loaded, config)
    except BaseException as err:
        os.unlink(tmp_path)
        raise NewPlayError("check_structure raised: %s" % err,
                           kind="STRUCTURE_ERROR")
    if failures:
        os.unlink(tmp_path)
        raise NewPlayError(
            "play_forge.check_structure rejected the play:\n  %s"
            % "\n  ".join(failures), kind="STRUCTURE_REJECTED")
    os.replace(tmp_path, out_path)


def existing_punch(path):
    """W1: name the EXISTING play's punch line in the refusal —
    different lines slug identically."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)["line"]["punch"]
    except BaseException:
        return "(unreadable — could not read its punch line)"


# ── receipts and output ────────────────────────────────────────────────

def append_receipt(report):
    """W7: a receipt on EVERY terminating path. A tool that refuses
    fifty times silently hides its own pattern."""
    receipt = {
        "tool": TOOL_NAME,
        "play_id": report.get("play_id"),
        "out_path": report.get("out_path"),
        "written": report.get("written", False),
        "variants": report.get("variant_count", 0),
        "candidates": report.get("candidates", []),
        "sidecar": SIDECAR_NOTE,
        "tag_match_rule": ("NFC -> casefold -> split on commas -> "
                           "strip -> exact whole tag"),
        "axis_assignment": report.get("axis_assignment"),
        "findings": report.get("findings", []),
        "refusals": report.get("refusals", []),
        "exit_code": report.get("exit_code"),
    }
    try:
        with open(os.path.join(BASE_DIR, RECEIPTS_NAME), "a",
                  encoding="utf-8") as handle:
            handle.write(json.dumps(receipt, sort_keys=True,
                                    ensure_ascii=False) + "\n")
    except OSError:
        pass


def format_report(report):
    lines = ["%s %s  variants=%s  exit=%s"
             % (TOOL_NAME, report.get("play_id"),
                report.get("variant_count", 0),
                report.get("exit_code"))]
    if report.get("out_path"):
        lines.append("  out: %s" % report["out_path"])
    if report.get("axis_assignment"):
        lines.append("  axes assigned by: %s"
                     % report["axis_assignment"])
    for item in report.get("candidates", []):
        lines.append("  candidate: %s (index line %d)"
                     % (item["asset_id"], item["index_line"]))
    lines.append("  %s" % SIDECAR_NOTE)
    for finding in report.get("findings", []):
        lines.append("  FINDING: %s" % finding)
    for refusal in report.get("refusals", []):
        lines.append("  REFUSED (%s): %s"
                     % (refusal["kind"], refusal["reason"]))
    lines.append("  %s" % DRAFT_NOTE)
    return "\n".join(lines)


def run(args, report):
    """The whole run, filling the ONE report dict both renderings come
    from (W7 parity is structural). The dict is main's, so a refusal
    still receipts whatever context was established first."""
    config = load_config(args.config)
    try:
        pf.preflight_fonts(config["fonts_dir"])      # W8, imported
    except pf.ForgeError as err:
        raise NewPlayError(str(err), kind="FONTS_MISSING")
    fixed_garment = resolve_garment_argument(args.garment)
    date_text = args.date or datetime.date.today().strftime(DATE_FORMAT)
    play_slug = slug(args.punch)
    if not play_slug:
        raise NewPlayError(
            "the punch line %r slugs to an empty id — a play needs a "
            "name" % args.punch, kind="EMPTY_SLUG")
    play_id = "%s%s%s" % (play_slug, SLUG_SEPARATOR, date_text)
    report["play_id"] = play_id
    out_path = os.path.join(config["out_dir"], play_id + OUT_SUFFIX)
    report["out_path"] = out_path
    if os.path.exists(out_path) and not args.overwrite:
        raise NewPlayError(
            "%s already exists — its punch line is %r. Use --overwrite "
            "to replace it." % (out_path, existing_punch(out_path)),
            kind="OUT_FILE_EXISTS")
    candidates = []
    if not args.no_art:
        candidates = art_candidates(config["index_root"], args.tag)
        if not candidates:
            raise NewPlayError(
                "no ASSET_INDEX row carries the tag %r with a sidecar "
                "entry — use --no-art to write a type-only play"
                % args.tag, kind="NO_ART_FOR_TAG")
    report["candidates"] = candidates
    layouts = (ART_FREE_LAYOUTS if args.no_art
               else tuple(play_schema.LAYOUTS))
    pairs = usable_font_pairs(args.punch, args.setup)
    ceiling = feasibility(layouts, pairs)
    count = min(TARGET_VARIANTS, ceiling)
    if count < TARGET_VARIANTS:
        report["findings"].append(
            "%d layouts and %d font pairs available; ceiling is "
            "2*min(%d,%d)=%d variants, not %d%s"
            % (len(layouts), len(pairs), len(layouts), len(pairs),
               ceiling, TARGET_VARIANTS,
               " (--no-art)" if args.no_art else ""))
    if count < 1:
        raise NewPlayError("the axis spaces allow zero variants",
                           kind="AXES_INFEASIBLE")
    if any(font in pf.TITLE_CASE_ONLY_FONTS for font in pf.FONT_ROSTER) \
            and pf.line_is_all_caps(args.punch):
        report["findings"].append(REGISTER_GAP_NOTE)
    axes, how = assign_axes(layouts, pairs, count)
    report["axis_assignment"] = how
    garments = garment_sequence(count, fixed_garment)
    play = build_play(args, candidates, axes, garments, date_text)
    os.makedirs(config["out_dir"], exist_ok=True)
    write_validated(play, out_path, config)
    report["written"] = True
    report["variant_count"] = len(play["variants"])
    report["exit_code"] = (EXIT_FINDINGS if report["findings"]
                           else EXIT_CLEAN)
    return report


def build_parser():
    parser = argparse.ArgumentParser(
        prog="play_new.py",
        description="One written line in, one valid play.json out. A "
                    "scaffolder: it does not render, does not rank, "
                    "and holds no taste of its own.")
    parser.add_argument("--setup", required=True)
    parser.add_argument("--punch", required=True)
    parser.add_argument("--feeling", required=True,
                        help="the named feeling (kct-brandkit v5.2 "
                             "EMOTION CHAIN item 5) — written into "
                             "the play as named_feeling")
    parser.add_argument("--tag", required=True,
                        help="niche tag to match, whole-tag exact")
    parser.add_argument("--garment", default=None,
                        help="Black | Sport Grey | both (default)")
    parser.add_argument("--no-art", action="store_true",
                        dest="no_art")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--date", default=None,
                        help="YYYY-MM-DD, default the local date")
    parser.add_argument("--config", default=DEFAULT_CONFIG_NAME)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv=None):
    _ensure_utf8_console()
    parser = build_parser()
    args = parser.parse_args(argv)          # argparse owns exit 2 here
    report = {"tool": TOOL_NAME, "written": False, "findings": [],
              "refusals": [], "candidates": [], "variant_count": 0}
    try:
        if FLEET_IMPORT_ERROR is not None:
            raise NewPlayError(
                "a fleet import failed (%s) — play_new imports "
                "play_forge, which needs Pillow"
                % FLEET_IMPORT_ERROR, kind="DEP_MISSING")
        args.setup = nfc(args.setup)        # W6: normalize once, first
        args.punch = nfc(args.punch)
        args.feeling = nfc(args.feeling)
        args.tag = nfc(args.tag)
        if args.date is not None:
            try:
                datetime.datetime.strptime(args.date, DATE_FORMAT)
            except ValueError:
                raise NewPlayError("--date must be YYYY-MM-DD (got %r)"
                                   % args.date, kind="BAD_DATE")
        run(args, report)
    except NewPlayError as err:
        report["refusals"] = [{"kind": err.kind, "reason": str(err)}]
        report["exit_code"] = EXIT_ERROR
        append_receipt(report)
        if args.json:
            print(json.dumps(report, sort_keys=True,
                             ensure_ascii=False))
        else:
            print("REFUSED (%s): %s" % (err.kind, err), file=sys.stderr)
        return EXIT_ERROR
    except BaseException as err:            # W12 crash floor
        report["refusals"] = [{"kind": "CRASH",
                               "reason": "%s: %s"
                                         % (type(err).__name__, err)}]
        report["exit_code"] = EXIT_ERROR
        append_receipt(report)
        message = ("CRASH (%s): %s — a traceback would have exited 1, "
                   "which this tool reads as 'written with findings'"
                   % (type(err).__name__, err))
        if args.json:
            print(json.dumps(report, sort_keys=True,
                             ensure_ascii=False))
        else:
            print(message, file=sys.stderr)
        return EXIT_ERROR
    append_receipt(report)
    if args.json:
        print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    else:
        print(format_report(report))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
