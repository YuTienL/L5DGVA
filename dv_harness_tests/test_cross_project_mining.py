"""CROSS-PROJECT PATTERN MINING (VI-2, 2026-09-05).

The per-project memory tiers were real; the tier ABOVE them -- "the same root
cause keeps recurring across our projects, and one of them already fixed it"
-- was not computable by anything in this harness.

Every test below drives REAL stores on disk. Each "project" is its own
temporary root with its own real `memory.MemoryStore`, populated through the
real `memory_router.route_and_store()` with the exact record shapes
`engine._record_debug_attempt_job_memory()` and
`engine._promote_verified_fix_knowledge()` write, and the failure signatures
come from the real `memory_vault.build_failure_signature()`. Nothing is
mocked, no fixture JSON is hand-typed into a store file, and no second real
project is synthesised out of this repo's own audit trail -- the test that
COPIES a project store exists precisely to prove that doing so is refused.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness import cross_project_mining as cpm
from dv_harness.evidence_db import signature_key
from dv_harness.memory import MemoryStore
from dv_harness.memory_router import route_and_store
from dv_harness.memory_vault import build_failure_signature

REPO_ROOT = Path(__file__).resolve().parents[1]

SYMPTOM_A = "AXI write response never returns on slave port 2"
CAUSE_A = "wready deasserted while the interconnect held wvalid"
SYMPTOM_B = "USB3 LFPS handshake never completes on port 0"
CAUSE_B = "polling.exit timeout while RX detect stays low"


# --------------------------------------------------------------------------
# Real project fixtures -- each one a separately constructed memory store
# --------------------------------------------------------------------------

def _signature(symptom=SYMPTOM_A, cause=CAUSE_A, protocol="AMBA4"):
    return build_failure_signature(protocol=protocol, symptom=symptom,
                                   root_cause_hint=cause)


def _job_failure(root: Path, signature: dict, *, git_sha=None, job_id=None,
                 stage="RE_AUDIT", attempt=1) -> dict:
    """One real Job Memory record through the real router, with the field set
    engine._record_debug_attempt_job_memory() actually writes."""
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
        "git_sha": git_sha,
    }
    if job_id is not None:
        record["job_id"] = job_id
    routed = route_and_store(root, record, cfg={})
    assert routed["destination"] == "JOB_MEMORY", routed
    return routed


def _verified_fix(root: Path, *, root_cause=CAUSE_A, symptom=SYMPTOM_A,
                  protocol="AMBA4") -> dict:
    """One real Engineering Memory verified_fix record, the shape
    engine._promote_verified_fix_knowledge() writes on a gate-verified
    RE_AUDIT close."""
    record = {
        "kind": "verified_fix",
        "verified": True,
        "title": f"Verified fix: {root_cause}",
        "scope": "engineering",
        "symptoms": [symptom],
        "root_cause": root_cause,
        "fix": "rtl commit 5e1f00d",
        "evidence": ["sim.log:9120", "fsdb:axi_wr_resp"],
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


@pytest.fixture
def workspace():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _project(workspace: Path, name: str) -> Path:
    """A real, empty project root with a real MemoryStore initialised."""
    root = workspace / name
    root.mkdir(parents=True, exist_ok=True)
    MemoryStore(root)  # real store, real index.json
    return root


def _entry(pid: str, root: Path):
    return {"project_id": pid, "root": str(root)}


def _memory_snapshot(root: Path):
    """Every memory file under a project and its exact bytes."""
    base = cpm.memory_store_dir(root)
    if not base.exists():
        return {}
    return {str(p.relative_to(base)): p.read_bytes()
            for p in sorted(base.rglob("*")) if p.is_file()}


# --------------------------------------------------------------------------
# The registry, and the guard that keeps "two projects" meaning two projects
# --------------------------------------------------------------------------

def test_registry_refuses_a_root_with_no_memory_store(workspace):
    """An empty tree is not a project that agrees with nothing -- it is not a
    project at all, and admitting it would let it pad the project count."""
    bare = workspace / "no_store"
    bare.mkdir()
    host = _project(workspace, "host")
    with pytest.raises(cpm.CrossProjectRegistryError) as exc:
        cpm.ProjectRegistry(host).register(bare, project_id="ghost")
    assert "no memory store" in str(exc.value)
    # and the probe did not bring one into existence
    assert not cpm.memory_store_dir(bare).exists()


def test_registry_refuses_duplicate_id_and_duplicate_root(workspace):
    host = _project(workspace, "host")
    a = _project(workspace, "proj_a")
    b = _project(workspace, "proj_b")
    reg = cpm.ProjectRegistry(host)
    reg.register(a, project_id="A")

    with pytest.raises(cpm.CrossProjectRegistryError):
        reg.register(b, project_id="A")          # id taken
    with pytest.raises(cpm.CrossProjectRegistryError):
        reg.register(a, project_id="A_again")    # root taken
    assert [e["project_id"] for e in reg.entries()] == ["A"]


def test_one_store_under_two_names_is_refused(workspace):
    """THE anti-fabrication guard. A byte-for-byte copy of a project's tree
    carries the same memory_ids, so registering it as a second "project"
    would manufacture a two-project consensus out of one project's audit
    trail. That is exactly the move this gap's brief forbids, and it is
    refused by the mechanism rather than by discipline."""
    host = _project(workspace, "host")
    a = _project(workspace, "proj_a")
    _job_failure(a, _signature(), git_sha="c-1")

    clone = workspace / "proj_a_copy"
    shutil.copytree(a, clone)

    reg = cpm.ProjectRegistry(host)
    reg.register(a, project_id="A")
    with pytest.raises(cpm.ProjectIdentityCollisionError) as exc:
        reg.register(clone, project_id="A_pretending_to_be_B")
    assert "one store under two names" in str(exc.value)
    assert [e["project_id"] for e in reg.entries()] == ["A"]


def test_registry_survives_a_round_trip_and_unregister(workspace):
    host = _project(workspace, "host")
    a, b = _project(workspace, "proj_a"), _project(workspace, "proj_b")
    _job_failure(a, _signature(), git_sha="c-1")
    _job_failure(b, _signature(symptom=SYMPTOM_B, cause=CAUSE_B), git_sha="c-2")

    reg = cpm.ProjectRegistry(host)
    reg.register(a, project_id="A")
    reg.register(b, project_id="B")

    reread = cpm.ProjectRegistry(host)
    assert [e["project_id"] for e in reread.roots()] == ["A", "B"]
    assert reread.unregister("A") is True
    assert reread.unregister("A") is False
    assert [e["project_id"] for e in cpm.ProjectRegistry(host).roots()] == ["B"]


def test_registry_operations_are_audited_in_the_real_events_log(workspace):
    host = _project(workspace, "host")
    a = _project(workspace, "proj_a")
    _job_failure(a, _signature(), git_sha="c-1")
    cpm.ProjectRegistry(host).register(a, project_id="A")

    events = [json.loads(line) for line in
              (host / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").splitlines()
              if line.strip()]
    assert [e["type"] for e in events if e["type"] == cpm.EVENT_REGISTER]
    reg_event = [e for e in events if e["type"] == cpm.EVENT_REGISTER][0]
    assert reg_event["project_id"] == "A"
    assert reg_event["root"] == str(a.resolve())


# --------------------------------------------------------------------------
# Mining: what counts as a cross-project pattern
# --------------------------------------------------------------------------

def test_one_project_never_yields_a_cross_project_pattern(workspace):
    """The honest answer about the SAMPLE. One project that recorded a failure
    many times is a single-project pattern -- which
    capability_evolution.repeated_unresolved_failure_patterns() already
    reports -- and calling it cross-project would be a false claim about how
    widely it was observed."""
    a = _project(workspace, "proj_a")
    sig = _signature()
    for i in range(5):
        _job_failure(a, sig, git_sha=f"c-{i}")

    report = cpm.mine_cross_project_patterns([_entry("A", a)])
    assert report["status"] == cpm.STATUS_INSUFFICIENT_PROJECTS
    assert report["cross_project_patterns"] == []
    assert "NO cross-project pattern is reported" in report["disclosure"]

    # Not silently dropped: the finding is still visible, correctly labelled,
    # and its five independent runs are still counted.
    assert len(report["single_project_patterns"]) == 1
    single = report["single_project_patterns"][0]
    assert single["project_ids"] == ["A"]
    assert single["total_independent_run_count"] == 5


def test_min_projects_below_two_is_refused():
    with pytest.raises(ValueError) as exc:
        cpm.mine_cross_project_patterns([], min_projects=1)
    assert "must be at least 2" in str(exc.value)


def test_the_same_signature_in_two_real_projects_is_a_cross_project_pattern(workspace):
    """Three separately built stores. A and B independently record the same
    real failure signature; C records a different one."""
    a, b, c = (_project(workspace, n) for n in ("proj_a", "proj_b", "proj_c"))
    shared = _signature()
    other = _signature(symptom=SYMPTOM_B, cause=CAUSE_B, protocol="USB3")

    _job_failure(a, shared, git_sha="a-1")
    _job_failure(a, shared, git_sha="a-2")
    _job_failure(b, shared, job_id="lsf-88101")
    _job_failure(c, other, git_sha="c-1")

    report = cpm.mine_cross_project_patterns(
        [_entry("A", a), _entry("B", b), _entry("C", c)])
    assert report["status"] == cpm.STATUS_OK
    assert report["projects_mined"] == 3

    assert len(report["cross_project_patterns"]) == 1
    pattern = report["cross_project_patterns"][0]
    assert pattern["project_ids"] == ["A", "B"]
    assert pattern["project_count"] == 2
    # Identity is the SHARED evidence_db hash, never a second definition.
    assert pattern["signature_key"] == signature_key(shared)
    # Per-project basis is present so a reader can re-derive the conclusion.
    assert pattern["per_project"]["A"]["independent_run_count"] == 2
    assert pattern["per_project"]["B"]["run_identities"] == ["job_id:lsf-88101"]
    assert len(pattern["per_project"]["A"]["memory_ids"]) == 2

    # C's own failure is reported, as a single-project pattern.
    assert [p["project_ids"] for p in report["single_project_patterns"]] == [["C"]]


def test_forty_runs_in_one_project_are_one_project_observation(workspace):
    """_run_identity()'s discipline lifted one level. Forty runs of one
    environment are forty reports of one project's circumstances; only a
    SECOND project makes the observation independent."""
    a, b = _project(workspace, "proj_a"), _project(workspace, "proj_b")
    sig = _signature()
    for i in range(40):
        _job_failure(a, sig, git_sha=f"a-{i}")
    _job_failure(b, _signature(symptom=SYMPTOM_B, cause=CAUSE_B), git_sha="b-1")

    report = cpm.mine_cross_project_patterns([_entry("A", a), _entry("B", b)])
    assert report["status"] == cpm.STATUS_OK
    assert report["cross_project_patterns"] == []          # 40 != 2 projects
    heavy = [p for p in report["single_project_patterns"] if p["project_ids"] == ["A"]][0]
    assert heavy["total_independent_run_count"] == 40


def test_retries_against_one_commit_stay_one_run_inside_a_project(workspace):
    a, b = _project(workspace, "proj_a"), _project(workspace, "proj_b")
    sig = _signature()
    _job_failure(a, sig, git_sha="a-1", attempt=1)
    _job_failure(a, sig, git_sha="a-1", attempt=2)
    _job_failure(a, sig, git_sha="a-1", stage="FAILURE_RECOVERY", attempt=1)
    _job_failure(b, sig, git_sha="b-1")

    pattern = cpm.mine_cross_project_patterns(
        [_entry("A", a), _entry("B", b)])["cross_project_patterns"][0]
    assert pattern["per_project"]["A"]["independent_run_count"] == 1
    assert pattern["per_project"]["A"]["occurrence_count"] == 3


# --------------------------------------------------------------------------
# The finding that only exists at this level: a transferable fix
# --------------------------------------------------------------------------

def test_a_fix_verified_in_one_project_is_surfaced_for_the_project_that_still_has_it_open(workspace):
    a, b = _project(workspace, "proj_a"), _project(workspace, "proj_b")
    sig = _signature()
    _job_failure(a, sig, git_sha="a-1")
    fix = _verified_fix(a)                      # A closed it, gate-verified
    _job_failure(b, sig, git_sha="b-1")         # B still has it open

    report = cpm.mine_cross_project_patterns([_entry("A", a), _entry("B", b)])
    pattern = report["cross_project_patterns"][0]
    assert pattern["resolved_in_projects"] == ["A"]
    assert pattern["unresolved_in_projects"] == ["B"]

    transfer = pattern["transferable_fix"]
    assert transfer is not None
    assert transfer["fixed_in"] == ["A"]
    assert transfer["open_in"] == ["B"]
    # The real memory_id of A's real verified_fix record, so the finding is
    # citable rather than a summary.
    assert [f["memory_id"] for f in transfer["fix_records"]] == [fix["memory_id"]]
    assert report["transferable_fix_count"] == 1


def test_no_transfer_when_nobody_fixed_it_and_none_when_everybody_did(workspace):
    a, b = _project(workspace, "proj_a"), _project(workspace, "proj_b")
    sig = _signature()
    _job_failure(a, sig, git_sha="a-1")
    _job_failure(b, sig, git_sha="b-1")

    open_everywhere = cpm.mine_cross_project_patterns(
        [_entry("A", a), _entry("B", b)])["cross_project_patterns"][0]
    assert open_everywhere["transferable_fix"] is None
    assert open_everywhere["resolved_in_projects"] == []

    _verified_fix(a)
    _verified_fix(b)
    fixed_everywhere = cpm.mine_cross_project_patterns(
        [_entry("A", a), _entry("B", b)])["cross_project_patterns"][0]
    assert fixed_everywhere["resolved_in_projects"] == ["A", "B"]
    assert fixed_everywhere["transferable_fix"] is None


def test_an_explanation_is_not_a_closure(workspace):
    """A bare root_cause/debug_lesson record explains a failure; only a
    gate-verified `verified_fix` closes it. Offering an explanation to another
    project as a transferable FIX is the expensive error, so it must not
    count -- capability_evolution's own reasoning, held here too."""
    a, b = _project(workspace, "proj_a"), _project(workspace, "proj_b")
    sig = _signature()
    _job_failure(a, sig, git_sha="a-1")
    _job_failure(b, sig, git_sha="b-1")
    route_and_store(a, {"kind": "root_cause", "verified": True, "scope": "engineering",
                        "title": "explanation only", "root_cause": CAUSE_A,
                        "symptoms": [SYMPTOM_A], "protocol": "AMBA4",
                        "confidence": "HIGH"}, cfg={})

    pattern = cpm.mine_cross_project_patterns(
        [_entry("A", a), _entry("B", b)])["cross_project_patterns"][0]
    assert pattern["resolved_in_projects"] == []
    assert pattern["transferable_fix"] is None


