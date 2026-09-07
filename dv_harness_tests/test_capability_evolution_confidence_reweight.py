"""CONFIDENCE-CALIBRATION FEEDBACK LOOP: a re-weighted score_confidence()
formula-constants PROPOSAL, drafted from a real confidence_calibration.py
tier-ordering inversion, routed through capability_evolution.py's existing
DISCOVERED-candidate machinery for human approval -- never applied to
inference.py directly.

WHAT THIS TESTS. Not "the function returns a dict". The things that can
actually go wrong with this specific coupling are:

  1. **A proposal fabricated out of nothing.** A CALIBRATED report (no real
     inversion) must draft no candidate at all -- the negative control every
     positive case here is paired against.
  2. **A live change smuggled in somewhere.** Filing this candidate must never
     touch dv_harness/inference.py, must never advance past DISCOVERED on its
     own, and must never weaken the real ControlPlane human-approval boundary
     -- the exact same three walls capability_evolution.py's own repeated-
     failure coupling already holds, held here for this second trigger.
  3. **A confidence label nobody recomputed.** The candidate's own confidence
     must be exactly what inference.score_confidence() derives from its
     stored inputs, never a self-reported number.
  4. **Duplicate or lost evidence across cycles.** The candidate_id must be
     stable across a re-run with the same evidence and must accumulate real
     new evidence rather than forking a duplicate.

Everything here is driven against real stores on disk: a real MemoryStore
populated through the REAL MemoryGC.confirm()/retract() writers, a real
confidence_calibration.calibrate() report, a real Blackboard, and a real
ControlPlane. Nothing is mocked.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness import capability_evolution as ce
from dv_harness import confidence_calibration as cc
from dv_harness.memory import MemoryGC, MemoryStore

ROOT = Path(__file__).resolve().parents[1]
INFERENCE_PY = ROOT / "dv_harness" / "inference.py"


@pytest.fixture
def root():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def add_record(store, tier, *, title="finding"):
    return store.add("engineering", {"title": title, "protocol": "USB3",
                                     "root_cause": f"{title}-rc", "confidence": tier})


def populate(store, tier, *, verified=0, rejected=0):
    """`verified` records really confirmed, `rejected` records really
    retracted -- through the REAL MemoryGC writers, exactly like
    test_confidence_calibration.py's own helper."""
    gc = MemoryGC(store)
    for i in range(verified):
        rec = add_record(store, tier, title=f"{tier}-ok-{i}")
        assert gc.confirm(rec["memory_id"], evidence={"note": "independent re-derivation"})
    for i in range(rejected):
        rec = add_record(store, tier, title=f"{tier}-bad-{i}")
        assert gc.retract(rec["memory_id"], "overturned by current evidence",
                          evidence={"sim_log": "run/sim.log:1201"})


def _real_inversion_proposal(root):
    """HIGH holding up 30% against MEDIUM's 90% -- a real, calibrate()-produced
    INVERTED_TIER_ORDER finding, and the drafted proposal over it."""
    store = MemoryStore(root)
    populate(store, "HIGH", verified=3, rejected=7)
    populate(store, "MEDIUM", verified=9, rejected=1)
    report = cc.calibrate(root)
    assert report["status"] == cc.STATUS_MISCALIBRATED
    proposal = cc.draft_reweighted_confidence_proposal(report)
    assert proposal["status"] == cc.REWEIGHT_PROPOSAL_DRAFTED
    return proposal


# --- negative control: nothing to propose files nothing ----------------------

def test_a_calibrated_report_files_no_candidate(root):
    store = MemoryStore(root)
    populate(store, "HIGH", verified=9, rejected=1)
    populate(store, "MEDIUM", verified=5, rejected=5)
    report = cc.calibrate(root)
    assert report["status"] == cc.STATUS_CALIBRATED

    proposal = cc.draft_reweighted_confidence_proposal(report)
    assert proposal["status"] == cc.REWEIGHT_PROPOSAL_NO_INVERSION

    result = ce.file_confidence_reweight_candidate(root, proposal, cfg={})
    assert result["filed"] is False
    assert result["reason"] == cc.REWEIGHT_PROPOSAL_NO_INVERSION
    assert ce.read_candidates(root) == {}


