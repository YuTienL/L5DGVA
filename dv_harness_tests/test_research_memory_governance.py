"""5-Level Memory governance for research / capability-evolution records, and
the Three Autonomy Levels' LEVEL C enforcement citations.

Two things are proven here, both against REAL code -- the real
`memory_router.route_memory()` / `route_and_store()` / admission gates, a real
`MemoryStore` on a real tmp_path, a real `ControlPlane`, and a real
`doc_extraction.build_research_evidence_card_skeleton()` card built from a real
file on disk. Nothing is mocked, because what is being asserted is precisely
that these mechanisms refuse things, and a mock cannot refuse.

1. MEMORY GOVERNANCE (master prompt sections 12/71/72). The four research
   `kind` strings route through the SAME dispatch function every other kind
   uses, and land at Working or Job tier. Reaching Engineering or Organizational
   requires clearing a bar that a single freshly-ingested paper card cannot
   clear from inside itself -- **Stage 1 Acceptance Test H**, which is
   `test_acceptance_h_*` below.

   The important half is the LAUNDERING case, not the happy path: a caller who
   relabels a ResearchEvidenceCard's `kind` to `methodology`/`debug_lesson` and
   sets `verified: true` is the realistic way research content would reach a
   durable tier by accident, and the gates recognize the record by its FIELD
   SHAPE rather than by the kind string it was handed.

2. LEVEL C CITATIONS (master prompt section 61). `autonomy_levels.
   LEVEL_C_ENFORCEMENT` claims specific real mechanisms enforce specific LEVEL C
   examples. Those claims are checked against the real modules here, so a
   renamed or deleted guard fails a test instead of leaving a confident,
   false table behind. The five rows that claim NOTHING enforces them are
   asserted to be exactly the five that were found unenforced, so silently
   shrinking that list is also a test failure.
"""
from pathlib import Path

import pytest

from dv_harness import autonomy_levels as al
from dv_harness import capability_evolution as ce
from dv_harness import memory_router as mr
from dv_harness import doc_extraction as dx
from dv_harness.control_plane import ControlPlane
from dv_harness.memory import MemoryStore


# --------------------------------------------------------------------------
# Helpers -- real records, real card, no fixtures that hide what is asserted


def _research_card_record(tmp_path, *, kind="research_evidence", **extra):
    """A memory record carrying a REAL ResearchEvidenceCard skeleton's identity
    fields, built by the real doc_extraction path from a real file."""
    doc = tmp_path / "sources" / "some_conference_paper.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("# A paper\n\nIt claims a thing.\n", encoding="utf-8")
    card = dx.build_research_evidence_card_skeleton(doc, tmp_path)

    record = {
        "kind": kind,
        "document_id": card["document_id"],
        "source_provenance": card["source_provenance"],
        "document_sha256": card["document_sha256"],
        "claim_set": [{"claim": "technique X cuts debug time", "classification": "AUTHOR_CLAIM"}],
    }
    record.update(extra)
    return record


def _fully_evidenced_engineering_shape(**extra):
    """A record that clears engineering_admission_gate()'s ORIGINAL three gates
    outright -- real evidence, HIGH confidence, a reusable claim. Used to prove
    the research bar is a FOURTH check and not a restatement of those three."""
    record = {
        "kind": "debug_lesson",
        "verified": True,
        "evidence": "sim.log:4412 UVM_ERROR, waveform tb.dut.u_phy:1.2ms",
        "confidence": "HIGH",
        "lesson": "arm the interrupt before releasing reset",
    }
    record.update(extra)
    return record


def _gate_validated_verification():
    """MemoryConsolidator.from_closed_finding()'s real shape -- one of the two
    _verification_is_gate_validated() recognizes. Not a third invented shape."""
    return {"single_sim": "PASS", "regression": "PASS", "reaudit": "CLEAN"}


# --------------------------------------------------------------------------
# route_memory(): the research kinds are in the REAL dispatch table


