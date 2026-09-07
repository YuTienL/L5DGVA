"""Tests for `dv_harness.shared_vip_sequencer_registry`: the intra-subsystem
branch_b*-vs-branch_b* shared-VIP-sequencer race detector -- the sibling of
`shared_bus_resource_registry.py`'s own branch_fw-vs-branch_a* detector.

Every test drives the real `analyze_shared_vip_sequencer_registry()` (never a
mock of its internals), and the CLI test drives the real
`python -m dv_harness.shared_vip_sequencer_registry` subprocess.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import shared_vip_sequencer_registry as svsr
from dv_harness import shared_bus_resource_registry as sbrr
from dv_harness import connectivity as conn


def _prog(task_group, lock_name=None, evidence="pattern.txt:10"):
    return {"task_group": task_group, "lock_name": lock_name, "evidence": evidence}


# ---------------------------------------------------------------------------
# Reuse proof: this module genuinely reuses shared_bus_resource_registry's
# classify_task_group/normalize_programmers rather than re-deriving them.
# ---------------------------------------------------------------------------

def test_reuses_classify_task_group_and_normalize_programmers_from_sibling_module():
    assert svsr.classify_task_group is sbrr.classify_task_group
    assert svsr.normalize_programmers is sbrr.normalize_programmers
    assert svsr.TG_BRANCH_B is sbrr.TG_BRANCH_B
    assert svsr.TG_INVALID is sbrr.TG_INVALID


# ---------------------------------------------------------------------------
# Core positive path: a real branch_b0-vs-branch_b1 race, no common lock
# ---------------------------------------------------------------------------

def test_branch_b_race_detected_with_no_common_lock():
    declarations = [{
        "resource_id": "SHARED_USB_HOST_AGENT",
        "resource_type": svsr.RT_VIP_AGENT,
        "programmers": [
            _prog("branch_b0", lock_name="B0_SCEN_LOCK",
                  evidence="vip_scenario_port0.txt:44"),
            _prog("branch_b1", lock_name="B1_SCEN_LOCK",
                  evidence="vip_scenario_port1.txt:52"),
        ],
    }]
    report = svsr.analyze_shared_vip_sequencer_registry(declarations)
    assert report["status"] == svsr.STATUS_CONTENTION
    assert report["resource_count"] == 1
    entry = report["entries"][0]
    assert entry["conflict_status"] == svsr.CONFLICT_B_B_RACE
    assert entry["lock_policy"] == svsr.LOCK_POLICY_DISTINCT
    owners = entry["conflicting_owners"]
    assert len(owners) == 1
    assert owners[0]["a_branch"] == "branch_b0"
    assert owners[0]["b_branch"] == "branch_b1"
    assert owners[0]["a_lock"] == "B0_SCEN_LOCK"
    assert owners[0]["b_lock"] == "B1_SCEN_LOCK"
    assert owners[0]["a_evidence"] == "vip_scenario_port0.txt:44"
    assert owners[0]["b_evidence"] == "vip_scenario_port1.txt:52"


def test_branch_b_race_detected_when_neither_side_declares_any_lock():
    declarations = [{
        "resource_id": "SHARED_ERROR_INJECTION_SEQUENCER",
        "resource_type": svsr.RT_VIP_SEQUENCER,
        "programmers": [
            _prog("branch_b0", lock_name=None, evidence="vip_scenario_port0.txt:12"),
            _prog("branch_b2", lock_name=None, evidence="vip_scenario_port2.txt:19"),
        ],
    }]
    report = svsr.analyze_shared_vip_sequencer_registry(declarations)
    assert report["status"] == svsr.STATUS_CONTENTION
    entry = report["entries"][0]
    assert entry["conflict_status"] == svsr.CONFLICT_B_B_RACE
    assert entry["lock_policy"] == svsr.LOCK_POLICY_NONE_DECLARED
    assert entry["conflicting_owners"][0]["a_lock"] == "NONE_DECLARED"
    assert entry["conflicting_owners"][0]["b_lock"] == "NONE_DECLARED"


# ---------------------------------------------------------------------------
# Positive control for CLEAR: a real shared lock serializes the pair
# ---------------------------------------------------------------------------

def test_shared_named_lock_is_reported_clear_not_contention():
    declarations = [{
        "resource_id": "SHARED_VIRTUAL_SEQUENCER",
        "resource_type": svsr.RT_VIP_VIRTUAL_SEQUENCER,
        "programmers": [
            _prog("branch_b0", lock_name="VSEQR_ARB_LOCK",
                  evidence="vip_scenario_port0.txt:8"),
            _prog("branch_b1", lock_name="VSEQR_ARB_LOCK",
                  evidence="vip_scenario_port1.txt:9"),
            _prog("branch_b2", lock_name="VSEQR_ARB_LOCK",
                  evidence="vip_scenario_port2.txt:10"),
        ],
    }]
    report = svsr.analyze_shared_vip_sequencer_registry(declarations)
    assert report["status"] == svsr.STATUS_CLEAR
    entry = report["entries"][0]
    assert entry["conflict_status"] == svsr.CONFLICT_NONE
    assert entry["lock_policy"] == svsr.LOCK_POLICY_SINGLE_SHARED
    assert entry["conflicting_owners"] == []


# ---------------------------------------------------------------------------
# Negative controls
# ---------------------------------------------------------------------------

def test_no_declarations_is_not_applicable():
    report = svsr.analyze_shared_vip_sequencer_registry([])
    assert report["status"] == svsr.STATUS_NOT_APPLICABLE
    assert report["resource_count"] == 0

    report_none = svsr.analyze_shared_vip_sequencer_registry(None)
    assert report_none["status"] == svsr.STATUS_NOT_APPLICABLE


def test_single_programmer_is_not_applicable_not_clear():
    declarations = [{
        "resource_id": "SOLO_VIP_AGENT",
        "programmers": [_prog("branch_b0", lock_name="X", evidence="f.txt:1")],
    }]
    report = svsr.analyze_shared_vip_sequencer_registry(declarations)
    assert report["status"] == svsr.STATUS_NOT_APPLICABLE
    assert report["entries"][0]["conflict_status"] == svsr.CONFLICT_NOT_APPLICABLE


def test_same_branch_b_index_declared_twice_is_out_of_scope_and_reports_clear_no_conflict():
    """Two declarations both for branch_b0 (e.g. a duplicate record, or the
    same body legitimately reusing its own sequencer) is NOT a race between
    two DIFFERENT branch_b bodies -- this module's own detection scope, per
    its module docstring."""
    declarations = [{
        "resource_id": "SHARED_VIP_AGENT",
        "programmers": [
            _prog("branch_b0", lock_name="A", evidence="f.txt:1"),
            _prog("branch_b0", lock_name="B", evidence="f.txt:2"),
        ],
    }]
    report = svsr.analyze_shared_vip_sequencer_registry(declarations)
    assert report["status"] == svsr.STATUS_CLEAR
    entry = report["entries"][0]
    assert entry["conflict_status"] == svsr.CONFLICT_NONE
    assert "no such pair here to judge" in entry["reason"]


def test_branch_a_only_pair_is_out_of_scope_and_reports_clear_no_conflict():
    """A resource shared only among branch_a*/branch_fw/block programmers,
    with no branch_b* body at all, is explicitly OUT of this module's scope
    (that pair belongs to shared_bus_resource_registry.py, or branch-
    mapper's cross-branch_a* rule) -- never a fabricated verdict here."""
    declarations = [{
        "resource_id": "APB_MASTER_SHARED",
        "programmers": [
            _prog("branch_a0", lock_name="X", evidence="f.txt:1"),
            _prog("branch_a1", lock_name="Y", evidence="f.txt:2"),
        ],
    }]
    report = svsr.analyze_shared_vip_sequencer_registry(declarations)
    assert report["status"] == svsr.STATUS_CLEAR
    entry = report["entries"][0]
    assert entry["conflict_status"] == svsr.CONFLICT_NONE
    assert "branch_b" in entry["reason"]


def test_invalid_task_group_name_yields_unknown_not_a_silent_clear():
    """This is the negative control proving the module refuses to fabricate
    an answer when evidence is absent: a non-canonical task_group name is
    never read as proof a second branch_b body is absent."""
    declarations = [{
        "resource_id": "SHARED_VIP_AGENT",
        "programmers": [
            _prog("branch_b0", lock_name="X", evidence="f.txt:1"),
            _prog("BranchB1", lock_name="Y", evidence="f.txt:2"),  # legacy naming
        ],
    }]
    report = svsr.analyze_shared_vip_sequencer_registry(declarations)
    assert report["status"] == svsr.STATUS_UNKNOWN
    entry = report["entries"][0]
    assert entry["conflict_status"] == svsr.CONFLICT_UNKNOWN
    assert "not evidence a second branch_b body is" in entry["reason"]


def test_missing_evidence_yields_unknown_not_a_silent_clear():
    declarations = [{
        "resource_id": "SHARED_VIP_AGENT",
        "programmers": [
            _prog("branch_b0", lock_name="X", evidence=""),
            _prog("branch_b1", lock_name="Y", evidence="f.txt:2"),
        ],
    }]
    report = svsr.analyze_shared_vip_sequencer_registry(declarations)
    assert report["status"] == svsr.STATUS_UNKNOWN
    entry = report["entries"][0]
    assert entry["conflict_status"] == svsr.CONFLICT_UNKNOWN
    assert "trustworthy" in entry["reason"]


def test_one_valid_pair_still_races_even_if_a_third_declaration_is_invalid():
    declarations = [{
        "resource_id": "SHARED_VIP_AGENT",
        "programmers": [
            _prog("branch_b0", lock_name="X", evidence="f.txt:1"),
            _prog("branch_b1", lock_name="Y", evidence="f.txt:2"),
            _prog("branch_b2", lock_name="Z", evidence=""),  # invalid: no evidence
        ],
    }]
    report = svsr.analyze_shared_vip_sequencer_registry(declarations)
    assert report["status"] == svsr.STATUS_CONTENTION
    entry = report["entries"][0]
    assert entry["conflict_status"] == svsr.CONFLICT_B_B_RACE
    owners = entry["conflicting_owners"]
    assert len(owners) == 1
    assert {owners[0]["a_branch"], owners[0]["b_branch"]} == {"branch_b0", "branch_b1"}


def test_duplicate_resource_id_raises_rather_than_silently_merging():
    declarations = [
        {"resource_id": "SAME_ID", "programmers": [_prog("branch_b0")]},
        {"resource_id": "SAME_ID", "programmers": [_prog("branch_b1")]},
    ]
    with pytest.raises(svsr.SharedVipSequencerRegistryError) as exc:
        svsr.analyze_shared_vip_sequencer_registry(declarations)
    assert exc.value.reason == "DUPLICATE_RESOURCE_ID"
    assert exc.value.detail["resource_ids"] == ["SAME_ID"]


def test_overall_contention_outranks_unknown_and_not_applicable():
    declarations = [
        {"resource_id": "R1", "programmers": [
            _prog("branch_b0", lock_name="A", evidence="f:1"),
            _prog("branch_b1", lock_name="B", evidence="f:2"),
        ]},
        {"resource_id": "R2", "programmers": [
            _prog("branch_b0", lock_name="X", evidence="f:3"),
            _prog("BadName", lock_name="Y", evidence="f:4"),
        ]},
        {"resource_id": "R3", "programmers": [_prog("branch_b0", evidence="f:5")]},
    ]
    report = svsr.analyze_shared_vip_sequencer_registry(declarations)
    assert report["status"] == svsr.STATUS_CONTENTION
    by_status = {e["resource_id"]: e["conflict_status"] for e in report["entries"]}
    assert by_status["R1"] == svsr.CONFLICT_B_B_RACE
    assert by_status["R2"] == svsr.CONFLICT_UNKNOWN
    assert by_status["R3"] == svsr.CONFLICT_NOT_APPLICABLE


# ---------------------------------------------------------------------------
# lock_policy unit checks
# ---------------------------------------------------------------------------

def test_lock_policy_partial_declaration():
    programmers = svsr.normalize_programmers([
        _prog("branch_b0", lock_name="X", evidence="f:1"),
        _prog("branch_b1", lock_name=None, evidence="f:2"),
    ])
    assert svsr.derive_lock_policy(programmers) == svsr.LOCK_POLICY_PARTIAL


def test_lock_policy_single_programmer():
    programmers = svsr.normalize_programmers([_prog("branch_b0", evidence="f:1")])
    assert svsr.derive_lock_policy(programmers) == svsr.LOCK_POLICY_SINGLE_PROGRAMMER


# ---------------------------------------------------------------------------
# Connectivity-rows enrichment (present and absent)
# ---------------------------------------------------------------------------

def test_connectivity_rows_resolve_hierarchy_when_bind_target_matches():
    declarations = [{
        "resource_id": "R1",
        "bind_target": "chip.core.usb_host_vip",
        "programmers": [_prog("branch_b0"), _prog("branch_b1")],
    }]
    connectivity_rows = [{
        "bind_target": "chip.core.usb_host_vip",
        "dut_instance": "chip.core.usb_host_vip.inst",
        "role": "PASSIVE",
        "vip_type": "svt_usb_agent",
    }]
    report = svsr.analyze_shared_vip_sequencer_registry(
        declarations, connectivity_rows=connectivity_rows)
    assert report["connectivity_rows_supplied"] is True
    assert report["entries"][0]["physical_hierarchy"] == "chip.core.usb_host_vip.inst"


def test_no_connectivity_rows_never_invents_a_hierarchy():
    declarations = [{
        "resource_id": "R1",
        "bind_target": "chip.core.usb_host_vip",
        "programmers": [_prog("branch_b0"), _prog("branch_b1")],
    }]
    report = svsr.analyze_shared_vip_sequencer_registry(declarations)
    assert report["connectivity_rows_supplied"] is False
    assert report["entries"][0]["physical_hierarchy"] is None


# ---------------------------------------------------------------------------
# resource_type honesty
# ---------------------------------------------------------------------------

def test_unrecognized_resource_type_is_reported_not_coerced():
    declarations = [{
        "resource_id": "R1",
        "resource_type": "SOME_MADE_UP_TYPE",
        "programmers": [_prog("branch_b0"), _prog("branch_b1")],
    }]
    report = svsr.analyze_shared_vip_sequencer_registry(declarations)
    entry = report["entries"][0]
    assert entry["resource_type"] == "SOME_MADE_UP_TYPE"
    assert entry["resource_type_recognized"] is False


def test_omitted_resource_type_defaults_to_unclassified():
    declarations = [{"resource_id": "R1", "programmers": [_prog("branch_b0"), _prog("branch_b1")]}]
    report = svsr.analyze_shared_vip_sequencer_registry(declarations)
    entry = report["entries"][0]
    assert entry["resource_type"] == svsr.RT_UNCLASSIFIED
    assert entry["resource_type_recognized"] is True


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def test_render_registry_table_and_format_report_do_not_raise():
    declarations = [{
        "resource_id": "R1",
        "programmers": [
            _prog("branch_b0", lock_name="A", evidence="f:1"),
            _prog("branch_b1", lock_name="B", evidence="f:2"),
        ],
    }]
    report = svsr.analyze_shared_vip_sequencer_registry(declarations)
    table = svsr.render_registry_table(report)
    assert "R1" in table
    text = svsr.format_report(report)
    assert "SHARED VIP SEQUENCER REGISTRY" in text
    assert svsr.STATUS_CONTENTION in text


def test_render_registry_table_empty_note_for_no_entries():
    report = svsr.analyze_shared_vip_sequencer_registry([])
    table = svsr.render_registry_table(report)
    assert "no shared VIP agents/sequencers declared" in table


# ---------------------------------------------------------------------------
# Real CLI subprocess invocations
# ---------------------------------------------------------------------------

def test_cli_execute_verb_contention_exit_code(tmp_path: Path):
    decl = tmp_path / "decls.json"
    decl.write_text(json.dumps([{
        "resource_id": "R1",
        "programmers": [
            _prog("branch_b0", lock_name="A", evidence="f:1"),
            _prog("branch_b1", lock_name="B", evidence="f:2"),
        ],
    }]), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.shared_vip_sequencer_registry",
         "--sequencer-declarations", str(decl), "--json"],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, text=True)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == svsr.STATUS_CONTENTION


def test_cli_execute_verb_clear_exit_code(tmp_path: Path):
    decl = tmp_path / "decls.json"
    decl.write_text(json.dumps([{
        "resource_id": "R1",
        "programmers": [
            _prog("branch_b0", lock_name="A", evidence="f:1"),
            _prog("branch_b1", lock_name="A", evidence="f:2"),
        ],
    }]), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.shared_vip_sequencer_registry",
         "--sequencer-declarations", str(decl)],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, text=True)
    assert result.returncode == 0
    assert svsr.STATUS_CLEAR in result.stdout


def test_cli_execute_verb_not_applicable_with_no_input(tmp_path: Path):
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.shared_vip_sequencer_registry"],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, text=True)
    assert result.returncode == 2
    assert svsr.STATUS_NOT_APPLICABLE in result.stdout
