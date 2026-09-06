"""SYSTEM-LEVEL READINESS GATES: eight named composite gates over SYS-37's own
real evidence.

WHAT THIS MODULE IS NOT
------------------------
It derives no new fact about a composition. Every condition each gate checks is
read verbatim off `system_readiness.derive_system_readiness()`'s own ten real
SYS-37 inputs (`_shared_resource_input()`/`_command_compatibility_input()`/etc.,
already computed by that module from `system_resource_registry.py`,
`system_command_plan.py`, `system_scheduling_plan.py` and
`system_topology_analysis.py`), plus SYS-35's real `build_composition_version_pin()`
document and SYS-33's real regression plan -- all imported and called read-only,
never re-derived. This module runs no analysis of its own kind, submits nothing
and authorizes nothing: a READY verdict here is exactly as inert as SYS-37's own
READY verdict, an input to the SYS-39 human-approval gate, never a substitute for
it (`system_readiness.py`'s own module docstring, unchanged by this file).

WHY EIGHT NAMED GATES INSTEAD OF ONE COMPOSITE VERDICT
--------------------------------------------------------
`derive_system_readiness()` already folds all ten inputs into one
READY/PARTIAL/BLOCKED/UNKNOWN verdict, and that fold is right for "can this
composition be integrated at all". It is the wrong shape for "WHICH concern is
what is stopping it" -- a caller staring at one PARTIAL verdict over ten inputs
still has to go read the `inputs` list by hand to find the one input that is
CONCERN. Grouping SYS-37's ten inputs into eight named, domain-scoped gates
(subsystem selection, resource reconciliation, command compatibility, scoreboard
composition, build composition, regression planning, error handling, and the
final system-wide signoff conjunction) gives a caller eight independently
checkable questions instead of one undifferentiated blob, while changing not one
bit of what SYS-37 itself already computed.

THE SAME WORST-WINS, NO-AVERAGING DISCIPLINE THIS PROJECT ALREADY APPLIES
EVERYWHERE (`subsystem_maturity_gate.py`, `functional_coverage_signoff.py`,
`spec_vplan_readiness_gate.py`)
--------------------------------------------------------------------------
Every gate here is a real AND-formula over its own required conditions, folded
by `_fold()`:

  * A single condition that is BLOCKED or CONCERN (a real, evidenced problem --
    an unresolved conflict, a missing build script, zero cross-subsystem
    scenarios) makes the WHOLE gate NOT_READY, regardless of how many other
    conditions on that gate are clean. Two clean conditions and one blocked one
    is not "mostly ready" -- it is not ready, exactly as this project's other
    composite gates already insist.
  * A condition genuinely absent evidence for (no scheduling plan was supplied,
    no version pin exists because nothing was selected) is UNKNOWN, and -- when
    nothing worse is present on that gate -- makes the gate
    INCOMPLETE_EVIDENCE, a THIRD value distinct from both READY and NOT_READY.
    This is GF-AT-28 as a hard constraint on this module specifically: a
    Critical UNKNOWN must never silently become READY, and it must equally
    never be reported as a confirmed NOT_READY it was never proven to be.
  * Only when every required condition on a gate is CLEAR does that gate report
    READY.

`GATE_VERDICTS = (READY, NOT_READY, INCOMPLETE_EVIDENCE)` is a vocabulary
asserted, at import time, to share no token with `dv_harness.models.Status` --
the same guard several sibling composite-gate modules already apply to their
own domain vocabularies.

THE EIGHT GATES, AND WHICH SYS-37 INPUT(S) EACH ONE OWNS
----------------------------------------------------------
Every one of SYS-37's ten named inputs is read by exactly one of the first
seven gates (never invented, never re-derived); `SYSTEM_SIGNOFF_READY` is the
final AND across all seven plus SYS-37's own overall verdict.

  SUBSYSTEM_SELECTION_READY     -- a non-empty SYS-1 selection, all SYS-4 READY
                                    (`subsystem_readiness`).
  RESOURCE_RECONCILIATION_READY -- SYS-24 shared-resource scheduling clean, and
                                    SYS-11/12/17 VIP-dedup/ownership clean
                                    (`shared_resource_conflicts`,
                                    `vip_dedup_resolution`).
  COMMAND_COMPATIBILITY_READY   -- SYS-18..22 command-plan collisions/mode
                                    preservation clean (`command_compatibility`).
  SCOREBOARD_COMPOSITION_READY  -- SYS-26 scoreboard reuse clean AND the
                                    cross-subsystem topology facts a correlation
                                    layer needs (SYS-28 address map, SYS-29
                                    clock/reset) are themselves clean
                                    (`scoreboard_compatibility`, `address_map`,
                                    `clock_reset`).
  BUILD_COMPOSITION_READY       -- SYS-4's own per-subsystem build presence
                                    clean AND SYS-35's version pin is
                                    restorable (`build_integration`, plus a real
                                    check of `build_composition_version_pin()`'s
                                    own `restorable` field).
  REGRESSION_PLAN_READY         -- SYS-4's regression-evidence factor clean,
                                    SYS-30 cross-subsystem scenarios exist to
                                    regress, AND SYS-33's own plan really
                                    derived at least one entry
                                    (`regression_evidence`,
                                    `scenario_availability`, plus a real check
                                    of `build_system_regression_plan()`'s own
                                    `entry_count`).
  ERROR_HANDLING_READY          -- SYS-37's own closing rule made checkable:
                                    the VIP-dedup input (the one input whose
                                    BLOCKED status IS "an unresolved
                                    DRIVER_CONFLICT or a blocked dedup
                                    decision") is clean, AND no SYS-37 input at
                                    all is BLOCKED.
  SYSTEM_SIGNOFF_READY          -- every one of the above seven gates READY,
                                    AND SYS-37's own overall `system_readiness`
                                    verdict is READY.

This module authorizes nothing. As with SYS-37 itself, a READY verdict here
still stops at SYS-39 for a human.
"""

