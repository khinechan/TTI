#!/usr/bin/env python3
"""pack_check.py — the pack gate. Did play_forge actually render these
PNGs, or did something else?

WHY THIS EXISTS: 2026-09-06, real vault. play_forge flattened
multi-color art to blobs (W5, correct), so colour was hand-patched
back into the rendered PNGs afterwards and the gates were not re-run.
Those files sat in forge-out/ beside real renders, indistinguishable
from them, and were shown to Khai as if gated. The rule "gates run
before Khai sees anything" was PROSE — nothing in the fleet could tell
a play_forge render from a file someone painted over, and the spec
sheet next to a hand-edited PNG still said PASS.

This is the mechanism. play_forge records the sha256 of every file it
writes; this reads the folder back and asks the ledger.

    A PNG that is not in play_forge's ledger was not rendered by
    play_forge. It may still be a fine picture; it is not a gated
    render, and it does not go in a pack.

READ-ONLY, LIKE vault_lint. It writes nothing — not a fix, not a
backup, not even its own receipt. It is a gate STAGE; gate_run keeps
the ledger of gate results. There is no --fix flag and there never
will be one. A test sweeps the folder and the ledger sha256 before and
after a run to prove it.

    pack_check.py <folder> [--ledger PATH] [--json]

Exit codes:
    0 = every PNG in the folder is a verified play_forge render
    1 = findings: one or more PNGs are not in the ledger
    2 = tool or input error — folder missing, no ledger, unreadable
        ledger, or a folder with no PNGs in it at all (a pack with
        nothing in it is an input error, never a clean pass)

Stdlib only for its own imports. play_forge is imported for its
constants — the ledger name and location are never restated here,
because a duplicated constant drifts — and Pillow arrives with it
transitively, exactly as it does for play_new; a missing one refuses
DEP_MISSING rather than crashing.
"""

import argparse
import hashlib
import json
import os
import sys

FLEET_IMPORT_ERROR = None
try:
    import play_forge as pf
except BaseException as _err:            # noqa: BLE001 - deliberate
    FLEET_IMPORT_ERROR = "%s: %s" % (type(_err).__name__, _err)

# ═══════════════════════════════════════════════════════════════════════
# RULES ARE DATA.
# Every name, verdict and message below is a constant. The logic
# further down references these and never a literal.
# ═══════════════════════════════════════════════════════════════════════

TOOL_NAME = "pack_check"

# The one doctrine line, quoted verbatim by --explain and by every
# finding's tail. Facts only: this tool judges provenance, never taste.
DOCTRINE = ("A PNG that is not in play_forge's ledger was not rendered "
            "by play_forge. It may still be a fine picture; it is not "
            "a gated render, and it does not go in a pack.")

# Only files directly inside the folder, never a recursive walk: a
# pack is a flat folder of chosen renders, and a subfolder of working
# files is not part of it.
PNG_SUFFIX = ".png"

VERDICT_VERIFIED = "RENDER_VERIFIED"
FINDING_NOT_A_RENDER = "NOT_A_FORGE_RENDER"

# When the same bytes appear in more than one receipt (an identical
# re-render), the EARLIEST receipt wins. Deterministic and stable as
# the ledger grows — a later run never rewrites which run a file is
# attributed to.
FIRST_RECEIPT_WINS = True

READ_ONLY_NOTE = ("read-only: this tool writes nothing, not even a "
                  "receipt. gate_run keeps the ledger of gate results.")

HASH_CHUNK = 1 << 20

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2

# END OF RULE DATA. Logic below references the constants above.
# ═══════════════════════════════════════════════════════════════════════


class ToolError(Exception):
    """Input or tool error. Exits 2, never 1 — "the pack is wrong" and
    "the tool could not look" are different events."""

    def __init__(self, message, kind="INPUT"):
        super().__init__(message)
        self.kind = kind


