"""Plan-Quality Feedback: cross-run stage-sequencing efficiency (2026-09-07).

WHAT WAS CONFIRMED MISSING BEFORE THIS WAS WRITTEN. A repo-wide grep for
`plan_quality`/`stage_sequenc`/`traversal` returned nothing executable. Two
real, adjacent mechanisms already answer NEARBY questions and neither answers
this one:

  * `loop_telemetry.py` (section 107/108) already folds one loop SESSION's own
    section-108 events into a real `LoopSession` -- state, iteration count,
    plateau/oscillation verdict, retry ledger, terminal outcome. It reports one
    session at a time; nothing groups SEVERAL sessions by the SHAPE of the
    graph path they took.
  * `loop_convergence.py` (sections 88-90) classifies a project-wide COVERAGE
    series and, separately, whether a project's `debug_loop_history`/regression
    history shows the loop undoing its own work. Both are PROJECT-wide signals
    across the whole evidence store; neither is grouped by which stages a
    SPECIFIC run actually visited, in what order.

Neither module asks "does THIS graph traversal shape -- INTAKE ->
ARCH_DISCOVERY -> PROJECT_MODEL -> FAILURE_RECOVERY -> PROJECT_MODEL -> ... --
tend to converge quickly across the runs that took it, or does it thrash".
This module is that missing cross-session rollup, and it derives nothing new:
every fact it groups is `loop_telemetry.read_loop_telemetry()`'s own real,
already-persisted per-session record (which itself already carries
`loop_convergence`'s own per-session plateau/oscillation verdict, folded in by
`engine._classify_loop_convergence_for_telemetry()` at retry-exhaustion -- see
CLAUDE.md's "Loop Telemetry Events + the GUI Loop Engineering Center" section).
Reading `loop_telemetry.read_loop_telemetry()` therefore already aggregates
BOTH modules' signals; this module's own job is exactly the GROUPING BY SHAPE
that neither performs.

DISTINCT FROM TWO OTHER REAL MECHANISMS, ON PURPOSE
-----------------------------------------------------
  * `capability_evolution.repeated_unresolved_failure_patterns()` answers "has
    the SAME FAILURE SIGNATURE recurred across independent runs with no
    gate-verified fix" -- a CAPABILITY-level question (does this harness need a
    new guard), keyed on failure content. This module never reads Job Memory,
    never files a capability candidate, and is keyed on the GRAPH PATH a run
    took, not on what failed along it.
  * Any per-profile/per-tier track record (`confidence_calibration.py`'s
    confidence-tier reliability, `checker_sb_qualification.py`'s
    checker/scoreboard trust record) scores a NAMED AGENT/CONFIDENCE-TIER/
    CHECKER's own history. This module scores neither an agent nor a tier --
    it scores a SEQUENCING SHAPE, and never reads an agent profile.

WHAT IT REUSES RATHER THAN REBUILDS
-------------------------------------
  * every per-session fact -- state, iteration count, plateau, oscillation,
    terminal_event, retry_backoff -- is `loop_telemetry.read_loop_telemetry()`'s
    own real return value, read once per project;
  * the "2 independent observations before a claim is trustworthy" floor is
    `loop_contract.DEFAULT_OSCILLATION_REPEAT_THRESHOLD`, imported, the same
    bar `loop_convergence.DEFAULT_PLATEAU_WINDOW`,
    `capability_evolution.REPEAT_FAILURE_MIN_OCCURRENCES` and
    `memory_router.ORGANIZATIONAL_MIN_CONFIRMATIONS` already use;
  * the OSCILLATING/PLATEAU/REGRESSION verdict tokens compared against a
    session's own `plateau`/`oscillation` fields are `loop_convergence`'s own
    constants, imported, never re-spelled;
  * rendering reuses `connectivity.render_markdown_table()`, this repo's one
    parameterized table renderer.

WHAT THIS MODULE DOES NOT DO
-------------------------------
  * It writes nothing. `aggregate_stage_sequence_shapes()` reads
    `.dv-harness/events.jsonl` through `loop_telemetry.read_loop_telemetry()`
    and nothing else; no state, blackboard, approval or memory record is ever
    touched, and no `engine.py`/graph file is read or edited by this item.
  * It mints no verdict and touches no gate. `ControlPlane.approve()`,
    `policy.can_signoff()`, `HumanApprovalRequiredError` and
    `ProductionWriteNotAuthorizedError` are untouched and unreferenced.
  * It never files a capability-evolution candidate, a question, or a memory
    record. A THRASHING shape is reported, not escalated -- acting on it is a
    human/agent decision this module does not make.
  * It never invents a shape. A project whose loops have never emitted a
    section-108 event reports the honest `NOT_AVAILABLE` `loop_telemetry`
    already names, never a fabricated empty-but-clean matrix.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .loop_contract import DEFAULT_OSCILLATION_REPEAT_THRESHOLD
from .loop_convergence import OSCILLATING as CONV_OSCILLATING
from .loop_convergence import PLATEAU as CONV_PLATEAU
from .loop_convergence import REGRESSION as CONV_REGRESSION

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------
STATUS_EFFICIENT = "EFFICIENT"
STATUS_MIXED = "MIXED"
STATUS_THRASHING = "THRASHING"
STATUS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

#: This module's own four-way shape verdict. Checked disjoint from
#: `models.Status`'s real stage-verdict vocabulary at import time.
SHAPE_QUALITY_STATUSES = (STATUS_EFFICIENT, STATUS_MIXED, STATUS_THRASHING,
                          STATUS_INSUFFICIENT_DATA)

#: Reported when `loop_telemetry.read_loop_telemetry()` itself has nothing.
REPORT_NOT_AVAILABLE = "NOT_AVAILABLE"

#: The same "2 independent observations" bar this whole project already uses
#: before treating a repeated pattern as real evidence rather than a fluke --
#: `loop_contract.DEFAULT_OSCILLATION_REPEAT_THRESHOLD`, reused, not re-typed.
SHAPE_MIN_OCCURRENCES_FOR_SCORE = DEFAULT_OSCILLATION_REPEAT_THRESHOLD

#: A shape whose average retries consume more than this fraction of its own
#: total dispatches is THRASHING on retry volume alone, even absent a real
#: confirmed oscillation fingerprint: a shape spending more than half its own
#: iterations re-attempting a stage it has not yet cleared is not converging
#: efficiently by any reasonable reading of "efficient".
RETRY_RATIO_THRASHING_THRESHOLD = 0.5


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's own status tokens must share no token with
    `dv_harness.models.Status` -- the same guard several sibling
    domain-vocabulary modules in this project already run against themselves."""
    from .models import Status
    verdicts = {s.value for s in Status}
    collide = sorted(set(SHAPE_QUALITY_STATUSES) & verdicts)
    if collide:
        raise AssertionError(
            f"plan_quality_feedback vocabulary collides with models.Status: {collide}")


