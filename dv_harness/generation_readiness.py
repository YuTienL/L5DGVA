"""dv_harness/generation_readiness.py -- section 211's GENERATION READINESS
MATRIX as a real, auto-generated artifact.

THE GAP THIS CLOSES
-------------------
Section 211 prints a twenty-row table with the columns

    Capability | Status | Existing Reuse | Evidence | Gap | Priority | Action

and prints EVERY cell of it empty. A 2026-09-06 completeness audit re-verified
the gap with a negative grep: `grep -rni "generation.readiness"` and
`grep -rn "GF-AT-"` matched only this specification's own text and
`golden_flow_readiness.py`'s docstring reference to its OWN, DIFFERENT section-47
matrix. Nothing in this repo had ever rendered section 211's table, so the only
way to answer "can this factory generate a subsystem environment from a spec, and
a system environment from subsystems?" was for an auditing session to assemble
the answer by hand -- which means two audits of the same project could disagree
about the same facts.

WHY THIS IS A SEPARATE MODULE FROM golden_flow_readiness.py
-----------------------------------------------------------
Stated first, because "build a second readiness matrix" is exactly the kind of
parallel mechanism this project's Methodology Consolidation Rule forbids, and
the split is deliberate rather than accidental:

  * `golden_flow_readiness.py` answers section 47's question -- "did the twenty
    GOLDEN FLOW STAGES of this project's run connect end-to-end with evidence".
    Its rows are `models.Stage` values and its facts are stage RUN STATE
    (state.json, gate counts, LSF jobs, coverage summaries, signoff records).
  * This module answers section 211's question -- "does this FACTORY have the
    generation capability each rung of Flow A (spec -> subsystem UVM) and Flow B
    (subsystem UVM -> system-level UVM) needs, and what do this project's real
    GENERATION ARTIFACTS say about it". Its rows are capabilities, its columns
    include `Existing Reuse` and `Priority` (which section 47's table does not
    have), and it reads generation artifacts -- env.manifest.json's own layers,
    the protocol capability registry, the subsystem environment registry, and
    the real SYS-1..40 cross-subsystem analysis -- never stage status.

The two tables therefore never read the same source, and neither is derivable
from the other. What IS shared is reused rather than re-minted: the
READY/PARTIAL/BLOCKED/UNKNOWN status vocabulary (`subsystem_discovery`'s own),
the PRESENT/ABSENT/BLOCKED/UNKNOWN capability vocabulary (`subsystem_discovery.
FACTOR_STATUSES`), the `inference.next_best_action()` Gap -> Action engine, and
`connectivity.render_markdown_table()`.

EVERY ROW ANSWERS TWO QUESTIONS, NOT ONE
-----------------------------------------
Section 211's `Status` column has to mean something for a harness that owns no
multi-subsystem project of its own, so each row is probed on two axes and the
row's Status is the WORSE of the two:

  * CAPABILITY -- does the generation mechanism this row NAMES exist and import
    in this harness? Decided by resolving the row's own declared `fact_source`
    dotted paths through the import system (`assert_fact_sources_resolvable()`
    proves the same set at test time), plus, for the three rows whose mechanism
    deliberately raises `NotImplementedError`, by ASKING it through the already
    -real `system_scheduling_plan.probe_composer_boundary()`.
  * PROJECT EVIDENCE -- what did the row's real reader return over THIS project
    root? env.manifest.json's own per-layer `status`/`reason`,
    `protocol_capability.capability_rows()`, the real subsystem environment
    registry, `system_resource_inventory.real_cross_subsystem_findings()`, and
    `system_topology_analysis.analyze_system_topology()`.

A capability that exists but has no project input is UNKNOWN, never READY. A
capability that genuinely does not exist is BLOCKED with the mechanism's own
reason text, never a quiet UNKNOWN. Nothing is fabricated for a row whose
backing mechanism has not landed: an unresolvable `fact_source` makes that row
BLOCKED and names the missing dotted path.

WHAT THIS MODULE IS NOT
-----------------------
  * It DERIVES NOTHING an existing reader already supplies. Re-deriving "are
    there two ACTIVE drivers on one SoC port" locally would make this module a
    second, silently-diverging opinion about a fact
    `system_resource_inventory` already owns and two real SYSTEM_LEVEL gates
    already act on.
  * It WRITES NO GOVERNANCE STATE and RUNS NOTHING. No stage is executed, no
    gate script invoked, no build/regression/LSF job submitted, no state,
    control or approval file written. env.manifest.json is read through
    `env_manifest.load_env_manifest()` and the registry through
    `environment_mode_router.read_registered_subsystem_entries()`, both of which
    return absence rather than creating anything. (Disclosed precisely: the
    `dv-harness generation-readiness` WRAPPER still constructs a `DVHarness` and
    appends the usual `CLI_ACCESS` audit event, exactly as `status` and
    `golden-flow-readiness` do -- that is the CLI's universal behaviour, not
    this report's. Call this module directly, or `python -m
    dv_harness.generation_readiness`, for the untouched-tree guarantee.)
  * It APPROVES NOTHING and ARBITRATES NOTHING. A DRIVER_CONFLICT row renders
    BLOCKED and carries SYS-12's `preferred_model` through as text for a HUMAN
    to arbitrate; this module never picks a winner between two conflicting
    drivers. It does not cross SYS-39/SYS-40's stop-before-generating-real-
    system-artifacts boundary -- the three rows that sit on that boundary report
    it as the boundary, which is why they are BLOCKED rather than filled in.

WHERE THE Priority COLUMN COMES FROM
-------------------------------------
Section 213 (GENERATION PRIORITIES) is the specification's own P0/P1/P2 list and
names the same capabilities section 211's rows do. Each row's `priority` is that
document's assignment and each row's `priority_basis` quotes the line it came
from, so the column is transcribed rather than judged. Where section 213's
wording covers a row only partly (row 6's "CSR/IRQ automation" half is P1 while
its "Scenario" half is P0), the basis says so instead of the table quietly
picking one.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from . import subsystem_discovery as sd

SCHEMA_VERSION = "1.0"

#: READY / PARTIAL / BLOCKED / UNKNOWN -- section SYS-4's own four words,
#: reused rather than redeclared (the same reuse `system_readiness.py` and
#: `golden_flow_readiness.py` already make).
READY = sd.READY
PARTIAL = sd.PARTIAL
BLOCKED = sd.BLOCKED
UNKNOWN = sd.UNKNOWN
GENERATION_READINESS_CLASSES: tuple = sd.READINESS_CLASSES

#: PRESENT / ABSENT / BLOCKED / UNKNOWN -- `subsystem_discovery.FACTOR_STATUSES`,
#: this repo's existing four words for "is this artifact really there". The
#: capability axis is a DIFFERENT question from the readiness axis, so it gets
#: the vocabulary that already means what it needs to mean rather than a fifth
#: set of words.
CAP_PRESENT = sd.PRESENT
CAP_ABSENT = sd.ABSENT
CAP_BLOCKED = sd.BLOCKED
CAP_UNKNOWN = sd.UNKNOWN
CAPABILITY_CLASSES: tuple = sd.FACTOR_STATUSES

#: Worst-wins ordering. BLOCKED is worse than UNKNOWN on purpose: "we know this
#: cannot be generated" must not be averaged away by "we do not know about that".
_SEVERITY = {READY: 0, UNKNOWN: 1, PARTIAL: 2, BLOCKED: 3}

#: Capability -> the readiness class it can contribute at best.
_CAPABILITY_TO_READINESS: Dict[str, str] = {
    CAP_PRESENT: READY,
    CAP_ABSENT: BLOCKED,
    CAP_BLOCKED: BLOCKED,
    CAP_UNKNOWN: UNKNOWN,
}

#: Section 211's exact column set, in the document's order. Rendered through
#: `connectivity.render_markdown_table()`, this repo's only parameterized table
#: renderer -- a second hand-rolled join loop is how a column list drifts out of
#: agreement with the spec it came from.
GENERATION_MATRIX_COLUMNS: tuple = (
    ("row", "Capability"),
    ("status", "Status"),
    ("existing_reuse", "Existing Reuse"),
    ("evidence", "Evidence"),
    ("gap", "Gap"),
    ("priority", "Priority"),
    ("action", "Action"),
)

#: Rendered in any cell whose real source supplied nothing. Never an empty
#: string: "this fact is absent" and "this column was never filled in" must not
#: look alike to a reviewer.
NONE_CELL = "-"

#: Section 213's own priority buckets, split by the two flows it splits them by.
P0_SPEC_TO_SUBSYSTEM = "P0_SPEC_TO_SUBSYSTEM"
P0_SUBSYSTEM_TO_SYSTEM = "P0_SUBSYSTEM_TO_SYSTEM"
P1 = "P1"
P2 = "P2"
PRIORITIES: tuple = (P0_SPEC_TO_SUBSYSTEM, P0_SUBSYSTEM_TO_SYSTEM, P1, P2)

#: Section 211's two halves, which are Flow A and Flow B of the whole document.
FLOW_A = "FLOW_A_SPEC_TO_SUBSYSTEM"
FLOW_B = "FLOW_B_SUBSYSTEM_TO_SYSTEM"
FLOWS: tuple = (FLOW_A, FLOW_B)

#: How long the REAL Track-B cross-subsystem chain is allowed to run inside a
#: readiness report. `system_resource_inventory` already owns this budget
#: concept and its own default for gate scripts; a report is not on a gate's
#: clock but must still not hang, so it gets its own, larger ceiling.
DEEP_ANALYSIS_BUDGET_SECONDS = 60.0


class GenerationReadinessError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


def worst_readiness(values) -> str:
    """STRICT worst-wins over readiness classes -- no mixing rule.

    Used to fold a row's two axes (capability, project evidence) into one
    Status. A present capability must never LIFT a row whose project evidence
    is absent: "the mechanism exists but nothing here uses it yet" is UNKNOWN,
    not PARTIAL. `combine_readiness()` below is the different, softer fold used
    to summarise MANY rows, where READY-plus-UNKNOWN really does mean partial
    progress.
    """
    vals = [v for v in (values or ()) if v]
    if not vals:
        return UNKNOWN
    for v in vals:
        if v not in _SEVERITY:
            raise GenerationReadinessError("UNKNOWN_READINESS_CLASS", {
                "value": v, "legal_values": list(GENERATION_READINESS_CLASSES)})
    return max(vals, key=lambda v: _SEVERITY[v])


def combine_readiness(values) -> str:
    """Worst-wins over a set of readiness classes, with two deliberate rules:

      * an empty input is UNKNOWN (nothing was measured), never READY;
      * a mix of READY and UNKNOWN is PARTIAL, not UNKNOWN -- half a row being
        real is exactly what PARTIAL means, and calling it UNKNOWN would hide
        real capability.
    """
    vals = [v for v in (values or ()) if v]
    if not vals:
        return UNKNOWN
    for v in vals:
        if v not in _SEVERITY:
            raise GenerationReadinessError("UNKNOWN_READINESS_CLASS", {
                "value": v, "legal_values": list(GENERATION_READINESS_CLASSES)})
    if all(v == READY for v in vals):
        return READY
    if any(v == BLOCKED for v in vals):
        return BLOCKED
    if all(v == UNKNOWN for v in vals):
        return UNKNOWN
    return PARTIAL


# ===========================================================================
# Row declarations -- section 211's twenty rows, in the document's order
# ===========================================================================

@dataclass(frozen=True)
class GenerationRowSpec:
    """One declared row of section 211's matrix.

    `label` is the document's own wording, character for character -- the
    import-time check below is what stops a later edit from quietly renaming a
    row the specification names. `fact_source` names the already-real readers
    the probe calls, so `assert_fact_sources_resolvable()` can prove every row
    is backed by code that still exists, and the capability axis can be decided
    from the same declaration rather than from a second, hand-kept list.
    """
    row_id: str
    label: str
    flow: str
    priority: str
    priority_basis: str
    existing_reuse: str
    fact_source: Tuple[str, ...]
    basis: str
    #: Extra dotted paths that must ALSO resolve for the capability to be
    #: PRESENT but which the probe does not itself call (a generator entry
    #: point, say). Kept separate from `fact_source` so the "every cell comes
    #: from a named reader" claim stays exactly true.
    capability_extra: Tuple[str, ...] = field(default=())


ROWS: Tuple[GenerationRowSpec, ...] = (
    # ---------------- Flow A: spec -> subsystem UVM ----------------
    GenerationRowSpec(
        "spec_parsing_requirement_ir", "Spec Parsing / Requirement IR",
        FLOW_A, P0_SPEC_TO_SUBSYSTEM, "section 213 P0 SPEC->SUBSYSTEM: 'Spec Intelligence'",
        "requirement_contract.analyze_requirement_contract_set() + doc_extraction.DocumentIndex",
        ("dv_harness.requirement_contract.analyze_requirement_contract_set",
         "dv_harness.requirement_contract.derive_status",
         "dv_harness.doc_extraction.DocumentIndex"),
        "The Requirement IR in this harness is requirement_contract's validated contract "
        "record set (AMBIGUOUS/CONTRADICTORY/RESOLVED per requirement), sourced from real "
        "documents through doc_extraction. There is no canonical persisted path for a "
        "project's contract set, so the project-evidence axis is honestly UNKNOWN until "
        "one is supplied -- never inferred from a stage status."),
    GenerationRowSpec(
        "dut_discovery", "DUT Discovery",
        FLOW_A, P0_SPEC_TO_SUBSYSTEM, "section 213 P0 SPEC->SUBSYSTEM: 'DUT Discovery'",
        "env_manifest.build_dut_facts_rtl() (real verible parse) + "
        "connectivity.capture_dut_instance_tree()",
        ("dv_harness.env_manifest.default_manifest_path",
         "dv_harness.env_manifest.load_env_manifest",
         "dv_harness.env_manifest.build_dut_facts_rtl",
         "dv_harness.connectivity.capture_dut_instance_tree"),
        "env.manifest.json's own dut_facts.rtl layer, which reports NOT_AVAILABLE with a "
        "real reason when no RTL was supplied to the generating run. Read, never "
        "re-parsed: re-running verible here would be a second opinion about the same "
        "files."),
    GenerationRowSpec(
        "protocol_vip_mapping", "Protocol / VIP Mapping",
        FLOW_A, P0_SPEC_TO_SUBSYSTEM,
        "section 213 P0 SPEC->SUBSYSTEM: 'Protocol/VIP + API Retrieval'",
        "protocol_capability.capability_rows() + protocol_router.resolve_protocol()",
        ("dv_harness.protocol_capability.capability_rows",
         "dv_harness.protocol_capability.STATUS_GENERIC_SKELETON_ONLY",
         "dv_harness.protocol_router.resolve_protocol"),
        "The real per-protocol capability rows, whose capability_status is DERIVED from "
        "whether the generator module actually imports -- so a protocol reporting "
        "GENERIC_SKELETON_ONLY has no protocol-specific model, whatever a registry file "
        "claims."),
    GenerationRowSpec(
        "vip_api_retrieval", "VIP API Retrieval",
        FLOW_A, P0_SPEC_TO_SUBSYSTEM,
        "section 213 P0 SPEC->SUBSYSTEM: 'Protocol/VIP + API Retrieval'",
        "vip_api_card.validate_vip_api_usage() over vip_symbol_index + "
        "env_manifest's vip_config layer",
        ("dv_harness.vip_api_card.validate_vip_api_usage",
         "dv_harness.vip_api_card.PROVEN",
         "dv_harness.env_manifest.load_env_manifest"),
        "GF-AT-05 ('unknown VIP API is not hallucinated') is vip_api_card's PROVEN/BLOCKED/"
        "UNPROVABLE verdict; the project-evidence axis is env.manifest.json's vip_config "
        "layer, i.e. whether a real $DESIGNWARE_HOME release and real user-guide refs were "
        "captured at all."),
    GenerationRowSpec(
        "uvm_architecture", "UVM Architecture",
        FLOW_A, P0_SPEC_TO_SUBSYSTEM,
        "section 213 P0 SPEC->SUBSYSTEM: 'Verification Architecture'",
        "uvm_generator.create_environment() + uvm_structural_lint.lint_uvm_environment()",
        ("dv_harness.uvm_generator.create_environment.create_environment",
         "dv_harness.uvm_structural_lint.lint_uvm_environment",
         "dv_harness.verible_parser.get_verible_version",
         "dv_harness.env_manifest.load_env_manifest"),
        "GF-AT-06 ('architecture precedes large code generation'). Capability is the real "
        "generation entry point plus a WORKING verible -- uvm_structural_lint reports "
        "NOT_AVAILABLE, never PASS, when verible cannot run, so a missing parser is a real "
        "reduction in what this factory can check. Project evidence is env.manifest.json's "
        "env_topology.component_hierarchy, the captured real UVM component tree."),
    GenerationRowSpec(
        "scenario_negative_csr_irq", "Scenario / Negative / CSR / IRQ",
        FLOW_A, P0_SPEC_TO_SUBSYSTEM,
        "section 213 P0 SPEC->SUBSYSTEM: 'Scenario'. The CSR/IRQ AUTOMATION half of this "
        "row is section 213 P1 ('CSR/IRQ automation'); the row is filed at its P0 half.",
        "sys_regmap.mode_determining_bits() + init_seq.directed_test_steps() + "
        "env_manifest.build_dut_facts_registers()",
        ("dv_harness.sys_regmap.mode_determining_bits",
         "dv_harness.init_seq.directed_test_steps",
         "dv_harness.env_manifest.load_env_manifest"),
        "GF-AT-09 ('register semantics are not guessed'): the CSR half stands on a real "
        "register map, which env.manifest.json's dut_facts.registers layer reports as "
        "LOADED or NOT_AVAILABLE with a reason."),
    GenerationRowSpec(
        "checker_coverage_assertions", "Checker / Coverage / Assertions",
        FLOW_A, P0_SPEC_TO_SUBSYSTEM, "section 213 P0 SPEC->SUBSYSTEM: 'Checker/Coverage'",
        "coverage_analysis.identify_holes() + uvm_generator.state_machine_checks + "
        "env_manifest's testplan_correspondence",
        ("dv_harness.coverage_analysis.identify_holes",
         "dv_harness.uvm_generator.state_machine_checks",
         "dv_harness.env_manifest.build_testplan_correspondence",
         "dv_harness.env_manifest.load_env_manifest"),
        "GF-AT-11 ('coverage maps to requirement/objective') is env.manifest.json's real "
        "testlist/vPlan/coverage-model three-way join. Reported here as the COVERAGE-MODEL "
        "side of generation capability; the vPlan traceability VERDICT is section 47's own "
        "row in golden_flow_readiness.py and is deliberately not re-decided here."),
    GenerationRowSpec(
        "config_build_compile_fix", "Config / Build / Compile-Fix",
        FLOW_A, P0_SPEC_TO_SUBSYSTEM,
        "section 213 P0 SPEC->SUBSYSTEM: 'Config' and 'Compile-Fix'",
        "uvm_generator.run_profile + makefile_to_run_profile + config_variant_coverage",
        ("dv_harness.uvm_generator.run_profile",
         "dv_harness.uvm_generator.makefile_to_run_profile",
         "dv_harness.config_variant_coverage.generate_covering_array",
         "dv_harness.env_manifest.load_env_manifest"),
        "GF-AT-12 ('compile-fix cannot retry forever'). Project evidence is "
        "env.manifest.json's env_topology.config_db_trace -- a real captured "
        "UVM_INFO config_db trace is what proves the built configuration was observed "
        "rather than assumed."),
    GenerationRowSpec(
        "single_test_proof", "Single-Test Proof",
        FLOW_A, P0_SPEC_TO_SUBSYSTEM, "section 213 P0 SPEC->SUBSYSTEM: 'Single-Test Proof'",
        "qualification.CANONICAL_LADDER + the real subsystem environment registry",
        ("dv_harness.qualification.tier_index",
         "dv_harness.qualification.map_to_system_level_state",
         "dv_harness.environment_mode_router.read_registered_subsystem_entries"),
        "GF-AT-13 ('subsystem READY requires deterministic proof'). The registry is "
        "written only by engine.py's _persist_subsystem_registry_entry() on a "
        "gate-validated SIGNOFF PASS, so a registered qualification_state at or above "
        "SMOKE_QUALIFIED is harness evidence rather than a claim."),

    # ---------------- Flow B: subsystem UVM -> system-level UVM ----------------
    GenerationRowSpec(
        "subsystem_inventory_decomposition", "Subsystem Inventory / Decomposition",
        FLOW_B, P0_SUBSYSTEM_TO_SYSTEM,
        "section 213 P0 SUBSYSTEM->SYSTEM: 'Inventory/Decomposition'",
        "subsystem_discovery.discover_subsystem_candidates() + "
        "environment_mode_router.read_registered_subsystem_entries()",
        ("dv_harness.subsystem_discovery.discover_subsystem_candidates",
         "dv_harness.subsystem_discovery.require_explicit_selection",
         "dv_harness.environment_mode_router.read_registered_subsystem_entries"),
        "SYS-1..SYS-4. Composition needs at least two registered subsystems; one or zero "
        "is reported as exactly that, never as a failure of the mechanism."),
    GenerationRowSpec(
        "shared_resource_vip_resolver", "Shared Resource / VIP Resolver",
        FLOW_B, P0_SUBSYSTEM_TO_SYSTEM,
        "section 213 P0 SUBSYSTEM->SYSTEM: 'Shared Resource/VIP Resolver'",
        "system_resource_inventory.real_cross_subsystem_findings() (SYS-9..SYS-14)",
        ("dv_harness.system_resource_inventory.real_cross_subsystem_findings",
         "dv_harness.system_resource_inventory.analyze_selected_subsystem_resources",
         "dv_harness.system_resource_inventory.evaluate_shared_vip_promotion"),
        "GF-AT-15 ('active VIP/resources inventoried'). The same front door the two real "
        "SYSTEM_LEVEL gate scripts and the SoC composer cross-check against, so this row "
        "and those verdicts can never disagree."),
    GenerationRowSpec(
        "active_driver_ownership", "Active Driver Ownership",
        FLOW_B, P0_SUBSYSTEM_TO_SYSTEM,
        "section 213 P0 SUBSYSTEM->SYSTEM: 'Active Driver Ownership'",
        "system_resource_inventory.apply_active_driver_conflict_rule() (SYS-12)",
        ("dv_harness.system_resource_inventory.apply_active_driver_conflict_rule",
         "dv_harness.system_resource_inventory.real_cross_subsystem_findings",
         "dv_harness.system_resource_inventory.INTEGRATION_STOPPED"),
        "GF-AT-16 ('same physical interface cannot have two active owners'). DETECTION "
        "only: a real conflict renders BLOCKED and carries SYS-12's preferred_model "
        "through as text for a HUMAN to arbitrate. Nothing in this module picks a winner."),
    GenerationRowSpec(
        "system_topology", "System Topology",
        FLOW_B, P0_SUBSYSTEM_TO_SYSTEM, "section 213 P0 SUBSYSTEM->SYSTEM: 'System Topology'",
        "system_topology_analysis.analyze_system_topology() (SYS-28..SYS-30)",
        ("dv_harness.system_topology_analysis.analyze_system_topology",
         "dv_harness.system_topology_analysis.build_system_topology_analysis"),
        "The real SYS-1 -> SYS-30 chain, run at most once per report and only when the "
        "cheap cross-subsystem front door already reported the evidence is there."),
    GenerationRowSpec(
        "address_clock_reset_irq", "Address / Clock / Reset / IRQ",
        FLOW_B, P1,
        "section 213 P1: 'address/route intelligence' and 'clock/reset scenarios'. Note "
        "GF-AT-23/24 make an address or clock/reset ownership CONFLICT block SYSTEM_READY "
        "regardless of this row's planning-priority bucket.",
        "system_topology_analysis.reconcile_address_maps() / compare_clock_reset_domains() "
        "/ reconcile_interrupt_maps()",
        ("dv_harness.system_topology_analysis.reconcile_address_maps",
         "dv_harness.system_topology_analysis.compare_clock_reset_domains",
         "dv_harness.system_topology_analysis.reconcile_interrupt_maps"),
        "Read off the SAME topology document row 13 produced -- the analysis is run once "
        "and read four ways, never re-run per row."),
    GenerationRowSpec(
        "command_integration", "Command Integration",
        FLOW_B, P0_SUBSYSTEM_TO_SYSTEM,
        "section 213 P0 SUBSYSTEM->SYSTEM: 'Command Integration'",
        "system_command_plan.build_system_command_plan() (SYS-18..SYS-22)",
        ("dv_harness.system_command_plan.build_system_command_plan",
         "dv_harness.system_command_plan.detect_command_collisions",
         "dv_harness.system_command_plan.assert_no_emitted_artifacts"),
        "GF-AT-17 ('system command.txt is not blind concatenation'). The plan's own "
        "assert_no_emitted_artifacts() is SYS-39/40's boundary in code: a PLAN exists, a "
        "real system command.txt is not written without human approval, and this row "
        "reports the plan, never a written artifact."),
    GenerationRowSpec(
        "system_virtual_sequencer", "System Virtual Sequencer",
        FLOW_B, P0_SUBSYSTEM_TO_SYSTEM,
        "section 213 P0 SUBSYSTEM->SYSTEM: 'System Architecture'",
        "system_command_plan.build_system_architecture() + "
        "soc_environment_composer.compose_soc_environment()'s virtual-sequencer fields",
        ("dv_harness.system_command_plan.build_system_architecture",
         "dv_harness.uvm_generator.soc_environment_composer.compose_soc_environment"),
        "GF-AT-19 ('system virtual sequencer reuses subsystem sequencers'). This is the "
        "one Flow-B content row the composer CAN build generically, because a subsystem "
        "sequencer handle is identity metadata rather than protocol behaviour -- which is "
        "exactly why the next three rows cannot be."),
    GenerationRowSpec(
        "system_scenario", "System Scenario",
        FLOW_B, P0_SUBSYSTEM_TO_SYSTEM,
        "section 213 P0 SUBSYSTEM->SYSTEM: 'System Scenario'",
        "system_topology_analysis.plan_system_scenario_model() (plans only) + "
        "soc_environment_composer.cross_subsystem_scenarios() (deliberately not implemented)",
        ("dv_harness.system_scheduling_plan.probe_composer_boundary",
         "dv_harness.system_topology_analysis.plan_system_scenario_model",
         "dv_harness.uvm_generator.soc_environment_composer.cross_subsystem_scenarios"),
        "The boundary is probed, not asserted: probe_composer_boundary() CALLS the stub "
        "and records that it still raises. Scenario BODIES are protocol-behaviour content "
        "with no primary source in registry metadata ('No Golden-Reference Content "
        "Mining'), and SYS-40 additionally requires human approval before any body is "
        "generated. BLOCKED here is the honest state, not a defect to paper over."),
    GenerationRowSpec(
        "system_correlation_scoreboard", "System Correlation Scoreboard",
        FLOW_B, P1, "section 213 P1: 'system correlation'",
        "system_scheduling_plan.plan_cross_subsystem_checking() (plans only) + "
        "soc_environment_composer.end_to_end_scoreboard() (deliberately not implemented)",
        ("dv_harness.system_scheduling_plan.probe_composer_boundary",
         "dv_harness.system_scheduling_plan.plan_cross_subsystem_checking",
         "dv_harness.uvm_generator.soc_environment_composer.end_to_end_scoreboard"),
        "GF-AT-21. Same probed boundary as the row above: cross-subsystem CHECKING LOGIC "
        "needs each subsystem's real transaction item fields and the real transformation "
        "between them."),
    GenerationRowSpec(
        "system_cross_coverage", "System Cross Coverage",
        FLOW_B, P1, "section 213 P1: 'cross coverage'",
        "soc_environment_composer.system_coverage() (deliberately not implemented)",
        ("dv_harness.system_scheduling_plan.probe_composer_boundary",
         "dv_harness.uvm_generator.soc_environment_composer.system_coverage"),
        "GF-AT-22. Same probed boundary: cross-subsystem coverage BINS need real "
        "per-subsystem state/event semantics to be meaningful."),
    GenerationRowSpec(
        "system_build_smoke_proof", "System Build / Smoke Proof",
        FLOW_B, P0_SUBSYSTEM_TO_SYSTEM,
        "section 213 P0 SUBSYSTEM->SYSTEM: 'System Build/Smoke'",
        "system_build_proof.analyze_system_merge() + run_system_smoke_proof() (section 206)",
        ("dv_harness.system_build_proof.analyze_system_merge",
         "dv_harness.system_build_proof.subsystem_source_sets",
         "dv_harness.system_build_proof.SMOKE_PROOF_LADDER",
         "dv_harness.system_build_proof.SMOKE_NOT_PROVEN"),
        "GF-AT-25 ('system smoke proof precedes large regression') and GF-AT-28 ('UNKNOWN "
        "never becomes PASS/READY automatically'). This row reports whether the ladder has "
        "real merged sources to run over; it never RUNS a build, an elaboration or a "
        "simulation, because a readiness report must not start one."),
)


def row_ids() -> List[str]:
    return [r.row_id for r in ROWS]


def row_labels() -> List[str]:
    return [r.label for r in ROWS]


#: Section 211 prints twenty rows. Transcribed once here so the import-time
#: check below compares the declarations against the SPECIFICATION's own list
#: rather than against itself -- a list that validates only its own length is
#: exactly how a row goes silently missing.
SECTION_211_ROW_LABELS: tuple = (
    "Spec Parsing / Requirement IR",
    "DUT Discovery",
    "Protocol / VIP Mapping",
    "VIP API Retrieval",
    "UVM Architecture",
    "Scenario / Negative / CSR / IRQ",
    "Checker / Coverage / Assertions",
    "Config / Build / Compile-Fix",
    "Single-Test Proof",
    "Subsystem Inventory / Decomposition",
    "Shared Resource / VIP Resolver",
    "Active Driver Ownership",
    "System Topology",
    "Address / Clock / Reset / IRQ",
    "Command Integration",
    "System Virtual Sequencer",
    "System Scenario",
    "System Correlation Scoreboard",
    "System Cross Coverage",
    "System Build / Smoke Proof",
)


def _assert_rows_match_section_211() -> None:
    declared = tuple(r.label for r in ROWS)
    if declared != SECTION_211_ROW_LABELS:
        raise GenerationReadinessError("SECTION_211_ROW_SET_CHANGED", {
            "declared": list(declared),
            "specification": list(SECTION_211_ROW_LABELS),
            "missing": [l for l in SECTION_211_ROW_LABELS if l not in declared],
            "unexpected": [l for l in declared if l not in SECTION_211_ROW_LABELS]})
    ids = [r.row_id for r in ROWS]
    if len(set(ids)) != len(ids):
        raise GenerationReadinessError("DUPLICATE_ROW_ID", {"row_ids": ids})


def _assert_declared_vocabularies_are_real() -> None:
    bad_flow = sorted({r.flow for r in ROWS if r.flow not in FLOWS})
    bad_priority = sorted({r.priority for r in ROWS if r.priority not in PRIORITIES})
    if bad_flow or bad_priority:
        raise GenerationReadinessError("ROW_SPEC_VOCABULARY_UNKNOWN", {
            "unknown_flows": bad_flow, "known_flows": list(FLOWS),
            "unknown_priorities": bad_priority, "known_priorities": list(PRIORITIES)})


_assert_rows_match_section_211()
_assert_declared_vocabularies_are_real()


# ===========================================================================
# Gap -> Action catalog (driven through inference.next_best_action)
# ===========================================================================

#: The catalog shape `inference.next_best_action()` documents, keyed by row_id
#: so a row's Action is one registered string rather than prose written per run.
#: The same domain-neutral engine `capability_evolution.py` and
#: `golden_flow_readiness.py` already drive with their own catalogs.
GENERATION_GAP_ACTION_CATALOG: Dict[str, Any] = {
    "source": "generation_readiness_row",
    "fallback": (
        "no action is registered for '{gap}' -- name the missing generation evidence and "
        "the real command that would produce it before treating this row as closed"
    ),
    "actions": {
        "spec_parsing_requirement_ir": (
            "supply a real requirement contract set and run it through "
            "`requirement_contract.analyze_requirement_contract_set()`; an AMBIGUOUS or "
            "CONTRADICTORY requirement must be resolved with a cited source, never "
            "resolved by the generator picking a reading"),
        "dut_discovery": (
            "run `dv-harness env-manifest generate --rtl-file <f> ...` so dut_facts.rtl is "
            "a real verible parse of the current RTL; GF-AT-03 requires discovery grounded "
            "in current RTL, not in a document"),
        "protocol_vip_mapping": (
            "close the protocol's capability row: a GENERIC_SKELETON_ONLY status means no "
            "protocol-specific model exists yet, so build one under "
            "`dv_harness/uvm_generator/` and re-run `python -m "
            "dv_harness.protocol_capability --sync`"),
        "vip_api_retrieval": (
            "build a real VIP symbol index and validate the generated sources with "
            "`vip_api_card.validate_vip_api_usage()`; GF-AT-05 makes an unindexed API a "
            "BLOCKED card, never a generated call"),
        "uvm_architecture": (
            "generate through the real entry point (`python "
            "tools/generate_protocol_uvm_environment.py ...`) and read the "
            "`uvm_structural_lint.json` it writes; if verible is not installed the lint "
            "reports NOT_AVAILABLE and this factory cannot check its own output "
            "structurally at all"),
        "scenario_negative_csr_irq": (
            "supply a real register map (`dv-harness env-manifest generate "
            "--register-map <f>`) and a real init sequence; GF-AT-09 forbids guessing "
            "register semantics, so an absent map blocks CSR scenario generation rather "
            "than downgrading it"),
        "checker_coverage_assertions": (
            "supply real testplan sources (`dv-harness env-manifest generate "
            "--testplan-sources <f>`) so the testlist/vPlan/coverage-model join exists; "
            "GF-AT-11 requires coverage to map to a requirement/objective"),
        "config_build_compile_fix": (
            "capture a real config_db trace from a run (`dv-harness env-manifest generate "
            "--config-db-trace-log <sim.log>`); a built configuration nobody observed is "
            "an assumption, not evidence"),
        "single_test_proof": (
            "take a subsystem through SUBSYSTEM_MODE to a gate-validated SIGNOFF PASS so "
            "engine.py registers it at SMOKE_QUALIFIED or above; GF-AT-13 requires "
            "deterministic proof, and a registry entry is the only thing that carries it"),
        "subsystem_inventory_decomposition": (
            "register at least two subsystems through SUBSYSTEM_MODE; per CLAUDE.md's "
            "Environment Generation Mode rule a missing subsystem is built through "
            "SUBSYSTEM_MODE and then returned to composition, never composed around"),
        "shared_resource_vip_resolver": (
            "run `dv-harness system-resources --select <A> <B>` over registered subsystems "
            "whose environments are really on disk; TRACK_B_ANALYSIS_UNAVAILABLE is an "
            "honest 'nothing was checked', never a clear result"),
        "active_driver_ownership": (
            "a DRIVER_CONFLICT is a HUMAN arbitration decision: read SYS-12's "
            "preferred_model, decide which subsystem owns the interface, and record that "
            "decision -- this harness detects the conflict and deliberately does not "
            "resolve it"),
        "system_topology": (
            "run `dv-harness system-topology --select <A> <B>`; the analysis needs two "
            "registered subsystems with real environments on disk before it can reconcile "
            "anything"),
        "address_clock_reset_irq": (
            "reconcile the conflicting address regions or clock/reset domains the analysis "
            "named; GF-AT-23/24 make either conflict block SYSTEM_READY, so this cannot be "
            "deferred past composition"),
        "command_integration": (
            "run `dv-harness system-command-plan --select <A> <B>` and resolve every "
            "blocking collision; GF-AT-17 forbids blind concatenation, and SYS-39 requires "
            "human approval before a real system command.txt is written"),
        "system_virtual_sequencer": (
            "compose through the real entry point once the subsystems are registered; the "
            "virtual sequencer is built from registered subsystem sequencer handles, so it "
            "is blocked by the registry, not by missing content"),
        "system_scenario": (
            "none available generically: cross-subsystem scenario BODIES need primary "
            "per-subsystem VIP/DUT evidence and SYS-40 human approval. Supply that "
            "evidence for the specific subsystems being composed -- do not fill the stub "
            "with a plausible-looking placeholder"),
        "system_correlation_scoreboard": (
            "none available generically: an end-to-end scoreboard needs each subsystem's "
            "real transaction item fields and the real transformation between them. "
            "`plan_cross_subsystem_checking()` plans the flow; the checking logic itself "
            "needs primary evidence"),
        "system_cross_coverage": (
            "none available generically: cross-subsystem coverage bins need real "
            "per-subsystem state/event semantics. Define them from primary evidence for "
            "the specific subsystems, never from a generic template"),
        "system_build_smoke_proof": (
            "run `dv-harness system-smoke-proof --select <A> <B>` once two subsystem "
            "environments are really on disk; GF-AT-28 means an unproven rung stays "
            "SMOKE_NOT_PROVEN and never becomes SYSTEM_READY on its own"),
    },
}


def _actions(root: Path, gaps: List[str]) -> Dict[str, str]:
    """row_id -> Action, via the REAL inference engine.

    `protocol` is None because this caller is not protocol-scoped; the catalog
    branch of `next_best_action()` never reaches the protocol registry.
    """
    if not gaps:
        return {}
    from .inference import next_best_action
    results = next_best_action(None, gaps, root,
                               gap_action_catalog=GENERATION_GAP_ACTION_CATALOG)
    return {r["gap"]: r["suggested_action"] for r in results}


# ===========================================================================
# Capability axis -- resolved through the import system, never declared
# ===========================================================================

def _resolve_dotted(dotted: str):
    """Resolve `pkg.mod.attr` / `pkg.mod.Class.attr` through the import system.

    Returns the object. Raises GenerationReadinessError naming the exact
    missing piece -- a row claiming a reader that has been renamed away is a row
    whose provenance is fiction, and it must fail loudly rather than render.
    """
    import importlib
    parts = dotted.split(".")
    obj = None
    rest: List[str] = []
    for cut in range(len(parts), 1, -1):
        try:
            obj = importlib.import_module(".".join(parts[:cut]))
        except Exception:
            continue
        rest = parts[cut:]
        break
    else:
        raise GenerationReadinessError("FACT_SOURCE_MODULE_UNIMPORTABLE",
                                       {"fact_source": dotted})
    for name in rest:
        if not hasattr(obj, name):
            raise GenerationReadinessError("FACT_SOURCE_ATTRIBUTE_MISSING", {
                "fact_source": dotted, "missing_attribute": name})
        obj = getattr(obj, name)
    return obj


def assert_fact_sources_resolvable() -> List[str]:
    """Every `fact_source` (and `capability_extra`) a row declares still
    resolves. Returns the resolved names.

    This is the anti-drift check that makes this module's reuse claim checkable
    rather than asserted.
    """
    resolved: List[str] = []
    for spec in ROWS:
        for dotted in tuple(spec.fact_source) + tuple(spec.capability_extra):
            try:
                _resolve_dotted(dotted)
            except GenerationReadinessError as exc:
                raise GenerationReadinessError(exc.reason,
                                               {**exc.detail, "row": spec.row_id}) from None
            resolved.append(dotted)
    return resolved


def probe_capability(spec: GenerationRowSpec) -> Dict[str, Any]:
    """Does the generation mechanism this row NAMES exist in this harness?

    PRESENT when every declared reader resolves; ABSENT (with the exact missing
    dotted path) when one does not. This is what makes a row whose backing
    mechanism has not landed render honestly instead of fabricating a status.
    """
    missing: List[str] = []
    for dotted in tuple(spec.fact_source) + tuple(spec.capability_extra):
        try:
            _resolve_dotted(dotted)
        except GenerationReadinessError as exc:
            missing.append(f"{dotted} ({exc.reason})")
    if missing:
        return {"capability": CAP_ABSENT,
                "detail": "unresolvable: " + "; ".join(missing),
                "missing": missing}
    return {"capability": CAP_PRESENT,
            "detail": f"{len(spec.fact_source) + len(spec.capability_extra)} declared "
                      f"reader(s) resolve",
            "missing": []}


# ===========================================================================
# Fact gathering -- every read below goes through an already-real reader
# ===========================================================================

@dataclass
class _Facts:
    """Everything the probes read, gathered once per report. Each field is
    either a real reader's own return value or None with a recorded reason."""
    root: Path
    cfg: Dict[str, Any]
    manifest: Optional[Dict[str, Any]]
    manifest_path: Optional[str]
    manifest_reason: str
    registry_entries: List[Dict[str, Any]]
    crosscheck: Dict[str, Any]
    topology: Optional[Dict[str, Any]]
    topology_reason: str
    composer_boundary: Optional[Dict[str, Any]]
    composer_boundary_reason: str
    deep: bool


