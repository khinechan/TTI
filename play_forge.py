#!/usr/bin/env python3
"""play_forge.py — THE MACHINE (MC FLEET B2, court riders Fable
2026-09-02; built 2026-09-02). One play.json in, N gated variants out.

Productizes the 5-variant play (kct-brandkit v5.2, MULTI-VARIANT
PLAYS): this tool enforces STRUCTURE and never judges taste. No
ranking, no ordering, no favourite, no "recommended" — number order
only, in every output; Khai's eye is the only selection layer (W10).

Per variant: a 4500x5400 LOSSLESS PNG authored natively at full size
(W5 — a 3px stroke authored at 1000px becomes 13.5px at 4500), a
220px squint that is a DOWNSAMPLE of the full render (never a second
draw pass), and a spec sheet (JSON + markdown) carrying axis values,
the named feeling, elements with verified provenance ids + sha256,
hexes with their clusters, fonts, and gate verdicts. Per run: one
contact sheet of fulls and one of squints, tiles in number order, and
a receipt — written even when the spec is rejected.

Walls (each has a test behind it):
  W1 recolor by alpha ONLY via recolor.py — never a local copy, never
     RGB equality (~30% of an anti-aliased shape is blended edge).
  W2 hexes are CLUSTERED by RGB distance before counting to 2, across
     type + all elements (garment excluded); clusters print in the
     spec sheet; >2 clusters rejects the spec.
  W3 NO try/except around font loading, ever. load_default() falls
     back to a tiny bitmap font SILENTLY — a missing roster font is a
     hard fail before variant 1 renders, via an isfile pre-flight of
     all four roster paths.
  W4 measure and fit, never pick a size: binary-search until the line
     fits its layout's width fraction; then the fitted line's mask is
     ERODED by min_stroke_px — if the ink does not survive, the line
     only fits by going too thin, and the variant is rejected with a
     named reason (min_stroke_px is config, PROVISIONAL — Khai's wash
     rule, not yet a D-number).
  W6 near-clones are rejected structurally: every variant pair differs
     on >=2 of font_pair / color_path / layout, and no pair shares
     both the element set and the clustered colour set.
  W7 provenance is VERIFIED, not declared: every element resolves to
     an ASSET_INDEX row AND its file's sha256 matches the B3 sidecar.
     Bundle-path asset_ids resolve through the sidecar the same way;
     this tool never crops a bundle itself.
  W8 fill/outline allowlists come from color_check.py's DATA
     (GARMENTS / PALETTES / BASE_FILLS / OUTLINES), never a local
     copy. A garment's outline-only hex is never a fill.
  W9 gates run AFTER render and verdicts are ATTACHED: color_check,
     thumb_check, and render_qc's check_thumbnail_eyes (character
     elements only — ornament/type variants record EYES_N/A; the
     module is vault-side, so its absence records EYES_UNAVAILABLE).
     A FAIL variant is badged on its contact tile, never hidden,
     never auto-fixed.
  W11 assets and fonts are NEVER committed; paths come from config;
     lossless PNG only; no credentials, no network.
  W12 families: straight | arc (C) | badge (D), the outline path
     works in all three; the layout registry maps the five layouts to
     concrete compositions, each with a one-line hierarchy rule
     (--explain prints them). Extending a registry = code + test +
     doc line.

Exit codes:
    0 = every variant rendered, every gate PASS
    1 = rendered with findings (a gate FAIL, a W4-rejected variant)
    2 = refusal: spec rejected (W2/W6/W8), provenance (W7), missing
        roster font (W3), bad config, unknown flag

Dependencies: Pillow (image-family tool, W7 court wording
2026-09-02). Renderer note (R1): batch_renderer/spec_renderer live
vault-side and are ABSENT from this repo, so the renderer lives here
— not a fork; there is no first copy in this repo.
"""

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

import asset_index_lint as ail
import color_check as cc
import play_schema
import recolor

# ═══════════════════════════════════════════════════════════════════════
# RULE DATA.
# ═══════════════════════════════════════════════════════════════════════

TOOL_NAME = "play_forge"
BASE_DIR = Path(__file__).resolve().parent
TOOLS_DIR = Path(__file__).resolve().parent   # gate tools live here
RECEIPTS_NAME = "play_forge_receipts.jsonl"   # gitignored (W11)

DEFAULT_CONFIG_NAME = "play_forge.config.json"
REQUIRED_CONFIG_KEYS = ("index_root", "fonts_dir", "out_dir")
KNOWN_CONFIG_KEYS = REQUIRED_CONFIG_KEYS + ("cluster_distance",
                                            "min_stroke_px",
                                            "min_stroke_survival")

DEFAULT_CLUSTER_DISTANCE = 10.0   # W2: #D9A441 vs #D9A442 = 1.0,
                                  # vs #7A9CB0 = 146.3
MAX_COLOR_CLUSTERS = 2            # the shop's 2-color law (D-053)

DEFAULT_MIN_STROKE_PX = 5         # W4 — PROVISIONAL: Khai's wash
                                  # rule, NOT yet a D-number; do not
                                  # cite one
DEFAULT_MIN_STROKE_SURVIVAL = 0.50
# W4, bench F1 (Fable, 2026-09-02): the fraction of the fitted line's
# ink that must survive erosion by min_stroke_px. PROVISIONAL, same
# wording as min_stroke_px, and a config key beside it. The original
# 0.01 asked "does the thickest 1% survive" — it could NEVER fire on
# a real font (measured on the real roster at a 5px kernel:
# Baseball/Vorn 0.80-0.89 at every layout, Mango Dream 0.44-0.62,
# Midtown Script 0.38-0.58; a 142px Midtown support rendered as a
# hairline and PASSED). At 0.50 the thin scripts are rejected in the
# tight layouts and the block fonts pass everywhere — a floor that
# actually bites.

CANVAS_W, CANVAS_H = 4500, 5400   # W5: author natively (300dpi)
MARGIN_PX = 150                   # brandkit minimum margin
SQUINT_W = 220
SQUINT_H = 264                    # 220 * 5400/4500
RESAMPLE = Image.LANCZOS          # squint IS this downsample (T5)

# The 4-font roster (kct-brandkit v5.2). Basenames are resolved in
# fonts_dir as <base>.otf then <base>.ttf — exact vault filenames are
# PROVISIONAL until Sonnet confirms (flagged). Fonts NEVER committed.
FONT_ROSTER = {
    "Baseball Athlete Jersey": "Baseball Athlete Jersey",
    "Vorn": "Vorn",
    "Midtown Script": "Midtown Script",
    "Mango Dream": "Mango Dream",
}
FONT_EXTS = (".otf", ".ttf")

# Brandkit register rule (v5.2, wired on Khai's order 2026-09-02):
# Midtown Script is Title Case only, never ALL CAPS. The wired half
# is the enforceable half — an all-caps line in a listed font rejects
# the variant by name.
TITLE_CASE_ONLY_FONTS = ("Midtown Script",)

MIN_FIT_SIZE = 20                 # W4 binary-search bounds
MAX_FIT_SIZE = 1400
STROKE_WIDTH_DIVISOR = 28         # outline stroke = size/28, min 2

