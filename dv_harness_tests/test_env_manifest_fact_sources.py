"""Tests for the four env.manifest.json fact sources added on 2026-09-04,
each of which a re-audit that day confirmed BLOCKED (absent, not stubbed):

  1. vip_config.vip_release            -- a REAL $DESIGNWARE_HOME scan.
  2. vip_config.user_guide_refs        -- OFFLINE-distilled user guides,
                                          recorded as pointers only.
  3. dut_facts.address_map/clock_reset -- the SoC-spec-pipeline fact source,
                                          with a real cross-check against
                                          dut_facts.registers.
  4. env_topology.testplan_correspondence -- the testlist/vPlan/coverage
                                          three-way join.

Two disciplines these tests deliberately hold to, matching
test_env_manifest.py's own:

  * Every fixture is a small, clearly-synthesized artifact built inside the
    test (a fake DesignWare tree made of real directories and real files, a
    hand-written SoC arch map). None is presented as captured project
    content, per CLAUDE.md's Evidence Truth Rule / No Golden-Reference
    Content Mining.
  * The PDF path is exercised against the ONE real PDF this repo actually
    contains (docs/DV_Agent_Harness_L5_Detailed_User_Guide_TC.pdf) rather
    than a synthesized byte string, because "pypdf really extracts text from
    a real PDF" is precisely the claim that a hand-rolled fake PDF would let
    pass while being false. It skips (never fakes) if that file is absent.
"""
from __future__ import annotations

import json

import pytest

from dv_harness import env_manifest, vip_user_guide_distill
from dv_harness.env_manifest import (
    EnvManifestValidationError,
    SocArchMapValidationError,
    assert_no_user_guide_body_in_manifest,
    build_dut_facts,
    build_dut_facts_address_map,
    build_dut_facts_clock_reset,
    build_dut_facts_registers,
    build_testplan_correspondence,
    build_user_guide_refs,
    build_vip_release,
    generate_env_manifest,
    load_soc_arch_map,
    load_testplan_sources,
    scan_designware_home,
    summarize_for_blackboard,
)
from dv_harness.vip_user_guide_distill import UserGuideDistillError, distill_user_guide

REPO_PDF = "docs/DV_Agent_Harness_L5_Detailed_User_Guide_TC.pdf"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_designware_home(tmp_path):
    """A REAL directory tree in the layout `dw_vip_setup` produces --
    $DESIGNWARE_HOME/vip/svt/<package>/<version>/ -- containing real files.
    Clearly synthesized test data; the point is that the scanner walks real
    directories and hashes real bytes, not that this is a real VIP."""
    home = tmp_path / "designware"
    usb = home / "vip" / "svt" / "usb_svt" / "R-2020.12"
    (usb / "doc").mkdir(parents=True)
    (usb / "doc" / "usb_svt_release_notes.txt").write_text(
        "usb_svt R-2020.12 release notes (synthesized test fixture)\n", encoding="utf-8")
    (usb / "doc" / "usb_svt_feature_matrix.html").write_text(
        "<html>feature matrix (synthesized test fixture)</html>\n", encoding="utf-8")
    # A second package whose install ships NO feature matrix -- the honest
    # all-null doc_file_ref path.
    apb = home / "vip" / "svt" / "amba_svt" / "Q-2019.06"
    (apb / "doc").mkdir(parents=True)
    (apb / "doc" / "ReleaseNotes.html").write_text("<html>amba rel notes</html>\n", encoding="utf-8")
    return home


@pytest.fixture()
def register_map_file(tmp_path):
    doc = {
        "schema_version": "1.0",
        "source": {"kind": "ral_model_export", "description": "synthesized test fixture"},
        "blocks": [
            {"name": "CTRL_BLOCK", "base_address": "0x1000", "registers": [
                {"name": "CTRL", "address_offset": "0x0", "width": 32, "access": "RW"}]},
            {"name": "DMA_BLOCK", "base_address": "0x2000", "registers": []},
        ],
    }
    p = tmp_path / "register_map.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


