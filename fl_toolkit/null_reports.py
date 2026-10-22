"""null_reports — audit items 15 and 16: random-partner nulls for the book's A–B and A–C claims. REPORTS ONLY: no chart
and no formula changes; every count is pair_core's own function.

Charts (daily.py, built at import): A = noon chart (no birth time) · B = 10 bodies + ASC + MC (no DSC key) · C = noon chart.
  family    F(x→y) = len(pair_core.attraction_family(chart_b = x, chart_a = y)): x's Venus/Mars ☌ □ ☍ within 1° of y's
            Sun/Moon/Venus/Mars/ASC/DSC. A→B = F(A→B) · B→A = F(B→A). A = natA (noon bodies, Moon left out: the book's rule)
  contacts  (all, tight) = pair_core.contact_counts(A, y): synastry within 3° (⚹ 2.5°), tight = orb ≤ 1°.
            A = pA (noon chart WITH its noon Moon): the point set that reproduces the book's 17 (checked below)
Null: N random moments t = T0 + u · (T1 − T0), u = random.Random(seed).random(), T0 = 1960-01-01, T1 = 2000-01-01 UTC
  (pair_core.random_chart's draw; a second Random(seed) through random_chart itself must return the same bodies: draw check).
  A–B (item 15): partner = the 10 bodies at t + ASC, MC at Frederick (astro_core.angles), as B has; it replaces B.
  A–C (item 16): partner = pair_core.random_chart (10 bodies, no angles: C has no birth time); it replaces C.
  percentile = share of partners strictly below the real value · p = (1 + #{partner ≥ real}) / (N + 1)
  (pair_core.null_percentile) · mean = the partners' mean.
  STD: share ≤ real and p_low = (1 + #{partner ≤ real}) / (N + 1) (the lower tail, for A–C's "fewer ties");
  "≈" is judged as |measured − expected| ≤ 2 Monte-Carlo SE at N (share: √(q(1 − q)/N) at the expected q · mean: sd/√N);
  Bonferroni line = 0.05 / 4 (four tests on the same pair).
Seed sensitivity: the same nulls at 4 more fixed seeds; the headline is the default seed.
Usage: cd fl_toolkit && python3 null_reports.py [--n 4000] [--seed S]  → robustness/null_reports.md + robustness/null_reports.json
"""
import sys, os, json, math, time, random, argparse, datetime as dt
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "pure_math", "code")]
import daily as D
A, P = D.A, D.P
rhu = D.Z.round_half_up

N_DEF, SEED_DEF = 4000, 20261021                  # null size and the headline seed
SENS_SEEDS, N_SENS = (1, 2, 3, 4, 5), 4           # seed sensitivity: the first 4 of these ≠ the headline seed (never tuned)
T0 = dt.datetime(1960, 1, 1, tzinfo=D.UTC)        # partner moments: uniform in [T0, T1) UTC
T1 = dt.datetime(2000, 1, 1, tzinfo=D.UTC)
BODIES = tuple(A.BODY)                            # the 10 bodies, Sun..Pluto
ALPHA, N_TESTS = 0.05, 4                          # STD: Bonferroni line ALPHA / N_TESTS (A→B, B→A, all, tight)
TOL_SE = 2.0                                      # STD: "≈" = within 2 Monte-Carlo standard errors at N
MORE_THAN = 0.999                                 # "fewer ties than 99.9% of random pairs"
EXP = dict(ab=2, all=17, tight=4, ac=2, ab_pct=0.950, ab_p=0.050, ba_p=0.125, all_pct=0.62, all_p=0.38,
           tight_pct=0.22, ac_mean=12.6, ac_le=0.0008, one_in=20)   # audit items 15–16 (the brief's numbers)
A_FAM, A_CON = D.natA, D.pA                       # A for the family (Moon out) · A for contact counts (noon Moon in)
B, C = D.natB, D.pC
C_NO_MOON = {k: v for k, v in C.items() if k != "Moon"}
OUT = os.path.join(HERE, "robustness")


