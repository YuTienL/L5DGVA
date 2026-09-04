"""SYS-28..SYS-30: cross-subsystem address-map reconciliation, cross-subsystem
clock/reset comparison and the system-level scenario-model plan.

FIXTURES. Every address map, clock/reset fact and interrupt port below is
INVENTED for this file and describes no real DUT -- this harness repo
legitimately has no multi-subsystem project. The per-subsystem field blocks are
built through `subsystem_architecture_analysis`'s OWN `_field()`/`_unavailable()`
constructors rather than as hand-typed dicts, so a change to the shape SYS-6
really produces breaks these tests instead of letting the reader drift. The
command.txt bodies are imported from
`test_subsystem_architecture_and_command_contract` for the same reason the
SYS-23..27 suite imports them: three fixture shapes describing three different
imaginary DUTs is how a suite stops meaning anything.

WHAT THE HARD CASES ARE. A conflict detector proved only on a happy path is not
proved at all, so the suite deliberately carries: two subsystems whose DDR
windows overlap legitimately (SHARED_MEMORY, not a conflict), two whose
configuration blocks partially overlap with nothing explaining it
(ADDRESS_OVERLAP_CONFLICT, escalated into the real question queue), two
declaring the identical region twice (ADDRESS_OVERLAP_VALID), an overlap
computed on a base one subsystem's own register map already disputes (UNKNOWN,
with SHARED_MEMORY kept in also_matched so the second finding is not lost), one
clock name carrying two frequencies, one reset name carrying two polarities, a
CDC boundary, and -- as the control that gives every one of those detection
power -- a third subsystem that shares nothing and must come back INDEPENDENT
rather than swept into the same verdict.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import subsystem_architecture_analysis as saa
from dv_harness import subsystem_command_contract as scc
from dv_harness import system_command_plan as scp
from dv_harness import system_resource_inventory as sri
from dv_harness import system_resource_registry as srr
from dv_harness import system_scheduling_plan as ssp
from dv_harness import system_topology_analysis as sta
from dv_harness.uvm_generator import amba_fabric_generator as afg
from dv_harness_tests.test_subsystem_architecture_and_command_contract import (  # reused
    CONTENDING_CPU_SIDE_COMMANDS,
    CPU_SIDE_COMMANDS,
    READ_ONLY_COMMANDS,
    _write,
)

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Synthetic per-subsystem SYS-6 analysis
# ---------------------------------------------------------------------------

def _address_entry(name, base, size, *, bus=None, target=None,
                   agreement="AGREES", evidence=None):
    """One `dut_facts.address_map` entry, shaped exactly as
    env_manifest.schema.json's own item definition."""
    return {
        "name": name, "base_address": base, "size_bytes": size, "bus": bus,
        "target": target, "evidence": evidence or f"synthetic:{name}",
        "description": None, "register_map_agreement": agreement,
    }


def _address_field(entries, *, disagreements=0):
    return saa._field(
        saa.DERIVED,
        source="env.manifest.json dut_facts.address_map (synthetic test fixture)",
        entries=entries, disagreement_count=disagreements)


def _clock_reset_field(clocks, resets):
    return saa._field(
        saa.DERIVED,
        source="env.manifest.json dut_facts.clock_reset (synthetic test fixture)",
        clocks=clocks, resets=resets)


def _interrupt_field(rtl_ports=(), waits=()):
    return saa._field(
        saa.DERIVED,
        source="env.manifest.json dut_facts.rtl ports + command.txt interrupt waits",
        rtl_ports=list(rtl_ports), command_txt_waits=list(waits),
        basis="NAME_TOKEN_MATCH_ON_RTL_PORTS_AND_ON_WAIT_CONDITIONS")


def _rtl_irq(module, port):
    return {"module": module, "port": port, "direction": "output",
            "matched_tokens": ["irq"], "evidence": f"{module}.v (sha256 deadbeef1234)"}


#: PCIE_SS: an AXI-attached DDR window, an APB configuration block, a shared
#: control block, and an SRAM scratch region whose own register map DISAGREES
#: about its base.
PCIE_ADDRESS_ENTRIES = [
    _address_entry("ddr_mem", "0x80000000", 0x10000000, bus="axi",
                   evidence="PCIE_SS soc_arch_map.json:ddr_mem"),
    _address_entry("pcie_csr", "0x10000000", 0x1000, bus="apb",
                   evidence="PCIE_SS soc_arch_map.json:pcie_csr"),
    _address_entry("sys_ctrl", "0x20000000", 0x1000, bus="apb",
                   evidence="PCIE_SS soc_arch_map.json:sys_ctrl"),
    _address_entry("sram_scratch", "0x30000000", 0x1000, bus="axi",
                   agreement="DISAGREES",
                   evidence="PCIE_SS soc_arch_map.json:sram_scratch"),
]

#: USB_SS: a DDR BUFFER inside PCIE_SS's DDR window (legitimate sharing), a
#: configuration block that lands INSIDE PCIE_SS's (a real conflict), the same
#: sys_ctrl block, and a mirror of the disputed SRAM region.
USB_ADDRESS_ENTRIES = [
    _address_entry("ddr_buffer", "0x80000000", 0x8000000, bus="axi",
                   evidence="USB_SS soc_arch_map.json:ddr_buffer"),
    _address_entry("usb_csr", "0x10000800", 0x1000, bus="apb",
                   evidence="USB_SS soc_arch_map.json:usb_csr"),
    _address_entry("sys_ctrl", "0x20000000", 0x1000, bus="apb",
                   evidence="USB_SS soc_arch_map.json:sys_ctrl"),
    _address_entry("sram_scratch_mirror", "0x30000000", 0x800, bus="axi",
                   evidence="USB_SS soc_arch_map.json:sram_scratch_mirror"),
]