@pytest.mark.parametrize("kind", mr.RESEARCH_EVIDENCE_KINDS + mr.CAPABILITY_EVOLUTION_KINDS)
def test_research_kinds_start_at_working_memory(kind):
    assert mr.route_memory({"kind": kind}) == "WORKING_MEMORY"


@pytest.mark.parametrize("kind", mr.RESEARCH_EVIDENCE_KINDS + mr.CAPABILITY_EVOLUTION_KINDS)
def test_research_kinds_reach_job_memory_only_with_a_real_job_id(kind):
    """Section 12's Job tier is literally "the current research-ingestion
    execution"; a blank or whitespace job_id is not one."""
    assert mr.route_memory({"kind": kind, "job_id": "JOB-77"}) == "JOB_MEMORY"
    assert mr.route_memory({"kind": kind, "job_id": ""}) == "WORKING_MEMORY"
    assert mr.route_memory({"kind": kind, "job_id": "   "}) == "WORKING_MEMORY"


@pytest.mark.parametrize("kind", mr.RESEARCH_EVIDENCE_KINDS + mr.CAPABILITY_EVOLUTION_KINDS)
def test_verified_flag_does_not_lift_a_research_kind(kind):
    """`verified: true` is what unlocks the Engineering tier for root_cause /
    verified_fix / debug_lesson. On a research kind it must do nothing at all:
    "the paper says so" and "this harness verified it" are the exact two things
    section 12 separates, and a caller setting the flag cannot merge them."""
    for extra in ({"verified": True}, {"verified": True, "job_id": "JOB-9"},
                  {"verified": True, "confidence": "HIGH"}):
        destination = mr.route_memory({"kind": kind, **extra})
        assert destination in ("WORKING_MEMORY", "JOB_MEMORY"), (kind, extra, destination)


def test_architecture_decision_ceiling_is_project_memory():
    """PROJECT_MEMORY is the ceiling for this kind, not a waypoint. Section 12
    also lists architecture decision history under Organizational Memory, but
    section 72 reserves that tier for human-approved governance decisions."""
    assert mr.route_memory({"kind": "architecture_decision"}) == "WORKING_MEMORY"
    assert mr.route_memory({"kind": "architecture_decision", "verified": True}) == "PROJECT_MEMORY"


@pytest.mark.parametrize("kind", mr.RESEARCH_ORIGIN_KINDS)
def test_no_research_kind_can_name_a_durable_tier_directly(kind):
    """The destination guarantee, asserted behaviourally across every shape a
    caller could hand the router -- not by grepping route_memory()'s source,
    which would constrain how it is written rather than what it decides."""
    shapes = (
        {}, {"verified": True}, {"job_id": "JOB-1"}, {"confidence": "HIGH"},
        {"verified": True, "confidence": "HIGH", "job_id": "JOB-1",
         "evidence": "the paper's own abstract", "lesson": "do the thing"},
    )
    for extra in shapes:
        destination = mr.route_memory({"kind": kind, **extra})
        assert destination not in ("ENGINEERING_MEMORY", "ORGANIZATIONAL_MEMORY"), (kind, extra)


def test_research_kinds_did_not_disturb_any_existing_routing():
    """The neighbouring branches still answer exactly as before. Adding kinds to
    a shared dispatch function is only safe if this stays true."""
    assert mr.route_memory({"kind": "credential"}) == "REJECT"
    assert mr.route_memory({"kind": "active_hypothesis"}) == "BLACKBOARD"
    assert mr.route_memory({"kind": "job_result"}) == "JOB_MEMORY"
    assert mr.route_memory({"kind": "react_reasoning_step"}) == "WORKING_MEMORY"
    assert mr.route_memory({"kind": "project_fact", "verified": True}) == "PROJECT_MEMORY"
    assert mr.route_memory({"kind": "root_cause", "verified": True}) == "ENGINEERING_MEMORY"
    assert mr.route_memory({"kind": "methodology", "verified": True}) == "ORGANIZATIONAL_MEMORY"
    assert mr.route_memory({"kind": "corner_case", "verified": True}) == "CORNER_CASE_LIBRARY"
    assert mr.route_memory({"kind": "anything_unrecognized"}) == "WORKING_MEMORY"


