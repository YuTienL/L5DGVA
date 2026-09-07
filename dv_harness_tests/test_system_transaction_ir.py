"""Tests for `dv_harness/system_transaction_ir.py` -- SystemTransactionIR.

Every per-fabric transaction fact used here is a REAL `amba_transaction_ir`
template, built by that module's own `build_transaction_ir_templates()` over
synthetic `AMBA_PORT_REGISTRY` rows (the identical `make_row()` fixture
`test_amba_transaction_ir.py` already established, reused verbatim rather
than re-typed). Nothing in this file hand-constructs a template dict to
"look like" real per-fabric output -- every composed field value asserted
below is read straight off the real template `build_transaction_ir_templates()`
actually returned, never guessed.
"""
from __future__ import annotations

import json

import pytest

from dv_harness.amba_fabric_discovery import BIND_CHECK_UNKNOWN_VALUE
from dv_harness.amba_port_registry import (
    AMBA_PORT_REGISTRY_FIELDS,
    ENDPOINT_HIERARCHY_NOT_ESTABLISHED,
)
from dv_harness.amba_transaction_ir import (
    AMBA_TRANSACTION_IR_FIELDS,
    IR_VALUE_PREDICTOR_DERIVED,
    build_transaction_ir_templates,
)
from dv_harness.connectivity import (
    EXTERNAL_ENDPOINT_MASTER,
    EXTERNAL_ENDPOINT_SLAVE,
    FABRIC_SIDE_SLAVE_INTERFACE,
    REQUIRED_HUMAN_INPUT,
)
from dv_harness import system_transaction_ir as stir


# ---------------------------------------------------------------------------
# Fixture -- the same make_row() convention test_amba_transaction_ir.py uses
# ---------------------------------------------------------------------------

def make_row(port_id: str, protocol: str, **overrides) -> dict:
    row = {
        "port_id": port_id,
        "fabric_port": port_id.lower(),
        "protocol": protocol,
        "fabric_role": FABRIC_SIDE_SLAVE_INTERFACE,
        "endpoint_role": EXTERNAL_ENDPOINT_MASTER,
        "endpoint_hierarchy": f"soc_top.u_{port_id.lower()}",
        "vip_bind_hierarchy": f"soc_top.u_{port_id.lower()}",
        "vip_mode": "PASSIVE_MONITOR",
        "clock": "ACLK",
        "reset": "ARESETN",
        "address_width": "32",
        "data_width": "64",
        "id_width": "4",
        "user_widths": "4",
        "scoreboard_channel": "sb_axi_master",
        "trace_status": "SOURCE_FOUND",
        "readiness": "READY_TO_BIND",
        "confidence": "HIGH",
        "source_evidence": [f"AMBA-16 matrix row {port_id.lower()}"],
        "row_id": port_id.lower(),
    }
    row.update(overrides)
    missing = [f for f in AMBA_PORT_REGISTRY_FIELDS if f not in row]
    assert not missing, f"synthetic row is missing real registry columns: {missing}"
    return row


def master_row(port_id: str, protocol: str = "AXI4", **overrides) -> dict:
    """A port observed at the MASTER side (the default `make_row()` role)."""
    return make_row(port_id, protocol, endpoint_role=EXTERNAL_ENDPOINT_MASTER, **overrides)


def slave_row(port_id: str, protocol: str = "AXI4", **overrides) -> dict:
    """A port observed at the SLAVE side."""
    return make_row(port_id, protocol, endpoint_role=EXTERNAL_ENDPOINT_SLAVE, **overrides)


def templates_for(*rows) -> list:
    """The REAL per-fabric IR templates `amba_transaction_ir` produces for
    these rows -- this is the only place any transaction fact in this test
    file comes from."""
    return build_transaction_ir_templates(rows)


# ===========================================================================
# Vocabulary / reuse sanity
# ===========================================================================

def test_known_transaction_fields_is_the_real_reused_tuple():
    assert stir.known_transaction_fields() == AMBA_TRANSACTION_IR_FIELDS
    assert len(stir.known_transaction_fields()) == 22


