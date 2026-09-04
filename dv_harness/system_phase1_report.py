"""SYS-38 and SYS-39 of the System-Level Verification Integration workflow: the
REQUIRED PHASE-1 OUTPUT -- exactly twenty-two sections, in the requirement's own
order -- and the PHASE-1 STOP CONDITION that ends it.

WHAT THIS MODULE IS NOT
-----------------------
Stated first, because it is the boundary this whole workflow exists inside.
This module COMPUTES NOTHING. Every section body is either a renderer another
SYS-N module already owns, called on that module's own document, or a visible
NOT SUPPLIED note naming the function that would fill it. There is no second
address-map verdict here, no second dedup decision, no second readiness
derivation -- a report that recomputed what it reports could disagree with the
artifacts it claims to summarise, and a reader would have no way to tell which
half was wrong.

Nor does it emit anything. `render_system_phase1_report()` runs three guards on
its own FINISHED text before returning it: the twenty-two headings are present,
once each, in order (`assert_report_section_order()`); the text contains no
`bind` statement, tested with `connectivity.parse_bind_line()` -- the repo's one
definition of what a bind is; and it contains no emittable SystemVerilog
(`syoscb_source_audit.assert_no_emittable_sv()`). Checking the section TUPLE
instead would only prove the tuple agrees with itself; a heading a body
accidentally swallowed, duplicated or emitted out of order is a real failure
mode and only a check on the rendered text catches it.

WHY THE STOP TEXT IS A TUPLE OF LINES AND NOT A DOCSTRING
----------------------------------------------------------
SYS-39 says "report exactly" and then gives ten lines. `SYS39_STOP_LINES` holds
those ten verbatim; `render_stop_condition()` joins them and nothing else may
be interleaved. `assert_stop_condition_exact()` compares a candidate text
against them line by line so that "exactly" is a check rather than a promise --
this is the sentence that tells a human the harness has stopped, and a
paraphrase of it is a different sentence.

The stop is unconditional. It does not depend on the SYS-37 verdict: a READY
composition stops for approval on precisely the same terms as a BLOCKED one,
because SYS-39's stop is about who decides, not about how the analysis came
out.
"""

from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import reference_pattern_audit as rpa
from . import subsystem_architecture_analysis as saa
from . import subsystem_command_contract as scc
from . import subsystem_discovery as sd
from . import syoscb_source_audit as ssa
from . import system_command_plan as scp
from . import system_readiness as sr
from . import system_regression_plan as srp
from . import system_resource_inventory as sri
from . import system_resource_registry as srr
from . import system_scheduling_plan as ssp
from . import system_topology_analysis as sta
from .amba_fabric_discovery import assert_no_bind_statement

SCHEMA_VERSION = "1.0"

SYSTEM_LEVEL_DOC = ("DV_Agent_Harness_L5_ULTIMATE_COMPLETE_Master_Prompt_"
                    "SystemLevel_AMBA4_SyoSil_CCE_Research.md")

#: SYS-38's twenty-two items, verbatim and in the requirement's own numbered
#: order (that document's lines 4461-4484). "Produce exactly" is read as: all
#: twenty-two, once each, in this order -- a section whose input is missing
#: renders a NOT SUPPLIED note rather than being omitted, because a reader told
#: there are twenty-two uses that to notice one is absent.
SYS38_SECTIONS: tuple = (
    (1, "USER SELECTED SUBSYSTEMS"),
    (2, "SUBSYSTEM EXISTENCE CHECK"),
    (3, "KNOWLEDGE CENTER STATUS"),
    (4, "SUBSYSTEM READINESS MATRIX"),
    (5, "PER-SUBSYSTEM ARCHITECTURE ANALYSIS"),
    (6, "PER-SUBSYSTEM command.txt ANALYSIS"),
    (7, "SUBSYSTEM COMMAND CONTRACTS"),
    (8, "VIP / AGENT RESOURCE INVENTORY"),
    (9, "DUPLICATE RESOURCE ANALYSIS"),
    (10, "ACTIVE DRIVER CONFLICTS"),
    (11, "SHARED RESOURCE PROPOSAL"),
    (12, "SYSTEM_RESOURCE_REGISTRY"),
    (13, "SUBSYSTEM INTEGRATION MATRIX"),
    (14, "VIP / AGENT DEDUPLICATION MATRIX"),
    (15, "ADDRESS MAP INTEGRATION"),
    (16, "CLOCK / RESET INTEGRATION"),
    (17, "SCOREBOARD INTEGRATION PLAN"),
    (18, "SYSTEM command.txt SYNTHESIS PLAN"),
    (19, "SYSTEM ARCHITECTURE"),
    (20, "OPEN QUESTIONS"),
    (21, "SYSTEM READINESS"),
    (22, "USER REVIEW GATE"),
)

#: SYS-39's ten lines, verbatim. See the module docstring for why this is data.
SYS39_STOP_LINES: tuple = (
    "SYSTEM-LEVEL INTEGRATION DISCOVERY COMPLETE",
    "SELECTED SUBSYSTEM EXISTENCE CHECK COMPLETE",
    "KNOWLEDGE CENTER CHECK COMPLETE",
    "SUBSYSTEM ARCHITECTURE ANALYSIS COMPLETE",
    "SUBSYSTEM command.txt ANALYSIS COMPLETE",
    "VIP / AGENT DEDUPLICATION COMPLETE",
    "SYSTEM command.txt PLAN COMPLETE",
    "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED",
    "AWAITING USER APPROVAL",
    "STOP.",
)


class SystemPhase1ReportError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# ===========================================================================
# Helpers
# ===========================================================================

def _not_supplied(what: str, how: str) -> str:
    """The body of a section whose input was not supplied. It names the missing
    artifact and the exact call that produces it -- a reader must be able to
    close the gap, not merely learn that one exists."""
    return (f"_NOT SUPPLIED._ {what} was not passed to "
            f"`build_system_phase1_report()`. To fill this section: {how}.")


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _heading(number: int, title: str) -> str:
    return f"## {number}. {title}"


