"""Real tests for `dv_harness/memory_quality_policy.py` (2026-09-06,
targeted_hardening item `memory_quality_forgetting`, spec section 228).

Every test drives the REAL `dv_harness.memory.MemoryStore`/`MemoryGC` on a
real temp directory -- no hand-written record files, no mocks of either
class. The negative controls are the ones this project's own house style is
graded on: a record with no age evidence, or one already retired, must never
be silently fabricated a staleness/deprecation/duplicate finding, and a
dry-run report must never write anything to disk.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from dv_harness.memory import MemoryGC, MemoryStore
from dv_harness.memory_quality_policy import (
    ACTION_DEPRECATE,
    ACTION_FLAG_STALE,
    ACTION_NONE,
    ACTION_SUPERSEDE,
    DEFAULT_DEPRECATE_AFTER_DAYS,
    DEFAULT_STALE_AFTER_DAYS,
    MemoryQualityPolicyError,
    apply_memory_quality_policy,
    classify_record_quality,
    evaluate_memory_quality,
    find_superseded_engineering_groups,
    load_declared_policy,
)

DAY = 86400.0


def _days_ago(now: float, days: float) -> float:
    return now - days * DAY


# ---------------------------------------------------------------------------
# classify_record_quality() -- pure function, ground 1 + 2
# ---------------------------------------------------------------------------

def test_classify_no_age_evidence_is_never_fabricated():
    """No `created_at` at all -> honest NONE/NO_AGE_EVIDENCE, never a guessed
    staleness/deprecation verdict."""
    decision = classify_record_quality({"memory_id": "MEM-1", "status": "ACTIVE"})
    assert decision["recommended_action"] == ACTION_NONE
    assert decision["reason"] == "NO_AGE_EVIDENCE"
    assert decision["evidence"] == {}


@pytest.mark.parametrize("status", ["DEPRECATED", "RETRACTED", "SUPERSEDED"])
def test_classify_already_terminal_record_is_left_alone(status):
    now = time.time()
    decision = classify_record_quality(
        {"memory_id": "MEM-1", "status": status, "created_at": _days_ago(now, 10000)},
        now=now,
    )
    assert decision["recommended_action"] == ACTION_NONE
    assert decision["reason"] == "STATUS_ALREADY_TERMINAL"


def test_classify_within_policy_window_recommends_nothing():
    now = time.time()
    decision = classify_record_quality(
        {"memory_id": "MEM-1", "status": "ACTIVE", "created_at": _days_ago(now, 5)},
        now=now,
    )
    assert decision["recommended_action"] == ACTION_NONE
    assert decision["reason"] == "WITHIN_POLICY_WINDOW"


def test_classify_flags_stale_by_age_when_reused():
    """Old, never confirmed, but genuinely REUSED -> demoted to
    NEEDS_REVALIDATION, not retired outright: ground 2 requires reuse_count
    == 0 too."""
    now = time.time()
    decision = classify_record_quality(
        {
            "memory_id": "MEM-1", "status": "ACTIVE",
            "created_at": _days_ago(now, DEFAULT_STALE_AFTER_DAYS + 5),
            "reuse_count": 3,
        },
        now=now,
    )
    assert decision["recommended_action"] == ACTION_FLAG_STALE
    assert "stale threshold" in decision["reason"]


def test_classify_deprecates_never_confirmed_never_reused_very_old_record():
    now = time.time()
    decision = classify_record_quality(
        {
            "memory_id": "MEM-1", "status": "ACTIVE",
            "created_at": _days_ago(now, DEFAULT_DEPRECATE_AFTER_DAYS + 5),
        },
        now=now,
    )
    assert decision["recommended_action"] == ACTION_DEPRECATE
    assert "deprecate threshold" in decision["reason"]
    assert decision["evidence"]["never_confirmed"] is True


def test_classify_deprecate_never_fires_when_ever_reused():
    """Negative control for ground 2: however old, a record anyone ever
    reused is never DEPRECATEd by this policy on its own -- it still routes
    through the weaker FLAG_STALE ground instead."""
    now = time.time()
    decision = classify_record_quality(
        {
            "memory_id": "MEM-1", "status": "ACTIVE",
            "created_at": _days_ago(now, DEFAULT_DEPRECATE_AFTER_DAYS + 100),
            "reuse_count": 1,
        },
        now=now,
    )
    assert decision["recommended_action"] == ACTION_FLAG_STALE


def test_classify_deprecate_never_fires_when_ever_confirmed():
    """Negative control for ground 2: a real confirmation exempts a record
    from DEPRECATE even when it is ancient and never reused."""
    now = time.time()
    decision = classify_record_quality(
        {
            "memory_id": "MEM-1", "status": "ACTIVE",
            "created_at": _days_ago(now, DEFAULT_DEPRECATE_AFTER_DAYS + 100),
            "confirmation_count": 1,
            "last_confirmed_at": _days_ago(now, DEFAULT_DEPRECATE_AFTER_DAYS + 90),
        },
        now=now,
    )
    assert decision["recommended_action"] != ACTION_DEPRECATE


def test_classify_malformed_record_refused():
    with pytest.raises(MemoryQualityPolicyError):
        classify_record_quality({"status": "ACTIVE"})  # no memory_id
    with pytest.raises(MemoryQualityPolicyError):
        classify_record_quality("not-a-dict")  # type: ignore[arg-type]


def test_classify_real_confirmation_resets_the_staleness_clock():
    """End-to-end proof this reads REAL evidence, not a guess: a record
    created long ago but genuinely, recently re-confirmed through the real
    MemoryGC.confirm() must NOT be flagged stale."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = MemoryStore(root)
        now = time.time()
        rec = store.add("engineering", {
            "protocol": "USB2", "root_cause": "ancient finding",
            "created_at": _days_ago(now, DEFAULT_STALE_AFTER_DAYS + 50),
        })
        assert MemoryGC(store).confirm(rec["memory_id"]) is True
        fresh = store.get(rec["memory_id"])
        assert fresh["confirmation_count"] == 1
        assert fresh["last_confirmed_at"] is not None

        decision = classify_record_quality(fresh, now=now)
        assert decision["recommended_action"] == ACTION_NONE
        assert decision["reason"] == "WITHIN_POLICY_WINDOW"


