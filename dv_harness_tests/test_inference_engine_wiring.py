"""Tests proving dv_harness/inference.py is actually wired into engine.py's
real stage-evaluation flow, not merely defined with zero callers (confirmed
by the 2026-08-28 architecture audit: score_confidence/identify_gap/
next_best_action/promote_if_high_confidence existed as real, tested code but
were never imported by engine.py or gates.py).

The real decision point: RE_AUDIT's root_cause_evidence_gate is the ONE gate
in the whole pipeline that produces a root-cause hypothesis with cited
supporting/counter evidence (see tools/verification_flow/
root_cause_evidence_gate.py's `hypotheses`/`supporting_evidence`/
`counter_evidence`/`confidence` fields). engine.py's new
DVHarness._score_root_cause_confidence(), called from run_stage() right
alongside the existing _promote_experience_knowledge/
_persist_subsystem_registry_entry side effects (same "only on a genuine
gate-verified PASS, best-effort, never downgrades the stage" pattern), now:
  - independently recomputes a confidence LEVEL via score_confidence() from
    real counts pulled out of that SAME evidence block (never trusting the
    agent's own self-reported `confidence` field),
  - reports a real gap via identify_gap() against the gate's own required
    evidence categories,
  - looks up a real next_best_action() suggestion for that gap,
  - and calls promote_if_high_confidence() with a real KnowledgeCenterClient
    (constructed the same way dashboard.py/fsdb_report.py already do:
    KnowledgeCenterClient(cfg, project_root)) ONLY when the recomputed level
    -- not the agent's claimed one -- is HIGH.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from dv_harness.engine import DVHarness
from dv_harness.models import Status
from dv_harness.adapters.base import AgentResult

ROOT = Path(__file__).resolve().parents[1]

# Every RE_AUDIT gate script (see gates.STAGE_GATES["RE_AUDIT"]) must be
# copied into the temp harness's tools/verification_flow/ for a genuine
# subprocess-executed PASS -- these are the real, unmodified scripts shipped
# in this repo, not stubs.
_RE_AUDIT_GATE_SCRIPTS = [
    "root_cause_evidence_gate.py",
    "rca_replay_fix_closure_gate.py",
    "deep_rca_evidence_gate.py",
    "dut_request_record_gate.py",
    "fix_effectiveness_gate.py",
    "fix_regression_non_regression_gate.py",
    "fix_risk_approval_gate.py",
    "nondeterminism_attribution_gate.py",
    "rca_confidence_escalation_gate.py",
    "regression_replay_equivalence_gate.py",
    "root_cause_attribution_consistency_gate.py",
]

_DEEP_RCA_REQUIRED_SOURCES = [
    "SIM_LOG", "TRACE", "RTL", "TESTBENCH", "COMMAND", "SCOREBOARD",
    "PHY_MODEL", "STANDARD_SPEC", "VIP_EXAMPLE", "VIP_SOURCE", "VIP_DOCUMENT",
]


def _fresh_harness():
    """A DVHarness rooted at a fresh temp dir -- no main_graph.json needed:
    _score_root_cause_confidence() only consumes the already-extracted
    evidence_blocks dict, it never touches self.graph. Caller must
    shutil.rmtree(tmp)."""
    tmp = Path(tempfile.mkdtemp())
    return tmp, DVHarness(tmp)


def _install_re_audit_gates(tmp: Path) -> None:
    gate_dir = tmp / "tools" / "verification_flow"
    gate_dir.mkdir(parents=True, exist_ok=True)
    for name in _RE_AUDIT_GATE_SCRIPTS:
        shutil.copy(ROOT / "tools" / "verification_flow" / name, gate_dir / name)
    policy_dir = tmp / ".dv-harness" / "inference"
    policy_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(
        ROOT / ".dv-harness" / "inference" / "inference_policy.json",
        policy_dir / "inference_policy.json",
    )


def _root_cause_evidence_gate_block() -> dict:
    """A real root_cause_evidence_gate PASS payload: 3 hypotheses (root_cause
    matches hypotheses[0].claim; hypotheses[1]/[2] are alternatives each
    independently refuted via their own counter_evidence, satisfying the
    gate's NO_ALTERNATIVE_HYPOTHESIS_REFUTED requirement). The agent's own
    top-level `confidence` is deliberately "MEDIUM" with an EMPTY top-level
    counter_evidence (legal for MEDIUM -- only HIGH/CONFIRMED require it
    non-empty) -- this is the exact real-data shape that lets the test prove
    score_confidence()'s independent recompute (which factors in the
    multi-hypothesis-refutation consensus bonus) can differ from what the
    agent itself claimed."""
    selected_claim = "ep0 FIFO underrun due to missing prefetch on GET_DESCRIPTOR"
    return {
        "symptom": "USB descriptor read timeout observed in regression run r42",
        "first_bad_event": {"time_ns": 1000, "signal": "usb_dev.ep0.timeout_irq"},
        "causal_chain": [
            {"time_ns": 900, "event": "host issues GET_DESCRIPTOR"},
            {"time_ns": 1000, "event": "ep0 fifo underrun -> timeout_irq asserted"},
        ],
        "root_cause": selected_claim,
        "supporting_evidence": [
            {"source": "sim.log", "citation": "line 4021: FIFO_EMPTY at t=1000ns"},
            {"source": "rtl", "citation": "usb_dev_ep0.sv:212 prefetch guard missing"},
        ],
        "counter_evidence": [],
        "confidence": "MEDIUM",
        "hypotheses": [
            {"claim": selected_claim, "category": "DUT_BUG",
             "supporting_evidence": ["sim.log:4021", "rtl:usb_dev_ep0.sv:212"],
             "counter_evidence": [], "missing_evidence": [],
             "confidence": "MEDIUM", "next_action": "confirm with waveform"},
            {"claim": "host-side descriptor request malformed", "category": "TB_BUG",
             "supporting_evidence": ["seq_lib review"],
             "counter_evidence": ["command.txt shows well-formed GET_DESCRIPTOR at t=900ns"],
             "missing_evidence": [], "confidence": "LOW", "next_action": "n/a -- ruled out"},
            {"claim": "VIP driver timing violation", "category": "VIP_ISSUE",
             "supporting_evidence": ["vip config review"],
             "counter_evidence": ["VIP trace shows spec-compliant timing"],
             "missing_evidence": [], "confidence": "LOW", "next_action": "n/a -- ruled out"},
        ],
    }


def _re_audit_pass_text() -> str:
    rca_replay_fix_closure = {
        "rca_id": "RCA-1", "attribution": "DUT_BUG", "reproducer_hash": "h1",
        "fix_commit_hash": "c1", "rerun_evidence_hash": "e1",
        "replay_equivalent": True, "pre_fix_result": "FAIL", "post_fix_result": "PASS",
        "attribution_confidence": "HIGH",
    }
    deep_rca = {
        "rca": {
            "evidence_sources": [
                {"source": s, "checked": True, "evidence_hash": f"h_{s}"}
                for s in _DEEP_RCA_REQUIRED_SOURCES
            ],
            "first_bad_event": {"time_ns": 1000},
            "causal_chain": [{"e": "a"}, {"e": "b"}],
            "confidence": "HIGH",
        }
    }
    dut_request = {
        "dut_request_path": "docs/dut-request.md", "issue_id": "ISSUE-1",
        "classification": "REAL_ISSUE", "root_cause": "ep0 FIFO underrun",
        "fix_summary": "add prefetch guard", "risk_summary": "low risk, localized to ep0",
        "verification_result": "PASS", "change_hash": "chg1",
    }
    fix_effectiveness = {
        "failure_signature_before": "SIG_TIMEOUT_EP0", "failure_signature_after": "NONE",
        "root_cause_id": "RCA-1", "fix_revision": "rev2", "rerun_evidence": "rerun-ev-1",
        "targeted_reproducer_passed": True, "broader_regression_passed": True,
        "new_failures_introduced": False,
    }
    fix_regression_non_regression = {
        "target_pre_fix_result": "FAIL", "target_post_fix_result": "PASS",
        "replay_equivalent": True,
        "critical_non_regression_tests": [
            {"testcase_id": "t1", "pre_fix_result": "PASS", "post_fix_result": "PASS",
             "evidence_hash": "h1"}
        ],
        "fix_commit_hash": "c1", "rerun_bundle_hash": "b1",
    }
    fix_risk_approval = {
        "root_cause_id": "RCA-1", "fix_plan": "add prefetch guard in ep0 fifo ctrl",
        "risk_assessment": "low", "affected_scope": "usb_dev.ep0",
        "regression_plan": "rerun ep0 test suite", "rollback_plan": "revert commit c1",
        "root_cause_confidence": "HIGH", "risk_level": "LOW", "approved_for_modify": True,
    }
    nondeterminism = {"deterministic": True}
    rca_confidence_escalation = {
        "confidence": "HIGH", "first_bad_event": {"time_ns": 1000},
        "causal_chain": [{"e": "a"}, {"e": "b"}],
        "supporting_evidence": ["sim.log:4021"],
        "counter_evidence": ["ruled out TB_BUG via command.txt review"],
    }
    regression_replay_equivalence = {
        "original": {"testcase_id": "t1", "seed": "1", "config_hash": "c1", "build_hash": "b1",
                     "artifact_hash": "a1", "command_hash": "cmd1", "result": "PASS"},
        "replay": {"testcase_id": "t1", "seed": "1", "config_hash": "c1", "build_hash": "b1",
                   "artifact_hash": "a1", "command_hash": "cmd1", "result": "PASS"},
    }
    root_cause_attribution_consistency = {
        "attribution": "DUT", "first_bad_event": {"time_ns": 1000},
        "causal_chain": [{"e": "a"}, {"e": "b"}],
        "supporting_evidence": ["sim.log:4021"],
        "counter_evidence": ["ruled out TB via command.txt"],
        "attribution_confidence": "HIGH",
    }

    blocks = {
        "root_cause_evidence_gate": _root_cause_evidence_gate_block(),
        "rca_replay_fix_closure_gate": rca_replay_fix_closure,
        "deep_rca_evidence_gate": deep_rca,
        "dut_request_record_gate": dut_request,
        "fix_effectiveness_gate": fix_effectiveness,
        "fix_regression_non_regression_gate": fix_regression_non_regression,
        "fix_risk_approval_gate": fix_risk_approval,
        "nondeterminism_attribution_gate": nondeterminism,
        "rca_confidence_escalation_gate": rca_confidence_escalation,
        "regression_replay_equivalence_gate": regression_replay_equivalence,
        "root_cause_attribution_consistency_gate": root_cause_attribution_consistency,
    }
    return "".join(
        f"```dv-harness-evidence:{gid}\n{json.dumps(payload)}\n```\n"
        for gid, payload in blocks.items()
    )


def test_re_audit_pass_wires_real_inference_confidence_gap_and_next_action():
    # End-to-end: a genuine RE_AUDIT PASS (all 11 real gate scripts actually
    # executed via subprocess, not mocked) must drive engine.py's new
    # _score_root_cause_confidence() call site, which in turn calls the REAL
    # dv_harness.inference functions -- proven by checking their exact,
    # independently-computable outputs land in both the blackboard and the
    # event log, not just "some dict got written".
    tmp, h = _fresh_harness()
    try:
        _install_re_audit_gates(tmp)
        h.set_stage("RE_AUDIT")
        text = _re_audit_pass_text()

        class _PassAdapter:
            def run(self, prompt, cwd, resume_session=None, agent_profile=None):
                return AgentResult(ok=True, text=text, raw={}, session_id=None)

        h.adapter = _PassAdapter()
        h.run_stage("goal")
        assert h.state.stages["RE_AUDIT"]["status"] == Status.PASS.value

        # --- score_confidence(): independently recomputed, NOT the agent's
        # own self-reported "confidence": "MEDIUM" -----------------------
        # independent_sources_count = len(supporting_evidence) = 2 -> 4
        # + evidence_refs_verified (first_bad_event/causal_chain/
        #   supporting_evidence all present) -> +2 = 6
        # + multi_agent_consensus_count = 2 (both alternative hypotheses
        #   independently refuted with their own counter_evidence) -> +2 = 8
        # counter_evidence_count = 0 (top-level counter_evidence is [])
        # -> no subtraction, no safety-floor cap -> HIGH.
        bb = h.blackboard.read("root_cause_confidence")
        assert bb is not None, "wiring must write a real blackboard record, not skip silently"
        conf = bb["value"]["recomputed_confidence"]
        assert conf == {"level": "HIGH", "score": 8, "capped_by_counter_evidence": False}
        assert bb["value"]["agent_reported_confidence"] == "MEDIUM"
        assert conf["level"] != bb["value"]["agent_reported_confidence"], (
            "the whole point of independent recompute is that it need not match "
            "the agent's own self-reported confidence"
        )

        # --- identify_gap(): counter_evidence is the one real evidence
        # category still empty on the SELECTED root_cause, independent of
        # the (unrelated) confidence-level recompute above --------------
        assert bb["value"]["gap"] == ["counter_evidence"]

        # --- next_best_action(): real generic-fallback branch (no protocol
        # was supplied in the evidence block, so no registry match is
        # possible -- this must be an honest "go inspect evidence" message,
        # never a fabricated specific-sounding registry reference) --------
        next_actions = bb["value"]["next_best_action"]
        assert len(next_actions) == 1
        assert next_actions[0]["gap"] == "counter_evidence"
        assert next_actions[0]["source"] == "generic"
        assert "no concrete registry item found" in next_actions[0]["suggested_action"]

        # --- promote_if_high_confidence(): a real KnowledgeCenterClient is
        # constructed and called (level IS HIGH) -- with knowledge_center
        # left at its default disabled config, add() genuinely returns
        # NOT_CONFIGURED, and that must surface as KC_ADD_FAILED, never as
        # a fabricated "promoted": True. -----------------------------------
        promotion = bb["value"]["promotion"]
        assert promotion["promoted"] is False
        assert promotion["reason"] == "KC_ADD_FAILED"
        assert promotion["kc_result"] == {"ok": False, "error": "NOT_CONFIGURED"}

        # Same data must also have been recorded as a durable event.
        events = (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
        scored = [json.loads(e) for e in events if json.loads(e).get("event") == "ROOT_CAUSE_CONFIDENCE_SCORED"]
        assert scored, f"no ROOT_CAUSE_CONFIDENCE_SCORED event recorded: {events}"
        assert scored[0]["recomputed_confidence"] == conf
        assert scored[0]["gap"] == ["counter_evidence"]
    finally:
        shutil.rmtree(tmp)


def test_low_confidence_finding_never_calls_promote_and_reports_larger_gap():
    # Direct call against the real method (still genuinely invoking
    # dv_harness.inference's real functions, just without re-running all 11
    # subprocess gate scripts) -- a sparse, low-signal finding: exactly 1
    # supporting-evidence citation, no verified base fields, no refuted
    # alternative hypotheses. Must recompute to LOW and never even attempt
    # a promotion.
    tmp, h = _fresh_harness()
    try:
        h.set_stage("RE_AUDIT")
        evidence_blocks = {
            "root_cause_evidence_gate": {
                "symptom": "s", "first_bad_event": {}, "causal_chain": [],
                "root_cause": "unclear", "supporting_evidence": ["one weak citation"],
                "counter_evidence": [], "confidence": "LOW",
                "hypotheses": [
                    {"claim": "unclear", "category": "UNKNOWN", "supporting_evidence": ["x"],
                     "counter_evidence": [], "missing_evidence": ["waveform"],
                     "confidence": "LOW", "next_action": "gather more evidence"},
                ],
            }
        }
        h._score_root_cause_confidence("RE_AUDIT", evidence_blocks)

        bb = h.blackboard.read("root_cause_confidence")
        assert bb is not None
        conf = bb["value"]["recomputed_confidence"]
        # independent_sources_count=1 -> 2; evidence_refs_verified=False
        # (first_bad_event=={} and causal_chain==[] are both falsy) -> +0;
        # counter_evidence_count=0; multi_agent_consensus_count=0 (no OTHER
        # hypotheses at all) -> score=2 -> LOW.
        assert conf == {"level": "LOW", "score": 2, "capped_by_counter_evidence": False}
        # Real gap: both first_bad_event and causal_chain are empty/falsy in
        # THIS block, on top of counter_evidence.
        assert bb["value"]["gap"] == ["first_bad_event", "causal_chain", "counter_evidence"]
        assert bb["value"]["promotion"] is None, (
            "promote_if_high_confidence must never be invoked for a non-HIGH level"
        )

        events = (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
        scored = [json.loads(e) for e in events if json.loads(e).get("event") == "ROOT_CAUSE_CONFIDENCE_SCORED"]
        assert scored and scored[0]["promotion"] is None
    finally:
        shutil.rmtree(tmp)


def test_stage_without_root_cause_gate_is_untouched_backward_compatible():
    # Backward compatibility: any stage whose STAGE_GATES mapping does not
    # include root_cause_evidence_gate (i.e. every stage except RE_AUDIT)
    # must be a complete no-op -- no blackboard write, no event, matching
    # this method's exact behavior before this feature existed for those
    # stages.
    tmp, h = _fresh_harness()
    try:
        h._score_root_cause_confidence("VERIFY", {"some_other_gate": {"x": 1}})
        assert h.blackboard.read("root_cause_confidence") is None
        events_path = tmp / ".dv-harness" / "events.jsonl"
        assert not events_path.exists() or "ROOT_CAUSE_CONFIDENCE_SCORED" not in events_path.read_text(encoding="utf-8")
    finally:
        shutil.rmtree(tmp)


def test_re_audit_without_root_cause_evidence_block_is_also_a_no_op():
    # RE_AUDIT is the mapped stage, but this particular evidence_blocks dict
    # simply never carried a root_cause_evidence_gate block (e.g. a
    # MISSING_EVIDENCE/GATE_FAIL run never reaches the PASS branch that
    # calls this method at all in engine.py -- this directly proves the
    # method itself is also defensive if ever called without one).
    tmp, h = _fresh_harness()
    try:
        h._score_root_cause_confidence("RE_AUDIT", {})
        assert h.blackboard.read("root_cause_confidence") is None
    finally:
        shutil.rmtree(tmp)
