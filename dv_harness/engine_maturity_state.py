"""L5DGVA V14 (`L5DGVA/L5_DGVA_Generic_MultiLevel_Verification_Contract_v14_STRICT_AI_Architecture.md`,
sections 340-341) `Universal Engine Maturity State` -- read only, computed
entirely over `dv_harness/eight_engine_runtime_proof_matrix.py`'s own already-
real per-engine facts. Never re-derives evidence that module already owns.

MIGRATED (M5 Capability Pool Closure, Batch 2, from Parent) verbatim -- this
module is CAP-POOL-001's target capability. It hardcodes no event names of its
own (it reads only `EngineProofRow.verdict`/`defined`/`implemented`/`wired`/
`gap_note`/`evidence_refs`, already real facts computed by
`eight_engine_runtime_proof_matrix.py`, migrated in this same batch), so the
5-vs-8-signal adaptation made to that module needed no adaptation here: this
module's own logic and text are byte-for-byte unchanged.

PRIMARY SOURCE, quoted verbatim (section 340, lines 5001-5009 of that file):

    ## 340. Universal Engine Maturity State

    For every engine track: DEFINED -> IMPLEMENTED -> WIRED ->
    INVOKED_WHEN_APPLICABLE -> ARTIFACT_PRODUCED -> ARTIFACT_CONSUMED ->
    OUTCOME_VERIFIED -> REGRESSION_PROTECTED.

    Only the final state qualifies as runtime PASS.

    Required: `EightEngineMaturityModel_PASS = true`

Section 341 (lines 5011-5019, same file) is why a state is never assumed past
what real evidence supports: "Class/module/file/CLAUDE.md existence does not
prove runtime execution."

WHY THIS IS A SEPARATE MODULE FROM `eight_engine_runtime_proof_matrix.py`.
That module already implements section 342 (`EightEngineRuntimeProofMatrix`)
in full -- EngineId/Defined/Implemented/Wired/Trigger/Invoked/
InvocationEvidence/EvidenceRefs are real per-engine facts, and it already
discloses ArtifactIds/ConsumerIds/DecisionImpact/OutcomeVerified/
RegressionIds as `NOT_AVAILABLE` for every row (no producer links a proven
invocation to those five facts today). Section 340 is a DIFFERENT contract
requirement from section 342 -- a named 8-STATE LADDER per engine track, with
its own required flag `EightEngineMaturityModel_PASS` -- and nothing in this
repo computed it before this module (confirmed: a grep for
`EightEngineMaturityModel_PASS` or `Universal Engine Maturity State` across
`dv_harness/*.py` had zero hits prior to this file). This module is the
section-340 ladder, expressed strictly as a mapping FROM
`eight_engine_runtime_proof_matrix.build_matrix()`'s own fields -- it adds no
new event producer, no new reader, and no new evidence source of its own.

THE MAPPING (the entire logic here).

  * `EngineProofRow.defined`/`implemented`/`wired` are already `True` for all
    8 engines in the real matrix, each backed by a real module + cited
    call-site (`evidence_refs`) -- so every engine's floor is `WIRED`.
  * `verdict == PROVEN` (a real, named event matched in the scanned window)
    advances the state one step further, to `INVOKED_WHEN_APPLICABLE`.
  * `verdict == NOT_PROVEN` (a real producer exists but stayed silent this
    window) or `verdict == NO_RUNTIME_SIGNAL_SOURCE` (no producer exists at
    all) both cap the state at `WIRED` -- the reason differs (a per-run fact
    vs. a structural instrumentation gap) and is disclosed verbatim in
    `blocked_reason`/`blocked_kind`, never collapsed into one "not invoked".
  * The remaining four states -- `ARTIFACT_PRODUCED`, `ARTIFACT_CONSUMED`,
    `OUTCOME_VERIFIED`, `REGRESSION_PROTECTED` -- are NEVER reached by this
    module today, for any engine, because
    `eight_engine_runtime_proof_matrix.py` itself reports the four section-342
    columns those states would rest on (`ArtifactIds`, `ConsumerIds`,
    `OutcomeVerified`, `RegressionIds`) as `NOT_AVAILABLE` for every row. This
    module refuses to invent a producer/consumer/verification/regression
    trace those facts don't carry -- disclosed as `NOT_MEASURABLE` (the same
    "no producer for this fact exists in this codebase at all" token
    `subsystem_maturity_gate.py` already uses, reused here rather than
    re-minted) on every row, always.

`EightEngineMaturityModel_PASS` is therefore honestly `False` against real
evidence today for every engine in this repo -- exactly the finding the
2026-09-16 L5DGVA audit (`.dv-harness/l5dgva_audit_result_A.md`, cluster C11)
already flagged before this module existed ("the maturity-model concept that
would classify other engines is itself undefined-but-not-wired"). Defining it
does not manufacture a PASS; it turns an undefined claim into an honestly
computed FAIL with a named, per-engine reason -- which is the actual gap
closure this task scoped.

WHAT THIS MODULE DELIBERATELY DOES NOT DO.

  * It does not read `.dv-harness/events.jsonl` itself, add a new event
    producer, or re-implement any part of the section-342 matching logic --
    every fact used here is read straight off
    `eight_engine_runtime_proof_matrix.EngineProofRow`.
  * It does not guess a farther state from a nearby-but-different signal
    (e.g. a test file existing for an engine's own module is NOT treated as
    `REGRESSION_PROTECTED` -- that would be exactly the class/file-existence
    fallacy section 341 exists to forbid; a real regression trace tied to a
    specific proven invocation's outcome is what section 340 asks for, and no
    producer in this codebase links one today).
  * It authorizes nothing -- no promotion, gate, signoff or production write.
    It is a read-only classification over another read-only module's output.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import eight_engine_runtime_proof_matrix as eerpm

SCHEMA_VERSION = "1.0"

#: Section 340's own 8-state ladder, verbatim order.
STATE_DEFINED = "DEFINED"
STATE_IMPLEMENTED = "IMPLEMENTED"
STATE_WIRED = "WIRED"
STATE_INVOKED_WHEN_APPLICABLE = "INVOKED_WHEN_APPLICABLE"
STATE_ARTIFACT_PRODUCED = "ARTIFACT_PRODUCED"
STATE_ARTIFACT_CONSUMED = "ARTIFACT_CONSUMED"
STATE_OUTCOME_VERIFIED = "OUTCOME_VERIFIED"
STATE_REGRESSION_PROTECTED = "REGRESSION_PROTECTED"

MATURITY_STATE_LADDER: Tuple[str, ...] = (
    STATE_DEFINED, STATE_IMPLEMENTED, STATE_WIRED, STATE_INVOKED_WHEN_APPLICABLE,
    STATE_ARTIFACT_PRODUCED, STATE_ARTIFACT_CONSUMED, STATE_OUTCOME_VERIFIED,
    STATE_REGRESSION_PROTECTED,
)

#: Only the final rung is section 340's own runtime PASS.
FINAL_STATE = STATE_REGRESSION_PROTECTED

#: A row's own verdict, section-340 style ("Any applicable missing stage
#: yields PARTIAL/FAIL, never PASS.") -- FAIL is reserved for an engine that
#: is not even DEFINED/IMPLEMENTED/WIRED; none of the real 8 engines are, per
#: eight_engine_runtime_proof_matrix.py's own cited evidence, so FAIL is
#: declared but never observed against this repo today.
ROW_PASS = "PASS"
ROW_PARTIAL = "PARTIAL"
ROW_FAIL = "FAIL"

#: Distinct from `eight_engine_runtime_proof_matrix.NOT_AVAILABLE` on
#: purpose, reusing `subsystem_maturity_gate.py`'s own disambiguation:
#: `NOT_MEASURABLE` means no producer for this fact exists in this codebase
#: at all, not merely that this call's evidence bundle omitted it.
NOT_MEASURABLE = "NOT_MEASURABLE"

#: The four upper states this module can never reach today, and why -- one
#: message, since the reason is identical for all four (the same four
#: section-342 columns are NOT_AVAILABLE on every row of the real matrix).
UPPER_STATES_BLOCKED_REASON = (
    "eight_engine_runtime_proof_matrix.py reports ArtifactIds/ConsumerIds/"
    "OutcomeVerified/RegressionIds as NOT_AVAILABLE for every engine -- no "
    "producer in this codebase links a proven invocation to an artifact-"
    "produced/consumed, outcome-verified or regression-protected trace yet. "
    "ARTIFACT_PRODUCED, ARTIFACT_CONSUMED, OUTCOME_VERIFIED and "
    "REGRESSION_PROTECTED are therefore NOT_MEASURABLE, not UNMET -- there is "
    "nothing this module could read today to answer them honestly."
)


@dataclass
class EngineMaturityRow:
    engine_id: str
    engine_name: str
    module: str
    reached_state: str
    blocked_kind: str  # "" | "NOT_YET_OBSERVED" | "NOT_MEASURABLE"
    blocked_reason: str
    row_verdict: str
    upper_states_status: str  # always NOT_MEASURABLE today; see module docstring
    proof_matrix_verdict: str
    evidence_refs: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "EngineId": self.engine_id,
            "EngineName": self.engine_name,
            "Module": self.module,
            "ReachedState": self.reached_state,
            "BlockedKind": self.blocked_kind,
            "BlockedReason": self.blocked_reason,
            "RowVerdict": self.row_verdict,
            "UpperStatesStatus": self.upper_states_status,
            "ProofMatrixVerdict": self.proof_matrix_verdict,
            "EvidenceRefs": self.evidence_refs,
        }


def _row_state(row: "eerpm.EngineProofRow") -> Tuple[str, str, str]:
    """Return (reached_state, blocked_kind, blocked_reason) for one real
    EngineProofRow, per this module's own mapping (see docstring)."""
    if row.verdict == eerpm.PROVEN:
        return STATE_INVOKED_WHEN_APPLICABLE, "", ""
    if row.verdict == eerpm.NOT_PROVEN:
        return (STATE_WIRED, "NOT_YET_OBSERVED",
                "a real events.jsonl producer exists for this engine but no matching "
                "event appeared in the scanned window -- WIRED is proven, "
                "INVOKED_WHEN_APPLICABLE is not yet, for this run")
    if row.verdict == eerpm.NO_RUNTIME_SIGNAL_SOURCE:
        return (STATE_WIRED, "NOT_MEASURABLE",
                row.gap_note or
                "this engine has no events.jsonl producer at all today -- "
                "INVOKED_WHEN_APPLICABLE is structurally unmeasurable, not merely "
                "unobserved this run")
    # Defensive: eight_engine_runtime_proof_matrix.VERDICTS is a closed set;
    # an unrecognized verdict must read as a disclosed gap, never crash or
    # silently default to a state.
    return (STATE_WIRED, "NOT_MEASURABLE",
            f"unrecognized proof-matrix verdict {row.verdict!r}")


