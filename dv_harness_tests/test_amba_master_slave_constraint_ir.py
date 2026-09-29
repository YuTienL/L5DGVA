"""Tests for dv_harness/amba_master_slave_constraint_ir.py.

Covers the core positive path (protocol-legal layer, DUT-capability layer,
scenario layer, and the full three-layer model) plus real negative controls:
the module's one hard rule (never infer DUT capability from VIP evidence),
an unconfirmed DUT capability never being assumed to match protocol legality,
a DUT capability that contradicts protocol legality being flagged rather than
silently narrowed, conflicting evidence being reported AMBIGUOUS rather than
resolved by picking one, and the three-layer model refusing to be flattened.
"""
from __future__ import annotations

import pytest

from dv_harness.amba_master_slave_constraint_ir import (
    DIMENSIONS,
    DUT_STATUS_AMBIGUOUS,
    DUT_STATUS_CONFIRMED,
    DUT_STATUS_UNKNOWN,
    SCENARIO_STATUS_CONTRADICTION,
    SCENARIO_STATUS_LEGAL,
    SCENARIO_STATUS_NOT_APPLICABLE,
    SCENARIO_STATUS_REQUIRES_CONFIRMATION,
    AmbaMasterSlaveConstraintError,
    assert_layers_structurally_separate,
    assert_no_vip_sourced_dut_capability,
    build_amba_master_slave_constraint_model,
    build_dut_capability_constraint_ir,
    build_protocol_legal_constraint_ir,
    build_scenario_constraint_ir,
    render_constraint_model_report,
)
from dv_harness.amba_transaction_ir import (
    IR_FIELD_APPLICABILITY_UNKNOWN,
    IR_FIELD_APPLICABLE,
    IR_FIELD_NOT_APPLICABLE,
)


# ===========================================================================
# Layer 1: ProtocolLegalConstraintIR
# ===========================================================================

def test_axi4_protocol_legal_burst_facts_are_real_amba4_values():
    ir = build_protocol_legal_constraint_ir("AXI4")
    assert ir["protocol"] == "AXI4"
    burst_type = ir["fields"]["burst_type"]
    assert burst_type["status"] == IR_FIELD_APPLICABLE
    assert burst_type["legal_value"] == frozenset({"FIXED", "INCR", "WRAP"})

    burst_len = ir["fields"]["burst_len"]
    assert burst_len["status"] == IR_FIELD_APPLICABLE
    assert burst_len["legal_value"]["INCR"] == (1, 256)
    assert burst_len["legal_value"]["FIXED"] == (1, 16)
    assert burst_len["legal_value"]["WRAP"] == (1, 16)

    security = ir["fields"]["security"]
    assert security["status"] == IR_FIELD_APPLICABLE
    assert security["legal_value"] == "AxPROT[1]"


def test_apb_has_no_burst_concept_at_all():
    ir = build_protocol_legal_constraint_ir("APB")
    for dim in ("burst_type", "burst_len", "burst_size"):
        assert ir["fields"][dim]["status"] == IR_FIELD_NOT_APPLICABLE
    # APB has no security signal in this repo's tracked signal sets either.
    assert ir["fields"]["security"]["status"] == IR_FIELD_NOT_APPLICABLE
    # But outstanding/ordering are still real, general facts about APB.
    assert ir["fields"]["outstanding"]["legal_value"] == 1
    assert ir["fields"]["ordering"]["status"] == IR_FIELD_APPLICABLE


def test_apb4_gains_security_where_apb_does_not():
    apb4 = build_protocol_legal_constraint_ir("APB4")
    assert apb4["fields"]["security"]["status"] == IR_FIELD_APPLICABLE
    assert apb4["fields"]["security"]["legal_value"] == "PPROT[0]"


def test_axi4_stream_has_no_outstanding_concept():
    ir = build_protocol_legal_constraint_ir("AXI4_STREAM")
    assert ir["fields"]["outstanding"]["status"] == IR_FIELD_NOT_APPLICABLE
    assert ir["fields"]["burst_type"]["status"] == IR_FIELD_NOT_APPLICABLE
    assert ir["fields"]["ordering"]["status"] == IR_FIELD_APPLICABLE
    assert ir["unmodeled_notes"]


