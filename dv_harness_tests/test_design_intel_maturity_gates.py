"""Tests for dv_harness/design_intel_maturity_gates.py -- the composite
9.0 / 9.5 / 10.0 Design Intelligence maturity qualification gates.

Discipline, mirroring dv_harness_tests/test_subsystem_maturity_gate.py's own
(this module is a deliberate SIBLING of subsystem_maturity_gate.py -- it is
never imported and never modified here):

  1. The condition/level TABLE is self-consistent: no duplicate condition id,
     every level's requirement set is a real subset of the level above it,
     every declared `fact_source` resolves through the real import system --
     with a negative control proving a renamed fact_source is refused rather
     than silently reported MET -- and the condition/verdict vocabulary
     shares no token with `models.Status`.
  2. Every condition is driven against REAL evidence produced by the REAL
     function it cites:
       - architecture_ir_built: a real tiny RTL file run through
         `design_architecture_ir.build_architecture_ir()` via the real
         `verible-verilog-syntax` binary.
       - source_registry_current: a real file's real sha256 (via
         `design_source_inventory.compute_source_hash()`), round-tripped
         through `build_source_registry()`.
       - intent_extracted_with_citations / constraints_extracted_with_units:
         real schema-valid `dut_intent.schema.json` / `constraints.schema.json`
         documents run through `design_intent.validate_intent()` /
         `validate_constraints()`.
       - knowledge_correlation_clean: real `design_knowledge_correlation
         .correlate()` calls over a real sources list.
       - source_discovery_completeness: always NOT_MEASURABLE, asserted
         never to block QUALIFIED at 10.0 while still appearing under
         disclosed_caveats.
  3. The composed VERDICT rule is exercised end to end across one evolving
     real project at all three levels, plus its own negative controls: a
     real defect makes the level NOT_QUALIFIED (never merely
     INCOMPLETE_EVIDENCE), and a level given no evidence at all is
     INCOMPLETE_EVIDENCE (never NOT_QUALIFIED, since nothing was proven
     wrong).
  4. Reading is never a mutating act: a full evaluate() run over a real RTL
     tree changes no file on disk.
  5. Both real CLI entry points (`conditions`, `evaluate`) are driven as
     real subprocesses.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dv_harness import design_intel_maturity_gates as dimg  # noqa: E402
from dv_harness import design_architecture_ir as dair  # noqa: E402
from dv_harness import design_source_inventory as dsi  # noqa: E402
from dv_harness import design_intent as di  # noqa: E402
from dv_harness import design_knowledge_correlation as dkc  # noqa: E402

requires_verible = pytest.mark.skipif(
    shutil.which("verible-verilog-syntax") is None,
    reason="verible-verilog-syntax not on PATH")


# ---------------------------------------------------------------------------
# real-evidence fixtures
# ---------------------------------------------------------------------------

CLEAN_RTL = """\
module usb_link_ctrl (
  input  wire clk,
  input  wire rst_n,
  output reg  link_up
);
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) link_up <= 1'b0;
    else        link_up <= 1'b1;
  end
