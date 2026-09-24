"""M7 V1 (L5DGVA_M7_STRUCTURED_MULTI_MODEL_MD_HANDOFF): tests for
`dv_harness/model_handoff.py` (HANDOFF_V1), `dv_harness/model_result.py`
(RESULT_V1 + round-trip validation), and `dv_harness/model_handoff_
workflow.py` (the real state machine + Canonical Consumer wiring).

Required test families (dispatch section 26), one section each below.
Every test runs against a real, throwaway git repo in tmp_path -- the
same real-git-over-tmp_path discipline `test_task_boundary_
conformance.py`/`test_m6_task_boundary_production_001.py` already
established, never a synthetic evidence fixture.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dv_harness.model_handoff import (
    ModelHandoffV1, build_handoff, to_markdown as handoff_to_markdown,
    from_markdown as handoff_from_markdown, HandoffBuildError, HandoffParseError,
    context_size_bytes,
)
from dv_harness.model_result import (
    ModelResultV1, to_markdown as result_to_markdown, from_markdown as result_from_markdown,
    ResultParseError, validate_result,
)
from dv_harness.model_handoff_workflow import (
    export_handoff, import_result, current_state, execute_verb,
    STATE_WAITING_FOR_HUMAN_TRANSPORT, STATE_RESULT_CONSUMED, STATE_RESULT_REJECTED,
    _registry_path,
)
from dv_harness.question_queue import QuestionQueueStore
from dv_harness.task_boundary_conformance import TaskBoundary

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git not on PATH")


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    _run(work, "init", "-q")
    _run(work, "config", "user.email", "test@example.com")
    _run(work, "config", "user.name", "Test")
    (work / "dv_harness").mkdir()
    (work / "dv_harness" / "module_a.py").write_text("# a\n", encoding="utf-8")
    (work / "dv_harness" / "module_b.py").write_text("# b\n", encoding="utf-8")
    _run(work, "add", "-A")
    _run(work, "commit", "-q", "-m", "initial")
    return work


def _scope(**overrides) -> TaskBoundary:
    base = dict(task_id="T-1", allowed_path_prefixes=("dv_harness/module_a.py",),
                forbidden_paths=("dv_harness/module_b.py",))
    base.update(overrides)
    return TaskBoundary(**base)


def _handoff(repo, **overrides) -> ModelHandoffV1:
    base = dict(task_id="T-1", task_type="review-route", target_model="codex",
                project_id="L5_DGVA", objective="Independent review of module_a.py",
                scope=_scope(), input_evidence_refs=["dv_harness/module_a.py"])
    base.update(overrides)
    return build_handoff(repo, **base)


def _pass_result(**overrides) -> ModelResultV1:
    base = dict(result_version="1.0", task_id="T-1", producer_model="codex", task_type="review-route",
                result_status="PASS", claims=["looks correct"], findings=["no defects"],
                evidence_refs=["dv_harness/module_a.py:1"], files_referenced=["dv_harness/module_a.py"])
    base.update(overrides)
    return ModelResultV1(**base)


# ---------------------------------------------------------------------------
# 1. Valid HANDOFF_V1 (build + markdown round-trip)
# ---------------------------------------------------------------------------

def test_valid_handoff_round_trips_through_markdown(repo):
    h = _handoff(repo)
    md = handoff_to_markdown(h)
    assert "L5DGVA_MODEL_HANDOFF_V1" in md
    h2 = handoff_from_markdown(md)
    assert h2.task_id == h.task_id
    assert h2.target_model == h.target_model
    assert h2.scope.allowed_path_prefixes == h.scope.allowed_path_prefixes
    assert h2.current_head == h.current_head
    assert h2.input_evidence_refs == h.input_evidence_refs


def test_handoff_current_head_is_a_real_git_sha(repo):
    h = _handoff(repo)
    real_head = _run(repo, "rev-parse", "HEAD").stdout.strip()
    assert h.current_head == real_head


def test_handoff_governance_refs_resolved_from_real_registry_when_present(repo):
    # governance_registry.py's own real registry lives at the CANONICAL
    # repo root, not the throwaway tmp_path repo -- resolving against the
    # real repo proves the reuse wiring works; a trigger with no match is
    # a legitimate empty result, not a failure.
    from pathlib import Path as _P
    canonical_root = _P(__file__).resolve().parents[1]
    h = build_handoff(canonical_root, task_id="T-GOV", task_type="review-route",
                      target_model="codex", project_id="L5_DGVA", objective="x",
                      scope=_scope(task_id="T-GOV"), governance_trigger="task boundary")
    assert isinstance(h.required_governance_refs, tuple)


# ---------------------------------------------------------------------------
# 2. Invalid/missing required handoff fields
# ---------------------------------------------------------------------------

def test_build_handoff_rejects_invalid_target_model(repo):
    with pytest.raises(HandoffBuildError) as exc:
        _handoff(repo, target_model="gemini")
    assert exc.value.reason == "INVALID_TARGET_MODEL"


def test_build_handoff_rejects_missing_task_id(repo):
    with pytest.raises(HandoffBuildError) as exc:
        _handoff(repo, task_id="")
    assert exc.value.reason == "MISSING_TASK_ID"


def test_build_handoff_rejects_missing_objective(repo):
    with pytest.raises(HandoffBuildError) as exc:
        _handoff(repo, objective="")
    assert exc.value.reason == "MISSING_OBJECTIVE"


def test_build_handoff_rejects_invalid_expected_output_type(repo):
    with pytest.raises(HandoffBuildError) as exc:
        _handoff(repo, expected_output_type="not_a_real_type")
    assert exc.value.reason == "INVALID_EXPECTED_OUTPUT_TYPE"


def test_from_markdown_rejects_a_document_missing_required_fields():
    with pytest.raises(HandoffParseError) as exc:
        handoff_from_markdown("# L5DGVA_MODEL_HANDOFF_V1\n\n## TASK_ID\nT-1\n")
    assert exc.value.reason == "MISSING_REQUIRED_FIELDS"
    assert "OBJECTIVE" in exc.value.detail["missing"]


def test_from_markdown_rejects_a_non_handoff_document():
    with pytest.raises(HandoffParseError) as exc:
        handoff_from_markdown("just some random text")
    assert exc.value.reason == "NOT_A_HANDOFF_DOCUMENT"


# ---------------------------------------------------------------------------
# 3. Valid RESULT_V1 (round-trip)
# ---------------------------------------------------------------------------

def test_valid_result_round_trips_through_markdown():
    r = _pass_result()
    md = result_to_markdown(r)
    assert "L5DGVA_MODEL_RESULT_V1" in md
    r2 = result_from_markdown(md)
    assert r2.task_id == r.task_id
    assert r2.result_status == r.result_status
    assert r2.evidence_refs == r.evidence_refs
    assert r2.claims == r.claims


# ---------------------------------------------------------------------------
# 4. Malformed result
# ---------------------------------------------------------------------------

def test_malformed_markdown_is_a_real_parse_error_not_a_silent_default():
    with pytest.raises(ResultParseError) as exc:
        result_from_markdown("not a result document at all")
    assert exc.value.reason == "NOT_A_RESULT_DOCUMENT"


def test_missing_required_result_fields_is_a_real_parse_error():
    with pytest.raises(ResultParseError) as exc:
        result_from_markdown("# L5DGVA_MODEL_RESULT_V1\n\n## TASK_ID\nT-1\n")
    assert exc.value.reason == "MISSING_REQUIRED_FIELDS"


def test_invalid_result_status_is_a_real_parse_error():
    bad = result_to_markdown(_pass_result()).replace("PASS", "MAYBE_OK_I_GUESS")
    with pytest.raises(ResultParseError) as exc:
        result_from_markdown(bad)
    assert exc.value.reason == "INVALID_RESULT_STATUS"


# ---------------------------------------------------------------------------
# 5/6/7/8. Task ID mismatch / producer mismatch / scope violation /
# forbidden file reference / missing evidence
# ---------------------------------------------------------------------------

def test_task_id_mismatch_is_not_accepted(repo):
    h = _handoff(repo)
    r = _pass_result(task_id="WRONG-ID")
    v = validate_result(h, r)
    assert v.task_id_validated is False
    assert v.accepted is False
    assert "TASK_ID_MISMATCH" in v.findings


def test_incompatible_task_type_is_not_accepted(repo):
    h = _handoff(repo, task_type="review-route")
    r = _pass_result(task_type="build-route")  # a real, different task type
    v = validate_result(h, r)
    assert v.task_type_validated is False
    assert v.accepted is False
    assert "TASK_TYPE_INCOMPATIBLE" in v.findings


def test_producer_mismatch_is_not_accepted(repo):
    h = _handoff(repo, target_model="codex")
    r = _pass_result(producer_model="chatgpt")
    v = validate_result(h, r)
    assert v.producer_validated is False
    assert v.accepted is False


def test_scope_violation_is_not_accepted(repo):
    h = _handoff(repo)  # allows only module_a.py, forbids module_b.py
    r = _pass_result(files_referenced=["dv_harness/module_b.py"])
    v = validate_result(h, r)
    assert v.scope_validated is False
    assert v.scope_violations[0]["path"] == "dv_harness/module_b.py"
    assert v.accepted is False


def test_forbidden_file_reference_is_flagged_even_if_also_plausible(repo):
    h = _handoff(repo)
    r = _pass_result(files_referenced=["dv_harness/module_a.py", "dv_harness/module_b.py"])
    v = validate_result(h, r)
    assert v.accepted is False
    assert any(sv["path"] == "dv_harness/module_b.py" for sv in v.scope_violations)


def test_missing_evidence_for_real_claims_is_not_accepted(repo):
    h = _handoff(repo)
    r = _pass_result(evidence_refs=[])  # claims/findings present, but no evidence_refs
    v = validate_result(h, r)
    assert v.evidence_validated is False
    assert v.accepted is False


def test_no_claims_no_findings_does_not_require_evidence(repo):
    h = _handoff(repo)
    r = _pass_result(claims=[], findings=[], evidence_refs=[], result_status="BLOCKED")
    v = validate_result(h, r)
    assert v.evidence_validated is True


# ---------------------------------------------------------------------------
# 9/10. Valid result consumption / rejected result not consumed
# ---------------------------------------------------------------------------

def test_valid_result_reaches_real_consumption(repo):
    h = _handoff(repo)
    export_handoff(repo, h)
    result_path = repo / "RESULT.md"
    result_path.write_text(result_to_markdown(_pass_result()), encoding="utf-8")

    outcome = import_result(repo, "T-1", result_path)
    assert outcome.state == STATE_RESULT_CONSUMED
    assert outcome.consumed is True
    assert _registry_path(repo).exists()
    registry_text = _registry_path(repo).read_text(encoding="utf-8")
    assert "T-1" in registry_text
    assert "codex" in registry_text


def test_rejected_result_is_never_consumed(repo):
    h = _handoff(repo)
    export_handoff(repo, h)
    result_path = repo / "BAD.md"
    result_path.write_text(result_to_markdown(_pass_result(task_id="WRONG")), encoding="utf-8")

    outcome = import_result(repo, "T-1", result_path)
    assert outcome.state == STATE_RESULT_REJECTED
    assert outcome.consumed is False
    assert not _registry_path(repo).exists()  # nothing was ever consumed/registered


def test_import_with_no_matching_handoff_is_rejected(repo):
    outcome = import_result(repo, "NEVER-EXPORTED", repo / "whatever.md")
    assert outcome.state == STATE_RESULT_REJECTED
    assert outcome.parse_error == "NO_MATCHING_HANDOFF"


# ---------------------------------------------------------------------------
# 11. Human wait/resume (state persists across process-shaped calls)
# ---------------------------------------------------------------------------

def test_export_leaves_state_waiting_for_human_transport(repo):
    h = _handoff(repo)
    export_handoff(repo, h)
    assert current_state(repo, "T-1") == STATE_WAITING_FOR_HUMAN_TRANSPORT


def test_status_check_does_not_mutate_state_or_busy_wait(repo):
    h = _handoff(repo)
    export_handoff(repo, h)
    s1 = current_state(repo, "T-1")
    s2 = current_state(repo, "T-1")
    assert s1 == s2 == STATE_WAITING_FOR_HUMAN_TRANSPORT  # a real, idempotent read


def test_resume_reads_real_persisted_state_a_second_process_could_read(repo):
    h = _handoff(repo)
    export_handoff(repo, h)
    # Simulate resumption: a fresh call with only (root, task_id), no
    # in-memory object carried over from export_handoff() above.
    resumed_state = current_state(Path(str(repo)), "T-1")
    assert resumed_state == STATE_WAITING_FOR_HUMAN_TRANSPORT


# ---------------------------------------------------------------------------
# 12/13. Codex / ChatGPT round-trip state (WAITING_FOR_HUMAN_TRANSPORT
# until a real result is returned -- never fabricated)
# ---------------------------------------------------------------------------

def test_codex_round_trip_state_is_waiting_until_a_real_result_returns(repo):
    h = _handoff(repo, target_model="codex")
    export_handoff(repo, h)
    assert current_state(repo, "T-1") == STATE_WAITING_FOR_HUMAN_TRANSPORT
    # No result file exists yet -- the real state must not silently advance.


def test_chatgpt_round_trip_state_is_waiting_until_a_real_result_returns(repo):
    h = _handoff(repo, task_id="T-2", target_model="chatgpt")
    export_handoff(repo, h)
    assert current_state(repo, "T-2") == STATE_WAITING_FOR_HUMAN_TRANSPORT


# ---------------------------------------------------------------------------
# 14. Independent-review context (no biasing conclusion in the handoff)
# ---------------------------------------------------------------------------

def test_independent_review_handoff_carries_no_prior_verdict_field(repo):
    h = _handoff(repo, independence_requirement="Do not assume the change is correct; "
                                                 "report defects independently.")
    md = handoff_to_markdown(h)
    assert "INDEPENDENCE_REQUIREMENT" in md
    assert "Do not assume the change is correct" in md
    # The handoff's own KNOWN_FACTS is caller-controlled and empty by
    # default here -- proving no implicit "it's fine" conclusion is baked
    # in by the builder itself.
    assert h.known_facts == ()


# ---------------------------------------------------------------------------
# 15. Fallback (missing/unavailable target, human transport error shapes)
# ---------------------------------------------------------------------------

def test_missing_result_file_is_a_real_rejection_not_a_crash(repo):
    h = _handoff(repo)
    export_handoff(repo, h)
    outcome = import_result(repo, "T-1", repo / "does_not_exist.md")
    assert outcome.state == STATE_RESULT_REJECTED
    assert outcome.parse_error == "RESULT_FILE_UNREADABLE"


def test_cli_import_exit_code_reflects_rejection(repo):
    h = _handoff(repo)
    export_handoff(repo, h)
    rc = execute_verb(["import", "--task-id", "T-1", "--result-file",
                       str(repo / "missing.md"), "--root", str(repo)])
    assert rc == 1


def test_cli_export_then_status_round_trip(repo):
    rc = execute_verb(["export", "--task-id", "T-CLI2", "--task-type", "review-route",
                       "--target-model", "chatgpt", "--project-id", "L5_DGVA",
                       "--objective", "cli test", "--root", str(repo)])
    assert rc == 0
    rc2 = execute_verb(["status", "--task-id", "T-CLI2", "--root", str(repo)])
    assert rc2 == 0


# ---------------------------------------------------------------------------
# 16. M6 non-regression -- this module must never touch M6's own real
# mechanisms except through their real, existing public API (TaskBoundary,
# QuestionQueueStore), never re-implement or bypass them.
# ---------------------------------------------------------------------------

def test_human_decision_required_routes_through_the_real_question_queue(repo):
    h = _handoff(repo)
    export_handoff(repo, h)
    result_path = repo / "RESULT_HDR.md"
    r = _pass_result(result_status="HUMAN_DECISION_REQUIRED",
                     human_decisions_required=["Should this finding block the change?"])
    result_path.write_text(result_to_markdown(r), encoding="utf-8")

    outcome = import_result(repo, "T-1", result_path)
    assert outcome.state == STATE_RESULT_CONSUMED
    assert outcome.question_id is not None
    store = QuestionQueueStore(repo)
    persisted = store.get_question(outcome.question_id)
    assert persisted is not None
    assert persisted["domain"] == "env"


def test_pass_result_with_no_human_decision_files_no_question(repo):
    h = _handoff(repo, task_id="T-NOQ")
    export_handoff(repo, h)
    result_path = repo / "RESULT_NOQ.md"
    result_path.write_text(result_to_markdown(_pass_result(task_id="T-NOQ")), encoding="utf-8")
    outcome = import_result(repo, "T-NOQ", result_path)
    assert outcome.question_id is None
    assert QuestionQueueStore(repo).list_questions() == []


def test_context_size_metrics_are_real_byte_counts_not_token_counts(repo):
    h = _handoff(repo)
    metrics = context_size_bytes(h)
    md_len = len(handoff_to_markdown(h).encode("utf-8"))
    assert metrics["handoff_bytes"] == md_len
    assert isinstance(metrics["handoff_bytes"], int)
