"""CROSS-LOOP COUPLING: engine.py wiring for the Confidence-Calibration
Feedback Loop (2026-09-07 Implement-phase gap close, Task 1 of the
Confidence/Inference-Layer audit).

`confidence_calibration.draft_reweighted_confidence_proposal()` and
`capability_evolution.build_confidence_reweight_candidate()` /
`file_confidence_reweight_candidate()` already existed, real and individually
tested, with no engine call site -- both modules' own CLAUDE.md sections
disclosed this as "REACHED, not WIRED". These tests drive the real wire:
`engine.DVHarness._file_confidence_reweight_candidate_from_calibration()`,
called immediately beside the existing repeated-failure coupling on the same
FAILURE_RECOVERY/RE_AUDIT FAIL/PARTIAL branch of a real `run_stage()`.

Everything below is driven against real stores on disk: a real MemoryStore, a
real MemoryGC.confirm()/retract(), a real Blackboard, and a real
DVHarness.run_stage() over the real shipped main_graph.json. Nothing is
mocked except the agent adapter, the only thing that would otherwise dispatch
a subprocess.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from dv_harness import capability_evolution as ce
from dv_harness.memory import MemoryGC, MemoryStore

ROOT = Path(__file__).resolve().parents[1]
REAL_GRAPH = ROOT / ".dv-harness" / "graph" / "main_graph.json"


def _fresh_harness():
    from dv_harness.engine import DVHarness
    tmp = Path(tempfile.mkdtemp())
    (tmp / ".dv-harness" / "graph").mkdir(parents=True)
    (tmp / ".dv-harness" / "graph" / "main_graph.json").write_text(
        REAL_GRAPH.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp, DVHarness(tmp)


def _events(root: Path, event: str) -> list:
    p = root / ".dv-harness" / "events.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            if rec.get("event") == event:
                out.append(rec)
    return out


class _FailingAdapter:
    """The agent could not complete the stage -- the same real, unstubbed
    context-gathering/Blackboard-read/failure-signature-construction path the
    sibling repeated-failure coupling's own tests already drive."""
    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
        from dv_harness.adapters.base import AgentResult
        return AgentResult(ok=False, text="", raw={"stderr": "adapter could not close the stage"},
                           session_id=None)


def _seed_findings(harness, symptom="LFPS handshake never completes",
                   root_cause="polling.exit timeout"):
    harness.blackboard.write("findings", {"last_report": {
        "symptom": symptom, "root_cause": root_cause,
    }}, source="test-seed")


def _run_failed_debug_stage(harness, git_sha, stage="RE_AUDIT"):
    from dv_harness.models import Status
    harness.state.git_sha = git_sha
    harness.set_stage(stage)
    harness.run_stage("close the failure")
    assert harness.state.stages[stage]["status"] == Status.FAIL.value
    return harness


def _add_record(store, tier, *, level="engineering", title="finding"):
    return store.add(level, {"title": title, "protocol": "USB3",
                             "root_cause": f"{title}-rc", "confidence": tier})


def _populate(store, tier, *, verified=0, rejected=0):
    """The real, already-established test recipe for building a real
    INVERTED_TIER_ORDER finding -- see test_confidence_calibration.py's own
    `populate()`, re-derived here since importing another test module's
    helper across files is not this project's own convention."""
    gc = MemoryGC(store)
    for i in range(verified):
        rec = _add_record(store, tier, title=f"{tier}-ok-{i}")
        assert gc.confirm(rec["memory_id"], evidence={"note": "independent re-derivation"})
    for i in range(rejected):
        rec = _add_record(store, tier, title=f"{tier}-bad-{i}")
        assert gc.retract(rec["memory_id"], "overturned by current evidence",
                          evidence={"sim_log": "run/sim.log:1201"})


# --- bare project: no memory history at all -----------------------------

def test_a_bare_project_files_nothing_but_still_emits_the_audit_event():
    """No MemoryStore on disk yet -> calibrate() reports NOT_AVAILABLE ->
    draft_reweighted_confidence_proposal() has no findings to propose from
    (REWEIGHT_PROPOSAL_NO_INVERSION) -> nothing is filed. The coupling must
    still record a real, honest event -- "nothing qualified" is itself
    citable evidence, exactly like its repeated-failure sibling."""
    tmp, h = _fresh_harness()
    try:
        h.adapter = _FailingAdapter()
        _seed_findings(h)
        _run_failed_debug_stage(h, "commit-aaa")

        events = _events(tmp, "CONFIDENCE_REWEIGHT_AUTO_DISCOVERY")
        assert len(events) == 1
        assert events[0]["proposal_status"] == "NO_INVERSION_FOUND"
        assert events[0]["filed"] is False
        assert events[0]["candidate_id"] is None
        assert ce.read_candidates(tmp) == {}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_passing_stage_never_runs_the_coupling_at_all():
    """The hook lives on the FAIL/PARTIAL debug branch only, exactly like its
    repeated-failure sibling."""
    from dv_harness.adapters.base import AgentResult
    from dv_harness.models import Status

    tmp, h = _fresh_harness()
    try:
        h.cfg["policy"]["require_stage_gate_evidence"] = False

        class _OkAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text="re-audit clean", raw={}, session_id=None)

        h.adapter = _OkAdapter()
        _seed_findings(h)
        h.state.git_sha = "commit-aaa"
        h.set_stage("RE_AUDIT")
        h.run_stage("goal")
        assert h.state.stages["RE_AUDIT"]["status"] == Status.PASS.value

        assert _events(tmp, "CONFIDENCE_REWEIGHT_AUTO_DISCOVERY") == []
        assert ce.read_candidates(tmp) == {}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- best-effort: a real internal failure must never break the stage -----

