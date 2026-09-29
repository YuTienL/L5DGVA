"""Tests for SYS-18..SYS-22 of the System-Level Verification Integration
workflow: `dv_harness/system_command_plan.py` -- the SYSTEM-LEVEL ARCHITECTURE
report, the SYSTEM command.txt reuse/routing PLAN, the BACKWARD COMPATIBILITY
assessment, the SYSTEM COMMAND IR and COMMAND COLLISION DETECTION.

EVERY fixture is SYNTHETIC and built inside a tmp_path: fake command.txt files
written in the real macro grammar, fake subsystem environments, a fake
registry. The command.txt builders are IMPORTED from
`test_subsystem_architecture_and_command_contract` and the subsystem-environment
builders from `test_system_resource_inventory` rather than copied, so the SYS-8
and SYS-9..17 layers these tests sit on cannot drift into a second fixture
shape. Nothing touches the real
`.dv-harness/soc-composer/subsystem_environment_registry.json` (legitimately
absent in this repo), and no test writes a real System command.txt anywhere.

No test generates System-Level UVM source, a System command.txt, a System
Command Parser/Router, a System Scenario Planner, a System Virtual Sequencer or
a command adapter. Six tests ASSERT that rather than trusting it, including a
byte-for-byte tree snapshot across a full run and a scan of the rendered report
for SystemVerilog.

The suite is deliberately not a happy path. A collision detector whose only
coverage is the case where everything agrees has no detection power, so the
cases that carry this suite are the conflicting and ambiguous ones:

  * two subsystems writing DIFFERENT values to one address -> a conflicting
    register write, with both values in the finding;
  * the same pair writing the SAME value -> a duplicated setup, NOT a conflict;
  * two subsystems both actively driving one CPU-side BFM -> competing active
    VIP traffic, blocking;
  * two subsystems both invoking one initialization -> a duplicate init AND an
    ordering conflict, and the ordering conflict is ONE finding rather than one
    per dependent command;
  * a command name that already contains the namespace separator -> an
    AMBIGUOUS_NAMESPACE route and a subsystem reported SUBSYSTEM_MODE_AT_RISK,
    never a silently ambiguous System command name;
  * a THREE-subsystem collision -> pairwise escalation questions, because
    `escalate_conflict()` refuses more than 3 sides rather than truncating an
    evidence path away;
  * two subsystems only READING one block -> no collision at all;
  * an unselected subsystem -> no leaf in the SYS-18 tree.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import question_queue
from dv_harness import source_authority as sa
from dv_harness import subsystem_command_contract as scc
from dv_harness import subsystem_discovery as sd
from dv_harness import system_command_plan as scp
from dv_harness import system_resource_inventory as sri
from dv_harness import system_resource_registry as srr
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

#: Writes the SAME value to the SAME address as CPU_SIDE_COMMANDS. The pair
#: (this vs CPU_SIDE_COMMANDS) is a DUPLICATED setup; the pair
#: (CONTENDING_CPU_SIDE_COMMANDS vs CPU_SIDE_COMMANDS) is a CONFLICTING write.
#: Holding both pairs in one suite is what proves the value comparison is real
#: rather than a same-address check wearing a conflict label.
SAME_VALUE_COMMANDS = """\
// TEST FIXTURE ONLY
initial
begin
  `CPUWRITE4B(32'h1400_0000, 32'h1);      //same address AND same value
  $finish;
end
"""

#: A reset-flavoured initialization, so DUPLICATE_RESET_SETUP is reachable and
#: is not a dead branch of the classifier.
RESET_SETUP_COMMANDS = """\
// TEST FIXTURE ONLY
initial
begin
  `GMODEL.RESET_SEQUENCE;
  `CPUWRITE4B(32'h1600_0000, 32'h1);
  $finish;
end
"""

#: A third subsystem contending on the same DUT-side BFM and the same address,
#: so a THREE-sided collision is reachable.
THIRD_CPU_SIDE_COMMANDS = """\
// TEST FIXTURE ONLY
initial
begin
  `GMODEL.GLOBAL_INIT;
  `CPUWRITE4B(32'h1400_0000, 32'h9);
  $finish;
end
"""


def _contracts(tmp_path, **per_subsystem):
    """A SYS-8 contract set over synthetic command.txt files, one per named
    subsystem. Uses the real `build_contract_set()`, never a hand-built dict:
    a plan built on a fabricated contract shape would prove nothing about the
    plan the real stack produces."""
    return scc.build_contract_set({
        name: [_write(tmp_path / name.lower() / "command.txt", text)]
        for name, text in per_subsystem.items()
    })


def _plan(tmp_path, *, registry_entries=None, selection=None, **per_subsystem):
    contract_set = _contracts(tmp_path, **per_subsystem)
    integration_plan = {"system_resource_registry": {"entries": list(registry_entries or [])}}
    document = scp.build_system_command_plan(
        integration_plan, contract_set,
        selection=selection or {"selected": sorted(per_subsystem)})
    return contract_set, document


def _collisions_of(document, collision_type):
    return [c for c in document["command_collisions"]["collisions"]
            if c["collision_type"] == collision_type]


# ============================================================================
# Drift guards -- the requirement's own sentences vs. the code
# ============================================================================

#: SYS-21's field list, copied verbatim from the master prompt
#: (DV_Agent_Harness_L5_ULTIMATE_COMPLETE_Master_Prompt_SystemLevel_AMBA4_
#: SyoSil_CCE_Research.md, "## SYS-21. SYSTEM COMMAND IR").
SYS21_REQUIREMENT_TEXT = (
    "system_command_id, source_subsystem, source_command, command_category, "
    "target_resource, target_sequence, arguments, dependencies, preconditions, "
    "postconditions, parallel_group, serialization_group, shared_resource, "
    "priority, timeout, completion_condition, evidence"
)

#: SYS-18's two mandated group headings and their children, verbatim.
SYS18_REQUIREMENT_CONTROL = (
    "System Command Parser/Router, System Scenario Planner, System Virtual Sequencer")
SYS18_REQUIREMENT_SHARED = (
    "CPU AXI Master, APB Master, AHB Master, Clock/Reset, Interrupt, Memory/Register Access")


def test_sys21_fields_match_the_requirements_own_sentence_one_to_one():
    """The document and the code cannot drift apart in either direction."""
    expected = tuple(p.strip() for p in SYS21_REQUIREMENT_TEXT.split(","))
    assert scp.SYS21_FIELDS == expected
    assert len(scp.SYS21_FIELDS) == 17


def test_sys18_node_names_match_the_requirements_own_tree():
    assert scp.SYS18_SYSTEM_CONTROL == tuple(
        p.strip() for p in SYS18_REQUIREMENT_CONTROL.split(","))
    assert scp.SYS18_SHARED_SOC_RESOURCES == tuple(
        p.strip() for p in SYS18_REQUIREMENT_SHARED.split(","))


def test_sys22_collision_types_cover_the_requirements_own_sentence():
    """SYS-22 names its classes in prose: "duplicate initialization/reset/clock
    setup/CPU configuration/APB programming/memory init, conflicting register
    writes/address setup, competing active VIP traffic, incompatible mode
    setup, ordering conflicts, shared-resource contention"."""
    assert len(scp.SYS22_COLLISION_TYPES) == 12
    assert len(set(scp.SYS22_COLLISION_TYPES)) == 12
    for token in ("INITIALIZATION", "RESET", "CLOCK", "CPU", "APB", "MEMORY",
                  "REGISTER_WRITE", "ADDRESS_SETUP", "VIP_TRAFFIC", "MODE_SETUP",
                  "ORDERING", "CONTENTION"):
        assert any(token in t for t in scp.SYS22_COLLISION_TYPES), token
    # Every class has a severity and the severities are a total order.
    assert set(scp.COLLISION_SEVERITY) == set(scp.SYS22_COLLISION_TYPES)
    assert len(set(scp.COLLISION_SEVERITY.values())) == 12


def test_ir_fields_match_the_json_schemas_required_list():
    schema = json.loads(scp.SCHEMA_PATH.read_text(encoding="utf-8"))
    required = schema["properties"]["system_command_ir"]["properties"]["entries"][
        "items"]["required"]
    assert tuple(required) == scp.SYS21_FIELDS


def test_no_second_classifier_is_defined_here():
    """REUSE BEFORE REBUILD, as a checkable claim rather than a comment. A
    second command parser, concurrency resolver or contract-conflict detector
    beside the SYS-7/SYS-8 originals is the duplicate-mechanism failure this
    project has already been bitten by."""
    source = (ROOT / "dv_harness" / "system_command_plan.py").read_text(encoding="utf-8")
    for forbidden in ("def analyze_command_file", "def extract_command_statements",
                      "def resolve_cross_subsystem_concurrency",
                      "def detect_contract_conflicts", "def build_subsystem_contracts",
                      "def classify_wait", "def resolve_conflict", "def authority_rank"):
        assert forbidden not in source, forbidden
    # And the layers below really are imported rather than respelled.
    assert "from . import subsystem_command_contract as scc" in source
    assert "from . import system_resource_registry as srr" in source
    assert "detect_contract_conflicts" in source, (
        "SYS-22 must REFINE the SYS-8 conflict joins, not re-derive them")


# ============================================================================
# SYS-18 -- SYSTEM-LEVEL ARCHITECTURE
# ============================================================================

def test_only_selected_subsystems_get_a_leaf(tmp_path):
    """SYS-18: "Instantiate only selected subsystems". A contract set naming
    three subsystems and a selection naming two must produce two leaves -- a
    tree that widened itself to what the evidence mentioned would compose a
    set the user did not choose, which is SYS-1's own refusal being bypassed
    one layer up."""
    contract_set = _contracts(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                              USB=CONTENDING_CPU_SIDE_COMMANDS,
                              ETH=READ_ONLY_COMMANDS)
    document = scp.build_system_command_plan(
        {"system_resource_registry": {"entries": []}}, contract_set,
        selection={"selected": ["PCIE", "USB"]})
    architecture = document["system_architecture"]
    leaves = [n["name"] for n in architecture["nodes"] if n["kind"] == "SUBSYSTEM_ENV"]
    assert leaves == ["PCIE", "USB"]
    assert "ETH" not in scp.render_architecture_tree(architecture)


def test_system_control_is_always_planned_never_implemented(tmp_path):
    """The single most important assertion in this file. A parser/router, a
    scenario planner and a virtual sequencer are CODE, and code is SYS-40."""
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    control = [n for n in document["system_architecture"]["nodes"]
               if n["kind"] == "SYSTEM_CONTROL"]
    assert [n["name"] for n in control] == list(scp.SYS18_SYSTEM_CONTROL)
    assert {n["status"] for n in control} == {scp.NODE_PLANNED_NOT_IMPLEMENTED}
    assert document["system_architecture"]["summary"]["system_control_implemented"] == 0


def test_an_implemented_system_control_node_is_refused(tmp_path):
    """The boundary is enforced, not described: a document claiming it built a
    virtual sequencer must not validate and must not pass the runtime check."""
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    node = next(n for n in document["system_architecture"]["nodes"]
                if n["name"] == "System Virtual Sequencer")
    node["status"] = scp.NODE_PROPOSED_FROM_REGISTRY
    with pytest.raises(scp.SystemCommandPlanError) as exc:
        scp.assert_no_emitted_artifacts(document)
    assert exc.value.reason == "SYSTEM_CONTROL_COMPONENT_IMPLEMENTED"
    import jsonschema
    with pytest.raises(jsonschema.ValidationError):
        scp.validate_system_command_plan(document)


def test_an_absent_shared_resource_category_says_so_rather_than_vanishing(tmp_path):
    """SYS-18 NAMES six categories. A tree that silently omitted the ones this
    selection has no evidence for would read as a complete statement about the
    structure -- the same distinction SYS-16 draws with NOT_AVAILABLE."""
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    shared = [n for n in document["system_architecture"]["nodes"]
              if n["kind"] == "SHARED_SOC_RESOURCE"]
    assert [n["name"] for n in shared] == list(scp.SYS18_SHARED_SOC_RESOURCES)
    assert {n["status"] for n in shared} == {scp.NODE_NOT_PRESENT_IN_SELECTION}
    for node in shared:
        assert "absence in the evidence" in node["basis"]


def test_a_shared_registry_entry_backs_its_category_and_a_blocked_one_blocks_it(tmp_path):
    entries = [
        {"resource_id": "CPU_AXI_MASTER", "resource_type": sri.RT_CPU_BUS_MASTER,
         "shared": srr.SHARED_ACROSS_SUBSYSTEMS, "reuse_decision": srr.REUSE_SHARED,
         "consumer_subsystems": ["PCIE", "USB"], "evidence": ["pcie/env.sv:10"]},
        {"resource_id": "APB_MASTER", "resource_type": sri.RT_APB_MASTER,
         "shared": srr.SHARED_ACROSS_SUBSYSTEMS, "reuse_decision": srr.BLOCKED,
         "consumer_subsystems": ["PCIE", "USB"], "evidence": ["usb/env.sv:22"]},
    ]
    _, document = _plan(tmp_path, registry_entries=entries,
                        PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    by_name = {n["name"]: n for n in document["system_architecture"]["nodes"]}
    assert by_name["CPU AXI Master"]["status"] == scp.NODE_PROPOSED_FROM_REGISTRY
    assert by_name["CPU AXI Master"]["backing_resources"] == ["CPU_AXI_MASTER"]
    assert by_name["APB Master"]["status"] == scp.NODE_BLOCKED_PENDING_OWNERSHIP
    assert by_name["AHB Master"]["status"] == scp.NODE_NOT_PRESENT_IN_SELECTION


def test_a_subsystem_specific_vip_is_never_hoisted_into_shared_soc_resources(tmp_path):
    """SYS-14: only shared SoC infrastructure is promoted. A PCIe VIP agent
    shared by two subsystems still has no SYS-18 shared-resource category, and
    inventing one for it would be exactly the unnecessary refactoring SYS-14
    tells the harness to avoid."""
    entries = [{"resource_id": "PCIE_VIP", "resource_type": sri.RT_VIP_AGENT,
                "shared": srr.SHARED_ACROSS_SUBSYSTEMS, "reuse_decision": srr.REUSE_SHARED,
                "consumer_subsystems": ["PCIE", "USB"], "evidence": []}]
    _, document = _plan(tmp_path, registry_entries=entries,
                        PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    for node in document["system_architecture"]["nodes"]:
        if node["kind"] == "SHARED_SOC_RESOURCE":
            assert "PCIE_VIP" not in node["backing_resources"]
            assert node["status"] == scp.NODE_NOT_PRESENT_IN_SELECTION


def test_a_resource_only_one_subsystem_consumes_is_not_a_shared_node(tmp_path):
    entries = [{"resource_id": "PCIE_LOCAL_AXI", "resource_type": sri.RT_AXI_MASTER,
                "shared": srr.NOT_SHARED, "reuse_decision": srr.KEEP_INDEPENDENT,
                "consumer_subsystems": ["PCIE"], "evidence": []}]
    _, document = _plan(tmp_path, registry_entries=entries,
                        PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    by_name = {n["name"]: n for n in document["system_architecture"]["nodes"]}
    assert by_name["CPU AXI Master"]["status"] == scp.NODE_NOT_PRESENT_IN_SELECTION
    # It stays where SYS-14 says it stays: on its own subsystem's leaf.
    pcie_leaf = next(n for n in document["system_architecture"]["nodes"]
                     if n["kind"] == "SUBSYSTEM_ENV" and n["name"] == "PCIE")
    assert "PCIE_LOCAL_AXI" in pcie_leaf["backing_resources"]


def test_an_empty_selection_instantiates_nothing(tmp_path):
    contract_set = _contracts(tmp_path, PCIE=CPU_SIDE_COMMANDS)
    document = scp.build_system_command_plan(
        {"system_resource_registry": {"entries": []}}, contract_set,
        selection={"selected": []})
    architecture = document["system_architecture"]
    assert [n for n in architecture["nodes"] if n["kind"] == "SUBSYSTEM_ENV"] == []
    assert "nothing is instantiated" in scp.render_architecture_tree(architecture)


# ============================================================================
# SYS-19 -- SYSTEM command.txt: REUSE, DO NOT REINVENT
# ============================================================================

def test_every_route_targets_an_existing_subsystem_target_never_a_new_one(tmp_path):
    """SYS-19: "Do not invent an unrelated command language when existing
    semantics can be reused." Every routed row's target must be a value the
    SYS-8 contract already carried."""
    contract_set, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                                   USB=CONTENDING_CPU_SIDE_COMMANDS)
    by_contract = {(c["subsystem_id"], c["command_name"]): c
                   for c in contract_set["contracts"]}
    for row in document["system_command_routing_plan"]["rows"]:
        contract = by_contract[(row["source_subsystem"], row["source_command"])]
        assert row["routes_to_agent"] == contract["target_agent"]
        assert row["routes_to_vip"] == contract["target_vip"]
        assert row["routes_to_sequence"] == (contract["target_sequence"] or "")


def test_namespacing_makes_a_shared_command_name_unique_without_renaming_it(tmp_path):
    """Both subsystems invoke CPUWRITE4B. The namespace resolves the NAME
    collision (that is what it is for) and the source command is unchanged --
    a rename would be the wholesale rewrite SYS-20 forbids."""
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    routing = document["system_command_routing_plan"]
    assert routing["summary"]["namespaced_names_are_unique"] is True
    rows = {r["system_command"]: r for r in routing["rows"]}
    assert "PCIE::CPUWRITE4B" in rows and "USB::CPUWRITE4B" in rows
    assert rows["PCIE::CPUWRITE4B"]["source_command"] == "CPUWRITE4B"
    assert rows["PCIE::CPUWRITE4B"]["name_shared_with"] == ["USB"]
    assert rows["USB::CPUWRITE4B"]["name_shared_with"] == ["PCIE"]


def test_a_dot_separator_would_have_been_ambiguous_which_is_why_it_is_not_the_separator(tmp_path):
    """The evidence behind the separator choice, held as a test rather than
    asserted in a comment. Real command names DO contain `.` -- a model task
    call is written `` `GMODEL.GLOBAL_INIT `` -- so a `.`-joined namespace would
    produce `PCIE.GMODEL.GLOBAL_INIT`, in which no adapter can tell where the
    namespace ends. `::` is chosen precisely because the SYS-7 grammar's own
    macro-name shape cannot produce it."""
    contract_set, _ = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                            USB=CONTENDING_CPU_SIDE_COMMANDS)
    names = [c["command_name"] for c in contract_set["contracts"]]
    assert any("." in n for n in names), names
    assert not any(scp.NAMESPACE_SEPARATOR in n for n in names), names
    assert scp.NAMESPACE_SEPARATOR == "::"


def test_a_command_name_containing_the_separator_is_ambiguous_not_silently_namespaced():
    """The guard for the case the current grammar cannot reach.

    The test above proves the real SYS-7 grammar truncates a macro name at
    `::`, so this verdict is unreachable through it TODAY. That is exactly why
    the guard is worth having and worth testing directly: a contract can also
    arrive from a declared `command_inventory.csv` overlay, and a future
    grammar change that started admitting `::` must fail loudly here rather
    than silently start emitting System command names that cannot be split back
    into (subsystem, command). The contract is built directly for that reason,
    not through the grammar."""
    contract_set = {"contracts": [
        {"subsystem_id": "AMB", "command_name": "PKG::INIT_BUS",
         "source_command_file": "amb/command.txt", "command_category": "INITIALIZATION",
         "target_agent": "PKG", "target_vip": "PKG", "target_sequence": "INIT_BUS",
         "evidence": ["amb/command.txt:4"]},
    ], "conflicts": []}
    routing = scp.plan_system_command_reuse(contract_set)
    row = routing["rows"][0]
    assert row["system_command"] == "AMB::PKG::INIT_BUS"
    assert row["route_verdict"] == scp.ROUTE_AMBIGUOUS_NAMESPACE
    assert "cannot be split back" in row["route_reason"]

    compat = scp.assess_backward_compatibility(contract_set, routing)
    assert compat["subsystems"][0]["compatibility_verdict"] == scp.COMPAT_AT_RISK
    assert compat["summary"]["at_risk"] == ["AMB"]
    assert compat["summary"]["all_subsystem_modes_preserved"] is False


def test_an_unresolved_target_is_reported_never_guessed(tmp_path):
    """`$finish` resolves to no agent, VIP or sequence. Naming one anyway would
    be inventing exactly the mapping SYS-19 forbids inventing."""
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    unresolved = [r for r in document["system_command_routing_plan"]["rows"]
                  if r["route_verdict"] == scp.ROUTE_TARGET_UNRESOLVED]
    assert any(r["source_command"] == "$finish" for r in unresolved)
    for row in unresolved:
        assert row["routes_to_agent"] in ("UNKNOWN", "")
        assert "inventing" in row["route_reason"]


def test_no_system_command_txt_is_emitted_by_the_routing_plan(tmp_path):
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    routing = document["system_command_routing_plan"]
    assert routing["system_command_txt_emitted"] is False
    assert routing["system_command_txt_path"] is None
    routing["system_command_txt_emitted"] = True
    with pytest.raises(scp.SystemCommandPlanError) as exc:
        scp.assert_no_emitted_artifacts(document)
    assert exc.value.reason == "SYSTEM_COMMAND_TXT_EMITTED"


# ============================================================================
# SYS-20 -- BACKWARD COMPATIBILITY
# ============================================================================

def test_every_subsystems_command_txt_is_recorded_by_digest_and_unmodified(tmp_path):
    """SYS-20 half one, checkable rather than asserted: the digest recorded in
    the plan must equal the file's digest on disk after the whole run."""
    contract_set, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                                   USB=CONTENDING_CPU_SIDE_COMMANDS)
    seen = 0
    for sub in document["backward_compatibility"]["subsystems"]:
        assert sub["command_txt_modified"] is False
        for record in sub["command_txt_files"]:
            on_disk = hashlib.sha256(Path(record["path"]).read_bytes()).hexdigest()
            assert record["sha256"] == on_disk
            seen += 1
    assert seen == 2
    assert document["backward_compatibility"]["summary"]["any_command_txt_modified"] is False