# ---------------------------------------------------------------------------
# find_superseded_engineering_groups() -- ground 3
# ---------------------------------------------------------------------------

def test_supersede_groups_duplicate_engineering_findings_by_confirmation_strength(tmp_path):
    store = MemoryStore(tmp_path)
    now = time.time()

    weak = store.add("engineering", {
        "protocol": "USB2", "root_cause": "LFPS timeout on port reset",
        "created_at": _days_ago(now, 400),
    })
    strong = store.add("engineering", {
        "protocol": "USB2", "root_cause": "LFPS TIMEOUT ON PORT RESET",  # case-insensitive match
        "created_at": _days_ago(now, 10),
    })
    MemoryGC(store).confirm(strong["memory_id"])  # confirmation_count=1 -> stronger

    groups = find_superseded_engineering_groups(store)
    assert len(groups) == 1
    group = groups[0]
    assert group["winner_memory_id"] == strong["memory_id"]
    losers = {r["memory_id"] for r in group["recommendations"]}
    assert losers == {weak["memory_id"]}
    rec = group["recommendations"][0]
    assert rec["recommended_action"] == ACTION_SUPERSEDE
    assert rec["superseded_by"] == strong["memory_id"]


def test_supersede_never_groups_different_protocol_or_missing_root_cause(tmp_path):
    """Negative control: this module never fabricates a duplicate finding
    without a real matching (protocol, root_cause) pair."""
    store = MemoryStore(tmp_path)
    store.add("engineering", {"protocol": "USB2", "root_cause": "issue A"})
    store.add("engineering", {"protocol": "PCIe", "root_cause": "issue A"})
    store.add("engineering", {"protocol": "USB2"})  # no root_cause at all
    store.add("engineering", {"root_cause": "issue A"})  # no protocol at all

    groups = find_superseded_engineering_groups(store)
    assert groups == []


def test_supersede_never_crosses_tier_boundary(tmp_path):
    """Negative control: this module is deliberately scoped to
    engineering-tier records only -- see module docstring."""
    store = MemoryStore(tmp_path)
    store.add("project", {"protocol": "USB2", "root_cause": "same text"})
    store.add("project", {"protocol": "USB2", "root_cause": "same text"})
    assert find_superseded_engineering_groups(store) == []


