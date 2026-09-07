"""RCA_G1 multi-agent evidence fan-out + independent synthesis (2026-09-03).

What this file exists to prove, and why the proof is shaped this way.

The gap this closes was NEVER "does the fan-out primitive work in isolation"
-- `_advance_with_fanout()` was already real and already tested
(test_graph_parallel_dispatch.py), and `.claude/workflows/
rca-multi-agent-fusion.js` was already a real Workflow script with real agent
profiles. The gap was that neither was ever reachable from the harness's own
RCA stage flow: the only `parallel_group` in `.dv-harness/graph/
main_graph.json` was ANALYSIS_G1 (a requirements/scenario/infra planning
fan-out, not the DUT/PHY/Register/VIP evidence mechanism CLAUDE.md's rule
names), and the Workflow script had zero callers from `dv_harness/engine.py`
-- it only ran when a human/session remembered to invoke it by name.

So every test below drives the REAL engine over the REAL main_graph.json,
through the REAL gate scripts, and asserts on REAL artifacts
(.dv-harness/agents/tasks.json, .dv-harness/blackboard/*.json,
.dv-harness/events.jsonl) -- not on mocks of the mechanism under test. The
one and only stub is the LLM adapter itself, which is unavoidable here (no
Claude subprocess in a unit-test environment) and is exactly the same stub
the already-proven ANALYSIS_G1 fan-out test uses. The agent TEXT is stubbed;
the graph traversal, the concurrency, the gate subprocesses, the task-store
bookkeeping and the Blackboard writes are all genuinely executed.
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path

from dv_harness.gates import STAGE_GATES
from dv_harness.graph import GraphDefinition
from dv_harness.models import Stage, Status
from dv_harness.policy import ORDER

ROOT = Path(__file__).resolve().parents[1]
REAL_GRAPH = ROOT / ".dv-harness" / "graph" / "main_graph.json"

RCA_BRANCHES = {"RCA_RTL_EVIDENCE", "RCA_LOG_EVIDENCE", "RCA_VIP_SPEC_EVIDENCE"}
RCA_BRANCH_TOPICS = {
    "RCA_RTL_EVIDENCE": "rca_rtl_evidence",
    "RCA_LOG_EVIDENCE": "rca_log_evidence",
    "RCA_VIP_SPEC_EVIDENCE": "rca_vip_spec_evidence",
}

_STAGE_RE = re.compile(r"Current Stage: (\S+)")


def _stage_from_prompt(prompt: str) -> str:
    m = _STAGE_RE.search(prompt)
    assert m, f"prompt did not embed 'Current Stage: <id>': {prompt[:200]!r}"
    return m.group(1)


def _real_project_harness():
    """A DVHarness on a fresh temp root carrying the REAL graph, the REAL
    gate scripts and the REAL inference policy -- so FAILURE_RECOVERY's and
    RCA_JOIN's gates are genuinely executed as subprocesses against the
    evidence the stub adapter emits, exactly as they would be in production.
    Caller is responsible for shutil.rmtree(tmp)."""
    from dv_harness.engine import DVHarness
    tmp = Path(tempfile.mkdtemp())
    (tmp / ".dv-harness" / "graph").mkdir(parents=True)
    (tmp / ".dv-harness" / "graph" / "main_graph.json").write_text(
        REAL_GRAPH.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp / ".dv-harness" / "inference").mkdir(parents=True)
    (tmp / ".dv-harness" / "inference" / "inference_policy.json").write_text(
        (ROOT / ".dv-harness" / "inference" / "inference_policy.json").read_text(encoding="utf-8"),
        encoding="utf-8")
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(ROOT / "tools" / "verification_flow",
                    tmp / "tools" / "verification_flow", ignore=ignore)
    shutil.copytree(ROOT / "tools" / "senior_dv",
                    tmp / "tools" / "senior_dv", ignore=ignore)
    return tmp, DVHarness(tmp)


def _evidence(gate_id: str, payload: dict) -> str:
    return "```dv-harness-evidence:" + gate_id + "\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


def _failure_recovery_text(classification: str) -> str:
    """FAILURE_RECOVERY evidence that really passes all five of its real
    STAGE_GATES scripts. `classification` is the one field under test -- it
    is what decides whether the RCA_G1 fan-out is armed."""
    return "\n\n".join([
        f"FAILURE_RECOVERY triage: {classification}.",
        _evidence("failure_attribution", {"boundary_trace": [
            {"stage": "INTERFACE_OUT", "expected": "ACK", "observed": "NAK"},
        ]}),
        _evidence("failure_signature_recurrence_gate", {"failures": [
            {"failure_id": "F-001", "signature": "sig-usb-lpm-nak"},
        ]}),
        _evidence("issue_triage_classification_gate", {
            "classification": classification,
            "classification_reason": "device NAKs the LPM transition the host requested",
            "evidence_hash": "sha256:0f3c9b21",
            "deep_rca_triggered": classification == "REAL_ISSUE",
            **({"known_issue_id": "KI-42"} if classification == "KNOWN" else {}),
        }),
        _evidence("unknown_failure_escalation_gate", {"classification": classification}),
        _evidence("focused_wave_debug_window_gate", {
            "deep_debug_required": False,
            "deep_debug_not_required_reason": "sim.log + RTL register state already localize the NAK",
        }),
    ])


def _rca_join_text() -> str:
    """RCA_JOIN's independent-synthesis evidence, in the real shape
    root_cause_evidence_gate.py structurally requires (>=2 hypotheses, the
    selected root_cause traceable to one of them, at least one OTHER carrying
    real counter_evidence)."""
    selected = "LPM L1 entry NAKed because the device-side remote-wake enable bit was never programmed"
    alternative = "Host issued the LPM token before the device finished its own reset sequence"
    return "\n\n".join([
        "RCA_JOIN synthesis over the three RCA_G1 branch topics.",
        _evidence("root_cause_evidence_gate", {
            "symptom": "UVM_ERROR: expected ACK for LPM token, observed NAK",
            "first_bad_event": "sim.log:4021 device NAK at 1832us on the first LPM token",
            "causal_chain": [
                "rca_rtl_evidence: remote-wake enable register resets to 0",
                "rca_log_evidence: no APB write to that register before 1832us",
                "rca_vip_spec_evidence: spec requires the enable set before an L1 request",
            ],
            "root_cause": selected,
            "supporting_evidence": [
                "rtl:usb_dev_pwr_ctrl.v:214 remote_wake_en default 1'b0",
                "sim.log:4021 NAK, no preceding APB write to 0x40",
                "vip_example lpm_l1_entry_seq.sv:88 programs the enable first",
            ],
            "counter_evidence": [
                "reset sequence completed at 900us, well before the LPM token",
            ],
            "confidence": "MEDIUM",
            "hypotheses": [
                {"claim": selected, "category": "TB_BUG",
                 "supporting_evidence": ["rtl:usb_dev_pwr_ctrl.v:214", "sim.log:4021"],
                 "counter_evidence": [], "missing_evidence": [],
                 "confidence": "MEDIUM", "next_action": "add the enable write to the pattern"},
                {"claim": alternative, "category": "TEST_ISSUE",
                 "supporting_evidence": ["command.txt:12 issues the token early"],
                 "counter_evidence": ["sim.log:2100 reset done at 900us, 930us before the token"],
                 "missing_evidence": [], "confidence": "LOW",
                 "next_action": "none -- refuted by the reset-completion timestamp"},
            ],
        }),
    ])


class _ScriptedAdapter:
    """Returns per-stage evidence text and records real concurrency windows.
    `sleep` is only applied to the RCA_G1 branches -- the point being
    measured is whether those three genuinely overlap in time."""

    def __init__(self, texts, sleep=0.0, harness=None):
        self.texts = texts
        self.sleep = sleep
        self.harness = harness
        self.lock = threading.Lock()
        self.seen = []
        self.peak = 0
        self._current = 0
        self.windows = {}
        self.active_stages_seen = []

    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
        from dv_harness.adapters.base import AgentResult
        stage = _stage_from_prompt(prompt)
        with self.lock:
            self.seen.append(stage)
            self._current += 1
            self.peak = max(self.peak, self._current)
            if self.harness is not None:
                self.active_stages_seen.append(list(self.harness.state.active_stages))
        enter = time.perf_counter()
        if self.sleep and stage in RCA_BRANCHES:
            time.sleep(self.sleep)
        with self.lock:
            self._current -= 1
            self.windows[stage] = (enter, time.perf_counter())
        return AgentResult(ok=True, text=self.texts.get(stage, f"evidence for {stage}"),
                            raw={}, session_id=None)


def _texts(classification="REAL_ISSUE"):
    t = {"FAILURE_RECOVERY": _failure_recovery_text(classification),
         "RCA_JOIN": _rca_join_text()}
    for b in RCA_BRANCHES:
        t[b] = f"{b} branch evidence: single-domain findings with real citations."
    return t


def _events(tmp: Path):
    p = tmp / ".dv-harness" / "events.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _tasks(tmp: Path):
    return json.loads((tmp / ".dv-harness" / "agents" / "tasks.json").read_text(encoding="utf-8"))


# --- graph/registration-level checks ---------------------------------------

def test_rca_g1_is_a_real_fanout_in_the_real_graph_bound_to_the_real_agent_profiles():
    """The three branches must dispatch the SAME already-existing specialist
    agent profiles `.claude/workflows/rca-multi-agent-fusion.js` fans out to
    -- the point of this closure is wiring the real mechanism into the real
    path, not building a second one beside it."""
    gd = GraphDefinition.load(REAL_GRAPH)
    branches = {n.id: n for n in gd.nodes.values() if n.parallel_group == "RCA_G1"}
    assert set(branches) == RCA_BRANCHES
    assert {n.agent for n in branches.values()} == {
        "rtl-evidence-agent", "log-evidence-agent", "vip-spec-evidence-agent"}
    for stage_id, topic in RCA_BRANCH_TOPICS.items():
        assert branches[stage_id].blackboard_write == [topic]
        assert (ROOT / ".claude" / "agents" / f"{branches[stage_id].agent}.md").exists()

    joins = [n for n in gd.nodes.values() if n.join_group == "RCA_G1"]
    assert len(joins) == 1 and joins[0].id == "RCA_JOIN"
    assert joins[0].agent == "analysis_debug"
    assert (ROOT / ".claude" / "agents" / "analysis_debug.md").exists()
    assert joins[0].blackboard_write == ["rca_evidence_fusion"], (
        "RCA_JOIN must persist to the same Blackboard topic rca-multi-agent-fusion.js "
        "writes, so both real paths converge on one record")

    # The whole fan-out really is reachable from FAILURE_RECOVERY's PASS edge.
    assert set(gd.next_frontier("FAILURE_RECOVERY", "PASS")) == RCA_BRANCHES | {"CHANGE_IMPACT"}


def test_rca_join_is_an_executable_stage_with_the_reused_root_cause_gate():
    """A join node that is a real Stage must EXECUTE, not be passed through
    like the synthetic ANALYSIS_JOIN -- otherwise the 'independent synthesis'
    half of CLAUDE.md's rule silently disappears."""
    assert Stage.RCA_JOIN.value in ORDER
    assert [g[0] for g in STAGE_GATES["RCA_JOIN"]] == ["root_cause_evidence_gate"], (
        "RCA_JOIN must reuse RE_AUDIT's existing root_cause_evidence_gate, not a new gate")
    assert "RCA_RTL_EVIDENCE" not in STAGE_GATES, (
        "an evidence-gathering branch must not be gated on producing a root cause")