# --------------------------------------------------------------------------
# Per-session extraction: the ordered stage sequence a real session visited
# --------------------------------------------------------------------------
def iteration_stage_sequence(session_detail: Dict[str, Any]) -> List[str]:
    """One `str` per `LOOP_ITERATION_STARTED` row in this session's own
    `iteration_history` -- `loop_telemetry.read_loop_telemetry()["sessions"]
    [run_id]["iteration_history"]`, unchanged.

    `engine._emit_loop_iteration_started()` fires exactly once per outer
    `loop()` `while True` dispatch -- one entry per real attempt at a stage,
    including intra-stage retries -- so this is the real, ordered, per-attempt
    stage list the session actually produced, never re-derived from
    `state.json`'s own (mutable, overwritten-in-place) `attempts` counter."""
    out: List[str] = []
    for row in session_detail.get("iteration_history") or []:
        if row.get("event") == "LOOP_ITERATION_STARTED" and row.get("stage"):
            out.append(str(row["stage"]))
    return out


def stage_sequence_shape(stage_sequence: List[str]) -> Tuple[str, ...]:
    """The graph TRAVERSAL PATH this module scores: the ordered sequence of
    DISTINCT stage nodes visited, collapsing only IMMEDIATELY-consecutive
    repeats (an intra-stage retry stays one hop in the path).

    A LATER re-visit of an already-left stage -- a real FAIL-edge loop-back,
    e.g. `PROJECT_MODEL -> FAILURE_RECOVERY -> PROJECT_MODEL` -- is NOT
    collapsed: it is a real, separate hop the graph's own edges produced, and
    is exactly the kind of shape this module exists to distinguish from a
    clean, no-loop-back traversal of the same nodes."""
    out: List[str] = []
    for s in stage_sequence:
        if not out or out[-1] != s:
            out.append(s)
    return tuple(out)


