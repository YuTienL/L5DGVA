"""Tests for SYOSCB-29 (REQUIRED ARCHITECTURE REPRESENTATION) and SYOSCB-30
(the twenty-nine-item REQUIRED PHASE-1 REPORT) -- `dv_harness/
syoscb_phase1_report.py`.

Three kinds of fixture, matching the ones `test_syoscb_topology_plan.py` uses:

  * NOTHING AT ALL. The empty-input case is a first-class test here, not an
    afterthought: a report assembler whose only tested path is "every artifact
    was supplied" is exactly the happy-path-only coverage this project has been
    burned by. Every branch and every section must say what is missing.
  * SYNTHETIC AMBA_PORT_REGISTRY rows, reusing `test_amba_route_transform_
    predictor.py`'s own `master()`/`slave()` helpers so a row here has exactly
    the columns a real one does.
  * The REAL parsed AMBA4 SoC fixture and the REAL upstream
    uvm_syoscb-1.0.2.4 tree at D:/DV/Scoreboard, read READ-ONLY, so the
    architecture tree's compare-class leaves are held against the source they
    claim to come from. Nothing is copied out of it.

The negative half of every assertion is the point: the tree must render
ARTIFACT_NOT_SUPPLIED rather than a fabricated branch, the adapter leaves must
not claim NOT_PRESENT_IN_FABRIC when there is no registry to say so, and the
SYOSCB-33 stop report must REFUSE to print COMPLETE over work nobody did.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from dv_harness import syoscb_phase1_report as spr
from dv_harness import syoscb_result_taxonomy as srt
from dv_harness import syoscb_source_audit as ssa
from dv_harness.amba_fabric_discovery import (
    assert_no_bind_statement,
    build_fabric_netlist,
    build_vip_bind_plan,
    trace_all_fabric_ports,
)
from dv_harness.amba_port_registry import build_amba_port_registry
from dv_harness.amba_route_transform_predictor import predict_routes
from dv_harness.amba_transaction_ir import (
    build_transaction_ir_templates,
    plan_amba_adapters,
)
from dv_harness.connectivity import AMBA4_DISPLAY_NAMES, REQUIRED_HUMAN_INPUT
from dv_harness.syoscb_phase1_report import (
    ADAPTER_NOT_PRESENT,
    BRANCH_NOT_BUILT,
    BRANCH_NOT_SUPPLIED,
    BRANCH_POPULATED,
    SYOSCB29_ADAPTER_ORDER,
    SYOSCB29_EVIDENCE_LEAVES,
    SYOSCB29_EVIDENCE_UNMAPPED,
    SYOSCB29_ROOT_LABEL,
    SYOSCB29_SPEC,
    SYOSCB30_SECTIONS,
    SYOSCB33_GATE_LINES,
    SYOSCB33_GATE_PRECONDITIONS,
    SyoscbPhase1ReportError,
    assert_architecture_tree_covers_spec,
    assert_report_section_order,
    build_architecture_tree,
    build_phase1_gate_checklist,
    build_scoreboard_test_plan,
    build_syoscb_phase1_report,
    collect_open_blockers,
    phase1_gate_blockers,
    render_architecture_tree,
    render_phase1_gate_report,
    render_syoscb_phase1_report,
    unpopulated_architecture_branches,
)
from dv_harness.syoscb_topology_plan import build_syoscb_configuration_plan
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

HARNESS_ROOT = Path(__file__).resolve().parents[1]
MODULE_SOURCE = Path(spr.__file__).read_text(encoding="utf-8")


@pytest.fixture
def two_axi_masters_one_ddr():
    """Two AXI4 masters into one AXI4 destination -- enough topology for a real
    registry, real predictions and a real SyoSil configuration plan."""
    return [master("CPU_AXI", "AXI4"),
            master("DMA_AXI", "AXI4", id_width="6"),
            slave("DDR_AXI", "AXI4", id_width="8")]


@pytest.fixture
def synthetic_plan(two_axi_masters_one_ddr):
    predictions = predict_routes(two_axi_masters_one_ddr, assume_full_connectivity=True)
    return build_syoscb_configuration_plan(two_axi_masters_one_ddr, predictions)


@pytest.fixture(scope="module")
def real_audit():
    if not REAL_SYOSCB_ROOT.is_dir():
        pytest.skip(f"no upstream source tree at {REAL_SYOSCB_ROOT}")
    return ssa.audit_syoscb_source(REAL_SYOSCB_ROOT)


# ===========================================================================
# SYOSCB-29: the architecture tree, with nothing supplied
# ===========================================================================

def test_the_tree_renders_every_mandated_branch_with_no_input_at_all():
    """SYOSCB-29's tree is mandatory. With no artifact supplied at all it must
    still carry every label the doc names -- an omitted branch is how a
    capability quietly stops being reviewed."""
    tree = render_architecture_tree(build_architecture_tree())
    assert tree.splitlines()[0] == SYOSCB29_ROOT_LABEL
    assert_architecture_tree_covers_spec(tree)          # would raise on a gap
    for label in ("AMBA SoC Fabric Verification", "Fabric Discovery",
                  "AMBA_PORT_REGISTRY", "VIP Bind Planning",
                  "AMBA Transaction Normalization", "AMBA Route / Transform Predictor",
                  "AMBA Scoreboard", "SyoSil UVM SCB", "Evidence"):
        assert label in tree


def test_an_unsupplied_branch_says_so_instead_of_looking_empty():
    representation = build_architecture_tree()
    tree = render_architecture_tree(representation)
    assert BRANCH_NOT_SUPPLIED in tree
    unpopulated = unpopulated_architecture_branches(representation)
    # Evidence is a fixed vocabulary and exists with no fabric; everything that
    # needs a discovered artifact must be reported as unpopulated.
    assert "Fabric Discovery" in unpopulated
    assert "VIP Bind Planning" in unpopulated
    assert "AMBA Route / Transform Predictor" in unpopulated
    assert "Evidence" not in unpopulated


def test_no_adapter_leaf_claims_the_fabric_lacks_a_protocol_with_no_registry():
    """`NOT_PRESENT_IN_FABRIC` is a claim ABOUT THE FABRIC. With no
    AMBA_PORT_REGISTRY there is no evidence for it, and asserting it anyway
    would be a fabricated negative."""
    tree = render_architecture_tree(build_architecture_tree())
    assert ADAPTER_NOT_PRESENT not in tree
    for protocol in SYOSCB29_ADAPTER_ORDER:
        assert f"{AMBA4_DISPLAY_NAMES[protocol]} Adapter = {BRANCH_NOT_SUPPLIED}" in tree


def test_the_generator_and_collector_are_reported_as_not_built(synthetic_plan):
    """No expected-transaction generator or actual-transaction collector is
    implemented anywhere in this repository, and Phase 1 may not implement
    one. The tree must say NOT_BUILT, not imply one exists."""
    tree = render_architecture_tree(build_architecture_tree(syoscb_plan=synthetic_plan))
    generator = tree.split("Expected Transaction Generator")[1]
    assert BRANCH_NOT_BUILT in generator.split("Actual Transaction Collector")[0]
    collector = tree.split("Actual Transaction Collector")[1]
    assert BRANCH_NOT_BUILT in collector.split("SyoSil UVM SCB")[0]


def test_the_compare_leaves_are_required_human_input_without_a_real_audit(
        synthetic_plan):
    tree = render_architecture_tree(build_architecture_tree(syoscb_plan=synthetic_plan))
    assert f"In-Order Compare = {BRANCH_NOT_SUPPLIED}" in tree
    assert f"Out-of-Order Compare = {BRANCH_NOT_SUPPLIED}" in tree


def test_assert_architecture_tree_covers_spec_catches_a_dropped_branch():
    """The assertion checks the FINISHED text, so a branch a projection
    accidentally dropped really does fail."""
    tree = render_architecture_tree(build_architecture_tree())
    mangled = tree.replace("Protocol Bridge Model", "(dropped)")
    with pytest.raises(SyoscbPhase1ReportError) as excinfo:
        assert_architecture_tree_covers_spec(mangled)
    assert "Protocol Bridge Model" in excinfo.value.detail["missing_labels"]


def test_the_spec_labels_are_the_documents_own_tree():
    """A cheap but real guard: the spec really names ten adapters, five
    predictor stages and the doc's own scoreboard/evidence leaves."""
    branches = dict(SYOSCB29_SPEC)
    assert len(branches["AMBA Transaction Normalization"]) == 10
    assert len(branches["AMBA Route / Transform Predictor"]) == 5
    assert len(branches["Evidence"]) == 6
    scoreboard = dict(branches["AMBA Scoreboard"])
    assert len(scoreboard["SyoSil UVM SCB"]) == 5


