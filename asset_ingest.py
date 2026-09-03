#!/usr/bin/env python3
"""asset_ingest.py — CF asset intake: catalogued, thumbnailed,
split-proposed, indexed. No hands. (MC FLEET B3, court riders Fable
2026-09-01; built 2026-09-02. Row format + play sample filed D-419.)

A downloaded CF folder or zip goes in; the tool inventories formats,
converts EPS/AI/PDF (and SVG, via Inkscape) to lossless PNG at >=
CONVERT_TARGET_PX on the longest side, detects bundle sheets and
PROPOSES a split with a numbered contact sheet, and REFUSES to catalog
a single piece until a human confirms the split (W1: connected
components is a proposal, never a decision — the real
Mailbox-SVG-835842 sheet gave 25 components for 9 true mailboxes).
On --confirm it saves + thumbnails each confirmed piece, appends an
ASSET_INDEX.md row that passes asset_index_lint BEFORE it is written
(W9), and records sha256 + CF product id + ingest date in the sidecar
ASSET_INDEX.hashes.json keyed by the row's path cell (W8 — the human
table stays exactly 7 columns, forever).

Licensing (W2): pixel format is a HINT, never a license verdict.
No-alpha / fully-opaque / identical-corner / JPEG-only inputs are held
NEEDS_HUMAN with reasons. The ONLY hard refusal is
NOT_LICENSED_ASSET: no license record resolvable for the product id.

Scope cuts: NO recolours at ingest (W5 — recolor.py ships the shared
helper for B2's render time; nothing here calls it). CF assets are
never committed (W10): everything lands under the configured
assets_dir, vault-side.

Runs (dry by default where a choice exists):
    asset_ingest.py <folder-or-zip>              inventory/convert/propose
    asset_ingest.py <folder> --confirm 1,3,5     catalog confirmed pieces
    asset_ingest.py --backfill [--apply]         sidecar entries for
                                                 existing rows (proposal
                                                 by default; W8)

Exit codes:
    0 = clean / nothing to do
    1 = proposals emitted, files held NEEDS_HUMAN, duplicate-stem
        siblings skipped (F9a), pieces cataloged, or backfill entries
        proposed/applied
    2 = tool or input error, and every refusal: NOT_LICENSED_ASSET,
        duplicate product id without --reingest, bad config/flags,
        unreadable sidecar or proposal

Dependencies: Pillow (the fleet already carries it via thumb_check;
flagged in the build report per D-394). Converters (Ghostscript,
Inkscape) are PROBED at startup and reported; a missing converter
makes CANT_CONVERT records, never silent skips (W3).
"""

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

import asset_index_lint as ail

# ═══════════════════════════════════════════════════════════════════════
# RULE DATA.
# ═══════════════════════════════════════════════════════════════════════

TOOL_NAME = "asset_ingest"
BASE_DIR = Path(__file__).resolve().parent
RECEIPTS_NAME = "asset_ingest_receipts.jsonl"   # beside the tool,
                                                # gitignored (W10)

DEFAULT_CONFIG_NAME = "asset_ingest.config.json"
REQUIRED_CONFIG_KEYS = ("index_root", "assets_dir", "license_dir")
KNOWN_CONFIG_KEYS = REQUIRED_CONFIG_KEYS + ("cf_subscription",)

# F3 (court, real shape): CF folders carry NO per-folder record — the
# license is the subscription itself (D-082). A per-folder
# license-record.md stays as an optional OVERRIDE. NOT_LICENSED_ASSET
# only when neither resolves; an EXPIRED subscription holds everything
# NEEDS_HUMAN, never silently licensed.
CF_SUBSCRIPTION_KEYS = ("status", "valid_through", "record_path")
CF_STATUS_LICENSED = "verified"

INDEX_NAME = "ASSET_INDEX.md"
SIDECAR_NAME = "ASSET_INDEX.hashes.json"        # W8: schema lives
SIDECAR_VERSION = 1                              # here, not in the table

LICENSE_RECORD_NAME = "license-record.md"
CF_LICENSE_LITERAL = "CF Subscription, verified"     # D-082, verbatim
PENDING_CELL = "pending"
USED_IN_FMT = "ingested %s — not yet used"

# W6: the CF folder name carries the product id as trailing digits;
# the name is NFC-normalized BEFORE this pattern ever sees it.
PRODUCT_ID_PATTERN = re.compile(r"(\d+)\s*$")

# W3: probe both, report both. Order within a tuple = preference.
GS_CANDIDATES = ("gs", "gswin64c", "gswin32c")
INKSCAPE_CANDIDATES = ("inkscape",)
CONVERTIBLE_EXTS = {          # ext -> converters that can take it,
    ".eps": ("gs", "inkscape"),        # preference order (F4)
    ".ai": ("gs", "inkscape"),
    ".pdf": ("gs", "inkscape"),
    ".svg": ("cairosvg", "inkscape"),  # F4: cairosvg preferred (fleet
                                       # lineage: make_icons.py),
                                       # inkscape is the fallback
}
RASTER_EXTS = (".png", ".jpg", ".jpeg")
JPEG_EXTS = (".jpg", ".jpeg")

# F7: CF bundles ship the same art as .ai/.eps/.pdf/.png side by side
# — converting each proposed the SAME regions three times over. One
# source per filename stem, picked in this order (court priority
# PNG > SVG > PDF > EPS > AI; jpg/jpeg appended last so a preview
# never outranks a master — addition flagged in the build report).
# Losers are recorded SKIPPED_DUPLICATE_STEM, never silently dropped.
# F8 (D-421): the priority is applied AFTER filtering each stem's
# candidates to formats a PROBED converter can handle on this box —
# picking an .svg on a gs-only box turned the whole stem into
# CANT_CONVERT while its .pdf sibling would have converted fine. If
# nothing is convertible, the raw-priority pick proceeds and fails
# loudly as before.
STEM_PRIORITY = (".png", ".svg", ".pdf", ".eps", ".ai",
                 ".jpg", ".jpeg")

CONVERT_TARGET_PX = 4000      # longest side of a converted PNG
CONVERT_PROBE_DPI = 72
CONVERT_TIMEOUT_S = 300

# W4: one piece in memory at a time. 4000x4000 RGBA = 61MB,
# 8000x8000 = 244MB. This cap (~9486x9486, ~343MB RGBA worst case) is
# both handed to Pillow and enforced by _open_image itself, so an
# oversized file is a loud CANT_OPEN, never an OOM or a silent warning.
MAX_IMAGE_PIXELS_CAP = 90_000_000

THUMB_PX = 512                # thumbnail box (longest side)
CONTACT_SHEET_PX = 2000       # contact sheet longest side
BOX_COLOR = (255, 0, 0, 255)
BOX_MERGE_COLOR = (255, 140, 0, 255)   # likely-merge boxes draw orange

# F1: black-on-alpha art is invisible on a transparent sheet — the
# human confirm has to SEE. The sheet composites onto an opaque light
# checkerboard, and boxes/numbers get a white halo so they read over
# dark and light art alike.
CHECKER_TILE_PX = 32
CHECKER_LIGHT = (238, 238, 238)        # #EEE
CHECKER_DARK = (204, 204, 204)         # #CCC
HALO_COLOR = (255, 255, 255, 255)
TEXT_HALO_OFFSETS = ((-2, -2), (-2, 0), (-2, 2), (0, -2), (0, 2),
                     (2, -2), (2, 0), (2, 2), (-1, -1), (-1, 1),
                     (1, -1), (1, 1))
NUMBER_FONT_PX = 24           # the human reads these numbers to type
                              # --confirm ids; tiny digits fail F1

PROPOSAL_VERSION = 2          # v2: proposals carry a seed pixel so
                              # confirm can mask-crop (F2); older
                              # proposal files must be re-ingested

MISSING_FILE_MARK = "MISSING_FILE"     # F6: backfill never records a
                                       # null hash

DEFAULT_ALPHA_THRESHOLD = 8   # a > threshold is "ink"; anti-aliased
                              # fringes below it never spawn crumbs
DEFAULT_MIN_SIZE = 24         # px, bbox longest side; smaller = crumb
DEFAULT_GAP_CLOSE = 0         # px of dilation joining gappy pieces
ERODE_PROBE_PX = 2            # W1 likely-merge probe: erode this much;
LIKELY_MERGE_MIN_PART = 0.2   # >=2 surviving parts this big -> flagged

