"""Tests for SYS-15..SYS-17 of the System-Level Verification Integration
workflow: `dv_harness/system_resource_registry.py` -- the SYSTEM_RESOURCE_
REGISTRY, the SUBSYSTEM INTEGRATION MATRIX and the VIP/AGENT DEDUPLICATION
MATRIX.

EVERY fixture is SYNTHETIC and built inside a tmp_path. The subsystem builders
are IMPORTED from `test_system_resource_inventory` rather than copied, so the
SYS-9..14 layer these tests sit on and the SYS-9..14 layer its own tests
exercise cannot drift apart into two different fixture shapes. Nothing touches
the real `.dv-harness/soc-composer/subsystem_environment_registry.json`
(legitimately absent in this repo) and no test writes the real
`system_resource_registry.json` -- every persistence test writes into
tmp_path.

No test generates System-Level UVM source, a System command.txt, a System
Virtual Sequencer, a shared agent or command routing, and four tests assert
that rather than trusting it.

The suite is deliberately not a happy path. A registry/dedup mechanism whose
only coverage is the case where everything agrees has no detection power, so
the cases that carry this suite are the conflicting and ambiguous ones:

  * two subsystems both driving one ACTIVE CPU AXI Master (each subsystem's
    own connectivity self-check passes) -> ONE registry entry, BLOCKED;
  * the same pair with one side PASSIVE -> REUSE_SHARED with a PROPOSED
    System owner;
  * the same physical resource configured differently -> RECONFIGURE;
  * a THIRD subsystem joining the same physical resource -> still one entry
    (identity is transitive), three consumers;
  * two PASSIVE monitors -> PASSIVE_ONLY, never REUSE_SHARED;
  * two subsystems whose SoC address ranges genuinely overlap;
  * a subsystem-specific PCIe VIP pair -> KEEP_INDEPENDENT, never promoted;
  * two ACTIVE rows inside ONE subsystem's own matrix -> a BLOCKED row in
    SYS-17's table with the same subsystem in both columns;
  * a clean pair on a resource that is stopped by a DIFFERENT conflict ->
    BLOCKED, so one clean pair cannot launder a stopped resource.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import connectivity as conn
from dv_harness import inference
from dv_harness import subsystem_discovery as sd
from dv_harness import system_resource_inventory as sri
from dv_harness import system_resource_registry as srr
from dv_harness_tests.test_system_resource_inventory import (  # synthetic builders, reused
    CPU_SIDE_COMMANDS,
    SHARED_CPU_BIND,
    _matrix_row,
    _registered_env,
    _subsystem_sources,
    _two_subsystems_sharing_one_cpu_master,
    _write,
    MASTER_ROLE,
)

ROOT = Path(__file__).resolve().parents[1]


def _plan(sources, *, selection=None, synthesis=None, contract_set=None):
    analysis = sri.build_cross_subsystem_resource_analysis(
        list(sources), contract_set=contract_set)
    return analysis, srr.build_system_integration_plan(
        analysis, selection=selection, synthesis=synthesis)


def _only_entry(plan):
    entries = plan["system_resource_registry"]["entries"]
    assert len(entries) == 1, [e["resource_id"] for e in entries]
    return entries[0]


# ============================================================================
# Drift guards: the requirement's own lists, held against the code
# ============================================================================

# Copied verbatim from the master prompt, SYS-15's "Create or extend a registry
# with:" sentence.
SYS15_REQUIREMENT_TEXT = (
    "resource_id, resource_type, protocol, physical_hierarchy, role, owner, "
    "consumer_subsystems, active_passive, shared, exclusive, clock, reset, "
    "address_domain, source_environment, source_config, conflict_status, "
    "reuse_decision, evidence, confidence")

# Copied verbatim from SYS-16's mandatory table header row.
SYS16_REQUIREMENT_TEXT = (
    "Subsystem | Environment | command.txt | Readiness | VIPs | Scoreboard | "
    "Shared Resources | Conflicts | Integration Status")

# Copied verbatim from SYS-17's mandatory table header row.
SYS17_REQUIREMENT_TEXT = (
    "Resource | Subsystem A | Subsystem B | Physical Interface | Relationship | "
    "Active Driver Conflict | Decision | System Owner")

# Copied verbatim from SYS-17's "Decision:" sentence.
SYS17_DECISION_TEXT = (
    "REUSE_SHARED / KEEP_INDEPENDENT / PASSIVE_ONLY / RECONFIGURE / "
    "MERGE_ACCESS_PATH / BLOCKED / UNKNOWN")


def test_sys15_fields_match_the_requirements_own_list_one_to_one():
    """Nineteen fields, not eighteen -- counted off the requirement's own
    sentence. A summary that says otherwise is wrong about the document."""
    items = SYS15_REQUIREMENT_TEXT.split(", ")
    assert len(items) == len(srr.SYS15_FIELDS) == 19
    assert tuple(items) == srr.SYS15_FIELDS


def test_sys16_columns_are_exactly_the_requirements_own_nine():
    items = tuple(c.strip() for c in SYS16_REQUIREMENT_TEXT.split("|"))
    assert items == srr.SYS16_COLUMNS
    assert len(items) == 9


def test_sys17_columns_are_exactly_the_requirements_own_eight():
    items = tuple(c.strip() for c in SYS17_REQUIREMENT_TEXT.split("|"))
    assert items == srr.SYS17_COLUMNS
    assert len(items) == 8


def test_sys17_decision_vocabulary_is_closed_and_verbatim():
    items = tuple(d.strip() for d in SYS17_DECISION_TEXT.split("/"))
    assert items == srr.SYS17_DECISIONS
    # Every decision has a severity, and every severity is a decision -- the
    # entry-level fold cannot silently ignore a value.
    assert set(srr.DECISION_SEVERITY) == set(srr.SYS17_DECISIONS)
    assert len(set(srr.DECISION_SEVERITY.values())) == len(srr.SYS17_DECISIONS)


def test_sys15_fields_match_the_json_schema_required_list():
    schema = json.loads((ROOT / "dv_harness" / "schemas"
                         / "system_resource_registry.schema.json").read_text(encoding="utf-8"))
    required = schema["properties"]["entries"]["items"]["required"]
    assert tuple(required) == srr.SYS15_FIELDS


def test_sys17_decision_vocabulary_matches_the_json_schema_enum():
    schema = json.loads((ROOT / "dv_harness" / "schemas"
                         / "system_resource_registry.schema.json").read_text(encoding="utf-8"))
    enum = schema["properties"]["entries"]["items"]["properties"]["reuse_decision"]["enum"]
    assert tuple(enum) == srr.SYS17_DECISIONS


def test_confidence_uses_the_one_existing_scorer_not_a_second_vocabulary():
    """`dv_harness_tests/test_confidence_vocabulary_separation.py` exists to
    stop another confidence-ish mechanism appearing; this holds SYS-15 to the
    same rule from the other side."""
    assert srr.inference is inference
    src = (ROOT / "dv_harness" / "system_resource_registry.py").read_text(encoding="utf-8")
    assert "inference.score_confidence(" in src
    assert '"HIGH" if' not in src and "CONFIDENCE_LEVELS = " not in src


def test_no_second_relationship_classifier_or_conflict_rule_is_defined_here():
    """SYS-15..17 must COMPOSE SYS-9..14, not restate it. A second copy of the
    relationship table or the conflict rule is exactly the duplicate-mechanism
    failure this project has been bitten by before."""
    src = (ROOT / "dv_harness" / "system_resource_registry.py").read_text(encoding="utf-8")
    for forbidden in ("def classify_resource_relationship",
                      "def apply_active_driver_conflict_rule",
                      "def evaluate_shared_vip_promotion",
                      "def compare_resources",
                      "def detect_duplicate_resources"):
        assert forbidden not in src, forbidden
    # And the relationship/promotion vocabularies are IMPORTED, never respelled.
    assert 'REL_SAME_PHYSICAL = ' not in src
    assert srr.MERGING_RELATIONSHIPS <= set(sri.RELATIONSHIP_CLASSES)


# ============================================================================
# SYS-15: the registry is a DIFFERENT granularity from the subsystem registry
# ============================================================================

def test_the_subsystem_registry_template_is_still_six_field_subsystem_granularity():
    """The claim this whole module rests on, re-verified against the real file
    rather than cited: the existing registry is one row per ENVIRONMENT with
    identity/qualification metadata, and has no resource-level field at all."""
    from tools.real_env import system_level_validator as slv
    assert set(slv.REQUIRED) == {
        "name", "environment_manifest", "release_sha", "qualification_state",
        "interface_compatibility", "clock_reset_compatibility"}
    for resource_field in ("resource_id", "consumer_subsystems", "physical_hierarchy",
                           "reuse_decision", "conflict_status"):
        assert resource_field not in slv.REQUIRED
    template = json.loads((ROOT / ".dv-harness" / "soc-composer"
                           / "subsystem_environment_registry_template.json"
                           ).read_text(encoding="utf-8"))
    assert template == {"subsystems": []}
    # And the real runtime file is still legitimately absent in this repo.
    assert not (ROOT / ".dv-harness" / "soc-composer"
                / "subsystem_environment_registry.json").exists()


def test_the_connectivity_matrix_structurally_cannot_hold_a_registry_entry():
    """The second half of the same claim: MATRIX_COLUMNS has no subsystem
    column, so it cannot express `owner` vs `consumer_subsystems` -- the
    distinction the whole SYS-15 registry exists to make."""
    for absent in ("owner", "consumer_subsystems", "conflict_status",
                   "reuse_decision", "shared", "exclusive"):
        assert absent not in conn.MATRIX_COLUMNS
    assert "active_passive" in conn.MATRIX_COLUMNS  # the one overlapping field


def test_two_subsystems_driving_one_cpu_master_collapse_to_one_blocked_entry(tmp_path):
    """The headline case. Each subsystem's OWN connectivity self-check passes
    (asserted here from the other side), and only the registry -- which holds
    both subsystems' evidence at once -- shows one resource with two owners."""
    a, b = _two_subsystems_sharing_one_cpu_master(tmp_path)
    analysis, plan = _plan([a, b])

    for per in analysis["inventory"]["per_subsystem"]:
        assert per["matrix_self_check"]["status"] == "PASS"
    assert analysis["inventory"]["resource_count"] == 2

    entry = _only_entry(plan)
    assert entry["consumer_subsystems"] == ["SUBSYS_A", "SUBSYS_B"]
    assert entry["shared"] == srr.SHARED_ACROSS_SUBSYSTEMS
    assert entry["conflict_status"] == srr.CONFLICT_DRIVER
    assert entry["reuse_decision"] == srr.BLOCKED
    assert entry["owner"] == srr.OWNER_UNRESOLVED
    assert sorted(entry["member_resource_ids"]) == sorted(
        r["resource_id"] for r in analysis["inventory"]["resources"])
    assert plan["system_resource_registry"]["summary"]["collapsed_resource_count"] == 1
    assert plan["summary"]["integration_plan_clean"] is False


