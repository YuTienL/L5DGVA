"""Tests for spec section 218's Requirement Testability classification
(dv_harness/requirement_testability.py), additive on top of
dv_harness/requirement_contract.py.

Discipline followed here, matching test_requirement_contract.py: ONE clean,
fully-populated requirement is asserted TESTABLE with zero findings, and
every other status is then driven by MUTATING that same clean record ONE
defect at a time -- so each assertion proves that rule caught that specific
injected defect. The central negative control
(test_all_unresolved_fields_is_indeterminate_never_guessed) proves the
module refuses to fabricate TESTABLE or UNTESTABLE_PROSE when no real
evidence is present at all -- the property this project's house style
requires every new module's test suite to prove.
"""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from dv_harness import requirement_contract as rc  # noqa: E402
from dv_harness import requirement_testability as rt  # noqa: E402


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

def clean_record(**over):
    """A fully-populated, internally coherent, and genuinely TESTABLE
    requirement. Synthetic -- it describes no real DUT; it exists to be
    mutated. Distinct wording from test_requirement_contract.py's own
    clean_record() so this file does not depend on that module's fixture
    happening to also satisfy this module's own detection patterns."""
    r = {
        "contract_schema_version": "1.0",
        "requirement_id": "REQ-IRQ-EN-001",
        "source": {"document": "soc_prog_guide.pdf", "locator": "section 4.1",
                   "quote": "IRQ_EN shall be asserted within 100 ns of the event."},
        "feature": "interrupt enable latency",
        "protocol": "AMBA_APB",
        "configuration": "NONE",
        "precondition": "NONE",
        "stimulus": "host writes 1 to the IRQ_EN field of STATUS_REG",
        "expected_result": "the STATUS_REG IRQ_EN bit shall equal 1 within 100 ns of the write",
        "observability": "monitor samples STATUS_REG via the register readback interface",
        "checker": "scoreboard asserts the sampled value matches the expected value; "
                   "a mismatch is reported as an assertion failure",
        "coverage_intent": "cover IRQ_EN 0->1 and 1->0 transitions",
        "priority": "P0",
        "criticality": "MAJOR",
        "confidence": "HIGH",
        "status": "COMPLETE",
    }
    r.update(over)
    return r


def findings_codes(findings):
    return {f["code"] for f in findings}


# --------------------------------------------------------------------------
# Vocabulary hygiene
# --------------------------------------------------------------------------

def test_testability_vocabulary_is_disjoint_from_requirement_contract_statuses():
    assert set(rt.TESTABILITY_VALUES).isdisjoint(set(rc.REQUIREMENT_STATUSES))


def test_testability_vocabulary_is_disjoint_from_models_status():
    from dv_harness import models
    assert set(rt.TESTABILITY_VALUES).isdisjoint({s.value for s in models.Status})


def test_collision_guard_passes_on_the_real_vocabulary():
    # Already run at import; re-running must not raise.
    rt.assert_no_status_vocabulary_collision()


def test_collision_guard_actually_detects_a_real_collision(monkeypatch):
    """Proves the guard has real detection power, not just that it happens
    not to fire today."""
    monkeypatch.setattr(rt, "TESTABILITY_VALUES", ("COMPLETE",))
    with pytest.raises(AssertionError):
        rt.assert_no_status_vocabulary_collision()


# --------------------------------------------------------------------------
# The clean, positive TESTABLE path
# --------------------------------------------------------------------------

def test_clean_record_is_testable_with_real_cited_evidence():
    result = rt.classify_requirement_testability(clean_record())
    assert result.status == rt.TESTABILITY_TESTABLE
    assert result.checkable_evidence
    assert result.observable_evidence
    assert "STATUS_REG" in result.observable_evidence


def test_clean_record_produces_zero_findings():
    assert rt.analyze_requirement_testability(clean_record()) == []


def test_a_requirement_not_declaring_contract_shape_is_never_analyzed():
    """This module only judges requirement_contract-shaped records -- the
    same discriminator declares_contract_shape() already establishes."""
    legacy = {"req_id": "R1", "expected_behavior": "shall work correctly"}
    assert rt.analyze_requirement_testability(legacy) == []


# --------------------------------------------------------------------------
# UNTESTABLE_PROSE -- resolved text, no checkable condition, no observable
# --------------------------------------------------------------------------

def test_purely_qualitative_prose_is_untestable():
    rec = clean_record(
        expected_result="the interrupt handling shall work correctly and behave as expected",
        observability="the system shall operate properly under all conditions",
        checker="the response shall be adequate and satisfactory",
    )
    result = rt.classify_requirement_testability(rec)
    assert result.status == rt.TESTABILITY_UNTESTABLE_PROSE
    assert result.checkable_evidence == []
    assert result.observable_evidence == []
    assert result.untestable_phrases


