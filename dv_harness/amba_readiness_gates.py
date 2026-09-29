"""AMBA readiness gates: the 9 named composite gates from section 71 ("MACHINE-CHECKABLE
GATES") of the AMBA M x N golden-flow source document
(``CLAUDE_L5_L3_GOLDEN_AMBA_SOC_BUS_MXN_COMPLETE.md`` / ``CLAUDE_L5_L3_GOLDEN_AMBA_SC_BUS_MXN.md``,
sections 71-80): ``L3_REFERENCE_READY``, ``AMBA_PORT_REGISTRY_READY``, ``AMBA_CONSTRAINT_READY``,
``AMBA_CONNECTIVITY_READY``, ``AMBA_VIP_BIND_READY``, ``AMBA_SCOREBOARD_READY``,
``AMBA_COVERAGE_READY``, ``AMBA_TEST_GENERATION_READY``, ``AMBA_SIGNOFF_READY``.

Each gate is a real AND-formula transcribed verbatim from the source document's own
``GATE = A AND B AND C ...`` blocks -- this module invents no new required condition and drops
none of the document's own. Every AND-term is a *condition name* a caller supplies evidence for
as a ``{"condition_name": ..., "status": ...}`` record; this module never inspects RTL/VIP/spec
evidence itself and never decides what counts as satisfying a named condition -- that judgment
belongs to whichever real producer (fabric discovery, port registry, scoreboard env, ...) the
caller's own evidence pipeline already has. Per this batch's file-safety scope this module imports
nothing from any file in the claimed-file list and nothing from any other new module built in this
batch -- every fact arrives as a generic, duck-typed condition record.

Discipline, matching this project's other composite-gate modules (``subsystem_maturity_gate.py``,
``functional_coverage_signoff.py``, ``spec_vplan_readiness_gate.py``, ``system_readiness_gates.py``):
worst-wins, never averaged. A single ``UNMET`` condition blocks the WHOLE gate as ``NOT_READY``
regardless of how many other conditions on that gate are clean. Only once no condition is UNMET
does an ``UNKNOWN``/``NOT_AVAILABLE`` condition -- or a condition nobody supplied evidence for at
all -- make the gate ``INCOMPLETE_EVIDENCE`` rather than either ``READY`` or ``NOT_READY``:
absent/unresolved evidence is never silently promoted to READY (GF-AT-28) and never forced into a
confirmed NOT_READY it was never proven to be.

``AMBA_TEST_GENERATION_READY`` (section 79) is the one gate in the source document whose own
AND-formula names THREE OTHER gates as terms (``AND AMBA_CONSTRAINT_READY`` /
``AND AMBA_CONNECTIVITY_READY`` / ``AND AMBA_VIP_BIND_READY``), not a raw condition a caller
measures directly. The 9 gates are evaluated in the document's own fixed order (72 -> 80), so by
the time ``AMBA_TEST_GENERATION_READY`` is evaluated every gate it references has already been
computed; that computed verdict is used automatically (READY -> MET, NOT_READY -> UNMET,
INCOMPLETE_EVIDENCE -> UNKNOWN) UNLESS the caller explicitly supplied its own condition record
naming that sub-gate directly -- an explicit, caller-supplied condition always outranks a derived
one, the same "real evidence outranks a derived value" precedence this project's Source Authority
Order already applies everywhere else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from dv_harness.models import Status

# --------------------------------------------------------------------------
# Vocabularies
# --------------------------------------------------------------------------

# Per-condition evidence status, supplied by the caller for each named AND-term.
# MET / UNMET are a caller's real evidence-backed judgment about that one named
# condition; UNKNOWN / NOT_AVAILABLE are the honest "we could not tell" states --
# kept as two distinct reasons rather than one, mirroring this project's other
# composite gates (a condition nobody could check is a different fact from one
# whose evidence source itself does not exist).
CONDITION_STATUSES: Tuple[str, ...] = ("MET", "UNMET", "UNKNOWN", "NOT_AVAILABLE")

# A condition a caller's list simply never mentions -- distinct from an explicit
# UNKNOWN/NOT_AVAILABLE record, but folded identically (never silently READY).
CONDITION_NOT_SUPPLIED = "NOT_SUPPLIED"

# Per-gate verdict.
GATE_READY = "READY"
GATE_NOT_READY = "NOT_READY"
GATE_INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"
GATE_VERDICTS: Tuple[str, ...] = (GATE_READY, GATE_NOT_READY, GATE_INCOMPLETE_EVIDENCE)

# Maps a computed sub-gate verdict onto the condition-status vocabulary, so a
# gate-name term inside another gate's AND-formula (AMBA_TEST_GENERATION_READY's
# three sub-gate references) is folded through the exact same worst-wins rule as
# every other condition.
_GATE_VERDICT_TO_CONDITION_STATUS: Dict[str, str] = {
    GATE_READY: "MET",
    GATE_NOT_READY: "UNMET",
    GATE_INCOMPLETE_EVIDENCE: "UNKNOWN",
}


class AmbaReadinessGatesError(ValueError):
    """Raised for malformed input -- never silently repaired or dropped."""


def _assert_no_verification_verdict_vocabulary() -> None:
    """This module's own vocabularies must share no token with ``models.Status`` --
    the same guard several sibling composite-gate modules already apply to
    themselves, so a per-condition MET/UNMET/UNKNOWN and a per-gate
    READY/NOT_READY/INCOMPLETE_EVIDENCE can never be misread as a stage verdict."""
    status_values = {member.value for member in Status}
    collisions = (set(CONDITION_STATUSES) | set(GATE_VERDICTS)) & status_values
    if collisions:
        raise AssertionError(
            "amba_readiness_gates vocabulary collides with dv_harness.models.Status: "
            f"{sorted(collisions)}"
        )


_assert_no_verification_verdict_vocabulary()

# --------------------------------------------------------------------------
# The 9 named gates, transcribed verbatim from sections 72-80 of the source
# document. Each tuple is the gate's own AND-formula, term for term, in the
# document's own order. A term that is itself one of GATE_NAMES (below) is a
# sub-gate reference, not a raw condition.
# --------------------------------------------------------------------------

GATE_NAMES: Tuple[str, ...] = (
    "L3_REFERENCE_READY",
    "AMBA_PORT_REGISTRY_READY",
    "AMBA_CONSTRAINT_READY",
    "AMBA_CONNECTIVITY_READY",
    "AMBA_VIP_BIND_READY",
    "AMBA_SCOREBOARD_READY",
    "AMBA_COVERAGE_READY",
    "AMBA_TEST_GENERATION_READY",
    "AMBA_SIGNOFF_READY",
)

GATE_REQUIRED_CONDITIONS: Dict[str, Tuple[str, ...]] = {
    # Section 72
    "L3_REFERENCE_READY": (
        "L3_Source_Found",
        "L3_Inventory_Complete",
        "L3_Baseline_Preserved",
        "Required_Build_Run_Context_Discovered",
        "Critical_UNKNOWN",
    ),
    # Section 73
    "AMBA_PORT_REGISTRY_READY": (
        "Required_Fabric_Ports_Discovered",
        "Required_Roles_Resolved",
        "Required_Hierarchy_Trace_Complete",
        "Required_Clock_Reset_Resolved",
        "Critical_UNKNOWN",
    ),
    # Section 74
    "AMBA_CONSTRAINT_READY": (
        "Every_Required_Master_Protocol_Resolved",
        "Every_Required_Master_DUT_Capability_Resolved",
        "Required_Ordering_Resolved",
        "Required_Security_Privilege_Resolved",
        "Constraint_Evidence_Valid",
        "Critical_UNKNOWN",
    ),
    # Section 75
    "AMBA_CONNECTIVITY_READY": (
        "Required_Master_Slave_Edges_Resolved",
        "Required_Memory_Map_Resolved",
        "RTL_Spec_Address_Correlation_Complete",
        "Critical_Address_Conflict",
        "Critical_Connectivity_Conflict",
        "Critical_UNKNOWN",
    ),
    # Section 76
    "AMBA_VIP_BIND_READY": (
        "Required_VIP_Instances_Resolved",
        "Required_Active_Passive_Ownership_Resolved",
        "Active_Driver_Conflict",
        "Required_Bind_Hierarchy_Validated",
        "Required_Clock_Reset_Validated",
        "Critical_UNKNOWN",
    ),
    # Section 77
    "AMBA_SCOREBOARD_READY": (
        "Transaction_Adapters_Valid",
        "Route_Predictor_Valid",
        "Expected_Source_Valid",
        "Actual_Source_Valid",
        "Ordering_Policy_Resolved",
        "SyoSil_Queues_Configured",
        "Deterministic_Known_Test_PASS",
        "Critical_UNKNOWN",
    ),
    # Section 78
    "AMBA_COVERAGE_READY": (
        "Required_Legal_Edges_Mapped",
        "Required_Constraint_Coverage_Mapped",
        "Required_Memory_Region_Coverage_Mapped",
        "Required_Routing_Coverage_Mapped",
        "Coverage_Reachability_Resolved",
        "Critical_UNKNOWN",
    ),
    # Section 79 -- the three AMBA_*_READY terms are sub-gate references, not
    # raw conditions (see module docstring).
    "AMBA_TEST_GENERATION_READY": (
        "Approved_vPlan_Valid",
        "AMBA_CONSTRAINT_READY",
        "AMBA_CONNECTIVITY_READY",
        "AMBA_VIP_BIND_READY",
        "Existing_DE_Command_Style_Learned",
        "Required_Checker_Scoreboard_Binding_Valid",
        "Critical_UNKNOWN",
    ),
    # Section 80
    "AMBA_SIGNOFF_READY": (
        "Required_vPlan_Items_Closed",
        "Required_Legal_Connectivity_Edges_Closed",
        "Required_Functional_Coverage_Items_Closed",
        "Required_Regression_PASS",
        "VIP_Protocol_Evidence_Valid",
        "SyoSil_Scoreboard_Evidence_Valid",
        "Critical_Unresolved_Failure",
        "Critical_UNKNOWN",
        "Traceability_Complete",
        "Evidence_Complete",
    ),
}

# Terms inside GATE_REQUIRED_CONDITIONS that are themselves gate names, i.e.
# sub-gate references rather than raw caller-measured conditions.
_SUB_GATE_REFERENCES: Dict[str, Tuple[str, ...]] = {
    gate_name: tuple(term for term in terms if term in GATE_NAMES)
    for gate_name, terms in GATE_REQUIRED_CONDITIONS.items()
}


def _assert_gate_table_well_formed() -> None:
    """Every declared gate name has a required-condition tuple, every sub-gate
    reference names a real gate, and no gate references itself or a gate that
    comes AFTER it in the document's own fixed order (which would make
    single-pass, no-recursion evaluation in document order unsound)."""
    if set(GATE_REQUIRED_CONDITIONS) != set(GATE_NAMES):
        raise AssertionError("GATE_REQUIRED_CONDITIONS must declare exactly GATE_NAMES")
    for index, gate_name in enumerate(GATE_NAMES):
        for term in _SUB_GATE_REFERENCES[gate_name]:
            if term not in GATE_NAMES:
                raise AssertionError(f"{gate_name} references unknown gate {term!r}")
            if GATE_NAMES.index(term) >= index:
                raise AssertionError(
                    f"{gate_name} references {term!r}, which does not come strictly "
                    "earlier in GATE_NAMES's fixed evaluation order"
                )


_assert_gate_table_well_formed()


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------


@dataclass
class ConditionEvaluation:
    """One AND-term's resolved evidence, as it was actually consumed by a gate."""

    condition_name: str
    status: str
    reason: Optional[str] = None
    is_sub_gate_reference: bool = False
    source: str = "caller_supplied"  # "caller_supplied" | "derived_from_sub_gate" | "not_supplied"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "condition_name": self.condition_name,
            "status": self.status,
            "reason": self.reason,
            "is_sub_gate_reference": self.is_sub_gate_reference,
            "source": self.source,
        }