# ===========================================================================
# Section renderers -- sections with no existing owner elsewhere
# ===========================================================================

def render_selected_subsystems(selection: Mapping[str, Any]) -> str:
    """Section 1. SYS-1's own refusal state is carried through verbatim: a
    report whose selection is inadmissible must SAY so at the top, because
    every section under it is then a description of a set the user never
    approved."""
    selected = list(selection.get("selected_subsystems") or [])
    lines = [
        f"Selected: {', '.join(selected) if selected else '(none)'}",
        "",
        f"- selection admissible: **{selection.get('selection_admissible')}**"
        + (f" -- refusal reason `{selection['refusal_reason']}`"
           if selection.get("refusal_reason") else ""),
        f"- environment mode: "
        f"{(selection.get('environment_mode_decision') or {}).get('mode', 'UNRESOLVED')}",
        f"- candidates discovered: "
        f"{len((selection.get('discovery') or {}).get('candidates') or [])}",
        "",
        "SYS-1 requires an explicit user selection; this report never composes a set "
        "the user did not choose.",
        "",
        sd.render_discovery_table(selection.get("discovery") or {}),
    ]
    if selection.get("blocking_conflicts"):
        lines += ["", "### Candidate-set conflicts blocking this selection", ""]
        for conflict in selection["blocking_conflicts"]:
            lines.append(f"- {conflict.get('subsystems')}: {conflict.get('reason')}")
    return "\n".join(lines)


def render_existence_check(selection: Mapping[str, Any]) -> str:
    """Section 2. SYS-2's five-value existence class per SELECTED subsystem,
    with the reasons behind it -- the candidate table in section 1 shows the
    column, this shows why it says what it says."""
    header = "| Subsystem | Existence class | Registered | Environment path | Next action |"
    lines = [header, "|" + "---|" * 5]
    for row in selection.get("selected_rows") or []:
        lines.append("| " + " | ".join(_cell(v) for v in (
            row.get("subsystem"), row.get("existence_class"),
            "YES" if row.get("registered") else "no",
            row.get("environment_path") or "-",
            row.get("next_action") or "-")) + " |")
    if len(lines) == 2:
        lines.append("| _no subsystem was selected_ |" + " |" * 4)
    body = ["\n".join(lines)]
    not_ready = list(selection.get("not_ready") or [])
    body += ["", f"Selected subsystems that are not EXISTS_READY: "
                 f"{[r['subsystem'] for r in not_ready] or 'none'}"]
    for row in selection.get("selected_rows") or []:
        reasons = list(row.get("existence_reasons") or [])
        if reasons:
            body.append(f"- **{row.get('subsystem')}** "
                        f"({row.get('existence_class')}): " + "; ".join(str(r) for r in reasons))
    return "\n".join(body)


def render_knowledge_center_status(selection: Mapping[str, Any],
                                   record: Optional[Mapping[str, Any]]) -> str:
    """Section 3. Both directions of the Knowledge Center relationship: what
    SYS-3 READ per subsystem, and what SYS-34 would WRITE for the composition
    -- which is built but deliberately not published at Phase 1."""
    header = "| Subsystem | KC status | KC record | Agreement with repository |"
    lines = [header, "|" + "---|" * 4]
    for row in selection.get("selected_rows") or []:
        kc_block = row.get("knowledge_center") or {}
        lines.append("| " + " | ".join(_cell(v) for v in (
            row.get("subsystem"), row.get("knowledge_center_status"),
            "found" if kc_block.get("found") else "-",
            kc_block.get("agreement") or kc_block.get("detail") or "-")) + " |")
    if len(lines) == 2:
        lines.append("| _no subsystem was selected_ |" + " |" * 3)
    out = ["\n".join(lines), "",
           "SYS-42: check the Knowledge Center but TRUST CURRENT REPOSITORY EVIDENCE. "
           "Every readiness/existence verdict in this report is derived from the "
           "repository; a KC record is corroboration, never the source.", ""]
    if record is None:
        out.append(_not_supplied(
            "The SYS-34 composition record",
            "run `system_readiness.build_system_composition_record()` and pass it as "
            "`knowledge_center_record`"))
    else:
        out += [
            "### SYS-34 composition record (built, NOT published)",
            "",
            f"- composition: `{record.get('COMPOSITION_ID')}`",
            f"- category: `{record.get('_category', 'system_composition')}` on the "
            "EXISTING shared Knowledge Center -- no parallel knowledge store",
            f"- PHASE: `{record.get('PHASE')}` -- "
            "`KnowledgeCenterClient.record_system_composition()` refuses to publish "
            "this phase; SYS-34 records knowledge after successful integration.",
        ]
    return "\n".join(out)


def render_readiness_matrix(selection: Mapping[str, Any]) -> str:
    """Section 4. SYS-4's thirteen factors as a real matrix -- one row per
    selected subsystem, one column per factor, plus the derived verdict. A
    per-subsystem verdict alone would not let a reader see that three
    subsystems are PARTIAL for three DIFFERENT reasons."""
    rows = list(selection.get("selected_rows") or [])
    header = "| Subsystem | " + " | ".join(sd.READINESS_FACTORS) + " | READINESS |"
    lines = [header, "|" + "---|" * (len(sd.READINESS_FACTORS) + 2)]
    for row in rows:
        factors = row.get("readiness_factors") or {}
        cells = [str(row.get("subsystem"))]
        for factor in sd.READINESS_FACTORS:
            cells.append(str((factors.get(factor) or {}).get("status", sd.UNKNOWN)))
        cells.append(str(row.get("readiness") or sd.UNKNOWN))
        lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    if not rows:
        lines.append("| _no subsystem was selected_ |"
                     + " |" * (len(sd.READINESS_FACTORS) + 1))
    out = ["\n".join(lines), "",
           "Statuses: PRESENT / ABSENT / BLOCKED / UNKNOWN. `ABSENT` means the tree was "
           "walked and nothing matched; `UNKNOWN` means it could not be walked. "
           "Collapsing those two is how an unexaminable environment starts reporting as "
           "an incomplete one.", ""]
    for row in rows:
        detail = row.get("readiness_detail") or {}
        out.append(f"- **{row.get('subsystem')}** -> {detail.get('readiness')}: "
                   f"{detail.get('evidence')}")
    return "\n".join(out)


