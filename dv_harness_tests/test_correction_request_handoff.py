"""Regression tests for `model_handoff_workflow.build_correction_request_
handoff()` -- the real producer for `AUTO_GENERATE_CORRECTION_REQUEST_
HANDOFF`, a named `NEXT_ACTION` in `execution_contract.NEXT_ACTION_TABLE`
that had no implementation anywhere in the codebase until a real Codex
RESULT_V1.md (M7-V1-CODEX-REVIEW-007) was quarantined with a real
`MALFORMED_ESCAPE` and exposed the gap live (P4 NO CAPABILITY ISLANDS)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import dv_harness.model_handoff_workflow as wf
from dv_harness.model_handoff import build_handoff, HandoffBuildError
from dv_harness.task_boundary_conformance import TaskBoundary

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git not on PATH")


def _run(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    w = tmp_path / "work"
    w.mkdir()
    _run(w, "init", "-q")
    _run(w, "config", "user.email", "t@example.com")
    _run(w, "config", "user.name", "T")
    (w / "dv_harness").mkdir()
    (w / "dv_harness" / "module_a.py").write_text("# x\n", encoding="utf-8")
    _run(w, "add", "-A")
    _run(w, "commit", "-q", "-m", "i")
    return w


def _export(repo: Path, task_id: str = "T-1", objective: str = "ORIGINAL real objective") -> Path:
    h = build_handoff(repo, task_id=task_id, task_type="review-route", target_model="codex", project_id="P",
                      objective=objective,
                      scope=TaskBoundary(task_id=task_id, allowed_path_prefixes=("dv_harness/module_a.py",)),
                      input_evidence_refs=["dv_harness/module_a.py"])
    wf.export_handoff(repo, h)
    return repo / ".dv-harness/model_handoffs" / task_id / "RESULT_V1.md"


def _malformed_result_text(task_id: str) -> str:
    bad = "D:" + chr(92) + "DV" + chr(92) + "single" + chr(92) + "backslash"
    return (
        "# L5DGVA_MODEL_RESULT_V1\n\n"
        "<!-- L5DGVA_VALUE_ENCODING=escaped-v1 -->\n\n"
        "## RESULT_VERSION\n1.0\n\n"
        f"## TASK_ID\n{task_id}\n\n"
        "## PRODUCER_MODEL\ncodex\n\n"
        "## TASK_TYPE\nreview-route\n\n"
        "## RESULT_STATUS\nFAIL\n\n"
        "## CLAIMS\n- CLAIM: c\n\n"
        f"## FINDINGS\n- FINDING: path is {bad}\n\n"
        "## EVIDENCE_REFS\n- dv_harness/module_a.py:1\n\n"
        "## COUNTER_EVIDENCE\n(none)\n\n"
        "## UNKNOWN_ITEMS\n(none)\n\n"
        "## FILES_REFERENCED\n- dv_harness/module_a.py\n\n"
        "## VALIDATION_PERFORMED\n- v\n\n"
        "## RECOMMENDED_ACTIONS\n(none)\n\n"
        "## HUMAN_DECISIONS_REQUIRED\n(none)\n\n"
        "## SCOPE_EXCEPTIONS\n(none)\n\n"
        f"## RETURNED_ARTIFACTS\n- .dv-harness/model_handoffs/{task_id}/RESULT_V1.md\n"
    )


def test_real_malformed_escape_result_is_rejected_not_silently_accepted(repo):
    """Sanity precondition: the exact real defect shape (an un-doubled
    backslash under the escaped-v1 marker) is genuinely rejected by the
    real parser, confirming this test's setup reproduces what REVIEW-007
    actually hit live, not an invented shape."""
    expected = _export(repo, "T-1")
    expected.write_text(_malformed_result_text("T-1"), encoding="utf-8")
    outcome = wf.import_result(repo, "T-1", expected)
    assert outcome.state == wf.STATE_RESULT_REJECTED
    assert outcome.parse_error == "MALFORMED_ESCAPE"


def test_correction_request_names_the_exact_real_failure(repo):
    expected = _export(repo, "T-1")
    expected.write_text(_malformed_result_text("T-1"), encoding="utf-8")
    wf.import_result(repo, "T-1", expected)

    correction = wf.build_correction_request_handoff(repo, "T-1")
    assert "MALFORMED_ESCAPE" in correction.objective
    assert "OFFENDING_VALUE=" in correction.objective
    assert "POSITION_IN_VALUE=" in correction.objective
    assert "backslash" in correction.objective.lower()


def test_correction_request_preserves_the_original_objective_in_full(repo):
    expected = _export(repo, "T-1", objective="ORIGINAL_MARKER_TEXT_12345")
    expected.write_text(_malformed_result_text("T-1"), encoding="utf-8")
    wf.import_result(repo, "T-1", expected)

    correction = wf.build_correction_request_handoff(repo, "T-1")
    assert "ORIGINAL_MARKER_TEXT_12345" in correction.objective


def test_correction_request_targets_the_same_task_id_and_model(repo):
    expected = _export(repo, "T-1")
    expected.write_text(_malformed_result_text("T-1"), encoding="utf-8")
    wf.import_result(repo, "T-1", expected)

    correction = wf.build_correction_request_handoff(repo, "T-1")
    assert correction.task_id == "T-1"
    assert correction.target_model == "codex"
    assert correction.task_type == "review-route"


def test_re_exporting_the_correction_request_resets_to_waiting_for_human_transport(repo):
    expected = _export(repo, "T-1")
    expected.write_text(_malformed_result_text("T-1"), encoding="utf-8")
    wf.import_result(repo, "T-1", expected)
    assert wf.current_state(repo, "T-1") == wf.STATE_RESULT_REJECTED

    correction = wf.build_correction_request_handoff(repo, "T-1")
    wf.export_handoff(repo, correction)
    assert wf.current_state(repo, "T-1") == wf.STATE_WAITING_FOR_HUMAN_TRANSPORT

    # And the EXISTING registration/expected path still resolves for a
    # corrected resubmission -- no new task_id, no new registration.
    import dv_harness.result_ingestion as ri
    assert "T-1" in ri.list_pending(repo)


def test_a_corrected_resubmission_to_the_same_path_is_consumed_normally(repo):
    """End-to-end: malformed -> rejected -> correction request exported ->
    a real corrected resubmission to the SAME path is consumed cleanly."""
    from dv_harness.model_result import ModelResultV1, to_markdown as r_to
    import dv_harness.result_ingestion as ri

    expected = _export(repo, "T-1")
    expected.write_text(_malformed_result_text("T-1"), encoding="utf-8")
    wf.import_result(repo, "T-1", expected)

    correction = wf.build_correction_request_handoff(repo, "T-1")
    wf.export_handoff(repo, correction)

    fixed = ModelResultV1(
        result_version="1.0", task_id="T-1", producer_model="codex", task_type="review-route",
        result_status="PASS", claims=["c"], findings=[],
        evidence_refs=["dv_harness/module_a.py:1"], files_referenced=["dv_harness/module_a.py"])
    expected.write_text(r_to(fixed), encoding="utf-8")
    res = ri.ingest_result_file(repo, "T-1", expected, trigger="MANUAL",
                                policy=ri.IngestionPolicy(quiet_seconds=0.05, min_observations=2))
    assert res.action == "IMPORTED"
    assert wf.current_state(repo, "T-1") == wf.STATE_RESULT_CONSUMED


def test_refuses_to_build_a_correction_request_for_a_task_that_is_not_actually_rejected(repo):
    expected = _export(repo, "T-1")
    with pytest.raises(HandoffBuildError):
        wf.build_correction_request_handoff(repo, "T-1")  # still WAITING_FOR_HUMAN_TRANSPORT


def test_refuses_for_an_unknown_task_id(repo):
    with pytest.raises(HandoffBuildError):
        wf.build_correction_request_handoff(repo, "NO-SUCH-TASK")