def test_vocabulary_disjoint_from_models_status():
    stir.assert_no_verification_verdict_vocabulary()  # must not raise


def test_link_and_overall_status_are_distinct_strings():
    assert len(set(stir.LINK_STATUSES)) == len(stir.LINK_STATUSES)
    assert len(set(stir.OVERALL_STATUSES)) == len(stir.OVERALL_STATUSES)


# ===========================================================================
# No links declared -> NOT_APPLICABLE, never a fabricated verdict
# ===========================================================================

def test_no_links_reports_not_applicable():
    ir = stir.build_system_transaction_ir({}, None)
    assert ir.overall_status == stir.OVERALL_NOT_APPLICABLE
    assert ir.entries == []
    assert "no system_transaction_links" in ir.overall_reason


def test_no_links_reports_not_applicable_with_empty_list():
    ir = stir.build_system_transaction_ir({"usb0": []}, [])
    assert ir.overall_status == stir.OVERALL_NOT_APPLICABLE


# ===========================================================================
# index_subsystem_fabrics -- validation, never silently accepted
# ===========================================================================

def test_index_subsystem_fabrics_empty_when_none():
    assert stir.index_subsystem_fabrics(None) == {}


def test_index_subsystem_fabrics_rejects_non_dict():
    with pytest.raises(stir.SystemTransactionIRError):
        stir.index_subsystem_fabrics(["not", "a", "dict"])


def test_index_subsystem_fabrics_rejects_non_list_value():
    with pytest.raises(stir.SystemTransactionIRError):
        stir.index_subsystem_fabrics({"usb0": "not-a-list"})


def test_index_subsystem_fabrics_rejects_blank_subsystem_id():
    templates = templates_for(master_row("U_M0"))
    with pytest.raises(stir.SystemTransactionIRError):
        stir.index_subsystem_fabrics({"": templates})


def test_index_subsystem_fabrics_rejects_duplicate_port_id():
    # Two distinct rows that happen to carry the same port_id -- a genuine
    # data-quality defect this module refuses to silently pick a winner over.
    row_a = master_row("U_M0", "AXI4")
    row_b = master_row("U_M0", "AHB")  # same port_id, different protocol
    templates = templates_for(row_a, row_b)
    with pytest.raises(stir.SystemTransactionIRError, match="duplicate port_id"):
        stir.index_subsystem_fabrics({"usb0": templates})


def test_index_subsystem_fabrics_propagates_incomplete_template_error():
    # A hand-mutated, INCOMPLETE template (missing the mandated 'fields' key
    # entirely) must be refused via the REAL amba_transaction_ir completeness
    # check -- never silently accepted as if it were real per-fabric output.
    templates = templates_for(master_row("U_M0"))
    broken = dict(templates[0])
    del broken["fields"]
    with pytest.raises(stir.SystemTransactionIRError):
        stir.index_subsystem_fabrics({"usb0": [broken]})


def test_index_subsystem_fabrics_builds_real_by_port_lookup():
    templates = templates_for(master_row("U_M0"), master_row("U_M1"))
    indexed = stir.index_subsystem_fabrics({"usb0": templates})
    assert set(indexed["usb0"]) == {"U_M0", "U_M1"}
    assert indexed["usb0"]["U_M0"] is templates[0]


# ===========================================================================
# build_system_transaction_entry -- link-level validation
# ===========================================================================

def _one_master_one_slave_indexed():
    master_templates = templates_for(master_row("U_M0", "AXI4"))
    slave_templates = templates_for(slave_row("U_S0", "APB"))
    return stir.index_subsystem_fabrics({"usb0": master_templates, "pcie0": slave_templates}), \
        master_templates[0], slave_templates[0]


def test_build_entry_rejects_non_dict():
    indexed, _m, _s = _one_master_one_slave_indexed()
    with pytest.raises(stir.SystemTransactionIRError):
        stir.build_system_transaction_entry("not-a-dict", indexed)


