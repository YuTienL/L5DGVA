"""Tests for dv_harness/amba_discovery_report.py -- AMBA-26 (L5 branch
mapping), AMBA-27 (evidence + confidence rule), AMBA-28 (the exact seventeen-
item discovery report order) and AMBA-29 (per-port and overall readiness).

TWO REAL RTL FIXTURES, DELIBERATELY DIFFERENT
---------------------------------------------
Both are imported rather than copied, so this module is proven against the
exact topologies AMBA-7..25 were proven against:

  * `test_amba_fabric_discovery.write_fabric_fixture` -- eleven fabric ports
    whose traces collectively reach ALL TEN AMBA-14 termination states,
    including MULTIPLE_SOURCE, MULTIPLE_DESTINATION, TRACE_BLOCKED, AMBIGUOUS,
    SOURCE_NOT_FOUND, DESTINATION_NOT_FOUND and INTERNAL_ONLY, across AXI4,
    APB4 and AHB-Lite. Its modules declare NO clock or reset ports at all, so
    AMBA-29's clock/reset attribute genuinely cannot resolve on any port. This
    is the AMBIGUOUS case, and it is the one most tests here run against: a
    readiness computation and a confidence scale exercised only on a clean
    fabric would be the happy-path-only coverage this project has already been
    burned by (see AMBA-14's ten states existing at all).
  * `test_amba_fabric_analysis.write_fixture` -- a clean two-master /
    two-slave AXI4 SoC WITH real spec-named clocks and resets, a CDC wrapper
    and an AXI-to-APB bridge. This is the CLEAN case, and it is what proves
    READY and HIGH/MEDIUM are reachable at all rather than being unreachable
    states a permissive test would never notice.

Both fixtures are synthetic and are the only place a bind-like construct could
legitimately live; neither contains one, and
`test_no_bind_statement_in_the_module_or_any_artifact_it_renders` asserts that
of the new module's own source and of every artifact it renders, per the
AMBA-30 / AMBA-31 review gate.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import amba_discovery_report as adr
from dv_harness import amba_fabric_discovery as afd
from dv_harness import amba_port_registry as apr
from dv_harness import connectivity, inference, question_queue
from dv_harness.amba_discovery_report import (
    AMBA28_SECTIONS,
    AMBA29_REQUIRED_ATTRIBUTES,
    AMBA30_REVIEW_GATE_LINES,
    BRANCH_FW_APPLICABLE,
    BRANCH_FW_NOT_APPLICABLE,
    CONFIDENCE_DEFINITIONS,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_UNKNOWN,
    CONFIDENCE_VALUES,
    CONFIRMED_TOPOLOGY_CONFIDENCE,
    Conclusion,
    DiscoveryInputs,
    DiscoveryReportError,
    EvidenceRef,
    L5_BRANCH_BLOCK,
    L5_BRANCH_FW,
    assert_not_reported_as_confirmed_topology,
    assert_readiness_respects_confidence,
    assert_report_section_order,
    branch_topology_gate_blockers,
    build_conclusions,
    build_discovery_report,
    build_l5_branch_mapping,
    build_port_readiness,
    compute_port_readiness,
    derive_overall_readiness,
    l5_branch_a,
    l5_branch_b,
    render_discovery_report,
    render_l5_branch_mapping_report,
    unresolved_abstractions,
)
from dv_harness.amba_fabric_discovery import (
    BIND_READINESS_BLOCKED,
    BIND_READINESS_PARTIAL,
    BIND_READINESS_READY,
    BIND_READINESS_UNKNOWN,
    BIND_READINESS_VALUES,
    TraceTerminationStatus,
)
from dv_harness.connectivity import REQUIRED_HUMAN_INPUT
from dv_harness.verible_parser import parse_file

from dv_harness_tests.test_amba_fabric_analysis import write_fixture as write_clean_fixture
from dv_harness_tests.test_amba_fabric_discovery import write_fabric_fixture

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)

ROOT = Path(__file__).resolve().parents[1]
BRANCH_TOPOLOGY_GATE = ROOT / "tools" / "verification_flow" / "branch_topology_gate.py"


# ---------------------------------------------------------------------------
# Fixtures: the ambiguous fabric and the clean one
# ---------------------------------------------------------------------------

class _Discovery:
    """One complete AMBA-1..25 pass, so every test below reads the SAME facts."""

    def __init__(self, netlist, fabric_path):
        self.netlist = netlist
        self.fabric_path = fabric_path
        self.traces = afd.trace_all_fabric_ports(netlist, afd.parse_instance_path(fabric_path))
        self.plan = afd.build_vip_bind_plan(netlist, self.traces)
        self.registry = apr.build_amba_port_registry(netlist, self.traces, self.plan)
        self.conclusions = build_conclusions(netlist, self.traces, self.plan.matrix)
        self.readiness = build_port_readiness(self.plan.matrix, self.traces,
                                              self.conclusions)
        self.branch_mapping = build_l5_branch_mapping(
            netlist, self.plan.matrix, self.plan.vip_instances,
            fabric_instance_path=fabric_path, port_readiness=self.readiness)

    def port(self, interface_id):
        return next(p for p in self.readiness if p.port == interface_id)

    def conclusion(self, interface_id, attribute):
        return next(c for c in self.conclusions
                    if c.subject == interface_id and c.attribute == attribute)


@pytest.fixture(scope="module")
def ambiguous(tmp_path_factory):
    """Eleven fabric ports, all ten AMBA-14 states, no clocks anywhere."""
    if shutil.which(VERIBLE_BIN) is None:
        pytest.skip("verible-verilog-syntax not on PATH")
    sv = write_fabric_fixture(tmp_path_factory.mktemp("amba26_ambiguous"))
    return _Discovery(afd.build_fabric_netlist([parse_file(sv)], "soc_top"), "u_fabric")


@pytest.fixture(scope="module")
def clean(tmp_path_factory):
    """Two AXI4 masters, two AXI4 fabric master ports, real clocks and resets."""
    if shutil.which(VERIBLE_BIN) is None:
        pytest.skip("verible-verilog-syntax not on PATH")
    sv = write_clean_fixture(tmp_path_factory.mktemp("amba26_clean"))
    return _Discovery(afd.build_fabric_netlist([parse_file(sv)], "soc_top"), "u_fabric")


# ===========================================================================
# AMBA-27: EVIDENCE + CONFIDENCE RULE
# ===========================================================================

def test_an_evidence_kind_outside_amba27s_list_is_refused():
    with pytest.raises(DiscoveryReportError) as exc:
        EvidenceRef("VIBES", "it looked right")
    assert exc.value.args[0] == "AMBA27_UNKNOWN_EVIDENCE_KIND"


def test_a_bare_evidence_kind_with_no_detail_is_not_a_reference_to_evidence():
    with pytest.raises(DiscoveryReportError) as exc:
        EvidenceRef("RTL_INSTANCE", "   ")
    assert exc.value.args[0] == "AMBA27_EVIDENCE_WITHOUT_DETAIL"


def test_a_conclusion_above_unknown_cannot_be_built_without_citing_evidence():
    """AMBA-27's first sentence, enforced at construction rather than reviewed:
    an unevidenced conclusion cannot reach a report at all."""
    with pytest.raises(DiscoveryReportError) as exc:
        Conclusion(subject="u_fabric:S00_AXI_", attribute="protocol",
                   statement="AXI4", confidence=CONFIDENCE_HIGH)
    assert exc.value.args[0] == "AMBA27_CONCLUSION_WITHOUT_EVIDENCE"


def test_an_unknown_conclusion_must_name_what_would_settle_it():
    with pytest.raises(DiscoveryReportError) as exc:
        Conclusion(subject="u_fabric:S00_AXI_", attribute="endpoint",
                   statement="cannot prove", confidence=CONFIDENCE_UNKNOWN)
    assert exc.value.args[0] == "AMBA27_UNKNOWN_WITHOUT_MISSING_EVIDENCE"

    ok = Conclusion(subject="u_fabric:S00_AXI_", attribute="endpoint",
                    statement="cannot prove", confidence=CONFIDENCE_UNKNOWN,
                    missing_evidence=["the driver's RTL is not in the parse set"])
    assert not ok.confirmable


def test_free_prose_cannot_be_passed_off_as_evidence():
    with pytest.raises(DiscoveryReportError) as exc:
        Conclusion(subject="s", attribute="protocol", statement="AXI4",
                   confidence=CONFIDENCE_HIGH,
                   evidence=["I checked the RTL"])
    assert exc.value.args[0] == "AMBA27_EVIDENCE_NOT_AN_EVIDENCE_REF"


def test_the_four_levels_are_exactly_the_docs_four_with_the_docs_definitions():
    assert CONFIDENCE_VALUES == ("HIGH", "MEDIUM", "LOW", "UNKNOWN")
    assert CONFIDENCE_DEFINITIONS[CONFIDENCE_HIGH] == "direct RTL connectivity"
    assert "one unresolved abstraction" in CONFIDENCE_DEFINITIONS[CONFIDENCE_MEDIUM]
    assert "naming-heavy" in CONFIDENCE_DEFINITIONS[CONFIDENCE_LOW]
    assert CONFIDENCE_DEFINITIONS[CONFIDENCE_UNKNOWN] == "cannot prove"
    # "LOW/UNKNOWN must not be reported as confirmed topology."
    assert CONFIRMED_TOPOLOGY_CONFIDENCE == {CONFIDENCE_HIGH, CONFIDENCE_MEDIUM}


@requires_verible
def test_every_conclusion_on_a_real_fabric_carries_a_level_and_real_evidence(ambiguous):
    """Not a spot check: EVERY conclusion the ambiguous fabric produces."""
    assert ambiguous.conclusions
    for c in ambiguous.conclusions:
        assert c.confidence in CONFIDENCE_VALUES
        if c.confidence == CONFIDENCE_UNKNOWN:
            assert c.missing_evidence
        else:
            assert c.evidence
            for ref in c.evidence:
                assert ref.kind in adr.EVIDENCE_KIND_KEYS
                assert ref.detail.strip()


@requires_verible
def test_four_attributes_are_answered_for_every_traced_port(ambiguous):
    by_subject = adr.conclusions_by_subject(ambiguous.conclusions)
    assert len(by_subject) == len(ambiguous.traces) == 11
    for subject, group in by_subject.items():
        assert {c.attribute for c in group} == {"protocol", "role", "endpoint",
                                                "bind_location"}


@requires_verible
def test_a_protocol_proven_from_its_own_signal_set_is_high(ambiguous):
    """HIGH = "direct RTL connectivity". The bundle's protocol comes from the
    ports really declared on the really elaborated instance."""
    c = ambiguous.conclusion("u_fabric:S00_AXI_", "protocol")
    assert c.confidence == CONFIDENCE_HIGH
    kinds = {e.kind for e in c.evidence}
    assert {"RTL_INSTANCE", "PORT_CONNECTION", "INTERFACE"} <= kinds


@requires_verible
def test_an_endpoint_that_cannot_be_proven_is_unknown_with_its_missing_evidence(ambiguous):
    """The port whose driver leaves the parsed design. UNKNOWN = "cannot
    prove", and it must say what is missing rather than fall back to LOW."""
    c = ambiguous.conclusion("u_fabric:S02_AXI_", "endpoint")
    assert c.confidence == CONFIDENCE_UNKNOWN
    assert c.missing_evidence
    assert not c.evidence
    assert not c.confirmable


