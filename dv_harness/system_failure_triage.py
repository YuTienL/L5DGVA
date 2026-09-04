"""SYS-31 and SYS-32 of the System-Level Verification Integration workflow:
SUBSYSTEM FAILURE ISOLATION (the record shape a multi-subsystem failure keeps)
and SYSTEM FAILURE TRIAGE (local vs cross-subsystem, and which mechanism
caused it).

WHAT THIS MODULE IS NOT
-----------------------
It reports on failures. It fixes nothing, runs nothing, and generates no
System-Level UVM source, System command.txt, virtual sequencer or command
router. A triage verdict is a CLASSIFICATION with its evidence attached, and
every classification names the upstream row it was decided from so a reader
can go and check it.

It also does not decide a ROOT CAUSE. SYS-32's word is "determine local vs
cross-subsystem ... or genuine SoC integration bug" -- a LOCUS, i.e. where to
look. `prior_evidence` is prior evidence, never an accepted root cause, per
the Engineering Memory Policy's own rule and `search_related_memory_for_
debug()`'s own docstring.

WHY A NEW MODULE RATHER THAN AN EXTENSION
-----------------------------------------
`memory_vault.build_failure_signature()` and the `job_failure` record
`lsf_client.py` builds around it are ONE-JOB, ONE-SUBSYSTEM by construction:
one `protocol`, one `pattern`, one `fsdb_path`, one sim.log. SYS-31's whole
point is that a System scenario's failure is N of those plus the scenario
that ties them together, and neither of those two files has a place to put an
N-sided record without changing what a job record means. So the join lives
here and the two existing shapes are reused verbatim:

  * `memory_vault.build_failure_signature()` builds every per-subsystem
    signature. This module defines no second symptom shape. The two SYS-31
    dimensions that signature genuinely lacked, `vip_agent` and `resource`,
    were added THERE as optional fields (see its own docstring for why they
    are omitted when absent rather than always present) instead of being
    re-invented here.
  * `memory_vault.search_related_memory_for_debug()` supplies prior evidence,
    unchanged, from the same two sources (vault Markdown + evidence DuckDB) as
    every other debug path.
  * `inference.score_confidence()` supplies CONFIDENCE. SYS-31 names it as a
    dimension the record must PRESERVE; the number itself is the existing
    Hypothesis->Evidence->Confidence math, not a second scale invented here.
  * `qualified_conclusion.QualifiedConclusion` is carried when a caller has
    one, never recomputed.

WHY THE CLASSIFIER CONSULTS RATHER THAN DERIVES
-----------------------------------------------
Four of SYS-32's seven causes are questions other requirements already
answer, and re-deriving any of them here would create a second opinion that
will eventually disagree with the first:

  * duplicate driver   -> the SYS-15 registry's own `conflict_status`
                          (`DRIVER_CONFLICT`), decided by SYS-10..SYS-14.
  * address conflict   -> a SYS-28 `ADDRESS_OVERLAP_CONFLICT` row.
  * clock/reset        -> a SYS-29 CONFLICTING_*/CDC_BOUNDARY row.
  * shared resource    -> a SYS-24 scheduling row that routes two subsystems
                          through one shared access point.
  * command ordering   -> a SYS-25 ORDER_DEPENDENT pair, or a SYS-22
                          ORDERING_CONFLICT collision.

So `triage_system_failure()` takes those documents as inputs and matches the
FAILING record against them. When an input is not supplied, the causes it
would have decided are reported as NOT_CONSULTED rather than as absent
evidence for the negative -- "we did not look" and "we looked and found
nothing" are different findings, and a triage report that conflated them
would quietly upgrade every unexamined failure to
GENUINE_SOC_INTEGRATION_BUG.

WHY EVERY MATCH IS EVIDENCE-LINKED, NEVER NAME-ONLY
---------------------------------------------------
A cause fires only when the FAILING record's own `resource`/`vip_agent`/
`command`/`subsystem` value appears in the upstream row -- not when a name
merely looks similar. That is SYS-10's "do not decide duplicates by class
names alone" applied to triage: a registry entry in DRIVER_CONFLICT somewhere
in the selection is not evidence that THIS failure was caused by it, and
reporting it as such would be a confident-looking guess.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from . import inference
from . import memory_vault as mv
from . import system_command_plan as scp
from . import system_resource_registry as srr
from . import system_scheduling_plan as ssp
from . import system_topology_analysis as sta

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "system_failure_triage.schema.json"
RECORD_SCHEMA_PATH = (Path(__file__).resolve().parent / "schemas"
                      / "system_failure_record.schema.json")
SCHEMA_VERSION = "1.0"


# ===========================================================================
# SYS-31 vocabulary
# ===========================================================================

#: SYS-31's mandated dimensions, verbatim and in the requirement's own order:
#: "Preserve SYSTEM SCENARIO / SUBSYSTEM / COMMAND / VIP-AGENT / RESOURCE /
#:  UVM_ERROR / LOG / WAVEFORM / ROOT-CAUSE HYPOTHESIS / CONFIDENCE."
#: Ten, each a DISTINCT key on the record. A test holds this tuple to that
#: sentence and to the record's own keys, so neither can quietly drop one.
SYS31_DIMENSIONS: tuple = (
    "system_scenario",
    "subsystem",
    "command",
    "vip_agent",
    "resource",
    "uvm_error",
    "log",
    "waveform",
    "root_cause_hypothesis",
    "confidence",
)

#: What a dimension says when its source genuinely captured nothing. A
#: distinct sentinel rather than "" or None, because a report reading
#: `waveform: ""` cannot tell "no FSDB was dumped" from "the field was never
#: filled in", and those have different next actions.
NOT_CAPTURED = "NOT_CAPTURED"

#: SYS-31's closing rule: "Never collapse all failures into generic System
#: failure." `assert_not_collapsed()` is that rule as a runtime check, and the
#: schema enforces the structural half.
COLLAPSE_RULE = (
    "SYS-31: a System-level failure record keeps one sub-record per failing "
    "subsystem, each with its own ten dimensions; it never reduces them to a "
    "single generic System failure."
)


# ===========================================================================
# SYS-32 vocabulary
# ===========================================================================

#: SYS-32's own list: "determine local vs cross-subsystem, shared-resource
#: cause, command ordering, duplicate driver, address conflict, clock/reset,
#: or genuine SoC integration bug." Seven named outcomes plus an honest
#: residual. Held to that sentence by a test.
LOCAL_SUBSYSTEM_DEFECT = "LOCAL_SUBSYSTEM_DEFECT"
SHARED_RESOURCE_CAUSE = "SHARED_RESOURCE_CAUSE"
COMMAND_ORDERING_CAUSE = "COMMAND_ORDERING_CAUSE"
DUPLICATE_DRIVER_CAUSE = "DUPLICATE_DRIVER_CAUSE"
ADDRESS_CONFLICT_CAUSE = "ADDRESS_CONFLICT_CAUSE"
CLOCK_RESET_CAUSE = "CLOCK_RESET_CAUSE"
GENUINE_SOC_INTEGRATION_BUG = "GENUINE_SOC_INTEGRATION_BUG"
TRIAGE_UNKNOWN = "UNKNOWN"

SYS32_CLASSIFICATIONS: tuple = (
    LOCAL_SUBSYSTEM_DEFECT, SHARED_RESOURCE_CAUSE, COMMAND_ORDERING_CAUSE,
    DUPLICATE_DRIVER_CAUSE, ADDRESS_CONFLICT_CAUSE, CLOCK_RESET_CAUSE,
    GENUINE_SOC_INTEGRATION_BUG, TRIAGE_UNKNOWN,
)

#: Precedence, most SPECIFIC mechanism first. The first five are named
#: mechanisms with a citable upstream row; a mechanism that fired always
#: outranks a residual, because "this failure sits on a known driver conflict"
#: is a more actionable finding than "two subsystems failed together".
#: GENUINE_SOC_INTEGRATION_BUG and LOCAL_SUBSYSTEM_DEFECT are the two
#: residuals -- cross-subsystem and single-subsystem respectively -- and
#: UNKNOWN is last, for a record with nothing to classify at all.
#:
#: Every signal that matched is kept in `also_matched`. A failure sitting on
#: BOTH an address conflict and a clock-domain crossing has two things to fix,
#: and a single-valued column that dropped the second would be a worse report
#: than one that never noticed it -- the same reasoning
#: `system_scheduling_plan.SYS25_PRECEDENCE` already applies to pair
#: relationships.
SYS32_PRECEDENCE: tuple = (
    DUPLICATE_DRIVER_CAUSE, ADDRESS_CONFLICT_CAUSE, CLOCK_RESET_CAUSE,
    SHARED_RESOURCE_CAUSE, COMMAND_ORDERING_CAUSE, GENUINE_SOC_INTEGRATION_BUG,
    LOCAL_SUBSYSTEM_DEFECT, TRIAGE_UNKNOWN,
)

#: SYS-32's first determination, kept as its own field rather than folded into
#: the classification: "local vs cross-subsystem" is a fact about how many
#: subsystems failed, and it stays readable even when the mechanism is UNKNOWN.
LOCUS_LOCAL = "LOCAL"
LOCUS_CROSS_SUBSYSTEM = "CROSS_SUBSYSTEM"
LOCUS_UNKNOWN = "UNKNOWN"
SYS32_LOCUS_VALUES: tuple = (LOCUS_LOCAL, LOCUS_CROSS_SUBSYSTEM, LOCUS_UNKNOWN)

#: Which upstream document decides which cause, and what it is called when a
#: caller did not supply it. NOT_CONSULTED is deliberately distinct from a
#: consulted-and-empty result: without it, an unsupplied address reconciliation
#: would read exactly like "no address conflict exists", which would silently
#: promote failures into GENUINE_SOC_INTEGRATION_BUG.
CONSULTED = "CONSULTED"
NOT_CONSULTED = "NOT_CONSULTED"

CAUSE_SOURCES: tuple = (
    (DUPLICATE_DRIVER_CAUSE, "system_resource_registry",
     "SYS-15 registry entry whose conflict_status is DRIVER_CONFLICT"),
    (ADDRESS_CONFLICT_CAUSE, "address_reconciliation",
     "SYS-28 row whose verdict is ADDRESS_OVERLAP_CONFLICT"),
    (CLOCK_RESET_CAUSE, "clock_reset_comparison",
     "SYS-29 row whose verdict is a CONFLICTING_* value or CDC_BOUNDARY"),
    (SHARED_RESOURCE_CAUSE, "scheduling_plan",
     "SYS-24 row routing two or more subsystems through one shared access point"),
    (COMMAND_ORDERING_CAUSE, "scheduling_plan/command_plan",
     "SYS-25 ORDER_DEPENDENT pair, or a SYS-22 ORDERING_CONFLICT collision"),
)

PHASE_BOUNDARY = (
    "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED -- SYS-31..SYS-32 failure-record "
    "shaping and failure-locus classification only. No System-Level environment, "
    "System command.txt, System Virtual Sequencer or command routing is produced, "
    "and no failure is fixed, re-run or waived here; that is SYS-40 and requires a "
    "separate explicit human approval."
)


class SystemFailureTriageError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# ===========================================================================
# SYS-31 -- SUBSYSTEM FAILURE ISOLATION
# ===========================================================================

def _or_not_captured(value: Any) -> Any:
    if value is None or value == "":
        return NOT_CAPTURED
    return value


def build_subsystem_failure_record(*, system_scenario_id: str, subsystem: str,
                                   command: Optional[str] = None,
                                   vip_agent: Optional[str] = None,
                                   resource: Optional[str] = None,
                                   protocol: Optional[str] = None,
                                   pattern: Optional[str] = None,
                                   symptom: Optional[str] = None,
                                   root_cause_hypothesis: Optional[str] = None,
                                   uvm_error_count: int = 0,
                                   uvm_fatal_count: int = 0,
                                   assertion_failure: bool = False,
                                   simulator_crash: bool = False,
                                   terminal_signature: Optional[str] = None,
                                   lsf_status: Optional[str] = None,
                                   sim_log: Optional[str] = None,
                                   fsdb_path: Optional[str] = None,
                                   job_id: Optional[str] = None,
                                   confidence: Optional[Mapping[str, Any]] = None,
                                   independent_sources_count: Optional[int] = None,
                                   evidence_refs_verified: Optional[bool] = None,
                                   counter_evidence_count: int = 0,
                                   multi_agent_consensus_count: int = 0,
                                   ) -> Dict[str, Any]:
    """ONE failing subsystem inside ONE System scenario, carrying all ten of
    SYS-31's dimensions as distinct fields.

    `failure_signature` is `memory_vault.build_failure_signature()`'s output
    verbatim -- this module defines no second symptom shape, and the
    `vip_agent`/`resource` values are passed THROUGH to it so a system-level
    record and a job-level record describe the same failure identically.

    CONFIDENCE is either the caller's already-computed
    `inference.score_confidence()` result (passed as `confidence`, e.g. the
    `confidence_basis` block `lsf_client.py` already puts on a job record) or
    is computed HERE by that same function from the evidence counts the caller
    supplies. It is never a number invented in this file, and when the caller
    supplies neither it stays an explicit UNKNOWN with the reason attached
    rather than defaulting to a level nothing earned -- the same discipline
    `MemoryStore.add()`'s honest "UNKNOWN" default already applies.
    """
    if not str(system_scenario_id or "").strip():
        raise SystemFailureTriageError("SYSTEM_SCENARIO_ID_REQUIRED", {
            "hint": "SYS-31's first dimension is SYSTEM SCENARIO; a record without one "
                    "cannot be joined back to the scenario that produced it"})
    if not str(subsystem or "").strip():
        raise SystemFailureTriageError("SUBSYSTEM_REQUIRED", {
            "hint": "SYS-31 forbids collapsing failures into a generic System failure; "
                    "a sub-record with no subsystem is exactly that collapse"})

    signature = mv.build_failure_signature(
        protocol=protocol, pattern=pattern, symptom=symptom,
        root_cause_hint=root_cause_hypothesis, uvm_error_count=uvm_error_count,
        uvm_fatal_count=uvm_fatal_count, assertion_failure=assertion_failure,
        simulator_crash=simulator_crash, terminal_signature=terminal_signature,
        lsf_status=lsf_status, vip_agent=vip_agent, resource=resource)

    if confidence is not None:
        confidence_block = dict(confidence)
        confidence_block.setdefault("source", "caller-supplied inference.score_confidence() result")
    elif independent_sources_count is not None and evidence_refs_verified is not None:
        confidence_block = dict(inference.score_confidence(
            independent_sources_count, bool(evidence_refs_verified),
            counter_evidence_count, multi_agent_consensus_count))
        confidence_block["source"] = "inference.score_confidence()"
    else:
        confidence_block = {
            "level": "UNKNOWN", "score": None, "capped_by_counter_evidence": False,
            "source": "NOT_SCORED",
            "reason": ("neither a computed confidence nor the evidence counts "
                       "inference.score_confidence() needs were supplied; an invented "
                       "level would be worse than an honest UNKNOWN"),
        }

    record = {
        # --- SYS-31's ten dimensions, one key each ---------------------------
        "system_scenario": system_scenario_id,
        "subsystem": subsystem,
        "command": _or_not_captured(command),
        "vip_agent": _or_not_captured(vip_agent),
        "resource": _or_not_captured(resource),
        "uvm_error": {
            "uvm_error_count": uvm_error_count,
            "uvm_fatal_count": uvm_fatal_count,
            "assertion_failure": bool(assertion_failure),
            "simulator_crash": bool(simulator_crash),
            "terminal_signature": _or_not_captured(terminal_signature),
        },
        "log": _or_not_captured(sim_log),
        "waveform": _or_not_captured(fsdb_path),
        "root_cause_hypothesis": _or_not_captured(root_cause_hypothesis),
        "confidence": confidence_block,
        # --- beside the ten, never inside them --------------------------------
        "protocol": _or_not_captured(protocol),
        "pattern": _or_not_captured(pattern),
        "job_id": _or_not_captured(job_id),
        "lsf_status": _or_not_captured(lsf_status),
        "failure_signature": signature,
        "is_failure": bool(uvm_error_count or uvm_fatal_count or assertion_failure
                           or simulator_crash or signature["abnormal_termination"]),
        "prior_evidence": {
            "searched": False,
            "reason": "search_related_memory_for_debug() not run for this record",
            "related_cases": [],
        },
    }
    missing = [d for d in SYS31_DIMENSIONS if d not in record]
    if missing:  # structural bug, not a data condition
        raise SystemFailureTriageError("SYS31_DIMENSION_MISSING", {"dimensions": missing})
    return record


def attach_prior_evidence(record: Dict[str, Any], root, cfg: Optional[Dict[str, Any]] = None,
                          limit: int = 5) -> Dict[str, Any]:
    """Attach prior evidence to one sub-record through
    `memory_vault.search_related_memory_for_debug()` -- the SAME shared Memory
    Agent interface `engine.py`'s FAILURE_RECOVERY stage and `lsf_client.py`'s
    terminal-reconcile path already use, called with the signature this record
    already carries.

    Prior evidence ONLY. Per the Engineering Memory Policy's own rule, a hit
    is a candidate hypothesis to rank higher, never an accepted root cause,
    and nothing here writes into `root_cause_hypothesis`.

    Best-effort: a vault or evidence-DB problem must never turn an
    already-built failure record into an exception.
    """
    try:
        result = mv.search_related_memory_for_debug(
            Path(root), cfg, record["failure_signature"], limit=limit)
        record["prior_evidence"] = {
            "searched": True,
            "reason": "",
            "related_cases": list(result.get("related_cases") or []),
            "vault_count": result.get("vault_count"),
            "evidence_db_count": result.get("evidence_db_count"),
            "disclaimer": ("prior evidence only -- never an accepted root cause; "
                           "validate against current evidence"),
        }
    except Exception as exc:  # pragma: no cover - defensive, mirrors lsf_client.py
        record["prior_evidence"] = {
            "searched": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "related_cases": [],
        }
    return record


def build_system_failure_record(system_scenario_id: str,
                                subsystem_records: Sequence[Mapping[str, Any]],
                                *,
                                participating_subsystems: Optional[Sequence[str]] = None,
                                qualified_conclusion: Optional[Mapping[str, Any]] = None,
                                ) -> Dict[str, Any]:
    """The SYSTEM-level wrapper: one scenario id holding N per-subsystem
    records, which is the shape SYS-31's "Never collapse all failures into
    generic System failure" requires and which a one-job/one-protocol
    `job_failure` record structurally cannot express.

    `qualified_conclusion` is carried verbatim when a caller has one
    (`qualified_conclusion.QualifiedConclusion`, already composed on every
    gate-verified RE_AUDIT/RCA_JOIN PASS) -- never recomputed here.
    """
    records = [dict(r) for r in subsystem_records or []]
    mismatched = sorted({r["system_scenario"] for r in records
                         if r.get("system_scenario") != system_scenario_id})
    if mismatched:
        raise SystemFailureTriageError("SCENARIO_ID_MISMATCH", {
            "expected": system_scenario_id, "found": mismatched,
            "hint": "a System failure record joins sub-records of ONE scenario; joining "
                    "two scenarios' failures would be the collapse SYS-31 forbids"})

    failing = [r for r in records if r.get("is_failure")]
    subsystems = sorted({r["subsystem"] for r in records})
    declared = sorted(participating_subsystems or subsystems)
    document = {
        "schema_version": SCHEMA_VERSION,
        "system_scenario_id": system_scenario_id,
        "dimensions": list(SYS31_DIMENSIONS),
        "participating_subsystems": declared,
        "per_subsystem": records,
        "qualified_conclusion": dict(qualified_conclusion) if qualified_conclusion else None,
        "collapse_rule": COLLAPSE_RULE,
        "summary": {
            "subsystem_record_count": len(records),
            "failing_subsystems": sorted({r["subsystem"] for r in failing}),
            "failing_record_count": len(failing),
            "subsystems_reporting": subsystems,
            "subsystems_declared_but_not_reporting": sorted(set(declared) - set(subsystems)),
            "generic_system_failure_records": 0,
            "confidence_levels": sorted({str((r.get("confidence") or {}).get("level"))
                                         for r in records}),
        },
        "phase_boundary": PHASE_BOUNDARY,
    }
    assert_not_collapsed(document)
    return document


def assert_not_collapsed(document: Mapping[str, Any]) -> None:
    """SYS-31's closing rule as a runtime check.

    Refuses a document that: reports failing subsystems but carries no
    per-subsystem record for one of them; carries a sub-record missing any of
    the ten dimensions; or claims a generic System failure record.
    """
    if document.get("summary", {}).get("generic_system_failure_records"):
        raise SystemFailureTriageError("GENERIC_SYSTEM_FAILURE_COLLAPSE", {
            "rule": COLLAPSE_RULE})
    reporting = {r.get("subsystem") for r in document.get("per_subsystem") or []}
    for subsystem in document.get("summary", {}).get("failing_subsystems") or []:
        if subsystem not in reporting:
            raise SystemFailureTriageError("FAILING_SUBSYSTEM_WITHOUT_RECORD", {
                "subsystem": subsystem, "rule": COLLAPSE_RULE})
    for record in document.get("per_subsystem") or []:
        missing = [d for d in SYS31_DIMENSIONS if d not in record]
        if missing:
            raise SystemFailureTriageError("SYS31_DIMENSION_MISSING", {
                "subsystem": record.get("subsystem"), "dimensions": missing,
                "rule": COLLAPSE_RULE})


# ===========================================================================
# SYS-32 -- SYSTEM FAILURE TRIAGE
# ===========================================================================

def _names_of(record: Mapping[str, Any], *fields: str) -> Set[str]:
    """The real, captured values a record offers for evidence-linking. A
    NOT_CAPTURED dimension contributes nothing -- an absent value must never
    match anything, or every unfilled field would link every failure to every
    upstream row."""
    out: Set[str] = set()
    for field in fields:
        value = record.get(field)
        if isinstance(value, str) and value and value != NOT_CAPTURED:
            out.add(value)
    return out


def _duplicate_driver_signals(failing: Sequence[Mapping[str, Any]],
                              registry: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """A SYS-15 registry entry already in DRIVER_CONFLICT, linked to THIS
    failure by the record's own resource/vip_agent value appearing in the
    entry's identity or member ids. An entry in conflict somewhere else in the
    selection is not evidence about this failure."""
    signals: List[Dict[str, Any]] = []
    for entry in registry.get("entries") or []:
        if entry.get("conflict_status") != srr.CONFLICT_DRIVER:
            continue
        identity = {str(entry.get("resource_id") or ""),
                    str(entry.get("physical_hierarchy") or ""),
                    str(entry.get("physical_interface_id") or "")}
        identity |= {str(m) for m in entry.get("member_resource_ids") or []}
        identity.discard("")
        consumers = set(entry.get("consumer_subsystems") or [])
        for record in failing:
            named = _names_of(record, "resource", "vip_agent")
            hit = named & identity
            if not hit:
                continue
            signals.append({
                "classification": DUPLICATE_DRIVER_CAUSE,
                "basis": (f"{record['subsystem']} failed while naming {sorted(hit)}, which "
                          f"is SYS-15 registry entry {entry.get('resource_id')} -- already "
                          f"decided {srr.CONFLICT_DRIVER} across "
                          f"{sorted(consumers)} by SYS-10..SYS-14"),
                "from_source": "system_resource_registry",
                "cited_row": str(entry.get("resource_id") or ""),
                "subsystems": sorted(consumers | {record["subsystem"]}),
            })
    return signals


def _address_conflict_signals(failing: Sequence[Mapping[str, Any]],
                              address_reconciliation: Mapping[str, Any]
                              ) -> List[Dict[str, Any]]:
    failing_subsystems = {r["subsystem"] for r in failing}
    signals: List[Dict[str, Any]] = []
    for row in address_reconciliation.get("overlaps") or []:
        if row.get("verdict") != sta.ADDRESS_OVERLAP_CONFLICT:
            continue
        pair = {row["subsystem_a"], row["subsystem_b"]}
        if not pair <= failing_subsystems:
            continue
        signals.append({
            "classification": ADDRESS_CONFLICT_CAUSE,
            "basis": (f"both failing subsystems {sorted(pair)} are the two sides of SYS-28 "
                      f"row {row['pair_id']} ({sta.ADDRESS_OVERLAP_CONFLICT}): "
                      f"{row['subsystem_a']}::{row['region_a']} and "
                      f"{row['subsystem_b']}::{row['region_b']} intersect at "
                      f"{row['intersection_start']}..{row['intersection_end']}"),
            "from_source": "address_reconciliation",
            "cited_row": row["pair_id"],
            "subsystems": sorted(pair),
        })
    return signals


def _clock_reset_signals(failing: Sequence[Mapping[str, Any]],
                         clock_reset_comparison: Mapping[str, Any]) -> List[Dict[str, Any]]:
    failing_subsystems = {r["subsystem"] for r in failing}
    interesting = {sta.CONFLICTING_CLOCK_FREQUENCY, sta.CONFLICTING_CLOCK_SOURCE,
                   sta.CONFLICTING_RESET_POLARITY, sta.CONFLICTING_RESET_SEQUENCING,
                   sta.CDC_BOUNDARY}
    signals: List[Dict[str, Any]] = []
    rows = list(clock_reset_comparison.get("clock_comparisons") or []) + list(
        clock_reset_comparison.get("reset_comparisons") or [])
    for row in rows:
        if row.get("verdict") not in interesting:
            continue
        pair = {row["subsystem_a"], row["subsystem_b"]}
        if not pair <= failing_subsystems:
            continue
        signals.append({
            "classification": CLOCK_RESET_CAUSE,
            "basis": (f"both failing subsystems {sorted(pair)} are the two sides of SYS-29 "
                      f"row {row['pair_id']} ({row['verdict']}): {row['basis']}"),
            "from_source": "clock_reset_comparison",
            "cited_row": row["pair_id"],
            "subsystems": sorted(pair),
        })
    return signals


def _shared_resource_signals(failing: Sequence[Mapping[str, Any]],
                             scheduling_plan: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """A SYS-24 row that routes two or more subsystems through ONE shared
    access point, where at least one failing record names that resource. The
    row is the evidence; the record's own `resource` value is the link."""
    failing_subsystems = {r["subsystem"] for r in failing}
    scheduling = scheduling_plan.get("shared_resource_scheduling") or {}
    signals: List[Dict[str, Any]] = []
    for row in scheduling.get("entries") or []:
        if row.get("scheduling_disposition") != ssp.SCHED_SINGLE_SHARED_ACCESS_POINT:
            continue
        consumers = set(row.get("consumer_subsystems") or [])
        if len(consumers & failing_subsystems) < 1:
            continue
        identity = {str(row.get("shared_resource_key") or ""),
                    str(row.get("registry_entry_id") or "")}
        identity |= {str(r) for r in row.get("command_resource_ids") or []}
        identity.discard("")
        named = {n for record in failing for n in _names_of(record, "resource", "vip_agent")}
        hit = named & identity
        if not hit:
            continue
        signals.append({
            "classification": SHARED_RESOURCE_CAUSE,
            "basis": (f"a failing record names {sorted(hit)}, which SYS-24 routes through "
                      f"one shared access point for {sorted(consumers)} "
                      f"({row.get('shared_access_point')}, "
                      f"{row.get('access_point_status')})"),
            "from_source": "scheduling_plan",
            "cited_row": str(row.get("shared_resource_key") or ""),
            "subsystems": sorted(consumers | failing_subsystems),
        })
    return signals


