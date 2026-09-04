"""SYS-23..SYS-27: initialization-scope classification, shared-resource
scheduling, the parallelism model, scoreboard-reuse planning and
cross-subsystem check planning.

FIXTURES. The synthetic command.txt bodies are imported from
`test_subsystem_architecture_and_command_contract` rather than copied, so the
SYS-5..8, SYS-18..22 and SYS-23..27 suites cannot drift into three fixture
shapes describing three different imaginary DUTs. The registry entries built
here are synthetic too: this harness repo legitimately has no multi-subsystem
project, and every one of them describes an invented resource. Nothing in this
file writes a real System command.txt, a real System-Level environment or a
real registry -- the tmp trees exist only to be parsed and then compared
byte-for-byte against themselves.

WHAT THE HARD CASES ARE. A dedup/conflict mechanism proved only on a
happy path is not proved at all, so the suite deliberately carries: two
subsystems invoking one initialization (a SYSTEM_ONCE deduplication candidate
with a real citation from each side), two subsystems actively driving one
CPU-side BFM (a shared access point), the same pair only READING one block (no
access point, and no SHARED_RESOURCE_COMMAND), two subsystems whose registry
entry is BLOCKED by a driver conflict (unschedulable rather than scheduled), a
third independent subsystem that must NOT be serialized with the contending
pair, a control case in which an independent pair IS serialized so the
"no global serialization" check is shown to have detection power, a pair
matching two SYS-25 signals at once (precedence, with the loser kept), an
interrupt-coupled pair over read-only sharing, a clock-domain-crossing pair
over one shared address, and a supported vs. unsupported SYS-27 flow.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import subsystem_command_contract as scc
from dv_harness import system_command_plan as scp
from dv_harness import system_resource_inventory as sri
from dv_harness import system_resource_registry as srr
from dv_harness import system_scheduling_plan as ssp
from dv_harness_tests.test_subsystem_architecture_and_command_contract import (  # reused
    CONTENDING_CPU_SIDE_COMMANDS,
    CPU_SIDE_COMMANDS,
    READ_ONLY_COMMANDS,
    _write,
)

ROOT = Path(__file__).resolve().parents[1]


# --- additional synthetic command.txt fixtures -------------------------------
# Same real macro grammar; content invented for this test, describing no real
# DUT. Each exists to carry a case the imported fixtures do not.

#: A second read-only file over the SAME register block READ_ONLY_COMMANDS
#: reads, with an interrupt-classified wait after the read. The pair
#: (this, READ_ONLY_COMMANDS) shares a resource with NO writer, so
#: SERIALIZE_RESOURCE cannot fire and INTERRUPT_DEPENDENT is reachable on its
#: own rather than only as a runner-up.
INTERRUPT_READER_COMMANDS = """\
// TEST FIXTURE ONLY
initial
begin
  `CPUREAD4B (32'h1900_0000, i);
  wait(top.dut.u_core.irq_done_evt);
end
"""

#: A subsystem that touches nothing any other fixture touches. Used to prove
#: SYS-24's "Do not globally serialize independent subsystems": this one must
#: stay concurrent with a pair that is genuinely serialized.
#:
#: It calls a model task rather than a CPU macro on purpose. A `CPUWRITE4B`
#: would make it share `BFM:DUT_SIDE` with every other fixture -- the
#: HOST/DUT-side BFM is exactly the shared physical agent SYS-24 is about --
#: and the subsystem would then be genuinely coupled, which would make this
#: fixture unable to test independence at all.
INDEPENDENT_COMMANDS = """\
// TEST FIXTURE ONLY
initial
begin
  `LONERMODEL.SETUP;
