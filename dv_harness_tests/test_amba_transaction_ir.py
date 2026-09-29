"""Tests for SYOSCB-10 (the AMBA Transaction IR) and SYOSCB-9 (the AMBA
protocol adapter PLAN) -- `dv_harness/amba_transaction_ir.py`.

Two kinds of fixture, on purpose:

  * The REAL one: the same synthetic multi-master/multi-slave AMBA4 SoC
    `test_amba_vip_bind_plan.py` parses with a real `verible-verilog-syntax`
    run, carried all the way through `build_amba_port_registry()`. Five of its
    seven fabric ports are deliberately unresolvable (a protocol bridge, a
    two-way fan-out, an unparsed black box, an unconnected port), so the IR is
    proven against ports whose endpoint hierarchy genuinely does not exist --
    not only against the clean two. An IR mechanism tested only on resolvable
    ports would be exactly the happy-path-only coverage this project has been
    burned by before.
  * SYNTHETIC AMBA_PORT_REGISTRY rows, for the protocol matrix and for the
    missing-evidence cases the real fixture cannot produce (it is AXI4-only on
    the fabric, so APB/AHB/AXI4-Stream applicability needs rows built by hand).
    These are Python dicts in the shape `AMBA_PORT_REGISTRY_FIELDS` defines;
    nothing here writes or reads SystemVerilog.

No SystemVerilog is emitted by any test, and `test_no_emittable_sv_anywhere`
asserts that of the module's own source and of every artifact it renders --
SYOSCB-33 puts every line of real adapter/IR code behind a human approval gate
this workflow has not reached.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from dv_harness import amba_transaction_ir as tir
from dv_harness import connectivity
from dv_harness.amba_fabric_discovery import (
    BIND_CHECK_UNKNOWN_VALUE,
    MULTIPLE_BRANCH_PARENT_BIND,
    assert_no_bind_statement,
    build_fabric_netlist,
    build_vip_bind_plan,
    trace_all_fabric_ports,
)
from dv_harness.amba_port_registry import (
    AMBA_PORT_REGISTRY_FIELDS,
    ENDPOINT_HIERARCHY_NOT_ESTABLISHED,
    build_amba_port_registry,
)
from dv_harness.amba_transaction_ir import (
    ADAPTER_VERDICT_ADD,
    ADAPTER_VERDICT_ENHANCE,
    ADAPTER_VERDICT_REUSE,
    ADAPTER_VERDICT_SEARCH_NOT_PERFORMED,
    AMBA_TRANSACTION_IR_FIELDS,
    AmbaTransactionIrError,
    IR_FIELD_APPLICABILITY_UNKNOWN,
    IR_FIELD_APPLICABLE,
    IR_FIELD_NOT_APPLICABLE,
    IR_FIELD_ORIGIN,
    IR_FIELD_WITNESS_SIGNALS,
    IR_OBSERVATION_POINT_UNRESOLVED,
    IR_OBSERVED_AT_MASTER_SIDE,
    IR_OBSERVED_AT_SLAVE_SIDE,
    IR_ORIGIN_ADAPTER_RUNTIME,
    IR_ORIGIN_PORT_REGISTRY,
    IR_ORIGIN_ROUTE_PREDICTOR,
    IR_REGISTRY_JOIN_COLUMN,
    IR_VALUE_ADAPTER_RUNTIME,
    IR_VALUE_NOT_APPLICABLE,
    IR_VALUE_PREDICTOR_DERIVED,
    SYOSIL_INGEST_BOUNDARY,
    assert_ir_templates_complete,
    assert_no_adapter_for_absent_protocol,
    assert_no_inapplicable_field_forced,
    build_transaction_ir_template,
    build_transaction_ir_templates,
    discovered_protocols,
    ir_field_applicability,
    observation_point,
    plan_amba_adapters,
    protocol_signal_vocabulary,
    render_amba_transaction_ir_report,
    render_ir_field_contract,
    unresolved_adapter_plans,
    unresolved_ir_fields,
)
from dv_harness.connectivity import (
    AMBA4_PROTOCOLS,
    AMBA_PROTOCOL_UNRESOLVED,
    EXTERNAL_ENDPOINT_MASTER,
    EXTERNAL_ENDPOINT_SLAVE,
    FABRIC_SIDE_MASTER_INTERFACE,
    FABRIC_SIDE_SLAVE_INTERFACE,
    REQUIRED_HUMAN_INPUT,
)
from dv_harness.syoscb_source_audit import assert_no_emittable_sv
from dv_harness.verible_parser import parse_file
from dv_harness_tests.test_amba_vip_bind_plan import FABRIC, write_fixture

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)

MODULE_SOURCE = Path(tir.__file__).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Synthetic AMBA_PORT_REGISTRY rows
# ---------------------------------------------------------------------------

def make_row(port_id: str, protocol: str, **overrides) -> dict:
    """One AMBA_PORT_REGISTRY row with every mandated column filled, so a test
    that omits a fact does so deliberately rather than by accident."""
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


# ---------------------------------------------------------------------------
# Real fixture: the parsed AMBA4 SoC -> AMBA_PORT_REGISTRY
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def registry(tmp_path_factory):
    if shutil.which(VERIBLE_BIN) is None:
        pytest.skip("verible-verilog-syntax not on PATH")
    sv = write_fixture(tmp_path_factory.mktemp("amba_transaction_ir_rtl"))
    netlist = build_fabric_netlist([parse_file(sv)], "soc_top")
    traces = trace_all_fabric_ports(netlist, FABRIC)
    plan = build_vip_bind_plan(netlist, traces)
    return build_amba_port_registry(netlist, traces, plan)


@pytest.fixture(scope="module")
def real_templates(registry):
    return build_transaction_ir_templates(registry)


def _template(templates, port_id):
    return next(t for t in templates if t["port_id"] == port_id)


# ===========================================================================
# SYOSCB-10: the field list and where each field comes from
# ===========================================================================

def test_the_ir_carries_syoscb_10s_own_field_list_in_the_docs_order():
    assert list(AMBA_TRANSACTION_IR_FIELDS) == [
        "protocol", "master_port_id", "slave_port_id", "source_hierarchy",
        "destination_hierarchy", "transaction_type", "address", "data", "byte_enable",
        "burst_type", "burst_len", "burst_size", "transaction_id", "original_id",
        "fabric_id", "response", "sequence_number", "timestamp", "route_id",
        "clock_domain", "expected_actual", "source_evidence",
    ]


def test_every_ir_field_declares_who_fills_it():
    for field in AMBA_TRANSACTION_IR_FIELDS:
        assert IR_FIELD_ORIGIN[field] in (
            IR_ORIGIN_PORT_REGISTRY, IR_ORIGIN_ADAPTER_RUNTIME, IR_ORIGIN_ROUTE_PREDICTOR)


def test_every_registry_backed_field_names_a_real_registry_column():
    """The audit's core finding as an executable check: the reusable half of the
    IR is a JOIN on the existing 19-column registry, not a second vocabulary."""
    assert set(IR_REGISTRY_JOIN_COLUMN) == {
        f for f, origin in IR_FIELD_ORIGIN.items() if origin == IR_ORIGIN_PORT_REGISTRY}
    for field, column in IR_REGISTRY_JOIN_COLUMN.items():
        assert column in AMBA_PORT_REGISTRY_FIELDS, f"{field} joins a non-existent column"


def test_the_genuinely_new_runtime_fields_are_not_claimed_as_registry_joins():
    """`address_width` is a static bit count and `address` is a per-transaction
    value; the audit's whole point is that these are different kinds of fact."""
    for field in ("address", "data", "byte_enable", "burst_type", "burst_len",
                  "burst_size", "transaction_id", "response", "sequence_number",
                  "timestamp", "transaction_type"):
        assert IR_FIELD_ORIGIN[field] == IR_ORIGIN_ADAPTER_RUNTIME
        assert field not in IR_REGISTRY_JOIN_COLUMN