@requires_verible
def test_a_port_whose_endpoint_lies_beyond_a_bridge_is_medium_not_high(ambiguous):
    """One unresolved abstraction -- what lies past the protocol bridge -- so
    MEDIUM by AMBA-27's own definition, never HIGH."""
    bridged = [t for t in ambiguous.traces
               if t.status == TraceTerminationStatus.PROTOCOL_BRIDGE_FOUND.value]
    assert bridged
    for trace in bridged:
        c = ambiguous.conclusion(trace.interface_id, "endpoint")
        assert c.confidence == CONFIDENCE_MEDIUM
        assert any(e.kind == "BRIDGE" for e in c.evidence)


@requires_verible
def test_medium_means_exactly_one_countable_unresolved_abstraction(clean):
    """AMBA-27's MEDIUM is not a feeling: `unresolved_abstractions()` returns a
    named list, one entry means MEDIUM and two or more mean LOW. The clean
    fixture's CDC-wrapped port is the real one-abstraction case (the wrapper's
    role rests on a name, which is a T3 naming heuristic)."""
    mediums = [c for c in clean.conclusions
               if c.attribute == "endpoint" and c.confidence == CONFIDENCE_MEDIUM]
    assert mediums, "the clean fixture must produce at least one MEDIUM endpoint"
    for c in mediums:
        trace = next(t for t in clean.traces if t.interface_id == c.subject)
        assert len(unresolved_abstractions(clean.netlist, trace)) == 1

    highs = [c for c in clean.conclusions
             if c.attribute == "endpoint" and c.confidence == CONFIDENCE_HIGH]
    for c in highs:
        trace = next(t for t in clean.traces if t.interface_id == c.subject)
        assert unresolved_abstractions(clean.netlist, trace) == []