end
"""

#: Two files writing ONE address from two different address-map regions, so a
#: declared region->clock mapping can put them in different clock domains while
#: they still share the address. CLOCK_DOMAIN_DEPENDENT needs exactly that
#: combination -- a different clock ALONE is two independent subsystems on two
#: clocks, which is the normal case and not a dependency.
FAST_DOMAIN_COMMANDS = """\
// TEST FIXTURE ONLY
initial
begin
  `CPUREAD4B (32'h2100_0000, i);
end
"""

SLOW_DOMAIN_COMMANDS = """\
// TEST FIXTURE ONLY
initial
begin
  `CPUREAD4B (32'h2100_0000, i);
end
"""


def _contracts(tmp_path, *, address_maps=None, region_clock_maps=None, **per_subsystem):
    """A SYS-8 contract set over synthetic command.txt files, one per named
    subsystem. Uses the real `build_contract_set()`, never a hand-built dict:
    a plan built on a fabricated contract shape would prove nothing about the
    plan the real stack produces."""
    return scc.build_contract_set(
        {name: [_write(tmp_path / name.lower() / "command.txt", text)]
         for name, text in per_subsystem.items()},
        address_maps=address_maps, region_clock_maps=region_clock_maps)


def _plan(tmp_path, *, registry_entries=None, resource_analysis=None,
          address_maps=None, region_clock_maps=None, **per_subsystem):
    contract_set = _contracts(tmp_path, address_maps=address_maps,
                              region_clock_maps=region_clock_maps, **per_subsystem)
    integration_plan = {"system_resource_registry": {
        "entries": list(registry_entries or []),
        "subsystems": sorted(per_subsystem)}}
    selection = {"selected": sorted(per_subsystem)}
    command_plan = scp.build_system_command_plan(
        integration_plan, contract_set, selection=selection)
    document = ssp.build_system_scheduling_plan(
        integration_plan, command_plan,
        resource_analysis=resource_analysis, selection=selection)
    return contract_set, command_plan, document


def _entry(document, command_id):
    return next(e for e in document["initialization_deduplication"]["entries"]
                if e["system_command_id"] == command_id)


def _entries_named(document, source_command):
    return [e for e in document["initialization_deduplication"]["entries"]
            if e["source_command"] == source_command]


def _row(document, key):
    return next((r for r in document["shared_resource_scheduling"]["entries"]
                 if r["shared_resource_key"] == key), None)


def _pair(document, subsystem_a, subsystem_b, command_a=None, command_b=None):
    for pair in document["parallelism_model"]["pairs"]:
        sides = {pair["subsystem_a"], pair["subsystem_b"]}
        if sides != {subsystem_a, subsystem_b}:
            continue
        if command_a and command_a not in (pair["command_a"], pair["command_b"]):
            continue
        if command_b and command_b not in (pair["command_a"], pair["command_b"]):
            continue
        return pair
    return None


def _registry_entry(resource_id, **overrides):
    """A synthetic SYS-15 registry entry carrying all 19 mandated fields.

    Built against `srr.SYS15_FIELDS` itself rather than a hand-typed key list,
    so a field added to the requirement makes this helper fail loudly instead
    of quietly producing an entry the real registry would never emit.
    """
    entry = {
        "resource_id": resource_id,
        "resource_type": sri.RT_CPU_BUS_MASTER,
        "protocol": "AXI4",
        "physical_hierarchy": [f"chip.{resource_id.lower()}"],
        "role": "MASTER",
        "owner": f"{srr.OWNER_PROPOSED_SYSTEM_PREFIX}::{sri.RT_CPU_BUS_MASTER}",
        "consumer_subsystems": ["PCIE", "USB"],
        "active_passive": "ACTIVE",
        "shared": srr.SHARED_ACROSS_SUBSYSTEMS,
        "exclusive": sri.EXCLUSIVE_YES,
        "clock": "chip.clk_axi",
        "reset": "chip.rst_n",
        "address_domain": [],
        "source_environment": [],
        "source_config": [],
        "conflict_status": srr.CONFLICT_NONE,
        "reuse_decision": srr.REUSE_SHARED,
        "evidence": [f"synthetic://{resource_id}"],
        "confidence": "MEDIUM",
        "member_resource_ids": [f"PCIE::{resource_id}", f"USB::{resource_id}"],
        "shareability": sri.SHAREABLE_CONDITIONAL,
        "physical_interface_id": resource_id,
        "reuse_decision_reason": "synthetic fixture",
        "related_entries": [],
        "confidence_detail": {},
        "recommendation_only": True,
    }
    missing = [f for f in srr.SYS15_FIELDS if f not in entry]
    assert not missing, f"fixture is missing mandated SYS-15 fields: {missing}"
    entry.update(overrides)
    return entry


def _analysis_linking(registry_resource_id, command_resource_ids, subsystems):
    """A minimal SYS-9 inventory carrying only the ONE field SYS-24 reads from
    it: `dependencies.command_resource_ids`, the real link that joins a
    registry entry to a command-layer resource."""
    return {"inventory": {"resources": [
        {"resource_id": f"{sid}::{registry_resource_id}",
         "owner_subsystem": sid,
         "resource_type": sri.RT_CPU_BUS_MASTER,
         "hierarchy": f"chip.{registry_resource_id.lower()}",
         "evidence": [f"synthetic://{sid}"],
         "dependencies": {"command_resource_ids": [
             {"resource_id": rid, "link_basis": "DECLARED_BY_PROJECT"}
             for rid in command_resource_ids]}}
        for sid in subsystems]}}


# ============================================================================
# Drift guards -- the requirement's own sentences vs. the code
# ============================================================================

#: SYS-23's classification list, copied verbatim from the master prompt
#: (DV_Agent_Harness_L5_ULTIMATE_COMPLETE_Master_Prompt_SystemLevel_AMBA4_
#: SyoSil_CCE_Research.md, "## SYS-23. INITIALIZATION DEDUPLICATION").
SYS23_REQUIREMENT_TEXT = (
    "SYSTEM_ONCE / SUBSYSTEM_ONCE / SCENARIO_ONCE / REPEATABLE / "
    "SHARED_RESOURCE_COMMAND")

#: SYS-25's relationship list, verbatim ("## SYS-25. PARALLELISM MODEL").
SYS25_REQUIREMENT_TEXT = (
    "PARALLEL_SAFE / SERIALIZE_RESOURCE / ORDER_DEPENDENT / INTERRUPT_DEPENDENT "
    "/ CLOCK_DOMAIN_DEPENDENT / UNKNOWN")

#: SYS-27's candidate flows, verbatim ("## SYS-27. CROSS-SUBSYSTEM CHECKING").
SYS27_REQUIREMENT_TEXT = (
    "PCIe->DDR->USB, CSI2->Memory->DSI, Ethernet->DMA->Memory, "
    "SD/eMMC->DMA->Memory, CPU/APB config->subsystem response, "
    "Interrupt->firmware->peripheral response")


def test_sys23_classes_match_the_requirements_own_sentence_one_to_one():
    expected = tuple(p.strip() for p in SYS23_REQUIREMENT_TEXT.split("/"))
    assert ssp.SYS23_CLASSES == expected


def test_sys25_relationships_match_the_requirements_own_sentence_one_to_one():
    expected = tuple(p.strip() for p in SYS25_REQUIREMENT_TEXT.split("/"))
    assert ssp.SYS25_RELATIONSHIPS == expected


def test_sys27_flows_match_the_requirements_own_sentence_one_to_one():
    expected = tuple(p.strip() for p in SYS27_REQUIREMENT_TEXT.split(","))
    assert tuple(f[1] for f in ssp.SYS27_FLOWS) == expected


def test_sys25_precedence_is_a_permutation_of_the_six_values():
    """A precedence list that dropped or duplicated a value would silently make
    one relationship unreachable."""
    assert sorted(ssp.SYS25_PRECEDENCE) == sorted(ssp.SYS25_RELATIONSHIPS)
    assert ssp.SYS25_PRECEDENCE[0] == ssp.REL_SERIALIZE_RESOURCE
    assert ssp.SYS25_PRECEDENCE[-1] == ssp.REL_UNKNOWN


def test_there_is_no_remove_action_anywhere_in_the_vocabulary():
    """SYS-23: "Do not remove commands without evidence". The strongest Phase-1
    action is naming a candidate, so no removal value exists to be reached by
    accident."""
    assert ssp.SYS23_DEDUP_ACTIONS == (ssp.DEDUP_KEEP, ssp.DEDUP_CANDIDATE)
    for action in ssp.SYS23_DEDUP_ACTIONS:
        assert "REMOVE" not in action and "DELETE" not in action


def test_vocabularies_match_the_json_schemas_enums():
    schema = json.loads(ssp.SCHEMA_PATH.read_text(encoding="utf-8"))
    dedup = schema["properties"]["initialization_deduplication"]["properties"]
    entry = dedup["entries"]["items"]["properties"]
    assert tuple(entry["scope_class"]["enum"]) == ssp.SYS23_CLASSES
    assert tuple(entry["deduplication_action"]["enum"]) == ssp.SYS23_DEDUP_ACTIONS

    scheduling = schema["properties"]["shared_resource_scheduling"]["properties"]
    row = scheduling["entries"]["items"]["properties"]
    assert sorted(row["scheduling_disposition"]["enum"]) == sorted(ssp.SYS24_DISPOSITIONS)
    assert row["access_point_status"]["const"] == ssp.ACCESS_POINT_STATUS

    parallel = schema["properties"]["parallelism_model"]["properties"]
    pair = parallel["pairs"]["items"]["properties"]
    assert sorted(pair["relationship"]["enum"]) == sorted(ssp.SYS25_RELATIONSHIPS)

    flows = schema["properties"]["cross_subsystem_checking"]["properties"]["flows"]
    assert flows["minItems"] == flows["maxItems"] == len(ssp.SYS27_FLOWS)
    assert sorted(flows["items"]["properties"]["verdict"]["enum"]) == sorted(
        ssp.SYS27_FLOW_VERDICTS)
    assert flows["items"]["properties"]["check_content_status"]["const"] == (
        ssp.CHECK_CONTENT_NOT_GENERATED)


def test_no_second_classifier_or_registry_is_defined_here():
    """A second copy of the layer below is the duplicate-mechanism failure this
    project has been bitten by before. Everything SYS-23..27 needs about
    commands, resources, sharing and concurrency is IMPORTED."""
    source = (ROOT / "dv_harness" / "system_scheduling_plan.py").read_text(encoding="utf-8")
    for forbidden in ("def build_system_command_ir", "def detect_command_collisions",
                      "def build_system_resource_registry", "def classify_resource_relationship",
                      "def resolve_cross_subsystem_concurrency", "def build_contract_set",
                      "def analyze_command_file", "def decide_reuse"):
        assert forbidden not in source, forbidden
    # The duplicate-setup classes are READ off scp's own tuple, never respelled.
    assert ssp.DUPLICATE_SETUP_COLLISIONS <= set(scp.SYS22_COLLISION_TYPES)
    # The SYS-27 intermediate resource types are sri's own constants.
    for _, _, _, groups, _ in ssp.SYS27_FLOWS:
        for group in groups:
            for resource_type in group:
                assert resource_type in sri.RESOURCE_TYPES, resource_type


# ============================================================================
# SYS-23 -- INITIALIZATION DEDUPLICATION
# ============================================================================

def test_one_initialization_invoked_by_two_subsystems_is_system_once(tmp_path):
    """The case SYS-23 exists for: `GMODEL.GLOBAL_INIT` in both files is one
    act the System needs performed once."""
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                           USB=CONTENDING_CPU_SIDE_COMMANDS)
    entries = _entries_named(document, "`GMODEL.GLOBAL_INIT")
    assert len(entries) == 2
    assert {e["source_subsystem"] for e in entries} == {"PCIE", "USB"}
    for entry in entries:
        assert entry["scope_class"] == ssp.SYSTEM_ONCE
        assert entry["duplicate_collision_id"].startswith("SYSCOL-")


def test_a_system_once_command_is_a_candidate_with_a_citation_from_each_side(tmp_path):
    """"Do not remove commands without evidence" -- the evidence is a real
    file:line from EACH subsystem, not one merged list."""
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                           USB=CONTENDING_CPU_SIDE_COMMANDS)
    entry = _entries_named(document, "`GMODEL.GLOBAL_INIT")[0]
    assert entry["deduplication_action"] == ssp.DEDUP_CANDIDATE
    assert set(entry["evidence_by_subsystem"]) == {"PCIE", "USB"}
    for sid, citations in entry["evidence_by_subsystem"].items():
        assert citations, sid
        assert any("command.txt" in c for c in citations), (sid, citations)


def test_no_command_is_ever_removed_merged_or_reordered(tmp_path):
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                           USB=CONTENDING_CPU_SIDE_COMMANDS)
    summary = document["initialization_deduplication"]["summary"]
    assert summary["commands_removed"] == 0
    assert summary["commands_merged"] == 0
    assert summary["commands_reordered"] == 0
    assert all(e["deduplication_action"] in ssp.SYS23_DEDUP_ACTIONS
               for e in document["initialization_deduplication"]["entries"])


def test_a_duplicate_backed_by_only_one_sides_citation_stays_KEEP():
    """Detection power for the evidence rule. A SYSTEM_ONCE verdict whose
    finding cites only one subsystem is a claim about the other subsystem that
    nothing supports, so it must not become a candidate."""
    ir = {"entries": [{
        "system_command_id": "PCIE::`GMODEL.GLOBAL_INIT",
        "source_subsystem": "PCIE", "source_command": "`GMODEL.GLOBAL_INIT",
        "command_category": "INITIALIZATION", "target_resource": [], "arguments": [],
        "preconditions": [], "postconditions": [], "dependencies": [],
        "parallel_group": "", "serialization_group": "", "shared_resource": [],
        "evidence": [], "derivation": {}}]}
    collisions = {"collisions": [{
        "collision_id": "SYSCOL-ONESIDED", "collision_type": scp.DUPLICATE_INITIALIZATION,
        "subject": "`GMODEL.GLOBAL_INIT", "subsystems": ["PCIE", "USB"],
        "commands": ["PCIE::`GMODEL.GLOBAL_INIT"],
        "evidence_by_subsystem": {"PCIE": ["pcie/command.txt:5"]}}]}
    result = ssp.classify_initialization_deduplication(ir, collisions, {"entries": []})
    entry = result["entries"][0]
    assert entry["scope_class"] == ssp.SYSTEM_ONCE
    assert entry["deduplication_action"] == ssp.DEDUP_KEEP
    assert str(ssp.MIN_EVIDENCE_SIDES_FOR_CANDIDATE) in entry["deduplication_action_reason"]


def test_a_command_contending_on_a_shared_resource_is_a_shared_resource_command(tmp_path):
    """Not a dedup question at all -- SYS-24 schedules it, and the label says
    so rather than proposing a removal."""
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                           USB=CONTENDING_CPU_SIDE_COMMANDS)
    writes = _entries_named(document, "CPUWRITE4B")
    assert writes
    for entry in writes:
        assert entry["scope_class"] == ssp.SHARED_RESOURCE_COMMAND
        assert entry["contended_resources"]
        assert entry["deduplication_action"] == ssp.DEDUP_KEEP


def test_a_read_only_shared_block_is_never_a_shared_resource_command(tmp_path):
    """Two subsystems only READING one block is not contention, and labelling
    it as such is how a dedup mechanism trains its users to ignore it."""
    _, _, document = _plan(tmp_path, ALPHA=READ_ONLY_COMMANDS, BETA=READ_ONLY_COMMANDS)
    reads = _entries_named(document, "CPUREAD4B")
    assert reads
    for entry in reads:
        assert entry["scope_class"] != ssp.SHARED_RESOURCE_COMMAND
        assert entry["contended_resources"] == []


def test_a_command_invoked_more_than_once_in_its_own_file_is_repeatable(tmp_path):
    """The evidence is the contract's own multiple distinct addresses, cited --
    not a new invocation counter and not a naming convention."""
    _, _, document = _plan(tmp_path, SOLO=CPU_SIDE_COMMANDS)
    entry = _entry(document, "SOLO::CPUWRITE4B")
    assert entry["scope_class"] == ssp.REPEATABLE
    assert entry["repeat_evidence"]["repeated"] is True
    assert entry["repeat_evidence"]["evidence"]


def test_an_initialization_no_other_subsystem_invokes_is_subsystem_once(tmp_path):
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, LONER=INDEPENDENT_COMMANDS)
    entry = _entry(document, "PCIE::`GMODEL.GLOBAL_INIT")
    assert entry["scope_class"] == ssp.SUBSYSTEM_ONCE
    assert entry["deduplication_action"] == ssp.DEDUP_KEEP


def test_an_observing_command_is_repeatable_and_never_a_candidate(tmp_path):
    """`$display` establishes nothing, so running it again deduplicates
    nothing. The basis names the CATEGORY, not a repeated-invocation count --
    a command with neither is still never a removal candidate."""
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, LONER=INDEPENDENT_COMMANDS)
    entry = _entry(document, "PCIE::$display")
    assert entry["command_category"] == "OBSERVATION"
    assert entry["scope_class"] == ssp.REPEATABLE
    assert entry["repeat_evidence"]["repeated"] is False
    assert "observes and establishes nothing" in entry["scope_basis"]
    assert entry["deduplication_action"] == ssp.DEDUP_KEEP


def test_every_classification_records_its_own_basis(tmp_path):
    """A verdict whose basis is not recorded next to it cannot be checked."""
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                           USB=CONTENDING_CPU_SIDE_COMMANDS)
    for entry in document["initialization_deduplication"]["entries"]:
        assert entry["scope_basis"].strip()
        assert entry["deduplication_action_reason"].strip()


def test_a_removal_action_is_refused_by_the_boundary_check(tmp_path):
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                           USB=CONTENDING_CPU_SIDE_COMMANDS)
    document["initialization_deduplication"]["entries"][0]["deduplication_action"] = "REMOVE"
    with pytest.raises(ssp.SystemSchedulingPlanError) as excinfo:
        ssp.assert_no_emitted_artifacts(document)
    assert excinfo.value.reason == "COMMAND_REMOVAL_PROPOSED"


def test_a_candidate_without_two_evidence_sides_is_refused_by_the_boundary_check(tmp_path):
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                           USB=CONTENDING_CPU_SIDE_COMMANDS)
    entry = _entries_named(document, "`GMODEL.GLOBAL_INIT")[0]
    entry["evidence_by_subsystem"] = {"PCIE": ["pcie/command.txt:5"]}
    with pytest.raises(ssp.SystemSchedulingPlanError) as excinfo:
        ssp.assert_no_emitted_artifacts(document)
    assert excinfo.value.reason == "DEDUPLICATION_CANDIDATE_WITHOUT_EVIDENCE"


# ============================================================================
# SYS-24 -- SHARED RESOURCE SCHEDULING
# ============================================================================

def test_two_subsystems_driving_one_bfm_get_one_named_access_point(tmp_path):
    """SYS-24's first sentence, on the command evidence axis: the DUT/host-side
    BFM two subsystems both write is one shared physical agent, and every user
    routes through one access point."""
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                           USB=CONTENDING_CPU_SIDE_COMMANDS)
    row = _row(document, "BFM:DUT_SIDE")
    assert row is not None
    assert row["scheduling_disposition"] == ssp.SCHED_SINGLE_SHARED_ACCESS_POINT
    assert row["consumer_subsystems"] == ["PCIE", "USB"]
    assert row["shared_access_point"].startswith(ssp.ACCESS_POINT_PREFIX)
    assert row["access_point_status"] == ssp.ACCESS_POINT_STATUS
    assert row["arbitration_policy_required"] is True
    assert row["routed_commands"], "the commands that would route are named"
    assert row["evidence_axes"] == [ssp.AXIS_COMMAND]


def test_the_named_access_point_is_never_built(tmp_path):
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                           USB=CONTENDING_CPU_SIDE_COMMANDS)
    assert document["summary"]["shared_access_points_built"] == 0
    assert document["shared_resource_scheduling"]["summary"][
        "shared_access_points_built"] == 0
    for row in document["shared_resource_scheduling"]["entries"]:
        assert row["access_point_status"] == ssp.ACCESS_POINT_STATUS
    row = document["shared_resource_scheduling"]["entries"][0]
    row["access_point_status"] = "IMPLEMENTED"
    with pytest.raises(ssp.SystemSchedulingPlanError) as excinfo:
        ssp.assert_no_emitted_artifacts(document)
    assert excinfo.value.reason == "SHARED_ACCESS_POINT_IMPLEMENTED"


def test_a_read_only_shared_block_gets_no_access_point(tmp_path):
    """Two readers need no arbiter, and proposing one would be scheduling
    derived from nothing."""
    _, _, document = _plan(tmp_path, ALPHA=READ_ONLY_COMMANDS, BETA=READ_ONLY_COMMANDS)
    assert document["shared_resource_scheduling"]["summary"][
        "shared_access_points_named"] == 0
    for row in document["shared_resource_scheduling"]["entries"]:
        assert row["shared_access_point"] == ssp.NO_ACCESS_POINT
        assert row["arbitration_policy_required"] is False


def test_a_blocked_registry_entry_is_unschedulable_not_scheduled(tmp_path):
    """SYS-12's stop, honoured at the scheduling layer. Proposing a shared
    access point for a resource whose ownership is unresolved would step past
    that stop."""
    blocked = _registry_entry("CPU_AXI_MASTER", reuse_decision=srr.BLOCKED,
                              conflict_status=srr.CONFLICT_DRIVER,
                              owner=srr.OWNER_UNRESOLVED,
                              reuse_decision_reason="two ACTIVE agents claim one interface")
    _, _, document = _plan(tmp_path, registry_entries=[blocked],
                           PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    row = _row(document, "CPU_AXI_MASTER")
    assert row["scheduling_disposition"] == ssp.SCHED_NOT_SCHEDULABLE
    assert row["shared_access_point"] == ssp.NO_ACCESS_POINT
    assert row["arbitration_policy_required"] is False
    assert document["summary"]["scheduling_plan_clean"] is False


def test_a_single_consumer_registry_entry_stays_subsystem_local(tmp_path):
    """SYS-24's second sentence made structural: hoisting an unshared resource
    into a System access point is the same mistake as serializing independent
    subsystems."""
    local = _registry_entry("PCIE_LOCAL_DMA", shared=srr.NOT_SHARED,
                            consumer_subsystems=["PCIE"], owner="PCIE",
                            member_resource_ids=["PCIE::PCIE_LOCAL_DMA"],
                            reuse_decision=srr.KEEP_INDEPENDENT)
    _, _, document = _plan(tmp_path, registry_entries=[local],
                           PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    row = _row(document, "PCIE_LOCAL_DMA")
    assert row["scheduling_disposition"] == ssp.SCHED_KEEP_SUBSYSTEM_LOCAL
    assert row["shared_access_point"] == ssp.NO_ACCESS_POINT


def test_a_passive_only_entry_needs_no_arbitration(tmp_path):
    passive = _registry_entry("APB_MONITOR", resource_type=sri.RT_APB_MASTER,
                              active_passive="PASSIVE",
                              exclusive=sri.EXCLUSIVE_NO,
                              reuse_decision=srr.PASSIVE_ONLY)
    _, _, document = _plan(tmp_path, registry_entries=[passive],
                           PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    row = _row(document, "APB_MONITOR")
    assert row["scheduling_disposition"] == ssp.SCHED_PASSIVE_NO_ARBITRATION
    assert row["shared_access_point"] == ssp.NO_ACCESS_POINT


def test_every_scheduling_decision_cites_the_real_field_it_derived_from(tmp_path):
    """SYS-24: "Scheduling must derive from actual resource/protocol
    constraints"."""
    shared = _registry_entry("CPU_AXI_MASTER")
    _, _, document = _plan(tmp_path, registry_entries=[shared],
                           PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    row = _row(document, "CPU_AXI_MASTER")
    assert row["scheduling_disposition"] == ssp.SCHED_SINGLE_SHARED_ACCESS_POINT
    fields = {c["from_field"] for c in row["scheduling_constraints"]}
    assert "system_resource_registry.exclusive" in fields
    assert "system_resource_registry.protocol" in fields
    for constraint in row["scheduling_constraints"]:
        assert constraint["constraint"] and constraint["value"]


def test_a_shared_entry_with_no_derivable_constraint_is_unknown_not_defaulted(tmp_path):
    """A scheduling policy nothing derived would be an invented verification
    parameter presented as evidence."""
    bare = _registry_entry("MYSTERY_RESOURCE", exclusive=sri.EXCLUSIVE_UNKNOWN,
                           active_passive="", protocol="PROTOCOL_NOT_CLASSIFIED",
                           clock=sri.UNRESOLVED, reset=sri.UNRESOLVED,
                           reuse_decision=srr.REUSE_SHARED)
    _, _, document = _plan(tmp_path, registry_entries=[bare],
                           PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    row = _row(document, "MYSTERY_RESOURCE")
    assert row["scheduling_disposition"] == ssp.SCHED_UNKNOWN
    assert row["scheduling_constraints"] == []
    assert "actual constraints" in row["scheduling_reason"]


def test_the_two_evidence_axes_are_joined_into_one_row_not_reported_twice(tmp_path):
    """A resource seen by BOTH the registry and the command layer is ONE shared
    agent. Two rows would present it as two consumable resources -- the same
    defect the registry itself refuses at its own layer."""
    shared = _registry_entry("CPU_AXI_MASTER")
    analysis = _analysis_linking("CPU_AXI_MASTER", ["BFM:DUT_SIDE"], ["PCIE", "USB"])
    _, _, document = _plan(tmp_path, registry_entries=[shared], resource_analysis=analysis,
                           PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    keys = [r["shared_resource_key"] for r in document["shared_resource_scheduling"]["entries"]]
    assert "BFM:DUT_SIDE" not in keys, "the command-layer id was folded into the entry"
    row = _row(document, "CPU_AXI_MASTER")
    assert row["evidence_axes"] == [ssp.AXIS_REGISTRY, ssp.AXIS_COMMAND]
    assert row["command_resource_ids"] == ["BFM:DUT_SIDE"]
    assert row["routed_commands"], "the joined row names the commands that would route"
    assert row["writing_subsystems"] == ["PCIE", "USB"]


def test_an_unlinked_registry_entry_says_so_rather_than_guessing_its_commands(tmp_path):
    shared = _registry_entry("CPU_AXI_MASTER")
    _, _, document = _plan(tmp_path, registry_entries=[shared],
                           PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    row = _row(document, "CPU_AXI_MASTER")
    assert row["routed_commands"] == []
    assert "no SYS-9 inventory link" in row["routed_commands_reason"]


def test_independent_subsystems_are_not_globally_serialized(tmp_path):
    """SYS-24's second sentence. PCIE and USB genuinely contend; LONER touches
    nothing either of them touches and must stay concurrent with both."""
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                           USB=CONTENDING_CPU_SIDE_COMMANDS, LONER=INDEPENDENT_COMMANDS)
    check = document["global_serialization_check"]
    assert check["verdict"] == ssp.NO_GLOBAL_SERIALIZATION
    assert check["violations"] == []
    assert ["PCIE", "USB"] in check["coupled_subsystem_pairs"]
    independent = {tuple(p) for p in check["independent_subsystem_pairs"]}
    assert ("LONER", "PCIE") in independent and ("LONER", "USB") in independent
    for pair in document["parallelism_model"]["pairs"]:
        if "LONER" in (pair["subsystem_a"], pair["subsystem_b"]):
            assert pair["relationship"] != ssp.REL_SERIALIZE_RESOURCE


def test_the_global_serialization_check_really_detects_a_violation():
    """Control case. A check that has never fired is not evidence that nothing
    fires it."""
    scheduling = {"entries": [{"consumer_subsystems": ["PCIE", "USB"],
                               "shared_resource_key": "BFM:DUT_SIDE",
                               "arbitration_policy_required": True}]}
    relationships = {"pairs": [{
        "pair_id": "SYSPAIR-CONTROL", "subsystem_a": "LONER", "subsystem_b": "PCIE",
        "relationship": ssp.REL_SERIALIZE_RESOURCE, "basis": "fabricated for this control",
        "serialization_groups_a": ["SERIALIZE::X"], "serialization_groups_b": ["SERIALIZE::X"]}]}
    check = ssp.check_no_global_serialization(
        scheduling, relationships, ["LONER", "PCIE", "USB"])
    assert check["verdict"] == ssp.GLOBAL_SERIALIZATION_DETECTED
    reasons = {v["reason"] for v in check["violations"]}
    assert reasons == {"SERIALIZE_RESOURCE_ON_AN_INDEPENDENT_PAIR",
                       "SHARED_SERIALIZATION_GROUP"}


def test_the_contention_gate_input_is_derived_and_invents_no_testcase_ids(tmp_path):
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                           USB=CONTENDING_CPU_SIDE_COMMANDS)
    gate_input = document["resource_contention_gate_input"]
    assert "BFM:DUT_SIDE" in gate_input["shared_resources"]
    assert gate_input["scenarios"] == []
    assert "contention_testcase_ids" in gate_input["scenarios_not_derived_reason"]
    assert "system_scheduling_plan" in gate_input["derived_from"]


def test_the_contention_gate_input_is_accepted_by_the_real_wired_gate(tmp_path):
    """The already-wired `system_level_resource_contention_gate.py` (registered
    in gates.STAGE_GATES["SYSTEM_LEVEL"]) is run as a real subprocess against
    the block this planner derives -- so the two mechanisms are joined rather
    than being two contention models."""
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                           USB=CONTENDING_CPU_SIDE_COMMANDS)
    plan_path = tmp_path / "contention_plan.json"
    plan_path.write_text(json.dumps(document["resource_contention_gate_input"]),
                         encoding="utf-8")
    gate = ROOT / "tools" / "verification_flow" / "system_level_resource_contention_gate.py"
    assert gate.is_file()
    result = subprocess.run([sys.executable, str(gate), "--plan", str(plan_path)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "PASS"


# ============================================================================
# SYS-25 -- PARALLELISM MODEL
# ============================================================================

def test_two_commands_contending_on_one_resource_are_serialize_resource(tmp_path):
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                           USB=CONTENDING_CPU_SIDE_COMMANDS)
    pair = _pair(document, "PCIE", "USB",
                 command_a="PCIE::CPUWRITE4B",
                 command_b="USB::CPUWRITE4B")
    assert pair is not None
    assert pair["relationship"] == ssp.REL_SERIALIZE_RESOURCE
    assert "shared_resource_dependency" in pair["from_field"]


def test_precedence_keeps_the_losing_signal_rather_than_discarding_it(tmp_path):
    """A pair that is BOTH contended and order-dependent reports the more
    restrictive verdict and still records the other reason. A single-valued
    enum that silently dropped the second reason would be a worse report than
    one that never noticed it."""
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                           USB=CONTENDING_CPU_SIDE_COMMANDS)
    multi = [p for p in document["parallelism_model"]["pairs"] if p["also_matched"]]
    assert multi, "no pair matched more than one SYS-25 signal"
    for pair in multi:
        matched = {s["relationship"] for s in pair["signals"]}
        winner = next(r for r in ssp.SYS25_PRECEDENCE if r in matched)
        assert pair["relationship"] == winner
        assert set(pair["also_matched"]) == matched - {winner}


def test_one_initialization_shared_by_two_subsystems_makes_an_order_dependency(tmp_path):
    """PCIE's commands require `GMODEL.GLOBAL_INIT` to have run; USB invokes
    that same initialization and can re-run it afterwards."""
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                           USB=CONTENDING_CPU_SIDE_COMMANDS)
    pair = _pair(document, "PCIE", "USB",
                 command_a="PCIE::CPUREAD4B",
                 command_b="USB::`GMODEL.GLOBAL_INIT")
    assert pair is not None
    assert ssp.REL_ORDER_DEPENDENT in (
        {pair["relationship"]} | set(pair["also_matched"]))


def test_a_same_named_within_file_ordering_edge_never_creates_a_cross_subsystem_order(tmp_path):
    """Two subsystems whose files both contain `CPUREAD4B` share a macro NAME
    and nothing else. An ordering edge inside one file is a statement about
    that file's own order, and matching it across subsystems would claim an
    order neither file states."""
    _, _, document = _plan(tmp_path, ALPHA=READ_ONLY_COMMANDS, BETA=READ_ONLY_COMMANDS)
    pair = _pair(document, "ALPHA", "BETA")
    assert pair is not None
    assert ssp.REL_ORDER_DEPENDENT not in (
        {pair["relationship"]} | set(pair["also_matched"]))
    assert all(s["from_field"] != "system_command_ir.dependencies"
               for s in pair["signals"])


def test_an_interrupt_handshake_over_a_shared_block_is_interrupt_dependent(tmp_path):
    """Read-only sharing, so SERIALIZE_RESOURCE cannot fire and
    INTERRUPT_DEPENDENT is reached on its own."""
    _, _, document = _plan(tmp_path, ALPHA=READ_ONLY_COMMANDS,
                           BETA=INTERRUPT_READER_COMMANDS)
    pair = _pair(document, "ALPHA", "BETA",
                 command_a="ALPHA::CPUREAD4B",
                 command_b="BETA::CPUREAD4B")
    assert pair is not None
    assert pair["relationship"] == ssp.REL_INTERRUPT_DEPENDENT
    assert "interrupt_dependency" in pair["from_field"]


def test_two_clock_domains_over_one_shared_address_is_clock_domain_dependent(tmp_path):
    """A different clock ALONE is two independent subsystems on two clocks --
    the normal case. The dependency needs the crossing to be over something
    they share."""
    address_map = [{"name": "PERIPH_A", "base_address": "32'h2100_0000",
                    "size_bytes": 0x1000}]
    _, _, document = _plan(
        tmp_path,
        address_maps={"FAST": address_map, "SLOW": address_map},
        region_clock_maps={"FAST": {"PERIPH_A": "chip.clk_fast"},
                           "SLOW": {"PERIPH_A": "chip.clk_slow"}},
        FAST=FAST_DOMAIN_COMMANDS, SLOW=SLOW_DOMAIN_COMMANDS)
    pair = _pair(document, "FAST", "SLOW")
    assert pair is not None
    assert pair["relationship"] == ssp.REL_CLOCK_DOMAIN_DEPENDENT
    assert "chip.clk_fast" in pair["basis"] and "chip.clk_slow" in pair["basis"]


def test_two_unrelated_subsystems_stay_parallel_safe(tmp_path):
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, LONER=INDEPENDENT_COMMANDS)
    pair = _pair(document, "PCIE", "LONER",
                 command_a="PCIE::`SMEMMODEL.FILLMEM",
                 command_b="LONER::`LONERMODEL.SETUP")
    assert pair is not None
    assert pair["relationship"] == ssp.REL_PARALLEL_SAFE
    assert document["summary"]["parallel_pairs_preserved"] > 0