def test_a_confirmed_only_inversion_files_no_candidate(root):
    store = MemoryStore(root)
    populate(store, "CONFIRMED", verified=2, rejected=8)
    populate(store, "HIGH", verified=9, rejected=1)
    report = cc.calibrate(root)
    proposal = cc.draft_reweighted_confidence_proposal(report)
    assert proposal["status"] == cc.REWEIGHT_PROPOSAL_NOT_ADDRESSABLE

    result = ce.file_confidence_reweight_candidate(root, proposal, cfg={})
    assert result["filed"] is False
    assert result["reason"] == cc.REWEIGHT_PROPOSAL_NOT_ADDRESSABLE
    assert ce.read_candidates(root) == {}


def test_build_confidence_reweight_candidate_refuses_a_non_drafted_proposal(root):
    for bad_status in (cc.REWEIGHT_PROPOSAL_NO_INVERSION, cc.REWEIGHT_PROPOSAL_NOT_ADDRESSABLE,
                       "SOMETHING_ELSE"):
        with pytest.raises(ValueError):
            ce.build_confidence_reweight_candidate(root, {"status": bad_status})


# --- the real, filed candidate -----------------------------------------------

def test_the_filed_candidate_is_real_persisted_state_at_DISCOVERED(root):
    proposal = _real_inversion_proposal(root)

    result = ce.file_confidence_reweight_candidate(root, proposal, cfg={})
    assert result["filed"] is True
    assert result["reason"] == "DISCOVERED"
    cid = result["candidate_id"]

    stored = ce.read_candidate(root, cid)
    assert stored is not None
    assert stored["current_status"] == "DISCOVERED"
    assert stored["promotion_status"] == "DISCOVERED"
    assert stored["trigger_type"] == "INTERNAL_AUDIT"
    assert stored["affected_capability"] == ce.CONFIDENCE_REWEIGHT_AFFECTED_CAPABILITY
    assert "high_threshold" in stored["evidence_refs"][0]
    assert stored["status_history"][0]["by"] == ce.CONFIDENCE_REWEIGHT_BY
    assert stored["status_history"][0]["from_status"] is None
    assert len(stored["status_history"]) == 1

    # The ONE Working Memory audit record, through the real router.
    audit = ce.candidate_audit_records(root, cid)
    assert len(audit) == 1
    assert audit[0]["current_status"] == "DISCOVERED"
    assert audit[0]["level"] == "working"


def test_the_filed_candidate_asserts_no_search_it_did_not_perform(root):
    """Same honesty rule the schema enforces for every other auto-filed
    candidate: no repository search was run, so overlap_status/recommendation
    are UNKNOWN, never a fabricated MISSING/ENHANCE."""
    proposal = _real_inversion_proposal(root)
    cid = ce.file_confidence_reweight_candidate(root, proposal, cfg={})["candidate_id"]
    stored = ce.read_candidate(root, cid)

    assert stored["overlap_status"] == "UNKNOWN"
    assert stored["recommendation"] == "UNKNOWN"
    assert stored["exact_gap"] == ""
    for slot in ce.L5_SEARCH_SLOTS:
        assert stored[slot]["matches"] == []
        assert stored[slot]["search_conclusive"] is False
        assert "NOT SEARCHED" in stored[slot]["search_basis"]


def test_proposed_action_carries_the_exact_proposal_numbers(root):
    proposal = _real_inversion_proposal(root)
    cid = ce.file_confidence_reweight_candidate(root, proposal, cfg={})["candidate_id"]
    stored = ce.read_candidate(root, cid)

    for value in (proposal["current_constants"], proposal["proposed_constants"]):
        assert str(value["high_threshold"]) in stored["proposed_action"]
    assert "never applied" in stored["proposed_action"].lower()
    assert "run_controlled_experiment" in stored["proposed_action"]
    assert "run_shadow_replication" in stored["proposed_action"]
    assert "HUMAN_APPROVED" in stored["proposed_action"]
    assert stored["experiment_required"] is True
    assert stored["experiment_plan"]
    assert stored["benchmark_plan"]