from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import system_readiness as sr
from .models import Status

# ===========================================================================
# Vocabulary -- reused from system_readiness.py, never re-typed
# ===========================================================================

#: SYS-37's own per-input status vocabulary (CLEAR/CONCERN/BLOCKED/UNKNOWN),
#: imported rather than redeclared -- every condition this module builds,
#: whether read straight off a SYS-37 input or synthesized from a SYS-35/SYS-33
#: real fact, is expressed in this same four-value vocabulary.
INPUT_CLEAR = sr.INPUT_CLEAR
INPUT_CONCERN = sr.INPUT_CONCERN
INPUT_BLOCKED = sr.INPUT_BLOCKED
INPUT_UNKNOWN = sr.INPUT_UNKNOWN
INPUT_STATUSES: tuple = sr.INPUT_STATUSES

#: This module's own gate-verdict vocabulary. Deliberately three values and
#: deliberately NOT any of SYS-37's four READY/PARTIAL/BLOCKED/UNKNOWN words --
#: a *gate* (an AND-formula over conditions) reports READY / NOT_READY /
#: INCOMPLETE_EVIDENCE, distinct from a *composition*'s own SYS-37 verdict.
GATE_READY = "READY"
GATE_NOT_READY = "NOT_READY"
GATE_INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"
GATE_VERDICTS: tuple = (GATE_READY, GATE_NOT_READY, GATE_INCOMPLETE_EVIDENCE)

#: How a sub-gate's own verdict folds into a condition on `SYSTEM_SIGNOFF_READY`.
GATE_VERDICT_TO_INPUT_STATUS: Dict[str, str] = {
    GATE_READY: INPUT_CLEAR,
    GATE_NOT_READY: INPUT_BLOCKED,
    GATE_INCOMPLETE_EVIDENCE: INPUT_UNKNOWN,
}

#: The eight named gates, in the order the module docstring describes them.
GATE_SUBSYSTEM_SELECTION_READY = "SUBSYSTEM_SELECTION_READY"
GATE_RESOURCE_RECONCILIATION_READY = "RESOURCE_RECONCILIATION_READY"
GATE_COMMAND_COMPATIBILITY_READY = "COMMAND_COMPATIBILITY_READY"
GATE_SCOREBOARD_COMPOSITION_READY = "SCOREBOARD_COMPOSITION_READY"
GATE_BUILD_COMPOSITION_READY = "BUILD_COMPOSITION_READY"
GATE_REGRESSION_PLAN_READY = "REGRESSION_PLAN_READY"
GATE_ERROR_HANDLING_READY = "ERROR_HANDLING_READY"
GATE_SYSTEM_SIGNOFF_READY = "SYSTEM_SIGNOFF_READY"

