"""§13 robustness (the color brief's §6): rerun examples 2–5 over ALPHA ∈ {0.5, 0.7, 0.9} × K_VIEW ∈ {0.15, 0.25, 0.35}
× K_SELF ∈ {5, 10, 15} and record the sign of (A's day-pull change, B's charge change) in every cell. A conclusion
counts as robust only if it holds in all 27 cells. Run: python3 color_robustness.py [--a-time tf|noon]
→ robustness/color_robustness[_noon].md. Deterministic: no timestamps in the output."""
import os, sys, argparse, itertools, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser(description=__doc__.split("\n")[0]); ap.add_argument("--a-time", choices=("tf", "noon"), default=None)
a = ap.parse_args(); sys.argv = sys.argv[:1]
import daily as D

ALPHAS, K_VIEWS, K_SELFS = (0.5, 0.7, 0.9), (0.15, 0.25, 0.35), (5.0, 10.0, 15.0)
EX = {
    2: ("2026-10-21", "top green + bottom silver", [{"slot": "top", "color": "green"}, {"slot": "bottom", "color": "silver"}]),
    3: ("2026-10-23", "dark brown top + bottom, red peek", [{"slot": "top", "color": "dark brown"}, {"slot": "bottom", "color": "dark brown"},
                                                            {"slot": "peek", "color": "red"}]),
    4: ("2026-10-26", "forest green top + bottom", [{"slot": "top", "color": "forest green"}, {"slot": "bottom", "color": "forest green"}]),
    5: ("2026-10-26", "silver top + bottom (control)", [{"slot": "top", "color": "silver"}, {"slot": "bottom", "color": "silver"}]),
}
EXPECT = {2: ("up", "down"), 3: ("up", "up"), 4: ("up", "down"), 5: ("down, or flat at ALPHA = 0.5", "up")}
WORD = {1: "up", 0: "flat", -1: "down"}


def sign(before, after):
    return (after > before) - (after < before)


if __name__ == "__main__":
    at = a.a_time or D.DEFAULT_OPT["a_time"]; opt = dict(D.DEFAULT_OPT, a_time=at)
    md = ["# §13 outfit color — robustness grid (A-chart mode: %s)" % at, "",
          "Each cell: (A's day-pull change, B's charge change) when B wears the outfit; charge = the 0–100 S′ (rounded half up), "
          "pull = the unrounded 0–10 day pull. 27 cells per example. Robust = the same sign in every cell.", ""]
    summary = ["| example | day | outfit | A's pull | B's charge | brief expected | robust? |", "|---|---|---|---|---|---|---|"]
    for n, (day, label, outfit) in EX.items():
        cells = {}
        for al, kv, ks in itertools.product(ALPHAS, K_VIEWS, K_SELFS):
            o = D.outfit_report(dt.date.fromisoformat(day), "B", outfit, opt, params=dict(ALPHA=al, K_VIEW=kv, K_SELF=ks))
            cells[(al, kv, ks)] = (sign(*o["viewer"]["day_pull"]), sign(*o["wearer"]["charge"]))
        ps, cs = {c[0] for c in cells.values()}, {c[1] for c in cells.values()}
        def mix(S, i):
            """'up' when every cell agrees, else each sign with its cell count."""
            if len(S) == 1: return WORD[next(iter(S))]
            return "mixed: " + ", ".join("%s in %d" % (WORD[x], sum(1 for c in cells.values() if c[i] == x)) for x in sorted(S, reverse=True))
        rob = "yes" if len(ps) == 1 and len(cs) == 1 and 0 not in ps | cs else "no"
        summary.append("| %d | %s | %s | %s | %s | %s / %s | %s |" % (n, day, label, mix(ps, 0), mix(cs, 1), EXPECT[n][0], EXPECT[n][1], rob))
        md += ["## Example %d — %s, %s" % (n, day, label), "", "| ALPHA \\ K_VIEW, K_SELF | " +
               " | ".join("%g, %g" % (kv, ks) for kv in K_VIEWS for ks in K_SELFS) + " |", "|---" * 10 + "|"]
        for al in ALPHAS:
            md.append("| %g | " % al + " | ".join("%s %s" % ({1: "↑", 0: "=", -1: "↓"}[cells[(al, kv, ks)][0]], {1: "↑", 0: "=", -1: "↓"}[cells[(al, kv, ks)][1]])
                                                 for kv in K_VIEWS for ks in K_SELFS) + " |")
        md.append("")
    out = md[:4] + ["## Summary", ""] + summary + [""] + md[4:]
    os.makedirs(os.path.join(HERE, "robustness"), exist_ok=True)
    path = os.path.join(HERE, "robustness", "color_robustness%s.md" % ("" if at == "tf" else "_" + at))
    open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print("\n".join(out[:4 + 2 + len(summary)]))
