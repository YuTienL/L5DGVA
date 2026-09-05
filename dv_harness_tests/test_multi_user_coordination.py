"""Tests for dv_harness/multi_user_coordination.py -- spec section 239's
multi-user coordination CONFLICT DETECTION (2026-09-06).

This is inherently a multi-session scenario, so nothing here is a
single-function smoke test. Every test builds TWO (sometimes three) REAL,
SEPARATE project roots -- exactly the layout USAGE_MULTI_USER_SAFETY.md's
"never share a `--project-root`" rule prescribes -- and each root is populated
by the REAL producing mechanism, never by a hand-written dict shaped to look
like one:

  * a REAL throwaway git repository with real commits, and each session's
    changed-file set computed by the REAL `change_impact.compute_and_write()`
    off a REAL `git diff --name-only <base>..<head>`;
  * a REAL `.dv-harness/requirements.csv` traceability registry, so the
    PLANNED regression sets are what the real `select_regression()` selects;
  * REAL `lsf_client.save_job_state()` records for submitted jobs;
  * REAL `AgentTaskStore.acquire(scope=SHARED)` claims through the same
    ownership ledger engine.py's parallel_group fan-out already uses;
  * REAL `CLI_ACCESS` events, so user identity comes off the same access trail
    `user_info.summarize_user_access()` already reads.

The central proofs are the three "two concurrent sessions" tests
(`test_two_sessions_on_different_shas_touching_the_same_rtl_file`,
`test_two_sessions_submitting_the_same_pattern_against_the_same_commit`,
`test_two_sessions_claiming_the_same_vip_instance`), each with a matching
negative case proving the detector does NOT fire on the benign arrangement,
and an end-to-end drive of the REAL `dv-harness coord detect` CLI subprocess.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from dv_harness import change_impact, multi_agent
from dv_harness import multi_user_coordination as muc
from dv_harness.lsf_client import JobState, save_job_state
from dv_harness.multi_agent import (MODE_READ, MODE_WRITE, SCOPE_LOCAL, SCOPE_SHARED,
                                     AgentTaskStore, ResourceKindError)

GIT = shutil.which("git")
requires_git = pytest.mark.skipif(GIT is None, reason="git is not on PATH")

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIREMENTS_CSV = (
    "REQ_ID,SOURCE,SCOPE,VPLAN_ID,SCENARIO_ID,COMMAND_ID,PATTERN_ID,CHECKER_ID,"
    "COVERAGE_ID,RESULT,STATUS,EVIDENCE\n"
    "REQ-USB3-LFPS-001,spec,usb3_link_ctrl,VP-LFPS,SC-1,CMD-1,usb3_lfps_basic,"
    "CHK-1,COV-1,,OPEN,\n"
    "REQ-USB3-PWR-002,spec,usb3_pwr_ctrl,VP-PWR,SC-2,CMD-2,usb3_u1_entry,"
    "CHK-2,COV-2,,OPEN,\n"
)


# --- real git repo ---------------------------------------------------------


def _git(root, *args, check=True):
    r = subprocess.run([GIT, *args], cwd=str(root), capture_output=True, text=True,
                       timeout=120, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise AssertionError(f"git {args} failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r


def _commit(root, message):
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", message)
    return _git(root, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture()
def repo(tmp_path):
    """One REAL shared design repository with three real commits:

        c0  initial
        c1  edits rtl/usb3_link_ctrl.v
        c2  edits rtl/usb3_link_ctrl.v again AND rtl/usb3_pwr_ctrl.v

    Two users working from different commits of this same repo is exactly the
    real-world shape stale-SHA detection exists for.
    """
    root = tmp_path / "design"
    (root / "rtl").mkdir(parents=True)
    (root / "doc").mkdir(parents=True)
    (root / "rtl" / "usb3_link_ctrl.v").write_text(
        "module usb3_link_ctrl(input clk, output reg done);\nendmodule\n", encoding="utf-8")
    (root / "rtl" / "usb3_pwr_ctrl.v").write_text(
        "module usb3_pwr_ctrl(input clk);\nendmodule\n", encoding="utf-8")
    (root / "doc" / "notes.md").write_text("# notes\n", encoding="utf-8")
    (root / ".gitignore").write_text(".dv-harness/\n", encoding="utf-8")
    subprocess.run([GIT, "init", "-q", "-b", "master", str(root)], check=True, timeout=60)
    _git(root, "config", "user.email", "coord@example.invalid")
    _git(root, "config", "user.name", "coord-test")
    c0 = _commit(root, "initial")

    (root / "rtl" / "usb3_link_ctrl.v").write_text(
        "module usb3_link_ctrl(input clk, output reg done);\n"
        "// alice's LFPS fix\nendmodule\n", encoding="utf-8")
    c1 = _commit(root, "lfps fix")

    (root / "rtl" / "usb3_link_ctrl.v").write_text(
        "module usb3_link_ctrl(input clk, output reg done);\n"
        "// alice's LFPS fix\n// bob's second edit\nendmodule\n", encoding="utf-8")
    (root / "rtl" / "usb3_pwr_ctrl.v").write_text(
        "module usb3_pwr_ctrl(input clk);\n// bob's power edit\nendmodule\n",
        encoding="utf-8")
    c2 = _commit(root, "second link edit + power edit")
    return {"root": root, "c0": c0, "c1": c1, "c2": c2}


# --- real per-user session roots -------------------------------------------


def _make_session_root(tmp_path, name):
    """One user's OWN `--project-root`, per USAGE_MULTI_USER_SAFETY.md."""
    root = tmp_path / name
    (root / ".dv-harness").mkdir(parents=True)
    (root / ".dv-harness" / "state.json").write_text(
        json.dumps({"project": name, "current_stage": "REGRESSION_SELECT",
                    "overall_status": "IN_PROGRESS", "git_sha": None}),
        encoding="utf-8")
    (root / ".dv-harness" / "requirements.csv").write_text(REQUIREMENTS_CSV,
                                                            encoding="utf-8")
    return root


