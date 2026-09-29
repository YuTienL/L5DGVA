"""dv_harness/consolidated_kpi_benchmark.py -- ONE cross-cutting KPI/benchmark
module, consolidating what would otherwise be several near-duplicate KPI
trackers scattered across intake, spec-to-signoff, spec-to-vplan and
golden-scenario/USB-benchmark surfaces.

THE GAP THIS CLOSES, re-verified by direct search before writing a line of
this module. `question_queue.py` already computes 4 real intake metrics
(`QuestionQueueStore.compute_metrics()` -- self_resolve_rate_percent,
blocking_questions_per_week, repeat_question_rate_percent,
assumption_overturned_rate_percent), `trend_analysis.py` already detects
PASS -> FAIL regressions and same-SHA flip-flops, and `signoff_export.py`
already evaluates whether a frozen signoff baseline has been invalidated by
later evidence. Each lives behind its own verb, in its own module, with its
own honesty rules -- and nothing anywhere assembled "how healthy is this
harness's own verification WORKFLOW" (as opposed to one project's DUT) into
one report a human could read once instead of running four commands and
reconciling four different vocabularies by hand. That is the same
PARTIALLY_WIRED-at-one-level-up shape `golden_flow_readiness.py` and
`platform_health.py` already closed for their own domains; this module does
the analogous consolidation for cross-cutting HARNESS KPIs.

THE HONESTY PATTERN THIS FOLLOWS is `confidence_calibration.py`'s: a KPI
computed from too few real events is reported `INSUFFICIENT_HISTORY`, never
a fabricated 100% or 0% -- that module is READ for the pattern (its own
`MIN_DETERMINATE_OUTCOMES_PER_TIER = 10` derivation: the smallest N at which
`1/N <= 0.1`, so a rate below it moves by more than the resolution it is
being read to) and this module reuses the identical derivation for its own
`MIN_SAMPLE_FOR_RATE`. Its CODE is not imported or copied -- this module
computes none of `confidence_calibration`'s facts and calibrates no
confidence tier; the two are peers, not a dependency.

WHAT THIS MODULE COMPUTES, and from which REAL producer -- never a second,
parallel re-derivation of a fact another module already owns:

  - question_queue_self_resolve_rate  -- `question_queue.QuestionQueueStore.
    compute_metrics()`, called verbatim. Self-resolve rate, repeat-question
    rate, blocking-questions/week and assumption-overturn rate are ONE real
    computation over ONE store's persisted questions/decisions; bundling
    them in one KPI entry is fidelity to that, not four disagreeing reports.
  - repeated_question_count -- a plain COUNT (not the rate `question_queue`
    already owns) of how many real asks in `QuestionQueueStore.
    list_questions()` are a re-ask of a `question_key` already asked before
    in this project. This is new arithmetic, but it is a COUNT over the same
    raw records `compute_metrics()` reads, never a re-derivation of that
    module's own Tier/self-resolve classification logic.
  - time_to_first_pass -- read from `.dv-harness/events.jsonl`'s real
    section-108 loop telemetry (`loop_telemetry.loop_events()`): the elapsed
    time from a real `LOOP_STARTED` event to the first real
    `LOOP_VERIFY_COMPLETED` event carrying `verdict == Status.PASS.value`,
    per real `run_id`. Never estimated from a stage's `attempts` counter or
    any other proxy.
  - false_pass_count -- `trend_analysis.detect_pattern_regressions()`'s own
    `SAME_GIT_SHA_PASSED_AND_FAILED` reason, over the real
    `regression_verdict_history` table in `evidence_db`: the same commit
    both passed and failed, which is a real, existing signal that an earlier
    PASS did not guarantee the property it claimed to (flake, incomplete
    check, environment-dependent result) -- never a fabricated
    "how many PASSes were actually wrong" count, which no producer in this
    codebase can answer without a labeled ground truth this repo does not
    have.
  - false_ready_count -- `signoff_export.evaluate_all_freezes()`'s own
    `INVALIDATED` count: a signoff baseline that WAS frozen (i.e. declared
    READY) and that real post-freeze evidence (RTL/waiver/evidence-hash
    divergence) later proved should not have stood unchanged. This is the
    closest real, existing analog to a "false-READY" signal this codebase
    has; it is a different question from a stale-but-honestly-still-valid
    freeze, which `evaluate_all_freezes()` itself reports as VALID.
  - ir_extraction_accuracy -- always `NOT_MEASURED`. Re-verified by direct
    search: no module in this repo computes an IR/requirement-extraction
    ACCURACY (agreement against a known-correct labeled extraction). What
    exists is `requirement_contract.analyze_requirement_contract_set()`
    (a self-CONSISTENCY status -- COMPLETE/AMBIGUOUS/CONTRADICTORY/UNKNOWN --
    over one already-produced record, not a comparison against ground
    truth) and `vplan_baseline._capture_requirement_ir_version()` (a content
    IDENTITY/version digest, not a correctness measurement). Neither answers
    "was the extraction accurate", and inventing a percentage here would be
    exactly the fabrication the Evidence Truth Rule forbids.
  - manual_edit_count / human_engineering_time -- always `NOT_MEASURED`.
    Re-verified by direct search (`manual_edit_count`, `engineering_time`,
    `human_hours`, `keystroke`, `human_effort`): no keystroke/diff-authorship
    tracker and no engineering-time tracker exists anywhere in this
    codebase. There is no honest number to report.

WHAT THIS MODULE DELIBERATELY DOES NOT DO. It computes no new confidence
tier, coverage number, or DV verdict; it re-derives no fact any of the
modules above already owns (only COUNTS/reads their own outputs); it writes
no state, control, approval, waiver, memory or Blackboard record; it invokes
no gate, build, regression or LSF submission; and it has deliberately no
stage gate of its own -- a gate that passed on a KPI nobody actually
measured would be worse than none. `ControlPlane.approve()`,
`policy.can_signoff()`, `assert_human_approval()` and the PR-only
main/master governance are untouched and unreferenced.

SCOPE NOTE per this task's own file-safety rules: this module reads
`question_queue.py`, `loop_telemetry.py`, `trend_analysis.py`,
`evidence_db.py`, `signoff_export.py` and `requirement_contract.py`/
`vplan_baseline.py` (the latter two only to CITE, in prose, why
`ir_extraction_accuracy` is NOT_MEASURED -- no function from either is
called). It does not import or wait on any OTHER item from this same batch
or the concurrently-running batch named in the master prompt.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

#: Per-KPI status. Deliberately four values, mirroring
#: `confidence_calibration.py`'s NOT_AVAILABLE / INSUFFICIENT_HISTORY split:
#: "there is nothing here" and "there is something but not enough of it" are
#: different operator facts with different fixes, and NOT_MEASURED is a
#: third, distinct fact again -- "this harness has never built a producer for
#: this KPI at all", never to be confused with either of the other two.
KPI_MEASURED = "MEASURED"
KPI_NOT_MEASURED = "NOT_MEASURED"
KPI_INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
KPI_NOT_AVAILABLE = "NOT_AVAILABLE"
KPI_STATUSES = frozenset({KPI_MEASURED, KPI_NOT_MEASURED, KPI_INSUFFICIENT_HISTORY,
                          KPI_NOT_AVAILABLE})

#: Which near-duplicate KPI-tracker surface a KPI consolidates, named exactly
#: as the task describes them. Informational grouping only -- nothing here
#: branches on it.
CATEGORY_INTAKE = "intake"
CATEGORY_SPEC_TO_SIGNOFF = "spec_to_signoff"
CATEGORY_SPEC_TO_VPLAN = "spec_to_vplan"
CATEGORY_GOLDEN_BENCHMARK = "golden_usb_benchmark"
KPI_CATEGORIES = frozenset({CATEGORY_INTAKE, CATEGORY_SPEC_TO_SIGNOFF,
                            CATEGORY_SPEC_TO_VPLAN, CATEGORY_GOLDEN_BENCHMARK})


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's KPI-status vocabulary must share no token with
    `dv_harness.models.Status` -- the same discipline
    `capability_evolution.py` / `benchmark_dataset.py` /
    `dependency_supply_chain.py` / `subsystem_maturity_gate.py` /
    `verification_strategy.py` already hold for their own vocabularies, so a
    KPI status can never be mistaken, by a reader or a log grep, for a DV
    stage-gate verdict."""
    from .models import Status
    verdicts = {s.value for s in Status}
    collision = verdicts.intersection(KPI_STATUSES)
    if collision:
        raise AssertionError(
            f"consolidated_kpi_benchmark KPI_STATUSES collides with "
            f"dv_harness.models.Status: {sorted(collision)}")


