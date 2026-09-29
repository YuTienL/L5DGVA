"""Adversarial regression tests for Codex's REVIEW-005 findings R005-1..
R005-3, found in a re-review of the REVIEW-004 remediation. Each test
independently reproduces the pre-fix defect shape (via direct construction
or real concurrent threads), without relying on Codex's own claim alone --
per this project's own Evidence Truth Rule."""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
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


# ================================================================ R005-1: stale-takeover compare-and-delete race

def test_malformed_lock_content_is_ownership_unknown_never_proof_of_death(repo, monkeypatch):
    """Codex REVIEW-005 R005-1: `_lock_owner_pid()` used to return `-1` for
    unparseable content, and `_pid_alive(-1)` returns `False` -- silently
    turning "I can't tell who owns this" into "the owner is dead". A
    malformed lock must never be taken over on that basis alone."""
    lock = repo / "x.lock"
    lock.write_text("not-a-valid-token-at-all", encoding="utf-8")
    os.utime(lock, (1_000_000_000, 1_000_000_000))  # force staleness
    monkeypatch.setattr(wf, "_pid_alive", lambda pid: (_ for _ in ()).throw(
        AssertionError("must never even ask _pid_alive about unparseable content")))
    token = wf._acquire_lock(lock, stale_seconds=1.0)
    assert token is None
    assert lock.read_text(encoding="utf-8") == "not-a-valid-token-at-all"  # untouched


def test_empty_lock_content_is_ownership_unknown_never_proof_of_death(repo, monkeypatch):
    lock = repo / "x.lock"
    lock.write_text("", encoding="utf-8")
    os.utime(lock, (1_000_000_000, 1_000_000_000))
    monkeypatch.setattr(wf, "_pid_alive", lambda pid: (_ for _ in ()).throw(
        AssertionError("must never even ask _pid_alive about empty content")))
    token = wf._acquire_lock(lock, stale_seconds=1.0)
    assert token is None


# The 3 tests formerly here (`test_content_verified_takeover_refuses_and_
# restores_a_live_lock_that_changed_underneath_it`,
# `test_content_verified_takeover_succeeds_when_content_is_unchanged`,
# `test_real_two_contender_race_never_admits_a_third_writer_or_lock_loss`)
# exercised `_content_verified_takeover()`/`_read_lock_snapshot()` directly.
# Codex's real REVIEW-006 R006-1 finding showed that stage-then-compare
# design itself had a real staging-window race (a third, perfectly normal
# acquirer could win the canonical path while it was briefly vacated for
# staging). Both functions were REMOVED, not patched, by the REVIEW-006 fix
# (`_try_stale_takeover_in_place()`, which never vacates the canonical
# path at all) -- their equivalent, stronger regression coverage now lives
# in `test_model_handoff_review006_remediation.py`
# (`test_third_normal_acquirer_cannot_win_while_a_stale_takeover_evaluation_
# is_in_progress`, `test_real_two_contender_race_admits_exactly_one_winner_
# never_corrupts_the_lock`).


# ================================================================ R005-2: quiet-interval slow-writer race

def test_slow_writer_pausing_longer_than_quiet_interval_can_still_be_consumed_mid_sequence(repo):
    """Codex REVIEW-005 R005-2's own real writer-thread probe, reproduced:
    a writer places a complete, valid INTERMEDIATE result, then pauses
    LONGER than the configured quiet interval before replacing it with a
    different complete, valid FINAL result. `_synchronous_stability_check()`
    only proves two snapshots were equal across `quiet_seconds` -- it
    cannot prove the writer is actually finished. This is a real, currently
    open, DISCLOSED boundary (not fixed by R005-1's unrelated lock change,
    and not silently declared closed) -- closing it needs a producer-side
    completion protocol (atomic rename from an unwatched temp name, or a
    sealed/manifest marker), per Codex's own recommended action, which is a
    separate, larger transport-contract change tracked as a follow-up
    rather than force-fit into this remediation pass."""
    expected = _export(repo, "T-SLOW")
    res_intermediate = _res(task_id="T-SLOW", claims=["intermediate"], findings=["intermediate-finding"])
    res_final = _res(task_id="T-SLOW", claims=["final"], findings=[], result_status="PASS")
    quiet_seconds = FAST_POLICY.quiet_seconds
    pause_seconds = quiet_seconds * 2.4  # deliberately longer than quiet_seconds, per Codex's own probe shape

    expected.write_text(r_to(res_intermediate), encoding="utf-8")
    timer = threading.Timer(pause_seconds, lambda: expected.write_text(r_to(res_final), encoding="utf-8"))
    timer.start()
    try:
        res = ri.ingest_result_file(repo, "T-SLOW", expected, trigger="MANUAL", policy=FAST_POLICY)
    finally:
        timer.join(timeout=5)

    assert res.action == "IMPORTED"
    assert res.outcome is not None and res.outcome.result is not None
    # The real, reproduced defect: the CONSUMED record is the INTERMEDIATE
    # snapshot, even though the writer's real sequence was not finished.
    assert tuple(res.outcome.result.claims) == ("intermediate",)
    # The disk now holds the writer's real final content -- proving the
    # import genuinely happened mid-sequence, not merely a stale read.
    assert expected.read_text(encoding="utf-8") == r_to(res_final)


