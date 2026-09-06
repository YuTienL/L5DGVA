"""Tests for dv_harness/outstanding_capability_ir.py.

Covers: the default-UNKNOWN core positive path, real CONFIRMED-field construction with
evidence, NOT_AVAILABLE distinct from UNKNOWN, and the negative controls proving this
module refuses to fabricate a numeric limit -- missing evidence, unrecognized evidence
kind, a bare NOT_AVAILABLE with no reason, a non-integer/negative value, an unknown field
name, and a malformed field-spec shape.
"""
import pytest

from dv_harness.outstanding_capability_ir import (
    ALL_STATUSES,
    FIELD_NAMES,
    RECOGNIZED_EVIDENCE_KINDS,
    STATUS_CONFIRMED,
    STATUS_NOT_AVAILABLE,
    STATUS_UNKNOWN,
    OutstandingCapabilityError,
    OutstandingCapabilityIR,
    build_outstanding_capability_ir,
    render_outstanding_capability_markdown,
)


# ===========================================================================
# Core positive path
# ===========================================================================

def test_default_build_is_all_unknown():
    ir = build_outstanding_capability_ir()
    assert isinstance(ir, OutstandingCapabilityIR)
    for name in FIELD_NAMES:
        f = ir.field_by_name(name)
        assert f.status == STATUS_UNKNOWN
        assert f.value is None
        assert f.evidence is None
    assert ir.unknown_fields() == FIELD_NAMES
    assert ir.confirmed_fields() == ()
    assert ir.not_available_fields() == ()


def test_all_seven_field_names_present():
    assert FIELD_NAMES == (
        "read_max", "write_max", "per_id_limit", "global_limit",
        "slave_accept_limit", "fabric_limit", "bridge_limit",
    )


def test_confirmed_field_with_real_evidence():
    ir = build_outstanding_capability_ir(field_inputs={
        "read_max": {
            "value": 16,
            "evidence": "usb3_link_ctrl.v:412 parameter MAX_OUTSTANDING_READ = 16",
            "evidence_kind": "rtl_parameter",
        },
    })
    f = ir.field_by_name("read_max")
    assert f.status == STATUS_CONFIRMED
    assert f.value == 16
    assert f.evidence_kind == "rtl_parameter"
    assert "MAX_OUTSTANDING_READ" in f.evidence
    # every other field stays honestly UNKNOWN
    assert ir.field_by_name("write_max").status == STATUS_UNKNOWN
    assert ir.confirmed_fields() == ("read_max",)


def test_multiple_confirmed_fields_and_identity_labels():
    ir = build_outstanding_capability_ir(
        field_inputs={
            "write_max": {"value": 8, "evidence": "spec section 4.2, Table 4-1",
                          "evidence_kind": "spec_document"},
            "per_id_limit": {"value": 4, "evidence": "register CSR_ID_DEPTH bitfield",
                             "evidence_kind": "register_field"},
        },
        master_name="AXI_M0",
        slave_name="DDR_CTRL",
        fabric_name="soc_fabric_top",
    )
    assert ir.master_name == "AXI_M0"
    assert ir.slave_name == "DDR_CTRL"
    assert ir.fabric_name == "soc_fabric_top"
    assert set(ir.confirmed_fields()) == {"write_max", "per_id_limit"}
    assert ir.field_by_name("global_limit").status == STATUS_UNKNOWN


def test_not_available_distinct_from_unknown():
    ir = build_outstanding_capability_ir(field_inputs={
        "bridge_limit": {
            "status": "NOT_AVAILABLE",
            "reason": "No register or spec document describes this width-conversion "
                      "bridge's own outstanding-depth cap; RTL search found no cap register.",
        },
    })
    f = ir.field_by_name("bridge_limit")
    assert f.status == STATUS_NOT_AVAILABLE
    assert f.value is None
    assert "outstanding-depth cap" in f.reason
    # NOT_AVAILABLE and UNKNOWN must be reported through different accessor buckets
    assert "bridge_limit" in ir.not_available_fields()
    assert "bridge_limit" not in ir.unknown_fields()
    # a field genuinely never asked about stays UNKNOWN, not NOT_AVAILABLE
    assert ir.field_by_name("fabric_limit").status == STATUS_UNKNOWN


def test_all_recognized_evidence_kinds_accepted():
    for kind in RECOGNIZED_EVIDENCE_KINDS:
        ir = build_outstanding_capability_ir(field_inputs={
            "global_limit": {"value": 32, "evidence": f"evidence via {kind}",
                             "evidence_kind": kind},
        })
        assert ir.field_by_name("global_limit").status == STATUS_CONFIRMED


def test_to_dict_shape():
    ir = build_outstanding_capability_ir(field_inputs={
        "read_max": {"value": 16, "evidence": "rtl port width", "evidence_kind": "rtl_port"},
    })
    d = ir.to_dict()
    assert set(d.keys()) == {"master_name", "slave_name", "fabric_name", "fields"}
    assert set(d["fields"].keys()) == set(FIELD_NAMES)
    assert d["fields"]["read_max"]["status"] == STATUS_CONFIRMED
    assert d["fields"]["write_max"]["status"] == STATUS_UNKNOWN


def test_status_vocabulary_has_exactly_three_values():
    assert set(ALL_STATUSES) == {STATUS_UNKNOWN, STATUS_NOT_AVAILABLE, STATUS_CONFIRMED}


