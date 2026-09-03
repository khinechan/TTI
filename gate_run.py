#!/usr/bin/env python3
"""gate_run.py — THE GATE RUNNER. Runs the certified tool fleet in a
fixed order and produces ONE verdict with receipts. It replaces a human
narrating results in prose: prose insistence isn't a mechanism — this
is the mechanism.

WHAT IT IS NOT: it does not re-implement, import, wrap, or reason about
what any tool does. It runs processes and reads exit codes. Every tool
in the fleet is court-certified with its own test suite. The runner's
entire domain expertise is: 0 means pass.

Exit codes (COURT ADDENDUM R5 — a DELIBERATE, documented exception to
the house 0/1/2 standard; do not "fix" this back):
    0 = PASS      full fleet, every stage 0
    1 = FAIL      one or more stages FAIL / HUNG / CANT_START
    2 = BAD INVOCATION  unknown flag, unknown tool name, empty fleet,
                  --only with --skip, a selection that runs zero stages
    3 = RUNNER INTERNAL ERROR  the runner itself broke — cannot write
                  a receipt or its report
    4 = PARTIAL   a valid reduced run (--only/--skip). NEVER a pass.
Precedence: 3 > 2 > 1 > 4 > 0. A reduced run with a failing stage
exits 1, not 4 — a failure is a failure regardless of scope.

Write surfaces — exactly two, named (W9):
    1. the receipts ledger:  <base>/gate_receipts.jsonl  (the TRUTH)
    2. the report file:      <base>/reports/gate_run_<run_id>.txt
where <base> is the directory gate_run.py lives in (Tools/Automation/
on the vault machine). If they ever disagree, THE RECEIPT WINS (W10).
Plus one court-sanctioned best-effort human line via runlog.py after
the receipt lands (amendment A1) — its failure never changes a verdict.

A receipt is written on EVERY run, PASS included (W11): a night with no
receipt means THE RUNNER DID NOT RUN, never "nothing was wrong".

Runtime (amendment A6): Linux-first, Python floor 3.10. POSIX process
groups (start_new_session + os.killpg) are the primary kill mechanism;
the Windows branch (CREATE_NEW_PROCESS_GROUP + taskkill /F /T) is a
secondary guard and is UNTESTED on a real Windows box.

Standard library only. The runner is read-only over the vault and over
every tool.
"""

import argparse
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

RUNNER_VERSION = "1.0.0"

# ═══════════════════════════════════════════════════════════════════════
# RULE DATA.
# ═══════════════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).resolve().parent
# Vault-side, gate_run.py lives in Tools/Automation/, so the two write
# surfaces below resolve to exactly the W9 paths. Tool paths resolve
# against this directory too, and every stage launches with cwd here
# (amendment A4: vault_lint's internal runlog.txt is a bare relative
# path — the explicit cwd keeps it, and every other relative path a
# tool touches, inside this directory).

RECEIPTS_NAME = "gate_receipts.jsonl"
REPORTS_DIRNAME = "reports"
RUNLOG_NAME = "runlog.py"          # best-effort human line only (A1)

DEFAULT_TIMEOUT_S = 300
SECONDARY_TIMEOUT_S = 5            # post-kill pipe drain; then abandon
RUNLOG_TIMEOUT_S = 30

# The STATE.md path for vault_lint is configuration, never a hardcoded
# path that exists nowhere (A5). The fleet entry carries the symbol
# below; it is substituted at launch so fleet_hash stays machine-stable.
STATE_MD_ENV = "GATE_RUN_STATE_MD"
STATE_MD_PLACEHOLDER = "{STATE_MD}"