#: ETH_SS: the control. Its whole map sits somewhere nothing else touches, so
#: every cross-subsystem verdict against it must come back independent/disjoint
#: -- which is what makes the conflict verdicts above evidence of detection
#: power rather than of a classifier that fires on everything.
ETH_ADDRESS_ENTRIES = [
    _address_entry("eth_csr", "0x40000000", 0x1000, bus="apb",
                   evidence="ETH_SS soc_arch_map.json:eth_csr"),
]


def _analysis(*, include_eth=True, pcie_clock_reset=None, usb_clock_reset=None,
              usb_address_entries=None, usb_interrupts=None):
    per_subsystem = [
        {
            "subsystem_id": "PCIE_SS",
            "fields": {
                "address_map": _address_field(PCIE_ADDRESS_ENTRIES, disagreements=1),
                "clock_reset": pcie_clock_reset or _clock_reset_field(
                    [{"name": "core_clk", "frequency_mhz": 100.0, "source": "pll0",
                      "domain": "soc", "evidence": "PCIE_SS soc_arch_map.json:core_clk"},
                     {"name": "pcie_clk", "frequency_mhz": 250.0, "source": "pcie_pll",
                      "domain": "pcie", "evidence": "PCIE_SS soc_arch_map.json:pcie_clk"}],
                    [{"name": "por_rst_n", "active_level": "low", "synchronous": False,
                      "clock": "core_clk", "clock_resolved": "RESOLVED",
                      "evidence": "PCIE_SS soc_arch_map.json:por_rst_n"}]),
                "interrupts": _interrupt_field([_rtl_irq("pcie_top", "sys_irq")]),
            },
        },
        {
            "subsystem_id": "USB_SS",
            "fields": {
                "address_map": _address_field(
                    usb_address_entries if usb_address_entries is not None
                    else USB_ADDRESS_ENTRIES),
                "clock_reset": usb_clock_reset or _clock_reset_field(
                    [{"name": "core_clk", "frequency_mhz": 200.0, "source": "pll0",
                      "domain": "soc", "evidence": "USB_SS soc_arch_map.json:core_clk"},
                     {"name": "usb_clk", "frequency_mhz": 60.0, "source": "usb_pll",
                      "domain": "usb", "evidence": "USB_SS soc_arch_map.json:usb_clk"}],
                    [{"name": "por_rst_n", "active_level": "high", "synchronous": False,
                      "clock": "core_clk", "clock_resolved": "RESOLVED",
                      "evidence": "USB_SS soc_arch_map.json:por_rst_n"}]),
                "interrupts": usb_interrupts if usb_interrupts is not None
                else _interrupt_field(
                    [_rtl_irq("usb_top", "sys_irq")],
                    [{"line": 12, "condition": "top.dut.u_core.usb_done_irq",
                      "wait_class": "INTERRUPT_EVENT_WAIT", "matched_tokens": ["irq"],
                      "basis": "SIGNAL_NAME_TOKEN_MATCH", "hierarchy_roots": ["top"],
                      "evidence": "usb/command.txt:12"}]),
            },
        },
    ]
    if include_eth:
        per_subsystem.append({
            "subsystem_id": "ETH_SS",
            "fields": {
                "address_map": _address_field(ETH_ADDRESS_ENTRIES),
                "clock_reset": _clock_reset_field(
                    [{"name": "eth_clk", "frequency_mhz": 125.0, "source": "eth_pll",
                      "domain": "eth", "evidence": "ETH_SS soc_arch_map.json:eth_clk"}],
                    [{"name": "eth_rst_n", "active_level": "low", "synchronous": True,
                      "clock": "eth_clk", "clock_resolved": "RESOLVED",
                      "evidence": "ETH_SS soc_arch_map.json:eth_rst_n"}]),
                "interrupts": _interrupt_field([_rtl_irq("eth_top", "eth_irq")]),
            },
        })
    return {"subsystems": [r["subsystem_id"] for r in per_subsystem],
            "per_subsystem": per_subsystem}


def _clock_reset_agent_entry():
    """A SYS-15 registry entry, built against `srr.SYS15_FIELDS` itself so a
    field added to the requirement's own list cannot be missed here."""
    entry = {
        "resource_id": "SYSRES-CLKRST-0001",
        "resource_type": sri.RT_CLOCK_RESET_AGENT,
        "protocol": "AMBA4",
        "physical_hierarchy": "top.dut.u_clkrst",
        "role": "MASTER",
        "owner": f"{srr.OWNER_PROPOSED_SYSTEM_PREFIX}::{sri.RT_CLOCK_RESET_AGENT}",
        "consumer_subsystems": ["PCIE_SS", "USB_SS"],
        "active_passive": "ACTIVE",
        "shared": srr.SHARED_ACROSS_SUBSYSTEMS,
        "exclusive": sri.EXCLUSIVE_YES,
        "clock": "core_clk",
        "reset": "por_rst_n",
        "address_domain": srr.NOT_AVAILABLE,
        "source_environment": "synthetic",
        "source_config": "synthetic",
        "conflict_status": srr.CONFLICT_DRIVER,
        "reuse_decision": srr.BLOCKED,
        "evidence": ["PCIE_SS connectivity matrix", "USB_SS connectivity matrix"],
        "confidence": "MEDIUM",
        "member_resource_ids": ["PCIE_SS::clkrst", "USB_SS::clkrst"],
    }
    missing = [f for f in srr.SYS15_FIELDS if f not in entry]
    assert not missing, missing
    return entry


