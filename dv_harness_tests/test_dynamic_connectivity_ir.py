"""Tests for dv_harness/dynamic_connectivity_ir.py.

Core positive path (a genuinely evidenced reconfigurable path, a genuinely
evidenced static path), plus real negative controls proving the module's
central fabrication-risk rule: a "reconfigurable"/"dynamic" classification is
asserted ONLY from real evidence naming a controlling mechanism, is NEVER
inferred from the fabric being an AMBA fabric in general, and is NEVER
defaulted to "static" or "dynamic" when no real evidence names a control
mechanism (UNKNOWN instead)."""
import json

import pytest

from dv_harness.dynamic_connectivity_ir import (
    STATUS_AMBIGUOUS_CONFLICTING_EVIDENCE,
    STATUS_RECONFIGURABLE_CONFIRMED,
    STATUS_STATIC_CONFIRMED,
    STATUS_UNKNOWN_MECHANISM_NOT_EVIDENCED,
    STATUS_UNKNOWN_NO_EVIDENCE,
    STATUS_UNKNOWN_STATIC_CLAIM_NOT_EVIDENCED,
    ControllingMechanism,
    DynamicConnectivityIRError,
    DynamicConnectivityPath,
    StaticRoutingClaim,
    build_dynamic_connectivity_ir,
    build_dynamic_connectivity_paths,
    classify_path_reconfigurability,
    execute_verb,
)


# ===========================================================================
# Core positive path
# ===========================================================================

def test_a_real_evidenced_control_register_classifies_reconfigurable_confirmed():
    mech = ControllingMechanism(
        register_name="FABRIC_ROUTE_CTRL",
        field_name="SLAVE_SEL",
        evidence=(
            "FABRIC_ROUTE_CTRL.SLAVE_SEL controls address decode for master M0: writing "
            "0/1/2 selects the destination slave among SLV0/SLV1/SLV2, per fabric_rtl.v:441"
        ),
    )
    result = classify_path_reconfigurability(mech, None)
    assert result.status == STATUS_RECONFIGURABLE_CONFIRMED
    assert not result.requires_human_review
    assert result.matched_phrases


def test_a_real_evidenced_hardwired_claim_classifies_static_confirmed():
    claim = StaticRoutingClaim(
        evidence="the M1->SLV3 decode is hardwired in RTL with no programmable field, per fabric_rtl.v:900",
    )
    result = classify_path_reconfigurability(None, claim)
    assert result.status == STATUS_STATIC_CONFIRMED
    assert not result.requires_human_review


def test_full_path_object_carries_its_own_classification():
    path = DynamicConnectivityPath(
        path_id="P0",
        master="M0",
        slave_or_region="SLV0",
        protocol="AXI4",
        controlling_mechanism=ControllingMechanism(
            register_name="ROUTE_SEL", evidence="ROUTE_SEL selects which slave M0 reaches, per regmap.json"
        ),
    )
    assert path.classification.status == STATUS_RECONFIGURABLE_CONFIRMED
    row = path.to_row()
    assert row["status"] == STATUS_RECONFIGURABLE_CONFIRMED
    assert row["requires_human_review"] is False


# ===========================================================================
# THE headline negative control: no evidence at all is never defaulted
# ===========================================================================

def test_no_evidence_at_all_reports_unknown_never_defaulted_to_static_or_dynamic():
    result = classify_path_reconfigurability(None, None)
    assert result.status == STATUS_UNKNOWN_NO_EVIDENCE
    assert result.requires_human_review is True
    assert result.matched_phrases == []


def test_path_with_no_mechanism_or_static_claim_is_unknown():
    path = DynamicConnectivityPath(path_id="P1", master="M1", slave_or_region="SLV1")
    assert path.classification.status == STATUS_UNKNOWN_NO_EVIDENCE
    assert path.classification.requires_human_review is True


# ===========================================================================
# Never inferred from the fabric being an AMBA fabric in general
# ===========================================================================