# THE FLEET — an explicit ordered list, never globbed, never discovered
# from a directory (W8: os.listdir order is filesystem-dependent).
# depends_on NEVER skips a stage — every stage always runs; it only
# annotates the report so root cause is distinguishable from echo.
# link_audit is REMOVED from the v1 fleet entirely (amendment A5): it
# is hardcoded to 5 incident products — a one-time checker, not a
# nightly gate. Deliberately excluded, not --skip'd. See --explain.
FLEET = [
    {"name": "heartbeat_check", "path": "heartbeat_check.py",
     "args": [], "timeout_s": None, "depends_on": []},
    {"name": "color_check", "path": "color_check.py",
     "args": ["--audit-rules"], "timeout_s": None, "depends_on": []},
    {"name": "thumb_check", "path": "thumb_check.py",
     "args": ["--audit-palette", "black"], "timeout_s": None,
     "depends_on": ["color_check"]},   # imports palette live
    {"name": "sku_check", "path": "sku_check.py",
     "args": [], "timeout_s": None, "depends_on": [],
     "requires_env": ["PRINTIFY_TOKEN"]},
    {"name": "vault_lint", "path": "vault_lint.py",
     "args": [STATE_MD_PLACEHOLDER, "--baseline",
              "vault_lint_baseline.json"],
     "timeout_s": None, "depends_on": []},
    {"name": "backup_age", "path": "vault_backup.py",
     "args": ["--check-age"], "timeout_s": None, "depends_on": []},
]
# ─────────────────────────── END OF FLEET ──────────────────────────────

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_BAD_INVOCATION = 2
EXIT_INTERNAL = 3
EXIT_PARTIAL = 4

EXIT_TABLE = [
    (EXIT_PASS, "PASS", "full fleet, every stage 0"),
    (EXIT_FAIL, "FAIL", "one or more stages FAIL / HUNG / CANT_START"),
    (EXIT_BAD_INVOCATION, "BAD INVOCATION",
     "unknown flag or tool name, empty fleet, --only with --skip"),
    (EXIT_INTERNAL, "RUNNER INTERNAL ERROR",
     "the runner itself broke — cannot write a receipt or report"),
    (EXIT_PARTIAL, "PARTIAL",
     "a valid reduced run (--only/--skip); never a pass"),
]
EXIT_PRECEDENCE = "3 > 2 > 1 > 4 > 0"

BAD_STATUSES = ("FAIL", "HUNG", "CANT_START")

# ═══════════════════════════════════════════════════════════════════════
# END OF RULE DATA.
# ═══════════════════════════════════════════════════════════════════════


class InvocationError(Exception):
    """Bad invocation. Exit 2. Zero stages have run."""


def fleet_hash(fleet):
    """R8: sha256 over a stable serialization of (name, path, args,
    timeout_s, depends_on) in fleet order, hex digest — defined so two
    implementations can't disagree. Paths and args are hashed as
    WRITTEN (placeholders unsubstituted) so the hash is machine-stable."""
    serial = json.dumps(
        [[e["name"], e["path"], e["args"], e["timeout_s"], e["depends_on"]]
         for e in fleet],
        separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serial.encode("utf-8")).hexdigest()


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _resolve_state_md(environ):
    configured = environ.get(STATE_MD_ENV)
    return Path(configured) if configured else BASE_DIR / "STATE.md"


def _substitute_args(args, environ):
    state_md = _resolve_state_md(environ)
    return [str(state_md) if a == STATE_MD_PLACEHOLDER else a for a in args]


# ─────────────────────────── stage execution ───────────────────────────

def _launch(cmd, cwd):
    """W1: argument list only. Never a shell, never a pipe, never a
    redirection wrapped around the invocation — a tool exiting 7, piped
    to head, returns 0: the failure INVERTS.
    W6: [sys.executable, path] always, never bare "python".
    A6: POSIX process group is primary; Windows branch is a secondary
    guard, untested on a real Windows box."""
    kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
              "cwd": str(cwd)}
    if os.name == "posix":
        kwargs["start_new_session"] = True
    else:
        kwargs["creationflags"] = getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(cmd, **kwargs)


def _kill_tree(proc):
    """Kill the stage's whole process tree. R6/A6: POSIX killpg is
    primary; on Windows, Popen.kill() kills only the direct child, so
    taskkill /F /T is the accepted mechanism (a system binary is not a
    new dependency, and an argument-list call is not output piping)."""
    if os.name == "posix":
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()
    else:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        proc.kill()


