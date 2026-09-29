"""dv_harness/mcp/server.py -- thin MCP-SDK transport wrapper around the 5
fixed read-only verbs in verbs.py/runtime.py.

**Which case of this task's point 4 applies (checked live, 2026-09-03, not
guessed)**: `import mcp` initially failed (`ModuleNotFoundError`, confirmed
via `pip show mcp` reporting not-installed) -- so this environment did NOT
already have an MCP SDK dependency/pattern established anywhere in this
repo. Per the task brief's own fallback instruction, `pip install mcp` was
then run to check whether a real MCP SDK is installable here at all (this
session does have outbound network access); it resolved and installed the
official Model Context Protocol Python SDK, version 2.1.1
(`mcp.server.mcpserver.MCPServer` -- 2.x's current name for the class 1.x
releases of this same SDK called `FastMCP`; importing
`mcp.server.fastmcp.FastMCP` under 2.1.1 raises a `ModuleNotFoundError`
whose own message states this rename). So: **a real MCP SDK IS confirmed
available**, and this module is a REAL thin transport wrapper around it,
not a placeholder JSON-line dispatcher. See .work/mcp-server-report.md for
the full disclosure.

This module registers EXACTLY 5 tools -- one per fixed verb -- and nothing
else (no resource/prompt registrations, no extra tools). Each tool function
below only (a) takes individually-typed keyword arguments so the SDK can
auto-generate a real per-tool input schema, (b) folds them into the one
`params` dict `ReadOnlyMcpContext.call()` already expects, and (c) returns
exactly what that already-validated core returned. No tool function here
performs a file/DB write of any kind -- see
dv_harness_tests/test_mcp_read_only_boundary.py, which statically scans
this file (along with every other file in this package) for write-capable
calls, and dv_harness_tests/test_mcp_server_transport.py, which drives this
real MCPServer instance end-to-end through the SDK's own `list_tools()`/
`call_tool()` API."""
from __future__ import annotations

from typing import Optional

from mcp.server.mcpserver import MCPServer

from .runtime import ReadOnlyMcpContext

SERVER_NAME = "dv-harness-env-mcp"
SERVER_DESCRIPTION = (
    "Internal, read-only access to env.manifest.json + the regression "
    "evidence DB. Exposes EXACTLY 5 fixed verbs -- get_vip_config, "
    "get_dut_port, get_register, get_topology, query_regression -- no "
    "free-text query verb, no write verb, no arbitrary file-read verb."
)


def build_server(manifest_path, evidence_db_path=None, *, name: str = SERVER_NAME) -> MCPServer:
    """Builds a real MCPServer exposing exactly the 5 fixed verbs as MCP
    tools, backed by a ReadOnlyMcpContext over `manifest_path`/
    `evidence_db_path`. Nothing else is registered on the returned
    server."""
    ctx = ReadOnlyMcpContext(manifest_path, evidence_db_path)
    server = MCPServer(name, version="1.0.0", description=SERVER_DESCRIPTION)

    @server.tool()
    def get_vip_config(instance_path: Optional[str] = None, vip_type: Optional[str] = None) -> dict:
        """VIP layer: a VIP instance's own already-resolved config, captured
        from a zero-time end_of_elaboration_phase dump -- never
        documentation. Omit both args to list every captured instance."""
        return ctx.call("get_vip_config", {"instance_path": instance_path, "vip_type": vip_type})

    @server.tool()
    def get_dut_port(module_name: str, port_name: Optional[str] = None) -> dict:
        """DUT layer: ports + parameters for one module, sourced from
        verible --export_json facts. `module_name` is required."""
        return ctx.call("get_dut_port", {"module_name": module_name, "port_name": port_name})

    @server.tool()
    def get_register(name: Optional[str] = None, address: Optional[str] = None) -> dict:
        """DUT layer: register facts from a structured RAL/IP-XACT-style
        source. Omit both args to list every register."""
        return ctx.call("get_register", {"name": name, "address": address})

    @server.tool()
    def get_topology(path_prefix: Optional[str] = None, component_type: Optional[str] = None,
                      include_config_db: bool = True) -> dict:
        """Env layer: component hierarchy (active/passive per real
        uvm_top.print_topology() output) + raw config_db SET/GET trace
        events from +UVM_CONFIG_DB_TRACE, filterable by a component/reporter
        path_prefix. Returns honest SET/GET event counts; does not claim a
        per-field matched/miswired verdict (see verbs.get_topology's own
        docstring for why -- the trace message body is intentionally left
        unparsed by the real generator)."""
        return ctx.call("get_topology", {
            "path_prefix": path_prefix, "component_type": component_type,
            "include_config_db": include_config_db,
        })

    @server.tool()
    def query_regression(query_shape: str, pattern: Optional[str] = None,
                          verdict_passed: Optional[bool] = None,
                          since: Optional[str] = None, until: Optional[str] = None,
                          limit: Optional[int] = None) -> dict:
        """Regression evidence via ONE of a fixed set of query shapes:
        "latest" (limit), "by_pattern" (pattern), "by_verdict"
        (verdict_passed), "by_date_range" (since, until) -- never
        caller-supplied raw SQL."""
        params: dict = {"query_shape": query_shape}
        for key, value in (("pattern", pattern), ("verdict_passed", verdict_passed),
                            ("since", since), ("until", until), ("limit", limit)):
            if value is not None:
                params[key] = value
        return ctx.call("query_regression", params)

    return server


def main(argv=None) -> int:
    """CLI entry point: `python -m dv_harness.mcp.server --manifest <path>
    [--evidence-db <path>]` runs the real stdio MCP transport via
    `MCPServer.run(transport="stdio")`. Not exercised by the automated test
    suite (it blocks on stdio for a real client) -- `build_server()` above
    is what tests drive directly through the SDK's own in-process
    `list_tools()`/`call_tool()` API."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="Path to env.manifest.json")
    parser.add_argument("--evidence-db", default=None, help="Path to the evidence.duckdb file")
    args = parser.parse_args(argv)
    server = build_server(args.manifest, args.evidence_db)
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":  # pragma: no cover - real stdio entry point
    raise SystemExit(main())
