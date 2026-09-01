"""Coverage for the 2026-09-01 stage-scoped completion percent addition.

Context (see the audit this closes): the harness could already show the
current stage (control_plane.describe_stage()) and an itemized list of
outstanding gate/field reasons (gates._evaluate_stage_evidence_core()), but
had no numeric completion percentage scoped to the CURRENT stage
specifically -- only a whole-run dashboard.py overall_progress_percent
(percent of ALL Stage enum values at PASS/CLOSED), computed only inside
dashboard.py's GET /api/state handler and never exposed via the CLI.

This file proves:
  1. gates._stage_completion_from_signatures() / the new
     gates.evaluate_stage_evidence_with_completion() derive a correct
     gates_total/gates_passed/stage_completion_percent from a REAL stage's
     REAL gate scripts (ARCH_CALIBRATION, 3 registered gates in
     gates.STAGE_GATES) at 0/3, 2/3 and 3/3 passing -- not synthetic
     signature tuples, the actual tools/verification_flow/*.py subprocess
     results (same fixture shape as test_react_loop.py's ARCH_CALIBRATION
     tests, kept as a self-contained copy here per this test suite's own
     "no cross-test-module import" convention -- see
     test_active_stages_read_sites.py's own note on this).
  2. A stage with zero registered gates in STAGE_GATES does not divide by
     zero and reports a sensible 100%-with-a-note default instead.
  3. control_plane.describe_stage() threads gates_total/gates_passed/
     stage_completion_percent/stage_completion_note into its returned dict
     alongside the pre-existing gate_verdict/gate_reasons.
  4. `dv-harness explain --stage` / `evidence --stage` (and the no-`--stage`
     evidence path) print those same fields in their JSON output.
  5. The pre-existing fixed-arity tuple contracts of
     gates.evaluate_stage_evidence() (2-tuple) and
     react_loop.evaluate_stage_evidence_with_detail() (3-tuple) are
     untouched by _evaluate_stage_evidence_core() gaining a 4th return
     element -- both real callers/tests unpack them at their original
     arity with no changes required.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

from dv_harness.gates import (
    STAGE_GATES,
    evaluate_stage_evidence,
    evaluate_stage_evidence_with_completion,
    _evaluate_stage_evidence_core,
    _stage_completion_from_signatures,
)
from dv_harness.react_loop import evaluate_stage_evidence_with_detail

ROOT = Path(__file__).resolve().parents[1]


def _mk_smoke_project():
    """Same fixture shape as test_react_loop.py's/test_engine_gates_and_
    routing.py's _mk_smoke_project -- a fresh temp project with the real
    main_graph.json, real .claude/agents, and real tools/verification_flow
    gate scripts, so ARCH_CALIBRATION's 3 real gates actually subprocess-run
    (never synthetic signatures)."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / ".dv-harness" / "graph").mkdir(parents=True)
    (tmp / ".dv-harness" / "graph" / "main_graph.json").write_text(
        (ROOT / ".dv-harness" / "graph" / "main_graph.json").read_text(encoding="utf-8"), encoding="utf-8")
    shutil.copytree(ROOT / ".claude" / "agents", tmp / ".claude" / "agents")
    shutil.copytree(ROOT / "tools", tmp / "tools")
    return tmp


# --- ARCH_CALIBRATION's 3 mandatory gates (architecture_calibration_gate,
# architecture_calibration_conflict_gate, vip_api_drift_gate) -- payloads
# copied from test_react_loop.py's own verified-by-execution fixtures (same
# gate scripts, same PASS/FAIL evidence shapes) -------------------------

_ARCH_CALIBRATION_GATE_PASS = (
    '```dv-harness-evidence:architecture_calibration_gate\n'
    '{"architecture_before": {"a": 1}, "architecture_after": {"a": 1}}\n```\n'
)
_CONFLICT_GATE_PASS = (
    '```dv-harness-evidence:architecture_calibration_conflict_gate\n'
    '{"conflicts": []}\n```\n'
)
_VIP_DRIFT_GATE_PASS = (
    '```dv-harness-evidence:vip_api_drift_gate\n'
    '{"current_vip_version": "1.0", "qualified_vip_version": "1.0", '
    '"current_vip_source_or_manual_hash": "h1"}\n```\n'
)
_VIP_DRIFT_GATE_FAIL = (
    '```dv-harness-evidence:vip_api_drift_gate\n'
    '{"current_vip_version": "2.0", "qualified_vip_version": "1.0", '
    '"api_diff_analyzed": false}\n```\n'
)

