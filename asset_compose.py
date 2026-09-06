#!/usr/bin/env python3
"""asset_compose.py — MC FLEET B5. Indexed licensed PIECES + a recipe
JSON -> ONE derived piece, a lint-clean ASSET_INDEX row, a sidecar
entry with structural provenance, and a receipt.

WHAT IT IS NOT: a designer. Every number comes from the recipe and a
missing number is a refusal. There are no defaults, no auto-placement
and no colour decisions anywhere in this file.

    A GREEN RUN MEANS THE RECIPE WAS FOLLOWED, NOT THAT THE PIECE IS
    GOOD. Swap two numbers and every wall still passes.

    asset_compose.py <recipe.json> [--config PATH] [--apply]
                     [--overwrite] [--json] [--explain]
    -> <index_root>/<output.path>  (RGBA, RGB all 0, alpha only)

Dry-run is the default: it does everything except write the piece, the
row and the sidecar entry, and it still writes a receipt.

Walls (each has a test behind it):
  W1  LICENSED SOURCES ONLY. Every source must be an existing FILE row
      carrying exactly ONE path, whose License cell matches a CLOSED
      allowlist after NFC -> strip -> casefold, and whose sidecar
      sha256 verifies against the bytes actually read.
  W2  READ ONCE. Each source's bytes are read exactly once, hashed,
      and decoded from those same bytes (BytesIO). The path is never
      reopened — a file swapped after the check cannot get in.
  W3  SINGLE ALPHA. The output's RGB is forced to 0 on every pixel.
      Colour is a render-time decision (play_forge + recolor), never
      baked into a piece.
  W4  NO TASTE. See the line above in capitals.
  W5  PROVENANCE IS STRUCTURAL. The sidecar entry is written by this
      tool from what it actually read: the recipe hash, and one
      derived_from record per LAYER (the same source used twice gives
      two records) naming the ops applied.
  W6  KIND ROUND TRIP. The Style cell is fed back through
      play_new.infer_kind and must return the recipe's kind. Prose is
      not a mechanism; the round trip is.
  W7  ONE PATH in the Asset cell. Provenance lives in the sidecar.
  W8  COMPONENTS measured with asset_ingest.label_components and
      matched against the recipe's expect_components.
  W9  EDGES. The resample filter is pinned by the recipe; after every
      resample, alpha below canvas.alpha_floor is swept to 0.
  W10 STROKE measured on the OUTPUT with play_forge's own kernel.
      Below the floor is a FINDING (exit 1), not a refusal — the piece
      still writes on --apply and Khai's eye decides.
  W11 BYTES. compress_level comes from the recipe. Two runs are
      byte-identical.
  W12 WRITES. tmp -> fsync -> os.replace; refuse an existing output
      without --overwrite; refuse an output path outside a pieces/ dir.
  W13 CRASH FLOOR, exit 0/1/2, --json parity from one report dict.

Everything this tool does not own is IMPORTED, never retyped: the row
lint and its shape from asset_index_lint, the kind inference from
play_new, the stroke kernel from play_forge, component labelling and
the sidecar reader/writer from asset_ingest. A duplicated rule drifts.

Pillow (image-family tool; W7 court wording 2026-09-02 extended to
asset_compose 2026-09-06). Stdlib otherwise.
"""

import argparse
import hashlib
import io
import json
import os
import sys
import unicodedata
import uuid
from datetime import datetime, timezone

FLEET_IMPORT_ERROR = None
try:
    from PIL import Image, ImageChops, ImageFilter
    import asset_index_lint as ail
    import asset_ingest as ai
    import play_forge as pf
    import play_new as pn
    import play_schema
except BaseException as _err:            # noqa: BLE001 - deliberate
    FLEET_IMPORT_ERROR = "%s: %s" % (type(_err).__name__, _err)

# ═══════════════════════════════════════════════════════════════════════
# RULES ARE DATA.
# Every constant, threshold, key set and message lives here. The logic
# below references these and never a literal. A rule change must never
# touch the math.
# ═══════════════════════════════════════════════════════════════════════

TOOL_NAME = "asset_compose"
RECEIPTS_NAME = "asset_compose_receipts.jsonl"   # beside the tool
DEFAULT_CONFIG_NAME = "asset_compose.config.json"
REQUIRED_CONFIG_KEYS = ("index_root",)
KNOWN_CONFIG_KEYS = REQUIRED_CONFIG_KEYS

RECIPE_SCHEMA = 1

# W1. A CLOSED allowlist of License cells, compared after
# NFC -> strip -> casefold. The CF form is IMPORTED from asset_ingest
# (D-082, verbatim there) rather than retyped here.
#
# THE AI-ROW BASIS STRING IS DELIBERATELY ABSENT. The B5 spec says to
# quote it from the live ASSET_INDEX header note via Sonnet and NOT to
# guess it; it appears nowhere in this repo. Until it lands, an AI row
# refuses NOT_LICENSED_SOURCE — which is what a wall is supposed to do
# with a value it has never been told. Add the verbatim string to this
# tuple and nothing else changes.
LICENSE_ALLOWLIST_VERBATIM = ()      # filled from asset_ingest below

# W7. The 'Used in' placeholder: a compose-verb sibling of
# asset_ingest.USED_IN_FMT, so an empty cell (L4) is impossible and the
# text is never invented per run.
USED_IN_FMT = "composed %s — not yet used"

# W12. An output must land in a pieces/ directory. Composed art is a
# PIECE; nothing else in the index shape expects one anywhere else.
PIECES_DIR_NAME = "pieces"

# W3. The single-alpha output: RGB forced to this on every pixel.
FLAT_RGB = (0, 0, 0)
OUTPUT_MODE = "RGBA"

# Luminance formulae, by name. Never inlined into the thresholding.
LUMINANCE_COEFFS = {
    "rec709": (0.2126, 0.7152, 0.0722),
    "rec601": (0.299, 0.587, 0.114),
}