@dataclass
class GateEvaluation:
    """One of the 9 named gates' evaluated verdict, with full per-condition evidence."""

    gate_name: str
    verdict: str
    conditions: List[ConditionEvaluation] = field(default_factory=list)
    blocking_conditions: List[str] = field(default_factory=list)
    incomplete_conditions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_name": self.gate_name,
            "verdict": self.verdict,
            "conditions": [c.to_dict() for c in self.conditions],
            "blocking_conditions": list(self.blocking_conditions),
            "incomplete_conditions": list(self.incomplete_conditions),
        }


@dataclass
class AmbaReadinessReport:
    """All 9 gates, evaluated in the document's own fixed order."""

    gates: Dict[str, GateEvaluation] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {name: gate.to_dict() for name, gate in self.gates.items()}

    def verdict_for(self, gate_name: str) -> str:
        if gate_name not in self.gates:
            raise AmbaReadinessGatesError(f"unknown gate: {gate_name!r}")
        return self.gates[gate_name].verdict

    def worst_verdict(self) -> str:
        """The worst verdict across all 9 gates (NOT_READY worse than
        INCOMPLETE_EVIDENCE worse than READY) -- a convenience rollup; each
        gate's own verdict remains the authoritative per-gate answer."""
        order = {GATE_READY: 0, GATE_INCOMPLETE_EVIDENCE: 1, GATE_NOT_READY: 2}
        worst = GATE_READY
        for gate in self.gates.values():
            if order[gate.verdict] > order[worst]:
                worst = gate.verdict
        return worst


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------


