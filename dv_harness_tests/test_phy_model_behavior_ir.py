"""Tests for dv_harness/phy_model_behavior_ir.py -- PHY architecture facts
(training/link-startup stage names, TX/RX capability statements, power-state
names) extracted from a REAL, offline-distilled PHY spec/model document,
each with a real document+line citation, plus an optional read-only merge of
dv_harness.phy_boundary's own RTL-derived bind-location decision.

The synthetic PHY spec fixture below states in its own text that it is a
test fixture and describes no real IP -- consistent with the "No
Golden-Reference Content Mining" rule: nothing here is mined from, or
compared against, a real vendor's PHY specification.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from dv_harness import phy_boundary, phy_model_behavior_ir as pmbi
from dv_harness import vip_user_guide_distill as ugd

FIXTURE_TEXT = """1.0 Overview

This is a synthetic PHY specification test fixture. It is not real protocol
content and describes no real vendor IP.

4.1 Link Training States

The link startup sequence proceeds through the following states:

- DETECT: initial state after reset, waits for receiver termination
- POLLING: elects and trains the physical link parameters
- CONFIGURATION: negotiates link width and lane numbering
- RECOVERY: re-establishes bit and symbol lock after an error

4.2 Transmitter Characteristics

- Supports differential output swing of 800mV to 1200mV typical
- Provides de-emphasis levels selectable per lane
- Implements a programmable transmitter equalization preset

4.3 Receiver Characteristics

- Provides continuous time linear equalization (CTLE)
- Detects receiver termination presence for link partner detection
- Supports adaptive decision feedback equalization (DFE)

4.4 Power Management States

P0: fully powered, active link, full bandwidth available
P1: standby, clocks gated, fast exit latency
P2: low power, PLL powered down, slower exit latency

4.5 Compliance Requirements

- Eye height shall exceed 50 mV at the compliance test point
- Jitter budget is allocated per the compliance test pattern
"""

NO_MARKER_TEXT = """1.0 Overview

This synthetic fixture intentionally contains none of this module's
structural section markers anywhere in its text.

2.0 Miscellaneous

- Some bullet point that is not inside any recognized section.
"""

MARKER_NO_ITEMS_TEXT = """4.1 Link Training States

