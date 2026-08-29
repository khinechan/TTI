#!/usr/bin/env python3
"""thumb_check.py — thumbnail legibility gate for KCT design PNGs.

color_check.py validates a color LIST and cannot see the art, so it can
only warn that low-contrast pairs "may blob if they touch." This tool
loads the actual PNG and answers: do they touch? Etsy shows shirts as
thumbnails; a design that reads as one blob at thumbnail size is
invisible at the exact moment a buyer decides (brandkit PERCEPTION
LAW 1, the Thumbnail Eye Test).

WHAT IT IS NOT: a file-level simulation. It is not a promise about how
any platform actually renders, resamples, or compresses a thumbnail,
and it does not model DTG ink on fabric.

Exit codes (house style, matches color_check.py / vault_lint.py):
    0 = PASS
    1 = FAIL (a blob failure, or an unknown garment)
    2 = ERROR (missing/unreadable file, palette does not describe the
        file, bad CLI argument)

Windows console encoding is handled: stdout/stderr are reconfigured to
UTF-8 (errors="replace") at startup, so the PALETTE AUDIT banner below
never raises UnicodeEncodeError on a cp1252 console (STATE.md D-378).
Display only -- never touches what gets written to STATE.md/RUNLOG/JSON.

Pillow is the only non-stdlib import. Read-only on the input; the only
write path is --debug-dir.
"""

import argparse
import json
import os
import sys
from collections import Counter

import PIL
from PIL import Image

# Palette, garments, and the contrast math come from color_check.py —
# the source of truth. A palette change lands here automatically and
# test_thumb_check asserts the regression-locked ratios still agree.
from color_check import (
    GARMENTS, PALETTES, OUTLINES, PROVISIONAL_WARNING,
    contrast_ratio, normalize_garment_name, normalize_hex,
)

# ═══════════════════════════════════════════════════════════════════════
# RULE DATA. Logic below references constants only, never a literal.
# ═══════════════════════════════════════════════════════════════════════

THUMB_SIZES = [140, 75, 45]
# 140 = Etsy search tile. 75 = small tile.
# 45  = the DESIGN as rendered inside a 140px SHIRT tile. A print
#       occupies ~25-35% of a mockup's height, so testing the design at
#       140px is roughly 3x kinder than the real shelf. This size is
#       the honest one.

SIZE_LABELS = {45: "design as rendered inside a 140px shirt tile"}

QUANT_TOLERANCE = 40.0
FAIL_INTER = 1.2    # blob FAIL floor
WARN_INTER = 1.5    # blob WARN floor (color_check's MIN_INTER_COLOR)
# VERIFIED: 0 of 10 dark-palette pairs clear 1.5 — best is
# gold/terracotta at 1.46. A single 1.5 FAIL floor bans every two-color
# dark design that touches. Two tiers, or this gate is red on arrival
# and gets bypassed inside a week.

ADJACENCY_MIN_FRAC = 0.085  # of thumb edge; floor 4 px
# VERIFIED: a fixed 12 px is 17% of a full seam at 140px and 32% at
# 75px — same number, double the strictness.

MIN_AREA_PCT = 2.0
# PERCENT OF NON-GARMENT (design/ink) PIXELS, not of the tile. "2% of
# the tile" and "2% of the ink" differ by 4x on a typical centered
# design; an ambiguous denominator is a silently wrong gate. Verdict
# areas use the ADJACENCY map's ink share so blend bands cannot erode
# a color below the floor.

SURVIVAL_WARN_PCT = 60.0
OFF_PALETTE_ERROR_PCT = 40.0   # of the tile, per thumb size
FLAT_STYLE_WARN_PCT = 8.0      # off-palette % of the tile at FULL res

ADJ_CANDIDATE_MIN_PCT = 0.5
# A palette color joins the ADJACENCY candidate set only if it holds at
# least this % of ink pixels at FULL resolution. VERIFIED on this
# machine: at 75px the gold/dusty-blue LANCZOS blend band quantizes to
# SAGE — an intermediate PALETTE color (43 sage px at 75px, 25 at 45px)
# — so even a no-tolerance full-palette map reports ZERO adjacency
# (80 pairs at 140px, 0 at 75px, 0 at 45px). Restricting candidates to
# {garment} ∪ {palette colors actually present at full res} dissolves
# the artifact wall: 80 / 45 / 27 pairs at 140 / 75 / 45. A design with
# real sage at full res keeps sage in the set — legitimate separators
# are preserved; only artifacts dissolve.