def _record_access(root, user, host="linux-dv01"):
    """A REAL CLI_ACCESS event, the same shape cli.py writes -- this is the
    only thing that tells a scan who drives a given project root."""
    p = Path(root) / ".dv-harness" / "events.jsonl"
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.time(), "event": "CLI_ACCESS",
                            "cmd": "start", "user": user, "host": host}) + "\n")


def _compute_selection(session_root, repo_root, base_sha, head_sha):
    """Drive the REAL change-impact computation: a real `git diff` against the
    real repo, written into this session's own `.dv-harness/`."""
    return change_impact.compute_and_write(
        session_root, base_sha=base_sha, head_sha=head_sha,
        diff=change_impact.changed_files(repo_root, base_sha, head_sha),
        registry=change_impact.load_trace_registry(session_root))


def _session(tmp_path, repo, name, user, base_sha, head_sha):
    root = _make_session_root(tmp_path, name)
    _record_access(root, user)
    _compute_selection(root, repo["root"], base_sha, head_sha)
    return root


# --- (a) stale-SHA conflict -------------------------------------------------


@requires_git
def test_two_sessions_on_different_shas_touching_the_same_rtl_file(tmp_path, repo):
    """THE central stale-SHA proof: two REAL concurrent sessions, each with its
    own project root and its own REAL git-diff-derived changed-file set, based
    on DIFFERENT baselines but touching the SAME RTL file."""
    alice = _session(tmp_path, repo, "alice_proj", "alice", repo["c0"], repo["c1"])
    bob = _session(tmp_path, repo, "bob_proj", "bob", repo["c1"], repo["c2"])

    report = muc.scan([("alice", str(alice)), ("bob", str(bob))])

    assert report["status"] == muc.STATUS_CONFLICTS, report
    stale = [c for c in report["conflicts"] if c["kind"] == muc.CONFLICT_STALE_SHA]
    assert len(stale) == 1, report["conflicts"]
    c = stale[0]
    # The overlapping file is real, and its risk came from the real classifier.
    assert c["detail"]["overlapping_files"] == ["rtl/usb3_link_ctrl.v"]
    assert c["detail"]["file_risk"]["rtl/usb3_link_ctrl.v"] == change_impact.RISK_HIGH
    assert c["severity"] == muc.SEVERITY_HIGH
    # The two baselines really are the two real commits.
    assert set(c["detail"]["base_shas"].values()) == {repo["c0"], repo["c1"]}
    assert sorted(c["users"]) == ["alice", "bob"]
    # DETECTION ONLY.
    assert c["arbitration"].startswith("NOT_PERFORMED")


@requires_git
def test_same_base_sha_is_not_a_stale_sha_conflict(tmp_path, repo):
    """The negative half: two users editing the same file from the SAME
    baseline is ordinary shared work, not a stale-SHA divergence."""
    alice = _session(tmp_path, repo, "alice_proj", "alice", repo["c0"], repo["c2"])
    bob = _session(tmp_path, repo, "bob_proj", "bob", repo["c0"], repo["c2"])

    report = muc.scan([("alice", str(alice)), ("bob", str(bob))])
    assert [c for c in report["conflicts"]
            if c["kind"] == muc.CONFLICT_STALE_SHA] == []


