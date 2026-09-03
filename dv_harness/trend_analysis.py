"""dv_harness/trend_analysis.py -- the cross-run TIME dimension over the
DuckDB evidence store (2026-09-03, cross-run-trend task).

`dv_harness/evidence_db.py` records what happened in each run. This module is
the only place that asks what changed BETWEEN runs:

  1. `daily_rollup()` / `day_over_day()` -- the four daily curves (pass rate,
     coverage, DUT testcase runtime, simulator license-hours) and a real
     latest-day-vs-previous-day comparison.
  2. `detect_pattern_regressions()` + `bisect_regression_to_rtl_commit()` --
     a pattern that was PASSing against one real `git_sha` and is now FAILing
     against another, narrowed to the RTL commits actually in that range.
  3. `detect_runtime_anomalies()` -- a job that PASSED but ran far slower than
     that same pattern's own historical baseline.

Everything here READS. This module never inserts, never migrates, and never
mutates the working tree or git state -- the only subprocess it ever runs is
a read-only `git rev-list`/`git cat-file`/`git show` (see `_git()`).

WHAT "RUNTIME" MEANS HERE, precisely, because this repo has two unrelated
things by that name: this module's runtime is `JobState.runtime_seconds` --
the DUT testcase's real LSF wall-clock duration, from the `run_time` column
`lsf_client._run_bjobs()` already requests on every poll. It is NOT
`dv_harness/stage_profile.py`'s or `dv_harness/react_loop.py`'s LLM-agent
orchestration timing, which measures how long an agent deliberated and has
nothing to do with simulation. The two must never be mixed into one curve.
"""
from __future__ import annotations

import statistics
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

# Pathspecs that decide whether a commit in a regression's commit range is an
# RTL change. Kept as a real, explicit list of the SystemVerilog/Verilog
# source extensions this project's own verible parser accepts
# (`dv_harness/verible_parser.py` parses .sv/.v; .svh/.vh are their header
# forms) -- never a guess at a directory layout, which varies per project.
# Overridable per call for a project that keeps RTL somewhere specific.
DEFAULT_RTL_PATHSPECS = ("*.v", "*.sv", "*.svh", "*.vh")

# Runtime-anomaly thresholds. Defaults are deliberately conservative -- this
# detector's whole value is that it fires on a genuinely abnormal PASS, so a
# noisy default that fired on ordinary LSF host-to-host variance would get
# ignored and be worse than nothing.
DEFAULT_MIN_BASELINE_SAMPLES = 5      # fewer prior runs than this -> no verdict
DEFAULT_RATIO_THRESHOLD = 2.0         # >= 2x the pattern's own median runtime
DEFAULT_Z_THRESHOLD = 3.0             # >= 3 sigma above its own mean

# Simulator seats a single running job is modelled as holding. See
# `daily_rollup()`'s docstring for exactly what license_hours does and does
# not claim.
DEFAULT_SEATS_PER_JOB = 1.0

LICENSE_HOURS_MODEL = (
    "derived: sum(job wall-clock runtime) x seats_per_job; this harness has no "
    "feed from a real license manager (lmstat/FlexLM), so this is a consumption "
    "ESTIMATE from real measured job runtime, not a measured license checkout"
)


# --------------------------------------------------------------------------
# Daily curves
# --------------------------------------------------------------------------

@dataclass
class DailyPoint:
    """One calendar day of the four curves. Every metric is Optional and is
    None -- never 0 -- when that day has no real evidence for it, so an empty
    day is never rendered as a real 0% pass rate or 0% coverage."""
    day: str
    verdict_count: int = 0
    verdict_passed: int = 0
    pass_rate_percent: Optional[float] = None
    coverage_percent: Optional[float] = None
    coverage_sample_count: int = 0
    job_count: int = 0
    runtime_job_count: int = 0
    total_runtime_hours: Optional[float] = None
    mean_runtime_seconds: Optional[float] = None
    license_hours: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _rows_by_day(store, sql: str) -> dict:
    return {row[0]: row for row in store.query(sql) if row[0] is not None}


