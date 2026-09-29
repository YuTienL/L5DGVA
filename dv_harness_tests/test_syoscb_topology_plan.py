"""Tests for SYOSCB-14 (multi-master/multi-slave scoreboard model), SYOSCB-15
(master -> producer mapping) and SYOSCB-16 (destination / ordering domain ->
queue mapping) -- `dv_harness/syoscb_topology_plan.py`.

Three kinds of fixture, for the same reasons `test_amba_route_transform_
predictor.py` uses two:

  * SYNTHETIC AMBA_PORT_REGISTRY rows, reusing that module's own `master()` /
    `slave()` helpers so a row here has exactly the columns a real one does.
    These carry the topologies the real fixture cannot produce -- three
    masters into one destination, two id-less APB masters into one slave, an
    unresolved protocol, a waived route.
  * The REAL parsed AMBA4 SoC fixture, carried through a real
    `build_amba_port_registry()` and `predict_routes()` into a real plan.
  * The REAL upstream uvm_syoscb-1.0.2.4 tree at D:/DV/Scoreboard, read
    READ-ONLY, to hold every cited API signature against the source it claims
    to come from. Nothing is copied out of it; `test_the_module_carries_no_
    upstream_source_body` checks that from the other direction.

Every mapping is tested on BOTH sides -- what it decides, and what it refuses
to decide when the evidence is missing. A planner tested only where the answer
exists is the happy-path-only coverage this project has been burned by.
"""
from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest

from dv_harness import syoscb_topology_plan as stp
from dv_harness.amba_fabric_discovery import (
    assert_no_bind_statement,
    build_fabric_netlist,
    build_vip_bind_plan,
    trace_all_fabric_ports,
)
from dv_harness.amba_port_registry import build_amba_port_registry
from dv_harness.amba_route_transform_predictor import (
    ORDERING_DOMAIN_PER_ROUTE,
    ORDERING_DOMAIN_PER_ROUTE_AND_ID,
    ROUTE_LEGAL,
    ROUTE_WAIVED,
    TRANSFORM_PREDICTED_FROM_TOPOLOGY,
    predict_routes,
)
from dv_harness.connectivity import AMBA_PROTOCOL_UNRESOLVED, REQUIRED_HUMAN_INPUT
from dv_harness.syoscb_source_audit import assert_no_emittable_sv, audit_syoscb_source
from dv_harness.syoscb_topology_plan import (
    ATTRIBUTION_BY_FABRIC_ID,
    ATTRIBUTION_SINGLE_MASTER,
    COMPARE_STRATEGY_DEFERRED,
    EXCLUDED_ORDERING_DOMAIN_UNRESOLVED,
    EXCLUDED_ROUTE_WAIVED,
    GROUPING_BY_DESTINATION_CLASS,
    GROUPING_BY_TRACED_DESTINATION,
    ORDERING_DOMAIN_KEYS,
    PRODUCER_NAME_SOURCE_COLUMN,
    QUEUE_SIDE_MASTER,
    QUEUE_SIDE_SLAVE,
    ROUTE_STATUS_VALUES,
    SYOSIL_CFG_API,
    SyoscbTopologyPlanError,
    assert_cited_syosil_api_matches_source,
    assert_every_producer_queue_is_declared,
    assert_names_are_legal_syosil_identifiers,
    assert_not_one_scoreboard_per_route,
    assert_producer_names_derive_from_registry,
    assert_producer_queue_lists_have_no_duplicates,
    assert_queues_are_not_per_physical_port,
    build_syoscb_configuration_plan,
    destination_class_of,
    group_routes_into_scoreboards,
    render_syoscb_configuration_plan_report,
    syosil_configuration_calls,
    unresolved_plan_questions,
    verify_cited_syosil_api,
)
from dv_harness.verible_parser import parse_file
from dv_harness_tests.test_amba_route_transform_predictor import master, slave
from dv_harness_tests.test_amba_vip_bind_plan import FABRIC, write_fixture

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)

REAL_SYOSCB_ROOT = Path("D:/DV/Scoreboard/uvm_syoscb-1.0.2.4")
real_source = pytest.mark.skipif(
    not REAL_SYOSCB_ROOT.is_dir(),
    reason=f"the real uvm_syoscb source tree is not present at {REAL_SYOSCB_ROOT}",
)

MODULE_SOURCE = Path(stp.__file__).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Synthetic topologies
# ---------------------------------------------------------------------------