# --------------------------------------------------------------------------
# The boundary: this miner reads, and only reads
# --------------------------------------------------------------------------

def test_mining_writes_nothing_to_any_mined_project(workspace):
    a, b = _project(workspace, "proj_a"), _project(workspace, "proj_b")
    sig = _signature()
    _job_failure(a, sig, git_sha="a-1")
    _verified_fix(a)
    _job_failure(b, sig, git_sha="b-1")

    before = {"A": _memory_snapshot(a), "B": _memory_snapshot(b)}
    report = cpm.mine_cross_project_patterns([_entry("A", a), _entry("B", b)])
    assert report["cross_project_patterns"]          # it really did find something
    after = {"A": _memory_snapshot(a), "B": _memory_snapshot(b)}
    assert before == after, "mining mutated a mined project's memory store"

    # And specifically: nothing reached the organizational tier.
    for root in (a, b):
        assert MemoryStore(root).find("organizational") == []


def test_mining_never_creates_a_store_in_a_root_that_has_none(workspace):
    """A miner reading someone else's tree must not bring a store into
    existence and then report it as an empty project."""
    a = _project(workspace, "proj_a")
    _job_failure(a, _signature(), git_sha="a-1")
    bare = workspace / "not_a_project"
    bare.mkdir()

    report = cpm.mine_cross_project_patterns([_entry("A", a), _entry("BARE", bare)])
    assert not cpm.memory_store_dir(bare).exists()
    bare_row = [p for p in report["projects"] if p["project_id"] == "BARE"][0]
    assert bare_row["readable"] is False
    assert bare_row["skipped_reason"] == cpm.SKIP_NO_MEMORY_STORE
    assert report["projects_mined"] == 1
    assert report["status"] == cpm.STATUS_INSUFFICIENT_PROJECTS


