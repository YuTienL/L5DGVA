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


# ---------------------------------------------------------------------------
# EXTENSION: RegisterDependencyGraph -- project-wide dependency graph over
# the FULL register set, independent of any one ProgrammingSequenceIR.
# Reuses the same RegisterFact shape and the same _detect_dependency_cycle()
# cycle detector validate_step_ordering() already uses.
# ---------------------------------------------------------------------------

def _acyclic_facts():
    # A small real DAG: dma_ctrl -> dma_base_addr, dma_len -> dma_base_addr,
    # link_en -> link_cfg -> phy_cfg (no dependents), plus a register that
    # depends on nothing (root) and one nobody depends on (leaf).
    return [
        {"name": "phy_cfg", "depends_on": []},
        {"name": "link_cfg", "depends_on": ["phy_cfg"]},
        {"name": "link_en", "depends_on": ["link_cfg"]},
        {"name": "dma_base_addr", "depends_on": []},
        {"name": "dma_len", "depends_on": ["dma_base_addr"]},
        {"name": "dma_ctrl", "depends_on": ["dma_base_addr", "dma_len"]},
    ]


def _cyclic_facts():
    return [
        {"name": "a", "depends_on": ["b"]},
        {"name": "b", "depends_on": ["c"]},
        {"name": "c", "depends_on": ["a"]},
    ]


def _dangling_facts():
    return [
        {"name": "phy_cfg", "depends_on": []},
        {"name": "link_cfg", "depends_on": ["phy_cfg", "ghost_reg"]},
    ]


def test_graph_dependencies_and_dependents_distinguish_unknown_from_empty():
    graph = psir.RegisterDependencyGraph.build(_facts(_acyclic_facts()))
    # a known register with a real, non-empty depends_on
    assert graph.dependencies("dma_ctrl") == ["dma_base_addr", "dma_len"]
    # a known register that declares no dependency at all -> real empty list
    assert graph.dependencies("phy_cfg") == []
    # an unknown register name -> None, never conflated with an empty list
    assert graph.dependencies("does_not_exist") is None
    assert graph.dependents("does_not_exist") is None
    # reverse-edge view: who directly depends on dma_base_addr
    assert graph.dependents("dma_base_addr") == ["dma_ctrl", "dma_len"]
    # a leaf nobody depends on -> real empty list, not None
    assert graph.dependents("dma_ctrl") == []
    assert graph.register_count == 6
    assert graph.known("phy_cfg") is True
    assert graph.known("nope") is False


def test_graph_transitive_dependencies_and_dependents():
    graph = psir.RegisterDependencyGraph.build(_facts(_acyclic_facts()))
    assert graph.transitive_dependencies("link_en") == ["link_cfg", "phy_cfg"]
    assert graph.transitive_dependencies("phy_cfg") == []
    assert graph.transitive_dependencies("unknown_reg") is None
    assert graph.transitive_dependents("phy_cfg") == ["link_cfg", "link_en"]
    assert graph.transitive_dependents("link_en") == []
    assert graph.transitive_dependents("unknown_reg") is None


def test_graph_detect_cycle_reuses_shared_detector_none_when_acyclic():
    graph = psir.RegisterDependencyGraph.build(_facts(_acyclic_facts()))
    assert graph.detect_cycle() is None


def test_graph_detect_cycle_finds_a_real_cycle():
    graph = psir.RegisterDependencyGraph.build(_facts(_cyclic_facts()))
    cycle = graph.detect_cycle()
    assert cycle is not None
    # closes back on the first element
    assert cycle[0] == cycle[-1]
    assert set(cycle) == {"a", "b", "c"}


def test_graph_dangling_dependencies_reported_project_wide():
    graph = psir.RegisterDependencyGraph.build(_facts(_dangling_facts()))
    dangling = graph.dangling_dependencies()
    assert dangling == [{"register": "link_cfg", "missing_dependency": "ghost_reg"}]
    # a clean graph reports none
    clean_graph = psir.RegisterDependencyGraph.build(_facts(_acyclic_facts()))
    assert clean_graph.dangling_dependencies() == []


def test_graph_topological_order_is_a_real_valid_write_order():
    graph = psir.RegisterDependencyGraph.build(_facts(_acyclic_facts()))
    topo = graph.topological_order()
    assert topo["status"] == psir.STATUS_TOPO_ORDER_VALID
    assert topo["cycle"] is None
    order = topo["order"]
    assert set(order) == {"phy_cfg", "link_cfg", "link_en", "dma_base_addr", "dma_len", "dma_ctrl"}
    # every dependency must appear strictly before its dependent
    pos = {name: i for i, name in enumerate(order)}
    assert pos["phy_cfg"] < pos["link_cfg"] < pos["link_en"]
    assert pos["dma_base_addr"] < pos["dma_len"] < pos["dma_ctrl"]