def test_owner_and_consumer_subsystems_are_genuinely_different_fields(tmp_path):
    """With one side PASSIVE the pair is promotable, so `owner` becomes a
    PROPOSED System owner while `consumer_subsystems` stays the two real
    environments. If the two fields ever collapsed into one, this is the case
    that would lose information."""
    a, b = _two_subsystems_sharing_one_cpu_master(tmp_path, b_active=False)
    _, plan = _plan([a, b])
    entry = _only_entry(plan)
    assert entry["reuse_decision"] == srr.REUSE_SHARED
    assert entry["owner"] == f"{srr.OWNER_PROPOSED_SYSTEM_PREFIX}::{sri.RT_AXI_MASTER}"
    assert entry["consumer_subsystems"] == ["SUBSYS_A", "SUBSYS_B"]
    assert entry["owner"] not in entry["consumer_subsystems"]
    assert entry["recommendation_only"] is True


def test_a_proposed_system_owner_is_never_asserted_as_an_actual_owner(tmp_path):
    a, b = _two_subsystems_sharing_one_cpu_master(tmp_path, b_active=False)
    _, plan = _plan([a, b])
    entry = _only_entry(plan)
    assert entry["owner"].startswith("PROPOSED_")
    assert "SYS-40" in plan["phase_boundary"]
    decision = list(plan["system_resource_registry"]["pair_decisions"].values())[0]
    assert decision["recommendation_only"] is True
    assert decision["implementation_phase"].startswith("SYS-40")


def test_differing_configurations_of_one_physical_resource_are_reconfigure(tmp_path):
    a, b = _two_subsystems_sharing_one_cpu_master(
        tmp_path, b_active=False, a_config={"data_width": "64"},
        b_config={"data_width": "32"})
    analysis, plan = _plan([a, b])
    entry = _only_entry(plan)
    assert entry["conflict_status"] == srr.CONFLICT_CONFIGURATION
    assert entry["reuse_decision"] == srr.RECONFIGURE
    assert entry["owner"] == srr.OWNER_UNRESOLVED
    # The two configuration fingerprints really do differ -- source_config is
    # what makes that visible in the registry itself.
    hashes = {c["configuration_hash"] for c in entry["source_config"]}
    assert len(hashes) == 2
    # And the disagreement was escalated through the existing 9-level order,
    # not resolved here.
    assert analysis["configuration_conflict_escalations"]
    verdicts = {e["conflict"]["verdict"]
                for e in analysis["configuration_conflict_escalations"]}
    assert verdicts == {"UNDECIDABLE_SAME_AUTHORITY"}
    assert "UNDECIDABLE_SAME_AUTHORITY" not in entry["reuse_decision"]