@requires_verible
def test_each_named_abstraction_says_where_it_is_and_what_it_is(ambiguous):
    for trace in ambiguous.traces:
        for a in unresolved_abstractions(ambiguous.netlist, trace):
            assert a["abstraction"] and a["where"] and a["detail"]


@requires_verible
def test_a_low_or_unknown_subject_may_not_be_reported_as_confirmed_topology(ambiguous):
    """AMBA-27's last line, enforced. Feeding the unresolved ports into a
    confirmed-topology claim raises rather than quietly publishing them."""
    unprovable = {c.subject for c in ambiguous.conclusions if not c.confirmable}
    assert unprovable
    with pytest.raises(DiscoveryReportError) as exc:
        assert_not_reported_as_confirmed_topology(ambiguous.conclusions, unprovable)
    assert exc.value.args[0] == "AMBA27_LOW_OR_UNKNOWN_REPORTED_AS_CONFIRMED"

    # The ports whose every conclusion is HIGH/MEDIUM pass the same check.
    confirmable = {s for s, g in adr.conclusions_by_subject(ambiguous.conclusions).items()
                   if all(c.confirmable for c in g)}
    assert_not_reported_as_confirmed_topology(ambiguous.conclusions, confirmable)


# --- the fourth trust vocabulary, and why it is not a duplicate -------------

def test_amba27s_medium_is_not_expressible_as_an_inference_confidence_score():
    """Same executable-rationale discipline as
    test_confidence_vocabulary_separation.py, applied to the vocabulary this
    module adds.

    `inference.score_confidence()` is ADDITIVE over evidence counts. AMBA-27's
    MEDIUM is SUBTRACTIVE over a count of unresolved abstractions. A conclusion
    with many citations and several unresolved abstractions is LOW here and
    HIGH there -- so routing AMBA-27 through score_confidence() would report a
    structurally-unresolved port as confirmed topology, which AMBA-27's last
    line forbids."""
    heavily_cited_but_unresolved = inference.score_confidence(
        independent_sources_count=3, evidence_refs_verified=True,
        counter_evidence_count=0, multi_agent_consensus_count=2)
    assert heavily_cited_but_unresolved["level"] == "HIGH"

    # The same conclusion under AMBA-27: three named unresolved abstractions.
    three = [{"abstraction": "OPAQUE_STRUCTURAL_ELEMENT", "where": "u_a", "detail": "x"},
             {"abstraction": "HOP_ROLE_RESTS_ON_A_NAME", "where": "u_b", "detail": "y"},
             {"abstraction": "MULTIPLE_BRANCHES_NOT_NARROWED", "where": "u_c",
              "detail": "z"}]
    assert len(three) >= 2      # AMBA-27: two or more is LOW, regardless of citations
    # And a single-source, single-abstraction conclusion is MEDIUM here while
    # score_confidence() rates it identically to the three-abstraction one
    # would be rated if only its source count were read.
    one_source = inference.score_confidence(
        independent_sources_count=1, evidence_refs_verified=True,
        counter_evidence_count=0, multi_agent_consensus_count=0)
    assert one_source["level"] == "MEDIUM"
    assert one_source["level"] != heavily_cited_but_unresolved["level"]
    # The orderings genuinely disagree: AMBA-27 ranks the one-abstraction
    # conclusion ABOVE the three-abstraction one, score_confidence() ranks the
    # richly-cited (three-abstraction) one above the single-source one.
    assert adr.worst_confidence([CONFIDENCE_MEDIUM]) == CONFIDENCE_MEDIUM
    assert adr.worst_confidence([CONFIDENCE_MEDIUM, CONFIDENCE_LOW]) == CONFIDENCE_LOW