@pytest.fixture()
def soc_arch_map_file(tmp_path):
    """CTRL_BLOCK agrees with the register map's 0x1000; DMA_BLOCK is
    deliberately at 0x3000 where the register map says 0x2000 (a real
    DISAGREES); MISC_BLOCK is in no register map at all."""
    doc = {
        "schema_version": "1.0",
        "source": {"kind": "soc_spec_pipeline_export", "description": "synthesized test fixture"},
        "address_map": [
            {"name": "MISC_BLOCK", "base_address": "0x4000", "size_bytes": 256, "bus": "APB"},
            {"name": "CTRL_BLOCK", "base_address": "0x1000", "size_bytes": 4096,
             "target": "chip.core.ctrl0", "evidence": "rtl/decoder.sv:88"},
            {"name": "DMA_BLOCK", "base_address": "0x3000", "size_bytes": 4096},
        ],
        "clocks": [
            {"name": "pclk", "frequency_mhz": 100.0, "source": "pll0_div4", "domain": "apb"},
            {"name": "aclk", "frequency_mhz": 400.0},
        ],
        "resets": [
            {"name": "presetn", "active_level": "low", "synchronous": True, "clock": "pclk"},
            {"name": "aresetn", "active_level": "low", "synchronous": False, "clock": "nonexistent_clk"},
            {"name": "por_n", "active_level": "low"},
        ],
    }
    p = tmp_path / "soc_arch_map.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


@pytest.fixture()
def testplan_sources_file(tmp_path):
    doc = {
        "schema_version": "1.0",
        "source": {"kind": "regression_list_plus_vplan_export", "description": "synthesized test fixture"},
        "testlist": [
            {"name": "smoke_test", "tier": "SMOKE"},
            {"name": "burst_test", "tier": "NIGHTLY"},
            {"name": "orphan_test", "tier": "WEEKLY"},
        ],
        "vplan_items": [
            {"id": "VP-001", "tests": ["smoke_test"], "coverage": ["cg_link_state"]},
            {"id": "VP-002", "tests": ["never_written_test"], "coverage": []},
            {"id": "VP-003", "tests": ["burst_test"], "coverage": ["cg_never_written"]},
            {"id": "VP-004", "tests": [], "coverage": []},
        ],
        "coverage_model": [
            {"name": "cg_link_state", "kind": "covergroup", "file": "tb/cov.sv", "line": 10},
            {"name": "cg_orphan", "kind": "covergroup"},
        ],
    }
    p = tmp_path / "testplan_sources.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 1. vip_config.vip_release -- real $DESIGNWARE_HOME scan
# ---------------------------------------------------------------------------

def test_scan_designware_home_finds_real_packages_versions_and_docs(fake_designware_home):
    packages = scan_designware_home(fake_designware_home)
    assert [(p["name"], p["version"]) for p in packages] == [
        ("amba_svt", "Q-2019.06"), ("usb_svt", "R-2020.12"),
    ], "packages must be sorted by (name, version) for a stable diff"

    usb = [p for p in packages if p["name"] == "usb_svt"][0]
    # Real file, really hashed -- not a placeholder.
    assert usb["release_notes"]["path"].endswith("usb_svt_release_notes.txt")
    assert len(usb["release_notes"]["sha256"]) == 64
    assert usb["release_notes"]["bytes"] > 0
    assert usb["feature_matrix"]["path"].endswith("usb_svt_feature_matrix.html")

    amba = [p for p in packages if p["name"] == "amba_svt"][0]
    assert amba["release_notes"]["path"].endswith("ReleaseNotes.html"), "case-insensitive fragment match"
    # This package genuinely ships no feature matrix: an all-null ref, so
    # "looked, and there is none" stays visible rather than being omitted.
    assert amba["feature_matrix"] == {"path": None, "sha256": None, "bytes": None}


def test_scan_designware_home_never_reads_document_content(fake_designware_home):
    """The release notes/feature matrix are recorded as path+sha256+bytes.
    Their TEXT must appear nowhere in the scan result -- env.manifest.json is
    a tier-2 always-resident artifact under CLAUDE.md's Context Budget."""
    blob = json.dumps(scan_designware_home(fake_designware_home))
    assert "synthesized test fixture" not in blob
    assert "feature matrix" not in blob


def test_build_vip_release_unset_env_is_honest_not_available(monkeypatch):
    monkeypatch.delenv(env_manifest.DESIGNWARE_HOME_ENV, raising=False)
    layer = build_vip_release()
    assert layer["status"] == "NOT_AVAILABLE"
    assert layer["designware_home"] is None
    assert layer["source"]["path"] is None
    assert "is not set" in layer["reason"]
    assert layer["packages"] == []