def test_the_adapter_is_named_and_planned_but_never_generated(tmp_path):
    """SYS-20 half two. The mechanism is stated -- strip the prefix, hand the
    subsystem's own parser the byte-identical token -- and nothing is built."""
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    for sub in document["backward_compatibility"]["subsystems"]:
        adapter = sub["adapter_plan"]
        assert adapter["status"] == scp.NODE_PLANNED_NOT_IMPLEMENTED
        assert adapter["generated"] is False
        assert adapter["reuses_existing_parser"] is True
        assert adapter["rewrites_required_in_subsystem"] == []
        assert "strip the leading" in adapter["mechanism"]
    assert document["backward_compatibility"]["summary"]["adapters_generated"] == 0


def test_a_generated_adapter_is_refused(tmp_path):
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    document["backward_compatibility"]["summary"]["adapters_generated"] = 1
    with pytest.raises(scp.SystemCommandPlanError) as exc:
        scp.assert_no_emitted_artifacts(document)
    assert exc.value.reason == "COMMAND_ADAPTER_GENERATED"


def test_one_at_risk_subsystem_is_not_folded_into_a_clean_total():
    """A compatibility summary reporting "all preserved" while one subsystem
    cannot round-trip would be exactly the reassurance that gets a real problem
    integrated. The clean subsystem must stay clean at the same time."""
    contract_set = {"contracts": [
        {"subsystem_id": "AMB", "command_name": "PKG::INIT_BUS",
         "source_command_file": "amb/command.txt", "command_category": "INITIALIZATION",
         "target_agent": "PKG", "target_vip": "PKG", "target_sequence": "INIT_BUS",
         "evidence": []},
        {"subsystem_id": "USB", "command_name": "CPUWRITE4B",
         "source_command_file": "usb/command.txt", "command_category": "REGISTER_ACCESS",
         "target_agent": "DUT_SIDE_BFM", "target_vip": "UNKNOWN", "target_sequence": "",
         "evidence": []},
    ], "conflicts": []}
    routing = scp.plan_system_command_reuse(contract_set)
    compat = scp.assess_backward_compatibility(contract_set, routing)
    by_id = {s["subsystem_id"]: s for s in compat["subsystems"]}
    assert by_id["AMB"]["compatibility_verdict"] == scp.COMPAT_AT_RISK
    assert by_id["AMB"]["ambiguous_commands"] == ["AMB::PKG::INIT_BUS"]
    assert by_id["USB"]["compatibility_verdict"] == scp.COMPAT_PRESERVED
    assert compat["summary"]["at_risk"] == ["AMB"]
    assert compat["summary"]["preserved"] == 1
    assert compat["summary"]["all_subsystem_modes_preserved"] is False


