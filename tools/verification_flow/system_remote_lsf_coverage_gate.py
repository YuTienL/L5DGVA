#!/usr/bin/env python3
import argparse,json,pathlib,sys
REQ={"system_level":["system_level_composition_gate","system_level_traceability_gate","system_level_release_pinning_gate","system_level_change_impact_gate","system_level_deadlock_livelock_gate"],"remote_control":["remote_control_supervisory_gate","remote_state_transition_gate","remote_action_audit_gate","remote_action_replay_gate"],"lsf_monitoring":["lsf_per_job_monitor_gate"]}
ap=argparse.ArgumentParser(); ap.add_argument("--flow",required=True); a=ap.parse_args(); f=json.loads(pathlib.Path(a.flow).read_text())
missing={g:[k for k in ks if not f.get(k)] for g,ks in REQ.items()}; missing={k:v for k,v in missing.items() if v}
if missing: print(json.dumps({"status":"FAIL","reason":"CONTROL_PLANE_COVERAGE_GAP","missing":missing})); sys.exit(2)
print(json.dumps({"status":"PASS"}))