def render_per_subsystem_architecture(synthesis: Mapping[str, Any]) -> str:
    """Section 5. SYS-6's field table PER SUBSYSTEM.

    `saa.render_architecture_table()` renders ONE subsystem's fields; this
    section is the per-subsystem list SYS-38 asks for, so it calls that
    renderer once per subsystem rather than inventing a combined table whose
    columns could disagree with it. SYS-5's isolation flag is carried at the
    top because a synthesis assembled without it would describe subsystems
    that were allowed to read each other's trees."""
    results = list(synthesis.get("per_subsystem") or [])
    isolation = synthesis.get("isolation") or {}
    out = [f"SYS-5 isolation checked: {isolation.get('checked')} -- "
           f"{isolation.get('rule', '')}",
           "",
           f"Cross-subsystem conflicts found afterward: "
           f"{(synthesis.get('summary') or {}).get('cross_subsystem_conflicts', 0)} "
           f"({(synthesis.get('summary') or {}).get('duplicate_active_drivers', 0)} "
           "duplicate active driver(s))",
           ""]
    if not results:
        out.append("_No subsystem analysis is present in this synthesis._")
    for result in results:
        coverage = result.get("coverage") or {}
        out += [
            f"### {result.get('subsystem_id')}",
            "",
            f"- environment root: {result.get('environment_root') or '(none)'}",
            f"- fields derived from real artifacts: {coverage.get('derived')}/"
            f"{coverage.get('fields_total')} "
            f"({coverage.get('not_available')} NOT_AVAILABLE, "
            f"{coverage.get('not_applicable')} NOT_APPLICABLE)",
            f"- artifacts read: {len(result.get('read_paths') or [])}",
            "",
            saa.render_architecture_table(result),
            "",
        ]
    return "\n".join(out)


def render_command_txt_analysis(synthesis: Mapping[str, Any]) -> str:
    """Section 6. SYS-7's per-subsystem command.txt analysis, rendered by
    `reference_pattern_audit.format_command_analysis()` -- the function that
    owns the shape SYS-7's analysis really has. A subsystem whose environment
    supplied NO command file says so: SYS-7 calls the analysis mandatory, so
    its absence is a finding about that subsystem, not an omission here."""
    out: List[str] = []
    for result in synthesis.get("per_subsystem") or []:
        sid = result.get("subsystem_id")
        analyses = list(result.get("command_analyses") or [])
        out += [f"### {sid}", ""]
        if not analyses:
            out += ["_No command.txt was found in this subsystem's environment tree._ "
                    "SYS-7 makes this analysis mandatory, so this is a finding about "
                    "the subsystem, not an omission in this report.", ""]
            continue
        for analysis in analyses:
            out += [f"`{analysis.get('command_file')}`", "", "```",
                    rpa.format_command_analysis(analysis), "```", ""]
    if not out:
        return _not_supplied(
            "The SYS-5..8 per-subsystem analysis",
            "run `subsystem_architecture_analysis.analyze_selected_subsystems()` and "
            "pass its `synthesis`")
    return "\n".join(out)


def render_duplicate_resource_analysis(resource_analysis: Mapping[str, Any]) -> str:
    """Section 9. SYS-10/SYS-11's cross-subsystem duplicate comparison, read
    off that layer's own relationship rows. An empty relationship list is an
    absence of CANDIDATES, never a proof that no duplicate exists, and the note
    says so -- the two read identically in a table and only one is a clean
    result."""
    summary = resource_analysis.get("summary") or {}
    out = [
        f"{summary.get('duplicate_candidate_count', 0)} cross-subsystem duplicate "
        f"candidate(s) compared; relationships by class: "
        f"{summary.get('relationships_by_class', {})}",
        "",
    ]
    relationships = list(resource_analysis.get("relationships") or [])
    if relationships:
        out.append(sri.render_relationship_table(relationships))
    else:
        out.append("_No cross-subsystem pair had a single agreeing identity signal._ "
                   "That is an absence of candidates, not a proof that no duplicate "
                   "exists.")
    promotions = list(resource_analysis.get("promotion_evaluation") or [])
    if promotions:
        out += ["", "### SYS-13 shared-VIP promotion evaluation", ""]
        for promotion in promotions:
            out.append(f"- [{promotion['decision']}] {promotion['resource_a']} vs "
                       f"{promotion['resource_b']}: {promotion['reason']}")
    return "\n".join(out)


def render_active_driver_conflicts(resource_analysis: Mapping[str, Any],
                                   integration_plan: Mapping[str, Any]) -> str:
    """Section 10. SYS-12's rule and its decisions, plus the registry entries
    that ended up carrying a DRIVER_CONFLICT status. Both are read; this
    section decides nothing, which matters because SYS-42's own golden rule
    ("one physical interface must not have multiple uncoordinated active
    drivers") is the thing being reported on."""
    rule = resource_analysis.get("active_driver_conflict_rule") or {}
    out = [rule.get("rule", "(no SYS-12 rule recorded)"), ""]
    decisions = list(rule.get("decisions") or [])
    if decisions:
        for decision in decisions:
            out.append(f"- [{decision['integration_status']}] {decision['scope']} "
                       f"{decision['resources']}: {decision['reason']}")
    else:
        out.append("- no active-driver conflict detected across or within the selected "
                   "subsystems")
    out += ["", f"Preferred model: {rule.get('preferred_model', '-')}", ""]

    registry = integration_plan.get("system_resource_registry") or {}
    conflicted = [e for e in (registry.get("entries") or [])
                  if e.get("conflict_status") != srr.CONFLICT_NONE]
    header = "| Resource | Type | Conflict status | Reuse decision | Owner | Consumers |"
    lines = [header, "|" + "---|" * 6]
    for entry in conflicted:
        lines.append("| " + " | ".join(_cell(v) for v in (
            entry["resource_id"], entry.get("resource_type"),
            entry.get("conflict_status"), entry.get("reuse_decision"),
            entry.get("owner"),
            ", ".join(entry.get("consumer_subsystems") or []) or "-")) + " |")
    if not conflicted:
        lines.append("| _no SYS-15 registry entry carries a conflict status_ |"
                     + " |" * 5)
    out.append("\n".join(lines))
    return "\n".join(out)


