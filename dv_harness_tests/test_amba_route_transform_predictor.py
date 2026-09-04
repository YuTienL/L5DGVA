"""Tests for SYOSCB-12 (the AMBA route/transform predictor) and SYOSCB-13
(address-map evidence) -- `dv_harness/amba_route_transform_predictor.py`.

Two kinds of fixture, for the same reason `test_amba_transaction_ir.py` uses
two:

  * The REAL one: the synthetic multi-master/multi-slave AMBA4 SoC
    `test_amba_vip_bind_plan.py` parses with a real `verible-verilog-syntax`
    run, carried through `build_amba_port_registry()` into real routes. That
    fixture's `u_ddr` port genuinely has no established `data_width`, so the
    predictor is exercised against a route whose width conversion CANNOT be
    decided -- and against the derived burst expectation that must inherit that
    unknown rather than defaulting.
  * SYNTHETIC AMBA_PORT_REGISTRY rows, for the transform cases the real fixture
    cannot produce (an AXI-to-APB bridge, a 64/32 downsize, an unresolved
    protocol, a non-power-of-two width pair). These are Python dicts in the
    shape `AMBA_PORT_REGISTRY_FIELDS` defines; nothing here writes or reads
    SystemVerilog, and no `uvm_syoscb` file is copied anywhere.

Every detector is tested on BOTH sides -- what it decides, and what it refuses
to decide when the evidence is missing. A predictor tested only where the
answer exists is the happy-path-only coverage this project has been burned by.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from dv_harness import amba_route_transform_predictor as rp
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
    registry_endpoints,
)
from dv_harness.amba_route_transform_predictor import (
    ADDRESS_EVIDENCE_CORROBORATES,
    ADDRESS_EVIDENCE_MISSING,
    ADDRESS_EVIDENCE_UNJOINED,
    ADDRESS_MAP_EVIDENCE_TYPES,
    BRIDGE_PROTOCOL_FAMILY,
    BRIDGE_SUB_PROTOCOL,
    BURST_MERGE,
    BURST_SPLIT,
    BURST_SPLIT_TO_SINGLE_TRANSFERS,
    DERIVED_RESPONSIBILITY_INPUTS,
    ORDERING_DOMAIN_PER_ROUTE,
    ORDERING_DOMAIN_PER_ROUTE_AND_ID,
    PREDICTOR_INFORMED_PLAN_FIELDS,
    ROUTE_LEGAL,
    ROUTE_RESPONSIBILITIES,
    ROUTE_WAIVED,
    TRANSFORM_NOT_APPLICABLE,
    TRANSFORM_NOT_IMPLIED,
    TRANSFORM_PREDICTED_FROM_TOPOLOGY,
    TRANSFORM_REQUIRED_HUMAN_INPUT,
    TRANSFORM_RUNTIME_PHASE_2,
    TRANSFORM_STATUS_VALUES,
    WIDTH_DOWNSIZE,
    WIDTH_UPSIZE,
    RouteTransformPredictorError,
    address_map_conflicts,
    assert_address_map_does_not_replace_topology,
    assert_no_route_guessed,
    assert_plan_proposals_are_not_confirmations,
    assert_predictions_complete,
    cross_check_address_map_evidence,
    detect_bridge_behavior,
    detect_burst_split_merge,
    detect_expected_response,
    detect_id_remap,
    detect_ordering_domain,
    detect_width_conversion,
    fabric_id_width,
    predict_routes,
    propose_scoreboard_plan_fields,
    registry_width,
    render_route_transform_report,
)
from dv_harness.connectivity import (
    AMBA_PROTOCOL_UNRESOLVED,
    EXTERNAL_ENDPOINT_MASTER,
    EXTERNAL_ENDPOINT_SLAVE,
    FABRIC_SIDE_MASTER_INTERFACE,
    FABRIC_SIDE_SLAVE_INTERFACE,
    REQUIRED_HUMAN_INPUT,
    SCOREBOARD_PLAN_FIELDS,
)
from dv_harness.syoscb_source_audit import (
    ORDERING_IN_ORDER,
    ORDERING_OUT_OF_ORDER,
    assert_no_emittable_sv,
)
from dv_harness.uvm_generator.address_map_verifier import AddressMapVerificationError
from dv_harness.uvm_generator.amba_fabric_generator import compute_id_width
from dv_harness.verible_parser import parse_file
from dv_harness_tests.test_amba_vip_bind_plan import FABRIC, write_fixture

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)

MODULE_SOURCE = Path(rp.__file__).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Synthetic AMBA_PORT_REGISTRY rows
# ---------------------------------------------------------------------------

def make_row(port_id: str, protocol: str, endpoint_role: str, **overrides) -> dict:
    """One AMBA_PORT_REGISTRY row with every mandated column filled, so a test
    that omits a fact does so deliberately rather than by accident."""
    row = {
        "port_id": port_id,
        "fabric_port": port_id.lower(),
        "protocol": protocol,
        # A port an external MASTER drives is the fabric's SLAVE interface, and
        # vice versa -- the same opposite-perspective rule registry_endpoints()
        # uses, so these rows project the way real ones do.
        "fabric_role": (FABRIC_SIDE_SLAVE_INTERFACE
                        if endpoint_role == EXTERNAL_ENDPOINT_MASTER
                        else FABRIC_SIDE_MASTER_INTERFACE),
        "endpoint_role": endpoint_role,
        "endpoint_hierarchy": f"soc_top.u_{port_id.lower()}",
        "vip_bind_hierarchy": f"soc_top.u_{port_id.lower()}",
        "vip_mode": "PASSIVE_MONITOR",
        "clock": "ACLK",
        "reset": "ARESETN",
        "address_width": "32",
        "data_width": "64",
        "id_width": "4",
        "user_widths": "4",
        "scoreboard_channel": "sb_axi",
        "trace_status": ("SOURCE_FOUND" if endpoint_role == EXTERNAL_ENDPOINT_MASTER
                         else "DESTINATION_FOUND"),
        "readiness": "READY_TO_BIND",
        "confidence": "HIGH",
        "source_evidence": [f"AMBA-16 matrix row {port_id.lower()}"],
        "row_id": port_id.lower(),
    }
    row.update(overrides)
    missing = [f for f in AMBA_PORT_REGISTRY_FIELDS if f not in row]
    assert not missing, f"synthetic row is missing real registry columns: {missing}"
    return row


def master(port_id="CPU_AXI", protocol="AXI4", **overrides):
    return make_row(port_id, protocol, EXTERNAL_ENDPOINT_MASTER, **overrides)


def slave(port_id="DDR_AXI", protocol="AXI4", **overrides):
    return make_row(port_id, protocol, EXTERNAL_ENDPOINT_SLAVE, **overrides)


@pytest.fixture
def axi_to_apb_rows():
    """Two AXI4 masters of different id widths, one AXI4 slave and one APB4
    slave -- every transform the module detects, on one topology."""
    return [
        master("CPU_AXI", "AXI4"),
        master("DMA_AXI", "AXI4", id_width="6"),
        slave("DDR_AXI", "AXI4", id_width="8"),
        slave("CFG_APB", "APB4", data_width="32", id_width=BIND_CHECK_UNKNOWN_VALUE),
    ]


def _route(predictions, route_id):
    return next(p for p in predictions if p["route_id"] == route_id)


def _answer(predictions, route_id, responsibility):
    return _route(predictions, route_id)["responsibilities"][responsibility]


# ---------------------------------------------------------------------------
# Real fixture: the parsed AMBA4 SoC -> AMBA_PORT_REGISTRY -> routes
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def real_registry(tmp_path_factory):
    if shutil.which(VERIBLE_BIN) is None:
        pytest.skip("verible-verilog-syntax not on PATH")
    sv = write_fixture(tmp_path_factory.mktemp("amba_route_predictor_rtl"))
    netlist = build_fabric_netlist([parse_file(sv)], "soc_top")
    traces = trace_all_fabric_ports(netlist, FABRIC)
    plan = build_vip_bind_plan(netlist, traces)
    return build_amba_port_registry(netlist, traces, plan)


@pytest.fixture(scope="module")
def real_predictions(real_registry):
    return predict_routes(real_registry, assume_full_connectivity=True)


# ===========================================================================
# SYOSCB-12's responsibility list and the status vocabulary
# ===========================================================================

def test_the_predictor_answers_syoscb_12s_own_ten_responsibilities_in_the_docs_order():
    assert list(ROUTE_RESPONSIBILITIES) == [
        "master_slave_route", "address_decode", "address_translation", "id_remap",
        "width_conversion", "burst_split_merge", "bridge_behavior",
        "expected_response", "routing_legality", "ordering_domain",
    ]


def test_required_human_input_reuses_the_harnesss_one_sentinel():
    """A second private "a human must supply this" string is exactly the
    duplicate-mechanism failure this project keeps catching."""
    assert TRANSFORM_REQUIRED_HUMAN_INPUT is REQUIRED_HUMAN_INPUT


def test_runtime_phase_2_is_not_the_same_status_as_required_human_input():
    """"Nobody has been asked" and "nobody is approved to run it yet" are the
    two sides of SYOSCB-33/34's gate and must stay distinguishable."""
    assert TRANSFORM_RUNTIME_PHASE_2 != TRANSFORM_REQUIRED_HUMAN_INPUT
    assert TRANSFORM_RUNTIME_PHASE_2 in TRANSFORM_STATUS_VALUES


