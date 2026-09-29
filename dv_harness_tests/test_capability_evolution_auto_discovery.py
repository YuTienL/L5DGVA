"""CROSS-LOOP COUPLING: the Verification Closure Loop auto-filing a
CapabilityEvolutionCandidate at DISCOVERED (2026-09-05).

The three loops -- verification closure (engine.run_stage()'s gates), project
learning (memory_router's tier promotions) and capability evolution
(capability_evolution.py's 11-state machine) -- were each individually real and
firing, and the EDGE between the first and the third did not exist:
`router.resolve_intent()` has no caller in engine.py, so capability_evolution.py
was reachable only by a human typing `dv-harness research <doc>`, and the same
real failure could recur across independent runs forever without ever raising a
question about the harness's own capability.

These tests hold that edge to its real behaviour, and -- at least as important
-- hold the boundary it must never cross. Everything is driven against real
stores on disk: a real MemoryStore, a real memory_router.route_and_store(), a
real Blackboard, a real ControlPlane, and (for the end-to-end half) a real
DVHarness.run_stage() over the real shipped main_graph.json. Nothing is mocked
except the agent adapter, which is the only thing that would otherwise dispatch
a subprocess.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness import capability_evolution as ce
from dv_harness.evidence_db import signature_key
from dv_harness.memory import MemoryStore
from dv_harness.memory_router import route_and_store
from dv_harness.memory_vault import build_failure_signature

ROOT = Path(__file__).resolve().parents[1]
REAL_GRAPH = ROOT / ".dv-harness" / "graph" / "main_graph.json"

SYMPTOM = "USB3 LFPS handshake never completes on port 0"
ROOT_CAUSE_HINT = "polling.exit timeout while RX detect stays low"


def _signature(**overrides):
    fields = dict(protocol="USB3", symptom=SYMPTOM, root_cause_hint=ROOT_CAUSE_HINT)
    fields.update(overrides)
    return build_failure_signature(**fields)


def _record_job_failure(root: Path, signature: dict, *, git_sha=None, job_id=None,
                        stage="RE_AUDIT", attempt=1) -> dict:
    """One real Job Memory record, written through the REAL router with the
    exact field set engine._record_debug_attempt_job_memory() writes."""
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
    """One real Engineering Memory verified_fix record, with the exact field
    shape engine._promote_verified_fix_knowledge() writes on a gate-verified
    RE_AUDIT close."""
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


@pytest.fixture
def root():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- detection: what counts as a repeated UNRESOLVED failure -----------------

def test_one_run_is_not_a_pattern(root):
    """Section 64's own warning, one level up: a single occurrence is one run's
    circumstances. It must never raise a capability proposal."""
    _record_job_failure(root, _signature(), git_sha="commit-aaa")
    assert ce.repeated_unresolved_failure_patterns(root) == []
    assert ce.file_candidates_for_repeated_failures(root, cfg={}) == []
    assert ce.read_candidates(root) == {}


def test_the_same_run_reported_twice_is_still_one_run(root):
    """Two failed ATTEMPTS of one stage against one commit are one observation,
    not two independent confirmations -- the same discipline
    memory_router's Engineering-tier confirmation counting applies."""
    sig = _signature()
    _record_job_failure(root, sig, git_sha="commit-aaa", stage="RE_AUDIT", attempt=1)
    _record_job_failure(root, sig, git_sha="commit-aaa", stage="RE_AUDIT", attempt=2)
    _record_job_failure(root, sig, git_sha="commit-aaa", stage="FAILURE_RECOVERY", attempt=1)

    assert ce.repeated_unresolved_failure_patterns(root) == []
    assert ce.read_candidates(root) == {}


def test_records_with_no_run_identity_never_manufacture_independence(root):
    """A job_failure carrying neither job_id nor git_sha cannot be told apart
    from another one. Counting each as its own run is exactly how a single bad
    session would manufacture its own capability proposal."""
    sig = _signature()
    _record_job_failure(root, sig, attempt=1)
    _record_job_failure(root, sig, attempt=2)
    assert ce.repeated_unresolved_failure_patterns(root) == []