def render_shared_resource_proposal(integration_plan: Mapping[str, Any],
                                    scheduling_plan: Mapping[str, Any]) -> str:
    """Section 11. What would be shared, and through what -- the registry's own
    reuse decisions joined to SYS-24's proposed access points. Every access
    point is PLANNED_NOT_IMPLEMENTED, and the status column carries that on
    every row rather than in a footnote."""
    registry = integration_plan.get("system_resource_registry") or {}
    proposed = [e for e in (registry.get("entries") or [])
                if e.get("reuse_decision") not in (srr.KEEP_INDEPENDENT,)]
    header = ("| Resource | Type | Reuse decision | System owner | Consumers | "
              "Shared |")
    lines = [header, "|" + "---|" * 6]
    for entry in proposed:
        lines.append("| " + " | ".join(_cell(v) for v in (
            entry["resource_id"], entry.get("resource_type"),
            entry.get("reuse_decision"), entry.get("owner"),
            ", ".join(entry.get("consumer_subsystems") or []) or "-",
            entry.get("shared"))) + " |")
    if not proposed:
        lines.append("| _every resource stays independent; nothing is proposed shared_ |"
                     + " |" * 5)
    out = ["\n".join(lines), "", "### SYS-24 proposed shared access points", "",
           ssp.render_shared_resource_scheduling_table(
               scheduling_plan.get("shared_resource_scheduling") or {}),
           "",
           f"Access points named: "
           f"{(scheduling_plan.get('summary') or {}).get('shared_access_points_named', 0)}; "
           f"built: "
           f"{(scheduling_plan.get('summary') or {}).get('shared_access_points_built', 0)}. "
           "Every proposal is a recommendation for a human; nothing is resolved here."]
    return "\n".join(out)


def render_scoreboard_integration_plan(scheduling_plan: Mapping[str, Any]) -> str:
    """Section 17. SYS-26's plan, projected from the plan document's own rows.

    This renderer lives here rather than in `system_scheduling_plan` because
    section 17 is the only consumer of a scoreboard TABLE; the plan module
    already renders every other part of its own document. Nothing is
    recomputed: `subsystem_scoreboard_modified` and
    `replaced_by_monolithic_scoreboard` are read straight off the rows that
    `assert_no_emitted_artifacts()` already refuses to let be True."""
    scoreboards = scheduling_plan.get("scoreboard_integration") or {}
    header = "| Subsystem | Disposition | Subsystem scoreboards | Modified | Replaced |"
    lines = [header, "|" + "---|" * 5]
    for row in scoreboards.get("subsystems") or []:
        lines.append("| " + " | ".join(_cell(v) for v in (
            row["subsystem_id"], row.get("disposition"),
            ", ".join(s["resource_id"] for s in (row.get("subsystem_scoreboards") or []))
            or "-",
            row.get("subsystem_scoreboard_modified"),
            row.get("replaced_by_monolithic_scoreboard"))) + " |")
    if len(lines) == 2:
        lines.append("| _no subsystem was in scope for scoreboard planning_ |" + " |" * 4)
    layer = scoreboards.get("system_correlation_layer") or {}
    out = ["\n".join(lines), "", "### System correlation layer", "",
           f"- name: `{layer.get('name', '-')}`",
           f"- status: **{layer.get('status', '-')}**",
           f"- sits above: {layer.get('sits_above') or '(nothing)'}",
           f"- replaces subsystem scoreboards: "
           f"{layer.get('replaces_subsystem_scoreboards')}",
           f"- blocked by: {layer.get('blocked_by', '-')}",
           "", f"{layer.get('content_boundary', '')}"]
    requirement = layer.get("topology_descriptor_requirement") or []
    if requirement:
        out += ["", "### Cross-subsystem topology descriptor", ""]
        for part in requirement:
            out.append(f"- `{part.get('part')}`: {part.get('status')} -- "
                       f"{part.get('reason', '')}")
    return "\n".join(out)


def render_command_synthesis_plan(command_plan: Mapping[str, Any],
                                  scheduling_plan: Mapping[str, Any],
                                  topology_analysis: Mapping[str, Any]) -> str:
    """Section 18. The SYSTEM command.txt SYNTHESIS PLAN -- and the section
    where a reader is most likely to expect command text. There is none. The
    plan is the routing table, the IR, the collision list and the scenario
    block shapes; every one of those describes what a System command.txt WOULD
    contain and none of them is it."""
    summary = command_plan.get("summary") or {}
    scenarios = topology_analysis.get("system_scenario_model") or {}
    out = [
        f"{summary.get('system_commands', 0)} System command(s) planned; "
        f"{summary.get('ir_entries', 0)} IR entr(y/ies); "
        f"{summary.get('collisions', 0)} collision(s) "
        f"({summary.get('blocking_collisions', 0)} blocking); "
        f"{(scenarios.get('summary') or {}).get('scenario_count', 0)} scenario shape(s).",
        "",
        "**No System command.txt is written by this report or by any module it calls.** "
        f"System command.txt written: "
        f"{(scenarios.get('summary') or {}).get('system_command_txt_written', 0)}; "
        f"scenario bodies generated: "
        f"{(scenarios.get('summary') or {}).get('scenario_bodies_generated', 0)}. "
        "Generating them is SYS-40 and requires a separate explicit human approval.",
        "",
        "### SYS-19 command routing plan",
        "",
        scp.render_routing_table(command_plan.get("system_command_routing_plan") or {}),
        "",
        "### SYS-21 System Command IR",
        "",
        scp.render_command_ir_table(command_plan.get("system_command_ir") or {}),
        "",
        "### SYS-22 command collisions",
        "",
        scp.render_collision_table(command_plan.get("command_collisions") or {}),
        "",
        "### SYS-23 initialization deduplication",
        "",
        ssp.render_initialization_deduplication_table(
            scheduling_plan.get("initialization_deduplication") or {}),
        "",
        "### SYS-30 scenario block shapes",
        "",
        sta.render_scenario_model_table(scenarios),
    ]
    return "\n".join(out)


