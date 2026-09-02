#!/usr/bin/env python3
"""play_schema.py — shared play.json loader (MC FLEET B3, W11; sample
filed as D-419). B2 imports this later; asset_ingest ships it now so
there is one schema, not two.

The contract: UNKNOWN FIELDS ARE IGNORED, NEVER ERRORS — the D-419
sample carries a free-text "note" field on elements, and future plays
will grow more. Required fields (from the sample) are validated and
missing/invalid ones raise PlayError. The layout registry is CLOSED:
a layout outside it is a typo, not an extension.

Standard library only — importable without Pillow.
"""

import json
import re

# ═══════════════════════════════════════════════════════════════════════
# RULE DATA.
# ═══════════════════════════════════════════════════════════════════════

# Closed registry (D-419): "Layout registry (closed)".
LAYOUTS = ("text_hero", "art_top", "art_hero", "frame",
           "text_dominant")

# Closed registries added for B2 (W12): text-treatment families —
# "straight" is the classic lockup, "arc" is family C, "badge" is
# family D. Optional per-variant field, defaulting to "straight";
# a value outside the registry is a typo, never an extension.
FAMILIES = ("straight", "arc", "badge")

# Optional per-element tag (B2 W9 court rider): the eyes gate runs
# ONLY on "character" elements. Absent = not a character.
ELEMENT_KINDS = ("character", "ornament", "subject")

HEX_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Required shapes, straight from the sample. Field lists here are the
# schema; the validators below only walk this data.
PLAY_REQUIRED = ("play_id", "line", "named_feeling", "variants")
LINE_REQUIRED = ("setup", "punch")
VARIANT_REQUIRED = ("id", "garment", "font_pair", "color_path",
                    "layout", "fill_hex", "outline_hex", "elements")
FONT_PAIR_REQUIRED = ("hero", "support")
ELEMENT_REQUIRED = ("asset_id", "recolor_hex", "size_fraction",
                    "position")

# ═══════════════════════════════════════════════════════════════════════
# END OF RULE DATA.
# ═══════════════════════════════════════════════════════════════════════


class PlayError(Exception):
    """A play.json that violates the required schema. Names the field."""


def _require(mapping, keys, where):
    if not isinstance(mapping, dict):
        raise PlayError("%s must be an object" % where)
    for key in keys:
        if key not in mapping:
            raise PlayError("%s is missing required field %r"
                            % (where, key))


def _require_str(value, where):
    if not isinstance(value, str) or not value.strip():
        raise PlayError("%s must be a non-empty string" % where)
    return value


def _require_hex(value, where, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not HEX_PATTERN.match(value):
        raise PlayError("%s must be '#RRGGBB'%s (got %r)"
                        % (where, " or null" if nullable else "",
                           value))
    return value


def validate_element(data, where):
    _require(data, ELEMENT_REQUIRED, where)
    fraction = data["size_fraction"]
    if (not isinstance(fraction, (int, float))
            or isinstance(fraction, bool)
            or not 0 < fraction <= 1):
        raise PlayError("%s.size_fraction must be a number in (0, 1] "
                        "(got %r)" % (where, fraction))
    kind = data.get("kind")
    if kind is not None and kind not in ELEMENT_KINDS:
        raise PlayError("%s.kind %r is not in the closed registry %s"
                        % (where, kind, list(ELEMENT_KINDS)))
    return {
        "kind": kind,
        "asset_id": _require_str(data["asset_id"],
                                 where + ".asset_id"),
        "recolor_hex": _require_hex(data["recolor_hex"],
                                    where + ".recolor_hex"),
        "size_fraction": float(fraction),
        "position": _require_str(data["position"],
                                 where + ".position"),
    }


def validate_variant(data, where):
    _require(data, VARIANT_REQUIRED, where)
    if not isinstance(data["id"], int) or isinstance(data["id"], bool):
        raise PlayError("%s.id must be an integer" % where)
    _require(data["font_pair"], FONT_PAIR_REQUIRED,
             where + ".font_pair")
    layout = data["layout"]
    if layout not in LAYOUTS:
        raise PlayError("%s.layout %r is not in the closed registry "
                        "%s" % (where, layout, list(LAYOUTS)))
    family = data.get("family", "straight")
    if family not in FAMILIES:
        raise PlayError("%s.family %r is not in the closed registry "
                        "%s" % (where, family, list(FAMILIES)))
    if not isinstance(data["elements"], list):
        raise PlayError("%s.elements must be a list" % where)
    return {
        "id": data["id"],
        "family": family,
        "garment": _require_str(data["garment"], where + ".garment"),
        "font_pair": {
            "hero": _require_str(data["font_pair"]["hero"],
                                 where + ".font_pair.hero"),
            "support": _require_str(data["font_pair"]["support"],
                                    where + ".font_pair.support"),
        },
        "color_path": _require_str(data["color_path"],
                                   where + ".color_path"),
        "layout": layout,
        "fill_hex": _require_hex(data["fill_hex"],
                                 where + ".fill_hex"),
        "outline_hex": _require_hex(data["outline_hex"],
                                    where + ".outline_hex",
                                    nullable=True),
        "elements": [
            validate_element(element, "%s.elements[%d]" % (where, i))
            for i, element in enumerate(data["elements"])
        ],
    }


def validate_play(data):
    """Validate a parsed play dict. Returns a NORMALIZED dict carrying
    only the known fields — unknown fields (e.g. an element's "note")
    are ignored, never errors (W11). Raises PlayError on anything
    missing or malformed."""
    _require(data, PLAY_REQUIRED, "play")
    _require(data["line"], LINE_REQUIRED, "play.line")
    if not isinstance(data["variants"], list) or not data["variants"]:
        raise PlayError("play.variants must be a non-empty list")
    return {
        "play_id": _require_str(data["play_id"], "play.play_id"),
        "line": {
            "setup": _require_str(data["line"]["setup"],
                                  "play.line.setup"),
            "punch": _require_str(data["line"]["punch"],
                                  "play.line.punch"),
        },
        "named_feeling": _require_str(data["named_feeling"],
                                      "play.named_feeling"),
        "variants": [
            validate_variant(variant, "play.variants[%d]" % i)
            for i, variant in enumerate(data["variants"])
        ],
    }


def load_play(path):
    """Read and validate a play.json file. JSON errors and schema
    errors both surface as PlayError naming the problem."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as err:
        raise PlayError("cannot read play file %s: %s" % (path, err))
    return validate_play(data)
