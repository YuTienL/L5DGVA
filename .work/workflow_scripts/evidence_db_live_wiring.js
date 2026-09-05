export const meta = {
  name: 'evidence-db-live-wiring',
  description: 'Wire evidence_db.py into a real reconciliation cycle + vip_distill bridge, so DuckDB stops being an empty tested library',
  phases: [
    { title: 'Wire', detail: 'sequential: reconciliation-cycle ingestion, then vip_distill bridge (same file, avoid concurrent-edit collision)' },
    { title: 'Review', detail: 'independent verification that real data actually lands in evidence.duckdb' },
  ],
}

const CONTEXT = `
## Background (read this before touching anything)

The "Production-Grade Execution Governance" workflow (2026-09-03) built
dv_harness/evidence_db.py (a real, tested, DuckDB-backed EvidenceStore
class) and dv_harness/vip_distill.py (a real, tested, pure evidence-
normalization module). Both are individually solid -- but the finish
report and an independent review both confirmed: NO caller anywhere in
this codebase actually invokes EvidenceStore.insert_job_state/
insert_job_memory_record/insert_regression_verdict/insert_coverage_sample/
insert_rtl_parse, and vip_distill.write_normalized_evidence()'s output has
nowhere to land. .dv-harness/evidence/evidence.duckdb does not exist
anywhere in this project -- confirmed by grep, confirmed again just now.
The user's own words: "evidence store...兩個工具真裝好、程式碼真的、但
.duckdb 檔案從沒被任何真實 reconcile cycle 寫入過一筆資料——目前是「測試過
的函式庫」,還不是「活的資料源」" -- fix exactly this.

Real evidence_db.py API (read the file's own header docstring in full
first -- it documents which REAL data shape each table mirrors and why):
- EvidenceStore(db_path) -- context-manager class, db_path from
  evidence_db.default_db_path(root)
- .insert_job_state(state) -- state is a dv_harness.lsf_client.JobState
  instance (or dict via asdict-compatible shape)
- .insert_job_memory_record(record: dict) -- the real kind in
  ("job_result","job_failure") record dict lsf_client._upsert_job_tier_
  memory_record() builds
- .insert_regression_verdict(pattern, verdict_passed, ...) -- mirrors
  uvm_generator.regression_list_manager.record_verdict()/
  apply_verdict_to_file() semantics
- .insert_coverage_sample(category: dict, ...) -- category matches
  coverage_analysis.parse_coverage_summary()'s per-category shape
- .insert_rtl_parse(parse_result: dict) -- parse_result from
  verible_parser.to_dict(verible_parser.parse_file(path))
- .query(sql, params) -- read path

Real regression_reporter.py structure (read the whole file, not just the
excerpt below): run_reconciliation_cycle(root, vcuser, uvm_root_path) is
the one real reconciliation cycle this harness runs (via lsf-watch-start).
It already has a precedent for exactly this kind of "best-effort side
write that must never break the cycle" integration --
_escalate_uvm_fatal_burst_if_needed(root, jobs_for_snapshot), called near
the end of the cycle, wrapped in try/except with a print-and-continue on
any failure, reading its own config block fresh from .dv-harness/
config.json each call rather than being threaded through every function
signature in the module. Follow this exact pattern, do not invent a new
integration style.

Real vip_distill.py structure: distill_sim_log/distill_job_record/
distill_fsdbreport/merge_evidence -> write_normalized_evidence(record,
out_path). NORMALIZED_EVIDENCE_SCHEMA_VERSION = "0.1.0-draft". A static
AST test (test_module_does_not_import_orchestration_or_memory_modules)
enforces vip_distill.py itself never imports lsf_client/memory_router/
memory_vault/preflight/duckdb -- this constraint is NOT to be relaxed;
the bridge/ingestion CALLER lives outside vip_distill.py, in
regression_reporter.py or evidence_db.py itself, never inside
vip_distill.py.
`

phase('Wire')

