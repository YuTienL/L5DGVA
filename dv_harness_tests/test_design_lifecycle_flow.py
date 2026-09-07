"""Tests for dv_harness/design_lifecycle_flow.py.

Fixtures live under dv_harness_tests/fixtures/design_lifecycle_flow/ and are
synthetic (their own file headers say so, not any real DUT's programming
guide). The positive-path test proves the initialization/shutdown/recovery
flows are extracted correctly from real supplied text and correctly
classified against `programming_sequence_ir`'s own PHASE vocabulary; the
negative controls prove the module reports honest NOT_AVAILABLE/UNCLASSIFIED
rather than fabricating a flow, a step, or a phase when the supplied text
does not state one.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import design_lifecycle_flow as dlf
from dv_harness import programming_sequence_ir as psir

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "design_lifecycle_flow"
GUIDE_FIXTURE = FIXTURES / "programming_guide.txt"
VIOLATION_FIXTURE = FIXTURES / "phase_order_violation.txt"
UNCLASSIFIED_FIXTURE = FIXTURES / "unclassified_step.txt"
BLANK_FIXTURE = FIXTURES / "no_lifecycle_flows.txt"
NO_STEP_CHAIN_FIXTURE = FIXTURES / "heading_no_step_chain.txt"


# ---------------------------------------------------------------------------
# Reuse discipline: the phase vocabulary is IMPORTED from
# programming_sequence_ir.py, never re-declared.
# ---------------------------------------------------------------------------
def test_phase_vocabulary_is_imported_directly_from_programming_sequence_ir():
    assert dlf.PHASE_INIT is psir.PHASE_INIT
    assert dlf.PHASE_CONFIGURE is psir.PHASE_CONFIGURE
    assert dlf.PHASE_ENABLE is psir.PHASE_ENABLE
    assert dlf.PHASE_RUN is psir.PHASE_RUN
    assert dlf.PHASE_WAIT is psir.PHASE_WAIT
    assert dlf.PHASE_VERIFY is psir.PHASE_VERIFY
    assert dlf.PHASE_DISABLE is psir.PHASE_DISABLE
    assert dlf.PHASE_RESET is psir.PHASE_RESET
    assert dlf.PHASE_RANK is psir.PHASE_RANK
    assert dlf.CANONICAL_PHASES is psir.CANONICAL_PHASES


# ---------------------------------------------------------------------------
# Positive path: real spec text -> all three flows extracted correctly.
# ---------------------------------------------------------------------------
def test_positive_path_extracts_initialization_flow_from_arrow_chain():
    report = dlf.extract_design_lifecycle_flow([str(GUIDE_FIXTURE)])
    assert report["status"] == dlf.STATUS_LOADED
    assert report["reason"] is None

    init = report["initialization_flow"]
    assert init["status"] == dlf.STATUS_LOADED
    texts = [s["text"] for s in init["steps"]]
    assert texts == [
        "Reset", "Clock/PHY readiness", "Base configuration", "Mode configuration",
        "Buffer/DMA setup", "Interrupt setup", "Enable block", "Wait ready", "Start operation",
    ]
    phases = [s["phase"] for s in init["steps"]]
    assert phases == [
        psir.PHASE_INIT, psir.PHASE_INIT, psir.PHASE_CONFIGURE, psir.PHASE_CONFIGURE,
        psir.PHASE_CONFIGURE, psir.PHASE_CONFIGURE, psir.PHASE_ENABLE, psir.PHASE_WAIT, psir.PHASE_RUN,
    ]
    assert all(s["phase_status"] == dlf.PHASE_STATUS_CLASSIFIED for s in init["steps"])
    assert init["phase_order_check"]["status"] == dlf.PHASE_ORDER_VALID
    assert init["phase_order_check"]["violations"] == []
    # every step carries a real, checkable file:line citation
    for s in init["steps"]:
        path, lineno = s["evidence"].rsplit(":", 1)
        assert path == str(GUIDE_FIXTURE)
        assert int(lineno) > 0


def test_positive_path_extracts_shutdown_flow_from_numbered_list():
    report = dlf.extract_design_lifecycle_flow([str(GUIDE_FIXTURE)])
    sd = report["shutdown_flow"]
    assert sd["status"] == dlf.STATUS_LOADED
    texts = [s["text"] for s in sd["steps"]]
    assert texts == [
        "Stop traffic", "Wait idle", "Disable engine", "Clear pending status",
        "Disable interrupts", "Reset if required",
    ]
    phases = [s["phase"] for s in sd["steps"]]
    assert phases == [
        psir.PHASE_DISABLE, psir.PHASE_WAIT, psir.PHASE_DISABLE, psir.PHASE_DISABLE,
        psir.PHASE_DISABLE, psir.PHASE_RESET,
    ]
    assert sd["phase_order_check"]["status"] == dlf.PHASE_ORDER_VALID


def test_positive_path_extracts_recovery_triggers_sub_heading_and_inline_forms():
    report = dlf.extract_design_lifecycle_flow([str(GUIDE_FIXTURE)])
    rec = report["recovery_flow"]
    assert rec["status"] == dlf.STATUS_LOADED

    timeout = rec["triggers"][dlf.TRIGGER_TIMEOUT]
    assert timeout["status"] == dlf.STATUS_LOADED
    assert [s["text"] for s in timeout["steps"]] == ["Disable engine", "Reset block"]
    assert [s["phase"] for s in timeout["steps"]] == [psir.PHASE_DISABLE, psir.PHASE_RESET]
    assert timeout["phase_order_check"]["status"] == dlf.PHASE_ORDER_VALID

    protocol_error = rec["triggers"][dlf.TRIGGER_PROTOCOL_ERROR]
    assert protocol_error["status"] == dlf.STATUS_LOADED
    assert [s["text"] for s in protocol_error["steps"]] == ["disable engine", "reset link", "reinitialize"]
    assert [s["phase"] for s in protocol_error["steps"]] == [
        psir.PHASE_DISABLE, psir.PHASE_RESET, psir.PHASE_INIT]

    link_loss = rec["triggers"][dlf.TRIGGER_LINK_LOSS]
    assert link_loss["status"] == dlf.STATUS_LOADED
    assert [s["text"] for s in link_loss["steps"]] == ["Disable engine", "Wait idle", "Reset block"]
    assert link_loss["phase_order_check"]["status"] == dlf.PHASE_ORDER_VALID

    # triggers with no evidence anywhere in the fixture stay honestly absent
    for trig in (dlf.TRIGGER_PHY_ERROR, dlf.TRIGGER_DMA_ERROR, dlf.TRIGGER_BUFFER_ERROR,
                 dlf.TRIGGER_SOFTWARE_ABORT):
        entry = rec["triggers"][trig]
        assert entry["status"] == dlf.STATUS_NOT_AVAILABLE
        assert entry["steps"] == []
        assert trig in entry["reason"] or "no documented recovery action" in entry["reason"]


def test_recovery_trigger_never_absorbs_a_foreign_trigger_inline_line():
    """The 'Protocol Error: ...' line sits textually inside the Timeout
    Recovery sub-heading's own block (no sub-heading separates the two) --
    proving `timeout`'s step chain is the real bulleted pair, not the
    unrelated inline protocol_error line, is the real detection power of
    `_strip_foreign_inline_trigger_lines()`."""
    report = dlf.extract_design_lifecycle_flow([str(GUIDE_FIXTURE)])
    timeout = report["recovery_flow"]["triggers"][dlf.TRIGGER_TIMEOUT]
    assert "Protocol Error" not in " ".join(s["text"] for s in timeout["steps"])
    assert len(timeout["steps"]) == 2


# ---------------------------------------------------------------------------
# Phase-order violation: a real, honestly-computed finding, never suppressed.
# ---------------------------------------------------------------------------
def test_phase_order_violation_is_detected_and_cites_both_steps():
    report = dlf.extract_design_lifecycle_flow([str(VIOLATION_FIXTURE)])
    init = report["initialization_flow"]
    assert init["status"] == dlf.STATUS_LOADED
    check = init["phase_order_check"]
    assert check["status"] == dlf.PHASE_ORDER_VIOLATION
    assert len(check["violations"]) == 1
    v = check["violations"][0]
    assert v["phase"] == psir.PHASE_CONFIGURE
    assert v["after_phase"] == psir.PHASE_ENABLE
    assert v["step_index"] == 1
    assert v["after_step_index"] == 0


def test_check_phase_order_reuses_the_real_phase_rank_table():
    steps = [
        dlf.FlowStep(index=0, text="a", evidence="x:1", phase=psir.PHASE_ENABLE),
        dlf.FlowStep(index=1, text="b", evidence="x:2", phase=psir.PHASE_INIT),
    ]
    report = dlf.check_phase_order(steps)
    assert report["status"] == dlf.PHASE_ORDER_VIOLATION
    assert report["violations"][0]["rank"] == psir.PHASE_RANK[psir.PHASE_INIT]
    assert report["violations"][0]["after_rank"] == psir.PHASE_RANK[psir.PHASE_ENABLE]


def test_check_phase_order_not_applicable_below_two_classified_steps():
    assert dlf.check_phase_order([])["status"] == dlf.PHASE_ORDER_NOT_APPLICABLE
    one = [dlf.FlowStep(index=0, text="a", evidence="x:1", phase=psir.PHASE_INIT)]
    assert dlf.check_phase_order(one)["status"] == dlf.PHASE_ORDER_NOT_APPLICABLE
    two_unclassified = [
        dlf.FlowStep(index=0, text="a", evidence="x:1", phase=None),
        dlf.FlowStep(index=1, text="b", evidence="x:2", phase=None),
    ]
    assert dlf.check_phase_order(two_unclassified)["status"] == dlf.PHASE_ORDER_NOT_APPLICABLE


# ---------------------------------------------------------------------------
# UNCLASSIFIED steps: never coerced onto a canonical phase, never dropped.
# ---------------------------------------------------------------------------
def test_unclassified_step_is_reported_honestly_never_guessed():
    report = dlf.extract_design_lifecycle_flow([str(UNCLASSIFIED_FIXTURE)])
    init = report["initialization_flow"]
    assert init["status"] == dlf.STATUS_LOADED
    steps = init["steps"]
    assert len(steps) == 3
    calibration = steps[1]
    assert calibration["text"] == "Perform vendor calibration handshake"
    assert calibration["phase"] is None
    assert calibration["phase_status"] == dlf.PHASE_STATUS_UNCLASSIFIED
    # the two classified steps around it still order-check cleanly; the
    # unclassified step contributes no rank claim either way
    assert init["phase_order_check"]["status"] == dlf.PHASE_ORDER_VALID


def test_classify_step_phase_reset_word_means_different_phases_per_flow_context():
    """The identical word 'reset' is the INIT-phase precondition at the
    start of an initialization flow, and the RESET-phase teardown action at
    the end of a shutdown flow -- real, disclosed, structural evidence
    (which flow the step was extracted from), not an unexplained
    inconsistency."""
    assert dlf.classify_step_phase("Reset", dlf.FLOW_INITIALIZATION) == psir.PHASE_INIT
    assert dlf.classify_step_phase("Reset if required", dlf.FLOW_SHUTDOWN) == psir.PHASE_RESET


def test_classify_step_phase_rejects_unknown_flow_kind():
    with pytest.raises(dlf.DesignLifecycleFlowError):
        dlf.classify_step_phase("Reset", "not_a_real_flow")


# ---------------------------------------------------------------------------
# Honest absence: no heading at all vs. a heading with no step-chain shape.
# ---------------------------------------------------------------------------
def test_no_recognized_heading_reports_not_available():
    report = dlf.extract_design_lifecycle_flow([str(BLANK_FIXTURE)])
    assert report["status"] == dlf.STATUS_NOT_AVAILABLE
    for key in ("initialization_flow", "shutdown_flow"):
        block = report[key]
        assert block["status"] == dlf.STATUS_NOT_AVAILABLE
        assert "no heading" in block["reason"]
        assert block["steps"] == []
    assert report["recovery_flow"]["status"] == dlf.STATUS_NOT_AVAILABLE
    for trig, entry in report["recovery_flow"]["triggers"].items():
        assert entry["status"] == dlf.STATUS_NOT_AVAILABLE


def test_heading_found_but_no_step_chain_is_a_distinct_reason():
    report = dlf.extract_design_lifecycle_flow([str(NO_STEP_CHAIN_FIXTURE)])
    init = report["initialization_flow"]
    assert init["status"] == dlf.STATUS_NOT_AVAILABLE
    assert "no recognizable step chain" in init["reason"]
    assert "no heading" not in init["reason"]


# ---------------------------------------------------------------------------
# Source-file honesty: missing/unsupplied sources never fabricate a flow.
# ---------------------------------------------------------------------------
def test_no_sources_supplied_is_honestly_not_available():
    report = dlf.extract_design_lifecycle_flow([])
    assert report["status"] == dlf.STATUS_NOT_AVAILABLE
    assert report["reason"] == "no source files were supplied"
    assert report["initialization_flow"]["status"] == dlf.STATUS_NOT_AVAILABLE
    assert report["shutdown_flow"]["status"] == dlf.STATUS_NOT_AVAILABLE
    assert report["recovery_flow"]["status"] == dlf.STATUS_NOT_AVAILABLE


def test_missing_source_file_is_recorded_not_silently_skipped():
    missing = str(FIXTURES / "does_not_exist.txt")
    report = dlf.extract_design_lifecycle_flow([missing])
    assert report["status"] == dlf.STATUS_NOT_AVAILABLE
    assert missing in report["source"]["missing"]
    assert report["source"]["paths"] == []


def test_a_real_and_a_missing_source_together_still_extract_the_real_one():
    missing = str(FIXTURES / "does_not_exist.txt")
    report = dlf.extract_design_lifecycle_flow([str(GUIDE_FIXTURE), missing])
    assert report["status"] == dlf.STATUS_LOADED
    assert missing in report["source"]["missing"]
    assert str(GUIDE_FIXTURE) in report["source"]["paths"]
    assert report["initialization_flow"]["status"] == dlf.STATUS_LOADED


# ---------------------------------------------------------------------------
# extract_step_chain() shape priority, tested directly.
# ---------------------------------------------------------------------------
def test_extract_step_chain_prefers_numbered_list_over_bullets():
    content = ["1. First", "2. Second", "- ignored bullet"]
    steps = dlf.extract_step_chain(content, 1, "x")
    assert [s.text for s in steps] == ["First", "Second"]


def test_extract_step_chain_single_bullet_is_accepted():
    content = ["- Only one recovery action"]
    steps = dlf.extract_step_chain(content, 1, "x")
    assert [s.text for s in steps] == ["Only one recovery action"]


def test_extract_step_chain_returns_empty_for_no_recognized_shape():
    content = ["Just a prose sentence.", "Another one."]
    assert dlf.extract_step_chain(content, 1, "x") == []


def test_arrow_chain_skips_leading_prose_before_the_real_seed():
    content = ["Example generic form:", "", "Reset", "-> Enable block"]
    steps = dlf.extract_step_chain(content, 1, "x")
    assert [s.text for s in steps] == ["Reset", "Enable block"]


# ---------------------------------------------------------------------------
# Interoperability: to_programming_sequence_ir() builds the REAL
# programming_sequence_ir types, never a re-declared parallel dataclass.
# ---------------------------------------------------------------------------
def test_to_programming_sequence_ir_builds_real_types_and_unclassified_token():
    steps = [
        dlf.FlowStep(index=0, text="Reset", evidence="x:1", phase=psir.PHASE_INIT),
        dlf.FlowStep(index=1, text="A mystery step", evidence="x:2", phase=None),
    ]
    ir = dlf.to_programming_sequence_ir("test_flow", steps)
    assert isinstance(ir, psir.ProgrammingSequenceIR)
    assert ir.name == "test_flow"
    assert len(ir.steps) == 2
    assert all(isinstance(s, psir.ProgrammingSequenceStep) for s in ir.steps)
    assert ir.steps[0].phase == psir.PHASE_INIT
    assert ir.steps[0].action == psir.ACTION_WAIT
    assert ir.steps[0].register is None
    assert ir.steps[0].description == "Reset"
    assert ir.steps[1].phase == "UNCLASSIFIED"
    assert "UNCLASSIFIED" not in psir.PHASE_RANK


def test_the_real_programming_sequence_ir_validator_flags_the_unclassified_phase():
    """Genuine interoperability, proven end to end: a caller supplying real
    register facts (even a single unrelated one, just to clear
    `validate_step_ordering()`'s own facts-required gate) gets the REAL
    UNKNOWN_PHASE finding back from `programming_sequence_ir.py`'s own
    validator for the step this module could not classify."""
    steps = [
        dlf.FlowStep(index=0, text="Reset", evidence="x:1", phase=psir.PHASE_INIT),
        dlf.FlowStep(index=1, text="A mystery step", evidence="x:2", phase=None),
    ]
    ir = dlf.to_programming_sequence_ir("test_flow", steps)
    facts = psir.register_facts_from_dicts([{"name": "placeholder_reg"}])
    report = psir.validate_step_ordering(ir, facts)
    assert report["status"] == psir.STATUS_ORDER_INVALID
    codes = {f["code"] for f in report["findings"]}
    assert psir.FINDING_UNKNOWN_PHASE in codes


def test_to_programming_sequence_ir_clean_flow_validates_order_valid_through_the_real_validator():
    report = dlf.extract_design_lifecycle_flow([str(GUIDE_FIXTURE)])
    init_steps = [
        dlf.FlowStep(**{k: v for k, v in s.items() if k in ("index", "text", "evidence", "phase")})
        for s in report["initialization_flow"]["steps"]
    ]
    ir = dlf.to_programming_sequence_ir("initialization", init_steps)
    facts = psir.register_facts_from_dicts([{"name": "placeholder_reg"}])
    validated = psir.validate_step_ordering(ir, facts)
    assert validated["status"] == psir.STATUS_ORDER_VALID


# ---------------------------------------------------------------------------
# Vocabulary hygiene.
# ---------------------------------------------------------------------------
def test_status_vocabulary_never_collides_with_models_status():
    dlf.assert_no_verification_verdict_vocabulary()  # must not raise


def test_recovery_triggers_match_section_313s_seven_named_conditions():
    assert dlf.RECOVERY_TRIGGERS == (
        "timeout", "protocol_error", "phy_error", "dma_error",
        "buffer_error", "software_abort", "link_loss",
    )
    assert set(dlf.TRIGGER_PATTERNS) == set(dlf.RECOVERY_TRIGGERS)


# ---------------------------------------------------------------------------
# CLI front door.
# ---------------------------------------------------------------------------
def test_cli_extract_json_exit_code_zero_on_a_loaded_flow():
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.design_lifecycle_flow", "extract",
         "--sources", str(GUIDE_FIXTURE), "--json"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == dlf.STATUS_LOADED
    assert payload["initialization_flow"]["status"] == dlf.STATUS_LOADED


def test_cli_extract_text_exit_code_two_on_not_available():
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.design_lifecycle_flow", "extract",
         "--sources", str(BLANK_FIXTURE)],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
    )
    assert result.returncode == 2
    assert "NOT_AVAILABLE" in result.stdout


def test_cli_usage_error_with_no_verb():
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.design_lifecycle_flow"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
    )
    assert result.returncode == 2
    assert "usage" in result.stderr
