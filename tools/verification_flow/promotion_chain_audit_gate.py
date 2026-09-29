#!/usr/bin/env python3
import argparse, json, os, pathlib, sys

ORDER = [
    "INTAKE_READY",
    "VPLAN_READY",
    "ARCHITECTURE_READY",
    "MECHANISM_READY",
    "TESTS_READY",
    "TRACEABILITY_READY",
    "EXECUTION_EVIDENCE_READY",
    "COVERAGE_QUALITY_READY",
    "RCA_READY",
    "RERUN_READY",
    "EXPERT_REVIEW_READY",
    "EXPERIENCE_READY",
    "PROMOTABLE"
]

# M8 Cohort 1 (CAP-M8-EXPLOOP-001 / GAP-M8-001): the real, already-wired
# promotion events dv_harness/engine.py's own route_and_store() call sites
# emit via StateStore.event() into this project's .dv-harness/events.jsonl
# (see engine.py lines ~1944/3189/3258/3434/3656). A real, non-failed write
# under one of these names is what now corroborates an EXPERIENCE_READY
# claim below instead of accepting the agent's bare say-so. Extend this set
# (never let it silently drift) if a 6th real promotion call site is added.
REAL_PROMOTION_EVENTS = {
    "EXPERIENCE_KNOWLEDGE_PROMOTED",
    "PROJECT_TOPOLOGY_PROMOTED",
    "VPLAN_SUMMARY_PROMOTED",
    "VERIFIED_FIX_PROMOTED",
    "DEBUG_ATTEMPT_JOB_MEMORY_RECORDED",
}


def _project_root():
    # Same DV_HARNESS_PROJECT_ROOT convention as waiver_scope_consistency_
    # gate.py / waiver_revision_freshness_gate.py / waiver_revalidation_
    # gate.py (dv_harness/gates.py's _gate_env(): a harness-supplied fact,
    # never sourced from agent-authored evidence text, so this check can't
    # be pointed at a fabricated tree). cwd fallback matches run_gate()'s
    # own cwd=<project root> subprocess convention.
    return pathlib.Path(os.environ.get("DV_HARNESS_PROJECT_ROOT") or os.getcwd())


def _real_experience_promotion_exists(root: pathlib.Path) -> bool:
    """True iff this project's own real, durable events.jsonl (dv_harness/
    storage.py's StateStore.event(), the same mechanism every engine.py
    route_and_store() call site already writes through) contains at least
    one real promotion event whose own `promotion` result reports a real,
    non-failed destination. GAP-M8-001's fix: previously EXPERIENCE_READY
    was structurally validated (non-empty string, right position) but never
    independently corroborated against anything real."""
    events_file = root / ".dv-harness" / "events.jsonl"
    if not events_file.exists():
        return False
    try:
        lines = events_file.read_text(encoding="utf-8").splitlines()
    except Exception:
        return False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("event") not in REAL_PROMOTION_EVENTS:
            continue
        promotion = rec.get("promotion")
        if not isinstance(promotion, dict):
            continue
        destination = promotion.get("destination")
        if not destination or destination == "PROMOTION_FAILED":
            continue
        return True
    return False


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--audit", required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.audit).read_text())
    events=d.get("events",[])
    if not events:
        print(json.dumps({"status":"FAIL","reason":"NO_EVENTS"})); return 2

    seen=[]
    names=set()
    for e in events:
        stage=e.get("stage")
        if stage not in ORDER:
            print(json.dumps({"status":"FAIL","reason":"UNKNOWN_STAGE","stage":stage})); return 3
        if stage in names:
            print(json.dumps({"status":"FAIL","reason":"DUPLICATE_STAGE","stage":stage})); return 4
        if not e.get("evidence"):
            print(json.dumps({"status":"FAIL","reason":"STAGE_WITHOUT_EVIDENCE","stage":stage})); return 5
        names.add(stage)
        seen.append(stage)

    # Enforce monotonic order
    idx=[ORDER.index(x) for x in seen]
    if idx != sorted(idx):
        print(json.dumps({"status":"FAIL","reason":"NON_MONOTONIC_PROMOTION_CHAIN","events":seen})); return 6

    # PROMOTABLE requires all mandatory stages before it, RCA/RERUN may be omitted only if no failure
    failure=d.get("failure_detected", False)
    mandatory = ORDER[:8] + ["EXPERT_REVIEW_READY","EXPERIENCE_READY","PROMOTABLE"]
    if failure:
        mandatory = ORDER
    missing=[x for x in mandatory if x not in names]
    if missing:
        print(json.dumps({"status":"FAIL","reason":"MISSING_PROMOTION_STAGES","missing":missing})); return 7

    # GAP-M8-001 (M8 Cohort 1): EXPERIENCE_READY is an agent-self-attested
    # stage name in this same --audit JSON, checked structurally above like
    # every other stage but never previously corroborated against anything
    # real. Require a real backing promotion event now.
    if "EXPERIENCE_READY" in names and not _real_experience_promotion_exists(_project_root()):
        print(json.dumps({
            "status": "FAIL", "reason": "EXPERIENCE_READY_NOT_VERIFIED",
            "detail": ("EXPERIENCE_READY was self-attested but no real promotion event "
                       "(EXPERIENCE_KNOWLEDGE_PROMOTED or a sibling route_and_store() "
                       "event) with a real, non-failed destination was found in this "
                       "project's .dv-harness/events.jsonl"),
        }))
        return 8

    print(json.dumps({"status":"PASS","stages":seen,"failure_detected":failure}))
    return 0

if __name__=="__main__":
    sys.exit(main())
