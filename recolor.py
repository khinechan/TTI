#!/usr/bin/env python3
"""recolor.py — the alpha-preserving recolor helper (MC FLEET B3, W5).

Shipped as a reusable module for B2's render-time recolouring. This
module NEVER pre-generates pool variants and asset_ingest never calls
it during ingest (W5 scope cut: no recolours at ingest). Taste lives
in kct-brandkit v5.2; the colour pool lives in color_check.py.

The rule: a > 0 -> new RGB, keep a. VERIFIED (court, 2026-09-01):
~30% of an anti-aliased shape's pixels are blended edge — thresholding
or flood-filling by colour destroys that edge; replacing the RGB
channels wholesale while leaving alpha untouched preserves it exactly.
Fully-transparent pixels also get the new RGB (invisible, and it
guarantees ZERO old-hue pixels survive anywhere — no halo when a
downstream tool resamples).

Requires Pillow (already in the fleet via thumb_check).
"""

import re

from PIL import Image

# ═══════════════════════════════════════════════════════════════════════
# RULE DATA.
# ═══════════════════════════════════════════════════════════════════════

HEX_PATTERN = re.compile(r"^#([0-9A-Fa-f]{6})$")

# ═══════════════════════════════════════════════════════════════════════
# END OF RULE DATA.
# ═══════════════════════════════════════════════════════════════════════


def parse_hex(value):
    """'#RRGGBB' -> (r, g, b). Anything else raises ValueError — fail
    closed, no colour guessing."""
    match = HEX_PATTERN.match(value if isinstance(value, str) else "")
    if not match:
        raise ValueError("not a #RRGGBB hex colour: %r" % (value,))
    digits = match.group(1)
    return tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))


def recolor(image, color):
    """Return a NEW RGBA image: every pixel's RGB replaced with
    `color` ('#RRGGBB' or an (r, g, b) tuple), alpha channel copied
    byte-for-byte from the input. The input image is not modified and
    not closed. Non-RGBA inputs are converted first (an image with no
    alpha recolors to a solid rectangle — that is what no alpha
    means, not an error)."""
    rgb = parse_hex(color) if isinstance(color, str) else tuple(color)
    if len(rgb) != 3 or any(not (0 <= c <= 255) for c in rgb):
        raise ValueError("not an (r, g, b) triple 0-255: %r" % (rgb,))
    rgba = image if image.mode == "RGBA" else image.convert("RGBA")
    alpha = rgba.getchannel("A")
    channels = [Image.new("L", rgba.size, c) for c in rgb]
    result = Image.merge("RGBA", (*channels, alpha))
    if rgba is not image:
        rgba.close()
    return result
