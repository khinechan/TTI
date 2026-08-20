#!/usr/bin/env python3
"""KCT design colour validator — a hard gate for the print-on-demand pipeline.

This validates the DESIGN FILE, not the printed shirt. DTG on dark garments
prints over a white underbase; reflective ink on fabric does not behave like
emissive pixels on a screen. A PASS here is a file-level PASS only.

Exit codes:
    0 = PASS
    1 = FAIL  (the design violated a rule, or the garment is unknown)
    2 = ERROR (malformed hex, or broken/missing rule config)

Standard library only.
"""

import argparse
import json
import re
import sys
from itertools import combinations

# ═══════════════════════════════════════════════════════════════════════
# RULES ARE DATA.
# Everything below this banner is a value, not logic. A palette change
# must never require touching the contrast math further down.
# ═══════════════════════════════════════════════════════════════════════

GARMENTS = {
    "black":        {"hex": "#141414", "class": "dark",  "provisional": False},
    "dark heather": {"hex": "#3E3C3A", "class": "dark",  "provisional": True},
    "sport grey":   {"hex": "#A6A6A4", "class": "light", "provisional": False},
}

PROVISIONAL_WARNING = (
    "{garment} hex is unmeasured (approx). Verdicts on this garment "
    "are provisional until a measured value replaces it."
)

# Allowed design colours, keyed by garment class. Exact match only.
PALETTES = {
    "dark": {
        "#D9A441": "gold",
        "#7A9CB0": "dusty blue",
        "#9CAF88": "sage",
        "#C67B5C": "terracotta",
        "#C98A8A": "dusty rose",
    },
    "light": {
        "#3E5C46": "forest",
        "#5C1F2E": "burgundy",
        "#4A2545": "plum",
        "#2A1810": "chocolate ink",
    },
}

# The outline role. Never inferred from a hex — the caller declares it
# with --outline, because the tool cannot see the art.
OUTLINE = {
    "hex": "#0C0C0C",
    "name": "outline black",
    "allowed_classes": ["dark"],
}

# Checked BEFORE the allowlist so the reason is specific, never generic.
EXPLICIT_BARS = [
    {
        "hex": "#A34730",
        "name": "brick red",
        "garment": "sport grey",
        "reason": "explicitly barred on sport grey — 2.46:1, below the 3.0 floor",
    },
]

THRESHOLDS = {
    "MIN_CONTRAST":            3.0,   # design colour vs garment
    "MARGINAL_BAND":           0.5,   # passes, but flagged
    "MAX_DESIGN_COLORS":       2,     # outline excluded
    "MIN_INTER_COLOR":         1.5,   # design colour vs design colour
    "OUTLINE_VISIBILITY_WARN": 1.5,   # outline vs garment
}

# Euclidean RGB distance under which a non-allowlisted hex earns a
# "did you mean ...?" hint. A HINT IN A FAILURE MESSAGE — never a pass.
NEAR_MISS_DISTANCE = 24.0

RULES = {
    "R1": "max design colours ({max}) — outline excluded",
    "R2": "design colour must be on this garment's allowlist",
    "R3": "design colour must clear {min}:1 contrast against the garment",
    "R4": "explicit bar for this hex on this garment",
    "R5": "outline role is permitted on {classes} garments only",
    "R6": "garment must be a known garment",
    "R7": "a design must contain at least one colour",
}

FOOTER_NOTE = (
    "file-level check only — not validated in print. DTG on dark garments "
    "prints over a white underbase; ink on fabric is reflective, not emissive."
)

# ═══════════════════════════════════════════════════════════════════════
# END OF RULE DATA. Nothing below references a palette value literally.
# ═══════════════════════════════════════════════════════════════════════


class InputError(Exception):
    """Malformed input. Exit 2 — the tool cannot evaluate, it did not fail."""


class ConfigError(Exception):
    """Broken or missing rule data. Exit 2."""


EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ERROR = 2

_HEX_RE = re.compile(r"^[0-9A-Fa-f]+$")


# ─────────────────────────────── parsing ───────────────────────────────

