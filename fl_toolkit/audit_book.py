"""audit_book — audit item 19: the book's Days tab against daily.py. Reads a Markdown export of the Days tab, finds
every Daily log table, reruns daily.main(day) once per date and lists every written value that differs, plus every
row or cell it could not read (nothing is skipped silently). READS ONLY: the export is never written. daily.py keeps
its own behavior: a date outside a cached reference window builds ref_<start>.json first (minutes, once).

table     a Markdown pipe table whose header cells START with the words  date · pillar · chemistry · a charge ·
          b charge · a with c  (case, spacing, punctuation, emoji and **bold** ignored), in any order: columns are
          mapped by header text, never by position. Separator rows and repeated headers are skipped; any other table
          is listed as ignored, with the columns it lacks. A | inside a cell must be escaped (\\|): a row with more
          cells than its header is an unreadable row, never a guess (a shorter row is padded with blank cells).
          Markdown escapes, <br>, images, links and emphasis are removed from every cell first.
date      2026-10-21 · 2026/10/21 · Oct 21, 2026 · October 21, 2026 · 21 Oct 2026 · 10/21/2026 (US order); a leading
          weekday (Wed / Wednesday,) is allowed and then checked too; anything else → an unreadable row, raw text kept
pillar    the first two CJK characters in the cell, compared exactly
chemistry the first number in the cell, against chemistry.scale (0–10)
X charge · pull   first number = charge (an integer), next number = pull; any separator (· / \\| , - spaces).
          🔴🟠🟡🟢 = tier, 🔥 ✅ = flag: each compared ONLY when written (a flag daily gives but the book left out
          is not a finding). A decimal with only a dash (or nothing) before it is a pull whose charge was left blank.
A with C  first number = charge (an integer), optional tier emoji
compare   a number matches when daily's value, rounded half up at the WRITTEN precision (bazi_core.round_half_up's
          rule: the Decimal of its repr), equals it: "1.9" ↔ 1.9 · "57" ↔ 57 · "2" ↔ 2.4. Text compares exactly.
          A blank or "—" cell (or a missing pull, or a pair cell of only dashes and separators like "— · —") is
          skipped and counted, never an error.
finding   {date, line, column, kind: mismatch · unreadable row · unreadable cell · error (daily.py raised), written,
          computed}; computed is daily's value as it prints it (a flag daily leaves empty shows as "none").
NOTE      rows written before v2 can differ for reasons that are not typos: A is time-free by default since v2 (the
          biggest mover — rerun with --a-time noon to compare against her noon chart), and the v2 fixes (pull sampled
          over the BaZi day 23:00–22:50, chemistry read at local noon New York): CHANGES.md lists which numbers moved.
          Rows written before v3 used seasons off: rerun them with --no-seasons (v3's default is seasons on).
Usage: cd fl_toolkit && python3 audit_book.py EXPORT.md [--json] [--a-time tf|noon] [--no-seasons]
Exit: 0 every row matches · 1 mismatches or unreadable rows/cells · 2 input or tool error (file missing or not UTF-8,
no Daily log table, no rows, daily.py raised; an unknown flag too). Human output and --json print ONE report dict;
findings are in date order, then column order (undated rows last, by line).
"""
import sys, os, re, json, html, argparse, datetime as dt
from decimal import Decimal, ROUND_HALF_UP

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "pure_math", "code")]

COLUMNS = (("date", "date"), ("pillar", "pillar"), ("chem", "chemistry"), ("A", "a charge"), ("B", "b charge"),
           ("C", "a with c"))                       # table key → the words its header cell starts with (normalized)