def test_build_vip_release_reads_the_real_env_var(monkeypatch, fake_designware_home):
    monkeypatch.setenv(env_manifest.DESIGNWARE_HOME_ENV, str(fake_designware_home))
    layer = build_vip_release()
    assert layer["status"] == "SCANNED"
    assert layer["designware_home"] == str(fake_designware_home)
    assert {p["name"] for p in layer["packages"]} == {"usb_svt", "amba_svt"}


def test_build_vip_release_stale_path_is_distinct_from_unset(monkeypatch, tmp_path):
    """An unset DESIGNWARE_HOME and a typo'd/stale one are different operator
    situations; collapsing them would hide a real, fixable mistake."""
    stale = tmp_path / "no_such_designware"
    monkeypatch.setenv(env_manifest.DESIGNWARE_HOME_ENV, str(stale))
    layer = build_vip_release()
    assert layer["status"] == "NOT_AVAILABLE"
    # The real bad path survives into the manifest so it stays diagnosable.
    assert layer["source"]["path"] == str(stale)
    assert layer["designware_home"] == str(stale)
    assert "not an existing directory" in layer["reason"]


def test_build_vip_release_explicit_path_overrides_env(monkeypatch, fake_designware_home, tmp_path):
    monkeypatch.setenv(env_manifest.DESIGNWARE_HOME_ENV, str(tmp_path / "ignored"))
    layer = build_vip_release(fake_designware_home)
    assert layer["status"] == "SCANNED"
    assert layer["designware_home"] == str(fake_designware_home)


def test_build_vip_release_reports_vendor_and_layout(monkeypatch, fake_designware_home):
    """Every real package found through the nested dw_vip_setup layout is
    'centralized', and the release layer records which vendor convention was
    actually used -- so a manifest reader never has to guess."""
    monkeypatch.setenv(env_manifest.DESIGNWARE_HOME_ENV, str(fake_designware_home))
    layer = build_vip_release()
    assert layer["vendor"] == "synopsys"
    assert {p["layout"] for p in layer["packages"]} == {"centralized"}


# ---------------------------------------------------------------------------
# 1b. vip_config.vip_release -- other vendors' VIP-home variables (VIP-01)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("vendor,env_var", [("cadence", "CDNS_VIP_HOME"), ("mentor", "MGC_VIP_HOME")])
def test_build_vip_release_falls_back_to_other_vendor_home_vars(monkeypatch, tmp_path, vendor, env_var):
    """With $DESIGNWARE_HOME unset, a Cadence- or Mentor/Siemens-only project
    (their own home variable set instead) still gets a real SCANNED result
    rather than a permanent, unexplained NOT_AVAILABLE (VIP-01)."""
    monkeypatch.delenv(env_manifest.DESIGNWARE_HOME_ENV, raising=False)
    home = tmp_path / "vendor_home"
    pkg = home / "vip" / "some_ip_svt" / "1.0"
    pkg.mkdir(parents=True)
    monkeypatch.setenv(env_var, str(home))
    layer = build_vip_release()
    assert layer["status"] == "SCANNED"
    assert layer["vendor"] == vendor
    assert layer["designware_home"] == str(home)
    assert [(p["name"], p["version"]) for p in layer["packages"]] == [("some_ip_svt", "1.0")]


def test_build_vip_release_designware_home_wins_over_other_vendors(monkeypatch, fake_designware_home, tmp_path):
    """$DESIGNWARE_HOME is checked first: when it is set, it is used even if
    a Cadence/Mentor variable also happens to be set."""
    monkeypatch.setenv(env_manifest.DESIGNWARE_HOME_ENV, str(fake_designware_home))
    monkeypatch.setenv("CDNS_VIP_HOME", str(tmp_path / "ignored_cadence_home"))
    layer = build_vip_release()
    assert layer["vendor"] == "synopsys"
    assert layer["designware_home"] == str(fake_designware_home)


def test_build_vip_release_unset_reason_names_all_checked_vendor_vars(monkeypatch):
    monkeypatch.delenv(env_manifest.DESIGNWARE_HOME_ENV, raising=False)
    monkeypatch.delenv("CDNS_VIP_HOME", raising=False)
    monkeypatch.delenv("MGC_VIP_HOME", raising=False)
    layer = build_vip_release()
    assert layer["status"] == "NOT_AVAILABLE"
    assert layer["vendor"] is None
    assert "CDNS_VIP_HOME" in layer["reason"]
    assert "MGC_VIP_HOME" in layer["reason"]