PROPOSAL_NAME = "split_proposal.json"
CONTACT_SHEET_FMT = "contact_sheet_%s.png"
PIECE_NAME_FMT = "piece_%02d.png"
THUMB_NAME_FMT = "piece_%02d_thumb.png"
# Fable 2026-09-02: ids joined with "+" on --confirm mean ONE piece
# cut from the MERGED masks of those proposals — outline art that
# components split into loops (a ring and its inner counter) is one
# object to a human. A group's files carry every id it was cut from,
# so the name can never be confused with a single-piece run.
GROUP_JOIN = "+"
GROUP_NAME_FMT = "piece_%s.png"
GROUP_THUMB_NAME_FMT = "piece_%s_thumb.png"
CONVERTED_DIRNAME = "converted"
PIECES_DIRNAME = "pieces"
THUMBS_DIRNAME = "thumbs"
STAGING_DIRNAME = "_ingest_staging"   # zip extraction target

# ── MIGRATION rule data (Fable order 2026-09-02) ──────────────────
# Legacy ASSET_INDEX rows predate the 7-column D-419 shape. The
# mapping is DATA and it FAILS CLOSED: a row shape with no rule here
# is reported UNMIGRATABLE and never rewritten by guesswork.
#
# LEGACY_COLUMN_MAPS[n] lists, for an n-column legacy row, which
# 7-column slot each legacy cell fills (0-based). Slots no legacy
# cell fills get PENDING_CELL.
#
# PROVISIONAL — the 5-column map assumes the table GREW by appending
# (Recolor and Used in are the newest two concepts), so a 5-col row
# is the first five headers. This build cannot see the live file:
# run --migrate WITHOUT --apply and check the proposed rows against
# the real ones before anything is written.
LEGACY_COLUMN_MAPS = {
    5: (0, 1, 2, 3, 4),      # Asset|License|Style|Niche tags|Colors
    6: (0, 1, 2, 3, 4, 5),   # ...plus Recolor
}

# Old asset-cell spellings the backfill parser cannot read. Each
# normalizer is NAMED so the receipt says which one touched a row;
# they only ever reshape the path's spelling, never its identity.
ASSET_PREFIX_STRIPS = ("Merch/Design Assets/", "Merch\\Design Assets\\")

COLUMN_TARGET = ail.COLUMN_COUNT   # 7, from the ONE lint
MIGRATE_BACKUP_FMT = "%s.migrate.%s.bak"

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2

# ═══════════════════════════════════════════════════════════════════════
# END OF RULE DATA.
# ═══════════════════════════════════════════════════════════════════════

Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS_CAP


class ToolError(Exception):
    """Exit-2 problem or refusal. `kind` names the refusal class."""

    def __init__(self, message, kind="ERROR"):
        super().__init__(message)
        self.kind = kind


class ImageTooBig(Exception):
    """A single file over MAX_IMAGE_PIXELS_CAP — per-file CANT_OPEN."""


def _ensure_utf8_console():
    """Fleet copy (D-378/D-380): display-only UTF-8 reconfigure that
    never becomes a crash site."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _open_image(path):
    """The single choke point for opening a file-backed image (W4 —
    the memory test counts concurrency through here). Enforces the
    pixel cap itself."""
    img = Image.open(path)
    if img.width * img.height > MAX_IMAGE_PIXELS_CAP:
        size = (img.width, img.height)
        img.close()
        raise ImageTooBig("%dx%d exceeds MAX_IMAGE_PIXELS_CAP=%d"
                          % (*size, MAX_IMAGE_PIXELS_CAP))
    return img


def hash_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now():
    return datetime.now(timezone.utc)


# ── converters (W3) ────────────────────────────────────────────────────

def probe_converters():
    """Which of Ghostscript / Inkscape / cairosvg exist on this box
    (F4: cairosvg is an import, not a binary). Reported in every
    ingest run's output — a run that finds none says so."""
    found = {"gs": None, "inkscape": None, "cairosvg": None}
    for name in GS_CANDIDATES:
        path = shutil.which(name)
        if path:
            found["gs"] = path
            break
    for name in INKSCAPE_CANDIDATES:
        path = shutil.which(name)
        if path:
            found["inkscape"] = path
            break
    try:
        import cairosvg                     # noqa: fleet lineage
        found["cairosvg"] = cairosvg
    except ImportError:
        pass
    return found


def stem_ext_usable(ext, converters):
    """F8: can THIS box do anything with a file of this format? A
    raster needs no converter; a vector format needs one of its
    probed engines present."""
    engines = CONVERTIBLE_EXTS.get(ext)
    if engines is None:
        return True
    return any(converters.get(engine) for engine in engines)


def converters_summary(converters):
    """JSON-safe view of the probe for reports and receipts."""
    return {"gs": converters.get("gs"),
            "inkscape": converters.get("inkscape"),
            "cairosvg": ("present" if converters.get("cairosvg")
                         else None)}


def _run_subprocess(cmd):
    """Injectable subprocess runner for the converter calls."""
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=CONVERT_TIMEOUT_S)


def _convert_with_gs(gs, src, out_png):
    """Two passes: probe at CONVERT_PROBE_DPI to learn the native
    size, then re-render at the dpi that puts the longest side at
    CONVERT_TARGET_PX. pngalpha keeps transparency; lossless PNG only
    (D-401)."""
    base = [gs, "-dSAFER", "-dBATCH", "-dNOPAUSE", "-dEPSCrop",
            "-sDEVICE=pngalpha"]
    probe = _run_subprocess(base + ["-r%d" % CONVERT_PROBE_DPI,
                                    "-o", out_png, src])
    if probe.returncode != 0 or not os.path.exists(out_png):
        return "ghostscript probe pass failed: %s" % \
            (probe.stderr or probe.stdout or "no output").strip()[:300]
    with _open_image(out_png) as probe_img:
        longest = max(probe_img.size)
    if longest <= 0:
        return "ghostscript probe produced an empty image"
    if longest < CONVERT_TARGET_PX:
        dpi = math.ceil(CONVERT_PROBE_DPI * CONVERT_TARGET_PX / longest)
        final = _run_subprocess(base + ["-r%d" % dpi, "-o", out_png,
                                        src])
        if final.returncode != 0 or not os.path.exists(out_png):
            return "ghostscript final pass (r=%d) failed: %s" % \
                (dpi,
                 (final.stderr or final.stdout or "no output")
                 .strip()[:300])
    return None


def _convert_with_inkscape(inkscape, src, out_png):
    result = _run_subprocess([
        inkscape, src, "--export-type=png",
        "--export-filename=%s" % out_png,
        "--export-width=%d" % CONVERT_TARGET_PX])
    if result.returncode != 0 or not os.path.exists(out_png):
        return "inkscape export failed: %s" % \
            (result.stderr or result.stdout or "no output")\
            .strip()[:300]
    return None


def _convert_with_cairosvg(module, src, out_png):
    """F4: preferred SVG path — cairosvg renders in-process, width
    scaled to the target (aspect preserved)."""
    try:
        module.svg2png(url=src, write_to=out_png,
                       output_width=CONVERT_TARGET_PX)
    except Exception as err:      # cairosvg raises library-specific
        return "cairosvg raised %s: %s" % (type(err).__name__,
                                           str(err)[:300])
    if not os.path.exists(out_png):
        return "cairosvg produced no output file"
    return None


def convert_file(src, out_png, converters):
    """Convert one EPS/AI/PDF/SVG to lossless PNG. Returns
    (engine, None) on success or (None, reason) — the CANT_CONVERT
    reason string (W3: loud, never a skip). F4: the engine that
    handled the file is reported."""
    ext = os.path.splitext(src)[1].lower()
    for engine in CONVERTIBLE_EXTS[ext]:
        handler = converters.get(engine)
        if not handler:
            continue
        try:
            if engine == "gs":
                reason = _convert_with_gs(handler, src, out_png)
            elif engine == "cairosvg":
                reason = _convert_with_cairosvg(handler, src, out_png)
            else:
                reason = _convert_with_inkscape(handler, src, out_png)
        except (subprocess.TimeoutExpired, OSError, ImageTooBig) as err:
            reason = "%s raised %s: %s" % (engine,
                                           type(err).__name__, err)
        if reason is None:
            return engine, None
        last_reason = reason
    available = [e for e in CONVERTIBLE_EXTS[ext] if converters.get(e)]
    if not available:
        summary = converters_summary(converters)
        return None, ("no converter available for %s (needs %s; probe "
                      "found gs=%s inkscape=%s cairosvg=%s)"
                      % (ext, "/".join(CONVERTIBLE_EXTS[ext]),
                         summary["gs"], summary["inkscape"],
                         summary["cairosvg"]))
    return None, last_reason


# ── config / identity ──────────────────────────────────────────────────