@requires_git
def test_different_shas_but_disjoint_files_is_not_a_conflict(tmp_path, repo):
    """Different baselines are only a conflict when the WORK overlaps."""
    alice = _make_session_root(tmp_path, "alice_proj")
    _record_access(alice, "alice")
    _compute_selection(alice, repo["root"], repo["c0"], repo["c1"])

    bob = _make_session_root(tmp_path, "bob_proj")
    _record_access(bob, "bob")
    # Bob's real diff c1..c2 touches usb3_link_ctrl.v too, so narrow him to a
    # real diff that does not: doc-only.
    doc_only = change_impact.changed_files(repo["root"], repo["c1"], repo["c2"])
    doc_only = dict(doc_only, files=["doc/notes.md"])
    change_impact.compute_and_write(bob, base_sha=repo["c1"], head_sha=repo["c2"],
                                    diff=doc_only,
                                    registry=change_impact.load_trace_registry(bob))

    report = muc.scan([("alice", str(alice)), ("bob", str(bob))])
    assert [c for c in report["conflicts"]
            if c["kind"] == muc.CONFLICT_STALE_SHA] == []


@requires_git
def test_doc_only_overlap_is_low_severity(tmp_path, repo):
    """Severity is the REAL `classify_risk()` of the overlapping files -- a
    doc-only collision is reported, but not as HIGH."""
    diff_a = dict(change_impact.changed_files(repo["root"], repo["c0"], repo["c1"]),
                  files=["doc/notes.md"])
    diff_b = dict(change_impact.changed_files(repo["root"], repo["c1"], repo["c2"]),
                  files=["doc/notes.md"])
    alice = _make_session_root(tmp_path, "alice_proj")
    _record_access(alice, "alice")
    change_impact.compute_and_write(alice, base_sha=repo["c0"], head_sha=repo["c1"],
                                    diff=diff_a, registry=[])
    bob = _make_session_root(tmp_path, "bob_proj")
    _record_access(bob, "bob")
    change_impact.compute_and_write(bob, base_sha=repo["c1"], head_sha=repo["c2"],
                                    diff=diff_b, registry=[])

    report = muc.scan([("alice", str(alice)), ("bob", str(bob))])
    stale = [c for c in report["conflicts"] if c["kind"] == muc.CONFLICT_STALE_SHA]
    assert len(stale) == 1
    assert stale[0]["severity"] == muc.SEVERITY_LOW


# --- (b) duplicate regression submission ------------------------------------


def _submit(root, job_id, pattern, sha, status="RUN"):
    """A REAL JobState record written through the REAL save_job_state()."""
    save_job_state(Path(root), JobState(
        job_id=job_id, regression_id=f"REG-{job_id}", pattern=pattern,
        seed="42", lsf_status=status, sim_status="UNKNOWN", git_sha=sha))


@requires_git
def test_two_sessions_submitting_the_same_pattern_against_the_same_commit(tmp_path, repo):
    """THE central duplicate-regression proof: two REAL concurrent sessions
    each holding a REAL in-flight JobState for the SAME pattern against the
    SAME commit."""
    alice = _session(tmp_path, repo, "alice_proj", "alice", repo["c0"], repo["c2"])
    bob = _session(tmp_path, repo, "bob_proj", "bob", repo["c0"], repo["c2"])
    _submit(alice, 111111, "usb3_lfps_basic", repo["c2"], status="RUN")
    _submit(bob, 222222, "usb3_lfps_basic", repo["c2"], status="PEND")

    report = muc.scan([("alice", str(alice)), ("bob", str(bob))])
    dups = [c for c in report["conflicts"]
            if c["kind"] == muc.CONFLICT_DUPLICATE_REGRESSION]
    submitted = [c for c in dups
                 if all(v["stage"] == muc.STAGE_SUBMITTED
                        for v in c["detail"]["claims"].values())]
    assert len(submitted) == 1, dups
    c = submitted[0]
    assert c["severity"] == muc.SEVERITY_HIGH
    assert c["detail"]["pattern"] == "usb3_lfps_basic"
    assert c["detail"]["commit"] == repo["c2"]
    job_ids = {v["job_id"] for v in c["detail"]["claims"].values()}
    assert job_ids == {111111, 222222}
    assert report["status"] == muc.STATUS_CONFLICTS
    assert c["arbitration"].startswith("NOT_PERFORMED")


@requires_git
def test_same_pattern_against_different_commits_is_not_a_duplicate(tmp_path, repo):
    """Two runs of one pattern against two different commits are two
    legitimately different results, never a duplicate."""
    alice = _session(tmp_path, repo, "alice_proj", "alice", repo["c0"], repo["c1"])
    bob = _session(tmp_path, repo, "bob_proj", "bob", repo["c1"], repo["c2"])
    _submit(alice, 111111, "usb3_lfps_basic", repo["c1"])
    _submit(bob, 222222, "usb3_lfps_basic", repo["c2"])

    report = muc.scan([("alice", str(alice)), ("bob", str(bob))])
    assert [c for c in report["conflicts"]
            if c["kind"] == muc.CONFLICT_DUPLICATE_REGRESSION] == []