def _ensure_utf8_console():
    """D-378 class: a cp1252 console must not turn a verdict into a
    UnicodeEncodeError. Display only."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def hash_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def default_ledger():
    """play_forge's own ledger, at the location play_forge writes it.
    Imported, never restated."""
    return os.path.join(str(pf.BASE_DIR), pf.RECEIPTS_NAME)


def load_ledger(path):
    """Every receipt in the ledger, in file order. Fail closed: a
    missing or unreadable ledger is exit 2, never an empty list — "no
    ledger" and "nothing rendered" must not look the same."""
    if not os.path.isfile(path):
        raise ToolError(
            "no play_forge ledger at %s — without it this tool cannot "
            "tell a render from a repaint, and it will not guess"
            % path, kind="LEDGER_MISSING")
    receipts = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    receipts.append(json.loads(line))
                except ValueError as err:
                    raise ToolError(
                        "ledger line %d is not valid JSON (%s): %s"
                        % (number, err, path), kind="LEDGER_UNREADABLE")
    except OSError as err:
        raise ToolError("ledger unreadable (%s): %s" % (err, path),
                        kind="LEDGER_UNREADABLE")
    return receipts


def index_renders(receipts):
    """sha256 -> the run that produced it. Only entries this tool can
    actually use: a receipt written before play_forge recorded hashes
    simply has no renders list, and contributes nothing."""
    index = {}
    for receipt in receipts:
        for entry in receipt.get("renders") or []:
            digest = entry.get("sha256")
            if not digest:
                continue
            if digest in index and FIRST_RECEIPT_WINS:
                continue
            index[digest] = {
                "play_id": receipt.get("play_id"),
                "completed_utc": receipt.get("completed_utc"),
                "file": entry.get("file"),
                "variant": entry.get("variant"),
            }
    return index


def pack_pngs(folder):
    """The PNGs directly inside the folder, sorted. Fail closed on a
    folder that is not there, and on one with nothing to check."""
    if not os.path.isdir(folder):
        raise ToolError("not a folder: %s" % folder,
                        kind="FOLDER_MISSING")
    names = sorted(name for name in os.listdir(folder)
                   if name.lower().endswith(PNG_SUFFIX)
                   and os.path.isfile(os.path.join(folder, name)))
    if not names:
        raise ToolError(
            "no %s files directly inside %s — a pack with nothing in "
            "it is an input error, not a clean pass"
            % (PNG_SUFFIX, folder), kind="EMPTY_PACK")
    return names


def run_check(folder, ledger_path):
    """The ONE report dict. Human output and --json both render this,
    so parity is structural."""
    names = pack_pngs(folder)
    index = index_renders(load_ledger(ledger_path))
    checked = []
    findings = []
    for name in names:
        digest = hash_file(os.path.join(folder, name))
        source = index.get(digest)
        if source is None:
            checked.append({"file": name, "sha256": digest,
                            "verdict": FINDING_NOT_A_RENDER,
                            "play_id": None, "completed_utc": None,
                            "rendered_as": None})
            findings.append(
                "%s: %s — sha256 %s is in no play_forge receipt. %s"
                % (FINDING_NOT_A_RENDER, name, digest, DOCTRINE))
            continue
        checked.append({"file": name, "sha256": digest,
                        "verdict": VERDICT_VERIFIED,
                        "play_id": source["play_id"],
                        "completed_utc": source["completed_utc"],
                        "rendered_as": source["file"]})
    verified = sum(1 for item in checked
                   if item["verdict"] == VERDICT_VERIFIED)
    return {
        "tool": TOOL_NAME,
        "folder": os.path.abspath(folder),
        "ledger": os.path.abspath(ledger_path),
        "counts": {"pngs": len(names), "verified": verified,
                   "not_a_forge_render": len(names) - verified},
        "checked": checked,
        "findings": findings,
        "doctrine": DOCTRINE,
        "exit_code": EXIT_FINDINGS if findings else EXIT_CLEAN,
    }