def _command_ordering_signals(failing: Sequence[Mapping[str, Any]],
                              scheduling_plan: Mapping[str, Any],
                              command_plan: Optional[Mapping[str, Any]]
                              ) -> List[Dict[str, Any]]:
    """Two evidence axes, both already computed elsewhere: a SYS-25
    ORDER_DEPENDENT pair between two failing records' commands, and a SYS-22
    ORDERING_CONFLICT collision naming them. Both link through the record's own
    `command` value, never through a subsystem name alone -- an ordering claim
    made from nothing but "these two subsystems both failed" would be the
    name-only inference SYS-10 rules out."""
    commands = {r["subsystem"]: _names_of(r, "command") for r in failing}
    all_commands = {c for cs in commands.values() for c in cs}
    signals: List[Dict[str, Any]] = []

    for pair in ((scheduling_plan.get("parallelism_model") or {}).get("pairs") or []):
        if pair.get("relationship") != ssp.REL_ORDER_DEPENDENT:
            continue
        pair_commands = {pair["command_a"], pair["command_b"]}
        # Whole-name match only: `c in pc` would let a command named INIT link
        # to every command whose namespaced id happens to contain that
        # substring, which is precisely the name-only inference SYS-10 rules
        # out. A SYSTEM command id is `<subsystem>::<command>`, so an exact
        # match or that one suffix form is the whole legitimate space.
        matched = {c for c in all_commands
                   if any(c == pc or pc.endswith(f"::{c}") for pc in pair_commands)}
        if len(matched) < 2:
            continue
        signals.append({
            "classification": COMMAND_ORDERING_CAUSE,
            "basis": (f"the failing records' commands {sorted(matched)} are the two sides of "
                      f"SYS-25 pair {pair['pair_id']} ({ssp.REL_ORDER_DEPENDENT}): "
                      f"{pair['basis']}"),
            "from_source": "scheduling_plan",
            "cited_row": pair["pair_id"],
            "subsystems": sorted({pair["subsystem_a"], pair["subsystem_b"]}),
        })

    collisions = ((command_plan or {}).get("command_collisions") or {}).get("collisions") or []
    for finding in collisions:
        if finding.get("collision_type") != scp.ORDERING_CONFLICT:
            continue
        finding_commands = set(finding.get("commands") or [])
        matched = {c for c in all_commands
                   if any(c == fc or fc.endswith(f"::{c}") for fc in finding_commands)}
        if not matched:
            continue
        signals.append({
            "classification": COMMAND_ORDERING_CAUSE,
            "basis": (f"the failing records' commands {sorted(matched)} appear in SYS-22 "
                      f"collision {finding.get('collision_id')} "
                      f"({scp.ORDERING_CONFLICT}) over {finding.get('subject')}"),
            "from_source": "command_plan",
            "cited_row": str(finding.get("collision_id") or ""),
            "subsystems": sorted(finding.get("subsystems") or []),
        })
    return signals


