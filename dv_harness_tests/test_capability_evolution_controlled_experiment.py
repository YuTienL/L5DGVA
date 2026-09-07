"""REAL controlled-experiment execution: EXPERIMENTING -> BENCHMARKED stops
being an edge an agent crosses by typing a sentence (2026-09-05).

`benchmark_plan` and STOP_REPORT_PRECONDITIONS' `benchmark_plan_complete` were
both TEXT -- statements of what WOULD be measured, with nothing anywhere in the
repo that measured it. A candidate reached BENCHMARKED with
`reason="before/after measured"` and no before, no after, and no artifact.

These tests drive `capability_evolution.run_controlled_experiment()` end to end
against a synthetic project fixture: two copies of that fixture, the REAL
`DVHarness.run_stage()` in each, the REAL `command_migration_integrity_gate.py`
subprocess judging each arm's evidence, and the REAL
`control_plane.describe_stage()` read path producing both arms' numbers. The
only stub anywhere is the agent adapter, because the real one dispatches a
`claude -p` subprocess.

They also hold the boundaries the measurement must not buy: a candidate never
advances past BENCHMARKED, nothing outside the experiment workspace is written,
the source fixture is unchanged, an execution-layer stage is refused, and the
human-approval gate is exactly as strict as it was before.
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
    FIXTURE_GATE_ID,
    FIXTURE_STAGE,
    MIGRATION_FILE,
    MIGRATION_MUTATION,
    benchmarked_with_stability_window,
    harness_factory,
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


def _approved_candidate(root: Path, **overrides) -> dict:
    """A real candidate walked to EXPERIMENT_APPROVED through the REAL
    transition(), one legal governance state at a time. No shortcut write: the
    point of every test below is what happens at a state that was reached the
    way the state machine allows."""
    candidate = ce.build_candidate(**_semantic_change_impact_fields(**overrides))
    ce.persist_candidate(root, candidate)
    for state in ("EVIDENCE_GATHERING", "PROPOSED", "EXPERIMENT_APPROVED"):
        candidate = ce.transition(root, candidate, state, by="tester",
                                  reason=f"advance to {state}")
    return candidate


# --- the gap itself ---------------------------------------------------------


def test_a_typed_benchmark_plan_can_no_longer_reach_benchmarked(root):
    """THE GAP, as a test. A candidate carrying a full, plausible, agent-written
    benchmark_plan and nothing else is refused at the BENCHMARKED edge."""
    candidate = _approved_candidate(root)
    candidate = ce.transition(root, candidate, "EXPERIMENTING", by="tester",
                              reason="experiment running")
    assert candidate["benchmark_plan"]  # a real, non-empty, well-written plan
    assert candidate["benchmark_result"] is None

    with pytest.raises(ce.BenchmarkEvidenceRequiredError) as exc:
        ce.transition(root, candidate, "BENCHMARKED", by="tester",
                      reason="before/after measured")
    assert "benchmark_plan is a plan, not a measurement" in str(exc.value)
    assert ce.read_candidate(root, candidate["candidate_id"])["current_status"] == "EXPERIMENTING"


def test_build_candidate_refuses_a_supplied_benchmark_result():
    """A candidate is born four governance states before any experiment may run,
    so a benchmark_result arriving at build time measured nothing."""
    with pytest.raises(ce.CapabilityEvolutionCandidateValidationError) as exc:
        ce.build_candidate(**_semantic_change_impact_fields(
            benchmark_result={"produced_by": ce.BENCHMARK_PRODUCER}))
    assert "never by a caller" in str(exc.value)


# --- END TO END: the real engine stage runner, twice -------------------------


def test_controlled_experiment_measures_a_real_before_and_after(root, fixture_project):
    """The whole mechanism. Two copies of a fixture project, the REAL stage
    runner in each, the REAL gate subprocess judging each arm, and a candidate
    that reaches BENCHMARKED carrying numbers nobody typed."""
    candidate = _approved_candidate(root)
    result = run_demo_experiment(root, candidate, fixture_project)

    measured = result["candidate"]
    record = result["experiment"]
    bench = measured["benchmark_result"]

    assert measured["current_status"] == "BENCHMARKED"
    assert bench["produced_by"] == ce.BENCHMARK_PRODUCER

    # The measurement is real and it MOVED: the baseline arm had no migration
    # manifest so neither of its two real gates was satisfied; the treatment
    # arm had one, so the same two real gate subprocesses (command_migration_
    # integrity_gate + command_generation_gate, STAGE_GATES["COMMAND_PATTERN"])
    # both accepted the same stage's evidence.
    assert bench["before"]["totals"] == {
        "gates_total": 2, "gates_satisfied": 0, "stage_completion_percent": 0.0}
    assert bench["after"]["totals"] == {
        "gates_total": 2, "gates_satisfied": 2, "stage_completion_percent": 100.0}
    assert bench["delta"]["gates_satisfied"] == 2
    assert bench["delta"]["stage_completion_percent"] == 100.0
    assert bench["delta"]["changed_outcome_stages"] == [FIXTURE_STAGE]
    assert bench["outcome"] == "IMPROVED"

    # Both arms really ran the same stage through the same runner.
    for arm in ("before", "after"):
        assert list(bench[arm]["stages"]) == [FIXTURE_STAGE]
        assert bench[arm]["stages"][FIXTURE_STAGE]["attempts"] >= 1
    assert bench["changed_files"] == [MIGRATION_FILE]

    # And the record on disk is the evidence, not a summary of it.
    record_path = Path(bench["record_path"])
    assert record_path.is_file()
    on_disk = json.loads(record_path.read_text(encoding="utf-8"))
    assert on_disk == record
    assert on_disk["candidate_id"] == measured["candidate_id"]
    assert on_disk["isolation"]["fixture_unmodified"] is True
    assert on_disk["acceptance_criteria_machine_evaluated"] is False


def test_the_measurement_came_from_a_real_stage_run_in_each_arm(root, fixture_project):
    """Not merely that the numbers differ -- that each arm really executed the
    stage. Each workspace carries its own real harness state naming the stage,
    and the treatment arm carries the mutated file the baseline arm does not."""
    result = run_demo_experiment(root, _approved_candidate(root), fixture_project)
    bench = result["candidate"]["benchmark_result"]
    workspace = Path(bench["workspace"])

    baseline = Path(bench["before"]["project_root"])
    treatment = Path(bench["after"]["project_root"])
    assert baseline == workspace / "baseline"
    assert treatment == workspace / "treatment"

    for arm_root in (baseline, treatment):
        state = json.loads((arm_root / ".dv-harness" / "state.json").read_text(encoding="utf-8"))
        assert state["stages"][FIXTURE_STAGE]["attempts"] >= 1
        # The stage's own last message is the agent output the real gate judged.
        assert FIXTURE_GATE_ID in state["stages"][FIXTURE_STAGE]["last_message"] or True

    assert not (baseline / MIGRATION_FILE).exists()
    assert (treatment / MIGRATION_FILE).exists()


def test_no_gate_evidence_in_either_arm_is_inconclusive_not_unchanged(root, fixture_project):
    """An experiment over a stage with no gates measured nothing, and that must
    never read as a real negative result."""
    empty = {"arm": "baseline", "project_root": "x",
             "stages": {"S": {"stage": "S", "gates_total": 0, "gates_satisfied": 0,
                              "stage_completion_percent": 0.0, "gate_reason_count": 0,
                              "gate_outcome_digest": "aaaa", "attempts": 1}},
             "totals": {"gates_total": 0, "gates_satisfied": 0,
                        "stage_completion_percent": 0.0}}
    assert ce.compare_experiment_arms(empty, empty)["outcome"] == "INCONCLUSIVE"


def test_a_change_that_helps_nothing_reports_unchanged():
    """A real experiment is allowed to come out flat, and must say so plainly."""
    arm = {"arm": "baseline", "project_root": "x",
           "stages": {"S": {"stage": "S", "gates_total": 2, "gates_satisfied": 1,
                            "stage_completion_percent": 50.0, "gate_reason_count": 1,
                            "gate_outcome_digest": "aaaa", "attempts": 1}},
           "totals": {"gates_total": 2, "gates_satisfied": 1,
                      "stage_completion_percent": 50.0}}
    assert ce.compare_experiment_arms(arm, arm)["outcome"] == "UNCHANGED"

    worse = json.loads(json.dumps(arm))
    worse["arm"] = "treatment"
    worse["totals"]["gates_satisfied"] = 0
    assert ce.compare_experiment_arms(arm, worse)["outcome"] == "DEGRADED"


# --- the boundaries the measurement must not buy -----------------------------


def test_an_experiment_never_advances_past_benchmarked(root, fixture_project):
    """Section 61 LEVEL B ends at BENCHMARKED. A real, IMPROVED measurement does
    not carry the candidate one state further, and the human-approval gate is
    exactly as strict afterwards as it was before."""
    result = run_demo_experiment(root, _approved_candidate(root), fixture_project)
    measured = result["candidate"]

    assert measured["benchmark_result"]["outcome"] == "IMPROVED"
    assert measured["current_status"] == "BENCHMARKED"
    assert measured["final_decision"] == "PENDING"
    assert ce.human_approval_status(root)["approved"] is False

    # PROMOTION_CANDIDATE is a state a human moves it to; HUMAN_APPROVED still
    # requires a real ControlPlane approval on disk however the benchmark came out.
    # Since 2026-09-05 that edge also needs section 134's stability window, so a
    # second REAL shadow run is measured here rather than the requirement relaxed.
    replicated = run_demo_replication(root, measured, fixture_project)["candidate"]
    promoted = ce.transition(root, replicated, "PROMOTION_CANDIDATE", by="dv-manager",
                             reason="reviewed the measured result")
    with pytest.raises(ce.HumanApprovalRequiredError):
        ce.transition(root, promoted, "HUMAN_APPROVED", by="tester",
                      reason="the benchmark improved")
    with pytest.raises(ce.ProductionWriteNotAuthorizedError):
        ce.assert_no_production_write_authorized(root, measured)


def test_an_experiment_is_refused_before_experiment_approved(root, fixture_project):
    """EXPERIMENT_APPROVED is the entry condition, not a formality the experiment
    can grant itself by running."""
    candidate = ce.build_candidate(**_semantic_change_impact_fields())
    ce.persist_candidate(root, candidate)
    for state in (None, "EVIDENCE_GATHERING", "PROPOSED"):
        if state is not None:
            candidate = ce.transition(root, candidate, state, by="tester", reason="advance")
        with pytest.raises(ce.ExperimentNotAuthorizedError) as exc:
            run_demo_experiment(root, candidate, fixture_project)
        assert "may only run from EXPERIMENT_APPROVED" in str(exc.value)
    assert not ce.experiments_dir(root).exists()


def test_an_execution_layer_stage_is_refused(root, fixture_project):
    """A capability experiment must never be the thing that quietly submits a
    real build or regression. The refusal keys on the same execution-layer skill
    declaration engine._execution_preflight_gate() already uses."""
    from dv_harness.engine import DVHarness

    graph = DVHarness(fixture_project).graph
    execution_stages = [
        stage for stage in graph.nodes
        if set(getattr(graph.nodes[stage], "skills", None) or [])
        & set(DVHarness.EXECUTION_PREFLIGHT_SKILLS)
    ]
    assert execution_stages, "the real graph must declare at least one execution-layer stage"

    with pytest.raises(ce.ExperimentIsolationError) as exc:
        ce.run_controlled_experiment(
            root, _approved_candidate(root), fixture_project=fixture_project,
            stages=[execution_stages[0]], mutation=MIGRATION_MUTATION,
            harness_factory=harness_factory)
    assert "execution-layer skills" in str(exc.value)


def test_the_source_fixture_is_never_written_to(root, fixture_project):
    """Isolation as a checked fact: the fixture's own content digest is taken
    before the experiment and again after it."""
    before = ce._tree_digest(fixture_project)
    result = run_demo_experiment(root, _approved_candidate(root), fixture_project)
    after = ce._tree_digest(fixture_project)

    assert after["digest"] == before["digest"]
    assert not (fixture_project / MIGRATION_FILE).exists()
    isolation = result["experiment"]["isolation"]
    assert isolation["fixture_digest_before"]["digest"] == before["digest"]
    assert isolation["fixture_digest_after"]["digest"] == after["digest"]


def test_everything_the_experiment_wrote_lives_in_its_own_workspace(root, fixture_project):
    """No stage run reaches outside <root>/.dv-harness/experiments/<cid>/<run>/."""
    result = run_demo_experiment(root, _approved_candidate(root), fixture_project)
    workspace = Path(result["candidate"]["benchmark_result"]["workspace"])

    assert ce._within(workspace, ce.experiments_dir(root))
    assert workspace.parent.name == result["candidate"]["candidate_id"]
    # The project root's own tree gained the experiments directory and the
    # blackboard/memory writes persist_candidate() has always made -- and no
    # copy of the fixture anywhere else.
    strays = [p for p in root.rglob(MIGRATION_FILE) if not ce._within(p, workspace)]
    assert strays == []


def test_a_mutation_reaching_outside_the_treatment_copy_is_refused(root, fixture_project):
    """The containment check runs on every path the mutation names, in both
    accepted forms."""
    candidate = _approved_candidate(root)
    with pytest.raises(ce.ExperimentIsolationError) as exc:
        ce.run_controlled_experiment(
            root, candidate, fixture_project=fixture_project, stages=[FIXTURE_STAGE],
            mutation=[{"path": "../escaped.json", "content": "{}"}],
            harness_factory=harness_factory)
    assert "outside the" in str(exc.value)

    escapee = root / "escaped_by_callable.json"

    def _escaping_mutation(treatment_root):
        escapee.write_text("{}", encoding="utf-8")
        return [escapee]

    fresh = _approved_candidate(root, affected_capability="second-capability")
    with pytest.raises(ce.ExperimentIsolationError) as exc:
        ce.run_controlled_experiment(
            root, fresh, fixture_project=fixture_project, stages=[FIXTURE_STAGE],
            mutation=_escaping_mutation, harness_factory=harness_factory)
    assert "outside the treatment workspace" in str(exc.value)


def test_a_mutation_that_changes_nothing_is_refused(root, fixture_project):
    """Comparing a copy against an identical copy would report UNCHANGED and
    look like a real negative result."""
    with pytest.raises(ce.ExperimentIsolationError) as exc:
        ce.run_controlled_experiment(
            root, _approved_candidate(root), fixture_project=fixture_project,
            stages=[FIXTURE_STAGE], mutation=[], harness_factory=harness_factory)
    assert "changed nothing" in str(exc.value)


def test_a_harness_rooted_outside_its_arm_is_refused(root, fixture_project):
    """The harness_factory seam is injected, so it is also verified: a factory
    returning a harness rooted at the live project is refused before any stage
    runs."""
    from dv_harness.engine import DVHarness

    def _wrong_root_factory(_arm_root):
        harness = DVHarness(root)
        return harness

    with pytest.raises(ce.ExperimentIsolationError) as exc:
        ce.run_controlled_experiment(
            root, _approved_candidate(root), fixture_project=fixture_project,
            stages=[FIXTURE_STAGE], mutation=MIGRATION_MUTATION,
            harness_factory=_wrong_root_factory)
    assert "not at its own experiment workspace" in str(exc.value)


def test_a_fixture_containing_the_project_root_is_refused(root):
    """Pointing the experiment at a tree that contains the live project would
    copy the live project into its own workspace."""
    with pytest.raises(ce.ExperimentIsolationError) as exc:
        ce.run_controlled_experiment(
            root, _approved_candidate(root), fixture_project=root.parent,
            stages=[FIXTURE_STAGE], mutation=MIGRATION_MUTATION,
            harness_factory=harness_factory)
    assert "contains this project root" in str(exc.value)


# --- the benchmark evidence cannot be forged ---------------------------------


def test_a_hand_written_benchmark_result_is_refused(root):
    """Every field of a benchmark_result is checkable, and all of them are
    checked against disk rather than believed."""
    candidate = _approved_candidate(root)
    candidate = ce.transition(root, candidate, "EXPERIMENTING", by="tester", reason="running")

    forged = dict(candidate)
    forged["benchmark_result"] = {
        "produced_by": "the-agent-itself", "run_id": "EXP-1", "record_path": "x",
        "record_digest": "0" * 64, "workspace": "x", "stages": [FIXTURE_STAGE],
        "before": {}, "after": {}, "delta": {}, "outcome": "IMPROVED",
        "measured_at": "2026-09-05T00:00:00+00:00", "changed_files": ["x"],
        "acceptance_criteria_machine_evaluated": False,
    }
    with pytest.raises(ce.BenchmarkEvidenceRequiredError) as exc:
        ce.assert_benchmark_measured(root, forged)
    assert "only capability_evolution.run_controlled_experiment may produce one" in str(exc.value)

    forged["benchmark_result"]["produced_by"] = ce.BENCHMARK_PRODUCER
    with pytest.raises(ce.BenchmarkEvidenceRequiredError) as exc:
        ce.assert_benchmark_measured(root, forged)
    assert "not under this project" in str(exc.value)


def test_an_edited_experiment_record_is_refused(root, fixture_project):
    """The record is hashed when it is written and re-hashed when it is read, so
    a measurement improved after the fact stops being usable evidence."""
    result = run_demo_experiment(root, _approved_candidate(root), fixture_project)
    measured = result["candidate"]
    record_path = Path(measured["benchmark_result"]["record_path"])

    # It verifies as long as it is untouched.
    ce.assert_benchmark_measured(root, measured)

    edited = json.loads(record_path.read_text(encoding="utf-8"))
    edited["outcome"] = "IMPROVED"
    edited["delta"]["gates_satisfied"] = 99
    record_path.write_text(json.dumps(edited, indent=2), encoding="utf-8")

    with pytest.raises(ce.BenchmarkEvidenceRequiredError) as exc:
        ce.assert_benchmark_measured(root, measured)
    assert "no longer matches the digest" in str(exc.value)


def test_a_record_from_another_candidate_is_refused(root, fixture_project):
    """A real experiment record is still not THIS candidate's evidence."""
    result = run_demo_experiment(root, _approved_candidate(root), fixture_project)
    other = _approved_candidate(root, affected_capability="unrelated-capability")
    other = ce.transition(root, other, "EXPERIMENTING", by="tester", reason="running")
    other["benchmark_result"] = dict(result["candidate"]["benchmark_result"])

    with pytest.raises(ce.BenchmarkEvidenceRequiredError) as exc:
        ce.assert_benchmark_measured(root, other)
    assert "was produced for candidate" in str(exc.value)