# W12 — layout registry: the five closed layouts mapped to concrete
# compositions. Each carries its ONE-LINE HIERARCHY RULE (doc).
# Extending this registry = code + a test + a doc line.
LAYOUT_SPECS = {
    "text_hero": {
        "doc": "the TEXT is the biggest element; art is a small "
               "accent around it",
        "hero_frac": 0.80, "support_frac": 0.52,
        "hero_cy": 0.46, "support_cy": 0.22},
    "text_dominant": {
        "doc": "text overwhelms the canvas; art sits tiny below the "
               "lines",
        "hero_frac": 0.86, "support_frac": 0.60,
        "hero_cy": 0.46, "support_cy": 0.30},
    "art_top": {
        "doc": "art sits above; the text below it is still the "
               "widest element",
        "hero_frac": 0.74, "support_frac": 0.50,
        "hero_cy": 0.66, "support_cy": 0.54},
    "art_hero": {
        "doc": "the ART is the biggest element; text is smaller, "
               "below it",
        "hero_frac": 0.55, "support_frac": 0.38,
        "hero_cy": 0.78, "support_cy": 0.68},
    "frame": {
        "doc": "left/right elements frame the centered text between "
               "them",
        # bench F5 fallout: the old 0.58 hero ran under the framing
        # art at sample scale — with the overlap wall live, frame
        # text must actually FIT between its frames
        "hero_frac": 0.46, "support_frac": 0.36,
        "hero_cy": 0.44, "support_cy": 0.30},
}

# W12 — family registry (closed, mirrored from play_schema.FAMILIES):
# straight = classic lockup · arc = family C (hero line on a circular
# arc) · badge = family D (ring, arced setup on top, straight hero
# center). The outline path works in ALL of them.
FAMILY_DOCS = {
    "straight": "hero and support drawn as straight centered lines",
    "arc": "family C: the hero line rides a circular arc, support "
           "straight below",
    "badge": "family D: a ring badge — setup arcs the top of the "
             "ring, hero straight in the center",
}
ARC_SPAN_RAD = 1.9                # radians of arc the hero line spans
ARC_SUPPORT_GAP_PX = 120          # bench F2: support sits BELOW the
                                  # arc's MEASURED extent, this far
BADGE_RING_CY = 0.45              # ring center as canvas-H fraction
BADGE_RING_FRAC = 0.33            # ring radius as fraction of canvas W
BADGE_RING_WIDTH_FRAC = 0.012
BADGE_TEXT_CHORD_FRAC = 0.72      # bench F3: badge text width is
                                  # capped by the ring's inner chord,
                                  # never by the layout's hero_frac
BADGE_ANCHOR_GAP = 0.06           # bench F3: badge anchors clear the
BADGE_ELEMENT_INSET = 0.22        # ring (above/below) or sit inside
                                  # it (left/right at 0.5±inset)

# Element positions: x is fixed per position; y derives from the
# LAYOUT's own line positions (anchor_for below), so "between" really
# sits between that layout's lines and "above_hero" clears them —
# fixed anchors collided with the hero line on text_hero (caught by
# eye on the first sample render).
POSITION_X = {
    "above_hero": 0.50,
    "below_support": 0.50,
    "between": 0.50,
    "left": 0.19,
    "right": 0.81,
    "center": 0.50,
}
ABOVE_HERO_FLOOR = 0.10
BELOW_SUPPORT_CEIL = 0.90
ELEMENT_GAP_PX = 40               # bench F6: breathing gap between an
                                  # element's INK and the measured
                                  # text edge it anchors against

GATE_TIMEOUT_S = 180
EYES_NA = "EYES_N/A"
EYES_UNAVAILABLE = ("EYES_UNAVAILABLE (render_qc is vault-side and "
                    "absent from this repo)")

CONTACT_TILE_W = 640              # contact tile width (fulls)
CONTACT_TILE_H = 768
FAIL_BADGE_COLOR = (200, 30, 30, 255)
LABEL_HALO = (255, 255, 255, 255)
LABEL_FONT_PX = 36

FULL_NAME_FMT = "variant_%02d.png"
SQUINT_NAME_FMT = "variant_%02d_squint.png"
SPEC_JSON_FMT = "variant_%02d_spec.json"
SPEC_MD_FMT = "variant_%02d_spec.md"
CONTACT_FULLS_NAME = "contact_fulls.png"
CONTACT_SQUINTS_NAME = "contact_squints.png"

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2

# ═══════════════════════════════════════════════════════════════════════
# END OF RULE DATA.
# ═══════════════════════════════════════════════════════════════════════


class ForgeError(Exception):
    """Refusal or spec rejection. Exit 2. `kind` names the class."""

    def __init__(self, message, kind="ERROR"):
        super().__init__(message)
        self.kind = kind


