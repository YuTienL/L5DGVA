# Evidence-DB Wiring -- Step 1: Wire real EvidenceStore writes into regression_reporter

Status: **DONE**

Test summary: `python -m pytest dv_harness_tests/test_regression_reporter.py
dv_harness_tests/test_evidence_db.py dv_harness_tests/test_evidence_db_wiring.py
dv_harness_tests/test_escalation_wiring.py` -> **72 passed, 0 failed** (81.20s).

## What was wired

Before this task, `dv_harness/evidence_db.py`'s `EvidenceStore` was real and
individually tested (`dv_harness_tests/test_evidence_db.py`) but had **no
real caller** anywhere in the codebase -- `.dv-harness/evidence/
evidence.duckdb` never got written by any real reconciliation cycle. This
task wires `EvidenceStore.insert_job_state()` / `.insert_regression_verdict()`
into the one real reconciliation cycle this harness runs,
`regression_reporter.run_reconciliation_cycle()` (invoked via
`lsf-watch-start`), following the EXACT best-effort pattern already
established by `_escalate_uvm_fatal_burst_if_needed()` in the same file.

## Files changed

### `dv_harness/regression_reporter.py`

- New function `_write_reconciliation_evidence_if_configured(root, reconciled,
  jobs_for_snapshot)` -- **`dv_harness/regression_reporter.py:149-197`**.
  - **`insert_job_state()` call site: `dv_harness/regression_reporter.py:191`**
    (`store.insert_job_state(state)`) -- called unconditionally for every
    `(state, _discrepancies)` in `reconciled.items()`.
  - **`insert_regression_verdict()` call site: `dv_harness/regression_reporter.py:193-194`**
    (`store.insert_regression_verdict(state.pattern, state.sim_status == "PASS",
    job_id=state.job_id)`) -- guarded by `if state.pattern and state.sim_status
    in ("PASS", "FAIL")`.
  - Wrapped in try/except exactly like `_escalate_uvm_fatal_burst_if_needed()`:
    any exception (config read, `duckdb` missing, a locked/corrupt DB file,
    or an insert failure) is caught, printed as
    `[reconciliation_cycle] evidence store write failed: {e}`, and swallowed
    -- never breaks the cycle's own real work.
  - Reads `.dv-harness/config.json`'s new `evidence_db` block fresh each call
    (via `config.load_config(root).get("evidence_db", {})`), same convention
    as the escalation function -- this stays the only place in the module
    that knows about the evidence store.
  - `EvidenceStore` is opened via its own context manager (`with
    _evidence_db.EvidenceStore(db_path) as store:`), so the connection is
    always closed at the end of each cycle and never leaked on an exception
    path (the `with` block's `__exit__` runs even if an insert inside it
    raises; the outer `try/except` catches whatever escapes past that).
- Call site wired into `run_reconciliation_cycle()` right after
  `_escalate_uvm_fatal_burst_if_needed(root, jobs_for_snapshot)` and before
  `render_snapshot()` is called -- **`dv_harness/regression_reporter.py:410-413`**.

### Condition reuse (requirement 2)

The regression-list safety net's own `apply_verdict_to_file()` call site
(`dv_harness/regression_reporter.py:430` as of the post-review F1/F7 fixes;
originally line 305-307 before this task's edits shifted line numbers, then
355, then 430 -- line-cited call sites in this repo drift as the file grows,
so treat any specific line number here as approximate and re-grep before
relying on it) uses:

```python
if state.pattern and verdict in ("PASSED", "FAILED"):
```

`_write_reconciliation_evidence_if_configured()` runs AFTER the per-job
analysis loop (over `reconciled`, a dict of already-finished `(state,
discrepancies)` tuples, not inside that loop), so the local `verdict`
variable is no longer in scope. `state.sim_status` was set from that exact
same `verdict` a few lines above the `apply_verdict_to_file()` call
(`PASSED -> "PASS"`, `FAILED -> "FAIL"`), in lock-step, so the mirrored
condition used here is:

```python
if state.pattern and state.sim_status in ("PASS", "FAIL"):
```

This is documented in the new function's own docstring so the next agent
does not need to re-derive it.

### `dv_harness/config.py`

New `evidence_db` block appended after the existing `escalation` block
(`dv_harness/config.py`, in `DEFAULT_CONFIG`):

```python
"evidence_db": {
    "enabled": True,
},
```