def test_two_independent_runs_sharing_one_signature_are_a_pattern(root):
    sig = _signature()
    a = _record_job_failure(root, sig, git_sha="commit-aaa")
    b = _record_job_failure(root, sig, job_id="LSF-99123")

    patterns = ce.repeated_unresolved_failure_patterns(root)
    assert len(patterns) == 1
    pattern = patterns[0]
    assert pattern["signature_key"] == signature_key(sig)
    assert pattern["independent_run_count"] == 2
    assert pattern["run_identities"] == ["git_sha:commit-aaa", "job_id:LSF-99123"]
    assert pattern["memory_ids"] == sorted([a["memory_id"], b["memory_id"]])
    assert pattern["resolved_by_verified_fix"] == []


def test_two_different_signatures_are_two_separate_patterns(root):
    """Grouping is evidence_db.signature_key() -- the SAME stable hash the
    evidence store already accumulates occurrence_count on, not a second
    definition of 'the same failure'."""
    first, second = _signature(), _signature(symptom="APB write times out")
    for sha in ("commit-aaa", "commit-bbb"):
        _record_job_failure(root, first, git_sha=sha)
        _record_job_failure(root, second, git_sha=sha)

    patterns = ce.repeated_unresolved_failure_patterns(root)
    assert len(patterns) == 2
    assert {p["signature_key"] for p in patterns} == {signature_key(first), signature_key(second)}


def test_a_gate_verified_fix_closes_the_pattern(root):
    """The UNRESOLVED half. A verified_fix record naming the signature's own
    root cause means the harness DID close this -- there is no missing
    capability to propose."""
    sig = _signature()
    _record_job_failure(root, sig, git_sha="commit-aaa")
    _record_job_failure(root, sig, git_sha="commit-bbb")
    assert len(ce.repeated_unresolved_failure_patterns(root)) == 1

    _record_verified_fix(root)
    assert ce.repeated_unresolved_failure_patterns(root) == []
    assert ce.file_candidates_for_repeated_failures(root, cfg={}) == []


def test_a_verified_fix_for_a_DIFFERENT_failure_does_not_close_this_one(root):
    """Matching is exact equality on the normalized claim text, never a
    substring or a score -- a fuzzy join would silently suppress real
    candidates, which is the more expensive error of the two."""
    sig = _signature()
    _record_job_failure(root, sig, git_sha="commit-aaa")
    _record_job_failure(root, sig, git_sha="commit-bbb")
    _record_verified_fix(root, root_cause="unrelated AXI ordering bug",
                         symptom="AXI write response out of order")
    assert len(ce.repeated_unresolved_failure_patterns(root)) == 1


def test_min_occurrences_below_two_is_refused(root):
    with pytest.raises(ValueError, match="at least 2"):
        ce.repeated_unresolved_failure_patterns(root, min_occurrences=1)


# --- filing: real state, at DISCOVERED, through the existing machinery -------

def test_the_filed_candidate_is_real_persisted_state_at_DISCOVERED(root):
    sig = _signature()
    a = _record_job_failure(root, sig, git_sha="commit-aaa")
    b = _record_job_failure(root, sig, git_sha="commit-bbb")

    results = ce.file_candidates_for_repeated_failures(root, cfg={})
    assert len(results) == 1 and results[0]["filed"] is True
    cid = results[0]["candidate_id"]

    # The ONE Blackboard topic every other candidate uses -- not a parallel store.
    stored = ce.read_candidate(root, cid)
    assert stored is not None
    assert stored["current_status"] == "DISCOVERED"
    assert stored["promotion_status"] == "DISCOVERED"
    assert stored["trigger_type"] == "FAILURE_PATTERN"
    assert stored["trigger_source"] == f"job_memory:failure_signature:{signature_key(sig)}"
    assert stored["evidence_refs"] == sorted([a["memory_id"], b["memory_id"]])
    assert stored["status_history"][0]["by"] == ce.AUTO_DISCOVERY_BY
    assert stored["status_history"][0]["from_status"] is None
    assert len(stored["status_history"]) == 1

    # ... and the Working Memory audit record, through the real router.
    audit = ce.candidate_audit_records(root, cid)
    assert len(audit) == 1
    assert audit[0]["current_status"] == "DISCOVERED"
    assert audit[0]["level"] == "working"

    # Every memory_id it cites really resolves -- evidence_refs_verified means
    # something.
    store = MemoryStore(root)
    for memory_id in stored["evidence_refs"]:
        assert store.get(memory_id) is not None