# ---------------------------------------------------------------------------
# 1c. scan_designware_home -- flat, per-project VIP copy layout (VIP-02)
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_flat_vip_home(tmp_path):
    """A REAL per-project private VIP copy, laid out flat as
    `{doc,examples,include,lib,src}` directly under the VIP-home directory
    itself -- never routed through a centralized `dw_vip_setup` install.
    This is the real, on-disk shape of this project's own Synopsys USB SVT
    VIP (see .work/intake-vip_source-report.md), which the nested-root-only
    scan silently reported as empty before VIP-02 was closed."""
    home = tmp_path / "USB" / "VIP"
    (home / "doc").mkdir(parents=True)
    (home / "examples").mkdir()
    (home / "include").mkdir()
    (home / "lib").mkdir()
    (home / "src").mkdir()
    (home / "doc" / "usb_svt_release_notes.txt").write_text("flat-layout release notes\n", encoding="utf-8")
    return home


def test_scan_designware_home_discovers_a_flat_project_vip_copy(fake_flat_vip_home):
    packages = scan_designware_home(fake_flat_vip_home)
    assert len(packages) == 1
    pkg = packages[0]
    # "VIP" itself is too generic a package name -- the parent ("USB")
    # is used instead.
    assert pkg["name"] == "USB"
    assert pkg["version"] is None
    assert pkg["layout"] == "flat_project_copy"
    assert pkg["install_path"] == str(fake_flat_vip_home)
    assert pkg["release_notes"]["path"].endswith("usb_svt_release_notes.txt")


def test_scan_designware_home_flat_layout_needs_at_least_two_markers(tmp_path):
    """A bare `src/` alone is too common on an arbitrary directory to be
    treated as proof it holds a VIP -- this must stay a real empty finding,
    not a false positive."""
    lonely = tmp_path / "just_some_src_dir"
    (lonely / "src").mkdir(parents=True)
    assert scan_designware_home(lonely) == []


def test_build_vip_release_with_flat_layout_end_to_end(monkeypatch, fake_flat_vip_home):
    monkeypatch.setenv(env_manifest.DESIGNWARE_HOME_ENV, str(fake_flat_vip_home))
    layer = build_vip_release()
    assert layer["status"] == "SCANNED"
    assert [p["layout"] for p in layer["packages"]] == ["flat_project_copy"]


# ---------------------------------------------------------------------------
# 2. vip_config.user_guide_refs -- offline distillation, pointers only
# ---------------------------------------------------------------------------

def test_distill_text_source_builds_real_section_index(tmp_path):
    src = tmp_path / "vip_guide.txt"
    src.write_text(
        "Front matter paragraph that is not a heading.\n"
        "1 Introduction\n"
        "The VIP supports two modes.\n"
        "2.1 Configuration Objects\n"
        "Set the config before build_phase.\n"
        "3.2 shows the resulting waveform for the case above, which is a body line.\n",
        encoding="utf-8",
    )
    record = distill_user_guide(src, tmp_path / "out", doc_kind="vip_user_guide")

    assert record["extraction"] == {"tool": "builtin", "tool_version": None,
                                    "method": "pre_extracted_text"}
    # A text source is not paginated -- honestly null, never a fabricated count.
    assert record["source_document"]["page_count"] is None
    assert record["section_count"] == 2, "the trailing sentence-punctuated body line is not a heading"

    md = (tmp_path / "out" / "vip_guide.reference.md").read_text(encoding="utf-8")
    assert "1 Introduction" in md and "2.1 Configuration Objects" in md
    assert "3.2 shows the resulting waveform" not in md
    # The full text really is preserved for a targeted read.
    fulltext = (tmp_path / "out" / "vip_guide.fulltext.txt").read_text(encoding="utf-8")
    assert "Set the config before build_phase." in fulltext


@pytest.mark.skipif(not __import__("pathlib").Path(REPO_PDF).is_file(),
                    reason=f"{REPO_PDF} not present")
def test_distill_real_pdf_end_to_end(tmp_path):
    """Exercises the REAL pypdf extraction path against the one real PDF
    this repo contains -- the claim being tested is that text extraction
    genuinely works, which a synthesized fake PDF could not establish."""
    record = distill_user_guide(REPO_PDF, tmp_path / "out", doc_kind="harness_user_guide")
    assert record["extraction"]["tool"] == "pypdf"
    assert record["extraction"]["method"] == "pdf_text_extraction"
    assert record["source_document"]["page_count"] and record["source_document"]["page_count"] > 1
    assert record["section_count"] > 0
    fulltext = (tmp_path / "out" / "DV_Agent_Harness_L5_Detailed_User_Guide_TC.fulltext.txt")
    assert fulltext.read_text(encoding="utf-8").strip(), "real text was extracted"
    # Round-trips through the loader env_manifest actually uses.
    reloaded = vip_user_guide_distill.load_reference_record(
        tmp_path / "out" / "DV_Agent_Harness_L5_Detailed_User_Guide_TC.reference.json")
    assert reloaded == record


