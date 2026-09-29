"""Tests for dv_harness/design_knowledge_correlation.py.

Because this module's whole contract is "generic IR-shaped input" (per the
batch's file-safety scope, it imports nothing else from dv_harness), these
fixtures are small, synthetic, hand-built source lists constructed directly
in this file -- never another module's real output -- so what is being
proven is the correlation logic itself: CONFLICT, GAP,
DOCUMENTED_VS_IMPLEMENTED detection and the assembled Design Knowledge Graph.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import design_knowledge_correlation as dkc


# ---------------------------------------------------------------------------
# Small fixture builders
# ---------------------------------------------------------------------------

def _spec_source(source_id="spec_v1", facts=None):
    return {
        "source_id": source_id, "source_kind": "spec", "role": dkc.ROLE_SPEC_DECLARATION,
        "facts": facts or [],
    }


def _rtl_source(source_id="rtl_verible", facts=None):
    return {
        "source_id": source_id, "source_kind": "rtl", "role": dkc.ROLE_IMPLEMENTATION_EVIDENCE,
        "facts": facts or [],
    }


def _other_source(source_id="testplan", facts=None):
    return {
        "source_id": source_id, "source_kind": "testplan", "role": dkc.ROLE_OTHER,
        "facts": facts or [],
    }


# ---------------------------------------------------------------------------
# Core positive path: a clean, fully-agreeing correlation
# ---------------------------------------------------------------------------

def test_clean_correlation_reports_zero_findings():
    sources = [
        _spec_source(facts=[
            {"fact_key": "usb_wake_irq.active_level", "fact_type": "interrupt",
             "value": "HIGH", "evidence_ref": "spec.md:120"},
        ]),
        _rtl_source(facts=[
            {"fact_key": "usb_wake_irq.active_level", "fact_type": "interrupt",
             "value": "high", "evidence_ref": "rtl/usb_top.v:88"},
        ]),
    ]
    report = dkc.correlate(sources)
    assert report["summary"]["conflict_count"] == 0
    assert report["summary"]["gap_count"] == 0
    assert report["summary"]["documented_vs_implemented_count"] == 0
    assert report["conflicts"] == []
    assert report["gaps"] == []
    assert report["documented_vs_implemented"] == []

    graph = report["knowledge_graph"]
    assert graph["summary"]["source_count"] == 2
    assert graph["summary"]["fact_count"] == 1
    assert graph["summary"]["facts_in_conflict"] == 0
    fact_node = graph["nodes"]["facts"][0]
    assert fact_node["consensus"] == dkc.CONSENSUS_AGREEMENT
    assert fact_node["distinct_value_count"] == 1
    # per-node provenance: both sources' contribution is embedded on the node
    provenance_sources = {p["source_id"] for p in fact_node["provenance"]}
    assert provenance_sources == {"spec_v1", "rtl_verible"}


def test_value_comparator_is_representation_tolerant_not_substance_tolerant():
    # "HIGH" vs "high" (whitespace/case) agree; 100 vs 100.0 (numeric repr) agree;
    # True vs "true" agree; but 100 vs 200 (genuine disagreement) does not.
    sources = [
        _spec_source(source_id="s1", facts=[
            {"fact_key": "f.case", "value": " HIGH ", "evidence_ref": "s1:1"},
            {"fact_key": "f.num", "value": 100, "evidence_ref": "s1:2"},
            {"fact_key": "f.bool", "value": True, "evidence_ref": "s1:3"},
            {"fact_key": "f.real_conflict", "value": 100, "evidence_ref": "s1:4"},
        ]),
        _rtl_source(source_id="s2", facts=[
            {"fact_key": "f.case", "value": "high", "evidence_ref": "s2:1"},
            {"fact_key": "f.num", "value": 100.0, "evidence_ref": "s2:2"},
            {"fact_key": "f.bool", "value": "true", "evidence_ref": "s2:3"},
            {"fact_key": "f.real_conflict", "value": 200, "evidence_ref": "s2:4"},
        ]),
    ]
    report = dkc.correlate(sources)
    conflict_keys = {c["fact_key"] for c in report["conflicts"]}
    assert conflict_keys == {"f.real_conflict"}


# ---------------------------------------------------------------------------
# CONFLICT
# ---------------------------------------------------------------------------

def test_conflict_two_sources_disagree_on_same_fact():
    sources = [
        _spec_source(source_id="spec", facts=[
            {"fact_key": "reset.por_rst_n.active_level", "value": "LOW", "evidence_ref": "spec.md:40"},
        ]),
        _rtl_source(source_id="rtl", facts=[
            {"fact_key": "reset.por_rst_n.active_level", "value": "HIGH", "evidence_ref": "rtl/top.v:12"},
        ]),
    ]
    report = dkc.correlate(sources)
    assert report["summary"]["conflict_count"] == 1
    finding = report["conflicts"][0]
    assert finding["finding_type"] == dkc.FINDING_CONFLICT
    assert finding["fact_key"] == "reset.por_rst_n.active_level"
    assert finding["node_id"] == "fact:reset.por_rst_n.active_level"
    assert len(finding["distinct_value_groups"]) == 2
    all_source_ids = {
        s["source_id"] for grp in finding["distinct_value_groups"] for s in grp["sources"]
    }
    assert all_source_ids == {"spec", "rtl"}
    # arbitration is explicitly NOT decided
    assert "does not decide which side is right" in finding["reason"]

    graph = report["knowledge_graph"]
    fact_node = graph["nodes"]["facts"][0]
    assert fact_node["consensus"] == dkc.CONSENSUS_CONFLICT
    assert fact_node["distinct_value_count"] == 2
    assert graph["summary"]["facts_in_conflict"] == 1


def test_conflict_three_way_split_groups_correctly():
    # Two sources agree (LOW), one disagrees (HIGH) -- exactly two value groups.
    sources = [
        _spec_source(source_id="spec", facts=[{"fact_key": "f", "value": "LOW", "evidence_ref": "a"}]),
        _rtl_source(source_id="rtl", facts=[{"fact_key": "f", "value": "low", "evidence_ref": "b"}]),
        _other_source(source_id="doc", facts=[{"fact_key": "f", "value": "HIGH", "evidence_ref": "c"}]),
    ]
    report = dkc.correlate(sources)
    assert report["summary"]["conflict_count"] == 1
    groups = report["conflicts"][0]["distinct_value_groups"]
    assert len(groups) == 2
    sizes = sorted(len(g["sources"]) for g in groups)
    assert sizes == [1, 2]


def test_no_conflict_when_only_one_source_asserts_a_fact():
    sources = [_spec_source(facts=[{"fact_key": "solo", "value": "X", "evidence_ref": "a"}])]
    report = dkc.correlate(sources)
    assert report["conflicts"] == []


# ---------------------------------------------------------------------------
# GAP
# ---------------------------------------------------------------------------

def test_gap_expected_fact_covered_by_no_source():
    sources = [
        _spec_source(facts=[{"fact_key": "feature.low_power_mode", "value": True, "evidence_ref": "spec.md:5"}]),
    ]
    expected = [
        {"fact_key": "feature.low_power_mode", "reason": "listed in vPlan"},
        {"fact_key": "feature.jtag_boundary_scan", "reason": "listed in vPlan", "required_by": "vplan.json#JTAG-1"},
    ]
    report = dkc.correlate(sources, expected_facts=expected)
    assert report["summary"]["gap_count"] == 1
    gap = report["gaps"][0]
    assert gap["finding_type"] == dkc.FINDING_GAP
    assert gap["fact_key"] == "feature.jtag_boundary_scan"
    assert gap["required_by"] == "vplan.json#JTAG-1"
    assert "no supplied source asserts any value" in gap["reason"]


def test_no_gaps_without_expected_facts_declared():
    sources = [_spec_source(facts=[{"fact_key": "f", "value": 1, "evidence_ref": "a"}])]
    report = dkc.correlate(sources, expected_facts=None)
    assert report["gaps"] == []
    assert report["summary"]["expected_fact_count"] == 0


def test_gap_not_reported_when_a_source_covers_it_even_if_disputed():
    # An expected fact that IS covered (even if by only one source) is not a gap.
    sources = [_spec_source(facts=[{"fact_key": "feature.x", "value": True, "evidence_ref": "a"}])]
    expected = [{"fact_key": "feature.x", "reason": "in scope"}]
    report = dkc.correlate(sources, expected_facts=expected)
    assert report["gaps"] == []


# ---------------------------------------------------------------------------
# DOCUMENTED_VS_IMPLEMENTED
# ---------------------------------------------------------------------------

def test_spec_declared_feature_with_no_rtl_evidence():
    sources = [
        _spec_source(facts=[
            {"fact_key": "feature.secure_boot", "value": True, "evidence_ref": "spec.md:200"},
            {"fact_key": "feature.shared", "value": True, "evidence_ref": "spec.md:201"},
        ]),
        _rtl_source(facts=[{"fact_key": "feature.shared", "value": True, "evidence_ref": "rtl.v:1"}]),
    ]
    report = dkc.correlate(sources)
    # "feature.shared" is covered on both sides -> no finding for it; only
    # "feature.secure_boot" (spec-only) is reported.
    assert report["summary"]["documented_vs_implemented_count"] == 1
    finding = report["documented_vs_implemented"][0]
    assert finding["finding_type"] == dkc.FINDING_DOC_VS_IMPL_SPEC_ONLY
    assert finding["fact_key"] == "feature.secure_boot"
    assert finding["spec_sources"][0]["source_id"] == "spec_v1"
    assert "no RTL/implementation evidence" in finding["reason"]


def test_rtl_evidence_for_something_spec_never_declared():
    sources = [
        _rtl_source(facts=[
            {"fact_key": "signal.debug_test_mode", "value": 1, "evidence_ref": "rtl/top.v:900"},
            {"fact_key": "feature.shared", "value": True, "evidence_ref": "rtl.v:1"},
        ]),
        _spec_source(facts=[{"fact_key": "feature.shared", "value": True, "evidence_ref": "spec.md:1"}]),
    ]
    report = dkc.correlate(sources)
    assert report["summary"]["documented_vs_implemented_count"] == 1
    finding = report["documented_vs_implemented"][0]
    assert finding["finding_type"] == dkc.FINDING_DOC_VS_IMPL_IMPLEMENTATION_ONLY
    assert finding["fact_key"] == "signal.debug_test_mode"
    assert finding["implementation_sources"][0]["source_id"] == "rtl_verible"
    assert "spec never declared" in finding["reason"]


def test_both_sides_present_is_not_a_doc_vs_impl_finding_even_when_values_conflict():
    sources = [
        _spec_source(facts=[{"fact_key": "feature.x", "value": "A", "evidence_ref": "spec.md:1"}]),
        _rtl_source(facts=[{"fact_key": "feature.x", "value": "B", "evidence_ref": "rtl.v:1"}]),
    ]
    report = dkc.correlate(sources)
    # this is a CONFLICT (both sides spoke, and disagree), never additionally
    # counted as a doc-vs-impl mismatch -- the two categories are disjoint.
    assert report["summary"]["conflict_count"] == 1
    assert report["summary"]["documented_vs_implemented_count"] == 0


def test_other_role_only_coverage_yields_no_doc_vs_impl_finding():
    sources = [_other_source(facts=[{"fact_key": "feature.y", "value": True, "evidence_ref": "testplan.csv:3"}])]
    report = dkc.correlate(sources)
    assert report["documented_vs_implemented"] == []


# ---------------------------------------------------------------------------
# Design Knowledge Graph structure / provenance
# ---------------------------------------------------------------------------

def test_knowledge_graph_edges_carry_real_evidence_and_role():
    sources = [
        _spec_source(source_id="spec", facts=[
            {"fact_key": "f1", "value": "X", "evidence_ref": "spec.md:1"},
        ]),
        _rtl_source(source_id="rtl", facts=[
            {"fact_key": "f1", "value": "X", "evidence_ref": "rtl.v:2"},
        ]),
    ]
    report = dkc.correlate(sources)
    graph = report["knowledge_graph"]
    assert {n["node_id"] for n in graph["nodes"]["sources"]} == {"source:spec", "source:rtl"}
    assert graph["nodes"]["facts"][0]["node_id"] == "fact:f1"
    edges_by_from = {e["from"]: e for e in graph["edges"]}
    assert edges_by_from["source:spec"]["evidence_ref"] == "spec.md:1"
    assert edges_by_from["source:spec"]["role"] == dkc.ROLE_SPEC_DECLARATION
    assert edges_by_from["source:rtl"]["role"] == dkc.ROLE_IMPLEMENTATION_EVIDENCE
    assert edges_by_from["source:spec"]["to"] == "fact:f1"


def test_build_knowledge_graph_is_independently_callable():
    sources = [_spec_source(facts=[{"fact_key": "f1", "value": 1, "evidence_ref": "a"}])]
    norm = dkc._validate_sources(sources)
    graph = dkc.build_knowledge_graph(norm)
    assert graph["summary"]["fact_count"] == 1


# ---------------------------------------------------------------------------
# Negative controls: malformed / mutated input must NOT silently pass
# ---------------------------------------------------------------------------

def test_negative_empty_sources_list_raises():
    with pytest.raises(dkc.DesignKnowledgeCorrelationError):
        dkc.correlate([])


def test_negative_sources_not_a_list_raises():
    with pytest.raises(dkc.DesignKnowledgeCorrelationError):
        dkc.correlate({"source_id": "x"})


def test_negative_duplicate_source_id_raises():
    sources = [
        _spec_source(source_id="dup", facts=[{"fact_key": "f", "value": 1, "evidence_ref": "a"}]),
        _rtl_source(source_id="dup", facts=[{"fact_key": "g", "value": 2, "evidence_ref": "b"}]),
    ]
    with pytest.raises(dkc.DesignKnowledgeCorrelationError, match="duplicate source_id"):
        dkc.correlate(sources)


def test_negative_missing_fact_key_raises():
    sources = [{"source_id": "s1", "source_kind": "spec", "facts": [{"value": 1}]}]
    with pytest.raises(dkc.DesignKnowledgeCorrelationError, match="fact_key"):
        dkc.correlate(sources)


def test_negative_missing_value_key_raises():
    sources = [{"source_id": "s1", "source_kind": "spec", "facts": [{"fact_key": "f"}]}]
    with pytest.raises(dkc.DesignKnowledgeCorrelationError, match="value"):
        dkc.correlate(sources)


def test_negative_invalid_role_raises():
    sources = [{"source_id": "s1", "source_kind": "spec", "role": "NOT_A_REAL_ROLE",
                "facts": [{"fact_key": "f", "value": 1}]}]
    with pytest.raises(dkc.DesignKnowledgeCorrelationError, match="role"):
        dkc.correlate(sources)


def test_negative_missing_source_id_raises():
    sources = [{"source_kind": "spec", "facts": [{"fact_key": "f", "value": 1}]}]
    with pytest.raises(dkc.DesignKnowledgeCorrelationError):
        dkc.correlate(sources)


def test_negative_malformed_expected_facts_raises():
    sources = [_spec_source(facts=[{"fact_key": "f", "value": 1}])]
    with pytest.raises(dkc.DesignKnowledgeCorrelationError):
        dkc.correlate(sources, expected_facts=[{"no_fact_key": True}])


def test_absent_evidence_never_reads_as_a_false_pass():
    # A fact that genuinely has conflicting evidence must NOT be silently
    # absorbed into "agreement" just because one source's value looks similar
    # in a naive string sense (e.g. "10" vs "100" must not fuzzy-match).
    sources = [
        _spec_source(source_id="s1", facts=[{"fact_key": "width", "value": "10", "evidence_ref": "a"}]),
        _rtl_source(source_id="s2", facts=[{"fact_key": "width", "value": "100", "evidence_ref": "b"}]),
    ]
    report = dkc.correlate(sources)
    assert report["summary"]["conflict_count"] == 1


# ---------------------------------------------------------------------------
# CLI front door
# ---------------------------------------------------------------------------

def test_cli_json_output_and_exit_code(tmp_path: Path):
    sources = [
        _spec_source(source_id="spec", facts=[{"fact_key": "f", "value": "A", "evidence_ref": "spec.md:1"}]),
        _rtl_source(source_id="rtl", facts=[{"fact_key": "f", "value": "B", "evidence_ref": "rtl.v:1"}]),
    ]
    sources_path = tmp_path / "sources.json"
    sources_path.write_text(json.dumps(sources), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.design_knowledge_correlation",
         "--sources", str(sources_path), "--json"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode == 1  # a real conflict was found
    payload = json.loads(result.stdout)
    assert payload["summary"]["conflict_count"] == 1


def test_cli_clean_input_exits_zero(tmp_path: Path):
    # OTHER-role only coverage triggers neither a conflict, a gap (no expected
    # facts declared) nor a doc-vs-impl finding -- genuinely clean.
    sources = [_other_source(facts=[{"fact_key": "f", "value": 1, "evidence_ref": "a"}])]
    sources_path = tmp_path / "sources.json"
    sources_path.write_text(json.dumps(sources), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.design_knowledge_correlation", "--sources", str(sources_path)],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode == 0


def test_cli_malformed_input_exits_two(tmp_path: Path):
    sources_path = tmp_path / "sources.json"
    sources_path.write_text(json.dumps([]), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.design_knowledge_correlation", "--sources", str(sources_path)],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode == 2


def test_cli_with_expected_facts_file(tmp_path: Path):
    sources = [_spec_source(facts=[{"fact_key": "feature.a", "value": True, "evidence_ref": "spec.md:1"}])]
    expected = [{"fact_key": "feature.b", "reason": "in vplan"}]
    sources_path = tmp_path / "sources.json"
    expected_path = tmp_path / "expected.json"
    sources_path.write_text(json.dumps(sources), encoding="utf-8")
    expected_path.write_text(json.dumps(expected), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.design_knowledge_correlation",
         "--sources", str(sources_path), "--expected-facts", str(expected_path), "--json"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["summary"]["gap_count"] == 1
    assert payload["gaps"][0]["fact_key"] == "feature.b"
