# Gap Fix: MCP Server Read-Only Violation (2026-09-03)

## Status: DONE

One-line test summary: **143 passed, 0 failed** across
`test_evidence_db.py`, `test_evidence_db_wiring.py`, `test_mcp_read_only_boundary.py`,
`test_mcp_query_regression.py`, `test_mcp_verbs.py`, `test_mcp_manifest_and_schema.py`,
`test_mcp_env_manifest_integration.py`, `test_mcp_server_transport.py` (includes the
2 new tests named in the task plus 3 supporting `EvidenceStore`-level tests).

## The defect (as proven by the reviewer)

`dv_harness/mcp/runtime.py`'s `ReadOnlyMcpContext.call()` opened its evidence DB via
plain `EvidenceStore(self.evidence_db_path)`. `EvidenceStore.__init__` unconditionally:

```python
self.db_path.parent.mkdir(parents=True, exist_ok=True)   # filesystem write
self._conn = duckdb.connect(str(self.db_path))            # READ-WRITE, creates file if missing
for stmt in _SCHEMA_STATEMENTS:
    self._conn.execute(stmt)                               # CREATE TABLE / CREATE SEQUENCE
```

so every `query_regression` call through the MCP context could create a directory, create
a 536KB `evidence.duckdb` file from nothing, and/or add missing schema tables to an
existing file — directly contradicting the module's whole "genuinely read-only" design
premise (`dv_harness_tests/test_mcp_read_only_boundary.py`'s own docstring).

Why the existing tests missed it: the AST-based read-only-boundary test only scans files
under `dv_harness/mcp/` — the real `mkdir`/`execute` calls live in `evidence_db.py`,
outside that scan's scope. The byte-identical-files test always seeded the DB via
`EvidenceStore` *before* constructing the MCP context, so by hash-comparison time the
schema already existed and every `CREATE ... IF NOT EXISTS` was a no-op — the
non-existent-DB and partial-schema cases were never exercised.

## The fix

1. **`dv_harness/evidence_db.py`** — `EvidenceStore.__init__` now takes a keyword-only
   `read_only: bool = False`. When `True`:
   - `mkdir()` is never called.
   - The schema DDL loop is never run.
   - The connection is opened via `duckdb.connect(str(db_path), read_only=True)`, which
     itself raises `duckdb.IOException` on a missing file (verified: never creates it) and
     would raise `duckdb.InvalidInputException`/similar on any DDL/DML attempted afterward
     (verified directly — see `test_read_only_true_blocks_ddl_and_dml`) — real
     defense-in-depth on top of this class simply issuing no DDL in this branch.

2. **`dv_harness/mcp/runtime.py`** — `ReadOnlyMcpContext.call()` now opens
   `EvidenceStore(self.evidence_db_path, read_only=True)`. Params are validated
   (`schema.validate_params`) *before* the open attempt, matching every other verb's
   "validate first" convention. The open is wrapped in
   `try/except duckdb.IOException` (caught specifically, not a broad `except duckdb.Error`,
   so a genuinely different problem — a corrupt file, a real query bug — still propagates
   instead of being silently folded into "no DB yet"). On that specific exception, `call()`
   returns a clean result instead of letting the exception reach the MCP client:

   ```python
   {
       "verb": "query_regression",
       "status": "NOT_AVAILABLE",
       "reason": f"no evidence database exists yet at {self.evidence_db_path}",
       "query_shape": params["query_shape"],
       "row_count": 0,
       "rows": [],
   }
   ```

   This mirrors the exact convention `get_vip_config`/`get_dut_port`/`get_register`/
   `get_topology` already use for "the real source isn't there" (a `NOT_AVAILABLE`/
   `NOT_FOUND` status with a `reason`, never a raised exception for an absent-but-expected
   source) — chosen so a caller sees one consistent shape across all 5 verbs for "this
   evidence source doesn't exist yet," rather than a special case for `query_regression`
   alone.

3. **`dv_harness/mcp/schema.py`** — `RESULT_SCHEMAS["query_regression"]["status"]` widened
   from `{"const": "OK"}` to `{"enum": ["OK", "NOT_AVAILABLE"]}` so the new honest result
   still passes `schema.validate_result()`.

4. **New tests**:
   - `dv_harness_tests/test_mcp_read_only_boundary.py::test_query_regression_against_nonexistent_db_creates_no_directory_or_file`
     — points `ReadOnlyMcpContext` at a `db_path` under a directory that never existed;
     confirms no directory is created, no file is created, and a clean `NOT_AVAILABLE`
     result comes back (not an unhandled exception).
   - `dv_harness_tests/test_mcp_read_only_boundary.py::test_query_regression_against_partial_schema_db_adds_no_tables_stays_byte_identical`
     — seeds a real `evidence.duckdb` with **only** a hand-created `regression_verdicts`
     table (raw SQL, never through `EvidenceStore`, which would create all 9 real tables) —
     the exact partial-schema gap the review found the existing byte-identical test never
     exercised — then drives every verb (including 3 `query_regression` shapes) through the
     real `ReadOnlyMcpContext` and confirms the file's SHA-256 hash and its `SHOW TABLES`
     list are both unchanged.
   - Also fixed a real DuckDB-connection-config conflict this fix exposed in the
     pre-existing `test_evidence_db_row_count_unchanged_after_every_verb_call`: it kept a
     read-write `EvidenceStore` connection open across the whole `ctx.call()` loop, which
     now fails with `duckdb.ConnectionException: ... different configuration than existing
     connections` once `ReadOnlyMcpContext` genuinely opens `read_only=True` (DuckDB
     refuses two same-process connections to one file with different access modes). Fixed
     by closing the seeding connection before `ctx.call()` runs and reopening a fresh one to
     verify counts afterward — a real, load-bearing ordering, not incidental cleanup, now
     documented inline in the test.
   - Three supporting `EvidenceStore`-level tests added directly in
     `dv_harness_tests/test_evidence_db.py`:
     `test_read_only_true_against_missing_file_raises_without_creating_anything`,
     `test_read_only_true_against_existing_db_does_not_add_missing_tables`,
     `test_read_only_true_blocks_ddl_and_dml`.

## Before/after: reproducing the reviewer's exact repro against the FIXED code

Live run against the fixed code (see command output below), reproducing both of the
reviewer's original scenarios:

### Repro A — non-existent DB path

**Old code** (`EvidenceStore(db_path)`, no `read_only`) — confirmed still on this machine
by calling the unmodified default constructor directly:
```
BEFORE: dir exists? False   file exists? False
AFTER:  dir exists? True    file exists? True   size bytes: 536576
```
Matches the reviewer's original finding exactly (~536KB file + directory created from
nothing).