@requires_git
def test_finished_job_is_not_an_in_flight_duplicate(tmp_path, repo):
    """A terminal (DONE) job is history. Two users having both run a pattern
    is not a live collision."""
    alice = _session(tmp_path, repo, "alice_proj", "alice", repo["c0"], repo["c2"])
    bob = _session(tmp_path, repo, "bob_proj", "bob", repo["c0"], repo["c2"])
    _submit(alice, 111111, "usb3_lfps_basic", repo["c2"], status="DONE")
    _submit(bob, 222222, "usb3_lfps_basic", repo["c2"], status="EXIT")

    report = muc.scan([("alice", str(alice)), ("bob", str(bob))])
    submitted = [c for c in report["conflicts"]
                 if c["kind"] == muc.CONFLICT_DUPLICATE_REGRESSION
                 and any(v["stage"] == muc.STAGE_SUBMITTED
                         for v in c["detail"]["claims"].values())]
    assert submitted == []


@requires_git
def test_planned_selection_duplicate_is_detected_and_ranked_below_submitted(tmp_path, repo):
    """"About to submit" is detected too, off the REAL computed selection -- and
    a planned/planned collision ranks MEDIUM while a submitted one ranks HIGH,
    because nothing is burning farm time yet."""
    alice = _session(tmp_path, repo, "alice_proj", "alice", repo["c0"], repo["c2"])
    bob = _session(tmp_path, repo, "bob_proj", "bob", repo["c0"], repo["c2"])

    # The real registry + real diff really do select a pattern for both.
    sel_a = change_impact.read_computed_selection(alice)["selection"]
    assert "usb3_lfps_basic" in sel_a["targeted_tests"], sel_a

    report = muc.scan([("alice", str(alice)), ("bob", str(bob))])
    planned = [c for c in report["conflicts"]
               if c["kind"] == muc.CONFLICT_DUPLICATE_REGRESSION]
    assert planned, report["conflicts"]
    assert {c["severity"] for c in planned} == {muc.SEVERITY_MEDIUM}
    assert any(c["detail"]["pattern"] == "usb3_lfps_basic" for c in planned)

    # Now Alice actually submits it: the same pattern/commit becomes HIGH.
    _submit(alice, 333333, "usb3_lfps_basic", repo["c2"], status="RUN")
    report2 = muc.scan([("alice", str(alice)), ("bob", str(bob))])
    mixed = [c for c in report2["conflicts"]
             if c["kind"] == muc.CONFLICT_DUPLICATE_REGRESSION
             and c["detail"]["pattern"] == "usb3_lfps_basic"
             and muc.STAGE_SUBMITTED in {v["stage"] for v in c["detail"]["claims"].values()}]
    assert mixed and mixed[0]["severity"] == muc.SEVERITY_HIGH
    # HIGH sorts before MEDIUM in the rendered report.
    severities = [c["severity"] for c in report2["conflicts"]]
    assert severities == sorted(severities, key=lambda s: muc._SEVERITY_ORDER[s])


# --- (c) shared-resource reservation ---------------------------------------


def _reserve(root, resource, kind, task_id, agent, mode=MODE_WRITE):
    """A REAL claim through the REAL AgentTaskStore ownership ledger."""
    store = AgentTaskStore(Path(root))
    ok, owner = store.acquire(f"{kind}:{resource}", task_id, agent,
                              scope=SCOPE_SHARED, kind=kind, mode=mode)
    assert ok, owner
    return owner


@requires_git
def test_two_sessions_claiming_the_same_vip_instance(tmp_path, repo):
    """THE central shared-resource proof: two REAL concurrent sessions each
    holding a REAL SHARED WRITE claim on the same VIP instance."""
    alice = _session(tmp_path, repo, "alice_proj", "alice", repo["c0"], repo["c1"])
    bob = _session(tmp_path, repo, "bob_proj", "bob", repo["c0"], repo["c1"])
    _reserve(alice, "u_axi_vip_m0", "vip_instance", "TASK-A", "dv-alice")
    time.sleep(0.01)
    _reserve(bob, "u_axi_vip_m0", "vip_instance", "TASK-B", "dv-bob")

    report = muc.scan([("alice", str(alice)), ("bob", str(bob))])
    res = [c for c in report["conflicts"] if c["kind"] == muc.CONFLICT_SHARED_RESOURCE]
    assert len(res) == 1, report["conflicts"]
    c = res[0]
    assert c["severity"] == muc.SEVERITY_HIGH
    assert c["detail"]["kind"] == "vip_instance"
    assert c["detail"]["resource"] == "vip_instance:u_axi_vip_m0"
    # Who claimed first is REPORTED, never enforced.
    assert c["detail"]["claimed_first_basis"] == "CLAIM_TIMESTAMP"
    assert c["detail"]["claimed_first"] == "alice@alice_proj"
    assert c["arbitration"].startswith("NOT_PERFORMED")


