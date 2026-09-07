"""Tests for dv_harness/artifact_relationship_discovery.py -- discovering
real, shared-identifier relationships between design_source_inventory
registry rows.

Real artifacts throughout: a real RTL file parsed by the real
verible-verilog-syntax subprocess (skipped, never faked, on a machine
without it on PATH -- same discipline test_design_architecture_ir.py already
uses), a real register-map JSON validated against the real
register_map.schema.json via env_manifest.load_register_map(), and real
plain-text/Markdown "spec doc" fixtures scanned by this module's own real
line-based extractor. Registry rows are built through the real
design_source_inventory.build_source_registry()/evaluate_source(), never
hand-shaped to merely look like that module's output.
"""
from __future__ import annotations

import json
import shutil
import textwrap
from pathlib import Path

import pytest

from dv_harness import artifact_relationship_discovery as ard
from dv_harness import design_source_inventory as dsi

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)


REGISTER_MAP_DOC = {
    "schema_version": "1.0",
    "blocks": [
        {
            "name": "USB3_LINK_CTRL",
            "base_address": "0x1000",
            "registers": [
                {
                    "name": "CTRL0",
                    "address_offset": "0x0",
                    "width": 32,
                    "access": "RW",
                    "fields": [
                        {"name": "LINK_ENABLE", "bit_offset": 0, "bit_width": 1, "access": "RW"},
                    ],
                },
            ],
        },
    ],
}


def _write_register_map(tmp_path: Path) -> Path:
    p = tmp_path / "regmap.json"
    p.write_text(json.dumps(REGISTER_MAP_DOC), encoding="utf-8")
    return p


def _write_rtl(tmp_path: Path) -> Path:
    p = tmp_path / "usb3_link_ctrl.sv"
    p.write_text(textwrap.dedent("""\
        module usb3_link_ctrl #(
            parameter WIDTH = 32
        ) (
            input  logic clk,
            input  logic rst_n,
            output logic link_up
        );
        endmodule
        """), encoding="utf-8")
    return p


def _write_spec_doc(tmp_path: Path, *, mention_block: bool, mention_module: bool = False) -> Path:
    lines = ["# USB3 Link Controller Spec", ""]
    if mention_block:
        lines.append("The USB3_LINK_CTRL register block configures link training.")
    if mention_module:
        lines.append("Instantiate usb3_link_ctrl at the top level.")
    lines.append("This document also mentions the ordinary word register several times.")
    p = tmp_path / "spec.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _row(source_id: str, path: Path, kind_type: str = "generic") -> dict:
    """A REAL design_source_inventory registry row (via evaluate_source()),
    never a hand-shaped stand-in for its output shape."""
    return dsi.evaluate_source(dsi.SourceEntry(source_id=source_id, type=kind_type, path=str(path)))


# ---------------------------------------------------------------------------
# 1. Per-kind extraction
# ---------------------------------------------------------------------------

def test_extract_from_register_map_yields_block_register_field_identifiers(tmp_path):
    path = _write_register_map(tmp_path)
    result = ard.extract_identifiers_from_entry(_row("REG1", path))
    assert result.status == ard.STATUS_EXTRACTED
    names = {(i.name, i.kind) for i in result.identifiers}
    assert ("USB3_LINK_CTRL", ard.KIND_BLOCK) in names
    assert ("CTRL0", ard.KIND_REGISTER) in names
    assert ("LINK_ENABLE", ard.KIND_FIELD) in names
    # Real structural locators, no invented line numbers.
    block_ident = next(i for i in result.identifiers if i.kind == ard.KIND_BLOCK)
    assert block_ident.locator == "block:USB3_LINK_CTRL"


def test_extract_from_register_map_rejects_a_non_register_map_json(tmp_path):
    path = tmp_path / "not_a_regmap.json"
    path.write_text(json.dumps({"totally": "unrelated"}), encoding="utf-8")
    result = ard.extract_identifiers_from_entry(_row("BAD1", path))
    assert result.status == ard.STATUS_NOT_AVAILABLE
    assert "NOT_A_REGISTER_MAP_DOCUMENT" in result.reason
    assert result.identifiers == []