def test_two_passive_monitors_are_passive_only_and_never_reuse_shared(tmp_path):
    a = _subsystem_sources(
        tmp_path, "SUBSYS_A",
        rows=[_matrix_row(dut_instance="chip.soc.cpu_axi_m", interface="axi_m",
                          vip_type="svt_axi_monitor", active_passive="passive",
                          bind_target=SHARED_CPU_BIND, protocol="AXI4",
                          role=MASTER_ROLE,
                          fabric_side_role=conn.FABRIC_SIDE_MASTER_INTERFACE)])
    b = _subsystem_sources(
        tmp_path, "SUBSYS_B",
        rows=[_matrix_row(dut_instance="chip.soc.cpu_axi_m", interface="axi_m",
                          vip_type="svt_axi_monitor", active_passive="passive",
                          bind_target=SHARED_CPU_BIND, protocol="AXI4",
                          role=MASTER_ROLE,
                          fabric_side_role=conn.FABRIC_SIDE_MASTER_INTERFACE)])
    analysis, plan = _plan([a, b])
    assert analysis["relationships"][0]["relationship"] == sri.REL_MONITOR_ONLY_DUPLICATE
    entry = _only_entry(plan)
    assert entry["reuse_decision"] == srr.PASSIVE_ONLY
    assert entry["conflict_status"] == srr.CONFLICT_NONE
    assert entry["owner"] in ("SUBSYS_A", "SUBSYS_B", srr.OWNER_UNRESOLVED)
    row = plan["vip_agent_deduplication_matrix"]["rows"][0]
    assert row["Active Driver Conflict"] == srr.ADC_NO
    assert row["Decision"] == srr.PASSIVE_ONLY


def test_identity_is_transitive_so_three_subsystems_make_one_entry(tmp_path):
    """A registry that merged pairwise instead of transitively would hold two
    overlapping entries for one physical resource, and a composer reading it
    would instantiate that resource twice."""
    def _passive_side(name):
        return _subsystem_sources(
            tmp_path, name,
            rows=[_matrix_row(dut_instance="chip.soc.cpu_axi_m", interface="axi_m",
                              vip_type="svt_axi_monitor", active_passive="passive",
                              bind_target=SHARED_CPU_BIND, protocol="AXI4",
                              role=MASTER_ROLE,
                              fabric_side_role=conn.FABRIC_SIDE_MASTER_INTERFACE)])
    _, plan = _plan([_passive_side("SUBSYS_A"), _passive_side("SUBSYS_B"),
                     _passive_side("SUBSYS_C")])
    entry = _only_entry(plan)
    assert entry["consumer_subsystems"] == ["SUBSYS_A", "SUBSYS_B", "SUBSYS_C"]
    assert len(entry["member_resource_ids"]) == 3
    assert len(entry["source_environment"]) == 3
    assert plan["system_resource_registry"]["summary"]["collapsed_resource_count"] == 2


def test_independent_resources_are_never_merged_into_one_entry(tmp_path):
    """Two genuinely different AMBA resources on two different protocols must
    stay two entries -- a registry that over-merges is worse than none."""
    a = _subsystem_sources(
        tmp_path, "SUBSYS_A",
        rows=[_matrix_row(dut_instance="chip.a.axi", interface="axi_m",
                          vip_type="svt_axi_master_agent", active_passive="active",
                          bind_target="chip.a.axi", protocol="AXI4", role=MASTER_ROLE,
                          fabric_side_role=conn.FABRIC_SIDE_MASTER_INTERFACE)],
        regions=(("A_CTRL", "0x10000000", 4096, "AXI4"),))
    b = _subsystem_sources(
        tmp_path, "SUBSYS_B",
        rows=[_matrix_row(dut_instance="chip.b.apb", interface="apb_m",
                          vip_type="svt_apb_master_agent", active_passive="active",
                          bind_target="chip.b.apb", protocol="APB4", role=MASTER_ROLE,
                          fabric_side_role=conn.FABRIC_SIDE_MASTER_INTERFACE)],
        regions=(("B_CTRL", "0x20000000", 4096, "APB4"),))
    _, plan = _plan([a, b])
    entries = plan["system_resource_registry"]["entries"]
    assert len(entries) == 2
    for entry in entries:
        assert entry["shared"] == srr.NOT_SHARED
        assert len(entry["consumer_subsystems"]) == 1
        assert entry["owner"] == entry["consumer_subsystems"][0]


def test_a_shared_logical_pair_is_cross_referenced_not_merged(tmp_path):
    """SYS-11's SHARED_LOGICAL_RESOURCE says in its own reason string that
    physical equivalence is NOT established. Merging two entries on that basis
    would make the authority assert something nothing proved, so the registry
    records a cross-reference instead."""
    overlapping = (("SHARED_DDR", "0x40000000", 0x10000, "AXI4"),)
    a = _subsystem_sources(
        tmp_path, "SUBSYS_A",
        rows=[_matrix_row(dut_instance="chip.a.ddr", interface="axi_s",
                          vip_type="svt_axi_slave_agent", active_passive="passive",
                          bind_target="chip.a.ddr", protocol="AXI4",
                          role=MASTER_ROLE,
                          fabric_side_role=conn.FABRIC_SIDE_MASTER_INTERFACE)],
        regions=overlapping)
    b = _subsystem_sources(
        tmp_path, "SUBSYS_B",
        rows=[_matrix_row(dut_instance="chip.b.ddr", interface="axi_s",
                          vip_type="svt_axi_slave_agent", active_passive="passive",
                          bind_target="chip.b.ddr", protocol="AXI4",
                          role=MASTER_ROLE,
                          fabric_side_role=conn.FABRIC_SIDE_MASTER_INTERFACE)],
        regions=overlapping)
    analysis, plan = _plan([a, b])
    relationship = analysis["relationships"][0]["relationship"]
    assert relationship not in srr.MERGING_RELATIONSHIPS
    entries = plan["system_resource_registry"]["entries"]
    assert len(entries) == 2, "a non-physical relationship must not collapse two entries"
    # ... but the relationship is not lost: each entry names the other.
    assert entries[0]["related_entries"] == [entries[1]["resource_id"]]
    assert entries[1]["related_entries"] == [entries[0]["resource_id"]]