def daily_rollup(store, *, seats_per_job: float = DEFAULT_SEATS_PER_JOB) -> list:
    """The four requested daily curves, one `DailyPoint` per calendar day that
    has ANY evidence, oldest first.

    - **pass rate**: from `regression_verdict_history` (the append-only table;
      `regression_verdicts` is a one-row-per-pattern snapshot whose upsert
      structurally cannot answer a day-over-day question -- see
      `evidence_db.insert_regression_verdict()`). `verdict_passed / verdict_count
      * 100` for that day's real recorded verdicts.
    - **coverage**: from `coverage_samples`, bins-weighted --
      `sum(bins_hit)/sum(bins_total)*100` across every category sample ingested
      that day. Bins-weighted rather than a mean of category percents because
      the bin counts are real measured numbers and a plain mean would let a
      12-bin category outvote a 4000-bin one. Falls back to the mean of
      `percent` for a day whose samples report no usable bin totals.
    - **runtime**: from `jobs.runtime_seconds`, the real DUT testcase LSF
      wall-clock (see this module's docstring on which "runtime" this is).
    - **license hours**: `total_runtime_hours * seats_per_job`. Stated plainly
      (`LICENSE_HOURS_MODEL`): this is a DERIVED consumption estimate from real
      measured job runtime, not a reading from a license manager -- nothing in
      this harness talks to lmstat/FlexLM today. `seats_per_job` exists so a
      project that knows its own real per-job feature checkout (e.g. a
      simulator seat plus a VIP feature) can scale the estimate instead of
      being handed a hardcoded one.

    All three source tables are bucketed by their own real ingestion timestamp
    (`recorded_at`/`ingested_at`, set by the store at write time) rather than
    by any caller-supplied timestamp string -- `coverage_samples.sample_timestamp`
    in particular is deliberately free-form passthrough text (epoch float,
    ISO string, whatever the coverage tool emitted) and is not a parseable
    bucket key."""
    verdicts = _rows_by_day(store, """
        SELECT strftime(recorded_at, '%Y-%m-%d') AS day,
               count(*) AS total,
               sum(CASE WHEN verdict_passed THEN 1 ELSE 0 END) AS passed
        FROM regression_verdict_history
        GROUP BY 1
    """)
    coverage = _rows_by_day(store, """
        SELECT strftime(ingested_at, '%Y-%m-%d') AS day,
               count(*) AS samples,
               sum(bins_total) AS bins_total,
               sum(bins_hit) AS bins_hit,
               avg(percent) AS mean_percent
        FROM coverage_samples
        GROUP BY 1
    """)
    jobs = _rows_by_day(store, """
        SELECT strftime(ingested_at, '%Y-%m-%d') AS day,
               count(*) AS jobs,
               count(runtime_seconds) AS timed_jobs,
               sum(runtime_seconds) AS total_seconds,
               avg(runtime_seconds) AS mean_seconds
        FROM jobs
        GROUP BY 1
    """)

    points = []
    for day in sorted(set(verdicts) | set(coverage) | set(jobs)):
        p = DailyPoint(day=day)
        if day in verdicts:
            _, total, passed = verdicts[day]
            p.verdict_count = int(total or 0)
            p.verdict_passed = int(passed or 0)
            if p.verdict_count:
                p.pass_rate_percent = round(100.0 * p.verdict_passed / p.verdict_count, 4)
        if day in coverage:
            _, samples, bins_total, bins_hit, mean_percent = coverage[day]
            p.coverage_sample_count = int(samples or 0)
            if bins_total:
                p.coverage_percent = round(100.0 * float(bins_hit or 0) / float(bins_total), 4)
            elif mean_percent is not None:
                p.coverage_percent = round(float(mean_percent), 4)
        if day in jobs:
            _, job_count, timed, total_seconds, mean_seconds = jobs[day]
            p.job_count = int(job_count or 0)
            p.runtime_job_count = int(timed or 0)
            if timed:
                p.total_runtime_hours = round(float(total_seconds or 0.0) / 3600.0, 6)
                p.mean_runtime_seconds = round(float(mean_seconds), 4)
                p.license_hours = round(p.total_runtime_hours * float(seats_per_job), 6)
        points.append(p)
    return points


