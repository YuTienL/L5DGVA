#!/usr/bin/env python3
# NOTICE (corrected 2026-08-31, protocol-generalization-gap-closing fix
# wave): this CLI calls UVMEnvironmentGenerator(...).generate(m) directly --
# that is generator.py's flat top-level generate() orchestration, which is
# DEPRECATED (see dv_harness/uvm_generator/generator.py's own NOTICE).
# tools/generate_protocol_uvm_environment.py (driving ProtocolEnvGenerator)
# is the preferred/official CLI going forward; it reuses this module's
# per-class emit methods unchanged but writes into the real subdirectory
# layout instead of this script's flat-file layout. This script is kept
# working as-is (not removed), but new callers should prefer the
# ProtocolEnvGenerator-based CLI.
import argparse,json,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dv_harness.uvm_generator.generator import UVMEnvironmentGenerator
ap=argparse.ArgumentParser()
ap.add_argument('--model',required=True)
ap.add_argument('--out',required=True)
a=ap.parse_args()
m=json.loads(pathlib.Path(a.model).read_text(encoding="utf-8"))
files=UVMEnvironmentGenerator(a.out).generate(m)
print('Generated',len(files),'files')
for f in files: print(f)