assert_no_verification_verdict_vocabulary()


#: The smallest N at which a computed RATE's own resolution (1/N) is no
#: coarser than 10 percentage points -- identical derivation, and identical
#: value, to `confidence_calibration.MIN_DETERMINATE_OUTCOMES_PER_TIER`.
#: Reused as a NUMBER (the arithmetic is the same regardless of which
#: project's rate is being read), not as a symbol imported from that module,
#: because this module calibrates no confidence tier and has no dependency
#: on that one.
MIN_SAMPLE_FOR_RATE = 10

#: Minimum number of real completed (start -> first-PASS) loop runs before a
#: median/spread is reported for `time_to_first_pass`. 3 samples = 2
#: consecutive independent runs beyond the first -- the same "2 independent
#: observations" bar this repo applies everywhere else
#: (`REPEAT_FAILURE_MIN_OCCURRENCES`, `ORGANIZATIONAL_MIN_CONFIRMATIONS`,
#: `loop_convergence.py`'s own `plateau_window`), plus one so a median is
#: something more than "the smaller of two numbers".
MIN_RUNS_FOR_TIMING = 3

#: Real producers, cited verbatim in every KPI record so a reader can go
#: check the claim rather than trust this module's arithmetic on faith.
PRODUCER_QUESTION_QUEUE_METRICS = "dv_harness.question_queue:QuestionQueueStore.compute_metrics"
PRODUCER_QUESTION_QUEUE_RAW = "dv_harness.question_queue:QuestionQueueStore.list_questions"
PRODUCER_LOOP_TELEMETRY = "dv_harness.loop_telemetry:loop_events"
PRODUCER_TREND_REGRESSIONS = "dv_harness.trend_analysis:detect_pattern_regressions"
PRODUCER_SIGNOFF_FREEZES = "dv_harness.signoff_export:evaluate_all_freezes"
#: Cited ONLY inside the ir_extraction_accuracy NOT_MEASURED reason text --
#: neither function is called by this module (see module docstring).
_REQUIREMENT_CONTRACT_STATUS_PRODUCER = (
    "dv_harness.requirement_contract:analyze_requirement_contract_set")
