"""Tests for dv_harness/programming_sequence_ir.py.

Real fixtures: small real JSON documents written to a temp directory (via
`tmp_path`), and the real CLI entry point driven as a real subprocess. No
mocks -- the module reads plain dicts/JSON files exactly as its real
`execute_verb()` front door does.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import programming_sequence_ir as psir


# ---------------------------------------------------------------------------
# helpers building a clean, real, positive-path fixture
# ---------------------------------------------------------------------------

def _clean_sequence_doc():
    return {
        "name": "usb3_link_bringup",
        "steps": [
            {"index": 0, "phase": "INIT", "action": "write",
             "register": "clk_en", "value": "0x1"},
            {"index": 1, "phase": "CONFIGURE", "action": "write",
             "register": "phy_cfg", "value": "0x3"},
            {"index": 2, "phase": "CONFIGURE", "action": "write",
             "register": "link_cfg", "value": "0x7"},
            {"index": 3, "phase": "ENABLE", "action": "write",
             "register": "link_en", "value": "0x1"},
            {"index": 4, "phase": "WAIT", "action": "wait"},
            {"index": 5, "phase": "VERIFY", "action": "read",
             "register": "link_status"},
            {"index": 6, "phase": "RESET", "action": "write",
             "register": "soft_reset", "value": "0x1"},
        ],
    }


def _clean_facts():
    return [
        {"name": "clk_en", "offset": "0x0", "access_type": "RW", "depends_on": []},
        {"name": "phy_cfg", "offset": "0x4", "access_type": "RW", "depends_on": ["clk_en"]},
        {"name": "link_cfg", "offset": "0x8", "access_type": "RW", "depends_on": ["phy_cfg"]},
        {"name": "link_en", "offset": "0xC", "access_type": "RW", "depends_on": ["link_cfg"]},
        {"name": "link_status", "offset": "0x10", "access_type": "RO", "depends_on": []},
        {"name": "soft_reset", "offset": "0x14", "access_type": "WO", "depends_on": []},
    ]


def _facts(facts_dicts):
    return psir.register_facts_from_dicts(facts_dicts)


def _ir(doc):
    return psir.programming_sequence_ir_from_dict(doc)


# ---------------------------------------------------------------------------
# positive path
# ---------------------------------------------------------------------------

def test_clean_sequence_passes_with_no_findings():
    report = psir.validate_step_ordering(_ir(_clean_sequence_doc()), _facts(_clean_facts()))
    assert report["status"] == psir.STATUS_ORDER_VALID
    assert report["findings"] == []
    assert report["step_count"] == 7
    assert report["register_fact_count"] == 6


def test_load_programming_sequence_from_real_file(tmp_path):
    p = tmp_path / "seq.json"
    p.write_text(json.dumps(_clean_sequence_doc()), encoding="utf-8")
    ir = psir.load_programming_sequence(p)
    assert ir.name == "usb3_link_bringup"
    assert len(ir.steps) == 7


# ---------------------------------------------------------------------------
# honesty: absent evidence must read as NOT_AVAILABLE / NOT_APPLICABLE,
# never a silent PASS
# ---------------------------------------------------------------------------

def test_no_register_facts_reports_not_available_not_a_false_pass():
    report = psir.validate_step_ordering(_ir(_clean_sequence_doc()), None)
    assert report["status"] == psir.STATUS_NOT_AVAILABLE
    assert "reason" in report and report["reason"]
    assert report["findings"] == []


def test_empty_register_facts_list_also_not_available():
    report = psir.validate_step_ordering(_ir(_clean_sequence_doc()), [])
    assert report["status"] == psir.STATUS_NOT_AVAILABLE


def test_zero_step_sequence_is_not_applicable():
    ir = _ir({"name": "empty_seq", "steps": []})
    report = psir.validate_step_ordering(ir, _facts(_clean_facts()))
    assert report["status"] == psir.STATUS_NOT_APPLICABLE
    assert report["step_count"] == 0


# ---------------------------------------------------------------------------
# negative controls -- each mutates the clean fixture ONE way and asserts
# the specific finding fires (mutated/broken input must NOT pass)
# ---------------------------------------------------------------------------

def test_phase_out_of_canonical_order_is_flagged():
    doc = _clean_sequence_doc()
    # Swap step 3 (ENABLE) to come back down to CONFIGURE after RESET-rank
    # step already appeared earlier -- construct a genuine regression: put
    # a CONFIGURE step after the ENABLE step.
    doc["steps"].insert(4, {"index": 4, "phase": "CONFIGURE", "action": "write",
                            "register": "link_cfg", "value": "0x0"})
    for i, s in enumerate(doc["steps"]):
        s["index"] = i
    report = psir.validate_step_ordering(_ir(doc), _facts(_clean_facts()))
    assert report["status"] == psir.STATUS_ORDER_INVALID
    codes = {f["code"] for f in report["findings"]}
    assert psir.FINDING_PHASE_ORDER_VIOLATION in codes


def test_unknown_phase_is_flagged():
    doc = _clean_sequence_doc()
    doc["steps"][1]["phase"] = "FROBNICATE"
    report = psir.validate_step_ordering(_ir(doc), _facts(_clean_facts()))
    assert report["status"] == psir.STATUS_ORDER_INVALID
    codes = {f["code"] for f in report["findings"]}
    assert psir.FINDING_UNKNOWN_PHASE in codes


def test_unknown_register_reference_is_flagged():
    doc = _clean_sequence_doc()
    doc["steps"][1]["register"] = "does_not_exist_reg"
    report = psir.validate_step_ordering(_ir(doc), _facts(_clean_facts()))
    assert report["status"] == psir.STATUS_ORDER_INVALID
    codes = {f["code"] for f in report["findings"]}
    assert psir.FINDING_UNKNOWN_REGISTER in codes


def test_write_to_read_only_register_is_flagged():
    doc = _clean_sequence_doc()
    # link_status is RO in the clean facts; write to it instead of reading.
    doc["steps"][5] = {"index": 5, "phase": "VERIFY", "action": "write",
                        "register": "link_status", "value": "0x1"}
    report = psir.validate_step_ordering(_ir(doc), _facts(_clean_facts()))
    assert report["status"] == psir.STATUS_ORDER_INVALID
    codes = {f["code"] for f in report["findings"]}
    assert psir.FINDING_ACCESS_TYPE_MISMATCH in codes


def test_read_from_write_only_register_is_flagged():
    doc = _clean_sequence_doc()
    doc["steps"][5] = {"index": 5, "phase": "VERIFY", "action": "read",
                        "register": "soft_reset"}  # soft_reset is WO
    report = psir.validate_step_ordering(_ir(doc), _facts(_clean_facts()))
    assert report["status"] == psir.STATUS_ORDER_INVALID
    codes = {f["code"] for f in report["findings"]}
    assert psir.FINDING_ACCESS_TYPE_MISMATCH in codes


def test_unknown_access_type_is_a_warning_not_a_fail():
    doc = _clean_sequence_doc()
    facts = _clean_facts()
    facts[3]["access_type"] = "XYZZY"  # link_en gets a bogus mnemonic
    report = psir.validate_step_ordering(_ir(doc), _facts(facts))
    codes = {f["code"] for f in report["findings"]}
    assert psir.FINDING_UNKNOWN_ACCESS_TYPE in codes
    unknown_findings = [f for f in report["findings"] if f["code"] == psir.FINDING_UNKNOWN_ACCESS_TYPE]
    assert all(f["severity"] == "WARNING" for f in unknown_findings)
    # a warning-only finding must not by itself flip status to FAIL
    assert report["status"] == psir.STATUS_ORDER_VALID


def test_dependency_not_yet_satisfied_is_flagged():
    doc = _clean_sequence_doc()
    facts = _clean_facts()
    # Declare link_en depends_on a register that IS a real fact but is never
    # written earlier in this particular sequence.
    for f in facts:
        if f["name"] == "link_en":
            f["depends_on"] = ["link_status"]
    report = psir.validate_step_ordering(_ir(doc), _facts(facts))
    assert report["status"] == psir.STATUS_ORDER_INVALID
    codes = {f["code"] for f in report["findings"]}
    assert psir.FINDING_DEPENDENCY_NOT_YET_SATISFIED in codes


def test_dangling_dependency_on_nonexistent_register_is_flagged():
    doc = _clean_sequence_doc()
    facts = _clean_facts()
    for f in facts:
        if f["name"] == "phy_cfg":
            f["depends_on"] = ["ghost_register"]
    report = psir.validate_step_ordering(_ir(doc), _facts(facts))
    assert report["status"] == psir.STATUS_ORDER_INVALID
    codes = {f["code"] for f in report["findings"]}
    assert psir.FINDING_DANGLING_DEPENDENCY in codes


def test_circular_dependency_is_flagged_once():
    doc = _clean_sequence_doc()
    facts = _clean_facts()
    by_name = {f["name"]: f for f in facts}
    by_name["clk_en"]["depends_on"] = ["link_en"]  # link_en -> ... -> clk_en -> link_en cycle
    report = psir.validate_step_ordering(_ir(doc), _facts(facts))
    assert report["status"] == psir.STATUS_ORDER_INVALID
    codes = [f["code"] for f in report["findings"]]
    assert codes.count(psir.FINDING_DEPENDENCY_CYCLE) == 1


def test_dependency_satisfied_earlier_in_sequence_does_not_fail():
    # Sanity: the clean fixture's own real depends_on chain (link_en depends
    # on link_cfg depends on phy_cfg depends on clk_en, all written earlier)
    # must not itself trigger a finding.
    report = psir.validate_step_ordering(_ir(_clean_sequence_doc()), _facts(_clean_facts()))
    codes = {f["code"] for f in report["findings"]}
    assert psir.FINDING_DEPENDENCY_NOT_YET_SATISFIED not in codes
    assert psir.FINDING_DANGLING_DEPENDENCY not in codes
    assert psir.FINDING_DEPENDENCY_CYCLE not in codes


# ---------------------------------------------------------------------------
# malformed-input controls -- construction itself must refuse, not coerce
# ---------------------------------------------------------------------------

def test_non_contiguous_step_indices_refused():
    doc = _clean_sequence_doc()
    doc["steps"][2]["index"] = 99
    with pytest.raises(psir.ProgrammingSequenceIRError):
        _ir(doc)


def test_missing_register_on_non_wait_step_refused():
    doc = {"name": "bad_seq", "steps": [
        {"index": 0, "phase": "INIT", "action": "write"},
    ]}
    with pytest.raises(psir.ProgrammingSequenceIRError):
        _ir(doc)


def test_bad_action_refused():
    doc = {"name": "bad_seq", "steps": [
        {"index": 0, "phase": "INIT", "action": "erase", "register": "clk_en"},
    ]}
    with pytest.raises(psir.ProgrammingSequenceIRError):
        _ir(doc)


def test_register_fact_missing_name_refused():
    with pytest.raises(psir.ProgrammingSequenceIRError):
        _facts([{"offset": "0x0", "access_type": "RW"}])


def test_register_fact_depends_on_not_a_list_refused():
    with pytest.raises(psir.ProgrammingSequenceIRError):
        _facts([{"name": "r1", "depends_on": "r0"}])


def test_no_name_document_refused():
    with pytest.raises(psir.ProgrammingSequenceIRError):
        _ir({"steps": []})


# ---------------------------------------------------------------------------
# CLI: real subprocess, real files
# ---------------------------------------------------------------------------

def _run_cli(args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.programming_sequence_ir"] + args,
        cwd=cwd, capture_output=True, text=True,
    )


def test_cli_pass_exit_0(tmp_path):
    seq_path = tmp_path / "seq.json"
    facts_path = tmp_path / "facts.json"
    seq_path.write_text(json.dumps(_clean_sequence_doc()), encoding="utf-8")
    facts_path.write_text(json.dumps(_clean_facts()), encoding="utf-8")
    repo_root = Path(__file__).resolve().parents[1]
    result = _run_cli(
        ["validate", "--sequence", str(seq_path), "--facts", str(facts_path), "--json"],
        cwd=str(repo_root),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "ORDER_VALID"


def test_cli_fail_exit_1_on_broken_sequence(tmp_path):
    doc = _clean_sequence_doc()
    doc["steps"][1]["register"] = "does_not_exist_reg"
    seq_path = tmp_path / "seq.json"
    facts_path = tmp_path / "facts.json"
    seq_path.write_text(json.dumps(doc), encoding="utf-8")
    facts_path.write_text(json.dumps(_clean_facts()), encoding="utf-8")
    repo_root = Path(__file__).resolve().parents[1]
    result = _run_cli(
        ["validate", "--sequence", str(seq_path), "--facts", str(facts_path), "--json"],
        cwd=str(repo_root),
    )
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "ORDER_INVALID"


def test_cli_not_available_exit_2_with_no_facts(tmp_path):
    seq_path = tmp_path / "seq.json"
    seq_path.write_text(json.dumps(_clean_sequence_doc()), encoding="utf-8")
    repo_root = Path(__file__).resolve().parents[1]
    result = _run_cli(
        ["validate", "--sequence", str(seq_path), "--json"], cwd=str(repo_root),
    )
    assert result.returncode == 2, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "NOT_AVAILABLE"


# ---------------------------------------------------------------------------
# vocabulary disjointness (import-time assertion re-checked explicitly)
# ---------------------------------------------------------------------------

def test_vocabulary_disjoint_from_models_status():
    psir.assert_no_verification_verdict_vocabulary()  # must not raise