def test_build_entry_rejects_missing_link_id():
    indexed, _m, _s = _one_master_one_slave_indexed()
    link = {"master_subsystem": "usb0", "master_port_id": "U_M0",
            "slave_subsystem": "pcie0", "slave_port_id": "U_S0", "evidence": "SoC bridge doc 4.2"}
    with pytest.raises(stir.SystemTransactionIRError):
        stir.build_system_transaction_entry(link, indexed)


def test_build_entry_rejects_missing_evidence():
    indexed, _m, _s = _one_master_one_slave_indexed()
    link = {"link_id": "L0", "master_subsystem": "usb0", "master_port_id": "U_M0",
            "slave_subsystem": "pcie0", "slave_port_id": "U_S0"}
    with pytest.raises(stir.SystemTransactionIRError, match="evidence"):
        stir.build_system_transaction_entry(link, indexed)


def test_build_entry_rejects_self_loop_same_subsystem():
    indexed, _m, _s = _one_master_one_slave_indexed()
    link = {"link_id": "L0", "master_subsystem": "usb0", "master_port_id": "U_M0",
            "slave_subsystem": "usb0", "slave_port_id": "U_M0", "evidence": "bogus self-link"}
    with pytest.raises(stir.SystemTransactionIRError, match="both"):
        stir.build_system_transaction_entry(link, indexed)


# ===========================================================================
# Unknown port -- never guessed, always LINK_UNKNOWN_PORT
# ===========================================================================

def test_build_entry_unknown_master_port():
    indexed, _m, _s = _one_master_one_slave_indexed()
    link = {"link_id": "L0", "master_subsystem": "usb0", "master_port_id": "U_MISSING",
            "slave_subsystem": "pcie0", "slave_port_id": "U_S0", "evidence": "bridge doc"}
    entry = stir.build_system_transaction_entry(link, indexed)
    assert entry.link_status == stir.LINK_UNKNOWN_PORT
    assert entry.fields == {}
    assert "master usb0.U_MISSING" in entry.reason


def test_build_entry_unknown_slave_port():
    indexed, _m, _s = _one_master_one_slave_indexed()
    link = {"link_id": "L0", "master_subsystem": "usb0", "master_port_id": "U_M0",
            "slave_subsystem": "pcie0", "slave_port_id": "U_MISSING", "evidence": "bridge doc"}
    entry = stir.build_system_transaction_entry(link, indexed)
    assert entry.link_status == stir.LINK_UNKNOWN_PORT
    assert "slave pcie0.U_MISSING" in entry.reason


def test_build_entry_unknown_subsystem_entirely():
    indexed, _m, _s = _one_master_one_slave_indexed()
    link = {"link_id": "L0", "master_subsystem": "ghost_subsystem", "master_port_id": "U_M0",
            "slave_subsystem": "pcie0", "slave_port_id": "U_S0", "evidence": "bridge doc"}
    entry = stir.build_system_transaction_entry(link, indexed)
    assert entry.link_status == stir.LINK_UNKNOWN_PORT


# ===========================================================================
# Both sides resolved -- real composed fields, side by side, never merged
# ===========================================================================

def test_build_entry_both_sides_resolved_composes_every_field_side_by_side():
    indexed, master_tmpl, slave_tmpl = _one_master_one_slave_indexed()
    link = {"link_id": "L0", "master_subsystem": "usb0", "master_port_id": "U_M0",
            "slave_subsystem": "pcie0", "slave_port_id": "U_S0",
            "evidence": "SoC interconnect bridge, top.sv:412"}
    entry = stir.build_system_transaction_entry(link, indexed)

    assert entry.link_status == stir.LINK_BOTH_SIDES_RESOLVED
    assert entry.master_unresolved_fields == []
    assert entry.slave_unresolved_fields == []
    # Every one of the 22 reused fields is present -- never a partial dict.
    assert set(entry.fields) == set(AMBA_TRANSACTION_IR_FIELDS)

    # Every composed field's master/slave half is read straight off the REAL
    # per-fabric template -- never re-derived.
    for name in AMBA_TRANSACTION_IR_FIELDS:
        comp = entry.fields[name]
        assert comp.master_value == master_tmpl["fields"][name]["value"]
        assert comp.master_origin == master_tmpl["fields"][name]["origin"]
        assert comp.slave_value == slave_tmpl["fields"][name]["value"]
        assert comp.slave_origin == slave_tmpl["fields"][name]["origin"]


