"""dv_harness_tests/test_checker_sb_qualification.py -- real tests for
dv_harness/checker_sb_qualification.py, including the required negative control proving the
module refuses to fabricate an answer when evidence is absent."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import checker_sb_qualification as csq
from dv_harness import models


# --- QualificationTrial construction / outcome derivation --------------------


def _trial(**overrides) -> csq.QualificationTrial:
    base = dict(
        trial_id="T1",
        component_id="usb3_link_scoreboard",
        component_kind="SCOREBOARD",
        defect_id="D1",
        injection_description="flipped one bit of the CRC check comparison in the TB model",
        injection_evidence="commit abc1234: deliberately introduced CRC-compare defect",
        component_verdict="FAIL",
        verdict_evidence="evidence_db normalized_evidence row EV-100 (job 42, verdict FAIL)",
    )
    base.update(overrides)
    return csq.QualificationTrial(**base)


def test_a_fail_verdict_on_a_defect_trial_is_a_confirmed_detection():
    t = _trial(component_verdict="FAILED")
    assert t.outcome == csq.OUTCOME_DETECTED


def test_a_pass_verdict_on_a_defect_trial_is_a_confirmed_false_pass():
    t = _trial(component_verdict="PASS")
    assert t.outcome == csq.OUTCOME_FALSE_PASS


def test_no_recorded_verdict_is_indeterminate_never_guessed():
    t = _trial(component_verdict=None, verdict_evidence=None)
    assert t.outcome == csq.OUTCOME_INDETERMINATE


def test_an_unrecognized_verdict_string_is_indeterminate_never_guessed():
    t = _trial(component_verdict="ABORTED", verdict_evidence="evidence_db row EV-200")
    assert t.outcome == csq.OUTCOME_INDETERMINATE


def test_trial_with_no_injection_evidence_is_refused():
    with pytest.raises(csq.CheckerSbQualificationError):
        _trial(injection_evidence="")


def test_trial_with_a_verdict_but_no_verdict_evidence_is_refused():
    with pytest.raises(csq.CheckerSbQualificationError):
        _trial(component_verdict="FAIL", verdict_evidence="")


def test_trial_with_invalid_component_kind_is_refused():
    with pytest.raises(csq.CheckerSbQualificationError):
        _trial(component_kind="MONITOR")


def test_trial_with_missing_defect_id_is_refused():
    with pytest.raises(csq.CheckerSbQualificationError):
        _trial(defect_id="   ")


# --- evaluate_component_qualification -----------------------------------------


def test_two_confirmed_detections_zero_false_pass_is_qualified():
    trials = [
        _trial(trial_id="T1", component_verdict="FAIL"),
        _trial(trial_id="T2", defect_id="D2", component_verdict="FAILED"),
    ]
    rec = csq.evaluate_component_qualification(trials)
    assert rec.status == csq.STATUS_QUALIFIED
    assert rec.detected_count == 2
    assert rec.false_pass_count == 0
    assert rec.confirmed_detections == ["T1", "T2"]


def test_one_confirmed_detection_is_only_partially_qualified():
    trials = [_trial(trial_id="T1", component_verdict="FAIL")]
    rec = csq.evaluate_component_qualification(trials)
    assert rec.status == csq.STATUS_PARTIALLY_QUALIFIED
    assert rec.detected_count == 1
    assert rec.false_pass_count == 0


def test_negative_control_no_trials_never_fabricates_a_verdict():
    """The required negative control: absent evidence must produce an honest, distinctly
    named status -- never a silently defaulted QUALIFIED or DISQUALIFIED."""
    rec = csq.no_trials_recorded("never_tested_scoreboard", "SCOREBOARD")
    assert rec.status == csq.STATUS_NO_TRIALS
    assert rec.trial_count == 0
    assert rec.detected_count == 0
    assert rec.false_pass_count == 0
    # And the function itself refuses to be called with zero trials, rather than silently
    # returning something plausible-looking.
    with pytest.raises(csq.CheckerSbQualificationError):
        csq.evaluate_component_qualification([])


def test_a_single_confirmed_false_pass_disqualifies_regardless_of_many_detections():
    """Worst-wins: five clean detections do not outweigh one confirmed false PASS."""
    trials = [
        _trial(trial_id=f"T{i}", defect_id=f"D{i}", component_verdict="FAIL")
        for i in range(1, 6)
    ] + [_trial(trial_id="T_BAD", defect_id="D_BAD", component_verdict="PASS")]
    rec = csq.evaluate_component_qualification(trials)
    assert rec.status == csq.STATUS_DISQUALIFIED
    assert rec.detected_count == 5
    assert rec.false_pass_count == 1
    assert rec.confirmed_false_passes == ["T_BAD"]


def test_all_indeterminate_trials_is_evidence_inconclusive_not_no_trials():
    trials = [
        _trial(trial_id="T1", component_verdict=None, verdict_evidence=None),
        _trial(trial_id="T2", defect_id="D2", component_verdict=None, verdict_evidence=None),
    ]
    rec = csq.evaluate_component_qualification(trials)
    assert rec.status == csq.STATUS_INCONCLUSIVE
    assert rec.trial_count == 2
    assert rec.indeterminate_count == 2


def test_mismatched_component_across_trials_is_refused():
    trials = [
        _trial(trial_id="T1", component_id="scb_a"),
        _trial(trial_id="T2", defect_id="D2", component_id="scb_b"),
    ]
    with pytest.raises(csq.CheckerSbQualificationError):
        csq.evaluate_component_qualification(trials)


def test_mismatched_component_kind_across_trials_is_refused():
    trials = [
        _trial(trial_id="T1", component_kind="SCOREBOARD"),
        _trial(trial_id="T2", defect_id="D2", component_kind="CHECKER"),
    ]
    with pytest.raises(csq.CheckerSbQualificationError):
        csq.evaluate_component_qualification(trials)


# --- evaluate_qualification_gate ----------------------------------------------


def test_gate_qualified_when_every_component_qualified():
    rec_a = csq.evaluate_component_qualification([
        _trial(trial_id="A1", component_id="scb_a", component_verdict="FAIL"),
        _trial(trial_id="A2", component_id="scb_a", defect_id="D2", component_verdict="FAIL"),
    ])
    rec_b = csq.evaluate_component_qualification([
        _trial(trial_id="B1", component_id="chk_b", component_kind="CHECKER", component_verdict="FAIL"),
        _trial(trial_id="B2", component_id="chk_b", component_kind="CHECKER", defect_id="D2",
              component_verdict="FAIL"),
    ])
    report = csq.evaluate_qualification_gate([rec_a, rec_b])
    assert report["verdict"] == csq.GATE_QUALIFIED
    assert report["disqualified"] == []
    assert report["incomplete"] == []


def test_gate_worst_wins_one_disqualified_outranks_many_qualified():
    good_records = [
        csq.evaluate_component_qualification([
            _trial(trial_id=f"G{i}_1", component_id=f"good_{i}", component_verdict="FAIL"),
            _trial(trial_id=f"G{i}_2", component_id=f"good_{i}", defect_id="D2",
                  component_verdict="FAIL"),
        ])
        for i in range(5)
    ]
    bad_record = csq.evaluate_component_qualification([
        _trial(trial_id="BAD1", component_id="bad_one", component_verdict="FAIL"),
        _trial(trial_id="BAD2", component_id="bad_one", defect_id="D2", component_verdict="PASS"),
    ])
    report = csq.evaluate_qualification_gate(good_records + [bad_record])
    assert report["verdict"] == csq.GATE_NOT_QUALIFIED
    assert report["disqualified"] == [{"component_id": "bad_one", "component_kind": "SCOREBOARD"}]


def test_gate_required_component_missing_from_records_is_incomplete_not_ignored():
    rec_a = csq.evaluate_component_qualification([
        _trial(trial_id="A1", component_id="scb_a", component_verdict="FAIL"),
        _trial(trial_id="A2", component_id="scb_a", defect_id="D2", component_verdict="FAIL"),
    ])
    report = csq.evaluate_qualification_gate(
        [rec_a], required_components=[("scb_a", "SCOREBOARD"), ("never_tested", "CHECKER")])
    assert report["verdict"] == csq.GATE_INCOMPLETE_EVIDENCE
    assert {"component_id": "never_tested", "component_kind": "CHECKER"} in report["incomplete"]


def test_gate_empty_input_is_incomplete_evidence_never_a_vacuous_qualified():
    report = csq.evaluate_qualification_gate([])
    assert report["verdict"] == csq.GATE_INCOMPLETE_EVIDENCE


def test_gate_duplicate_component_records_refused():
    rec_a = csq.evaluate_component_qualification([
        _trial(trial_id="A1", component_id="scb_a", component_verdict="FAIL"),
        _trial(trial_id="A2", component_id="scb_a", defect_id="D2", component_verdict="FAIL"),
    ])
    with pytest.raises(csq.CheckerSbQualificationError):
        csq.evaluate_qualification_gate([rec_a, rec_a])


# --- vocabulary collision guard ------------------------------------------------


def test_vocabulary_guard_passes_on_the_real_vocabularies():
    csq.assert_no_verification_verdict_vocabulary()  # must not raise


def test_vocabulary_guard_has_real_detection_power(monkeypatch):
    monkeypatch.setattr(csq, "QUALIFICATION_STATUSES", csq.QUALIFICATION_STATUSES + (models.Status.PASS.value,))
    with pytest.raises(AssertionError):
        csq.assert_no_verification_verdict_vocabulary()


# --- trial_from_dict / rendering / to_dict ------------------------------------


def test_trial_from_dict_round_trip():
    d = _trial().to_dict()
    d.pop("outcome")
    t2 = csq.trial_from_dict(d)
    assert t2.trial_id == "T1"
    assert t2.outcome == csq.OUTCOME_DETECTED


def test_trial_from_dict_rejects_unrecognized_field():
    d = _trial().to_dict()
    d["bogus_field"] = "x"
    with pytest.raises(csq.CheckerSbQualificationError):
        csq.trial_from_dict(d)


def test_trial_from_dict_rejects_non_dict():
    with pytest.raises(csq.CheckerSbQualificationError):
        csq.trial_from_dict("not a dict")


def test_render_qualification_markdown_contains_verdict_and_component():
    rec = csq.evaluate_component_qualification([
        _trial(trial_id="A1", component_id="scb_a", component_verdict="FAIL"),
        _trial(trial_id="A2", component_id="scb_a", defect_id="D2", component_verdict="FAIL"),
    ])
    report = csq.evaluate_qualification_gate([rec])
    md = csq.render_qualification_markdown(report)
    assert "QUALIFIED" in md
    assert "scb_a" in md


# --- CLI ------------------------------------------------------------------------


def _write_trials(tmp_path: Path, trials: list) -> Path:
    p = tmp_path / "trials.json"
    p.write_text(json.dumps({"trials": trials}), encoding="utf-8")
    return p


def _run_cli(args, cwd) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.checker_sb_qualification"] + args,
        cwd=str(cwd), capture_output=True, text=True, timeout=60)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_cli_qualified_exit_code_zero(tmp_path):
    trials = [
        _trial(trial_id="A1", component_id="scb_a", component_verdict="FAIL").to_dict(),
        _trial(trial_id="A2", component_id="scb_a", defect_id="D2", component_verdict="FAIL").to_dict(),
    ]
    for t in trials:
        t.pop("outcome")
    trials_file = _write_trials(tmp_path, trials)
    proc = _run_cli(["evaluate", "--trials", str(trials_file), "--json"], _repo_root())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == csq.GATE_QUALIFIED


def test_cli_disqualified_exit_code_one(tmp_path):
    trials = [
        _trial(trial_id="A1", component_id="scb_a", component_verdict="FAIL").to_dict(),
        _trial(trial_id="A2", component_id="scb_a", defect_id="D2", component_verdict="PASS").to_dict(),
    ]
    for t in trials:
        t.pop("outcome")
    trials_file = _write_trials(tmp_path, trials)
    proc = _run_cli(["evaluate", "--trials", str(trials_file), "--json"], _repo_root())
    assert proc.returncode == 1, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == csq.GATE_NOT_QUALIFIED


def test_cli_malformed_trials_file_exit_code_two(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json", encoding="utf-8")
    proc = _run_cli(["evaluate", "--trials", str(p)], _repo_root())
    assert proc.returncode == 2, proc.stdout + proc.stderr


def test_cli_missing_trials_arg_exit_code_two():
    proc = _run_cli(["evaluate"], _repo_root())
    assert proc.returncode == 2, proc.stdout + proc.stderr


def test_cli_required_missing_component_exit_code_two(tmp_path):
    trials = [
        _trial(trial_id="A1", component_id="scb_a", component_verdict="FAIL").to_dict(),
        _trial(trial_id="A2", component_id="scb_a", defect_id="D2", component_verdict="FAIL").to_dict(),
    ]
    for t in trials:
        t.pop("outcome")
    trials_file = _write_trials(tmp_path, trials)
    proc = _run_cli(
        ["evaluate", "--trials", str(trials_file), "--required", "never_tested:CHECKER", "--json"],
        _repo_root())
    assert proc.returncode == 2, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == csq.GATE_INCOMPLETE_EVIDENCE
