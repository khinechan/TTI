"""Tests for audit_book (audit item 19). Every export here is BUILT AT TEST TIME from daily.main() output, so no book
number is hard-coded and the main session's fixes to daily.py cannot break them. daily.main runs once per date
(setUpClass); the in-process runs read those results through audit_book's compute hook, and one subprocess run goes
through the real daily.main path end to end. Dates stay inside the cached 2026-10-20 window (no cache is built).
Run: cd fl_toolkit && python3 -m unittest test_audit_book -v"""
import sys, os, io, json, tempfile, subprocess, unittest, contextlib, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "pure_math", "code")]
import audit_book as AB
import daily as D

DAYS = (dt.date(2026, 10, 21), dt.date(2026, 10, 27), dt.date(2026, 11, 1))   # inside the cached 2026-10-20 window
KEYS = ("date", "pillar", "chem", "A", "B", "C")
HEAD = {"date": "Date", "pillar": "Pillar", "chem": "Chemistry", "A": "A charge · pull", "B": "B charge · pull",
        "C": "A with C"}
MON = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
TIER_NEXT = {"🔴": "🟠", "🟠": "🟡", "🟡": "🟢", "🟢": "🔴"}
FLAG_WRONG = {"": "🔥", "🔥": "✅", "✅": "🔥"}


def pair(r, tier=True, flag=True, sep=" · ", with_pull=True, **over):
    r = dict(r, **over)
    return "%s%s%s" % (r["charge"], " " + r["tier"] if tier else "",
                       (sep + str(r["pull"]) + (" " + r["flag"] if flag and r["flag"] else "")) if with_pull else "")


def cells(res, date_text, tier=True, sep=" · ", flag=True):
    return dict(date=date_text, pillar=res["pillar"], chem=str(res["chemistry"]["scale"]),
                A=pair(res["A"], tier, flag, sep), B=pair(res["B"], tier, flag, sep),
                C="%s%s" % (res["A_with_C"]["charge"], " " + res["A_with_C"]["tier"] if tier else ""))


def table(rows, order=KEYS, head=HEAD):
    out = ["| " + " | ".join(head[k] for k in order) + " |", "|" + "|".join(" :---- " for _ in order) + "|"]
    return "\n".join(out + ["| " + " | ".join(r[k] for k in order) + " |" for r in rows]) + "\n"


def mdy(d, long=False):
    return "%s %d, %d" % (d.strftime("%B") if long else MON[d.month - 1], d.day, d.year)