def test_the_predictor_owned_fields_name_their_owner_rather_than_sitting_empty():
    for field in ("original_id", "fabric_id", "route_id", "expected_actual"):
        assert IR_FIELD_ORIGIN[field] == IR_ORIGIN_ROUTE_PREDICTOR


def test_no_witness_signal_is_invented_outside_connectivitys_signal_table():
    for field, tokens in IR_FIELD_WITNESS_SIGNALS.items():
        unknown = sorted(set(tokens) - set(connectivity.ALL_AMBA_SIGNAL_NAMES))
        assert not unknown, f"{field} witnesses signals nothing else knows: {unknown}"


# ===========================================================================
# SYOSCB-10: "Do not force protocol-inapplicable fields"
# ===========================================================================

def test_a_protocols_vocabulary_is_its_fingerprint_plus_its_familys_optional_signals():
    axi4 = protocol_signal_vocabulary("AXI4")
    assert connectivity.PROTOCOL_FINGERPRINTS["AXI4"] <= axi4
    # WSTRB is in no AXI4 fingerprint (a fingerprint is a minimum match) but
    # AXI4 really carries it, which is what makes byte_enable applicable.
    assert "WSTRB" in axi4 and "WSTRB" not in connectivity.PROTOCOL_FINGERPRINTS["AXI4"]