def test_a_single_subsystem_set_produces_no_pair_at_all(tmp_path):
    """A command.txt is sequential by construction, so its own commands' order
    is already stated and the six-value vocabulary carries no information."""
    _, _, document = _plan(tmp_path, SOLO=CPU_SIDE_COMMANDS)
    assert document["parallelism_model"]["pairs"] == []
    assert document["parallelism_model"]["summary"]["cross_subsystem_only"] is True


def test_an_undecidable_pair_reports_unknown_rather_than_a_guess(tmp_path):
    """UNKNOWN is reachable and used: neither side was decided parallel-safe
    and no contention, ordering, interrupt or clock evidence links them."""
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                           USB=CONTENDING_CPU_SIDE_COMMANDS)
    unknown = [p for p in document["parallelism_model"]["pairs"]
               if p["relationship"] == ssp.REL_UNKNOWN]
    assert unknown
    for pair in unknown:
        assert pair["signals"] == []
        assert "no SYS-25 signal matched" in pair["basis"]


def test_pair_ids_are_stable_across_runs(tmp_path):
    _, _, first = _plan(tmp_path / "a", PCIE=CPU_SIDE_COMMANDS,
                        USB=CONTENDING_CPU_SIDE_COMMANDS)
    _, _, second = _plan(tmp_path / "b", PCIE=CPU_SIDE_COMMANDS,
                         USB=CONTENDING_CPU_SIDE_COMMANDS)
    assert ([p["pair_id"] for p in first["parallelism_model"]["pairs"]]
            == [p["pair_id"] for p in second["parallelism_model"]["pairs"]])


