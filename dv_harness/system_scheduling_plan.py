"""SYS-23..SYS-27 of the System-Level Verification Integration workflow: the
INITIALIZATION DEDUPLICATION classification, the SHARED RESOURCE SCHEDULING
plan, the PARALLELISM MODEL, the SCOREBOARD INTEGRATION reuse plan and the
CROSS-SUBSYSTEM CHECKING plan.

WHAT THIS MODULE IS NOT
-----------------------
It is the single most important boundary in this layer, so it is stated
before anything else. Nothing here emits a shared sequencer, a shared driver,
a shared queue, an arbiter, a System Scoreboard, a Correlation Layer, a
cross-subsystem checker, a scenario body or any System-Level UVM source.

  * SYS-23 CLASSIFIES commands and never removes one. There is deliberately
    no `REMOVE` value in `SYS23_DEDUP_ACTIONS`: SYS-23's own closing sentence
    is "Do not remove commands without evidence", and the strongest thing a
    Phase-1 report may say is that a human should decide.
  * SYS-24 NAMES the single shared access point every user of a shared
    physical agent would route through. `access_point_status` is
    PLANNED_NOT_IMPLEMENTED for every entry and stays that way through this
    whole workflow -- a sequencer/driver/queue is code, and code is SYS-40.
  * SYS-25 classifies command-pair RELATIONSHIPS. It schedules nothing.
  * SYS-26 records that each selected subsystem's OWN scoreboard is reused
    unmodified, and describes the correlation layer that would sit above
    them, including the prerequisite that does not exist yet. It writes no
    scoreboard content.
  * SYS-27 evaluates SYS-27's own six candidate flows for architectural
    support and states, per flow, what a real check would need. It writes no
    check content.

`soc_environment_composer.cross_subsystem_scenarios()`,
`end_to_end_scoreboard()` and `system_coverage()` are the code-level statement
of the same boundary, and this module does not cross it -- it REPORTS it.
`probe_composer_boundary()` calls all three and records that each still
raises NotImplementedError, so SYS-26/SYS-27's "content is out of scope"
claim is a checked fact in every produced document rather than a comment that
can quietly go stale. `assert_no_emitted_artifacts()` is the runtime check of
the rest, and tests assert both rather than trusting this paragraph.

WHY A NEW MODULE RATHER THAN AN EXTENSION
-----------------------------------------
SYS-23..27 all operate on the JOIN of two things neither existing module
owns: the SYS-21 System Command IR (one row per SYSTEM-level command) and the
SYS-15 System Resource Registry (one row per SYSTEM-level resource).

  * `system_command_plan.py` (SYS-18..22) builds the IR from a contract set
    and takes no resource registry into its IR at all -- `build_system_
    command_ir()`'s only inputs are the contract set and the routing plan. A
    SYS-24 scheduling row is one (shared resource x the commands routed
    through it), a granularity its IR cannot express.
  * `system_resource_registry.py` (SYS-15..17) is resource-granularity and
    takes no command input whatsoever. It cannot say which commands would
    contend for an entry.
  * `subsystem_command_contract.py` (SYS-5..8) is deliberately
    subsystem-local; SYS-25's relationship is a property of a PAIR of
    commands from two different subsystems.

So this module follows exactly the precedent `system_resource_registry.py`
and `system_command_plan.py` set: a new module at the new granularity that
IMPORTS and COMPOSES the layers below and re-derives none of them.

  * `scp.build_system_command_ir()` supplies every command fact, including
    the `parallel_group`/`serialization_group` naming and the three-valued
    `parallel_safe` verdict `scc.resolve_cross_subsystem_concurrency()`
    decided over the whole set. No second concurrency resolver.
  * `scp.detect_command_collisions()` supplies the duplicate/conflict
    findings SYS-23 classifies. SYS-23 does NOT re-join command names across
    subsystems: SYS-22 already did that join, and its findings already carry
    `evidence_by_subsystem`, which is exactly the per-side citation SYS-23's
    "do not remove without evidence" rule needs.
  * `srr.build_system_resource_registry()` supplies which resources are
    shared, who consumes them, and what was decided about them. SYS-24 does
    not re-derive sharing.
  * `sri` supplies the resource TYPE vocabulary and the inventory link
    (`dependencies.command_resource_ids`) that joins a registry entry to the
    command-layer resource ids. That link is read, never recomputed.

WHY SYS-25's SIX VALUES ARE NOT `scc.PARALLEL_SAFETY_VALUES`
------------------------------------------------------------
`scc.parallel_safe` is a THREE-valued verdict about ONE command against the
whole rest of the set ("may this command run beside another subsystem's
commands at all"). SYS-25 asks for a relationship between a PAIR, and its six
values distinguish REASONS that three-valued verdict folds together: an
ordering dependency, an interrupt handshake and a clock-domain crossing all
land on the same `NOT_PARALLEL_SAFE`/`PARALLEL_SAFE` answer while needing
completely different scheduling. So the pair classifier CONSUMES
`parallel_safe` as its resource-contention signal and adds the four
distinctions it cannot carry; it never recomputes contention.

The single verdict is chosen by `SYS25_PRECEDENCE`, most restrictive first,
and every signal that matched is kept beside it in `also_matched` -- a
single-valued enum that silently discarded the second reason a pair is
coupled would be a worse report than one that never noticed it.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from . import connectivity as conn
from . import reference_pattern_audit as rpa
from . import system_command_plan as scp
from . import system_resource_inventory as sri
from . import system_resource_registry as srr

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "system_scheduling_plan.schema.json"
SCHEMA_VERSION = "1.0"


# ===========================================================================
# SYS-23 vocabulary
# ===========================================================================

#: SYS-23's classification vocabulary, verbatim and in the requirement's own
#: order: "Classify commands: SYSTEM_ONCE / SUBSYSTEM_ONCE / SCENARIO_ONCE /
#: REPEATABLE / SHARED_RESOURCE_COMMAND." Five values. A test holds this tuple
#: to that sentence, so neither the code nor a summary of it can drift.
SYSTEM_ONCE = "SYSTEM_ONCE"
SUBSYSTEM_ONCE = "SUBSYSTEM_ONCE"
SCENARIO_ONCE = "SCENARIO_ONCE"
REPEATABLE = "REPEATABLE"
SHARED_RESOURCE_COMMAND = "SHARED_RESOURCE_COMMAND"

SYS23_CLASSES: tuple = (
    SYSTEM_ONCE, SUBSYSTEM_ONCE, SCENARIO_ONCE, REPEATABLE, SHARED_RESOURCE_COMMAND,
)

#: What may be DONE with a classified command at Phase 1. There is deliberately
#: no REMOVE, no MERGE and no HOIST value: SYS-23's own rule is "Do not remove
#: commands without evidence", and the honest Phase-1 maximum is to name a
#: candidate and hand the decision to a human. Removing a command is a change to
#: a real command.txt, which is SYS-40.
DEDUP_KEEP = "KEEP"
DEDUP_CANDIDATE = "DEDUPLICATION_CANDIDATE_PENDING_HUMAN_DECISION"
SYS23_DEDUP_ACTIONS: tuple = (DEDUP_KEEP, DEDUP_CANDIDATE)

#: How many DIFFERENT subsystems must cite real evidence before a command may
#: be named a deduplication candidate. Two, because a duplicate is by
#: definition a statement about two sides and a candidate backed by one side's
#: citation is a claim about the other side that nothing supports.
MIN_EVIDENCE_SIDES_FOR_CANDIDATE = 2

#: SYS-22 collision classes that evidence a DUPLICATED SETUP -- the six SYS-22
#: names for one act performed more than once. Read off `scp`'s own tuple
#: rather than respelled, so a thirteenth collision class added there cannot
#: silently fail to reach SYS-23.
DUPLICATE_SETUP_COLLISIONS: frozenset = frozenset({
    scp.DUPLICATE_INITIALIZATION, scp.DUPLICATE_RESET_SETUP, scp.DUPLICATE_CLOCK_SETUP,
    scp.DUPLICATE_CPU_CONFIGURATION, scp.DUPLICATE_APB_PROGRAMMING,
    scp.DUPLICATE_MEMORY_INIT,
})

#: SYS-7 categories whose commands establish state rather than exercise it.
#: Only these can reach SYSTEM_ONCE / SUBSYSTEM_ONCE -- a register read is not
#: an initialization however many subsystems perform it.
INITIALIZING_CATEGORIES: frozenset = frozenset({
    rpa.C_INITIALIZATION, rpa.C_MEMORY_BACKDOOR, rpa.C_MODEL_TASK,
})

#: SYS-7 categories that OBSERVE and change nothing. A command in one of these
#: is REPEATABLE by construction: running it twice cannot deduplicate anything,
#: so it can never be a removal candidate.
OBSERVING_CATEGORIES: frozenset = frozenset({
    rpa.C_OBSERVATION, rpa.C_SYNCHRONIZATION,
})


# ===========================================================================
# SYS-24 vocabulary
# ===========================================================================

#: SYS-24's dispositions. "Route all users of a shared physical agent through a
#: single shared sequencer/driver/queue" is the first; the others exist because
#: SYS-24's second and third sentences forbid applying it blindly ("Do not
#: globally serialize independent subsystems. Scheduling must derive from
#: actual resource/protocol constraints").
SCHED_SINGLE_SHARED_ACCESS_POINT = "ROUTE_THROUGH_SINGLE_SHARED_ACCESS_POINT"
SCHED_KEEP_SUBSYSTEM_LOCAL = "KEEP_SUBSYSTEM_LOCAL_NO_CROSS_SUBSYSTEM_USER"
SCHED_PASSIVE_NO_ARBITRATION = "PASSIVE_OBSERVERS_NEED_NO_ARBITRATION"
SCHED_NOT_SCHEDULABLE = "NOT_SCHEDULABLE_PENDING_OWNERSHIP_RESOLUTION"
SCHED_UNKNOWN = "UNKNOWN_PENDING_EVIDENCE"

SYS24_DISPOSITIONS: tuple = (
    SCHED_SINGLE_SHARED_ACCESS_POINT, SCHED_KEEP_SUBSYSTEM_LOCAL,
    SCHED_PASSIVE_NO_ARBITRATION, SCHED_NOT_SCHEDULABLE, SCHED_UNKNOWN,
)

#: The shared access point is NAMED and never built. The prefix makes that
#: unmistakable in every report, every JSON dump and every grep.
ACCESS_POINT_PREFIX = "PROPOSED_SHARED_ACCESS_POINT"
ACCESS_POINT_STATUS = "PLANNED_NOT_IMPLEMENTED"
NO_ACCESS_POINT = "NO_SHARED_ACCESS_POINT_REQUIRED"

#: Which evidence axis produced a scheduling row. Both are real, already-built
#: mechanisms and a resource seen by both is ONE row citing both -- reporting
#: it twice would present one shared agent as two.
AXIS_REGISTRY = "SYSTEM_RESOURCE_REGISTRY"
AXIS_COMMAND = "SUBSYSTEM_COMMAND_CONTRACT"

#: SYS-24's "Do not globally serialize independent subsystems", as a verdict.
NO_GLOBAL_SERIALIZATION = "NO_GLOBAL_SERIALIZATION"
GLOBAL_SERIALIZATION_DETECTED = "GLOBAL_SERIALIZATION_DETECTED"

#: Registry `reuse_decision` values that mean nobody may be routed anywhere yet.
#: BLOCKED is SYS-12's stop; UNKNOWN is an absence of evidence, and proposing a
#: single access point for a resource nothing proved shared would be the stop
#: stepped past at the scheduling layer.
UNSCHEDULABLE_DECISIONS: frozenset = frozenset({srr.BLOCKED, srr.DECISION_UNKNOWN})

#: Registry `reuse_decision` values whose consumers are ALL passive observers,
#: so there is nothing to arbitrate between them. Both of SYS-17's monitor
#: -duplicate decisions belong here: PASSIVE_ONLY keeps two monitors and
#: REMOVE_DUPLICATE keeps one, and neither outcome puts a driver on the
#: interface. Leaving REMOVE_DUPLICATE out would fall through to
#: SCHED_SINGLE_SHARED_ACCESS_POINT and propose a shared sequencer/driver/queue
#: for a resource nobody drives.
PASSIVE_NO_ARBITRATION_DECISIONS: frozenset = frozenset({
    srr.PASSIVE_ONLY, srr.REMOVE_DUPLICATE})


# ===========================================================================
# SYS-25 vocabulary
# ===========================================================================

#: SYS-25's relationship vocabulary, verbatim and in its own order:
#: "PARALLEL_SAFE / SERIALIZE_RESOURCE / ORDER_DEPENDENT / INTERRUPT_DEPENDENT
#: / CLOCK_DOMAIN_DEPENDENT / UNKNOWN." Six values, held to that sentence by a
#: test.
REL_PARALLEL_SAFE = "PARALLEL_SAFE"
REL_SERIALIZE_RESOURCE = "SERIALIZE_RESOURCE"
REL_ORDER_DEPENDENT = "ORDER_DEPENDENT"
REL_INTERRUPT_DEPENDENT = "INTERRUPT_DEPENDENT"
REL_CLOCK_DOMAIN_DEPENDENT = "CLOCK_DOMAIN_DEPENDENT"
REL_UNKNOWN = "UNKNOWN"

SYS25_RELATIONSHIPS: tuple = (
    REL_PARALLEL_SAFE, REL_SERIALIZE_RESOURCE, REL_ORDER_DEPENDENT,
    REL_INTERRUPT_DEPENDENT, REL_CLOCK_DOMAIN_DEPENDENT, REL_UNKNOWN,
)

#: Which verdict wins when a pair matches more than one signal, MOST
#: RESTRICTIVE FIRST -- from "must not overlap at all", through "must be
#: ordered", "must be joined by a handshake" and "may overlap but crosses a
#: clock domain", to "may overlap freely" and finally "no evidence either way".
#: SYS-25's own first sentence is "Preserve realistic concurrency ... where
#: safe", so the tie-break has to be the safe side; every signal that matched
#: is still carried in `also_matched`, so choosing one verdict never discards
#: the other reason.
SYS25_PRECEDENCE: tuple = (
    REL_SERIALIZE_RESOURCE, REL_ORDER_DEPENDENT, REL_INTERRUPT_DEPENDENT,
    REL_CLOCK_DOMAIN_DEPENDENT, REL_PARALLEL_SAFE, REL_UNKNOWN,
)


# ===========================================================================
# SYS-26 vocabulary
# ===========================================================================

SCOREBOARD_REUSE_EXISTING = "REUSE_EXISTING_SUBSYSTEM_SCOREBOARD"
SCOREBOARD_NONE_IN_EVIDENCE = "NO_SUBSYSTEM_SCOREBOARD_IN_EVIDENCE"
SYS26_SCOREBOARD_DISPOSITIONS: tuple = (SCOREBOARD_REUSE_EXISTING,
                                        SCOREBOARD_NONE_IN_EVIDENCE)

CORRELATION_LAYER_NAME = "PROPOSED_SYSTEM_SCOREBOARD_CORRELATION_LAYER"
CORRELATION_LAYER_STATUS = "PLANNED_NOT_IMPLEMENTED"

#: The cross-subsystem TOPOLOGY DESCRIPTOR that CLAUDE.md's "Environment
#: Generation Mode" section names as limit (1) -- "a real cross-subsystem
#: topology descriptor (address/interrupt/DMA maps) that does not exist yet".
#: Each part is checked for PRESENCE against real registry evidence, so the
#: report says which of the three the current selection could actually supply
#: rather than repeating a blanket "not available".
TOPO_ADDRESS_MAP = "address_map"
TOPO_INTERRUPT_MAP = "interrupt_map"
TOPO_DMA_MAP = "dma_map"
TOPOLOGY_DESCRIPTOR_PARTS: tuple = (TOPO_ADDRESS_MAP, TOPO_INTERRUPT_MAP, TOPO_DMA_MAP)

TOPO_PRESENT = "EVIDENCE_PRESENT_IN_SELECTION"
TOPO_ABSENT = "NO_EVIDENCE_IN_SELECTION"


# ===========================================================================
# SYS-27 vocabulary
# ===========================================================================

FLOW_SUPPORTED = "SUPPORTED_BY_ARCHITECTURE"
FLOW_ENDPOINT_ABSENT = "NOT_SUPPORTED_ENDPOINT_SUBSYSTEM_ABSENT"
FLOW_INTERMEDIATE_ABSENT = "NOT_SUPPORTED_INTERMEDIATE_RESOURCE_ABSENT"
FLOW_UNKNOWN = "UNKNOWN_INSUFFICIENT_EVIDENCE"

SYS27_FLOW_VERDICTS: tuple = (FLOW_SUPPORTED, FLOW_ENDPOINT_ABSENT,
                              FLOW_INTERMEDIATE_ABSENT, FLOW_UNKNOWN)

#: SYS-27's own six candidate flows, verbatim: "Possible flows include
#: PCIe->DDR->USB, CSI2->Memory->DSI, Ethernet->DMA->Memory,
#: SD/eMMC->DMA->Memory, CPU/APB config->subsystem response,
#: Interrupt->firmware->peripheral response."
#:
#: Each entry is (flow_id, verbatim text, endpoint groups, intermediate
#: resource-type groups, minimum participating subsystems). An ENDPOINT GROUP
#: is a tuple of accepted protocol name tokens, and each group must be matched
#: by a DIFFERENT selected subsystem -- a single subsystem cannot be both ends
#: of a cross-subsystem flow. An INTERMEDIATE GROUP is a tuple of accepted
#: `sri` resource types, any one of which satisfies it, and every group must be
#: satisfied. The resource types are `sri`'s own constants rather than
#: respelled strings, so a renamed type breaks the import rather than silently
#: matching nothing.
#:
#: The last two flows name no protocol at all ("CPU/APB config", "Interrupt")
#: and are therefore evaluated purely on resource evidence plus the minimum
#: participating-subsystem count. That is the requirement's own shape, not an
#: omission.
SYS27_FLOWS: tuple = (
    ("PCIE_DDR_USB", "PCIe->DDR->USB",
     (("PCIE",), ("USB",)),
     ((sri.RT_MEMORY_MODEL,),), 2),
    ("CSI2_MEMORY_DSI", "CSI2->Memory->DSI",
     (("CSI2", "CSI"), ("DSI",)),
     ((sri.RT_MEMORY_MODEL,),), 2),
    ("ETHERNET_DMA_MEMORY", "Ethernet->DMA->Memory",
     (("ETHERNET", "ETH"),),
     ((sri.RT_DMA_MODEL,), (sri.RT_MEMORY_MODEL,)), 1),
    ("SD_EMMC_DMA_MEMORY", "SD/eMMC->DMA->Memory",
     (("EMMC", "MMC", "SD", "SDIO"),),
     ((sri.RT_DMA_MODEL,), (sri.RT_MEMORY_MODEL,)), 1),
    ("CPU_APB_CONFIG_RESPONSE", "CPU/APB config->subsystem response",
     (),
     ((sri.RT_CPU_BUS_MASTER, sri.RT_APB_MASTER, sri.RT_REGISTER_ACCESS_AGENT),), 1),
    ("INTERRUPT_FIRMWARE_PERIPHERAL", "Interrupt->firmware->peripheral response",
     (),
     ((sri.RT_INTERRUPT_AGENT,), (sri.RT_FIRMWARE_AGENT,)), 1),
)

#: A supported flow gets a description of what a real check WOULD need. Every
#: input is reported NOT_AVAILABLE with a reason: a cross-subsystem check needs
#: each side's transaction item fields and the real transformation between them,
#: which is protocol-BEHAVIOR content with no primary source in registry
#: metadata (CLAUDE.md, "No Golden-Reference Content Mining").
CHECK_CONTENT_NOT_GENERATED = "NOT_GENERATED_SYS40_REQUIRES_HUMAN_APPROVAL"
CHECK_INPUT_NOT_AVAILABLE = "NOT_AVAILABLE"

SYS27_REQUIRED_CHECK_INPUTS: tuple = (
    ("source_transaction_type",
     "the producing subsystem's own UVM transaction item type and the fields that "
     "carry the payload being tracked"),
    ("destination_transaction_type",
     "the consuming subsystem's own UVM transaction item type and its corresponding "
     "payload fields"),
    ("address_translation",
     "how an address in the producer's domain maps into the consumer's -- the "
     "cross-subsystem topology descriptor named under SYS-26"),
    ("ordering_and_completion_rule",
     "when the flow is considered complete, and what reordering the fabric is "
     "permitted to perform between the two ends"),
)


# ===========================================================================
# Boundary
# ===========================================================================

#: The three `soc_environment_composer` functions that must still raise. Named
#: here so `probe_composer_boundary()` cannot silently check fewer of them than
#: the requirement's scope covers.
COMPOSER_BOUNDARY_FUNCTIONS: tuple = (
    "cross_subsystem_scenarios", "end_to_end_scoreboard", "system_coverage",
)

PHASE_BOUNDARY = (
    "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED -- SYS-23..SYS-27 are the "
    "initialization-scope CLASSIFICATION, the shared-resource scheduling PLAN, the "
    "parallelism RELATIONSHIP model, the scoreboard-reuse PLAN and the "
    "cross-subsystem checking PLAN. No command is removed, merged or reordered; no "
    "shared sequencer, driver, queue or arbiter is generated; no System Scoreboard "
    "or Correlation Layer is written; no cross-subsystem check, scenario or coverage "
    "content is emitted; no subsystem scoreboard is modified or replaced; and every "
    "subsystem environment is read-only throughout. "
    "soc_environment_composer.cross_subsystem_scenarios() / end_to_end_scoreboard() "
    "/ system_coverage() still raise NotImplementedError and this layer does not "
    "change that. Every access point, correlation layer and check named here is a "
    "RECOMMENDATION for a human. Building any of it is SYS-40 and requires a "
    "separate explicit human approval.")


class SystemSchedulingPlanError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = dict(detail or {})


def probe_composer_boundary() -> Dict[str, Any]:
    """Call all three `soc_environment_composer` cross-subsystem stubs and
    record that each still raises NotImplementedError.

    SYS-26 and SYS-27 both stop where they do because that content has no
    primary source in registry metadata, and the composer states that boundary
    in code. Restating it in a comment here would make this module's own claim
    unfalsifiable; calling the functions makes it a checked fact carried in
    every produced document. A stub that had been filled in would flip
    `boundary_intact` to False rather than pass unnoticed.

    Imported lazily: `soc_environment_composer` is a generator module and this
    is a planning module, so importing it at module scope would create a
    planning->generation dependency for the sake of an assertion.
    """
    from .uvm_generator import soc_environment_composer as sec
    probes: List[Dict[str, Any]] = []
    for name in COMPOSER_BOUNDARY_FUNCTIONS:
        function = getattr(sec, name)
        try:
            function({})
        except NotImplementedError as exc:
            probes.append({"function": name, "raises": "NotImplementedError",
                           "reason": str(exc)[:240]})
        else:
            probes.append({"function": name, "raises": "",
                           "reason": "DID NOT RAISE -- this stub has been implemented"})
    return {
        "module": "dv_harness.uvm_generator.soc_environment_composer",
        "probes": probes,
        "boundary_intact": all(p["raises"] == "NotImplementedError" for p in probes),
        "meaning": ("cross-subsystem scenario, scoreboard and coverage CONTENT is "
                    "protocol-BEHAVIOR content with no primary source in registry "
                    "metadata; SYS-26/SYS-27 plan around that boundary and do not "
                    "cross it"),
    }


def assert_no_emitted_artifacts(document: Mapping[str, Any]) -> None:
    """The SYS-39/SYS-40 boundary, as a runtime check rather than a comment.

    Raises unless the document states, on its own face, that no command was
    removed, no shared access point was built, no subsystem scoreboard was
    replaced and no check content was generated. A planning document that could
    not answer these questions about itself would be exactly the artifact a
    reader might mistake for the real thing.
    """
    dedup = document.get("initialization_deduplication") or {}
    scheduling = document.get("shared_resource_scheduling") or {}
    scoreboards = document.get("scoreboard_integration") or {}
    checking = document.get("cross_subsystem_checking") or {}

    for entry in dedup.get("entries") or []:
        if entry["deduplication_action"] not in SYS23_DEDUP_ACTIONS:
            raise SystemSchedulingPlanError("COMMAND_REMOVAL_PROPOSED", {
                "system_command_id": entry["system_command_id"],
                "action": entry["deduplication_action"],
                "hint": "SYS-23: 'Do not remove commands without evidence'. Removing a "
                        "command edits a real command.txt, which is SYS-40."})
        if (entry["deduplication_action"] == DEDUP_CANDIDATE
                and len(entry["evidence_by_subsystem"]) < MIN_EVIDENCE_SIDES_FOR_CANDIDATE):
            raise SystemSchedulingPlanError("DEDUPLICATION_CANDIDATE_WITHOUT_EVIDENCE", {
                "system_command_id": entry["system_command_id"],
                "evidence_sides": sorted(entry["evidence_by_subsystem"])})

    for row in scheduling.get("entries") or []:
        if row["access_point_status"] != ACCESS_POINT_STATUS:
            raise SystemSchedulingPlanError("SHARED_ACCESS_POINT_IMPLEMENTED", {
                "resource": row["shared_resource_key"],
                "status": row["access_point_status"]})

    for row in scoreboards.get("subsystems") or []:
        if row["subsystem_scoreboard_modified"]:
            raise SystemSchedulingPlanError("SUBSYSTEM_SCOREBOARD_MODIFIED", {
                "subsystem_id": row["subsystem_id"]})
        if row["replaced_by_monolithic_scoreboard"]:
            raise SystemSchedulingPlanError("SUBSYSTEM_SCOREBOARD_REPLACED", {
                "subsystem_id": row["subsystem_id"],
                "hint": "SYS-26: 'Do not replace known-good subsystem scoreboards with "
                        "one monolithic scoreboard'."})
    correlation = scoreboards.get("system_correlation_layer") or {}
    if correlation and correlation.get("status") != CORRELATION_LAYER_STATUS:
        raise SystemSchedulingPlanError("CORRELATION_LAYER_IMPLEMENTED", {
            "status": correlation.get("status")})

    for flow in checking.get("flows") or []:
        if flow["check_content_status"] != CHECK_CONTENT_NOT_GENERATED:
            raise SystemSchedulingPlanError("CROSS_SUBSYSTEM_CHECK_CONTENT_GENERATED", {
                "flow_id": flow["flow_id"], "status": flow["check_content_status"]})

    if document.get("artifacts_generated"):
        raise SystemSchedulingPlanError("ARTIFACT_GENERATED", {
            "artifacts": document.get("artifacts_generated")})


# ===========================================================================
# SYS-23 -- INITIALIZATION DEDUPLICATION
# ===========================================================================

def _repeated_invocation_evidence(entry: Mapping[str, Any]) -> Dict[str, Any]:
    """Whether one command is invoked more than once inside its OWN file, and
    the citation for it.

    Derived from the contract's own already-computed fields rather than from a
    new invocation counter: `address_dependency` holds one record per DISTINCT
    address the command touched, and the argument profile holds the distinct
    literal values per position. Either being plural is real evidence of more
    than one invocation, cited to the addresses/values that prove it. A
    single-address, single-value command is NOT thereby proven single-invoked
    -- that is reported as an absence, never as a verdict.
    """
    addresses = list((entry.get("derivation") or {}).get("address_dependency") or [])
    if len(addresses) > 1:
        return {"repeated": True,
                "basis": "MULTIPLE_DISTINCT_ADDRESSES_TOUCHED_BY_ONE_COMMAND",
                "detail": ", ".join(a["address"] for a in addresses[:4]),
                "evidence": [e for a in addresses[:2] for e in (a.get("evidence") or [])][:4]}
    for argument in entry.get("arguments") or []:
        if int(argument.get("distinct_value_count") or 0) > 1:
            return {"repeated": True,
                    "basis": "MULTIPLE_DISTINCT_ARGUMENT_VALUES_AT_ONE_POSITION",
                    "detail": (f"position {argument['position']} ({argument.get('role')}) "
                               f"carries {argument['distinct_value_count']} distinct values"),
                    "evidence": list(entry.get("evidence") or [])[:4]}
    return {"repeated": False,
            "basis": "NO_MULTI_INVOCATION_EVIDENCE_IN_THE_SOURCE_FILE",
            "detail": "", "evidence": []}


def classify_initialization_scope(entry: Mapping[str, Any],
                                  *,
                                  duplicate_findings: Sequence[Mapping[str, Any]] = (),
                                  shared_resource_ids: Optional[Set[str]] = None,
                                  ) -> Dict[str, Any]:
    """SYS-23's five-value classification for ONE System Command IR entry.

    Precedence, and why it is this order:

      SYSTEM_ONCE  a command SYS-22 already found DUPLICATED as a setup across
                   two or more subsystems, whose own category is an
                   initializing one. This is the only class that answers "run
                   this once for the whole System", so it must win: labelling
                   it SHARED_RESOURCE_COMMAND would hide the exact finding
                   SYS-23 exists to surface.
      SHARED_RESOURCE_COMMAND
                   any remaining command with a CONTENDED cross-subsystem
                   shared resource. Its execution count is not a dedup question
                   at all -- SYS-24 schedules it -- and this label says so.
      SUBSYSTEM_ONCE
                   an initializing command with no cross-subsystem duplicate
                   and no contended sharing: once per subsystem instance.
      SCENARIO_ONCE
                   a non-initializing, non-shared command with no evidence of
                   repeated invocation in its own file: once per scenario.
      REPEATABLE   evidence of more than one invocation in its own file, an
                   observing category, or -- as the residual -- no evidence
                   constraining execution count at all.

    REPEATABLE is deliberately the residual rather than an UNKNOWN value.
    SYS-23's vocabulary has no UNKNOWN, and REPEATABLE is the only one of the
    five whose consequence is to change nothing: an unclassifiable command
    reported REPEATABLE proposes no deduplication, which is precisely what
    "Do not remove commands without evidence" requires of a case with no
    evidence. The basis string says so explicitly rather than implying a
    verdict was reached.
    """
    shared_ids = set(shared_resource_ids or ())
    command_id = entry["system_command_id"]
    category = entry.get("command_category") or ""

    duplicate = next((f for f in duplicate_findings
                      if command_id in (f.get("commands") or [])
                      and f["collision_type"] in DUPLICATE_SETUP_COLLISIONS), None)
    contended = sorted({
        dep["resource_id"]
        for dep in ((entry.get("derivation") or {}).get("shared_resource_dependency") or [])
        if dep.get("contention") != "READ_ONLY_SHARING"})
    registry_shared = sorted(set(entry.get("shared_resource") or []) & shared_ids)
    repeat = _repeated_invocation_evidence(entry)

    if duplicate is not None and category in INITIALIZING_CATEGORIES:
        return {
            "scope_class": SYSTEM_ONCE,
            "basis": (f"SYS-22 classified {entry['source_command']} as "
                      f"{duplicate['collision_type']} across "
                      f"{duplicate['subsystems']}, and its own SYS-7 category is "
                      f"{category} -- one act performed once per subsystem where the "
                      "System needs it performed once"),
            "duplicate_collision_id": duplicate["collision_id"],
            "contended_resources": contended,
            "repeat_evidence": repeat,
        }
    if contended or registry_shared:
        return {
            "scope_class": SHARED_RESOURCE_COMMAND,
            "basis": ("this command uses "
                      + ", ".join(contended or registry_shared)
                      + ", which another selected subsystem also uses with at least one "
                        "writer. How often it runs is a SYS-24 scheduling decision "
                        "against that shared agent, not a deduplication decision"),
            "duplicate_collision_id": "",
            "contended_resources": contended or registry_shared,
            "repeat_evidence": repeat,
        }
    if repeat["repeated"]:
        return {
            "scope_class": REPEATABLE,
            "basis": (f"{repeat['basis']}: {repeat['detail']} -- the source file itself "
                      "invokes this command more than once, so it is not a once-only "
                      "setup"),
            "duplicate_collision_id": "",
            "contended_resources": [],
            "repeat_evidence": repeat,
        }
    if category in OBSERVING_CATEGORIES:
        return {
            "scope_class": REPEATABLE,
            "basis": (f"the command's own SYS-7 category is {category}; it observes and "
                      "establishes nothing, so running it again deduplicates nothing"),
            "duplicate_collision_id": "",
            "contended_resources": [],
            "repeat_evidence": repeat,
        }
    if category in INITIALIZING_CATEGORIES:
        return {
            "scope_class": SUBSYSTEM_ONCE,
            "basis": (f"category {category} establishes state, and no other selected "
                      "subsystem invokes this command or contends for its resources -- "
                      "it is once per subsystem instance, not once per System"),
            "duplicate_collision_id": "",
            "contended_resources": [],
            "repeat_evidence": repeat,
        }
    if category:
        return {
            "scope_class": SCENARIO_ONCE,
            "basis": (f"category {category} is neither an initialization nor an "
                      "observation, nothing evidences a second invocation in its own "
                      "file, and no other subsystem contends for its resources -- one "
                      "invocation per scenario"),
            "duplicate_collision_id": "",
            "contended_resources": [],
            "repeat_evidence": repeat,
        }
    return {
        "scope_class": REPEATABLE,
        "basis": ("no evidence constrains how often this command may run: its SYS-7 "
                  "category is empty, nothing evidences repeated invocation, and no "
                  "cross-subsystem duplicate or contention reached it. REPEATABLE is "
                  "the residual because it proposes no deduplication, which is what "
                  "SYS-23's 'do not remove commands without evidence' requires of a "
                  "case with no evidence"),
        "duplicate_collision_id": "",
        "contended_resources": [],
        "repeat_evidence": repeat,
    }


def classify_initialization_deduplication(ir: Mapping[str, Any],
                                          collisions: Mapping[str, Any],
                                          registry: Optional[Mapping[str, Any]] = None,
                                          ) -> Dict[str, Any]:
    """SYS-23 over one System Command IR.

    The cross-subsystem duplicate JOIN is not performed here: SYS-22 already
    performed it, and its findings already carry per-side citations
    (`evidence_by_subsystem`), which is exactly what SYS-23's "do not remove
    commands without evidence" rule needs. Re-joining command names would be a
    second answer to a question this codebase has answered once.
    """
    duplicate_findings = [f for f in (collisions.get("collisions") or [])
                          if f["collision_type"] in DUPLICATE_SETUP_COLLISIONS]
    shared_resource_ids: Set[str] = set()
    for registry_entry in ((registry or {}).get("entries") or []):
        if registry_entry.get("shared") == srr.SHARED_ACROSS_SUBSYSTEMS:
            shared_resource_ids.update(registry_entry.get("member_resource_ids") or [])

    entries: List[Dict[str, Any]] = []
    for ir_entry in (ir.get("entries") or []):
        classification = classify_initialization_scope(
            ir_entry, duplicate_findings=duplicate_findings,
            shared_resource_ids=shared_resource_ids)
        finding = next((f for f in duplicate_findings
                        if f["collision_id"] == classification["duplicate_collision_id"]),
                       None)
        evidence_by_subsystem: Dict[str, List[str]] = (
            {k: list(v) for k, v in (finding or {}).get("evidence_by_subsystem", {}).items()})

        # A deduplication candidate needs a real citation from each side. A
        # SYSTEM_ONCE verdict backed by one subsystem's citation would be a
        # claim about the other subsystem that nothing supports, so it stays
        # KEEP with the shortfall named.
        if (classification["scope_class"] == SYSTEM_ONCE
                and len(evidence_by_subsystem) >= MIN_EVIDENCE_SIDES_FOR_CANDIDATE):
            action = DEDUP_CANDIDATE
            action_reason = (
                "a human decides whether the System runs this once. This report removes, "
                "merges and reorders nothing: SYS-23's rule is 'Do not remove commands "
                "without evidence', and editing a subsystem's command.txt is SYS-40.")
        else:
            action = DEDUP_KEEP
            action_reason = (
                "kept as-is" if classification["scope_class"] != SYSTEM_ONCE else
                f"kept as-is: only {len(evidence_by_subsystem)} subsystem(s) supplied a "
                f"citation and {MIN_EVIDENCE_SIDES_FOR_CANDIDATE} are required before a "
                "duplicate may even be named a candidate")

        entries.append({
            "system_command_id": ir_entry["system_command_id"],
            "source_subsystem": ir_entry["source_subsystem"],
            "source_command": ir_entry["source_command"],
            "command_category": ir_entry.get("command_category") or "",
            "scope_class": classification["scope_class"],
            "scope_basis": classification["basis"],
            "deduplication_action": action,
            "deduplication_action_reason": action_reason,
            "duplicate_collision_id": classification["duplicate_collision_id"],
            "contended_resources": classification["contended_resources"],
            "repeat_evidence": classification["repeat_evidence"],
            "evidence_by_subsystem": evidence_by_subsystem,
        })

    entries.sort(key=lambda e: e["system_command_id"])
    by_class = {c: sum(1 for e in entries if e["scope_class"] == c) for c in SYS23_CLASSES}
    return {
        "schema_version": SCHEMA_VERSION,
        "classes": list(SYS23_CLASSES),
        "entries": entries,
        "summary": {
            "entry_count": len(entries),
            "by_scope_class": by_class,
            "deduplication_candidates": sum(1 for e in entries
                                            if e["deduplication_action"] == DEDUP_CANDIDATE),
            "commands_removed": 0,
            "commands_merged": 0,
            "commands_reordered": 0,
        },
    }


# ===========================================================================
# SYS-24 -- SHARED RESOURCE SCHEDULING
# ===========================================================================

def _command_resource_links(resource_analysis: Optional[Mapping[str, Any]],
                            ) -> Dict[str, Set[str]]:
    """{sri resource_id -> {scc command-layer resource ids}} from the SYS-9
    inventory's OWN `dependencies.command_resource_ids` link.

    That link is what makes a registry entry and a command's required resource
    the same physical thing; it is read here and never recomputed. An empty map
    (no inventory supplied) means the two axes cannot be joined, which is
    reported as an absence rather than guessed at by name.
    """
    links: Dict[str, Set[str]] = {}
    inventory = (resource_analysis or {}).get("inventory") or {}
    for resource in inventory.get("resources") or []:
        ids = {link["resource_id"] for link
               in ((resource.get("dependencies") or {}).get("command_resource_ids") or [])}
        if ids:
            links[resource["resource_id"]] = ids
    return links


def _access_point_name(key: str) -> str:
    """A stable, readable name for the single shared sequencer/driver/queue.
    The hash suffix keeps two resources whose ids differ only in characters a
    name cannot carry from collapsing into one name."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", key).strip("_").upper()[:48] or "RESOURCE"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:6].upper()
    return f"{ACCESS_POINT_PREFIX}::{slug}::{digest}"