def test_the_existing_three_way_vocabulary_disjointness_is_untouched():
    """The new scale reuses inference's three words BY MANDATE (AMBA-27 spells
    them out). It must not leak into the two tier ladders that
    test_confidence_vocabulary_separation.py keeps token-disjoint from them."""
    bind_tiers = {t.value for t in connectivity.BindTier}
    qq_tiers = set(question_queue.TIER_NAMES.values())
    for level in CONFIDENCE_VALUES:
        for name in bind_tiers | qq_tiers:
            assert level not in name.upper()
    src = (ROOT / "dv_harness" / "amba_discovery_report.py").read_text(encoding="utf-8")
    assert "test_confidence_vocabulary_separation" in src, (
        "the rationale anchor a future auditor greps for must stay in the module")
    assert not re.search(r"^\s*(from\s+\S*inference\S*\s+import|import\s+\S*inference)",
                         src, re.MULTILINE), (
        "AMBA-27 must not be routed through inference.py -- see this test's docstring")


# ===========================================================================
# AMBA-29: READINESS
# ===========================================================================

def test_the_five_required_attributes_are_the_docs_five():
    assert [k for k, _ in AMBA29_REQUIRED_ATTRIBUTES] == [
        "protocol", "role", "endpoint", "bind_hierarchy", "clock_reset"]


@requires_verible
def test_every_port_gets_exactly_one_of_the_four_states(ambiguous):
    assert len(ambiguous.readiness) == 11
    for pr in ambiguous.readiness:
        assert pr.status in BIND_READINESS_VALUES
        assert pr.reason
        assert [a.key for a in pr.attributes] == [k for k, _ in AMBA29_REQUIRED_ATTRIBUTES]


@requires_verible
def test_a_fully_established_port_is_ready(clean):
    """READY is reachable, and only when all five attributes really resolved.
    The clean fixture has real spec-named clocks and resets; the ambiguous one
    has none, which is why no port there can be READY."""
    ready = [pr for pr in clean.readiness if pr.status == BIND_READINESS_READY]
    assert ready, "the clean fixture must produce at least one READY port"
    for pr in ready:
        assert all(a.resolved for a in pr.attributes)
        assert pr.unresolved_attributes == []
        assert pr.confidence in CONFIRMED_TOPOLOGY_CONFIDENCE


@requires_verible
def test_no_port_of_a_clockless_fabric_is_ready_and_each_names_clock_reset(ambiguous):
    """The failure a permissive readiness rule makes: every one of these ports
    has protocol, role and a bind location, and not one of them has a clock.
    READY must not be reachable by four-fifths of the evidence."""
    assert all(pr.status != BIND_READINESS_READY for pr in ambiguous.readiness)
    partials = [pr for pr in ambiguous.readiness if pr.status == BIND_READINESS_PARTIAL]
    assert partials
    for pr in partials:
        assert "clock/reset" in pr.unresolved_attributes
        assert "clock/reset" in pr.reason


@requires_verible
def test_a_multiple_branch_port_is_partial_not_blocked(ambiguous):
    """AMBA-12/13 enumerate every branch and forbid choosing one. That open
    CHOICE is not the same as having nowhere to bind, and collapsing it to
    BLOCKED would send a reviewer looking for missing RTL."""
    multi = [t for t in ambiguous.traces
             if t.status in (TraceTerminationStatus.MULTIPLE_SOURCE.value,
                             TraceTerminationStatus.MULTIPLE_DESTINATION.value)]
    assert multi
    for trace in multi:
        pr = ambiguous.port(trace.interface_id)
        assert pr.status == BIND_READINESS_PARTIAL
        assert "AMBA-12/13" in pr.reason


def _row(**over):
    base = {"row_id": "u_fabric:S00_AXI_", "fabric_port": "u_fabric:S00_AXI_",
            "protocol": "AXI4", "fabric_role": "SLAVE_INTERFACE",
            "endpoint_instance_path": "u_cpu", "trace_status": "SOURCE_FOUND",
            "proposed_vip_bind_hierarchy": "u_cpu:M_AXI_", "vip_role": "MONITOR",
            "clock": "ACLK", "reset": "ARESETN", "validation": None}
    base.update(over)
    return base


def test_a_port_with_nothing_established_is_unknown_not_blocked():
    """UNKNOWN = "insufficient evidence". Two different failures the doc keeps
    apart: nothing is known here, versus nothing usable exists."""
    pr = compute_port_readiness(_row(
        protocol=REQUIRED_HUMAN_INPUT, fabric_role=REQUIRED_HUMAN_INPUT,
        endpoint_instance_path="", trace_status="AMBIGUOUS",
        proposed_vip_bind_hierarchy=REQUIRED_HUMAN_INPUT,
        clock=REQUIRED_HUMAN_INPUT, reset=REQUIRED_HUMAN_INPUT))
    assert pr.status == BIND_READINESS_UNKNOWN
    assert "insufficient evidence" in pr.reason


def test_an_identified_port_with_no_endpoint_and_no_location_is_blocked_not_unknown():
    """BLOCKED = "no usable endpoint/bind location". The port IS identified --
    protocol and role are known -- so "insufficient evidence" would be the
    wrong thing to tell a reviewer."""
    pr = compute_port_readiness(_row(
        endpoint_instance_path="", trace_status="DESTINATION_NOT_FOUND",
        proposed_vip_bind_hierarchy=REQUIRED_HUMAN_INPUT))
    assert pr.status == BIND_READINESS_BLOCKED
    assert "no usable endpoint and no usable bind location" in pr.reason


