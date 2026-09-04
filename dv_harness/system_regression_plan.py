"""SYS-33 and SYS-36 of the System-Level Verification Integration workflow: the
SYSTEM REGRESSION plan, and the subsystem-git-change -> System CHANGE IMPACT
producer that feeds it.

WHAT THIS MODULE IS NOT
-----------------------
Stated first, because it is the boundary this whole workflow exists inside.
Nothing here RUNS a regression, submits an LSF job, writes a testlist, writes a
System command.txt, or emits a scenario body. SYS-33's output is a PLAN whose
every entry carries `execution_status = PLANNED_NOT_EXECUTED`, and
`assert_nothing_executed()` refuses a plan that says otherwise. Executing it is
SYS-40, behind a separate explicit human approval this workflow does not
obtain.

SYS-36 likewise READS git and READS the SYS-15/21/26/30 artifacts. It writes no
regression selection into `.dv-harness/regression_selection.csv`, does not
touch `change_impact.compute_and_write()`'s artifacts, and never calls
`regression_tiers.record_active_tier()`. The one file it can produce is the
`--impact` JSON `tools/verification_flow/system_level_change_impact_gate.py`
already reads -- and even that only when a caller explicitly asks for it.

WHY A NEW MODULE RATHER THAN AN EXTENSION OF change_impact.py
-------------------------------------------------------------
`change_impact.py` is real, wired (engine.py's `Stage.REGRESSION_SELECT`) and
evidence-grounded, and its SHAPE is exactly right -- so this module reuses its
mechanics rather than copying them:

  * `change_impact.changed_files()` is the ONE git-diff implementation in this
    repo, including its degrade-never-raise contract (NO_GIT / UNKNOWN_BASE /
    UNKNOWN_HEAD / DIFF_FAILED, each with an empty file list that a caller can
    never mistake for "nothing changed"). `_subsystem_diff()` calls it once per
    subsystem with that subsystem's OWN tree as the repo root and its OWN
    registered `release_sha` as the base. There is no second `git diff` here.
  * `change_impact.classify_risk()` supplies the RTL/testbench/doc/metadata
    risk of each changed path. No second path classifier.
  * `regression_tiers.CLASS_TARGETED/DEPENDENCY/SAFETY/MANDATORY_SIGNOFF` is
    the selection-class vocabulary every plan entry carries. A fifth vocabulary
    for the same idea is exactly the duplication this project has already been
    bitten by.

What it cannot be is an extension of that module, and that is structural, not
stylistic. `change_impact.py` operates on ONE repository root, ONE base ref and
a flat `.dv-harness/requirements.csv` trace registry; it has no notion of
subsystem identity, and by design -- `compute_change_impact()`'s inputs are
file paths and requirement rows. SYS-36 asks a different question with a
different arity: N subsystems, N base refs (each subsystem's own registered
release_sha, not one repo-wide base), and a join not against requirements but
against the SYS-15 resource registry, the SYS-21 command IR, the SYS-26
scoreboard plan and the SYS-30 scenario model. Widening `compute_change_impact()`
to take a per-subsystem base would change the meaning of its existing return
value for its existing caller.

WHY "DO NOT BLINDLY CONCATENATE" IS A CHECK, NOT A PROMISE
----------------------------------------------------------
SYS-33's second sentence is its only prohibition, so it gets a real check
rather than a comment. Every plan entry carries a `basis` naming the artifact
and the row it came from, and `concatenation_check` reports the UNIVERSE it
selected from beside the count it selected -- so a plan that took everything is
visibly a plan that took everything. `assert_not_blind_concatenation()` raises
when a plan selected its whole universe while some entry cites no basis at all,
which is the shape a concatenation actually has: everything in, nothing said
about why.

Exclusions are recorded, never silently dropped, for the same reason: a reader
who cannot see what was left out cannot tell a selection from a filter that
happened to match everything.
"""

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from . import change_impact as ci
from . import reference_pattern_audit as rpa
from . import regression_tiers as rt
from . import subsystem_discovery as sd
from . import system_command_plan as scp
from . import system_resource_inventory as sri
from . import system_resource_registry as srr
from . import system_scheduling_plan as ssp
from . import system_topology_analysis as sta
from .qualification import SYSTEM_LEVEL_STATES

SCHEMA_VERSION = "1.0"


# ===========================================================================
# SYS-33 vocabulary
# ===========================================================================

#: SYS-33's own list, verbatim and in the requirement's own order: "Build from
#: known-good subsystem tests, selected command sequences, cross-subsystem
#: scenarios, shared-resource contention, boot/config, interrupt, DMA,
#: stress/concurrency." Eight categories. Held to that sentence by a test.
CAT_KNOWN_GOOD_SUBSYSTEM_TESTS = "KNOWN_GOOD_SUBSYSTEM_TESTS"
CAT_SELECTED_COMMAND_SEQUENCES = "SELECTED_COMMAND_SEQUENCES"
CAT_CROSS_SUBSYSTEM_SCENARIOS = "CROSS_SUBSYSTEM_SCENARIOS"
CAT_SHARED_RESOURCE_CONTENTION = "SHARED_RESOURCE_CONTENTION"
CAT_BOOT_CONFIG = "BOOT_CONFIG"
CAT_INTERRUPT = "INTERRUPT"
CAT_DMA = "DMA"
CAT_STRESS_CONCURRENCY = "STRESS_CONCURRENCY"

SYS33_CATEGORIES: tuple = (
    CAT_KNOWN_GOOD_SUBSYSTEM_TESTS,
    CAT_SELECTED_COMMAND_SEQUENCES,
    CAT_CROSS_SUBSYSTEM_SCENARIOS,
    CAT_SHARED_RESOURCE_CONTENTION,
    CAT_BOOT_CONFIG,
    CAT_INTERRUPT,
    CAT_DMA,
    CAT_STRESS_CONCURRENCY,
)

#: Nothing in this plan runs. The status is on every entry, not only in the
#: summary, because a plan entry copied out of context must still say so.
PLANNED_NOT_EXECUTED = "PLANNED_NOT_EXECUTED"

#: `concatenation_check` verdicts. FULL_UNIVERSE_SELECTED is not a failure --
#: a two-subsystem selection in which everything really is relevant is a real
#: outcome -- but it is the state SYS-33's prohibition is about, so it is named
#: rather than reported as an ordinary selection.
SELECTION_EVIDENCED = "SELECTION_EVIDENCED"
FULL_UNIVERSE_SELECTED = "FULL_UNIVERSE_SELECTED"
EMPTY_UNIVERSE = "EMPTY_UNIVERSE"