def _validate_condition_records(
    conditions: Sequence[Mapping[str, Any]]
) -> Dict[str, ConditionEvaluation]:
    """Validate and index the caller-supplied condition list. Raises on any
    malformed or duplicate record rather than silently dropping or coercing it."""
    if not isinstance(conditions, (list, tuple)):
        raise AmbaReadinessGatesError(
            f"conditions must be a list/tuple of records, got {type(conditions).__name__}"
        )
    indexed: Dict[str, ConditionEvaluation] = {}
    for entry in conditions:
        if not isinstance(entry, Mapping):
            raise AmbaReadinessGatesError(f"condition record must be a mapping, got {entry!r}")
        name = entry.get("condition_name")
        status = entry.get("status")
        if not isinstance(name, str) or not name.strip():
            raise AmbaReadinessGatesError(f"condition record missing a real condition_name: {entry!r}")
        if not isinstance(status, str) or status not in CONDITION_STATUSES:
            raise AmbaReadinessGatesError(
                f"condition {name!r} has an unrecognized status {status!r}; "
                f"must be one of {CONDITION_STATUSES}"
            )
        if name in indexed:
            raise AmbaReadinessGatesError(f"duplicate condition_name in input: {name!r}")
        reason = entry.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise AmbaReadinessGatesError(f"condition {name!r} has a non-string reason: {reason!r}")
        indexed[name] = ConditionEvaluation(
            condition_name=name, status=status, reason=reason, source="caller_supplied"
        )
    return indexed


