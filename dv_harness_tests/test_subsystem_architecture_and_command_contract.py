"""Tests for SYS-5..SYS-8 of the System-Level Verification Integration
workflow:

  reference_pattern_audit.py's new SYS-7 command.txt grammar / control-flow /
  dependency layer, dv_harness/subsystem_command_contract.py (SYS-8), and
  dv_harness/subsystem_architecture_analysis.py (SYS-5 + SYS-6).

EVERY fixture is SYNTHETIC and built inside a tmp_path: fake command.txt files
written in the real macro grammar, fake subsystem environment trees, a fake
registry, a fake topology dump, a fake SoC architecture map. Nothing touches
the real .dv-harness/soc-composer/subsystem_environment_registry.json (which
is legitimately absent in this repo), no real project's command.txt is opened,
and no test generates System-Level UVM source, a System command.txt or a
virtual sequencer -- SYS-5..8 is discovery/analysis/reporting only, and two
tests assert that rather than trusting it.

The suite is deliberately not a happy path. The cases that carry the coverage
for a dedup/conflict mechanism are the conflicting ones: two subsystems both
actively driving one CPU-side BFM, two subsystems writing one address literal,
two subsystems merely READING one block (which must NOT be reported as a
driver conflict), a single-subsystem set whose parallel-safety is honestly
undecidable, and an analysis that read a neighbour's evidence.
"""
import json
from pathlib import Path

import pytest

from dv_harness import reference_pattern_audit as rpa
from dv_harness import subsystem_architecture_analysis as saa
from dv_harness import subsystem_command_contract as scc
from dv_harness import subsystem_discovery as sd

ROOT = Path(__file__).resolve().parents[1]


# --- synthetic command.txt fixtures ------------------------------------------
# Written in the real macro grammar confirmed against D:/DV/Task/USB/command.txt
# and D:/DV/Task/USB/patterns/*.txt, but the content is invented for this test
# and describes no real DUT.

CPU_SIDE_COMMANDS = """\
//=========================================================================
// File Name    : synthetic_cpu_side.txt  (TEST FIXTURE ONLY)
//=========================================================================
`include "wave.txt"
reg [7:0] regdata1B;
integer   i;

initial
begin
  `GMODEL.GLOBAL_INIT;
  $display("global init done");
  `CPUWRITE4B(32'h1400_0000, 32'h1);      //ctrl rst=1
  `CPUWRITE4B(32'h1400_0004, 32'h2600);   //enable
  wait(top.dut.u_core.irq_done_evt);
  #100;
  `CPUWRITE4B(32'h1400_0008, 32'h1);      //irq clear
  `CPUREAD4B (32'h1400_0004, i);
  `SMEMMODEL.FILLMEM("/synthetic/path/trb.hex" ,
                     4,
                     40'h2000_1000,
                     'd32);
  force top.dut.override_n = 1'b0;
  release top.dut.override_n;
  $finish;
end
"""

HOST_SIDE_COMMANDS = """\
//=========================================================================
// File Name    : synthetic_host_side.txt  (TEST FIXTURE ONLY)
//=========================================================================
initial
begin
  `HOSTWRITE4B(32'h1700_0000, 32'h5);
  `HOSTWRITE4B(32'h1700_0010, 32'h9);
  wait(top.host.link_up);
  $finish;
end
"""

# Deliberately contends with CPU_SIDE_COMMANDS: the same `CPUWRITE4B macro
# (therefore the same DUT-side BFM), the same 1400 register block, and the
# exact same address literal 32'h1400_0000.
CONTENDING_CPU_SIDE_COMMANDS = """\
//=========================================================================
// File Name    : synthetic_second_subsystem.txt  (TEST FIXTURE ONLY)
//=========================================================================
initial
begin
  `GMODEL.GLOBAL_INIT;
  `CPUWRITE4B(32'h1400_0000, 32'h7);      //same address, different value
  `CPUWRITE4B(32'h1500_0000, 32'h3);
  $finish;
end
"""

READ_ONLY_COMMANDS = """\
initial
begin
  `CPUREAD4B (32'h1900_0000, i);
  `CPUREAD4B (32'h1900_0004, i);
end
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ============================================================================
# SYS-7 -- the command.txt grammar layer on reference_pattern_audit
# ============================================================================

def test_macro_name_shape_is_written_once_and_both_layers_agree():
    """Drift guard. The write-symmetry layer's full call regex and the SYS-7
    statement classifier's name regex are now built from ONE fragment; two
    spellings of "what a register macro name looks like" is how the two layers
    would come to disagree about the same call."""
    assert rpa._MACRO_NAME_FRAGMENT in rpa._MACRO_CALL_RE.pattern
    assert rpa._MACRO_NAME_FRAGMENT in rpa._REGISTER_MACRO_NAME_RE.pattern
    for name in ("HOSTWRITE4B", "CPUWRITE1B", "DEVREAD2B"):
        assert rpa._REGISTER_MACRO_NAME_RE.match(name)
        call = f"`{name}(32'h1000_0000, 32'h1);"
        assert rpa._MACRO_CALL_RE.search(call), name
    for name in ("HOSTWRITE", "WRITE4B", "hostwrite4b", "CPUWRITE4"):
        assert not rpa._REGISTER_MACRO_NAME_RE.match(name), name


def test_existing_write_symmetry_layer_still_extracts_the_same_writes(tmp_path):
    """The regex factoring must not have changed the pre-existing layer's
    behaviour. Register READs stay discarded there (that layer is a WRITE
    symmetry audit) even though the SYS-7 layer now classifies them."""
    path = _write(tmp_path / "p.txt", CPU_SIDE_COMMANDS)
    writes = rpa.extract_register_writes(path)
    assert [w.macro for w in writes] == ["CPUWRITE4B"] * 3
    assert all(w.host_or_dut_context == "DUT" for w in writes)
    assert [w.base for w in writes] == ["1400", "1400", "1400"]
    assert not any(w.macro.endswith("READ4B") for w in writes)


def test_every_real_command_txt_idiom_is_classified(tmp_path):
    path = _write(tmp_path / "c.txt", CPU_SIDE_COMMANDS)
    statements = rpa.extract_command_statements(path)
    kinds = {s.kind for s in statements}
    for expected in (rpa.K_REGISTER_WRITE, rpa.K_REGISTER_READ, rpa.K_MODEL_TASK_CALL,
                     rpa.K_WAIT_CONDITION, rpa.K_DELAY, rpa.K_FORCE, rpa.K_RELEASE,
                     rpa.K_DISPLAY, rpa.K_TERMINATION, rpa.K_DIRECTIVE,
                     rpa.K_DECLARATION, rpa.K_PROCESS, rpa.K_BLOCK_BEGIN,
                     rpa.K_BLOCK_END):
        assert expected in kinds, expected
    assert all(s.kind in rpa.STATEMENT_KINDS for s in statements)
    assert all(s.category in rpa.COMMAND_CATEGORIES for s in statements)
    # Nothing falls through to UNCLASSIFIED on the real grammar.
    assert [s.text for s in statements if s.kind == rpa.K_UNCLASSIFIED] == []


def test_a_call_spanning_four_lines_is_one_statement(tmp_path):
    """`SMEMMODEL.FILLMEM(...) spans four physical lines in the real corpus. A
    line-at-a-time reader -- which is exactly what the write-symmetry layer is
    -- sees four fragments; the SYS-7 layer must see one call with four args."""
    path = _write(tmp_path / "c.txt", CPU_SIDE_COMMANDS)
    fillmem = [s for s in rpa.extract_command_statements(path)
               if s.name == "`SMEMMODEL.FILLMEM"]
    assert len(fillmem) == 1
    stmt = fillmem[0]
    assert stmt.end_line - stmt.line == 3
    assert len(stmt.arguments) == 4
    assert stmt.arguments[0] == '"/synthetic/path/trb.hex"'
    assert stmt.arguments[2] == "40'h2000_1000"


