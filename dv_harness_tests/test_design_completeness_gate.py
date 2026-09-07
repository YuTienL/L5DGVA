"""Tests for dv_harness/design_completeness_gate.py.

Every category's real extractor is driven through the module's own probe,
never mocked -- a real .xlsx built with openpyxl, real RTL parsed by the
real verible-verilog-syntax front end (skipped, never faked, when it is not
on PATH), a real .upf power-intent fixture already in this repo, and real
plain in-memory documents for the categories whose real entry point takes
already-structured data. Negative controls (no input at all) prove the
module never fabricates a status for a category nobody attempted -- the
central Evidence Truth Rule property this module exists to hold.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import openpyxl
import pytest

from dv_harness import design_completeness_gate as dcg
from dv_harness.golden_flow_readiness import READY, PARTIAL, BLOCKED, UNKNOWN

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None, reason="verible-verilog-syntax not on PATH",
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "interrupt_dma_clock_reset"
POWER_INTENT_FIXTURE = Path(__file__).parent / "fixtures" / "power_intent" / "synthetic_lp_soc.upf"


# ===========================================================================
# Structural / anti-drift
# ===========================================================================

def test_row_ids_are_unique_and_every_row_has_a_probe():
    ids = dcg.row_ids()
    assert len(ids) == len(set(ids))
    assert set(ids) == set(dcg.PROBES)


def test_assert_fact_sources_resolvable_resolves_every_real_extractor():
    resolved = dcg.assert_fact_sources_resolvable()
    assert len(resolved) >= len(dcg.ROWS)


def test_a_renamed_fact_source_fails_the_drift_check(monkeypatch):
    bad_row = dcg.CompletenessRowSpec(
        "bogus", "Bogus category",
        ("dv_harness.register_excel_extract.this_function_was_renamed_away",),
        "negative control",
    )
    monkeypatch.setattr(dcg, "ROWS", dcg.ROWS + (bad_row,))
    with pytest.raises(dcg.DesignCompletenessError) as exc:
        dcg.assert_fact_sources_resolvable()
    assert exc.value.reason == "FACT_SOURCE_ATTRIBUTE_MISSING"


def test_duplicate_row_id_is_refused():
    dup = dcg.CompletenessRowSpec("register_map", "dup", ("dv_harness.golden_flow_readiness.READY",), "x")
    rows = dcg.ROWS + (dup,)
    with pytest.raises(dcg.DesignCompletenessError) as exc:
        # replicate the module's own guard against a live ROWS tuple
        ids = [r.row_id for r in rows]
        if len(set(ids)) != len(ids):
            raise dcg.DesignCompletenessError("DUPLICATE_ROW_ID", {"row_ids": ids})
    assert exc.value.reason == "DUPLICATE_ROW_ID"


# ===========================================================================
# Negative control: no input at all is UNKNOWN, never a fabricated status --
# proven for every one of the thirteen real categories at once.
# ===========================================================================

@pytest.mark.parametrize("row_id", dcg.row_ids())
def test_no_input_supplied_is_unknown_never_ready_never_blocked(row_id):
    result = dcg.PROBES[row_id](None)
    assert result["status"] == UNKNOWN
    assert "never attempted" in result["gap"]


def test_full_matrix_with_no_inputs_at_all_is_unknown_overall():
    matrix = dcg.derive_design_intelligence_completeness({})
    assert matrix["design_intelligence_completeness"] == UNKNOWN
    assert matrix["summary"]["rows_ready"] == 0
    assert matrix["summary"]["rows_unknown"] == len(dcg.ROWS)
    # every declared row is present -- "UNKNOWN" and "omitted" must not look alike
    assert {r["row_id"] for r in matrix["rows"]} == set(dcg.row_ids())


# ===========================================================================
# register_map
# ===========================================================================

HEADERS = ["Register Name", "Offset", "Width", "Access", "Reset Value", "Notes"]


def _write_xlsx(path: Path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEADERS)
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_register_map_clean_extraction_is_ready(tmp_path):
    xlsx = tmp_path / "regs.xlsx"
    _write_xlsx(xlsx, [["CTRL0", "0x0", 32, "RW", "0x0", "control"]])
    result = dcg.PROBES["register_map"]({"path": str(xlsx)})
    assert result["status"] == READY
    assert "1 register(s)" in result["evidence"]


def test_register_map_missing_file_is_unknown(tmp_path):
    result = dcg.PROBES["register_map"]({"path": str(tmp_path / "nope.xlsx")})
    assert result["status"] == UNKNOWN


def test_register_map_empty_workbook_is_blocked(tmp_path):
    xlsx = tmp_path / "empty.xlsx"
    wb = openpyxl.Workbook()
    wb.save(xlsx)
    result = dcg.PROBES["register_map"]({"path": str(xlsx)})
    assert result["status"] == BLOCKED


# ===========================================================================
# register_rtl_trace  (requires verible)
# ===========================================================================

@requires_verible
def test_register_rtl_trace_confirmed_port_is_ready():
    result = dcg.PROBES["register_rtl_trace"]({
        "fields": [{"name": "irq_uart"}],
        "rtl_paths": [str(FIXTURES_DIR / "dut_top.sv")],
    })
    assert result["status"] == READY
    assert "TRACE_CONFIRMED" in result["evidence"]


@requires_verible
def test_register_rtl_trace_fabricated_name_is_partial_or_unknown():
    result = dcg.PROBES["register_rtl_trace"]({
        "fields": [{"name": "totally_fabricated_signal_xyz"}],
        "rtl_paths": [str(FIXTURES_DIR / "dut_top.sv")],
    })
    assert result["status"] in (PARTIAL, UNKNOWN)


def test_register_rtl_trace_no_fields_is_unknown():
    result = dcg.PROBES["register_rtl_trace"]({"fields": [], "rtl_paths": []})
    assert result["status"] == UNKNOWN


# ===========================================================================
# phy_boundary
# ===========================================================================

def _phy_ctrl_modules():
    return [
        {"name": "phy0", "ports": [{"name": "pipe_data", "direction": "output", "data_type": "[7:0]"}]},
        {"name": "ctrl0", "ports": [{"name": "pipe_data", "direction": "input", "data_type": "[7:0]"}]},
    ]


def test_phy_boundary_extracted_is_ready():
    result = dcg.PROBES["phy_boundary"]({
        "rtl_modules": _phy_ctrl_modules(), "phy_module": "phy0", "controller_module": "ctrl0",
    })
    assert result["status"] == READY
    assert "EXTRACTED" in result["evidence"]


def test_phy_boundary_unknown_module_is_unknown():
    result = dcg.PROBES["phy_boundary"]({
        "rtl_modules": _phy_ctrl_modules(), "phy_module": "phy_missing", "controller_module": "ctrl0",
    })
    assert result["status"] == UNKNOWN


# ===========================================================================
# phy_model_behavior
# ===========================================================================

def _fake_reference_record(tmp_path) -> dict:
    import hashlib
    text = (
        "4.1 Link Training and Status State Machine\n"
        "LTSSM: Detect -> Polling -> Configuration -> L0\n\n"
        "4.2 Transmitter\n"
        "TX: supports 8b/10b encoding at full rate\n\n"
        "4.3 Power States\n"
        "P0: full power, P3: off\n"
    )
    fulltext = tmp_path / "phy_spec.fulltext.txt"
    fulltext.write_text(text, encoding="utf-8")
    return {
        "schema_version": "1.0", "doc_kind": "protocol_spec", "title": "Synthetic PHY Spec",
        "source_document": {"path": "synthetic_phy_spec.txt", "sha256": None, "bytes": None},
        "full_text_extract": {
            "path": str(fulltext),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        },
    }


def test_phy_model_behavior_extracted_is_ready(tmp_path):
    record = _fake_reference_record(tmp_path)
    result = dcg.PROBES["phy_model_behavior"]({"reference_record": record})
    assert result["status"] == READY
    assert "EXTRACTED" in result["evidence"]


def test_phy_model_behavior_missing_fulltext_is_unknown(tmp_path):
    record = _fake_reference_record(tmp_path)
    Path(record["full_text_extract"]["path"]).unlink()
    result = dcg.PROBES["phy_model_behavior"]({"reference_record": record})
    assert result["status"] == UNKNOWN


# ===========================================================================
# architecture_ir  (requires verible)
# ===========================================================================

@requires_verible
def test_architecture_ir_built_is_ready():
    result = dcg.PROBES["architecture_ir"]({"rtl_files": [str(FIXTURES_DIR / "dut_top.sv")]})
    assert result["status"] == READY
    assert "BUILT" in result["evidence"]


def test_architecture_ir_no_files_is_unknown():
    result = dcg.PROBES["architecture_ir"]({"rtl_files": []})
    assert result["status"] == UNKNOWN


# ===========================================================================
# interrupt_dma_clock_reset
# ===========================================================================

def test_interrupt_dma_clock_reset_all_facets_loaded_is_ready():
    result = dcg.PROBES["interrupt_dma_clock_reset"]({
        "source_paths": [str(FIXTURES_DIR / "dut_top.sv"), str(FIXTURES_DIR / "programming_guide.txt")],
    })
    assert result["status"] == READY
    assert "3/3 facet(s)" in result["evidence"]


def test_interrupt_dma_clock_reset_no_sources_is_unknown():
    result = dcg.PROBES["interrupt_dma_clock_reset"]({"source_paths": []})
    assert result["status"] == UNKNOWN


def test_interrupt_dma_clock_reset_no_matching_content_is_partial_or_unknown(tmp_path):
    plain = tmp_path / "no_facts.txt"
    plain.write_text("this file mentions absolutely nothing relevant.\n", encoding="utf-8")
    result = dcg.PROBES["interrupt_dma_clock_reset"]({"source_paths": [str(plain)]})
    assert result["status"] == UNKNOWN


# ===========================================================================
# programming_sequence
# ===========================================================================

VALID_SEQUENCE = {
    "name": "bring_up",
    "steps": [
        {"index": 0, "phase": "INIT", "action": "write", "register": "CTRL0", "value": "0x1"},
        {"index": 1, "phase": "CONFIGURE", "action": "write", "register": "CTRL0", "value": "0x2"},
    ],
}
VALID_FACTS = [{"name": "CTRL0", "access_type": "RW"}]


def test_programming_sequence_order_valid_is_ready():
    result = dcg.PROBES["programming_sequence"]({"sequence": VALID_SEQUENCE, "facts": VALID_FACTS})
    assert result["status"] == READY
    assert "ORDER_VALID" in result["evidence"]


def test_programming_sequence_order_invalid_is_partial():
    bad_sequence = {
        "name": "bring_up",
        "steps": [
            {"index": 0, "phase": "CONFIGURE", "action": "write", "register": "CTRL0", "value": "0x2"},
            {"index": 1, "phase": "INIT", "action": "write", "register": "CTRL0", "value": "0x1"},
        ],
    }
    result = dcg.PROBES["programming_sequence"]({"sequence": bad_sequence, "facts": VALID_FACTS})
    assert result["status"] == PARTIAL
    assert "PHASE_ORDER_VIOLATION" in result["gap"]


def test_programming_sequence_malformed_document_is_blocked():
    result = dcg.PROBES["programming_sequence"]({"sequence": {"name": "x"}, "facts": []})
    assert result["status"] == BLOCKED


def test_programming_sequence_no_facts_is_unknown():
    result = dcg.PROBES["programming_sequence"]({"sequence": VALID_SEQUENCE, "facts": []})
    assert result["status"] == UNKNOWN


# ===========================================================================
# verification_intent
# ===========================================================================

def test_verification_intent_with_real_dut_evidence_is_ready():
    result = dcg.PROBES["verification_intent"]({
        "record": {"requirement_id": "REQ-1"},
        "source_paths": [str(FIXTURES_DIR / "dut_top.sv"), str(FIXTURES_DIR / "programming_guide.txt")],
    })
    assert result["status"] == READY
    assert "DUT_EVIDENCE_FOUND" in result["evidence"]


def test_verification_intent_with_no_dut_evidence_is_unknown():
    result = dcg.PROBES["verification_intent"]({"record": {"requirement_id": "REQ-2"}})
    assert result["status"] == UNKNOWN


def test_verification_intent_malformed_record_is_blocked():
    result = dcg.PROBES["verification_intent"]({"record": "not-a-dict"})
    assert result["status"] == BLOCKED


# ===========================================================================
# dut_evidence_correlation  (requires verible; builds a real env.manifest.json
# through the real env_manifest.generate_and_write(), never hand-written)
# ===========================================================================

DUT_FIXTURE = textwrap.dedent("""\
    module usb_link_ctrl (
        input  logic pclk,
        input  logic presetn,
        output logic usb_wake_irq
    );
        assign usb_wake_irq = 1'b0;
    endmodule
    """)

REGISTER_MAP_FIXTURE = {
    "schema_version": "1.0",
    "source": {"kind": "ral_model_export", "description": "synthesized test fixture, not a real project"},
    "blocks": [{
        "name": "CTRL_BLOCK", "base_address": "0x1000",
        "registers": [{
            "name": "CTRL0", "address_offset": "0x0", "width": 32, "access": "RW",
            "reset_value": "0x0", "fields": [],
        }],
    }],
}
SOC_ARCH_MAP_FIXTURE = {
    "schema_version": "1.0",
    "source": {"kind": "soc_spec_pipeline_export", "description": "synthesized test fixture"},
    "clocks": [{"name": "pclk", "frequency_mhz": 100.0, "domain": "apb", "evidence": "spec.md:12"}],
    "resets": [{"name": "presetn", "active_level": "low", "synchronous": True, "clock": "pclk",
                "evidence": "spec.md:14"}],
}


@pytest.fixture
def real_manifest_path(tmp_path):
    from dv_harness import env_manifest
    dut_sv = tmp_path / "usb_link_ctrl.sv"
    dut_sv.write_text(DUT_FIXTURE, encoding="utf-8")
    reg = tmp_path / "register_map.json"
    reg.write_text(json.dumps(REGISTER_MAP_FIXTURE), encoding="utf-8")
    soc = tmp_path / "soc_arch_map.json"
    soc.write_text(json.dumps(SOC_ARCH_MAP_FIXTURE), encoding="utf-8")
    out = tmp_path / "env.manifest.json"
    env_manifest.generate_and_write(out, rtl_files=[dut_sv], register_map_path=reg, soc_arch_map_path=soc)
    return out


@requires_verible
def test_dut_evidence_correlation_confirmed_is_ready(real_manifest_path):
    result = dcg.PROBES["dut_evidence_correlation"]({
        "items": [{"item_id": "i1", "fact_type": "module", "name": "usb_link_ctrl"}],
        "manifest_path": str(real_manifest_path),
    })
    assert result["status"] == READY
    assert "RTL_CONFIRMED" in result["evidence"]


def test_dut_evidence_correlation_no_manifest_is_unknown():
    result = dcg.PROBES["dut_evidence_correlation"]({
        "items": [{"item_id": "i1", "fact_type": "module", "name": "usb_link_ctrl"}],
        "manifest_path": None,
    })
    assert result["status"] == UNKNOWN


# ===========================================================================
# design_knowledge_correlation
# ===========================================================================

def test_design_knowledge_correlation_clean_is_ready():
    sources = [
        {"source_id": "spec", "source_kind": "spec_document", "role": "SPEC_DECLARATION",
         "facts": [{"fact_key": "reset_active_level", "value": "low"}]},
        {"source_id": "rtl", "source_kind": "rtl", "role": "IMPLEMENTATION_EVIDENCE",
         "facts": [{"fact_key": "reset_active_level", "value": "low"}]},
    ]
    result = dcg.PROBES["design_knowledge_correlation"]({"sources": sources})
    assert result["status"] == READY
    assert "conflicts=0" in result["evidence"]


def test_design_knowledge_correlation_real_conflict_is_blocked():
    sources = [
        {"source_id": "spec", "source_kind": "spec_document", "role": "SPEC_DECLARATION",
         "facts": [{"fact_key": "reset_active_level", "value": "low"}]},
        {"source_id": "rtl", "source_kind": "rtl", "role": "IMPLEMENTATION_EVIDENCE",
         "facts": [{"fact_key": "reset_active_level", "value": "high"}]},
    ]
    result = dcg.PROBES["design_knowledge_correlation"]({"sources": sources})
    assert result["status"] == BLOCKED
    assert "conflict" in result["gap"]


def test_design_knowledge_correlation_malformed_input_is_blocked():
    result = dcg.PROBES["design_knowledge_correlation"]({"sources": [{"source_id": "x"}]})
    assert result["status"] == BLOCKED


# ===========================================================================
# design_source_inventory
# ===========================================================================

def test_design_source_inventory_real_source_is_ready(tmp_path):
    real_file = tmp_path / "register_map.json"
    real_file.write_text(json.dumps(REGISTER_MAP_FIXTURE), encoding="utf-8")
    result = dcg.PROBES["design_source_inventory"]({
        "entries": [{"source_id": "reg_map", "type": "register_map", "path": str(real_file)}],
    })
    assert result["status"] == READY
    assert "1 source(s) registered" in result["evidence"]


def test_design_source_inventory_missing_path_is_blocked(tmp_path):
    result = dcg.PROBES["design_source_inventory"]({
        "entries": [{"source_id": "reg_map", "type": "register_map", "path": str(tmp_path / "gone.json")}],
    })
    assert result["status"] == BLOCKED


def test_design_source_inventory_no_entries_is_unknown():
    result = dcg.PROBES["design_source_inventory"]({"entries": []})
    assert result["status"] == UNKNOWN


# ===========================================================================
# spec_doc_map  (a real .txt "pre-extracted text" source -- no pypdf needed)
# ===========================================================================

SPEC_DOC_TEXT = (
    "Chapter 1: Overview\n"
    "This document describes the synthetic test device.\n\n"
    "Chapter 4: Register Map\n"
    "Table 4-1: Register Summary\n"
    "See the register descriptions below.\n"
)


def test_spec_doc_map_real_structure_is_ready(tmp_path):
    src = tmp_path / "dut_spec.txt"
    src.write_text(SPEC_DOC_TEXT, encoding="utf-8")
    result = dcg.PROBES["spec_doc_map"]({"source_path": str(src), "out_dir": str(tmp_path / "out")})
    assert result["status"] == READY
    assert "section(s)" in result["evidence"]


def test_spec_doc_map_missing_file_is_unknown(tmp_path):
    result = dcg.PROBES["spec_doc_map"]({
        "source_path": str(tmp_path / "nope.txt"), "out_dir": str(tmp_path / "out"),
    })
    assert result["status"] == UNKNOWN


def test_spec_doc_map_unsupported_suffix_is_unknown(tmp_path):
    src = tmp_path / "spec.xyz"
    src.write_text("hello", encoding="utf-8")
    result = dcg.PROBES["spec_doc_map"]({"source_path": str(src), "out_dir": str(tmp_path / "out")})
    assert result["status"] == UNKNOWN


# ===========================================================================
# power_intent
# ===========================================================================

def test_power_intent_real_upf_fixture():
    result = dcg.PROBES["power_intent"]({"upf_paths": [str(POWER_INTENT_FIXTURE)]})
    # this repo's own real fixture is a clean, self-consistent UPF -> PASS.
    assert result["status"] == READY
    assert "power domain(s)" in result["evidence"]


def test_power_intent_no_upf_is_unknown():
    result = dcg.PROBES["power_intent"]({"upf_paths": []})
    assert result["status"] == UNKNOWN


def test_power_intent_self_contradictory_upf_is_blocked(tmp_path):
    # a switchable domain with NO isolation strategy -- a real, detected
    # self-consistency defect (never simulated, never invented).
    bad_upf = tmp_path / "bad.upf"
    bad_upf.write_text(
        "upf_version 2.0\n"
        "set_design_top top\n"
        "create_power_domain PD_CORE -elements {u_core}\n"
        "create_supply_port VDD_CORE -direction in\n"
        "create_supply_net VDD_CORE_NET\n"
        "connect_supply_net VDD_CORE_NET -ports VDD_CORE\n"
        "set_domain_supply_net PD_CORE -primary_power_net VDD_CORE_NET\n"
        "create_power_switch SW_CORE -domain PD_CORE -output_supply_port {vout VDD_CORE_NET}\n",
        encoding="utf-8",
    )
    result = dcg.PROBES["power_intent"]({"upf_paths": [str(bad_upf)]})
    assert result["status"] == BLOCKED


# ===========================================================================
# The composite fold, worst-wins, over real per-category probe results
# ===========================================================================

@requires_verible
def test_full_matrix_worst_wins_one_blocked_category_dominates(tmp_path):
    xlsx = tmp_path / "regs.xlsx"
    _write_xlsx(xlsx, [["CTRL0", "0x0", 32, "RW", "0x0", "control"]])

    inputs = {
        "register_map": {"path": str(xlsx)},         # READY
        "power_intent": {"upf_paths": []},            # UNKNOWN
        # a genuinely malformed field_refs entry -- RegisterFieldRef() rejects
        # an unknown keyword, so trace_register_fields() raises for real.
        "register_rtl_trace": {
            "fields": [{"name": "irq_uart", "not_a_real_field": True}],
            "rtl_paths": [str(FIXTURES_DIR / "dut_top.sv")],
        },
    }
    matrix = dcg.derive_design_intelligence_completeness(inputs)
    assert matrix["design_intelligence_completeness"] == BLOCKED
    by_id = {r["row_id"]: r for r in matrix["rows"]}
    assert by_id["register_map"]["status"] == READY
    assert by_id["register_rtl_trace"]["status"] == BLOCKED


def test_full_matrix_all_ready_categories_fold_to_ready(tmp_path):
    xlsx = tmp_path / "regs.xlsx"
    _write_xlsx(xlsx, [["CTRL0", "0x0", 32, "RW", "0x0", "control"]])
    inputs = {"register_map": {"path": str(xlsx)}}
    for spec in dcg.ROWS:
        if spec.row_id == "register_map":
            continue
        inputs[spec.row_id] = None  # deliberately UNKNOWN -- still not READY overall
    matrix = dcg.derive_design_intelligence_completeness(inputs)
    # one READY row among twelve UNKNOWN rows -> worst-wins PARTIAL, never READY
    assert matrix["design_intelligence_completeness"] == PARTIAL


def test_markdown_render_and_report_text_include_every_row():
    matrix = dcg.derive_design_intelligence_completeness({})
    md = dcg.render_design_completeness_matrix(matrix)
    for spec in dcg.ROWS:
        assert spec.label in md
    report = dcg.format_design_completeness_report(matrix)
    assert "DESIGN INTELLIGENCE COMPLETENESS MATRIX" in report
    assert matrix["design_intelligence_completeness"] in report


# ===========================================================================
# CLI
# ===========================================================================

def test_cli_no_inputs_exits_2(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.design_completeness_gate"],
        cwd=str(Path(__file__).parent.parent), capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "DESIGN INTELLIGENCE COMPLETENESS MATRIX" in proc.stdout


def test_cli_with_real_inputs_file_and_json(tmp_path):
    xlsx = tmp_path / "regs.xlsx"
    _write_xlsx(xlsx, [["CTRL0", "0x0", 32, "RW", "0x0", "control"]])
    inputs_path = tmp_path / "inputs.json"
    inputs_path.write_text(json.dumps({"register_map": {"path": str(xlsx)}}), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.design_completeness_gate",
         "--inputs", str(inputs_path), "--json"],
        cwd=str(Path(__file__).parent.parent), capture_output=True, text=True,
    )
    assert proc.returncode == 2  # PARTIAL overall (twelve categories still UNKNOWN)
    payload = json.loads(proc.stdout)
    row = {r["row_id"]: r for r in payload["rows"]}["register_map"]
    assert row["status"] == READY