def test_distill_rejects_unsupported_suffix(tmp_path):
    src = tmp_path / "guide.docx"
    src.write_bytes(b"not really a docx")
    with pytest.raises(UserGuideDistillError, match="unsupported suffix"):
        distill_user_guide(src, tmp_path / "out")


def test_load_reference_record_rejects_arbitrary_json(tmp_path):
    """`env-manifest generate --user-guide-ref` must not be pointable at any
    JSON file that then gets recorded as a distilled user-guide reference."""
    p = tmp_path / "not_a_record.json"
    p.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    with pytest.raises(UserGuideDistillError, match="not a vip_user_guide_distill reference record"):
        vip_user_guide_distill.load_reference_record(p)


def test_build_user_guide_refs_records_pointers_not_content(tmp_path):
    src = tmp_path / "vip_guide.txt"
    body = "A distinctive sentence that must never reach env.manifest.json.\n"
    src.write_text("1 Overview\n" + body, encoding="utf-8")
    distill_user_guide(src, tmp_path / "out")

    layer = build_user_guide_refs([tmp_path / "out" / "vip_guide.reference.json"])
    assert layer["status"] == "INDEXED"
    assert len(layer["documents"]) == 1
    doc = layer["documents"][0]
    assert set(doc) == {"title", "doc_kind", "source_document", "distilled_reference",
                        "full_text_extract", "extraction", "section_count"}
    assert doc["section_count"] == 1
    # Pointers carry identity, never bytes.
    assert len(doc["source_document"]["sha256"]) == 64
    assert body.strip() not in json.dumps(layer)


def test_build_user_guide_refs_not_available_when_none_distilled():
    layer = build_user_guide_refs()
    assert layer["status"] == "NOT_AVAILABLE"
    assert layer["documents"] == []
    assert "vip-user-guide distill" in layer["reason"], "the reason must name the real command to fix it"


def test_assert_no_user_guide_body_rejects_a_content_key():
    manifest = {"vip_config": {"user_guide_refs": {
        "status": "INDEXED", "reason": None,
        "documents": [{"title": "g", "content": "leaked prose"}],
    }}}
    with pytest.raises(EnvManifestValidationError, match="would carry user-guide CONTENT"):
        assert_no_user_guide_body_in_manifest(manifest)


def test_assert_no_user_guide_body_rejects_a_long_string():
    """The schema polices SHAPE; it cannot notice prose parked in a field
    that is legitimately a string. This is the check that can."""
    manifest = {"vip_config": {"user_guide_refs": {
        "status": "INDEXED", "reason": None,
        "documents": [{"title": "x" * 5000}],
    }}}
    with pytest.raises(EnvManifestValidationError, match="exceeds the .* pointer budget"):
        assert_no_user_guide_body_in_manifest(manifest)


# ---------------------------------------------------------------------------
# 3. dut_facts.address_map / dut_facts.clock_reset
# ---------------------------------------------------------------------------

def test_load_soc_arch_map_rejects_reset_without_active_level(tmp_path):
    """An assumed reset polarity is one of the cheapest ways to hold a DUT in
    reset for a whole run while every gate still passes -- so the input
    contract requires it and the loader fails closed."""
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"schema_version": "1.0",
                             "resets": [{"name": "rst_n"}]}), encoding="utf-8")
    with pytest.raises(SocArchMapValidationError, match="active_level"):
        load_soc_arch_map(p)


def test_load_soc_arch_map_rejects_malformed_base_address(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"schema_version": "1.0",
                             "address_map": [{"name": "B", "base_address": "4096", "size_bytes": 16}]}),
                 encoding="utf-8")
    with pytest.raises(SocArchMapValidationError):
        load_soc_arch_map(p)


