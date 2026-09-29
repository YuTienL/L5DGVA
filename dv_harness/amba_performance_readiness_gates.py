"""AMBA performance readiness gates: two composite gates -- ``BUS_PERFORMANCE_READY`` and
``BUS_PERFORMANCE_SIGNOFF_READY`` -- each a real AND-formula over caller-supplied condition
inputs, matching this project's other composite-gate modules (``amba_readiness_gates.py``,
``subsystem_maturity_gate.py``, ``functional_coverage_signoff.py``, ``spec_vplan_readiness_
gate.py``, ``system_readiness_gates.py``).

THIS IS THE HIGHEST FABRICATION-RISK DOMAIN IN THIS PROJECT: PERFORMANCE. This harness has no
live simulator and no formal timing tool, so this module never computes, measures, or estimates
a single performance number -- it only folds already-real ``{"condition_name": ..., "status":
...}`` records a caller supplies. Per this batch's file-safety scope this module deliberately
imports NOTHING from ``amba_performance_calculator.py``, ``amba_performance_requirement_
checker.py``, or ``amba_performance_classification.py`` -- it never assumes any of those three
modules exist, ran, or finished cleanly in the same batch. Whatever those modules concluded
reaches this gate only as a generic, duck-typed condition record naming their conceptual output
(e.g. ``Performance_Target_Declared``, ``Performance_Requirement_Evaluation_Complete``) -- this
module never inspects a waveform, a sim.log, or an fsdb_report.py output itself, and never
decides what counts as satisfying a named condition.

Three fabrication-risk rules are enforced IN CODE here, never left as a docstring promise:

(a) A numeric threshold/target is NEVER invented by this module. It has no field anywhere for a
    number. A caller either supplies a condition record saying whether a target was declared
    (``Performance_Target_Declared``: MET/UNMET/UNKNOWN/NOT_AVAILABLE) or the whole performance
    dimension is marked NOT_APPLICABLE for a project/path that is not performance-critical (see
    below) -- there is no third path where this module guesses a plausible-looking number.
(b) An unprovable peak/baseline/metric condition yields UNKNOWN/NOT_AVAILABLE, which this
    module folds to ``INCOMPLETE_EVIDENCE`` -- never a computed-looking percentage, never
    silently promoted to READY (GF-AT-28), and never forced into a confirmed NOT_READY it was
    never proven to be.
(c) Functional correctness ALWAYS outranks a performance PASS. Every gate's own AND-formula
    below includes a ``Functional_Correctness_Confirmed`` term; because the fold is a strict
    AND (worst-wins, never averaged or weighted), a functionally-incorrect transaction
    (``Functional_Correctness_Confirmed`` == UNMET) blocks the WHOLE gate as NOT_READY
    regardless of how many performance conditions on that same gate read MET -- a hard
    precedence enforced by the fold's own arithmetic, never a score a high performance number
    could outweigh.

Discipline, matching this project's other composite-gate modules: worst-wins, never averaged.
A single UNMET condition blocks the WHOLE gate as NOT_READY regardless of how many other
conditions on that gate are clean. Only once no condition is UNMET does an UNKNOWN/
NOT_AVAILABLE condition -- or a condition nobody supplied evidence for at all -- make the gate
INCOMPLETE_EVIDENCE rather than either READY or NOT_READY.

An explicit, CALLER-DECLARED ``NOT_APPLICABLE`` outcome is supported for a project/path that is
not performance-critical. This is never inferred by this module from the condition list itself
(there is no rule like "no performance conditions supplied means not applicable" -- that would
silently read an unmeasured project as one with nothing to measure); it is only ever produced
when the caller explicitly declares ``not_applicable=True`` with a real, non-empty ``reason``.
This lets a project that genuinely has no performance-critical path skip this dimension of
signoff honestly, without forcing every project through a performance dimension it does not
need, and without ever guessing that skip on the harness's own initiative.

``BUS_PERFORMANCE_SIGNOFF_READY``'s own AND-formula names ``BUS_PERFORMANCE_READY`` as one of
its terms, exactly as ``AMBA_TEST_GENERATION_READY`` names three earlier gates in
``amba_readiness_gates.py``: the two gates are evaluated in a fixed order (READY, then
SIGNOFF_READY) so that sub-gate reference is always already computed by the time it is needed,
and an explicit caller-supplied condition record naming ``BUS_PERFORMANCE_READY`` directly
always outranks the derived sub-gate verdict -- the same "real evidence outranks a derived
value" precedence this project's Source Authority Order already applies everywhere else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from dv_harness.models import Status

# --------------------------------------------------------------------------
# Vocabularies
# --------------------------------------------------------------------------

# Per-condition evidence status, supplied by the caller for each named AND-term. MET/UNMET are
# a caller's real evidence-backed judgment about that one named condition; UNKNOWN/NOT_AVAILABLE
# are the honest "we could not tell" states -- kept as two distinct reasons rather than one, the
# same discipline amba_readiness_gates.py already applies (a condition nobody could check is a
# different fact from one whose evidence source itself does not exist).
CONDITION_STATUSES: Tuple[str, ...] = ("MET", "UNMET", "UNKNOWN", "NOT_AVAILABLE")

# A condition a caller's list simply never mentions -- distinct from an explicit
# UNKNOWN/NOT_AVAILABLE record, but folded identically (never silently READY).
CONDITION_NOT_SUPPLIED = "NOT_SUPPLIED"

# Per-gate verdict.
GATE_READY = "READY"
GATE_NOT_READY = "NOT_READY"
GATE_INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"
GATE_NOT_APPLICABLE = "NOT_APPLICABLE"
GATE_VERDICTS: Tuple[str, ...] = (
    GATE_READY,
    GATE_NOT_READY,
    GATE_INCOMPLETE_EVIDENCE,
    GATE_NOT_APPLICABLE,
)

# Maps a computed sub-gate verdict onto the condition-status vocabulary, so a gate-name term
# inside another gate's AND-formula (BUS_PERFORMANCE_SIGNOFF_READY's reference to
# BUS_PERFORMANCE_READY) is folded through the exact same worst-wins rule as every other
# condition. A sub-gate that was itself NOT_APPLICABLE folds as MET here -- a performance
# dimension a caller has explicitly declared irrelevant must never block a later gate that
# references it.
_GATE_VERDICT_TO_CONDITION_STATUS: Dict[str, str] = {
    GATE_READY: "MET",
    GATE_NOT_READY: "UNMET",
    GATE_INCOMPLETE_EVIDENCE: "UNKNOWN",
    GATE_NOT_APPLICABLE: "MET",
}


class AmbaPerformanceReadinessGatesError(ValueError):
    """Raised for malformed input -- never silently repaired or dropped."""


def _assert_no_verification_verdict_vocabulary() -> None:
    """This module's own vocabularies must share no token with ``models.Status`` -- the same
    guard several sibling composite-gate modules already apply to themselves, so a per-condition
    MET/UNMET/UNKNOWN and a per-gate READY/NOT_READY/INCOMPLETE_EVIDENCE/NOT_APPLICABLE can never
    be misread as a stage verdict."""
    status_values = {member.value for member in Status}
    collisions = (set(CONDITION_STATUSES) | set(GATE_VERDICTS)) & status_values
    if collisions:
        raise AssertionError(
            "amba_performance_readiness_gates vocabulary collides with dv_harness.models.Status: "
            f"{sorted(collisions)}"
        )


_assert_no_verification_verdict_vocabulary()

# --------------------------------------------------------------------------
# The 2 named gates. Each tuple is the gate's own AND-formula, term for term.
# ``Functional_Correctness_Confirmed`` appears on BOTH gates deliberately -- functional
# correctness always outranks a performance PASS, so it is re-asserted at signoff rather than
# trusted to have stayed true since the earlier gate.
# --------------------------------------------------------------------------

GATE_NAMES: Tuple[str, ...] = (
    "BUS_PERFORMANCE_READY",
    "BUS_PERFORMANCE_SIGNOFF_READY",
)

GATE_REQUIRED_CONDITIONS: Dict[str, Tuple[str, ...]] = {
    "BUS_PERFORMANCE_READY": (
        # Functional correctness always outranks a performance PASS (rule c above): a single
        # UNMET here blocks this whole gate regardless of how clean every performance condition
        # below reads.
        "Functional_Correctness_Confirmed",
        # A numeric threshold/target is CALLER-declared or this gate is NOT_APPLICABLE (rule a):
        # this module never invents one, so this condition asks only whether the caller's own
        # evidence pipeline recorded a real declared target.
        "Performance_Target_Declared",
        # An unprovable peak/baseline metric yields UNKNOWN, never a computed-looking number
        # (rule b): this condition asks only whether a real baseline/peak metric was actually
        # captured by whatever real artifact (fsdb_report.py output, a sim.log, a caller-supplied
        # trace record) the caller's own pipeline produced.
        "Baseline_Metric_Captured",
        # How the metric above was actually measured must itself be traceable -- an unprovable
        # methodology is exactly the "silently divide by a value nobody actually supplied" trap
        # rule (b) forbids.
        "Measurement_Methodology_Defined",
        "Critical_UNKNOWN",
    ),
    "BUS_PERFORMANCE_SIGNOFF_READY": (
        "BUS_PERFORMANCE_READY",
        # Re-asserted at signoff: functional correctness still outranks performance at the point
        # of signoff, not only at the earlier readiness check.
        "Functional_Correctness_Confirmed",
        # Whatever real regression-comparison evidence the caller's own pipeline produced
        # (current run vs. the declared baseline) -- this module never re-derives the comparison
        # itself.
        "Performance_Regression_Comparison_Complete",
        # The caller's own performance-requirement-checking pipeline (conceptually
        # amba_performance_requirement_checker.py's output, never imported here) concluded and
        # is reported as one condition record.
        "Performance_Requirement_Evaluation_Complete",
        "Critical_UNKNOWN",
    ),
}

# Terms inside GATE_REQUIRED_CONDITIONS that are themselves gate names, i.e. sub-gate references
# rather than raw caller-measured conditions.
_SUB_GATE_REFERENCES: Dict[str, Tuple[str, ...]] = {
    gate_name: tuple(term for term in terms if term in GATE_NAMES)
    for gate_name, terms in GATE_REQUIRED_CONDITIONS.items()
}


def _assert_gate_table_well_formed() -> None:
    """Every declared gate name has a required-condition tuple, every sub-gate reference names a
    real gate, and no gate references itself or a gate that comes AFTER it in GATE_NAMES's own
    fixed order (which would make single-pass, no-recursion evaluation in that order unsound)."""
    if set(GATE_REQUIRED_CONDITIONS) != set(GATE_NAMES):
        raise AssertionError("GATE_REQUIRED_CONDITIONS must declare exactly GATE_NAMES")
    for index, gate_name in enumerate(GATE_NAMES):
        for term in _SUB_GATE_REFERENCES[gate_name]:
            if term not in GATE_NAMES:
                raise AssertionError(f"{gate_name} references unknown gate {term!r}")
            if GATE_NAMES.index(term) >= index:
                raise AssertionError(
                    f"{gate_name} references {term!r}, which does not come strictly earlier in "
                    "GATE_NAMES's fixed evaluation order"
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
class NotApplicableDeclaration:
    """A caller's explicit, real declaration that a gate's performance dimension does not apply
    to this project/path -- never inferred by this module from an absent or empty condition
    list."""

    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {"not_applicable": True, "reason": self.reason}


@dataclass
class GateEvaluation:
    """One of the 2 named gates' evaluated verdict, with full per-condition evidence."""

    gate_name: str
    verdict: str
    conditions: List[ConditionEvaluation] = field(default_factory=list)
    blocking_conditions: List[str] = field(default_factory=list)
    incomplete_conditions: List[str] = field(default_factory=list)
    not_applicable_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_name": self.gate_name,
            "verdict": self.verdict,
            "conditions": [c.to_dict() for c in self.conditions],
            "blocking_conditions": list(self.blocking_conditions),
            "incomplete_conditions": list(self.incomplete_conditions),
            "not_applicable_reason": self.not_applicable_reason,
        }