# ============================================================================
# SYS-26 -- SCOREBOARD INTEGRATION
# ============================================================================

def test_each_subsystems_own_scoreboard_is_reused_unmodified(tmp_path):
    scoreboard = _registry_entry("PCIE_SCOREBOARD", resource_type=sri.RT_SCOREBOARD,
                                 consumer_subsystems=["PCIE"], shared=srr.NOT_SHARED,
                                 member_resource_ids=["PCIE::PCIE_SCOREBOARD"],
                                 reuse_decision=srr.KEEP_INDEPENDENT)
    _, _, document = _plan(tmp_path, registry_entries=[scoreboard],
                           PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    rows = {r["subsystem_id"]: r for r in document["scoreboard_integration"]["subsystems"]}
    assert rows["PCIE"]["disposition"] == ssp.SCOREBOARD_REUSE_EXISTING
    assert rows["PCIE"]["subsystem_scoreboards"][0]["resource_id"] == "PCIE_SCOREBOARD"
    for row in rows.values():
        assert row["subsystem_scoreboard_modified"] is False
        assert row["replaced_by_monolithic_scoreboard"] is False


def test_a_subsystem_with_no_scoreboard_in_evidence_says_so(tmp_path):
    """An absence in the evidence, never a finding that the subsystem has none
    -- and never a reason to write a replacement."""
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                           USB=CONTENDING_CPU_SIDE_COMMANDS)
    for row in document["scoreboard_integration"]["subsystems"]:
        assert row["disposition"] == ssp.SCOREBOARD_NONE_IN_EVIDENCE
        assert "absence in the evidence" in row["reason"]
        assert row["replaced_by_monolithic_scoreboard"] is False