def retry_count(stage_sequence: List[str]) -> int:
    """How many of this session's real dispatches were an immediate re-attempt
    of the SAME stage the previous dispatch just left -- the difference
    between the raw per-attempt sequence and its shape-collapsed form."""
    return len(stage_sequence) - len(stage_sequence_shape(stage_sequence))


# --------------------------------------------------------------------------
# Per-shape aggregate
# --------------------------------------------------------------------------
@dataclass
class ShapeQualityRecord:
    """One traversal shape's aggregate across every real session that took it."""
    shape: Tuple[str, ...] = ()
    occurrences: int = 0
    run_ids: List[str] = field(default_factory=list)
    total_iterations: List[int] = field(default_factory=list)
    total_retries: List[int] = field(default_factory=list)
    oscillating_run_ids: List[str] = field(default_factory=list)
    plateau_run_ids: List[str] = field(default_factory=list)
    regression_run_ids: List[str] = field(default_factory=list)
    terminal_outcomes: Dict[str, int] = field(default_factory=dict)
    avg_iterations: Optional[float] = None
    avg_retries: Optional[float] = None
    retry_ratio: Optional[float] = None
    oscillation_rate: float = 0.0
    plateau_rate: float = 0.0
    success_rate: Optional[float] = None
    status: str = STATUS_INSUFFICIENT_DATA
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["shape"] = list(self.shape)
        return d


def classify_shape_quality(rec: ShapeQualityRecord, *,
                           min_occurrences: int = SHAPE_MIN_OCCURRENCES_FOR_SCORE,
                           retry_ratio_thrashing_threshold: float =
                           RETRY_RATIO_THRASHING_THRESHOLD) -> Tuple[str, str]:
    """Worst-wins over the real signals a shape's own occurrences carry.

    Precedence, most severe first, exactly the "an averaged fold must never
    hide a genuine problem in one facet" rule this project applies everywhere:

      1. **INSUFFICIENT_DATA** -- fewer than `min_occurrences` independent
         sessions took this shape. A claim about one run is not a track
         record.
      2. **THRASHING** -- a real confirmed oscillation
         (`loop_convergence.OSCILLATING`) or a real recorded REGRESSION on ANY
         session of this shape (worst-wins: one real oscillation among clean
         siblings is still real evidence this shape thrashes), OR the average
         retry ratio across all occurrences meets
         `retry_ratio_thrashing_threshold`.
      3. **MIXED** -- some real inefficiency (a real PLATEAU verdict on at
         least one occurrence, or any retries at all) but nothing that clears
         THRASHING's own bar.
      4. **EFFICIENT** -- every occurrence converged with no oscillation, no
         plateau, no retries.
    """
    if rec.occurrences < min_occurrences:
        return STATUS_INSUFFICIENT_DATA, (
            f"only {rec.occurrences} independent session(s) recorded this shape; "
            f"{min_occurrences} are needed before its efficiency can be judged")

    if rec.oscillating_run_ids:
        return STATUS_THRASHING, (
            f"{len(rec.oscillating_run_ids)} of {rec.occurrences} session(s) on this "
            f"shape recorded a real {CONV_OSCILLATING} verdict -- the loop undid its "
            f"own work on this path")
    if rec.regression_run_ids:
        return STATUS_THRASHING, (
            f"{len(rec.regression_run_ids)} of {rec.occurrences} session(s) on this "
            f"shape recorded a real {CONV_REGRESSION} verdict -- the progress metric "
            f"declined on this path")
    if (rec.retry_ratio or 0.0) >= retry_ratio_thrashing_threshold:
        return STATUS_THRASHING, (
            f"average retry ratio {rec.retry_ratio:.2f} across {rec.occurrences} "
            f"session(s) meets the {retry_ratio_thrashing_threshold:.2f} thrashing "
            f"threshold -- more than half of this shape's own dispatches were retries")

    if rec.plateau_run_ids or (rec.avg_retries or 0.0) > 0:
        bits = []
        if rec.plateau_run_ids:
            bits.append(f"{len(rec.plateau_run_ids)} session(s) recorded a real "
                        f"{CONV_PLATEAU} verdict")
        if (rec.avg_retries or 0.0) > 0:
            bits.append(f"average {rec.avg_retries:.2f} retries per session")
        return STATUS_MIXED, "; ".join(bits) + " -- real but non-critical inefficiency"

    return STATUS_EFFICIENT, (
        f"all {rec.occurrences} session(s) on this shape converged with no oscillation, "
        f"no plateau and no retries")


