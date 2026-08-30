"""Tests for dv_harness/uvm_generator/mipi_dphy_generator.py -- the D-PHY
lane electrical-state-machine model generator (D-PHY only; C-PHY out of
scope, see the generator module's docstring)."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness.uvm_generator.mipi_dphy_generator import (
    DPHYError,
    DPHY_STATES,
    DPHY_TRANSITIONS,
    MIPIDPHYGenerator,
    compute_ecc,
    ECC_DATA_WIDTH_BITS,
    ECC_PARITY_WIDTH_BITS,
    simulate_lane_sequence,
    validate_transition,
)


# ---- pure-function tests: validate_transition / simulate_lane_sequence -----

def test_validate_transition_accepts_known_legal_edges():
    # STOP is the common hub state -- HS burst entry, turnaround, and
    # escape-mode entry are all legal directly from STOP.
    validate_transition("STOP", "HS_REQUEST")
    validate_transition("STOP", "TURNAROUND")
    validate_transition("STOP", "ESCAPE_MODE")
    # full HS burst sequence
    validate_transition("HS_REQUEST", "HS_PREPARE")
    validate_transition("HS_PREPARE", "HS_SYNC")
    validate_transition("HS_SYNC", "HS_DATA")
    validate_transition("HS_DATA", "STOP")
    # escape mode gateways into ULPS, both return to STOP
    validate_transition("ESCAPE_MODE", "ULPS")
    validate_transition("ULPS", "STOP")
    validate_transition("TURNAROUND", "STOP")


def test_validate_transition_rejects_illegal_edge():
    with pytest.raises(DPHYError) as exc:
        validate_transition("STOP", "HS_DATA")  # cannot skip straight to HS_DATA
    assert exc.value.reason == "ILLEGAL_TRANSITION"
    assert exc.value.detail["state_from"] == "STOP"
    assert exc.value.detail["state_to"] == "HS_DATA"


def test_validate_transition_rejects_unknown_state_names():
    with pytest.raises(DPHYError) as exc:
        validate_transition("STOP", "NOT_A_REAL_STATE")
    assert exc.value.reason == "UNKNOWN_STATE"

    with pytest.raises(DPHYError) as exc2:
        validate_transition("NOT_A_REAL_STATE", "STOP")
    assert exc2.value.reason == "UNKNOWN_STATE"


def test_dphy_transitions_only_references_known_states():
    # Every key and every value in the dict-of-sets must be a real DPHY_STATES
    # member -- guards against a typo silently creating an unreachable/dead edge.
    known = set(DPHY_STATES)
    for src, dests in DPHY_TRANSITIONS.items():
        assert src in known
        assert dests <= known


def test_simulate_lane_sequence_full_hs_burst_succeeds():
    result = simulate_lane_sequence(
        ["HS_REQUEST", "HS_PREPARE", "HS_SYNC", "HS_DATA", "STOP"]
    )
    assert result["ok"] is True
    assert result["final_state"] == "STOP"
    assert result["visited"] == ["STOP", "HS_REQUEST", "HS_PREPARE", "HS_SYNC", "HS_DATA", "STOP"]
    assert result["error"] is None


def test_simulate_lane_sequence_escape_mode_to_ulps_succeeds():
    result = simulate_lane_sequence(["ESCAPE_MODE", "ULPS", "STOP"])
    assert result["ok"] is True
    assert result["visited"] == ["STOP", "ESCAPE_MODE", "ULPS", "STOP"]


def test_simulate_lane_sequence_stops_at_first_illegal_transition():
    # HS_REQUEST -> HS_SYNC (skipping HS_PREPARE) is illegal; the trailing
    # HS_DATA/STOP events must never be reached/recorded.
    result = simulate_lane_sequence(["HS_REQUEST", "HS_SYNC", "HS_DATA", "STOP"])
    assert result["ok"] is False
    assert result["final_state"] == "HS_REQUEST"
    assert result["visited"] == ["STOP", "HS_REQUEST"]
    assert result["error"]["reason"] == "ILLEGAL_TRANSITION"
    assert result["error"]["detail"]["state_from"] == "HS_REQUEST"
    assert result["error"]["detail"]["state_to"] == "HS_SYNC"


def test_simulate_lane_sequence_rejects_unknown_start_state():
    with pytest.raises(DPHYError) as exc:
        simulate_lane_sequence(["STOP"], start_state="BOGUS")
    assert exc.value.reason == "UNKNOWN_STATE"


# ---- compute_ecc: STRUCTURAL-ONLY tests, per the confidence note ----------
# (compute_ecc is an explicitly-labeled placeholder, NOT the verified real
# CSI-2/DSI generator matrix -- see its docstring. Only the structural
# properties the module claims are honestly tested here, never an exact
# hand-computed real-spec value.)

def test_compute_ecc_is_deterministic_for_identical_input():
    a = compute_ecc(0x123456)
    b = compute_ecc(0x123456)
    assert a == b


def test_compute_ecc_output_is_fixed_width():
    for value in (0, 1, 0xFFFFFF, 0xABCDEF, 0x800000):
        ecc = compute_ecc(value)
        assert 0 <= ecc < (1 << ECC_PARITY_WIDTH_BITS)


def test_compute_ecc_rejects_out_of_range_header():
    with pytest.raises(DPHYError) as exc:
        compute_ecc(1 << ECC_DATA_WIDTH_BITS)  # one bit past the 24-bit field
    assert exc.value.reason == "HEADER_WIDTH_OUT_OF_RANGE"

    with pytest.raises(DPHYError):
        compute_ecc(-1)


def test_compute_ecc_rejects_non_int_input():
    with pytest.raises(DPHYError) as exc:
        compute_ecc("0x1234")
    assert exc.value.reason == "INVALID_HEADER_TYPE"


# ---- generation/integration tests ------------------------------------------

def _sample_topology(**overrides):
    t = {"module_name": "csi2_dphy", "role": "TX", "lane_count": 4}
    t.update(overrides)
    return t


def test_generate_emits_expected_files_with_real_values():
    tmp = Path(tempfile.mkdtemp())
    try:
        files = MIPIDPHYGenerator(tmp).generate(_sample_topology())
        assert "csi2_dphy_lane_state.sv" in files
        assert "dphy_topology.json" in files
        assert "environment_manifest.json" in files

        sv_text = (tmp / "csi2_dphy_lane_state.sv").read_text(encoding="utf-8")
        # every DPHY_STATES name must appear literally (real computed enum, not a stub)
        for name in DPHY_STATES:
            assert name in sv_text
        assert "LANE_COUNT = 4" in sv_text
        # a legal edge from the real DPHY_TRANSITIONS dict must appear in the case text
        assert "lane_next_state[i] == HS_REQUEST" in sv_text

        topo = json.loads((tmp / "dphy_topology.json").read_text(encoding="utf-8"))
        assert topo["lane_count"] == 4
        assert topo["role"] == "TX"
        assert set(topo["states"]) == set(DPHY_STATES)
        assert topo["transitions"]["STOP"] == sorted(DPHY_TRANSITIONS["STOP"])

        manifest = json.loads((tmp / "environment_manifest.json").read_text(encoding="utf-8"))
        assert manifest["qualification_status"] == "ENV_GENERATED"
        assert manifest["vip"]["binding_status"] == "PLACEHOLDER_UNTIL_CURRENT_VIP_EVIDENCE"
        assert manifest["cphy_status"] == "OUT_OF_SCOPE_THIS_PASS"
        assert manifest["ecc_status"] == "PLACEHOLDER_NEEDS_SPEC_VERIFICATION"
    finally:
        shutil.rmtree(tmp)


def test_generate_rejects_invalid_role():
    tmp = Path(tempfile.mkdtemp())
    try:
        with pytest.raises(DPHYError) as exc:
            MIPIDPHYGenerator(tmp).generate(_sample_topology(role="BOTH"))
        assert exc.value.reason == "INVALID_ROLE"
    finally:
        shutil.rmtree(tmp)


def test_generate_rejects_invalid_lane_count():
    tmp = Path(tempfile.mkdtemp())
    try:
        with pytest.raises(DPHYError) as exc:
            MIPIDPHYGenerator(tmp).generate(_sample_topology(lane_count=0))
        assert exc.value.reason == "INVALID_LANE_COUNT"

        with pytest.raises(DPHYError):
            MIPIDPHYGenerator(tmp).generate(_sample_topology(lane_count="4"))
    finally:
        shutil.rmtree(tmp)


def test_generate_is_deterministic_across_runs():
    tmp1 = Path(tempfile.mkdtemp())
    tmp2 = Path(tempfile.mkdtemp())
    try:
        MIPIDPHYGenerator(tmp1).generate(_sample_topology())
        MIPIDPHYGenerator(tmp2).generate(_sample_topology())
        sv1 = (tmp1 / "csi2_dphy_lane_state.sv").read_text(encoding="utf-8")
        sv2 = (tmp2 / "csi2_dphy_lane_state.sv").read_text(encoding="utf-8")
        assert sv1 == sv2
    finally:
        shutil.rmtree(tmp1)
        shutil.rmtree(tmp2)
