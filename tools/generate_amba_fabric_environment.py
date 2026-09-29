#!/usr/bin/env python3
# Mirrors tools/generate_uvm_environment.py's exact shape -- same integration
# level as generator.py's deprecated flat-orchestration single-agent
# generator (generator.py's own per-class emit methods remain live and
# authoritative; only its top-level generate() orchestration is deprecated,
# in favor of ProtocolEnvGenerator -- see generator.py's NOTICE): a
# standalone script, not a dv-harness CLI subcommand.
import argparse, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dv_harness.uvm_generator.amba_fabric_generator import AMBAFabricGenerator
ap = argparse.ArgumentParser()
ap.add_argument('--topology', required=True)
ap.add_argument('--out', required=True)
a = ap.parse_args()
t = json.loads(pathlib.Path(a.topology).read_text(encoding="utf-8"))
files = AMBAFabricGenerator(a.out).generate(t)
print('Generated', len(files), 'files')
for f in files:
    print(f)