def _ensure_utf8_console():
    """Fleet copy (D-378/D-380): display-only, never a crash site."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _utc_now():
    return datetime.now(timezone.utc)


def hash_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ── config ─────────────────────────────────────────────────────────────

def load_config(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        raise ForgeError("config not found: %s (paths are config, "
                         "never hardcoded — copy "
                         "play_forge.config.example.json)" % path)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as err:
        raise ForgeError("config unreadable: %s (%s)" % (path, err))
    if not isinstance(raw, dict):
        raise ForgeError("config must be a JSON object: %s" % path)
    for key in sorted(raw):
        if key not in KNOWN_CONFIG_KEYS:
            raise ForgeError("unknown config key %r (known: %s)"
                             % (key, ", ".join(KNOWN_CONFIG_KEYS)))
    for key in REQUIRED_CONFIG_KEYS:
        if key not in raw or not isinstance(raw[key], str) \
                or not raw[key]:
            raise ForgeError("config key %r missing or not a "
                             "non-empty string" % key)
    cluster_distance = raw.get("cluster_distance",
                               DEFAULT_CLUSTER_DISTANCE)
    if not isinstance(cluster_distance, (int, float)) \
            or isinstance(cluster_distance, bool) \
            or cluster_distance <= 0:
        raise ForgeError("cluster_distance must be a positive number")
    min_stroke = raw.get("min_stroke_px", DEFAULT_MIN_STROKE_PX)
    if not isinstance(min_stroke, int) or isinstance(min_stroke, bool) \
            or min_stroke < 1:
        raise ForgeError("min_stroke_px must be a positive integer")
    survival = raw.get("min_stroke_survival",
                       DEFAULT_MIN_STROKE_SURVIVAL)
    if not isinstance(survival, (int, float)) \
            or isinstance(survival, bool) or not 0 < survival < 1:
        raise ForgeError("min_stroke_survival must be a number in "
                         "(0, 1)")
    config = {key: os.path.abspath(raw[key])
              for key in REQUIRED_CONFIG_KEYS}
    if not os.path.isdir(config["index_root"]):
        raise ForgeError("index_root is not a directory: %s"
                         % config["index_root"])
    if not os.path.isdir(config["fonts_dir"]):
        raise ForgeError("fonts_dir is not a directory: %s"
                         % config["fonts_dir"])
    config["cluster_distance"] = float(cluster_distance)
    config["min_stroke_px"] = min_stroke
    config["min_stroke_survival"] = float(survival)
    return config


# ── fonts (W3) ─────────────────────────────────────────────────────────

def preflight_fonts(fonts_dir):
    """Resolve all four roster fonts BEFORE variant 1 renders. Missing
    = hard refusal. This is an isfile pre-flight, not a load — and the
    loads that follow carry NO try/except and never call
    load_default (W3)."""
    resolved = {}
    missing = []
    for name in sorted(FONT_ROSTER):
        base = FONT_ROSTER[name]
        for ext in FONT_EXTS:
            candidate = os.path.join(fonts_dir, base + ext)
            if os.path.isfile(candidate):
                resolved[name] = candidate
                break
        else:
            missing.append("%s (looked for %s)"
                           % (name, " / ".join(base + e
                                               for e in FONT_EXTS)))
    if missing:
        raise ForgeError("W3 FONT PRE-FLIGHT: roster font(s) missing "
                         "from %s: %s — hard fail, nothing rendered, "
                         "load_default is never an answer"
                         % (fonts_dir, "; ".join(missing)),
                         kind="FONT_MISSING")
    return resolved


def fit_text_size(text, font_path, target_width):
    """W4: binary-search the largest size whose rendered length fits
    target_width. Never picks a size, never guesses."""
    lo, hi = MIN_FIT_SIZE, MAX_FIT_SIZE
    best = MIN_FIT_SIZE
    while lo <= hi:
        mid = (lo + hi) // 2
        font = ImageFont.truetype(font_path, mid)
        if font.getlength(text) <= target_width:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def stroke_kernel(min_stroke_px):
    """W4's erosion kernel: min_stroke_px, rounded UP to odd because
    MinFilter needs an odd size. Factored out here so asset_compose can
    IMPORT it and erode by exactly the same rule instead of keeping a
    second copy that drifts (B5, 2026-09-06)."""
    return min_stroke_px if min_stroke_px % 2 else min_stroke_px + 1


def measure_stroke_survival(text, font_path, size, min_stroke_px):
    """W4's measurement: render the fitted line's mask, erode by
    min_stroke_px, return the surviving ink FRACTION. The caller
    compares it to min_stroke_survival — the number is measured, the
    floor is config (bench F1)."""
    font = ImageFont.truetype(font_path, size)
    left, top, right, bottom = font.getbbox(text)
    width = max(1, right - left)
    height = max(1, bottom - top)
    mask = Image.new("L", (width + 4, height + 4), 0)
    ImageDraw.Draw(mask).text((2 - left, 2 - top), text, font=font,
                              fill=255)
    ink = sum(1 for v in mask.tobytes() if v)
    if ink == 0:
        return 0.0
    eroded = mask.filter(
        ImageFilter.MinFilter(stroke_kernel(min_stroke_px)))
    survived = sum(1 for v in eroded.tobytes() if v)
    mask.close()
    eroded.close()
    return survived / ink


# ── colour law (W2/W8) ─────────────────────────────────────────────────

def _rgb(hexstr):
    return recolor.parse_hex(hexstr)


def cluster_hexes(hexes, max_distance):
    """W2: union-find over RGB Euclidean distance. Returns sorted
    clusters (each a sorted list of the member hexes)."""
    unique = sorted(set(h.upper() for h in hexes))
    parent = list(range(len(unique)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(unique)):
        for j in range(i + 1, len(unique)):
            a, b = _rgb(unique[i]), _rgb(unique[j])
            distance = math.dist(a, b)
            if distance <= max_distance:
                parent[find(i)] = find(j)
    groups = {}
    for i, hexval in enumerate(unique):
        groups.setdefault(find(i), []).append(hexval)
    return sorted(sorted(g) for g in groups.values())


def fill_pool(garment):
    """W8: the garment's legal FILL hexes, straight from
    color_check's data — palette class plus BASE_FILLS."""
    info = cc.GARMENTS[garment]
    pool = set(cc.PALETTES[info["class"]])
    pool.update(cc.BASE_FILLS.get(garment, {}))
    return pool


def outline_only_hex(garment):
    """The garment's outline hex when it is NOT also a legal fill —
    that hex may never appear as a fill (T10; D-313 lineage)."""
    entry = cc.OUTLINES.get(garment)
    if entry and entry["hex"] not in fill_pool(garment):
        return entry["hex"]
    return None


# ── structure gates (W2/W6/W8) ─────────────────────────────────────────

def check_structure(play, config):
    """All structural law, before any render. Returns
    (failures, clusters_by_variant). Any failure rejects the SPEC."""
    failures = []
    clusters_by_variant = {}
    for variant in play["variants"]:
        vid = variant["id"]
        garment = variant["garment"].lower()
        if garment not in cc.GARMENTS:
            failures.append("V%d: unknown garment %r (color_check "
                            "knows %s)" % (vid, variant["garment"],
                                           sorted(cc.GARMENTS)))
            continue
        outline_entry = cc.OUTLINES.get(garment)
        if variant["color_path"] == "outline_path":
            if outline_entry is None:
                failures.append("V%d: outline_path on %r, which has "
                                "no OUTLINES entry in color_check"
                                % (vid, garment))
            elif (variant["outline_hex"] or "").upper() \
                    != outline_entry["hex"].upper():
                failures.append("V%d: W8 — outline_path on %r must "
                                "use its OUTLINES hex %s (%s), got %r"
                                % (vid, garment, outline_entry["hex"],
                                   outline_entry["name"],
                                   variant["outline_hex"]))
        elif variant["color_path"] == "flat_pool":
            if variant["outline_hex"] is not None:
                failures.append("V%d: flat_pool carries outline_hex "
                                "%r — the outline path is a different "
                                "color_path" % (vid,
                                                variant["outline_hex"]))
        else:
            failures.append("V%d: unknown color_path %r"
                            % (vid, variant["color_path"]))
        forbidden = outline_only_hex(garment)
        if forbidden:
            for role, hexval in (
                    [("fill_hex", variant["fill_hex"])]
                    + [("element %s recolor" % e["asset_id"],
                        e["recolor_hex"])
                       for e in variant["elements"]]):
                if hexval and hexval.upper() == forbidden.upper():
                    failures.append("V%d: W8 — %s is OUTLINE-ONLY on "
                                    "%r and may never be a fill (%s)"
                                    % (vid, forbidden, garment, role))
        for element in variant["elements"]:
            if element["position"] not in POSITION_X:
                failures.append("V%d: unknown element position %r "
                                "(registry: %s)"
                                % (vid, element["position"],
                                   sorted(POSITION_X)))
        hexes = [variant["fill_hex"]]
        if variant["outline_hex"]:
            hexes.append(variant["outline_hex"])
        hexes += [e["recolor_hex"] for e in variant["elements"]]
        clusters = cluster_hexes(hexes, config["cluster_distance"])
        clusters_by_variant[vid] = clusters
        if len(clusters) > MAX_COLOR_CLUSTERS:
            failures.append("V%d: W2 — %d colour clusters, the law is "
                            "%d (distance %.1f): %s"
                            % (vid, len(clusters), MAX_COLOR_CLUSTERS,
                               config["cluster_distance"], clusters))
    variants = play["variants"]
    for i in range(len(variants)):
        for j in range(i + 1, len(variants)):
            a, b = variants[i], variants[j]
            differing = sum((
                (a["font_pair"]["hero"], a["font_pair"]["support"])
                != (b["font_pair"]["hero"], b["font_pair"]["support"]),
                a["color_path"] != b["color_path"],
                a["layout"] != b["layout"],
            ))
            if differing < 2:
                failures.append("V%d vs V%d: W6 — differ on only %d "
                                "of font_pair/color_path/layout; "
                                "every pair needs >=2"
                                % (a["id"], b["id"], differing))
            same_elements = (
                sorted(e["asset_id"] for e in a["elements"])
                == sorted(e["asset_id"] for e in b["elements"]))
            same_clusters = (clusters_by_variant.get(a["id"])
                             == clusters_by_variant.get(b["id"]))
            if same_elements and same_clusters:
                failures.append("V%d vs V%d: W6 — same element set "
                                "AND same colour clusters; axis "
                                "labels alone do not make a variant"
                                % (a["id"], b["id"]))
    return failures, clusters_by_variant


