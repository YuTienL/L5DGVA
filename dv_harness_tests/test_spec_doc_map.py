"""Tests for dv_harness/spec_doc_map.py -- the offline structural distiller
for non-VIP DUT spec/datasheet/programming-guide documents.

Fixtures are REAL PDFs built with `reportlab` (already a project dependency in
this environment) rather than a hand-typed byte string, so the module under
test is exercised against a genuine pypdf-readable document, the same
discipline `vip_user_guide_distill.py`'s own extraction relies on. Nothing
here is a real DUT's spec -- every fixture is synthetic and clearly so.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import spec_doc_map as sdm

reportlab = pytest.importorskip("reportlab", reason="reportlab not installed in this environment")
from reportlab.pdfgen import canvas  # noqa: E402


def _build_clean_pdf(path: Path) -> None:
    """A small, real, synthetic 3-page 'DUT spec' PDF:
      page 1: chapter 1 'Overview' (no register content)
      page 2: chapter 4 'Register Map' + subsection 4.1 + a table caption
      page 3: chapter 5 'Electrical Characteristics' + a table caption
    Chapter 4 is the only register-titled chapter, so its computed page
    range must be exactly [2, 2] -- bounded by chapter 5's own start page.
    """
    c = canvas.Canvas(str(path), pagesize=(612, 792))
    c.drawString(72, 750, "1 Overview")
    c.drawString(72, 730, "This device implements a simple bus interface for testing purposes.")
    c.showPage()
    c.drawString(72, 750, "4 Register Map")
    c.drawString(72, 730, "4.1 Register Bit Definitions")
    c.drawString(72, 710, "Table 4-1: Register Summary")
    c.drawString(72, 690, "The register map below lists all control and status registers.")
    c.showPage()
    c.drawString(72, 750, "5 Electrical Characteristics")
    c.drawString(72, 730, "Table 5-1: Timing Parameters")
    c.showPage()
    c.save()


def _build_chapter_keyword_pdf(path: Path) -> None:
    """A single-page PDF using the 'Chapter N: Title' convention instead of a
    bare leading number, to prove that heading form is detected too, and
    proving the register-CSR keyword variant fires."""
    c = canvas.Canvas(str(path), pagesize=(612, 792))
    c.drawString(72, 750, "Chapter 7: CSR Reference")
    c.drawString(72, 730, "Table 7-1: CSR Offsets")
    c.showPage()
    c.save()


def _build_no_structure_pdf(path: Path) -> None:
    """A PDF with real page content but no numbered/Chapter headings and no
    Table captions at all -- a genuine zero, not a failure."""
    c = canvas.Canvas(str(path), pagesize=(612, 792))
    c.drawString(72, 750, "Overview")
    c.drawString(72, 730, "This document intentionally has no numbered headings.")
    c.showPage()
    c.save()


def _build_registration_false_positive_pdf(path: Path) -> None:
    """A chapter titled 'Registration Procedures' -- an administrative
    chapter that must NOT be mistaken for a register-map chapter (proves the
    word-boundary regex, not a bare substring match)."""
    c = canvas.Canvas(str(path), pagesize=(612, 792))
    c.drawString(72, 750, "9 Registration Procedures")
    c.drawString(72, 730, "How to register this product with the vendor.")
    c.showPage()
    c.save()


@pytest.fixture()
def clean_pdf(tmp_path) -> Path:
    p = tmp_path / "dut_spec.pdf"
    _build_clean_pdf(p)
    return p


# ---------------------------------------------------------------------------
# Core positive path
# ---------------------------------------------------------------------------

def test_extract_clean_pdf_produces_correct_structure(tmp_path, clean_pdf):
    out_dir = tmp_path / "out"
    record = sdm.extract_spec_doc_map(clean_pdf, out_dir, title="Synthetic DUT Spec", doc_kind="dut_spec")

    assert record["schema_version"] == sdm.SCHEMA_VERSION
    assert record["doc_kind"] == "dut_spec"
    assert record["title"] == "Synthetic DUT Spec"
    assert record["source_document"]["page_count"] == 3
    assert record["extraction"]["tool"] == "pypdf"
    assert record["extraction"]["method"] == "pdf_structure_scan"
    assert record["extraction"]["tool_version"]  # a real pypdf version string

    # -- sections: chapter 1, chapter 4, subsection 4.1, chapter 5 --
    headings = [(s["number"], s["heading"], s["page"], s["level"]) for s in record["sections"]]
    assert ("1", "1 Overview", 1, 1) in headings
    assert ("4", "4 Register Map", 2, 1) in headings
    assert ("4.1", "4.1 Register Bit Definitions", 2, 2) in headings
    assert ("5", "5 Electrical Characteristics", 3, 1) in headings
    assert record["section_count"] == len(record["sections"]) == 4

    # -- tables: two captions, correct pages --
    tables = [(t["number"], t["caption"], t["page"]) for t in record["tables"]]
    assert ("4-1", "Table 4-1: Register Summary", 2) in tables
    assert ("5-1", "Table 5-1: Timing Parameters", 3) in tables
    assert record["table_count"] == 2

    # -- register chapters: ONLY chapter 4, bounded to page 2 --
    reg = record["register_chapters"]
    assert len(reg) == 1
    assert reg[0]["number"] == "4"
    assert reg[0]["start_page"] == 2
    assert reg[0]["end_page"] == 2  # bounded by chapter 5's start page (3 - 1)
    assert record["register_chapter_count"] == 1

    # -- never any body prose in the persisted record --
    dumped = json.dumps(record)
    assert "bus interface" not in dumped
    assert "control and status registers" not in dumped

    # -- two artifacts on disk, both structure-only, no fulltext file at all --
    json_path = out_dir / "dut_spec.structure_map.json"
    md_path = out_dir / "dut_spec.structure_map.md"
    assert json_path.is_file()
    assert md_path.is_file()
    assert not (out_dir / "dut_spec.fulltext.txt").exists()
    md_text = md_path.read_text(encoding="utf-8")
    assert "bus interface" not in md_text
    assert "Register Map" in md_text  # headings, not prose, are expected content

    # -- structure_map pointer in the record matches the real file on disk --
    assert record["structure_map"]["path"] == str(md_path)
    assert record["structure_map"]["sha256"] == sdm._sha256_text(md_text)


def test_load_spec_doc_map_round_trips(tmp_path, clean_pdf):
    out_dir = tmp_path / "out"
    record = sdm.extract_spec_doc_map(clean_pdf, out_dir)
    json_path = out_dir / "dut_spec.structure_map.json"
    loaded = sdm.load_spec_doc_map(json_path)
    assert loaded == record


def test_chapter_keyword_heading_form_and_csr_detection(tmp_path):
    p = tmp_path / "chapter_form.pdf"
    _build_chapter_keyword_pdf(p)
    record = sdm.extract_spec_doc_map(p, tmp_path / "out")
    headings = [(s["number"], s["title"], s["page"]) for s in record["sections"]]
    assert ("7", "CSR Reference", 1) in headings
    assert record["table_count"] == 1
    assert record["tables"][0]["caption"] == "Table 7-1: CSR Offsets"
    reg = record["register_chapters"]
    assert len(reg) == 1
    assert reg[0]["number"] == "7"
    assert reg[0]["start_page"] == 1
    assert reg[0]["end_page"] == 1  # last/only chapter -> bounded by page_count


def test_text_source_reports_honest_null_pages(tmp_path):
    """A .txt (pre-extracted) source: sections/tables are still detected, but
    page is honestly None everywhere -- never a fabricated page number."""
    txt = tmp_path / "programming_guide.txt"
    txt.write_text(
        "4 Register Map\n"
        "Table 4-1: Register Summary\n"
        "Some descriptive body prose that is not a heading.\n"
        "5 Electrical Characteristics\n",
        encoding="utf-8",
    )
    record = sdm.extract_spec_doc_map(txt, tmp_path / "out", doc_kind="programming_guide")
    assert record["extraction"]["method"] == "pre_extracted_text_structure_scan"
    assert record["source_document"]["page_count"] is None
    assert all(s["page"] is None for s in record["sections"])
    assert all(t["page"] is None for t in record["tables"])
    reg = record["register_chapters"]
    assert len(reg) == 1
    assert reg[0]["start_page"] is None
    assert reg[0]["end_page"] is None


# ---------------------------------------------------------------------------
# Negative controls: absent/unreadable evidence must never fabricate a result
# ---------------------------------------------------------------------------

def test_no_structure_pdf_reports_real_zeros_not_a_crash(tmp_path):
    p = tmp_path / "no_structure.pdf"
    _build_no_structure_pdf(p)
    record = sdm.extract_spec_doc_map(p, tmp_path / "out")
    assert record["section_count"] == 0
    assert record["table_count"] == 0
    assert record["register_chapter_count"] == 0
    md_text = (tmp_path / "out" / "no_structure.structure_map.md").read_text(encoding="utf-8")
    assert "No numbered chapter/section headings were detected" in md_text
    assert "No table captions were detected" in md_text
    assert "No chapter heading matched a register/CSR keyword" in md_text


def test_registration_procedures_is_not_a_register_chapter_false_positive(tmp_path):
    """Word-boundary negative control: a chapter about 'Registration' (an
    unrelated administrative process) must not be credited as a register
    chapter just because it shares a substring with 'register'."""
    p = tmp_path / "registration.pdf"
    _build_registration_false_positive_pdf(p)
    record = sdm.extract_spec_doc_map(p, tmp_path / "out")
    assert record["section_count"] == 1
    assert record["register_chapter_count"] == 0
    assert record["register_chapters"] == []


def test_missing_source_file_raises_with_real_reason(tmp_path):
    missing = tmp_path / "does_not_exist.pdf"
    with pytest.raises(sdm.SpecDocMapError, match="does not exist"):
        sdm.extract_spec_doc_map(missing, tmp_path / "out")


def test_unsupported_suffix_raises_with_real_reason(tmp_path):
    bad = tmp_path / "spec.docx"
    bad.write_bytes(b"not a real docx, just bytes")
    with pytest.raises(sdm.SpecDocMapError, match="unsupported suffix"):
        sdm.extract_spec_doc_map(bad, tmp_path / "out")


def test_missing_pypdf_dependency_raises_actionable_error(monkeypatch, tmp_path, clean_pdf):
    """Simulate pypdf genuinely not being installed (rather than skipping the
    test) by making the import fail inside _extract_pdf_pages, and assert the
    module raises rather than silently producing an empty structure map."""
    import builtins
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "pypdf":
            raise ImportError("simulated: pypdf not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    with pytest.raises(sdm.SpecDocMapError, match="pypdf"):
        sdm.extract_spec_doc_map(clean_pdf, tmp_path / "out")


def test_load_spec_doc_map_rejects_malformed_json(tmp_path):
    bad = tmp_path / "not_json.structure_map.json"
    bad.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(sdm.SpecDocMapError, match="not a readable JSON"):
        sdm.load_spec_doc_map(bad)


def test_load_spec_doc_map_rejects_foreign_record_shape(tmp_path):
    foreign = tmp_path / "foreign.json"
    foreign.write_text(json.dumps({"some_other_field": 1}), encoding="utf-8")
    with pytest.raises(sdm.SpecDocMapError, match="missing"):
        sdm.load_spec_doc_map(foreign)


# ---------------------------------------------------------------------------
# execute_verb() / CLI: honest NOT_AVAILABLE reporting
# ---------------------------------------------------------------------------

def test_execute_verb_extract_missing_source_reports_not_available(tmp_path):
    text, code = sdm.execute_verb(
        "extract", source_path=str(tmp_path / "nope.pdf"), out_dir=str(tmp_path / "out"))
    assert code == 2
    assert "NOT_AVAILABLE" in text
    assert "does not exist" in text


def test_execute_verb_extract_success_json(tmp_path, clean_pdf):
    text, code = sdm.execute_verb(
        "extract", source_path=str(clean_pdf), out_dir=str(tmp_path / "out"), as_json=True)
    assert code == 0
    payload = json.loads(text)
    assert payload["status"] == "EXTRACTED"
    assert payload["section_count"] == 4


def test_execute_verb_show_round_trips(tmp_path, clean_pdf):
    sdm.execute_verb("extract", source_path=str(clean_pdf), out_dir=str(tmp_path / "out"))
    record_path = tmp_path / "out" / "dut_spec.structure_map.json"
    text, code = sdm.execute_verb("show", record_path=str(record_path), as_json=True)
    assert code == 0
    payload = json.loads(text)
    assert payload["section_count"] == 4


def test_execute_verb_unknown_verb(tmp_path):
    text, code = sdm.execute_verb("bogus")
    assert code == 2
    assert "unknown verb" in text


def test_cli_subprocess_extract_and_show(tmp_path, clean_pdf):
    out_dir = tmp_path / "out"
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.spec_doc_map", "extract",
         "--source", str(clean_pdf), "--out-dir", str(out_dir), "--json"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "EXTRACTED"
    assert payload["register_chapter_count"] == 1

    show = subprocess.run(
        [sys.executable, "-m", "dv_harness.spec_doc_map", "show",
         "--record", str(out_dir / "dut_spec.structure_map.json"), "--json"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
    )
    assert show.returncode == 0, show.stderr
    shown = json.loads(show.stdout)
    assert shown["section_count"] == 4


def test_cli_subprocess_not_available_exit_code(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.spec_doc_map", "extract",
         "--source", str(tmp_path / "missing.pdf"), "--out-dir", str(tmp_path / "out")],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent),
    )
    assert proc.returncode == 2
    assert "NOT_AVAILABLE" in proc.stdout