# ===========================================================================
# registry_width: an unestablished width is None, never a plausible default
# ===========================================================================

@pytest.mark.parametrize("raw", [BIND_CHECK_UNKNOWN_VALUE, REQUIRED_HUMAN_INPUT,
                                 "N/A", "", None, "0", "-4"])
def test_an_unestablished_width_reads_as_none_not_as_a_default(raw):
    assert registry_width({"data_width": raw}, "data_width") is None


@pytest.mark.parametrize("raw,expected", [("64", 64), (32, 32), ("0x20", 32), (" 8 ", 8)])
def test_a_real_width_is_read_as_an_int(raw, expected):
    assert registry_width({"data_width": raw}, "data_width") == expected


# ===========================================================================
# Width conversion
# ===========================================================================

def test_equal_data_widths_imply_no_conversion_and_still_state_why():
    entry = detect_width_conversion(master(data_width="64"), slave(data_width="64"))
    assert entry["status"] == TRANSFORM_NOT_IMPLIED
    assert entry["evidence"], "even a NO_TRANSFORM answer must state its basis"


def test_a_wider_master_than_slave_is_a_downsize_with_a_real_ratio():
    entry = detect_width_conversion(master(data_width="64"), slave(data_width="16"))
    assert entry["status"] == TRANSFORM_PREDICTED_FROM_TOPOLOGY
    assert entry["value"]["direction"] == WIDTH_DOWNSIZE
    assert entry["value"]["ratio"] == 4


def test_a_narrower_master_than_slave_is_an_upsize():
    entry = detect_width_conversion(master(data_width="32"), slave(data_width="128"))
    assert entry["value"]["direction"] == WIDTH_UPSIZE
    assert entry["value"]["ratio"] == 4


def test_a_missing_data_width_refuses_rather_than_assuming_no_conversion():
    entry = detect_width_conversion(
        master(data_width=BIND_CHECK_UNKNOWN_VALUE), slave(data_width="64"))
    assert entry["status"] == TRANSFORM_REQUIRED_HUMAN_INPUT
    assert "data_width" in entry["evidence"][0]


def test_a_non_integer_width_ratio_goes_to_a_human_rather_than_a_computed_fraction():
    entry = detect_width_conversion(master(data_width="48"), slave(data_width="32"))
    assert entry["status"] == TRANSFORM_REQUIRED_HUMAN_INPUT


# ===========================================================================
# Burst split / merge
# ===========================================================================