# LUMINANCE IS 0..1 IN THE RECIPE. Every document in this system — the
# B5 spec, PM's review, Fable's bench script — writes "lum < 0.35", and
# the first build range-checked 0..255 instead. On the real run
# lum_max 0.35 passed every check, matched only pure black, produced an
# EMPTY beanie layer, and the run went GREEN by coincidence. Wrong and
# passing is the worst class of bug this repo has. The scale is applied
# ONCE, inside luminance_band, and nowhere else.
LUMINANCE_SCALE = 255.0

# The CLOSED op registry: op name -> its required parameter names.
# An op not here, or a parameter not listed, refuses.
OP_PARAMS = {
    "ink_layer": ("luminance", "lum_max"),
    "mid_layer": ("luminance", "lum_min", "lum_max"),
    "solid": (),
    "outline_thicken": ("mode", "amount"),
}
OP_OPTIONAL_PARAMS = {
    "ink_layer": ("allow_overlap",),
    "mid_layer": ("allow_overlap",),
    "solid": (),
    "outline_thicken": (),
}
THICKEN_MODES = ("percent", "px")

# outline_thicken grows the alpha by a SQUARE (Chebyshev) radius, which
# is what MaxFilter(2r+1) does — but MaxFilter is O(k^2) and the real
# beanie piece needed r=118: Fable measured MaxFilter(11) at 2.7s and
# MaxFilter(41) at 22.2s on it, so r=118 is about twelve minutes for
# one layer. A square max IS separable, so this dilates by doubling
# steps instead: ~log2(r) rounds of shift-and-lighten per axis. See
# dilate_alpha for the measured equivalence.
DILATE_START_STEP = 1

# W9. Resample filters, by name — pinned by the recipe, never chosen
# here. Measured halo at a>0 vs a>=128 (50 -> 400px, Fable's bench):
# NEAREST 0 · BILINEAR 4 · BICUBIC 4 · LANCZOS 19 px. That halo is the
# reason alpha_floor exists.
RESAMPLE_NAMES = ("NEAREST", "BILINEAR", "BICUBIC", "LANCZOS")

# Placement vocabulary. Nothing else is accepted.
ALIGNS = ("center", "left", "right")
SCALE_MODES = ("px", "width_rel_to_layer")
GAP_EDGES = ("top", "bottom")

# Closed key sets, level by level. No defaults anywhere: a key that is
# required and absent is MISSING_KEY, and a key that is present and
# unknown is UNKNOWN_KEY.
RECIPE_KEYS = ("schema", "output", "canvas", "layers")
OUTPUT_KEYS = ("path", "kind", "style", "niche_tags", "colors",
               "recolor", "expect_components", "compress_level")
CANVAS_KEYS = ("resample", "alpha_floor", "max_layer_upsample",
               "min_stroke_px", "min_stroke_survival")
LAYER_KEYS = ("id", "source_asset_id", "ops", "placement")
PLACEMENT_KEYS = ("align", "scale", "squash", "gap")
PLACEMENT_REQUIRED = ("align", "scale")
SCALE_KEYS_BY_MODE = {"px": ("mode", "width"),
                      "width_rel_to_layer": ("mode", "layer", "factor")}
SQUASH_KEYS = ("h_factor",)
GAP_KEYS = ("rel_to_own_height", "from", "edge")

ALPHA_MIN, ALPHA_MAX = 0, 255
COMPRESS_MIN, COMPRESS_MAX = 0, 9
LUM_MIN, LUM_MAX = 0.0, 1.0

# The one honest sentence about what a green run proves. Quoted by
# --explain and by the human report, verbatim.
NO_TASTE_NOTE = ("a green run means the recipe was followed, not that "
                 "the piece is good — swapped numbers pass every wall.")

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2

# END OF RULE DATA. Logic below references the constants above.
# ═══════════════════════════════════════════════════════════════════════

if FLEET_IMPORT_ERROR is None:
    LICENSE_ALLOWLIST_VERBATIM = (ai.CF_LICENSE_LITERAL,)


class ComposeError(Exception):
    """A refusal. Exits 2 and names its rule."""

    def __init__(self, message, kind="INPUT"):
        super().__init__(message)
        self.kind = kind


def _ensure_utf8_console():
    """D-378 class: a cp1252 console must not turn a verdict into a
    UnicodeEncodeError. Display only."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _utc_now():
    return datetime.now(timezone.utc)


def nfc(text):
    return unicodedata.normalize("NFC", text)


def license_key(cell):
    """W1's comparison form: NFC -> strip -> casefold. Applied to both
    sides, so 'cf subscription,  VERIFIED ' and an NFD spelling both
    resolve to the same key as the allowlist entry."""
    return nfc(cell).strip().casefold()


def license_allowlist():
    return tuple(sorted(license_key(item)
                        for item in LICENSE_ALLOWLIST_VERBATIM))


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


# ── recipe ─────────────────────────────────────────────────────────────

def _no_duplicate_keys(pairs):
    """json.load's object_pairs_hook. A duplicate key in a recipe is
    two different intentions in one file and the last one silently
    wins — refuse instead."""
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError("duplicate key %r" % key)
        seen[key] = value
    return seen


def _check_keys(obj, where, required, optional=()):
    if not isinstance(obj, dict):
        raise ComposeError("%s must be a JSON object" % where,
                           kind="RECIPE_SHAPE")
    known = tuple(required) + tuple(optional)
    for key in sorted(obj):
        if key not in known:
            raise ComposeError(
                "unknown key %r in %s (known: %s) — refusing, fail "
                "closed" % (key, where, ", ".join(known)),
                kind="UNKNOWN_KEY")
    for key in required:
        if key not in obj:
            raise ComposeError(
                "%s is missing required key %r — there are no defaults "
                "in this tool" % (where, key), kind="MISSING_KEY")
    return obj


def _int_in(value, low, high, where):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ComposeError("%s must be an integer" % where,
                           kind="RECIPE_SHAPE")
    if not low <= value <= high:
        raise ComposeError("%s must be %d..%d, got %d"
                           % (where, low, high, value),
                           kind="RECIPE_RANGE")
    return value


def _number(value, where):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ComposeError("%s must be a number" % where,
                           kind="RECIPE_SHAPE")
    return float(value)


def _text(value, where):
    if not isinstance(value, str) or not value:
        raise ComposeError("%s must be a non-empty string" % where,
                           kind="RECIPE_SHAPE")
    return value


def canonical_recipe(recipe):
    """The bytes a recipe hash is taken over. Canonical so a reformat
    of the file does not change its identity."""
    return json.dumps(recipe, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def load_recipe(path):
    """Strict recipe load. Duplicate keys, unknown keys, missing keys,
    an unsupported schema: all refuse. No defaults are supplied for
    anything, ever."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
    except OSError as err:
        raise ComposeError("recipe unreadable: %s (%s)" % (path, err),
                           kind="RECIPE_UNREADABLE")
    try:
        recipe = json.loads(raw, object_pairs_hook=_no_duplicate_keys)
    except ValueError as err:
        message = str(err)
        if message.startswith("duplicate key"):
            raise ComposeError(
                "recipe has a %s — two intentions in one file, and the "
                "last one would win silently: %s" % (message, path),
                kind="DUPLICATE_KEY")
        raise ComposeError("recipe is not valid JSON (%s): %s"
                           % (err, path), kind="RECIPE_UNREADABLE")
    _check_keys(recipe, "recipe", RECIPE_KEYS)
    if recipe["schema"] != RECIPE_SCHEMA:
        raise ComposeError(
            "recipe schema is %r; this tool speaks schema %d only"
            % (recipe["schema"], RECIPE_SCHEMA),
            kind="SCHEMA_UNSUPPORTED")
    validate_output(recipe["output"])
    validate_canvas(recipe["canvas"])
    validate_layers(recipe["layers"])
    return recipe


