"""One-off script persisting the 2026-09-02 DEBUG_WORKFLOW_GUIDE.md gap
audit + closure into the harness's own Engineering Memory tier, via
memory_router.route_and_store() -- per the standing session policy: any
confirmed gap must be distilled into permanent harness capability AND
written back to the shared Knowledge Center (/home/svcacct/AI/DB).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dv_harness.memory_router import route_and_store

ROOT = Path(r"D:\DV\Task\DV_Agent_Harness_L5\v50")

RECORD = {
    "kind": "verified_fix",
    "verified": True,
    "title": "DEBUG_WORKFLOW_GUIDE.md audit: 8 confirmed gaps between documented and wired debug workflow, 6 closed",
    "scope": "engine",
    "symptoms": [
        "A doc describing the intended FAILURE_RECOVERY/RE_AUDIT debug workflow (FSDB-off default, targeted waveform rerun, Waveform Dump Gate, Knowledge Center lookup, Evidence Truth Rule, human sign-off, RTL write protection, single-test-before-full-regression, auto-persist verified fixes) reads as accurate, but a code audit found every single claim PARTIALLY_WIRED -- real gate scripts exist for each, but positioned at the wrong graph node, bypassable via a self-attested field, or entirely un-cross-checked against real files/registries",
    ],
    "root_cause": (
        "A documented workflow can describe real gate mechanisms (they do exist, in the file/line "
        "sense) while still not matching actual runtime behavior, because: (1) a precise gate is wired "
        "to the wrong pipeline stage/graph edge (e.g. focused_wave_debug_window_gate was wired only to "
        "WAVE_ANALYSIS, reachable only pre-batch from VERIFY's PASS edge, never from the post-batch-"
        "failure FAILURE_RECOVERY path the doc actually describes); (2) a real check can be trivially "
        "satisfied by a free-text agent-attested field with no cross-check against ground truth (e.g. "
        "override_reason accepted any non-empty string, evidence_hash never independently recomputed "
        "from a real file, approved_for_modify was the same agent's own self-declared boolean with no "
        "ControlPlane cross-check); (3) a real post-hoc validation gate is mistaken in prose for a "
        "pre-condition gate because pipeline topology (main_graph.json edge order) wasn't checked."
    ),
    "fix": (
        "Closed 6 of 8 confirmed gaps via sequential (not parallel -- all touch shared dv_harness/"
        "gates.py and dv_harness/engine.py, parallel edits would conflict) implementer agents, each "
        "reading current file state fresh, adding real cross-checks against ground-truth files/"
        "registries (not more self-attested fields), and adding regression tests: "
        "(1) regression_submission_policy_gate now requires override_reason to link to a real "
        "prior-failure record (findings.json or JobState); focused_wave_debug_window_gate wired into "
        "STAGE_GATES['FAILURE_RECOVERY'] with a real deep_debug_required:false+reason escape hatch. "
        "(2) deep_rca_evidence_gate now independently recomputes sha256 of a real cited file when "
        "evidence_path is supplied, FAILing EVIDENCE_HASH_STALE_OR_FABRICATED on mismatch. "
        "(3) engine.py's PROMOTION_READINESS/SIGNOFF-style WAIT_USER hard-stop extended to RE_AUDIT "
        "specifically for DUT_BUG/high-risk fixes; fix_risk_approval_gate now cross-checks the real "
        ".dv-harness/control.json instead of trusting only the agent's own approved_for_modify field. "
        "(4) RTL write protection hardened three ways: settings.json Write() deny rules added "
        "alongside existing Edit() ones, a new Bash-level regex guard in block-destructive.ps1, and a "
        "new rtl_write_scope_guard_gate wired into STAGE_GATES['IMPLEMENT'] checking agent-attested "
        "touched_paths against a real project-configured rtl_protection.protected_paths list. "
        "(5) regression_selection_completeness_gate (STAGE_GATES['REGRESSION_SELECT'], the real "
        "pre-condition point before a full regression submits) now requires single-test reverify "
        "evidence when following a fix cycle; fix_regression_non_regression_gate cross-checks claimed "
        "pre/post-fix results against real .dv-harness/lsf/jobs/<job_id>.json JobState records when a "
        "job_id is supplied (bare-testcase-id resolution left honestly open -- no per-testcase-latest-"
        "result registry exists yet to resolve it without guessing). "
        "(6) engine.py gained _promote_verified_fix_knowledge(), auto-calling route_and_store() with "
        "kind='verified_fix' when RE_AUDIT's fix_effectiveness_gate AND fix_regression_non_regression_"
        "gate both PASS -- no more manual one-off persistence script needed for the common case."
    ),
    "verification": {
        "single_sim": "N/A (engine/gate-logic fix, not a simulation fix)",
        "regression": "6 new/updated test files (test_deep_rca_evidence_gate.py new, test_fix_risk_approval_gate.py new, test_engine_gates_and_routing.py +497 lines, test_inference_engine_wiring.py +158 lines) -- full local suite 1749 passed after all 6 fixes combined, 0 failures",
        "reaudit": "CONFIRMED: changes synced to and import-smoke-tested against the real /home/svcacct/AI/Agent deployment (STAGE_GATES['RE_AUDIT'] shows 11 gates including the hardened deep_rca_evidence_gate, STAGE_GATES['FAILURE_RECOVERY'] present)",
    },
    "confidence": "CONFIRMED",
    "note": (
        "2 of 8 audited gaps NOT yet closed (out of this session's scope, tracked here for a future "
        "session): (a) Knowledge Center auto-lookup BEFORE FAILURE_RECOVERY/RE_AUDIT concludes a fresh "
        "root cause -- KnowledgeCenterClient.search() still only reachable via manual CLI/GUI, never "
        "auto-invoked by the stage flow; (b) root_cause_evidence_gate's supporting_evidence/"
        "counter_evidence fields remain free-text with no hash-freshness check (deep_rca_evidence_gate "
        "got this fix, root_cause_evidence_gate's field shape is structurally different -- citation "
        "strings, not hash+path entries -- so the same mechanism doesn't directly transfer). "
        "GENERALIZABLE LESSON: when auditing whether a documented workflow is 'real,' checking that a "
        "gate script EXISTS is necessary but not sufficient -- also check (1) which STAGE_GATES entry "
        "wires it in, (2) which main_graph.json edges actually reach that stage, (3) whether the "
        "checked fields are cross-verified against a real file/registry or merely self-attested by the "
        "same agent making the claim being checked."
    ),
    "provenance": "dv-agent-harness-l5 session, 2026-09-02, DEBUG_WORKFLOW_GUIDE.md audit + gap closure",
}


def main() -> int:
    result = route_and_store(ROOT, RECORD)
    print(f"[{RECORD['title'][:60]}...] -> {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