def test_a_subsystem_specific_pcie_vip_pair_is_keep_independent_never_promoted(tmp_path):
    """SYS-14, through SYS-13's NOT_ELIGIBLE_SUBSYSTEM_SPECIFIC verdict, is
    the thing that must survive the translation into SYS-17's vocabulary."""
    def _pcie(name):
        return _subsystem_sources(
            tmp_path, name,
            rows=[_matrix_row(dut_instance="chip.pcie.ctrl", interface="pipe",
                              vip_type="svt_pcie_device_agent", active_passive="passive",
                              bind_target="chip.pcie.ctrl", protocol="PCIe")])
    _, plan = _plan([_pcie("PCIE_A"), _pcie("PCIE_B")])
    rows = plan["vip_agent_deduplication_matrix"]["rows"]
    assert rows, "the two PCIe agents are an apparent duplicate and must appear"
    assert {r["Decision"] for r in rows} == {srr.KEEP_INDEPENDENT}
    assert {r["System Owner"] for r in rows} == {srr.NO_SYSTEM_OWNER}
    for entry in plan["system_resource_registry"]["entries"]:
        assert entry["reuse_decision"] == srr.KEEP_INDEPENDENT
        assert not entry["owner"].startswith(srr.OWNER_PROPOSED_SYSTEM_PREFIX)


def test_a_stopped_resource_cannot_be_laundered_clean_by_a_second_pair(tmp_path):
    """SUBSYS_A has TWO active rows on one bind target inside its OWN matrix --
    a SYS-12 stop with no cross-subsystem pair involved. SUBSYS_B then shares
    that same interface passively, which on its own would read as a clean
    REUSE_SHARED. The stop must win: a decision on a stopped resource may not
    step past that stop."""
    a = _subsystem_sources(
        tmp_path, "SUBSYS_A",
        rows=[_matrix_row(dut_instance="chip.soc.cpu_axi_m", interface="axi_m",
                          vip_type="svt_axi_master_agent", active_passive="active",
                          bind_target=SHARED_CPU_BIND, protocol="AXI4",
                          role=MASTER_ROLE,
                          fabric_side_role=conn.FABRIC_SIDE_MASTER_INTERFACE),
              _matrix_row(dut_instance="chip.soc.cpu_axi_m2", interface="axi_m",
                          vip_type="svt_axi_master_agent", active_passive="active",
                          bind_target=SHARED_CPU_BIND, protocol="AXI4",
                          role=MASTER_ROLE,
                          fabric_side_role=conn.FABRIC_SIDE_MASTER_INTERFACE)])
    b = _subsystem_sources(
        tmp_path, "SUBSYS_B",
        rows=[_matrix_row(dut_instance="chip.soc.cpu_axi_m", interface="axi_m",
                          vip_type="svt_axi_master_agent", active_passive="passive",
                          bind_target=SHARED_CPU_BIND, protocol="AXI4",
                          role=MASTER_ROLE,
                          fabric_side_role=conn.FABRIC_SIDE_MASTER_INTERFACE)])
    analysis, plan = _plan([a, b])
    stopped = set(analysis["active_driver_conflict_rule"]["stopped_resource_ids"])
    assert stopped, "the within-subsystem collision must produce a SYS-12 stop"

    decisions = list(plan["system_resource_registry"]["pair_decisions"].values())
    assert decisions
    assert all(d["decision"] == srr.BLOCKED for d in decisions), [
        (d["sys11_relationship"], d["decision"]) for d in decisions]
    assert any(d["overridden_by_sys12_stop"] for d in decisions)
    for entry in plan["system_resource_registry"]["entries"]:
        if set(entry["member_resource_ids"]) & stopped:
            assert entry["reuse_decision"] == srr.BLOCKED
            assert entry["owner"] == srr.OWNER_UNRESOLVED


def test_an_independent_pair_is_not_blocked_by_an_unrelated_stop(tmp_path):
    """The other side of the same override: a resource stopped by a conflict
    of its own says nothing about a genuinely INDEPENDENT pair, and blocking
    that pair too would be noise a reviewer learns to ignore."""
    a = _subsystem_sources(
        tmp_path, "SUBSYS_A",
        rows=[_matrix_row(dut_instance="chip.a.axi", interface="axi_m",
                          vip_type="svt_axi_master_agent", active_passive="active",
                          bind_target="chip.a.axi", protocol="AXI4", role=MASTER_ROLE,
                          fabric_side_role=conn.FABRIC_SIDE_MASTER_INTERFACE),
              _matrix_row(dut_instance="chip.a.axi2", interface="axi_m",
                          vip_type="svt_axi_master_agent", active_passive="active",
                          bind_target="chip.a.axi", protocol="AXI4", role=MASTER_ROLE,
                          fabric_side_role=conn.FABRIC_SIDE_MASTER_INTERFACE)],
        regions=(("A_CTRL", "0x10000000", 4096, "AXI4"),))
    b = _subsystem_sources(
        tmp_path, "SUBSYS_B",
        rows=[_matrix_row(dut_instance="chip.b.apb", interface="apb_m",
                          vip_type="svt_apb_master_agent", active_passive="active",
                          bind_target="chip.b.apb", protocol="APB4", role=MASTER_ROLE,
                          fabric_side_role=conn.FABRIC_SIDE_MASTER_INTERFACE)],
        regions=(("B_CTRL", "0x20000000", 4096, "APB4"),))
    analysis, plan = _plan([a, b])
    assert analysis["active_driver_conflict_rule"]["stopped_resource_ids"]
    independent = [d for d in plan["system_resource_registry"]["pair_decisions"].values()
                   if d["sys11_relationship"] == sri.REL_INDEPENDENT]
    assert independent
    assert all(d["decision"] == srr.KEEP_INDEPENDENT for d in independent)
    assert all(d["overridden_by_sys12_stop"] is False for d in independent)


def test_a_registry_entry_carrying_a_conflict_is_never_reported_high_confidence(tmp_path):
    a, b = _two_subsystems_sharing_one_cpu_master(tmp_path)
    _, plan = _plan([a, b])
    entry = _only_entry(plan)
    assert entry["conflict_status"] != srr.CONFLICT_NONE
    assert entry["confidence"] != "HIGH"
    # The conflict really is what lowered it: the same two independent
    # environments with no conflict score higher through the same scorer.
    without_conflict = inference.score_confidence(
        independent_sources_count=2, evidence_refs_verified=True,
        counter_evidence_count=0, multi_agent_consensus_count=0)
    assert without_conflict["level"] == "HIGH"
    assert entry["confidence_detail"]["score"] < without_conflict["score"]


def test_an_active_passive_pair_is_not_scored_as_a_contradiction(tmp_path):
    """`exclusive` is DERIVED from active/passive, so the healthy
    SAME_PHYSICAL case necessarily disagrees on it. The disagreement is still
    REPORTED; it just must not be counted as evidence against the entry."""
    a, b = _two_subsystems_sharing_one_cpu_master(tmp_path, b_active=False)
    _, plan = _plan([a, b])
    entry = _only_entry(plan)
    assert entry["exclusive"].startswith(srr.DISAGREEMENT)
    assert entry["confidence_detail"]["capped_by_counter_evidence"] is False