class AuditBook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = {d: D.main(d) for d in DAYS}
        cls.compute = staticmethod(lambda d: AB.view(cls.res[d]))
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_ab(self, text, *flags, name="days.md"):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as fh: fh.write(text)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = AB.main([path, *flags], compute=self.compute)
        return code, out.getvalue(), err.getvalue()

    def report(self, text):
        code, out, _ = self.run_ab(text, "--json")
        rep = json.loads(out); self.assertEqual(rep["exit"], code)
        return rep

    def clean_export(self):
        d0, d1, d2 = DAYS; r = self.res
        t1 = table([cells(r[d0], d0.isoformat()),                                         # ISO, tiers, " · "
                    cells(r[d1], mdy(d1), tier=False, sep="/"),                            # Oct 27, 2026, no tiers, "/"
                    cells(r[d2], "%s, %s" % (r[d2]["weekday"][:3], mdy(d2)), sep=", ")])   # weekday + date, ", "
        head2 = {"date": "**DATE**", "pillar": "Pillar 干支", "chem": "Chemistry (0–10)", "A": "A-charge / pull",
                 "B": "B Charge·Pull", "C": "A with C"}                                    # header text, not position
        order2 = ("C", "B", "date", "chem", "A", "pillar")
        t2 = table([cells(r[d0], "%d %s %d" % (d0.day, MON[d0.month - 1], d0.year), sep=" \\| "),
                    cells(r[d1], "%d/%d/%d" % (d1.month, d1.day, d1.year), sep=" - ", flag=False),
                    cells(r[d2], "%s, %s" % (r[d2]["weekday"], mdy(d2, long=True)), sep="  "),
                    cells(r[d0], d0.strftime("%Y/%m/%d"), tier=False)], order2, head2)
        return "# Days\n\n## Daily log\n\n" + t1 + "\nSome prose | with a pipe.\n\n" + t2

    def test_clean_export_exits_0(self):
        rep = self.report(self.clean_export())
        self.assertEqual((rep["exit"], rep["findings"], rep["error"]), (0, [], None))
        self.assertEqual((len(rep["tables"]), rep["rows"], rep["dates"]), (2, 7, 3))
        self.assertGreaterEqual(rep["checked"], 7 * 7)      # pillar, chemistry, 2 × (charge, pull), A with C at least
        self.assertEqual(rep["blank"], {})

    def test_injected_errors_are_exactly_the_findings(self):
        d0, d1, d2 = DAYS; r = self.res
        a = r[d0]["A"]["charge"]; wrong_a = a - 1 if a == 100 else a + 1
        p = r[d1]["B"]["pull"]; wrong_p = "%.1f" % (p + 0.3)
        wrong_pillar = "甲子" if r[d1]["pillar"] != "甲子" else "乙丑"
        wrong_tier = TIER_NEXT[r[d2]["A_with_C"]["tier"]]
        rows = [dict(cells(r[d0], d0.isoformat()), A=pair(r[d0]["A"], charge=wrong_a)),
                dict(cells(r[d1], d1.isoformat()), pillar=wrong_pillar, B=pair(r[d1]["B"], pull=wrong_p)),
                dict(cells(r[d2], mdy(d2)), C="%s %s" % (r[d2]["A_with_C"]["charge"], wrong_tier)),
                dict(cells(r[d0], "Octember 3, 2026"))]
        rep = self.report(table(rows))
        got = [(f["date"], f["column"], f["kind"]) for f in rep["findings"]]
        self.assertEqual(got, [(d0.isoformat(), "A charge", "mismatch"), (d1.isoformat(), "Pillar", "mismatch"),
                               (d1.isoformat(), "B pull", "mismatch"), (d2.isoformat(), "A with C tier", "mismatch"),
                               (None, "Date", "unreadable row")])
        f = rep["findings"]
        self.assertEqual((f[0]["written"], f[0]["computed"]), (str(wrong_a), a))
        self.assertEqual((f[2]["written"], f[2]["computed"]), (wrong_p, p))
        self.assertEqual((f[1]["written"], f[3]["written"], f[4]["written"]), (wrong_pillar, wrong_tier, "Octember 3, 2026"))
        self.assertEqual(f[4]["line"], 6)                    # header, separator, 3 rows → the 4th row is line 6
        self.assertEqual(rep["exit"], 1); self.assertIsNotNone(rep["note"])

    def test_flags_compare_only_when_written(self):
        d = DAYS[1]; r = self.res[d]
        bad = FLAG_WRONG[r["A"]["flag"]]
        rows = [dict(cells(r, d.isoformat(), flag=False)),                                  # no flag written: no finding
                dict(cells(r, d.isoformat()), A="%s %s · %s %s" % (r["A"]["charge"], r["A"]["tier"], r["A"]["pull"], bad))]
        rep = self.report(table(rows))
        self.assertEqual([(f["line"], f["column"], f["written"]) for f in rep["findings"]], [(4, "A flag", bad)])
        self.assertEqual(rep["findings"][0]["computed"], r["A"]["flag"] or "none")

    def test_blank_cells_are_skipped_and_counted(self):
        d = DAYS[0]; r = self.res[d]
        row = dict(cells(r, d.isoformat()), chem="—", A=pair(r["A"], with_pull=False), B="", C="—")
        rep = self.report(table([row, {k: "" for k in KEYS}]))
        self.assertEqual((rep["exit"], rep["findings"]), (0, []))
        self.assertEqual(rep["blank"], {"Chemistry": 1, "A pull": 1, "B charge": 1, "B pull": 1, "A with C charge": 1})
        self.assertEqual((rep["rows"], rep["blank_rows"]), (1, 1))
        rep = self.report(table([dict(cells(r, d.isoformat()), B="— · —", C="-"),            # dashes per slot = blank
                                 dict({k: "—" for k in KEYS}, A="— · —", B="- / -")]))     # a template row = blank row
        self.assertEqual((rep["exit"], rep["findings"]), (0, []))
        self.assertEqual(rep["blank"], {"B charge": 1, "B pull": 1, "A with C charge": 1})
        self.assertEqual((rep["rows"], rep["blank_rows"]), (1, 1))

    def test_wrong_weekday_is_a_finding(self):
        d = DAYS[0]; r = self.res[d]
        wrong = "Thu" if not r["weekday"].startswith("Thu") else "Fri"
        rep = self.report(table([cells(r, "%s %s" % (wrong, mdy(d)))]))
        self.assertEqual([(f["column"], f["kind"], f["written"], f["computed"]) for f in rep["findings"]],
                         [("Weekday", "mismatch", wrong, r["weekday"])])

    def test_unreadable_cell_and_extra_cells_are_findings(self):
        d = DAYS[0]; r = self.res[d]
        rows = [dict(cells(r, d.isoformat()), chem="high"), dict(cells(r, d.isoformat()), B="57 | 3.3")]   # unescaped |
        rep = self.report(table(rows) + "| nope |\n")                                       # a short row is padded
        self.assertEqual([(f["line"], f["column"], f["kind"]) for f in rep["findings"]],
                         [(3, "Chemistry", "unreadable cell"), (4, "Cells", "unreadable row"), (5, "Date", "unreadable row")])
        self.assertEqual(rep["exit"], 1)

    def test_no_table_or_no_file_exits_2(self):
        rep = self.report("# Days\n\nNo log yet.\n\n| Day | Note |\n|---|---|\n| Mon | x |\n")
        self.assertEqual(rep["exit"], 2); self.assertEqual(rep["error"], AB.NO_TABLE)
        self.assertEqual(rep["ignored_tables"][0]["line"], 5)
        self.assertIn("chemistry", rep["ignored_tables"][0]["missing"])
        self.assertEqual(self.report(table([]))["exit"], 2)                                 # header only: no rows
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(AB.main([os.path.join(self.tmp.name, "missing.md")], compute=self.compute), 2)
        self.assertIn("no such file", err.getvalue())

    def test_unknown_flag_exits_2(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            AB.main(["x.md", "--fix"], compute=self.compute)
        self.assertEqual(cm.exception.code, 2)

    def test_daily_error_is_exit_2(self):
        def broken(day): raise KeyError("mid-edit")
        d = DAYS[0]
        self.assertEqual(self.run_ab(table([cells(self.res[d], d.isoformat())]), name="err.md")[0], 0)   # sane first
        path = os.path.join(self.tmp.name, "err.md")
        with contextlib.redirect_stdout(io.StringIO()) as o:
            self.assertEqual(AB.main([path, "--json"], compute=broken), 2)
        self.assertEqual([f["kind"] for f in json.loads(o.getvalue())["findings"]], ["error"])

    def test_json_parity_and_determinism(self):
        d0, d1 = DAYS[:2]; r = self.res
        text = table([dict(cells(r[d1], d1.isoformat()), pillar="甲子" if r[d1]["pillar"] != "甲子" else "乙丑"),
                      dict(cells(r[d0], "someday")), dict(cells(r[d0], d0.isoformat()), chem="9.99")])
        code_h, out_h, _ = self.run_ab(text)
        code_j, out_j, _ = self.run_ab(text, "--json")
        rep = json.loads(out_j)
        self.assertEqual(code_h, code_j); self.assertGreater(len(rep["findings"]), 0)
        lines = [l for l in out_h.splitlines() if ": written " in l]
        self.assertEqual(lines, [AB.finding_line(f) for f in rep["findings"]])
        self.assertEqual(out_h, AB.human(rep) + "\n")
        self.assertEqual(out_j, self.run_ab(text, "--json")[1])                          # byte-identical rerun
        self.assertEqual([f["date"] for f in rep["findings"]], sorted(f["date"] for f in rep["findings"] if f["date"]) + [None])

    def test_end_to_end_cli_real_daily(self):
        d = DAYS[0]
        path = os.path.join(self.tmp.name, "e2e.md")
        with open(path, "w", encoding="utf-8") as fh: fh.write(table([cells(self.res[d], mdy(d))]))
        p = subprocess.run([sys.executable, os.path.join(HERE, "audit_book.py"), path, "--json"], cwd=HERE,
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertEqual(json.loads(p.stdout)["findings"], [])


class Readers(unittest.TestCase):
    def test_date_shapes(self):
        want = dt.date(2026, 10, 21)
        for t in ("2026-10-21", "2026/10/21", "Oct 21, 2026", "October 21, 2026", "Wed Oct 21, 2026",
                  "Wednesday, October 21, 2026", "21 Oct 2026", "10/21/2026", "oct 21 2026", "Oct. 21st, 2026"):
            self.assertEqual(AB.read_date(t)[0], want, t)
        self.assertEqual(AB.read_date("Wednesday, October 21, 2026")[1], "Wednesday")
        for t in ("Jan 5, 2027", "January 5, 2027", "Tue Jan 5, 2027", "5 Jan 2027", "2027-01-05", "1/5/2027"):
            self.assertEqual(AB.read_date(t)[0], dt.date(2027, 1, 5), t)   # January is month index 0: not falsy-dropped
        for t in ("21/10/2026", "2026-02-30", "Octember 21, 2026", "10/21/26", "21.10.2026", "Oct 21", "", "tomorrow"):
            self.assertIsNone(AB.read_date(t), t)

    def test_pair_separators(self):
        want = {"A charge": "90", "A pull": "1.8"}
        for t in ("90 · 1.8", "90/1.8", "90 | 1.8", "90, 1.8", "90 - 1.8", "90 1.8", "90·1.8"):
            self.assertEqual(AB.read_pair(t, "A"), (want, []), t)
        self.assertEqual(AB.read_pair("90 🔴 · 1.8 🔥", "A")[0], dict(want, **{"A tier": "🔴", "A flag": "🔥"}))
        self.assertEqual(AB.read_pair("— · 1.8 ✅", "A"), ({"A pull": "1.8", "A flag": "✅"}, ["A charge"]))
        self.assertEqual(AB.read_pair("13 🟢", "A with C", pull=False), ({"A with C charge": "13", "A with C tier": "🟢"}, []))
        self.assertIsNone(AB.read_pair("high", "A")); self.assertIsNone(AB.read_pair("2.5", "A with C", pull=False))

    def test_precision_as_written(self):
        self.assertTrue(AB.same("A pull", "1.9", 1.9)); self.assertTrue(AB.same("A charge", "57", 57))
        self.assertTrue(AB.same("Chemistry", "2", 2.4)); self.assertTrue(AB.same("Chemistry", "2.40", 2.4))
        self.assertTrue(AB.same("Chemistry", "3", 2.5))                                      # half up, not half even
        self.assertFalse(AB.same("A pull", "1.8", 1.85)); self.assertFalse(AB.same("A pull", "1.9", 1.8))
        self.assertTrue(AB.same("Weekday", "Wed", "Wednesday")); self.assertFalse(AB.same("Weekday", "Thu", "Wednesday"))

    def test_cells_are_cleaned(self):
        self.assertEqual(AB.clean("**90** 🔴️\\-1.8<br>"), "90 🔴-1.8")
        self.assertEqual(AB.split_row("| a | b \\| c | d |"), ["a", "b \\| c", "d"])
        self.assertEqual(len(AB.header_map(AB.split_row("| **DATE** | Pillar 干支 | Chemistry (0–10) | A-charge/pull | "
                                                         "B Charge·Pull | A with C |"))), 6)


class ATime(unittest.TestCase):
    """--a-time: the rerun can use A's noon chart, so rows written before v2 are checked against what produced them."""

    def test_noon_mode_reruns_with_the_noon_chart(self):
        day = DAYS[0]
        self.assertEqual(AB.computed(day, "noon"), AB.view(D.main(day, dict(D.DEFAULT_OPT, a_time="noon"))))
        self.assertEqual(AB.computed(day), AB.view(D.main(day)))
        self.assertNotEqual(AB.computed(day, "noon")["A pull"], AB.computed(day)["A pull"])   # 1.8 vs 2.1 on 2026-10-21

    def test_no_seasons_reruns_the_v2_engine(self):         # v3: rows written before v3 used seasons off
        day = DAYS[0]
        self.assertEqual(AB.computed(day, None, False), AB.view(D.main(day, dict(D.DEFAULT_OPT, seasons=False))))
        self.assertNotEqual(AB.computed(day, None, False)["B charge"], AB.computed(day)["B charge"])   # 57 vs 96 on 10-21

    def test_bad_mode_exits_2(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            AB.main(["x.md", "--a-time", "dusk"])
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