def normalize_hex(raw):
    """'#d9a441' / 'D9A441' / ' #D9a441 ' / '#FFF' -> '#D9A441'.

    Rejects 8-digit/alpha hex and anything that is not 3 or 6 hex digits.
    Fails closed: raises InputError rather than guessing.
    """
    if raw is None:
        raise InputError("missing colour value")
    text = str(raw).strip()
    if not text:
        raise InputError("empty colour value — expected #RRGGBB")
    body = text[1:] if text.startswith("#") else text
    if not _HEX_RE.match(body):
        raise InputError(
            "'%s' is not a valid hex colour — expected #RRGGBB" % text
        )
    if len(body) == 8:
        raise InputError(
            "'%s' is 8-digit/alpha hex — alpha is not supported, "
            "expected #RRGGBB" % text
        )
    if len(body) == 3:
        body = "".join(ch * 2 for ch in body)
    if len(body) != 6:
        raise InputError(
            "'%s' has %d hex digits — expected 6 (#RRGGBB) or 3 (#RGB)"
            % (text, len(body))
        )
    return "#" + body.upper()


def normalize_garment_name(raw):
    """Case-insensitive, whitespace-tolerant. Never fuzzy-matched."""
    return " ".join(str(raw or "").strip().lower().split())


# ─────────────────────────── the contrast math ─────────────────────────
# Touches no palette value. Pure WCAG relative luminance.

def _channels(hex_color):
    body = hex_color.lstrip("#")
    return [int(body[i:i + 2], 16) for i in (0, 2, 4)]


def relative_luminance(hex_color):
    out = []
    for value in _channels(hex_color):
        c = value / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = out
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(hex_a, hex_b):
    la, lb = relative_luminance(hex_a), relative_luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def rgb_distance(hex_a, hex_b):
    a, b = _channels(hex_a), _channels(hex_b)
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def fmt_ratio(value):
    return "%.2f:1" % value


# ───────────────────────────── config guard ────────────────────────────

def validate_config():
    """Fail closed on broken or missing rule data. Raises ConfigError."""
    if not GARMENTS:
        raise ConfigError("no garments configured")
    if not PALETTES:
        raise ConfigError("no palettes configured")
    for key, value in THRESHOLDS.items():
        if not isinstance(value, (int, float)):
            raise ConfigError("threshold %s is not numeric" % key)
    for name, spec in GARMENTS.items():
        for field in ("hex", "class", "provisional"):
            if field not in spec:
                raise ConfigError("garment '%s' is missing '%s'" % (name, field))
        try:
            normalize_hex(spec["hex"])
        except InputError as exc:
            raise ConfigError("garment '%s' has a bad hex: %s" % (name, exc))
        if spec["class"] not in PALETTES:
            raise ConfigError(
                "garment '%s' has class '%s' with no palette"
                % (name, spec["class"])
            )
    for cls, palette in PALETTES.items():
        if not palette:
            raise ConfigError("palette for class '%s' is empty" % cls)
        for hex_color in palette:
            try:
                normalize_hex(hex_color)
            except InputError as exc:
                raise ConfigError("palette '%s' has a bad hex: %s" % (cls, exc))
    try:
        normalize_hex(OUTLINE["hex"])
    except (InputError, KeyError, TypeError) as exc:
        raise ConfigError("outline config is broken: %s" % exc)
    if not OUTLINE.get("allowed_classes"):
        raise ConfigError("outline config declares no allowed classes")
    for bar in EXPLICIT_BARS:
        for field in ("hex", "name", "garment", "reason"):
            if field not in bar:
                raise ConfigError("explicit bar is missing '%s'" % field)
        if normalize_garment_name(bar["garment"]) not in GARMENTS:
            raise ConfigError(
                "explicit bar names unknown garment '%s'" % bar["garment"]
            )


def rule_text(rule_id):
    return RULES[rule_id].format(
        max=THRESHOLDS["MAX_DESIGN_COLORS"],
        min=THRESHOLDS["MIN_CONTRAST"],
        classes="/".join(OUTLINE["allowed_classes"]),
    )


def _violation(rule_id, message):
    return {"rule": rule_id, "rule_text": rule_text(rule_id), "message": message}


def _find_bar(hex_color, garment_name):
    for bar in EXPLICIT_BARS:
        if (normalize_hex(bar["hex"]) == hex_color
                and normalize_garment_name(bar["garment"]) == garment_name):
            return bar
    return None


