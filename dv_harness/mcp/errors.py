"""dv_harness/mcp/errors.py -- exception types for the internal read-only
MCP server. Every one of the 5 fixed verbs (get_vip_config, get_dut_port,
get_register, get_topology, query_regression) raises one of these on any
input/lookup problem rather than returning a silently-wrong result; none of
these are ever raised as a side effect of a write attempt succeeding
partially, because no write path exists in this package at all -- see
dv_harness_tests/test_mcp_read_only_boundary.py."""
from __future__ import annotations


class McpError(Exception):
    """Base class for every error this package raises."""


class McpNotFoundError(McpError):
    """A required real input (env.manifest.json itself, an evidence DB file)
    does not exist. Distinct from a verb reporting NOT_FOUND/NOT_AVAILABLE
    as a normal successful JSON result for a missing manifest SECTION or
    ENTRY -- this is for the file-level precondition."""


class McpValidationError(McpError):
    """Params (or, in a test, a result) failed schema validation against
    this verb's fixed JSON Schema, or a query_regression call named a
    query_shape outside the fixed set / omitted a shape's required
    params."""


class McpUnknownVerbError(McpError):
    """Caller asked for a verb name outside the fixed set of exactly 5.
    There is no free-text/catch-all verb this ever falls through to."""