# ============================================================================
# SYS-21 -- SYSTEM COMMAND IR
# ============================================================================

def test_every_ir_entry_carries_all_seventeen_fields_and_is_derived(tmp_path):
    contract_set, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                                   USB=CONTENDING_CPU_SIDE_COMMANDS)
    ir = document["system_command_ir"]
    assert ir["summary"]["entry_count"] == len(contract_set["contracts"])
    assert ir["summary"]["authored_by_user"] is False
    for entry in ir["entries"]:
        for field in scp.SYS21_FIELDS:
            assert field in entry, field
        # Nothing beyond the 17 plus the documented `derivation` sidecar.
        assert set(entry) - set(scp.SYS21_FIELDS) == {"derivation"}


def test_ir_command_facts_are_copied_from_the_contract_never_recomputed(tmp_path):
    """The IR is a projection of the SYS-8 contract. A field that disagreed
    with its contract would mean two answers to one question."""
    contract_set, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                                   USB=CONTENDING_CPU_SIDE_COMMANDS)
    by_key = {(c["subsystem_id"], c["command_name"]): c for c in contract_set["contracts"]}
    for entry in document["system_command_ir"]["entries"]:
        contract = by_key[(entry["source_subsystem"], entry["source_command"])]
        assert entry["command_category"] == contract["command_category"]
        assert entry["arguments"] == contract["arguments"]
        assert entry["dependencies"] == contract["ordering_constraints"]
        assert entry["preconditions"] == contract["preconditions"]
        assert entry["postconditions"] == contract["postconditions"]
        assert entry["evidence"] == contract["evidence"]
        assert entry["target_resource"] == sorted(
            {r["resource_id"] for r in contract["required_resources"]})