def _gather_facts(root: Path, cfg: Optional[Dict[str, Any]] = None,
                  *, deep: bool = True) -> _Facts:
    from . import env_manifest as em
    from . import system_resource_inventory as sri
    from .environment_mode_router import read_registered_subsystem_entries

    root = Path(root)
    if cfg is None:
        from .config import DEFAULT_CONFIG, load_config
        # load_config() MATERIALIZES a default config.json when none exists.
        # For a project that has never run, take the same deep copy of the same
        # DEFAULT_CONFIG that branch returns, minus the write.
        if (root / ".dv-harness" / "config.json").exists():
            cfg = load_config(root)
        else:
            import json as _json
            cfg = _json.loads(_json.dumps(DEFAULT_CONFIG))

    manifest: Optional[Dict[str, Any]] = None
    manifest_path: Optional[str] = None
    manifest_reason = ""
    try:
        path = em.default_manifest_path(root)
        if path is None or not Path(path).is_file():
            manifest_reason = ("no env.manifest.json on disk -- produce one with "
                               "`dv-harness env-manifest generate`")
        else:
            manifest_path = str(path)
            manifest = em.load_env_manifest(path)
    except Exception as exc:
        manifest_reason = f"env.manifest.json unreadable: {type(exc).__name__}: {exc}"

    try:
        registry_entries = read_registered_subsystem_entries(root)
    except Exception as exc:  # pragma: no cover - reader already degrades to []
        registry_entries = []
        manifest_reason = manifest_reason or f"registry unreadable: {exc}"

    # The cheap Track-B front door. It already answers "is there anything real
    # to analyse" (fewer than two subsystems / environments not on disk / SYS-1
    # refusal) with a concrete reason, so the expensive chain below only runs
    # when this one says the evidence is there.
    try:
        crosscheck = sri.real_cross_subsystem_findings(
            root, budget_seconds=DEEP_ANALYSIS_BUDGET_SECONDS)
    except Exception as exc:  # pragma: no cover - the reader catches its own
        crosscheck = {"status": sri.CROSSCHECK_UNAVAILABLE,
                      "reason": f"{type(exc).__name__}: {exc}", "subsystems": []}

    topology: Optional[Dict[str, Any]] = None
    topology_reason = ""
    if not deep:
        topology_reason = "deep analysis disabled for this report (deep=False)"
    elif crosscheck.get("status") != sri.CROSSCHECK_AVAILABLE:
        topology_reason = str(crosscheck.get("reason") or "cross-subsystem analysis unavailable")
    else:
        try:
            from . import system_topology_analysis as sta
            topology = sta.analyze_system_topology(root, list(crosscheck["subsystems"]))
        except Exception as exc:
            topology_reason = f"topology analysis failed: {type(exc).__name__}: {exc}"

    composer_boundary: Optional[Dict[str, Any]] = None
    composer_boundary_reason = ""
    try:
        from . import system_scheduling_plan as ssp
        composer_boundary = ssp.probe_composer_boundary()
    except Exception as exc:
        composer_boundary_reason = f"boundary probe failed: {type(exc).__name__}: {exc}"

    return _Facts(root=root, cfg=cfg, manifest=manifest, manifest_path=manifest_path,
                  manifest_reason=manifest_reason, registry_entries=registry_entries,
                  crosscheck=crosscheck, topology=topology, topology_reason=topology_reason,
                  composer_boundary=composer_boundary,
                  composer_boundary_reason=composer_boundary_reason, deep=deep)


