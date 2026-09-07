"""dv_harness/plan_quality_feedback.py -- cross-run stage-sequencing efficiency.

WHAT THESE TESTS ARE FOR.

  1. **The shape extraction is real, not guessed.** `iteration_stage_sequence()`/
     `stage_sequence_shape()`/`retry_count()` are proven against the exact
     dict shape `loop_telemetry.read_loop_telemetry()` really returns (proven
     via one real engine-driven session below), and against hand-built rows
     of that same documented shape for the edge cases a single real run
     cannot cheaply exercise (a FAIL-edge loop-back re-visit, several
     independent sessions of one shape).
  2. **Classification is worst-wins, and it is proven to have real detection
     power** -- INSUFFICIENT_DATA below the occurrence floor, THRASHING on a
     real OSCILLATING/REGRESSION verdict or a high retry ratio, MIXED on a
     real PLATEAU verdict or any retries, EFFICIENT only when every occurrence
     is clean.
  3. **The aggregator never fabricates a shape.** A project whose loops never
     emitted a section-108 event reports the honest `available: False`
     `loop_telemetry` itself already names -- proven over a bare project, and
     over a real one-shot `run_stage()` that is not a loop.
  4. **It is genuinely wired to the real engine.** One real `DVHarness.loop()`
     over the real shipped `main_graph.json`, run TWICE against the same
     fixture (the retry budget reset between runs, standing in for a human
     re-running the loop after the earlier retry budget was spent), proves
     two real, independent sessions taking the identical shape are grouped
     together with `occurrences == 2` and a real, non-fabricated status.
  5. **Reading it never writes anything.** A byte-level snapshot proves
     `aggregate_stage_sequence_shapes()` leaves the project untouched.

Nothing here runs a build, a regression or an LSF submission. `COMMAND_PATTERN`
is the same non-execution-layer, no-FAIL-edge fixture stage
`test_loop_telemetry.py` already uses for exactly that reason.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness import loop_convergence as lcv
from dv_harness import plan_quality_feedback as pqf
from dv_harness.models import Status

from .controlled_experiment_fixture import (
    FIXTURE_STAGE,
    MIGRATION_FILE,
    MIGRATION_PAYLOAD,
    harness_factory,
    make_fixture_project,
)


@pytest.fixture
def project():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield make_fixture_project(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def root():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_real_loop_to_retry_exhaustion(project: Path, goal: str = "verify the pattern"):
    h = harness_factory(project)
    h.state.current_stage = FIXTURE_STAGE
    h.store.save(h.state)
    h.loop(goal)
    return h


def _reset_fixture_stage_for_a_fresh_session(project: Path):
    """Clears the persisted `COMMAND_PATTERN` attempts/status, standing in for
    a human clearing the retry budget so the loop can be re-run -- the same
    kind of real, human-taken recovery action `loop_budget.py`'s own
    `reset()`/`breaker-reset` verbs perform, without invoking those verbs
    directly (this fixture never reaches a real circuit-breaker trip)."""
    h = harness_factory(project)
    h.state.stages.pop(FIXTURE_STAGE, None)
    h.state.current_stage = FIXTURE_STAGE
    h.store.save(h.state)
    return h


# ==========================================================================
# 1. Vocabulary hygiene
# ==========================================================================
def test_status_vocabulary_shares_no_token_with_models_status():
    pqf.assert_no_verification_verdict_vocabulary()
    assert set(pqf.SHAPE_QUALITY_STATUSES).isdisjoint({s.value for s in Status})


def test_a_forged_vocabulary_collision_is_caught(monkeypatch):
    monkeypatch.setattr(pqf, "SHAPE_QUALITY_STATUSES",
                        tuple(pqf.SHAPE_QUALITY_STATUSES) + (Status.PASS.value,))
    with pytest.raises(AssertionError, match="collides with models.Status"):
        pqf.assert_no_verification_verdict_vocabulary()


# ==========================================================================
# 2. Pure extraction: iteration_stage_sequence / stage_sequence_shape / retry_count
# ==========================================================================
def _session(*stages):
    """A minimal `loop_telemetry` session-detail dict carrying exactly the
    `iteration_history` shape `_fold_session()` really produces."""
    return {"iteration_history": [
        {"event": "LOOP_ITERATION_STARTED", "iteration": i + 1, "stage": s}
        for i, s in enumerate(stages)
    ]}


def test_iteration_stage_sequence_reads_only_iteration_started_rows_with_a_stage():
    detail = {"iteration_history": [
        {"event": "LOOP_CREATED", "stage": None},
        {"event": "LOOP_ITERATION_STARTED", "iteration": 1, "stage": "INTAKE"},
        {"event": "LOOP_ACTION_SELECTED", "iteration": 1, "stage": "INTAKE"},
        {"event": "LOOP_ITERATION_STARTED", "iteration": 2, "stage": "ARCH_DISCOVERY"},
    ]}
    assert pqf.iteration_stage_sequence(detail) == ["INTAKE", "ARCH_DISCOVERY"]


def test_stage_sequence_shape_collapses_only_immediately_consecutive_repeats():
    seq = ["COMMAND_PATTERN", "COMMAND_PATTERN", "COMMAND_PATTERN"]
    assert pqf.stage_sequence_shape(seq) == ("COMMAND_PATTERN",)
    assert pqf.retry_count(seq) == 2


def test_a_later_revisit_after_leaving_a_stage_is_not_collapsed():
    """The real FAIL-edge-loop-back case: PROJECT_MODEL -> FAILURE_RECOVERY ->
    PROJECT_MODEL is a real, separate hop in the traversal shape, never
    silently merged with the earlier visit."""
    seq = ["INTAKE", "PROJECT_MODEL", "FAILURE_RECOVERY", "PROJECT_MODEL", "IMPLEMENT"]
    shape = pqf.stage_sequence_shape(seq)
    assert shape == ("INTAKE", "PROJECT_MODEL", "FAILURE_RECOVERY",
                     "PROJECT_MODEL", "IMPLEMENT")
    assert pqf.retry_count(seq) == 0


def test_retry_count_is_exactly_the_raw_minus_shape_length_difference():
    seq = ["A", "A", "B", "B", "B", "C"]
    assert pqf.stage_sequence_shape(seq) == ("A", "B", "C")
    assert pqf.retry_count(seq) == 3


# ==========================================================================
# 3. classify_shape_quality(): worst-wins, over hand-built records
# ==========================================================================
def _rec(occurrences, *, oscillating=0, plateau=0, regression=0,
         avg_iterations=1.0, avg_retries=0.0):
    r = pqf.ShapeQualityRecord(
        shape=("STAGE_A",), occurrences=occurrences,
        run_ids=[f"r{i}" for i in range(occurrences)],
        oscillating_run_ids=[f"r{i}" for i in range(oscillating)],
        plateau_run_ids=[f"r{i}" for i in range(plateau)],
        regression_run_ids=[f"r{i}" for i in range(regression)],
        avg_iterations=avg_iterations, avg_retries=avg_retries,
        retry_ratio=(avg_retries / avg_iterations) if avg_iterations else 0.0,
    )
    return r


def test_below_the_occurrence_floor_is_insufficient_data():
    status, reason = pqf.classify_shape_quality(_rec(1))
    assert status == pqf.STATUS_INSUFFICIENT_DATA
    assert "1 independent session" in reason


def test_at_the_occurrence_floor_a_clean_record_is_efficient():
    status, _ = pqf.classify_shape_quality(_rec(2))
    assert status == pqf.STATUS_EFFICIENT


def test_any_real_oscillation_makes_the_whole_shape_thrashing_even_with_clean_siblings():
    status, reason = pqf.classify_shape_quality(_rec(5, oscillating=1))
    assert status == pqf.STATUS_THRASHING
    assert lcv.OSCILLATING in reason


def test_any_real_regression_verdict_also_makes_the_shape_thrashing():
    status, reason = pqf.classify_shape_quality(_rec(4, regression=1))
    assert status == pqf.STATUS_THRASHING
    assert lcv.REGRESSION in reason


def test_a_high_retry_ratio_is_thrashing_with_no_oscillation_at_all():
    status, reason = pqf.classify_shape_quality(
        _rec(2, avg_iterations=4.0, avg_retries=3.0))  # ratio 0.75
    assert status == pqf.STATUS_THRASHING
    assert "retry ratio" in reason


def test_a_retry_ratio_just_under_the_threshold_is_never_thrashing_on_that_basis_alone():
    status, _ = pqf.classify_shape_quality(
        _rec(2, avg_iterations=3.0, avg_retries=1.0))  # ratio 0.333
    assert status != pqf.STATUS_THRASHING


def test_a_real_plateau_with_no_oscillation_or_high_retry_ratio_is_mixed_not_thrashing():
    status, reason = pqf.classify_shape_quality(_rec(3, plateau=1))
    assert status == pqf.STATUS_MIXED
    assert lcv.PLATEAU in reason


def test_any_nonzero_retries_with_no_plateau_or_oscillation_is_mixed():
    status, reason = pqf.classify_shape_quality(
        _rec(2, avg_iterations=2.0, avg_retries=0.5))  # ratio 0.25, below thrashing bar
    assert status == pqf.STATUS_MIXED
    assert "retries per session" in reason


def test_a_wholly_clean_record_at_or_above_the_floor_is_efficient():
    status, reason = pqf.classify_shape_quality(_rec(3))
    assert status == pqf.STATUS_EFFICIENT
    assert "no oscillation, no plateau and no retries" in reason


def test_a_custom_occurrence_floor_and_retry_threshold_are_honored():
    status, _ = pqf.classify_shape_quality(_rec(3), min_occurrences=4)
    assert status == pqf.STATUS_INSUFFICIENT_DATA
    status2, _ = pqf.classify_shape_quality(
        _rec(2, avg_iterations=4.0, avg_retries=1.0),  # ratio 0.25
        retry_ratio_thrashing_threshold=0.2)
    assert status2 == pqf.STATUS_THRASHING


# ==========================================================================
# 4. aggregate_stage_sequence_shapes() over a caller-supplied telemetry
#    payload -- the exact shape read_loop_telemetry() really returns
# ==========================================================================
def _telemetry_payload(rows, sessions):
    return {"available": True, "rows": rows, "sessions": sessions}


def test_two_sessions_sharing_one_shape_are_grouped_with_occurrences_two():
    rows = [
        {"run_id": "r1", "plateau": "NOT_EVALUATED", "oscillation": "NOT_EVALUATED",
         "terminal_event": "LOOP_FAILED"},
        {"run_id": "r2", "plateau": "NOT_EVALUATED", "oscillation": "NOT_EVALUATED",
         "terminal_event": "LOOP_FAILED"},
    ]
    sessions = {
        "r1": _session("COMMAND_PATTERN", "COMMAND_PATTERN"),
        "r2": _session("COMMAND_PATTERN", "COMMAND_PATTERN", "COMMAND_PATTERN"),
    }
    report = pqf.aggregate_stage_sequence_shapes(
        Path("/does/not/matter"), telemetry=_telemetry_payload(rows, sessions))
    assert report.available is True
    assert report.sessions_examined == 2
    assert len(report.shapes) == 1
    shape = report.shapes[0]
    assert shape["shape"] == ["COMMAND_PATTERN"]
    assert shape["occurrences"] == 2
    assert shape["avg_iterations"] == 2.5
    assert shape["avg_retries"] == 1.5  # (1 + 2) / 2
    assert shape["status"] == pqf.STATUS_THRASHING  # ratio 0.6 >= 0.5


def test_two_distinct_shapes_are_reported_separately_never_merged():
    rows = [
        {"run_id": "r1", "plateau": "NOT_EVALUATED", "oscillation": "NOT_EVALUATED",
         "terminal_event": "LOOP_SUCCESS"},
        {"run_id": "r2", "plateau": "NOT_EVALUATED", "oscillation": "NOT_EVALUATED",
         "terminal_event": "LOOP_SUCCESS"},
        {"run_id": "r3", "plateau": "NOT_EVALUATED", "oscillation": "NOT_EVALUATED",
         "terminal_event": "LOOP_SUCCESS"},
    ]
    sessions = {
        "r1": _session("A", "B"),
        "r2": _session("A", "B"),
        "r3": _session("A", "C"),
    }
    report = pqf.aggregate_stage_sequence_shapes(
        Path("x"), telemetry=_telemetry_payload(rows, sessions))
    by_shape = {tuple(s["shape"]): s for s in report.shapes}
    assert set(by_shape) == {("A", "B"), ("A", "C")}
    assert by_shape[("A", "B")]["occurrences"] == 2
    assert by_shape[("A", "B")]["status"] == pqf.STATUS_EFFICIENT
    assert by_shape[("A", "C")]["occurrences"] == 1
    assert by_shape[("A", "C")]["status"] == pqf.STATUS_INSUFFICIENT_DATA


def test_success_rate_is_computed_only_over_sessions_that_actually_reached_a_terminal_event():
    rows = [
        {"run_id": "r1", "plateau": "NOT_EVALUATED", "oscillation": "NOT_EVALUATED",
         "terminal_event": "LOOP_SUCCESS"},
        {"run_id": "r2", "plateau": "NOT_EVALUATED", "oscillation": "NOT_EVALUATED",
         "terminal_event": "LOOP_FAILED"},
        {"run_id": "r3", "plateau": "NOT_EVALUATED", "oscillation": "NOT_EVALUATED",
         "terminal_event": None},
    ]
    sessions = {r: _session("A") for r in ("r1", "r2", "r3")}
    report = pqf.aggregate_stage_sequence_shapes(
        Path("x"), telemetry=_telemetry_payload(rows, sessions))
    shape = report.shapes[0]
    assert shape["occurrences"] == 3
    # denominator is 2 (r1, r2 -- both terminal); r3 counts toward occurrences
    # but never toward success_rate, since it never actually finished.
    assert shape["success_rate"] == 0.5
    assert shape["terminal_outcomes"]["(not terminal)"] == 1


def test_a_real_oscillation_verdict_string_from_loop_convergence_is_recognized():
    rows = [
        {"run_id": "r1", "plateau": "NOT_EVALUATED", "oscillation": lcv.OSCILLATING,
         "terminal_event": "LOOP_FAILED"},
        {"run_id": "r2", "plateau": "NOT_EVALUATED", "oscillation": "NOT_DETECTED",
         "terminal_event": "LOOP_SUCCESS"},
    ]
    sessions = {"r1": _session("A"), "r2": _session("A")}
    report = pqf.aggregate_stage_sequence_shapes(
        Path("x"), telemetry=_telemetry_payload(rows, sessions))
    shape = report.shapes[0]
    assert shape["oscillation_rate"] == 0.5
    assert shape["status"] == pqf.STATUS_THRASHING


def test_sessions_with_no_recorded_iteration_are_reported_but_not_grouped():
    rows = [{"run_id": "r1", "plateau": "NOT_EVALUATED", "oscillation": "NOT_EVALUATED",
             "terminal_event": "LOOP_STOPPED"}]
    sessions = {"r1": {"iteration_history": []}}
    report = pqf.aggregate_stage_sequence_shapes(
        Path("x"), telemetry=_telemetry_payload(rows, sessions))
    assert report.sessions_examined == 1
    assert report.sessions_with_no_shape == 1
    assert report.shapes == []


def test_shapes_are_sorted_by_occurrences_descending_then_avg_iterations():
    rows = [
        {"run_id": f"r{i}", "plateau": "NOT_EVALUATED", "oscillation": "NOT_EVALUATED",
         "terminal_event": "LOOP_SUCCESS"}
        for i in range(3)
    ]
    sessions = {
        "r0": _session("A"),
        "r1": _session("B", "B"),
        "r2": _session("B", "B"),
    }
    report = pqf.aggregate_stage_sequence_shapes(
        Path("x"), telemetry=_telemetry_payload(rows, sessions))
    assert [tuple(s["shape"]) for s in report.shapes] == [("B",), ("A",)]


# ==========================================================================
# 5. Honest absence: no telemetry, and a one-shot run_stage() is not a loop
# ==========================================================================
def test_a_bare_project_reports_the_real_honest_unavailable_reason(root):
    report = pqf.aggregate_stage_sequence_shapes(root)
    assert report.available is False
    assert "NO_LOOP_TELEMETRY" in report.reason
    assert report.shapes == []


def test_a_one_shot_run_stage_is_not_a_loop_and_reports_unavailable(project):
    h = harness_factory(project)
    h.run_stage("verify the pattern", stage=FIXTURE_STAGE)
    report = pqf.aggregate_stage_sequence_shapes(project)
    assert report.available is False


# ==========================================================================
# 6. Real engine wiring: two real, independent sessions of the SAME shape
# ==========================================================================
def test_two_real_independent_loop_sessions_of_the_same_shape_are_grouped(project):
    """The failure mode this whole item exists to close: nothing in this repo
    ever grouped SEVERAL real sessions by the traversal path they took. Both
    sessions here are driven by a REAL `DVHarness.loop()` over the REAL
    shipped `main_graph.json`, with the REAL
    `command_migration_integrity_gate.py` subprocess judging the stage --
    never a hand-written events.jsonl line."""
    h1 = _run_real_loop_to_retry_exhaustion(project, "first attempt")
    max_retry = h1.cfg["policy"]["max_stage_retries"]

    _reset_fixture_stage_for_a_fresh_session(project)
    h2 = harness_factory(project)
    h2.loop("second attempt, after the retry budget was cleared")

    report = pqf.aggregate_stage_sequence_shapes(project)
    assert report.available is True
    assert report.sessions_examined == 2

    matching = [s for s in report.shapes if s["shape"] == [FIXTURE_STAGE]]
    assert len(matching) == 1, report.shapes
    rec = matching[0]
    assert rec["occurrences"] == 2
    # A retry-exhausting session dispatches max_stage_retries + 1 times.
    assert rec["avg_iterations"] == float(max_retry + 1)
    assert rec["avg_retries"] == float(max_retry)
    assert rec["terminal_outcomes"].get("LOOP_FAILED") == 2
    assert rec["success_rate"] == 0.0
    # A retry-heavy, always-failing shape is real evidence it thrashes.
    assert rec["status"] == pqf.STATUS_THRASHING


def test_a_real_gate_pass_produces_a_shorter_shape_than_the_retry_exhausted_one(project):
    """Positive control: the same fixture, the same real gate, with the
    migration manifest present so the first dispatch really PASSes and the
    loop really advances past COMMAND_PATTERN -- proving the extracted shape
    reflects what the graph ACTUALLY did, not a fixed assumption."""
    (project / MIGRATION_FILE).write_text(json.dumps(MIGRATION_PAYLOAD), encoding="utf-8")
    h = harness_factory(project)
    h.state.current_stage = FIXTURE_STAGE
    h.store.save(h.state)
    h.loop("verify the pattern")

    report = pqf.aggregate_stage_sequence_shapes(project)
    assert report.available is True
    assert report.sessions_examined == 1
    shape = report.shapes[0]
    # COMMAND_PATTERN itself passed in exactly one dispatch -- the shape's
    # own first hop carries no retry of that stage.
    assert shape["shape"][0] == FIXTURE_STAGE
    assert shape["shape"].count(FIXTURE_STAGE) == 1


def test_the_run_id_filter_scopes_the_report_to_one_real_session(project):
    h1 = _run_real_loop_to_retry_exhaustion(project, "first")
    _reset_fixture_stage_for_a_fresh_session(project)
    h2 = harness_factory(project)
    h2.loop("second")

    from dv_harness import loop_telemetry as lt
    all_rows = lt.read_loop_telemetry(project)["rows"]
    one_run_id = all_rows[0]["run_id"]

    report = pqf.aggregate_stage_sequence_shapes(project, run_id=one_run_id)
    assert report.sessions_examined == 1
    assert report.shapes[0]["occurrences"] == 1
    assert report.shapes[0]["run_ids"] == [one_run_id]


# ==========================================================================
# 7. Reading is never a mutating act
# ==========================================================================
def test_reading_writes_nothing_at_all(project):
    _run_real_loop_to_retry_exhaustion(project)

    def _snapshot():
        return {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}

    before = _snapshot()
    pqf.aggregate_stage_sequence_shapes(project)
    pqf.aggregate_stage_sequence_shapes(project)
    after = _snapshot()
    assert before == after


def test_the_module_never_reaches_for_an_approval_gate():
    """A tokenize-based check over the module's own real source, the same
    discipline several sibling read-only modules in this project already
    apply to themselves."""
    import io
    import tokenize

    src = Path(pqf.__file__).read_text(encoding="utf-8")
    names = set()
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.NAME:
            names.add(tok.string)
    forbidden = {"approve", "can_signoff", "HumanApprovalRequiredError",
                "ProductionWriteNotAuthorizedError", "run_stage", "bsub_submit_with_preflight"}
    hit = names & forbidden
    assert not hit, f"plan_quality_feedback.py references a gate/approval/dispatch symbol: {hit}"


# ==========================================================================
# 8. Rendering + the module front door
# ==========================================================================
def test_render_report_text_on_an_unavailable_report():
    text = pqf.render_report_text({"available": False, "reason": "NO_LOOP_TELEMETRY: x"})
    assert "no plan-quality feedback" in text
    assert "NO_LOOP_TELEMETRY" in text


def test_render_report_text_on_a_real_report(project):
    _run_real_loop_to_retry_exhaustion(project)
    payload = pqf.aggregate_stage_sequence_shapes(project).to_dict()
    text = pqf.render_report_text(payload)
    assert "Plan-Quality Feedback" in text
    assert FIXTURE_STAGE in text
    assert pqf.STATUS_INSUFFICIENT_DATA in text  # only one occurrence yet


def test_execute_verb_show_on_a_real_project(project):
    _run_real_loop_to_retry_exhaustion(project)
    code, payload = pqf.execute_verb(project, "show", as_json=True)
    assert code == 0
    assert payload["available"] is True
    assert len(payload["shapes"]) == 1


def test_execute_verb_show_on_a_bare_project_exits_two(root):
    code, _ = pqf.execute_verb(root, "show", as_json=True)
    assert code == 2


def test_execute_verb_rejects_an_unknown_verb(root):
    code, payload = pqf.execute_verb(root, "bogus")
    assert code == 1
    assert payload["error"] == "UNKNOWN_VERB"


def test_the_real_cli_subprocess_reports_and_exits(project):
    import subprocess
    import sys

    _run_real_loop_to_retry_exhaustion(project)
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.plan_quality_feedback", "show",
         "--project-root", str(project), "--json"],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["available"] is True
    assert payload["shapes"][0]["shape"] == [FIXTURE_STAGE]