def plan_from(rows, **kwargs):
    """Registry rows -> real predictions -> a real plan, with no step faked.

    `assume_full_connectivity=True` is the predictor's own opt-in bulk
    declaration; a test that wants a WAIVED route passes real `connectivity`
    evidence instead."""
    destination_classes = kwargs.pop("destination_classes", None)
    predictions = predict_routes(rows, **{"assume_full_connectivity": True, **kwargs})
    return build_syoscb_configuration_plan(
        rows, predictions, destination_classes=destination_classes)


@pytest.fixture
def three_masters_one_ddr():
    """The shape SYOSCB-14 is about: three AXI4 masters, one AXI4 destination.
    Naively three scoreboards; correctly one."""
    return [
        master("CPU_AXI", "AXI4"),
        master("DMA_AXI", "AXI4", id_width="6"),
        master("GPU_AXI", "AXI4", id_width="5"),
        slave("DDR_AXI", "AXI4", id_width="8"),
    ]


@pytest.fixture
def two_apb_masters_one_slave():
    """Two APB4 masters into one APB4 slave. APB carries no transaction id, so
    an item observed at the destination cannot say which master sent it -- the
    genuinely-undecidable attribution case."""
    return [
        master("HOST_APB", "APB4", data_width="32", id_width="UNKNOWN"),
        master("DEBUG_APB", "APB4", data_width="32", id_width="UNKNOWN"),
        slave("CFG_APB", "APB4", data_width="32", id_width="UNKNOWN"),
    ]


@pytest.fixture
def ddr_and_sram():
    """One master, two AXI4 destinations -- the fixture the destination-class
    grouping decision is visible on."""
    return [
        master("CPU_AXI", "AXI4"),
        slave("DDR_AXI", "AXI4", id_width="8"),
        slave("SRAM_AXI", "AXI4", id_width="8"),
    ]


def _group(plan, scoreboard_id):
    return next(g for g in plan["scoreboards"] if g["scoreboard_id"] == scoreboard_id)


def _producer(plan, name):
    return next(p for p in plan["producers"] if p["producer_name"] == name)


# ===========================================================================
# SYOSCB-15's own instruction: verify the API from source, do not assume it
# ===========================================================================

@real_source
def test_every_cited_syosil_api_signature_matches_the_real_source():
    """SYOSCB-15's own instruction: verify exact SyoSil producer semantics and
    API from source before generation; do not hardcode API calls from
    assumptions."""
    audit = audit_syoscb_source(REAL_SYOSCB_ROOT)
    rows = verify_cited_syosil_api(audit)
    assert rows, "SYOSIL_CFG_API must cite at least the producer/queue API"
    assert [r["status"] for r in rows] == ["MATCHES"] * len(rows), [
        (r["api_id"], r["status"], r["observed"]) for r in rows if r["status"] != "MATCHES"]
    assert_cited_syosil_api_matches_source(audit)


@real_source
def test_the_cited_producer_api_really_takes_a_bare_string_and_a_queue_list():
    """The whole SYOSCB-15 mapping rests on a producer being a NAME, not a
    typed master object. That is a fact about the source, so it is asserted
    against the source rather than described in a comment."""
    audit = audit_syoscb_source(REAL_SYOSCB_ROOT)
    cfg = audit.class_named("cl_syoscb_cfg")
    setter = next(m for m in cfg["api"] if m["name"] == "set_producer")
    assert setter["arguments"] == "(string producer, queue_names[])"
    assert setter["return_type"] == "bit"
    pl = audit.class_named("cl_syoscb_cfg_pl")
    assert [m["arguments"] for m in pl["api"] if m["name"] == "set_list"] == ["(string list[])"]


def test_a_drifted_api_citation_is_refused_rather_than_planned_around():
    """The negative half: an upstream tree whose `set_producer` moved must fail
    loudly, not quietly plan a call against a signature that is not there."""

    class _Audit:
        root = "synthetic"

        @staticmethod
        def class_named(name):
            if name != "cl_syoscb_cfg":
                return None
            return {"name": name, "api": [
                {"name": "set_producer", "arguments": "(string producer)",
                 "file": "src/cl_syoscb_cfg.svh", "line": 999}]}

    rows = verify_cited_syosil_api(_Audit())
    statuses = {r["api_id"]: r["status"] for r in rows}
    assert statuses["cl_syoscb_cfg::set_producer"] == "SIGNATURE_DRIFTED"
    assert statuses["cl_syoscb_cfg::set_queues"] == "METHOD_NOT_FOUND"
    assert statuses["cl_syoscb::add_item"] == "CLASS_NOT_FOUND"
    with pytest.raises(SyoscbTopologyPlanError) as exc:
        assert_cited_syosil_api_matches_source(_Audit())
    assert exc.value.reason == "SYOSIL_CITED_API_DOES_NOT_MATCH_SOURCE"