@pytest.mark.parametrize("protocol,expected_not_applicable", [
    ("AHB", {"byte_enable", "transaction_id", "original_id", "fabric_id"}),
    ("AHB_LITE", {"byte_enable", "transaction_id", "original_id", "fabric_id"}),
    ("APB", {"byte_enable", "burst_type", "burst_len", "burst_size",
             "transaction_id", "original_id", "fabric_id", "response"}),
    ("APB3", {"byte_enable", "burst_type", "burst_len", "burst_size",
              "transaction_id", "original_id", "fabric_id"}),
    ("APB4", {"burst_type", "burst_len", "burst_size",
              "transaction_id", "original_id", "fabric_id"}),
    ("AXI3", set()),
    ("AXI4", set()),
    ("AXI4_LITE", {"burst_type", "burst_len", "burst_size",
                   "transaction_id", "original_id", "fabric_id"}),
    ("ACE_LITE", set()),
    ("AXI4_STREAM", {"address", "burst_type", "burst_len", "burst_size", "response"}),
])
def test_field_applicability_is_derived_from_each_protocols_real_signals(
        protocol, expected_not_applicable):
    applicability = ir_field_applicability(protocol)
    assert {f for f, e in applicability.items()
            if e["status"] == IR_FIELD_NOT_APPLICABLE} == expected_not_applicable
    assert set(applicability) == set(AMBA_TRANSACTION_IR_FIELDS)


def test_every_applicable_conditional_field_cites_the_signal_that_witnesses_it():
    applicability = ir_field_applicability("AXI4")
    assert applicability["burst_len"]["witnesses"] == ["ARLEN", "AWLEN"]
    assert "AWLEN" in applicability["burst_len"]["reason"]
    assert applicability["response"]["witnesses"] == ["BRESP", "RRESP"]


def test_apb3_gains_a_response_field_that_base_apb_does_not_have():
    """PSLVERR is exactly what separates APB3 from APB in connectivity.py's own
    evidence sets; the IR inherits that distinction rather than restating it."""
    assert ir_field_applicability("APB")["response"]["status"] == IR_FIELD_NOT_APPLICABLE
    assert ir_field_applicability("APB3")["response"]["status"] == IR_FIELD_APPLICABLE
    assert "PSLVERR" in ir_field_applicability("APB3")["response"]["witnesses"]


def test_an_unresolved_protocol_reports_unknown_rather_than_not_applicable():
    """"this bus has no burst length" and "nobody established what this bus is"
    are different facts, and only the second is a closable discovery gap."""
    applicability = ir_field_applicability(AMBA_PROTOCOL_UNRESOLVED)
    for field in IR_FIELD_WITNESS_SIGNALS:
        assert applicability[field]["status"] == IR_FIELD_APPLICABILITY_UNKNOWN
    # Protocol-independent fields stay applicable: a transaction observed on an
    # unclassified bus still has a timestamp and a source of evidence.
    assert applicability["timestamp"]["status"] == IR_FIELD_APPLICABLE
    assert applicability["source_evidence"]["status"] == IR_FIELD_APPLICABLE


def test_an_inapplicable_field_holds_the_not_applicable_sentinel_and_nothing_else():
    template = build_transaction_ir_template(make_row("P_APB", "APB"))
    assert template["fields"]["burst_len"]["value"] == IR_VALUE_NOT_APPLICABLE
    assert template["fields"]["response"]["value"] == IR_VALUE_NOT_APPLICABLE
    assert_no_inapplicable_field_forced(template)


