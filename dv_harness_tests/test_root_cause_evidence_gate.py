"""Tests for tools/verification_flow/root_cause_evidence_gate.py's optional
`evidence_refs` freshness check (2026-09-02, second remaining audit gap: the
gate's supporting_evidence/counter_evidence fields were free-text citation
strings with no freshness check -- an agent could paste a plausible-looking
but stale/remembered string and still PASS).

`evidence_refs` reuses manual_lookup_before_edit_gate.py's own
_verify_evidence_refs() (an array of {"path": ..., "quote": ...} objects,
independently verified against the REAL current file on disk) rather than
inventing a second, parallel mechanism -- see the gate script's own module
header for the full rationale, including why no --root ContextFlag is
needed (gates.run_gate() already runs every gate subprocess with
cwd=<real project root>, exactly like manual_lookup_before_edit_gate.py's
own no-ContextFlag design)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "verification_flow" / "root_cause_evidence_gate.py"

# A real, stable file+quote pair already used the same way by
# test_engine_gates_and_routing.py's own manual_lookup_before_edit_gate
# evidence_refs tests -- path is relative to the real project root, matching
# run_gate()'s real subprocess cwd convention.
_REAL_REF = {"path": "CLAUDE.md", "quote": "Evidence Truth Rule"}


def _run_gate(root_cause: dict):
    tmp = Path(tempfile.mkdtemp())
    try:
        infile = tmp / "root_cause.json"
        infile.write_text(json.dumps(root_cause), encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--root-cause", str(infile)],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT),
        )
        out = json.loads((r.stdout or "").strip() or "{}")
        return r.returncode, out
    finally:
        import shutil
        shutil.rmtree(tmp)


def _hypotheses(selected_claim: str, extra=None):
    hyps = [
        {"claim": selected_claim, "category": "DUT_BUG",
         "supporting_evidence": ["sim.log:4021"], "counter_evidence": [],
         "missing_evidence": [], "confidence": "MEDIUM", "next_action": "confirm with waveform"},
        {"claim": "alt: TB-side malformed request", "category": "TB_BUG",
         "supporting_evidence": ["seq_lib review"],
         "counter_evidence": ["command.txt shows well-formed request"],
         "missing_evidence": [], "confidence": "LOW", "next_action": "n/a -- ruled out"},
    ]
    if extra:
        hyps[0].update(extra)
    return hyps


def _base_root_cause(**overrides):
    selected_claim = "ep0 FIFO underrun due to missing prefetch on GET_DESCRIPTOR"
    d = {
        "symptom": "USB descriptor read timeout observed in regression run r42",
        "first_bad_event": {"time_ns": 1000},
        "causal_chain": [{"time_ns": 900, "event": "a"}, {"time_ns": 1000, "event": "b"}],
        "root_cause": selected_claim,
        "supporting_evidence": ["sim.log:4021: FIFO_EMPTY at t=1000ns"],
        "counter_evidence": [],
        "confidence": "MEDIUM",
        "hypotheses": _hypotheses(selected_claim, overrides.pop("hyp0_extra", None)),
    }
    d.update(overrides)
    return d


def test_pass_legacy_free_text_only_backward_compat():
    # No evidence_refs anywhere -- must PASS exactly like before this
    # change, proving old callers that never adopted evidence_refs keep
    # working (the weaker/legacy free-text-only fallback).
    rc, out = _run_gate(_base_root_cause())
    assert rc == 0 and out["status"] == "PASS"


def test_pass_top_level_evidence_refs_real_match():
    rc, out = _run_gate(_base_root_cause(evidence_refs=[_REAL_REF]))
    assert rc == 0 and out["status"] == "PASS"


def test_fail_top_level_evidence_refs_nonexistent_path():
    rc, out = _run_gate(_base_root_cause(
        evidence_refs=[{"path": "no_such_file_anywhere.sv", "quote": "x"}]))
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "EVIDENCE_FILE_NOT_FOUND"
    assert out["field"] == "evidence_refs"


def test_fail_top_level_evidence_refs_wrong_quote():
    rc, out = _run_gate(_base_root_cause(
        evidence_refs=[{"path": "CLAUDE.md", "quote": "this exact sentence does not exist in CLAUDE.md"}]))
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "EVIDENCE_QUOTE_NOT_FOUND_IN_FILE"
    assert out["path"] == "CLAUDE.md"


def test_pass_hypothesis_level_evidence_refs_real_match():
    rc, out = _run_gate(_base_root_cause(hyp0_extra={"evidence_refs": [_REAL_REF]}))
    assert rc == 0 and out["status"] == "PASS"


def test_fail_hypothesis_level_evidence_refs_wrong_quote():
    rc, out = _run_gate(_base_root_cause(hyp0_extra={
        "evidence_refs": [{"path": "CLAUDE.md", "quote": "fabricated text never in this file"}],
    }))
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "EVIDENCE_QUOTE_NOT_FOUND_IN_FILE"
    assert out["index"] == 0
    assert out["field"] == "hypotheses[0].evidence_refs"


def test_fail_hypothesis_level_evidence_refs_nonexistent_path():
    rc, out = _run_gate(_base_root_cause(hyp0_extra={
        "evidence_refs": [{"path": "definitely_not_a_real_file.sv", "quote": "x"}],
    }))
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "EVIDENCE_FILE_NOT_FOUND"
    assert out["index"] == 0


def test_evidence_refs_never_bypasses_no_supporting_evidence_check():
    # A real, verifiable evidence_refs entry must not let an empty free-text
    # supporting_evidence field slide through -- the base completeness check
    # is still mandatory and must fire BEFORE evidence_refs is even looked at.
    d = _base_root_cause(evidence_refs=[_REAL_REF])
    d["supporting_evidence"] = []
    rc, out = _run_gate(d)
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "NO_SUPPORTING_EVIDENCE"


def test_evidence_refs_never_bypasses_insufficient_hypotheses_check():
    # A real, verifiable top-level evidence_refs entry must not let a
    # non-trivial finding skip the >=2-hypotheses structural requirement --
    # evidence_refs is an additive citation-freshness check, never a
    # replacement for the existing hypothesis-count/refutation checks.
    d = _base_root_cause(evidence_refs=[_REAL_REF])
    d["hypotheses"] = d["hypotheses"][:1]  # drop the refuted alternative
    rc, out = _run_gate(d)
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "INSUFFICIENT_HYPOTHESES"


def test_evidence_refs_never_bypasses_no_alternative_hypothesis_refuted_check():
    d = _base_root_cause(evidence_refs=[_REAL_REF])
    for h in d["hypotheses"]:
        if h["claim"] != d["root_cause"]:
            h["counter_evidence"] = []  # no longer refuted
    rc, out = _run_gate(d)
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "NO_ALTERNATIVE_HYPOTHESIS_REFUTED"


def test_reference_tree_citation_forbidden_still_applies_to_evidence_refs():
    # Same forbidden-reference-tree barrier manual_lookup_before_edit_gate.py
    # already enforces (reused here via the shared _verify_evidence_refs) --
    # a confident citation into USB_UVM_Handoff must FAIL even though the
    # citation format itself is otherwise well-formed.
    rc, out = _run_gate(_base_root_cause(
        evidence_refs=[{"path": "USB_UVM_Handoff/some_file.sv", "quote": "x"}]))
    assert rc != 0 and out["status"] == "FAIL"
    assert out["reason"] == "REFERENCE_TREE_CITATION_FORBIDDEN"
