#!/usr/bin/env python3
import argparse,json,pathlib,sys,math
ap=argparse.ArgumentParser(); ap.add_argument("--rerun",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.rerun).read_text())
if d.get("deep_debug_required") is not True:
    print(json.dumps({"status":"FAIL","reason":"FOCUSED_WAVE_RERUN_WITHOUT_NEED"})); sys.exit(2)
# CLAUDE.md "Waveform Dump User Gate": before ANY waveform-enabled simulation,
# the user must be asked to confirm dump scope and level/depth -- this gate
# previously only checked the technical rerun mechanics (window math, kill,
# identity) and never enforced that confirmation actually happened, despite
# .dv-harness/governance/waveform_dump_policy.json declaring
# user_confirmation_required=true with required_fields=[scope,level_or_depth].
# Found by the 2026-08-28 GUI/CLI end-to-end confirmation audit: this was the
# one CLAUDE.md rule with a governance policy file but literally no enforcing
# gate anywhere in the pipeline -- an agent that forgot to ask would never be
# caught. Added 2026-08-28.
policy_path = pathlib.Path(".dv-harness/governance/waveform_dump_policy.json")
required_fields = ["scope", "level_or_depth"]
if policy_path.exists():
    try:
        required_fields = json.loads(policy_path.read_text()).get("required_fields", required_fields)
    except Exception:
        pass
confirm = d.get("dump_scope_confirmed")
if not isinstance(confirm, dict):
    print(json.dumps({"status":"FAIL","reason":"WAVEFORM_DUMP_SCOPE_NOT_CONFIRMED",
                      "required_fields": required_fields})); sys.exit(9)
missing = [f for f in required_fields if not str(confirm.get(f) or "").strip()]
if missing or not str(confirm.get("confirmed_by") or "").strip():
    print(json.dumps({"status":"FAIL","reason":"WAVEFORM_DUMP_SCOPE_CONFIRMATION_INCOMPLETE",
                      "missing_fields": missing + (["confirmed_by"] if not str(confirm.get("confirmed_by") or "").strip() else [])})); sys.exit(10)
if d.get("wave_mode")!=1 or d.get("fsdb_start_us")!=0:
    print(json.dumps({"status":"FAIL","reason":"FOCUSED_RERUN_MUST_USE_WAVE1_FROM_TIME0"})); sys.exit(3)
terr=d.get("first_error_time_us"); stop=d.get("fsdb_stop_us")
if terr is None or stop is None or not math.isclose(float(stop),float(terr)+200.0,rel_tol=0,abs_tol=1e-9):
    print(json.dumps({"status":"FAIL","reason":"INVALID_FOCUSED_FSDB_STOP_WINDOW",
                      "expected_stop_us":None if terr is None else float(terr)+200.0})); sys.exit(4)
if d.get("simulation_stopped_at_fsdb_stop") is not True:
    print(json.dumps({"status":"FAIL","reason":"SIMULATION_NOT_STOPPED_AFTER_CAPTURE"})); sys.exit(5)
if d.get("job_killed_or_terminated") is not True:
    print(json.dumps({"status":"FAIL","reason":"JOB_NOT_KILLED_AFTER_FOCUSED_CAPTURE"})); sys.exit(6)
if d.get("identity_preserved") is not True:
    print(json.dumps({"status":"FAIL","reason":"FOCUSED_RERUN_IDENTITY_DRIFT"})); sys.exit(7)
if not d.get("waveform_or_fsdbreport_evidence_hash"):
    print(json.dumps({"status":"FAIL","reason":"NO_FOCUSED_WAVEFORM_EVIDENCE"})); sys.exit(8)
print(json.dumps({"status":"PASS"}))