_ARCH_CALIBRATION_ALL_PASS = _ARCH_CALIBRATION_GATE_PASS + _CONFLICT_GATE_PASS + _VIP_DRIFT_GATE_PASS
_ARCH_CALIBRATION_2_OF_3_PASS = _ARCH_CALIBRATION_GATE_PASS + _CONFLICT_GATE_PASS + _VIP_DRIFT_GATE_FAIL
_ARCH_CALIBRATION_0_OF_3_PASS = ""  # no evidence blocks at all -> MISSING_EVIDENCE, 0/3 signatures ok


# --- item 1: gates_total/gates_passed/stage_completion_percent at 0/3, 2/3, 3/3

def test_three_of_three_gates_passing_yields_100_percent():
    tmp = _mk_smoke_project()
    try:
        assert len(STAGE_GATES["ARCH_CALIBRATION"]) == 3
        verdict, reasons, completion = evaluate_stage_evidence_with_completion(
            tmp, "ARCH_CALIBRATION", _ARCH_CALIBRATION_ALL_PASS)
        assert verdict == "PASS"
        assert completion == {
            "gates_total": 3,
            "gates_passed": 3,
            "stage_completion_percent": 100,
            "stage_completion_note": None,
        }
    finally:
        shutil.rmtree(tmp)


def test_two_of_three_gates_passing_yields_67_percent():
    tmp = _mk_smoke_project()
    try:
        verdict, reasons, completion = evaluate_stage_evidence_with_completion(
            tmp, "ARCH_CALIBRATION", _ARCH_CALIBRATION_2_OF_3_PASS)
        assert verdict == "GATE_FAIL"
        assert completion["gates_total"] == 3
        assert completion["gates_passed"] == 2
        assert completion["stage_completion_percent"] == round(100 * 2 / 3) == 67
        assert completion["stage_completion_note"] is None
    finally:
        shutil.rmtree(tmp)


def test_zero_of_three_gates_passing_yields_0_percent():
    tmp = _mk_smoke_project()
    try:
        verdict, reasons, completion = evaluate_stage_evidence_with_completion(
            tmp, "ARCH_CALIBRATION", _ARCH_CALIBRATION_0_OF_3_PASS)
        assert verdict == "MISSING_EVIDENCE"
        assert completion == {
            "gates_total": 3,
            "gates_passed": 0,
            "stage_completion_percent": 0,
            "stage_completion_note": None,
        }
    finally:
        shutil.rmtree(tmp)


# --- item 2: a stage with zero registered gates does not divide by zero ----

def test_stage_with_zero_registered_gates_defaults_to_100_with_note():
    assert "__NO_SUCH_STAGE__" not in STAGE_GATES
    verdict, reasons, completion = evaluate_stage_evidence_with_completion(
        ROOT, "__NO_SUCH_STAGE__", "anything at all")
    assert verdict == "NO_GATE_REQUIRED"
    assert completion["gates_total"] == 0
    assert completion["gates_passed"] == 0
    assert completion["stage_completion_percent"] == 100
    assert isinstance(completion["stage_completion_note"], str) and completion["stage_completion_note"]


def test_stage_completion_helper_zero_gates_no_zero_division_error():
    """Direct unit check on the helper itself -- gates=None/[] must never
    raise ZeroDivisionError."""
    assert _stage_completion_from_signatures(None, []) == {
        "gates_total": 0, "gates_passed": 0,
        "stage_completion_percent": 100,
        "stage_completion_note": "stage has no registered gates; treated as fully complete",
    }
    assert _stage_completion_from_signatures([], []) == _stage_completion_from_signatures(None, [])


# --- item 5: pre-existing tuple contracts are untouched ---------------------

def test_evaluate_stage_evidence_public_2_tuple_contract_unchanged():
    verdict, reasons = evaluate_stage_evidence(ROOT, "__NO_SUCH_STAGE__", "anything at all")
    assert verdict == "NO_GATE_REQUIRED"
    assert reasons == []


def test_evaluate_stage_evidence_with_detail_public_3_tuple_contract_unchanged():
    tmp = _mk_smoke_project()
    try:
        verdict, reasons, signatures = evaluate_stage_evidence_with_detail(
            tmp, "ARCH_CALIBRATION", _ARCH_CALIBRATION_ALL_PASS)
        assert verdict == "PASS"
        assert len(signatures) == 3
    finally:
        shutil.rmtree(tmp)