def _scheduling_constraints(registry_entry: Optional[Mapping[str, Any]],
                            contentions: Sequence[str],
                            ) -> Dict[str, Any]:
    """SYS-24's "Scheduling must derive from actual resource/protocol
    constraints", as the list of REAL fields that decided this row.

    Every constraint names the field it was read from. A row whose constraint
    list is empty says so and lands on SCHED_UNKNOWN rather than getting a
    plausible-looking default policy, because a scheduling policy nothing
    derived is an invented verification parameter.
    """
    constraints: List[Dict[str, Any]] = []
    entry = registry_entry or {}
    if entry.get("exclusive") == sri.EXCLUSIVE_YES:
        constraints.append({"constraint": "EXCLUSIVE_ACCESS_REQUIRED",
                            "from_field": "system_resource_registry.exclusive",
                            "value": entry["exclusive"]})
    if entry.get("active_passive"):
        constraints.append({"constraint": "DRIVE_MODE",
                            "from_field": "system_resource_registry.active_passive",
                            "value": entry["active_passive"]})
    protocol = entry.get("protocol")
    if protocol and protocol != conn.PROTOCOL_NOT_CLASSIFIED:
        constraints.append({"constraint": "PROTOCOL_ORDERING_RULES_APPLY",
                            "from_field": "system_resource_registry.protocol",
                            "value": protocol})
    for field in ("clock", "reset"):
        value = str(entry.get(field) or "")
        if value.startswith(srr.DISAGREEMENT):
            constraints.append({"constraint": f"{field.upper()}_DOMAIN_DISAGREEMENT",
                                "from_field": f"system_resource_registry.{field}",
                                "value": value})
    for contention in sorted(set(contentions)):
        if contention and contention != "READ_ONLY_SHARING":
            constraints.append({
                "constraint": f"COMMAND_LAYER_{contention}",
                "from_field": "subsystem_command_contract.shared_resource_dependency"
                              ".contention",
                "value": contention})
    return {
        "constraints": constraints,
        "derived": bool(constraints),
        "reason": ("" if constraints else
                   "no resource or protocol constraint was found in the registry entry or "
                   "in any contract's shared-resource dependency; SYS-24 requires "
                   "scheduling to derive from actual constraints, so none is proposed"),
    }


