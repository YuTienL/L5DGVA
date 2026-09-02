import json
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path

from dv_harness.graph import GraphDefinition
from dv_harness.models import Status
from dv_harness.policy import graph_next

ROOT = Path(__file__).resolve().parents[1]
REAL_GRAPH = ROOT / ".dv-harness" / "graph" / "main_graph.json"

ANALYSIS_G1 = {"REQUIREMENTS_TRACEABILITY", "SOC_SCENARIO_PLANNER", "INFRASTRUCTURE_AUDIT"}


def _fresh_harness(with_graph=True):
    """Mirrors test_engine_gates_and_routing.py's own _fresh_harness helper --
    a DVHarness rooted at a fresh temp dir, optionally with the real
    project's main_graph.json copied in. Caller is responsible for
    shutil.rmtree(tmp)."""
    from dv_harness.engine import DVHarness
    tmp = Path(tempfile.mkdtemp())
    if with_graph:
        (tmp / ".dv-harness" / "graph").mkdir(parents=True)
        (tmp / ".dv-harness" / "graph" / "main_graph.json").write_text(
            REAL_GRAPH.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp, DVHarness(tmp)


def _write_synthetic_fanout_graph(tmp: Path):
    """A small, standalone, test-only graph -- deliberately separate from
    the real main_graph.json, per the actual fan-out node ids/roles it
    reuses real Stage enum members (so HarnessState.ensure_stages() already
    has a StageState for each) but its edges/parallel_group/join_group are
    entirely test-local, not the real pipeline's semantics."""
    nodes = [
        {"id": "ENV_CHECK", "route": "analysis-route", "agent": "analysis-agent"},
        {"id": "INTAKE", "route": "analysis-route", "agent": "analysis-agent",
         "parallel_group": "TESTG1", "blackboard_write": ["bw_a"]},
        {"id": "DISCOVERY", "route": "analysis-route", "agent": "analysis-agent",
         "parallel_group": "TESTG1", "blackboard_write": ["bw_b"]},
        {"id": "COMMAND_PATTERN", "route": "analysis-route", "agent": "analysis-agent",
         "parallel_group": "TESTG1", "blackboard_write": ["bw_c"]},
        {"id": "DE_BASELINE_REPRODUCTION", "route": "lead-route", "agent": "dv-lead",
         "join_group": "TESTG1"},
        {"id": "ARCH_DISCOVERY", "route": "analysis-route", "agent": "analysis-agent"},
    ]
    edges = [
        {"source": "ENV_CHECK", "target": "INTAKE", "condition": "PASS"},
        {"source": "ENV_CHECK", "target": "DISCOVERY", "condition": "PASS"},
        {"source": "ENV_CHECK", "target": "COMMAND_PATTERN", "condition": "PASS"},
        {"source": "INTAKE", "target": "DE_BASELINE_REPRODUCTION", "condition": "PASS"},
        {"source": "DISCOVERY", "target": "DE_BASELINE_REPRODUCTION", "condition": "PASS"},
        {"source": "COMMAND_PATTERN", "target": "DE_BASELINE_REPRODUCTION", "condition": "PASS"},
        {"source": "DE_BASELINE_REPRODUCTION", "target": "ARCH_DISCOVERY", "condition": "PASS"},
    ]
    (tmp / ".dv-harness" / "graph").mkdir(parents=True)
    (tmp / ".dv-harness" / "graph" / "main_graph.json").write_text(
        json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False, indent=2),
        encoding="utf-8")


_STAGE_RE = re.compile(r"Current Stage: (\S+)")


def _stage_from_prompt(prompt: str) -> str:
    m = _STAGE_RE.search(prompt)
    assert m, f"prompt did not embed 'Current Stage: <id>': {prompt[:200]!r}"
    return m.group(1)


# --- next_frontier() unit-level tests --------------------------------------

def test_next_frontier_matches_next_for_for_ordinary_nodes():
    gd = GraphDefinition.load(REAL_GRAPH)
    ordinary = ["ENV_CHECK", "INTAKE", "DISCOVERY", "COMMAND_PATTERN",
                "DE_BASELINE_REPRODUCTION", "VPLAN", "BUILD", "VERIFY",
                "REGRESSION_MONITOR", "RE_AUDIT", "SIGNOFF"]
    for node in ordinary:
        for condition in ("PASS", "FAIL", "BLOCKED"):
            frontier = gd.next_frontier(node, condition)
            single = gd.next_for(node, condition)
            if single is None:
                assert frontier == [], (node, condition)
            else:
                assert frontier == [single], (node, condition, frontier, single)