def _delta(new: Optional[float], old: Optional[float]) -> Optional[float]:
    if new is None or old is None:
        return None
    return round(new - old, 6)


def day_over_day(points: list) -> Optional[dict]:
    """Latest day vs. the day immediately before it in `points`. None when
    there are fewer than two days of evidence -- an honest "not enough
    history yet", never a comparison against a fabricated zero baseline.

    A metric whose value is missing on EITHER day yields a None delta rather
    than treating the missing side as 0."""
    if len(points) < 2:
        return None
    new, old = points[-1], points[-2]
    return {
        "latest_day": new.day,
        "previous_day": old.day,
        "pass_rate_percent": {"latest": new.pass_rate_percent, "previous": old.pass_rate_percent,
                               "delta": _delta(new.pass_rate_percent, old.pass_rate_percent)},
        "coverage_percent": {"latest": new.coverage_percent, "previous": old.coverage_percent,
                              "delta": _delta(new.coverage_percent, old.coverage_percent)},
        "total_runtime_hours": {"latest": new.total_runtime_hours,
                                 "previous": old.total_runtime_hours,
                                 "delta": _delta(new.total_runtime_hours, old.total_runtime_hours)},
        "license_hours": {"latest": new.license_hours, "previous": old.license_hours,
                           "delta": _delta(new.license_hours, old.license_hours)},
    }


# --------------------------------------------------------------------------
# Regression detection + bisect to an RTL commit
# --------------------------------------------------------------------------

@dataclass
class PatternRegression:
    """One real PASS -> FAIL transition for a single pattern, taken from two
    consecutive rows of that pattern's own `regression_verdict_history`."""
    pattern: str
    last_good_sha: Optional[str]
    last_good_at: Optional[str]
    last_good_job_id: Optional[int]
    first_bad_sha: Optional[str]
    first_bad_at: Optional[str]
    first_bad_job_id: Optional[int]
    bisectable: bool
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def detect_pattern_regressions(store) -> list:
    """Every pattern whose MOST RECENT verdict transition was PASS -> FAIL.

    Deliberately the most recent transition only, not every historical flip: a
    pattern that broke, was fixed, and broke again should surface the CURRENT
    breakage's commit range, not the stale one. A pattern that is currently
    passing produces nothing.

    `bisectable` is False (with a real `reason`) when the two verdicts carry no
    two DISTINCT git SHAs -- either the job never recorded one, or both ran
    against the identical source. The identical-SHA case is itself a real,
    useful signal: the same commit both passed and failed, so the cause is NOT
    an RTL change (seed, environment, license/infra flake, or a genuinely
    intermittent DUT bug) and pointing a bisect at an empty commit range would
    be a fabricated answer."""
    rows = store.query("""
        SELECT pattern, verdict_passed, job_id, git_sha, recorded_at
        FROM regression_verdict_history
        ORDER BY pattern, recorded_at, id
    """)
    by_pattern: dict = {}
    for pattern, passed, job_id, git_sha, recorded_at in rows:
        by_pattern.setdefault(pattern, []).append((bool(passed), job_id, git_sha, recorded_at))

    regressions = []
    for pattern, history in sorted(by_pattern.items()):
        if len(history) < 2 or history[-1][0]:
            continue  # no history to compare, or currently passing
        # Walk back to the last PASS before this uninterrupted FAIL streak.
        idx = len(history) - 1
        while idx > 0 and not history[idx - 1][0]:
            idx -= 1
        if history[idx - 1][0] is not True:
            continue  # never passed in recorded history -- not a regression
        good = history[idx - 1]
        bad = history[idx]
        good_sha, bad_sha = good[2], bad[2]
        if not good_sha or not bad_sha:
            bisectable, reason = False, "NO_GIT_SHA_RECORDED"
        elif good_sha == bad_sha:
            bisectable, reason = False, "SAME_GIT_SHA_PASSED_AND_FAILED"
        else:
            bisectable, reason = True, "PASS_TO_FAIL_ACROSS_DISTINCT_SHAS"
        regressions.append(PatternRegression(
            pattern=pattern,
            last_good_sha=good_sha, last_good_at=str(good[3]), last_good_job_id=good[1],
            first_bad_sha=bad_sha, first_bad_at=str(bad[3]), first_bad_job_id=bad[1],
            bisectable=bisectable, reason=reason,
        ))
    return regressions