def test_priority_and_timeout_are_honestly_unassigned_with_a_stated_reason(tmp_path):
    """Nothing in a subsystem command.txt states either. A derived-looking
    number here would be an invented verification parameter."""
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    for entry in document["system_command_ir"]["entries"]:
        assert entry["priority"] == scp.PRIORITY_UNASSIGNED
        assert entry["timeout"] == scp.TIMEOUT_NOT_SPECIFIED
        assert entry["derivation"]["priority_reason"]
        assert entry["derivation"]["timeout_reason"]


def test_groups_follow_the_contracts_own_parallel_safety_verdict(tmp_path):
    """No second concurrency classifier: the grouping is a NAMING of the
    verdict `resolve_cross_subsystem_concurrency()` already reached."""
    contract_set, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                                   USB=CONTENDING_CPU_SIDE_COMMANDS)
    by_key = {(c["subsystem_id"], c["command_name"]): c for c in contract_set["contracts"]}
    saw_parallel = saw_serial = False
    for entry in document["system_command_ir"]["entries"]:
        contract = by_key[(entry["source_subsystem"], entry["source_command"])]
        if contract["parallel_safe"] == scc.PARALLEL_SAFE:
            assert entry["parallel_group"] == f"PARALLEL::{entry['source_subsystem']}"
            assert entry["serialization_group"] == ""
            saw_parallel = True
        elif contract["parallel_safe"] == scc.NOT_PARALLEL_SAFE:
            assert entry["parallel_group"] == ""
            assert entry["serialization_group"].startswith("SERIALIZE::")
            saw_serial = True
    assert saw_parallel and saw_serial, "this fixture must exercise both verdicts"