# --------------------------------------------------------------------------
# Research-origin detection: by FIELD SHAPE, not by the kind string


def test_research_origin_survives_relabelling_the_kind(tmp_path):
    """The laundering path, one edit wide: relabel the kind and the card's
    identity fields are still on the record. If detection keyed on `kind` alone
    this record would pass as ordinary DV engineering content."""
    record = _research_card_record(tmp_path, kind="debug_lesson")
    assert mr.is_research_origin(record) is True
    signals = mr.research_provenance_signals(record)
    assert "FIELD:document_id" in signals
    assert "FIELD:source_provenance" in signals
    assert "FIELD:claim_set" in signals
    # ...and the kind signal is absent, which is the point: field shape alone
    # is sufficient, so shedding the kind sheds nothing.
    assert not any(s.startswith("KIND:") for s in signals)


def test_ordinary_dv_engineering_content_is_not_research_origin():
    """The false-positive half. A gate that flags everything protects nothing,
    because it gets switched off."""
    assert mr.is_research_origin(_fully_evidenced_engineering_shape()) is False
    assert mr.research_provenance_signals(_fully_evidenced_engineering_shape()) == []


def test_capability_evolution_trigger_type_is_a_research_signal():
    assert mr.is_research_origin({"kind": "note", "trigger_type": "EXTERNAL_RESEARCH"}) is True
    assert mr.is_research_origin({"kind": "note", "candidate_id": "CEC-abc123"}) is True


# --------------------------------------------------------------------------
# STAGE 1 ACCEPTANCE TEST H
# A single freshly-ingested ResearchEvidenceCard cannot reach Organizational.


def test_acceptance_h_fresh_card_cannot_reach_organizational_memory(tmp_path):
    """Acceptance Test H, driven through the REAL router end to end.

    The record is deliberately given every advantage a determined caller could
    give it: the `methodology` kind that route_memory() really does send to
    ORGANIZATIONAL_MEMORY, `verified: true`, a gate-validated verification block
    in a shape _verification_is_gate_validated() really accepts, and HIGH
    confidence. It still must not land there, because it is one paper, ingested
    once, that this harness has never reproduced.
    """
    record = _research_card_record(
        tmp_path,
        kind="methodology",
        verified=True,
        confidence="HIGH",
        evidence="section 4 of the paper",
        lesson="adopt technique X",
        verification=_gate_validated_verification(),
    )
    assert mr.route_memory(record) == "ORGANIZATIONAL_MEMORY"

    result = mr.route_and_store(tmp_path, record, cfg={})

    assert result["destination"] == "WORKING_MEMORY"
    # The demotion carries its own reason codes, so a reader of the Working
    # Memory record can see exactly what was missing rather than finding a
    # record that merely happens to be sitting one tier down.
    admission = result["organizational_admission"]
    assert admission["admitted"] is False
    assert "RESEARCH_ORIGIN_REQUIRES_HUMAN_APPROVAL" in admission["reasons"]
    store = MemoryStore(tmp_path)
    assert store.find("organizational") == []
    assert store.find("engineering") == []


def test_acceptance_h_rejection_names_the_missing_authority(tmp_path):
    """WHY it was refused, not just that it was. Section 72 is an AUTHORITY
    rule, so the reason must be about a human decision, never about evidence
    quality -- the three ordinary evidence gates are separately satisfied here."""
    record = _research_card_record(
        tmp_path, kind="methodology", verified=True, confidence="HIGH",
        evidence="section 4", lesson="adopt X", verification=_gate_validated_verification(),
    )
    admitted, reasons = mr.organizational_admission_gate(tmp_path, record)
    assert admitted is False
    assert "RESEARCH_ORIGIN_REQUIRES_HUMAN_APPROVAL" in reasons


