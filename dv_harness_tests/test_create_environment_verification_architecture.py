"""CAP-M5-ARCH-001 (M5 Cohort 2): the verification_architecture wire into
dv_harness/uvm_generator/create_environment.py -- B8's own capability, real
and additive, merged from the M5 N-Way Capability Semantic Merge. B8 shipped
NO test coverage for this feature at all (confirmed: every test file that
exercises create_environment() was byte-identical between canonical and B8);
every test here is authored fresh this wave.

Also covers the two mode-string defect fixes found and corrected during this
merge (create_environment()'s SUBSYSTEM_MODE and SYSTEM_LEVEL_MODE return
dicts previously hard-coded their `environment_mode` literal instead of
using the real resolved `decision["environment_mode"]`) -- see
M5_COHORT_2_ARCH001_MODE_DEFECT_ANALYSIS.md for the full disposition.
"""
import json
import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness.uvm_generator.create_environment import (
    create_environment, VerificationArchitectureConflictError,
)
from dv_harness.verification_architecture import validate_verification_architecture

ROOT = Path(__file__).resolve().parents[1]


def _tmp():
    return Path(tempfile.mkdtemp())


def _pcie_manifest(**extra):
    m = {
        "protocol": "PCIe",
        "clocks": [{"name": "refclk"}],
        "resets": [{"name": "perst_n"}],
        "smoke_tests": [{"name": "link_training"}],
    }
    m.update(extra)
    return m


# ---------------------------------------------------------------------------
# NOT_AVAILABLE default path -- the pre-existing behavior, unaffected
# ---------------------------------------------------------------------------

def test_generate_without_verification_architecture_inputs_reports_not_available():
    tmp = _tmp()
    try:
        result = create_environment(tmp, _pcie_manifest(), out_dir=tmp / "out")
        va = result["verification_architecture"]
        assert va["status"] == "NOT_AVAILABLE"
        assert va["reason"] == "NO_VERIFICATION_ARCHITECTURE_INPUTS_DECLARED_IN_REQUEST"
        assert not (tmp / "out" / "verification_architecture.json").exists()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Real assembly, schema compliance (the regression this file exists to
# guarantee: B8's own written file broke additionalProperties:false with an
# extra synthetic "status" key -- confirmed with real jsonschema evidence
# before merging, corrected, never propagated)
# ---------------------------------------------------------------------------

def test_generate_with_verification_architecture_inputs_assembles_and_writes_schema_compliant_file():
    tmp = _tmp()
    try:
        manifest = _pcie_manifest(verification_architecture_inputs={"bind_entries": []})
        result = create_environment(tmp, manifest, out_dir=tmp / "out")
        va = result["verification_architecture"]
        assert "status" not in va, (
            "the assembled document must stay byte-for-byte the real "
            "assemble_verification_architecture() shape (minus _irs) -- a "
            "synthetic 'status' key was B8's own defect, verified this wave "
            "to violate verification_architecture.schema.json's "
            "additionalProperties:false"
        )
        assert va["schema_version"]
        # Must not raise: this is the real regression check.
        validate_verification_architecture(va)

        written = tmp / "out" / "verification_architecture.json"
        assert written.exists()
        on_disk = json.loads(written.read_text(encoding="utf-8"))
        assert on_disk == va
        validate_verification_architecture(on_disk)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_verification_architecture_present_in_system_level_mode_too(tmp_path, monkeypatch):
    """Both dispatch branches wire the same helper -- SYSTEM_LEVEL_MODE must
    not be a second, divergent implementation."""
    root = tmp_path
    registry_dir = root / ".dv-harness" / "soc-composer"
    registry_dir.mkdir(parents=True)
    (registry_dir / "subsystem_environment_registry.json").write_text(json.dumps({
        "subsystems": [
            {"name": "USB", "environment_manifest": {"protocol": "USB"},
             "release_sha": "a" * 40, "qualification_state": "BASELINE_READY",
             "interface_compatibility": {}, "clock_reset_compatibility": {}},
            {"name": "PCIe", "environment_manifest": {"protocol": "PCIe"},
             "release_sha": "b" * 40, "qualification_state": "BASELINE_READY",
             "interface_compatibility": {}, "clock_reset_compatibility": {}},
        ]
    }), encoding="utf-8")

    def _fake_compose(subsystems, request, root_):
        return {"soc_tb_top.sv": "// stub\n"}

    import dv_harness.uvm_generator.create_environment as ce_mod
    monkeypatch.setattr(ce_mod, "compose_soc_environment", _fake_compose)

    request = {
        "requested_subsystems": ["USB", "PCIe"],
        "soc_name": "test_soc",
        "verification_architecture_inputs": {"bind_entries": []},
    }
    result = create_environment(root, request, out_dir=tmp_path / "soc_out")
    assert result["environment_mode"] == "SYSTEM_LEVEL_MODE"
    va = result["verification_architecture"]
    assert "status" not in va
    validate_verification_architecture(va)


# ---------------------------------------------------------------------------
# strict_verification_architecture -- real HIGH-severity conflict
# ---------------------------------------------------------------------------

def test_strict_verification_architecture_raises_on_high_severity_conflict():
    tmp = _tmp()
    try:
        manifest = _pcie_manifest(
            strict_verification_architecture=True,
            verification_architecture_inputs={
                "vip_config": {"status": "CAPTURED", "vip_instances": [
                    {"instance_path": "chip.core.usb0.if0", "vip_type": "svt_usb3", "config_fields": {}},
                    {"instance_path": "chip.core.usb0.if0", "vip_type": "svt_usb2", "config_fields": {}},
                ]},
                "active_passive_by_instance": {"chip.core.usb0.if0": "ACTIVE"},
            },
        )
        with pytest.raises(VerificationArchitectureConflictError) as exc:
            create_environment(tmp, manifest, out_dir=tmp / "out")
        assert exc.value.reason == "VERIFICATION_ARCHITECTURE_PLACEMENT_CONFLICT"
        kinds = [c["kind"] for c in exc.value.detail["high_severity_conflicts"]]
        assert "DUPLICATE_ACTIVE_VIP" in kinds
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_verification_architecture_conflict_non_blocking_by_default():
    """Default behaviour is non-blocking -- an unrequested strict flag must
    not turn a previously-working generation into a hard failure."""
    tmp = _tmp()
    try:
        manifest = _pcie_manifest(
            verification_architecture_inputs={
                "vip_config": {"status": "CAPTURED", "vip_instances": [
                    {"instance_path": "chip.core.usb0.if0", "vip_type": "svt_usb3", "config_fields": {}},
                    {"instance_path": "chip.core.usb0.if0", "vip_type": "svt_usb2", "config_fields": {}},
                ]},
                "active_passive_by_instance": {"chip.core.usb0.if0": "ACTIVE"},
            },
        )
        result = create_environment(tmp, manifest, out_dir=tmp / "out")
        kinds = [c["kind"] for c in result["verification_architecture"]["placement_conflicts"]]
        assert "DUPLICATE_ACTIVE_VIP" in kinds
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Mode-string defect regression (both branches)
# ---------------------------------------------------------------------------

def test_subsystem_mode_environment_mode_reflects_real_decision_not_a_literal():
    tmp = _tmp()
    try:
        result = create_environment(tmp, _pcie_manifest(), out_dir=tmp / "out")
        assert result["environment_mode"] == result["decision"]["environment_mode"] == "SUBSYSTEM_MODE"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