@requires_verible
def test_extract_from_rtl_yields_module_parameter_port_identifiers(tmp_path):
    path = _write_rtl(tmp_path)
    result = ard.extract_identifiers_from_entry(_row("RTL1", path))
    assert result.status == ard.STATUS_EXTRACTED
    names = {(i.name, i.kind) for i in result.identifiers}
    assert ("usb3_link_ctrl", ard.KIND_MODULE) in names
    assert ("WIDTH", ard.KIND_PARAMETER) in names
    assert ("clk", ard.KIND_PORT) in names
    assert ("link_up", ard.KIND_PORT) in names


def test_extract_from_rtl_reports_not_available_when_verible_missing(tmp_path, monkeypatch):
    from dv_harness import verible_parser

    def _boom(*a, **k):
        raise verible_parser.VeribleUnavailableError("simulated: not on PATH")

    monkeypatch.setattr(verible_parser, "run_export_json", _boom)
    path = _write_rtl(tmp_path)
    result = ard.extract_identifiers_from_entry(_row("RTL2", path))
    assert result.status == ard.STATUS_NOT_AVAILABLE
    assert "VERIBLE_UNAVAILABLE" in result.reason
    assert result.identifiers == []


def test_extract_from_text_finds_designed_looking_tokens_with_real_line_citations(tmp_path):
    path = _write_spec_doc(tmp_path, mention_block=True)
    result = ard.extract_identifiers_from_entry(_row("SPEC1", path))
    assert result.status == ard.STATUS_EXTRACTED
    tokens = {i.name for i in result.identifiers}
    assert "USB3_LINK_CTRL" in tokens
    ident = next(i for i in result.identifiers if i.name == "USB3_LINK_CTRL")
    assert ident.kind == ard.KIND_TOKEN
    assert ident.locator.startswith("line:")
    # Plain lowercase English prose words never pass the shape filter.
    assert "the" not in tokens
    assert "register" not in tokens
    assert "document" not in tokens


def test_extract_from_text_excludes_stopwords_even_when_shaped_like_a_token(tmp_path):
    path = tmp_path / "doc.txt"
    path.write_text("See TABLE 3 for details. Also see FIGURE 2 and the APPENDIX.\n",
                     encoding="utf-8")
    result = ard.extract_identifiers_from_entry(_row("SPEC2", path))
    tokens = {i.name.upper() for i in result.identifiers}
    assert "TABLE" not in tokens
    assert "FIGURE" not in tokens
    assert "APPENDIX" not in tokens


def test_extract_from_pdf_reports_not_available_with_no_distilled_fulltext(tmp_path):
    pdf_path = tmp_path / "spec.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    result = ard.extract_identifiers_from_entry(_row("PDF1", pdf_path))
    assert result.status == ard.STATUS_NOT_AVAILABLE
    assert "NO_DISTILLED_FULLTEXT" in result.reason
    assert "spec.fulltext.txt" in result.reason


def test_extract_from_pdf_reads_the_real_distilled_fulltext_sibling(tmp_path):
    pdf_path = tmp_path / "spec.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    fulltext = tmp_path / "spec.fulltext.txt"
    fulltext.write_text("The USB3_LINK_CTRL block is documented here.\n", encoding="utf-8")
    result = ard.extract_identifiers_from_entry(_row("PDF2", pdf_path))
    assert result.status == ard.STATUS_EXTRACTED
    assert result.path == str(pdf_path)
    names = {i.name for i in result.identifiers}
    assert "USB3_LINK_CTRL" in names


def test_extract_reports_not_available_for_unsupported_suffix(tmp_path):
    path = tmp_path / "waveform.fsdb"
    path.write_bytes(b"binary junk")
    result = ard.extract_identifiers_from_entry(_row("BIN1", path))
    assert result.status == ard.STATUS_NOT_AVAILABLE
    assert "UNSUPPORTED_ARTIFACT_KIND" in result.reason