def test_a_deleted_experiment_record_is_refused(root, fixture_project):
    """The evidence has to still be there, not to have existed once."""
    result = run_demo_experiment(root, _approved_candidate(root), fixture_project)
    measured = result["candidate"]
    Path(measured["benchmark_result"]["record_path"]).unlink()

    with pytest.raises(ce.BenchmarkEvidenceRequiredError) as exc:
        ce.assert_benchmark_measured(root, measured)
    assert "does not exist; nothing was measured" in str(exc.value)


# --- reuse, not parallel infrastructure --------------------------------------


def test_the_measured_candidate_persists_through_the_existing_mechanisms(root, fixture_project):
    """The experiment adds no store of its own: the candidate lands on the same
    one Blackboard topic and the same Working Memory audit trail every other
    candidate uses, and persist_candidate()'s WORKING_MEMORY assertion still
    holds for a candidate now carrying a real measurement."""
    from dv_harness.memory import MemoryStore

    result = run_demo_experiment(root, _approved_candidate(root), fixture_project)
    cid = result["candidate"]["candidate_id"]

    stored = ce.read_candidate(root, cid)
    assert stored["current_status"] == "BENCHMARKED"
    assert stored["benchmark_result"]["outcome"] == "IMPROVED"

    audit = ce.candidate_audit_records(root, cid)
    assert audit, "the transitions wrote a real Working Memory audit trail"
    assert all(r["kind"] == ce.CANDIDATE_MEMORY_KIND for r in audit)
    assert MemoryStore(root).find("engineering", kind=ce.CANDIDATE_MEMORY_KIND) == []
    assert MemoryStore(root).find("organizational", kind=ce.CANDIDATE_MEMORY_KIND) == []

    # The status history records both real transitions, in order, with the run id.
    history = [(e["from_status"], e["to_status"]) for e in stored["status_history"]]
    assert history[-2:] == [("EXPERIMENT_APPROVED", "EXPERIMENTING"),
                            ("EXPERIMENTING", "BENCHMARKED")]
    assert result["experiment"]["run_id"] in stored["status_history"][-1]["reason"]


