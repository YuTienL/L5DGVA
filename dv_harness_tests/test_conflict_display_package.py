"""Tests for dv_harness.conflict_display_package -- the structured 9-field
conflict DISPLAY package built over real source_authority.py conflict
records and real user_answer_validator.py CONTRADICTED validations.

Nothing here is a mock: every source-conflict test drives a real
`question_queue.QuestionQueueStore` on tmp_path through the real
`source_authority.escalate_conflict()`/`answer_question()` path, and every
answer-validation test drives a real `user_answer_validator.validate_answer()`
call against a real, temporary RTL file parsed by the real
verible-verilog-syntax front end (skipped, never faked, on a machine without
it on PATH) or real recorded build facts.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import conflict_display_package as cdp
from dv_harness import question_queue
from dv_harness import source_authority as sa
from dv_harness import user_answer_validator as uav
from dv_harness import verible_parser

REPO_ROOT = Path(__file__).resolve().parents[1]


def _has_verible() -> bool:
    try:
        subprocess.run([verible_parser.DEFAULT_VERIBLE_BIN, "--help"],
                        capture_output=True, timeout=5)
        return True
    except Exception:
        return False


HAS_VERIBLE = _has_verible()


def _resolved_conflict():
    return sa.resolve_conflict([
        sa.SourceClaim("dut_rtl", "base = 0x1272_0000", "rtl/decoder.sv:118"),
        sa.SourceClaim("controller_doc", "base = 0x1272_8000", "Doc/regs.md:88"),
    ])


def _undecidable_conflict():
    return sa.resolve_conflict([
        sa.SourceClaim("dut_rtl", "base = 0x1272_0000", "rtl/decoder.sv:118"),
        sa.SourceClaim("dut_rtl", "base = 0x1272_9000", "rtl/decoder2.sv:9"),
    ])


def _three_sided_conflict():
    return sa.resolve_conflict([
        sa.SourceClaim("dut_rtl", "a", "rtl.sv:1"),
        sa.SourceClaim("controller_doc", "b", "doc.md:2"),
        sa.SourceClaim("ip_user_guide", "c", "ug.pdf:3"),
    ])


# ===========================================================================
# Vocabulary hygiene
# ===========================================================================

def test_nine_fields_exactly():
    assert len(cdp.CONFLICT_DISPLAY_FIELDS) == 9
    assert cdp.CONFLICT_DISPLAY_FIELDS == (
        "conflict_type", "affected_fact", "evidence_a", "evidence_b", "evidence_c",
        "recommended_authority", "downstream_impact", "next_best_action", "user_decision",
    )


def test_conflict_type_never_collides_with_source_authority_vocabulary():
    assert cdp.CONFLICT_TYPE_USER_CLAIM_VS_EVIDENCE not in sa.CONFLICT_TYPES
    # the assert function itself should not raise on the real, unmodified state
    cdp.assert_no_conflict_type_vocabulary_collision()


def test_vocabulary_collision_guard_has_real_detection_power(monkeypatch):
    monkeypatch.setattr(sa, "CONFLICT_TYPES", sa.CONFLICT_TYPES + (cdp.CONFLICT_TYPE_USER_CLAIM_VS_EVIDENCE,))
    with pytest.raises(AssertionError):
        cdp.assert_no_conflict_type_vocabulary_collision()


# ===========================================================================
# Builder 1: source_authority conflicts
# ===========================================================================

def test_resolved_conflict_builds_all_nine_fields_with_real_evidence(tmp_path):
    conflict = _resolved_conflict()
    package = cdp.build_conflict_display_package_from_source_conflict(
        conflict, subject="tca register base address")

    for k in cdp.CONFLICT_DISPLAY_FIELDS:
        assert k in package

    assert package["conflict_type"] == sa.classify_conflict(conflict)
    assert package["affected_fact"] == "tca register base address"

    # highest authority (dut_rtl, tier 3) first, per resolve_conflict()'s own
    # ranked claims order
    assert package["evidence_a"]["source"] == "dut_rtl"
    assert package["evidence_a"]["evidence_path"] == "rtl/decoder.sv:118"
    assert "tier 3" in package["evidence_a"]["source_version"]

    assert package["evidence_b"]["source"] == "controller_doc"
    assert package["evidence_b"]["evidence_path"] == "Doc/regs.md:88"
    assert "tier 6" in package["evidence_b"]["source_version"]

    assert package["evidence_c"] is None

    assert "DUT RTL" in package["recommended_authority"]
    assert "outranks" in package["recommended_authority"] or "tier" in package["recommended_authority"]
    assert package["downstream_impact"]  # a real, non-empty string
    assert package["next_best_action"]
    assert package["user_decision"] == cdp.USER_DECISION_NOT_ESCALATED


def test_undecidable_conflict_recommended_authority_names_the_real_tie_rule():
    conflict = _undecidable_conflict()
    package = cdp.build_conflict_display_package_from_source_conflict(
        conflict, subject="tca register base address")
    assert package["conflict_type"] == sa.classify_conflict(conflict)
    assert "cannot break" in package["recommended_authority"]
    assert package["evidence_a"]["source"] == "dut_rtl"
    assert package["evidence_b"]["source"] == "dut_rtl"
    assert package["evidence_c"] is None


def test_three_sided_conflict_fills_all_three_evidence_slots():
    conflict = _three_sided_conflict()
    package = cdp.build_conflict_display_package_from_source_conflict(
        conflict, subject="widget config")
    assert package["evidence_a"]["source"] == "dut_rtl"
    assert package["evidence_b"]["source"] == "controller_doc"
    assert package["evidence_c"]["source"] == "ip_user_guide"


def test_three_distinct_source_types_report_an_honest_unclassified_type_never_a_guess():
    """source_authority.classify_conflict() is genuinely pairwise-only (a real,
    disclosed scope boundary -- more than 2 DISTINCT source TYPES is refused
    with CONFLICT_TYPE_NEEDS_ONE_OR_TWO_SOURCE_TYPES). This module must never
    work around that by guessing a pairwise label; it reports the real
    refusal reason and still builds every other field."""
    conflict = _three_sided_conflict()
    with pytest.raises(sa.SourceAuthorityError):
        sa.classify_conflict(conflict)  # confirms the real module's own refusal
    package = cdp.build_conflict_display_package_from_source_conflict(
        conflict, subject="widget config")
    assert package["conflict_type"].startswith("UNCLASSIFIED_MULTI_SOURCE_TYPE_CONFLICT")
    assert "CONFLICT_TYPE_NEEDS_ONE_OR_TWO_SOURCE_TYPES" in package["conflict_type"]
    assert package["recommended_authority"]  # every other field still builds


def test_no_conflict_verdict_is_refused_not_rendered_as_agreement():
    agree = sa.resolve_conflict([
        sa.SourceClaim("dut_rtl", "base = 0x1272_0000", "rtl/decoder.sv:118"),
        sa.SourceClaim("controller_doc", "base = 0x1272_0000", "Doc/regs.md:88"),
    ])
    with pytest.raises(cdp.ConflictDisplayError) as exc:
        cdp.build_conflict_display_package_from_source_conflict(agree, subject="base")
    assert exc.value.reason == "NO_CONFLICT_HAS_NOTHING_TO_DISPLAY"


def test_missing_subject_is_refused_never_guessed():
    conflict = _resolved_conflict()
    with pytest.raises(cdp.ConflictDisplayError) as exc:
        cdp.build_conflict_display_package_from_source_conflict(conflict, subject="")
    assert exc.value.reason == "SUBJECT_REQUIRED"
    with pytest.raises(cdp.ConflictDisplayError):
        cdp.build_conflict_display_package_from_source_conflict(conflict, subject=None)


def test_single_claim_conflict_is_refused():
    single = {"verdict": sa.VERDICT_RESOLVED, "claims": [
        sa.SourceClaim("dut_rtl", "x", "a.sv:1").to_dict()], "rule": "n/a"}
    with pytest.raises(cdp.ConflictDisplayError) as exc:
        cdp.build_conflict_display_package_from_source_conflict(single, subject="x")
    assert exc.value.reason == "CONFLICT_NEEDS_AT_LEAST_TWO_CLAIMS"


def test_malformed_conflict_input_is_refused():
    with pytest.raises(cdp.ConflictDisplayError) as exc:
        cdp.build_conflict_display_package_from_source_conflict("not a dict", subject="x")
    assert exc.value.reason == "CONFLICT_MUST_BE_A_DICT"


# ===========================================================================
# User Decision -- reading REAL question_queue records, never fabricating a
# human decision from a machine default.
# ===========================================================================

def test_open_escalation_reports_pending_awaiting_human(tmp_path):
    rec = sa.escalate_conflict(tmp_path, _resolved_conflict(), domain="dut",
                                subject="tca register base address")
    store = question_queue.QuestionQueueStore(tmp_path)
    persisted = store.get_question(rec["id"])
    package = cdp.build_conflict_display_package_from_source_conflict(
        _resolved_conflict(), subject="tca register base address",
        question_record=persisted, store=store)
    assert "PENDING" in package["user_decision"]
    assert rec["id"] in package["user_decision"]


def test_real_human_answer_reads_as_decided_by_human_never_as_auto_assumption(tmp_path):
    rec = sa.escalate_conflict(tmp_path, _resolved_conflict(), domain="dut",
                                subject="tca register base address")
    store = question_queue.QuestionQueueStore(tmp_path)
    store.answer_question(rec["id"], answer="RTL is authoritative here",
                           basis="re-read the decoder", decided_by="jane.doe")
    persisted = store.get_question(rec["id"])
    package = cdp.build_conflict_display_package_from_source_conflict(
        _resolved_conflict(), subject="tca register base address",
        question_record=persisted, store=store)
    assert "DECIDED_BY_HUMAN" in package["user_decision"]
    assert "jane.doe" in package["user_decision"]
    assert "RTL is authoritative here" in package["user_decision"]
    assert "TIER2_AUTO_ASSUMPTION" not in package["user_decision"]


def test_tier2_auto_assumption_is_never_presented_as_a_human_decision(tmp_path):
    # Build a Tier-2-classifiable escalation directly through add_question()
    # with a non-cannot-assume context, so it self-resolves as an assumption
    # rather than a blocking Tier-3.
    store = question_queue.QuestionQueueStore(tmp_path)
    record = store.add_question(
        domain="env", question="Is FSDB dumping needed for this run?",
        context_path="run/config", options=["yes", "no"], recommendation="no",
        assumption_if_unanswered="no", context={},
    )
    assert record["tier"] == question_queue.TIER2_SAFE_ASSUME
    package = cdp.build_conflict_display_package_from_source_conflict(
        _resolved_conflict(), subject="tca register base address",
        question_record=record, store=store)
    assert "TIER2_AUTO_ASSUMPTION" in package["user_decision"]
    assert "not a human decision" in package["user_decision"]
    assert "DECIDED_BY_HUMAN" not in package["user_decision"]


def test_no_question_record_at_all_is_honestly_not_escalated():
    package = cdp.build_conflict_display_package_from_source_conflict(
        _resolved_conflict(), subject="base address")
    assert package["user_decision"] == cdp.USER_DECISION_NOT_ESCALATED


# ===========================================================================
# Builder 2: user_answer_validator CONTRADICTED validations
# ===========================================================================

@pytest.mark.skipif(not HAS_VERIBLE, reason="verible-verilog-syntax not on PATH")
def test_contradicted_module_existence_claim_builds_nine_fields(tmp_path):
    rtl = tmp_path / "top.v"
    rtl.write_text("module usb_core(input clk); endmodule\n", encoding="utf-8")
    validation = uav.validate_answer("DUT top module is usb_core_v2", rtl_files=[rtl])
    assert validation.status == uav.CONTRADICTED

    package = cdp.build_conflict_display_package_from_answer_validation(
        validation, user_decision="pending correction")

    for k in cdp.CONFLICT_DISPLAY_FIELDS:
        assert k in package
    assert package["conflict_type"] == cdp.CONFLICT_TYPE_USER_CLAIM_VS_EVIDENCE
    assert "usb_core_v2" in package["affected_fact"]
    assert package["evidence_a"]["source"] == "USER_CLAIM (unverified)"
    assert package["evidence_a"]["claim"] == "DUT top module is usb_core_v2"
    assert package["evidence_b"]["source"] == "REAL_EVIDENCE"
    assert "verible_parser" in package["evidence_b"]["source_version"]
    assert package["evidence_c"] is None
    assert "outranks an unverified user claim" in package["recommended_authority"]
    assert package["user_decision"] == "pending correction"
    assert package["next_best_action"]


def test_contradicted_build_inclusion_claim_from_to_dict_shape():
    dut_facts_rtl = {"status": "PARSED", "files": [{"file_path": "rtl/other_file.v"}]}
    validation = uav.validate_answer(
        "build includes file usb3_link_ctrl.v", dut_facts_rtl=dut_facts_rtl)
    assert validation.status == uav.CONTRADICTED

    package = cdp.build_conflict_display_package_from_answer_validation(validation.to_dict())
    assert package["conflict_type"] == cdp.CONFLICT_TYPE_USER_CLAIM_VS_EVIDENCE
    assert "usb3_link_ctrl.v" in package["affected_fact"]
    assert "env_manifest" in package["evidence_b"]["source_version"]
    assert package["user_decision"] == cdp.USER_DECISION_NOT_ESCALATED


def test_validated_answer_has_nothing_to_display_and_is_refused():
    dut_facts_rtl = {"status": "PARSED", "files": [{"file_path": "rtl/usb3_link_ctrl.v"}]}
    validation = uav.validate_answer(
        "build includes file rtl/usb3_link_ctrl.v", dut_facts_rtl=dut_facts_rtl)
    assert validation.status == uav.VALIDATED
    with pytest.raises(cdp.ConflictDisplayError) as exc:
        cdp.build_conflict_display_package_from_answer_validation(validation)
    assert exc.value.reason == "ONLY_CONTRADICTED_VALIDATIONS_HAVE_A_CONFLICT_TO_DISPLAY"


def test_unverifiable_answer_is_refused_not_silently_shown_as_a_conflict():
    validation = uav.validate_answer("this text matches no known claim pattern at all")
    assert validation.status == uav.UNVERIFIABLE
    with pytest.raises(cdp.ConflictDisplayError):
        cdp.build_conflict_display_package_from_answer_validation(validation)


def test_malformed_validation_input_is_refused():
    with pytest.raises(cdp.ConflictDisplayError) as exc:
        cdp.build_conflict_display_package_from_answer_validation(42)
    assert exc.value.reason == "VALIDATION_MUST_BE_A_DICT_OR_ANSWERVALIDATION"


# ===========================================================================
# Downstream impact -- best-effort change_cascade.py reuse, honest fallback
# ===========================================================================

def test_downstream_impact_reuses_change_cascade_for_a_known_field():
    conflict = sa.resolve_conflict([
        sa.SourceClaim("dut_rtl", "a", "rtl.sv:1", detail={}),
        sa.SourceClaim("controller_doc", "b", "doc.md:2"),
    ])
    package = cdp.build_conflict_display_package_from_source_conflict(
        conflict, subject="rtl_source")
    assert "change_cascade.py" in package["downstream_impact"]
    assert "dv_harness.env_manifest" in package["downstream_impact"] or "env.manifest" in package["downstream_impact"]


def test_downstream_impact_is_honest_not_assessed_for_an_unknown_field():
    conflict = _resolved_conflict()
    package = cdp.build_conflict_display_package_from_source_conflict(
        conflict, subject="some_totally_unrelated_free_text_fact")
    assert "NOT_ASSESSED" in package["downstream_impact"]


def test_downstream_impact_caller_override_always_wins():
    conflict = _resolved_conflict()
    package = cdp.build_conflict_display_package_from_source_conflict(
        conflict, subject="rtl_source", downstream_impact="a caller's own real assessment")
    assert package["downstream_impact"] == "a caller's own real assessment"


# ===========================================================================
# Rendering
# ===========================================================================

def test_render_markdown_shows_evidence_side_by_side():
    conflict = _three_sided_conflict()
    package = cdp.build_conflict_display_package_from_source_conflict(
        conflict, subject="widget config")
    md = cdp.render_conflict_display_markdown(package)
    assert "widget config" in md
    assert "Evidence A" in md
    assert "Evidence B" in md
    assert "Evidence C" in md
    assert "rtl.sv:1" in md
    assert "doc.md:2" in md
    assert "ug.pdf:3" in md
    # a table row per rendered value, adjacent columns for direct comparison
    lines = md.splitlines()
    evidence_path_line = [l for l in lines if "Evidence Path" in l][0]
    assert "rtl.sv:1" in evidence_path_line
    assert "doc.md:2" in evidence_path_line
    assert "ug.pdf:3" in evidence_path_line


def test_render_markdown_handles_a_two_sided_conflict_with_no_third_column():
    conflict = _resolved_conflict()
    package = cdp.build_conflict_display_package_from_source_conflict(
        conflict, subject="base address")
    md = cdp.render_conflict_display_markdown(package)
    assert "Evidence A" in md
    assert "Evidence B" in md
    assert "Evidence C" not in md


def test_render_markdown_refuses_an_incomplete_package():
    with pytest.raises(cdp.ConflictDisplayError) as exc:
        cdp.render_conflict_display_markdown({"conflict_type": "X"})
    assert exc.value.reason == "PACKAGE_MISSING_FIELD"


def test_render_markdown_title_override():
    conflict = _resolved_conflict()
    package = cdp.build_conflict_display_package_from_source_conflict(
        conflict, subject="base address")
    md = cdp.render_conflict_display_markdown(package, title="Custom Title")
    assert md.startswith("### Custom Title")


# ===========================================================================
# CLI
# ===========================================================================

def test_cli_from_source_conflict_subprocess(tmp_path):
    conflict = _resolved_conflict()
    conflict_path = tmp_path / "conflict.json"
    conflict_path.write_text(json.dumps(conflict), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.conflict_display_package",
         "from-source-conflict", "--conflict", str(conflict_path),
         "--subject", "base address", "--json"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    for k in cdp.CONFLICT_DISPLAY_FIELDS:
        assert k in payload


def test_cli_from_answer_validation_subprocess(tmp_path):
    dut_facts_rtl = {"status": "PARSED", "files": [{"file_path": "rtl/other_file.v"}]}
    validation = uav.validate_answer(
        "build includes file usb3_link_ctrl.v", dut_facts_rtl=dut_facts_rtl)
    v_path = tmp_path / "validation.json"
    v_path.write_text(json.dumps(validation.to_dict()), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.conflict_display_package",
         "from-answer-validation", "--validation", str(v_path)],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr
    assert "USER_CLAIM_VS_EVIDENCE_CONFLICT" in result.stdout


def test_cli_reports_a_refusal_as_exit_2(tmp_path):
    dut_facts_rtl = {"status": "PARSED", "files": [{"file_path": "rtl/usb3_link_ctrl.v"}]}
    validation = uav.validate_answer(
        "build includes file rtl/usb3_link_ctrl.v", dut_facts_rtl=dut_facts_rtl)
    assert validation.status == uav.VALIDATED
    v_path = tmp_path / "validation.json"
    v_path.write_text(json.dumps(validation.to_dict()), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.conflict_display_package",
         "from-answer-validation", "--validation", str(v_path)],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["error"] == "ONLY_CONTRADICTED_VALIDATIONS_HAVE_A_CONFLICT_TO_DISPLAY"