# --------------------------------------------------------------------------
# The whole-project report
# --------------------------------------------------------------------------
@dataclass
class PlanQualityReport:
    root: str
    available: bool
    reason: str = ""
    sessions_examined: int = 0
    sessions_with_no_shape: int = 0
    shapes: List[Dict[str, Any]] = field(default_factory=list)
    status_counts: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def aggregate_stage_sequence_shapes(root, *,
                                    run_id: Optional[str] = None,
                                    scan_lines: Optional[int] = None,
                                    min_occurrences: int = SHAPE_MIN_OCCURRENCES_FOR_SCORE,
                                    retry_ratio_thrashing_threshold: float =
                                    RETRY_RATIO_THRASHING_THRESHOLD,
                                    telemetry: Optional[Dict[str, Any]] = None
                                    ) -> PlanQualityReport:
    """Section-108/107 telemetry, grouped by the traversal SHAPE each real
    session took, and scored.

    `telemetry` lets a caller (or a test) hand in an already-computed
    `loop_telemetry.read_loop_telemetry()` payload; omitted, this function
    reads it fresh via the real, read-only `loop_telemetry` module -- no
    `state.json`, no `StateStore.load()`, no other file is opened."""
    root = Path(root)
    if telemetry is None:
        from . import loop_telemetry as lt
        kwargs: Dict[str, Any] = {"run_id": run_id}
        if scan_lines is not None:
            kwargs["scan_lines"] = scan_lines
        telemetry = lt.read_loop_telemetry(root, **kwargs)

    if not telemetry.get("available"):
        return PlanQualityReport(
            root=str(root), available=False,
            reason=telemetry.get("reason") or REPORT_NOT_AVAILABLE)

    sessions = telemetry.get("sessions") or {}
    rows = telemetry.get("rows") or []

    groups: Dict[Tuple[str, ...], ShapeQualityRecord] = {}
    sessions_with_no_shape = 0

    for row in rows:
        rid = row.get("run_id")
        detail = sessions.get(rid) or {}
        sequence = iteration_stage_sequence(detail)
        if not sequence:
            sessions_with_no_shape += 1
            continue
        shape = stage_sequence_shape(sequence)
        rec = groups.setdefault(shape, ShapeQualityRecord(shape=shape))
        rec.occurrences += 1
        rec.run_ids.append(str(rid))
        rec.total_iterations.append(len(sequence))
        rec.total_retries.append(retry_count(sequence))

        plateau = row.get("plateau")
        oscillation = row.get("oscillation")
        if oscillation == CONV_OSCILLATING:
            rec.oscillating_run_ids.append(str(rid))
        if plateau == CONV_PLATEAU:
            rec.plateau_run_ids.append(str(rid))
        if plateau == CONV_REGRESSION:
            rec.regression_run_ids.append(str(rid))

        terminal = row.get("terminal_event")
        key = terminal or "(not terminal)"
        rec.terminal_outcomes[key] = rec.terminal_outcomes.get(key, 0) + 1

    status_counts: Dict[str, int] = {s: 0 for s in SHAPE_QUALITY_STATUSES}
    out_shapes: List[Dict[str, Any]] = []
    for shape, rec in groups.items():
        n = rec.occurrences
        rec.avg_iterations = round(sum(rec.total_iterations) / n, 3)
        rec.avg_retries = round(sum(rec.total_retries) / n, 3)
        rec.retry_ratio = (round(rec.avg_retries / rec.avg_iterations, 4)
                           if rec.avg_iterations else 0.0)
        rec.oscillation_rate = round(len(rec.oscillating_run_ids) / n, 4)
        rec.plateau_rate = round(len(rec.plateau_run_ids) / n, 4)
        terminal_total = sum(v for k, v in rec.terminal_outcomes.items()
                             if k != "(not terminal)")
        success_total = rec.terminal_outcomes.get("LOOP_SUCCESS", 0)
        rec.success_rate = (round(success_total / terminal_total, 4)
                            if terminal_total else None)
        rec.status, rec.reason = classify_shape_quality(
            rec, min_occurrences=min_occurrences,
            retry_ratio_thrashing_threshold=retry_ratio_thrashing_threshold)
        status_counts[rec.status] = status_counts.get(rec.status, 0) + 1
        out_shapes.append(rec.to_dict())

    out_shapes.sort(key=lambda d: (-d["occurrences"], d["avg_iterations"] or 0.0,
                                   tuple(d["shape"])))

    return PlanQualityReport(
        root=str(root), available=True,
        sessions_examined=len(rows),
        sessions_with_no_shape=sessions_with_no_shape,
        shapes=out_shapes,
        status_counts=status_counts,
    )


