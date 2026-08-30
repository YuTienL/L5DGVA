#!/usr/bin/env python3
# Mirrors tools/generate_amba_fabric_environment.py's exact shape -- a
# standalone script, not a dv-harness CLI subcommand.
import argparse, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dv_harness.uvm_generator.pattern_registry_generator import (
    build_registry, emit_registry_txt, emit_pattern_pool_svh, emit_makefile_fragment,
)

ap = argparse.ArgumentParser()
ap.add_argument('--patterns', required=True, help='JSON: [{"name","suite","dir","file"?}, ...]')
ap.add_argument('--declared-suites', help='optional JSON: ["suite0", "suite1", ...] fixed taxonomy')
ap.add_argument('--out', required=True)
a = ap.parse_args()

patterns = json.loads(pathlib.Path(a.patterns).read_text(encoding="utf-8"))
declared = json.loads(pathlib.Path(a.declared_suites).read_text(encoding="utf-8")) if a.declared_suites else None
registry = build_registry(patterns, declared_suites=declared)

out = pathlib.Path(a.out)
out.mkdir(parents=True, exist_ok=True)
(out / "registry.json").write_text(json.dumps(registry, indent=2), encoding="utf-8")
(out / "pattern_list.txt").write_text(emit_registry_txt(registry), encoding="utf-8")
(out / "dv_uvm_pattern_pool.svh").write_text(emit_pattern_pool_svh(registry), encoding="utf-8")
(out / "pattern_registry.mk").write_text(
    emit_makefile_fragment(str(out / "pattern_list.txt")), encoding="utf-8")

print(json.dumps({"status": "OK", "pattern_count": len(registry["patterns"]),
                   "suite_names": registry["suite_names"], "out": str(out)}))
