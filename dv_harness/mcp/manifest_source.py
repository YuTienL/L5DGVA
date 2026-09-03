"""dv_harness/mcp/manifest_source.py -- the ONLY function in this package
that touches env.manifest.json on disk, and it only ever reads it.

`load_manifest()` opens the file in default (read) mode via
`Path.read_text()`, parses it as JSON, and returns a plain dict. There is no
companion `save_manifest()`/`write_manifest()` function in this module, and
none should ever be added here -- the manifest is owned and written
exclusively by the separate env.manifest.json GENERATOR workstream
(dv_harness/env_manifest.py, per this task's own brief); this MCP server is
a read-only CONSUMER of that file only. See
dv_harness_tests/test_mcp_read_only_boundary.py for the static + behavioral
proof this boundary actually holds."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Union

from .errors import McpError, McpNotFoundError


def load_manifest(manifest_path: Union[str, Path]) -> dict:
    """Reads and parses env.manifest.json fresh from disk. Deliberately does
    NOT cache across calls -- an MCP verb answering "what is the current
    value" must reflect whatever the generator most recently wrote, not a
    stale in-memory copy from an earlier call in a long-lived server
    process."""
    path = Path(manifest_path)
    if not path.is_file():
        raise McpNotFoundError(f"env.manifest.json not found at {path}")
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise McpError(f"env.manifest.json at {path} is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise McpError(f"env.manifest.json at {path} must decode to a JSON object, got {type(data).__name__}")
    return data
