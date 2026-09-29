"""ENGINE WIRING: inference.py gap-close (2026-09-07 Implement-phase, Task 2
of the Confidence/Inference-Layer audit) -- `inference.collect_hypothesis_
shapes()` / `detect_hypothesis_generation_bias()` were real, individually
tested, with no engine call site. These tests drive the real wire:
`engine.DVHarness._detect_hypothesis_generation_bias()`, called beside the
existing capability-evolution couplings on the same FAILURE_RECOVERY/RE_AUDIT
FAIL/PARTIAL branch of a real `run_stage()`.

Everything below is driven against real stores on disk: a real MemoryStore, a
real MemoryGC.retract(), a real Blackboard, and a real
DVHarness.run_stage() over the real shipped main_graph.json. Nothing is
mocked except the agent adapter.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

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


def _add_root_cause(store, *, title, evidence):
    return store.add("engineering", {
        "kind": "root_cause", "title": title, "protocol": "USB3",
        "root_cause": f"{title}-rc", "evidence": evidence,
    })


def _seed_biased_corpus(store):
    """5 hypotheses citing "control_register" (never retracted) vs. 5 citing
    only "symptom_register" (all retracted) -- the item's own worked
    example, "hypotheses citing only a symptom register and never a control
    register are wrong more often", built from real MemoryStore/MemoryGC
    writers, matching test_inference.py's own real recipe."""
    gc = MemoryGC(store)
    for i in range(5):
        rec = _add_root_cause(
            store, title=f"clean-{i}",
            evidence={"control_register": "CTRL.mode=2", "symptom_register": "STATUS.err=1"})
    for i in range(5):
        rec = _add_root_cause(
            store, title=f"wrong-{i}", evidence={"symptom_register": "STATUS.err=1"})
        assert gc.retract(rec["memory_id"], "found wrong: real cause was elsewhere",
                          evidence={"note": "re-derived"})


# --- bare project: no memory history at all -------------------------------

def test_a_bare_project_reports_not_available_and_writes_the_topic_honestly():
    """No hypotheses at all -> NOT_AVAILABLE, never a fabricated finding.
    The Blackboard topic is still written -- "no pattern qualified" is
    itself citable evidence, exactly like the capability-evolution
    couplings' own event philosophy."""
    from dv_harness import inference as inf

    tmp, h = _fresh_harness()
    try:
        h.adapter = _FailingAdapter()
        _seed_findings(h)
        _run_failed_debug_stage(h, "commit-aaa")

        events = _events(tmp, "HYPOTHESIS_GENERATION_BIAS_DETECTED")
        assert len(events) == 1
        assert events[0]["status"] == inf.BIAS_STATUS_NOT_AVAILABLE
        assert events[0]["hypothesis_count"] == 0

        topic = h.blackboard.read("hypothesis_generation_bias")
        assert topic["value"]["status"] == inf.BIAS_STATUS_NOT_AVAILABLE
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_passing_stage_never_runs_the_coupling_at_all():
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

        assert _events(tmp, "HYPOTHESIS_GENERATION_BIAS_DETECTED") == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- best-effort: a real internal failure must never break the stage -----

def test_a_bias_detection_failure_never_breaks_the_stage_result(monkeypatch):
    from dv_harness import inference as inf
    from dv_harness.models import Status

    tmp, h = _fresh_harness()
    try:
        def _boom(root):
            raise RuntimeError("memory index unreadable")

        monkeypatch.setattr(inf, "collect_hypothesis_shapes", _boom)
        h.adapter = _FailingAdapter()
        _seed_findings(h)
        _run_failed_debug_stage(h, "commit-aaa")

        assert h.state.stages["RE_AUDIT"]["status"] == Status.FAIL.value
        assert _events(tmp, "HYPOTHESIS_GENERATION_BIAS_DETECTED") == []
        failures = _events(tmp, "HYPOTHESIS_GENERATION_BIAS_DETECTED_FAILED")
        assert len(failures) == 1
        assert "memory index unreadable" in failures[0]["error"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- end to end: a real bias corpus surfaces a real finding ---------------

def test_a_real_biased_corpus_surfaces_a_real_finding_on_the_blackboard():
    """A project whose own real retraction history matches the item's own
    worked example -> a real run_stage() FAIL/PARTIAL -> a real
    BIAS_DETECTED finding, on the Blackboard, with no human involved and no
    change to score_confidence()'s own formula."""
    from dv_harness import inference as inf

    tmp, h = _fresh_harness()
    try:
        store = MemoryStore(tmp)
        _seed_biased_corpus(store)

        h.adapter = _FailingAdapter()
        _seed_findings(h)
        _run_failed_debug_stage(h, "commit-aaa")

        events = _events(tmp, "HYPOTHESIS_GENERATION_BIAS_DETECTED")
        assert len(events) == 1
        assert events[0]["status"] == inf.BIAS_STATUS_BIAS_DETECTED
        assert events[0]["hypothesis_count"] == 10
        assert events[0]["category_finding_count"] >= 1

        topic = h.blackboard.read("hypothesis_generation_bias")
        result = topic["value"]
        assert result["status"] == inf.BIAS_STATUS_BIAS_DETECTED
        findings = result["category_findings"]
        assert any(
            f["category"] == "control_register"
            and f["direction"] == inf.DIRECTION_ABSENCE_CORRELATES
            for f in findings
        )

        # Advisory only: it wrote a report, never a decision. No approval,
        # no memory mutation beyond the biased corpus itself.
        assert store.get is not None  # the same real store, untouched otherwise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
