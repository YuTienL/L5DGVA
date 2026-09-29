# evidence-db-wiring step 2 -- vip_distill.py -> EvidenceStore.normalized_evidence bridge

Status: **DONE**

Test summary: `pytest dv_harness_tests/test_evidence_db.py dv_harness_tests/test_evidence_db_wiring.py dv_harness_tests/test_vip_distill.py dv_harness_tests/test_regression_reporter.py dv_harness_tests/test_escalation_wiring.py` -> **103 passed, 0 failed** (115.32s). A full-suite `pytest --collect-only -q` was also run to confirm this change introduces no import/collection errors anywhere else in the repo.

## Background / what this closes

Step 1 (see `.work/evidence-db-wiring-step1-report.md`) wired real
`EvidenceStore.insert_job_state()`/`insert_regression_verdict()` calls into
`regression_reporter.run_reconciliation_cycle()`. It explicitly left
`insert_normalized_evidence`/vip_distill among the "remaining-unwired API
surface". Independently, `.work/governance-vip-distill-report.md`'s own
"Follow-ups" section (#1/#2) had already flagged the same gap from the other
side: `vip_distill.write_normalized_evidence()`'s output had "nowhere to
land" because no `evidence_db.py` existed yet when that workstream was
built, and its `NORMALIZED_EVIDENCE_SCHEMA_VERSION = "0.1.0-draft"` was
explicitly marked "-draft ... until reconciled against a real
evidence_db.py schema". This step is that reconciliation: one real table,
one real upsert method, one real best-effort caller wired into the same
reconciliation cycle step 1 already instrumented.

## What was done

### 1. `dv_harness/evidence_db.py` -- new `normalized_evidence` table + `insert_normalized_evidence()`

- New `normalized_evidence` table (schema statement added to
  `_SCHEMA_STATEMENTS`), mirroring `vip_distill.py`'s own envelope shape
  1:1: `evidence_id` (PK), `schema_version`, `source_kind`, `job_id`,
  `pattern`, `protocol`, `run_dir`, `verdict`, `counts_json`, `detail_json`,
  `provenance_json`, `distilled_at`, `distiller`, `ingested_at`. `counts`/
  `detail`/`provenance` are stored as JSON text -- same convention
  `insert_job_memory_record()` already uses for `failure_signature_json`/
  `prior_related_knowledge_json`, since their internal shape varies by
  `source_kind` and this table has no need to query into them structurally.
- `EvidenceStore.insert_normalized_evidence(record: dict)` -- an upsert
  keyed on `record["evidence_id"]`, following the EXACT
  `INSERT ... ON CONFLICT (...) DO UPDATE SET ...` pattern
  `insert_job_memory_record()`/`insert_regression_verdict()` already use
  (no new upsert style invented). The natural key is not one this module
  invents -- `evidence_id` is vip_distill's OWN deterministic
  content-derived id (`vip_distill._evidence_id()`: same real evidence
  always hashes to the same id), so re-distilling and re-ingesting the same
  sim.log/job-record/fsdbreport twice upserts the same row rather than
  duplicating it, exactly like `memory_id`/`signature_key` already do for
  their own tables.
- Module header docstring updated with a `normalized_evidence` entry in the
  same "Sources, read in full before designing this schema" list style as
  every other table, explicitly naming both governance reports' open items
  and stating the upsert key.

### 2. `dv_harness/regression_reporter.py` -- new caller `_write_normalized_evidence_if_configured()`

New function, same file, same pattern as step 1's
`_write_reconciliation_evidence_if_configured()` and the pre-existing
`_escalate_uvm_fatal_burst_if_needed()`: try/except with print-and-continue,
reads the SAME `evidence_db` config block fresh each call (not a second
config key -- `normalized_evidence` lives in the same `evidence.duckdb`
file, so one on/off switch controls the whole store). Called from
`run_reconciliation_cycle()` right after step 1's own evidence writer, at
`dv_harness/regression_reporter.py:486-487`
(`_write_reconciliation_evidence_if_configured(root, reconciled)` then
`_write_normalized_evidence_if_configured(root, reconciled)`) as of the
post-review F1/F7 fixes -- originally cited as line 412 here before those
fixes shifted line numbers; re-grep the function name rather than trusting
either number going forward.

For every reconciled job with a real `state.sim_log`:
`vip_distill.distill_sim_log(log_path=state.sim_log, job_id=state.job_id,
pattern=state.pattern, run_dir=state.run_dir)` is called (a fresh parse of
the log, not threaded from the main per-job loop's own earlier
`parse_sim_log_file()` call a few dozen lines up -- same "reads fresh
rather than threaded" precedent step 1's own function already set), and its
envelope is inserted via `insert_normalized_evidence()` UNCHANGED -- this
caller never re-shapes or second-guesses vip_distill's own output. A job
with no `sim_log` is silently skipped (nothing for vip_distill to
normalize), not an error. Failures are isolated per-job (an inner
try/except around the distill+insert pair) so one bad log does not block a
sibling job's real evidence from landing, inside an outer try/except that
still catches a store-construction failure (corrupt/locked DB file) exactly
like step 1's writer does.

**Design decision worth stating explicitly: `distill_sim_log()` alone, not
`merge_evidence([distill_sim_log(...), distill_job_record(...)])`.**
`state.uvm_error_count`/`uvm_fatal_count`/`sim_status` were themselves
DERIVED from this SAME log's epilogue a few lines above in this same
function's per-job loop (`if verdict == "PASSED": state.sim_status =
"PASS"`, etc. -- see the loop starting at the `for jid, (state,
_discrepancies) in reconciled.items():` line). A `distill_job_record(asdict
(state))` envelope would therefore restate the identical real fact
`distill_sim_log()` already captured, only under a different source's own
verdict vocabulary (`"PASS"` vs. sim_log's `"PASSED"`).
`merge_evidence()`'s combined-verdict logic -- by vip_distill's own
documented design, each source's real vocabulary is "never coerced" --
reads that cosmetic vocabulary mismatch as genuinely conflicting evidence
and reports `AMBIGUOUS`, which would have misrepresented an unambiguous
real PASS/FAIL as ambiguous on essentially every job. Verified this
directly: constructing both envelopes for the same PASS job and calling
`merge_evidence()` does yield `combined_verdict == "AMBIGUOUS"` (confirmed
against `vip_distill.py`'s real logic, not asserted from reading it).
`distill_sim_log()` alone is also the richer of the two sources here (full
classified signatures + epilogue detail, versus job-record's mostly
passthrough fields), so nothing real is lost by not merging. This reasoning
is captured in the function's own docstring in `regression_reporter.py` so
a future reader does not "fix" this by adding the merge back in.

## Tests

- `dv_harness_tests/test_evidence_db.py` -- 5 new tests under a new
  `# ---- normalized_evidence` section: round-trip of scalar fields,
  `counts`/`detail`/`provenance` stored and read back correctly as JSON,
  upsert-by-`evidence_id` (re-ingesting the same id updates in place, one
  row not two), `evidence_id` required, and a real `counts=None` (the
  fsdbreport case) round-trips as a genuine SQL NULL rather than a
  JSON-encoded `"null"` masquerading as checked-but-unknown counts.
- `dv_harness_tests/test_evidence_db_wiring.py` -- new
  `TestWriteNormalizedEvidenceIfConfigured` class (5 tests, unit-level,
  same style as step 1's `TestWriteReconciliationEvidenceIfConfigured`):
  a job with a real sim_log writes a real `normalized_evidence` row with
  the real `NORMALIZED_EVIDENCE_SCHEMA_VERSION`; a job with no `sim_log` is
  skipped; the disabled-`evidence_db`-config path skips the write entirely
  (DB file never created); an unreadable sim_log for one job does not block
  a sibling job's real evidence from landing (per-job isolation); a
  corrupt/unopenable DB file never raises out of the function.
  Plus a new end-to-end test,
  `test_full_cycle_normalized_evidence_row_is_consistent_with_job_and_verdict_rows`
  (the required end-to-end test): runs a real `run_reconciliation_cycle()`
  against a synthetic job with a real-shaped FAILING sim.log fixture
  (`UVM_ERROR`/epilogue/`VERDICT: FAILED`), then queries all three tables
  -- `jobs`, `regression_verdicts`, `normalized_evidence` -- through a
  fresh `EvidenceStore` connection and asserts: the `normalized_evidence`
  row's `schema_version` matches `vip_distill.NORMALIZED_EVIDENCE_SCHEMA_
  VERSION`, `source_kind == "sim_log"`, `verdict == "FAILED"`,
  `counts_json` decodes to the real `{"uvm_fatal": 0, "uvm_error": 1,
  "uvm_warning": 0}`, and -- the explicit no-duplication/no-drift check --
  the SAME `job_id`/`pattern` identity (`333`/`"baz"`) is present and equal
  across all three tables for this one reconciled job.

Combined run confirming nothing in step 1's own tests (or vip_distill's own
tests) broke by this composition:
`pytest dv_harness_tests/test_evidence_db.py
dv_harness_tests/test_evidence_db_wiring.py dv_harness_tests/test_vip_distill.py
dv_harness_tests/test_regression_reporter.py
dv_harness_tests/test_escalation_wiring.py -q` -> **103 passed, 0 failed**
(115.32s). A full-repo `pytest --collect-only -q` was also run afterward to
confirm no import/collection error was introduced anywhere else by this
change (this repo's full suite is large enough that a full non-collect run
was not attempted here, matching the precedent already set in
`.work/governance-vip-distill-report.md`'s own report of a full-suite stall
unrelated to that workstream's changes).

## Files changed

- `dv_harness/evidence_db.py` -- new `normalized_evidence` table
  (`_SCHEMA_STATEMENTS`), new `EvidenceStore.insert_normalized_evidence()`
  method, header docstring updated with the new table's source/upsert-key
  documentation.
- `dv_harness/regression_reporter.py` -- new
  `_write_normalized_evidence_if_configured(root, reconciled)` function,
  called from `run_reconciliation_cycle()` right after step 1's own
  `_write_reconciliation_evidence_if_configured()` call.
- `dv_harness_tests/test_evidence_db.py` -- 5 new tests (+`import json`,
  previously unused in this file).
- `dv_harness_tests/test_evidence_db_wiring.py` -- new
  `TestWriteNormalizedEvidenceIfConfigured` class (5 tests) + 1 new
  end-to-end test method; `from dv_harness import vip_distill as vd` added
  to imports.
- `vip_distill.py` itself -- **untouched**, per scope (its own AST-enforced
  test, `test_module_does_not_import_orchestration_or_memory_modules`,
  still forbids it importing `duckdb`/`evidence_db`/`lsf_client`/etc.; this
  bridge's caller lives entirely in `regression_reporter.py`, exactly as
  instructed).

## Remaining unwired API surface (honest, not claimed done here)

Out of this step's stated scope, listed for a future workstream exactly
like step 1's own report did:
- `vip_distill.distill_job_record()`/`distill_fsdbreport()`/
  `merge_evidence()` have no real caller yet -- only `distill_sim_log()` is
  wired, for the documented reason above (avoiding the `AMBIGUOUS`
  vocabulary-mismatch artifact). A future workstream wiring fsdbreport
  evidence (once a real fsdbreport-producing call site exists in the
  reconciliation cycle) would call `distill_fsdbreport()` +
  `insert_normalized_evidence()` the same way, with no schema change needed
  -- `source_kind="fsdbreport"` already round-trips correctly (see the
  `counts=None` test above).
- `insert_coverage_sample()`/`insert_rtl_parse()` remain unwired, as noted
  in step 1's report -- unchanged by this step, out of scope.