def test_cross_protocol_bridge_disagreement_is_reported_never_merged():
    """A real AXI4-master-to-APB-slave bridge: the two sides genuinely
    disagree on 'protocol'. This module must report BOTH values, never pick
    a winner or silently average them into one."""
    indexed, master_tmpl, slave_tmpl = _one_master_one_slave_indexed()
    link = {"link_id": "L0", "master_subsystem": "usb0", "master_port_id": "U_M0",
            "slave_subsystem": "pcie0", "slave_port_id": "U_S0", "evidence": "bridge doc 4.2"}
    entry = stir.build_system_transaction_entry(link, indexed)

    protocol_comp = entry.fields["protocol"]
    assert protocol_comp.master_value == "AXI4"
    assert protocol_comp.slave_value == "APB"
    assert protocol_comp.master_value != protocol_comp.slave_value
    assert protocol_comp.master_resolved is True
    assert protocol_comp.slave_resolved is True


# ===========================================================================
# Partially resolved -- a real discovery gap on either side is reported
# honestly, never silently treated as resolved (the negative control)
# ===========================================================================

def test_build_entry_master_side_unresolved_clock_is_never_hidden():
    master_templates = templates_for(master_row("U_M0", "AXI4", clock=BIND_CHECK_UNKNOWN_VALUE))
    slave_templates = templates_for(slave_row("U_S0", "APB"))
    indexed = stir.index_subsystem_fabrics({"usb0": master_templates, "pcie0": slave_templates})
    link = {"link_id": "L0", "master_subsystem": "usb0", "master_port_id": "U_M0",
            "slave_subsystem": "pcie0", "slave_port_id": "U_S0", "evidence": "bridge doc"}
    entry = stir.build_system_transaction_entry(link, indexed)

    assert entry.link_status == stir.LINK_SIDES_PARTIALLY_RESOLVED
    assert "clock_domain" in entry.master_unresolved_fields
    assert entry.slave_unresolved_fields == []
    clock_comp = entry.fields["clock_domain"]
    assert clock_comp.master_value == REQUIRED_HUMAN_INPUT
    assert clock_comp.master_resolved is False


def test_build_entry_slave_side_unresolved_hierarchy_is_never_hidden():
    master_templates = templates_for(master_row("U_M0", "AXI4"))
    slave_templates = templates_for(
        slave_row("U_S0", "APB", endpoint_hierarchy=ENDPOINT_HIERARCHY_NOT_ESTABLISHED)
    )
    indexed = stir.index_subsystem_fabrics({"usb0": master_templates, "pcie0": slave_templates})
    link = {"link_id": "L0", "master_subsystem": "usb0", "master_port_id": "U_M0",
            "slave_subsystem": "pcie0", "slave_port_id": "U_S0", "evidence": "bridge doc"}
    entry = stir.build_system_transaction_entry(link, indexed)

    assert entry.link_status == stir.LINK_SIDES_PARTIALLY_RESOLVED
    assert entry.master_unresolved_fields == []
    assert "destination_hierarchy" in entry.slave_unresolved_fields


# ===========================================================================
# Whole-IR worst-wins folding
# ===========================================================================

def test_overall_complete_when_every_link_fully_resolves():
    master_templates = templates_for(master_row("U_M0", "AXI4"))
    slave_templates = templates_for(slave_row("U_S0", "APB"))
    fabrics = {"usb0": master_templates, "pcie0": slave_templates}
    links = [{"link_id": "L0", "master_subsystem": "usb0", "master_port_id": "U_M0",
              "slave_subsystem": "pcie0", "slave_port_id": "U_S0", "evidence": "bridge doc"}]
    ir = stir.build_system_transaction_ir(fabrics, links)
    assert ir.overall_status == stir.OVERALL_COMPLETE
    assert len(ir.entries) == 1


