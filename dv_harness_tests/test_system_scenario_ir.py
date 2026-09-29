"""Real tests for dv_harness/system_scenario_ir.py.

Every scenario record these tests feed into `system_scenario_ir.py` is produced
by the REAL `system_topology_analysis.plan_system_scenario_model()` over a
small, hand-built SYS-18..22 command plan and SYS-23..27 scheduling plan -- the
same real shape that function's own module expects, never a scenario dict
hand-typed to merely look like one. This proves the reuse claim in
`system_scenario_ir.py`'s own docstring rather than merely asserting it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import pattern_fragment_ir as pfir
from dv_harness import system_scenario_ir as ssi
from dv_harness import system_scheduling_plan as ssp
from dv_harness import system_topology_analysis as sta


# ===========================================================================
# Fixture builders -- real system_topology_analysis.plan_system_scenario_model()
# ===========================================================================

def _command_plan():
    return {
        "system_command_ir": {
            "entries": [
                {"system_command_id": "CMD-A1", "source_subsystem": "A",
                 "source_command": "init_a", "command_category": "INIT"},
                {"system_command_id": "CMD-B1", "source_subsystem": "B",
                 "source_command": "init_b", "command_category": "INIT"},
                {"system_command_id": "CMD-C1", "source_subsystem": "C",
                 "source_command": "init_c", "command_category": "INIT"},
            ]
        }
    }


def _scheduling_plan():
    return {
        "parallelism_model": {
            "pairs": [
                {"command_a": "CMD-A1", "command_b": "CMD-B1",
                 "relationship": ssp.REL_PARALLEL_SAFE},
            ]
        },
        "cross_subsystem_checking": {
            "flows": [
                {"flow_id": "FLOW-AB", "flow": "A talks to B",
                 "verdict": ssp.FLOW_SUPPORTED, "participating_subsystems": ["A", "B"]},
            ],
            "summary": {
                "coupled_subsystem_pairs": [["B", "C"]],
            },
        },
    }


def _real_scenario_model():
    """Two REAL scenarios: FLOW-AB over subsystems {A, B} (one parallel block
    of size 2), and COUPLED-B-C over subsystems {B, C} (two sequential blocks
    of size 1, since no SYS-25 relationship was declared for CMD-B1/CMD-C1).
    They share subsystem B -- the real fixture the coupling-edge tests need.
    """
    return sta.plan_system_scenario_model(_command_plan(), _scheduling_plan())


def _scenario_ids(model):
    return sorted(s["scenario_id"] for s in model["scenarios"])


# ===========================================================================
# Real-shape sanity: the fixture itself behaves the way this module assumes
# ===========================================================================

def test_real_scenario_model_has_two_cross_subsystem_scenarios_sharing_b():
    model = _real_scenario_model()
    scenarios = model["scenarios"]
    assert len(scenarios) == 2
    for s in scenarios:
        assert s["cross_subsystem"] is True
        assert s["scenario_body_status"] == sta.SCENARIO_BODY_NOT_GENERATED
    subsystems_by_scenario = {s["scenario_id"]: set(s["participating_subsystems"])
                               for s in scenarios}
    shared = set.intersection(*subsystems_by_scenario.values())
    assert shared == {"B"}


# ===========================================================================
# build_system_scenario_ir / build_system_scenario_irs
# ===========================================================================

def test_build_system_scenario_ir_wraps_real_scenario_record_verbatim():
    model = _real_scenario_model()
    raw = next(s for s in model["scenarios"] if set(s["participating_subsystems"]) == {"A", "B"})
    ir = ssi.build_system_scenario_ir(raw)
    assert ir.scenario_id == raw["scenario_id"]
    assert ir.participating_subsystems == raw["participating_subsystems"]
    assert ir.block_plan == raw["block_plan"]
    assert ir.parallel_block_count == raw["parallel_block_count"] == 1
    assert ir.scenario_body_status == sta.SCENARIO_BODY_NOT_GENERATED
    assert ir.declared_preconditions == []
    assert ir.declared_postconditions == []
    d = ir.to_dict()
    assert d["scenario_id"] == raw["scenario_id"]


def test_build_system_scenario_ir_rejects_non_mapping():
    with pytest.raises(ssi.SystemScenarioIrError) as exc:
        ssi.build_system_scenario_ir(["not", "a", "dict"])
    assert exc.value.reason == "MALFORMED_SCENARIO_RECORD"


def test_build_system_scenario_ir_rejects_missing_required_field():
    raw = _real_scenario_model()["scenarios"][0]
    mutated = dict(raw)
    del mutated["participating_subsystems"]
    with pytest.raises(ssi.SystemScenarioIrError) as exc:
        ssi.build_system_scenario_ir(mutated)
    assert exc.value.reason == "SCENARIO_RECORD_MISSING_FIELDS"
    assert "participating_subsystems" in exc.value.detail["missing"]


def test_build_system_scenario_ir_refuses_a_body_status_off_the_pinned_value():
    """WHAT THIS MODULE IS NOT, enforced: a scenario whose body status has
    moved off NOT_GENERATED must never be wrapped into a trusted IR."""
    raw = dict(_real_scenario_model()["scenarios"][0])
    raw["scenario_body_status"] = "GENERATED"
    with pytest.raises(ssi.SystemScenarioIrError) as exc:
        ssi.build_system_scenario_ir(raw)
    assert exc.value.reason == "SCENARIO_BODY_STATUS_NOT_PINNED"


def test_build_system_scenario_ir_refuses_a_forbidden_body_shaped_key():
    raw = dict(_real_scenario_model()["scenarios"][0])
    raw["scenario_body"] = "task main; ... endtask"
    with pytest.raises(ssi.SystemScenarioIrError) as exc:
        ssi.build_system_scenario_ir(raw)
    assert exc.value.reason == "SCENARIO_BODY_EMITTED"
    assert exc.value.detail["key"] == "scenario_body"


def test_build_system_scenario_irs_from_full_model_document():
    model = _real_scenario_model()
    irs = ssi.build_system_scenario_irs(model)
    assert [ir.scenario_id for ir in irs] == _scenario_ids(model)


def test_build_system_scenario_irs_from_bare_list():
    model = _real_scenario_model()
    irs = ssi.build_system_scenario_irs(model["scenarios"])
    assert len(irs) == 2


def test_build_system_scenario_irs_rejects_unrecognized_shape():
    with pytest.raises(ssi.SystemScenarioIrError) as exc:
        ssi.build_system_scenario_irs(42)
    assert exc.value.reason == "UNRECOGNIZED_SCENARIO_MODEL_SHAPE"


def test_build_system_scenario_irs_rejects_duplicate_scenario_id():
    model = _real_scenario_model()
    dup = model["scenarios"][0]
    with pytest.raises(ssi.SystemScenarioIrError) as exc:
        ssi.build_system_scenario_irs([dup, dict(dup)])
    assert exc.value.reason == "DUPLICATE_SCENARIO_ID"


# ===========================================================================
# Evidence Truth Rule: declared preconditions/postconditions require a
# real citation -- the mandated negative control
# ===========================================================================

def test_declared_precondition_missing_reason_is_refused_never_fabricated():
    model = _real_scenario_model()
    raw = model["scenarios"][0]
    with pytest.raises(ssi.SystemScenarioIrError) as exc:
        ssi.build_system_scenario_ir(
            raw, declared_preconditions=[{"event": "A_B_LINK_UP"}])  # no reason cited
    assert exc.value.reason == "PRECONDITION_MISSING_REASON"


def test_declared_precondition_missing_event_is_refused():
    model = _real_scenario_model()
    raw = model["scenarios"][0]
    with pytest.raises(ssi.SystemScenarioIrError) as exc:
        ssi.build_system_scenario_ir(
            raw, declared_preconditions=[{"reason": "spec section 4.2"}])
    assert exc.value.reason == "PRECONDITION_MISSING_EVENT"


def test_declared_postcondition_missing_reason_is_refused():
    model = _real_scenario_model()
    raw = model["scenarios"][0]
    with pytest.raises(ssi.SystemScenarioIrError) as exc:
        ssi.build_system_scenario_ir(
            raw, declared_postconditions=[{"event": "A_B_LINK_UP"}])
    assert exc.value.reason == "POSTCONDITION_MISSING_REASON"


def test_declared_condition_not_a_mapping_is_refused():
    model = _real_scenario_model()
    raw = model["scenarios"][0]
    with pytest.raises(ssi.SystemScenarioIrError) as exc:
        ssi.build_system_scenario_ir(raw, declared_preconditions=["A_B_LINK_UP"])
    assert exc.value.reason == "PRECONDITION_NOT_A_MAPPING"


def test_declared_condition_with_real_citation_is_accepted_and_carried_through():
    model = _real_scenario_model()
    raw = model["scenarios"][0]
    ir = ssi.build_system_scenario_ir(
        raw,
        declared_postconditions=[
            {"event": "A_B_LINK_UP",
             "reason": "programming guide section 4.2: A-B handshake completes here"}])
    assert ir.declared_postconditions[0]["event"] == "A_B_LINK_UP"
    assert "4.2" in ir.declared_postconditions[0]["reason"]


# ===========================================================================
# Structural subsystem-coupling edges -- derived, never a human declaration
# ===========================================================================

def test_coupling_edge_detected_between_scenarios_sharing_a_subsystem():
    model = _real_scenario_model()
    irs = ssi.build_system_scenario_irs(model)
    edges = ssi.derive_subsystem_coupling_edges(irs)
    assert len(edges) == 1
    edge = edges[0]
    assert edge["relationship"] == ssi.COUPLING_SHARES_SUBSYSTEMS
    assert edge["shared_subsystems"] == ["B"]
    assert {edge["scenario_a"], edge["scenario_b"]} == {ir.scenario_id for ir in irs}


def test_no_coupling_edge_between_scenarios_sharing_no_subsystem():
    a = ssi.build_system_scenario_ir({
        "scenario_id": "S1", "derived_from": "F1", "description": "d1",
        "participating_subsystems": ["A"], "cross_subsystem": False,
        "command_count": 1, "block_plan": [],
        "scenario_body_status": sta.SCENARIO_BODY_NOT_GENERATED,
    })
    b = ssi.build_system_scenario_ir({
        "scenario_id": "S2", "derived_from": "F2", "description": "d2",
        "participating_subsystems": ["Z"], "cross_subsystem": False,
        "command_count": 1, "block_plan": [],
        "scenario_body_status": sta.SCENARIO_BODY_NOT_GENERATED,
    })
    assert ssi.derive_subsystem_coupling_edges([a, b]) == []


# ===========================================================================
# Dependency-chain readiness -- CALLS pattern_fragment_ir.py, never
# reimplements it
# ===========================================================================

def _two_scenarios_with_one_real_dependency():
    model = _real_scenario_model()
    raw_ab = next(s for s in model["scenarios"] if set(s["participating_subsystems"]) == {"A", "B"})
    raw_bc = next(s for s in model["scenarios"] if set(s["participating_subsystems"]) == {"B", "C"})
    ir_ab = ssi.build_system_scenario_ir(
        raw_ab,
        declared_postconditions=[
            {"event": "A_B_LINK_UP", "reason": "programming guide 4.2: A-B link established"}])
    ir_bc = ssi.build_system_scenario_ir(
        raw_bc,
        declared_preconditions=[
            {"event": "A_B_LINK_UP",
             "reason": "B's own link with C assumes the A-B link is already up, per spec 5.1"}])
    return ir_ab, ir_bc


def test_dependency_chain_covered_when_producer_scheduled_first():
    ir_ab, ir_bc = _two_scenarios_with_one_real_dependency()
    result = ssi.check_system_scenario_dependency_readiness(
        [ir_ab, ir_bc], order=[ir_ab.scenario_id, ir_bc.scenario_id])
    assert result["order_used"] == [ir_ab.scenario_id, ir_bc.scenario_id]
    by_id = {r["fragment_id"]: r for r in result["per_scenario"]}
    assert by_id[ir_bc.scenario_id]["chain_status"] == pfir.CHAIN_STATUS_ALL_COVERED
    assert by_id[ir_bc.scenario_id]["precondition_status"][0]["status"] == pfir.CHAIN_COVERED
    assert by_id[ir_ab.scenario_id]["chain_status"] == pfir.CHAIN_STATUS_NO_PRECONDITIONS
    assert result["all_covered"] is True
    assert result["by_chain_status"][pfir.CHAIN_STATUS_HAS_UNCOVERED] == 0


def test_dependency_chain_uncovered_when_consumer_scheduled_first():
    ir_ab, ir_bc = _two_scenarios_with_one_real_dependency()
    result = ssi.check_system_scenario_dependency_readiness(
        [ir_ab, ir_bc], order=[ir_bc.scenario_id, ir_ab.scenario_id])
    by_id = {r["fragment_id"]: r for r in result["per_scenario"]}
    assert by_id[ir_bc.scenario_id]["chain_status"] == pfir.CHAIN_STATUS_HAS_UNCOVERED
    assert by_id[ir_bc.scenario_id]["precondition_status"][0]["status"] == pfir.CHAIN_UNCOVERED
    assert result["all_covered"] is False


def test_dependency_chain_defaults_to_the_scenarios_own_list_order():
    ir_ab, ir_bc = _two_scenarios_with_one_real_dependency()
    ordered = sorted([ir_ab, ir_bc], key=lambda s: s.scenario_id)
    result = ssi.check_system_scenario_dependency_readiness(ordered)
    assert result["order_used"] == [s.scenario_id for s in ordered]


def test_check_system_scenario_dependency_readiness_raises_on_empty_list():
    with pytest.raises(ssi.SystemScenarioIrError) as exc:
        ssi.check_system_scenario_dependency_readiness([])
    assert exc.value.reason == "EMPTY_SCENARIO_LIST"


def test_check_system_scenario_dependency_readiness_delegates_order_mismatch_to_pfir():
    """Proves genuine delegation: the reused pattern_fragment_ir error's own
    reason ('ORDER_MISMATCH') surfaces here verbatim, never a different,
    re-derived error."""
    ir_ab, ir_bc = _two_scenarios_with_one_real_dependency()
    with pytest.raises(ssi.SystemScenarioIrError) as exc:
        ssi.check_system_scenario_dependency_readiness(
            [ir_ab, ir_bc], order=[ir_ab.scenario_id, "NOT-A-REAL-SCENARIO-ID"])
    assert exc.value.reason == "ORDER_MISMATCH"


# ===========================================================================
# SystemScenarioGraph -- composition
# ===========================================================================

def test_build_system_scenario_graph_end_to_end_all_covered():
    model = _real_scenario_model()
    scen_ids = _scenario_ids(model)
    # Build declarations keyed by the REAL scenario ids so the A-B scenario's
    # postcondition and the B-C scenario's precondition line up correctly
    # regardless of hash order.
    raw_ab = next(s for s in model["scenarios"] if set(s["participating_subsystems"]) == {"A", "B"})
    raw_bc = next(s for s in model["scenarios"] if set(s["participating_subsystems"]) == {"B", "C"})
    declarations = {
        raw_ab["scenario_id"]: {
            "postconditions": [
                {"event": "A_B_LINK_UP", "reason": "programming guide 4.2"}]},
        raw_bc["scenario_id"]: {
            "preconditions": [
                {"event": "A_B_LINK_UP", "reason": "spec 5.1: B-C link assumes A-B link up"}]},
    }
    graph = ssi.build_system_scenario_graph(
        model, dependency_declarations=declarations,
        order=[raw_ab["scenario_id"], raw_bc["scenario_id"]])

    assert graph["summary"]["scenario_count"] == 2
    assert graph["summary"]["cross_subsystem_scenario_count"] == 2
    assert graph["summary"]["coupling_edge_count"] == 1
    assert graph["summary"]["declared_dependency_count"] == 1
    assert graph["summary"]["dependency_chain_all_covered"] is True
    assert [s["scenario_id"] for s in graph["scenarios"]] == sorted(scen_ids)
    ssi.assert_no_scenario_body_emitted(graph)  # must not raise


def test_build_system_scenario_graph_on_zero_scenarios_is_honest_not_an_error():
    empty_model = {"scenarios": [], "summary": {"scenario_count": 0}}
    graph = ssi.build_system_scenario_graph(empty_model)
    assert graph["scenarios"] == []
    assert graph["subsystem_coupling_edges"] == []
    assert graph["summary"]["scenario_count"] == 0
    assert graph["summary"]["dependency_chain_all_covered"] is True


def test_build_system_scenario_graph_from_plans_reuses_plan_system_scenario_model():
    graph = ssi.build_system_scenario_graph_from_plans(_command_plan(), _scheduling_plan())
    assert graph["summary"]["scenario_count"] == 2
    assert graph["summary"]["coupling_edge_count"] == 1


def test_assert_no_scenario_body_emitted_catches_a_mutated_status():
    model = _real_scenario_model()
    graph = ssi.build_system_scenario_graph(model)
    mutated = json.loads(json.dumps(graph))
    mutated["scenarios"][0]["scenario_body_status"] = "GENERATED"
    with pytest.raises(ssi.SystemScenarioIrError) as exc:
        ssi.assert_no_scenario_body_emitted(mutated)
    assert exc.value.reason == "SCENARIO_BODY_STATUS_NOT_PINNED"


def test_assert_no_scenario_body_emitted_catches_a_forbidden_key():
    model = _real_scenario_model()
    graph = ssi.build_system_scenario_graph(model)
    mutated = json.loads(json.dumps(graph))
    mutated["scenarios"][0]["command_txt"] = "task main; endtask"
    with pytest.raises(ssi.SystemScenarioIrError) as exc:
        ssi.assert_no_scenario_body_emitted(mutated)
    assert exc.value.reason == "SCENARIO_BODY_EMITTED"


# ===========================================================================
# Rendering
# ===========================================================================

def test_render_system_scenario_markdown_includes_scenarios_and_coupling():
    model = _real_scenario_model()
    graph = ssi.build_system_scenario_graph(model)
    text = ssi.render_system_scenario_markdown(graph)
    assert "SYSTEM SCENARIO IR + DEPENDENCY GRAPH" in text
    assert "SHARES_SUBSYSTEMS" in text
    for scenario in graph["scenarios"]:
        assert scenario["scenario_id"] in text


def test_render_system_scenario_markdown_handles_empty_graph():
    empty_model = {"scenarios": []}
    graph = ssi.build_system_scenario_graph(empty_model)
    text = ssi.render_system_scenario_markdown(graph)
    assert "no scenario planned" in text
    assert "no two scenarios" in text


# ===========================================================================
# Vocabulary hygiene
# ===========================================================================

def test_vocabulary_never_collides_with_models_status():
    # Import-time assertion already ran; re-run explicitly so a future edit
    # that reintroduces a collision fails this test directly too.
    ssi._assert_no_verification_verdict_vocabulary()


# ===========================================================================
# CLI front door
# ===========================================================================

def test_execute_verb_json_output(tmp_path, capsys):
    model = _real_scenario_model()
    model_path = tmp_path / "scenario_model.json"
    model_path.write_text(json.dumps(model), encoding="utf-8")
    rc = ssi.execute_verb(["--scenario-model", str(model_path), "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["summary"]["scenario_count"] == 2


def test_execute_verb_reports_not_available_on_malformed_input(tmp_path, capsys):
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps(42), encoding="utf-8")
    rc = ssi.execute_verb(["--scenario-model", str(bad_path)])
    assert rc == 2
    out = capsys.readouterr().out
    assert "NOT_AVAILABLE" in out
    assert "UNRECOGNIZED_SCENARIO_MODEL_SHAPE" in out


def test_cli_subprocess_end_to_end(tmp_path):
    model = _real_scenario_model()
    raw_ab = next(s for s in model["scenarios"] if set(s["participating_subsystems"]) == {"A", "B"})
    raw_bc = next(s for s in model["scenarios"] if set(s["participating_subsystems"]) == {"B", "C"})
    model_path = tmp_path / "scenario_model.json"
    model_path.write_text(json.dumps(model), encoding="utf-8")
    decl_path = tmp_path / "declarations.json"
    decl_path.write_text(json.dumps({
        raw_ab["scenario_id"]: {"postconditions": [
            {"event": "A_B_LINK_UP", "reason": "programming guide 4.2"}]},
        raw_bc["scenario_id"]: {"preconditions": [
            {"event": "A_B_LINK_UP", "reason": "spec 5.1"}]},
    }), encoding="utf-8")

    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.system_scenario_ir",
         "--scenario-model", str(model_path),
         "--dependency-declarations", str(decl_path),
         "--order", raw_ab["scenario_id"], raw_bc["scenario_id"],
         "--json"],
        cwd=str(repo_root), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)
    assert parsed["summary"]["dependency_chain_all_covered"] is True