# ── provenance (W7) ────────────────────────────────────────────────────

def load_sidecar(index_root):
    path = os.path.join(index_root, "ASSET_INDEX.hashes.json")
    if not os.path.isfile(path):
        raise ForgeError("W7: no ASSET_INDEX.hashes.json at %s — "
                         "provenance cannot be verified, so nothing "
                         "renders" % index_root, kind="PROVENANCE")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as err:
        raise ForgeError("W7: sidecar unreadable (%s)" % err,
                         kind="PROVENANCE")
    if not isinstance(data, dict) \
            or not isinstance(data.get("entries"), dict):
        raise ForgeError("W7: sidecar has no entries dict",
                         kind="PROVENANCE")
    return data["entries"]


def load_index_paths(index_root):
    path = os.path.join(index_root, "ASSET_INDEX.md")
    if not os.path.isfile(path):
        raise ForgeError("W7: no ASSET_INDEX.md at %s" % index_root,
                         kind="PROVENANCE")
    with open(path, "r", encoding="utf-8") as handle:
        lines = handle.read().split("\n")
    paths = set()
    for line in lines:
        if not line.strip().startswith("|"):
            continue
        if ail.is_separator_row(line) or ail.is_header_row(line):
            continue
        if ail.lint_row(line):
            continue
        rel = ail.asset_path(line)
        if rel:
            paths.add(rel)
    return paths


def resolve_element(asset_id, sidecar_entries, index_paths_set,
                    index_root):
    """W7: asset_id -> (sidecar key, sha256). Exact key first; a
    bundle-path prefix (D-419 note) resolves ONLY when it matches
    exactly one sidecar key. Row must exist; file must exist; hash
    must match. Anything else refuses."""
    aid = asset_id.rstrip("/")
    if asset_id in sidecar_entries:
        key = asset_id
    elif aid in sidecar_entries:
        key = aid
    else:
        matches = sorted(k for k in sidecar_entries
                         if k.startswith(aid + "/"))
        if not matches:
            raise ForgeError("W7: %r has no sidecar entry (exact or "
                             "prefix) — provenance unverifiable"
                             % asset_id, kind="PROVENANCE")
        if len(matches) > 1:
            raise ForgeError("W7: %r is ambiguous — %d sidecar "
                             "entries match (%s …); name the piece"
                             % (asset_id, len(matches), matches[0]),
                             kind="PROVENANCE")
        key = matches[0]
    if key not in index_paths_set:
        raise ForgeError("W7: %r resolves to %r, which has NO "
                         "ASSET_INDEX row" % (asset_id, key),
                         kind="PROVENANCE")
    entry = sidecar_entries[key]
    file_path = os.path.join(index_root, *key.split("/"))
    if not os.path.isfile(file_path):
        raise ForgeError("W7: %r resolves to %r but the file is "
                         "missing under index_root" % (asset_id, key),
                         kind="PROVENANCE")
    actual = hash_file(file_path)
    if actual != entry.get("sha256"):
        raise ForgeError("W7: %r sha256 mismatch — sidecar %s, file "
                         "%s. REFUSED." % (key,
                                           entry.get("sha256"),
                                           actual), kind="PROVENANCE")
    return key, actual, file_path


# ── drawing ────────────────────────────────────────────────────────────

def anchor_for(position, layout, family):
    """Element anchor as canvas fractions — y computed from the
    layout's own line positions so positions mean the same thing in
    every layout. Badge anchors are RING-aware (bench F3): above and
    below clear the ring, left/right sit inside it."""
    x = POSITION_X[position]
    if family == "badge":
        ring_ry = BADGE_RING_FRAC * CANVAS_W / CANVAS_H
        if position == "above_hero":
            return x, max(ABOVE_HERO_FLOOR,
                          BADGE_RING_CY - ring_ry - BADGE_ANCHOR_GAP)
        if position == "below_support":
            return x, min(BELOW_SUPPORT_CEIL,
                          BADGE_RING_CY + ring_ry + BADGE_ANCHOR_GAP)
        if position == "left":
            return 0.50 - BADGE_ELEMENT_INSET, BADGE_RING_CY
        if position == "right":
            return 0.50 + BADGE_ELEMENT_INSET, BADGE_RING_CY
        return 0.50, BADGE_RING_CY
    top = layout["support_cy"]
    bottom = layout["hero_cy"]
    if position == "above_hero":
        y = max(ABOVE_HERO_FLOOR, top / 2 + 0.04)
    elif position == "below_support":
        y = min(BELOW_SUPPORT_CEIL, (bottom + 1.0) / 2)
    elif position == "center":
        y = 0.50
    else:                     # between, left, right: the line midgap
        y = (top + bottom) / 2
    return x, y