@dataclass
class AmbaPerformanceReadinessReport:
    """Both named gates, evaluated in the document's own fixed order."""

    gates: Dict[str, GateEvaluation] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {name: gate.to_dict() for name, gate in self.gates.items()}

    def verdict_for(self, gate_name: str) -> str:
        if gate_name not in self.gates:
            raise AmbaPerformanceReadinessGatesError(f"unknown gate: {gate_name!r}")
        return self.gates[gate_name].verdict

    def worst_verdict(self) -> str:
        """The worst verdict across both gates (NOT_READY worse than INCOMPLETE_EVIDENCE worse
        than READY/NOT_APPLICABLE, the latter two treated as equally non-blocking) -- a
        convenience rollup; each gate's own verdict remains the authoritative per-gate answer."""
        order = {
            GATE_READY: 0,
            GATE_NOT_APPLICABLE: 0,
            GATE_INCOMPLETE_EVIDENCE: 1,
            GATE_NOT_READY: 2,
        }
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
    """Validate and index the caller-supplied condition list. Raises on any malformed or
    duplicate record rather than silently dropping or coercing it."""
    if not isinstance(conditions, (list, tuple)):
        raise AmbaPerformanceReadinessGatesError(
            f"conditions must be a list/tuple of records, got {type(conditions).__name__}"
        )
    indexed: Dict[str, ConditionEvaluation] = {}
    for entry in conditions:
        if not isinstance(entry, Mapping):
            raise AmbaPerformanceReadinessGatesError(
                f"condition record must be a mapping, got {entry!r}"
            )
        name = entry.get("condition_name")
        status = entry.get("status")
        if not isinstance(name, str) or not name.strip():
            raise AmbaPerformanceReadinessGatesError(
                f"condition record missing a real condition_name: {entry!r}"
            )
        if not isinstance(status, str) or status not in CONDITION_STATUSES:
            raise AmbaPerformanceReadinessGatesError(
                f"condition {name!r} has an unrecognized status {status!r}; must be one of "
                f"{CONDITION_STATUSES}"
            )
        if name in indexed:
            raise AmbaPerformanceReadinessGatesError(f"duplicate condition_name in input: {name!r}")
        reason = entry.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise AmbaPerformanceReadinessGatesError(
                f"condition {name!r} has a non-string reason: {reason!r}"
            )
        indexed[name] = ConditionEvaluation(
            condition_name=name, status=status, reason=reason, source="caller_supplied"
        )
    return indexed