def _manifest_layer(facts: _Facts, *path: str) -> Optional[Dict[str, Any]]:
    node: Any = facts.manifest
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node if isinstance(node, dict) else None


def _layer_verdict(facts: _Facts, path: Tuple[str, ...],
                   extra: str = "") -> Tuple[str, str, str]:
    """(readiness, evidence, gap) for one env.manifest.json layer.

    The layer's OWN `status`/`reason` is the verdict -- env_manifest already
    distinguishes "no input was supplied to this generation run" from "the input
    was supplied and failed to parse", and re-deciding that here would be a
    second opinion about the same file."""
    dotted = ".".join(path)
    if facts.manifest is None:
        return UNKNOWN, f"{dotted}=NO_MANIFEST", facts.manifest_reason
    layer = _manifest_layer(facts, *path)
    if layer is None:
        return (UNKNOWN, f"{dotted}=ABSENT_FROM_MANIFEST",
                f"env.manifest.json carries no {dotted} layer")
    status = str(layer.get("status") or "UNKNOWN")
    if status in ("NOT_AVAILABLE", "UNKNOWN"):
        # No count is appended to an absent layer: "0 file(s)" beside
        # NOT_AVAILABLE reads like a measured zero rather than an absence.
        return (UNKNOWN, f"{dotted}={status}",
                str(layer.get("reason") or f"{dotted} is {status}"))
    return READY, f"{dotted}={status}" + (f" ({extra})" if extra else ""), ""