FIELDS = (("Weekday", ("weekday",)), ("Pillar", ("pillar",)), ("Chemistry", ("chemistry", "scale")),
          ("A charge", ("A", "charge")), ("A tier", ("A", "tier")), ("A pull", ("A", "pull")), ("A flag", ("A", "flag")),
          ("B charge", ("B", "charge")), ("B tier", ("B", "tier")), ("B pull", ("B", "pull")), ("B flag", ("B", "flag")),
          ("A with C charge", ("A_with_C", "charge")), ("A with C tier", ("A_with_C", "tier")))
                                                    # finding column → its key path in daily.main's output, report order
TEXT = {"Weekday", "Pillar", "A tier", "A flag", "B tier", "B flag", "A with C tier"}   # exact text; the rest numbers
ORDER = {c: i for i, c in enumerate(("Cells", "Date", "daily.py") + tuple(f for f, _ in FIELDS))}   # column sort order
TIERS, FLAGS = "🔴🟠🟡🟢", "🔥✅"                    # charge tiers · pull flags (bazi_core.tier, daily.flag_scale)
BLANK = {"", "—", "–", "-", "--"}                   # a cell (or a pull's slot) holding only this is left blank
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MIN_PREFIX = 3                                      # a month or weekday may be cut to ≥ 3 letters (Oct, Sept, Wed)
DATE_FORMS = (r"(?P<y>\d{4})[-/](?P<m>\d{1,2})[-/](?P<d>\d{1,2})",                      # 2026-10-21 · 2026/10/21
              r"(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>\d{4})",                              # 10/21/2026 (US order)
              r"(?P<mn>[a-z]+)\.? (?P<d>\d{1,2})(?:st|nd|rd|th)?,? (?P<y>\d{4})",         # Oct 21, 2026
              r"(?P<d>\d{1,2})(?:st|nd|rd|th)? (?P<mn>[a-z]+)\.?,? (?P<y>\d{4})")         # 21 Oct 2026
LEAD_WEEKDAY = r"(?P<wd>[a-z]+)\.?,? (?P<rest>.+)"  # "Wed " / "Wednesday, " before any date form
NUM = re.compile(r"\d+(?:\.\d+)?")                  # a number as written (unsigned: "-" is a separator)
CJK2 = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]{2}")   # a pillar: two CJK characters
PIPE = re.compile(r"(?<!\\)\|")                     # a cell boundary: an unescaped |
SEP_CELL = re.compile(r":?-+:?")                    # a separator-row cell (|---|:--:|)
MD_DROP = re.compile(r"!\[[^\]]*\](?:\[[^\]]*\]|\([^)]*\))|\[\^[^\]]*\]|<[^>]+>")   # images, footnote marks, HTML tags
MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")      # [text](url) → text
MD_ESC = re.compile(r"\\([!-/:-@\[-`{-~])")         # \- \| \. … → the character
MD_MARKS = str.maketrans({"*": None, "_": None, "`": None, "~": None, "\ufe0f": None, "\u200b": None, "\xa0": " "})
LEAD_NOISE = re.compile(r"[\s·•/|,;:]")             # dropped before testing what precedes a lone pull for a dash
NOTE = ("rows written before v2 can differ for reasons that are not typos: A is time-free by default since v2 (the "
        "biggest mover — rerun with --a-time noon to compare against her noon chart), and the v2 fixes (BaZi-day pull "
        "sampling, local-noon chemistry); CHANGES.md lists which numbers moved. Rows written before v3 used seasons off: "
        "rerun them with --no-seasons")
NO_TABLE = "no Daily log table: no pipe table has Date, Pillar, Chemistry, A charge, B charge and A with C headers"
_MEMO = {}                                          # (date, A-chart mode, seasons) → view(daily.main(...)), one run each


def clean(cell):
    """A cell as plain text: Markdown images/links/footnotes/HTML tags/escapes/emphasis, emoji variation selectors and
       extra spaces removed."""
    t = MD_ESC.sub(r"\1", MD_LINK.sub(r"\1", MD_DROP.sub(" ", cell)))
    return " ".join(html.unescape(t).translate(MD_MARKS).split())


def norm(cell):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", clean(cell).lower()).split())