DECLARE_TOLERANCE = 8.0
# A color is DECLARED only when it appears NEAR-EXACTLY at full
# resolution (RGB distance <= this) above ADJ_CANDIDATE_MIN_PCT of ink.
# THE PHANTOM-COLOR FIX (Open Flags 2026-08-28, pixel-verified in this
# repo): flattened art with soft/anti-aliased edges puts ink+garment
# and ink+fill blend pixels inside a THIRD palette color's tolerance-40
# bucket — measured: a legal ink+forest design on sport grey put 0.54%
# of ink into the plum bucket and reported "chocolate ink / plum" WARN
# at every size; ink+burgundy crossed into a phantom "burgundy / plum"
# FAIL at 1.03. KCT art is flat exact-hex pools (Style DNA), so a real
# color always has near-exact pixels; blends never do. Declaring from
# strict counts means edge-blend pixels are attributed to their
# neighboring DECLARED colors in the adjacency map, and a legal 2-color
# design can never report a third. The tolerance-40 bucket map is
# unchanged (reporting only) — undeclared buckets carry a caveat.

FULLRES_DISTINCT_CAP = 1 << 20  # getcolors cap before octree fallback

FOOTER_NOTE = (
    "file-level simulation — not a promise of how any platform renders "
    "thumbnails, and not a model of DTG ink on fabric."
)
DENOMINATOR_NOTE = (
    "area floors are % of NON-GARMENT (ink) pixels; off-palette "
    "percentages are % of the tile."
)

# ═══════════════════════════════════════════════════════════════════════
# END OF RULE DATA.
# ═══════════════════════════════════════════════════════════════════════

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ERROR = 2

_RESAMPLE = getattr(getattr(Image, "Resampling", Image), "LANCZOS")


class ToolError(Exception):
    """The tool could not evaluate the file. Exit 2."""