def test_supersede_ties_break_on_recency_then_memory_id(tmp_path):
    store = MemoryStore(tmp_path)
    now = time.time()
    older = store.add("engineering", {
        "protocol": "PCIe", "root_cause": "link training fail",
        "created_at": _days_ago(now, 20),
    })
    newer = store.add("engineering", {
        "protocol": "PCIe", "root_cause": "link training fail",
        "created_at": _days_ago(now, 1),
    })
    groups = find_superseded_engineering_groups(store)
    assert len(groups) == 1
    assert groups[0]["winner_memory_id"] == newer["memory_id"]


# ---------------------------------------------------------------------------
# evaluate_memory_quality() -- read-only, never mints a store
# ---------------------------------------------------------------------------

def test_evaluate_reports_not_available_and_creates_nothing_on_a_bare_root(tmp_path):
    result = evaluate_memory_quality(tmp_path)
    assert result["status"] == "NOT_AVAILABLE"
    assert not (tmp_path / ".dv-harness").exists()


def test_evaluate_report_is_read_only(tmp_path):
    """Dry-run evaluation must never mutate the store it reports on."""
    store = MemoryStore(tmp_path)
    rec = store.add("engineering", {
        "protocol": "USB2", "root_cause": "old unconfirmed finding",
        "created_at": _days_ago(time.time(), DEFAULT_DEPRECATE_AFTER_DAYS + 5),
    })
    before = json.dumps(store.get(rec["memory_id"]), sort_keys=True)

    report = evaluate_memory_quality(tmp_path)
    assert report["status"] == "ACTION_RECOMMENDED"
    assert any(d["memory_id"] == rec["memory_id"] for d in report["deprecate"])

    after = json.dumps(store.get(rec["memory_id"]), sort_keys=True)
    assert before == after
    assert store.get(rec["memory_id"])["status"] == "ACTIVE"


def test_evaluate_respects_levels_filter(tmp_path):
    store = MemoryStore(tmp_path)
    old_ts = _days_ago(time.time(), DEFAULT_STALE_AFTER_DAYS + 5)
    store.add("project", {"created_at": old_ts, "reuse_count": 1})
    report_all = evaluate_memory_quality(tmp_path)
    report_eng_only = evaluate_memory_quality(tmp_path, levels=["engineering"])
    assert report_all["total_recommended"] == 1
    assert report_eng_only["total_recommended"] == 0


# ---------------------------------------------------------------------------
# apply_memory_quality_policy() -- real MemoryGC writes
# ---------------------------------------------------------------------------

def test_apply_dry_run_default_writes_nothing(tmp_path):
    store = MemoryStore(tmp_path)
    rec = store.add("engineering", {
        "protocol": "USB2", "root_cause": "never confirmed old finding",
        "created_at": _days_ago(time.time(), DEFAULT_DEPRECATE_AFTER_DAYS + 5),
    })
    result = apply_memory_quality_policy(tmp_path)  # dry_run=True default
    assert result["dry_run"] is True
    assert result["applied"] == []
    assert store.get(rec["memory_id"])["status"] == "ACTIVE"


def test_apply_actually_deprecates_via_real_memorygc(tmp_path):
    store = MemoryStore(tmp_path)
    rec = store.add("engineering", {
        "protocol": "USB2", "root_cause": "genuinely stale unconfirmed finding",
        "created_at": _days_ago(time.time(), DEFAULT_DEPRECATE_AFTER_DAYS + 5),
    })
    result = apply_memory_quality_policy(tmp_path, dry_run=False)
    assert result["dry_run"] is False
    applied_ids = {a["memory_id"] for a in result["applied"] if a["applied"]}
    assert rec["memory_id"] in applied_ids

    on_disk = store.get(rec["memory_id"])
    assert on_disk["status"] == "DEPRECATED"
    assert on_disk["deprecation_reason"]  # the real reason MemoryGC.deprecate() stored


