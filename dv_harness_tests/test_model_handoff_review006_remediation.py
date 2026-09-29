"""Adversarial regression tests for Codex's REVIEW-006 findings R006-1..
R006-4, found in a re-review of the REVIEW-005 remediation. Each test
independently reproduces the pre-fix defect shape (via direct construction
or real concurrent threads), without relying on Codex's own claim alone --
per this project's own Evidence Truth Rule."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from unittest import mock

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


# ================================================================ R006-1: takeover staging-window race

def test_third_normal_acquirer_cannot_win_while_a_stale_takeover_evaluation_is_in_progress(repo, monkeypatch):
    """Codex REVIEW-006 R006-1's real 3-role probe, reproduced: stale A
    exists; contender C begins evaluating A for takeover (holding the real
    OS advisory lock mid-evaluation, gated here to a precise point); a
    normal, unrelated acquirer D attempts _acquire_lock() concurrently.
    Under the REVIEW-006 fix (never unlink/rename the canonical lock path)
    the path is never absent, so D's fresh O_CREAT|O_EXCL attempt correctly
    fails (file still exists) and D's own fallback takeover attempt
    correctly fails to acquire the already-held advisory lock -- D can
    never win mid-evaluation, and once C finishes, on-disk content is
    exactly C's own real outcome, never overwritten or corrupted by D
    (the exact defect the pre-fix stage-then-restore design had)."""
    lock = repo / "x.lock"
    token_a = wf._acquire_lock(lock)
    assert token_a is not None
    os.utime(lock, (1_000_000_000, 1_000_000_000))
    monkeypatch.setattr(wf, "_pid_alive", lambda pid: False)

    c_holds_lock = threading.Event()
    release_c = threading.Event()
    real_read = wf._read_lock_snapshot_from_fd

    def gated_read(fd):
        result = real_read(fd)
        c_holds_lock.set()
        assert release_c.wait(timeout=5)
        return result

    monkeypatch.setattr(wf, "_read_lock_snapshot_from_fd", gated_read)

    results = {}

    def run_c():
        results["c"] = wf._acquire_lock(lock, stale_seconds=1.0)

    tc = threading.Thread(target=run_c)
    tc.start()
    assert c_holds_lock.wait(timeout=5)

    # D attempts a normal acquire WHILE C is mid-evaluation, still holding the advisory lock.
    assert lock.exists()
    token_d = wf._acquire_lock(lock, stale_seconds=1.0)
    assert token_d is None  # D can never win while C holds the advisory lock
    assert lock.exists()  # the canonical path was never vacated during C's evaluation

    release_c.set()
    tc.join(timeout=5)
    assert results["c"] is not None
    assert lock.read_text(encoding="utf-8") == results["c"]  # C's real outcome, never overwritten by D
    wf._release_lock(lock, results["c"])
    assert not lock.exists()


def test_real_two_contender_race_admits_exactly_one_winner_never_corrupts_the_lock(repo, monkeypatch):
    """A real-concurrency sibling to the deterministic test above: two
    threads race `_acquire_lock()` against the same stale, dead-owner lock
    with no artificial gating. Exactly one must win; the lock's final
    on-disk content must match that winner's own token -- never lost,
    corrupted, or shared."""
    lock = repo / "x.lock"
    wf._acquire_lock(lock)
    os.utime(lock, (1_000_000_000, 1_000_000_000))
    monkeypatch.setattr(wf, "_pid_alive", lambda pid: False)

    barrier = threading.Barrier(2)
    results = {}

    def contender(name):
        barrier.wait(timeout=5)
        results[name] = wf._acquire_lock(lock, stale_seconds=1.0)

    tb = threading.Thread(target=contender, args=("B",))
    tc = threading.Thread(target=contender, args=("C",))
    tb.start()
    tc.start()
    tb.join(timeout=10)
    tc.join(timeout=10)

    winners = {n: t for n, t in results.items() if t is not None}
    assert len(winners) == 1, f"exactly one contender must win, got {results}"
    (winner_token,) = winners.values()
    assert lock.read_text(encoding="utf-8") == winner_token
    wf._release_lock(lock, winner_token)


def test_stale_takeover_still_requires_a_provably_dead_owner(repo, monkeypatch):
    """The REVIEW-006 redesign must not regress REVIEW-004 R004-2's own
    invariant: a live recorded owner is never taken over, however stale
    the file looks."""
    lock = repo / "x.lock"
    wf._acquire_lock(lock)
    os.utime(lock, (1_000_000_000, 1_000_000_000))
    monkeypatch.setattr(wf, "_pid_alive", lambda pid: True)
    assert wf._acquire_lock(lock, stale_seconds=1.0) is None


def test_malformed_lock_content_still_never_treated_as_proof_of_death(repo, monkeypatch):
    lock = repo / "x.lock"
    lock.write_text("not-a-valid-token", encoding="utf-8")
    os.utime(lock, (1_000_000_000, 1_000_000_000))
    monkeypatch.setattr(wf, "_pid_alive", lambda pid: (_ for _ in ()).throw(
        AssertionError("must never even ask _pid_alive about unparseable content")))
    assert wf._acquire_lock(lock, stale_seconds=1.0) is None
    assert lock.read_text(encoding="utf-8") == "not-a-valid-token"


# ================================================================ R006-2: manifest/stability check-then-reread race

def test_sealed_manifest_verified_bytes_are_what_gets_imported_even_if_file_changes_right_after(repo):
    """REVIEW-006 R006-2 fix, direct proof: `_unsafe_manual_path_reason()`
    threads the manifest-verified byte buffer straight into
    `_ingest_locked()`'s own import step -- it never re-reads the path
    afterward. Simulated here by swapping the file's real on-disk content
    to a DIFFERENT valid result immediately after the real manifest check
    has already run (mirroring Codex's own real interleaving); the
    CONSUMED record must still be the manifest-verified content, never the
    swapped-in one."""
    expected = _export(repo, "T-1")
    expected.write_text(r_to(_res(claims=["result-a"])), encoding="utf-8")
    data_a = expected.read_bytes()
    manifest_path = expected.with_name(expected.name + ".manifest.json")
    manifest_path.write_text(
        json.dumps({"sha256": hashlib.sha256(data_a).hexdigest(), "size": len(data_a)}), encoding="utf-8")

    real_check = ri._sealed_manifest_confirms_completion

    def swap_after_check(path):
        verified = real_check(path)
        if verified is not None:
            path.write_text(r_to(_res(claims=["result-b"], result_status="PASS", findings=[])), encoding="utf-8")
        return verified

    with mock.patch.object(ri, "_sealed_manifest_confirms_completion", side_effect=swap_after_check):
        res = ri.ingest_result_file(repo, "T-1", expected, trigger="MANUAL", policy=FAST_POLICY)

    assert res.action == "IMPORTED"
    assert tuple(res.outcome.result.claims) == ("result-a",)
    assert expected.read_text(encoding="utf-8") != r_to(_res(claims=["result-a"]))  # disk really did change


def test_quiet_interval_verified_bytes_are_what_gets_imported_even_if_file_changes_right_after(repo):
    """Same class of fix, no-manifest path: `_synchronous_stability_check()`
    now returns the actual confirmed bytes, and `_ingest_locked()` imports
    exactly those -- never a fresh, independent re-read that a writer could
    race against after the check already passed."""
    expected = _export(repo, "T-1")
    expected.write_text(r_to(_res(claims=["result-a"])), encoding="utf-8")

    real_check = ri._synchronous_stability_check

    def swap_after_check(path, policy):
        verified = real_check(path, policy)
        if verified is not None:
            path.write_text(r_to(_res(claims=["result-b"], result_status="PASS", findings=[])), encoding="utf-8")
        return verified

    with mock.patch.object(ri, "_synchronous_stability_check", side_effect=swap_after_check):
        res = ri.ingest_result_file(repo, "T-1", expected, trigger="MANUAL", policy=FAST_POLICY)

    assert res.action == "IMPORTED"
    assert tuple(res.outcome.result.claims) == ("result-a",)


# ================================================================ R006-3: registration correlation narrower than claimed

def test_tampered_model_producer_task_type_and_head_are_rejected_despite_correct_task_id_and_path(repo):
    """Codex REVIEW-006 R006-3's real probe, reproduced: every one of the 10
    schema keys present, TASK_ID and EXPECTED_RESULT_FILE both correct, but
    TARGET_MODEL/EXPECTED_PRODUCER changed to "chatgpt", EXPECTED_TASK_TYPE
    to "wrong-type", and CURRENT_HEAD to 40 zeroes. The REVIEW-005 version
    of `_valid_registration()` wrongly accepted this."""
    expected = _export(repo, "T-1")
    reg_path = repo / ".dv-harness/model_handoffs/T-1/expected_result.json"
    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    reg["TARGET_MODEL"] = "chatgpt"
    reg["EXPECTED_PRODUCER"] = "chatgpt"
    reg["EXPECTED_TASK_TYPE"] = "wrong-type"
    reg["CURRENT_HEAD"] = "0" * 40
    reg_path.write_text(json.dumps(reg), encoding="utf-8")
    expected.write_text(r_to(_res()), encoding="utf-8")

    assert ri._valid_registration(reg, repo, "T-1") is False
    res = ri.ingest_result_file(repo, "T-1", expected, trigger="MANUAL", policy=FAST_POLICY)
    assert res.action == "UNREGISTERED_PATH_REFUSED"
    assert res.detail == "MALFORMED_REGISTRATION"


def test_tampered_handoff_file_and_contract_are_also_rejected(repo):
    expected = _export(repo, "T-1")
    reg_path = repo / ".dv-harness/model_handoffs/T-1/expected_result.json"
    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    reg["HANDOFF_FILE"] = "some/other/path.md"
    reg["EXPECTED_RESULT_CONTRACT"] = "SOME_OTHER_SCHEMA"
    assert ri._valid_registration(reg, repo, "T-1") is False


def test_wait_state_is_validated_as_a_known_state_value_not_live_equality(repo):
    """WAIT_STATE legitimately reflects the state AT REGISTRATION TIME, not
    the CURRENT live state -- comparing it against `current_state()` would
    reject every real registration once a result has actually arrived
    (which is exactly when this check runs). It must still reject a bogus
    state name, though."""
    expected = _export(repo, "T-1")
    reg_path = repo / ".dv-harness/model_handoffs/T-1/expected_result.json"
    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    assert reg["WAIT_STATE"] == wf.STATE_WAITING_FOR_HUMAN_TRANSPORT

    # A real result arrives and gets consumed -- current_state() has now
    # moved on, but the ORIGINAL registration must still validate.
    expected.write_text(r_to(_res()), encoding="utf-8")
    res = ri.ingest_result_file(repo, "T-1", expected, trigger="MANUAL", policy=FAST_POLICY)
    assert res.action == "IMPORTED"
    assert wf.current_state(repo, "T-1") == wf.STATE_RESULT_CONSUMED
    assert ri._valid_registration(reg, repo, "T-1") is True  # the ORIGINAL registration, still valid

    bogus = dict(reg, WAIT_STATE="NOT_A_REAL_STATE")
    assert ri._valid_registration(bogus, repo, "T-1") is False


def test_valid_real_registration_still_passes_after_the_correlation_fix(repo):
    expected = _export(repo, "T-1")
    expected.write_text(r_to(_res()), encoding="utf-8")
    res = ri.ingest_result_file(repo, "T-1", expected, trigger="MANUAL", policy=FAST_POLICY)
    assert res.action == "IMPORTED"
