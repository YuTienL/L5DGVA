"""Tests for dv_harness/vip_callback_hook_extraction.py -- the SIXTH VIP
capability IR, VIPCallbackHookIR, classifying a REAL vip_symbol_index into
VIP CALLBACK/EXTENSION-POINT-shaped classes via a NAMING heuristic (a small
suffix table checked disjoint from vip_capability_extraction.py's OWN
already-disjoint table) + an INHERITANCE heuristic (a real UVM
uvm_callback/uvm_callback_iter base-class marker, or a bounded structural
extension-point fallback), each carrying the SAME 5-level qualification tag
the other five capabilities already use.

Discipline, matching test_vip_capability_extraction.py's own convention:

  1. A real callback/hook class (svt_demo_report_cb, added to the shared
     synthetic fixture svt_demo_pkg.sv for this module -- it previously
     declared no callback-shaped class) is classified correctly, with real
     cited evidence, at the honest INFERRED_FROM_NAMING floor absent
     corroboration, and every promotion rule is driven one at a time.
  2. Every OTHER real class in that shared fixture is proven correctly
     UNCLASSIFIED by this module -- including the two virtual-class-shaped
     ones (svt_demo_driver, svt_demo_agent) that could plausibly be
     mistaken for an extension point, proving the phase-method exclusion in
     the structural fallback has real detection power.
  3. Negative controls give the classifier its detection power: naming and
     inheritance genuinely disagreeing (in BOTH directions) is reported as
     an ambiguous candidate, never guessed into either side; a class
     matching neither heuristic is left unclassified.
  4. The disjoint-suffix-table import-time assertion is proven to actually
     catch a real collision when one is introduced.
  5. Both real CLI entry points (`python -m
     dv_harness.vip_callback_hook_extraction`) are driven as real
     subprocesses.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from dv_harness import vip_callback_hook_extraction as vche
from dv_harness import vip_capability_extraction as vce
from dv_harness import vip_symbol_index as vsi
from dv_harness import vip_user_guide_distill as vud

REPO_ROOT = Path(__file__).resolve().parents[1]
VIP_SRC_ROOT = REPO_ROOT / "examples" / "asset_processing" / "inputs" / "vip_src"
VIP_SRC_BASE = REPO_ROOT / "examples" / "asset_processing" / "inputs"


@pytest.fixture(scope="module")
def demo_index():
    """A REAL vip_symbol_index over the REAL synthetic VIP source this repo
    already ships (the same fixture vip_capability_extraction's own tests
    use), extended with one real UVM-callback-shaped class,
    svt_demo_report_cb, for this module's own use -- built by the real
    indexer, not a hand-written dict."""
    return vsi.build_symbol_index([VIP_SRC_ROOT], "demo", relative_to=VIP_SRC_BASE)


def _write(tmp_path, subdir, name, text):
    d = tmp_path / subdir
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(text, encoding="utf-8")
    return d, p


def _rec(report, class_name):
    hits = [r for r in report.items if r.class_name == class_name]
    assert hits, f"no VIPCallbackHookRecord for {class_name!r}; got {[r.class_name for r in report.items]}"
    return hits[0]


# ---------------------------------------------------------------------------
# 0. reuse proofs: the module imports, never re-declares, the shared vocabulary
# ---------------------------------------------------------------------------

def test_qualification_vocabulary_is_reused_not_redeclared():
    assert vche.QUALIFICATION_LEVELS is vce.QUALIFICATION_LEVELS
    assert vche.PROJECT_PROVEN is vce.PROJECT_PROVEN
    assert vche.VIP_DOCUMENTED is vce.VIP_DOCUMENTED
    assert vche.VIP_EXAMPLE_MATCHED is vce.VIP_EXAMPLE_MATCHED
    assert vche.INFERRED_FROM_NAMING is vce.INFERRED_FROM_NAMING
    assert vche.UNKNOWN is vce.UNKNOWN
    assert vche.IR_AMBIGUOUS is vce.IR_AMBIGUOUS


def test_disjoint_suffix_table_is_asserted_at_import_and_catches_a_real_collision():
    # The real, live check already ran at import -- re-running it here (over
    # the SAME real vip_capability_extraction table) must still pass.
    table = vche.assert_callback_suffix_disjoint_from_existing()
    assert table["cb"] == vche.IR_VIP_CALLBACK_HOOK
    assert table["callback"] == vche.IR_VIP_CALLBACK_HOOK
    assert table["hook"] == vche.IR_VIP_CALLBACK_HOOK
    # None of the other five capabilities' own suffixes were disturbed.
    assert table["cfg"] == vce.IR_VIP_CONFIG
    assert table["seq"] == vce.IR_VIP_SCENARIO_PATTERN

    # A deliberately-introduced collision ("cfg" is already claimed by
    # vip_capability_extraction's own config category) must raise, proving
    # this check has real detection power rather than merely never firing.
    with pytest.raises(RuntimeError, match="naming-suffix table collision"):
        vche.assert_callback_suffix_disjoint_from_existing(("cfg",))
    with pytest.raises(RuntimeError, match="naming-suffix table collision"):
        vche.assert_callback_suffix_disjoint_from_existing(("seq",))


# ---------------------------------------------------------------------------
# 1. clean baseline: the real callback class classified, everything else not
# ---------------------------------------------------------------------------

def test_classifies_real_callback_class_via_name_and_inheritance_agreement(demo_index):
    report = vche.extract_vip_callback_hooks(demo_index)
    assert report.status == "CLASSIFIED"
    assert report.reason is None
    assert report.ambiguous == []

    cb = _rec(report, "svt_demo_report_cb")
    assert cb.ir_type == vche.IR_VIP_CALLBACK_HOOK
    assert cb.basis == "NAME_AND_INHERITANCE_AGREE"
    assert cb.base_class == "uvm_callback"
    assert cb.name_category == vche.IR_VIP_CALLBACK_HOOK
    assert cb.inheritance_category == vche.IR_VIP_CALLBACK_HOOK
    assert cb.qualification == vche.INFERRED_FROM_NAMING  # no corroboration supplied
    decl = [e for e in cb.evidence if e["kind"] == "VIP_SYMBOL_INDEX_DECLARATION"]
    assert decl and decl[0]["location"] == f"{cb.file}:{cb.line}"
    assert "extends uvm_callback" in decl[0]["detail"]

    assert report.items == [cb]


def test_every_other_real_class_is_correctly_left_unclassified(demo_index):
    """The headline negative control: NONE of this fixture's six other real
    classes -- including the two `virtual class`-shaped ones whose own
    declared methods are ordinary UVM phase overrides -- is misclassified as
    callback/hook-shaped. svt_demo_driver in particular is exactly the case
    the phase-method exclusion in the structural fallback exists to catch:
    it is a real `virtual class` declaring only `virtual function
    build_phase(...)`/`virtual task run_phase(...)`, which would otherwise
    look structurally identical to a real extension point."""
    report = vche.extract_vip_callback_hooks(demo_index)
    assert set(report.unclassified_class_names) == {
        "svt_demo_cfg", "svt_demo_transaction", "svt_demo_base_sequence",
        "svt_demo_monitor", "svt_demo_driver", "svt_demo_agent",
    }
    assert report.ambiguous == []


def test_no_item_is_ever_project_proven_or_documented_without_real_corroboration(demo_index):
    report = vche.extract_vip_callback_hooks(demo_index)
    assert report.items, "fixture must actually classify something for this assertion to mean anything"
    for rec in report.items:
        assert rec.qualification == vche.INFERRED_FROM_NAMING
    assert report.counts_by_qualification == {vche.INFERRED_FROM_NAMING: len(report.items)}
    assert report.project_sources_scanned == 0
    assert report.example_sources_scanned == 0
    assert report.user_guide_references_scanned == 0


# ---------------------------------------------------------------------------
# 2. promotion rules, one at a time
# ---------------------------------------------------------------------------

def test_project_proven_requires_a_real_citation_in_project_source(demo_index, tmp_path):
    d, _ = _write(tmp_path, "project", "env.sv", "svt_demo_report_cb cb;\n")
    report = vche.extract_vip_callback_hooks(demo_index, project_sources=[d], project_relative_to=d)
    cb = _rec(report, "svt_demo_report_cb")
    assert cb.qualification == vche.PROJECT_PROVEN
    usage = [e for e in cb.evidence if e["kind"] == "PROJECT_USAGE"]
    assert usage and usage[0]["location"] == "env.sv:1"


def test_vip_example_matched_requires_a_real_citation_in_example_source(demo_index, tmp_path):
    d, _ = _write(tmp_path, "Examples", "basic_example.sv", "svt_demo_report_cb cb;\n")
    report = vche.extract_vip_callback_hooks(demo_index, example_sources=[d], example_relative_to=d)
    cb = _rec(report, "svt_demo_report_cb")
    assert cb.qualification == vche.VIP_EXAMPLE_MATCHED
    usage = [e for e in cb.evidence if e["kind"] == "VIP_EXAMPLE_USAGE"]
    assert usage and usage[0]["location"] == "basic_example.sv:1"


def test_vip_documented_uses_a_real_distilled_user_guide_reference(demo_index, tmp_path):
    guide_txt = tmp_path / "guide.txt"
    guide_txt.write_text(textwrap.dedent("""\
        1. Overview
        This document is a synthetic user-guide fixture for testing only.

        4.1 svt_demo_report_cb Callback Reference
        Describes the callback hook points
        """), encoding="utf-8")
    record = vud.distill_user_guide(guide_txt, tmp_path / "distilled")
    ref_md = record["distilled_reference"]["path"]
    assert Path(ref_md).exists()

    report = vche.extract_vip_callback_hooks(demo_index, user_guide_reference_md=[ref_md])
    cb = _rec(report, "svt_demo_report_cb")
    assert cb.qualification == vche.VIP_DOCUMENTED
    usage = [e for e in cb.evidence if e["kind"] == "VIP_USER_GUIDE_SECTION"]
    assert usage and "svt_demo_report_cb" in usage[0]["detail"]


def test_promotion_priority_project_over_documented_over_example(demo_index, tmp_path):
    proj_dir, _ = _write(tmp_path, "project", "env.sv", "svt_demo_report_cb cb;\n")
    ex_dir, _ = _write(tmp_path, "Examples", "ex.sv", "svt_demo_report_cb cb2;\n")
    guide_txt = tmp_path / "guide.txt"
    guide_txt.write_text(textwrap.dedent("""\
        1.1 svt_demo_report_cb Reference
        Describes the callback
        """), encoding="utf-8")
    record = vud.distill_user_guide(guide_txt, tmp_path / "distilled2")
    ref_md = record["distilled_reference"]["path"]

    report = vche.extract_vip_callback_hooks(
        demo_index,
        project_sources=[proj_dir], project_relative_to=proj_dir,
        example_sources=[ex_dir], example_relative_to=ex_dir,
        user_guide_reference_md=[ref_md],
    )
    cb = _rec(report, "svt_demo_report_cb")
    assert cb.qualification == vche.PROJECT_PROVEN


# ---------------------------------------------------------------------------
# 3. negative controls: ambiguity, both directions, and non-classification
# ---------------------------------------------------------------------------

def test_name_says_callback_but_inheritance_says_scenario_pattern_is_ambiguous(tmp_path):
    d, _ = _write(tmp_path, "vip", "evil.sv", textwrap.dedent("""\
        package evil_pkg;
          class svt_evil_hook extends uvm_sequence;
            virtual task body();
            endtask
          endclass
        endpackage
        """))
    index = vsi.build_symbol_index([d], "demo")
    report = vche.extract_vip_callback_hooks(index)
    assert report.status == "ONLY_AMBIGUOUS"
    assert report.items == []
    assert len(report.ambiguous) == 1
    amb = report.ambiguous[0]
    assert amb.class_name == "svt_evil_hook"
    assert amb.ir_type == vche.IR_AMBIGUOUS
    assert amb.qualification == vche.UNKNOWN
    assert amb.basis == "NAME_AND_INHERITANCE_DISAGREE"
    assert amb.name_category == vche.IR_VIP_CALLBACK_HOOK
    assert amb.inheritance_category == vce.IR_VIP_SCENARIO_PATTERN
    assert "svt_evil_hook" not in [r.class_name for r in report.items]


def test_inheritance_says_callback_but_name_says_scenario_pattern_is_ambiguous(tmp_path):
    d, _ = _write(tmp_path, "vip", "evil2.sv", textwrap.dedent("""\
        package evil2_pkg;
          class svt_evil_seq extends uvm_callback;
            virtual function void pre_body();
            endfunction
          endclass
        endpackage
        """))
    index = vsi.build_symbol_index([d], "demo")
    report = vche.extract_vip_callback_hooks(index)
    assert report.status == "ONLY_AMBIGUOUS"
    assert report.items == []
    amb = report.ambiguous[0]
    assert amb.class_name == "svt_evil_seq"
    assert amb.basis == "NAME_AND_INHERITANCE_DISAGREE"
    assert amb.name_category == vce.IR_VIP_SCENARIO_PATTERN
    assert amb.inheritance_category == vche.IR_VIP_CALLBACK_HOOK
    assert "UVM callback base class" in amb.reason


def test_class_matching_neither_heuristic_is_left_unclassified(tmp_path):
    d, _ = _write(tmp_path, "vip", "helper.sv", textwrap.dedent("""\
        package helper_pkg;
          class svt_helper_util extends uvm_object;
            bit enabled;
          endclass
        endpackage
        """))
    index = vsi.build_symbol_index([d], "demo")
    report = vche.extract_vip_callback_hooks(index)
    assert report.status == "NOTHING_CLASSIFIED"
    assert report.reason == "NO_CLASS_MATCHED_ANY_NAMING_OR_INHERITANCE_HEURISTIC"
    assert report.items == []
    assert report.ambiguous == []
    assert report.unclassified_class_names == ["svt_helper_util"]


def test_structural_extension_point_fallback_classifies_via_inheritance_only(tmp_path):
    """No callback-shaped name, no uvm_callback/uvm_callback_iter base -- but
    a real `virtual class` declaring a real, non-phase virtual method is
    still recognised as a real extension point, citing the real method
    declaration."""
    d, _ = _write(tmp_path, "vip", "ext.sv", textwrap.dedent("""\
        package ext_pkg;
          virtual class svt_demo_extension_base extends uvm_object;
            virtual function void on_custom_event(int id);
            endfunction
          endclass
        endpackage
        """))
    index = vsi.build_symbol_index([d], "demo")
    report = vche.extract_vip_callback_hooks(index)
    assert report.status == "CLASSIFIED"
    ext = _rec(report, "svt_demo_extension_base")
    assert ext.basis == "INHERITANCE_ONLY"
    assert ext.name_category is None
    assert ext.inheritance_category == vche.IR_VIP_CALLBACK_HOOK
    assert [m["name"] for m in ext.hook_methods] == ["on_custom_event"]
    method_ev = [e for e in ext.evidence if e["kind"] == "VIP_SYMBOL_INDEX_METHOD_DECLARATION"]
    assert method_ev and "on_custom_event" in method_ev[0]["detail"]


def test_structural_fallback_never_fires_on_a_virtual_class_with_only_phase_methods(tmp_path):
    """The required negative control for the structural heuristic: a
    `virtual class` whose ONLY virtual/extern methods are real UVM phase
    overrides must never be classified callback/hook-shaped -- proving the
    phase-name exclusion actually has detection power, independent of the
    shared fixture's own svt_demo_driver case."""
    d, _ = _write(tmp_path, "vip", "comp.sv", textwrap.dedent("""\
        package comp_pkg;
          virtual class svt_demo_component_base extends uvm_object;
            virtual function void build_phase(uvm_phase phase);
            endfunction
            virtual task run_phase(uvm_phase phase);
            endtask
          endclass
        endpackage
        """))
    index = vsi.build_symbol_index([d], "demo")
    report = vche.extract_vip_callback_hooks(index)
    assert report.status == "NOTHING_CLASSIFIED"
    assert report.items == []
    assert report.ambiguous == []
    assert report.unclassified_class_names == ["svt_demo_component_base"]


