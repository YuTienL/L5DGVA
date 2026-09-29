"""Adversarial regression tests for Codex's REVIEW-004 findings R004-1..
R004-4, found in the automatic external result ingestion layer built for
REVIEW-002/003. Each test independently reproduces the pre-fix defect shape
(via the git history / by construction) and proves the fix, without relying
on Codex's own claim alone."""
from __future__ import annotations

import csv
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

import dv_harness.model_handoff_workflow as wf
import dv_harness.result_ingestion as ri
from dv_harness.model_handoff import build_handoff
from dv_harness.model_result import ModelResultV1, to_markdown as r_to
from dv_harness.task_boundary_conformance import TaskBoundary

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git not on PATH")

FAST_POLICY = ri.IngestionPolicy(quiet_seconds=0.05, min_observations=2)


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


def _export(repo: Path, task_id: str = "T-1") -> Path:
    h = build_handoff(repo, task_id=task_id, task_type="review-route", target_model="codex", project_id="P",
                      objective="review",
                      scope=TaskBoundary(task_id=task_id, allowed_path_prefixes=("dv_harness/module_a.py",)),
                      input_evidence_refs=["dv_harness/module_a.py"])
    wf.export_handoff(repo, h)
    return repo / ".dv-harness/model_handoffs" / task_id / "RESULT_V1.md"


def _res(task_id="T-1", **kw) -> ModelResultV1:
    base = dict(result_version="1.0", task_id=task_id, producer_model="codex", task_type="review-route",
                result_status="FAIL", claims=["c"], findings=["f"],
                evidence_refs=["dv_harness/module_a.py:1"], files_referenced=["dv_harness/module_a.py"])
    base.update(kw)
    return ModelResultV1(**base)


def _rows(repo: Path, task="T-1"):
    p = wf._registry_path(repo)
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["task_id"] == task]


# ================================================================ R004-1: path-trust bypass

def test_arbitrary_unregistered_path_is_refused_by_default(repo):
    _export(repo)
    rogue = repo / "attacker_supplied.md"
    rogue.write_text(r_to(_res()), encoding="utf-8")
    res = ri.ingest_result_file(repo, "T-1", rogue, trigger="MANUAL", policy=FAST_POLICY)
    assert res.action == "UNREGISTERED_PATH_REFUSED"
    assert wf.current_state(repo, "T-1") == wf.STATE_WAITING_FOR_HUMAN_TRANSPORT
    assert _rows(repo) == []


def test_manual_import_cli_verb_refuses_an_arbitrary_result_file(repo):
    _export(repo)
    rogue = repo / "attacker_supplied.md"
    rogue.write_text(r_to(_res()), encoding="utf-8")
    rc = wf.execute_verb(["import", "--task-id", "T-1", "--result-file", str(rogue), "--root", str(repo)])
    assert rc == 1
    assert wf.current_state(repo, "T-1") == wf.STATE_WAITING_FOR_HUMAN_TRANSPORT


def test_ingestion_with_no_registration_at_all_is_refused(repo):
    h = build_handoff(repo, task_id="T-2", task_type="review-route", target_model="codex", project_id="P",
                      objective="x", scope=TaskBoundary(task_id="T-2", allowed_path_prefixes=("dv_harness/module_a.py",)),
                      input_evidence_refs=["dv_harness/module_a.py"])
    wf.export_handoff(repo, h)
    (repo / ".dv-harness/model_handoffs/T-2/expected_result.json").unlink()  # simulate no registration
    expected = repo / ".dv-harness/model_handoffs/T-2/RESULT_V1.md"
    expected.write_text(r_to(_res(task_id="T-2")), encoding="utf-8")
    res = ri.ingest_result_file(repo, "T-2", expected, trigger="MANUAL", policy=FAST_POLICY)
    assert res.action == "UNREGISTERED_PATH_REFUSED" and res.detail == "NO_REGISTRATION"


def test_symlinked_manual_path_is_refused(repo, tmp_path):
    _export(repo)
    outside = tmp_path / "outside.md"
    outside.write_text(r_to(_res()), encoding="utf-8")
    link = repo / ".dv-harness/model_handoffs/T-1/RESULT_V1.md"
    try:
        import os
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted")
    res = ri.ingest_result_file(repo, "T-1", link, trigger="MANUAL", policy=FAST_POLICY)
    assert res.action == "UNREGISTERED_PATH_REFUSED" and res.detail == "UNSAFE_FILE"


def test_empty_manual_result_file_is_refused(repo):
    expected = _export(repo)
    expected.write_text("", encoding="utf-8")
    res = ri.ingest_result_file(repo, "T-1", expected, trigger="MANUAL", policy=FAST_POLICY)
    assert res.action == "UNREGISTERED_PATH_REFUSED" and res.detail == "EMPTY_FILE"