def test_forcing_an_inapplicable_field_is_refused():
    template = build_transaction_ir_template(make_row("P_APB", "APB"))
    template["fields"]["burst_len"]["value"] = 0
    with pytest.raises(AmbaTransactionIrError) as exc:
        assert_no_inapplicable_field_forced(template)
    assert exc.value.reason == "IR_INAPPLICABLE_FIELD_FORCED"
    assert exc.value.detail["fields"][0]["field"] == "burst_len"


# ===========================================================================
# Observation point and the near/far split
# ===========================================================================

def test_a_fabric_slave_interface_observes_the_master_side_and_vice_versa():
    assert observation_point(make_row("P", "AXI4", endpoint_role="",
                                      fabric_role=FABRIC_SIDE_SLAVE_INTERFACE)) == \
        IR_OBSERVED_AT_MASTER_SIDE
    assert observation_point(make_row("P", "AXI4", endpoint_role="",
                                      fabric_role=FABRIC_SIDE_MASTER_INTERFACE)) == \
        IR_OBSERVED_AT_SLAVE_SIDE


def test_the_endpoints_own_role_wins_over_the_fabric_side_role():
    row = make_row("P", "AXI4", endpoint_role=EXTERNAL_ENDPOINT_SLAVE,
                   fabric_role=FABRIC_SIDE_SLAVE_INTERFACE)
    assert observation_point(row) == IR_OBSERVED_AT_SLAVE_SIDE


def test_a_multiple_destination_parent_row_observes_nothing_of_its_own():
    row = make_row("P", "AXI4", endpoint_role="", fabric_role="",
                   vip_bind_hierarchy=MULTIPLE_BRANCH_PARENT_BIND)
    assert observation_point(row) == IR_OBSERVATION_POINT_UNRESOLVED


def test_the_near_port_id_is_joined_and_the_far_one_is_left_to_the_predictor():
    master_side = build_transaction_ir_template(
        make_row("U_FABRIC_S00_AXI", "AXI4", endpoint_role=EXTERNAL_ENDPOINT_MASTER))
    assert master_side["fields"]["master_port_id"]["value"] == "U_FABRIC_S00_AXI"
    assert master_side["fields"]["slave_port_id"]["value"] == IR_VALUE_PREDICTOR_DERIVED
    assert "SYOSCB-12" in master_side["fields"]["slave_port_id"]["evidence"][0]

    slave_side = build_transaction_ir_template(
        make_row("U_FABRIC_M00_AXI", "AXI4", endpoint_role=EXTERNAL_ENDPOINT_SLAVE))
    assert slave_side["fields"]["slave_port_id"]["value"] == "U_FABRIC_M00_AXI"
    assert slave_side["fields"]["master_port_id"]["value"] == IR_VALUE_PREDICTOR_DERIVED


def test_the_source_evidence_column_is_reused_verbatim_rather_than_reworded():
    row = make_row("P", "AXI4", source_evidence=["AMBA-16 matrix row p", "trace SOURCE_FOUND"])
    template = build_transaction_ir_template(row)
    assert template["fields"]["source_evidence"]["value"] == [
        "AMBA-16 matrix row p", "trace SOURCE_FOUND"]


# ===========================================================================
# Missing evidence is reported, never filled in
# ===========================================================================

def test_an_unknown_clock_becomes_required_human_input_not_a_guessed_domain():
    template = build_transaction_ir_template(
        make_row("P", "AXI4", clock=BIND_CHECK_UNKNOWN_VALUE))
    assert template["fields"]["clock_domain"]["value"] == REQUIRED_HUMAN_INPUT
    assert "AMBA-15 point 6" in template["fields"]["clock_domain"]["evidence"][0]
    assert "clock_domain" in template["unresolved_fields"]


def test_an_unestablished_endpoint_hierarchy_is_not_replaced_by_a_last_known_path():
    """`amba_port_registry` deliberately refuses to put a last-known path into
    `endpoint_hierarchy`; the IR must respect that refusal rather than reach
    around it."""
    template = build_transaction_ir_template(make_row(
        "P", "AXI4", endpoint_hierarchy=ENDPOINT_HIERARCHY_NOT_ESTABLISHED,
        last_known_hierarchy="soc_top.u_opaque"))
    assert template["fields"]["source_hierarchy"]["value"] == REQUIRED_HUMAN_INPUT
    assert "soc_top.u_opaque" not in str(template["fields"]["source_hierarchy"])
    assert "source_hierarchy" in template["unresolved_fields"]