def test_a_destination_with_no_burst_concept_splits_into_single_transfers():
    m, s = master(protocol="AXI4"), slave(protocol="APB4", data_width="64")
    entry = detect_burst_split_merge(m, s, detect_width_conversion(m, s))
    assert entry["value"]["kind"] == BURST_SPLIT_TO_SINGLE_TRANSFERS


def test_neither_end_carrying_a_burst_is_not_applicable_not_no_transform():
    m, s = master(protocol="APB4"), slave(protocol="APB3")
    entry = detect_burst_split_merge(m, s, detect_width_conversion(m, s))
    assert entry["status"] == TRANSFORM_NOT_APPLICABLE


def test_a_downsize_multiplies_the_beat_count_and_an_upsize_divides_it():
    m, s = master(data_width="64"), slave(data_width="32")
    split = detect_burst_split_merge(m, s, detect_width_conversion(m, s))
    assert split["value"] == {"kind": BURST_SPLIT, "beat_count_factor": 2}
    m, s = master(data_width="32"), slave(data_width="64")
    merge = detect_burst_split_merge(m, s, detect_width_conversion(m, s))
    assert merge["value"] == {"kind": BURST_MERGE, "beat_count_factor": 2}


def test_the_burst_expectation_inherits_an_unknown_width_instead_of_defaulting():
    """The derived-from-a-guess failure mode, at the function level."""
    m, s = master(data_width=BIND_CHECK_UNKNOWN_VALUE), slave()
    width = detect_width_conversion(m, s)
    entry = detect_burst_split_merge(m, s, width)
    assert entry["status"] == TRANSFORM_REQUIRED_HUMAN_INPUT
    assert any("data_width" in e for e in entry["evidence"])


def test_an_unresolved_protocol_leaves_the_burst_expectation_open():
    m, s = master(protocol=AMBA_PROTOCOL_UNRESOLVED), slave()
    entry = detect_burst_split_merge(m, s, detect_width_conversion(m, s))
    assert entry["status"] == TRANSFORM_REQUIRED_HUMAN_INPUT


def test_burst_applicability_comes_from_connectivitys_signal_sets_not_from_this_module():
    """No AMBA signal name is typed in this module: "APB has no burst" must be a
    consequence of `connectivity.py`'s reviewed signal table."""
    for token in ("AWLEN", "ARLEN", "HBURST", "PSLVERR", "BRESP", "AWID"):
        assert token not in MODULE_SOURCE


# ===========================================================================
# ID remap -- the layer on top of compute_id_width()
# ===========================================================================

def test_the_fabric_id_width_is_compute_id_widths_own_number_not_a_second_formula():
    rows = [master("CPU_AXI", id_width="4"), master("DMA_AXI", id_width="6")]
    entry = fabric_id_width(rows)
    assert entry["value"]["fabric_id_width"] == compute_id_width(
        [{"id": "CPU_AXI", "id_width": 4}, {"id": "DMA_AXI", "id_width": 6}]) == 7


def test_one_master_with_an_unknown_id_width_blocks_the_whole_fabric_width():
    """Dropping it would compute a narrower W_out from the remaining masters --
    a smaller, confidently-wrong number instead of an honest refusal."""
    entry = fabric_id_width([master("CPU_AXI", id_width="4"),
                             master("DMA_AXI", id_width=BIND_CHECK_UNKNOWN_VALUE)])
    assert entry["status"] == TRANSFORM_REQUIRED_HUMAN_INPUT
    assert "DMA_AXI" in entry["evidence"][0]


def test_no_traced_master_leaves_the_fabric_id_width_undecided():
    assert fabric_id_width([])["status"] == TRANSFORM_REQUIRED_HUMAN_INPUT


def test_an_id_extension_is_reported_with_the_exact_bit_count():
    masters = [master("CPU_AXI", id_width="4"), master("DMA_AXI", id_width="6")]
    entry = detect_id_remap(masters[0], slave(id_width="8"), fabric_id_width(masters))
    assert entry["value"]["kind"] == "EXTENSION"
    assert entry["value"]["extension_bits"] == 3


def test_a_single_master_whose_slave_is_wide_enough_implies_no_remap():
    masters = [master("CPU_AXI", id_width="4")]
    entry = detect_id_remap(masters[0], slave(id_width="4"), fabric_id_width(masters))
    assert entry["status"] == TRANSFORM_NOT_IMPLIED


def test_a_slave_narrower_than_the_fabric_width_implies_a_reissue():
    masters = [master("CPU_AXI", id_width="4")]
    entry = detect_id_remap(masters[0], slave(id_width="2"), fabric_id_width(masters))
    assert entry["value"]["kind"] == "SLAVE_REISSUE"


def test_a_protocol_with_no_transaction_id_has_nothing_to_remap():
    masters = [master("APB_M", protocol="APB4")]
    entry = detect_id_remap(masters[0], slave(protocol="APB4"), fabric_id_width(masters))
    assert entry["status"] == TRANSFORM_NOT_APPLICABLE


def test_a_slave_that_has_an_id_but_no_measured_width_leaves_the_remap_open():
    masters = [master("CPU_AXI", id_width="4")]
    entry = detect_id_remap(masters[0], slave(id_width=BIND_CHECK_UNKNOWN_VALUE),
                            fabric_id_width(masters))
    assert entry["status"] == TRANSFORM_REQUIRED_HUMAN_INPUT
    assert entry["value"]["slave_id_width"] == REQUIRED_HUMAN_INPUT


def test_a_slave_with_no_id_concept_is_not_confused_with_one_nobody_measured():
    masters = [master("CPU_AXI", id_width="4")]
    entry = detect_id_remap(masters[0],
                            slave(protocol="APB4", id_width=BIND_CHECK_UNKNOWN_VALUE),
                            fabric_id_width(masters))
    assert entry["value"]["slave_id_width"] == TRANSFORM_NOT_APPLICABLE


def test_an_undecided_fabric_width_leaves_every_routes_remap_open():
    masters = [master("CPU_AXI", id_width=BIND_CHECK_UNKNOWN_VALUE)]
    entry = detect_id_remap(masters[0], slave(), fabric_id_width(masters))
    assert entry["status"] == TRANSFORM_REQUIRED_HUMAN_INPUT