def test_manual_partial_write_is_refused_by_the_synchronous_stability_check(repo):
    expected = _export(repo)
    full_text = r_to(_res())
    expected.write_text(full_text[: len(full_text) // 2], encoding="utf-8")

    def _finish_write_mid_check():
        time.sleep(0.02)
        expected.write_text(full_text, encoding="utf-8")

    t = threading.Thread(target=_finish_write_mid_check)
    t.start()
    res = ri.ingest_result_file(repo, "T-1", expected, trigger="MANUAL",
                                policy=ri.IngestionPolicy(quiet_seconds=0.1, min_observations=2))
    t.join()
    assert res.action == "UNREGISTERED_PATH_REFUSED" and res.detail == "NOT_STABLE"
    assert wf.current_state(repo, "T-1") == wf.STATE_WAITING_FOR_HUMAN_TRANSPORT


def test_the_real_registered_expected_path_is_still_accepted_manually(repo):
    expected = _export(repo)
    expected.write_text(r_to(_res()), encoding="utf-8")
    res = ri.ingest_result_file(repo, "T-1", expected, trigger="MANUAL", policy=FAST_POLICY)
    assert res.action == "IMPORTED" and res.outcome.consumed
    assert wf.current_state(repo, "T-1") == wf.STATE_RESULT_CONSUMED


def test_explicit_override_still_permits_a_documented_recovery_path(repo, tmp_path):
    _export(repo)
    recovery_copy = tmp_path / "recovered_result.md"
    recovery_copy.write_text(r_to(_res()), encoding="utf-8")
    res = ri.ingest_result_file(repo, "T-1", recovery_copy, trigger="MANUAL",
                                allow_unregistered_path=True, policy=FAST_POLICY)
    assert res.action == "IMPORTED" and res.outcome.consumed


def test_auto_watcher_path_is_unaffected_by_the_new_gate(repo):
    expected = _export(repo)
    expected.write_text(r_to(_res()), encoding="utf-8")
    for i in range(4):
        ri.poll_once(repo, policy=FAST_POLICY, now=i * 0.1)
    assert wf.current_state(repo, "T-1") == wf.STATE_RESULT_CONSUMED


# ================================================================ R004-2: lock ownership race

def test_lock_carries_a_real_unique_owner_token_not_a_bare_pid(repo):
    lock = repo / "x.lock"
    token = wf._acquire_lock(lock)
    assert token is not None and ":" in token
    assert lock.read_text(encoding="utf-8") == token
    wf._release_lock(lock, token)
    assert not lock.exists()


def test_release_cannot_remove_a_lock_it_does_not_own(repo):
    lock = repo / "x.lock"
    token_a = wf._acquire_lock(lock)
    assert token_a is not None
    wf._release_lock(lock, "some-other-token:999")  # a different, wrong token
    assert lock.exists()  # the real owner's lock survives an owner-blind release attempt
    wf._release_lock(lock, token_a)
    assert not lock.exists()


def test_stale_takeover_requires_the_recorded_owner_to_be_provably_dead(repo, monkeypatch):
    lock = repo / "x.lock"
    token_a = wf._acquire_lock(lock)
    assert token_a is not None
    import os
    os.utime(lock, (1_000_000_000, 1_000_000_000))  # force staleness
    monkeypatch.setattr(wf, "_pid_alive", lambda pid: True)  # but the recorded owner IS alive
    token_b = wf._acquire_lock(lock, stale_seconds=1.0)
    assert token_b is None  # never taken over from a live owner, however stale the file looks


def test_stale_takeover_succeeds_only_once_the_owner_is_provably_dead(repo, monkeypatch):
    lock = repo / "x.lock"
    token_a = wf._acquire_lock(lock)
    import os
    os.utime(lock, (1_000_000_000, 1_000_000_000))
    monkeypatch.setattr(wf, "_pid_alive", lambda pid: False)
    token_b = wf._acquire_lock(lock, stale_seconds=1.0)
    assert token_b is not None and token_b != token_a
    wf._release_lock(lock, token_b)


def test_a_third_writer_cannot_be_admitted_by_two_sequential_owner_blind_releases(repo, monkeypatch):
    """The exact race Codex described: process A holds, B takes over a stale
    lock, A's own (now-stale) release call must never remove B's real lock."""
    lock = repo / "x.lock"
    token_a = wf._acquire_lock(lock)
    import os
    os.utime(lock, (1_000_000_000, 1_000_000_000))
    monkeypatch.setattr(wf, "_pid_alive", lambda pid: False)
    token_b = wf._acquire_lock(lock, stale_seconds=1.0)
    assert token_b is not None
    # A (unaware it was ever superseded) tries to release using its OWN old token.
    wf._release_lock(lock, token_a)
    assert lock.exists() and lock.read_text(encoding="utf-8") == token_b  # B's lock is untouched
    token_c = wf._acquire_lock(lock)  # no third writer can sneak in while B holds it
    assert token_c is None
    wf._release_lock(lock, token_b)


# ================================================================ R004-3: cross-task registry race

def test_two_different_tasks_consuming_concurrently_each_get_exactly_one_row(repo):
    exports = {t: _export(repo, t) for t in ("T-A", "T-B", "T-C")}
    for t, rp in exports.items():
        rp.write_text(r_to(_res(task_id=t)), encoding="utf-8")

    errors = []

    def _consume(task_id, rp):
        try:
            wf.import_result(repo, task_id, rp)
        except Exception as exc:  # pragma: no cover - failure surfaced via `errors`
            errors.append((task_id, exc))

    threads = [threading.Thread(target=_consume, args=(t, rp)) for t, rp in exports.items()]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=30)

    assert not errors, errors
    for t in exports:
        assert wf.current_state(repo, t) == wf.STATE_RESULT_CONSUMED
        assert len(_rows(repo, t)) == 1
    with open(wf._registry_path(repo), newline="", encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))
    assert len(all_rows) == 3  # no lost, corrupted, or duplicated rows
    assert len({r["task_id"] for r in all_rows}) == 3


