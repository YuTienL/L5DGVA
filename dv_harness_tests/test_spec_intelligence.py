"""Tests for dv_harness/spec_intelligence.py.

Because actual spec-prose extraction depends on an LLM reading a real
document, these tests validate the SCHEMA and the mechanical
validation/re-derivation gate -- never a claim that this module itself
"understood" a spec. Extraction documents below are hand-constructed
fixtures, exactly as this module's own docstring says its tests must be.

The one genuinely mechanical, real (non-LLM) piece -- SpecMap, layered on
`vip_user_guide_distill.py` -- IS driven end to end over real synthetic
`.txt` fixtures, because that half of the module really does compute
something from a real document rather than validate an agent's claim.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import spec_intelligence as si

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# Fixture builders
# --------------------------------------------------------------------------

def _req(rid: str, **overrides) -> dict:
    base = {
        "contract_schema_version": "1.0",
        "requirement_id": rid,
        "source": {"document": "spec.txt", "locator": "4.3.1",
                   "quote": "The link shall enter U1 within 10us of the LFPS handshake."},
        "feature": "LFPS handshake timing",
        "protocol": "USB3",
        "configuration": "NONE",
        "precondition": "NONE",
        "stimulus": "Assert LFPS on both TX lanes",
        "expected_result": "Link enters U1 within 10us",
        "observability": "link_state signal",
        "checker": "link_state_checker",
        "coverage_intent": "cover LFPS entry timing",
        "priority": "P1",
        "criticality": "MAJOR",
        "confidence": "HIGH",
        "status": "COMPLETE",
        "extraction_id": f"X-{rid}",
        "derivation": "EXPLICIT",
    }
    base.update(overrides)
    return base


def _doc(atomic=None, relations=None, provenance="AGENT_SELF_ATTESTED", **extra) -> dict:
    d = {
        "schema_version": "1.0",
        "evidence_provenance": provenance,
        "atomic_requirements": atomic or [],
        "relations": relations or [],
    }
    d.update(extra)
    return d


def _errors(result: dict):
    return [f for f in result["findings"] if f["severity"] == "ERROR"]


def _codes(result: dict):
    return {f["code"] for f in result["findings"]}


# --------------------------------------------------------------------------
# Positive control
# --------------------------------------------------------------------------

def test_clean_document_passes_with_no_findings():
    r1 = _req("R-1")
    doc = _doc(atomic=[r1])
    result = si.analyze_spec_extraction(doc)
    assert result["status"] == "PASS"
    assert result["findings"] == []
    assert result["atomic_requirement_count"] == 1
    assert result["dependency_graph"]["nodes"] == ["R-1"]


def test_clean_document_with_valid_refines_relation_passes():
    general = _req("R-1", feature="Link recovery", stimulus="Any recoverable error",
                    expected_result="Link recovers to U0")
    specific = _req("R-2", feature="Link recovery on CRC error",
                     stimulus="Inject a single CRC error", expected_result="Link recovers to U0 within 1ms")
    rel = {"from_requirement_id": "R-2", "to_requirement_id": "R-1", "kind": "REFINES",
           "rationale": "R-2 is a more specific case of R-1's general recovery requirement.",
           "confidence": "HIGH"}
    doc = _doc(atomic=[general, specific], relations=[rel])
    result = si.analyze_spec_extraction(doc)
    assert result["status"] == "PASS", result["findings"]
    assert result["dependency_graph"]["cycle"] is None
    assert result["dependency_graph"]["topological_order"] == ["R-2", "R-1"]


# --------------------------------------------------------------------------
# Document-level shape / evidence provenance (reuses evidence_provenance.py)
# --------------------------------------------------------------------------

def test_non_dict_document_is_not_available():
    result = si.analyze_spec_extraction([1, 2, 3])
    assert result["status"] == "NOT_AVAILABLE"


def test_empty_document_is_not_available():
    result = si.analyze_spec_extraction(_doc())
    assert result["status"] == "NOT_AVAILABLE"
    assert result["reason"]


def test_missing_evidence_provenance_fails():
    doc = _doc(atomic=[_req("R-1")])
    del doc["evidence_provenance"]
    result = si.analyze_spec_extraction(doc)
    assert result["status"] == "FAIL"
    assert "EVIDENCE_PROVENANCE_MISSING" in _codes(result)


def test_invalid_evidence_provenance_value_fails():
    doc = _doc(atomic=[_req("R-1")], provenance="A_HUMAN_TOLD_ME")
    result = si.analyze_spec_extraction(doc)
    assert result["status"] == "FAIL"
    assert "EVIDENCE_PROVENANCE_INVALID" in _codes(result)


def test_tool_derived_without_derivation_object_fails():
    doc = _doc(atomic=[_req("R-1")], provenance=si.TOOL_DERIVED)
    result = si.analyze_spec_extraction(doc)
    assert result["status"] == "FAIL"
    assert "EVIDENCE_PROVENANCE_DERIVATION_MISSING" in _codes(result)


def test_tool_derived_with_nonexistent_artifact_fails(tmp_path):
    doc = _doc(atomic=[_req("R-1")], provenance=si.TOOL_DERIVED,
               evidence_derivation={"tool": "ip_xact_extractor", "artifact_path": "does/not/exist.xml"})
    result = si.analyze_spec_extraction(doc, project_root=tmp_path)
    assert result["status"] == "FAIL"
    assert "EVIDENCE_PROVENANCE_ARTIFACT_NOT_FOUND" in _codes(result)


def test_tool_derived_with_real_artifact_on_disk_passes(tmp_path):
    artifact = tmp_path / "extraction_tool_output.xml"
    artifact.write_text("<real/>", encoding="utf-8")
    doc = _doc(atomic=[_req("R-1")], provenance=si.TOOL_DERIVED,
               evidence_derivation={"tool": "ip_xact_extractor", "artifact_path": "extraction_tool_output.xml"})
    result = si.analyze_spec_extraction(doc, project_root=tmp_path)
    assert "EVIDENCE_PROVENANCE_ARTIFACT_NOT_FOUND" not in _codes(result)
    assert "EVIDENCE_PROVENANCE_DERIVATION_MISSING" not in _codes(result)
    assert result["status"] == "PASS"


def test_simulation_derived_with_real_artifact_passes(tmp_path):
    artifact = tmp_path / "sim_trace_extract.json"
    artifact.write_text("{}", encoding="utf-8")
    doc = _doc(atomic=[_req("R-1")], provenance=si.SIMULATION_DERIVED,
               evidence_derivation={"tool": "trace_extractor", "artifact_path": "sim_trace_extract.json"})
    result = si.analyze_spec_extraction(doc, project_root=tmp_path)
    assert result["status"] == "PASS"


# --------------------------------------------------------------------------
# Atomic requirement: requirement_contract.py field/status reuse
# --------------------------------------------------------------------------

def test_atomic_requirement_not_contract_shaped_fails():
    rec = _req("R-1")
    del rec["contract_schema_version"]
    doc = _doc(atomic=[rec])
    result = si.analyze_spec_extraction(doc)
    assert result["status"] == "FAIL"
    assert "NOT_CONTRACT_SHAPED" in _codes(result)


def test_atomic_requirement_schema_validation_failure():
    rec = _req("R-1")
    del rec["checker"]
    doc = _doc(atomic=[rec])
    result = si.analyze_spec_extraction(doc)
    assert result["status"] == "FAIL"
    assert "SCHEMA_VALIDATION_FAILED" in _codes(result)


def test_atomic_requirement_status_overclaimed_reuses_requirement_contract_rule():
    """A record claiming COMPLETE while checker is TBD -- the exact
    requirement_contract.py STATUS_OVERCLAIMED case -- must surface here too,
    proving analyze_requirement_contract() is really called, not re-derived."""
    rec = _req("R-1", checker="TBD")
    doc = _doc(atomic=[rec])
    result = si.analyze_spec_extraction(doc)
    assert result["status"] == "FAIL"
    assert "STATUS_OVERCLAIMED" in _codes(result)


def test_invalid_derivation_value_fails():
    rec = _req("R-1", derivation="INFERRED_MAYBE")
    doc = _doc(atomic=[rec])
    result = si.analyze_spec_extraction(doc)
    assert result["status"] == "FAIL"
    assert "INVALID_DERIVATION" in _codes(result)


def test_explicit_without_quote_fails():
    rec = _req("R-1", source={"document": "spec.txt", "locator": "4.3.1"})
    doc = _doc(atomic=[rec])
    result = si.analyze_spec_extraction(doc)
    assert result["status"] == "FAIL"
    assert "EXPLICIT_REQUIRES_QUOTE" in _codes(result)


def test_implicit_without_derivation_basis_fails():
    rec = _req("R-1", derivation="IMPLICIT_HIGH_CONFIDENCE")
    doc = _doc(atomic=[rec])
    result = si.analyze_spec_extraction(doc)
    assert result["status"] == "FAIL"
    assert "IMPLICIT_REQUIRES_DERIVATION_BASIS" in _codes(result)


def test_implicit_high_confidence_mismatch_with_low_confidence_fails():
    rec = _req("R-1", derivation="IMPLICIT_HIGH_CONFIDENCE",
               derivation_basis="Inferred from the mandatory ack timing in R-4.", confidence="LOW")
    doc = _doc(atomic=[rec])
    result = si.analyze_spec_extraction(doc)
    assert result["status"] == "FAIL"
    assert "IMPLICIT_HIGH_CONFIDENCE_MISMATCH" in _codes(result)


def test_implicit_high_confidence_with_matching_confidence_passes():
    rec = _req("R-1", derivation="IMPLICIT_HIGH_CONFIDENCE",
               derivation_basis="Inferred from the mandatory ack timing in R-4.", confidence="MEDIUM")
    doc = _doc(atomic=[rec])
    result = si.analyze_spec_extraction(doc)
    assert "IMPLICIT_HIGH_CONFIDENCE_MISMATCH" not in _codes(result)
    assert result["status"] == "PASS"


def test_implicit_review_required_without_open_issue_fails():
    rec = _req("R-1", derivation="IMPLICIT_REVIEW_REQUIRED",
               derivation_basis="Inferred from the shared precondition of R-2 and R-3.")
    doc = _doc(atomic=[rec])
    result = si.analyze_spec_extraction(doc)
    assert result["status"] == "FAIL"
    assert "IMPLICIT_REVIEW_REQUIRED_WITHOUT_OPEN_ISSUE" in _codes(result)


def test_implicit_review_required_with_real_ambiguity_reuses_requirement_contract_and_passes():
    """The open question is filed in requirement_contract.py's OWN
    `ambiguities` array -- there is no second, parallel open-question field."""
    rec = _req(
        "R-1", status="AMBIGUOUS", derivation="IMPLICIT_REVIEW_REQUIRED",
        derivation_basis="Inferred from the shared precondition of R-2 and R-3.",
        ambiguities=[{"description": "Unclear whether U1 exit must also complete within the bound.",
                      "resolution_or_question": "Does the spec require U1 EXIT within 10us too?"}],
    )
    doc = _doc(atomic=[rec])
    result = si.analyze_spec_extraction(doc)
    assert "IMPLICIT_REVIEW_REQUIRED_WITHOUT_OPEN_ISSUE" not in _codes(result)
    assert result["status"] == "PASS"


def test_missing_extraction_id_fails():
    rec = _req("R-1", extraction_id="")
    doc = _doc(atomic=[rec])
    result = si.analyze_spec_extraction(doc)
    assert result["status"] == "FAIL"
    assert "MISSING_EXTRACTION_ID" in _codes(result)


def test_duplicate_requirement_id_fails():
    doc = _doc(atomic=[_req("R-1", extraction_id="X-A"), _req("R-1", extraction_id="X-B")])
    result = si.analyze_spec_extraction(doc)
    assert result["status"] == "FAIL"
    assert "DUPLICATE_REQUIREMENT_ID" in _codes(result)


def test_duplicate_extraction_id_fails():
    doc = _doc(atomic=[_req("R-1", extraction_id="X-SAME"), _req("R-2", extraction_id="X-SAME")])
    result = si.analyze_spec_extraction(doc)
    assert result["status"] == "FAIL"
    assert "DUPLICATE_EXTRACTION_ID" in _codes(result)


# --------------------------------------------------------------------------
# Relations
# --------------------------------------------------------------------------

def test_relation_unknown_requirement_fails():
    doc = _doc(atomic=[_req("R-1")], relations=[
        {"from_requirement_id": "R-1", "to_requirement_id": "R-99", "kind": "REFINES", "rationale": "..."}])
    result = si.analyze_spec_extraction(doc)
    assert result["status"] == "FAIL"
    assert "RELATION_UNKNOWN_REQUIREMENT" in _codes(result)


def test_relation_self_reference_fails():
    doc = _doc(atomic=[_req("R-1")], relations=[
        {"from_requirement_id": "R-1", "to_requirement_id": "R-1", "kind": "REFINES", "rationale": "..."}])
    result = si.analyze_spec_extraction(doc)
    assert result["status"] == "FAIL"
    assert "RELATION_SELF_REFERENCE" in _codes(result)


def test_relation_invalid_kind_fails():
    doc = _doc(atomic=[_req("R-1"), _req("R-2")], relations=[
        {"from_requirement_id": "R-1", "to_requirement_id": "R-2", "kind": "RELATES_TO", "rationale": "..."}])
    result = si.analyze_spec_extraction(doc)
    assert result["status"] == "FAIL"
    assert "RELATION_INVALID_KIND" in _codes(result)


def test_relation_missing_rationale_fails():
    doc = _doc(atomic=[_req("R-1"), _req("R-2")], relations=[
        {"from_requirement_id": "R-1", "to_requirement_id": "R-2", "kind": "EXTENDS", "rationale": "  "}])
    result = si.analyze_spec_extraction(doc)
    assert result["status"] == "FAIL"
    assert "RELATION_MISSING_RATIONALE" in _codes(result)


def test_relation_kind_contradiction_fails():
    doc = _doc(atomic=[_req("R-1"), _req("R-2")], relations=[
        {"from_requirement_id": "R-1", "to_requirement_id": "R-2", "kind": "DUPLICATES", "rationale": "same text"},
        {"from_requirement_id": "R-2", "to_requirement_id": "R-1", "kind": "CONFLICTS_WITH", "rationale": "actually differ"},
    ])
    result = si.analyze_spec_extraction(doc)
    assert result["status"] == "FAIL"
    assert "RELATION_KIND_CONTRADICTION" in _codes(result)


def test_duplicate_relation_declaration_is_a_warning_not_a_failure():
    doc = _doc(atomic=[_req("R-1"), _req("R-2")], relations=[
        {"from_requirement_id": "R-1", "to_requirement_id": "R-2", "kind": "EXTENDS", "rationale": "a"},
        {"from_requirement_id": "R-1", "to_requirement_id": "R-2", "kind": "EXTENDS", "rationale": "b"},
    ])
    result = si.analyze_spec_extraction(doc)
    assert "DUPLICATE_RELATION_DECLARATION" in _codes(result)
    findings = [f for f in result["findings"] if f["code"] == "DUPLICATE_RELATION_DECLARATION"]
    assert findings[0]["severity"] == "WARNING"
    assert result["status"] == "PASS"


def test_declared_duplicates_with_low_similarity_is_flagged():
    a = _req("R-1", feature="LFPS handshake timing", stimulus="Assert LFPS", expected_result="Enter U1 within 10us")
    b = _req("R-2", feature="Hot-reset recovery", stimulus="Assert warm reset",
             expected_result="Device re-enumerates within 100ms")
    rel = {"from_requirement_id": "R-1", "to_requirement_id": "R-2", "kind": "DUPLICATES",
           "rationale": "agent claims these are the same requirement"}
    result = si.analyze_spec_extraction(_doc(atomic=[a, b], relations=[rel]))
    assert "DUPLICATES_SIMILARITY_LOW" in _codes(result)
    f = [x for x in result["findings"] if x["code"] == "DUPLICATES_SIMILARITY_LOW"][0]
    assert f["severity"] == "WARNING"
    assert f["similarity"] < si.DUPLICATE_SIMILARITY_LOW_THRESHOLD


def test_declared_duplicates_with_identical_text_is_not_flagged():
    a = _req("R-1")
    b = _req("R-2")  # same feature/stimulus/expected_result text as R-1
    rel = {"from_requirement_id": "R-1", "to_requirement_id": "R-2", "kind": "DUPLICATES", "rationale": "identical wording"}
    result = si.analyze_spec_extraction(_doc(atomic=[a, b], relations=[rel]))
    assert "DUPLICATES_SIMILARITY_LOW" not in _codes(result)
    assert result["status"] == "PASS"


def test_conflicts_with_not_filed_in_contract_is_flagged():
    a = _req("R-1")
    b = _req("R-2", feature="A different feature", stimulus="A different stimulus",
              expected_result="A different expected result")
    rel = {"from_requirement_id": "R-1", "to_requirement_id": "R-2", "kind": "CONFLICTS_WITH",
           "rationale": "agent believes these disagree"}
    result = si.analyze_spec_extraction(_doc(atomic=[a, b], relations=[rel]))
    assert "CONFLICT_RELATION_NOT_FILED_IN_CONTRACT" in _codes(result)


def test_conflicts_with_filed_as_real_contradiction_is_not_flagged():
    a = _req(
        "R-1", status="CONTRADICTORY",
        contradictions=[{"description": "Two sources disagree on the U1 entry bound.",
                         "conflicting_sources": [{"document": "spec_v1.txt"}, {"document": "spec_v2.txt"}]}],
    )
    b = _req("R-2", feature="A different feature", stimulus="A different stimulus",
              expected_result="A different expected result")
    rel = {"from_requirement_id": "R-1", "to_requirement_id": "R-2", "kind": "CONFLICTS_WITH",
           "rationale": "R-1 is itself contradictory against another source describing R-2's area"}
    result = si.analyze_spec_extraction(_doc(atomic=[a, b], relations=[rel]))
    assert "CONFLICT_RELATION_NOT_FILED_IN_CONTRACT" not in _codes(result)


def test_possible_undeclared_duplicate_pair_is_flagged():
    a = _req("R-1")
    b = _req("R-2")  # identical text, no declared relation at all
    result = si.analyze_spec_extraction(_doc(atomic=[a, b]))
    assert "POSSIBLE_UNDECLARED_DUPLICATE_PAIR" in _codes(result)
    f = [x for x in result["findings"] if x["code"] == "POSSIBLE_UNDECLARED_DUPLICATE_PAIR"][0]
    assert f["severity"] == "WARNING"
    assert result["status"] == "PASS"


def test_possible_undeclared_duplicate_pair_is_silenced_by_a_declared_relation():
    a = _req("R-1")
    b = _req("R-2")
    rel = {"from_requirement_id": "R-1", "to_requirement_id": "R-2", "kind": "DUPLICATES", "rationale": "same text"}
    result = si.analyze_spec_extraction(_doc(atomic=[a, b], relations=[rel]))
    assert "POSSIBLE_UNDECLARED_DUPLICATE_PAIR" not in _codes(result)


def test_dedup_scan_skipped_when_too_many_requirements(monkeypatch):
    monkeypatch.setattr(si, "MAX_DEDUP_SCAN_SIZE", 1)
    a = _req("R-1")
    b = _req("R-2")
    result = si.analyze_spec_extraction(_doc(atomic=[a, b]))
    assert "DEDUP_SCAN_SKIPPED_TOO_MANY_REQUIREMENTS" in _codes(result)
    assert "POSSIBLE_UNDECLARED_DUPLICATE_PAIR" not in _codes(result)


# --------------------------------------------------------------------------
# Dependency graph
# --------------------------------------------------------------------------

def test_dependency_graph_topological_order_over_a_chain():
    valid = {"A": _req("A"), "B": _req("B"), "C": _req("C")}
    relations = [
        {"from_requirement_id": "A", "to_requirement_id": "B", "kind": "REFINES", "rationale": "..."},
        {"from_requirement_id": "B", "to_requirement_id": "C", "kind": "EXTENDS", "rationale": "..."},
    ]
    graph = si.build_dependency_graph(valid, relations)
    assert graph["cycle"] is None
    assert graph["topological_order"] == ["A", "B", "C"]
    assert graph["edge_count_by_kind"] == {"REFINES": 1, "EXTENDS": 1}


def test_dependency_graph_detects_a_refines_cycle():
    valid = {"A": _req("A"), "B": _req("B")}
    relations = [
        {"from_requirement_id": "A", "to_requirement_id": "B", "kind": "REFINES", "rationale": "..."},
        {"from_requirement_id": "B", "to_requirement_id": "A", "kind": "REFINES", "rationale": "..."},
    ]
    graph = si.build_dependency_graph(valid, relations)
    assert graph["cycle"] is not None
    assert set(graph["cycle"]) == {"A", "B"}
    assert graph["topological_order"] is None


def test_dependency_graph_cycle_reaches_top_level_analysis_as_a_failure():
    doc = _doc(atomic=[_req("A"), _req("B")], relations=[
        {"from_requirement_id": "A", "to_requirement_id": "B", "kind": "REFINES", "rationale": "..."},
        {"from_requirement_id": "B", "to_requirement_id": "A", "kind": "REFINES", "rationale": "..."},
    ])
    result = si.analyze_spec_extraction(doc)
    assert result["status"] == "FAIL"
    assert "RELATION_CYCLE_DETECTED" in _codes(result)
    assert result["dependency_graph"]["cycle"] is not None


def test_dependency_graph_symmetric_relations_do_not_feed_ordering():
    """DUPLICATES/CONFLICTS_WITH are edges, but never an ordering constraint --
    a DUPLICATES-only pair must not be reported as a cycle or given an order
    derived from adjacency that was never built for it."""
    valid = {"A": _req("A"), "B": _req("B")}
    relations = [{"from_requirement_id": "A", "to_requirement_id": "B", "kind": "DUPLICATES", "rationale": "..."}]
    graph = si.build_dependency_graph(valid, relations)
    assert graph["cycle"] is None
    assert graph["topological_order"] == ["A", "B"]
    assert graph["edge_count_by_kind"] == {"DUPLICATES": 1}


# --------------------------------------------------------------------------
# requirement_similarity()
# --------------------------------------------------------------------------

def test_requirement_similarity_identical_text_is_one():
    assert si.requirement_similarity(_req("R-1"), _req("R-2")) == pytest.approx(1.0)


def test_requirement_similarity_none_when_nothing_resolved_on_one_side():
    a = _req("R-1")
    b = _req("R-2", feature="TBD", stimulus="TBD", expected_result="TBD")
    assert si.requirement_similarity(a, b) is None


def test_requirement_similarity_low_for_unrelated_requirements():
    a = _req("R-1", feature="LFPS handshake timing", stimulus="Assert LFPS", expected_result="Enter U1 within 10us")
    b = _req("R-2", feature="Bulk endpoint retry", stimulus="Force a NAK",
              expected_result="Host retries within 3 frames")
    score = si.requirement_similarity(a, b)
    assert score is not None and score < 0.5


# --------------------------------------------------------------------------
# SpecMap -- real (non-LLM) mechanical distillation, layered on
# vip_user_guide_distill.py
# --------------------------------------------------------------------------

_FIXTURE_SPEC_TEXT = """Protocol Specification Fixture