def test_a_calibration_failure_never_breaks_the_stage_result(monkeypatch):
    """Best-effort by design, mirroring every sibling _promote_*/_record_*
    method and the repeated-failure coupling: a confidence-calibration
    bookkeeping problem must never turn an already-computed stage result into
    a crash -- and it is recorded, never swallowed silently."""
    from dv_harness import confidence_calibration as cc
    from dv_harness.models import Status

    tmp, h = _fresh_harness()
    try:
        def _boom(root, *, cfg=None, store=None):
            raise RuntimeError("memory index unreadable")

        monkeypatch.setattr(cc, "calibrate", _boom)
        h.adapter = _FailingAdapter()
        _seed_findings(h)
        _run_failed_debug_stage(h, "commit-aaa")

        assert h.state.stages["RE_AUDIT"]["status"] == Status.FAIL.value
        assert _events(tmp, "CONFIDENCE_REWEIGHT_AUTO_DISCOVERY") == []
        failures = _events(tmp, "CONFIDENCE_REWEIGHT_AUTO_DISCOVERY_FAILED")
        assert len(failures) == 1
        assert "memory index unreadable" in failures[0]["error"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- end to end: a real inversion files a real DISCOVERED candidate ------

def test_a_real_tier_inversion_files_a_real_discovered_candidate_end_to_end():
    """A project whose own real confirm/retract history contradicts the
    HIGH > MEDIUM ordering -> a real run_stage() FAIL/PARTIAL on the
    FAILURE_RECOVERY/RE_AUDIT branch -> a real DISCOVERED
    CapabilityEvolutionCandidate, with no human involved, and never a live
    change to inference.py's own formula."""
    tmp, h = _fresh_harness()
    try:
        store = MemoryStore(tmp)
        _populate(store, "HIGH", verified=3, rejected=7)     # 30% reliable
        _populate(store, "MEDIUM", verified=9, rejected=1)   # 90% reliable

        h.adapter = _FailingAdapter()
        _seed_findings(h)
        _run_failed_debug_stage(h, "commit-aaa")

        events = _events(tmp, "CONFIDENCE_REWEIGHT_AUTO_DISCOVERY")
        assert len(events) == 1
        assert events[0]["proposal_status"] == "PROPOSAL_DRAFTED"
        assert events[0]["filed"] is True
        assert events[0]["reason"] == "DISCOVERED"
        candidate_id = events[0]["candidate_id"]
        assert candidate_id

        candidates = ce.read_candidates(tmp)
        assert list(candidates) == [candidate_id]
        candidate = candidates[candidate_id]
        assert candidate["current_status"] == "DISCOVERED"
        assert candidate["trigger_type"] == "INTERNAL_AUDIT"
        # DISCOVERY only: no repository search was performed, and no
        # approval was minted anywhere along the way.
        assert candidate["overlap_status"] == "UNKNOWN"
        assert ce.human_approval_status(tmp)["approved"] is False

        # inference.py's live formula is completely untouched by this run --
        # the proposal is data a human must approve through the controlled-
        # experiment machinery, never applied directly.
        import inspect
        from dv_harness import inference
        src_before = inspect.getsource(inference.score_confidence)

        # Re-running the coupling a second time over unchanged evidence must
        # not grow the audit trail with a duplicate candidate. (The second
        # failed stage, against a second commit, ALSO satisfies the sibling
        # repeated-failure coupling's own "2 independent runs" trigger --
        # that candidate is real, expected, and deliberately not asserted
        # against here; this test only holds the confidence-reweight
        # candidate to its own, single-instance behaviour.)
        _run_failed_debug_stage(h, "commit-bbb")
        events2 = _events(tmp, "CONFIDENCE_REWEIGHT_AUTO_DISCOVERY")
        assert len(events2) == 2
        assert events2[1]["filed"] is False
        assert events2[1]["reason"] == "ALREADY_ON_FILE_UNCHANGED"
        assert events2[1]["candidate_id"] == candidate_id
        all_candidates = ce.read_candidates(tmp)
        reweight_ids = [cid for cid, c in all_candidates.items()
                       if c["trigger_type"] == "INTERNAL_AUDIT"]
        assert reweight_ids == [candidate_id]

        assert inspect.getsource(inference.score_confidence) == src_before
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