def plan_shared_resource_scheduling(ir: Mapping[str, Any],
                                    registry: Mapping[str, Any],
                                    *,
                                    resource_analysis: Optional[Mapping[str, Any]] = None,
                                    ) -> Dict[str, Any]:
    """SYS-24: one row per SHARED PHYSICAL AGENT, naming the single access
    point every user would route through and the commands that would route.

    TWO REAL EVIDENCE AXES, RECONCILED RATHER THAN RE-DERIVED. A shared
    physical agent is evidenced from the environment side (a SYS-15 registry
    entry whose `shared` is SHARED_ACROSS_SUBSYSTEMS, itself built from the
    connectivity matrices) and from the command side (a contract's
    `shared_resource_dependency`, built from the command.txt files). Both are
    already computed by mechanisms this module imports. Where the SYS-9
    inventory supplies a link between them, the two are JOINED into ONE row
    citing both axes -- emitting one row per axis would present a single
    shared agent as two consumable resources, which is the same defect the
    registry itself refuses at its own layer.
    """
    links = _command_resource_links(resource_analysis)

    # command-layer facts, keyed by scc resource id
    users_by_command_resource: Dict[str, Set[str]] = {}
    commands_by_command_resource: Dict[str, Set[str]] = {}
    contention_by_command_resource: Dict[str, Set[str]] = {}
    writers_by_command_resource: Dict[str, Set[str]] = {}
    evidence_by_command_resource: Dict[str, List[str]] = {}
    for entry in (ir.get("entries") or []):
        derivation = entry.get("derivation") or {}
        for dep in derivation.get("shared_resource_dependency") or []:
            rid = dep["resource_id"]
            users_by_command_resource.setdefault(rid, set()).add(entry["source_subsystem"])
            users_by_command_resource[rid].update(dep.get("other_subsystems") or [])
            commands_by_command_resource.setdefault(rid, set()).add(
                entry["system_command_id"])
            contention_by_command_resource.setdefault(rid, set()).add(
                str(dep.get("contention") or ""))
            if dep.get("this_access") == "WRITE":
                writers_by_command_resource.setdefault(rid, set()).add(
                    entry["source_subsystem"])
            citations = evidence_by_command_resource.setdefault(rid, [])
            for citation in dep.get("evidence") or []:
                if citation not in citations and len(citations) < 6:
                    citations.append(citation)

    rows: List[Dict[str, Any]] = []
    claimed_command_resources: Set[str] = set()

    for registry_entry in (registry.get("entries") or []):
        members = set(registry_entry.get("member_resource_ids") or [])
        command_resources = sorted({rid for member in members
                                    for rid in links.get(member, set())})
        claimed_command_resources.update(command_resources)
        consumers = sorted(set(registry_entry.get("consumer_subsystems") or []))
        for rid in command_resources:
            consumers = sorted(set(consumers) | users_by_command_resource.get(rid, set()))
        routed = sorted({cid for rid in command_resources
                         for cid in commands_by_command_resource.get(rid, set())})
        contentions = sorted({c for rid in command_resources
                              for c in contention_by_command_resource.get(rid, set())})
        constraints = _scheduling_constraints(registry_entry, contentions)

        decision = registry_entry.get("reuse_decision")
        shared = registry_entry.get("shared") == srr.SHARED_ACROSS_SUBSYSTEMS
        if decision in UNSCHEDULABLE_DECISIONS:
            disposition = SCHED_NOT_SCHEDULABLE
            reason = (f"the SYS-15 registry decided {decision} for this resource "
                      f"({registry_entry.get('reuse_decision_reason', '')[:200]}). Routing "
                      "users through a shared access point before ownership is resolved "
                      "would step past the SYS-12 stop at the scheduling layer")
        elif not shared and len(consumers) < 2:
            disposition = SCHED_KEEP_SUBSYSTEM_LOCAL
            reason = ("exactly one selected subsystem consumes this resource, so there is "
                      "no cross-subsystem user to arbitrate between. SYS-24's second "
                      "sentence forbids serializing independent subsystems, and hoisting "
                      "an unshared resource into a System access point is that same "
                      "mistake made structurally")
        elif decision in PASSIVE_NO_ARBITRATION_DECISIONS:
            disposition = SCHED_PASSIVE_NO_ARBITRATION
            reason = ("every consumer of this resource is a passive observer; passive "
                      "monitors do not drive it, so they need no shared driver or queue "
                      "between them"
                      + (" (the registry additionally judged one of them redundant, which "
                         "removes an observer and never adds a driver)"
                         if decision == srr.REMOVE_DUPLICATE else ""))
        elif not constraints["derived"]:
            disposition = SCHED_UNKNOWN
            reason = constraints["reason"]
        else:
            disposition = SCHED_SINGLE_SHARED_ACCESS_POINT
            reason = (f"{len(consumers)} selected subsystems use this one physical "
                      "resource with at least one writer, so every user routes through a "
                      "single shared sequencer/driver/queue rather than instantiating its "
                      "own agent on the same interface")

        needs_access_point = disposition == SCHED_SINGLE_SHARED_ACCESS_POINT
        rows.append({
            "shared_resource_key": registry_entry["resource_id"],
            "resource_type": registry_entry.get("resource_type") or "",
            "protocol": registry_entry.get("protocol") or "",
            "evidence_axes": ([AXIS_REGISTRY] + ([AXIS_COMMAND] if command_resources else [])),
            "registry_entry_id": registry_entry["resource_id"],
            "command_resource_ids": command_resources,
            "consumer_subsystems": consumers,
            "writing_subsystems": sorted({s for rid in command_resources
                                          for s in writers_by_command_resource.get(rid, set())}),
            "routed_commands": routed,
            "routed_commands_reason": (
                "" if command_resources else
                "no SYS-9 inventory link joins this registry entry to a command-layer "
                "resource, so which commands would route through it is not derivable "
                "from this evidence"),
            "scheduling_disposition": disposition,
            "scheduling_reason": reason,
            "scheduling_constraints": constraints["constraints"],
            "arbitration_policy_required": needs_access_point,
            "shared_access_point": (_access_point_name(registry_entry["resource_id"])
                                    if needs_access_point else NO_ACCESS_POINT),
            "access_point_status": ACCESS_POINT_STATUS,
            "registry_reuse_decision": decision or "",
            "evidence": sorted({e for rid in command_resources
                                for e in evidence_by_command_resource.get(rid, [])}
                               | set(registry_entry.get("evidence") or []))[:8],
        })

    # Command-axis-only shared agents: a resource two subsystems' command.txt
    # files both drive, which no registry entry claimed. This is the
    # `BFM:HOST_SIDE` shape -- a real shared physical agent evidenced by the
    # command layer, invisible to a connectivity matrix that has no subsystem
    # column. Dropping it because no registry entry linked to it would lose
    # exactly the finding SYS-24 is for.
    for rid in sorted(set(users_by_command_resource) - claimed_command_resources):
        consumers = sorted(users_by_command_resource[rid])
        contentions = sorted(contention_by_command_resource.get(rid, set()))
        constraints = _scheduling_constraints(None, contentions)
        if len(consumers) < 2:
            disposition, reason = SCHED_KEEP_SUBSYSTEM_LOCAL, (
                "only one selected subsystem's commands use this resource")
        elif not constraints["derived"]:
            disposition, reason = SCHED_UNKNOWN, constraints["reason"]
        else:
            disposition, reason = SCHED_SINGLE_SHARED_ACCESS_POINT, (
                f"{len(consumers)} selected subsystems' command.txt files use this one "
                "resource with at least one writer; every user routes through a single "
                "shared sequencer/driver/queue")
        needs_access_point = disposition == SCHED_SINGLE_SHARED_ACCESS_POINT
        rows.append({
            "shared_resource_key": rid,
            "resource_type": "",
            "protocol": "",
            "evidence_axes": [AXIS_COMMAND],
            "registry_entry_id": "",
            "command_resource_ids": [rid],
            "consumer_subsystems": consumers,
            "writing_subsystems": sorted(writers_by_command_resource.get(rid, set())),
            "routed_commands": sorted(commands_by_command_resource.get(rid, set())),
            "routed_commands_reason": "",
            "scheduling_disposition": disposition,
            "scheduling_reason": reason,
            "scheduling_constraints": constraints["constraints"],
            "arbitration_policy_required": needs_access_point,
            "shared_access_point": (_access_point_name(rid) if needs_access_point
                                    else NO_ACCESS_POINT),
            "access_point_status": ACCESS_POINT_STATUS,
            "registry_reuse_decision": "",
            "evidence": sorted(evidence_by_command_resource.get(rid, []))[:8],
        })

    rows.sort(key=lambda r: r["shared_resource_key"])
    by_disposition = {d: sum(1 for r in rows if r["scheduling_disposition"] == d)
                      for d in SYS24_DISPOSITIONS}
    return {
        "schema_version": SCHEMA_VERSION,
        "entries": rows,
        "summary": {
            "row_count": len(rows),
            "by_disposition": by_disposition,
            "shared_access_points_named": sum(
                1 for r in rows if r["shared_access_point"] != NO_ACCESS_POINT),
            "shared_access_points_built": 0,
            "command_resource_link_available": bool(links),
        },
    }


