"""Tests for dv_harness/uvm_generator/protocol_env_generator.py (9-policy
audit / USB regen-fidelity plan Phase 1 item 4, 2026-08-29): real
subdirectory-shaped layout superseding generator.py's flat output."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from dv_harness.uvm_generator.generator import UVMEnvironmentGenerator, sv_id
from dv_harness.uvm_generator.protocol_env_generator import ProtocolEnvGenerator, LAYOUT, EXTRA_DIRS

ROOT = Path(__file__).resolve().parents[1]

MANIFEST = {
    "protocol": "usb3_2",
    "role": "DEVICE",
    "vip": {"package_imports": ["usb_vip_pkg"], "agent_type": "usb_agent", "agent_instance": "usb_agent0"},
    "smoke_tests": [{"name": "smoke"}, {"name": "enum"}],
}


def test_generate_produces_the_real_subdirectory_shape():
    tmp = Path(tempfile.mkdtemp())
    try:
        files = ProtocolEnvGenerator(tmp).generate(MANIFEST)
        # Directory-shape claim: every catalogued USB_UVM_Handoff top-level
        # tb/ subdirectory this generator claims to populate (or at least
        # create) must actually exist on disk.
        for d in ["tb/env", "tb/seq", "tb/tests", "tb/top", "filelist"] + EXTRA_DIRS:
            assert (tmp / d).is_dir(), f"missing directory: {d}"
        for rel in files:
            assert (tmp / rel).exists(), f"missing generated file: {rel}"
    finally:
        shutil.rmtree(tmp)


def test_generated_files_land_in_the_layout_declared_subdirectory():
    tmp = Path(tempfile.mkdtemp())
    try:
        p = sv_id(MANIFEST["protocol"])
        files = ProtocolEnvGenerator(tmp).generate(MANIFEST)
        assert f"{LAYOUT['config']}/{p}_config.sv" in files
        assert f"{LAYOUT['virtual_sequencer']}/{p}_virtual_sequencer.sv" in files
        assert f"{LAYOUT['tb_top']}/tb_top.sv" in files
        assert "filelist/dv_uvm_files.f" in files
        assert "environment_manifest.json" in files
    finally:
        shutil.rmtree(tmp)


def test_relocated_content_is_byte_identical_to_the_flat_generator():
    # The gap this module closes is WHERE files land, not their content --
    # confirm content is unchanged from generator.py's own emit methods.
    tmp = Path(tempfile.mkdtemp())
    try:
        p = sv_id(MANIFEST["protocol"])
        ProtocolEnvGenerator(tmp).generate(MANIFEST)
        flat = UVMEnvironmentGenerator(tmp / "_flat_reference")
        expected_config = flat.config(MANIFEST, p)
        actual_config = (tmp / LAYOUT["config"] / f"{p}_config.sv").read_text(encoding="utf-8")
        assert actual_config == expected_config
    finally:
        shutil.rmtree(tmp)


def test_manifest_records_qualification_status_and_generated_files():
    tmp = Path(tempfile.mkdtemp())
    try:
        files = ProtocolEnvGenerator(tmp).generate(MANIFEST)
        manifest = json.loads((tmp / "environment_manifest.json").read_text(encoding="utf-8"))
        assert manifest["qualification_status"] == "ENV_GENERATED"
        assert sorted(manifest["generated_files"]) == sorted(files)
    finally:
        shutil.rmtree(tmp)


def test_cli_shim_generates_environment_from_manifest_file():
    tmp = Path(tempfile.mkdtemp())
    try:
        manifest_path = tmp / "manifest.json"
        manifest_path.write_text(json.dumps(MANIFEST), encoding="utf-8")
        out_dir = tmp / "out"
        r = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "generate_protocol_uvm_environment.py"),
             "--manifest", str(manifest_path), "--out", str(out_dir)],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["status"] == "OK"
        assert (out_dir / "tb" / "top" / "tb_top.sv").exists()
    finally:
        shutil.rmtree(tmp)