def test_two_commands_contending_on_one_resource_share_a_serialization_group(tmp_path):
    """The whole point of naming the group after the contended resource."""
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    by_id = {e["system_command_id"]: e for e in document["system_command_ir"]["entries"]}
    a = by_id["PCIE::CPUWRITE4B"]["serialization_group"]
    b = by_id["USB::CPUWRITE4B"]["serialization_group"]
    assert a and a == b, (a, b)
    assert "BFM:DUT_SIDE" in a


def test_single_subsystem_parallel_group_is_undecidable_not_a_verdict(tmp_path):
    """A one-subsystem set has no second subsystem to be concurrent WITH."""
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS)
    for entry in document["system_command_ir"]["entries"]:
        assert entry["parallel_group"] == scp.PARALLEL_GROUP_UNDECIDABLE
        assert entry["serialization_group"] == ""
        assert "SINGLE_SUBSYSTEM" in entry["derivation"]["grouping_reason"]


def test_completion_condition_is_derived_from_evidence_and_cites_its_basis(tmp_path):
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    conditions = set()
    for entry in document["system_command_ir"]["entries"]:
        assert entry["derivation"]["completion_basis"], entry["system_command_id"]
        conditions.add(entry["completion_condition"])
    # The fixture has an interrupt wait, a $finish and plain returns, so more
    # than one value must be reachable -- a single-valued field would carry no
    # information at all.
    assert len(conditions) >= 2, conditions
    assert scp.COMPLETION_TERMINATES_FILE in conditions


# ============================================================================
# SYS-22 -- COMMAND COLLISION DETECTION
# ============================================================================

