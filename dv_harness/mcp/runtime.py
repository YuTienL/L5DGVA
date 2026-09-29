"""dv_harness/mcp/runtime.py -- the framework-agnostic runtime context: a
single JSON-in/JSON-out `.call(verb, params)` entry point over the 5 fixed
verbs, backed by real on-disk env.manifest.json + evidence.duckdb paths.
Imports nothing from `mcp` (the transport SDK) -- `server.py` is the thin
wrapper layered on top of THIS class, not the other way around, so this
class (and everything it depends on: manifest_source.py, verbs.py,
regression_queries.py, schema.py) stays fully usable/testable in an
environment without the `mcp` package installed at all, per this task's own
"function set first, transport wrapper only if a real SDK is confirmed
available" instruction."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from . import schema, verbs
from .errors import McpError
from .manifest_source import load_manifest


class ReadOnlyMcpContext:
    """Holds configured paths only (not open file handles) -- every `.call()`
    re-reads env.manifest.json fresh via manifest_source.load_manifest()
    (see that module's own docstring for why: no staleness across a
    long-lived server process) and opens a fresh, short-lived, genuinely
    read-only EvidenceStore connection (`read_only=True`, 2026-09-03 gap
    fix -- see evidence_db.EvidenceStore's own docstring) for a
    query_regression call, closed again before `.call()` returns. This
    class itself has no method that could write to either -- it only ever
    calls `verbs.dispatch()`, which itself only ever calls
    `EvidenceStore.query()` (see regression_queries.py) and plain dict
    reads over the manifest.

    2026-09-03 gap fix history: this class used to open its EvidenceStore
    with the default (read-write) constructor, which -- via
    EvidenceStore.__init__'s unconditional `mkdir()` + `CREATE TABLE IF NOT
    EXISTS` schema init -- silently created the evidence directory/file
    from nothing, and added any of this project's schema tables an
    existing DB happened to be missing, on every single call. That directly
    contradicted this package's whole read-only design premise (see
    test_mcp_read_only_boundary.py's own docstring) and went undetected
    because the AST-based boundary test only scans files under
    dv_harness/mcp/ (the actual mkdir/execute calls live in evidence_db.py,
    outside that scan's scope) and the byte-identical-files test always
    seeded the DB via EvidenceStore first, so the schema already existed
    and the DDL calls were no-ops by the time hashes were compared -- the
    non-existent-DB and partial-schema cases were never exercised. See
    .work/gap-fix-mcp-readonly-report.md for the full before/after proof."""

    def __init__(self, manifest_path: Union[str, Path],
                 evidence_db_path: Optional[Union[str, Path]] = None):
        self.manifest_path = Path(manifest_path)
        self.evidence_db_path = Path(evidence_db_path) if evidence_db_path else None

    def call(self, verb: str, params: Optional[dict] = None) -> dict:
        params = params or {}
        if verb == "query_regression":
            if self.evidence_db_path is None:
                raise McpError(
                    "query_regression requires this context to be constructed "
                    "with an evidence_db_path")
            # Validated up front, before ever touching the DB path, so a
            # malformed call (bad/missing query_shape, unknown param) still
            # raises McpValidationError regardless of whether an evidence DB
            # exists -- the same "validate first" order every other verb in
            # verbs.py already follows, and verbs.dispatch()/query_regression
            # would validate again anyway (idempotent) once a real store is
            # in hand below.
            schema.validate_params("query_regression", params)
            # Imported here, not at module load, so constructing/using this
            # class for manifest-only verbs never requires duckdb to be
            # installed -- mirrors evidence_db.EvidenceStore's own lazy
            # import of duckdb for the identical reason.
            import duckdb

            from dv_harness.evidence_db import EvidenceStore
            try:
                store = EvidenceStore(self.evidence_db_path, read_only=True)
            except duckdb.IOException:
                # Caught specifically (not a broad `except duckdb.Error`)
                # because duckdb.IOException on a read_only=True connect is
                # the one, verified failure mode a genuinely-missing
                # evidence.duckdb file produces (see evidence_db.py's
                # EvidenceStore.__init__ read_only branch) -- any OTHER
                # duckdb error (a corrupt file, a real query bug) is a
                # different, real problem that must still propagate rather
                # than being silently folded into "no DB yet". This mirrors
                # get_vip_config/get_dut_port/get_register/get_topology's
                # own established convention of reporting an absent real
                # source as an honest NOT_AVAILABLE result rather than
                # raising -- so a caller sees one consistent shape for "this
                # evidence source doesn't exist yet" across all 5 verbs.
                result = {
                    "verb": "query_regression",
                    "status": "NOT_AVAILABLE",
                    "reason": f"no evidence database exists yet at {self.evidence_db_path}",
                    "query_shape": params["query_shape"],
                    "row_count": 0,
                    "rows": [],
                }
                schema.validate_result("query_regression", result)
                return result
            try:
                return verbs.dispatch(verb, params, evidence_store=store)
            finally:
                store.close()
        manifest = load_manifest(self.manifest_path)
        return verbs.dispatch(verb, params, manifest=manifest)