def test_a_hand_edited_registry_cannot_smuggle_one_store_in_twice(workspace):
    """The registry file is editable text, so the identity guard cannot live
    only on the write path. Mining re-checks the roots it is actually
    handed."""
    host = _project(workspace, "host")
    a = _project(workspace, "proj_a")
    _job_failure(a, _signature(), git_sha="a-1")
    clone = workspace / "proj_a_copy"
    shutil.copytree(a, clone)

    registry_path = host / cpm.REGISTRY_RELPATH
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps({
        "version": 1, "host_root": str(host),
        "projects": [{"project_id": "A", "root": str(a)},
                     {"project_id": "B", "root": str(clone)}],
    }), encoding="utf-8")

    report = cpm.mine_registered_projects(host)
    assert report["registered_project_count"] == 2
    assert report["projects_mined"] == 1
    assert report["status"] == cpm.STATUS_INSUFFICIENT_PROJECTS
    assert report["cross_project_patterns"] == []
    assert report["identity_collisions"][0]["project_id"] == "B"
    assert report["identity_collisions"][0]["collides_with"] == "A"


def test_promotion_readiness_reports_and_never_promotes(workspace):
    a, b = _project(workspace, "proj_a"), _project(workspace, "proj_b")
    sig = _signature()
    _job_failure(a, sig, git_sha="a-1")
    _verified_fix(a)
    _job_failure(b, sig, git_sha="b-1")

    pattern = cpm.mine_cross_project_patterns(
        [_entry("A", a), _entry("B", b)])["cross_project_patterns"][0]
    readiness = pattern["promotion_readiness"]
    assert readiness["eligible_for_promotion_review"] is True
    assert readiness["blocking"] == []
    assert "promote_to_organizational" in readiness["promotion_path"]
    assert "never promotes" in readiness["promotion_path"]
    # "eligible for REVIEW" mints nothing: the tier is still empty.
    for root in (a, b):
        assert MemoryStore(root).find("organizational") == []


