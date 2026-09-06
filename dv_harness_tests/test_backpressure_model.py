"""Tests for dv_harness/backpressure_model.py.

Proves: legal-backpressure-tolerance classification on named AMBA channels is derived ONLY from
real, caller-supplied evidence text (never from the channel name), honestly reports NOT_AVAILABLE
when no evidence is supplied, reports AMBIGUOUS on genuinely conflicting evidence, and the
stall-violation comparison never invents a bound or an observed value.
"""
import json
import subprocess
import sys

import pytest

from dv_harness.backpressure_model import (
    AMBA_CHANNELS,
    BackpressureModelError,
    ChannelToleranceResult,
    assert_no_verification_verdict_vocabulary,
    build_backpressure_model,
    classify_channel_tolerance,
    detect_stall_violation,
    format_backpressure_report,
)


# ---------------------------------------------------------------------------
# Vocabulary hygiene
# ---------------------------------------------------------------------------

def test_status_vocabulary_never_collides_with_models_status():
    # Must not raise.
    assert_no_verification_verdict_vocabulary()


def test_amba_channels_is_fixed_and_covers_the_task_named_channels():
    assert "AXI_AW" in AMBA_CHANNELS
    assert "AXI_W" in AMBA_CHANNELS
    assert "AXI_B" in AMBA_CHANNELS
    assert "AXI_AR" in AMBA_CHANNELS
    assert "AXI_R" in AMBA_CHANNELS
    assert "AHB_HREADY" in AMBA_CHANNELS
    assert "APB_PREADY" in AMBA_CHANNELS
    assert "GENERIC_VALID_READY" in AMBA_CHANNELS


# ---------------------------------------------------------------------------
# Core positive path: BOUNDED classification
# ---------------------------------------------------------------------------

def test_bounded_stall_classified_from_evidence_text():
    result = classify_channel_tolerance(
        "AXI_AW",
        "The interconnect specifies a maximum stall of 16 cycles on this channel before the "
        "transaction must be considered a protocol violation.")
    assert result.status == "RESOLVED"
    assert result.tolerance_class == "BOUNDED"
    assert result.max_stall_cycles == 16
    assert len(result.evidence) == 1
    assert "16" in result.evidence[0].matched_text


def test_bounded_stall_alternate_phrasing_must_assert_ready_within():
    result = classify_channel_tolerance(
        "AHB_HREADY",
        "The slave must assert HREADY within 8 cycles of HTRANS going non-IDLE, per section 4.2.")
    assert result.status == "RESOLVED"
    assert result.tolerance_class == "BOUNDED"
    assert result.max_stall_cycles == 8


def test_bounded_stall_up_to_n_wait_states_phrasing():
    result = classify_channel_tolerance(
        "APB_PREADY", "The slave may insert up to 4 wait states before asserting PREADY.")
    assert result.status == "RESOLVED"
    assert result.tolerance_class == "BOUNDED"
    assert result.max_stall_cycles == 4


# ---------------------------------------------------------------------------
# Core positive path: UNBOUNDED classification
# ---------------------------------------------------------------------------

def test_unbounded_stall_classified_from_evidence_text():
    result = classify_channel_tolerance(
        "AXI_R",
        "Per the RTL comment at fabric_arb.v:212, RVALID may be held low indefinitely while the "
        "backing memory is busy -- there is no bound on the number of wait states here.")
    assert result.status == "RESOLVED"
    assert result.tolerance_class == "UNBOUNDED"
    assert result.max_stall_cycles is None
    assert len(result.evidence) >= 1


def test_unbounded_stall_generic_valid_ready_phrasing():
    result = classify_channel_tolerance(
        "GENERIC_VALID_READY",
        "The consuming block may deassert ready indefinitely under backpressure, per the "
        "programming guide's flow-control section.")
    assert result.status == "RESOLVED"
    assert result.tolerance_class == "UNBOUNDED"


# ---------------------------------------------------------------------------
# THE HEADLINE TEST: refuses to claim a fact when required evidence is absent
# ---------------------------------------------------------------------------

def test_no_evidence_supplied_reports_not_available_never_a_guess():
    result = classify_channel_tolerance("AXI_AW", None)
    assert result.status == "NOT_AVAILABLE"
    assert result.tolerance_class == "UNKNOWN"
    assert result.max_stall_cycles is None
    assert result.evidence == []


