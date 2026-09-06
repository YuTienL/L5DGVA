"""Tests for dv_harness/interrupt_dma_clock_reset_extraction.py.

Fixtures live under dv_harness_tests/fixtures/interrupt_dma_clock_reset/ and
are synthetic (their own file headers say so, not any real DUT/spec). The
positive-path test proves every facet is correctly extracted from real
supplied text; the negative controls prove the module reports honest
NOT_AVAILABLE rather than fabricating a priority scheme, a channel count, or
a reset polarity when the supplied text does not state one.
"""
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import interrupt_dma_clock_reset_extraction as idcr

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "interrupt_dma_clock_reset"
RTL_FIXTURE = FIXTURES / "dut_top.sv"
DOC_FIXTURE = FIXTURES / "programming_guide.txt"
BLANK_FIXTURE = FIXTURES / "no_interrupt_no_priority.txt"
AMBIGUOUS_RESET_FIXTURE = FIXTURES / "ambiguous_reset.sv"


# ---------------------------------------------------------------------------
# Positive path: real RTL + real doc text -> every facet extracted correctly.
# ---------------------------------------------------------------------------
def test_positive_path_extracts_every_facet_from_real_sources():
    report = idcr.extract_interrupt_dma_clock_reset([str(RTL_FIXTURE), str(DOC_FIXTURE)])

    assert report["status"] == "LOADED"
    assert report["reason"] is None
    assert set(report["source"]["paths"]) == {str(RTL_FIXTURE), str(DOC_FIXTURE)}
    assert report["source"]["missing"] == []

    # --- interrupt architecture ---
    ia = report["interrupt_architecture"]
    assert ia["status"] == "LOADED"
    names = {s["name"] for s in ia["sources"]}
    assert names == {"irq_uart", "irq_vec"}
    uart = next(s for s in ia["sources"] if s["name"] == "irq_uart")
    assert uart["direction"] == "input"
    assert uart["description"] == "UART interrupt"
    assert uart["evidence"] == f"{RTL_FIXTURE}:12"
    vec = next(s for s in ia["sources"] if s["name"] == "irq_vec")
    assert vec["width"] == "3:0"

    priority = ia["priority_scheme"]
    assert priority["status"] == "LOADED"
    chain = next(st for st in priority["statements"] if st["type"] == "ORDERED_CHAIN")
    assert chain["order"] == ["IRQ0", "IRQ1", "IRQ2", "IRQ3"]
    extreme = next(st for st in priority["statements"] if st["type"] == "HIGHEST")
    assert extreme["source"] == "IRQ0"

    masking = ia["masking_scheme"]
    assert masking["status"] == "LOADED"
    assert any("INTR_MASK" in st["text"] for st in masking["statements"])

    # --- DMA architecture ---
    da = report["dma_architecture"]
    assert da["status"] == "LOADED"
    cc = da["channel_count"]
    assert cc["status"] == "LOADED"
    assert cc["value"] == 4
    assert cc["declared_as"] == "NUM_DMA_CHANNELS"

    desc = da["descriptor_model"]
    assert desc["status"] == "LOADED"
    assert desc["struct_name"] == "dma_desc_t"
    field_names = [f["name"] for f in desc["fields"]]
    assert field_names == ["src_addr", "dst_addr", "length", "valid"]
    src_addr = desc["fields"][0]
    assert src_addr["width"] == "31:0"

    # --- clock/reset extension, shape-compatible with env_manifest's
    # dut_facts.clock_reset resets (name/active_level/synchronous/clock/
    # clock_resolved/evidence/description) ---
    cr = report["clock_reset_extension"]
    assert cr["status"] == "LOADED"
    clock_names = {c["name"] for c in cr["clocks"]}
    assert clock_names == {"clk", "cfg_clk"}

    resets_by_name = {r["name"]: r for r in cr["resets"]}
    assert set(resets_by_name) == {"rst_n", "cfg_rst"}

    async_reset = resets_by_name["rst_n"]
    assert async_reset["active_level"] == "LOW"
    assert async_reset["synchronous"] is False
    assert async_reset["clock"] == "clk"
    assert async_reset["clock_resolved"] == "RESOLVED"
    for required_key in ("name", "active_level", "synchronous", "clock",
                          "clock_resolved", "evidence", "description"):
        assert required_key in async_reset

    sync_reset = resets_by_name["cfg_rst"]
    assert sync_reset["active_level"] == "HIGH"
    assert sync_reset["synchronous"] is True
    assert sync_reset["clock"] == "cfg_clk"
    assert sync_reset["clock_resolved"] == "RESOLVED"


# ---------------------------------------------------------------------------
# Negative control 1: no interrupt-named port in the supplied RTL ->
# interrupt sources NOT_AVAILABLE, never an empty-but-silent LOADED.
# ---------------------------------------------------------------------------
def test_no_interrupt_ports_reports_not_available_not_empty_pass():
    report = idcr.extract_interrupt_dma_clock_reset([str(AMBIGUOUS_RESET_FIXTURE)])
    ia = report["interrupt_architecture"]
    assert ia["status"] == "NOT_AVAILABLE"
    assert ia["sources"] == []
    assert "interrupt naming convention" in ia["reason"]


