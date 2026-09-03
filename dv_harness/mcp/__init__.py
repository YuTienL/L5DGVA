"""dv_harness/mcp -- internal, READ-ONLY MCP server exposing exactly 5
fixed verbs: get_vip_config, get_dut_port, get_register, get_topology,
query_regression. No free-text query verb, no write verb, no arbitrary
file-read verb -- see .work/mcp-server-report.md for the full design
writeup and dv_harness_tests/test_mcp_read_only_boundary.py for the
enforced (not merely documented) read-only proof.

Layout (mirrors dv_harness/uvm_generator/'s subpackage-with-schemas
precedent):
  errors.py             -- exception types
  manifest_source.py     -- the ONLY read of env.manifest.json in this package
  schema.py + schemas/    -- fixed per-verb param/result JSON Schemas, plus
                             this package's own ASSUMED env.manifest.json
                             contract (reconciliation-pending against the
                             real generator -- see that schema file's header)
  verbs.py                -- the 5 verbs' real logic (framework-agnostic)
  regression_queries.py   -- query_regression's fixed SQL shapes over
                             evidence_db.EvidenceStore.query()
  runtime.py              -- ReadOnlyMcpContext: the framework-agnostic
                             JSON-in/JSON-out `.call(verb, params)` entry
                             point over real manifest/DB paths
  server.py               -- thin transport wrapper around the real `mcp`
                             SDK (mcp.server.mcpserver.MCPServer), layered
                             on top of runtime.py

Only `errors`/`runtime`/`verbs` are imported at package-import time -- none
of them require the `mcp` transport SDK or `duckdb`/`jsonschema` to be
importABLE at import time (those are imported lazily, inside the functions
that actually need them), so `import dv_harness.mcp` never hard-fails on an
environment missing one of those optional packages. `server.py` (which DOES
hard-require `mcp`) is imported explicitly by a caller that wants the real
transport, e.g. `from dv_harness.mcp.server import build_server`."""
from __future__ import annotations

from .errors import McpError, McpNotFoundError, McpUnknownVerbError, McpValidationError
from .runtime import ReadOnlyMcpContext
from .verbs import VERBS, dispatch

__all__ = [
    "McpError",
    "McpNotFoundError",
    "McpUnknownVerbError",
    "McpValidationError",
    "ReadOnlyMcpContext",
    "VERBS",
    "dispatch",
]