def test_graph_topological_order_reports_cycle_never_a_partial_order():
    graph = psir.RegisterDependencyGraph.build(_facts(_cyclic_facts()))
    topo = graph.topological_order()
    assert topo["status"] == psir.STATUS_TOPO_ORDER_CYCLE
    assert topo["order"] is None
    assert topo["cycle"] is not None


def test_graph_to_report_bundles_everything():
    graph = psir.RegisterDependencyGraph.build(_facts(_acyclic_facts()))
    report = graph.to_report()
    assert report["schema_version"] == psir.SCHEMA_VERSION
    assert report["status"] == psir.STATUS_GRAPH_AVAILABLE
    assert report["register_count"] == 6
    assert report["cycle"] is None
    assert report["dangling_dependencies"] == []
    assert report["topological_order"]["status"] == psir.STATUS_TOPO_ORDER_VALID


# --- build_register_dependency_graph(): the honest report-shaped front door ---

def test_build_register_dependency_graph_no_facts_is_honestly_not_available():
    # Absence of evidence must NEVER read as a vacuous "empty but available"
    # graph -- the same discipline validate_step_ordering() already applies.
    report = psir.build_register_dependency_graph(None)
    assert report["status"] == psir.STATUS_GRAPH_NOT_AVAILABLE
    assert report["register_count"] == 0
    assert report["cycle"] is None
    assert report["dangling_dependencies"] == []
    assert "reason" in report and report["reason"]
    assert report["topological_order"]["status"] == psir.STATUS_GRAPH_NOT_AVAILABLE

    empty_report = psir.build_register_dependency_graph([])
    assert empty_report["status"] == psir.STATUS_GRAPH_NOT_AVAILABLE


def test_build_register_dependency_graph_with_real_facts():
    report = psir.build_register_dependency_graph(_facts(_acyclic_facts()))
    assert report["status"] == psir.STATUS_GRAPH_AVAILABLE
    assert report["register_count"] == 6
    assert report["cycle"] is None


def test_build_register_dependency_graph_surfaces_cycle_and_dangling():
    cyc_report = psir.build_register_dependency_graph(_facts(_cyclic_facts()))
    assert cyc_report["status"] == psir.STATUS_GRAPH_AVAILABLE
    assert cyc_report["cycle"] is not None

    dangling_report = psir.build_register_dependency_graph(_facts(_dangling_facts()))
    assert dangling_report["dangling_dependencies"] == [
        {"register": "link_cfg", "missing_dependency": "ghost_reg"}
    ]


# ---------------------------------------------------------------------------
# EXTENSION: Illegal Sequence Catalog -- documented misuse knowledge, never
# invented here; every entry requires a real, non-empty evidence citation.
# ---------------------------------------------------------------------------

def _clean_pattern_dict(pattern_id="P-DMA-ARM-BEFORE-FLUSH"):
    return {
        "pattern_id": pattern_id,
        "registers_in_order": ["dma_arm", "dma_flush"],
        "evidence": "programming_guide.pdf section 4.2",
        "description": "arming DMA before a prior flush completes locks the engine",
        "rationale": "DMA hardware latch is not cleared until flush completes",
        "severity": "ERROR",
    }


def test_illegal_sequence_pattern_from_dict_clean():
    pattern = psir.illegal_sequence_pattern_from_dict(_clean_pattern_dict())
    assert pattern.pattern_id == "P-DMA-ARM-BEFORE-FLUSH"
    assert pattern.registers_in_order == ["dma_arm", "dma_flush"]
    assert pattern.evidence
    assert pattern.severity == "ERROR"


def test_illegal_sequence_pattern_requires_a_real_evidence_citation():
    raw = _clean_pattern_dict()
    raw["evidence"] = ""
    with pytest.raises(psir.ProgrammingSequenceIRError):
        psir.illegal_sequence_pattern_from_dict(raw)

    raw2 = _clean_pattern_dict()
    del raw2["evidence"]
    with pytest.raises(psir.ProgrammingSequenceIRError):
        psir.illegal_sequence_pattern_from_dict(raw2)


def test_illegal_sequence_pattern_requires_at_least_two_registers():
    raw = _clean_pattern_dict()
    raw["registers_in_order"] = ["dma_arm"]
    with pytest.raises(psir.ProgrammingSequenceIRError):
        psir.illegal_sequence_pattern_from_dict(raw)


def test_illegal_sequence_pattern_rejects_bad_register_entries():
    raw = _clean_pattern_dict()
    raw["registers_in_order"] = ["dma_arm", ""]
    with pytest.raises(psir.ProgrammingSequenceIRError):
        psir.illegal_sequence_pattern_from_dict(raw)