def test_empty_index_reports_not_available_never_a_clean_pass():
    empty = {
        "schema_version": "1.0", "generator": {"tool": "t", "version": "1.0"},
        "protocol": "demo", "roots": [],
        "stats": {"files_scanned": 0, "classes_indexed": 0, "methods_indexed": 0, "bytes_scanned": 0},
        "classes": [],
    }
    report = vche.extract_vip_callback_hooks(empty)
    assert report.status == "NOT_AVAILABLE"
    assert report.reason == "VIP_SYMBOL_INDEX_CONTAINS_NO_CLASSES"
    assert report.items == [] and report.ambiguous == []


def test_missing_index_file_raises_rather_than_reporting_a_clean_result(tmp_path):
    with pytest.raises(vche.VipCallbackHookExtractionError):
        vche.load_index_and_classify(tmp_path / "does_not_exist.json")


# ---------------------------------------------------------------------------
# 4. real CLI entry point
# ---------------------------------------------------------------------------

def test_cli_module_entrypoint_classifies_and_writes_artifact(demo_index, tmp_path):
    index_path = tmp_path / "index.json"
    vsi.save_symbol_index(demo_index, index_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.vip_callback_hook_extraction",
         "--index", str(index_path), "--out-dir", str(out_dir), "--json"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "CLASSIFIED"
    written = json.loads((out_dir / vche.CAPABILITY_EXTRACTION_REPORT_NAME).read_text(encoding="utf-8"))
    assert written["status"] == "CLASSIFIED"
    names = {item["class_name"] for item in written["items"]}
    assert names == {"svt_demo_report_cb"}


def test_cli_module_entrypoint_exits_2_on_missing_index(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.vip_callback_hook_extraction",
         "--index", str(tmp_path / "nope.json")],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "VipCallbackHookExtractionError" in proc.stdout or "does not exist" in proc.stdout
