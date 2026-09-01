#!/usr/bin/env python3
"""tools/verification_flow/fix_regression_non_regression_gate.py

BUG FIX (2026-09-02, RE_AUDIT-precondition audit follow-up): this gate used
to accept target_pre_fix_result/target_post_fix_result as pure self-attested
JSON strings, never cross-checked against REGRESSION_MONITOR's actual
recorded result for the testcase. A real per-job registry does exist and is
readable the same way regression_submission_policy_gate.py's own
prior_failure_ref/_job_state_is_real_failure already reads it: one
JobState record per submitted LSF job at .dv-harness/lsf/jobs/<job_id>.json
(dv_harness/lsf_client.py save_job_state/load_job_state), with sim_status
advanced to "PASS"/"FAIL" by dv_harness/regression_reporter.py's real
analysis cycle -- the actual REGRESSION_MONITOR-maintained ground truth.

target_pre_fix_job_id/target_post_fix_job_id are OPTIONAL, additive fields:
when supplied, the claimed target_*_fix_result is cross-checked against that
job's real recorded sim_status (FAIL with TARGET_RESULT_CLAIM_MISMATCH on
disagreement, or TARGET_RESULT_JOB_REF_UNRESOLVED if the job_id does not
resolve to a real on-disk JobState record at all -- an agent cannot point at
a fabricated job id to dodge the check). A job_id (not a bare testcase_id
string) is required to identify a specific run unambiguously, matching
prior_failure_ref's own job_id convention -- the same testcase pattern can
be submitted more than once, so testcase_id alone cannot pin one recorded
result. When target_testcase_id is also supplied, the referenced job's own
`pattern` field must match it. Omitting the job_id fields entirely keeps the
prior self-attestation-only behavior unchanged (never a regression -- see
this file's own pre-existing TARGET_FIX_NOT_PROVEN check below)."""
import argparse,json,pathlib,sys

JOBS_DIR = pathlib.Path(".dv-harness") / "lsf" / "jobs"


def _load_job_record(job_id):
    p = JOBS_DIR / f"{job_id}.json"
    if not p.exists():
        return None
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) else None


ap=argparse.ArgumentParser(); ap.add_argument("--closure",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.closure).read_text())
if d.get("target_pre_fix_result")!="FAIL" or d.get("target_post_fix_result")!="PASS":
    print(json.dumps({"status":"FAIL","reason":"TARGET_FIX_NOT_PROVEN"})); sys.exit(2)

for _job_field, _result_field in (("target_pre_fix_job_id", "target_pre_fix_result"),
                                   ("target_post_fix_job_id", "target_post_fix_result")):
    _job_id = d.get(_job_field)
    if not _job_id:
        continue
    _rec = _load_job_record(_job_id)
    if _rec is None:
        print(json.dumps({"status":"FAIL","reason":"TARGET_RESULT_JOB_REF_UNRESOLVED",
                           "field":_job_field,"job_id":_job_id})); sys.exit(7)
    _recorded = _rec.get("sim_status")
    _claimed = d.get(_result_field)
    if _recorded != _claimed:
        print(json.dumps({"status":"FAIL","reason":"TARGET_RESULT_CLAIM_MISMATCH",
                           "field":_result_field,"job_id":_job_id,
                           "claimed":_claimed,"recorded":_recorded})); sys.exit(8)
    _target_testcase_id = d.get("target_testcase_id")
    _recorded_pattern = _rec.get("pattern")
    if _target_testcase_id and _recorded_pattern and _recorded_pattern != _target_testcase_id:
        print(json.dumps({"status":"FAIL","reason":"TARGET_RESULT_CLAIM_MISMATCH",
                           "field":"target_testcase_id","job_id":_job_id,
                           "claimed":_target_testcase_id,"recorded":_recorded_pattern})); sys.exit(8)

if d.get("replay_equivalent") is not True:
    print(json.dumps({"status":"FAIL","reason":"TARGET_RERUN_NOT_EQUIVALENT"})); sys.exit(3)
for t in d.get("critical_non_regression_tests",[]):
    if t.get("pre_fix_result")=="PASS" and t.get("post_fix_result")!="PASS":
        print(json.dumps({"status":"FAIL","reason":"FIX_CAUSED_REGRESSION","testcase_id":t.get("testcase_id")})); sys.exit(4)
    if t.get("pre_fix_result")=="PASS" and not t.get("evidence_hash"):
        print(json.dumps({"status":"FAIL","reason":"NON_REGRESSION_WITHOUT_EVIDENCE","testcase_id":t.get("testcase_id")})); sys.exit(5)
if not d.get("fix_commit_hash") or not d.get("rerun_bundle_hash"):
    print(json.dumps({"status":"FAIL","reason":"FIX_CLOSURE_WITHOUT_ARTIFACT_HASH"})); sys.exit(6)
print(json.dumps({"status":"PASS"}))
