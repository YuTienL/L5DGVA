"""Agent/Skill benchmark dataset governance (spec section 226), end to end.

The gap these tests close is that `capability_evolution.run_controlled_experiment()`
is per-CANDIDATE execution: one proposed change, one fixture, one measurement. It
answers "did this change help". Nothing answered "how does this agent score
against a VERSIONED corpus of cases with known expected outcomes, and was it
scored on the very examples it was tuned on".

Everything below is real. The datasets are the two synthetic corpora committed
under `fixtures/benchmark_datasets/` (clearly labelled as fixtures, derived from
no real project). The eval runner is `capability_evolution`'s OWN isolated
two-arm shadow run: two copies of the synthetic fixture project, the REAL
`DVHarness.run_stage()` in each arm, the REAL `command_migration_integrity_gate.py`
subprocess judging each arm's evidence, and the REAL
`control_plane.describe_stage()` producing both arms' numbers. The only stub is
the agent adapter -- and here that stub IS the subject under evaluation, which is
the point: two different adapters are two different Agent versions and score
differently on the same corpus.

The central test is `test_two_dataset_versions_produce_two_distinguishable_results`:
the SAME subject, evaluated against v1 and then against v2, produces two records
that disagree on status, on score, and on which case failed -- because v2 added a
harder case, and the version bump is what says so.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from dv_harness import benchmark_dataset as bd
from dv_harness import capability_evolution as ce

from .controlled_experiment_fixture import (
    MIGRATION_FILE,
    harness_factory as evidence_subject_factory,
    make_fixture_project,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "benchmark_datasets"
DATASET_ID = "command-pattern-evidence"

SUBJECT_A = {"subject_id": "command-pattern-evidence-agent",
             "subject_version": "1.0.0",
             "subject_kind": "AGENT_ADAPTER",
             "notes": "submits the migration manifest as gate evidence when one is present"}
SUBJECT_B = {"subject_id": "command-pattern-evidence-agent",
             "subject_version": "0.9.0",
             "subject_kind": "AGENT_ADAPTER",
             "notes": "an earlier version that never submits gate evidence"}


# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def root():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def fixtures_root():
    """A fixtures root holding the synthetic project every case's `fixture_ref`
    names, so `default_fixture_resolver()` is exercised for real."""
    tmp = Path(tempfile.mkdtemp())
    try:
        make_fixture_project(tmp / "command_pattern_project")
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def load_fixture_dataset(version: int) -> dict:
    return json.loads((FIXTURES / f"command_pattern_evidence_v{version}.json")
                      .read_text(encoding="utf-8"))


class NoEvidenceSubject:
    """Subject B: an earlier agent version that reads the project and reports,
    but never produces a gate evidence block. It is a real behavioural
    difference, not a broken adapter -- the harness runs the stage normally and
    simply has nothing to judge."""

    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
        from dv_harness.adapters.base import AgentResult

        present = (Path(cwd) / MIGRATION_FILE).exists()
        return AgentResult(
            ok=True,
            text=("I inspected the project. A command migration manifest is "
                  f"{'present' if present else 'absent'}. I am not producing migration "
                  "integrity evidence in this version."),
            raw={}, session_id=None)


def no_evidence_subject_factory(project_root):
    from dv_harness.engine import DVHarness

    harness = DVHarness(Path(project_root))
    harness.adapter = NoEvidenceSubject()
    return harness


def eval_against(root, fixtures_root, version, subject, factory=evidence_subject_factory):
    return bd.run_benchmark_eval(
        root, DATASET_ID, subject=subject,
        fixture_resolver=bd.default_fixture_resolver(fixtures_root),
        harness_factory=factory, version=version)


# --- the versioned registry -------------------------------------------------


def test_registering_a_version_records_a_real_content_digest(root):
    stored = bd.register_dataset_version(root, load_fixture_dataset(1))
    assert stored["version"] == 1 and stored["previous_version"] is None
    assert len(stored["cases"]) == 3
    assert stored["content_digest"] == bd.dataset_content_digest(stored["cases"])
    assert set(stored["case_digests"]) == {c["case_id"] for c in stored["cases"]}
    assert bd.version_path(root, DATASET_ID, 1).is_file()
    assert bd.list_versions(root, DATASET_ID) == [1]
    assert bd.list_datasets(root) == [DATASET_ID]


def test_re_registering_the_same_version_is_idempotent(root):
    first = bd.register_dataset_version(root, load_fixture_dataset(1))
    again = bd.register_dataset_version(root, load_fixture_dataset(1))
    assert again["content_digest"] == first["content_digest"]
    assert again["registered_at"] == first["registered_at"]  # nothing was rewritten


def test_a_registered_version_is_immutable_and_must_be_bumped(root):
    bd.register_dataset_version(root, load_fixture_dataset(1))
    edited = load_fixture_dataset(1)
    edited["cases"][0]["expected_result"] = "UNCHANGED"
    with pytest.raises(bd.DatasetVersionConflictError) as exc:
        bd.register_dataset_version(root, edited)
    assert "immutable" in str(exc.value) and "bump to v2" in str(exc.value)


def test_re_registering_over_a_drifted_version_is_refused_not_blessed(root):
    """The hole an idempotence check alone leaves open: the stored version's
    recorded digest still matches what is being offered, while its cases on disk
    no longer do."""
    bd.register_dataset_version(root, load_fixture_dataset(1))
    path = bd.version_path(root, DATASET_ID, 1)
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["cases"][0]["owner"] = "someone-else"
    path.write_text(json.dumps(stored, indent=2), encoding="utf-8")

    with pytest.raises(bd.DatasetVersionConflictError) as exc:
        bd.register_dataset_version(root, load_fixture_dataset(1))
    assert bd.INTEGRITY_DRIFT in str(exc.value) and "bless the drift" in str(exc.value)


def test_a_bump_that_changes_no_case_is_refused(root):
    bd.register_dataset_version(root, load_fixture_dataset(1))
    pointless = load_fixture_dataset(1)
    pointless["version"] = 2
    with pytest.raises(bd.DatasetVersionConflictError) as exc:
        bd.register_dataset_version(root, pointless)
    assert "changes no case is not a new dataset version" in str(exc.value)


def test_a_version_may_not_be_back_dated(root):
    """Filling in a version number BELOW the latest -- the case an
    already-registered-version check cannot see, because that file is absent."""
    bd.register_dataset_version(root, load_fixture_dataset(1))
    v3 = load_fixture_dataset(2)
    v3["version"] = 3
    bd.register_dataset_version(root, v3)
    assert bd.list_versions(root, DATASET_ID) == [1, 3]

    back = load_fixture_dataset(2)  # version 2, which does not exist yet
    with pytest.raises(bd.DatasetVersionConflictError) as exc:
        bd.register_dataset_version(root, back)
    assert "back-date" in str(exc.value)


def test_a_version_bump_is_detected_and_named(root):
    """THE BUMP, as a diff over case CONTENT digests -- not over case ids, and
    not over a version number someone typed."""
    bd.register_dataset_version(root, load_fixture_dataset(1))
    bd.register_dataset_version(root, load_fixture_dataset(2))

    diff = bd.diff_dataset_versions(root, DATASET_ID, 1, 2)
    assert diff["bumped"] is True
    assert diff["old_content_digest"] != diff["new_content_digest"]
    assert diff["added_case_ids"] == ["mismatched-hashes-expect-repair"]
    assert diff["removed_case_ids"] == [] and diff["modified_case_ids"] == []
    assert len(diff["unchanged_case_ids"]) == 3

    # And a MODIFIED case is reported as modified, not as an add plus a remove.
    v3 = load_fixture_dataset(2)
    v3["version"] = 3
    v3["cases"][1]["known_ambiguity"] = "rewritten for v3"
    bd.register_dataset_version(root, v3)
    diff23 = bd.diff_dataset_versions(root, DATASET_ID, 2, 3)
    assert diff23["modified_case_ids"] == ["manifest-mismatched-hashes"]
    assert diff23["added_case_ids"] == [] and diff23["removed_case_ids"] == []


def test_editing_a_case_in_place_is_reported_as_content_drift(root):
    """The failure mode a version number alone cannot catch: someone edits a
    stored case and the version still claims to be v1."""
    bd.register_dataset_version(root, load_fixture_dataset(1))
    assert bd.verify_dataset_integrity(root, DATASET_ID, 1)["status"] == bd.INTEGRITY_OK

    path = bd.version_path(root, DATASET_ID, 1)
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["cases"][2]["expected_result"] = "IMPROVED"
    path.write_text(json.dumps(stored, indent=2), encoding="utf-8")

    report = bd.verify_dataset_integrity(root, DATASET_ID, 1)
    assert report["status"] == bd.INTEGRITY_DRIFT
    assert report["drifted_case_ids"] == ["no-manifest-unrelated-file"]
    assert "edited in place" in report["detail"]


def test_validation_refuses_a_case_that_cannot_be_governed_or_run():
    base = load_fixture_dataset(1)

    def broken(**mutate):
        data = json.loads(json.dumps(base))
        data["cases"][0].update(mutate)
        return data

    for mutate, needle in (
        ({"difficulty": "TRIVIAL"}, "difficulty must be one of"),
        ({"qualification": "PROBABLY_FINE"}, "qualification must be one of"),
        ({"expected_result": "PASS"}, "BENCHMARK_OUTCOMES"),
        ({"known_ambiguity": None}, "known_ambiguity must be a string"),
        ({"project_coverage": []}, "project_coverage must be a non-empty list"),
        ({"stages": []}, "stages must be a non-empty list"),
        ({"mutation": []}, "mutation must be a non-empty list"),
        ({"mutation": [{"path": "../escape.txt", "content": "x"}]}, "must be a relative path"),
        ({"owner": "  "}, "owner must be a non-empty string"),
    ):
        with pytest.raises(bd.DatasetValidationError) as exc:
            bd.validate_dataset(broken(**mutate))
        assert needle in str(exc.value), (mutate, str(exc.value))

    missing = json.loads(json.dumps(base))
    del missing["cases"][0]["provenance"]
    with pytest.raises(bd.DatasetValidationError) as exc:
        bd.validate_dataset(missing)
    assert "section 226 requires every tracked field" in str(exc.value)

    duplicated = json.loads(json.dumps(base))
    duplicated["cases"].append(json.loads(json.dumps(duplicated["cases"][0])))
    with pytest.raises(bd.DatasetValidationError):
        bd.validate_dataset(duplicated)


def test_benchmark_vocabulary_is_disjoint_from_the_verification_verdicts():
    """A benchmark score must never be greppable as a DV verdict -- the same
    rule capability_evolution enforces on its own four vocabularies."""
    bd.assert_no_verification_verdict_vocabulary()
    ce.assert_no_verification_verdict_vocabulary()


# --- train/test leakage -----------------------------------------------------


def test_leakage_is_keyed_on_case_content_not_case_id(root):
    """A case used to tune a subject stays leaked when it is carried into the
    next dataset version unchanged, and stops being leaked when the case itself
    is genuinely rewritten. Renaming it launders nothing."""
    bd.register_dataset_version(root, load_fixture_dataset(1))
    bd.register_dataset_version(root, load_fixture_dataset(2))
    bd.record_tuning_use(root, DATASET_ID, "manifest-matching-hashes",
                         subject_id=SUBJECT_A["subject_id"],
                         subject_version=SUBJECT_A["subject_version"],
                         used_for="tuned the evidence-block emitter on this case",
                         version=1)

    v1 = bd.leakage_report(root, DATASET_ID, subject_id=SUBJECT_A["subject_id"],
                           subject_version=SUBJECT_A["subject_version"], version=1)
    assert v1["status"] == bd.LEAKAGE_PARTIAL
    assert v1["leaked_case_ids"] == ["manifest-matching-hashes"] and v1["held_out_count"] == 2

    # carried into v2 unchanged -> still leaked, though the use was recorded on v1
    v2 = bd.leakage_report(root, DATASET_ID, subject_id=SUBJECT_A["subject_id"],
                           subject_version=SUBJECT_A["subject_version"], version=2)
    assert v2["leaked_case_ids"] == ["manifest-matching-hashes"] and v2["held_out_count"] == 3

    # renamed but otherwise identical -> the content digest is unchanged, so the
    # leakage follows it; genuinely rewritten -> it does not.
    v3 = load_fixture_dataset(2)
    v3["version"] = 3
    v3["cases"][0]["case_id"] = "manifest-matching-hashes-renamed"
    bd.register_dataset_version(root, v3)
    renamed = bd.leakage_report(root, DATASET_ID, subject_id=SUBJECT_A["subject_id"],
                                subject_version=SUBJECT_A["subject_version"], version=3)
    assert renamed["leaked_case_ids"] == ["manifest-matching-hashes-renamed"]

    v4 = load_fixture_dataset(2)
    v4["version"] = 4
    v4["cases"][0]["expected_result"] = "UNCHANGED"  # a different question entirely
    bd.register_dataset_version(root, v4)
    rewritten = bd.leakage_report(root, DATASET_ID, subject_id=SUBJECT_A["subject_id"],
                                   subject_version=SUBJECT_A["subject_version"], version=4)
    assert rewritten["status"] == bd.LEAKAGE_CLEAN and rewritten["leaked_case_ids"] == []


def test_a_tuning_use_on_another_subject_version_is_related_not_leaked(root):
    bd.register_dataset_version(root, load_fixture_dataset(1))
    bd.record_tuning_use(root, DATASET_ID, "manifest-matching-hashes",
                         subject_id=SUBJECT_A["subject_id"],
                         subject_version="0.9.0",
                         used_for="tuned the previous agent version on this case")
    report = bd.leakage_report(root, DATASET_ID, subject_id=SUBJECT_A["subject_id"],
                               subject_version="1.0.0")
    assert report["status"] == bd.LEAKAGE_CLEAN
    assert report["related_tuning_use_case_ids"] == ["manifest-matching-hashes"]


def test_a_tuning_use_must_name_a_real_case_and_a_real_subject(root):
    bd.register_dataset_version(root, load_fixture_dataset(1))
    with pytest.raises(bd.DatasetNotFoundError):
        bd.record_tuning_use(root, DATASET_ID, "no-such-case", subject_id="a",
                             subject_version="1", used_for="x")
    with pytest.raises(bd.DatasetValidationError):
        bd.record_tuning_use(root, DATASET_ID, "manifest-matching-hashes",
                             subject_id="a", subject_version="", used_for="x")
    with pytest.raises(bd.DatasetValidationError):
        bd.record_tuning_use(root, DATASET_ID, "manifest-matching-hashes",
                             subject_id="a", subject_version="1", used_for="   ")


# --- the eval runner: REAL two-arm shadow runs ------------------------------


def test_two_dataset_versions_produce_two_distinguishable_results(root, fixtures_root):
    """THE CENTRAL TEST. One subject, two dataset versions, two real evaluations.

    Every case here is a real isolated two-arm run through the real engine stage
    runner and the real gate subprocess. v1's three cases are all met; v2 adds a
    harder held-back case this subject version does not handle, and the result
    differs in status, in score, in the failing case, and in the dataset digest
    it cites."""
    bd.register_dataset_version(root, load_fixture_dataset(1))
    bd.register_dataset_version(root, load_fixture_dataset(2))

    r1 = eval_against(root, fixtures_root, 1, SUBJECT_A)
    r2 = eval_against(root, fixtures_root, 2, SUBJECT_A)

    # -- distinguishable, on every axis that matters
    assert r1["status"] == bd.RUN_MET and r2["status"] == bd.RUN_NOT_MET
    assert (r1["dataset_version"], r2["dataset_version"]) == (1, 2)
    assert r1["dataset_content_digest"] != r2["dataset_content_digest"]
    assert r1["summary"]["total"] == 3 and r2["summary"]["total"] == 4
    assert r1["summary"]["matched"] == 3 and r2["summary"]["matched"] == 3
    assert r1["summary"]["mismatched_case_ids"] == []
    assert r2["summary"]["mismatched_case_ids"] == ["mismatched-hashes-expect-repair"]
    assert r1["summary"]["held_out_match_rate"] == 1.0
    assert r2["summary"]["held_out_match_rate"] == 0.75
    assert r1["run_id"] != r2["run_id"]

    # -- and per-case, the outcomes are the ones the real gate produced
    by_case = {c["case_id"]: c for c in r2["cases"]}
    assert by_case["manifest-matching-hashes"]["observed_result"] == "IMPROVED"
    assert by_case["manifest-mismatched-hashes"]["observed_result"] == "UNCHANGED"
    assert by_case["no-manifest-unrelated-file"]["observed_result"] == "UNCHANGED"
    assert by_case["mismatched-hashes-expect-repair"]["observed_result"] == "UNCHANGED"
    assert by_case["mismatched-hashes-expect-repair"]["expected_result"] == "IMPROVED"
    assert by_case["mismatched-hashes-expect-repair"]["outcome"] == bd.CASE_MISMATCHED

    # -- each case really ran: a real record, in a real workspace, with two real
    #    arms measured through the real describe_stage() read path
    for case in r2["cases"]:
        record_path = Path(case["record_path"])
        assert record_path.is_file()
        assert ce._within(record_path, ce.experiments_dir(root))
        record = json.loads(record_path.read_text(encoding="utf-8"))
        assert record["isolation"]["fixture_unmodified"] is True
        assert record["isolation"]["execution_stages_allowed"] is False
        for arm in ("baseline", "treatment"):
            assert (Path(case["workspace"]) / arm / ".dv-harness").is_dir()
            assert record[{"baseline": "before", "treatment": "after"}[arm]]["arm"] == arm
    improved = json.loads(Path(by_case["manifest-matching-hashes"]["record_path"])
                          .read_text(encoding="utf-8"))
    assert improved["before"]["totals"]["gates_satisfied"] == 0
    assert improved["after"]["totals"]["gates_satisfied"] == 1

    # -- both runs are on disk and readable back
    runs = bd.read_eval_runs(root, DATASET_ID)
    assert [r["dataset_version"] for r in runs] == [1, 2]


def test_a_result_identifies_the_subject_version_and_the_environment(root, fixtures_root):
    """Section 226: "Benchmark results must identify Agent/Skill version and
    environment." Read, not declared."""
    single = load_fixture_dataset(1)
    single["cases"] = single["cases"][:1]
    bd.register_dataset_version(root, single)

    record = eval_against(root, fixtures_root, 1, SUBJECT_A)
    assert record["subject"]["subject_id"] == SUBJECT_A["subject_id"]
    assert record["subject"]["subject_version"] == "1.0.0"
    assert record["subject"]["subject_kind"] == "AGENT_ADAPTER"
    env = record["environment"]
    assert env["python_version"] and env["platform"] and env["harness_root"] == str(root)
    assert "harness_git_sha" in env  # None on a machine with no git is honest, not absent
    assert record["produced_by"] == bd.BENCHMARK_EVAL_PRODUCER

    with pytest.raises(bd.DatasetValidationError) as exc:
        bd.run_benchmark_eval(root, DATASET_ID, subject={"subject_id": "x"},
                              fixture_resolver=bd.default_fixture_resolver(fixtures_root),
                              harness_factory=evidence_subject_factory)
    assert "identify the subject_id and subject_version" in str(exc.value)