def _registry(entries=None, subsystems=("PCIE_SS", "USB_SS", "ETH_SS")):
    return {"entries": list(entries or []), "subsystems": list(subsystems)}


def _plans(tmp_path):
    """A real SYS-18..22 command plan and SYS-23..27 scheduling plan over
    synthetic command.txt files, built with the real builders -- SYS-30's block
    plan is only meaningful over relationships the real SYS-25 classifier
    decided."""
    contract_set = scc.build_contract_set({
        "PCIE_SS": [_write(tmp_path / "pcie_ss" / "command.txt", CPU_SIDE_COMMANDS)],
        "USB_SS": [_write(tmp_path / "usb_ss" / "command.txt",
                          CONTENDING_CPU_SIDE_COMMANDS)],
        "ETH_SS": [_write(tmp_path / "eth_ss" / "command.txt", READ_ONLY_COMMANDS)],
    })
    integration_plan = {"system_resource_registry": _registry()}
    selection = {"selected": ["ETH_SS", "PCIE_SS", "USB_SS"]}
    command_plan = scp.build_system_command_plan(
        integration_plan, contract_set, selection=selection)
    scheduling_plan = ssp.build_system_scheduling_plan(
        integration_plan, command_plan, selection=selection)
    return integration_plan, command_plan, scheduling_plan, selection


def _row(reconciliation, region_a, region_b):
    for row in reconciliation["overlaps"]:
        if {row["region_a"], row["region_b"]} == {region_a, region_b}:
            return row
    raise AssertionError(f"no overlap row for {region_a} x {region_b}: "
                         f"{[(r['region_a'], r['region_b']) for r in reconciliation['overlaps']]}")


def _cr_row(comparison, kind, name_a, name_b):
    rows = comparison["clock_comparisons" if kind == "CLOCK" else "reset_comparisons"]
    for row in rows:
        if {row["name_a"], row["name_b"]} == {name_a, name_b}:
            return row
    raise AssertionError(f"no {kind} row for {name_a} x {name_b}")


# ============================================================================
# Vocabulary held to the requirement's own sentences
# ============================================================================

def test_sys28_classes_match_the_requirements_own_sentence_one_to_one():
    """SYS-28: "Detect ADDRESS_OVERLAP_VALID / ADDRESS_OVERLAP_CONFLICT /
    SHARED_MEMORY / UNKNOWN.\""""
    assert sta.SYS28_OVERLAP_CLASSES == (
        "ADDRESS_OVERLAP_VALID", "ADDRESS_OVERLAP_CONFLICT", "SHARED_MEMORY", "UNKNOWN")


def test_sys28_range_kinds_cover_the_requirements_five_named_ranges():
    """SYS-28: "Determine register/memory/DMA/APB/AXI ranges"."""
    assert sta.SYS28_RANGE_KINDS[:5] == (
        sta.RANGE_REGISTER, sta.RANGE_MEMORY, sta.RANGE_DMA, sta.RANGE_APB, sta.RANGE_AXI)
    assert sta.SYS28_RANGE_KINDS[5] == sta.RANGE_UNCLASSIFIED


def test_sys28_precedence_is_a_permutation_with_unknown_first_and_conflict_last():
    assert sorted(sta.SYS28_PRECEDENCE) == sorted(sta.SYS28_OVERLAP_CLASSES)
    assert sta.SYS28_PRECEDENCE[0] == sta.ADDRESS_UNKNOWN
    assert sta.SYS28_PRECEDENCE[-1] == sta.ADDRESS_OVERLAP_CONFLICT


def test_sys29_keeps_source_frequency_polarity_and_sequencing_separate():
    """SYS-29: "Compare clock source/frequency, reset source/polarity/
    sequencing, CDC dependencies." Four distinct disagreements, four distinct
    verdicts -- collapsing them would name a pair without naming the fix."""
    for verdict in (sta.CONFLICTING_CLOCK_SOURCE, sta.CONFLICTING_CLOCK_FREQUENCY,
                    sta.CONFLICTING_RESET_POLARITY, sta.CONFLICTING_RESET_SEQUENCING,
                    sta.CDC_BOUNDARY):
        assert verdict in sta.SYS29_VERDICTS
    assert len(set(sta.SYS29_VERDICTS)) == len(sta.SYS29_VERDICTS) == 10
    assert sorted(sta.SYS29_CLOCK_PRECEDENCE) == sorted(set(sta.SYS29_CLOCK_PRECEDENCE))
    assert sorted(sta.SYS29_RESET_PRECEDENCE) == sorted(set(sta.SYS29_RESET_PRECEDENCE))


def test_vocabularies_match_the_json_schemas_enums():
    schema = json.loads(sta.SCHEMA_PATH.read_text(encoding="utf-8"))
    props = schema["properties"]
    overlap = (props["address_map_reconciliation"]["properties"]["overlaps"]["items"]
               ["properties"])
    assert sorted(overlap["verdict"]["enum"]) == sorted(sta.SYS28_OVERLAP_CLASSES)
    cr = schema["$defs"]["cr_rows"]["items"]["properties"]
    assert sorted(cr["verdict"]["enum"]) == sorted(sta.SYS29_VERDICTS)
    interrupts = (props["interrupt_map_reconciliation"]["properties"]["lines"]["items"]
                  ["properties"])
    assert sorted(interrupts["verdict"]["enum"]) == sorted(sta.SYS28_INTERRUPT_VERDICTS)
    ownership = (props["clock_reset_comparison"]["properties"]["ownership_proposals"]
                 ["items"]["properties"])
    assert sorted(ownership["proposal"]["enum"]) == sorted(sta.SYS29_OWNERSHIP_PROPOSALS)
    assert ownership["status"]["const"] == sta.OWNERSHIP_STATUS
    scenario = props["system_scenario_model"]["properties"]["scenarios"]["items"]["properties"]
    assert scenario["scenario_body_status"]["const"] == sta.SCENARIO_BODY_NOT_GENERATED
    assert sorted(scenario["block_plan"]["items"]["properties"]["block_kind"]["enum"]) == \
        sorted(sta.SYS30_BLOCK_KINDS)


