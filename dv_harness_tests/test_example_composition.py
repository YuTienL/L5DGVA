"""Tests for dv_harness/example_composition.py.

Core positive path (a real compatible two-example composition), then every
one of the 7 conditions is driven to a real, named-pair conflict by mutating
one fact at a time off that same clean baseline -- plus malformed-input and
link-disambiguation negative controls, and a real CLI subprocess check.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness.example_composition import (
    CompositionInputError,
    COND_AGENT_CONFIG,
    COND_CLOCK_ASSUMPTIONS,
    COND_PROTOCOL_MODE,
    COND_RESET_ASSUMPTIONS,
    COND_ROLE,
    COND_SEQUENCER_OWNERSHIP,
    COND_VIP_VERSION,
    STATUS_BLOCKED,
    STATUS_COMPOSED,
    STATUS_NOT_AVAILABLE,
    evaluate_vip_example_composition,
    execute_verb,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _clean_pair():
    """Two genuinely compatible qualified VIP examples: a USB3 host example
    and a USB3 device example on one declared link, agreeing on every
    composition-relevant fact."""
    host = {
        "example_id": "usb3_host_example",
        "vip_type": "svt_usb3_agent",
        "vip_version": "2023.03",
        "role": "HOST",
        "protocol_mode": "USB3.1_GEN1x1",
        "agent_config": {"data_width": 32, "num_lanes": 1},
        "sequencer_path": "tb_top.host_agent.sqr",
        "link_id": "link0",
        "active": True,
        "reset_assumptions": {"signal": "rst_n", "active_level": "LOW", "synchronous": True},
        "clock_assumptions": {"signal": "clk_ref", "frequency_mhz": 125},
    }
    device = {
        "example_id": "usb3_device_example",
        "vip_type": "svt_usb3_agent",
        "vip_version": "2023.03",
        "role": "DEVICE",
        "protocol_mode": "USB3.1_GEN1x1",
        "agent_config": {"data_width": 32, "num_lanes": 1},
        "sequencer_path": "tb_top.device_agent.sqr",
        "link_id": "link0",
        "active": False,
        "reset_assumptions": {"signal": "rst_n", "active_level": "LOW", "synchronous": True},
        "clock_assumptions": {"signal": "clk_ref", "frequency_mhz": 125},
    }
    return [host, device]


# --------------------------------------------------------------------------
# core positive path
# --------------------------------------------------------------------------

def test_clean_compatible_pair_composes():
    report = evaluate_vip_example_composition(_clean_pair())
    assert report["status"] == STATUS_COMPOSED
    assert report["conflict_count"] == 0
    assert report["malformed_examples"] == []
    assert report["example_count_valid"] == 2
    for cond in report["conditions"].values():
        assert cond["conflicts"] == []
    scenario = report["composed_scenario"]
    assert scenario is not None
    assert set(scenario["example_ids"]) == {"usb3_host_example", "usb3_device_example"}
    assert scenario["vip_types"] == ["svt_usb3_agent"]
    assert scenario["protocol_modes"] == ["USB3.1_GEN1x1"]


def test_report_never_mutates_the_supplied_examples():
    examples = _clean_pair()
    before = copy.deepcopy(examples)
    evaluate_vip_example_composition(examples)
    assert examples == before


# --------------------------------------------------------------------------
# negative control 1: VIP version conflict
# --------------------------------------------------------------------------

def test_vip_version_conflict_is_blocked_and_names_the_pair():
    examples = _clean_pair()
    examples[1]["vip_version"] = "2019.09"
    report = evaluate_vip_example_composition(examples)
    assert report["status"] == STATUS_BLOCKED
    cond = report["conditions"][COND_VIP_VERSION]
    assert cond["status"] == "CONFLICT"
    assert len(cond["conflicts"]) == 1
    pair = cond["conflicts"][0]["pair"]
    assert set(pair) == {"usb3_host_example", "usb3_device_example"}
    assert cond["conflicts"][0]["detail"]["vip_version_a"] == "2023.03"
    assert cond["conflicts"][0]["detail"]["vip_version_b"] == "2019.09"
    # every OTHER condition stays clean -- this is a targeted single-defect mutation
    for cid, c in report["conditions"].items():
        if cid != COND_VIP_VERSION:
            assert c["conflicts"] == [], f"unexpected conflict on {cid}"


def test_different_vip_type_examples_never_compared_for_version():
    examples = _clean_pair()
    examples[1]["vip_type"] = "svt_axi_agent"
    examples[1]["vip_version"] = "9999.01"
    report = evaluate_vip_example_composition(examples)
    cond = report["conditions"][COND_VIP_VERSION]
    assert cond["status"] == "NOT_APPLICABLE"
    assert cond["conflicts"] == []


# --------------------------------------------------------------------------
# negative control 2: role conflict (two active drivers, same link)
# --------------------------------------------------------------------------

def test_duplicate_active_role_on_same_link_is_blocked():
    examples = _clean_pair()
    examples[1]["role"] = "HOST"
    examples[1]["active"] = True
    report = evaluate_vip_example_composition(examples)
    assert report["status"] == STATUS_BLOCKED
    cond = report["conditions"][COND_ROLE]
    assert cond["status"] == "CONFLICT"
    pair = cond["conflicts"][0]["pair"]
    assert set(pair) == {"usb3_host_example", "usb3_device_example"}


def test_two_active_hosts_on_different_links_do_not_conflict_on_role():
    """The link-disambiguation false-positive control: two independent ports
    (declared via different link_id) may both legitimately be HOST."""
    host_a = {
        "example_id": "port0_host", "vip_type": "svt_usb3_agent", "vip_version": "1.0",
        "role": "HOST", "link_id": "port0",
    }
    host_b = {
        "example_id": "port1_host", "vip_type": "svt_usb3_agent", "vip_version": "1.0",
        "role": "HOST", "link_id": "port1",
    }
    report = evaluate_vip_example_composition([host_a, host_b])
    assert report["status"] == STATUS_COMPOSED
    assert report["conditions"][COND_ROLE]["conflicts"] == []


def test_two_examples_with_no_link_info_share_the_unspecified_bucket():
    """Disclosed design choice: with no link_id/sequencer_path on either
    side, two active-role examples ARE flagged -- absence of disambiguating
    evidence is never read as proof of independence."""
    host_a = {"example_id": "a", "vip_type": "svt_usb3_agent", "vip_version": "1.0", "role": "HOST"}
    host_b = {"example_id": "b", "vip_type": "svt_usb3_agent", "vip_version": "1.0", "role": "HOST"}
    report = evaluate_vip_example_composition([host_a, host_b])
    assert report["status"] == STATUS_BLOCKED
    assert report["conditions"][COND_ROLE]["conflicts"]


# --------------------------------------------------------------------------
# negative control 3: protocol mode conflict
# --------------------------------------------------------------------------

def test_protocol_mode_mismatch_on_same_link_is_blocked():
    examples = _clean_pair()
    examples[1]["protocol_mode"] = "USB3.1_GEN2x1"
    report = evaluate_vip_example_composition(examples)
    assert report["status"] == STATUS_BLOCKED
    cond = report["conditions"][COND_PROTOCOL_MODE]
    assert cond["status"] == "CONFLICT"
    detail = cond["conflicts"][0]["detail"]
    assert detail["protocol_mode_a"] == "USB3.1_GEN1x1"
    assert detail["protocol_mode_b"] == "USB3.1_GEN2x1"


# --------------------------------------------------------------------------
# negative control 4: agent config conflict
# --------------------------------------------------------------------------

def test_agent_config_disagreement_on_shared_field_is_blocked():
    examples = _clean_pair()
    examples[1]["agent_config"]["data_width"] = 16
    report = evaluate_vip_example_composition(examples)
    assert report["status"] == STATUS_BLOCKED
    cond = report["conditions"][COND_AGENT_CONFIG]
    assert cond["status"] == "CONFLICT"
    fields = cond["conflicts"][0]["detail"]["fields"]
    assert any(f["field"] == "data_width" and f["value_a"] == 32 and f["value_b"] == 16
               for f in fields)


def test_agent_config_field_present_on_only_one_side_is_not_a_conflict():
    examples = _clean_pair()
    examples[0]["agent_config"]["extra_only_on_host"] = "whatever"
    report = evaluate_vip_example_composition(examples)
    assert report["status"] == STATUS_COMPOSED
    assert report["conditions"][COND_AGENT_CONFIG]["conflicts"] == []


# --------------------------------------------------------------------------
# negative control 5: sequencer ownership conflict
# --------------------------------------------------------------------------

def test_two_active_drivers_on_same_sequencer_path_is_blocked():
    examples = _clean_pair()
    examples[1]["sequencer_path"] = examples[0]["sequencer_path"]
    examples[1]["active"] = True
    report = evaluate_vip_example_composition(examples)
    assert report["status"] == STATUS_BLOCKED
    cond = report["conditions"][COND_SEQUENCER_OWNERSHIP]
    assert cond["status"] == "CONFLICT"
    pair = cond["conflicts"][0]["pair"]
    assert set(pair) == {"usb3_host_example", "usb3_device_example"}


def test_active_plus_passive_on_same_path_is_not_an_ownership_conflict():
    examples = _clean_pair()
    examples[1]["sequencer_path"] = examples[0]["sequencer_path"]
    # examples[1] ("device") stays active=False -- a monitor sharing a path
    # with the real active driver is legitimate.
    report = evaluate_vip_example_composition(examples)
    assert report["conditions"][COND_SEQUENCER_OWNERSHIP]["conflicts"] == []


def test_unresolved_active_status_is_reported_but_never_forced_into_a_conflict():
    examples = _clean_pair()
    examples[1]["sequencer_path"] = examples[0]["sequencer_path"]
    del examples[1]["active"]
    examples[1]["role"] = "SOME_UNRECOGNISED_ROLE"
    report = evaluate_vip_example_composition(examples)
    cond = report["conditions"][COND_SEQUENCER_OWNERSHIP]
    assert cond["conflicts"] == []
    assert any(u["identity"] == "usb3_device_example" for u in cond["unresolved_active_status"])


# --------------------------------------------------------------------------
# negative control 6: reset assumption conflict
# --------------------------------------------------------------------------

def test_reset_assumption_disagreement_on_same_signal_is_blocked():
    examples = _clean_pair()
    examples[1]["reset_assumptions"]["active_level"] = "HIGH"
    report = evaluate_vip_example_composition(examples)
    assert report["status"] == STATUS_BLOCKED
    cond = report["conditions"][COND_RESET_ASSUMPTIONS]
    assert cond["status"] == "CONFLICT"
    fields = cond["conflicts"][0]["detail"]["fields"]
    assert any(f["field"] == "active_level" for f in fields)


def test_reset_signals_with_different_names_are_never_compared():
    examples = _clean_pair()
    examples[1]["reset_assumptions"]["signal"] = "rst_device_n"
    examples[1]["reset_assumptions"]["active_level"] = "HIGH"
    report = evaluate_vip_example_composition(examples)
    assert report["status"] == STATUS_COMPOSED
    assert report["conditions"][COND_RESET_ASSUMPTIONS]["conflicts"] == []


# --------------------------------------------------------------------------
# negative control 7: clock assumption conflict
# --------------------------------------------------------------------------

def test_clock_frequency_disagreement_on_same_signal_is_blocked():
    examples = _clean_pair()
    examples[1]["clock_assumptions"]["frequency_mhz"] = 100
    report = evaluate_vip_example_composition(examples)
    assert report["status"] == STATUS_BLOCKED
    cond = report["conditions"][COND_CLOCK_ASSUMPTIONS]
    assert cond["status"] == "CONFLICT"
    fields = cond["conflicts"][0]["detail"]["fields"]
    assert any(f["field"] == "frequency_mhz" and f["value_a"] == 125 and f["value_b"] == 100
               for f in fields)


def test_clock_numeric_tolerance_never_manufactures_a_false_conflict():
    examples = _clean_pair()
    examples[1]["clock_assumptions"]["frequency_mhz"] = 125.0000001
    report = evaluate_vip_example_composition(examples)
    assert report["status"] == STATUS_COMPOSED
    assert report["conditions"][COND_CLOCK_ASSUMPTIONS]["conflicts"] == []


# --------------------------------------------------------------------------
# malformed input / insufficient examples
# --------------------------------------------------------------------------

def test_non_dict_entry_is_malformed_and_excluded():
    examples = _clean_pair() + ["not-a-dict"]
    report = evaluate_vip_example_composition(examples)
    assert report["status"] == STATUS_COMPOSED
    assert report["example_count_valid"] == 2
    assert any(m["reason"] == "EXAMPLE_NOT_A_DICT" for m in report["malformed_examples"])


def test_entry_with_no_identity_is_malformed_and_excluded():
    examples = _clean_pair()
    examples.append({"vip_type": "svt_axi_agent", "vip_version": "1.0"})
    report = evaluate_vip_example_composition(examples)
    assert report["example_count_valid"] == 2
    assert any(m["reason"] == "NO_RESOLVABLE_IDENTITY" for m in report["malformed_examples"])


def test_duplicate_identity_excludes_both_and_never_silently_picks_one():
    examples = _clean_pair()
    dup = dict(examples[0])
    dup["vip_version"] = "totally different"
    examples.append(dup)
    report = evaluate_vip_example_composition(examples)
    dup_entries = [m for m in report["malformed_examples"] if m["reason"] == "DUPLICATE_EXAMPLE_ID"]
    assert len(dup_entries) == 2
    assert report["example_count_valid"] == 1  # only the device example remains unique


def test_fewer_than_two_valid_examples_is_not_available():
    report = evaluate_vip_example_composition([_clean_pair()[0]])
    assert report["status"] == STATUS_NOT_AVAILABLE
    assert report["example_count_valid"] == 1


def test_empty_examples_is_not_available():
    report = evaluate_vip_example_composition([])
    assert report["status"] == STATUS_NOT_AVAILABLE


def test_non_sequence_examples_raises_composition_input_error():
    with pytest.raises(CompositionInputError):
        evaluate_vip_example_composition({"not": "a list"})


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _run_cli(payload, tmp_path, extra_args=()):
    examples_file = tmp_path / "examples.json"
    examples_file.write_text(json.dumps(payload), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.example_composition", "compose",
         "--examples", str(examples_file), *extra_args],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )


def test_cli_composed_exit_0(tmp_path):
    result = _run_cli(_clean_pair(), tmp_path, extra_args=["--json"])
    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["status"] == STATUS_COMPOSED


def test_cli_blocked_exit_1(tmp_path):
    examples = _clean_pair()
    examples[1]["vip_version"] = "0.0.1"
    result = _run_cli(examples, tmp_path)
    assert result.returncode == 1
    assert "BLOCKED" in result.stdout


def test_cli_not_available_exit_2(tmp_path):
    result = _run_cli([], tmp_path)
    assert result.returncode == 2
    assert "NOT_AVAILABLE" in result.stdout
