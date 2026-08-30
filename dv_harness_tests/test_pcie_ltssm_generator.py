"""Tests for dv_harness/uvm_generator/pcie_ltssm_generator.py -- the PCIe
LTSSM top-level state-machine generator (parity-audit gap, 2026-08-29)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from dv_harness.uvm_generator.pcie_ltssm_generator import (
    LTSSM_STATES, LTSSM_TRANSITIONS, LTSSMError, LTSSMTopologyError,
    PCIeLTSSMGenerator, compute_lane_crc, simulate_training_sequence,
    validate_ltssm_topology, validate_transition,
)

ROOT = Path(__file__).resolve().parents[1]


# ---- pure-function tests (no I/O) ------------------------------------------

def test_validate_transition_legal_cases():
    assert validate_transition("DETECT", "POLLING") is True
    assert validate_transition("POLLING", "CONFIGURATION") is True
    assert validate_transition("POLLING", "DETECT") is True
    assert validate_transition("CONFIGURATION", "L0") is True
    assert validate_transition("CONFIGURATION", "DETECT") is True
    assert validate_transition("L0", "RECOVERY") is True
    assert validate_transition("L0", "L0S") is True
    assert validate_transition("L0", "L1") is True
    assert validate_transition("RECOVERY", "L0") is True
    assert validate_transition("RECOVERY", "DETECT") is True
    # any-state -> Hot Reset / Disabled is a directed, explicitly-confident rule
    assert validate_transition("L0", "HOT_RESET") is True
    assert validate_transition("CONFIGURATION", "DISABLED") is True


def test_validate_transition_illegal_case_raises_typed_error():
    with pytest.raises(LTSSMError) as exc:
        validate_transition("DETECT", "L0")  # cannot skip Polling/Configuration
    assert exc.value.reason == "ILLEGAL_LTSSM_TRANSITION"
    assert exc.value.detail["from"] == "DETECT"
    assert exc.value.detail["to"] == "L0"
    assert "POLLING" in exc.value.detail["legal_targets"]


def test_validate_transition_unknown_state_raises_typed_error():
    with pytest.raises(LTSSMError) as exc:
        validate_transition("DETECT", "NOT_A_REAL_STATE")
    assert exc.value.reason == "UNKNOWN_LTSSM_STATE"
    assert exc.value.detail["field"] == "state_to"


def test_hot_reset_and_disabled_only_return_to_detect():
    assert LTSSM_TRANSITIONS["HOT_RESET"] == frozenset({"DETECT"})
    assert LTSSM_TRANSITIONS["DISABLED"] == frozenset({"DETECT"})


def test_every_state_has_a_row_in_the_transition_table():
    assert set(LTSSM_TRANSITIONS.keys()) == LTSSM_STATES
    assert len(LTSSM_STATES) == 11


def test_simulate_training_sequence_all_legal():
    events = [
        {"from": "DETECT", "to": "POLLING"},
        {"from": "POLLING", "to": "CONFIGURATION"},
        {"from": "CONFIGURATION", "to": "L0"},
    ]
    result = simulate_training_sequence(events)
    assert result["completed"] is True
    assert result["halted_at_index"] is None
    assert result["illegal_transition"] is None
    assert result["state_history"] == ["DETECT", "POLLING", "CONFIGURATION", "L0"]
    assert all(s["legal"] for s in result["steps"])


def test_simulate_training_sequence_stops_at_first_illegal_transition():
    events = [
        {"from": "DETECT", "to": "POLLING"},
        {"from": "POLLING", "to": "CONFIGURATION"},
        {"from": "CONFIGURATION", "to": "L2"},  # ILLEGAL: Configuration cannot jump to L2
        {"from": "L2", "to": "DETECT"},  # must never be evaluated -- sequence stopped before this
    ]
    result = simulate_training_sequence(events)
    assert result["completed"] is False
    assert result["halted_at_index"] == 2
    assert result["illegal_transition"]["from"] == "CONFIGURATION"
    assert result["illegal_transition"]["to"] == "L2"
    assert result["illegal_transition"]["reason"] == "ILLEGAL_LTSSM_TRANSITION"
    # state history only reflects legal progress up to (not past) the halt point
    assert result["state_history"] == ["DETECT", "POLLING", "CONFIGURATION"]
    # only 3 steps recorded (indices 0,1,2) -- the 4th event was never touched
    assert len(result["steps"]) == 3
    assert result["steps"][-1]["legal"] is False


def test_simulate_training_sequence_requires_nonempty_events():
    with pytest.raises(LTSSMError) as exc:
        simulate_training_sequence([])
    assert exc.value.reason == "EMPTY_EVENT_SEQUENCE"


def test_compute_lane_crc_bytes_and_bits_agree():
    # 0xDE 0xAD as bytes vs. the equivalent explicit bit list must match.
    from_bytes = compute_lane_crc(b"\xde\xad")
    bits = [1, 1, 0, 1, 1, 1, 1, 0, 1, 0, 1, 0, 1, 1, 0, 1]
    from_bits = compute_lane_crc(bits)
    assert from_bytes == from_bits
    assert isinstance(from_bytes, int)
    assert 0 <= from_bytes <= 0xFFFFFFFF


def test_compute_lane_crc_rejects_invalid_bit_values():
    with pytest.raises(LTSSMError) as exc:
        compute_lane_crc([0, 1, 2])
    assert exc.value.reason == "INVALID_CRC_INPUT"


def test_validate_ltssm_topology_rejects_bad_lane_width():
    with pytest.raises(LTSSMTopologyError) as exc:
        validate_ltssm_topology({"lane_width": 7, "role": "RC", "gen_speed": "Gen3"})
    assert exc.value.reason == "INVALID_LANE_WIDTH"


def test_validate_ltssm_topology_rejects_bad_role():
    with pytest.raises(LTSSMTopologyError) as exc:
        validate_ltssm_topology({"lane_width": 16, "role": "SWITCH", "gen_speed": "Gen3"})
    assert exc.value.reason == "INVALID_ROLE"


def test_validate_ltssm_topology_accepts_good_topology():
    validate_ltssm_topology({"lane_width": 16, "role": "EP", "gen_speed": "Gen4"})  # must not raise


# ---- generation + CLI integration ------------------------------------------

def _sample_topology():
    return {"name": "pcie_x8", "lane_width": 8, "gen_speed": "Gen3", "role": "EP"}


def test_generate_emits_expected_files_with_real_values():
    tmp = Path(tempfile.mkdtemp())
    try:
        files = PCIeLTSSMGenerator(tmp).generate(_sample_topology())
        assert "pcie_x8_ltssm_pkg.sv" in files
        assert "pcie_x8_ltssm_state_reg.sv" in files
        assert "ltssm_topology.json" in files
        assert "environment_manifest.json" in files

        pkg_text = (tmp / "pcie_x8_ltssm_pkg.sv").read_text(encoding="utf-8")
        # every top-level state name must appear in the emitted enum
        for state in LTSSM_STATES:
            assert state in pkg_text
        # the legality function must encode a real (from Python) transition edge
        assert "DETECT: return (to_state inside {" in pkg_text
        assert "POLLING" in pkg_text

        reg_text = (tmp / "pcie_x8_ltssm_state_reg.sv").read_text(encoding="utf-8")
        assert "LANE_WIDTH = 8" in reg_text
        assert "gen_speed=\"Gen3\"" in reg_text
        assert "role=EP" in reg_text

        topo = json.loads((tmp / "ltssm_topology.json").read_text(encoding="utf-8"))
        assert topo["lane_width"] == 8
        assert topo["role"] == "EP"
        assert set(topo["states"]) == LTSSM_STATES
        assert topo["transitions"]["DETECT"] == sorted(LTSSM_TRANSITIONS["DETECT"])

        manifest = json.loads((tmp / "environment_manifest.json").read_text(encoding="utf-8"))
        assert manifest["qualification_status"] == "ENV_GENERATED"
        assert manifest["vip"]["binding_status"] == "PLACEHOLDER_UNTIL_CURRENT_VIP_EVIDENCE"
        assert set(manifest["ltssm_states"]) == LTSSM_STATES
    finally:
        shutil.rmtree(tmp)


def test_generate_rejects_invalid_topology_before_writing_files():
    tmp = Path(tempfile.mkdtemp())
    try:
        bad = {"name": "bad", "lane_width": 3, "gen_speed": "Gen3", "role": "EP"}
        with pytest.raises(LTSSMTopologyError):
            PCIeLTSSMGenerator(tmp).generate(bad)
        assert list(tmp.iterdir()) == []  # refuses to silently emit a partially-wrong result
    finally:
        shutil.rmtree(tmp)


def test_cli_shim_generates_expected_files():
    tmp = Path(tempfile.mkdtemp())
    try:
        topo_path = tmp / "topology.json"
        topo_path.write_text(json.dumps(_sample_topology()), encoding="utf-8")
        out_dir = tmp / "out"
        script = ROOT / "tools" / "generate_pcie_ltssm_environment.py"
        r = subprocess.run(
            [sys.executable, str(script), "--topology", str(topo_path), "--out", str(out_dir)],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, r.stderr
        assert (out_dir / "ltssm_topology.json").exists()
        assert (out_dir / "environment_manifest.json").exists()
        assert (out_dir / "pcie_x8_ltssm_pkg.sv").exists()
    finally:
        shutil.rmtree(tmp)