def _resolve_condition(
    condition_name: str,
    is_sub_gate_reference: bool,
    supplied: Mapping[str, ConditionEvaluation],
    gate_verdicts: Mapping[str, str],
) -> ConditionEvaluation:
    """Resolve one AND-term to its evaluated status. A caller-supplied record for
    this exact name always wins (real evidence outranks a derived value, this
    project's Source Authority Order applied here). Absent that, a sub-gate
    reference is derived from the already-computed sub-gate verdict. Absent
    both, the condition was simply never supplied -- honestly UNKNOWN, never
    silently READY/MET."""
    if condition_name in supplied:
        record = supplied[condition_name]
        return ConditionEvaluation(
            condition_name=condition_name,
            status=record.status,
            reason=record.reason,
            is_sub_gate_reference=is_sub_gate_reference,
            source="caller_supplied",
        )
    if is_sub_gate_reference and condition_name in gate_verdicts:
        sub_verdict = gate_verdicts[condition_name]
        derived_status = _GATE_VERDICT_TO_CONDITION_STATUS[sub_verdict]
        return ConditionEvaluation(
            condition_name=condition_name,
            status=derived_status,
            reason=f"derived from sub-gate {condition_name} verdict {sub_verdict}",
            is_sub_gate_reference=True,
            source="derived_from_sub_gate",
        )
    return ConditionEvaluation(
        condition_name=condition_name,
        status="UNKNOWN",
        reason="no evidence supplied for this condition",
        is_sub_gate_reference=is_sub_gate_reference,
        source="not_supplied",
    )