This section discusses link training in prose only, with no recognizable
"ID: description" or "ID  description" item lines at all, just paragraphs
of running text that happen to be longer than a heading and end with a
period so they are never mistaken for one either.
"""


@pytest.fixture()
def distilled_phy_doc(tmp_path):
    src = tmp_path / "synthetic_phy_spec.txt"
    src.write_text(FIXTURE_TEXT, encoding="utf-8")
    out_dir = tmp_path / "distilled"
    record = ugd.distill_user_guide(src, out_dir, title="Synthetic PHY Spec", doc_kind="protocol_spec")
    return record


def _mod(name, ports):
    return {"name": name, "ports": [
        {"name": n, "direction": d, "data_type": t} for n, d, t in ports]}


PARALLEL_PAIR = [
    _mod("phy", [("pclk", "input", "logic"), ("pipe_txdata", "input", "logic [31:0]"),
                 ("pipe_rxdata", "output", "logic [31:0]"), ("txp", "output", "logic")]),
    _mod("ctrl", [("pclk", "input", "logic"), ("pipe_txdata", "output", "logic [31:0]"),
                  ("pipe_rxdata", "input", "logic [31:0]")]),
]


# ===========================================================================
# absent PHY doc -> NOT_AVAILABLE everywhere, never a guess
# ===========================================================================

def test_no_document_supplied_is_not_available_for_every_field():
    doc = pmbi.extract_phy_model_behavior_ir()
    assert doc["status"] == "NOT_AVAILABLE"
    assert doc["source"] is None
    for field in ("training_link_startup_stages", "tx_capabilities", "rx_capabilities", "power_states"):
        assert doc[field]["status"] == "NOT_AVAILABLE"
        assert doc[field]["items"] == []
        assert doc[field]["reason"]
    pmbi.validate_phy_model_behavior_ir(doc)


def test_disclosure_is_always_present_and_states_not_silicon():
    doc = pmbi.extract_phy_model_behavior_ir()
    assert "NOT SILICON" in doc["disclosure"]
    assert "electrical" in doc["disclosure"].lower()


def test_missing_reference_record_path_reports_not_available(tmp_path):
    doc = pmbi.extract_phy_model_behavior_ir(reference_record_path=tmp_path / "nope.reference.json")
    assert doc["status"] == "NOT_AVAILABLE"
    assert "could not load" in doc["reason"]


def test_malformed_reference_record_dict_is_rejected():
    doc = pmbi.extract_phy_model_behavior_ir(reference_record={"schema_version": "1.0"})
    assert doc["status"] == "NOT_AVAILABLE"
    assert "missing" in doc["reason"]


def test_missing_fulltext_file_on_disk_reports_not_available(distilled_phy_doc):
    Path(distilled_phy_doc["full_text_extract"]["path"]).unlink()
    doc = pmbi.extract_phy_model_behavior_ir(reference_record=distilled_phy_doc)
    assert doc["status"] == "NOT_AVAILABLE"
    assert "missing on disk" in doc["reason"]


# ===========================================================================
# real doc supplied -> real extraction, real citations
# ===========================================================================

def test_extracted_status_and_source_identity(distilled_phy_doc):
    doc = pmbi.extract_phy_model_behavior_ir(reference_record=distilled_phy_doc)
    assert doc["status"] == "EXTRACTED"
    assert doc["source"]["doc_kind"] == "protocol_spec"
    assert doc["source"]["title"] == "Synthetic PHY Spec"
    assert doc["source"]["fulltext_sha256_verified"] is True
    pmbi.validate_phy_model_behavior_ir(doc)


def test_training_stages_are_found_with_real_names(distilled_phy_doc):
    doc = pmbi.extract_phy_model_behavior_ir(reference_record=distilled_phy_doc)
    field = doc["training_link_startup_stages"]
    assert field["status"] == "FOUND"
    names = {item["name"] for item in field["items"]}
    assert names == {"DETECT", "POLLING", "CONFIGURATION", "RECOVERY"}


def test_power_states_are_found_with_real_names(distilled_phy_doc):
    doc = pmbi.extract_phy_model_behavior_ir(reference_record=distilled_phy_doc)
    field = doc["power_states"]
    assert field["status"] == "FOUND"
    names = {item["name"] for item in field["items"]}
    assert names == {"P0", "P1", "P2"}


def test_tx_and_rx_capabilities_are_found_as_verbatim_text(distilled_phy_doc):
    doc = pmbi.extract_phy_model_behavior_ir(reference_record=distilled_phy_doc)
    tx_texts = [item["evidence_text"] for item in doc["tx_capabilities"]["items"]]
    rx_texts = [item["evidence_text"] for item in doc["rx_capabilities"]["items"]]
    assert any("differential output swing" in t for t in tx_texts)
    assert any("de-emphasis" in t for t in tx_texts)
    assert any("continuous time linear equalization" in t for t in rx_texts)
    assert any("decision feedback equalization" in t for t in rx_texts)
    # No cross-contamination between TX and RX buckets.
    assert not any("equalization (CTLE)" in t for t in tx_texts)
    assert not any("de-emphasis" in t for t in rx_texts)


def test_citations_point_at_real_lines_in_the_real_fulltext_file(distilled_phy_doc):
    doc = pmbi.extract_phy_model_behavior_ir(reference_record=distilled_phy_doc)
    fulltext_lines = Path(distilled_phy_doc["full_text_extract"]["path"]).read_text(
        encoding="utf-8").splitlines()
    checked = 0
    for field_name in ("training_link_startup_stages", "tx_capabilities", "rx_capabilities", "power_states"):
        for item in doc[field_name]["items"]:
            citation = item["citation"]
            real_line = fulltext_lines[citation["line"] - 1].strip()
            assert item["evidence_text"] in real_line or real_line in item["evidence_text"]
            assert citation["fulltext_path"] == distilled_phy_doc["full_text_extract"]["path"]
            checked += 1
    assert checked >= 10


def test_content_after_an_unrelated_recognized_heading_is_not_misattributed(distilled_phy_doc):
    """The '4.5 Compliance Requirements' section's bullets must not leak into
    tx_capabilities/rx_capabilities/power_states even though it immediately
    follows the Power Management States section -- current_category must
    reset at every recognized heading, matched or not."""
    doc = pmbi.extract_phy_model_behavior_ir(reference_record=distilled_phy_doc)
    for field_name in ("tx_capabilities", "rx_capabilities"):
        texts = [item["evidence_text"] for item in doc[field_name]["items"]]
        assert not any("eye height" in t.lower() for t in texts)
        assert not any("jitter budget" in t.lower() for t in texts)
    power_names = {item["name"] for item in doc["power_states"]["items"]}
    assert "Eye" not in power_names and "Jitter" not in power_names


# ===========================================================================
# honest structural non-findings -- never a false FOUND
# ===========================================================================

def test_no_marker_section_detected_is_reported_honestly(tmp_path):
    src = tmp_path / "no_markers.txt"
    src.write_text(NO_MARKER_TEXT, encoding="utf-8")
    record = ugd.distill_user_guide(src, tmp_path / "out", doc_kind="protocol_spec")
    doc = pmbi.extract_phy_model_behavior_ir(reference_record=record)
    assert doc["status"] == "EXTRACTED"
    for field_name in ("training_link_startup_stages", "tx_capabilities", "rx_capabilities", "power_states"):
        field = doc[field_name]
        assert field["status"] == "NO_MARKER_SECTION_DETECTED"
        assert field["items"] == []
        assert field["reason"]


def test_marker_section_found_but_no_items_is_a_distinct_status(tmp_path):
    src = tmp_path / "prose_only.txt"
    src.write_text(MARKER_NO_ITEMS_TEXT, encoding="utf-8")
    record = ugd.distill_user_guide(src, tmp_path / "out", doc_kind="protocol_spec")
    doc = pmbi.extract_phy_model_behavior_ir(reference_record=record)
    field = doc["training_link_startup_stages"]
    assert field["status"] == "MARKER_SECTION_FOUND_NO_ITEMS"
    assert field["items"] == []
    # The other three categories never even saw their marker section.
    assert doc["power_states"]["status"] == "NO_MARKER_SECTION_DETECTED"


def test_a_bare_numbered_list_item_is_not_mistaken_for_a_heading():
    """'1. Detect' (a plain numbered list item -- one integer, no dotted
    subsection) must NOT reset the current section the way '4.1 Link
    Training States' does; only a real X.Y-shaped section number does."""
    assert pmbi._is_heading_like("1. Detect") is False
    assert pmbi._is_heading_like("4.1 Link Training States") is True
    assert pmbi._is_heading_like("POWER MANAGEMENT STATES") is True
    assert pmbi._is_heading_like("- DETECT: initial state after reset") is False