def triage_system_failure(system_failure_record: Mapping[str, Any], *,
                          registry: Optional[Mapping[str, Any]] = None,
                          address_reconciliation: Optional[Mapping[str, Any]] = None,
                          clock_reset_comparison: Optional[Mapping[str, Any]] = None,
                          scheduling_plan: Optional[Mapping[str, Any]] = None,
                          command_plan: Optional[Mapping[str, Any]] = None,
                          ) -> Dict[str, Any]:
    """SYS-32 over ONE SYS-31 System failure record.

    Reuses every upstream mechanism and re-derives none of them (see the module
    docstring). Returns a classification, its locus, the signals that matched,
    and -- importantly -- which sources were CONSULTED, so a reader can tell a
    negative finding from an unexamined one.
    """
    failing = [r for r in system_failure_record.get("per_subsystem") or []
               if r.get("is_failure")]
    failing_subsystems = sorted({r["subsystem"] for r in failing})

    consulted = {}
    signals: List[Dict[str, Any]] = []
    if registry is not None:
        consulted[DUPLICATE_DRIVER_CAUSE] = CONSULTED
        signals += _duplicate_driver_signals(failing, registry)
    else:
        consulted[DUPLICATE_DRIVER_CAUSE] = NOT_CONSULTED
    if address_reconciliation is not None:
        consulted[ADDRESS_CONFLICT_CAUSE] = CONSULTED
        signals += _address_conflict_signals(failing, address_reconciliation)
    else:
        consulted[ADDRESS_CONFLICT_CAUSE] = NOT_CONSULTED
    if clock_reset_comparison is not None:
        consulted[CLOCK_RESET_CAUSE] = CONSULTED
        signals += _clock_reset_signals(failing, clock_reset_comparison)
    else:
        consulted[CLOCK_RESET_CAUSE] = NOT_CONSULTED
    if scheduling_plan is not None:
        consulted[SHARED_RESOURCE_CAUSE] = CONSULTED
        signals += _shared_resource_signals(failing, scheduling_plan)
    else:
        consulted[SHARED_RESOURCE_CAUSE] = NOT_CONSULTED
    if scheduling_plan is not None or command_plan is not None:
        consulted[COMMAND_ORDERING_CAUSE] = CONSULTED
        signals += _command_ordering_signals(failing, scheduling_plan or {}, command_plan)
    else:
        consulted[COMMAND_ORDERING_CAUSE] = NOT_CONSULTED

    if not failing:
        locus = LOCUS_UNKNOWN
    elif len(failing_subsystems) >= 2:
        locus = LOCUS_CROSS_SUBSYSTEM
    else:
        locus = LOCUS_LOCAL

    unconsulted = sorted(k for k, v in consulted.items() if v == NOT_CONSULTED)
    matched = {s["classification"] for s in signals}

    if not failing:
        matched.add(TRIAGE_UNKNOWN)
        residual_reason = ("no sub-record in this System failure record reports a failure, "
                           "so there is nothing to classify")
    elif locus == LOCUS_CROSS_SUBSYSTEM and not matched:
        matched.add(GENUINE_SOC_INTEGRATION_BUG)
        residual_reason = (
            f"{len(failing_subsystems)} subsystems failed inside one System scenario and "
            f"none of the {len(CAUSE_SOURCES)} named mechanisms matched"
            + (f"; NOTE {unconsulted} were NOT CONSULTED, so this residual is weaker than "
               "it looks and should be re-run once they are supplied" if unconsulted else
               ", with every named mechanism consulted"))
    elif locus == LOCUS_LOCAL and not matched:
        matched.add(LOCAL_SUBSYSTEM_DEFECT)
        residual_reason = (
            f"only {failing_subsystems[0]} failed and no cross-subsystem mechanism linked "
            "it to another selected subsystem"
            + (f"; NOTE {unconsulted} were NOT CONSULTED" if unconsulted else ""))
    else:
        residual_reason = ""

    classification = next((c for c in SYS32_PRECEDENCE if c in matched), TRIAGE_UNKNOWN)
    chosen = next((s for s in signals if s["classification"] == classification), None)
    triage_id = "SYSTRIAGE-" + hashlib.sha256("|".join(
        [str(system_failure_record.get("system_scenario_id")), *failing_subsystems]
    ).encode("utf-8")).hexdigest()[:10].upper()

    return {
        "schema_version": SCHEMA_VERSION,
        "triage_id": triage_id,
        "system_scenario_id": system_failure_record.get("system_scenario_id"),
        "classifications": list(SYS32_CLASSIFICATIONS),
        "precedence": list(SYS32_PRECEDENCE),
        "locus": locus,
        "locus_basis": (f"{len(failing_subsystems)} failing subsystem(s): "
                        f"{failing_subsystems}" if failing else
                        "no failing sub-record in this System failure record"),
        "classification": classification,
        "basis": chosen["basis"] if chosen else residual_reason,
        "cited_row": chosen["cited_row"] if chosen else "",
        "from_source": chosen["from_source"] if chosen else "residual",
        "also_matched": sorted(matched - {classification}),
        "signals": signals,
        "failing_subsystems": failing_subsystems,
        "sources_consulted": consulted,
        "sources_not_consulted": unconsulted,
        "cause_sources": [{"classification": c, "source": s, "decided_by": d}
                          for c, s, d in CAUSE_SOURCES],
        "prior_evidence_by_subsystem": {
            r["subsystem"]: r.get("prior_evidence", {}) for r in failing},
        "root_cause_decided": False,
        "root_cause_note": (
            "SYS-32 determines a LOCUS -- where to look -- not a root cause. Prior "
            "evidence is prior evidence; validate every hypothesis against current "
            "evidence per the Evidence Truth Rule."),
        "failures_fixed": 0,
        "failures_waived": 0,
        "phase_boundary": PHASE_BOUNDARY,
    }