def _nearest_allowed(hex_color, palette):
    """Nearest allowlisted colour by simple RGB distance, or None."""
    best_hex, best_name, best_distance = None, None, None
    for candidate, name in palette.items():
        candidate = normalize_hex(candidate)
        distance = rgb_distance(hex_color, candidate)
        if best_distance is None or distance < best_distance:
            best_hex, best_name, best_distance = candidate, name, distance
    if best_distance is not None and best_distance <= NEAR_MISS_DISTANCE:
        return {"hex": best_hex, "name": best_name, "distance": best_distance}
    return None


# ──────────────────────────── the check itself ─────────────────────────

def run_check(garment_input, color_inputs, outline_input=None):
    """Return one report dict. Human and --json modes both render THIS,
    so the verdict can never differ between them.

    Raises InputError (exit 2) on malformed hex. Rule violations are
    reported in the returned dict with exit_code 1.
    """
    validate_config()

    min_contrast = THRESHOLDS["MIN_CONTRAST"]
    marginal_ceiling = min_contrast + THRESHOLDS["MARGINAL_BAND"]
    max_colors = THRESHOLDS["MAX_DESIGN_COLORS"]
    min_inter = THRESHOLDS["MIN_INTER_COLOR"]
    outline_warn = THRESHOLDS["OUTLINE_VISIBILITY_WARN"]
    outline_hex_canonical = normalize_hex(OUTLINE["hex"])

    report = {
        "verdict": "PASS",
        "exit_code": EXIT_PASS,
        "garment": None,
        "entries": [],
        "violations": [],
        "warnings": [],
        "notes": [],
        "design_color_count": 0,
        "max_design_colors": max_colors,
        "provisional": False,
        "provisional_warning": None,
        "thresholds": dict(THRESHOLDS),
        "disclaimer": FOOTER_NOTE,
    }

    def fail(rule_id, message):
        report["verdict"] = "FAIL"
        report["exit_code"] = EXIT_FAIL
        report["violations"].append(_violation(rule_id, message))

    # 1. PARSE — before anything else, so bad input is exit 2 not exit 1.
    parsed = [normalize_hex(value) for value in (color_inputs or [])]
    outline_hex = normalize_hex(outline_input) if outline_input is not None else None

    # 2. GARMENT LOOKUP — exact after normalisation. Never fuzzy-matched.
    garment_name = normalize_garment_name(garment_input)
    if garment_name not in GARMENTS:
        known = ", ".join(sorted(GARMENTS))
        fail("R6", "unknown garment '%s' — known garments: %s"
                   % (str(garment_input).strip(), known))
        report["known_garments"] = sorted(GARMENTS)
        return report

    garment = GARMENTS[garment_name]
    garment_hex = normalize_hex(garment["hex"])
    garment_class = garment["class"]
    palette = {normalize_hex(k): v for k, v in PALETTES[garment_class].items()}

    report["garment"] = {
        "name": garment_name,
        "hex": garment_hex,
        "class": garment_class,
        "provisional": bool(garment["provisional"]),
    }

    # PROVISIONAL garments warn in EVERY report. Never silent.
    if garment["provisional"]:
        warning = PROVISIONAL_WARNING.format(garment=garment_name)
        report["provisional"] = True
        report["provisional_warning"] = warning
        report["warnings"].append(warning)

    # 3. DEDUPE, case-insensitively (already normalised to canonical form).
    unique = []
    duplicates = {}
    for hex_color in parsed:
        if hex_color in unique:
            duplicates[hex_color] = duplicates.get(hex_color, 1) + 1
        else:
            unique.append(hex_color)
    if duplicates:
        detail = ", ".join(
            "%s x%d" % (h, n) for h, n in sorted(duplicates.items())
        )
        report["notes"].append(
            "DEDUPE: %d duplicate entr%s removed (%s) — %d unique design colour%s counted."
            % (len(parsed) - len(unique),
               "y" if len(parsed) - len(unique) == 1 else "ies",
               detail, len(unique), "" if len(unique) == 1 else "s")
        )
    report["dedupe"] = {
        "submitted": len(parsed),
        "unique": len(unique),
        "duplicates": duplicates,
    }
    report["design_color_count"] = len(unique)

    # 4. EMPTY CHECK. A design with no colours is a bug in the caller.
    if not unique:
        fail("R7", "no design colours supplied — an empty design cannot pass")

    # Per-colour evaluation: bar → allowlist → contrast.
    for hex_color in unique:
        entry = {
            "hex": hex_color,
            "name": palette.get(hex_color),
            "role": "design",
            "allowed": False,
            "ratio": None,
            "status": "",
            "counted": True,
            "notes": [],
            "rule": None,
        }
        ratio = contrast_ratio(hex_color, garment_hex)

        # 5. EXPLICIT BAR — before the allowlist, so the reason is specific.
        bar = _find_bar(hex_color, garment_name)
        if bar is not None:
            entry["name"] = bar["name"]
            entry["status"] = bar["reason"]
            entry["rule"] = "R4"
            fail("R4", "%s %s — %s" % (bar["name"], hex_color, bar["reason"]))
            report["entries"].append(entry)
            continue

        # 6. ALLOWLIST — exact match. A near-miss shade is not the colour.
        if hex_color not in palette:
            message = ("%s is not on the %s-garment allowlist — measured "
                       "%s against %s %s (rule R2)"
                       % (hex_color, garment_class, fmt_ratio(ratio),
                          garment_name, garment_hex))
            if hex_color == outline_hex_canonical:
                hint = ("this is the outline colour — declare the role "
                        "explicitly with --outline; it is never inferred")
                entry["notes"].append(hint)
                message += " — " + hint
            else:
                near = _nearest_allowed(hex_color, palette)
                if near is not None:
                    hint = "did you mean %s %s?" % (near["name"], near["hex"])
                    entry["notes"].append(hint)
                    message += " — " + hint
            entry["status"] = "not on allowlist"
            entry["rule"] = "R2"
            entry["ratio"] = round(ratio, 2)
            fail("R2", message)
            report["entries"].append(entry)
            continue

        # 7. CONTRAST vs the SPECIFIC GARMENT HEX, never the class.
        entry["allowed"] = True
        entry["ratio"] = round(ratio, 2)
        if ratio < min_contrast:
            entry["status"] = "below %.1f floor" % min_contrast
            entry["rule"] = "R3"
            fail("R3", "%s %s is %s against %s %s — below the %.1f:1 floor"
                       % (palette[hex_color], hex_color, fmt_ratio(ratio),
                          garment_name, garment_hex, min_contrast))
        elif ratio < marginal_ceiling:
            entry["status"] = "MARGINAL"
            note = ("%s — passes, but within measurement error of the floor. "
                    "Garment dye lots vary." % fmt_ratio(ratio))
            entry["notes"].append(note)
            report["warnings"].append(
                "MARGINAL: %s %s %s" % (palette[hex_color], hex_color, note)
            )
        else:
            entry["status"] = "OK"
        report["entries"].append(entry)

    # OUTLINE — declared role only. Uncounted, exempt from the floor,
    # ratio ALWAYS reported.
    if outline_hex is not None:
        entry = {
            "hex": outline_hex,
            "name": OUTLINE["name"],
            "role": "outline",
            "allowed": False,
            "ratio": round(contrast_ratio(outline_hex, garment_hex), 2),
            "status": "",
            "counted": False,
            "notes": [],
            "rule": None,
        }
        ratio = contrast_ratio(outline_hex, garment_hex)
        if outline_hex != outline_hex_canonical:
            entry["name"] = None
            entry["status"] = "not the allowed outline colour"
            entry["rule"] = "R2"
            fail("R2", "outline %s is not the allowed outline colour %s — "
                       "measured %s against %s"
                       % (outline_hex, outline_hex_canonical,
                          fmt_ratio(ratio), garment_name))
        elif garment_class not in OUTLINE["allowed_classes"]:
            entry["status"] = "outline not permitted on %s garments" % garment_class
            entry["rule"] = "R5"
            fail("R5", "outline %s is not permitted on %s (%s class) — "
                       "outline is %s-only; measured %s against the garment"
                       % (outline_hex, garment_name, garment_class,
                          "/".join(OUTLINE["allowed_classes"]), fmt_ratio(ratio)))
        else:
            entry["allowed"] = True
            entry["status"] = "outline role, not counted"
            if ratio > outline_warn:
                warning = (
                    "outline may read as a visible ring on this garment, not a "
                    "hidden one — verify against D-311 intent."
                )
                entry["notes"].append("%s — %s" % (fmt_ratio(ratio), warning))
                report["warnings"].append(
                    "OUTLINE: %s vs %s = %s — %s"
                    % (outline_hex, garment_name, fmt_ratio(ratio), warning)
                )
        report["entries"].append(entry)

    # 8. COLOUR COUNT — after dedupe, outline excluded.
    if len(unique) > max_colors:
        fail("R1", "%d design colours after dedupe, max is %d (outline "
                   "excluded)" % (len(unique), max_colors))

    # 9. INTER-COLOUR CONTRAST — WARN, never FAIL: two low-contrast colours
    # are fine if they never touch, and this tool cannot see the art.
    inter = []
    for a, b in combinations(unique, 2):
        ratio = contrast_ratio(a, b)
        pair = {
            "a": a, "b": b,
            "a_name": palette.get(a), "b_name": palette.get(b),
            "ratio": round(ratio, 2),
            "below_floor": ratio < min_inter,
        }
        inter.append(pair)
        if ratio < min_inter:
            label_a = "%s %s" % (palette[a], a) if a in palette else a
            label_b = "%s %s" % (palette[b], b) if b in palette else b
            report["warnings"].append(
                "%s vs %s = %s. These are the same value in different hues. "
                "If they touch in the art, the design reads as one blob at "
                "thumbnail size (brandkit PERCEPTION LAW 1)."
                % (label_a, label_b, fmt_ratio(ratio))
            )
    report["inter_color"] = inter

    return report