#: Why a candidate was excluded. Every exclusion carries one of these plus a
#: free-text detail; "it did not match" is not a reason a reader can check.
EXCL_NOT_KNOWN_GOOD = "NOT_KNOWN_GOOD_NO_QUALIFIED_PASS_EVIDENCE"
EXCL_DEDUP_CANDIDATE = "DEDUPLICATION_CANDIDATE_PENDING_HUMAN_DECISION"
EXCL_NOT_CROSS_SUBSYSTEM = "NOT_CROSS_SUBSYSTEM_SCENARIO"
EXCL_NOT_SCHEDULABLE = "NOT_SCHEDULABLE_PENDING_OWNERSHIP_RESOLUTION"
EXCL_BLOCKING_COLLISION = "BLOCKING_COMMAND_COLLISION_UNRESOLVED"

PHASE_BOUNDARY = (
    "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED -- SYS-33 regression PLANNING and "
    "SYS-36 change-impact ANALYSIS only. No regression is executed, no job is "
    "submitted, no testlist/regression.list is written, and no System command.txt, "
    "scenario body or System-Level UVM source is produced; that is SYS-40 and "
    "requires a separate explicit human approval."
)


class SystemRegressionPlanError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# ===========================================================================
# Guards
# ===========================================================================

def assert_nothing_executed(document: Mapping[str, Any]) -> None:
    """Runtime check of this module's boundary, run on every document
    `build_system_regression_plan()` returns.

    Refuses a plan that reports a run, a submitted job or a written testlist,
    or that carries an entry whose `execution_status` is anything but
    PLANNED_NOT_EXECUTED."""
    for key in ("jobs_submitted", "tests_executed", "testlists_written",
                "artifacts_generated"):
        if document.get(key):
            raise SystemRegressionPlanError("REGRESSION_EXECUTION_ATTEMPTED", {
                "key": key, "value": document.get(key)})
    for entry in document.get("entries") or []:
        if entry.get("execution_status") != PLANNED_NOT_EXECUTED:
            raise SystemRegressionPlanError("REGRESSION_ENTRY_EXECUTED", {
                "entry_id": entry.get("entry_id"),
                "execution_status": entry.get("execution_status")})
        for forbidden in ("result", "verdict", "sim_log", "job_id", "uvm_errors"):
            if forbidden in entry:
                raise SystemRegressionPlanError("REGRESSION_ENTRY_EXECUTED", {
                    "entry_id": entry.get("entry_id"), "key": forbidden})


def assert_not_blind_concatenation(document: Mapping[str, Any]) -> None:
    """SYS-33's own prohibition, as a check on the finished plan.

    A concatenation has a recognisable shape: every candidate is in, and no
    entry says why it is in. Either half alone is legitimate -- a selection
    CAN take everything when everything is genuinely relevant, and a partial
    selection with one thin basis is still a selection -- so this raises only
    on both together, and names the entries with no basis so the caller can
    fix the real problem rather than the verdict."""
    check = document.get("concatenation_check") or {}
    if check.get("verdict") != FULL_UNIVERSE_SELECTED:
        return
    unevidenced = sorted(e["entry_id"] for e in (document.get("entries") or [])
                         if not str(e.get("basis") or "").strip())
    if unevidenced:
        raise SystemRegressionPlanError("BLIND_CONCATENATION_DETECTED", {
            "entries_without_basis": unevidenced,
            "universe": check.get("universe"),
            "selected": check.get("selected"),
            "hint": "SYS-33: do not blindly concatenate all subsystem regressions; "
                    "every included entry must cite the artifact row it came from"})


# ===========================================================================
# SYS-33 -- entry construction
# ===========================================================================

def _entry_id(category: str, *parts: Any) -> str:
    digest = hashlib.sha256("|".join([category, *[str(p) for p in parts]])
                            .encode("utf-8")).hexdigest()[:10].upper()
    return f"SYSREG-{digest}"


def _entry(category: str, *, subsystems: Sequence[str], source_artifact: str,
           source_id: str, description: str, basis: str,
           selection_class: str) -> Dict[str, Any]:
    return {
        "entry_id": _entry_id(category, source_artifact, source_id),
        "category": category,
        "selection_class": selection_class,
        "participating_subsystems": sorted(set(str(s) for s in subsystems if s)),
        "source_artifact": source_artifact,
        "source_id": str(source_id),
        "description": description,
        "basis": basis,
        "execution_status": PLANNED_NOT_EXECUTED,
    }


def _exclusion(category: str, source_id: str, reason: str, detail: str) -> Dict[str, Any]:
    return {"category": category, "source_id": str(source_id),
            "reason": reason, "detail": detail}