def render_system_architecture(command_plan: Mapping[str, Any],
                               scheduling_plan: Mapping[str, Any]) -> str:
    """Section 19. SYS-18's architecture tree plus SYS-25's parallelism model.

    Every node of the tree carries its own status (`PLANNED_NOT_IMPLEMENTED`,
    `PROPOSED_FROM_REGISTRY`, `SELECTED_SUBSYSTEM_ENV`, ...) -- the tree is a
    description of a system that does not exist yet, and a node status is how a
    reader tells a real reused subsystem environment from a proposal."""
    architecture = command_plan.get("system_architecture") or {}
    out = ["```", scp.render_architecture_tree(architecture), "```", ""]
    counts = architecture.get("summary") or {}
    if counts:
        out += [f"Node statuses: {counts.get('by_status', counts)}", ""]
    out += ["### SYS-25 parallelism model", "",
            ssp.render_parallelism_table(scheduling_plan.get("parallelism_model") or {}),
            "",
            "### SYS-27 cross-subsystem flows", "",
            ssp.render_cross_subsystem_flow_table(
                scheduling_plan.get("cross_subsystem_checking") or {})]
    return "\n".join(out)


# ===========================================================================
# Section 20 -- OPEN QUESTIONS
# ===========================================================================

def collect_open_questions(*,
                           selection: Optional[Mapping[str, Any]] = None,
                           resource_analysis: Optional[Mapping[str, Any]] = None,
                           integration_plan: Optional[Mapping[str, Any]] = None,
                           command_plan: Optional[Mapping[str, Any]] = None,
                           scheduling_plan: Optional[Mapping[str, Any]] = None,
                           topology_analysis: Optional[Mapping[str, Any]] = None,
                           readiness: Optional[Mapping[str, Any]] = None,
                           version_pin: Optional[Mapping[str, Any]] = None,
                           ) -> List[Dict[str, Any]]:
    """Every unresolved decision this Phase-1 analysis surfaced, COLLECTED from
    the layers that found them.

    Nothing is escalated from here. The layers that detect a conflict already
    file it through `source_authority.escalate_conflict()` into the real
    question queue -- `system_topology_analysis.escalate_address_conflicts()`
    and `system_command_plan`'s own escalation -- and those escalations are
    idempotent because their Q-ids derive from the finding. A report that
    re-escalated on every render would grow the queue every time somebody
    printed it. So this collects the already-filed Q-ids and the items still
    awaiting a decision, and cites where each came from."""
    questions: List[Dict[str, Any]] = []

    def add(source: str, subject: str, question: str, blocking: bool,
            question_id: str = "") -> None:
        questions.append({"source": source, "subject": subject, "question": question,
                          "blocking": blocking, "question_id": question_id})

    if selection is not None:
        if selection.get("refusal_reason"):
            add("SYS-1 selection", ", ".join(selection.get("selected_subsystems") or [])
                or "(empty selection)",
                f"selection is not admissible ({selection['refusal_reason']}); which "
                "subsystems should this composition really contain?", True)
        for row in selection.get("not_ready") or []:
            add("SYS-2 existence", row["subsystem"],
                f"{row['subsystem']} is {row['existence_class']} / {row['readiness']}; "
                f"next action: {row['next_action']}", True)
        for conflict in selection.get("blocking_conflicts") or []:
            add("SYS-1 candidate set", ", ".join(conflict.get("subsystems") or []),
                str(conflict.get("reason") or "candidate-set conflict"), True)

    if resource_analysis is not None:
        for escalation in resource_analysis.get("configuration_conflict_escalations") or []:
            add("SYS-11 configuration conflict", str(escalation.get("field")),
                f"{(escalation.get('conflict') or {}).get('verdict')} -- "
                f"{(escalation.get('conflict') or {}).get('rule')}", False,
                str(escalation.get("question_id") or ""))
        rule = resource_analysis.get("active_driver_conflict_rule") or {}
        for decision in rule.get("decisions") or []:
            if decision.get("integration_status") in (
                    srr.INTEGRATION_BLOCKED_DRIVER_CONFLICT, srr.INTEGRATION_HELD):
                add("SYS-12 active driver conflict", str(decision.get("resources")),
                    str(decision.get("reason") or ""), True)

    if integration_plan is not None:
        registry = integration_plan.get("system_resource_registry") or {}
        for entry in registry.get("entries") or []:
            if entry.get("conflict_status") == srr.CONFLICT_NONE:
                continue
            add("SYS-15 registry", entry["resource_id"],
                f"conflict_status={entry['conflict_status']}, "
                f"reuse_decision={entry.get('reuse_decision')}: "
                f"{entry.get('reuse_decision_reason', '')}",
                entry.get("conflict_status") == srr.CONFLICT_DRIVER)

    if command_plan is not None:
        for collision in (command_plan.get("command_collisions") or {}).get(
                "collisions") or []:
            add("SYS-22 command collision", str(collision.get("subject")),
                f"{collision.get('collision_type')}: {collision.get('detail', '')}",
                bool(collision.get("blocks_integration")),
                str(collision.get("collision_id") or ""))

    if scheduling_plan is not None:
        scheduling = scheduling_plan.get("shared_resource_scheduling") or {}
        for row in scheduling.get("entries") or []:
            if row.get("scheduling_disposition") != ssp.SCHED_NOT_SCHEDULABLE:
                continue
            add("SYS-24 scheduling", str(row.get("shared_resource_key")),
                str(row.get("scheduling_reason") or ""), True)

    if topology_analysis is not None:
        address = topology_analysis.get("address_map_reconciliation") or {}
        for escalation in address.get("escalations") or []:
            add("SYS-28 address conflict", str(escalation.get("subject") or ""),
                "cross-subsystem address overlap escalated through source_authority",
                True, str(escalation.get("question_id") or ""))
        for row in address.get("overlaps") or []:
            if row.get("verdict") != sta.ADDRESS_OVERLAP_CONFLICT:
                continue
            add("SYS-28 address conflict",
                f"{row['subsystem_a']}:{row['region_a']} ~ "
                f"{row['subsystem_b']}:{row['region_b']}",
                str(row.get("basis") or ""), True)
        clock_reset = topology_analysis.get("clock_reset_comparison") or {}
        for row in (list(clock_reset.get("clock_comparisons") or [])
                    + list(clock_reset.get("reset_comparisons") or [])):
            if not str(row.get("verdict", "")).startswith("CONFLICTING"):
                continue
            add("SYS-29 clock/reset", f"{row['subsystem_a']} ~ {row['subsystem_b']}",
                f"{row['verdict']}: {row.get('basis', '')}", True)

    if version_pin is not None:
        for subsystem in version_pin.get("unpinned_subsystems") or []:
            add("SYS-35 version pinning", subsystem,
                "no registered release_sha, so this composition cannot be restored and "
                "SYS-36 change impact is undecidable for it", False)

    if readiness is not None:
        for row in readiness.get("inputs") or []:
            if row["status"] == sr.INPUT_CLEAR:
                continue
            add("SYS-37 readiness input", row["input"],
                f"{row['status']}: {row['evidence']}",
                row["status"] == sr.INPUT_BLOCKED)

    questions.sort(key=lambda q: (not q["blocking"], q["source"], q["subject"]))
    return questions