def test_a_monolithic_replacement_is_refused_by_the_boundary_check(tmp_path):
    """SYS-26's second sentence, as a CHECK. In soc_environment_composer the
    same guarantee holds only by omission; here it can actually fail."""
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                           USB=CONTENDING_CPU_SIDE_COMMANDS)
    document["scoreboard_integration"]["subsystems"][0][
        "replaced_by_monolithic_scoreboard"] = True
    with pytest.raises(ssp.SystemSchedulingPlanError) as excinfo:
        ssp.assert_no_emitted_artifacts(document)
    assert excinfo.value.reason == "SUBSYSTEM_SCOREBOARD_REPLACED"


def test_the_correlation_layer_is_named_and_never_implemented(tmp_path):
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                           USB=CONTENDING_CPU_SIDE_COMMANDS)
    correlation = document["scoreboard_integration"]["system_correlation_layer"]
    assert correlation["name"] == ssp.CORRELATION_LAYER_NAME
    assert correlation["status"] == ssp.CORRELATION_LAYER_STATUS
    assert correlation["replaces_subsystem_scoreboards"] is False
    document["scoreboard_integration"]["system_correlation_layer"]["status"] = "BUILT"
    with pytest.raises(ssp.SystemSchedulingPlanError) as excinfo:
        ssp.assert_no_emitted_artifacts(document)
    assert excinfo.value.reason == "CORRELATION_LAYER_IMPLEMENTED"


