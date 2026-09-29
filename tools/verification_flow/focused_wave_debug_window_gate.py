#!/usr/bin/env python3
import argparse,json,os,pathlib,sys,math
_env_root = os.environ.get("DV_HARNESS_PACKAGE_ROOT")
_ROOT = pathlib.Path(_env_root) if _env_root else pathlib.Path(__file__).resolve().parents[2]  # dogfooding/legacy fallback
sys.path.insert(0, str(_ROOT))
from dv_harness.waveform_dump_gate import verify_dump_scope_confirmation  # noqa: E402
ap=argparse.ArgumentParser(); ap.add_argument("--rerun",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.rerun).read_text())
# ESCAPE HATCH (targeted-wave-debug-window-recovery-wiring, 2026-09-02): this
# gate is now also mandatory (see dv_harness/gates.py STAGE_GATES) for
# FAILURE_RECOVERY, which -- unlike WAVE_ANALYSIS's always-do-a-representative-
# wave-rerun flow -- must legitimately skip waveform entirely when cheaper
# evidence already located the failure (CLAUDE.md "Evidence cost order,
# low to high ... do not open FSDB first", restated in this stage's own
# STAGE_INSTRUCTIONS text). Same "<x>_applicable:false + reason" escape-hatch
# shape already used by fabric_topology_completeness_gate/protocol_structural_
# completeness_gate/system_level_subsystem_set_completeness_gate for a
# mandatory-but-not-always-relevant evidence block, applied here to
# deep_debug_required's existing field rather than inventing a new one: an
# explicit False must carry a real justification, or this still FAILs --
# a bare absent/falsy value (the pre-existing behavior) is not enough to
# silently skip the check.
if d.get("deep_debug_required") is False:
    if not str(d.get("deep_debug_not_required_reason") or "").strip():
        print(json.dumps({"status":"FAIL","reason":"DEEP_DEBUG_NOT_REQUIRED_WITHOUT_REASON"})); sys.exit(11)
    print(json.dumps({"status":"PASS","deep_debug_required":False})); sys.exit(0)
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
#
# STRENGTHENED 2026-09-04 (AI-mechanism #12 "AI Debug Closed Loop" gap
# closure). The 2026-08-28 version above checked that `confirmed_by` was a
# non-empty string -- a value the agent writing this evidence block fills in
# itself. That is honest on the interactive path (a human really was asked)
# and unsatisfiable-except-by-fabrication on the autonomous one:
# engine.loop() dispatches a headless `claude -p --dangerously-skip-permissions`
# subprocess with no live channel back to a human, so an in-flight
# AskUserQuestion cannot be answered and the ONLY way past this gate was the
# LLM self-filling the field -- the gate passing exactly when nobody had been
# asked. `confirmed_by` is now cross-checked against the real question-queue
# decision for this scope (dv_harness/waveform_dump_gate.py), which only
# `QuestionQueueStore.answer_question()` -- i.e. a human running
# `dv-harness question-queue answer` -- can write.
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
                      "needs_user_input": True,
                      "required_fields": required_fields})); sys.exit(9)
missing = [f for f in required_fields if not str(confirm.get(f) or "").strip()]
if missing or not str(confirm.get("confirmed_by") or "").strip():
    print(json.dumps({"status":"FAIL","reason":"WAVEFORM_DUMP_SCOPE_CONFIRMATION_INCOMPLETE",
                      "needs_user_input": True,
                      "missing_fields": missing + (["confirmed_by"] if not str(confirm.get("confirmed_by") or "").strip() else [])})); sys.exit(10)
# The confirmation must resolve to a REAL human answer in the question queue,
# not to whatever string the agent wrote. Project root is the cwd (same
# convention policy_path above already uses; gates.run_gate always runs this
# script with cwd=<project root>), never DV_HARNESS_PACKAGE_ROOT, which only
# locates the importable package.
_ok, _detail = verify_dump_scope_confirmation(pathlib.Path("."), confirm)
if not _ok:
    print(json.dumps({"status":"FAIL", **_detail})); sys.exit(12)
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