def test_the_module_carries_no_upstream_source_body():
    """SYOSCB-2 / SYOSCB-33: this module cites the upstream tree, it does not
    absorb it. A copied method body would be vendoring by another name."""
    for token in ("endfunction", "endclass", "`uvm_info", "`uvm_fatal", "this.producers["):
        assert token not in MODULE_SOURCE, f"upstream source body leaked into the module: {token}"


# ===========================================================================
# SYOSCB-14: the plan collapses, it does not multiply
# ===========================================================================

def test_three_masters_into_one_destination_are_one_scoreboard_and_two_queues(
        three_masters_one_ddr):
    """SYOSCB-14's "4 Masters x 8 Slaves = 32 independent scoreboard
    instances" anti-pattern, at the smallest size that can show it."""
    plan = plan_from(three_masters_one_ddr)
    assert plan["scaling"]["legal_route_count"] == 3
    assert plan["scaling"]["naive_one_scoreboard_per_route_count"] == 3
    assert plan["scaling"]["planned_scoreboard_count"] == 1
    assert plan["scaling"]["planned_queue_count"] == 2
    assert len(plan["producers"]) == 3
    group = plan["scoreboards"][0]
    assert sorted(group["route_ids"]) == sorted(
        p["route_id"] for p in predict_routes(three_masters_one_ddr,
                                              assume_full_connectivity=True))


def test_the_planned_counts_are_derived_from_discovery_not_from_a_constant(
        three_masters_one_ddr):
    """Adding a fourth master must change the producer count and nothing
    else -- that is what "scales with discovered fabric topology" means."""
    smaller = plan_from(three_masters_one_ddr)
    bigger = plan_from(three_masters_one_ddr + [master("NPU_AXI", "AXI4", id_width="3")])
    assert bigger["scaling"]["legal_route_count"] == 4
    assert len(bigger["producers"]) == len(smaller["producers"]) + 1
    assert (bigger["scaling"]["planned_scoreboard_count"]
            == smaller["scaling"]["planned_scoreboard_count"] == 1)
    assert (bigger["scaling"]["planned_queue_count"]
            == smaller["scaling"]["planned_queue_count"] == 2)


def test_the_subscriber_count_is_the_upstream_build_phase_loops_own_arithmetic(
        three_masters_one_ddr):
    """`build_phase` creates one subscriber per (producer, queue-in-its-list)
    pair, so the plan's predicted component count is that loop, not an
    estimate."""
    plan = plan_from(three_masters_one_ddr)
    assert plan["scaling"]["planned_subscriber_count"] == sum(
        len(p["queue_names"]) for p in plan["producers"]) == 6
    assert "src/cl_syoscb.svh:114-125" in plan["scaling"]["subscriber_count_basis"]


def test_a_destination_class_groups_two_traced_destinations_into_one_scoreboard(
        ddr_and_sram):
    """SYOSCB-16's "queue may represent a peripheral group / destination
    class": with the class supplied, two destinations share one queue pair."""
    plan = plan_from(ddr_and_sram,
                     destination_classes={"soc_top.u_ddr_axi": "MEMORY",
                                          "soc_top.u_sram_axi": "MEMORY"})
    assert plan["scaling"]["legal_route_count"] == 2
    assert plan["scaling"]["planned_scoreboard_count"] == 1
    assert plan["scaling"]["planned_queue_count"] == 2
    group = plan["scoreboards"][0]
    assert group["destination_class"] == "MEMORY"
    assert group["grouping_basis"] == GROUPING_BY_DESTINATION_CLASS
    assert sorted(group["slave_endpoints"]) == ["soc_top.u_ddr_axi", "soc_top.u_sram_axi"]


def test_the_destination_class_can_be_supplied_by_registry_port_id_too(ddr_and_sram):
    """A caller has only two identifiers for a destination -- the traced
    hierarchy and the registry port_id -- so both must key the supplied map."""
    entry = destination_class_of(
        {"slave_endpoint": "soc_top.u_ddr_axi", "slave_port_id": "DDR_AXI"},
        {"DDR_AXI": "memory"})
    assert entry["destination_class"] == "MEMORY"
    assert entry["grouping_basis"] == GROUPING_BY_DESTINATION_CLASS


# ===========================================================================
# SYOSCB-16: the fallback is reported as a fallback
# ===========================================================================

