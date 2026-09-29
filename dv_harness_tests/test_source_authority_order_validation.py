"""Tests for dv_harness/source_authority_order_validation.py -- a standalone, read-only report
comparing source_authority.py's real AUTHORITY_ORDER against which side a human has actually picked
in practice, over a project's real, answered Tier-3 conflict-escalation questions filed by
source_authority.escalate_conflict(). Every fixture drives the REAL source_authority.py /
question_queue.py machinery (real resolve_conflict()/escalate_conflict()/answer_question() calls) --
never a hand-shaped question record standing in for what they would produce, except where a test's
own point is to prove this module refuses to be fooled by a record that merely LOOKS similar."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import question_queue as qq
from dv_harness import source_authority as sa
from dv_harness import source_authority_order_validation as m


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _dut_rtl_vs_controller_doc_conflict():
    return sa.resolve_conflict([
        sa.SourceClaim("dut_rtl", "base = 0x1272_0000", "rtl/decoder.sv:118"),
        sa.SourceClaim("controller_doc", "base = 0x1272_8000", "Doc/regs.md:88"),
    ])


def _escalate_and_answer(tmp_path, *, answer, basis="human review", decided_by="reviewer",
                          conflict=None, subject="base address"):
    conflict = conflict or _dut_rtl_vs_controller_doc_conflict()
    store = qq.QuestionQueueStore(tmp_path)
    rec = sa.escalate_conflict(tmp_path, conflict, domain="dut", subject=subject)
    store.answer_question(rec["id"], answer=answer, basis=basis, decided_by=decided_by)
    return store, rec


# ---------------------------------------------------------------------------
# is_conflict_escalation_record / parse_conflict_candidates -- shape recognition
# ---------------------------------------------------------------------------

class TestShapeRecognition:
    def test_a_real_escalate_conflict_record_is_recognized(self, tmp_path):
        store = qq.QuestionQueueStore(tmp_path)
        rec = sa.escalate_conflict(tmp_path, _dut_rtl_vs_controller_doc_conflict(),
                                    domain="dut", subject="base address")
        persisted = store.get_question(rec["id"])
        assert m.is_conflict_escalation_record(persisted)
        candidates = m.parse_conflict_candidates(persisted)
        assert candidates is not None
        ids = sorted(c.source_id for c in candidates)
        assert ids == ["controller_doc", "dut_rtl"]

    def test_three_sided_conflict_is_recognized(self, tmp_path):
        conflict = sa.resolve_conflict([
            sa.SourceClaim("simulation_result", "a", "sim.log:1"),
            sa.SourceClaim("ip_user_guide", "b", "ug.pdf:9"),
            sa.SourceClaim("vip_document", "c", "vip.md:3"),
        ])
        rec = sa.escalate_conflict(tmp_path, conflict, domain="env", subject="three-way")
        assert rec is not None
        assert m.is_conflict_escalation_record(rec)
        candidates = m.parse_conflict_candidates(rec)
        assert len(candidates) == 3

    def test_multiple_choice_question_is_not_a_conflict_escalation(self, tmp_path):
        """N-way build_multiple_choice_question() questions share the "Tier-3, 2-3 options" shape
        but use a completely different label/rationale convention -- must never be mistaken for a
        real AUTHORITY_ORDER conflict."""
        store = qq.QuestionQueueStore(tmp_path)
        rec = qq.build_multiple_choice_question(
            store, domain="dut", subject="which bind target",
            candidates=[
                {"label": "target A", "evidence_path": "a.sv:1"},
                {"label": "target B", "evidence_path": "b.sv:2"},
            ],
        )
        assert rec["tier"] == 3
        assert not m.is_conflict_escalation_record(rec)
        assert m.parse_conflict_candidates(rec) is None

    def test_ordinary_non_tier3_question_is_not_a_conflict_escalation(self, tmp_path):
        store = qq.QuestionQueueStore(tmp_path)
        rec = store.add_question(
            domain="env", question="is FSDB required?", context_path="x",
            options=["yes", "no"], recommendation="yes", assumption_if_unanswered="no",
        )
        assert rec["tier"] != 3
        assert not m.is_conflict_escalation_record(rec)

    def test_a_record_with_the_right_shape_but_wrong_tier_is_refused(self):
        """tier must ALSO be 3 -- option-shape alone is not sufficient, per the module's own
        stated reason (a Tier-1/2 record could coincidentally carry similar-looking text)."""
        fake = {
            "tier": 2,
            "status": "ANSWERED",
            "answer": "x", "basis": "y",
            "options": [
                {"label": "Trust the DUT RTL (tier 3): base=1", "rationale": "evidence: a.sv:1"},
                {"label": "Trust the controller doc/programming guide (tier 6): base=2",
                 "rationale": "evidence: b.md:2"},
            ],
        }
        assert not m.is_conflict_escalation_record(fake)
        assert m.build_conflict_case(fake) is None

    def test_options_missing_evidence_prefix_is_refused(self):
        fake = {
            "tier": 3,
            "options": [
                {"label": "Trust the DUT RTL (tier 3): base=1", "rationale": "just trust it"},
                {"label": "Trust the controller doc/programming guide (tier 6): base=2",
                 "rationale": "evidence: b.md:2"},
            ],
        }
        assert m.parse_conflict_candidates(fake) is None

    def test_options_naming_an_unrecognized_source_is_refused(self):
        fake = {
            "tier": 3,
            "options": [
                {"label": "Trust the made-up source (tier 3): base=1", "rationale": "evidence: a.sv:1"},
                {"label": "Trust the controller doc/programming guide (tier 6): base=2",
                 "rationale": "evidence: b.md:2"},
            ],
        }
        assert m.parse_conflict_candidates(fake) is None

    def test_a_label_naming_a_doc_phrase_with_the_wrong_tier_number_is_refused(self):
        """The doc_phrase and the "(tier N):" marker must BOTH belong to the same real
        AUTHORITY_ORDER entry -- a mismatched pair must not resolve to either."""
        fake = {
            "tier": 3,
            "options": [
                {"label": "Trust the DUT RTL (tier 6): base=1", "rationale": "evidence: a.sv:1"},
                {"label": "Trust the controller doc/programming guide (tier 6): base=2",
                 "rationale": "evidence: b.md:2"},
            ],
        }
        assert m.parse_conflict_candidates(fake) is None

    def test_too_few_or_too_many_options_is_refused(self):
        one = {"tier": 3, "options": [
            {"label": "Trust the DUT RTL (tier 3): x", "rationale": "evidence: a.sv:1"}]}
        assert m.parse_conflict_candidates(one) is None

        four = {"tier": 3, "options": [
            {"label": f"Trust the DUT RTL (tier 3): x{i}", "rationale": f"evidence: a{i}.sv:1"}
            for i in range(4)
        ]}
        assert m.parse_conflict_candidates(four) is None


# ---------------------------------------------------------------------------
# determine_authority_prediction
# ---------------------------------------------------------------------------

class TestAuthorityPrediction:
    def test_a_strict_rank_difference_predicts_the_higher_authority_side(self, tmp_path):
        rec = sa.escalate_conflict(tmp_path, _dut_rtl_vs_controller_doc_conflict(),
                                    domain="dut", subject="x")
        candidates = m.parse_conflict_candidates(rec)
        prediction = m.determine_authority_prediction(candidates)
        assert prediction.status == "PREDICTED"
        assert prediction.predicted_source_id == "dut_rtl"

    def test_a_same_tier_pair_predicts_nothing_honestly(self, tmp_path):
        """A tier-4 register_file DUT-vs-Global pair shares one AUTHORITY_ORDER rank in the
        persisted record (the sub-ordering is not carried in the label text this module reads) --
        this must be reported as an honest tie, never a fabricated prediction."""
        conflict = sa.resolve_conflict([
            sa.SourceClaim("register_file", "a", "regmap/dut.json:1", qualifier="dut"),
            sa.SourceClaim("register_file", "b", "regmap/global.json:2", qualifier="global"),
        ])
        rec = sa.escalate_conflict(tmp_path, conflict, domain="dut", subject="regfile tie")
        candidates = m.parse_conflict_candidates(rec)
        prediction = m.determine_authority_prediction(candidates)
        assert prediction.status == "TIE"
        assert prediction.predicted_source_id is None


# ---------------------------------------------------------------------------
# determine_human_pick -- the honest, evidence-only matching
# ---------------------------------------------------------------------------

class TestHumanPick:
    def _candidates(self, tmp_path):
        rec = sa.escalate_conflict(tmp_path, _dut_rtl_vs_controller_doc_conflict(),
                                    domain="dut", subject="x")
        return m.parse_conflict_candidates(rec)

    def test_picked_by_literal_evidence_path_citation(self, tmp_path):
        candidates = self._candidates(tmp_path)
        record = {"answer": "confirmed at rtl/decoder.sv:118, the doc has drifted", "basis": None}
        pick = m.determine_human_pick(record, candidates)
        assert pick.status == "PICKED_BY_EVIDENCE_PATH_CITATION"
        assert pick.picked_source_id == "dut_rtl"
        assert pick.matched_evidence == ["rtl/decoder.sv:118"]

    def test_two_cited_evidence_paths_is_ambiguous_never_guessed(self, tmp_path):
        candidates = self._candidates(tmp_path)
        record = {"answer": "both rtl/decoder.sv:118 and Doc/regs.md:88 look plausible", "basis": None}
        pick = m.determine_human_pick(record, candidates)
        assert pick.status == "AMBIGUOUS"
        assert pick.picked_source_id is None
        assert set(pick.matched_evidence) == {"rtl/decoder.sv:118", "Doc/regs.md:88"}

    def test_picked_by_alias_mention_when_no_evidence_path_is_cited(self, tmp_path):
        candidates = self._candidates(tmp_path)
        record = {"answer": "the RTL is right, doc had a typo", "basis": None}
        pick = m.determine_human_pick(record, candidates)
        # "RTL" is a real registered alias of dut_rtl; "doc" alone is not a registered alias of
        # controller_doc (its aliases are all compound "*_doc" tokens), so this resolves cleanly.
        assert pick.status == "PICKED_BY_DOC_PHRASE_OR_ALIAS_MENTION"
        assert pick.picked_source_id == "dut_rtl"

    def test_no_recognizable_mention_is_honestly_unresolved(self, tmp_path):
        candidates = self._candidates(tmp_path)
        record = {"answer": "looks fine, go with whatever", "basis": None}
        pick = m.determine_human_pick(record, candidates)
        assert pick.status == "UNRESOLVED_NO_MATCH"
        assert pick.picked_source_id is None

    def test_empty_answer_and_basis_is_honestly_unresolved(self, tmp_path):
        candidates = self._candidates(tmp_path)
        pick = m.determine_human_pick({"answer": None, "basis": ""}, candidates)
        assert pick.status == "UNRESOLVED_NO_MATCH"

    def test_alias_matching_respects_word_boundaries(self, tmp_path):
        """"RTL" must not match inside an unrelated longer word."""
        candidates = self._candidates(tmp_path)
        record = {"answer": "the PORTLAND office signed off on this", "basis": None}
        pick = m.determine_human_pick(record, candidates)
        assert pick.status == "UNRESOLVED_NO_MATCH"

    def test_basis_text_is_also_searched(self, tmp_path):
        candidates = self._candidates(tmp_path)
        record = {"answer": "confirmed", "basis": "see rtl/decoder.sv:118 for the real value"}
        pick = m.determine_human_pick(record, candidates)
        assert pick.status == "PICKED_BY_EVIDENCE_PATH_CITATION"
        assert pick.picked_source_id == "dut_rtl"


# ---------------------------------------------------------------------------
# build_conflict_case -- one record -> one outcome
# ---------------------------------------------------------------------------

class TestBuildConflictCase:
    def test_match_outcome(self, tmp_path):
        store, rec = _escalate_and_answer(
            tmp_path, answer="confirmed at rtl/decoder.sv:118, doc is stale")
        persisted = store.get_question(rec["id"])
        case = m.build_conflict_case(persisted)
        assert case.outcome == "MATCH"
        assert case.authority_prediction.predicted_source_id == "dut_rtl"
        assert case.human_pick.picked_source_id == "dut_rtl"
        assert case.decided_by == "reviewer"

    def test_mismatch_outcome(self, tmp_path):
        store, rec = _escalate_and_answer(
            tmp_path, answer="per Doc/regs.md:88 the doc is right, RTL had a known bug")
        persisted = store.get_question(rec["id"])
        case = m.build_conflict_case(persisted)
        assert case.outcome == "MISMATCH"
        assert case.authority_prediction.predicted_source_id == "dut_rtl"
        assert case.human_pick.picked_source_id == "controller_doc"

    def test_pending_unanswered_outcome(self, tmp_path):
        rec = sa.escalate_conflict(tmp_path, _dut_rtl_vs_controller_doc_conflict(),
                                    domain="dut", subject="x")
        assert rec["status"] == "OPEN"
        case = m.build_conflict_case(rec)
        assert case.outcome == "PENDING_UNANSWERED"
        assert case.human_pick is None

    def test_tie_outcome(self, tmp_path):
        conflict = sa.resolve_conflict([
            sa.SourceClaim("register_file", "a", "regmap/dut.json:1", qualifier="dut"),
            sa.SourceClaim("register_file", "b", "regmap/global.json:2", qualifier="global"),
        ])
        store, rec = _escalate_and_answer(
            tmp_path, answer="use regmap/dut.json:1", conflict=conflict, subject="regfile tie")
        persisted = store.get_question(rec["id"])
        case = m.build_conflict_case(persisted)
        assert case.outcome == "TIE_NO_AUTHORITY_PREDICTION"

    def test_human_pick_ambiguous_outcome(self, tmp_path):
        store, rec = _escalate_and_answer(
            tmp_path, answer="both rtl/decoder.sv:118 and Doc/regs.md:88 mentioned")
        persisted = store.get_question(rec["id"])
        case = m.build_conflict_case(persisted)
        assert case.outcome == "HUMAN_PICK_AMBIGUOUS"

    def test_human_pick_unresolved_outcome(self, tmp_path):
        store, rec = _escalate_and_answer(tmp_path, answer="go with whatever")
        persisted = store.get_question(rec["id"])
        case = m.build_conflict_case(persisted)
        assert case.outcome == "HUMAN_PICK_UNRESOLVED"

    def test_non_conflict_record_returns_none(self, tmp_path):
        store = qq.QuestionQueueStore(tmp_path)
        rec = store.add_question(domain="env", question="q", context_path="x",
                                  options=["a", "b"], recommendation="a",
                                  assumption_if_unanswered="a")
        assert m.build_conflict_case(rec) is None


# ---------------------------------------------------------------------------
# build_report -- the full, end-to-end report
# ---------------------------------------------------------------------------

class TestBuildReport:
    def test_no_conflict_escalations_at_all_is_honestly_reported(self, tmp_path):
        qq.QuestionQueueStore(tmp_path)  # constructing a store creates no files
        report = m.build_report(tmp_path)
        assert report.status == "NO_EVALUABLE_CASES"
        assert report.total_conflict_escalations_found == 0
        assert report.match_rate_percent is None

    def test_order_matches_practice_when_every_evaluable_case_agrees(self, tmp_path):
        store = qq.QuestionQueueStore(tmp_path)
        rec = sa.escalate_conflict(tmp_path, _dut_rtl_vs_controller_doc_conflict(),
                                    domain="dut", subject="x")
        store.answer_question(rec["id"], answer="confirmed at rtl/decoder.sv:118",
                               basis="", decided_by="r")
        report = m.build_report(tmp_path)
        assert report.status == "ORDER_MATCHES_PRACTICE"
        assert report.matches == 1
        assert report.mismatches == 0
        assert report.match_rate_percent == 100.0

    def test_order_diverges_from_practice_on_a_real_override(self, tmp_path):
        store, rec = _escalate_and_answer(
            tmp_path, answer="per Doc/regs.md:88 the doc is right, RTL had a known bug")
        report = m.build_report(tmp_path)
        assert report.status == "ORDER_DIVERGES_FROM_PRACTICE"
        assert report.mismatches == 1
        assert report.override_pairs == [
            {"authority_predicted": "dut_rtl", "human_picked": "controller_doc", "count": 1}
        ]

    def test_full_mixed_scenario_counts_every_bucket_correctly(self, tmp_path):
        store = qq.QuestionQueueStore(tmp_path)

        # 1: MATCH
        rec1 = sa.escalate_conflict(tmp_path, _dut_rtl_vs_controller_doc_conflict(),
                                     domain="dut", subject="case1")
        store.answer_question(rec1["id"], answer="confirmed at rtl/decoder.sv:118",
                               basis="", decided_by="r1")

        # 2: MISMATCH (override, twice, same pair)
        conflict2 = sa.resolve_conflict([
            sa.SourceClaim("dut_rtl", "a", "rtl/y.sv:9"),
            sa.SourceClaim("ip_user_guide", "b", "ug.pdf:2"),
        ])
        rec2 = sa.escalate_conflict(tmp_path, conflict2, domain="dut", subject="case2")
        store.answer_question(rec2["id"], answer="per ug.pdf:2 the user guide is authoritative here",
                               basis="", decided_by="r2")

        conflict2b = sa.resolve_conflict([
            sa.SourceClaim("dut_rtl", "a", "rtl/z.sv:3"),
            sa.SourceClaim("ip_user_guide", "b", "ug2.pdf:4"),
        ])
        rec2b = sa.escalate_conflict(tmp_path, conflict2b, domain="dut", subject="case2b")
        store.answer_question(rec2b["id"], answer="per ug2.pdf:4 go with the user guide again",
                               basis="", decided_by="r2b")

        # 3: TIE
        conflict3 = sa.resolve_conflict([
            sa.SourceClaim("register_file", "a", "regmap/dut.json:1", qualifier="dut"),
            sa.SourceClaim("register_file", "b", "regmap/global.json:2", qualifier="global"),
        ])
        rec3 = sa.escalate_conflict(tmp_path, conflict3, domain="dut", subject="case3")
        store.answer_question(rec3["id"], answer="use regmap/dut.json:1", basis="", decided_by="r3")

        # 4: AMBIGUOUS
        conflict4 = sa.resolve_conflict([
            sa.SourceClaim("vip_example", "a", "ex.sv:1"),
            sa.SourceClaim("vip_document", "b", "vdoc.md:2"),
        ])
        rec4 = sa.escalate_conflict(tmp_path, conflict4, domain="vip", subject="case4")
        store.answer_question(rec4["id"], answer="both ex.sv:1 and vdoc.md:2 look relevant",
                               basis="", decided_by="r4")

        # 5: UNRESOLVED
        conflict5 = sa.resolve_conflict([
            sa.SourceClaim("simulation_result", "a", "sim.log:1"),
            sa.SourceClaim("existing_testbench_bind", "b", "tb_bind.sv:2"),
        ])
        rec5 = sa.escalate_conflict(tmp_path, conflict5, domain="env", subject="case5")
        store.answer_question(rec5["id"], answer="fine either way", basis="", decided_by="r5")

        # 6: still open
        conflict6 = sa.resolve_conflict([
            sa.SourceClaim("reference_command_txt", "a", "cmd.txt:1"),
            sa.SourceClaim("vip_document", "b", "vdoc2.md:3"),
        ])
        sa.escalate_conflict(tmp_path, conflict6, domain="env", subject="case6")

        report = m.build_report(tmp_path)
        # 7 real escalate_conflict() calls total (case2 alone files two separate escalations,
        # rec2 and rec2b, to get the same override pair twice): 6 answered + 1 still open.
        assert report.total_conflict_escalations_found == 7
        assert report.answered_conflict_escalations == 6
        assert report.open_pending_conflict_escalations == 1
        assert report.matches == 1
        assert report.mismatches == 2
        assert report.ties_no_authority_prediction == 1
        assert report.human_pick_ambiguous == 1
        assert report.human_pick_unresolved == 1
        assert report.evaluable_cases == 3
        assert report.match_rate_percent == pytest.approx(33.33, abs=0.01)
        assert report.status == "ORDER_DIVERGES_FROM_PRACTICE"

        # per-level stats: dut_rtl was the predicted winner in all three of case1/case2/case2b --
        # confirmed once (case1) and overridden twice (case2, case2b)
        dut_rtl_stats = next(s for s in report.per_level_stats if s.id == "dut_rtl")
        assert dut_rtl_stats.times_predicted_winner == 3
        assert dut_rtl_stats.times_predicted_winner_confirmed == 1
        assert dut_rtl_stats.times_predicted_winner_overridden == 2

        ip_ug_stats = next(s for s in report.per_level_stats if s.id == "ip_user_guide")
        assert ip_ug_stats.times_chosen_by_human_over_higher_authority == 2

        # override pairs: one distinct pair, counted twice
        assert report.override_pairs == [
            {"authority_predicted": "dut_rtl", "human_picked": "ip_user_guide", "count": 2}
        ]

        # every 9 levels always appear, even ones that never showed up in any conflict
        assert len(report.per_level_stats) == 9
        assert {s.id for s in report.per_level_stats} == {s.id for s in sa.AUTHORITY_ORDER}

    def test_accepts_a_prebuilt_store_or_a_bare_path(self, tmp_path):
        store, rec = _escalate_and_answer(tmp_path, answer="confirmed at rtl/decoder.sv:118")
        via_store = m.build_report(store)
        via_path = m.build_report(tmp_path)
        assert via_store.status == via_path.status
        assert via_store.matches == via_path.matches

    def test_a_minimal_test_double_with_no_kwargs_support_still_works(self, tmp_path):
        store, rec = _escalate_and_answer(tmp_path, answer="confirmed at rtl/decoder.sv:118")
        real_records = store.list_questions()

        class _Minimal:
            def list_questions(self):
                return real_records

        report = m.build_report(_Minimal())
        assert report.matches == 1

    def test_build_report_never_writes_anything_to_disk(self, tmp_path):
        """Reading is never a mutating act -- building the report over an already-populated
        project must leave every file byte-for-byte, mtime-for-mtime unchanged."""
        store, rec = _escalate_and_answer(tmp_path, answer="confirmed at rtl/decoder.sv:118")
        dv_harness_dir = tmp_path / ".dv-harness"
        before = {
            p: (p.read_bytes(), p.stat().st_mtime_ns)
            for p in dv_harness_dir.rglob("*") if p.is_file()
        }
        assert before  # sanity: the fixture really produced files
        m.build_report(tmp_path)
        after = {
            p: (p.read_bytes(), p.stat().st_mtime_ns)
            for p in dv_harness_dir.rglob("*") if p.is_file()
        }
        assert before == after

    def test_authority_order_object_is_never_mutated(self, tmp_path):
        """This item's own scope: report only, never modify AUTHORITY_ORDER itself."""
        before = tuple(sa.AUTHORITY_ORDER)
        store, rec = _escalate_and_answer(
            tmp_path, answer="per Doc/regs.md:88 the doc is right, RTL had a known bug")
        m.build_report(tmp_path)
        assert sa.AUTHORITY_ORDER is before or tuple(sa.AUTHORITY_ORDER) == before
        assert tuple(sa.AUTHORITY_ORDER) == before