GATE_NAMES: tuple = (
    GATE_SUBSYSTEM_SELECTION_READY,
    GATE_RESOURCE_RECONCILIATION_READY,
    GATE_COMMAND_COMPATIBILITY_READY,
    GATE_SCOREBOARD_COMPOSITION_READY,
    GATE_BUILD_COMPOSITION_READY,
    GATE_REGRESSION_PLAN_READY,
    GATE_ERROR_HANDLING_READY,
    GATE_SYSTEM_SIGNOFF_READY,
)


class SystemReadinessGateError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


def _assert_gate_vocabulary_disjoint_from_status() -> None:
    """Import-time guard: this module's own three-value gate-verdict
    vocabulary must never collide with `dv_harness.models.Status` -- a real
    stage-gate PASS/FAIL/BLOCKED/... is a different kind of fact from one of
    these composite gates' own READY/NOT_READY/INCOMPLETE_EVIDENCE verdict, and
    conflating the two tokens would let a caller mistake one for the other."""
    collision = set(GATE_VERDICTS) & {member.value for member in Status}
    if collision:
        raise SystemReadinessGateError(
            "GATE_VERDICT_VOCABULARY_COLLIDES_WITH_STATUS",
            {"collision": sorted(collision)})


_assert_gate_vocabulary_disjoint_from_status()


# ===========================================================================
# Conditions -- each one a single real fact, expressed in SYS-37's own
# CLEAR/CONCERN/BLOCKED/UNKNOWN vocabulary
# ===========================================================================

def _condition(name: str, status: str, evidence: str, **detail) -> Dict[str, Any]:
    if status not in INPUT_STATUSES:
        raise SystemReadinessGateError(
            "UNKNOWN_CONDITION_STATUS", {"condition": name, "status": status})
    return {"condition": name, "status": status, "evidence": evidence, **detail}


def _input_condition(readiness: Mapping[str, Any], input_name: str) -> Dict[str, Any]:
    """Read one of SYS-37's own ten real inputs verbatim off
    `derive_system_readiness()`'s result -- never re-derived. A readiness
    document that somehow lacks the named input (e.g. a caller handed this
    module a partial/hand-built document rather than a real one) is honestly
    UNKNOWN rather than silently assumed clean."""
    by_name = {row.get("input"): row for row in (readiness.get("inputs") or [])}
    row = by_name.get(input_name)
    if row is None:
        return _condition(
            input_name, INPUT_UNKNOWN,
            f"SYS-37 input '{input_name}' is absent from the supplied readiness document")
    return _condition(row["input"], row["status"], row.get("evidence", ""))