def test_comment_and_string_awareness(tmp_path):
    """A `//` inside a string literal is not a comment, a comma inside one does
    not split an argument, and a trailing comment is kept as the field hint --
    the only place a bare hex value's engineering meaning is stated."""
    path = _write(tmp_path / "c.txt",
                  'initial begin\n'
                  '  `SMEMMODEL.FILLMEM("http://host/a,b.hex", 4);  //two args, not three\n'
                  '  `CPUWRITE4B(32\'h1400_0000, 32\'h1); //ctrl rst=1\n'
                  'end\n')
    statements = rpa.extract_command_statements(path)
    fillmem = next(s for s in statements if s.name == "`SMEMMODEL.FILLMEM")
    assert fillmem.arguments == ['"http://host/a,b.hex"', "4"]
    assert fillmem.comment == "two args, not three"
    write = next(s for s in statements if s.kind == rpa.K_REGISTER_WRITE)
    assert write.comment == "ctrl rst=1"


def test_string_text_never_becomes_a_consumer(tmp_path):
    """$display("...Command.") and `include "wave.txt" both contain a dotted
    token that is text, not a hierarchical reference."""
    path = _write(tmp_path / "c.txt",
                  'initial begin\n'
                  '  $display("=>Start 2nd Address Device Command.");\n'
                  '  wait(top.dut.ready);\n'
                  'end\n')
    roles = rpa.classify_command_roles(rpa.extract_command_statements(path))
    consumers = {c["consumer"] for c in roles["consumers"]}
    assert consumers == {"top"}
    assert "Command" not in consumers


def test_interrupt_waits_are_classified_and_cite_the_deciding_token(tmp_path):
    path = _write(tmp_path / "c.txt",
                  'initial begin\n'
                  '  wait(top.dut.irq_done_evt);\n'
                  '  wait(top.dut.sram_init_done);\n'
                  'end\n')
    analysis = rpa.analyze_command_file(path)
    waits = analysis["waits"]["waits"]
    assert [w["wait_class"] for w in waits] == ["INTERRUPT_EVENT_WAIT", "SIGNAL_LEVEL_WAIT"]
    assert "evt" in waits[0]["matched_tokens"]
    assert waits[0]["basis"] == "SIGNAL_NAME_TOKEN_MATCH"
    # The second wait is not guessed either way -- absence of a token is its
    # whole basis, and it says so.
    assert waits[1]["matched_tokens"] == []
    assert waits[1]["basis"] == "NO_INTERRUPT_NAME_TOKEN"
    assert analysis["interrupt_waits"]["count"] == 1


def test_ordering_edges_are_semantic_never_implicit_program_order(tmp_path):
    path = _write(tmp_path / "c.txt", CPU_SIDE_COMMANDS)
    ordering = rpa.analyze_command_file(path)["ordering"]
    relations = set(ordering["relations_used"])
    assert "WAIT_GATED" in relations
    assert "DELAY_GATED" in relations
    assert "INITIALIZATION_PRECEDES" in relations
    assert "ADDRESS_READ_AFTER_WRITE" in relations
    assert relations <= set(rpa.ORDERING_RELATIONS)
    # 20 statements would give ~190 pairwise program-order edges; a semantic
    # edge set must be far smaller than that or it carries no information.
    assert len(ordering["edges"]) < 20
    assert not ordering["truncated"]


def test_force_without_a_matching_release_says_so(tmp_path):
    path = _write(tmp_path / "c.txt",
                  "initial begin\n  force top.dut.a = 1'b0;\n"
                  "  `CPUWRITE4B(32'h1400_0000, 32'h1);\nend\n")
    edges = rpa.analyze_command_file(path)["ordering"]["edges"]
    force_edge = next(e for e in edges if e["relation"] == "FORCE_ACTIVE_DURING")
    assert "no matching release found" in force_edge["detail"]


def test_absent_aspects_report_not_found_with_the_search_performed(tmp_path):
    """An aspect nobody mentions is indistinguishable from one nobody looked
    for. The real USB corpus has no loops and no $error at all, so these must
    be reported as NOT_FOUND with the search, not omitted."""
    path = _write(tmp_path / "c.txt", CPU_SIDE_COMMANDS)
    analysis = rpa.analyze_command_file(path)
    for aspect in ("loops_and_repetition", "concurrency", "error_handling"):
        assert analysis[aspect]["status"] == "NOT_FOUND", aspect
        assert analysis[aspect]["count"] == 0
        assert analysis[aspect]["searched_for"]
    assert analysis["termination"]["status"] == "EXPLICIT"


def test_loops_and_fork_join_are_classified_when_present(tmp_path):
    path = _write(tmp_path / "c.txt",
                  "initial begin\n  repeat (4) begin\n"
                  "    `CPUWRITE4B(32'h1400_0000, 32'h1);\n  end\n"
                  "  fork\n    #10;\n  join_none\n"
                  '  if (i != 0) $error("mismatch");\nend\n')
    analysis = rpa.analyze_command_file(path)
    assert analysis["loops_and_repetition"]["status"] == "FOUND"
    assert analysis["concurrency"]["status"] == "FOUND"
    assert analysis["error_handling"]["status"] == "FOUND"


def test_parser_is_unresolved_rather_than_guessed_and_resolves_when_supplied(tmp_path):
    path = _write(tmp_path / "c.txt", CPU_SIDE_COMMANDS)
    unresolved = rpa.analyze_command_file(path)["roles"]["parser"]
    assert unresolved["status"] == "UNRESOLVED"
    assert "CPUWRITE4B" in unresolved["unresolved_macros"]

    defs = _write(tmp_path / "defs.svh",
                  "`define CPUWRITE4B(a,d) ...\n`define CPUREAD4B(a,d) ...\n"
                  "`define GMODEL tb.gmodel\n`define SMEMMODEL tb.smem\n")
    resolved = rpa.analyze_command_file(
        path, macro_definition_sources=[defs])["roles"]["parser"]
    assert resolved["status"] == "RESOLVED"
    assert str(defs) in resolved["resolved_macros"]["CPUWRITE4B"]
    assert resolved["unresolved_macros"] == []


def test_producer_is_unresolved_unless_declared(tmp_path):
    path = _write(tmp_path / "c.txt", CPU_SIDE_COMMANDS)
    assert rpa.analyze_command_file(path)["roles"]["producer"]["status"] == "UNRESOLVED"
    declared = rpa.analyze_command_file(path, declared_producer="DE_DV")["roles"]["producer"]
    assert declared["status"] == "DECLARED"
    assert declared["value"] == "DE_DV"