def _crosscheck_available(facts: _Facts) -> bool:
    from . import system_resource_inventory as sri
    return facts.crosscheck.get("status") == sri.CROSSCHECK_AVAILABLE


def _crosscheck_gap(facts: _Facts) -> str:
    return (f"cross-subsystem analysis unavailable: "
            f"{facts.crosscheck.get('reason') or 'no reason recorded'}")


def _boundary_probe(facts: _Facts, function_name: str) -> Optional[Dict[str, Any]]:
    for probe in ((facts.composer_boundary or {}).get("probes") or ()):
        if probe.get("function") == function_name:
            return probe
    return None


# ===========================================================================
# Per-row probes
# ===========================================================================
#
# Contract, held by every probe below:
#   * returns {"status", "evidence", "gap"} where status is a readiness class;
#   * reads ONLY through the readers named in the row's own `fact_source`
#     (gathered once into _Facts);
#   * NEVER raises for a project that has not run -- absence is a verdict
#     (UNKNOWN plus a gap naming what is absent), not an error.
#
# The capability axis is applied by `derive_generation_readiness()` AFTER the
# probe, so no probe has to remember to check it.

def _probe_requirement_ir(facts: _Facts, spec: GenerationRowSpec) -> Dict[str, str]:
    # No canonical persisted path exists for a project's requirement contract
    # set, so this row reports the capability honestly and says exactly what
    # would make it READY -- it does NOT read a stage status and call that
    # requirement evidence.
    return {"status": UNKNOWN,
            "evidence": "requirement contract analyzer available; no contract set is "
                        "persisted at a canonical project path",
            "gap": "no requirement contract set has been supplied for this project, so "
                   "no requirement IR exists to generate from"}