def test_no_second_address_or_overlap_arithmetic_is_defined_here():
    """REUSE-FIRST, checked rather than asserted in a comment. This module must
    not carry its own address parser, its own interval comparison or its own
    conflict resolver -- `amba_fabric_generator` and `source_authority` own
    those, and a second copy is what this project has repeatedly caught as a
    real defect."""
    import re

    text = open(sta.__file__, encoding="utf-8").read()
    # No re-implemented base-16/base-0 address parsing: parse_addr owns it.
    assert not re.search(r"\bint\([^)]*,\s*(?:0|16)\)", text)
    assert "afg.parse_addr(" in text
    # The overlap DECISION goes through the existing function, by name -- the
    # module must not carry its own `start < end` interval comparison.
    assert "afg.compute_address_regions(" in text
    assert '["start"] <' not in text and '["end"] >' not in text
    # No second conflict resolver: escalation goes through source_authority.
    assert "sa.resolve_conflict(" in text
    assert "def resolve_conflict" not in text
    # No second registry builder, command IR, collision detector or pair
    # relationship classifier either -- SYS-15..27 own all four.
    for forbidden in ("def build_system_resource_registry", "def build_system_command_ir",
                      "def detect_command_collisions",
                      "def classify_parallelism_relationships"):
        assert forbidden not in text


# ============================================================================
# SYS-28 -- ADDRESS MAP ANALYSIS
# ============================================================================

def test_two_memory_windows_that_overlap_are_shared_memory_not_a_conflict():
    reconciliation = sta.reconcile_address_maps(_analysis())
    row = _row(reconciliation, "ddr_mem", "ddr_buffer")
    assert row["verdict"] == sta.SHARED_MEMORY
    assert row["range_kind_a"] == row["range_kind_b"] == sta.RANGE_MEMORY
    assert row["intersection_start"] == "0x80000000"
    assert row["intersection_end"] == "0x88000000"
    assert not row["escalation_required"]


def test_two_configuration_blocks_that_partially_overlap_are_a_conflict():
    reconciliation = sta.reconcile_address_maps(_analysis())
    row = _row(reconciliation, "pcie_csr", "usb_csr")
    assert row["verdict"] == sta.ADDRESS_OVERLAP_CONFLICT
    assert row["escalation_required"]
    assert row["intersection_start"] == "0x10000800"
    assert "0x10000800" in row["basis"]
    # both sides' own evidence is carried, which is what makes the escalation
    # answerable by whoever receives it
    assert any("PCIE_SS" in e for e in row["evidence"])
    assert any("USB_SS" in e for e in row["evidence"])


def test_the_identical_region_declared_twice_is_a_valid_overlap():
    reconciliation = sta.reconcile_address_maps(_analysis())
    rows = [r for r in reconciliation["overlaps"]
            if r["region_a"] == r["region_b"] == "sys_ctrl"]
    assert rows, "the block both subsystems declare should produce a row"
    assert all(r["verdict"] == sta.ADDRESS_OVERLAP_VALID for r in rows)
    assert all(not r["escalation_required"] for r in rows)


def test_an_overlap_on_a_disputed_base_is_unknown_and_keeps_the_second_finding():
    """The case most easily got wrong: an overlap computed on top of a base
    that one subsystem's own register map already reports as DISAGREES is a
    finding about that subsystem's two artifacts, not about this pair. It must
    not be reported as a cross-subsystem conflict -- and the shared-memory
    reading it ALSO matched must survive in also_matched rather than being
    silently dropped."""
    reconciliation = sta.reconcile_address_maps(_analysis())
    row = _row(reconciliation, "sram_scratch", "sram_scratch_mirror")
    assert row["verdict"] == sta.ADDRESS_UNKNOWN
    assert row["from_field"] == "register_map_agreement"
    assert sta.SHARED_MEMORY in row["also_matched"]
    assert "DISAGREES" in row["basis"]
    assert row["escalation_required"]


def test_a_subsystem_that_shares_nothing_produces_no_overlap_row_at_all():
    """The control. Without it, every verdict above could be a classifier that
    fires on any pair it is handed."""
    reconciliation = sta.reconcile_address_maps(_analysis())
    involved = {s for r in reconciliation["overlaps"]
                for s in (r["subsystem_a"], r["subsystem_b"])}
    assert "ETH_SS" not in involved
    assert reconciliation["summary"]["disjoint_pairs"] > 0


def test_the_overlap_decision_is_the_existing_functions_not_a_second_one():
    """The probe's answer must agree with `compute_address_regions()` called
    directly on the same two regions -- i.e. the exclusive-end convention
    (`cur.start < prev.end`) is REUSED, not re-derived. Two perfectly adjacent
    regions are NOT an overlap, which is exactly where a hand-written
    comparison usually gets it wrong."""
    adjacent = [
        _address_entry("a_lo", "0x50000000", 0x1000),
        _address_entry("b_hi", "0x50001000", 0x1000),
    ]
    analysis = _analysis(include_eth=False, usb_address_entries=adjacent)
    reconciliation = sta.reconcile_address_maps(analysis)
    pairs = {(r["region_a"], r["region_b"]) for r in reconciliation["overlaps"]}
    assert ("a_lo", "b_hi") not in pairs and ("b_hi", "a_lo") not in pairs
    with pytest.raises(afg.AddressMapError) as excinfo:
        afg.compute_address_regions(
            [{"id": "a_lo", "base_addr": 0x50000000, "size": 0x1000},
             {"id": "b_hi", "base_addr": 0x50001000, "size": 0x1000}],
            [], sta.PROBE_ADDR_WIDTH)
    assert excinfo.value.reason == "ADDRESS_MAP_NOT_FULL_COVERAGE"  # not OVERLAP