def test_dispatchers_and_target_vip_sequences_come_from_the_calls(tmp_path):
    path = _write(tmp_path / "c.txt", CPU_SIDE_COMMANDS)
    roles = rpa.analyze_command_file(path)["roles"]
    assert {d["dispatcher"] for d in roles["dispatchers"]} == {"CPUWRITE4B", "CPUREAD4B"}
    assert {t["target_sequence"] for t in roles["target_vip_sequences"]} == {
        "`GMODEL.GLOBAL_INIT", "`SMEMMODEL.FILLMEM"}
    assert "<DUT_SIDE_BFM>" in {c["consumer"] for c in roles["consumers"]}


def test_sys7_analysis_never_modifies_the_command_txt(tmp_path):
    """SYS-7's own closing rule and SYS-8's 'Keep original command.txt intact'."""
    path = _write(tmp_path / "c.txt", CPU_SIDE_COMMANDS)
    before = path.read_bytes()
    rpa.analyze_command_file(path)
    rpa.extract_command_statements(path)
    scc.build_subsystem_contracts("S", [path])
    assert path.read_bytes() == before


# ============================================================================
# SYS-8 -- SubsystemCommandContract
# ============================================================================

def test_contract_dataclass_carries_sys8s_field_list_in_its_own_order():
    from dataclasses import fields as dataclass_fields
    names = [f.name for f in dataclass_fields(scc.SubsystemCommandContract)]
    assert names[:len(scc.SYS8_FIELDS)] == list(scc.SYS8_FIELDS)
    # The only extra field is the documented basis for parallel_safe.
    assert names[len(scc.SYS8_FIELDS):] == ["parallel_safety_reason"]


def test_json_schema_requires_exactly_sys8s_field_list():
    schema = json.loads(scc.SCHEMA_PATH.read_text(encoding="utf-8"))
    required = schema["$defs"]["contract"]["required"]
    assert required == list(scc.SYS8_FIELDS)
    properties = set(schema["$defs"]["contract"]["properties"])
    assert set(scc.SYS8_FIELDS) | {"parallel_safety_reason"} == properties


def test_contract_set_validates_against_the_real_schema(tmp_path):
    doc = scc.build_contract_set({
        "SUBSYS_A": [_write(tmp_path / "a" / "command.txt", CPU_SIDE_COMMANDS)],
        "SUBSYS_B": [_write(tmp_path / "b" / "command.txt", CONTENDING_CPU_SIDE_COMMANDS)],
    })
    scc.validate_contract_set(doc)
    assert doc["command_txt_modified"] is False
    assert "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED" in doc["phase_boundary"]


def test_single_subsystem_set_reports_parallel_safety_as_undecidable(tmp_path):
    """The honesty case. A contract set holding ONE subsystem has no second
    subsystem to be concurrent with, so every verdict must be UNKNOWN with the
    reason -- not PARALLEL_SAFE by default, which would be a claim nothing in
    the set supports."""
    doc = scc.build_contract_set({
        "SUBSYS_A": [_write(tmp_path / "a" / "command.txt", CPU_SIDE_COMMANDS)]})
    assert doc["contracts"]
    assert {c["parallel_safe"] for c in doc["contracts"]} == {scc.PARALLEL_SAFETY_UNKNOWN}
    assert all("SINGLE_SUBSYSTEM_CONTRACT_SET" in c["parallel_safety_reason"]
               for c in doc["contracts"])
    assert all(c["serialization_required"] is False for c in doc["contracts"])
    assert all(c["shared_resource_dependency"] == [] for c in doc["contracts"])
    assert doc["conflicts"] == []
    assert doc["summary"]["parallel_safety_undecidable"] == len(doc["contracts"])


def test_two_subsystems_driving_one_cpu_side_bfm_is_a_duplicate_active_driver(tmp_path):
    """THE conflicting case this mechanism exists for -- SYS-10's "PCIe and USB
    both contain a CPU AXI Master representing the same SoC physical
    interface", arriving through their command.txt files. Both subsystems
    invoke `CPUWRITE4B, so both actively drive BFM:DUT_SIDE."""
    doc = scc.build_contract_set({
        "SUBSYS_A": [_write(tmp_path / "a" / "command.txt", CPU_SIDE_COMMANDS)],
        "SUBSYS_B": [_write(tmp_path / "b" / "command.txt", CONTENDING_CPU_SIDE_COMMANDS)],
    })
    duplicates = [c for c in doc["conflicts"]
                  if c["conflict_type"] == "DUPLICATE_ACTIVE_DRIVER"]
    bfm = next(c for c in duplicates if c["resource_id"] == "BFM:DUT_SIDE")
    assert bfm["subsystems"] == ["SUBSYS_A", "SUBSYS_B"]
    assert bfm["writing_subsystems"] == ["SUBSYS_A", "SUBSYS_B"]
    assert bfm["resolution"] == "STOP_AUTOMATIC_INTEGRATION_UNTIL_OWNERSHIP_RESOLVED"
    assert bfm["evidence"], "a conflict with no citation is not checkable"
    # And the affected contracts are marked, not just the conflict list.
    a_write = next(c for c in doc["contracts"]
                   if c["subsystem_id"] == "SUBSYS_A" and c["command_name"] == "CPUWRITE4B")
    assert a_write["parallel_safe"] == scc.NOT_PARALLEL_SAFE
    assert a_write["serialization_required"] is True
    shared = {s["resource_id"]: s for s in a_write["shared_resource_dependency"]}
    assert shared["BFM:DUT_SIDE"]["contention"] == "ACTIVE_DRIVER_CONTENTION"
    assert shared["BFM:DUT_SIDE"]["other_subsystems"] == ["SUBSYS_B"]


def test_two_subsystems_writing_one_address_is_an_address_write_collision(tmp_path):
    doc = scc.build_contract_set({
        "SUBSYS_A": [_write(tmp_path / "a" / "command.txt", CPU_SIDE_COMMANDS)],
        "SUBSYS_B": [_write(tmp_path / "b" / "command.txt", CONTENDING_CPU_SIDE_COMMANDS)],
    })
    collisions = [c for c in doc["conflicts"]
                  if c["conflict_type"] == "ADDRESS_WRITE_COLLISION"]
    assert [c["address"] for c in collisions] == ["32'h1400_0000"]
    assert collisions[0]["writing_subsystems"] == ["SUBSYS_A", "SUBSYS_B"]
    # 32'h1400_0004 is written only by A; a single writer is not a collision.
    assert "32'h1400_0004" not in {c.get("address") for c in collisions}