def test_filing_never_touches_inference_py(root):
    """The whole point of routing through DATA and a human-approved
    controlled experiment: not one byte of the real, live inference.py moves
    just because a proposal was drafted and filed."""
    before = INFERENCE_PY.read_bytes()
    proposal = _real_inversion_proposal(root)
    ce.file_confidence_reweight_candidate(root, proposal, cfg={})
    assert INFERENCE_PY.read_bytes() == before


def test_confidence_is_recomputed_not_self_reported(root):
    proposal = _real_inversion_proposal(root)
    cid = ce.file_confidence_reweight_candidate(root, proposal, cfg={})["candidate_id"]
    stored = ce.read_candidate(root, cid)
    ce.assert_confidence_recomputed(stored)   # must not raise
    assert stored["evidence_strength"]["scale"] == 2


def test_the_candidate_id_is_stable_and_accumulates_new_evidence(root):
    store = MemoryStore(root)
    populate(store, "HIGH", verified=3, rejected=7)
    populate(store, "MEDIUM", verified=9, rejected=1)
    report = cc.calibrate(root)
    proposal = cc.draft_reweighted_confidence_proposal(report)
    first = ce.file_confidence_reweight_candidate(root, proposal, cfg={})
    assert first["filed"] is True and first["reason"] == "DISCOVERED"

    # A second, later cycle's own re-run over the SAME real evidence.
    report2 = cc.calibrate(root)
    proposal2 = cc.draft_reweighted_confidence_proposal(report2)
    second = ce.file_confidence_reweight_candidate(root, proposal2, cfg={})
    assert second["candidate_id"] == first["candidate_id"]
    assert second["filed"] is False
    assert second["reason"] == "ALREADY_ON_FILE_UNCHANGED"
    assert len(ce.candidate_audit_records(root, first["candidate_id"])) == 1

    # NEW real evidence -- a further real inversion pair -- refreshes it.
    populate(store, "LOW", verified=10, rejected=0)   # HIGH now also < LOW
    report3 = cc.calibrate(root)
    proposal3 = cc.draft_reweighted_confidence_proposal(report3)
    third = ce.file_confidence_reweight_candidate(root, proposal3, cfg={})
    assert third["candidate_id"] == first["candidate_id"]
    assert third["filed"] is True
    assert third["reason"] == "NEW_EVIDENCE"
    stored = ce.read_candidate(root, first["candidate_id"])
    assert stored["current_status"] == "DISCOVERED"
    assert len(stored["status_history"]) == 1   # no state changed, no entry invented


# --- the boundary: DISCOVERED and no further, ever ---------------------------

def test_a_candidate_a_human_moved_on_is_never_dragged_back(root):
    proposal = _real_inversion_proposal(root)
    cid = ce.file_confidence_reweight_candidate(root, proposal, cfg={})["candidate_id"]

    moved = ce.transition(root, ce.read_candidate(root, cid), "EVIDENCE_GATHERING",
                          by="a-real-human", reason="starting the six searches", cfg={})
    assert moved["current_status"] == "EVIDENCE_GATHERING"

    again = ce.file_confidence_reweight_candidate(root, proposal, cfg={})
    assert again["filed"] is False
    assert again["reason"] == "ALREADY_BEYOND_DISCOVERED"
    assert ce.read_candidate(root, cid)["current_status"] == "EVIDENCE_GATHERING"


def test_an_auto_filed_candidate_cannot_be_advanced_to_PROPOSED(root):
    """The wall is STRUCTURAL: an UNKNOWN overlap_status is pinned by the
    candidate schema's own allOf to DISCOVERED/EVIDENCE_GATHERING/REJECTED."""
    proposal = _real_inversion_proposal(root)
    cid = ce.file_confidence_reweight_candidate(root, proposal, cfg={})["candidate_id"]

    gathering = ce.transition(root, ce.read_candidate(root, cid), "EVIDENCE_GATHERING",
                              by="a-real-human", reason="searching", cfg={})
    with pytest.raises(ce.CapabilityEvolutionCandidateValidationError):
        ce.transition(root, gathering, "PROPOSED", by="a-real-human",
                      reason="skipping the searches", cfg={})


