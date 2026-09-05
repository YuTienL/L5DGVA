"""Coverage hole/trend analysis plumbing (see poster-compliance audit gap:
"Coverage 詳細分析（Hole 分析/Waiver UI/趨勢圖）", 2026-08-29).

This module deliberately does NOT parse any real coverage database (UCIS,
urg HTML, or otherwise) -- per the project's Evidence Truth Rule, this repo
has no such parser, and inventing one here would be fabricated evidence.
Instead, this operates on a coverage summary that has ALREADY been reduced
to plain JSON by whatever real coverage tool the project uses (e.g. a urg
merge report converted to JSON). If no such file exists yet, there is
nothing to run this against -- that is the correct, honest state, not an
error to be papered over.

dashboard.py's GET /api/coverage wires parse_coverage_summary()/
identify_holes()/compute_coverage_trend()/render_coverage_trend_svg() up to
a real coverage-summary file and history file on disk (see that module for
the HTTP surface); append_history_sample() below is the one production write
path a coverage-producing step uses to grow that history file."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from .storage import _atomic_replace


class CoverageAnalysisError(ValueError):
    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def parse_coverage_summary(data: dict) -> dict:
    """Validates and returns a real coverage summary already reduced to plain
    JSON of shape {"categories": [{"name", "percent", "bins_total",
    "bins_hit"}, ...]}. Never silently clamps or fixes malformed input --
    raises CoverageAnalysisError with a specific reason instead."""
    categories = data.get("categories") if isinstance(data, dict) else None
    if not isinstance(categories, list) or not categories:
        raise CoverageAnalysisError(
            "MALFORMED_CATEGORY",
            {"reason": "'categories' must be a non-empty list", "data": data},
        )

    validated = []
    for entry in categories:
        if not isinstance(entry, dict) or not all(
            k in entry for k in ("name", "percent", "bins_total", "bins_hit")
        ):
            raise CoverageAnalysisError(
                "MALFORMED_CATEGORY",
                {"reason": "category missing name/percent/bins_total/bins_hit", "entry": entry},
            )
        name = entry["name"]
        percent = entry["percent"]
        bins_total = entry["bins_total"]
        bins_hit = entry["bins_hit"]

        if bins_hit > bins_total:
            raise CoverageAnalysisError(
                "BINS_HIT_EXCEEDS_TOTAL",
                {"name": name, "bins_hit": bins_hit, "bins_total": bins_total},
            )
        if not (0 <= percent <= 100):
            raise CoverageAnalysisError(
                "PERCENT_OUT_OF_RANGE",
                {"name": name, "percent": percent},
            )

        validated.append({
            "name": name,
            "percent": percent,
            "bins_total": bins_total,
            "bins_hit": bins_hit,
        })

    return {"categories": validated}


def identify_holes(parsed: dict, threshold_percent: float = 100.0) -> list:
    """Every category whose percent < threshold_percent, sorted ascending by
    percent (worst first), each annotated with bins_missing = bins_total -
    bins_hit. An empty list is a legitimate, correct result -- not an error."""
    holes = [
        {**c, "bins_missing": c["bins_total"] - c["bins_hit"]}
        for c in parsed["categories"]
        if c["percent"] < threshold_percent
    ]
    holes.sort(key=lambda c: c["percent"])
    return holes


#: The percent band inside which a coverage delta is NOISE, not a trend. Named
#: (it was an inline `0.5` until 2026-09-05) because `loop_convergence.py`'s
#: section-88 classifier needs the SAME tolerance: two modules disagreeing about
#: what counts as "flat" would let one report PLATEAU while the other reports
#: IMPROVING over the identical series.
FLAT_TREND_TOLERANCE_PERCENT = 0.5


def compute_coverage_trend(history: list) -> dict:
    """Pure function over [{"timestamp": str|number, "percent": float}, ...]
    in any order. Sorts by timestamp first, then reports delta =
    last_percent - first_percent. FLAT tolerance is
    |delta| < FLAT_TREND_TOLERANCE_PERCENT (a small, deliberately fixed
    tolerance so trivial run-to-run noise doesn't get reported as an
    IMPROVING/DECLINING trend). Requires at least 2 entries -- never guesses a
    trend from a single data point."""
    if len(history) < 2:
        raise CoverageAnalysisError(
            "INSUFFICIENT_HISTORY",
            {"reason": "at least 2 history entries are required", "count": len(history)},
        )

    ordered = sorted(history, key=lambda h: h["timestamp"])
    first_percent = ordered[0]["percent"]
    last_percent = ordered[-1]["percent"]
    delta = last_percent - first_percent

    if abs(delta) < FLAT_TREND_TOLERANCE_PERCENT:
        trend = "FLAT"
    elif delta > 0:
        trend = "IMPROVING"
    else:
        trend = "DECLINING"

    return {
        "trend": trend,
        "delta": delta,
        "first_percent": first_percent,
        "last_percent": last_percent,
    }


def render_hole_report_text(holes: list) -> str:
    """Plain-text human-readable report, one line per hole. Presentation-only
    -- no new logic beyond formatting."""
    if not holes:
        return "No coverage holes -- 100% across all reported categories."
    lines = [
        f"{h['name']}: {h['percent']}% ({h['bins_missing']}/{h['bins_total']} bins missing)"
        for h in holes
    ]
    return "\n".join(lines)


def render_coverage_trend_svg(history: list, width: int = 480, height: int = 140, margin: int = 24) -> str:
    """Hand-rolled inline SVG line chart over history (no external chart
    library -- this project has no CDN access to load one). Requires >= 2
    points, same floor as compute_coverage_trend() (a single point has no
    line to draw) -- raises CoverageAnalysisError('INSUFFICIENT_HISTORY')
    rather than silently drawing a degenerate chart. Points are plotted in
    timestamp order on a fixed 0-100 percent Y axis (not autoscaled to the
    data's own min/max), so a consistently-high-coverage run doesn't
    visually look like it swings wildly. Presentation-only: one <circle> per
    sample plus one <polyline> joining them, no new coverage logic beyond
    compute_coverage_trend()'s own sort-by-timestamp."""
    if len(history) < 2:
        raise CoverageAnalysisError(
            "INSUFFICIENT_HISTORY",
            {"reason": "at least 2 history entries are required to render a trend chart",
             "count": len(history)},
        )
    ordered = sorted(history, key=lambda h: h["timestamp"])
    n = len(ordered)
    plot_w = width - 2 * margin
    plot_h = height - 2 * margin

    def x_for(i):
        return margin + (plot_w * i / (n - 1) if n > 1 else 0)

    def y_for(percent):
        pct = max(0.0, min(100.0, percent))
        return margin + plot_h * (1 - pct / 100.0)

    points = [(x_for(i), y_for(h["percent"])) for i, h in enumerate(ordered)]
    polyline_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    circles = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" class="cov-trend-point">'
        f'<title>{h["timestamp"]}: {h["percent"]}%</title></circle>'
        for (x, y), h in zip(points, ordered)
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'class="cov-trend-svg" role="img" aria-label="Coverage trend over {n} samples">'
        f'<polyline points="{polyline_points}" fill="none" stroke="#2457a6" stroke-width="2"/>'
        f"{circles}"
        f"</svg>"
    )