# ───────────────────────────── rendering ───────────────────────────────

def render_human(report):
    lines = []
    garment = report["garment"]
    if garment:
        lines.append("══ COLOR CHECK ══  garment: %s (%s, %s)"
                     % (garment["name"], garment["hex"], garment["class"]))
    else:
        lines.append("══ COLOR CHECK ══  garment: UNKNOWN")
    lines.append("VERDICT: %s" % report["verdict"])

    if report.get("provisional_warning"):
        lines.append("")
        lines.append("PROVISIONAL: %s" % report["provisional_warning"])

    if report["entries"]:
        lines.append("")
        for entry in report["entries"]:
            name = entry["name"] or "unknown"
            if entry["role"] == "outline":
                name = "outline"
            allowed = "allowed" if entry["allowed"] else "NOT ALLOWED"
            ratio = fmt_ratio(entry["ratio"]) if entry["ratio"] is not None else "--"
            lines.append("%-8s %-14s %-12s %-9s %s"
                         % (entry["hex"], name, allowed, ratio, entry["status"]))
            for note in entry["notes"]:
                lines.append("%s↳ %s" % (" " * 9, note))

    if garment:
        count_line = ("DESIGN COLORS: %d of max %d"
                      % (report["design_color_count"], report["max_design_colors"]))
        if report["design_color_count"] > report["max_design_colors"]:
            count_line += "  → RULE 1 VIOLATED"
        lines.append("")
        lines.append(count_line)

    for note in report["notes"]:
        lines.append(note)

    for violation in report["violations"]:
        lines.append("FAIL [%s]: %s" % (violation["rule"], violation["message"]))

    for warning in report["warnings"]:
        lines.append("WARN: %s" % warning)

    lines.append("NOTE: %s" % report["disclaimer"])
    return "\n".join(lines)