def test_declared_protocol_is_never_read_by_the_classifier():
    """Identical evidence, or its absence, under different declared protocol
    strings must classify byte-identically -- `classify_path_
    reconfigurability()` does not even accept a `protocol` parameter, and this
    proves `DynamicConnectivityPath` never routes it in through a side door."""
    common_kwargs = dict(
        controlling_mechanism=None,
        static_claim=None,
    )
    for protocol in (None, "AXI4", "AHB", "APB", "SOME_MADE_UP_FABRIC_NAME"):
        path = DynamicConnectivityPath(
            path_id="PX", master="MX", slave_or_region="SLVX", protocol=protocol, **common_kwargs
        )
        assert path.classification.status == STATUS_UNKNOWN_NO_EVIDENCE, (
            f"protocol={protocol!r} must not influence classification when no evidence is supplied"
        )

    mech = ControllingMechanism(
        register_name="ROUTE_SEL",
        evidence="ROUTE_SEL controls address decode for this master, per rtl.v:1",
    )
    for protocol in (None, "AXI4", "AHB", "APB", "AN_UNRELATED_LABEL"):
        path = DynamicConnectivityPath(
            path_id="PY", master="MY", slave_or_region="SLVY", protocol=protocol,
            controlling_mechanism=mech,
        )
        assert path.classification.status == STATUS_RECONFIGURABLE_CONFIRMED, (
            f"protocol={protocol!r} must not suppress a real, evidenced reconfigurable finding"
        )


def test_amba_protocol_name_alone_is_not_enough_to_claim_reconfigurable():
    """The specific scenario the task calls out: a fabric being AMBA must
    never, by itself, make a path read as reconfigurable."""
    path = DynamicConnectivityPath(
        path_id="P2", master="M2", slave_or_region="SLV2", protocol="AXI4",
    )
    assert path.classification.status != STATUS_RECONFIGURABLE_CONFIRMED
    assert path.classification.status == STATUS_UNKNOWN_NO_EVIDENCE


# ===========================================================================
# A declared mechanism whose own evidence does not actually say it controls
# routing/decode is refused, not promoted
# ===========================================================================

def test_a_declared_mechanism_with_unrelated_evidence_is_not_promoted_to_reconfigurable():
    mech = ControllingMechanism(
        register_name="IRQ_MASK",
        evidence="IRQ_MASK masks which interrupt sources are enabled, per rtl.v:88",
    )
    result = classify_path_reconfigurability(mech, None)
    assert result.status == STATUS_UNKNOWN_MECHANISM_NOT_EVIDENCED
    assert result.requires_human_review is True
    assert result.matched_phrases == []


def test_a_declared_static_claim_with_no_static_language_is_not_promoted():
    claim = StaticRoutingClaim(evidence="this register bank documents the DMA channel count, per doc.pdf p.4")
    result = classify_path_reconfigurability(None, claim)
    assert result.status == STATUS_UNKNOWN_STATIC_CLAIM_NOT_EVIDENCED
    assert result.requires_human_review is True


# ===========================================================================
# Conflicting evidence for one path is a genuine, unresolved conflict
# ===========================================================================

def test_both_mechanism_and_static_claim_declared_is_ambiguous_never_resolved():
    mech = ControllingMechanism(
        register_name="ROUTE_SEL", evidence="ROUTE_SEL selects the destination slave, per rtl.v:5",
    )
    claim = StaticRoutingClaim(evidence="the decode is hardwired, per doc.pdf p.9")
    result = classify_path_reconfigurability(mech, claim)
    assert result.status == STATUS_AMBIGUOUS_CONFLICTING_EVIDENCE
    assert result.requires_human_review is True
    assert "ROUTE_SEL" in result.reason or "selects the destination slave" in result.reason


# ===========================================================================
# Construction refusals -- an uncited claim is refused outright
# ===========================================================================

def test_controlling_mechanism_with_empty_evidence_is_refused():
    with pytest.raises(DynamicConnectivityIRError):
        ControllingMechanism(register_name="ROUTE_SEL", evidence="   ")


def test_controlling_mechanism_with_empty_register_name_is_refused():
    with pytest.raises(DynamicConnectivityIRError):
        ControllingMechanism(register_name="", evidence="controls address decode, per rtl.v:1")


def test_static_claim_with_empty_evidence_is_refused():
    with pytest.raises(DynamicConnectivityIRError):
        StaticRoutingClaim(evidence="")


@pytest.mark.parametrize("missing_field", ["path_id", "master", "slave_or_region"])
def test_path_missing_required_identity_field_is_refused(missing_field):
    kwargs = {"path_id": "P0", "master": "M0", "slave_or_region": "SLV0"}
    kwargs[missing_field] = ""
    with pytest.raises(DynamicConnectivityIRError):
        DynamicConnectivityPath(**kwargs)


# ===========================================================================
# build_dynamic_connectivity_paths / build_dynamic_connectivity_ir
# ===========================================================================