# ===========================================================================
# Bridge behavior
# ===========================================================================

def test_a_protocol_family_change_is_a_bridge():
    entry = detect_bridge_behavior(master(protocol="AXI4"), slave(protocol="APB4"))
    assert entry["value"]["kind"] == BRIDGE_PROTOCOL_FAMILY


def test_a_sub_protocol_change_inside_one_family_is_still_a_bridge():
    entry = detect_bridge_behavior(master(protocol="AXI4"), slave(protocol="AXI4_LITE"))
    assert entry["value"]["kind"] == BRIDGE_SUB_PROTOCOL


def test_identical_protocols_imply_no_bridge():
    entry = detect_bridge_behavior(master(protocol="AXI4"), slave(protocol="AXI4"))
    assert entry["status"] == TRANSFORM_NOT_IMPLIED


def test_an_unresolved_protocol_cannot_rule_a_bridge_in_or_out():
    entry = detect_bridge_behavior(master(protocol=AMBA_PROTOCOL_UNRESOLVED), slave())
    assert entry["status"] == TRANSFORM_REQUIRED_HUMAN_INPUT


# ===========================================================================
# Expected response
# ===========================================================================

def test_different_response_encodings_imply_a_re_encoding():
    entry = detect_expected_response(master(protocol="AXI4"), slave(protocol="APB4"), [])
    assert entry["value"]["kind"] == "RESPONSE_RE_ENCODING"
    assert entry["value"]["master_response_signals"] != entry["value"]["slave_response_signals"]


def test_one_shared_encoding_settles_the_shape_and_defers_the_value_to_phase_2():
    entry = detect_expected_response(master(protocol="AXI4"), slave(protocol="AXI4"), [])
    assert entry["status"] == TRANSFORM_RUNTIME_PHASE_2


def test_a_declared_decode_error_region_is_cited_in_the_response_expectation():
    entry = detect_expected_response(
        master(), slave(),
        [{"owner": "unmapped_hole", "owner_kind": "DECODE_ERROR"}])
    assert entry["value"]["decode_error_regions_declared"] == ["unmapped_hole"]
    assert any("unmapped_hole" in e for e in entry["evidence"])


def test_a_protocol_pair_with_no_response_channel_is_not_applicable():
    entry = detect_expected_response(master(protocol="AXI4_STREAM"),
                                     slave(protocol="AXI4_STREAM"), [])
    assert entry["status"] == TRANSFORM_NOT_APPLICABLE


# ===========================================================================
# Ordering domain
# ===========================================================================

def test_a_protocol_with_transaction_ids_orders_only_within_an_id():
    entry = detect_ordering_domain(master(protocol="AXI4"), slave())
    assert entry["value"]["domain_key"] == ORDERING_DOMAIN_PER_ROUTE_AND_ID
    assert entry["value"]["route_ordering_expectation"] == ORDERING_OUT_OF_ORDER


def test_the_reorder_window_depth_is_never_derived():
    """A depth is an outstanding-transaction configuration nobody discovered;
    computing a plausible one is the guess SYOSCB-12 forbids."""
    entry = detect_ordering_domain(master(protocol="AXI4"), slave())
    assert entry["value"]["ordering_tolerance_depth"] == REQUIRED_HUMAN_INPUT


def test_a_protocol_with_no_transaction_id_is_strictly_in_order_with_depth_zero():
    entry = detect_ordering_domain(master(protocol="APB4"), slave(protocol="APB4"))
    assert entry["value"]["domain_key"] == ORDERING_DOMAIN_PER_ROUTE
    assert entry["value"]["route_ordering_expectation"] == ORDERING_IN_ORDER
    assert entry["value"]["ordering_tolerance_depth"] == 0


def test_the_ordering_vocabulary_is_the_audits_not_a_second_one():
    """`syoscb_source_audit` already maps IN_ORDER/OUT_OF_ORDER onto the real
    `cl_syoscb_compare_{io,iop,ooo}` classes; a private synonym here would make
    that mapping unreachable."""
    entry = detect_ordering_domain(master(protocol="AXI4"), slave())
    assert entry["value"]["route_ordering_expectation"] in (
        ORDERING_IN_ORDER, ORDERING_OUT_OF_ORDER)


def test_an_unresolved_protocol_leaves_the_ordering_domain_open():
    entry = detect_ordering_domain(master(protocol=AMBA_PROTOCOL_UNRESOLVED), slave())
    assert entry["status"] == TRANSFORM_REQUIRED_HUMAN_INPUT


# ===========================================================================
# predict_routes: the whole pipeline on synthetic rows
# ===========================================================================

def test_every_traced_master_slave_pair_gets_one_complete_prediction(axi_to_apb_rows):
    predictions = predict_routes(axi_to_apb_rows, assume_full_connectivity=True)
    assert len(predictions) == 4
    assert_predictions_complete(predictions)
    for prediction in predictions:
        assert set(prediction["responsibilities"]) == set(ROUTE_RESPONSIBILITIES)


def test_the_axi_to_apb_route_detects_every_transform_at_once(axi_to_apb_rows):
    predictions = predict_routes(axi_to_apb_rows, assume_full_connectivity=True)
    answers = _route(predictions, "CPU_AXI__TO__CFG_APB")["responsibilities"]
    assert answers["width_conversion"]["value"]["direction"] == WIDTH_DOWNSIZE
    assert answers["burst_split_merge"]["value"]["kind"] == BURST_SPLIT_TO_SINGLE_TRANSFERS
    assert answers["bridge_behavior"]["value"]["kind"] == BRIDGE_PROTOCOL_FAMILY
    assert answers["expected_response"]["value"]["kind"] == "RESPONSE_RE_ENCODING"
    assert answers["id_remap"]["value"]["extension_bits"] == 3


