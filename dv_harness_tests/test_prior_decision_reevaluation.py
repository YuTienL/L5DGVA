"""dv_harness/prior_decision_reevaluation.py -- automatic reevaluation of PRIOR
capability-evolution decisions (Research-Capability Evolution master prompt
section 77).

Every test drives REAL stores on disk: a real `memory.MemoryStore`, a real
`memory_router.route_and_store()`, a real Blackboard-backed
`capability_evolution` candidate, and a real
`capability_evolution.repeated_unresolved_failure_patterns()` /
`cross_project_mining.mine_cross_project_patterns()`. Nothing is mocked.
The negative controls (a live candidate, an unchanged-evidence rejection, and
a resolved-not-grown pattern) are the properties this module is graded on:
absent NEW real evidence, it must flag nothing.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness import capability_evolution as ce
from dv_harness import cross_project_mining as cpm
from dv_harness import prior_decision_reevaluation as rde
from dv_harness.memory import MemoryStore
from dv_harness.memory_router import route_and_store
from dv_harness.memory_vault import build_failure_signature

SYMPTOM = "USB3 LFPS handshake never completes on port 0"
ROOT_CAUSE_HINT = "polling.exit timeout while RX detect stays low"


def _signature(**overrides):
    fields = dict(protocol="USB3", symptom=SYMPTOM, root_cause_hint=ROOT_CAUSE_HINT)
    fields.update(overrides)
    return build_failure_signature(**fields)


def _record_job_failure(root: Path, signature: dict, *, git_sha=None, job_id=None,
                        stage="RE_AUDIT", attempt=1) -> dict:
    record = {
        "kind": "job_failure",
        "scope": "debug",
        "title": f"{stage} attempt {attempt} did not close",
        "stage": stage,
        "attempt": attempt,
        "status": "PARTIAL",
        "blocking_reason": "GATE_FAIL: root_cause_evidence_gate",
        "failure_signature": signature,
        "protocol": signature.get("protocol"),
        "git_sha": git_sha,
    }
    if job_id is not None:
        record["job_id"] = job_id
    routed = route_and_store(root, record, cfg={})
    assert routed["destination"] == "JOB_MEMORY", routed
    return routed


def _record_verified_fix(root: Path, *, root_cause=ROOT_CAUSE_HINT, symptom=SYMPTOM) -> dict:
    record = {
        "kind": "verified_fix",
        "verified": True,
        "title": f"Verified fix: {root_cause}",
        "scope": "engineering",
        "symptoms": [symptom],
        "root_cause": root_cause,
        "fix": "rtl commit deadbeef",
        "evidence": ["sim.log:4412", "fsdb:polling.exit"],
        "reusable": True,
        "verification": {"targeted_reproducer_passed": True,
                         "broader_regression_passed": True,
                         "new_failures_introduced": False},
        "confidence": "HIGH",
        "protocol": "USB3",
    }
    routed = route_and_store(root, record, cfg={})
    assert routed["destination"] == "ENGINEERING_MEMORY", routed
    return routed


def _file_two_run_candidate(root: Path) -> dict:
    """A real DISCOVERED candidate backed by two independent job_failure runs,
    through the real capability_evolution auto-discovery path."""
    sig = _signature()
    _record_job_failure(root, sig, git_sha="commit-aaa")
    _record_job_failure(root, sig, job_id="LSF-10001")
    filed = ce.file_candidates_for_repeated_failures(root, cfg={})
    assert len(filed) == 1 and filed[0]["filed"] is True
    return ce.read_candidate(root, filed[0]["candidate_id"])


def _reject(root: Path, candidate: dict, reason="not a priority right now") -> dict:
    rejected = ce.transition(root, candidate, "REJECTED", by="a-real-human", reason=reason, cfg={})
    assert rejected["current_status"] == "REJECTED"
    return ce.read_candidate(root, rejected["candidate_id"])


@pytest.fixture
def root():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def workspace():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# prior_decision_status(): classification off real, already-recorded fields
# ---------------------------------------------------------------------------

def test_a_live_discovered_candidate_is_not_a_prior_decision(root):
    candidate = _file_two_run_candidate(root)
    status = rde.prior_decision_status(candidate)
    assert status["status"] == rde.NOT_A_PRIOR_DECISION


def test_a_rejected_candidate_is_classified_rejected_with_the_real_transition_time(root):
    candidate = _file_two_run_candidate(root)
    rejected = _reject(root, candidate)
    status = rde.prior_decision_status(rejected)
    assert status["status"] == "REJECTED"
    real_at = rejected["status_history"][-1]["at"]
    assert rejected["status_history"][-1]["to_status"] == "REJECTED"
    assert status["decided_at"] == real_at


def test_hold_is_classified_with_no_fabricated_timestamp(root):
    """final_decision has no producer anywhere in this codebase beyond
    build_candidate()'s PENDING default -- a human sets it directly. This must
    never invent a decided_at for it."""
    candidate = dict(_file_two_run_candidate(root))
    candidate["final_decision"] = "HOLD"
    status = rde.prior_decision_status(candidate)
    assert status["status"] == "HOLD"
    assert status["decided_at"] is None


def test_superseded_is_relayed_from_a_declaration_never_derived(root):
    candidate = dict(_file_two_run_candidate(root))
    candidate["superseded_by"] = "CEC-deadbeefcafe"
    status = rde.prior_decision_status(candidate)
    assert status["status"] == "SUPERSEDED"
    assert "CEC-deadbeefcafe" in status["basis"]


def test_no_declaration_never_guesses_superseded(root):
    """The negative half of the SUPERSEDED discipline: absence of a
    superseded_by field must never be read as SUPERSEDED."""
    candidate = _file_two_run_candidate(root)
    assert "superseded_by" not in candidate
    status = rde.prior_decision_status(candidate)
    assert status["status"] != "SUPERSEDED"


# ---------------------------------------------------------------------------
# detect_new_repeated_failure_evidence() / detect_reconsiderations(): the core
# evidence-truth property. Negative controls first.
# ---------------------------------------------------------------------------

def test_NEGATIVE_CONTROL_rejection_with_no_new_evidence_flags_nothing(root):
    """The property this module is graded on: a REJECTED decision with
    UNCHANGED evidence since the rejection must never be flagged."""
    candidate = _file_two_run_candidate(root)
    _reject(root, candidate)
    assert rde.detect_reconsiderations(root) == []


def test_a_new_independent_run_after_rejection_is_detected(root):
    sig = _signature()
    candidate = _file_two_run_candidate(root)
    rejected = _reject(root, candidate)

    third = _record_job_failure(root, sig, job_id="LSF-20002")

    flags = rde.detect_reconsiderations(root)
    assert len(flags) == 1
    flag = flags[0]
    assert flag["candidate_id"] == rejected["candidate_id"]
    assert flag["prior_decision_status"] == "REJECTED"
    rep = flag["new_evidence"]["repeated_failure"]
    assert rep is not None
    assert rep["new_memory_ids"] == [third["memory_id"]]
    assert flag["new_evidence"]["cross_project"] is None
    assert flag["evidence_reasons"] == ["NEW_REPEATED_FAILURE_EVIDENCE"]


def test_a_verified_fix_closing_the_pattern_is_not_misread_as_new_evidence(root):
    """Resolution makes the pattern DISAPPEAR from
    repeated_unresolved_failure_patterns(); this must not be mistaken for
    'evidence grew'."""
    candidate = _file_two_run_candidate(root)
    _reject(root, candidate)
    _record_verified_fix(root)
    assert ce.repeated_unresolved_failure_patterns(root) == []
    assert rde.detect_reconsiderations(root) == []


def test_a_live_not_yet_decided_candidate_is_never_flagged_even_with_new_evidence(root):
    """Scope discipline: only concluded decisions (REJECTED/HOLD/SUPERSEDED)
    are ever examined -- a candidate still DISCOVERED is a live proposal, not
    a prior decision to reconsider."""
    sig = _signature()
    _file_two_run_candidate(root)  # left DISCOVERED, never rejected
    _record_job_failure(root, sig, job_id="LSF-30003")
    assert rde.detect_reconsiderations(root) == []


def test_a_human_authored_candidate_with_no_trigger_source_is_never_matched_by_guesswork(root):
    """A candidate with no job_memory:failure_signature: trigger_source must
    never be matched against ANY repeated-failure pattern by inferring a
    signature from its hypothesis text."""
    candidate = dict(_file_two_run_candidate(root))
    candidate.pop("trigger_source", None)
    candidate["current_status"] = "REJECTED"
    assert rde.repeated_failure_signature_key(candidate) is None
    assert rde.detect_new_repeated_failure_evidence(root, candidate) is None


# ---------------------------------------------------------------------------
# Cross-project evidence (via cross_project_mining.py, caller-supplied)
# ---------------------------------------------------------------------------

def _second_project(workspace: Path, name: str) -> Path:
    proj = workspace / name
    proj.mkdir(parents=True, exist_ok=True)
    MemoryStore(proj)
    return proj


def test_new_cross_project_evidence_is_detected(workspace):
    project_a = _second_project(workspace, "project_a")
    project_b = _second_project(workspace, "project_b")

    candidate = _file_two_run_candidate(project_a)
    rejected = _reject(project_a, candidate)

    sig = _signature()
    b1 = _record_job_failure(project_b, sig, git_sha="b-commit-1")
    b2 = _record_job_failure(project_b, sig, job_id="LSF-B-2")

    report = cpm.mine_cross_project_patterns([
        {"project_id": "A", "root": str(project_a)},
        {"project_id": "B", "root": str(project_b)},
    ])
    assert report["status"] == cpm.STATUS_OK
    cross_patterns = report["cross_project_patterns"]
    assert len(cross_patterns) == 1

    flags = rde.detect_reconsiderations(
        project_a, cross_project_patterns=cross_patterns,
    )
    assert len(flags) == 1
    flag = flags[0]
    assert flag["candidate_id"] == rejected["candidate_id"]
    cross = flag["new_evidence"]["cross_project"]
    assert cross is not None
    assert set(cross["new_memory_ids"]) == {b1["memory_id"], b2["memory_id"]}
    assert cross["project_count"] == 2
    assert "NEW_CROSS_PROJECT_EVIDENCE" in flag["evidence_reasons"]


def test_no_cross_project_patterns_supplied_yields_no_cross_project_flag(root):
    """Absence of supplied cross-project data is answered honestly (None),
    never read as a claim that no cross-project evidence exists."""
    candidate = _file_two_run_candidate(root)
    _reject(root, candidate)
    assert rde.detect_reconsiderations(root, cross_project_patterns=None) == []
    assert rde.detect_reconsiderations(root, cross_project_patterns=[]) == []


# ---------------------------------------------------------------------------
# Filing: persists ONLY the flag, to WORKING_MEMORY, and never touches the
# candidate's own governance state.
# ---------------------------------------------------------------------------

def test_filing_persists_to_working_memory_and_is_idempotent(root):
    sig = _signature()
    candidate = _file_two_run_candidate(root)
    _reject(root, candidate)
    _record_job_failure(root, sig, job_id="LSF-40004")

    first = rde.file_reconsiderations(root, cfg={})
    assert len(first) == 1
    assert first[0]["filed"] is True
    assert first[0]["reason"] == "NEW_EVIDENCE"
    assert first[0]["persisted"]["memory"]["destination"] == "WORKING_MEMORY"

    stored = rde.existing_reconsideration_flags(root)
    assert len(stored) == 1
    assert stored[0]["kind"] == rde.RECONSIDERATION_FLAG_MEMORY_KIND

    # Re-running with the SAME evidence must not duplicate the record.
    second = rde.file_reconsiderations(root, cfg={})
    assert len(second) == 1
    assert second[0]["filed"] is False
    assert second[0]["reason"] == "ALREADY_FLAGGED_UNCHANGED"
    assert len(rde.existing_reconsideration_flags(root)) == 1


def test_filing_never_touches_the_flagged_candidates_own_state(root):
    sig = _signature()
    candidate = _file_two_run_candidate(root)
    rejected = _reject(root, candidate)
    _record_job_failure(root, sig, job_id="LSF-50005")

    before = ce.read_candidate(root, rejected["candidate_id"])
    rde.file_reconsiderations(root, cfg={})
    after = ce.read_candidate(root, rejected["candidate_id"])

    assert before == after
    assert after["current_status"] == "REJECTED"
    assert after["final_decision"] == "PENDING"


def test_growing_evidence_further_mints_a_different_flag_id(root):
    sig = _signature()
    candidate = _file_two_run_candidate(root)
    _reject(root, candidate)
    _record_job_failure(root, sig, job_id="LSF-60006")
    first_flags = rde.detect_reconsiderations(root)
    assert len(first_flags) == 1
    first_id = first_flags[0]["flag_id"]

    _record_job_failure(root, sig, job_id="LSF-70007")
    second_flags = rde.detect_reconsiderations(root)
    assert len(second_flags) == 1
    second_id = second_flags[0]["flag_id"]

    assert first_id != second_id


# ---------------------------------------------------------------------------
# mint_flag_id(): stable and content-derived, matching
# capability_evolution.mint_candidate_id()'s own discipline.
# ---------------------------------------------------------------------------

def test_mint_flag_id_is_stable_for_identical_inputs():
    rep = {"new_memory_ids": ["MEM-2", "MEM-1"]}
    a = rde.mint_flag_id("CEC-abc", rep, None)
    b = rde.mint_flag_id("CEC-abc", dict(rep), None)
    assert a == b
    assert a.startswith("RCF-")


def test_mint_flag_id_differs_for_different_evidence():
    a = rde.mint_flag_id("CEC-abc", {"new_memory_ids": ["MEM-1"]}, None)
    b = rde.mint_flag_id("CEC-abc", {"new_memory_ids": ["MEM-1", "MEM-2"]}, None)
    assert a != b


# ---------------------------------------------------------------------------
# CLI front door
# ---------------------------------------------------------------------------

def test_cli_detect_prints_json_and_exits_zero(root, capsys):
    sig = _signature()
    candidate = _file_two_run_candidate(root)
    _reject(root, candidate)
    _record_job_failure(root, sig, job_id="LSF-80008")

    exit_code = rde.main(["detect", "--root", str(root)])
    assert exit_code == 0
    out = json.loads(capsys.readouterr().out)
    assert isinstance(out, list) and len(out) == 1
    assert out[0]["prior_decision_status"] == "REJECTED"


def test_cli_file_persists_and_second_run_is_idempotent(root, capsys):
    sig = _signature()
    candidate = _file_two_run_candidate(root)
    _reject(root, candidate)
    _record_job_failure(root, sig, job_id="LSF-90009")

    assert rde.main(["file", "--root", str(root)]) == 0
    out1 = json.loads(capsys.readouterr().out)
    assert out1[0]["filed"] is True

    assert rde.main(["file", "--root", str(root)]) == 0
    out2 = json.loads(capsys.readouterr().out)
    assert out2[0]["filed"] is False
    assert out2[0]["reason"] == "ALREADY_FLAGGED_UNCHANGED"
