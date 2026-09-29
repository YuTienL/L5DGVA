"""Real-subprocess tests for
tools/verification_flow/spec_to_vplan_quality_gate.py.

Discipline: ONE clean, fully-covered spec/vplan evidence set is asserted to
PASS with zero findings, then every one of the four rules is driven by
MUTATING that same clean payload one defect at a time -- so each assertion
proves that rule caught that specific injected defect -- exactly the pattern
`test_requirement_contract.py` and `test_uvm_structural_lint.py` already use
in this repo. The gate is driven as a REAL subprocess against a REAL file on
disk, matching `test_requirement_contract.py`'s own `run_gate()` helper.
"""
import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "tools" / "verification_flow" / "spec_to_vplan_quality_gate.py"


def clean_payload():
    """Fully covered, internally coherent evidence. Synthetic -- describes
    no real spec/DUT; it exists to be mutated."""
    return {
        "spec_items": [
            {"spec_id": "SPEC-1", "criticality": "P0", "text": "device shall ack within 2 cycles"},
            {"spec_id": "SPEC-2", "criticality": "P2", "text": "device may report status via debug port"},
        ],
        "vplan_items": [
            {"vplan_id": "VP-1", "traces_to": ["SPEC-1"]},
            {"vplan_id": "VP-2", "traces_to": ["SPEC-2"]},
        ],
        "contradictions": [
            {"contradiction_id": "C1", "description": "spec section 3 vs section 9 disagree on reset polarity",
             "resolved": True, "resolution": "section 9 supersedes per errata"},
        ],
        "ambiguities": [
            {"ambiguity_id": "A1", "description": "\"promptly\" is not a cycle count",
             "resolved": False, "open_question": "Q-104"},
        ],
    }


def run_gate(payload, tmp_path):
    p = tmp_path / "vplan_quality.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(GATE), "--vplan-quality", str(p)],
        capture_output=True, text=True, cwd=str(ROOT),
    )


def out(result):
    return json.loads(result.stdout)


# --------------------------------------------------------------------------
# Positive path
# --------------------------------------------------------------------------

