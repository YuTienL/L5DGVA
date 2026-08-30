#!/usr/bin/env python3
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