def test_illegal_sequence_pattern_rejects_bad_severity():
    raw = _clean_pattern_dict()
    raw["severity"] = "CRITICAL"
    with pytest.raises(psir.ProgrammingSequenceIRError):
        psir.illegal_sequence_pattern_from_dict(raw)


def test_illegal_sequence_pattern_requires_pattern_id():
    raw = _clean_pattern_dict()
    raw["pattern_id"] = ""
    with pytest.raises(psir.ProgrammingSequenceIRError):
        psir.illegal_sequence_pattern_from_dict(raw)


def test_load_illegal_sequence_catalog_empty_is_empty_list():
    assert psir.load_illegal_sequence_catalog(None) == []
    assert psir.load_illegal_sequence_catalog([]) == []


def test_load_illegal_sequence_catalog_rejects_duplicate_pattern_id():
    raws = [_clean_pattern_dict("DUP"), _clean_pattern_dict("DUP")]
    with pytest.raises(psir.ProgrammingSequenceIRError):
        psir.load_illegal_sequence_catalog(raws)


def test_load_illegal_sequence_catalog_real_catalog():
    raws = [_clean_pattern_dict("P1"), _clean_pattern_dict("P2")]
    catalog = psir.load_illegal_sequence_catalog(raws)
    assert len(catalog) == 2
    assert {p.pattern_id for p in catalog} == {"P1", "P2"}


# --- check_illegal_sequences(): real subsequence matching over WRITE order ---

def _dma_sequence_doc(order):
    """Build a minimal sequence whose WRITE order is exactly `order`."""
    steps = []
    for i, reg in enumerate(order):
        steps.append({"index": i, "phase": "CONFIGURE", "action": "write",
                       "register": reg, "value": "0x1"})
    return {"name": "dma_seq", "steps": steps}


def test_check_illegal_sequences_matches_contiguous_write_order():
    ir = _ir(_dma_sequence_doc(["dma_arm", "dma_flush"]))
    catalog = [psir.illegal_sequence_pattern_from_dict(_clean_pattern_dict())]
    findings = psir.check_illegal_sequences(ir, catalog)
    assert len(findings) == 1
    f = findings[0]
    assert f.code == psir.FINDING_MATCHES_DOCUMENTED_ILLEGAL_SEQUENCE
    assert f.severity == "ERROR"
    assert "P-DMA-ARM-BEFORE-FLUSH" in f.message


def test_check_illegal_sequences_matches_non_contiguous_write_order():
    # dma_arm ... other write ... dma_flush -- still a real subsequence match,
    # not necessarily contiguous, per the module's own documented rule.
    ir = _ir(_dma_sequence_doc(["dma_arm", "unrelated_reg", "dma_flush"]))
    catalog = [psir.illegal_sequence_pattern_from_dict(_clean_pattern_dict())]
    findings = psir.check_illegal_sequences(ir, catalog)
    assert len(findings) == 1
    assert findings[0].code == psir.FINDING_MATCHES_DOCUMENTED_ILLEGAL_SEQUENCE


def test_check_illegal_sequences_no_match_when_order_reversed():
    ir = _ir(_dma_sequence_doc(["dma_flush", "dma_arm"]))
    catalog = [psir.illegal_sequence_pattern_from_dict(_clean_pattern_dict())]
    assert psir.check_illegal_sequences(ir, catalog) == []


def test_check_illegal_sequences_empty_catalog_or_no_steps_reports_nothing():
    ir = _ir(_dma_sequence_doc(["dma_arm", "dma_flush"]))
    assert psir.check_illegal_sequences(ir, []) == []
    assert psir.check_illegal_sequences(ir, None) == []
    empty_ir = _ir({"name": "empty", "steps": []})
    catalog = [psir.illegal_sequence_pattern_from_dict(_clean_pattern_dict())]
    assert psir.check_illegal_sequences(empty_ir, catalog) == []


def test_check_illegal_sequences_severity_is_per_pattern():
    raw = _clean_pattern_dict()
    raw["severity"] = "WARNING"
    ir = _ir(_dma_sequence_doc(["dma_arm", "dma_flush"]))
    catalog = [psir.illegal_sequence_pattern_from_dict(raw)]
    findings = psir.check_illegal_sequences(ir, catalog)
    assert len(findings) == 1
    assert findings[0].severity == "WARNING"


# --- validate_step_ordering(): the catalog folds into the existing report ---

def test_validate_step_ordering_default_behavior_unchanged_with_no_catalog():
    # Every pre-extension caller's behavior must be byte-for-byte unchanged
    # when illegal_sequence_catalog is omitted (default None).
    report = psir.validate_step_ordering(_ir(_clean_sequence_doc()), _facts(_clean_facts()))
    assert report["status"] == psir.STATUS_ORDER_VALID
    assert report["illegal_sequence_catalog_size"] == 0