def test_unresolved_protocol_reports_unknown_on_every_dimension():
    ir = build_protocol_legal_constraint_ir("AMBA_PROTOCOL_UNRESOLVED")
    for dim in DIMENSIONS:
        assert ir["fields"][dim]["status"] == IR_FIELD_APPLICABILITY_UNKNOWN
        assert ir["fields"][dim]["legal_value"] is None


def test_ahb_single_outstanding_and_strict_program_order():
    ir = build_protocol_legal_constraint_ir("AHB")
    assert ir["fields"]["outstanding"]["legal_value"] == 1
    assert ir["fields"]["ordering"]["legal_value"] == "STRICT_PROGRAM_ORDER"
    assert ir["fields"]["burst_len"]["legal_value"]["WRAP4"] == (4, 4)


# ===========================================================================
# Layer 2: DUTCapabilityConstraintIR
# ===========================================================================

def test_dut_capability_confirmed_from_real_rtl_evidence():
    evidence = [
        {"dimension": "burst_len", "value": {"INCR": (1, 64)},
         "source_kind": "rtl_parameter", "citation": "usb3_fabric.v:120 MAX_INCR_LEN=64"},
    ]
    dut_ir = build_dut_capability_constraint_ir("AXI4", evidence)
    entry = dut_ir["fields"]["burst_len"]
    assert entry["status"] == DUT_STATUS_CONFIRMED
    assert entry["value"] == {"INCR": (1, 64)}
    assert "usb3_fabric.v:120" in entry["evidence"][0]


def test_dut_capability_unconfirmed_field_is_honestly_unknown():
    dut_ir = build_dut_capability_constraint_ir("AXI4", dut_evidence=[])
    for dim in DIMENSIONS:
        assert dut_ir["fields"][dim]["status"] == DUT_STATUS_UNKNOWN


def test_dut_capability_from_vip_evidence_is_forbidden():
    """THE critical rule: a VIP manual/example proves what the VIP can drive,
    never what the DUT actually implements."""
    evidence = [
        {"dimension": "burst_len", "value": {"INCR": (1, 256)},
         "source_kind": "vip_user_guide", "citation": "svt_axi_user_guide.pdf section 4.2"},
    ]
    with pytest.raises(AmbaMasterSlaveConstraintError) as exc:
        build_dut_capability_constraint_ir("AXI4", evidence)
    assert exc.value.code == "DUT_CAPABILITY_FROM_VIP_EVIDENCE_FORBIDDEN"


def test_assert_no_vip_sourced_dut_capability_direct():
    with pytest.raises(AmbaMasterSlaveConstraintError):
        assert_no_vip_sourced_dut_capability(
            [{"dimension": "outstanding", "value": 16, "source_kind": "vip_example",
              "citation": "svt example"}])
    # A real RTL source must never trip the same guard.
    assert_no_vip_sourced_dut_capability(
        [{"dimension": "outstanding", "value": 16, "source_kind": "rtl_parameter",
          "citation": "top.v:10"}])


def test_dut_capability_conflicting_evidence_is_ambiguous_not_resolved():
    evidence = [
        {"dimension": "outstanding", "value": 8, "source_kind": "rtl_parameter",
         "citation": "top.v:10 MAX_OUTSTANDING=8"},
        {"dimension": "outstanding", "value": 16, "source_kind": "spec_document",
         "citation": "programming_guide.pdf section 3.1"},
    ]
    dut_ir = build_dut_capability_constraint_ir("AXI4", evidence)
    entry = dut_ir["fields"]["outstanding"]
    assert entry["status"] == DUT_STATUS_AMBIGUOUS
    assert entry["value"] == [8, 16]