def derive_maturity_state(root: Path, *, run_id: Optional[str] = None,
                          scan_lines: int = eerpm.loop_telemetry.DEFAULT_EVENT_SCAN_LINES,
                          ) -> Dict[str, Any]:
    """Section 340's `EightEngineMaturityModel_PASS` and per-engine state,
    derived entirely from `eight_engine_runtime_proof_matrix.build_matrix()`'s
    real rows -- never a second read of events.jsonl."""
    root = Path(root)
    proof_rows = eerpm.build_matrix(root, run_id=run_id, scan_lines=scan_lines)

    rows: Dict[str, EngineMaturityRow] = {}
    for engine_id, prow in proof_rows.items():
        reached_state, blocked_kind, blocked_reason = _row_state(prow)
        row_verdict = ROW_PASS if reached_state == FINAL_STATE else (
            ROW_PARTIAL if prow.defined and prow.implemented and prow.wired else ROW_FAIL)
        rows[engine_id] = EngineMaturityRow(
            engine_id=engine_id, engine_name=prow.engine_name, module=prow.module,
            reached_state=reached_state, blocked_kind=blocked_kind,
            blocked_reason=blocked_reason, row_verdict=row_verdict,
            upper_states_status=NOT_MEASURABLE,
            proof_matrix_verdict=prow.verdict, evidence_refs=list(prow.evidence_refs),
        )

    all_final = bool(rows) and all(r.reached_state == FINAL_STATE for r in rows.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "run_id": run_id,
        "maturity_state_ladder": list(MATURITY_STATE_LADDER),
        "rows": {k: v.to_dict() for k, v in rows.items()},
        "EightEngineMaturityModel_PASS": all_final,
        "upper_states_blocked_reason": UPPER_STATES_BLOCKED_REASON,
        "authorizes": (
            "nothing. Read-only classification over "
            "eight_engine_runtime_proof_matrix.py's own real per-engine facts; "
            "approves no promotion, gate, signoff or production write."),
    }