def test_the_all_axi_route_reports_the_absence_of_transforms_as_a_finding(axi_to_apb_rows):
    answers = _route(predict_routes(axi_to_apb_rows, assume_full_connectivity=True),
                     "DMA_AXI__TO__DDR_AXI")["responsibilities"]
    assert answers["width_conversion"]["status"] == TRANSFORM_NOT_IMPLIED
    assert answers["bridge_behavior"]["status"] == TRANSFORM_NOT_IMPLIED
    assert answers["burst_split_merge"]["status"] == TRANSFORM_NOT_IMPLIED


def test_address_translation_is_required_human_input_when_nobody_supplied_evidence(
        axi_to_apb_rows):
    """Whether the interconnect presents the slave the full system address or a
    base-relative offset is a fabric CONFIGURATION fact. The address map cannot
    imply it, so the predictor must refuse rather than compute one."""
    predictions = predict_routes(axi_to_apb_rows, assume_full_connectivity=True)
    for prediction in predictions:
        entry = prediction["responsibilities"]["address_translation"]
        assert entry["status"] == TRANSFORM_REQUIRED_HUMAN_INPUT
        assert "address_translation" in prediction["unresolved_responsibilities"]


def test_supplied_address_translation_evidence_is_used_verbatim(axi_to_apb_rows):
    predictions = predict_routes(
        axi_to_apb_rows, assume_full_connectivity=True,
        address_translations=[{
            "master": "soc_top.u_cpu_axi", "slave": "soc_top.u_cfg_apb",
            "kind": "BASE_RELATIVE_OFFSET",
            "detail": "the APB bridge subtracts the window base",
            "evidence": "rtl/soc_apb_bridge.v:214 paddr <= awaddr - BASE"}])
    entry = _answer(predictions, "CPU_AXI__TO__CFG_APB", "address_translation")
    assert entry["status"] == TRANSFORM_PREDICTED_FROM_TOPOLOGY
    assert entry["evidence"] == ["rtl/soc_apb_bridge.v:214 paddr <= awaddr - BASE"]
    # Only the route the evidence names -- not every route on the fabric.
    assert (_answer(predictions, "CPU_AXI__TO__DDR_AXI", "address_translation")["status"]
            == TRANSFORM_REQUIRED_HUMAN_INPUT)


def test_address_decode_reuses_compute_address_regions_and_cites_the_region(
        axi_to_apb_rows):
    predictions = predict_routes(
        axi_to_apb_rows, assume_full_connectivity=True, address_width=32,
        address_map_slaves=[
            {"id": "soc_top.u_ddr_axi", "base_addr": 0, "size": 0x8000_0000},
            {"id": "soc_top.u_cfg_apb", "base_addr": 0x8000_0000, "size": 0x8000_0000}])
    entry = _answer(predictions, "CPU_AXI__TO__CFG_APB", "address_decode")
    assert entry["status"] == TRANSFORM_PREDICTED_FROM_TOPOLOGY
    assert entry["value"]["regions"] == [{"start_addr": "0x80000000",
                                          "end_addr": "0x100000000"}]


def test_a_slave_with_no_address_region_reports_a_decode_gap_not_a_guess(axi_to_apb_rows):
    predictions = predict_routes(axi_to_apb_rows, assume_full_connectivity=True)
    entry = _answer(predictions, "CPU_AXI__TO__DDR_AXI", "address_decode")
    assert entry["status"] == TRANSFORM_REQUIRED_HUMAN_INPUT
    assert "ADDRESS_MAP_EVIDENCE_TYPES" in entry["evidence"][0]


def test_a_waived_pair_is_still_predicted_and_labelled_illegal(axi_to_apb_rows):
    predictions = predict_routes(axi_to_apb_rows, connectivity={
        "soc_top.u_cpu_axi": {"accessible_slaves": ["soc_top.u_ddr_axi",
                                                    "soc_top.u_cfg_apb"]},
        "soc_top.u_dma_axi": {
            "accessible_slaves": ["soc_top.u_ddr_axi"],
            "excluded": [{"slave_id": "soc_top.u_cfg_apb",
                          "waiver_evidence": "rtl/soc_top.v:88 -- DMA has no CFG path"}]},
    })
    entry = _answer(predictions, "DMA_AXI__TO__CFG_APB", "routing_legality")
    assert entry["value"]["pair_status"] == ROUTE_WAIVED
    assert "no CFG path" in entry["value"]["waiver_evidence"]
    assert (_answer(predictions, "CPU_AXI__TO__CFG_APB",
                    "routing_legality")["value"]["pair_status"] == ROUTE_LEGAL)


def test_an_unresolved_pair_still_raises_out_of_build_scoreboard_matrix(axi_to_apb_rows):
    """The predictor does not soften the existing evidence gate: a pair neither
    accessible nor waived is refused upstream, not reported as a route."""
    with pytest.raises(Exception) as excinfo:
        predict_routes(axi_to_apb_rows, connectivity={
            "soc_top.u_cpu_axi": {"accessible_slaves": ["soc_top.u_ddr_axi"]},
            "soc_top.u_dma_axi": {"accessible_slaves": ["soc_top.u_ddr_axi"]}})
    assert "UNRESOLVED_PAIR" in str(excinfo.value)


def test_a_topology_with_no_traced_slave_refuses_rather_than_predicting_nothing():
    """The existing registry's own refusal is inherited, not re-implemented: a
    one-sided topology raises `PortRegistryError` out of
    `project_to_fabric_topology()` before any route is invented."""
    from dv_harness.amba_port_registry import PortRegistryError

    with pytest.raises(PortRegistryError) as excinfo:
        predict_routes([master("CPU_AXI")], assume_full_connectivity=True)
    assert excinfo.value.reason == "AMBA_PORT_REGISTRY_TOPOLOGY_INCOMPLETE"