def test_no_supplied_destination_class_is_a_reported_fallback_not_a_decision(ddr_and_sram):
    """"Do not blindly create one queue per physical port" is a rule about not
    defaulting. Grouping per traced destination is what this module CAN do
    from discovery alone -- so it does it, and says so."""
    plan = plan_from(ddr_and_sram)
    assert plan["scaling"]["planned_scoreboard_count"] == 2
    assert {g["grouping_basis"] for g in plan["scoreboards"]} == {
        GROUPING_BY_TRACED_DESTINATION}
    questions = [q for q in unresolved_plan_questions(plan)
                 if q["question"] == "DESTINATION_CLASS_NOT_SUPPLIED"]
    assert len(questions) == 2
    assert any("do not blindly create one queue per physical port" in e.lower()
               for q in questions for e in q["evidence"])


def test_a_supplied_destination_class_raises_no_fallback_question(ddr_and_sram):
    plan = plan_from(ddr_and_sram,
                     destination_classes={"soc_top.u_ddr_axi": "MEMORY",
                                          "soc_top.u_sram_axi": "MEMORY"})
    assert not [q for q in unresolved_plan_questions(plan)
                if q["question"] == "DESTINATION_CLASS_NOT_SUPPLIED"]


def test_two_ordering_domains_on_one_destination_class_stay_two_scoreboards():
    """A queue key is (destination class, ordering domain). An AXI master and
    an APB master reaching one supplied class do NOT share a queue -- their
    transactions are compared under different ordering semantics."""
    rows = [master("CPU_AXI", "AXI4"),
            master("HOST_APB", "APB4", data_width="32", id_width="UNKNOWN"),
            slave("DDR_AXI", "AXI4", id_width="8"),
            slave("CFG_APB", "APB4", data_width="32", id_width="UNKNOWN")]
    plan = plan_from(rows, destination_classes={"soc_top.u_ddr_axi": "FABRIC_SINK",
                                                "soc_top.u_cfg_apb": "FABRIC_SINK"})
    domains = {g["ordering_domain_key"] for g in plan["scoreboards"]}
    assert domains == {ORDERING_DOMAIN_PER_ROUTE, ORDERING_DOMAIN_PER_ROUTE_AND_ID}
    assert {g["destination_class"] for g in plan["scoreboards"]} == {"FABRIC_SINK"}
    assert plan["scaling"]["planned_scoreboard_count"] == 2


# ===========================================================================
# SYOSCB-15: producers
# ===========================================================================

def test_producer_names_come_from_the_registry_port_id_never_a_counter(
        three_masters_one_ddr):
    plan = plan_from(three_masters_one_ddr)
    assert sorted(p["producer_name"] for p in plan["producers"]) == [
        "CPU_AXI", "DMA_AXI", "GPU_AXI"]
    for producer in plan["producers"]:
        assert producer["derived_from"] == (
            f"AMBA_PORT_REGISTRY {producer['producer_name']}.{PRODUCER_NAME_SOURCE_COLUMN}")
        assert producer["registry_row_id"] == producer["producer_name"].lower()
    assert_producer_names_derive_from_registry(plan, three_masters_one_ddr)


def test_a_producer_no_registry_row_backs_is_refused(three_masters_one_ddr):
    plan = plan_from(three_masters_one_ddr)
    doctored = copy.deepcopy(plan)
    doctored["producers"][0]["producer_name"] = "master0"
    with pytest.raises(SyoscbTopologyPlanError) as exc:
        assert_producer_names_derive_from_registry(doctored, three_masters_one_ddr)
    assert exc.value.reason == "SYOSCB_PLAN_PRODUCER_NOT_IN_PORT_REGISTRY"
    assert exc.value.detail["producers"] == ["master0"]


def test_each_producer_feeds_both_queues_when_the_fabric_id_identifies_it(
        three_masters_one_ddr):
    """Three AXI4 masters with predicted fabric ids: a slave-side item CAN be
    attributed, so every producer is registered on both queues."""
    plan = plan_from(three_masters_one_ddr)
    group = plan["scoreboards"][0]
    assert group["slave_side_producer_attribution"]["status"] == ATTRIBUTION_BY_FABRIC_ID
    for producer in plan["producers"]:
        assert sorted(producer["queue_names"]) == sorted(
            [f"{group['scoreboard_id']}_{QUEUE_SIDE_MASTER}",
             f"{group['scoreboard_id']}_{QUEUE_SIDE_SLAVE}"])
        assert producer["withheld_queues"] == []


