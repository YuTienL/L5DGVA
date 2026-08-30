#!/usr/bin/env python3
# Mirrors tools/generate_amba_fabric_environment.py's exact shape -- a
# standalone script, not a dv-harness CLI subcommand.
import argparse, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dv_harness.uvm_generator.pcie_ltssm_generator import PCIeLTSSMGenerator
ap = argparse.ArgumentParser()
ap.add_argument('--topology', required=True)
ap.add_argument('--out', required=True)
a = ap.parse_args()
t = json.loads(pathlib.Path(a.topology).read_text(encoding="utf-8"))
files = PCIeLTSSMGenerator(a.out).generate(t)
print('Generated', len(files), 'files')
for f in files:
    print(f)