endmodule
"""


def _valid_intent_doc() -> dict:
    return {
        "schema_version": "1.0",
        "dut_name": "usb_link_ctrl",
        "source": {"document": "usb_link_ctrl_controller_guide.pdf", "section": "3.2"},
        "modes": [],
        "state_machine": {
            "states": [
                {"name": "RESET", "description": "link held in reset", "is_initial": True},
                {"name": "LINK_UP", "description": "link is up"},
            ],
            "transitions": [
                {"from": "RESET", "to": "LINK_UP", "trigger": "rst_n deasserted",
                 "basis": {"document": "usb_link_ctrl_controller_guide.pdf", "section": "3.2.1"}},
            ],
        },
        "legal_drop_conditions": [
            {"id": "DROP-001", "description": "reset-in-flight drop",
             "applies_when": "rst_n asserted mid-transfer", "mode": None,
             "basis": {"document": "usb_link_ctrl_controller_guide.pdf", "section": "4.1"}},
        ],
        "backpressure_conditions": [
            {"id": "BP-001", "description": "link-not-up stall",
             "applies_when": "link_up == 0", "mode": None,
             "basis": {"document": "usb_link_ctrl_controller_guide.pdf", "section": "4.2"}},
        ],
        "ordering_rules": [
            {"scope": "whole interface", "guarantee": "strict_in_order",
             "basis": {"document": "usb_link_ctrl_controller_guide.pdf", "section": "5.0"}},
        ],
    }


def _valid_constraints_doc() -> dict:
    return {
        "schema_version": "1.0",
        "ip_name": "usb_link_ctrl",
        "source": {"document": "usb_link_ctrl_user_guide.pdf", "section": "2.1"},
        "timing_constraints": [
            {"id": "T-001", "parameter": "tRESET_WIDTH", "description": "minimum reset pulse width",
             "min": 20.0, "typ": None, "max": None, "unit": "ns",
             "basis": {"document": "usb_link_ctrl_user_guide.pdf", "section": "2.1.1"}},
        ],
        "electrical_limits": [
            {"id": "E-001", "parameter": "VDD", "description": "core supply voltage",
             "min": 0.9, "max": 1.1, "unit": "V",
             "basis": {"document": "usb_link_ctrl_user_guide.pdf", "section": "2.2"}},
        ],
        "untestable_items": [],
    }


def _clean_knowledge_sources() -> list:
    return [
        {"source_id": "spec-1", "source_kind": "controller_doc", "role": dkc.ROLE_SPEC_DECLARATION,
         "facts": [{"fact_key": "reset_active_level", "value": "active_low",
                    "evidence_ref": "usb_link_ctrl_controller_guide.pdf#3.2"}]},
        {"source_id": "rtl-1", "source_kind": "rtl_extraction", "role": dkc.ROLE_IMPLEMENTATION_EVIDENCE,
         "facts": [{"fact_key": "reset_active_level", "value": "active_low",
                    "evidence_ref": "usb_link_ctrl.v:5"}]},
    ]


def _conflicting_knowledge_sources() -> list:
    return [
        {"source_id": "spec-1", "source_kind": "controller_doc", "role": dkc.ROLE_SPEC_DECLARATION,
         "facts": [{"fact_key": "reset_active_level", "value": "active_low"}]},
        {"source_id": "rtl-1", "source_kind": "rtl_extraction", "role": dkc.ROLE_IMPLEMENTATION_EVIDENCE,
         "facts": [{"fact_key": "reset_active_level", "value": "active_high"}]},
    ]


# ---------------------------------------------------------------------------
# 1. table self-consistency
# ---------------------------------------------------------------------------

def test_no_duplicate_condition_ids():
    ids = [c.condition_id for c in dimg.CONDITIONS]
    assert len(ids) == len(set(ids))


def test_levels_are_strictly_monotonic():
    dimg.assert_levels_are_monotonic()
    prior = set()
    for level in dimg.MATURITY_LEVELS:
        current = set(dimg.LEVEL_REQUIREMENTS[level])
        assert prior <= current, f"{level} dropped a condition required at a lower level"
        prior = current
    assert prior == set(dimg.LEVEL_REQUIREMENTS[dimg.LEVEL_10_0])


def test_fact_sources_all_resolve():
    resolved = dimg.assert_fact_sources_resolvable()
    assert resolved
    for spec in dimg.CONDITIONS:
        for dotted in spec.fact_source:
            assert dotted in resolved


def test_a_renamed_fact_source_is_refused_not_silently_met(monkeypatch):
    bad_spec = dimg.ConditionSpec(
        "bogus", "test-only", ("dv_harness.design_architecture_ir.THIS_DOES_NOT_EXIST",),
        dimg._evaluate_architecture_ir_built)
    monkeypatch.setitem(dimg.CONDITIONS_BY_ID, "bogus", bad_spec)
    monkeypatch.setattr(dimg, "CONDITIONS", dimg.CONDITIONS + (bad_spec,))
    with pytest.raises(dimg.DesignIntelMaturityGateError) as exc:
        dimg.assert_fact_sources_resolvable()
    assert exc.value.reason == "FACT_SOURCE_ATTRIBUTE_MISSING"


def test_vocabulary_disjoint_from_models_status():
    dimg.assert_no_verification_verdict_vocabulary()


def test_vocabulary_collision_is_actually_detected(monkeypatch):
    monkeypatch.setattr(dimg, "CONDITION_STATUSES", dimg.CONDITION_STATUSES + ("PASS",))
    with pytest.raises(dimg.DesignIntelMaturityGateError) as exc:
        dimg.assert_no_verification_verdict_vocabulary()
    assert exc.value.reason == "VERDICT_VOCABULARY_COLLIDES_WITH_MODELS_STATUS"


def test_this_module_never_imports_subsystem_maturity_gate():
    import ast
    src = Path(dimg.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "subsystem_maturity_gate"
            assert node.module != "dv_harness.subsystem_maturity_gate"
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "subsystem_maturity_gate" not in alias.name


# ---------------------------------------------------------------------------
# 2. per-condition real evidence
# ---------------------------------------------------------------------------

@requires_verible
def test_architecture_ir_built_met_on_real_clean_rtl(tmp_path):
    f = tmp_path / "usb_link_ctrl.v"
    f.write_text(CLEAN_RTL, encoding="utf-8")
    result = dimg._evaluate_architecture_ir_built(tmp_path, dimg.GateInputs(rtl_files=[f]))
    assert result.status == dimg.MET
    assert result.evidence["module_count"] == 1


@requires_verible
def test_architecture_ir_built_unmet_on_real_duplicate_module_name(tmp_path):
    f1 = tmp_path / "a.v"
    f2 = tmp_path / "b.v"
    f1.write_text(CLEAN_RTL, encoding="utf-8")
    f2.write_text(CLEAN_RTL, encoding="utf-8")  # same module name, second file
    result = dimg._evaluate_architecture_ir_built(tmp_path, dimg.GateInputs(rtl_files=[f1, f2]))
    assert result.status == dimg.UNMET
    assert "more than one" in result.reason.lower()
    assert result.evidence["duplicate_modules"]


def test_architecture_ir_built_not_available_with_no_rtl_files(tmp_path):
    result = dimg._evaluate_architecture_ir_built(tmp_path, dimg.GateInputs())
    assert result.status == dimg.NOT_AVAILABLE


def test_architecture_ir_built_not_available_on_unrunnable_verible(tmp_path):
    f = tmp_path / "usb_link_ctrl.v"
    f.write_text(CLEAN_RTL, encoding="utf-8")
    ir = dair.build_architecture_ir([f], verible_bin="verible-verilog-syntax-does-not-exist")
    result = dimg._evaluate_architecture_ir_built(tmp_path, dimg.GateInputs(architecture_ir=ir))
    assert result.status == dimg.NOT_AVAILABLE


def test_source_registry_current_met_on_real_confirmed_hash(tmp_path):
    f = tmp_path / "usb_link_ctrl.v"
    f.write_text(CLEAN_RTL, encoding="utf-8")
    real_hash = dsi.compute_source_hash(f)["hash"]
    assert real_hash
    entries = [dsi.SourceEntry(source_id="rtl-1", type="rtl", path=str(f),
                                authority_hint="dut_rtl", recorded_hash=real_hash)]
    result = dimg._evaluate_source_registry_current(tmp_path, dimg.GateInputs(source_entries=entries))
    assert result.status == dimg.MET
    assert result.evidence["summary"][dsi.STATUS_CURRENT] == 1


def test_source_registry_current_unmet_on_real_stale_hash(tmp_path):
    f = tmp_path / "usb_link_ctrl.v"
    f.write_text(CLEAN_RTL, encoding="utf-8")
    entries = [dsi.SourceEntry(source_id="rtl-1", type="rtl", path=str(f),
                                recorded_hash="0" * 64)]  # a real but wrong recorded hash
    result = dimg._evaluate_source_registry_current(tmp_path, dimg.GateInputs(source_entries=entries))
    assert result.status == dimg.UNMET
    assert "STALE" in result.reason or "0" in result.reason


def test_source_registry_current_not_available_with_no_entries(tmp_path):
    result = dimg._evaluate_source_registry_current(tmp_path, dimg.GateInputs())
    assert result.status == dimg.NOT_AVAILABLE


def test_intent_extracted_with_citations_met_on_real_valid_doc(tmp_path):
    result = dimg._evaluate_intent_extracted_with_citations(
        tmp_path, dimg.GateInputs(intent_doc=_valid_intent_doc()))
    assert result.status == dimg.MET
    assert result.evidence["state_count"] == 2


def test_intent_extracted_with_citations_unmet_on_undeclared_transition_state(tmp_path):
    doc = _valid_intent_doc()
    doc["state_machine"]["transitions"][0]["to"] = "NO_SUCH_STATE"
    result = dimg._evaluate_intent_extracted_with_citations(tmp_path, dimg.GateInputs(intent_doc=doc))
    assert result.status == dimg.UNMET


def test_intent_extracted_with_citations_unmet_on_missing_citation(tmp_path):
    doc = _valid_intent_doc()
    del doc["legal_drop_conditions"][0]["basis"]
    result = dimg._evaluate_intent_extracted_with_citations(tmp_path, dimg.GateInputs(intent_doc=doc))
    assert result.status == dimg.UNMET


def test_intent_extracted_with_citations_not_available_with_no_doc(tmp_path):
    result = dimg._evaluate_intent_extracted_with_citations(tmp_path, dimg.GateInputs())
    assert result.status == dimg.NOT_AVAILABLE


def test_constraints_extracted_with_units_met_on_real_valid_doc(tmp_path):
    result = dimg._evaluate_constraints_extracted_with_units(
        tmp_path, dimg.GateInputs(constraints_doc=_valid_constraints_doc()))
    assert result.status == dimg.MET
    assert result.evidence["timing_count"] == 1


def test_constraints_extracted_with_units_unmet_on_missing_unit(tmp_path):
    doc = _valid_constraints_doc()
    doc["timing_constraints"][0]["unit"] = None
    result = dimg._evaluate_constraints_extracted_with_units(tmp_path, dimg.GateInputs(constraints_doc=doc))
    assert result.status == dimg.UNMET


def test_constraints_extracted_with_units_not_available_with_no_doc(tmp_path):
    result = dimg._evaluate_constraints_extracted_with_units(tmp_path, dimg.GateInputs())
    assert result.status == dimg.NOT_AVAILABLE


def test_knowledge_correlation_clean_met_on_real_agreeing_sources(tmp_path):
    result = dimg._evaluate_knowledge_correlation_clean(
        tmp_path, dimg.GateInputs(knowledge_sources=_clean_knowledge_sources()))
    assert result.status == dimg.MET


def test_knowledge_correlation_clean_unmet_on_real_conflict(tmp_path):
    result = dimg._evaluate_knowledge_correlation_clean(
        tmp_path, dimg.GateInputs(knowledge_sources=_conflicting_knowledge_sources()))
    assert result.status == dimg.UNMET
    assert result.evidence["summary"]["conflict_count"] == 1


def test_knowledge_correlation_clean_unmet_on_real_gap(tmp_path):
    sources = [
        {"source_id": "spec-1", "source_kind": "controller_doc", "role": dkc.ROLE_SPEC_DECLARATION,
         "facts": []},
    ]
    expected = [{"fact_key": "reset_active_level", "reason": "required for scoreboard exemptions"}]
    result = dimg._evaluate_knowledge_correlation_clean(
        tmp_path, dimg.GateInputs(knowledge_sources=sources, knowledge_expected_facts=expected))
    assert result.status == dimg.UNMET
    assert result.evidence["summary"]["gap_count"] == 1


def test_knowledge_correlation_clean_not_available_with_no_sources(tmp_path):
    result = dimg._evaluate_knowledge_correlation_clean(tmp_path, dimg.GateInputs())
    assert result.status == dimg.NOT_AVAILABLE


def test_knowledge_correlation_clean_not_available_on_malformed_sources(tmp_path):
    result = dimg._evaluate_knowledge_correlation_clean(
        tmp_path, dimg.GateInputs(knowledge_sources=[{"source_kind": "x"}]))  # missing source_id
    assert result.status == dimg.NOT_AVAILABLE


def test_source_discovery_completeness_always_not_measurable(tmp_path):
    result = dimg._evaluate_source_discovery_completeness(tmp_path, dimg.GateInputs())
    assert result.status == dimg.NOT_MEASURABLE
    result2 = dimg._evaluate_source_discovery_completeness(
        tmp_path, dimg.GateInputs(source_entries=[dsi.SourceEntry(source_id="x", type="rtl")]))
    assert result2.status == dimg.NOT_MEASURABLE


# ---------------------------------------------------------------------------
# 3. end-to-end verdict rule over one evolving real project
# ---------------------------------------------------------------------------

def test_incomplete_evidence_with_no_evidence_supplied_at_all(tmp_path):
    for level in dimg.MATURITY_LEVELS:
        report = dimg.derive_maturity_gate(level, tmp_path, dimg.GateInputs())
        assert report["verdict"] == dimg.INCOMPLETE_EVIDENCE, level
        assert not report["unmet_conditions"]


@requires_verible
def test_qualified_at_9_0_with_real_clean_evidence(tmp_path):
    f = tmp_path / "usb_link_ctrl.v"
    f.write_text(CLEAN_RTL, encoding="utf-8")
    inputs = dimg.GateInputs(rtl_files=[f], intent_doc=_valid_intent_doc())
    report = dimg.derive_maturity_gate(dimg.LEVEL_9_0, tmp_path, inputs)
    assert report["verdict"] == dimg.QUALIFIED, report


@requires_verible
def test_qualified_at_9_5_with_real_clean_evidence(tmp_path):
    f = tmp_path / "usb_link_ctrl.v"
    f.write_text(CLEAN_RTL, encoding="utf-8")
    real_hash = dsi.compute_source_hash(f)["hash"]
    inputs = dimg.GateInputs(
        rtl_files=[f], intent_doc=_valid_intent_doc(), constraints_doc=_valid_constraints_doc(),
        source_entries=[dsi.SourceEntry(source_id="rtl-1", type="rtl", path=str(f),
                                         recorded_hash=real_hash)])
    report = dimg.derive_maturity_gate(dimg.LEVEL_9_5, tmp_path, inputs)
    assert report["verdict"] == dimg.QUALIFIED, report


@requires_verible
def test_qualified_at_10_0_with_disclosed_caveat_never_blocking(tmp_path):
    f = tmp_path / "usb_link_ctrl.v"
    f.write_text(CLEAN_RTL, encoding="utf-8")
    real_hash = dsi.compute_source_hash(f)["hash"]
    inputs = dimg.GateInputs(
        rtl_files=[f], intent_doc=_valid_intent_doc(), constraints_doc=_valid_constraints_doc(),
        source_entries=[dsi.SourceEntry(source_id="rtl-1", type="rtl", path=str(f),
                                         recorded_hash=real_hash)],
        knowledge_sources=_clean_knowledge_sources())
    report = dimg.derive_maturity_gate(dimg.LEVEL_10_0, tmp_path, inputs)
    assert report["verdict"] == dimg.QUALIFIED, report
    assert report["disclosed_caveats"] == [dimg.COND_SOURCE_DISCOVERY_COMPLETENESS]
    assert dimg.COND_SOURCE_DISCOVERY_COMPLETENESS not in report["unmet_conditions"]
    assert dimg.COND_SOURCE_DISCOVERY_COMPLETENESS not in report["unavailable_conditions"]


@requires_verible
def test_not_qualified_never_softened_to_incomplete_evidence_on_a_real_defect(tmp_path):
    f1 = tmp_path / "a.v"
    f2 = tmp_path / "b.v"
    f1.write_text(CLEAN_RTL, encoding="utf-8")
    f2.write_text(CLEAN_RTL, encoding="utf-8")  # real duplicate module name -> UNMET
    inputs = dimg.GateInputs(rtl_files=[f1, f2], intent_doc=_valid_intent_doc())
    report = dimg.derive_maturity_gate(dimg.LEVEL_9_0, tmp_path, inputs)
    assert report["verdict"] == dimg.NOT_QUALIFIED
    assert dimg.COND_ARCHITECTURE_IR_BUILT in report["unmet_conditions"]


def test_unknown_level_raises():
    with pytest.raises(dimg.DesignIntelMaturityGateError):
        dimg.derive_maturity_gate("11.0", ".", dimg.GateInputs())


# ---------------------------------------------------------------------------
# 4. reading never mutates the project
# ---------------------------------------------------------------------------

@requires_verible
def test_evaluate_never_writes_to_disk(tmp_path):
    f = tmp_path / "usb_link_ctrl.v"
    f.write_text(CLEAN_RTL, encoding="utf-8")
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    inputs = dimg.GateInputs(rtl_files=[f], intent_doc=_valid_intent_doc(),
                              constraints_doc=_valid_constraints_doc())
    dimg.derive_maturity_gate(dimg.LEVEL_9_5, tmp_path, inputs)
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert before == after


# ---------------------------------------------------------------------------
# 5. real CLI subprocess invocations
# ---------------------------------------------------------------------------

def test_cli_conditions_verb_real_subprocess():
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.design_intel_maturity_gates", "conditions"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert dimg.COND_ARCHITECTURE_IR_BUILT in proc.stdout
    assert dimg.COND_SOURCE_DISCOVERY_COMPLETENESS in proc.stdout


def test_cli_evaluate_verb_incomplete_evidence_real_subprocess(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.design_intel_maturity_gates",
         "evaluate", "--level", "9.0", "--root", str(tmp_path), "--json"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == dimg.INCOMPLETE_EVIDENCE


@requires_verible
def test_cli_evaluate_verb_qualified_real_subprocess(tmp_path):
    rtl = tmp_path / "usb_link_ctrl.v"
    rtl.write_text(CLEAN_RTL, encoding="utf-8")
    intent_path = tmp_path / "intent.json"
    intent_path.write_text(json.dumps(_valid_intent_doc()), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.design_intel_maturity_gates",
         "evaluate", "--level", "9.0", "--root", str(tmp_path),
         "--rtl-file", str(rtl), "--intent-doc", str(intent_path), "--json"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == dimg.QUALIFIED