def test_two_subsystems_writing_different_values_to_one_address_is_a_conflict(tmp_path):
    """THE case value pairing exists for. Both values must be IN the finding:
    a conflict a reader cannot check is not a finding."""
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    found = _collisions_of(document, scp.CONFLICTING_REGISTER_WRITE)
    assert len(found) == 1, [c["subject"] for c in document["command_collisions"]["collisions"]]
    conflict = found[0]
    assert conflict["subject"] == "32'h1400_0000"
    assert conflict["subsystems"] == ["PCIE", "USB"]
    assert conflict["written_values"] == {"PCIE": ["32'h1"], "USB": ["32'h7"]}
    assert conflict["blocks_integration"] is True
    assert conflict["evidence"], "a collision with no citation is not checkable"


def test_two_subsystems_writing_the_SAME_value_is_a_duplicate_not_a_conflict(tmp_path):
    """The converse, and the reason this detector needs the values rather than
    just the addresses. Reporting a duplicated init as a conflicting write
    would train its users to ignore the real ones."""
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, SAME=SAME_VALUE_COMMANDS)
    assert _collisions_of(document, scp.CONFLICTING_REGISTER_WRITE) == []
    assert _collisions_of(document, scp.INCOMPATIBLE_MODE_SETUP) == []
    duplicates = [c for c in document["command_collisions"]["collisions"]
                  if c["subject"] == "32'h1400_0000"]
    assert len(duplicates) == 1, [c["collision_type"] for c in duplicates]
    # DUPLICATE_RESET_SETUP specifically: the fixture's own trailing comment on
    # that write is `//ctrl rst=1`, which is real reset evidence the classifier
    # reads. The point of the assertion is the DUPLICATE_ family, not the exact
    # member -- both agree it is a duplicated setup and not a conflict.
    assert duplicates[0]["collision_type"].startswith("DUPLICATE_")
    assert "SAME value" in duplicates[0]["detail"]
    assert duplicates[0]["blocks_integration"] is False


def test_two_subsystems_driving_one_bfm_is_competing_active_vip_traffic(tmp_path):
    """SYS-10's "PCIe and USB both contain a CPU AXI Master" shape, arriving
    through command.txt. SYS-12 says this stops automatic integration."""
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    found = _collisions_of(document, scp.COMPETING_ACTIVE_VIP_TRAFFIC)
    assert [c["subject"] for c in found] == ["BFM:DUT_SIDE"]
    assert found[0]["blocks_integration"] is True
    assert "STOP_AUTOMATIC_SYSTEM_INTEGRATION" in found[0]["resolution"]
    assert found[0]["derived_from"].startswith(
        "subsystem_command_contract.detect_contract_conflicts"), \
        "SYS-22 must REFINE the SYS-8 join, not re-derive it"


def test_two_subsystems_invoking_one_initialization_is_a_duplicate_and_an_ordering_conflict(tmp_path):
    """Both fixtures call `GMODEL.GLOBAL_INIT. That is two findings, not one:
    the act is duplicated (SYS-23 will decide what to do about it) AND the
    second subsystem can re-run it after the first depended on it."""
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    duplicates = [c for c in document["command_collisions"]["collisions"]
                  if c["collision_type"].startswith("DUPLICATE_")
                  and c["subject"] == "`GMODEL.GLOBAL_INIT"]
    assert len(duplicates) == 1
    assert duplicates[0]["subsystems"] == ["PCIE", "USB"]
    assert duplicates[0]["blocks_integration"] is False, (
        "SYS-23's own rule is that a command is not removed without evidence, so a "
        "duplicate is a REPORT, not a stop")
    ordering = _collisions_of(document, scp.ORDERING_CONFLICT)
    assert len(ordering) == 1, [c["subject"] for c in ordering]
    assert ordering[0]["subject"] == "initialization `GMODEL.GLOBAL_INIT"
    assert ordering[0]["blocks_integration"] is True


def test_the_ordering_conflict_is_one_finding_not_one_per_dependent_command(tmp_path):
    """Every REGISTER_ACCESS command in a file shares the same preceding
    initialization. Per-command rows would restate one finding many times and
    bury the collisions that are genuinely distinct -- the same reason
    read/read sharing is not reported as a driver conflict."""
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    ordering = _collisions_of(document, scp.ORDERING_CONFLICT)
    assert len(ordering) == 1
    # It still names every command whose precondition is at stake.
    assert len(ordering[0]["commands"]) > 1


def test_a_reset_flavoured_duplicate_is_classified_as_a_reset_setup(tmp_path):
    """DUPLICATE_RESET_SETUP must be reachable rather than a dead branch."""
    _, document = _plan(tmp_path, A=RESET_SETUP_COMMANDS, B=RESET_SETUP_COMMANDS)
    assert _collisions_of(document, scp.DUPLICATE_RESET_SETUP), \
        [c["collision_type"] for c in document["command_collisions"]["collisions"]]


def test_two_subsystems_only_reading_one_block_produce_no_collision(tmp_path):
    """A detector that fires on read/read sharing has no signal left."""
    _, document = _plan(tmp_path, A=READ_ONLY_COMMANDS, B=READ_ONLY_COMMANDS)
    blocking = [c for c in document["command_collisions"]["collisions"]
                if c["blocks_integration"]]
    assert blocking == [], [c["collision_type"] for c in blocking]


def test_a_single_subsystem_set_has_no_cross_subsystem_collision(tmp_path):
    """A command.txt is sequential by construction; its own internal order is
    stated, so contention with itself is not a System-level collision."""
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS)
    assert document["command_collisions"]["collisions"] == []
    assert document["summary"]["blocking_collisions"] == 0


def test_no_collision_is_dropped_when_two_detectors_reach_the_same_subject(tmp_path):
    """Merging is deduplication of a REPORT, never of a collision: the merged
    record must name BOTH derivations so nothing is quietly lost."""
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    collisions = document["command_collisions"]["collisions"]
    keys = [(c["collision_type"], c["subject"], tuple(c["subsystems"])) for c in collisions]
    assert len(keys) == len(set(keys)), "one finding per (type, subject, subsystems)"
    for finding in collisions:
        assert finding["derived_from"], finding["collision_id"]
    assert document["command_collisions"]["summary"]["no_collision_silently_resolved"] is True
    # The address join is reported ONCE, by the value-aware detector, which is a
    # strict superset of the SYS-8 join: same records, plus the values. The
    # SYS-8 branch defers rather than emitting a second, weaker label for the
    # same address -- deferring to more information is not dropping a finding.
    address = [c for c in collisions if c["subject"] == "32'h1400_0000"]
    assert len(address) == 1, [c["collision_type"] for c in address]
    assert address[0]["collision_type"] == scp.CONFLICTING_REGISTER_WRITE
    # The resource joins ARE still taken from the SYS-8 detector.
    assert any(f["derived_from"].startswith("subsystem_command_contract.")
               for f in collisions)