def test_an_unresolved_protocol_leaves_every_conditional_field_to_a_human():
    template = build_transaction_ir_template(make_row("P", AMBA_PROTOCOL_UNRESOLVED))
    assert template["fields"]["protocol"]["value"] == REQUIRED_HUMAN_INPUT
    for field in IR_FIELD_WITNESS_SIGNALS:
        assert template["fields"][field]["value"] == REQUIRED_HUMAN_INPUT, field
        assert template["fields"][field]["applicability"] == IR_FIELD_APPLICABILITY_UNKNOWN
    # Not silently promoted to a runtime sentinel an adapter would then fill.
    assert IR_VALUE_ADAPTER_RUNTIME not in {
        template["fields"][f]["value"] for f in IR_FIELD_WITNESS_SIGNALS}
    assert set(template["unresolved_fields"]) >= set(IR_FIELD_WITNESS_SIGNALS) | {"protocol"}


def test_an_unresolved_observation_point_leaves_both_ends_open():
    template = build_transaction_ir_template(
        make_row("P", "AXI4", endpoint_role="", fabric_role=""))
    for field in ("master_port_id", "slave_port_id",
                  "source_hierarchy", "destination_hierarchy"):
        assert template["fields"][field]["value"] == REQUIRED_HUMAN_INPUT, field


def test_a_runtime_field_is_not_counted_as_missing_evidence():
    """A field with a known owner who has not run yet is not the same as a fact
    discovery failed to establish; only the second needs a human."""
    template = build_transaction_ir_template(make_row("P", "AXI4"))
    assert template["fields"]["address"]["value"] == IR_VALUE_ADAPTER_RUNTIME
    assert unresolved_ir_fields(template) == []


# ===========================================================================
# Template completeness
# ===========================================================================

def test_a_template_missing_one_of_syoscb_10s_fields_is_refused():
    template = build_transaction_ir_template(make_row("P", "AXI4"))
    template["fields"].pop("burst_size")
    with pytest.raises(AmbaTransactionIrError) as exc:
        assert_ir_templates_complete([template])
    assert exc.value.reason == "IR_TEMPLATE_INCOMPLETE"
    assert "burst_size" in exc.value.detail["missing_fields"]


def test_a_field_entry_with_an_empty_value_is_refused_rather_than_written():
    template = build_transaction_ir_template(make_row("P", "AXI4"))
    template["fields"]["timestamp"]["value"] = ""
    with pytest.raises(AmbaTransactionIrError) as exc:
        assert_ir_templates_complete([template])
    assert exc.value.reason == "IR_FIELD_ENTRY_INCOMPLETE"
    assert exc.value.detail["field"] == "timestamp"


# ===========================================================================
# SYOSCB-9: the adapter plan
# ===========================================================================

def test_only_protocols_the_registry_really_carries_get_an_adapter():
    rows = [make_row("M0", "AXI4"), make_row("S0", "APB4"),
            make_row("X0", AMBA_PROTOCOL_UNRESOLVED)]
    plans = plan_amba_adapters(rows, existing_adapters=[])
    assert [p["protocol"] for p in plans] == ["APB4", "AXI4"]
    assert discovered_protocols(rows) == ["APB4", "AXI4"]
    # SYOSCB-8: the framework can model all ten; only two are in evidence.
    assert "AHB_TRANSACTION_ADAPTER" not in {p["adapter_id"] for p in plans}
    assert_no_adapter_for_absent_protocol(plans, rows)


def test_an_adapter_planned_for_a_protocol_no_port_speaks_is_refused():
    rows = [make_row("M0", "AXI4")]
    plans = plan_amba_adapters(rows, existing_adapters=[])
    plans.append({"adapter_id": "AHB_TRANSACTION_ADAPTER", "protocol": "AHB"})
    with pytest.raises(AmbaTransactionIrError) as exc:
        assert_no_adapter_for_absent_protocol(plans, rows)
    assert exc.value.reason == "ADAPTER_PLANNED_FOR_ABSENT_PROTOCOL"
    assert exc.value.detail["adapter_ids"] == ["AHB_TRANSACTION_ADAPTER"]


