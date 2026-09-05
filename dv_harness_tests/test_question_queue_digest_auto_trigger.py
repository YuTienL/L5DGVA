"""The question-queue digest + 4-metrics AUTO-TRIGGER on engine.py's real
stage-transition path (2026-09-05).

`question_queue.build_digest()` and `compute_metrics()` were real, correct and
individually tested (test_question_queue.py) but DORMANT: their only caller
anywhere in the repo was the hand-typed `dv-harness question-queue digest` /
`... status` CLI verb, so an unattended `loop()` run batched nothing for a
human to answer and recorded none of the 4 tracking metrics. These tests hold
the wiring that closed that -- `DVHarness._emit_question_digest_at_stage_
boundary()`, called from `advance()` -- to the real behaviour, against a real
QuestionQueueStore on disk and the real shipped main_graph.json (never a mock
of either).
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from dv_harness.question_queue import DIGEST_BOUNDARY_STAGES, QuestionQueueStore

ROOT = Path(__file__).resolve().parents[1]
REAL_GRAPH = ROOT / ".dv-harness" / "graph" / "main_graph.json"

METRIC_KEYS = (
    "self_resolve_rate_percent",
    "blocking_questions_per_week",
    "repeat_question_rate_percent",
    "assumption_overturned_rate_percent",
)


def _fresh_harness():
    """A DVHarness rooted at a fresh temp dir carrying the REAL shipped graph
    -- same helper shape as test_graph_parallel_dispatch.py's. Caller does
    shutil.rmtree(tmp)."""
    from dv_harness.engine import DVHarness
    tmp = Path(tempfile.mkdtemp())
    (tmp / ".dv-harness" / "graph").mkdir(parents=True)
    (tmp / ".dv-harness" / "graph" / "main_graph.json").write_text(
        REAL_GRAPH.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp, DVHarness(tmp)


def _events(root: Path, event: str = "QUESTION_QUEUE_DIGEST") -> list:
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


def _ask_blocking(store: QuestionQueueStore, context_path: str = "dut.regs.TX_ERR") -> dict:
    """One real Tier-3 blocking question -- the only kind that stays OPEN and
    therefore the only kind a digest has anything to batch."""
    return store.add_question(
        domain="dut",
        question="Is dropping a short packet at this boundary legal per spec?",
        context_path=context_path,
        options=[{"label": "Treat as a legal drop", "rationale": "spec section 6.2 permits it"},
                 {"label": "Treat as an error", "rationale": "the DUT's own errata says otherwise"}],
        recommendation="Treat as a legal drop",
        assumption_if_unanswered="None -- this decides a pass/fail verdict.",
        context={"affects_pass_fail_verdict": True},
    )


# --- the hook can actually fire on the shipped pipeline ----------------------

def test_every_digest_boundary_stage_is_a_real_node_in_the_shipped_graph():
    """A hook keyed on stage names that the real graph never reaches would be
    dead wiring that still passes every behavioural test below (which set the
    stage by hand). This is the check that keeps it reachable."""
    nodes = {n["id"] for n in json.loads(REAL_GRAPH.read_text(encoding="utf-8"))["nodes"]}
    assert DIGEST_BOUNDARY_STAGES <= nodes, sorted(DIGEST_BOUNDARY_STAGES - nodes)


# --- the digest actually fires, and actually batches -------------------------

def test_advance_past_a_boundary_stage_emits_a_real_digest_and_the_4_metrics():
    tmp, h = _fresh_harness()
    try:
        store = QuestionQueueStore(tmp)
        q = _ask_blocking(store)
        assert q["status"] == "OPEN"
        assert q["digest_batch_id"] is None

        h.set_stage("REGRESSION_MONITOR")
        assert h.advance("goal") == "COVERAGE_CLOSURE"

        evs = _events(tmp)
        assert len(evs) == 1
        ev = evs[0]
        assert ev["stage"] == "REGRESSION_MONITOR"
        assert ev["trigger"] == "stage_boundary"
        assert ev["emitted"] is True
        assert ev["batch_id"].startswith("DIGEST-")
        assert ev["question_count"] == 1
        assert ev["by_owner"] == {q["owner"]: 1}

        # Not just an event: the question on disk really carries the batch id,
        # i.e. a real build_digest() ran rather than a summary being logged.
        persisted = QuestionQueueStore(tmp).get_question(q["id"])
        assert persisted["digest_batch_id"] == ev["batch_id"]
        assert persisted["digest_emitted_at"]

        for key in METRIC_KEYS:
            assert key in ev["metrics"], key
        # Real computed values over the real store, not placeholders: one
        # Tier-3 blocking ask in the 7-day window, zero Tier-1 self-resolves.
        assert ev["metrics"]["blocking_questions_per_week"] == 1.0
        assert ev["metrics"]["self_resolve_rate_percent"] == 0.0
        assert ev["metrics"]["total_questions"] == 1
        assert ev["metrics"]["self_resolve_rate_target_percent"] == 90.0
    finally:
        shutil.rmtree(tmp)


def test_an_ordinary_stage_transition_emits_nothing():
    """Part B's "batched into a daily/end-of-run digest, never real-time
    pings": every stage boundary that is NOT one of the four regression-cycle
    boundaries must leave the queue completely untouched."""
    tmp, h = _fresh_harness()
    try:
        store = QuestionQueueStore(tmp)
        q = _ask_blocking(store)

        h.set_stage("DISCOVERY")
        assert h.advance("goal") == "COMMAND_PATTERN"

        assert _events(tmp) == []
        assert QuestionQueueStore(tmp).get_question(q["id"])["digest_batch_id"] is None
    finally:
        shutil.rmtree(tmp)


def test_a_boundary_with_nothing_pending_still_records_a_metrics_datapoint():
    """A metrics series with datapoints only on the cycles that happened to
    have pending questions is not a series. emitted=False is the honest "this
    cycle had nothing to escalate" datapoint, and it is still recorded."""
    tmp, h = _fresh_harness()
    try:
        h.set_stage("COVERAGE_CLOSURE")
        assert h.advance("goal") == "RE_AUDIT"

        evs = _events(tmp)
        assert len(evs) == 1
        assert evs[0]["emitted"] is False
        assert evs[0]["batch_id"] is None
        assert evs[0]["question_count"] == 0
        assert evs[0]["by_owner"] == {}
        assert evs[0]["metrics"]["total_questions"] == 0
        for key in METRIC_KEYS:
            assert key in evs[0]["metrics"], key
    finally:
        shutil.rmtree(tmp)