def test_extract_reports_not_available_for_missing_path(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    result = ard.extract_identifiers_from_entry(_row("MISS1", missing))
    assert result.status == ard.STATUS_NOT_AVAILABLE
    assert "PATH_DOES_NOT_EXIST" in result.reason


def test_extract_reports_not_available_for_no_path_at_all():
    result = ard.extract_identifiers_from_entry({"source_id": "NOPATH1"})
    assert result.status == ard.STATUS_NOT_AVAILABLE
    assert "NO_PATH_SUPPLIED" in result.reason


def test_extract_reports_not_available_for_a_directory(tmp_path):
    d = tmp_path / "adir"
    d.mkdir()
    result = ard.extract_identifiers_from_entry(_row("DIR1", d))
    assert result.status == ard.STATUS_NOT_AVAILABLE
    assert "IS_A_DIRECTORY" in result.reason


def test_extract_raises_when_entry_has_no_source_id(tmp_path):
    with pytest.raises(ard.ArtifactRelationshipDiscoveryError) as exc:
        ard.extract_identifiers_from_entry({"path": str(tmp_path / "x.json")})
    assert exc.value.reason == "SOURCE_ID_MUST_BE_STATED"


# ---------------------------------------------------------------------------
# 2. Relationship discovery -- the headline "register map <-> spec doc" case
# ---------------------------------------------------------------------------

def test_discovers_a_real_relationship_between_register_map_and_spec_doc(tmp_path):
    """This module's own worked example: a register-map file's real BLOCK
    name is a NAMED ENTITY, cited by a spec doc that mentions it -- reported
    as a real relationship, never inferred from file naming alone."""
    regmap_path = _write_register_map(tmp_path)
    spec_path = _write_spec_doc(tmp_path, mention_block=True)
    entries = [_row("REGMAP", regmap_path), _row("SPEC", spec_path)]

    report = ard.discover_relationships(entries)

    assert report.artifact_count == 2
    matches = [r for r in report.relationships if r.identifier == "usb3_link_ctrl"]
    assert len(matches) == 1
    rel = matches[0]
    assert {rel.artifact_a, rel.artifact_b} == {"REGMAP", "SPEC"}
    kinds = {rel.kind_a, rel.kind_b}
    assert ard.KIND_BLOCK in kinds
    assert ard.KIND_TOKEN in kinds


def test_no_relationship_reported_when_spec_doc_never_mentions_the_block(tmp_path):
    regmap_path = _write_register_map(tmp_path)
    spec_path = _write_spec_doc(tmp_path, mention_block=False)
    entries = [_row("REGMAP", regmap_path), _row("SPEC", spec_path)]

    report = ard.discover_relationships(entries)

    assert report.relationships == []


def test_anti_false_positive_two_spec_docs_sharing_only_a_generic_token_are_not_related(tmp_path):
    """Two text-only artifacts sharing a scanned prose TOKEN (not a real
    named entity on either side) must never be reported as related -- see
    this module's own ANTI-FALSE-POSITIVE RULE."""
    doc_a = tmp_path / "a.md"
    doc_a.write_text("This section describes the SOME_SHARED_TOKEN behavior.\n", encoding="utf-8")
    doc_b = tmp_path / "b.md"
    doc_b.write_text("Another unrelated document also names SOME_SHARED_TOKEN here.\n",
                      encoding="utf-8")
    entries = [_row("DOCA", doc_a), _row("DOCB", doc_b)]

    report = ard.discover_relationships(entries)

    assert report.relationships == []
    # Confirm the token really was extracted on both sides -- the absence of
    # a relationship is the anti-false-positive rule firing, not a failure
    # to extract anything at all.
    assert any(i.name == "SOME_SHARED_TOKEN"
               for i in report.extraction_results["DOCA"].identifiers)
    assert any(i.name == "SOME_SHARED_TOKEN"
               for i in report.extraction_results["DOCB"].identifiers)


@requires_verible
def test_two_rtl_files_sharing_a_real_parameter_name_are_related(tmp_path):
    """A named-entity <-> named-entity match (both real RTL parameter
    names, from two DIFFERENT modules) is reported even though neither side
    is prose -- proving matching is not limited to text-scanned tokens."""
    a_dir = tmp_path / "a"
    b_dir = tmp_path / "b"
    a_dir.mkdir()
    b_dir.mkdir()
    path_a = a_dir / "branch_a0.sv"
    path_a.write_text(textwrap.dedent("""\
        module branch_a0 #(
            parameter LANE_WIDTH = 4
        ) (input logic clk);
        endmodule
        """), encoding="utf-8")
    path_b = b_dir / "branch_a1.sv"
    path_b.write_text(textwrap.dedent("""\
        module branch_a1 #(
            parameter LANE_WIDTH = 4
        ) (input logic clk);
        endmodule
        """), encoding="utf-8")

    entries = [_row("A0", path_a), _row("A1", path_b)]
    report = ard.discover_relationships(entries)

    matches = [r for r in report.relationships if r.identifier == "lane_width"]
    assert len(matches) == 1
    rel = matches[0]
    assert rel.kind_a == ard.KIND_PARAMETER
    assert rel.kind_b == ard.KIND_PARAMETER
    assert {rel.name_a, rel.name_b} == {"LANE_WIDTH"}
    # `clk` (a real shared PORT name too) must also be discovered -- proves
    # more than one shared identifier per artifact pair is reported.
    assert any(r.identifier == "clk" for r in report.relationships)


def test_unresolved_artifacts_are_surfaced_honestly(tmp_path):
    missing = tmp_path / "gone.json"
    present = _write_register_map(tmp_path)
    entries = [_row("GONE", missing), _row("PRESENT", present)]

    report = ard.discover_relationships(entries)

    assert len(report.unresolved_artifacts) == 1
    assert report.unresolved_artifacts[0]["source_id"] == "GONE"
    assert "PATH_DOES_NOT_EXIST" in report.unresolved_artifacts[0]["reason"]


def test_extraction_results_are_reused_when_supplied(tmp_path):
    regmap_path = _write_register_map(tmp_path)
    entry = _row("REGMAP", regmap_path)
    first = ard.discover_relationships([entry])
    cached = dict(first.extraction_results)
    # Delete the file on disk -- if the cache is genuinely reused, a second
    # call must not re-extract (and therefore must not fail).
    regmap_path.unlink()
    second = ard.discover_relationships([entry], extraction_results=cached)
    assert second.extraction_results["REGMAP"].status == ard.STATUS_EXTRACTED


def test_discover_relationships_from_registry_uses_the_real_build_source_registry_shape(tmp_path):
    regmap_path = _write_register_map(tmp_path)
    spec_path = _write_spec_doc(tmp_path, mention_block=True)
    registry = dsi.build_source_registry([
        dsi.SourceEntry(source_id="REGMAP", type="register_file", path=str(regmap_path)),
        dsi.SourceEntry(source_id="SPEC", type="spec_doc", path=str(spec_path)),
    ])
    report = ard.discover_relationships_from_registry(registry)
    assert report.artifact_count == 2
    assert any(r.identifier == "usb3_link_ctrl" for r in report.relationships)


def test_discover_relationships_from_registry_rejects_a_shape_with_no_sources_key():
    with pytest.raises(ard.ArtifactRelationshipDiscoveryError) as exc:
        ard.discover_relationships_from_registry({"not_sources": []})
    assert exc.value.reason == "REGISTRY_HAS_NO_SOURCES_LIST"


def test_render_relationships_markdown_includes_counts_and_unresolved_section(tmp_path):
    regmap_path = _write_register_map(tmp_path)
    spec_path = _write_spec_doc(tmp_path, mention_block=True)
    missing = tmp_path / "gone.txt"
    entries = [_row("REGMAP", regmap_path), _row("SPEC", spec_path), _row("GONE", missing)]
    report = ard.discover_relationships(entries)
    text = ard.render_relationships_markdown(report)
    assert "Artifacts examined: 3" in text
    assert "Relationships discovered: 1" in text
    assert "Unresolved artifacts: 1" in text
    assert "GONE" in text


# ---------------------------------------------------------------------------
# 3. CLI front door
# ---------------------------------------------------------------------------

def test_cli_finds_a_relationship_and_exits_zero(tmp_path, capsys):
    regmap_path = _write_register_map(tmp_path)
    spec_path = _write_spec_doc(tmp_path, mention_block=True)
    registry = dsi.build_source_registry([
        dsi.SourceEntry(source_id="REGMAP", type="register_file", path=str(regmap_path)),
        dsi.SourceEntry(source_id="SPEC", type="spec_doc", path=str(spec_path)),
    ])
    sources_file = tmp_path / "registry.json"
    sources_file.write_text(json.dumps(registry), encoding="utf-8")

    rc = ard.main(["--sources", str(sources_file), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["artifact_count"] == 2
    assert len(out["relationships"]) >= 1


def test_cli_exits_one_when_no_relationships_found(tmp_path, capsys):
    spec_path = _write_spec_doc(tmp_path, mention_block=False)
    sources_file = tmp_path / "registry.json"
    sources_file.write_text(json.dumps([{"source_id": "SPEC", "path": str(spec_path)}]),
                             encoding="utf-8")
    rc = ard.main(["--sources", str(sources_file)])
    capsys.readouterr()
    assert rc == 1


def test_cli_exits_two_on_unreadable_sources_file(tmp_path, capsys):
    rc = ard.main(["--sources", str(tmp_path / "nope.json")])
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.err