def test_address_map_cross_check_against_register_map(soc_arch_map_file, register_map_file):
    registers = build_dut_facts_registers(register_map_file)
    layer = build_dut_facts_address_map(soc_arch_map_file, registers_layer=registers)

    assert layer["status"] == "LOADED"
    assert [e["name"] for e in layer["entries"]] == ["CTRL_BLOCK", "DMA_BLOCK", "MISC_BLOCK"], \
        "sorted by base_address then name for a stable diff"
    verdicts = {e["name"]: e["register_map_agreement"] for e in layer["entries"]}
    assert verdicts == {
        "CTRL_BLOCK": "AGREES",              # both say 0x1000
        "DMA_BLOCK": "DISAGREES",            # arch 0x3000 vs register map 0x2000
        "MISC_BLOCK": "NOT_IN_REGISTER_MAP",  # no such block in the register map
    }
    assert layer["disagreement_count"] == 1
    # The conflict is SURFACED, never resolved here: the address map keeps
    # its own value untouched (CLAUDE.md's Source Authority Order).
    dma = [e for e in layer["entries"] if e["name"] == "DMA_BLOCK"][0]
    assert dma["base_address"] == "0x3000"


def test_address_map_agreement_compares_integers_not_strings(tmp_path, register_map_file):
    """0x01000 and 0x1000 are the same address. A string compare would
    manufacture a disagreement that does not exist."""
    p = tmp_path / "arch.json"
    p.write_text(json.dumps({"schema_version": "1.0", "address_map": [
        {"name": "CTRL_BLOCK", "base_address": "0x01000", "size_bytes": 16}]}), encoding="utf-8")
    layer = build_dut_facts_address_map(p, registers_layer=build_dut_facts_registers(register_map_file))
    assert layer["entries"][0]["register_map_agreement"] == "AGREES"


def test_address_map_without_register_map_is_not_available_not_absent(soc_arch_map_file):
    """"nothing to compare against" must stay distinct from "compared, and
    absent" -- they are different findings."""
    layer = build_dut_facts_address_map(soc_arch_map_file,
                                         registers_layer=build_dut_facts_registers(None))
    assert {e["register_map_agreement"] for e in layer["entries"]} == {"NOT_AVAILABLE"}
    assert layer["disagreement_count"] == 0


def test_address_map_not_available_when_no_input_supplied():
    layer = build_dut_facts_address_map(None)
    assert layer["status"] == "NOT_AVAILABLE"
    assert layer["source"]["path"] is None
    assert "soc_arch_map.schema.json" in layer["reason"]


def test_address_map_not_available_when_file_omits_the_key(tmp_path):
    p = tmp_path / "arch.json"
    p.write_text(json.dumps({"schema_version": "1.0", "clocks": [{"name": "clk"}]}), encoding="utf-8")
    layer = build_dut_facts_address_map(p)
    assert layer["status"] == "NOT_AVAILABLE"
    # The real supplied path stays traceable, same discipline as build_vip_config().
    assert layer["source"]["path"] == str(p)
    assert "no 'address_map' key" in layer["reason"]


def test_clock_reset_resolves_reset_to_clock_and_flags_unknown(soc_arch_map_file):
    layer = build_dut_facts_clock_reset(soc_arch_map_file)
    assert layer["status"] == "LOADED"
    assert [c["name"] for c in layer["clocks"]] == ["aclk", "pclk"]
    resolved = {r["name"]: r["clock_resolved"] for r in layer["resets"]}
    assert resolved == {
        "aresetn": "UNKNOWN_CLOCK",   # names a clock the document never declares
        "por_n": "NOT_SPECIFIED",     # no clock given at all
        "presetn": "RESOLVED",        # names a real clock
    }
    # active_level survives verbatim -- never defaulted.
    assert all(r["active_level"] == "low" for r in layer["resets"])


def test_clock_reset_not_available_when_file_has_neither_key(tmp_path):
    p = tmp_path / "arch.json"
    p.write_text(json.dumps({"schema_version": "1.0", "address_map": []}), encoding="utf-8")
    layer = build_dut_facts_clock_reset(p)
    assert layer["status"] == "NOT_AVAILABLE"
    assert "neither 'clocks' nor 'resets'" in layer["reason"]


def test_build_dut_facts_wires_all_four_sub_layers(soc_arch_map_file, register_map_file):
    facts = build_dut_facts(None, register_map_file, soc_arch_map_path=soc_arch_map_file)
    assert set(facts) == {"rtl", "registers", "address_map", "clock_reset"}
    # The cross-check really ran against THIS call's register map.
    assert facts["address_map"]["disagreement_count"] == 1


