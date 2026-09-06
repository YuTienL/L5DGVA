"""Tests for `dv_harness.shared_bus_resource_registry`: the intra-subsystem
branch_fw-vs-branch_a* shared-bus race detector.

Every test drives the real `analyze_shared_bus_resource_registry()` (never a
mock of its internals), and the CLI test drives the real
`python -m dv_harness.shared_bus_resource_registry` subprocess.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import shared_bus_resource_registry as sbrr
from dv_harness import connectivity as conn


def _prog(task_group, lock_name=None, evidence="pattern.txt:10"):
    return {"task_group": task_group, "lock_name": lock_name, "evidence": evidence}


# ---------------------------------------------------------------------------
# classify_task_group -- canonical vocabulary
# ---------------------------------------------------------------------------

def test_classify_task_group_recognizes_the_canonical_forms():
    assert sbrr.classify_task_group("block") == sbrr.TG_BLOCK
    assert sbrr.classify_task_group("branch_fw") == sbrr.TG_BRANCH_FW
    assert sbrr.classify_task_group("branch_a0") == sbrr.TG_BRANCH_A
    assert sbrr.classify_task_group("branch_a12") == sbrr.TG_BRANCH_A
    assert sbrr.classify_task_group("branch_b0") == sbrr.TG_BRANCH_B


@pytest.mark.parametrize("bad", [
    "branch_a", "branchA0", "BRANCH_A0", "branch_a_0", "port0", "", None, "branch_fw0",
])
def test_classify_task_group_rejects_non_canonical_forms(bad):
    assert sbrr.classify_task_group(bad) == sbrr.TG_INVALID


# ---------------------------------------------------------------------------
# Core positive path: a real branch_fw-vs-branch_a0 race, no common lock
# ---------------------------------------------------------------------------

def test_fw_a_race_detected_with_no_common_lock():
    declarations = [{
        "resource_id": "SHARED_IRQ_CTRL",
        "resource_type": sbrr.RT_INTERRUPT_CONTROLLER,
        "programmers": [
            _prog("branch_fw", lock_name="FW_IRQ_LOCK",
                  evidence="common/fw_service_loop.svh:88"),
            _prog("branch_a1", lock_name="A1_INIT_LOCK",
                  evidence="common/soc_run.svh:112"),
        ],
    }]
    report = sbrr.analyze_shared_bus_resource_registry(declarations)
    assert report["status"] == sbrr.STATUS_CONTENTION
    assert report["resource_count"] == 1
    entry = report["entries"][0]
    assert entry["conflict_status"] == sbrr.CONFLICT_FW_A_RACE
    assert entry["lock_policy"] == sbrr.LOCK_POLICY_DISTINCT
    owners = entry["conflicting_owners"]
    assert len(owners) == 1
    assert owners[0]["fw_branch"] == "branch_fw"
    assert owners[0]["a_branch"] == "branch_a1"
    assert owners[0]["fw_lock"] == "FW_IRQ_LOCK"
    assert owners[0]["a_lock"] == "A1_INIT_LOCK"
    assert owners[0]["fw_evidence"] == "common/fw_service_loop.svh:88"
    assert owners[0]["a_evidence"] == "common/soc_run.svh:112"


def test_fw_a_race_detected_when_neither_side_declares_any_lock():
    declarations = [{
        "resource_id": "SHARED_PHY_CFG_BLOCK",
        "resource_type": sbrr.RT_SHARED_PHY_CONFIG,
        "programmers": [
            _prog("branch_fw", lock_name=None, evidence="common/fw_service_loop.svh:41"),
            _prog("branch_a0", lock_name=None, evidence="common/soc_run.svh:76"),
        ],
    }]
    report = sbrr.analyze_shared_bus_resource_registry(declarations)
    assert report["status"] == sbrr.STATUS_CONTENTION
    entry = report["entries"][0]
    assert entry["conflict_status"] == sbrr.CONFLICT_FW_A_RACE
    assert entry["lock_policy"] == sbrr.LOCK_POLICY_NONE_DECLARED
    assert entry["conflicting_owners"][0]["fw_lock"] == "NONE_DECLARED"
    assert entry["conflicting_owners"][0]["a_lock"] == "NONE_DECLARED"


# ---------------------------------------------------------------------------
# Positive control for CLEAR: a real shared lock serializes the pair
# ---------------------------------------------------------------------------

def test_shared_named_lock_is_reported_clear_not_contention():
    declarations = [{
        "resource_id": "SHARED_RESET_CTRL",
        "resource_type": sbrr.RT_SHARED_RESET,
        "programmers": [
            _prog("branch_fw", lock_name="RESET_SEQ_LOCK",
                  evidence="common/fw_service_loop.svh:52"),
            _prog("branch_a0", lock_name="RESET_SEQ_LOCK",
                  evidence="common/soc_run.svh:64"),
            _prog("branch_a1", lock_name="RESET_SEQ_LOCK",
                  evidence="common/soc_run.svh:66"),
        ],
    }]
    report = sbrr.analyze_shared_bus_resource_registry(declarations)
    assert report["status"] == sbrr.STATUS_CLEAR
    entry = report["entries"][0]
    assert entry["conflict_status"] == sbrr.CONFLICT_NONE
    assert entry["lock_policy"] == sbrr.LOCK_POLICY_SINGLE_SHARED
    assert entry["conflicting_owners"] == []


# ---------------------------------------------------------------------------
# Negative controls
# ---------------------------------------------------------------------------

def test_no_declarations_is_not_applicable():
    report = sbrr.analyze_shared_bus_resource_registry([])
    assert report["status"] == sbrr.STATUS_NOT_APPLICABLE
    assert report["resource_count"] == 0

    report_none = sbrr.analyze_shared_bus_resource_registry(None)
    assert report_none["status"] == sbrr.STATUS_NOT_APPLICABLE


def test_single_programmer_is_not_applicable_not_clear():
    declarations = [{
        "resource_id": "APB_MASTER_0",
        "resource_type": sbrr.RT_BUS_MASTER,
        "programmers": [_prog("branch_a0", lock_name="A0_LOCK",
                              evidence="common/soc_run.svh:70")],
    }]
    report = sbrr.analyze_shared_bus_resource_registry(declarations)
    assert report["status"] == sbrr.STATUS_NOT_APPLICABLE
    assert report["entries"][0]["conflict_status"] == sbrr.CONFLICT_NOT_APPLICABLE
    assert report["entries"][0]["lock_policy"] == sbrr.LOCK_POLICY_SINGLE_PROGRAMMER


def test_branch_a_only_pair_is_out_of_scope_and_reports_clear_no_conflict():
    """Two branch_a* programmers on one shared resource is a real arbitration
    question (branch-mapper's cross-branch_a* rule), but it is NOT this
    module's declared detection scope (branch_fw-vs-branch_a*) -- it must
    report NO_CONFLICT for THIS check rather than a fabricated race verdict
    about a pairing nobody asked it to judge."""
    declarations = [{
        "resource_id": "SHARED_PHY_COMMON_BLOCK",
        "resource_type": sbrr.RT_SHARED_PHY_CONFIG,
        "programmers": [
            _prog("branch_a0", lock_name="A0_LOCK", evidence="common/soc_run.svh:80"),
            _prog("branch_a1", lock_name="A1_LOCK", evidence="common/soc_run.svh:82"),
        ],
    }]
    report = sbrr.analyze_shared_bus_resource_registry(declarations)
    assert report["status"] == sbrr.STATUS_CLEAR
    entry = report["entries"][0]
    assert entry["conflict_status"] == sbrr.CONFLICT_NONE
    assert "no branch_fw programmer" in entry["reason"]
    # lock_policy is still computed over the whole declared set, independent
    # of the fw/a scoping above.
    assert entry["lock_policy"] == sbrr.LOCK_POLICY_DISTINCT


def test_invalid_task_group_name_yields_unknown_not_a_silent_clear():
    declarations = [{
        "resource_id": "IRQ_CTRL",
        "resource_type": sbrr.RT_INTERRUPT_CONTROLLER,
        "programmers": [
            _prog("branch_fw", lock_name="L1", evidence="fw.svh:9"),
            _prog("branchA0", lock_name="L1", evidence="soc_run.svh:9"),  # legacy/invalid name
        ],
    }]
    report = sbrr.analyze_shared_bus_resource_registry(declarations)
    assert report["status"] == sbrr.STATUS_UNKNOWN
    entry = report["entries"][0]
    assert entry["conflict_status"] == sbrr.CONFLICT_UNKNOWN
    assert "cannot be classified" in entry["reason"]


def test_missing_evidence_yields_unknown_not_a_silent_clear():
    declarations = [{
        "resource_id": "SHARED_RESET",
        "resource_type": sbrr.RT_SHARED_RESET,
        "programmers": [
            {"task_group": "branch_fw", "lock_name": "L1", "evidence": ""},
            _prog("branch_a0", lock_name="L1", evidence="soc_run.svh:20"),
        ],
    }]
    report = sbrr.analyze_shared_bus_resource_registry(declarations)
    assert report["status"] == sbrr.STATUS_UNKNOWN
    assert report["entries"][0]["conflict_status"] == sbrr.CONFLICT_UNKNOWN


def test_one_valid_pair_still_races_even_if_a_second_declaration_is_invalid():
    """An invalid declaration on one side must not hide a real race proven by
    a DIFFERENT, valid declaration on the same resource."""
    declarations = [{
        "resource_id": "IRQ_CTRL",
        "resource_type": sbrr.RT_INTERRUPT_CONTROLLER,
        "programmers": [
            _prog("branch_fw", lock_name="FW_LOCK", evidence="fw.svh:1"),
            _prog("branch_a0", lock_name="A0_LOCK", evidence="soc_run.svh:1"),
            {"task_group": "branch_a1", "lock_name": "A1_LOCK", "evidence": ""},  # invalid
        ],
    }]
    report = sbrr.analyze_shared_bus_resource_registry(declarations)
    assert report["status"] == sbrr.STATUS_CONTENTION
    entry = report["entries"][0]
    assert entry["conflict_status"] == sbrr.CONFLICT_FW_A_RACE
    branches = {o["a_branch"] for o in entry["conflicting_owners"]}
    assert branches == {"branch_a0"}  # the invalid branch_a1 record never contributes a pair


def test_duplicate_resource_id_raises_rather_than_silently_merging():
    declarations = [
        {"resource_id": "R1", "programmers": [_prog("branch_fw"), _prog("branch_a0")]},
        {"resource_id": "R1", "programmers": [_prog("branch_fw"), _prog("branch_a1")]},
    ]
    with pytest.raises(sbrr.SharedBusResourceRegistryError) as exc:
        sbrr.analyze_shared_bus_resource_registry(declarations)
    assert exc.value.reason == "DUPLICATE_RESOURCE_ID"


def test_overall_contention_outranks_unknown_and_not_applicable():
    declarations = [
        {"resource_id": "R_RACE", "resource_type": sbrr.RT_BUS_MASTER,
         "programmers": [_prog("branch_fw", lock_name="L1"), _prog("branch_a0", lock_name="L2")]},
        {"resource_id": "R_UNKNOWN", "resource_type": sbrr.RT_SHARED_RESET,
         "programmers": [
             {"task_group": "branch_fw", "lock_name": "L1", "evidence": ""},
             _prog("branch_a0", lock_name="L1")]},
        {"resource_id": "R_SINGLE", "programmers": [_prog("branch_a0")]},
    ]
    report = sbrr.analyze_shared_bus_resource_registry(declarations)
    assert report["status"] == sbrr.STATUS_CONTENTION
    assert report["summary"]["entries_by_conflict_status"][sbrr.CONFLICT_FW_A_RACE] == 1
    assert report["summary"]["entries_by_conflict_status"][sbrr.CONFLICT_UNKNOWN] == 1
    assert report["summary"]["entries_by_conflict_status"][sbrr.CONFLICT_NOT_APPLICABLE] == 1


# ---------------------------------------------------------------------------
# lock_policy, checked directly
# ---------------------------------------------------------------------------

def test_lock_policy_partial_declaration():
    progs = sbrr.normalize_programmers([
        _prog("branch_fw", lock_name="L1", evidence="a:1"),
        _prog("branch_a0", lock_name=None, evidence="a:2"),
    ])
    assert sbrr.derive_lock_policy(progs) == sbrr.LOCK_POLICY_PARTIAL


def test_lock_policy_single_programmer():
    progs = sbrr.normalize_programmers([_prog("branch_a0", lock_name="L1", evidence="a:1")])
    assert sbrr.derive_lock_policy(progs) == sbrr.LOCK_POLICY_SINGLE_PROGRAMMER


# ---------------------------------------------------------------------------
# connectivity_rows enrichment -- optional, never invented
# ---------------------------------------------------------------------------

def test_connectivity_rows_resolve_hierarchy_when_bind_target_matches():
    row = conn.ConnectivityRow(
        dut_instance="chip.core.irq_ctrl", interface="apb_if", direction="slave",
        role="vip_role=slave_responder", vip_type="svt_apb_agent", count=1,
        active_passive=conn.ACTIVE_INTERFACE, bind_target="chip.core.irq_ctrl.apb_if",
        tier="T1",
    )
    declarations = [{
        "resource_id": "IRQ_CTRL", "resource_type": sbrr.RT_INTERRUPT_CONTROLLER,
        "bind_target": "chip.core.irq_ctrl.apb_if",
        "programmers": [_prog("branch_fw", lock_name="L1"), _prog("branch_a0", lock_name="L1")],
    }]
    report = sbrr.analyze_shared_bus_resource_registry(declarations, connectivity_rows=[row])
    assert report["connectivity_rows_supplied"] is True
    assert report["entries"][0]["physical_hierarchy"] == "chip.core.irq_ctrl"


def test_no_connectivity_rows_never_invents_a_hierarchy():
    declarations = [{
        "resource_id": "IRQ_CTRL",
        "bind_target": "chip.core.irq_ctrl.apb_if",
        "programmers": [_prog("branch_fw"), _prog("branch_a0")],
    }]
    report = sbrr.analyze_shared_bus_resource_registry(declarations)
    assert report["connectivity_rows_supplied"] is False
    assert report["entries"][0]["physical_hierarchy"] is None


# ---------------------------------------------------------------------------
# resource_type honesty: an unrecognized value is carried through, not
# silently coerced or defaulted to UNCLASSIFIED.
# ---------------------------------------------------------------------------

def test_unrecognized_resource_type_is_reported_not_coerced():
    declarations = [{
        "resource_id": "R1", "resource_type": "SOMETHING_NEW",
        "programmers": [_prog("branch_fw"), _prog("branch_a0")],
    }]
    report = sbrr.analyze_shared_bus_resource_registry(declarations)
    entry = report["entries"][0]
    assert entry["resource_type"] == "SOMETHING_NEW"
    assert entry["resource_type_recognized"] is False


def test_omitted_resource_type_defaults_to_unclassified():
    declarations = [{"resource_id": "R1",
                     "programmers": [_prog("branch_fw"), _prog("branch_a0")]}]
    report = sbrr.analyze_shared_bus_resource_registry(declarations)
    entry = report["entries"][0]
    assert entry["resource_type"] == sbrr.RT_UNCLASSIFIED
    assert entry["resource_type_recognized"] is True


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def test_render_registry_table_and_format_report_do_not_raise():
    declarations = [{
        "resource_id": "IRQ_CTRL", "resource_type": sbrr.RT_INTERRUPT_CONTROLLER,
        "programmers": [_prog("branch_fw", lock_name="L1"), _prog("branch_a0", lock_name="L2")],
    }]
    report = sbrr.analyze_shared_bus_resource_registry(declarations)
    table = sbrr.render_registry_table(report)
    assert "IRQ_CTRL" in table
    assert "branch_fw" in table
    text = sbrr.format_report(report)
    assert "CONTENTION" in text


def test_render_registry_table_empty_note_for_no_entries():
    report = sbrr.analyze_shared_bus_resource_registry([])
    table = sbrr.render_registry_table(report)
    assert "no shared resources declared" in table


# ---------------------------------------------------------------------------
# CLI front door, driven as a real subprocess
# ---------------------------------------------------------------------------

def test_cli_execute_verb_contention_exit_code(tmp_path: Path):
    decl = [{
        "resource_id": "IRQ_CTRL", "resource_type": sbrr.RT_INTERRUPT_CONTROLLER,
        "programmers": [_prog("branch_fw", lock_name="L1"), _prog("branch_a0", lock_name="L2")],
    }]
    decl_path = tmp_path / "resources.json"
    decl_path.write_text(json.dumps(decl), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.shared_bus_resource_registry",
         "--resource-declarations", str(decl_path), "--json"],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == sbrr.STATUS_CONTENTION


def test_cli_execute_verb_clear_exit_code(tmp_path: Path):
    decl = [{
        "resource_id": "R1",
        "programmers": [_prog("branch_fw", lock_name="L1"), _prog("branch_a0", lock_name="L1")],
    }]
    decl_path = tmp_path / "resources.json"
    decl_path.write_text(json.dumps(decl), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.shared_bus_resource_registry",
         "--resource-declarations", str(decl_path)],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0
    assert "CLEAR" in result.stdout


def test_cli_execute_verb_not_applicable_with_no_input(tmp_path: Path):
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.shared_bus_resource_registry"],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 2
    assert "NOT_APPLICABLE" in result.stdout