def split_row(line):
    t = line.strip()
    t = t[1:] if t.startswith("|") else t
    t = t[:-1] if t.endswith("|") and not t.endswith("\\|") else t
    return [c.strip() for c in PIPE.split(t)]


def is_separator(cells):
    return all(SEP_CELL.fullmatch(c.strip()) for c in cells) and any(len(c.strip()) > 1 for c in cells)


def header_map(cells):
    """{table key: cell index} for every COLUMNS key whose words start a header cell (the first such cell wins)."""
    found = {}
    for i, c in enumerate(cells):
        n = norm(c)
        for key, words in COLUMNS:
            if key not in found and (n == words or n.startswith(words + " ")): found[key] = i
    return found


def blocks(text):
    """Runs of consecutive lines holding an unescaped | → [[(line number, line)]]."""
    out, cur = [], []
    for n, line in enumerate(text.splitlines(), 1):
        if PIPE.search(line): cur.append((n, line))
        elif cur: out.append(cur); cur = []
    return out + ([cur] if cur else [])


def named(tok, names):
    tok = tok.lower()
    return next((i for i, n in enumerate(names) if len(tok) >= MIN_PREFIX and n.startswith(tok)), None)


def read_date(text):
    """→ (date, weekday as written or None); None when the text is none of the accepted shapes or no real date."""
    t = " ".join(re.sub(r"\s*,\s*", ", ", text.strip()).split()); wd = None
    m = re.fullmatch(LEAD_WEEKDAY, t, re.I)
    if m and named(m["wd"], WEEKDAYS) is not None: wd, t = m["wd"], m["rest"]
    for form in DATE_FORMS:
        m = re.fullmatch(form, t, re.I)
        if not m: continue
        i = named(m["mn"], MONTHS) if "mn" in m.re.groupindex else None   # 0 = January: test `is None`, never `or`
        mo = int(m["m"]) if "m" in m.re.groupindex else 0 if i is None else i + 1   # 0 → no date
        try: return dt.date(int(m["y"]), mo, int(m["d"])), wd
        except ValueError: return None
    return None


def read_pair(t, who, pull=True):
    """'90 🔴 · 1.8 🔥' → ({'A charge': '90', 'A tier': '🔴', 'A pull': '1.8', 'A flag': '🔥'}, [blank columns]);
       pull=False ("A with C"): charge and tier only. None when the cell cannot be read."""
    nums = list(NUM.finditer(t)); out, blank = {}, []
    if nums and "." in nums[0].group():             # no integer first: only a pull whose charge was left blank
        if not pull or LEAD_NOISE.sub("", t[:nums[0].start()]) not in BLANK: return None
        nums.insert(0, None)
    tier = next((c for c in t if c in TIERS), None); flag = next((c for c in t if c in FLAGS), None) if pull else None
    if not nums and not tier and not flag: return None
    vals = [m.group() if m else None for m in nums] + [None, None]
    slots = ((who + " charge", vals[0]), (who + " tier", tier))
    for col, v in slots + (((who + " pull", vals[1]), (who + " flag", flag)) if pull else ()):
        if v is not None: out[col] = v
        elif col.endswith(("charge", "pull")): blank.append(col)
    return out, blank


def read_row(cells, cols):
    """One data row (padded to its header) → (date or None, weekday written, {column: written}, [blank columns],
       [(column, raw) unreadable])."""
    get = lambda k: clean(cells[cols[k]])
    written, blank, bad = {}, [], []
    for key, col, rd in (("pillar", "Pillar", lambda t: CJK2.search(t)), ("chem", "Chemistry", lambda t: NUM.search(t))):
        t = get(key)
        if t in BLANK: blank.append(col)
        elif rd(t): written[col] = rd(t).group()
        else: bad.append((col, t))
    for key, who, pull in (("A", "A", True), ("B", "B", True), ("C", "A with C", False)):
        t = get(key)
        if t in BLANK or not LEAD_NOISE.sub("", t).strip("—–-"):   # "— · —": only dashes and separators = blank
            blank += [who + " charge"] + ([who + " pull"] if pull else []); continue
        r = read_pair(t, who, pull)
        if r is None: bad.append((who + " charge", t))
        else: written.update(r[0]); blank += r[1]
    d = read_date(get("date"))
    return (d[0] if d else None), (d[1] if d else None), written, blank, bad