def test_skipping_governance_states_is_still_refused(root):
    proposal = _real_inversion_proposal(root)
    cid = ce.file_confidence_reweight_candidate(root, proposal, cfg={})["candidate_id"]
    stored = ce.read_candidate(root, cid)

    for target in ("PROPOSED", "EXPERIMENT_APPROVED", "PROMOTION_CANDIDATE",
                   "HUMAN_APPROVED", "PRODUCTION"):
        with pytest.raises(ce.IllegalPromotionTransitionError):
            ce.transition(root, stored, target, by="x", reason="y", cfg={})


def test_the_human_approval_gate_is_untouched(root):
    """Nothing about this coupling weakens the real LEVEL B -> LEVEL C
    boundary: a production write on this candidate's behalf still needs a
    real ControlPlane approval on disk, and its own state still refuses it."""
    proposal = _real_inversion_proposal(root)
    cid = ce.file_confidence_reweight_candidate(root, proposal, cfg={})["candidate_id"]
    stored = ce.read_candidate(root, cid)

    assert ce.human_approval_status(root)["approved"] is False
    with pytest.raises(ce.HumanApprovalRequiredError):
        ce.assert_human_approval(root, stored)
    with pytest.raises(ce.ProductionWriteNotAuthorizedError):
        ce.assert_no_production_write_authorized(root, stored)
    assert stored["approval_level"] == "HUMAN_APPROVAL_REQUIRED"
    assert stored["final_decision"] == "PENDING"


def test_the_auto_filed_candidate_never_reaches_a_tier_above_working_memory(root):
    proposal = _real_inversion_proposal(root)
    cid = ce.file_confidence_reweight_candidate(root, proposal, cfg={})["candidate_id"]

    store = MemoryStore(root)
    records = store.find(kind=ce.CANDIDATE_MEMORY_KIND, candidate_id=cid)
    assert records and all(r["level"] == "working" for r in records)
    assert store.find("engineering", kind=ce.CANDIDATE_MEMORY_KIND) == []
    assert store.find("project", kind=ce.CANDIDATE_MEMORY_KIND) == []


def test_the_module_still_holds_its_no_verification_authority_guarantee():
    ce.assert_no_verification_verdict_vocabulary()


# --- the real end-to-end pipeline, both modules, nothing mocked --------------

def test_end_to_end_from_real_memory_records_to_a_filed_candidate(root):
    """The whole coupling, driven the way a real caller would: real
    MemoryGC.confirm()/retract() writes, a real calibrate(), a real
    draft_reweighted_confidence_proposal(), a real file_confidence_reweight_candidate()."""
    inference_before = INFERENCE_PY.read_bytes()

    store = MemoryStore(root)
    populate(store, "HIGH", verified=3, rejected=7)     # 30%
    populate(store, "MEDIUM", verified=9, rejected=1)   # 90%

    report = cc.calibrate(root)
    proposal = cc.draft_reweighted_confidence_proposal(report)
    result = ce.file_confidence_reweight_candidate(root, proposal, cfg={})

    assert result["filed"] is True
    stored = ce.read_candidate(root, result["candidate_id"])
    assert stored["current_status"] == "DISCOVERED"
    assert stored["trigger_type"] == "INTERNAL_AUDIT"
    assert "HIGH" in stored["hypothesis"] and "MEDIUM" in stored["hypothesis"]
    assert stored["proposed_action"].count(str(cc.SCORE_CONFIDENCE_CONSTANTS["high_threshold"]
                                               + cc.SCORE_CONFIDENCE_CONSTANTS["source_weight"])) >= 1

    # Never a live code change anywhere along the real chain, end to end.
    assert INFERENCE_PY.read_bytes() == inference_before