def test_the_missing_topology_descriptor_is_itemised_part_by_part(tmp_path):
    """Reporting one blanket "not available" would hide that a selection may
    already carry real address regions and be missing only the interrupt map."""
    with_addresses = _registry_entry(
        "DDR_MEMORY", resource_type=sri.RT_MEMORY_MODEL,
        address_domain=[{"owner_subsystem": "PCIE", "status": "RESOLVED",
                         "regions": [{"name": "DDR", "start": 0, "end": 0x1000}]}])
    _, _, document = _plan(tmp_path, registry_entries=[with_addresses],
                           PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    parts = {p["part"]: p for p in document["scoreboard_integration"][
        "system_correlation_layer"]["topology_descriptor_requirement"]}
    assert tuple(parts) == ssp.TOPOLOGY_DESCRIPTOR_PARTS
    assert parts[ssp.TOPO_ADDRESS_MAP]["status"] == ssp.TOPO_PRESENT
    assert parts[ssp.TOPO_ADDRESS_MAP]["evidence"] == ["DDR"]
    assert parts[ssp.TOPO_INTERRUPT_MAP]["status"] == ssp.TOPO_ABSENT
    assert parts[ssp.TOPO_DMA_MAP]["status"] == ssp.TOPO_ABSENT
    assert document["scoreboard_integration"]["summary"][
        "topology_descriptor_parts_missing"] == 2


# ============================================================================
# SYS-27 -- CROSS-SUBSYSTEM CHECKING
# ============================================================================

def test_a_flow_whose_endpoints_and_intermediate_are_all_present_is_supported(tmp_path):
    ddr = _registry_entry("DDR_MEMORY", resource_type=sri.RT_MEMORY_MODEL)
    _, _, document = _plan(tmp_path, registry_entries=[ddr],
                           PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    flow = next(f for f in document["cross_subsystem_checking"]["flows"]
                if f["flow_id"] == "PCIE_DDR_USB")
    assert flow["verdict"] == ssp.FLOW_SUPPORTED
    assert flow["participating_subsystems"] == ["PCIE", "USB"]
    assert flow["cross_subsystem"] is True
    assert {e["subsystem_id"] for e in flow["matched_endpoints"]} == {"PCIE", "USB"}
    assert flow["satisfied_intermediate_resources"][0]["registry_entries"] == ["DDR_MEMORY"]


def test_a_flow_missing_its_intermediate_resource_is_not_supported(tmp_path):
    """PCIe and USB are both selected, but nothing in the registry is a memory
    model, so PCIe->DDR->USB has no DDR to cross."""
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                           USB=CONTENDING_CPU_SIDE_COMMANDS)
    flow = next(f for f in document["cross_subsystem_checking"]["flows"]
                if f["flow_id"] == "PCIE_DDR_USB")
    assert flow["verdict"] == ssp.FLOW_INTERMEDIATE_ABSENT
    assert flow["missing_intermediate_resource_groups"] == [[sri.RT_MEMORY_MODEL]]
    assert flow["required_check_inputs"] == []


def test_a_flow_whose_endpoint_subsystem_is_not_selected_is_not_supported(tmp_path):
    ddr = _registry_entry("DDR_MEMORY", resource_type=sri.RT_MEMORY_MODEL)
    _, _, document = _plan(tmp_path, registry_entries=[ddr],
                           PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    flow = next(f for f in document["cross_subsystem_checking"]["flows"]
                if f["flow_id"] == "CSI2_MEMORY_DSI")
    assert flow["verdict"] == ssp.FLOW_ENDPOINT_ABSENT
    assert flow["missing_endpoint_groups"]


def test_one_subsystem_cannot_be_both_ends_of_a_cross_subsystem_flow(tmp_path):
    """A selection of one PCIe subsystem plus a DDR model does not make
    PCIe->DDR->USB real, however the tokens line up."""
    ddr = _registry_entry("DDR_MEMORY", resource_type=sri.RT_MEMORY_MODEL,
                          consumer_subsystems=["PCIE_USB_BRIDGE"],
                          member_resource_ids=["PCIE_USB_BRIDGE::DDR_MEMORY"])
    _, _, document = _plan(tmp_path, registry_entries=[ddr],
                           PCIE_USB_BRIDGE=CPU_SIDE_COMMANDS)
    flow = next(f for f in document["cross_subsystem_checking"]["flows"]
                if f["flow_id"] == "PCIE_DDR_USB")
    assert flow["verdict"] == ssp.FLOW_ENDPOINT_ABSENT


def test_endpoint_matching_tolerates_a_version_suffix_but_is_not_a_substring_match():
    """`USB3` matches USB; `SDIO` is its own token and is not reached through a
    substring of `SD`."""
    assert "USB" in ssp._name_tokens("USB3_DEVICE")
    assert "USB3" in ssp._name_tokens("USB3_DEVICE")
    assert "CSI2" in ssp._name_tokens("MIPI_CSI2") and "CSI" in ssp._name_tokens("MIPI_CSI2")
    assert "SD" not in ssp._name_tokens("SDIO_HOST")
    assert "SDIO" in ssp._name_tokens("SDIO_HOST")


def test_a_supported_flow_names_what_a_check_would_need_and_writes_none(tmp_path):
    ddr = _registry_entry("DDR_MEMORY", resource_type=sri.RT_MEMORY_MODEL)
    _, _, document = _plan(tmp_path, registry_entries=[ddr],
                           PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    flow = next(f for f in document["cross_subsystem_checking"]["flows"]
                if f["flow_id"] == "PCIE_DDR_USB")
    assert flow["check_content_status"] == ssp.CHECK_CONTENT_NOT_GENERATED
    inputs = {i["input"] for i in flow["required_check_inputs"]}
    assert inputs == {name for name, _ in ssp.SYS27_REQUIRED_CHECK_INPUTS}
    for required in flow["required_check_inputs"]:
        assert required["availability"] == ssp.CHECK_INPUT_NOT_AVAILABLE
        assert "Golden-Reference" in required["reason"]
    assert document["cross_subsystem_checking"]["summary"]["checks_generated"] == 0


def test_generated_check_content_is_refused_by_the_boundary_check(tmp_path):
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                           USB=CONTENDING_CPU_SIDE_COMMANDS)
    document["cross_subsystem_checking"]["flows"][0]["check_content_status"] = "GENERATED"
    with pytest.raises(ssp.SystemSchedulingPlanError) as excinfo:
        ssp.assert_no_emitted_artifacts(document)
    assert excinfo.value.reason == "CROSS_SUBSYSTEM_CHECK_CONTENT_GENERATED"


def test_a_single_participant_flow_is_flagged_against_the_composition_gate(tmp_path):
    """`system_level_composition_gate.py` refuses a scenario naming fewer than
    two subsystems with NOT_CROSS_SUBSYSTEM_SCENARIO, so a flow that would hit
    that says so rather than reading as ready to declare."""
    cpu = _registry_entry("CPU_AXI_MASTER", consumer_subsystems=["SOLO"],
                          shared=srr.NOT_SHARED,
                          member_resource_ids=["SOLO::CPU_AXI_MASTER"])
    _, _, document = _plan(tmp_path, registry_entries=[cpu], SOLO=CPU_SIDE_COMMANDS)
    flow = next(f for f in document["cross_subsystem_checking"]["flows"]
                if f["flow_id"] == "CPU_APB_CONFIG_RESPONSE")
    assert flow["cross_subsystem"] is False
    assert "NOT_CROSS_SUBSYSTEM_SCENARIO" in flow["composition_gate_note"]


# ============================================================================
# The SYS-39/SYS-40 boundary
# ============================================================================

def test_the_composer_stubs_are_probed_and_still_raise(tmp_path):
    """SYS-26/27's "content is out of scope" is a CHECKED fact in every
    produced document, not a comment that can go stale."""
    _, _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                           USB=CONTENDING_CPU_SIDE_COMMANDS)
    boundary = document["composer_boundary"]
    assert boundary["boundary_intact"] is True
    assert ([p["function"] for p in boundary["probes"]]
            == list(ssp.COMPOSER_BOUNDARY_FUNCTIONS))
    for probe in boundary["probes"]:
        assert probe["raises"] == "NotImplementedError"
        assert probe["reason"]
    assert document["summary"]["composer_boundary_intact"] is True


def test_this_module_holds_no_file_writer_at_all():
    """Unlike SYS-15..17's layer, which persists a registry, this layer
    persists nothing -- so the check is for ZERO writers, not a bounded
    number."""
    source = (ROOT / "dv_harness" / "system_scheduling_plan.py").read_text(encoding="utf-8")
    for writer in (".write_text(", ".write_bytes(", "open(", "os.replace",
                   "shutil.copy", "mkdir("):
        assert writer not in source, writer


def test_the_rendered_report_contains_no_systemverilog(tmp_path):
    ddr = _registry_entry("DDR_MEMORY", resource_type=sri.RT_MEMORY_MODEL)
    _, _, document = _plan(tmp_path, registry_entries=[ddr],
                           PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    report = ssp.format_system_scheduling_plan_report(document)
    for token in ("module ", "endmodule", "class ", "endclass", "uvm_component_utils",
                  "task ", "endtask", "function ", "endfunction", "`uvm_"):
        assert token not in report, token
    assert "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED" in report


def test_a_full_run_leaves_every_subsystem_tree_byte_identical(tmp_path):
    """Read-only, proven by comparison rather than by intent."""
    def snapshot(root):
        return {str(p.relative_to(root)): p.read_bytes()
                for p in sorted(root.rglob("*")) if p.is_file()}

    contract_set = _contracts(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                              USB=CONTENDING_CPU_SIDE_COMMANDS)
    before = snapshot(tmp_path)
    integration_plan = {"system_resource_registry": {
        "entries": [_registry_entry("CPU_AXI_MASTER")], "subsystems": ["PCIE", "USB"]}}
    selection = {"selected": ["PCIE", "USB"]}
    command_plan = scp.build_system_command_plan(
        integration_plan, contract_set, selection=selection)
    document = ssp.build_system_scheduling_plan(
        integration_plan, command_plan, selection=selection)
    ssp.format_system_scheduling_plan_report(document)
    assert snapshot(tmp_path) == before


def test_no_system_level_artifact_appears_anywhere_after_a_full_run(tmp_path):
    _, _, _ = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    names = {p.name for p in tmp_path.rglob("*") if p.is_file()}
    for forbidden in ("system_command.txt", "soc_command.txt", "soc_tb_top.sv",
                      "system_virtual_sequencer.sv", "system_scoreboard.sv",
                      "system_resource_registry.json"):
        assert forbidden not in names, forbidden
    assert all(p.name == "command.txt" for p in tmp_path.rglob("*") if p.is_file())


def test_the_document_validates_against_the_real_json_schema(tmp_path):
    ddr = _registry_entry("DDR_MEMORY", resource_type=sri.RT_MEMORY_MODEL)
    analysis = _analysis_linking("DDR_MEMORY", ["BFM:DUT_SIDE"], ["PCIE", "USB"])
    _, _, document = _plan(tmp_path, registry_entries=[ddr], resource_analysis=analysis,
                           PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    ssp.validate_system_scheduling_plan(document)
    assert document["artifacts_generated"] == []


def test_an_empty_selection_plans_nothing(tmp_path):
    document = ssp.build_system_scheduling_plan(
        {"system_resource_registry": {"entries": [], "subsystems": []}},
        scp.build_system_command_plan(
            {"system_resource_registry": {"entries": []}},
            {"contracts": [], "conflicts": []}, selection={"selected": []}),
        selection={"selected": []})
    assert document["initialization_deduplication"]["entries"] == []
    assert document["shared_resource_scheduling"]["entries"] == []
    assert document["parallelism_model"]["pairs"] == []
    assert document["scoreboard_integration"]["subsystems"] == []
    assert all(f["verdict"] != ssp.FLOW_SUPPORTED
               for f in document["cross_subsystem_checking"]["flows"])
    ssp.validate_system_scheduling_plan(document)


# ============================================================================
# The real CLI front door
# ============================================================================

def _synthetic_project(tmp_path: Path):
    """A real project tree the SYS-1 selection gate admits. Reused wholesale
    from the SYS-18..22 suite rather than rebuilt, so the two CLI layers cannot
    drift into two project-tree shapes."""
    from dv_harness_tests.test_system_command_plan import _synthetic_project as build
    return build(tmp_path)


def _snapshot(root: Path):
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _run_cli(tmp_path: Path, *extra):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp_path),
         "system-scheduling-plan", *extra],
        cwd=str(ROOT), capture_output=True, text=True)