const step1 = await agent(`${CONTEXT}

## Your task: wire real EvidenceStore writes into regression_reporter.run_reconciliation_cycle()

This is the FIRST of two sequential steps (a second agent will build on your work after you finish -- work only in regression_reporter.py, evidence_db.py, and their tests; do not touch vip_distill.py).

Concrete requirements:
1. Add a new best-effort function in regression_reporter.py, e.g. _write_reconciliation_evidence_if_configured(root, reconciled, jobs_for_snapshot) -- following _escalate_uvm_fatal_burst_if_needed's EXACT pattern (wrapped in try/except, print-and-continue on failure, reads its own tiny config need fresh rather than being threaded through every call site). Call it from run_reconciliation_cycle() at the appropriate point (after reconciled jobs are known, near where the snapshot is rendered).
2. For each reconciled job (state, discrepancies) in the reconciled dict: call EvidenceStore.insert_job_state(state) unconditionally (a job's own state IS the fact being recorded). If state has a determinate PASS/FAIL verdict and a known pattern (mirror the same condition Part 3's regression-list safety-net logic in this same file already uses to decide whether to call apply_verdict_to_file() -- read that call site first and reuse its exact condition, do not invent a different one), also call insert_regression_verdict(pattern, verdict_passed, ...).
3. Add a dv_harness/config.py config block for this (evidence_db: {enabled: true, ...} or similar -- since this only writes to a local DuckDB file with no network/credential exposure, defaulting enabled is reasonable, unlike escalation's opt-in-False default; but document your reasoning in the report and make it toggleable). Read config.py's existing preflight/escalation blocks first to match the exact style (comment convention, empty-vs-populated defaults).
4. Open/close the EvidenceStore correctly per cycle -- read evidence_db.py's own __enter__/__exit__ context-manager support first; do not leave a connection open across cycles or leak one on an exception path.
5. Write a real, end-to-end test: construct a fake/synthetic reconciled job set (following whatever existing test fixture pattern regression_reporter's own test file already uses for run_reconciliation_cycle -- read dv_harness_tests/test_regression_reporter.py or wherever its tests live first), run one reconciliation cycle against a temp project root, then open evidence.duckdb directly and assert real rows exist in jobs/regression_verdicts. This is the test that proves "DuckDB stops being empty" -- it must not mock EvidenceStore itself, only the LSF/live-job discovery layer that's already mocked in this file's existing tests.
6. Confirm a DB write failure (e.g. a locked/corrupt DB file) does not break the reconciliation cycle's own real work (job state persistence, snapshot rendering) -- write a test proving this too.

Write a report to .work/evidence-db-wiring-step1-report.md. Run the new + existing regression_reporter tests yourself and confirm pass before reporting DONE. Report DONE/BLOCKED/NEEDS_CONTEXT with a one-line test summary, and explicitly state the exact insert_job_state/insert_regression_verdict call sites (file:line) so the next agent can build the vip_distill bridge on top without re-deriving them.`, {label: 'wire:reconciliation-ingestion', phase: 'Wire'})

