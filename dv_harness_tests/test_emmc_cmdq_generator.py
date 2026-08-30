"""Tests for dv_harness/uvm_generator/emmc_cmdq_generator.py -- the real
eMMC/SD CMDQ tag-based out-of-order request/completion scoreboard generator
(parity audit gap: eMMC/MMC and SD/SDIO need a tag-based scoreboard
structurally different from AMBA's static M x N pairing)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from dv_harness.uvm_generator.emmc_cmdq_generator import (
    CMDQError, EMMCCmdqGenerator,
    issue_tag, complete_tag, check_final_state, hs200_tuning_step,
)

ROOT = Path(__file__).resolve().parents[1]


# ---- pure-function tests (no I/O) ------------------------------------------

def test_issue_tag_adds_tag_to_outstanding():
    outstanding = issue_tag(set(), 5)
    assert outstanding == {5}
    outstanding = issue_tag(outstanding, 7)
    assert outstanding == {5, 7}


def test_issue_tag_out_of_range_low():
    with pytest.raises(CMDQError) as exc:
        issue_tag(set(), -1)
    assert exc.value.reason == "TAG_OUT_OF_RANGE"


def test_issue_tag_out_of_range_high_default_32():
    with pytest.raises(CMDQError) as exc:
        issue_tag(set(), 32)
    assert exc.value.reason == "TAG_OUT_OF_RANGE"
    assert exc.value.detail["num_tags"] == 32


def test_issue_tag_respects_custom_num_tags():
    # tag=4 is valid under num_tags=8 but not under num_tags=4
    outstanding = issue_tag(set(), 4, num_tags=8)
    assert outstanding == {4}
    with pytest.raises(CMDQError) as exc:
        issue_tag(set(), 4, num_tags=4)
    assert exc.value.reason == "TAG_OUT_OF_RANGE"


def test_issue_tag_already_outstanding_is_protocol_violation():
    outstanding = issue_tag(set(), 3)
    with pytest.raises(CMDQError) as exc:
        issue_tag(outstanding, 3)
    assert exc.value.reason == "TAG_ALREADY_OUTSTANDING"
    assert exc.value.detail["tag"] == 3


def test_complete_tag_removes_from_outstanding():
    outstanding = {1, 2, 3}
    result = complete_tag(outstanding, 2)
    assert result == {1, 3}
    # original set not mutated
    assert outstanding == {1, 2, 3}


def test_complete_tag_for_unissued_tag_raises():
    with pytest.raises(CMDQError) as exc:
        complete_tag(set(), 9)
    assert exc.value.reason == "COMPLETION_FOR_UNISSUED_TAG"
    assert exc.value.detail["tag"] == 9


def test_complete_tag_for_already_completed_tag_raises():
    outstanding = issue_tag(set(), 6)
    outstanding = complete_tag(outstanding, 6)
    # completing again (duplicate/spurious completion) is the same error
    with pytest.raises(CMDQError) as exc:
        complete_tag(outstanding, 6)
    assert exc.value.reason == "COMPLETION_FOR_UNISSUED_TAG"


def test_out_of_order_completion_is_allowed():
    # Issue tags 0, 1, 2 in order; complete them 2, 0, 1 -- any order is
    # legal for CMDQ, unlike AMBA's static pairing.
    outstanding = set()
    for tag in (0, 1, 2):
        outstanding = issue_tag(outstanding, tag)
    outstanding = complete_tag(outstanding, 2)
    outstanding = complete_tag(outstanding, 0)
    outstanding = complete_tag(outstanding, 1)
    assert outstanding == set()


def test_check_final_state_clean_when_empty():
    assert check_final_state(set()) == []


def test_check_final_state_reports_stuck_tags():
    stuck = check_final_state({5, 1, 9})
    assert stuck == [1, 5, 9]  # sorted


# ---- hs200_tuning_step convergence behavior --------------------------------

def test_hs200_tuning_step_converges_to_stable_center():
    state = {"low": 0, "high": 15, "current_tap": 7, "converged": False, "final_tap": None}
    seen_final = False
    for _ in range(10):
        # deterministic pass/fail rule: pass if current_tap <= 7 else fail
        # (models a stable pass window of [0,7])
        pass_result = state["current_tap"] <= 7
        state = hs200_tuning_step(state, pass_result)
        if state["converged"]:
            seen_final = True
            break
    assert seen_final, "tuning loop did not converge within 10 iterations"
    assert state["final_tap"] is not None
    assert 0 <= state["final_tap"] <= 15


def test_hs200_tuning_step_is_idempotent_once_converged():
    state = {"low": 4, "high": 4, "current_tap": 4, "converged": True, "final_tap": 4}
    result = hs200_tuning_step(state, True)
    assert result == state


def test_hs200_tuning_step_narrows_window_on_fail():
    state = {"low": 0, "high": 15, "current_tap": 8, "converged": False, "final_tap": None}
    result = hs200_tuning_step(state, False)
    assert result["converged"] is False
    # failing tap excludes itself and everything below from the window
    assert result["high"] == 7
    assert result["low"] == 0


def test_hs200_tuning_step_narrows_window_on_pass():
    state = {"low": 0, "high": 15, "current_tap": 8, "converged": False, "final_tap": None}
    result = hs200_tuning_step(state, True)
    assert result["converged"] is False
    assert result["low"] == 8
    assert result["high"] == 15


# ---- generation + integration test -----------------------------------------

def _sample_topology(include_tuning=False):
    return {
        "module_name": "emmc_cq_scoreboard",
        "num_tags": 32,
        "include_hs200_tuning": include_tuning,
    }


def test_generate_emits_expected_files_with_real_values():
    tmp = Path(tempfile.mkdtemp())
    try:
        files = EMMCCmdqGenerator(tmp).generate(_sample_topology())
        assert "emmc_cq_scoreboard.sv" in files
        assert "environment_manifest.json" in files
        assert "emmc_cmdq_topology.json" in files

        sv_text = (tmp / "emmc_cq_scoreboard.sv").read_text(encoding="utf-8")
        assert "NUM_TAGS = 32" in sv_text
        assert "TAG_ALREADY_OUTSTANDING" in sv_text
        assert "COMPLETION_FOR_UNISSUED_TAG" in sv_text
        assert "STUCK_TAGS_AT_END_OF_TEST" in sv_text

        manifest = json.loads((tmp / "environment_manifest.json").read_text(encoding="utf-8"))
        assert manifest["qualification_status"] == "ENV_GENERATED"
        assert manifest["vip"]["binding_status"] == "PLACEHOLDER_UNTIL_CURRENT_VIP_EVIDENCE"
        assert manifest["num_tags"] == 32

        topology = json.loads((tmp / "emmc_cmdq_topology.json").read_text(encoding="utf-8"))
        assert topology["scoreboard_shape"] == "TAG_BASED_OUT_OF_ORDER"
        assert topology["num_tags"] == 32
    finally:
        shutil.rmtree(tmp)


def test_generate_with_hs200_tuning_requested_emits_tuning_task():
    tmp = Path(tempfile.mkdtemp())
    try:
        files = EMMCCmdqGenerator(tmp).generate(_sample_topology(include_tuning=True))
        sv_text = (tmp / "emmc_cq_scoreboard.sv").read_text(encoding="utf-8")
        assert "tuning_step" in sv_text
        assert "NEEDS SPEC VERIFICATION" in sv_text
        manifest = json.loads((tmp / "environment_manifest.json").read_text(encoding="utf-8"))
        assert manifest["include_hs200_tuning"] is True
    finally:
        shutil.rmtree(tmp)


def test_generate_without_hs200_tuning_omits_tuning_task():
    tmp = Path(tempfile.mkdtemp())
    try:
        EMMCCmdqGenerator(tmp).generate(_sample_topology(include_tuning=False))
        sv_text = (tmp / "emmc_cq_scoreboard.sv").read_text(encoding="utf-8")
        assert "task automatic tuning_step" not in sv_text
    finally:
        shutil.rmtree(tmp)


def test_generate_rejects_invalid_num_tags():
    tmp = Path(tempfile.mkdtemp())
    try:
        with pytest.raises(CMDQError) as exc:
            EMMCCmdqGenerator(tmp).generate({"module_name": "bad", "num_tags": 0})
        assert exc.value.reason == "INVALID_NUM_TAGS"
    finally:
        shutil.rmtree(tmp)


def test_cli_shim_generates_files():
    tmp = Path(tempfile.mkdtemp())
    try:
        topo_path = tmp / "topology.json"
        topo_path.write_text(json.dumps(_sample_topology()), encoding="utf-8")
        out_dir = tmp / "out"
        script = ROOT / "tools" / "generate_emmc_cmdq_environment.py"
        r = subprocess.run(
            [sys.executable, str(script), "--topology", str(topo_path), "--out", str(out_dir)],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, r.stderr
        assert (out_dir / "emmc_cmdq_topology.json").exists()
        assert (out_dir / "emmc_cq_scoreboard.sv").exists()
    finally:
        shutil.rmtree(tmp)