def test_apply_actually_flags_stale_via_real_memorygc(tmp_path):
    store = MemoryStore(tmp_path)
    rec = store.add("engineering", {
        "protocol": "USB2", "root_cause": "reused but aging finding",
        "created_at": _days_ago(time.time(), DEFAULT_STALE_AFTER_DAYS + 5),
        "reuse_count": 2,
    })
    result = apply_memory_quality_policy(tmp_path, dry_run=False)
    assert any(a["memory_id"] == rec["memory_id"] and a["recommended_action"] == ACTION_FLAG_STALE
               for a in result["applied"])
    on_disk = store.get(rec["memory_id"])
    assert on_disk["status"] == "NEEDS_REVALIDATION"
    assert on_disk["stale_reason"]


def test_apply_actually_supersedes_duplicate_via_real_memorygc(tmp_path):
    store = MemoryStore(tmp_path)
    now = time.time()
    weak = store.add("engineering", {
        "protocol": "USB2", "root_cause": "duplicate finding text",
        "created_at": _days_ago(now, 5),
    })
    strong = store.add("engineering", {
        "protocol": "USB2", "root_cause": "duplicate finding text",
        "created_at": _days_ago(now, 1),
    })
    MemoryGC(store).confirm(strong["memory_id"])

    result = apply_memory_quality_policy(tmp_path, dry_run=False)

    weak_after = store.get(weak["memory_id"])
    strong_after = store.get(strong["memory_id"])
    assert weak_after["status"] == "SUPERSEDED"
    assert weak_after["superseded_by"] == strong["memory_id"]
    assert weak_after["supersede_reason"]
    # The winner is left completely untouched by the policy.
    assert strong_after["status"] == "ACTIVE"


def test_apply_never_touches_a_bare_root(tmp_path):
    result = apply_memory_quality_policy(tmp_path, dry_run=False)
    assert result["status"] == "NOT_AVAILABLE"
    assert result["applied"] == []
    assert not (tmp_path / ".dv-harness").exists()


# ---------------------------------------------------------------------------
# load_declared_policy()
# ---------------------------------------------------------------------------

def test_declared_policy_defaults_when_no_config(tmp_path):
    policy = load_declared_policy(tmp_path)
    assert policy["source"] == "default"
    assert policy["stale_after_days"] == DEFAULT_STALE_AFTER_DAYS
    assert policy["deprecate_after_days"] == DEFAULT_DEPRECATE_AFTER_DAYS
    assert not (tmp_path / ".dv-harness").exists()  # a plain read must mint nothing


def test_declared_policy_reads_project_override(tmp_path):
    cfg_dir = tmp_path / ".dv-harness"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(
        json.dumps({"memory_quality": {"stale_after_days": 30, "deprecate_after_days": 90}}),
        encoding="utf-8",
    )
    policy = load_declared_policy(tmp_path)
    assert policy == {"stale_after_days": 30, "deprecate_after_days": 90, "source": "declared"}


def test_declared_policy_tolerates_malformed_config(tmp_path):
    cfg_dir = tmp_path / ".dv-harness"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text("{not valid json", encoding="utf-8")
    policy = load_declared_policy(tmp_path)
    assert policy["source"] == "default"


# ---------------------------------------------------------------------------
# CLI front door
# ---------------------------------------------------------------------------

def test_cli_report_and_apply_real_subprocess(tmp_path):
    store = MemoryStore(tmp_path)
    rec = store.add("engineering", {
        "protocol": "USB2", "root_cause": "cli-driven stale finding",
        "created_at": _days_ago(time.time(), DEFAULT_DEPRECATE_AFTER_DAYS + 5),
    })

    report_proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.memory_quality_policy", "--root", str(tmp_path), "report"],
        capture_output=True, text=True,
    )
    assert report_proc.returncode == 1
    payload = json.loads(report_proc.stdout)
    assert payload["status"] == "ACTION_RECOMMENDED"
    assert store.get(rec["memory_id"])["status"] == "ACTIVE"  # report never writes

    apply_proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.memory_quality_policy", "--root", str(tmp_path), "apply"],
        capture_output=True, text=True,
    )
    assert apply_proc.returncode == 1
    assert store.get(rec["memory_id"])["status"] == "DEPRECATED"


def test_cli_not_available_exit_code(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.memory_quality_policy", "--root", str(tmp_path), "report"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2
