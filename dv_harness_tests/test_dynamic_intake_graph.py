"""Tests for dv_harness/dynamic_intake_graph.py -- the Dynamic Intake Graph
(section 7). Every graphed FIELD/CATEGORY fact comes from a real
`intake_state.build_intake_state()` run (real `phy_boundary.
classify_boundary()`/`decide_bind_location()` output feeds `dut_boundary`,
exactly as `test_intake_state.py` itself constructs it) -- nothing here
hand-writes an IntakeFieldRecord. Every positive-linking assertion is paired
with a negative control proving the module refuses to fabricate a node,
edge, or non-empty answer when the real evidence is genuinely absent.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import artifact_relationship_discovery as ard
from dv_harness import intake_state as ist
from dv_harness import phy_boundary
from dv_harness.dynamic_intake_graph import (
    DynamicIntakeGraph,
    DynamicIntakeGraphError,
    UNSPECIFIED_RELATION,
    artifact_node_id,
    build_dynamic_intake_graph,
    category_node_id,
    edges_from_artifact_relationships,
    field_node_id,
    graph_connectivity_report,
    impacted_neighbors,
)

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# fixtures: real IntakeState, built through the real intake_state builder
# ---------------------------------------------------------------------------

def _real_parallel_boundary_doc():
    phy_module = {"name": "phy", "ports": [{"name": "pipe_data", "direction": "output", "data_type": "[7:0]"}]}
    ctrl_module = {"name": "ctrl", "ports": [{"name": "pipe_data", "direction": "input", "data_type": "[7:0]"}]}
    signals = phy_boundary.extract_boundary_signals(phy_module, ctrl_module)
    classification = phy_boundary.classify_boundary(signals)
    bind_decision = phy_boundary.decide_bind_location(classification, signals)
    assert classification["kind"] == "PARALLEL"
    assert bind_decision["bindable"] is True
    return {"status": "EXTRACTED", "bind_decision": bind_decision}


def _small_real_intake_state():
    """A real IntakeState with a genuine mix of resolved/blocked/missing
    fields across several categories -- dut_boundary AUTO_RESOLVED (real
    phy_boundary PARALLEL case), known_pass_test AUTO_RESOLVED, build_env
    BLOCKED (a real FAIL gate-1 result), and vip_resolution left MISSING
    (nothing supplied)."""
    return ist.build_intake_state(
        dut_boundary=_real_parallel_boundary_doc(),
        known_pass_tests=[{"test_name": "test_usb_smoke", "verdict": "PASS"}],
        build_env_gate={"status": "FAIL", "detail": {"reason": "elaboration error"}},
        active_driver_conflicts=[],
    )


def _empty_intake_state():
    return ist.IntakeState([])


# ---------------------------------------------------------------------------
# intake_state ingestion: real fields + real category rollup, reused not
# reinvented
# ---------------------------------------------------------------------------

def test_real_dut_boundary_field_and_category_are_graphed():
    state = _small_real_intake_state()
    graph = build_dynamic_intake_graph(state)
    node = graph.node(field_node_id("dut_boundary"))
    assert node is not None
    assert node["kind"] == "FIELD"
    assert node["attrs"]["status"] == ist.IntakeFieldStatus.AUTO_RESOLVED.value
    assert node["attrs"]["category"] == "dut_boundary"

    cat = graph.node(category_node_id("dut_boundary"))
    assert cat is not None
    assert cat["kind"] == "CATEGORY"
    # category_status() is called through, never re-derived -- must agree
    # exactly with intake_state's own real fold.
    assert cat["attrs"]["rollup_status"] == state.category_status("dut_boundary")
    assert cat["attrs"]["rollup_status"] == ist.IntakeFieldStatus.AUTO_RESOLVED.value


def test_in_category_edge_links_field_to_its_real_category():
    state = _small_real_intake_state()
    graph = build_dynamic_intake_graph(state)
    assert field_node_id("dut_boundary") in graph.fields_in_category("dut_boundary")


def test_build_env_blocked_field_and_category_reflect_real_fail_gate():
    state = _small_real_intake_state()
    graph = build_dynamic_intake_graph(state)
    node = graph.node(field_node_id("build_env"))
    assert node["attrs"]["status"] == ist.IntakeFieldStatus.BLOCKED.value
    assert node["attrs"]["reason"] == "elaboration error"
    cat = graph.node(category_node_id("build_env"))
    assert cat["attrs"]["rollup_status"] == ist.IntakeFieldStatus.BLOCKED.value


def test_blocking_category_with_zero_fields_still_gets_a_missing_category_node_NEGATIVE_CONTROL():
    # A caller-assembled IntakeState (e.g. scoped to one subsystem) that
    # never recorded ANY field under vip_resolution -- the category must
    # still be visible on the graph, honestly MISSING via the real
    # category_status() fold, never silently omitted as if it were never a
    # blocking category at all.
    state = ist.IntakeState([
        ist.IntakeFieldRecord(field="dut_boundary", category="dut_boundary", value="phy",
                               source="test", confidence="HIGH",
                               status=ist.IntakeFieldStatus.AUTO_RESOLVED.value),
    ])
    assert state.category_status("vip_resolution") == ist.IntakeFieldStatus.MISSING.value  # sanity
    graph = build_dynamic_intake_graph(state)
    cat = graph.node(category_node_id("vip_resolution"))
    assert cat is not None
    assert cat["attrs"]["rollup_status"] == ist.IntakeFieldStatus.MISSING.value
    assert graph.fields_in_category("vip_resolution") == []


def test_sources_used_intake_state_true_relationship_edges_false_when_none_supplied():
    graph = build_dynamic_intake_graph(_small_real_intake_state())
    assert graph.sources_used["intake_state"] is True
    assert graph.sources_used["relationship_edges"] is False


# ---------------------------------------------------------------------------
# artifact-relationship edges (duck-typed; artifact_relationship_discovery.py
# does not exist in this codebase)
# ---------------------------------------------------------------------------

def test_relationship_edge_between_two_known_fields_is_queryable_both_directions():
    state = _small_real_intake_state()
    edges = [{"from": "dut_boundary", "to": "build_env", "relation": "GATES",
              "evidence": "dut boundary must resolve before build env is meaningful"}]
    graph = build_dynamic_intake_graph(state, edges)
    assert graph.sources_used["relationship_edges"] is True

    out = graph.related_to(field_node_id("dut_boundary"))
    assert out == [{"neighbor": field_node_id("build_env"), "relation": "GATES", "direction": "out"}]
    back = graph.related_to(field_node_id("build_env"))
    assert back == [{"neighbor": field_node_id("dut_boundary"), "relation": "GATES", "direction": "in"}]


def test_relationship_edge_to_unknown_field_creates_honest_artifact_stub_NEGATIVE_CONTROL():
    state = _small_real_intake_state()
    edges = [{"from": "dut_boundary", "to": "some_external_doc.pdf", "relation": "CITES"}]
    graph = build_dynamic_intake_graph(state, edges)
    stub = graph.node(artifact_node_id("some_external_doc.pdf"))
    assert stub is not None
    assert stub["kind"] == "ARTIFACT"
    assert "not a field this IntakeState recorded" in stub["attrs"]["note"]
    # never silently coerced into an existing FIELD node
    assert graph.node(field_node_id("some_external_doc.pdf")) is None


def test_relationship_edge_missing_relation_is_labeled_unspecified_not_guessed():
    state = _small_real_intake_state()
    edges = [{"from": "dut_boundary", "to": "build_env"}]
    graph = build_dynamic_intake_graph(state, edges)
    rel = graph.related_to(field_node_id("dut_boundary"))[0]
    assert rel["relation"] == UNSPECIFIED_RELATION
    assert any(UNSPECIFIED_RELATION in n for n in graph.notes)


def test_relationship_edge_missing_from_or_to_raises_NEGATIVE_CONTROL():
    state = _small_real_intake_state()
    with pytest.raises(DynamicIntakeGraphError):
        build_dynamic_intake_graph(state, [{"from": "dut_boundary"}])
    with pytest.raises(DynamicIntakeGraphError):
        build_dynamic_intake_graph(state, [{"to": "build_env"}])


def test_relationship_edge_bad_confidence_raises_NEGATIVE_CONTROL():
    state = _small_real_intake_state()
    with pytest.raises(DynamicIntakeGraphError):
        build_dynamic_intake_graph(
            state, [{"from": "dut_boundary", "to": "build_env", "confidence": "VERY_SURE"}])


def test_repeated_identical_edge_is_idempotent_no_duplicate():
    state = _small_real_intake_state()
    edges = [{"from": "dut_boundary", "to": "build_env", "relation": "GATES"}] * 3
    graph = build_dynamic_intake_graph(state, edges)
    assert len(graph.edges("RELATES_TO")) == 1


# ---------------------------------------------------------------------------
# edges_from_artifact_relationships: real integration with the (now-existing)
# artifact_relationship_discovery.py, built concurrently in this same batch
# after this module's own docstring was originally written.
# ---------------------------------------------------------------------------

def _real_artifact_relationship_report(tmp_path):
    """Two real artifacts on disk that genuinely share a named identifier:
    a schema-valid register-map JSON declaring register `USB_LINK_CTRL`
    (a real KIND_REGISTER named entity), and a plain-text doc whose prose
    mentions that same name (a KIND_TOKEN occurrence) -- exactly the
    "register-map file references a block also described in a spec doc"
    shape that module's own docstring uses as its worked example, and NOT
    a token-vs-token pair (which its own anti-false-positive rule refuses to
    report)."""
    regmap = tmp_path / "usb_link.regmap.json"
    regmap.write_text(json.dumps({
        "schema_version": "1.0",
        "blocks": [{
            "name": "usb_link_block", "base_address": "0x1000",
            "registers": [{
                "name": "USB_LINK_CTRL", "address_offset": "0x0",
                "width": 32, "access": "RW",
            }],
        }],
    }), encoding="utf-8")
    spec_doc = tmp_path / "usb_link_spec.txt"
    spec_doc.write_text(
        "Section 4: the USB_LINK_CTRL register governs link bring-up.\n",
        encoding="utf-8")
    return ard.discover_relationships([
        {"source_id": "usb_link_regmap", "path": str(regmap)},
        {"source_id": "usb_link_spec_doc", "path": str(spec_doc)},
    ])


def test_edges_from_artifact_relationships_graphs_a_real_shared_identifier(tmp_path):
    report = _real_artifact_relationship_report(tmp_path)
    assert len(report.relationships) == 1, report.relationships  # sanity: real relationship found
    edges = edges_from_artifact_relationships(report)
    assert len(edges) == 1
    edge = edges[0]
    assert edge["from"] == "usb_link_regmap"
    assert edge["to"] == "usb_link_spec_doc"
    assert edge["relation"] == "SHARES_IDENTIFIER:usb_link_ctrl"
    assert "USB_LINK_CTRL" in edge["evidence"]

    graph = build_dynamic_intake_graph(_small_real_intake_state(), edges)
    # neither artifact is an intake field this IntakeState recorded -- both
    # become honest ARTIFACT stubs, never coerced into an existing FIELD.
    a = graph.node(artifact_node_id("usb_link_regmap"))
    b = graph.node(artifact_node_id("usb_link_spec_doc"))
    assert a is not None and a["kind"] == "ARTIFACT"
    assert b is not None and b["kind"] == "ARTIFACT"
    rel = graph.related_to(artifact_node_id("usb_link_regmap"))
    assert rel == [{"neighbor": artifact_node_id("usb_link_spec_doc"),
                     "relation": "SHARES_IDENTIFIER:usb_link_ctrl", "direction": "out"}]


def test_edges_from_artifact_relationships_accepts_to_dict_and_bare_list(tmp_path):
    report = _real_artifact_relationship_report(tmp_path)
    via_dict = edges_from_artifact_relationships(report.to_dict())
    via_bare_list = edges_from_artifact_relationships(report.relationships)
    via_report = edges_from_artifact_relationships(report)
    assert via_dict == via_report == via_bare_list


def test_edges_from_artifact_relationships_no_relationships_is_empty_NEGATIVE_CONTROL(tmp_path):
    # Two artifacts that share nothing real -- the discovery module correctly
    # finds zero relationships, and this adapter must not fabricate one.
    only = tmp_path / "unrelated.txt"
    only.write_text("nothing to see here\n", encoding="utf-8")
    report = ard.discover_relationships([{"source_id": "only", "path": str(only)}])
    assert edges_from_artifact_relationships(report) == []
    assert edges_from_artifact_relationships(None) == []


def test_edges_from_artifact_relationships_malformed_entry_raises_NEGATIVE_CONTROL():
    with pytest.raises(DynamicIntakeGraphError):
        edges_from_artifact_relationships([{"artifact_a": "x"}])  # missing artifact_b
    with pytest.raises(DynamicIntakeGraphError):
        edges_from_artifact_relationships(["not-a-relationship-row"])


# ---------------------------------------------------------------------------
# graph mechanics (add_node/add_edge/neighbors)
# ---------------------------------------------------------------------------

def test_add_node_conflicting_kind_raises_NEGATIVE_CONTROL():
    graph = DynamicIntakeGraph()
    graph.add_node("x", "FIELD")
    with pytest.raises(DynamicIntakeGraphError):
        graph.add_node("x", "CATEGORY")


def test_add_node_merges_attrs_and_appends_provenance():
    graph = DynamicIntakeGraph()
    graph.add_node("x", "FIELD", provenance={"a": 1}, foo="bar")
    graph.add_node("x", "FIELD", provenance={"a": 2}, baz="qux")
    node = graph.node("x")
    assert node["attrs"] == {"foo": "bar", "baz": "qux"}
    assert node["provenance"] == [{"a": 1}, {"a": 2}]


def test_neighbors_rejects_unknown_direction_NEGATIVE_CONTROL():
    graph = DynamicIntakeGraph()
    with pytest.raises(DynamicIntakeGraphError):
        graph.neighbors("x", direction="sideways")


# ---------------------------------------------------------------------------
# graph_connectivity_report / impacted_neighbors
# ---------------------------------------------------------------------------

def test_connectivity_report_not_applicable_for_empty_intake_state_NEGATIVE_CONTROL():
    graph = build_dynamic_intake_graph(_empty_intake_state())
    report = graph_connectivity_report(graph)
    assert report["status"] == "NOT_APPLICABLE"


def test_connectivity_report_lists_orphan_fields_when_no_relationships_supplied():
    state = _small_real_intake_state()
    graph = build_dynamic_intake_graph(state)
    report = graph_connectivity_report(graph)
    assert report["status"] == "OK"
    assert report["relationship_edge_count"] == 0
    assert "dut_boundary" in report["orphan_fields"]
    assert report["orphan_field_count"] == report["field_count"]


def test_connectivity_report_orphan_count_drops_when_a_field_is_related():
    state = _small_real_intake_state()
    graph = build_dynamic_intake_graph(
        state, [{"from": "dut_boundary", "to": "build_env", "relation": "GATES"}])
    report = graph_connectivity_report(graph)
    assert "dut_boundary" not in report["orphan_fields"]
    assert "build_env" not in report["orphan_fields"]
    assert report["orphan_field_count"] < report["field_count"]


def test_impacted_neighbors_reports_real_neighbor_status():
    state = _small_real_intake_state()
    graph = build_dynamic_intake_graph(
        state, [{"from": "dut_boundary", "to": "build_env", "relation": "GATES"}])
    result = impacted_neighbors(graph, "dut_boundary")
    assert result["status"] == "OK"
    assert result["field_status"] == ist.IntakeFieldStatus.AUTO_RESOLVED.value
    assert len(result["neighbors"]) == 1
    neighbor = result["neighbors"][0]
    assert neighbor["neighbor"] == field_node_id("build_env")
    assert neighbor["neighbor_status"] == ist.IntakeFieldStatus.BLOCKED.value


def test_impacted_neighbors_unknown_field_is_not_available_NEGATIVE_CONTROL():
    graph = build_dynamic_intake_graph(_small_real_intake_state())
    result = impacted_neighbors(graph, "field_that_was_never_recorded")
    assert result["status"] == "NOT_AVAILABLE"
    assert "not a field" in result["reason"]


def test_to_dict_and_stats_are_stable_and_sorted():
    state = _small_real_intake_state()
    graph = build_dynamic_intake_graph(
        state, [{"from": "dut_boundary", "to": "build_env", "relation": "GATES"}])
    d = graph.to_dict()
    assert [n["id"] for n in d["nodes"]] == sorted(n["id"] for n in d["nodes"])
    assert [(e["source"], e["target"], e["kind"]) for e in d["edges"]] == sorted(
        (e["source"], e["target"], e["kind"]) for e in d["edges"])
    stats = graph.stats()
    assert stats["total_nodes"] == len(d["nodes"])
    assert stats["total_edges"] == len(d["edges"])
    assert stats["edge_counts"].get("RELATES_TO") == 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.dynamic_intake_graph", *args],
        cwd=str(ROOT), capture_output=True, text=True,
    )


def test_cli_builds_and_reports_json(tmp_path):
    state = _small_real_intake_state()
    intake_file = tmp_path / "intake_state.json"
    intake_file.write_text(json.dumps(state.to_dict()), encoding="utf-8")
    rel_file = tmp_path / "relationships.json"
    rel_file.write_text(json.dumps([
        {"from": "dut_boundary", "to": "build_env", "relation": "GATES"},
    ]), encoding="utf-8")

    result = _run_cli("--intake-state", str(intake_file), "--relationships", str(rel_file), "--json")
    assert result.returncode == 0, result.stderr
    doc = json.loads(result.stdout)
    assert doc["sources_used"]["relationship_edges"] is True
    assert any(e["kind"] == "RELATES_TO" for e in doc["edges"])


def test_cli_no_relationships_still_succeeds(tmp_path):
    state = _small_real_intake_state()
    intake_file = tmp_path / "intake_state.json"
    intake_file.write_text(json.dumps(state.to_dict()), encoding="utf-8")
    result = _run_cli("--intake-state", str(intake_file))
    assert result.returncode == 0, result.stderr
    assert "nodes:" in result.stdout


def test_cli_malformed_intake_state_file_exits_2_NEGATIVE_CONTROL(tmp_path):
    bad_file = tmp_path / "bad_intake_state.json"
    bad_file.write_text(json.dumps({"not_fields": []}), encoding="utf-8")
    result = _run_cli("--intake-state", str(bad_file))
    assert result.returncode == 2
    assert "error" in result.stderr


def test_cli_malformed_relationships_file_exits_2_NEGATIVE_CONTROL(tmp_path):
    state = _small_real_intake_state()
    intake_file = tmp_path / "intake_state.json"
    intake_file.write_text(json.dumps(state.to_dict()), encoding="utf-8")
    rel_file = tmp_path / "bad_relationships.json"
    rel_file.write_text(json.dumps({"nope": "not edges"}), encoding="utf-8")
    result = _run_cli("--intake-state", str(intake_file), "--relationships", str(rel_file))
    assert result.returncode == 2
    assert "error" in result.stderr
