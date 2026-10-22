"""bazi_core — the BaZi math, as modular arithmetic. No chart is built in: branches, stems and
day masters are inputs.

Indexing: stems  s ∈ 0..9  (甲 0 … 癸 9)  · element e = ⌊s/2⌋ (0 wood, 1 fire, 2 earth, 3 metal, 4 water)
                                         · polarity p = s mod 2 (0 yang, 1 yin)
          branches i ∈ 0..11 (子 0 … 亥 11) · sexagenary index g ∈ 0..59 (甲子 0): stem g mod 10, branch g mod 12
"""
import math

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
ELEMENTS = ["wood", "fire", "earth", "metal", "water"]


# ---------- calendar ----------
def jdn(y, m, d):
    """Julian Day Number (Gregorian):
       a = ⌊(14 − m)/12⌋, y' = y + 4800 − a, m' = m + 12a − 3
       JDN = d + ⌊(153m' + 2)/5⌋ + 365y' + ⌊y'/4⌋ − ⌊y'/100⌋ + ⌊y'/400⌋ − 32045"""
    a = (14 - m) // 12; yy = y + 4800 - a; mm = m + 12 * a - 3
    return d + (153 * mm + 2) // 5 + 365 * yy + yy // 4 - yy // 100 + yy // 400 - 32045


def civil_from_jdn(J):
    """Inverse of jdn(): Julian Day Number → (y, m, d) (Gregorian)."""
    a = J + 32044; b = (4 * a + 3) // 146097; c = a - 146097 * b // 4
    d = (4 * c + 3) // 1461; e = c - 1461 * d // 4; m = (5 * e + 2) // 153
    return 100 * b + d - 4800 + m // 10, m + 3 - 12 * (m // 10), e - (153 * m + 2) // 5 + 1


def day_index(y, m, d, hour_local=12.0, flip_hour=23.0):
    """g = (JDN + 49) mod 60. The BaZi day starts at 23:00 local, so a time ≥ flip_hour counts as the next day."""
    j = jdn(y, m, d) + (1 if hour_local >= flip_hour else 0)
    return (j + 49) % 60


def pillar_name(g):
    return STEMS[g % 10] + BRANCHES[g % 12]