def _run_stage(entry, resolved_path, cwd, environ):
    """One stage. Exit code is the ONLY signal (W2): stdout/stderr are
    captured as BYTES, stored for humans, never interpreted. On timeout
    there is NO returncode to read (W5, verified) — status HUNG,
    returncode null, never a fabricated number. After the kill, a short
    secondary communicate() drains the pipe; a grandchild holding the
    inherited pipe open must never block the fleet."""
    cmd = [sys.executable, str(resolved_path)] + \
        _substitute_args(entry["args"], environ)
    timeout = entry["timeout_s"] or DEFAULT_TIMEOUT_S
    started = time.monotonic()
    proc = _launch(cmd, cwd)
    try:
        out, err = proc.communicate(timeout=timeout)
        returncode = proc.returncode
        # W7: a return code is an arbitrary int. Only == 0 is pass —
        # never a range check. (POSIX itself masks codes to 8 bits:
        # sys.exit(300) arrives as 44 here and as 300 on Windows.)
        status = "PASS" if returncode == 0 else "FAIL"
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            out, err = proc.communicate(timeout=SECONDARY_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            out, err = b"", b""   # abandon the pipe; never block the fleet
        returncode = None
        status = "HUNG"
    duration = time.monotonic() - started
    return status, returncode, duration, out or b"", err or b""


# ──────────────────────────── the engine ───────────────────────────────

def run_gate(only=None, skip=None, fleet=None, base_dir=None,
             environ=None):
    """THE ENGINE (amendment A3): returns the report dict and writes the
    two surfaces (receipt + report file) plus the best-effort runlog
    line. gate_menu.py imports this and format_report() — it never
    re-implements stage running. Raises InvocationError for exit-2
    conditions before any stage runs."""
    fleet = FLEET if fleet is None else fleet
    base = Path(base_dir) if base_dir is not None else BASE_DIR
    environ = os.environ if environ is None else environ

    if only and skip:
        raise InvocationError("--only and --skip together — pick one")
    if not fleet:
        raise InvocationError("the fleet is empty — nothing to run is "
                              "not a pass")
    names = [e["name"] for e in fleet]
    if len(set(names)) != len(names):
        raise InvocationError("duplicate stage names in the fleet")
    for requested, flag in ((only, "--only"), (skip, "--skip")):
        for name in requested or []:
            if name not in names:
                raise InvocationError(
                    "unknown tool name %r in %s — fleet: %s. Refusing "
                    "to run zero stages and look like success."
                    % (name, flag, ", ".join(names)))

    excluded = []
    if only:
        excluded = [{"name": n, "by": "--only"} for n in names
                    if n not in only]
    elif skip:
        excluded = [{"name": n, "by": "--skip"} for n in names
                    if n in skip]
    excluded_names = {e["name"] for e in excluded}
    if len(excluded_names) == len(names):
        raise InvocationError("selection leaves zero stages to run — "
                              "refusing: it would look exactly like a "
                              "clean gate")

    run_id = uuid.uuid4().hex
    started_utc = _utc_now_iso()
    started_mono = time.monotonic()

    # W4: pre-flight the ENTIRE fleet before stage 1 — resolve every
    # path, check every requirement, report every problem at once.
    preflight_errors = []
    resolved = {}
    for entry in fleet:
        if entry["name"] in excluded_names:
            continue
        path = Path(entry["path"])
        if not path.is_absolute():
            path = base / path
        resolved[entry["name"]] = path
        if not path.is_file():
            preflight_errors.append(
                (entry["name"], "tool file not found: %s" % path))
            continue
        for var in entry.get("requires_env", []):
            if not environ.get(var):
                preflight_errors.append(
                    (entry["name"],
                     "required environment variable %s is not set" % var))
        if STATE_MD_PLACEHOLDER in entry.get("args", []):
            state_md = _resolve_state_md(environ)
            if not state_md.is_file():
                if environ.get(STATE_MD_ENV):
                    reason = ("%s points to a missing file: %s"
                              % (STATE_MD_ENV, state_md))
                else:
                    reason = ("%s is not set and the default %s is "
                              "absent — the stage cannot start"
                              % (STATE_MD_ENV, state_md))
                preflight_errors.append((entry["name"], reason))
    cant_start = {}
    for name, reason in preflight_errors:
        cant_start.setdefault(name, []).append(reason)

    # Run every non-excluded, startable stage. depends_on never skips —
    # halting on first failure is precedence-shadowing (the D-363
    # disease). All stages always run.
    reports_dir = base / REPORTS_DIRNAME
    report_path = reports_dir / ("gate_run_%s.txt" % run_id)
    stages = []
    for entry in fleet:
        record = {
            "name": entry["name"],
            "path": str(resolved.get(entry["name"],
                                     base / entry["path"])),
            "status": None, "returncode": None, "duration_s": 0.0,
            "stdout_bytes": 0, "stderr_bytes": 0,
            "output_ref": str(report_path),
            "depends_on": list(entry["depends_on"]),
            "downstream_note": None,
            "stdout_text": "", "stderr_text": "",   # report rendering only
        }
        if entry["name"] in excluded_names:
            record["status"] = "EXCLUDED"
        elif entry["name"] in cant_start:
            record["status"] = "CANT_START"
            record["stderr_text"] = "; ".join(cant_start[entry["name"]])
        else:
            status, returncode, duration, out, err = _run_stage(
                entry, resolved[entry["name"]], base, environ)
            record["status"] = status
            record["returncode"] = returncode
            record["duration_s"] = round(duration, 3)
            record["stdout_bytes"] = len(out)
            record["stderr_bytes"] = len(err)
            # errors="replace" at DISPLAY only (W14); lengths above are
            # from the raw bytes.
            record["stdout_text"] = out.decode("utf-8", errors="replace")
            record["stderr_text"] = err.decode("utf-8", errors="replace")
        stages.append(record)

    by_name = {s["name"]: s for s in stages}
    for record in stages:
        if record["status"] in BAD_STATUSES:
            for dep in record["depends_on"]:
                dep_status = by_name.get(dep, {}).get("status")
                if dep_status in BAD_STATUSES:
                    record["downstream_note"] = (
                        "may be downstream of %s %s" % (dep, dep_status))
                    break

    ran = [s for s in stages if s["status"] != "EXCLUDED"]
    bad = [s for s in stages if s["status"] in BAD_STATUSES]
    mode = "PARTIAL" if excluded else "FULL"
    if bad:
        verdict, exit_code = "FAIL", EXIT_FAIL
    elif mode == "PARTIAL":
        verdict, exit_code = "PARTIAL", EXIT_PARTIAL
    else:
        verdict, exit_code = "PASS", EXIT_PASS

    report = {
        "run_id": run_id,
        "started_utc": started_utc,
        "finished_utc": _utc_now_iso(),
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "runner_version": RUNNER_VERSION,
        "fleet_hash": fleet_hash(fleet),
        "mode": mode,
        "excluded": excluded,
        "verdict": verdict,
        "exit_code": exit_code,
        "duration_s": round(time.monotonic() - started_mono, 3),
        "counts": {
            "passed": sum(1 for s in ran if s["status"] == "PASS"),
            "failed": sum(1 for s in ran if s["status"] == "FAIL"),
            "hung": sum(1 for s in ran if s["status"] == "HUNG"),
            "cant_start": sum(1 for s in ran
                              if s["status"] == "CANT_START"),
            "excluded": len(excluded),
        },
        "receipt_path": str(base / RECEIPTS_NAME),
        "report_path": str(report_path),
        "notes": [],
        "stages": stages,
    }

    # Write surface 2: the report file — a RENDERING; deleting it loses
    # no truth (W10). Written before the receipt so the receipt's
    # output_ref points at something that exists.
    internal_error = None
    try:
        reports_dir.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8",
                  newline="\n") as handle:
            handle.write(format_report(report))
            handle.write("\n\n══ CAPTURED OUTPUT (rendering; receipt "
                         "stores byte lengths only) ══\n")
            for record in stages:
                handle.write("\n── %s (%s) stdout ──\n%s\n"
                             % (record["name"], record["status"],
                                record["stdout_text"] or "(empty)"))
                handle.write("── %s stderr ──\n%s\n"
                             % (record["name"],
                                record["stderr_text"] or "(empty)"))
    except OSError as exc:
        internal_error = "cannot write report file: %s" % exc

    # Write surface 1: the receipt — THE TRUTH, on every run including
    # PASS (W11). Silence must be diagnosable.
    if internal_error is not None:
        report["exit_code"] = EXIT_INTERNAL
        report["notes"].append(internal_error)
    try:
        receipt = {k: v for k, v in report.items() if k != "stages"}
        receipt["stages"] = [
            {k: v for k, v in s.items()
             if k not in ("stdout_text", "stderr_text")}
            for s in report["stages"]]
        with open(base / RECEIPTS_NAME, "a", encoding="utf-8",
                  newline="\n") as handle:
            handle.write(json.dumps(receipt, sort_keys=True,
                                    separators=(",", ":")))
            handle.write("\n")
    except OSError as exc:
        report["exit_code"] = EXIT_INTERNAL
        report["notes"].append("cannot write receipt: %s — RUNNER "
                               "INTERNAL ERROR" % exc)
        return report

    # Best-effort human line via runlog.py (amendment A1). Failure here
    # NEVER changes the verdict and is NEVER exit 3 — noted only.
    runlog = base / RUNLOG_NAME
    if runlog.is_file():
        word = {"PASS": "OK", "FAIL": "FAIL", "PARTIAL": "WARN"}[verdict]
        try:
            done = subprocess.run(
                [sys.executable, str(runlog), "gate-run", word,
                 "%s %s" % (run_id, verdict), "--verified",
                 "fleet %s · %d stages" % (report["fleet_hash"][:12],
                                           len(ran))],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=str(base), timeout=RUNLOG_TIMEOUT_S)
            if done.returncode != 0:
                report["notes"].append(
                    "runlog line not recorded (runlog.py exited %d); "
                    "verdict unchanged" % done.returncode)
        except (OSError, subprocess.TimeoutExpired) as exc:
            report["notes"].append(
                "runlog line not recorded (%s); verdict unchanged" % exc)
    else:
        report["notes"].append("runlog.py not present beside gate_run.py "
                               "— human ledger line skipped")
    return report