def validate_output(output):
    _check_keys(output, "output", OUTPUT_KEYS)
    for key in ("path", "kind", "style", "niche_tags", "colors",
                "recolor"):
        _text(output[key], "output.%s" % key)
    if output["kind"] not in play_schema.ELEMENT_KINDS:
        raise ComposeError(
            "output.kind %r is not one of %s"
            % (output["kind"], ", ".join(play_schema.ELEMENT_KINDS)),
            kind="RECIPE_SHAPE")
    _int_in(output["expect_components"], 1, 1 << 20,
            "output.expect_components")
    _int_in(output["compress_level"], COMPRESS_MIN, COMPRESS_MAX,
            "output.compress_level")
    return output


def validate_canvas(canvas):
    _check_keys(canvas, "canvas", CANVAS_KEYS)
    if canvas["resample"] not in RESAMPLE_NAMES:
        raise ComposeError(
            "canvas.resample %r is not one of %s"
            % (canvas["resample"], ", ".join(RESAMPLE_NAMES)),
            kind="RECIPE_SHAPE")
    _int_in(canvas["alpha_floor"], ALPHA_MIN, ALPHA_MAX,
            "canvas.alpha_floor")
    _int_in(canvas["min_stroke_px"], 1, 1 << 20, "canvas.min_stroke_px")
    if _number(canvas["max_layer_upsample"],
               "canvas.max_layer_upsample") < 1.0:
        raise ComposeError("canvas.max_layer_upsample must be >= 1.0",
                           kind="RECIPE_RANGE")
    survival = _number(canvas["min_stroke_survival"],
                       "canvas.min_stroke_survival")
    if not 0.0 <= survival <= 1.0:
        raise ComposeError("canvas.min_stroke_survival must be 0..1",
                           kind="RECIPE_RANGE")
    return canvas


def validate_layers(layers):
    if not isinstance(layers, list) or not layers:
        raise ComposeError("layers must be a non-empty array — order "
                           "is data here", kind="RECIPE_SHAPE")
    seen = []
    for index, layer in enumerate(layers):
        where = "layers[%d]" % index
        _check_keys(layer, where, LAYER_KEYS)
        layer_id = _text(layer["id"], where + ".id")
        if layer_id in seen:
            raise ComposeError("duplicate layer id %r" % layer_id,
                               kind="RECIPE_SHAPE")
        _text(layer["source_asset_id"], where + ".source_asset_id")
        validate_ops(layer["ops"], where + ".ops")
        validate_placement(layer["placement"], where + ".placement",
                           seen)
        seen.append(layer_id)
    return layers


def validate_ops(ops, where):
    if not isinstance(ops, list) or not ops:
        raise ComposeError("%s must be a non-empty array" % where,
                           kind="RECIPE_SHAPE")
    ranges = []
    for index, op in enumerate(ops):
        spot = "%s[%d]" % (where, index)
        if not isinstance(op, dict) or "op" not in op:
            raise ComposeError("%s must be an object with an 'op'"
                               % spot, kind="RECIPE_SHAPE")
        name = op["op"]
        if name not in OP_PARAMS:
            raise ComposeError(
                "unknown op %r at %s (the registry is closed: %s)"
                % (name, spot, ", ".join(sorted(OP_PARAMS))),
                kind="UNKNOWN_OP")
        _check_keys(op, spot, ("op",) + OP_PARAMS[name],
                    OP_OPTIONAL_PARAMS[name])
        if name in ("ink_layer", "mid_layer"):
            if op["luminance"] not in LUMINANCE_COEFFS:
                raise ComposeError(
                    "%s.luminance %r is not one of %s"
                    % (spot, op["luminance"],
                       ", ".join(sorted(LUMINANCE_COEFFS))),
                    kind="RECIPE_SHAPE")
            low = (LUM_MIN if name == "ink_layer"
                   else _number(op["lum_min"], spot + ".lum_min"))
            high = _number(op["lum_max"], spot + ".lum_max")
            for value, label in ((low, "lum_min"), (high, "lum_max")):
                if not LUM_MIN <= value <= LUM_MAX:
                    raise ComposeError(
                        "%s.%s is %g; luminance is 0..1 in a recipe, "
                        "not 0..255 — a 0..255 value here would match "
                        "everything or nothing and still look green"
                        % (spot, label, value), kind="RECIPE_RANGE")
            if low > high:
                raise ComposeError("%s has lum_min above lum_max"
                                   % spot, kind="RECIPE_RANGE")
            if not op.get("allow_overlap"):
                for other_low, other_high, other_spot in ranges:
                    if low <= other_high and other_low <= high:
                        raise ComposeError(
                            "%s luminance range %g..%g overlaps %s "
                            "(%g..%g) — set allow_overlap true if that "
                            "is deliberate"
                            % (spot, low, high, other_spot, other_low,
                               other_high),
                            kind="RANGE_OVERLAP")
            ranges.append((low, high, spot))
        if name == "outline_thicken":
            if op["mode"] not in THICKEN_MODES:
                raise ComposeError(
                    "%s.mode %r is not one of %s"
                    % (spot, op["mode"], ", ".join(THICKEN_MODES)),
                    kind="RECIPE_SHAPE")
            if _number(op["amount"], spot + ".amount") <= 0:
                raise ComposeError("%s.amount must be positive" % spot,
                                   kind="RECIPE_RANGE")
    return ops