# ---------------------------------------------------------------------------
# 4. env_topology.testplan_correspondence
# ---------------------------------------------------------------------------

def test_testplan_correspondence_full_three_way_join(testplan_sources_file):
    layer = build_testplan_correspondence(testplan_sources_file)
    assert layer["status"] == "COMPUTED"
    assert layer["axes_available"] == {"testlist": True, "vplan_items": True, "coverage_model": True}

    verdicts = {i["id"]: i["verdict"] for i in layer["items"]}
    assert verdicts == {
        "VP-001": "LINKED",                # every claim resolves
        "VP-002": "BROKEN_TEST_REF",       # claims a test nobody runs
        "VP-003": "BROKEN_COVERAGE_REF",   # claims a covergroup nobody wrote
        "VP-004": "UNCLAIMED",             # intent with nothing attached
    }
    vp002 = [i for i in layer["items"] if i["id"] == "VP-002"][0]
    assert vp002["tests_missing"] == ["never_written_test"]
    assert vp002["tests_present"] == []

    # The reverse direction, invisible to any per-item check.
    assert layer["orphans"]["tests_not_in_any_vplan_item"] == ["orphan_test"]
    assert layer["orphans"]["coverage_not_referenced_by_any_vplan_item"] == ["cg_orphan"]

    assert layer["summary"] == {
        "testlist_count": 3, "vplan_item_count": 4, "coverage_model_count": 2,
        "linked_count": 1, "broken_count": 2, "unclaimed_count": 1,
        "orphan_test_count": 1, "orphan_coverage_count": 1,
    }


def test_testplan_correspondence_broken_on_both_axes(tmp_path):
    p = tmp_path / "tp.json"
    p.write_text(json.dumps({
        "schema_version": "1.0",
        "testlist": [], "coverage_model": [],
        "vplan_items": [{"id": "VP-9", "tests": ["ghost_test"], "coverage": ["cg_ghost"]}],
    }), encoding="utf-8")
    layer = build_testplan_correspondence(p)
    assert layer["items"][0]["verdict"] == "BROKEN_TEST_AND_COVERAGE_REF"
    assert layer["summary"]["broken_count"] == 1


def test_testplan_correspondence_partial_never_scores_unchecked_claims_as_linked(tmp_path):
    """The failure this guards against: only the vPlan axis is supplied, so
    nothing can verify its test claims -- reporting LINKED there would be
    exactly the false reassurance this layer exists to prevent."""
    p = tmp_path / "tp.json"
    p.write_text(json.dumps({
        "schema_version": "1.0",
        "vplan_items": [{"id": "VP-1", "tests": ["some_test"], "coverage": []}],
    }), encoding="utf-8")
    layer = build_testplan_correspondence(p)

    assert layer["status"] == "PARTIAL"
    assert layer["axes_available"] == {"testlist": False, "vplan_items": True, "coverage_model": False}
    assert layer["items"][0]["verdict"] == "NOT_CHECKED"
    assert layer["summary"]["linked_count"] == 0
    assert "testlist" in layer["reason"] and "coverage_model" in layer["reason"]
    # An orphan list must never be able to mean "we could not look".
    assert layer["orphans"]["tests_not_in_any_vplan_item"] == []


def test_testplan_correspondence_not_available_when_no_axis_present(tmp_path):
    p = tmp_path / "tp.json"
    p.write_text(json.dumps({"schema_version": "1.0"}), encoding="utf-8")
    layer = build_testplan_correspondence(p)
    assert layer["status"] == "NOT_AVAILABLE"
    assert layer["source"]["path"] == str(p)


def test_testplan_correspondence_not_available_when_no_input_supplied():
    layer = build_testplan_correspondence(None)
    assert layer["status"] == "NOT_AVAILABLE"
    assert "testplan_sources.schema.json" in layer["reason"]
    assert layer["summary"]["vplan_item_count"] == 0


def test_load_testplan_sources_rejects_unknown_coverage_kind(tmp_path):
    p = tmp_path / "tp.json"
    p.write_text(json.dumps({"schema_version": "1.0",
                             "coverage_model": [{"name": "c", "kind": "vibes"}]}), encoding="utf-8")
    # Referenced through the module rather than imported, so pytest does not
    # try to COLLECT the `Testplan...` class as a test class.
    with pytest.raises(env_manifest.TestplanSourcesValidationError):
        load_testplan_sources(p)