def hex_to_rgb(hex_color):
    body = normalize_hex(hex_color).lstrip("#")
    return tuple(int(body[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#%02X%02X%02X" % rgb


def dist2(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def pixels_rgb(image):
    """Row-major (r, g, b) tuples without the deprecated getdata()."""
    raw = image.tobytes()
    return list(zip(raw[0::3], raw[1::3], raw[2::3]))


# ─────────────────────────── palette wiring ────────────────────────────

def resolve_garment(garment_input):
    """Same semantics and wording as color_check.py: unknown garment is
    a FAIL (exit 1) that lists the known garments."""
    name = normalize_garment_name(garment_input)
    if name not in GARMENTS:
        return None, ("unknown garment '%s' — known garments: %s"
                      % (str(garment_input).strip(), ", ".join(sorted(GARMENTS))))
    return name, None


def palette_for(garment_name):
    """[(name, hex, rgb)] for the garment's class, plus the garment's
    RULED outline (per-garment since D-341/D-342/D-343). When the ruled
    outline aliases a palette color (black's outline is gold), no
    separate outline bucket exists — outline pixels ARE that color; a
    garment with no ruled outline (dark heather) gets none either."""
    spec = GARMENTS[garment_name]
    entries = [(cname, normalize_hex(chex), hex_to_rgb(chex))
               for chex, cname in PALETTES[spec["class"]].items()]
    ruled = OUTLINES.get(garment_name)
    if ruled:
        ohex = normalize_hex(ruled["hex"])
        if ohex not in {h for _n, h, _r in entries}:
            entries.append(("outline", ohex, hex_to_rgb(ohex)))
    return entries


# ───────────────────────── image pipeline stages ───────────────────────

def load_design(path):
    if not os.path.isfile(path):
        raise ToolError("file not found: %s" % path)
    try:
        image = Image.open(path)
        image.load()
        return image.convert("RGBA")
    except Exception as exc:
        raise ToolError("cannot read %s as an image: %s" % (path, exc))


def composite(design, garment_rgb):
    """Opaque garment field under the art, honoring the alpha channel.
    Real art has soft alpha at every edge; those pixels become genuine
    garment/ink blends — expected, not an error."""
    field = Image.new("RGBA", design.size, garment_rgb + (255,))
    return Image.alpha_composite(field, design).convert("RGB")


def color_histogram(image):
    """(count, rgb) pairs at full resolution. Streams via Pillow's
    histogram; falls back to an octree quantize for pathological
    many-color images (reported as approximate)."""
    colors = image.getcolors(maxcolors=FULLRES_DISTINCT_CAP)
    if colors is not None:
        return [(count, rgb) for count, rgb in colors], False
    reduced = image.quantize(colors=256)
    pal = reduced.getpalette()
    approx = []
    for count, idx in reduced.getcolors(256):
        approx.append((count, tuple(pal[idx * 3:idx * 3 + 3])))
    return approx, True


def bucket_of(rgb, buckets, tol2):
    """Tolerance map: nearest bucket within QUANT_TOLERANCE, else None
    (off-palette). Used for REPORTING ONLY."""
    best, best_d = None, None
    for name, _hex, brgb in buckets:
        d = dist2(rgb, brgb)
        if best_d is None or d < best_d:
            best, best_d = name, d
    return best if best_d <= tol2 else None


def full_res_stats(comp, garment_rgb, buckets):
    """Stage 3: quantize at native resolution before any downsampling."""
    histogram, approximate = color_histogram(comp)
    tol2 = QUANT_TOLERANCE * QUANT_TOLERANCE
    strict2 = DECLARE_TOLERANCE * DECLARE_TOLERANCE
    counts = Counter()
    strict_counts = Counter()
    off = Counter()
    total = 0
    all_buckets = [("garment", rgb_to_hex(garment_rgb), garment_rgb)] + buckets
    for count, rgb in histogram:
        total += count
        name = bucket_of(rgb, all_buckets, tol2)
        if name is None:
            counts["off-palette"] += count
            off[rgb] += count
        else:
            counts[name] += count
            if bucket_of(rgb, all_buckets, strict2) == name:
                strict_counts[name] += count
    ink = total - counts["garment"]
    return {
        "total": total, "ink": ink, "counts": counts, "off": off,
        "strict_counts": strict_counts,
        "approximate": approximate,
        "off_pct_tile": 100.0 * counts["off-palette"] / total if total else 0.0,
    }


def adjacency_candidates(full_stats, garment_rgb, buckets):
    """Rider-verified fix: nearest-neighbor with NO tolerance cutoff,
    candidate set restricted to {garment} ∪ {palette colors DECLARED at
    FULL resolution above ADJ_CANDIDATE_MIN_PCT of ink pixels}. Since
    the 2026-08-28 phantom fix, DECLARED means near-exact pixels
    (DECLARE_TOLERANCE) — anti-aliased edge blends can land in a third
    color's tolerance-40 bucket but never in its strict bucket, so
    blends are attributed to their neighboring declared colors and a
    legal 2-color design cannot report a phantom third. See the
    constants' comments for the sage-wall and phantom-plum numbers."""
    cands = [("garment", rgb_to_hex(garment_rgb), garment_rgb)]
    ink = max(1, full_stats["ink"])
    for name, chex, crgb in buckets:
        if 100.0 * full_stats["strict_counts"].get(name, 0) / ink                 >= ADJ_CANDIDATE_MIN_PCT:
            cands.append((name, chex, crgb))
    return cands


def map_thumbnail(thumb, buckets, garment_rgb, adj_cands):
    """Stage 5: TWO MAPS.
    (a) bucket map — nearest within QUANT_TOLERANCE, else off-palette;
        REPORTING ONLY.
    (b) adjacency map — nearest with no tolerance over the restricted
        candidate set; the touching test ONLY.
    ⚠ WHY TWO MAPS: with a tolerance map the LANCZOS blend band along a
    boundary quantizes to off-palette at small sizes, building a
    one-pixel wall that makes touching colors never 4-adjacent — the
    flagship check would PASS the exact design it exists to catch,
    silently, at the smallest size where blobbing matters most. A
    no-tolerance map over the FULL palette still fails: the band can
    quantize to an intermediate PALETTE color (measured: a sage wall
    between gold and dusty blue at 75px). Hence the restricted set.
    Separately, the outline BUCKET gets polluted on dark garments by
    design-vs-GARMENT edge blends passing near #0C0C0C (measured: 0.7%
    outline bucket on an outline-free fixture on one machine) — so an
    outline bucket on a design with no full-res outline is caveated,
    never reported as fact."""
    tol2 = QUANT_TOLERANCE * QUANT_TOLERANCE
    all_buckets = [("garment", rgb_to_hex(garment_rgb), garment_rgb)] + buckets
    data = pixels_rgb(thumb)
    bucket_counts = Counter()
    off = Counter()
    for rgb in data:
        name = bucket_of(rgb, all_buckets, tol2)
        if name is None:
            bucket_counts["off-palette"] += 1
            off[rgb] += 1
        else:
            bucket_counts[name] += 1
    grid = []
    for rgb in data:
        best, best_d = None, None
        for name, _hex, crgb in adj_cands:
            d = dist2(rgb, crgb)
            if best_d is None or d < best_d:
                best, best_d = name, d
        grid.append(best)
    return bucket_counts, off, grid


def count_adjacency(grid, size):
    """4-neighborhood adjacent-pair counts between differing colors,
    with the contact coordinates kept for --debug-dir."""
    pairs = Counter()
    contacts = {}
    w = h = size
    for y in range(h):
        row = y * w
        for x in range(w):
            a = grid[row + x]
            if x + 1 < w:
                b = grid[row + x + 1]
                if a != b:
                    key = tuple(sorted((a, b)))
                    pairs[key] += 1
                    contacts.setdefault(key, []).append((x, y))
            if y + 1 < h:
                b = grid[row + w + x]
                if a != b:
                    key = tuple(sorted((a, b)))
                    pairs[key] += 1
                    contacts.setdefault(key, []).append((x, y))
    return pairs, contacts


# ──────────────────────────── the gate itself ──────────────────────────

def run_gate(path, garment_input):
    """One shared report dict feeds both output modes, so parity is
    structural rather than maintained."""
    garment_name, error = resolve_garment(garment_input)
    if error is not None:
        return {
            "verdict": "FAIL", "exit_code": EXIT_FAIL,
            "violations": [error], "findings": [], "sizes": {},
            "garment": None, "footer": [FOOTER_NOTE],
            "pillow": PIL.__version__,
        }

    spec = GARMENTS[garment_name]
    garment_hex = normalize_hex(spec["hex"])
    garment_rgb = hex_to_rgb(garment_hex)
    buckets = palette_for(garment_name)
    hex_by_name = {name: chex for name, chex, _ in buckets}

    design = load_design(path)
    comp = composite(design, garment_rgb)
    full = full_res_stats(comp, garment_rgb, buckets)
    if full["ink"] == 0:
        raise ToolError("no design pixels detected — the file is entirely "
                        "the garment color or fully transparent; nothing "
                        "to certify")

    findings = []

    if full["off_pct_tile"] > FLAT_STYLE_WARN_PCT:
        findings.append({
            "severity": "WARN", "check": "flat-style", "size": None,
            "name": "full-res",
            "message": "%.1f%% off-palette at full resolution — the design "
                       "may use gradients or blends. Style DNA allows ONE "
                       "flat shadow tone per color, no gradients."
                       % full["off_pct_tile"],
        })

    outline_declared = (
        100.0 * full["strict_counts"].get("outline", 0) / max(1, full["ink"])
        >= ADJ_CANDIDATE_MIN_PCT)
    adj_cands = adjacency_candidates(full, garment_rgb, buckets)

    sizes_report = {}
    for size in THUMB_SIZES:
        thumb = comp.resize((size, size), _RESAMPLE)
        bucket_counts, off, grid = map_thumbnail(
            thumb, buckets, garment_rgb, adj_cands)
        total = size * size

        # Stage 6: off-palette guard — never certify a file the palette
        # does not describe; show what it actually contains.
        off_pct = 100.0 * bucket_counts["off-palette"] / total
        if off_pct > OFF_PALETTE_ERROR_PCT:
            top5 = sorted(off.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            raise ToolError(
                "%.1f%% of the %dpx tile is off-palette (limit %.0f%%) — "
                "the palette does not describe this file. Top unrecognized "
                "colors: %s"
                % (off_pct, size, OFF_PALETTE_ERROR_PCT,
                   ", ".join("%s ×%d" % (rgb_to_hex(rgb), n)
                             for rgb, n in top5)))

        adj_counts = Counter(grid)
        ink_adj = total - adj_counts.get("garment", 0)
        pairs, contacts = count_adjacency(grid, size)
        touch_min = max(4, round(size * ADJACENCY_MIN_FRAC))

        pair_rows = []
        for (a, b), touch in sorted(pairs.items()):
            if "garment" in (a, b) or touch < touch_min:
                continue
            ratio = contrast_ratio(hex_by_name[a], hex_by_name[b])
            area_a = 100.0 * adj_counts[a] / max(1, ink_adj)
            area_b = 100.0 * adj_counts[b] / max(1, ink_adj)
            row = {"a": a, "b": b, "ratio": round(ratio, 2), "touch": touch,
                   "area_a": round(area_a, 1), "area_b": round(area_b, 1),
                   "touch_min": touch_min}
            if "outline" in (a, b):
                # Invisibility against the garment is the outline's job
                # (D-311); it is exempt from blob verdicts.
                row["verdict"] = "EXEMPT (outline)"
            elif ratio < FAIL_INTER and area_a >= MIN_AREA_PCT and area_b >= MIN_AREA_PCT:
                row["verdict"] = "FAIL"
                findings.append({
                    "severity": "FAIL", "check": "blob", "size": size,
                    "name": "%s / %s" % (a, b),
                    "message": "%s / %s blob at %dpx: ratio %.2f:1 (< %.1f "
                               "floor), %d adjacent pairs (min %d), areas "
                               "%.1f%% / %.1f%% of ink (both ≥ %.1f%% floor)"
                               % (a, b, size, ratio, FAIL_INTER, touch,
                                  touch_min, area_a, area_b, MIN_AREA_PCT),
                })
            elif ratio < WARN_INTER and area_a >= MIN_AREA_PCT and area_b >= MIN_AREA_PCT:
                row["verdict"] = "WARN (%.1f-%.1f band)" % (FAIL_INTER, WARN_INTER)
                findings.append({
                    "severity": "WARN", "check": "blob-band", "size": size,
                    "name": "%s / %s" % (a, b),
                    "message": "%s / %s at %dpx: ratio %.2f:1 sits in the "
                               "%.1f-%.1f band, %d adjacent pairs, areas "
                               "%.1f%% / %.1f%% of ink"
                               % (a, b, size, ratio, FAIL_INTER, WARN_INTER,
                                  touch, area_a, area_b),
                })
            elif ratio < WARN_INTER:
                row["verdict"] = "WARN (accent)"
                findings.append({
                    "severity": "WARN", "check": "blob-accent", "size": size,
                    "name": "%s / %s" % (a, b),
                    "message": "%s / %s at %dpx: ratio %.2f:1 but one side "
                               "is an accent below %.1f%% of ink (%.1f%% / "
                               "%.1f%%) — accents never fail"
                               % (a, b, size, ratio, MIN_AREA_PCT,
                                  area_a, area_b),
                })
            else:
                row["verdict"] = "OK"
            pair_rows.append(row)

        # Stage 9: survival PER COLOR — aggregate coverage hides the
        # outline, the thinnest element in every KCT design and always
        # the first casualty ("confident thick dark-chocolate outlines
        # of even weight").
        survival_rows = []
        declared_names = {n for n, _h, _r in adj_cands}
        for name, chex, _rgb in buckets:
            full_count = full["counts"].get(name, 0)
            if full_count == 0 and name != "outline":
                continue
            if name not in declared_names and not (
                    name == "outline" and outline_declared):
                # An undeclared color's bucket is edge-blend pollution
                # (caveated in the report) — judging its "survival"
                # would be a phantom finding, same disease as the
                # phantom pairs (2026-08-28 fix).
                continue
            if name == "outline" and not outline_declared and full_count == 0:
                continue
            full_cov = full_count / full["total"]
            thumb_cov = bucket_counts.get(name, 0) / total
            survival = 100.0 * thumb_cov / full_cov if full_cov else 0.0
            survival_rows.append({"name": name, "survival": round(survival, 1)})
            if survival < SURVIVAL_WARN_PCT:
                findings.append({
                    "severity": "WARN", "check": "survival", "size": size,
                    "name": name,
                    "message": "thin detail in %s vanishes at %dpx — %.1f%% "
                               "of its full-res coverage survives (floor "
                               "%.0f%%)%s"
                               % (name, size, survival, SURVIVAL_WARN_PCT,
                                  " — losing the outline is a specific "
                                  "brand failure, not a rounding error"
                                  if name == "outline" else ""),
                })

        bucket_rows = [{"name": "garment", "hex": garment_hex,
                        "px": bucket_counts["garment"],
                        "pct_tile": round(100.0 * bucket_counts["garment"] / total, 1),
                        "survival": None, "caveat": None}]
        for name, chex, _rgb in buckets:
            count = bucket_counts.get(name, 0)
            if count == 0 and full["counts"].get(name, 0) == 0:
                continue
            caveat = None
            declared_names = {n for n, _h, _r in adj_cands}
            if count and name not in declared_names:
                caveat = ("blend artifacts — %s has no near-exact pixels "
                          "at full resolution; these are anti-aliased "
                          "edge blends, attributed to declared colors in "
                          "the touching test (2026-08-28 phantom fix)"
                          % name)
            srow = next((s for s in survival_rows if s["name"] == name), None)
            bucket_rows.append({"name": name, "hex": chex, "px": count,
                                "pct_tile": round(100.0 * count / total, 1),
                                "survival": srow["survival"] if srow else None,
                                "caveat": caveat})
        bucket_rows.append({"name": "off-palette", "hex": None,
                            "px": bucket_counts["off-palette"],
                            "pct_tile": round(off_pct, 1),
                            "survival": None, "caveat": None})

        sizes_report[str(size)] = {
            "size": size, "label": SIZE_LABELS.get(size),
            "buckets": bucket_rows, "pairs": pair_rows,
            "ink_px": ink_adj, "touch_min": touch_min,
            "off_pct_tile": round(off_pct, 1),
            "contacts": {("%s|%s" % k): v for k, v in contacts.items()},
        }

    size_order = {s: i for i, s in enumerate(THUMB_SIZES)}
    findings.sort(key=lambda f: (
        0 if f["severity"] == "FAIL" else 1,
        size_order.get(f["size"], -1),
        f["name"]))

    verdict = "FAIL" if any(f["severity"] == "FAIL" for f in findings) else "PASS"
    footer = [FOOTER_NOTE, DENOMINATOR_NOTE]
    provisional = bool(spec["provisional"])
    if provisional:
        footer.append(PROVISIONAL_WARNING.format(garment=garment_name))

    return {
        "verdict": verdict,
        "exit_code": EXIT_FAIL if verdict == "FAIL" else EXIT_PASS,
        "file": path,
        "garment": {"name": garment_name, "hex": garment_hex,
                    "class": spec["class"], "provisional": provisional},
        "pillow": PIL.__version__,
        "full_res": {"width": design.size[0], "height": design.size[1],
                     "off_pct_tile": round(full["off_pct_tile"], 1),
                     "approximate_histogram": full["approximate"],
                     "detected": sorted(n for n, _h, _r in
                                        adjacency_candidates(full, garment_rgb,
                                                             buckets))},
        "outline_declared": outline_declared,
        "violations": [],
        "findings": findings,
        "sizes": sizes_report,
        "footer": footer,
    }


# ───────────────────────────── debug output ────────────────────────────

def write_debug(report, path, garment_input, debug_dir):
    """Writes ONLY inside debug_dir. Never beside the input, never the
    input itself. Annotates each flagged pair's contact region in red."""
    os.makedirs(debug_dir, exist_ok=True)
    garment_name, _ = resolve_garment(garment_input)
    garment_rgb = hex_to_rgb(GARMENTS[garment_name]["hex"])
    comp = composite(load_design(path), garment_rgb)
    stem = os.path.splitext(os.path.basename(path))[0]
    written = []
    flagged = {(f["size"], f["name"]) for f in report["findings"]
               if f["check"].startswith("blob")}
    for key, size_rep in report["sizes"].items():
        size = size_rep["size"]
        thumb = comp.resize((size, size), _RESAMPLE)
        out = os.path.join(debug_dir, "%s_%dpx.png" % (stem, size))
        thumb.save(out)
        written.append(out)
        marks = []
        for pair_key, coords in size_rep["contacts"].items():
            a, b = pair_key.split("|")
            if (size, "%s / %s" % (a, b)) in flagged or \
               (size, "%s / %s" % (b, a)) in flagged:
                marks.extend(coords)
        if marks:
            overlay = thumb.copy()
            px = overlay.load()
            for x, y in marks:
                px[x, y] = (255, 0, 0)
            out = os.path.join(debug_dir, "%s_%dpx_contacts.png" % (stem, size))
            overlay.save(out)
            written.append(out)
    return written


# ───────────────────────────── rendering ───────────────────────────────

def render_human(report):
    out = []
    if report["garment"] is None:
        out.append("══ THUMB CHECK ══")
        out.append("VERDICT: FAIL")
        for violation in report["violations"]:
            out.append("FAIL: %s" % violation)
        out.append("NOTE: %s" % FOOTER_NOTE)
        return "\n".join(out)

    g = report["garment"]
    out.append("══ THUMB CHECK ══ %s -> %s (%s, %s)"
               % (report["file"], g["name"], g["hex"], g["class"]))
    out.append("Pillow %s · full-res %dx%d"
               % (report["pillow"], report["full_res"]["width"],
                  report["full_res"]["height"]))
    flat = ("gradient/blend WARN" if any(
        f["check"] == "flat-style" for f in report["findings"])
        else "flat-style OK")
    out.append("full-res off-palette: %.1f%% of tile  (%s)"
               % (report["full_res"]["off_pct_tile"], flat))
    out.append("adjacency candidates: %s"
               % ", ".join(report["full_res"]["detected"]))

    for key in [str(s) for s in THUMB_SIZES]:
        rep = report["sizes"][key]
        label = " (%s)" % rep["label"] if rep["label"] else ""
        out.append("")
        out.append("── %dpx ──%s" % (rep["size"], label))
        out.append("%-12s %-9s %8s %7s %9s" % ("color", "hex", "px", "%tile", "survival"))
        for row in rep["buckets"]:
            surv = ("%.0f%%" % row["survival"]) if row["survival"] is not None else "--"
            out.append("%-12s %-9s %8s %6.1f%% %9s"
                       % (row["name"], row["hex"] or "--",
                          "{:,}".format(row["px"]), row["pct_tile"], surv))
            if row["caveat"]:
                out.append("             ↳ CAVEAT: %s" % row["caveat"])
        if rep["pairs"]:
            out.append("%-24s %6s %6s  %s" % ("pair", "ratio", "touch", "verdict"))
            for p in rep["pairs"]:
                out.append("%-24s %6.2f %6d  %s"
                           % ("%s / %s" % (p["a"], p["b"]), p["ratio"],
                              p["touch"], p["verdict"]))

    out.append("")
    for f in report["findings"]:
        out.append("%s [%s]: %s" % (f["severity"], f["check"], f["message"]))
    warns = sum(1 for f in report["findings"] if f["severity"] == "WARN")
    fails = sum(1 for f in report["findings"] if f["severity"] == "FAIL")
    if report["verdict"] == "FAIL":
        out.append("VERDICT: FAIL — %d blob failure%s, %d warning%s"
                   % (fails, "" if fails == 1 else "s",
                      warns, "" if warns == 1 else "s"))
    else:
        out.append("VERDICT: PASS%s"
                   % (" with %d warning%s" % (warns, "" if warns == 1 else "s")
                      if warns else ""))
    for note in report["footer"]:
        out.append("NOTE: %s" % note)
    return "\n".join(out)


def render_json(report):
    slim = dict(report)
    slim["sizes"] = {k: {kk: vv for kk, vv in v.items() if kk != "contacts"}
                     for k, v in report["sizes"].items()}
    return json.dumps(slim, indent=2, sort_keys=True)


# ─────────────────────────── auxiliary modes ───────────────────────────

def audit_palette(garment_input, as_json):
    """The tool saying YOUR PALETTE IS THE PROBLEM rather than only THIS
    DESIGN IS. Five colors of near-identical value is a brandkit
    PERCEPTION LAW 2 finding ('contrast beats hue') and no per-design
    gating fixes it. The headline is COMPUTED, never hardcoded."""
    garment_name, error = resolve_garment(garment_input)
    if error is not None:
        if as_json:
            print(json.dumps({"verdict": "FAIL", "exit_code": EXIT_FAIL,
                              "error": error}, indent=2, sort_keys=True))
        else:
            print("FAIL: %s" % error)
        return EXIT_FAIL
    spec = GARMENTS[garment_name]
    names = [(n, h) for h, n in PALETTES[spec["class"]].items()]
    rows = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            (na, ha), (nb, hb) = names[i], names[j]
            ratio = contrast_ratio(ha, hb)
            verdict = ("FAIL if touching" if ratio < FAIL_INTER
                       else "WARN band" if ratio < WARN_INTER else "OK")
            rows.append({"a": na, "b": nb, "ratio": round(ratio, 2),
                         "verdict": verdict})
    rows.sort(key=lambda r: (r["ratio"], r["a"], r["b"]))
    total = len(rows)
    clear_warn = sum(1 for r in rows if r["ratio"] >= WARN_INTER)
    clear_fail = sum(1 for r in rows if r["ratio"] >= FAIL_INTER)
    payload = {
        "garment": garment_name, "class": spec["class"],
        "pairs": rows, "total": total,
        "clear_warn_inter": clear_warn, "clear_fail_inter": clear_fail,
        "warn_inter": WARN_INTER, "fail_inter": FAIL_INTER,
        "provisional": bool(spec["provisional"]),
        "exit_code": EXIT_PASS,
    }
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return EXIT_PASS
    print("══ PALETTE AUDIT ══ %s (%s class)" % (garment_name, spec["class"]))
    print("%d of %d pairs clear WARN_INTER (%.1f); %d of %d clear "
          "FAIL_INTER (%.1f)"
          % (clear_warn, total, WARN_INTER, clear_fail, total, FAIL_INTER))
    for r in rows:
        print("  %-14s / %-14s %5.2f:1  %s" % (r["a"], r["b"], r["ratio"],
                                               r["verdict"]))
    if clear_warn == 0:
        print("HEADLINE: no pair in this palette clears the %.1f blob-warn "
              "floor — the palette, not any single design, is the problem "
              "(PERCEPTION LAW 2: contrast beats hue). A palette change is "
              "a court decision; this tool only reports it." % WARN_INTER)
    if spec["provisional"]:
        print("NOTE: %s" % PROVISIONAL_WARNING.format(garment=garment_name))
    print("NOTE: %s" % FOOTER_NOTE)
    return EXIT_PASS


def render_explain():
    out = ["══ THUMB CHECK — THE CHECKS ══", ""]
    out.append("TWO MAPS (the correctness-critical part):")
    out.append("  bucket map — nearest palette color within QUANT_TOLERANCE "
               "(%.0f), else off-palette. Reporting only." % QUANT_TOLERANCE)
    out.append("  adjacency map — nearest with NO tolerance, candidates "
               "restricted to {garment} ∪ {palette colors above %.1f%% of "
               "ink at FULL res}. Touching test only." % ADJ_CANDIDATE_MIN_PCT)
    out.append("  why: with a tolerance map, the LANCZOS blend band along a "
               "boundary becomes an off-palette one-pixel wall at small "
               "sizes and touching colors are never 4-adjacent — measured: "
               "80 gold/dusty-blue adjacent pairs at 140px, ZERO at 75px. "
               "A no-tolerance FULL-palette map still fails: the band "
               "quantizes to an intermediate palette color (measured: a "
               "43px sage wall at 75px, 25px at 45px). The restricted set "
               "yields 80 / 45 / 27 pairs at 140 / 75 / 45. Real sage at "
               "full res stays in the set — only artifacts dissolve.")
    out.append("")
    out.append("blob verdicts: touching pairs below %.1f FAIL (both sides ≥ "
               "%.1f%% of ink); %.1f-%.1f is a WARN band; accents below the "
               "area floor warn and never fail. Two tiers because 0 of 10 "
               "dark-palette pairs clear %.1f (best: gold/terracotta 1.46) — "
               "a single %.1f floor bans every two-color dark design that "
               "touches and the gate gets bypassed inside a week."
               % (FAIL_INTER, MIN_AREA_PCT, FAIL_INTER, WARN_INTER,
                  WARN_INTER, WARN_INTER))
    out.append("")
    out.append("outline: PER-GARMENT since D-341/D-342/D-343 (black -> "
               "gold #D9A441, aliasing the gold bucket; sport grey -> "
               "#0C0C0C, its own bucket; dark heather unruled). Outline "
               "pairs are exempt from blob verdicts where the bucket "
               "exists. Survival keeps a named outline line: the outline "
               "is the thinnest element in every KCT design and always "
               "the first casualty (measured: 1px lines at full res -> "
               "0.00%% survival at 140 and 75).")
    out.append("")
    out.append("declared colors (the 2026-08-28 phantom fix): a color "
               "joins the adjacency candidate set only when it has "
               "near-exact pixels (distance <= %.0f) at full resolution "
               "above %.1f%% of ink. VERIFIED: flattened art with soft "
               "edges put ink+garment blends inside plum's tolerance-40 "
               "bucket — a legal ink+forest design reported a phantom "
               "'chocolate ink / plum' WARN and ink+burgundy a phantom "
               "'burgundy / plum' FAIL at 1.03. Strict declaration "
               "attributes edge blends to their neighboring declared "
               "colors; undeclared buckets are caveated in the report, "
               "never turned into verdicts."
               % (DECLARE_TOLERANCE, ADJ_CANDIDATE_MIN_PCT))
    out.append("")
    out.append("full-res quantize pass: catches gradients/blends "
               "(Style DNA: one flat shadow tone per color) that "
               "color_check structurally cannot see — it only receives "
               "hexes. Off-palette above %.0f%% of the tile at any thumb "
               "size is exit 2 with the top unrecognized colors: never "
               "certify a file the palette does not describe."
               % OFF_PALETTE_ERROR_PCT)
    out.append("")
    out.append("survival: per color, never aggregate — aggregate coverage "
               "hides the outline completely. Floor %.0f%% of full-res "
               "coverage." % SURVIVAL_WARN_PCT)
    out.append("")
    out.append("--audit-palette: the rule-audit idea from color_check test "
               "18 applied to perception — audit the RULES, not just the "
               "art. Headline computed live, never hardcoded.")
    out.append("")
    out.append("NOTE: %s" % FOOTER_NOTE)
    out.append("NOTE: %s" % DENOMINATOR_NOTE)
    return "\n".join(out)


EPILOG = """\
WHAT THIS IS NOT: a file-level simulation. It is not a promise about how
any platform actually renders, resamples, or compresses a thumbnail, and
it does not model DTG ink on fabric.

exit codes:
  0  PASS
  1  FAIL   a blob failure at any size, or an unknown garment
  2  ERROR  missing/unreadable file, palette does not describe the file

examples:
  thumb_check.py design.png "black"
  thumb_check.py design.png "black" --json
  thumb_check.py design.png "black" --debug-dir out/
  thumb_check.py --audit-palette "black"
  thumb_check.py --explain
"""


def build_parser():
    parser = argparse.ArgumentParser(
        prog="thumb_check.py",
        description="Thumbnail legibility gate: loads the actual PNG and "
                    "answers the question color_check cannot — do the "
                    "low-contrast colors touch?",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image", nargs="?", help="design PNG (RGBA honored)")
    parser.add_argument("garment", nargs="?", help="garment name")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable output; same verdict")
    parser.add_argument("--debug-dir", metavar="DIR",
                        help="write annotated thumbnails into DIR (the only "
                             "write path; never touches the input)")
    parser.add_argument("--audit-palette", metavar="GARMENT",
                        help="print the mutual-contrast matrix for a "
                             "garment's palette")
    parser.add_argument("--explain", action="store_true",
                        help="every check, what it catches, why it exists")
    return parser


def _ensure_utf8_console():
    """Reconfigure stdout/stderr for UTF-8 display, substituting any
    character the console codepage can't render instead of crashing.
    Windows consoles default to the system codepage (cp1252 etc.), not
    UTF-8 -- the PALETTE AUDIT banner below raised UnicodeEncodeError
    there (STATE.md D-378). Display only -- this never touches what
    gets written to STATE.md/RUNLOG/JSON, which stay real UTF-8 bytes
    regardless (same display-vs-stored split as gate_run.py's own W14
    stdout_text/stderr_text decode). No-op if the stream doesn't support
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
            return EXIT_PASS
        if args.audit_palette:
            return audit_palette(args.audit_palette, args.json)
        if not args.image or not args.garment:
            raise ToolError("usage: thumb_check.py IMAGE GARMENT "
                            "(or --audit-palette GARMENT / --explain)")

        report = run_gate(args.image, args.garment)
        if args.debug_dir and report["garment"] is not None:
            report["debug_files"] = write_debug(
                report, args.image, args.garment, args.debug_dir)
        print(render_json(report) if args.json else render_human(report))
        return report["exit_code"]

    except ToolError as exc:
        if args.json:
            print(json.dumps({"verdict": "ERROR", "exit_code": EXIT_ERROR,
                              "error": str(exc)}, indent=2, sort_keys=True))
        else:
            sys.stderr.write("ERROR: %s\n" % exc)
            sys.stderr.write("NOTE: %s\n" % FOOTER_NOTE)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