def test_the_filed_candidate_asserts_no_search_it_did_not_perform(root):
    """The honesty rule the schema exists to enforce: no repository search was
    run, so all six slots are search_conclusive FALSE, overlap_status is
    UNKNOWN (never a fabricated MISSING, which is what licenses an ADD) and the
    derived recommendation is UNKNOWN."""
    sig = _signature()
    _record_job_failure(root, sig, git_sha="commit-aaa")
    _record_job_failure(root, sig, git_sha="commit-bbb")
    cid = ce.file_candidates_for_repeated_failures(root, cfg={})[0]["candidate_id"]
    stored = ce.read_candidate(root, cid)

    assert stored["overlap_status"] == "UNKNOWN"
    assert stored["recommendation"] == "UNKNOWN"
    assert stored["exact_gap"] == ""
    assert stored["enhance_insufficient_reason"] == ""
    for slot in ce.L5_SEARCH_SLOTS:
        assert stored[slot]["matches"] == []
        assert stored[slot]["search_conclusive"] is False
        assert "NOT SEARCHED" in stored[slot]["search_basis"]
    # The basis names the real next action for that slot's own question, quoted
    # out of the existing RESEARCH_GAP_ACTION_CATALOG rather than reinvented.
    assert "ROSTER.md" in stored["existing_agent"]["search_basis"]
    assert "route_memory()" in stored["existing_memory"]["search_basis"]


def test_confidence_is_recomputed_from_the_real_independent_run_count(root):
    """Not a self-reported label: the stored confidence must be exactly what
    inference.score_confidence() produces from the stored inputs, and the
    independent-sources input is the RUN count, never the record count."""
    sig = _signature()
    _record_job_failure(root, sig, git_sha="commit-aaa", attempt=1)
    _record_job_failure(root, sig, git_sha="commit-aaa", attempt=2)  # same run
    _record_job_failure(root, sig, git_sha="commit-bbb")

    cid = ce.file_candidates_for_repeated_failures(root, cfg={})[0]["candidate_id"]
    stored = ce.read_candidate(root, cid)

    assert stored["confidence"]["inputs"]["independent_sources_count"] == 2
    assert len(stored["evidence_refs"]) == 3
    ce.assert_confidence_recomputed(stored)
    assert stored["evidence_strength"]["scale"] == 2


def test_the_candidate_id_is_stable_across_cycles_and_accumulates_evidence(root):
    """Content-derived identity is what makes a recurrence in a LATER cycle land
    on the SAME record instead of forking a duplicate."""
    sig = _signature()
    _record_job_failure(root, sig, git_sha="commit-aaa")
    _record_job_failure(root, sig, git_sha="commit-bbb")
    first = ce.file_candidates_for_repeated_failures(root, cfg={})[0]
    assert first["reason"] == "DISCOVERED"

    _record_job_failure(root, sig, git_sha="commit-ccc")
    second = ce.file_candidates_for_repeated_failures(root, cfg={})[0]

    assert second["candidate_id"] == first["candidate_id"]
    assert second["filed"] is True and second["reason"] == "NEW_EVIDENCE"
    assert len(ce.read_candidates(root)) == 1
    stored = ce.read_candidate(root, first["candidate_id"])
    assert len(stored["evidence_refs"]) == 3
    assert stored["current_status"] == "DISCOVERED"
    # No state changed, so no transition entry was invented.
    assert len(stored["status_history"]) == 1