def test_empty_string_evidence_reports_not_available():
    result = classify_channel_tolerance("APB_PREADY", "   ")
    assert result.status == "NOT_AVAILABLE"


def test_channel_name_alone_never_implies_a_tolerance_even_when_name_suggests_one():
    # A channel literally named to look "AXI-like" with real-looking but empty evidence must not
    # inherit any assumed protocol-general tolerance (e.g. "AXI READY may stall forever") -- the
    # Evidence Truth Rule requires this be classified purely from the (absent) evidence text.
    result = classify_channel_tolerance("AXI_AW", {"citation": "no evidence_text key supplied here"})
    assert result.status == "NOT_AVAILABLE"
    assert result.tolerance_class == "UNKNOWN"


def test_unrecognized_phrasing_reports_not_available_not_a_guess():
    result = classify_channel_tolerance(
        "AXI_W", "The write channel behaves reasonably under load in most configurations.")
    assert result.status == "NOT_AVAILABLE"
    assert result.evidence == []


# ---------------------------------------------------------------------------
# AMBIGUOUS: both claims present, never resolved by picking one
# ---------------------------------------------------------------------------

def test_conflicting_bounded_and_unbounded_evidence_is_ambiguous():
    result = classify_channel_tolerance(
        "AXI_B",
        "The design document states a maximum stall of 32 cycles on BVALID, but an earlier "
        "revision's RTL comment says BVALID may be held low indefinitely under congestion.")
    assert result.status == "AMBIGUOUS"
    assert result.tolerance_class == "UNKNOWN"
    assert result.max_stall_cycles is None
    classes_cited = {e.tolerance_class for e in result.evidence}
    assert classes_cited == {"BOUNDED", "UNBOUNDED"}


# ---------------------------------------------------------------------------
# Duck-typed evidence input (mapping and attribute-bearing object)
# ---------------------------------------------------------------------------

def test_evidence_as_mapping_with_evidence_text_key():
    result = classify_channel_tolerance(
        "AXI_AR", {"evidence_text": "The arbiter allows a maximum stall of 20 cycles on ARVALID."})
    assert result.status == "RESOLVED"
    assert result.max_stall_cycles == 20


def test_evidence_as_attribute_bearing_object():
    class Evidence:
        text = "The slave must assert HREADY within 12 cycles per the datasheet."

    result = classify_channel_tolerance("AHB_HREADY", Evidence())
    assert result.status == "RESOLVED"
    assert result.max_stall_cycles == 12


def test_unrecognized_channel_name_raises():
    with pytest.raises(BackpressureModelError):
        classify_channel_tolerance("AXI_NOT_A_REAL_CHANNEL", "a maximum stall of 4 cycles")


# ---------------------------------------------------------------------------
# build_backpressure_model: full per-project record, every channel always present
# ---------------------------------------------------------------------------

def test_build_backpressure_model_covers_every_channel_even_with_no_evidence():
    model = build_backpressure_model({})
    assert set(model.results.keys()) == set(AMBA_CHANNELS)
    for ch in AMBA_CHANNELS:
        assert model.results[ch].status == "NOT_AVAILABLE"


def test_build_backpressure_model_with_partial_evidence():
    model = build_backpressure_model({
        "AXI_AW": "a maximum stall of 10 cycles",
        "APB_PREADY": "PREADY may be deasserted indefinitely while the peripheral clock is gated",
    })
    assert model.results["AXI_AW"].status == "RESOLVED"
    assert model.results["AXI_AW"].tolerance_class == "BOUNDED"
    assert model.results["APB_PREADY"].tolerance_class == "UNBOUNDED"
    # Every other channel got no evidence at all -- honestly NOT_AVAILABLE, not silently omitted.
    for ch in AMBA_CHANNELS:
        if ch not in ("AXI_AW", "APB_PREADY"):
            assert model.results[ch].status == "NOT_AVAILABLE"


def test_format_backpressure_report_renders_a_markdown_table():
    model = build_backpressure_model({"AXI_R": "a maximum stall of 6 cycles"})
    text = format_backpressure_report(model)
    assert "AXI_R" in text
    assert "BOUNDED" in text
    assert "6" in text
    assert "|" in text  # markdown pipe table


# ---------------------------------------------------------------------------
# detect_stall_violation: never invents a bound or an observed value
# ---------------------------------------------------------------------------