def test_next_frontier_returns_all_three_analysis_g1_targets_for_protocol_capability():
    gd = GraphDefinition.load(REAL_GRAPH)
    frontier = gd.next_frontier("PROTOCOL_CAPABILITY", "PASS")
    assert set(frontier) == ANALYSIS_G1
    assert len(frontier) == 3
    # next_for() is unchanged: still returns exactly one of those three
    # (first match by edge priority), never touched by this feature.
    single = gd.next_for("PROTOCOL_CAPABILITY", "PASS")
    assert single in ANALYSIS_G1


def test_next_frontier_regression_matches_next_for_across_all_real_nodes():
    # Backward-compatibility proof: for every one of the 37 real nodes except
    # PROTOCOL_CAPABILITY (the only real fan-out source today), next_frontier()
    # on a PASS transition returns a single-element list carrying exactly the
    # same target next_for() already returned -- a strict superset, never a
    # behavior change, for every other stage in the pipeline.
    gd = GraphDefinition.load(REAL_GRAPH)
    assert len(gd.nodes) == 37
    changed = {"PROTOCOL_CAPABILITY"}
    for node_id in gd.nodes:
        frontier = gd.next_frontier(node_id, "PASS")
        single = gd.next_for(node_id, "PASS")
        if node_id in changed:
            continue
        if single is None:
            assert frontier == [], node_id
        else:
            assert frontier == [single], (node_id, frontier, single)


# --- advance() backward-compatibility (ordinary, non-parallel stages) ------

def test_advance_is_unaffected_for_ordinary_stages():
    from dv_harness.adapters.base import AgentResult
    tmp, h = _fresh_harness()
    try:
        h.cfg["policy"]["require_stage_gate_evidence"] = False
        calls = []

        class _CountingAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                calls.append(_stage_from_prompt(prompt))
                return AgentResult(ok=True, text="fine", raw={}, session_id=None)

        h.adapter = _CountingAdapter()
        h.set_stage("DISCOVERY")
        h.run_stage("goal")
        assert h.state.stages["DISCOVERY"]["status"] == Status.PASS.value

        expected = graph_next("DISCOVERY", "PASS", tmp)
        n = h.advance("goal")
        assert n == expected == "COMMAND_PATTERN"
        assert h.state.current_stage == "COMMAND_PATTERN"
        # advance() on an ordinary (non-fan-out) stage must not itself invoke
        # the adapter at all -- it only recomputes current_stage, exactly as
        # graph_next()-based advance() already did before this feature.
        assert calls == ["DISCOVERY"]
        # active_stages is purely additive and stays empty outside a fan-out.
        assert h.state.active_stages == []
        assert h.state.effective_active_stages() == ["COMMAND_PATTERN"]
    finally:
        shutil.rmtree(tmp)


# --- engine-level fan-out/join dispatch (standalone synthetic graph) -------