def format_report(report):
    counts = report["counts"]
    lines = ["pack_check %s  pngs=%d verified=%d not-a-render=%d  "
             "exit=%d" % (report["folder"], counts["pngs"],
                          counts["verified"],
                          counts["not_a_forge_render"],
                          report["exit_code"]),
             "  ledger: %s" % report["ledger"]]
    for item in report["checked"]:
        if item["verdict"] == VERDICT_VERIFIED:
            lines.append("  %s: %s — play %s, rendered %s"
                         % (item["file"], VERDICT_VERIFIED,
                            item["play_id"], item["completed_utc"]))
        else:
            lines.append("  %s: %s" % (item["file"],
                                       FINDING_NOT_A_RENDER))
    if report["findings"]:
        lines.append("  %s" % report["doctrine"])
    lines.append("  %s" % READ_ONLY_NOTE)
    return "\n".join(lines)


def render_explain():
    return "\n".join([
        "pack_check — the pack gate.",
        "",
        DOCTRINE,
        "",
        "It hashes every %s directly inside the folder and looks that"
        % PNG_SUFFIX,
        "sha256 up in play_forge's receipts ledger. Found: "
        + VERDICT_VERIFIED + ", named with the",
        "play and the time it was rendered. Not found: "
        + FINDING_NOT_A_RENDER + ", named by file.",
        "",
        "Exit 0 every PNG verified · 1 findings · 2 tool or input "
        "error",
        "(folder missing, no ledger, unreadable ledger, or no PNGs at "
        "all).",
        "",
        READ_ONLY_NOTE,
    ])


def build_parser():
    parser = argparse.ArgumentParser(
        prog="pack_check.py",
        description="Did play_forge render these PNGs? Read-only.")
    parser.add_argument("folder", nargs="?",
                        help="the pack folder to check")
    parser.add_argument("--ledger", default=None,
                        help="play_forge receipts ledger (default: "
                             "the one beside play_forge.py)")
    parser.add_argument("--json", action="store_true",
                        help="machine output, same report dict")
    parser.add_argument("--explain", action="store_true",
                        help="what this gate checks, and why")
    return parser


def _emit_error(kind, message, as_json):
    if as_json:
        print(json.dumps({"tool": TOOL_NAME, "verdict": "ERROR",
                          "exit_code": EXIT_ERROR,
                          "error_kind": kind, "error": message},
                         indent=2, sort_keys=True))
    else:
        sys.stderr.write("ERROR [%s]: %s\n" % (kind, message))


def _main(argv=None):
    _ensure_utf8_console()
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    args = parser.parse_args(argv)
    try:
        if args.explain:
            print(render_explain())
            return EXIT_CLEAN
        if FLEET_IMPORT_ERROR is not None:
            raise ToolError(
                "play_forge could not be imported (%s) — its ledger "
                "name and location come from it, and are never "
                "restated here" % FLEET_IMPORT_ERROR,
                kind="DEP_MISSING")
        if not args.folder:
            raise ToolError("no folder given — usage: pack_check.py "
                            "FOLDER [--ledger PATH] [--json]")
        ledger_path = args.ledger or default_ledger()
        report = run_check(args.folder, ledger_path)
    except ToolError as err:
        _emit_error(err.kind, str(err), args.json)
        return EXIT_ERROR
    print(json.dumps(report, indent=2, sort_keys=True) if args.json
          else format_report(report))
    return report["exit_code"]


def main(argv=None):
    """CRASH FLOOR. A bare traceback exits 1, and this tool's contract
    reads 1 as "findings" — a real verdict on a real pack. So without
    this guard a crash and an ungated PNG are the same integer to
    gate_run and to any wrapper. SystemExit and KeyboardInterrupt are
    NOT caught: argparse owns exit 2 for a bad flag and must stay
    untouched. This tool writes nothing, so the CRASH line IS the
    record."""
    try:
        return _main(argv)
    except Exception as err:
        reason = "%s: %s" % (type(err).__name__, err)
        source = sys.argv[1:] if argv is None else list(argv)
        if "--json" in source:
            print(json.dumps({"tool": TOOL_NAME, "verdict": "CRASH",
                              "exit_code": EXIT_ERROR,
                              "error": reason},
                             indent=2, sort_keys=True))
        else:
            sys.stderr.write("CRASH (%s): %s\n"
                             % (type(err).__name__, err))
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