# --- the real end-to-end run ------------------------------------------------

def test_real_issue_triage_dispatches_the_rca_fanout_end_to_end():
    tmp, h = _real_project_harness()
    try:
        adapter = _ScriptedAdapter(_texts("REAL_ISSUE"), sleep=1.0, harness=h)
        h.adapter = adapter

        # --- 1. FAILURE_RECOVERY runs for real, through its five real gates.
        h.set_stage("FAILURE_RECOVERY")
        h.run_stage("goal")
        assert h.state.stages["FAILURE_RECOVERY"]["status"] == Status.PASS.value, \
            h.state.stages["FAILURE_RECOVERY"].get("blocking_reason")
        armed = h.state.rca_evidence_fanout_armed
        assert armed and armed.startswith("REAL_ISSUE:"), armed
        assert "sha256:0f3c9b21" in armed, (
            "the arming token must record WHICH real triage evidence authorized the fan-out")

        adapter.seen.clear()
        adapter.windows.clear()
        adapter.peak = 0

        # --- 2. advance() takes the fan-out, concurrently.
        n = h.advance("goal")

        assert set(adapter.seen) == RCA_BRANCHES
        assert adapter.peak >= 2, adapter.seen
        span = (max(w[1] for w in adapter.windows.values())
                - min(w[0] for w in adapter.windows.values()))
        assert span < 1.0 * 1.8, (span, adapter.windows)
        for seen in adapter.active_stages_seen[-3:]:
            assert set(seen) == RCA_BRANCHES

        # --- 3. The join is a real stage the engine LANDED on, not skipped.
        assert n == "RCA_JOIN"
        assert h.state.current_stage == "RCA_JOIN"
        assert h.state.stages["RCA_JOIN"]["status"] == Status.NOT_STARTED.value, \
            "RCA_JOIN must be pending execution, not silently passed through"
        for b in RCA_BRANCHES:
            assert h.state.stages[b]["status"] == Status.PASS.value
            assert h.blackboard.read(RCA_BRANCH_TOPICS[b]) is not None

        # --- 4. Arming is single-use.
        assert h.state.rca_evidence_fanout_armed is None

        # --- 5. AgentTaskStore bookkeeping is real for every branch
        #        (the audit's own verification criterion).
        tasks = [t for t in _tasks(tmp) if t.get("parallel_group") == "RCA_G1"]
        assert len(tasks) == 3, tasks
        assert {t["agent"] for t in tasks} == {
            "rtl-evidence-agent", "log-evidence-agent", "vip-spec-evidence-agent"}
        for t in tasks:
            assert t["status"] == "COMPLETED", t
            assert isinstance(t["started_at"], float) and isinstance(t["completed_at"], float)
            assert t["completed_at"] >= t["started_at"]
            assert t["duration_sec"] >= 0.0

        # --- 6. RCA_JOIN executes for real and its root_cause_evidence_gate
        #        subprocess accepts the synthesis.
        adapter.seen.clear()
        h.run_stage("goal")
        assert h.state.stages["RCA_JOIN"]["status"] == Status.PASS.value, \
            h.state.stages["RCA_JOIN"].get("blocking_reason")
        assert adapter.seen == ["RCA_JOIN"]

        fusion = h.blackboard.read("rca_evidence_fusion")
        assert fusion is not None, "RCA_JOIN must persist the fused record"
        value = fusion["value"]
        assert value["produced_by"] == "engine:RCA_G1_graph_fanout"
        assert value["root_cause"].startswith("LPM L1 entry NAKed")
        contributing = {c["agent"] for c in value["contributing_agents"]}
        assert contributing == {"rtl-evidence-agent", "log-evidence-agent", "vip-spec-evidence-agent"}

        # --- 7. multi_agent_consensus_count now derives from REAL concurrent
        #        agents, not only the single-agent hypothesis proxy.
        rcc = h.blackboard.read("root_cause_confidence")["value"]
        assert rcc["stage"] == "RCA_JOIN"
        assert rcc["concurrent_agent_evidence_count"] == 3

        # --- 8. The fan-out resolves back onto the original pipeline.
        assert h.advance("goal") == "CHANGE_IMPACT"

        # --- 9. Real, auditable event trail.
        events = _events(tmp)
        kinds = [e.get("event") for e in events]
        assert "RCA_EVIDENCE_FANOUT_ARMED" in kinds
        assert "RCA_EVIDENCE_FANOUT_DISPATCHED" in kinds
        assert {e.get("stage") for e in events} >= RCA_BRANCHES | {"RCA_JOIN"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_non_real_issue_triage_keeps_the_original_single_path():
    """CLAUDE.md scopes multi-agent evidence acquisition to important
    DUT/PHY/Register/VIP changes -- a KNOWN-issue triage must cost zero extra
    agents and route exactly as it did before this feature existed."""
    tmp, h = _real_project_harness()
    try:
        adapter = _ScriptedAdapter(_texts("KNOWN"), harness=h)
        h.adapter = adapter
        h.set_stage("FAILURE_RECOVERY")
        h.run_stage("goal")
        assert h.state.stages["FAILURE_RECOVERY"]["status"] == Status.PASS.value, \
            h.state.stages["FAILURE_RECOVERY"].get("blocking_reason")
        assert h.state.rca_evidence_fanout_armed is None

        adapter.seen.clear()
        n = h.advance("goal")

        assert n == "CHANGE_IMPACT"
        assert h.state.current_stage == "CHANGE_IMPACT"
        assert adapter.seen == [], "no branch agent may run without a REAL_ISSUE triage"
        for b in RCA_BRANCHES:
            assert h.state.stages[b]["status"] == Status.NOT_STARTED.value
        assert [t for t in _tasks(tmp) if t.get("parallel_group") == "RCA_G1"] == []
        assert h.state.active_stages == []
        assert "RCA_EVIDENCE_FANOUT_NOT_ARMED" in [e.get("event") for e in _events(tmp)]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_stale_arming_is_cleared_by_a_later_non_real_issue_triage():
    """One triage decision authorizes exactly one fan-out, and a later
    non-REAL_ISSUE triage actively revokes an older authorization rather than
    letting it stay live (CLAUDE.md: any current root cause must be
    revalidated with current evidence)."""
    tmp, h = _real_project_harness()
    try:
        h.adapter = _ScriptedAdapter(_texts("REAL_ISSUE"), harness=h)
        h.set_stage("FAILURE_RECOVERY")
        h.run_stage("goal")
        assert h.state.rca_evidence_fanout_armed

        h.adapter = _ScriptedAdapter(_texts("MISCLASSIFIED"), harness=h)
        h.set_stage("FAILURE_RECOVERY")
        h.run_stage("goal")
        assert h.state.stages["FAILURE_RECOVERY"]["status"] == Status.PASS.value
        assert h.state.rca_evidence_fanout_armed is None
        assert h.advance("goal") == "CHANGE_IMPACT"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- backward compatibility of the conditional resolver --------------------

def test_conditional_resolver_leaves_the_unconditional_analysis_g1_fanout_alone():
    tmp, h = _real_project_harness()
    try:
        frontier = h.graph.next_frontier("PROTOCOL_CAPABILITY", "PASS")
        assert h._resolve_conditional_fanout_frontier("PROTOCOL_CAPABILITY", frontier) == frontier
        # ...and it stays untouched whether or not the RCA fan-out is armed.
        h.state.rca_evidence_fanout_armed = "REAL_ISSUE:sha256:deadbeef"
        assert h._resolve_conditional_fanout_frontier("PROTOCOL_CAPABILITY", frontier) == frontier
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_conditional_resolver_is_a_noop_for_every_ordinary_single_edge_stage():
    tmp, h = _real_project_harness()
    try:
        for node_id in h.graph.nodes:
            for condition in ("PASS", "FAIL", "BLOCKED"):
                frontier = h.graph.next_frontier(node_id, condition)
                if node_id == "FAILURE_RECOVERY" and condition == "PASS":
                    continue
                assert h._resolve_conditional_fanout_frontier(node_id, frontier) == frontier, node_id
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- genuine cross-branch CONTRADICTION detection (2026-09-07,
# fanout_contradiction_detection) ------------------------------------------
#
# additive to the whole fan-out mechanism above: contributing_agents,
# multi_agent_consensus_count and the root_cause_evidence_gate PASS itself
# are untouched by every test below -- these tests only assert on the new
# branch_contradiction_flag field.

def _branch_root_cause_text(claim: str | None) -> str:
    """A branch's own real evidence text. RCA_RTL_EVIDENCE/RCA_LOG_EVIDENCE/
    RCA_VIP_SPEC_EVIDENCE are deliberately NOT gated on root_cause_evidence_
    gate (STAGE_GATES has no entry for them), so this fenced block is never
    required to PASS the branch stage -- it is only real text a branch agent
    MAY choose to emit, exactly what _detect_rca_branch_contradictions()
    reads. `claim is None` reproduces a branch that found nothing citable
    (no fenced block at all) -- the uncorroborated, non-contradictory case."""
    if claim is None:
        return "branch findings: nothing conclusive to cite yet."
    return "branch findings.\n\n" + _evidence("root_cause_evidence_gate", {"root_cause": claim})


def _run_rca_fanout_to_join(claims: dict) -> tuple[Path, "DVHarness"]:
    """Drives FAILURE_RECOVERY -> the real RCA_G1 fan-out -> RCA_JOIN exactly
    like test_real_issue_triage_dispatches_the_rca_fanout_end_to_end above,
    except each branch's own stubbed text is built from `claims`
    ({stage_id: claim_or_None}) instead of the generic placeholder text, so
    each branch's real Blackboard topic really carries (or really omits) a
    root_cause_evidence_gate-shaped block for RCA_JOIN's synthesis point to
    read back. Caller is responsible for shutil.rmtree(tmp)."""
    tmp, h = _real_project_harness()
    texts = _texts("REAL_ISSUE")
    for stage_id, claim in claims.items():
        texts[stage_id] = _branch_root_cause_text(claim)
    h.adapter = _ScriptedAdapter(texts, harness=h)
    h.set_stage("FAILURE_RECOVERY")
    h.run_stage("goal")
    assert h.state.stages["FAILURE_RECOVERY"]["status"] == Status.PASS.value
    assert h.advance("goal") == "RCA_JOIN"
    for b in RCA_BRANCHES:
        assert h.state.stages[b]["status"] == Status.PASS.value
    h.run_stage("goal")
    assert h.state.stages["RCA_JOIN"]["status"] == Status.PASS.value, \
        h.state.stages["RCA_JOIN"].get("blocking_reason")
    return tmp, h


def test_rca_join_flags_a_real_cross_branch_contradiction():
    """Two of the three real, independently-dispatched RCA_G1 branches each
    cite a REAL but DIFFERENT root_cause for the same finding -- exactly the
    genuine disagreement the fan-out's own blind-dispatch design can produce,
    and CLAUDE.md's Evidence Truth Rule requires be surfaced rather than
    silently folded into (or out of) the consensus count."""
    tmp, h = _run_rca_fanout_to_join({
        "RCA_RTL_EVIDENCE": "remote-wake enable register never programmed before the LPM token",
        "RCA_LOG_EVIDENCE": "host issued the LPM token before device reset completed",
        "RCA_VIP_SPEC_EVIDENCE": None,
    })
    try:
        fusion = h.blackboard.read("rca_evidence_fusion")["value"]
        flag = fusion["branch_contradiction_flag"]
        assert flag["contradiction_detected"] is True
        agents = {c["agent"] for c in flag["conflicting_claims"]}
        assert agents == {"rtl-evidence-agent", "log-evidence-agent"}
        claims = {c["root_cause"] for c in flag["conflicting_claims"]}
        assert len(claims) == 2

        # additive-only: the existing consensus-count accumulation and the
        # already-real contributing_agents list are completely untouched by
        # a real detected contradiction.
        contributing = {c["agent"] for c in fusion["contributing_agents"]}
        assert contributing == {"rtl-evidence-agent", "log-evidence-agent", "vip-spec-evidence-agent"}
        rcc = h.blackboard.read("root_cause_confidence")["value"]
        assert rcc["concurrent_agent_evidence_count"] == 3
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_rca_join_reports_no_contradiction_when_branches_agree():
    """Two branches independently citing the SAME real root cause is
    corroboration, not contradiction -- must never be flagged."""
    same = "remote-wake enable register never programmed before the LPM token"
    tmp, h = _run_rca_fanout_to_join({
        "RCA_RTL_EVIDENCE": same,
        "RCA_LOG_EVIDENCE": same,
        "RCA_VIP_SPEC_EVIDENCE": None,
    })
    try:
        flag = h.blackboard.read("rca_evidence_fusion")["value"]["branch_contradiction_flag"]
        assert flag["contradiction_detected"] is False
        assert flag["conflicting_claims"] == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_rca_join_reports_no_contradiction_when_branches_are_merely_uncorroborated():
    """One branch citing a real root cause and the other two finding nothing
    citable is the honest UNCORROBORATED case CLAUDE.md's own item text
    distinguishes from a genuine contradiction -- must never be flagged as
    one."""
    tmp, h = _run_rca_fanout_to_join({
        "RCA_RTL_EVIDENCE": "remote-wake enable register never programmed before the LPM token",
        "RCA_LOG_EVIDENCE": None,
        "RCA_VIP_SPEC_EVIDENCE": None,
    })
    try:
        flag = h.blackboard.read("rca_evidence_fusion")["value"]["branch_contradiction_flag"]
        assert flag["contradiction_detected"] is False
        assert flag["conflicting_claims"] == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_rca_join_contradiction_flag_is_never_fabricated_when_no_branch_cites_a_root_cause():
    """The generic placeholder branch text used by every OTHER test in this
    file (no fenced root_cause_evidence_gate block at all, exactly the
    original test_real_issue_triage_dispatches_the_rca_fanout_end_to_end
    fixture) must produce an honest, present, non-contradictory flag -- never
    a missing field, and never a fabricated True."""
    tmp, h = _real_project_harness()
    try:
        h.adapter = _ScriptedAdapter(_texts("REAL_ISSUE"), harness=h)
        h.set_stage("FAILURE_RECOVERY")
        h.run_stage("goal")
        assert h.advance("goal") == "RCA_JOIN"
        h.run_stage("goal")
        assert h.state.stages["RCA_JOIN"]["status"] == Status.PASS.value

        flag = h.blackboard.read("rca_evidence_fusion")["value"]["branch_contradiction_flag"]
        assert flag["contradiction_detected"] is False
        assert flag["conflicting_claims"] == []
        assert "uncorroborated" in flag["basis"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