def test_an_open_pattern_is_a_question_not_knowledge(workspace):
    a, b = _project(workspace, "proj_a"), _project(workspace, "proj_b")
    sig = _signature()
    _job_failure(a, sig, git_sha="a-1")
    _job_failure(b, sig, git_sha="b-1")
    pattern = cpm.mine_cross_project_patterns(
        [_entry("A", a), _entry("B", b)])["cross_project_patterns"][0]
    readiness = pattern["promotion_readiness"]
    assert readiness["eligible_for_promotion_review"] is False
    assert any("verified_fix" in reason for reason in readiness["blocking"])


# --------------------------------------------------------------------------
# Audit trail and honest production status
# --------------------------------------------------------------------------

def test_a_mining_pass_that_found_nothing_is_still_recorded(workspace):
    """capability_evolution's own convention: every outcome, including
    "nothing qualified", is one event -- a pass on which nothing qualified is
    itself citable evidence."""
    host = _project(workspace, "host")
    a = _project(workspace, "proj_a")
    _job_failure(a, _signature(), git_sha="a-1")
    cpm.ProjectRegistry(host).register(a, project_id="A")

    report = cpm.mine_registered_projects(host)
    assert report["status"] == cpm.STATUS_INSUFFICIENT_PROJECTS

    events = [json.loads(line) for line in
              (host / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").splitlines()
              if line.strip()]
    mine_events = [e for e in events if e["type"] == cpm.EVENT_MINE]
    assert len(mine_events) == 1
    assert mine_events[0]["status"] == cpm.STATUS_INSUFFICIENT_PROJECTS
    assert mine_events[0]["cross_project_pattern_count"] == 0


def test_production_status_is_computed_not_claimed(workspace):
    host = _project(workspace, "host")
    a, b = _project(workspace, "proj_a"), _project(workspace, "proj_b")
    _job_failure(a, _signature(), git_sha="a-1")
    _job_failure(b, _signature(symptom=SYMPTOM_B, cause=CAUSE_B), git_sha="b-1")

    empty = cpm.production_status(host)
    assert empty["registered_project_count"] == 0
    assert empty["can_produce_cross_project_result"] is False

    reg = cpm.ProjectRegistry(host)
    reg.register(a, project_id="A")
    assert cpm.production_status(host)["can_produce_cross_project_result"] is False
    reg.register(b, project_id="B")
    assert cpm.production_status(host)["can_produce_cross_project_result"] is True


def test_this_repository_honestly_reports_no_production_cross_project_result():
    """The disclosure this gap's brief requires, asserted rather than
    narrated: this repo is ONE project with ONE memory store, so it has no
    second real project to mine and produces no production finding. The test
    is a pure read of the real repo root -- it registers nothing."""
    status = cpm.production_status(REPO_ROOT)
    assert status["registered_with_readable_store"] < cpm.CROSS_PROJECT_MIN_PROJECTS
    assert status["can_produce_cross_project_result"] is False
    assert "cannot be inflated" in status["disclosure"]


def test_the_miner_reuses_the_shared_failure_identity_and_kinds():
    """Guards the consolidation rule itself: if someone later gives this
    module its own hash or its own idea of "a closed failure", these
    identities break and this test fails."""
    from dv_harness import capability_evolution as ce

    assert cpm.REPEAT_FAILURE_JOB_MEMORY_KIND is ce.REPEAT_FAILURE_JOB_MEMORY_KIND
    assert cpm.RESOLVING_ENGINEERING_MEMORY_KIND is ce.RESOLVING_ENGINEERING_MEMORY_KIND
    assert cpm.CROSS_PROJECT_MIN_PROJECTS == ce.REPEAT_FAILURE_MIN_OCCURRENCES
    sig = _signature()
    assert cpm.project_failure_index  # module-level miner, not a copy in a test
    assert signature_key(sig) == signature_key(dict(sig))