def test_a_disagreeing_field_is_reported_as_a_disagreement_not_silently_resolved(tmp_path):
    a, b = _two_subsystems_sharing_one_cpu_master(tmp_path, b_active=False)
    _, plan = _plan([a, b])
    entry = _only_entry(plan)
    # Comma-separated, never pipe-separated: this value is rendered into a
    # markdown table cell and a literal pipe there splits the row silently.
    assert entry["active_passive"] == f"{srr.DISAGREEMENT}(active,passive)"
    assert "|" not in entry["active_passive"]
    # ... while a field the members genuinely agree on stays a plain value.
    assert entry["clock"] == "core_clk"
    assert entry["protocol"] == "AXI4"


def test_physical_hierarchy_is_a_list_because_two_environments_name_trees_apart(tmp_path):
    a, b = _two_subsystems_sharing_one_cpu_master(tmp_path, b_active=False)
    _, plan = _plan([a, b])
    entry = _only_entry(plan)
    assert isinstance(entry["physical_hierarchy"], list)
    assert entry["physical_hierarchy"] == ["chip.soc.cpu_axi_m"]


def test_a_registry_entry_id_is_shaped_differently_from_a_subsystem_local_id(tmp_path):
    a, b = _two_subsystems_sharing_one_cpu_master(tmp_path)
    analysis, plan = _plan([a, b])
    entry = _only_entry(plan)
    assert entry["resource_id"].startswith("SYSRES::")
    for member in analysis["inventory"]["resources"]:
        assert not member["resource_id"].startswith("SYSRES::")
        assert plan["system_resource_registry"]["entry_of_resource"][
            member["resource_id"]] == entry["resource_id"]


# ============================================================================
# SYS-16: subsystem integration matrix
# ============================================================================

def test_every_selected_subsystem_appears_even_with_no_resources(tmp_path):
    a = _subsystem_sources(tmp_path, "SUBSYS_A", rows=[])
    b = _subsystem_sources(tmp_path, "SUBSYS_B", rows=[])
    _, plan = _plan([a, b])
    matrix = plan["subsystem_integration_matrix"]
    assert [r["Subsystem"] for r in matrix["rows"]] == ["SUBSYS_A", "SUBSYS_B"]
    assert all(r["VIPs"] == "0" for r in matrix["rows"])


def test_a_selected_subsystem_missing_from_the_matrix_raises(tmp_path):
    """SYS-16: 'Every selected subsystem must appear.' A rule that only warns
    is not a rule -- and a table that silently omits a subsystem reads as a
    complete statement about the selection."""
    matrix = {"rows": [{"Subsystem": "SUBSYS_A"}]}
    with pytest.raises(srr.SystemResourceRegistryError) as exc:
        srr.assert_every_selected_subsystem_present(matrix, ["SUBSYS_A", "SUBSYS_B"])
    assert exc.value.reason == "SYS16_SELECTED_SUBSYSTEM_MISSING_FROM_MATRIX"
    assert exc.value.detail["missing"] == ["SUBSYS_B"]


def test_a_subsystem_selected_but_never_inventoried_still_gets_a_row(tmp_path):
    a, b = _two_subsystems_sharing_one_cpu_master(tmp_path)
    analysis, _ = _plan([a, b])
    registry = srr.build_system_resource_registry(analysis)
    selection = {"selected_subsystems": ["SUBSYS_A", "SUBSYS_B", "SUBSYS_GHOST"],
                 "selected_rows": []}
    matrix = srr.build_subsystem_integration_matrix(analysis, registry, selection=selection)
    ghost = [r for r in matrix["rows"] if r["Subsystem"] == "SUBSYS_GHOST"]
    assert len(ghost) == 1
    assert ghost[0]["Integration Status"] == srr.INTEGRATION_UNKNOWN
    assert ghost[0]["VIPs"] == srr.NOT_AVAILABLE


def test_not_available_is_distinct_from_zero_in_every_column(tmp_path):
    """"nobody looked" and "we looked and found none" are opposite findings.
    Without SYS-1..4 and SYS-5..8 inputs the columns those layers answer must
    say NOT_AVAILABLE, never 0 and never READY."""
    a, b = _two_subsystems_sharing_one_cpu_master(tmp_path, b_active=False)
    _, plan = _plan([a, b])
    row = plan["subsystem_integration_matrix"]["rows"][0]
    assert row["command.txt"] == srr.NOT_AVAILABLE
    assert row["Readiness"] == srr.NOT_AVAILABLE
    assert row["Scoreboard"].startswith(srr.NOT_AVAILABLE)
    assert row["Integration Status"] == srr.INTEGRATION_UNKNOWN
    # ... while the columns this layer CAN answer are real counts.
    assert row["VIPs"] == "1"
    assert row["Shared Resources"] == "1"


def test_readiness_and_command_txt_come_from_the_existing_sys1_and_sys7_layers(tmp_path):
    """No second readiness classifier: the cell is the verdict
    subsystem_discovery already printed in SYS-1's own table."""
    a, b = _two_subsystems_sharing_one_cpu_master(tmp_path, b_active=False)
    analysis, _ = _plan([a, b])
    registry = srr.build_system_resource_registry(analysis)
    selection = {
        "selected_subsystems": ["SUBSYS_A", "SUBSYS_B"],
        "selected_rows": [
            {"subsystem": "SUBSYS_A", "environment_path": "/env/a", "readiness": "READY",
             "existence_class": "EXISTS_READY"},
            {"subsystem": "SUBSYS_B", "environment_path": "/env/b", "readiness": "PARTIAL",
             "existence_class": "EXISTS_PARTIAL"}],
    }
    synthesis = {"per_subsystem": [
        {"subsystem_id": "SUBSYS_A",
         "command_analyses": [{"command_file": "/env/a/command.txt"}],
         "fields": {"scoreboards": {"status": "DERIVED", "source": "env_topology",
                                    "components": [{"full_name": "env.sb"}]}}},
        {"subsystem_id": "SUBSYS_B", "command_analyses": [],
         "fields": {"scoreboards": {"status": "NOT_APPLICABLE", "source": "env_topology",
                                    "components": []}}}]}
    matrix = srr.build_subsystem_integration_matrix(
        analysis, registry, selection=selection, synthesis=synthesis)
    by_name = {r["Subsystem"]: r for r in matrix["rows"]}
    assert by_name["SUBSYS_A"]["Readiness"] == "READY"
    assert by_name["SUBSYS_A"]["command.txt"] == "1"
    assert by_name["SUBSYS_A"]["Scoreboard"] == "DERIVED(1)"
    assert by_name["SUBSYS_A"]["Integration Status"] == srr.INTEGRATION_READY
    # SUBSYS_B is EXISTS_PARTIAL -- SYS-2's own verdict blocks it, and the
    # zero-scoreboard cell says NOT_APPLICABLE, not NOT_AVAILABLE.
    assert by_name["SUBSYS_B"]["Scoreboard"] == "NOT_APPLICABLE(0)"
    assert by_name["SUBSYS_B"]["Integration Status"] == srr.INTEGRATION_BLOCKED_NOT_READY


