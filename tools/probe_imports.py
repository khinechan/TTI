#!/usr/bin/env python3
"""STEP 0 for play_new.py. Reports the REAL import surface. Writes nothing.
Exit 0 = every expected surface present. Exit 2 = something is missing (named)."""
import importlib, inspect, json, os, sys

# This file lives in tools/, so sys.path[0] is tools/ and every fleet
# module at the repo root is invisible — as delivered the probe
# reported all four as ModuleNotFoundError and could never exit 0.
# Put the repo root on the path before importing anything.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# WANT corrected by Fable's riders, verified against the real branch:
# the layout registry is LAYOUT_SPECS (play_forge) / LAYOUTS
# (play_schema), never LAYOUT_REGISTRY; asset_index_lint exposes the
# per-ROW entry point lint_row and has no lint_file/lint;
# play_schema.validate_play takes a DICT, load_play takes a PATH.
WANT = {
    "play_schema":      {"callables": ["load_play", "validate_play"],
                         "constants": ["LAYOUTS", "FAMILIES", "ELEMENT_KINDS"]},
    "play_forge":       {"callables": ["check_structure", "load_config",
                                       "line_is_all_caps"],
                         "constants": ["FONT_ROSTER", "TITLE_CASE_ONLY_FONTS",
                                       "LAYOUT_SPECS"]},
    "asset_index_lint": {"callables": ["lint_row", "asset_path", "asset_paths",
                                       "find_header_lines"], "constants": []},
    "color_check":      {"callables": [],
                         "constants": ["GARMENTS", "PALETTES", "BASE_FILLS", "OUTLINES"]},
    # B5 (asset_compose) STEP 0, 2026-09-06.
    "play_new":         {"callables": ["infer_kind"],
                         "constants": ["KIND_KEYWORDS",
                                       "KIND_CLAUSE_DELIMITERS",
                                       "STYLE_COLUMN"]},
    "asset_ingest":     {"callables": ["label_components", "load_sidecar",
                                       "write_sidecar"],
                         "constants": ["SIDECAR_NAME", "SIDECAR_VERSION",
                                       "CONVERT_TARGET_PX", "USED_IN_FMT"]},
    "recolor":          {"callables": ["recolor"], "constants": []},
}
WANT["asset_index_lint"]["constants"] = ["COLUMN_COUNT", "HEADER_CELLS",
                                         "ASSET_PATH_JOIN"]
WANT["play_forge"]["callables"].append("measure_stroke_survival")
report = {"modules": {}, "missing": [], "ok": True}
for mod, want in WANT.items():
    entry = {"import": "ok", "callables": {}, "constants": {}, "all_public": []}
    try:
        m = importlib.import_module(mod)
    except Exception as e:
        entry["import"] = "%s: %s" % (type(e).__name__, e)
        report["missing"].append(mod); report["ok"] = False
        report["modules"][mod] = entry; continue
    entry["all_public"] = sorted(n for n in dir(m) if not n.startswith("_"))
    for name in want["callables"]:
        fn = getattr(m, name, None)
        if fn is None:
            entry["callables"][name] = None
        else:
            sig = inspect.signature(fn)
            entry["callables"][name] = {
                "signature": str(sig),
                "params": [{"name": p.name, "kind": str(p.kind),
                            "has_default": p.default is not inspect._empty}
                           for p in sig.parameters.values()],
                "doc": (inspect.getdoc(fn) or "").splitlines()[:2],
            }
    for name in want["constants"]:
        v = getattr(m, name, None)
        if v is None:
            entry["constants"][name] = None
        else:
            entry["constants"][name] = {
                "type": type(v).__name__,
                "len": (len(v) if hasattr(v, "__len__") else None),
                "sample": (sorted(v.keys())[:6] if isinstance(v, dict)
                           else list(v)[:6] if hasattr(v, "__iter__")
                                               and not isinstance(v, str)
                           else repr(v)),
            }
    report["modules"][mod] = entry

for mod, e in report["modules"].items():
    for k, v in list(e["callables"].items()) + list(e["constants"].items()):
        if v is None:
            report["missing"].append("%s.%s" % (mod, k)); report["ok"] = False

print(json.dumps(report, indent=2, sort_keys=True))
sys.exit(0 if report["ok"] else 2)
