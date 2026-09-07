"""ENGINE WIRING: inference.rank_evidence_by_information_value() gap-close
(2026-09-07 Implement-phase, Task 3 of the Confidence/Inference-Layer audit).

`rank_evidence_by_information_value()` was real and individually tested, with
no engine call site. This is that wire:
`engine.DVHarness._root_cause_hypotheses_voi_ranking()`, called from
`_score_root_cause_confidence()` immediately after the existing
`root_cause_confidence` Blackboard write / `ROOT_CAUSE_CONFIDENCE_SCORED`
event pair -- sitting strictly downstream of the recomputed confidence_result
and gap, never feeding back into either.

`_score_root_cause_confidence()` is called DIRECTLY (mirroring
`test_inference_engine_wiring.py`'s own
`test_low_confidence_finding_never_calls_promote_and_reports_larger_gap()`),
never through a real gate-script subprocess -- the method only ever consumes
the already-extracted `evidence_blocks` dict, so this is a real, direct
exercise of the real production code path, not a re-derivation of it.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from dv_harness.engine import DVHarness

ROOT = Path(__file__).resolve().parents[1]


def _fresh_harness():
    tmp = Path(tempfile.mkdtemp())
    return tmp, DVHarness(tmp)


def _root_cause_evidence_gate_block() -> dict:
    """A real root_cause_evidence_gate-shaped PASS payload: 3 hypotheses,
    the selected one (hypotheses[0]) matching block["root_cause"], the other
    two independently refuted -- the same real shape
    root_cause_evidence_gate.py itself requires
    (NO_ALTERNATIVE_HYPOTHESIS_REFUTED)."""
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


def test_a_real_hypotheses_array_produces_a_real_voi_ranking():
    tmp, h = _fresh_harness()
    try:
        evidence_blocks = {"root_cause_evidence_gate": _root_cause_evidence_gate_block()}
        h._score_root_cause_confidence("RE_AUDIT", evidence_blocks)

        bb = h.blackboard.read("root_cause_evidence_voi_ranking")
        assert bb is not None
        ranking = bb["value"]
        assert ranking["hypothesis_count"] == 3
        # counter_evidence is missing (empty) only for the selected
        # hypothesis, and present for both alternatives -> a real,
        # discriminating category the ranking should surface.
        categories = {r["category"] for r in ranking["ranked"]}
        assert "counter_evidence" in categories

        events = [e for e in _events(tmp) if e.get("event") == "ROOT_CAUSE_EVIDENCE_VOI_RANKED"]
        assert len(events) == 1
        assert events[0]["hypothesis_count"] == 3
        assert events[0]["ranked_category_count"] == len(ranking["ranked"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_no_hypotheses_field_is_a_real_no_op():
    """block["hypotheses"] absent -> nothing to rank -> no Blackboard write,
    no event -- the existing root_cause_confidence topic/event are
    completely unaffected."""
    tmp, h = _fresh_harness()
    try:
        block = _root_cause_evidence_gate_block()
        del block["hypotheses"]
        evidence_blocks = {"root_cause_evidence_gate": block}
        h._score_root_cause_confidence("RE_AUDIT", evidence_blocks)

        assert h.blackboard.read("root_cause_evidence_voi_ranking") is None
        assert h.blackboard.read("root_cause_confidence") is not None
        assert _events(tmp, "ROOT_CAUSE_EVIDENCE_VOI_RANKED") == []
        assert _events(tmp, "ROOT_CAUSE_CONFIDENCE_SCORED") != []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_empty_hypotheses_list_is_also_a_real_no_op():
    tmp, h = _fresh_harness()
    try:
        block = _root_cause_evidence_gate_block()
        block["hypotheses"] = []
        evidence_blocks = {"root_cause_evidence_gate": block}
        h._score_root_cause_confidence("RE_AUDIT", evidence_blocks)

        assert h.blackboard.read("root_cause_evidence_voi_ranking") is None
        assert _events(tmp, "ROOT_CAUSE_EVIDENCE_VOI_RANKED") == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_bad_hypotheses_shape_is_best_effort_and_never_breaks_the_stage(monkeypatch):
    from dv_harness import inference as inf

    tmp, h = _fresh_harness()
    try:
        def _boom(hypotheses):
            raise RuntimeError("adapter produced a malformed shape")

        monkeypatch.setattr(inf, "rank_evidence_by_information_value", _boom)
        evidence_blocks = {"root_cause_evidence_gate": _root_cause_evidence_gate_block()}
        # Must not raise -- best-effort, the same guarantee every sibling
        # side effect in _score_root_cause_confidence() already holds.
        h._score_root_cause_confidence("RE_AUDIT", evidence_blocks)

        assert h.blackboard.read("root_cause_evidence_voi_ranking") is None
        # The existing, unrelated root_cause_confidence write must still
        # have succeeded -- a VOI-ranking failure must never downgrade an
        # already-computed confidence score.
        assert h.blackboard.read("root_cause_confidence") is not None
        failures = _events(tmp, "ROOT_CAUSE_EVIDENCE_VOI_RANKING_FAILED")
        assert len(failures) == 1
        assert "malformed shape" in failures[0]["error"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_selected_hypothesis_uses_the_recomputed_level_never_the_agent_claim():
    """The selected hypothesis's own self-reported confidence is "MEDIUM",
    but the independently recomputed score_confidence() level is what must
    actually drive its urgency weight -- proven by checking the ranking
    changes when the recomputed level, not the declared one, changes."""
    tmp, h = _fresh_harness()
    try:
        block = _root_cause_evidence_gate_block()
        evidence_blocks = {"root_cause_evidence_gate": block}
        confidence_result = h._root_cause_confidence_inputs(block)
        from dv_harness.inference import score_confidence
        recomputed = score_confidence(**confidence_result)

        ranking = h._root_cause_hypotheses_voi_ranking(block, recomputed)
        assert ranking is not None
        # The selected hypothesis's own recorded level in the ranking's
        # "hypotheses_missing"/"hypotheses_applicable" bookkeeping is opaque
        # by design (rank_evidence_by_information_value() does not echo the
        # per-hypothesis level back) -- what is directly checkable here is
        # that supplying an artificially different recomputed level changes
        # the ranking, proving the recomputed value (not the hard-coded
        # "MEDIUM" the fixture's own selected hypothesis declares) is what
        # is actually threaded through.
        forced_high = dict(recomputed, level="HIGH")
        ranking_high = h._root_cause_hypotheses_voi_ranking(block, forced_high)
        forced_low = dict(recomputed, level="LOW")
        ranking_low = h._root_cause_hypotheses_voi_ranking(block, forced_low)
        assert ranking_high != ranking_low
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _events(root: Path, event: str = None) -> list:
    import json as _json
    p = root / ".dv-harness" / "events.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = _json.loads(line)
            if event is None or rec.get("event") == event:
                out.append(rec)
    return out