def test_untestable_prose_produces_a_warning_finding():
    rec = clean_record(
        expected_result="the interrupt handling shall work correctly",
        observability="the system shall behave as expected",
        checker="the response shall be reasonable",
    )
    findings = rt.analyze_requirement_testability(rec)
    assert findings_codes(findings) == {"REQUIREMENT_UNTESTABLE_PROSE"}
    assert findings[0]["severity"] == rt.SEVERITY_WARNING


def test_untestable_prose_reuses_requirement_contracts_hedging_scan():
    """detect_ambiguous_language() hits (a hedge with no checkable/observable
    elsewhere) contribute to the untestable-prose determination too."""
    rec = clean_record(
        expected_result="the device should generally respond in most cases",
        observability="TBD",
        checker="TBD",
    )
    result = rt.classify_requirement_testability(rec)
    assert result.status == rt.TESTABILITY_UNTESTABLE_PROSE
    bases = {h["basis"] for h in result.untestable_phrases}
    assert "hedging_scan" in bases


# --------------------------------------------------------------------------
# INDETERMINATE -- the central negative control: absent evidence must never
# be guessed toward TESTABLE or UNTESTABLE_PROSE.
# --------------------------------------------------------------------------

def test_all_unresolved_fields_is_indeterminate_never_guessed():
    rec = clean_record(expected_result="TBD", observability="UNKNOWN", checker="N/A")
    result = rt.classify_requirement_testability(rec)
    assert result.status == rt.TESTABILITY_INDETERMINATE
    assert "unresolved" in result.reason
    assert result.checkable_evidence == []
    assert result.observable_evidence == []


def test_all_unresolved_fields_produces_an_info_finding_not_a_warning():
    rec = clean_record(expected_result="", observability="", checker="")
    findings = rt.analyze_requirement_testability(rec)
    assert findings_codes(findings) == {"REQUIREMENT_TESTABILITY_INDETERMINATE"}
    assert findings[0]["severity"] == rt.SEVERITY_INFO


def test_checkable_without_observable_is_indeterminate_not_testable():
    rec = clean_record(
        expected_result="the returned value shall equal 5",
        checker="assert result matches expectation",
        observability="TBD",
    )
    result = rt.classify_requirement_testability(rec)
    assert result.status == rt.TESTABILITY_INDETERMINATE
    assert result.checkable_evidence
    assert result.observable_evidence == []
    assert "no observable signal" in result.reason


def test_observable_without_checkable_is_indeterminate_not_testable():
    rec = clean_record(
        expected_result="TBD",
        checker="TBD",
        observability="monitor observes STATUS_REG on the bus",
    )
    result = rt.classify_requirement_testability(rec)
    assert result.status == rt.TESTABILITY_INDETERMINATE
    assert result.observable_evidence
    assert result.checkable_evidence == []
    assert "no checkable condition" in result.reason


# --------------------------------------------------------------------------
# Detection primitives, individually
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text,expect_label", [
    ("value shall equal 5", "comparison_phrase"),
    ("observed == expected", "comparison_operator"),
    ("register shall be set to 1", "assignment_phrase"),
    ("address is 0xFF", "hex_literal"),
    ("value is 8'hFF", "verilog_literal"),
    ("within 100 ns of the event", "timing_value"),
    ("no more than 3 retries", "bounded_value"),
    ("scoreboard flags a mismatch", "checker_mechanism"),
])
def test_detect_checkable_condition_positive(text, expect_label):
    assert expect_label in rt.detect_checkable_condition(text)


def test_detect_checkable_condition_on_vague_text_is_empty():
    assert rt.detect_checkable_condition("the system shall work correctly") == []


def test_detect_checkable_condition_on_unresolved_input_is_empty():
    assert rt.detect_checkable_condition("TBD") == []
    assert rt.detect_checkable_condition(None) == []


@pytest.mark.parametrize("text,expect", [
    ("STATUS_REG bit is sampled", "STATUS_REG"),
    ("a waveform trace was captured", "observation_mechanism"),
    ("the monitor observes the bus", "observation_mechanism"),
])
def test_detect_observable_signal_positive(text, expect):
    assert expect in rt.detect_observable_signal(text)


def test_detect_observable_signal_on_vague_text_is_empty():
    assert rt.detect_observable_signal("the system shall behave correctly") == []


@pytest.mark.parametrize("phrase", [
    "shall work correctly", "behave as expected", "be robust",
    "in a timely manner", "adequate", "satisfactory",
])
def test_detect_untestable_prose_phrases_positive(phrase):
    assert phrase in rt.detect_untestable_prose_phrases(f"the system {phrase}.") or \
        any(phrase in hit for hit in rt.detect_untestable_prose_phrases(f"the system {phrase}."))