def _known_good_subsystem_tests(selection: Mapping[str, Any],
                                registry_entries: Sequence[Mapping[str, Any]],
                                ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
    """SYS-33's first source. "Known-good" is not "present": a subsystem
    qualifies only when its SIGNOFF registration recorded a qualification_state
    the system level accepts (`qualification.SYSTEM_LEVEL_STATES`, the one
    canonical vocabulary -- this module does not invent a second) AND SYS-4's
    own `pass_evidence` factor is PRESENT for it.

    Both halves are required because they answer different questions: the
    registry says a human-gated SIGNOFF happened, the readiness factor says the
    evidence is still on disk to point at. A subsystem failing either is
    EXCLUDED with the failing half named -- never dropped, because "your PCIe
    tests are not in this plan" is precisely the kind of fact a reader must be
    able to see."""
    by_name = {str(e.get("name") or "").lower(): e for e in registry_entries}
    entries: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    rows = list(selection.get("selected_rows") or [])
    for row in rows:
        sid = str(row.get("subsystem") or "")
        reg = by_name.get(sid.lower()) or {}
        qual = reg.get("qualification_state")
        factors = (row.get("readiness_factors") or {})
        pass_evidence = (factors.get("pass_evidence") or {})
        regression_evidence = (factors.get("regression_evidence") or {})
        tests = (factors.get("tests") or {})

        problems: List[str] = []
        if qual not in SYSTEM_LEVEL_STATES:
            problems.append(
                f"registry qualification_state={qual!r} is not one of "
                f"{sorted(SYSTEM_LEVEL_STATES)}")
        if pass_evidence.get("status") != sd.PRESENT:
            problems.append(
                f"SYS-4 pass_evidence factor is {pass_evidence.get('status')!r} "
                f"({pass_evidence.get('evidence')})")
        if problems:
            excluded.append(_exclusion(
                CAT_KNOWN_GOOD_SUBSYSTEM_TESTS, sid, EXCL_NOT_KNOWN_GOOD,
                "; ".join(problems)))
            continue

        cited = list(tests.get("matched") or []) + list(pass_evidence.get("matched") or [])
        entries.append(_entry(
            CAT_KNOWN_GOOD_SUBSYSTEM_TESTS,
            subsystems=[sid],
            source_artifact="subsystem_environment_registry + SYS-4 readiness factors",
            source_id=sid,
            description=f"{sid}'s own already-passing subsystem tests, rerun unmodified "
                        "under the System-Level composition",
            basis=f"qualification_state={qual}; pass_evidence={pass_evidence.get('evidence')}"
                  f"; tests={tests.get('status')}"
                  f"; regression_evidence={regression_evidence.get('status')}"
                  + (f"; cited={cited[:3]}" if cited else ""),
            selection_class=rt.CLASS_MANDATORY,
        ))
    return entries, excluded, len(rows)


def _selected_command_sequences(command_plan: Mapping[str, Any],
                                scheduling_plan: Mapping[str, Any],
                                ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
    """SYS-33's second source, and the one where "selected" carries the most
    weight. The universe is the SYS-21 IR; a command is excluded when SYS-23
    already classified it a deduplication candidate (running both copies is
    precisely what that classification says is undecided) or when SYS-22 found
    a BLOCKING collision on it. Both exclusions are read off those layers'
    verdicts -- this function re-decides neither."""
    ir = command_plan.get("system_command_ir") or {"entries": []}
    dedup = scheduling_plan.get("initialization_deduplication") or {"entries": []}
    collisions = command_plan.get("command_collisions") or {"collisions": []}

    dedup_by_id = {e["system_command_id"]: e for e in (dedup.get("entries") or [])}
    # SYS-22 already decided which collision types stop integration and already
    # remapped every detector's own command ids onto the SYS-21
    # `system_command_id` space (`detect_command_collisions()`'s
    # `contract_id_to_system_id` pass). Both are read here; neither is redone.
    blocked_ids: Set[str] = set()
    for collision in collisions.get("collisions") or []:
        if collision.get("blocks_integration"):
            blocked_ids.update(str(c) for c in (collision.get("commands") or []))

    entries: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    ir_entries = list(ir.get("entries") or [])
    for ir_entry in ir_entries:
        cid = ir_entry["system_command_id"]
        if cid in blocked_ids:
            excluded.append(_exclusion(
                CAT_SELECTED_COMMAND_SEQUENCES, cid, EXCL_BLOCKING_COLLISION,
                "SYS-22 recorded a blocking collision on this command; running it "
                "before that is resolved would exercise the collision, not the system"))
            continue
        classification = dedup_by_id.get(cid) or {}
        if classification.get("deduplication_action") == ssp.DEDUP_CANDIDATE:
            excluded.append(_exclusion(
                CAT_SELECTED_COMMAND_SEQUENCES, cid, EXCL_DEDUP_CANDIDATE,
                f"SYS-23 scope_class={classification.get('scope_class')}: "
                f"{classification.get('deduplication_action_reason')}"))
            continue
        entries.append(_entry(
            CAT_SELECTED_COMMAND_SEQUENCES,
            subsystems=[ir_entry["source_subsystem"]],
            source_artifact="system_command_ir",
            source_id=cid,
            description=f"{ir_entry['source_subsystem']}::{ir_entry['source_command']}",
            basis=f"SYS-21 IR entry; category={ir_entry.get('command_category')}; "
                  f"SYS-23 scope_class={classification.get('scope_class', 'NOT_CLASSIFIED')}",
            selection_class=rt.CLASS_TARGETED,
        ))
    return entries, excluded, len(ir_entries)


def _cross_subsystem_scenarios(topology_analysis: Mapping[str, Any],
                               ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
    """SYS-33's third source: the SYS-30 scenario SHAPES, read as-is. A
    scenario with fewer than two participating subsystems is excluded citing
    the SYS-30 row's own `composition_gate_note` -- the note already says
    `system_level_composition_gate.py` would refuse it, so this is that gate's
    verdict carried forward, not a second opinion."""
    model = topology_analysis.get("system_scenario_model") or {"scenarios": []}
    entries: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    scenarios = list(model.get("scenarios") or [])
    for scenario in scenarios:
        if not scenario.get("cross_subsystem"):
            excluded.append(_exclusion(
                CAT_CROSS_SUBSYSTEM_SCENARIOS, scenario["scenario_id"],
                EXCL_NOT_CROSS_SUBSYSTEM,
                scenario.get("composition_gate_note")
                or "fewer than two participating subsystems"))
            continue
        entries.append(_entry(
            CAT_CROSS_SUBSYSTEM_SCENARIOS,
            subsystems=scenario.get("participating_subsystems") or [],
            source_artifact="system_scenario_model",
            source_id=scenario["scenario_id"],
            description=scenario.get("description") or "",
            basis=f"SYS-30 scenario derived from {scenario.get('derived_from')}; "
                  f"{scenario.get('command_count')} command(s); "
                  f"body={scenario.get('scenario_body_status')}",
            selection_class=rt.CLASS_TARGETED,
        ))
    return entries, excluded, len(scenarios)


def _shared_resource_contention(scheduling_plan: Mapping[str, Any],
                                ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
    """SYS-33's fourth source: the SYS-24 rows that describe a real contention
    point -- a resource whose users must route through one shared access point.
    A row SYS-24 already called NOT_SCHEDULABLE is excluded rather than planned:
    a contention test against a resource whose ownership is unresolved would be
    exercising the unresolved ownership."""
    scheduling = scheduling_plan.get("shared_resource_scheduling") or {"entries": []}
    entries: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    rows = list(scheduling.get("entries") or [])
    for row in rows:
        disposition = row.get("scheduling_disposition")
        if disposition == ssp.SCHED_NOT_SCHEDULABLE:
            excluded.append(_exclusion(
                CAT_SHARED_RESOURCE_CONTENTION, row["shared_resource_key"],
                EXCL_NOT_SCHEDULABLE, str(row.get("scheduling_reason") or "")))
            continue
        if disposition != ssp.SCHED_SINGLE_SHARED_ACCESS_POINT:
            continue
        entries.append(_entry(
            CAT_SHARED_RESOURCE_CONTENTION,
            subsystems=row.get("consumer_subsystems") or [],
            source_artifact="shared_resource_scheduling",
            source_id=row["shared_resource_key"],
            description=f"contention on {row['shared_resource_key']} between "
                        f"{', '.join(row.get('consumer_subsystems') or []) or '(unknown)'}",
            basis=f"SYS-24 disposition={disposition}; "
                  f"access_point={row.get('shared_access_point')} "
                  f"({row.get('access_point_status')}); "
                  f"writers={row.get('writing_subsystems')}",
            selection_class=rt.CLASS_SAFETY,
        ))
    return entries, excluded, len(rows)


def _boot_config(command_plan: Mapping[str, Any],
                 scheduling_plan: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """SYS-33's boot/config category. Membership is SYS-23's own scope
    classification (SYSTEM_ONCE / SUBSYSTEM_ONCE), which is already restricted
    to `INITIALIZING_CATEGORIES` -- so this reads a decision rather than
    re-deriving "is this command a boot step" from a name."""
    ir_by_id = {e["system_command_id"]: e
                for e in ((command_plan.get("system_command_ir") or {}).get("entries") or [])}
    dedup = scheduling_plan.get("initialization_deduplication") or {"entries": []}
    entries: List[Dict[str, Any]] = []
    for row in dedup.get("entries") or []:
        if row.get("scope_class") not in (ssp.SYSTEM_ONCE, ssp.SUBSYSTEM_ONCE):
            continue
        ir_entry = ir_by_id.get(row["system_command_id"]) or {}
        entries.append(_entry(
            CAT_BOOT_CONFIG,
            subsystems=[row.get("source_subsystem")],
            source_artifact="initialization_deduplication",
            source_id=row["system_command_id"],
            description=f"boot/config step {row.get('source_subsystem')}::"
                        f"{row.get('source_command')}",
            basis=f"SYS-23 scope_class={row.get('scope_class')}: {row.get('scope_basis')}; "
                  f"SYS-7 category={ir_entry.get('command_category') or row.get('command_category')}",
            selection_class=rt.CLASS_DEPENDENCY,
        ))
    return entries


def _interrupt(command_plan: Mapping[str, Any],
               topology_analysis: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """SYS-33's interrupt category, from two real sources that answer two
    different questions and are therefore both kept: a command whose SYS-21
    completion condition IS an interrupt handshake (the per-command view), and
    a SYS-28 interrupt line shared across subsystems (the topology view -- a
    line two subsystems both drive or observe is an integration risk no single
    command's completion condition reveals)."""
    entries: List[Dict[str, Any]] = []
    for ir_entry in ((command_plan.get("system_command_ir") or {}).get("entries") or []):
        if ir_entry.get("completion_condition") != scp.COMPLETION_INTERRUPT:
            continue
        entries.append(_entry(
            CAT_INTERRUPT,
            subsystems=[ir_entry["source_subsystem"]],
            source_artifact="system_command_ir",
            source_id=ir_entry["system_command_id"],
            description=f"interrupt handshake in {ir_entry['source_subsystem']}::"
                        f"{ir_entry['source_command']}",
            basis=f"SYS-21 completion_condition={scp.COMPLETION_INTERRUPT}",
            selection_class=rt.CLASS_TARGETED,
        ))
    interrupts = topology_analysis.get("interrupt_map_reconciliation") or {}
    for line in interrupts.get("lines") or []:
        if line.get("verdict") != sta.INTERRUPT_LINE_SHARED:
            continue
        entries.append(_entry(
            CAT_INTERRUPT,
            subsystems=line.get("subsystems") or [],
            source_artifact="interrupt_map_reconciliation",
            source_id=str(line.get("line") or ""),
            description=f"interrupt line {line.get('line')} shared across subsystems",
            basis=f"SYS-28 verdict={line.get('verdict')}; "
                  f"subsystems={line.get('subsystems')}",
            selection_class=rt.CLASS_SAFETY,
        ))
    return entries


def _dma(integration_plan: Mapping[str, Any],
         topology_analysis: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """SYS-33's DMA category, from the SYS-15 registry's own DMA_MODEL entries
    and the SYS-28 regions this repo's address-range classifier typed
    DMA_RANGE. Neither is a name guess made here: `RT_DMA_MODEL` is
    `system_resource_inventory`'s resource type and `RANGE_DMA` is
    `system_topology_analysis.classify_address_range_kind()`'s verdict."""
    entries: List[Dict[str, Any]] = []
    registry = integration_plan.get("system_resource_registry") or {"entries": []}
    for entry in registry.get("entries") or []:
        if entry.get("resource_type") != sri.RT_DMA_MODEL:
            continue
        subsystems = list(entry.get("consumer_subsystems") or [])
        if entry.get("owner"):
            subsystems.append(str(entry["owner"]))
        entries.append(_entry(
            CAT_DMA,
            subsystems=subsystems,
            source_artifact="system_resource_registry",
            source_id=entry["resource_id"],
            description=f"DMA model {entry['resource_id']} "
                        f"({entry.get('reuse_decision')})",
            basis=f"SYS-15 resource_type={sri.RT_DMA_MODEL}; "
                  f"shared={entry.get('shared')}; "
                  f"conflict_status={entry.get('conflict_status')}",
            selection_class=rt.CLASS_TARGETED,
        ))
    address = topology_analysis.get("address_map_reconciliation") or {}
    for sid, block in sorted((address.get("per_subsystem") or {}).items()):
        for region in block.get("regions") or []:
            if region.get("range_kind") != sta.RANGE_DMA:
                continue
            entries.append(_entry(
                CAT_DMA,
                subsystems=[region.get("subsystem_id") or sid],
                source_artifact="address_map_reconciliation",
                source_id=f"{sid}::{region.get('name') or region.get('target') or ''}",
                description=f"DMA address range {region.get('name')} in {sid}",
                basis=f"SYS-28 range_kind={sta.RANGE_DMA}; "
                      f"basis={region.get('range_kind_basis')}; "
                      f"base={region.get('base_address')}",
                selection_class=rt.CLASS_DEPENDENCY,
            ))
    return entries


def _stress_concurrency(scheduling_plan: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """SYS-33's stress/concurrency category: the SYS-25 command pairs already
    classified PARALLEL_SAFE. Those pairs are the ONLY ones a concurrency test
    may legitimately drive together -- every other relationship value says the
    two must be ordered, serialized or are undecided, and a stress test built
    on an undecided pair would be measuring the harness's own uncertainty.

    `classify_parallelism_relationships()` emits cross-subsystem pairs only
    (`summary.cross_subsystem_only`), so every entry here is by construction a
    multi-subsystem concurrency case."""
    relationships = scheduling_plan.get("parallelism_model") or {"pairs": []}
    entries: List[Dict[str, Any]] = []
    for pair in relationships.get("pairs") or []:
        if pair.get("relationship") != ssp.REL_PARALLEL_SAFE:
            continue
        entries.append(_entry(
            CAT_STRESS_CONCURRENCY,
            subsystems=[pair.get("subsystem_a"), pair.get("subsystem_b")],
            source_artifact="parallelism_model",
            source_id=f"{pair['command_a']}|{pair['command_b']}",
            description=f"concurrent {pair['command_a']} + {pair['command_b']}",
            basis=f"SYS-25 relationship={ssp.REL_PARALLEL_SAFE}: {pair.get('basis')}",
            selection_class=rt.CLASS_SAFETY,
        ))
    return entries


# ===========================================================================
# SYS-33 -- composition
# ===========================================================================

def build_system_regression_plan(selection: Mapping[str, Any],
                                 integration_plan: Mapping[str, Any],
                                 command_plan: Mapping[str, Any],
                                 scheduling_plan: Mapping[str, Any],
                                 topology_analysis: Mapping[str, Any],
                                 *,
                                 registry_entries: Optional[Sequence[Mapping[str, Any]]] = None,
                                 ) -> Dict[str, Any]:
    """SYS-33 over the SYS-1 selection and the SYS-15..30 artifacts. Reads
    only; runs nothing.

    Every one of SYS-33's eight categories is present in `by_category` even
    when it is empty, and an empty one carries the reason it is empty. A
    category silently missing from a plan is indistinguishable from a category
    with nothing in it, and only one of those is a finding."""
    registry_entries = list(registry_entries or [])

    known_good, excl_a, universe_a = _known_good_subsystem_tests(
        selection, registry_entries)
    commands, excl_b, universe_b = _selected_command_sequences(
        command_plan, scheduling_plan)
    scenarios, excl_c, universe_c = _cross_subsystem_scenarios(topology_analysis)
    contention, excl_d, universe_d = _shared_resource_contention(scheduling_plan)

    by_category: Dict[str, List[Dict[str, Any]]] = {
        CAT_KNOWN_GOOD_SUBSYSTEM_TESTS: known_good,
        CAT_SELECTED_COMMAND_SEQUENCES: commands,
        CAT_CROSS_SUBSYSTEM_SCENARIOS: scenarios,
        CAT_SHARED_RESOURCE_CONTENTION: contention,
        CAT_BOOT_CONFIG: _boot_config(command_plan, scheduling_plan),
        CAT_INTERRUPT: _interrupt(command_plan, topology_analysis),
        CAT_DMA: _dma(integration_plan, topology_analysis),
        CAT_STRESS_CONCURRENCY: _stress_concurrency(scheduling_plan),
    }
    empty_reasons = {
        CAT_KNOWN_GOOD_SUBSYSTEM_TESTS:
            "no selected subsystem carried both a system-level qualification_state and "
            "PRESENT SYS-4 pass evidence",
        CAT_SELECTED_COMMAND_SEQUENCES:
            "the SYS-21 command IR is empty, or every entry was excluded",
        CAT_CROSS_SUBSYSTEM_SCENARIOS:
            "SYS-30 planned no scenario with two or more participating subsystems",
        CAT_SHARED_RESOURCE_CONTENTION:
            "no SYS-24 row required routing through a single shared access point",
        CAT_BOOT_CONFIG:
            "no command was classified SYSTEM_ONCE or SUBSYSTEM_ONCE by SYS-23",
        CAT_INTERRUPT:
            "no command completes on an interrupt handshake and no SYS-28 interrupt "
            "line is shared across subsystems",
        CAT_DMA:
            "no SYS-15 registry entry is a DMA model and no SYS-28 region classified "
            "as a DMA range",
        CAT_STRESS_CONCURRENCY:
            "no SYS-25 cross-subsystem command pair was classified PARALLEL_SAFE",
    }

    entries: List[Dict[str, Any]] = []
    for category in SYS33_CATEGORIES:
        entries.extend(by_category[category])
    # A pair of categories can legitimately derive an entry from the same row
    # (a DMA model that is also a contended shared resource). Keep the first
    # occurrence in SYS-33's own category order: reporting one row twice would
    # inflate the plan and the concatenation check that reads its size.
    seen: Set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for entry in entries:
        if entry["entry_id"] in seen:
            continue
        seen.add(entry["entry_id"])
        deduped.append(entry)
    entries = deduped

    excluded = excl_a + excl_b + excl_c + excl_d
    universe = universe_a + universe_b + universe_c + universe_d
    selected_from_universe = len(known_good) + len(commands) + len(scenarios) + len(contention)
    if universe == 0:
        verdict = EMPTY_UNIVERSE
    elif selected_from_universe < universe:
        verdict = SELECTION_EVIDENCED
    else:
        verdict = FULL_UNIVERSE_SELECTED

    document = {
        "schema_version": SCHEMA_VERSION,
        "categories": list(SYS33_CATEGORIES),
        "selected_subsystems": sorted(str(s) for s in
                                      (selection.get("selected_subsystems") or [])),
        "entries": entries,
        "by_category": {
            category: {
                "entry_ids": [e["entry_id"] for e in by_category[category]],
                "count": len(by_category[category]),
                "empty_reason": ("" if by_category[category]
                                 else empty_reasons[category]),
            }
            for category in SYS33_CATEGORIES
        },
        "excluded": excluded,
        "concatenation_check": {
            "rule": "SYS-33: do not blindly concatenate all subsystem regressions",
            "universe": universe,
            "selected": selected_from_universe,
            "excluded": len(excluded),
            "verdict": verdict,
            "universe_sources": {
                CAT_KNOWN_GOOD_SUBSYSTEM_TESTS: universe_a,
                CAT_SELECTED_COMMAND_SEQUENCES: universe_b,
                CAT_CROSS_SUBSYSTEM_SCENARIOS: universe_c,
                CAT_SHARED_RESOURCE_CONTENTION: universe_d,
            },
        },
        "summary": {
            "entry_count": len(entries),
            "by_category": {c: len(by_category[c]) for c in SYS33_CATEGORIES},
            "by_selection_class": {
                cls: sum(1 for e in entries if e["selection_class"] == cls)
                for cls in (rt.CLASS_TARGETED, rt.CLASS_DEPENDENCY,
                            rt.CLASS_SAFETY, rt.CLASS_MANDATORY)
            },
            "excluded_count": len(excluded),
            "empty_categories": [c for c in SYS33_CATEGORIES if not by_category[c]],
            "concatenation_verdict": verdict,
            "tests_executed": 0,
            "jobs_submitted": 0,
        },
        "jobs_submitted": [],
        "tests_executed": [],
        "testlists_written": [],
        "artifacts_generated": [],
        "phase_boundary": PHASE_BOUNDARY,
    }
    assert_nothing_executed(document)
    assert_not_blind_concatenation(document)
    return document


# ===========================================================================
# SYS-36 -- CHANGE IMPACT
# ===========================================================================

#: Why a subsystem's diff could not be computed, beyond the statuses
#: `change_impact.changed_files()` itself returns. A subsystem with no
#: registered release_sha has no base to diff against at all -- distinct from
#: "we diffed and found nothing", and reporting it as the latter is exactly the
#: false-clean this whole layer exists to prevent.
DIFF_NO_BASE_SHA = "NO_REGISTERED_RELEASE_SHA"
DIFF_NO_ENVIRONMENT_PATH = "NO_ENVIRONMENT_PATH"

#: `change_impact.changed_files()`'s one status that means the answer is real.
DIFF_REAL = "REAL_DIFF"

#: SYS-36's own permission ("Do not always rerun everything if selective
#: regression is evidence-supported") read as a precondition rather than a
#: preference: selection is allowed only when EVERY selected subsystem produced
#: a real diff. One subsystem whose diff failed means the changed set is
#: unknown, and narrowing a regression on an unknown changed set is the
#: false-negative this rule is worth having.
SELECTIVE_SUPPORTED = "SELECTIVE_REGRESSION_EVIDENCE_SUPPORTED"
SELECTIVE_UNSUPPORTED = "FULL_PLAN_RETAINED_DIFF_EVIDENCE_INCOMPLETE"


def _subsystem_diff(root, row: Mapping[str, Any],
                    registry_entry: Mapping[str, Any],
                    head_rev: str) -> Dict[str, Any]:
    """One subsystem's git change since its own registered release_sha.

    The diff is taken inside the SUBSYSTEM's own tree, not the harness repo:
    `release_sha` is that environment's release, and resolving it against this
    repository would either fail or -- worse, if the SHA happens to exist here
    -- succeed against an unrelated history."""
    sid = str(row.get("subsystem") or registry_entry.get("name") or "")
    base = str(registry_entry.get("release_sha") or "").strip()
    env_path = str(row.get("environment_path") or "").strip()
    if not base:
        return {"subsystem": sid, "status": DIFF_NO_BASE_SHA, "base_sha": "",
                "head_sha": "", "files": [], "changed": False,
                "detail": "this subsystem has no registered release_sha; "
                          "SYS-35 pinning is a precondition for SYS-36",
                "risk_counts": {}}
    if not env_path:
        return {"subsystem": sid, "status": DIFF_NO_ENVIRONMENT_PATH, "base_sha": base,
                "head_sha": "", "files": [], "changed": False,
                "detail": "no environment path is known for this subsystem, so there "
                          "is no tree to diff",
                "risk_counts": {}}
    diff = ci.changed_files(Path(env_path), base, head_rev)
    files = list(diff.get("files") or [])
    risk_counts: Dict[str, int] = {}
    for path in files:
        risk = ci.classify_risk(path)
        risk_counts[risk] = risk_counts.get(risk, 0) + 1
    return {
        "subsystem": sid,
        "status": diff["status"],
        "base_sha": diff.get("base_sha") or base,
        "head_sha": diff.get("head_sha") or "",
        "files": files,
        "changed": diff["status"] == DIFF_REAL and bool(files),
        "detail": diff.get("detail") or "",
        "risk_counts": risk_counts,
        "environment_path": env_path,
    }


def compute_subsystem_change_impact(root,
                                    selection: Mapping[str, Any],
                                    integration_plan: Mapping[str, Any],
                                    command_plan: Mapping[str, Any],
                                    scheduling_plan: Mapping[str, Any],
                                    topology_analysis: Mapping[str, Any],
                                    *,
                                    registry_entries: Optional[Sequence[Mapping[str, Any]]] = None,
                                    head_rev: str = "HEAD",
                                    ) -> Dict[str, Any]:
    """SYS-36: subsystem git change -> affected System resources / commands /
    scenarios / scoreboards.

    This is the producer for the `--impact` JSON
    `tools/verification_flow/system_level_change_impact_gate.py` currently
    takes entirely on the agent's word. Every field it validates is COMPUTED
    here from a real `git diff` against the real registered release_sha and the
    real SYS-15/21/26/30 artifacts -- so the gate's internal-consistency check
    is run against a payload that was derived rather than asserted."""
    registry_entries = list(registry_entries or [])
    by_name = {str(e.get("name") or "").lower(): e for e in registry_entries}
    rows = list(selection.get("selected_rows") or [])
    selected = sorted(str(s) for s in (selection.get("selected_subsystems") or []))

    diffs = [_subsystem_diff(root, row,
                             by_name.get(str(row.get("subsystem") or "").lower()) or {},
                             head_rev)
             for row in rows]
    changed = sorted({d["subsystem"] for d in diffs if d["changed"]})
    undecidable = sorted({d["subsystem"] for d in diffs if d["status"] != DIFF_REAL})
    changed_set = set(changed)

    registry = integration_plan.get("system_resource_registry") or {"entries": []}
    affected_resources = []
    for entry in registry.get("entries") or []:
        touching = sorted(changed_set & (
            {str(entry.get("owner") or "")}
            | {str(c) for c in (entry.get("consumer_subsystems") or [])}))
        if not touching:
            continue
        affected_resources.append({
            "resource_id": entry["resource_id"],
            "resource_type": entry.get("resource_type"),
            "changed_subsystems": touching,
            "reuse_decision": entry.get("reuse_decision"),
            "conflict_status": entry.get("conflict_status"),
        })

    ir = command_plan.get("system_command_ir") or {"entries": []}
    affected_commands = [
        {"system_command_id": e["system_command_id"],
         "source_subsystem": e["source_subsystem"],
         "source_command": e.get("source_command"),
         "command_category": e.get("command_category")}
        for e in (ir.get("entries") or []) if e["source_subsystem"] in changed_set]

    model = topology_analysis.get("system_scenario_model") or {"scenarios": []}
    system_scenarios = [
        {"scenario_id": s["scenario_id"],
         "participating_subsystems": list(s.get("participating_subsystems") or []),
         "cross_subsystem": bool(s.get("cross_subsystem"))}
        for s in (model.get("scenarios") or [])]
    affected_scenarios = sorted(
        s["scenario_id"] for s in system_scenarios
        if changed_set & set(s["participating_subsystems"]))

    scoreboards = scheduling_plan.get("scoreboard_integration") or {"subsystems": []}
    affected_scoreboards = [
        {"subsystem_id": s["subsystem_id"], "disposition": s.get("disposition"),
         "scoreboards": [r["resource_id"] for r in (s.get("subsystem_scoreboards") or [])]}
        for s in (scoreboards.get("subsystems") or [])
        if s["subsystem_id"] in changed_set]

    selective = SELECTIVE_SUPPORTED if (rows and not undecidable) else SELECTIVE_UNSUPPORTED
    return {
        "schema_version": SCHEMA_VERSION,
        "selected_subsystems": selected,
        "head_rev": head_rev,
        "subsystem_diffs": diffs,
        "changed_subsystems": changed,
        "undecidable_subsystems": undecidable,
        "affected_system_resources": affected_resources,
        "affected_system_commands": affected_commands,
        "affected_system_scenarios": affected_scenarios,
        "affected_scoreboards": affected_scoreboards,
        "system_scenarios": system_scenarios,
        "selective_regression": {
            "verdict": selective,
            "reason": (
                "every selected subsystem produced a real git diff against its own "
                "registered release_sha, so the changed set is known and the plan may "
                "be narrowed to it"
                if selective == SELECTIVE_SUPPORTED else
                "at least one selected subsystem's diff could not be computed "
                f"({undecidable or 'no subsystem rows supplied'}), so the changed set is "
                "not known and narrowing the plan would be a guess"),
            "undecidable_subsystems": undecidable,
        },
        "summary": {
            "subsystems_examined": len(diffs),
            "changed_subsystems": len(changed),
            "undecidable_subsystems": len(undecidable),
            "affected_resources": len(affected_resources),
            "affected_commands": len(affected_commands),
            "affected_scenarios": len(affected_scenarios),
            "affected_scoreboards": len(affected_scoreboards),
            "selective_regression_verdict": selective,
        },
        "phase_boundary": PHASE_BOUNDARY,
    }


def build_change_impact_gate_input(impact: Mapping[str, Any]) -> Dict[str, Any]:
    """The exact payload `system_level_change_impact_gate.py` reads, computed
    rather than attested.

    The gate recomputes `impacted` from `system_scenarios` x
    `changed_subsystems` and FAILs on any impacted scenario missing from
    `rerun_scenarios`. `affected_system_scenarios` is derived by the same
    intersection over the same two lists, so a payload built here passes that
    check by construction -- which is the point: the gate stops being a check
    on the agent's arithmetic and becomes a check that the payload it was
    handed really is the one this producer computed."""
    return {
        "selected_subsystems": list(impact.get("selected_subsystems") or []),
        "changed_subsystems": list(impact.get("changed_subsystems") or []),
        "system_scenarios": [
            {"scenario_id": s["scenario_id"],
             "participating_subsystems": list(s.get("participating_subsystems") or [])}
            for s in (impact.get("system_scenarios") or [])],
        "rerun_scenarios": list(impact.get("affected_system_scenarios") or []),
        "evidence": {
            "producer": "dv_harness.system_regression_plan.compute_subsystem_change_impact",
            "subsystem_diffs": [
                {"subsystem": d["subsystem"], "status": d["status"],
                 "base_sha": d.get("base_sha"), "head_sha": d.get("head_sha"),
                 "changed_file_count": len(d.get("files") or [])}
                for d in (impact.get("subsystem_diffs") or [])],
            "selective_regression_verdict": (
                impact.get("selective_regression") or {}).get("verdict"),
        },
    }


def select_targeted_system_regression(plan: Mapping[str, Any],
                                      impact: Mapping[str, Any]) -> Dict[str, Any]:
    """SYS-36's last sentence applied to the SYS-33 plan.

    Two rules, both of which only ever WIDEN the retained set relative to a
    naive "keep what touches a changed subsystem":

      * An entry of class MANDATORY_SIGNOFF is retained regardless. That is
        `regression_tiers`' own meaning of the class and
        `change_impact.select_regression()`'s own "expand, never shrink"
        confidence rule, applied at system level rather than restated.
      * An entry with NO participating subsystem at all is retained, because an
        entry whose scope is unknown cannot be proven irrelevant.

    When the diff evidence is incomplete the whole plan is retained and the
    reason says so -- SYS-36 permits selective regression, it does not permit
    guessing at one."""
    entries = list(plan.get("entries") or [])
    verdict = (impact.get("selective_regression") or {}).get("verdict")
    if verdict != SELECTIVE_SUPPORTED:
        return {
            "mode": SELECTIVE_UNSUPPORTED,
            "reason": (impact.get("selective_regression") or {}).get("reason", ""),
            "retained_entry_ids": [e["entry_id"] for e in entries],
            "dropped_entry_ids": [],
            "summary": {"retained": len(entries), "dropped": 0,
                        "universe": len(entries)},
        }
    changed = set(impact.get("changed_subsystems") or [])
    retained: List[str] = []
    dropped: List[Dict[str, Any]] = []
    for entry in entries:
        subsystems = set(entry.get("participating_subsystems") or [])
        if entry.get("selection_class") == rt.CLASS_MANDATORY:
            retained.append(entry["entry_id"])
            continue
        if not subsystems:
            retained.append(entry["entry_id"])
            continue
        if subsystems & changed:
            retained.append(entry["entry_id"])
            continue
        dropped.append({"entry_id": entry["entry_id"], "category": entry["category"],
                        "participating_subsystems": sorted(subsystems),
                        "reason": "no participating subsystem changed since its "
                                  "registered release_sha"})
    return {
        "mode": SELECTIVE_SUPPORTED,
        "reason": (impact.get("selective_regression") or {}).get("reason", ""),
        "changed_subsystems": sorted(changed),
        "retained_entry_ids": retained,
        "dropped_entry_ids": [d["entry_id"] for d in dropped],
        "dropped": dropped,
        "summary": {"retained": len(retained), "dropped": len(dropped),
                    "universe": len(entries)},
    }


# ===========================================================================
# Reporting
# ===========================================================================

def _cell(value: Any) -> str:
    """Markdown cell text with pipes escaped -- a value containing `|` must not
    silently gain a column."""
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_regression_plan_table(plan: Mapping[str, Any]) -> str:
    header = ("| Category | Entry | Class | Subsystems | Source | Basis | Status |")
    lines = [header, "|" + "---|" * 7]
    for entry in plan.get("entries") or []:
        lines.append("| " + " | ".join(_cell(v) for v in (
            entry["category"], entry["entry_id"], entry["selection_class"],
            ", ".join(entry["participating_subsystems"]) or "-",
            f"{entry['source_artifact']}:{entry['source_id']}",
            entry["basis"], entry["execution_status"])) + " |")
    if len(lines) == 2:
        lines.append("| _no regression entry could be derived for this selection_ |"
                     + " |" * 6)
    return "\n".join(lines)


def render_change_impact_table(impact: Mapping[str, Any]) -> str:
    header = ("| Subsystem | Diff status | Base (release_sha) | Head | Changed files | "
              "Changed |")
    lines = [header, "|" + "---|" * 6]
    for diff in impact.get("subsystem_diffs") or []:
        lines.append("| " + " | ".join(_cell(v) for v in (
            diff["subsystem"], diff["status"], (diff.get("base_sha") or "-")[:12],
            (diff.get("head_sha") or "-")[:12], len(diff.get("files") or []),
            "YES" if diff["changed"] else "no")) + " |")
    if len(lines) == 2:
        lines.append("| _no selected subsystem row was available to diff_ |" + " |" * 5)
    return "\n".join(lines)


def format_system_regression_report(plan: Mapping[str, Any],
                                    impact: Optional[Mapping[str, Any]] = None,
                                    selection_result: Optional[Mapping[str, Any]] = None,
                                    ) -> str:
    """The SYS-33/SYS-36 section of the Phase-1 report."""
    summary = plan["summary"]
    check = plan["concatenation_check"]
    out = [
        "# SYSTEM REGRESSION PLAN (SYS-33) AND CHANGE IMPACT (SYS-36)",
        "",
        f"Selected subsystems: {', '.join(plan['selected_subsystems']) or '(none)'}",
        "",
        "## SYS-33 SYSTEM REGRESSION",
        "",
        f"{summary['entry_count']} planned entry/-ies across "
        f"{len(SYS33_CATEGORIES)} mandated categories; "
        f"{summary['excluded_count']} candidate(s) excluded with a recorded reason; "
        f"{summary['tests_executed']} test(s) executed; "
        f"{summary['jobs_submitted']} job(s) submitted.",
        "",
        f"Concatenation check: {check['verdict']} -- selected {check['selected']} of a "
        f"{check['universe']}-row universe ({check['rule']}).",
        "",
        render_regression_plan_table(plan),
        "",
        "### Empty categories",
        "",
    ]
    empties = [c for c in SYS33_CATEGORIES if not plan["by_category"][c]["count"]]
    if empties:
        for category in empties:
            out.append(f"- **{category}**: {plan['by_category'][category]['empty_reason']}")
    else:
        out.append("_(every SYS-33 category has at least one planned entry)_")
    out += ["", "### Excluded candidates", ""]
    if plan.get("excluded"):
        for row in plan["excluded"]:
            out.append(f"- `{row['source_id']}` ({row['category']}): "
                       f"{row['reason']} -- {row['detail']}")
    else:
        out.append("_(no candidate was excluded)_")

    out += ["", "## SYS-36 CHANGE IMPACT", ""]
    if impact is None:
        out += ["_Not computed. Run "
                "`system_regression_plan.compute_subsystem_change_impact()` and pass "
                "the result as `impact`._"]
    else:
        isummary = impact["summary"]
        out += [
            f"{isummary['subsystems_examined']} subsystem(s) diffed against their own "
            f"registered release_sha; {isummary['changed_subsystems']} changed; "
            f"{isummary['undecidable_subsystems']} undecidable.",
            "",
            render_change_impact_table(impact),
            "",
            f"Affected: {isummary['affected_resources']} System resource(s), "
            f"{isummary['affected_commands']} System command(s), "
            f"{isummary['affected_scenarios']} scenario(s), "
            f"{isummary['affected_scoreboards']} scoreboard group(s).",
            "",
            f"Selective regression: {impact['selective_regression']['verdict']} -- "
            f"{impact['selective_regression']['reason']}",
        ]
    out += ["", "## PHASE BOUNDARY", "", plan["phase_boundary"]]
    return "\n".join(out)


def _assert_categories_match_the_requirement() -> None:
    """SYS-33 names eight sources in one sentence. Import-time check that the
    tuple still has exactly those eight, so a future edit that adds a ninth
    category has to change the requirement's own reading deliberately rather
    than by appending to a list."""
    if len(SYS33_CATEGORIES) != 8 or len(set(SYS33_CATEGORIES)) != 8:
        raise SystemRegressionPlanError("SYS33_CATEGORY_SET_CHANGED", {
            "categories": list(SYS33_CATEGORIES),
            "expected_count": 8,
            "requirement": "SYS-33: known-good subsystem tests, selected command "
                           "sequences, cross-subsystem scenarios, shared-resource "
                           "contention, boot/config, interrupt, DMA, "
                           "stress/concurrency"})


_assert_categories_match_the_requirement()