def render_open_questions(questions: Sequence[Mapping[str, Any]]) -> str:
    header = "| Blocking | Source | Subject | Question | Filed as |"
    lines = [header, "|" + "---|" * 5]
    for question in questions:
        lines.append("| " + " | ".join(_cell(v) for v in (
            "YES" if question["blocking"] else "-", question["source"],
            question["subject"], question["question"],
            question.get("question_id") or "-")) + " |")
    if len(lines) == 2:
        lines.append("| _no open question was surfaced by this analysis_ |" + " |" * 4)
    blocking = sum(1 for q in questions if q["blocking"])
    return "\n".join([
        f"{len(questions)} open question(s), {blocking} of them blocking.",
        "",
        "\n".join(lines),
        "",
        "Conflicts detected by SYS-11/SYS-22/SYS-28 are filed into the real question "
        "queue by those layers through `source_authority.escalate_conflict()`. This "
        "section COLLECTS them; rendering this report files nothing.",
    ])


# ===========================================================================
# Section 22 -- USER REVIEW GATE / SYS-39
# ===========================================================================

def render_stop_condition() -> str:
    """SYS-39's ten lines, exactly, and nothing between them."""
    return "\n".join(SYS39_STOP_LINES)


def assert_stop_condition_exact(text: str) -> None:
    """SYS-39 says "report exactly". Verify a candidate block against the ten
    lines, in order, with nothing interleaved -- this is the sentence that
    tells a human the harness has stopped, and a paraphrase of it is a
    different sentence."""
    lines = [line.strip() for line in str(text or "").strip().splitlines()
             if line.strip()]
    if lines != list(SYS39_STOP_LINES):
        raise SystemPhase1ReportError("SYS39_STOP_CONDITION_NOT_EXACT", {
            "found": lines, "required": list(SYS39_STOP_LINES)})


def render_user_review_gate(readiness: Optional[Mapping[str, Any]],
                            questions: Sequence[Mapping[str, Any]]) -> str:
    """Section 22. The gate itself: what a human is being asked to approve, and
    SYS-39's stop text verbatim.

    The stop is UNCONDITIONAL. A READY verdict and a BLOCKED one produce the
    same ten lines, because SYS-39's stop is about who decides, not about how
    the analysis came out."""
    blocking = [q for q in questions if q["blocking"]]
    verdict = (readiness or {}).get("system_readiness", sd.UNKNOWN)
    out = [
        f"System readiness: **{verdict}**. Blocking open questions: {len(blocking)}.",
        "",
        "What approval would authorize (SYS-40, and nothing in this report has done "
        "any of it): create/update the System-Level environment; reuse the selected "
        "subsystem environments; create/update the System Resource Registry; resolve "
        "approved shared agents; implement the System virtual sequencer/router; "
        "command routing/adapters; generate the System command.txt; connect subsystem "
        "scoreboards; add cross-subsystem correlation; integrate build/filelists/"
        "config; static checks; build; verify; WAVE=1; fsdbreport; targeted/System "
        "regression; benchmark; signoff evidence; PR; Human Review. Never direct-push "
        "main.",
        "",
        "This gate is not satisfied by this report's own verdict. It is satisfied only "
        "by an explicit human approval.",
        "",
        "```",
        render_stop_condition(),
        "```",
    ]
    if blocking:
        out += ["", "Blocking items a reviewer must decide first:", ""]
        for question in blocking:
            out.append(f"- [{question['source']}] {question['subject']}: "
                       f"{question['question']}")
    return "\n".join(out)


# ===========================================================================
# Composition
# ===========================================================================