def line_is_all_caps(line):
    """True when every LETTER in the line is uppercase (and there is
    at least one). Whole-line, deliberately: this is the exact rule
    the Midtown Script register check has always applied, factored out
    here so play_new can IMPORT it and predict this tool instead of
    keeping a second copy that drifts (Fable rider, 2026-09-04)."""
    letters = [c for c in line if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def _stroke_width(size):
    return max(2, size // STROKE_WIDTH_DIVISOR)


def draw_straight_line(canvas, text, font_path, size, center, fill,
                       stroke_fill):
    font = ImageFont.truetype(font_path, size)
    draw = ImageDraw.Draw(canvas)
    kwargs = {"font": font, "fill": fill, "anchor": "mm"}
    if stroke_fill:
        kwargs["stroke_width"] = _stroke_width(size)
        kwargs["stroke_fill"] = stroke_fill
    draw.text(center, text, **kwargs)


def draw_arc_line(canvas, text, font_path, size, center, radius, fill,
                  stroke_fill):
    """Family C mechanics: each character rendered on its own tile,
    rotated to the arc tangent, composited along the circle. The
    outline path flows through (W12)."""
    font = ImageFont.truetype(font_path, size)
    total = font.getlength(text)
    span = min(ARC_SPAN_RAD, total / radius)
    theta = -span / 2
    stroke = _stroke_width(size) if stroke_fill else 0
    for char in text:
        advance = font.getlength(char)
        step = (advance / total) * span if total else 0
        mid = theta + step / 2
        if not char.isspace():
            tile_side = size * 2 + stroke * 4
            tile = Image.new("RGBA", (tile_side, tile_side),
                             (0, 0, 0, 0))
            tile_draw = ImageDraw.Draw(tile)
            kwargs = {"font": font, "fill": fill, "anchor": "mm"}
            if stroke_fill:
                kwargs["stroke_width"] = stroke
                kwargs["stroke_fill"] = stroke_fill
            tile_draw.text((tile_side // 2, tile_side // 2), char,
                           **kwargs)
            rotated = tile.rotate(-math.degrees(mid), expand=True,
                                  resample=Image.BICUBIC)
            tile.close()
            x = center[0] + radius * math.sin(mid)
            y = center[1] - radius * math.cos(mid)
            canvas.alpha_composite(
                rotated, (int(x - rotated.width / 2),
                          int(y - rotated.height / 2)))
            rotated.close()
        theta += step


def render_variant(variant, roster, config, provenance):
    """W5: author natively at 4500x5400. Every drawn thing — each
    element, each text line, the badge ring — goes onto its OWN layer,
    and any pixel intersection between layers rejects the variant with
    a name (bench F5: a machine can fail it; a human never has to see
    it first). Returns (canvas, placed, sizes) or raises
    VariantRejected."""
    layout = LAYOUT_SPECS[variant["layout"]]
    usable = CANVAS_W - 2 * MARGIN_PX
    setup = variant["_setup"]
    punch = variant["_punch"]
    family = variant["family"]
    fill = variant["fill_hex"]
    stroke_fill = variant["outline_hex"]
    hero_path = roster[variant["font_pair"]["hero"]]
    support_path = roster[variant["font_pair"]["support"]]
    for font_name, line in ((variant["font_pair"]["hero"], punch),
                            (variant["font_pair"]["support"], setup)):
        if font_name in TITLE_CASE_ONLY_FONTS:
            if line_is_all_caps(line):
                raise VariantRejected(
                    "REGISTER: %s is Title Case only, got %r"
                    % (font_name, line))
    hero_target = layout["hero_frac"] * usable
    setup_target = layout["support_frac"] * usable
    ring_r = int(CANVAS_W * BADGE_RING_FRAC)
    ring_w = max(6, int(CANVAS_W * BADGE_RING_WIDTH_FRAC))
    if family == "badge":
        # bench F3: badge text is capped by the ring's inner chord,
        # never by the layout's width fraction
        chord = 2 * (ring_r - ring_w - 40) * BADGE_TEXT_CHORD_FRAC
        hero_target = min(hero_target, chord)
        setup_target = min(setup_target, chord)
    size_punch = fit_text_size(punch, hero_path, hero_target)
    size_setup = fit_text_size(setup, support_path, setup_target)
    for line, path, size, role in (
            (punch, hero_path, size_punch, "hero"),
            (setup, support_path, size_setup, "support")):
        survival = measure_stroke_survival(line, path, size,
                                           config["min_stroke_px"])
        if survival < config["min_stroke_survival"]:
            raise VariantRejected(
                "W4 MIN_STROKE: %s line %r fits at size %d but only "
                "%.2f of its ink survives a %dpx erosion (floor "
                "%.2f) — a line that only fits by going too thin is "
                "a wash failure"
                % (role, line, size, survival,
                   config["min_stroke_px"],
                   config["min_stroke_survival"]))
    canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    layer_masks = []

    def add_layer(name, painter):
        layer = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
        painter(layer)
        mask = layer.getchannel("A").point(
            lambda v: 255 if v else 0)
        for other_name, other_mask in layer_masks:
            overlap_img = ImageChops.darker(mask, other_mask)
            overlap = overlap_img.histogram()[255]
            overlap_img.close()
            if overlap:
                mask.close()
                layer.close()
                for _, m in layer_masks:
                    m.close()
                canvas.close()
                raise VariantRejected(
                    "OVERLAP (bench F5): %s x %s, %d px — layers "
                    "never intersect" % (name, other_name, overlap))
        canvas.alpha_composite(layer)
        layer.close()
        layer_masks.append((name, mask))
        return mask

    def _reject(message):
        for _, mask in layer_masks:
            mask.close()
        canvas.close()
        raise VariantRejected(message)

    # bench F6: text renders FIRST so above_hero / below_support /
    # between anchor off the MEASURED text masks, never a fixed
    # fraction that ignores the element's own height
    text_bboxes = {}
    if family == "badge":
        cx, cy = CANVAS_W // 2, int(CANVAS_H * BADGE_RING_CY)
        box = (cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r)

        def paint_ring(layer):
            draw = ImageDraw.Draw(layer)
            if stroke_fill:
                draw.ellipse(box, outline=stroke_fill,
                             width=ring_w
                             + 2 * _stroke_width(size_punch))
            draw.ellipse(box, outline=fill, width=ring_w)

        text_bboxes["ring"] = add_layer("ring", paint_ring).getbbox()
        text_bboxes["support"] = add_layer(
            "support", lambda layer: draw_arc_line(
                layer, setup, support_path, size_setup, (cx, cy),
                int((ring_r - ring_w) * 0.78), fill,
                stroke_fill)).getbbox()
        text_bboxes["hero"] = add_layer(
            "hero", lambda layer: draw_straight_line(
                layer, punch, hero_path, size_punch, (cx, cy), fill,
                stroke_fill)).getbbox()
    elif family == "arc":
        radius = max(600, int(
            ImageFont.truetype(hero_path, size_punch)
            .getlength(punch) / ARC_SPAN_RAD))
        center = (CANVAS_W // 2,
                  int(layout["hero_cy"] * CANVAS_H) + radius // 3)
        hero_mask = add_layer("hero", lambda layer: draw_arc_line(
            layer, punch, hero_path, size_punch, center, radius,
            fill, stroke_fill))
        text_bboxes["hero"] = hero_mask.getbbox()
        # bench F2: place the support below the arc's MEASURED
        # extent, never at a hoped-for layout position
        arc_bbox = text_bboxes["hero"]
        arc_bottom = arc_bbox[3] if arc_bbox else center[1]
        setup_font = ImageFont.truetype(support_path, size_setup)
        s_top, s_bottom = setup_font.getbbox(setup)[1::2]
        half_height = max(1, (s_bottom - s_top) // 2)
        support_cy = arc_bottom + ARC_SUPPORT_GAP_PX + half_height
        if support_cy + half_height > CANVAS_H - MARGIN_PX:
            _reject(
                "ARC_OVERFLOW (bench F2): the arc's measured extent "
                "(bottom %d) leaves no room for the support line "
                "above the %dpx margin" % (arc_bottom, MARGIN_PX))
        text_bboxes["support"] = add_layer(
            "support", lambda layer: draw_straight_line(
                layer, setup, support_path, size_setup,
                (CANVAS_W // 2, support_cy), fill,
                stroke_fill)).getbbox()
    else:
        text_bboxes["support"] = add_layer(
            "support", lambda layer: draw_straight_line(
                layer, setup, support_path, size_setup,
                (CANVAS_W // 2,
                 int(layout["support_cy"] * CANVAS_H)),
                fill, stroke_fill)).getbbox()
        text_bboxes["hero"] = add_layer(
            "hero", lambda layer: draw_straight_line(
                layer, punch, hero_path, size_punch,
                (CANVAS_W // 2, int(layout["hero_cy"] * CANVAS_H)),
                fill, stroke_fill)).getbbox()
    boxes = [b for b in text_bboxes.values() if b]
    text_top = min(b[1] for b in boxes)
    text_bottom = max(b[3] for b in boxes)
    hero_box = text_bboxes.get("hero")
    support_box = text_bboxes.get("support")
    gap_top = gap_bottom = None
    if hero_box and support_box:
        upper, lower = sorted((hero_box, support_box),
                              key=lambda b: b[1])
        gap_top, gap_bottom = upper[3], lower[1]
    placed = []
    for element in variant["elements"]:
        key, sha, file_path = provenance[element["asset_id"]]
        position = element["position"]
        img = Image.open(file_path)
        rgba = img.convert("RGBA")
        img.close()
        colored = recolor.recolor(rgba, element["recolor_hex"])
        rgba.close()
        target = max(1, int(element["size_fraction"] * CANVAS_W))
        scale = target / max(colored.size)
        resized = colored.resize(
            (max(1, int(colored.width * scale)),
             max(1, int(colored.height * scale))), RESAMPLE)
        colored.close()
        ink = resized.getchannel("A").getbbox() \
            or (0, 0, resized.width, resized.height)
        ink_h = ink[3] - ink[1]
        ink_mid = (ink[1] + ink[3]) // 2
        # Fable live-run fix (2026-09-02): badge above/below now
        # MEASURE too — F6 covered straight/arc only, so a tall
        # element on a badge still anchored off a fixed ring-radius
        # fraction and hit the F5 wall ("element x ring"). For badge,
        # the measured text extent IS the ring mask (it encloses the
        # arced support and the hero).
        measured = position in ("above_hero", "below_support") or (
            family != "badge" and position == "between")
        if measured and position == "above_hero":
            room = text_top - MARGIN_PX - ELEMENT_GAP_PX
            paste_y = text_top - ELEMENT_GAP_PX - ink[3]
            if ink_h > room or (paste_y + ink_mid
                                < ABOVE_HERO_FLOOR * CANVAS_H):
                resized.close()
                _reject("ELEMENT_NO_ROOM (bench F6): above_hero, "
                        "needs %d px, has %d px"
                        % (ink_h + ELEMENT_GAP_PX,
                           max(0, text_top - MARGIN_PX)))
        elif measured and position == "below_support":
            room = (CANVAS_H - MARGIN_PX) - text_bottom \
                - ELEMENT_GAP_PX
            paste_y = text_bottom + ELEMENT_GAP_PX - ink[1]
            if ink_h > room or (paste_y + ink_mid
                                > BELOW_SUPPORT_CEIL * CANVAS_H):
                resized.close()
                _reject("ELEMENT_NO_ROOM (bench F6): below_support, "
                        "needs %d px, has %d px"
                        % (ink_h + ELEMENT_GAP_PX,
                           max(0, CANVAS_H - MARGIN_PX
                               - text_bottom)))
        elif measured:                        # between
            room = ((gap_bottom - gap_top - 2 * ELEMENT_GAP_PX)
                    if gap_top is not None else 0)
            if ink_h > room:
                resized.close()
                _reject("ELEMENT_NO_ROOM (bench F6): between, needs "
                        "%d px, has %d px"
                        % (ink_h + 2 * ELEMENT_GAP_PX,
                           max(0, (gap_bottom - gap_top)
                               if gap_top is not None else 0)))
            paste_y = (gap_top + gap_bottom) // 2 - ink_mid
        if measured:
            paste_x = int(POSITION_X[position] * CANVAS_W
                          - resized.width / 2)
        else:
            ax, ay = anchor_for(position, layout, family)
            paste_x = int(ax * CANVAS_W - resized.width / 2)
            paste_y = int(ay * CANVAS_H - resized.height / 2)
        try:
            add_layer("element:%s" % element["asset_id"],
                      lambda layer: layer.alpha_composite(
                          resized, (paste_x, paste_y)))
        finally:
            resized.close()
        placed.append({"asset_id": element["asset_id"], "path": key,
                       "sha256": sha, "kind": element["kind"],
                       "recolor_hex": element["recolor_hex"],
                       "size_fraction": element["size_fraction"],
                       "position": element["position"]})
    for _, mask in layer_masks:
        mask.close()
    return canvas, placed, {"hero": size_punch, "support": size_setup}


class VariantRejected(Exception):
    """Per-variant W4 rejection. Named reason; the run continues."""


# ── gates (W9) ─────────────────────────────────────────────────────────

def _run_gate(cmd):
    try:
        result = subprocess.run([sys.executable] + cmd,
                                capture_output=True, text=True,
                                timeout=GATE_TIMEOUT_S,
                                cwd=str(TOOLS_DIR))
        code = result.returncode
    except (subprocess.TimeoutExpired, OSError) as err:
        return {"exit": None, "verdict": "ERROR",
                "detail": str(err)[:200]}
    verdict = ("PASS" if code == 0
               else "FAIL" if code == 1 else "ERROR")
    tail = (result.stdout or result.stderr or "").strip()
    return {"exit": code, "verdict": verdict, "detail": tail[-400:]}


def run_gates(variant, png_path, placed):
    garment = variant["garment"].lower()
    declared = sorted({variant["fill_hex"].upper()}
                      | {p["recolor_hex"].upper() for p in placed})
    color_cmd = [str(TOOLS_DIR / "color_check.py"), garment] \
        + declared + ["--json"]
    if variant["outline_hex"]:
        color_cmd += ["--outline", variant["outline_hex"]]
    gates = {"color_check": _run_gate(color_cmd),
             "thumb_check": _run_gate(
                 [str(TOOLS_DIR / "thumb_check.py"), png_path,
                  garment, "--json"])}
    has_character = any(p["kind"] == "character" for p in placed)
    if not has_character:
        gates["eyes"] = {"verdict": EYES_NA,
                         "detail": "no kind:\"character\" element — "
                                   "court rider, not a FAIL"}
    else:
        try:
            import render_qc
        except ImportError:
            gates["eyes"] = {"verdict": EYES_UNAVAILABLE, "detail": ""}
        else:
            try:
                result = render_qc.check_thumbnail_eyes(png_path)
                gates["eyes"] = {"verdict": ("PASS" if result
                                             else "FAIL"),
                                 "detail": repr(result)[:200]}
            except Exception as err:
                gates["eyes"] = {"verdict": "ERROR",
                                 "detail": str(err)[:200]}
    return gates


def gates_failed(gates):
    return any(g.get("verdict") == "FAIL" for g in gates.values())


# ── output ─────────────────────────────────────────────────────────────

def _label(draw, xy, text, color, font):
    for dx in (-2, 0, 2):
        for dy in (-2, 0, 2):
            if dx or dy:
                draw.text((xy[0] + dx, xy[1] + dy), text,
                          fill=LABEL_HALO, font=font)
    draw.text(xy, text, fill=color, font=font)


def _sheet_font():
    try:
        return ImageFont.load_default(LABEL_FONT_PX)
    except TypeError:
        return ImageFont.load_default()


def build_contact_sheet(tiles, path):
    """Tiles strictly in number order (W10) — a rejected variant is a
    labeled placeholder so numbering never re-flows."""
    width = CONTACT_TILE_W * len(tiles)
    sheet = Image.new("RGB", (width, CONTACT_TILE_H), (230, 230, 230))
    font = _sheet_font()
    for index, tile in enumerate(tiles):
        x = index * CONTACT_TILE_W
        if tile["image"] is not None:
            sheet.paste(tile["image"], (x, 0))
            tile["image"].close()
        draw = ImageDraw.Draw(sheet)
        _label(draw, (x + 12, 10), str(tile["number"]),
               (200, 30, 30), font)
        if tile.get("badge"):
            draw.rectangle((x, CONTACT_TILE_H - 60,
                            x + CONTACT_TILE_W - 1,
                            CONTACT_TILE_H - 1),
                           fill=FAIL_BADGE_COLOR)
            _label(draw, (x + 12, CONTACT_TILE_H - 52),
                   tile["badge"], (255, 255, 255), font)
        if tile.get("note"):
            _label(draw, (x + 12, CONTACT_TILE_H // 2),
                   tile["note"][:40], (60, 60, 60), font)
    sheet.save(path)
    sheet.close()


def garment_tile(full_or_squint, garment, tile_size):
    background = Image.new("RGB", tile_size,
                           _rgb(cc.GARMENTS[garment]["hex"]))
    scaled = full_or_squint.resize(tile_size, RESAMPLE)
    background.paste(scaled, (0, 0), scaled)
    scaled.close()
    return background


def write_spec_sheets(out_dir, number, variant, placed, clusters,
                      sizes, gates, feeling, rejected_reason,
                      render_sha256=None):
    """render_sha256 is the sha256 of the BYTES ON DISK, hashed after
    the final write — not of the in-memory image. A spec that says
    PASS beside a hand-edited PNG is the hole this closes: the hash
    names which file the verdict was about. A rejected variant renders
    nothing, so it gets None."""
    spec = {
        "variant": number,
        "named_feeling": feeling,
        "axes": {"font_pair": variant["font_pair"],
                 "color_path": variant["color_path"],
                 "layout": variant["layout"],
                 "family": variant["family"]},
        "layout_hierarchy": LAYOUT_SPECS[variant["layout"]]["doc"],
        "garment": variant["garment"],
        "fill_hex": variant["fill_hex"],
        "outline_hex": variant["outline_hex"],
        "color_clusters": clusters,
        "fitted_sizes": sizes,
        "elements": placed,
        "gates": gates,
        "rejected": rejected_reason,
        "render_sha256": render_sha256,
    }
    with open(os.path.join(out_dir, SPEC_JSON_FMT % number), "w",
              encoding="utf-8") as handle:
        json.dump(spec, handle, sort_keys=True, ensure_ascii=False,
                  indent=1)
    lines = ["# Variant %d spec" % number,
             "- feeling: %s" % feeling,
             "- garment: %s" % variant["garment"],
             "- axes: fonts %s + %s · %s · %s · family %s"
             % (variant["font_pair"]["hero"],
                variant["font_pair"]["support"],
                variant["color_path"], variant["layout"],
                variant["family"]),
             "- hierarchy: %s"
             % LAYOUT_SPECS[variant["layout"]]["doc"],
             "- fill %s · outline %s"
             % (variant["fill_hex"], variant["outline_hex"]),
             "- colour clusters (W2): %s" % clusters]
    for item in placed or []:
        lines.append("- element %s -> %s sha256=%s kind=%s"
                     % (item["asset_id"], item["path"],
                        item["sha256"], item["kind"]))
    for key in sorted(render_sha256 or {}):
        lines.append("- render sha256 (%s): %s"
                     % (key, render_sha256[key]))
    for name, verdict in sorted((gates or {}).items()):
        lines.append("- gate %s: %s" % (name, verdict.get("verdict")))
    if rejected_reason:
        lines.append("- REJECTED: %s" % rejected_reason)
    with open(os.path.join(out_dir, SPEC_MD_FMT % number), "w",
              encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return spec


def _render_order(entry):
    """Sort key for renders[]: numbered variants first in number
    order, then the contact sheets, then by filename. The leading
    boolean is what puts null LAST — sorting a None against an int
    raises TypeError, so the order has to be stated, not inherited."""
    variant = entry["variant"]
    return (variant is None, 0 if variant is None else variant,
            entry["file"])


def append_receipt(report):
    receipt = {
        "tool": TOOL_NAME,
        "play_id": report.get("play_id"),
        "exit_code": report.get("exit_code"),
        "variants_total": report.get("variants_total", 0),
        "rendered": report.get("rendered", 0),
        "rejected": report.get("rejected", []),
        "gate_fails": report.get("gate_fails", []),
        "refusals": report.get("refusals", []),
        "renders": report.get("renders", []),
        "play_sha256": report.get("play_sha256"),
        "out_dir": report.get("out_dir"),
        "out_dir_mode": report.get("out_dir_mode"),
        "duration_s": report.get("duration_s"),
        "completed_utc": _utc_now().isoformat(timespec="seconds"),
    }
    try:
        with open(os.path.join(BASE_DIR, RECEIPTS_NAME), "a",
                  encoding="utf-8") as handle:
            handle.write(json.dumps(receipt, sort_keys=True,
                                    ensure_ascii=False) + "\n")
    except OSError:
        pass


# ── the run ────────────────────────────────────────────────────────────

def run_forge(config, play_path, overwrite=False):
    started = time.monotonic()
    try:
        play = play_schema.load_play(play_path)
    except play_schema.PlayError as err:
        raise ForgeError("spec rejected by the W11 loader: %s" % err,
                         kind="SPEC_REJECTED")
    roster = preflight_fonts(config["fonts_dir"])          # W3
    failures, clusters_by_variant = check_structure(play, config)
    if failures:
        raise ForgeError("SPEC REJECTED (%d structural failure(s)):\n"
                         "  %s" % (len(failures),
                                   "\n  ".join(failures)),
                         kind="SPEC_REJECTED")
    sidecar = load_sidecar(config["index_root"])           # W7
    index_set = load_index_paths(config["index_root"])
    provenance = {}
    for variant in play["variants"]:
        for element in variant["elements"]:
            if element["asset_id"] not in provenance:
                provenance[element["asset_id"]] = resolve_element(
                    element["asset_id"], sidecar, index_set,
                    config["index_root"])
    out_dir = os.path.join(config["out_dir"], play["play_id"])
    out_dir_mode = "FRESH"
    if os.path.isdir(out_dir) and os.listdir(out_dir):
        # bench F4: a second run of the same play_id silently
        # overwrote the first (mark-never-delete). Refuse unless the
        # human says overwrite — vault_backup W0 shape.
        if not overwrite:
            raise ForgeError(
                "OUT_DIR (bench F4): %s is non-empty — a second run "
                "would overwrite the previous renders. Re-run with "
                "--overwrite to do that deliberately." % out_dir,
                kind="OUT_DIR_NOT_EMPTY")
        out_dir_mode = "OVERWRITE"
    os.makedirs(out_dir, exist_ok=True)
    full_tiles = []
    squint_tiles = []
    rejected = []
    gate_fails = []
    variant_reports = []
    renders = []
    rendered = 0
    for variant in play["variants"]:
        number = variant["id"]
        variant["_setup"] = play["line"]["setup"]
        variant["_punch"] = play["line"]["punch"]
        garment = variant["garment"].lower()
        clusters = clusters_by_variant[number]
        try:
            canvas, placed, sizes = render_variant(
                variant, roster, config, provenance)
        except VariantRejected as err:
            rejected.append({"id": number, "reason": str(err)})
            write_spec_sheets(out_dir, number, variant, [], clusters,
                              None, None, play["named_feeling"],
                              str(err))
            full_tiles.append({"number": number, "image": None,
                               "note": "REJECTED"})
            squint_tiles.append({"number": number, "image": None,
                                 "note": "REJECTED"})
            variant_reports.append({"variant": number,
                                    "rejected": str(err)})
            continue
        full_path = os.path.join(out_dir, FULL_NAME_FMT % number)
        canvas.save(full_path)                              # lossless
        squint = canvas.resize((SQUINT_W, SQUINT_H), RESAMPLE)  # T5
        squint_path = os.path.join(out_dir, SQUINT_NAME_FMT % number)
        squint.save(squint_path)
        # The bytes on disk, hashed after the final write. This is what
        # makes a hand-edited PNG detectable: nothing else in the fleet
        # could tell a forge render from a file someone painted over.
        render_sha256 = {"full": hash_file(full_path),
                         "squint": hash_file(squint_path)}
        renders.append({"variant": number,
                        "file": FULL_NAME_FMT % number,
                        "sha256": render_sha256["full"]})
        renders.append({"variant": number,
                        "file": SQUINT_NAME_FMT % number,
                        "sha256": render_sha256["squint"]})
        gates = run_gates(variant, full_path, placed)       # W9
        failed = gates_failed(gates)
        if failed:
            gate_fails.append(number)
        spec = write_spec_sheets(out_dir, number, variant, placed,
                                 clusters, sizes, gates,
                                 play["named_feeling"], None,
                                 render_sha256)
        variant_reports.append(spec)
        full_tiles.append({
            "number": number,
            "image": garment_tile(canvas, garment,
                                  (CONTACT_TILE_W, CONTACT_TILE_H)),
            "badge": "GATE FAIL" if failed else None})
        squint_tiles.append({
            "number": number,
            "image": garment_tile(squint, garment,
                                  (SQUINT_W, SQUINT_H)),
            "badge": "FAIL" if failed else None})
        squint.close()
        canvas.close()
        rendered += 1
    fulls_sheet_path = os.path.join(out_dir, CONTACT_FULLS_NAME)
    build_contact_sheet(full_tiles, fulls_sheet_path)
    squint_sheet_tiles = [
        {"number": t["number"],
         "image": (t["image"].resize((SQUINT_W, SQUINT_H), RESAMPLE)
                   if t["image"] else None),
         "badge": t.get("badge"), "note": t.get("note")}
        for t in squint_tiles]
    for tile in squint_tiles:
        if tile["image"]:
            tile["image"].close()
    sheet_w, sheet_h = SQUINT_W, SQUINT_H
    sheet = Image.new("RGB", (sheet_w * len(squint_sheet_tiles),
                              sheet_h), (230, 230, 230))
    font = _sheet_font()
    for index, tile in enumerate(squint_sheet_tiles):
        x = index * sheet_w
        if tile["image"] is not None:
            sheet.paste(tile["image"], (x, 0))
            tile["image"].close()
        draw = ImageDraw.Draw(sheet)
        _label(draw, (x + 6, 4), str(tile["number"]), (200, 30, 30),
               font)
        if tile.get("badge"):
            _label(draw, (x + 6, sheet_h - 42), tile["badge"],
                   FAIL_BADGE_COLOR[:3], font)
    squints_sheet_path = os.path.join(out_dir, CONTACT_SQUINTS_NAME)
    sheet.save(squints_sheet_path)
    sheet.close()
    # The contact sheets are things Khai LOOKS AT, so they are renders
    # too (Fable ruling, 2026-09-06) — and a raw out_dir should be able
    # to pass pack_check clean. They belong to no single variant, so
    # their variant is null.
    for name, sheet_path in ((CONTACT_FULLS_NAME, fulls_sheet_path),
                             (CONTACT_SQUINTS_NAME,
                              squints_sheet_path)):
        renders.append({"variant": None, "file": name,
                        "sha256": hash_file(sheet_path)})
    exit_code = (EXIT_FINDINGS if (rejected or gate_fails)
                 else EXIT_CLEAN)
    return {
        "tool": TOOL_NAME,
        "play_id": play["play_id"],
        "named_feeling": play["named_feeling"],
        "variants_total": len(play["variants"]),
        "rendered": rendered,
        "rejected": rejected,
        "gate_fails": sorted(gate_fails),
        "refusals": [],
        "variants": variant_reports,
        "renders": sorted(renders, key=_render_order),
        "play_sha256": hash_file(play_path),
        "out_dir": out_dir,
        "out_dir_mode": out_dir_mode,
        "duration_s": round(time.monotonic() - started, 3),
        "exit_code": exit_code,
    }


def format_report(report):
    """Number order only. Facts only. No ranking language, ever
    (W10) — the test suite greps this output for it."""
    lines = ["play_forge %s  variants=%d rendered=%d  exit=%d"
             % (report["play_id"], report["variants_total"],
                report["rendered"], report["exit_code"]),
             "  feeling: %s" % report["named_feeling"],
             "  out: %s" % report["out_dir"]]
    for spec in report["variants"]:
        number = spec["variant"]
        if spec.get("rejected"):
            lines.append("  variant %d: REJECTED — %s"
                         % (number, spec["rejected"]))
            continue
        gates = " ".join("%s=%s" % (k, v.get("verdict"))
                         for k, v in sorted(spec["gates"].items()))
        lines.append("  variant %d: %s · %s · %s · clusters=%d · %s"
                     % (number, spec["axes"]["color_path"],
                        spec["axes"]["layout"],
                        spec["axes"]["family"],
                        len(spec["color_clusters"]), gates))
    for item in report["rejected"]:
        lines.append("  REJECTED %d: %s" % (item["id"],
                                            item["reason"]))
    lines.append("  selection layer: Khai's eye. Facts only, number "
                 "order only.")
    return "\n".join(lines)


def _main(argv=None):
    _ensure_utf8_console()
    parser = argparse.ArgumentParser(
        prog="play_forge.py",
        description="One play.json in, N gated variants out. "
                    "Structure enforced; taste never judged; no "
                    "ranking, ever.")
    parser.add_argument("play", nargs="?",
                        help="the play.json (D-419 shape)")
    parser.add_argument("--config", default=DEFAULT_CONFIG_NAME)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--overwrite", action="store_true",
                        help="allow re-rendering into a non-empty "
                             "out_dir/<play_id> (bench F4 — refused "
                             "otherwise)")
    parser.add_argument("--explain", action="store_true",
                        help="print the layout/family registries and "
                             "their hierarchy rules")
    args = parser.parse_args(argv)
    if args.explain:
        for layout in play_schema.LAYOUTS:
            print("layout %-13s %s" % (layout,
                                       LAYOUT_SPECS[layout]["doc"]))
        for family in play_schema.FAMILIES:
            print("family %-13s %s" % (family, FAMILY_DOCS[family]))
        return EXIT_CLEAN
    report = None
    try:
        if not args.play:
            raise ForgeError("a play.json path is required")
        config = load_config(args.config)
        report = run_forge(config, args.play,
                           overwrite=args.overwrite)
    except ForgeError as err:
        report = {"tool": TOOL_NAME, "play_id": None,
                  "variants_total": 0, "rendered": 0, "rejected": [],
                  "gate_fails": [],
                  "refusals": [{"kind": err.kind,
                                "reason": str(err)}],
                  "exit_code": EXIT_ERROR}
        append_receipt(report)
        if args.json:
            print(json.dumps(report, sort_keys=True,
                             ensure_ascii=False))
        else:
            print("REFUSED (%s): %s" % (err.kind, err),
                  file=sys.stderr)
        return EXIT_ERROR
    append_receipt(report)
    if args.json:
        print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    else:
        print(format_report(report))
    return report["exit_code"]


def main(argv=None):
    """CRASH FLOOR. A bare traceback exits 1, and this tool's contract
    reads 1 as "rendered with findings" — so without this guard a
    crash and a good run are the same integer to gate_run and to any
    wrapper. SystemExit and KeyboardInterrupt are NOT caught: argparse
    owns exit 2 for a bad flag and must stay untouched."""
    try:
        return _main(argv)
    except Exception as err:
        report = {"tool": TOOL_NAME, "exit_code": EXIT_ERROR,
                  "refusals": [{"kind": "CRASH",
                                "reason": "%s: %s"
                                          % (type(err).__name__, err)}]}
        try:
            append_receipt(report)
        except Exception:
            pass                      # a receipt must never mask this
        source = sys.argv[1:] if argv is None else list(argv)
        if "--json" in source:
            print(json.dumps(report, sort_keys=True,
                             ensure_ascii=False))
        else:
            print("CRASH (%s): %s" % (type(err).__name__, err),
                  file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