def test_re_filing_unchanged_evidence_writes_nothing(root):
    """Otherwise every failed stage attempt would append another Working Memory
    audit record for no new information."""
    sig = _signature()
    _record_job_failure(root, sig, git_sha="commit-aaa")
    _record_job_failure(root, sig, git_sha="commit-bbb")
    cid = ce.file_candidates_for_repeated_failures(root, cfg={})[0]["candidate_id"]

    again = ce.file_candidates_for_repeated_failures(root, cfg={})
    assert again[0]["filed"] is False
    assert again[0]["reason"] == "ALREADY_ON_FILE_UNCHANGED"
    assert len(ce.candidate_audit_records(root, cid)) == 1


# --- the boundary: DISCOVERED and no further, ever ---------------------------

def test_a_candidate_a_human_moved_on_is_never_dragged_back(root):
    """This is the branch that makes 'auto-file at DISCOVERED only' true across
    cycles rather than only on the first one."""
    sig = _signature()
    _record_job_failure(root, sig, git_sha="commit-aaa")
    _record_job_failure(root, sig, git_sha="commit-bbb")
    cid = ce.file_candidates_for_repeated_failures(root, cfg={})[0]["candidate_id"]

    moved = ce.transition(root, ce.read_candidate(root, cid), "EVIDENCE_GATHERING",
                          by="a-real-human", reason="starting the six searches", cfg={})
    assert moved["current_status"] == "EVIDENCE_GATHERING"

    _record_job_failure(root, sig, git_sha="commit-ccc")
    result = ce.file_candidates_for_repeated_failures(root, cfg={})[0]
    assert result["filed"] is False
    assert result["reason"] == "ALREADY_BEYOND_DISCOVERED"
    assert ce.read_candidate(root, cid)["current_status"] == "EVIDENCE_GATHERING"
    assert len(ce.read_candidate(root, cid)["status_history"]) == 2


def test_an_auto_filed_candidate_cannot_be_advanced_to_PROPOSED(root):
    """The wall is STRUCTURAL, not a policy this code is trusted to respect: an
    UNKNOWN overlap_status is pinned by the candidate schema's own allOf to
    DISCOVERED/EVIDENCE_GATHERING/REJECTED. Reaching PROPOSED requires six
    conclusive searches only a real research-architect pass can produce."""
    sig = _signature()
    _record_job_failure(root, sig, git_sha="commit-aaa")
    _record_job_failure(root, sig, git_sha="commit-bbb")
    cid = ce.file_candidates_for_repeated_failures(root, cfg={})[0]["candidate_id"]

    gathering = ce.transition(root, ce.read_candidate(root, cid), "EVIDENCE_GATHERING",
                              by="a-real-human", reason="searching", cfg={})
    with pytest.raises(ce.CapabilityEvolutionCandidateValidationError):
        ce.transition(root, gathering, "PROPOSED", by="a-real-human",
                      reason="skipping the searches", cfg={})
    assert ce.read_candidate(root, cid)["current_status"] == "EVIDENCE_GATHERING"


def test_skipping_governance_states_is_still_refused(root):
    sig = _signature()
    _record_job_failure(root, sig, git_sha="commit-aaa")
    _record_job_failure(root, sig, git_sha="commit-bbb")
    cid = ce.file_candidates_for_repeated_failures(root, cfg={})[0]["candidate_id"]
    stored = ce.read_candidate(root, cid)

    for target in ("PROPOSED", "EXPERIMENT_APPROVED", "PROMOTION_CANDIDATE",
                   "HUMAN_APPROVED", "PRODUCTION"):
        with pytest.raises(ce.IllegalPromotionTransitionError):
            ce.transition(root, stored, target, by="x", reason="y", cfg={})


def test_the_human_approval_gate_is_untouched_by_an_auto_filed_candidate(root):
    """Nothing about auto-DISCOVERY weakens the LEVEL B -> LEVEL C boundary: a
    production write on this candidate's behalf still needs a real ControlPlane
    approval on disk, and the candidate's own state still refuses it."""
    sig = _signature()
    _record_job_failure(root, sig, git_sha="commit-aaa")
    _record_job_failure(root, sig, git_sha="commit-bbb")
    cid = ce.file_candidates_for_repeated_failures(root, cfg={})[0]["candidate_id"]
    stored = ce.read_candidate(root, cid)

    assert ce.human_approval_status(root)["approved"] is False
    with pytest.raises(ce.HumanApprovalRequiredError):
        ce.assert_human_approval(root, stored)
    with pytest.raises(ce.ProductionWriteNotAuthorizedError):
        ce.assert_no_production_write_authorized(root, stored)
    assert stored["approval_level"] == "HUMAN_APPROVAL_REQUIRED"
    assert stored["final_decision"] == "PENDING"


