"""Tests for dv_harness/uvm_generator/amba_fabric_generator.py -- the real
AMBA M x N generator (see plan-amba-mxn-generator design pass, 2026-08-28)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from dv_harness.uvm_generator.amba_fabric_generator import (
    AMBAFabricGenerator, AddressMapError, ScoreboardMatrixError,
    compute_address_regions, compute_id_width, build_scoreboard_matrix, parse_addr,
    FabricGraphMismatchError, cross_check_fabric_graph,
)
from dv_harness.amba_fabric_graph_ir import build_amba_fabric_graph

ROOT = Path(__file__).resolve().parents[1]


# ---- pure-function tests (no I/O) ------------------------------------------

def test_compute_id_width_examples():
    assert compute_id_width([{"id": "m0", "id_width": 4}, {"id": "m1", "id_width": 6}]) == 7  # ceil(log2(2))+6=1+6=7
    assert compute_id_width([{"id_width": 4}, {"id_width": 6}, {"id_width": 4}, {"id_width": 4}]) == 8  # ceil(log2(4))+6=2+6=8
    assert compute_id_width([{"id_width": 3}]) == 3  # M=1: ceil(log2(1))+3=0+3=3


def test_compute_id_width_requires_at_least_one_master():
    with pytest.raises(ValueError):
        compute_id_width([])


def test_compute_address_regions_detects_overlap():
    slaves = [{"id": "s0", "base_addr": "0x0", "size": "0x1000"},
              {"id": "s1", "base_addr": "0x800", "size": "0x1000"}]
    with pytest.raises(AddressMapError) as exc:
        compute_address_regions(slaves, [], addr_width=16)
    assert exc.value.reason == "ADDRESS_MAP_OVERLAP"


def test_compute_address_regions_detects_undeclared_gap():
    slaves = [{"id": "s0", "base_addr": "0x0", "size": "0x1000"},
              {"id": "s1", "base_addr": "0x2000", "size": "0x1000"}]
    reserved = [{"name": "rsvd_top", "base_addr": "0x3000", "size": "0xd000", "decerr": True}]
    with pytest.raises(AddressMapError) as exc:
        compute_address_regions(slaves, reserved, addr_width=16)
    assert exc.value.reason == "ADDRESS_MAP_GAP"


def test_compute_address_regions_passes_full_coverage():
    slaves = [{"id": "s0", "base_addr": "0x0", "size": "0x1000"},
              {"id": "s1", "base_addr": "0x1000", "size": "0x1000"}]
    reserved = [{"name": "rsvd_top", "base_addr": "0x2000", "size": "0xe000", "decerr": True}]
    regions = compute_address_regions(slaves, reserved, addr_width=16)
    assert [r["owner"] for r in regions] == ["s0", "s1", "rsvd_top"]
    assert regions[0]["start"] == 0 and regions[-1]["end"] == 1 << 16


def test_compute_address_regions_fails_without_full_coverage():
    slaves = [{"id": "s0", "base_addr": "0x0", "size": "0x1000"}]
    with pytest.raises(AddressMapError) as exc:
        compute_address_regions(slaves, [], addr_width=16)
    assert exc.value.reason == "ADDRESS_MAP_NOT_FULL_COVERAGE"


def test_parse_addr_handles_hex_underscore_and_int():
    assert parse_addr("0x1000") == 0x1000
    assert parse_addr("0x0010_0000") == 0x00100000
    assert parse_addr(4096) == 4096


def test_build_scoreboard_matrix_requires_explicit_evidence():
    masters = [{"id": "m0"}]
    slaves = [{"id": "s0"}]
    with pytest.raises(ScoreboardMatrixError) as exc:
        build_scoreboard_matrix(masters, slaves, connectivity=None, assume_full_connectivity=False)
    assert exc.value.reason == "NO_CONNECTIVITY_EVIDENCE"


def test_build_scoreboard_matrix_full_when_opted_in():
    masters = [{"id": "m0"}, {"id": "m1"}]
    slaves = [{"id": "s0"}, {"id": "s1"}]
    matrix = build_scoreboard_matrix(masters, slaves, connectivity=None, assume_full_connectivity=True)
    assert len(matrix) == 4
    assert all(e["status"] == "IMPLEMENTED" for e in matrix)


def test_build_scoreboard_matrix_unresolved_pair_fails():
    masters = [{"id": "m0"}]
    slaves = [{"id": "s0"}, {"id": "s1"}]
    connectivity = {"m0": {"accessible_slaves": ["s0"]}}  # s1 neither accessible nor excluded
    with pytest.raises(ScoreboardMatrixError) as exc:
        build_scoreboard_matrix(masters, slaves, connectivity, assume_full_connectivity=False)
    assert exc.value.reason == "UNRESOLVED_PAIR"
    assert exc.value.detail["slave_id"] == "s1"


def test_build_scoreboard_matrix_resolves_accessible_and_waived():
    masters = [{"id": "m0"}, {"id": "m1"}]
    slaves = [{"id": "s0"}, {"id": "s1"}]
    connectivity = {
        "m0": {"accessible_slaves": ["s0", "s1"]},
        "m1": {"accessible_slaves": ["s0"], "excluded": [{"slave_id": "s1", "waiver_evidence": "no DMA path per u_decode"}]},
    }
    matrix = build_scoreboard_matrix(masters, slaves, connectivity, assume_full_connectivity=False)
    by_pair = {(e["master_id"], e["slave_id"]): e for e in matrix}
    assert by_pair[("m0", "s0")]["status"] == "IMPLEMENTED"
    assert by_pair[("m0", "s1")]["status"] == "IMPLEMENTED"
    assert by_pair[("m1", "s0")]["status"] == "IMPLEMENTED"
    assert by_pair[("m1", "s1")]["status"] == "WAIVED"
    assert by_pair[("m1", "s1")]["waiver_approved"] is True
    assert "no DMA path" in by_pair[("m1", "s1")]["waiver_evidence"]


# ---- generation + gate integration -----------------------------------------

def _sample_topology():
    return {
        "fabric_name": "soc_fabric",
        "addr_width": 16,
        "masters": [{"id": "m0", "name": "cpu0", "id_width": 4}, {"id": "m1", "name": "dma0", "id_width": 6}],
        "slaves": [{"id": "s0", "name": "sram", "base_addr": "0x0000", "size": "0x1000"},
                   {"id": "s1", "name": "uart", "base_addr": "0x1000", "size": "0x1000"}],
        "reserved_regions": [{"name": "rsvd0", "base_addr": "0x2000", "size": "0xe000", "decerr": True}],
        "connectivity": {
            "m0": {"accessible_slaves": ["s0", "s1"]},
            "m1": {"accessible_slaves": ["s0"], "excluded": [{"slave_id": "s1", "waiver_evidence": "DMA has no UART path"}]},
        },
    }


def test_generate_emits_expected_files_with_real_values():
    tmp = Path(tempfile.mkdtemp())
    try:
        files = AMBAFabricGenerator(tmp).generate(_sample_topology())
        assert "fabric_topology.json" in files
        assert "environment_manifest.json" in files
        assert "soc_fabric_addr_decoder.sv" in files

        decoder_text = (tmp / "soc_fabric_addr_decoder.sv").read_text(encoding="utf-8")
        # literal computed hex bounds, not placeholders
        assert "16'h0" in decoder_text
        assert "16'h1000" in decoder_text
        assert "16'h2000" in decoder_text

        pkg_text = (tmp / "soc_fabric_env_pkg.sv").read_text(encoding="utf-8")
        assert "ID_WIDTH_OUT = 7" in pkg_text  # ceil(log2(2))+6=7, literal computed value

        manifest = json.loads((tmp / "environment_manifest.json").read_text(encoding="utf-8"))
        assert manifest["qualification_status"] == "ENV_GENERATED"
        assert manifest["vip"]["binding_status"] == "PLACEHOLDER_UNTIL_CURRENT_VIP_EVIDENCE"
        assert manifest["id_width_out"] == 7
    finally:
        shutil.rmtree(tmp)


def test_generate_without_fabric_graph_reports_not_supplied():
    """The pre-existing, unaffected path (no t['fabric_graph'] declared):
    fabric_graph_cross_check must be an honest NOT_SUPPLIED, never absent
    and never a guessed/empty cross-check."""
    tmp = Path(tempfile.mkdtemp())
    try:
        files = AMBAFabricGenerator(tmp).generate(_sample_topology())
        manifest = json.loads((tmp / "environment_manifest.json").read_text(encoding="utf-8"))
        assert manifest["fabric_graph_cross_check"] == {
            "status": "NOT_SUPPLIED", "reason": "NO_FABRIC_GRAPH_DECLARED_IN_TOPOLOGY"}
        topology = json.loads((tmp / "fabric_topology.json").read_text(encoding="utf-8"))
        assert "internal_fabric_nodes" not in topology
    finally:
        shutil.rmtree(tmp)


# ---------------------------------------------------------------------------
# ARCH-04/ARCH-12 wire: cross_check_fabric_graph() (real amba_fabric_graph_ir.py
# input, never self-derived from RTL)
# ---------------------------------------------------------------------------

def _sample_fabric_graph_nodes():
    return [
        {"node_id": "m0", "kind": "master_endpoint", "evidence": ["topology declares m0"]},
        {"node_id": "m1", "kind": "master_endpoint", "evidence": ["topology declares m1"]},
        {"node_id": "s0", "kind": "slave_endpoint", "evidence": ["topology declares s0"]},
        {"node_id": "s1", "kind": "slave_endpoint", "evidence": ["topology declares s1"]},
        {"node_id": "xbar0", "kind": "crossbar", "evidence": ["RTL: soc_fabric_xbar instance"]},
    ]


def test_cross_check_fabric_graph_succeeds_when_endpoints_match():
    t = _sample_topology()
    graph = build_amba_fabric_graph(_sample_fabric_graph_nodes(), [])
    result = cross_check_fabric_graph(t, graph)
    assert result["master_endpoints_verified"] == ["m0", "m1"]
    assert result["slave_endpoints_verified"] == ["s0", "s1"]
    assert result["internal_nodes"] == [{"node_id": "xbar0", "kind": "crossbar"}]


def test_cross_check_fabric_graph_raises_on_missing_endpoint():
    t = _sample_topology()
    # s1 is never declared as a slave_endpoint node -- a real graph/topology
    # disagreement, not a soft-degraded warning.
    nodes = [n for n in _sample_fabric_graph_nodes() if n["node_id"] != "s1"]
    graph = build_amba_fabric_graph(nodes, [])
    with pytest.raises(FabricGraphMismatchError) as exc:
        cross_check_fabric_graph(t, graph)
    assert exc.value.reason == "FABRIC_GRAPH_ENDPOINT_MISMATCH"
    assert exc.value.detail["missing_slave_endpoints"] == ["s1"]
    assert exc.value.detail["missing_master_endpoints"] == []


def test_generate_with_fabric_graph_end_to_end():
    """The regression this test exists to guarantee: generate() must not
    raise when t['fabric_graph'] is supplied (env() itself takes no
    fabric-graph parameter -- the cross-check is surfaced only via the two
    JSON artifacts below, never threaded into env()'s own SV content)."""
    t = _sample_topology()
    t["fabric_graph"] = {"nodes": _sample_fabric_graph_nodes(), "edges": []}
    tmp = Path(tempfile.mkdtemp())
    try:
        files = AMBAFabricGenerator(tmp).generate(t)
        manifest = json.loads((tmp / "environment_manifest.json").read_text(encoding="utf-8"))
        assert manifest["fabric_graph_cross_check"]["master_endpoints_verified"] == ["m0", "m1"]
        assert manifest["fabric_graph_cross_check"]["slave_endpoints_verified"] == ["s0", "s1"]
        topology = json.loads((tmp / "fabric_topology.json").read_text(encoding="utf-8"))
        assert topology["internal_fabric_nodes"] == [{"node_id": "xbar0", "kind": "crossbar"}]
    finally:
        shutil.rmtree(tmp)


def test_generate_with_fabric_graph_mismatch_raises_before_writing_files():
    t = _sample_topology()
    bad_nodes = [n for n in _sample_fabric_graph_nodes() if n["node_id"] != "m1"]
    t["fabric_graph"] = {"nodes": bad_nodes, "edges": []}
    tmp = Path(tempfile.mkdtemp())
    try:
        with pytest.raises(FabricGraphMismatchError):
            AMBAFabricGenerator(tmp).generate(t)
    finally:
        shutil.rmtree(tmp)


def _run_fabric_gate(topology_path):
    script = ROOT / "tools" / "verification_flow" / "fabric_topology_completeness_gate.py"
    r = subprocess.run([sys.executable, str(script), "--topology", str(topology_path)],
                        capture_output=True, text=True, timeout=30)
    out = json.loads((r.stdout or "").strip() or "{}")
    return r.returncode, out


def test_generated_fabric_topology_passes_gate():
    tmp = Path(tempfile.mkdtemp())
    try:
        AMBAFabricGenerator(tmp).generate(_sample_topology())
        rc, out = _run_fabric_gate(tmp / "fabric_topology.json")
        assert rc == 0, out
        assert out["status"] == "PASS"
        assert out["masters"] == 2 and out["slaves"] == 2
        assert out["scoreboard_pairs"] == 4
    finally:
        shutil.rmtree(tmp)


def test_generated_fabric_topology_fails_gate_on_missing_pair():
    # Mutate a known-valid generated file rather than trying to make the
    # generator itself emit an invalid one (it refuses to, by design).
    tmp = Path(tempfile.mkdtemp())
    try:
        AMBAFabricGenerator(tmp).generate(_sample_topology())
        topo = json.loads((tmp / "fabric_topology.json").read_text(encoding="utf-8"))
        topo["scoreboard_matrix"].pop()
        mutated = tmp / "mutated_topology.json"
        mutated.write_text(json.dumps(topo), encoding="utf-8")
        rc, out = _run_fabric_gate(mutated)
        assert rc != 0
        assert out["reason"] == "MISSING_SCOREBOARD_PAIRS"
    finally:
        shutil.rmtree(tmp)


def test_cli_shim_generates_and_passes_gate():
    tmp = Path(tempfile.mkdtemp())
    try:
        topo_path = tmp / "topology.json"
        topo_path.write_text(json.dumps(_sample_topology()), encoding="utf-8")
        out_dir = tmp / "out"
        script = ROOT / "tools" / "generate_amba_fabric_environment.py"
        r = subprocess.run(
            [sys.executable, str(script), "--topology", str(topo_path), "--out", str(out_dir)],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, r.stderr
        assert (out_dir / "fabric_topology.json").exists()
        rc, out = _run_fabric_gate(out_dir / "fabric_topology.json")
        assert rc == 0 and out["status"] == "PASS"
    finally:
        shutil.rmtree(tmp)