def render_json(report):
    return json.dumps(report, indent=2, sort_keys=True)


# ─────────────────────────── auxiliary modes ───────────────────────────

def list_garments(as_json):
    validate_config()
    payload = []
    for name in sorted(GARMENTS):
        spec = GARMENTS[name]
        payload.append({
            "name": name,
            "hex": normalize_hex(spec["hex"]),
            "class": spec["class"],
            "provisional": bool(spec["provisional"]),
            "allowed_colors": [
                {"hex": normalize_hex(h), "name": n}
                for h, n in PALETTES[spec["class"]].items()
            ],
            "outline_allowed": spec["class"] in OUTLINE["allowed_classes"],
        })
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return EXIT_PASS
    print("══ KNOWN GARMENTS ══")
    for item in payload:
        flag = "  PROVISIONAL" if item["provisional"] else ""
        print("\n%s (%s, %s)%s" % (item["name"], item["hex"], item["class"], flag))
        if item["provisional"]:
            print("  %s" % PROVISIONAL_WARNING.format(garment=item["name"]))
        for color in item["allowed_colors"]:
            ratio = contrast_ratio(color["hex"], item["hex"])
            print("  %-8s %-14s %s" % (color["hex"], color["name"], fmt_ratio(ratio)))
        if item["outline_allowed"]:
            ratio = contrast_ratio(normalize_hex(OUTLINE["hex"]), item["hex"])
            print("  %-8s %-14s %s  (declare with --outline)"
                  % (normalize_hex(OUTLINE["hex"]), "outline", fmt_ratio(ratio)))
    print("\nNOTE: %s" % FOOTER_NOTE)
    return EXIT_PASS