# ───────────────────────────── rendering ───────────────────────────────

def format_report(report):
    """ONE truth, two renderings (W13): this and --json both read the
    dict run_gate() returned."""
    out = []
    out.append("══ GATE RUN ══ run_id %s · %s"
               % (report["run_id"], report["started_utc"]))
    out.append("fleet: %d stages · mode: %s · fleet_hash %s"
               % (len(report["stages"]) - report["counts"]["excluded"],
                  report["mode"], report["fleet_hash"][:12]))
    if report["excluded"]:
        out.append("excluded: %s"
                   % ", ".join("%s (%s)" % (e["name"], e["by"])
                               for e in report["excluded"]))
    out.append("")
    out.append("%-18s %-11s %-5s %-8s %s"
               % ("stage", "status", "code", "time", ""))
    for record in report["stages"]:
        code = ("-" if record["returncode"] is None
                else str(record["returncode"]))
        note = ""
        if record["status"] == "HUNG":
            note = "timeout"
        elif record["status"] == "CANT_START":
            note = record["stderr_text"]
        if record["downstream_note"]:
            note = (note + "  " if note else "") + \
                "(%s)" % record["downstream_note"]
        out.append("%-18s %-11s %-5s %-8s %s"
                   % (record["name"], record["status"], code,
                      "%.1fs" % record["duration_s"], note))
    counts = report["counts"]
    out.append("")
    out.append("VERDICT: %s (%d failed, %d hung, %d cant-start, "
               "%d passed, %d excluded)"
               % (report["verdict"], counts["failed"], counts["hung"],
                  counts["cant_start"], counts["passed"],
                  counts["excluded"]))
    out.append("receipt: %s" % report["receipt_path"])
    out.append("report:  %s" % report["report_path"])
    for note in report["notes"]:
        out.append("NOTE: %s" % note)
    out.append("exit %d" % report["exit_code"])
    return "\n".join(out)


