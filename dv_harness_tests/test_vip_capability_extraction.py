"""Tests for dv_harness/vip_capability_extraction.py -- classifying a REAL
`vip_symbol_index` into VIPConfigIR/VIPTransactionIR/VIPScenarioPatternIR/
VIPCheckerCapabilityIR/VIPCoverageCapabilityIR, each carrying a 5-level
qualification tag (PROJECT_PROVEN/VIP_DOCUMENTED/VIP_EXAMPLE_MATCHED/
INFERRED_FROM_NAMING/UNKNOWN).

Discipline, the same one test_vip_api_card.py / test_power_intent.py use:

  1. A clean baseline is built over the REAL synthetic VIP source this repo
     already ships (examples/asset_processing/inputs/vip_src/svt_demo_pkg.sv,
     the same fixture vip_api_card's own tests use), classified with NO
     corroborating evidence supplied at all, and asserted to reach every one
     of the four IR categories that fixture's real classes actually support,
     each landing at the honest default qualification (INFERRED_FROM_NAMING)
     -- proving the module never promotes on the strength of a heuristic
     match alone.
  2. Every promotion rule is then driven by supplying real corroborating
     evidence (a real project-source citation, a real VIP-example citation, a
     real `vip_user_guide_distill`-produced reference.md) one at a time, and
     the priority ordering across all three is checked together.
  3. Negative controls give the classifier its detection power: a class whose
     naming and inheritance signals genuinely DISAGREE is reported ambiguous
     with qualification UNKNOWN, never silently guessed into either category;
     a class matching neither heuristic is left unclassified, never forced
     into one of the five IRs.
  4. Both real CLI entry points (`python -m dv_harness.vip_capability_extraction`)
     are driven as real subprocesses.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from dv_harness import vip_capability_extraction as vce
from dv_harness import vip_symbol_index as vsi
from dv_harness import vip_user_guide_distill as vud

REPO_ROOT = Path(__file__).resolve().parents[1]
VIP_SRC_ROOT = REPO_ROOT / "examples" / "asset_processing" / "inputs" / "vip_src"
VIP_SRC_BASE = REPO_ROOT / "examples" / "asset_processing" / "inputs"


@pytest.fixture(scope="module")
def demo_index():
    """A REAL vip_symbol_index over the REAL synthetic VIP source, built by
    the real indexer -- not a hand-written dict."""
    return vsi.build_symbol_index([VIP_SRC_ROOT], "demo", relative_to=VIP_SRC_BASE)


def _write(tmp_path, subdir, name, text):
    d = tmp_path / subdir
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(text, encoding="utf-8")
    return d, p


def _rec(report, class_name):
    hits = [r for r in report.items if r.class_name == class_name]
    assert hits, f"no VIPCapabilityRecord for {class_name!r}; got {[r.class_name for r in report.items]}"
    return hits[0]


# ---------------------------------------------------------------------------
# 1. clean baseline: classification with NO corroborating evidence
# ---------------------------------------------------------------------------

def test_classifies_demo_vip_into_four_ir_types_from_naming_and_inheritance(demo_index):
    report = vce.extract_vip_capabilities(demo_index)
    assert report.status == "CLASSIFIED"
    assert report.reason is None

    cfg = _rec(report, "svt_demo_cfg")
    assert cfg.ir_type == vce.IR_VIP_CONFIG
    assert cfg.basis == "NAME_ONLY"           # uvm_object is too generic to corroborate config
    assert cfg.base_class == "uvm_object"
    assert {f["name"] for f in cfg.config_fields} == {
        "enable_protocol_checks", "max_burst_length", "coverage_enable", "interface_name"}

    txn = _rec(report, "svt_demo_transaction")
    assert txn.ir_type == vce.IR_VIP_TRANSACTION
    assert txn.basis == "NAME_AND_INHERITANCE_AGREE"
    assert txn.base_class == "uvm_sequence_item"
    assert {f["name"] for f in txn.config_fields} == {"address", "payload", "is_write"}

    seq = _rec(report, "svt_demo_base_sequence")
    assert seq.ir_type == vce.IR_VIP_SCENARIO_PATTERN
    assert seq.basis == "NAME_AND_INHERITANCE_AGREE"
    assert seq.base_class == "uvm_sequence"
    assert seq.pattern_kind == "SEQUENCE"

    mon = _rec(report, "svt_demo_monitor")
    assert mon.ir_type == vce.IR_VIP_CHECKER_CAPABILITY
    assert mon.basis == "NAME_AND_INHERITANCE_AGREE"
    assert mon.base_class == "uvm_monitor"
    assert mon.analysis_ports == []           # real fixture declares none -- never fabricated

    assert vce.IR_VIP_COVERAGE_CAPABILITY not in report.counts_by_ir_type
    # svt_demo_report_cb (added for the sixth VIPCallbackHookIR capability,
    # see dv_harness/vip_callback_hook_extraction.py) is correctly left
    # unclassified by THIS five-capability module: its name suffix ("cb")
    # and its inheritance base ("uvm_callback") match neither of the five
    # naming suffixes nor the five inheritance markers this module tracks.
    assert set(report.unclassified_class_names) == {
        "svt_demo_driver", "svt_demo_agent", "svt_demo_report_cb"}
    assert report.counts_by_ir_type == {
        vce.IR_VIP_CONFIG: 1, vce.IR_VIP_TRANSACTION: 1,
        vce.IR_VIP_SCENARIO_PATTERN: 1, vce.IR_VIP_CHECKER_CAPABILITY: 1,
    }


def test_no_item_is_ever_project_proven_or_documented_without_real_corroboration(demo_index):
    """The headline honesty rule: with zero corroborating evidence supplied,
    NOTHING may be tagged PROJECT_PROVEN/VIP_DOCUMENTED/VIP_EXAMPLE_MATCHED --
    every classified item stays at the honest INFERRED_FROM_NAMING floor."""
    report = vce.extract_vip_capabilities(demo_index)
    assert report.items, "fixture must actually classify something for this assertion to mean anything"
    for rec in report.items:
        assert rec.qualification == vce.INFERRED_FROM_NAMING
    assert report.counts_by_qualification == {vce.INFERRED_FROM_NAMING: len(report.items)}
    assert report.project_sources_scanned == 0
    assert report.example_sources_scanned == 0
    assert report.user_guide_references_scanned == 0
    # Every real declaration evidence entry cites a real file:line the
    # indexer actually recorded -- never a fabricated location.
    for rec in report.items:
        decl = [e for e in rec.evidence if e["kind"] == "VIP_SYMBOL_INDEX_DECLARATION"]
        assert decl and decl[0]["location"] == f"{rec.file}:{rec.line}"


# ---------------------------------------------------------------------------
# 2. promotion rules, one at a time, then combined priority
# ---------------------------------------------------------------------------

def test_project_proven_requires_a_real_citation_in_project_source(demo_index, tmp_path):
    d, p = _write(tmp_path, "project", "env.sv", "svt_demo_cfg cfg;\n")
    report = vce.extract_vip_capabilities(demo_index, project_sources=[d], project_relative_to=d)
    cfg = _rec(report, "svt_demo_cfg")
    assert cfg.qualification == vce.PROJECT_PROVEN
    usage = [e for e in cfg.evidence if e["kind"] == "PROJECT_USAGE"]
    assert usage and usage[0]["location"] == "env.sv:1"
    # Nothing else was cited -- nothing else may be promoted.
    txn = _rec(report, "svt_demo_transaction")
    assert txn.qualification == vce.INFERRED_FROM_NAMING


def test_vip_example_matched_requires_a_real_citation_in_example_source(demo_index, tmp_path):
    d, p = _write(tmp_path, "Examples", "basic_example.sv", "svt_demo_transaction txn;\n")
    report = vce.extract_vip_capabilities(demo_index, example_sources=[d], example_relative_to=d)
    txn = _rec(report, "svt_demo_transaction")
    assert txn.qualification == vce.VIP_EXAMPLE_MATCHED
    usage = [e for e in txn.evidence if e["kind"] == "VIP_EXAMPLE_USAGE"]
    assert usage and usage[0]["location"] == "basic_example.sv:1"
    cfg = _rec(report, "svt_demo_cfg")
    assert cfg.qualification == vce.INFERRED_FROM_NAMING


def test_vip_documented_uses_a_real_distilled_user_guide_reference(demo_index, tmp_path):
    guide_txt = tmp_path / "guide.txt"
    guide_txt.write_text(textwrap.dedent("""\
        1. Overview
        This document is a synthetic user-guide fixture for testing only.

        3.1 svt_demo_transaction Structure
        Describes the transaction fields
        """), encoding="utf-8")
    record = vud.distill_user_guide(guide_txt, tmp_path / "distilled")
    ref_md = record["distilled_reference"]["path"]
    assert Path(ref_md).exists()

    report = vce.extract_vip_capabilities(demo_index, user_guide_reference_md=[ref_md])
    txn = _rec(report, "svt_demo_transaction")
    assert txn.qualification == vce.VIP_DOCUMENTED
    usage = [e for e in txn.evidence if e["kind"] == "VIP_USER_GUIDE_SECTION"]
    assert usage and "svt_demo_transaction" in usage[0]["detail"]
    cfg = _rec(report, "svt_demo_cfg")
    assert cfg.qualification == vce.INFERRED_FROM_NAMING


def test_promotion_priority_project_over_documented_over_example(demo_index, tmp_path):
    proj_dir, _ = _write(tmp_path, "project", "env.sv", "svt_demo_cfg cfg;\n")
    ex_dir, _ = _write(tmp_path, "Examples", "ex.sv",
                       "svt_demo_transaction txn;\nsvt_demo_cfg cfg2;\n")
    guide_txt = tmp_path / "guide.txt"
    guide_txt.write_text(textwrap.dedent("""\
        1.1 svt_demo_cfg Configuration Object
        Describes configuration knobs

        1.2 svt_demo_transaction Reference
        Describes transaction fields
        """), encoding="utf-8")
    record = vud.distill_user_guide(guide_txt, tmp_path / "distilled2")
    ref_md = record["distilled_reference"]["path"]

    report = vce.extract_vip_capabilities(
        demo_index,
        project_sources=[proj_dir], project_relative_to=proj_dir,
        example_sources=[ex_dir], example_relative_to=ex_dir,
        user_guide_reference_md=[ref_md],
    )
    # svt_demo_cfg: cited in project AND example, documented too -> PROJECT wins.
    cfg = _rec(report, "svt_demo_cfg")
    assert cfg.qualification == vce.PROJECT_PROVEN
    # svt_demo_transaction: documented AND example-cited, no project citation
    # -> VIP_DOCUMENTED wins over VIP_EXAMPLE_MATCHED.
    txn = _rec(report, "svt_demo_transaction")
    assert txn.qualification == vce.VIP_DOCUMENTED
    # Nothing cites the sequence or the monitor anywhere -- both stay at the
    # honest floor.
    seq = _rec(report, "svt_demo_base_sequence")
    mon = _rec(report, "svt_demo_monitor")
    assert seq.qualification == vce.INFERRED_FROM_NAMING
    assert mon.qualification == vce.INFERRED_FROM_NAMING


# ---------------------------------------------------------------------------
# 3. negative controls: ambiguity and non-classification are never guessed away
# ---------------------------------------------------------------------------

def test_naming_and_inheritance_disagreement_is_reported_ambiguous_not_guessed(tmp_path):
    d, _ = _write(tmp_path, "vip", "evil.sv", textwrap.dedent("""\
        package evil_pkg;
          class svt_evil_cfg extends uvm_sequence;
            virtual task body();
            endtask
          endclass
        endpackage
        """))
    index = vsi.build_symbol_index([d], "demo")
    report = vce.extract_vip_capabilities(index)
    assert report.status == "ONLY_AMBIGUOUS"
    assert report.items == []
    assert len(report.ambiguous) == 1
    amb = report.ambiguous[0]
    assert amb.class_name == "svt_evil_cfg"
    assert amb.ir_type == vce.IR_AMBIGUOUS
    assert amb.qualification == vce.UNKNOWN
    assert amb.basis == "NAME_AND_INHERITANCE_DISAGREE"
    assert amb.name_category == vce.IR_VIP_CONFIG
    assert amb.inheritance_category == vce.IR_VIP_SCENARIO_PATTERN
    assert "svt_evil_cfg" not in [r.class_name for r in report.items]


def test_class_matching_neither_heuristic_is_left_unclassified(tmp_path):
    d, _ = _write(tmp_path, "vip", "helper.sv", textwrap.dedent("""\
        package helper_pkg;
          class svt_helper_util extends uvm_object;
            bit enabled;
          endclass
        endpackage
        """))
    index = vsi.build_symbol_index([d], "demo")
    report = vce.extract_vip_capabilities(index)
    assert report.status == "NOTHING_CLASSIFIED"
    assert report.reason == "NO_CLASS_MATCHED_ANY_NAMING_OR_INHERITANCE_HEURISTIC"
    assert report.items == []
    assert report.ambiguous == []
    assert report.unclassified_class_names == ["svt_helper_util"]


def test_empty_index_reports_not_available_never_a_clean_pass():
    empty = {
        "schema_version": "1.0", "generator": {"tool": "t", "version": "1.0"},
        "protocol": "demo", "roots": [],
        "stats": {"files_scanned": 0, "classes_indexed": 0, "methods_indexed": 0, "bytes_scanned": 0},
        "classes": [],
    }
    report = vce.extract_vip_capabilities(empty)
    assert report.status == "NOT_AVAILABLE"
    assert report.reason == "VIP_SYMBOL_INDEX_CONTAINS_NO_CLASSES"
    assert report.items == [] and report.ambiguous == []


def test_naming_suffix_table_is_disjoint():
    table = vce.assert_naming_categories_disjoint()
    assert table["cfg"] == vce.IR_VIP_CONFIG
    assert table["seq"] == vce.IR_VIP_SCENARIO_PATTERN
    assert table["monitor"] == vce.IR_VIP_CHECKER_CAPABILITY
    assert table["cov"] == vce.IR_VIP_COVERAGE_CAPABILITY
    assert table["item"] == vce.IR_VIP_TRANSACTION
    assert len(table) == len(set(table))  # every key genuinely unique


# ---------------------------------------------------------------------------
# VIP-04 / VIP-05 / VIP-18: real vendor naming and vendor base-class markers
# ---------------------------------------------------------------------------

def test_real_synopsys_usb_svt_naming_convention_classifies_as_transaction(tmp_path):
    """svt_usb_transfer -- the REAL Synopsys USB SVT core transaction class
    name (.work/intake-vip_examples-report.md) -- matches none of the naming
    suffixes this table had before VIP-04 (item/txn/transaction/packet/
    frame). It must classify purely from the added 'transfer' suffix when no
    inheritance evidence is present at all."""
    d, _ = _write(tmp_path, "vip", "transfer.sv", textwrap.dedent("""\
        package usb_pkg;
          class svt_usb_transfer extends uvm_object;
            bit [7:0] pid;
          endclass
        endpackage
        """))
    index = vsi.build_symbol_index([d], "usb")
    report = vce.extract_vip_capabilities(index)
    rec = _rec(report, "svt_usb_transfer")
    assert rec.ir_type == vce.IR_VIP_TRANSACTION
    assert rec.basis == "NAME_ONLY"


def test_inheritance_walks_through_a_fully_indexed_vendor_intermediate_base(tmp_path):
    """When the vendor's own intermediate base class IS indexed (both files
    scanned), the existing multi-level chain walk already resolves the real
    UVM terminal correctly with no vendor-marker fallback needed -- this is
    the positive control the fallback below is contrasted against."""
    d, _ = _write(tmp_path, "vip", "usb.sv", textwrap.dedent("""\
        package usb_pkg;
          class svt_transaction extends uvm_sequence_item;
            bit dummy;
          endclass
          class svt_usb_transfer extends svt_transaction;
            bit [7:0] pid;
          endclass
        endpackage
        """))
    index = vsi.build_symbol_index([d], "usb")
    report = vce.extract_vip_capabilities(index)
    rec = _rec(report, "svt_usb_transfer")
    assert rec.ir_type == vce.IR_VIP_TRANSACTION
    assert rec.basis == "NAME_AND_INHERITANCE_AGREE"
    assert rec.inheritance_chain == ["svt_usb_transfer", "svt_transaction"]
    assert rec.chain_closed is True
    assert rec.inheritance_via_vendor_marker is False


def test_inheritance_falls_back_to_vendor_marker_when_intermediate_base_is_unindexed(tmp_path):
    """The genuinely unhandled case (VIP-05): `svt_transaction` is the
    vendor's own base class but its file was never scanned (e.g. excluded
    from the roots, or opaque behind pragma protect). The chain is OPEN and
    `svt_transaction` is neither indexed nor a bare uvm_* marker -- but it IS
    a known, documented vendor base-class name, so classification must still
    succeed via the vendor-marker fallback rather than silently failing."""
    d, _ = _write(tmp_path, "vip", "usb.sv", textwrap.dedent("""\
        package usb_pkg;
          class svt_usb_transfer extends svt_transaction;
            bit [7:0] pid;
          endclass
        endpackage
        """))
    index = vsi.build_symbol_index([d], "usb")
    cat, chain, closed, terminal_base, via_marker = vce.classify_by_inheritance(
        vip_api_card_by_name := {c["name"]: c for c in index["classes"]}, "svt_usb_transfer")
    assert cat == vce.IR_VIP_TRANSACTION
    assert chain == ["svt_usb_transfer"]
    assert closed is False                    # a real absence claim is NOT provable here
    assert terminal_base == "svt_transaction"
    assert via_marker is True

    report = vce.extract_vip_capabilities(index)
    rec = _rec(report, "svt_usb_transfer")
    assert rec.ir_type == vce.IR_VIP_TRANSACTION
    assert rec.inheritance_via_vendor_marker is True
    assert rec.chain_closed is False
    assert any(e["kind"] == "VENDOR_BASE_LIBRARY_MARKER" for e in rec.evidence)


def test_vendor_marker_table_covers_the_real_synopsys_intermediate_base_layer(tmp_path):
    """.work/intake-vip_source-report.md lists svt_transaction.sv/
    svt_configuration.sv/svt_sequencer.sv/svt_agent.sv/svt_xactor.sv as the
    real vendor intermediate base-class layer for this project's own VIP.
    The extensible marker table must know the ones this module classifies
    (transaction/config/sequence/checker), each mapped unambiguously."""
    assert vce._VENDOR_BASE_LIBRARY_MARKER_TO_CATEGORY["svt_transaction"] == vce.IR_VIP_TRANSACTION
    assert vce._VENDOR_BASE_LIBRARY_MARKER_TO_CATEGORY["svt_configuration"] == vce.IR_VIP_CONFIG
    assert vce._VENDOR_BASE_LIBRARY_MARKER_TO_CATEGORY["svt_sequence"] == vce.IR_VIP_SCENARIO_PATTERN
    assert vce._VENDOR_BASE_LIBRARY_MARKER_TO_CATEGORY["svt_virtual_sequence"] == vce.IR_VIP_SCENARIO_PATTERN
    # Disjoint against the strict UVM marker table -- no name claims two
    # different categories across the two tables.
    overlap = set(vce._INHERITANCE_MARKER_TO_CATEGORY) & set(vce._VENDOR_BASE_LIBRARY_MARKER_TO_CATEGORY)
    assert overlap == set()


def test_missing_index_file_raises_rather_than_reporting_a_clean_result(tmp_path):
    with pytest.raises(vce.VipCapabilityExtractionError):
        vce.load_index_and_classify(tmp_path / "does_not_exist.json")


# ---------------------------------------------------------------------------
# 4. real CLI entry point
# ---------------------------------------------------------------------------

def test_cli_module_entrypoint_classifies_and_writes_artifact(demo_index, tmp_path):
    index_path = tmp_path / "index.json"
    vsi.save_symbol_index(demo_index, index_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.vip_capability_extraction",
         "--index", str(index_path), "--out-dir", str(out_dir), "--json"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "CLASSIFIED"
    written = json.loads((out_dir / vce.CAPABILITY_EXTRACTION_REPORT_NAME).read_text(encoding="utf-8"))
    assert written["status"] == "CLASSIFIED"
    names = {item["class_name"] for item in written["items"]}
    assert {"svt_demo_cfg", "svt_demo_transaction", "svt_demo_base_sequence",
            "svt_demo_monitor"} <= names


def test_cli_module_entrypoint_exits_2_on_missing_index(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.vip_capability_extraction",
         "--index", str(tmp_path / "nope.json")],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "VipCapabilityExtractionError" in proc.stdout or "does not exist" in proc.stdout