# ===========================================================================
# SYOSCB-29 vs. the SYOSCB-21 taxonomy
# ===========================================================================

def test_every_taxonomy_value_is_placed_under_a_leaf_or_explicitly_unmapped():
    placed = [v for _, values in SYOSCB29_EVIDENCE_LEAVES for v in values]
    placed += list(SYOSCB29_EVIDENCE_UNMAPPED)
    assert sorted(placed) == sorted(srt.SCOREBOARD_RESULT_VALUES)


def test_the_coarsening_is_visible_in_the_tree_not_only_in_a_comment():
    """SYOSCB-29's six Evidence names are coarser than the fourteen-value
    taxonomy. The three values no leaf names must be printed, not dropped."""
    tree = render_architecture_tree(build_architecture_tree())
    for value in SYOSCB29_EVIDENCE_UNMAPPED:
        assert value in tree
    assert "NOT_NAMED_BY_SYOSCB29" in tree


# ===========================================================================
# SYOSCB-30: the twenty-nine sections
# ===========================================================================

def test_the_report_has_all_twenty_nine_sections_with_no_input():
    report = build_syoscb_phase1_report()
    assert [n for n, _ in SYOSCB30_SECTIONS] == [n for n, _, _ in report.sections]
    assert len(report.sections) == 29
    text = render_syoscb_phase1_report(report)
    assert_report_section_order(text)                   # would raise on a gap
    assert "NOT SUPPLIED" in text


