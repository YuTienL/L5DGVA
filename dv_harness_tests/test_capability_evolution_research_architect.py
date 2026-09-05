# dv_harness_tests/test_capability_evolution_research_architect.py
#
# Stage-1 acceptance tests B/C/D/E of the Research-Capability Evolution master
# prompt, plus the mechanism tests that make them meaningful.
#
# Scope boundary held by these tests themselves: no real external paper or
# standard is ingested or analyzed anywhere here (Stage 2), and nothing
# implements a capability-evolution change to production code (Stage 3). Every
# candidate below is synthetic and every persistence test runs against a
# tmp_path root, never this repo.
import hashlib
import json
import re
from pathlib import Path

import pytest

from dv_harness import capability_evolution as ce
from dv_harness.blackboard import Blackboard
from dv_harness.control_plane import ControlPlane
from dv_harness.inference import next_best_action, score_confidence
from dv_harness.memory import MemoryStore
from dv_harness.models import Status

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# Synthetic evidence. Both cards below describe the SAME technique -- semantic
# change-impact analysis, the master prompt's own section 15 worked example --
# and differ only in whether this repository could actually be searched. That
# is the single variable acceptance tests B and C are about.


def _search(matches, basis, conclusive=True):
    return {"matches": list(matches), "search_basis": basis, "search_conclusive": conclusive}


def _semantic_change_impact_fields(**overrides):
    """A candidate raised from a synthetic ResearchEvidenceCard about semantic
    change-impact analysis -- a technique that demonstrably overlaps a REAL
    existing mechanism in this repo: dv_harness/change_impact.py's
    compute_change_impact()/select_regression(), owned by the
    CORE/verification-change-impact skill and enforced at the REGRESSION_SELECT
    stage by regression_selection_completeness_gate.py."""
    fields = {
        "trigger_source": "DOC-0123456789ab",
        "trigger_type": "EXTERNAL_RESEARCH",
        "source_provenance": [{
            "document": "semantic_change_impact.pdf",
            "version": "sha256:" + "9" * 64,
            "page": "7",
            "section": "5.2 Results",
            "source_location": "Table 3",
        }],
        "evidence_refs": [
            "research/evidence_cards/paper_001.card.json",
            "dv_harness/change_impact.py:compute_change_impact",
        ],
        "hypothesis": (
            "Deriving change impact from a spec/RTL SEMANTIC delta, rather than from the "
            "git textual diff alone, would shrink the selected regression without losing "
            "escapes."
        ),
        "affected_capability": "verification-change-impact",
        "existing_agent": _search(
            ["analysis-agent (CHANGE_IMPACT node)"],
            "read .claude/agents/ROSTER.md and .claude/agents/analysis-agent.md in full",
        ),
        "existing_skill": _search(
            ["CORE/verification-change-impact"],
            "grep -ril 'change.impact' .claude/skills/**/SKILL.md, then read the hit",
        ),
        "existing_graph_node": _search(
            ["CHANGE_IMPACT", "REGRESSION_SELECT"],
            "read .dv-harness/graph/main_graph.json nodes and gates.py STAGE_GATES",
        ),
        "existing_state": _search(
            [],
            "read dv_harness/blackboard.py's topics; no semantic-delta topic exists, "
            "the computed selection lives in .dv-harness/regression/computed_selection.json",
        ),
        "existing_memory": _search(
            [],
            "read memory_router.route_memory()'s dispatch table; no change-impact kind",
        ),
        "existing_files": _search(
            [
                "dv_harness/change_impact.py compute_change_impact()/select_regression()",
                "tools/verification_flow/regression_selection_completeness_gate.py",
            ],
            "grep -rn 'change_impact' --include=*.py dv_harness tools, then read both hits",
        ),
        "exact_gap": (
            "select_regression() ranks from a git textual diff and a file->module map; "
            "nothing derives a spec/RTL semantic delta, so a comment-only edit and a "
            "state-machine edit to the same file select the same regression."
        ),
        "proposed_action": (
            "Extend dv_harness/change_impact.py with a semantic-delta stage in front of "
            "the existing file->module map, keeping select_regression()'s TARGETED/"
            "DEPENDENCY/SAFETY output shape and its NO-SHRINK gate unchanged."
        ),
        "expected_verification_benefit": (
            "Fewer irrelevant tests per small RTL change at equal escape rate, measured "
            "against replayed historical changes."
        ),
        "evidence_strength": {
            "scale": 3,
            "rationale": "One controlled benchmark over 4 designs, reported by the authors.",
        },
        "confidence": {"inputs": {
            "independent_sources_count": 2,
            "evidence_refs_verified": True,
            "counter_evidence_count": 0,
            "multi_agent_consensus_count": 0,
        }},
        "implementation_difficulty": "MEDIUM",
        "integration_risk": "MEDIUM",
        "maintenance_cost": "MEDIUM",
        "experiment_required": True,
        "experiment_plan": (
            "Replay 20 historical RTL/spec changes and compare the semantic selection "
            "against the current select_regression() output and the known outcomes."
        ),
        "benchmark_plan": (
            "Before/after: selected test count, wall-clock regression cost, and missed "
            "known failures, on the same 20 replayed changes."
        ),
        "acceptance_criteria": [
            "no historically-caught failure is missed by the semantic selection",
            "median selected test count falls by >=20% on the replay set",
        ],
        "rollback_plan": (
            "The semantic stage is a separate function called from "
            "compute_change_impact(); revert that one call and the pre-existing "
            "file->module path is restored byte-for-byte."
        ),
        "approval_level": "HUMAN_APPROVAL_REQUIRED",
    }
    fields.update(overrides)
    return fields