def test_two_subject_versions_score_differently_on_the_same_dataset(root, fixtures_root):
    """The other half of "distinguishable": the corpus is fixed and the subject
    moves. An earlier agent version that never submits evidence does not meet the
    case the current one meets."""
    single = load_fixture_dataset(1)
    single["cases"] = single["cases"][:1]
    bd.register_dataset_version(root, single)

    current = eval_against(root, fixtures_root, 1, SUBJECT_A)
    earlier = eval_against(root, fixtures_root, 1, SUBJECT_B,
                           factory=no_evidence_subject_factory)

    assert current["status"] == bd.RUN_MET and earlier["status"] == bd.RUN_NOT_MET
    assert current["cases"][0]["observed_result"] == "IMPROVED"
    assert earlier["cases"][0]["observed_result"] == "UNCHANGED"
    assert current["dataset_content_digest"] == earlier["dataset_content_digest"]


def test_an_eval_on_only_tuning_examples_is_inadmissible(root, fixtures_root):
    """Section 226's rule as a status: "Do not evaluate a capability only on
    examples used to tune it." Every case matched, and the run still does not
    count."""
    single = load_fixture_dataset(1)
    single["cases"] = single["cases"][:1]
    bd.register_dataset_version(root, single)
    bd.record_tuning_use(root, DATASET_ID, "manifest-matching-hashes",
                         subject_id=SUBJECT_A["subject_id"],
                         subject_version=SUBJECT_A["subject_version"],
                         used_for="tuned the evidence-block emitter on this exact case")

    record = eval_against(root, fixtures_root, 1, SUBJECT_A)
    assert record["cases"][0]["outcome"] == bd.CASE_MATCHED
    assert record["cases"][0]["used_for_tuning"] is True
    assert record["summary"]["matched"] == 1
    assert record["summary"]["held_out_total"] == 0
    assert record["leakage"]["status"] == bd.LEAKAGE_FULL
    assert record["status"] == bd.RUN_INADMISSIBLE


