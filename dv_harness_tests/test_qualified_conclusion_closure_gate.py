"""The Qualified Conclusion actually entering CLOSURE -- proven on the real
production path (engine.loop() -> policy.can_signoff()), not in isolation.

Why this file exists (2026-09-04 re-audit of mechanism #9, "Hypothesis +
Evidence + Result + Gate = Conclusion"). Every ingredient was already real,
wired and firing: RE_AUDIT's 11 hard gates run as real subprocesses and their
exit codes are ground truth, root_cause_evidence_gate structurally requires
>=2 hypotheses with a refuted alternative, inference.score_confidence()
independently recomputes confidence from that same block, and
engine._score_root_cause_confidence() composes the two into a real
QualifiedConclusion on every gate-verified RE_AUDIT PASS.

What did NOT exist is the last edge: that conclusion was written to the
"qualified_conclusion" Blackboard topic and then read by NOTHING on the
production path.

  - `grep -rn qualified_conclusion` outside .work/ matched engine.py (the
    writer), qualified_conclusion.py, dashboard.py (display only) and
    test_qualified_conclusion.py -- and NO node in the real shipped
    .dv-harness/graph/main_graph.json declared it in `blackboard_read`, so
    no closure stage ever even saw it in its prompt.
  - policy.can_signoff() -- the one hard-stop engine.loop() consults BEFORE
    running SIGNOFF -- asked only whether RE_AUDIT reached stage PASS
    (`require_second_pass_audit`), never what it CONCLUDED.

The difference between those two facts is reachable, not theoretical, which
test_a_gate_passing_re_audit_can_still_conclude_not_qualified below proves
against the real gate scripts: root_cause_evidence_gate only mandates
non-empty counter_evidence at its own HIGH/CONFIRMED tier, so a MEDIUM
finding with one supporting citation and two unrefuted counter-evidence
entries passes all 11 RE_AUDIT gates while score_confidence() recomputes to
LOW (2*1 + 2 - 3*2 = -2) -- is_qualified=False. Before this fix that run
closed into SIGNOFF exactly like a fully qualified one.

The RE_AUDIT gate fixtures are IMPORTED from test_inference_engine_wiring
rather than copied: they are the same real, already-verified 11-gate PASS
payloads, and a second copy here could silently drift from the gate scripts.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from dv_harness import policy as policy_mod
from dv_harness.engine import DVHarness
from dv_harness.gates import extract_evidence_blocks
from dv_harness.models import Status
from dv_harness.policy import can_signoff, read_qualified_conclusion
from dv_harness.adapters.base import AgentResult

from dv_harness_tests.test_inference_engine_wiring import (
    _install_re_audit_gates,
    _re_audit_pass_text,
    _root_cause_evidence_gate_block,
)

ROOT = Path(__file__).resolve().parents[1]

_SELECTED_CLAIM = "ep0 FIFO underrun due to missing prefetch on GET_DESCRIPTOR"


def _unqualified_root_cause_block() -> dict:
    """A root_cause_evidence_gate payload that genuinely PASSES the real gate
    yet recomputes to LOW confidence, i.e. is_qualified=False.

    It clears every one of the gate's own structural requirements (all seven
    required fields, a non-empty first_bad_event/causal_chain/
    supporting_evidence, a valid confidence level, 2 hypotheses with the
    selected root_cause matching hypotheses[0].claim and hypotheses[1]
    carrying its own counter_evidence). What makes it unqualified is the
    arithmetic score_confidence() applies to that same real data:
      min(1,3)*2  (one supporting citation)      =  2
      + 2         (first_bad_event + causal_chain + supporting_evidence)
      - 2*3       (two recorded, unrefuted counter-evidence entries)
      + 0         (only ONE other hypothesis refuted -> consensus 1, no bonus)
      = -2        -> LOW
    `confidence` is MEDIUM, deliberately: the gate's
    HIGH_CONFIDENCE_WITHOUT_COUNTER_EVIDENCE_REVIEW check only applies at the
    HIGH/CONFIRMED tier, which is exactly why this shape gets through it."""
    return {
        "symptom": "USB descriptor read timeout observed in regression run r42",
        "first_bad_event": {"time_ns": 1000, "signal": "usb_dev.ep0.timeout_irq"},
        "causal_chain": [
            {"time_ns": 900, "event": "host issues GET_DESCRIPTOR"},
            {"time_ns": 1000, "event": "ep0 fifo underrun -> timeout_irq asserted"},
        ],
        "root_cause": _SELECTED_CLAIM,
        "supporting_evidence": ["sim.log:4021 FIFO_EMPTY at t=1000ns"],
        "counter_evidence": [
            "waveform shows the prefetch fifo non-empty at t=980ns",
            "a second run at the same seed did not reproduce the timeout",
        ],
        "confidence": "MEDIUM",
        "hypotheses": [
            {"claim": _SELECTED_CLAIM, "category": "DUT_BUG",
             "supporting_evidence": ["sim.log:4021"], "counter_evidence": [],
             "missing_evidence": [], "confidence": "MEDIUM",
             "next_action": "confirm with waveform"},
            {"claim": "host-side descriptor request malformed", "category": "TB_BUG",
             "supporting_evidence": ["seq_lib review"],
             "counter_evidence": ["command.txt shows a well-formed GET_DESCRIPTOR at t=900ns"],
             "missing_evidence": [], "confidence": "LOW", "next_action": "n/a -- ruled out"},
        ],
    }


def _re_audit_text(root_cause_block: dict) -> str:
    """The real 11-gate RE_AUDIT PASS evidence with only its
    root_cause_evidence_gate block swapped. Re-parsed through the REAL
    gates.extract_evidence_blocks() the engine itself uses, so this helper
    cannot drift from the fence format run_stage() actually reads."""
    blocks = extract_evidence_blocks(_re_audit_pass_text())
    blocks["root_cause_evidence_gate"] = root_cause_block
    return "".join(
        f"```dv-harness-evidence:{gid}\n{json.dumps(payload)}\n```\n"
        for gid, payload in blocks.items()
    )


class _TextAdapter:
    """Stands in for the agent authoring the evidence. Counts its own calls:
    that count is what distinguishes 'loop() refused SIGNOFF before running
    it' (0 calls) from 'loop() actually reached SIGNOFF' (>=1)."""

    def __init__(self, text: str):
        self.text = text
        self.calls: list[str] = []

    def run(self, prompt, cwd, resume_session=None, agent_profile=None):
        self.calls.append(prompt)
        return AgentResult(ok=True, text=self.text, raw={}, session_id=None)