@requires_verible
def test_a_disproven_bind_location_is_blocked_and_never_averages_to_partial(ambiguous):
    """AMBA-15's DISPROVEN check dominates: a bind hierarchy that does not
    exist is not a location a human can approve, however many other attributes
    resolved."""
    validation = afd.validate_vip_bind_location(
        ambiguous.netlist, "u_does_not_exist/u_nor_this", "S_AXI_")
    assert validation.readiness == BIND_READINESS_BLOCKED
    pr = compute_port_readiness(_row(validation=validation))
    assert pr.status == BIND_READINESS_BLOCKED
    assert "DISPROVEN" in pr.reason
    # Every other attribute in that row is resolved; the verdict is still BLOCKED.
    assert all(a.resolved for a in pr.attributes)


def test_the_amba15_thirteen_point_readiness_is_reported_beside_not_merged():
    """AMBA-29 names five attributes; AMBA-15 checks thirteen including signal
    widths. A port with an unprovable USER width is PARTIAL there and may be
    READY here, and the report must show both rather than silently pick one."""
    class _V:
        readiness = BIND_READINESS_PARTIAL
        checks: list = []
        unknown_points = ["USER widths known where applicable"]
        failed_points: list = []
    pr = compute_port_readiness(_row(validation=_V()))
    assert pr.status == BIND_READINESS_READY
    assert pr.bind_location_readiness == BIND_READINESS_PARTIAL


@requires_verible
def test_overall_readiness_is_derived_from_the_per_port_set_worst_first(ambiguous):
    overall = derive_overall_readiness(ambiguous.readiness)
    statuses = {pr.status for pr in ambiguous.readiness}
    assert overall["overall"] == afd._worst_readiness(statuses)
    assert sum(overall["counts"].values()) == len(ambiguous.readiness)
    assert overall["total_ports"] == 11
    # Actionable, not a mood: the ports that produced the verdict are named.
    assert overall["governing_ports"]
    assert all(g["status"] == overall["overall"] for g in overall["governing_ports"])
    assert all(g["reason"] for g in overall["governing_ports"])


def test_an_empty_port_set_is_unknown_not_ready():
    """A fabric nobody discovered ports on has not been proven ready for
    anything -- the vacuous-truth failure a naive `all()` rollup makes."""
    overall = derive_overall_readiness([])
    assert overall["overall"] == BIND_READINESS_UNKNOWN
    assert overall["total_ports"] == 0
    assert "no fabric port" in overall["reason"]


def test_one_blocked_port_governs_the_whole_rollup():
    ports = [compute_port_readiness(_row(row_id=f"p{i}")) for i in range(4)]
    assert derive_overall_readiness(ports)["overall"] == BIND_READINESS_READY
    ports.append(compute_port_readiness(_row(
        row_id="p_bad", endpoint_instance_path="", trace_status="TRACE_BLOCKED",
        proposed_vip_bind_hierarchy=REQUIRED_HUMAN_INPUT)))
    overall = derive_overall_readiness(ports)
    assert overall["overall"] == BIND_READINESS_BLOCKED
    assert [g["port"] for g in overall["governing_ports"]] == ["p_bad"]


def test_a_ready_port_resting_on_low_evidence_is_refused():
    """The one place AMBA-27 and AMBA-29 are coupled: a READY port is a
    confirmed-topology claim, and AMBA-27 forbids confirming LOW/UNKNOWN."""
    pr = compute_port_readiness(_row())
    assert pr.status == BIND_READINESS_READY
    pr.confidence = CONFIDENCE_LOW
    with pytest.raises(DiscoveryReportError) as exc:
        assert_readiness_respects_confidence([pr])
    assert exc.value.args[0] == "AMBA29_READY_PORT_ON_LOW_OR_UNKNOWN_EVIDENCE"


@requires_verible
def test_both_real_fabrics_satisfy_the_confidence_readiness_coupling(ambiguous, clean):
    assert_readiness_respects_confidence(ambiguous.readiness)
    assert_readiness_respects_confidence(clean.readiness)


# ===========================================================================
# AMBA-26: L5 BRANCH MAPPING
# ===========================================================================

def test_branch_names_use_the_repos_canonical_underscore_zero_indexed_form():
    """`branch_topology_gate.py` declares itself the single source of truth for
    the canonical form after four incompatible conventions were found
    coexisting. AMBA-26 says to map into EXISTING L5 naming, so that spelling
    wins over the master prompt's `branch-a1..N` prose."""
    assert l5_branch_a(0) == "branch_a0" and l5_branch_a(3) == "branch_a3"
    assert l5_branch_b(0) == "branch_b0"
    assert L5_BRANCH_BLOCK == "block" and L5_BRANCH_FW == "branch_fw"
    gate_src = BRANCH_TOPOLOGY_GATE.read_text(encoding="utf-8")
    assert 'f"branch_a{i}" for i in range(0,dut_ports)' in gate_src
    assert 'f"branch_b{i}" for i in range(0,vip_ports)' in gate_src


@requires_verible
def test_branch_a_is_one_per_fabric_facing_physical_interface(ambiguous):
    """AMBA-26's unit is the fabric PORT, by actual port count -- not the
    master/slave AGENT the branch-mapper skill's 2026-09-01 placeholder used.
    A multiple-source port's enumerated branches are not extra interfaces."""
    mapping = ambiguous.branch_mapping
    assert mapping.dut_port_count == len(ambiguous.traces) == 11
    assert [e["branch"] for e in mapping.branch_a] == [f"branch_a{i}" for i in range(11)]
    assert {e["fabric_port"] for e in mapping.branch_a} == {
        t.interface_id for t in ambiguous.traces}


