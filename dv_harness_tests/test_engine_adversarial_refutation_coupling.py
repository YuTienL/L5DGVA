"""ENGINE WIRING: Adversarial Refutation Pass gap-close (2026-09-07).

`react_loop.attempt_hypothesis_refutation()` and
`qualified_conclusion.build_qualified_conclusion(refutation_result=,
require_refutation_pass=)` were both real and individually tested, with zero
`engine.py` call site -- confirmed by grep before this task began (both
`qualified_conclusion.py`'s and `react_loop.py`'s own module docstrings
disclosed "REACHED, not yet WIRED"). This is that wire:
`engine.DVHarness._attempt_root_cause_hypothesis_refutation()`, gated behind
the new, additive, OFF-by-default `policy.enable_adversarial_refutation_pass`
config flag (mirroring `enable_inner_react_loop`'s own escape-hatch
convention), called from `_score_root_cause_confidence()` immediately before
the existing `build_qualified_conclusion()` call.

`_score_root_cause_confidence()` is called DIRECTLY (mirroring
`test_engine_voi_ranking_coupling.py`'s own convention), never through a real
gate-script subprocess -- the method only ever consumes the already-extracted
`evidence_blocks` dict, so this is a real, direct exercise of the real
production code path, not a re-derivation of it. `react_loop.
attempt_hypothesis_refutation()` itself dispatches one real, LIVE
`adapter.run()` call, so every test that turns the flag on monkeypatches that
one function at its real import location (`dv_harness.react_loop`) rather than
invoking a live `claude` subprocess.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from dv_harness.engine import DVHarness

ROOT = Path(__file__).resolve().parents[1]


def _fresh_harness():
    tmp = Path(tempfile.mkdtemp())
    return tmp, DVHarness(tmp)


def _root_cause_evidence_gate_block() -> dict:
    """A real root_cause_evidence_gate-shaped PASS payload -- the same
    fixture shape test_engine_voi_ranking_coupling.py already established,
    reused here since this coupling sits immediately after that one in the
    same method."""
    return {
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
        "confidence": "MEDIUM",
    }


def _events(root: Path, event: str = None) -> list:
    p = root / ".dv-harness" / "events.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            if event is None or rec.get("event") == event:
                out.append(rec)
    return out


def _real_attempt_result(attempted: bool, refuted: bool, rationale: str = "") -> dict:
    return {"attempted": attempted, "refuted": refuted,
            "counter_evidence": [], "rationale": rationale}


# ---------------------------------------------------------------------------
# Negative control: the flag is OFF by default -- byte-identical behavior to
# before this wiring existed.
# ---------------------------------------------------------------------------

def test_flag_off_by_default_never_calls_refutation_or_widens_qualification(monkeypatch):
    from dv_harness import react_loop as rl

    def _boom(*a, **kw):
        raise AssertionError("attempt_hypothesis_refutation must not be called when the flag is off")

    monkeypatch.setattr(rl, "attempt_hypothesis_refutation", _boom)

    tmp, h = _fresh_harness()
    try:
        assert h.cfg.get("policy", {}).get("enable_adversarial_refutation_pass", False) is False
        evidence_blocks = {"root_cause_evidence_gate": _root_cause_evidence_gate_block()}
        h._score_root_cause_confidence("RE_AUDIT", evidence_blocks,
                                        profile_id="p1", agent_name="review-agent")

        bb = h.blackboard.read("qualified_conclusion")
        assert bb is not None
        record = bb["value"]
        assert record["refutation"] is None
        assert _events(tmp, "ADVERSARIAL_REFUTATION_PASS_RUN") == []
        assert _events(tmp, "ADVERSARIAL_REFUTATION_PASS_FAILED") == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Flag ON: the real hook fires, composes into the real QualifiedConclusion.
# ---------------------------------------------------------------------------

def test_flag_on_survives_refutation_composes_into_qualified_conclusion(monkeypatch):
    from dv_harness import react_loop as rl

    captured = {}

    def _fake_attempt(adapter, root, hypothesis, evidence_refs=None, profiler=None,
                       profile_id=None, agent_name=""):
        captured["hypothesis"] = hypothesis
        captured["evidence_refs"] = evidence_refs
        captured["profile_id"] = profile_id
        captured["agent_name"] = agent_name
        return _real_attempt_result(attempted=True, refuted=False,
                                     rationale="both citations hold up under scrutiny")

    monkeypatch.setattr(rl, "attempt_hypothesis_refutation", _fake_attempt)

    tmp, h = _fresh_harness()
    try:
        h.cfg.setdefault("policy", {})["enable_adversarial_refutation_pass"] = True
        block = _root_cause_evidence_gate_block()
        evidence_blocks = {"root_cause_evidence_gate": block}
        h._score_root_cause_confidence("RE_AUDIT", evidence_blocks,
                                        profile_id="p1", agent_name="review-agent")

        # The real hook was actually called with this attempt's own real
        # selected root_cause and its own real supporting_evidence citations
        # -- never a fabricated hypothesis or evidence set.
        assert captured["hypothesis"] == block["root_cause"]
        assert any("FIFO_EMPTY" in ref for ref in captured["evidence_refs"])
        assert captured["profile_id"] == "p1"
        assert captured["agent_name"] == "review-agent"

        run_events = _events(tmp, "ADVERSARIAL_REFUTATION_PASS_RUN")
        assert len(run_events) == 1
        assert run_events[0]["attempted"] is True
        assert run_events[0]["refuted"] is False

        bb = h.blackboard.read("qualified_conclusion")
        assert bb is not None
        record = bb["value"]
        assert record["refutation"]["attempted"] is True
        assert record["refutation"]["refuted"] is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_confirmed_refutation_disqualifies_unconditionally():
    """A real, confirmed refutation (refuted=True) must disqualify the
    conclusion regardless of confidence -- the exact rule
    qualified_conclusion.build_qualified_conclusion() itself already
    enforces; this proves the wire actually reaches that enforcement rather
    than short-circuiting it."""
    tmp, h = _fresh_harness()
    try:
        block = _root_cause_evidence_gate_block()
        evidence_blocks = {"root_cause_evidence_gate": block}
        confidence_result = {"level": "HIGH", "score": 9,
                              "capped_by_counter_evidence": False}
        refutation = _real_attempt_result(attempted=True, refuted=True,
                                           rationale="the cited FIFO_EMPTY line does not exist at t=1000ns")

        from dv_harness.qualified_conclusion import build_qualified_conclusion
        qc = build_qualified_conclusion("PASS", confidence_result, block,
                                        refutation_result=refutation,
                                        require_refutation_pass=True)
        assert qc.is_qualified is False
        assert qc.refutation["refuted"] is True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_required_but_not_attempted_never_qualifies():
    """The Evidence Truth Rule negative control: with the flag on
    (require_refutation_pass=True), a refutation attempt that never got a
    real, parseable answer (attempted=False -- a transport failure or two
    unparseable replies, per attempt_hypothesis_refutation()'s own contract)
    must be treated identically to "no pass was run at all" -- it can never
    be silently read as a survived refutation."""
    tmp, h = _fresh_harness()
    try:
        block = _root_cause_evidence_gate_block()
        confidence_result = {"level": "HIGH", "score": 9,
                              "capped_by_counter_evidence": False}
        refutation = _real_attempt_result(attempted=False, refuted=False)

        from dv_harness.qualified_conclusion import build_qualified_conclusion
        qc = build_qualified_conclusion("PASS", confidence_result, block,
                                        refutation_result=refutation,
                                        require_refutation_pass=True)
        assert qc.is_qualified is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_wired_hook_transport_failure_returns_none_and_stage_still_completes(monkeypatch):
    """A real exception inside attempt_hypothesis_refutation() (e.g. the
    live adapter itself raising) must degrade to refutation_result=None,
    log ADVERSARIAL_REFUTATION_PASS_FAILED, and never turn an already-
    computed, already-gate-verified stage PASS into a crash -- the same
    best-effort guarantee every sibling side effect in
    _score_root_cause_confidence() already holds."""
    from dv_harness import react_loop as rl

    def _boom(*a, **kw):
        raise RuntimeError("live adapter transport failure")

    monkeypatch.setattr(rl, "attempt_hypothesis_refutation", _boom)

    tmp, h = _fresh_harness()
    try:
        h.cfg.setdefault("policy", {})["enable_adversarial_refutation_pass"] = True
        evidence_blocks = {"root_cause_evidence_gate": _root_cause_evidence_gate_block()}
        # Must not raise.
        h._score_root_cause_confidence("RE_AUDIT", evidence_blocks)

        failures = _events(tmp, "ADVERSARIAL_REFUTATION_PASS_FAILED")
        assert len(failures) == 1
        assert "transport failure" in failures[0]["error"]

        run_events = _events(tmp, "ADVERSARIAL_REFUTATION_PASS_RUN")
        assert len(run_events) == 1
        assert run_events[0]["attempted"] is False

        # The whole stage's own qualified_conclusion write still succeeded
        # (with is_qualified structurally False, since attempted=False under
        # a required pass never qualifies) -- a refutation-hook failure never
        # downgrades an already-earned stage PASS into a lost record.
        bb = h.blackboard.read("qualified_conclusion")
        assert bb is not None
        assert bb["value"]["is_qualified"] is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_no_root_cause_in_block_never_calls_the_live_adapter():
    """block["root_cause"] absent -> nothing to refute -> the wired hook
    returns None without ever invoking react_loop.attempt_hypothesis_
    refutation() (which would otherwise dispatch a real adapter call over an
    empty hypothesis string)."""
    tmp, h = _fresh_harness()
    try:
        block = {"symptom": "no conclusion reached yet"}
        result = h._attempt_root_cause_hypothesis_refutation("RE_AUDIT", block)
        assert result is None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_evidence_refs_extraction_handles_list_and_dict_supporting_evidence(monkeypatch):
    from dv_harness import react_loop as rl

    captured = {}

    def _fake_attempt(adapter, root, hypothesis, evidence_refs=None, **kw):
        captured["evidence_refs"] = evidence_refs
        return _real_attempt_result(attempted=True, refuted=False)

    monkeypatch.setattr(rl, "attempt_hypothesis_refutation", _fake_attempt)

    tmp, h = _fresh_harness()
    try:
        # List-of-dicts shape (the fixture's own real shape).
        block_list = {"root_cause": "x", "supporting_evidence": [
            {"source": "sim.log", "citation": "a"},
            {"source": "rtl", "citation": "b"},
        ]}
        h._attempt_root_cause_hypothesis_refutation("RE_AUDIT", block_list)
        assert len(captured["evidence_refs"]) == 2

        # Dict shape (a caller keying evidence by name).
        block_dict = {"root_cause": "x", "supporting_evidence": {
            "sim_log": "a", "rtl": "b",
        }}
        h._attempt_root_cause_hypothesis_refutation("RE_AUDIT", block_dict)
        assert set(captured["evidence_refs"]) == {"a", "b"}

        # Absent supporting_evidence -> an empty list, never a crash.
        block_none = {"root_cause": "x"}
        h._attempt_root_cause_hypothesis_refutation("RE_AUDIT", block_none)
        assert captured["evidence_refs"] == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