def test_an_unparseable_region_is_unknown_and_never_silently_dropped():
    broken = [{"name": "bad_region", "base_address": "not-an-address",
               "size_bytes": 0x1000, "bus": "apb", "target": None, "evidence": "x",
               "description": None, "register_map_agreement": "NOT_AVAILABLE"}]
    analysis = _analysis(include_eth=False, usb_address_entries=broken)
    reconciliation = sta.reconcile_address_maps(analysis)
    rows = [r for r in reconciliation["overlaps"] if r["region_b"] == "bad_region"
            or r["region_a"] == "bad_region"]
    assert rows, "an unreadable region must still be reported, not omitted"
    assert all(r["verdict"] == sta.ADDRESS_UNKNOWN for r in rows)
    assert all(r["probe_reason"] == "NOT_PROBED_UNPARSEABLE_REGION" for r in rows)


def test_a_subsystem_whose_own_map_overlaps_itself_is_reported_separately():
    """An intra-subsystem defect is `compute_address_regions()`'s verdict and
    belongs in that subsystem's own self_consistency block, never mixed into
    the cross-subsystem table."""
    self_overlapping = [
        _address_entry("win_a", "0x60000000", 0x2000),
        _address_entry("win_b", "0x60001000", 0x2000),
    ]
    analysis = _analysis(include_eth=False, usb_address_entries=self_overlapping)
    reconciliation = sta.reconcile_address_maps(analysis)
    consistency = reconciliation["per_subsystem"]["USB_SS"]["self_consistency"]
    assert consistency["self_overlap"] is True
    assert consistency["verdict"] == "ADDRESS_MAP_OVERLAP"
    assert reconciliation["summary"]["subsystems_with_self_overlap"] == ["USB_SS"]


def test_a_conflict_is_escalated_into_the_real_question_queue(tmp_path):
    """Through `source_authority.escalate_conflict()` -- the same channel
    address_map_verifier and system_command_plan already use, not a second
    escalation mechanism. Both sides are the same authority tier, so the
    verdict is UNDECIDABLE_SAME_AUTHORITY and a human is asked."""
    from dv_harness import question_queue

    store = question_queue.QuestionQueueStore(tmp_path)
    reconciliation = sta.reconcile_address_maps(_analysis(), question_store=store)
    assert reconciliation["summary"]["escalations_filed"] >= 1
    questions = store.list_questions()
    texts = " ".join(json.dumps(q) for q in questions)
    assert "pcie_csr" in texts and "usb_csr" in texts
    # Idempotent: re-running the same detector over unchanged sources must not
    # grow the queue.
    before = len(questions)
    sta.reconcile_address_maps(_analysis(), question_store=store)
    assert len(store.list_questions()) == before


def test_nothing_is_relocated_and_no_address_map_is_modified():
    reconciliation = sta.reconcile_address_maps(_analysis())
    assert reconciliation["summary"]["regions_relocated"] == 0
    assert reconciliation["summary"]["address_maps_modified"] == 0


# ============================================================================
# SYS-28 -- interrupt mapping
# ============================================================================

def test_an_interrupt_line_named_by_two_subsystems_is_shared():
    interrupts = sta.reconcile_interrupt_maps(_analysis())
    shared = [r for r in interrupts["lines"] if r["line"] == "sys_irq"]
    assert len(shared) == 1
    assert shared[0]["verdict"] == sta.INTERRUPT_LINE_SHARED
    assert shared[0]["subsystems"] == ["PCIE_SS", "USB_SS"]
    # shared, not "conflicting": whether both DRIVE it is SYS-10/SYS-15's
    # question and is deliberately not re-answered here
    assert "SYS-10/SYS-15" in shared[0]["reason"]


def test_a_command_txt_interrupt_wait_is_matched_by_signal_not_by_full_path():
    interrupts = sta.reconcile_interrupt_maps(_analysis())
    lines = {r["line"] for r in interrupts["lines"]}
    assert "usb_done_irq" in lines
    assert not any("top.dut" in line for line in lines)


def test_a_subsystem_without_interrupt_evidence_is_named_not_assumed_empty():
    no_evidence = saa._unavailable(
        "env.manifest.json dut_facts.rtl ports + command.txt interrupt waits",
        "no RTL parse and no command.txt for this subsystem",
        rtl_ports=[], command_txt_waits=[])
    interrupts = sta.reconcile_interrupt_maps(
        _analysis(include_eth=False, usb_interrupts=no_evidence))
    assert interrupts["summary"]["subsystems_without_interrupt_evidence"] == ["USB_SS"]


# ============================================================================
# SYS-29 -- CLOCK / RESET INTEGRATION
# ============================================================================

def test_one_clock_name_with_two_frequencies_is_a_frequency_conflict():
    comparison = sta.compare_clock_reset_domains(
        _analysis(), address_reconciliation=sta.reconcile_address_maps(_analysis()))
    row = _cr_row(comparison, "CLOCK", "core_clk", "core_clk")
    assert row["verdict"] == sta.CONFLICTING_CLOCK_FREQUENCY
    assert row["from_field"] == "frequency_mhz"
    assert sta.SAME_CLOCK_DOMAIN in row["also_matched"]
    assert "100" in row["basis"] and "200" in row["basis"]


