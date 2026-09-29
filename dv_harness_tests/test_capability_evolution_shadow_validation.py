"""Shadow / digital-twin validation: one successful shadow run is not proof
(master prompt sections 133/134, 2026-09-05).

Section 133's canonical picture -- one input, two arms, current production
behavior against the candidate, compare the results, and nothing about
production changes until a promotion -- was already
`capability_evolution.run_controlled_experiment()`. What did NOT exist is
section 134's promotion flow around it: shadow runs PLURAL, a regression-safety
check that a net-positive total cannot hide a broken stage behind, a stability
window in front of BENCHMARKED -> PROMOTION_CANDIDATE, and a concrete rollback.

These tests drive all of it against the same synthetic fixture the controlled
experiment uses: two copies of a real project, the REAL `DVHarness.run_stage()`
in each, the REAL `command_migration_integrity_gate.py` subprocess judging both
arms. The only stub anywhere is the agent adapter, because the real one
dispatches a `claude -p` subprocess. Nothing here runs a build, a regression or
an LSF submission.

They also hold the boundary the new evidence must not buy: a cleared stability
window authorizes NOTHING. HUMAN_APPROVED still needs a real ControlPlane
approval, a production write is still refused, and a replication moves no
governance state at all.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness import capability_evolution as ce
from dv_harness.control_plane import ControlPlane

from .controlled_experiment_fixture import (
    FIXTURE_STAGE,
    benchmarked_with_stability_window,
    make_fixture_project,
    run_demo_experiment,
    run_demo_replication,
)
from .test_capability_evolution_research_architect import _semantic_change_impact_fields


@pytest.fixture
def root():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def fixture_project():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield make_fixture_project(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _approved_candidate(root: Path) -> dict:
    """A candidate walked through the REAL transition() to EXPERIMENT_APPROVED."""
    candidate = ce.build_candidate(**_semantic_change_impact_fields())
    ce.persist_candidate(root, candidate)
    for state in ("EVIDENCE_GATHERING", "PROPOSED", "EXPERIMENT_APPROVED"):
        candidate = ce.transition(root, candidate, state, by="tester",
                                  reason=f"advance to {state}")
    return candidate


def _benchmarked(root: Path, fixture_project: Path) -> dict:
    return run_demo_experiment(root, _approved_candidate(root), fixture_project)["candidate"]


# --- section 134: shadow runs, plural ----------------------------------------


def test_one_shadow_run_is_not_sufficient_proof(root, fixture_project):
    """The gap itself. A candidate with a real, IMPROVED, isolated measurement
    behind it could reach PROMOTION_CANDIDATE on that single run; section 134
    says in as many words that it may not."""
    measured = _benchmarked(root, fixture_project)
    assert measured["current_status"] == "BENCHMARKED"
    assert measured["benchmark_result"]["outcome"] == "IMPROVED"

    status = ce.stability_window_status(root, measured)
    assert status["established"] is False
    assert status["countable_runs"] == 1
    assert any("single successful shadow run" in b for b in status["blockers"])

    with pytest.raises(ce.StabilityWindowNotEstablishedError) as exc:
        ce.transition(root, measured, "PROMOTION_CANDIDATE", by="dv-manager",
                      reason="the benchmark improved")
    assert "stability window" in str(exc.value)
    assert ce.read_candidate(root, measured["candidate_id"])["current_status"] == "BENCHMARKED"


def test_a_second_real_shadow_run_establishes_the_window(root, fixture_project):
    """The positive control for the test above: the SAME candidate, the same
    fixture, the same stages, measured a second time for real -- and the edge
    that was refused now opens."""
    measured = _benchmarked(root, fixture_project)
    replicated = run_demo_replication(root, measured, fixture_project)["candidate"]

    status = ce.stability_window_status(root, replicated)
    assert status["established"] is True, status["blockers"]
    assert status["countable_runs"] == ce.STABILITY_WINDOW_MIN_RUNS == 2
    assert status["outcomes"] == ["IMPROVED", "IMPROVED"]
    assert status["stages"] == [FIXTURE_STAGE]
    assert status["regression_safe"] is True

    promoted = ce.transition(root, replicated, "PROMOTION_CANDIDATE", by="dv-manager",
                             reason="two measured runs reviewed")
    assert promoted["current_status"] == "PROMOTION_CANDIDATE"

    # The evidence is copied onto the candidate's own audit trail, so "the window
    # was established" is re-readable after the fact rather than only at the
    # moment the edge was crossed.
    window = promoted["status_history"][-1]["stability_window"]
    assert window["countable_runs"] == 2
    assert sorted(window["run_ids"]) == sorted(status["run_ids"])
    assert window["acceptance_criteria_machine_evaluated"] is False


def test_a_replication_really_ran_two_arms_and_moved_no_state(root, fixture_project):
    """A replication is a MEASUREMENT, not a governance step. It must produce a
    real two-arm run on disk and leave the candidate exactly where it was."""
    measured = _benchmarked(root, fixture_project)
    history_before = list(measured.get("status_history"))

    result = run_demo_replication(root, measured, fixture_project)
    replicated, record = result["candidate"], result["experiment"]

    assert replicated["current_status"] == "BENCHMARKED"
    assert replicated["promotion_status"] == "BENCHMARKED"
    assert replicated["status_history"] == history_before, (
        "a replication appended a governance transition; section 70's state "
        "machine gains no edge for replication")

    assert record["run_kind"] == ce.SHADOW_RUN_KIND_REPLICATION
    assert record["produced_by"] == ce.SHADOW_REPLICATION_PRODUCER
    # Both arms really ran: each has its own harness state, and the two arms
    # reached genuinely different gate outcomes.
    workspace = Path(record["workspace"])
    for arm in ce.EXPERIMENT_ARMS:
        assert (workspace / arm / ".dv-harness" / "state.json").is_file()
    assert (record["before"]["stages"][FIXTURE_STAGE]["gate_outcome_digest"]
            != record["after"]["stages"][FIXTURE_STAGE]["gate_outcome_digest"])
    # STAGE_GATES["COMMAND_PATTERN"] carries two real gates (command_migration_
    # integrity_gate + command_generation_gate); the fixture's stub agent
    # supplies both evidence blocks once the migration manifest is present, so
    # a real PASS satisfies both, not one.
    assert record["before"]["totals"]["gates_satisfied"] == 0
    assert record["after"]["totals"]["gates_satisfied"] == 2


def test_a_replication_is_refused_before_a_benchmark_exists(root, fixture_project):
    """A replication replicates a measurement, so there must be one. Every state
    before BENCHMARKED is refused, including the one an experiment runs from."""
    candidate = ce.build_candidate(**_semantic_change_impact_fields())
    ce.persist_candidate(root, candidate)
    for state in (None, "EVIDENCE_GATHERING", "PROPOSED", "EXPERIMENT_APPROVED"):
        if state is not None:
            candidate = ce.transition(root, candidate, state, by="tester",
                                      reason=f"advance to {state}")
        with pytest.raises(ce.ExperimentNotAuthorizedError):
            run_demo_replication(root, candidate, fixture_project)


def test_a_replication_refuses_to_prop_up_a_tampered_benchmark(root, fixture_project):
    """A replication must never be the second run that lends weight to a first
    one whose record has since been edited."""
    measured = _benchmarked(root, fixture_project)
    record_path = Path(measured["benchmark_result"]["record_path"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["outcome"] = "IMPROVED"
    record["delta"]["gates_satisfied"] = 99
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(ce.BenchmarkEvidenceRequiredError):
        run_demo_replication(root, measured, fixture_project)


# --- section 134: regression safety ------------------------------------------


def test_regression_safety_sees_the_stage_a_net_positive_total_hides():
    """compare_experiment_arms() reports a NET verdict, and a net verdict cannot
    see a trade. This is the case the section-134 node exists for: +2 gates on
    one stage, -1 on another, IMPROVED overall, one stage genuinely broken."""
    def arm(name, satisfied):
        stages = {
            stage: {"stage": stage, "gates_total": 3, "gates_satisfied": n,
                    "stage_completion_percent": 100.0 * n / 3, "gate_reason_count": 0,
                    "gate_outcome_digest": f"{stage}{n}", "attempts": 1}
            for stage, n in satisfied.items()
        }
        return {"arm": name, "project_root": "x", "stages": stages,
                "totals": {"gates_total": 6,
                           "gates_satisfied": sum(satisfied.values()),
                           "stage_completion_percent": 50.0}}

    before = arm("baseline", {"A": 0, "B": 3})
    after = arm("treatment", {"A": 2, "B": 2})

    assert ce.compare_experiment_arms(before, after)["outcome"] == "IMPROVED"
    safety = ce.regression_safety(before, after)
    assert safety["safe"] is False
    assert safety["regressed_stages"] == [
        {"stage": "B", "metric": "gates_satisfied", "baseline": 3, "treatment": 2}]


def test_regression_safety_is_clean_on_a_real_improving_run(root, fixture_project):
    """The negative control: a real run that genuinely only improved must not be
    reported as a regression, or the check has no discriminating power."""
    record = run_demo_experiment(
        root, _approved_candidate(root), fixture_project)["experiment"]
    assert record["outcome"] == "IMPROVED"
    assert record["regression_safety"] == {
        "safe": True, "regressed_stages": [], "unmeasured_in_treatment": []}


def test_a_stage_the_treatment_stopped_measuring_is_not_a_neutral_result():
    """The one way a regression can hide from a per-stage check that only walks
    the intersection: stop measuring the stage."""
    stage = {"gates_total": 1, "gates_satisfied": 1, "stage_completion_percent": 100.0}
    before = {"stages": {"A": dict(stage), "B": dict(stage)}}
    after = {"stages": {"A": dict(stage)}}
    safety = ce.regression_safety(before, after)
    assert safety["safe"] is False
    assert safety["unmeasured_in_treatment"] == ["B"]


def test_a_regressed_run_cannot_close_a_stability_window(root, fixture_project):
    """End to end: two REAL runs, and the second one's record edited so its
    treatment arm regressed a stage. The window refuses -- through the
    recomputed per-stage view, not through the record's stored verdict."""
    measured = _benchmarked(root, fixture_project)
    result = run_demo_replication(root, measured, fixture_project)
    replicated = result["candidate"]
    assert ce.stability_window_status(root, replicated)["established"] is True

    # Swap the two arms' gate counts and re-pin, so the ONLY thing wrong is the
    # measurement itself -- the digest still matches, the record still exists,
    # both arms are still on disk, and the record's own stored `outcome` still
    # says IMPROVED. That is the case this check has to catch: the stored net
    # verdict is not what decides regression safety.
    record_path = Path(result["record_path"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["before"]["stages"][FIXTURE_STAGE]["gates_satisfied"] = 1
    record["before"]["totals"]["gates_satisfied"] = 1
    record["after"]["stages"][FIXTURE_STAGE]["gates_satisfied"] = 0
    record["after"]["totals"]["gates_satisfied"] = 0
    assert record["outcome"] == "IMPROVED"
    text = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True)
    record_path.write_text(text, encoding="utf-8")
    import hashlib
    replicated["shadow_runs"][-1]["record_digest"] = hashlib.sha256(
        text.encode("utf-8")).hexdigest()

    status = ce.stability_window_status(root, replicated)
    assert status["established"] is False
    assert status["regression_safe"] is False
    assert any("regressed" in b for b in status["blockers"])
    with pytest.raises(ce.StabilityWindowNotEstablishedError):
        ce.transition(root, replicated, "PROMOTION_CANDIDATE", by="dv-manager",
                      reason="net result still looks fine")


# --- the window counts only pinned, re-readable, agreeing runs ---------------


def test_a_hand_written_experiment_record_counts_for_nothing(root, fixture_project):
    """The whole anti-forgery story: a run counts because the CANDIDATE pins it
    by digest, never because a file appeared in the experiments directory."""
    measured = _benchmarked(root, fixture_project)
    real = json.loads(Path(measured["benchmark_result"]["record_path"]).read_text("utf-8"))

    forged_dir = ce.experiments_dir(root) / measured["candidate_id"] / "EXP-FORGED"
    forged_dir.mkdir(parents=True)
    forged = dict(real, run_id="EXP-FORGED", workspace=str(forged_dir))
    (forged_dir / ce.EXPERIMENT_RECORD_NAME).write_text(
        json.dumps(forged, indent=2, sort_keys=True), encoding="utf-8")

    status = ce.stability_window_status(root, measured)
    assert status["countable_runs"] == 1, "an unpinned record on disk was counted"
    assert status["established"] is False


def test_a_deleted_replication_record_stops_counting(root, fixture_project):
    """Countable is re-checked against disk every time, not decided once."""
    replicated = benchmarked_with_stability_window(
        root, _approved_candidate(root), fixture_project)
    assert ce.stability_window_status(root, replicated)["established"] is True

    Path(replicated["shadow_runs"][-1]["record_path"]).unlink()
    status = ce.stability_window_status(root, replicated)
    assert status["established"] is False
    assert status["countable_runs"] == 1
    assert any("does not exist" in (u["reason"] or "") for u in status["uncountable_runs"])


def test_a_record_whose_arm_workspaces_are_gone_stops_counting(root, fixture_project):
    """The digest proves the record was not EDITED, not that anything ever ran.
    A shadow run's evidence is its two arms, so they must still be there."""
    replicated = benchmarked_with_stability_window(
        root, _approved_candidate(root), fixture_project)
    workspace = Path(replicated["shadow_runs"][-1]["workspace"])
    shutil.rmtree(workspace / "treatment")

    status = ce.stability_window_status(root, replicated)
    assert status["established"] is False
    assert any("treatment arm workspace" in (u["reason"] or "")
               for u in status["uncountable_runs"])


def test_runs_over_different_stages_are_not_a_replication(root, fixture_project):
    """Replication means re-measuring the same thing. Two runs that measured
    different stage sets are two experiments, not a window."""
    replicated = benchmarked_with_stability_window(
        root, _approved_candidate(root), fixture_project)
    replicated["shadow_runs"][-1]["stages"] = [FIXTURE_STAGE, "SOME_OTHER_STAGE"]
    # The pin's own stage list is not what is judged -- the record on disk is --
    # so this must still pass, proving the check reads the measurement.
    assert ce.stability_window_status(root, replicated)["established"] is True

    record_path = Path(replicated["shadow_runs"][-1]["record_path"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["stages"] = [FIXTURE_STAGE, "SOME_OTHER_STAGE"]
    text = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True)
    record_path.write_text(text, encoding="utf-8")
    import hashlib
    replicated["shadow_runs"][-1]["record_digest"] = hashlib.sha256(
        text.encode("utf-8")).hexdigest()

    status = ce.stability_window_status(root, replicated)
    assert status["established"] is False
    assert any("different stage sets" in b for b in status["blockers"])


def test_runs_that_disagree_are_what_unstable_means(root, fixture_project):
    """Two real runs, one IMPROVED and one UNCHANGED: both are admissible
    outcomes on their own, and disagreeing is exactly the instability a
    stability window exists to catch."""
    replicated = benchmarked_with_stability_window(
        root, _approved_candidate(root), fixture_project)
    record_path = Path(replicated["shadow_runs"][-1]["record_path"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["outcome"] = "UNCHANGED"
    text = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True)
    record_path.write_text(text, encoding="utf-8")
    import hashlib
    replicated["shadow_runs"][-1]["record_digest"] = hashlib.sha256(
        text.encode("utf-8")).hexdigest()

    status = ce.stability_window_status(root, replicated)
    assert status["established"] is False
    assert any("disagree" in b for b in status["blockers"])


def test_a_degraded_run_is_refused_outright(root, fixture_project):
    """DEGRADED and INCONCLUSIVE are outside the window's admissible vocabulary
    however consistently they recur."""
    replicated = benchmarked_with_stability_window(
        root, _approved_candidate(root), fixture_project)
    import hashlib
    for pin in [replicated["benchmark_result"], replicated["shadow_runs"][-1]]:
        record_path = Path(pin["record_path"])
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["outcome"] = "DEGRADED"
        text = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True)
        record_path.write_text(text, encoding="utf-8")
        pin["record_digest"] = hashlib.sha256(text.encode("utf-8")).hexdigest()

    status = ce.stability_window_status(root, replicated)
    assert status["established"] is False
    assert any("DEGRADED" in b for b in status["blockers"])


def test_the_window_reports_every_blocker_at_once(root, fixture_project):
    """The caller is deciding whether to run another replication or to stop and
    fix something; one blocker per round would make that several rounds."""
    measured = _benchmarked(root, fixture_project)
    measured["rollback_plan"] = "   "
    status = ce.stability_window_status(root, measured)
    assert len(status["blockers"]) >= 2
    assert any("single successful shadow run" in b for b in status["blockers"])
    assert any("rollback" in b for b in status["blockers"])


# --- section 134: provide rollback -------------------------------------------


def test_the_rollback_manifest_is_derived_from_the_untouched_baseline_arm(
        root, fixture_project):
    """`rollback_plan` is prose authored before anything ran. The manifest is the
    other half: what the experiment's OWN control copy holds at each path the
    mutation wrote."""
    from .controlled_experiment_fixture import MIGRATION_FILE

    replicated = benchmarked_with_stability_window(
        root, _approved_candidate(root), fixture_project)
    manifest = ce.shadow_rollback_manifest(root, replicated)

    assert manifest["candidate_id"] == replicated["candidate_id"]
    assert manifest["applied"] is False
    assert manifest["rollback_plan"] == replicated["rollback_plan"]
    entry = next(e for e in manifest["entries"] if e["path"] == MIGRATION_FILE)
    # The fixture's mutation CREATES the manifest file, so the baseline arm does
    # not have it and the concrete undo really is a delete.
    assert entry["existed_in_baseline"] is False
    assert entry["restore_action"] == "delete"
    assert entry["baseline_digest"] is None
    assert entry["treatment_digest"], "the treatment arm's written file was not hashed"

    # And it restores nothing: producing the manifest must not itself be an undo.
    treatment_file = Path(manifest["workspace"]) / "treatment" / MIGRATION_FILE
    assert treatment_file.is_file()


def test_a_rollback_manifest_needs_a_countable_run(root, fixture_project):
    measured = _benchmarked(root, fixture_project)
    Path(measured["benchmark_result"]["record_path"]).unlink()
    with pytest.raises(ce.BenchmarkEvidenceRequiredError):
        ce.shadow_rollback_manifest(root, measured)


# --- the boundaries this evidence must not buy -------------------------------


def test_an_established_window_authorizes_nothing(root, fixture_project):
    """The load-bearing boundary. Two real, agreeing, regression-free runs are
    MORE evidence and no more authority: HUMAN_APPROVED still requires a real
    ControlPlane approval on disk, and a production write is still refused."""
    replicated = benchmarked_with_stability_window(
        root, _approved_candidate(root), fixture_project)
    assert ce.stability_window_status(root, replicated)["established"] is True
    assert ce.human_approval_status(root)["approved"] is False

    promoted = ce.transition(root, replicated, "PROMOTION_CANDIDATE", by="dv-manager",
                             reason="two measured runs reviewed")
    with pytest.raises(ce.HumanApprovalRequiredError):
        ce.transition(root, promoted, "HUMAN_APPROVED", by="tester",
                      reason="both shadow runs improved")
    with pytest.raises(ce.ProductionWriteNotAuthorizedError):
        ce.assert_no_production_write_authorized(root, promoted)

    # The real approval still unblocks the last edge exactly as before.
    ControlPlane(root).approve(ce.HUMAN_APPROVAL_STAGE, note="reviewed both runs",
                               reviewer_id="dv-manager", reviewer_confidence="HIGH")
    approved = ce.transition(root, promoted, "HUMAN_APPROVED", by="dv-manager",
                             reason="approved on the measured window")
    assert approved["current_status"] == "HUMAN_APPROVED"


def test_the_window_is_not_required_of_a_candidate_that_ran_no_experiment(root):
    """PROPOSED -> PROMOTION_CANDIDATE belongs to a candidate whose own
    experiment_required is False. It ran no experiment, so it has no window to
    establish, and the new precondition must not make that edge unwalkable."""
    fields = _semantic_change_impact_fields()
    fields["experiment_required"] = False
    fields["experiment_plan"] = ""
    fields["benchmark_plan"] = ""
    candidate = ce.build_candidate(**fields)
    ce.persist_candidate(root, candidate)
    for state in ("EVIDENCE_GATHERING", "PROPOSED"):
        candidate = ce.transition(root, candidate, state, by="tester",
                                  reason=f"advance to {state}")

    promoted = ce.transition(root, candidate, "PROMOTION_CANDIDATE", by="dv-manager",
                             reason="no experiment was required")
    assert promoted["current_status"] == "PROMOTION_CANDIDATE"
    assert "stability_window" not in promoted["status_history"][-1]


def test_shadow_runs_cannot_be_supplied_by_whoever_assembles_a_candidate(root):
    """Mirrors build_candidate()'s benchmark_result guard, one step further
    along: a candidate is born six governance states before a replication may
    run, so shadow_runs arriving there pins runs nothing ran."""
    with pytest.raises(ce.CapabilityEvolutionCandidateValidationError) as exc:
        ce.build_candidate(**_semantic_change_impact_fields(), shadow_runs=[{
            "produced_by": ce.SHADOW_REPLICATION_PRODUCER,
            "run_kind": "replication", "run_id": "EXP-1", "record_path": "x",
            "record_digest": "y", "stages": ["S"], "outcome": "IMPROVED",
            "measured_at": "2026-09-05T00:00:00+00:00",
        }])
    assert "run_shadow_replication" in str(exc.value)


def test_the_replicated_candidate_still_validates_against_the_schema(
        root, fixture_project):
    """shadow_runs is a real schema field, not an extra key the validator would
    reject -- persist_candidate() validates on every write, so a replication
    that produced an unvalidatable candidate could never have persisted."""
    replicated = benchmarked_with_stability_window(
        root, _approved_candidate(root), fixture_project)
    ce.validate_candidate(replicated)
    stored = ce.read_candidate(root, replicated["candidate_id"])
    assert len(stored["shadow_runs"]) == 1
    assert stored["shadow_runs"][0]["produced_by"] == ce.SHADOW_REPLICATION_PRODUCER
    assert stored["current_status"] == "BENCHMARKED"


def test_no_verdict_token_reaches_a_shadow_run_record(root, fixture_project):
    """This module's standing guarantee, held over the new record fields too:
    nothing here persists a member of models.Status."""
    from dv_harness.models import Status

    result = run_demo_replication(
        root, _benchmarked(root, fixture_project), fixture_project)
    # Quoted-value comparison, the same form the controlled experiment's own
    # guard uses: a bare substring test would fire on PARTIAL_MATCH, which is
    # this module's own overlap vocabulary and not a verification verdict.
    for blob in (json.dumps(result["experiment"]),
                 json.dumps(result["candidate"]["shadow_runs"])):
        for status in Status:
            assert f'"{status.value}"' not in blob, (
                f"{status.value} reached a shadow-run artifact")
    ce.assert_no_verification_verdict_vocabulary()


def test_a_replication_never_writes_outside_its_own_workspace(root, fixture_project):
    """The isolation properties run_controlled_experiment() holds are the
    replication's too, because they are the same code -- proven rather than
    assumed by fingerprinting the source fixture across a real replication."""
    measured = _benchmarked(root, fixture_project)
    before = ce._tree_digest(fixture_project)
    result = run_demo_replication(root, measured, fixture_project)
    assert ce._tree_digest(fixture_project)["digest"] == before["digest"]

    workspace = Path(result["record_path"]).parent
    assert workspace.parent.parent == ce.experiments_dir(root)
    assert result["experiment"]["isolation"]["fixture_unmodified"] is True
    assert result["experiment"]["isolation"]["execution_stages_allowed"] is False