def build_system_phase1_report(*,
                               selection: Optional[Mapping[str, Any]] = None,
                               synthesis: Optional[Mapping[str, Any]] = None,
                               resource_analysis: Optional[Mapping[str, Any]] = None,
                               integration_plan: Optional[Mapping[str, Any]] = None,
                               command_plan: Optional[Mapping[str, Any]] = None,
                               scheduling_plan: Optional[Mapping[str, Any]] = None,
                               topology_analysis: Optional[Mapping[str, Any]] = None,
                               regression_plan: Optional[Mapping[str, Any]] = None,
                               change_impact: Optional[Mapping[str, Any]] = None,
                               version_pin: Optional[Mapping[str, Any]] = None,
                               readiness: Optional[Mapping[str, Any]] = None,
                               knowledge_center_record: Optional[Mapping[str, Any]] = None,
                               ) -> Dict[str, Any]:
    """SYS-38's twenty-two sections, assembled from artifacts other modules
    already computed.

    Every argument is optional and every omission renders a visible NOT
    SUPPLIED note naming the function that would fill it -- a section is never
    silently dropped, because a reader told there are twenty-two sections uses
    that to notice one is missing.

    Nothing here recomputes anything. Sections 5, 7, 8, 12-19 are the EXISTING
    SYS-5..30 renderers called in SYS-38's mandated order."""
    questions = collect_open_questions(
        selection=selection, resource_analysis=resource_analysis,
        integration_plan=integration_plan, command_plan=command_plan,
        scheduling_plan=scheduling_plan, topology_analysis=topology_analysis,
        readiness=readiness, version_pin=version_pin)

    missing_selection = _not_supplied(
        "The SYS-1 selection",
        "run `subsystem_discovery.require_explicit_selection(root, selected)` and pass "
        "it as `selection`")
    missing_synthesis = _not_supplied(
        "The SYS-5..8 per-subsystem analysis",
        "run `subsystem_architecture_analysis.analyze_selected_subsystems()` and pass "
        "its `synthesis`")
    missing_resources = _not_supplied(
        "The SYS-9..14 cross-subsystem resource analysis",
        "run `system_resource_inventory.analyze_selected_subsystem_resources()` and "
        "pass its `resource_analysis`")
    missing_integration = _not_supplied(
        "The SYS-15..17 integration plan",
        "run `system_resource_registry.plan_system_integration()` and pass its "
        "`integration_plan`")
    missing_command = _not_supplied(
        "The SYS-18..22 command plan",
        "run `system_command_plan.plan_system_commands()` and pass its `command_plan`")
    missing_scheduling = _not_supplied(
        "The SYS-23..27 scheduling plan",
        "run `system_scheduling_plan.plan_system_scheduling()` and pass its "
        "`scheduling_plan`")
    missing_topology = _not_supplied(
        "The SYS-28..30 topology analysis",
        "run `system_topology_analysis.analyze_system_topology()` and pass its "
        "`topology_analysis`")

    bodies: Dict[int, str] = {
        1: (render_selected_subsystems(selection) if selection is not None
            else missing_selection),
        2: (render_existence_check(selection) if selection is not None
            else missing_selection),
        3: (render_knowledge_center_status(selection, knowledge_center_record)
            if selection is not None else missing_selection),
        4: (render_readiness_matrix(selection) if selection is not None
            else missing_selection),
        5: (render_per_subsystem_architecture(synthesis) if synthesis is not None
            else missing_synthesis),
        6: (render_command_txt_analysis(synthesis) if synthesis is not None
            else missing_synthesis),
        7: (scc.format_contract_report(synthesis.get("contract_set") or {})
            if synthesis is not None else missing_synthesis),
        8: (sri.render_resource_inventory_table(resource_analysis["inventory"])
            if resource_analysis is not None else missing_resources),
        9: (render_duplicate_resource_analysis(resource_analysis)
            if resource_analysis is not None else missing_resources),
        10: (render_active_driver_conflicts(resource_analysis, integration_plan or {})
             if resource_analysis is not None else missing_resources),
        11: (render_shared_resource_proposal(integration_plan, scheduling_plan or {})
             if integration_plan is not None else missing_integration),
        12: (srr.render_registry_table(
            integration_plan.get("system_resource_registry") or {})
            if integration_plan is not None else missing_integration),
        13: (srr.render_subsystem_integration_matrix(
            integration_plan.get("subsystem_integration_matrix") or {})
            if integration_plan is not None else missing_integration),
        14: (srr.render_vip_deduplication_matrix(
            integration_plan.get("vip_agent_deduplication_matrix") or {})
            if integration_plan is not None else missing_integration),
        15: (sta.render_address_overlap_table(
            topology_analysis.get("address_map_reconciliation") or {})
            if topology_analysis is not None else missing_topology),
        16: (sta.render_clock_reset_table(
            topology_analysis.get("clock_reset_comparison") or {})
            if topology_analysis is not None else missing_topology),
        17: (render_scoreboard_integration_plan(scheduling_plan)
             if scheduling_plan is not None else missing_scheduling),
        18: (render_command_synthesis_plan(command_plan, scheduling_plan or {},
                                           topology_analysis or {})
             if command_plan is not None else missing_command),
        19: (render_system_architecture(command_plan, scheduling_plan or {})
             if command_plan is not None else missing_command),
        20: render_open_questions(questions),
        21: (sr.format_system_readiness_report(readiness, version_pin,
                                               knowledge_center_record)
             if readiness is not None else _not_supplied(
                 "The SYS-37 readiness derivation",
                 "run `system_readiness.derive_system_readiness()` and pass it as "
                 "`readiness`")),
        22: render_user_review_gate(readiness, questions),
    }
    # Sections 15/16 add their own SYS-33/36 appendix: the regression plan is
    # not one of SYS-38's twenty-two headings, so it is reported under SYS-21
    # SYSTEM READINESS rather than smuggled in as a twenty-third section.
    if regression_plan is not None:
        bodies[21] = "\n\n".join([
            bodies[21], "---", "",
            srp.format_system_regression_report(regression_plan, change_impact)])

    return {
        "schema_version": SCHEMA_VERSION,
        "sections": [{"number": number, "title": title, "body": bodies[number]}
                     for number, title in SYS38_SECTIONS],
        "open_questions": questions,
        "system_readiness": (readiness or {}).get("system_readiness", sd.UNKNOWN),
        "stop_condition": render_stop_condition(),
        "summary": {
            "section_count": len(SYS38_SECTIONS),
            "sections_not_supplied": sorted(
                number for number, _ in SYS38_SECTIONS
                if bodies[number].startswith("_NOT SUPPLIED._")),
            "open_questions": len(questions),
            "blocking_open_questions": sum(1 for q in questions if q["blocking"]),
            "system_readiness": (readiness or {}).get("system_readiness", sd.UNKNOWN),
            "implementation_started": False,
        },
        "phase_boundary": srp.PHASE_BOUNDARY,
    }