def test_no_search_performed_is_not_reported_as_nothing_to_reuse():
    """SYOSCB-9 mandates searching existing adapters FIRST. `None` means nobody
    looked, which must never read as a licence to write a new adapter."""
    rows = [make_row("M0", "AXI4")]
    plans = plan_amba_adapters(rows)
    assert plans[0]["verdict"] == ADAPTER_VERDICT_SEARCH_NOT_PERFORMED
    assert plans[0]["verdict"] == REQUIRED_HUMAN_INPUT
    assert unresolved_adapter_plans(plans) == plans
    assert "no search result was supplied" in plans[0]["rationale"]


def test_a_real_search_that_found_nothing_becomes_add():
    plans = plan_amba_adapters([make_row("M0", "AXI4")], existing_adapters=[])
    assert plans[0]["verdict"] == ADAPTER_VERDICT_ADD
    assert unresolved_adapter_plans(plans) == []


def test_an_existing_adapter_covering_every_runtime_field_becomes_reuse():
    rows = [make_row("M0", "AXI4")]
    runtime = [f for f in AMBA_TRANSACTION_IR_FIELDS
               if IR_FIELD_ORIGIN[f] == IR_ORIGIN_ADAPTER_RUNTIME]
    plans = plan_amba_adapters(rows, existing_adapters=[{
        "protocol": "AXI4", "identifier": "svt_axi_transaction_normalizer",
        "evidence": "vip_ref/axi4.md:120", "covers_ir_fields": runtime}])
    assert plans[0]["verdict"] == ADAPTER_VERDICT_REUSE
    assert plans[0]["reuse_evidence"] == ["vip_ref/axi4.md:120"]


def test_an_existing_adapter_missing_a_field_becomes_enhance_not_add():
    """"Default = ENHANCE / REUSE before ADD" -- a partial match is enhanced."""
    plans = plan_amba_adapters([make_row("M0", "AXI4")], existing_adapters=[{
        "protocol": "AXI4", "identifier": "legacy_axi_adapter",
        "evidence": "connectivity.py:1", "covers_ir_fields": ["address", "data"]}])
    assert plans[0]["verdict"] == ADAPTER_VERDICT_ENHANCE
    assert "burst_len" in plans[0]["rationale"]


def test_each_adapter_entry_separates_what_it_populates_from_what_it_must_join():
    plans = plan_amba_adapters([make_row("M0", "AXI4")], existing_adapters=[])
    entry = plans[0]
    assert "address" in entry["ir_fields_to_populate"]
    assert "protocol" in entry["ir_fields_joined_from_registry"]
    assert "clock_domain" in entry["ir_fields_joined_from_registry"]
    assert "route_id" in entry["ir_fields_from_predictor"]
    assert entry["ir_fields_not_applicable"] == []
    assert set(entry["ir_fields_to_populate"]) & set(
        entry["ir_fields_joined_from_registry"]) == set()


def test_an_apb_adapter_is_told_which_fields_it_must_not_force():
    plans = plan_amba_adapters([make_row("S0", "APB")], existing_adapters=[])
    entry = plans[0]
    assert set(entry["ir_fields_not_applicable"]) >= {"burst_len", "response",
                                                      "transaction_id"}
    assert "burst_len" not in entry["ir_fields_to_populate"]


def test_the_plan_cites_the_real_upstream_ingest_boundary_read_only():
    plans = plan_amba_adapters([make_row("M0", "AXI4")], existing_adapters=[])
    assert plans[0]["syosil_ingest_boundary"] == SYOSIL_INGEST_BOUNDARY
    assert "cl_syoscb.svh:58" in SYOSIL_INGEST_BOUNDARY
    assert plans[0]["implementation_status"] == "PHASE_2_ONLY_NO_SV_EMITTED_HERE"


def test_an_empty_registry_plans_no_adapter_at_all():
    assert plan_amba_adapters([], existing_adapters=[]) == []
    assert discovered_protocols([]) == []


# ===========================================================================
# Against the REAL parsed AMBA4 SoC registry
# ===========================================================================

@requires_verible
def test_every_real_registry_row_gets_exactly_one_ir_template(registry, real_templates):
    assert [t["port_id"] for t in real_templates] == [r["port_id"] for r in registry]
    assert len(real_templates) >= 7, "the fixture must carry the seven fabric ports"