def test_two_subsystems_only_reading_one_block_is_not_a_driver_conflict(tmp_path):
    """A dedup mechanism that reports read/read sharing as a driver conflict
    trains its users to ignore it. Two subsystems reading the same block share
    a resource; neither drives it."""
    doc = scc.build_contract_set({
        "SUBSYS_A": [_write(tmp_path / "a" / "command.txt", READ_ONLY_COMMANDS)],
        "SUBSYS_B": [_write(tmp_path / "b" / "command.txt", READ_ONLY_COMMANDS)],
    })
    assert doc["conflicts"] == []
    read = next(c for c in doc["contracts"] if c["command_name"] == "CPUREAD4B")
    shared = {s["resource_id"]: s for s in read["shared_resource_dependency"]}
    assert shared["REGISTER_BLOCK:1900"]["contention"] == "READ_ONLY_SHARING"
    assert read["parallel_safe"] == scc.PARALLEL_SAFE
    assert read["serialization_required"] is False


def test_a_subsystem_contending_only_with_itself_is_not_a_conflict(tmp_path):
    """Two command.txt files of ONE subsystem writing the same block is
    ordinary -- a command.txt is sequential by construction, and its ordering
    is already expressed by ordering_constraints."""
    doc = scc.build_contract_set({
        "SUBSYS_A": [_write(tmp_path / "a" / "one.txt", CPU_SIDE_COMMANDS),
                     _write(tmp_path / "a" / "two.txt", CONTENDING_CPU_SIDE_COMMANDS)],
        "SUBSYS_B": [_write(tmp_path / "b" / "command.txt", HOST_SIDE_COMMANDS)],
    })
    assert [c for c in doc["conflicts"]
            if c["conflict_type"] == "ADDRESS_WRITE_COLLISION"] == []
    host = next(c for c in doc["contracts"]
                if c["subsystem_id"] == "SUBSYS_B" and c["command_name"] == "HOSTWRITE4B")
    assert host["parallel_safe"] == scc.PARALLEL_SAFE


def test_required_resources_carry_kind_access_basis_and_citation(tmp_path):
    doc = scc.build_contract_set({
        "SUBSYS_A": [_write(tmp_path / "a" / "command.txt", CPU_SIDE_COMMANDS)]})
    write = next(c for c in doc["contracts"] if c["command_name"] == "CPUWRITE4B")
    by_id = {r["resource_id"]: r for r in write["required_resources"]}
    assert by_id["BFM:DUT_SIDE"]["access"] == "WRITE"
    assert by_id["REGISTER_BLOCK:1400"]["resource_kind"] == scc.R_REGISTER_BLOCK
    assert all(r["basis"] for r in write["required_resources"])
    assert all(r["evidence"] for r in write["required_resources"])
    fillmem = next(c for c in doc["contracts"]
                   if c["command_name"] == "`SMEMMODEL.FILLMEM")
    assert "MEMORY_MODEL:SMEMMODEL" in {r["resource_id"]
                                        for r in fillmem["required_resources"]}
    assert fillmem["target_vip"] == "SMEMMODEL"
    assert fillmem["target_sequence"] == "FILLMEM"


def test_arguments_carry_positional_roles_derived_from_the_macro_shape(tmp_path):
    doc = scc.build_contract_set({
        "SUBSYS_A": [_write(tmp_path / "a" / "command.txt", CPU_SIDE_COMMANDS)]})
    write = next(c for c in doc["contracts"] if c["command_name"] == "CPUWRITE4B")
    assert [a["role"] for a in write["arguments"]] == ["ADDRESS", "VALUE"]
    assert write["arguments"][0]["distinct_value_count"] == 3
    read = next(c for c in doc["contracts"] if c["command_name"] == "CPUREAD4B")
    assert [a["role"] for a in read["arguments"]] == ["ADDRESS", "DESTINATION"]


def test_interrupt_and_reset_dependencies_are_derived_with_a_cited_basis(tmp_path):
    doc = scc.build_contract_set({
        "SUBSYS_A": [_write(tmp_path / "a" / "command.txt", CPU_SIDE_COMMANDS)]})
    write = next(c for c in doc["contracts"] if c["command_name"] == "CPUWRITE4B")
    assert write["interrupt_dependency"]["depends_on_interrupt"] is True
    assert write["interrupt_dependency"]["waits"][0]["matched_tokens"]
    assert write["reset_dependency"]["touches_reset"] is True
    assert "rst" in write["reset_dependency"]["statements"][0]["matched_tokens"]
    host_only = scc.build_contract_set({
        "SUBSYS_B": [_write(tmp_path / "b" / "command.txt", HOST_SIDE_COMMANDS)]})
    hw = next(c for c in host_only["contracts"] if c["command_name"] == "HOSTWRITE4B")
    assert hw["reset_dependency"]["touches_reset"] is False
    assert hw["reset_dependency"]["basis"] == "NO_RESET_NAME_TOKEN"


def test_preconditions_record_the_initialization_that_precedes_every_invocation(tmp_path):
    doc = scc.build_contract_set({
        "SUBSYS_A": [_write(tmp_path / "a" / "command.txt", CPU_SIDE_COMMANDS)]})
    write = next(c for c in doc["contracts"] if c["command_name"] == "CPUWRITE4B")
    kinds = {p["kind"] for p in write["preconditions"]}
    assert "PRECEDING_INITIALIZATION" in kinds
    init = next(p for p in write["preconditions"]
                if p["kind"] == "PRECEDING_INITIALIZATION")
    assert init["detail"] == "`GMODEL.GLOBAL_INIT"
    assert ":" in init["evidence"]


def test_clock_domain_is_unresolved_without_a_declared_region_clock_map(tmp_path):
    """Two resolution steps, each able to fail honestly on its own. A
    soc_arch_map address_map entry carries no clock of its own, so naming the
    located regions and reporting UNRESOLVED is the correct answer."""
    command = _write(tmp_path / "a" / "command.txt", CPU_SIDE_COMMANDS)
    address_map = [{"name": "CTRL_BLOCK", "base_address": "0x14000000",
                    "size_bytes": 0x1000}]

    no_map = scc.build_contract_set({"SUBSYS_A": [command]})
    write = next(c for c in no_map["contracts"] if c["command_name"] == "CPUWRITE4B")
    assert write["clock_domain"]["status"] == "UNRESOLVED"
    assert "no address map supplied" in write["clock_domain"]["reason"]

    regions_only = scc.build_contract_set(
        {"SUBSYS_A": [command]}, address_maps={"SUBSYS_A": address_map})
    write = next(c for c in regions_only["contracts"] if c["command_name"] == "CPUWRITE4B")
    assert write["clock_domain"]["status"] == "UNRESOLVED"
    assert write["clock_domain"]["address_regions"] == ["CTRL_BLOCK"]

    resolved = scc.build_contract_set(
        {"SUBSYS_A": [command]}, address_maps={"SUBSYS_A": address_map},
        region_clock_maps={"SUBSYS_A": {"CTRL_BLOCK": "core_clk"}})
    write = next(c for c in resolved["contracts"] if c["command_name"] == "CPUWRITE4B")
    assert write["clock_domain"]["status"] == "RESOLVED"
    assert write["clock_domain"]["clock"] == "core_clk"