# ---------------------------------------------------------------------------
# format_report / vocabulary guard
# ---------------------------------------------------------------------------

class TestFormatReportAndVocabulary:
    def test_format_report_renders_headline_numbers(self, tmp_path):
        store, rec = _escalate_and_answer(tmp_path, answer="confirmed at rtl/decoder.sv:118")
        report = m.build_report(tmp_path)
        text = m.format_report(report)
        assert "ORDER_MATCHES_PRACTICE" in text
        assert "matches: 1" in text
        assert "DUT RTL" in text  # per-level table renders the real doc_phrase

    def test_format_report_on_no_evaluable_cases_shows_the_no_overrides_note(self, tmp_path):
        qq.QuestionQueueStore(tmp_path)
        report = m.build_report(tmp_path)
        text = m.format_report(report)
        assert "no real overrides found" in text

    def test_vocabulary_guard_has_real_detection_power(self, monkeypatch):
        """Mutation-style proof: force a real collision with dv_harness.models.Status and confirm
        the guard actually raises, rather than merely never having tripped by accident."""
        monkeypatch.setattr(m, "REPORT_STATUSES", ("PASS",))
        with pytest.raises(m.SourceAuthorityOrderValidationError):
            m.assert_no_verification_verdict_vocabulary()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestCli:
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "dv_harness.source_authority_order_validation", *args],
            capture_output=True, text=True,
        )

    def test_cli_no_evaluable_cases_exit_code(self, tmp_path):
        qq.QuestionQueueStore(tmp_path)
        proc = self._run("--root", str(tmp_path), "--json")
        assert proc.returncode == 2, proc.stderr
        out = json.loads(proc.stdout)
        assert out["status"] == "NO_EVALUABLE_CASES"

    def test_cli_matches_exit_code(self, tmp_path):
        store, rec = _escalate_and_answer(tmp_path, answer="confirmed at rtl/decoder.sv:118")
        proc = self._run("--root", str(tmp_path), "--json")
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        assert out["status"] == "ORDER_MATCHES_PRACTICE"

    def test_cli_diverges_exit_code(self, tmp_path):
        store, rec = _escalate_and_answer(
            tmp_path, answer="per Doc/regs.md:88 the doc is right, RTL had a known bug")
        proc = self._run("--root", str(tmp_path), "--json")
        assert proc.returncode == 1, proc.stderr
        out = json.loads(proc.stdout)
        assert out["status"] == "ORDER_DIVERGES_FROM_PRACTICE"

    def test_cli_default_text_output(self, tmp_path):
        store, rec = _escalate_and_answer(tmp_path, answer="confirmed at rtl/decoder.sv:118")
        proc = self._run("--root", str(tmp_path))
        assert proc.returncode == 0, proc.stderr
        assert "Source Authority Order Validation" in proc.stdout