def hour_branch(hour_local):
    """Two-hour blocks: i = ⌊(h + 1)/2⌋ mod 12 → 子 = 23:00–00:59, 丑 = 01:00–02:59, …, 亥 = 21:00–22:59."""
    return BRANCHES[int((hour_local + 1) // 2) % 12]


# ---------- branch relations (all as arithmetic on i, j) ----------
PENALTY_SETS = [{2, 5, 8}, {1, 7, 10}, {0, 3}]   # 寅巳申 · 丑未戌 · 子卯 (any two members)
SELF_PENALTY = {4, 6, 9, 11}                       # 辰 午 酉 亥


def relations(a, b):
    """Relations between two branches.
       same branch: 自刑 if i ∈ {辰 午 酉 亥}, else 'same'
       冲 clash   ⇔ i − j ≡ 6 (mod 12)        (opposite on the 12-branch circle)
       合 combine ⇔ i + j ≡ 1 (mod 12)        (the six harmony pairs)
       害 harm    ⇔ i + j ≡ 7 (mod 12)        (the six harm pairs)
       刑 penalty ⇔ {i, j} inside one penalty set
       Several can hold at once (e.g. 巳申 = 合 + 刑; 寅巳 = 害 + 刑)."""
    i, j = BRANCHES.index(a), BRANCHES.index(b)
    if i == j:
        return ["自刑" if i in SELF_PENALTY else "same"]
    out = []
    if (i - j) % 12 == 6: out.append("冲")
    if (i + j) % 12 == 1: out.append("合")
    if (i + j) % 12 == 7: out.append("害")
    if any(i in s and j in s for s in PENALTY_SETS): out.append("刑")
    return out


# ---------- ten gods (stem vs day master) ----------
TEN_GODS = {0: ("比肩", "劫財"), 1: ("食神", "傷官"), 2: ("偏財", "正財"), 3: ("七殺", "正官"), 4: ("偏印", "正印")}


def ten_god(day_master, stem):
    """d = (e_stem − e_DM) mod 5 → 0 same element · 1 DM produces it · 2 DM controls it ·
       3 it controls DM · 4 it produces DM; then same polarity → first name, opposite → second."""
    s0, s = STEMS.index(day_master), STEMS.index(stem)
    d = (s // 2 - s0 // 2) % 5
    return TEN_GODS[d][0 if s % 2 == s0 % 2 else 1]


def combine_partner(stem):
    """五合: s ↔ (s + 5) mod 10 (甲己 · 乙庚 · 丙辛 · 丁壬 · 戊癸)."""
    return STEMS[(STEMS.index(stem) + 5) % 10]


# ---------- stars ----------
def peach_blossom(year_branch):
    """咸池 from the year branch: trine group k = i mod 4 → peach = (9 − 3k) mod 12
       (申子辰 → 酉 · 巳酉丑 → 午 · 寅午戌 → 卯 · 亥卯未 → 子)."""
    i = BRANCHES.index(year_branch)
    return BRANCHES[(9 - 3 * (i % 4)) % 12]


def trine_of(branch):
    """The three branches 4 apart (三合 frame) containing the branch."""
    i = BRANCHES.index(branch)
    return [BRANCHES[(i + 4 * k) % 12] for k in range(3)]


def peach_frame(year_branch):
    """The other two branches of the peach blossom's trine."""
    p = peach_blossom(year_branch)
    return [b for b in trine_of(p) if b != p]


# ---------- luck pillars (大運) ----------
def luck_forward(male, year_stem):
    """陽男陰女順，陰男陽女逆: forward iff (male and yang year) or (female and yin year)."""
    yang = STEMS.index(year_stem) % 2 == 0
    return yang == bool(male)


def luck_start_years(days_to_jie):
    """Start age in years = days from the chart's moment to the nearest 節 (jie) in the luck direction ÷ 3."""
    return days_to_jie / 3.0


def luck_pillar(month_g, k, forward):
    """k-th luck pillar (k = 1, 2, …): month pillar index moved k steps along the 60-cycle."""
    return (month_g + (k if forward else -k)) % 60


# ---------- DAILY v0.1 friction score ----------
W_OWN = {"冲": 20, "刑": 15, "害": 12, "合": 10, "自刑": 12, "same": 6}
W_OTHER = {"冲": 15, "刑": 12, "害": 10, "合": 10, "自刑": 10, "same": 10}


def stem_bonus(day_master, stem):
    """+10 for the combine partner and 七殺 · +5 for 傷官 and both resource stems (偏印, 正印) · else 0."""
    if stem == combine_partner(day_master): return 10
    g = ten_god(day_master, stem)
    if g == "七殺": return 10
    if g in ("傷官", "偏印", "正印"): return 5
    return 0


def rel_points(a, b, W):
    return [(a + b + r, W[r]) for r in relations(a, b)]


def day_score(day_stem, day_branch, own, other, day_master, year_branch, attraction_pts=0, station_pts=0):
    """S = 35 + Σ_own W_own(day, b) + Σ_other W_other(day, b) + 20·[day = peach] + 6·[day ∈ peach frame]
           + stem bonus + attraction points + Saturn-station points.
       own   = this chart's distinct natal branches + its current luck branch (a separate term, even when it repeats a natal
               branch); other = the other chart's distinct natal branches."""
    parts = [("base", 35)]
    for b in own: parts += [(n + " (own)", v) for n, v in rel_points(day_branch, b, W_OWN)]
    for b in other: parts += [(n + " (other)", v) for n, v in rel_points(day_branch, b, W_OTHER)]
    if day_branch == peach_blossom(year_branch): parts.append(("咸池 day", 20))
    if day_branch in peach_frame(year_branch): parts.append(("咸池 frame day", 6))
    sb = stem_bonus(day_master, day_stem)
    if sb: parts.append(("stem " + day_stem, sb))
    if attraction_pts: parts.append(("attraction", attraction_pts))
    if station_pts: parts.append(("Saturn station", station_pts))
    raw = sum(v for _, v in parts)
    return raw, rescale(raw), parts


def hour_score(hour_br, day_branch, own, other, year_branch):
    """H = Σ_own W_own(hour, b) + Σ_other W_other(hour, b) + W_own(day, hour) + 8·[hour = peach]."""
    parts = []
    for b in own: parts += [(n + " (own)", v) for n, v in rel_points(hour_br, b, W_OWN)]
    for b in other: parts += [(n + " (other)", v) for n, v in rel_points(hour_br, b, W_OTHER)]
    parts += [("day " + n, v) for n, v in rel_points(day_branch, hour_br, W_OWN)]
    if hour_br == peach_blossom(year_branch): parts.append(("咸池 hour", 8))
    return sum(v for _, v in parts), parts


def rescale(raw):
    """S' = clip(round((S − 60) · 2.2 + 20), 5, 100)."""
    return max(5, min(100, round((raw - 60) * 2.2 + 20)))


def tier(score):
    return "🔴" if score >= 85 else "🟠" if score >= 65 else "🟡" if score >= 45 else "🟢"
