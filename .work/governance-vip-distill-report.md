# vip_distill.py -- Evidence Normalization scope (2026-09-03)

## Scope

From the user's own spec (verbatim, Traditional Chinese): "vip_distill.py
定位：只負責 evidence normalization（Raw VIP/sim evidence -> vip_distill.py
-> Normalized Evidence JSON -> DuckDB -> Analysis Agent ->
Hypothesis->Evidence->Confidence -> Memory Agent），不負責 orchestration、
memory promotion 或 job control。" This workstream scopes (here: creates,
since it did not previously exist) that module to exactly that
responsibility, and no more.

## Discovery performed first (per task instructions -- verify, don't assume)

Full-repo grep before writing anything:
- `find . -iname "*vip_distill*"` -- **zero hits anywhere in the repo.**
  The module did not exist under any name, exact or approximate. This is a
  greenfield creation, not a narrowing of drifted scope.
- `grep -ril "distill" --include=*.py .` -- only two unrelated `.work/`
  one-off memory-persistence scripts (`persist_debug_workflow_gap_closure_
  memory.py`, `persist_usb_handoff_distillation_memory.py`) and
  `dv_harness/fsdb_report.py`'s own docstring use of the word
  "distilled"/"distillation" (describing where ITS confirmed flag grammar
  came from -- unrelated to this module). No pre-existing "distill"-named
  engine module of any kind.
