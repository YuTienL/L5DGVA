"""The Engineering -> Organizational promotion EVALUATION, wired into the
SECOND real production writer (2026-09-04, gap-close-ai-engine #7 "5-Level
Memory Engine").

`test_engineering_confirmation_accumulation.py` proves the confirmation really
accumulates on the real path and that `promote_to_organizational()` then
succeeds -- but it calls that function by hand. In production only ONE of
`DVHarness`'s two Engineering-tier writers actually asked:
`_promote_verified_fix_knowledge()` (RE_AUDIT / `verified_fix`).
`_promote_experience_knowledge()` (EXPERT_FEEDBACK_LOOP / `debug_lesson`) wrote
through the same `_add_or_confirm_engineering()` -- so it could raise a
record's `confirmation_count` past `ORGANIZATIONAL_MIN_CONFIRMATIONS`, i.e.
clear the one gate that had never been cleared -- and then evaluated nothing.

An EXPERT_FEEDBACK_LOOP PASS independently re-deriving a root cause a previous
RE_AUDIT already recorded is exactly the "second independent run" CLAUDE.md's
confirmation rule is written around. Before this, that moment reached the
Organizational tier only if a human remembered to run `dv-harness memory
promote` by hand.

These tests run the REAL cross-stage sequence -- a real RE_AUDIT
`run_stage()` PASS followed by real EXPERT_FEEDBACK_LOOP `run_stage()` PASSes,
every mapped gate script executed as a real subprocess, a real un-mocked
`route_and_store()` writing to a real `MemoryStore` -- and assert the
evaluation now fires by itself from the experience path. Nothing here calls
`promote_to_organizational()` or `MemoryGC.confirm()` directly; that is the
entire point.

Fixtures are imported from `test_engineering_confirmation_accumulation` rather
than copied, so both modules stay bound to one definition of a real PASS.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from dv_harness.engine import DVHarness
from dv_harness.memory import MemoryStore
from dv_harness.memory_router import ORGANIZATIONAL_MIN_CONFIRMATIONS
from dv_harness.models import Status
from dv_harness_tests.test_engineering_confirmation_accumulation import (
    _FIXTURE_ROOT_CAUSE,
    _USB_GOAL,
    _PassAdapter,
    _engineering_records,
    _fresh_harness_with_graph,
    _run_re_audit_pass,
)

ROOT = Path(__file__).resolve().parents[1]

_EXPERT_FEEDBACK_GATE_SCRIPTS = (
    "expert_feedback_closure_gate.py",
    "experience_knowledge_gate.py",
    "experience_applicability_gate.py",
)


def _install_expert_feedback_gates(tmp: Path) -> None:
    gate_dir = tmp / "tools" / "verification_flow"
    gate_dir.mkdir(parents=True, exist_ok=True)
    for name in _EXPERT_FEEDBACK_GATE_SCRIPTS:
        shutil.copy(ROOT / "tools" / "verification_flow" / name, gate_dir / name)


def _expert_feedback_pass_text(root_cause: str, knowledge_id: str) -> str:
    """A real EXPERT_FEEDBACK_LOOP PASS payload for all three of that stage's
    STAGE_GATES members -- the same shape
    test_engine_gates_and_routing.test_run_stage_promotes_experience_knowledge_
    to_engineering_memory_on_pass already proves really PASSes.

    `root_cause` is the half of the (protocol, root_cause) dedup key this
    stage supplies; the other half is the harness's own resolve_protocol()
    value, exactly as in production."""
    feedback = {"items": [{"feedback_id": "f1", "disposition": "ACCEPTED", "expert_id": "e1",
                           "rationale": "r", "action_id": "a1", "closure_evidence_hash": "h1"}]}
    knowledge = {"knowledge_id": knowledge_id, "title": "t", "pattern": "p",
                 "root_cause": root_cause, "evidence": "ev",
                 "applicability_constraints": "ac", "expert_approved": True}
    applicability = {"knowledge": {"expert_approved": True, "evidence": "ev1",
                                   "applicability_constraints": {"protocol": "USB"}},
                     "context": {"protocol": "USB"}}
    return (
        f"```dv-harness-evidence:expert_feedback_closure_gate\n{json.dumps(feedback)}\n```\n"
        f"```dv-harness-evidence:experience_knowledge_gate\n{json.dumps(knowledge)}\n```\n"
        f"```dv-harness-evidence:experience_applicability_gate\n{json.dumps(applicability)}\n```\n"
    )


def _run_expert_feedback_pass(h: DVHarness, goal: str, root_cause: str,
                              knowledge_id: str = "K-1") -> None:
    """One real, independently gate-verified EXPERT_FEEDBACK_LOOP PASS."""
    h.set_stage("EXPERT_FEEDBACK_LOOP")
    h.adapter = _PassAdapter(_expert_feedback_pass_text(root_cause, knowledge_id))
    h.run_stage(goal)
    assert h.state.stages["EXPERT_FEEDBACK_LOOP"]["status"] == Status.PASS.value


def _events(root: Path, name: str):
    path = root / ".dv-harness" / "events.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("event") == name:
            out.append(ev)
    return out


def _fresh_harness_for_both_stages():
    tmp, h = _fresh_harness_with_graph()
    _install_expert_feedback_gates(tmp)
    return tmp, h


def test_re_audit_persists_the_real_confidence_inputs_on_the_engineering_record():
    # The enabling half of the wiring. inference.score_confidence()'s four
    # inputs are only derivable from a real root_cause_evidence_gate evidence
    # block, and EXPERT_FEEDBACK_LOOP has none (gates.STAGE_GATES registers
    # experience_knowledge_gate on that stage alone, and root_cause_evidence_
    # gate only on RCA_JOIN/RE_AUDIT). So the run that DOES have one now
    # persists what it really derived, letting a later confirming run evaluate
    # promotion against real inputs instead of having none at all.
    #
    # Asserted against the durable store, and required to actually score HIGH,
    # so a fixture change that made these inputs vacuous cannot silently turn
    # the promotion test below into a no-op.
    from dv_harness.inference import score_confidence

    tmp, h = _fresh_harness_with_graph()
    try:
        _run_re_audit_pass(h, _USB_GOAL)
        record = [r for r in _engineering_records(tmp) if r.get("kind") == "verified_fix"][0]
        inputs = record.get("confidence_inputs")
        assert isinstance(inputs, dict), record
        assert set(inputs) == {"independent_sources_count", "evidence_refs_verified",
                               "counter_evidence_count", "multi_agent_consensus_count"}
        assert score_confidence(**inputs)["level"] == "HIGH", inputs
    finally:
        shutil.rmtree(tmp)


def test_expert_feedback_loop_pass_that_confirms_a_record_evaluates_organizational_promotion():
    # THE gap this closes, end to end on the real path. One real RE_AUDIT PASS
    # records the finding; two real EXPERT_FEEDBACK_LOOP PASSes independently
    # re-derive the same (protocol, root_cause) and so confirm it twice,
    # clearing promote_to_organizational()'s third gate. The evaluation must
    # fire BY ITSELF from the experience path -- no hand-run CLI verb -- and
    # must really land the record in the Organizational tier.
    tmp, h = _fresh_harness_for_both_stages()
    try:
        _run_re_audit_pass(h, _USB_GOAL)
        record = [r for r in _engineering_records(tmp) if r.get("kind") == "verified_fix"][0]
        memory_id = record["memory_id"]
        assert record["confirmation_count"] == 0

        # Confirmation 1 of 2: the gate is not yet clearable, so the
        # evaluation fires and honestly refuses.
        _run_expert_feedback_pass(h, _USB_GOAL, _FIXTURE_ROOT_CAUSE, knowledge_id="K-1")
        assert MemoryStore(tmp).get(memory_id)["confirmation_count"] == 1
        evals = [e for e in _events(tmp, "ORGANIZATIONAL_PROMOTION_EVALUATED")
                 if e["memory_id"] == memory_id]
        assert evals, "the experience path confirmed a record and never evaluated promotion"
        assert evals[-1]["result"]["reason"] == "INSUFFICIENT_CONFIRMATION", evals[-1]

        # Confirmation 2 of 2: gate 3 clears, and the promotion really happens.
        _run_expert_feedback_pass(h, _USB_GOAL, _FIXTURE_ROOT_CAUSE, knowledge_id="K-2")
        assert (MemoryStore(tmp).get(memory_id)["confirmation_count"]
                == ORGANIZATIONAL_MIN_CONFIRMATIONS)

        evals = [e for e in _events(tmp, "ORGANIZATIONAL_PROMOTION_EVALUATED")
                 if e["memory_id"] == memory_id]
        final = evals[-1]["result"]
        # A cleared promotion returns route_and_store()'s own result -- there
        # is no "promoted": True key on the success path -- so assert the
        # record really reached ORGANIZATIONAL_MEMORY rather than being
        # demoted to Working with an organizational_admission_rejected reason.
        assert final.get("destination") == "ORGANIZATIONAL_MEMORY", final
        assert final["promotion_gate"]["confirmation_count"] == ORGANIZATIONAL_MIN_CONFIRMATIONS
        assert final["promotion_gate"]["qualitative_shape"] == "re_audit_gate_shape"
        assert final["promotion_gate"]["confidence_result"]["level"] == "HIGH"

        # Still ONE verified_fix record: confirming must never mint a rival copy.
        assert len([r for r in _engineering_records(tmp) if r.get("kind") == "verified_fix"]) == 1
    finally:
        shutil.rmtree(tmp)


def test_a_first_experience_pass_that_confirms_nothing_evaluates_nothing():
    # The precision half: the evaluation is bound to the CONFIRMATION event,
    # not to "an experience record was written". A freshly-minted record has
    # confirmation_count 0 and could only ever produce an
    # INSUFFICIENT_CONFIRMATION event, so firing on it would be noise rather
    # than coverage.
    tmp, h = _fresh_harness_for_both_stages()
    try:
        _run_expert_feedback_pass(h, _USB_GOAL, "a root cause nothing else recorded")
        assert [r for r in _engineering_records(tmp) if r.get("kind") == "debug_lesson"], (
            "the experience write path did not run at all -- this test proves nothing")
        assert _events(tmp, "ORGANIZATIONAL_PROMOTION_EVALUATED") == []
    finally:
        shutil.rmtree(tmp)


def test_a_confirmed_record_without_persisted_confidence_inputs_is_not_scored_on_invented_ones():
    # The honest half. A record created before this change -- or by a write
    # path that never had a root_cause_evidence_gate block -- carries no
    # persisted confidence inputs, and EXPERT_FEEDBACK_LOOP cannot derive them
    # because that stage has no root_cause evidence at all. The evaluation
    # must record NO_CONFIDENCE_INPUTS rather than fabricate counts that would
    # score HIGH and promote a record on invented evidence.
    tmp, h = _fresh_harness_for_both_stages()
    try:
        _run_re_audit_pass(h, _USB_GOAL)
        record = [r for r in _engineering_records(tmp) if r.get("kind") == "verified_fix"][0]
        memory_id = record["memory_id"]

        # Reproduce the pre-existing on-disk shape by removing ONLY the newly
        # persisted field, leaving every gate-relevant field untouched.
        store = MemoryStore(tmp)
        stripped = {k: v for k, v in store.get(memory_id).items() if k != "confidence_inputs"}
        (tmp / ".dv-harness" / "memory" / "engineering" / f"{memory_id}.json").write_text(
            json.dumps(stripped, ensure_ascii=False, indent=2), encoding="utf-8")

        _run_expert_feedback_pass(h, _USB_GOAL, _FIXTURE_ROOT_CAUSE)

        evals = [e for e in _events(tmp, "ORGANIZATIONAL_PROMOTION_EVALUATED")
                 if e["memory_id"] == memory_id]
        assert evals, "the confirmation happened but nothing was recorded"
        assert evals[-1]["result"] == {"promoted": False, "reason": "NO_CONFIDENCE_INPUTS"}
    finally:
        shutil.rmtree(tmp)