def test_an_eval_refuses_a_drifted_dataset_version(root, fixtures_root):
    """A result must cite a corpus that still describes what was run."""
    bd.register_dataset_version(root, load_fixture_dataset(1))
    path = bd.version_path(root, DATASET_ID, 1)
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["cases"][0]["expected_result"] = "UNCHANGED"
    path.write_text(json.dumps(stored, indent=2), encoding="utf-8")

    with pytest.raises(bd.DatasetVersionConflictError) as exc:
        eval_against(root, fixtures_root, 1, SUBJECT_A)
    assert bd.INTEGRITY_DRIFT in str(exc.value)
    assert not bd.read_eval_runs(root, DATASET_ID)


def test_a_case_that_cannot_be_resolved_is_errored_not_matched(root, fixtures_root):
    """A case the runner could not execute is never a match, and the reason is
    recorded rather than dropped."""
    single = load_fixture_dataset(1)
    single["cases"] = single["cases"][:1]
    single["cases"][0]["fixture_ref"] = "no_such_fixture_project"
    bd.register_dataset_version(root, single)

    record = eval_against(root, fixtures_root, 1, SUBJECT_A)
    case = record["cases"][0]
    assert case["outcome"] == bd.CASE_ERRORED and case["observed_result"] is None
    assert "does not exist" in case["error"]
    assert record["status"] == bd.RUN_NOT_MET
    assert record["summary"]["errored"] == 1