def test_every_unsupplied_section_names_the_function_that_would_fill_it():
    """"NOT SUPPLIED" without a remedy is a dead end. Each such section says
    which real function produces its input."""
    report = build_syoscb_phase1_report()
    for number in (2, 3, 4, 6, 10, 13, 14, 15, 16, 19, 20, 21, 22, 24, 25, 26):
        body = report.section(number)
        assert "NOT SUPPLIED" in body, number
        assert "`" in body and "(" in body, number


def test_assert_report_section_order_catches_a_missing_heading():
    text = render_syoscb_phase1_report(build_syoscb_phase1_report())
    mangled = text.replace("## 17. SYOSIL CAPABILITY MAPPING\n", "")
    with pytest.raises(SyoscbPhase1ReportError) as excinfo:
        assert_report_section_order(mangled)
    assert excinfo.value.reason == "SYOSCB30_SECTION_MISSING"
    assert excinfo.value.detail["number"] == 17


def test_assert_report_section_order_catches_an_out_of_order_heading():
    text = render_syoscb_phase1_report(build_syoscb_phase1_report())
    heading = "## 28. OPEN BLOCKERS"
    body = text.replace(heading + "\n", "")
    reordered = body.replace("## 1. CURRENT L5 AMBA CAPABILITY AUDIT\n",
                             heading + "\n\n## 1. CURRENT L5 AMBA CAPABILITY AUDIT\n")
    with pytest.raises(SyoscbPhase1ReportError) as excinfo:
        assert_report_section_order(reordered)
    assert excinfo.value.reason == "SYOSCB30_SECTIONS_OUT_OF_ORDER"


def test_section_one_reports_a_real_import_check_not_a_claim():
    """Item 1 must be checkable. Every module it lists is really imported."""
    body = build_syoscb_phase1_report().section(1)
    assert "dv_harness.syoscb_topology_plan" in body
    assert "IMPORTABLE" in body
    assert "NOT_IMPORTABLE" not in body


def test_section_four_really_runs_the_not_vendored_scan(real_audit):
    """Item 4 is a RESULT, not a promise: `assert_not_vendored()` is executed
    against this repository with the real audit's file hashes."""
    body = build_syoscb_phase1_report(repo_root=HARNESS_ROOT,
                                      audit=real_audit).section(4)
    assert "CLEAN" in body
    assert "VIOLATION" not in body


def test_section_five_refuses_to_invent_an_integration_path():
    body = build_syoscb_phase1_report().section(5)
    assert REQUIRED_HUMAN_INPUT in body
    assert "no file was copied" in body