# ---------------------------------------------------------------------------
# Negative control 2: a document with no priority/masking language at all ->
# both facets NOT_AVAILABLE with a real, distinct reason, never inferred
# from the mere presence of interrupt sources.
# ---------------------------------------------------------------------------
def test_document_with_no_priority_or_masking_language_reports_not_available():
    report = idcr.extract_interrupt_dma_clock_reset([str(BLANK_FIXTURE)])
    ia = report["interrupt_architecture"]
    assert ia["priority_scheme"]["status"] == "NOT_AVAILABLE"
    assert ia["priority_scheme"]["statements"] == []
    assert ia["masking_scheme"]["status"] == "NOT_AVAILABLE"
    assert ia["masking_scheme"]["statements"] == []
    da = report["dma_architecture"]
    assert da["status"] == "NOT_AVAILABLE"
    assert da["channel_count"]["status"] == "NOT_AVAILABLE"
    assert da["channel_count"]["value"] is None
    assert da["descriptor_model"]["status"] == "NOT_AVAILABLE"
    assert report["clock_reset_extension"]["status"] == "NOT_AVAILABLE"
    # Nothing at all was extractable from this source -> honest top status.
    assert report["status"] == "NOT_AVAILABLE"


# ---------------------------------------------------------------------------
# Negative control 3: a reset signal name that does NOT match the reset
# naming convention must never be guessed as a reset, even though it is the
# first `if` inside the always block.
# ---------------------------------------------------------------------------
def test_ambiguous_reset_signal_name_is_never_guessed():
    report = idcr.extract_interrupt_dma_clock_reset([str(AMBIGUOUS_RESET_FIXTURE)])
    cr = report["clock_reset_extension"]
    assert cr["resets"] == []
    # The clock itself is still a real, separately-provable fact (it IS used
    # as a posedge clock in a real always block), so it is reported even
    # though the block's own first `if` names a signal that does not match
    # the reset naming convention and must never be guessed as a reset.
    assert [c["name"] for c in cr["clocks"]] == ["clk"]
    assert cr["status"] == "LOADED"


# ---------------------------------------------------------------------------
# Negative control 4: a mutated fixture with the DMA channel-count parameter
# removed must not fabricate a channel count from the descriptor struct or
# from anything else.
# ---------------------------------------------------------------------------
def test_removed_channel_count_parameter_reports_not_available(tmp_path):
    original = RTL_FIXTURE.read_text(encoding="utf-8")
    mutated = original.replace(
        "module dut_top #(\n    parameter NUM_DMA_CHANNELS = 4\n) (",
        "module dut_top (",
    )
    assert mutated != original, "mutation must actually remove the parameter line"
    mutated_path = tmp_path / "dut_top_no_channel_count.sv"
    mutated_path.write_text(mutated, encoding="utf-8")

    report = idcr.extract_interrupt_dma_clock_reset([str(mutated_path)])
    cc = report["dma_architecture"]["channel_count"]
    assert cc["status"] == "NOT_AVAILABLE"
    assert cc["value"] is None
    # The descriptor model is untouched by this mutation and must still load
    # -- proving one facet's absence never masks another's presence.
    assert report["dma_architecture"]["descriptor_model"]["status"] == "LOADED"


# ---------------------------------------------------------------------------
# Negative control 5: no source files at all, and a missing file -> honest
# NOT_AVAILABLE naming the real reason, never a crash and never a fabricated
# LOADED.
# ---------------------------------------------------------------------------
def test_no_sources_supplied_reports_not_available():
    report = idcr.extract_interrupt_dma_clock_reset([])
    assert report["status"] == "NOT_AVAILABLE"
    assert report["reason"] == "no source files were supplied"


def test_missing_source_file_is_recorded_not_raised(tmp_path):
    missing = tmp_path / "does_not_exist.sv"
    report = idcr.extract_interrupt_dma_clock_reset([str(missing)])
    assert report["status"] == "NOT_AVAILABLE"
    assert str(missing) in report["source"]["missing"]
    assert report["source"]["paths"] == []


# ---------------------------------------------------------------------------
# classify_source() and the real generated PCIe environment
# ---------------------------------------------------------------------------
def test_classify_source_by_suffix():
    assert idcr.classify_source(Path("foo.sv")) == "rtl"
    assert idcr.classify_source(Path("foo.v")) == "rtl"
    assert idcr.classify_source(Path("foo.txt")) == "text"
    assert idcr.classify_source(Path("foo.bin")) == "unknown"


def test_unrecognized_suffix_is_still_read_and_recorded(tmp_path):
    p = tmp_path / "notes.weird"
    p.write_text("The DMA controller supports 4 independent DMA channels.\n", encoding="utf-8")
    report = idcr.extract_interrupt_dma_clock_reset([str(p)])
    assert str(p) in report["source"]["unrecognized"]
    assert report["dma_architecture"]["channel_count"]["value"] == 4


# ---------------------------------------------------------------------------
# CLI front door, driven as a real subprocess
# ---------------------------------------------------------------------------
def test_cli_extract_json_real_subprocess():
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.interrupt_dma_clock_reset_extraction",
         "extract", "--sources", str(RTL_FIXTURE), str(DOC_FIXTURE), "--json"],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert '"status": "LOADED"' in result.stdout
    assert "irq_uart" in result.stdout


def test_cli_no_sources_exits_nonzero():
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.interrupt_dma_clock_reset_extraction",
         "extract", "--sources"],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 2