def test_registry_migration_uses_a_unique_temp_filename(repo):
    legacy = ["task_id", "target_model", "task_type", "state", "result_status", "handoff_path", "result_path",
              "consumed_at_head", "question_id"]
    reg = wf._registry_path(repo)
    reg.parent.mkdir(parents=True, exist_ok=True)
    with open(reg, "w", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=legacy).writeheader()
    with wf._registry_lock(repo):
        wf._ensure_registry_schema(reg)
    leftover_tmp = list(reg.parent.glob("*.migrate.*.tmp"))
    assert leftover_tmp == []  # os.replace() consumed the unique temp file, nothing left behind
    with open(reg, newline="", encoding="utf-8") as f:
        assert list(csv.DictReader(f).fieldnames) == wf._REGISTRY_FIELDS


def test_registry_lock_serializes_concurrent_appends_without_a_shared_fixed_temp_name(repo, monkeypatch):
    real_ensure = wf._ensure_registry_schema
    calls = []

    def slow_ensure(path):
        calls.append(1)
        time.sleep(0.05)  # widen the race window
        return real_ensure(path)

    monkeypatch.setattr(wf, "_ensure_registry_schema", slow_ensure)
    exports = {t: _export(repo, t) for t in ("T-A", "T-B")}
    for t, rp in exports.items():
        rp.write_text(r_to(_res(task_id=t)), encoding="utf-8")
    threads = [threading.Thread(target=wf.import_result, args=(repo, t, rp)) for t, rp in exports.items()]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=30)
    with open(wf._registry_path(repo), newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2 and len({r["task_id"] for r in rows}) == 2


# ================================================================ R004-4: reconciliation identity

def test_reconciliation_matches_the_real_persisted_consumed_digest(repo):
    expected = _export(repo)
    expected.write_text(r_to(_res()), encoding="utf-8")
    ri.ingest_result_file(repo, "T-1", expected, trigger="AUTO", policy=FAST_POLICY)  # real consumption
    ing_state_path = repo / ".dv-harness/model_handoffs/T-1/ingestion_state.json"
    ing_state_path.unlink()  # simulate: consumed through a path that predates ingestion records
    res = ri.ingest_result_file(repo, "T-1", expected, trigger="AUTO", policy=FAST_POLICY)
    assert res.action == "DUPLICATE_SUPPRESSED" and res.detail == "RECONCILED"
    entry = ri._load_ing(repo, "T-1")["results"][res.sha256]
    assert entry["note"] == "RECONCILED_DIGEST_VERIFIED"


def test_reconciliation_quarantines_a_hash_that_does_not_match_the_real_consumed_digest(repo):
    expected = _export(repo)
    expected.write_text(r_to(_res(findings=["original"])), encoding="utf-8")
    ri.ingest_result_file(repo, "T-1", expected, trigger="AUTO", policy=FAST_POLICY)
    (repo / ".dv-harness/model_handoffs/T-1/ingestion_state.json").unlink()
    expected.write_text(r_to(_res(findings=["a different result entirely"])), encoding="utf-8")
    res = ri.ingest_result_file(repo, "T-1", expected, trigger="AUTO", policy=FAST_POLICY)
    assert res.action == "LATE_CHANGE_QUARANTINED"
    entry = ri._load_ing(repo, "T-1")["results"][res.sha256]
    assert entry["import_state"] == ri.H_QUARANTINED
    assert entry["rejection_reason"] == "RECONCILIATION_DIGEST_MISMATCH"
    assert len(_rows(repo)) == 1  # the real, originally-consumed row is untouched


def test_reconciliation_without_any_persisted_digest_falls_back_honestly(repo, monkeypatch):
    expected = _export(repo)
    expected.write_text(r_to(_res()), encoding="utf-8")
    ri.ingest_result_file(repo, "T-1", expected, trigger="AUTO", policy=FAST_POLICY)
    (repo / ".dv-harness/model_handoffs/T-1/ingestion_state.json").unlink()
    monkeypatch.setattr(ri, "_real_consumed_digest", lambda root, task_id: None)  # pre-digest-era state
    res = ri.ingest_result_file(repo, "T-1", expected, trigger="AUTO", policy=FAST_POLICY)
    assert res.action == "DUPLICATE_SUPPRESSED" and res.detail == "RECONCILED"
    entry = ri._load_ing(repo, "T-1")["results"][res.sha256]
    assert entry["note"] == "RECONCILED_FROM_WORKFLOW_STATE"