def audit_rules(as_json):
    """Audit the RULE DATA, not the code. Every allowlisted colour on every
    garment its class allows must clear MIN_CONTRAST. Exit 1 if the palette
    itself violates the floor."""
    validate_config()
    min_contrast = THRESHOLDS["MIN_CONTRAST"]
    marginal_ceiling = min_contrast + THRESHOLDS["MARGINAL_BAND"]
    min_inter = THRESHOLDS["MIN_INTER_COLOR"]

    rows, failures = [], []
    for garment_name in sorted(GARMENTS):
        spec = GARMENTS[garment_name]
        garment_hex = normalize_hex(spec["hex"])
        for hex_color, color_name in PALETTES[spec["class"]].items():
            hex_color = normalize_hex(hex_color)
            ratio = contrast_ratio(hex_color, garment_hex)
            status = ("FAIL" if ratio < min_contrast
                      else "MARGINAL" if ratio < marginal_ceiling else "OK")
            row = {
                "garment": garment_name, "garment_hex": garment_hex,
                "class": spec["class"], "color": color_name, "hex": hex_color,
                "ratio": round(ratio, 2), "status": status,
            }
            rows.append(row)
            if status == "FAIL":
                failures.append(row)
        if spec["class"] in OUTLINE["allowed_classes"]:
            outline_hex = normalize_hex(OUTLINE["hex"])
            rows.append({
                "garment": garment_name, "garment_hex": garment_hex,
                "class": spec["class"], "color": OUTLINE["name"],
                "hex": outline_hex,
                "ratio": round(contrast_ratio(outline_hex, garment_hex), 2),
                "status": "EXEMPT (outline)",
            })

    pairs = []
    for cls in sorted(PALETTES):
        palette = {normalize_hex(k): v for k, v in PALETTES[cls].items()}
        for a, b in combinations(sorted(palette), 2):
            ratio = contrast_ratio(a, b)
            pairs.append({
                "class": cls, "a": a, "a_name": palette[a],
                "b": b, "b_name": palette[b], "ratio": round(ratio, 2),
                "mud_pair": ratio < min_inter,
            })

    exit_code = EXIT_FAIL if failures else EXIT_PASS
    if as_json:
        print(json.dumps({
            "verdict": "FAIL" if failures else "PASS",
            "exit_code": exit_code,
            "contrast_audit": rows,
            "inter_color_audit": pairs,
            "failures": failures,
            "thresholds": dict(THRESHOLDS),
            "disclaimer": FOOTER_NOTE,
        }, indent=2, sort_keys=True))
        return exit_code

    print("══ RULE AUDIT ══  every allowlisted colour vs every garment of its class")
    print("VERDICT: %s" % ("FAIL" if failures else "PASS"))
    print()
    for row in rows:
        print("%-13s %-8s %-14s %-9s %s"
              % (row["garment"], row["hex"], row["color"],
                 fmt_ratio(row["ratio"]), row["status"]))
    print("\n══ INTER-COLOUR AUDIT ══  mutual ratio of every allowed pair")
    for pair in pairs:
        flag = "  MUD PAIR (< %.1f:1)" % min_inter if pair["mud_pair"] else ""
        print("%-6s %-14s vs %-14s %s%s"
              % (pair["class"], pair["a_name"], pair["b_name"],
                 fmt_ratio(pair["ratio"]), flag))
    if failures:
        print("\nRULE DATA VIOLATES THE %.1f:1 FLOOR:" % min_contrast)
        for row in failures:
            print("  %s %s on %s = %s"
                  % (row["color"], row["hex"], row["garment"],
                     fmt_ratio(row["ratio"])))
    print("\nNOTE: %s" % FOOTER_NOTE)
    return exit_code