def validate_placement(placement, where, earlier_ids):
    _check_keys(placement, where, PLACEMENT_REQUIRED,
                tuple(k for k in PLACEMENT_KEYS
                      if k not in PLACEMENT_REQUIRED))
    if placement["align"] not in ALIGNS:
        raise ComposeError("%s.align %r is not one of %s"
                           % (where, placement["align"],
                              ", ".join(ALIGNS)),
                           kind="RECIPE_SHAPE")
    scale = placement["scale"]
    if not isinstance(scale, dict) or "mode" not in scale:
        raise ComposeError("%s.scale needs a mode" % where,
                           kind="RECIPE_SHAPE")
    mode = scale["mode"]
    if mode not in SCALE_MODES:
        raise ComposeError("%s.scale.mode %r is not one of %s"
                           % (where, mode, ", ".join(SCALE_MODES)),
                           kind="RECIPE_SHAPE")
    _check_keys(scale, where + ".scale", SCALE_KEYS_BY_MODE[mode])
    if mode == "px":
        _int_in(scale["width"], 1, 1 << 20, where + ".scale.width")
    else:
        _reference(scale["layer"], earlier_ids, where + ".scale.layer")
        if _number(scale["factor"], where + ".scale.factor") <= 0:
            raise ComposeError("%s.scale.factor must be positive"
                               % where, kind="RECIPE_RANGE")
    if "squash" in placement:
        _check_keys(placement["squash"], where + ".squash", SQUASH_KEYS)
        if _number(placement["squash"]["h_factor"],
                   where + ".squash.h_factor") <= 0:
            raise ComposeError("%s.squash.h_factor must be positive"
                               % where, kind="RECIPE_RANGE")
    if "gap" in placement:
        gap = _check_keys(placement["gap"], where + ".gap", GAP_KEYS)
        _number(gap["rel_to_own_height"],
                where + ".gap.rel_to_own_height")
        _reference(gap["from"], earlier_ids, where + ".gap.from")
        if gap["edge"] not in GAP_EDGES:
            raise ComposeError("%s.gap.edge %r is not one of %s"
                               % (where, gap["edge"],
                                  ", ".join(GAP_EDGES)),
                               kind="RECIPE_SHAPE")
    return placement


def _reference(layer_id, earlier_ids, where):
    """A layer may reference only layers BEFORE it. Placement resolves
    in one pass against frozen geometry, so a forward reference is a
    number that does not exist yet — refuse rather than guess."""
    if layer_id not in earlier_ids:
        raise ComposeError(
            "%s names %r, which is not an EARLIER layer (earlier: %s) "
            "— placement resolves in one forward pass"
            % (where, layer_id,
               ", ".join(earlier_ids) if earlier_ids else "none"),
            kind="FORWARD_REFERENCE")
    return layer_id


# ── config ─────────────────────────────────────────────────────────────