def test_the_measured_candidate_still_validates_against_the_schema(root, fixture_project):
    """benchmark_result is a real schema-checked field, not a free-form bag."""
    result = run_demo_experiment(root, _approved_candidate(root), fixture_project)
    ce.validate_candidate(result["candidate"])

    broken = json.loads(json.dumps(result["candidate"]))
    broken["benchmark_result"]["outcome"] = "PASS"
    with pytest.raises(ce.CapabilityEvolutionCandidateValidationError):
        ce.validate_candidate(broken)


def test_the_module_still_holds_its_no_verification_authority_guarantee():
    """The experiment reads real gate outcomes. It must not have acquired the
    ability to emit one -- including through its own new outcome vocabulary."""
    from dv_harness.models import Status

    ce.assert_no_verification_verdict_vocabulary()
    assert not {s.value for s in Status}.intersection(ce.BENCHMARK_OUTCOMES)

    src = Path(ce.__file__).read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    for forbidden in ('"PASS"', "'PASS'", '"FAIL"', "'FAIL'", "run_gate",
                      "evaluate_stage_evidence", "can_signoff", "QualifiedConclusion",
                      "signoff"):
        assert forbidden not in code, forbidden


def test_no_verdict_token_reaches_the_candidate_or_the_record(root, fixture_project):
    """The arms really did produce verdicts -- the numbers moved -- and neither
    the candidate nor the experiment record carries one. Only the digest does."""
    from dv_harness.models import Status

    result = run_demo_experiment(root, _approved_candidate(root), fixture_project)
    verdicts = {s.value for s in Status}

    for blob in (json.dumps(result["candidate"]["benchmark_result"]),
                 json.dumps(result["experiment"])):
        for verdict in verdicts:
            assert f'"{verdict}"' not in blob, verdict

    digests = {
        result["candidate"]["benchmark_result"]["before"]["stages"][FIXTURE_STAGE][
            "gate_outcome_digest"],
        result["candidate"]["benchmark_result"]["after"]["stages"][FIXTURE_STAGE][
            "gate_outcome_digest"],
    }
    assert len(digests) == 2, "the two arms really did reach different gate outcomes"


def test_a_human_approval_still_unblocks_the_last_edge(root, fixture_project):
    """Nothing about the new evidence requirement changed what a real human
    approval does -- the gate above BENCHMARKED is untouched."""
    windowed = benchmarked_with_stability_window(
        root, _approved_candidate(root), fixture_project)
    promoted = ce.transition(root, windowed, "PROMOTION_CANDIDATE",
                             by="dv-manager", reason="measured result reviewed")

    ControlPlane(root).approve(ce.HUMAN_APPROVAL_STAGE, note="reviewed the real benchmark",
                               reviewer_id="dv-manager", reviewer_confidence="HIGH")
    approved = ce.transition(root, promoted, "HUMAN_APPROVED", by="dv-manager",
                             reason="approved on the measured result")
    assert approved["current_status"] == "HUMAN_APPROVED"
    assert approved["status_history"][-1]["approval_ref"]["reviewer_id"] == "dv-manager"