def triage_from_topology_analysis(system_failure_record: Mapping[str, Any],
                                  topology_analysis: Mapping[str, Any],
                                  integration_plan: Mapping[str, Any],
                                  command_plan: Mapping[str, Any],
                                  scheduling_plan: Mapping[str, Any],
                                  ) -> Dict[str, Any]:
    """Convenience front door for the common case: triage against the four
    documents the SYS-15..30 stack already produced, unpacked from them so a
    caller does not have to know which key each cause is decided from."""
    return triage_system_failure(
        system_failure_record,
        registry=integration_plan.get("system_resource_registry") or {"entries": []},
        address_reconciliation=topology_analysis.get("address_map_reconciliation"),
        clock_reset_comparison=topology_analysis.get("clock_reset_comparison"),
        scheduling_plan=scheduling_plan,
        command_plan=command_plan)


# ===========================================================================
# Reporting
# ===========================================================================

def validate_system_failure_record(document: Mapping[str, Any]) -> None:
    """Validate a `build_system_failure_record()` document against the real
    JSON schema. Raises jsonschema.ValidationError on a violation."""
    import jsonschema
    schema = json.loads(RECORD_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(document, schema)


def validate_system_failure_triage(document: Mapping[str, Any]) -> None:
    """Validate a `triage_system_failure()` document against the real JSON
    schema. Raises jsonschema.ValidationError on a violation."""
    import jsonschema
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(document, schema)


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_failure_isolation_table(record: Mapping[str, Any]) -> str:
    """SYS-31's ten dimensions, one column each, one row per subsystem -- the
    literal shape "never collapse into a generic System failure" asks for."""
    header = ("| System scenario | Subsystem | Command | VIP agent | Resource | UVM_ERROR | "
              "Log | Waveform | Root-cause hypothesis | Confidence |")
    lines = [header, "|" + "---|" * 10]
    for row in record.get("per_subsystem") or []:
        uvm = row["uvm_error"]
        lines.append("| " + " | ".join(_cell(v) for v in (
            row["system_scenario"], row["subsystem"], row["command"], row["vip_agent"],
            row["resource"],
            f"E{uvm['uvm_error_count']}/F{uvm['uvm_fatal_count']}"
            + ("/ASSERT" if uvm["assertion_failure"] else "")
            + ("/CRASH" if uvm["simulator_crash"] else ""),
            row["log"], row["waveform"], row["root_cause_hypothesis"],
            (row.get("confidence") or {}).get("level"))) + " |")
    if len(lines) == 2:
        lines.append("| _no subsystem failure record_ |" + " |" * 9)
    return "\n".join(lines)


def format_system_failure_triage_report(record: Mapping[str, Any],
                                        triage: Mapping[str, Any]) -> str:
    """The SYS-31..32 section of the Phase-1 report."""
    summary = record["summary"]
    out = [
        "# SYSTEM FAILURE ISOLATION AND TRIAGE (SYS-31..SYS-32)",
        "",
        f"System scenario: {record['system_scenario_id']}",
        f"Participating subsystems: "
        f"{', '.join(record['participating_subsystems']) or '(none)'}",
        "",
        "## SYS-31 SUBSYSTEM FAILURE ISOLATION",
        "",
        f"{summary['subsystem_record_count']} per-subsystem record(s); "
        f"{summary['failing_record_count']} failing "
        f"({', '.join(summary['failing_subsystems']) or 'none'}); "
        f"{summary['generic_system_failure_records']} generic System failure record(s).",
        "",
        render_failure_isolation_table(record),
        "",
        "## SYS-32 SYSTEM FAILURE TRIAGE",
        "",
        f"Locus: **{triage['locus']}** -- {triage['locus_basis']}",
        f"Classification: **{triage['classification']}**"
        + (f" (also matched: {', '.join(triage['also_matched'])})"
           if triage["also_matched"] else ""),
        f"Basis: {triage['basis']}",
        f"Cited row: {triage['cited_row'] or '(residual -- no upstream row cited)'}",
        "",
        "| Cause | Decided by | Consulted |",
        "|---|---|---|",
    ]
    for entry in triage["cause_sources"]:
        out.append("| " + " | ".join(_cell(v) for v in (
            entry["classification"], entry["decided_by"],
            triage["sources_consulted"].get(entry["classification"], NOT_CONSULTED))) + " |")
    out += [
        "",
        triage["root_cause_note"],
        "",
        "## PHASE BOUNDARY",
        "",
        triage["phase_boundary"],
    ]
    return "\n".join(out)
