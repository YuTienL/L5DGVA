"""Tests for dv_harness/answer_inconsistency_fatigue_detection.py -- a real
detector over a session's real sequence of answers, reusing
user_answer_validator.validate_answer() as the per-answer signal, and a real
save-and-resume checkpoint offer wrapping intake_baseline.freeze_intake_baseline()
unmodified.

No verible binary is required anywhere in this suite: every module-existence
("DUT top") claim is exercised with NO rtl_files supplied at all (which
correctly reports UNVERIFIABLE, and is exactly what this module's self-
contradiction detector needs -- it operates on the extracted target, not on
whether the underlying evidence check could run), and every build-inclusion
claim is checked against a plain, hand-built dut_facts_rtl dict (no RTL
parsing involved at all).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dv_harness import answer_inconsistency_fatigue_detection as aif  # noqa: E402
from dv_harness import intake_baseline as ib  # noqa: E402
from dv_harness import user_answer_validator as uav  # noqa: E402


def _dut_facts_rtl(*included_files):
    return {"status": "PARSED", "files": [{"file_path": f} for f in included_files]}


COMPLETE_FACTS = {
    "dut_top_boundary": {"top_module": "usb3_link_top"},
    "dut_sha": "a" * 64,
    "tb_sha": "b" * 64,
    "source_file_hashes": {"src/env.sv": "content"},
    "vip_declaration": {"vip_type": "usb3"},
    "bind_topology_hash": "c" * 40,
    "reference_uvm_hash": "d" * 40,
    "de_command_txt_hash": "raw command.txt text",
    "known_test_list": ["smoke_test"],
    "unresolved_critical_unknowns_count": 1,
    "unresolved_conflicts_count": 0,
    "recorded_user_decisions_count": 2,
}


# ---------------------------------------------------------------------------
# validate_session_answers -- reuse of user_answer_validator.validate_answer()
# ---------------------------------------------------------------------------

class TestValidateSessionAnswers:
    def test_reuses_validate_answer_and_preserves_order(self):
        answers = [
            "DUT top module is usb_core",
            {"raw_text": "build includes file top.v",
             "dut_facts_rtl": _dut_facts_rtl("top.v")},
        ]
        result = aif.validate_session_answers(answers)
        assert len(result) == 2
        assert result[0].index == 0
        assert result[0].validation.claim_type == uav.CLAIM_MODULE_EXISTENCE
        assert result[0].validation.target == "usb_core"
        assert result[0].validation.status == uav.UNVERIFIABLE
        assert result[1].index == 1
        assert result[1].validation.status == uav.VALIDATED

    def test_per_answer_evidence_override_is_honored(self):
        # session-level dut_facts_rtl says nothing is included; this ONE
        # answer supplies its own override that really includes the file.
        answers = [
            {"raw_text": "build includes file a.v",
             "dut_facts_rtl": _dut_facts_rtl("a.v")},
        ]
        result = aif.validate_session_answers(answers, dut_facts_rtl=_dut_facts_rtl())
        assert result[0].validation.status == uav.VALIDATED

    def test_singular_dut_top_field_is_tagged_only_for_dut_top_phrasing(self):
        answers = ["DUT top module is usb_core", "module foo_helper exists"]
        result = aif.validate_session_answers(answers)
        assert result[0].singular_field == aif.SINGULAR_FIELD_DUT_TOP
        assert result[1].singular_field is None

    def test_missing_raw_text_in_a_dict_entry_raises(self):
        with pytest.raises(ValueError):
            aif.validate_session_answers([{"asked_at": "t0"}])

    def test_none_answers_raises(self):
        with pytest.raises(ValueError):
            aif.validate_session_answers(None)


# ---------------------------------------------------------------------------
# Signal 1: self-contradiction
# ---------------------------------------------------------------------------

class TestContradictionDetection:
    def test_two_different_dut_top_values_is_a_real_contradiction(self):
        answers = [
            "the DUT top module is usb_core",
            "actually the DUT top is pcie_core",
        ]
        session = aif.validate_session_answers(answers)
        findings = aif.detect_contradictions(session)
        assert len(findings) == 1
        f = findings[0]
        assert f.field_key == aif.SINGULAR_FIELD_DUT_TOP
        assert f.established_target == "usb_core"
        assert f.conflicting_target == "pcie_core"
        assert f.established_index == 0
        assert f.conflicting_index == 1

    def test_case_and_whitespace_only_restatement_is_never_a_contradiction(self):
        answers = [
            "DUT top module is usb_core",
            "DUT top is  USB_CORE",  # same target, different case/whitespace
        ]
        session = aif.validate_session_answers(answers)
        assert aif.detect_contradictions(session) == []

    def test_flip_flop_reports_each_real_disagreement(self):
        answers = [
            "DUT top module is A",
            "DUT top module is B",
            "DUT top module is A",
        ]
        session = aif.validate_session_answers(answers)
        findings = aif.detect_contradictions(session)
        assert len(findings) == 2
        assert (findings[0].established_target, findings[0].conflicting_target) == ("A", "B")
        assert (findings[1].established_target, findings[1].conflicting_target) == ("B", "A")

    def test_different_ordinary_module_existence_claims_never_conflict(self):
        # NEGATIVE CONTROL: a design legitimately has many modules. Two
        # ordinary "module X exists" claims about DIFFERENT modules must
        # never be fabricated into a contradiction merely because both are
        # CLAIM_MODULE_EXISTENCE claims with different targets.
        answers = ["module usb_phy_wrap exists", "module usb_link_ctrl exists"]
        session = aif.validate_session_answers(answers)
        assert aif.detect_contradictions(session) == []

    def test_unrelated_claim_types_never_conflict_with_dut_top(self):
        answers = [
            "DUT top module is usb_core",
            {"raw_text": "build includes file usb_core.v",
             "dut_facts_rtl": _dut_facts_rtl("usb_core.v")},
        ]
        session = aif.validate_session_answers(answers)
        assert aif.detect_contradictions(session) == []


# ---------------------------------------------------------------------------
# Signal 2: degrading-quality (fatigue) trend
# ---------------------------------------------------------------------------

def _bad_answer(i):
    return {"raw_text": f"build includes file missing_{i}.v",
            "dut_facts_rtl": _dut_facts_rtl(f"present_{i}.v")}  # never matches -> CONTRADICTED


def _good_answer(i):
    return {"raw_text": f"build includes file present_{i}.v",
            "dut_facts_rtl": _dut_facts_rtl(f"present_{i}.v")}  # matches -> VALIDATED


class TestFatigueTrendDetection:
    def test_tail_run_of_three_bad_answers_is_detected(self):
        answers = [_good_answer(0), _good_answer(1), _bad_answer(2), _bad_answer(3),
                   _bad_answer(4)]
        session = aif.validate_session_answers(answers)
        # sanity: confirm the "bad" answers really are CONTRADICTED, not something else
        assert all(a.validation.status == uav.CONTRADICTED for a in session[2:])
        findings = aif.detect_fatigue_trend(session)
        kinds = [f.kind for f in findings]
        assert aif.FINDING_TAIL_RUN in kinds
        tail = next(f for f in findings if f.kind == aif.FINDING_TAIL_RUN)
        assert tail.detail["run_length"] == 3
        assert tail.detail["end_index"] == 4

    def test_a_single_bad_answer_surrounded_by_good_ones_is_not_a_tail_run(self):
        answers = [_good_answer(0), _bad_answer(1), _good_answer(2)]
        session = aif.validate_session_answers(answers)
        findings = aif.detect_fatigue_trend(session)
        assert not any(f.kind == aif.FINDING_TAIL_RUN for f in findings)

    def test_increasing_bad_rate_trend_is_detected(self):
        answers = [_good_answer(0), _good_answer(1), _good_answer(2), _good_answer(3),
                   _bad_answer(4), _bad_answer(5), _bad_answer(6), _bad_answer(7)]
        session = aif.validate_session_answers(answers)
        findings = aif.detect_fatigue_trend(session)
        rate = next(f for f in findings if f.kind == aif.FINDING_RATE_TREND)
        assert rate.detail["first_half_bad_rate"] == 0.0
        assert rate.detail["second_half_bad_rate"] == 1.0

    def test_a_flat_bad_rate_never_reports_a_rate_trend(self):
        # every answer bad from the start -- no INCREASE over the session, so no trend.
        answers = [_bad_answer(i) for i in range(6)]
        session = aif.validate_session_answers(answers)
        findings = aif.detect_fatigue_trend(session)
        assert not any(f.kind == aif.FINDING_RATE_TREND for f in findings)
        # the tail-run check DOES still fire, honestly, since the whole tail is bad.
        assert any(f.kind == aif.FINDING_TAIL_RUN for f in findings)

    def test_too_short_a_session_runs_no_fatigue_check_at_all(self):
        answers = [_bad_answer(0), _bad_answer(1)]  # below FATIGUE_MIN_CONSECUTIVE_BAD
        session = aif.validate_session_answers(answers)
        assert aif.detect_fatigue_trend(session) == []


# ---------------------------------------------------------------------------
# analyze_session_fatigue -- the combined, worst-wins verdict
# ---------------------------------------------------------------------------

class TestAnalyzeSessionFatigue:
    def test_clean_session_reports_no_pattern(self):
        answers = [_good_answer(i) for i in range(5)]
        report = aif.analyze_session_fatigue(answers)
        assert report.status == aif.STATUS_NO_PATTERN
        assert report.contradictions == []
        assert report.fatigue_findings == []

    def test_contradiction_outranks_fatigue_trend_even_when_both_present(self):
        answers = [
            "DUT top module is usb_core",
            _bad_answer(0), _bad_answer(1), _bad_answer(2),
            "actually the DUT top is pcie_core",
        ]
        report = aif.analyze_session_fatigue(answers)
        assert report.status == aif.STATUS_CONTRADICTORY
        assert len(report.contradictions) == 1
        # the fatigue findings were real too, but never reported once a
        # contradiction is found -- worst-wins, and the report says so.
        assert report.fatigue_findings == []

    def test_contradiction_is_reported_even_with_only_two_answers(self):
        answers = ["DUT top module is A", "DUT top module is B"]
        report = aif.analyze_session_fatigue(answers)
        assert report.status == aif.STATUS_CONTRADICTORY
        assert report.answer_count == 2

    def test_fatigue_trend_without_contradiction_reports_fatigue_status(self):
        answers = [_good_answer(0), _bad_answer(1), _bad_answer(2), _bad_answer(3)]
        report = aif.analyze_session_fatigue(answers)
        assert report.status == aif.STATUS_FATIGUE
        assert report.contradictions == []
        assert len(report.fatigue_findings) >= 1

    def test_negative_control_insufficient_data_is_never_fabricated_as_clean_or_fatigue(self):
        """The required negative control: a session too short for either
        fatigue check to have honestly run must NEVER be reported as a
        checked-and-clean STATUS_NO_PATTERN (which would claim a check ran
        and found nothing), and must NEVER be silently upgraded to
        STATUS_FATIGUE either -- it is its own distinct, honest status."""
        answers = [_bad_answer(0)]  # a single answer: nothing to trend at all
        report = aif.analyze_session_fatigue(answers)
        assert report.status == aif.STATUS_INSUFFICIENT_DATA
        assert report.status != aif.STATUS_NO_PATTERN
        assert report.status != aif.STATUS_FATIGUE
        assert report.answer_count == 1

    def test_negative_control_unverifiable_answers_are_never_silently_dropped_from_the_bad_rate(self):
        """A session with NO rtl_files/dut_facts_rtl/manifest supplied at all
        makes every module-existence answer honestly UNVERIFIABLE (evidence
        genuinely absent). This must still be counted as 'bad' for the tail-
        run check -- silently treating an unverifiable claim as if it were
        VALIDATED would be exactly the fabricated-clean-answer failure this
        detector exists to prevent."""
        answers = ["DUT top module is a", "module b exists", "module c exists",
                   "module d exists"]
        session = aif.validate_session_answers(answers)  # no evidence supplied anywhere
        assert all(a.validation.status == uav.UNVERIFIABLE for a in session)
        findings = aif.detect_fatigue_trend(session)
        assert any(f.kind == aif.FINDING_TAIL_RUN for f in findings)
        report = aif.analyze_session_fatigue(answers)
        assert report.status == aif.STATUS_FATIGUE

    def test_to_dict_round_trips_every_field(self):
        answers = [_bad_answer(0), _bad_answer(1), _bad_answer(2)]
        report = aif.analyze_session_fatigue(answers)
        d = report.to_dict()
        assert d["status"] == aif.STATUS_FATIGUE
        assert d["answer_count"] == 3
        assert isinstance(d["fatigue_findings"], list) and d["fatigue_findings"]
        assert len(d["answers"]) == 3


# ---------------------------------------------------------------------------
# recommend_checkpoint / offer_save_and_resume_checkpoint
# ---------------------------------------------------------------------------

class TestCheckpointOffer:
    def test_recommend_checkpoint_true_only_on_a_real_finding(self):
        clean = aif.analyze_session_fatigue([_good_answer(i) for i in range(4)])
        assert aif.recommend_checkpoint(clean).recommended is False

        contradictory = aif.analyze_session_fatigue(
            ["DUT top module is A", "DUT top module is B"])
        assert aif.recommend_checkpoint(contradictory).recommended is True

        fatigue = aif.analyze_session_fatigue(
            [_good_answer(0), _bad_answer(1), _bad_answer(2), _bad_answer(3)])
        assert aif.recommend_checkpoint(fatigue).recommended is True

        insufficient = aif.analyze_session_fatigue([_bad_answer(0)])
        assert aif.recommend_checkpoint(insufficient).recommended is False

    def test_offer_refuses_to_freeze_a_clean_session_without_force(self, tmp_path):
        clean = aif.analyze_session_fatigue([_good_answer(i) for i in range(4)])
        with pytest.raises(ValueError, match="not offered"):
            aif.offer_save_and_resume_checkpoint(
                tmp_path, COMPLETE_FACTS, frozen_by="reviewer@example.com",
                report=clean)
        # and, per the Evidence Truth Rule, refusing to offer must never have
        # written anything to disk.
        assert ib.list_intake_freezes(tmp_path) == []

    def test_offer_writes_a_real_freeze_via_the_unmodified_intake_baseline_mechanism(self, tmp_path):
        contradictory = aif.analyze_session_fatigue(
            ["DUT top module is A", "DUT top module is B"])
        result = aif.offer_save_and_resume_checkpoint(
            tmp_path, COMPLETE_FACTS, frozen_by="reviewer@example.com",
            report=contradictory)
        assert "freeze_id" in result["freeze"]
        assert "answer_inconsistency_fatigue_detection" in result["freeze"]["note"]
        assert "contradictory answer" in result["freeze"]["note"]
        # the SAME real freeze mechanism -- reading it back through
        # intake_baseline.py's own unmodified loader proves this is a real,
        # on-disk freeze record, not a fabricated return value.
        on_disk = ib.list_intake_freezes(tmp_path)
        assert len(on_disk) == 1
        assert on_disk[0]["freeze_id"] == result["freeze"]["freeze_id"]

    def test_offer_with_force_writes_a_checkpoint_for_a_clean_session_when_asked(self, tmp_path):
        clean = aif.analyze_session_fatigue([_good_answer(i) for i in range(4)])
        result = aif.offer_save_and_resume_checkpoint(
            tmp_path, COMPLETE_FACTS, frozen_by="reviewer@example.com",
            report=clean, force=True, note="periodic checkpoint")
        assert "periodic checkpoint" in result["freeze"]["note"]
        assert len(ib.list_intake_freezes(tmp_path)) == 1

    def test_offer_still_enforces_intake_baseline_s_own_frozen_by_requirement(self, tmp_path):
        contradictory = aif.analyze_session_fatigue(
            ["DUT top module is A", "DUT top module is B"])
        with pytest.raises(ValueError, match="frozen_by"):
            aif.offer_save_and_resume_checkpoint(
                tmp_path, COMPLETE_FACTS, frozen_by="", report=contradictory)


# ---------------------------------------------------------------------------
# CLI front door
# ---------------------------------------------------------------------------

class TestCli:
    def test_cli_exits_1_on_a_real_contradiction(self, tmp_path, capsys):
        import json
        answers_file = tmp_path / "answers.json"
        answers_file.write_text(json.dumps(
            ["DUT top module is A", "DUT top module is B"]))
        rc = aif.execute_verb(["analyze", "--answers", str(answers_file), "--json"])
        assert rc == 1
        out = capsys.readouterr().out
        assert aif.STATUS_CONTRADICTORY in out

    def test_cli_exits_0_on_a_clean_session(self, tmp_path, capsys):
        import json
        answers_file = tmp_path / "answers.json"
        facts_file = tmp_path / "facts.json"
        answers_file.write_text(json.dumps([
            {"raw_text": "build includes file a.v"},
            {"raw_text": "build includes file b.v"},
            {"raw_text": "build includes file c.v"},
            {"raw_text": "build includes file d.v"},
        ]))
        facts_file.write_text(json.dumps(_dut_facts_rtl("a.v", "b.v", "c.v", "d.v")))
        rc = aif.execute_verb([
            "analyze", "--answers", str(answers_file),
            "--dut-facts-rtl", str(facts_file), "--json"])
        assert rc == 0
        assert aif.STATUS_NO_PATTERN in capsys.readouterr().out

    def test_cli_exits_2_on_insufficient_data(self, tmp_path, capsys):
        import json
        answers_file = tmp_path / "answers.json"
        answers_file.write_text(json.dumps(["build includes file only_one.v"]))
        rc = aif.execute_verb(["analyze", "--answers", str(answers_file)])
        assert rc == 2

    def test_cli_refuses_a_missing_answers_file(self, tmp_path, capsys):
        rc = aif.execute_verb(["analyze", "--answers", str(tmp_path / "nope.json")])
        assert rc == 2
        assert "REFUSED" in capsys.readouterr().out

    def test_cli_refuses_a_non_list_answers_file(self, tmp_path, capsys):
        import json
        answers_file = tmp_path / "answers.json"
        answers_file.write_text(json.dumps({"not": "a list"}))
        rc = aif.execute_verb(["analyze", "--answers", str(answers_file)])
        assert rc == 2
        assert "ANSWERS_MUST_BE_A_JSON_LIST" in capsys.readouterr().out
