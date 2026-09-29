"""Tests for dv_harness/potential_spec_gap_detector.py.

Every positive test proves a specific structural-absence pattern is DETECTED from real keyword
evidence in synthetic requirement text; every negative control proves a specific way the detector
must NOT fire (a matching counterpart present under the same subject, a single requirement that
already states both halves, an empty/unusable input, unrelated subjects that must not be
manufactured into a false pairing). No mocks: this module has no external dependency to mock, and
the tests drive its real public functions and its real `python -m` CLI subprocess.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness.potential_spec_gap_detector import (
    GAP_MISSING_DISABLE,
    GAP_MISSING_ERROR_CONDITION,
    GAP_MISSING_ERROR_RECOVERY,
    GAP_MISSING_INFLIGHT_RESET_BEHAVIOR,
    GAP_MISSING_INTERRUPT_CLEAR,
    GAPS_DETECTED,
    NOT_AVAILABLE,
    NO_GAPS_DETECTED,
    POTENTIAL_SPEC_GAP,
    SpecGapFinding,
    detect_spec_gaps,
    render_report_text,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _find(report, gap_type):
    return [f for f in report.findings if f.gap_type == gap_type]


# --- Pattern 1: normal condition defined, no error condition -----------------------------------

def test_normal_condition_with_no_error_condition_is_flagged():
    requirements = [
        {
            "id": "REQ-1",
            "subject": "dma channel 0 transfer",
            "text": "When the DMA channel 0 transfer completes successfully, the completion "
                    "status bit shall be set in the status register.",
        },
    ]
    report = detect_spec_gaps(requirements)
    assert report.status == GAPS_DETECTED
    hits = _find(report, GAP_MISSING_ERROR_CONDITION)
    assert len(hits) == 1
    finding = hits[0]
    assert finding.status == POTENTIAL_SPEC_GAP
    assert finding.requirement_id == "REQ-1"
    assert finding.missing_counterpart == "ERROR_CONDITION"
    assert any(k in ("success", "successfully", "completes", "completion") for k in finding.matched_keywords)


def test_normal_condition_paired_with_real_error_condition_same_subject_is_not_flagged():
    requirements = [
        {
            "id": "REQ-1",
            "subject": "dma channel 0 transfer",
            "text": "When the DMA channel 0 transfer completes successfully, the completion "
                    "status bit shall be set.",
        },
        {
            "id": "REQ-2",
            "subject": "dma channel 0 transfer",
            "text": "When the DMA channel 0 transfer completes with an error, the error status "
                    "bit shall be set and the error code latched.",
        },
    ]
    report = detect_spec_gaps(requirements)
    # REQ-2's own error condition still has no recovery path of its own (a separate, correctly
    # detected gap) -- what this test proves is narrower: the NORMAL/ERROR pairing itself is
    # satisfied, so GAP_MISSING_ERROR_CONDITION specifically must not fire.
    assert _find(report, GAP_MISSING_ERROR_CONDITION) == []


# --- Pattern 2: enable defined, no disable -----------------------------------------------------

def test_enable_with_no_disable_is_flagged():
    requirements = [
        {
            "id": "REQ-3",
            "subject": "uart_tx",
            "text": "The UART_TX_ENABLE bit shall enable transmission when set to 1.",
        },
    ]
    report = detect_spec_gaps(requirements)
    hits = _find(report, GAP_MISSING_DISABLE)
    assert len(hits) == 1
    assert hits[0].missing_counterpart == "DISABLE"
    assert "enable" in hits[0].matched_keywords


def test_enable_and_disable_same_subject_is_not_flagged():
    requirements = [
        {"id": "REQ-3", "subject": "DMA channel 0", "text": "The DMA channel 0 enable bit shall enable channel operation when set."},
        {"id": "REQ-4", "subject": "DMA channel 0", "text": "The DMA channel 0 disable bit shall disable channel operation when cleared."},
    ]
    report = detect_spec_gaps(requirements)
    assert report.status == NO_GAPS_DETECTED
    assert _find(report, GAP_MISSING_DISABLE) == []


def test_enable_and_disable_on_unrelated_subjects_is_still_flagged():
    requirements = [
        {"id": "REQ-A", "subject": "uart_tx_enable", "text": "The UART TX enable bit shall enable transmission."},
        {"id": "REQ-B", "subject": "spi_rx_disable", "text": "The SPI RX disable bit shall disable reception."},
    ]
    report = detect_spec_gaps(requirements)
    hits = _find(report, GAP_MISSING_DISABLE)
    assert len(hits) == 1
    assert hits[0].requirement_id == "REQ-A"


# --- Pattern 3: interrupt-assert defined, no interrupt-clear -----------------------------------

def test_interrupt_assert_with_no_clear_is_flagged():
    requirements = [
        {
            "id": "REQ-5",
            "subject": "rx fifo full interrupt",
            "text": "The RX FIFO full condition shall assert the rx_full interrupt to the CPU.",
        },
    ]
    report = detect_spec_gaps(requirements)
    hits = _find(report, GAP_MISSING_INTERRUPT_CLEAR)
    assert len(hits) == 1
    assert hits[0].missing_counterpart == "INTERRUPT_CLEAR"
    assert "interrupt" in hits[0].matched_keywords
    assert "assert" in hits[0].matched_keywords


def test_interrupt_assert_and_clear_same_subject_is_not_flagged():
    requirements = [
        {"id": "REQ-5", "subject": "rx fifo full interrupt", "text": "The RX FIFO full condition shall assert the rx_full interrupt to the CPU."},
        {"id": "REQ-6", "subject": "rx fifo full interrupt", "text": "Writing 1 to INTR_CLR shall clear the rx_full interrupt."},
    ]
    report = detect_spec_gaps(requirements)
    assert _find(report, GAP_MISSING_INTERRUPT_CLEAR) == []


# --- Pattern 4: reset defined, no in-flight-operation behavior ---------------------------------

def test_reset_with_no_inflight_behavior_is_flagged():
    requirements = [
        {
            "id": "REQ-7",
            "subject": "dma soft reset",
            "text": "A soft reset shall reinitialize the DMA controller registers to their "
                    "default values.",
        },
    ]
    report = detect_spec_gaps(requirements)
    hits = _find(report, GAP_MISSING_INFLIGHT_RESET_BEHAVIOR)
    assert len(hits) == 1
    assert hits[0].missing_counterpart == "INFLIGHT_OPERATION_BEHAVIOR"
    assert "reset" in hits[0].matched_keywords


def test_reset_self_satisfying_inflight_behavior_in_same_requirement_is_not_flagged():
    requirements = [
        {
            "id": "REQ-7",
            "subject": "dma soft reset",
            "text": "A soft reset asserted while a DMA transfer is already in progress shall "
                    "abort the transfer and reinitialize registers to their default values.",
        },
    ]
    report = detect_spec_gaps(requirements)
    assert _find(report, GAP_MISSING_INFLIGHT_RESET_BEHAVIOR) == []


def test_reset_and_separate_inflight_requirement_same_subject_is_not_flagged():
    requirements = [
        {"id": "REQ-7", "subject": "dma soft reset", "text": "A soft reset shall reinitialize the DMA controller registers to their default values."},
        {"id": "REQ-8", "subject": "dma soft reset", "text": "If a soft reset occurs while a DMA transfer is outstanding, the transfer shall be aborted."},
    ]
    report = detect_spec_gaps(requirements)
    assert _find(report, GAP_MISSING_INFLIGHT_RESET_BEHAVIOR) == []


# --- Pattern 5: error condition defined, no recovery path --------------------------------------

def test_error_condition_with_no_recovery_is_flagged():
    requirements = [
        {
            "id": "REQ-9",
            "subject": "spi crc error",
            "text": "A CRC error on the SPI link shall set the crc_err status bit.",
        },
    ]
    report = detect_spec_gaps(requirements)
    hits = _find(report, GAP_MISSING_ERROR_RECOVERY)
    assert len(hits) == 1
    assert hits[0].missing_counterpart == "ERROR_RECOVERY"
    assert "error" in hits[0].matched_keywords


def test_error_condition_and_recovery_same_subject_is_not_flagged():
    requirements = [
        {"id": "REQ-9", "subject": "spi crc error", "text": "A CRC error on the SPI link shall set the crc_err status bit."},
        {"id": "REQ-10", "subject": "spi crc error", "text": "Software shall retry the SPI transaction to recover from a CRC error."},
    ]
    report = detect_spec_gaps(requirements)
    assert _find(report, GAP_MISSING_ERROR_RECOVERY) == []


# --- Negative controls: absence / usage boundaries ----------------------------------------------

def test_empty_requirement_list_is_not_available():
    report = detect_spec_gaps([])
    assert report.status == NOT_AVAILABLE
    assert report.requirements_analyzed == 0
    assert report.findings == ()


def test_none_requirements_is_not_available():
    report = detect_spec_gaps(None)
    assert report.status == NOT_AVAILABLE


def test_requirements_with_no_usable_text_are_skipped_and_report_not_available():
    requirements = [
        {"id": "REQ-11"},  # no text field at all
        {"id": "REQ-12", "text": "   "},  # blank text
        {"id": "REQ-13", "unrelated_field": "not a recognized text alias"},
    ]
    report = detect_spec_gaps(requirements)
    assert report.status == NOT_AVAILABLE
    assert report.requirements_analyzed == 0
    assert set(report.requirements_skipped_no_text) == {"REQ-11", "REQ-12", "REQ-13"}


def test_mixed_skipped_and_real_requirement_still_analyzes_the_real_one():
    requirements = [
        {"id": "REQ-14"},
        {"id": "REQ-15", "subject": "usb reset", "text": "A USB bus reset shall reinitialize the endpoint state machine."},
    ]
    report = detect_spec_gaps(requirements)
    assert report.requirements_skipped_no_text == ("REQ-14",)
    assert report.requirements_analyzed == 1
    assert report.status == GAPS_DETECTED
    assert _find(report, GAP_MISSING_INFLIGHT_RESET_BEHAVIOR)[0].requirement_id == "REQ-15"


def test_no_gaps_when_no_classifiable_content_present():
    requirements = [
        {"id": "REQ-16", "text": "The register map base address shall be 0xB000_0000."},
    ]
    report = detect_spec_gaps(requirements)
    assert report.status == NO_GAPS_DETECTED
    assert report.findings == ()


def test_fallback_derived_subject_without_explicit_subject_field_still_pairs():
    requirements = [
        {"id": "REQ-17", "text": "When the DMA channel 0 transfer completes successfully, the completion status bit shall be set."},
        {"id": "REQ-18", "text": "When the DMA channel 0 transfer completes with an error, the error status bit shall be set and the error code latched."},
    ]
    report = detect_spec_gaps(requirements)
    assert _find(report, GAP_MISSING_ERROR_CONDITION) == []


def test_finding_status_is_structurally_pinned_to_potential_spec_gap():
    with pytest.raises(ValueError):
        SpecGapFinding(
            status="APPROVED",
            gap_type=GAP_MISSING_DISABLE,
            requirement_id="REQ-X",
            requirement_text="text",
            matched_keywords=("enable",),
            missing_counterpart="DISABLE",
            subject_display="x",
            reason="reason",
        )


def test_finding_rejects_unrecognized_gap_type():
    with pytest.raises(ValueError):
        SpecGapFinding(
            status=POTENTIAL_SPEC_GAP,
            gap_type="NOT_A_REAL_GAP_TYPE",
            requirement_id="REQ-X",
            requirement_text="text",
            matched_keywords=("enable",),
            missing_counterpart="DISABLE",
            subject_display="x",
            reason="reason",
        )


def test_render_report_text_includes_gap_type_and_evidence():
    requirements = [
        {"id": "REQ-1", "subject": "dma channel 0", "text": "When the DMA channel 0 transfer completes successfully, the status bit shall be set."},
    ]
    report = detect_spec_gaps(requirements)
    text = render_report_text(report)
    assert "MISSING_ERROR_CONDITION" in text
    assert "REQ-1" in text
    assert "evidence:" in text


def test_report_to_dict_and_finding_to_dict_are_json_serializable():
    requirements = [
        {"id": "REQ-1", "subject": "dma channel 0", "text": "When the DMA channel 0 transfer completes successfully, the status bit shall be set."},
    ]
    report = detect_spec_gaps(requirements)
    payload = json.dumps(report.to_dict())
    assert "POTENTIAL_SPEC_GAP" in payload


# --- CLI (python -m) subprocess tests -----------------------------------------------------------

def _run_cli(args):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.potential_spec_gap_detector", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )


def test_cli_no_args_usage_exit_2():
    result = _run_cli([])
    assert result.returncode == 2
    assert "usage:" in result.stdout


def test_cli_missing_file_exit_2():
    result = _run_cli(["does_not_exist_12345.json"])
    assert result.returncode == 2


def test_cli_gaps_detected_exit_1_and_no_gaps_exit_0(tmp_path):
    gap_file = tmp_path / "gap_requirements.json"
    gap_file.write_text(json.dumps([
        {"id": "REQ-1", "subject": "dma channel 0", "text": "When the DMA channel 0 transfer completes successfully, the status bit shall be set."},
    ]), encoding="utf-8")
    result = _run_cli([str(gap_file), "--json"])
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "GAPS_DETECTED"
    assert payload["findings"][0]["status"] == "POTENTIAL_SPEC_GAP"

    clean_file = tmp_path / "clean_requirements.json"
    clean_file.write_text(json.dumps([
        {"id": "REQ-1", "text": "The register map base address shall be 0xB000_0000."},
    ]), encoding="utf-8")
    result = _run_cli([str(clean_file)])
    assert result.returncode == 0
    assert "NO_GAPS_DETECTED" in result.stdout


def test_cli_accepts_requirements_wrapper_object(tmp_path):
    wrapper_file = tmp_path / "wrapped.json"
    wrapper_file.write_text(json.dumps({
        "requirements": [
            {"id": "REQ-1", "subject": "dma channel 0", "text": "When the DMA channel 0 transfer completes successfully, the status bit shall be set."},
        ]
    }), encoding="utf-8")
    result = _run_cli([str(wrapper_file)])
    assert result.returncode == 1
