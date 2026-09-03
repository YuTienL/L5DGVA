"""dv_harness/mcp/schema.py -- fixed JSON Schemas for the 5 verbs' PARAMS
and RESULTS, plus a reference to the REAL env.manifest.json contract this
package validates fixtures against: dv_harness/schemas/env_manifest.schema.json
(dv_harness/env_manifest.py's own schema, landed by the parallel manifest-
generator workstream partway through this session -- RECONCILED, not just
flagged: verbs.py's field lookups below were updated to match this real
schema's actual field names once it landed. See .work/mcp-server-report.md
for the before/after diff of what this package originally assumed versus
what the real generator actually produces.

This is the concrete mechanism behind Part A's "fixed schema (no free-text
parsing of arbitrary greps)" design goal: every verb call's params are
validated against ONE OF EXACTLY 5 schemas below before any lookup runs, and
every result is validated against its own fixed schema before being
returned -- a verb can never silently start accepting a new ad-hoc param or
emitting an undocumented result shape."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import McpValidationError

# The real, authoritative schema -- owned and written by
# dv_harness/env_manifest.py's own workstream, this package only READS it
# (same read-only discipline as manifest_source.py's relationship to the
# manifest FILE itself: consumer, never writer, of another workstream's
# artifact).
_ENV_MANIFEST_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "env_manifest.schema.json"


def _load_env_manifest_schema() -> dict:
    return json.loads(_ENV_MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8"))


ENV_MANIFEST_SCHEMA = _load_env_manifest_schema()


# ---- per-verb PARAM schemas -------------------------------------------------
# Every property is individually typed and `additionalProperties: false` --
# a caller cannot smuggle an extra, unreviewed field through any verb.

PARAM_SCHEMAS: dict[str, dict] = {
    "get_vip_config": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "instance_path": {"type": ["string", "null"]},
            "vip_type": {"type": ["string", "null"]},
        },
    },
    "get_dut_port": {
        "type": "object",
        "additionalProperties": False,
        "required": ["module_name"],
        "properties": {
            "module_name": {"type": "string", "minLength": 1},
            "port_name": {"type": ["string", "null"]},
        },
    },
    "get_register": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "block_name": {"type": ["string", "null"], "description": "register_map block name, e.g. USB3_CTRL_BLOCK."},
            "name": {"type": ["string", "null"], "description": "Register name within a block, e.g. CTRL."},
            "address": {"type": ["string", "null"], "description": "Matches EITHER a register's address_offset OR its absolute address (base_address + address_offset), both as '0x...' hex strings."},
        },
    },
    "get_topology": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "path_prefix": {"type": ["string", "null"]},
            "component_type": {"type": ["string", "null"]},
            "include_config_db": {"type": ["boolean", "null"]},
        },
    },
    "query_regression": {
        "type": "object",
        "additionalProperties": False,
        "required": ["query_shape"],
        "properties": {
            "query_shape": {"enum": ["latest", "by_pattern", "by_verdict", "by_date_range"]},
            "pattern": {"type": "string"},
            "verdict_passed": {"type": "boolean"},
            "since": {"type": "string"},
            "until": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
        },
    },
}


# ---- per-verb RESULT schemas ------------------------------------------------
# Loose on the payload sub-shape (that mirrors whatever the manifest/DB
# actually held) but strict on the envelope every result always carries:
# `verb` + `status` are present on every single result, so a caller (or a
# test) can always tell which verb answered and whether the data was really
# there without inspecting payload internals.

RESULT_SCHEMAS: dict[str, dict] = {
    "get_vip_config": {
        "type": "object",
        "required": ["verb", "status", "instances"],
        "properties": {
            "verb": {"const": "get_vip_config"},
            "status": {"enum": ["CAPTURED", "NOT_AVAILABLE"]},
            "instances": {"type": "array"},
        },
    },
    "get_dut_port": {
        "type": "object",
        "required": ["verb", "status", "module_name"],
        "properties": {
            "verb": {"const": "get_dut_port"},
            "status": {"enum": ["FOUND", "NOT_FOUND", "NOT_AVAILABLE"]},
            "module_name": {"type": "string"},
        },
    },
    "get_register": {
        "type": "object",
        "required": ["verb", "status", "registers"],
        "properties": {
            "verb": {"const": "get_register"},
            "status": {"enum": ["LOADED", "NOT_AVAILABLE"]},
            "registers": {"type": "array"},
        },
    },
    "get_topology": {
        "type": "object",
        "required": ["verb", "component_hierarchy_status", "components",
                     "config_db_trace_status", "config_db_entries"],
        "properties": {
            "verb": {"const": "get_topology"},
            "component_hierarchy_status": {"enum": ["CAPTURED", "NOT_AVAILABLE"]},
            "config_db_trace_status": {"enum": ["CAPTURED", "NOT_AVAILABLE"]},
            "components": {"type": "array"},
            "config_db_entries": {"type": "array"},
        },
    },
    "query_regression": {
        "type": "object",
        "required": ["verb", "status", "query_shape", "rows"],
        "properties": {
            "verb": {"const": "query_regression"},
            # OK: a real EvidenceStore was opened read-only and queried.
            # NOT_AVAILABLE: no evidence.duckdb file exists yet at the
            # configured path -- ReadOnlyMcpContext.call()'s honest result
            # for that case (2026-09-03 gap fix), matching every other
            # verb's own NOT_AVAILABLE-on-missing-source convention
            # (get_vip_config/get_dut_port/get_register/get_topology all
            # already report NOT_AVAILABLE rather than raising when their
            # manifest section is absent).
            "status": {"enum": ["OK", "NOT_AVAILABLE"]},
            "query_shape": {"enum": ["latest", "by_pattern", "by_verdict", "by_date_range"]},
            "rows": {"type": "array"},
        },
    },
}


def _validate(instance: Any, schema: dict, *, what: str) -> None:
    try:
        import jsonschema
    except ImportError as e:  # pragma: no cover - jsonschema is a real,
        # confirmed-installed dependency in this environment; this branch
        # exists only so importing this module never hard-fails on a
        # machine that genuinely lacks it, matching evidence_db.py's own
        # lazy-import-of-duckdb convention.
        raise McpValidationError(
            f"jsonschema package is required to validate {what} but is not installed"
        ) from e
    try:
        jsonschema.validate(instance=instance, schema=schema)
    except jsonschema.ValidationError as e:
        raise McpValidationError(f"{what} failed schema validation: {e.message}") from e


def validate_params(verb: str, params: dict) -> None:
    if verb not in PARAM_SCHEMAS:
        raise McpValidationError(f"{verb!r} is not one of the 5 fixed MCP verbs")
    _validate(params, PARAM_SCHEMAS[verb], what=f"{verb} params")


def validate_result(verb: str, result: dict) -> None:
    if verb not in RESULT_SCHEMAS:
        raise McpValidationError(f"{verb!r} is not one of the 5 fixed MCP verbs")
    _validate(result, RESULT_SCHEMAS[verb], what=f"{verb} result")


def validate_manifest(manifest: dict) -> None:
    """Validates a loaded env.manifest.json dict against the REAL, landed
    schema (ENV_MANIFEST_SCHEMA, read from dv_harness/schemas/
    env_manifest.schema.json). Used by tests to keep the synthetic fixture
    honest; verbs.py itself does NOT call this on every lookup (a manifest
    field genuinely absent from an older/newer real generator output should
    surface as that verb's own NOT_AVAILABLE/NOT_FOUND status, not a hard
    schema-validation crash)."""
    _validate(manifest, ENV_MANIFEST_SCHEMA, what="env.manifest.json")