def test_a_single_master_route_is_attributable_without_any_id(ddr_and_sram):
    """Attribution needs an id only when more than one master could have sent
    the item. One master into a destination is unambiguous by construction."""
    plan = plan_from(ddr_and_sram)
    for group in plan["scoreboards"]:
        assert group["slave_side_producer_attribution"]["status"] == ATTRIBUTION_SINGLE_MASTER


# ===========================================================================
# The missing-evidence paths
# ===========================================================================

def test_two_id_less_masters_into_one_slave_block_the_group_instead_of_guessing(
        two_apb_masters_one_slave):
    """The honest refusal: APB carries no transaction id, so a slave-side
    monitor cannot name the master that sent an item, and
    `cl_syoscb_compare_iop` matches only on equal producers. The plan reports
    the question rather than registering an attribution nothing established."""
    plan = plan_from(two_apb_masters_one_slave)
    group = plan["scoreboards"][0]
    attribution = group["slave_side_producer_attribution"]
    assert attribution["status"] == REQUIRED_HUMAN_INPUT
    assert any("cl_syoscb_compare_iop.svh:119" in e for e in attribution["evidence"])
    assert plan["scoreboards_blocked_on_producer_attribution"] == [group["scoreboard_id"]]

    slave_queue = f"{group['scoreboard_id']}_{QUEUE_SIDE_SLAVE}"
    for producer in plan["producers"]:
        assert producer["queue_names"] == [f"{group['scoreboard_id']}_{QUEUE_SIDE_MASTER}"]
        assert [w["queue_name"] for w in producer["withheld_queues"]] == [slave_queue]

    assert any(q["question"] == "SLAVE_SIDE_PRODUCER_ATTRIBUTION"
               for q in unresolved_plan_questions(plan))


def test_a_blocked_group_proposes_no_configuration_call(two_apb_masters_one_slave):
    """A group with no slave-side producer has no configuration a Phase-2
    implementer could write; emitting one would hand them a scoreboard that
    silently compares nothing."""
    plan = plan_from(two_apb_masters_one_slave)
    assert syosil_configuration_calls(plan) == []
    report = render_syoscb_configuration_plan_report(plan)
    assert "every planned scoreboard is blocked on an open question" in report


def test_an_unresolved_protocol_excludes_the_route_with_a_reason_not_silently():
    """The ordering domain is undecidable when the protocol never resolved, and
    a queue keyed on an undecided ordering domain would be a guess. The route
    is excluded, named, and carried into the open questions."""
    rows = [master("CPU_AXI", "AXI4"),
            master("MYSTERY_PORT", AMBA_PROTOCOL_UNRESOLVED),
            slave("DDR_AXI", "AXI4", id_width="8")]
    plan = plan_from(rows)
    excluded = plan["excluded_routes"]
    assert [r["excluded"] for r in excluded] == [EXCLUDED_ORDERING_DOMAIN_UNRESOLVED]
    assert excluded[0]["master_port_id"] == "MYSTERY_PORT"
    assert excluded[0]["ordering_domain_key"] == REQUIRED_HUMAN_INPUT
    assert excluded[0]["excluded_evidence"], "an exclusion must state what it was decided from"
    assert plan["scaling"]["legal_route_count"] == 1
    assert "MYSTERY_PORT" not in {p["producer_name"] for p in plan["producers"]}
    assert any(q["question"] == EXCLUDED_ORDERING_DOMAIN_UNRESOLVED
               for q in unresolved_plan_questions(plan))


def test_a_waived_route_carries_no_queue_but_is_still_reported():
    """An illegal route must not get scoreboard structure -- traffic on it is a
    finding, not a transaction to match -- and must not vanish either."""
    rows = [master("CPU_AXI", "AXI4"),
            slave("DDR_AXI", "AXI4", id_width="8"),
            slave("SECURE_AXI", "AXI4", id_width="8")]
    connectivity = {"soc_top.u_cpu_axi": {
        "accessible_slaves": ["soc_top.u_ddr_axi"],
        "excluded": [{"slave_id": "soc_top.u_secure_axi",
                      "waiver_evidence": "the CPU has no path to the secure island"}]}}
    plan = plan_from(rows, assume_full_connectivity=False, connectivity=connectivity)
    assert [r["excluded"] for r in plan["excluded_routes"]] == [EXCLUDED_ROUTE_WAIVED]
    assert plan["scaling"]["planned_scoreboard_count"] == 1
    assert all("SECURE" not in q["queue_name"] for q in plan["queues"])
    assert any(q["question"] == EXCLUDED_ROUTE_WAIVED for q in unresolved_plan_questions(plan))