def load_config(path):
    """Strict config load. Paths come from config, never hardcoded."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        raise ComposeError(
            "config not found: %s (copy %s.example)"
            % (path, DEFAULT_CONFIG_NAME), kind="CONFIG_MISSING")
    except (OSError, ValueError) as err:
        raise ComposeError("config unreadable: %s (%s)" % (path, err),
                           kind="CONFIG_UNREADABLE")
    if not isinstance(raw, dict):
        raise ComposeError("config must be a JSON object: %s" % path,
                           kind="CONFIG_UNREADABLE")
    for key in sorted(raw):
        if key not in KNOWN_CONFIG_KEYS:
            raise ComposeError(
                "unknown config key %r (known: %s) — refusing, fail "
                "closed" % (key, ", ".join(KNOWN_CONFIG_KEYS)),
                kind="CONFIG_UNKNOWN_KEY")
    for key in REQUIRED_CONFIG_KEYS:
        if not isinstance(raw.get(key), str) or not raw[key]:
            raise ComposeError(
                "config key %r missing or not a non-empty string" % key,
                kind="CONFIG_MISSING_KEY")
    root = os.path.abspath(raw["index_root"])
    if not os.path.isdir(root):
        raise ComposeError("index_root is not a directory: %s" % root,
                           kind="CONFIG_BAD_PATH")
    return {"index_root": root}


# ── sources (W1 + W2) ──────────────────────────────────────────────────

def index_rows(index_root):
    """asset_id -> its row line. Header rows are identified
    STRUCTURALLY by asset_index_lint, never by their text."""
    path = os.path.join(index_root, ai.INDEX_NAME)
    if not os.path.isfile(path):
        raise ComposeError("no %s in %s" % (ai.INDEX_NAME, index_root),
                           kind="INDEX_MISSING")
    with open(path, "r", encoding="utf-8") as handle:
        lines = handle.read().split("\n")
    headers = ail.find_header_lines(lines)
    rows = {}
    for number, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        if ail.is_separator_row(line) or number in headers:
            continue
        if ail.lint_row(line):
            continue
        primary = ail.asset_path(line)
        if primary and primary not in rows:
            rows[primary] = {"line": line, "number": number + 1}
    return rows


def read_source(asset_id, index_root, rows, sidecar_entries):
    """W1 + W2, in one place. Returns a dict carrying the BYTES that
    were read, their hash, and the decoded image — the path is never
    reopened after this, so a file swapped afterwards cannot get in."""
    row = rows.get(asset_id)
    if row is None:
        raise ComposeError(
            "W1: %r has no valid ASSET_INDEX FILE row — a source must "
            "be indexed and licensed" % asset_id,
            kind="SOURCE_NOT_INDEXED")
    if asset_id.endswith("/"):
        raise ComposeError("W1: %r is a folder row, not a file"
                           % asset_id, kind="SOURCE_IS_FOLDER")
    declared = ail.asset_paths(row["line"])
    if len(declared) != 1:
        raise ComposeError(
            "W1: %r sits in a row declaring %d paths (%s) — a source "
            "must be one file"
            % (asset_id, len(declared),
               (" %s " % ail.ASSET_PATH_JOIN).join(declared)),
            kind="SOURCE_MULTI_PATH")
    cells = ail.split_cells(row["line"])
    allowed = license_allowlist()
    if license_key(cells[1]) not in allowed:
        raise ComposeError(
            "W1: %r has License %r, which is not in the allowlist "
            "(%s) — refusing. An unlisted licence is never assumed "
            "good." % (asset_id, cells[1].strip(), "; ".join(allowed)),
            kind="NOT_LICENSED_SOURCE")
    entry = sidecar_entries.get(asset_id)
    if not entry or not entry.get("sha256"):
        raise ComposeError(
            "W1: %r has no sidecar sha256 — provenance unverifiable"
            % asset_id, kind="PROVENANCE_MISMATCH")
    file_path = os.path.join(index_root, *asset_id.split("/"))
    try:
        with open(file_path, "rb") as handle:
            data = handle.read()          # W2: exactly once
    except OSError as err:
        raise ComposeError("W1: %r unreadable (%s)" % (asset_id, err),
                           kind="SOURCE_UNREADABLE")
    digest = sha256_bytes(data)
    if digest != entry["sha256"]:
        raise ComposeError(
            "W1: %r hashes %s but the sidecar says %s — the file on "
            "disk is not the indexed one"
            % (asset_id, digest, entry["sha256"]),
            kind="PROVENANCE_MISMATCH")
    try:
        image = Image.open(io.BytesIO(data))   # W2: from those bytes
        image.load()
    except Exception as err:                   # Pillow raises broadly
        raise ComposeError("W1: %r is not a readable image (%s)"
                           % (asset_id, err), kind="SOURCE_UNREADABLE")
    return {"asset_id": asset_id, "sha256": digest,
            "image": image.convert(OUTPUT_MODE), "style": cells[2]}


# ── ops (pure pixel transforms) ────────────────────────────────────────

def luminance_band(image, coeffs, low, high):
    """The alpha of the pixels whose luminance falls in [low, high],
    MASKED TO a>0 FIRST. A transparent black pixel is not ink: without
    the mask every fully-transparent pixel reads luminance 0 and the
    whole canvas becomes the ink layer.

    low and high arrive on the RECIPE's 0..1 scale and are scaled to
    the L-mode 0..255 band HERE, once. This is the only place the two
    scales meet."""
    red, green, blue, alpha = image.split()
    visible = alpha.point(lambda v: 255 if v else 0)
    lum = Image.merge("RGB", (red, green, blue)).convert(
        "L", (coeffs[0], coeffs[1], coeffs[2], 0))
    low, high = low * LUMINANCE_SCALE, high * LUMINANCE_SCALE
    band = lum.point(lambda v: 255 if low <= v <= high else 0)
    return ImageChops.darker(ImageChops.darker(band, visible), alpha)


def apply_op(image, op):
    """One pure pixel transform, in RGBA. Returns a new image."""
    name = op["op"]
    if name == "solid":
        return image.copy()
    if name in ("ink_layer", "mid_layer"):
        coeffs = LUMINANCE_COEFFS[op["luminance"]]
        low = LUM_MIN if name == "ink_layer" else float(op["lum_min"])
        alpha = luminance_band(image, coeffs, low, float(op["lum_max"]))
        out = image.copy()
        out.putalpha(alpha)
        return out
    if name == "outline_thicken":
        alpha = image.split()[3]
        if op["mode"] == "percent":
            width = max(image.size)
            grow = int(round(width * float(op["amount"]) / 100.0))
        else:
            grow = int(round(float(op["amount"])))
        out = image.copy()
        out.putalpha(dilate_alpha(alpha, max(0, grow)))
        return out
    raise ComposeError("unknown op %r" % name, kind="UNKNOWN_OP")


def dilate_alpha(alpha, radius):
    """Grow an alpha channel by a square radius. EXACTLY equal to
    ImageFilter.MaxFilter(2*radius+1) — byte-for-byte on the grey
    channel, not merely footprint-equal — because a square max is
    separable and max is idempotent: a window of radius c, maxed with
    itself shifted by s, is a window of radius c+s.

    MEASURED on a 1200px fixture with 3px strokes and one lone pixel
    (r=20): MaxFilter(41) 2.79s · this 0.124s, 0 differing pixels.
    BoxBlur(20)-then-threshold, which the bench suggested, ran in
    0.008s but lost 2433 pixels and moved the bbox by 1px on two edges
    — a single opaque pixel averaged over a 41x41 box rounds to 0 in
    uint8, so thin art loses ends. Exact and fast beat faster and
    approximate, so this is the choice."""
    if radius <= 0:
        return alpha.copy()
    out = alpha
    covered = 0
    step = DILATE_START_STEP
    while covered < radius:
        span = min(step, radius - covered)
        for delta in ((span, 0), (-span, 0), (0, span), (0, -span)):
            out = ImageChops.lighter(out, ImageChops.offset(out, *delta))
        covered += span
        step *= 2
    return out


def op_record(op):
    """What goes in derived_from: the op's name and its parameters,
    sorted so the record is deterministic."""
    return {"op": op["op"],
            "params": {k: v for k, v in sorted(op.items())
                       if k != "op"}}


# ── compose ────────────────────────────────────────────────────────────

def sweep_alpha(image, floor):
    """W9: after every resample, alpha below the floor goes to 0. The
    resample halo (LANCZOS measured 19px at a>0) is what trips
    play_forge's OVERLAP wall, which binarizes at a>0."""
    alpha = image.split()[3].point(lambda v: v if v >= floor else 0)
    out = image.copy()
    out.putalpha(alpha)
    return out


