"""CLAUDE.md section 55's SELF-LEARNING READINESS MATRIX
(`dv_harness/self_learning_readiness.py` + `python -m
dv_harness.self_learning_readiness`).

WHAT THESE TESTS ARE FOR, mirroring `test_golden_flow_readiness.py`'s own
five-part framing for the sibling matrix this module deliberately does NOT
duplicate:

  1. **A row that silently disappears.** All 22 rows are declared as a fixed
     tuple; a fresh project with nothing on disk must still produce all 22
     (UNKNOWN), never fewer.
  2. **A cell not sourced from anything.** Every row's `fact_source` is
     resolved through the import system, and every evidence-bearing row here
     is driven from a REAL artifact written by a REAL writer -- a real
     `MemoryStore`, a real `Blackboard`, a real `ControlPlane`, a real
     `CornerCaseLibrary`, a real `ProjectRegistry` -- never a patched-in
     return value.
  3. **A report that flatters the project.** The negative controls: an
     engineering-tier record that no longer clears the REAL
     `engineering_admission_gate()` (missing evidence, no reusable claim) must
     read BLOCKED, never READY just because its stored `confidence` field
     still says HIGH; a corner-case-library index that says zero cases while
     real per-case record files sit on disk right next to it must read
     BLOCKED, never the READY an unquestioning index read would report; a
     project with SOME but not ENOUGH confirmed/rejected outcomes must stay
     UNKNOWN, never a fabricated READY.
  4. **A read that is secretly a write.** Running the matrix against a project
     that has never used a surface must not mint that surface's directory or
     file -- no `.dv-harness/` tree of any kind for a project that never had
     one, and an already-populated project's files are byte-identical
     afterwards.
  5. **The front door drifting from the module.** `python -m
     dv_harness.self_learning_readiness` is driven as a REAL subprocess.

Nothing here runs a stage, files a real production change, or promotes
anything to Organizational Memory: every candidate/record/registration below
is written directly through the real writer that owns it, on a `tmp_path`
root, never against this repository.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dv_harness import capability_evolution as ce  # noqa: E402
from dv_harness import self_learning_readiness as slr  # noqa: E402
from dv_harness.blackboard import Blackboard  # noqa: E402
from dv_harness.control_plane import ControlPlane  # noqa: E402
from dv_harness.cross_project_mining import ProjectRegistry  # noqa: E402
from dv_harness.evidence_db import signature_key  # noqa: E402
from dv_harness.memory import CornerCaseLibrary, MemoryConsolidator, MemoryGC, MemoryStore  # noqa: E402
from dv_harness.memory_router import route_and_store  # noqa: E402
from dv_harness.memory_vault import build_failure_signature  # noqa: E402


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    return tmp_path / "proj"


def _row(matrix, row_id):
    for r in matrix["rows"]:
        if r["row_id"] == row_id:
            return r
    raise KeyError(row_id)


def _tree_snapshot(root: Path) -> dict:
    """path -> (mtime_ns, content) for every file under `.dv-harness/`, used
    to prove a read stayed a read."""
    dv = root / ".dv-harness"
    if not dv.is_dir():
        return {}
    out = {}
    for p in dv.rglob("*"):
        if p.is_file():
            out[str(p.relative_to(root))] = (p.stat().st_mtime_ns, p.read_bytes())
    return out


# ---------------------------------------------------------------------------
# Real Job Memory / candidate fixtures, adapted from
# test_capability_evolution_auto_discovery.py's own real-writer helpers.
# ---------------------------------------------------------------------------

SYMPTOM = "USB3 LFPS handshake never completes on port 0"
ROOT_CAUSE_HINT = "polling.exit timeout while RX detect stays low"


def _signature(**overrides):
    fields = dict(protocol="USB3", symptom=SYMPTOM, root_cause_hint=ROOT_CAUSE_HINT)
    fields.update(overrides)
    return build_failure_signature(**fields)


def _record_job_failure(root: Path, signature: dict, *, git_sha=None, job_id=None,
                        stage="RE_AUDIT", attempt=1) -> dict:
    record = {
        "kind": "job_failure", "scope": "debug",
        "title": f"{stage} attempt {attempt} did not close",
        "stage": stage, "attempt": attempt, "status": "PARTIAL",
        "blocking_reason": "GATE_FAIL: root_cause_evidence_gate",
        "failure_signature": signature, "protocol": signature.get("protocol"),
        "git_sha": git_sha,
    }
    if job_id is not None:
        record["job_id"] = job_id
    routed = route_and_store(root, record, cfg={})
    assert routed["destination"] == "JOB_MEMORY", routed
    return routed


def _search(matches, basis, conclusive=True):
    return {"matches": list(matches), "search_basis": basis, "search_conclusive": conclusive}


def _complete_candidate_fields(**overrides):
    """A schema-valid, FULLY-SEARCHED candidate (adapted from
    test_capability_evolution_research_architect.py's own
    _semantic_change_impact_fields()): every one of the six searches is
    conclusive, so unanswered_l5_check_questions() is empty and
    decide_recommendation() resolves to a real, non-UNKNOWN recommendation."""
    fields = {
        "trigger_source": "DOC-0123456789ab",
        "trigger_type": "EXTERNAL_RESEARCH",
        "source_provenance": [{
            "document": "semantic_change_impact.pdf", "version": "sha256:" + "9" * 64,
            "page": "7", "section": "5.2 Results", "source_location": "Table 3",
        }],
        "evidence_refs": ["research/evidence_cards/paper_001.card.json",
                          "dv_harness/change_impact.py:compute_change_impact"],
        "hypothesis": "Deriving change impact from a semantic delta would shrink regression.",
        "affected_capability": "verification-change-impact",
        "existing_agent": _search(["analysis-agent (CHANGE_IMPACT node)"],
                                  "read .claude/agents/ROSTER.md"),
        "existing_skill": _search(["CORE/verification-change-impact"],
                                  "grep .claude/skills/**/SKILL.md"),
        "existing_graph_node": _search(["CHANGE_IMPACT", "REGRESSION_SELECT"],
                                       "read main_graph.json + STAGE_GATES"),
        "existing_state": _search([], "read blackboard.py topics; none matches"),
        "existing_memory": _search([], "read memory_router dispatch table; none matches"),
        "existing_files": _search(
            ["dv_harness/change_impact.py compute_change_impact()"],
            "grep -rn change_impact dv_harness tools"),
        "exact_gap": "select_regression() has no semantic-delta stage in front of the "
                     "file->module map.",
        "proposed_action": "Extend compute_change_impact() with a semantic-delta stage.",
        "expected_verification_benefit": "Fewer irrelevant tests at equal escape rate.",
        "evidence_strength": {"scale": 3, "rationale": "One controlled benchmark."},
        "confidence": {"inputs": {
            "independent_sources_count": 2, "evidence_refs_verified": True,
            "counter_evidence_count": 0, "multi_agent_consensus_count": 0}},
        "implementation_difficulty": "MEDIUM", "integration_risk": "MEDIUM",
        "maintenance_cost": "MEDIUM", "experiment_required": True,
        "experiment_plan": "Replay 20 historical changes and compare selections.",
        "benchmark_plan": "Before/after selected test count on the replay set.",
        "acceptance_criteria": ["no historically-caught failure is missed"],
        "rollback_plan": "Revert the one call site; the prior path is restored byte-for-byte.",
        "approval_level": "HUMAN_APPROVAL_REQUIRED",
    }
    fields.update(overrides)
    return fields


# ===========================================================================
# 1. Row declarations, resolvability, and CLI wiring
# ===========================================================================

def test_22_rows_declared_unique_and_resolvable():
    assert len(slr.ROWS) == 22
    assert len(set(slr.row_ids())) == 22
    assert len(set(slr.row_labels())) == 22
    resolved = slr.assert_fact_sources_resolvable()
    assert len(resolved) >= 22  # at least one fact_source per row


def test_every_row_maps_to_exactly_one_probe():
    assert set(slr.PROBES) == set(slr.row_ids())


def test_combine_readiness_worst_wins_and_empty_is_unknown():
    assert slr.combine_readiness([]) == slr.UNKNOWN
    assert slr.combine_readiness([slr.READY, slr.UNKNOWN]) == slr.PARTIAL
    assert slr.combine_readiness([slr.READY, slr.BLOCKED, slr.UNKNOWN]) == slr.BLOCKED
    assert slr.combine_readiness([slr.UNKNOWN, slr.UNKNOWN]) == slr.UNKNOWN
    assert slr.combine_readiness([slr.READY, slr.READY]) == slr.READY


# ===========================================================================
# 2. The untouched-tree guarantee (Negative Control #1: no fabrication of
#    state, and no fabrication of readiness, for a project that never ran)
# ===========================================================================

def test_empty_project_all_22_rows_unknown_and_no_dv_harness_tree_created(project: Path):
    project.mkdir(parents=True)
    assert not (project / ".dv-harness").exists()

    matrix = slr.derive_self_learning_readiness(project)

    assert len(matrix["rows"]) == 22
    assert {r["status"] for r in matrix["rows"]} == {slr.UNKNOWN}
    assert matrix["self_learning_readiness"] == slr.UNKNOWN
    assert matrix["summary"]["rows_unknown"] == 22

    # The one property that matters most: asking the question about a project
    # that never used ANY of these surfaces must not create a single file for
    # it -- not a memory store, not a Blackboard, not a control.json.
    assert not (project / ".dv-harness").exists()


def test_populated_project_is_byte_identical_after_a_read(project: Path):
    project.mkdir(parents=True)
    store = MemoryStore(project)
    store.add("engineering", {
        "title": "real finding", "root_cause": "polling.exit timeout",
        "fix": "widen RX detect window", "confidence": "HIGH", "reusable": True,
        "evidence": {"waveform": "rx_detect.fsdb"},
    })
    ControlPlane(project).approve(ce.HUMAN_APPROVAL_STAGE, note="n", reviewer_id="eng1")

    before = _tree_snapshot(project)
    assert before  # sanity: there is real state to protect

    slr.derive_self_learning_readiness(project)

    after = _tree_snapshot(project)
    assert after == before


# ===========================================================================
# 3. Memory Index Integrity
# ===========================================================================

def test_memory_index_integrity_ready_then_blocked_on_drift(project: Path):
    project.mkdir(parents=True)
    store = MemoryStore(project)
    store.add("working", {"title": "a real note"})

    matrix = slr.derive_self_learning_readiness(project)
    assert _row(matrix, "memory_index_integrity")["status"] == slr.READY

    # Corrupt the index: an index row pointing at a memory_id with no file --
    # the exact "lost update" shape memory.py's own index_integrity() docstring
    # describes as a real, previously-measured defect in this project.
    rows = store._index()
    rows.append({"memory_id": "MEM-GHOST0000", "level": "working",
                "path": "working/MEM-GHOST0000.json", "created_at": time.time()})
    store._save_index(rows)

    matrix = slr.derive_self_learning_readiness(project)
    row = _row(matrix, "memory_index_integrity")
    assert row["status"] == slr.BLOCKED
    assert "index row(s) with no file" in row["gap"]


# ===========================================================================
# 4. Engineering / Organizational admission health
#    (Negative Control #2: a stored HIGH-confidence record that no longer
#    clears the REAL gate must not be reported READY)
# ===========================================================================

def test_engineering_admission_health_negative_control(project: Path):
    project.mkdir(parents=True)
    store = MemoryStore(project)
    # A record that genuinely clears engineering_admission_gate(): real
    # evidence, HIGH confidence, and a reusable claim field.
    store.add("engineering", {
        "title": "real finding", "root_cause": "polling.exit timeout",
        "fix": "widen RX detect window", "confidence": "HIGH", "reusable": True,
        "evidence": {"waveform": "rx_detect.fsdb"},
    })
    matrix = slr.derive_self_learning_readiness(project)
    assert _row(matrix, "engineering_admission_health")["status"] == slr.READY

    # A second record that LOOKS admitted (level=="engineering", on disk) but
    # carries neither real evidence nor a reusable claim -- e.g. a record hand
    # -written or corrupted after the gate that should have refused it. The
    # module must recompute the gate from the record's own content, never
    # trust that "it is in the engineering/ directory" means it was admitted.
    store.add("engineering", {"title": "unverified guess", "confidence": "HIGH"})

    matrix = slr.derive_self_learning_readiness(project)
    row = _row(matrix, "engineering_admission_health")
    assert row["status"] == slr.BLOCKED
    assert "1/2" in row["evidence"]
    assert "NO_EVIDENCE" in row["gap"] or "NO_REUSABLE_CLAIM" in row["gap"]


def test_organizational_admission_health_absent_and_present(project: Path):
    project.mkdir(parents=True)
    store = MemoryStore(project)
    matrix = slr.derive_self_learning_readiness(project)
    assert _row(matrix, "organizational_admission_health")["status"] == slr.UNKNOWN

    # A record placed straight in the organizational tier without ever
    # clearing promote_to_organizational()'s real gates (no
    # source_engineering_memory_id, no HIGH confidence_result) -- exactly the
    # forgery organizational_admission_gate() exists to catch.
    store.add("organizational", {"title": "unearned promotion"})
    matrix = slr.derive_self_learning_readiness(project)
    row = _row(matrix, "organizational_admission_health")
    assert row["status"] == slr.BLOCKED
    assert "NO_ACTIVE_ENGINEERING_SOURCE_RECORD" in row["gap"]


# ===========================================================================
# 5. Revalidation queue / retraction+supersede ledger / confirmed-conclusion
#    accumulation -- MemoryGC's real contradiction/staleness surfaces.
# ===========================================================================

def test_revalidation_and_ledger_and_confirmation_rows(project: Path):
    project.mkdir(parents=True)
    store = MemoryStore(project)
    gc = MemoryGC(store)

    stale = store.add("engineering", {
        "title": "aging claim", "root_cause": "x", "confidence": "HIGH", "reusable": True})
    retracted = store.add("engineering", {
        "title": "wrong claim", "root_cause": "y", "confidence": "HIGH", "reusable": True})
    superseded = store.add("engineering", {
        "title": "old claim", "root_cause": "z", "confidence": "HIGH", "reusable": True})

    matrix = slr.derive_self_learning_readiness(project)
    assert _row(matrix, "revalidation_queue")["status"] == slr.READY
    assert _row(matrix, "confirmed_conclusion_accumulation")["status"] == slr.UNKNOWN

    gc.flag_stale(stale["memory_id"], "aged past max_age_days")
    gc.retract(retracted["memory_id"], "root cause disproven")
    gc.supersede(superseded["memory_id"], "MEM-NEWER0000", "a later run found the real cause")

    matrix = slr.derive_self_learning_readiness(project)
    reval = _row(matrix, "revalidation_queue")
    assert reval["status"] == slr.PARTIAL
    assert "1 record(s) flagged NEEDS_REVALIDATION" in reval["evidence"]

    ledger = _row(matrix, "retraction_supersede_ledger")
    assert ledger["status"] == slr.READY
    assert "1 RETRACTED, 1 SUPERSEDED" in ledger["evidence"]

    # MemoryConsolidator.from_closed_finding() is the real CONFIRMED-tier
    # writer -- confidence_calibration.py's own TIER_DEFINITION_SOURCE names
    # it, not a hand-set confidence string.
    MemoryConsolidator(store).from_closed_finding(
        {"status": "CLOSED", "title": "closed finding", "root_cause": "polling.exit",
         "fix": "widen window"},
        {"single_sim": "PASS", "regression": "NOT_REQUIRED", "reaudit": "CLEAN"},
    )
    matrix = slr.derive_self_learning_readiness(project)
    confirmed = _row(matrix, "confirmed_conclusion_accumulation")
    assert confirmed["status"] == slr.READY
    assert "1 CONFIRMED-tier" in confirmed["evidence"]


# ===========================================================================
# 6. Corner-Case Library, including its own real drift finding
#    (Negative Control #3: an index that says zero while real record files
#    sit on disk must not be reported READY)
# ===========================================================================

def test_corner_case_library_absent_ready_and_index_drift(project: Path):
    project.mkdir(parents=True)
    matrix = slr.derive_self_learning_readiness(project)
    assert _row(matrix, "corner_case_library")["status"] == slr.UNKNOWN

    lib = CornerCaseLibrary(project)
    lib.add({"corner_id": "cc1", "protocol": "AXI4", "category": "ordering",
             "risk_tier": "P0", "description": "out-of-order response"})

    matrix = slr.derive_self_learning_readiness(project)
    row = _row(matrix, "corner_case_library")
    assert row["status"] == slr.READY
    assert "1 corner case(s), 1 ACTIVE" in row["evidence"]

    # Corrupt the index the way this repo's own store was actually found
    # corrupted while validating this module: wipe index.json's rows while
    # leaving the real per-case record file on disk untouched.
    index_path = project / ".dv-harness" / "memory" / "corner_case_library" / "index.json"
    index_path.write_text("[]", encoding="utf-8")

    matrix = slr.derive_self_learning_readiness(project)
    row = _row(matrix, "corner_case_library")
    assert row["status"] == slr.BLOCKED
    assert "record file(s) exist with no index row" in row["gap"]


# ===========================================================================
# 7. Candidate-lifecycle rows: L5 check, overlap/recommendation, promotion
#    state governance, human approval, benchmark, stability window, rollback,
#    audit trail, architecture decisions, repeated-failure auto-filing.
# ===========================================================================

def test_l5_check_and_overlap_rows_ready_for_a_complete_candidate(project: Path):
    project.mkdir(parents=True)
    candidate = ce.build_candidate(**_complete_candidate_fields())
    ce.persist_candidate(project, candidate)

    matrix = slr.derive_self_learning_readiness(project)
    assert _row(matrix, "l5_check_completeness")["status"] == slr.READY
    overlap = _row(matrix, "overlap_recommendation_decisions")
    assert overlap["status"] == slr.READY
    assert "ENHANCE=1" in overlap["evidence"]

    audit = _row(matrix, "candidate_decision_audit_trail")
    assert audit["status"] == slr.READY

    governance = _row(matrix, "promotion_state_governance")
    assert governance["status"] == slr.READY
    assert "DISCOVERED=1" in governance["evidence"]


def test_l5_check_and_overlap_rows_degrade_with_an_incomplete_candidate(project: Path):
    """A second, genuinely in-flight candidate -- written straight to the
    Blackboard the way a live research session would leave it mid-search,
    never through persist_candidate()'s schema gate -- must pull the combined
    verdict down to PARTIAL rather than being silently ignored."""
    project.mkdir(parents=True)
    complete = ce.build_candidate(**_complete_candidate_fields())
    ce.persist_candidate(project, complete)

    incomplete = dict(complete)
    incomplete["candidate_id"] = "CEC-incomplete0"
    incomplete["current_status"] = "EVIDENCE_GATHERING"
    incomplete["recommendation"] = "UNKNOWN"
    # An EMPTY search_basis, not merely an inconclusive one: _slot_answered()
    # keys on search_basis being non-empty, so this is what actually leaves
    # q3 (existing_files) unanswered rather than answered-but-inconclusive.
    incomplete["existing_files"] = _search([], "", conclusive=False)
    Blackboard(project).upsert_capability_evolution_candidate(
        incomplete["candidate_id"], incomplete, source="test")

    matrix = slr.derive_self_learning_readiness(project)
    assert _row(matrix, "l5_check_completeness")["status"] == slr.PARTIAL
    assert _row(matrix, "overlap_recommendation_decisions")["status"] == slr.PARTIAL

    governance = _row(matrix, "promotion_state_governance")
    assert governance["status"] == slr.READY  # both states are legal section-70 states
    assert "EVIDENCE_GATHERING=1" in governance["evidence"]


def test_promotion_state_governance_blocked_on_illegal_state(project: Path):
    project.mkdir(parents=True)
    candidate = ce.build_candidate(**_complete_candidate_fields())
    candidate["current_status"] = "NOT_A_REAL_STATE"
    Blackboard(project).upsert_capability_evolution_candidate(
        candidate["candidate_id"], candidate, source="test")

    matrix = slr.derive_self_learning_readiness(project)
    row = _row(matrix, "promotion_state_governance")
    assert row["status"] == slr.BLOCKED
    assert "NOT_A_REAL_STATE" in row["gap"]


def test_human_approval_gate_absent_then_approved(project: Path):
    project.mkdir(parents=True)
    matrix = slr.derive_self_learning_readiness(project)
    row = _row(matrix, "human_approval_gate")
    assert row["status"] == slr.UNKNOWN
    assert not (project / ".dv-harness").exists()  # ControlPlane was never constructed

    ControlPlane(project).approve(
        ce.HUMAN_APPROVAL_STAGE, note="reviewed the L5.x proposal",
        reviewer_id="reviewer1", reviewer_confidence="HIGH")

    matrix = slr.derive_self_learning_readiness(project)
    row = _row(matrix, "human_approval_gate")
    assert row["status"] == slr.READY
    assert "approved=True" in row["evidence"]


def test_production_rollback_history_blocked_on_empty_plan(project: Path):
    project.mkdir(parents=True)
    # build_candidate() itself requires a non-empty rollback_plan (schema), so
    # a genuinely empty one can only reach the Blackboard the way a hand-
    # edited or corrupted record would -- written directly, bypassing the
    # schema gate persist_candidate() would otherwise enforce.
    candidate = ce.build_candidate(**_complete_candidate_fields())
    candidate["rollback_plan"] = ""
    candidate["current_status"] = "PRODUCTION"
    Blackboard(project).upsert_capability_evolution_candidate(
        candidate["candidate_id"], candidate, source="test")

    matrix = slr.derive_self_learning_readiness(project)
    row = _row(matrix, "production_rollback_history")
    assert row["status"] == slr.BLOCKED
    assert candidate["candidate_id"] in row["gap"]


def test_repeated_failure_auto_filed_partial_then_ready(project: Path):
    project.mkdir(parents=True)
    sig = _signature()
    _record_job_failure(project, sig, git_sha="commit-aaa")
    _record_job_failure(project, sig, git_sha="commit-bbb")

    matrix = slr.derive_self_learning_readiness(project)
    row = _row(matrix, "repeated_failure_auto_filed")
    assert row["status"] == slr.PARTIAL
    assert "1 repeated unresolved failure pattern(s)" in row["evidence"]
    assert "0 auto-filed" in row["evidence"]

    filed = ce.file_candidates_for_repeated_failures(project)
    assert len(filed) == 1 and filed[0]["filed"] is True

    matrix = slr.derive_self_learning_readiness(project)
    row = _row(matrix, "repeated_failure_auto_filed")
    assert row["status"] == slr.READY
    assert "1 auto-filed" in row["evidence"]


def test_architecture_decision_history_row(project: Path):
    project.mkdir(parents=True)
    matrix = slr.derive_self_learning_readiness(project)
    assert _row(matrix, "architecture_decision_history")["status"] == slr.UNKNOWN

    from dv_harness.memory_router import ARCHITECTURE_DECISION_KIND
    # PROJECT_MEMORY is architecture_decision's ceiling only once it is
    # DECIDED -- route_memory() keys that on `verified`, not on the kind
    # string alone (an unverified one stays in WORKING_MEMORY).
    routed = route_and_store(project, {
        "kind": ARCHITECTURE_DECISION_KIND, "title": "adopt semantic change-impact",
        "decision": "ENHANCE change_impact.py", "verified": True}, cfg={})
    assert routed["destination"] == "PROJECT_MEMORY"

    matrix = slr.derive_self_learning_readiness(project)
    row = _row(matrix, "architecture_decision_history")
    assert row["status"] == slr.READY
    assert "1 architecture_decision" in row["evidence"]


# ===========================================================================
# 8. Confidence Tier Calibration -- must stay honestly UNKNOWN on partial
#    history rather than claiming CALIBRATED early.
# ===========================================================================

def test_confidence_tier_calibration_stays_unknown_below_the_history_bar(project: Path):
    project.mkdir(parents=True)
    store = MemoryStore(project)
    gc = MemoryGC(store)
    # Three confirmed HIGH-tier outcomes -- real evidence, but fewer than
    # confidence_calibration.MIN_DETERMINATE_OUTCOMES_PER_TIER (10). A module
    # that fabricated readiness from a small sample would report CALIBRATED
    # here; the real one must not.
    for i in range(3):
        rec = store.add("engineering", {
            "title": f"finding {i}", "root_cause": f"cause {i}", "confidence": "HIGH",
            "reusable": True})
        gc.confirm(rec["memory_id"])

    matrix = slr.derive_self_learning_readiness(project)
    row = _row(matrix, "confidence_tier_calibration")
    assert row["status"] == slr.UNKNOWN
    assert "INSUFFICIENT_HISTORY" in row["evidence"]


# ===========================================================================
# 9. Cross-Project Registry + Pattern Mining, against real separately
#    constructed project trees (never this repository counted twice).
# ===========================================================================

def test_cross_project_registry_and_pattern_mining(project: Path, tmp_path: Path):
    project.mkdir(parents=True)
    matrix = slr.derive_self_learning_readiness(project)
    assert _row(matrix, "cross_project_registry")["status"] == slr.UNKNOWN
    assert _row(matrix, "cross_project_pattern_mining")["status"] == slr.UNKNOWN

    other = tmp_path / "other_project"
    other.mkdir()
    sig = _signature(protocol="PCIe")
    _record_job_failure(project, sig, git_sha="commit-aaa")
    _record_job_failure(project, sig, git_sha="commit-bbb")
    _record_job_failure(other, sig, git_sha="commit-ccc")
    _record_job_failure(other, sig, git_sha="commit-ddd")

    registry = ProjectRegistry(project)
    registry.register(project, project_id="host")
    registry.register(other, project_id="other")

    matrix = slr.derive_self_learning_readiness(project)
    reg_row = _row(matrix, "cross_project_registry")
    assert reg_row["status"] == slr.READY
    assert "2 registered project(s), 2 readable" in reg_row["evidence"]

    mining_row = _row(matrix, "cross_project_pattern_mining")
    assert mining_row["status"] == slr.READY
    assert "1 cross-project pattern(s)" in mining_row["evidence"]


# ===========================================================================
# 10. Execute() exit-code contract and the real CLI subprocess
# ===========================================================================

def test_execute_exit_code_matches_verdict(project: Path):
    project.mkdir(parents=True)
    code, matrix, text = slr.execute(project)
    assert code == 2
    assert matrix["self_learning_readiness"] == slr.UNKNOWN
    assert "SELF-LEARNING READINESS MATRIX" in text


def test_cli_subprocess_json_has_22_rows(tmp_path: Path):
    project = tmp_path / "cliproj"
    project.mkdir()
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.self_learning_readiness",
         "--project-root", str(project), "--json"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 2, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == slr.SCHEMA_VERSION
    assert len(payload["rows"]) == 22
    assert not (project / ".dv-harness").exists()


def test_cli_subprocess_text_report_renders_the_table(tmp_path: Path):
    project = tmp_path / "cliproj2"
    project.mkdir()
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.self_learning_readiness",
         "--project-root", str(project)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 2, result.stderr
    assert "SELF-LEARNING READINESS MATRIX (section 55)" in result.stdout
    assert "Corner-Case Library" in result.stdout
    assert "Cross-Project Pattern Mining" in result.stdout