def test_engine_dispatches_all_three_branches_concurrently_and_joins():
    from dv_harness.adapters.base import AgentResult
    from dv_harness.engine import DVHarness
    tmp = Path(tempfile.mkdtemp())
    try:
        _write_synthetic_fanout_graph(tmp)
        h = DVHarness(tmp)
        h.cfg["policy"]["require_stage_gate_evidence"] = False

        lock = threading.Lock()
        state = {"current": 0, "peak": 0, "seen": [], "windows": {}}
        # SLEEP=0.25 (with a 1.8x margin, i.e. a 0.45s threshold below) was
        # observed to fail under real `pytest -n8` contention: a captured
        # failure showed COMMAND_PATTERN's window (enter=..7657, exit=..0163)
        # entirely disjoint from DISCOVERY/INTAKE's window (enter=..2570),
        # a ~0.24s gap -- not a dispatch bug (the fan-out code correctly uses
        # ThreadPoolExecutor(max_workers=len(targets)), submitting all branches
        # in one tight loop), but real OS thread-scheduling latency: under
        # heavy multi-process CPU contention (8 competing pytest-xdist worker
        # processes, several themselves spawning gate-script subprocesses),
        # the OS can delay actually scheduling 2 of the 3 freshly-created
        # worker threads onto a core for a while even though Python submitted
        # all 3 essentially simultaneously. That absolute OS-jitter magnitude
        # doesn't shrink just because SLEEP is larger, so a longer SLEEP
        # dilutes it to a much smaller fraction of the window instead --
        # same calibration principle as the d289589 dashboard-test fix.
        SLEEP = 1.0

        class _SlowAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                stage = _stage_from_prompt(prompt)
                with lock:
                    state["current"] += 1
                    state["peak"] = max(state["peak"], state["current"])
                    state["seen"].append(stage)
                    # active_stages must already reflect the full branch set
                    # while branches are genuinely concurrently in flight.
                    state.setdefault("active_stages_seen", []).append(list(h.state.active_stages))
                enter = time.perf_counter()
                time.sleep(SLEEP)
                exit_ = time.perf_counter()
                with lock:
                    state["current"] -= 1
                    state["windows"][stage] = (enter, exit_)
                return AgentResult(ok=True, text=f"evidence for {stage}", raw={}, session_id=None)

        h.adapter = _SlowAdapter()
        h.set_stage("ENV_CHECK")
        h.run_stage("goal")
        assert h.state.stages["ENV_CHECK"]["status"] == Status.PASS.value
        state["seen"].clear()
        state["peak"] = 0
        state["windows"].clear()
        state["active_stages_seen"] = []

        n = h.advance("goal")

        # Concurrency evidence, independent of any pre-dispatch overhead
        # (thread-pool/subprocess startup, etc.): at least two branches were
        # inside the fake adapter's sleep at the same time (peak), and the
        # real span from the first branch entering to the last branch
        # exiting is close to a SINGLE branch's SLEEP, not the sum of all
        # three -- true serial execution would make this span >= 3*SLEEP.
        assert state["peak"] >= 2, state
        assert set(state["seen"]) == {"INTAKE", "DISCOVERY", "COMMAND_PATTERN"}
        first_enter = min(w[0] for w in state["windows"].values())
        last_exit = max(w[1] for w in state["windows"].values())
        span = last_exit - first_enter
        assert span < SLEEP * 1.8, (span, state["windows"])

        # The join is only reached once all 3 branches PASS.
        assert n == "ARCH_DISCOVERY"
        assert h.state.current_stage == "ARCH_DISCOVERY"
        for b in ("INTAKE", "DISCOVERY", "COMMAND_PATTERN"):
            assert h.state.stages[b]["status"] == Status.PASS.value

        frontier = json.loads((tmp / ".dv-harness" / "graph" / "parallel_frontier.json")
                               .read_text(encoding="utf-8"))
        entry = frontier["TESTG1"]
        assert entry["source_node"] == "ENV_CHECK"
        assert entry["branches"] == {"INTAKE": "PASS", "DISCOVERY": "PASS", "COMMAND_PATTERN": "PASS"}

        # HarnessState.active_stages: populated with all 3 branches for the
        # entire duration of the fan-out (every adapter call observed the
        # full set, not a partial/growing one), then cleared back to []
        # now that current_stage has advanced past the join.
        for seen in state["active_stages_seen"]:
            assert set(seen) == {"INTAKE", "DISCOVERY", "COMMAND_PATTERN"}
        assert h.state.active_stages == []
        assert h.state.effective_active_stages() == ["ARCH_DISCOVERY"]
    finally:
        shutil.rmtree(tmp)


def test_engine_fanout_join_does_not_proceed_when_one_branch_fails():
    from dv_harness.adapters.base import AgentResult
    from dv_harness.engine import DVHarness
    tmp = Path(tempfile.mkdtemp())
    try:
        _write_synthetic_fanout_graph(tmp)
        h = DVHarness(tmp)
        h.cfg["policy"]["require_stage_gate_evidence"] = False
        h.cfg["policy"]["max_stage_retries"] = 0

        class _OneFailsAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                stage = _stage_from_prompt(prompt)
                if stage == "DISCOVERY":
                    return AgentResult(ok=False, text="boom", raw={"stderr": "boom"}, session_id=None)
                return AgentResult(ok=True, text=f"evidence for {stage}", raw={}, session_id=None)

        h.adapter = _OneFailsAdapter()
        h.set_stage("ENV_CHECK")
        h.run_stage("goal")
        assert h.state.stages["ENV_CHECK"]["status"] == Status.PASS.value

        n = h.advance("goal")

        # The join node (DE_BASELINE_REPRODUCTION -> ARCH_DISCOVERY) must NOT
        # be reached -- DISCOVERY has no FAIL edge in the synthetic graph
        # (mirroring the real ANALYSIS_G1 branches, none of which have one
        # either), so the engine stays parked on the failed branch, exactly
        # like the existing single-stage retry-exhaustion path does.
        assert n == "DISCOVERY"
        assert h.state.current_stage == "DISCOVERY"
        assert h.state.stages["DISCOVERY"]["status"] == Status.FAIL.value
        # The other two branches' real results are still recorded, not
        # discarded, even though the fan-out overall did not pass.
        assert h.state.stages["INTAKE"]["status"] == Status.PASS.value
        assert h.state.stages["COMMAND_PATTERN"]["status"] == Status.PASS.value
        # active_stages is deliberately NOT cleared when the join isn't
        # reached -- a human looking at a parked, blocked fan-out can still
        # see which branches were concurrently active when it stopped,
        # mirroring parallel_frontier.json's own persistent record.
        assert set(h.state.active_stages) == {"INTAKE", "DISCOVERY", "COMMAND_PATTERN"}
    finally:
        shutil.rmtree(tmp)