def same(col, written, value):
    """Does the written text match daily's value? Numbers at the written precision, rounded half up."""
    if col == "Weekday": return str(value).lower().startswith(written.lower())
    if col in TEXT: return written == value
    w = Decimal(written)
    return Decimal(repr(value)).quantize(Decimal(1).scaleb(w.as_tuple().exponent), rounding=ROUND_HALF_UP) == w


def view(res):
    """daily.main's output → {finding column: value} (FIELDS key paths)."""
    out = {}
    for col, path in FIELDS:
        v = res
        for k in path: v = v[k]
        out[col] = v
    return out


def computed(day, a_time=None, seasons=None):
    """view(daily.main(day)), once per date (A-chart mode, seasons) per process. daily is imported here, so a broken
       daily.py is an error finding (exit 2), not a traceback. None = daily's default (time-free A; seasons on)."""
    if (day, a_time, seasons) not in _MEMO:
        import daily as D
        opt = {k: v for k, v in (("a_time", a_time), ("seasons", seasons)) if v is not None}
        _MEMO[(day, a_time, seasons)] = view(D.main(day, dict(D.DEFAULT_OPT, **opt)) if opt else D.main(day))
    return _MEMO[(day, a_time, seasons)]


def finding(date, line, col, kind, written, value):
    return dict(date=date.isoformat() if date else None, line=line, column=col, kind=kind, written=written,
                computed=value)


def new_report(path):
    return dict(file=path, tables=[], ignored_tables=[], rows=0, blank_rows=0, dates=0, checked=0, blank={},
                findings=[], note=None, error=None, exit=2)


def audit(text, compute, path=None):
    """The report dict for one export's text; compute(day) → {finding column: daily's value}."""
    rep = new_report(path); rows = []; blank = {}
    for block in blocks(text):
        cols = None; first = None
        for n, line in block:
            cells = split_row(line)
            if is_separator(cells): continue
            hm = header_map(cells); first = hm if first is None else first
            if len(hm) == len(COLUMNS):
                cols, ncell = hm, len(cells)
                rep["tables"].append(dict(line=n, columns=[clean(cells[hm[k]]) for k, _ in COLUMNS])); continue
            if cols is None: continue
            if all(not LEAD_NOISE.sub("", clean(c)).strip("—–-") for c in cells): rep["blank_rows"] += 1; continue
            rep["rows"] += 1
            if len(cells) > ncell:
                rep["findings"].append(finding(None, n, "Cells", "unreadable row", line.strip(),
                                               "%d cells, header has %d" % (len(cells), ncell))); continue
            cells += [""] * (ncell - len(cells))
            day, wd, written, bl, bad = read_row(cells, cols)
            if day is None:
                rep["findings"].append(finding(None, n, "Date", "unreadable row", clean(cells[cols["date"]]), None)); continue
            if wd: written["Weekday"] = wd
            rows.append((day, n, written, bl, bad))
        if cols is None and len(block) > 1:
            rep["ignored_tables"].append(dict(line=block[0][0], missing=[w for k, w in COLUMNS if k not in (first or {})]))
    if not rep["tables"]: rep["error"] = NO_TABLE; return rep
    if not rep["rows"]: rep["error"] = "the Daily log table has no rows"; return rep
    seen = {}
    for day, n, written, bl, bad in sorted(rows, key=lambda r: (r[0], r[1])):
        if day not in seen:
            try: seen[day] = compute(day)
            except Exception as e: seen[day] = "%s: %s" % (type(e).__name__, e)
        v = seen[day]
        if isinstance(v, str):
            rep["findings"].append(finding(day, n, "daily.py", "error", "", v)); continue
        for col in bl: blank[col] = blank.get(col, 0) + 1
        for col, raw in bad: rep["findings"].append(finding(day, n, col, "unreadable cell", raw, v[col]))
        for col, w in written.items():
            rep["checked"] += 1
            if not same(col, w, v[col]):
                rep["findings"].append(finding(day, n, col, "mismatch", w, "none" if v[col] == "" else v[col]))
    rep["dates"] = len(seen)
    rep["blank"] = {c: blank[c] for c, _ in FIELDS if c in blank}
    rep["findings"].sort(key=lambda f: (f["date"] is None, f["date"] or "", f["line"], ORDER[f["column"]]))
    kinds = {f["kind"] for f in rep["findings"]}
    rep["note"] = NOTE if "mismatch" in kinds else None
    rep["exit"] = 2 if "error" in kinds else 1 if kinds else 0
    return rep