const step2 = await agent(`${CONTEXT}

## Your task: design and wire the vip_distill -> evidence_db normalized-evidence bridge

This is the SECOND of two sequential steps. Step 1 just wired real EvidenceStore.insert_job_state/insert_regression_verdict calls into regression_reporter.run_reconciliation_cycle() -- read its full report below before starting, since your work builds on the same integration point and must not conflict with it or duplicate its writes.

### Step 1's report (read in full):
${step1}

Concrete requirements:
1. vip_distill.write_normalized_evidence()'s output (schema_version "0.1.0-draft", built from distill_sim_log/distill_job_record/distill_fsdbreport/merge_evidence) currently has nowhere to land in evidence_db.py -- no matching table exists. Design and add a normalized_evidence table to evidence_db.py's schema (read the file's own header docstring's "schema design principle" -- every table mirrors a real data shape, never an invented generic one; this record IS a real, already-defined shape from vip_distill.py, so this is in-scope) and add EvidenceStore.insert_normalized_evidence(record: dict) -- an upsert, matching this module's own established idempotency convention (read insert_job_memory_record/_upsert_failure_signature for the exact upsert pattern this file already uses; reuse it, do not invent a different one).
2. Wire a real caller: after step 1's reconciliation-cycle ingestion runs for a job with a sim_log, call vip_distill.distill_sim_log()/distill_job_record() to build the normalized record, then EvidenceStore.insert_normalized_evidence() to store it. Decide precisely where this caller lives -- regression_reporter.py (alongside step 1's new function) is the natural place since it already has the job/sim_log context; do NOT put orchestration/DB-calling code inside vip_distill.py itself (its own AST-enforced test forbids importing duckdb/evidence_db/etc. -- this must not change).
3. This closes the exact gap the governance workflow's own vip_distill report flagged as "documented as pending reconciliation once that workstream lands" -- read .work/governance-vip-distill-report.md and .work/governance-evidence-report.md in full first for the exact open items both sides already disclosed, so your bridge design actually reconciles what both sides expected rather than inventing a third shape.
4. Write a real, end-to-end test: run a reconciliation cycle against a synthetic job with a real-shaped sim_log fixture, confirm a normalized_evidence row lands in evidence.duckdb with the correct schema_version and content, and confirm it does NOT duplicate/conflict with step 1's own job_state/regression_verdict rows for the same job (query all three tables after one cycle, assert consistent job/pattern identifiers across them).
5. Update dv_harness/evidence_db.py's own header docstring to document the new table exactly like the existing ones are documented (source shape, real producer, upsert key).

Write a report to .work/evidence-db-wiring-step2-report.md. Run ALL regression_reporter + evidence_db + vip_distill tests yourself (not just your own new ones) and confirm the full set passes before reporting DONE -- this is the step most likely to have silently broken step 1's tests if the schema/caller design doesn't compose cleanly. Report DONE/BLOCKED/NEEDS_CONTEXT with a one-line test summary.`, {label: 'wire:vip-distill-bridge', phase: 'Wire'})

phase('Review')

const review = await agent(`Independently review this 2-step "wire evidence_db into a real reconciliation cycle" effort for DV Agent Harness L5. Read both reports in full first:

D:\\DV\\Task\\DV_Agent_Harness_L5\\v50\\.work\\evidence-db-wiring-step1-report.md
D:\\DV\\Task\\DV_Agent_Harness_L5\\v50\\.work\\evidence-db-wiring-step2-report.md

Step 1 and step 2's own raw returned text (cross-reference against the report files):

### Step 1
${step1}

### Step 2
${step2}

Verify by running real commands yourself -- never by trusting either report's prose:
1. Run the full project test suite (python -m pytest dv_harness_tests/ -q) and report the real pass/fail count.
2. Actually run a reconciliation cycle yourself against a synthetic/temp project root (following whichever test fixture both steps' own new tests already established) and then open .dv-harness/evidence/evidence.duckdb directly with EvidenceStore/duckdb and query it -- confirm real rows genuinely exist in jobs, regression_verdicts, and normalized_evidence. This is the one claim ("DuckDB is no longer empty") that must be verified by YOU actually seeing rows, not by reading a report that says so.
3. Confirm the DB-write-failure-must-never-break-the-cycle guarantee from step 1 still holds after step 2's changes (re-run or re-read that specific test).
4. Confirm vip_distill.py itself still has zero import of duckdb/evidence_db/lsf_client/memory_router/memory_vault/preflight (re-run its AST-enforcement test, or grep it yourself) -- the bridge caller must live in regression_reporter.py, not inside vip_distill.py.
5. Confirm the new config.py evidence_db block follows the established style (compare directly against the preflight/escalation blocks) and that its default (enabled or not) is deliberate and justified, not accidental.
6. Check for git hygiene issues (uncommitted files, whole-file staging sweeping in unrelated concurrent changes -- verify with git status/git diff --cached before any commit these agents may have made).
7. Confirm evidence_db.py's header docstring was actually updated to document the new normalized_evidence table (read it yourself).

Report a clear verdict (APPROVED / NEEDS_FIX) with concrete, evidence-cited findings.`, {label: 'review', phase: 'Review', model: 'claude-opus-5'})

return { step1, step2, review }