def flatten_rgb(image):
    """W3: colour is a render-time decision. Every pixel's RGB becomes
    FLAT_RGB; alpha is untouched."""
    alpha = image.split()[3]
    out = Image.new(OUTPUT_MODE, image.size, FLAT_RGB + (0,))
    out.putalpha(alpha)
    return out


def resize_layer(image, width, resample, canvas, report):
    height = max(1, int(round(image.size[1] * width / image.size[0])))
    ratio = width / float(image.size[0])
    if ratio > canvas["max_layer_upsample"]:
        raise ComposeError(
            "W9: layer would upsample %.3fx, above "
            "canvas.max_layer_upsample %.3f"
            % (ratio, canvas["max_layer_upsample"]),
            kind="UPSAMPLE_EXCEEDED")
    return image.resize((width, height), resample), ratio


def compose(recipe, sources, report):
    """Ops first (pure pixels), then ONE forward pass of placement
    against frozen geometry. Returns the flattened RGBA output."""
    canvas = recipe["canvas"]
    resample = getattr(Image, canvas["resample"])
    floor = canvas["alpha_floor"]
    placed = {}
    order = []
    for layer in recipe["layers"]:
        image = sources[layer["id"]]["image"]
        for op in layer["ops"]:
            image = apply_op(image, op)
        if image.split()[3].getbbox() is None:
            raise ComposeError(
                "layer %r is EMPTY after its ops (%s) — a layer that "
                "contributes nothing is never what a recipe meant, and "
                "it is exactly how a wrong threshold produces a green "
                "run" % (layer["id"],
                         " -> ".join(op["op"] for op in layer["ops"])),
                kind="EMPTY_LAYER")
        placement = layer["placement"]
        scale = placement["scale"]
        if scale["mode"] == "px":
            width = int(scale["width"])
        else:
            base = placed[scale["layer"]]["image"].size[0]
            width = max(1, int(round(base * float(scale["factor"]))))
        image, ratio = resize_layer(image, width, resample, canvas,
                                    report)
        image = sweep_alpha(image, floor)
        if "squash" in placement:
            factor = float(placement["squash"]["h_factor"])
            height = max(1, int(round(image.size[1] * factor)))
            image = image.resize((image.size[0], height), resample)
            image = sweep_alpha(image, floor)
        placed[layer["id"]] = {"image": image,
                               "placement": placement,
                               "upsample": round(ratio, 6)}
        order.append(layer["id"])
    return assemble(placed, order, recipe, floor)


def assemble(placed, order, recipe, floor):
    """Lay the frozen layers out. Vertical position comes from gap
    (relative to the layer's own height, measured off a named earlier
    layer's edge); horizontal from align. Nothing is auto-placed."""
    tops = {}
    for layer_id in order:
        item = placed[layer_id]
        placement = item["placement"]
        height = item["image"].size[1]
        if "gap" not in placement:
            tops[layer_id] = 0
            continue
        gap = placement["gap"]
        other = placed[gap["from"]]
        other_top = tops[gap["from"]]
        offset = int(round(height * float(gap["rel_to_own_height"])))
        if gap["edge"] == "top":
            tops[layer_id] = other_top - height - offset
        else:
            tops[layer_id] = (other_top + other["image"].size[1]
                              + offset)
    widest = max(placed[i]["image"].size[0] for i in order)
    top = min(tops[i] for i in order)
    bottom = max(tops[i] + placed[i]["image"].size[1] for i in order)
    sheet = Image.new(OUTPUT_MODE, (widest, bottom - top),
                      FLAT_RGB + (0,))
    for layer_id in order:
        item = placed[layer_id]
        image = item["image"]
        align = item["placement"]["align"]
        if align == "left":
            x = 0
        elif align == "right":
            x = widest - image.size[0]
        else:
            x = (widest - image.size[0]) // 2
        sheet.alpha_composite(image, (x, tops[layer_id] - top))
    sheet = sweep_alpha(sheet, floor)
    return flatten_rgb(sheet)


def measure_output(image, canvas):
    """W8 + W10 + W9's footprint, all measured on the FINAL alpha
    after the sweep. Numbers, not opinions. The erosion kernel is
    play_forge's own rule, IMPORTED — W10 says never retype it, and my
    first draft retyped it wrong (2*n+1 instead of round-up-to-odd)."""
    alpha = image.split()[3]
    binary = alpha.point(lambda v: 255 if v else 0)
    components = ai.label_components(binary)
    eroded = binary.filter(ImageFilter.MinFilter(
        pf.stroke_kernel(canvas["min_stroke_px"])))
    ink = sum(binary.histogram()[1:])
    survived = sum(eroded.histogram()[1:])
    survival = (survived / float(ink)) if ink else 0.0
    return {"components": len(components),
            "footprint_bbox": list(binary.getbbox() or ()),
            "ink_px": ink,
            "stroke_survival": round(survival, 6)}


# ── output ─────────────────────────────────────────────────────────────

def build_style(output):
    """W6: the Style cell as it will land, then fed straight back
    through play_new.infer_kind. The round trip is the mechanism."""
    style = output["style"]
    kind, why = pn.infer_kind(style)
    if kind != output["kind"]:
        raise ComposeError(
            "W6: Style %r infers kind %r (%s) but the recipe says %r — "
            "the row and the recipe must agree, and the round trip is "
            "what proves it" % (style, kind, why, output["kind"]),
            kind="KIND_MISMATCH")
    return style


def build_row(output, date_text):
    """W7: exactly ONE path in the Asset cell; 'Used in' never empty.
    Proven against asset_index_lint BEFORE it is allowed to land."""
    cells = ["`%s`" % output["path"], ai.CF_LICENSE_LITERAL,
             output["style"], output["niche_tags"], output["colors"],
             output["recolor"], USED_IN_FMT % date_text]
    line = ail.format_row(cells)
    findings = ail.lint_row(line)
    if findings:
        raise ComposeError(
            "W7: the composed row fails its own lint (%s) — refusing "
            "to append" % "; ".join(findings), kind="ROW_LINT_FAILED")
    if len(ail.asset_paths(line)) != 1:
        raise ComposeError("W7: the composed row must declare exactly "
                           "one path", kind="ROW_LINT_FAILED")
    return line