# --------------------------------------------------------------------------
# Rendering + front door
# --------------------------------------------------------------------------
def render_report_text(payload: Dict[str, Any]) -> str:
    if not payload.get("available"):
        return f"(no plan-quality feedback) {payload.get('reason', '')}"
    from .connectivity import render_markdown_table

    lines = [
        f"Plan-Quality Feedback ({payload.get('root')})",
        f"sessions examined: {payload.get('sessions_examined')}  "
        f"(no-shape: {payload.get('sessions_with_no_shape')})",
        f"status counts: {payload.get('status_counts')}",
        "",
    ]
    rows = []
    for s in payload.get("shapes") or []:
        rows.append({
            "shape": " -> ".join(s.get("shape") or []),
            "status": s.get("status"),
            "occurrences": s.get("occurrences"),
            "avg_iterations": s.get("avg_iterations"),
            "avg_retries": s.get("avg_retries"),
            "retry_ratio": s.get("retry_ratio"),
            "oscillation_rate": s.get("oscillation_rate"),
            "success_rate": s.get("success_rate"),
        })
    lines.append(render_markdown_table(
        [("shape", "Shape"), ("status", "Status"), ("occurrences", "N"),
         ("avg_iterations", "Avg Iter"), ("avg_retries", "Avg Retries"),
         ("retry_ratio", "Retry Ratio"), ("oscillation_rate", "Oscillation Rate"),
         ("success_rate", "Success Rate")],
        rows, empty_note="(no traversal shapes recorded)"))
    return "\n".join(lines)


def execute_verb(root: Path, verb: str, *,
                 run_id: Optional[str] = None,
                 as_json: bool = False) -> Tuple[int, Any]:
    """One implementation behind `python -m dv_harness.plan_quality_feedback`,
    the same shared-`execute_verb()` convention `loop_contract`/`loop_budget`/
    `loop_telemetry` follow."""
    root = Path(root)
    if verb in ("show", "report"):
        payload = aggregate_stage_sequence_shapes(root, run_id=run_id).to_dict()
        if not as_json:
            return (0 if payload.get("available") else 2), render_report_text(payload)
        return (0 if payload.get("available") else 2), payload
    return 1, {"ok": False, "error": "UNKNOWN_VERB", "verb": verb,
               "known": ["show", "report"]}


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - CLI shim
    import argparse
    p = argparse.ArgumentParser(
        prog="python -m dv_harness.plan_quality_feedback",
        description="Cross-run stage-sequencing efficiency, aggregated read-only "
                    "over real loop_telemetry.py/loop_convergence.py signals.")
    p.add_argument("verb", choices=["show", "report"])
    p.add_argument("--project-root", default=".")
    p.add_argument("--run-id", default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    code, payload = execute_verb(Path(args.project_root), args.verb,
                                 run_id=args.run_id, as_json=args.json)
    print(payload if isinstance(payload, str)
          else json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
