"""color_core (STD) — §13 outfit color, a STORY MECHANIC. A garment's color maps to the five elements by a standard
five-element color table, and that vector nudges two existing numbers: the wearer's §7 day charge and the viewer's
§9 pull. The colors move the numbers only because this model defines them to, so nothing here proves anything about
colors. It is off unless an outfit is passed. No chart, date or place is built in: every input is passed.

outfit vector  E[e] = Σ_g c_g · w(color_g, e) / Σ_g c_g        c = SLOT_W[slot] · w = COLORS[color] · Σ_e E[e] = 1
taste          T = Σ_g c_g · [color_g ∈ VENUS_PALETTE[the viewer's natal Venus sign]] / Σ_g c_g
wearer         W = Σ_e E[e] · F_wearer[e] ∈ [−1, 1] · raw′ = raw − K_SELF · W · charge′ = bazi_core.rescale(raw′), tier(charge′)
viewer         V = ALPHA · Σ_e E[e] · F_viewer[e] + (1 − ALPHA) · T · m = 1 + K_VIEW · V
               day pull  = (Σ w·s / Σ w) / top × 10                                   (not capped: today's value)
               day pull′ = min(PULL_CAP, Σ w·s·(m if the sample's block is seen else 1) / Σ w / top × 10)
               seen block: pull = (Σ_block w·s / Σ_block w) / top × 10 · pull′ = min(PULL_CAP, pull · m); others unchanged
               color multiplies pull, so a zero-pull day stays zero
role tag       the dominant element of E (a tie, within TIE_EPS, goes to the earlier of wood, fire, earth, metal, water),
               as its family relative to a day master's element (strength_core.family) → ROLE_LABEL. A label only, no number.
F (favorability) comes from strength_core; element_totals, strength and favorability are re-exported here.
Usage: E = outfit_vector([{"slot": "top", "color": "green"}, {"slot": "bottom", "color": "silver"}])
       wearer_effect(E, F_wearer, raw) · viewer_effect(E, F_viewer, taste(outfit, "Cancer"), samples, weights, block_of, top)"""
import astro_core as A
import bazi_core as Z
import strength_core as SC
from strength_core import element_totals, strength, favorability   # re-exported: color_core provides them too

ELEMENTS = Z.ELEMENTS
COLORS = {   # color token → {element: weight}, every row sums to 1 (STD five-element colors; editable)
    **{c: {"wood": 1.0} for c in ("green", "forest green", "dark green")},
    "sea green": {"wood": 0.7, "water": 0.3}, "teal": {"wood": 0.6, "water": 0.4},
    "olive": {"wood": 0.5, "earth": 0.5}, "olive brown": {"wood": 0.3, "earth": 0.7},
    **{c: {"fire": 1.0} for c in ("red", "orange", "orange-red", "pink", "purple")},
    "burgundy": {"fire": 0.7, "water": 0.3}, "russet brown": {"earth": 0.7, "fire": 0.3},
    **{c: {"earth": 1.0} for c in ("brown", "dark brown", "khaki", "tan", "beige", "camel", "yellow", "mustard")},
    "cream": {"earth": 0.5, "metal": 0.5}, "ivory": {"metal": 0.8, "earth": 0.2},
    **{c: {"metal": 1.0} for c in ("white", "pearl", "silver", "grey", "gold")},
    "charcoal": {"metal": 0.6, "water": 0.4},
    **{c: {"water": 1.0} for c in ("black", "navy", "dark blue", "royal blue", "blue", "denim")},
    "light blue": {"water": 0.6, "wood": 0.4},
}
SLOT_W = {"top": 0.55, "bottom": 0.30, "peek": 0.10, "shoes": 0.05, "accessory": 0.05}   # coverage c; peek = an under-layer that shows
VENUS_PALETTE = {   # natal Venus sign → the colors that sign likes (STD Western; editable), Aries … Pisces in order
    "Aries": ("red",), "Taurus": ("green", "pink"), "Gemini": ("yellow", "light blue"),
    "Cancer": ("silver", "white", "pearl", "cream", "sea green"), "Leo": ("gold", "orange"),
    "Virgo": ("navy", "brown", "green"), "Libra": ("pink", "light blue"), "Scorpio": ("black", "burgundy"),
    "Sagittarius": ("purple",), "Capricorn": ("brown", "black", "grey"), "Aquarius": ("teal", "royal blue"),
    "Pisces": ("sea green", "purple"),
}
COLOR_PARAMS = {
    "K_SELF": 10.0,       # raw §7 points moved by a fully (un)favorable outfit on its wearer: raw′ = raw − K_SELF·W
    "K_VIEW": 0.25,       # the viewer's pull multiplier swing: m = 1 + K_VIEW·V, so m ∈ [0.75, 1.25]
    "ALPHA": 0.7,         # V's share from the viewer's favorability; 1 − ALPHA comes from Venus-sign taste
    "SEEN": "辰巳午未申",  # default two-hour blocks when the viewer sees the wearer (07:00–16:59)
    "PULL_CAP": 10.0,     # the 0–10 pull scale's ceiling after color
}
ROLE_LABEL = {"output": "play, enjoyment", "wealth": "warmth, desire", "officer": "duty, husband (for a woman), rules",
              "resource": "comfort, care", "peer": "sameness, rivalry"}   # story labels for role_tag