def test_clock_domain_reports_multiple_when_a_command_spans_two_domains(tmp_path):
    command = _write(tmp_path / "a" / "command.txt", CONTENDING_CPU_SIDE_COMMANDS)
    address_map = [{"name": "BLK_A", "base_address": "0x14000000", "size_bytes": 0x1000},
                   {"name": "BLK_B", "base_address": "0x15000000", "size_bytes": 0x1000}]
    doc = scc.build_contract_set(
        {"SUBSYS_A": [command]}, address_maps={"SUBSYS_A": address_map},
        region_clock_maps={"SUBSYS_A": {"BLK_A": "clk_a", "BLK_B": "clk_b"}})
    write = next(c for c in doc["contracts"] if c["command_name"] == "CPUWRITE4B")
    assert write["clock_domain"]["status"] == "MULTIPLE"
    assert write["clock_domain"]["clocks"] == ["clk_a", "clk_b"]


def test_declared_command_inventory_overlay_supplies_handler_and_vip_sequence(tmp_path):
    """The repo's real command_inventory.csv is an existing recorded answer to
    'who handles this command'. Re-deriving it from scratch would be a second,
    competing answer -- it is read as a declared overlay and never rewritten."""
    csv_path = _write(tmp_path / "command_inventory.csv",
                      "COMMAND_ID,PROTOCOL,COMMAND,PARAMETERS,SOURCE,USER_SCOPE,"
                      "HANDLER,VIP_SEQUENCE,STATUS,CONFIDENCE\n"
                      "CMD-900,SYNTH,CPUWRITE4B,addr+value,fixture,DE_DV,"
                      "synthetic_cpu_bfm_task,synth_write_vseq,FIXTURE,HIGH\n")
    before = csv_path.read_bytes()
    doc = scc.build_contract_set(
        {"SUBSYS_A": [_write(tmp_path / "a" / "command.txt", CPU_SIDE_COMMANDS)]},
        inventory_overlay_path=csv_path)
    write = next(c for c in doc["contracts"] if c["command_name"] == "CPUWRITE4B")
    assert write["target_agent"] == "synthetic_cpu_bfm_task"
    assert write["target_sequence"] == "synth_write_vseq"
    assert any("CMD-900" in e for e in write["evidence"])
    assert csv_path.read_bytes() == before

    # An absent overlay is an honest "nothing declared", never a failure.
    assert scc.load_command_inventory_overlay(tmp_path / "nope.csv") == {}


def test_ordering_constraints_are_a_view_of_the_sys7_edges_not_a_second_derivation(tmp_path):
    path = _write(tmp_path / "a" / "command.txt", CPU_SIDE_COMMANDS)
    edges = rpa.analyze_command_file(path)["ordering"]["edges"]
    doc = scc.build_contract_set({"SUBSYS_A": [path]})
    write = next(c for c in doc["contracts"] if c["command_name"] == "CPUWRITE4B")
    assert write["ordering_constraints"]
    assert {o["relation"] for o in write["ordering_constraints"]} <= {
        e["relation"] for e in edges}
    assert all(o["direction"] in ("PRECEDES", "FOLLOWS")
               for o in write["ordering_constraints"])
    # Repeated identical edges are collapsed with a count, not listed 900 times.
    assert all(o.get("occurrences", 1) >= 1 for o in write["ordering_constraints"])


# ============================================================================
# SYS-5 / SYS-6 -- per-subsystem architecture analysis
# ============================================================================

def _topology_dump(path: Path) -> Path:
    return _write(path, json.dumps({"components": [
        {"full_name": "uvm_test_top", "type_name": "synth_base_test", "is_active": "UVM_ACTIVE"},
        {"full_name": "uvm_test_top.env", "type_name": "synth_env", "is_active": "UVM_ACTIVE"},
        {"full_name": "uvm_test_top.env.agent0", "type_name": "synth_agent", "is_active": "UVM_ACTIVE"},
        {"full_name": "uvm_test_top.env.agent0.drv", "type_name": "synth_driver", "is_active": "UVM_ACTIVE"},
        {"full_name": "uvm_test_top.env.agent0.mon", "type_name": "synth_monitor", "is_active": "UVM_PASSIVE"},
        {"full_name": "uvm_test_top.env.agent0.seqr", "type_name": "synth_sequencer", "is_active": "UVM_ACTIVE"},
        {"full_name": "uvm_test_top.env.vseqr", "type_name": "synth_virtual_sequencer", "is_active": "UVM_ACTIVE"},
        {"full_name": "uvm_test_top.env.sb", "type_name": "synth_scoreboard", "is_active": "UVM_PASSIVE"},
        {"full_name": "uvm_test_top.env.pred", "type_name": "synth_predictor", "is_active": "UVM_PASSIVE"},
        {"full_name": "uvm_test_top.env.cov", "type_name": "synth_coverage_collector", "is_active": "UVM_PASSIVE"},
        {"full_name": "uvm_test_top.env.chk", "type_name": "synth_checker", "is_active": "UVM_PASSIVE"},
        {"full_name": "uvm_test_top.env.refm", "type_name": "synth_reference_model", "is_active": "UVM_PASSIVE"},
        {"full_name": "uvm_test_top.env.mystery", "type_name": "synth_widget", "is_active": "NOT_APPLICABLE"},
    ]}))


def _soc_arch_map(path: Path) -> Path:
    return _write(path, json.dumps({
        "schema_version": "1.0",
        "address_map": [
            {"name": "CTRL_BLOCK", "base_address": "0x14000000", "size_bytes": 4096},
            {"name": "MEM_MODEL_WINDOW", "base_address": "0x20000000", "size_bytes": 65536},
        ],
        "clocks": [{"name": "core_clk", "frequency_mhz": 100}],
        "resets": [{"name": "core_rst_n", "active_level": "low", "clock": "core_clk"}],
    }))


def _subsystem_env(tmp_path: Path, name: str, command_text: str) -> Path:
    """A synthetic subsystem environment carrying a real (schema-valid)
    env.manifest.json, a run_profile.json and a command.txt."""
    from dv_harness import env_manifest
    from dv_harness.uvm_generator import run_profile

    env = tmp_path / "generated" / name
    (env / ".dv-harness").mkdir(parents=True, exist_ok=True)
    _write(env / "command.txt", command_text)
    # The rest of SYS-4's 13 readiness factors, so this environment classifies
    # EXISTS_READY and the SYS-1 selection gate admits it. Empty stub files:
    # the readiness probe is a name-convention artifact probe (and says so),
    # and inventing plausible RTL/UVM content here would be fabricating
    # evidence a test has no business asserting against.
    for rel in ("rtl/dut_core.sv", "env/synth_env.sv", "env/synth_agent.sv",
                "env/synth_scoreboard.sv", "vip/svt_synth_vip.sv", "Makefile",
                "filelist.f", "test/synth_test.sv", "seq/synth_seq.sv",
                "tb/tb_top.sv", "cfg/synth_config.sv", "cfg/clock_reset_map.json",
                "logs/sim.log", "regression.list", "docs/readme.md"):
        _write(env / rel, "// synthetic fixture, empty on purpose\n")
    env_manifest.generate_and_write(
        env / ".dv-harness" / "env.manifest.json",
        topology_dump_path=_topology_dump(env / "topology_dump.json"),
        soc_arch_map_path=_soc_arch_map(env / "soc_arch_map.json"))
    profile = run_profile.new_empty_profile("makefile", str(env / "Makefile"), "SYNTH", "synth_")
    # run_profile.json's own real shape, per run_profile.schema.json.
    profile["runtime_params"] = [
        {"name": "WAVE", "type": "bool01", "default": "0"},
        {"name": "FSDB_REPORT", "type": "bool01", "default": "0"},
        {"name": "REGRESS_LIST", "type": "path", "default": "regression.list"},
    ]
    profile["targets"] = [{"name": "compile"}, {"name": "sim"}, {"name": "regress"}]
    (env / ".dv-harness" / "run_profile.json").write_text(
        json.dumps(profile), encoding="utf-8")
    return env