def test_acceptance_h_a_self_written_approval_block_is_not_an_approval(tmp_path):
    """A record that CONTAINS an approval-shaped dict is a record that wrote its
    own approval. The gate re-reads the live ControlPlane instead."""
    record = _research_card_record(
        tmp_path, kind="methodology", verified=True, confidence="HIGH",
        evidence="section 4", lesson="adopt X", verification=_gate_validated_verification(),
        human_approval={"stage": ce.HUMAN_APPROVAL_STAGE, "reviewer_id": "definitely-a-human"},
    )
    reasons = mr.research_organizational_admission_reasons(tmp_path, record)
    assert reasons == ["RESEARCH_HUMAN_APPROVAL_NOT_ON_RECORD"]

    # And with a REAL approval on disk through the real ControlPlane, the
    # research authority reason clears -- proving the check reads live state
    # rather than simply always refusing.
    ControlPlane(tmp_path).approve(
        ce.HUMAN_APPROVAL_STAGE, note="reviewed the candidate",
        reviewer_id="a-real-human", reviewer_confidence="HIGH",
    )
    assert mr.research_organizational_admission_reasons(tmp_path, record) == []


def test_acceptance_h_holds_for_every_research_evidence_kind(tmp_path):
    """Not just the one card shape above: no research kind reaches the
    organizational tier through route_and_store() on a fresh project."""
    for kind in mr.RESEARCH_ORIGIN_KINDS:
        record = _research_card_record(tmp_path, kind=kind, verified=True, confidence="HIGH")
        result = mr.route_and_store(tmp_path, record, cfg={})
        assert result["destination"] in ("WORKING_MEMORY", "JOB_MEMORY", "PROJECT_MEMORY"), (
            kind, result["destination"])
    assert MemoryStore(tmp_path).find("organizational") == []


# --------------------------------------------------------------------------
# Engineering tier: the FOURTH bar, and why the original three cannot see it


def test_engineering_gate_original_three_pass_but_research_bar_refuses(tmp_path):
    """The load-bearing assertion of this whole pass. The SAME record body
    clears engineering_admission_gate() outright when it is ordinary DV content,
    and is refused when the card's identity fields are on it -- so the research
    bar is demonstrably a fourth, independent check and not a re-run of the
    three."""
    ordinary = _fully_evidenced_engineering_shape()
    admitted, reasons = mr.engineering_admission_gate(ordinary, root=tmp_path)
    assert (admitted, reasons) == (True, [])

    laundered = _research_card_record(tmp_path, kind="debug_lesson")
    laundered.update({k: v for k, v in ordinary.items() if k != "kind"})
    admitted, reasons = mr.engineering_admission_gate(laundered, root=tmp_path)
    assert admitted is False
    assert "RESEARCH_SINGLE_SOURCE_CLAIM" in reasons
    assert "RESEARCH_NO_INTERNAL_VALIDATION" in reasons
    # None of the ORIGINAL three reason codes fired -- they were all satisfied.
    assert not {"NOT_VERIFIED", "NO_EVIDENCE", "CONFIDENCE_TOO_LOW", "NO_REUSABLE_CLAIM"} & set(reasons)


def test_engineering_gate_without_root_fails_rather_than_skips(tmp_path):
    """`root` is optional so the signature stays a drop-in for every existing
    caller. Omitting it must not become a way to skip the research bar: an
    unverifiable corroboration claim is not a corroboration."""
    laundered = _research_card_record(tmp_path, kind="debug_lesson")
    laundered.update(_fully_evidenced_engineering_shape())
    admitted, reasons = mr.engineering_admission_gate(laundered)
    assert admitted is False
    assert "RESEARCH_PROVENANCE_UNVERIFIABLE" in reasons


def test_the_same_paper_cited_twice_is_still_one_source(tmp_path):
    """`corroborating_memory_ids` is re-read off the real store and counted by
    DISTINCT source document. Two ids that resolve to the same paper are one
    occurrence, which is exactly the "never a single occurrence" rule."""
    store = MemoryStore(tmp_path)
    card = _research_card_record(tmp_path)
    first = store.add("working", dict(card))
    second = store.add("working", dict(card))  # same document_id, different memory_id

    record = _research_card_record(tmp_path, kind="debug_lesson")
    record.update(_fully_evidenced_engineering_shape())
    record["corroborating_memory_ids"] = [first["memory_id"], second["memory_id"]]
    record["verification"] = _gate_validated_verification()

    reasons = mr.research_engineering_admission_reasons(tmp_path, record)
    assert "RESEARCH_SINGLE_SOURCE_CLAIM" in reasons
    assert "RESEARCH_NO_INTERNAL_VALIDATION" not in reasons  # that half really is satisfied