def run(path, compute):
    if not os.path.isfile(path): return dict(new_report(path), error="no such file: %s" % path)
    try:
        with open(path, encoding="utf-8-sig") as fh: text = fh.read()
    except (OSError, UnicodeDecodeError) as e: return dict(new_report(path), error="cannot read %s: %s" % (path, e))
    return audit(text, compute, path)


def finding_line(f):
    show = lambda v: "—" if v is None else json.dumps(v, ensure_ascii=False)
    return "%s  line %d  %s  %s: written %s · computed %s" % (f["date"] or "(no date)", f["line"], f["column"],
                                                               f["kind"], show(f["written"]), show(f["computed"]))


def human(rep):
    out = ["audit_book · %s" % rep["file"]]
    out += ["Daily log table at line %d: %s" % (t["line"], " | ".join(t["columns"])) for t in rep["tables"]]
    out += ["ignored table at line %d (lacks: %s)" % (t["line"], ", ".join(t["missing"])) for t in rep["ignored_tables"]]
    if rep["tables"]:
        bl = ", ".join("%s %d" % kv for kv in rep["blank"].items())
        out.append("rows %d (+%d blank) · dates %d · values checked %d · blank skipped %d%s" % (
            rep["rows"], rep["blank_rows"], rep["dates"], rep["checked"], sum(rep["blank"].values()), " (%s)" % bl if bl else ""))
    out += [finding_line(f) for f in rep["findings"]]
    if rep["note"]: out.append("note: " + rep["note"])
    out.append("exit %d · %d finding%s" % (rep["exit"], len(rep["findings"]), "" if len(rep["findings"]) == 1 else "s"))
    return "\n".join(out)


def main(argv=None, compute=None):
    ap = argparse.ArgumentParser(description="Audit the book's Daily log (a Markdown export of the Days tab) against daily.py.")
    ap.add_argument("export", help="the Days tab exported as Markdown (.md)")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    ap.add_argument("--a-time", choices=("tf", "noon"), help="A's chart for the rerun (default: daily.py's, time-free)")
    ap.add_argument("--seasons", action=argparse.BooleanOptionalAction, default=None,
                    help="v3 seasons for the rerun (default: daily.py's, on); --no-seasons for rows written before v3")
    a = ap.parse_args(argv)
    try: rep = run(a.export, compute or (lambda day: computed(day, a.a_time, a.seasons)))
    except Exception as e:                          # crash floor: one line, exit 2, never a traceback
        rep = dict(new_report(a.export), error="CRASH (%s): %s" % (type(e).__name__, e))
    if a.json: print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        print(human(rep))
        if rep["error"]: print("audit_book: error: " + rep["error"], file=sys.stderr)
    return rep["exit"]


if __name__ == "__main__":
    sys.exit(main())