def test_section_twenty_five_is_not_available_rather_than_never_built():
    """SYOSCB-25/26 need a real toolchain run. That is a Phase-2-only
    blocker, and the report must say so instead of implying nobody built it."""
    body = build_syoscb_phase1_report().section(25)
    assert "NOT_AVAILABLE" in body
    assert "Phase-2-only" in body or "Phase 1" in body


# ===========================================================================
# SYOSCB-33: the stop report refuses to over-claim
# ===========================================================================

def test_the_gate_report_refuses_to_render_over_incomplete_work():
    checklist = build_phase1_gate_checklist()
    assert phase1_gate_blockers(checklist) == [k for _, k in SYOSCB33_GATE_PRECONDITIONS]
    with pytest.raises(SyoscbPhase1ReportError) as excinfo:
        render_phase1_gate_report(checklist)
    assert excinfo.value.reason == "SYOSCB33_GATE_PRECONDITIONS_INCOMPLETE"
    assert excinfo.value.detail["incomplete"]


def test_section_twenty_nine_names_what_it_may_not_claim():
    """When the gate cannot be earned, section 29 must print the reason rather
    than the gate text -- and must not print a single COMPLETE line."""
    body = build_syoscb_phase1_report().section(29)
    assert "is NOT rendered" in body
    # A gate line may appear as the CLAIM IT WOULD MAKE inside the blocker
    # table, but the rendered stop report -- which is what "STOP." marks --
    # must be absent entirely, and so must its fenced block.
    assert "STOP." not in body
    assert "```" not in body
    # ...and each unmet precondition is named next to the line it would claim.
    for line, key in SYOSCB33_GATE_PRECONDITIONS:
        assert line in body
        assert key in body


def test_a_checklist_cannot_be_forged_by_a_caller():
    """`build_phase1_gate_checklist()` derives every value from a real
    artifact; there is no argument that sets one directly."""
    checklist = build_phase1_gate_checklist(registry=[{"port_id": "X"}])
    assert checklist["amba_port_registry_complete"] is True
    assert checklist["route_predictor_plan_complete"] is False
    assert "amba_port_registry_complete" not in phase1_gate_blockers(checklist)


def test_the_gate_lines_are_the_documents_own_eleven():
    assert len(SYOSCB33_GATE_LINES) == 11
    assert SYOSCB33_GATE_LINES[-2:] == ("IMPLEMENTATION NOT STARTED",
                                        "AWAITING USER APPROVAL")
    assert len(SYOSCB33_GATE_PRECONDITIONS) == 9


# ===========================================================================
# SYOSCB-30 items 24 and 28
# ===========================================================================

def test_the_test_plan_is_derived_per_real_scoreboard_group(synthetic_plan):
    plans = build_scoreboard_test_plan(synthetic_plan)
    groups = {g["scoreboard_id"] for g in synthetic_plan["scoreboards"]}
    assert groups
    assert {p["scoreboard_id"] for p in plans} == groups
    assert len(plans) == len(groups) * len(spr.SCOREBOARD_TEST_INTENTS)
    for entry in plans:
        assert entry["implementation_status"] == "PHASE_2_ONLY_NO_SV_EMITTED_HERE"
        assert entry["expected_results"]
        for result in entry["expected_results"]:
            assert result in srt.SCOREBOARD_RESULT_VALUES


def test_a_scoreboard_blocked_on_producer_attribution_blocks_its_tests():
    """Two APB4 masters into one APB4 slave: APB carries no transaction id, so
    an item observed at the destination cannot say which master sent it. A
    stress test over that scoreboard would report noise, not a failure."""
    rows = [master("HOST_APB", "APB4", data_width="32", id_width="UNKNOWN"),
            master("DEBUG_APB", "APB4", data_width="32", id_width="UNKNOWN"),
            slave("CFG_APB", "APB4", data_width="32", id_width="UNKNOWN")]
    predictions = predict_routes(rows, assume_full_connectivity=True)
    plan = build_syoscb_configuration_plan(rows, predictions)
    assert plan["scoreboards_blocked_on_producer_attribution"]
    plans = build_scoreboard_test_plan(plan)
    assert plans
    assert all(p["status"] == REQUIRED_HUMAN_INPUT for p in plans)
    assert all(p["blocked_reason"] for p in plans)


