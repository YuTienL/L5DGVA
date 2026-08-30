#!/usr/bin/env python3
# Thin CLI shim over dv_harness/uvm_generator/regression_list_manager.py --
# mirrors tools/generate_amba_fabric_environment.py's integration level (a
# standalone script, not a dv-harness CLI subcommand).
import argparse, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dv_harness.uvm_generator.regression_list_manager import (
    record_verdict, record_suite, emit_makefile_fragment,
)


def _read_list(path):
    p = pathlib.Path(path)
    if not p.exists():
        return []
    return [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _write_list(path, lines):
    pathlib.Path(path).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", required=True, help="path to regression.list")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_verdict = sub.add_parser("record-verdict")
    p_verdict.add_argument("--pattern", required=True)
    group = p_verdict.add_mutually_exclusive_group(required=True)
    group.add_argument("--passed", action="store_true")
    group.add_argument("--failed", action="store_true")

    p_suite = sub.add_parser("record-suite")
    p_suite.add_argument("--verdicts", required=True,
                          help='path to JSON file: [["pattern", true|false], ...]')

    p_makefile = sub.add_parser("emit-makefile-fragment")
    p_makefile.add_argument("--out", required=True)

    a = ap.parse_args()

    if a.cmd == "record-verdict":
        lines = record_verdict(_read_list(a.list), a.pattern, a.passed)
        _write_list(a.list, lines)
        print(json.dumps({"status": "OK", "list": a.list, "entries": lines}))
    elif a.cmd == "record-suite":
        verdicts = [tuple(v) for v in json.loads(pathlib.Path(a.verdicts).read_text(encoding="utf-8"))]
        lines = record_suite(_read_list(a.list), verdicts)
        _write_list(a.list, lines)
        print(json.dumps({"status": "OK", "list": a.list, "entries": lines}))
    elif a.cmd == "emit-makefile-fragment":
        pathlib.Path(a.out).write_text(emit_makefile_fragment(a.list), encoding="utf-8")
        print(json.dumps({"status": "OK", "out": a.out}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