def test_collision_ids_are_stable_across_runs(tmp_path):
    """A finding whose id changed every run could never be answered, tracked or
    deduplicated in the question queue."""
    _, first = _plan(tmp_path / "one", PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    _, second = _plan(tmp_path / "two", PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    assert ([c["collision_id"] for c in first["command_collisions"]["collisions"]]
            == [c["collision_id"] for c in second["command_collisions"]["collisions"]])


def test_every_collision_carries_a_real_citation_for_each_side(tmp_path):
    """Escalation needs one path PER side; a merged list cannot supply that,
    and `assert_both_evidence_paths_present()` refuses a question without it."""
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    for finding in document["command_collisions"]["collisions"]:
        by_subsystem = finding["evidence_by_subsystem"]
        assert set(by_subsystem) >= set(finding["subsystems"]), finding["collision_id"]
        for sid in finding["subsystems"]:
            assert by_subsystem[sid], (finding["collision_id"], sid)


# ============================================================================
# SYS-22 escalation -- through source_authority, into the real question queue
# ============================================================================

def test_two_command_txt_claims_are_same_authority_and_the_order_says_so(tmp_path):
    """The reason this module classifies collision TYPE itself and only reuses
    the ESCALATION: both sides are tier-2 `reference_command_txt`, so the
    9-level order returns UNDECIDABLE and cannot pick a winner. That is the
    correct answer here, not a shortcoming."""
    conflict = sa.resolve_conflict([
        sa.SourceClaim(source="reference_command_txt", claim="PCIE owns it",
                       evidence_path="pcie/command.txt:12"),
        sa.SourceClaim(source="reference_command_txt", claim="USB owns it",
                       evidence_path="usb/command.txt:7"),
    ])
    assert conflict["verdict"] == sa.VERDICT_UNDECIDABLE
    assert conflict["winner"] is None


def test_collisions_are_filed_into_the_real_question_queue(tmp_path):
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    store = question_queue.QuestionQueueStore(tmp_path)
    records = scp.escalate_command_collisions(store, document["command_collisions"])
    assert len(records) == len(document["command_collisions"]["collisions"])
    persisted = store.list_questions()
    assert len(persisted) == len(records)
    for record in records:
        assert record["domain"] == "env"
        assert len(record["options"]) == 2
        # Both sides' own evidence paths reached the queue.
        rationales = " ".join(o.get("rationale", "") for o in record["options"])
        assert "pcie" in rationales.lower() and "usb" in rationales.lower(), rationales


def test_escalation_is_idempotent_over_unchanged_command_txt(tmp_path):
    """A detector wired into a re-runnable plan must not grow the queue. This
    was a real regression in `reference_pattern_audit`'s own escalation."""
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    store = question_queue.QuestionQueueStore(tmp_path)
    first = scp.escalate_command_collisions(store, document["command_collisions"])
    after_first = len(store.list_questions())
    second = scp.escalate_command_collisions(store, document["command_collisions"])
    assert len(store.list_questions()) == after_first
    assert [q["id"] for q in first] == [q["id"] for q in second]


def test_a_three_subsystem_collision_is_split_into_pairwise_questions(tmp_path):
    """`escalate_conflict()` refuses more than 3 sides rather than truncating,
    because dropping a side drops its evidence path with it. Three subsystems
    contending on one BFM must therefore become three pairwise questions, not
    one truncated one and not a crash."""
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                        USB=CONTENDING_CPU_SIDE_COMMANDS, ETH=THIRD_CPU_SIDE_COMMANDS)
    bfm = _collisions_of(document, scp.COMPETING_ACTIVE_VIP_TRAFFIC)
    assert bfm and bfm[0]["subsystems"] == ["ETH", "PCIE", "USB"]
    store = question_queue.QuestionQueueStore(tmp_path)
    records = scp.escalate_command_collisions(store, {"collisions": bfm})
    assert len(records) == 3, [r["question"] for r in records]
    pairs = {tuple(sorted(o["label"].split(" owns ")[0].split()[-1]
                          for o in r["options"])) for r in records}
    assert len(pairs) == 3


def test_a_three_way_address_conflict_names_all_three_values(tmp_path):
    """Three subsystems writing three different values to one address is one
    finding carrying all three, never a pair with the third silently dropped."""
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                        USB=CONTENDING_CPU_SIDE_COMMANDS, ETH=THIRD_CPU_SIDE_COMMANDS)
    found = _collisions_of(document, scp.CONFLICTING_REGISTER_WRITE)
    assert len(found) == 1
    assert found[0]["written_values"] == {
        "ETH": ["32'h9"], "PCIE": ["32'h1"], "USB": ["32'h7"]}


# ============================================================================
# Phase boundary -- SYS-39 / SYS-40
# ============================================================================

def _snapshot(root: Path):
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_a_full_run_writes_nothing_anywhere(tmp_path):
    """Byte-for-byte, across the whole tree. SYS-7 ("do not modify command.txt
    during discovery") and SYS-8 ("keep original command.txt intact") as a
    checked property rather than a promise."""
    contract_set = _contracts(tmp_path, PCIE=CPU_SIDE_COMMANDS,
                              USB=CONTENDING_CPU_SIDE_COMMANDS)
    before = _snapshot(tmp_path)
    document = scp.build_system_command_plan(
        {"system_resource_registry": {"entries": []}}, contract_set,
        selection={"selected": ["PCIE", "USB"]})
    scp.format_system_command_plan_report(document)
    scp.validate_system_command_plan(document)
    assert _snapshot(tmp_path) == before


