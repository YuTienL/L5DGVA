"""Real-producer tests for dv_harness/consolidated_kpi_benchmark.py.

Every fixture here is built through the REAL owning module -- a real
`QuestionQueueStore.add_question()`, a real `loop_telemetry.emit()` through a
real `storage.StateStore`, a real `evidence_db.EvidenceStore.
insert_regression_verdict()`, a real `waiver_store.record_waiver()`/
`revoke_waiver()`, and a real `signoff_export.freeze_signoff_baseline()`.
Nothing is hand-written into a JSON/JSONL file to look like real evidence.

Core positive paths are proven MEASURED with a value that matches (or is
independently derivable from) the real underlying producer's own output, and
each is paired with real negative controls: no evidence at all (NOT_AVAILABLE)
and too little evidence (INSUFFICIENT_HISTORY) -- so a report never reports a
fabricated 100%/0% off a couple of samples. `ir_extraction_accuracy` /
`manual_edit_count` / `human_engineering_time` are asserted NOT_MEASURED with
a real, named missing-producer reason on every call -- the headline assertion
this task requires.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from dv_harness import consolidated_kpi_benchmark as kpi_mod
from dv_harness.question_queue import QuestionQueueStore
from dv_harness.storage import StateStore
from dv_harness import loop_telemetry
from dv_harness.evidence_db import EvidenceStore, default_db_path
from dv_harness import waiver_store
from dv_harness.signoff_export import freeze_signoff_baseline


# ---------------------------------------------------------------------------
# Fixture builders -- each goes through the REAL producing module
# ---------------------------------------------------------------------------

def _add_question(qq: QuestionQueueStore, idx: int, *, distinct: bool = True) -> dict:
    """One real filed question. `distinct=False` re-asks the SAME
    question_key as index 0, so a caller can build a real repeated-ask
    corpus."""
    suffix = idx if distinct else 0
    return qq.add_question(
        domain="env",
        question=f"is dimension {suffix} configured this way?",
        context_path=f"config/dim_{suffix}",
        options=["yes", "no"],
        recommendation="yes",
        assumption_if_unanswered="yes",
    )


def _emit_loop_run(store: StateStore, run_id: str, *, verdict: str = "PASS",
                   stage: str = "IMPLEMENT") -> None:
    loop_telemetry.emit(store, "LOOP_STARTED", run_id=run_id, stage=stage)
    time.sleep(0.01)
    loop_telemetry.emit(store, "LOOP_VERIFY_COMPLETED", run_id=run_id, stage=stage,
                        status=verdict, verdict=verdict)


def _minimal_waiver(waiver_id: str) -> dict:
    return {
        "waiver_id": waiver_id,
        "item": "coverage/bin_x",
        "reason": "known tool limitation, tracked externally",
        "evidence": "ticket://TOOL-123",
        "scope": {
            "requirement_ids": "REQ-1",
            "subsystem": "usb",
            "spec_revision": "v1",
            "design_evidence_hash": "abc123",
            "approval_id": "APR-1",
            "scope_hash": "hash1",
        },
        "approver": "test-approver",
        "affected_version": {"rtl_hash": "deadbeef"},
        "risk": "LOW",
        "created_at": "2026-09-01T00:00:00Z",
        "expires_at": "2099-01-01T00:00:00Z",
    }


# ---------------------------------------------------------------------------
# question_queue_self_resolve_rate + repeated_question_count
# ---------------------------------------------------------------------------

def test_self_resolve_rate_not_available_with_no_questions(tmp_path):
    result = kpi_mod.kpi_question_queue_self_resolve_rate(tmp_path)
    assert result["status"] == kpi_mod.KPI_NOT_AVAILABLE
    assert result["value"] is None
    assert result["reason"] == "NO_QUESTIONS_RECORDED"
    assert result["real_producer"] == kpi_mod.PRODUCER_QUESTION_QUEUE_METRICS


def test_self_resolve_rate_insufficient_history_below_threshold(tmp_path):
    qq = QuestionQueueStore(tmp_path)
    for i in range(kpi_mod.MIN_SAMPLE_FOR_RATE - 1):
        _add_question(qq, i)
    result = kpi_mod.kpi_question_queue_self_resolve_rate(tmp_path, store=qq)
    assert result["status"] == kpi_mod.KPI_INSUFFICIENT_HISTORY
    assert result["value"] is None
    assert result["sample_size"] == kpi_mod.MIN_SAMPLE_FOR_RATE - 1


def test_self_resolve_rate_measured_matches_real_compute_metrics(tmp_path):
    qq = QuestionQueueStore(tmp_path)
    for i in range(kpi_mod.MIN_SAMPLE_FOR_RATE + 3):
        _add_question(qq, i)
    # Independently call the REAL producer this KPI is supposed to reuse,
    # and assert the KPI's reported number is not a re-derivation that could
    # silently drift from it.
    real_metrics = qq.compute_metrics()
    result = kpi_mod.kpi_question_queue_self_resolve_rate(tmp_path, store=qq)
    assert result["status"] == kpi_mod.KPI_MEASURED
    assert result["value"] == real_metrics["self_resolve_rate_percent"]
    assert result["detail"]["blocking_questions_per_week"] == real_metrics["blocking_questions_per_week"]
    assert result["detail"]["repeat_question_rate_percent"] == real_metrics["repeat_question_rate_percent"]
    assert result["sample_size"] == kpi_mod.MIN_SAMPLE_FOR_RATE + 3


def test_repeated_question_count_not_available_with_no_questions(tmp_path):
    result = kpi_mod.kpi_repeated_question_count(tmp_path)
    assert result["status"] == kpi_mod.KPI_NOT_AVAILABLE
    assert result["value"] is None


def test_repeated_question_count_measured_counts_real_reasks(tmp_path):
    qq = QuestionQueueStore(tmp_path)
    # 3 distinct question_keys, plus 4 more asks that re-use key index 0 --
    # 7 total asks, 3 distinct keys, so 4 are real repeats.
    for i in range(3):
        _add_question(qq, i)
    for _ in range(4):
        _add_question(qq, 0, distinct=False)
    result = kpi_mod.kpi_repeated_question_count(tmp_path, store=qq)
    assert result["status"] == kpi_mod.KPI_MEASURED
    assert result["value"] == 4
    assert result["detail"]["distinct_question_keys"] == 3
    assert result["detail"]["total_asks"] == 7


def test_repeated_question_count_zero_when_every_ask_is_distinct(tmp_path):
    qq = QuestionQueueStore(tmp_path)
    for i in range(5):
        _add_question(qq, i)
    result = kpi_mod.kpi_repeated_question_count(tmp_path, store=qq)
    assert result["status"] == kpi_mod.KPI_MEASURED
    assert result["value"] == 0


# ---------------------------------------------------------------------------
# time_to_first_pass
# ---------------------------------------------------------------------------

def test_time_to_first_pass_not_available_with_no_events(tmp_path):
    result = kpi_mod.kpi_time_to_first_pass(tmp_path)
    assert result["status"] == kpi_mod.KPI_NOT_AVAILABLE
    assert result["value"] is None
    assert result["reason"] == "NO_LOOP_TELEMETRY_EVENTS"


def test_time_to_first_pass_insufficient_history_below_min_runs(tmp_path):
    store = StateStore(tmp_path)
    for i in range(kpi_mod.MIN_RUNS_FOR_TIMING - 1):
        _emit_loop_run(store, f"run-{i}", verdict="PASS")
    result = kpi_mod.kpi_time_to_first_pass(tmp_path)
    assert result["status"] == kpi_mod.KPI_INSUFFICIENT_HISTORY
    assert result["value"] is None
    assert result["sample_size"] == kpi_mod.MIN_RUNS_FOR_TIMING - 1


def test_time_to_first_pass_measured_over_real_loop_telemetry(tmp_path):
    store = StateStore(tmp_path)
    for i in range(kpi_mod.MIN_RUNS_FOR_TIMING + 1):
        _emit_loop_run(store, f"run-{i}", verdict="PASS")
    result = kpi_mod.kpi_time_to_first_pass(tmp_path)
    assert result["status"] == kpi_mod.KPI_MEASURED
    assert result["unit"] == "seconds"
    assert result["value"] >= 0.0
    assert result["sample_size"] == kpi_mod.MIN_RUNS_FOR_TIMING + 1
    assert result["detail"]["min_seconds"] <= result["value"] <= result["detail"]["max_seconds"]


def test_time_to_first_pass_never_counts_a_fail_verdict_as_first_pass(tmp_path):
    """Negative control: a run whose only LOOP_VERIFY_COMPLETED is FAIL must
    never contribute a duration -- proves the KPI reads `verdict`, not merely
    "any LOOP_VERIFY_COMPLETED event happened"."""
    store = StateStore(tmp_path)
    for i in range(kpi_mod.MIN_RUNS_FOR_TIMING):
        _emit_loop_run(store, f"fail-{i}", verdict="FAIL")
    result = kpi_mod.kpi_time_to_first_pass(tmp_path)
    # runs_seen > 0 (real LOOP_STARTED events exist) but zero reached PASS
    assert result["status"] == kpi_mod.KPI_INSUFFICIENT_HISTORY
    assert result["sample_size"] == 0


# ---------------------------------------------------------------------------
# false_pass_count
# ---------------------------------------------------------------------------

def test_false_pass_count_not_available_with_no_evidence_db(tmp_path):
    result = kpi_mod.kpi_false_pass_count(tmp_path)
    assert result["status"] == kpi_mod.KPI_NOT_AVAILABLE
    assert result["value"] is None
    assert result["reason"] == "NO_EVIDENCE_DATABASE"


def test_false_pass_count_insufficient_history_below_threshold(tmp_path):
    db_path = default_db_path(tmp_path)
    store = EvidenceStore(db_path)
    try:
        store.insert_regression_verdict("pat_flaky", True, job_id=1, git_sha="sha1")
        store.insert_regression_verdict("pat_flaky", False, job_id=2, git_sha="sha1")
    finally:
        store.close()
    result = kpi_mod.kpi_false_pass_count(tmp_path)
    assert result["status"] == kpi_mod.KPI_INSUFFICIENT_HISTORY
    assert result["value"] is None
    assert result["sample_size"] == 2


def test_false_pass_count_measured_detects_same_sha_pass_and_fail(tmp_path):
    db_path = default_db_path(tmp_path)
    store = EvidenceStore(db_path)
    try:
        # The real false-PASS signal: identical git_sha both passed and
        # failed.
        store.insert_regression_verdict("pat_flaky", True, job_id=1, git_sha="sha1")
        store.insert_regression_verdict("pat_flaky", False, job_id=2, git_sha="sha1")
        # Padding rows, spread across other patterns, that do NOT regress --
        # real history, never a real regression -- to clear
        # MIN_SAMPLE_FOR_RATE without adding a second false-pass.
        for i in range(4):
            store.insert_regression_verdict(f"pat_clean_{i}", True, job_id=10 + i, git_sha=f"sha{i}")
            store.insert_regression_verdict(f"pat_clean_{i}", True, job_id=20 + i, git_sha=f"sha{i}b")
    finally:
        store.close()
    result = kpi_mod.kpi_false_pass_count(tmp_path)
    assert result["status"] == kpi_mod.KPI_MEASURED
    assert result["value"] == 1
    assert result["detail"]["affected_patterns"] == ["pat_flaky"]
    assert result["sample_size"] == 10


def test_false_pass_count_zero_when_no_pattern_regressed(tmp_path):
    """Negative control: real history, real distinct SHAs, everything still
    passing -- must report a real zero, not merely skip the KPI."""
    db_path = default_db_path(tmp_path)
    store = EvidenceStore(db_path)
    try:
        for i in range(10):
            store.insert_regression_verdict(f"pat_{i}", True, job_id=i, git_sha=f"sha{i}")
    finally:
        store.close()
    result = kpi_mod.kpi_false_pass_count(tmp_path)
    assert result["status"] == kpi_mod.KPI_MEASURED
    assert result["value"] == 0


# ---------------------------------------------------------------------------
# false_ready_count
# ---------------------------------------------------------------------------

def test_false_ready_count_not_available_with_no_freeze(tmp_path):
    result = kpi_mod.kpi_false_ready_count(tmp_path)
    assert result["status"] == kpi_mod.KPI_NOT_AVAILABLE
    assert result["value"] is None


def test_false_ready_count_measured_zero_when_freeze_still_valid(tmp_path):
    waiver_store.record_waiver(tmp_path, _minimal_waiver("W-STILL-VALID"))
    freeze_signoff_baseline(tmp_path, frozen_by="test-human")
    result = kpi_mod.kpi_false_ready_count(tmp_path)
    assert result["status"] == kpi_mod.KPI_MEASURED
    assert result["value"] == 0
    assert result["sample_size"] == 1


def test_false_ready_count_measured_detects_invalidated_freeze(tmp_path):
    """Core positive path: a signoff baseline was frozen (declared READY),
    the waiver it carried was later revoked with no RTL/git change at all --
    exactly the section-238 post-freeze-invalidation path signoff_export.py
    itself proves -- and this KPI must report that as a real false-ready
    count, not silently as VALID."""
    waiver_store.record_waiver(tmp_path, _minimal_waiver("W-LATER-REVOKED"))
    freeze_signoff_baseline(tmp_path, frozen_by="test-human")
    waiver_store.revoke_waiver(tmp_path, "W-LATER-REVOKED", "test-human",
                               "superseded by a corrected fix")
    result = kpi_mod.kpi_false_ready_count(tmp_path)
    assert result["status"] == kpi_mod.KPI_MEASURED
    assert result["value"] == 1
    assert result["sample_size"] == 1


# ---------------------------------------------------------------------------
# The headline requirement: NOT_MEASURED KPIs never fabricate a number
# ---------------------------------------------------------------------------

def test_ir_extraction_accuracy_is_always_not_measured_never_fabricated():
    result = kpi_mod.kpi_ir_extraction_accuracy()
    assert result["status"] == kpi_mod.KPI_NOT_MEASURED
    assert result["value"] is None
    assert result["reason"] == "NO_ACCURACY_PRODUCER_EXISTS"
    assert "requirement_contract" in result["detail"]["closest_existing_mechanisms"][0]
    assert "vplan_baseline" in result["detail"]["closest_existing_mechanisms"][1]


def test_manual_edit_count_is_always_not_measured_never_fabricated():
    result = kpi_mod.kpi_manual_edit_count()
    assert result["status"] == kpi_mod.KPI_NOT_MEASURED
    assert result["value"] is None
    assert result["reason"] == "NO_PRODUCER_EXISTS"


def test_human_engineering_time_is_always_not_measured_never_fabricated():
    result = kpi_mod.kpi_human_engineering_time()
    assert result["status"] == kpi_mod.KPI_NOT_MEASURED
    assert result["value"] is None
    assert result["reason"] == "NO_PRODUCER_EXISTS"


# ---------------------------------------------------------------------------
# The consolidated report itself
# ---------------------------------------------------------------------------

def test_benchmark_report_includes_every_kpi_in_fixed_order(tmp_path):
    report = kpi_mod.benchmark_report(tmp_path)
    names = tuple(k["kpi"] for k in report["kpis"])
    assert names == kpi_mod.KPI_NAMES
    assert report["kpi_count"] == len(kpi_mod.KPI_NAMES)


def test_benchmark_report_on_a_bare_project_never_fabricates_any_number(tmp_path):
    """A project with nothing recorded anywhere must report every KPI as
    NOT_AVAILABLE or NOT_MEASURED -- never a computed value, and never a
    fabricated 100%/0%."""
    report = kpi_mod.benchmark_report(tmp_path)
    for k in report["kpis"]:
        assert k["status"] in (kpi_mod.KPI_NOT_AVAILABLE, kpi_mod.KPI_NOT_MEASURED)
        assert k["value"] is None
        assert k["reason"]


def test_benchmark_report_reading_writes_nothing_to_a_bare_project(tmp_path):
    """Reading is never a mutating act -- no QuestionQueueStore/EvidenceStore
    write path is triggered by merely producing a report."""
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    kpi_mod.benchmark_report(tmp_path)
    after = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    assert before == after == []


def test_kpi_vocabulary_disjoint_from_models_status():
    from dv_harness.models import Status
    verdicts = {s.value for s in Status}
    assert not verdicts.intersection(kpi_mod.KPI_STATUSES)


def test_kpi_helper_requires_reason_for_non_measured_status():
    with pytest.raises(ValueError):
        kpi_mod._kpi("x", kpi_mod.CATEGORY_INTAKE, kpi_mod.KPI_NOT_MEASURED)


def test_kpi_helper_rejects_unknown_status():
    with pytest.raises(ValueError):
        kpi_mod._kpi("x", kpi_mod.CATEGORY_INTAKE, "BOGUS_STATUS", reason="x")


# ---------------------------------------------------------------------------
# CLI front door
# ---------------------------------------------------------------------------

def test_cli_names_verb(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.consolidated_kpi_benchmark", "names",
         "--project-root", str(tmp_path)],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]))
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["kpi_names"] == list(kpi_mod.KPI_NAMES)


def test_cli_report_verb_json_on_bare_project(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.consolidated_kpi_benchmark", "report", "--json",
         "--project-root", str(tmp_path)],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]))
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["kpi_count"] == len(kpi_mod.KPI_NAMES)


def test_cli_show_verb_renders_text(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.consolidated_kpi_benchmark", "show",
         "--project-root", str(tmp_path)],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]))
    assert proc.returncode == 0, proc.stderr
    assert "Consolidated KPI Benchmark" in proc.stdout
    assert "ir_extraction_accuracy" in proc.stdout