def section_body(report: Mapping[str, Any], number: int) -> str:
    for section in report.get("sections") or []:
        if section["number"] == number:
            return section["body"]
    raise SystemPhase1ReportError("SYS38_SECTION_NOT_PRESENT", {
        "number": number,
        "present": [s["number"] for s in (report.get("sections") or [])]})


def render_system_phase1_report(report: Mapping[str, Any], *,
                                title: str = "System-Level Verification Integration "
                                             "-- Phase-1 Report") -> str:
    """The whole report, in SYS-38's exact order, self-checked.

    Three guards on the FINISHED text before it is returned: the twenty-two
    headings really are present, once each, in order; the text contains no
    `bind` statement; and it contains no emittable SystemVerilog."""
    summary = report["summary"]
    lines = [
        f"# {title}",
        "",
        f"SYS-38 mandates this exact twenty-two-item order "
        f"(`{SYSTEM_LEVEL_DOC}:4461-4484`). Every section is present; one whose input "
        "was not supplied says so rather than being omitted.",
        "",
        f"System readiness: **{summary['system_readiness']}** | "
        f"open questions: {summary['open_questions']} "
        f"({summary['blocking_open_questions']} blocking) | "
        f"sections not supplied: {summary['sections_not_supplied'] or 'none'} | "
        f"implementation started: {summary['implementation_started']}",
        "",
    ]
    for section in report["sections"]:
        lines += [_heading(section["number"], section["title"]), "",
                  section["body"], ""]
    lines += ["---", "", report["phase_boundary"], ""]
    text = "\n".join(lines)
    assert_report_section_order(text)
    assert_no_bind_statement(text)
    ssa.assert_no_emittable_sv(text, label="SYS-38 Phase-1 report")
    assert_stop_condition_exact(report["stop_condition"])
    return text


def assert_report_section_order(text: str) -> None:
    """SYS-38's "produce exactly" order, verified against the FINISHED text.

    Checking the source tuple would only prove the tuple agrees with itself. A
    heading a section body accidentally swallowed, duplicated or emitted out of
    order is a real failure mode this catches and that one would not."""
    body = str(text or "")
    positions: List[tuple] = []
    for number, title in SYS38_SECTIONS:
        heading = _heading(number, title)
        count = body.count("\n" + heading + "\n") + (
            1 if body.startswith(heading + "\n") else 0)
        if count == 0:
            raise SystemPhase1ReportError("SYS38_SECTION_MISSING", {
                "number": number, "title": title, "expected_heading": heading,
                "hint": "SYS-38 mandates all twenty-two sections; a section with no "
                        "input must render a NOT SUPPLIED note, never be omitted"})
        if count > 1:
            raise SystemPhase1ReportError("SYS38_SECTION_DUPLICATED", {
                "number": number, "title": title, "occurrences": count})
        positions.append((number, 0 if body.startswith(heading + "\n")
                          else body.index("\n" + heading + "\n")))
    ordered = [n for n, _ in sorted(positions, key=lambda p: p[1])]
    expected = [n for n, _ in SYS38_SECTIONS]
    if ordered != expected:
        raise SystemPhase1ReportError("SYS38_SECTIONS_OUT_OF_ORDER", {
            "found_order": ordered, "required_order": expected})


def produce_phase1_report(root, selected: Sequence[str], *,
                          declared: Optional[Mapping[str, Any]] = None,
                          knowledge_center_client: Any = None,
                          inventory_overlay_path=None,
                          question_store: Any = None,
                          head_rev: str = "HEAD",
                          ) -> Dict[str, Any]:
    """Front door: SYS-1 selection through SYS-37 readiness (all reused via
    `system_readiness.assess_system_readiness()`), then SYS-38's twenty-two
    sections and SYS-39's stop.

    Returns the assembled report, its rendered text, and the stop condition.
    Writes nothing anywhere and publishes nothing to the Knowledge Center."""
    result = sr.assess_system_readiness(
        root, selected, declared=declared,
        knowledge_center_client=knowledge_center_client,
        inventory_overlay_path=inventory_overlay_path,
        question_store=question_store, head_rev=head_rev)
    report = build_system_phase1_report(
        selection=result["selection"], synthesis=result["synthesis"],
        resource_analysis=result["resource_analysis"],
        integration_plan=result["integration_plan"],
        command_plan=result["command_plan"],
        scheduling_plan=result["scheduling_plan"],
        topology_analysis=result["topology_analysis"],
        regression_plan=result["regression_plan"],
        change_impact=result["change_impact"],
        version_pin=result["version_pin"],
        readiness=result["system_readiness"],
        knowledge_center_record=result["knowledge_center_record"])
    return {**result, "phase1_report": report,
            "phase1_report_text": render_system_phase1_report(report),
            "stop_condition": render_stop_condition()}


def _assert_section_set_matches_the_requirement() -> None:
    """SYS-38 lists twenty-two numbered items. Import-time check that the tuple
    still has exactly those twenty-two, numbered 1..22 with no repeat, so a
    future edit that adds a twenty-third has to change the requirement's own
    reading deliberately rather than by appending to a list."""
    numbers = [n for n, _ in SYS38_SECTIONS]
    titles = [t for _, t in SYS38_SECTIONS]
    if numbers != list(range(1, 23)) or len(set(titles)) != 22:
        raise SystemPhase1ReportError("SYS38_SECTION_SET_CHANGED", {
            "numbers": numbers, "expected": list(range(1, 23)),
            "duplicate_titles": sorted({t for t in titles if titles.count(t) > 1})})
    if len(SYS39_STOP_LINES) != 10:
        raise SystemPhase1ReportError("SYS39_STOP_LINE_SET_CHANGED", {
            "lines": list(SYS39_STOP_LINES), "expected_count": 10})


_assert_section_set_matches_the_requirement()