def test_the_ordering_tolerance_depth_stays_an_open_question_on_an_out_of_order_route(
        three_masters_one_ddr):
    """SYOSCB-12 reports the reorder-window depth as REQUIRED_HUMAN_INPUT; a
    planner that filled it in here would be answering on the predictor's
    behalf."""
    plan = plan_from(three_masters_one_ddr)
    group = plan["scoreboards"][0]
    assert group["ordering_domain_key"] == ORDERING_DOMAIN_PER_ROUTE_AND_ID
    assert group["ordering_tolerance_depth"] == REQUIRED_HUMAN_INPUT
    assert any(q["question"] == "ORDERING_TOLERANCE_DEPTH"
               for q in unresolved_plan_questions(plan))


def test_an_in_order_route_carries_a_real_depth_of_zero(two_apb_masters_one_slave):
    """The other side of the same coin: APB really is strictly ordered, so the
    depth is a derived 0 and not an open question."""
    plan = plan_from(two_apb_masters_one_slave)
    group = plan["scoreboards"][0]
    assert group["ordering_domain_key"] == ORDERING_DOMAIN_PER_ROUTE
    assert group["ordering_tolerance_depth"] == 0
    assert not [q for q in unresolved_plan_questions(plan)
                if q["question"] == "ORDERING_TOLERANCE_DEPTH"]


# ===========================================================================
# SYOSCB-17 is not decided here
# ===========================================================================

def test_the_compare_algorithm_is_deferred_on_every_group(three_masters_one_ddr,
                                                          two_apb_masters_one_slave):
    """The ordering DOMAIN is the key items are grouped by; the compare
    ALGORITHM is what runs inside a group. Deriving the second from the first
    is how an out-of-order route silently gets an in-order comparison."""
    for rows in (three_masters_one_ddr, two_apb_masters_one_slave):
        plan = plan_from(rows)
        assert {g["compare_strategy"] for g in plan["scoreboards"]} == {
            COMPARE_STRATEGY_DEFERRED}
        assert all(q["question"] == "COMPARE_STRATEGY"
                   for q in unresolved_plan_questions(plan)
                   if q["question"] == "COMPARE_STRATEGY")
    assert "cl_syoscb_compare_io" not in str(
        [g["compare_strategy"] for g in plan["scoreboards"]])


# ===========================================================================
# The assertions have real detection power
# ===========================================================================

def test_a_fragmented_queue_key_is_refused(three_masters_one_ddr):
    """The per-physical-port shape, reached the only way it can be: a plan
    whose groups split routes that share a key."""
    plan = plan_from(three_masters_one_ddr)
    doctored = copy.deepcopy(plan)
    group = doctored["scoreboards"][0]
    moved = group["route_ids"].pop()
    doctored["scoreboards"].append({**copy.deepcopy(group),
                                    "scoreboard_id": "SB_DDR_AXI__SPLIT",
                                    "route_ids": [moved]})
    with pytest.raises(SyoscbTopologyPlanError) as exc:
        assert_queues_are_not_per_physical_port(doctored)
    assert exc.value.reason == "SYOSCB_PLAN_QUEUE_KEY_FRAGMENTED"
    assert exc.value.detail["route_id"] == moved


def test_one_scoreboard_per_route_is_refused_when_the_routes_share_a_key(
        three_masters_one_ddr):
    plan = plan_from(three_masters_one_ddr)
    doctored = copy.deepcopy(plan)
    doctored["scaling"]["planned_scoreboard_count"] = 3
    with pytest.raises(SyoscbTopologyPlanError) as exc:
        assert_not_one_scoreboard_per_route(doctored)
    assert exc.value.reason == "SYOSCB_PLAN_ONE_SCOREBOARD_PER_ROUTE"


def test_one_scoreboard_per_route_is_legal_when_every_route_has_its_own_key(ddr_and_sram):
    """The rule is "unless the architecture truly requires it" -- two
    destinations with one master each really are two scoreboards."""
    plan = plan_from(ddr_and_sram)
    assert (plan["scaling"]["planned_scoreboard_count"]
            == plan["scaling"]["legal_route_count"] == 2)
    assert_not_one_scoreboard_per_route(plan)