def test_one_reset_name_with_two_polarities_is_a_polarity_conflict():
    comparison = sta.compare_clock_reset_domains(_analysis())
    row = _cr_row(comparison, "RESET", "por_rst_n", "por_rst_n")
    assert row["verdict"] == sta.CONFLICTING_RESET_POLARITY
    assert row["from_field"] == "active_level"


def test_two_domains_sharing_an_address_range_are_a_cdc_boundary():
    address = sta.reconcile_address_maps(_analysis())
    comparison = sta.compare_clock_reset_domains(
        _analysis(), address_reconciliation=address)
    row = _cr_row(comparison, "CLOCK", "pcie_clk", "usb_clk")
    assert row["verdict"] == sta.CDC_BOUNDARY
    assert row["shared_address_pairs"], "the CDC verdict must cite the SYS-28 rows"


def test_two_domains_sharing_nothing_are_independent_not_a_cdc_boundary():
    """The control that gives CDC_BOUNDARY detection power. ETH_SS shares no
    address range with anyone, so its clock must come back INDEPENDENT."""
    address = sta.reconcile_address_maps(_analysis())
    comparison = sta.compare_clock_reset_domains(
        _analysis(), address_reconciliation=address)
    eth_rows = [r for r in comparison["clock_comparisons"]
                if "ETH_SS" in (r["subsystem_a"], r["subsystem_b"])]
    assert eth_rows
    assert all(r["verdict"] == sta.INDEPENDENT_CLOCK_DOMAIN for r in eth_rows)
    assert all(not r["shared_address_pairs"] for r in eth_rows)


def test_a_subsystem_with_no_clock_reset_evidence_is_unknown_not_compatible():
    unavailable = saa._unavailable(
        "env.manifest.json dut_facts.clock_reset",
        "clock_reset layer NOT_AVAILABLE", clocks=[], resets=[])
    comparison = sta.compare_clock_reset_domains(
        _analysis(include_eth=False, usb_clock_reset=unavailable))
    assert comparison["summary"]["by_verdict"][sta.CLOCK_RESET_UNKNOWN] >= 1
    computed = sta.clock_reset_compatibility_input(comparison)
    assert computed["computed_value"] == "UNKNOWN"


def test_duplicate_clock_reset_agents_are_read_from_the_registry_not_re_derived():
    comparison = sta.compare_clock_reset_domains(
        _analysis(), registry=_registry([_clock_reset_agent_entry()]))
    agents = comparison["clock_reset_agents"]
    assert len(agents) == 1
    assert agents[0]["duplicate"] is True
    assert agents[0]["conflict_status"] == srr.CONFLICT_DRIVER
    assert "not re-derived here" in agents[0]["source"]
    assert comparison["summary"]["duplicate_clock_reset_agents"] == 1
    assert comparison["summary"]["conflicting_clock_reset_agents"] == 1


def test_a_shared_clock_is_a_system_ownership_candidate_and_a_local_one_is_not():
    comparison = sta.compare_clock_reset_domains(_analysis())
    by_name = {(r["kind"], r["name"]): r for r in comparison["ownership_proposals"]}
    assert by_name[("CLOCK", "core_clk")]["proposal"] == sta.OWNERSHIP_SYSTEM_GLOBAL_CANDIDATE
    assert by_name[("CLOCK", "eth_clk")]["proposal"] == sta.OWNERSHIP_SUBSYSTEM_LOCAL
    # a proposal, never a move
    assert all(r["status"] == sta.OWNERSHIP_STATUS
               for r in comparison["ownership_proposals"])
    assert comparison["summary"]["clocks_or_resets_modified"] == 0


def test_the_clock_reset_compatibility_field_becomes_a_computed_value():
    """The real computation behind the self-attested string
    system_level_composition_gate.py currently takes on trust -- offered as an
    input, never wired into the gate here."""
    comparison = sta.compare_clock_reset_domains(_analysis())
    computed = sta.clock_reset_compatibility_input(comparison)
    assert computed["field"] == "clock_reset_compatibility"
    assert computed["computed_value"] == "FAIL"
    assert computed["gate_wired"] is False
    assert "PCIE_SS|USB_SS" in comparison["summary"]["conflicting_pairs"]


def test_a_clean_selection_computes_pass_rather_than_always_failing():
    """Detection power for the FAIL above: a selection whose clocks and resets
    agree must compute PASS."""
    agreeing = _clock_reset_field(
        [{"name": "core_clk", "frequency_mhz": 100.0, "source": "pll0",
          "domain": "soc", "evidence": "USB_SS soc_arch_map.json:core_clk"}],
        [{"name": "por_rst_n", "active_level": "low", "synchronous": False,
          "clock": "core_clk", "clock_resolved": "RESOLVED",
          "evidence": "USB_SS soc_arch_map.json:por_rst_n"}])
    comparison = sta.compare_clock_reset_domains(
        _analysis(include_eth=False, usb_clock_reset=agreeing))
    computed = sta.clock_reset_compatibility_input(comparison)
    assert computed["computed_value"] == "PASS"
    assert comparison["summary"]["conflicts"] == 0


# ============================================================================
# SYS-30 -- SYSTEM-LEVEL SCENARIO MODEL
# ============================================================================