def test_a_bridge_second_side_row_never_becomes_a_route_endpoint(axi_to_apb_rows):
    """`_rows_by_endpoint()` must mirror `registry_endpoints()`'s exclusions, or
    the predictor would name an endpoint the topology projection does not."""
    rows = axi_to_apb_rows + [
        slave("BRIDGE_FAR", "APB4", amba11_second_side=True,
              endpoint_hierarchy="soc_top.u_bridge_far"),
        slave("FANOUT_PARENT", "AXI4", vip_bind_hierarchy=MULTIPLE_BRANCH_PARENT_BIND,
              endpoint_hierarchy="soc_top.u_fanout_parent"),
    ]
    predictions = predict_routes(rows, assume_full_connectivity=True)
    endpoints = {p["slave_endpoint"] for p in predictions}
    assert "soc_top.u_bridge_far" not in endpoints
    assert "soc_top.u_fanout_parent" not in endpoints
    assert endpoints == set(registry_endpoints(rows)["slaves"])


def test_an_unresolved_endpoint_row_contributes_no_route(axi_to_apb_rows):
    rows = axi_to_apb_rows + [
        slave("BLOCKED", "AXI4", trace_status="TRACE_BLOCKED",
              endpoint_hierarchy=ENDPOINT_HIERARCHY_NOT_ESTABLISHED)]
    predictions = predict_routes(rows, assume_full_connectivity=True)
    assert all("BLOCKED" not in p["route_id"] for p in predictions)


# ===========================================================================
# The guards
# ===========================================================================

def test_assert_predictions_complete_catches_a_dropped_responsibility(axi_to_apb_rows):
    predictions = predict_routes(axi_to_apb_rows, assume_full_connectivity=True)
    predictions[0]["responsibilities"].pop("id_remap")
    with pytest.raises(RouteTransformPredictorError) as excinfo:
        assert_predictions_complete(predictions)
    assert excinfo.value.reason == "ROUTE_PREDICTION_INCOMPLETE"


def test_assert_predictions_complete_catches_an_eleventh_responsibility(axi_to_apb_rows):
    predictions = predict_routes(axi_to_apb_rows, assume_full_connectivity=True)
    predictions[0]["responsibilities"]["qos_arbitration"] = {
        "status": TRANSFORM_NOT_IMPLIED, "value": None, "evidence": ["invented"]}
    with pytest.raises(RouteTransformPredictorError) as excinfo:
        assert_predictions_complete(predictions)
    assert excinfo.value.reason == "ROUTE_PREDICTION_UNKNOWN_RESPONSIBILITY"


def test_a_prediction_with_no_stated_basis_is_refused(axi_to_apb_rows):
    predictions = predict_routes(axi_to_apb_rows, assume_full_connectivity=True)
    predictions[0]["responsibilities"]["bridge_behavior"]["evidence"] = []
    with pytest.raises(RouteTransformPredictorError) as excinfo:
        assert_predictions_complete(predictions)
    assert excinfo.value.reason == "ROUTE_PREDICTION_WITHOUT_EVIDENCE"


def test_a_derived_answer_may_not_outlive_its_own_missing_input(axi_to_apb_rows):
    rows = [master("CPU_AXI", data_width=BIND_CHECK_UNKNOWN_VALUE), slave("DDR_AXI")]
    predictions = predict_routes(rows, assume_full_connectivity=True)
    assert_no_route_guessed(predictions)  # honest to begin with
    predictions[0]["responsibilities"]["burst_split_merge"] = {
        "status": TRANSFORM_PREDICTED_FROM_TOPOLOGY,
        "value": {"kind": BURST_SPLIT, "beat_count_factor": 2},
        "evidence": ["a plausible default nobody derived"]}
    with pytest.raises(RouteTransformPredictorError) as excinfo:
        assert_no_route_guessed(predictions)
    assert excinfo.value.reason == "ROUTE_PREDICTION_DERIVED_FROM_UNKNOWN"


def test_every_derived_responsibility_names_a_real_responsibility_as_its_input():
    for derived, source in DERIVED_RESPONSIBILITY_INPUTS.items():
        assert derived in ROUTE_RESPONSIBILITIES
        assert source in ROUTE_RESPONSIBILITIES
        assert derived != source


# ===========================================================================
# Feeding connectivity.SCOREBOARD_PLAN_FIELDS -- as proposals
# ===========================================================================

def test_the_predictor_extends_the_existing_plan_schema_rather_than_inventing_one():
    assert set(PREDICTOR_INFORMED_PLAN_FIELDS) <= set(SCOREBOARD_PLAN_FIELDS)


def test_proposals_are_never_marked_confirmed(axi_to_apb_rows):
    proposals = propose_scoreboard_plan_fields(
        predict_routes(axi_to_apb_rows, assume_full_connectivity=True))
    assert set(proposals) == set(PREDICTOR_INFORMED_PLAN_FIELDS)
    assert_plan_proposals_are_not_confirmations(proposals)
    assert all(entry["confirmed"] is False for entry in proposals.values())


def test_a_proposal_claiming_confirmation_is_refused(axi_to_apb_rows):
    proposals = propose_scoreboard_plan_fields(
        predict_routes(axi_to_apb_rows, assume_full_connectivity=True))
    proposals["ordering"]["confirmed"] = True
    with pytest.raises(RouteTransformPredictorError) as excinfo:
        assert_plan_proposals_are_not_confirmations(proposals)
    assert excinfo.value.reason == "PREDICTOR_PROPOSAL_CLAIMS_CONFIRMATION"


def test_only_legal_routes_are_proposed_as_endpoint_pairs(axi_to_apb_rows):
    predictions = predict_routes(axi_to_apb_rows, connectivity={
        "soc_top.u_cpu_axi": {"accessible_slaves": ["soc_top.u_ddr_axi",
                                                    "soc_top.u_cfg_apb"]},
        "soc_top.u_dma_axi": {
            "accessible_slaves": ["soc_top.u_ddr_axi"],
            "excluded": [{"slave_id": "soc_top.u_cfg_apb",
                          "waiver_evidence": "rtl/soc_top.v:88"}]},
    })
    pairs = propose_scoreboard_plan_fields(predictions)["endpoint_pairs"]["proposal"]
    assert {"source": "soc_top.u_dma_axi", "sink": "soc_top.u_cfg_apb"} not in pairs
    assert len(pairs) == 3