def test_two_distinct_sources_plus_internal_validation_admits(tmp_path):
    """The positive path, so the bar is proven CLEARABLE rather than merely
    strict -- a gate nothing can ever pass is a gate somebody deletes.

    The second source is an INTERNAL record with no external document, which is
    the independent second source section 71's lifecycle actually asks for: this
    harness having re-derived the claim itself.
    """
    store = MemoryStore(tmp_path)
    paper = store.add("working", _research_card_record(tmp_path))
    internal = store.add("engineering", {
        "kind": "root_cause", "verified": True, "protocol": "USB",
        "root_cause": "reset released before interrupt arm",
        "evidence": "sim.log:9001", "confidence": "HIGH",
    })

    record = _research_card_record(tmp_path, kind="debug_lesson")
    record.update(_fully_evidenced_engineering_shape())
    record["corroborating_memory_ids"] = [paper["memory_id"], internal["memory_id"]]
    record["verification"] = _gate_validated_verification()

    assert mr.research_engineering_admission_reasons(tmp_path, record) == []
    admitted, reasons = mr.engineering_admission_gate(record, root=tmp_path)
    assert (admitted, reasons) == (True, [])


def test_an_internal_benchmark_is_the_other_way_to_satisfy_validation(tmp_path):
    """Section 69's before/after benchmark. All four fields are required
    together -- a metric with no before/after is a name, and a before/after with
    no evidence pointer is a number nobody can re-derive."""
    record = _research_card_record(tmp_path, kind="debug_lesson")
    record.update(_fully_evidenced_engineering_shape())

    record["internal_benchmark"] = {"metric": "debug_hours", "before": "6", "after": "2"}
    assert "RESEARCH_NO_INTERNAL_VALIDATION" in mr.research_engineering_admission_reasons(
        tmp_path, record)

    record["internal_benchmark"]["evidence"] = ".dv-harness/telemetry/stages/DEBUG.json"
    assert "RESEARCH_NO_INTERNAL_VALIDATION" not in mr.research_engineering_admission_reasons(
        tmp_path, record)


def test_a_dead_corroborating_id_counts_for_nothing(tmp_path):
    """Ids that resolve to nothing, or to a non-ACTIVE record, are not sources."""
    store = MemoryStore(tmp_path)
    record = _research_card_record(tmp_path, kind="debug_lesson")
    record.update(_fully_evidenced_engineering_shape())
    record["verification"] = _gate_validated_verification()
    record["corroborating_memory_ids"] = ["MEM-DOESNOTEXIST", "MEM-ALSONOTREAL"]
    assert "RESEARCH_SINGLE_SOURCE_CLAIM" in mr.research_engineering_admission_reasons(
        tmp_path, record)
    assert store.find("engineering") == []


def test_research_bar_reuses_the_organizational_confirmation_constant():
    """The corroboration count is ORGANIZATIONAL_MIN_CONFIRMATIONS itself, not a
    research-specific number -- one bar, not a second looser one invented for
    research. Asserted so a future edit cannot quietly fork them."""
    import inspect
    source = inspect.getsource(mr.research_engineering_admission_reasons)
    assert "ORGANIZATIONAL_MIN_CONFIRMATIONS" in source
    assert mr.ORGANIZATIONAL_MIN_CONFIRMATIONS == 2


# --------------------------------------------------------------------------
# THREE AUTONOMY LEVELS -- LEVEL C enforcement citations (section 61)


def test_level_c_examples_are_section_61s_nine_verbatim():
    assert al.LEVEL_C_EXAMPLES == (
        "merging to main",
        "changing default production workflow",
        "changing signoff policy",
        "changing verification oracle semantics",
        "changing regression selection policy used for signoff",
        "changing shared schemas with production impact",
        "changing organizational verification policy",
        "enabling new autonomous destructive actions",
        "changing remote execution/security policy",
    )


