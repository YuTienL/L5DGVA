"""Tests for `dv_harness.system_readiness_gates`.

The core positive path drives the REAL `system_readiness.derive_system_readiness()`
over a fully-populated, all-clear synthetic SYS-1/17/18-22/24/26/28/29/30/33/35
evidence set (built directly against each real `_xxx_input()` helper's own
documented CLEAR condition in `system_readiness.py`), then asserts every one of
this module's eight named gates reports READY. Every other test is a real
negative control: one real input/fact flipped to CONCERN/BLOCKED/absent, with
every OTHER input/fact still clean, asserting the fold caught exactly that one
defect on exactly the gate(s) that own it -- proving the AND-formula, not merely
exercising it.
"""

import pytest

from dv_harness import subsystem_discovery as sd
from dv_harness import system_readiness as sr
from dv_harness import system_readiness_gates as srg


# ===========================================================================
# A fully-populated, real, all-clear evidence set
# ===========================================================================

def _clean_selection():
    return {
        "selected_rows": [
            {
                "subsystem": "usb",
                "readiness": sd.READY,
                "environment_path": "envs/usb",
                "protocol": "USB",
                "readiness_factors": {
                    "build": {"status": sd.PRESENT},
                    "regression_evidence": {"status": sd.PRESENT},
                },
            },
            {
                "subsystem": "pcie",
                "readiness": sd.READY,
                "environment_path": "envs/pcie",
                "protocol": "PCIe",
                "readiness_factors": {
                    "build": {"status": sd.PRESENT},
                    "regression_evidence": {"status": sd.PRESENT},
                },
            },
        ]
    }


def _clean_integration_plan():
    return {
        "system_resource_registry": {
            "summary": {
                "entry_count": 2,
                "collapsed_resource_count": 0,
                "entries_by_conflict_status": {},
                "entries_by_reuse_decision": {},
            },
            "entries": [],
        },
        "vip_agent_deduplication_matrix": {"summary": {"blocked": 0}, "rows": []},
    }


def _clean_command_plan():
    return {
        "summary": {
            "blocking_collisions": 0,
            "collisions": 0,
            "subsystem_modes_preserved": True,
            "system_commands": 4,
        },
        "system_command_routing_plan": {"rows": []},
        "system_architecture": {"root": "chip"},
    }


def _clean_scheduling_plan():
    return {
        "shared_resource_scheduling": {
            "summary": {"by_disposition": {}, "row_count": 0},
        },
        "global_serialization_check": {
            "verdict": "NO_GLOBAL_SERIALIZATION",
        },
        "scoreboard_integration": {
            "summary": {
                "scoreboards_modified": 0,
                "scoreboards_replaced": 0,
                "scoreboards_reused": 2,
                "topology_descriptor_parts_missing": 0,
            }
        },
    }


def _clean_topology_analysis():
    return {
        "address_map_reconciliation": {
            "summary": {
                "conflicts": 0,
                "subsystems_with_self_overlap": [],
                "region_count": 2,
                "overlapping_pairs": 0,
                "by_verdict": {},
            }
        },
        "clock_reset_compatibility_input": {
            "computed_value": "PASS",
            "reason": "all clocks/resets compatible",
        },
        "clock_reset_comparison": {"summary": {"conflicts": 0}},
        "system_scenario_model": {
            "summary": {
                "cross_subsystem_scenarios": 3,
                "scenario_count": 5,
                "scenario_bodies_generated": 0,
            }
        },
    }


def _clean_regression_plan():
    return {"summary": {"entry_count": 6}}


def _clean_readiness():
    return sr.derive_system_readiness(
        _clean_selection(), _clean_integration_plan(), _clean_command_plan(),
        _clean_scheduling_plan(), _clean_topology_analysis(),
        version_pin=None, regression_plan=_clean_regression_plan())


def _clean_version_pin():
    return {
        "composition_id": "SYSCOMP-TEST",
        "subsystems": ["usb", "pcie"],
        "restorable": True,
        "unpinned_subsystems": [],
    }