def test_a_second_boundary_does_not_re_batch_an_already_digested_question():
    """build_digest() only ever batches never-yet-digested questions; crossing
    two boundaries in one run must not re-arm a batch id on a question a human
    is already sitting on."""
    tmp, h = _fresh_harness()
    try:
        store = QuestionQueueStore(tmp)
        q = _ask_blocking(store)

        h.set_stage("REGRESSION_MONITOR")
        assert h.advance("goal") == "COVERAGE_CLOSURE"
        assert h.advance("goal") == "RE_AUDIT"

        evs = _events(tmp)
        assert [e["stage"] for e in evs] == ["REGRESSION_MONITOR", "COVERAGE_CLOSURE"]
        assert evs[0]["emitted"] is True
        assert evs[1]["emitted"] is False
        assert QuestionQueueStore(tmp).get_question(q["id"])["digest_batch_id"] == evs[0]["batch_id"]
    finally:
        shutil.rmtree(tmp)


def test_a_question_queue_failure_never_breaks_the_stage_transition(monkeypatch):
    """Best-effort by design, mirroring _file_waveform_dump_scope_question():
    an unreadable queue must not turn a completed stage transition into a
    crash -- and the failure is recorded rather than swallowed silently."""
    from dv_harness import question_queue as qq

    tmp, h = _fresh_harness()
    try:
        def _boom(self, **kwargs):
            raise RuntimeError("question store unreadable")

        monkeypatch.setattr(qq.QuestionQueueStore, "build_digest", _boom)
        h.set_stage("REGRESSION_MONITOR")
        assert h.advance("goal") == "COVERAGE_CLOSURE"

        assert _events(tmp) == []
        failed = _events(tmp, "QUESTION_QUEUE_DIGEST_FAILED")
        assert len(failed) == 1
        assert "question store unreadable" in failed[0]["error"]
        assert failed[0]["stage"] == "REGRESSION_MONITOR"
    finally:
        shutil.rmtree(tmp)


# --- the AUTONOMOUS path, not just a hand-called advance() -------------------

def test_digest_fires_after_a_real_gate_verified_stage_pass():
    """advance() is what loop() delegates to on every PASS. This drives the
    real sequence -- run_stage() to a real PASS, then the same advance() the
    loop calls -- so the wiring is proven on the path an unattended run takes,
    not only on a hand-set stage."""
    from dv_harness.adapters.base import AgentResult
    from dv_harness.models import Status

    tmp, h = _fresh_harness()
    try:
        h.cfg["policy"]["require_stage_gate_evidence"] = False

        class _OkAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text="regression cycle complete", raw={}, session_id=None)

        h.adapter = _OkAdapter()
        store = QuestionQueueStore(tmp)
        q = _ask_blocking(store)

        h.set_stage("REGRESSION_MONITOR")
        h.run_stage("goal")
        assert h.state.stages["REGRESSION_MONITOR"]["status"] == Status.PASS.value

        assert h.advance("goal") == "COVERAGE_CLOSURE"

        evs = _events(tmp)
        assert len(evs) == 1
        assert evs[0]["emitted"] is True
        assert evs[0]["question_count"] == 1
        assert QuestionQueueStore(tmp).get_question(q["id"])["digest_batch_id"] == evs[0]["batch_id"]
    finally:
        shutil.rmtree(tmp)
