#!/usr/bin/env python3
import argparse, json, pathlib, sys, datetime
# BUG FIX (2026-08-28, plan-qualification-vocab design pass): was a nested
# {"qualification": {"status": "BUILDER_AVAILABLE"}} -- the only writer of
# that shape anywhere in the repo, never read by anything downstream. Now a
# flat qualification_status field, matching dv_harness/uvm_generator/
# generator.py's convention (the shape examples/generated_pcie_uvm_env/'s
# real manifest actually uses).
_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
from dv_harness.qualification import QualificationTier
ap=argparse.ArgumentParser()
ap.add_argument('--protocol',required=True)
ap.add_argument('--dut',required=True)
ap.add_argument('--role',required=True)
ap.add_argument('--out',required=True)
a=ap.parse_args()
d={
 "protocol":a.protocol,"dut":{"name":a.dut},"role":a.role,
 "interfaces":[],"clocks":[],"resets":[],"vip":{"status":"DISCOVERY_REQUIRED"},
 "tests":[],"scoreboards":[],"coverage":[],"evidence":[],
 "qualification_status":QualificationTier.BUILDER_AVAILABLE.value,
 "generated_at":datetime.datetime.now(datetime.timezone.utc).isoformat()
}
p=pathlib.Path(a.out); p.parent.mkdir(parents=True,exist_ok=True)
p.write_text(json.dumps(d,indent=2))
print(p)