def test_a_driver_conflict_outranks_a_not_ready_subsystem_in_the_status_column(tmp_path):
    a, b = _two_subsystems_sharing_one_cpu_master(tmp_path)
    analysis, _ = _plan([a, b])
    registry = srr.build_system_resource_registry(analysis)
    selection = {"selected_subsystems": ["SUBSYS_A", "SUBSYS_B"],
                 "selected_rows": [
                     {"subsystem": "SUBSYS_A", "readiness": "BLOCKED",
                      "existence_class": "EXISTS_BLOCKED"},
                     {"subsystem": "SUBSYS_B", "readiness": "READY",
                      "existence_class": "EXISTS_READY"}]}
    matrix = srr.build_subsystem_integration_matrix(analysis, registry, selection=selection)
    for row in matrix["rows"]:
        assert row["Integration Status"] == srr.INTEGRATION_BLOCKED_DRIVER_CONFLICT
        assert int(row["Conflicts"]) >= 1


def test_the_rendered_sys16_table_has_exactly_the_mandated_header(tmp_path):
    a, b = _two_subsystems_sharing_one_cpu_master(tmp_path)
    _, plan = _plan([a, b])
    text = srr.render_subsystem_integration_matrix(plan["subsystem_integration_matrix"])
    assert text.splitlines()[0] == "| " + SYS16_REQUIREMENT_TEXT + " |"
    assert len(text.splitlines()) == 4  # header + separator + two subsystems


# ============================================================================
# SYS-17: VIP / agent deduplication matrix
# ============================================================================

def test_the_rendered_sys17_table_has_exactly_the_mandated_header(tmp_path):
    a, b = _two_subsystems_sharing_one_cpu_master(tmp_path)
    _, plan = _plan([a, b])
    text = srr.render_vip_deduplication_matrix(plan["vip_agent_deduplication_matrix"])
    assert text.splitlines()[0] == "| " + SYS17_REQUIREMENT_TEXT + " |"


def test_a_pipe_in_real_data_does_not_split_a_rendered_row(tmp_path):
    """A hierarchy path, a bind target or a DISAGREEMENT value carrying a
    literal '|' would silently add columns to a markdown row -- corruption a
    reader of the rendered table cannot see."""
    a, b = _two_subsystems_sharing_one_cpu_master(tmp_path, b_active=False)
    _, plan = _plan([a, b])
    entry = _only_entry(plan)
    assert entry["active_passive"].startswith(srr.DISAGREEMENT)

    poisoned = json.loads(json.dumps(plan, default=str))
    poisoned["vip_agent_deduplication_matrix"]["rows"][0]["Physical Interface"] = "chip|evil"
    poisoned["subsystem_integration_matrix"]["rows"][0]["Environment"] = "/a|b"
    for text, columns in (
            (srr.render_vip_deduplication_matrix(
                poisoned["vip_agent_deduplication_matrix"]), srr.SYS17_COLUMNS),
            (srr.render_subsystem_integration_matrix(
                poisoned["subsystem_integration_matrix"]), srr.SYS16_COLUMNS),
            (srr.render_registry_table(poisoned["system_resource_registry"]), None)):
        lines = text.splitlines()
        # Count only UNESCAPED pipes -- an escaped `\|` is one cell's content
        # in markdown, which is exactly what the renderer must produce.
        widths = {len(re.split(r"(?<!\\)\|", line)) for line in lines}
        assert len(widths) == 1, (widths, lines)
        assert all("\\|" in line or "|evil" not in line and "a|b" not in line
                   for line in lines)
        if columns is not None:
            assert widths == {len(columns) + 2}


def test_every_decision_is_inside_the_closed_vocabulary(tmp_path):
    a, b = _two_subsystems_sharing_one_cpu_master(tmp_path)
    _, plan = _plan([a, b])
    for row in plan["vip_agent_deduplication_matrix"]["rows"]:
        assert row["Decision"] in srr.SYS17_DECISIONS
        assert row["Active Driver Conflict"] in srr.ADC_VALUES


def test_active_driver_conflict_is_three_valued_and_unproven_is_not_no(tmp_path):
    """Two ACTIVE agents whose physical identity is NOT established are the
    dangerous middle case. Reporting them as NO is how a real conflict gets
    integrated; reporting them as YES would be a claim the evidence does not
    support."""
    a = _subsystem_sources(
        tmp_path, "SUBSYS_A",
        rows=[_matrix_row(dut_instance="chip.a.ddr", interface="axi_s",
                          vip_type="svt_axi_master_agent", active_passive="active",
                          bind_target="chip.a.ddr", protocol="AXI4", role=MASTER_ROLE,
                          fabric_side_role=conn.FABRIC_SIDE_MASTER_INTERFACE)],
        regions=(("SHARED_DDR", "0x40000000", 0x10000, "AXI4"),))
    b = _subsystem_sources(
        tmp_path, "SUBSYS_B",
        rows=[_matrix_row(dut_instance="chip.b.ddr", interface="axi_s",
                          vip_type="svt_axi_master_agent", active_passive="active",
                          bind_target="chip.b.ddr", protocol="AXI4", role=MASTER_ROLE,
                          fabric_side_role=conn.FABRIC_SIDE_MASTER_INTERFACE)],
        regions=(("SHARED_DDR", "0x40000000", 0x10000, "AXI4"),))
    analysis, plan = _plan([a, b])
    rel = analysis["relationships"][0]
    assert rel["relationship"] != sri.REL_DRIVER_CONFLICT
    assert rel["both_active"] is True
    row = plan["vip_agent_deduplication_matrix"]["rows"][0]
    assert row["Active Driver Conflict"] == srr.ADC_UNPROVEN
    # SYS-12 HELD it, so the decision is BLOCKED rather than a merge.
    assert analysis["active_driver_conflict_rule"]["held_resource_ids"]
    assert row["Decision"] == srr.BLOCKED
    assert row["System Owner"] == srr.OWNER_UNRESOLVED


def test_a_within_subsystem_collision_appears_in_the_decision_table(tmp_path):
    """SYS-12's rule is about two active AGENTS, not two subsystems. A
    within-matrix collision that never reached the mandatory decision table
    would be a real BLOCKED finding a human never signs off on."""
    a = _subsystem_sources(
        tmp_path, "SUBSYS_A",
        rows=[_matrix_row(dut_instance="chip.a", interface="axi_m",
                          vip_type="svt_axi_master_agent", active_passive="active",
                          bind_target=SHARED_CPU_BIND, protocol="AXI4"),
              _matrix_row(dut_instance="chip.b", interface="axi_m2",
                          vip_type="svt_axi_master_agent", active_passive="active",
                          bind_target=SHARED_CPU_BIND, protocol="AXI4")])
    b = _subsystem_sources(tmp_path, "SUBSYS_B", rows=[])
    analysis, plan = _plan([a, b])
    within = [r for r in plan["vip_agent_deduplication_matrix"]["rows"]
              if r["detail"]["scope"] == "WITHIN_SUBSYSTEM"]
    assert len(within) == 1
    assert within[0]["Subsystem A"] == within[0]["Subsystem B"] == "SUBSYS_A"
    assert within[0]["Decision"] == srr.BLOCKED
    assert within[0]["Active Driver Conflict"] == srr.ADC_YES
    assert within[0]["Physical Interface"] == SHARED_CPU_BIND
    assert srr.render_vip_deduplication_matrix(
        plan["vip_agent_deduplication_matrix"]).count("SUBSYS_A | SUBSYS_A") == 1