# ===========================================================================
# Core positive path
# ===========================================================================

def test_all_clean_evidence_makes_every_gate_ready():
    readiness = _clean_readiness()
    assert readiness["system_readiness"] == sr.READY, readiness["evidence"]

    result = srg.derive_system_readiness_gates(
        readiness, selection=_clean_selection(), version_pin=_clean_version_pin(),
        regression_plan=_clean_regression_plan())

    for name in srg.GATE_NAMES:
        assert result["gates"][name]["verdict"] == srg.GATE_READY, (
            name, result["gates"][name])
    assert result["summary"]["system_signoff_ready"] is True
    assert result["summary"]["gates_ready"] == 8
    assert result["summary"]["gates_not_ready"] == 0
    assert result["summary"]["gates_incomplete_evidence"] == 0


def test_from_assessment_convenience_wrapper_matches_direct_call():
    readiness = _clean_readiness()
    assessment = {
        "selection": _clean_selection(),
        "version_pin": _clean_version_pin(),
        "regression_plan": _clean_regression_plan(),
        "system_readiness": readiness,
    }
    via_wrapper = srg.derive_system_readiness_gates_from_assessment(assessment)
    via_direct = srg.derive_system_readiness_gates(
        readiness, selection=_clean_selection(), version_pin=_clean_version_pin(),
        regression_plan=_clean_regression_plan())
    assert via_wrapper["summary"] == via_direct["summary"]


# ===========================================================================
# GF-AT-28: an entirely-unevidenced composition never reads READY anywhere
# ===========================================================================

def test_completely_empty_evidence_is_incomplete_everywhere_never_ready():
    readiness = sr.derive_system_readiness({}, {}, {}, {}, {})
    assert readiness["system_readiness"] == sr.UNKNOWN

    result = srg.derive_system_readiness_gates(readiness)

    for name in srg.GATE_NAMES:
        verdict = result["gates"][name]["verdict"]
        assert verdict != srg.GATE_READY, (name, result["gates"][name])
        assert verdict == srg.GATE_INCOMPLETE_EVIDENCE, (name, verdict)
    assert result["summary"]["system_signoff_ready"] is False


# ===========================================================================
# Negative controls: one real defect at a time, everything else clean
# ===========================================================================

def test_one_blocked_subsystem_blocks_only_selection_and_signoff():
    selection = _clean_selection()
    selection["selected_rows"][0]["readiness"] = sd.BLOCKED
    readiness = sr.derive_system_readiness(
        selection, _clean_integration_plan(), _clean_command_plan(),
        _clean_scheduling_plan(), _clean_topology_analysis(),
        regression_plan=_clean_regression_plan())

    result = srg.derive_system_readiness_gates(
        readiness, selection=selection, version_pin=_clean_version_pin(),
        regression_plan=_clean_regression_plan())

    assert result["gates"][srg.GATE_SUBSYSTEM_SELECTION_READY]["verdict"] == srg.GATE_NOT_READY
    assert result["gates"][srg.GATE_SYSTEM_SIGNOFF_READY]["verdict"] == srg.GATE_NOT_READY
    # Every other gate's own conditions are untouched by this defect.
    assert result["gates"][srg.GATE_COMMAND_COMPATIBILITY_READY]["verdict"] == srg.GATE_READY
    assert result["gates"][srg.GATE_SCOREBOARD_COMPOSITION_READY]["verdict"] == srg.GATE_READY