def _validate_not_applicable_declaration(
    gate_name: str, declaration: Optional[Mapping[str, Any]]
) -> Optional[NotApplicableDeclaration]:
    """A NOT_APPLICABLE declaration is only ever honored when explicit and real: a caller must
    set ``not_applicable: True`` AND supply a non-empty ``reason``. Anything else (absent,
    ``not_applicable: False``, or a missing/blank reason) is refused rather than silently
    accepted or silently ignored, since a NOT_APPLICABLE outcome must never be inferred by this
    module on its own initiative."""
    if declaration is None:
        return None
    if not isinstance(declaration, Mapping):
        raise AmbaPerformanceReadinessGatesError(
            f"{gate_name}: not_applicable_declaration must be a mapping, got {declaration!r}"
        )
    flag = declaration.get("not_applicable")
    if flag is False or flag is None:
        return None
    if flag is not True:
        raise AmbaPerformanceReadinessGatesError(
            f"{gate_name}: not_applicable_declaration['not_applicable'] must be a real bool, "
            f"got {flag!r}"
        )
    reason = declaration.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise AmbaPerformanceReadinessGatesError(
            f"{gate_name}: a not_applicable declaration requires a real, non-empty 'reason' -- "
            "an unreasoned skip is never accepted"
        )
    return NotApplicableDeclaration(reason=reason)