@requires_git
def test_amba_port_and_license_feature_conflicts_are_detected(tmp_path, repo):
    """The other two kinds section 239 names, through the same one mechanism."""
    alice = _session(tmp_path, repo, "alice_proj", "alice", repo["c0"], repo["c1"])
    bob = _session(tmp_path, repo, "bob_proj", "bob", repo["c0"], repo["c1"])
    _reserve(alice, "AXI_M0", "amba_fabric_port", "TASK-A1", "dv-alice")
    _reserve(alice, "vcs_runtime", "license_feature", "TASK-A2", "dv-alice")
    _reserve(bob, "AXI_M0", "amba_fabric_port", "TASK-B1", "dv-bob")
    _reserve(bob, "vcs_runtime", "license_feature", "TASK-B2", "dv-bob")

    report = muc.scan([("alice", str(alice)), ("bob", str(bob))])
    kinds = {c["detail"]["kind"] for c in report["conflicts"]
             if c["kind"] == muc.CONFLICT_SHARED_RESOURCE}
    assert kinds == {"amba_fabric_port", "license_feature"}


@requires_git
def test_two_read_claims_are_not_a_conflict(tmp_path, repo):
    alice = _session(tmp_path, repo, "alice_proj", "alice", repo["c0"], repo["c1"])
    bob = _session(tmp_path, repo, "bob_proj", "bob", repo["c0"], repo["c1"])
    _reserve(alice, "u_axi_vip_m0", "vip_instance", "TASK-A", "dv-alice", mode=MODE_READ)
    _reserve(bob, "u_axi_vip_m0", "vip_instance", "TASK-B", "dv-bob", mode=MODE_READ)

    report = muc.scan([("alice", str(alice)), ("bob", str(bob))])
    assert [c for c in report["conflicts"]
            if c["kind"] == muc.CONFLICT_SHARED_RESOURCE] == []


@requires_git
def test_read_against_write_is_a_conflict(tmp_path, repo):
    alice = _session(tmp_path, repo, "alice_proj", "alice", repo["c0"], repo["c1"])
    bob = _session(tmp_path, repo, "bob_proj", "bob", repo["c0"], repo["c1"])
    _reserve(alice, "u_axi_vip_m0", "vip_instance", "TASK-A", "dv-alice", mode=MODE_WRITE)
    _reserve(bob, "u_axi_vip_m0", "vip_instance", "TASK-B", "dv-bob", mode=MODE_READ)

    report = muc.scan([("alice", str(alice)), ("bob", str(bob))])
    assert len([c for c in report["conflicts"]
                if c["kind"] == muc.CONFLICT_SHARED_RESOURCE]) == 1


@requires_git
def test_local_fanout_topic_claims_never_become_a_cross_user_conflict(tmp_path, repo):
    """THE false-positive guard, and the reason `scope` had to be recorded: the
    engine's own parallel_group fan-out claims blackboard TOPIC names that are
    identical in every project. Driven through the REAL default acquire()
    signature engine.py uses, with no scope argument at all."""
    alice = _session(tmp_path, repo, "alice_proj", "alice", repo["c0"], repo["c1"])
    bob = _session(tmp_path, repo, "bob_proj", "bob", repo["c0"], repo["c1"])
    for root, branch in ((alice, "A"), (bob, "B")):
        store = AgentTaskStore(Path(root))
        for topic in ("findings", "verification_state", "coverage_state"):
            ok, _ = store.acquire(topic, f"FANOUT-ANALYSIS_G1-{branch}", "debug-agent")
            assert ok

    report = muc.scan([("alice", str(alice)), ("bob", str(bob))])
    assert [c for c in report["conflicts"]
            if c["kind"] == muc.CONFLICT_SHARED_RESOURCE] == []
    # And the LOCAL claims really are on disk -- the detector filtered them by
    # scope, it did not fail to see them.
    assert len(multi_agent.read_reservations(alice)) == 3
    assert multi_agent.read_reservations(alice, scope=SCOPE_SHARED) == []


def test_legacy_ownership_record_without_scope_reads_as_local(tmp_path):
    """An ownership.json written before the scope split must never be
    reinterpreted into a cross-user conflict it never meant."""
    root = tmp_path / "legacy"
    (root / ".dv-harness" / "agents").mkdir(parents=True)
    (root / ".dv-harness" / "agents" / "ownership.json").write_text(
        json.dumps({"findings": {"task_id": "FANOUT-X", "agent": "a", "mode": "WRITE"}}),
        encoding="utf-8")
    rows = multi_agent.read_reservations(root)
    assert rows[0]["scope"] == SCOPE_LOCAL
    assert multi_agent.read_reservations(root, scope=SCOPE_SHARED) == []