def test_a_within_subsystem_collision_makes_one_entry_not_two(tmp_path):
    """Two ACTIVE rows of one matrix claiming one bind target are two agents on
    ONE physical interface. The registry is the composition authority, so it
    must hold ONE entry for that interface -- two would present it as two
    consumable resources -- and that entry must be BLOCKED even though no
    CROSS-subsystem pair decision ever reached it."""
    a = _subsystem_sources(
        tmp_path, "SUBSYS_A",
        rows=[_matrix_row(dut_instance="chip.a", interface="axi_m",
                          vip_type="svt_axi_master_agent", active_passive="active",
                          bind_target=SHARED_CPU_BIND, protocol="AXI4"),
              _matrix_row(dut_instance="chip.b", interface="axi_m2",
                          vip_type="svt_axi_master_agent", active_passive="active",
                          bind_target=SHARED_CPU_BIND, protocol="AXI4")])
    analysis, plan = _plan([a])
    assert analysis["inventory"]["resource_count"] == 2
    assert analysis["relationships"] == [], "no CROSS-subsystem pair exists here"

    entry = _only_entry(plan)
    assert len(entry["member_resource_ids"]) == 2
    assert entry["consumer_subsystems"] == ["SUBSYS_A"]
    assert entry["shared"] == srr.NOT_SHARED  # one subsystem, two claimants
    assert entry["conflict_status"] == srr.CONFLICT_DRIVER
    assert entry["reuse_decision"] == srr.BLOCKED
    assert entry["owner"] == srr.OWNER_UNRESOLVED
    assert "SYS-12" in entry["reuse_decision_reason"]
    assert plan["summary"]["integration_plan_clean"] is False


def test_physical_interface_is_unresolved_rather_than_a_guess_from_one_side(tmp_path):
    """A pair whose only agreeing signal is the VIP class name has no shared
    physical interface, and inventing one from either side's hierarchy is
    exactly what SYS-10 forbids."""
    def _named(name, hierarchy):
        return _subsystem_sources(
            tmp_path, name,
            rows=[_matrix_row(dut_instance=hierarchy, interface="if0",
                              vip_type="svt_widget_agent", active_passive="passive",
                              bind_target=hierarchy)],
            regions=())
    analysis, plan = _plan([_named("SUBSYS_A", "chip.a.widget"),
                            _named("SUBSYS_B", "chip.b.widget")])
    rows = plan["vip_agent_deduplication_matrix"]["rows"]
    assert len(rows) == 1, "the two identically-named agents are an apparent duplicate"
    assert analysis["relationships"][0]["name_evidence_only"] is True
    assert rows[0]["Physical Interface"] == sri.UNRESOLVED
    assert rows[0]["Decision"] == srr.DECISION_UNKNOWN
    assert rows[0]["System Owner"] == srr.OWNER_UNRESOLVED
    assert "NAME_EVIDENCE_ONLY" in rows[0]["detail"]["decision_reason"]
    # The pair did NOT merge, and the Resource cell says so by naming both
    # entries rather than only one side's.
    assert " ~ " in rows[0]["Resource"]
    assert len(plan["system_resource_registry"]["entries"]) == 2


def test_the_registry_and_the_dedup_table_never_disagree_about_a_decision(tmp_path):
    """One decision function feeds both. A test rather than a comment,
    because two vocabularies that drift apart is this project's own
    hard-won lesson."""
    a, b = _two_subsystems_sharing_one_cpu_master(tmp_path, b_active=False)
    _, plan = _plan([a, b])
    entry = _only_entry(plan)
    rows = plan["vip_agent_deduplication_matrix"]["rows"]
    assert len(rows) == 1
    assert rows[0]["Decision"] == entry["reuse_decision"]
    assert rows[0]["System Owner"] == entry["owner"]
    assert rows[0]["Resource"] == entry["resource_id"]


def test_rows_are_ordered_most_restrictive_first(tmp_path):
    a, b = _two_subsystems_sharing_one_cpu_master(tmp_path)
    _, plan = _plan([a, b])
    rows = plan["vip_agent_deduplication_matrix"]["rows"]
    severities = [srr.DECISION_SEVERITY[r["Decision"]] for r in rows]
    assert severities == sorted(severities)


# ============================================================================
# SYS-15 persistence
# ============================================================================

def test_the_registry_round_trips_through_a_real_file(tmp_path):
    a, b = _two_subsystems_sharing_one_cpu_master(tmp_path)
    _, plan = _plan([a, b])
    project = tmp_path / "project"
    project.mkdir()
    path = srr.write_system_resource_registry(project, plan["system_resource_registry"])
    assert path == project / ".dv-harness" / "soc-composer" / "system_resource_registry.json"
    # Written BESIDE the subsystem registry, never into it.
    assert path.name != "subsystem_environment_registry.json"
    assert not (path.parent / "subsystem_environment_registry.json").exists()

    read_back = srr.read_system_resource_registry(project)
    assert read_back["status"] == "PRESENT"
    assert read_back["authority_scope"] == "PLANNING_ONLY"
    assert read_back["artifacts_modified"] is False
    assert "SYS-40" in read_back["phase_boundary"]
    assert [e["resource_id"] for e in read_back["entries"]] == [
        e["resource_id"] for e in plan["system_resource_registry"]["entries"]]


def test_an_absent_registry_reports_absent_rather_than_raising(tmp_path):
    result = srr.read_system_resource_registry(tmp_path)
    assert result["status"] == "ABSENT"
    assert result["entries"] == []


def test_a_document_that_is_not_planning_scoped_is_refused(tmp_path):
    with pytest.raises(srr.SystemResourceRegistryError) as exc:
        srr.write_system_resource_registry(
            tmp_path, {"authority_scope": "AUTHORITATIVE", "entries": []})
    assert exc.value.reason == "REGISTRY_NOT_PLANNING_SCOPED"
    assert not (tmp_path / ".dv-harness").exists()