def _resolve_condition(
    condition_name: str,
    is_sub_gate_reference: bool,
    supplied: Mapping[str, ConditionEvaluation],
    gate_verdicts: Mapping[str, str],
) -> ConditionEvaluation:
    """Resolve one AND-term to its evaluated status. A caller-supplied record for this exact
    name always wins (real evidence outranks a derived value, this project's Source Authority
    Order applied here). Absent that, a sub-gate reference is derived from the already-computed
    sub-gate verdict. Absent both, the condition was simply never supplied -- honestly UNKNOWN,
    never silently READY/MET."""
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
    """Worst-wins fold: any UNMET blocks the whole gate as NOT_READY regardless of how many
    other conditions are clean; only absent that does any UNKNOWN/NOT_AVAILABLE condition make
    the gate INCOMPLETE_EVIDENCE; only when every condition is MET does the gate read READY.
    This is also where rule (c) -- functional correctness always outranks a performance PASS --
    is actually enforced: a single UNMET ``Functional_Correctness_Confirmed`` term folds the
    same way as any other UNMET term, blocking the gate outright rather than being averaged
    against however many performance conditions read MET."""
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
    not_applicable_declaration: Optional[Mapping[str, Any]] = None,
) -> GateEvaluation:
    """Evaluate exactly one of the 2 named gates against a caller-supplied condition list.
    ``gate_verdicts`` supplies the already-computed verdict for ``BUS_PERFORMANCE_READY`` when
    evaluating ``BUS_PERFORMANCE_SIGNOFF_READY`` (omit it, or leave that sub-gate absent from it,
    to have that term read as UNKNOWN rather than derived). ``not_applicable_declaration``, when
    it carries a real ``{"not_applicable": True, "reason": "..."}`` record, short-circuits this
    gate to ``NOT_APPLICABLE`` without evaluating any condition at all -- the project/path this
    gate covers is not performance-critical, per the caller's own explicit statement.
    """
    if gate_name not in GATE_REQUIRED_CONDITIONS:
        raise AmbaPerformanceReadinessGatesError(
            f"unknown gate {gate_name!r}; must be one of {GATE_NAMES}"
        )
    not_applicable = _validate_not_applicable_declaration(gate_name, not_applicable_declaration)
    if not_applicable is not None:
        return GateEvaluation(
            gate_name=gate_name,
            verdict=GATE_NOT_APPLICABLE,
            conditions=[],
            blocking_conditions=[],
            incomplete_conditions=[],
            not_applicable_reason=not_applicable.reason,
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


def evaluate_amba_performance_readiness_gates(
    conditions: Sequence[Mapping[str, Any]],
    not_applicable_declarations: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> AmbaPerformanceReadinessReport:
    """Evaluate both named gates in a fixed order (``BUS_PERFORMANCE_READY`` ->
    ``BUS_PERFORMANCE_SIGNOFF_READY``), so that ``BUS_PERFORMANCE_SIGNOFF_READY``'s own sub-gate
    reference is always already evaluated before it needs it. ``conditions`` is validated ONCE
    and reused for every gate -- a caller supplies one flat list naming whichever conditions it
    has evidence for; a condition name irrelevant to a given gate is simply ignored by that
    gate's own evaluation. ``not_applicable_declarations`` optionally maps a gate name to its own
    explicit NOT_APPLICABLE declaration (see ``evaluate_gate``); a gate absent from it is
    evaluated normally.
    """
    supplied = _validate_condition_records(conditions)  # validate once, fail fast
    not_applicable_declarations = not_applicable_declarations or {}
    report = AmbaPerformanceReadinessReport()
    computed_verdicts: Dict[str, str] = {}
    for gate_name in GATE_NAMES:
        evaluation = evaluate_gate(
            gate_name,
            [c.to_dict() for c in supplied.values()],
            gate_verdicts=computed_verdicts,
            not_applicable_declaration=not_applicable_declarations.get(gate_name),
        )
        report.gates[gate_name] = evaluation
        computed_verdicts[gate_name] = evaluation.verdict
    return report


# --------------------------------------------------------------------------
# Rendering / CLI
# --------------------------------------------------------------------------


def render_readiness_report(report: AmbaPerformanceReadinessReport) -> str:
    lines = ["AMBA Performance Readiness Gates", "=" * 32, ""]
    for gate_name in GATE_NAMES:
        gate = report.gates[gate_name]
        lines.append(f"{gate_name}: {gate.verdict}")
        if gate.verdict == GATE_NOT_APPLICABLE:
            lines.append(f"  NOT_APPLICABLE: {gate.not_applicable_reason}")
            lines.append("")
            continue
        for cond in gate.conditions:
            tag = " (sub-gate)" if cond.is_sub_gate_reference else ""
            lines.append(f"  - {cond.condition_name}{tag}: {cond.status}")
        if gate.blocking_conditions:
            lines.append(f"  BLOCKED BY: {', '.join(gate.blocking_conditions)}")
        if gate.incomplete_conditions:
            lines.append(f"  INCOMPLETE: {', '.join(gate.incomplete_conditions)}")
        lines.append("")
    lines.append(f"Worst verdict across both gates: {report.worst_verdict()}")
    return "\n".join(lines)


def execute_verb(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(prog="amba_performance_readiness_gates")
    sub = parser.add_subparsers(dest="verb", required=True)

    gates_parser = sub.add_parser("gates", help="list the 2 gate names")
    gates_parser.add_argument("--json", action="store_true")

    conditions_parser = sub.add_parser(
        "conditions", help="list one gate's required condition names"
    )
    conditions_parser.add_argument("--gate", required=True, choices=GATE_NAMES)
    conditions_parser.add_argument("--json", action="store_true")

    evaluate_parser = sub.add_parser("evaluate", help="evaluate both gates")
    evaluate_parser.add_argument(
        "--conditions", required=True, help="path to a JSON list of condition records"
    )
    evaluate_parser.add_argument(
        "--not-applicable",
        help="path to a JSON object mapping gate name to its NOT_APPLICABLE declaration",
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
        not_applicable_declarations = None
        if args.not_applicable:
            try:
                with open(args.not_applicable, "r", encoding="utf-8") as handle:
                    not_applicable_declarations = json.load(handle)
            except (OSError, json.JSONDecodeError) as exc:
                print(
                    f"NOT_AVAILABLE: could not read not-applicable file: {exc}", file=sys.stderr
                )
                return 2
        try:
            report = evaluate_amba_performance_readiness_gates(
                conditions, not_applicable_declarations=not_applicable_declarations
            )
        except AmbaPerformanceReadinessGatesError as exc:
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