def test_detect_untestable_prose_phrases_longest_match_wins():
    hits = rt.detect_untestable_prose_phrases("the device shall work correctly under load")
    # Both "shall work correctly" and the shorter "work correctly" it contains
    # are in the phrase list; only the longer one should survive de-dup.
    assert hits == ["shall work correctly"]


def test_detect_untestable_prose_phrases_on_concrete_text_is_empty():
    assert rt.detect_untestable_prose_phrases("STATUS_REG shall equal 0x1 within 10 ns") == []


# --------------------------------------------------------------------------
# Set-level analysis
# --------------------------------------------------------------------------

def test_analyze_set_counts_and_skips_non_contract_records():
    records = [
        clean_record(requirement_id="R1"),
        clean_record(requirement_id="R2", expected_result="shall work correctly",
                     observability="shall operate properly", checker="shall be adequate"),
        {"req_id": "legacy", "expected_behavior": "not contract shaped"},
    ]
    result = rt.analyze_requirement_testability_set(records)
    assert result["analyzed"] == 2
    assert result["testability_counts"][rt.TESTABILITY_TESTABLE] == 1
    assert result["testability_counts"][rt.TESTABILITY_UNTESTABLE_PROSE] == 1
    assert len(result["findings"]) == 1


def test_analyze_set_over_empty_list_reports_zero_analyzed():
    result = rt.analyze_requirement_testability_set([])
    assert result["analyzed"] == 0
    assert result["findings"] == []


# --------------------------------------------------------------------------
# execute_verb / CLI front door
# --------------------------------------------------------------------------

def _write(tmp_path, payload):
    p = tmp_path / "requirements.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_execute_verb_pass_on_clean_document(tmp_path):
    p = _write(tmp_path, {"schema_version": "1.0", "requirements": [clean_record()]})
    text, code = rt.execute_verb(str(p))
    assert code == 0
    assert "PASS" in text


def test_execute_verb_fail_on_untestable_document(tmp_path):
    rec = clean_record(expected_result="shall work correctly",
                       observability="shall operate properly",
                       checker="shall be adequate")
    p = _write(tmp_path, {"schema_version": "1.0", "requirements": [rec]})
    text, code = rt.execute_verb(str(p))
    assert code == 1
    assert "FAIL" in text
    assert "REQUIREMENT_UNTESTABLE_PROSE" in text


def test_execute_verb_not_available_when_nothing_in_contract_shape(tmp_path):
    p = _write(tmp_path, {"schema_version": "1.0",
                          "requirements": [{"req_id": "legacy"}]})
    text, code = rt.execute_verb(str(p))
    assert code == 2
    assert "NOT_AVAILABLE" in text


def test_execute_verb_not_available_on_missing_file(tmp_path):
    text, code = rt.execute_verb(str(tmp_path / "does_not_exist.json"))
    assert code == 2
    assert "NOT_AVAILABLE" in text


def test_execute_verb_json_output_is_valid_json(tmp_path):
    p = _write(tmp_path, {"schema_version": "1.0", "requirements": [clean_record()]})
    text, code = rt.execute_verb(str(p), as_json=True)
    parsed = json.loads(text)
    assert parsed["status"] == "PASS"
    assert code == 0


def test_execute_verb_fail_on_indeterminate_when_flagged(tmp_path):
    rec = clean_record(expected_result="TBD", observability="TBD", checker="TBD")
    p = _write(tmp_path, {"schema_version": "1.0", "requirements": [rec]})
    _, code_default = rt.execute_verb(str(p))
    _, code_strict = rt.execute_verb(str(p), fail_on_indeterminate=True)
    assert code_default == 0
    assert code_strict == 1


def test_real_cli_subprocess_pass(tmp_path):
    p = _write(tmp_path, {"schema_version": "1.0", "requirements": [clean_record()]})
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.requirement_testability",
         "--requirements", str(p)],
        capture_output=True, text=True, cwd=str(ROOT))
    assert result.returncode == 0
    assert "PASS" in result.stdout


def test_real_cli_subprocess_fail(tmp_path):
    rec = clean_record(expected_result="shall work correctly",
                       observability="shall operate properly",
                       checker="shall be adequate")
    p = _write(tmp_path, {"schema_version": "1.0", "requirements": [rec]})
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.requirement_testability",
         "--requirements", str(p)],
        capture_output=True, text=True, cwd=str(ROOT))
    assert result.returncode == 1
    assert "FAIL" in result.stdout