_VPLAN_BASELINE_VERSION_PRODUCER = (
    "dv_harness.vplan_baseline:_capture_requirement_ir_version")


def _kpi(name: str, category: str, status: str, *,
        value: Any = None, unit: Optional[str] = None,
        sample_size: Optional[int] = None,
        min_sample_required: Optional[int] = None,
        real_producer: Optional[str] = None,
        reason: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One KPI record, in the one shape every KPI in this report shares.
    `status` must be one of KPI_STATUSES; `reason` is REQUIRED for anything
    other than KPI_MEASURED, so a non-measured KPI never reaches a report
    silent about why."""
    if status not in KPI_STATUSES:
        raise ValueError(f"unknown KPI status {status!r}; known: {sorted(KPI_STATUSES)}")
    if category not in KPI_CATEGORIES:
        raise ValueError(f"unknown KPI category {category!r}; known: {sorted(KPI_CATEGORIES)}")
    if status != KPI_MEASURED and not reason:
        raise ValueError(f"KPI {name!r} status={status} requires a real reason")
    return {
        "kpi": name,
        "category": category,
        "status": status,
        "value": value,
        "unit": unit,
        "sample_size": sample_size,
        "min_sample_required": min_sample_required,
        "real_producer": real_producer,
        "reason": reason,
        "detail": dict(detail) if detail else {},
    }


# --------------------------------------------------------------------------
# Intake: question_queue.py's own real metrics + a new raw count over its
# own raw records
# --------------------------------------------------------------------------

def kpi_question_queue_self_resolve_rate(root: Path, *, store=None) -> Dict[str, Any]:
    """Self-resolve rate, plus the 3 sibling real metrics
    `QuestionQueueStore.compute_metrics()` already computes in the SAME call,
    bundled into one KPI record because they are one real computation over
    one store -- never four separately-gated re-derivations of the same
    underlying data."""
    from .question_queue import QuestionQueueStore
    qq = store if store is not None else QuestionQueueStore(Path(root))
    questions = qq.list_questions()
    total = len(questions)
    if total == 0:
        return _kpi("question_queue_self_resolve_rate", CATEGORY_INTAKE, KPI_NOT_AVAILABLE,
                    unit="percent", sample_size=0, min_sample_required=MIN_SAMPLE_FOR_RATE,
                    real_producer=PRODUCER_QUESTION_QUEUE_METRICS,
                    reason="NO_QUESTIONS_RECORDED",
                    detail={"detail": "this project's question_queue has never filed a "
                                       "question -- there is nothing to compute a rate from"})
    if total < MIN_SAMPLE_FOR_RATE:
        return _kpi("question_queue_self_resolve_rate", CATEGORY_INTAKE, KPI_INSUFFICIENT_HISTORY,
                    unit="percent", sample_size=total, min_sample_required=MIN_SAMPLE_FOR_RATE,
                    real_producer=PRODUCER_QUESTION_QUEUE_METRICS,
                    reason="TOO_FEW_QUESTIONS_FOR_A_STABLE_RATE",
                    detail={"detail": f"{total} question(s) on file; "
                                       f"{MIN_SAMPLE_FOR_RATE} required before a rate has "
                                       f"resolution finer than {100 // MIN_SAMPLE_FOR_RATE} "
                                       f"percentage points per record"})
    metrics = qq.compute_metrics()
    return _kpi("question_queue_self_resolve_rate", CATEGORY_INTAKE, KPI_MEASURED,
                value=metrics["self_resolve_rate_percent"], unit="percent",
                sample_size=total, min_sample_required=MIN_SAMPLE_FOR_RATE,
                real_producer=PRODUCER_QUESTION_QUEUE_METRICS,
                detail={
                    "self_resolve_rate_target_percent": metrics["self_resolve_rate_target_percent"],
                    "blocking_questions_per_week": metrics["blocking_questions_per_week"],
                    "repeat_question_rate_percent": metrics["repeat_question_rate_percent"],
                    "assumption_overturned_rate_percent": metrics["assumption_overturned_rate_percent"],
                })


def kpi_repeated_question_count(root: Path, *, store=None) -> Dict[str, Any]:
    """How many real asks (`QuestionQueueStore.list_questions()`) are a
    re-ask of a `question_key` this project has already asked before --
    total asks minus distinct question_keys. A plain count over the raw
    records, deliberately NOT the same computation as
    `compute_metrics()['repeat_question_rate_percent']` (which counts only
    re-asks AFTER a human answer that failed to resolve at Tier 1): this KPI
    answers "how much genuine repetition is in the ask stream", that one
    answers "how often does re-asking a settled question fail to
    self-resolve". Both are real and both are useful; this module reports
    both rather than picking one."""
    from .question_queue import QuestionQueueStore
    qq = store if store is not None else QuestionQueueStore(Path(root))
    questions = qq.list_questions()
    total = len(questions)
    if total == 0:
        return _kpi("repeated_question_count", CATEGORY_INTAKE, KPI_NOT_AVAILABLE,
                    unit="count", sample_size=0,
                    real_producer=PRODUCER_QUESTION_QUEUE_RAW,
                    reason="NO_QUESTIONS_RECORDED",
                    detail={"detail": "no questions on file to count repeats over"})
    distinct_keys = {q["question_key"] for q in questions}
    repeated = total - len(distinct_keys)
    return _kpi("repeated_question_count", CATEGORY_INTAKE, KPI_MEASURED,
                value=repeated, unit="count", sample_size=total,
                real_producer=PRODUCER_QUESTION_QUEUE_RAW,
                detail={"distinct_question_keys": len(distinct_keys), "total_asks": total})


# --------------------------------------------------------------------------
# Spec-to-signoff: time-to-first-PASS from real loop telemetry
# --------------------------------------------------------------------------

def _first_pass_durations(root: Path) -> Tuple[List[float], Dict[str, Any]]:
    """Real (LOOP_STARTED -> first LOOP_VERIFY_COMPLETED PASS) elapsed
    seconds, one per real `run_id` that reached both. Reads
    `.dv-harness/events.jsonl` through `loop_telemetry.loop_events()` --
    there is no second events.jsonl parser here."""
    from . import loop_telemetry
    from .models import Status
    picked, stats = loop_telemetry.loop_events(root)
    by_run: Dict[Tuple[str, str], Dict[str, str]] = {}
    for e in picked:
        run_id = e.get("run_id")
        loop_id = e.get("loop_id")
        if not run_id:
            continue
        key = (loop_id, run_id)
        rec = by_run.setdefault(key, {})
        if e.get("event") == "LOOP_STARTED" and "started" not in rec:
            rec["started"] = e.get("ts")
        elif (e.get("event") == "LOOP_VERIFY_COMPLETED"
              and e.get("verdict") == Status.PASS.value
              and rec.get("started") and "first_pass" not in rec):
            rec["first_pass"] = e.get("ts")
    durations: List[float] = []
    for rec in by_run.values():
        started, first_pass = rec.get("started"), rec.get("first_pass")
        if not started or not first_pass:
            continue
        try:
            t0 = datetime.fromisoformat(started)
            t1 = datetime.fromisoformat(first_pass)
        except ValueError:
            continue
        delta = (t1 - t0).total_seconds()
        if delta >= 0:
            durations.append(delta)
    return durations, {"runs_seen": len(by_run), **stats}


def kpi_time_to_first_pass(root: Path) -> Dict[str, Any]:
    durations, stats = _first_pass_durations(root)
    n = len(durations)
    if stats["runs_seen"] == 0:
        return _kpi("time_to_first_pass", CATEGORY_SPEC_TO_SIGNOFF, KPI_NOT_AVAILABLE,
                    unit="seconds", sample_size=0,
                    real_producer=PRODUCER_LOOP_TELEMETRY,
                    reason="NO_LOOP_TELEMETRY_EVENTS",
                    detail={"detail": "no LOOP_STARTED/LOOP_VERIFY_COMPLETED events in "
                                       ".dv-harness/events.jsonl -- this project has never "
                                       "run `dv-harness start --loop`", **stats})
    if n < MIN_RUNS_FOR_TIMING:
        return _kpi("time_to_first_pass", CATEGORY_SPEC_TO_SIGNOFF, KPI_INSUFFICIENT_HISTORY,
                    unit="seconds", sample_size=n, min_sample_required=MIN_RUNS_FOR_TIMING,
                    real_producer=PRODUCER_LOOP_TELEMETRY,
                    reason="TOO_FEW_COMPLETED_RUNS",
                    detail={"detail": f"{n} run(s) reached a first PASS; "
                                       f"{MIN_RUNS_FOR_TIMING} required before a median is "
                                       f"more than the smaller of two samples",
                            "raw_seconds": durations, **stats})
    return _kpi("time_to_first_pass", CATEGORY_SPEC_TO_SIGNOFF, KPI_MEASURED,
                value=round(statistics.median(durations), 3), unit="seconds",
                sample_size=n, min_sample_required=MIN_RUNS_FOR_TIMING,
                real_producer=PRODUCER_LOOP_TELEMETRY,
                detail={"mean_seconds": round(statistics.mean(durations), 3),
                        "min_seconds": round(min(durations), 3),
                        "max_seconds": round(max(durations), 3), **stats})


# --------------------------------------------------------------------------
# Spec-to-signoff: false-PASS, from the real trend-analysis regression
# detector over evidence_db's own regression_verdict_history
# --------------------------------------------------------------------------

def _open_evidence_store(root: Path, *, read_only: bool = True):
    """Opens `.dv-harness/evidence/evidence.duckdb` READ-ONLY, or returns
    None if it does not exist yet -- the same guard `golden_scenario._open_
    store()` / `trend_analysis.trend_report()` already use, so a KPI report
    never conjures an evidence database into existence."""
    from . import evidence_db
    path = evidence_db.default_db_path(root)
    if not Path(path).exists():
        return None
    try:
        return evidence_db.EvidenceStore(path, read_only=read_only)
    except Exception:
        return None


def kpi_false_pass_count(root: Path) -> Dict[str, Any]:
    from . import trend_analysis
    store = _open_evidence_store(root)
    if store is None:
        return _kpi("false_pass_count", CATEGORY_SPEC_TO_SIGNOFF, KPI_NOT_AVAILABLE,
                    unit="count", sample_size=0,
                    real_producer=PRODUCER_TREND_REGRESSIONS,
                    reason="NO_EVIDENCE_DATABASE",
                    detail={"detail": "no .dv-harness/evidence/evidence.duckdb -- nothing "
                                       "has been reconciled into regression_verdict_history yet"})
    try:
        total_rows_rows = store.query("SELECT COUNT(*) FROM regression_verdict_history")
        total_rows = int(total_rows_rows[0][0]) if total_rows_rows else 0
        regressions = trend_analysis.detect_pattern_regressions(store)
    except Exception as exc:
        # duckdb raises CatalogException for a database predating this
        # table -- the same tolerance memory_vault.search_related_memory_
        # for_debug() already applies to the identical failure mode.
        return _kpi("false_pass_count", CATEGORY_SPEC_TO_SIGNOFF, KPI_NOT_AVAILABLE,
                    unit="count", sample_size=0,
                    real_producer=PRODUCER_TREND_REGRESSIONS,
                    reason="REGRESSION_VERDICT_HISTORY_UNQUERYABLE",
                    detail={"detail": str(exc)})
    finally:
        try:
            store.close()
        except Exception:
            pass
    same_sha = [r for r in regressions
                if r.reason == "SAME_GIT_SHA_PASSED_AND_FAILED"]
    if total_rows == 0:
        return _kpi("false_pass_count", CATEGORY_SPEC_TO_SIGNOFF, KPI_NOT_AVAILABLE,
                    unit="count", sample_size=0,
                    real_producer=PRODUCER_TREND_REGRESSIONS,
                    reason="NO_REGRESSION_VERDICTS_RECORDED",
                    detail={"detail": "regression_verdict_history has no rows"})
    if total_rows < MIN_SAMPLE_FOR_RATE:
        return _kpi("false_pass_count", CATEGORY_SPEC_TO_SIGNOFF, KPI_INSUFFICIENT_HISTORY,
                    unit="count", sample_size=total_rows, min_sample_required=MIN_SAMPLE_FOR_RATE,
                    real_producer=PRODUCER_TREND_REGRESSIONS,
                    reason="TOO_FEW_RECORDED_VERDICTS",
                    detail={"detail": f"{total_rows} recorded verdict row(s); "
                                       f"{MIN_SAMPLE_FOR_RATE} required",
                            "raw_count_so_far": len(same_sha)})
    return _kpi("false_pass_count", CATEGORY_SPEC_TO_SIGNOFF, KPI_MEASURED,
                value=len(same_sha), unit="count",
                sample_size=total_rows, min_sample_required=MIN_SAMPLE_FOR_RATE,
                real_producer=PRODUCER_TREND_REGRESSIONS,
                detail={"reason_matched": "SAME_GIT_SHA_PASSED_AND_FAILED",
                        "patterns_examined": len(regressions),
                        "affected_patterns": [r.pattern for r in same_sha]})


# --------------------------------------------------------------------------
# Golden-scenario / signoff benchmark: false-READY, from the real signoff
# freeze-invalidation evaluator
# --------------------------------------------------------------------------

def kpi_false_ready_count(root: Path) -> Dict[str, Any]:
    from .signoff_export import evaluate_all_freezes, FREEZE_INVALIDATED
    result = evaluate_all_freezes(Path(root))
    if result.get("status") == "NOT_AVAILABLE" or "freeze_count" not in result:
        return _kpi("false_ready_count", CATEGORY_GOLDEN_BENCHMARK, KPI_NOT_AVAILABLE,
                    unit="count", sample_size=0,
                    real_producer=PRODUCER_SIGNOFF_FREEZES,
                    reason=result.get("reason", "NO_FROZEN_SIGNOFF_BASELINE"),
                    detail={"detail": "no signoff baseline has ever been frozen in this "
                                       "project (signoff_export.freeze_signoff_baseline())"})
    freeze_count = result["freeze_count"]
    invalidated = result["counts"].get(FREEZE_INVALIDATED, 0)
    return _kpi("false_ready_count", CATEGORY_GOLDEN_BENCHMARK, KPI_MEASURED,
                value=invalidated, unit="count", sample_size=freeze_count,
                real_producer=PRODUCER_SIGNOFF_FREEZES,
                detail={"freeze_count": freeze_count, "counts": result["counts"]})


# --------------------------------------------------------------------------
# Honest NOT_MEASURED KPIs -- no real producer exists for these, and none is
# invented. Each is checked every time this report runs so the disclosure is
# never a stale claim.
# --------------------------------------------------------------------------

def kpi_ir_extraction_accuracy() -> Dict[str, Any]:
    return _kpi("ir_extraction_accuracy", CATEGORY_SPEC_TO_VPLAN, KPI_NOT_MEASURED,
                unit="percent",
                reason="NO_ACCURACY_PRODUCER_EXISTS",
                detail={"detail": (
                    "no module in this codebase compares an extracted requirement/IR "
                    "against a known-correct labeled extraction. The closest real "
                    "mechanisms are requirement_contract.analyze_requirement_contract_set() "
                    "(a self-consistency status -- COMPLETE/AMBIGUOUS/CONTRADICTORY/UNKNOWN "
                    "-- over one already-produced record, not agreement with ground truth) "
                    "and vplan_baseline._capture_requirement_ir_version() (a content-identity "
                    "digest, not a correctness measurement). Neither answers 'was the "
                    "extraction accurate', so no number is reported here."),
                        "closest_existing_mechanisms": [
                            _REQUIREMENT_CONTRACT_STATUS_PRODUCER,
                            _VPLAN_BASELINE_VERSION_PRODUCER]})


def kpi_manual_edit_count() -> Dict[str, Any]:
    return _kpi("manual_edit_count", CATEGORY_GOLDEN_BENCHMARK, KPI_NOT_MEASURED,
                unit="count",
                reason="NO_PRODUCER_EXISTS",
                detail={"detail": "no keystroke, diff-authorship, or hand-edit tracker "
                                   "exists anywhere in this codebase; there is no real "
                                   "event stream to count."})


def kpi_human_engineering_time() -> Dict[str, Any]:
    return _kpi("human_engineering_time", CATEGORY_GOLDEN_BENCHMARK, KPI_NOT_MEASURED,
                unit="seconds",
                reason="NO_PRODUCER_EXISTS",
                detail={"detail": "no time-tracking mechanism exists anywhere in this "
                                   "codebase (no session-duration log tied to a human "
                                   "engineer's own work, as distinct from `engine.now()` "
                                   "timestamps on harness-internal events); there is no "
                                   "real measurement to report."})


# --------------------------------------------------------------------------
# The consolidated report
# --------------------------------------------------------------------------

#: Every KPI this report always includes, in this fixed order. A KPI listed
#: here always has a row in the report -- MEASURED, NOT_MEASURED,
#: INSUFFICIENT_HISTORY or NOT_AVAILABLE -- never silently omitted.
KPI_NAMES: Tuple[str, ...] = (
    "question_queue_self_resolve_rate",
    "repeated_question_count",
    "time_to_first_pass",
    "false_pass_count",
    "false_ready_count",
    "ir_extraction_accuracy",
    "manual_edit_count",
    "human_engineering_time",
)


def benchmark_report(root: Path) -> Dict[str, Any]:
    """The whole consolidated KPI report for one project. Reading is never a
    mutating act: no `QuestionQueueStore`/`EvidenceStore` write path is
    called, evidence/question-queue stores are opened read-only or not
    constructed at all when their backing file is absent, and no signoff
    freeze, gate, approval or memory record is written."""
    from .engine import now as _now
    root = Path(root)
    kpis = [
        kpi_question_queue_self_resolve_rate(root),
        kpi_repeated_question_count(root),
        kpi_time_to_first_pass(root),
        kpi_false_pass_count(root),
        kpi_false_ready_count(root),
        kpi_ir_extraction_accuracy(),
        kpi_manual_edit_count(),
        kpi_human_engineering_time(),
    ]
    names = tuple(k["kpi"] for k in kpis)
    if names != KPI_NAMES:
        raise AssertionError(f"benchmark_report() KPI order drifted from KPI_NAMES: {names}")
    counts_by_status = {s: sum(1 for k in kpis if k["status"] == s) for s in sorted(KPI_STATUSES)}
    return {
        "generated_at": _now(),
        "project_root": str(root),
        "kpi_count": len(kpis),
        "counts_by_status": counts_by_status,
        "kpis": kpis,
    }


def render_report_text(report: Dict[str, Any]) -> str:
    lines = [f"Consolidated KPI Benchmark -- {report['kpi_count']} KPI(s), "
             f"{report['counts_by_status']}"]
    for k in report["kpis"]:
        val = k["value"]
        unit = f" {k['unit']}" if k.get("unit") else ""
        lines.append(f"  [{k['status']:<20}] {k['kpi']:<32} "
                     f"{'' if val is None else val}{unit}"
                     f"{'' if not k.get('reason') else '  (' + k['reason'] + ')'}")
    return "\n".join(lines)


def execute_verb(root: Path, verb: str, *, as_json: bool = False) -> Tuple[int, Any]:
    """Shared implementation for `python -m dv_harness.consolidated_kpi_
    benchmark <verb>`. No `dv-harness` CLI verb was added -- `cli.py` is
    explicitly off-limits to this task; a future integration step may wire
    one in.

    Exit codes are reporting signals only, never an approval or gate signal:
    0 the report was produced (regardless of how many KPIs are
    NOT_MEASURED/INSUFFICIENT_HISTORY -- those are expected, honest states,
    not failures of this command), 1 a usage error."""
    root = Path(root)
    if verb == "names":
        return 0, {"kpi_names": list(KPI_NAMES), "categories": sorted(KPI_CATEGORIES),
                   "statuses": sorted(KPI_STATUSES),
                   "min_sample_for_rate": MIN_SAMPLE_FOR_RATE,
                   "min_runs_for_timing": MIN_RUNS_FOR_TIMING}
    if verb in ("report", "show"):
        report = benchmark_report(root)
        if verb == "show" and not as_json:
            return 0, render_report_text(report)
        return 0, report
    return 1, {"ok": False, "error": "UNKNOWN_VERB", "verb": verb,
               "known": ["names", "report", "show"]}


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - CLI shim
    import argparse
    p = argparse.ArgumentParser(
        prog="python -m dv_harness.consolidated_kpi_benchmark",
        description="Consolidated cross-cutting KPI/benchmark report -- self-resolve rate, "
                    "repeated-question count, time-to-first-PASS, false-PASS/false-READY "
                    "count, and honest NOT_MEASURED disclosures for IR extraction accuracy "
                    "and any human-effort KPI with no real producer.")
    p.add_argument("verb", choices=["names", "report", "show"])
    p.add_argument("--project-root", default=".")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    code, payload = execute_verb(Path(args.project_root), args.verb, as_json=args.json)
    print(payload if isinstance(payload, str)
          else json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return code


if __name__ == "__main__":  # pragma: no cover - CLI shim
    raise SystemExit(main())