def exit_code_table():
    lines = ["exit codes (court-approved exception to the house 0/1/2 "
             "standard — R5):"]
    for code, name, meaning in EXIT_TABLE:
        lines.append("  %d  %-22s %s" % (code, name, meaning))
    lines.append("precedence: %s — a reduced run with a failing stage "
                 "exits 1, not 4." % EXIT_PRECEDENCE)
    return "\n".join(lines)


def render_list(fleet, base, environ):
    out = ["══ THE FLEET ══ (explicit ordered list — never globbed; "
           "hash %s)" % fleet_hash(fleet)[:12]]
    for entry in fleet:
        path = Path(entry["path"])
        if not path.is_absolute():
            path = base / path
        exists = "ok" if path.is_file() else "MISSING"
        args = " ".join(_substitute_args(entry["args"], environ)) or "-"
        out.append("  %-18s %-9s %s  args: %s  timeout: %ss%s"
                   % (entry["name"], exists, path, args,
                      entry["timeout_s"] or DEFAULT_TIMEOUT_S,
                      ("  depends_on: %s" % ",".join(entry["depends_on"])
                       if entry["depends_on"] else "")))
    out.append("write surfaces: %s and %s/"
               % (base / RECEIPTS_NAME, base / REPORTS_DIRNAME))
    return "\n".join(out)


