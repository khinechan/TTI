"""strength_core (STD) — chart strength and favorable elements, by the standard hidden-stem method (outside THE MATH
§1–§12). No chart is built in: the four pillars are inputs, as 2-character strings ("庚申").

element of a stem   e(s) = ELEMENTS[⌊s/2⌋]   (as in bazi_core)
element totals      T[e] = Σ_{visible stems except the day master} 1.0·[e(s) = e]
                         + Σ_{branches} m_b · Σ_k w_k · [e(h_k) = e]
                    h_k = the branch's hidden stems (HIDDEN, main stem first) · w = HIDDEN_W[number of hidden stems]
                    m_b = 2.0 for the month branch (season), 1.0 otherwise · the month STEM is not doubled
                    a missing hour pillar (None) is skipped and the result is flagged partial
family              relative to the day master's element d: peer e = d · output GEN[d] = e · wealth CTL[d] = e
                    · officer CTL[e] = d · resource GEN[e] = d
strength            S = (peer + resource) / Σ_e T[e]
favorability        S < 0.45 weak: peer, resource +1, output, wealth, officer −1 · S > 0.55 strong: the reverse
                    · otherwise balanced: all 0 · then fire +0.5 if the month branch ∈ 申酉戌亥子丑,
                    water +0.5 if it ∈ 巳午未 · clip every F[e] to [−1, 1]
Usage: chart_strength(["庚申", "甲申", "壬申", None]) → dict(dm, dm_element, totals, S, verdict, F, partial)"""
import bazi_core as Z

HIDDEN = {"子": "癸", "丑": "己癸辛", "寅": "甲丙戊", "卯": "乙", "辰": "戊乙癸", "巳": "丙庚戊",
          "午": "丁己", "未": "己丁乙", "申": "庚壬戊", "酉": "辛", "戌": "戊辛丁", "亥": "壬甲"}   # branch → hidden stems, main first
HIDDEN_W = {1: [1.0], 2: [0.7, 0.3], 3: [0.6, 0.3, 0.1]}   # hidden-stem weights, by how many stems the branch holds
VISIBLE_W = 1.0                     # each visible stem (the day pillar's own stem, the day master, is left out)
MONTH_W = 2.0                       # the month branch's hidden stems count double (season); the month stem does not
WEAK_BELOW, STRONG_ABOVE = 0.45, 0.55   # S < 0.45 weak · S > 0.55 strong · otherwise balanced
SEASON_FIRE = "申酉戌亥子丑"         # autumn and winter months: the chart wants warmth, fire +0.5
SEASON_WATER = "巳午未"              # summer months: the chart wants cooling, water +0.5
SEASON_BUMP = 0.5                   # the size of the season bump
GEN = {"wood": "fire", "fire": "earth", "earth": "metal", "metal": "water", "water": "wood"}   # generating cycle
CTL = {"wood": "earth", "earth": "water", "water": "fire", "fire": "metal", "metal": "wood"}   # control cycle
SUPPORT = ("peer", "resource")      # the families that strengthen the day master
PILLARS = ("year", "month", "day", "hour")   # the input order


def element_of(stem):
    """e(s) = ELEMENTS[⌊s/2⌋]."""
    return Z.ELEMENTS[Z.STEMS.index(stem) // 2]


def _check(name, p):
    if not (isinstance(p, str) and len(p) == 2 and p[0] in Z.STEMS and p[1] in Z.BRANCHES):
        raise ValueError("%s pillar must be a stem + a branch, e.g. '庚申'; got %r" % (name, p))


def element_totals(pillars):
    """pillars = [year, month, day, hour or None] → ({element: T[e]} over all five elements, partial)."""
    if len(pillars) != 4: raise ValueError("pillars = [year, month, day, hour or None]; got %d items" % len(pillars))
    T = {e: 0.0 for e in Z.ELEMENTS}; partial = pillars[3] is None
    for k, p in enumerate(pillars):
        if k == 3 and partial: continue
        _check(PILLARS[k], p)
        if k != 2: T[element_of(p[0])] += VISIBLE_W
        hs, m = HIDDEN[p[1]], (MONTH_W if k == 1 else 1.0)
        for h, w in zip(hs, HIDDEN_W[len(hs)]): T[element_of(h)] += m * w
    return T, partial


def family(d, e):
    """e's family relative to the day master's element d, read off the GEN and CTL cycles."""
    if e == d: return "peer"
    if GEN[d] == e: return "output"
    if CTL[d] == e: return "wealth"
    if CTL[e] == d: return "officer"
    return "resource"


def strength(totals, dm_element):
    """S = (peer + resource) / Σ totals."""
    return sum(v for e, v in totals.items() if family(dm_element, e) in SUPPORT) / sum(totals.values())


def verdict(S, lo=WEAK_BELOW, hi=STRONG_ABOVE):
    return "weak" if S < lo else "strong" if S > hi else "balanced"


def favorability(dm_element, S, month_branch, lo=WEAK_BELOW, hi=STRONG_ABOVE):
    """F[e] ∈ [−1, 1]: weak → support +1, the rest −1 · strong → the reverse · balanced → 0; then the season bump."""
    if not (isinstance(month_branch, str) and len(month_branch) == 1 and month_branch in Z.BRANCHES):
        raise ValueError("month_branch must be one of %s; got %r" % (Z.BRANCHES, month_branch))
    v = verdict(S, lo, hi); F = {}
    for e in Z.ELEMENTS:
        sup = 1.0 if family(dm_element, e) in SUPPORT else -1.0
        F[e] = 0.0 if v == "balanced" else sup if v == "weak" else -sup
    if month_branch in SEASON_FIRE: F["fire"] += SEASON_BUMP
    if month_branch in SEASON_WATER: F["water"] += SEASON_BUMP
    return {e: max(-1.0, min(1.0, f)) for e, f in F.items()}


def chart_strength(pillars):
    """Everything at once: dict(dm, dm_element, totals, S, verdict, F, partial)."""
    T, partial = element_totals(pillars); dm = pillars[2][0]; d = element_of(dm); S = strength(T, d)
    return dict(dm=dm, dm_element=d, totals=T, S=S, verdict=verdict(S), F=favorability(d, S, pillars[1][1]), partial=partial)