@requires_verible
def test_the_real_master_side_port_joins_its_own_port_id_from_the_registry(real_templates):
    template = _template(real_templates, "U_FABRIC_S00_AXI")
    assert template["observation_point"] == IR_OBSERVED_AT_MASTER_SIDE
    assert template["fields"]["master_port_id"]["value"] == "U_FABRIC_S00_AXI"
    assert template["fields"]["protocol"]["value"] == "AXI4"
    # The registry's own endpoint_hierarchy for this port, joined not re-traced.
    assert template["fields"]["source_hierarchy"]["value"] == "u_cpu"
    assert template["fields"]["destination_hierarchy"]["value"] == IR_VALUE_PREDICTOR_DERIVED


@requires_verible
def test_the_unresolvable_real_ports_report_missing_hierarchy_rather_than_inventing_one(
        registry, real_templates):
    """Five of the fixture's seven ports deliberately never resolve an endpoint.
    Their IR must say so."""
    unresolved = [t for t in real_templates if t["unresolved_fields"]]
    assert unresolved, "the fixture's unresolvable ports must surface in the IR"
    for template in unresolved:
        row = next(r for r in registry if r["port_id"] == template["port_id"])
        near = ("source_hierarchy" if template["observation_point"] ==
                IR_OBSERVED_AT_MASTER_SIDE else "destination_hierarchy")
        if row["endpoint_hierarchy"] == ENDPOINT_HIERARCHY_NOT_ESTABLISHED and \
                template["observation_point"] != IR_OBSERVATION_POINT_UNRESOLVED:
            assert template["fields"][near]["value"] == REQUIRED_HUMAN_INPUT


@requires_verible
def test_the_real_registry_plans_only_the_two_protocols_it_has_evidence_for(registry):
    """The fixture's fabric ports are AXI4; its AXI4->APB4 bridge contributes an
    AMBA-11 second-side APB4 row. Both are real evidence, so both get an
    adapter -- and the other eight AMBA-4 protocols get none."""
    plans = plan_amba_adapters(registry, existing_adapters=[])
    assert {p["protocol"] for p in plans} == {"AXI4", "APB4"}
    assert_no_adapter_for_absent_protocol(plans, registry)
    for absent in set(AMBA4_PROTOCOLS) - {"AXI4", "APB4"}:
        assert f"{absent}_TRANSACTION_ADAPTER" not in {p["adapter_id"] for p in plans}
    apb4 = next(p for p in plans if p["protocol"] == "APB4")
    assert set(apb4["ir_fields_not_applicable"]) >= {"burst_len", "transaction_id"}


@requires_verible
def test_the_real_report_renders_and_names_the_open_decisions(registry, real_templates):
    text = render_amba_transaction_ir_report(
        real_templates, plan_amba_adapters(registry))
    assert "SYOSCB-9 / SYOSCB-10" in text
    assert "AXI4" in text
    assert REQUIRED_HUMAN_INPUT in text
    assert "cl_syoscb.svh:58" in text
    assert "SYOSCB-33" in text


# ===========================================================================
# Phase-1 boundary: nothing emitted, nothing vendored
# ===========================================================================

def test_no_emittable_sv_anywhere():
    assert_no_emittable_sv(MODULE_SOURCE, label="amba_transaction_ir.py")
    templates = build_transaction_ir_templates(
        [make_row("M0", "AXI4"), make_row("S0", "APB")])
    plans = plan_amba_adapters([make_row("M0", "AXI4"), make_row("S0", "APB")],
                               existing_adapters=[])
    for text in (render_amba_transaction_ir_report(templates, plans),
                 render_ir_field_contract("AXI4")):
        assert_no_emittable_sv(text)
        assert_no_bind_statement(text)


def test_the_module_never_reads_or_copies_the_upstream_syoscb_tree():
    """SYOSCB-2 vendoring is Phase-2. This module cites upstream file:line
    strings and opens nothing under D:/DV/Scoreboard."""
    assert "D:/DV/Scoreboard" not in MODULE_SOURCE
    assert "uvm_syoscb-1.0.2.4" in MODULE_SOURCE  # cited by name only
    for forbidden in ("open(", "read_text(", "read_bytes(", "shutil.copy"):
        assert forbidden not in MODULE_SOURCE, forbidden