def fam(x, y): return len(P.attraction_family(chart_b=x, chart_a=y))


REAL = dict(ab=fam(A_FAM, B), ba=fam(B, A_FAM), all=P.contact_counts(A_CON, B)[0], tight=P.contact_counts(A_CON, B)[1],
            ac=P.contact_counts(A_CON, C)[0], all_no_moon=P.contact_counts(A_FAM, B)[0],
            tight_no_moon=P.contact_counts(A_FAM, B)[1])     # the book's real values (contacts: A's noon Moon in / out)


def partner_stats(n, seed):
    """One null run: per partner the headline statistics + the point-set checks. → (rows, draw-check matches)."""
    rng, chk = random.Random(seed), random.Random(seed); rows, same = [], 0
    for _ in range(n):
        t = T0 + dt.timedelta(seconds=rng.random() * (T1 - T0).total_seconds())
        bod = {b: A.lon(b, t) for b in BODIES}
        cc = P.random_chart(chk, T0, T1); same += cc == bod
        asc, mc = A.angles(t, D.LAT, D.LON); pt = dict(bod, ASC=asc, MC=mc)
        al, ti = P.contact_counts(A_CON, pt); al0, ti0 = P.contact_counts(A_FAM, pt)
        rows.append(dict(ab=fam(A_FAM, pt), ba=fam(pt, A_FAM), all=al, tight=ti, ac=P.contact_counts(A_CON, cc)[0],
                         ab_bodies=fam(A_FAM, bod), ab_dsc=fam(A_FAM, dict(pt, DSC=(asc + 180) % 360, IC=(mc + 180) % 360)),
                         ba_moon=fam(pt, A_CON), all_no_moon=al0, tight_no_moon=ti0,
                         ac_no_moon=P.contact_counts(A_FAM, cc)[0]))
    return rows, same


def versus(real, vals):
    """real vs the null sample: pair_core.null_percentile + mean, sd, the lower tail (STD) and the histogram."""
    n = len(vals); below, p = P.null_percentile(real, vals)
    m = sum(vals) / n; sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (n - 1))
    le = sum(1 for v in vals if v <= real)
    return dict(real=real, percentile=rhu(below, 4), p=rhu(p, 4), mean=rhu(m, 3), sd=rhu(sd, 3),
                share_le=rhu(le / n, 5), share_gt=rhu(1 - le / n, 5), p_low=rhu((1 + le) / (n + 1), 5),
                hist=[[v, c] for v, c in sorted(Counter(vals).items())])


def se_share(q, n): return math.sqrt(q * (1 - q) / n)


def inv_p(v):
    """1/p = (N + 1) / (1 + #≥ real) from the counts (not from the 4-decimal p)."""
    return (1 + sum(c for _, c in v["hist"])) / (1 + sum(c for x, c in v["hist"] if x >= v["real"]))


def near(meas, exp, se): return abs(meas - exp) <= TOL_SE * se, (meas - exp) / se if se else 0.0


def run(n, seed):
    rows, same = partner_stats(n, seed)
    col = lambda k: [r[k] for r in rows]; real = REAL
    t = dict(ab=versus(real["ab"], col("ab")), ba=versus(real["ba"], col("ba")), all=versus(real["all"], col("all")),
             tight=versus(real["tight"], col("tight")), ac=versus(real["ac"], col("ac")),
             ab_bodies=versus(real["ab"], col("ab_bodies")), ab_dsc=versus(real["ab"], col("ab_dsc")),
             ba_moon=versus(real["ba"], col("ba_moon")), all_no_moon=versus(real["all_no_moon"], col("all_no_moon")),
             tight_no_moon=versus(real["tight_no_moon"], col("tight_no_moon")), ac_no_moon=versus(real["ac"], col("ac_no_moon")))
    return t, same