def test_render_markdown_produces_a_row_per_field():
    ir = build_outstanding_capability_ir(field_inputs={
        "read_max": {"value": 16, "evidence": "rtl port width", "evidence_kind": "rtl_port"},
        "write_max": {"status": "NOT_AVAILABLE", "reason": "no evidence found anywhere"},
    })
    md = render_outstanding_capability_markdown(ir)
    assert "read_max" in md
    assert "write_max" in md
    assert STATUS_CONFIRMED in md
    assert STATUS_NOT_AVAILABLE in md
    # every one of the 7 fields must appear even if UNKNOWN
    for name in FIELD_NAMES:
        assert name in md


# ===========================================================================
# Negative controls: this module refuses to fabricate/guess a limit
# ===========================================================================

def test_confirmed_value_with_no_evidence_is_refused():
    with pytest.raises(OutstandingCapabilityError) as exc:
        build_outstanding_capability_ir(field_inputs={
            "read_max": {"value": 16, "evidence": "", "evidence_kind": "rtl_parameter"},
        })
    assert exc.value.code == "CONFIRMED_WITH_NO_EVIDENCE"


def test_confirmed_value_with_missing_evidence_key_is_refused():
    with pytest.raises(OutstandingCapabilityError) as exc:
        build_outstanding_capability_ir(field_inputs={
            "read_max": {"value": 16, "evidence_kind": "rtl_parameter"},
        })
    assert exc.value.code == "CONFIRMED_WITH_NO_EVIDENCE"


def test_confirmed_value_with_unrecognized_evidence_kind_is_refused():
    with pytest.raises(OutstandingCapabilityError) as exc:
        build_outstanding_capability_ir(field_inputs={
            "read_max": {"value": 16, "evidence": "a VIP user manual example",
                         "evidence_kind": "vip_user_manual_example"},
        })
    assert exc.value.code == "UNRECOGNIZED_EVIDENCE_KIND"


def test_confirmed_value_non_integer_is_refused():
    with pytest.raises(OutstandingCapabilityError) as exc:
        build_outstanding_capability_ir(field_inputs={
            "read_max": {"value": "sixteen", "evidence": "rtl parameter",
                         "evidence_kind": "rtl_parameter"},
        })
    assert exc.value.code == "CONFIRMED_VALUE_NOT_INTEGER"


def test_confirmed_value_bool_is_refused_as_not_a_real_integer():
    with pytest.raises(OutstandingCapabilityError) as exc:
        build_outstanding_capability_ir(field_inputs={
            "read_max": {"value": True, "evidence": "rtl parameter",
                         "evidence_kind": "rtl_parameter"},
        })
    assert exc.value.code == "CONFIRMED_VALUE_NOT_INTEGER"


def test_confirmed_value_negative_is_refused():
    with pytest.raises(OutstandingCapabilityError) as exc:
        build_outstanding_capability_ir(field_inputs={
            "read_max": {"value": -1, "evidence": "rtl parameter",
                         "evidence_kind": "rtl_parameter"},
        })
    assert exc.value.code == "CONFIRMED_VALUE_NEGATIVE"


def test_not_available_with_no_reason_is_refused():
    with pytest.raises(OutstandingCapabilityError) as exc:
        build_outstanding_capability_ir(field_inputs={
            "read_max": {"status": "NOT_AVAILABLE"},
        })
    assert exc.value.code == "NOT_AVAILABLE_REASON_MISSING"


def test_not_available_with_blank_reason_is_refused():
    with pytest.raises(OutstandingCapabilityError) as exc:
        build_outstanding_capability_ir(field_inputs={
            "read_max": {"status": "NOT_AVAILABLE", "reason": "   "},
        })
    assert exc.value.code == "NOT_AVAILABLE_REASON_MISSING"


def test_unknown_field_name_in_field_inputs_is_refused():
    with pytest.raises(OutstandingCapabilityError) as exc:
        build_outstanding_capability_ir(field_inputs={
            "read_maximum_totally_wrong_name": {"value": 16, "evidence": "x",
                                                 "evidence_kind": "rtl_parameter"},
        })
    assert exc.value.code == "UNKNOWN_FIELD_NAME"


def test_field_by_name_unknown_name_is_refused():
    ir = build_outstanding_capability_ir()
    with pytest.raises(OutstandingCapabilityError) as exc:
        ir.field_by_name("not_a_real_field")
    assert exc.value.code == "UNKNOWN_FIELD_NAME"


def test_malformed_field_spec_shape_is_refused():
    with pytest.raises(OutstandingCapabilityError) as exc:
        build_outstanding_capability_ir(field_inputs={"read_max": 16})
    assert exc.value.code == "MALFORMED_FIELD_SPEC"


def test_field_spec_dict_with_neither_recognized_shape_is_refused():
    with pytest.raises(OutstandingCapabilityError) as exc:
        build_outstanding_capability_ir(field_inputs={"read_max": {"foo": "bar"}})
    assert exc.value.code == "MALFORMED_FIELD_SPEC"


def test_field_inputs_not_a_mapping_is_refused():
    with pytest.raises(OutstandingCapabilityError) as exc:
        build_outstanding_capability_ir(field_inputs=["read_max"])
    assert exc.value.code == "FIELD_INPUTS_NOT_A_MAPPING"


def test_literal_unknown_string_leaves_field_unknown():
    ir = build_outstanding_capability_ir(field_inputs={"read_max": "UNKNOWN"})
    assert ir.field_by_name("read_max").status == STATUS_UNKNOWN