# --- the governance boundary this must not cross ---------------------------


def test_an_eval_mints_no_candidate_and_can_never_back_a_promotion(root, fixtures_root):
    """A benchmark eval evaluates an AGENT. It is not evidence for promoting a
    capability-evolution candidate, and the two must not be confusable: no
    transition is made, no candidate is written, and the records it leaves in the
    experiments directory are refused by the stability window's own pin check."""
    single = load_fixture_dataset(1)
    single["cases"] = single["cases"][:1]
    bd.register_dataset_version(root, single)
    record = eval_against(root, fixtures_root, 1, SUBJECT_A)

    assert bd.BENCHMARK_EVAL_PRODUCER not in ce.SHADOW_RUN_PRODUCERS
    assert ce.read_candidates(root) == {}
    assert not (Path(root) / ".dv-harness" / "blackboard"
                / "capability_evolution_candidates.json").exists()

    case = record["cases"][0]
    case_record = json.loads(Path(case["record_path"]).read_text(encoding="utf-8"))
    assert case_record["produced_by"] == bd.BENCHMARK_EVAL_PRODUCER
    assert case_record["run_kind"] == bd.CASE_RUN_KIND
    assert not case_record["candidate_id"].startswith("CEC-")

    # And if someone hands that record to the stability window as a pin, it is
    # rejected on the producer check -- the same check that already refuses a
    # hand-written experiment.json.
    pin = {"produced_by": case_record["produced_by"], "run_id": case_record["run_id"],
           "record_path": case["record_path"],
           "record_digest": ce._sha256_text(
               Path(case["record_path"]).read_text(encoding="utf-8"))}
    judged = ce._read_pinned_run(root, case_record["candidate_id"], pin)
    assert judged["admissible"] is False
    assert "not a shadow-run producer" in judged["reason"]