1 Overview
This section provides background text that is not itself a heading.

2 Register Map
This chapter describes the register layout.

Table 2.1 Register Summary
Offset  Name        Description
0x00    CTRL        Control register
0x04    STATUS      Status register

2.1 Control Register
The control register enables the link.

2.2 Status Register
The status register reports link state.

Table 2.2: Status Bit Definitions
Bit   Name    Description
0x0   LINKUP  Link up indicator

3 Timing Requirements
This chapter is unrelated to registers.
"""

_FIXTURE_NO_HEADINGS_TEXT = """Plain Prose Fixture

This document has no numbered headings at all, only ordinary paragraphs
describing behavior in prose. It exists to prove SpecMap reports an honest
empty structure rather than fabricating one.
"""


def _write_fixture(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_distill_spec_map_detects_sections_tables_and_register_chapters(tmp_path):
    source = _write_fixture(tmp_path, "fixture_spec.txt", _FIXTURE_SPEC_TEXT)
    out_dir = tmp_path / "out"
    spec_map = si.distill_spec_map(source, out_dir, title="Fixture Protocol Spec")

    headings = [s["heading"] for s in spec_map["sections"]]
    assert headings == [
        "1 Overview", "2 Register Map", "2.1 Control Register",
        "2.2 Status Register", "3 Timing Requirements",
    ]
    assert all(s["page"] is None for s in spec_map["sections"])  # .txt source: no PDF pages

    assert spec_map["table_count"] == 2
    table_numbers = {t["number"] for t in spec_map["tables"]}
    assert table_numbers == {"2.1", "2.2"}
    captions = {t["caption"] for t in spec_map["tables"]}
    assert "Register Summary" in captions
    assert "Status Bit Definitions" in captions

    register_headings = {r["heading"] for r in spec_map["register_chapters"]}
    assert register_headings == {"2 Register Map", "2.1 Control Register", "2.2 Status Register"}
    assert "1 Overview" not in register_headings
    assert "3 Timing Requirements" not in register_headings

    # never full body text: the SpecMap record itself carries no document
    # prose beyond headings/captions it already recovered from the section
    # index / table-caption line.
    dumped = json.dumps(spec_map)
    assert "This chapter describes the register layout" not in dumped
    assert "Control register enables the link" not in dumped

    assert Path(spec_map["spec_map_path"]).is_file()


def test_spec_map_on_a_document_with_no_headings_is_honestly_empty(tmp_path):
    source = _write_fixture(tmp_path, "no_headings.txt", _FIXTURE_NO_HEADINGS_TEXT)
    out_dir = tmp_path / "out"
    spec_map = si.distill_spec_map(source, out_dir)
    assert spec_map["sections"] == []
    assert spec_map["section_count"] == 0
    assert spec_map["register_chapters"] == []


def test_load_spec_map_round_trips(tmp_path):
    source = _write_fixture(tmp_path, "fixture_spec.txt", _FIXTURE_SPEC_TEXT)
    out_dir = tmp_path / "out"
    spec_map = si.distill_spec_map(source, out_dir)
    loaded = si.load_spec_map(spec_map["spec_map_path"])
    assert loaded["section_count"] == spec_map["section_count"]
    assert loaded["table_count"] == spec_map["table_count"]


def test_load_spec_map_rejects_a_foreign_json_file(tmp_path):
    foreign = tmp_path / "not_a_spec_map.json"
    foreign.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    with pytest.raises(si.SpecIntelligenceError):
        si.load_spec_map(foreign)


def test_load_spec_map_rejects_unreadable_file(tmp_path):
    bogus = tmp_path / "bogus.json"
    bogus.write_text("{not json", encoding="utf-8")
    with pytest.raises(si.SpecIntelligenceError):
        si.load_spec_map(bogus)


def test_build_spec_map_refuses_when_distilled_reference_missing_on_disk(tmp_path):
    source = _write_fixture(tmp_path, "fixture_spec.txt", _FIXTURE_SPEC_TEXT)
    out_dir = tmp_path / "out"
    record = si.distill_user_guide(source, out_dir, doc_kind="protocol_spec")
    reference_json = out_dir / "fixture_spec.reference.json"
    Path(record["distilled_reference"]["path"]).unlink()  # delete a real producer's own output
    with pytest.raises(si.SpecIntelligenceError):
        si.build_spec_map(reference_json, out_dir)


def test_build_spec_map_refuses_on_a_record_that_is_not_a_real_distillation(tmp_path):
    fake_ref = tmp_path / "fake.reference.json"
    fake_ref.write_text(json.dumps({"not": "a real reference record"}), encoding="utf-8")
    with pytest.raises(si.UserGuideDistillError):
        si.build_spec_map(fake_ref, tmp_path)


# --------------------------------------------------------------------------
# CLI, driven as real subprocesses
# --------------------------------------------------------------------------

def _run_cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.spec_intelligence"] + args,
        cwd=str(cwd or REPO_ROOT), capture_output=True, text=True,
    )


def test_cli_analyze_clean_document_exits_zero(tmp_path):
    doc_path = tmp_path / "extraction.json"
    doc_path.write_text(json.dumps(_doc(atomic=[_req("R-1")])), encoding="utf-8")
    proc = _run_cli(["analyze", "--extraction", str(doc_path), "--json"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "PASS"


def test_cli_analyze_failing_document_exits_one(tmp_path):
    rec = _req("R-1")
    del rec["contract_schema_version"]
    doc_path = tmp_path / "extraction.json"
    doc_path.write_text(json.dumps(_doc(atomic=[rec])), encoding="utf-8")
    proc = _run_cli(["analyze", "--extraction", str(doc_path), "--json"])
    assert proc.returncode == 1, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "FAIL"


def test_cli_analyze_missing_file_exits_two(tmp_path):
    proc = _run_cli(["analyze", "--extraction", str(tmp_path / "does_not_exist.json")])
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "NOT_AVAILABLE" in proc.stdout


def test_cli_spec_map_builds_a_real_artifact(tmp_path):
    source = _write_fixture(tmp_path, "fixture_spec.txt", _FIXTURE_SPEC_TEXT)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    si.distill_user_guide(source, out_dir, doc_kind="protocol_spec")
    reference_json = out_dir / "fixture_spec.reference.json"
    proc = _run_cli(["spec-map", "--reference", str(reference_json), "--out", str(out_dir), "--json"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["section_count"] == 5
    assert Path(payload["spec_map_path"]).is_file()