def _inputs_for(env: Path, subsystem_id: str, **extra) -> saa.SubsystemAnalysisInputs:
    return saa.SubsystemAnalysisInputs(
        subsystem_id=subsystem_id,
        environment_root=str(env),
        env_manifest_path=str(env / ".dv-harness" / "env.manifest.json"),
        run_profile_path=str(env / ".dv-harness" / "run_profile.json"),
        command_files=[str(env / "command.txt")],
        **extra)


# SYS-6's field list, copied verbatim from the master prompt (lines 4274-4519,
# "## SYS-6. ANALYZE EACH SUBSYSTEM VERIFICATION ARCHITECTURE"). Held against
# the code by the test below so the requirement and SYS6_FIELDS cannot drift
# apart in either direction -- the same drift-guard pattern
# source_authority.assert_doc_matches_code() already uses for the 9-level order.
SYS6_REQUIREMENT_TEXT = (
    "DUT hierarchy, UVM top/env, agents, VIPs, active/passive mode, sequencers, "
    "drivers, monitors, virtual sequencers, scoreboards, reference models, "
    "predictors, coverage collectors, assertions/checkers, config objects, "
    "virtual interfaces, clock/reset, interrupts, DMA, firmware interaction, "
    "register model, memory model, address map, "
    "build/run/regression/waveform/fsdbreport flows"
)


def _slug(item: str) -> str:
    return item.lower().replace("/", "_").replace(" ", "_")


def test_sys6_fields_match_the_requirements_own_list_one_to_one():
    items = SYS6_REQUIREMENT_TEXT.split(", ")
    assert len(items) == len(saa.SYS6_FIELDS) == 24
    for item, field_name in zip(items, saa.SYS6_FIELDS):
        # "DUT hierarchy" -> dut_hierarchy, "VIPs" -> vips,
        # "assertions/checkers" -> assertions_checkers, and so on.
        assert _slug(item).rstrip("s") in field_name or field_name.startswith(
            _slug(item).split("_")[0].rstrip("s")), (item, field_name)


def test_sys6_report_carries_a_verdict_for_every_mandated_field(tmp_path):
    env = _subsystem_env(tmp_path, "subsys_a", CPU_SIDE_COMMANDS)
    result = saa.analyze_subsystem_architecture(_inputs_for(env, "SUBSYS_A"))
    assert list(result["fields"]) == list(saa.SYS6_FIELDS)
    assert all(block["status"] in saa.FIELD_STATUSES
               for block in result["fields"].values())
    assert all(block["source"] for block in result["fields"].values())
    # Every non-DERIVED field must say WHY, or the report is unfalsifiable.
    assert all(block["reason"] for block in result["fields"].values()
               if block["status"] != saa.DERIVED)
    assert result["analysis_status"] == "COMPLETE"
    assert result["artifacts_modified"] is False


def test_the_fields_the_audit_found_missing_are_now_derived(tmp_path):
    """interrupts / DMA / firmware interaction / memory model / virtual
    interfaces / semantic component roles were the SYS-6 fields with no field,
    schema or code behind them anywhere."""
    env = _subsystem_env(tmp_path, "subsys_a", CPU_SIDE_COMMANDS)
    fields = saa.analyze_subsystem_architecture(_inputs_for(env, "SUBSYS_A"))["fields"]
    assert fields["interrupts"]["status"] == saa.DERIVED
    assert fields["interrupts"]["command_txt_waits"]
    assert fields["dma"]["status"] == saa.DERIVED  # the FILLMEM 'trb' descriptor load
    assert fields["firmware_interaction"]["status"] == saa.DERIVED
    assert fields["memory_model"]["status"] == saa.DERIVED
    assert "SMEMMODEL" in fields["memory_model"]["command_txt_models"]
    for role_field in ("scoreboards", "predictors", "coverage_collectors",
                       "reference_models", "assertions_checkers", "virtual_sequencers",
                       "sequencers", "drivers", "monitors", "agents"):
        assert fields[role_field]["status"] == saa.DERIVED, role_field
        assert fields[role_field]["components"], role_field


def test_component_roles_cite_what_decided_them_and_admit_unclassified(tmp_path):
    env = _subsystem_env(tmp_path, "subsys_a", CPU_SIDE_COMMANDS)
    roles = saa.analyze_subsystem_architecture(_inputs_for(env, "SUBSYS_A"))["component_roles"]
    by_name = {r["full_name"]: r for r in roles}
    # Most-specific-first ordering: a virtual sequencer must not be swallowed
    # by the plain "sequencer" token, and a plain one must still be found.
    assert by_name["uvm_test_top.env.vseqr"]["role"] == "virtual_sequencer"
    assert by_name["uvm_test_top.env.agent0.seqr"]["role"] == "sequencer"
    assert by_name["uvm_test_top.env.sb"]["role"] == "scoreboard"
    assert all(r["role_basis"] for r in roles)
    assert by_name["uvm_test_top.env.sb"]["matched_token"] == "scoreboard"
    # A component nothing matches is UNCLASSIFIED, never assigned a plausible
    # role -- that guess is what a name-token classifier must not make.
    mystery = by_name["uvm_test_top.env.mystery"]
    assert mystery["role"] == "UNCLASSIFIED"
    assert mystery["role_basis"] == "NO_ROLE_TOKEN_MATCH"
    assert all(r["role"] in saa.COMPONENT_ROLES for r in roles)


def test_a_declared_role_beats_the_name_tokens(tmp_path):
    env = _subsystem_env(tmp_path, "subsys_a", CPU_SIDE_COMMANDS)
    inputs = _inputs_for(env, "SUBSYS_A", declared_component_roles={
        "uvm_test_top.env.mystery": "scoreboard"})
    roles = saa.analyze_subsystem_architecture(inputs)["component_roles"]
    mystery = next(r for r in roles if r["full_name"] == "uvm_test_top.env.mystery")
    assert mystery["role"] == "scoreboard"
    assert mystery["role_basis"] == "DECLARED_BY_PROJECT"


def test_active_passive_comes_from_the_dump_never_from_a_name(tmp_path):
    env = _subsystem_env(tmp_path, "subsys_a", CPU_SIDE_COMMANDS)
    block = saa.analyze_subsystem_architecture(
        _inputs_for(env, "SUBSYS_A"))["fields"]["active_passive_mode"]
    assert block["status"] == saa.DERIVED
    assert "get_is_active" in block["source"]
    # The monitor is passive in the dump even though nothing in its NAME says so.
    assert "uvm_test_top.env.agent0.mon" in block["passive"]
    assert "uvm_test_top.env.agent0.drv" in block["active"]
    # NOT_APPLICABLE stays its own third state -- a component with no
    # active/passive concept is not silently counted as passive.
    assert "uvm_test_top.env.mystery" in block["not_applicable"]


