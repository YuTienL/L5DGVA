"""Tests for dv_harness/dut_errata_correlation.py.

Fixtures are REAL PDFs built with `reportlab` (already a project dependency,
the same discipline test_spec_doc_map.py already established) and a REAL
env.manifest.json built through env_manifest.generate_and_write() over a
real verible-parsed RTL file and a real register-map JSON -- never a
hand-written manifest, per this project's Evidence Truth Rule. Nothing here
is a real DUT's errata sheet -- every fixture is synthetic and clearly so.

Coverage:
  * structural extraction -- erratum headers in both recognised forms
    ("Erratum N: Title" and a bare "ERR###: Title"), labeled
    affected-component/revision/workaround/status fields, the excerpt cap,
    and the honest real-zero case (a document with no recognisable erratum
    header at all).
  * correlation -- an exact RTL/register match (RTL_LOCATED), a fabricated
    affected-component name against an available manifest (RTL_NOT_LOCATED,
    a real negative), an erratum citing nothing (NO_AFFECTED_COMPONENT_CITED),
    and the required negative control: no manifest supplied at all
    (NOT_AVAILABLE, never silently read as RTL_NOT_LOCATED).
  * the one-shot `analyze_errata()` front door, including the mandatory
    "no errata document supplied" -> NOT_AVAILABLE contract this task exists
    to satisfy.
  * the CLI front door across all four verbs and their documented exit codes.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from dv_harness import env_manifest
from dv_harness import dut_evidence_correlation as dec
from dv_harness import dut_errata_correlation as dxc

reportlab = pytest.importorskip("reportlab", reason="reportlab not installed in this environment")
from reportlab.pdfgen import canvas  # noqa: E402

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Synthetic DUT RTL + register-map fixtures (never real project content),
# mirroring test_dut_evidence_correlation.py's own fixture shapes.
# ---------------------------------------------------------------------------

DUT_FIXTURE = textwrap.dedent("""\
    module usb_link_ctrl (
        input  logic       pclk,
        input  logic       presetn,
        output logic       usb_wake_irq
    );
        assign usb_wake_irq = 1'b0;
    endmodule
    """)

REGISTER_MAP_FIXTURE = {
    "schema_version": "1.0",
    "source": {"kind": "ral_model_export", "description": "synthesized test fixture, not a real project"},
    "blocks": [
        {
            "name": "CTRL_BLOCK",
            "base_address": "0x1000",
            "registers": [
                {
                    "name": "CTRL0",
                    "address_offset": "0x0",
                    "width": 32,
                    "access": "RW",
                    "reset_value": "0x0",
                    "fields": [],
                },
            ],
        },
    ],
}


@pytest.fixture
def dut_sv(tmp_path):
    p = tmp_path / "usb_link_ctrl.sv"
    p.write_text(DUT_FIXTURE, encoding="utf-8")
    return p


@pytest.fixture
def register_map_json(tmp_path):
    p = tmp_path / "register_map.json"
    p.write_text(json.dumps(REGISTER_MAP_FIXTURE), encoding="utf-8")
    return p


@pytest.fixture
def full_manifest_path(tmp_path, dut_sv, register_map_json):
    out = tmp_path / "env.manifest.json"
    env_manifest.generate_and_write(out, rtl_files=[dut_sv], register_map_path=register_map_json)
    return out


# ---------------------------------------------------------------------------
# Synthetic errata-sheet PDF fixtures.
# ---------------------------------------------------------------------------

def _build_errata_pdf(path: Path) -> None:
    """A real, small, synthetic 'silicon errata sheet' PDF, never a real
    vendor's document:
      page 1: Erratum 1 (keyword form) citing Affected Register: CTRL0,
              a Silicon Revision, and a Workaround section (has_workaround).
      page 2: a bare 'ERR002: Title' erratum citing an affected block that
              does NOT exist anywhere in the RTL/register-map fixtures
              (a real negative -- proves RTL_NOT_LOCATED).
      page 3: an erratum with no affected-component citation at all (proves
              NO_AFFECTED_COMPONENT_CITED), plus a Status-labeled field.
    """
    c = canvas.Canvas(str(path), pagesize=(612, 792))
    c.drawString(72, 750, "Erratum 1: CTRL0 Write Glitch on Cold Reset")
    c.drawString(72, 730, "Affected Register: CTRL0")
    c.drawString(72, 710, "Silicon Revision: A0, A1")
    c.drawString(72, 690, "Description: A spurious write may occur to CTRL0 immediately after cold reset.")
    c.drawString(72, 670, "Workaround: Re-write CTRL0 to its known-good value after reset deassertion.")
    c.showPage()
    c.drawString(72, 750, "ERR002: Ghost DMA Engine Stall")
    c.drawString(72, 730, "Affected Block: GHOST_DMA_ENGINE_THAT_DOES_NOT_EXIST")
    c.drawString(72, 710, "Description: A block this errata sheet cites that the RTL does not have.")
    c.showPage()
    c.drawString(72, 750, "Erratum 3: General Documentation Note")
    c.drawString(72, 730, "Status: Informational")
    c.drawString(72, 710, "This entry names no affected hardware component at all.")
    c.showPage()
    c.save()


def _build_no_errata_pdf(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=(612, 792))
    c.drawString(72, 750, "Known Issues")
    c.drawString(72, 730, "This chapter intentionally contains no recognisable erratum header.")
    c.showPage()
    c.save()


@pytest.fixture
def errata_pdf(tmp_path) -> Path:
    p = tmp_path / "dut_errata.pdf"
    _build_errata_pdf(p)
    return p


# ---------------------------------------------------------------------------
# Structural extraction
# ---------------------------------------------------------------------------

def test_extract_errata_pdf_finds_three_errata_with_correct_structure(tmp_path, errata_pdf):
    out_dir = tmp_path / "out"
    record = dxc.extract_errata_document(errata_pdf, out_dir, title="Synthetic Errata Sheet")

    assert record["schema_version"] == dxc.SCHEMA_VERSION
    assert record["doc_kind"] == "errata_sheet"
    assert record["title"] == "Synthetic Errata Sheet"
    assert record["source_document"]["page_count"] == 3
    assert record["extraction"]["tool"] == "pypdf"
    assert record["extraction"]["method"] == "pdf_errata_scan"
    assert record["erratum_count"] == 3

    by_id = {e["erratum_id"]: e for e in record["errata"]}
    assert set(by_id) == {"1", "ERR002", "3"}

    e1 = by_id["1"]
    assert e1["title"] == "CTRL0 Write Glitch on Cold Reset"
    assert e1["page"] == 1
    comps = [c["name"] for c in e1["affected_components"]]
    assert comps == ["CTRL0"]
    assert e1["affected_components"][0]["raw_label"] == "affected register"
    assert e1["revisions_affected"] == ["A0, A1"]
    assert e1["has_workaround"] is True
    # the full description/workaround PROSE is never persisted -- only a
    # bounded excerpt of the non-labeled lines.
    dumped = json.dumps(record)
    assert "known-good value" not in dumped

    e2 = by_id["ERR002"]
    assert e2["title"] == "Ghost DMA Engine Stall"
    assert e2["page"] == 2
    assert [c["name"] for c in e2["affected_components"]] == ["GHOST_DMA_ENGINE_THAT_DOES_NOT_EXIST"]

    e3 = by_id["3"]
    assert e3["affected_components"] == []
    assert e3["status"] == "Informational"

    json_path = out_dir / "dut_errata.errata_index.json"
    md_path = out_dir / "dut_errata.errata_index.md"
    assert json_path.is_file()
    assert md_path.is_file()
    md_text = md_path.read_text(encoding="utf-8")
    assert "CTRL0 Write Glitch" in md_text
    assert "known-good value" not in md_text


def test_load_errata_document_round_trips(tmp_path, errata_pdf):
    out_dir = tmp_path / "out"
    record = dxc.extract_errata_document(errata_pdf, out_dir)
    loaded = dxc.load_errata_document(out_dir / "dut_errata.errata_index.json")
    assert loaded == record


def test_text_source_reports_honest_null_pages(tmp_path):
    txt = tmp_path / "errata.txt"
    txt.write_text(
        "Erratum 5: Text-Sourced Erratum\n"
        "Affected Signal: usb_wake_irq\n",
        encoding="utf-8",
    )
    record = dxc.extract_errata_document(txt, tmp_path / "out")
    assert record["extraction"]["method"] == "pre_extracted_text_errata_scan"
    assert record["source_document"]["page_count"] is None
    assert record["erratum_count"] == 1
    assert record["errata"][0]["page"] is None


def test_no_errata_pdf_reports_real_zero_not_a_crash(tmp_path):
    p = tmp_path / "no_errata.pdf"
    _build_no_errata_pdf(p)
    record = dxc.extract_errata_document(p, tmp_path / "out")
    assert record["erratum_count"] == 0
    assert record["errata"] == []
    md_text = (tmp_path / "out" / "no_errata.errata_index.md").read_text(encoding="utf-8")
    assert "No erratum entries" in md_text


def test_missing_source_file_raises_with_real_reason(tmp_path):
    with pytest.raises(dxc.ErrataDocumentError, match="does not exist"):
        dxc.extract_errata_document(tmp_path / "nope.pdf", tmp_path / "out")


def test_unsupported_suffix_raises_with_real_reason(tmp_path):
    bad = tmp_path / "errata.docx"
    bad.write_bytes(b"not a real docx")
    with pytest.raises(dxc.ErrataDocumentError, match="unsupported suffix"):
        dxc.extract_errata_document(bad, tmp_path / "out")


def test_missing_pypdf_dependency_raises_actionable_error(monkeypatch, tmp_path, errata_pdf):
    import builtins
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "pypdf":
            raise ImportError("simulated: pypdf not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    with pytest.raises(dxc.ErrataDocumentError, match="pypdf"):
        dxc.extract_errata_document(errata_pdf, tmp_path / "out")


def test_load_errata_document_rejects_malformed_json(tmp_path):
    bad = tmp_path / "not_json.errata_index.json"
    bad.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(dxc.ErrataDocumentError, match="not a readable JSON"):
        dxc.load_errata_document(bad)


def test_load_errata_document_rejects_foreign_record_shape(tmp_path):
    foreign = tmp_path / "foreign.json"
    foreign.write_text(json.dumps({"some_other_field": 1}), encoding="utf-8")
    with pytest.raises(dxc.ErrataDocumentError, match="missing"):
        dxc.load_errata_document(foreign)


# ---------------------------------------------------------------------------
# Correlation -- reuses dut_evidence_correlation.py's own verdicts
# ---------------------------------------------------------------------------

@requires_verible
def test_erratum_citing_a_real_register_is_rtl_located(full_manifest_path, errata_pdf, tmp_path):
    doc_record = dxc.extract_errata_document(errata_pdf, tmp_path / "out")
    report = dxc.correlate_errata(doc_record["errata"], full_manifest_path)
    assert report["manifest_status"] == "LOADED"
    by_id = {r["erratum_id"]: r for r in report["errata"]}

    r1 = by_id["1"]
    assert r1["correlation_status"] == dxc.STATUS_RTL_LOCATED
    assert r1["citations"][0]["status"] == dec.STATUS_RTL_CONFIRMED
    assert r1["citations"][0]["exact_matches"][0]["kind"] == "register"

    r2 = by_id["ERR002"]
    assert r2["correlation_status"] == dxc.STATUS_RTL_NOT_LOCATED
    assert r2["citations"][0]["status"] == dec.STATUS_RTL_NOT_FOUND

    r3 = by_id["3"]
    assert r3["correlation_status"] == dxc.STATUS_NO_AFFECTED_COMPONENT_CITED
    assert r3["citations"] == []

    assert report["summary"][dxc.STATUS_RTL_LOCATED] == 1
    assert report["summary"][dxc.STATUS_RTL_NOT_LOCATED] == 1
    assert report["summary"][dxc.STATUS_NO_AFFECTED_COMPONENT_CITED] == 1


def test_partial_match_reads_partially_located(full_manifest_path):
    # "CTRL0X" is not an exact name in the fixture register map, but a real
    # substring relationship exists ("CTRL0" is a substring of "CTRL0X"),
    # so this must read PARTIALLY_LOCATED, never upgraded to LOCATED.
    erratum = {
        "erratum_id": "ERR-PARTIAL", "title": "Partial Match Test", "page": 1,
        "affected_components": [{"raw_label": "affected register", "name": "CTRL0X", "page": 1}],
        "revisions_affected": [], "has_workaround": False, "status": None, "excerpt": "",
    }
    manifest = env_manifest.load_env_manifest(full_manifest_path)
    result = dxc.correlate_erratum_to_rtl(erratum, manifest)
    assert result["correlation_status"] == dxc.STATUS_RTL_PARTIALLY_LOCATED
    assert result["citations"][0]["status"] == dec.STATUS_RTL_PARTIAL


def test_no_manifest_supplied_is_not_available_never_not_located(errata_pdf, tmp_path):
    """The required negative control: an erratum with a real
    affected-component citation, but NO manifest at all, must read
    NOT_AVAILABLE -- never silently collapsed into RTL_NOT_LOCATED, which
    would misrepresent 'we could not check' as a real negative finding."""
    doc_record = dxc.extract_errata_document(errata_pdf, tmp_path / "out")
    missing_manifest = tmp_path / "does_not_exist" / "env.manifest.json"
    report = dxc.correlate_errata(doc_record["errata"], missing_manifest)
    assert report["manifest_status"] == "NOT_AVAILABLE"
    by_id = {r["erratum_id"]: r for r in report["errata"]}
    assert by_id["1"]["correlation_status"] == dxc.STATUS_NOT_AVAILABLE
    assert by_id["1"]["citations"][0]["status"] == dec.STATUS_NOT_AVAILABLE
    assert by_id["ERR002"]["correlation_status"] == dxc.STATUS_NOT_AVAILABLE
    # the citation-free erratum stays NO_AFFECTED_COMPONENT_CITED regardless
    # of manifest availability -- it never had anything to correlate.
    assert by_id["3"]["correlation_status"] == dxc.STATUS_NO_AFFECTED_COMPONENT_CITED
    assert report["summary"][dxc.STATUS_NOT_AVAILABLE] == 2
    assert report["summary"][dxc.STATUS_RTL_NOT_LOCATED] == 0


def test_correlate_errata_with_none_manifest_path(errata_pdf, tmp_path):
    doc_record = dxc.extract_errata_document(errata_pdf, tmp_path / "out")
    report = dxc.correlate_errata(doc_record["errata"], None)
    assert report["manifest_status"] == "NOT_AVAILABLE"
    assert "manifest_reason" not in report  # None path is distinct from a real missing-path reason


def test_invalid_manifest_propagates_validation_error(tmp_path, errata_pdf):
    doc_record = dxc.extract_errata_document(errata_pdf, tmp_path / "out")
    bad = tmp_path / "env.manifest.json"
    bad.write_text(json.dumps({"schema_version": "1.2", "not_a_valid_manifest": True}), encoding="utf-8")
    with pytest.raises(env_manifest.EnvManifestValidationError):
        dxc.correlate_errata(doc_record["errata"], bad)


# ---------------------------------------------------------------------------
# The one-shot `analyze_errata()` front door -- the mandatory
# "no errata document supplied" -> NOT_AVAILABLE contract.
# ---------------------------------------------------------------------------

def test_analyze_errata_with_no_source_is_honestly_not_available(tmp_path):
    report = dxc.analyze_errata(None, tmp_path / "env.manifest.json")
    assert report["status"] == dxc.STATUS_NOT_AVAILABLE
    assert "no errata" in report["reason"].lower()
    assert report["errata"] == []
    assert report["erratum_count"] == 0
    assert report["summary"] == {s: 0 for s in dxc.ERRATUM_CORRELATION_STATUSES}


def test_analyze_errata_with_empty_string_source_is_not_available(tmp_path):
    report = dxc.analyze_errata("", tmp_path / "env.manifest.json")
    assert report["status"] == dxc.STATUS_NOT_AVAILABLE


def test_analyze_errata_with_missing_source_file_is_not_available(tmp_path):
    report = dxc.analyze_errata(str(tmp_path / "nope.pdf"), tmp_path / "env.manifest.json")
    assert report["status"] == dxc.STATUS_NOT_AVAILABLE
    assert "does not exist" in report["reason"]


@requires_verible
def test_analyze_errata_end_to_end(tmp_path, errata_pdf, full_manifest_path):
    report = dxc.analyze_errata(str(errata_pdf), str(full_manifest_path), tmp_path / "out")
    assert report["status"] == "ANALYZED"
    assert report["manifest_status"] == "LOADED"
    assert report["erratum_count"] == 3
    assert report["summary"][dxc.STATUS_RTL_LOCATED] == 1
    assert report["summary"][dxc.STATUS_RTL_NOT_LOCATED] == 1
    assert report["structure_map"]["path"]


# ---------------------------------------------------------------------------
# CLI front door
# ---------------------------------------------------------------------------

def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.dut_errata_correlation", *args],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )


def test_cli_extract_and_show(tmp_path, errata_pdf):
    out_dir = tmp_path / "out"
    proc = _run_cli("extract", "--source", str(errata_pdf), "--out-dir", str(out_dir), "--json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "EXTRACTED"
    assert payload["erratum_count"] == 3

    show = _run_cli("show", "--record", str(out_dir / "dut_errata.errata_index.json"), "--json")
    assert show.returncode == 0, show.stderr
    shown = json.loads(show.stdout)
    assert shown["erratum_count"] == 3


def test_cli_extract_missing_source_exits_two(tmp_path):
    proc = _run_cli("extract", "--source", str(tmp_path / "nope.pdf"), "--out-dir", str(tmp_path / "out"))
    assert proc.returncode == 2
    assert "NOT_AVAILABLE" in proc.stdout


@requires_verible
def test_cli_correlate_exits_one_on_real_not_located_finding(tmp_path, errata_pdf, full_manifest_path):
    out_dir = tmp_path / "out"
    _run_cli("extract", "--source", str(errata_pdf), "--out-dir", str(out_dir))
    proc = _run_cli(
        "correlate", "--errata-index", str(out_dir / "dut_errata.errata_index.json"),
        "--manifest", str(full_manifest_path), "--json",
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["summary"][dxc.STATUS_RTL_NOT_LOCATED] == 1


def test_cli_correlate_no_manifest_exits_two_not_available(tmp_path, errata_pdf):
    out_dir = tmp_path / "out"
    _run_cli("extract", "--source", str(errata_pdf), "--out-dir", str(out_dir))
    proc = _run_cli(
        "correlate", "--errata-index", str(out_dir / "dut_errata.errata_index.json"), "--json",
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["manifest_status"] == "NOT_AVAILABLE"


def test_cli_analyze_no_source_exits_two_not_available(tmp_path):
    proc = _run_cli("analyze", "--manifest", str(tmp_path / "env.manifest.json"))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "NOT_AVAILABLE" in proc.stdout


@requires_verible
def test_cli_analyze_end_to_end_exit_one_on_real_finding(tmp_path, errata_pdf, full_manifest_path):
    proc = _run_cli(
        "analyze", "--source", str(errata_pdf), "--manifest", str(full_manifest_path),
        "--out-dir", str(tmp_path / "out"), "--json",
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ANALYZED"
    assert payload["summary"][dxc.STATUS_RTL_LOCATED] == 1


def test_cli_unknown_verb_via_execute_verb():
    text, code = dxc.execute_verb("bogus")
    assert code == 2
    assert "unknown verb" in text