def test_an_undeclared_producer_queue_is_refused_before_phase_2_finds_out(
        three_masters_one_ddr):
    """`set_producer()` returns 1'b0 for an unknown queue name, silently, at
    src/cl_syoscb_cfg.svh:163-166. Catching it here is the whole point of
    citing the API."""
    doctored = copy.deepcopy(plan_from(three_masters_one_ddr))
    doctored["producers"][0]["queue_names"].append("SB_QUEUE_THAT_WAS_NEVER_DECLARED")
    with pytest.raises(SyoscbTopologyPlanError) as exc:
        assert_every_producer_queue_is_declared(doctored)
    assert exc.value.reason == "SYOSCB_PLAN_PRODUCER_QUEUE_NOT_DECLARED"
    assert "163-166" in exc.value.detail["citation"]


def test_a_duplicated_producer_queue_is_refused(three_masters_one_ddr):
    doctored = copy.deepcopy(plan_from(three_masters_one_ddr))
    doctored["producers"][0]["queue_names"] *= 2
    with pytest.raises(SyoscbTopologyPlanError) as exc:
        assert_producer_queue_lists_have_no_duplicates(doctored)
    assert exc.value.reason == "SYOSCB_PLAN_PRODUCER_QUEUE_DUPLICATED"
    assert "154-160" in exc.value.detail["citation"]


def test_a_hierarchy_path_used_as_a_name_is_refused(three_masters_one_ddr):
    """A producer/queue name is concatenated into a UVM component name at
    src/cl_syoscb.svh:120, so a traced path used raw would produce an illegal
    component path."""
    doctored = copy.deepcopy(plan_from(three_masters_one_ddr))
    doctored["producers"][0]["producer_name"] = "soc_top.u_cpu_axi"
    with pytest.raises(SyoscbTopologyPlanError) as exc:
        assert_names_are_legal_syosil_identifiers(doctored)
    assert exc.value.reason == "SYOSCB_PLAN_ILLEGAL_SYOSIL_NAME"
    assert exc.value.detail["names"] == [{"kind": "producer", "name": "soc_top.u_cpu_axi"}]


def test_a_route_neither_grouped_nor_excluded_is_refused(three_masters_one_ddr):
    doctored = copy.deepcopy(plan_from(three_masters_one_ddr))
    dropped = doctored["scoreboards"][0]["route_ids"].pop()
    with pytest.raises(SyoscbTopologyPlanError) as exc:
        stp.assert_plan_complete(doctored)
    assert exc.value.reason == "SYOSCB_PLAN_ROUTE_NEITHER_GROUPED_NOR_EXCLUDED"
    assert exc.value.detail["route_ids"] == [dropped]


def test_a_group_missing_one_observation_side_is_refused(three_masters_one_ddr):
    doctored = copy.deepcopy(plan_from(three_masters_one_ddr))
    doctored["queues"] = [q for q in doctored["queues"] if q["side"] == QUEUE_SIDE_MASTER]
    with pytest.raises(SyoscbTopologyPlanError) as exc:
        stp.assert_plan_complete(doctored)
    assert exc.value.reason == "SYOSCB_PLAN_GROUP_QUEUE_SIDES_INCOMPLETE"


# ===========================================================================
# The configuration calls and the review artifact
# ===========================================================================

def test_the_configuration_calls_are_structured_records_not_systemverilog(
        three_masters_one_ddr):
    plan = plan_from(three_masters_one_ddr)
    calls = syosil_configuration_calls(plan)
    api_ids = [c["api_id"] for c in calls]
    assert api_ids[:2] == ["cl_syoscb_cfg::set_queues", "cl_syoscb_cfg::set_primary_queue"]
    assert api_ids.count("cl_syoscb_cfg::set_producer") == 3
    # `set_queue` is never planned: build_phase constructs the queue objects.
    assert "cl_syoscb_cfg::set_queue" not in api_ids
    for call in calls:
        assert isinstance(call["arguments"], dict)
        assert ";" not in str(call["arguments"]), "a call record must not be an SV statement"
    primary = next(c for c in calls if c["api_id"] == "cl_syoscb_cfg::set_primary_queue")
    assert primary["arguments"]["primary_queue_name"].endswith(QUEUE_SIDE_MASTER)


def test_the_report_renders_and_passes_both_emission_gates(three_masters_one_ddr):
    plan = plan_from(three_masters_one_ddr)
    report = render_syoscb_configuration_plan_report(plan)
    assert_no_emittable_sv(report, label="test")
    assert_no_bind_statement(report)
    for expected in ("SYOSCB-14", "SYOSCB-15", "SYOSCB-16", "CPU_AXI",
                     "cl_syoscb_cfg::set_producer", "src/cl_syoscb_cfg.svh:71"):
        assert expected in report