def test_build_from_dicts_produces_the_expected_mixed_statuses():
    specs = [
        {
            "path_id": "P0", "master": "M0", "slave_or_region": "SLV0", "protocol": "AXI4",
            "controlling_mechanism": {
                "register_name": "ROUTE_SEL", "field_name": "SEL",
                "evidence": "ROUTE_SEL.SEL controls address decode, per rtl.v:10",
            },
        },
        {
            "path_id": "P1", "master": "M1", "slave_or_region": "SLV1", "protocol": "AHB",
            "static_claim": {"evidence": "hardwired, non-programmable, per doc.pdf p.2"},
        },
        {"path_id": "P2", "master": "M2", "slave_or_region": "SLV2"},
    ]
    ir = build_dynamic_connectivity_ir(specs)
    statuses = {p.path_id: p.classification.status for p in ir.paths}
    assert statuses == {
        "P0": STATUS_RECONFIGURABLE_CONFIRMED,
        "P1": STATUS_STATIC_CONFIRMED,
        "P2": STATUS_UNKNOWN_NO_EVIDENCE,
    }
    summary = ir.summary()
    assert summary["total_paths"] == 3
    assert summary["requires_human_review_count"] == 1
    assert summary["counts_by_status"][STATUS_RECONFIGURABLE_CONFIRMED] == 1
    assert summary["counts_by_status"][STATUS_STATIC_CONFIRMED] == 1
    assert summary["counts_by_status"][STATUS_UNKNOWN_NO_EVIDENCE] == 1


def test_build_from_dicts_rejects_non_list_input():
    with pytest.raises(DynamicConnectivityIRError):
        build_dynamic_connectivity_paths({"not": "a list"})


def test_build_from_dicts_names_the_offending_index_on_malformed_entry():
    specs = [
        {"path_id": "P0", "master": "M0", "slave_or_region": "SLV0"},
        {"path_id": "", "master": "M1", "slave_or_region": "SLV1"},
    ]
    with pytest.raises(DynamicConnectivityIRError, match=r"path_specs\[1\]"):
        build_dynamic_connectivity_paths(specs)


def test_render_markdown_renders_a_row_per_path_and_handles_empty():
    ir = build_dynamic_connectivity_ir([
        {"path_id": "P0", "master": "M0", "slave_or_region": "SLV0",
         "controlling_mechanism": {"register_name": "R", "evidence": "controls address decode, per x:1"}},
    ])
    text = ir.render_markdown()
    assert "P0" in text
    assert STATUS_RECONFIGURABLE_CONFIRMED in text

    empty_ir = build_dynamic_connectivity_ir([])
    assert "no dynamic-connectivity paths declared" in empty_ir.render_markdown()


# ===========================================================================
# CLI front door
# ===========================================================================

def test_cli_statuses_verb():
    exit_code, result, _text = execute_verb(["statuses"])
    assert exit_code == 0
    assert STATUS_RECONFIGURABLE_CONFIRMED in result["statuses"]
    assert STATUS_STATIC_CONFIRMED in result["resolved"]


def test_cli_classify_verb_exit_0_when_every_path_resolved(tmp_path):
    doc = {
        "paths": [
            {"path_id": "P0", "master": "M0", "slave_or_region": "SLV0",
             "controlling_mechanism": {"register_name": "R", "evidence": "controls address decode, per x:1"}},
            {"path_id": "P1", "master": "M1", "slave_or_region": "SLV1",
             "static_claim": {"evidence": "hardwired, per x:2"}},
        ]
    }
    p = tmp_path / "paths.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    exit_code, result, _text = execute_verb(["classify", "--paths", str(p), "--json"])
    assert exit_code == 0
    assert result["summary"]["requires_human_review_count"] == 0


def test_cli_classify_verb_exit_1_when_any_path_unresolved(tmp_path):
    doc = [{"path_id": "P0", "master": "M0", "slave_or_region": "SLV0"}]
    p = tmp_path / "paths.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    exit_code, result, _text = execute_verb(["classify", "--paths", str(p)])
    assert exit_code == 1
    assert result["summary"]["requires_human_review_count"] == 1


def test_cli_classify_verb_exit_2_on_malformed_input(tmp_path):
    doc = [{"path_id": "", "master": "M0", "slave_or_region": "SLV0"}]
    p = tmp_path / "paths.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    exit_code, result, _text = execute_verb(["classify", "--paths", str(p)])
    assert exit_code == 2
    assert "error" in result