def test_every_level_c_example_has_a_reviewed_enforcement_verdict():
    assert set(al.LEVEL_C_ENFORCEMENT) == set(al.LEVEL_C_EXAMPLES)
    for example, entry in al.LEVEL_C_ENFORCEMENT.items():
        assert entry["status"] in ("ENFORCED", "PARTIAL", "NONE"), example
        assert entry["mechanism"].strip(), example


def test_level_c_citations_resolve_against_the_real_modules():
    """The whole point of citing importable symbols rather than writing prose: a
    guard that is renamed or deleted fails here instead of leaving a confident,
    false claim of enforcement in the source tree."""
    al.assert_level_c_citations_resolve()


def test_merging_to_main_really_is_enforced():
    """Spot-check the ENFORCED row against the real module rather than trusting
    the table's own summary of it."""
    from dv_harness import git_governance

    assert al.LEVEL_C_ENFORCEMENT["merging to main"]["status"] == "ENFORCED"
    assert git_governance.PROTECTED_BRANCHES == ("main", "master")
    assert git_governance.is_protected_branch("main") is True
    assert git_governance.is_protected_branch("master") is True
    assert git_governance.is_protected_branch("gap-close/whatever") is False


def test_signoff_policy_row_matches_what_protected_removals_really_covers():
    """The PARTIAL row claims PROTECTED_REMOVALS covers every PROMOTION_READINESS
    and SIGNOFF gate. Checked against the real STAGE_GATES table, because that is
    a claim about coverage and coverage claims go stale silently."""
    from dv_harness import gates, self_tuning

    assert al.LEVEL_C_ENFORCEMENT["changing signoff policy"]["status"] == "PARTIAL"
    for stage in ("PROMOTION_READINESS", "SIGNOFF"):
        stage_gates = gates.STAGE_GATES.get(stage, [])
        assert stage_gates, stage
        for entry in stage_gates:
            assert (stage, entry[0]) in self_tuning.PROTECTED_REMOVALS, (stage, entry[0])
            assert self_tuning.propose_remove_override(Path("."), stage, entry[0]) is False


def test_regression_selection_row_is_honestly_not_the_submission_row():
    """The NONE verdict for "regression selection policy used for signoff" rests
    on PROTECTED_PARAMETERS covering regression SUBMISSION, a different policy.
    Asserted here so the two are never conflated into a false ENFORCED."""
    from dv_harness import self_tuning

    assert al.LEVEL_C_ENFORCEMENT[
        "changing regression selection policy used for signoff"]["status"] == "NONE"
    protected_gate_ids = {gate_id for (gate_id, _param) in self_tuning.PROTECTED_PARAMETERS}
    assert "regression_submission_policy_gate" in protected_gate_ids
    # The selection policy's real home carries no protected entry at all.
    assert not any("change_impact" in g or "regression_tier" in g for g in protected_gate_ids)


def test_the_unenforced_level_c_items_are_named_and_derived():
    """Five LEVEL C examples have no ITEM-SPECIFIC enforcement today. They are
    flagged, not closed: building production-safety enforcement in the same pass
    that decided it was needed would ship a safety mechanism nobody independently
    reviewed. Pinning the list here means quietly shrinking it is a test failure,
    and honestly closing one is a deliberate edit to both the table and this
    test."""
    assert al.LEVEL_C_UNENFORCED == (
        "changing default production workflow",
        "changing verification oracle semantics",
        "changing regression selection policy used for signoff",
        "changing shared schemas with production impact",
        "changing remote execution/security policy",
    )
    # Derived from the table, never hand-listed beside it.
    assert al.LEVEL_C_UNENFORCED == tuple(
        e for e in al.LEVEL_C_EXAMPLES if al.LEVEL_C_ENFORCEMENT[e]["status"] == "NONE")
    for example in al.LEVEL_C_UNENFORCED:
        assert "OPEN GAP" in al.LEVEL_C_ENFORCEMENT[example]["residual"], example