def _git(root, args: list, timeout: int = 30) -> tuple:
    """Read-only git invocation. Returns (returncode, stdout, stderr); a
    missing git binary is (127, "", msg) rather than an exception, so a
    machine without git degrades to "cannot bisect" instead of killing the
    caller's whole trend report."""
    try:
        proc = subprocess.run(["git", "-C", str(root), *args],
                              capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        return 127, "", f"git not found on PATH: {e}"
    except subprocess.TimeoutExpired as e:
        return 124, "", f"git timed out: {e}"
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _commit_exists(root, sha: str) -> bool:
    rc, _, _ = _git(root, ["cat-file", "-e", f"{sha}^{{commit}}"])
    return rc == 0


@dataclass
class BisectResult:
    """The narrowed commit range for one regression, plus the exact real
    `git bisect` command sequence to run when a re-run is actually possible."""
    pattern: str
    status: str
    last_good_sha: Optional[str] = None
    first_bad_sha: Optional[str] = None
    candidate_commits: list = field(default_factory=list)
    identified_commit: Optional[dict] = None
    total_commits_in_range: int = 0
    bisect_plan: list = field(default_factory=list)
    detail: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def bisect_regression_to_rtl_commit(root, regression: PatternRegression, *,
                                    pathspecs=DEFAULT_RTL_PATHSPECS) -> BisectResult:
    """Narrows one `PatternRegression` to the RTL commits that can actually be
    responsible for it, using the real git history between the last-good and
    first-bad SHAs recorded against the pattern's own verdicts.

    `status` is one of:
      - `IDENTIFIED_COMMIT` -- exactly one RTL commit in the range; the
        regression IS attributable to it, no further bisection needed.
      - `CANDIDATE_RANGE` -- several RTL commits; `bisect_plan` carries the
        real `git bisect start <bad> <good>` sequence to narrow them.
      - `NO_RTL_COMMITS_IN_RANGE` -- real commits exist between the two SHAs
        but none of them touched RTL. A meaningful negative result: look at
        testbench/VIP/constraint/seed/environment changes instead, not RTL.
      - `NOT_BISECTABLE` -- the regression itself carried no two distinct SHAs
        (see `detect_pattern_regressions()`).
      - `SHA_NOT_IN_REPO` / `GIT_UNAVAILABLE` -- honest failure states; a SHA
        recorded on a job that ran against a DIFFERENT checkout than `root`
        is reported as such rather than silently producing an empty range that
        would read as "no RTL commits are responsible".

    WHAT THIS DOES NOT DO, stated plainly: it does not RUN `git bisect`. A real
    bisection has to re-run the failing testcase at each probed commit, which
    means a simulator, a license and an LSF submission per step -- none of which
    exist in a local analysis context, and which this module must not pretend
    to have done. The part that genuinely needed the cross-run database (going
    from "this pattern is failing" to "here is the exact, evidence-backed
    commit range, and here is the one commit if it narrows to one") is real and
    is what this function returns."""
    if not regression.bisectable:
        return BisectResult(pattern=regression.pattern, status="NOT_BISECTABLE",
                            last_good_sha=regression.last_good_sha,
                            first_bad_sha=regression.first_bad_sha,
                            detail=regression.reason)
    root = Path(root)
    good, bad = regression.last_good_sha, regression.first_bad_sha
    rc, _, err = _git(root, ["rev-parse", "--git-dir"])
    if rc != 0:
        return BisectResult(pattern=regression.pattern, status="GIT_UNAVAILABLE",
                            last_good_sha=good, first_bad_sha=bad, detail=err.strip())
    missing = [s for s in (good, bad) if not _commit_exists(root, s)]
    if missing:
        return BisectResult(pattern=regression.pattern, status="SHA_NOT_IN_REPO",
                            last_good_sha=good, first_bad_sha=bad,
                            detail=f"not present in {root}: {', '.join(missing)}")

    rc, all_out, err = _git(root, ["rev-list", "--reverse", f"{good}..{bad}"])
    if rc != 0:
        return BisectResult(pattern=regression.pattern, status="GIT_UNAVAILABLE",
                            last_good_sha=good, first_bad_sha=bad, detail=err.strip())
    total = len([line for line in all_out.splitlines() if line.strip()])

    rc, out, err = _git(root, ["rev-list", "--reverse", f"{good}..{bad}", "--", *pathspecs])
    if rc != 0:
        return BisectResult(pattern=regression.pattern, status="GIT_UNAVAILABLE",
                            last_good_sha=good, first_bad_sha=bad,
                            total_commits_in_range=total, detail=err.strip())

    commits = []
    for sha in [line.strip() for line in out.splitlines() if line.strip()]:
        rc2, show, _ = _git(root, ["show", "-s", "--format=%H%x1f%an%x1f%aI%x1f%s", sha])
        if rc2 == 0 and show.strip():
            full, author, when, subject = (show.strip().split("\x1f") + ["", "", ""])[:4]
        else:
            full, author, when, subject = sha, "", "", ""
        rc3, files, _ = _git(root, ["show", "--pretty=format:", "--name-only", sha, "--", *pathspecs])
        commits.append({
            "sha": full, "author": author, "authored_at": when, "subject": subject,
            "rtl_files": sorted({f.strip() for f in files.splitlines() if f.strip()}),
        })

    if not commits:
        return BisectResult(pattern=regression.pattern, status="NO_RTL_COMMITS_IN_RANGE",
                            last_good_sha=good, first_bad_sha=bad,
                            total_commits_in_range=total,
                            detail=("no commit between the last-good and first-bad SHAs touched "
                                    f"{', '.join(pathspecs)}; look at testbench/VIP/constraint/"
                                    "seed/environment changes rather than RTL"))
    if len(commits) == 1:
        return BisectResult(pattern=regression.pattern, status="IDENTIFIED_COMMIT",
                            last_good_sha=good, first_bad_sha=bad,
                            candidate_commits=commits, identified_commit=commits[0],
                            total_commits_in_range=total)
    return BisectResult(
        pattern=regression.pattern, status="CANDIDATE_RANGE",
        last_good_sha=good, first_bad_sha=bad,
        candidate_commits=commits, total_commits_in_range=total,
        bisect_plan=[
            f"git bisect start {bad} {good}",
            f"# at each probed commit, re-run pattern {regression.pattern!r} and mark the result:",
            "git bisect good   # the pattern PASSED at this commit",
            "git bisect bad    # the pattern FAILED at this commit",
            "git bisect reset",
        ],
    )


# --------------------------------------------------------------------------
# Runtime anomaly detection (passed, but abnormally slow)
# --------------------------------------------------------------------------

@dataclass
class RuntimeAnomaly:
    pattern: str
    job_id: Optional[int]
    runtime_seconds: float
    baseline_median_seconds: float
    baseline_mean_seconds: float
    baseline_stddev_seconds: Optional[float]
    baseline_sample_count: int
    ratio_to_median: float
    z_score: Optional[float]
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def detect_runtime_anomalies(store, *,
                             min_samples: int = DEFAULT_MIN_BASELINE_SAMPLES,
                             ratio_threshold: float = DEFAULT_RATIO_THRESHOLD,
                             z_threshold: float = DEFAULT_Z_THRESHOLD) -> list:
    """Jobs that PASSED but ran far slower than their own pattern's historical
    baseline -- the failure mode a pass/fail-only view is structurally blind to
    (a test that still passes while quietly taking 5x as long is real evidence
    of a DUT/testbench problem, and it is also what silently eats a
    regression's license-hours).

    Scope, deliberately narrow:
      - Only `sim_status = 'PASS'` jobs are candidates AND only PASS jobs form
        the baseline. A FAILing job's runtime is a different distribution
        entirely (an early UVM_FATAL exits fast, a hang runs to timeout), and
        mixing the two would make the baseline meaningless.
      - A job is never compared against a baseline that includes ITSELF; the
        baseline for each candidate is built from that pattern's OTHER jobs.
        Without this, one enormous outlier drags up the very median it is being
        judged against and hides itself.
      - A pattern with fewer than `min_samples` other PASS runs yields NO
        verdict at all. An "anomaly" called against two prior runs is noise,
        and reporting it would train a reader to ignore this detector.

    A job is flagged when it is at least `ratio_threshold` x the baseline
    MEDIAN (robust to the outliers this is looking for, unlike the mean) OR at
    least `z_threshold` sigma above the baseline mean. `z_score` is None when
    the baseline has zero variance (every prior run took exactly the same
    time), in which case the ratio test alone decides -- never a division by
    zero, and never a fabricated infinite z."""
    rows = store.query("""
        SELECT pattern, job_id, runtime_seconds
        FROM jobs
        WHERE sim_status = 'PASS'
          AND runtime_seconds IS NOT NULL
          AND pattern IS NOT NULL
        ORDER BY pattern, job_id
    """)
    by_pattern: dict = {}
    for pattern, job_id, runtime in rows:
        by_pattern.setdefault(pattern, []).append((job_id, float(runtime)))

    anomalies = []
    for pattern, samples in sorted(by_pattern.items()):
        if len(samples) < min_samples + 1:
            continue
        for i, (job_id, runtime) in enumerate(samples):
            baseline = [r for j, (_, r) in enumerate(samples) if j != i]
            if len(baseline) < min_samples:
                continue
            median = statistics.median(baseline)
            mean = statistics.fmean(baseline)
            stdev = statistics.stdev(baseline) if len(baseline) > 1 else 0.0
            ratio = (runtime / median) if median > 0 else float("inf")
            z = ((runtime - mean) / stdev) if stdev > 0 else None
            triggers = []
            if median > 0 and ratio >= ratio_threshold:
                triggers.append(f"RATIO_GE_{ratio_threshold}X_MEDIAN")
            if z is not None and z >= z_threshold:
                triggers.append(f"Z_SCORE_GE_{z_threshold}")
            if not triggers:
                continue
            anomalies.append(RuntimeAnomaly(
                pattern=pattern, job_id=job_id, runtime_seconds=round(runtime, 4),
                baseline_median_seconds=round(median, 4),
                baseline_mean_seconds=round(mean, 4),
                baseline_stddev_seconds=round(stdev, 4) if stdev else None,
                baseline_sample_count=len(baseline),
                ratio_to_median=round(ratio, 4) if ratio != float("inf") else None,
                z_score=round(z, 4) if z is not None else None,
                reason="+".join(triggers),
            ))
    return anomalies


# --------------------------------------------------------------------------
# One report over all three
# --------------------------------------------------------------------------

def trend_report(root, *, seats_per_job: float = DEFAULT_SEATS_PER_JOB,
                 rtl_pathspecs=DEFAULT_RTL_PATHSPECS,
                 min_samples: int = DEFAULT_MIN_BASELINE_SAMPLES,
                 ratio_threshold: float = DEFAULT_RATIO_THRESHOLD,
                 z_threshold: float = DEFAULT_Z_THRESHOLD) -> dict:
    """The whole cross-run time dimension as one JSON-serializable dict, read
    from this project's real `.dv-harness/evidence/evidence.duckdb`.

    Opens the store READ-ONLY (`EvidenceStore(read_only=True)`): this report
    must never create a database that does not exist yet, nor migrate one that
    does, nor block a concurrently-running `lsf-watch` writer. A project with
    no evidence database yet gets `{"available": False, ...}` -- the honest
    pre-first-run state, not an empty set of curves that would read as
    "measured, and there is nothing"."""
    from . import evidence_db as _evidence_db

    root = Path(root)
    db_path = _evidence_db.default_db_path(root)
    if not db_path.exists():
        return {"available": False, "db_path": str(db_path),
                "reason": "no evidence database yet -- nothing has been reconciled into it"}
    try:
        store = _evidence_db.EvidenceStore(db_path, read_only=True)
    except Exception as e:
        return {"available": False, "db_path": str(db_path), "reason": str(e)}
    try:
        points = daily_rollup(store, seats_per_job=seats_per_job)
        regressions = detect_pattern_regressions(store)
        anomalies = detect_runtime_anomalies(store, min_samples=min_samples,
                                             ratio_threshold=ratio_threshold,
                                             z_threshold=z_threshold)
    finally:
        store.close()

    bisects = [bisect_regression_to_rtl_commit(root, r, pathspecs=rtl_pathspecs).to_dict()
               for r in regressions]
    return {
        "available": True,
        "db_path": str(db_path),
        "license_hours_model": LICENSE_HOURS_MODEL,
        "seats_per_job": seats_per_job,
        "daily": [p.to_dict() for p in points],
        "day_over_day": day_over_day(points),
        "regressions": [r.to_dict() for r in regressions],
        "bisects": bisects,
        "runtime_anomalies": [a.to_dict() for a in anomalies],
    }


def render_trend_report_text(report: dict) -> str:
    """Human-readable rendering of `trend_report()` for the CLI."""
    if not report.get("available"):
        return f"trend: NO EVIDENCE DATABASE\n  {report.get('db_path')}\n  {report.get('reason')}"
    lines = [f"DV Agent Harness L5 -- cross-run trend ({report['db_path']})", ""]
    lines.append(f"{'DAY':<12}{'PASS%':>8}{'COV%':>8}{'RUN_H':>10}{'LIC_H':>10}{'JOBS':>7}")
    lines.append("-" * 55)
    for p in report["daily"]:
        def f(v, w, prec=2):
            return f"{v:>{w}.{prec}f}" if isinstance(v, (int, float)) else f"{'-':>{w}}"
        lines.append(f"{p['day']:<12}{f(p['pass_rate_percent'], 8)}{f(p['coverage_percent'], 8)}"
                     f"{f(p['total_runtime_hours'], 10, 3)}{f(p['license_hours'], 10, 3)}"
                     f"{p['job_count']:>7}")
    dod = report.get("day_over_day")
    lines += ["", "DAY OVER DAY"]
    if not dod:
        lines.append("- fewer than 2 days of evidence; no comparison possible yet")
    else:
        lines.append(f"- {dod['previous_day']} -> {dod['latest_day']}")
        for key in ("pass_rate_percent", "coverage_percent", "total_runtime_hours", "license_hours"):
            d = dod[key]["delta"]
            lines.append(f"  {key:<22} {dod[key]['previous']} -> {dod[key]['latest']}"
                         + (f"  (delta {d:+})" if d is not None else "  (delta n/a)"))
    lines += ["", "REGRESSIONS (PASS -> FAIL)"]
    if not report["regressions"]:
        lines.append("- none")
    for r, b in zip(report["regressions"], report["bisects"]):
        lines.append(f"- {r['pattern']}: {r['last_good_sha']} PASS -> {r['first_bad_sha']} FAIL "
                     f"[{r['reason']}]")
        lines.append(f"    bisect: {b['status']}"
                     + (f" -- {b['detail']}" if b.get("detail") else ""))
        if b.get("identified_commit"):
            c = b["identified_commit"]
            lines.append(f"    responsible commit: {c['sha'][:12]} {c['subject']} "
                         f"({', '.join(c['rtl_files']) or 'no rtl files listed'})")
        elif b.get("candidate_commits"):
            lines.append(f"    {len(b['candidate_commits'])} RTL candidates of "
                         f"{b['total_commits_in_range']} commits in range:")
            for c in b["candidate_commits"]:
                lines.append(f"      {c['sha'][:12]} {c['subject']}")
            for step in b.get("bisect_plan", []):
                lines.append(f"      $ {step}")
    lines += ["", "RUNTIME ANOMALIES (passed, abnormally slow)"]
    if not report["runtime_anomalies"]:
        lines.append("- none")
    for a in report["runtime_anomalies"]:
        lines.append(f"- {a['pattern']} job {a['job_id']}: {a['runtime_seconds']}s vs median "
                     f"{a['baseline_median_seconds']}s over {a['baseline_sample_count']} prior "
                     f"runs (x{a['ratio_to_median']}, z={a['z_score']}) [{a['reason']}]")
    lines += ["", f"license_hours model: {report['license_hours_model']}"]
    return "\n".join(lines)