def _closure_project() -> Path:
    """A project root a real RE_AUDIT and a real loop()-driven SIGNOFF can
    both run in: its own copy of the RE_AUDIT gate scripts + inference policy,
    and the REAL shipped graph (so the blackboard_read edge under test is the
    shipped one, not a fixture)."""
    tmp = Path(tempfile.mkdtemp())
    _install_re_audit_gates(tmp)
    (tmp / ".dv-harness" / "graph").mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / ".dv-harness" / "graph" / "main_graph.json",
                tmp / ".dv-harness" / "graph" / "main_graph.json")
    return tmp


def _drive_re_audit(tmp: Path, root_cause_block: dict) -> DVHarness:
    h = DVHarness(tmp)
    h.set_stage("RE_AUDIT")
    h.adapter = _TextAdapter(_re_audit_text(root_cause_block))
    h.run_stage("close out the ep0 timeout root cause")
    assert h.state.stages["RE_AUDIT"]["status"] == Status.PASS.value, \
        h.state.stages["RE_AUDIT"].get("blocking_reason")
    return h


def _arm_signoff(h: DVHarness) -> _TextAdapter:
    """Point the harness at SIGNOFF with a fresh adapter that submits NO
    evidence. If loop() reaches SIGNOFF at all the adapter records a call and
    the stage then fails its own gate battery, which is enough -- this test is
    about the pre-stage refusal, not about satisfying the 9 SIGNOFF gates
    (test_signoff_stage_gate_e2e.py already does that end to end)."""
    h.set_stage("SIGNOFF")
    h.cfg["policy"]["max_stage_retries"] = 0
    h.cfg["policy"]["enable_inner_react_loop"] = False
    adapter = _TextAdapter("no evidence submitted")
    h.adapter = adapter
    return adapter