def _selection_nonempty_condition(selection: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = list((selection or {}).get("selected_rows") or [])
    if not rows:
        return _condition("selection_nonempty", INPUT_UNKNOWN, "no subsystem was selected")
    return _condition(
        "selection_nonempty", INPUT_CLEAR,
        f"{len(rows)} subsystem(s) selected: {[r.get('subsystem') for r in rows]}")


def _version_pin_restorable_condition(version_pin: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """SYS-35's own `restorable` field, read verbatim -- never recomputed."""
    pin = dict(version_pin or {})
    subsystems = list(pin.get("subsystems") or [])
    if not subsystems:
        return _condition(
            "version_pin_restorable", INPUT_UNKNOWN,
            "no SYS-35 version pin was supplied, or it pins no subsystem")
    if pin.get("restorable"):
        return _condition(
            "version_pin_restorable", INPUT_CLEAR,
            f"composition {pin.get('composition_id')} is restorable: every selected "
            "subsystem is pinned to a registered release_sha")
    unpinned = list(pin.get("unpinned_subsystems") or [])
    return _condition(
        "version_pin_restorable", INPUT_BLOCKED,
        f"{unpinned} carr(y/ies) no registered release_sha; this composition is not "
        "restorable", unpinned_subsystems=unpinned)


def _regression_plan_populated_condition(
        regression_plan: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """SYS-33's own `entry_count`, read verbatim -- never recomputed."""
    if regression_plan is None:
        return _condition(
            "regression_plan_populated", INPUT_UNKNOWN,
            "no SYS-33 regression plan was supplied")
    entry_count = (regression_plan.get("summary") or {}).get("entry_count")
    if entry_count is None:
        return _condition(
            "regression_plan_populated", INPUT_UNKNOWN,
            "the supplied SYS-33 regression plan carries no entry_count summary field")
    if entry_count:
        return _condition(
            "regression_plan_populated", INPUT_CLEAR,
            f"SYS-33 regression plan derived {entry_count} entr(y/ies)")
    return _condition(
        "regression_plan_populated", INPUT_CONCERN,
        "SYS-33 regression plan derived zero entries")


def _no_blocked_sys37_input_condition(readiness: Mapping[str, Any]) -> Dict[str, Any]:
    """Cross-cuts all ten SYS-37 inputs at once: is there ANY input this
    composition's own readiness document already found BLOCKED. When every
    single input is UNKNOWN (nothing could be evidenced at all) this reports
    UNKNOWN rather than CLEAR -- "we have no evidence of a blocking problem"
    is not the same claim as "we checked and there is none"."""
    by_status = readiness.get("by_status") or {}
    blocked = list(by_status.get(INPUT_BLOCKED) or [])
    if blocked:
        return _condition(
            "no_sys37_input_blocked", INPUT_BLOCKED,
            f"SYS-37 input(s) BLOCKED: {blocked}", blocked_inputs=blocked)
    total_inputs = len(readiness.get("inputs") or [])
    unknown = list(by_status.get(INPUT_UNKNOWN) or [])
    if total_inputs and len(unknown) == total_inputs:
        return _condition(
            "no_sys37_input_blocked", INPUT_UNKNOWN,
            "no SYS-37 input could be evidenced at all, so whether any is blocked "
            "cannot be confirmed")
    return _condition("no_sys37_input_blocked", INPUT_CLEAR, "no SYS-37 input is BLOCKED")


def _overall_sys37_readiness_condition(readiness: Mapping[str, Any]) -> Dict[str, Any]:
    """SYS-37's own single fold-of-ten-inputs verdict, read verbatim, folded
    into a condition on the final SYSTEM_SIGNOFF_READY gate."""
    verdict = readiness.get("system_readiness")
    evidence = readiness.get("evidence", "")
    if verdict == sr.READY:
        return _condition("sys37_overall_readiness", INPUT_CLEAR,
                          f"SYS-37 overall system_readiness={verdict}: {evidence}")
    if verdict == sr.BLOCKED:
        return _condition("sys37_overall_readiness", INPUT_BLOCKED,
                          f"SYS-37 overall system_readiness={verdict}: {evidence}")
    if verdict == sr.UNKNOWN:
        return _condition("sys37_overall_readiness", INPUT_UNKNOWN,
                          f"SYS-37 overall system_readiness={verdict}: {evidence}")
    # PARTIAL, or any value this module has never seen -- a real, unresolved
    # concern, never silently rounded up to CLEAR.
    return _condition("sys37_overall_readiness", INPUT_CONCERN,
                      f"SYS-37 overall system_readiness={verdict}: {evidence}")


# ===========================================================================
# The worst-wins fold
# ===========================================================================

def _fold(conditions: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """One gate's real AND-formula. Mirrors the exact precedence
    `system_readiness.derive_system_readiness()` already applies one level
    down, and the same discipline `subsystem_maturity_gate.py`/
    `functional_coverage_signoff.py`/`spec_vplan_readiness_gate.py` apply to
    their own composite verdicts:

      NOT_READY            any condition BLOCKED or CONCERN -- a single
                            unmet/unresolved condition blocks the gate
                            regardless of how many others are CLEAR.
      INCOMPLETE_EVIDENCE   no BLOCKED/CONCERN condition, but at least one
                            condition is UNKNOWN -- insufficient evidence to
                            call this gate READY, and not the same claim as a
                            confirmed NOT_READY either.
      READY                 every required condition is CLEAR. Nothing less.
    """
    by_status = {s: [c["condition"] for c in conditions if c["status"] == s]
                 for s in INPUT_STATUSES}
    if by_status[INPUT_BLOCKED] or by_status[INPUT_CONCERN]:
        verdict = GATE_NOT_READY
        why = "unmet condition(s): " + "; ".join(
            f"{c['condition']}={c['status']}: {c['evidence']}" for c in conditions
            if c["status"] in (INPUT_BLOCKED, INPUT_CONCERN))
    elif by_status[INPUT_UNKNOWN]:
        verdict = GATE_INCOMPLETE_EVIDENCE
        why = "insufficient evidence: " + "; ".join(
            f"{c['condition']}: {c['evidence']}" for c in conditions
            if c["status"] == INPUT_UNKNOWN)
    else:
        verdict = GATE_READY
        why = f"all {len(conditions)} required condition(s) are CLEAR"
    return {
        "verdict": verdict,
        "evidence": why,
        "conditions": list(conditions),
        "by_status": by_status,
    }


# ===========================================================================
# The eight named gates
# ===========================================================================

def _subsystem_selection_ready(readiness: Mapping[str, Any],
                               selection: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    conditions = [
        _selection_nonempty_condition(selection),
        _input_condition(readiness, sr.IN_SUBSYSTEM_READINESS),
    ]
    return _fold(conditions)


def _resource_reconciliation_ready(readiness: Mapping[str, Any]) -> Dict[str, Any]:
    conditions = [
        _input_condition(readiness, sr.IN_SHARED_RESOURCE_CONFLICTS),
        _input_condition(readiness, sr.IN_VIP_DEDUP_RESOLUTION),
    ]
    return _fold(conditions)


def _command_compatibility_ready(readiness: Mapping[str, Any]) -> Dict[str, Any]:
    conditions = [_input_condition(readiness, sr.IN_COMMAND_COMPATIBILITY)]
    return _fold(conditions)


def _scoreboard_composition_ready(readiness: Mapping[str, Any]) -> Dict[str, Any]:
    conditions = [
        _input_condition(readiness, sr.IN_SCOREBOARD_COMPATIBILITY),
        _input_condition(readiness, sr.IN_ADDRESS_MAP),
        _input_condition(readiness, sr.IN_CLOCK_RESET),
    ]
    return _fold(conditions)


def _build_composition_ready(readiness: Mapping[str, Any],
                             version_pin: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    conditions = [
        _input_condition(readiness, sr.IN_BUILD_INTEGRATION),
        _version_pin_restorable_condition(version_pin),
    ]
    return _fold(conditions)


def _regression_plan_ready(readiness: Mapping[str, Any],
                           regression_plan: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    conditions = [
        _input_condition(readiness, sr.IN_REGRESSION_EVIDENCE),
        _input_condition(readiness, sr.IN_SCENARIO_AVAILABILITY),
        _regression_plan_populated_condition(regression_plan),
    ]
    return _fold(conditions)


def _error_handling_ready(readiness: Mapping[str, Any]) -> Dict[str, Any]:
    conditions = [
        _input_condition(readiness, sr.IN_VIP_DEDUP_RESOLUTION),
        _no_blocked_sys37_input_condition(readiness),
    ]
    return _fold(conditions)


def _system_signoff_ready(gate_reports: Mapping[str, Mapping[str, Any]],
                          readiness: Mapping[str, Any]) -> Dict[str, Any]:
    conditions = []
    for name in GATE_NAMES:
        if name == GATE_SYSTEM_SIGNOFF_READY:
            continue
        report = gate_reports[name]
        status = GATE_VERDICT_TO_INPUT_STATUS.get(report["verdict"], INPUT_UNKNOWN)
        conditions.append(_condition(
            name, status, f"{name}={report['verdict']}: {report['evidence']}"))
    conditions.append(_overall_sys37_readiness_condition(readiness))
    return _fold(conditions)


# ===========================================================================
# Front door
# ===========================================================================

def derive_system_readiness_gates(readiness: Mapping[str, Any], *,
                                  selection: Optional[Mapping[str, Any]] = None,
                                  version_pin: Optional[Mapping[str, Any]] = None,
                                  regression_plan: Optional[Mapping[str, Any]] = None,
                                  ) -> Dict[str, Any]:
    """The eight named composite gates over SYS-37's real evidence.

    `readiness` must be the real dict `system_readiness.derive_system_readiness()`
    returns. `selection`/`version_pin`/`regression_plan` are the matching real
    SYS-1/SYS-35/SYS-33 documents when a caller has them; each is optional and
    its absence is reported as an honest UNKNOWN condition on the gate(s) that
    need it, never assumed clean.

    Nothing here re-runs any SYS-* analysis, writes any file, or authorizes
    anything -- see the module docstring.
    """
    if not isinstance(readiness, Mapping) or "inputs" not in readiness:
        raise SystemReadinessGateError(
            "NOT_A_SYS37_READINESS_DOCUMENT", {"got": type(readiness).__name__})

    reports: Dict[str, Any] = {}
    reports[GATE_SUBSYSTEM_SELECTION_READY] = _subsystem_selection_ready(readiness, selection)
    reports[GATE_RESOURCE_RECONCILIATION_READY] = _resource_reconciliation_ready(readiness)
    reports[GATE_COMMAND_COMPATIBILITY_READY] = _command_compatibility_ready(readiness)
    reports[GATE_SCOREBOARD_COMPOSITION_READY] = _scoreboard_composition_ready(readiness)
    reports[GATE_BUILD_COMPOSITION_READY] = _build_composition_ready(readiness, version_pin)
    reports[GATE_REGRESSION_PLAN_READY] = _regression_plan_ready(readiness, regression_plan)
    reports[GATE_ERROR_HANDLING_READY] = _error_handling_ready(readiness)
    reports[GATE_SYSTEM_SIGNOFF_READY] = _system_signoff_ready(reports, readiness)

    by_verdict = {v: [n for n in GATE_NAMES if reports[n]["verdict"] == v]
                  for v in GATE_VERDICTS}
    return {
        "gates": reports,
        "gate_names": list(GATE_NAMES),
        "by_verdict": by_verdict,
        "authorizes": "NOTHING -- SYS-39 stops for explicit user approval regardless of "
                      "this verdict, exactly as SYS-37's own verdict does",
        "summary": {
            "system_signoff_ready": reports[GATE_SYSTEM_SIGNOFF_READY]["verdict"] == GATE_READY,
            "gates_ready": len(by_verdict[GATE_READY]),
            "gates_not_ready": len(by_verdict[GATE_NOT_READY]),
            "gates_incomplete_evidence": len(by_verdict[GATE_INCOMPLETE_EVIDENCE]),
            "gates_total": len(GATE_NAMES),
        },
    }


def derive_system_readiness_gates_from_assessment(
        assessment: Mapping[str, Any]) -> Dict[str, Any]:
    """Convenience front door over `system_readiness.assess_system_readiness()`'s
    own result bundle: unpacks the real `selection`/`version_pin`/
    `regression_plan`/`system_readiness` documents it already assembled and
    calls `derive_system_readiness_gates()` read-only. Never re-runs any SYS-*
    analysis of its own."""
    return derive_system_readiness_gates(
        assessment["system_readiness"],
        selection=assessment.get("selection"),
        version_pin=assessment.get("version_pin"),
        regression_plan=assessment.get("regression_plan"),
    )


# ===========================================================================
# Reporting
# ===========================================================================

def render_system_readiness_gates_table(gates_result: Mapping[str, Any]) -> str:
    header = "| Gate | Verdict | Evidence |"
    lines = [header, "|---|---|---|"]
    reports = gates_result.get("gates") or {}
    for name in gates_result.get("gate_names") or GATE_NAMES:
        report = reports.get(name) or {}
        evidence = str(report.get("evidence", "")).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {name} | {report.get('verdict', '')} | {evidence} |")
    return "\n".join(lines)


def format_system_readiness_gates_report(gates_result: Mapping[str, Any]) -> str:
    summary = gates_result.get("summary") or {}
    out = [
        "# SYSTEM READINESS GATES (composite AND-formulas over SYS-37/35/33 evidence)",
        "",
        f"{summary.get('gates_ready', 0)} ready / "
        f"{summary.get('gates_not_ready', 0)} not ready / "
        f"{summary.get('gates_incomplete_evidence', 0)} incomplete evidence, "
        f"of {summary.get('gates_total', 0)} gates.",
        "",
        render_system_readiness_gates_table(gates_result),
        "",
        f"SYSTEM_SIGNOFF_READY = {summary.get('system_signoff_ready')}.",
        "",
        f"This verdict authorizes: {gates_result.get('authorizes', '')}",
    ]
    return "\n".join(out)


def _assert_eight_named_gates() -> None:
    """Import-time check that this module still defines exactly eight named
    gates -- the same defensive pattern `system_readiness.py`'s own
    `_assert_input_set_matches_the_requirement()` uses for its ten inputs."""
    if len(GATE_NAMES) != 8 or len(set(GATE_NAMES)) != 8:
        raise SystemReadinessGateError(
            "GATE_NAME_SET_CHANGED", {"gates": list(GATE_NAMES), "expected_count": 8})


_assert_eight_named_gates()
