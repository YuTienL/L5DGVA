#!/usr/bin/env python3
# Mirrors tools/generate_uvm_environment.py's / generate_amba_fabric_environment.py's
# exact shape -- a standalone script, not a dv-harness CLI subcommand.
import argparse, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dv_harness.uvm_generator.protocol_env_generator import ProtocolEnvGenerator

ap = argparse.ArgumentParser()
ap.add_argument('--manifest', required=True)
ap.add_argument('--out', required=True)
a = ap.parse_args()
m = json.loads(pathlib.Path(a.manifest).read_text(encoding="utf-8"))
files = ProtocolEnvGenerator(a.out).generate(m)
print(json.dumps({"status": "OK", "generated_files": files, "out": a.out}))
