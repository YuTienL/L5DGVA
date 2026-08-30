#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--state",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.state).read_text())

jobs=d.get("elaboration_jobs",[])
shared=d.get("shared_output_paths",[])
active=[j for j in jobs if j.get("state") in ("RUN","PEND","STARTING")]

# More than one active elab writer to same shared outputs is forbidden.
writers={}
for j in active:
    for p in j.get("write_paths",[]):
        writers.setdefault(p,[]).append(j.get("job_id"))
for p,ids in writers.items():
    if p in shared and len(ids)>1:
        print(json.dumps({"status":"FAIL","reason":"CONCURRENT_SHARED_ELABORATION_COLLISION",
                          "path":p,"job_ids":ids})); sys.exit(2)

if d.get("parallel_test_workers",0)>1 and d.get("each_worker_runs_full_compile"):
    print(json.dumps({"status":"FAIL","reason":"PARALLEL_WORKERS_MUST_NOT_RECOMPILE_SHARED_SIMV"})); sys.exit(3)

if d.get("build_owner_count",0)!=1:
    print(json.dumps({"status":"FAIL","reason":"SINGLE_BUILD_OWNER_REQUIRED",
                      "build_owner_count":d.get("build_owner_count",0)})); sys.exit(4)

if d.get("simv_valid") and d.get("worker_invokes_usbc_elab"):
    print(json.dumps({"status":"FAIL","reason":"REDUNDANT_ELAB_WHEN_VALID_SIMV_EXISTS"})); sys.exit(5)

print(json.dumps({"status":"PASS"}))
