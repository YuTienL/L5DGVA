"""Tests for dv_harness.amba_performance_readiness_gates.

Synthetic condition-record fixtures only (no real simulator/waveform exists to draw from --
this harness has none). Covers: the positive path for both gates, worst-wins negative controls,
the hard functional-correctness-outranks-performance precedence, the explicit-only NOT_APPLICABLE
path, sub-gate derivation/override, malformed-input refusals, and the real CLI subprocess exit
codes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness.amba_performance_readiness_gates import (
    GATE_INCOMPLETE_EVIDENCE,
    GATE_NAMES,
    GATE_NOT_APPLICABLE,
    GATE_NOT_READY,
    GATE_READY,
    GATE_REQUIRED_CONDITIONS,
    AmbaPerformanceReadinessGatesError,
    evaluate_amba_performance_readiness_gates,
    evaluate_gate,
    render_readiness_report,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _cond(name: str, status: str, reason: str = None):
    record = {"condition_name": name, "status": status}
    if reason is not None:
        record["reason"] = reason
    return record


def _all_met_conditions():
    """A synthetic, fully-clean condition set covering every real condition name both gates
    declare (excluding the BUS_PERFORMANCE_READY sub-gate reference, which is derived)."""
    names = set()
    for gate_name in GATE_NAMES:
        names.update(GATE_REQUIRED_CONDITIONS[gate_name])
    names.discard("BUS_PERFORMANCE_READY")  # sub-gate reference, derived not supplied
    return [_cond(name, "MET") for name in sorted(names)]


# --------------------------------------------------------------------------
# Core positive path
# --------------------------------------------------------------------------


def test_both_gates_ready_when_every_condition_is_met():
    report = evaluate_amba_performance_readiness_gates(_all_met_conditions())
    assert report.verdict_for("BUS_PERFORMANCE_READY") == GATE_READY
    assert report.verdict_for("BUS_PERFORMANCE_SIGNOFF_READY") == GATE_READY
    assert report.worst_verdict() == GATE_READY


def test_signoff_gate_derives_bus_performance_ready_as_a_sub_gate():
    # No explicit BUS_PERFORMANCE_READY condition supplied -- it must be DERIVED from the
    # already-computed sub-gate verdict, not left NOT_SUPPLIED/UNKNOWN.
    report = evaluate_amba_performance_readiness_gates(_all_met_conditions())
    signoff = report.gates["BUS_PERFORMANCE_SIGNOFF_READY"]
    sub_gate_conditions = [c for c in signoff.conditions if c.condition_name == "BUS_PERFORMANCE_READY"]
    assert len(sub_gate_conditions) == 1
    sub = sub_gate_conditions[0]
    assert sub.is_sub_gate_reference is True
    assert sub.status == "MET"
    assert sub.source == "derived_from_sub_gate"


def test_explicit_sub_gate_condition_outranks_the_derived_one():
    # Real evidence outranks a derived value (Source Authority Order): even though
    # BUS_PERFORMANCE_READY would derive READY -> MET, an explicit caller-supplied UNMET record
    # for that exact condition name must win.
    conditions = _all_met_conditions() + [_cond("BUS_PERFORMANCE_READY", "UNMET", "human override")]
    report = evaluate_amba_performance_readiness_gates(conditions)
    signoff = report.gates["BUS_PERFORMANCE_SIGNOFF_READY"]
    assert signoff.verdict == GATE_NOT_READY
    assert "BUS_PERFORMANCE_READY" in signoff.blocking_conditions


# --------------------------------------------------------------------------
# Worst-wins negative controls
# --------------------------------------------------------------------------


def test_single_unmet_condition_blocks_the_whole_gate_regardless_of_others():
    conditions = _all_met_conditions()
    for i, cond in enumerate(conditions):
        if cond["condition_name"] == "Measurement_Methodology_Defined":
            conditions[i] = _cond("Measurement_Methodology_Defined", "UNMET", "no methodology on file")
            break
    report = evaluate_amba_performance_readiness_gates(conditions)
    ready = report.gates["BUS_PERFORMANCE_READY"]
    assert ready.verdict == GATE_NOT_READY
    assert ready.blocking_conditions == ["Measurement_Methodology_Defined"]
    # Every other condition on that gate stayed clean -- confirms this is NOT an average.
    other_statuses = {c.condition_name: c.status for c in ready.conditions}
    assert other_statuses["Performance_Target_Declared"] == "MET"
    assert other_statuses["Baseline_Metric_Captured"] == "MET"


def test_unknown_condition_yields_incomplete_evidence_never_ready_never_not_ready():
    conditions = _all_met_conditions()
    for i, cond in enumerate(conditions):
        if cond["condition_name"] == "Baseline_Metric_Captured":
            conditions[i] = _cond("Baseline_Metric_Captured", "UNKNOWN", "waveform not captured")
            break
    report = evaluate_amba_performance_readiness_gates(conditions)
    ready = report.gates["BUS_PERFORMANCE_READY"]
    assert ready.verdict == GATE_INCOMPLETE_EVIDENCE
    assert ready.blocking_conditions == []
    assert "Baseline_Metric_Captured" in ready.incomplete_conditions


def test_not_available_condition_also_yields_incomplete_evidence():
    conditions = _all_met_conditions()
    for i, cond in enumerate(conditions):
        if cond["condition_name"] == "Performance_Target_Declared":
            conditions[i] = _cond("Performance_Target_Declared", "NOT_AVAILABLE", "no target file")
            break
    report = evaluate_amba_performance_readiness_gates(conditions)
    assert report.gates["BUS_PERFORMANCE_READY"].verdict == GATE_INCOMPLETE_EVIDENCE


def test_a_condition_never_supplied_at_all_is_incomplete_evidence_not_silently_ready():
    # Only supply conditions for BUS_PERFORMANCE_READY's terms, leaving every
    # BUS_PERFORMANCE_SIGNOFF_READY-only condition unsupplied.
    conditions = [_cond(name, "MET") for name in GATE_REQUIRED_CONDITIONS["BUS_PERFORMANCE_READY"]]
    report = evaluate_amba_performance_readiness_gates(conditions)
    signoff = report.gates["BUS_PERFORMANCE_SIGNOFF_READY"]
    assert signoff.verdict == GATE_INCOMPLETE_EVIDENCE
    assert "Performance_Regression_Comparison_Complete" in signoff.incomplete_conditions
    assert "Performance_Requirement_Evaluation_Complete" in signoff.incomplete_conditions
    not_supplied = [c for c in signoff.conditions if c.condition_name == "Performance_Regression_Comparison_Complete"]
    assert not_supplied[0].source == "not_supplied"
    assert not_supplied[0].status == "UNKNOWN"


def test_unmet_outranks_unknown_on_the_same_gate():
    conditions = _all_met_conditions()
    updated = []
    for cond in conditions:
        if cond["condition_name"] == "Baseline_Metric_Captured":
            updated.append(_cond("Baseline_Metric_Captured", "UNKNOWN"))
        elif cond["condition_name"] == "Measurement_Methodology_Defined":
            updated.append(_cond("Measurement_Methodology_Defined", "UNMET"))
        else:
            updated.append(cond)
    report = evaluate_amba_performance_readiness_gates(updated)
    ready = report.gates["BUS_PERFORMANCE_READY"]
    assert ready.verdict == GATE_NOT_READY  # UNMET beats UNKNOWN, never averaged together
    assert ready.blocking_conditions == ["Measurement_Methodology_Defined"]


# --------------------------------------------------------------------------
# Functional correctness always outranks performance PASS (rule c) -- the headline test.
# --------------------------------------------------------------------------


def test_functional_correctness_outranks_a_high_performance_pass():
    # Every performance-specific condition reads MET (a "high-performance" transaction), but
    # functional correctness is UNMET -- this must still be an overall FAIL (NOT_READY), a hard
    # precedence, never a weighted score a strong performance result could outweigh.
    conditions = [
        _cond("Functional_Correctness_Confirmed", "UNMET", "scoreboard mismatch on this transaction"),
        _cond("Performance_Target_Declared", "MET"),
        _cond("Baseline_Metric_Captured", "MET"),
        _cond("Measurement_Methodology_Defined", "MET"),
        _cond("Critical_UNKNOWN", "MET"),
    ]
    report = evaluate_amba_performance_readiness_gates(conditions)
    ready = report.gates["BUS_PERFORMANCE_READY"]
    assert ready.verdict == GATE_NOT_READY
    assert "Functional_Correctness_Confirmed" in ready.blocking_conditions
    # And the signoff gate, referencing the now-NOT_READY sub-gate, is blocked too.
    assert report.gates["BUS_PERFORMANCE_SIGNOFF_READY"].verdict == GATE_NOT_READY


def test_functional_correctness_unmet_at_signoff_blocks_even_if_readiness_gate_was_ready():
    conditions = _all_met_conditions()
    updated = [
        c if c["condition_name"] != "Functional_Correctness_Confirmed" else _cond(
            "Functional_Correctness_Confirmed", "UNMET", "a later regression run found a scoreboard mismatch"
        )
        for c in conditions
    ]
    # Both gates share the same condition name; this single UNMET record blocks both.
    report = evaluate_amba_performance_readiness_gates(updated)
    assert report.gates["BUS_PERFORMANCE_READY"].verdict == GATE_NOT_READY
    assert report.gates["BUS_PERFORMANCE_SIGNOFF_READY"].verdict == GATE_NOT_READY


# --------------------------------------------------------------------------
# NOT_APPLICABLE: explicit-only, never inferred.
# --------------------------------------------------------------------------


def test_not_applicable_is_never_inferred_from_an_empty_condition_list():
    # An empty condition list must NOT read as NOT_APPLICABLE -- absence of evidence is
    # INCOMPLETE_EVIDENCE, never a silently-assumed "this project has nothing to measure".
    report = evaluate_amba_performance_readiness_gates([])
    assert report.gates["BUS_PERFORMANCE_READY"].verdict == GATE_INCOMPLETE_EVIDENCE
    assert report.gates["BUS_PERFORMANCE_READY"].verdict != GATE_NOT_APPLICABLE


def test_explicit_not_applicable_declaration_short_circuits_the_gate():
    declarations = {
        "BUS_PERFORMANCE_READY": {
            "not_applicable": True,
            "reason": "this project has no performance-critical path (declared by the project owner)",
        }
    }
    report = evaluate_amba_performance_readiness_gates([], not_applicable_declarations=declarations)
    ready = report.gates["BUS_PERFORMANCE_READY"]
    assert ready.verdict == GATE_NOT_APPLICABLE
    assert "performance-critical" in ready.not_applicable_reason
    assert ready.conditions == []  # no condition was evaluated at all


def test_not_applicable_sub_gate_folds_as_met_never_as_a_block():
    # A NOT_APPLICABLE BUS_PERFORMANCE_READY must not block BUS_PERFORMANCE_SIGNOFF_READY --
    # "not performance-critical" is not the same fact as "unproven" or "failed".
    declarations = {
        "BUS_PERFORMANCE_READY": {"not_applicable": True, "reason": "no performance-critical path"}
    }
    conditions = [
        _cond("Functional_Correctness_Confirmed", "MET"),
        _cond("Performance_Regression_Comparison_Complete", "MET"),
        _cond("Performance_Requirement_Evaluation_Complete", "MET"),
        _cond("Critical_UNKNOWN", "MET"),
    ]
    report = evaluate_amba_performance_readiness_gates(
        conditions, not_applicable_declarations=declarations
    )
    assert report.gates["BUS_PERFORMANCE_READY"].verdict == GATE_NOT_APPLICABLE
    assert report.gates["BUS_PERFORMANCE_SIGNOFF_READY"].verdict == GATE_READY
    assert report.worst_verdict() == GATE_READY


def test_not_applicable_declaration_without_a_reason_is_refused():
    with pytest.raises(AmbaPerformanceReadinessGatesError):
        evaluate_gate("BUS_PERFORMANCE_READY", [], not_applicable_declaration={"not_applicable": True})


def test_not_applicable_declaration_with_blank_reason_is_refused():
    with pytest.raises(AmbaPerformanceReadinessGatesError):
        evaluate_gate(
            "BUS_PERFORMANCE_READY", [], not_applicable_declaration={"not_applicable": True, "reason": "   "}
        )


def test_not_applicable_false_is_a_no_op_normal_evaluation_proceeds():
    report_conditions = _all_met_conditions()
    conditions_for_ready = [
        c for c in report_conditions if c["condition_name"] in GATE_REQUIRED_CONDITIONS["BUS_PERFORMANCE_READY"]
    ]
    evaluation = evaluate_gate(
        "BUS_PERFORMANCE_READY",
        conditions_for_ready,
        not_applicable_declaration={"not_applicable": False},
    )
    assert evaluation.verdict == GATE_READY


def test_not_applicable_declaration_must_be_a_real_bool_not_a_truthy_string():
    with pytest.raises(AmbaPerformanceReadinessGatesError):
        evaluate_gate(
            "BUS_PERFORMANCE_READY",
            [],
            not_applicable_declaration={"not_applicable": "true", "reason": "typed string, not a bool"},
        )


# --------------------------------------------------------------------------
# Malformed-input refusals
# --------------------------------------------------------------------------


def test_unrecognized_status_is_refused():
    with pytest.raises(AmbaPerformanceReadinessGatesError):
        evaluate_gate(
            "BUS_PERFORMANCE_READY", [_cond("Functional_Correctness_Confirmed", "PASS")]
        )


def test_duplicate_condition_name_is_refused():
    with pytest.raises(AmbaPerformanceReadinessGatesError):
        evaluate_amba_performance_readiness_gates(
            [
                _cond("Functional_Correctness_Confirmed", "MET"),
                _cond("Functional_Correctness_Confirmed", "UNMET"),
            ]
        )


def test_condition_record_missing_a_name_is_refused():
    with pytest.raises(AmbaPerformanceReadinessGatesError):
        evaluate_gate("BUS_PERFORMANCE_READY", [{"status": "MET"}])


def test_conditions_must_be_a_sequence_not_a_bare_dict():
    with pytest.raises(AmbaPerformanceReadinessGatesError):
        evaluate_amba_performance_readiness_gates({"Functional_Correctness_Confirmed": "MET"})


def test_unknown_gate_name_is_refused():
    with pytest.raises(AmbaPerformanceReadinessGatesError):
        evaluate_gate("NOT_A_REAL_GATE", [])


def test_non_string_reason_is_refused():
    with pytest.raises(AmbaPerformanceReadinessGatesError):
        evaluate_gate(
            "BUS_PERFORMANCE_READY",
            [{"condition_name": "Functional_Correctness_Confirmed", "status": "MET", "reason": 123}],
        )


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def test_render_readiness_report_contains_both_gate_names_and_worst_verdict():
    report = evaluate_amba_performance_readiness_gates(_all_met_conditions())
    text = render_readiness_report(report)
    for gate_name in GATE_NAMES:
        assert gate_name in text
    assert "Worst verdict across both gates" in text


def test_render_readiness_report_shows_not_applicable_reason():
    declarations = {"BUS_PERFORMANCE_READY": {"not_applicable": True, "reason": "no perf-critical path"}}
    report = evaluate_amba_performance_readiness_gates([], not_applicable_declarations=declarations)
    text = render_readiness_report(report)
    assert "NOT_APPLICABLE: no perf-critical path" in text


# --------------------------------------------------------------------------
# Real CLI subprocess
# --------------------------------------------------------------------------


def _run_cli(args, cwd=REPO_ROOT):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.amba_performance_readiness_gates"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_cli_gates_verb_lists_both_gate_names():
    result = _run_cli(["gates", "--json"])
    assert result.returncode == 0
    names = json.loads(result.stdout)
    assert set(names) == set(GATE_NAMES)


def test_cli_conditions_verb_lists_required_conditions_for_a_gate():
    result = _run_cli(["conditions", "--gate", "BUS_PERFORMANCE_READY", "--json"])
    assert result.returncode == 0
    conditions = json.loads(result.stdout)
    assert "Functional_Correctness_Confirmed" in conditions


def test_cli_evaluate_exits_zero_when_all_ready(tmp_path):
    conditions_file = tmp_path / "conditions.json"
    conditions_file.write_text(json.dumps(_all_met_conditions()), encoding="utf-8")
    result = _run_cli(["evaluate", "--conditions", str(conditions_file), "--json"])
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["BUS_PERFORMANCE_READY"]["verdict"] == GATE_READY


def test_cli_evaluate_exits_one_when_not_ready(tmp_path):
    conditions_file = tmp_path / "conditions.json"
    conditions_file.write_text(
        json.dumps([_cond("Functional_Correctness_Confirmed", "UNMET", "real scoreboard mismatch")]),
        encoding="utf-8",
    )
    result = _run_cli(["evaluate", "--conditions", str(conditions_file)])
    assert result.returncode == 1


def test_cli_evaluate_exits_two_on_unreadable_conditions_file():
    result = _run_cli(["evaluate", "--conditions", "/does/not/exist.json"])
    assert result.returncode == 2


def test_cli_evaluate_with_not_applicable_file_exits_zero(tmp_path):
    conditions_file = tmp_path / "conditions.json"
    conditions_file.write_text(json.dumps([]), encoding="utf-8")
    not_applicable_file = tmp_path / "not_applicable.json"
    not_applicable_file.write_text(
        json.dumps(
            {
                "BUS_PERFORMANCE_READY": {"not_applicable": True, "reason": "no perf-critical path"},
                "BUS_PERFORMANCE_SIGNOFF_READY": {"not_applicable": True, "reason": "no perf-critical path"},
            }
        ),
        encoding="utf-8",
    )
    result = _run_cli(
        [
            "evaluate",
            "--conditions",
            str(conditions_file),
            "--not-applicable",
            str(not_applicable_file),
            "--json",
        ]
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["BUS_PERFORMANCE_READY"]["verdict"] == GATE_NOT_APPLICABLE
    assert payload["BUS_PERFORMANCE_SIGNOFF_READY"]["verdict"] == GATE_NOT_APPLICABLE