def test_stall_violation_within_bound():
    tolerance = classify_channel_tolerance("AXI_AW", "a maximum stall of 16 cycles")
    result = detect_stall_violation(tolerance, observed_max_stall_cycles=10)
    assert result.status == "WITHIN_TOLERANCE"
    assert result.declared_max_stall_cycles == 16
    assert result.observed_max_stall_cycles == 10


def test_stall_violation_exceeds_bound():
    tolerance = classify_channel_tolerance("AXI_AW", "a maximum stall of 16 cycles")
    result = detect_stall_violation(tolerance, observed_max_stall_cycles=17)
    assert result.status == "VIOLATION"
    assert result.declared_max_stall_cycles == 16
    assert result.observed_max_stall_cycles == 17


def test_stall_violation_unbounded_channel_is_always_within_tolerance():
    tolerance = classify_channel_tolerance("AXI_R", "RVALID may stall indefinitely")
    result = detect_stall_violation(tolerance, observed_max_stall_cycles=999999)
    assert result.status == "WITHIN_TOLERANCE"
    assert result.declared_max_stall_cycles is None


def test_stall_violation_no_observed_value_supplied_is_unknown_never_a_guess():
    tolerance = classify_channel_tolerance("AXI_AW", "a maximum stall of 16 cycles")
    result = detect_stall_violation(tolerance, observed_max_stall_cycles=None)
    assert result.status == "UNKNOWN"
    assert result.observed_max_stall_cycles is None


def test_stall_violation_unresolved_tolerance_is_unknown():
    tolerance = classify_channel_tolerance("AXI_W", None)  # NOT_AVAILABLE
    result = detect_stall_violation(tolerance, observed_max_stall_cycles=5)
    assert result.status == "UNKNOWN"


def test_stall_violation_ambiguous_tolerance_is_unknown():
    tolerance = classify_channel_tolerance(
        "AXI_B",
        "a maximum stall of 32 cycles, but BVALID may be held low indefinitely under congestion")
    result = detect_stall_violation(tolerance, observed_max_stall_cycles=5)
    assert result.status == "UNKNOWN"


def test_stall_violation_invalid_observed_value_raises():
    tolerance = classify_channel_tolerance("AXI_AW", "a maximum stall of 16 cycles")
    with pytest.raises(BackpressureModelError):
        detect_stall_violation(tolerance, observed_max_stall_cycles="not a number")


def test_stall_violation_bool_observed_value_raises():
    tolerance = classify_channel_tolerance("AXI_AW", "a maximum stall of 16 cycles")
    with pytest.raises(BackpressureModelError):
        detect_stall_violation(tolerance, observed_max_stall_cycles=True)


# ---------------------------------------------------------------------------
# CLI (real subprocess)
# ---------------------------------------------------------------------------

def test_cli_json_output(tmp_path):
    evidence_file = tmp_path / "evidence.json"
    evidence_file.write_text(json.dumps({
        "AXI_AW": "a maximum stall of 16 cycles",
        "AXI_R": "RVALID may stall indefinitely",
    }), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.backpressure_model",
         "--evidence-file", str(evidence_file), "--json"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["AXI_AW"]["tolerance_class"] == "BOUNDED"
    assert out["AXI_AW"]["max_stall_cycles"] == 16
    assert out["AXI_R"]["tolerance_class"] == "UNBOUNDED"
    assert out["APB_PREADY"]["status"] == "NOT_AVAILABLE"


def test_cli_with_observed_stalls_reports_violation(tmp_path):
    evidence_file = tmp_path / "evidence.json"
    evidence_file.write_text(json.dumps({"AXI_AW": "a maximum stall of 16 cycles"}), encoding="utf-8")
    observed_file = tmp_path / "observed.json"
    observed_file.write_text(json.dumps({"AXI_AW": 20}), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.backpressure_model",
         "--evidence-file", str(evidence_file),
         "--observed-stalls-file", str(observed_file), "--json"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["stall_violations"]["AXI_AW"]["status"] == "VIOLATION"


def test_cli_default_text_output(tmp_path):
    evidence_file = tmp_path / "evidence.json"
    evidence_file.write_text(json.dumps({"AXI_AW": "a maximum stall of 16 cycles"}), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.backpressure_model",
         "--evidence-file", str(evidence_file)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "AXI_AW" in proc.stdout
    assert "BOUNDED" in proc.stdout