# --------------------------------------------------------------------------
# Stage-1 Acceptance Test B


def test_B_overlapping_technique_produces_enhance_not_add():
    """A card describing a technique that clearly overlaps a REAL existing
    dv_harness mechanism must decide ENHANCE. ADD must be unreachable while any
    of the six searches returned a match -- master prompt sections 2.2/14, and
    the exact failure mode this project has already had caught once (parallel
    tiered-confidence classifiers, duplicate memory mechanisms)."""
    candidate = ce.build_candidate(**_semantic_change_impact_fields())

    assert candidate["recommendation"] == "ENHANCE"
    assert candidate["recommendation"] != "ADD"
    assert candidate["overlap_status"] == "PARTIAL_MATCH"
    # The decision names the real asset it is telling the change to go into.
    assert "dv_harness/change_impact.py" in candidate["existing_files"]["matches"][0]
    assert "CORE/verification-change-impact" in candidate["existing_skill"]["matches"]
    # And it is a decision made by code from the recorded evidence, not a label.
    assert "ADD is unreachable" in candidate["decision_rationale"]


def test_B_add_is_refused_even_when_the_agent_asks_for_it():
    """The agent stating ADD does not make it ADD. A stated recommendation that
    disagrees with the evidence is an error, never an override."""
    with pytest.raises(ce.CapabilityEvolutionCandidateValidationError) as exc:
        ce.build_candidate(**_semantic_change_impact_fields(
            recommendation="ADD",
            enhance_insufficient_reason="I would rather write a new agent.",
        ))
    assert "decides 'ENHANCE'" in str(exc.value)


def test_B_add_is_reachable_only_from_a_conclusively_empty_search():
    """ENHANCE is not hardcoded: with every search conclusive and empty, plus a
    real reason ENHANCE is insufficient, HIGH recomputed confidence and
    evidence_strength >= 3, the SAME code path decides ADD. Without this the
    test above would prove only that the function always says ENHANCE."""
    empty = {
        slot: _search([], f"searched for PSS in {slot}; no hit anywhere in the repo")
        for slot in ce.L5_SEARCH_SLOTS
    }
    candidate = ce.build_candidate(**_semantic_change_impact_fields(
        affected_capability="portable-stimulus (PSS)",
        exact_gap="no PSS model, skill, node or module exists anywhere in this repo",
        enhance_insufficient_reason=(
            "there is no existing asset to extend: grep for 'portable stimulus'/'PSS' "
            "over .claude/skills, dv_harness/*.py and every *.md returns zero hits"
        ),
        evidence_strength={"scale": 4, "rationale": "two independent production reports"},
        confidence={"inputs": {
            "independent_sources_count": 3,
            "evidence_refs_verified": True,
            "counter_evidence_count": 0,
            "multi_agent_consensus_count": 2,
        }},
        **empty,
    ))
    assert candidate["overlap_status"] == "MISSING"
    assert candidate["recommendation"] == "ADD"