def _fold_gate_verdict(resolved: Sequence[ConditionEvaluation]) -> Tuple[str, List[str], List[str]]:
    """Worst-wins fold: any UNMET blocks the whole gate as NOT_READY regardless
    of how many other conditions are clean; only absent that does any
    UNKNOWN/NOT_AVAILABLE condition make the gate INCOMPLETE_EVIDENCE; only when
    every condition is MET does the gate read READY."""
    blocking = [c.condition_name for c in resolved if c.status == "UNMET"]
    incomplete = [c.condition_name for c in resolved if c.status in ("UNKNOWN", "NOT_AVAILABLE")]
    if blocking:
        return GATE_NOT_READY, blocking, incomplete
    if incomplete:
        return GATE_INCOMPLETE_EVIDENCE, blocking, incomplete
    return GATE_READY, blocking, incomplete


def evaluate_gate(
    gate_name: str,
    conditions: Sequence[Mapping[str, Any]],
    gate_verdicts: Optional[Mapping[str, str]] = None,
) -> GateEvaluation:
    """Evaluate exactly one of the 9 named gates against a caller-supplied
    condition list. ``gate_verdicts`` supplies already-computed verdicts for any
    earlier gate this gate's own AND-formula references as a sub-gate term
    (only ``AMBA_TEST_GENERATION_READY`` has any); omit it (or leave a
    referenced sub-gate absent from it) to have that sub-gate term read as
    UNKNOWN rather than derived.
    """
    if gate_name not in GATE_REQUIRED_CONDITIONS:
        raise AmbaReadinessGatesError(
            f"unknown gate {gate_name!r}; must be one of {GATE_NAMES}"
        )
    supplied = _validate_condition_records(conditions)
    gate_verdicts = gate_verdicts or {}
    sub_gate_refs = set(_SUB_GATE_REFERENCES[gate_name])
    resolved = [
        _resolve_condition(term, term in sub_gate_refs, supplied, gate_verdicts)
        for term in GATE_REQUIRED_CONDITIONS[gate_name]
    ]
    verdict, blocking, incomplete = _fold_gate_verdict(resolved)
    return GateEvaluation(
        gate_name=gate_name,
        verdict=verdict,
        conditions=resolved,
        blocking_conditions=blocking,
        incomplete_conditions=incomplete,
    )