**Fixed code** (`ReadOnlyMcpContext.call("query_regression", ...)`):
```
BEFORE: dir exists? False   file exists? False
AFTER:  dir exists? False   file exists? False
result: {'verb': 'query_regression', 'status': 'NOT_AVAILABLE',
         'reason': 'no evidence database exists yet at <path>',
         'query_shape': 'latest', 'row_count': 0, 'rows': []}
```
No directory, no file, and a clean result instead of an unhandled exception.

### Repro B — pre-existing partial-schema DB

**Old code**: DB seeded with only 1 table (`regression_verdicts`); calling
`EvidenceStore(db_path)` again (the old runtime.py's own code path):
```
BEFORE: tables = ['regression_verdicts']                                    (1 table)
AFTER:  tables = ['coverage_samples', 'failure_signatures', 'job_memory_records',
                  'jobs', 'normalized_evidence', 'regression_verdicts',
                  'rtl_modules', 'rtl_parameters', 'rtl_ports', 'rtl_signals']  (10 tables)
tables added: 9
```
Matches the reviewer's original finding exactly (9 tables added).

**Fixed code** (`ReadOnlyMcpContext.call("query_regression", ...)` against the same
partial-schema DB):
```
BEFORE: tables = ['regression_verdicts']   hash = 79bada5091eb...
AFTER:  tables = ['regression_verdicts']   hash = 79bada5091eb...
result status: OK   row_count: 1
tables unchanged: True   hash unchanged: True
```

Both of the reviewer's exact repros no longer reproduce against the fixed code.

## Test run

```
python -m pytest dv_harness_tests/test_evidence_db.py dv_harness_tests/test_mcp_read_only_boundary.py \
  dv_harness_tests/test_mcp_query_regression.py dv_harness_tests/test_mcp_verbs.py \
  dv_harness_tests/test_mcp_manifest_and_schema.py dv_harness_tests/test_mcp_env_manifest_integration.py \
  dv_harness_tests/test_mcp_server_transport.py dv_harness_tests/test_evidence_db_wiring.py -q

143 passed in 93.68s
```

## Files touched

- `dv_harness/evidence_db.py` — `EvidenceStore.__init__` gains real `read_only: bool = False`
  support (class docstring updated too). Note: this file already carried uncommitted,
  unrelated changes from a concurrent workstream (the `normalized_evidence` table) when
  this fix started — those were left untouched; this fix's diff is additive on top of them.
- `dv_harness/mcp/runtime.py` — `ReadOnlyMcpContext.call()` opens `EvidenceStore(...,
  read_only=True)`, validates params first, and catches `duckdb.IOException` into a clean
  `NOT_AVAILABLE` result.
- `dv_harness/mcp/schema.py` — `query_regression` result schema's `status` widened to allow
  `NOT_AVAILABLE` alongside `OK`.
- `dv_harness_tests/test_evidence_db.py` — 3 new `read_only=True` tests (also already
  carried unrelated concurrent `normalized_evidence` test additions, left untouched).
- `dv_harness_tests/test_mcp_read_only_boundary.py` — 2 new tests closing the exact gap the
  review named, plus a necessary fix to the pre-existing row-count test's connection
  lifecycle (see above).

## Scope note

Per this session's shared-tree caution: `git status --short` was checked before editing
each file, and `git diff <file>` was reviewed for `evidence_db.py` and `test_evidence_db.py`
specifically (both already had uncommitted changes from a separate, concurrent
`normalized_evidence`/DuckDB-wiring workstream) before this fix's own edits were layered on
top. Nothing has been committed as part of this fix — consistent with the stated state that
none of the 4 workstreams' changes have been committed yet.