def append_history_sample(history_path, percent: float, timestamp: Any = None) -> list:
    """Appends one {"timestamp","percent"} sample to the JSON array at
    history_path (creating the parent directory and starting a fresh empty
    array if neither exists yet), atomically (via storage._atomic_replace) so
    a concurrent reader (dashboard.py's GET /api/coverage polling loop) never
    observes a torn/partial write. This is the real production write path a
    coverage-producing step (a future COVERAGE_CLOSURE-stage script, or any
    tool that just reduced a fresh urg/UCIS merge report to a percent number)
    calls to grow the history compute_coverage_trend()/render_coverage_trend_svg()
    read -- never hand-edited JSON. An existing file that fails to parse or
    isn't a JSON list is treated as an empty history rather than raising --
    this is an append operation, not a validator; parse_coverage_summary()'s
    strict validation is for the summary file, not this trend log. timestamp
    defaults to time.time() (epoch seconds) when omitted. Returns the full
    updated history list."""
    path = Path(history_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list = []
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                existing = loaded
        except Exception:
            existing = []
    existing.append({"timestamp": timestamp if timestamp is not None else time.time(), "percent": percent})
    fd, tmp = tempfile.mkstemp(prefix="history.", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        _atomic_replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return existing


# ===========================================================================
# Seed strategy differentiation (2026-09-04, Section 3 item 3b)
# ===========================================================================
#
# GAP THIS CLOSES. COVERAGE_CLOSURE already required a
# `root_cause_classification` per coverage hole, from the enum
# MISSING_TEST / INSUFFICIENT_CONSTRAINT / UNREACHABLE_STIMULUS -- a real
# taxonomy that LOOKED like the "distinguish 'not enough seeds yet' from
# 'the stimulus structurally cannot reach this bin'" differentiation the
# spec asks for. Reading the gate that enforced it
# (tools/verification_flow/coverage_hole_regeneration_gate.py) showed it was
# not: all three classes were forced down the SAME remediation --
# `regenerated_testcase_ids` + `rerun_evidence` or FAIL. UNREACHABLE_STIMULUS,
# the one case where generating yet another testcase is provably the wrong
# move, was treated identically to MISSING_TEST. And nothing anywhere tracked
# how many seeds a bin had actually been given, so "hasn't run enough yet"
# was not even a representable state -- the classification was a free-text
# field checked for presence, never derived from run history.
#
# What is added here, all from REAL data this project already produces:
#   - `count_seed_attempts()`   distinct `seed` values recorded in the
#     evidence DB's `jobs` table per pattern (lsf_client.JobState.seed,
#     already captured per job and already mirrored into DuckDB by
#     regression_reporter._write_reconciliation_evidence_if_configured()).
#   - `patterns_for_coverage_id()`  the coverage_id -> PATTERN_ID linkage the
#     project's own `.dv-harness/requirements.csv` traceability registry
#     already asserts (COVERAGE_ID and PATTERN_ID are adjacent columns of
#     the same row).
#   - `classify_coverage_hole()`  the differentiated verdict, and crucially a
#     differentiated ACTION per class -- including the fourth class the enum
#     was missing, INSUFFICIENT_SEED_ATTEMPTS ("this bin has only ever seen N
#     distinct seeds; N < the project's minimum, so 'add seeds' is the
#     correct next move, not 'invent another testcase'").
#
# The UNREACHABLE_STIMULUS action routes to dv_harness/question_queue.py at
# Tier 3 (cannot-assume). That is not an arbitrary choice of destination: an
# unreachable-bin call decides whether a coverage item may be closed without
# ever being hit, which is `affects_pass_fail_verdict` AND `affects_spec_intent`
# -- two of question_queue's three hard-coded Tier-3 triggers -- and the owner
# it routes to for domain "dut" is the designer, who is the only party who can
# actually confirm the RTL cannot produce that condition.

ROOT_CAUSE_MISSING_TEST = "MISSING_TEST"
ROOT_CAUSE_INSUFFICIENT_CONSTRAINT = "INSUFFICIENT_CONSTRAINT"
ROOT_CAUSE_UNREACHABLE_STIMULUS = "UNREACHABLE_STIMULUS"
ROOT_CAUSE_INSUFFICIENT_SEED_ATTEMPTS = "INSUFFICIENT_SEED_ATTEMPTS"

ROOT_CAUSE_CLASSES = (
    ROOT_CAUSE_MISSING_TEST,
    ROOT_CAUSE_INSUFFICIENT_CONSTRAINT,
    ROOT_CAUSE_UNREACHABLE_STIMULUS,
    ROOT_CAUSE_INSUFFICIENT_SEED_ATTEMPTS,
)

ACTION_GENERATE_TESTCASE = "GENERATE_TESTCASE_AND_RERUN"
ACTION_ADJUST_CONSTRAINT = "ADJUST_CONSTRAINT_AND_RERUN"
ACTION_ADD_SEEDS = "ADD_SEEDS_AND_RERUN"
ACTION_ESCALATE_TO_HUMAN = "ESCALATE_TO_QUESTION_QUEUE"

# Which classes must be answered with a regenerated testcase + rerun. Named
# here so the enforcing gate and this module cannot drift apart on the one
# question that was miswired before.
CLASSES_REQUIRING_TEST_REGENERATION = (
    ROOT_CAUSE_MISSING_TEST,
    ROOT_CAUSE_INSUFFICIENT_CONSTRAINT,
)
CLASSES_REQUIRING_HUMAN_ESCALATION = (ROOT_CAUSE_UNREACHABLE_STIMULUS,)
CLASSES_REQUIRING_MORE_SEEDS = (ROOT_CAUSE_INSUFFICIENT_SEED_ATTEMPTS,)

# Default minimum distinct seeds a bin must have actually been given before
# "randomization has had a fair chance at it" is a defensible claim.
#
# JUSTIFICATION (and why it is a project-overridable default, not a constant
# buried in a branch): this harness reads no coverage database and therefore
# cannot compute a per-bin hit probability, so any universal number would be
# fabricated precision. What it CAN do is refuse to let a structural verdict
# ("unreachable") or an expensive one ("write another testcase") be issued
# against a bin that has barely been sampled. 20 distinct seeds is the
# smallest count at which the observed "never hit" is more informative than
# noise for a bin a constrained-random test is expected to hit
# occasionally; below it, the honest answer is "we have not tried yet".
# Override per project via config.json: `coverage.min_seed_attempts`.
DEFAULT_MIN_SEED_ATTEMPTS = 20

COVERAGE_CONFIG_KEY = "coverage"


def min_seed_attempts(cfg=None) -> int:
    if isinstance(cfg, dict):
        block = cfg.get(COVERAGE_CONFIG_KEY, cfg)
        if isinstance(block, dict):
            v = block.get("min_seed_attempts")
            if isinstance(v, int) and v > 0:
                return v
    return DEFAULT_MIN_SEED_ATTEMPTS


def count_seed_attempts(root, patterns=None, *, db_path=None) -> dict:
    """`{pattern: distinct seed count}` from the REAL `jobs` rows in the
    evidence DB. A pattern with no rows is reported as 0, never omitted --
    "this pattern has never run" and "this pattern is not in the result" must
    not look the same to a caller deciding whether to escalate.

    Degrades to all-zeros (never raises) when duckdb is missing or the DB
    does not exist: no run history is a real state, and it correctly makes
    every bin look under-sampled, which routes to "add seeds", the cheapest
    and safest of the four actions."""
    wanted = [str(p) for p in (patterns or [])]
    counts = {p: 0 for p in wanted}
    try:
        from .evidence_db import EvidenceStore, default_db_path
    except Exception:
        return counts
    path = Path(db_path) if db_path else default_db_path(Path(root))
    if not Path(path).exists():
        return counts
    try:
        with EvidenceStore(path, read_only=True) as store:
            rows = store.query(
                "SELECT pattern, COUNT(DISTINCT seed) FROM jobs "
                "WHERE pattern IS NOT NULL AND seed IS NOT NULL GROUP BY pattern")
    except Exception:
        return counts
    observed = {str(p): int(n or 0) for p, n in rows if p}
    if not wanted:
        return observed
    for p in wanted:
        counts[p] = observed.get(p, 0)
    return counts


def seed_history_available(root, *, db_path=None) -> bool:
    """True only when this project genuinely HAS run history to measure seed
    attempts against -- an evidence DB that exists and holds at least one job
    row carrying a real seed.

    This distinction is load-bearing, and a real test found why: without it,
    a project with no evidence DB (which is most projects today -- the store
    is opt-in) reports 0 seed attempts for every bin, and the "not sampled
    enough -> add seeds" rule would then fire for EVERY hole and permanently
    suppress the UNREACHABLE_STIMULUS escalation path this feature exists to
    open. Reporting "0 attempts" from a store that was never written is not
    a measurement of anything; classify_coverage_hole() therefore skips the
    seed-attempt gate entirely in that case and says so in `basis`, rather
    than issuing a verdict it has no data for."""
    try:
        from .evidence_db import EvidenceStore, default_db_path
    except Exception:
        return False
    path = Path(db_path) if db_path else default_db_path(Path(root))
    if not Path(path).exists():
        return False
    try:
        with EvidenceStore(path, read_only=True) as store:
            rows = store.query("SELECT COUNT(*) FROM jobs WHERE seed IS NOT NULL")
    except Exception:
        return False
    return bool(rows and rows[0][0])


def patterns_for_coverage_id(root, coverage_id: str, *, registry=None) -> list:
    """PATTERN_IDs the project's own traceability registry links to this
    coverage bin. Reuses change_impact.load_trace_registry() rather than
    re-parsing requirements.csv here, so both features read the registry
    through exactly one loader."""
    if registry is None:
        try:
            from .change_impact import load_trace_registry
            registry = load_trace_registry(Path(root))
        except Exception:
            registry = []
    cid = (coverage_id or "").strip().lower()
    if not cid:
        return []
    out = []
    for r in registry:
        if (r.get("COVERAGE_ID") or "").strip().lower() != cid:
            continue
        pid = (r.get("PATTERN_ID") or "").strip()
        if pid and pid not in out:
            out.append(pid)
    return out


def classify_coverage_hole(root, hole: dict, *, cfg=None, registry=None,
                            seed_counts=None, db_path=None,
                            history_available=None) -> dict:
    """The differentiated verdict for ONE coverage hole.

    `hole` is one entry of a real `coverage_hole_regeneration_gate` evidence
    payload (`coverage_id`, optional agent-supplied
    `root_cause_classification`). Returns:

      {"coverage_id", "linked_patterns", "distinct_seed_attempts",
       "min_seed_attempts", "seed_evidence_available",
       "agent_classification", "classification", "recommended_action",
       "requires_human_escalation", "basis"}

    PRECEDENCE, and why it is this way round: the SEED-ATTEMPT check runs
    BEFORE the agent's own classification is honoured for the two expensive
    classes. A bin that has genuinely only seen 3 seeds cannot support a
    claim of "structurally unreachable" or "the constraint is wrong" -- the
    evidence for either simply has not been gathered yet -- so the computed
    verdict is INSUFFICIENT_SEED_ATTEMPTS and the action is "add seeds",
    regardless of what the agent guessed. This is the specific
    "沒跑夠 -> 加 seed" branch that did not exist anywhere before.

    The agent's classification IS honoured (a) when the bin has been
    adequately sampled, and (b) always for MISSING_TEST, which is a
    structural statement about the vPlan ("no test targets this at all")
    that seed count neither supports nor refutes -- a bin no test even aims
    at will never accumulate seeds no matter how long you wait, so gating it
    on seed count would deadlock it.
    """
    coverage_id = str(hole.get("coverage_id") or "")
    agent_class = (hole.get("root_cause_classification") or "").strip().upper() or None
    linked = patterns_for_coverage_id(root, coverage_id, registry=registry)
    if seed_counts is None:
        seed_counts = count_seed_attempts(root, linked, db_path=db_path)
    if history_available is None:
        history_available = seed_history_available(root, db_path=db_path)
    attempts = sum(int(seed_counts.get(p, 0) or 0) for p in linked)
    minimum = min_seed_attempts(cfg)

    result = {
        "coverage_id": coverage_id,
        "linked_patterns": linked,
        "distinct_seed_attempts": attempts,
        "min_seed_attempts": minimum,
        "seed_history_available": bool(history_available),
        "seed_evidence_available": bool(linked) and any(seed_counts.get(p) for p in linked),
        "agent_classification": agent_class,
    }

    if not linked:
        # No pattern is traced to this bin at all. That is exactly
        # MISSING_TEST, and it is a computed conclusion, not a guess.
        result.update({
            "classification": ROOT_CAUSE_MISSING_TEST,
            "recommended_action": ACTION_GENERATE_TESTCASE,
            "requires_human_escalation": False,
            "basis": "NO_PATTERN_TRACED_TO_COVERAGE_ID_IN_REQUIREMENTS_REGISTRY",
        })
        return result

    if agent_class == ROOT_CAUSE_MISSING_TEST:
        result.update({
            "classification": ROOT_CAUSE_MISSING_TEST,
            "recommended_action": ACTION_GENERATE_TESTCASE,
            "requires_human_escalation": False,
            "basis": "AGENT_CLASSIFICATION_MISSING_TEST (seed count not applicable)",
        })
        return result

    if attempts < minimum and history_available:
        result.update({
            "classification": ROOT_CAUSE_INSUFFICIENT_SEED_ATTEMPTS,
            "recommended_action": ACTION_ADD_SEEDS,
            "requires_human_escalation": False,
            "basis": (f"ONLY_{attempts}_DISTINCT_SEEDS_RECORDED_FOR_{linked} "
                      f"(minimum {minimum}) -- randomization has not had a fair "
                      f"attempt, so neither an unreachability nor a constraint "
                      f"verdict is supportable yet"),
        })
        return result

    seed_basis = (f"{attempts} distinct seeds (>= {minimum})" if history_available
                  else "NO_SEED_RUN_HISTORY_AVAILABLE (no evidence DB rows to measure "
                       "against, so the seed-attempt check could not be performed and the "
                       "agent's own classification is accepted rather than overridden by a "
                       "measurement that does not exist)")

    if agent_class == ROOT_CAUSE_UNREACHABLE_STIMULUS:
        result.update({
            "classification": ROOT_CAUSE_UNREACHABLE_STIMULUS,
            "recommended_action": ACTION_ESCALATE_TO_HUMAN,
            "requires_human_escalation": True,
            "basis": (f"{seed_basis}: this bin is claimed structurally unreachable -- only the "
                      f"design owner can confirm that, and generating another testcase cannot"),
        })
        return result

    if agent_class == ROOT_CAUSE_INSUFFICIENT_CONSTRAINT:
        result.update({
            "classification": ROOT_CAUSE_INSUFFICIENT_CONSTRAINT,
            "recommended_action": ACTION_ADJUST_CONSTRAINT,
            "requires_human_escalation": False,
            "basis": f"{seed_basis}: the current constraints never hit this bin",
        })
        return result

    # Adequately sampled, but the agent gave no (or an unrecognised)
    # classification. Report that honestly rather than inventing one.
    result.update({
        "classification": None,
        "recommended_action": None,
        "requires_human_escalation": False,
        "basis": ("SEED_SAMPLING_ADEQUATE_BUT_NO_RECOGNISED_CLASSIFICATION_SUPPLIED "
                  f"(agent said {agent_class!r}; expected one of {list(ROOT_CAUSE_CLASSES)})"),
    })
    return result


def escalate_unreachable_stimulus(root, verdict: dict, *, store=None, now=None) -> dict:
    """Route ONE `UNREACHABLE_STIMULUS` verdict to the real question queue as
    a Tier-3 (cannot-assume) question owned by the designer.

    Idempotent by construction: `question_queue.make_question_key()` hashes
    (domain, question, context_path), and the context_path here is the
    coverage id, so re-running COVERAGE_CLOSURE for the same bin re-derives
    the same key -- and once a human has answered it, `classify_tier()`'s
    decisions-store shortcut resolves it at Tier 1 instead of asking again.
    That "asked once, never re-asked" property is the queue's own guarantee;
    this function inherits it rather than re-implementing it.

    Returns the persisted question record."""
    from .question_queue import QuestionQueueStore

    store = store or QuestionQueueStore(Path(root))
    coverage_id = verdict.get("coverage_id") or "UNKNOWN_COVERAGE_ID"
    attempts = verdict.get("distinct_seed_attempts")
    minimum = verdict.get("min_seed_attempts")
    patterns = verdict.get("linked_patterns") or []
    question = (
        f"Coverage bin {coverage_id} was never hit after {attempts} distinct seeds "
        f"(project minimum {minimum}) across pattern(s) {patterns}. Is this bin "
        f"structurally unreachable in the current DUT/RTL, or is the stimulus missing "
        f"a legal condition that should reach it?"
    )
    return store.add_question(
        domain="dut",
        question=question,
        context_path=f"coverage/{coverage_id}",
        options=[
            {"label": "STRUCTURALLY_UNREACHABLE",
             "rationale": "The RTL cannot produce this condition; the bin should be waived/excluded with design sign-off."},
            {"label": "REACHABLE_STIMULUS_GAP",
             "rationale": "The condition is legal; the stimulus/constraints must be extended to produce it."},
        ],
        recommendation="STRUCTURALLY_UNREACHABLE",
        assumption_if_unanswered=(
            "None -- this is a Tier-3 cannot-assume question: closing a coverage bin as "
            "unreachable without design confirmation changes a signoff verdict."),
        context={
            # Both are literally true for this question and are two of
            # question_queue's three hard-coded Tier-3 triggers.
            "affects_pass_fail_verdict": True,
            "affects_spec_intent": True,
            "blast_radius": "multi_regression",
            "coverage_id": coverage_id,
            "linked_patterns": patterns,
            "distinct_seed_attempts": attempts,
        },
        now=now,
    )


def escalate_unreachable_holes(root, holes, *, cfg=None, registry=None,
                                db_path=None, store=None, now=None,
                                history_available=None) -> list:
    """Classify every hole in a real `coverage_hole_regeneration_gate`
    payload and escalate the ones that genuinely need a human. Returns one
    record per hole ({"verdict", "question_id"}), so a caller can report
    exactly which bins were escalated and why."""
    out = []
    for hole in (holes or []):
        if not isinstance(hole, dict) or hole.get("waived"):
            continue
        verdict = classify_coverage_hole(root, hole, cfg=cfg, registry=registry,
                                          db_path=db_path,
                                          history_available=history_available)
        question_id = None
        if verdict.get("requires_human_escalation"):
            question_id = escalate_unreachable_stimulus(
                root, verdict, store=store, now=now).get("id")
        out.append({"verdict": verdict, "question_id": question_id})
    return out
