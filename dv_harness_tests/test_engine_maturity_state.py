"""L5DGVA V14 section 340 (`Universal Engine Maturity State`): tests for
`dv_harness/engine_maturity_state.py`.

MIGRATED (M5 Capability Pool Closure, Batch 2, from Parent) verbatim -- confirmed
none of these tests use any of the 3 memory-promotion signals dropped from
eight_engine_runtime_proof_matrix.py's adaptation (only ROOT_CAUSE_CONFIDENCE_SCORED/
LOOP_ACTION_SELECTED/BLACKBOARD_TOPIC_REFRESH/EXPERIENCE_KNOWLEDGE_PROMOTED/LOOP_BLOCKED
fixtures are used, all real in canonical), so no adaptation was needed.

WHAT THESE TESTS ARE FOR. This module is a pure mapping from
`eight_engine_runtime_proof_matrix.build_matrix()`'s real rows onto section
340's 8-state ladder. The things worth proving:

  1. An engine with NO events.jsonl producer at all (NO_RUNTIME_SIGNAL_SOURCE)
     caps at WIRED with blocked_kind NOT_MEASURABLE -- a structural gap, not a
     per-run fact.
  2. An engine WITH a real producer that stayed silent this window
     (NOT_PROVEN) also caps at WIRED, but with blocked_kind NOT_YET_OBSERVED
     -- a different, disclosed reason from case 1, never collapsed together.
  3. An engine with a real matching event (PROVEN) advances to
     INVOKED_WHEN_APPLICABLE, and never further -- the four upper states are
     always NOT_MEASURABLE, for every engine, because
     eight_engine_runtime_proof_matrix.py's own ArtifactIds/ConsumerIds/
     OutcomeVerified/RegressionIds are NOT_AVAILABLE on every row.
  4. EightEngineMaturityModel_PASS is False against any real evidence this
     repo can produce today (no engine can reach REGRESSION_PROTECTED), and
     this module does not fabricate a way around that.
  5. run_id scoping matches eight_engine_runtime_proof_matrix.py's own
     semantics (it is the only thing this module forwards to that reader).
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness import engine_maturity_state as ems
from dv_harness import eight_engine_runtime_proof_matrix as eerpm
from dv_harness.storage import StateStore


@pytest.fixture()
def project_root():
    d = Path(tempfile.mkdtemp(prefix="engine_maturity_state_"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _store(root: Path) -> StateStore:
    return StateStore(root)


def test_all_eight_engines_present_no_more_no_fewer(project_root):
    report = ems.derive_maturity_state(project_root)
    assert set(report["rows"].keys()) == {r.engine_id for r in eerpm.ENGINE_RULES}
    assert len(report["rows"]) == 8


def test_ladder_matches_section_340_verbatim_order():
    assert ems.MATURITY_STATE_LADDER == (
        "DEFINED", "IMPLEMENTED", "WIRED", "INVOKED_WHEN_APPLICABLE",
        "ARTIFACT_PRODUCED", "ARTIFACT_CONSUMED", "OUTCOME_VERIFIED",
        "REGRESSION_PROTECTED",
    )
    assert ems.FINAL_STATE == "REGRESSION_PROTECTED"


def test_no_runtime_signal_source_engine_caps_at_wired_structurally(project_root):
    """Multi-Agent Orchestrator has no events.jsonl producer at all -- must
    cap at WIRED with blocked_kind NOT_MEASURABLE, never a fabricated further
    state and never conflated with a merely-silent-this-window engine."""
    report = ems.derive_maturity_state(project_root)
    row = report["rows"]["multi_agent_orchestrator"]
    assert row["ReachedState"] == "WIRED"
    assert row["BlockedKind"] == "NOT_MEASURABLE"
    assert row["BlockedReason"]  # real, non-empty, disclosed
    assert row["RowVerdict"] == "PARTIAL"
    assert row["ProofMatrixVerdict"] == eerpm.NO_RUNTIME_SIGNAL_SOURCE


def test_not_proven_engine_caps_at_wired_as_not_yet_observed(project_root):
    """Autonomous Inference Engine HAS a real producer (ROOT_CAUSE_CONFIDENCE_
    SCORED) but nothing fired in this empty log -- caps at WIRED too, but for
    a different, disclosed reason (NOT_YET_OBSERVED, not NOT_MEASURABLE)."""
    report = ems.derive_maturity_state(project_root)
    row = report["rows"]["autonomous_inference_engine"]
    assert row["ReachedState"] == "WIRED"
    assert row["BlockedKind"] == "NOT_YET_OBSERVED"
    assert "scanned window" in row["BlockedReason"]
    assert row["ProofMatrixVerdict"] == eerpm.NOT_PROVEN


def test_proven_engine_advances_to_invoked_when_applicable_and_no_further(project_root):
    store = _store(project_root)
    store.event({
        "ts": "2026-09-16T00:00:00Z", "stage": "RE_AUDIT",
        "event": "ROOT_CAUSE_CONFIDENCE_SCORED",
        "recomputed_confidence": {"level": "HIGH", "score": 5},
        "agent_reported_confidence": "HIGH",
        "concurrent_agent_evidence_count": 2,
        "gap": [], "next_best_action": [], "promotion": {"promoted": True},
    })
    report = ems.derive_maturity_state(project_root)
    row = report["rows"]["autonomous_inference_engine"]
    assert row["ReachedState"] == "INVOKED_WHEN_APPLICABLE"
    assert row["BlockedKind"] == ""
    assert row["RowVerdict"] == "PARTIAL"  # not PASS -- PASS requires REGRESSION_PROTECTED
    assert row["ProofMatrixVerdict"] == eerpm.PROVEN
    # Never advances past INVOKED_WHEN_APPLICABLE, no matter what fired.
    assert row["UpperStatesStatus"] == ems.NOT_MEASURABLE


def test_eight_engine_maturity_model_pass_is_false_against_any_real_evidence(project_root):
    """No engine can reach REGRESSION_PROTECTED with today's instrumentation
    -- proving even the single most favorable real event fixture for every
    signal-bearing engine still yields EightEngineMaturityModel_PASS = False."""
    store = _store(project_root)
    store.event({"ts": "t", "stage": "RE_AUDIT", "event": "ROOT_CAUSE_CONFIDENCE_SCORED"})
    store.event({"ts": "t", "stage": "X", "event": "LOOP_ACTION_SELECTED", "route": "r"})
    store.event({"ts": "t", "stage": "COVERAGE", "event": "BLACKBOARD_TOPIC_REFRESH"})
    store.event({"ts": "t", "stage": "DEBUG", "event": "EXPERIENCE_KNOWLEDGE_PROMOTED",
                 "promotion": {"destination": "ENGINEERING_MEMORY"}})
    store.event({"ts": "t", "stage": "SIGNOFF", "event": "LOOP_BLOCKED",
                 "reason": "SIGNOFF_GATE_REFUSED"})
    report = ems.derive_maturity_state(project_root)
    assert report["EightEngineMaturityModel_PASS"] is False
    for row in report["rows"].values():
        assert row["ReachedState"] != "REGRESSION_PROTECTED"
        assert row["RowVerdict"] != "PASS"


def test_run_id_scoping_matches_proof_matrix_semantics(project_root):
    store = _store(project_root)
    store.event({"ts": "t1", "stage": "RE_AUDIT", "event": "ROOT_CAUSE_CONFIDENCE_SCORED",
                 "run_id": "loop:A"})
    report_a = ems.derive_maturity_state(project_root, run_id="loop:A")
    assert report_a["rows"]["autonomous_inference_engine"]["ReachedState"] == \
        "INVOKED_WHEN_APPLICABLE"

    report_b = ems.derive_maturity_state(project_root, run_id="loop:B")
    assert report_b["rows"]["autonomous_inference_engine"]["ReachedState"] == "WIRED"


def test_no_row_ever_reaches_fail_against_real_engine_rules(project_root):
    """All 8 real engines are Defined/Implemented/Wired True per
    eight_engine_runtime_proof_matrix.py's own cited evidence -- FAIL is
    declared in this module but never actually observed against this repo."""
    report = ems.derive_maturity_state(project_root)
    for row in report["rows"].values():
        assert row["RowVerdict"] in ("PARTIAL", "PASS")
        assert row["RowVerdict"] != "FAIL"


def test_execute_verb_show_and_state(project_root):
    code, text = ems.execute_verb(project_root, "show")
    assert code == 2  # EightEngineMaturityModel_PASS is False against an empty log
    assert "EightEngineMaturityModel_PASS = False" in text
    assert "Autonomous Inference Engine" in text

    code2, payload = ems.execute_verb(project_root, "state")
    assert payload["EightEngineMaturityModel_PASS"] is False
    assert len(payload["rows"]) == 8
    assert payload["upper_states_blocked_reason"]

    code3, payload3 = ems.execute_verb(project_root, "bogus")
    assert code3 == 1
    assert payload3["error"] == "UNKNOWN_VERB"


def test_authorizes_nothing(project_root):
    report = ems.derive_maturity_state(project_root)
    assert "nothing" in report["authorizes"].lower()