def _probe_dut_discovery(facts: _Facts, spec: GenerationRowSpec) -> Dict[str, str]:
    layer = _manifest_layer(facts, "dut_facts", "rtl")
    extra = f"{len(layer.get('files') or [])} file(s)" if layer else ""
    status, evidence, gap = _layer_verdict(facts, ("dut_facts", "rtl"), extra)
    return {"status": status, "evidence": evidence, "gap": gap}


def _probe_protocol_vip_mapping(facts: _Facts, spec: GenerationRowSpec) -> Dict[str, str]:
    from . import protocol_capability as pc
    try:
        rows = pc.capability_rows()
    except Exception as exc:
        return {"status": UNKNOWN, "evidence": "protocol capability rows unreadable",
                "gap": f"capability_rows() failed: {type(exc).__name__}: {exc}"}
    skeleton = sorted(str(r.get("protocol") or r.get("name"))
                      for r in rows
                      if r.get("capability_status") == pc.STATUS_GENERIC_SKELETON_ONLY)
    modelled = len(rows) - len(skeleton)
    evidence = f"{modelled}/{len(rows)} protocol(s) carry a protocol-specific model"
    if not rows:
        return {"status": UNKNOWN, "evidence": "0 protocol(s) declared",
                "gap": "no protocol capability is declared in this harness"}
    if skeleton:
        return {"status": PARTIAL, "evidence": evidence,
                "gap": "only the protocol-agnostic skeleton exists for: "
                       + ", ".join(skeleton)}
    return {"status": READY, "evidence": evidence, "gap": ""}