def test_a_case_can_never_reach_the_execution_layer(root, fixtures_root):
    """`allow_execution_stages` is hard-wired False in the eval runner, so a
    stored corpus can never spend farm resources. A case naming an
    execution-layer stage stops the eval loudly rather than running one."""
    single = load_fixture_dataset(1)
    single["cases"] = single["cases"][:1]
    single["cases"][0]["stages"] = ["BUILD"]
    bd.register_dataset_version(root, single)

    with pytest.raises(bd.BenchmarkEvalIsolationError) as exc:
        eval_against(root, fixtures_root, 1, SUBJECT_A)
    assert "isolation" in str(exc.value)


# --- the CLI ---------------------------------------------------------------


def test_cli_registers_verifies_diffs_and_reports_leakage(root, tmp_path):
    """One shared implementation with `dv-harness benchmark-dataset`, same
    convention as power-intent and golden-scenario."""
    v1_file = tmp_path / "v1.json"
    v1_file.write_text(json.dumps(load_fixture_dataset(1)), encoding="utf-8")
    v2_file = tmp_path / "v2.json"
    v2_file.write_text(json.dumps(load_fixture_dataset(2)), encoding="utf-8")

    text, code = bd.execute_verb("list", root=root)
    assert code == 2 and "NOT_AVAILABLE" in text

    for path in (v1_file, v2_file):
        text, code = bd.execute_verb("register", root=root, json_file=str(path))
        assert code == 0 and "registered command-pattern-evidence" in text

    text, code = bd.execute_verb("verify", root=root, dataset_id=DATASET_ID)
    assert code == 0 and bd.INTEGRITY_OK in text

    text, code = bd.execute_verb("diff", root=root, dataset_id=DATASET_ID,
                                 old_version=1, new_version=2)
    assert code == 0 and "BUMPED" in text and "mismatched-hashes-expect-repair" in text

    text, code = bd.execute_verb("leakage", root=root, dataset_id=DATASET_ID,
                                 subject_id=SUBJECT_A["subject_id"],
                                 subject_version=SUBJECT_A["subject_version"])
    assert code == 0 and bd.LEAKAGE_CLEAN in text

    text, code = bd.execute_verb("record-tuning-use", root=root, dataset_id=DATASET_ID,
                                 case_id="manifest-matching-hashes",
                                 subject_id=SUBJECT_A["subject_id"],
                                 subject_version=SUBJECT_A["subject_version"],
                                 used_for="tuned on this case")
    assert code == 0
    text, code = bd.execute_verb("leakage", root=root, dataset_id=DATASET_ID,
                                 subject_id=SUBJECT_A["subject_id"],
                                 subject_version=SUBJECT_A["subject_version"])
    assert code == 1 and bd.LEAKAGE_PARTIAL in text

    # drift is an exit-1 finding, not a silent pass
    path = bd.version_path(root, DATASET_ID, 1)
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["cases"][0]["difficulty"] = "EXPERT"
    path.write_text(json.dumps(stored, indent=2), encoding="utf-8")
    text, code = bd.execute_verb("verify", root=root, dataset_id=DATASET_ID)
    assert code == 1 and bd.INTEGRITY_DRIFT in text

    text, code = bd.execute_verb("runs", root=root, dataset_id=DATASET_ID)
    assert code == 2 and "NOT_AVAILABLE" in text