def test_the_cli_refuses_an_empty_selection_through_sys1(tmp_path):
    """SYS-1's explicit-selection refusal is not bypassed by adding a verb on
    top of the stack. An empty plan must read as "nothing was selected", never
    as "these subsystems are clean"."""
    _synthetic_project(tmp_path)
    proc = _run_cli(tmp_path)
    assert proc.returncode == 2, proc.stderr
    assert "NO_EXPLICIT_SELECTION" in proc.stdout
    assert "no shared resource in this selection" in proc.stdout
    assert "no cross-subsystem command pair" in proc.stdout


def test_the_cli_reports_the_plan_and_writes_no_system_level_artifact(tmp_path):
    """The real end-to-end path: a real subprocess through the whole
    SYS-1 -> SYS-27 stack, and both subsystem environments byte-identical
    afterwards."""
    a, b = _synthetic_project(tmp_path)
    before = {**_snapshot(a), **_snapshot(b)}
    proc = _run_cli(tmp_path, "--select", "SUBSYS_A", "--select", "SUBSYS_B")
    assert proc.returncode in (0, 2), proc.stderr
    assert "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED" in proc.stdout
    assert ssp.ACCESS_POINT_STATUS in proc.stdout
    assert ssp.CHECK_CONTENT_NOT_GENERATED in proc.stdout
    assert {**_snapshot(a), **_snapshot(b)} == before
    for forbidden in ("system_command.txt", "soc_command.txt", "system_scoreboard.sv",
                      "system_virtual_sequencer.sv"):
        assert not list(tmp_path.rglob(forbidden)), forbidden
    for path in tmp_path.rglob("*.sv"):
        assert path.read_text(encoding="utf-8") == (
            "// synthetic fixture, empty on purpose\n"), path