def test_every_proposed_transform_carries_the_numbers_it_came_from(axi_to_apb_rows):
    proposals = propose_scoreboard_plan_fields(
        predict_routes(axi_to_apb_rows, assume_full_connectivity=True))
    transforms = proposals["transformation_rules"]["proposal"]
    assert transforms, "an AXI-to-APB fabric implies at least one transform"
    for transform in transforms:
        assert transform["basis"], "a proposed transform with no basis is a guess"
        assert transform["route_id"]


def test_an_unresolved_ordering_domain_is_not_proposed():
    rows = [master("MYSTERY", protocol=AMBA_PROTOCOL_UNRESOLVED), slave("DDR_AXI")]
    proposals = propose_scoreboard_plan_fields(
        predict_routes(rows, assume_full_connectivity=True))
    assert proposals["ordering"]["proposal"] == {}


# ===========================================================================
# SYOSCB-13: address map evidence
# ===========================================================================

DECODER = [{"instance": "soc_top.u_ddr_axi", "base": 0x0,
            "evidence": "rtl/soc_decoder.v:41 -- addr[31:31] == 1'b0"},
           {"instance": "soc_top.u_cfg_apb", "base": 0x8000_0000,
            "evidence": "rtl/soc_decoder.v:47 -- addr[31:31] == 1'b1"}]
HISTOGRAM = [{"base": 0x0, "access_count": 128, "source": "command.txt"},
             {"base": 0x8000_0000, "access_count": 12, "source": "sanity/cfg_init.txt"}]


def test_every_syoscb_13_evidence_type_names_a_real_verifier_argument_and_authority():
    from dv_harness import source_authority as sa

    assert len(ADDRESS_MAP_EVIDENCE_TYPES) == 7, "SYOSCB-13 lists seven evidence types"
    for spec in ADDRESS_MAP_EVIDENCE_TYPES:
        assert spec["verifier_argument"] in (
            "decoder_entries", "bfm_access_histogram", "register_doc_entries")
        assert sa.authority_source(spec["authority_source"]) is not None


def test_the_decoder_outranks_every_document_evidence_type():
    """SYOSCB-13's "Prefer direct implementation evidence when sources conflict",
    as a mechanical rank comparison rather than a judgment."""
    from dv_harness import source_authority as sa

    decoder = next(s for s in ADDRESS_MAP_EVIDENCE_TYPES
                   if s["evidence_type"] == "fabric RTL decoder")
    for spec in ADDRESS_MAP_EVIDENCE_TYPES:
        if spec["verifier_argument"] != "register_doc_entries":
            continue
        assert (sa.authority_rank(decoder["authority_source"])
                < sa.authority_rank(spec["authority_source"]))


def test_the_two_evidence_types_with_no_purpose_built_parser_say_so():
    """A naming gap recorded as data, not left for a reader to discover by
    finding no parser."""
    generic = {s["evidence_type"] for s in ADDRESS_MAP_EVIDENCE_TYPES
               if s["ingestion"] == "GENERIC_DOC_SLOT"}
    assert {"fabric generated configuration", "firmware headers"} <= generic


def test_verified_bases_join_onto_traced_slaves(axi_to_apb_rows):
    cross_check = cross_check_address_map_evidence(axi_to_apb_rows, DECODER, HISTOGRAM)
    assert_address_map_does_not_replace_topology(cross_check, axi_to_apb_rows)
    assert all(s["status"] == ADDRESS_EVIDENCE_CORROBORATES
               for s in cross_check["per_slave"])
    assert cross_check["slaves_without_address_evidence"] == []


def test_a_traced_slave_with_no_address_evidence_is_a_named_gap(axi_to_apb_rows):
    cross_check = cross_check_address_map_evidence(
        axi_to_apb_rows, DECODER[:1], HISTOGRAM)
    assert cross_check["slaves_without_address_evidence"] == ["soc_top.u_cfg_apb"]
    missing = next(s for s in cross_check["per_slave"]
                   if s["slave_endpoint"] == "soc_top.u_cfg_apb")
    assert missing["status"] == ADDRESS_EVIDENCE_MISSING


def test_an_address_map_instance_naming_no_traced_endpoint_never_becomes_a_slave(
        axi_to_apb_rows):
    """SYOSCB-13: address-map evidence supports but does not replace topology
    evidence. The unjoined instance is reported, and the slave list is
    unchanged."""
    decoder = DECODER + [{"instance": "soc_top.u_rom", "base": 0x4000_0000,
                          "evidence": "rtl/soc_decoder.v:53"}]
    histogram = HISTOGRAM + [{"base": 0x4000_0000, "access_count": 3,
                              "source": "command.txt"}]
    cross_check = cross_check_address_map_evidence(axi_to_apb_rows, decoder, histogram)
    assert_address_map_does_not_replace_topology(cross_check, axi_to_apb_rows)
    assert [u["instance"] for u in cross_check["unjoined_address_evidence"]] == [
        "soc_top.u_rom"]
    assert cross_check["unjoined_address_evidence"][0]["status"] == ADDRESS_EVIDENCE_UNJOINED
    assert "soc_top.u_rom" not in cross_check["traced_slaves"]


def test_the_topology_guard_fires_if_the_slave_list_was_altered(axi_to_apb_rows):
    cross_check = cross_check_address_map_evidence(axi_to_apb_rows, DECODER, HISTOGRAM)
    cross_check["traced_slaves"].append("soc_top.u_rom")
    with pytest.raises(RouteTransformPredictorError) as excinfo:
        assert_address_map_does_not_replace_topology(cross_check, axi_to_apb_rows)
    assert excinfo.value.reason == "ADDRESS_MAP_ALTERED_TOPOLOGY"


def test_an_instance_naming_map_joins_a_decoder_name_to_a_traced_endpoint(
        axi_to_apb_rows):
    decoder = [{"instance": "DDR", "base": 0x0, "evidence": "rtl/soc_decoder.v:41"}]
    cross_check = cross_check_address_map_evidence(
        axi_to_apb_rows, decoder, HISTOGRAM,
        endpoint_of_instance={"DDR": "soc_top.u_ddr_axi"})
    assert cross_check["unjoined_address_evidence"] == []
    ddr = next(s for s in cross_check["per_slave"]
               if s["slave_endpoint"] == "soc_top.u_ddr_axi")
    assert ddr["status"] == ADDRESS_EVIDENCE_CORROBORATES


