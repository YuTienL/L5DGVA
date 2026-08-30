"""Tests for dv_harness/uvm_generator/canfd_arbitration_generator.py -- the
CAN-FD arbitration + error-state-machine generator (parity-audit follow-up,
2026-08-29). Mirrors test_amba_fabric_generator.py's 3-tier style:
pure-function tests, then generation/integration tests."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from dv_harness.uvm_generator.canfd_arbitration_generator import (
    CANFDArbitrationGenerator,
    ArbitrationError, ErrorStateError, CRCError, TopologyError,
    resolve_arbitration, apply_error_event, compute_crc, resolve_id_width,
    ERROR_PASSIVE_THRESHOLD, BUS_OFF_THRESHOLD,
)

ROOT = Path(__file__).resolve().parents[1]


# ---- resolve_arbitration ----------------------------------------------------

def test_resolve_arbitration_lowest_identifier_wins():
    # node A = 010, node B = 011, node C = 001 (dominant='0' wins).
    # Bit0: A=0,B=0,C=0 -> bus=0, nobody has '1' here, all continue.
    # Bit1: A=1,B=1,C=0 -> bus=0 (C drove dominant), A and B lose at bit1.
    # Remaining: C alone -> winner.
    contenders = [
        {"node_id": "A", "identifier_bits": "010"},
        {"node_id": "B", "identifier_bits": "011"},
        {"node_id": "C", "identifier_bits": "001"},
    ]
    result = resolve_arbitration(contenders)
    assert result["winner_node_id"] == "C"
    losers_by_id = {l["node_id"]: l["lost_at_bit"] for l in result["losers"]}
    assert losers_by_id == {"A": 1, "B": 1}


def test_resolve_arbitration_losers_can_drop_at_different_bit_positions():
    # A=000, B=100, C=110
    # bit0: A=0,B=1,C=1 -> bus=0 (A dominant); B,C lose at bit0.
    # remaining: A alone -> winner immediately.
    contenders = [
        {"node_id": "A", "identifier_bits": "000"},
        {"node_id": "B", "identifier_bits": "100"},
        {"node_id": "C", "identifier_bits": "110"},
    ]
    result = resolve_arbitration(contenders)
    assert result["winner_node_id"] == "A"
    losers_by_id = {l["node_id"]: l["lost_at_bit"] for l in result["losers"]}
    assert losers_by_id == {"B": 0, "C": 0}


def test_resolve_arbitration_single_contender_wins_trivially():
    result = resolve_arbitration([{"node_id": "only", "identifier_bits": "101"}])
    assert result == {"winner_node_id": "only", "losers": []}


def test_resolve_arbitration_empty_list_raises():
    with pytest.raises(ArbitrationError) as exc:
        resolve_arbitration([])
    assert exc.value.reason == "EMPTY_CONTENDER_LIST"


def test_resolve_arbitration_length_mismatch_raises():
    contenders = [{"node_id": "A", "identifier_bits": "010"},
                  {"node_id": "B", "identifier_bits": "01"}]
    with pytest.raises(ArbitrationError) as exc:
        resolve_arbitration(contenders)
    assert exc.value.reason == "IDENTIFIER_LENGTH_MISMATCH"


def test_resolve_arbitration_duplicate_node_id_raises():
    contenders = [{"node_id": "A", "identifier_bits": "010"},
                  {"node_id": "A", "identifier_bits": "011"}]
    with pytest.raises(ArbitrationError) as exc:
        resolve_arbitration(contenders)
    assert exc.value.reason == "DUPLICATE_NODE_ID"


def test_resolve_arbitration_invalid_bits_raises():
    contenders = [{"node_id": "A", "identifier_bits": "01x"},
                  {"node_id": "B", "identifier_bits": "010"}]
    with pytest.raises(ArbitrationError) as exc:
        resolve_arbitration(contenders)
    assert exc.value.reason == "INVALID_IDENTIFIER_BITS"


def test_resolve_arbitration_identical_identifiers_no_winner():
    contenders = [{"node_id": "A", "identifier_bits": "010"},
                  {"node_id": "B", "identifier_bits": "010"}]
    with pytest.raises(ArbitrationError) as exc:
        resolve_arbitration(contenders)
    assert exc.value.reason == "IDENTICAL_IDENTIFIERS_NO_WINNER"
    assert set(exc.value.detail["tied_node_ids"]) == {"A", "B"}


# ---- apply_error_event ------------------------------------------------------

def test_apply_error_event_tx_error_increments_tec_by_8():
    state = {"tec": 10, "rec": 0, "mode": "ERROR_ACTIVE"}
    new = apply_error_event(state, "TX_ERROR")
    assert new == {"tec": 18, "rec": 0, "mode": "ERROR_ACTIVE"}


def test_apply_error_event_rx_error_normal_increments_rec_by_1():
    state = {"tec": 0, "rec": 10, "mode": "ERROR_ACTIVE"}
    new = apply_error_event(state, "RX_ERROR", severity="normal")
    assert new["rec"] == 11


def test_apply_error_event_rx_error_severe_increments_rec_by_8():
    state = {"tec": 0, "rec": 10, "mode": "ERROR_ACTIVE"}
    new = apply_error_event(state, "RX_ERROR", severity="severe")
    assert new["rec"] == 18


def test_apply_error_event_tx_success_decrements_and_floors_at_0():
    state = {"tec": 0, "rec": 0, "mode": "ERROR_ACTIVE"}
    new = apply_error_event(state, "TX_SUCCESS")
    assert new["tec"] == 0  # floored, not -1
    state2 = {"tec": 5, "rec": 0, "mode": "ERROR_ACTIVE"}
    assert apply_error_event(state2, "TX_SUCCESS")["tec"] == 4


def test_apply_error_event_rx_success_decrements_and_floors_at_0():
    state = {"tec": 0, "rec": 0, "mode": "ERROR_ACTIVE"}
    new = apply_error_event(state, "RX_SUCCESS")
    assert new["rec"] == 0
    state2 = {"tec": 0, "rec": 5, "mode": "ERROR_ACTIVE"}
    assert apply_error_event(state2, "RX_SUCCESS")["rec"] == 4


def test_apply_error_event_tec_crosses_127_to_error_passive():
    # 120 + 8 = 128 > 127 -> ERROR_PASSIVE
    state = {"tec": 120, "rec": 0, "mode": "ERROR_ACTIVE"}
    new = apply_error_event(state, "TX_ERROR")
    assert new["tec"] == ERROR_PASSIVE_THRESHOLD + 1 == 128
    assert new["mode"] == "ERROR_PASSIVE"
    # boundary just below: 119 + 8 = 127, NOT > 127 -> stays ERROR_ACTIVE
    state_below = {"tec": 119, "rec": 0, "mode": "ERROR_ACTIVE"}
    below = apply_error_event(state_below, "TX_ERROR")
    assert below["tec"] == 127 and below["mode"] == "ERROR_ACTIVE"


def test_apply_error_event_rec_crosses_127_to_error_passive():
    state = {"tec": 0, "rec": 120, "mode": "ERROR_ACTIVE"}
    new = apply_error_event(state, "RX_ERROR", severity="severe")  # 120+8=128
    assert new["rec"] == 128
    assert new["mode"] == "ERROR_PASSIVE"


def test_apply_error_event_tec_crosses_255_to_bus_off():
    # 250 + 8 = 258 > 255 -> BUS_OFF
    state = {"tec": 250, "rec": 0, "mode": "ERROR_PASSIVE"}
    new = apply_error_event(state, "TX_ERROR")
    assert new["tec"] == 258
    assert new["mode"] == "BUS_OFF"
    # boundary just below: 247+8=255, NOT >255 -> stays ERROR_PASSIVE
    state_below = {"tec": 247, "rec": 0, "mode": "ERROR_PASSIVE"}
    below = apply_error_event(state_below, "TX_ERROR")
    assert below["tec"] == 255 and below["mode"] == "ERROR_PASSIVE"


def test_apply_error_event_bus_off_refuses_further_events():
    state = {"tec": 260, "rec": 0, "mode": "BUS_OFF"}
    with pytest.raises(ErrorStateError) as exc:
        apply_error_event(state, "TX_SUCCESS")
    assert exc.value.reason == "BUS_OFF_RECOVERY_NOT_MODELED"


def test_apply_error_event_invalid_mode_event_severity_raise():
    with pytest.raises(ErrorStateError) as exc1:
        apply_error_event({"tec": 0, "rec": 0, "mode": "WEIRD"}, "TX_ERROR")
    assert exc1.value.reason == "INVALID_MODE"

    with pytest.raises(ErrorStateError) as exc2:
        apply_error_event({"tec": 0, "rec": 0, "mode": "ERROR_ACTIVE"}, "NOT_AN_EVENT")
    assert exc2.value.reason == "INVALID_EVENT"

    with pytest.raises(ErrorStateError) as exc3:
        apply_error_event({"tec": 0, "rec": 0, "mode": "ERROR_ACTIVE"}, "RX_ERROR", severity="extreme")
    assert exc3.value.reason == "INVALID_SEVERITY"


def test_apply_error_event_negative_counters_raise():
    with pytest.raises(ErrorStateError) as exc:
        apply_error_event({"tec": -1, "rec": 0, "mode": "ERROR_ACTIVE"}, "TX_ERROR")
    assert exc.value.reason == "INVALID_TEC"


# ---- compute_crc -------------------------------------------------------------

def test_compute_crc_hand_worked_width3_example():
    # HAND-WORKED EXAMPLE (shown step by step, not just asserted):
    # message M = "1101", generator polynomial G(x) = x^3 + x + 1 (binary
    # 1011: leading implicit-1 bit + low-3-bits "011" as the `polynomial`
    # argument). Standard "augmented message" CRC construction: divide
    # (M followed by 3 zero bits) = "1101000" by "1011" using XOR (mod-2)
    # long division, tracking a sliding 4-bit window exactly like the
    # compute_crc() implementation does:
    #
    #   work = 1 1 0 1 0 0 0   (index:0..6)
    #   i=0: work[0]='1' -> XOR window[0:4]=1101 with 1011 = 0110
    #        work = 0 1 1 0 0 0 0
    #   i=1: work[1]='1' -> XOR window[1:5]=1100 with 1011 = 0111
    #        work = 0 0 1 1 1 0 0
    #   i=2: work[2]='1' -> XOR window[2:6]=1110 with 1011 = 0101
    #        work = 0 0 0 1 0 1 0
    #   i=3: work[3]='1' -> XOR window[3:7]=1010 with 1011 = 0001
    #        work = 0 0 0 0 0 0 1
    #   remainder = work[4:7] = "001"
    result = compute_crc("1101", poly_width=3, polynomial=0b011)
    assert result == "001"


def test_compute_crc_is_self_consistent_appending_remainder_gives_zero():
    # Fundamental CRC receiver-side property (works for any width/poly):
    # appending the computed CRC remainder to the original message and
    # re-dividing by the same polynomial must yield an all-zero remainder.
    # This is a strong, independent correctness check for the widths this
    # generator actually cares about (15, and 17/21 via an explicit
    # verified-by-caller polynomial), without requiring a second by-hand
    # division for a 15+ bit polynomial.
    message = "101100110101"
    crc15 = compute_crc(message, poly_width=15)  # default 0x4599 polynomial
    assert len(crc15) == 15
    check = compute_crc(message + crc15, poly_width=15)
    assert check == "0" * 15

    # width=17 with an explicit (caller-supplied) polynomial -- exercise the
    # override path since no default is hardcoded for this width.
    crc17 = compute_crc(message, poly_width=17, polynomial=0x1685B)
    assert len(crc17) == 17
    check17 = compute_crc(message + crc17, poly_width=17, polynomial=0x1685B)
    assert check17 == "0" * 17


def test_compute_crc_missing_polynomial_for_width_17_raises():
    with pytest.raises(CRCError) as exc:
        compute_crc("1010", poly_width=17)
    assert exc.value.reason == "POLYNOMIAL_NOT_VERIFIED"


def test_compute_crc_generic_width_with_explicit_polynomial_works():
    # compute_crc is a generic algorithm -- widths other than 15/17/21 are
    # fine as long as the caller supplies an explicit polynomial (the
    # CAN-FD-specific 15/17/21 restriction lives in the generator's
    # _validate_crc_width, not in this pure function).
    result = compute_crc("1101", poly_width=4, polynomial=0b0011)
    assert len(result) == 4


def test_compute_crc_invalid_poly_width_raises():
    with pytest.raises(CRCError) as exc:
        compute_crc("1010", poly_width=0)
    assert exc.value.reason == "INVALID_POLY_WIDTH"
    with pytest.raises(CRCError) as exc2:
        compute_crc("1010", poly_width=-3)
    assert exc2.value.reason == "INVALID_POLY_WIDTH"


def test_compute_crc_invalid_bit_string_raises():
    with pytest.raises(CRCError) as exc:
        compute_crc("10x0", poly_width=15)
    assert exc.value.reason == "INVALID_BIT_STRING"


# ---- resolve_id_width --------------------------------------------------------

def test_resolve_id_width_standard_and_extended():
    assert resolve_id_width({"id_format": "STANDARD"}) == 11
    assert resolve_id_width({"id_format": "EXTENDED"}) == 29
    assert resolve_id_width({"id_width": 12}) == 12


def test_resolve_id_width_requires_exactly_one_source():
    with pytest.raises(TopologyError) as exc:
        resolve_id_width({})
    assert exc.value.reason == "MISSING_ID_WIDTH_OR_FORMAT"

    with pytest.raises(TopologyError) as exc2:
        resolve_id_width({"id_width": 11, "id_format": "STANDARD"})
    assert exc2.value.reason == "AMBIGUOUS_ID_WIDTH_SPEC"

    with pytest.raises(TopologyError) as exc3:
        resolve_id_width({"id_format": "WEIRD"})
    assert exc3.value.reason == "UNKNOWN_ID_FORMAT"


# ---- generation + integration -------------------------------------------------

def _sample_topology():
    return {
        "bus_name": "vehicle_canfd0",
        "node_ids": ["ecu_gateway", "ecu_engine", "ecu_infotainment"],
        "id_format": "STANDARD",
        "crc_width": 17,
    }


def test_generate_emits_expected_files_with_real_values():
    tmp = Path(tempfile.mkdtemp())
    try:
        files = CANFDArbitrationGenerator(tmp).generate(_sample_topology())
        assert "vehicle_canfd0_arbitration_tb.sv" in files
        assert "vehicle_canfd0_error_state_machine.sv" in files
        assert "canfd_topology.json" in files
        assert "environment_manifest.json" in files

        arb_text = (tmp / "vehicle_canfd0_arbitration_tb.sv").read_text(encoding="utf-8")
        assert "NUM_NODES = 3" in arb_text
        assert "ID_WIDTH  = 11" in arb_text  # STANDARD format -> 11-bit, literal computed value
        assert "winner:" in arb_text  # embedded real resolve_arbitration() worked example

        esm_text = (tmp / "vehicle_canfd0_error_state_machine.sv").read_text(encoding="utf-8")
        assert "'tec': 128" in esm_text or "128" in esm_text  # embedded real apply_error_event() worked example
        assert "'mode': 'BUS_OFF'" in esm_text

        topo = json.loads((tmp / "canfd_topology.json").read_text(encoding="utf-8"))
        assert topo["bus_name"] == "vehicle_canfd0"
        assert topo["node_ids"] == ["ecu_gateway", "ecu_engine", "ecu_infotainment"]
        assert topo["id_width"] == 11
        assert topo["crc_width"] == 17
        assert topo["num_nodes"] == 3

        manifest = json.loads((tmp / "environment_manifest.json").read_text(encoding="utf-8"))
        assert manifest["qualification_status"] == "ENV_GENERATED"
        assert manifest["vip"]["binding_status"] == "PLACEHOLDER_UNTIL_CURRENT_VIP_EVIDENCE"
        assert manifest["id_width"] == 11
        assert manifest["crc_polynomial_status"] == "NEEDS_SPEC_VERIFICATION"  # crc_width=17, no default poly
    finally:
        shutil.rmtree(tmp)


def test_generate_with_default_crc15_has_no_verification_flag():
    tmp = Path(tempfile.mkdtemp())
    try:
        t = _sample_topology()
        t["crc_width"] = 15
        CANFDArbitrationGenerator(tmp).generate(t)
        manifest = json.loads((tmp / "environment_manifest.json").read_text(encoding="utf-8"))
        assert "crc_polynomial_status" not in manifest
    finally:
        shutil.rmtree(tmp)


def test_generate_rejects_missing_node_ids():
    tmp = Path(tempfile.mkdtemp())
    try:
        t = {"bus_name": "b0", "id_format": "STANDARD"}
        with pytest.raises(TopologyError) as exc:
            CANFDArbitrationGenerator(tmp).generate(t)
        assert exc.value.reason == "MISSING_NODE_IDS"
    finally:
        shutil.rmtree(tmp)


def test_generate_rejects_unsupported_crc_width():
    tmp = Path(tempfile.mkdtemp())
    try:
        t = _sample_topology()
        t["crc_width"] = 8
        with pytest.raises(TopologyError) as exc:
            CANFDArbitrationGenerator(tmp).generate(t)
        assert exc.value.reason == "UNSUPPORTED_CRC_WIDTH"
    finally:
        shutil.rmtree(tmp)


def test_cli_shim_generates_expected_outputs():
    tmp = Path(tempfile.mkdtemp())
    try:
        topo_path = tmp / "topology.json"
        topo_path.write_text(json.dumps(_sample_topology()), encoding="utf-8")
        out_dir = tmp / "out"
        script = ROOT / "tools" / "generate_canfd_arbitration_environment.py"
        r = subprocess.run(
            [sys.executable, str(script), "--topology", str(topo_path), "--out", str(out_dir)],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, r.stderr
        assert (out_dir / "canfd_topology.json").exists()
        assert (out_dir / "environment_manifest.json").exists()
        assert (out_dir / "vehicle_canfd0_arbitration_tb.sv").exists()
        assert (out_dir / "vehicle_canfd0_error_state_machine.sv").exists()
    finally:
        shutil.rmtree(tmp)