def load_config(path):
    """Strict load, fail closed: missing file, bad JSON, unknown key,
    missing key, nonexistent dirs, assets_dir outside index_root — all
    exit 2."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        raise ToolError("config not found: %s (assets_dir is config, "
                        "never hardcoded — copy "
                        "asset_ingest.config.example.json)" % path)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as err:
        raise ToolError("config unreadable: %s (%s)" % (path, err))
    if not isinstance(raw, dict):
        raise ToolError("config must be a JSON object: %s" % path)
    for key in sorted(raw):
        if key not in KNOWN_CONFIG_KEYS:
            raise ToolError("unknown config key %r (known: %s)"
                            % (key, ", ".join(KNOWN_CONFIG_KEYS)))
    for key in REQUIRED_CONFIG_KEYS:
        if key not in raw or not isinstance(raw[key], str) \
                or not raw[key]:
            raise ToolError("config key %r missing or not a non-empty "
                            "string" % key)
    config = {key: os.path.abspath(raw[key])
              for key in REQUIRED_CONFIG_KEYS}
    for key in ("index_root", "license_dir"):
        if not os.path.isdir(config[key]):
            raise ToolError("%s is not a directory: %s"
                            % (key, config[key]))
    try:
        inside = (os.path.commonpath([config["index_root"],
                                      config["assets_dir"]])
                  == config["index_root"])
    except ValueError:
        inside = False
    if not inside:
        raise ToolError("assets_dir must live INSIDE index_root so "
                        "Asset cells can be relative paths "
                        "(assets_dir=%s, index_root=%s)"
                        % (config["assets_dir"], config["index_root"]))
    config["cf_subscription"] = None
    if "cf_subscription" in raw:
        sub = raw["cf_subscription"]
        if not isinstance(sub, dict):
            raise ToolError("cf_subscription must be an object")
        for key in sorted(sub):
            if key not in CF_SUBSCRIPTION_KEYS:
                raise ToolError("unknown cf_subscription key %r "
                                "(known: %s)"
                                % (key,
                                   ", ".join(CF_SUBSCRIPTION_KEYS)))
        for key in CF_SUBSCRIPTION_KEYS:
            if (key not in sub or not isinstance(sub[key], str)
                    or not sub[key]):
                raise ToolError("cf_subscription key %r missing or "
                                "not a non-empty string" % key)
        try:
            valid_through = datetime.strptime(
                sub["valid_through"], "%Y-%m-%d").date()
        except ValueError:
            raise ToolError("cf_subscription.valid_through must be "
                            "YYYY-MM-DD (got %r)"
                            % sub["valid_through"])
        config["cf_subscription"] = {
            "status": sub["status"],
            "valid_through": valid_through,
            "record_path": sub["record_path"],
        }
    return config


def parse_product_id(name):
    """W6: NFC-normalize FIRST, then take the trailing digits. Returns
    the id string or None."""
    nfc = unicodedata.normalize(
        "NFC", os.path.basename(name.rstrip("/\\")).strip())
    match = PRODUCT_ID_PATTERN.search(nfc)
    return match.group(1) if match else None


def resolve_license(input_dir, config, product_id):
    """W2 + F3 (the court's real shape): the license IS the CF
    subscription (D-082). Licensed when the numeric product id parsed
    AND cf_subscription.status is 'verified' AND today is on or
    before valid_through. A per-folder license-record.md is an
    optional OVERRIDE, not a requirement. Returns (state, desc):
    ('LICENSED', ...) | ('EXPIRED', ...) | (None, None). Expired is
    never silently licensed — the caller holds everything NEEDS_HUMAN.
    license_dir is retained in the config contract but no longer
    consulted for resolution."""
    local = os.path.join(input_dir, LICENSE_RECORD_NAME)
    if os.path.isfile(local):
        return "LICENSED", "folder %s (override)" % LICENSE_RECORD_NAME
    sub = config.get("cf_subscription")
    if sub and product_id.isdigit() \
            and sub["status"] == CF_STATUS_LICENSED:
        today = _utc_now().date()
        if today <= sub["valid_through"]:
            return "LICENSED", ("%s (subscription valid through %s, "
                                "record: %s)"
                                % (CF_LICENSE_LITERAL,
                                   sub["valid_through"].isoformat(),
                                   sub["record_path"]))
        return "EXPIRED", ("CF subscription EXPIRED %s (today %s) — "
                           "held NEEDS_HUMAN, never silently licensed"
                           % (sub["valid_through"].isoformat(),
                              today.isoformat()))
    return None, None


# ── sidecar (W8) ───────────────────────────────────────────────────────

def sidecar_path(config):
    return os.path.join(config["index_root"], SIDECAR_NAME)


def index_path(config):
    return os.path.join(config["index_root"], INDEX_NAME)


def load_sidecar(path):
    """Missing sidecar = empty (this tool creates it); an UNREADABLE
    or wrong-shape sidecar = exit 2, no fallback."""
    if not os.path.exists(path):
        return {"version": SIDECAR_VERSION, "tool": TOOL_NAME,
                "entries": {}}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as err:
        raise ToolError("sidecar unreadable: %s (%s) — refusing, no "
                        "empty fallback" % (path, err))
    if (not isinstance(data, dict) or data.get("tool") != TOOL_NAME
            or not isinstance(data.get("entries"), dict)):
        raise ToolError("sidecar at %s was not written by %s — "
                        "refusing" % (path, TOOL_NAME))
    return data


def write_sidecar(path, data):
    tmp = path + ".%s.tmp" % uuid.uuid4().hex
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, sort_keys=True, ensure_ascii=False,
                  indent=1)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def append_index_line(path, line):
    """Append one row, guaranteeing it lands on its own line."""
    with open(path, "r+b") as handle:
        handle.seek(0, os.SEEK_END)
        needs_newline = False
        if handle.tell() > 0:
            handle.seek(-1, os.SEEK_END)
            needs_newline = handle.read(1) != b"\n"
        handle.seek(0, os.SEEK_END)
        if needs_newline:
            handle.write(b"\n")
        handle.write(line.encode("utf-8") + b"\n")


# ── inventory / zip ────────────────────────────────────────────────────

def extract_zip(zip_path, staging_root, findings):
    """Extract a CF zip under _ingest_staging/ with a zip-slip guard.
    Returns the extraction folder."""
    stem = unicodedata.normalize(
        "NFC", os.path.splitext(os.path.basename(zip_path))[0])
    dest = os.path.join(staging_root, stem)
    os.makedirs(dest, exist_ok=True)
    dest_real = os.path.realpath(dest)
    with zipfile.ZipFile(zip_path) as archive:
        for member in sorted(archive.namelist()):
            target = os.path.realpath(os.path.join(dest, member))
            if not (target == dest_real
                    or target.startswith(dest_real + os.sep)):
                findings.append("ZIP_SLIP_SKIPPED: %s escapes the "
                                "extraction dir — not extracted"
                                % member)
                continue
            archive.extract(member, dest)
    return dest


def inventory_folder(folder, counts):
    """Deterministic walk. Returns {ext: [relpaths]}; symlinks are
    counted and skipped before any stat (same discipline as
    vault_backup W4)."""
    by_ext = {}
    for dirpath, dirnames, filenames in os.walk(folder,
                                                followlinks=False):
        dirnames.sort()
        filenames.sort()
        dirnames[:] = [d for d in dirnames
                       if not os.path.islink(os.path.join(dirpath, d))]
        for name in filenames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                counts["symlinks"] += 1
                continue
            ext = os.path.splitext(name)[1].lower()
            rel = os.path.relpath(full, folder).replace(os.sep, "/")
            by_ext.setdefault(ext, []).append(rel)
    return by_ext


# ── preview heuristics (W2) ────────────────────────────────────────────

def preview_reasons(png_path, jpeg_only_folder):
    """Hints that the file is a preview render, not the licensed
    vector's export. Returns a list of reasons; empty = accepted.
    The corner check applies to OPAQUE images only — a transparent
    cut-out's identical transparent corners are normal, not a hint."""
    reasons = []
    if jpeg_only_folder:
        reasons.append("JPEG-only folder (the licensed Headset asset "
                       "is EPS+JPG — format is a hint, not a verdict)")
    img = _open_image(png_path)
    try:
        rgba = img.convert("RGBA")
    finally:
        img.close()
    try:
        alpha = rgba.getchannel("A")
        lo, hi = alpha.getextrema()
        opaque = False
        if lo == 255:
            opaque = True
            reasons.append("alpha channel fully opaque")
        if "A" not in img.getbands() and img.mode not in ("P", "LA"):
            reasons.append("no alpha channel in source")
            opaque = True
        if opaque:
            w, h = rgba.size
            corners = {rgba.getpixel((0, 0)),
                       rgba.getpixel((w - 1, 0)),
                       rgba.getpixel((0, h - 1)),
                       rgba.getpixel((w - 1, h - 1))}
            if len(corners) == 1:
                reasons.append("all four corner pixels identical "
                               "(flat background sheet)")
    finally:
        rgba.close()
    return sorted(set(reasons))


# ── connected components (W1) ──────────────────────────────────────────

def build_mask(alpha, threshold, gap_close):
    """Binary ink mask from an alpha channel: a > threshold, then
    optional dilation so a gappy wreath proposes as one piece."""
    mask = alpha.point(lambda a: 255 if a > threshold else 0)
    if gap_close > 0:
        mask = mask.filter(ImageFilter.MaxFilter(2 * gap_close + 1))
    return mask


def label_components(mask):
    """8-connected component labelling over a binary L-mode mask.
    Returns components sorted by (top, left): [{bbox: [l, t, r, b]
    inclusive, pixels: n}]. Pure Python — fine for gate-size runs;
    every pass touches ONE mask, never a list of open images (W4)."""
    width, height = mask.size
    data = mask.tobytes()
    visited = bytearray(width * height)
    components = []
    for start in range(width * height):
        if not data[start] or visited[start]:
            continue
        stack = [start]
        visited[start] = 1
        pixels = 0
        min_x = max_x = start % width
        min_y = max_y = start // width
        while stack:
            index = stack.pop()
            x = index % width
            y = index // width
            pixels += 1
            if x < min_x:
                min_x = x
            if x > max_x:
                max_x = x
            if y < min_y:
                min_y = y
            if y > max_y:
                max_y = y
            for dy in (-1, 0, 1):
                ny = y + dy
                if not 0 <= ny < height:
                    continue
                row = ny * width
                for dx in (-1, 0, 1):
                    nx = x + dx
                    if not 0 <= nx < width:
                        continue
                    neighbor = row + nx
                    if data[neighbor] and not visited[neighbor]:
                        visited[neighbor] = 1
                        stack.append(neighbor)
        components.append({"bbox": [min_x, min_y, max_x, max_y],
                           "pixels": pixels,
                           "seed": [start % width, start // width]})
    components.sort(key=lambda c: (c["bbox"][1], c["bbox"][0]))
    return components


def flood_membership(mask, seed_xy):
    """F2: the membership map of ONE component — flood the mask from
    its recorded seed pixel. Returns an L image (255 inside the
    component, 0 outside) so confirm can cut by label, not by bbox."""
    width, height = mask.size
    data = mask.tobytes()
    start = seed_xy[1] * width + seed_xy[0]
    if not (0 <= start < width * height) or not data[start]:
        raise ToolError("proposal seed %s does not sit on ink — the "
                        "mask no longer matches the proposal; re-run "
                        "ingest" % (seed_xy,))
    member = bytearray(width * height)
    member[start] = 255
    stack = [start]
    while stack:
        index = stack.pop()
        x = index % width
        y = index // width
        for dy in (-1, 0, 1):
            ny = y + dy
            if not 0 <= ny < height:
                continue
            row = ny * width
            for dx in (-1, 0, 1):
                nx = x + dx
                if not 0 <= nx < width:
                    continue
                neighbor = row + nx
                if data[neighbor] and not member[neighbor]:
                    member[neighbor] = 255
                    stack.append(neighbor)
    return Image.frombytes("L", (width, height), bytes(member))


def checkerboard(size):
    """F1: opaque light checkerboard so black-on-alpha art is visible
    on the contact sheet."""
    board = Image.new("RGB", size, CHECKER_LIGHT)
    draw = ImageDraw.Draw(board)
    for top in range(0, size[1], CHECKER_TILE_PX):
        for left in range(0, size[0], CHECKER_TILE_PX):
            if ((left // CHECKER_TILE_PX)
                    + (top // CHECKER_TILE_PX)) % 2:
                draw.rectangle((left, top,
                                left + CHECKER_TILE_PX - 1,
                                top + CHECKER_TILE_PX - 1),
                               fill=CHECKER_DARK)
    return board.convert("RGBA")


def likely_merge(mask, component):
    """W1 probe for the 2px-overlap failure: erode the component by
    ERODE_PROBE_PX; if it falls apart into >= 2 substantial parts, two
    pieces probably touched. A hint on the proposal, never a
    decision."""
    left, top, right, bottom = component["bbox"]
    sub = mask.crop((left, top, right + 1, bottom + 1))
    eroded = sub.filter(ImageFilter.MinFilter(2 * ERODE_PROBE_PX + 1))
    sub.close()
    parts = label_components(eroded)
    eroded.close()
    total = sum(p["pixels"] for p in parts)
    if total == 0:
        return False
    substantial = [p for p in parts
                   if p["pixels"] >= LIKELY_MERGE_MIN_PART * total]
    return len(substantial) >= 2


def propose_for_png(abs_png, out_dir, params, counts, next_id):
    """Propose a split for one accepted PNG: components over the ink
    mask, numbered contact sheet with every box drawn. Returns
    (source_record, next_id). One file-backed image open at a time."""
    img = _open_image(abs_png)
    try:
        rgba = img.convert("RGBA")
    finally:
        img.close()
    alpha = rgba.getchannel("A")
    sheet_base = rgba.copy()
    rgba.close()
    mask = build_mask(alpha, params["alpha_threshold"],
                      params["gap_close"])
    alpha.close()
    proposals = []
    for component in label_components(mask):
        left, top, right, bottom = component["bbox"]
        if max(right - left + 1, bottom - top + 1) < params["min_size"]:
            counts["crumbs_dropped"] += 1
            continue
        proposals.append({
            "id": next_id,
            "bbox": component["bbox"],
            "pixels": component["pixels"],
            "seed": component["seed"],       # F2: confirm floods from
            "likely_merge": likely_merge(mask, component),  # here
        })
        next_id += 1
    mask.close()
    # contact sheet (W1, F1): art composited onto an OPAQUE light
    # checkerboard — black-on-alpha art must be VISIBLE — with every
    # box and number drawn over a white halo
    original_w = sheet_base.width
    sheet_base.thumbnail((CONTACT_SHEET_PX, CONTACT_SHEET_PX))
    scale = sheet_base.width / original_w if original_w else 1.0
    sheet = Image.alpha_composite(checkerboard(sheet_base.size),
                                  sheet_base)
    sheet_base.close()
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default(NUMBER_FONT_PX)
    except TypeError:          # older Pillow: unsized bitmap font
        font = ImageFont.load_default()
    for proposal in proposals:
        left, top, right, bottom = [v * scale
                                    for v in proposal["bbox"]]
        color = (BOX_MERGE_COLOR if proposal["likely_merge"]
                 else BOX_COLOR)
        draw.rectangle([left - 1, top - 1, right + 1, bottom + 1],
                       outline=HALO_COLOR, width=4)
        draw.rectangle([left, top, right, bottom], outline=color,
                       width=2)
        label = str(proposal["id"])
        for dx, dy in TEXT_HALO_OFFSETS:
            draw.text((left + 5 + dx, top + 5 + dy), label,
                      fill=HALO_COLOR, font=font)
        draw.text((left + 5, top + 5), label, fill=color, font=font)
    stem = os.path.splitext(os.path.basename(abs_png))[0]
    sheet_name = CONTACT_SHEET_FMT % stem
    sheet.convert("RGB").save(os.path.join(out_dir, sheet_name))
    sheet.close()
    counts["proposed"] += len(proposals)
    return {"path": os.path.abspath(abs_png),
            "sha256": hash_file(abs_png),
            "contact_sheet": sheet_name,
            "proposals": proposals}, next_id


# ── receipts ───────────────────────────────────────────────────────────

def append_receipt(report):
    """Gate-receipts pattern: one JSON line per run, EVERY run
    including a refused one (T15). Best-effort — a receipt failure
    must not mask the run's own verdict."""
    receipt = {
        "tool": TOOL_NAME,
        "run": report.get("run", "UNKNOWN"),
        "product_id": report.get("product_id"),
        "exit_code": report.get("exit_code"),
        "counts": report.get("counts", {}),
        "cant_convert": report.get("cant_convert", []),
        "skipped_duplicate_stem": report.get("skipped_duplicate_stem",
                                             []),
        "raster_over_vector": report.get("raster_over_vector", []),
        "findings": report.get("findings", []),
        "migrated": [{"line": i["line"], "section": i["section"]}
                     for i in report.get("proposals", [])],
        "unmigratable": [{"line": i["line"], "detail": i["detail"]}
                         for i in report.get("unmigratable", [])],
        "backup": report.get("backup"),
        "needs_human": [item["file"] for item
                        in report.get("needs_human", [])],
        "refusals": report.get("refusals", []),
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


# ── runs ───────────────────────────────────────────────────────────────

def _new_counts():
    return {"inventoried": 0, "converted": 0, "cant_convert": 0,
            "cant_open": 0, "needs_human": 0, "proposed": 0,
            "crumbs_dropped": 0, "confirmed": 0, "rows_appended": 0,
            "rows_rejected": 0, "sidecar_entries": 0, "symlinks": 0,
            "missing_files": 0, "skipped_duplicate_stem": 0,
            "rows_migrated": 0, "unmigratable": 0}


def product_out_dir(config, product_id):
    return os.path.join(config["assets_dir"], "product-%s" % product_id)


def run_ingest(config, input_path, opts):
    """Inventory, convert, hold or propose. Never catalogs (W1)."""
    started = time.monotonic()
    counts = _new_counts()
    findings = []
    converters = probe_converters()
    if os.path.isdir(input_path):
        folder = input_path
    elif os.path.isfile(input_path) and zipfile.is_zipfile(input_path):
        staging = os.path.join(config["assets_dir"], STAGING_DIRNAME)
        os.makedirs(staging, exist_ok=True)
        folder = extract_zip(input_path, staging, findings)
    else:
        raise ToolError("input is neither a folder nor a zip: %s"
                        % input_path)
    # the extraction folder's name is the zip stem, already NFC — so
    # both shapes parse the id off the folder they actually use
    product_id = parse_product_id(folder)
    if product_id is None:
        raise ToolError("no product id (trailing digits) in the "
                        "NFC-normalized name %r — CF folder names "
                        "carry the id" % os.path.basename(folder),
                        kind="PRODUCT_ID_UNRESOLVED")
    license_state, license_ref = resolve_license(folder, config,
                                                 product_id)
    if license_state is None:
        raise ToolError("no license resolvable for product %s: no %s "
                        "override in the folder and no valid "
                        "cf_subscription in the config (F3)"
                        % (product_id, LICENSE_RECORD_NAME),
                        kind="NOT_LICENSED_ASSET")
    sidecar = load_sidecar(sidecar_path(config))
    already = sorted(path for path, entry in sidecar["entries"].items()
                     if entry.get("product_id") == product_id)
    if already and not opts["reingest"]:
        raise ToolError("product id %s is already ingested (%d sidecar "
                        "entries, first: %s) — re-run with --reingest "
                        "to do it again" % (product_id, len(already),
                                            already[0]),
                        kind="DUPLICATE_PRODUCT_ID")
    by_ext = inventory_folder(folder, counts)
    counts["inventoried"] = sum(len(v) for v in by_ext.values())
    # F7: dedupe same-stem duplicates BEFORE conversion — one source
    # per stem, by STEM_PRIORITY; the rest are receipts, not work.
    # F8: only formats a probed converter can handle compete; the
    # receipt names the winner and why each sibling lost.
    stem_candidates = {}
    for ext in STEM_PRIORITY:
        for rel in by_ext.get(ext, []):
            stem_candidates.setdefault(
                os.path.splitext(rel)[0], []).append((ext, rel))
    prefer_vector = opts.get("prefer_vector", False)
    stem_winner = {}
    vector_sibling = {}
    skipped_duplicate_stem = []
    for stem in sorted(stem_candidates):
        candidates = stem_candidates[stem]   # in priority order
        order = candidates
        if prefer_vector:                    # F9b: per-run override —
            order = ([p for p in candidates  # vectors outrank rasters
                      if p[0] in CONVERTIBLE_EXTS]
                     + [p for p in candidates
                        if p[0] not in CONVERTIBLE_EXTS])
        usable = [pair for pair in order
                  if stem_ext_usable(pair[0], converters)]
        winner_ext, winner_rel = usable[0] if usable else order[0]
        stem_winner[stem] = winner_rel
        if winner_ext not in CONVERTIBLE_EXTS:
            vectors = [rel for ext, rel in candidates
                       if ext in CONVERTIBLE_EXTS]
            if vectors:                      # F9b: floor check later
                vector_sibling[winner_rel] = vectors[0]
        winner_index = order.index((winner_ext, winner_rel))
        for index, (ext, rel) in enumerate(order):
            if rel == winner_rel:
                continue
            if index < winner_index \
                    and not stem_ext_usable(ext, converters):
                reason = ("%s needs %s (absent)"
                          % (ext.lstrip("."),
                             "|".join(CONVERTIBLE_EXTS[ext])))
            elif (prefer_vector and ext not in CONVERTIBLE_EXTS
                    and winner_ext in CONVERTIBLE_EXTS):
                reason = ("--prefer-vector: vector outranks raster "
                          "this run")
            else:
                reason = "lower stem priority than %s" % winner_rel
            skipped_duplicate_stem.append(
                {"file": rel, "kept": winner_rel, "reason": reason})
    counts["skipped_duplicate_stem"] = len(skipped_duplicate_stem)

    def _is_winner(rel):
        return stem_winner.get(os.path.splitext(rel)[0]) == rel

    out_dir = product_out_dir(config, product_id)
    os.makedirs(out_dir, exist_ok=True)
    cant_convert = []
    converted_paths = []
    converted_files = []
    for ext in sorted(CONVERTIBLE_EXTS):
        for rel in by_ext.get(ext, []):
            if not _is_winner(rel):
                continue
            src = os.path.join(folder, *rel.split("/"))
            out_sub = os.path.join(out_dir, CONVERTED_DIRNAME)
            os.makedirs(out_sub, exist_ok=True)
            out_png = os.path.join(
                out_sub,
                os.path.splitext(os.path.basename(rel))[0] + ".png")
            engine, reason = convert_file(src, out_png, converters)
            if reason is None:
                counts["converted"] += 1
                converted_paths.append(out_png)
                converted_files.append({"file": rel,
                                        "converter": engine})
            else:
                counts["cant_convert"] += 1
                cant_convert.append({"file": rel, "reason": reason})
    # Fable cleanup 2026-09-02: when the dedupe's skip reasons say
    # "duplicate" but nothing converted, the receipt must say WHY
    # nothing ran — not leave the reader to infer it
    unconvertible = sorted(
        ext for ext in CONVERTIBLE_EXTS
        if by_ext.get(ext) and not stem_ext_usable(ext, converters))
    if unconvertible and counts["converted"] == 0:
        findings.append("all candidates skipped: no converter for %s "
                        "on this box" % "/".join(unconvertible))
    raster_rels = [rel for ext in RASTER_EXTS
                   for rel in by_ext.get(ext, []) if _is_winner(rel)]
    jpeg_only = bool(raster_rels) and not converted_paths and all(
        os.path.splitext(rel)[1].lower() in JPEG_EXTS
        for rel in raster_rels)
    # F9b: a raster that beat a vector sibling gets its dimensions in
    # the receipt; below the tool's own conversion floor it is HELD —
    # the vector would have delivered 4000px, the png cannot
    raster_over_vector = []
    below_floor = {}
    for rel in sorted(vector_sibling):
        abs_path = os.path.join(folder, *rel.split("/"))
        try:
            with _open_image(abs_path) as dims_img:
                width, height = dims_img.size
        except (ImageTooBig, OSError, Image.DecompressionBombError):
            continue              # the preview loop records CANT_OPEN
        raster_over_vector.append(
            {"file": rel, "width": width, "height": height,
             "vector_sibling": vector_sibling[rel]})
        longest = max(width, height)
        if longest < CONVERT_TARGET_PX:
            below_floor[abs_path] = (
                "RASTER_BELOW_FLOOR: %s %dpx; vector sibling %s "
                "skipped — consider --prefer-vector"
                % (rel, longest, vector_sibling[rel]))
    needs_human = []
    accepted = []
    for candidate in sorted(
            [os.path.join(folder, *rel.split("/"))
             for rel in raster_rels] + converted_paths):
        try:
            reasons = preview_reasons(candidate, jpeg_only)
        except (ImageTooBig, OSError,
                Image.DecompressionBombError) as err:
            counts["cant_open"] += 1
            cant_convert.append({"file": os.path.basename(candidate),
                                 "reason": "CANT_OPEN: %s" % err})
            continue
        if license_state == "EXPIRED":       # F3: hold everything
            reasons = [license_ref] + reasons
        if candidate in below_floor:         # F9b: hold, with the hint
            reasons = [below_floor[candidate]] + reasons
        if reasons:
            counts["needs_human"] += 1
            needs_human.append({"file": os.path.basename(candidate),
                                "reasons": reasons})
        else:
            accepted.append(candidate)
    params = {"alpha_threshold": opts["alpha_threshold"],
              "min_size": opts["min_size"],
              "gap_close": opts["gap_close"]}
    sources = []
    next_id = 1
    for candidate in accepted:
        record, next_id = propose_for_png(candidate, out_dir, params,
                                          counts, next_id)
        sources.append(record)
    proposal = {"tool": TOOL_NAME, "version": PROPOSAL_VERSION,
                "product_id": product_id, "params": params,
                "license": license_ref,
                "created_utc": _utc_now().isoformat(timespec="seconds"),
                "sources": sources}
    with open(os.path.join(out_dir, PROPOSAL_NAME), "w",
              encoding="utf-8") as handle:
        json.dump(proposal, handle, sort_keys=True, ensure_ascii=False,
                  indent=1)
    # F9a: a skipped duplicate is work the gate must see — gate_run
    # reads only the exit code, and a blank raster winning a stem
    # whose siblings were skipped looked like a clean PASS
    busy = (counts["proposed"] or counts["needs_human"]
            or counts["cant_convert"] or counts["cant_open"]
            or counts["skipped_duplicate_stem"])
    return {
        "tool": TOOL_NAME, "run": "INGEST", "product_id": product_id,
        "license": license_ref, "license_state": license_state,
        "converters": converters_summary(converters),
        "converted_files": converted_files,
        "skipped_duplicate_stem": skipped_duplicate_stem,
        "raster_over_vector": raster_over_vector,
        "inventory": {ext: len(v) for ext, v in sorted(by_ext.items())},
        "counts": counts, "cant_convert": cant_convert,
        "needs_human": needs_human,
        "sources": [{"path": s["path"],
                     "contact_sheet": s["contact_sheet"],
                     "proposals": s["proposals"]} for s in sources],
        "out_dir": out_dir, "findings": findings, "refusals": [],
        "note": ("split PROPOSED — nothing is cataloged until "
                 "--confirm (W1)"),
        "duration_s": round(time.monotonic() - started, 3),
        "exit_code": EXIT_FINDINGS if busy else EXIT_CLEAN,
    }


def _parse_confirm_ids(opts, all_ids):
    if opts["confirm_file"]:
        try:
            with open(opts["confirm_file"], "r",
                      encoding="utf-8") as handle:
                text = handle.read()
        except OSError as err:
            raise ToolError("cannot read confirm file: %s" % err)
    else:
        text = opts["confirm"]
    text = text.strip()
    if text.lower() == "all":
        return [(i,) for i in sorted(all_ids)]
    groups = []
    seen = []
    for token in re.split(r"[\s,]+", text):
        if not token:
            continue
        members = []
        for part in token.split(GROUP_JOIN):
            if not part.isdigit():
                raise ToolError(
                    "--confirm takes piece ids like '1,3,5', a group "
                    "like '2%s3%s4', or 'all' (got %r)"
                    % (GROUP_JOIN, GROUP_JOIN, token))
            members.append(int(part))
        unknown = sorted(set(members) - set(all_ids))
        if unknown:
            raise ToolError("confirm ids %s are not in the proposal "
                            "(has %s)" % (unknown, sorted(all_ids)))
        for member in members:
            if member in seen:
                raise ToolError("piece id %d appears twice in "
                                "--confirm — a piece belongs to one "
                                "output, never two" % member)
            seen.append(member)
        groups.append(tuple(sorted(set(members))))
    if not groups:
        raise ToolError("--confirm resolved to zero ids")
    return sorted(groups)


def run_confirm(config, input_path, opts):
    """Catalog human-confirmed pieces: piece PNG + thumbnail + linted
    index row + sidecar entry. One file-backed image open at a time
    (W4)."""
    started = time.monotonic()
    counts = _new_counts()
    product_id = parse_product_id(input_path)
    if product_id is None:
        raise ToolError("no product id in %r" % input_path,
                        kind="PRODUCT_ID_UNRESOLVED")
    out_dir = product_out_dir(config, product_id)
    proposal_file = os.path.join(out_dir, PROPOSAL_NAME)
    try:
        with open(proposal_file, "r", encoding="utf-8") as handle:
            proposal = json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as err:
        raise ToolError("no readable %s for product %s (%s) — run the "
                        "ingest pass first" % (PROPOSAL_NAME,
                                               product_id, err))
    if proposal.get("tool") != TOOL_NAME:
        raise ToolError("proposal at %s was not written by this tool"
                        % proposal_file)
    if proposal.get("version") != PROPOSAL_VERSION:
        raise ToolError("proposal at %s is version %r; this build "
                        "writes v%d proposals (seed-based mask-crop, "
                        "F2) — re-run the ingest pass"
                        % (proposal_file, proposal.get("version"),
                           PROPOSAL_VERSION))
    if not os.path.isfile(index_path(config)):
        raise ToolError("%s missing at %s — this tool never invents "
                        "the human table" % (INDEX_NAME,
                                             index_path(config)))
    id_map = {}
    for source in proposal["sources"]:
        current = hash_file(source["path"])
        if current != source["sha256"]:
            raise ToolError("source changed since the proposal "
                            "(%s) — re-run ingest so the human "
                            "confirms what is actually there"
                            % source["path"])
        for piece in source["proposals"]:
            id_map[piece["id"]] = (source, piece)
    ids = _parse_confirm_ids(opts, id_map.keys())
    sidecar = load_sidecar(sidecar_path(config))
    pieces_dir = os.path.join(out_dir, PIECES_DIRNAME)
    thumbs_dir = os.path.join(out_dir, THUMBS_DIRNAME)
    os.makedirs(pieces_dir, exist_ok=True)
    os.makedirs(thumbs_dir, exist_ok=True)
    today = _utc_now().strftime("%Y-%m-%d")
    params = proposal["params"]
    groups = ids
    id_to_source = {}
    for index, source in enumerate(proposal["sources"]):
        for piece in source["proposals"]:
            id_to_source[piece["id"]] = index
    for group in groups:
        sources_touched = {id_to_source[i] for i in group}
        if len(sources_touched) > 1:
            raise ToolError(
                "group %s spans %d source images — a merged piece is "
                "cut from ONE sheet"
                % (GROUP_JOIN.join(str(i) for i in group),
                   len(sources_touched)))
    rejected = []
    confirmed = []
    for index, source in enumerate(proposal["sources"]):
        wanted = [g for g in groups if id_to_source[g[0]] == index]
        if not wanted:
            continue
        by_id = {p["id"]: p for p in source["proposals"]}
        img = _open_image(source["path"])
        try:
            rgba = img.convert("RGBA")
        finally:
            img.close()
        alpha = rgba.getchannel("A")
        # F2: rebuild the masks the proposal was made from; the cut
        # uses the UN-dilated mask so gap-close never fattens a halo
        dilated = build_mask(alpha, params["alpha_threshold"],
                             params["gap_close"])
        undilated = (dilated if params["gap_close"] == 0
                     else build_mask(alpha,
                                     params["alpha_threshold"], 0))
        alpha.close()
        for group in wanted:
            pieces = [by_id[i] for i in group]
            label = GROUP_JOIN.join("%02d" % i for i in group)
            piece_id = group[0] if len(group) == 1 else label
            left = min(p["bbox"][0] for p in pieces)
            top = min(p["bbox"][1] for p in pieces)
            right = max(p["bbox"][2] for p in pieces)
            bottom = max(p["bbox"][3] for p in pieces)
            box = (left, top, right + 1, bottom + 1)
            # one output from the MERGED masks of every member: the
            # union is what a human means by "these loops are one
            # piece"; the cut still uses the un-dilated mask (F2)
            membership = None
            for piece in pieces:
                member = flood_membership(dilated, piece["seed"])
                if membership is None:
                    membership = member
                else:
                    merged = ImageChops.lighter(membership, member)
                    membership.close()
                    member.close()
                    membership = merged
            cut_mask = (membership if undilated is dilated
                        else ImageChops.darker(membership, undilated))
            crop = rgba.crop(box)
            crop.load()
            piece_alpha = ImageChops.multiply(
                crop.getchannel("A"), cut_mask.crop(box))
            crop.putalpha(piece_alpha)
            if cut_mask is not membership:
                cut_mask.close()
            membership.close()
            if len(group) == 1:
                piece_name = PIECE_NAME_FMT % group[0]
                thumb_name = THUMB_NAME_FMT % group[0]
            else:
                piece_name = GROUP_NAME_FMT % label
                thumb_name = GROUP_THUMB_NAME_FMT % label
            piece_path = os.path.join(pieces_dir, piece_name)
            crop.save(piece_path)
            thumb = crop.copy()
            crop.close()
            thumb.thumbnail((THUMB_PX, THUMB_PX))
            thumb.save(os.path.join(thumbs_dir, thumb_name))
            thumb.close()
            counts["confirmed"] += 1
            rel = os.path.relpath(
                piece_path, config["index_root"]).replace(os.sep, "/")
            cells = ("`%s`" % rel, CF_LICENSE_LITERAL, opts["style"],
                     opts["tags"], opts["colors"],
                     opts["recolor_mode"], USED_IN_FMT % today)
            try:
                row = ail.format_row(cells)
            except ValueError as err:
                counts["rows_rejected"] += 1
                rejected.append({"piece": piece_id,
                                 "reason": str(err)})
                continue
            append_index_line(index_path(config), row)
            counts["rows_appended"] += 1
            sidecar["entries"][rel] = {"sha256": hash_file(piece_path),
                                       "product_id": product_id,
                                       "ingested_utc": today}
            counts["sidecar_entries"] += 1
            confirmed.append({"id": piece_id, "path": rel})
        if undilated is not dilated:
            undilated.close()
        dilated.close()
        rgba.close()
    write_sidecar(sidecar_path(config), sidecar)
    return {
        "tool": TOOL_NAME, "run": "CONFIRM", "product_id": product_id,
        "counts": counts, "confirmed": confirmed,
        "rows_rejected": rejected, "refusals": [],
        "cant_convert": [], "needs_human": [],
        "duration_s": round(time.monotonic() - started, 3),
        "exit_code": (EXIT_FINDINGS if counts["confirmed"]
                      else EXIT_CLEAN),
    }


def normalize_asset_cell(cell):
    """Reshape an old asset-cell spelling into the D-419 shape:
    backtick-quoted, forward slashes, relative to
    'Merch/Design Assets/'. Returns (new_cell, notes). Only the
    SPELLING changes — never which file the row points at."""
    notes = []
    text = cell.strip()
    if text.startswith("`") and text.endswith("`") and len(text) > 1:
        inner = text[1:-1]
    else:
        inner = text
        notes.append("added backticks")
    if "\\" in inner:
        inner = inner.replace("\\", "/")
        notes.append("backslashes to forward slashes")
    for prefix in ASSET_PREFIX_STRIPS:
        normalized_prefix = prefix.replace("\\", "/")
        if inner.startswith(normalized_prefix):
            inner = inner[len(normalized_prefix):]
            notes.append("stripped the %r prefix"
                         % normalized_prefix)
            break
    if inner.startswith("/"):
        inner = inner.lstrip("/")
        notes.append("made the path relative")
    inner = inner.strip()
    return "`%s`" % inner, notes


def _section_of(lines, index):
    """Nearest preceding markdown heading — the receipt names it so a
    human can find the row without counting lines."""
    for number in range(index, -1, -1):
        stripped = lines[number].strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return "(no section heading)"


def migrate_line(line):
    """One content row -> (new_line, kind, detail). kind is OK (already
    valid, untouched), MIGRATED, or UNMIGRATABLE. Pure: no writes, no
    guessing — a shape with no rule comes back UNMIGRATABLE."""
    if not ail.lint_row(line):
        return line, "OK", "already the 7-column D-419 shape"
    cells = ail.split_cells(line)
    if cells is None:
        return line, "UNMIGRATABLE", "not a table row"
    notes = []
    if len(cells) == COLUMN_TARGET:
        new_cells = list(cells)
    else:
        mapping = LEGACY_COLUMN_MAPS.get(len(cells))
        if mapping is None:
            return (line, "UNMIGRATABLE",
                    "%d columns, and no LEGACY_COLUMN_MAPS rule for "
                    "that shape — refusing to guess" % len(cells))
        new_cells = [PENDING_CELL] * COLUMN_TARGET
        for position, slot in enumerate(mapping):
            new_cells[slot] = cells[position]
        notes.append("%d columns -> %d (slots %s filled, the rest "
                     "%r)" % (len(cells), COLUMN_TARGET,
                              list(mapping), PENDING_CELL))
    asset_cell, asset_notes = normalize_asset_cell(new_cells[0])
    if asset_cell != new_cells[0]:
        new_cells[0] = asset_cell
        notes.extend(asset_notes)
    new_cells = [cell if cell.strip() else PENDING_CELL
                 for cell in new_cells]
    try:
        new_line = ail.format_row(new_cells)      # W9: lint or bust
    except ValueError as err:
        return line, "UNMIGRATABLE", str(err)
    if not notes:
        notes.append("cells unchanged; row reformatted to the "
                     "canonical spacing")
    return new_line, "MIGRATED", "; ".join(notes)


def run_migrate(config, opts):
    """Bring legacy ASSET_INDEX rows to the 7-column D-419 shape.
    Dry-run default; --apply writes after a verified backup. Rows
    that are already valid are byte-faithful — untouched, not
    reformatted."""
    started = time.monotonic()
    counts = _new_counts()
    idx = index_path(config)
    if not os.path.isfile(idx):
        raise ToolError("%s missing at %s" % (INDEX_NAME, idx))
    with open(idx, "r", encoding="utf-8") as handle:
        original = handle.read()
    lines = original.split("\n")
    proposals = []
    unmigratable = []
    new_lines = list(lines)
    for number, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        if ail.is_separator_row(line) or ail.is_header_row(line):
            continue
        new_line, kind, detail = migrate_line(line)
        if kind == "OK":
            continue
        record = {"line": number + 1,
                  "section": _section_of(lines, number),
                  "before": line, "after": new_line,
                  "detail": detail}
        if kind == "UNMIGRATABLE":
            unmigratable.append(record)
            counts["unmigratable"] += 1
            continue
        proposals.append(record)
        new_lines[number] = new_line
        counts["rows_migrated"] += 1
    applied = False
    backup_path = None
    if proposals and opts["apply"]:
        stamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
        backup_path = MIGRATE_BACKUP_FMT % (idx, stamp)
        with open(backup_path, "w", encoding="utf-8",
                  newline="") as handle:
            handle.write(original)
            handle.flush()
            os.fsync(handle.fileno())
        if hash_file(backup_path) != hashlib.sha256(
                original.encode("utf-8")).hexdigest():
            raise ToolError("backup at %s does not match the file it "
                            "copied — refusing to write"
                            % backup_path)
        payload = "\n".join(new_lines)
        tmp = idx + ".%s.tmp" % uuid.uuid4().hex
        with open(tmp, "w", encoding="utf-8", newline="") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, idx)
        applied = True
    busy = bool(proposals or unmigratable)
    return {
        "tool": TOOL_NAME, "run": "MIGRATE", "product_id": None,
        "counts": counts, "proposals": proposals,
        "unmigratable": unmigratable, "applied": applied,
        "backup": backup_path, "refusals": [],
        "cant_convert": [], "needs_human": [], "findings": [],
        "note": ("written (backup: %s)" % backup_path if applied else
                 "dry-run — nothing written; --apply writes after a "
                 "verified backup"),
        "duration_s": round(time.monotonic() - started, 3),
        "exit_code": EXIT_FINDINGS if busy else EXIT_CLEAN,
    }


def run_backfill(config, opts):
    """W8: propose sidecar entries for every EXISTING index row that
    lacks one. Dry-run default; --apply writes; only ever ADDS keys."""
    started = time.monotonic()
    counts = _new_counts()
    idx = index_path(config)
    if not os.path.isfile(idx):
        raise ToolError("%s missing at %s" % (INDEX_NAME, idx))
    with open(idx, "r", encoding="utf-8") as handle:
        lines = handle.read().split("\n")
    sidecar = load_sidecar(sidecar_path(config))
    proposals = {}
    bad_rows = []
    for number, line in enumerate(lines, start=1):
        if not line.strip().startswith("|"):
            continue
        if ail.is_separator_row(line) or ail.is_header_row(line):
            continue
        findings = ail.lint_row(line)
        if findings:
            bad_rows.append({"line": number, "findings": findings})
            continue
        rel = ail.asset_path(line)
        if rel in sidecar["entries"] or rel in proposals:
            continue
        abs_path = os.path.join(config["index_root"],
                                *rel.split("/"))
        entry = {"product_id": (parse_product_id(
                     os.path.dirname(rel) or rel) or "UNKNOWN"),
                 "ingested_utc": _utc_now().strftime("%Y-%m-%d")}
        if os.path.isfile(abs_path):
            entry["sha256"] = hash_file(abs_path)
        else:
            # F6: never a null hash — the missing file is recorded
            # loudly and counted
            entry["sha256"] = MISSING_FILE_MARK
            entry["note"] = "backfill: file not found under index_root"
            counts["missing_files"] += 1
        proposals[rel] = entry
    applied = False
    if proposals and opts["apply"]:
        sidecar["entries"].update(proposals)
        write_sidecar(sidecar_path(config), sidecar)
        applied = True
    counts["sidecar_entries"] = len(proposals)
    return {
        "tool": TOOL_NAME, "run": "BACKFILL", "product_id": None,
        "counts": counts, "proposed_entries": proposals,
        "bad_rows": bad_rows, "applied": applied, "refusals": [],
        "cant_convert": [], "needs_human": [],
        "note": ("written" if applied else
                 "dry-run — nothing written; --apply writes "
                 "(Sonnet applies)"),
        "duration_s": round(time.monotonic() - started, 3),
        "exit_code": (EXIT_FINDINGS if proposals or bad_rows
                      else EXIT_CLEAN),
    }


# ── output (one dict, two renderings) ──────────────────────────────────

def format_report(report):
    lines = ["asset_ingest %s  product=%s  exit=%d"
             % (report["run"], report.get("product_id"),
                report["exit_code"])]
    if "converters" in report:
        lines.append("  converters: gs=%s inkscape=%s cairosvg=%s "
                     "(W3 probe)"
                     % (report["converters"]["gs"],
                        report["converters"]["inkscape"],
                        report["converters"]["cairosvg"]))
    for item in report.get("skipped_duplicate_stem", []):
        lines.append("  SKIPPED_DUPLICATE_STEM: %s (kept %s — %s)"
                     % (item["file"], item["kept"], item["reason"]))
    for item in report.get("raster_over_vector", []):
        lines.append("  RASTER_OVER_VECTOR: %s %dx%d (vector sibling "
                     "%s skipped)"
                     % (item["file"], item["width"], item["height"],
                        item["vector_sibling"]))
    for item in report.get("converted_files", []):
        lines.append("  CONVERTED: %s via %s"
                     % (item["file"], item["converter"]))
    if report.get("license"):
        lines.append("  license: %s" % report["license"])
    if report.get("inventory"):
        lines.append("  inventory: " + " ".join(
            "%s=%d" % (ext or "(none)", n)
            for ext, n in report["inventory"].items()))
    for item in report.get("cant_convert", []):
        lines.append("  CANT_CONVERT: %s — %s"
                     % (item["file"], item["reason"]))
    for item in report.get("needs_human", []):
        lines.append("  NEEDS_HUMAN: %s — %s"
                     % (item["file"], "; ".join(item["reasons"])))
    for source in report.get("sources", []):
        lines.append("  source %s -> %d proposal(s), sheet %s"
                     % (os.path.basename(source["path"]),
                        len(source["proposals"]),
                        source["contact_sheet"]))
        for piece in source["proposals"]:
            lines.append("    #%d bbox=%s px=%d%s"
                         % (piece["id"], piece["bbox"],
                            piece["pixels"],
                            "  LIKELY-MERGE" if piece["likely_merge"]
                            else ""))
    for item in report.get("confirmed", []):
        lines.append("  CATALOGED #%s -> %s"
                     % (item["id"], item["path"]))
    for item in report.get("rows_rejected", []):
        lines.append("  ROW REJECTED (never written): piece %s — %s"
                     % (item["piece"], item["reason"]))
    if report["run"] == "MIGRATE":
        for item in report["proposals"]:
            lines.append("  MIGRATE line %d [%s]: %s"
                         % (item["line"], item["section"],
                            item["detail"]))
            lines.append("    - %s" % item["before"])
            lines.append("    + %s" % item["after"])
        for item in report["unmigratable"]:
            lines.append("  UNMIGRATABLE line %d [%s]: %s"
                         % (item["line"], item["section"],
                            item["detail"]))
            lines.append("    - %s" % item["before"])
    if report["run"] == "BACKFILL":
        for rel in sorted(report["proposed_entries"]):
            lines.append("  BACKFILL %s: %s" %
                         ("+ " + rel,
                          report["proposed_entries"][rel]["sha256"]))
        for bad in report["bad_rows"]:
            lines.append("  BAD ROW line %d: %s"
                         % (bad["line"], "; ".join(bad["findings"])))
    for finding in report.get("findings", []):
        lines.append("  FINDING: %s" % finding)
    if report.get("note"):
        lines.append("  NOTE: %s" % report["note"])
    counts = report["counts"]
    lines.append("  " + " ".join("%s=%s" % (k, counts[k])
                                 for k in sorted(counts)))
    return "\n".join(lines)


def main(argv=None):
    _ensure_utf8_console()
    parser = argparse.ArgumentParser(
        prog="asset_ingest.py",
        description="CF asset intake: inventory, convert, propose a "
                    "split (never auto-catalog), confirm, index, "
                    "sidecar.")
    parser.add_argument("input", nargs="?",
                        help="CF folder or zip (omit for --backfill)")
    parser.add_argument("--config", default=DEFAULT_CONFIG_NAME)
    parser.add_argument("--confirm", default=None,
                        help="piece ids to catalog: '1,3,5', "
                             "'all', or a group like '2+3+4' — one "
                             "piece cut from those merged masks")
    parser.add_argument("--confirm-file", default=None,
                        help="file holding the ids (same syntax)")
    parser.add_argument("--reingest", action="store_true",
                        help="allow a product id already in the "
                             "sidecar (W7)")
    parser.add_argument("--prefer-vector", action="store_true",
                        help="F9b: vectors outrank rasters in the "
                             "same-stem pick this run (when a probed "
                             "converter can handle them)")
    parser.add_argument("--backfill", action="store_true",
                        help="propose sidecar entries for existing "
                             "index rows (W8)")
    parser.add_argument("--migrate", action="store_true",
                        help="bring legacy ASSET_INDEX rows to the "
                             "7-column D-419 shape (dry-run; "
                             "--apply writes after a backup)")
    parser.add_argument("--apply", action="store_true",
                        help="with --backfill or --migrate: write "
                             "the proposals")
    parser.add_argument("--min-side", type=int, dest="min_side",
                        default=DEFAULT_MIN_SIZE,
                        help="smallest proposal kept: the LONGEST "
                             "SIDE of its bounding box, in px "
                             "(default %(default)s)")
    parser.add_argument("--min-size", type=int, dest="min_side",
                        default=argparse.SUPPRESS,
                        help=argparse.SUPPRESS)   # F5: hidden alias
    parser.add_argument("--gap-close", type=int,
                        default=DEFAULT_GAP_CLOSE)
    parser.add_argument("--alpha-threshold", type=int,
                        default=DEFAULT_ALPHA_THRESHOLD)
    parser.add_argument("--style", default=PENDING_CELL)
    parser.add_argument("--tags", default=PENDING_CELL)
    parser.add_argument("--colors", default=PENDING_CELL)
    parser.add_argument("--recolor-mode", default=PENDING_CELL,
                        help="Recolor column value: flat | tonal "
                             "(default: pending)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    run_kind = "INGEST"
    report = None
    try:
        if args.backfill and args.migrate:
            raise ToolError("--backfill and --migrate are different "
                            "runs — pick one")
        for flag_name, flag in (("--backfill", args.backfill),
                                ("--migrate", args.migrate)):
            if flag and (args.input or args.confirm
                         or args.confirm_file):
                raise ToolError("%s takes no input and no --confirm"
                                % flag_name)
        if args.apply and not (args.backfill or args.migrate):
            raise ToolError("--apply only means something with "
                            "--backfill or --migrate")
        if args.confirm and args.confirm_file:
            raise ToolError("--confirm and --confirm-file are one "
                            "mechanism — pick one")
        if not (args.backfill or args.migrate) and not args.input:
            raise ToolError("input folder or zip required (or "
                            "--backfill / --migrate)")
        if not (0 <= args.alpha_threshold <= 255):
            raise ToolError("--alpha-threshold must be 0..255")
        if args.min_side < 1 or args.gap_close < 0:
            raise ToolError("--min-side must be >=1, --gap-close >=0")
        config = load_config(args.config)
        opts = {"confirm": args.confirm,
                "confirm_file": args.confirm_file,
                "reingest": args.reingest, "apply": args.apply,
                "prefer_vector": args.prefer_vector,
                "min_size": args.min_side,
                "gap_close": args.gap_close,
                "alpha_threshold": args.alpha_threshold,
                "style": args.style, "tags": args.tags,
                "colors": args.colors,
                "recolor_mode": args.recolor_mode}
        if args.migrate:
            run_kind = "MIGRATE"
            report = run_migrate(config, opts)
        elif args.backfill:
            run_kind = "BACKFILL"
            report = run_backfill(config, opts)
        elif args.confirm or args.confirm_file:
            run_kind = "CONFIRM"
            report = run_confirm(config, args.input, opts)
        else:
            report = run_ingest(config, args.input, opts)
    except ToolError as err:
        report = {"tool": TOOL_NAME, "run": run_kind,
                  "product_id": None, "counts": _new_counts(),
                  "refusals": [{"kind": err.kind,
                                "reason": str(err)}],
                  "cant_convert": [], "needs_human": [],
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


if __name__ == "__main__":
    sys.exit(main())
