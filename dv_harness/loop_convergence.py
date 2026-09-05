"""LOOP_ENGINEERING sections 88-90: convergence classification, plateau
detection, and oscillation / no-progress detection.

WHAT WAS ACTUALLY MISSING, RE-VERIFIED BEFORE THIS FILE WAS WRITTEN
-------------------------------------------------------------------
`loop_contract.py` (LOOP-1, 2026-09-05) closed sections 85/86 -- the contract
schema and the `LoopState` vocabulary -- and its own module docstring states
what it deliberately did NOT do: "It does not DETECT plateau or oscillation.
`observe_*` reports `PLATEAU_NOT_EVALUATED` ... A progress-metric series
(coverage over iterations) has a real producer -- `trend_analysis.py` and
`coverage_analysis.py` -- and wiring one in is a separate change." A repo-wide
grep on 2026-09-05 confirmed that was still true: `PLATEAU` appeared only as a
`LoopState` member nothing computed, and no function anywhere classified a
progress series. `LoopPlateau.detection_window` / `minimum_gain` and
`LoopConvergence.minimum_progress` / `window` were all `None` on the
verification-closure contract for exactly that reason.

This module is that separate change. It is the DETECTOR half; `loop_contract`
stays the vocabulary half.

WHAT IT REUSES RATHER THAN REBUILDS
-----------------------------------
Not one number here is re-derived from raw evidence this project already
reduces:

  * the coverage series is `trend_analysis.daily_rollup()`'s own
    `DailyPoint.coverage_percent` -- the bins-weighted daily curve computed
    from the real `coverage_samples` rows, never a second aggregation;
  * the repeat-fix-revert fingerprint is `trend_analysis.
    detect_verdict_oscillation()`, which reads the same
    `regression_verdict_history` table `detect_pattern_regressions()` reads;
  * the repeat-FAILURE fingerprint is `loop_contract.
    detect_oscillation_from_debug_loop_history()`, called, not copied;
  * the "flat" tolerance is `coverage_analysis.FLAT_TREND_TOLERANCE_PERCENT`,
    the same band `compute_coverage_trend()` calls FLAT -- so this classifier
    and that one cannot disagree about the identical series;
  * the plateau INVESTIGATION is `coverage_analysis.classify_coverage_hole()`,
    which already distinguishes unreachable-stimulus from stimulus-gap from
    not-yet-sampled per bin against real seed-run history. Section 89's
    "unreachable bins / stimulus-gap investigation" is that classifier
    aggregated to a loop-level next action, not a second bin classifier.

`capability_evolution.repeated_unresolved_failure_patterns()` is adjacent and
deliberately NOT called: it groups Job Memory `job_failure` records by
`evidence_db.signature_key()` in order to FILE a capability candidate, and its
threshold semantics (independent RUNS, closed only by a `verified_fix` record)
are purpose-built for that. What this module borrows from it is the technique --
collapse repetitions, count INDEPENDENT observations, never fuzzy-match -- over
a different real key (the regression `pattern`), because a loop verdict must
not depend on whether a capability candidate happened to be filed.

WHAT THIS MODULE DOES NOT DO
-----------------------------
  * It writes nothing and escalates nothing. `investigate_plateau()` CLASSIFIES
    holes and reports which ones need a human; the real escalator is still
    `coverage_analysis.escalate_unreachable_holes()`, which a caller invokes
    deliberately. An observation that files questions as a side effect would
    make reading the loop's state a mutating act.
  * It mints no verdict and touches no gate. `HumanApprovalRequiredError`,
    `ProductionWriteNotAuthorizedError`, `ControlPlane.approve()`,
    `policy.can_signoff()` and the PR-only main/master governance are
    untouched and uncalled from here.
  * It never invents a series. A project with no evidence database, or one
    whose days carry no coverage sample, reports UNKNOWN with the real reason.
    A classifier that never ran and a classifier that found nothing are
    different facts -- the same rule `PLATEAU_NOT_EVALUATED` encodes.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from .coverage_analysis import (
    ACTION_ADD_SEEDS,
    ACTION_ADJUST_CONSTRAINT,
    ACTION_ESCALATE_TO_HUMAN,
    ACTION_GENERATE_TESTCASE,
    FLAT_TREND_TOLERANCE_PERCENT,
    ROOT_CAUSE_INSUFFICIENT_CONSTRAINT,
    ROOT_CAUSE_INSUFFICIENT_SEED_ATTEMPTS,
    ROOT_CAUSE_MISSING_TEST,
    ROOT_CAUSE_UNREACHABLE_STIMULUS,
)
from .loop_contract import (
    DEFAULT_OSCILLATION_REPEAT_THRESHOLD,
    LoopState,
    detect_oscillation_from_debug_loop_history,
)

# --------------------------------------------------------------------------
# Section 88: the convergence verdicts
# --------------------------------------------------------------------------
CONVERGING = "CONVERGING"
SLOW_CONVERGENCE = "SLOW_CONVERGENCE"
NO_PROGRESS = "NO_PROGRESS"
PLATEAU = "PLATEAU"
REGRESSION = "REGRESSION"
OSCILLATING = "OSCILLATING"
UNKNOWN = "UNKNOWN"

#: Section 88's vocabulary, verbatim and complete.
CONVERGENCE_VERDICTS = (
    CONVERGING, SLOW_CONVERGENCE, NO_PROGRESS, PLATEAU,
    REGRESSION, OSCILLATING, UNKNOWN,
)

#: Every convergence verdict's `LoopState` meaning, TOTAL by construction
#: (`assert_verdict_mapping_total()`). `None` is a DECIDED entry, not an
#: omission: section 86's state machine has no REGRESSION and no NO_PROGRESS
#: member, and minting one here would be exactly the second-vocabulary defect
#: `loop_contract`'s own "WHY A SECOND ENUM" section argues against. Those two
#: verdicts are carried as the verdict itself and leave the loop's state to be
#: derived from the stage's real status.
#:
#: SLOW_CONVERGENCE maps to CONVERGING because it IS forward progress -- slowly.
#: Mapping it to PLATEAU would tell a loop to stop retrying something that is
#: still working.
VERDICT_TO_LOOP_STATE: Dict[str, Optional[LoopState]] = {
    CONVERGING: LoopState.CONVERGING,
    SLOW_CONVERGENCE: LoopState.CONVERGING,
    NO_PROGRESS: None,
    PLATEAU: LoopState.PLATEAU,
    REGRESSION: None,
    OSCILLATING: LoopState.OSCILLATING,
    UNKNOWN: None,
}


def assert_verdict_mapping_total() -> None:
    """Every section-88 verdict must have a decided loop meaning, and the
    mapping must name no verdict outside `CONVERGENCE_VERDICTS`. Called by the
    tests; a new verdict added without a decision here fails them."""
    missing = [v for v in CONVERGENCE_VERDICTS if v not in VERDICT_TO_LOOP_STATE]
    if missing:
        raise AssertionError(
            f"convergence verdicts with no LoopState meaning decided: {missing}. "
            f"Add them to VERDICT_TO_LOOP_STATE (and say why in its comment).")
    unknown = [k for k in VERDICT_TO_LOOP_STATE if k not in CONVERGENCE_VERDICTS]
    if unknown:
        raise AssertionError(
            f"VERDICT_TO_LOOP_STATE names non-verdict keys: {unknown}")
    bad = [f"{k}->{v}" for k, v in VERDICT_TO_LOOP_STATE.items()
           if v is not None and not isinstance(v, LoopState)]
    if bad:
        raise AssertionError(
            f"VERDICT_TO_LOOP_STATE values must be a LoopState or None: {bad}")


# --------------------------------------------------------------------------
# Thresholds. Every one derived from a number this project already defends,
# never a fresh magic constant.
# --------------------------------------------------------------------------

#: Below this the metric did not move; it is `coverage_analysis`'s own FLAT
#: band, so "flat" means the same thing to both modules.
DEFAULT_NOISE_FLOOR_PERCENT = FLAT_TREND_TOLERANCE_PERCENT

#: The window's net gain that makes CONVERGING an unambiguous claim: twice the
#: noise floor, so a run sitting on the edge of the tolerance band is reported
#: SLOW_CONVERGENCE (real, but only just) rather than promoted to CONVERGING.
DEFAULT_MIN_GAIN_PERCENT = 2 * DEFAULT_NOISE_FLOOR_PERCENT

#: How many trailing samples the verdict is computed over. Four is the smallest
#: window that can hold the three consecutive deltas an OSCILLATING verdict
#: needs (two direction reversals), so the window cannot structurally hide the
#: verdict it is supposed to be able to produce.
DEFAULT_CONVERGENCE_WINDOW = 4

#: Consecutive no-gain SAMPLES before flat becomes PLATEAU rather than
#: NO_PROGRESS. Three samples is two consecutive no-gain INTERVALS -- the same
#: "2 INDEPENDENT observations" bar `DEFAULT_OSCILLATION_REPEAT_THRESHOLD`,
#: `capability_evolution.REPEAT_FAILURE_MIN_OCCURRENCES` and
#: `memory_router.ORGANIZATIONAL_MIN_CONFIRMATIONS` already use. One flat
#: interval is an ordinary quiet day and must not read as a plateau.
DEFAULT_PLATEAU_WINDOW = DEFAULT_OSCILLATION_REPEAT_THRESHOLD + 1

#: The per-interval gain below which a sample counts as no progress for the
#: plateau run. The noise floor again, deliberately: a plateau is a run of
#: intervals each of which failed to move the metric out of the noise.
DEFAULT_PLATEAU_MIN_GAIN_PERCENT = DEFAULT_NOISE_FLOOR_PERCENT

#: Direction reversals among SIGNIFICANT deltas before the series is called
#: OSCILLATING. Same threshold, same reason.
DEFAULT_OSCILLATION_MIN_REVERSALS = DEFAULT_OSCILLATION_REPEAT_THRESHOLD

#: Reasons a verdict is UNKNOWN. Distinct strings on purpose: "this project has
#: no evidence database" and "it has one but no day in it carries a coverage
#: number" are different operator problems with different fixes.
INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
NO_EVIDENCE_DATABASE = "NO_EVIDENCE_DATABASE"
NO_COVERAGE_SAMPLES = "NO_COVERAGE_SAMPLES"

#: The metric this classifier is applied to on the real path. Named so the
#: contract and the verdict cannot disagree about what was measured.
COVERAGE_PERCENT_METRIC = "coverage_percent"


# --------------------------------------------------------------------------
# The series
# --------------------------------------------------------------------------
@dataclass
class ProgressPoint:
    """One real observation of a progress metric.

    `label` is the observation's own identity as its producer recorded it (for
    the real path: the calendar day `trend_analysis.daily_rollup()` bucketed
    by), never an index this module invented -- so a verdict can always be
    traced back to the rows it was computed from."""
    label: str
    value: float
    source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def points_from_daily_rollup(daily_points: List[Any], *,
                             metric: str = COVERAGE_PERCENT_METRIC) -> List[ProgressPoint]:
    """`trend_analysis.DailyPoint` list -> `ProgressPoint` series.

    A day whose metric is `None` is SKIPPED, never read as 0 -- that is
    `DailyPoint`'s own documented contract ("None -- never 0 -- when that day
    has no real evidence for it"), and treating a quiet day as 0% coverage
    would manufacture a REGRESSION out of an absence."""
    out: List[ProgressPoint] = []
    for p in daily_points or []:
        value = getattr(p, metric, None)
        if value is None:
            continue
        out.append(ProgressPoint(label=str(getattr(p, "day", "")),
                                 value=float(value),
                                 source=f"trend_analysis.daily_rollup().{metric}"))
    return out


def points_from_history(history: List[Dict[str, Any]]) -> List[ProgressPoint]:
    """`coverage_analysis.append_history_sample()`'s own
    `[{"timestamp","percent"}, ...]` trend log -> `ProgressPoint` series,
    sorted by timestamp exactly as `compute_coverage_trend()` sorts it."""
    usable = [h for h in (history or [])
              if isinstance(h, dict) and h.get("percent") is not None
              and h.get("timestamp") is not None]
    ordered = sorted(usable, key=lambda h: h["timestamp"])
    return [ProgressPoint(label=str(h["timestamp"]), value=float(h["percent"]),
                          source="coverage_analysis.append_history_sample()")
            for h in ordered]


# --------------------------------------------------------------------------
# Section 88: the classifier
# --------------------------------------------------------------------------
@dataclass
class ConvergenceVerdict:
    """One verdict plus every number it was computed from.

    The evidence fields are the point of this dataclass, exactly as they are
    for `LoopObservation`: a reader must be able to re-derive the verdict
    without trusting it."""
    verdict: str
    metric: str
    reason: str
    series_length: int = 0
    window_used: int = 0
    window_labels: List[str] = field(default_factory=list)
    window_values: List[float] = field(default_factory=list)
    deltas: List[float] = field(default_factory=list)
    net_delta: Optional[float] = None
    significant_reversals: int = 0
    flat_run_samples: int = 0
    thresholds: Dict[str, Any] = field(default_factory=dict)
    loop_state: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _sign(value: float, noise_floor: float) -> int:
    if value >= noise_floor:
        return 1
    if value <= -noise_floor:
        return -1
    return 0


def _trailing_flat_run(points: List[ProgressPoint], min_gain: float) -> int:
    """How many trailing samples of the WHOLE series form an unbroken run of
    intervals in which the metric did not MOVE by `min_gain`.

    ABSOLUTE movement, not gain: a plateau is a metric that has stopped moving,
    and counting a large DECLINE as "did not gain" would let a spike-then-crash
    series -- whose window net is flat only because the two cancel -- report a
    long plateau it never had. A real decline is REGRESSION's business, and
    `classify_convergence()` tests that first.

    Computed over the whole series and not just the window on purpose: a
    plateau's whole meaning is that it has lasted, and truncating the count at
    the window would cap a six-day plateau at the window size and make a long
    plateau indistinguishable from a fresh one."""
    if not points:
        return 0
    run = 1
    for i in range(len(points) - 1, 0, -1):
        if abs(points[i].value - points[i - 1].value) < min_gain:
            run += 1
        else:
            break
    return run


def classify_convergence(points: List[ProgressPoint], *,
                         metric: str = COVERAGE_PERCENT_METRIC,
                         window: int = DEFAULT_CONVERGENCE_WINDOW,
                         min_gain: float = DEFAULT_MIN_GAIN_PERCENT,
                         noise_floor: float = DEFAULT_NOISE_FLOOR_PERCENT,
                         plateau_window: int = DEFAULT_PLATEAU_WINDOW,
                         plateau_min_gain: float = DEFAULT_PLATEAU_MIN_GAIN_PERCENT,
                         oscillation_min_reversals: int =
                         DEFAULT_OSCILLATION_MIN_REVERSALS) -> ConvergenceVerdict:
    """Section 88's classifier over one real progress-metric series.

    PRECEDENCE, and why it is this order:

      1. **OSCILLATING** -- `oscillation_min_reversals` direction reversals
         among deltas that cleared the noise floor. First, because a series
         that goes up, down and up again can have any net value at all: a
         net-flat oscillation would otherwise read as NO_PROGRESS, which points
         a loop at "add stimulus" when the real problem is that its own changes
         keep undoing each other. Only SIGNIFICANT deltas carry a direction --
         a sequence jittering inside the tolerance band has no directions to
         reverse, and counting its noise as reversals would make every flat
         series oscillate.
      2. **REGRESSION** -- net decline past the noise floor. The metric got
         worse, which no forward-progress verdict may describe.
      3. **CONVERGING** -- net gain >= `min_gain`.
      4. **SLOW_CONVERGENCE** -- net gain that cleared the noise floor but not
         `min_gain`. Real progress, at a rate worth naming.
      5. Flat: **PLATEAU** when the trailing no-gain run reaches
         `plateau_window` samples, otherwise **NO_PROGRESS**. The distinction is
         load-bearing: NO_PROGRESS is "this window did not move", PLATEAU is
         "it has not moved for long enough that continuing the same strategy is
         the wrong move", and only the second justifies section 89's
         investigation.

    Fewer than two points is **UNKNOWN/INSUFFICIENT_HISTORY**, the same floor
    `compute_coverage_trend()` enforces -- a trend guessed from one sample is
    not a measurement."""
    thresholds = {
        "window": window, "min_gain_percent": min_gain,
        "noise_floor_percent": noise_floor,
        "plateau_window_samples": plateau_window,
        "plateau_min_gain_percent": plateau_min_gain,
        "oscillation_min_reversals": oscillation_min_reversals,
    }
    series = list(points or [])
    if len(series) < 2:
        return ConvergenceVerdict(
            verdict=UNKNOWN, metric=metric, reason=INSUFFICIENT_HISTORY,
            series_length=len(series), thresholds=thresholds,
            window_labels=[p.label for p in series],
            window_values=[round(p.value, 6) for p in series],
            loop_state=None,
        )

    win = series[-window:] if window and window > 0 else series
    values = [p.value for p in win]
    deltas = [round(values[i + 1] - values[i], 6) for i in range(len(values) - 1)]
    net = round(values[-1] - values[0], 6)
    signs = [s for s in (_sign(d, noise_floor) for d in deltas) if s != 0]
    reversals = sum(1 for i in range(len(signs) - 1) if signs[i] != signs[i + 1])
    flat_run = _trailing_flat_run(series, plateau_min_gain)

    base = dict(metric=metric, series_length=len(series), window_used=len(win),
                window_labels=[p.label for p in win],
                window_values=[round(v, 6) for v in values],
                deltas=deltas, net_delta=net, significant_reversals=reversals,
                flat_run_samples=flat_run, thresholds=thresholds)

    if reversals >= oscillation_min_reversals:
        verdict, reason = OSCILLATING, (
            f"{reversals} direction reversals among deltas clearing the "
            f"{noise_floor}% noise floor: the metric is being undone as fast as it is gained")
    elif net <= -noise_floor:
        verdict, reason = REGRESSION, (
            f"net {net}% over {len(win)} samples: the metric declined past the "
            f"{noise_floor}% noise floor")
    elif net >= min_gain:
        verdict, reason = CONVERGING, (
            f"net +{net}% over {len(win)} samples (>= {min_gain}% minimum progress)")
    elif net >= noise_floor:
        verdict, reason = SLOW_CONVERGENCE, (
            f"net +{net}% over {len(win)} samples: real progress, but below the "
            f"{min_gain}% minimum-progress bar")
    elif flat_run >= plateau_window:
        verdict, reason = PLATEAU, (
            f"{flat_run} consecutive samples moved less than {plateau_min_gain}% "
            f"(plateau window {plateau_window}); continuing the same strategy is not "
            f"expected to move this metric")
    else:
        verdict, reason = NO_PROGRESS, (
            f"net {net}% over {len(win)} samples is inside the {noise_floor}% noise floor, "
            f"but only {flat_run} consecutive flat samples -- short of the {plateau_window} "
            f"a plateau claim needs")

    state = VERDICT_TO_LOOP_STATE[verdict]
    return ConvergenceVerdict(verdict=verdict, reason=reason,
                              loop_state=state.value if state else None, **base)


# --------------------------------------------------------------------------
# Section 89: the plateau investigation
# --------------------------------------------------------------------------
#: What a plateau investigation concludes when there is nothing to investigate.
NO_HOLES_TO_INVESTIGATE = "NO_HOLES_TO_INVESTIGATE"

#: The plateau claim is premature: bins that have not been fairly sampled
#: cannot support any structural conclusion.
PLATEAU_PREMATURE_UNDER_SAMPLED = "PLATEAU_PREMATURE_UNDER_SAMPLED"


@dataclass
class PlateauInvestigation:
    """Section 89's unreachable-bins / stimulus-gap investigation, aggregated
    from `coverage_analysis.classify_coverage_hole()`'s real per-bin verdicts.

    `escalator` NAMES the real escalation path rather than taking it: nothing
    here writes to the question queue."""
    holes_examined: int
    by_classification: Dict[str, int] = field(default_factory=dict)
    unreachable_candidates: List[str] = field(default_factory=list)
    stimulus_gap_candidates: List[str] = field(default_factory=list)
    under_sampled_candidates: List[str] = field(default_factory=list)
    unclassified: List[str] = field(default_factory=list)
    recommended_action: str = NO_HOLES_TO_INVESTIGATE
    basis: str = ""
    escalation_required: bool = False
    escalator: str = "coverage_analysis.escalate_unreachable_holes()"
    verdicts: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def investigate_plateau(root, holes: List[Dict[str, Any]], *,
                        cfg: Optional[Dict[str, Any]] = None,
                        registry=None, db_path=None,
                        history_available=None) -> PlateauInvestigation:
    """Why is the coverage curve flat -- unreachable bins, a stimulus gap, or
    simply not enough seeds yet?

    Every per-bin verdict is `coverage_analysis.classify_coverage_hole()`'s,
    unchanged: it already measures distinct seed attempts against real
    `jobs` rows, resolves coverage_id -> PATTERN_ID through the project's own
    traceability registry, and refuses to let an "unreachable" claim stand on a
    bin that has barely been sampled. This function adds exactly one thing that
    did not exist: the LOOP-level next action over the whole set.

    The aggregate precedence is that same per-bin precedence applied one level
    up, for the same reason:
      1. any under-sampled bin -> ADD_SEEDS, and the plateau is reported
         PREMATURE. Seeds are the cheapest and safest move, and a plateau
         declared over bins randomization has not fairly attempted is not a
         plateau -- it is an unfinished run.
      2. otherwise any stimulus-gap bin (MISSING_TEST / INSUFFICIENT_CONSTRAINT)
         -> generate a testcase or adjust constraints. Real, actionable work
         that does not need a human decision.
      3. otherwise any unreachable-stimulus bin -> ESCALATE. Only the design
         owner can confirm the RTL cannot produce a condition, and writing
         another testcase provably cannot.
    """
    from .coverage_analysis import classify_coverage_hole, seed_history_available

    # Probed ONCE for the whole investigation rather than once per hole:
    # `classify_coverage_hole()` would otherwise re-open the evidence database
    # for every bin, and -- more importantly -- two bins in one investigation
    # must not be able to disagree about whether this project has seed history
    # at all.
    if history_available is None:
        history_available = seed_history_available(root, db_path=db_path)

    inv = PlateauInvestigation(holes_examined=0)
    for hole in (holes or []):
        if not isinstance(hole, dict) or hole.get("waived"):
            continue
        verdict = classify_coverage_hole(root, hole, cfg=cfg, registry=registry,
                                         db_path=db_path,
                                         history_available=history_available)
        inv.holes_examined += 1
        inv.verdicts.append(verdict)
        cid = verdict.get("coverage_id") or ""
        cls = verdict.get("classification")
        key = cls or "UNCLASSIFIED"
        inv.by_classification[key] = inv.by_classification.get(key, 0) + 1
        if cls == ROOT_CAUSE_INSUFFICIENT_SEED_ATTEMPTS:
            inv.under_sampled_candidates.append(cid)
        elif cls in (ROOT_CAUSE_MISSING_TEST, ROOT_CAUSE_INSUFFICIENT_CONSTRAINT):
            inv.stimulus_gap_candidates.append(cid)
        elif cls == ROOT_CAUSE_UNREACHABLE_STIMULUS:
            inv.unreachable_candidates.append(cid)
        else:
            inv.unclassified.append(cid)

    if not inv.holes_examined:
        inv.basis = ("no unwaived coverage hole was supplied, so the flat curve has no "
                     "per-bin explanation to report")
        return inv

    if inv.under_sampled_candidates:
        inv.recommended_action = ACTION_ADD_SEEDS
        inv.basis = (f"{len(inv.under_sampled_candidates)} of {inv.holes_examined} bins have "
                     f"not had a fair randomization attempt "
                     f"({PLATEAU_PREMATURE_UNDER_SAMPLED}); no structural conclusion about "
                     f"this plateau is supportable until they have")
    elif inv.stimulus_gap_candidates:
        missing_test = inv.by_classification.get(ROOT_CAUSE_MISSING_TEST, 0)
        inv.recommended_action = (ACTION_GENERATE_TESTCASE if missing_test
                                  else ACTION_ADJUST_CONSTRAINT)
        inv.basis = (f"{len(inv.stimulus_gap_candidates)} of {inv.holes_examined} bins are a "
                     f"real stimulus gap ({missing_test} with no test traced to them at all); "
                     f"the plateau is the current stimulus's ceiling, not the DUT's")
    elif inv.unreachable_candidates:
        inv.recommended_action = ACTION_ESCALATE_TO_HUMAN
        inv.escalation_required = True
        inv.basis = (f"{len(inv.unreachable_candidates)} of {inv.holes_examined} bins are "
                     f"claimed structurally unreachable and are adequately sampled; only the "
                     f"design owner can confirm that, and generating another testcase cannot")
    else:
        inv.recommended_action = NO_HOLES_TO_INVESTIGATE
        inv.basis = (f"all {inv.holes_examined} bins were adequately sampled but carry no "
                     f"recognised root-cause classification, so this plateau has no computed "
                     f"explanation -- see each verdict's own basis")
    return inv


# --------------------------------------------------------------------------
# Section 90: oscillation / no-progress over both real fingerprints
# --------------------------------------------------------------------------
@dataclass
class OscillationFindings:
    """Both of section 90's fingerprints, over the two real stores that already
    carry them."""
    oscillating: bool
    repeat_failure: Dict[str, Any] = field(default_factory=dict)
    repeat_fix_revert: List[Dict[str, Any]] = field(default_factory=list)
    fingerprints: List[str] = field(default_factory=list)
    repeat_threshold: int = DEFAULT_OSCILLATION_REPEAT_THRESHOLD

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def detect_oscillation(*, debug_loop_entries: Optional[List[Dict[str, Any]]] = None,
                       fix_reverts: Optional[List[Any]] = None,
                       repeat_threshold: int = DEFAULT_OSCILLATION_REPEAT_THRESHOLD
                       ) -> OscillationFindings:
    """Section 90's two fingerprints, combined.

      * **repeat-failure** -- the same `(failing_stage, target_fail_edge)` pair
        recurring in the Blackboard `debug_loop_history` topic. Computed by
        `loop_contract.detect_oscillation_from_debug_loop_history()`, called
        rather than copied: there must be exactly one definition of that
        fingerprint in this codebase.
      * **repeat-fix-revert** -- a regression pattern that went
        FAIL -> PASS -> FAIL more than once, from `trend_analysis.
        detect_verdict_oscillation()`. Its `FLAKY_SAME_SHA` case is already
        excluded there (one commit that both passed and failed is an
        intermittent test, not the loop undoing its own work), so this function
        honours that module's `oscillating` flag rather than re-deciding it.

    Either fingerprint alone is enough. They are independent evidence of the
    same failure mode -- a loop repeating an action that is not working -- and
    requiring both would mean a project with no regression evidence database
    could never report oscillation at all."""
    repeat_failure = detect_oscillation_from_debug_loop_history(
        debug_loop_entries or [], repeat_threshold=repeat_threshold)
    reverts = []
    for o in (fix_reverts or []):
        reverts.append(o.to_dict() if hasattr(o, "to_dict") else dict(o))
    fingerprints: List[str] = []
    if repeat_failure.get("oscillating"):
        fingerprints.extend(f"REPEAT_FAILURE:{k}"
                            for k in sorted(repeat_failure.get("repeated_fingerprints") or {}))
    fingerprints.extend(f"REPEAT_FIX_REVERT:{o.get('pattern')}"
                        for o in reverts if o.get("oscillating"))
    return OscillationFindings(
        oscillating=bool(fingerprints),
        repeat_failure=repeat_failure,
        repeat_fix_revert=reverts,
        fingerprints=fingerprints,
        repeat_threshold=repeat_threshold,
    )


# --------------------------------------------------------------------------
# The whole classification over one real project
# --------------------------------------------------------------------------
@dataclass
class LoopConvergenceReport:
    """Sections 88-90 for one project, from its own evidence on disk."""
    root: str
    available: bool
    metric: str
    convergence: Dict[str, Any] = field(default_factory=dict)
    oscillation: Dict[str, Any] = field(default_factory=dict)
    plateau_investigation: Optional[Dict[str, Any]] = None
    loop_state: Optional[str] = None
    verdict: str = UNKNOWN
    sources: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def classify_loop_convergence(root, *,
                              cfg: Optional[Dict[str, Any]] = None,
                              points: Optional[List[ProgressPoint]] = None,
                              holes: Optional[List[Dict[str, Any]]] = None,
                              debug_loop_entries: Optional[List[Dict[str, Any]]] = None,
                              fix_reverts: Optional[List[Any]] = None,
                              db_path=None,
                              metric: str = COVERAGE_PERCENT_METRIC,
                              **classifier_kwargs: Any) -> LoopConvergenceReport:
    """Sections 88-90 over one real project, read from its own stores.

    The series comes from the REAL evidence database via
    `trend_analysis.daily_rollup()` unless a caller supplies `points`
    (the tests do, and so does any caller that already has a series in hand).
    The database is opened READ-ONLY, exactly as `trend_analysis.trend_report()`
    opens it: this classification must never create a database that does not
    exist, migrate one that does, or block a concurrently-running `lsf-watch`
    writer.

    Supplying `points` means this function reads NO database at all, so the
    repeat-fix-revert fingerprint is not derived either -- such a caller passes
    `fix_reverts` (whatever `trend_analysis.detect_verdict_oscillation()`
    returned) if it wants that half. Deriving one half from a caller's series
    and the other from a database the caller did not ask to be read would make
    the two halves describe different runs.

    **An oscillation fingerprint OVERRIDES the series verdict.** A coverage
    curve can climb steadily while the loop repeatedly re-breaks the same
    regression pattern -- the metric and the fingerprint are measuring different
    things, and the fingerprint is direct evidence of the loop undoing its own
    work, which is the more urgent and more specific fact. The series verdict is
    kept in `convergence` either way, so nothing is hidden by the override.

    Nothing here writes. `plateau_investigation` is present only when the final
    verdict is PLATEAU or NO_PROGRESS and real holes were supplied; it reports
    which bins would need escalation and names the real escalator, and takes
    that path itself for none of them."""
    from . import trend_analysis as ta

    root = Path(root)
    sources: Dict[str, Any] = {}
    reason = ""
    fix_reverts = list(fix_reverts or [])

    if points is None:
        from . import evidence_db as _evidence_db
        path = Path(db_path) if db_path else _evidence_db.default_db_path(root)
        sources["evidence_db"] = str(path)
        if not Path(path).exists():
            points = []
            reason = NO_EVIDENCE_DATABASE
        else:
            try:
                store = _evidence_db.EvidenceStore(path, read_only=True)
            except Exception as exc:
                points = []
                reason = f"{NO_EVIDENCE_DATABASE}: {type(exc).__name__}: {exc}"
            else:
                try:
                    daily = ta.daily_rollup(store)
                    points = points_from_daily_rollup(daily, metric=metric)
                    fix_reverts = fix_reverts or ta.detect_verdict_oscillation(
                        store, min_cycles=DEFAULT_OSCILLATION_REPEAT_THRESHOLD)
                finally:
                    store.close()
                sources["daily_points"] = len(daily)
                if not points:
                    reason = NO_COVERAGE_SAMPLES
    else:
        sources["series"] = "caller-supplied"

    sources["series_points"] = len(points or [])
    verdict = classify_convergence(points or [], metric=metric, **classifier_kwargs)
    if verdict.verdict == UNKNOWN and reason:
        verdict.reason = reason

    osc = detect_oscillation(debug_loop_entries=debug_loop_entries,
                             fix_reverts=fix_reverts)

    final = verdict.verdict
    final_state = verdict.loop_state
    if osc.oscillating:
        final = OSCILLATING
        state = VERDICT_TO_LOOP_STATE[OSCILLATING]
        final_state = state.value if state else None

    investigation = None
    if final in (PLATEAU, NO_PROGRESS) and holes:
        investigation = investigate_plateau(root, holes, cfg=cfg, db_path=db_path).to_dict()

    return LoopConvergenceReport(
        root=str(root),
        available=bool(points),
        metric=metric,
        convergence=verdict.to_dict(),
        oscillation=osc.to_dict(),
        plateau_investigation=investigation,
        loop_state=final_state,
        verdict=final,
        sources=sources,
        reason=reason or verdict.reason,
    )


def render_convergence_report_text(report: Dict[str, Any]) -> str:
    """Human-readable rendering for the CLI."""
    conv = report.get("convergence") or {}
    osc = report.get("oscillation") or {}
    lines = [f"DV Agent Harness L5 -- loop convergence ({report.get('root')})", ""]
    lines.append(f"VERDICT        {report.get('verdict')}"
                 + (f"  -> LoopState {report.get('loop_state')}"
                    if report.get("loop_state") else "  (no LoopState claim)"))
    lines.append(f"metric         {report.get('metric')}")
    lines.append(f"series verdict {conv.get('verdict')} -- {conv.get('reason')}")
    if conv.get("window_labels"):
        pairs = ", ".join(f"{lbl}={val}" for lbl, val in
                          zip(conv.get("window_labels") or [], conv.get("window_values") or []))
        lines.append(f"window         {pairs}")
        lines.append(f"deltas         {conv.get('deltas')}  net {conv.get('net_delta')}")
        lines.append(f"reversals      {conv.get('significant_reversals')}   "
                     f"flat run {conv.get('flat_run_samples')} samples")
    lines += ["", f"OSCILLATION    {'YES' if osc.get('oscillating') else 'no'}"]
    for fp in osc.get("fingerprints") or []:
        lines.append(f"  - {fp}")
    for o in osc.get("repeat_fix_revert") or []:
        lines.append(f"  - {o.get('pattern')}: {o.get('fix_revert_cycles')} fix-revert cycle(s) "
                     f"[{o.get('classification')}]")
    inv = report.get("plateau_investigation")
    lines += ["", "PLATEAU INVESTIGATION"]
    if not inv:
        lines.append("- not performed (verdict is not PLATEAU/NO_PROGRESS, or no holes supplied)")
    else:
        lines.append(f"- {inv['holes_examined']} holes examined: {inv['by_classification']}")
        lines.append(f"- recommended action: {inv['recommended_action']}")
        lines.append(f"  {inv['basis']}")
        if inv.get("escalation_required"):
            lines.append(f"  escalate with: {inv['escalator']} "
                         f"(bins {inv['unreachable_candidates']})")
    return "\n".join(lines)