def _probe_vip_api_retrieval(facts: _Facts, spec: GenerationRowSpec) -> Dict[str, str]:
    rel_status, rel_evidence, rel_gap = _layer_verdict(facts, ("vip_config", "vip_release"))
    ug_status, ug_evidence, ug_gap = _layer_verdict(facts, ("vip_config", "user_guide_refs"))
    # Deduped: both halves report the same "no manifest" reason when there is
    # no manifest, and printing it twice makes one gap look like two.
    gaps = list(dict.fromkeys(g for g in (rel_gap, ug_gap) if g))
    return {"status": combine_readiness([rel_status, ug_status]),
            "evidence": "; ".join([rel_evidence, ug_evidence]),
            "gap": "; ".join(gaps)}


def _probe_uvm_architecture(facts: _Facts, spec: GenerationRowSpec) -> Dict[str, str]:
    from . import verible_parser as vp
    evidence, gaps, parts = [], [], []
    try:
        version = vp.get_verible_version()
    except Exception as exc:  # pragma: no cover - reader returns None on failure
        version = None
        gaps.append(f"verible probe failed: {type(exc).__name__}: {exc}")
    if version:
        evidence.append(f"verible={version}")
        parts.append(READY)
    else:
        evidence.append("verible=NOT_AVAILABLE")
        gaps.append("verible is not runnable here, so uvm_structural_lint reports "
                    "NOT_AVAILABLE (never PASS) and generated UVM cannot be checked "
                    "structurally before it costs a compile")
        parts.append(UNKNOWN)
    hier = _manifest_layer(facts, "env_topology", "component_hierarchy")
    extra = f"{len(hier.get('components') or [])} component(s)" if hier else ""
    h_status, h_evidence, h_gap = _layer_verdict(
        facts, ("env_topology", "component_hierarchy"), extra)
    evidence.append(h_evidence)
    parts.append(h_status)
    if h_gap:
        gaps.append(h_gap)
    return {"status": combine_readiness(parts), "evidence": "; ".join(evidence),
            "gap": "; ".join(gaps)}


def _probe_scenario_csr_irq(facts: _Facts, spec: GenerationRowSpec) -> Dict[str, str]:
    layer = _manifest_layer(facts, "dut_facts", "registers")
    # `blocks` is the key build_dut_facts_registers() really writes.
    extra = f"{len(layer.get('blocks') or [])} register block(s)" if layer else ""
    status, evidence, gap = _layer_verdict(facts, ("dut_facts", "registers"), extra)
    return {"status": status, "evidence": evidence, "gap": gap}


def _probe_checker_coverage(facts: _Facts, spec: GenerationRowSpec) -> Dict[str, str]:
    corr = _manifest_layer(facts, "env_topology", "testplan_correspondence")
    summary = (corr or {}).get("summary") or {}
    extra = ""
    if summary:
        extra = (f"linked={summary.get('linked_count', 0)}, "
                 f"broken={summary.get('broken_count', 0)}, "
                 f"unclaimed={summary.get('unclaimed_count', 0)}")
    status, evidence, gap = _layer_verdict(
        facts, ("env_topology", "testplan_correspondence"), extra)
    if status == READY and (summary.get("broken_count") or summary.get("unclaimed_count")):
        return {"status": PARTIAL, "evidence": evidence,
                "gap": f"{summary.get('broken_count', 0)} broken and "
                       f"{summary.get('unclaimed_count', 0)} unclaimed vPlan item(s) in the "
                       f"coverage-model join"}
    return {"status": status, "evidence": evidence, "gap": gap}


def _probe_config_build(facts: _Facts, spec: GenerationRowSpec) -> Dict[str, str]:
    trace = _manifest_layer(facts, "env_topology", "config_db_trace")
    extra = f"{len(trace.get('entries') or [])} entry/entries" if trace else ""
    status, evidence, gap = _layer_verdict(facts, ("env_topology", "config_db_trace"), extra)
    return {"status": status, "evidence": evidence, "gap": gap}


def _probe_single_test_proof(facts: _Facts, spec: GenerationRowSpec) -> Dict[str, str]:
    from . import qualification as q
    entries = facts.registry_entries
    if not entries:
        return {"status": UNKNOWN, "evidence": "0 registered subsystem environment(s)",
                "gap": "no subsystem has reached a gate-validated SIGNOFF PASS, so no "
                       "deterministic single-test proof is on record"}
    proven, unproven = [], []
    for entry in entries:
        name = str(entry.get("name"))
        state = str(entry.get("qualification_state") or "")
        try:
            q.map_to_system_level_state(state)
        except ValueError as exc:
            unproven.append(f"{name}={state or 'UNSET'} ({exc})")
        else:
            proven.append(f"{name}={state}")
    evidence = f"{len(proven)}/{len(entries)} registered subsystem(s) at SMOKE_QUALIFIED or above"
    if proven:
        evidence += ": " + ", ".join(proven)
    if unproven:
        return {"status": PARTIAL if proven else BLOCKED, "evidence": evidence,
                "gap": "not system-composition eligible: " + "; ".join(unproven)}
    return {"status": READY, "evidence": evidence, "gap": ""}


def _probe_subsystem_inventory(facts: _Facts, spec: GenerationRowSpec) -> Dict[str, str]:
    names = [str(e.get("name")) for e in facts.registry_entries]
    evidence = f"{len(names)} registered subsystem(s)" + (f": {', '.join(names)}" if names else "")
    if len(names) >= 2:
        return {"status": READY, "evidence": evidence, "gap": ""}
    if len(names) == 1:
        return {"status": PARTIAL, "evidence": evidence,
                "gap": "one registered subsystem: system-level composition needs at least "
                       "two, so build the missing one through SUBSYSTEM_MODE first"}
    return {"status": UNKNOWN, "evidence": evidence,
            "gap": "the subsystem environment registry is empty -- nothing has been "
                   "registered by a gate-validated SIGNOFF PASS"}


def _probe_shared_resource_resolver(facts: _Facts, spec: GenerationRowSpec) -> Dict[str, str]:
    if not _crosscheck_available(facts):
        return {"status": UNKNOWN,
                "evidence": f"TRACK_B_ANALYSIS_UNAVAILABLE "
                            f"({facts.crosscheck.get('reason') or 'no reason recorded'})",
                "gap": _crosscheck_gap(facts)}
    cc = facts.crosscheck
    shared = cc.get("shared_relationships") or []
    evidence = (f"{cc.get('resource_count', 0)} resource(s) inventoried across "
                f"{len(cc.get('subsystems') or [])} subsystem(s); "
                f"{len(shared)} shared/same-physical relationship(s)")
    if not shared:
        return {"status": READY, "evidence": evidence,
                "gap": ""}
    return {"status": PARTIAL, "evidence": evidence,
            "gap": f"{len(shared)} shared resource relationship(s) need an ownership "
                   f"decision: "
                   + "; ".join(f"{r.get('resource_a')} vs {r.get('resource_b')}"
                               f" ({r.get('relationship')})" for r in shared[:5])}


def _probe_active_driver_ownership(facts: _Facts, spec: GenerationRowSpec) -> Dict[str, str]:
    if not _crosscheck_available(facts):
        return {"status": UNKNOWN,
                "evidence": f"TRACK_B_ANALYSIS_UNAVAILABLE "
                            f"({facts.crosscheck.get('reason') or 'no reason recorded'})",
                "gap": _crosscheck_gap(facts)}
    cc = facts.crosscheck
    conflicts = cc.get("driver_conflicts") or 0
    allowed = bool(cc.get("automatic_integration_allowed"))
    evidence = (f"{conflicts} driver conflict(s); automatic_integration_allowed={allowed}; "
                f"stopped={list(cc.get('stopped_resource_ids') or [])}; "
                f"held={list(cc.get('held_resource_ids') or [])}")
    if allowed and not conflicts:
        return {"status": READY, "evidence": evidence, "gap": ""}
    # DETECTION reported; ARBITRATION is deliberately left to a human. SYS-12's
    # preferred model is carried through as the text that human reads.
    return {"status": BLOCKED, "evidence": evidence,
            "gap": ("HUMAN ARBITRATION REQUIRED -- two ACTIVE owners on one physical "
                    "interface. SYS-12 preferred model: "
                    f"{cc.get('preferred_model') or 'none recorded'}. This harness detects "
                    "the conflict and does not pick a winner.")}


def _probe_system_topology(facts: _Facts, spec: GenerationRowSpec) -> Dict[str, str]:
    if facts.topology is None:
        return {"status": UNKNOWN, "evidence": "topology analysis NOT_RUN",
                "gap": facts.topology_reason or _crosscheck_gap(facts)}
    doc = facts.topology.get("topology_analysis") or {}
    summary = doc.get("summary") or {}
    evidence = (f"{len(summary.get('selected_subsystems') or [])} subsystem(s); "
                f"topology_clean={summary.get('topology_clean')}; "
                f"address_regions={summary.get('address_regions', 0)}; "
                f"interrupt_lines={summary.get('interrupt_lines', 0)}")
    if summary.get("topology_clean"):
        return {"status": READY, "evidence": evidence, "gap": ""}
    return {"status": PARTIAL, "evidence": evidence,
            "gap": "the reconciled system topology is not clean -- see the "
                   "Address / Clock / Reset / IRQ row for the specific conflicts"}


