"""Tests for dv_harness/pattern_ir_assembly.py.

Covers: the core positive path (a real ScenarioIR-shaped list of items,
assembled into a PatternIR with global/dut/fw_policy/vip/check command
lists), plus negative controls that must read as an honest AMBIGUOUS/
UNKNOWN/NOT_AVAILABLE status or a genuinely unclassified entry -- never a
silent guess -- per this repo's Evidence Truth Rule.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from dv_harness import pattern_ir_assembly as pia


# ===========================================================================
# Fixtures: real, small, ScenarioIR-shaped inputs (plain dicts/lists)
# ===========================================================================

def _real_scenario_items():
    """A small, real ScenarioIR-shaped fixture: one item carrying an
    objective plus stimulus/checker/coverage_intent text, mirroring the
    field vocabulary `requirement_contract.RequirementContract` already uses
    for `stimulus`/`checker`/`coverage_intent` (this module does not import
    that class, but accepts the same shape duck-typed)."""
    return [
        {
            "id": "SCN-ENUM-0",
            "objective": "Verify port 0 completes enumeration at its built speed.",
            "stimulus": "Host issues GET_DESCRIPTOR requests through the VIP host agent.",
            "checker": "DSTS.CONNECTSPD for port 0 matches the built SPEED0 value.",
            "coverage_intent": "Sample enumeration_cg.speed_cp for port 0.",
            "port": 0,
        },
        {
            "id": "SCN-ENUM-1",
            "objective": "Verify port 1 completes enumeration at its built speed.",
            "stimulus": "Host issues GET_DESCRIPTOR requests through the VIP host agent.",
            "checker": "DSTS.CONNECTSPD for port 1 matches the built SPEED1 value.",
            "coverage_intent": "Sample enumeration_cg.speed_cp for port 1.",
            "port": 1,
        },
    ]


def _real_global_dut_fw_commands():
    return {
        "global_commands": ["STAGE0_WAIT_BRIDGE_READY", "STAGE1_GLOBAL_INIT"],
        "dut_commands": [
            {"text": "PORT0_PHY_BRINGUP", "port": 0},
            {"text": "PORT1_PHY_BRINGUP", "port": 1},
        ],
        "fw_policy_commands": ["FW_SERVICE_LOOP_ARM_ALL_PORTS"],
    }


# ===========================================================================
# Positive path
# ===========================================================================

def test_positive_path_assembles_all_five_layers_default_order():
    cfg = dict(_real_global_dut_fw_commands())
    cfg["items"] = _real_scenario_items()

    pir = pia.assemble_pattern_ir(cfg)

    assert len(pir.global_commands) == 2
    assert len(pir.dut_commands) == 2
    assert len(pir.fw_policy_commands) == 1
    # 2 items x (stimulus + coverage_intent) = 4 vip commands
    assert len(pir.vip_commands) == 4
    # 2 items x checker = 2 check commands
    assert len(pir.check_commands) == 2
    assert pir.unclassified == []

    # objective/port traceability preserved on generated entries
    vip_texts = {c["text"] for c in pir.vip_commands}
    assert any("GET_DESCRIPTOR" in t for t in vip_texts)
    ports = {c["port"] for c in pir.vip_commands}
    assert ports == {0, 1}

    # No declared_order supplied -> default assumed, no risk.
    assert pir.ordering_status == pia.ORDER_STATUS_DEFAULT_ASSUMED
    assert pir.ordering_risks == []
    assert pir.command_counts == {
        "global": 2, "dut": 2, "fw_policy": 1, "vip": 4, "check": 2,
    }

    as_dict = pir.as_dict()
    assert as_dict["branch_fw_present"] is True  # fw_policy_commands supplied


def test_layer_override_routes_a_field_to_a_non_default_layer():
    items = [{
        "id": "SCN-CFG-0",
        "objective": "A configure-before-enable pause point belongs with bring-up.",
        "stimulus": "Write endpoint configuration before DALEPENA is enabled.",
        "layer_overrides": {"stimulus": "dut"},
    }]
    pir = pia.assemble_pattern_ir({"items": items})
    assert len(pir.dut_commands) == 1
    assert pir.dut_commands[0]["field"] == "stimulus"
    assert pir.vip_commands == []
    assert pir.unclassified == []


# ===========================================================================
# Negative controls
# ===========================================================================

def test_item_with_no_intent_fields_is_unclassified_not_guessed():
    items = [{"id": "SCN-EMPTY", "objective": "Nothing else here."}]
    pir = pia.assemble_pattern_ir({"items": items})
    assert pir.vip_commands == []
    assert pir.check_commands == []
    assert len(pir.unclassified) == 1
    assert pir.unclassified[0]["reason"] == "NO_INTENT_FIELDS_PRESENT"
    assert pir.unclassified[0]["item_id"] == "SCN-EMPTY"


def test_layer_override_naming_an_unknown_layer_is_unclassified():
    items = [{
        "id": "SCN-BAD-OVERRIDE",
        "stimulus": "Some stimulus text.",
        "layer_overrides": {"stimulus": "branch_zzz_not_real"},
    }]
    pir = pia.assemble_pattern_ir({"items": items})
    assert pir.vip_commands == []
    assert len(pir.unclassified) == 1
    assert pir.unclassified[0]["reason"] == "LAYER_OVERRIDE_UNKNOWN_LAYER"


def test_scenario_ir_shape_unrecognized_raises_rather_than_silently_empty():
    for bad in (42, "not-a-shape", 3.14):
        try:
            pia.assemble_pattern_ir(bad)
            assert False, f"expected PatternIrAssemblyError for {bad!r}"
        except pia.PatternIrAssemblyError as e:
            assert e.reason == "SCENARIO_IR_SHAPE_UNRECOGNIZED"


def test_items_key_not_a_list_raises_distinct_reason():
    try:
        pia.assemble_pattern_ir({"items": "not-a-list"})
        assert False, "expected PatternIrAssemblyError"
    except pia.PatternIrAssemblyError as e:
        assert e.reason == "SCENARIO_IR_ITEMS_NOT_A_LIST"


def test_caller_supplied_command_missing_text_is_unclassified():
    cfg = {"items": [], "global_commands": [{"port": 0}]}
    pir = pia.assemble_pattern_ir(cfg)
    assert pir.global_commands == []
    assert len(pir.unclassified) == 1
    assert pir.unclassified[0]["reason"] == "COMMAND_ENTRY_MISSING_TEXT"


# ===========================================================================
# Ordering validation: pattern-architecture SKILL.md sections 2 and 4
# ===========================================================================

def test_default_layer_order_matches_pattern_architecture_skill():
    assert pia.DEFAULT_LAYER_ORDER == ("global", "dut", "fw_policy", "vip", "check")


def test_declared_order_matching_default_is_pass():
    result = pia.validate_layer_ordering(list(pia.DEFAULT_LAYER_ORDER))
    assert result["status"] == pia.ORDER_STATUS_PASS
    assert result["risks"] == []


def test_declared_order_naming_unknown_layer_is_ambiguous():
    result = pia.validate_layer_ordering(["global", "dut", "not_a_real_layer",
                                          "vip", "check"])
    assert result["status"] == pia.ORDER_STATUS_AMBIGUOUS
    assert result["order_used"] is None
    assert result["risks"][0]["risk"] == "UNKNOWN_LAYER_NAME_IN_DECLARED_ORDER"


def test_declared_order_incomplete_is_ambiguous():
    result = pia.validate_layer_ordering(["global", "dut", "vip", "check"])
    assert result["status"] == pia.ORDER_STATUS_AMBIGUOUS
    assert result["risks"][0]["risk"] == "INCOMPLETE_OR_DUPLICATE_DECLARED_ORDER"


def test_declared_order_check_before_vip_is_named_risk():
    # verdict placed before branch_b* completes -- exactly the section-1/2
    # violation this module must flag, not silently accept.
    result = pia.validate_layer_ordering(["global", "dut", "fw_policy", "check", "vip"])
    assert result["status"] == pia.ORDER_STATUS_DEVIATION_RISK
    risk_names = {r["risk"] for r in result["risks"]}
    assert "CHECK_BEFORE_VIP" in risk_names


def test_declared_order_fw_policy_after_vip_is_named_risk():
    result = pia.validate_layer_ordering(["global", "dut", "vip", "fw_policy", "check"])
    assert result["status"] == pia.ORDER_STATUS_DEVIATION_RISK
    risk_names = {r["risk"] for r in result["risks"]}
    assert "FW_POLICY_AFTER_VIP" in risk_names


def test_declared_order_global_not_first_is_named_risk():
    result = pia.validate_layer_ordering(["dut", "global", "fw_policy", "vip", "check"])
    assert result["status"] == pia.ORDER_STATUS_DEVIATION_RISK
    risk_names = {r["risk"] for r in result["risks"]}
    assert "GLOBAL_NOT_FIRST" in risk_names
    assert "DUT_BEFORE_GLOBAL" in risk_names


def test_join_any_with_branch_fw_present_is_flagged_as_known_trap():
    # pattern-architecture SKILL.md section 2's central trap: join_any is
    # only safe when branch_a* never returns on its own; once branch_fw is
    # its own branch, join_any silently reports a false pass.
    result = pia.validate_layer_ordering(list(pia.DEFAULT_LAYER_ORDER),
                                         vip_join_mode="join_any",
                                         branch_fw_present=True)
    assert result["status"] == pia.ORDER_STATUS_PASS  # ordering itself is fine
    risk_names = {r["risk"] for r in result["risks"]}
    assert "JOIN_ANY_WITH_BRANCH_FW" in risk_names  # but risks is non-empty anyway


def test_join_any_with_branch_fw_presence_unknown_is_flagged_unknown_not_guessed():
    result = pia.validate_layer_ordering(list(pia.DEFAULT_LAYER_ORDER),
                                         vip_join_mode="join_any",
                                         branch_fw_present=None)
    risk_names = {r["risk"] for r in result["risks"]}
    assert "JOIN_ANY_BRANCH_FW_PRESENCE_UNKNOWN" in risk_names


def test_join_any_without_branch_fw_still_requires_justification():
    result = pia.validate_layer_ordering(list(pia.DEFAULT_LAYER_ORDER),
                                         vip_join_mode="join_any",
                                         branch_fw_present=False)
    risk_names = {r["risk"] for r in result["risks"]}
    assert "JOIN_ANY_REQUIRES_JUSTIFICATION" in risk_names


def test_join_mode_join_with_branch_fw_present_has_no_join_risk():
    result = pia.validate_layer_ordering(list(pia.DEFAULT_LAYER_ORDER),
                                         vip_join_mode="join",
                                         branch_fw_present=True)
    assert result["risks"] == []


def test_end_to_end_assembly_surfaces_join_any_risk_via_top_level_config():
    cfg = {
        "items": _real_scenario_items(),
        "fw_policy_commands": ["FW_SERVICE_LOOP_ARM_ALL_PORTS"],
        "vip_join_mode": "join_any",
    }
    pir = pia.assemble_pattern_ir(cfg)
    assert pir.branch_fw_present is True
    risk_names = {r["risk"] for r in pir.ordering_risks}
    assert "JOIN_ANY_WITH_BRANCH_FW" in risk_names


def test_branch_index_suffixed_layer_names_normalize_to_canonical():
    assert pia._canonical_layer("branch_a0") == pia.LAYER_DUT
    assert pia._canonical_layer("branch_b1") == pia.LAYER_VIP
    assert pia._canonical_layer("block") == pia.LAYER_GLOBAL
    assert pia._canonical_layer("branch_fw") == pia.LAYER_FW_POLICY
    assert pia._canonical_layer("FINAL_CHECK") == pia.LAYER_CHECK
    assert pia._canonical_layer("totally_unknown_thing") is None