def test_level_c_report_renders_the_unenforced_items():
    report = al.level_c_enforcement_report()
    for example in al.LEVEL_C_EXAMPLES:
        assert example in report
    assert "NO item-specific enforcement today" in report


def test_the_autonomy_levels_are_documented_at_the_enforcement_points():
    """Section 61 is documented in real source, at the code that enforces it --
    not only in a markdown file a reader of this code would never open.

    Three enforcement points, checked separately because they are three
    different claims:
      * capability_evolution.py -- the LEVEL B -> LEVEL C boundary, carrying the
        narrative immediately above the two functions that enforce it;
      * git_governance.py -- LEVEL C example 1;
      * self_tuning.py -- LEVEL C example 3's real (partial) enforcement.
    """
    ce_source = Path(ce.__file__).read_text(encoding="utf-8")
    assert "THE THREE AUTONOMY LEVELS" in ce_source
    for marker in ("LEVEL A -- RESEARCH AUTONOMY",
                   "LEVEL B -- EXPERIMENT AUTONOMY",
                   "LEVEL C -- PRODUCTION PROMOTION"):
        assert marker in ce_source, marker
    # Level A's binding constraint, on the module whose work is all Level A.
    assert "MUST NOT MODIFY" in ce_source
    # Both LEVEL C enforcement functions carry the level in their own docstring.
    assert "LEVEL C" in (ce.assert_human_approval.__doc__ or "")
    assert "LEVEL C" in (ce.assert_no_production_write_authorized.__doc__ or "")

    al_source = Path(al.__file__).read_text(encoding="utf-8")
    for marker in ("LEVEL A -- RESEARCH AUTONOMY",
                   "LEVEL B -- EXPERIMENT AUTONOMY",
                   "LEVEL C -- PRODUCTION PROMOTION"):
        assert marker in al_source, marker
    # Level B's easily-forgotten SECOND constraint, not just its first.
    assert "NEVER bypasses" in al_source
    assert "ISOLATED and REVERSIBLE" in al_source

    from dv_harness import git_governance, self_tuning
    assert "AUTONOMY LEVEL C" in Path(git_governance.__file__).read_text(encoding="utf-8")
    assert "AUTONOMY LEVEL C" in Path(self_tuning.__file__).read_text(encoding="utf-8")


def test_the_level_c_table_lives_where_it_does_not_weaken_an_existing_guard():
    """Acceptance Test E scans capability_evolution.py's non-comment source for
    verdict/signoff vocabulary, so that module can never quietly acquire
    verification authority. Section 61's own example wording contains exactly
    that vocabulary, so the table lives in autonomy_levels.py instead of
    weakening the guard to accommodate it. Asserted here so a later edit does
    not "simplify" by moving the table back and relaxing Acceptance Test E.
    """
    ce_code = "\n".join(
        line for line in Path(ce.__file__).read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    for forbidden in ("signoff", "can_signoff", '"PASS"', "'PASS'"):
        assert forbidden not in ce_code, forbidden
    # The vocabulary really is present in the table's actual home.
    assert "changing signoff policy" in al.LEVEL_C_EXAMPLES


def test_level_c_boundary_still_actually_refuses(tmp_path):
    """The documentation above is only worth anything if the gate under it still
    bites. A benchmarked candidate with no human approval may not touch
    production -- section 61's closing line, as a real raise."""
    candidate = {"candidate_id": "CEC-test", "current_status": "BENCHMARKED"}
    with pytest.raises(ce.ProductionWriteNotAuthorizedError):
        ce.assert_no_production_write_authorized(tmp_path, candidate)

    candidate["current_status"] = "HUMAN_APPROVED"
    with pytest.raises(ce.HumanApprovalRequiredError):
        ce.assert_no_production_write_authorized(tmp_path, candidate)

    ControlPlane(tmp_path).approve(
        ce.HUMAN_APPROVAL_STAGE, note="approved for Stage 3",
        reviewer_id="a-real-human", reviewer_confidence="HIGH")
    ce.assert_no_production_write_authorized(tmp_path, candidate)