def test_dut_evidence_unrecognized_source_kind_does_not_confirm():
    evidence = [{"dimension": "outstanding", "value": 8, "source_kind": "agent_guess",
                "citation": "an agent's own guess"}]
    dut_ir = build_dut_capability_constraint_ir("AXI4", evidence)
    assert dut_ir["fields"]["outstanding"]["status"] == DUT_STATUS_UNKNOWN


def test_dut_evidence_unknown_dimension_raises():
    with pytest.raises(AmbaMasterSlaveConstraintError) as exc:
        build_dut_capability_constraint_ir(
            "AXI4",
            [{"dimension": "not_a_real_dimension", "value": 1,
              "source_kind": "rtl_parameter", "citation": "top.v:1"}])
    assert exc.value.code == "DUT_EVIDENCE_UNKNOWN_DIMENSION"


def test_spec_structural_index_enriches_citation_without_inventing_a_value():
    spec_index = {"register_chapters": [
        {"title": "Register Map", "start_page": 10, "end_page": 14}]}
    evidence = [{"dimension": "burst_len", "value": {"INCR": (1, 64)},
                "source_kind": "spec_document", "citation": "programming_guide.pdf",
                "page": 12}]
    dut_ir = build_dut_capability_constraint_ir("AXI4", evidence, spec_index)
    citation = dut_ir["fields"]["burst_len"]["evidence"][0]
    assert "Register Map" in citation
    assert "page 12" in citation


# ===========================================================================
# Layer 3: ScenarioConstraintIR
# ===========================================================================

def test_scenario_requires_human_confirmation_when_dut_capability_unknown():
    protocol_ir = build_protocol_legal_constraint_ir("AXI4")
    dut_ir = build_dut_capability_constraint_ir("AXI4", dut_evidence=[])
    scenario = build_scenario_constraint_ir(protocol_ir, dut_ir)
    entry = scenario["fields"]["burst_len"]
    assert entry["status"] == SCENARIO_STATUS_REQUIRES_CONFIRMATION
    assert entry["value"] is None
    assert "never assume" in entry["reason"]


def test_scenario_legal_narrows_protocol_max_to_dut_confirmed_value():
    protocol_ir = build_protocol_legal_constraint_ir("AXI4")
    dut_ir = build_dut_capability_constraint_ir("AXI4", [
        {"dimension": "burst_len", "value": {"INCR": (1, 64), "FIXED": (1, 16),
                                             "WRAP": (1, 16)},
         "source_kind": "rtl_parameter", "citation": "top.v:1"}])
    scenario = build_scenario_constraint_ir(protocol_ir, dut_ir)
    entry = scenario["fields"]["burst_len"]
    assert entry["status"] == SCENARIO_STATUS_LEGAL
    assert entry["value"]["INCR"] == (1, 64)  # protocol max 256 narrowed to DUT's 64


def test_scenario_flags_dut_capability_that_exceeds_protocol_legality():
    protocol_ir = build_protocol_legal_constraint_ir("AXI4")
    dut_ir = build_dut_capability_constraint_ir("AXI4", [
        {"dimension": "burst_len", "value": {"INCR": (1, 300)},
         "source_kind": "rtl_parameter", "citation": "top.v:1 (bogus 300-beat claim)"}])
    scenario = build_scenario_constraint_ir(protocol_ir, dut_ir)
    entry = scenario["fields"]["burst_len"]
    assert entry["status"] == SCENARIO_STATUS_CONTRADICTION
    assert entry["value"] is None
    assert "300" in entry["reason"]


def test_scenario_flags_outstanding_beyond_a_single_outstanding_protocols_hard_cap():
    protocol_ir = build_protocol_legal_constraint_ir("AHB")
    dut_ir = build_dut_capability_constraint_ir("AHB", [
        {"dimension": "outstanding", "value": 4, "source_kind": "rtl_parameter",
         "citation": "ahb_master.v:5"}])
    scenario = build_scenario_constraint_ir(protocol_ir, dut_ir)
    entry = scenario["fields"]["outstanding"]
    assert entry["status"] == SCENARIO_STATUS_CONTRADICTION