# --- 1. the hole is real and reachable ---------------------------------------

def test_a_gate_passing_re_audit_can_still_conclude_not_qualified():
    """All 11 real RE_AUDIT gate scripts PASS as subprocesses, the stage
    closes PASS -- and the composed conclusion is nonetheless NOT qualified.
    This is the reachability proof the whole gate below rests on; without it
    can_signoff()'s new check would be guarding an impossible state."""
    tmp = _closure_project()
    try:
        h = _drive_re_audit(tmp, _unqualified_root_cause_block())

        qc = read_qualified_conclusion(h.blackboard)
        assert qc is not None, "a gate-verified RE_AUDIT PASS must record a conclusion"
        assert qc["gate_verdict"] == "PASS"
        assert qc["inference_confidence"] == {
            "level": "LOW", "score": -2, "capped_by_counter_evidence": False}
        assert qc["is_qualified"] is False
        # The hypothesis carried into the conclusion is the SELECTED claim the
        # gate structurally tied to hypotheses[0], not free text.
        assert qc["hypothesis"] == _SELECTED_CLAIM
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- 2. the real production path now refuses closure --------------------------

def test_loop_refuses_signoff_while_the_recorded_conclusion_is_not_qualified():
    """The gap, closed on the real path: engine.loop() must not run SIGNOFF at
    all while the recorded conclusion says is_qualified=False -- proven by the
    SIGNOFF adapter never being invoked, not merely by a return value."""
    tmp = _closure_project()
    try:
        h = _drive_re_audit(tmp, _unqualified_root_cause_block())
        adapter = _arm_signoff(h)

        h.loop("sign off the environment")

        assert adapter.calls == [], "SIGNOFF must never have been dispatched"
        assert h.state.stages["SIGNOFF"]["status"] == Status.BLOCKED.value
        reason = h.state.stages["SIGNOFF"].get("last_message") or ""
        assert "Qualified Conclusion" in reason and "LOW" in reason, reason
        # Still at SIGNOFF, blocked for a human -- not silently rerouted.
        assert h.state.current_stage == "SIGNOFF"

        # require_second_pass_audit is NOT what stopped it: RE_AUDIT really is
        # PASS, so the older check passes and only the new one refuses.
        assert h.state.stages["RE_AUDIT"]["status"] == Status.PASS.value
        assert can_signoff(h.state, h.cfg)[0] is True, \
            "without the blackboard, can_signoff must be unchanged from before"
        assert can_signoff(h.state, h.cfg, h.blackboard)[0] is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_loop_reaches_signoff_once_the_conclusion_qualifies():
    """The other half: the refusal is tied to the conclusion, not to anything
    else about the project. The SAME project, re-audited with the real
    HIGH-confidence evidence, dispatches SIGNOFF for real."""
    tmp = _closure_project()
    try:
        h = _drive_re_audit(tmp, _unqualified_root_cause_block())
        assert read_qualified_conclusion(h.blackboard)["is_qualified"] is False

        # A genuine re-audit with better evidence: the same 11 real gates, the
        # HIGH-confidence root-cause block (3 supporting-evidence-backed
        # hypotheses, two independently refuted -> score 8 -> HIGH).
        h.set_stage("RE_AUDIT")
        h.adapter = _TextAdapter(_re_audit_text(_root_cause_evidence_gate_block()))
        h.run_stage("re-audit with corroborating evidence")
        assert h.state.stages["RE_AUDIT"]["status"] == Status.PASS.value
        qc = read_qualified_conclusion(h.blackboard)
        assert qc["inference_confidence"]["level"] == "HIGH"
        assert qc["is_qualified"] is True

        adapter = _arm_signoff(h)
        h.loop("sign off the environment")

        assert adapter.calls, "SIGNOFF must now actually be dispatched"
        assert h.state.stages["SIGNOFF"]["status"] != Status.BLOCKED.value
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- 3. disclosed residual and the policy switch ------------------------------