def render_explain():
    return """\
══ GATE RUN — THE CHECKS AND WHY ══

subprocess only, never import (W1): the runner runs processes and reads
exit codes. It never pipes, tees, or redirects a tool's invocation —
verified on two machines: a tool exiting 7, piped to head, returns 0.
The failure does not degrade, it INVERTS: a red tool reports green.

exit code is the ONLY signal (W2): stdout/stderr are captured and
stored for a human, never parsed. A tool that prints "FAIL FAIL FAIL"
and exits 0 is a PASS; one that prints "everything is fine" and exits 1
is a FAIL. This closes output-parsing breakage permanently.

fail closed (W3): nonzero -> FAIL; can't start -> FAIL, never a skip;
hang past timeout -> HUNG (no returncode exists — none is fabricated);
empty fleet -> refuse; unknown --only/--skip name -> refuse. There is
no path where something went wrong and the verdict is PASS.

pre-flight (W4): every path and requirement checked before stage 1 —
all problems reported at once, in the first second.

all stages always run: depends_on annotates ("may be downstream of
color_check FAIL"), it never skips. Halting on first failure is
precedence-shadowing — the D-363 disease.

receipts (W10/W11): the JSONL ledger is the truth; the report file is
a rendering a human may delete with no loss. A receipt is written on
EVERY run, PASS included — a night with no receipt means the runner
did not run, never "nothing was wrong". Receipts store output byte
LENGTHS, not content: append-only, small, scannable for months, and it
enforces the no-parsing wall structurally.

partial is never a pass: --only/--skip yields verdict PARTIAL, exit 4,
with mode and excluded[] stated in the receipt and fleet_hash proving
what the full fleet was. A permanently skipped broken tool means
permanently PARTIAL — that is the truth, no escape hatch.

link_audit is deliberately EXCLUDED from the v1 fleet (not --skip'd):
it is hardcoded to the 5 incident products — a one-time checker, not a
nightly gate (amendment A5, from the live vault).

duration is RECORDED only in v1 (rider R7): the "anomalously fast
pass" flag ships in v1.1 with a wired rule or not at all — a flag with
no defined rule is prose.

""" + exit_code_table()


# ─────────────────────────────── the CLI ───────────────────────────────

def build_parser(base=None, environ=None):
    base = base if base is not None else BASE_DIR
    parser = argparse.ArgumentParser(
        prog="gate_run.py",
        description="The gate runner: runs the certified fleet in fixed "
                    "order, one verdict, receipts on every run.",
        epilog=exit_code_table() + "\n\nwrite surfaces (the only two): "
               "\n  receipts ledger: %s\n  report files:    %s%s"
               % (base / RECEIPTS_NAME, base / REPORTS_DIRNAME, os.sep) +
               "\nplus one best-effort human line via runlog.py after "
               "each receipt (A1);\nits failure never changes a verdict."
               "\n\nNOTE: this is a self-audit/integrity gate (rule "
               "audits, palette audit,\nvault lint) — per-design QC "
               "stays gate_menu's interactive job.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true",
                        help="machine output; same dict as human mode")
    parser.add_argument("--only", metavar="NAMES",
                        help="comma-separated stage names to run "
                             "(verdict PARTIAL at best, exit 4)")
    parser.add_argument("--skip", metavar="NAMES",
                        help="comma-separated stage names to exclude "
                             "(verdict PARTIAL at best)")
    parser.add_argument("--list", action="store_true",
                        help="print the fleet with resolved paths; no run")
    parser.add_argument("--explain", action="store_true",
                        help="every check and why it exists")
    return parser


def _split_names(text):
    return [n.strip() for n in (text or "").split(",") if n.strip()]


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else EXIT_BAD_INVOCATION
        return code

    try:
        if args.explain:
            print(render_explain())
            return EXIT_PASS
        if args.list:
            print(render_list(FLEET, BASE_DIR, os.environ))
            return EXIT_PASS

        report = run_gate(only=_split_names(args.only) or None,
                          skip=_split_names(args.skip) or None)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(format_report(report))
        return report["exit_code"]

    except InvocationError as exc:
        sys.stderr.write("ERROR: %s\n" % exc)
        return EXIT_BAD_INVOCATION
    except Exception as exc:   # the runner itself broke
        sys.stderr.write("RUNNER INTERNAL ERROR: %s\n" % exc)
        return EXIT_INTERNAL


if __name__ == "__main__":
    sys.exit(main())