def test_the_report_states_the_naive_instance_count_it_is_measured_against(
        three_masters_one_ddr):
    report = render_syoscb_configuration_plan_report(plan_from(three_masters_one_ddr))
    assert "naive one-scoreboard-per-route shape would be 3 instance(s)" in report


def test_the_module_reuses_the_predictors_vocabulary_rather_than_copying_it():
    """A second private ordering-domain or route-status vocabulary is exactly
    the duplicate-mechanism failure this project keeps catching."""
    assert ORDERING_DOMAIN_KEYS == (ORDERING_DOMAIN_PER_ROUTE,
                                    ORDERING_DOMAIN_PER_ROUTE_AND_ID)
    assert ROUTE_STATUS_VALUES == (ROUTE_LEGAL, ROUTE_WAIVED)
    assert stp.REQUIRED_HUMAN_INPUT is REQUIRED_HUMAN_INPUT


def test_every_cited_api_entry_names_a_real_upstream_file_path():
    """Cheap, and it keeps the citation table from acquiring an entry whose
    path nobody could open."""
    for entry in SYOSIL_CFG_API:
        assert entry["file"].startswith("src/")
        assert entry["file"].endswith(".svh")
        assert entry["line"] > 0
        assert entry["api_id"] == f"{entry['class']}::{entry['method']}"


# ===========================================================================
# The real parsed AMBA4 SoC, end to end
# ===========================================================================

@pytest.fixture(scope="module")
def real_registry(tmp_path_factory):
    if shutil.which(VERIBLE_BIN) is None:
        pytest.skip("verible-verilog-syntax not on PATH")
    sv = write_fixture(tmp_path_factory.mktemp("syoscb_topology_plan_rtl"))
    netlist = build_fabric_netlist([parse_file(sv)], "soc_top")
    traces = trace_all_fabric_ports(netlist, FABRIC)
    plan = build_vip_bind_plan(netlist, traces)
    return build_amba_port_registry(netlist, traces, plan)


@requires_verible
def test_the_real_discovered_fabric_produces_a_real_plan(real_registry):
    """The whole chain with nothing synthetic: real RTL -> real trace -> real
    AMBA_PORT_REGISTRY -> real predictions -> a real SyoSil configuration
    plan."""
    predictions = predict_routes(real_registry, assume_full_connectivity=True)
    plan = build_syoscb_configuration_plan(real_registry, predictions)
    assert plan["scaling"]["legal_route_count"] >= 1
    assert plan["scaling"]["planned_scoreboard_count"] >= 1
    assert plan["producers"], "a discovered master must become a producer"
    for producer in plan["producers"]:
        assert producer["producer_name"] in {r["port_id"] for r in real_registry}
    assert_queues_are_not_per_physical_port(plan)
    assert_every_producer_queue_is_declared(plan)
    assert_names_are_legal_syosil_identifiers(plan)
    report = render_syoscb_configuration_plan_report(plan)
    assert_no_emittable_sv(report, label="real fixture plan")
    assert_no_bind_statement(report)


@requires_verible
def test_the_real_plans_groups_never_outnumber_its_routes(real_registry):
    predictions = predict_routes(real_registry, assume_full_connectivity=True)
    plan = build_syoscb_configuration_plan(real_registry, predictions)
    grouping = group_routes_into_scoreboards(predictions)
    assert (plan["scaling"]["planned_scoreboard_count"]
            <= plan["scaling"]["legal_route_count"])
    assert len(grouping["groups"]) == plan["scaling"]["planned_scoreboard_count"]
    assert all(r["excluded"] or r["ordering_domain_key"] != REQUIRED_HUMAN_INPUT
               for r in plan["routes"])


@requires_verible
@real_source
def test_the_real_plan_is_built_on_an_api_the_real_source_still_carries(real_registry):
    """The two real inputs joined: the discovered fabric and the upstream
    library, checked together the way a Phase-2 implementer would have to."""
    predictions = predict_routes(real_registry, assume_full_connectivity=True)
    plan = build_syoscb_configuration_plan(real_registry, predictions)
    audit = audit_syoscb_source(REAL_SYOSCB_ROOT)
    assert_cited_syosil_api_matches_source(audit)
    planned = {c["api_id"] for c in syosil_configuration_calls(plan)}
    cited = {e["api_id"] for e in SYOSIL_CFG_API}
    assert planned <= cited, "a planned call must be one the citation table verified"
    assert TRANSFORM_PREDICTED_FROM_TOPOLOGY in {
        p["responsibilities"]["ordering_domain"]["status"] for p in predictions}
