"""LOOP_ENGINEERING sections 107 + 108: the loop telemetry events and the GUI
Loop Engineering Center (LOOP-4, 2026-09-05).

WHAT THESE TESTS ARE FOR. Not "the vocabulary tuple has nineteen strings in it".
Before this change all nineteen section-108 names had ZERO producers anywhere in
the repo, so the five things that can actually go wrong here are:

  1. **A vocabulary with no producer.** The failure mode this whole gap WAS.
     Every event that can be produced on the real engine path is driven out of a
     REAL `DVHarness.loop()` over the REAL shipped `main_graph.json`, with the
     REAL `command_migration_integrity_gate.py` subprocess judging the stage --
     never by calling `loop_telemetry.emit()` directly. The one test that does
     call `emit()` directly is the test that it REFUSES an unknown name.
  2. **A fabricated row.** A project whose loops never emitted an event must
     report an honest empty state, and a `run_stage()` that is not a loop must
     emit nothing at all. Reading the card must not create either.
  3. **A number the GUI invented.** Every column must equal what the mechanism
     that owns it computed -- the state `loop_contract` derived, the plateau
     verdict `loop_convergence` classified over a REAL evidence database, the
     verified gain the same function `dashboard._overall_progress()` uses.
  4. **The terminal-event invariant breaking.** Exactly one of
     `TERMINAL_LOOP_EVENTS` per loop session, on every one of `loop()`'s return
     paths -- driven here through the real takeover, pause, circuit-breaker,
     retry-exhaustion and run-out-of-graph paths.
  5. **Observability becoming a mutating act, or weakening a gate.** Emitting
     LOOP_HUMAN_GATE_REQUIRED must authorize nothing, and reading the card must
     approve nothing.

Nothing here runs a build, a regression or an LSF submission. COMMAND_PATTERN is
an `implementation-route` node with no FAIL edge in the real graph, chosen for
exactly that reason: a retry-exhausted `loop()` stops deterministically instead
of walking on into BUILD/VERIFY/REGRESSION. The only stubbed thing is the agent
adapter, because the real one dispatches a `claude -p` subprocess.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness import loop_contract as lc
from dv_harness import loop_convergence as lcv
from dv_harness import loop_telemetry as lt
from dv_harness.control_plane import ControlPlane
from dv_harness.models import Stage, Status
from dv_harness.storage import StateStore

from .controlled_experiment_fixture import (
    FIXTURE_STAGE,
    MIGRATION_FILE,
    MIGRATION_PAYLOAD,
    harness_factory,
    make_fixture_project,
)
# The REAL evidence-database writers LOOP-2's own tests use -- reused rather
# than re-implemented, so a coverage day in this file is written by exactly the
# function `engine._append_coverage_history_sample()` calls.
from .test_loop_convergence import _coverage_days


@pytest.fixture
def project():
    """An isolated fixture project: the real graph, one real gate script."""
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


def _events(root: Path):
    f = Path(root) / ".dv-harness" / "events.jsonl"
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]


def _loop_event_names(root: Path):
    return [e["event"] for e in _events(root) if e.get("event") in lt.LOOP_TELEMETRY_EVENTS]


def _run_real_loop_to_retry_exhaustion(project: Path):
    """Drive the REAL DVHarness.loop() until COMMAND_PATTERN's retry budget is
    spent. The gate really runs; the stub adapter submits no evidence while
    MIGRATION_FILE is absent."""
    h = harness_factory(project)
    h.state.current_stage = FIXTURE_STAGE
    h.store.save(h.state)
    h.loop("verify the command pattern migration")
    return h


class _AlwaysOkAdapter:
    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
        from dv_harness.adapters.base import AgentResult
        return AgentResult(ok=True, text="done", raw={}, session_id=None)


def _closing_project(tmp: Path) -> Path:
    """A project a real `loop()` can actually CLOSE, which in this harness is
    only possible through SIGNOFF -- the last entry in `policy.ORDER`, and the
    one stage whose PASS `advance()` has nowhere to go from.

    Two REAL policy keys are off, each for a stated reason rather than to make
    a test pass: `require_stage_gate_evidence` is what lets a stub adapter
    reach a PASS without SIGNOFF's nine gate scripts on disk (the PASS still
    goes through the real `run_stage()`), and `require_second_pass_audit` is
    what lets the REAL `policy.can_signoff()` clear on a project that never ran
    RE_AUDIT.

    **The human approval is SATISFIED, never bypassed.** `run_stage()` turns a
    gate-passing SIGNOFF into WAIT_USER unless a real ControlPlane approval is
    on record, and that check is untouched -- `_approve_signoff()` below files
    a real approval through the real `ControlPlane.approve()`, exactly as
    `dv-harness approve SIGNOFF` does. It is also CONSUMED per PASS, so a
    second session needs a second approval; that is asserted rather than
    worked around."""
    (tmp / ".dv-harness").mkdir(parents=True, exist_ok=True)
    (tmp / ".dv-harness" / "config.json").write_text(json.dumps({"policy": {
        "require_stage_gate_evidence": False,
        "require_second_pass_audit": False,
        "max_stage_retries": 0,
    }}), encoding="utf-8")
    return tmp


def _approve_signoff(project: Path):
    """One real human approval, through the real API a human's
    `dv-harness approve SIGNOFF` goes through."""
    return ControlPlane(project).approve(
        Stage.SIGNOFF.value, note="fixture reviewer accepts this synthetic project",
        reviewer_id="test-reviewer", reviewer_confidence="HIGH")


def _run_loop_to_closed(project: Path):
    from dv_harness.engine import DVHarness
    from dv_harness.policy import ORDER
    h = DVHarness(project)
    h.adapter = _AlwaysOkAdapter()
    h.state.current_stage = ORDER[-1]
    h.store.save(h.state)
    h.loop("close the project")
    return h


# ==========================================================================
# 1. The vocabulary: section 108's own list, and its bridge to section 86
# ==========================================================================
def test_the_taxonomy_is_section_108s_nineteen_names_in_its_order():
    """Compared against a transcription of the specification's own line, not
    against itself."""
    lt.assert_events_match_section_108()
    assert len(lt.LOOP_TELEMETRY_EVENTS) == 19
    assert len(set(lt.LOOP_TELEMETRY_EVENTS)) == 19


def test_every_loop_state_has_a_decided_event_meaning_or_a_stated_reason():
    """The totality technique `loop_contract.assert_status_mapping_total()`
    uses: a LoopState added without deciding its telemetry meaning fails here
    rather than silently producing nothing."""
    lt.assert_loop_state_mapping_total()
    assert set(lt.LOOP_STATE_TO_EVENT) == set(lc.LOOP_STATE_VALUES)


def test_a_new_loop_state_without_a_decision_fails_the_totality_check(monkeypatch):
    monkeypatch.setattr(lc, "LOOP_STATE_VALUES",
                        tuple(lc.LOOP_STATE_VALUES) + ("QUANTUM_SUPERPOSITION",))
    monkeypatch.setattr(lt, "LOOP_STATE_VALUES", lc.LOOP_STATE_VALUES)
    with pytest.raises(AssertionError, match="no telemetry meaning decided"):
        lt.assert_loop_state_mapping_total()


def test_a_state_that_names_no_event_must_say_why(monkeypatch):
    """A `None` with no reason reads to a human as an oversight."""
    monkeypatch.setitem(lt.LOOP_STATE_TO_EVENT, lc.LoopState.SUCCESS.value, None)
    with pytest.raises(AssertionError, match="no stated reason"):
        lt.assert_loop_state_mapping_total()


def test_the_four_states_with_no_section_108_event_are_exactly_the_reasoned_ones():
    """CANCELLED and STALE genuinely have no producer in this harness -- and
    that is stated, not implied by absence."""
    silent = {k for k, v in lt.LOOP_STATE_TO_EVENT.items() if v is None}
    assert silent == {"READY", "VERIFYING", "CANCELLED", "STALE"}
    for state in silent:
        assert lt.loop_state_event_reason(state)
    assert "no cancel path" in lt.loop_state_event_reason("CANCELLED")


def test_columns_and_drilldown_are_section_107s_own():
    lt.assert_columns_match_section_107()
    assert [l for _, l in lt.SECTION_107_COLUMNS][0] == "Loop"
    assert len(lt.SECTION_107_DRILLDOWN_FIELDS) == 14


def test_an_event_name_outside_section_108_is_refused_not_written(root):
    """The one direct-`emit()` test in this file, and it is a refusal: an
    unrecognized name in events.jsonl would be dropped silently by the reader
    while the emitter looked like it had reported something."""
    store = StateStore(root)
    with pytest.raises(lt.LoopTelemetryEventError):
        lt.emit(store, "LOOP_VIBES_DETECTED", run_id="r1")
    assert _loop_event_names(root) == []


# ==========================================================================
# 2. The real engine path: events nobody wrote for a test
# ==========================================================================
def test_a_real_retry_exhausted_loop_emits_the_whole_iteration_family(project):
    """The failure mode this gap WAS: names with no producer. Every event here
    was written by a real `loop()` running a real gate."""
    _run_real_loop_to_retry_exhaustion(project)
    names = _loop_event_names(project)

    for expected in ("LOOP_CREATED", "LOOP_STARTED", "LOOP_ITERATION_STARTED",
                     "LOOP_ACTION_SELECTED", "LOOP_VERIFY_COMPLETED",
                     "LOOP_PROGRESS_UPDATED", "LOOP_NO_PROGRESS",
                     "LOOP_RETRY_SCHEDULED", "LOOP_BUDGET_WARNING",
                     "LOOP_BUDGET_EXHAUSTED", "LOOP_FAILED"):
        assert expected in names, f"{expected} was never produced by a real loop()"

    # One session, one id, and the iteration counter really counted iterations.
    ids = {e["run_id"] for e in _events(project)
           if e.get("event") in lt.LOOP_TELEMETRY_EVENTS}
    assert len(ids) == 1
    starts = [e for e in _events(project) if e.get("event") == "LOOP_ITERATION_STARTED"]
    assert [e["iteration"] for e in starts] == list(range(1, len(starts) + 1))
    assert len(starts) >= 2, "a retry-exhausting loop must have iterated more than once"


def test_exactly_one_terminal_event_per_loop_session(project):
    """Section 107's table is one row per session; two terminal events would be
    two contradictory answers to 'how did this end'."""
    _run_real_loop_to_retry_exhaustion(project)
    terminal = [n for n in _loop_event_names(project) if n in lt.TERMINAL_LOOP_EVENTS]
    assert terminal == ["LOOP_FAILED"]


def test_the_budget_events_carry_the_real_attempt_numbers(project):
    """A warning that does not precede exhaustion is worth nothing, and the
    numbers must be the ones `loop()` actually branched on."""
    h = _run_real_loop_to_retry_exhaustion(project)
    max_retry = h.cfg["policy"]["max_stage_retries"]
    evs = _events(project)

    warn = [e for e in evs if e.get("event") == "LOOP_BUDGET_WARNING"][-1]
    assert warn["attempts_remaining"] == 0
    assert warn["max_stage_retries"] == max_retry
    assert warn["attempts"] == max_retry, "the warning must fire on the LAST allowed retry"

    exhausted = [e for e in evs if e.get("event") == "LOOP_BUDGET_EXHAUSTED"][-1]
    assert exhausted["attempts"] > max_retry
    assert exhausted["loop_state"] == lc.LoopState.BUDGET_EXHAUSTED.value
    # Emitted AFTER the warning, never before it.
    names = _loop_event_names(project)
    assert names.index("LOOP_BUDGET_WARNING") < names.index("LOOP_BUDGET_EXHAUSTED")


def test_the_verifier_event_names_the_real_gates_not_the_agent(project):
    """Section 87: the producer does not verify its own output. What judged the
    stage is recorded from `gates.effective_stage_gates()`."""
    _run_real_loop_to_retry_exhaustion(project)
    from dv_harness.gates import effective_stage_gates
    real = [g[0] for g in effective_stage_gates(FIXTURE_STAGE, project)]

    verify = [e for e in _events(project) if e.get("event") == "LOOP_VERIFY_COMPLETED"][-1]
    assert verify["gate_ids"] == real
    assert verify["gate_count"] == len(real)
    assert verify["status"] in (Status.FAIL.value, Status.PARTIAL.value)
    assert "evaluate_stage_evidence" in verify["verifier"]


def test_no_verified_gain_is_reported_as_no_progress_not_as_converging(project):
    """Section 110's LOOP-AT-26: artifact churn without verified gain is
    no-progress. The fixture stage never passes its gate, so no iteration may
    ever report CONVERGING."""
    _run_real_loop_to_retry_exhaustion(project)
    names = _loop_event_names(project)
    assert "LOOP_NO_PROGRESS" in names
    assert "LOOP_CONVERGING" not in names

    prog = [e for e in _events(project) if e.get("event") == "LOOP_PROGRESS_UPDATED"]
    assert prog[0]["metric"] == lt.GATE_VERIFIED_STAGE_METRIC
    assert prog[0]["delta"] == 0
    assert prog[0]["total"] == len(Stage)


def test_a_real_gate_pass_is_the_positive_control_for_converging(project):
    """Without this, LOOP_NO_PROGRESS above would only prove the fixture always
    fails. Same fixture, same real gate, with the manifest present."""
    (project / MIGRATION_FILE).write_text(json.dumps(MIGRATION_PAYLOAD), encoding="utf-8")
    h = harness_factory(project)
    h.state.current_stage = FIXTURE_STAGE
    h.store.save(h.state)
    h.loop("verify the command pattern migration")

    names = _loop_event_names(project)
    assert "LOOP_CONVERGING" in names
    conv = [e for e in _events(project) if e.get("event") == "LOOP_CONVERGING"][0]
    assert conv["metric"] == lt.GATE_VERIFIED_STAGE_METRIC
    assert conv["delta"] >= 1
    assert conv["loop_state"] == lc.LoopState.CONVERGING.value


def test_a_one_shot_run_stage_is_not_a_loop_and_emits_nothing(project):
    """`run_stage()` on its own iterates nothing. A row in the Loop Engineering
    Center for it would be a loop session that never happened."""
    h = harness_factory(project)
    h.run_stage("verify the command pattern migration", stage=FIXTURE_STAGE)
    assert _loop_event_names(project) == []
    assert lt.read_loop_telemetry(project)["available"] is False


def test_a_dry_run_loop_opens_no_session(project):
    """Same reason: a dry run dispatches one stage and iterates nothing."""
    h = harness_factory(project)
    h.state.current_stage = FIXTURE_STAGE
    h.store.save(h.state)
    h.loop("verify the command pattern migration", dry_run=True)
    assert _loop_event_names(project) == []


# ==========================================================================
# 3. Every one of loop()'s return paths ends the session honestly
# ==========================================================================
def test_a_real_takeover_emits_the_human_gate_and_stops_the_session(project):
    h = harness_factory(project)
    h.state.current_stage = FIXTURE_STAGE
    h.store.save(h.state)
    ControlPlane(project).takeover(FIXTURE_STAGE, "human is driving")
    h.loop("verify the command pattern migration")

    names = _loop_event_names(project)
    assert "LOOP_HUMAN_GATE_REQUIRED" in names
    assert [n for n in names if n in lt.TERMINAL_LOOP_EVENTS] == ["LOOP_STOPPED"]
    stop = [e for e in _events(project) if e.get("event") == "LOOP_STOPPED"][-1]
    assert stop["reason"] == "TAKEOVER_ACTIVE"
    assert "release-takeover" in stop["resume_condition"]
    # It never dispatched the stage: the human override really outranked it.
    assert "LOOP_VERIFY_COMPLETED" not in names


def test_a_real_pause_stops_the_session_as_stopped_not_blocked(project):
    """PAUSED and BLOCKED are different operator situations with different
    recoveries; collapsing them would send a human to the wrong command."""
    h = harness_factory(project)
    h.state.current_stage = FIXTURE_STAGE
    h.store.save(h.state)
    ControlPlane(project).pause("waiting on a license")
    h.loop("verify the command pattern migration")

    stop = [e for e in _events(project) if e.get("event") == "LOOP_STOPPED"][-1]
    assert stop["loop_state"] == lc.LoopState.STOPPED.value
    assert "waiting on a license" in stop["reason"]
    assert "dv-harness resume" in stop["resume_condition"]
    assert "LOOP_BLOCKED" not in _loop_event_names(project)


def test_a_real_open_circuit_breaker_ends_the_session_as_blocked(project):
    """LOOP-3's breaker, tripped through its own real API, reached through the
    real `_circuit_breaker_gate()` at the top of a real `loop()` cycle."""
    from dv_harness import loop_budget as lb
    engine = lb.BudgetEngine(project, {"policy": {}})
    engine.trip_breaker("REPEATED_IDENTICAL_FAILURE",
                        "the same UVM_FATAL three times",
                        evidence={"stage": FIXTURE_STAGE})

    h = harness_factory(project)
    h.state.current_stage = FIXTURE_STAGE
    h.store.save(h.state)
    h.loop("verify the command pattern migration")

    names = _loop_event_names(project)
    assert [n for n in names if n in lt.TERMINAL_LOOP_EVENTS] == ["LOOP_BLOCKED"]
    blocked = [e for e in _events(project) if e.get("event") == "LOOP_BLOCKED"][-1]
    assert blocked["reason"] == "CIRCUIT_BREAKER_OPEN"
    assert "breaker-reset" in blocked["resume_condition"]
    assert "LOOP_VERIFY_COMPLETED" not in names, "an open breaker must stop NEW actions"


def test_a_loop_that_runs_out_of_graph_reports_loop_success(root):
    """The loop's own machine-checkable done -- `overall_status == CLOSED` --
    and the ONLY place LOOP_SUCCESS may be emitted. A per-stage PASS is
    CONVERGING, never SUCCESS."""
    p = _closing_project(root)
    _approve_signoff(p)
    h = _run_loop_to_closed(p)

    assert h.state.overall_status == Status.CLOSED.value
    names = _loop_event_names(p)
    assert [n for n in names if n in lt.TERMINAL_LOOP_EVENTS] == ["LOOP_SUCCESS"]
    succ = [e for e in _events(p) if e.get("event") == "LOOP_SUCCESS"][-1]
    assert succ["machine_checkable_done"] == "state.overall_status == CLOSED"
    # A stage PASS in the same session was CONVERGING, not SUCCESS.
    assert "LOOP_CONVERGING" in names


def test_loop_created_fires_once_and_a_later_session_reports_resumed(project):
    """Both decisions are READ out of the append-only log, never set by a flag:
    a second session on a loop that did not reach LOOP_SUCCESS is a resume."""
    h = _run_real_loop_to_retry_exhaustion(project)
    assert _loop_event_names(project).count("LOOP_CREATED") == 1
    assert "LOOP_RESUMED" not in _loop_event_names(project)

    h.state.stages[FIXTURE_STAGE]["attempts"] = 0
    h.state.current_stage = FIXTURE_STAGE
    h.store.save(h.state)
    h.loop("verify the command pattern migration, second round")

    names = _loop_event_names(project)
    assert names.count("LOOP_CREATED") == 1, "a loop is created once, not per session"
    assert "LOOP_RESUMED" in names
    resumed = [e for e in _events(project) if e.get("event") == "LOOP_RESUMED"][-1]
    assert resumed["last_terminal_event"] == "LOOP_FAILED"
    assert resumed["prior_session_count"] == 1
    # Two sessions, two run_ids, two rows.
    payload = lt.read_loop_telemetry(project)
    assert len({r["run_id"] for r in payload["rows"]}) == 2


def test_a_successful_session_is_not_reported_as_resumed_afterwards(root):
    """The negative control for LOOP_RESUMED: a loop that really closed is not
    something the next session continues. Without it, "resumed" would only
    prove the detector fires, not that it discriminates."""
    p = _closing_project(root)
    _approve_signoff(p)
    _run_loop_to_closed(p)
    assert "LOOP_SUCCESS" in _loop_event_names(p)

    # A second real session. The SIGNOFF approval is CONSUMED per PASS, so a
    # second one is genuinely required -- the human gate is still standing.
    _approve_signoff(p)
    _run_loop_to_closed(p)
    assert "LOOP_RESUMED" not in _loop_event_names(p)
    assert _loop_event_names(p).count("LOOP_SUCCESS") == 2


# ==========================================================================
# 4. Plateau / oscillation: LOOP-2's classifier, fired on the real path
# ==========================================================================
def test_a_real_flat_coverage_curve_produces_loop_plateau_detected(project):
    """The whole point of wiring `loop_convergence` into the engine: before
    this, PLATEAU was REACHED but never PRODUCED, and every observation carried
    PLATEAU_NOT_EVALUATED forever.

    The four coverage days are written by the REAL
    `dashboard.append_coverage_history_sample()` -- the exact function
    `engine._append_coverage_history_sample()` calls on a gate-verified
    COVERAGE_CLOSURE PASS -- into a REAL DuckDB evidence store."""
    _coverage_days(project, [("2026-09-01", 88.0), ("2026-09-02", 88.1),
                             ("2026-09-03", 88.0), ("2026-09-04", 88.2)])
    _run_real_loop_to_retry_exhaustion(project)

    names = _loop_event_names(project)
    assert "LOOP_PLATEAU_DETECTED" in names
    plat = [e for e in _events(project) if e.get("event") == "LOOP_PLATEAU_DETECTED"][-1]
    assert plat["metric"] == lt.COVERAGE_SERIES_METRIC
    assert plat["verdict"] == lcv.PLATEAU
    assert plat["convergence"]["sources"]["series_points"] == 4
    assert plat["loop_state"] == lc.LoopState.PLATEAU.value

    # ...and the observation LOOP-1 writes now carries a real verdict instead
    # of PLATEAU_NOT_EVALUATED.
    obs = [e for e in _events(project) if e.get("event") == "LOOP_STATE_OBSERVED"][-1]
    assert obs["plateau"] == lcv.PLATEAU


def test_a_real_rising_curve_is_the_positive_control_and_emits_no_plateau(project):
    """Without this, the PLATEAU above could be an artifact of running the
    classifier at all rather than a measurement of the series."""
    _coverage_days(project, [("2026-09-01", 40.0), ("2026-09-02", 55.0),
                             ("2026-09-03", 70.0), ("2026-09-04", 85.0)])
    _run_real_loop_to_retry_exhaustion(project)

    names = _loop_event_names(project)
    assert "LOOP_PLATEAU_DETECTED" not in names
    conv = [e for e in _events(project)
            if e.get("event") == "LOOP_CONVERGING"
            and e.get("metric") == lt.COVERAGE_SERIES_METRIC]
    assert conv, "a real rising series must produce a cross-run CONVERGING verdict"
    assert conv[-1]["convergence"]["convergence"]["net_delta"] == 45.0


def test_a_project_with_no_evidence_database_emits_no_plateau_verdict_at_all(project):
    """The fabrication guard, and the one that matters most: a detector that
    could not run must never read as 'no plateau'."""
    _run_real_loop_to_retry_exhaustion(project)
    names = _loop_event_names(project)
    assert "LOOP_PLATEAU_DETECTED" not in names
    assert not [e for e in _events(project)
                if e.get("event") in ("LOOP_CONVERGING", "LOOP_NO_PROGRESS")
                and e.get("metric") == lt.COVERAGE_SERIES_METRIC]

    obs = [e for e in _events(project) if e.get("event") == "LOOP_STATE_OBSERVED"][-1]
    assert obs["plateau"] == lc.PLATEAU_NOT_EVALUATED

    row = lt.read_loop_telemetry(project)["rows"][0]
    assert row["plateau"] == lt.NOT_EVALUATED
    assert row["oscillation"] == lt.NOT_EVALUATED


def test_the_two_progress_metrics_are_never_conflated(project):
    """Two real metrics on two real cadences. Every event says which one
    produced it, so a per-iteration gate verdict can never be read as a
    statement about the coverage curve."""
    _coverage_days(project, [("2026-09-01", 88.0), ("2026-09-02", 88.1),
                             ("2026-09-03", 88.0), ("2026-09-04", 88.2)])
    _run_real_loop_to_retry_exhaustion(project)

    metrics = {e["event"]: e.get("metric") for e in _events(project)
               if e.get("event") in lt.LOOP_TELEMETRY_EVENTS and e.get("metric")}
    assert metrics["LOOP_PROGRESS_UPDATED"] == lt.GATE_VERIFIED_STAGE_METRIC
    assert metrics["LOOP_PLATEAU_DETECTED"] == lt.COVERAGE_SERIES_METRIC
    # The per-iteration no-progress verdict is about stages, not coverage.
    per_iter = [e for e in _events(project)
                if e.get("event") == "LOOP_NO_PROGRESS"
                and e.get("metric") == lt.GATE_VERIFIED_STAGE_METRIC]
    assert per_iter


# ==========================================================================
# 5. The reader: section 107's table, honest about what it does not have
# ==========================================================================
def test_a_project_with_no_loop_telemetry_reports_an_honest_empty_state(root):
    payload = lt.read_loop_telemetry(root)
    assert payload["available"] is False
    assert payload["rows"] == []
    assert lt.NO_LOOP_TELEMETRY in payload["reason"]
    assert "events.jsonl" in payload["reason"]
    assert "dv-harness start --loop" in payload["reason"], (
        "an empty state must name the real command that would populate it")
    # Reading created nothing.
    assert not (root / ".dv-harness" / "events.jsonl").exists()
    assert not (root / ".dv-harness" / "state.json").exists()


def test_the_row_reports_the_state_loop_contract_derived_not_one_of_its_own(project):
    _run_real_loop_to_retry_exhaustion(project)
    row = lt.read_loop_telemetry(project)["rows"][0]
    assert row["state"] == lc.LoopState.FAILED.value
    assert row["state"] in lc.LOOP_STATE_VALUES
    assert row["terminal_event"] == "LOOP_FAILED"


def test_the_verified_gain_column_equals_the_dashboards_own_progress_figure(root):
    """One definition of "which stages count", two consumers. A second copy of
    the predicate is how the progress bar and this column drift apart."""
    from dv_harness import dashboard
    p = _closing_project(root)
    _approve_signoff(p)
    _run_loop_to_closed(p)

    state = json.loads((p / ".dv-harness" / "state.json").read_text(encoding="utf-8"))
    done, total = lt.gate_verified_stage_count(state["stages"])
    assert dashboard._overall_progress(state) == round(100 * done / total)

    gain = lt.read_loop_telemetry(p)["rows"][0]["verified_gain"]
    assert gain["value"] == done and gain["total"] == total


def test_the_next_action_column_comes_from_the_real_inference_engine(project):
    """Section 10 forbids re-implementing the Gap -> Next-Best-Action engine;
    this drives the real one through its catalog parameter."""
    _run_real_loop_to_retry_exhaustion(project)
    row = lt.read_loop_telemetry(project)["rows"][0]
    assert row["next_action"]
    assert row["next_action"] == lt.LOOP_NEXT_ACTION_CATALOG["actions"]["FAILED"]

    from dv_harness.inference import next_best_action
    direct = next_best_action(None, ["PLATEAU"], project,
                              gap_action_catalog=lt.LOOP_NEXT_ACTION_CATALOG)
    assert direct[0]["source"] == lt.LOOP_NEXT_ACTION_CATALOG["source"]
    assert "STOP expanding seeds blindly" in direct[0]["suggested_action"]


def test_the_drilldown_carries_every_one_of_section_107s_fourteen_fields(project):
    _run_real_loop_to_retry_exhaustion(project)
    payload = lt.read_loop_telemetry(project)
    detail = payload["sessions"][payload["rows"][0]["run_id"]]
    for key, _label in lt.SECTION_107_DRILLDOWN_FIELDS:
        assert key in detail, f"section 107 drill-down field {key} missing"

    assert detail["goal"] == "verify the command pattern migration"
    assert detail["trigger"] == "dv_harness.engine.DVHarness.loop()"
    assert detail["verifier"]["gate_count"] >= 1
    assert detail["retry_backoff"]["max_stage_retries"] is not None
    assert detail["stop_reason"] == "RETRIES_EXHAUSTED_AND_NO_FAIL_EDGE"
    assert "main_graph.json" in detail["resume_condition"]
    hist = detail["iteration_history"]
    assert hist[0]["event"] == "LOOP_CREATED"
    assert hist[-1]["event"] == "LOOP_FAILED"


def test_a_torn_or_foreign_audit_line_never_breaks_the_reader(project):
    """events.jsonl is append-only and shared with every other subsystem; a
    half-written line or an unrelated event must be skipped, not fatal."""
    _run_real_loop_to_retry_exhaustion(project)
    with (project / ".dv-harness" / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write('{"event": "CLI_ACCESS", "verb": "status"}\n')
        f.write('{"event": "LOOP_STARTED", "run_id"\n')          # torn
    payload = lt.read_loop_telemetry(project)
    assert payload["available"] is True
    assert len(payload["rows"]) == 1


def test_filtering_by_run_id_returns_only_that_session(project):
    h = _run_real_loop_to_retry_exhaustion(project)
    h.state.stages[FIXTURE_STAGE]["attempts"] = 0
    h.state.current_stage = FIXTURE_STAGE
    h.store.save(h.state)
    h.loop("second round")

    all_rows = lt.read_loop_telemetry(project)["rows"]
    assert len(all_rows) == 2
    one = lt.read_loop_telemetry(project, run_id=all_rows[0]["run_id"])
    assert len(one["rows"]) == 1
    assert one["rows"][0]["run_id"] == all_rows[0]["run_id"]


def test_the_module_front_door_prints_the_table_and_exits_nonzero_when_empty(project, root):
    code, text = lt.execute_verb(root, "show")
    assert code == 2 and "no loop telemetry" in text

    _run_real_loop_to_retry_exhaustion(project)
    code, text = lt.execute_verb(project, "show")
    assert code == 0
    assert "Loop | State | Iteration | Verified Gain" in text
    assert lc.VERIFICATION_CLOSURE_LOOP in text

    code, payload = lt.execute_verb(project, "names")
    assert code == 0 and len(payload["event_names"]) == 19
    code, _ = lt.execute_verb(project, "not-a-verb")
    assert code == 1


# ==========================================================================
# 6. Boundaries: observing authorizes nothing, reading writes nothing
# ==========================================================================
def test_emitting_a_human_gate_event_authorizes_nothing(project):
    """LOOP_HUMAN_GATE_REQUIRED records that a human decision is OWED. It must
    not be, or become, the decision."""
    from dv_harness import capability_evolution as ce
    h = harness_factory(project)
    h.state.current_stage = FIXTURE_STAGE
    h.store.save(h.state)
    ControlPlane(project).takeover(FIXTURE_STAGE, "human is driving")
    h.loop("verify the command pattern migration")
    assert "LOOP_HUMAN_GATE_REQUIRED" in _loop_event_names(project)

    cp = ControlPlane(project).load()
    assert not cp.get("approvals"), "no approval may be minted by observing a gate"
    with pytest.raises(ce.HumanApprovalRequiredError):
        ce.assert_human_approval(project)
    with pytest.raises(ce.ProductionWriteNotAuthorizedError):
        ce.assert_no_production_write_authorized(project, {"current_status": "BENCHMARKED"})


def test_reading_the_telemetry_writes_nothing_at_all(project):
    _run_real_loop_to_retry_exhaustion(project)
    before = {p: p.stat().st_mtime_ns for p in (project / ".dv-harness").rglob("*")
              if p.is_file()}
    for _ in range(3):
        lt.read_loop_telemetry(project)
        lt.previous_session_summary(project)
    after = {p: p.stat().st_mtime_ns for p in (project / ".dv-harness").rglob("*")
             if p.is_file()}
    assert before == after


def test_the_telemetry_module_never_reaches_for_an_approval_gate():
    """Asserted against the module's own source, so a future edit that reaches
    for one fails here rather than at review time."""
    src = Path(lt.__file__).read_text(encoding="utf-8")
    for forbidden in ("ControlPlane", "can_signoff", "assert_human_approval",
                      "approve(", "HumanApprovalRequiredError",
                      "ProductionWriteNotAuthorizedError"):
        assert forbidden not in src, f"loop_telemetry.py must not reference {forbidden}"


def test_a_telemetry_failure_never_breaks_the_loop(project, monkeypatch):
    """Best-effort, like every sibling `_record_*`: an observability failure
    must never turn a real routing decision into a crash."""
    def boom(*a, **k):
        raise RuntimeError("events.jsonl is on fire")
    monkeypatch.setattr(lt, "emit", boom)

    h = _run_real_loop_to_retry_exhaustion(project)
    assert h.state.stages[FIXTURE_STAGE]["attempts"] > h.cfg["policy"]["max_stage_retries"]
    failures = [e for e in _events(project)
                if e.get("event") == "LOOP_TELEMETRY_EMIT_FAILED"]
    assert failures, "the failure must be recorded, not swallowed"
    assert "events.jsonl is on fire" in failures[0]["error"]