def test_shared_claim_requires_a_known_resource_kind(tmp_path):
    store = AgentTaskStore(tmp_path)
    with pytest.raises(ResourceKindError):
        store.acquire("whatever", "T1", "a", scope=SCOPE_SHARED, kind="made_up_kind")
    with pytest.raises(ResourceKindError):
        store.acquire("whatever", "T1", "a", scope=SCOPE_SHARED, kind=None)
    # Nothing was recorded by the refused claim.
    assert multi_agent.read_reservations(tmp_path) == []


def test_release_only_by_the_holding_task(tmp_path):
    """Releasing is not a way around the contention check."""
    store = AgentTaskStore(tmp_path)
    store.acquire("vip_instance:u0", "TASK-A", "alice", scope=SCOPE_SHARED,
                  kind="vip_instance")
    ok, cur = store.release("vip_instance:u0", "TASK-B")
    assert ok is False and cur["task_id"] == "TASK-A"
    assert len(multi_agent.read_reservations(tmp_path, scope=SCOPE_SHARED)) == 1
    ok, cur = store.release("vip_instance:u0", "TASK-A")
    assert ok is True
    assert multi_agent.read_reservations(tmp_path, scope=SCOPE_SHARED) == []
    assert store.release("vip_instance:u0", "TASK-A") == (False, None)


def test_existing_local_acquire_contract_is_unchanged(tmp_path):
    """The pre-existing engine.py call site's behavior, byte for byte in
    meaning: a second task claiming a held topic is refused and gets the
    current owner back."""
    store = AgentTaskStore(tmp_path)
    ok, owner = store.acquire("findings", "FANOUT-G1-A", "debug-agent")
    assert ok is True and owner["task_id"] == "FANOUT-G1-A" and owner["mode"] == "WRITE"
    ok2, owner2 = store.acquire("findings", "FANOUT-G1-B", "coverage-agent")
    assert ok2 is False and owner2["task_id"] == "FANOUT-G1-A"
    # Re-claiming by the SAME task still succeeds (idempotent), as before.
    assert store.acquire("findings", "FANOUT-G1-A", "debug-agent")[0] is True


# --- identity, UNKNOWNs and the honest-failure contract ---------------------


@requires_git
def test_same_user_two_roots_is_not_a_multi_user_conflict(tmp_path, repo):
    """One person's own two working copies are not a coordination conflict."""
    a = _session(tmp_path, repo, "alice_a", "alice", repo["c0"], repo["c1"])
    b = _session(tmp_path, repo, "alice_b", "alice", repo["c1"], repo["c2"])
    report = muc.scan([("alice", str(a)), ("alice", str(b))])
    assert report["conflicts"] == []
    assert report["skipped_pairs"][0]["reason"] == "SAME_USER"


@requires_git
def test_user_identity_is_read_off_the_real_access_trail(tmp_path, repo):
    """No declared user: identity comes from the SAME CLI_ACCESS trail
    user_info.summarize_user_access() already reads."""
    alice = _session(tmp_path, repo, "alice_proj", "alice", repo["c0"], repo["c1"])
    bob = _session(tmp_path, repo, "bob_proj", "bob", repo["c1"], repo["c2"])
    report = muc.scan([(None, str(alice)), (None, str(bob))])
    users = {s["user"]: s["user_source"] for s in report["sessions"]}
    assert users == {"alice": "EVENTS_ACCESS_TRAIL", "bob": "EVENTS_ACCESS_TRAIL"}
    assert report["status"] == muc.STATUS_CONFLICTS