@requires_verible
def test_branch_b_is_by_discovered_vip_count_not_by_slave_or_port_count(ambiguous):
    """The other half of the placeholder's unit mismatch: branch_b is the VIP
    count, and on a real fabric that is neither the port count nor the slave
    count (a bridge's second side adds one, an unresolvable port adds none)."""
    mapping = ambiguous.branch_mapping
    assert mapping.vip_port_count == len(ambiguous.plan.vip_instances)
    assert mapping.vip_port_count != mapping.dut_port_count
    endpoints = afd.discovered_topology_ids(ambiguous.traces)
    assert mapping.vip_port_count != len(endpoints["slaves"])
    assert [e["branch"] for e in mapping.branch_b] == [
        f"branch_b{i}" for i in range(mapping.vip_port_count)]
    assert all(e["vip_id"] for e in mapping.branch_b)


@requires_verible
def test_no_abstract_branch_name_is_invented(ambiguous):
    """AMBA-26: "Do not invent abstract branch names.\""""
    allowed = re.compile(r"^(block|branch_fw|branch_a\d+|branch_b\d+)$")
    for name in ambiguous.branch_mapping.branch_names:
        assert allowed.match(name), name


@requires_verible
def test_branch_fw_is_not_claimed_without_real_interrupt_evidence(ambiguous):
    """"when applicable". The ambiguous fixture's fabric declares no
    interrupt/event port, so branch_fw is named (existing L5 topology always
    carries it) but its interrupt contract is not asserted."""
    fw = ambiguous.branch_mapping.branch_fw
    assert fw["applicability"] == BRANCH_FW_NOT_APPLICABLE
    assert fw["interrupt_driven"] is False
    assert fw["interrupt_ports"] == []
    assert fw["confidence"] == CONFIDENCE_UNKNOWN
    assert fw["requires_human_confirmation"] is True
    assert L5_BRANCH_FW in ambiguous.branch_mapping.branch_names


def test_branch_fw_interrupt_evidence_is_tiered_as_the_naming_heuristic_it_is():
    """A port called IRQ is a NAME, not a proven interrupt contract. It reaches
    T3/LOW and still requires human confirmation -- it never becomes a fact."""
    modules = [{
        "name": "top", "ports": [], "continuous_assigns": [],
        "instances": [{"instance_name": "u_fabric", "module_name": "fabric_bb",
                       "connections": [
                           {"port_name": "S_AXI_AWVALID", "position": 0,
                            "expr_text": None, "nets": ["n0"]},
                           {"port_name": "FABRIC_ERR_IRQ", "position": 1,
                            "expr_text": None, "nets": ["n1"]}]}],
    }]
    netlist = afd.build_fabric_netlist([{"modules": modules}], "top")
    mapping = build_l5_branch_mapping(netlist, [], [], fabric_instance_path="u_fabric")
    fw = mapping.branch_fw
    assert fw["applicability"] == BRANCH_FW_APPLICABLE
    assert fw["interrupt_ports"] == ["FABRIC_ERR_IRQ"]
    assert fw["evidence_tier"] == connectivity.BindTier.T3_NAMING_HEURISTIC.value
    assert fw["confidence"] == CONFIDENCE_LOW
    assert fw["requires_human_confirmation"] is True


@requires_verible
def test_the_arbitration_policy_is_required_human_input_not_guessed(ambiguous):
    """Round-robin vs priority vs QoS lives in arbiter RTL nobody has read.
    AMBA-25 identified the shared resources; the POLICY is refused."""
    model = ambiguous.branch_mapping.cross_branch_bus_model
    assert model["arbitration_policy"] == REQUIRED_HUMAN_INPUT
    assert model["arbitration_policy_source"]
    fields = {b["field"] for b in branch_topology_gate_blockers(ambiguous.branch_mapping)}
    assert "cross_branch_bus_model.arbitration_policy" in fields
    assert "branch_fw_interrupt_driven" in fields