def test_B_missing_without_a_stated_enhance_reason_falls_back_to_experiment():
    """MISSING alone does not license ADD. Master prompt section 14 question 10
    is a precondition, not a form field filled in afterwards."""
    empty = {
        slot: _search([], f"searched {slot}; no hit")
        for slot in ce.L5_SEARCH_SLOTS
    }
    candidate = ce.build_candidate(**_semantic_change_impact_fields(
        affected_capability="portable-stimulus (PSS)",
        exact_gap="no PSS model exists",
        evidence_strength={"scale": 4, "rationale": "two independent production reports"},
        confidence={"inputs": {
            "independent_sources_count": 3,
            "evidence_refs_verified": True,
            "counter_evidence_count": 0,
            "multi_agent_consensus_count": 2,
        }},
        **empty,
    ))
    assert candidate["recommendation"] == "EXPERIMENT"
    assert "no stated reason ENHANCE is insufficient" in candidate["decision_rationale"]


# --------------------------------------------------------------------------
# Stage-1 Acceptance Test C


def test_C_insufficient_repository_evidence_produces_unknown_not_missing():
    """A card whose repository search could not actually be completed must
    decide UNKNOWN. A fabricated MISSING here is what would license an ADD over
    the top of a mechanism that already exists -- the single most expensive
    wrong answer this whole pipeline can produce."""
    candidate_fields = _semantic_change_impact_fields(
        existing_files=_search(
            [],
            "attempted `grep -rn change_impact dv_harness/` but the tree was not "
            "readable from this session; the search settles nothing",
            conclusive=False,
        ),
    )
    decision = ce.decide_recommendation(candidate_fields)

    assert decision["overlap_status"] == "UNKNOWN"
    assert decision["overlap_status"] != "MISSING"
    assert decision["recommendation"] == "UNKNOWN"
    assert decision["recommendation"] not in ("ADD", "ENHANCE", "KEEP", "REJECT")
    assert "absence is not a finding" in decision["rationale"]


def test_C_unknown_is_reported_with_the_real_next_best_action():
    """UNKNOWN is not a dead end: the same inference.next_best_action() every
    other stage uses reports what would settle it. The action is a real search
    instruction, not the DV-simulation fallback."""
    fields = _semantic_change_impact_fields(
        existing_skill=_search([], "not searched: skills tree unavailable", conclusive=False),
    )
    # Drop a whole slot so the ten-question check is genuinely incomplete too.
    fields.pop("existing_memory")
    actions = ce.next_actions_for_unanswered(fields)

    gaps = {a["gap"] for a in actions}
    assert "q8_which_memory_layer_stores_it" in gaps
    memory_action = next(a for a in actions if a["gap"] == "q8_which_memory_layer_stores_it")
    assert memory_action["source"] == "l5_check_search_plan"
    assert "route_memory()" in memory_action["suggested_action"]
    # None of it is the protocol-registry path's DV-simulation fallback.
    assert not any("RTL/spec/VIP" in a["suggested_action"] for a in actions)


def test_C_a_missing_claim_over_an_inconclusive_search_does_not_validate():
    """Belt and braces: even a hand-written candidate that asserts MISSING is
    rejected by the schema when any search_conclusive is false, so the honesty
    rule holds for a record this module did not build."""
    fields = _semantic_change_impact_fields()
    candidate = ce.build_candidate(**fields)
    candidate["overlap_status"] = "MISSING"
    candidate["existing_files"]["search_conclusive"] = False
    with pytest.raises(ce.CapabilityEvolutionCandidateValidationError):
        ce.validate_candidate(candidate)


# --------------------------------------------------------------------------
# Stage-1 Acceptance Test D


