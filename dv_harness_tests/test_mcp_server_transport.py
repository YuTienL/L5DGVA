"""Tests for dv_harness/mcp/server.py -- the thin transport wrapper around
the real, confirmed-installed `mcp` SDK (mcp.server.mcpserver.MCPServer,
version 2.1.1 as of 2026-09-03; see server.py's own module docstring for
how that was confirmed live rather than assumed). Skipped outright (not
failed) on any machine where `mcp` genuinely is not installed -- this
package's core (runtime.py/verbs.py/regression_queries.py, exercised by
test_mcp_verbs.py/test_mcp_query_regression.py) has no such dependency and
stays fully tested either way, per this task's own "function set first,
transport wrapper only if confirmed available" framing."""
from __future__ import annotations

import asyncio
import json

import pytest

mcp = pytest.importorskip("mcp")
duckdb = pytest.importorskip("duckdb")
pytest.importorskip("jsonschema")

from dv_harness.evidence_db import EvidenceStore
from dv_harness.mcp.server import SERVER_DESCRIPTION, build_server

from .mcp_manifest_fixture import build_fixture_manifest


@pytest.fixture
def manifest_path(tmp_path):
    path = tmp_path / "env.manifest.json"
    path.write_text(json.dumps(build_fixture_manifest()), encoding="utf-8")
    return path


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "evidence.duckdb"
    store = EvidenceStore(path)
    store.insert_regression_verdict("usb3_lfps_basic", True, job_id=1)
    store.close()
    return path


def _content_json(call_result):
    """A real CallToolResult's `.content` is a list of TextContent blocks;
    this package's tools always return one dict, so this is always exactly
    one JSON-text block."""
    assert len(call_result.content) == 1
    return json.loads(call_result.content[0].text)


def test_build_server_registers_exactly_the_5_fixed_tools(manifest_path, db_path):
    server = build_server(manifest_path, db_path)

    async def _list():
        return await server.list_tools()

    tools = asyncio.run(_list())
    names = {t.name for t in tools}
    assert names == {
        "get_vip_config", "get_dut_port", "get_register", "get_topology", "query_regression",
    }


def test_server_description_states_the_fixed_verb_design_goal(manifest_path, db_path):
    server = build_server(manifest_path, db_path)
    assert "get_vip_config" in SERVER_DESCRIPTION
    assert "query_regression" in SERVER_DESCRIPTION
    assert "no write verb" in SERVER_DESCRIPTION.lower() or "read-only" in SERVER_DESCRIPTION.lower()


def test_call_tool_get_vip_config_through_real_sdk(manifest_path, db_path):
    server = build_server(manifest_path, db_path)

    async def _call():
        return await server.call_tool("get_vip_config", {"vip_type": "usb3_vip_config"})

    result = asyncio.run(_call())
    assert result.is_error is False
    payload = _content_json(result)
    assert payload["status"] == "CAPTURED"
    assert payload["match_count"] == 1


def test_call_tool_get_dut_port_requires_module_name_through_real_sdk(manifest_path, db_path):
    server = build_server(manifest_path, db_path)

    async def _call():
        return await server.call_tool("get_dut_port", {"module_name": "apb_bridge"})

    result = asyncio.run(_call())
    assert result.is_error is False
    payload = _content_json(result)
    assert payload["status"] == "FOUND"
    assert {p["name"] for p in payload["ports"]} == {"pclk", "pready"}


def test_call_tool_query_regression_through_real_sdk(manifest_path, db_path):
    server = build_server(manifest_path, db_path)

    async def _call():
        return await server.call_tool("query_regression", {"query_shape": "latest", "limit": 5})

    result = asyncio.run(_call())
    assert result.is_error is False
    payload = _content_json(result)
    assert payload["query_shape"] == "latest"
    assert payload["row_count"] == 1


def test_call_tool_unknown_tool_name_is_rejected_by_the_real_sdk(manifest_path, db_path):
    """The SDK itself refuses a tool name that was never registered -- this
    is the real-transport-level version of the same fixed-5-verbs guarantee
    verbs.dispatch() already enforces at the core layer."""
    server = build_server(manifest_path, db_path)

    async def _call():
        return await server.call_tool("run_arbitrary_shell_command", {})

    with pytest.raises(Exception):
        asyncio.run(_call())
