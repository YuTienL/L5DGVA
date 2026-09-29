"""Tests for dv_harness/mcp/manifest_source.py + dv_harness/mcp/schema.py."""
from __future__ import annotations

import json

import pytest

jsonschema = pytest.importorskip("jsonschema")

from dv_harness.mcp import schema
from dv_harness.mcp.errors import McpError, McpNotFoundError, McpValidationError
from dv_harness.mcp.manifest_source import load_manifest

from .mcp_manifest_fixture import build_fixture_manifest, build_not_available_manifest


# ---- manifest_source.load_manifest() ---------------------------------------

def test_load_manifest_round_trips_real_json_file(tmp_path):
    manifest = build_fixture_manifest()
    path = tmp_path / "env.manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    loaded = load_manifest(path)
    assert loaded == manifest


def test_load_manifest_missing_file_raises_not_found(tmp_path):
    with pytest.raises(McpNotFoundError):
        load_manifest(tmp_path / "does_not_exist.json")


def test_load_manifest_malformed_json_raises_mcp_error(tmp_path):
    path = tmp_path / "env.manifest.json"
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(McpError):
        load_manifest(path)


def test_load_manifest_rejects_non_object_top_level(tmp_path):
    path = tmp_path / "env.manifest.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    with pytest.raises(McpError):
        load_manifest(path)


# ---- schema.py: fixture honesty -------------------------------------------

def test_fixture_manifest_matches_assumed_schema():
    schema.validate_manifest(build_fixture_manifest())


def test_not_available_fixture_manifest_matches_assumed_schema():
    schema.validate_manifest(build_not_available_manifest())


def test_assumed_schema_rejects_unknown_top_level_key():
    manifest = build_fixture_manifest()
    manifest["unexpected_top_level_key"] = 1
    with pytest.raises(McpValidationError):
        schema.validate_manifest(manifest)


def test_assumed_schema_rejects_bad_vip_config_status_enum():
    manifest = build_fixture_manifest()
    manifest["vip_config"]["status"] = "MAYBE"
    with pytest.raises(McpValidationError):
        schema.validate_manifest(manifest)


# ---- schema.py: per-verb param/result schemas ------------------------------

@pytest.mark.parametrize("verb", ["get_vip_config", "get_dut_port", "get_register",
                                    "get_topology", "query_regression"])
def test_every_fixed_verb_has_a_param_and_result_schema(verb):
    assert verb in schema.PARAM_SCHEMAS
    assert verb in schema.RESULT_SCHEMAS


def test_validate_params_rejects_unknown_verb():
    with pytest.raises(McpValidationError):
        schema.validate_params("delete_everything", {})


def test_validate_params_rejects_extra_field():
    with pytest.raises(McpValidationError):
        schema.validate_params("get_dut_port", {"module_name": "usb3_top", "extra": 1})


def test_validate_params_rejects_missing_required_field():
    with pytest.raises(McpValidationError):
        schema.validate_params("get_dut_port", {})