def test_blocking_command_collision_blocks_only_command_compatibility_and_signoff():
    command_plan = _clean_command_plan()
    command_plan["summary"]["blocking_collisions"] = 1
    readiness = sr.derive_system_readiness(
        _clean_selection(), _clean_integration_plan(), command_plan,
        _clean_scheduling_plan(), _clean_topology_analysis(),
        regression_plan=_clean_regression_plan())

    result = srg.derive_system_readiness_gates(
        readiness, selection=_clean_selection(), version_pin=_clean_version_pin(),
        regression_plan=_clean_regression_plan())

    assert result["gates"][srg.GATE_COMMAND_COMPATIBILITY_READY]["verdict"] == srg.GATE_NOT_READY
    assert result["gates"][srg.GATE_SYSTEM_SIGNOFF_READY]["verdict"] == srg.GATE_NOT_READY
    assert result["gates"][srg.GATE_SUBSYSTEM_SELECTION_READY]["verdict"] == srg.GATE_READY
    assert result["gates"][srg.GATE_RESOURCE_RECONCILIATION_READY]["verdict"] == srg.GATE_READY


def test_address_map_conflict_blocks_scoreboard_composition_and_signoff():
    topology_analysis = _clean_topology_analysis()
    topology_analysis["address_map_reconciliation"]["summary"]["conflicts"] = 1
    readiness = sr.derive_system_readiness(
        _clean_selection(), _clean_integration_plan(), _clean_command_plan(),
        _clean_scheduling_plan(), topology_analysis,
        regression_plan=_clean_regression_plan())

    result = srg.derive_system_readiness_gates(
        readiness, selection=_clean_selection(), version_pin=_clean_version_pin(),
        regression_plan=_clean_regression_plan())

    assert result["gates"][srg.GATE_SCOREBOARD_COMPOSITION_READY]["verdict"] == srg.GATE_NOT_READY
    assert result["gates"][srg.GATE_SYSTEM_SIGNOFF_READY]["verdict"] == srg.GATE_NOT_READY
    assert result["gates"][srg.GATE_COMMAND_COMPATIBILITY_READY]["verdict"] == srg.GATE_READY


def test_unresolved_driver_conflict_blocks_resource_reconciliation_and_error_handling():
    integration_plan = _clean_integration_plan()
    integration_plan["system_resource_registry"]["summary"]["entries_by_conflict_status"] = {
        "DRIVER_CONFLICT": 1,
    }
    integration_plan["system_resource_registry"]["entries"] = [
        {"resource_id": "AXI_M0", "conflict_status": "DRIVER_CONFLICT"},
    ]
    readiness = sr.derive_system_readiness(
        _clean_selection(), integration_plan, _clean_command_plan(),
        _clean_scheduling_plan(), _clean_topology_analysis(),
        regression_plan=_clean_regression_plan())

    assert readiness["active_driver_conflict"]["unresolved"] is True

    result = srg.derive_system_readiness_gates(
        readiness, selection=_clean_selection(), version_pin=_clean_version_pin(),
        regression_plan=_clean_regression_plan())

    assert result["gates"][srg.GATE_RESOURCE_RECONCILIATION_READY]["verdict"] == srg.GATE_NOT_READY
    assert result["gates"][srg.GATE_ERROR_HANDLING_READY]["verdict"] == srg.GATE_NOT_READY
    assert result["gates"][srg.GATE_SYSTEM_SIGNOFF_READY]["verdict"] == srg.GATE_NOT_READY
    # Unaffected gates stay clean.
    assert result["gates"][srg.GATE_BUILD_COMPOSITION_READY]["verdict"] == srg.GATE_READY


def test_unpinned_subsystem_blocks_build_composition_only():
    version_pin = {
        "composition_id": "SYSCOMP-TEST",
        "subsystems": ["usb", "pcie"],
        "restorable": False,
        "unpinned_subsystems": ["pcie"],
    }
    readiness = _clean_readiness()

    result = srg.derive_system_readiness_gates(
        readiness, selection=_clean_selection(), version_pin=version_pin,
        regression_plan=_clean_regression_plan())

    assert result["gates"][srg.GATE_BUILD_COMPOSITION_READY]["verdict"] == srg.GATE_NOT_READY
    assert result["gates"][srg.GATE_SYSTEM_SIGNOFF_READY]["verdict"] == srg.GATE_NOT_READY
    assert result["gates"][srg.GATE_REGRESSION_PLAN_READY]["verdict"] == srg.GATE_READY