# ---------------------------------------------------------------------------
# end-to-end: the four sources inside a real, schema-valid manifest
# ---------------------------------------------------------------------------

def test_full_manifest_carries_all_four_new_fact_sources(
        tmp_path, fake_designware_home, register_map_file, soc_arch_map_file, testplan_sources_file):
    src = tmp_path / "vip_guide.txt"
    src.write_text("1 Overview\nBody text.\n", encoding="utf-8")
    distill_user_guide(src, tmp_path / "guides")

    manifest = generate_env_manifest(
        register_map_path=register_map_file,
        designware_home=fake_designware_home,
        user_guide_reference_paths=[tmp_path / "guides" / "vip_guide.reference.json"],
        soc_arch_map_path=soc_arch_map_file,
        testplan_sources_path=testplan_sources_file,
    )
    # generate_env_manifest() validates against schema 1.2 internally; these
    # assert the layers really carry real content, not just that it validated.
    assert manifest["schema_version"] == "1.2"
    assert manifest["vip_config"]["vip_release"]["status"] == "SCANNED"
    assert len(manifest["vip_config"]["vip_release"]["packages"]) == 2
    assert manifest["vip_config"]["user_guide_refs"]["status"] == "INDEXED"
    assert manifest["dut_facts"]["address_map"]["disagreement_count"] == 1
    assert len(manifest["dut_facts"]["clock_reset"]["resets"]) == 3
    assert manifest["env_topology"]["testplan_correspondence"]["status"] == "COMPUTED"


def test_full_manifest_with_no_new_inputs_is_valid_and_honestly_not_available(monkeypatch):
    monkeypatch.delenv(env_manifest.DESIGNWARE_HOME_ENV, raising=False)
    manifest = generate_env_manifest()
    for layer in (manifest["vip_config"]["vip_release"],
                  manifest["vip_config"]["user_guide_refs"],
                  manifest["dut_facts"]["address_map"],
                  manifest["dut_facts"]["clock_reset"],
                  manifest["env_topology"]["testplan_correspondence"]):
        assert layer["status"] == "NOT_AVAILABLE"
        assert layer["reason"], "every NOT_AVAILABLE must carry a non-empty, actionable reason"


def test_regenerating_new_layers_from_unchanged_inputs_is_byte_identical(
        tmp_path, fake_designware_home, soc_arch_map_file, testplan_sources_file):
    """Diffability: a real diff must always mean a real underlying change."""
    kwargs = dict(designware_home=fake_designware_home,
                  soc_arch_map_path=soc_arch_map_file,
                  testplan_sources_path=testplan_sources_file)
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    env_manifest.generate_and_write(a, **kwargs)
    env_manifest.generate_and_write(b, **kwargs)
    assert a.read_bytes() == b.read_bytes()


def test_blackboard_summary_carries_the_new_layers_without_inlining_content(
        tmp_path, fake_designware_home, register_map_file, soc_arch_map_file, testplan_sources_file):
    src = tmp_path / "vip_guide.txt"
    body = "Prose that must never reach a stage prompt."
    src.write_text("1 Overview\n" + body + "\n", encoding="utf-8")
    distill_user_guide(src, tmp_path / "guides")

    manifest = generate_env_manifest(
        register_map_path=register_map_file,
        designware_home=fake_designware_home,
        user_guide_reference_paths=[tmp_path / "guides" / "vip_guide.reference.json"],
        soc_arch_map_path=soc_arch_map_file,
        testplan_sources_path=testplan_sources_file,
    )
    summary = summarize_for_blackboard(manifest, manifest_path=tmp_path / "env.manifest.json")

    # The conflicts a reading stage must not have to open a file to find.
    assert summary["dut_facts"]["address_map"]["disagreeing_regions"] == ["DMA_BLOCK"]
    assert summary["env_topology"]["testplan_correspondence"]["broken_item_ids"] == ["VP-002", "VP-003"]
    assert summary["env_topology"]["testplan_correspondence"]["unclaimed_item_ids"] == ["VP-004"]
    assert summary["vip_config"]["vip_release"]["packages"] == [
        {"name": "amba_svt", "version": "Q-2019.06"},
        {"name": "usb_svt", "version": "R-2020.12"},
    ]
    # Prompt-sized by construction: no document prose, and no full verible
    # parse trees / register field tables.
    blob = json.dumps(summary)
    assert body not in blob
    assert "cg_link_state" not in blob, "per-item coverage detail stays in the manifest"