**Default-enabled reasoning** (per the task's explicit ask to document it):
unlike `escalation`/`knowledge_center`/`self_tuning` (all opt-in `False`),
this write touches only a local `.dv-harness/evidence/evidence.duckdb` file
on the machine running the cycle -- no network call, no credential, no
cross-user visibility. There is no exposure surface that argues for
opt-in-off, and the entire point of this task is for the evidence store to
actually receive real cycle data by default rather than silently staying
empty unless a user discovers and flips a config flag. `enabled: false` is
still available for a dry-run project or a machine without `duckdb`
installed (construction failure is caught and logged either way, never
fatal).

## Connection lifecycle (requirement 4)

`EvidenceStore.__enter__`/`__exit__` (`dv_harness/evidence_db.py:221-225`)
already exist and were not modified. The new wiring uses them via `with
_evidence_db.EvidenceStore(db_path) as store:` -- one connection opened and
closed per reconciliation cycle, never held open across cycles, never
leaked on an exception (the `with` statement's own `__exit__` still fires on
an exception raised by an `insert_*` call inside the block; the enclosing
`try/except` around the whole function additionally guards construction
failure itself, e.g. a locked/corrupt DB file where `EvidenceStore.__init__`
raises before `__enter__` is ever reached).

## Tests added

New file `dv_harness_tests/test_evidence_db_wiring.py` (9 tests, all
passing), deliberately **not** mocking `EvidenceStore` itself -- only the
LSF/live-job discovery layer this file's existing `test_regression_reporter.py`
tests already mock (`lsf_client.discover_live_jobs` / `lsf_client._run_bjobs`):

- `TestWriteReconciliationEvidenceIfConfigured` (unit-level, calling
  `_write_reconciliation_evidence_if_configured()` directly with a synthetic
  `reconciled` dict):
  - PASS verdict -> real `jobs` row + real `regression_verdicts` row
    (`verdict_passed=True`).
  - FAIL verdict -> real rows, `verdict_passed=False`.
  - Indeterminate (`sim_status="UNKNOWN"`) -> `jobs` row written, **no**
    `regression_verdicts` row (mirrors `apply_verdict_to_file()` not being
    called either).
  - Missing `pattern` -> same as above (no verdict row).
  - Empty `reconciled` -> no error, DB file created with empty tables
    (schema init is idempotent `CREATE TABLE IF NOT EXISTS`).
  - `evidence_db.enabled=False` in `.dv-harness/config.json` -> DB file is
    never even created.
  - `EvidenceStore` construction raising (simulated locked/corrupt DB) ->
    no exception escapes.
- `TestReconciliationCycleEndToEndEvidenceWrite` (real, full
  `run_reconciliation_cycle()` calls -- **the tests that prove "DuckDB
  stops being empty"**):
  - `test_full_cycle_leaves_real_rows_in_evidence_duckdb`: runs one real
    cycle against a temp project root (job 111, pattern "foo", PASSED
    epilogue), then opens `evidence.duckdb` through a **fresh**
    `EvidenceStore`/DuckDB connection (independent of whatever connection
    the cycle itself used) and asserts real `jobs` and `regression_verdicts`
    rows exist, alongside confirming the cycle's pre-existing real work
    (`regression.list`) still happened.
  - `test_db_write_failure_does_not_break_the_reconciliation_cycle`:
    pre-writes a corrupt (not-a-valid-DuckDB-file) `evidence.duckdb`
    (confirmed via a standalone `duckdb.connect()` probe that this raises a
    real `duckdb.IOException`), then runs a full cycle and asserts the
    cycle's own real work (job state persisted, `regression.list` updated,
    snapshot returned and containing the job) still completes normally
    despite the unopenable DB.

## Scope discipline

Per the task's instruction, only `regression_reporter.py`, `evidence_db.py`
(read-only -- no changes needed there; its existing API and context-manager
support were sufficient), `config.py`, and their tests were touched.
`vip_distill.py` was not modified, read, or imported from the new code --
the bridge/ingestion caller for `vip_distill`'s normalized-evidence output
is explicitly left for the next agent, per the task's own note that the
caller belongs outside `vip_distill.py`.

## For the next agent (vip_distill bridge, step 2)

- The `EvidenceStore` open/close pattern to reuse:
  `dv_harness/regression_reporter.py:149-197` at the time this note was
  written (`_write_reconciliation_evidence_if_configured`; line numbers
  have since shifted -- re-grep the function name rather than trusting the
  number).
- `insert_job_state()` call site: was `dv_harness/regression_reporter.py:191`
  at the time this note was written.
- `insert_regression_verdict()` call site + its exact guard condition: was
  `dv_harness/regression_reporter.py:193-194` at the time this note was
  written (guard: `state.pattern and state.sim_status in ("PASS", "FAIL")`,
  derived from the `apply_verdict_to_file()` call site's `state.pattern and
  verdict in ("PASSED", "FAILED")` condition -- that guard now lives at
  `dv_harness/regression_reporter.py:430`, not the `:355` originally cited
  here).
- The new `evidence_db` config block lives in `dv_harness/config.py`'s
  `DEFAULT_CONFIG["evidence_db"]` (`enabled: True` by default) -- read it
  the same way (`config.load_config(root).get("evidence_db", {})`) rather
  than inventing a second config block for `vip_distill` output ingestion,
  unless the next agent has a concrete reason the two should be independently
  toggleable.
- `EvidenceStore.insert_job_memory_record()` (job_result/job_failure +
  failure_signature aggregation) and `.insert_coverage_sample()` /
  `.insert_rtl_parse()` remain **unwired** -- out of this step's scope, but
  real, tested, and available on the same `EvidenceStore` instance if a
  future step wants to fold `vip_distill.write_normalized_evidence()`'s
  output (or a `job_result`/`job_failure` memory record, or a coverage/RTL
  parse) into the same per-cycle `with EvidenceStore(...) as store:` block
  this task introduced.
