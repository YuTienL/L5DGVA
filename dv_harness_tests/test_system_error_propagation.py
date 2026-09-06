"""Tests for `dv_harness/system_error_propagation.py`: the ErrorPropagationIR
tracer over a real-or-duck-typed `system_topology_analysis.py`-shaped
topology document.

Every topology fixture is a small synthetic dict built inline, shaped
exactly like `system_topology_analysis.build_system_topology_analysis()`'s
own real output (`address_map_reconciliation.overlaps`,
`interrupt_map_reconciliation.lines`, `clock_reset_comparison.
clock_comparisons`/`reset_comparisons`) -- this module never imports that
module, so these fixtures are the contract this suite holds it to.

The suite proves the real positive path (a shared-memory edge propagates an
ADDRESS_DECODE_FAULT and a complete recovery chain reads COMPLETE) plus, in
this project's mutate-one-fact style, real negative controls: an affected
subsystem with no declared response reads INCOMPLETE (never silently
COMPLETE); a condition kind only follows edges relevant to it (an address
edge never propagates an INTERRUPT_STORM); an honest SYS-28/SYS-29 `UNKNOWN`
verdict is never treated as a proven path; an origin absent from the
topology, and an empty topology, both read NOT_AVAILABLE rather than a
guessed trace; a transitive multi-hop chain is followed and a placeholder
response is treated the same as a missing one; and the real CLI subprocess
exit codes are asserted.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import system_error_propagation as sep


# ===========================================================================
# Fixture builders -- shaped like system_topology_analysis.py's real output
# ===========================================================================

def _address_row(sid_a, sid_b, verdict, region_a="ra", region_b="rb", pair_id="SYSADDR-1"):
    return {"pair_id": pair_id, "subsystem_a": sid_a, "region_a": region_a,
            "subsystem_b": sid_b, "region_b": region_b, "verdict": verdict}


def _interrupt_row(line, subsystems, verdict=sep._INTERRUPT_SHARED_VERDICT):
    return {"line": line, "normalized_line": line.lower(), "verdict": verdict,
            "subsystems": list(subsystems)}


def _cr_row(sid_a, sid_b, name_a, name_b, verdict, pair_id="SYSCR-1"):
    return {"pair_id": pair_id, "subsystem_a": sid_a, "name_a": name_a,
            "subsystem_b": sid_b, "name_b": name_b, "verdict": verdict}


def _topology(address_overlaps=(), interrupt_lines=(), clock_comparisons=(),
             reset_comparisons=(), selected=None):
    subsystems = set(selected or [])
    for row in address_overlaps:
        subsystems.update((row["subsystem_a"], row["subsystem_b"]))
    for row in interrupt_lines:
        subsystems.update(row["subsystems"])
    for row in list(clock_comparisons) + list(reset_comparisons):
        subsystems.update((row["subsystem_a"], row["subsystem_b"]))
    return {
        "selected_subsystems": sorted(subsystems),
        "address_map_reconciliation": {
            "per_subsystem": {s: {} for s in subsystems},
            "overlaps": list(address_overlaps),
        },
        "interrupt_map_reconciliation": {"lines": list(interrupt_lines)},
        "clock_reset_comparison": {
            "per_subsystem": {s: {} for s in subsystems},
            "clock_comparisons": list(clock_comparisons),
            "reset_comparisons": list(reset_comparisons),
        },
    }


def _response(subsystem_id, response_action="disable channel and re-init controller",
             evidence="fw_recovery_spec.md#section-4"):
    return {"subsystem_id": subsystem_id, "response_action": response_action,
            "evidence": evidence}


# ===========================================================================
# Positive path
# ===========================================================================

def test_address_decode_fault_propagates_via_shared_memory_and_chain_is_complete():
    topology = _topology(address_overlaps=[
        _address_row("usb_subsys", "dma_subsys", "SHARED_MEMORY"),
    ])
    ir = sep.trace_error_propagation(
        "usb_subsys", "ADDRESS_DECODE_FAULT", topology,
        declared_responses=[_response("dma_subsys")])
    report = ir.to_dict()
    assert report["recovery_chain_status"] == sep.CHAIN_COMPLETE
    assert report["affected_count"] == 1
    assert report["affected_subsystems"][0]["subsystem_id"] == "dma_subsys"
    assert report["affected_subsystems"][0]["response_status"] == sep.RESPONSE_DECLARED
    assert report["missing_response_subsystems"] == []
    assert report["edges_considered"][0]["kind"] == sep.EDGE_SHARED_ADDRESS_SPACE


# ===========================================================================
# Negative control 1: a Critical UNKNOWN (missing declared response) must
# never silently become a COMPLETE recovery chain.
# ===========================================================================

def test_missing_declared_response_makes_the_chain_incomplete_not_complete():
    topology = _topology(address_overlaps=[
        _address_row("usb_subsys", "dma_subsys", "SHARED_MEMORY"),
    ])
    ir = sep.trace_error_propagation("usb_subsys", "ADDRESS_DECODE_FAULT", topology,
                                     declared_responses=None)
    report = ir.to_dict()
    assert report["recovery_chain_status"] == sep.CHAIN_INCOMPLETE
    assert report["missing_response_subsystems"] == ["dma_subsys"]
    assert report["affected_subsystems"][0]["response_status"] == sep.RESPONSE_MISSING


# ===========================================================================
# Negative control 2: condition-relevant edge filtering -- an INTERRUPT_STORM
# must never propagate over a shared-address edge, only a shared-interrupt
# edge.
# ===========================================================================

def test_interrupt_storm_only_follows_shared_interrupt_edges_not_address_edges():
    topology = _topology(
        address_overlaps=[_address_row("origin", "addr_neighbor", "SHARED_MEMORY")],
        interrupt_lines=[_interrupt_row("irq_dma_done", ["origin", "irq_neighbor"])],
    )
    ir = sep.trace_error_propagation(
        "origin", "INTERRUPT_STORM", topology,
        declared_responses=[_response("irq_neighbor"), _response("addr_neighbor")])
    report = ir.to_dict()
    affected_ids = {a["subsystem_id"] for a in report["affected_subsystems"]}
    assert affected_ids == {"irq_neighbor"}
    assert "addr_neighbor" not in affected_ids
    assert report["relevant_edge_kinds"] == [sep.EDGE_SHARED_INTERRUPT_LINE]


# ===========================================================================
# Negative control 3: an honest SYS-28/SYS-29 UNKNOWN verdict (data-quality
# defect inside one side, per that module's own docstring) must never be
# treated as a proven propagation path.
# ===========================================================================

def test_unknown_verdicts_are_never_treated_as_a_proven_path():
    topology = _topology(
        address_overlaps=[_address_row("origin", "disputed_neighbor", "UNKNOWN")],
        clock_comparisons=[_cr_row("origin", "indep_neighbor", "clk_a", "clk_b",
                                   "INDEPENDENT_CLOCK_DOMAIN")],
    )
    ir = sep.trace_error_propagation("origin", "GENERIC", topology)
    report = ir.to_dict()
    assert report["recovery_chain_status"] == sep.CHAIN_NO_PROPAGATION
    assert report["affected_count"] == 0


# ===========================================================================
# Negative control 4: an origin the topology does not name at all, and an
# empty topology, both report NOT_AVAILABLE rather than a guessed trace.
# ===========================================================================

def test_origin_not_in_topology_reports_not_available():
    topology = _topology(address_overlaps=[
        _address_row("subsys_a", "subsys_b", "SHARED_MEMORY"),
    ])
    ir = sep.trace_error_propagation("nonexistent_subsys", "GENERIC", topology)
    assert ir.recovery_chain_status == sep.CHAIN_NOT_AVAILABLE
    assert any(u["field"] == "origin" for u in ir.unknowns)


def test_empty_topology_reports_not_available():
    ir = sep.trace_error_propagation("origin", "GENERIC", {})
    assert ir.recovery_chain_status == sep.CHAIN_NOT_AVAILABLE
    assert any(u["field"] == "topology" for u in ir.unknowns)


# ===========================================================================
# Negative control 5: a multi-hop transitive chain is followed via real
# edges only, and a placeholder response ("TBD") is treated the same as a
# genuinely missing one -- never promoted to DECLARED.
# ===========================================================================

def test_transitive_multi_hop_chain_and_placeholder_response_is_incomplete():
    topology = _topology(reset_comparisons=[
        _cr_row("a", "b", "rst_n", "rst_n", "SAME_RESET_DOMAIN", pair_id="SYSCR-A-B"),
        _cr_row("b", "c", "rst_n", "rst_n", "SAME_RESET_DOMAIN", pair_id="SYSCR-B-C"),
    ])
    ir = sep.trace_error_propagation(
        "a", "RESET_ASSERTION", topology,
        declared_responses=[_response("b"), _response("c", response_action="TBD")])
    report = ir.to_dict()
    affected_ids = {a["subsystem_id"] for a in report["affected_subsystems"]}
    assert affected_ids == {"b", "c"}
    by_id = {a["subsystem_id"]: a for a in report["affected_subsystems"]}
    assert by_id["c"]["hop_count"] == 2
    assert by_id["c"]["response_status"] == sep.RESPONSE_PLACEHOLDER
    assert report["recovery_chain_status"] == sep.CHAIN_INCOMPLETE
    assert report["missing_response_subsystems"] == ["c"]


def test_explicitly_declared_no_response_is_distinct_from_missing():
    topology = _topology(address_overlaps=[
        _address_row("origin", "neighbor", "ADDRESS_OVERLAP_CONFLICT"),
    ])
    ir = sep.trace_error_propagation(
        "origin", "BUS_ERROR", topology,
        declared_responses=[{"subsystem_id": "neighbor", "declares_response": False}])
    report = ir.to_dict()
    assert report["affected_subsystems"][0]["response_status"] == sep.RESPONSE_EXPLICITLY_NONE
    assert report["recovery_chain_status"] == sep.CHAIN_INCOMPLETE


def test_unrecognized_condition_kind_is_treated_as_generic_with_a_named_unknown():
    topology = _topology(address_overlaps=[
        _address_row("origin", "neighbor", "SHARED_MEMORY"),
    ])
    ir = sep.trace_error_propagation("origin", {"kind": "TOTALLY_MADE_UP_KIND"}, topology,
                                     declared_responses=[_response("neighbor")])
    assert ir.condition_kind == sep.CONDITION_GENERIC
    assert any(u["field"] == "condition_kind" for u in ir.unknowns)
    assert ir.recovery_chain_status == sep.CHAIN_COMPLETE


def test_cdc_boundary_edge_used_for_cdc_violation_condition():
    topology = _topology(
        address_overlaps=[_address_row("origin", "neighbor", "SHARED_MEMORY",
                                       pair_id="SYSADDR-CDC")],
        clock_comparisons=[_cr_row("origin", "neighbor", "clk_a", "clk_b", "CDC_BOUNDARY",
                                   pair_id="SYSCR-CDC")],
    )
    ir = sep.trace_error_propagation("origin", "CDC_VIOLATION", topology,
                                     declared_responses=[_response("neighbor")])
    report = ir.to_dict()
    assert report["affected_count"] == 1
    kinds = {e["kind"] for e in report["edges_considered"]}
    assert sep.EDGE_CLOCK_DOMAIN_CROSSING in kinds
    assert sep.EDGE_SHARED_ADDRESS_SPACE not in kinds


# ===========================================================================
# Malformed-input refusals
# ===========================================================================

def test_missing_origin_raises():
    with pytest.raises(sep.SystemErrorPropagationError):
        sep.trace_error_propagation("", "GENERIC", _topology())


def test_non_mapping_topology_raises():
    with pytest.raises(sep.SystemErrorPropagationError):
        sep.trace_error_propagation("origin", "GENERIC", "not-a-mapping")  # type: ignore[arg-type]


# ===========================================================================
# Real CLI subprocess, exit codes
# ===========================================================================

def _write(path: Path, obj) -> Path:
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def _run_cli(topology_path, origin, condition, declared_responses_path=None):
    argv = [sys.executable, "-m", "dv_harness.system_error_propagation", "trace",
            "--origin", origin, "--condition", condition,
            "--topology", str(topology_path), "--json"]
    if declared_responses_path is not None:
        argv += ["--declared-responses", str(declared_responses_path)]
    repo_root = Path(__file__).resolve().parents[1]
    return subprocess.run(argv, cwd=str(repo_root), capture_output=True, text=True)


def test_cli_exit_code_0_on_complete(tmp_path):
    topology = _topology(address_overlaps=[_address_row("a", "b", "SHARED_MEMORY")])
    topology_path = _write(tmp_path / "topology.json", topology)
    responses_path = _write(tmp_path / "responses.json", [_response("b")])
    result = _run_cli(topology_path, "a", "ADDRESS_DECODE_FAULT", responses_path)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["recovery_chain_status"] == sep.CHAIN_COMPLETE


def test_cli_exit_code_1_on_incomplete(tmp_path):
    topology = _topology(address_overlaps=[_address_row("a", "b", "SHARED_MEMORY")])
    topology_path = _write(tmp_path / "topology.json", topology)
    result = _run_cli(topology_path, "a", "ADDRESS_DECODE_FAULT")
    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["recovery_chain_status"] == sep.CHAIN_INCOMPLETE


def test_cli_exit_code_2_on_origin_not_in_topology(tmp_path):
    topology = _topology(address_overlaps=[_address_row("a", "b", "SHARED_MEMORY")])
    topology_path = _write(tmp_path / "topology.json", topology)
    result = _run_cli(topology_path, "nonexistent", "GENERIC")
    assert result.returncode == 2, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["recovery_chain_status"] == sep.CHAIN_NOT_AVAILABLE