def render_maturity_state_text(report: Dict[str, Any]) -> str:
    header = f"{'Engine':<32} | {'Reached State':<26} | {'Row Verdict':<8} | Blocked Reason"
    lines = [header, "-" * len(header)]
    for row in report["rows"].values():
        lines.append(f"{row['EngineName']:<32} | {row['ReachedState']:<26} | "
                     f"{row['RowVerdict']:<8} | {row['BlockedReason']}")
    lines.append("")
    lines.append(f"EightEngineMaturityModel_PASS = {report['EightEngineMaturityModel_PASS']}")
    return "\n".join(lines)


def execute_verb(root: Path, verb: str, *, run_id: Optional[str] = None) -> Tuple[int, Any]:
    """Same shared-`execute_verb()` convention
    `eight_engine_runtime_proof_matrix`/`loop_telemetry`/`loop_contract` already
    follow."""
    root = Path(root)
    if verb in ("state", "show"):
        report = derive_maturity_state(root, run_id=run_id)
        code = 0 if report["EightEngineMaturityModel_PASS"] else 2
        if verb == "show":
            return code, render_maturity_state_text(report)
        return code, report
    return 1, {"ok": False, "error": "UNKNOWN_VERB", "verb": verb, "known": ["state", "show"]}


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - CLI shim
    import argparse
    import json
    p = argparse.ArgumentParser(
        prog="python -m dv_harness.engine_maturity_state",
        description="L5DGVA V14 section 340's Universal Engine Maturity State, derived "
                    "entirely from eight_engine_runtime_proof_matrix.py's real per-engine facts.")
    p.add_argument("verb", choices=["state", "show"])
    p.add_argument("--project-root", default=".")
    p.add_argument("--run-id", default=None)
    args = p.parse_args(argv)
    code, payload = execute_verb(Path(args.project_root), args.verb, run_id=args.run_id)
    print(payload if isinstance(payload, str)
          else json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
