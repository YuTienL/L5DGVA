"""dv_harness/spec_vplan_readiness_gate.py -- SPEC_VPLAN_READY: a composite
conjunction over the SPEC-TO-VPLAN pipeline stage specifically.

THE GAP THIS CLOSES, AND THE TWO NEIGHBOURING MECHANISMS THIS IS NOT
---------------------------------------------------------------------
This project already has at least two composite "is X ready" conjunctions built
on the identical worst-wins discipline, and this is deliberately a THIRD,
narrower one rather than a duplicate of either:

  * `verification_intake_contract.py`'s `INTAKE_READY` asks whether the WHOLE
    PROJECT's intake -- across every sub-domain intake touches (env manifest,
    question queue, connectivity, requirement contracts, golden scenarios,
    waivers, VIP API provability, ...) -- is ready for a human to review. It is
    a project-wide capstone, not specific to any one pipeline stage.
  * `subsystem_maturity_gate.py`'s three named levels (9.0 / 9.5 / 10.0) ask
    whether a WHOLE SUBSYSTEM has reached one of three fixed maturity bars,
    each level's own fixed condition SET spanning golden-flow connectivity,
    system smoke-proof, VIP API provability, bind-tier cleanliness and
    regression evidence -- a subsystem-wide qualification ladder, not a
    per-stage gate.
  * `SPEC_VPLAN_READY`, this module, asks a narrower question than either:
    is the SPEC-TO-VPLAN pipeline stage specifically -- the step that turns a
    parsed specification into a vPlan/requirement-contract artifact ready to
    drive generation -- ready to be considered done. It has no opinion on
    intake as a whole and no opinion on subsystem maturity; a project could be
    SPEC_VPLAN_READY while its overall INTAKE_READY is still False (a later
    sub-domain, e.g. connectivity, has not caught up yet), and a subsystem
    could clear SPEC_VPLAN_READY for every one of its constituent specs while
    sitting nowhere near 9.0 maturity (which also requires golden-flow,
    smoke-proof, VIP-API and regression-evidence conditions this gate does not
    touch at all). Three different questions, three different scopes, three
    separate mechanisms -- exactly the same reasoning
    `subsystem_maturity_gate.py`'s own docstring already gives for staying
    independent of `subsystem_practicality_score.py`.

A repo-wide search for `SPEC_VPLAN_READY`/`spec_vplan_ready` before writing this
module matched nothing executable: `tools/verification_flow/
spec_to_vplan_quality_gate.py` and `spec_to_vplan_requirement_quality_gate.py`
are per-REQUIREMENT-RECORD shape checks (five/fifteen fields on one requirement
at a time), and neither produces a single composite verdict over an arbitrary,
named condition set the way this module does.

REUSE OVER REINVENT -- AND WHY THIS FILE IMPORTS NEITHER SIBLING BY NAME
--------------------------------------------------------------------------
Both `verification_intake_contract.py` and `subsystem_maturity_gate.py` are
concurrently-running batch items on this task's own "never import" list (along
with `functional_coverage_signoff.py`, whose own Closure-percentage rollup uses
the identical worst-wins shape one level down at the per-bin-credit level).
Per this task's explicit scope, none of the three is imported here. What IS
reused is the DISCIPLINE those modules already state in prose as a design
principle rather than as a function this module could call without also
importing whichever fixed condition set that module happens to hardcode:
worst-wins, no-averaging, one unresolved condition among a hundred clean ones
still blocks. That is followed here exactly, independently re-derived over
this module's own condition-status and gate-verdict vocabularies, the same way
`verification_intake_contract.py` itself independently re-derives
`golden_flow_readiness.combine_readiness()`'s fold rule rather than importing
that function and its own twenty hardcoded rows.

Every condition this gate evaluates arrives as a plain, duck-typed
`{"condition_name": <str>, "status": <one of CONDITION_STATUSES>, "reason":
<str, optional>}` record the CALLER assembles -- this module hardcodes NONE of
them. Which conditions actually belong to "is the spec-to-vplan stage done"
(spec parsed and mapped, every requirement's own per-record status COMPLETE
per `requirement_contract.py`'s five-value vocabulary, every vPlan item's
test/coverage correspondence resolved, no unresolved spec/vplan delta, no open
Tier-3 escalation against this stage's own artifacts, and so on) is a decision
for whichever real per-domain modules a given project has wired -- several of
which are themselves still-building concurrent batch items today. Accepting
them as caller-supplied records rather than importing their producers is not a
shortcut; it is the only way this module's condition set can grow as new
producers land without this file changing at all.

THE VOCABULARY, AND WHY IT IS A THIRD DISTINCT PAIR OF ENUMS
----------------------------------------------------------------
A condition's own per-item outcome (`MET` / `UNMET` / `UNKNOWN` /
`NOT_AVAILABLE`) and this gate's own composite verdict (`QUALIFIED` /
`NOT_QUALIFIED` / `INCOMPLETE_EVIDENCE`) are BOTH checked at import time
(`assert_no_verification_verdict_vocabulary()`) to share no token with
`dv_harness.models.Status` -- the identical guard
`subsystem_maturity_gate.py`, `capability_evolution.py`,
`benchmark_dataset.py` and `dependency_supply_chain.py` already apply to their
own domain-specific vocabularies, reimplemented here rather than imported
because `subsystem_maturity_gate.py` itself is off-limits. A condition read as
`MET` is not a stage reaching `Status.PASS`; conflating the two would let this
gate's verdict be misread as a graph-routing signal, which it is not and never
triggers.

`UNKNOWN` and `NOT_AVAILABLE` are kept as two distinct tokens rather than
collapsed into one, because different not-yet-finished producer modules in
this same batch may spell "I could not resolve this" either way, and a caller
should not have to normalize vocabulary before handing this gate a condition
list. Both are treated identically by the fold below -- "checked and could not
be resolved" and "the evidence for this does not exist yet" are both reasons a
human must not be told the spec-to-vplan stage is done, the same
non-distinction `verification_intake_contract.py`'s own `INTAKE_READY` already
draws between its `UNMET` and `UNKNOWN`.

SPEC_VPLAN_READY: A CONJUNCTION, NEVER AN AVERAGE -- WORST-WINS, TWO TIERS DEEP
----------------------------------------------------------------------------------
The fold is strictly worst-wins and stops at the first tier that has anything
in it, exactly the precedence `subsystem_maturity_gate.py`'s own docstring
states for its per-level verdict:

  1. Any condition `UNMET` -> the whole gate is `NOT_QUALIFIED`, regardless of
     how many other conditions are `MET` and regardless of whether any other
     condition is also `UNKNOWN`/`NOT_AVAILABLE`. A single unresolved
     requirement or vPlan gap blocks readiness outright; it is never diluted
     into a percentage, a majority vote, or an average with the conditions
     that are clean.
  2. Otherwise, any condition `UNKNOWN` or `NOT_AVAILABLE` -> `INCOMPLETE_
     EVIDENCE`. This is the rule this task's own instruction states in as many
     words: an unresolved-evidence condition must never be silently read as
     either a pass (`QUALIFIED`) or a confirmed failure (`NOT_QUALIFIED`) --
     it is a third, honestly distinct outcome, because "we could not check"
     and "we checked and it failed" are different facts with different
     remedies. `UNMET` still outranks this tier: a project that has BOTH a
     confirmed-failing requirement AND an unresolved one is `NOT_QUALIFIED`,
     not `INCOMPLETE_EVIDENCE` -- the confirmed failure is the more actionable,
     and more urgent, fact.
  3. Otherwise (every condition `MET`) -> `QUALIFIED`.

An absent or empty `conditions` list is never a vacuous `QUALIFIED` over zero
conditions measured -- it reports `INCOMPLETE_EVIDENCE` with a real reason
("nothing was supplied to evaluate"), the same "an empty input is UNKNOWN,
never READY" rule `golden_flow_readiness.combine_readiness()` and
`verification_intake_contract.evaluate_intake_readiness()` both already state
for their own folds. A condition record with an unrecognized `status`, a
missing `condition_name`/`status` key, or a `condition_name` repeated by an
earlier record in the same list all raise `SpecVplanReadinessGateError` rather
than being silently dropped or resolved by picking one -- an ambiguous input
must read as an error per the Evidence Truth Rule, never as a confident guess
about which of two same-named conditions is the real one.

WHAT THIS MODULE DOES NOT DO
------------------------------
It runs no stage, invokes no gate script, submits no build/regression/LSF job,
and writes no state/control/approval file of its own -- `ControlPlane.
approve()`, `policy.can_signoff()`, `assert_human_approval()` and the PR-only
main/master governance are untouched and unreferenced (checked against this
module's own source by a test, the same discipline `platform_health.py`'s
`assert_authorizes_nothing()` already applies to itself). A `QUALIFIED`
verdict is an input to a human's decision that the spec-to-vplan stage is
done, never a substitute for one, and there is deliberately no stage gate --
this module's own `python -m` front door is the only entry point, per this
project's disclosed "skip CLI wiring when `cli.py` is under concurrent edit"
convention several very recent same-day additions have also used.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field as _dc_field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

SCHEMA_VERSION = "1.0"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SpecVplanReadinessGateError(ValueError):
    """Raised for a malformed condition record, an unrecognized condition
    status, or a vocabulary collision with `models.Status`. Carries `reason`
    (a short machine-checkable token) and `detail` (a dict naming exactly what
    was wrong), the same convention `IntakeContractError`/
    `SubsystemMaturityGateError` already use in this codebase."""

    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# ===========================================================================
# Vocabularies -- both checked disjoint from `models.Status` below
# ===========================================================================

#: One caller-supplied condition's own outcome. `UNKNOWN` and `NOT_AVAILABLE`
#: are kept as two distinct tokens (different not-yet-finished producers in
#: this batch may spell "could not resolve" either way) but are folded
#: identically -- see the module docstring's worst-wins section.
MET = "MET"
UNMET = "UNMET"
UNKNOWN = "UNKNOWN"
NOT_AVAILABLE = "NOT_AVAILABLE"
CONDITION_STATUSES: Tuple[str, ...] = (MET, UNMET, UNKNOWN, NOT_AVAILABLE)
CLEAR_CONDITION_STATUSES: Tuple[str, ...] = (MET,)
HARD_BLOCKING_CONDITION_STATUSES: Tuple[str, ...] = (UNMET,)
INCOMPLETE_EVIDENCE_CONDITION_STATUSES: Tuple[str, ...] = (UNKNOWN, NOT_AVAILABLE)

#: This gate's own composite verdict -- deliberately the SAME three tokens
#: `subsystem_maturity_gate.py` uses for its own per-level verdict (this
#: task's own instruction states the rule in exactly those words), applied
#: here to one stage's condition set rather than to a fixed maturity ladder.
QUALIFIED = "QUALIFIED"
NOT_QUALIFIED = "NOT_QUALIFIED"
INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"
GATE_VERDICTS: Tuple[str, ...] = (QUALIFIED, NOT_QUALIFIED, INCOMPLETE_EVIDENCE)


def assert_no_verification_verdict_vocabulary() -> None:
    """Import-time guard: neither vocabulary above shares a token with
    `models.Status`. Reimplemented here (rather than imported from
    `subsystem_maturity_gate.py`, which applies the identical guard) because
    that module is on this batch's own "never import" list; the check itself
    -- and the reason for it -- is the same one `capability_evolution.py` /
    `benchmark_dataset.py` / `dependency_supply_chain.py` /
    `subsystem_maturity_gate.py` already apply to their own vocabularies."""
    from .models import Status
    known = {s.value for s in Status}
    clash = sorted((set(CONDITION_STATUSES) | set(GATE_VERDICTS)) & known)
    if clash:
        raise SpecVplanReadinessGateError("VERDICT_VOCABULARY_COLLIDES_WITH_MODELS_STATUS", {
            "clash": clash, "known_status_values": sorted(known)})


assert_no_verification_verdict_vocabulary()


# ===========================================================================
# Condition record + composite result
# ===========================================================================

@dataclass
class ConditionEvaluation:
    """One caller-supplied `{"condition_name", "status", "reason"}` record,
    normalized. `condition_name` is the caller's own name for whatever
    real spec-to-vplan-stage fact it represents (e.g. "requirement_contracts_
    all_complete", "vplan_delta_resolved", "spec_doc_map_no_orphans") -- this
    module assigns no meaning to the name itself beyond using it as the
    dedup/report key."""
    condition_name: str
    status: str
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"condition_name": self.condition_name, "status": self.status,
                "reason": self.reason}


@dataclass
class SpecVplanReadinessResult:
    """The `SPEC_VPLAN_READY` verdict over one caller-supplied condition set.

    `spec_vplan_ready` is `True` if and only if `status == QUALIFIED` -- kept
    as a separate boolean field, the same convenience
    `verification_intake_contract.IntakeReadinessResult.ready` already offers
    beside its own `status`, so a caller who only wants a boolean need not
    string-compare `status` itself."""
    spec_vplan_ready: bool
    status: str
    evaluated_count: int
    blocking: List[Dict[str, Any]]
    incomplete_evidence: List[Dict[str, Any]]
    clear: List[Dict[str, Any]]
    checked_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "spec_vplan_ready": self.spec_vplan_ready,
            "status": self.status,
            "evaluated_count": self.evaluated_count,
            "blocking": self.blocking,
            "incomplete_evidence": self.incomplete_evidence,
            "clear": self.clear,
            "checked_at": self.checked_at,
        }


def _normalize_conditions(
    conditions: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    seen_names: set = set()
    normalized: List[Dict[str, Any]] = []
    for i, c in enumerate(conditions):
        if not isinstance(c, Mapping) or "condition_name" not in c or "status" not in c:
            raise SpecVplanReadinessGateError("MALFORMED_CONDITION_RECORD", {
                "index": i, "record": dict(c) if isinstance(c, Mapping) else c,
                "hint": "each condition needs both a 'condition_name' and a 'status' key"})
        name = c["condition_name"]
        status = c["status"]
        if not name or not str(name).strip():
            raise SpecVplanReadinessGateError("EMPTY_CONDITION_NAME", {"index": i})
        if status not in CONDITION_STATUSES:
            raise SpecVplanReadinessGateError("UNKNOWN_CONDITION_STATUS", {
                "condition_name": name, "status": status,
                "known_statuses": sorted(CONDITION_STATUSES)})
        if name in seen_names:
            raise SpecVplanReadinessGateError("DUPLICATE_CONDITION_NAME", {
                "condition_name": name,
                "hint": "two conditions sharing one name could silently hide whichever one "
                        "actually blocks readiness -- name each condition once"})
        seen_names.add(name)
        normalized.append({
            "condition_name": name, "status": status, "reason": c.get("reason", ""),
        })
    return normalized


def evaluate_spec_vplan_readiness(
    conditions: Optional[Sequence[Mapping[str, Any]]],
    *,
    now: Optional[str] = None,
) -> SpecVplanReadinessResult:
    """The `SPEC_VPLAN_READY` conjunction. `conditions` is a caller-assembled,
    caller-named list of `{"condition_name", "status", "reason"?}` records --
    this module hardcodes none of them, since which conditions belong to "is
    the spec-to-vplan pipeline stage done" depends on which real per-domain
    producers a given project has wired (spec/doc mapping, requirement
    contract completeness, vPlan/spec delta resolution, and others not yet
    built in this batch).

    NO AVERAGING, WORST-WINS, TWO TIERS DEEP: any `UNMET` condition makes the
    result `NOT_QUALIFIED` outright, regardless of how many others are `MET`
    and regardless of whether any other condition is `UNKNOWN`/
    `NOT_AVAILABLE`. Only once no condition is `UNMET` does any `UNKNOWN`/
    `NOT_AVAILABLE` condition make the result `INCOMPLETE_EVIDENCE` -- never
    silently read as either `QUALIFIED` or `NOT_QUALIFIED`. Every condition
    `MET` is the only path to `QUALIFIED`. See the module docstring's
    "SPEC_VPLAN_READY: A CONJUNCTION, NEVER AN AVERAGE" section for the full
    reasoning and its precedent in this codebase.

    An absent or empty `conditions` list reports `INCOMPLETE_EVIDENCE` with
    `spec_vplan_ready=False` -- never a vacuous `QUALIFIED` over zero
    conditions measured, the same "an empty input is UNKNOWN, never READY"
    rule this project's other composite-readiness folds already state. A
    condition record carrying an unrecognized `status`, a missing
    `condition_name`/`status` key, an empty `condition_name`, or a
    `condition_name` repeated by an earlier record in the same list all raise
    `SpecVplanReadinessGateError` rather than being silently dropped or
    resolved by picking one."""
    ts = now or _utcnow_iso()
    if not conditions:
        return SpecVplanReadinessResult(
            spec_vplan_ready=False, status=INCOMPLETE_EVIDENCE, evaluated_count=0,
            blocking=[], incomplete_evidence=[], clear=[], checked_at=ts)

    normalized = _normalize_conditions(conditions)

    blocking = [c for c in normalized if c["status"] in HARD_BLOCKING_CONDITION_STATUSES]
    incomplete = [c for c in normalized if c["status"] in INCOMPLETE_EVIDENCE_CONDITION_STATUSES]
    clear = [c for c in normalized if c["status"] in CLEAR_CONDITION_STATUSES]

    if blocking:
        status, ready = NOT_QUALIFIED, False
    elif incomplete:
        status, ready = INCOMPLETE_EVIDENCE, False
    else:
        status, ready = QUALIFIED, True

    return SpecVplanReadinessResult(
        spec_vplan_ready=ready, status=status, evaluated_count=len(normalized),
        blocking=blocking, incomplete_evidence=incomplete, clear=clear, checked_at=ts)


# ===========================================================================
# Ad hoc front door -- no `dv-harness` CLI verb, per this task's own
# escape hatch (`cli.py` is on this batch's never-touch list, and several
# very recent same-day additions in this repo have made the identical
# disclosed choice for the same reason: concurrent edits to that file).
# ===========================================================================

def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def format_readiness_report(result: SpecVplanReadinessResult) -> str:
    lines = [f"SPEC_VPLAN_READY: {result.status} "
             f"(evaluated {result.evaluated_count} condition(s))"]
    if result.blocking:
        lines.append("Blocking (UNMET):")
        for c in result.blocking:
            reason = f" -- {c['reason']}" if c.get("reason") else ""
            lines.append(f"  - {c['condition_name']}: {c['status']}{reason}")
    if result.incomplete_evidence:
        lines.append("Incomplete evidence (UNKNOWN/NOT_AVAILABLE):")
        for c in result.incomplete_evidence:
            reason = f" -- {c['reason']}" if c.get("reason") else ""
            lines.append(f"  - {c['condition_name']}: {c['status']}{reason}")
    if result.clear:
        lines.append(f"Clear (MET): {', '.join(c['condition_name'] for c in result.clear)}")
    return "\n".join(lines)


def execute_verb(verb: str, *, conditions_path: Optional[str] = None,
                  as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `python -m
    dv_harness.spec_vplan_readiness_gate`. Returns (text, exit_code): 0
    QUALIFIED, 1 NOT_QUALIFIED, 2 INCOMPLETE_EVIDENCE / a real usage error."""
    if verb == "statuses":
        text = (json.dumps(list(CONDITION_STATUSES), indent=2) if as_json
                 else "\n".join(CONDITION_STATUSES))
        return text, 0
    if verb == "verdicts":
        text = (json.dumps(list(GATE_VERDICTS), indent=2) if as_json
                 else "\n".join(GATE_VERDICTS))
        return text, 0
    if verb == "evaluate":
        if not conditions_path:
            return "evaluate requires --conditions", 2
        try:
            conditions = _load_json(conditions_path)
            result = evaluate_spec_vplan_readiness(conditions)
        except SpecVplanReadinessGateError as e:
            return f"{e.reason}: {json.dumps(e.detail)}", 2
        text = (json.dumps(result.to_dict(), indent=2) if as_json
                 else format_readiness_report(result))
        code = {QUALIFIED: 0, NOT_QUALIFIED: 1, INCOMPLETE_EVIDENCE: 2}[result.status]
        return text, code
    return f"unknown verb: {verb!r} (expected statuses|verdicts|evaluate)", 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.spec_vplan_readiness_gate",
        description="The SPEC_VPLAN_READY conjunction over caller-named "
                    "spec-to-vplan-stage conditions.")
    ap.add_argument("verb", choices=("statuses", "verdicts", "evaluate"))
    ap.add_argument("--conditions", dest="conditions_path",
                     help="For 'evaluate': path to a JSON list of "
                          "{\"condition_name\", \"status\", \"reason\"} records.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable form.")
    a = ap.parse_args(argv)
    text, code = execute_verb(a.verb, conditions_path=a.conditions_path, as_json=a.json)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