def test_validate_step_ordering_folds_in_documented_illegal_sequence_finding():
    doc = _clean_sequence_doc()
    # add two writes at the end that reproduce the documented illegal order
    doc["steps"].append({"index": 7, "phase": "RESET", "action": "write",
                          "register": "dma_arm", "value": "0x1"})
    doc["steps"].append({"index": 8, "phase": "RESET", "action": "write",
                          "register": "dma_flush", "value": "0x1"})
    facts = _clean_facts() + [
        {"name": "dma_arm", "access_type": "WO", "depends_on": []},
        {"name": "dma_flush", "access_type": "WO", "depends_on": []},
    ]
    catalog = [psir.illegal_sequence_pattern_from_dict(_clean_pattern_dict())]
    report = psir.validate_step_ordering(_ir(doc), _facts(facts), illegal_sequence_catalog=catalog)
    assert report["status"] == psir.STATUS_ORDER_INVALID
    assert report["illegal_sequence_catalog_size"] == 1
    codes = {f["code"] for f in report["findings"]}
    assert psir.FINDING_MATCHES_DOCUMENTED_ILLEGAL_SEQUENCE in codes


def test_validate_step_ordering_catalog_check_still_needs_no_register_facts_for_that_specific_finding():
    # check_illegal_sequences() itself needs no register facts at all, but
    # validate_step_ordering()'s catalog branch only runs inside the
    # real-evidence branch (i.e. register_facts must still be supplied for
    # the OTHER three checks to run at all) -- confirm the NOT_AVAILABLE
    # honesty status still wins when no facts are supplied, catalog or not.
    doc = _dma_sequence_doc(["dma_arm", "dma_flush"])
    catalog = [psir.illegal_sequence_pattern_from_dict(_clean_pattern_dict())]
    report = psir.validate_step_ordering(_ir(doc), None, illegal_sequence_catalog=catalog)
    assert report["status"] == psir.STATUS_NOT_AVAILABLE


# ---------------------------------------------------------------------------
# CLI: the "graph" verb, real subprocess, real files
# ---------------------------------------------------------------------------

def test_cli_graph_verb_exit_0_no_cycle_no_dangling(tmp_path):
    facts_path = tmp_path / "facts.json"
    facts_path.write_text(json.dumps(_acyclic_facts()), encoding="utf-8")
    repo_root = Path(__file__).resolve().parents[1]
    result = _run_cli(["graph", "--facts", str(facts_path), "--json"], cwd=str(repo_root))
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == psir.STATUS_GRAPH_AVAILABLE
    assert report["cycle"] is None


def test_cli_graph_verb_exit_1_on_real_cycle(tmp_path):
    facts_path = tmp_path / "facts.json"
    facts_path.write_text(json.dumps(_cyclic_facts()), encoding="utf-8")
    repo_root = Path(__file__).resolve().parents[1]
    result = _run_cli(["graph", "--facts", str(facts_path), "--json"], cwd=str(repo_root))
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["cycle"] is not None


def test_cli_graph_verb_exit_1_on_dangling_dependency(tmp_path):
    facts_path = tmp_path / "facts.json"
    facts_path.write_text(json.dumps(_dangling_facts()), encoding="utf-8")
    repo_root = Path(__file__).resolve().parents[1]
    result = _run_cli(["graph", "--facts", str(facts_path), "--json"], cwd=str(repo_root))
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["dangling_dependencies"]


def test_cli_graph_verb_exit_2_not_available_missing_facts_flag(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    result = _run_cli(["graph"], cwd=str(repo_root))
    assert result.returncode == 2, result.stdout + result.stderr


def test_cli_validate_with_catalog_flag_reports_documented_illegal_sequence(tmp_path):
    doc = _dma_sequence_doc(["dma_arm", "dma_flush"])
    facts = [
        {"name": "dma_arm", "access_type": "WO", "depends_on": []},
        {"name": "dma_flush", "access_type": "WO", "depends_on": []},
    ]
    catalog = [_clean_pattern_dict()]
    seq_path = tmp_path / "seq.json"
    facts_path = tmp_path / "facts.json"
    catalog_path = tmp_path / "catalog.json"
    seq_path.write_text(json.dumps(doc), encoding="utf-8")
    facts_path.write_text(json.dumps(facts), encoding="utf-8")
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    repo_root = Path(__file__).resolve().parents[1]
    result = _run_cli(
        ["validate", "--sequence", str(seq_path), "--facts", str(facts_path),
         "--catalog", str(catalog_path), "--json"],
        cwd=str(repo_root),
    )
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "ORDER_INVALID"
    assert report["illegal_sequence_catalog_size"] == 1
    codes = {f["code"] for f in report["findings"]}
    assert "MATCHES_DOCUMENTED_ILLEGAL_SEQUENCE" in codes