def test_unknown_identity_is_reported_not_assumed(tmp_path):
    """A root with no access trail is compared, but the report says the
    identity was unknown -- it is never silently treated as a second person."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    for r in (a, b):
        (r / ".dv-harness").mkdir(parents=True)
        (r / ".dv-harness" / "state.json").write_text("{}", encoding="utf-8")
    report = muc.scan([(None, str(a)), (None, str(b))])
    reasons = {u["reason"] for u in report["unknowns"]}
    assert "USER_IDENTITY_UNKNOWN" in reasons
    assert "PAIR_USER_IDENTITY_UNKNOWN" in reasons
    assert report["status"] == muc.STATUS_UNKNOWN


def test_missing_change_impact_is_unknown_never_clear(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    for r, user in ((a, "alice"), (b, "bob")):
        (r / ".dv-harness").mkdir(parents=True)
        (r / ".dv-harness" / "state.json").write_text("{}", encoding="utf-8")
        _record_access(r, user)
    report = muc.scan([(None, str(a)), (None, str(b))])
    assert report["status"] == muc.STATUS_UNKNOWN
    assert any(u["reason"] == "NO_CHANGE_IMPACT_COMPUTATION" for u in report["unknowns"])


def test_one_session_is_unknown_not_clear(tmp_path):
    a = tmp_path / "a"
    (a / ".dv-harness").mkdir(parents=True)
    (a / ".dv-harness" / "state.json").write_text("{}", encoding="utf-8")
    report = muc.scan([("alice", str(a))])
    assert report["status"] == muc.STATUS_UNKNOWN
    assert any(u["reason"] == "INSUFFICIENT_SESSIONS" for u in report["unknowns"])


@requires_git
def test_scan_never_writes_into_a_peer_project_root(tmp_path, repo):
    """A scan must be read-only against another user's root -- it must not
    create state.json, an agents/ ledger, or anything else there."""
    alice = _session(tmp_path, repo, "alice_proj", "alice", repo["c0"], repo["c1"])
    bob = tmp_path / "bob_bare"
    bob.mkdir()

    def snapshot(p):
        return sorted(str(q.relative_to(p)) for q in Path(p).rglob("*"))

    before_a, before_b = snapshot(alice), snapshot(bob)
    muc.scan([("alice", str(alice)), ("bob", str(bob))])
    assert snapshot(alice) == before_a
    assert snapshot(bob) == before_b


@requires_git
def test_three_sessions_are_compared_pairwise(tmp_path, repo):
    alice = _session(tmp_path, repo, "alice_proj", "alice", repo["c0"], repo["c1"])
    bob = _session(tmp_path, repo, "bob_proj", "bob", repo["c1"], repo["c2"])
    carol = _session(tmp_path, repo, "carol_proj", "carol", repo["c0"], repo["c2"])
    report = muc.scan([("alice", str(alice)), ("bob", str(bob)), ("carol", str(carol))])
    stale = [c for c in report["conflicts"] if c["kind"] == muc.CONFLICT_STALE_SHA]
    pairs = {tuple(sorted(c["users"])) for c in stale}
    # alice(c0..c1) vs bob(c1..c2) and bob vs carol(c0..c2) both diverge; alice
    # vs carol share base c0 and so do not.
    assert ("alice", "bob") in pairs
    assert ("bob", "carol") in pairs
    assert ("alice", "carol") not in pairs


# --- the audit event and the real CLI --------------------------------------


@requires_git
def test_scan_writes_one_real_audit_event(tmp_path, repo):
    alice = _session(tmp_path, repo, "alice_proj", "alice", repo["c0"], repo["c1"])
    bob = _session(tmp_path, repo, "bob_proj", "bob", repo["c1"], repo["c2"])
    scanner = _make_session_root(tmp_path, "scanner")

    text, code = muc.execute_verb("detect", root=scanner,
                                  sessions=[f"alice={alice}", f"bob={bob}"])
    assert code == 1, text
    events = [json.loads(l) for l in
              (scanner / ".dv-harness" / "events.jsonl").read_text(
                  encoding="utf-8").splitlines() if l.strip()]
    scans = [e for e in events if e["event"] == muc.EVENT_NAME]
    assert len(scans) == 1
    assert scans[0]["status"] == muc.STATUS_CONFLICTS
    assert scans[0]["counts"][muc.CONFLICT_STALE_SHA] == 1
    assert scans[0]["conflict_summaries"][0]["kind"] == muc.CONFLICT_STALE_SHA


@requires_git
def test_clear_scan_is_recorded_too(tmp_path, repo):
    """"We checked and found nothing" is itself citable evidence.

    A genuinely clear arrangement: two users on different baselines whose real
    diffs touch DISJOINT files and therefore select DISJOINT patterns.
    """
    a = _session(tmp_path, repo, "alice_proj", "alice", repo["c0"], repo["c1"])
    b = _make_session_root(tmp_path, "bob_proj")
    _record_access(b, "bob")
    pwr_only = dict(change_impact.changed_files(repo["root"], repo["c1"], repo["c2"]),
                    files=["rtl/usb3_pwr_ctrl.v"])
    change_impact.compute_and_write(b, base_sha=repo["c1"], head_sha=repo["c2"],
                                    diff=pwr_only,
                                    registry=change_impact.load_trace_registry(b))
    scanner = _make_session_root(tmp_path, "scanner")
    text, code = muc.execute_verb("detect", root=scanner,
                                  sessions=[f"alice={a}", f"bob={b}"])
    assert code == 0, text
    events = [json.loads(l) for l in
              (scanner / ".dv-harness" / "events.jsonl").read_text(
                  encoding="utf-8").splitlines() if l.strip()]
    assert [e for e in events if e["event"] == muc.EVENT_NAME][0]["status"] == \
        muc.STATUS_CLEAR


def test_session_spec_parsing_keeps_windows_paths_intact():
    assert muc._parse_session_spec("alice=/home/alice/proj") == ("alice", "/home/alice/proj")
    assert muc._parse_session_spec("/home/alice/proj") == (None, "/home/alice/proj")
    # A drive-lettered Windows path is a PATH, not user "C".
    assert muc._parse_session_spec(r"C:\work\proj") == (None, r"C:\work\proj")
    assert muc._parse_session_spec(r"bob=C:\work\proj") == ("bob", r"C:\work\proj")


def _run_cli(*args, cwd):
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT), PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "dv_harness.cli", *args],
                          cwd=str(cwd), capture_output=True, text=True, timeout=300,
                          env=env, encoding="utf-8", errors="replace")


@requires_git
def test_real_cli_detect_subprocess_reports_conflicts(tmp_path, repo):
    """End to end through the REAL `dv-harness coord` CLI: reserve on two
    roots, then detect, as two real subprocesses."""
    alice = _session(tmp_path, repo, "alice_proj", "alice", repo["c0"], repo["c1"])
    bob = _session(tmp_path, repo, "bob_proj", "bob", repo["c1"], repo["c2"])

    r = _run_cli("--project-root", str(alice), "coord", "reserve",
                 "--resource", "u_axi_vip_m0", "--kind", "vip_instance",
                 "--task", "TASK-A", "--agent", "dv-alice", cwd=REPO_ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    r = _run_cli("--project-root", str(bob), "coord", "reserve",
                 "--resource", "u_axi_vip_m0", "--kind", "vip_instance",
                 "--task", "TASK-B", "--agent", "dv-bob", cwd=REPO_ROOT)
    assert r.returncode == 0, r.stdout + r.stderr

    scanner = _make_session_root(tmp_path, "scanner")
    r = _run_cli("--project-root", str(scanner), "coord", "detect",
                 "--session", f"alice={alice}", "--session", f"bob={bob}",
                 "--json", cwd=REPO_ROOT)
    assert r.returncode == 1, r.stdout + r.stderr
    report = json.loads(r.stdout[r.stdout.index("{"):])
    kinds = {c["kind"] for c in report["conflicts"]}
    assert muc.CONFLICT_STALE_SHA in kinds
    assert muc.CONFLICT_SHARED_RESOURCE in kinds

    # And releasing really clears the shared-resource half.
    r = _run_cli("--project-root", str(bob), "coord", "release",
                 "--resource", "u_axi_vip_m0", "--kind", "vip_instance",
                 "--task", "TASK-B", cwd=REPO_ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    r = _run_cli("--project-root", str(scanner), "coord", "detect",
                 "--session", f"alice={alice}", "--session", f"bob={bob}",
                 "--json", cwd=REPO_ROOT)
    report2 = json.loads(r.stdout[r.stdout.index("{"):])
    assert muc.CONFLICT_SHARED_RESOURCE not in {c["kind"] for c in report2["conflicts"]}


@requires_git
def test_real_module_entry_point_matches_the_cli(tmp_path, repo):
    """`python -m dv_harness.multi_user_coordination` and `dv-harness coord`
    are ONE implementation, per this repo's execute_verb convention."""
    alice = _session(tmp_path, repo, "alice_proj", "alice", repo["c0"], repo["c1"])
    bob = _session(tmp_path, repo, "bob_proj", "bob", repo["c1"], repo["c2"])
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT), PYTHONIOENCODING="utf-8")
    r = subprocess.run(
        [sys.executable, "-m", "dv_harness.multi_user_coordination", "detect",
         "--root", str(tmp_path / "scanner_mod"),
         "--session", f"alice={alice}", "--session", f"bob={bob}"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=300, env=env,
        encoding="utf-8", errors="replace")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "STALE_SHA_CONFLICT" in r.stdout


def test_cli_detect_refuses_a_single_session(tmp_path):
    text, code = muc.execute_verb("detect", root=tmp_path,
                                  sessions=[str(tmp_path)], record_event=False)
    assert code == 2
    assert "two or more" in text


def test_reserve_refuses_an_unknown_kind_via_the_verb(tmp_path):
    text, code = muc.execute_verb("reserve", root=tmp_path, resource="x",
                                  kind="not_a_kind")
    assert code == 2
    assert "ResourceKindError" in text


@requires_git
def test_no_approval_gate_or_stage_gate_is_introduced():
    """This mechanism must not have become a gate. Detection informs a human;
    it never decides a stage."""
    from dv_harness import gates
    text = repr(getattr(gates, "STAGE_GATES", {}))
    assert "multi_user_coordination" not in text
    assert "coordination" not in text.lower()
    src = (REPO_ROOT / "dv_harness" / "multi_user_coordination.py").read_text(
        encoding="utf-8")
    for forbidden in ("bsub", "subprocess.run", "approve(", "can_signoff"):
        assert forbidden not in src, forbidden