def test_not_available_and_not_applicable_stay_distinct(tmp_path):
    """"nobody looked" and "we looked and there are none" are opposite
    findings. A subsystem with no manifest at all reports NOT_AVAILABLE with
    the real producing command; one whose captured hierarchy simply has no
    such component reports NOT_APPLICABLE."""
    env = _subsystem_env(tmp_path, "subsys_a", HOST_SIDE_COMMANDS)
    bare = saa.analyze_subsystem_architecture(saa.SubsystemAnalysisInputs(
        subsystem_id="BARE", environment_root=str(tmp_path / "nowhere")))
    assert bare["fields"]["scoreboards"]["status"] == saa.NOT_AVAILABLE
    assert "env-manifest generate" in bare["fields"]["scoreboards"]["reason"]
    assert bare["fields"]["build_run_regression_waveform_fsdbreport_flows"]["status"] \
        == saa.NOT_AVAILABLE

    full = saa.analyze_subsystem_architecture(_inputs_for(env, "SUBSYS_B"))
    # HOST_SIDE_COMMANDS names no reset and no DMA, and the hierarchy IS
    # captured -- so these are NOT_APPLICABLE, not NOT_AVAILABLE.
    assert full["fields"]["dma"]["status"] == saa.NOT_APPLICABLE
    assert "none matched" in full["fields"]["dma"]["reason"]
    assert full["fields"]["virtual_interfaces"]["status"] == saa.NOT_AVAILABLE


def test_build_run_regression_waveform_flows_come_from_the_real_run_profile(tmp_path):
    env = _subsystem_env(tmp_path, "subsys_a", CPU_SIDE_COMMANDS)
    block = saa.analyze_subsystem_architecture(
        _inputs_for(env, "SUBSYS_A"))["fields"][
            "build_run_regression_waveform_fsdbreport_flows"]
    assert block["status"] == saa.DERIVED
    assert block["waveform_parameters"] == ["FSDB_REPORT", "WAVE"]
    assert block["regression_parameters"] == ["REGRESS_LIST"]
    assert block["targets"] == ["compile", "regress", "sim"]


def test_per_subsystem_analyses_run_independently_and_pass_the_isolation_check(tmp_path):
    a = _subsystem_env(tmp_path, "subsys_a", CPU_SIDE_COMMANDS)
    b = _subsystem_env(tmp_path, "subsys_b", CONTENDING_CPU_SIDE_COMMANDS)
    results = saa.run_per_subsystem_analyses(
        [_inputs_for(a, "SUBSYS_A"), _inputs_for(b, "SUBSYS_B")])
    assert [r["subsystem_id"] for r in results] == ["SUBSYS_A", "SUBSYS_B"]
    assert all(r["analysis_status"] == "COMPLETE" for r in results)
    # Each analysis read only its own tree -- the property the isolation check
    # asserts, restated here against the recorded reads.
    for result, own in zip(results, [a, b]):
        assert result["read_paths"]
        assert all(str(own) in p for p in result["read_paths"])


def test_cross_contamination_raises_rather_than_warns(tmp_path):
    a = _subsystem_env(tmp_path, "subsys_a", CPU_SIDE_COMMANDS)
    b = _subsystem_env(tmp_path, "subsys_b", HOST_SIDE_COMMANDS)
    contaminated = [
        {"subsystem_id": "SUBSYS_A", "environment_root": str(a),
         "read_paths": [str(a / "command.txt"), str(b / "command.txt")],
         "analysis_status": "COMPLETE"},
        {"subsystem_id": "SUBSYS_B", "environment_root": str(b),
         "read_paths": [str(b / "command.txt")], "analysis_status": "COMPLETE"},
    ]
    with pytest.raises(saa.CrossContaminationError) as excinfo:
        saa.assert_no_cross_contamination(contaminated)
    assert "SUBSYS_A read" in str(excinfo.value)
    # And the synthesis cannot be reached around it.
    with pytest.raises(saa.CrossContaminationError):
        saa.synthesize_subsystem_analyses(contaminated)


def test_synthesis_refuses_to_run_before_every_analysis_is_complete(tmp_path):
    a = _subsystem_env(tmp_path, "subsys_a", CPU_SIDE_COMMANDS)
    results = saa.run_per_subsystem_analyses([_inputs_for(a, "SUBSYS_A")])
    incomplete = [dict(results[0], analysis_status="IN_PROGRESS")]
    with pytest.raises(RuntimeError, match="not COMPLETE"):
        saa.synthesize_subsystem_analyses(incomplete)


def test_synthesis_surfaces_the_cross_subsystem_duplicate_active_driver(tmp_path):
    """SYS-5's "cross-subsystem synthesis happens afterward": the conflict is
    invisible to either subsystem's own analysis and appears only once both
    are combined."""
    a = _subsystem_env(tmp_path, "subsys_a", CPU_SIDE_COMMANDS)
    b = _subsystem_env(tmp_path, "subsys_b", CONTENDING_CPU_SIDE_COMMANDS)
    results = saa.run_per_subsystem_analyses(
        [_inputs_for(a, "SUBSYS_A"), _inputs_for(b, "SUBSYS_B")])
    synthesis = saa.synthesize_subsystem_analyses(results)
    assert synthesis["summary"]["duplicate_active_drivers"] >= 1
    conflicts = synthesis["contract_set"]["conflicts"]
    assert "BFM:DUT_SIDE" in {c.get("resource_id") for c in conflicts}
    assert synthesis["isolation"]["checked"] is True
    assert synthesis["artifacts_modified"] is False
    # A single subsystem's own analysis carries no conflict, by construction.
    solo = saa.synthesize_subsystem_analyses([results[0]])
    assert solo["contract_set"]["conflicts"] == []


def test_synthesis_feeds_each_subsystems_own_address_map_into_its_contracts(tmp_path):
    a = _subsystem_env(tmp_path, "subsys_a", CPU_SIDE_COMMANDS)
    results = saa.run_per_subsystem_analyses(
        [_inputs_for(a, "SUBSYS_A", region_clock_map={"CTRL_BLOCK": "core_clk"})])
    synthesis = saa.synthesize_subsystem_analyses(results)
    write = next(c for c in synthesis["contract_set"]["contracts"]
                 if c["command_name"] == "CPUWRITE4B")
    assert write["clock_domain"]["status"] == "RESOLVED"
    assert write["clock_domain"]["clock"] == "core_clk"
    assert write["clock_domain"]["address_regions"] == ["CTRL_BLOCK"]


def test_command_files_are_discovered_through_one_shared_definition(tmp_path):
    """discover_command_files() reuses subsystem_discovery's own command_txt
    globs, so the SYS-2 existence probe and the SYS-7 analyzer cannot disagree
    about whether a subsystem has a command.txt."""
    env = _subsystem_env(tmp_path, "subsys_a", CPU_SIDE_COMMANDS)
    found = saa.discover_command_files(env)
    assert [Path(p).name for p in found] == ["command.txt"]
    probe = sd.probe_environment_artifacts(env)
    assert probe["command_txt"]["status"] == sd.PRESENT
    assert saa.discover_command_files("") == []