def _probe_address_clock_reset_irq(facts: _Facts, spec: GenerationRowSpec) -> Dict[str, str]:
    if facts.topology is None:
        return {"status": UNKNOWN, "evidence": "topology analysis NOT_RUN",
                "gap": facts.topology_reason or _crosscheck_gap(facts)}
    summary = ((facts.topology.get("topology_analysis") or {}).get("summary") or {})
    addr_conflicts = summary.get("address_conflicts", 0)
    cr_conflicts = summary.get("clock_reset_conflicts", 0)
    shared_irq = summary.get("shared_interrupt_lines", 0)
    evidence = (f"address_conflicts={addr_conflicts}; "
                f"shared_memory_windows={summary.get('shared_memory_windows', 0)}; "
                f"clock_reset_conflicts={cr_conflicts}; "
                f"cdc_boundaries={summary.get('cdc_boundaries', 0)}; "
                f"shared_interrupt_lines={shared_irq}")
    gaps = []
    if addr_conflicts:
        gaps.append(f"{addr_conflicts} address conflict(s) -- GF-AT-23 blocks SYSTEM_READY")
    if cr_conflicts:
        gaps.append(f"{cr_conflicts} clock/reset conflict(s) -- GF-AT-24 blocks SYSTEM_READY")
    if gaps:
        return {"status": BLOCKED, "evidence": evidence, "gap": "; ".join(gaps)}
    if shared_irq:
        return {"status": PARTIAL, "evidence": evidence,
                "gap": f"{shared_irq} interrupt line(s) shared across subsystems need an "
                       f"ownership decision"}
    return {"status": READY, "evidence": evidence, "gap": ""}


def _probe_command_integration(facts: _Facts, spec: GenerationRowSpec) -> Dict[str, str]:
    if facts.topology is None:
        return {"status": UNKNOWN, "evidence": "command plan NOT_BUILT",
                "gap": facts.topology_reason or _crosscheck_gap(facts)}
    plan = facts.topology.get("command_plan") or {}
    summary = plan.get("summary") or {}
    evidence = (f"{summary.get('system_commands', 0)} system command(s); "
                f"ir_entries={summary.get('ir_entries', 0)}; "
                f"collisions={summary.get('collisions', 0)} "
                f"(blocking={summary.get('blocking_collisions', 0)}); "
                f"command_plan_clean={summary.get('command_plan_clean')}")
    if summary.get("blocking_collisions"):
        return {"status": BLOCKED, "evidence": evidence,
                "gap": f"{summary['blocking_collisions']} blocking command collision(s) -- "
                       f"GF-AT-17 forbids blind concatenation"}
    if not summary.get("command_plan_clean"):
        return {"status": PARTIAL, "evidence": evidence,
                "gap": "the command plan is not clean (ambiguous namespace or a subsystem "
                       "mode not preserved)"}
    return {"status": READY, "evidence": evidence, "gap": ""}


def _probe_system_virtual_sequencer(facts: _Facts, spec: GenerationRowSpec) -> Dict[str, str]:
    if facts.topology is None:
        return {"status": UNKNOWN, "evidence": "system architecture NOT_BUILT",
                "gap": facts.topology_reason or _crosscheck_gap(facts)}
    arch = ((facts.topology.get("command_plan") or {}).get("system_architecture") or {})
    selected = arch.get("selected_subsystems") or []
    evidence = (f"system architecture over {len(selected)} subsystem(s)"
                + (f": {', '.join(str(s) for s in selected)}" if selected else ""))
    if len(selected) >= 2:
        return {"status": READY, "evidence": evidence, "gap": ""}
    return {"status": PARTIAL, "evidence": evidence,
            "gap": "a system virtual sequencer over fewer than two subsystems reuses "
                   "nothing across subsystems"}


def _boundary_row(facts: _Facts, function_name: str, what: str) -> Dict[str, str]:
    """The shared verdict for the three rows sitting on the composer's
    deliberately-unimplemented boundary. The boundary is PROBED (the stub is
    really called and really raises), never asserted from a comment."""
    if facts.composer_boundary is None:
        return {"status": UNKNOWN, "evidence": "composer boundary NOT_PROBED",
                "gap": facts.composer_boundary_reason or "boundary probe unavailable"}
    probe = _boundary_probe(facts, function_name)
    if probe is None:
        return {"status": UNKNOWN,
                "evidence": f"{function_name} not covered by the boundary probe",
                "gap": f"system_scheduling_plan.COMPOSER_BOUNDARY_FUNCTIONS does not "
                       f"include {function_name}"}
    if probe.get("raises") != "NotImplementedError":
        # The stub has been implemented since this row was written. That is a
        # real change in generation capability and must be reported as one --
        # not silently rendered as still-blocked.
        return {"status": PARTIAL,
                "evidence": f"{function_name} NO LONGER raises NotImplementedError",
                "gap": "this row's declared boundary has moved; re-derive its status "
                       "against the implemented generator before trusting it"}
    return {"status": BLOCKED,
            "evidence": f"{function_name} raises NotImplementedError (boundary intact)",
            "gap": f"{what} is protocol-BEHAVIOUR content with no primary source in "
                   f"subsystem registry metadata; SYS-40 additionally requires human "
                   f"approval before any body is generated. Composer reason: "
                   + str(probe.get("reason") or "")[:200]}


def _probe_system_scenario(facts: _Facts, spec: GenerationRowSpec) -> Dict[str, str]:
    return _boundary_row(facts, "cross_subsystem_scenarios",
                         "a cross-subsystem scenario body")


def _probe_system_correlation_scoreboard(facts: _Facts,
                                         spec: GenerationRowSpec) -> Dict[str, str]:
    return _boundary_row(facts, "end_to_end_scoreboard",
                         "end-to-end cross-subsystem checking logic")


def _probe_system_cross_coverage(facts: _Facts, spec: GenerationRowSpec) -> Dict[str, str]:
    return _boundary_row(facts, "system_coverage",
                         "cross-subsystem coverage bin content")


def _probe_system_build_smoke(facts: _Facts, spec: GenerationRowSpec) -> Dict[str, str]:
    from . import system_build_proof as sbp
    try:
        sets = sbp.subsystem_source_sets(facts.root)
    except Exception as exc:
        return {"status": UNKNOWN, "evidence": "subsystem source sets unreadable",
                "gap": f"subsystem_source_sets() failed: {type(exc).__name__}: {exc}"}
    with_sources = {k: len(v) for k, v in sets.items() if v}
    empty = sorted(k for k, v in sets.items() if not v)
    evidence = (f"{len(with_sources)}/{len(sets)} registered subsystem(s) have UVM sources "
                f"on disk"
                + (f" ({', '.join(f'{k}:{n}' for k, n in sorted(with_sources.items()))})"
                   if with_sources else ""))
    if not sets:
        return {"status": UNKNOWN, "evidence": "0 registered subsystem(s)",
                "gap": "nothing is registered, so the section 206 smoke-proof ladder has "
                       "no merged source set to run over -- SMOKE_NOT_PROVEN, never READY"}
    if empty:
        return {"status": PARTIAL if with_sources else UNKNOWN, "evidence": evidence,
                "gap": "no UVM sources on disk for: " + ", ".join(empty)}
    if len(with_sources) < 2:
        return {"status": PARTIAL, "evidence": evidence,
                "gap": "a system merge check needs at least two subsystem source sets; a "
                       "duplicate class across two environments is invisible with one"}
    # The ladder itself is deliberately NOT run here: a readiness report must
    # not start a build, an elaboration or a simulation. GF-AT-28 -- an unrun
    # ladder is SMOKE_NOT_PROVEN, never READY.
    return {"status": PARTIAL, "evidence": evidence + "; ladder NOT_RUN by this report",
            "gap": f"the section 206 ladder has real sources but has not been run "
                   f"({sbp.SMOKE_NOT_PROVEN}); run `dv-harness system-smoke-proof` -- this "
                   f"report never starts a build"}


#: row_id -> probe. Declared separately from ROWS so a row can never be added
#: without a probe (asserted below) and a probe can never be orphaned.
PROBES: Dict[str, Callable[[_Facts, GenerationRowSpec], Dict[str, str]]] = {
    "spec_parsing_requirement_ir": _probe_requirement_ir,
    "dut_discovery": _probe_dut_discovery,
    "protocol_vip_mapping": _probe_protocol_vip_mapping,
    "vip_api_retrieval": _probe_vip_api_retrieval,
    "uvm_architecture": _probe_uvm_architecture,
    "scenario_negative_csr_irq": _probe_scenario_csr_irq,
    "checker_coverage_assertions": _probe_checker_coverage,
    "config_build_compile_fix": _probe_config_build,
    "single_test_proof": _probe_single_test_proof,
    "subsystem_inventory_decomposition": _probe_subsystem_inventory,
    "shared_resource_vip_resolver": _probe_shared_resource_resolver,
    "active_driver_ownership": _probe_active_driver_ownership,
    "system_topology": _probe_system_topology,
    "address_clock_reset_irq": _probe_address_clock_reset_irq,
    "command_integration": _probe_command_integration,
    "system_virtual_sequencer": _probe_system_virtual_sequencer,
    "system_scenario": _probe_system_scenario,
    "system_correlation_scoreboard": _probe_system_correlation_scoreboard,
    "system_cross_coverage": _probe_system_cross_coverage,
    "system_build_smoke_proof": _probe_system_build_smoke,
}


def _assert_every_row_has_a_probe() -> None:
    missing = [r.row_id for r in ROWS if r.row_id not in PROBES]
    orphan = [k for k in PROBES if k not in {r.row_id for r in ROWS}]
    if missing or orphan:
        raise GenerationReadinessError("ROW_PROBE_SET_MISMATCH", {
            "rows_without_probe": missing, "probes_without_row": orphan})