def test_both_real_cli_entry_points_share_one_implementation(root, tmp_path):
    """`python -m dv_harness.benchmark_dataset` and `dv-harness benchmark-dataset`,
    driven as REAL subprocesses, and their exit codes asserted."""
    v1_file = tmp_path / "v1.json"
    v1_file.write_text(json.dumps(load_fixture_dataset(1)), encoding="utf-8")

    def module(*args):
        return subprocess.run(
            [sys.executable, "-m", "dv_harness.benchmark_dataset", *args,
             "--root", str(root)],
            capture_output=True, text=True, timeout=180, encoding="utf-8",
            errors="replace", cwd=str(Path(__file__).resolve().parents[1]))

    def cli(*args):
        return subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(root),
             "benchmark-dataset", *args],
            capture_output=True, text=True, timeout=180, encoding="utf-8",
            errors="replace", cwd=str(Path(__file__).resolve().parents[1]))

    empty = module("list")
    assert empty.returncode == 2 and "NOT_AVAILABLE" in empty.stdout

    reg = module("register", "--json-file", str(v1_file))
    assert reg.returncode == 0, reg.stdout + reg.stderr
    assert "registered command-pattern-evidence v1" in reg.stdout

    listed = cli("list", "--json")
    assert listed.returncode == 0, listed.stdout + listed.stderr
    assert json.loads(listed.stdout)[0]["dataset_id"] == DATASET_ID

    ok = cli("verify", "--dataset-id", DATASET_ID)
    assert ok.returncode == 0 and bd.INTEGRITY_OK in ok.stdout

    path = bd.version_path(root, DATASET_ID, 1)
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["cases"][0]["owner"] = "someone-else"
    path.write_text(json.dumps(stored, indent=2), encoding="utf-8")

    drifted = module("verify", "--dataset-id", DATASET_ID, "--json")
    assert drifted.returncode == 1, drifted.stdout + drifted.stderr
    assert json.loads(drifted.stdout)[0]["status"] == bd.INTEGRITY_DRIFT

    conflict = cli("register", "--json-file", str(v1_file))
    assert conflict.returncode == 2
    assert "DatasetVersionConflictError" in conflict.stdout