def test_overall_incomplete_worst_wins_over_one_clean_link():
    clean_master = templates_for(master_row("U_M0", "AXI4"))
    clean_slave = templates_for(slave_row("U_S0", "APB"))
    dirty_master = templates_for(master_row("U_M1", "AXI4", clock=BIND_CHECK_UNKNOWN_VALUE))
    dirty_slave = templates_for(slave_row("U_S1", "APB"))
    fabrics = {"usb0": clean_master + dirty_master, "pcie0": clean_slave + dirty_slave}
    links = [
        {"link_id": "clean", "master_subsystem": "usb0", "master_port_id": "U_M0",
         "slave_subsystem": "pcie0", "slave_port_id": "U_S0", "evidence": "bridge doc A"},
        {"link_id": "dirty", "master_subsystem": "usb0", "master_port_id": "U_M1",
         "slave_subsystem": "pcie0", "slave_port_id": "U_S1", "evidence": "bridge doc B"},
    ]
    ir = stir.build_system_transaction_ir(fabrics, links)
    assert ir.overall_status == stir.OVERALL_INCOMPLETE
    statuses = {e.link_id: e.link_status for e in ir.entries}
    assert statuses["clean"] == stir.LINK_BOTH_SIDES_RESOLVED
    assert statuses["dirty"] == stir.LINK_SIDES_PARTIALLY_RESOLVED


def test_overall_incomplete_when_one_link_names_an_unknown_port():
    master_templates = templates_for(master_row("U_M0", "AXI4"))
    slave_templates = templates_for(slave_row("U_S0", "APB"))
    fabrics = {"usb0": master_templates, "pcie0": slave_templates}
    links = [{"link_id": "L0", "master_subsystem": "usb0", "master_port_id": "U_GHOST",
              "slave_subsystem": "pcie0", "slave_port_id": "U_S0", "evidence": "bridge doc"}]
    ir = stir.build_system_transaction_ir(fabrics, links)
    assert ir.overall_status == stir.OVERALL_INCOMPLETE
    assert ir.entries[0].link_status == stir.LINK_UNKNOWN_PORT


def test_duplicate_link_id_raises():
    master_templates = templates_for(master_row("U_M0", "AXI4"))
    slave_templates = templates_for(slave_row("U_S0", "APB"))
    fabrics = {"usb0": master_templates, "pcie0": slave_templates}
    links = [
        {"link_id": "L0", "master_subsystem": "usb0", "master_port_id": "U_M0",
         "slave_subsystem": "pcie0", "slave_port_id": "U_S0", "evidence": "bridge doc A"},
        {"link_id": "L0", "master_subsystem": "usb0", "master_port_id": "U_M0",
         "slave_subsystem": "pcie0", "slave_port_id": "U_S0", "evidence": "bridge doc B"},
    ]
    with pytest.raises(stir.SystemTransactionIRError, match="duplicate link_id"):
        stir.build_system_transaction_ir(fabrics, links)


def test_links_must_be_a_list():
    with pytest.raises(stir.SystemTransactionIRError):
        stir.build_system_transaction_ir({}, {"not": "a list"})


# ===========================================================================
# to_dict()/to_row() shape
# ===========================================================================

def test_to_dict_shape_carries_reused_fields_verbatim():
    ir = stir.build_system_transaction_ir({}, None)
    d = ir.to_dict()
    assert d["reused_fields"] == list(AMBA_TRANSACTION_IR_FIELDS)
    assert d["overall_status"] == stir.OVERALL_NOT_APPLICABLE
    assert d["entries"] == []


def test_entry_to_dict_and_to_row_round_trip():
    master_templates = templates_for(master_row("U_M0", "AXI4"))
    slave_templates = templates_for(slave_row("U_S0", "APB"))
    fabrics = {"usb0": master_templates, "pcie0": slave_templates}
    links = [{"link_id": "L0", "master_subsystem": "usb0", "master_port_id": "U_M0",
              "slave_subsystem": "pcie0", "slave_port_id": "U_S0", "evidence": "bridge doc"}]
    ir = stir.build_system_transaction_ir(fabrics, links)
    entry = ir.entries[0]
    d = entry.to_dict()
    assert d["link_id"] == "L0"
    assert set(d["fields"]) == set(AMBA_TRANSACTION_IR_FIELDS)
    row = entry.to_row()
    assert row["master"] == "usb0.U_M0"
    assert row["slave"] == "pcie0.U_S0"
    # JSON-serializable end to end (the CLI/report path depends on this).
    json.dumps(ir.to_dict())


