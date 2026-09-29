"""INTRA-PROJECT ROOT-CAUSE CLUSTERING.

`capability_evolution.repeated_unresolved_failure_patterns()` groups this
project's own `job_failure` records by EXACT `evidence_db.signature_key()` --
the right tool for "the same failure, recorded twice". It was never the right
tool for "two agents worded the same real root cause differently", and
nothing else in this repo answered that question either. This module does,
within one project's own store, and is a pure SUGGESTION layer: it never
writes, merges, retracts or supersedes a memory record.

Every test below drives a REAL `MemoryStore` on disk through the REAL
production write path (`memory_router.route_and_store()`), with real
`memory_vault.build_failure_signature()` signatures -- exactly the
`test_cross_project_mining.py` convention this module's own sibling already
established. Nothing is mocked and no fixture JSON is hand-typed into a store
file.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from dv_harness import intra_project_root_cause_clustering as rcc
from dv_harness.memory import MemoryStore
from dv_harness.memory_router import route_and_store
from dv_harness.memory_vault import build_failure_signature

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

@pytest.fixture
def workspace():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _project(workspace: Path, name: str = "proj") -> Path:
    root = workspace / name
    root.mkdir(parents=True, exist_ok=True)
    MemoryStore(root)  # real store, real index.json
    return root


def _job_failure(root: Path, signature: dict, *, job_id=None, git_sha=None,
                 stage="RE_AUDIT", attempt=1) -> dict:
    """One real Job Memory record through the real router -- the exact field
    set engine._record_debug_attempt_job_memory() writes."""
    record = {
        "kind": "job_failure",
        "scope": "debug",
        "title": f"{stage} attempt {attempt} did not close",
        "stage": stage,
        "attempt": attempt,
        "status": "PARTIAL",
        "blocking_reason": "GATE_FAIL: root_cause_evidence_gate",
        "failure_signature": signature,
        "protocol": signature.get("protocol"),
    }
    if job_id is not None:
        record["job_id"] = job_id
    if git_sha is not None:
        record["git_sha"] = git_sha
    routed = route_and_store(root, record, cfg={})
    assert routed["destination"] == "JOB_MEMORY", routed
    return routed


def _verified_fix(root: Path, *, root_cause: str, symptom: str = "",
                  protocol: str = "USB3") -> dict:
    """One real Engineering Memory verified_fix record -- the shape
    engine._promote_verified_fix_knowledge() writes on a gate-verified
    RE_AUDIT close."""
    record = {
        "kind": "verified_fix",
        "verified": True,
        "title": f"Verified fix: {root_cause}",
        "scope": "engineering",
        "symptoms": [symptom] if symptom else [],
        "root_cause": root_cause,
        "fix": "rtl commit 5e1f00d",
        "evidence": ["sim.log:9120"],
        "reusable": True,
        "verification": {"targeted_reproducer_passed": True,
                         "broader_regression_passed": True,
                         "new_failures_introduced": False},
        "confidence": "HIGH",
        "protocol": protocol,
    }
    routed = route_and_store(root, record, cfg={})
    assert routed["destination"] == "ENGINEERING_MEMORY", routed
    return routed


def _memory_snapshot(root: Path):
    base = root / ".dv-harness" / "memory"
    if not base.exists():
        return {}
    return {str(p.relative_to(base)): p.read_bytes()
            for p in sorted(base.rglob("*")) if p.is_file()}


SYMPTOM_A = "link training timeout on lane 0 during recovery"
CAUSE_A = "phy calibration timing violation"
SYMPTOM_B = "link training timeout observed on lane zero"
CAUSE_B = "phy calibration timing issue"


def _sig_a(protocol="USB3"):
    return build_failure_signature(protocol=protocol, pattern="usb3_link_train_test",
                                   symptom=SYMPTOM_A, root_cause_hint=CAUSE_A)


def _sig_b(protocol="USB3"):
    return build_failure_signature(protocol=protocol, pattern="usb3_recovery_regress",
                                   symptom=SYMPTOM_B, root_cause_hint=CAUSE_B)


# --------------------------------------------------------------------------
# Vocabulary hygiene
# --------------------------------------------------------------------------

def test_vocabulary_never_collides_with_models_status():
    rcc.assert_no_verification_verdict_vocabulary()


def test_vocabulary_guard_has_real_detection_power(monkeypatch):
    """The collision guard must actually trip on a real collision, not just
    never fire by accident."""
    monkeypatch.setattr(rcc, "_VOCAB_TOKENS", frozenset(rcc._VOCAB_TOKENS | {"PASS"}))
    with pytest.raises(AssertionError):
        rcc.assert_no_verification_verdict_vocabulary()


# --------------------------------------------------------------------------
# Absence of evidence -- never fabricated, never mints a store
# --------------------------------------------------------------------------

def test_bare_project_reports_insufficient_evidence_and_mints_no_store(workspace):
    bare = workspace / "bare"
    bare.mkdir()
    report = rcc.cluster_intra_project_root_causes(bare)
    assert report["status"] == rcc.STATUS_INSUFFICIENT_EVIDENCE
    assert report["clusters"] == []
    assert not (bare / ".dv-harness").exists()


def test_project_with_a_real_store_but_no_job_failures_is_insufficient_evidence(workspace):
    root = _project(workspace)
    report = rcc.cluster_intra_project_root_causes(root)
    assert report["status"] == rcc.STATUS_INSUFFICIENT_EVIDENCE


def test_invalid_min_similarity_raises():
    with pytest.raises(rcc.IntraProjectClusteringError):
        rcc.cluster_intra_project_root_causes(".", min_similarity=0.0)
    with pytest.raises(rcc.IntraProjectClusteringError):
        rcc.cluster_intra_project_root_causes(".", min_similarity=1.5)
    with pytest.raises(rcc.IntraProjectClusteringError):
        rcc.cluster_intra_project_root_causes(".", min_similarity=-0.2)


# --------------------------------------------------------------------------
# The positive case: two differently-worded signatures, same protocol,
# real text overlap -> clustered
# --------------------------------------------------------------------------

def test_two_differently_worded_signatures_are_clustered(workspace):
    root = _project(workspace)
    _job_failure(root, _sig_a(), job_id="J1")
    _job_failure(root, _sig_b(), job_id="J2")

    before = _memory_snapshot(root)
    report = rcc.cluster_intra_project_root_causes(root)
    after = _memory_snapshot(root)

    assert before == after, "clustering must never mutate the store"
    assert report["status"] == rcc.STATUS_CLUSTERS_FOUND
    assert report["signature_group_count"] == 2
    assert len(report["clusters"]) == 1

    cluster = report["clusters"][0]
    assert cluster["protocol"] == "usb3"
    assert len(cluster["member_signature_keys"]) == 2
    assert cluster["total_occurrence_count"] == 2
    assert cluster["total_independent_run_count"] == 2
    assert cluster["run_identities"] == ["job_id:J1", "job_id:J2"]
    assert cluster["resolution_status"] == rcc.RESOLUTION_ALL_OPEN
    # real, cited evidence basis -- never a bare opaque id
    assert len(cluster["pairwise_evidence"]) == 1
    edge = cluster["pairwise_evidence"][0]
    assert edge["similarity_score"] >= rcc.DEFAULT_MIN_SIMILARITY
    assert set(edge["shared_tokens"]) >= {"link", "training", "timeout", "phy", "calibration"}
    # a stable, content-derived id
    assert cluster["cluster_id"] == rcc._cluster_id(cluster["member_signature_keys"])


def test_cluster_id_is_stable_across_reruns(workspace):
    root = _project(workspace)
    _job_failure(root, _sig_a(), job_id="J1")
    _job_failure(root, _sig_b(), job_id="J2")

    r1 = rcc.cluster_intra_project_root_causes(root)
    r2 = rcc.cluster_intra_project_root_causes(root)
    assert r1["clusters"][0]["cluster_id"] == r2["clusters"][0]["cluster_id"]


# --------------------------------------------------------------------------
# Negative control: different protocol -> never bridged by text overlap
# --------------------------------------------------------------------------

def test_same_text_different_protocol_is_never_clustered(workspace):
    root = _project(workspace)
    _job_failure(root, _sig_a(protocol="USB3"), job_id="J1")
    _job_failure(root, _sig_b(protocol="PCIe"), job_id="J2")

    report = rcc.cluster_intra_project_root_causes(root)
    assert report["clusters"] == []
    assert report["status"] == rcc.STATUS_NO_CLUSTERS_FOUND
    assert len(report["single_signature_groups"]) == 2


# --------------------------------------------------------------------------
# Negative control: low similarity -> stays a single, never guessed into a
# cluster
# --------------------------------------------------------------------------

def test_dissimilar_text_same_protocol_is_not_clustered(workspace):
    root = _project(workspace)
    sig_a = build_failure_signature(protocol="USB3", symptom=SYMPTOM_A,
                                    root_cause_hint=CAUSE_A)
    sig_c = build_failure_signature(
        protocol="USB3",
        symptom="scoreboard data mismatch on read completion",
        root_cause_hint="address decoder returned the wrong bank",
    )
    _job_failure(root, sig_a, job_id="J1")
    _job_failure(root, sig_c, job_id="J2")

    report = rcc.cluster_intra_project_root_causes(root)
    assert report["clusters"] == []
    assert report["status"] == rcc.STATUS_NO_CLUSTERS_FOUND
    assert {s["signature_key"] for s in report["single_signature_groups"]} == {
        rcc_key(sig_a), rcc_key(sig_c)
    }


def rcc_key(signature):
    from dv_harness.evidence_db import signature_key
    return signature_key(signature)


# --------------------------------------------------------------------------
# Ineligible groups: honestly reported, never silently paired
# --------------------------------------------------------------------------

def test_missing_protocol_group_is_ineligible_not_silently_paired(workspace):
    root = _project(workspace)
    sig_no_protocol = build_failure_signature(symptom=SYMPTOM_A, root_cause_hint=CAUSE_A)
    _job_failure(root, sig_no_protocol, job_id="J1")
    _job_failure(root, _sig_b(), job_id="J2")

    report = rcc.cluster_intra_project_root_causes(root)
    assert report["clusters"] == []
    ineligible = report["ineligible_signature_groups"]
    assert len(ineligible) == 1
    assert ineligible[0]["reason"] == rcc.REASON_MISSING_PROTOCOL
    # the group WITH a protocol is still reported, as an unclustered single
    assert len(report["single_signature_groups"]) == 1


def test_insufficient_descriptive_text_group_is_ineligible(workspace):
    root = _project(workspace)
    thin_sig = build_failure_signature(protocol="USB3", symptom="x")
    _job_failure(root, thin_sig, job_id="J1")
    _job_failure(root, _sig_a(), job_id="J2")

    report = rcc.cluster_intra_project_root_causes(root)
    ineligible = report["ineligible_signature_groups"]
    assert len(ineligible) == 1
    assert ineligible[0]["reason"] == rcc.REASON_INSUFFICIENT_TEXT


# --------------------------------------------------------------------------
# Exact-duplicate signatures already accumulate under ONE signature_key --
# this module's job starts one level above that
# --------------------------------------------------------------------------

def test_identical_signature_dicts_stay_one_group_not_two(workspace):
    root = _project(workspace)
    sig = _sig_a()
    _job_failure(root, sig, job_id="J1")
    _job_failure(root, dict(sig), job_id="J2")  # byte-identical signature, second run

    report = rcc.cluster_intra_project_root_causes(root)
    assert report["signature_group_count"] == 1
    assert report["clusters"] == []
    single = report["single_signature_groups"][0]
    assert single["occurrence_count"] == 2
    assert single["independent_run_count"] == 2


def test_same_run_across_two_signature_keys_is_not_double_counted(workspace):
    """A run union across cluster members must collapse a run that
    coincidentally appears under both differently-worded signatures, never
    double-count it."""
    root = _project(workspace)
    _job_failure(root, _sig_a(), job_id="J1")
    _job_failure(root, _sig_b(), job_id="J1")  # same run, second wording

    report = rcc.cluster_intra_project_root_causes(root)
    assert len(report["clusters"]) == 1
    cluster = report["clusters"][0]
    assert cluster["run_identities"] == ["job_id:J1"]
    assert cluster["total_independent_run_count"] == 1
    assert cluster["total_occurrence_count"] == 2  # two distinct memory_ids


# --------------------------------------------------------------------------
# Resolution status: reused capability_evolution.failure_resolution_claims()
# exact-text join, never fuzzy
# --------------------------------------------------------------------------

def test_cluster_resolution_status_all_open(workspace):
    root = _project(workspace)
    _job_failure(root, _sig_a(), job_id="J1")
    _job_failure(root, _sig_b(), job_id="J2")
    report = rcc.cluster_intra_project_root_causes(root)
    assert report["clusters"][0]["resolution_status"] == rcc.RESOLUTION_ALL_OPEN


def test_cluster_resolution_status_partially_resolved(workspace):
    root = _project(workspace)
    _job_failure(root, _sig_a(), job_id="J1")
    _job_failure(root, _sig_b(), job_id="J2")
    # A verified_fix whose root_cause exactly matches A's own root_cause_hint
    # text (normalized) -- closes A's exact wording only, never B's, since
    # the join is exact-text, never fuzzy.
    _verified_fix(root, root_cause=CAUSE_A)

    report = rcc.cluster_intra_project_root_causes(root)
    cluster = report["clusters"][0]
    assert cluster["resolution_status"] == rcc.RESOLUTION_PARTIALLY_RESOLVED
    members_by_key = {m["signature_key"]: m for m in cluster["members"]}
    resolved_members = [m for m in members_by_key.values() if m["resolved_by_verified_fix"]]
    open_members = [m for m in members_by_key.values() if not m["resolved_by_verified_fix"]]
    assert len(resolved_members) == 1
    assert len(open_members) == 1


def test_cluster_resolution_status_all_resolved(workspace):
    root = _project(workspace)
    _job_failure(root, _sig_a(), job_id="J1")
    _job_failure(root, _sig_b(), job_id="J2")
    _verified_fix(root, root_cause=CAUSE_A)
    _verified_fix(root, root_cause=CAUSE_B)

    report = rcc.cluster_intra_project_root_causes(root)
    assert report["clusters"][0]["resolution_status"] == rcc.RESOLUTION_ALL_RESOLVED


# --------------------------------------------------------------------------
# Scan-skipped guard: never silently unbounded, every eligible group still
# reported
# --------------------------------------------------------------------------

def test_scan_skipped_when_eligible_group_count_exceeds_max(workspace, monkeypatch):
    root = _project(workspace)
    monkeypatch.setattr(rcc, "MAX_CLUSTER_SCAN_SIZE", 2)
    for i in range(4):
        sig = build_failure_signature(
            protocol="USB3",
            symptom=f"distinct failure number {i} on port {i}",
            root_cause_hint=f"root cause variant {i}",
        )
        _job_failure(root, sig, job_id=f"J{i}")

    report = rcc.cluster_intra_project_root_causes(root)
    assert report["status"] == rcc.STATUS_SCAN_SKIPPED
    assert report["clusters"] == []
    assert len(report["single_signature_groups"]) == 4
    assert all("note" in s for s in report["single_signature_groups"])


# --------------------------------------------------------------------------
# Rendering + CLI
# --------------------------------------------------------------------------

def test_render_report_markdown_includes_cluster_table(workspace):
    root = _project(workspace)
    _job_failure(root, _sig_a(), job_id="J1")
    _job_failure(root, _sig_b(), job_id="J2")
    report = rcc.cluster_intra_project_root_causes(root)
    text = rcc.render_report_markdown(report)
    assert "Intra-Project Root-Cause Clustering" in text
    assert report["clusters"][0]["cluster_id"] in text


def test_execute_verb_exit_codes(workspace, capsys):
    bare = workspace / "bare"
    bare.mkdir()
    assert rcc.execute_verb(["--root", str(bare)]) == 2  # insufficient evidence

    root = _project(workspace, "with_cluster")
    _job_failure(root, _sig_a(), job_id="J1")
    _job_failure(root, _sig_b(), job_id="J2")
    assert rcc.execute_verb(["--root", str(root), "--json"]) == 1  # a real finding

    root2 = _project(workspace, "no_cluster")
    _job_failure(root2, _sig_a(protocol="USB3"), job_id="J1")
    _job_failure(root2, _sig_b(protocol="PCIe"), job_id="J2")
    assert rcc.execute_verb(["--root", str(root2)]) == 0  # clean, no finding


def test_cli_subprocess_round_trip(workspace):
    root = _project(workspace, "cli_proj")
    _job_failure(root, _sig_a(), job_id="J1")
    _job_failure(root, _sig_b(), job_id="J2")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.intra_project_root_cause_clustering",
         "--root", str(root), "--json"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 1, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == rcc.STATUS_CLUSTERS_FOUND
    assert len(payload["clusters"]) == 1