# ─────────────────────────────── the CLI ───────────────────────────────

EPILOG = """\
exit codes:
  0  PASS
  1  FAIL   the design violated a rule (or the garment is unknown)
  2  ERROR  malformed hex, or broken rule config

SCOPE: this validates the DESIGN FILE, not the printed shirt. DTG on dark
garments prints over a white underbase, and reflective ink on fabric does not
behave like emissive pixels on a screen. A PASS here is a file-level PASS only.

examples:
  color_check.py "black" "#D9A441" "#7A9CB0"
  color_check.py "black" "#D9A441" --outline "#0C0C0C"
  color_check.py "sport grey" "#3E5C46" --json
  color_check.py --list-garments
  color_check.py --audit-rules
"""


# Options are extracted before positionals so that colours may appear on
# either side of a flag: `black --outline "#0C0C0C" "#D9A441"` and
# `black "#D9A441" --outline "#0C0C0C"` are the same command. argparse
# cannot split positionals around an option on its own.
_VALUE_OPTIONS = ("--outline",)
_FLAG_OPTIONS = ("--json", "--list-garments", "--audit-rules", "-h", "--help")


def reorder_argv(argv):
    """Return argv with every option moved after the positionals."""
    positionals, options = [], []
    tokens = list(argv)
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            positionals.extend(tokens[index + 1:])
            break
        name = token.split("=", 1)[0] if token.startswith("--") else token
        if name in _VALUE_OPTIONS:
            options.append(token)
            if "=" not in token and index + 1 < len(tokens):
                index += 1
                options.append(tokens[index])
        elif name in _FLAG_OPTIONS:
            options.append(token)
        elif token.startswith("-") and len(token) > 1:
            # Unrecognised option: hand it to argparse so it errors properly.
            options.append(token)
        else:
            positionals.append(token)
        index += 1
    return positionals + options


def build_parser():
    parser = argparse.ArgumentParser(
        prog="color_check.py",
        description="KCT design colour validator — a hard gate, not an "
                    "advisor. Fails closed: if it is not explicitly allowed, "
                    "it fails.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("garment", nargs="?",
                        help="garment name (case-insensitive)")
    parser.add_argument("colors", nargs="*",
                        help="design colours as #RRGGBB, RRGGBB, or #RGB")
    parser.add_argument("--outline", metavar="HEX", default=None,
                        help="declare a colour as the outline role. Never "
                             "inferred from the hex — the tool cannot see the "
                             "art. Uncounted and exempt from the contrast "
                             "floor; dark garments only.")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable output; same verdict as human mode")
    parser.add_argument("--list-garments", action="store_true",
                        help="list known garments and their allowed palettes")
    parser.add_argument("--audit-rules", action="store_true",
                        help="audit the rule data itself: every allowlisted "
                             "colour vs every garment of its class")
    return parser


def main(argv=None):
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    args = parser.parse_args(reorder_argv(argv))

    try:
        if args.list_garments:
            return list_garments(args.json)
        if args.audit_rules:
            return audit_rules(args.json)

        if args.garment is None:
            raise InputError(
                "no garment supplied — usage: color_check.py GARMENT "
                "HEX [HEX ...] [--outline HEX]"
            )

        report = run_check(args.garment, args.colors, args.outline)
        print(render_json(report) if args.json else render_human(report))
        return report["exit_code"]

    except InputError as exc:
        _emit_error("INPUT", str(exc), args.json)
        return EXIT_ERROR
    except ConfigError as exc:
        _emit_error("CONFIG", str(exc), args.json)
        return EXIT_ERROR


def _emit_error(kind, message, as_json):
    if as_json:
        print(json.dumps({
            "verdict": "ERROR",
            "exit_code": EXIT_ERROR,
            "error_type": kind,
            "error": message,
            "disclaimer": FOOTER_NOTE,
        }, indent=2, sort_keys=True))
    else:
        sys.stderr.write("ERROR [%s]: %s\n" % (kind, message))
        sys.stderr.write("NOTE: %s\n" % FOOTER_NOTE)


if __name__ == "__main__":
    sys.exit(main())
