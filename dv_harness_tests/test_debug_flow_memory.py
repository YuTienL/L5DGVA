"""Tests for Workstream 3 of 4 (obsidian-memory-debugflow, 2026-09-03):
debug-flow memory integration, regression-job memory extraction, Git commit
policy, and session save/restore integration built on top of Workstream 1's
`dv_harness/memory_vault.py` foundational layer (see
`.work/obsidian-memory-core-report.md`) and Workstream 2's CLI/skill/
security additions.

Covers:
  - Phase 10/11 shared interface (`dv_harness/memory_vault.py`):
    `build_failure_signature()` / `search_related_memory_for_debug()`.
  - Phase 13 -- Git Integration: vault write-through extended to JOB_MEMORY/
    PROJECT_MEMORY ("verified Job result"/"Project Memory update"), the real
    `memory(<protocol>): <short description>` commit-message policy, and the
    `knowledge_commit_sha` write-back onto the underlying JSON MemoryStore
    record for traceability.
  - Phase 10 engine.py wiring: FAILURE_RECOVERY's BEFORE prior-evidence
    surfacing (`vault_related_cases`), the FAIL/PARTIAL AFTER Job-Memory-only
    hook, and RE_AUDIT PASS's extended verified_fix record (git_sha/test/
    result) + `promote_to_organizational()` trigger.
  - Phase 11 lsf_client.py wiring: a real UVM_ERROR/UVM_FATAL/abnormal-
    termination terminal reconcile attaches a failure signature + prior
    related knowledge onto the job_failure record.

Session save/restore round-trip tests for Phase 14 live in
`test_session_and_info.py` (the file that already owns session_snapshot.py
coverage) -- see its "Phase 14 extension" section, not duplicated here.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from dv_harness import memory_vault as mv
from dv_harness.memory import MemoryStore
from dv_harness.memory_router import (
    route_and_store, _build_vault_commit_message, _write_back_knowledge_commit_sha,
    _VAULT_WRITE_THROUGH_DESTINATIONS,
)

def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


def _rmtree(path: Path) -> None:
    def _on_rm_error(func, p, exc_info):
        import os as _os, stat as _stat
        _os.chmod(p, _stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=_on_rm_error)


_NO_SHARE_CFG = {"knowledge_center": {"enabled": False},
                  "memory": {"vault_path": "", "obsidian_cli": "disabled", "git_enabled": False}}


# ---------------------------------------------------------------------------
# Phase 10/11 shared interface: build_failure_signature / search_related_
# memory_for_debug (dv_harness/memory_vault.py)
# ---------------------------------------------------------------------------

def test_build_failure_signature_derives_abnormal_termination_honestly():
    sig = mv.build_failure_signature(protocol="USB2", pattern="t1", symptom="ep0 timeout",
                                      uvm_fatal_count=1)
    assert sig["abnormal_termination"] is True
    assert sig["protocol"] == "USB2"

    sig2 = mv.build_failure_signature(pattern="t2", uvm_error_count=3)
    assert sig2["abnormal_termination"] is False  # errors alone (no fatal/crash/EXIT) are not abnormal termination

    sig3 = mv.build_failure_signature(lsf_status="EXIT")
    assert sig3["abnormal_termination"] is True

    sig4 = mv.build_failure_signature(terminal_signature="SIGSEGV")
    assert sig4["abnormal_termination"] is True


def test_search_related_memory_for_debug_empty_signature_returns_no_results_not_everything():
    # An empty query would otherwise mean "list everything in the vault" per
    # FileSystemMarkdownAdapter.search()'s own convention -- deliberately
    # NOT useful prior evidence for a specific failure with no real signal
    # yet, so this must short-circuit to an honest empty result instead.
    tmp = _tmp()
    try:
        # Seed one real note so "list everything" would have something to
        # wrongly return if the empty-query guard were absent.
        fs = mv.FileSystemMarkdownAdapter(tmp / "vault", git_enabled=False)
        fs.create({"id": "MEM-1", "memory_level": "engineering", "protocol": "USB2",
                   "status": "ACTIVE", "confidence": "HIGH",
                   "created": "2026-09-03T00:00:00+00:00", "updated": "2026-09-03T00:00:00+00:00"})
        cfg = {**_NO_SHARE_CFG, "memory": {"vault_path": str(tmp / "vault"), "obsidian_cli": "disabled",
                                            "git_enabled": False}}
        sig = mv.build_failure_signature()
        result = mv.search_related_memory_for_debug(tmp, cfg, sig)
        assert result["ok"] is True
        assert result["related_cases"] == []
        assert result["count"] == 0
    finally:
        _rmtree(tmp)


def test_search_related_memory_for_debug_finds_a_real_vault_note_ranked():
    tmp = _tmp()
    try:
        vault = tmp / "vault"
        fs = mv.FileSystemMarkdownAdapter(vault, git_enabled=False)
        fs.create({"id": "MEM-EP0", "memory_level": "engineering", "protocol": "USB2",
                   "status": "ACTIVE", "confidence": "HIGH", "failure": "ep0 fifo underrun",
                   "created": "2026-09-03T00:00:00+00:00", "updated": "2026-09-03T00:00:00+00:00"},
                  sections={"Root Cause": "missing prefetch guard on GET_DESCRIPTOR"})
        fs.create({"id": "MEM-UNRELATED", "memory_level": "engineering", "protocol": "PCIe",
                   "status": "ACTIVE", "confidence": "LOW", "failure": "link training timeout",
                   "created": "2026-09-03T00:00:00+00:00", "updated": "2026-09-03T00:00:00+00:00"})

        cfg = {"memory": {"vault_path": str(vault), "obsidian_cli": "disabled", "git_enabled": False}}
        # The search term must be a literal substring of the target note's
        # real text -- FileSystemMarkdownAdapter's optional `rg` prefilter
        # (see its own docstring) treats a multi-word query as one fixed
        # exact-substring term, not OR'd tokens, so "ep0 fifo underrun"
        # (verbatim in MEM-EP0's `failure` field) is used here rather than a
        # paraphrase that would legitimately find nothing.
        sig = mv.build_failure_signature(protocol="USB2", symptom="ep0 fifo underrun")
        result = mv.search_related_memory_for_debug(tmp, cfg, sig, limit=5)
        assert result["ok"] is True
        note_ids = [c["frontmatter"]["id"] for c in result["related_cases"]]
        assert "MEM-EP0" in note_ids
        assert "MEM-UNRELATED" not in note_ids
    finally:
        _rmtree(tmp)


def test_search_related_memory_for_debug_never_raises_on_provider_failure():
    tmp = _tmp()
    try:
        with patch.object(mv, "get_active_provider", side_effect=RuntimeError("boom")):
            sig = mv.build_failure_signature(symptom="anything")
            result = mv.search_related_memory_for_debug(tmp, {}, sig)
        assert result["ok"] is False
        assert result["related_cases"] == []
        assert result["error"] == "MEMORY_SEARCH_FAILED"
    finally:
        _rmtree(tmp)


# ---------------------------------------------------------------------------
# Phase 13 -- Git Integration: JOB_MEMORY/PROJECT_MEMORY vault write-through,
# commit-message policy, knowledge_commit_sha write-back
# ---------------------------------------------------------------------------

def test_vault_write_through_destinations_include_job_and_project_but_not_working():
    assert _VAULT_WRITE_THROUGH_DESTINATIONS == {"JOB_MEMORY", "PROJECT_MEMORY"}


def test_build_vault_commit_message_format():
    msg = _build_vault_commit_message({"protocol": "USB2", "title": "Verified fix: ep0 underrun"})
    assert msg == "memory(USB2): Verified fix: ep0 underrun"

    # No real protocol on the record -- "_general" fallback, never fabricated.
    msg2 = _build_vault_commit_message({"root_cause": "missing guard"})
    assert msg2 == "memory(_general): missing guard"


def test_route_and_store_job_memory_writes_a_vault_note_under_job_folder():
    tmp = _tmp()
    try:
        cfg = {**_NO_SHARE_CFG, "memory": {"vault_path": str(tmp / "vault"), "obsidian_cli": "disabled",
                                            "git_enabled": False}}
        result = route_and_store(tmp, {
            "kind": "job_failure", "job_id": 7, "pattern": "usb_ep0_timeout",
            "protocol": "USB2", "title": "LSF job 7 reached EXIT",
        }, cfg=cfg)
        assert result["destination"] == "JOB_MEMORY"
        vault = result["vault_write"]
        assert vault["ok"] is True
        assert vault["path"].replace("\\", "/").startswith("06_Agent_Memory/Job/")
    finally:
        _rmtree(tmp)


def test_route_and_store_project_memory_writes_a_vault_note_under_project_folder():
    tmp = _tmp()
    try:
        cfg = {**_NO_SHARE_CFG, "memory": {"vault_path": str(tmp / "vault"), "obsidian_cli": "disabled",
                                            "git_enabled": False}}
        result = route_and_store(tmp, {
            "kind": "project_fact", "verified": True, "title": "vPlan finalized: 12 items",
            "protocol": "USB2",
        }, cfg=cfg)
        assert result["destination"] == "PROJECT_MEMORY"
        vault = result["vault_write"]
        assert vault["ok"] is True
        assert vault["path"].replace("\\", "/").startswith("06_Agent_Memory/Project/")
    finally:
        _rmtree(tmp)


def test_route_and_store_working_memory_never_writes_a_vault_note():
    # The user's spec's explicit negative: "NOT on every Working Memory
    # update" -- satisfied by construction (WORKING_MEMORY is absent from
    # _VAULT_WRITE_THROUGH_DESTINATIONS and has no dedicated branch either).
    tmp = _tmp()
    try:
        cfg = {**_NO_SHARE_CFG, "memory": {"vault_path": str(tmp / "vault"), "obsidian_cli": "disabled",
                                            "git_enabled": False}}
        result = route_and_store(tmp, {"kind": "react_reasoning_step", "hypothesis": "h"}, cfg=cfg)
        assert result["destination"] == "WORKING_MEMORY"
        assert "vault_write" not in result
        assert not (tmp / "vault" / "06_Agent_Memory" / "Working").exists() or not any(
            (tmp / "vault" / "06_Agent_Memory" / "Working").iterdir())
    finally:
        _rmtree(tmp)


def test_write_back_knowledge_commit_sha_patches_the_real_local_record():
    tmp = _tmp()
    try:
        mem = MemoryStore(tmp).add("engineering", {"title": "t", "root_cause": "rc"})
        _write_back_knowledge_commit_sha(tmp, mem, {"ok": True, "knowledge_commit_sha": "deadbeef"})
        reloaded = MemoryStore(tmp).get(mem["memory_id"])
        assert reloaded["knowledge_commit_sha"] == "deadbeef"
        # rtl_sha/tb_sha-style traceability field, never touching the rest of
        # the record's own real content.
        assert reloaded["root_cause"] == "rc"
    finally:
        _rmtree(tmp)


def test_write_back_knowledge_commit_sha_is_a_no_op_without_a_real_sha():
    tmp = _tmp()
    try:
        mem = MemoryStore(tmp).add("engineering", {"title": "t"})
        before = MemoryStore(tmp).get(mem["memory_id"])
        _write_back_knowledge_commit_sha(tmp, mem, {"ok": True})  # no knowledge_commit_sha key
        after = MemoryStore(tmp).get(mem["memory_id"])
        assert after == before
    finally:
        _rmtree(tmp)


def test_engineering_memory_promotion_gets_a_real_knowledge_commit_sha_when_git_enabled():
    if shutil.which("git") is None:
        pytest.skip("git not installed on this machine")
    tmp = _tmp()
    try:
        cfg = {**_NO_SHARE_CFG, "memory": {"vault_path": str(tmp / "vault"), "obsidian_cli": "disabled",
                                            "git_enabled": True}}
        result = route_and_store(tmp, {
            "kind": "verified_fix", "verified": True, "protocol": "USB2",
            "title": "Verified fix: ep0 underrun", "root_cause": "missing prefetch guard",
            "confidence": "HIGH", "evidence": ["sim.log:8821 UVM_ERROR ep0 underrun"],
        }, cfg=cfg)
        assert result["vault_write"]["ok"] is True
        assert result["vault_write"].get("knowledge_commit_sha")

        rec = MemoryStore(tmp).get(result["memory_id"])
        assert rec["knowledge_commit_sha"] == result["vault_write"]["knowledge_commit_sha"]

        import subprocess
        log = subprocess.run(["git", "log", "--oneline"], cwd=str(tmp / "vault"),
                              capture_output=True, text=True)
        assert "memory(USB2):" in log.stdout
    finally:
        _rmtree(tmp)


# ---------------------------------------------------------------------------
# Phase 10 engine.py wiring: FAILURE_RECOVERY BEFORE prior-evidence surfacing
# + FAIL/PARTIAL AFTER Job-Memory-only hook
# ---------------------------------------------------------------------------

def test_failure_recovery_surfaces_vault_related_cases_as_prior_evidence_only():
    from dv_harness.engine import DVHarness
    from dv_harness.adapters.base import AgentResult
    tmp = _tmp()
    try:
        vault = tmp / "vault"
        fs = mv.FileSystemMarkdownAdapter(vault, git_enabled=False)
        fs.create({"id": "MEM-PRIOR", "memory_level": "engineering", "protocol": "USB2",
                   "status": "ACTIVE", "confidence": "HIGH", "failure": "ep0 fifo underrun prior case",
                   "created": "2026-09-03T00:00:00+00:00", "updated": "2026-09-03T00:00:00+00:00"})

        h = DVHarness(tmp)
        h.cfg["memory"] = {"vault_path": str(vault), "obsidian_cli": "disabled", "git_enabled": False}
        h.cfg["policy"]["require_stage_gate_evidence"] = False  # this test is about the PROMPT, not the verdict

        captured = {}

        class _CaptureAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                captured["prompt"] = prompt
                return AgentResult(ok=True, text="ok", raw={}, session_id=None)

        h.adapter = _CaptureAdapter()
        h.set_stage("FAILURE_RECOVERY")
        h.run_stage("ep0 fifo underrun prior case")

        prompt = captured["prompt"]
        assert "DV-Knowledge Vault" in prompt
        assert "MEM-PRIOR" in prompt
        # CLAUDE.md Evidence Truth Rule disclaimer -- prior evidence, not an
        # assumed answer.
        assert "不得直接假設 previous root cause == current root cause" in prompt
    finally:
        _rmtree(tmp)


def test_failure_recovery_partial_attempt_writes_job_memory_only_never_engineering_memory():
    from dv_harness.engine import DVHarness
    from dv_harness.adapters.base import AgentResult
    tmp = _tmp()
    try:
        h = DVHarness(tmp)

        class _NoEvidenceAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text="looked into it, no conclusive evidence yet.",
                                    raw={}, session_id=None)

        h.adapter = _NoEvidenceAdapter()
        h.set_stage("FAILURE_RECOVERY")
        h.run_stage("debug ep0 timeout")

        # FAILURE_RECOVERY has 4 mandatory gates and this response supplies
        # none of them -- MISSING_EVIDENCE -> PARTIAL (no graph node, so no
        # InnerReactLoop retries to reach a different verdict).
        assert h.state.stages["FAILURE_RECOVERY"]["status"] == "PARTIAL"

        mem = MemoryStore(tmp)
        job_rows = [r for r in mem._index() if r.get("level") == "job"]
        assert job_rows, "expected a real Job Memory record for the failed/partial debug attempt"
        assert job_rows[0]["title"].startswith("FAILURE_RECOVERY attempt")

        eng_rows = [r for r in mem._index() if r.get("level") == "engineering"]
        assert not eng_rows, ("a debug attempt that did NOT close with PASS must never promote to "
                               "Engineering Memory -- 'on FAIL, update Job Memory only (no promotion)'")
    finally:
        _rmtree(tmp)


def test_re_audit_pass_writes_no_job_memory_record_only_engineering():
    # The symmetric counterpart: a genuine PASS must NOT ALSO write the
    # FAIL/PARTIAL Job Memory record -- the two AFTER branches are mutually
    # exclusive on ss["status"].
    from dv_harness.engine import DVHarness
    from dv_harness.adapters.base import AgentResult
    tmp = _tmp()
    try:
        h = DVHarness(tmp)
        h.cfg["policy"]["require_stage_gate_evidence"] = False
        h.cfg["memory"] = {"vault_path": str(tmp / "vault"), "obsidian_cli": "disabled", "git_enabled": False}

        class _PassAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text="fine", raw={}, session_id=None)

        h.adapter = _PassAdapter()
        h.set_stage("RE_AUDIT")
        h.run_stage("goal")
        assert h.state.stages["RE_AUDIT"]["status"] == "PASS"

        mem = MemoryStore(tmp)
        assert not [r for r in mem._index() if r.get("level") == "job"]
    finally:
        _rmtree(tmp)


# ---------------------------------------------------------------------------
# Phase 11 lsf_client.py wiring: regression-job failure signature + prior
# related knowledge on a real UVM_ERROR/UVM_FATAL/abnormal-termination signal
# ---------------------------------------------------------------------------

def test_terminal_reconcile_job_failure_attaches_failure_signature_and_prior_knowledge():
    from dv_harness.lsf_client import (
        JobState, save_job_state, reconcile_job, _write_job_tier_memory_on_terminal_reconcile,
    )
    tmp = _tmp()
    try:
        vault = tmp / "vault"
        fs = mv.FileSystemMarkdownAdapter(vault, git_enabled=False)
        fs.create({"id": "MEM-PRIOR-USB", "memory_level": "engineering", "protocol": "USB2",
                   "status": "ACTIVE", "confidence": "HIGH", "failure": "usb_ep0_timeout prior fatal",
                   "created": "2026-09-03T00:00:00+00:00", "updated": "2026-09-03T00:00:00+00:00"})
        (tmp / ".dv-harness" / "config.json").parent.mkdir(parents=True, exist_ok=True)
        (tmp / ".dv-harness" / "config.json").write_text(json.dumps({
            "memory": {"vault_path": str(vault), "obsidian_cli": "disabled", "git_enabled": False},
        }), encoding="utf-8")

        state = JobState(job_id=42, pattern="usb_ep0_timeout prior fatal", lsf_status="RUN",
                          sim_status="RUNNING", uvm_fatal_count=1)
        save_job_state(tmp, state)
        state, discrepancies = reconcile_job(state, {"JOBID": "42", "STAT": "DONE"})
        _write_job_tier_memory_on_terminal_reconcile(tmp, 42, state, discrepancies)

        rec = MemoryStore(tmp).get("JOB-42-TERMINAL-RECONCILE")
        assert rec["kind"] == "job_failure"
        assert rec["failure_signature"]["uvm_fatal_count"] == 1
        assert rec["failure_signature"]["abnormal_termination"] is True
        related_ids = [c["frontmatter"]["id"] for c in rec.get("prior_related_knowledge", [])]
        assert "MEM-PRIOR-USB" in related_ids
    finally:
        _rmtree(tmp)


def test_terminal_reconcile_job_result_never_searches_prior_knowledge():
    # A plain job_result (no real failure signal) must never attach a
    # failure_signature/prior_related_knowledge -- searching would be noise,
    # and this is exactly the `is_failure` guard's negative case.
    from dv_harness.lsf_client import JobState, save_job_state, reconcile_job, \
        _write_job_tier_memory_on_terminal_reconcile
    tmp = _tmp()
    try:
        state = JobState(job_id=43, pattern="clean_pass", lsf_status="RUN", sim_status="RUNNING")
        save_job_state(tmp, state)
        state, discrepancies = reconcile_job(state, {"JOBID": "43", "STAT": "DONE"})
        with patch("dv_harness.memory_vault.search_related_memory_for_debug") as mock_search:
            _write_job_tier_memory_on_terminal_reconcile(tmp, 43, state, discrepancies)
        assert not mock_search.called

        rec = MemoryStore(tmp).get("JOB-43-TERMINAL-RECONCILE")
        assert rec["kind"] == "job_result"
        assert "failure_signature" not in rec
        assert "prior_related_knowledge" not in rec
    finally:
        _rmtree(tmp)


def test_terminal_reconcile_memory_search_failure_never_blocks_the_job_memory_write():
    from dv_harness.lsf_client import JobState, save_job_state, reconcile_job, \
        _write_job_tier_memory_on_terminal_reconcile
    tmp = _tmp()
    try:
        state = JobState(job_id=44, pattern="crashy", lsf_status="EXIT", sim_status="RUNNING")
        save_job_state(tmp, state)
        state, discrepancies = reconcile_job(state, {"JOBID": "44", "STAT": "EXIT"})
        with patch("dv_harness.memory_vault.search_related_memory_for_debug",
                   side_effect=RuntimeError("boom")):
            _write_job_tier_memory_on_terminal_reconcile(tmp, 44, state, discrepancies)

        rec = MemoryStore(tmp).get("JOB-44-TERMINAL-RECONCILE")
        assert rec is not None
        assert rec["kind"] == "job_failure"
    finally:
        _rmtree(tmp)


# ---------------------------------------------------------------------------
# Phase 13 traceability: a vault commit that was EXPECTED but silently did not
# happen (2026-09-04 gap close). Observed for real: a full-suite run under
# machine load produced `knowledge_commit_sha: None` on a promotion whose note
# was genuinely new -- i.e. NOTHING_TO_COMMIT was impossible -- while the same
# test passed in isolation. `_run_git()`'s blanket except made a transient git
# failure indistinguishable from "nothing changed", with no retry and no
# signal, so a verified promotion could lose its traceability pointer silently.
# ---------------------------------------------------------------------------

def _git_repo(tmp: Path) -> Path:
    vault = tmp / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    assert mv._ensure_git_repo(vault) is True
    return vault


def _commit_fails_n_times(n: int):
    """Fails only `git commit`, only the first `n` times, exactly the way a
    real transient failure presents (`_run_git_ex` returning no process at
    all). Every other git invocation runs for real, so the retry that follows
    is a REAL commit against a REAL repo, not a mocked success."""
    real = mv._run_git_ex
    state = {"left": n, "commit_calls": 0}

    def fake(vault_path, args, timeout=10):
        if args and args[0] == "commit":
            state["commit_calls"] += 1
            if state["left"] > 0:
                state["left"] -= 1
                return None, "TimeoutExpired: git commit timed out after 10 seconds"
        return real(vault_path, args, timeout=timeout)

    return fake, state


def test_a_transient_git_failure_is_retried_and_the_retry_really_commits():
    if shutil.which("git") is None:
        pytest.skip("git not installed on this machine")
    tmp = _tmp()
    try:
        vault = _git_repo(tmp)
        (vault / "note.md").write_text("real content", encoding="utf-8")
        fake, state = _commit_fails_n_times(1)
        with patch.object(mv, "_run_git_ex", fake):
            out = mv._commit_vault_change_detailed(vault, "memory(USB2): transient retry")
        assert out["status"] == mv.COMMIT_STATUS_COMMITTED
        assert out["attempts"] == 2, "the first attempt must really have failed"
        assert state["commit_calls"] == 2

        # The retry produced a REAL commit in the REAL repo, not just a dict.
        import subprocess
        log = subprocess.run(["git", "log", "--oneline"], cwd=str(vault),
                              capture_output=True, text=True)
        assert "memory(USB2): transient retry" in log.stdout
        rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(vault),
                              capture_output=True, text=True)
        assert out["knowledge_commit_sha"] == rev.stdout.strip()
    finally:
        _rmtree(tmp)


def test_a_persistent_git_failure_is_reported_as_COMMIT_FAILED_with_the_real_reason():
    if shutil.which("git") is None:
        pytest.skip("git not installed on this machine")
    tmp = _tmp()
    try:
        vault = _git_repo(tmp)
        (vault / "note.md").write_text("real content", encoding="utf-8")
        fake, state = _commit_fails_n_times(99)
        with patch.object(mv, "_run_git_ex", fake):
            out = mv._commit_vault_change_detailed(vault, "memory(USB2): never lands")
        assert out["status"] == mv.COMMIT_STATUS_FAILED
        assert out.get("knowledge_commit_sha") is None, "never fabricate a SHA"
        assert "TimeoutExpired" in out["error"], "git's own reason must survive, not be swallowed"
        assert state["commit_calls"] == mv._GIT_COMMIT_ATTEMPTS

        # The whole point of this gap close: FAILED is now distinguishable
        # from the ordinary, benign "there was nothing to commit".
        assert out["status"] != mv.COMMIT_STATUS_NOTHING_TO_COMMIT
    finally:
        _rmtree(tmp)


def test_nothing_to_commit_is_its_own_status_and_is_never_retried():
    if shutil.which("git") is None:
        pytest.skip("git not installed on this machine")
    tmp = _tmp()
    try:
        vault = _git_repo(tmp)
        (vault / "note.md").write_text("real content", encoding="utf-8")
        first = mv._commit_vault_change_detailed(vault, "memory(USB2): first")
        assert first["status"] == mv.COMMIT_STATUS_COMMITTED

        second = mv._commit_vault_change_detailed(vault, "memory(USB2): nothing changed")
        assert second["status"] == mv.COMMIT_STATUS_NOTHING_TO_COMMIT
        assert second["attempts"] == 1, "an expected outcome must not burn the retry budget"
        assert second.get("error") is None
    finally:
        _rmtree(tmp)


def test_a_silently_failed_vault_commit_now_reaches_route_and_store_and_the_durable_record():
    """The real payoff: an ENGINEERING_MEMORY promotion whose vault commit
    genuinely fails must say so, both in route_and_store()'s own result and on
    the durable JSON record -- previously it produced a record with no SHA and
    no explanation, indistinguishable from one written before git was on."""
    if shutil.which("git") is None:
        pytest.skip("git not installed on this machine")
    tmp = _tmp()
    try:
        cfg = {**_NO_SHARE_CFG, "memory": {"vault_path": str(tmp / "vault"),
                                            "obsidian_cli": "disabled", "git_enabled": True}}
        fake, _state = _commit_fails_n_times(99)
        with patch.object(mv, "_run_git_ex", fake):
            result = route_and_store(tmp, {
                "kind": "verified_fix", "verified": True, "protocol": "USB2",
                "title": "Verified fix: ep0 underrun", "root_cause": "missing prefetch guard",
                "confidence": "HIGH", "evidence": ["sim.log:8821 UVM_ERROR ep0 underrun"],
            }, cfg=cfg)

        # The note itself still landed -- a git failure must never cost the write.
        assert result["vault_write"]["ok"] is True
        assert result["vault_write"].get("knowledge_commit_sha") is None
        assert result["vault_write"]["knowledge_commit_status"] == mv.COMMIT_STATUS_FAILED
        assert "TimeoutExpired" in result["vault_write"]["knowledge_commit_error"]

        rec = MemoryStore(tmp).get(result["memory_id"])
        assert rec.get("knowledge_commit_sha") is None
        assert rec["knowledge_commit_status"] == mv.COMMIT_STATUS_FAILED
        assert "TimeoutExpired" in rec["knowledge_commit_error"]
    finally:
        _rmtree(tmp)


def test_a_successful_promotion_records_the_sha_and_no_failure_status():
    if shutil.which("git") is None:
        pytest.skip("git not installed on this machine")
    tmp = _tmp()
    try:
        cfg = {**_NO_SHARE_CFG, "memory": {"vault_path": str(tmp / "vault"),
                                            "obsidian_cli": "disabled", "git_enabled": True}}
        result = route_and_store(tmp, {
            "kind": "verified_fix", "verified": True, "protocol": "USB2",
            "title": "Verified fix: ep0 underrun", "root_cause": "missing prefetch guard",
            "confidence": "HIGH", "evidence": ["sim.log:8821 UVM_ERROR ep0 underrun"],
        }, cfg=cfg)
        assert result["vault_write"]["knowledge_commit_status"] == mv.COMMIT_STATUS_COMMITTED
        rec = MemoryStore(tmp).get(result["memory_id"])
        assert rec["knowledge_commit_sha"] == result["vault_write"]["knowledge_commit_sha"]
        # A healthy record carries the SHA and is not polluted with a status.
        assert "knowledge_commit_status" not in rec
        assert "knowledge_commit_error" not in rec
    finally:
        _rmtree(tmp)


def test_a_git_disabled_vault_write_carries_no_commit_keys_at_all():
    """git_enabled=False is this project's documented default, not a defect
    (memory_doctor.check_git()) -- it must stay byte-identical to before, with
    no COMMIT_FAILED-shaped noise implying something broke."""
    tmp = _tmp()
    try:
        fs = mv.FileSystemMarkdownAdapter(tmp / "vault", git_enabled=False)
        created = fs.create({"id": "MEM-NOGIT", "memory_level": "engineering", "protocol": "USB2",
                             "status": "ACTIVE", "confidence": "HIGH", "failure": "ep0 underrun",
                             "created": "2026-09-04T00:00:00+00:00",
                             "updated": "2026-09-04T00:00:00+00:00"})
        assert created["ok"] is True
        for key in ("knowledge_commit_sha", "knowledge_commit_status",
                    "knowledge_commit_error", "knowledge_commit_attempts"):
            assert key not in created
        assert "knowledge_commit_status" not in fs.update("MEM-NOGIT", {"confidence": "CONFIRMED"})
        assert "knowledge_commit_status" not in fs.delete("MEM-NOGIT")
    finally:
        _rmtree(tmp)


def test_the_sha_only_helper_keeps_its_prior_optional_str_contract():
    """`cli.py`'s `memory vault-commit` calls `_commit_vault_change()` and
    stores the result directly -- it must still be a SHA string or None, never
    the new outcome dict."""
    if shutil.which("git") is None:
        pytest.skip("git not installed on this machine")
    tmp = _tmp()
    try:
        vault = _git_repo(tmp)
        (vault / "note.md").write_text("real content", encoding="utf-8")
        sha = mv._commit_vault_change(vault, "memory(USB2): sha only")
        assert isinstance(sha, str) and len(sha) == 40
        assert mv._commit_vault_change(vault, "memory(USB2): nothing changed") is None
    finally:
        _rmtree(tmp)