@requires_verible
def test_the_mapping_is_checked_by_the_real_existing_branch_topology_gate(ambiguous,
                                                                          tmp_path):
    """Not "schema-compatible" as a claim -- the real gate is run as a
    subprocess against the real emitted document, twice: once as discovered
    (it must FAIL, and for exactly the reasons the blockers named), and once
    with a human's answers filled in (it must PASS with the discovered port
    counts)."""
    doc = ambiguous.branch_mapping.to_branch_topology()
    path = tmp_path / "branch_topology.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(BRANCH_TOPOLOGY_GATE),
                           "--topology", str(path)],
                          capture_output=True, text=True)
    assert proc.returncode != 0
    failed = json.loads(proc.stdout)
    assert failed["status"] == "FAIL"
    assert failed["reason"] in {b["gate_reason"]
                                for b in branch_topology_gate_blockers(
                                    ambiguous.branch_mapping)}

    # The same document with the two human-supplied answers filled in.
    doc["branch_fw_interrupt_driven"] = True
    doc["cross_branch_bus_model"] = {
        "shared_resources": ["u_sram0"], "arbitration_policy": "round_robin"}
    path.write_text(json.dumps(doc), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(BRANCH_TOPOLOGY_GATE),
                           "--topology", str(path)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout
    passed = json.loads(proc.stdout)
    assert passed == {"status": "PASS", "dut_ports": 11,
                      "vip_ports": ambiguous.branch_mapping.vip_port_count}


@requires_verible
def test_the_branch_mapping_report_states_its_open_items(ambiguous):
    text = render_l5_branch_mapping_report(ambiguous.branch_mapping)
    assert "AMBA-26 L5 Branch Mapping" in text
    assert "branch_a0" in text and "branch_b0" in text
    assert "does NOT yet pass the existing branch-topology gate" in text
    assert "arbitration_policy" in text


# ===========================================================================
# AMBA-28: DISCOVERY REPORT ORDER
# ===========================================================================

def test_the_seventeen_sections_are_the_docs_seventeen_in_the_docs_order():
    assert [n for n, _ in AMBA28_SECTIONS] == list(range(1, 18))
    assert [t for _, t in AMBA28_SECTIONS] == [
        "INPUT RESOLUTION", "BUS FABRIC INSTANCE", "PORT ENUMERATION",
        "PROTOCOL CLASSIFICATION", "MASTER / SLAVE COUNTS", "PER-PORT RTL TRACE",
        "FABRIC PORT -> VIP BIND MATRIX", "UNRESOLVED PORTS", "TOPOLOGY TREE",
        "CLOCK / RESET MATRIX", "VIP INSTANCE PLAN",
        "SCOREBOARD REFERENCE ENVIRONMENT ANALYSIS", "SCOREBOARD CONNECTION PLAN",
        "AMBA_PORT_REGISTRY DRAFT", "READINESS STATUS",
        "OPEN QUESTIONS / MISSING EVIDENCE", "USER REVIEW GATE"]


@requires_verible
def test_a_real_report_carries_all_seventeen_sections_once_each_in_order(ambiguous):
    report = build_discovery_report(
        ambiguous.netlist, ambiguous.traces, ambiguous.plan, ambiguous.registry,
        inputs=DiscoveryInputs(top_module="soc_top", fabric_instance_path="u_fabric",
                               rtl_sources=["amba4_soc_fixture.sv"]),
        conclusions=ambiguous.conclusions, port_readiness=ambiguous.readiness,
        branch_mapping=ambiguous.branch_mapping)
    assert [n for n, _, _ in report.sections] == list(range(1, 18))
    text = render_discovery_report(report)
    assert_report_section_order(text)      # raises if the finished text disagrees
    for number, title in AMBA28_SECTIONS:
        assert f"## {number}. {title}" in text


@requires_verible
def test_a_section_whose_input_was_not_supplied_says_so_rather_than_vanishing(ambiguous):
    """"this analysis was not run" and "this analysis found nothing" must not
    look alike -- the property AMBA-17's mandatory-even-when-empty table has."""
    report = build_discovery_report(
        ambiguous.netlist, ambiguous.traces, ambiguous.plan, ambiguous.registry,
        conclusions=ambiguous.conclusions, port_readiness=ambiguous.readiness)
    for number in (10, 12, 13):            # clock/reset, scoreboard env, scaling
        body = report.section(number)
        assert "NOT SUPPLIED" in body
        assert "To fill this section:" in body


@requires_verible
def test_the_supplied_analyses_really_replace_the_not_supplied_notes(ambiguous):
    """The optional sections are wired to the real AMBA-24/AMBA-25 renderers,
    not just to a placeholder."""
    from dv_harness.amba_fabric_analysis import (
        analyze_all_bind_point_domains, build_fabric_scaling_plan)
    domains = analyze_all_bind_point_domains(ambiguous.netlist, ambiguous.plan.matrix,
                                             ambiguous.traces)
    scaling = build_fabric_scaling_plan(ambiguous.registry, assume_full_connectivity=True)
    report = build_discovery_report(
        ambiguous.netlist, ambiguous.traces, ambiguous.plan, ambiguous.registry,
        conclusions=ambiguous.conclusions, port_readiness=ambiguous.readiness,
        domain_analyses=domains, scaling_plan=scaling)
    assert "NOT SUPPLIED" not in report.section(10)
    assert "NOT SUPPLIED" not in report.section(13)
    assert_report_section_order(render_discovery_report(report))


def test_a_missing_section_is_caught_in_the_finished_text():
    text = "\n".join([f"## {n}. {t}\n\nbody\n" for n, t in AMBA28_SECTIONS[:-1]])
    with pytest.raises(DiscoveryReportError) as exc:
        assert_report_section_order("\n" + text)
    assert exc.value.args[0] == "AMBA28_SECTION_MISSING"


def test_sections_out_of_order_are_caught_in_the_finished_text():
    shuffled = list(AMBA28_SECTIONS)
    shuffled[2], shuffled[9] = shuffled[9], shuffled[2]
    text = "\n" + "\n".join([f"## {n}. {t}\n\nbody\n" for n, t in shuffled])
    with pytest.raises(DiscoveryReportError) as exc:
        assert_report_section_order(text)
    assert exc.value.args[0] == "AMBA28_SECTIONS_OUT_OF_ORDER"


def test_a_duplicated_section_heading_is_caught():
    text = "\n" + "\n".join([f"## {n}. {t}\n\nbody\n" for n, t in AMBA28_SECTIONS])
    text += f"\n## 1. {AMBA28_SECTIONS[0][1]}\n\nagain\n"
    with pytest.raises(DiscoveryReportError) as exc:
        assert_report_section_order(text)
    assert exc.value.args[0] == "AMBA28_SECTION_DUPLICATED"


@requires_verible
def test_section_17_is_amba30s_gate_text_verbatim(ambiguous):
    report = build_discovery_report(
        ambiguous.netlist, ambiguous.traces, ambiguous.plan, ambiguous.registry,
        conclusions=ambiguous.conclusions, port_readiness=ambiguous.readiness)
    body = report.section(17)
    assert AMBA30_REVIEW_GATE_LINES == (
        "AMBA FABRIC DISCOVERY COMPLETE", "FABRIC PORT CLASSIFICATION COMPLETE",
        "ENDPOINT TRACE COMPLETE", "VIP BIND PLAN COMPLETE",
        "SCOREBOARD MAPPING COMPLETE", "UVM IMPLEMENTATION NOT STARTED",
        "AWAITING USER REVIEW")
    for line in AMBA30_REVIEW_GATE_LINES:
        assert line in body
    assert body.index("AMBA FABRIC DISCOVERY COMPLETE") < body.index("AWAITING USER REVIEW")
    assert "No production UVM has been generated or modified" in body


@requires_verible
def test_section_16_collects_every_open_item_from_every_source(ambiguous):
    report = build_discovery_report(
        ambiguous.netlist, ambiguous.traces, ambiguous.plan, ambiguous.registry,
        conclusions=ambiguous.conclusions, port_readiness=ambiguous.readiness,
        branch_mapping=ambiguous.branch_mapping)
    body = report.section(16)
    for source in ("AMBA-14 trace", "AMBA-27", "AMBA-29 readiness",
                   "AMBA-26 branch mapping"):
        assert source in body


@requires_verible
def test_section_15_derives_and_prints_the_overall_verdict(ambiguous):
    body = build_discovery_report(
        ambiguous.netlist, ambiguous.traces, ambiguous.plan, ambiguous.registry,
        conclusions=ambiguous.conclusions,
        port_readiness=ambiguous.readiness).section(15)
    overall = derive_overall_readiness(ambiguous.readiness)
    assert f"OVERALL AMBA VERIFICATION READINESS: {overall['overall']}" in body
    for value in BIND_READINESS_VALUES:
        assert value in body


@requires_verible
def test_sections_1_to_4_report_the_real_resolved_inputs_and_bundles(ambiguous):
    report = build_discovery_report(
        ambiguous.netlist, ambiguous.traces, ambiguous.plan, ambiguous.registry,
        inputs=DiscoveryInputs(top_module="soc_top", fabric_instance_path="u_fabric",
                               filelists=["rtl.f"], defines=["AXI_ID_W=4"]),
        conclusions=ambiguous.conclusions, port_readiness=ambiguous.readiness)
    assert "rtl.f" in report.section(1) and "FILELIST" in report.section(1)
    assert "AXI_ID_W=4" in report.section(1)
    assert "u_fabric" in report.section(2) and "soc_top" in report.section(2)
    assert "AMBA bundle(s) enumerated" in report.section(3)
    for trace in ambiguous.traces:
        assert trace.bundle_prefix in report.section(3)
        assert trace.interface_id in report.section(4)


@requires_verible
def test_an_input_naming_a_hierarchy_that_does_not_exist_says_so(ambiguous):
    report = build_discovery_report(
        ambiguous.netlist, ambiguous.traces, ambiguous.plan, ambiguous.registry,
        inputs=DiscoveryInputs(top_module="soc_top",
                               fabric_instance_path="u_not_a_real_instance"),
        conclusions=ambiguous.conclusions, port_readiness=ambiguous.readiness)
    assert "is NOT an elaborated instance" in report.section(2)


@requires_verible
def test_the_report_composes_the_existing_renderers_rather_than_new_tables(ambiguous):
    """Items 5-11 and 14 must be the artifacts a human was already taught to
    read; a second, separately-computed table would be free to disagree with
    the one AMBA-16..25 produced."""
    report = build_discovery_report(
        ambiguous.netlist, ambiguous.traces, ambiguous.plan, ambiguous.registry,
        conclusions=ambiguous.conclusions, port_readiness=ambiguous.readiness)
    assert report.section(5) == afd.render_amba_topology_summary(ambiguous.plan.summary)
    assert report.section(6) == afd.render_endpoint_trace_report(ambiguous.traces)
    assert report.section(7) == afd.render_fabric_vip_bind_matrix(ambiguous.plan.matrix)
    assert report.section(8) == afd.render_unresolved_fabric_port_table(
        ambiguous.plan.unresolved)
    assert ambiguous.plan.tree in report.section(9)
    assert report.section(11) == afd.render_vip_instance_plan(
        ambiguous.plan.vip_instances)
    assert report.section(14) == apr.render_amba_port_registry(ambiguous.registry)


# ===========================================================================
# AMBA-30 / AMBA-31: nothing here emits a bind
# ===========================================================================

@requires_verible
def test_no_bind_statement_in_the_module_or_any_artifact_it_renders(ambiguous, clean):
    src = (ROOT / "dv_harness" / "amba_discovery_report.py").read_text(encoding="utf-8")
    afd.assert_no_bind_statement(src)
    for disc in (ambiguous, clean):
        report = build_discovery_report(
            disc.netlist, disc.traces, disc.plan, disc.registry,
            conclusions=disc.conclusions, port_readiness=disc.readiness,
            branch_mapping=disc.branch_mapping)
        afd.assert_no_bind_statement(render_discovery_report(report))
        afd.assert_no_bind_statement(render_l5_branch_mapping_report(disc.branch_mapping))
        afd.assert_no_bind_statement(adr.render_conclusions(disc.conclusions))
        afd.assert_no_bind_statement(adr.render_readiness_status(disc.readiness))


def test_a_report_that_somehow_contained_a_bind_would_be_refused():
    """The self-check has detection power: the same text with a real bind in it
    is refused by the same call path the renderer runs."""
    with pytest.raises(afd.FabricDiscoveryError) as exc:
        afd.assert_no_bind_statement(
            "## 1. INPUT RESOLUTION\n\nbind soc_top axi_if u_if (.*);\n")
    assert exc.value.args[0] == "BIND_STATEMENT_IN_DISCOVERY_ARTIFACT"