def test_the_auto_filed_candidate_never_reaches_a_tier_above_working_memory(root):
    """One run's repeated failure is not verified engineering knowledge, and
    persist_candidate()'s own assertion is what keeps it out."""
    sig = _signature()
    _record_job_failure(root, sig, git_sha="commit-aaa")
    _record_job_failure(root, sig, git_sha="commit-bbb")
    cid = ce.file_candidates_for_repeated_failures(root, cfg={})[0]["candidate_id"]

    store = MemoryStore(root)
    records = store.find(kind=ce.CANDIDATE_MEMORY_KIND, candidate_id=cid)
    assert records and all(r["level"] == "working" for r in records)
    assert store.find("engineering", kind=ce.CANDIDATE_MEMORY_KIND) == []
    assert store.find("project", kind=ce.CANDIDATE_MEMORY_KIND) == []


def test_the_module_still_holds_its_no_verification_authority_guarantee():
    """The new coupling reads failure evidence; it must not have acquired any
    ability to emit something a reader could take for a verification verdict."""
    ce.assert_no_verification_verdict_vocabulary()


# --- END TO END: the real engine path ----------------------------------------

def _fresh_harness():
    from dv_harness.engine import DVHarness
    tmp = Path(tempfile.mkdtemp())
    (tmp / ".dv-harness" / "graph").mkdir(parents=True)
    (tmp / ".dv-harness" / "graph" / "main_graph.json").write_text(
        REAL_GRAPH.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp, DVHarness(tmp)


def _events(root: Path, event: str) -> list:
    p = root / ".dv-harness" / "events.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            if rec.get("event") == event:
                out.append(rec)
    return out


class _FailingAdapter:
    """The agent could not complete the stage. Nothing else about run_stage()
    is stubbed: the real context gathering, the real Blackboard read, the real
    failure-signature construction and the real Job Memory write all run."""
    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
        from dv_harness.adapters.base import AgentResult
        return AgentResult(ok=False, text="", raw={"stderr": "adapter could not close the stage"},
                           session_id=None)


def _seed_findings(harness, symptom=SYMPTOM, root_cause=ROOT_CAUSE_HINT):
    """The real Blackboard topic engine._gather_stage_context() sources a debug
    failure signature from -- same `findings.last_report` shape
    _write_blackboard_from_evidence() writes on a real stage PASS."""
    harness.blackboard.write("findings", {"last_report": {
        "symptom": symptom, "root_cause": root_cause,
    }}, source="test-seed")


def _run_failed_debug_stage(harness, git_sha, stage="RE_AUDIT"):
    from dv_harness.models import Status
    harness.state.git_sha = git_sha
    harness.set_stage(stage)
    harness.run_stage("close the LFPS failure")
    assert harness.state.stages[stage]["status"] == Status.FAIL.value
    return harness


def test_two_real_failed_run_stage_calls_auto_file_a_candidate_end_to_end():
    """The whole edge, on the path an unattended run actually takes: a real
    run_stage() that does not close, writing a real job_failure record with a
    real failure_signature, twice against two different commits -- and a real
    CapabilityEvolutionCandidate appearing at DISCOVERED with no human
    involved, with the real memory_ids of those two records as its evidence."""
    tmp, h = _fresh_harness()
    try:
        h.adapter = _FailingAdapter()
        _seed_findings(h)

        _run_failed_debug_stage(h, "commit-aaa")
        # One run: detected, but deliberately not yet a pattern.
        first = _events(tmp, "CAPABILITY_EVOLUTION_AUTO_DISCOVERY")
        assert len(first) == 1
        assert first[0]["patterns_detected"] == 0
        assert first[0]["filed"] == []
        assert ce.read_candidates(tmp) == {}

        _run_failed_debug_stage(h, "commit-bbb")

        events = _events(tmp, "CAPABILITY_EVOLUTION_AUTO_DISCOVERY")
        assert len(events) == 2
        assert events[1]["stage"] == "RE_AUDIT"
        assert events[1]["patterns_detected"] == 1
        assert len(events[1]["filed"]) == 1
        filed = events[1]["filed"][0]
        assert filed["current_status"] == "DISCOVERED"
        assert filed["independent_run_count"] == 2

        candidates = ce.read_candidates(tmp)
        assert list(candidates) == [filed["candidate_id"]]
        candidate = candidates[filed["candidate_id"]]
        assert candidate["current_status"] == "DISCOVERED"
        assert candidate["trigger_type"] == "FAILURE_PATTERN"
        assert candidate["recommendation"] == "UNKNOWN"
        assert SYMPTOM.lower() in candidate["hypothesis"].lower()

        # The evidence really is the two job_failure records the two stage runs
        # wrote -- the coupling read what the closure loop produced, not a
        # separately-constructed fixture.
        job_records = MemoryStore(tmp).find("job", kind="job_failure")
        assert candidate["evidence_refs"] == sorted(r["memory_id"] for r in job_records)
        assert len(job_records) == 2

        # DISCOVERY only: no approval was minted anywhere along the way.
        assert ce.human_approval_status(tmp)["approved"] is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_passing_stage_files_nothing():
    """The hook lives on the FAIL/PARTIAL debug branch only. A stage that
    closes must leave the capability-evolution loop completely untouched."""
    from dv_harness.adapters.base import AgentResult
    from dv_harness.models import Status

    tmp, h = _fresh_harness()
    try:
        h.cfg["policy"]["require_stage_gate_evidence"] = False

        class _OkAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text="re-audit clean", raw={}, session_id=None)

        h.adapter = _OkAdapter()
        _seed_findings(h)
        h.state.git_sha = "commit-aaa"
        h.set_stage("RE_AUDIT")
        h.run_stage("goal")
        assert h.state.stages["RE_AUDIT"]["status"] == Status.PASS.value

        assert _events(tmp, "CAPABILITY_EVOLUTION_AUTO_DISCOVERY") == []
        assert ce.read_candidates(tmp) == {}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_an_auto_discovery_failure_never_breaks_the_stage_result(monkeypatch):
    """Best-effort by design, mirroring every sibling _promote_*/_record_*
    method: a capability-evolution bookkeeping problem must never turn an
    already-computed stage result into a crash -- and it is recorded rather
    than swallowed silently."""
    from dv_harness.models import Status

    tmp, h = _fresh_harness()
    try:
        def _boom(root, **kwargs):
            raise RuntimeError("blackboard topic unreadable")

        monkeypatch.setattr(ce, "file_candidates_for_repeated_failures", _boom)
        h.adapter = _FailingAdapter()
        _seed_findings(h)
        _run_failed_debug_stage(h, "commit-aaa")

        assert h.state.stages["RE_AUDIT"]["status"] == Status.FAIL.value
        assert _events(tmp, "CAPABILITY_EVOLUTION_AUTO_DISCOVERY") == []
        failures = _events(tmp, "CAPABILITY_EVOLUTION_AUTO_DISCOVERY_FAILED")
        assert len(failures) == 1
        assert "blackboard topic unreadable" in failures[0]["error"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_verified_fix_recorded_by_the_engine_path_stops_the_auto_filing():
    """The two halves joined on the real path: the closure loop's own
    Engineering-tier verified_fix record is what makes a recurrence stop being
    a capability question."""
    tmp, h = _fresh_harness()
    try:
        h.adapter = _FailingAdapter()
        _seed_findings(h)
        _run_failed_debug_stage(h, "commit-aaa")
        _record_verified_fix(tmp)
        _run_failed_debug_stage(h, "commit-bbb")

        events = _events(tmp, "CAPABILITY_EVOLUTION_AUTO_DISCOVERY")
        assert [e["patterns_detected"] for e in events] == [0, 0]
        assert ce.read_candidates(tmp) == {}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