def test_the_three_source_method_is_reused_whole_not_softened(axi_to_apb_rows):
    """A decoder base no BFM pattern exercises is still refused -- the
    cross-check adds a join on top of `verify_address_map()`, it does not
    weaken it."""
    with pytest.raises(AddressMapVerificationError) as excinfo:
        cross_check_address_map_evidence(axi_to_apb_rows, DECODER, HISTOGRAM[:1])
    assert excinfo.value.reason == "ZERO_ACCESS_HISTOGRAM"


def test_a_document_disagreement_is_recorded_and_resolved_toward_the_decoder(
        axi_to_apb_rows):
    cross_check = cross_check_address_map_evidence(
        axi_to_apb_rows, DECODER, HISTOGRAM,
        register_doc_entries=[{"instance": "soc_top.u_cfg_apb", "base": 0x9000_0000,
                               "doc_ref": "docs/soc_regmap.pdf p.12"}])
    conflicts = address_map_conflicts(cross_check)
    assert len(conflicts) == 1
    assert conflicts[0]["instance"] == "soc_top.u_cfg_apb"
    # The decoder wins, by the harness's own 9-level authority order.
    assert "dut_rtl" in str(conflicts[0]["resolution"])
    # ...and the verified base is still the decoder's, not the document's.
    assert conflicts[0]["base_hex"] == hex(0x8000_0000)


def test_no_disagreement_means_no_fabricated_conflict(axi_to_apb_rows):
    cross_check = cross_check_address_map_evidence(
        axi_to_apb_rows, DECODER, HISTOGRAM,
        register_doc_entries=[{"instance": "soc_top.u_cfg_apb", "base": 0x8000_0000,
                               "doc_ref": "docs/soc_regmap.pdf p.12"}])
    assert address_map_conflicts(cross_check) == []


# ===========================================================================
# The real parsed fixture
# ===========================================================================

@requires_verible
def test_the_real_fabric_produces_one_route_per_traced_pair(real_registry,
                                                            real_predictions):
    endpoints = registry_endpoints(real_registry)
    assert len(real_predictions) == len(endpoints["masters"]) * len(endpoints["slaves"])
    assert_predictions_complete(real_predictions)
    assert_no_route_guessed(real_predictions)


@requires_verible
def test_the_real_fabrics_unmeasured_ddr_width_is_reported_not_defaulted(
        real_predictions):
    """`u_ddr`'s AMBA-15 checklist genuinely never established a data_width. The
    predictor must say so -- on the width AND on the burst expectation derived
    from it -- rather than assuming the widths match."""
    ddr = next(p for p in real_predictions if p["slave_endpoint"] == "u_ddr")
    assert ddr["responsibilities"]["width_conversion"]["status"] == \
        TRANSFORM_REQUIRED_HUMAN_INPUT
    assert ddr["responsibilities"]["burst_split_merge"]["status"] == \
        TRANSFORM_REQUIRED_HUMAN_INPUT
    assert "width_conversion" in ddr["unresolved_responsibilities"]
    assert "burst_split_merge" in ddr["unresolved_responsibilities"]


@requires_verible
def test_the_real_fabrics_matched_sram_route_is_decided(real_predictions):
    sram = next(p for p in real_predictions if p["slave_endpoint"] == "u_sram0")
    assert sram["responsibilities"]["width_conversion"]["status"] == TRANSFORM_NOT_IMPLIED
    assert sram["responsibilities"]["id_remap"]["status"] == \
        TRANSFORM_PREDICTED_FROM_TOPOLOGY
    assert sram["responsibilities"]["id_remap"]["value"]["extension_bits"] == 1


@requires_verible
def test_no_unresolved_or_bridge_far_side_port_became_a_real_route(real_registry,
                                                                   real_predictions):
    endpoints = registry_endpoints(real_registry)
    assert {p["slave_endpoint"] for p in real_predictions} == set(endpoints["slaves"])
    assert {p["master_endpoint"] for p in real_predictions} == set(endpoints["masters"])


# ===========================================================================
# Phase-1 boundary (SYOSCB-33 / SYOSCB-34)
# ===========================================================================

def test_the_rendered_report_is_neither_emittable_sv_nor_a_bind(axi_to_apb_rows):
    predictions = predict_routes(axi_to_apb_rows, assume_full_connectivity=True)
    cross_check = cross_check_address_map_evidence(axi_to_apb_rows, DECODER, HISTOGRAM)
    text = render_route_transform_report(predictions, cross_check)
    assert_no_emittable_sv(text, label="test-rendered SYOSCB-12/13 report")
    assert_no_bind_statement(text)
    assert "SYOSCB-33" in text
    assert "u_rom" not in text


def test_the_report_names_every_route_and_its_open_questions(axi_to_apb_rows):
    predictions = predict_routes(axi_to_apb_rows, assume_full_connectivity=True)
    text = render_route_transform_report(predictions)
    for prediction in predictions:
        assert prediction["route_id"] in text
    assert "address_translation" in text
    for responsibility in ROUTE_RESPONSIBILITIES:
        assert responsibility in text


def test_the_module_itself_contains_no_emittable_systemverilog():
    assert_no_emittable_sv(MODULE_SOURCE, label="amba_route_transform_predictor.py")
    assert_no_bind_statement(MODULE_SOURCE)


def test_nothing_was_vendored_out_of_the_read_only_syoscb_source():
    """SYOSCB-2 is a Phase-2 item: this module cites the upstream library's
    behavior through `syoscb_source_audit`, and copies no path out of it."""
    assert "D:/DV/Scoreboard" not in MODULE_SOURCE
    assert "uvm_syoscb-1.0.2.4" not in MODULE_SOURCE