def conventions():
    """The real values under each candidate point set → (A–B rows: A, B set, all, tight, A→B, B→A ·
       A–C rows: A, C set, contacts). A: Moon out (natA) / noon Moon in (pA) · B: natB / bodies only / + DSC + IC ·
       C: noon chart with / without its Moon."""
    Bb = {k: v for k, v in B.items() if k in BODIES}; Bd = dict(B, DSC=(B["ASC"] + 180) % 360, IC=(B["MC"] + 180) % 360)
    ab, ac = [], []
    for an, a in (("Moon out (natA)", A_FAM), ("noon Moon in (pA)", A_CON)):
        for bn, b in (("bodies + ASC + MC (natB)", B), ("bodies only", Bb), ("+ DSC + IC", Bd)):
            ab.append((an, bn) + P.contact_counts(a, b) + (fam(a, b), fam(b, a)))
        for cn, c in (("noon, Moon in (pC)", C), ("noon, Moon out", C_NO_MOON)):
            ac.append((an, cn, P.contact_counts(a, c)[0]))
    return ab, ac


def claims(h, n):
    ok = lambda b: "✓" if b else "✗"; cl = []
    def share(src, text, meas, exp):
        good, z = near(meas, exp, se_share(exp, n))
        fm = "%.5f" if exp < 0.01 else "%.4f"
        cl.append((ok(good), src, text, (fm + " (expected " + fm + "; %+.1f SE)") % (meas, exp, z)))
    cl.append((ok(REAL["ab"] == EXP["ab"]), "task", "A→B family count = 2 (holds for births before 7:45 PM)", str(REAL["ab"])))
    cl.append((ok(REAL["all"] == EXP["all"]), "task", "all A–B contacts = 17",
               "%d with A's noon Moon in (%d with it out)" % (REAL["all"], REAL["all_no_moon"])))
    cl.append((ok(REAL["tight"] == EXP["tight"]), "task", "tight A–B contacts (≤ 1°) = 4", str(REAL["tight"])))
    cl.append((ok(REAL["ac"] == EXP["ac"]), "task", "A–C contacts, bodies only = 2", str(REAL["ac"])))
    share("audit 15", "A→B family: percentile 0.950", h["ab"]["percentile"], EXP["ab_pct"])
    share("audit 15", "A→B family: p ≈ 0.050 (births before 7:45 PM)", h["ab"]["p"], EXP["ab_p"])
    share("audit 15", "B→A family: p ≈ 0.125 (births before 7:45 PM)", h["ba"]["p"], EXP["ba_p"])
    share("audit 15", "all contacts 17 ≈ 62nd percentile", h["all"]["percentile"], EXP["all_pct"])
    share("audit 15", "all contacts p ≈ 0.38", h["all"]["p"], EXP["all_p"])
    share("audit 15", "tight contacts 4 ≈ 22nd percentile", h["tight"]["percentile"], EXP["tight_pct"])
    p = h["ab"]["p"]; line = ALPHA / N_TESTS
    cl.append((ok(p > line), "audit 15", "A→B p does not clear the Bonferroni line %.4f" % line, "p = %.4f" % p))
    ip = inv_p(h["ab"])
    cl.append((ok(round(ip) == EXP["one_in"]), "audit 15", "\"about a 1-in-20 result\"", "1 in %d (1/p = %.1f)" % (round(ip), ip)))
    cl.append((ok(h["ab"]["p"] < min(h["all"]["p"], h["tight"]["p"])), "audit 15",
               "the family hits are what is unusual, not the overall contact count",
               "p: family %.4f · all %.4f · tight %.4f" % (h["ab"]["p"], h["all"]["p"], h["tight"]["p"])))
    good, z = near(h["ac"]["mean"], EXP["ac_mean"], h["ac"]["sd"] / math.sqrt(n))
    cl.append((ok(good), "audit 16", "A–C random-partner mean ≈ 12.6", "%.3f (sd %.3f; %+.1f SE)" % (h["ac"]["mean"], h["ac"]["sd"], z)))
    share("audit 16", "A–C share of random partners ≤ 2 ≈ 0.0008", h["ac"]["share_le"], EXP["ac_le"])
    cl.append((ok(h["ac"]["share_gt"] >= MORE_THAN), "audit 16", "\"fewer ties than 99.9% of random pairs\"",
               "share with more ties = %.5f" % h["ac"]["share_gt"]))
    return cl