def check_no_global_serialization(scheduling: Mapping[str, Any],
                                  relationships: Mapping[str, Any],
                                  selected_subsystems: Sequence[str],
                                  ) -> Dict[str, Any]:
    """SYS-24's "Do not globally serialize independent subsystems", as a real
    check rather than an intention.

    Two subsystems are INDEPENDENT when no scheduling row lists both as
    consumers. The check is that no independent pair was nevertheless given a
    SERIALIZE_RESOURCE relationship and that no independent pair shares a
    serialization group -- the two ways a naive planner turns "serialize the
    contended pair" into "serialize everything".
    """
    subsystems = sorted(set(selected_subsystems))
    coupled: Set[Tuple[str, str]] = set()
    for row in scheduling.get("entries") or []:
        consumers = sorted(set(row.get("consumer_subsystems") or []))
        for i, a in enumerate(consumers):
            for b in consumers[i + 1:]:
                coupled.add((a, b))

    independent = [(a, b) for i, a in enumerate(subsystems) for b in subsystems[i + 1:]
                   if (a, b) not in coupled]

    violations: List[Dict[str, Any]] = []
    for pair in (relationships.get("pairs") or []):
        key = tuple(sorted((pair["subsystem_a"], pair["subsystem_b"])))
        if key not in set(independent):
            continue
        if pair["relationship"] == REL_SERIALIZE_RESOURCE:
            violations.append({
                "subsystems": list(key), "reason": "SERIALIZE_RESOURCE_ON_AN_INDEPENDENT_PAIR",
                "detail": pair["basis"], "pair_id": pair["pair_id"]})
        shared_groups = sorted(set(pair["serialization_groups_a"])
                               & set(pair["serialization_groups_b"]))
        if shared_groups:
            violations.append({
                "subsystems": list(key), "reason": "SHARED_SERIALIZATION_GROUP",
                "detail": f"both sides are in {shared_groups}", "pair_id": pair["pair_id"]})

    return {
        "verdict": GLOBAL_SERIALIZATION_DETECTED if violations else NO_GLOBAL_SERIALIZATION,
        "independent_subsystem_pairs": [list(p) for p in independent],
        "coupled_subsystem_pairs": [list(p) for p in sorted(coupled)],
        "violations": violations,
        "basis": ("two subsystems are independent when no shared-resource scheduling row "
                  "lists both as consumers; SYS-24 requires such a pair to stay "
                  "concurrent"),
    }


def resource_contention_gate_input(scheduling: Mapping[str, Any]) -> Dict[str, Any]:
    """The `shared_resources` half of the evidence block the ALREADY-WIRED
    `tools/verification_flow/system_level_resource_contention_gate.py` reads.

    That gate is real, registered in `gates.STAGE_GATES["SYSTEM_LEVEL"]` and
    documented in `prompts.py`. It checks that every scenario touching a shared
    resource declares an arbitration policy and contention tests. Its
    `shared_resources` list has until now been agent-supplied prose; this
    function derives it from the real registry/contract evidence instead, so
    the two mechanisms JOIN rather than becoming a second contention model.

    `scenarios` is deliberately EMPTY and says why. A scenario carries
    `contention_testcase_ids`, and inventing testcase ids for tests that do not
    exist is precisely the fabrication this whole layer refuses; deriving real
    ones needs the System-Level scenario model (SYS-30) and real testcases,
    both of which are SYS-40.
    """
    shared = sorted({row["shared_resource_key"] for row in scheduling.get("entries") or []
                     if row["arbitration_policy_required"]})
    return {
        "shared_resources": shared,
        "scenarios": [],
        "scenarios_not_derived_reason": (
            "a scenario entry requires contention_testcase_ids, which name real "
            "testcases. None exists at Phase 1 and inventing ids would fabricate "
            "verification evidence. Deriving them needs SYS-30's System-Level scenario "
            "model and real tests, which is SYS-40."),
        "derived_from": "dv_harness.system_scheduling_plan.plan_shared_resource_scheduling",
    }