def test_the_test_plan_is_empty_rather_than_invented_without_a_plan():
    assert build_scoreboard_test_plan(None) == []
    body = build_syoscb_phase1_report().section(24)
    assert "NOT SUPPLIED" in body


def test_open_blockers_come_from_each_owning_modules_own_function(synthetic_plan):
    """Item 28 aggregates; it never re-derives. Every row names the module
    that raised it."""
    rows = collect_open_blockers(syoscb_plan=synthetic_plan)
    assert rows
    assert {r["source"] for r in rows} <= {
        "SYOSCB-1 source audit", "SYOSCB-9 IR", "SYOSCB-10 adapter plan",
        "SYOSCB-12 predictor", "SYOSCB-14/16 plan", "SYOSCB-17 compare strategy",
        "SYOSCB-18 match key", "SYOSCB-22 counters", "SYOSCB-3 registration"}
    assert any(r["source"] == "SYOSCB-14/16 plan" for r in rows)


def test_an_unsearched_adapter_plan_is_an_open_blocker_not_an_add_verdict(
        two_axi_masters_one_ddr):
    """SYOSCB-9 requires searching existing adapters first. `None` means nobody
    looked, which must reach item 28 -- not be rounded up to ADD."""
    unsearched = plan_amba_adapters(two_axi_masters_one_ddr, None)
    rows = collect_open_blockers(adapter_plans=unsearched)
    assert [r for r in rows if r["source"] == "SYOSCB-10 adapter plan"]
    checklist = build_phase1_gate_checklist(adapter_plans=unsearched)
    assert checklist["amba_adapter_plan_complete"] is False

    searched = plan_amba_adapters(two_axi_masters_one_ddr, [])
    assert not [r for r in collect_open_blockers(adapter_plans=searched)
                if r["source"] == "SYOSCB-10 adapter plan"]
    assert build_phase1_gate_checklist(
        adapter_plans=searched)["amba_adapter_plan_complete"] is True


# ===========================================================================
# The real upstream source, read-only
# ===========================================================================

@real_source
def test_the_compare_leaves_carry_real_upstream_class_names(real_audit,
                                                            synthetic_plan):
    """SYOSCB-29's three compare leaves are annotated from the REAL library on
    disk. Inventing a class name for a library that can be read is the exact
    fabrication this pass exists to avoid."""
    tree = render_architecture_tree(
        build_architecture_tree(syoscb_plan=synthetic_plan, audit=real_audit))
    for expected in ("cl_syoscb_compare_io", "cl_syoscb_compare_iop",
                     "cl_syoscb_compare_ooo"):
        assert expected in tree
    assert ".svh:" in tree                       # a real file:line citation


@real_source
def test_the_limitation_analysis_checks_protocol_agnosticism_rather_than_asserting_it(
        real_audit):
    body = build_syoscb_phase1_report(audit=real_audit).section(18)
    assert "no AMBA protocol awareness" in body
    assert "audited class" in body


@real_source
def test_the_capability_mapping_cites_real_classes(real_audit):
    body = build_syoscb_phase1_report(audit=real_audit).section(17)
    assert "cl_syoscb" in body
    assert ".svh:" in body


@real_source
def test_nothing_from_the_upstream_tree_is_copied_into_this_module():
    """The module may cite the upstream source; it may not carry a body from
    it. Checked the same way `syoscb_topology_plan`'s test checks it."""
    assert "class cl_syoscb" not in MODULE_SOURCE
    assert "endclass" not in MODULE_SOURCE
    assert "`include" not in MODULE_SOURCE


# ===========================================================================
# The real parsed AMBA4 SoC, end to end
# ===========================================================================

@pytest.fixture(scope="module")
def real_artifacts(tmp_path_factory):
    if shutil.which(VERIBLE_BIN) is None:
        pytest.skip("verible-verilog-syntax not on PATH")
    sv = write_fixture(tmp_path_factory.mktemp("syoscb_phase1_report_rtl"))
    netlist = build_fabric_netlist([parse_file(sv)], "soc_top")
    traces = trace_all_fabric_ports(netlist, FABRIC)
    plan = build_vip_bind_plan(netlist, traces)
    registry = build_amba_port_registry(netlist, traces, plan)
    predictions = predict_routes(registry, assume_full_connectivity=True)
    return {
        "netlist": netlist, "traces": traces, "plan": plan, "registry": registry,
        "predictions": predictions,
        "syoscb_plan": build_syoscb_configuration_plan(registry, predictions),
        "ir_templates": build_transaction_ir_templates(registry),
        "adapter_plans": plan_amba_adapters(registry, []),
    }