def _assert_every_row_has_an_action() -> None:
    catalog = GENERATION_GAP_ACTION_CATALOG["actions"]
    missing = [r.row_id for r in ROWS if r.row_id not in catalog]
    orphan = [k for k in catalog if k not in {r.row_id for r in ROWS}]
    if missing or orphan:
        raise GenerationReadinessError("ROW_ACTION_CATALOG_MISMATCH", {
            "rows_without_action": missing, "actions_without_row": orphan})


_assert_every_row_has_a_probe()
_assert_every_row_has_an_action()


# ===========================================================================
# The matrix
# ===========================================================================

def derive_generation_readiness(root, cfg: Optional[Dict[str, Any]] = None,
                                *, deep: bool = True) -> Dict[str, Any]:
    """Section 211's matrix for one real project root.

    Read-only and total: every declared row appears in the output, including
    rows whose sources reported absence -- section 211's table is mandatory, and
    "this row is UNKNOWN" and "this row was omitted" must not look alike.

    `deep=False` skips the expensive SYS-1..SYS-30 topology chain and reports
    the Flow-B topology/command rows as UNKNOWN with that as the recorded
    reason. It never changes any other row's verdict.
    """
    root = Path(root)
    facts = _gather_facts(root, cfg, deep=deep)
    rows: List[Dict[str, Any]] = []
    for spec in ROWS:
        cap = probe_capability(spec)
        try:
            probed = PROBES[spec.row_id](facts, spec)
        except Exception as e:  # a probe bug must not delete a mandatory row
            probed = {"status": UNKNOWN, "evidence": NONE_CELL,
                      "gap": f"probe raised {type(e).__name__}: {e}"}
        project_status = probed.get("status") or UNKNOWN
        if project_status not in GENERATION_READINESS_CLASSES:
            raise GenerationReadinessError("PROBE_RETURNED_UNKNOWN_READINESS_CLASS", {
                "row": spec.row_id, "status": project_status,
                "legal_values": list(GENERATION_READINESS_CLASSES)})
        # STRICT worst of the two axes. A mechanism that does not exist cannot
        # be rescued by project evidence, and -- the direction that matters most
        # for honesty -- project evidence that is absent is NOT lifted to
        # PARTIAL just because the mechanism exists. GF-AT-28: UNKNOWN never
        # becomes READY (or PARTIAL) automatically.
        capability_readiness = _CAPABILITY_TO_READINESS[cap["capability"]]
        status = worst_readiness([capability_readiness, project_status])
        evidence = (probed.get("evidence") or "").strip()
        gap = (probed.get("gap") or "").strip()
        if cap["capability"] != CAP_PRESENT:
            gap = "; ".join(x for x in (f"capability {cap['capability']}: {cap['detail']}",
                                        gap) if x)
        rows.append({
            "row_id": spec.row_id,
            "row": spec.label,
            "status": status,
            "capability": cap["capability"],
            "capability_detail": cap["detail"],
            "project_evidence_status": project_status,
            "existing_reuse": spec.existing_reuse,
            "evidence": evidence or NONE_CELL,
            "gap": gap or NONE_CELL,
            "priority": spec.priority,
            "priority_basis": spec.priority_basis,
            "flow": spec.flow,
            "action": NONE_CELL,
            "fact_source": list(spec.fact_source),
            "basis": spec.basis,
        })

    # Action only for rows that are not READY: a closed row has no next action,
    # and printing one anyway teaches a reader to ignore the column.
    open_rows = [r["row_id"] for r in rows if r["status"] != READY]
    actions = _actions(root, open_rows)
    for r in rows:
        if r["row_id"] in actions:
            r["action"] = actions[r["row_id"]]

    counts = {cls: sum(1 for r in rows if r["status"] == cls)
              for cls in GENERATION_READINESS_CLASSES}
    by_flow = {flow: combine_readiness([r["status"] for r in rows if r["flow"] == flow])
               for flow in FLOWS}
    by_priority = {p: combine_readiness([r["status"] for r in rows if r["priority"] == p])
                   for p in PRIORITIES if any(r["priority"] == p for r in rows)}
    verdict = combine_readiness([r["status"] for r in rows])
    return {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "deep_analysis": deep,
        "env_manifest_path": facts.manifest_path,
        "registered_subsystems": [str(e.get("name")) for e in facts.registry_entries],
        "cross_subsystem_analysis_status": facts.crosscheck.get("status"),
        "cross_subsystem_analysis_reason": facts.crosscheck.get("reason", ""),
        "composer_boundary_intact": (facts.composer_boundary or {}).get("boundary_intact"),
        "rows": rows,
        "summary": {
            "rows_total": len(rows),
            **{f"rows_{cls.lower()}": counts[cls] for cls in GENERATION_READINESS_CLASSES},
            "by_flow": by_flow,
            "by_priority": by_priority,
        },
        "generation_readiness": verdict,
        "readiness_rule": (
            "Section 211: a capability is READY only when the generation mechanism really "
            "exists in this harness AND this project carries the real evidence that "
            "mechanism needs. GF-AT-28: UNKNOWN never becomes READY automatically."),
        "authorizes": (
            "nothing. This matrix is an input to a human's generation decision. It runs no "
            "stage, invokes no gate, starts no build or regression, writes no governance "
            "state, and never arbitrates an active-driver ownership conflict -- that "
            "decision stays with a human, as does SYS-39/SYS-40's approval before any real "
            "system command.txt, scenario body or shared driver code is generated."),
    }


def _cell(value: Any) -> str:
    """Pipe/newline-safe cell text -- the same escaping `system_readiness._cell()`
    applies before its own tables. Done caller-side: a reason read off a real
    analysis can legitimately contain a `|`, and the shared
    `render_markdown_table()` deliberately renders values verbatim."""
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_generation_matrix(matrix: Mapping[str, Any]) -> str:
    """Section 211's table in the document's exact seven-column shape.

    The JSON payload keeps every cell's raw text; only this rendered view is
    escaped."""
    from .connectivity import render_markdown_table
    keys = [k for k, _ in GENERATION_MATRIX_COLUMNS]
    rows = [{k: _cell(r.get(k, NONE_CELL)) for k in keys} for r in (matrix.get("rows") or ())]
    return render_markdown_table(
        list(GENERATION_MATRIX_COLUMNS), rows,
        empty_note="(no row was produced -- this is a bug: section 211's twenty rows are "
                   "mandatory even when every one is UNKNOWN)")


def format_generation_readiness_report(matrix: Mapping[str, Any]) -> str:
    """The section 211 report: the verdict, the counts, the table, and the two
    boundaries (what the rule is, what the verdict authorizes)."""
    summary = matrix["summary"]
    out = [
        "# GENERATION READINESS MATRIX (section 211)",
        "",
        f"**{matrix['generation_readiness']}** -- {summary['rows_ready']} ready / "
        f"{summary['rows_partial']} partial / {summary['rows_blocked']} blocked / "
        f"{summary['rows_unknown']} unknown, of {summary['rows_total']} rows.",
        "",
        f"Flow A (spec -> subsystem UVM): {summary['by_flow'][FLOW_A]}    "
        f"Flow B (subsystem UVM -> system-level UVM): {summary['by_flow'][FLOW_B]}",
        "",
        f"Project root: `{matrix['root']}`  (generated {matrix['generated_at']})",
        f"Registered subsystems: "
        f"{', '.join(matrix['registered_subsystems']) or '(none)'}    "
        f"Cross-subsystem analysis: {matrix['cross_subsystem_analysis_status']}"
        + (f" ({matrix['cross_subsystem_analysis_reason']})"
           if matrix.get("cross_subsystem_analysis_reason") else ""),
        "",
        render_generation_matrix(matrix),
        "",
        matrix["readiness_rule"],
        "",
        f"This verdict authorizes: {matrix['authorizes']}",
    ]
    blocked = [r for r in matrix.get("rows") or () if r["status"] == BLOCKED]
    if blocked:
        out += ["", "## Blocked rows", ""]
        out += [f"- **{r['row']}** ({r['priority']}) -- {r['gap']}" for r in blocked]
    return "\n".join(out)


# ===========================================================================
# One shared entry point for `dv-harness generation-readiness` and
# `python -m dv_harness.generation_readiness`
# ===========================================================================

def execute(root, *, cfg: Optional[Dict[str, Any]] = None,
            as_json: bool = False, deep: bool = True) -> Tuple[int, Dict[str, Any], str]:
    """Returns (exit_code, matrix, rendered_text).

    Exit 2 unless the whole matrix is READY. That is NOT an approval signal in
    either direction -- section 211's verdict is an audit input and a human
    still decides -- but a CI step must not read PARTIAL/BLOCKED/UNKNOWN as a
    clean run. Same convention `dv-harness golden-flow-readiness` and
    `dv-harness system-phase1-report` already use.
    """
    matrix = derive_generation_readiness(root, cfg, deep=deep)
    text = (format_generation_readiness_report(matrix) if not as_json else "")
    return (0 if matrix["generation_readiness"] == READY else 2), matrix, text


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - thin CLI shim
    import argparse
    import json as _json
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.generation_readiness",
        description="Section 211's GENERATION READINESS MATRIX, aggregated from this "
                    "harness's real generation mechanisms and this project's real "
                    "generation artifacts. Reads only; runs no stage and starts no build.")
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--no-deep", action="store_true",
                    help="Skip the SYS-1..SYS-30 cross-subsystem topology chain; the "
                         "Flow-B topology/command rows report UNKNOWN with that reason.")
    args = ap.parse_args(argv)
    code, matrix, text = execute(Path(args.project_root), as_json=args.as_json,
                                 deep=not args.no_deep)
    print(_json.dumps(matrix, ensure_ascii=False, indent=2) if args.as_json else text)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