def test_the_persisted_registry_validates_against_its_own_schema(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    a, b = _two_subsystems_sharing_one_cpu_master(tmp_path, b_active=False)
    _, plan = _plan([a, b])
    schema = json.loads((ROOT / "dv_harness" / "schemas"
                         / "system_resource_registry.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(
        json.loads(json.dumps(plan["system_resource_registry"], default=str)), schema)


# ============================================================================
# SYS-39 boundary: this layer generates nothing
# ============================================================================

def _snapshot(root: Path):
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_a_full_sys15_17_run_modifies_no_file_anywhere(tmp_path):
    a, b = _two_subsystems_sharing_one_cpu_master(tmp_path)
    before = _snapshot(tmp_path)
    analysis, plan = _plan([a, b])
    srr.format_integration_plan_report(plan)
    assert _snapshot(tmp_path) == before
    assert plan["artifacts_modified"] is False
    assert plan["system_resource_registry"]["artifacts_modified"] is False
    assert plan["subsystem_integration_matrix"]["artifacts_modified"] is False
    assert plan["vip_agent_deduplication_matrix"]["artifacts_modified"] is False
    assert analysis["artifacts_modified"] is False


def test_the_report_contains_no_systemverilog_and_no_command_txt_content(tmp_path):
    a, b = _two_subsystems_sharing_one_cpu_master(tmp_path, b_active=False)
    _, plan = _plan([a, b])
    text = srr.format_integration_plan_report(plan)
    for token in ("class ", "endclass", "`uvm_", "module ", "endmodule", "task ",
                  "function void", "uvm_sequence", "virtual sequencer;", ".sv\n"):
        assert token not in text, token
    assert "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED" in text
    assert "SYS-40" in text


def test_the_soc_composer_cross_subsystem_stubs_still_raise():
    """SYS-26/27/30 content stays unimplemented on purpose -- filling those in
    is SYS-40, and a registry that quietly enabled them would be the breach
    this whole boundary exists to prevent."""
    from dv_harness.uvm_generator import soc_environment_composer as sec
    for fn in (sec.cross_subsystem_scenarios, sec.end_to_end_scoreboard,
               sec.system_coverage):
        with pytest.raises(NotImplementedError):
            fn({})


def test_no_system_level_uvm_or_command_txt_source_is_emitted_by_this_module():
    src = (ROOT / "dv_harness" / "system_resource_registry.py").read_text(encoding="utf-8")
    for token in ("endclass", "endmodule", "`uvm_component_utils", "uvm_sequence #",
                  "virtual_sequencer", "command_router", "def write_command",
                  "def generate_", "def emit_", ".sv\""):
        assert token not in src, token
    # The ONLY thing this module ever writes is the SYS-15 planning registry.
    assert src.count(".write_text(") == 1
    assert src.count("open(") == 0
    write_body = src.split("def write_system_resource_registry", 1)[1].split("\ndef ", 1)[0]
    assert ".write_text(" in write_body
    assert "system_resource_registry.json" in srr.REGISTRY_FILENAME


# ============================================================================
# The real CLI verb
# ============================================================================

def test_the_cli_refuses_without_an_explicit_selection(tmp_path):
    """SYS-1's refusal is not bypassed by adding a verb on top of it."""
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp_path),
         "system-integration-plan"],
        cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "NO_EXPLICIT_SELECTION" in (proc.stdout + proc.stderr)


def _registered_two_subsystem_project(tmp_path: Path) -> None:
    """A synthetic project SYS-1 classifies EXISTS_READY for two subsystems
    that both actively drive one CPU AXI Master -- the real front door's own
    end-to-end conflicting case."""
    rows = [_matrix_row(dut_instance="chip.soc.cpu_axi_m", interface="axi_m",
                        vip_type="svt_cpu_axi_master_agent", active_passive="active",
                        bind_target=SHARED_CPU_BIND, protocol="AXI4", role=MASTER_ROLE)]
    for name, sha in (("SUBSYS_A", "aaa111"), ("SUBSYS_B", "bbb222")):
        _registered_env(tmp_path, name, rows=rows,
                        vip_instances=[(SHARED_CPU_BIND, "svt_cpu_axi_master_agent",
                                        {"data_width": "64"})],
                        command_text=CPU_SIDE_COMMANDS,
                        regions=(("CTRL", "0x14000000", 4096, "AXI4"),),
                        release_sha=sha)
    _write(sd.candidate_sources_path(tmp_path), json.dumps({"candidates": [
        {"name": n, "protocol": "SYNTH",
         "environment_path": str(tmp_path / "generated" / n.lower())}
        for n in ("SUBSYS_A", "SUBSYS_B")]}))
    _write(tmp_path / ".dv-harness" / "soc-composer" / "subsystem_environment_registry.json",
           json.dumps({"subsystems": [
               {"name": n,
                "environment_manifest": str(tmp_path / "generated" / n.lower()
                                            / ".dv-harness" / "env.manifest.json"),
                "release_sha": sha, "qualification_state": "REGRESSION_QUALIFIED",
                "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS"}
               for n, sha in (("SUBSYS_A", "aaa111"), ("SUBSYS_B", "bbb222"))]}))


def test_the_cli_verb_exits_2_and_prints_both_mandatory_tables(tmp_path):
    """The real front door as a subprocess. A standing BLOCKED decision must
    not read as a clean run to a CI step, and both mandated tables must be in
    the output a human signs off on."""
    _registered_two_subsystem_project(tmp_path)
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp_path),
         "system-integration-plan", "--select", "SUBSYS_A", "--select", "SUBSYS_B"],
        cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 2, proc.stderr[-2000:]
    assert "SYS-15 SYSTEM_RESOURCE_REGISTRY" in proc.stdout
    assert "| " + SYS16_REQUIREMENT_TEXT + " |" in proc.stdout
    assert "| " + SYS17_REQUIREMENT_TEXT + " |" in proc.stdout
    assert "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED" in proc.stdout
    assert srr.BLOCKED in proc.stdout
    # Nothing was persisted without --write-registry.
    assert not srr.registry_path(tmp_path).exists()


def test_the_cli_write_registry_flag_persists_only_the_planning_document(tmp_path):
    _registered_two_subsystem_project(tmp_path)
    generated = tmp_path / "generated"
    before = _snapshot(generated)
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp_path),
         "system-integration-plan", "--select", "SUBSYS_A", "--select", "SUBSYS_B",
         "--write-registry"],
        cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 2, proc.stderr[-2000:]
    written = srr.read_system_resource_registry(tmp_path)
    assert written["status"] == "PRESENT"
    assert written["authority_scope"] == "PLANNING_ONLY"
    assert written["entries"]
    # The two subsystem ENVIRONMENTS are byte-for-byte untouched, and the
    # SUBSYSTEM registry beside it is too.
    assert _snapshot(generated) == before
    subsystem_registry = json.loads(
        (tmp_path / ".dv-harness" / "soc-composer"
         / "subsystem_environment_registry.json").read_text(encoding="utf-8"))
    assert set(subsystem_registry) == {"subsystems"}
    assert all(set(s) == {"name", "environment_manifest", "release_sha",
                          "qualification_state", "interface_compatibility",
                          "clock_reset_compatibility"}
               for s in subsystem_registry["subsystems"])