def _tree_fingerprint(*dirs):
    """sha256 of every file's bytes under each directory, keyed by path."""
    out = {}
    for d in dirs:
        for p in sorted(Path(d).rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                out[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def test_D_running_the_decision_logic_modifies_no_repo_file(tmp_path):
    """Running the whole research-architect code path -- decide, build,
    persist, transition, read back -- must not modify one byte under
    dv_harness/ or .claude/. Master prompt section 73's Self-Improvement Safety
    Boundary: the machinery that proposes changes to this harness may not BE a
    change to this harness."""
    before = _tree_fingerprint(ROOT / "dv_harness", ROOT / ".claude")

    candidate = ce.build_candidate(**_semantic_change_impact_fields())
    ce.decide_recommendation(candidate)
    ce.persist_candidate(tmp_path, candidate)
    candidate = ce.transition(tmp_path, candidate, "EVIDENCE_GATHERING",
                              by="research-architect", reason="gathering internal replay evidence")
    ce.read_candidates(tmp_path)
    ce.candidate_audit_records(tmp_path)
    ce.human_approval_status(tmp_path)
    ce.stop_report_blockers({})

    after = _tree_fingerprint(ROOT / "dv_harness", ROOT / ".claude")
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert changed == [], f"the decision path modified repo files: {changed}"


def test_D_everything_persisted_lands_under_the_project_state_dir(tmp_path):
    """The positive half: it really did write, and everything it wrote is under
    <root>/.dv-harness/. A test that only proves 'nothing changed' would also
    pass if the module silently wrote nothing at all."""
    candidate = ce.build_candidate(**_semantic_change_impact_fields())
    ce.persist_candidate(tmp_path, candidate)

    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert written, "persist_candidate wrote nothing"
    for p in written:
        assert ".dv-harness" in p.relative_to(tmp_path).parts, p

    stored = ce.read_candidate(tmp_path, candidate["candidate_id"])
    assert stored["recommendation"] == "ENHANCE"
    assert stored["hypothesis"] == candidate["hypothesis"]


# --------------------------------------------------------------------------
# Stage-1 Acceptance Test E


def test_E_no_decision_vocabulary_can_be_read_as_a_verification_verdict():
    """Nothing this agent can emit may collide with dv_harness.models.Status.
    An LLM's reasoning must not be able to become a PASS by any path, including
    a string comparison in someone else's code."""
    ce.assert_no_verification_verdict_vocabulary()

    verdicts = {s.value for s in Status}
    assert "PASS" in verdicts  # the guard is checking a real vocabulary
    for vocabulary in (ce.RECOMMENDATIONS, ce.PROMOTION_STATES, ce.OVERLAP_STATUSES):
        assert not verdicts.intersection(vocabulary)


def test_E_the_module_never_names_a_verification_verdict_at_all():
    """Source-level: the module contains no PASS/FAIL verdict literal, imports
    no gate runner, and calls nothing that could record a stage verdict. This
    catches a future edit that adds such a path before it ships."""
    src = ce.__file__ and Path(ce.__file__).read_text(encoding="utf-8")
    code = "\n".join(
        line for line in src.splitlines()
        if not line.lstrip().startswith("#")
    )
    for forbidden in ('"PASS"', "'PASS'", '"FAIL"', "'FAIL'",
                      "run_gate", "evaluate_stage_evidence", "can_signoff",
                      "QualifiedConclusion", "signoff"):
        assert forbidden not in code, (
            f"capability_evolution.py references {forbidden!r} -- this module has no "
            "verification authority and must never acquire one"
        )


def test_E_decision_output_is_always_inside_its_own_closed_vocabulary():
    """Sweep the real decision function over every combination of the inputs it
    branches on. It must never return anything outside RECOMMENDATIONS, and in
    particular never a verdict-shaped token, whatever it is fed."""
    seen = set()
    for n_matches in range(0, 7):
        for conclusive in (True, False):
            for gap in ("", "something real is missing"):
                for counter in (0, 2):
                    for strength in (1, 4):
                        for reason in ("", "no existing asset to extend"):
                            slots = {}
                            for i, slot in enumerate(ce.L5_SEARCH_SLOTS):
                                slots[slot] = _search(
                                    ["some/real/asset.py"] if i < n_matches else [],
                                    "a real search basis",
                                    conclusive,
                                )
                            fields = _semantic_change_impact_fields(
                                exact_gap=gap,
                                enhance_insufficient_reason=reason,
                                evidence_strength={"scale": strength, "rationale": "r"},
                                confidence={"inputs": {
                                    "independent_sources_count": 3,
                                    "evidence_refs_verified": True,
                                    "counter_evidence_count": counter,
                                    "multi_agent_consensus_count": 0,
                                }},
                                **slots,
                            )
                            decision = ce.decide_recommendation(fields)
                            seen.add(decision["recommendation"])
                            assert decision["recommendation"] in ce.RECOMMENDATIONS
                            assert decision["overlap_status"] in ce.OVERLAP_STATUSES
    # The sweep really did exercise more than one branch.
    assert {"UNKNOWN", "KEEP", "ENHANCE", "ADD", "EXPERIMENT", "REJECT"} <= seen


def test_E_confidence_is_recomputed_never_believed():
    """self_tuning.classify_proposal() trusts an LLM's own "confidence": "HIGH"
    verbatim. This module must not: a stored level that does not re-derive from
    its own inputs is rejected."""
    candidate = ce.build_candidate(**_semantic_change_impact_fields(
        confidence={"inputs": {
            "independent_sources_count": 1,
            "evidence_refs_verified": True,
            "counter_evidence_count": 0,
            "multi_agent_consensus_count": 0,
        }}))
    # 1*2 + 2 = 4 -> MEDIUM, computed by the real formula, not stated.
    assert candidate["confidence"] == {
        **score_confidence(**candidate["confidence"]["inputs"]),
        "inputs": candidate["confidence"]["inputs"],
    }
    assert candidate["confidence"]["level"] == "MEDIUM"

    # The exact self-report self_tuning.classify_proposal() would have believed.
    candidate["confidence"]["level"] = "HIGH"
    with pytest.raises(ce.CapabilityEvolutionCandidateValidationError) as exc:
        ce.assert_confidence_recomputed(candidate)
    assert "not a claim this module accepts on trust" in str(exc.value)


# --------------------------------------------------------------------------
# Promotion policy (master prompt section 70)


def test_promotion_states_are_exactly_section_70s_eleven():
    assert ce.PROMOTION_STATES == (
        "DISCOVERED", "EVIDENCE_GATHERING", "PROPOSED", "EXPERIMENT_APPROVED",
        "EXPERIMENTING", "BENCHMARKED", "PROMOTION_CANDIDATE", "HUMAN_APPROVED",
        "PRODUCTION", "REJECTED", "ROLLED_BACK",
    )
    schema = json.loads(ce.CAPABILITY_EVOLUTION_CANDIDATE_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert tuple(schema["$defs"]["promotion_state"]["enum"]) == ce.PROMOTION_STATES


def test_governance_states_cannot_be_skipped():
    """"Do not skip governance states." A jump straight from DISCOVERED to
    PRODUCTION, or past the experiment states on a candidate that declares it
    needs one, raises."""
    with pytest.raises(ce.IllegalPromotionTransitionError):
        ce.assert_legal_transition("DISCOVERED", "PRODUCTION")
    with pytest.raises(ce.IllegalPromotionTransitionError):
        ce.assert_legal_transition("PROMOTION_CANDIDATE", "PRODUCTION")
    with pytest.raises(ce.IllegalPromotionTransitionError) as exc:
        ce.assert_legal_transition("PROPOSED", "PROMOTION_CANDIDATE",
                                   {"experiment_required": True})
    assert "experiment_required" in str(exc.value)
    # The one sanctioned bypass, and only for a candidate that declares it.
    ce.assert_legal_transition("PROPOSED", "PROMOTION_CANDIDATE", {"experiment_required": False})


def test_a_successful_experiment_does_not_imply_human_approved(tmp_path):
    """Section 70, stated verbatim: 'A successful experiment does not
    automatically imply HUMAN_APPROVED.' The gate is a real ControlPlane
    approval on disk, not a state the agent can write for itself.

    The experiment half of this path is REAL as of 2026-09-05: EXPERIMENTING ->
    BENCHMARKED runs run_controlled_experiment() against an isolated synthetic
    fixture and is refused without the record it produces, so 'a successful
    experiment' here is a measured one rather than the words 'before/after
    measured' typed into a reason field."""
    from .controlled_experiment_fixture import (
        make_fixture_project, run_demo_experiment, run_demo_replication)

    candidate = ce.build_candidate(**_semantic_change_impact_fields())
    for to_status, reason in (
        ("EVIDENCE_GATHERING", "gathering replay evidence"),
        ("PROPOSED", "evidence gathered"),
        ("EXPERIMENT_APPROVED", "experiment approved by the review"),
    ):
        candidate = ce.transition(tmp_path, candidate, to_status,
                                  by="research-architect", reason=reason)

    fixture = make_fixture_project(tmp_path / "experiment_fixture")
    measured = run_demo_experiment(tmp_path, candidate, fixture)["candidate"]
    assert measured["current_status"] == "BENCHMARKED"
    assert measured["benchmark_result"]["outcome"] == "IMPROVED"

    # Section 134's stability window: one successful shadow run is not enough to
    # reach PROMOTION_CANDIDATE, so a second REAL run is measured.
    replicated = run_demo_replication(tmp_path, measured, fixture)["candidate"]
    candidate = ce.transition(tmp_path, replicated, "PROMOTION_CANDIDATE",
                              by="research-architect", reason="acceptance criteria met")

    with pytest.raises(ce.HumanApprovalRequiredError) as exc:
        ce.transition(tmp_path, candidate, "HUMAN_APPROVED",
                      by="research-architect", reason="the benchmark passed")
    assert ce.HUMAN_APPROVAL_STAGE in str(exc.value)
    assert "dv-harness approve" in str(exc.value)

    # A REAL human approval through the REAL ControlPlane unblocks it, and the
    # candidate carries that approval record as its own evidence.
    ControlPlane(tmp_path).approve(
        ce.HUMAN_APPROVAL_STAGE, note="reviewed the replay benchmark",
        reviewer_id="dv-manager", reviewer_confidence="HIGH")
    candidate = ce.transition(tmp_path, candidate, "HUMAN_APPROVED",
                              by="research-architect", reason="the benchmark passed")
    assert candidate["current_status"] == "HUMAN_APPROVED"
    assert candidate["status_history"][-1]["approval_ref"]["reviewer_id"] == "dv-manager"


def test_no_production_write_is_authorized_before_human_approval(tmp_path):
    """The Stage 2/Stage 3 boundary as a callable check, for whatever future
    caller is about to touch a file."""
    candidate = ce.build_candidate(**_semantic_change_impact_fields())
    with pytest.raises(ce.ProductionWriteNotAuthorizedError):
        ce.assert_no_production_write_authorized(tmp_path, candidate)

    approved = dict(candidate, current_status="HUMAN_APPROVED")
    with pytest.raises(ce.HumanApprovalRequiredError):
        ce.assert_no_production_write_authorized(tmp_path, approved)

    ControlPlane(tmp_path).approve(ce.HUMAN_APPROVAL_STAGE, note="ok",
                                   reviewer_id="dv-manager", reviewer_confidence="HIGH")
    ce.assert_no_production_write_authorized(tmp_path, approved)


def test_status_history_is_append_only_and_records_every_state(tmp_path):
    candidate = ce.build_candidate(**_semantic_change_impact_fields())
    candidate = ce.transition(tmp_path, candidate, "EVIDENCE_GATHERING",
                              by="research-architect", reason="r1")
    candidate = ce.transition(tmp_path, candidate, "PROPOSED",
                              by="research-architect", reason="r2")
    assert [e["to_status"] for e in candidate["status_history"]] == [
        "DISCOVERED", "EVIDENCE_GATHERING", "PROPOSED"]
    assert candidate["status_history"][0]["from_status"] is None
    assert candidate["status_history"][-1]["from_status"] == "EVIDENCE_GATHERING"


# --------------------------------------------------------------------------
# Persistence: real Blackboard + real memory router, never a parallel store


def test_candidate_lands_on_the_real_blackboard_topic(tmp_path):
    candidate = ce.build_candidate(**_semantic_change_impact_fields())
    ce.persist_candidate(tmp_path, candidate)

    payload = Blackboard(tmp_path).read(ce.BLACKBOARD_TOPIC)
    assert payload["topic"] == "capability_evolution_candidates"
    assert candidate["candidate_id"] in payload["value"]["items"]
    counts = Blackboard(tmp_path).capability_evolution_counts()
    assert counts == {"total": 1, "by_status": {"DISCOVERED": 1}}


def test_candidate_audit_record_routes_to_working_memory_only(tmp_path):
    """The audit record goes through the REAL memory_router, and its
    destination is asserted to be WORKING_MEMORY. A single design session is
    not the repeated, human-approved evidence the Engineering or Organizational
    tier requires, so this pass must be structurally unable to reach them."""
    candidate = ce.build_candidate(**_semantic_change_impact_fields())
    result = ce.persist_candidate(tmp_path, candidate)
    assert result["memory"]["destination"] == "WORKING_MEMORY"

    records = ce.candidate_audit_records(tmp_path, candidate["candidate_id"])
    assert len(records) == 1
    assert records[0]["kind"] == "capability_evolution_candidate"
    assert records[0]["level"] == "working"
    # Never flagged verified: memory_router's engineering/organizational
    # admission gates must never see a truthy `verified` on one of these.
    assert not records[0].get("verified")

    store = MemoryStore(tmp_path)
    assert store.find("engineering") == []
    assert store.find("organizational") == []


def test_candidate_kind_can_never_route_above_job_memory():
    """The tier invariant this module actually depends on, asserted against the
    REAL route_memory() for every record shape this module can produce.

    This test used to assert something else: that no branch for
    CANDIDATE_MEMORY_KIND existed in route_memory() at all, on the theory that
    the kind reached WORKING_MEMORY through the function's fallthrough. That
    stopped being true -- section 12's memory-governance pass gave the kind a
    NAMED branch (memory_router.CAPABILITY_EVOLUTION_KINDS) which routes it to
    the same tier by decision instead of by default. The old assertion did not
    fail, which is the problem worth recording: it grepped route_memory()'s body
    for the literal kind string, and the branch refers to a module-level
    constant, so it kept passing while no longer proving its own docstring.

    A source grep was the wrong instrument regardless -- it constrained HOW the
    router is written rather than WHAT it decides. What this module needs is a
    destination guarantee, so that is what is asserted now, behaviourally:
    a candidate record never reaches Engineering or Organizational Memory, no
    matter which shape it carries or how route_memory() is refactored later.
    A single design/build session is not the repeated, human-approved evidence
    those two tiers require.
    """
    from dv_harness.memory_router import route_memory

    # The shape persist_candidate() actually writes: no job_id, no verified flag.
    assert route_memory({"kind": ce.CANDIDATE_MEMORY_KIND}) == "WORKING_MEMORY"

    # Every other shape a caller could hand it stays at or below Job Memory.
    # `verified: True` is the important one: on other kinds that flag is the
    # thing that unlocks the Engineering tier, and it must not do so here.
    for extra in (
        {},
        {"job_id": "JOB-1"},
        {"verified": True},
        {"verified": True, "confidence": "HIGH"},
        {"job_id": "JOB-1", "verified": True, "confidence": "HIGH"},
    ):
        record = {"kind": ce.CANDIDATE_MEMORY_KIND, **extra}
        destination = route_memory(record)
        assert destination in ("WORKING_MEMORY", "JOB_MEMORY"), (
            f"{extra} routed a capability-evolution candidate to {destination}; "
            "this kind must never reach Engineering or Organizational Memory"
        )


def test_candidate_id_is_stable_across_cycles_and_content_derived():
    """The one capability self_tuning.py has no counterpart for: an identical
    proposal re-derived in a later cycle lands on the SAME record instead of
    forking a duplicate."""
    args = ("verification-change-impact", "semantic delta shrinks regression",
            "extend change_impact.py")
    assert ce.mint_candidate_id(*args) == ce.mint_candidate_id(*args)
    assert re.fullmatch(r"CEC-[0-9a-f]{12}", ce.mint_candidate_id(*args))
    assert ce.mint_candidate_id("failure-triage", *args[1:]) != ce.mint_candidate_id(*args)
    with pytest.raises(ValueError):
        ce.mint_candidate_id("", "h", "a")


# --------------------------------------------------------------------------
# Section 43's mandatory stop


def test_stop_report_is_section_43s_exact_text():
    complete = {k: True for k in ce.STOP_REPORT_PRECONDITIONS}
    assert ce.render_stop_report(complete) == (
        "RESEARCH COMPLETE\n"
        "CURRENT L5 BASELINE COMPLETE\n"
        "RESEARCH-INGESTION OPERATIONAL\n"
        "RESEARCH-ARCHITECT OPERATIONAL\n"
        "L5.x PROPOSAL COMPLETE\n"
        "IMPLEMENTATION NOT STARTED\n"
        "AWAITING HUMAN APPROVAL\n"
        "\n"
        "STOP."
    )


def test_stop_report_refuses_to_claim_completeness_it_does_not_have():
    partial = {k: True for k in ce.STOP_REPORT_PRECONDITIONS}
    partial["benchmark_plan_complete"] = False
    with pytest.raises(ce.CapabilityEvolutionCandidateValidationError) as exc:
        ce.render_stop_report(partial)
    assert "benchmark_plan_complete" in str(exc.value)
    assert ce.stop_report_blockers({}) == list(ce.STOP_REPORT_PRECONDITIONS)


# --------------------------------------------------------------------------
# The inference.py extension: additive, and every existing caller unaffected


def test_next_best_action_registry_path_is_unchanged_without_the_new_parameter():
    """The three-positional-argument call every existing caller makes behaves
    exactly as before -- same result, same `source` values."""
    gaps = ["rtl_evidence", "totally_unrelated_gap_string"]
    assert next_best_action("USB", gaps, ROOT) == next_best_action(
        "USB", gaps, ROOT, gap_action_catalog=None)
    for entry in next_best_action("USB", gaps, ROOT):
        assert entry["source"] in ("protocol_builder_registry", "generic")


def test_next_best_action_catalog_branch_reads_no_file_and_validates_its_input():
    catalog = {"source": "unit_test", "actions": {"alpha": "do alpha"},
               "fallback": "nothing registered for {gap}"}
    out = next_best_action("ignored", ["alpha", "beta"], None, gap_action_catalog=catalog)
    assert out == [
        {"gap": "alpha", "suggested_action": "do alpha", "source": "unit_test"},
        {"gap": "beta", "suggested_action": "nothing registered for beta", "source": "generic"},
    ]
    for bad in ({}, {"source": "s"}, {"source": "", "actions": {}, "fallback": "f"},
                {"source": "s", "actions": {"a": 1}, "fallback": "f"}, "not a dict"):
        with pytest.raises(ValueError):
            next_best_action("p", ["alpha"], None, gap_action_catalog=bad)


def test_memory_store_find_is_the_shared_query_the_audit_asked_for(tmp_path):
    store = MemoryStore(tmp_path)
    store.add("project", {"kind": "self_tuning_adjustment", "status": "REVERTED", "gate_id": "g1"})
    store.add("project", {"kind": "self_tuning_adjustment", "status": "APPLIED", "gate_id": "g2"})
    store.add("working", {"kind": "capability_evolution_candidate", "candidate_id": "CEC-1"})

    reverted = store.find("project", kind="self_tuning_adjustment", status="REVERTED")
    assert [r["gate_id"] for r in reverted] == ["g1"]
    assert len(store.find("project", kind="self_tuning_adjustment")) == 2
    assert len(store.find(kind="self_tuning_adjustment")) == 2
    assert store.find("working", kind="capability_evolution_candidate")[0]["candidate_id"] == "CEC-1"
    with pytest.raises(ValueError):
        store.find("not-a-tier")


# --------------------------------------------------------------------------
# The agent profile is held to the code it cites


def test_research_architect_profile_exists_and_is_read_only_of_production():
    from dv_harness.agent_profile import load_agent_profile

    profile = load_agent_profile(ROOT, "research-architect")
    assert profile is not None and profile.found
    # It decides; it does not implement. Tool scope is what actually enforces
    # separation of duties in this repo -- every artifact it produces is
    # persisted by real harness code, never hand-written.
    assert "Edit" in profile.disallowed_tools
    assert "Write" in profile.disallowed_tools


def test_research_architect_profile_cites_only_real_assets():
    text = (ROOT / ".claude" / "agents" / "research-architect.md").read_text(encoding="utf-8")
    for cited in (
        "dv_harness/capability_evolution.py",
        "dv_harness/inference.py",
        "dv_harness/schemas/capability_evolution_candidate.schema.json",
        ".claude/skills/research-ingestion/SKILL.md",
        "dv_harness/control_plane.py",
        "dv_harness/change_impact.py",
    ):
        assert cited in text, f"profile does not cite {cited}"
        assert (ROOT / cited).exists(), f"profile cites {cited}, which does not exist"
    # Every function name the profile names must be real.
    for fn in ("decide_recommendation", "build_candidate", "persist_candidate",
               "assert_human_approval", "render_stop_report", "transition"):
        assert fn in text
        assert hasattr(ce, fn), f"profile names {fn}(), which capability_evolution.py lacks"


def test_roster_records_research_architect_honestly():
    """ROSTER.md's own contract: a NOT_DISPATCHED profile must say how its
    role-shaped work really runs. The dispatch-status agreement itself is
    checked by test_agent_dispatch_map.py; this asserts the honesty note."""
    from dv_harness.agent_dispatch import agent_dispatch_map

    info = agent_dispatch_map(ROOT)["research-architect"]
    assert info["status"] == "NOT_DISPATCHED"
    roster = (ROOT / ".claude" / "agents" / "ROSTER.md").read_text(encoding="utf-8")
    entry = roster.split("**research-architect** -- Dispatch:")[1].split("** -- Dispatch:")[0]
    assert "How this role really runs" in entry
    assert "capability_evolution.py" in entry