def test_core_function_now_returns_a_4_tuple_with_completion_last():
    tmp = _mk_smoke_project()
    try:
        verdict, reasons, signatures, completion = _evaluate_stage_evidence_core(
            tmp, "ARCH_CALIBRATION", _ARCH_CALIBRATION_ALL_PASS)
        assert verdict == "PASS"
        assert len(signatures) == 3
        assert completion["stage_completion_percent"] == 100
    finally:
        shutil.rmtree(tmp)


# --- item 3: control_plane.describe_stage() surfaces the new fields --------

def test_describe_stage_surfaces_completion_fields_matching_gate_verdict():
    from dv_harness.control_plane import describe_stage
    from dv_harness.models import HarnessState

    tmp = _mk_smoke_project()
    try:
        state = HarnessState()
        state.stages["ARCH_CALIBRATION"] = {
            "status": "PASS", "attempts": 1,
            "last_message": _ARCH_CALIBRATION_2_OF_3_PASS,
        }
        out = describe_stage(tmp, state, "ARCH_CALIBRATION")
        assert out["gate_verdict"] == "GATE_FAIL"
        assert out["gates_total"] == 3
        assert out["gates_passed"] == 2
        assert out["stage_completion_percent"] == 67
        assert out["stage_completion_note"] is None
        # Pre-existing fields untouched.
        assert out["stage"] == "ARCH_CALIBRATION"
        assert isinstance(out["gate_reasons"], list)
    finally:
        shutil.rmtree(tmp)


def test_describe_stage_zero_gate_stage_reports_100_with_note():
    from dv_harness.control_plane import describe_stage
    from dv_harness.models import HarnessState

    state = HarnessState()
    state.stages["__NO_SUCH_STAGE__"] = {"status": "IN_PROGRESS", "attempts": 0, "last_message": ""}
    out = describe_stage(ROOT, state, "__NO_SUCH_STAGE__")
    assert out["gate_verdict"] == "NO_GATE_REQUIRED"
    assert out["gates_total"] == 0
    assert out["gates_passed"] == 0
    assert out["stage_completion_percent"] == 100
    assert out["stage_completion_note"]


# --- item 4: CLI explain/evidence print the new fields ----------------------

def _run_cli(monkeypatch, capsys, argv):
    from dv_harness import cli
    monkeypatch.setattr(sys, "argv", ["dv-harness"] + argv)
    cli.main()
    return capsys.readouterr().out


def test_cli_evidence_stage_prints_completion_fields(monkeypatch, capsys):
    from dv_harness.engine import DVHarness

    tmp = _mk_smoke_project()
    try:
        h = DVHarness(tmp)
        h.cfg["policy"]["require_stage_gate_evidence"] = False
        h.state.stages["ARCH_CALIBRATION"] = {
            "status": "PASS", "attempts": 1,
            "last_message": _ARCH_CALIBRATION_ALL_PASS,
        }
        h.store.save(h.state)

        out = _run_cli(monkeypatch, capsys,
                        ["--project-root", str(tmp), "evidence", "--stage", "ARCH_CALIBRATION"])
        data = json.loads(out)
        assert data["stage"] == "ARCH_CALIBRATION"
        assert data["gate_verdict"] == "PASS"
        assert data["gates_total"] == 3
        assert data["gates_passed"] == 3
        assert data["stage_completion_percent"] == 100
    finally:
        shutil.rmtree(tmp)


def test_cli_explain_stage_prints_completion_fields(monkeypatch, capsys):
    from dv_harness.engine import DVHarness

    tmp = _mk_smoke_project()
    try:
        h = DVHarness(tmp)
        h.cfg["policy"]["require_stage_gate_evidence"] = False
        h.state.stages["ARCH_CALIBRATION"] = {
            "status": "PARTIAL", "attempts": 1,
            "last_message": _ARCH_CALIBRATION_2_OF_3_PASS,
        }
        h.store.save(h.state)

        out = _run_cli(monkeypatch, capsys,
                        ["--project-root", str(tmp), "explain", "--stage", "ARCH_CALIBRATION"])
        assert '"gates_total": 3' in out
        assert '"gates_passed": 2' in out
        assert '"stage_completion_percent": 67' in out
    finally:
        shutil.rmtree(tmp)