KEYS = (("ab", "A→B family"), ("ba", "B→A family"), ("all", "all A–B contacts"), ("tight", "tight A–B (≤ 1°)"))


def build_report(n, seed, head, same, conv, sens, seeds):
    cl = claims(head, n); line = ALPHA / N_TESTS; p = head["ab"]["p"]
    extra = [r for r in P.synastry(A_CON, B) if r not in P.synastry(A_FAM, B)]
    rng_of = lambda k, f: (min(s[k][f] for s in sens.values()), max(s[k][f] for s in sens.values()))
    srange = {k: {f: list(rng_of(k, f)) for f in ("percentile", "p", "mean", "share_le")} for k in head}
    note = ("Holds for births before 7:45 PM: after it A's Mars–B's Venus tie passes the 1° family orb, so A→B drops to 1 and "
            "B→A to 0 (robustness/birth_time_sweep.md), and the 17 contacts also need A's noon Moon (A has no birth time). "
            "Multiple testing (STD): %d tests were run on the same pair (A→B, B→A, all, tight), so a Bonferroni line is "
            "%.2f/%d = %.4f; the A→B p = %.4f %s it (the brief's p ≈ 0.05 does not). Honest wording: "
            "\"about a 1-in-%d result\" under this null (the brief's ≈ 0.05 / 1-in-20 is close to what a partner that also "
            "carries a DSC key gives: p = %.4f here, %.4f–%.4f over the %d seeds) — and what is unusual is the attraction-family "
            "hits, not the overall contact count." % (N_TESTS, ALPHA, N_TESTS, line, p, "clears" if p <= line else "does not clear", round(inv_p(head["ab"])), head["ab_dsc"]["p"],
                                                       srange["ab_dsc"]["p"][0], srange["ab_dsc"]["p"][1], len(seeds)))
    meth = ["Partners: N = %d moments uniform in [%s, %s) UTC, t = T0 + u·(T1 − T0), u = random.Random(%d).random() — "
            "pair_core.random_chart's draw; draw check: at every seed (%s), %d of %d × %d partners identical to random_chart's "
            "own bodies." % (n, T0.date(), T1.date(), seed, ", ".join(map(str, seeds)), sum(same.values()), len(seeds), n),
            "A–B partner = 10 bodies + ASC + MC at Frederick (%.4f, %.4f; astro_core.angles), as B has; no DSC key (B has none)."
            % (D.LAT, D.LON),
            "A–C partner = pair_core.random_chart (10 bodies, no angles: C has no birth time).",
            "Family uses A = natA (noon bodies, Moon left out: the book's rule); contact counts use A = pA (the noon chart WITH "
            "its noon Moon), the point set that reproduces 17/4/2. A has no birth time, so the Moon part is a noon convention: "
            "the extra contact it adds is %s." % ", ".join("A %s %s B %s %.2f°" % (r[1], r[2], r[3], r[0]) for r in extra),
            "percentile = share strictly below (pair_core.null_percentile) · p = (1 + #≥ real)/(N + 1) · STD p_low = "
            "(1 + #≤ real)/(N + 1) · ✓ = within %g Monte-Carlo SE of the brief's number at N." % TOL_SE,
            "Files carry no timestamp and no runtime, so a rerun is byte-identical; the runtime is printed on the console."]
    js = dict(what="audit items 15–16: random-partner nulls (null_reports.py)", n=n, seed=seed, seeds_sensitivity=seeds,
              range_utc=[T0.isoformat(), T1.isoformat()], frederick=[D.LAT, D.LON], draw_check={str(s): dict(same=same[s], of=n) for s in seeds},
              real=REAL, expected=EXP, claims=[dict(mark=m, source=s, claim=c, measured=v) for m, s, c, v in cl],
              conventions_real=dict(ab=[dict(A=a, B=b, all=c, tight=d, ab=e, ba=f) for a, b, c, d, e, f in conv[0]],
                                    ac=[dict(A=a, C=b, contacts=c) for a, b, c in conv[1]]),
              ab_null={k: head[k] for k, _ in KEYS},
              ab_family_partner_points=dict(bodies_only=head["ab_bodies"], asc_mc=head["ab"], asc_mc_dsc_ic=head["ab_dsc"]),
              moon_in_out=dict(ba_moon_in=head["ba_moon"], all_moon_out=head["all_no_moon"],
                               tight_moon_out=head["tight_no_moon"], ac_moon_out=head["ac_no_moon"]),
              ac_null=head["ac"], multiple_testing=dict(tests=N_TESTS, alpha=ALPHA, line=line, ab_p=p, clears=p <= line,
                                                         one_in=round(inv_p(head["ab"])), note=note),
              seed_sensitivity=dict(headline_seed=seed, per_seed={str(s): {k: {f: v[k][f] for f in ("percentile", "p", "mean", "share_le")}
                                                                             for k in head} for s, v in sens.items()},
                                    range=srange),
              method=meth)
    f4 = lambda x: "%.4f" % x
    md = ["# Null reports — audit items 15 and 16", "",
          "`python3 null_reports.py --n %d --seed %d` · partners %s to %s UTC · seed sensitivity at %s · "
          "draw check %d/%d." % (n, seed, T0.date(), T1.date(), ", ".join(map(str, seeds[1:])), sum(same.values()), len(seeds) * n), "",
          "## Claims", "", "| | source | claim | measured |", "|---|---|---|---|"]
    md += ["| %s | %s | %s | %s |" % c for c in cl]
    hit = lambda v, e: "**%d ✓**" % v if v == e else "%d" % v
    md += ["", "## Real values under each point-set convention (book: 17 all · 4 tight · 2 A→B · 2 A–C)", "",
           "| A | B | all A–B | tight A–B | A→B family | B→A family |", "|---|---|---|---|---|---|"]
    md += ["| %s | %s | %s | %s | %s | %d |" % (a, b, hit(c, EXP["all"]), hit(d, EXP["tight"]), hit(e, EXP["ab"]), f)
           for a, b, c, d, e, f in conv[0]]
    md += ["", "| A | C | A–C contacts |", "|---|---|---|"] + ["| %s | %s | %s |" % (a, b, hit(c, EXP["ac"])) for a, b, c in conv[1]]
    md += ["", "The convention that reproduces 17 / 4 / 2 is A's noon chart **with** its noon Moon for contact counts "
           "(B as natB, C as its noon chart; C's Moon in or out gives 2 either way). The family counts do not depend on A's Moon "
           "for A→B; B→A is 1 either way. Used below: family on natA (as briefed), contacts on pA.", "",
           "## A–B null (item 15) — seed %d, N = %d" % (seed, n), "",
           "| test | real | percentile | p | null mean | brief |", "|---|---|---|---|---|---|"]
    brief = dict(ab="pct 0.950, p ≈ 0.050", ba="p ≈ 0.125", all="≈ 62nd pct, p ≈ 0.38", tight="≈ 22nd pct")
    md += ["| %s | %d | %s | %s | %.3f | %s |" % (lab, head[k]["real"], f4(head[k]["percentile"]), f4(head[k]["p"]),
                                                 head[k]["mean"], brief[k]) for k, lab in KEYS]
    md += ["", note, "", "### Point-set checks (diagnostic, same partners)", "",
           "| test | point set | real | percentile | p | null mean |", "|---|---|---|---|---|---|"]
    for k, lab, ps in (("ab_bodies", "A→B family", "partner bodies only"), ("ab", "A→B family", "partner + ASC + MC (headline)"),
                       ("ab_dsc", "A→B family", "partner + ASC + MC + DSC + IC"),
                       ("ba_moon", "B→A family", "A's noon Moon in"), ("all_no_moon", "all A–B contacts", "A's Moon out"),
                       ("tight_no_moon", "tight A–B", "A's Moon out")):
        md.append("| %s | %s | %d | %s | %s | %.3f |" % (lab, ps, head[k]["real"], f4(head[k]["percentile"]), f4(head[k]["p"]), head[k]["mean"]))
    md += ["", "A DSC key on the partner counts every axis contact twice (☌ DSC = ☍ ASC, □ DSC = □ ASC, ☍ DSC = ☌ ASC), "
           "which raises the null's share of ≥ 2 hits; B carries no DSC key, so the headline partner carries none either.", "",
           "## A–C null (item 16) — seed %d, N = %d" % (seed, n), "",
           "| real | null mean | sd | share ≤ real | share > real | percentile | p | p_low (STD) |", "|---|---|---|---|---|---|---|---|",
           "| %d | %.3f | %.3f | %.5f | %.5f | %s | %s | %.5f |" % (head["ac"]["real"], head["ac"]["mean"], head["ac"]["sd"],
                                                           head["ac"]["share_le"], head["ac"]["share_gt"], f4(head["ac"]["percentile"]),
                                                           f4(head["ac"]["p"]), head["ac"]["p_low"]), "",
           "Method: bodies only (C has no birth time, so no angles on either side of the null); the random partner replaces C; "
           "statistic = all synastry contacts with A (3° orbs, ⚹ 2.5°). A small count is the unusual direction here, so the "
           "readout is the lower tail (share ≤ real); pair_core's upper-tail p is ≈ 1 by design. With A's Moon out: null mean "
           "%.3f, share ≤ 2 = %.5f." % (head["ac_no_moon"]["mean"], head["ac_no_moon"]["share_le"]), "",
           "## Seed sensitivity (headline = seed %d)" % seed, "",
           "| seed | A→B pct | A→B p | B→A p | all pct | all p | tight pct | A–C mean | A–C share ≤ 2 | A→B p with DSC |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    row = lambda lab, g: "| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
        lab, g("ab", "percentile"), g("ab", "p"), g("ba", "p"), g("all", "percentile"), g("all", "p"),
        g("tight", "percentile"), g("ac", "mean"), g("ac", "share_le"), g("ab_dsc", "p"))
    for s in seeds:
        md.append(row(str(s), lambda k, f, s=s: ("%.3f" if f == "mean" else "%.5f" if f == "share_le" else "%.4f") % sens[s][k][f]))
    md.append(row("**range**", lambda k, f: (("%.3f–%.3f" if f == "mean" else "%.5f–%.5f" if f == "share_le" else "%.4f–%.4f")
                                             % tuple(srange[k][f]))))
    md += ["", "## Method", ""] + ["- " + m for m in meth] + [""]
    console = ["%s %-9s %-62s %s" % c for c in cl]
    return dict(json=js, md="\n".join(md), console=console)


def main():
    ap = argparse.ArgumentParser(description="Audit items 15–16: A–B and A–C random-partner nulls.")
    ap.add_argument("--n", type=int, default=N_DEF, help="random partners per null (default %d)" % N_DEF)
    ap.add_argument("--seed", type=int, default=SEED_DEF, help="headline seed (default %d)" % SEED_DEF)
    a = ap.parse_args()
    if a.n < 2: ap.error("--n must be ≥ 2")
    t_start = time.time()
    seeds = [a.seed] + [s for s in SENS_SEEDS if s != a.seed][:N_SENS]
    sens, same = {}, {}
    for s in seeds: sens[s], same[s] = run(a.n, s)
    rep = build_report(a.n, a.seed, sens[a.seed], same, conventions(), sens, seeds)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "null_reports.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(rep["json"], f, ensure_ascii=False, indent=1); f.write("\n")
    with open(os.path.join(OUT, "null_reports.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(rep["md"])
    print("seed %d, N = %d, seeds %s" % (a.seed, a.n, seeds))
    for line in rep["console"]: print(line)
    print("runtime %.1f s" % (time.time() - t_start))


if __name__ == "__main__":
    main()