@requires_verible
def test_the_whole_chain_produces_a_complete_report(real_artifacts):
    """Real RTL -> real trace -> real AMBA_PORT_REGISTRY -> real predictions ->
    real plan -> the twenty-nine sections and SYOSCB-29's tree, with nothing
    synthetic in between."""
    report = build_syoscb_phase1_report(**real_artifacts)
    text = render_syoscb_phase1_report(report)
    assert_report_section_order(text)
    assert_no_bind_statement(text)
    ssa.assert_no_emittable_sv(text, label="real fixture Phase-1 report")
    assert len(report.sections) == 29
    tree = render_architecture_tree(report.architecture)
    assert "AXI4 Adapter = " in tree
    assert BRANCH_NOT_SUPPLIED not in tree.split("AMBA Transaction Normalization")[1] \
        .split("AMBA Route / Transform Predictor")[0]
    populated = [label for label, _ in report.architecture.entries
                 if report.architecture.branch_status[label]["status"]
                 == BRANCH_POPULATED]
    assert "Fabric Discovery" in populated
    assert "AMBA Route / Transform Predictor" in populated


@requires_verible
def test_an_adapter_leaf_for_an_absent_protocol_says_not_present(real_artifacts):
    """SYOSCB-8: no adapter is planned for a protocol the fabric does not
    carry. The tree names all ten adapters as a VOCABULARY and marks the
    absent ones."""
    tree = render_architecture_tree(
        build_architecture_tree(registry=real_artifacts["registry"],
                                adapter_plans=real_artifacts["adapter_plans"]))
    assert ADAPTER_NOT_PRESENT in tree
    planned = {p["protocol"] for p in real_artifacts["adapter_plans"]}
    for protocol in SYOSCB29_ADAPTER_ORDER:
        label = f"{AMBA4_DISPLAY_NAMES[protocol]} Adapter"
        if protocol in planned:
            assert f"{label} = {ADAPTER_NOT_PRESENT}" not in tree
        else:
            assert f"{label} = {ADAPTER_NOT_PRESENT}" in tree


#: `build_phase1_gate_checklist()` takes only the artifacts a gate line rests
#: on -- the IR templates are section 19's input, not a gate precondition.
GATE_ARTIFACT_KEYS = ("netlist", "traces", "plan", "registry", "predictions",
                      "syoscb_plan", "adapter_plans")


@requires_verible
@real_source
def test_the_gate_is_earnable_only_with_every_artifact(real_artifacts, real_audit):
    payload = ssa.build_component_registration_payload(real_audit)
    gate_inputs = {k: real_artifacts[k] for k in GATE_ARTIFACT_KEYS}
    checklist = build_phase1_gate_checklist(
        audit=real_audit, registration_payload=payload, **gate_inputs)
    assert phase1_gate_blockers(checklist) == []
    gate = render_phase1_gate_report(checklist)
    assert gate.splitlines()[:11] == list(SYOSCB33_GATE_LINES)
    assert gate.endswith("STOP.")

    # ...and drop ONE artifact: the gate must refuse again.
    without_audit = build_phase1_gate_checklist(
        registration_payload=payload, **gate_inputs)
    assert phase1_gate_blockers(without_audit) == ["syosil_source_audit_complete"]
    with pytest.raises(SyoscbPhase1ReportError):
        render_phase1_gate_report(without_audit)


@requires_verible
@real_source
def test_a_complete_gate_still_reports_its_open_items(real_artifacts, real_audit):
    """Nine COMPLETE lines must never read as "nothing is open"."""
    payload = ssa.build_component_registration_payload(real_audit)
    report = build_syoscb_phase1_report(
        audit=real_audit, registration_payload=payload, **real_artifacts)
    body = report.section(29)
    assert "STOP." in body
    assert f"{len(report.open_blockers)} open item(s)" in body
    assert report.open_blockers, "a real fabric always leaves something open"