def test_fulltext_hash_mismatch_is_detected_but_extraction_still_proceeds(distilled_phy_doc):
    """A full-text file that changed since distillation is a real, detectable
    fact (fulltext_sha256_verified: False) -- it must not silently pass as
    verified, but it also must not block extraction from the file that IS
    on disk right now."""
    fulltext_path = Path(distilled_phy_doc["full_text_extract"]["path"])
    fulltext_path.write_text(fulltext_path.read_text(encoding="utf-8") + "\ntampered line\n",
                              encoding="utf-8")
    doc = pmbi.extract_phy_model_behavior_ir(reference_record=distilled_phy_doc)
    assert doc["status"] == "EXTRACTED"
    assert doc["source"]["fulltext_sha256_verified"] is False


# ===========================================================================
# boundary_context -- read-only reuse of phy_boundary.py's own output
# ===========================================================================

def test_no_boundary_doc_supplied_is_honestly_unavailable():
    doc = pmbi.extract_phy_model_behavior_ir()
    ctx = doc["boundary_context"]
    assert ctx["available"] is False
    assert ctx["mount_layer"] is None


def test_real_phy_boundary_document_is_merged_in_read_only(distilled_phy_doc):
    boundary_doc = phy_boundary.extract_phy_boundary(PARALLEL_PAIR, "phy", "ctrl")
    doc = pmbi.extract_phy_model_behavior_ir(reference_record=distilled_phy_doc,
                                              phy_boundary_doc=boundary_doc)
    ctx = doc["boundary_context"]
    assert ctx["available"] is True
    assert ctx["phy_module"] == "phy"
    assert ctx["controller_module"] == "ctrl"
    assert ctx["boundary_status"] == "EXTRACTED"
    assert ctx["classification_kind"] == "PARALLEL"
    assert ctx["mount_layer"] == "controller_phy_parallel_boundary"
    assert ctx["bindable"] is True


def test_invalid_boundary_document_is_refused_not_trusted():
    doc = pmbi.extract_phy_model_behavior_ir(phy_boundary_doc={"schema_version": "1.0"})
    ctx = doc["boundary_context"]
    assert ctx["available"] is False
    assert "failed its own schema validation" in ctx["reason"]


def test_not_available_phy_boundary_document_is_carried_through_honestly():
    """A phy_boundary document that is itself schema-valid but internally
    NOT_AVAILABLE (e.g. a declared module absent from the real RTL) must be
    reported as such -- available=True (a real, valid document was supplied)
    with boundary_status=NOT_AVAILABLE, never silently dropped."""
    boundary_doc = phy_boundary.extract_phy_boundary(PARALLEL_PAIR, "nope", "ctrl")
    doc = pmbi.extract_phy_model_behavior_ir(phy_boundary_doc=boundary_doc)
    ctx = doc["boundary_context"]
    assert ctx["available"] is True
    assert ctx["boundary_status"] == "NOT_AVAILABLE"
    assert ctx["classification_kind"] == "UNDECIDABLE"
    assert ctx["bindable"] is False


# ===========================================================================
# schema validation
# ===========================================================================

def test_invalid_document_is_rejected():
    with pytest.raises(pmbi.PhyModelBehaviorIRValidationError):
        pmbi.validate_phy_model_behavior_ir({"schema_version": "1.0"})


def test_save_and_load_round_trip_is_deterministic(distilled_phy_doc, tmp_path):
    doc = pmbi.extract_phy_model_behavior_ir(reference_record=distilled_phy_doc)
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    pmbi.save_phy_model_behavior_ir(doc, a)
    pmbi.save_phy_model_behavior_ir(pmbi.load_phy_model_behavior_ir(a), b)
    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")


def test_scan_phy_doc_text_respects_the_item_cap(distilled_phy_doc):
    full_text = Path(distilled_phy_doc["full_text_extract"]["path"]).read_text(encoding="utf-8")
    scan = pmbi.scan_phy_doc_text(full_text, document_label="d", fulltext_path="p",
                                   max_items_per_category=2)
    assert len(scan["items"][pmbi._CAT_TRAINING]) == 2