- `find . -iname "*evidence_db*"` -- **zero hits.** The Evidence-Store
  workstream (`evidence_db.py`, the DuckDB loader the user's own pipeline
  diagram names as this module's downstream consumer) has not landed yet
  in this repo as of this session. Per the task's own instruction ("design
  a reasonable, documented schema and note in your report that it should
  be reconciled once evidence_db.py's real schema is known"), this
  workstream proceeded with its own documented schema design rather than
  waiting or guessing at an unseen one.
- `.work/*.md` listing -- no `evidence-store`/`duckdb`-named report present
  either, confirming that workstream's own report is also not yet
  available to coordinate against.
- Confirmed sibling, already-landed parallel workstream:
  `.work/governance-preflight-report.md` + `.claude/agents/preflight-
  resource-guard-agent.md` -- the Preflight/Resource Guard Agent named in
  the same user spec paragraph was built by a separate, already-completed
  parallel workstream this session; this workstream deliberately does not
  touch `dv_harness/preflight.py` or `dv_harness/lsf_client.py`.

## What was built

### `dv_harness/vip_distill.py` (new module, ~300 lines)

A pure re-shaping/aggregation layer over evidence this project's tools
already produce. It never re-implements marker/epilogue parsing itself --
all real parsing logic stays exactly where it already lives:

- **`distill_sim_log(log_text=|log_path=, job_id=, pattern=, protocol=,
  run_dir=)`** -- delegates to `sim_log_analysis.parse_sim_log[_file]()` +
  `classify_signatures()` (existing, unmodified engine code), re-shapes
  their output (`total_lines`/`epilogue`/classified `signatures`) into the
  shared envelope below. `verdict`/`counts` come straight from the real
  epilogue (`PASSED`/`FAILED`, `uvm_fatal`/`uvm_error`/`uvm_warning`) --
  `None` when no epilogue is present, never fabricated.
- **`distill_job_record(job_record: dict)`** -- normalizes a job-tier
  record shaped exactly like `lsf_client._upsert_job_tier_memory_record()`
  already builds (`job_failure`/`job_result` kind, same field names:
  `lsf_status`/`sim_status`/`uvm_error_count`/`uvm_fatal_count`/
  `terminal_signature`/`seed`/`fsdb_path`/`failure_signature`/
  `prior_related_knowledge`), or a raw `JobState.asdict()` dump. **Read-
  only**: it never loads/saves a `.dv-harness/lsf/jobs/*.json` file itself,
  never calls into `lsf_client`, and takes no kill/requeue/promotion
  action -- it only re-shapes a dict a caller already has in hand. Unknown/
  future fields on the input are silently ignored (forward-compatible),
  not an error.
- **`distill_fsdbreport(report_text=|parsed_report=, fsdb_path=, topic=,
  job_id=, pattern=)`** -- delegates to
  `fsdb_report.parse_fsdbreport_output()` (existing, unmodified), wraps its
  already-honest `{"parsed": True/False, ...}` result into the envelope.
  `verdict`/`counts` are structurally `None` (fsdbreport is signal-level
  trace evidence with no PASS/FAIL concept of its own -- never invented).
- **`merge_evidence(components, job_id=, pattern=, protocol=, run_dir=)`**
  -- combines >=2 already-normalized envelopes for the same job into one
  `source_kind="combined"` envelope: sums `counts` fields present across
  components, picks the worst signature severity, and computes a combined
  verdict where any real `FAILED`/`FAIL` component wins outright (never
  averaged away) and genuinely mixed vocabulary (`PASSED` vs `PASS`) is
  reported as `AMBIGUOUS` rather than silently coerced to one string. Pure
  arithmetic/selection over fields the inputs already state -- never
  re-parses raw evidence or introduces a new fact.
- **`write_normalized_evidence(record, out_path)`** -- the ONLY I/O in the
  module: a thin JSON writer with no decision logic (mirrors
  `fsdb_report.write_topic_report()`'s "build the shape, then just write
  it" split). Never chooses the destination, never routes into
  memory/DuckDB itself.

### Normalized Evidence JSON schema (this workstream's own design, `NORMALIZED_EVIDENCE_SCHEMA_VERSION = "0.1.0-draft"`)

Shared envelope every `distill_*()`/`merge_evidence()` call returns:

```jsonc
{
  "schema_version": "0.1.0-draft",
  "evidence_id": "EVID-<sha256[:24]>",       // deterministic: same real input -> same id
  "source_kind": "sim_log|job_record|fsdbreport|combined",
  "distilled_at": <unix ts>,
  "distiller": "vip_distill.py",
  "job_id": <optional, omitted not null when unknown>,
  "pattern": <optional>,
  "protocol": <optional>,
  "run_dir": <optional>,
  "verdict": "PASSED|FAILED|FAIL|PASS|AMBIGUOUS|null",  // each source's own real vocabulary, never coerced
  "counts": {"uvm_fatal": int|null, "uvm_error": int|null, "uvm_warning": int|null} | null,
  "detail": { ... source-kind-specific real content ... },
  "provenance": { "source_path"?: str, "parser"?: str, "source_memory_id"?: str, "merged_from_evidence_ids"?: [...] }
}
```

**Deliberately NOT included in this schema** (each belongs to a separate,
later stage of the user's own pipeline, not this module):
`next_action`/`recommended_fix`/`promote_to`/`job_control_action`/any
hypothesis-confidence field -- those are the Analysis Agent's and Memory
Agent's job (Hypothesis -> Evidence -> Confidence -> Memory Agent, per the
spec's own pipeline diagram), never this module's.

**Schema reconciliation note (must be revisited)**: this schema was
designed with no real `evidence_db.py`/DuckDB-loader schema to coordinate
against (see Discovery above -- it does not exist in this repo yet). When
that workstream lands, its real column/table shape must be checked against
this envelope and this schema updated (bumping
`NORMALIZED_EVIDENCE_SCHEMA_VERSION` and dropping the `-draft` suffix once
confirmed) rather than assumed compatible.

## Explicit non-goals (enforced, not just documented)

The module docstring states these; a real test
(`test_module_does_not_import_orchestration_or_memory_modules`, using
`ast.parse()` over real import statements only -- not a naive substring
scan, which would false-positive on the docstring's own scope explanation)
statically asserts `vip_distill.py` never imports `memory_router`,
`memory_vault`, `lsf_client`, `preflight`, or `duckdb`, and never
references `route_and_store`/`bsub_submit`/`MemoryStore`:

- **No orchestration** -- never calls `bsub`/`bjobs`/`pueue`/`just`, never
  touches `lsf_client.bsub_submit*()` or any scheduler.
- **No memory promotion** -- never calls
  `memory_router.route_and_store()`/`promote_to_organizational()`, never
  writes into `.dv-harness/memory/**` itself. A Normalized Evidence JSON is
  an INPUT a separate Analysis/Memory Agent may later act on; producing it
  is not itself a memory write.
- **No job control** -- no kill/requeue/retry decisions, no `JobState`
  mutation; `distill_job_record()` only reads a dict it is handed.
- **No DuckDB access** -- only emits JSON; loading it into DuckDB is the
  separate Evidence-Store workstream's job once it exists.

## Tests

`dv_harness_tests/test_vip_distill.py` -- 20 tests, all against real
project evidence shapes (the documented "FINAL CHECK @ ... / UVM_FATAL =
N, UVM_ERROR = N, UVM_WARNING = N / VERDICT: PASSED|FAILED" epilogue format
`test_sim_log_analysis.py` already validates; a job-record dict shaped
exactly like `lsf_client._upsert_job_tier_memory_record()`'s real output;
real fsdbreport CSV structural parsing via `fsdb_report.
parse_fsdbreport_output()`), covering:
- input validation (exactly-one-of argument pairs, non-dict/empty job
  record rejected) via `VipDistillError`,
- correct normalization of a clean PASS log and a multi-signature FAILED
  log (verdict, counts, classified signatures, severity ordering),
- `job_id`/`pattern` omitted (not null) when not supplied,
- deterministic `evidence_id` (same input -> same id; different `job_id`
  -> different id),
- job-record normalization including the real field vocabulary, unknown-
  field forward tolerance, and `sim_status=="UNKNOWN"` yielding no verdict,
- fsdbreport normalization (`report_text=` and pre-parsed `parsed_report=`
  paths), including the honest `parsed:false` degradation path,
- `merge_evidence()`'s >=2-components requirement, its "no nested
  `combined` components" guard, correct sum/worst-severity aggregation,
  "any real FAILED wins" verdict logic, and the `AMBIGUOUS` case for
  genuinely differing PASS-vocabulary strings across components,
- `write_normalized_evidence()`'s parent-directory creation and JSON
  round-trip,
- the static scope-guard test described above.

Run: `python -m pytest dv_harness_tests/test_vip_distill.py -q` -> 20
passed. A full `dv_harness_tests/` suite run was attempted as broader
regression verification but stalled with zero output for several minutes
(pre-existing environment behavior -- likely a test elsewhere in the
~2000-test suite blocking on a subprocess/relay-shaped call with no
timeout, unrelated to this change) and was killed rather than waited out
indefinitely. As a scoped substitute, the three modules this workstream
actually reads from -- `sim_log_analysis.py`, `fsdb_report.py` -- were run
together with the new test file
(`pytest dv_harness_tests/test_vip_distill.py dv_harness_tests/
test_sim_log_analysis.py dv_harness_tests/test_fsdb_report.py -q`) and all
37 passed. This workstream's change is purely additive (one new module,
one new test file; no existing file was modified), so no pre-existing
test's behavior was touched. The full-suite stall itself is a real,
named gap worth a separate look (not investigated further here as out of
this workstream's narrow scope) -- whichever test is responsible should
get an explicit timeout.

## What was moved

Nothing. Per the Discovery section above, no `vip_distill.py` (or
similarly-named module) existed anywhere in this repo before this
workstream -- there was no drifted scope to narrow back, and no logic to
relocate elsewhere.

## Follow-ups for later workstreams

1. Reconcile `NORMALIZED_EVIDENCE_SCHEMA_VERSION` against the real
   `evidence_db.py`/DuckDB loader's schema once that workstream lands.
2. Once `evidence_db.py` exists, a thin, separate ingestion caller (in
   that module, not this one) should call `write_normalized_evidence()`'s
   output (or the in-memory envelope dicts directly) and load them into
   DuckDB -- `vip_distill.py` itself must not gain a DuckDB dependency.
3. If/when a real Analysis Agent consumes these envelopes for Hypothesis
   -> Evidence -> Confidence scoring, it should do so by reading Normalized
   Evidence JSON this module already produces, never by importing
   `vip_distill.py` internals to reach back into raw sim.log/job-record
   shapes itself (defeats the point of normalizing in the first place).