def evaluate_amba_readiness_gates(
    conditions: Sequence[Mapping[str, Any]]
) -> AmbaReadinessReport:
    """Evaluate all 9 named gates in the source document's own fixed order
    (L3_REFERENCE_READY -> ... -> AMBA_SIGNOFF_READY), so that
    AMBA_TEST_GENERATION_READY's sub-gate references (AMBA_CONSTRAINT_READY,
    AMBA_CONNECTIVITY_READY, AMBA_VIP_BIND_READY) are always evaluated before
    it needs them. ``conditions`` is validated ONCE and reused for every gate
    -- a caller supplies one flat list naming whichever conditions it has
    evidence for; a condition name irrelevant to a given gate is simply
    ignored by that gate's own evaluation.
    """
    supplied = _validate_condition_records(conditions)  # validate once, fail fast
    report = AmbaReadinessReport()
    computed_verdicts: Dict[str, str] = {}
    for gate_name in GATE_NAMES:
        evaluation = evaluate_gate(
            gate_name,
            [c.to_dict() for c in supplied.values()],
            gate_verdicts=computed_verdicts,
        )
        report.gates[gate_name] = evaluation
        computed_verdicts[gate_name] = evaluation.verdict
    return report


# --------------------------------------------------------------------------
# Rendering / CLI
# --------------------------------------------------------------------------


def render_readiness_report(report: AmbaReadinessReport) -> str:
    lines = ["AMBA Readiness Gates", "=" * 21, ""]
    for gate_name in GATE_NAMES:
        gate = report.gates[gate_name]
        lines.append(f"{gate_name}: {gate.verdict}")
        for cond in gate.conditions:
            tag = " (sub-gate)" if cond.is_sub_gate_reference else ""
            lines.append(f"  - {cond.condition_name}{tag}: {cond.status}")
        if gate.blocking_conditions:
            lines.append(f"  BLOCKED BY: {', '.join(gate.blocking_conditions)}")
        if gate.incomplete_conditions:
            lines.append(f"  INCOMPLETE: {', '.join(gate.incomplete_conditions)}")
        lines.append("")
    lines.append(f"Worst verdict across all 9 gates: {report.worst_verdict()}")
    return "\n".join(lines)


def execute_verb(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(prog="amba_readiness_gates")
    sub = parser.add_subparsers(dest="verb", required=True)

    gates_parser = sub.add_parser("gates", help="list the 9 gate names")
    gates_parser.add_argument("--json", action="store_true")

    conditions_parser = sub.add_parser(
        "conditions", help="list one gate's required condition names"
    )
    conditions_parser.add_argument("--gate", required=True, choices=GATE_NAMES)
    conditions_parser.add_argument("--json", action="store_true")

    evaluate_parser = sub.add_parser("evaluate", help="evaluate all 9 gates")
    evaluate_parser.add_argument(
        "--conditions", required=True, help="path to a JSON list of condition records"
    )
    evaluate_parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.verb == "gates":
        if args.json:
            print(json.dumps(list(GATE_NAMES), indent=2))
        else:
            print("\n".join(GATE_NAMES))
        return 0

    if args.verb == "conditions":
        terms = GATE_REQUIRED_CONDITIONS[args.gate]
        if args.json:
            print(json.dumps(list(terms), indent=2))
        else:
            print("\n".join(terms))
        return 0

    if args.verb == "evaluate":
        try:
            with open(args.conditions, "r", encoding="utf-8") as handle:
                conditions = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"NOT_AVAILABLE: could not read conditions file: {exc}", file=sys.stderr)
            return 2
        try:
            report = evaluate_amba_readiness_gates(conditions)
        except AmbaReadinessGatesError as exc:
            print(f"NOT_AVAILABLE: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(render_readiness_report(report))
        worst = report.worst_verdict()
        if worst == GATE_NOT_READY:
            return 1
        if worst == GATE_INCOMPLETE_EVIDENCE:
            return 1
        return 0

    parser.error(f"unknown verb: {args.verb}")
    return 2


def main() -> None:
    import sys

    sys.exit(execute_verb())


if __name__ == "__main__":
    main()