# ===========================================================================
# Rendering
# ===========================================================================

def test_render_markdown_includes_overall_and_table():
    master_templates = templates_for(master_row("U_M0", "AXI4"))
    slave_templates = templates_for(slave_row("U_S0", "APB"))
    fabrics = {"usb0": master_templates, "pcie0": slave_templates}
    links = [{"link_id": "L0", "master_subsystem": "usb0", "master_port_id": "U_M0",
              "slave_subsystem": "pcie0", "slave_port_id": "U_S0", "evidence": "bridge doc"}]
    ir = stir.build_system_transaction_ir(fabrics, links)
    text = stir.render_system_transaction_markdown(ir)
    assert "Overall: " + stir.OVERALL_COMPLETE in text
    assert "usb0.U_M0" in text
    assert "pcie0.U_S0" in text


def test_render_markdown_empty_note_when_no_links():
    ir = stir.build_system_transaction_ir({}, None)
    text = stir.render_system_transaction_markdown(ir)
    assert "no system transaction links declared" in text


# ===========================================================================
# CLI front door
# ===========================================================================

def test_execute_verb_fields_lists_reused_tuple():
    code, result, _text = stir.execute_verb(["fields"])
    assert code == 0
    assert result["fields"] == list(AMBA_TRANSACTION_IR_FIELDS)


def test_execute_verb_build_success(tmp_path):
    master_templates = templates_for(master_row("U_M0", "AXI4"))
    slave_templates = templates_for(slave_row("U_S0", "APB"))
    fabrics_file = tmp_path / "fabrics.json"
    links_file = tmp_path / "links.json"
    fabrics_file.write_text(json.dumps({"usb0": master_templates, "pcie0": slave_templates}), encoding="utf-8")
    links_file.write_text(json.dumps([
        {"link_id": "L0", "master_subsystem": "usb0", "master_port_id": "U_M0",
         "slave_subsystem": "pcie0", "slave_port_id": "U_S0", "evidence": "bridge doc"}
    ]), encoding="utf-8")

    code, result, _text = stir.execute_verb([
        "build", "--fabrics", str(fabrics_file), "--links", str(links_file), "--json",
    ])
    assert code == 0
    assert result["overall_status"] == stir.OVERALL_COMPLETE


def test_execute_verb_build_reports_error_on_malformed_link(tmp_path):
    fabrics_file = tmp_path / "fabrics.json"
    links_file = tmp_path / "links.json"
    fabrics_file.write_text(json.dumps({}), encoding="utf-8")
    links_file.write_text(json.dumps([{"link_id": "L0"}]), encoding="utf-8")  # missing everything else

    code, result, _text = stir.execute_verb([
        "build", "--fabrics", str(fabrics_file), "--links", str(links_file), "--json",
    ])
    assert code == 2
    assert "error" in result


def test_execute_verb_build_not_applicable_exits_zero(tmp_path):
    fabrics_file = tmp_path / "fabrics.json"
    links_file = tmp_path / "links.json"
    fabrics_file.write_text(json.dumps({}), encoding="utf-8")
    links_file.write_text(json.dumps([]), encoding="utf-8")

    code, result, _text = stir.execute_verb([
        "build", "--fabrics", str(fabrics_file), "--links", str(links_file), "--json",
    ])
    assert code == 0
    assert result["overall_status"] == stir.OVERALL_NOT_APPLICABLE


def test_main_runs_end_to_end(tmp_path, capsys):
    fabrics_file = tmp_path / "fabrics.json"
    links_file = tmp_path / "links.json"
    fabrics_file.write_text(json.dumps({}), encoding="utf-8")
    links_file.write_text(json.dumps([]), encoding="utf-8")
    exit_code = stir.main(["build", "--fabrics", str(fabrics_file), "--links", str(links_file)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Overall" in captured.out