def test_absence_of_a_conclusion_record_is_not_a_refusal():
    """Disclosed residual, asserted rather than left implicit: only a recorded
    conclusion that says is_qualified=False blocks. A project that never wrote
    one is governed by require_second_pass_audit alone, exactly as before --
    blocking on absence would make every pre-existing project unclosable."""
    tmp = _closure_project()
    try:
        h = DVHarness(tmp)
        h.state.stages["RE_AUDIT"]["status"] = Status.PASS.value
        assert read_qualified_conclusion(h.blackboard) is None
        assert can_signoff(h.state, h.cfg, h.blackboard) == (True, "", None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_require_qualified_conclusion_false_disables_the_check():
    tmp = _closure_project()
    try:
        h = _drive_re_audit(tmp, _unqualified_root_cause_block())
        assert can_signoff(h.state, h.cfg, h.blackboard)[0] is False
        h.cfg["policy"]["require_qualified_conclusion"] = False
        assert can_signoff(h.state, h.cfg, h.blackboard) == (True, "", None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_read_qualified_conclusion_tolerates_missing_and_malformed_records():
    """It is consulted from a hard-stop that must never crash a real run."""
    assert read_qualified_conclusion(None) is None
    tmp = Path(tempfile.mkdtemp())
    try:
        h = DVHarness(tmp)
        assert read_qualified_conclusion(h.blackboard) is None
        h.blackboard.write(policy_mod.QUALIFIED_CONCLUSION_TOPIC, "not-a-dict", source="test")
        assert read_qualified_conclusion(h.blackboard) is None
        # A record with no is_qualified key is not a refusal either -- only an
        # explicit False is.
        h.blackboard.write(policy_mod.QUALIFIED_CONCLUSION_TOPIC, {"gate_verdict": "PASS"},
                           source="test")
        h.state.stages["RE_AUDIT"]["status"] = Status.PASS.value
        assert can_signoff(h.state, h.cfg, h.blackboard) == (True, "", None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- 4. the graph half: the closure stages really READ the topic --------------

def test_closure_nodes_read_the_conclusion_in_the_real_shipped_graph():
    """The other direction of the same gap. can_signoff() stops an unqualified
    conclusion from closing; this edge is what puts the conclusion in front of
    the closure stages at all -- engine.run_stage() snapshots
    node.blackboard_read into the stage prompt, so a topic no node declares is
    invisible to every agent. Asserted against the REAL shipped graph."""
    graph = json.loads((ROOT / ".dv-harness" / "graph" / "main_graph.json")
                       .read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in graph["nodes"]}
    topic = policy_mod.QUALIFIED_CONCLUSION_TOPIC
    for stage in ("REQUIREMENT_CLOSURE", "PROMOTION_READINESS", "SIGNOFF"):
        assert topic in (nodes[stage].get("blackboard_read") or []), \
            f"{stage} must read the Qualified Conclusion it is closing on"

    # And SIGNOFF's entry checklist names it, so a run that reaches SIGNOFF
    # without one is reported rather than silently unremarked.
    signoff_checklist = {i["item_id"] for i in (nodes["SIGNOFF"].get("expected_evidence") or [])}
    assert topic in signoff_checklist


def test_the_conclusion_topic_really_reaches_a_closure_stage_prompt():
    """The declaration above is only half an edge -- this proves the engine
    actually serializes that topic's real value into the stage prompt."""
    tmp = _closure_project()
    try:
        h = _drive_re_audit(tmp, _unqualified_root_cause_block())
        h.set_stage("PROMOTION_READINESS")
        h.cfg["policy"]["max_stage_retries"] = 0
        h.cfg["policy"]["enable_inner_react_loop"] = False
        adapter = _TextAdapter("no evidence submitted")
        h.adapter = adapter
        h.run_stage("assess promotion readiness")

        assert adapter.calls
        prompt = adapter.calls[0]
        assert policy_mod.QUALIFIED_CONCLUSION_TOPIC in prompt
        assert _SELECTED_CLAIM in prompt, \
            "the real conclusion's own hypothesis must reach the closure prompt"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