def test_a_scenario_plan_never_emits_a_body_or_a_system_command_txt(tmp_path):
    _, command_plan, scheduling_plan, _ = _plans(tmp_path)
    model = sta.plan_system_scenario_model(command_plan, scheduling_plan)
    assert model["summary"]["scenario_bodies_generated"] == 0
    assert model["summary"]["system_command_txt_written"] == 0
    for scenario in model["scenarios"]:
        assert scenario["scenario_body_status"] == sta.SCENARIO_BODY_NOT_GENERATED
        for forbidden in ("scenario_body", "command_txt", "generated_source"):
            assert forbidden not in scenario


def test_every_planned_command_comes_from_a_real_subsystem_contract(tmp_path):
    """SYS-30: "Derive syntax from existing subsystem semantics rather than
    forcing a new language.\""""
    _, command_plan, scheduling_plan, _ = _plans(tmp_path)
    model = sta.plan_system_scenario_model(command_plan, scheduling_plan)
    real_ids = {e["system_command_id"]
                for e in command_plan["system_command_ir"]["entries"]}
    for scenario in model["scenarios"]:
        derivation = scenario["syntax_derivation"]
        assert derivation["derived_from_existing_subsystem_semantics"] is True
        assert derivation["invented_command_count"] == 0
        assert derivation["new_language_introduced"] is False
        for block in scenario["block_plan"]:
            for member in block["members"]:
                assert member["system_command_id"] in real_ids


def test_the_only_proposed_keywords_are_the_two_block_markers(tmp_path):
    _, command_plan, scheduling_plan, _ = _plans(tmp_path)
    model = sta.plan_system_scenario_model(command_plan, scheduling_plan)
    for scenario in model["scenarios"]:
        keywords = scenario["syntax_derivation"]["proposed_keywords"]
        assert tuple(k["keyword"] for k in keywords) == sta.PROPOSED_SCENARIO_KEYWORDS
        assert all(k["status"] == sta.PROPOSED_KEYWORD_STATUS for k in keywords)


def test_two_commands_of_one_subsystem_are_never_planned_in_one_parallel_block(tmp_path):
    """A command.txt is sequential by construction, so its own order is already
    stated; planning two of its commands as concurrent would be this layer
    re-ordering a file it does not own."""
    _, command_plan, scheduling_plan, _ = _plans(tmp_path)
    model = sta.plan_system_scenario_model(command_plan, scheduling_plan)
    for scenario in model["scenarios"]:
        for block in scenario["block_plan"]:
            if block["block_kind"] != sta.BLOCK_PARALLEL:
                continue
            subsystems = [m["subsystem"] for m in block["members"]]
            assert len(subsystems) == len(set(subsystems)), block


def test_a_non_parallel_safe_pair_closes_the_block_and_says_why(tmp_path):
    """The SYS-25 relationships are CONSUMED, not re-decided: a block boundary
    must cite the relationship that caused it."""
    _, command_plan, scheduling_plan, _ = _plans(tmp_path)
    model = sta.plan_system_scenario_model(command_plan, scheduling_plan)
    boundaries = [b for s in model["scenarios"] for b in s["block_plan"]
                  if "cannot join the preceding block" in b["basis"]]
    assert boundaries, "the contending fixtures must produce at least one boundary"
    known = set(ssp.SYS25_RELATIONSHIPS) | {"SAME_SUBSYSTEM_COMMAND_TXT_IS_SEQUENTIAL"}
    for block in boundaries:
        assert any(rel in block["basis"] for rel in known), block["basis"]


def test_every_scenario_names_at_least_two_subsystems_or_says_the_gate_would_refuse(
        tmp_path):
    _, command_plan, scheduling_plan, _ = _plans(tmp_path)
    model = sta.plan_system_scenario_model(command_plan, scheduling_plan)
    for scenario in model["scenarios"]:
        if len(scenario["participating_subsystems"]) < 2:
            assert "NOT_CROSS_SUBSYSTEM_SCENARIO" in scenario["composition_gate_note"]
        else:
            assert scenario["cross_subsystem"] is True


# ============================================================================
# Composition, guards and reporting
# ============================================================================

def test_the_full_document_validates_against_the_real_schema(tmp_path):
    integration_plan, command_plan, scheduling_plan, selection = _plans(tmp_path)
    document = sta.build_system_topology_analysis(
        _analysis(), integration_plan, command_plan, scheduling_plan,
        selection=selection)
    sta.validate_system_topology_analysis(document)
    assert document["summary"]["address_conflicts"] == 1
    assert document["summary"]["shared_memory_windows"] == 1
    assert document["summary"]["clock_reset_conflicts"] >= 1
    assert document["summary"]["topology_clean"] is False


def test_a_clean_selection_reports_topology_clean(tmp_path):
    """Detection power for `topology_clean`: it must be reachable as True, or
    it is a constant dressed up as a verdict."""
    integration_plan, command_plan, scheduling_plan, selection = _plans(tmp_path)
    clean = _analysis(
        include_eth=False,
        usb_address_entries=[_address_entry("usb_only", "0x70000000", 0x1000, bus="apb")],
        usb_clock_reset=_clock_reset_field(
            [{"name": "usb_clk", "frequency_mhz": 60.0, "source": "usb_pll",
              "domain": "usb", "evidence": "USB_SS:usb_clk"}],
            [{"name": "usb_rst_n", "active_level": "low", "synchronous": True,
              "clock": "usb_clk", "clock_resolved": "RESOLVED",
              "evidence": "USB_SS:usb_rst_n"}]))
    document = sta.build_system_topology_analysis(
        clean, integration_plan, command_plan, scheduling_plan, selection=selection)
    sta.validate_system_topology_analysis(document)
    assert document["summary"]["address_conflicts"] == 0
    assert document["summary"]["topology_clean"] is True