def test_clean_payload_passes_with_zero_findings(tmp_path):
    r = run_gate(clean_payload(), tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    d = out(r)
    assert d["status"] == "PASS"
    assert d["spec_items"] == 2
    assert d["vplan_items"] == 2
    assert "findings" not in d


def test_ambiguity_addressed_via_resolution_text_instead_of_resolved_flag_still_passes(tmp_path):
    payload = clean_payload()
    payload["ambiguities"][0]["resolved"] = False
    payload["ambiguities"][0].pop("open_question")
    payload["ambiguities"][0]["resolution"] = "clarified as 3 cycles per errata E-12"
    r = run_gate(payload, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert out(r)["status"] == "PASS"


# --------------------------------------------------------------------------
# Negative control 1: no spec items at all
# --------------------------------------------------------------------------

def test_no_spec_items_reports_no_spec_items_not_a_false_pass(tmp_path):
    payload = clean_payload()
    payload["spec_items"] = []
    r = run_gate(payload, tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    d = out(r)
    assert d["status"] == "FAIL"
    assert d["reason"] == "NO_SPEC_ITEMS"


def test_absent_spec_items_key_entirely_also_reports_no_spec_items(tmp_path):
    payload = clean_payload()
    del payload["spec_items"]
    r = run_gate(payload, tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    assert out(r)["reason"] == "NO_SPEC_ITEMS"


# --------------------------------------------------------------------------
# Negative control 2: critical omission
# --------------------------------------------------------------------------

def test_critical_spec_item_with_no_tracing_vplan_item_is_critical_omission(tmp_path):
    payload = clean_payload()
    # SPEC-1 is P0 (critical) -- remove the only vplan item that traces to it.
    payload["vplan_items"] = [v for v in payload["vplan_items"] if v["vplan_id"] != "VP-1"]
    r = run_gate(payload, tmp_path)
    assert r.returncode == 3, r.stdout + r.stderr
    d = out(r)
    assert d["status"] == "FAIL"
    assert d["reason"] == "CRITICAL_OMISSION"
    ids = {f["spec_id"] for f in d["findings"]["critical_omission"]}
    assert ids == {"SPEC-1"}


def test_noncritical_uncovered_spec_item_is_traceability_gap_not_critical_omission(tmp_path):
    payload = clean_payload()
    # SPEC-2 is P2 (non-critical) -- remove its only trace.
    payload["vplan_items"] = [v for v in payload["vplan_items"] if v["vplan_id"] != "VP-2"]
    r = run_gate(payload, tmp_path)
    assert r.returncode == 6, r.stdout + r.stderr
    d = out(r)
    assert d["reason"] == "TRACEABILITY_GAP"
    assert "critical_omission" not in d["findings"]
    specs = {f.get("spec_id") for f in d["findings"]["traceability_gap"] if "spec_id" in f}
    assert "SPEC-2" in specs


# --------------------------------------------------------------------------
# Negative control 3: unresolved contradiction
# --------------------------------------------------------------------------

def test_contradiction_filed_and_never_closed_is_unresolved_contradiction(tmp_path):
    payload = clean_payload()
    payload["contradictions"][0]["resolved"] = False
    payload["contradictions"][0].pop("resolution")
    r = run_gate(payload, tmp_path)
    assert r.returncode == 4, r.stdout + r.stderr
    d = out(r)
    assert d["reason"] == "UNRESOLVED_CONTRADICTION"
    ids = {f["contradiction_id"] for f in d["findings"]["unresolved_contradiction"]}
    assert ids == {"C1"}


def test_contradiction_with_open_question_on_file_is_not_unresolved(tmp_path):
    payload = clean_payload()
    payload["contradictions"][0]["resolved"] = False
    payload["contradictions"][0].pop("resolution")
    payload["contradictions"][0]["open_question"] = "Q-201"
    r = run_gate(payload, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert out(r)["status"] == "PASS"


# --------------------------------------------------------------------------
# Negative control 4: unresolved ambiguity
# --------------------------------------------------------------------------

def test_ambiguity_filed_and_never_closed_is_unresolved_ambiguity(tmp_path):
    payload = clean_payload()
    payload["ambiguities"][0]["open_question"] = None
    r = run_gate(payload, tmp_path)
    assert r.returncode == 5, r.stdout + r.stderr
    d = out(r)
    assert d["reason"] == "UNRESOLVED_AMBIGUITY"
    ids = {f["ambiguity_id"] for f in d["findings"]["unresolved_ambiguity"]}
    assert ids == {"A1"}


# --------------------------------------------------------------------------
# Negative control 5: traceability gap (orphan vplan item / dangling trace)
# --------------------------------------------------------------------------

def test_vplan_item_with_no_trace_at_all_is_traceability_gap(tmp_path):
    payload = clean_payload()
    payload["vplan_items"].append({"vplan_id": "VP-99", "traces_to": []})
    r = run_gate(payload, tmp_path)
    assert r.returncode == 6, r.stdout + r.stderr
    d = out(r)
    assert d["reason"] == "TRACEABILITY_GAP"
    reasons = {f.get("reason") for f in d["findings"]["traceability_gap"]}
    assert "VPLAN_ITEM_NOT_TRACED_TO_SPEC" in reasons
    vids = {f.get("vplan_id") for f in d["findings"]["traceability_gap"]}
    assert "VP-99" in vids


def test_vplan_item_tracing_to_a_spec_id_never_supplied_is_dangling_reference(tmp_path):
    payload = clean_payload()
    payload["vplan_items"].append({"vplan_id": "VP-100", "traces_to": ["SPEC-999"]})
    r = run_gate(payload, tmp_path)
    assert r.returncode == 6, r.stdout + r.stderr
    d = out(r)
    assert d["reason"] == "TRACEABILITY_GAP"
    dangling = [f for f in d["findings"]["traceability_gap"] if f.get("dangling_spec_ref")]
    assert any(f["vplan_id"] == "VP-100" and f["dangling_spec_ref"] == "SPEC-999" for f in dangling)
    reasons = {f.get("reason") for f in dangling}
    assert reasons == {"VPLAN_TRACE_TARGETS_UNKNOWN_SPEC_ID"}


# --------------------------------------------------------------------------
# Priority ordering: several defects at once report the most severe first,
# but every kind is still visible in `findings`.
# --------------------------------------------------------------------------

def test_multiple_simultaneous_defects_report_most_severe_reason_but_all_findings(tmp_path):
    payload = clean_payload()
    # critical omission
    payload["vplan_items"] = [v for v in payload["vplan_items"] if v["vplan_id"] != "VP-1"]
    # unresolved contradiction
    payload["contradictions"][0]["resolved"] = False
    payload["contradictions"][0].pop("resolution")
    # unresolved ambiguity
    payload["ambiguities"][0]["open_question"] = None
    # traceability gap: dangling reference
    payload["vplan_items"].append({"vplan_id": "VP-101", "traces_to": ["SPEC-NOPE"]})

    r = run_gate(payload, tmp_path)
    assert r.returncode == 3, r.stdout + r.stderr  # CRITICAL_OMISSION is most severe
    d = out(r)
    assert d["reason"] == "CRITICAL_OMISSION"
    assert set(d["findings"].keys()) == {
        "critical_omission", "unresolved_contradiction",
        "unresolved_ambiguity", "traceability_gap",
    }


# --------------------------------------------------------------------------
# Malformed entries are skipped gracefully, never crash the gate.
# --------------------------------------------------------------------------

def test_non_dict_entries_in_lists_are_skipped_without_crashing(tmp_path):
    payload = clean_payload()
    payload["vplan_items"].append("not-a-dict")
    payload["contradictions"].append(None)
    payload["ambiguities"].append(42)
    r = run_gate(payload, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert out(r)["status"] == "PASS"


def test_output_is_deterministic_json_for_the_same_input(tmp_path):
    payload = clean_payload()
    r1 = run_gate(payload, tmp_path)
    r2 = run_gate(copy.deepcopy(payload), tmp_path)
    assert r1.stdout == r2.stdout
    assert r1.returncode == r2.returncode == 0