def check_output_path(output, index_root, overwrite):
    """W12: a piece lands in a pieces/ dir, and never over an existing
    file without the human saying so."""
    parts = output["path"].split("/")
    if PIECES_DIR_NAME not in parts[:-1]:
        raise ComposeError(
            "W12: output.path %r is not under a %s/ directory — a "
            "composed piece is a PIECE"
            % (output["path"], PIECES_DIR_NAME),
            kind="OUTPUT_NOT_IN_PIECES")
    full = os.path.join(index_root, *parts)
    if os.path.exists(full) and not overwrite:
        raise ComposeError(
            "W12: %s already exists — re-run with --overwrite to "
            "replace it deliberately" % full, kind="OUTPUT_EXISTS")
    return full


def write_png(image, path, compress_level):
    """W11 + W12: explicit compress_level, tmp -> fsync -> replace."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".%s.tmp" % uuid.uuid4().hex
    with open(tmp, "wb") as handle:
        image.save(handle, format="PNG", compress_level=compress_level)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def sidecar_entry(output, measured, recipe_sha, derived_from,
                  file_sha, date_text):
    """W5: written by this tool from what it actually read. kind is
    recorded here as well as in the Style cell — the duplication is
    FLAGGED (D-394); Sonnet may rule that this one supersedes."""
    return {"sha256": file_sha,
            "tool": TOOL_NAME,
            "kind": output["kind"],
            "product_id": "COMPOSED",
            "ingested_utc": date_text,
            "recipe_sha256": recipe_sha,
            "derived_from": derived_from,
            "components": measured["components"],
            "footprint_bbox": measured["footprint_bbox"],
            "stroke_survival": measured["stroke_survival"]}


def check_entry_provenance(entry, asset_id):
    """Fail-closed rule: an entry claiming this tool with no
    derived_from is a lie about where a piece came from."""
    if entry.get("tool") == TOOL_NAME and not entry.get("derived_from"):
        raise ComposeError(
            "W5: sidecar entry for %r says tool %s but carries no "
            "derived_from — provenance claimed and not kept"
            % (asset_id, TOOL_NAME), kind="SIDECAR_NO_PROVENANCE")
    return entry


# ── the run ────────────────────────────────────────────────────────────

def run_compose(recipe_path, config, opts):
    """The ONE report dict. Human output and --json both render it."""
    date_text = _utc_now().date().isoformat()
    recipe = load_recipe(recipe_path)
    recipe_sha = sha256_bytes(canonical_recipe(recipe))
    output = recipe["output"]
    index_root = config["index_root"]
    report = {
        "tool": TOOL_NAME,
        "recipe": os.path.abspath(recipe_path),
        "recipe_sha256": recipe_sha,
        "output_path": output["path"],
        "applied": False,
        "layers": [],
        "findings": [],
        "refusals": [],
        "note": NO_TASTE_NOTE,
        "exit_code": EXIT_CLEAN,
    }
    full_out = check_output_path(output, index_root, opts["overwrite"])
    style = build_style(output)                      # W6, before work
    rows = index_rows(index_root)
    sidecar = ai.load_sidecar(ai.sidecar_path(config))
    entries = sidecar["entries"]
    for asset_id, entry in sorted(entries.items()):
        check_entry_provenance(entry, asset_id)
    sources = {}
    derived_from = []
    for layer in recipe["layers"]:
        source = read_source(layer["source_asset_id"], index_root,
                             rows, entries)
        sources[layer["id"]] = source
        derived_from.append({
            "layer": layer["id"],
            "asset_id": source["asset_id"],
            "sha256_at_compose": source["sha256"],
            "ops": [op_record(op) for op in layer["ops"]]})
        report["layers"].append({"id": layer["id"],
                                 "asset_id": source["asset_id"],
                                 "sha256_at_compose": source["sha256"],
                                 "source_size": list(
                                     source["image"].size)})
    image = compose(recipe, sources, report)
    measured = measure_output(image, recipe["canvas"])
    report["measured"] = measured
    report["style"] = style
    if measured["components"] != output["expect_components"]:
        raise ComposeError(
            "W8: measured %d component(s), the recipe expects %d"
            % (measured["components"], output["expect_components"]),
            kind="COMPONENT_MISMATCH")
    canvas = recipe["canvas"]
    if measured["stroke_survival"] < canvas["min_stroke_survival"]:
        report["findings"].append(
            "W10 STROKE: survival %.3f is below "
            "canvas.min_stroke_survival %.3f at min_stroke_px %d — the "
            "piece still writes; the number is here for Khai's eye."
            % (measured["stroke_survival"],
               canvas["min_stroke_survival"], canvas["min_stroke_px"]))
    row = build_row(output, date_text)
    report["row"] = row
    if opts["apply"]:
        write_png(image, full_out, output["compress_level"])
        with open(full_out, "rb") as handle:
            file_sha = sha256_bytes(handle.read())
        entries[output["path"]] = sidecar_entry(
            output, measured, recipe_sha, derived_from, file_sha,
            date_text)
        sidecar["version"] = ai.SIDECAR_VERSION
        ai.write_sidecar(ai.sidecar_path(config), sidecar)
        ai.append_index_line(os.path.join(index_root, ai.INDEX_NAME),
                             row)
        report["applied"] = True
        report["output_sha256"] = file_sha
    image.close()
    for source in sources.values():
        source["image"].close()
    report["exit_code"] = (EXIT_FINDINGS if report["findings"]
                           else EXIT_CLEAN)
    return report


def format_report(report):
    lines = ["asset_compose %s  applied=%s  exit=%d"
             % (report["output_path"], report["applied"],
                report["exit_code"]),
             "  recipe: %s (%s)" % (report["recipe"],
                                    report["recipe_sha256"][:16])]
    for layer in report.get("layers", []):
        lines.append("  layer %s <- %s (%s)"
                     % (layer["id"], layer["asset_id"],
                        layer["sha256_at_compose"][:16]))
    measured = report.get("measured")
    if measured:
        lines.append("  measured: components=%d bbox=%s "
                     "stroke_survival=%.3f"
                     % (measured["components"],
                        measured["footprint_bbox"],
                        measured["stroke_survival"]))
    if report.get("row"):
        lines.append("  row: %s" % report["row"])
    for finding in report["findings"]:
        lines.append("  FINDING %s" % finding)
    if not report["applied"]:
        lines.append("  DRY RUN — nothing written but this receipt. "
                     "Re-run with --apply.")
    lines.append("  %s" % report["note"])
    return "\n".join(lines)


def render_explain():
    return "\n".join([
        "asset_compose — indexed licensed pieces + a recipe -> one "
        "derived piece.",
        "",
        NO_TASTE_NOTE.upper(),
        "",
        "Every number comes from the recipe. There are no defaults: a "
        "missing",
        "number is a refusal, not a guess. Sources must be indexed, "
        "licensed and",
        "hash-verified; their bytes are read ONCE and the image is "
        "decoded from",
        "those same bytes. The output carries alpha only — colour is a "
        "render-time",
        "decision that belongs to play_forge.",
        "",
        "LUMINANCE IS 0..1 in a recipe, never 0..255. It is scaled to "
        "the image's",
        "0..255 band in one place inside the tool. A layer that comes "
        "out EMPTY after",
        "its ops refuses EMPTY_LAYER rather than quietly contributing "
        "nothing.",
        "",
        "outline_thicken grows by a square radius, dilating in "
        "doubling steps — the",
        "same result as a max filter, without the O(k^2) cost that made "
        "a real 3%",
        "thicken take twelve minutes.",
        "",
        "The row and the sidecar carry product_id \"COMPOSED\", a "
        "WORD not a number:",
        "a composed piece descends from several products and has no "
        "single one.",
        "",
        "Exit 0 clean · 1 findings (the stroke floor) · 2 refusal or "
        "tool error.",
        "Dry-run is the default; --apply writes the piece, the row and "
        "the sidecar.",
    ])


def append_receipt(report):
    receipt = {"tool": TOOL_NAME,
               "recipe_sha256": report.get("recipe_sha256"),
               "output_path": report.get("output_path"),
               "output_sha256": report.get("output_sha256"),
               "applied": report.get("applied", False),
               "layers": report.get("layers", []),
               "measured": report.get("measured"),
               "findings": report.get("findings", []),
               "refusals": report.get("refusals", []),
               "exit_code": report.get("exit_code"),
               "completed_utc": _utc_now().isoformat(
                   timespec="seconds")}
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(
                __file__)), RECEIPTS_NAME), "a",
                encoding="utf-8") as handle:
            handle.write(json.dumps(receipt, sort_keys=True,
                                    ensure_ascii=False) + "\n")
    except OSError:
        pass                      # a receipt must never mask the run


def build_parser():
    parser = argparse.ArgumentParser(
        prog="asset_compose.py",
        description="Indexed licensed pieces + a recipe -> one derived "
                    "piece. Dry-run by default.")
    parser.add_argument("recipe", nargs="?", help="the recipe JSON")
    parser.add_argument("--config", default=DEFAULT_CONFIG_NAME)
    parser.add_argument("--apply", action="store_true",
                        help="write the piece, the row and the sidecar")
    parser.add_argument("--overwrite", action="store_true",
                        help="replace an existing output deliberately")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--explain", action="store_true")
    return parser


def _main(argv=None):
    _ensure_utf8_console()
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    args = parser.parse_args(argv)
    try:
        if args.explain:
            print(render_explain())
            return EXIT_CLEAN
        if FLEET_IMPORT_ERROR is not None:
            raise ComposeError(
                "a fleet dependency is missing (%s) — every rule this "
                "tool applies is imported from the module that owns it"
                % FLEET_IMPORT_ERROR, kind="DEP_MISSING")
        if not args.recipe:
            raise ComposeError("no recipe given — usage: "
                               "asset_compose.py RECIPE.json")
        config = load_config(args.config)
        report = run_compose(args.recipe, config,
                             {"apply": args.apply,
                              "overwrite": args.overwrite})
    except ComposeError as err:
        report = {"tool": TOOL_NAME, "applied": False, "findings": [],
                  "refusals": [{"kind": err.kind, "reason": str(err)}],
                  "note": NO_TASTE_NOTE, "exit_code": EXIT_ERROR}
        append_receipt(report)
        if args.json:
            print(json.dumps(report, sort_keys=True,
                             ensure_ascii=False, indent=2))
        else:
            print("REFUSED (%s): %s" % (err.kind, err),
                  file=sys.stderr)
        return EXIT_ERROR
    append_receipt(report)
    if args.json:
        print(json.dumps(report, sort_keys=True, ensure_ascii=False,
                         indent=2))
    else:
        print(format_report(report))
    return report["exit_code"]


def main(argv=None):
    """CRASH FLOOR. A bare traceback exits 1, and this tool's contract
    reads 1 as "findings" — a real measurement on a real piece. So
    without this guard a crash and a thin-stroke warning are the same
    integer to gate_run and to any wrapper. SystemExit and
    KeyboardInterrupt are NOT caught: argparse owns exit 2 for a bad
    flag and must stay untouched."""
    try:
        return _main(argv)
    except Exception as err:
        reason = "%s: %s" % (type(err).__name__, err)
        report = {"tool": TOOL_NAME, "applied": False, "findings": [],
                  "refusals": [{"kind": "CRASH", "reason": reason}],
                  "exit_code": EXIT_ERROR}
        append_receipt(report)
        source = sys.argv[1:] if argv is None else list(argv)
        if "--json" in source:
            print(json.dumps(report, sort_keys=True,
                             ensure_ascii=False, indent=2))
        else:
            print("CRASH (%s): %s" % (type(err).__name__, err),
                  file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