# ===========================================================================
# SYS-25 -- PARALLELISM MODEL
# ===========================================================================

def _pair_signals(a: Mapping[str, Any], b: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Every SYS-25 signal that matched for one cross-subsystem command pair.

    Each signal names the field it was read from, so a verdict can be checked
    without re-deriving it. Nothing here re-decides resource contention:
    `scc.resolve_cross_subsystem_concurrency()` already computed the contended
    dependency list carried on each IR entry, and this reads it.
    """
    signals: List[Dict[str, Any]] = []
    deriv_a = a.get("derivation") or {}
    deriv_b = b.get("derivation") or {}

    contended_a = {d["resource_id"] for d in deriv_a.get("shared_resource_dependency") or []
                   if d.get("contention") != "READ_ONLY_SHARING"}
    contended_b = {d["resource_id"] for d in deriv_b.get("shared_resource_dependency") or []
                   if d.get("contention") != "READ_ONLY_SHARING"}
    shared_contended = sorted(contended_a & contended_b)
    if shared_contended:
        signals.append({
            "relationship": REL_SERIALIZE_RESOURCE,
            "from_field": "system_command_ir.derivation.shared_resource_dependency",
            "basis": ("both commands contend for " + ", ".join(shared_contended[:4])
                      + " with at least one writer, so they must not overlap"),
            "detail": shared_contended})

    # ORDER: one side's PRECEDING_INITIALIZATION precondition names the other
    # side's command. This is exactly the first of the two disturber rules
    # `scp._ordering_collisions()` already applies for SYS-22's ORDERING_CONFLICT
    # ("it invokes the same initialization again"), reused rather than re-argued:
    # an initialization is an act on shared state, so the other subsystem
    # re-performing it can invalidate the precondition this one depends on, and
    # neither file states an order between them.
    #
    # The IR's `dependencies` field (SYS-8's `ordering_constraints`) is
    # deliberately NOT a signal here. Those edges are WITHIN one file --
    # `_ordering_constraints_for()` reads one file's own statement stream -- so
    # an edge naming `` `CPUREAD4B `` says this file's write precedes this
    # file's read. Matching that name against another subsystem's identically
    # named command would claim a cross-subsystem order neither file states,
    # from nothing but a shared macro name, which is precisely the name-only
    # inference SYS-10's "do not decide duplicates by class names alone" rules
    # out. A precondition survives that test because the two sides are the same
    # ACT on shared state, not merely the same spelling.
    for first, second, first_id, second_id in (
            (a, b, a["system_command_id"], b["system_command_id"]),
            (b, a, b["system_command_id"], a["system_command_id"])):
        other_command = second["source_command"]
        for pre in first.get("preconditions") or []:
            if (pre.get("kind") == "PRECEDING_INITIALIZATION"
                    and str(pre.get("detail") or "") == other_command):
                signals.append({
                    "relationship": REL_ORDER_DEPENDENT,
                    "from_field": "system_command_ir.preconditions",
                    "basis": (f"{first_id} requires {other_command} to have run first "
                              f"({pre.get('kind')} cited at {pre.get('evidence')}), and "
                              f"{second_id} is that same initialization in another "
                              "subsystem, which can re-run it after this one depended "
                              "on it"),
                    "detail": [pre.get("evidence", "")]})

    # INTERRUPT: one side completes on an interrupt handshake and the two sides
    # share a resource or an address, so the handshake couples them. An
    # interrupt-completing command with nothing in common with the other side is
    # NOT reported -- that would make every interrupt-driven command dependent
    # on everything.
    common_resources = sorted(set(a.get("target_resource") or [])
                              & set(b.get("target_resource") or []))
    addresses_a = {d["address"] for d in deriv_a.get("address_dependency") or []}
    addresses_b = {d["address"] for d in deriv_b.get("address_dependency") or []}
    common_addresses = sorted(addresses_a & addresses_b)
    interrupt_sides = [e["system_command_id"] for e in (a, b)
                       if ((e.get("derivation") or {}).get("interrupt_dependency") or {}
                           ).get("depends_on_interrupt")]
    if interrupt_sides and (common_resources or common_addresses):
        signals.append({
            "relationship": REL_INTERRUPT_DEPENDENT,
            "from_field": "system_command_ir.derivation.interrupt_dependency",
            "basis": (f"{interrupt_sides} completes on an interrupt handshake and the "
                      "pair shares "
                      + (", ".join(common_resources[:3]) if common_resources
                         else ", ".join(common_addresses[:3]))
                      + ", so the handshake orders them against each other"),
            "detail": interrupt_sides})

    # CLOCK DOMAIN: the two commands' own SYS-8 clock-domain records resolve to
    # different domains while they share a resource or an address. A different
    # clock with nothing in common is two independent subsystems running on two
    # clocks, which is the normal case and not a dependency.
    clock_a = (deriv_a.get("clock_domain") or {}).get("clock") or ""
    clock_b = (deriv_b.get("clock_domain") or {}).get("clock") or ""
    if (clock_a and clock_b and clock_a != clock_b
            and (common_resources or common_addresses)):
        signals.append({
            "relationship": REL_CLOCK_DOMAIN_DEPENDENT,
            "from_field": "system_command_ir.derivation.clock_domain",
            "basis": (f"the two commands resolve to different clock domains "
                      f"({clock_a} vs {clock_b}) while sharing "
                      + (", ".join(common_resources[:3]) if common_resources
                         else ", ".join(common_addresses[:3]))
                      + ", so their interaction crosses a clock boundary"),
            "detail": [clock_a, clock_b]})

    if (a.get("parallel_group") and a["parallel_group"] != scp.PARALLEL_GROUP_UNDECIDABLE
            and b.get("parallel_group")
            and b["parallel_group"] != scp.PARALLEL_GROUP_UNDECIDABLE
            and not shared_contended and not common_resources and not common_addresses):
        signals.append({
            "relationship": REL_PARALLEL_SAFE,
            "from_field": "system_command_ir.parallel_group",
            "basis": ("cross-subsystem parallel safety was decided PARALLEL_SAFE for both "
                      "commands and they share no resource and no address"),
            "detail": [a["parallel_group"], b["parallel_group"]]})
    return signals


def classify_parallelism_relationships(ir: Mapping[str, Any]) -> Dict[str, Any]:
    """SYS-25 over every CROSS-SUBSYSTEM command pair in one IR.

    Pairs from the SAME subsystem are deliberately not classified: a
    command.txt is sequential by construction, so its own commands' order is
    already stated and the six-value vocabulary would carry no information for
    them. That is the same reasoning `scc.resolve_cross_subsystem_concurrency()`
    already applies to `parallel_safe`, reused rather than re-argued.
    """
    entries = list(ir.get("entries") or [])
    pairs: List[Dict[str, Any]] = []
    for i, a in enumerate(entries):
        for b in entries[i + 1:]:
            if a["source_subsystem"] == b["source_subsystem"]:
                continue
            signals = _pair_signals(a, b)
            matched = {s["relationship"] for s in signals}
            relationship = next((r for r in SYS25_PRECEDENCE if r in matched), REL_UNKNOWN)
            chosen = next((s for s in signals if s["relationship"] == relationship), None)
            pair_id = "SYSPAIR-" + hashlib.sha256(
                "|".join(sorted((a["system_command_id"], b["system_command_id"])))
                .encode("utf-8")).hexdigest()[:10].upper()
            pairs.append({
                "pair_id": pair_id,
                "command_a": a["system_command_id"],
                "command_b": b["system_command_id"],
                "subsystem_a": a["source_subsystem"],
                "subsystem_b": b["source_subsystem"],
                "relationship": relationship,
                "basis": (chosen["basis"] if chosen else
                          "no SYS-25 signal matched this pair: cross-subsystem parallel "
                          "safety was not decidable, and no contention, ordering, "
                          "interrupt or clock-domain evidence links the two commands"),
                "from_field": chosen["from_field"] if chosen else "",
                "also_matched": sorted(matched - {relationship}),
                "signals": signals,
                "serialization_groups_a": ([a["serialization_group"]]
                                           if a.get("serialization_group") else []),
                "serialization_groups_b": ([b["serialization_group"]]
                                           if b.get("serialization_group") else []),
            })

    pairs.sort(key=lambda p: (p["command_a"], p["command_b"]))
    by_relationship = {r: sum(1 for p in pairs if p["relationship"] == r)
                       for r in SYS25_RELATIONSHIPS}
    return {
        "schema_version": SCHEMA_VERSION,
        "relationships": list(SYS25_RELATIONSHIPS),
        "precedence": list(SYS25_PRECEDENCE),
        "pairs": pairs,
        "summary": {
            "pair_count": len(pairs),
            "by_relationship": by_relationship,
            "parallel_preserved": by_relationship[REL_PARALLEL_SAFE],
            "cross_subsystem_only": True,
        },
    }


# ===========================================================================
# SYS-26 -- SCOREBOARD INTEGRATION
# ===========================================================================

def _topology_descriptor_requirement(registry: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Which of the three parts of the missing cross-subsystem topology
    descriptor the CURRENT selection could actually supply, from real registry
    evidence.

    CLAUDE.md names the missing prerequisite as "a real cross-subsystem
    topology descriptor (address/interrupt/DMA maps)". Reporting a blanket
    "not available" would hide that a selection may already carry, say, real
    address regions and be missing only the interrupt map -- which is the
    difference between a small gap and a large one.
    """
    entries = list(registry.get("entries") or [])
    address_regions = sorted({
        str(region.get("name") or "")
        for entry in entries for domain in entry.get("address_domain") or []
        for region in domain.get("regions") or []} - {""})
    interrupt_entries = sorted({e["resource_id"] for e in entries
                                if e.get("resource_type") == sri.RT_INTERRUPT_AGENT})
    dma_entries = sorted({e["resource_id"] for e in entries
                          if e.get("resource_type") == sri.RT_DMA_MODEL})

    found = {TOPO_ADDRESS_MAP: address_regions,
             TOPO_INTERRUPT_MAP: interrupt_entries,
             TOPO_DMA_MAP: dma_entries}
    described = {
        TOPO_ADDRESS_MAP: ("which address ranges each subsystem sees and how one "
                           "subsystem's address maps into another's"),
        TOPO_INTERRUPT_MAP: ("which interrupt line each subsystem raises and which "
                             "agent observes it at System level"),
        TOPO_DMA_MAP: ("which DMA engine moves a payload between two subsystems and "
                       "what transformation it applies"),
    }
    return [{
        "part": part,
        "status": TOPO_PRESENT if found[part] else TOPO_ABSENT,
        "describes": described[part],
        "evidence": found[part][:6],
        "reason": ("" if found[part] else
                   f"no registry entry in this selection supplies {part} evidence"),
    } for part in TOPOLOGY_DESCRIPTOR_PARTS]


def plan_scoreboard_integration(registry: Mapping[str, Any],
                                selected_subsystems: Sequence[str],
                                *,
                                resource_analysis: Optional[Mapping[str, Any]] = None,
                                ) -> Dict[str, Any]:
    """SYS-26: "Default to reuse of existing subsystem scoreboards under a
    System Scoreboard/Correlation Layer."

    The REUSE half is stated per subsystem and is enforceable:
    `subsystem_scoreboard_modified` and `replaced_by_monolithic_scoreboard` are
    both False for every row and `assert_no_emitted_artifacts()` raises on
    either being True. That matters because in `soc_environment_composer` the
    same guarantee holds only BY OMISSION -- `_soc_tb_top()` instantiates each
    registered subsystem's own already-generated env class by name and there is
    simply no code path that could regenerate a scoreboard. An absence of a
    dangerous code path is a real guarantee, but it is not a CHECK, and a
    reader cannot tell the two apart from the outside. This makes it a check.

    The CORRELATION LAYER half is named, described and PLANNED_NOT_IMPLEMENTED.
    Its prerequisite -- the cross-subsystem topology descriptor -- is itemised
    part by part against real evidence rather than dismissed in one sentence,
    and the composer boundary is probed rather than cited.
    """
    scoreboards_by_subsystem: Dict[str, List[Dict[str, Any]]] = {
        sid: [] for sid in sorted(set(selected_subsystems))}
    inventory = (resource_analysis or {}).get("inventory") or {}
    for resource in inventory.get("resources") or []:
        if resource.get("resource_type") != sri.RT_SCOREBOARD:
            continue
        scoreboards_by_subsystem.setdefault(resource["owner_subsystem"], []).append({
            "resource_id": resource["resource_id"],
            "hierarchy": resource.get("hierarchy") or "",
            "evidence": list(resource.get("evidence") or [])[:3],
        })
    for entry in (registry.get("entries") or []):
        if entry.get("resource_type") != sri.RT_SCOREBOARD:
            continue
        for consumer in entry.get("consumer_subsystems") or []:
            rows = scoreboards_by_subsystem.setdefault(consumer, [])
            if not any(r["resource_id"] == entry["resource_id"] for r in rows):
                rows.append({"resource_id": entry["resource_id"],
                             "hierarchy": ", ".join(entry.get("physical_hierarchy") or []),
                             "evidence": list(entry.get("evidence") or [])[:3]})

    subsystems: List[Dict[str, Any]] = []
    for sid in sorted(scoreboards_by_subsystem):
        found = sorted(scoreboards_by_subsystem[sid], key=lambda r: r["resource_id"])
        subsystems.append({
            "subsystem_id": sid,
            "disposition": SCOREBOARD_REUSE_EXISTING if found else SCOREBOARD_NONE_IN_EVIDENCE,
            "subsystem_scoreboards": found,
            "subsystem_scoreboard_modified": False,
            "replaced_by_monolithic_scoreboard": False,
            "reason": (
                "this subsystem's own scoreboard is reused unmodified under the System "
                "correlation layer" if found else
                "no scoreboard resource for this subsystem appears in the SYS-9 inventory "
                "or the SYS-15 registry. That is an absence in the evidence, not a "
                "finding that the subsystem has none -- and it is never a reason to write "
                "a replacement"),
        })

    requirement = _topology_descriptor_requirement(registry)
    missing = [part["part"] for part in requirement if part["status"] == TOPO_ABSENT]
    return {
        "schema_version": SCHEMA_VERSION,
        "subsystems": subsystems,
        "system_correlation_layer": {
            "name": CORRELATION_LAYER_NAME,
            "status": CORRELATION_LAYER_STATUS,
            "sits_above": [s["subsystem_id"] for s in subsystems
                           if s["disposition"] == SCOREBOARD_REUSE_EXISTING],
            "replaces_subsystem_scoreboards": False,
            "purpose": ("correlate transactions that one subsystem's scoreboard saw leave "
                        "with what another subsystem's scoreboard saw arrive, leaving "
                        "each subsystem's own checking untouched"),
            "blocked_by": ("the cross-subsystem topology descriptor "
                           f"({', '.join(missing)}) is not available for this selection"
                           if missing else
                           "the correlation CONTENT itself: matching two subsystems' "
                           "transaction item types is protocol-behaviour content with no "
                           "primary source in registry metadata"),
            "topology_descriptor_requirement": requirement,
            "content_boundary": (
                "SYS-26's correlation CONTENT is not written at Phase 1. "
                "soc_environment_composer.end_to_end_scoreboard() states the same "
                "boundary in code and still raises; see composer_boundary below."),
        },
        "summary": {
            "subsystem_count": len(subsystems),
            "scoreboards_reused": sum(1 for s in subsystems
                                      if s["disposition"] == SCOREBOARD_REUSE_EXISTING),
            "scoreboards_modified": 0,
            "scoreboards_replaced": 0,
            "topology_descriptor_parts_available": sum(
                1 for p in requirement if p["status"] == TOPO_PRESENT),
            "topology_descriptor_parts_missing": len(missing),
        },
    }


# ===========================================================================
# SYS-27 -- CROSS-SUBSYSTEM CHECKING
# ===========================================================================

def _name_tokens(name: str) -> Set[str]:
    """Tokens of a subsystem/protocol name, for endpoint matching.

    A whole-token match with an optional trailing digit run, never a substring:
    `USB3` matches the token `USB`, `MIPI_CSI2` matches `CSI2` and `CSI`, and
    `SDIO` does NOT match `SD` -- `SDIO` is its own token in the flow table
    precisely so a substring rule is not needed to reach it.
    """
    tokens: Set[str] = set()
    for part in re.split(r"[^A-Za-z0-9]+", str(name or "").upper()):
        if not part:
            continue
        tokens.add(part)
        stripped = part.rstrip("0123456789")
        if stripped and stripped != part:
            tokens.add(stripped)
    return tokens


def _match_endpoint(group: Sequence[str], candidates: Mapping[str, Set[str]],
                    ) -> Optional[Tuple[str, str]]:
    """(subsystem_id, matched token) for the first candidate matching an
    endpoint group, or None."""
    for subsystem in sorted(candidates):
        for token in group:
            if token in candidates[subsystem]:
                return subsystem, token
    return None


def plan_cross_subsystem_checking(registry: Mapping[str, Any],
                                  selected_subsystems: Sequence[str],
                                  *,
                                  relationships: Optional[Mapping[str, Any]] = None,
                                  ) -> Dict[str, Any]:
    """SYS-27: evaluate SYS-27's own six candidate flows against the ACTUAL
    architecture of the current selection.

    SYS-27's rule is "Only create checks supported by actual SoC architecture",
    so this evaluates SUPPORT and creates no check. Support has two halves,
    each read from real evidence:

      * every ENDPOINT group must be matched by a DIFFERENT selected subsystem.
        The basis is a name-token match and is labelled as one -- a subsystem
        directory called `PCIE` is real evidence that a PCIe subsystem was
        selected, and pretending it is structural evidence would overstate it.
      * every INTERMEDIATE resource group must be satisfied by a real SYS-15
        registry entry of one of its types. This is structural: a DDR memory
        model either appears in the registry or it does not.

    A supported flow gets a `required_check_inputs` list, every entry
    NOT_AVAILABLE with the reason. That list is a description of what a check
    would need, never a check.
    """
    subsystems = sorted(set(selected_subsystems))
    candidates: Dict[str, Set[str]] = {sid: _name_tokens(sid) for sid in subsystems}
    for entry in (registry.get("entries") or []):
        protocol = str(entry.get("protocol") or "")
        if not protocol or protocol == conn.PROTOCOL_NOT_CLASSIFIED:
            continue
        for consumer in entry.get("consumer_subsystems") or []:
            candidates.setdefault(consumer, set()).update(_name_tokens(protocol))

    types_present: Dict[str, List[str]] = {}
    for entry in (registry.get("entries") or []):
        types_present.setdefault(str(entry.get("resource_type") or ""), []).append(
            entry["resource_id"])

    flows: List[Dict[str, Any]] = []
    for flow_id, text, endpoint_groups, intermediate_groups, minimum in SYS27_FLOWS:
        matched_endpoints: List[Dict[str, Any]] = []
        used: Set[str] = set()
        missing_endpoints: List[List[str]] = []
        for group in endpoint_groups:
            remaining = {k: v for k, v in candidates.items() if k not in used}
            hit = _match_endpoint(group, remaining)
            if hit is None:
                missing_endpoints.append(list(group))
                continue
            used.add(hit[0])
            matched_endpoints.append({
                "subsystem_id": hit[0], "matched_token": hit[1],
                "accepted_tokens": list(group),
                "basis": "SUBSYSTEM_OR_REGISTRY_PROTOCOL_NAME_TOKEN_MATCH"})

        satisfied: List[Dict[str, Any]] = []
        missing_resources: List[List[str]] = []
        for group in intermediate_groups:
            found = [rid for rtype in group for rid in types_present.get(rtype, [])]
            if found:
                satisfied.append({"accepted_types": list(group),
                                  "registry_entries": sorted(found)[:4],
                                  "basis": "SYSTEM_RESOURCE_REGISTRY_ENTRY_OF_THIS_TYPE"})
            else:
                missing_resources.append(list(group))

        participating = sorted({e["subsystem_id"] for e in matched_endpoints}
                               or set(subsystems))
        if missing_endpoints:
            verdict = FLOW_ENDPOINT_ABSENT
            reason = (f"no selected subsystem matches {missing_endpoints}; this flow "
                      "cannot be checked because one of its ends is not in the selection")
        elif missing_resources:
            verdict = FLOW_INTERMEDIATE_ABSENT
            reason = (f"no SYS-15 registry entry of type {missing_resources} exists in "
                      "this selection, so the intermediate stage of this flow is not "
                      "present in the architecture")
        elif len(participating) < minimum:
            verdict = FLOW_UNKNOWN
            reason = (f"the flow needs at least {minimum} participating subsystem(s) and "
                      f"{len(participating)} were resolved; support cannot be decided "
                      "from this evidence")
        else:
            verdict = FLOW_SUPPORTED
            reason = ("every endpoint and every intermediate resource this flow needs is "
                      "present in the selection's own evidence")

        flow: Dict[str, Any] = {
            "flow_id": flow_id,
            "flow": text,
            "verdict": verdict,
            "reason": reason,
            "participating_subsystems": participating,
            "matched_endpoints": matched_endpoints,
            "missing_endpoint_groups": missing_endpoints,
            "satisfied_intermediate_resources": satisfied,
            "missing_intermediate_resource_groups": missing_resources,
            "check_content_status": CHECK_CONTENT_NOT_GENERATED,
            "required_check_inputs": [],
            "cross_subsystem": len(participating) >= 2,
            "composition_gate_note": (
                "" if len(participating) >= 2 else
                "fewer than two participating subsystems: a scenario declared for this "
                "flow would be refused by system_level_composition_gate.py with "
                "NOT_CROSS_SUBSYSTEM_SCENARIO"),
        }
        if verdict == FLOW_SUPPORTED:
            flow["required_check_inputs"] = [{
                "input": name,
                "describes": describes,
                "availability": CHECK_INPUT_NOT_AVAILABLE,
                "reason": ("protocol-behaviour content with no primary source in "
                           "registry/qualification metadata; CLAUDE.md's 'No "
                           "Golden-Reference Content Mining' requires it be sourced from "
                           "primary per-subsystem VIP/DUT evidence, and writing it is "
                           "SYS-40"),
            } for name, describes in SYS27_REQUIRED_CHECK_INPUTS]
        flows.append(flow)

    by_verdict = {v: sum(1 for f in flows if f["verdict"] == v) for v in SYS27_FLOW_VERDICTS}
    coupled_pairs = sorted({tuple(sorted((p["subsystem_a"], p["subsystem_b"])))
                            for p in ((relationships or {}).get("pairs") or [])
                            if p["relationship"] != REL_PARALLEL_SAFE})
    return {
        "schema_version": SCHEMA_VERSION,
        "flows": flows,
        "summary": {
            "flow_count": len(flows),
            "by_verdict": by_verdict,
            "supported_flows": [f["flow_id"] for f in flows if f["verdict"] == FLOW_SUPPORTED],
            "checks_generated": 0,
            "coupled_subsystem_pairs": [list(p) for p in coupled_pairs],
        },
    }


# ===========================================================================
# SCENARIO-LEVEL PARALLEL EXECUTION SCHEDULING (additive; not one of SYS-23..27)
# ===========================================================================
#
# WHY THIS IS A GENUINE GAP, NOT A RESTATEMENT OF SYS-25 OR SYS-30
# -----------------------------------------------------------------
# SYS-25's own module docstring above says it plainly: "SYS-25 classifies
# command-pair RELATIONSHIPS. It schedules nothing." Its six-valued verdict is
# about a PAIR OF COMMANDS, and `check_no_global_serialization()` only asks
# whether two SUBSYSTEMS were wrongly serialized. Neither is a question about
# two whole SCENARIOS.
#
# `system_topology_analysis.plan_system_scenario_model()` (SYS-30) is the
# other near neighbour, and it is INSIDE-one-scenario scheduling: its
# `_block_plan()` groups ONE scenario's OWN commands into PARALLEL/SEQUENTIAL
# blocks. It never compares two DIFFERENT scenarios against each other, and it
# could not import this reasoning even if it wanted to say more -- that module
# already imports `system_scheduling_plan` (`from . import system_scheduling_
# plan as ssp`), so the reverse import would be circular. That is exactly why
# this capability belongs HERE, as an ADDITIVE extension of this module, and
# is exposed as a function any caller (including `system_topology_analysis.py`,
# which already holds SYS-30's scenario list) can call with plain,
# duck-typed scenario records -- never by this module importing that one.
#
# So the real, unmet question is: given two already-planned SYS-30-shaped
# scenarios (or any two named command sets with a declared participating-
# subsystem list), may they be DISPATCHED to run AT THE SAME TIME without
# contending for a resource SYS-24 already scheduled, or violating a
# relationship SYS-25 already classified? Nothing in this codebase answers
# that before this section.
#
# NO SECOND MODEL. Every fact this section reads is imported or re-read from
# THIS module's own SYS-24 `shared_resource_scheduling` output and SYS-25
# `parallelism_model` output -- both already computed once by
# `build_system_scheduling_plan()`. It re-derives no resource-sharing fact and
# no command-pair relationship a second way; it only asks what those two
# already-decided artifacts imply about a PAIR OF SCENARIOS built from them.
#
# WORST-WINS, LIKE EVERY OTHER GATE IN THIS FILE. A scenario pair is
# `SCENARIO_PARALLEL_SAFE` only when every one of the checks below comes back
# clean; a single blocking or unresolved signal fails the whole pair, exactly
# as SYS-25's own `SYS25_PRECEDENCE` picks the most restrictive matched signal
# rather than averaging.
#
# STILL PLANNING ONLY. This produces a scheduling PLAN -- a verdict a human or
# an LSF dispatcher would read before submitting two scenarios concurrently.
# It submits no job, runs no simulator, and emits no scenario body, parallel
# block, sequencer or arbiter -- the same SYS-40 boundary the rest of this
# file holds.

#: Every value this section can reach for one scenario PAIR, most restrictive
#: first. A pair reaches `SCENARIO_PARALLEL_SAFE` only by falling through all
#: four blocking/unresolved checks -- the same "residual, never asserted"
#: shape SYS-25's own `REL_PARALLEL_SAFE`/`REL_UNKNOWN` precedence already
#: uses.
SCENARIO_SERIALIZE_SHARED_SUBSYSTEM = "SCENARIO_SERIALIZE_SHARED_SUBSYSTEM_INSTANCE"
SCENARIO_SERIALIZE_SHARED_RESOURCE = "SCENARIO_SERIALIZE_SHARED_RESOURCE_CONTENTION"
SCENARIO_SERIALIZE_COMMAND_DEPENDENCY = "SCENARIO_SERIALIZE_COMMAND_DEPENDENCY"
SCENARIO_UNKNOWN = "SCENARIO_UNKNOWN_PENDING_EVIDENCE"
SCENARIO_PARALLEL_SAFE = "SCENARIO_PARALLEL_SAFE"

SCENARIO_SCHEDULING_PRECEDENCE: tuple = (
    SCENARIO_SERIALIZE_SHARED_SUBSYSTEM, SCENARIO_SERIALIZE_SHARED_RESOURCE,
    SCENARIO_SERIALIZE_COMMAND_DEPENDENCY, SCENARIO_UNKNOWN, SCENARIO_PARALLEL_SAFE,
)
SCENARIO_SCHEDULING_VERDICTS: tuple = SCENARIO_SCHEDULING_PRECEDENCE


def scenario_command_ids(scenario: Mapping[str, Any]) -> List[str]:
    """The `system_command_id` list a scenario record covers.

    Accepts a plain `command_ids` list (the generic, minimal shape), or the
    real `system_topology_analysis.plan_system_scenario_model()` (SYS-30)
    shape, whose commands live one level down inside `block_plan[].members[].
    system_command_id`. Reading the SYS-30 shape directly, rather than
    requiring a caller to flatten it first, is what lets this function be
    called with SYS-30's own scenario records unmodified.
    """
    if scenario.get("command_ids") is not None:
        return list(scenario["command_ids"])
    ids: List[str] = []
    for block in scenario.get("block_plan") or []:
        for member in block.get("members") or []:
            cid = member.get("system_command_id")
            if cid:
                ids.append(cid)
    return ids


def _relationship_pair_index(relationships: Mapping[str, Any],
                             ) -> Dict[Tuple[str, str], str]:
    """{sorted (command_a, command_b) -> relationship} off SYS-25's own pair
    list.

    This is the same lookup `system_topology_analysis._pair_relationship_
    index()` already builds one layer up -- reimplemented here, never
    imported, because that module imports THIS one (`from . import
    system_scheduling_plan as ssp`) and the reverse import would be circular.
    Both are a few lines over the SAME `relationships["pairs"]` list SYS-25
    produces; neither re-decides a relationship.
    """
    index: Dict[Tuple[str, str], str] = {}
    for pair in (relationships or {}).get("pairs") or []:
        key = tuple(sorted((pair["command_a"], pair["command_b"])))
        index[key] = pair["relationship"]
    return index


def _scenario_pair_signals(scenario_a: Mapping[str, Any], scenario_b: Mapping[str, Any],
                           command_ids_a: Sequence[str], command_ids_b: Sequence[str],
                           known_command_ids: Set[str],
                           pair_index: Mapping[Tuple[str, str], str],
                           scheduling: Mapping[str, Any],
                           ) -> List[Dict[str, Any]]:
    """Every blocking/unresolved signal for one scenario pair, each naming the
    real field it was read from -- the SYS-25 `_pair_signals()` shape, one
    granularity up."""
    signals: List[Dict[str, Any]] = []
    subsystems_a = set(scenario_a.get("participating_subsystems") or [])
    subsystems_b = set(scenario_b.get("participating_subsystems") or [])
    shared_subsystems = sorted(subsystems_a & subsystems_b)
    if shared_subsystems:
        signals.append({
            "verdict": SCENARIO_SERIALIZE_SHARED_SUBSYSTEM,
            "from_field": "scenario.participating_subsystems",
            "basis": (f"both scenarios include subsystem(s) {shared_subsystems}; that "
                      "subsystem's own command.txt is sequential by construction and this "
                      "evidence models one running instance of it, so two scenarios "
                      "sharing it cannot be certified to run concurrently from this "
                      "evidence"),
            "detail": shared_subsystems,
        })

    set_a, set_b = set(command_ids_a), set(command_ids_b)
    for row in scheduling.get("entries") or []:
        if row.get("scheduling_disposition") != SCHED_SINGLE_SHARED_ACCESS_POINT:
            continue
        routed = set(row.get("routed_commands") or [])
        hit_a = sorted(routed & set_a)
        hit_b = sorted(routed & set_b)
        if hit_a and hit_b:
            signals.append({
                "verdict": SCENARIO_SERIALIZE_SHARED_RESOURCE,
                "from_field": "shared_resource_scheduling.entries.routed_commands",
                "basis": (f"both scenarios route commands through the single shared "
                          f"access point SYS-24 named for {row['shared_resource_key']} "
                          f"({row['shared_access_point']}); every user must route through "
                          "it, so the two scenarios cannot arbitrate it concurrently"),
                "detail": {"shared_resource_key": row["shared_resource_key"],
                           "commands_a": hit_a[:4], "commands_b": hit_b[:4]},
            })

    unresolved: List[Tuple[str, str]] = []
    for command_a in sorted(set_a):
        for command_b in sorted(set_b):
            key = tuple(sorted((command_a, command_b)))
            relationship = pair_index.get(key)
            if relationship is not None:
                if relationship != REL_PARALLEL_SAFE:
                    signals.append({
                        "verdict": SCENARIO_SERIALIZE_COMMAND_DEPENDENCY,
                        "from_field": "parallelism_model.pairs",
                        "basis": (f"SYS-25 classified {command_a} / {command_b} as "
                                  f"{relationship}, which forbids running them "
                                  "concurrently"),
                        "detail": {"command_a": command_a, "command_b": command_b,
                                  "relationship": relationship},
                    })
            elif command_a not in known_command_ids or command_b not in known_command_ids:
                # A command this evidence never covers. Never same-subsystem: that
                # case is excluded from SYS-25's own pairing (see `classify_
                # parallelism_relationships`) and is already reported above via
                # `shared_subsystems`, not silently re-flagged as an evidence gap.
                unresolved.append((command_a, command_b))
    if unresolved:
        signals.append({
            "verdict": SCENARIO_UNKNOWN,
            "from_field": "parallelism_model.pairs",
            "basis": ("at least one command pair between these scenarios names a command "
                      "absent from the SYS-21 command IR this parallelism model was built "
                      "from, so its relationship could not be classified"),
            "detail": {"unresolved_pairs": [list(p) for p in unresolved[:4]],
                      "unresolved_pair_count": len(unresolved)},
        })
    return signals


def evaluate_scenario_pair_parallel_safety(scenario_a: Mapping[str, Any],
                                           scenario_b: Mapping[str, Any],
                                           ir: Mapping[str, Any],
                                           scheduling: Mapping[str, Any],
                                           relationships: Mapping[str, Any],
                                           ) -> Dict[str, Any]:
    """One scenario PAIR's parallel-execution verdict, from the SAME SYS-24
    `shared_resource_scheduling` and SYS-25 `parallelism_model` documents
    `build_system_scheduling_plan()` already produced. Re-derives neither.

    `ir` is the SYS-21 System Command IR the `relationships` argument was
    classified from (`classify_parallelism_relationships(ir)`'s own input) --
    passed explicitly, never re-read from a global, so a caller cannot get a
    scenario-scheduling verdict decided against evidence the relationships
    model was not actually built from.
    """
    command_ids_a = scenario_command_ids(scenario_a)
    command_ids_b = scenario_command_ids(scenario_b)
    known_command_ids = {e["system_command_id"] for e in (ir.get("entries") or [])}

    scenario_pair_id = "SCENPAIR-" + hashlib.sha256(
        "|".join(sorted((str(scenario_a.get("scenario_id") or ""),
                         str(scenario_b.get("scenario_id") or ""))))
        .encode("utf-8")).hexdigest()[:10].upper()

    if not command_ids_a or not command_ids_b:
        return {
            "scenario_pair_id": scenario_pair_id,
            "scenario_a": scenario_a.get("scenario_id") or "",
            "scenario_b": scenario_b.get("scenario_id") or "",
            "verdict": SCENARIO_UNKNOWN,
            "basis": ("at least one of the two scenarios supplies no command_ids to "
                      "evaluate, so a parallel-safety verdict is not decidable from this "
                      "evidence"),
            "from_field": "",
            "also_matched": [],
            "signals": [],
            "command_count_a": len(command_ids_a),
            "command_count_b": len(command_ids_b),
        }

    pair_index = _relationship_pair_index(relationships)
    signals = _scenario_pair_signals(scenario_a, scenario_b, command_ids_a, command_ids_b,
                                     known_command_ids, pair_index, scheduling)
    matched = {s["verdict"] for s in signals}
    verdict = next((v for v in SCENARIO_SCHEDULING_PRECEDENCE if v in matched),
                   SCENARIO_PARALLEL_SAFE)
    chosen = next((s for s in signals if s["verdict"] == verdict), None)
    return {
        "scenario_pair_id": scenario_pair_id,
        "scenario_a": scenario_a.get("scenario_id") or "",
        "scenario_b": scenario_b.get("scenario_id") or "",
        "verdict": verdict,
        "basis": (chosen["basis"] if chosen else
                  "no blocking signal matched: the two scenarios share no subsystem, no "
                  "SYS-24 shared access point routes commands from both, and every "
                  "cross-subsystem command pair between them was classified "
                  f"{REL_PARALLEL_SAFE}"),
        "from_field": chosen["from_field"] if chosen else "",
        "also_matched": sorted(matched - {verdict}),
        "signals": signals,
        "command_count_a": len(command_ids_a),
        "command_count_b": len(command_ids_b),
    }


def schedule_scenario_parallel_execution(scenarios: Sequence[Mapping[str, Any]],
                                         ir: Mapping[str, Any],
                                         scheduling: Mapping[str, Any],
                                         relationships: Mapping[str, Any],
                                         ) -> Dict[str, Any]:
    """Every scenario PAIR's parallel-execution verdict, over a caller-supplied
    scenario list -- typically SYS-30's own `system_scenario_model["scenarios"]`
    -- against THIS module's own SYS-24/SYS-25 evidence.

    This is a SCHEDULING DECISION about which already-planned scenarios may be
    DISPATCHED at the same time; it submits no job, runs no simulator, and
    generates no scenario body, parallel block, sequencer or arbiter -- the
    same SYS-40 boundary `PHASE_BOUNDARY` states for the rest of this module.
    """
    scenarios = list(scenarios)
    pairs: List[Dict[str, Any]] = []
    for i, scenario_a in enumerate(scenarios):
        for scenario_b in scenarios[i + 1:]:
            pairs.append(evaluate_scenario_pair_parallel_safety(
                scenario_a, scenario_b, ir, scheduling, relationships))
    pairs.sort(key=lambda p: (p["scenario_a"], p["scenario_b"]))
    by_verdict = {v: sum(1 for p in pairs if p["verdict"] == v)
                 for v in SCENARIO_SCHEDULING_VERDICTS}
    return {
        "schema_version": SCHEMA_VERSION,
        "verdicts": list(SCENARIO_SCHEDULING_VERDICTS),
        "precedence": list(SCENARIO_SCHEDULING_PRECEDENCE),
        "scenario_count": len(scenarios),
        "pairs": pairs,
        "summary": {
            "pair_count": len(pairs),
            "by_verdict": by_verdict,
            "parallel_safe_pairs": by_verdict[SCENARIO_PARALLEL_SAFE],
        },
        "scenario_execution_boundary": (
            "This is a scheduling DECISION about which already-planned SYS-30 scenarios "
            "may be dispatched concurrently. No job is submitted, no simulator is run, "
            "and no scenario body, parallel block, sequencer or arbiter is generated by "
            "this function or anything it calls. Every signal is read from this module's "
            "own already-computed SYS-24 shared_resource_scheduling and SYS-25 "
            "parallelism_model; nothing here re-derives resource sharing or command-pair "
            "safety a second way."),
    }


def render_scenario_parallel_schedule_table(schedule: Mapping[str, Any]) -> str:
    columns = ["SCENARIO A", "SCENARIO B", "VERDICT", "ALSO MATCHED"]
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for pair in schedule.get("pairs") or []:
        lines.append("| " + " | ".join(_cell(v) for v in (
            pair["scenario_a"], pair["scenario_b"], pair["verdict"],
            ",".join(pair["also_matched"]) or "-",
        )) + " |")
    if len(lines) == 2:
        lines.append("| _(fewer than two scenarios supplied)_ |" + " - |" * (len(columns) - 1))
    return "\n".join(lines)


# ===========================================================================
# Composition
# ===========================================================================

def build_system_scheduling_plan(integration_plan: Mapping[str, Any],
                                 command_plan: Mapping[str, Any],
                                 *,
                                 resource_analysis: Optional[Mapping[str, Any]] = None,
                                 selection: Optional[Mapping[str, Any]] = None,
                                 ) -> Dict[str, Any]:
    """SYS-23 -> SYS-24 -> SYS-25 -> SYS-26 -> SYS-27 over one SYS-15..17
    integration plan and one SYS-18..22 command plan. Reads only; writes
    nothing anywhere, and this module holds no file writer at all."""
    registry = integration_plan.get("system_resource_registry") or {"entries": []}
    ir = command_plan.get("system_command_ir") or {"entries": []}
    collisions = command_plan.get("command_collisions") or {"collisions": []}

    selected = list((selection or {}).get("selected")
                    or (command_plan.get("summary") or {}).get("selected_subsystems")
                    or registry.get("subsystems") or [])
    if not selected:
        selected = sorted({e["source_subsystem"] for e in (ir.get("entries") or [])})

    dedup = classify_initialization_deduplication(ir, collisions, registry)
    scheduling = plan_shared_resource_scheduling(
        ir, registry, resource_analysis=resource_analysis)
    relationships = classify_parallelism_relationships(ir)
    serialization_check = check_no_global_serialization(scheduling, relationships, selected)
    scoreboards = plan_scoreboard_integration(
        registry, selected, resource_analysis=resource_analysis)
    checking = plan_cross_subsystem_checking(registry, selected,
                                             relationships=relationships)
    boundary = probe_composer_boundary()

    document = {
        "schema_version": SCHEMA_VERSION,
        "selected_subsystems": sorted(selected),
        "initialization_deduplication": dedup,
        "shared_resource_scheduling": scheduling,
        "global_serialization_check": serialization_check,
        "resource_contention_gate_input": resource_contention_gate_input(scheduling),
        "parallelism_model": relationships,
        "scoreboard_integration": scoreboards,
        "cross_subsystem_checking": checking,
        "composer_boundary": boundary,
        "summary": {
            "selected_subsystems": sorted(selected),
            "commands_classified": dedup["summary"]["entry_count"],
            "deduplication_candidates": dedup["summary"]["deduplication_candidates"],
            "commands_removed": 0,
            "shared_resource_rows": scheduling["summary"]["row_count"],
            "shared_access_points_named": scheduling["summary"]["shared_access_points_named"],
            "shared_access_points_built": 0,
            "global_serialization_verdict": serialization_check["verdict"],
            "command_pairs_classified": relationships["summary"]["pair_count"],
            "parallel_pairs_preserved": relationships["summary"]["parallel_preserved"],
            "scoreboards_reused": scoreboards["summary"]["scoreboards_reused"],
            "scoreboards_replaced": 0,
            "supported_flows": checking["summary"]["supported_flows"],
            "checks_generated": 0,
            "composer_boundary_intact": boundary["boundary_intact"],
            "scheduling_plan_clean": (
                serialization_check["verdict"] == NO_GLOBAL_SERIALIZATION
                and scheduling["summary"]["by_disposition"][SCHED_NOT_SCHEDULABLE] == 0
                and boundary["boundary_intact"]),
        },
        "artifacts_generated": [],
        "phase_boundary": PHASE_BOUNDARY,
    }
    assert_no_emitted_artifacts(document)
    return document


def plan_system_scheduling(root, selected: Sequence[str], *,
                           declared: Optional[Mapping[str, Any]] = None,
                           knowledge_center_client: Any = None,
                           inventory_overlay_path=None,
                           ) -> Dict[str, Any]:
    """Front door: SYS-1 selection -> SYS-5..8 analysis -> SYS-9..14 resources
    -> SYS-15..17 registry/matrices -> SYS-18..22 command plan -> SYS-23..27
    scheduling/parallelism/scoreboard/checking plan.

    The whole lower stack is reused through
    `system_command_plan.plan_system_commands()`, which itself goes through
    `subsystem_discovery.require_explicit_selection()` -- so SYS-1's refusal to
    compose a set the user did not choose is not bypassed by adding a verb on
    top of it.
    """
    result = scp.plan_system_commands(
        root, selected, declared=declared,
        knowledge_center_client=knowledge_center_client,
        inventory_overlay_path=inventory_overlay_path)
    scheduling_plan = build_system_scheduling_plan(
        result["integration_plan"], result["command_plan"],
        resource_analysis=result.get("resource_analysis"),
        selection=result["selection"])
    return {**result, "scheduling_plan": scheduling_plan}


# ===========================================================================
# Reporting
# ===========================================================================

def validate_system_scheduling_plan(document: Mapping[str, Any]) -> None:
    """Validate a `build_system_scheduling_plan()` document against the real
    JSON schema. Raises jsonschema.ValidationError on a violation."""
    import jsonschema
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(document, schema)


def _cell(value: Any) -> str:
    """Markdown cell text with pipes escaped -- a value containing `|` must not
    silently gain a column."""
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_initialization_deduplication_table(dedup: Mapping[str, Any]) -> str:
    columns = ["SYSTEM_COMMAND_ID", "SUBSYSTEM", "CATEGORY", "SCOPE CLASS", "ACTION",
               "EVIDENCE SIDES"]
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for entry in dedup.get("entries") or []:
        lines.append("| " + " | ".join(_cell(v) for v in (
            entry["system_command_id"], entry["source_subsystem"],
            entry["command_category"] or "-", entry["scope_class"],
            entry["deduplication_action"],
            ",".join(sorted(entry["evidence_by_subsystem"])) or "-",
        )) + " |")
    if len(lines) == 2:
        lines.append("| _(no command classified)_ |" + " - |" * (len(columns) - 1))
    return "\n".join(lines)


def render_shared_resource_scheduling_table(scheduling: Mapping[str, Any]) -> str:
    columns = ["SHARED RESOURCE", "AXES", "CONSUMERS", "ROUTED COMMANDS", "DISPOSITION",
               "SHARED ACCESS POINT", "STATUS"]
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for row in scheduling.get("entries") or []:
        lines.append("| " + " | ".join(_cell(v) for v in (
            row["shared_resource_key"], ",".join(row["evidence_axes"]),
            ",".join(row["consumer_subsystems"]) or "-",
            len(row["routed_commands"]), row["scheduling_disposition"],
            row["shared_access_point"], row["access_point_status"],
        )) + " |")
    if len(lines) == 2:
        lines.append("| _(no shared resource in this selection)_ |"
                     + " - |" * (len(columns) - 1))
    return "\n".join(lines)


def render_parallelism_table(relationships: Mapping[str, Any]) -> str:
    columns = ["PAIR", "COMMAND A", "COMMAND B", "RELATIONSHIP", "ALSO MATCHED"]
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for pair in relationships.get("pairs") or []:
        lines.append("| " + " | ".join(_cell(v) for v in (
            pair["pair_id"], pair["command_a"], pair["command_b"],
            pair["relationship"], ",".join(pair["also_matched"]) or "-",
        )) + " |")
    if len(lines) == 2:
        lines.append("| _(no cross-subsystem command pair)_ |" + " - |" * (len(columns) - 1))
    return "\n".join(lines)


def render_cross_subsystem_flow_table(checking: Mapping[str, Any]) -> str:
    columns = ["FLOW", "VERDICT", "PARTICIPATING SUBSYSTEMS", "CHECK CONTENT"]
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for flow in checking.get("flows") or []:
        lines.append("| " + " | ".join(_cell(v) for v in (
            flow["flow"], flow["verdict"],
            ",".join(flow["participating_subsystems"]) or "-",
            flow["check_content_status"],
        )) + " |")
    return "\n".join(lines)


def format_system_scheduling_plan_report(document: Mapping[str, Any]) -> str:
    """The SYS-23..SYS-27 deliverable. Reporting only -- this function emits no
    SystemVerilog, no command.txt, no sequencer and no checker."""
    summary = document["summary"]
    dedup = document["initialization_deduplication"]
    scheduling = document["shared_resource_scheduling"]
    serialization = document["global_serialization_check"]
    relationships = document["parallelism_model"]
    scoreboards = document["scoreboard_integration"]
    checking = document["cross_subsystem_checking"]
    boundary = document["composer_boundary"]

    out = ["# SYSTEM SCHEDULING, PARALLELISM, SCOREBOARD AND CHECKING PLAN "
           "(SYS-23..SYS-27)", "",
           f"- selected subsystems: {summary['selected_subsystems']}",
           f"- commands classified: {summary['commands_classified']} "
           f"({summary['deduplication_candidates']} deduplication candidate(s); "
           f"{summary['commands_removed']} removed)",
           f"- shared resources scheduled: {summary['shared_resource_rows']} "
           f"({summary['shared_access_points_named']} access point(s) NAMED, "
           f"{summary['shared_access_points_built']} built)",
           f"- global serialization: {summary['global_serialization_verdict']}",
           f"- command pairs classified: {summary['command_pairs_classified']} "
           f"({summary['parallel_pairs_preserved']} kept PARALLEL_SAFE)",
           f"- subsystem scoreboards reused: {summary['scoreboards_reused']} "
           f"({summary['scoreboards_replaced']} replaced)",
           f"- architecturally supported flows: {summary['supported_flows']} "
           f"({summary['checks_generated']} checks generated)",
           f"- composer boundary intact: {summary['composer_boundary_intact']}",
           f"- scheduling plan clean: {summary['scheduling_plan_clean']}", "",
           "## SYS-23 INITIALIZATION DEDUPLICATION", "",
           f"Classes: {', '.join(SYS23_CLASSES)}.", "",
           render_initialization_deduplication_table(dedup), "",
           "No command is removed, merged or reordered by this report. SYS-23's own "
           "rule is \"Do not remove commands without evidence\", so the strongest "
           f"action available here is {DEDUP_CANDIDATE}, which requires a real citation "
           f"from at least {MIN_EVIDENCE_SIDES_FOR_CANDIDATE} different subsystems and "
           "hands the decision to a human. Editing a subsystem's command.txt is SYS-40.",
           ""]

    candidates = [e for e in dedup["entries"] if e["deduplication_action"] == DEDUP_CANDIDATE]
    if candidates:
        out += ["### Deduplication candidates", ""]
        for entry in candidates:
            out.append(f"- **{entry['system_command_id']}** ({entry['scope_class']}): "
                       f"{entry['scope_basis']}")
            for sid, citations in sorted(entry["evidence_by_subsystem"].items()):
                out.append(f"  - {sid}: {citations[:2]}")
        out.append("")

    out += ["## SYS-24 SHARED RESOURCE SCHEDULING", "",
            render_shared_resource_scheduling_table(scheduling), "",
            "Every access point above is a NAME with status "
            f"{ACCESS_POINT_STATUS}. A sequencer, a driver, a queue and an arbiter are "
            "code, and code is SYS-40. Each row's scheduling decision cites the real "
            "resource/protocol constraint fields it was derived from; a row with no "
            f"derivable constraint reports {SCHED_UNKNOWN} rather than a default policy.",
            "",
            f"**Global serialization check**: {serialization['verdict']}. "
            f"Independent subsystem pairs kept parallel: "
            f"{serialization['independent_subsystem_pairs']}.", ""]
    if serialization["violations"]:
        out += ["### Independent subsystems that were serialized anyway", ""]
        for violation in serialization["violations"]:
            out.append(f"- {violation['subsystems']}: {violation['reason']} -- "
                       f"{violation['detail']}")
        out.append("")

    gate_input = document["resource_contention_gate_input"]
    out += [f"Shared resources for `system_level_resource_contention_gate.py`: "
            f"{gate_input['shared_resources']}. "
            f"{gate_input['scenarios_not_derived_reason']}", ""]

    out += ["## SYS-25 PARALLELISM MODEL", "",
            f"Relationships: {', '.join(SYS25_RELATIONSHIPS)}. Precedence when more "
            f"than one signal matches, most restrictive first: "
            f"{' > '.join(SYS25_PRECEDENCE)}.", "",
            render_parallelism_table(relationships), "",
            "Only CROSS-SUBSYSTEM pairs are classified: a command.txt is sequential by "
            "construction, so a pair from one subsystem has its order already stated. "
            "Every signal that matched is kept in ALSO MATCHED, so choosing one verdict "
            "never discards the other reason a pair is coupled.", ""]

    out += ["## SYS-26 SCOREBOARD INTEGRATION", "",
            "| SUBSYSTEM | DISPOSITION | SCOREBOARDS | MODIFIED | REPLACED |",
            "|---|---|---|---|---|"]
    for row in scoreboards["subsystems"]:
        out.append("| {} | {} | {} | {} | {} |".format(
            _cell(row["subsystem_id"]), _cell(row["disposition"]),
            len(row["subsystem_scoreboards"]),
            row["subsystem_scoreboard_modified"], row["replaced_by_monolithic_scoreboard"]))
    if not scoreboards["subsystems"]:
        out.append("| _(no subsystem analysed)_ | - | - | - | - |")
    correlation = scoreboards["system_correlation_layer"]
    out += ["", f"`{correlation['name']}` is {correlation['status']}. "
            f"{correlation['purpose']}. Blocked by: {correlation['blocked_by']}.", "",
            "| TOPOLOGY DESCRIPTOR PART | STATUS | DESCRIBES |", "|---|---|---|"]
    for part in correlation["topology_descriptor_requirement"]:
        out.append("| {} | {} | {} |".format(
            _cell(part["part"]), _cell(part["status"]), _cell(part["describes"])))
    out += ["", "No subsystem scoreboard is modified or replaced. SYS-26's default is "
            "reuse, and this plan never proposes the monolithic replacement its second "
            "sentence warns against.", ""]

    out += ["## SYS-27 CROSS-SUBSYSTEM CHECKING", "",
            render_cross_subsystem_flow_table(checking), "",
            "SYS-27's rule is \"Only create checks supported by actual SoC "
            "architecture\". A flow is SUPPORTED only when every endpoint is a "
            "different selected subsystem and every intermediate resource is a real "
            "SYS-15 registry entry. A supported flow gets a list of what a real check "
            "would NEED; no check is written.", ""]
    supported = [f for f in checking["flows"] if f["verdict"] == FLOW_SUPPORTED]
    if supported:
        out += ["### What a supported flow's check would require", ""]
        for flow in supported:
            out.append(f"- **{flow['flow']}** ({flow['participating_subsystems']}):")
            for required in flow["required_check_inputs"]:
                out.append(f"  - {required['input']} [{required['availability']}]: "
                           f"{required['describes']}")
        out.append("")

    out += ["## COMPOSER BOUNDARY (checked, not asserted)", "",
            f"`{boundary['module']}` -- boundary intact: {boundary['boundary_intact']}."]
    for probe in boundary["probes"]:
        out.append(f"- `{probe['function']}()` raises "
                   f"{probe['raises'] or 'NOTHING -- IT HAS BEEN IMPLEMENTED'}")
    out += ["", boundary["meaning"], "",
            "## PHASE BOUNDARY", "", document["phase_boundary"]]
    return "\n".join(out)
