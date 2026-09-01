"""Tests for dv_harness/qualified_conclusion.py -- the first-class "Qualified
Conclusion" verdict type this harness's AI-mechanism architecture audit
(2026-09-01) found was missing, even though every ingredient it needs
already existed as real, wired, tested code: gates.py's
evaluate_stage_evidence_with_detail() (per-stage gate verdicts, factored
through react_loop.py) and inference.py's score_confidence() (independently
recomputed confidence, never the agent's self-reported value).

Covers both layers:
  - build_qualified_conclusion() as a pure function, directly, for the exact
    three scenarios the task specifies (PASS+HIGH -> qualified; GATE_FAIL ->
    not qualified regardless of confidence; PASS+LOW -> not qualified) plus
    boundary/error-path cases.
  - the real engine.py call site (DVHarness._score_root_cause_confidence),
    proving the composed QualifiedConclusion actually gets persisted to the
    "qualified_conclusion" Blackboard topic during a real RE_AUDIT run, not
    only reachable as a standalone unit.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness.qualified_conclusion import (
    QualifiedConclusion,
    build_qualified_conclusion,
    InvalidGateVerdictError,
    InvalidConfidenceResultError,
    InvalidExecutionEvidenceError,
    QUALIFYING_GATE_VERDICTS,
)
from dv_harness.inference import score_confidence
from dv_harness.engine import DVHarness

# A real root_cause_evidence_gate-shaped payload (same fields the actual gate
# script and engine.py's _score_root_cause_confidence read) -- used as
# execution_evidence across the pure-function tests below.
_EXECUTION_EVIDENCE = {
    "symptom": "USB descriptor read timeout observed in regression run r42",
    "first_bad_event": {"time_ns": 1000, "signal": "usb_dev.ep0.timeout_irq"},
    "causal_chain": [
        {"time_ns": 900, "event": "host issues GET_DESCRIPTOR"},
        {"time_ns": 1000, "event": "ep0 fifo underrun -> timeout_irq asserted"},
    ],
    "root_cause": "ep0 FIFO underrun due to missing prefetch on GET_DESCRIPTOR",
    "supporting_evidence": [
        {"source": "sim.log", "citation": "line 4021: FIFO_EMPTY at t=1000ns"},
        {"source": "rtl", "citation": "usb_dev_ep0.sv:212 prefetch guard missing"},
    ],
    "counter_evidence": [],
}


def _confidence(level: str, **overrides) -> dict:
    """A real score_confidence()-shaped dict at the given level, using
    score_confidence() itself (not a hand-authored stand-in) so these tests
    stay tied to the real inference.py contract."""
    presets = {
        "HIGH": dict(independent_sources_count=3, evidence_refs_verified=True,
                     counter_evidence_count=0, multi_agent_consensus_count=2),
        "MEDIUM": dict(independent_sources_count=1, evidence_refs_verified=True,
                       counter_evidence_count=0, multi_agent_consensus_count=0),
        "LOW": dict(independent_sources_count=1, evidence_refs_verified=False,
                    counter_evidence_count=0, multi_agent_consensus_count=0),
    }
    kwargs = presets[level]
    kwargs.update(overrides)
    result = score_confidence(**kwargs)
    assert result["level"] == level, f"preset drifted from inference.py's real formula: {result}"
    return result


# --- Task-specified scenarios ------------------------------------------------

def test_pass_plus_high_confidence_is_qualified():
    qc = build_qualified_conclusion("PASS", _confidence("HIGH"), _EXECUTION_EVIDENCE)
    assert isinstance(qc, QualifiedConclusion)
    assert qc.is_qualified is True
    assert qc.gate_verdict == "PASS"
    assert qc.inference_confidence["level"] == "HIGH"
    assert qc.hypothesis == _EXECUTION_EVIDENCE["root_cause"]
    assert qc.evidence_refs, "supporting_evidence citations must be carried through"


def test_gate_fail_is_not_qualified_regardless_of_confidence():
    # Even the best possible confidence (HIGH) must not qualify a conclusion
    # whose own gate verdict is GATE_FAIL -- internally-inconsistent evidence
    # is a precondition for trusting the confidence number at all.
    qc = build_qualified_conclusion("GATE_FAIL", _confidence("HIGH"), _EXECUTION_EVIDENCE)
    assert qc.is_qualified is False
    assert qc.gate_verdict == "GATE_FAIL"
    assert qc.inference_confidence["level"] == "HIGH"


def test_pass_plus_low_confidence_is_not_qualified():
    qc = build_qualified_conclusion("PASS", _confidence("LOW"), _EXECUTION_EVIDENCE)
    assert qc.is_qualified is False
    assert qc.gate_verdict == "PASS"
    assert qc.inference_confidence["level"] == "LOW"


# --- Boundary coverage over the full verdict/level cross product -----------

@pytest.mark.parametrize("verdict", list(QUALIFYING_GATE_VERDICTS))
@pytest.mark.parametrize("level", ["HIGH", "MEDIUM"])
def test_qualifying_verdict_with_non_low_confidence_is_always_qualified(verdict, level):
    qc = build_qualified_conclusion(verdict, _confidence(level), _EXECUTION_EVIDENCE)
    assert qc.is_qualified is True


@pytest.mark.parametrize("verdict", list(QUALIFYING_GATE_VERDICTS))
def test_qualifying_verdict_with_low_confidence_is_not_qualified(verdict):
    qc = build_qualified_conclusion(verdict, _confidence("LOW"), _EXECUTION_EVIDENCE)
    assert qc.is_qualified is False


@pytest.mark.parametrize("verdict", [
    "MISSING_EVIDENCE", "NEEDS_USER_INPUT", "DV_REVIEW_PENDING", "GATE_FAIL",
])
@pytest.mark.parametrize("level", ["HIGH", "MEDIUM", "LOW"])
def test_non_qualifying_verdict_is_never_qualified(verdict, level):
    qc = build_qualified_conclusion(verdict, _confidence(level), _EXECUTION_EVIDENCE)
    assert qc.is_qualified is False


# --- Field composition -------------------------------------------------------

def test_hypothesis_falls_back_to_hypothesis_field_when_no_root_cause():
    qc = build_qualified_conclusion("PASS", _confidence("HIGH"), {"hypothesis": "alt claim"})
    assert qc.hypothesis == "alt claim"


def test_execution_result_carries_the_full_evidence_block_verbatim():
    qc = build_qualified_conclusion("PASS", _confidence("HIGH"), _EXECUTION_EVIDENCE)
    assert qc.execution_result == _EXECUTION_EVIDENCE
    # Must be a copy, not the same object -- caller's dict is never mutated
    # or aliased into the returned dataclass.
    assert qc.execution_result is not _EXECUTION_EVIDENCE


def test_as_dict_is_json_serializable_asdict_form():
    import json
    qc = build_qualified_conclusion("PASS", _confidence("HIGH"), _EXECUTION_EVIDENCE)
    d = qc.as_dict()
    assert d["is_qualified"] is True
    assert d["gate_verdict"] == "PASS"
    json.dumps(d)  # must not raise


def test_evidence_refs_normalizes_dict_and_scalar_shapes():
    qc = build_qualified_conclusion("PASS", _confidence("HIGH"), {
        "root_cause": "x",
        "supporting_evidence": {"a": "cite1", "b": "cite2"},
        "causal_chain": "single scalar chain note",
    })
    assert set(qc.evidence_refs) == {"cite1", "cite2", "single scalar chain note"}


def test_empty_execution_evidence_yields_empty_hypothesis_and_refs():
    qc = build_qualified_conclusion("PASS", _confidence("HIGH"), {})
    assert qc.hypothesis == ""
    assert qc.evidence_refs == []
    assert qc.is_qualified is True  # gate/confidence alone still drive qualification


# --- Error paths: malformed caller input, never a silent wrong answer ------

def test_unknown_gate_verdict_raises_typed_error():
    with pytest.raises(InvalidGateVerdictError) as exc_info:
        build_qualified_conclusion("TOTALLY_MADE_UP", _confidence("HIGH"), _EXECUTION_EVIDENCE)
    assert exc_info.value.reason == "UNKNOWN_GATE_VERDICT"
    assert exc_info.value.detail["gate_result"] == "TOTALLY_MADE_UP"


def test_malformed_confidence_result_raises_typed_error():
    with pytest.raises(InvalidConfidenceResultError) as exc_info:
        build_qualified_conclusion("PASS", {"level": "SUPER_HIGH"}, _EXECUTION_EVIDENCE)
    assert exc_info.value.reason == "MALFORMED_CONFIDENCE_RESULT"


def test_non_dict_confidence_result_raises_typed_error():
    with pytest.raises(InvalidConfidenceResultError):
        build_qualified_conclusion("PASS", "HIGH", _EXECUTION_EVIDENCE)


def test_non_dict_execution_evidence_raises_typed_error():
    with pytest.raises(InvalidExecutionEvidenceError) as exc_info:
        build_qualified_conclusion("PASS", _confidence("HIGH"), ["not", "a", "dict"])
    assert exc_info.value.reason == "EXECUTION_EVIDENCE_NOT_A_DICT"


# --- Real engine.py wiring: the composed object actually gets persisted ----

def _fresh_harness():
    tmp = Path(tempfile.mkdtemp())
    return tmp, DVHarness(tmp)


def test_engine_persists_qualified_conclusion_on_real_pass_high_confidence():
    # Mirrors test_inference_engine_wiring.py's direct-call style (no
    # subprocess gate execution needed -- _score_root_cause_confidence only
    # consumes the already-extracted evidence_blocks dict). Default verdict
    # argument is "PASS", the only value the one real call site in
    # run_stage() ever uses today.
    tmp, h = _fresh_harness()
    try:
        h.set_stage("RE_AUDIT")
        evidence_blocks = {"root_cause_evidence_gate": {**_EXECUTION_EVIDENCE, "hypotheses": [
                {"claim": _EXECUTION_EVIDENCE["root_cause"], "counter_evidence": []},
                {"claim": "alt 1", "counter_evidence": ["ruled out via command.txt"]},
                {"claim": "alt 2", "counter_evidence": ["ruled out via VIP trace"]},
            ]}}
        h._score_root_cause_confidence("RE_AUDIT", evidence_blocks)

        bb = h.blackboard.read("qualified_conclusion")
        assert bb is not None, "engine must persist a real qualified_conclusion Blackboard record"
        value = bb["value"]
        assert value["gate_verdict"] == "PASS"
        assert value["inference_confidence"]["level"] == "HIGH"
        assert value["is_qualified"] is True
        assert value["hypothesis"] == _EXECUTION_EVIDENCE["root_cause"]

        events = (tmp / ".dv-harness" / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
        import json as _json
        built = [_json.loads(e) for e in events if _json.loads(e).get("event") == "QUALIFIED_CONCLUSION_BUILT"]
        assert built and built[0]["is_qualified"] is True
    finally:
        shutil.rmtree(tmp)


def test_engine_persists_ai_opinion_label_data_on_low_confidence():
    # A sparse finding (same shape test_inference_engine_wiring.py's
    # LOW-confidence test uses) recomputes to LOW -- the engine must still
    # persist a QualifiedConclusion, just with is_qualified False (the "AI
    # Opinion" case dashboard.py renders distinctly).
    tmp, h = _fresh_harness()
    try:
        h.set_stage("RE_AUDIT")
        evidence_blocks = {
            "root_cause_evidence_gate": {
                "symptom": "s", "first_bad_event": {}, "causal_chain": [],
                "root_cause": "unclear", "supporting_evidence": ["one weak citation"],
                "counter_evidence": [],
            }
        }
        h._score_root_cause_confidence("RE_AUDIT", evidence_blocks)

        bb = h.blackboard.read("qualified_conclusion")
        assert bb is not None
        value = bb["value"]
        assert value["inference_confidence"]["level"] == "LOW"
        assert value["is_qualified"] is False
        assert value["gate_verdict"] == "PASS"
    finally:
        shutil.rmtree(tmp)


def test_engine_does_not_persist_qualified_conclusion_when_no_root_cause_block():
    # Same backward-compatible no-op contract as root_cause_confidence's own
    # equivalent test in test_inference_engine_wiring.py: no root_cause_
    # evidence_gate block means _score_root_cause_confidence returns before
    # ever reaching the QualifiedConclusion composition.
    tmp, h = _fresh_harness()
    try:
        h._score_root_cause_confidence("RE_AUDIT", {})
        assert h.blackboard.read("qualified_conclusion") is None
    finally:
        shutil.rmtree(tmp)


def test_engine_would_mark_gate_fail_verdict_as_not_qualified_via_explicit_verdict_arg():
    # The one real call site only ever invokes this method on a gate-verified
    # PASS (see run_stage()'s `if verdict == "PASS":` guard), but the method
    # itself takes `verdict` as an explicit parameter precisely so it stays
    # correct under a hypothetical future non-PASS caller -- proven directly
    # here rather than only trusted by inspection.
    tmp, h = _fresh_harness()
    try:
        h.set_stage("RE_AUDIT")
        evidence_blocks = {"root_cause_evidence_gate": {**_EXECUTION_EVIDENCE, "hypotheses": [
                {"claim": _EXECUTION_EVIDENCE["root_cause"], "counter_evidence": []},
                {"claim": "alt 1", "counter_evidence": ["ruled out via command.txt"]},
                {"claim": "alt 2", "counter_evidence": ["ruled out via VIP trace"]},
            ]}}
        h._score_root_cause_confidence("RE_AUDIT", evidence_blocks, verdict="GATE_FAIL")

        bb = h.blackboard.read("qualified_conclusion")
        assert bb is not None
        value = bb["value"]
        # Confidence still recomputes HIGH from the same real citations...
        assert value["inference_confidence"]["level"] == "HIGH"
        # ...but GATE_FAIL disqualifies it regardless.
        assert value["gate_verdict"] == "GATE_FAIL"
        assert value["is_qualified"] is False
    finally:
        shutil.rmtree(tmp)