def test_scenario_flags_ordering_looser_than_protocol_requires():
    protocol_ir = build_protocol_legal_constraint_ir("AHB")
    dut_ir = build_dut_capability_constraint_ir("AHB", [
        {"dimension": "ordering", "value": "PER_ID_ORDERED_CROSS_ID_UNORDERED_PERMITTED",
         "source_kind": "rtl_parameter", "citation": "ahb_master.v:9"}])
    scenario = build_scenario_constraint_ir(protocol_ir, dut_ir)
    assert scenario["fields"]["ordering"]["status"] == SCENARIO_STATUS_CONTRADICTION


def test_scenario_flags_non_power_of_two_burst_size():
    protocol_ir = build_protocol_legal_constraint_ir("AXI4")
    dut_ir = build_dut_capability_constraint_ir("AXI4", [
        {"dimension": "burst_size", "value": {3}, "source_kind": "rtl_parameter",
         "citation": "top.v:2"}])
    scenario = build_scenario_constraint_ir(protocol_ir, dut_ir)
    assert scenario["fields"]["burst_size"]["status"] == SCENARIO_STATUS_CONTRADICTION


def test_scenario_never_applicable_for_apb_regardless_of_dut_claims():
    protocol_ir = build_protocol_legal_constraint_ir("APB")
    dut_ir = build_dut_capability_constraint_ir("APB", [
        {"dimension": "burst_type", "value": frozenset({"INCR"}),
         "source_kind": "rtl_parameter", "citation": "apb_master.v:1"}])
    scenario = build_scenario_constraint_ir(protocol_ir, dut_ir)
    # The protocol layer rules burst_type out entirely; the DUT layer is never
    # even consulted for it.
    assert scenario["fields"]["burst_type"]["status"] == SCENARIO_STATUS_NOT_APPLICABLE


def test_scenario_protocol_layer_mismatch_raises():
    axi4 = build_protocol_legal_constraint_ir("AXI4")
    ahb_dut = build_dut_capability_constraint_ir("AHB", [])
    with pytest.raises(AmbaMasterSlaveConstraintError) as exc:
        build_scenario_constraint_ir(axi4, ahb_dut)
    assert exc.value.code == "PROTOCOL_MISMATCH_BETWEEN_LAYERS"


# ===========================================================================
# The three-layer model -- structural separation
# ===========================================================================

def test_full_model_has_exactly_three_top_level_layers():
    model = build_amba_master_slave_constraint_model("AXI4", dut_evidence=[
        {"dimension": "outstanding", "value": 8, "source_kind": "rtl_parameter",
         "citation": "top.v:1"}])
    assert set(model.keys()) == {"protocol_legal", "dut_capability", "scenario_constraint"}
    assert model["dut_capability"]["fields"]["outstanding"]["status"] == DUT_STATUS_CONFIRMED
    assert model["scenario_constraint"]["fields"]["outstanding"]["status"] == SCENARIO_STATUS_LEGAL
    assert_layers_structurally_separate(model)  # must not raise


def test_flattened_model_is_refused():
    model = build_amba_master_slave_constraint_model("APB")
    model["burst_type"] = {"status": "APPLICABLE"}  # simulate a flattening bug
    with pytest.raises(AmbaMasterSlaveConstraintError) as exc:
        assert_layers_structurally_separate(model)
    assert exc.value.code == "CONSTRAINT_MODEL_FLATTENED"


def test_model_missing_a_layer_is_refused():
    with pytest.raises(AmbaMasterSlaveConstraintError) as exc:
        assert_layers_structurally_separate({"protocol_legal": {}, "dut_capability": {}})
    assert exc.value.code == "CONSTRAINT_MODEL_NOT_THREE_LAYERS"


def test_render_constraint_model_report_covers_all_three_layers():
    model = build_amba_master_slave_constraint_model("AHB")
    text = render_constraint_model_report(model)
    assert "Protocol-Legal Constraint" in text
    assert "DUT-Capability Constraint" in text
    assert "Scenario Constraint" in text
    assert "AHB" in text