def test_assert_no_emitted_artifacts_actually_catches_a_violation(tmp_path):
    integration_plan, command_plan, scheduling_plan, selection = _plans(tmp_path)
    document = sta.build_system_topology_analysis(
        _analysis(), integration_plan, command_plan, scheduling_plan,
        selection=selection)

    generated = json.loads(json.dumps(document))
    generated["artifacts_generated"] = ["system_command.txt"]
    with pytest.raises(sta.SystemTopologyAnalysisError) as excinfo:
        sta.assert_no_emitted_artifacts(generated)
    assert excinfo.value.reason == "ARTIFACT_GENERATION_ATTEMPTED"

    if document["system_scenario_model"]["scenarios"]:
        bodied = json.loads(json.dumps(document))
        bodied["system_scenario_model"]["scenarios"][0]["scenario_body"] = "fork ... join"
        with pytest.raises(sta.SystemTopologyAnalysisError) as excinfo:
            sta.assert_no_emitted_artifacts(bodied)
        assert excinfo.value.reason == "SCENARIO_BODY_GENERATED"

    owned = json.loads(json.dumps(document))
    proposals = owned["clock_reset_comparison"]["ownership_proposals"]
    if proposals:
        proposals[0]["status"] = "IMPLEMENTED"
        with pytest.raises(sta.SystemTopologyAnalysisError) as excinfo:
            sta.assert_no_emitted_artifacts(owned)
        assert excinfo.value.reason == "CLOCK_RESET_OWNERSHIP_IMPLEMENTED"


def test_the_composer_boundary_is_still_intact(tmp_path):
    """SYS-26/27's three NotImplementedError stubs must still raise: this build
    plans about them and never fills them in."""
    integration_plan, command_plan, scheduling_plan, selection = _plans(tmp_path)
    document = sta.build_system_topology_analysis(
        _analysis(), integration_plan, command_plan, scheduling_plan,
        selection=selection)
    assert document["composer_boundary"]["boundary_intact"] is True


def test_the_report_renders_every_section_with_the_real_numbers(tmp_path):
    integration_plan, command_plan, scheduling_plan, selection = _plans(tmp_path)
    document = sta.build_system_topology_analysis(
        _analysis(), integration_plan, command_plan, scheduling_plan,
        selection=selection)
    report = sta.format_system_topology_report(document)
    assert "SYS-28 ADDRESS MAP ANALYSIS" in report
    assert "SYS-29 CLOCK / RESET INTEGRATION" in report
    assert "SYS-30 SYSTEM-LEVEL SCENARIO MODEL" in report
    assert sta.ADDRESS_OVERLAP_CONFLICT in report
    assert sta.SHARED_MEMORY in report
    assert sta.CONFLICTING_RESET_POLARITY in report
    assert "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED" in report


# ============================================================================
# The real CLI front door
# ============================================================================

def _synthetic_project(tmp_path):
    """A real project tree the SYS-1 selection gate admits. Reused wholesale
    from the SYS-18..22 suite rather than rebuilt, so the CLI layers of
    SYS-18..22, SYS-23..27 and SYS-28..30 cannot drift into three project-tree
    shapes."""
    from dv_harness_tests.test_system_command_plan import _synthetic_project as build
    return build(tmp_path)


def _snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _run_cli(tmp_path, *extra):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp_path),
         "system-topology-analysis", *extra],
        cwd=str(ROOT), capture_output=True, text=True)


def test_the_cli_refuses_an_empty_selection_through_sys1(tmp_path):
    """SYS-1's explicit-selection refusal is not bypassed by adding a verb on
    top of the stack. An empty analysis must read as "nothing was selected",
    never as "these subsystems have no address or clock conflict"."""
    _synthetic_project(tmp_path)
    proc = _run_cli(tmp_path)
    assert proc.returncode == 2, proc.stderr
    assert "NO_EXPLICIT_SELECTION" in proc.stdout
    assert "no cross-subsystem address overlap in this selection" in proc.stdout


def test_the_cli_reports_the_analysis_and_writes_no_system_level_artifact(tmp_path):
    """The real end-to-end path: a real subprocess through the whole
    SYS-1 -> SYS-30 stack, and both subsystem environments byte-identical
    afterwards. This is the check that matters most for this layer -- an
    analysis pass that quietly wrote a System command.txt or touched a
    subsystem environment would be exactly the SYS-40 crossing SYS-39 forbids.
    """
    a, b = _synthetic_project(tmp_path)
    before = {**_snapshot(a), **_snapshot(b)}
    proc = _run_cli(tmp_path, "--select", "SUBSYS_A", "--select", "SUBSYS_B")
    assert proc.returncode in (0, 2), proc.stderr
    assert "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED" in proc.stdout
    assert "SYS-28 ADDRESS MAP ANALYSIS" in proc.stdout
    assert "SYS-29 CLOCK / RESET INTEGRATION" in proc.stdout
    assert "SYS-30 SYSTEM-LEVEL SCENARIO MODEL" in proc.stdout
    assert sta.SCENARIO_BODY_NOT_GENERATED in proc.stdout
    assert {**_snapshot(a), **_snapshot(b)} == before
    for forbidden in ("system_command.txt", "soc_command.txt", "system_scoreboard.sv",
                      "system_virtual_sequencer.sv", "system_address_decoder.sv"):
        assert not list(tmp_path.rglob(forbidden)), forbidden
    for path in tmp_path.rglob("*.sv"):
        assert path.read_text(encoding="utf-8") == (
            "// synthetic fixture, empty on purpose\n"), path