def test_full_flow_from_discovery_through_selection_to_synthesis(tmp_path):
    a = _subsystem_env(tmp_path, "subsys_a", CPU_SIDE_COMMANDS)
    b = _subsystem_env(tmp_path, "subsys_b", CONTENDING_CPU_SIDE_COMMANDS)
    registry = tmp_path / ".dv-harness" / "soc-composer" / "subsystem_environment_registry.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps({"subsystems": [
        {"name": "SUBSYS_A",
         "environment_manifest": str(a / ".dv-harness" / "env.manifest.json"),
         "release_sha": "aaa111", "qualification_state": "REGRESSION_QUALIFIED",
         "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS"},
        {"name": "SUBSYS_B",
         "environment_manifest": str(b / ".dv-harness" / "env.manifest.json"),
         "release_sha": "bbb222", "qualification_state": "REGRESSION_QUALIFIED",
         "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS"},
    ]}), encoding="utf-8")
    sources = sd.candidate_sources_path(tmp_path)
    sources.parent.mkdir(parents=True, exist_ok=True)
    sources.write_text(json.dumps({"candidates": [
        {"name": "SUBSYS_A", "protocol": "SYNTH_A", "environment_path": str(a)},
        {"name": "SUBSYS_B", "protocol": "SYNTH_B", "environment_path": str(b)},
    ]}), encoding="utf-8")

    result = saa.analyze_selected_subsystems(tmp_path, ["SUBSYS_A", "SUBSYS_B"])
    assert result["selection"]["selected_subsystems"] == ["SUBSYS_A", "SUBSYS_B"]
    synthesis = result["synthesis"]
    assert synthesis["subsystems"] == ["SUBSYS_A", "SUBSYS_B"]
    assert synthesis["summary"]["duplicate_active_drivers"] >= 1

    report = saa.format_analysis_report(synthesis)
    assert "PER-SUBSYSTEM VERIFICATION ARCHITECTURE ANALYSIS (SYS-5..SYS-8)" in report
    assert "DUPLICATE_ACTIVE_DRIVER" in report
    assert "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED" in report
    for name in saa.SYS6_FIELDS:
        assert name in report


def test_selection_is_still_required_and_is_still_refused_when_absent(tmp_path):
    """SYS-1's refusal is not bypassed by the SYS-5 front door."""
    result = saa.analyze_selected_subsystems(tmp_path, [])
    assert result["selection"]["selection_admissible"] is False
    assert result["selection"]["refusal_reason"] == "NO_EXPLICIT_SELECTION"
    assert result["synthesis"]["per_subsystem"] == []


# ============================================================================
# The hard constraint: nothing here generates a System-Level artifact
# ============================================================================

def test_the_whole_flow_writes_nothing_into_the_analyzed_environments(tmp_path):
    a = _subsystem_env(tmp_path, "subsys_a", CPU_SIDE_COMMANDS)
    b = _subsystem_env(tmp_path, "subsys_b", CONTENDING_CPU_SIDE_COMMANDS)

    def snapshot():
        return {str(p.relative_to(tmp_path)): p.read_bytes()
                for p in sorted(tmp_path.rglob("*")) if p.is_file()}

    before = snapshot()
    results = saa.run_per_subsystem_analyses(
        [_inputs_for(a, "SUBSYS_A"), _inputs_for(b, "SUBSYS_B")])
    synthesis = saa.synthesize_subsystem_analyses(results)
    saa.format_analysis_report(synthesis)
    assert snapshot() == before, "SYS-5..8 is analysis only and must write nothing"


def test_no_system_level_uvm_source_or_system_command_txt_is_produced(tmp_path):
    """The report is text about what a System-Level composition WOULD need. It
    must not contain a System command.txt, a virtual sequencer or UVM source --
    that is SYS-40, gated on a separate explicit human approval."""
    a = _subsystem_env(tmp_path, "subsys_a", CPU_SIDE_COMMANDS)
    b = _subsystem_env(tmp_path, "subsys_b", CONTENDING_CPU_SIDE_COMMANDS)
    synthesis = saa.synthesize_subsystem_analyses(saa.run_per_subsystem_analyses(
        [_inputs_for(a, "SUBSYS_A"), _inputs_for(b, "SUBSYS_B")]))
    report = saa.format_analysis_report(synthesis)
    for forbidden in ("class ", "endclass", "`uvm_component_utils", "module ",
                      "endmodule", "uvm_sequence #"):
        assert forbidden not in report, forbidden
    assert not list(tmp_path.rglob("*_vseqr.sv"))
    assert not list(tmp_path.rglob("system_command.txt"))


def test_soc_composer_cross_subsystem_stubs_are_still_unimplemented():
    """These three stay NotImplementedError through this entire effort. Filling
    them with real protocol-behaviour content is SYS-40 territory."""
    from dv_harness.uvm_generator import soc_environment_composer as composer
    manifest = {"subsystems": [{"name": "SUBSYS_A"}, {"name": "SUBSYS_B"}]}
    for fn in (composer.cross_subsystem_scenarios, composer.end_to_end_scoreboard,
               composer.system_coverage):
        with pytest.raises(NotImplementedError):
            fn(manifest)


# ============================================================================
# The CLI front door, driven as a real subprocess
# ============================================================================

def _synthetic_project(tmp_path: Path):
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
    import subprocess
    import sys
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp_path),
         "subsystem-analysis", *extra],
        cwd=str(ROOT), capture_output=True, text=True)


def test_cli_reports_the_conflict_and_exits_nonzero(tmp_path):
    """SYS-12's "stop automatic integration of that resource" must not read as
    a clean run to a CI step, so a standing cross-subsystem conflict is a
    non-zero exit."""
    _synthetic_project(tmp_path)
    proc = _run_cli(tmp_path, "--select", "SUBSYS_A", "--select", "SUBSYS_B")
    assert proc.returncode == 2, proc.stderr
    assert "DUPLICATE_ACTIVE_DRIVER" in proc.stdout
    assert "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED" in proc.stdout


def test_cli_refuses_and_says_so_when_nothing_is_selected(tmp_path):
    """An empty analysis must read as "nothing was selected", never as "these
    subsystems are clean"."""
    _synthetic_project(tmp_path)
    proc = _run_cli(tmp_path)
    assert proc.returncode == 2, proc.stderr
    assert "NO_EXPLICIT_SELECTION" in proc.stdout
    assert "SUBSYS_A" in proc.stdout and "SUBSYS_B" in proc.stdout
    assert "DUPLICATE_ACTIVE_DRIVER" not in proc.stdout


def test_cli_exits_zero_on_a_clean_single_subsystem_selection(tmp_path):
    _synthetic_project(tmp_path)
    proc = _run_cli(tmp_path, "--select", "SUBSYS_A", "--json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["synthesis"]["summary"]["cross_subsystem_conflicts"] == 0
    assert {c["parallel_safe"] for c in payload["synthesis"]["contract_set"]["contracts"]} \
        == {scc.PARALLEL_SAFETY_UNKNOWN}
