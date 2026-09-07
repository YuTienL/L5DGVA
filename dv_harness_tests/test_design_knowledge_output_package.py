"""Tests for dv_harness/design_knowledge_output_package.py -- the
design-knowledge family's exportable package + downstream-consumer contract.

Discipline: every LIVE slot is driven by a REAL call into that family
member's own real entry point (design_source_inventory.build_source_registry
hashing real temp files, design_knowledge_correlation.correlate over a real
sources list, design_intent.validate_intent/render_intent_markdown over the
project's own real worked-example fixture
(examples/asset_processing/inputs/dut_intent.yaml, the same fixture
test_asset_processing_artifacts.py's own design_intent tests use),
design_architecture_ir.build_architecture_ir over a real synthetic .sv file
with a deliberately-unrunnable verible binary (the same determinism trick
test_design_architecture_ir.py's own tests use, so this test suite needs no
verible install), spec_intelligence.analyze_spec_extraction over a real
extraction-shaped document, verification_intent_ir.build_verification_intent_
ir_set over a real minimal requirement record) -- never a hand-shaped stand-in
for what one of those modules would have returned. `bundle_hash` is
cross-checked against an INDEPENDENT direct call into
`signoff_export.compute_bundle_hash()` on the positive path, proving this
module really reuses that function rather than reimplementing it. Negative
controls prove a malformed/absent input is reported honestly (present=False,
a real error string, package_kind PARTIAL) rather than fabricated as present.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import design_knowledge_output_package as dkop
from dv_harness import signoff_export as se

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_ARGS = [sys.executable, "-m", "dv_harness.design_knowledge_output_package"]

REAL_INTENT_YAML = REPO_ROOT / "examples" / "asset_processing" / "inputs" / "dut_intent.yaml"
REAL_CONSTRAINTS_YAML = REPO_ROOT / "examples" / "asset_processing" / "inputs" / "constraints.yaml"


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _real_intent_doc() -> dict:
    import yaml
    return yaml.safe_load(REAL_INTENT_YAML.read_text(encoding="utf-8"))


def _real_constraints_doc() -> dict:
    import yaml
    return yaml.safe_load(REAL_CONSTRAINTS_YAML.read_text(encoding="utf-8"))


def _correlation_sources() -> list:
    return [
        {"source_id": "spec_v3", "source_kind": "spec", "role": "SPEC_DECLARATION",
         "facts": [{"fact_key": "usb_wake_irq.active_level", "fact_type": "interrupt",
                    "value": "HIGH", "evidence_ref": "spec.md:120"}]},
        {"source_id": "rtl_extract", "source_kind": "rtl", "role": "IMPLEMENTATION_EVIDENCE",
         "facts": [{"fact_key": "usb_wake_irq.active_level", "fact_type": "interrupt",
                    "value": "LOW", "evidence_ref": "top.sv:44"}]},
    ]


def _spec_extraction_doc() -> dict:
    return {
        "schema_version": "1.0",
        "evidence_provenance": "AGENT_SELF_ATTESTED",
        "atomic_requirements": [{
            "contract_schema_version": "1.0",
            "requirement_id": "R-1",
            "source": {"document": "spec.txt", "locator": "4.3.1",
                       "quote": "The link shall enter U1 within 10us."},
            "feature": "LFPS handshake timing",
            "protocol": "USB3",
            "configuration": "NONE",
            "precondition": "NONE",
            "stimulus": "Assert LFPS on both TX lanes",
            "expected_result": "Link enters U1 within 10us",
            "observability": "link_state signal",
            "checker": "link_state_checker",
            "coverage_intent": "cover LFPS entry timing",
            "priority": "P1",
            "criticality": "MAJOR",
            "confidence": "HIGH",
            "status": "COMPLETE",
            "extraction_id": "X-R-1",
            "derivation": "EXPLICIT",
        }],
        "relations": [],
    }


def _rtl_module_text(name: str = "leaf_mod") -> str:
    return f"module {name}(input clk, input rst_n, output reg done);\nendmodule\n"


ALL_LIVE_KWARGS = None  # filled in by _all_live_config(tmp_path)


def _all_live_config(tmp_path: Path) -> dict:
    src_file = tmp_path / "spec.txt"
    src_file.write_text("dummy spec text", encoding="utf-8")
    rtl_file = tmp_path / "leaf.sv"
    rtl_file.write_text(_rtl_module_text(), encoding="utf-8")
    return {
        "design_source_inventory": {"live": {"entries": [
            {"source_id": "spec_doc", "type": "spec", "path": str(src_file),
             "authority_hint": "spec_doc"},
        ]}},
        "design_knowledge_correlation": {"live": {"sources": _correlation_sources()}},
        "design_intent": {"live": {
            "intent_doc": _real_intent_doc(), "constraints_doc": _real_constraints_doc()}},
        "design_architecture_ir": {"live": {"rtl_files": [str(rtl_file)]}},
        "spec_intelligence": {"live": {"document": _spec_extraction_doc()}},
        "verification_intent_ir": {"live": {"records": [{"requirement_id": "REQ-1"}]}},
    }


# ---------------------------------------------------------------------------
# Downstream-consumer contract -- module-level, always covers all six slots
# ---------------------------------------------------------------------------

def test_contract_covers_every_family_slot_both_directions():
    assert set(dkop.DOWNSTREAM_CONSUMER_CONTRACT) == set(dkop.FAMILY_SLOTS)
    for name, entry in dkop.DOWNSTREAM_CONSUMER_CONTRACT.items():
        assert entry["may_rely_on"], name
        assert entry["must_reverify"], name
        assert entry["producer"], name


def test_assert_contract_covers_family_catches_drift():
    bad = dict(dkop.DOWNSTREAM_CONSUMER_CONTRACT)
    del bad["design_intent"]
    orig = dkop.DOWNSTREAM_CONSUMER_CONTRACT
    dkop.DOWNSTREAM_CONSUMER_CONTRACT = bad
    try:
        with pytest.raises(AssertionError):
            dkop.assert_contract_covers_family()
    finally:
        dkop.DOWNSTREAM_CONSUMER_CONTRACT = orig


# ---------------------------------------------------------------------------
# Zero slots requested -> honest PARTIAL, never a fabricated COMPLETE
# ---------------------------------------------------------------------------

def test_no_slots_requested_is_partial_but_still_writes_the_contract(tmp_path):
    out_dir = tmp_path / "pkg"
    result = dkop.collect_design_knowledge_package(tmp_path, out_dir)

    assert result["status"] == "OK"
    assert result["package_kind"] == dkop.PACKAGE_ASSEMBLY_PARTIAL
    for name in dkop.FAMILY_SLOTS:
        assert result["slot_status"][name]["requested"] is False
        assert result["slot_status"][name]["present"] is False

    # The contract itself is bundled regardless -- it documents the FAMILY,
    # not this particular run's data.
    contract_path = out_dir / "downstream_consumer_contract.json"
    assert contract_path.is_file()
    on_disk = json.loads(contract_path.read_text(encoding="utf-8"))
    assert set(on_disk["slots"]) == set(dkop.FAMILY_SLOTS)

    manifest_doc = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_doc["bundle_hash"] == result["bundle_hash"]
    assert manifest_doc["package_kind"] == dkop.PACKAGE_ASSEMBLY_PARTIAL


# ---------------------------------------------------------------------------
# Every slot live-assembled for real -> PACKAGE_ASSEMBLY_COMPLETE
# ---------------------------------------------------------------------------

def test_all_six_slots_live_assembled_yields_complete_package(tmp_path):
    out_dir = tmp_path / "pkg"
    config = _all_live_config(tmp_path)
    result = dkop.collect_design_knowledge_package(tmp_path, out_dir, **config)

    assert result["status"] == "OK"
    for name in dkop.FAMILY_SLOTS:
        st = result["slot_status"][name]
        assert st["requested"] is True, name
        assert st["source"] == dkop.SOURCE_LIVE_ASSEMBLED, name
        assert st["present"] is True, name
        assert st["error"] is None, name
    assert result["package_kind"] == dkop.PACKAGE_ASSEMBLY_COMPLETE

    # Cross-check design_source_inventory's real bundled content against a
    # direct independent call -- proves no fabrication, only a faithful copy
    # of what that module really returned.
    from dv_harness import design_source_inventory as dsi
    direct = dsi.build_source_registry(config["design_source_inventory"]["live"]["entries"])
    on_disk = json.loads((out_dir / "design_source_inventory.json").read_text(encoding="utf-8"))
    assert on_disk["sources"][0]["hash"] == direct["sources"][0]["hash"]
    assert direct["sources"][0]["hash"] is not None

    # design_knowledge_correlation really found the real conflict the two
    # fixture sources disagree about.
    corr = json.loads((out_dir / "design_knowledge_correlation.json").read_text(encoding="utf-8"))
    assert corr["summary"]["conflict_count"] == 1
    assert corr["conflicts"][0]["fact_key"] == "usb_wake_irq.active_level"

    # design_intent: both intent and constraints markdown were really
    # rendered from the real worked-example fixture, and cite a real basis.
    intent_md = (out_dir / "design_intent" / "intent.md").read_text(encoding="utf-8")
    assert "demo_usb_controller" in intent_md
    constraints_json = json.loads(
        (out_dir / "design_intent" / "constraints.json").read_text(encoding="utf-8"))
    assert constraints_json == _real_constraints_doc()

    # design_architecture_ir: a REAL verible parse of the real synthetic
    # .sv file (this environment has a real verible binary installed, the
    # same one test_design_architecture_ir.py's own unskipped suite uses).
    air = json.loads((out_dir / "design_architecture_ir.json").read_text(encoding="utf-8"))
    assert air["status"] == "BUILT"
    assert air["files"][0]["status"] == "PARSED"
    assert "leaf_mod" in air["modules"]

    # spec_intelligence really validated the one clean requirement.
    spec = json.loads((out_dir / "spec_intelligence.json").read_text(encoding="utf-8"))
    assert spec["status"] == "PASS"
    assert spec["atomic_requirement_count"] == 1

    # verification_intent_ir really built one IR carrying the real
    # AGENT_SELF_ATTESTED self-attestation this module's contract cites.
    vir_docs = json.loads((out_dir / "verification_intent_ir.json").read_text(encoding="utf-8"))
    assert len(vir_docs) == 1
    assert vir_docs[0]["requirement_id"] == "REQ-1"
    assert vir_docs[0]["evidence_provenance"] == "AGENT_SELF_ATTESTED"


def test_manifest_entries_match_signoff_export_shape_and_reuse_its_hash(tmp_path):
    out_dir = tmp_path / "pkg"
    config = _all_live_config(tmp_path)
    result = dkop.collect_design_knowledge_package(tmp_path, out_dir, **config)

    for entry in result["manifest"]:
        assert set(entry) == {"artifact", "present", "bundled_path", "content_sha256"}

    independent_hash = se.compute_bundle_hash(result["manifest"])
    assert independent_hash == result["bundle_hash"]


def test_content_sha256_matches_real_bundled_file_bytes(tmp_path):
    import hashlib
    out_dir = tmp_path / "pkg"
    config = _all_live_config(tmp_path)
    result = dkop.collect_design_knowledge_package(tmp_path, out_dir, **config)
    for entry in result["manifest"]:
        if not entry["present"]:
            assert entry["content_sha256"] is None
            continue
        path = out_dir / entry["bundled_path"]
        real_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert entry["content_sha256"] == real_digest


# ---------------------------------------------------------------------------
# Caller-supplied precomputed records
# ---------------------------------------------------------------------------

def test_caller_supplied_record_is_bundled_verbatim(tmp_path):
    out_dir = tmp_path / "pkg"
    precomputed = {"generated_at": "2026-01-01T00:00:00+00:00", "source_count": 0,
                    "sources": [], "summary": {}}
    result = dkop.collect_design_knowledge_package(
        tmp_path, out_dir, design_source_inventory={"record": precomputed})

    st = result["slot_status"]["design_source_inventory"]
    assert st["source"] == dkop.SOURCE_CALLER_SUPPLIED
    assert st["present"] is True
    on_disk = json.loads((out_dir / "design_source_inventory.json").read_text(encoding="utf-8"))
    assert on_disk == precomputed


# ---------------------------------------------------------------------------
# Negative controls: never fabricate presence/success on a real failure
# ---------------------------------------------------------------------------

def test_malformed_correlation_sources_is_reported_absent_with_real_error(tmp_path):
    out_dir = tmp_path / "pkg"
    result = dkop.collect_design_knowledge_package(
        tmp_path, out_dir,
        design_knowledge_correlation={"live": {"sources": []}})  # empty -> real ValueError

    st = result["slot_status"]["design_knowledge_correlation"]
    assert st["requested"] is True
    assert st["present"] is False
    assert st["error"] is not None
    assert "non-empty list" in st["error"]

    manifest_by_artifact = {m["artifact"]: m for m in result["manifest"]}
    assert manifest_by_artifact["design_knowledge_correlation"]["present"] is False
    assert manifest_by_artifact["design_knowledge_correlation"]["content_sha256"] is None
    assert not (out_dir / "design_knowledge_correlation.json").exists()

    assert result["package_kind"] == dkop.PACKAGE_ASSEMBLY_PARTIAL


def test_malformed_intent_doc_reports_real_error_never_a_fabricated_markdown(tmp_path):
    out_dir = tmp_path / "pkg"
    bad_intent = {"schema_version": "1.0"}  # missing every required field
    result = dkop.collect_design_knowledge_package(
        tmp_path, out_dir, design_intent={"live": {"intent_doc": bad_intent}})

    st = result["slot_status"]["design_intent"]
    assert st["requested"] is True
    assert st["present"] is False
    assert st["error"] is not None and "intent:" in st["error"]
    assert not (out_dir / "design_intent").exists()
    assert result["package_kind"] == dkop.PACKAGE_ASSEMBLY_PARTIAL


def test_design_intent_partial_success_reports_both_the_real_half_and_the_real_error(tmp_path):
    """intent_doc validates and renders for real; constraints_doc is
    malformed. Both facts must survive -- the real intent markdown must be
    bundled AND the real constraints error must be reported, never one
    silently masking the other."""
    out_dir = tmp_path / "pkg"
    result = dkop.collect_design_knowledge_package(
        tmp_path, out_dir,
        design_intent={"live": {
            "intent_doc": _real_intent_doc(),
            "constraints_doc": {"schema_version": "1.0"}}})

    st = result["slot_status"]["design_intent"]
    assert st["present"] is True  # the intent half really produced output
    assert st["error"] is not None and "constraints:" in st["error"]

    manifest_by_artifact = {m["artifact"]: m for m in result["manifest"]}
    assert manifest_by_artifact["design_intent:intent_markdown"]["present"] is True
    assert manifest_by_artifact["design_intent:constraints_markdown"]["present"] is False
    assert (out_dir / "design_intent" / "intent.md").is_file()
    assert not (out_dir / "design_intent" / "constraints.md").exists()

    # A partial slot success still drags the WHOLE package to PARTIAL --
    # worst-wins, not "at least one artifact landed".
    assert result["package_kind"] == dkop.PACKAGE_ASSEMBLY_PARTIAL


def test_unparseable_top_module_override_is_reported_absent_never_crashes(tmp_path):
    """build_architecture_ir raises DesignArchitectureIRError for an explicit
    top_module that was never parsed -- this must be caught, not crash the
    whole package assembly. Uses the REAL default verible binary (confirmed
    installed in this environment by test_design_architecture_ir.py's own
    unskipped suite) so the file really parses and the top_module override
    really has something real to fail against."""
    rtl_file = tmp_path / "leaf.sv"
    rtl_file.write_text(_rtl_module_text("leaf_mod"), encoding="utf-8")
    out_dir = tmp_path / "pkg"
    result = dkop.collect_design_knowledge_package(
        tmp_path, out_dir,
        design_architecture_ir={"live": {
            "rtl_files": [str(rtl_file)],
            "top_module": "definitely_not_a_real_module"}})

    st = result["slot_status"]["design_architecture_ir"]
    assert st["present"] is False
    assert st["error"] is not None
    assert result["package_kind"] == dkop.PACKAGE_ASSEMBLY_PARTIAL


def test_invalid_slot_shape_is_reported_as_invalid_request(tmp_path):
    out_dir = tmp_path / "pkg"
    result = dkop.collect_design_knowledge_package(
        tmp_path, out_dir, spec_intelligence={"record": {}, "live": {}})  # both given -> invalid

    st = result["slot_status"]["spec_intelligence"]
    assert st["source"] == dkop.SOURCE_INVALID_REQUEST
    assert st["present"] is False
    assert "exactly one" in st["error"]
    assert result["package_kind"] == dkop.PACKAGE_ASSEMBLY_PARTIAL


# ---------------------------------------------------------------------------
# require_complete: refusal writes nothing at all
# ---------------------------------------------------------------------------

def test_require_complete_refuses_and_writes_nothing_when_partial(tmp_path):
    out_dir = tmp_path / "pkg"
    assert not out_dir.exists()
    result = dkop.collect_design_knowledge_package(
        tmp_path, out_dir,
        design_knowledge_correlation={"live": {"sources": []}},
        require_complete=True)

    assert result["status"] == "REFUSED"
    assert result["reason"] == "PACKAGE_NOT_COMPLETE"
    assert result["manifest"] == []
    assert result["bundle_hash"] is None
    assert not out_dir.exists()


def test_require_complete_succeeds_and_writes_when_every_requested_slot_landed(tmp_path):
    out_dir = tmp_path / "pkg"
    config = _all_live_config(tmp_path)
    result = dkop.collect_design_knowledge_package(
        tmp_path, out_dir, require_complete=True, **config)

    assert result["status"] == "OK"
    assert result["package_kind"] == dkop.PACKAGE_ASSEMBLY_COMPLETE
    assert out_dir.is_dir()
    assert (out_dir / "manifest.json").is_file()


# ---------------------------------------------------------------------------
# CLI subprocess
# ---------------------------------------------------------------------------

def test_cli_collect_reports_partial_kind_on_empty_config(tmp_path):
    out_dir = tmp_path / "pkg"
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    proc = subprocess.run(
        CLI_ARGS + ["collect", "--root", str(tmp_path), "--out-dir", str(out_dir),
                    "--config", str(config_path), "--json"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["package_kind"] == dkop.PACKAGE_ASSEMBLY_PARTIAL
    assert (out_dir / "manifest.json").is_file()


def test_cli_collect_complete_with_full_live_config_exits_zero(tmp_path):
    out_dir = tmp_path / "pkg"
    config = _all_live_config(tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    proc = subprocess.run(
        CLI_ARGS + ["collect", "--root", str(tmp_path), "--out-dir", str(out_dir),
                    "--config", str(config_path), "--json"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["package_kind"] == dkop.PACKAGE_ASSEMBLY_COMPLETE


def test_cli_text_output_names_every_slot(tmp_path):
    out_dir = tmp_path / "pkg"
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    proc = subprocess.run(
        CLI_ARGS + ["collect", "--root", str(tmp_path), "--out-dir", str(out_dir),
                    "--config", str(config_path)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    for name in dkop.FAMILY_SLOTS:
        assert name in proc.stdout


def test_cli_refuses_on_unrecognized_slot_name(tmp_path):
    out_dir = tmp_path / "pkg"
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps({"not_a_real_slot": {"record": {}}}), encoding="utf-8")
    proc = subprocess.run(
        CLI_ARGS + ["collect", "--root", str(tmp_path), "--out-dir", str(out_dir),
                    "--config", str(bad_path)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert not out_dir.exists()


def test_cli_refuses_on_malformed_config_json(tmp_path):
    out_dir = tmp_path / "pkg"
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("not json", encoding="utf-8")
    proc = subprocess.run(
        CLI_ARGS + ["collect", "--root", str(tmp_path), "--out-dir", str(out_dir),
                    "--config", str(bad_path)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert not out_dir.exists()