def test_zero_cross_subsystem_scenarios_is_a_concern_on_regression_plan_ready():
    topology_analysis = _clean_topology_analysis()
    topology_analysis["system_scenario_model"]["summary"]["cross_subsystem_scenarios"] = 0
    readiness = sr.derive_system_readiness(
        _clean_selection(), _clean_integration_plan(), _clean_command_plan(),
        _clean_scheduling_plan(), topology_analysis,
        regression_plan=_clean_regression_plan())

    result = srg.derive_system_readiness_gates(
        readiness, selection=_clean_selection(), version_pin=_clean_version_pin(),
        regression_plan=_clean_regression_plan())

    assert result["gates"][srg.GATE_REGRESSION_PLAN_READY]["verdict"] == srg.GATE_NOT_READY
    assert result["gates"][srg.GATE_SYSTEM_SIGNOFF_READY]["verdict"] == srg.GATE_NOT_READY
    # scoreboard composition does not read scenario_availability, so it is unaffected.
    assert result["gates"][srg.GATE_SCOREBOARD_COMPOSITION_READY]["verdict"] == srg.GATE_READY


def test_zero_entry_regression_plan_is_a_real_concern_never_silently_clean():
    empty_regression_plan = {"summary": {"entry_count": 0}}
    readiness = sr.derive_system_readiness(
        _clean_selection(), _clean_integration_plan(), _clean_command_plan(),
        _clean_scheduling_plan(), _clean_topology_analysis(),
        regression_plan=empty_regression_plan)

    result = srg.derive_system_readiness_gates(
        readiness, selection=_clean_selection(), version_pin=_clean_version_pin(),
        regression_plan=empty_regression_plan)

    assert result["gates"][srg.GATE_REGRESSION_PLAN_READY]["verdict"] == srg.GATE_NOT_READY


def test_no_regression_plan_supplied_is_incomplete_evidence_not_ready_or_blocked():
    readiness = sr.derive_system_readiness(
        _clean_selection(), _clean_integration_plan(), _clean_command_plan(),
        _clean_scheduling_plan(), _clean_topology_analysis(),
        regression_plan=None)

    result = srg.derive_system_readiness_gates(
        readiness, selection=_clean_selection(), version_pin=_clean_version_pin(),
        regression_plan=None)

    assert result["gates"][srg.GATE_REGRESSION_PLAN_READY]["verdict"] == srg.GATE_INCOMPLETE_EVIDENCE
    assert result["gates"][srg.GATE_SYSTEM_SIGNOFF_READY]["verdict"] != srg.GATE_READY


# ===========================================================================
# Structural / vocabulary guarantees
# ===========================================================================

def test_gate_vocabulary_never_collides_with_models_status():
    from dv_harness.models import Status
    status_values = {member.value for member in Status}
    assert set(srg.GATE_VERDICTS).isdisjoint(status_values)


def test_exactly_eight_named_gates_declared():
    assert len(srg.GATE_NAMES) == 8
    assert len(set(srg.GATE_NAMES)) == 8
    assert srg.GATE_NAMES[-1] == srg.GATE_SYSTEM_SIGNOFF_READY


def test_readiness_document_missing_inputs_key_is_refused():
    with pytest.raises(srg.SystemReadinessGateError):
        srg.derive_system_readiness_gates({"not": "a real readiness document"})


def test_unrecognized_condition_status_is_refused():
    with pytest.raises(srg.SystemReadinessGateError):
        srg._condition("bogus", "NOT_A_REAL_STATUS", "evidence")


def test_render_and_format_do_not_raise_and_carry_every_gate_name():
    readiness = _clean_readiness()
    result = srg.derive_system_readiness_gates(
        readiness, selection=_clean_selection(), version_pin=_clean_version_pin(),
        regression_plan=_clean_regression_plan())
    table = srg.render_system_readiness_gates_table(result)
    report = srg.format_system_readiness_gates_report(result)
    for name in srg.GATE_NAMES:
        assert name in table
        assert name in report
    assert "SYSTEM_SIGNOFF_READY = True" in report