TIE_EPS = 1e-9        # role_tag: E values within this of the top are a tie (float noise must not break the tie rule)
# ---------- end of constants ----------
SIGN_FULL = dict(zip(A.SIGNS, VENUS_PALETTE))   # astro_core abbreviation → full sign name ("Can" → "Cancer")


def norm_color(c):
    """Lowercase, strip, collapse inner whitespace; hyphens kept: ' Forest  GREEN ' → 'forest green'."""
    return " ".join(str(c).lower().split())


def garments(outfit):
    """[(c_g, color token)], every slot and color checked. ValueError on an empty outfit, an unknown slot or color."""
    if not outfit: raise ValueError("empty outfit: give at least one {'slot': ..., 'color': ...}")
    out = []
    for g in outfit:
        s, c = g.get("slot"), norm_color(g.get("color"))
        if s not in SLOT_W: raise ValueError("unknown slot %r; known slots: %s" % (s, ", ".join(SLOT_W)))
        if c not in COLORS: raise ValueError("unknown color %r; known colors: %s" % (g.get("color"), ", ".join(sorted(COLORS))))
        out.append((SLOT_W[s], c))
    return out


def outfit_vector(outfit):
    """E[e] = Σ c_g·w(color_g, e) / Σ c_g over all five elements (0.0 where absent). Slots may repeat."""
    G = garments(outfit); tot = sum(c for c, _ in G)
    return {e: sum(c * COLORS[k].get(e, 0.0) for c, k in G) / tot for e in ELEMENTS}


def taste(outfit, venus_sign):
    """T = the coverage share of garments whose color is in the palette of venus_sign ("Cancer" or "Can")."""
    sign = SIGN_FULL.get(venus_sign, venus_sign)
    if sign not in VENUS_PALETTE:
        raise ValueError("unknown Venus sign %r; known: %s" % (venus_sign, ", ".join(list(VENUS_PALETTE) + list(SIGN_FULL))))
    G = garments(outfit)
    return sum(c for c, k in G if k in VENUS_PALETTE[sign]) / sum(c for c, _ in G)


def wearer_effect(E, F_wearer, raw, params=COLOR_PARAMS):
    """W = Σ E·F_wearer · raw′ = raw − K_SELF·W · charge and tier through bazi_core.rescale / bazi_core.tier."""
    W = sum(E[e] * F_wearer[e] for e in ELEMENTS); after = raw - params["K_SELF"] * W
    cb, ca = Z.rescale(raw), Z.rescale(after)
    return dict(W=W, raw_before=raw, raw_after=after, charge_before=cb, charge_after=ca,
                tier_before=Z.tier(cb), tier_after=Z.tier(ca))


def viewer_effect(E, F_viewer, T, samples, weights, block_of, top, seen=None, params=COLOR_PARAMS):
    """The viewer's day pull and seen-block pulls, before and after color (unrounded).
       samples = the day's moment scores, weights = per-sample weights (½ on a repeated DST hour),
       block_of = each sample's hour-branch character, top = the reference window's top day score."""
    seen = params["SEEN"] if seen is None else seen
    if not len(samples) == len(weights) == len(block_of):
        raise ValueError("samples, weights and block_of differ in length: %d, %d, %d" % (len(samples), len(weights), len(block_of)))
    ok = set(Z.BRANCHES); bad = sorted({b for b in list(seen) + list(block_of) if b not in ok}, key=repr)   # per char
    if bad: raise ValueError("not hour branches: %s; known: %s" % (" ".join(map(repr, bad)), Z.BRANCHES))
    if min(weights, default=-1) < 0 or sum(weights) <= 0 or top <= 0:
        raise ValueError("weights must be ≥ 0 with a positive sum, and top > 0")
    V = params["ALPHA"] * sum(E[e] * F_viewer[e] for e in ELEMENTS) + (1 - params["ALPHA"]) * T
    m, cap, sw = 1 + params["K_VIEW"] * V, params["PULL_CAP"], sum(weights)
    rows = list(zip(samples, weights, block_of))
    before = sum(w * s for s, w, _ in rows) / sw / top * 10
    after = min(cap, sum(w * s * (m if b in seen else 1) for s, w, b in rows) / sw / top * 10)
    blocks = {}
    for br in Z.BRANCHES:
        bw = sum(w for _, w, b in rows if b == br)
        if br not in seen or bw == 0: continue
        pb = sum(w * s for s, w, b in rows if b == br) / bw / top * 10
        blocks[br] = (pb, min(cap, pb * m))
    return dict(V=V, T=T, multiplier=m, day_pull_before=before, day_pull_after=after, blocks=blocks)


def role_tag(E, dm_element):
    """(family, label) of E's dominant element relative to dm_element. A tie (values within TIE_EPS, so float noise
       cannot break it) goes to the earlier element in wood, fire, earth, metal, water."""
    top = max(E[e] for e in ELEMENTS)
    fam = SC.family(dm_element, next(e for e in ELEMENTS if E[e] >= top - TIE_EPS))
    return fam, ROLE_LABEL[fam]