def test_the_module_holds_no_file_writer_at_all(tmp_path):
    """SYS-15..17's registry module holds exactly one `.write_text(`, because
    it persists a planning registry. This module persists nothing, so it must
    hold none -- a writer here would have no legitimate purpose."""
    source = (ROOT / "dv_harness" / "system_command_plan.py").read_text(encoding="utf-8")
    assert ".write_text(" not in source
    assert ".write_bytes(" not in source
    assert "open(" not in source.replace(".read_text(", "").replace("SCHEMA_PATH.read_text(", "")


def test_the_rendered_report_contains_no_systemverilog(tmp_path):
    """A report a reader could mistake for a generated environment is the exact
    artifact SYS-39 exists to prevent."""
    _, document = _plan(tmp_path, PCIE=CPU_SIDE_COMMANDS, USB=CONTENDING_CPU_SIDE_COMMANDS)
    report = scp.format_system_command_plan_report(document)
    # Real SystemVerilog tokens only. Prose describing a virtual sequencer is
    # the whole point of an architecture REPORT; emitting one is what must not
    # happen, and these are the tokens that would prove it had.
    for token in ("endmodule", "endclass", "endtask", "endfunction", "`uvm_",
                  "uvm_component", "uvm_sequence", "::type_id::create",
                  "initial begin", "always_ff", "always_comb"):
        assert token not in report, token
    assert "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED" in report
    assert document["artifacts_generated"] == []


def test_the_soc_composer_cross_subsystem_stubs_are_still_unimplemented():
    """This layer must not have been the excuse to fill them in. Their content
    is protocol BEHAVIOUR, which is SYS-40 and needs primary per-subsystem VIP/
    DUT evidence -- not a planning descriptor."""
    from dv_harness.uvm_generator import soc_environment_composer as sec
    for name in ("cross_subsystem_scenarios", "end_to_end_scoreboard", "system_coverage"):
        func = getattr(sec, name)
        with pytest.raises(NotImplementedError):
            func({"soc_name": "SYNTH", "subsystems": [{"name": "PCIE"}, {"name": "USB"}]})


# ============================================================================
# Real CLI subprocess runs
# ============================================================================

def _synthetic_project(tmp_path: Path):
    """A real project tree the SYS-1 selection gate admits, built through the
    SYS-9..14 suite's own environment builder so the two layers cannot drift
    into two fixture shapes."""
    from dv_harness_tests.test_subsystem_architecture_and_command_contract import (
        _subsystem_env)
    a = _subsystem_env(tmp_path, "subsys_a", CPU_SIDE_COMMANDS)
    b = _subsystem_env(tmp_path, "subsys_b", CONTENDING_CPU_SIDE_COMMANDS)
    registry = (tmp_path / ".dv-harness" / "soc-composer"
                / "subsystem_environment_registry.json")
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps({"subsystems": [
        {"name": n, "environment_manifest": str(e / ".dv-harness" / "env.manifest.json"),
         "release_sha": sha, "qualification_state": "REGRESSION_QUALIFIED",
         "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS"}
        for n, e, sha in (("SUBSYS_A", a, "aaa111"), ("SUBSYS_B", b, "bbb222"))
    ]}), encoding="utf-8")
    sources = sd.candidate_sources_path(tmp_path)
    sources.parent.mkdir(parents=True, exist_ok=True)
    sources.write_text(json.dumps({"candidates": [
        {"name": "SUBSYS_A", "protocol": "SYNTH_A", "environment_path": str(a)},
        {"name": "SUBSYS_B", "protocol": "SYNTH_B", "environment_path": str(b)},
    ]}), encoding="utf-8")
    return a, b


def _run_cli(tmp_path: Path, *extra):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp_path),
         "system-command-plan", *extra],
        cwd=str(ROOT), capture_output=True, text=True)


def test_cli_reports_the_collisions_and_exits_nonzero(tmp_path):
    """A standing blocking collision must not read as a clean run to a CI
    step: a System command.txt must not be synthesised on that plan."""
    _synthetic_project(tmp_path)
    proc = _run_cli(tmp_path, "--select", "SUBSYS_A", "--select", "SUBSYS_B")
    assert proc.returncode == 2, proc.stderr
    assert "COMPETING_ACTIVE_VIP_TRAFFIC" in proc.stdout
    assert "CONFLICTING_REGISTER_WRITE" in proc.stdout
    assert "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED" in proc.stdout
    assert "PLANNED_NOT_IMPLEMENTED" in proc.stdout


def test_cli_refuses_and_says_so_when_nothing_is_selected(tmp_path):
    """An empty plan must read as "nothing was selected", never as "these
    subsystems are clean"."""
    _synthetic_project(tmp_path)
    proc = _run_cli(tmp_path)
    assert proc.returncode == 2, proc.stderr
    assert "NO_EXPLICIT_SELECTION" in proc.stdout
    # No collision FINDING (the class vocabulary is printed as a legend either
    # way; a finding carries a SYSCOL id).
    assert "SYSCOL-" not in proc.stdout
    assert "no collision detected in this command set" in proc.stdout
    assert "Selected SUBSYS_A Env" not in proc.stdout


def test_cli_escalate_files_real_questions_and_the_run_writes_no_command_txt(tmp_path):
    """The real end-to-end path: a real subprocess, a real question queue on
    disk, and both subsystem environments byte-identical afterwards."""
    a, b = _synthetic_project(tmp_path)
    before = {**_snapshot(a), **_snapshot(b)}
    proc = _run_cli(tmp_path, "--select", "SUBSYS_A", "--select", "SUBSYS_B", "--escalate")
    assert proc.returncode == 2, proc.stderr
    assert "collision question(s) filed" in proc.stdout
    questions = question_queue.QuestionQueueStore(tmp_path).list_questions()
    assert questions, proc.stdout
    assert all(q["domain"] == "env" for q in questions)
    assert {**_snapshot(a), **_snapshot(b)} == before
    # No System command.txt was written anywhere in the project.
    assert not list(tmp_path.rglob("system_command.txt"))
    assert not list(tmp_path.rglob("soc_command.txt"))
    for path in tmp_path.rglob("*.sv"):
        assert path.read_text(encoding="utf-8") == (
            "// synthetic fixture, empty on purpose\n"), path