def test_sealed_manifest_lets_a_producer_skip_quiet_interval_inference_entirely(repo):
    """R005-2 real, bounded improvement: a producer that writes a sealed
    manifest sidecar (sha256 + size) matching the ACTUAL final content
    gives ingestion a positive completion proof, skipping
    `_synchronous_stability_check()`'s sleep-based inference -- verified
    here by timing: under a policy whose quiet_seconds is deliberately
    large, a call WITH a matching manifest returns almost immediately,
    while the pre-existing behavior would have to sleep the full interval."""
    import hashlib
    import time as _time

    expected = _export(repo, "T-1")
    expected.write_text(r_to(_res()), encoding="utf-8")
    # Hash the file's REAL on-disk bytes (never the in-memory string) -- on
    # Windows, text-mode write can translate line endings, so the actual
    # bytes can differ from `content.encode("utf-8")`.
    data = expected.read_bytes()
    manifest_path = expected.with_name(expected.name + ".manifest.json")
    manifest_path.write_text(
        __import__("json").dumps({"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}),
        encoding="utf-8")

    slow_policy = ri.IngestionPolicy(quiet_seconds=5.0, min_observations=2)
    started = _time.monotonic()
    res = ri.ingest_result_file(repo, "T-1", expected, trigger="MANUAL", policy=slow_policy)
    elapsed = _time.monotonic() - started

    assert res.action == "IMPORTED"
    assert elapsed < 2.0, f"sealed manifest should bypass the {slow_policy.quiet_seconds}s quiet sleep, took {elapsed}s"


def test_stale_sealed_manifest_never_authorizes_early_consumption_of_a_newer_unfinished_write(repo):
    """A manifest written against an OLD (intermediate) snapshot must never
    be trusted for content that has since changed -- ingestion falls back
    to ordinary quiet-interval inference, never a manifest-based shortcut,
    when the manifest's recorded digest does not match the file's real
    current bytes."""
    import hashlib

    expected = _export(repo, "T-1")
    expected.write_text(r_to(_res(claims=["intermediate"])), encoding="utf-8")
    intermediate_bytes = expected.read_bytes()  # real on-disk bytes, never the in-memory string
    manifest_path = expected.with_name(expected.name + ".manifest.json")
    manifest_path.write_text(
        __import__("json").dumps({"sha256": hashlib.sha256(intermediate_bytes).hexdigest(),
                                  "size": len(intermediate_bytes)}),
        encoding="utf-8")
    expected.write_text(r_to(_res(claims=["final"], result_status="PASS", findings=[])),
                        encoding="utf-8")  # content changed; manifest now stale/mismatched

    assert ri._sealed_manifest_confirms_completion(expected) is None
    res = ri.ingest_result_file(repo, "T-1", expected, trigger="MANUAL", policy=FAST_POLICY)
    # Falls back to the ordinary (unaffected) quiet-interval path and still
    # succeeds once the file is genuinely quiescent -- the mismatched
    # manifest is simply ignored, never trusted.
    assert res.action == "IMPORTED"
    assert tuple(res.outcome.result.claims) == ("final",)


# ================================================================ R005-3: registration-authenticity gap

def test_empty_registration_stub_is_never_treated_as_a_genuine_registration(repo):
    """Codex REVIEW-005 R005-3: `_unsafe_manual_path_reason()` used to treat
    any successfully-decoded JSON object at `expected_result.json` as proof
    of registration -- `{}` satisfied the presence-only gate as long as the
    caller supplied the hard-coded task result path."""
    expected = _export(repo, "T-1")
    reg_path = repo / ".dv-harness/model_handoffs/T-1/expected_result.json"
    reg_path.write_text("{}", encoding="utf-8")
    expected.write_text(r_to(_res()), encoding="utf-8")

    res = ri.ingest_result_file(repo, "T-1", expected, trigger="MANUAL", policy=FAST_POLICY)
    assert res.action == "UNREGISTERED_PATH_REFUSED"
    assert res.detail == "MALFORMED_REGISTRATION"


def test_registration_copied_from_a_different_task_is_rejected(repo):
    """A registration record that decodes fine but names a DIFFERENT
    task_id (e.g. copied, or written by a bug/race for the wrong task) must
    never satisfy this task's own registration gate merely because a JSON
    object exists at its path."""
    _export(repo, "T-1")
    expected2 = _export(repo, "T-2")
    tampered = dict(ri._read_json(repo / ".dv-harness/model_handoffs/T-1/expected_result.json"))
    (repo / ".dv-harness/model_handoffs/T-2/expected_result.json").write_text(
        __import__("json").dumps(tampered), encoding="utf-8")
    expected2.write_text(r_to(_res(task_id="T-2")), encoding="utf-8")

    res = ri.ingest_result_file(repo, "T-2", expected2, trigger="MANUAL", policy=FAST_POLICY)
    assert res.action == "UNREGISTERED_PATH_REFUSED"
    assert res.detail == "MALFORMED_REGISTRATION"


def test_register_expected_result_replaces_a_malformed_stub_with_a_genuine_registration(repo):
    """`register_expected_result()` must never return a tampered/empty stub
    unchanged merely because SOME object already exists at that path -- it
    must (re)write the real, correlated registration."""
    task_id = "T-STUB"
    _export(repo, task_id)  # real export_handoff() call establishes the real handoff on disk
    stub_path = repo / ".dv-harness/model_handoffs" / task_id / "expected_result.json"
    stub_path.write_text("{}", encoding="utf-8")

    reg = ri.register_expected_result(repo, task_id)
    assert reg.get("TASK_ID") == task_id
    assert all(k in reg for k in ri._REGISTRATION_SCHEMA_FIELDS)
    assert ri._valid_registration(reg, repo, task_id) is True


def test_valid_real_registration_still_passes_unchanged(repo):
    """The fix must not regress the ordinary, legitimate path: a real
    registration produced by `register_expected_result()` itself continues
    to be trusted and ingestion proceeds normally."""
    expected = _export(repo, "T-1")
    expected.write_text(r_to(_res()), encoding="utf-8")
    res = ri.ingest_result_file(repo, "T-1", expected, trigger="MANUAL", policy=FAST_POLICY)
    assert res.action == "IMPORTED"
