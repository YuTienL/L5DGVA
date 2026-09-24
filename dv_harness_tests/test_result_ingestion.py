"""Behavioral tests for dv_harness/result_ingestion.py (Automatic External
Result Ingestion, `HUMAN_MANUAL_IMPORT_REQUIRED=NO`). The 17 test names from
the requirements/prompt are present verbatim; each drives the real workflow
against a throwaway git repo -- no mock of the validator, parser or registry.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import dv_harness.model_handoff_workflow as wf
import dv_harness.result_ingestion as ri
from dv_harness import execution_contract as ec
from dv_harness.model_handoff import build_handoff
from dv_harness.model_result import ModelResultV1, to_markdown
from dv_harness.question_queue import QuestionQueueStore
from dv_harness.task_boundary_conformance import TaskBoundary

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git not on PATH")

POLICY = ri.IngestionPolicy(quiet_seconds=2.0, min_observations=2, max_import_attempts=3)


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
    for n in ("module_a.py", "engine.py"):
        (w / "dv_harness" / n).write_text("# x\n", encoding="utf-8")
    _run(w, "add", "-A")
    _run(w, "commit", "-q", "-m", "i")
    return w


def _export(repo: Path, task_id: str = "T-1", **kw) -> Path:
    h = build_handoff(repo, task_id=task_id, task_type="review-route", target_model="codex", project_id="P",
                      objective="review",
                      scope=TaskBoundary(task_id=task_id, allowed_path_prefixes=("dv_harness/module_a.py",),
                                         forbidden_paths=("dv_harness/engine.py",)),
                      input_evidence_refs=["dv_harness/module_a.py"], **kw)
    wf.export_handoff(repo, h)
    return repo / ri._expected_path(repo, task_id).relative_to(repo)


def _res(task_id="T-1", **kw) -> ModelResultV1:
    base = dict(result_version="1.0", task_id=task_id, producer_model="codex", task_type="review-route",
                result_status="FAIL", claims=["c"], findings=["f"],
                evidence_refs=["dv_harness/module_a.py:1"], files_referenced=["dv_harness/module_a.py"])
    base.update(kw)
    return ModelResultV1(**base)


def _place(path: Path, result: ModelResultV1) -> str:
    path.write_text(to_markdown(result), encoding="utf-8")
    return path.read_text(encoding="utf-8")


def _settle(repo: Path, start: float = 0.0, step: float = 1.5, polls: int = 4, policy=POLICY):
    """Drive poll_once with injected time so stability is exercised
    without sleeping. Returns the list of per-poll reports."""
    out = []
    for i in range(polls):
        out.append(ri.poll_once(repo, policy=policy, now=start + i * step))
    return out


def _rows(repo: Path, task="T-1"):
    p = wf._registry_path(repo)
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["task_id"] == task]


def _events(repo: Path, task="T-1"):
    return [e["event"] for e in ri.read_events(repo, task)]


# ------------------------------------------------------------- registration

def test_expected_result_registration(repo):
    _export(repo)
    reg = json.loads((repo / ".dv-harness/model_handoffs/T-1/expected_result.json").read_text(encoding="utf-8"))
    for k in ("TASK_ID", "TARGET_MODEL", "HANDOFF_FILE", "EXPECTED_RESULT_FILE", "EXPECTED_RESULT_CONTRACT",
              "EXPECTED_PRODUCER", "EXPECTED_TASK_TYPE", "CURRENT_HEAD", "WAIT_STATE", "CREATED_AT"):
        assert reg[k], k
    assert reg["EXPECTED_RESULT_FILE"] == ".dv-harness/model_handoffs/T-1/RESULT_V1.md"
    assert reg["WAIT_STATE"] == "WAITING_FOR_HUMAN_TRANSPORT"
    assert reg["EXPECTED_PRODUCER"] == "codex"
    assert "EXPECTED_RESULT_REGISTERED" in _events(repo)
    assert ri.register_expected_result(repo, "T-1") == reg  # idempotent
    assert ri.list_pending(repo) == ["T-1"]


def test_two_pending_tasks_claiming_one_expected_path_is_a_conflict(repo):
    _export(repo, "T-1")
    _export(repo, "T-2")
    reg2 = repo / ".dv-harness/model_handoffs/T-2/expected_result.json"
    data = json.loads(reg2.read_text(encoding="utf-8"))
    data["EXPECTED_RESULT_FILE"] = ".dv-harness/model_handoffs/T-1/RESULT_V1.md"  # tampered / colliding registration
    reg2.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ri.IngestionError) as exc:
        ri.register_expected_result(repo, "T-1")
    assert exc.value.reason == "EXPECTED_RESULT_FILE_CONFLICT"


def test_unsafe_task_id_is_rejected(repo):
    with pytest.raises(ri.IngestionError):
        ri._task_dir(repo, "../evil")


# ------------------------------------------------------------- detection scope

def test_watcher_ignores_unregistered_files(repo):
    expected = _export(repo, "T-1")
    stray = repo / ".dv-harness/model_handoffs/T-UNREGISTERED"
    stray.mkdir(parents=True)
    (stray / "RESULT_V1.md").write_text(to_markdown(_res("T-UNREGISTERED")), encoding="utf-8")
    (repo / "RESULT_V1.md").write_text(to_markdown(_res()), encoding="utf-8")
    (repo / "notes.md").write_text("# not a result\n", encoding="utf-8")
    reports = _settle(repo)
    assert all(r["task_id"] == "T-1" for rep in reports for r in rep)
    assert not expected.exists()
    assert wf.current_state(repo, "T-1") == wf.STATE_WAITING_FOR_HUMAN_TRANSPORT
    assert wf.current_state(repo, "T-UNREGISTERED") is None
    assert _rows(repo, "T-UNREGISTERED") == []


def test_result_not_imported_until_stable(repo):
    expected = _export(repo)
    _place(expected, _res())
    assert ri.poll_once(repo, policy=POLICY, now=0.0)[0]["status"] == "OBSERVING"
    assert ri.poll_once(repo, policy=POLICY, now=1.0)[0]["status"] == "OBSERVING"  # 2 observations but < quiet
    assert wf.current_state(repo, "T-1") == wf.STATE_WAITING_FOR_HUMAN_TRANSPORT
    # content changes mid-write -> stability evidence resets
    _place(expected, _res(findings=["f", "g"]))
    assert ri.poll_once(repo, policy=POLICY, now=1.5)[0]["status"] == "OBSERVING"
    assert ri.poll_once(repo, policy=POLICY, now=3.0)[0]["status"] == "OBSERVING"
    assert wf.current_state(repo, "T-1") == wf.STATE_WAITING_FOR_HUMAN_TRANSPORT
    row = ri.poll_once(repo, policy=POLICY, now=4.0)[0]
    assert row["status"] == "STABLE" and row["action"] == "IMPORTED"
    assert wf.current_state(repo, "T-1") == wf.STATE_RESULT_CONSUMED
    ev = _events(repo)
    assert ev.index("RESULT_DETECTED") < ev.index("RESULT_STABILITY_CONFIRMED") < ev.index("RESULT_HASHED") \
        < ev.index("AUTO_IMPORT_STARTED")


def test_empty_file_is_never_imported(repo):
    expected = _export(repo)
    expected.write_text("", encoding="utf-8")
    assert all(r[0]["status"] == "OBSERVING" for r in _settle(repo))
    assert wf.current_state(repo, "T-1") == wf.STATE_WAITING_FOR_HUMAN_TRANSPORT


def test_symlinked_result_is_never_followed(repo, tmp_path):
    expected = _export(repo)
    target = tmp_path / "outside.md"
    target.write_text(to_markdown(_res()), encoding="utf-8")
    try:
        os.symlink(target, expected)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted")
    assert all(r[0]["status"] == "UNSAFE" for r in _settle(repo))
    assert wf.current_state(repo, "T-1") == wf.STATE_WAITING_FOR_HUMAN_TRANSPORT
    assert "RESULT_UNSAFE_PATH" in _events(repo)


# ------------------------------------------------------------- import / consume / resume

def test_auto_import_uses_canonical_validator(repo, monkeypatch):
    expected = _export(repo)
    calls = []
    real = wf.import_result
    monkeypatch.setattr(wf, "import_result", lambda *a, **k: (calls.append(a), real(*a, **k))[1])
    _place(expected, _res(task_id="T-WRONG"))  # the canonical validator's TASK_ID check must fire
    _settle(repo)
    assert len(calls) == 1 and Path(calls[0][2]).name == "RESULT_V1.md"
    entry = next(iter(ri._load_ing(repo, "T-1")["results"].values()))
    assert "TASK_ID_MISMATCH" in entry["validation_findings"]
    assert wf.current_state(repo, "T-1") == wf.STATE_RESULT_REJECTED


def test_valid_result_auto_consumes(repo):
    expected = _export(repo)
    _place(expected, _res())
    _settle(repo)
    assert wf.current_state(repo, "T-1") == wf.STATE_RESULT_CONSUMED
    assert len(_rows(repo)) == 1
    ing = ri._load_ing(repo, "T-1")
    entry = next(iter(ing["results"].values()))
    assert entry["import_state"] == "CONSUMED" and entry["consumed_at"] and entry["import_attempt_id"].startswith("T-1:")
    assert list(ing["results"])[0] == ing["last_detected_result_sha256"]
    assert ri.list_pending(repo) == []
    assert {"RESULT_ACCEPTED", "RESULT_CONSUMED"} <= set(_events(repo))


def test_valid_result_auto_resumes(repo):
    expected = _export(repo)
    _place(expected, _res())
    _settle(repo)
    rec = ec.read_next_action(repo, "T-1")
    assert rec["next_action"] == "AUTO_REMEDIATE_CONFIRMED_FINDINGS" and rec["auto_actionable"] is True
    stop = ec.read_persisted_stop(repo, "T-1")
    assert stop["STATE"] == "AUTO_RUNNING" and stop["HUMAN_ACTION_REQUIRED"] == "NO"  # stale transport stop replaced
    assert {"AUTO_RESUME_STARTED", "NEXT_ACTION_RESOLVED"} <= set(_events(repo))
    assert ri._load_ing(repo, "T-1")["auto_resume_status"] == "DONE"


def test_human_decision_result_resumes_into_a_real_authority_stop(repo):
    expected = _export(repo)
    _place(expected, _res(result_status="HUMAN_DECISION_REQUIRED", human_decisions_required=["accept?"]))
    _settle(repo)
    stop = ec.read_persisted_stop(repo, "T-1")
    assert stop["STOP_REASON"] == "HUMAN_AUTHORITY_REQUIRED" and stop["HUMAN_ACTION_REQUIRED"] == "YES"
    assert len(QuestionQueueStore(repo).list_questions()) == 1


# ------------------------------------------------------------- duplicates / quarantine / retry

def test_same_hash_consumed_once(repo):
    expected = _export(repo)
    text = _place(expected, _res(result_status="HUMAN_DECISION_REQUIRED", human_decisions_required=["q?"]))
    _settle(repo)
    for _ in range(3):  # recopy identical bytes (new mtime), repeated scans, direct re-ingest
        expected.write_text(text, encoding="utf-8")
        assert ri.ingest_result_file(repo, "T-1", expected, trigger="AUTO", policy=POLICY).action == "DUPLICATE_SUPPRESSED"
        ri.poll_once(repo, policy=POLICY, now=99.0)
    assert len(_rows(repo)) == 1
    assert len(QuestionQueueStore(repo).list_questions()) == 1
    assert _events(repo).count("RESULT_CONSUMED") == 1
    assert _events(repo).count("DUPLICATE_SUPPRESSED") == 1  # logged once, not per poll


def test_rejected_hash_not_reimported_forever(repo, monkeypatch):
    expected = _export(repo)
    calls = []
    real = wf.import_result
    monkeypatch.setattr(wf, "import_result", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    _place(expected, _res(files_referenced=["dv_harness/engine.py"]))  # forbidden path
    _settle(repo, polls=10)
    assert len(calls) == 1
    ing = ri._load_ing(repo, "T-1")
    entry = next(iter(ing["results"].values()))
    assert entry["import_state"] == "QUARANTINED" and "SCOPE_VIOLATION" in entry["validation_findings"]
    assert entry["retry_eligibility"] == ri.RETRY_ON_CHANGE and entry["rejection_reason"]
    assert ing["auto_import_status"] == "QUARANTINED"
    assert _events(repo).count("RESULT_QUARANTINED") == 1
    assert ec.read_next_action(repo, "T-1")["next_action"] == "AUTO_CLASSIFY_SCOPE_VIOLATION"


def test_forbidden_path_result_rejected(repo):
    expected = _export(repo)
    _place(expected, _res(evidence_refs=["dv_harness/engine.py:1"], files_referenced=[]))
    _settle(repo)
    assert wf.current_state(repo, "T-1") == wf.STATE_RESULT_REJECTED
    assert _rows(repo) == []  # a rejected result is never consumed


def test_changed_result_hash_can_retry_when_authorized(repo):
    expected = _export(repo)
    _place(expected, _res(files_referenced=["dv_harness/engine.py"]))
    _settle(repo)
    assert wf.current_state(repo, "T-1") == wf.STATE_RESULT_REJECTED
    _place(expected, _res())  # the external author corrected the file: new content, new hash
    _settle(repo, start=100.0)
    assert wf.current_state(repo, "T-1") == wf.STATE_RESULT_CONSUMED
    assert len(_rows(repo)) == 1


def test_scheduled_replay_reimports_the_same_hash_exactly_once(repo, monkeypatch):
    expected = _export(repo)
    _place(expected, _res(files_referenced=["dv_harness/engine.py"]))
    _settle(repo)
    sha = ri._load_ing(repo, "T-1")["last_detected_result_sha256"]
    calls = []
    real = wf.import_result
    monkeypatch.setattr(wf, "import_result", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    ri.schedule_replay(repo, "T-1", sha, "validator fixed by Canonical remediation")
    _settle(repo, start=200.0, polls=6)
    assert len(calls) == 1  # replayed once, re-quarantined, not looped
    assert "REPLAY_SCHEDULED" in _events(repo)
    with pytest.raises(ri.IngestionError):
        ri.schedule_replay(repo, "T-1", "0" * 64, "x")


# ------------------------------------------------------------- startup / restart / recovery

def test_startup_scan_imports_pending_result(repo):
    expected = _export(repo)
    _place(expected, _res())  # already present before any watcher exists
    policy = ri.IngestionPolicy(quiet_seconds=0.0, min_observations=2)
    rep = ri.startup_scan(repo, policy=policy, sleep=lambda s: None, timeout_seconds=5)
    assert wf.current_state(repo, "T-1") == wf.STATE_RESULT_CONSUMED
    assert len(_rows(repo)) == 1
    assert rep == [] or rep[-1]["status"] != "OBSERVING"


def test_startup_scan_registers_a_waiting_task_that_has_no_registration(repo):
    expected = _export(repo)
    (repo / ".dv-harness/model_handoffs/T-1/expected_result.json").unlink()
    _place(expected, _res())
    assert ri.list_pending(repo) == []
    ri.startup_scan(repo, policy=ri.IngestionPolicy(quiet_seconds=0.0), sleep=lambda s: None, timeout_seconds=5)
    assert wf.current_state(repo, "T-1") == wf.STATE_RESULT_CONSUMED


def test_restart_preserves_idempotency(repo):
    expected = _export(repo)
    _place(expected, _res(result_status="HUMAN_DECISION_REQUIRED", human_decisions_required=["q?"]))
    _settle(repo)
    import importlib
    importlib.reload(ri)  # a fresh process: no in-memory state at all
    for i in range(3):
        ri.startup_scan(repo, policy=ri.IngestionPolicy(quiet_seconds=0.0), sleep=lambda s: None, timeout_seconds=2)
        ri.poll_once(repo, policy=POLICY, now=500.0 + i)
    assert len(_rows(repo)) == 1
    assert len(QuestionQueueStore(repo).list_questions()) == 1


def test_partial_import_recovery(repo, monkeypatch):
    expected = _export(repo)
    _place(expected, _res())
    real_save = wf._save_state
    fail = {"on": True}

    def flaky(root, tid, st):
        if fail["on"] and st.get("state") == wf.STATE_RESULT_CONSUMED:
            raise OSError("disk full")
        return real_save(root, tid, st)

    monkeypatch.setattr(wf, "_save_state", flaky)
    _settle(repo, polls=4)
    assert wf.current_state(repo, "T-1") == wf.STATE_RESULT_ACCEPTED  # interrupted, inspectable
    assert "AUTO_IMPORT_FAILED_TRANSIENT" in _events(repo)
    fail["on"] = False
    ri.poll_once(repo, policy=POLICY, now=50.0)
    assert wf.current_state(repo, "T-1") == wf.STATE_RESULT_CONSUMED
    assert len(_rows(repo)) == 1


def test_registry_failure_recovery(repo, monkeypatch):
    expected = _export(repo)
    _place(expected, _res(result_status="HUMAN_DECISION_REQUIRED", human_decisions_required=["q?"]))
    real = wf._append_registry
    state = {"fail": True}

    def flaky(*a, **k):
        if state["fail"]:
            raise OSError("registry down")
        return real(*a, **k)

    monkeypatch.setattr(wf, "_append_registry", flaky)
    _settle(repo, polls=3)
    assert _rows(repo) == [] and len(QuestionQueueStore(repo).list_questions()) == 1
    state["fail"] = False
    ri.poll_once(repo, policy=POLICY, now=60.0)
    assert len(_rows(repo)) == 1 and len(QuestionQueueStore(repo).list_questions()) == 1
    assert wf.current_state(repo, "T-1") == wf.STATE_RESULT_CONSUMED


def test_persistent_import_failure_terminates_and_is_never_a_pass(repo, monkeypatch):
    expected = _export(repo)
    _place(expected, _res())
    monkeypatch.setattr(wf, "_append_registry", lambda *a, **k: (_ for _ in ()).throw(OSError("registry down")))
    _settle(repo, polls=12)
    assert "INGESTION_TERMINATED" in _events(repo)
    stop = ec.read_persisted_stop(repo, "T-1")
    assert stop["STOP_REASON"] == "TERMINATION_POLICY_TRIGGERED"
    assert wf.current_state(repo, "T-1") != wf.STATE_RESULT_CONSUMED


def test_change_after_consumption_is_quarantined_not_reimported(repo):
    expected = _export(repo)
    _place(expected, _res())
    _settle(repo)
    expected.write_text(to_markdown(_res(findings=["tampered"])), encoding="utf-8")
    res = ri.ingest_result_file(repo, "T-1", expected, trigger="AUTO", policy=POLICY)
    assert res.action == "LATE_CHANGE_QUARANTINED"
    assert len(_rows(repo)) == 1 and "RESULT_CHANGED_AFTER_CONSUMPTION" in _events(repo)


def test_result_consumed_before_ingestion_records_existed_is_reconciled(repo):
    expected = _export(repo)
    _place(expected, _res())
    wf.import_result(repo, "T-1", expected)  # legacy/manual path, no ingestion identity recorded
    res = ri.ingest_result_file(repo, "T-1", expected, trigger="AUTO", policy=POLICY)
    assert res.action == "DUPLICATE_SUPPRESSED" and len(_rows(repo)) == 1


# ------------------------------------------------------------- correlation

def test_multiple_pending_tasks_do_not_cross_resume(repo):
    a = _export(repo, "T-A")
    b = _export(repo, "T-B")
    _place(a, _res(task_id="T-B"))  # B's result lands at A's expected path
    _settle(repo)
    assert wf.current_state(repo, "T-A") == wf.STATE_RESULT_REJECTED
    assert wf.current_state(repo, "T-B") == wf.STATE_WAITING_FOR_HUMAN_TRANSPORT
    assert _rows(repo, "T-B") == [] and _rows(repo, "T-A") == []
    _place(b, _res(task_id="T-B"))
    _settle(repo, start=100.0)
    assert wf.current_state(repo, "T-B") == wf.STATE_RESULT_CONSUMED
    assert wf.current_state(repo, "T-A") == wf.STATE_RESULT_REJECTED
    assert ec.read_next_action(repo, "T-A")["event"] != "RESULT_CONSUMED"
    assert len(_rows(repo, "T-B")) == 1 and _rows(repo, "T-A") == []


def test_wrong_producer_cannot_resume_the_task(repo):
    expected = _export(repo)
    _place(expected, _res(producer_model="chatgpt"))
    _settle(repo)
    assert wf.current_state(repo, "T-1") == wf.STATE_RESULT_REJECTED


# ------------------------------------------------------------- one shared path / no manual step

def test_manual_and_auto_import_share_ingestion_path(repo, monkeypatch):
    expected = _export(repo)
    seen = []
    real_ingest = ri.ingest_result_file
    real_import = wf.import_result
    monkeypatch.setattr(ri, "ingest_result_file",
                        lambda *a, **k: (seen.append(k.get("trigger")), real_ingest(*a, **k))[1])
    monkeypatch.setattr(wf, "import_result", lambda *a, **k: (seen.append("CANONICAL"), real_import(*a, **k))[1])
    _place(expected, _res())
    _settle(repo)
    assert seen == ["AUTO", "CANONICAL"]
    # the manual verb goes through the very same two layers and is a suppressed duplicate
    seen.clear()
    rc = wf.execute_verb(["import", "--task-id", "T-1", "--result-file", str(expected), "--root", str(repo)])
    assert seen == ["MANUAL"] and rc == 0
    assert len(_rows(repo)) == 1


def test_manual_import_of_a_valid_result_still_works_for_recovery(repo):
    expected = _export(repo)
    _place(expected, _res())
    rc = wf.execute_verb(["import", "--task-id", "T-1", "--result-file", str(expected), "--root", str(repo)])
    assert rc == 0 and wf.current_state(repo, "T-1") == wf.STATE_RESULT_CONSUMED
    assert next(iter(ri._load_ing(repo, "T-1")["results"].values()))["import_state"] == "CONSUMED"


def test_human_manual_import_not_required(repo):
    expected = _export(repo)
    report = ri.transport_stop_report(repo, "T-1")
    assert report["STOP_REASON"] == "HUMAN_TRANSPORT_REQUIRED" and "IMPORT_COMMAND" not in report
    assert report["AUTO_IMPORT"] == "ENABLED" and report["AUTO_RESUME"] == "ENABLED"
    before = json.dumps(ri.status_report(repo))
    assert "WAITING_FOR_USER_TO_IMPORT" not in before
    # the human's whole contribution: the artifact appears at the expected path
    _place(expected, _res())
    _settle(repo)
    after = ri.status_report(repo)
    t = after["TASKS"]["T-1"]
    assert t["WORKFLOW_STATE"] == wf.STATE_RESULT_CONSUMED and t["AUTO_IMPORT_STATUS"] == "DONE"
    assert t["AUTO_RESUME_STATUS"] == "DONE" and t["NEXT_ACTION"] == "AUTO_REMEDIATE_CONFIRMED_FINDINGS"
    assert t["HUMAN_ACTION_REQUIRED"] == "NO" and after["PENDING_EXTERNAL_RESULTS"] == []
    assert "WAITING_FOR_USER_TO_IMPORT" not in json.dumps(after)


def test_waiting_for_user_to_import_is_not_a_valid_stop_reason():
    with pytest.raises(ec.InvalidStopReasonError):
        ec.validate_stop_reason("WAITING_FOR_USER_TO_IMPORT")


# ------------------------------------------------------------- watcher lifecycle

def test_watch_loop_imports_and_reports_a_fresh_heartbeat(repo):
    expected = _export(repo)
    _place(expected, _res())
    ticks = {"t": 0.0}
    policy = ri.IngestionPolicy(quiet_seconds=0.0, min_observations=2, poll_interval_seconds=0.01, idle_exit_seconds=0.0)
    ri.watch(repo, policy=policy, max_iterations=5, sleep=lambda s: None)
    assert wf.current_state(repo, "T-1") == wf.STATE_RESULT_CONSUMED
    rec = json.loads(ri._watcher_file(repo).read_text(encoding="utf-8"))
    assert rec["status"] == "STOPPED" and rec["iterations"] >= 2
    assert "WATCH_STARTED" in _events(repo)


def test_watcher_status_active_recoverable_stopped(repo, tmp_path):
    (repo / ".dv-harness/model_handoffs").mkdir(parents=True)
    assert ri.watcher_status(repo) == "RECOVERABLE"  # never started
    import time
    ri._atomic_write_json(ri._watcher_file(repo), {"last_heartbeat_epoch": time.time(), "status": "ACTIVE"})
    assert ri.watcher_status(repo) == "ACTIVE"
    assert ri.watcher_status(repo, now=time.time() + 3600) == "RECOVERABLE"  # stale heartbeat -> recoverable
    ri._atomic_write_json(ri._watcher_file(repo), {"last_heartbeat_epoch": time.time(), "status": "STOPPED"})
    assert ri.watcher_status(repo) == "STOPPED"


def test_ensure_watcher_never_spawns_a_process_under_the_test_guard(repo):
    assert os.environ["L5DGVA_RESULT_WATCHER"] == "off"
    assert ri.ensure_watcher(repo) == "RECOVERABLE"
    assert not ri._watcher_file(repo).exists()


def test_stop_watcher_is_cooperative(repo):
    _export(repo)
    ri.stop_watcher(repo)
    ri.watch(repo, policy=ri.IngestionPolicy(poll_interval_seconds=0.01), max_iterations=3, sleep=lambda s: None)
    rec = json.loads(ri._watcher_file(repo).read_text(encoding="utf-8"))
    assert rec["status"] == "STOPPED"


def test_direct_write_by_the_external_model_at_the_expected_path_is_detected(repo):
    # Codex working in the same repo writes EXPECTED_RESULT_FILE itself: same detection path,
    # no extra authority is granted to the writer.
    expected = _export(repo)
    with open(expected, "w", encoding="utf-8") as f:
        f.write(to_markdown(_res()))
    _settle(repo)
    assert wf.current_state(repo, "T-1") == wf.STATE_RESULT_CONSUMED


def test_policy_is_configurable_from_a_file(repo):
    (repo / ".dv-harness").mkdir(exist_ok=True)
    (repo / ".dv-harness/result_ingestion_policy.json").write_text(
        json.dumps({"quiet_seconds": 9.5, "max_import_attempts": 7, "unknown_key": 1}), encoding="utf-8")
    p = ri.load_policy(repo)
    assert p.quiet_seconds == 9.5 and p.max_import_attempts == 7 and p.min_observations == 2
