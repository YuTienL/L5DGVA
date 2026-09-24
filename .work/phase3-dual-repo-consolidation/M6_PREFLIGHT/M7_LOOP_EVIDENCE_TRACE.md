# M7 Loop Evidence Trace

Real, append-only persistence: `dv_harness/result_action_router.py::
append_iteration_trace()`/`read_iteration_traces()`. On-disk record:
`.dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-001/loop_evidence_trace.jsonl`
(6 lines, one per closed finding).

## Provenance note (honesty over completeness)

`result_action_router.py` did not exist while F1-F6 were actually being
found and fixed -- that work ran as direct, manual Prime Directive V2 P5
FIND->FIX->VERIFY (git commit `740fbe6`), not through this module's own
loop. The 6 `IterationTrace` records below were written AFTER the fact,
once the module existed, using the real, already-verified facts from
that work (real root causes, real changed files, real passing test
names, the real commit SHA as `regression_signature`). This is disclosed
as backfilled evidence of real work, not a live trace of an autonomous
loop that does not exist in production yet -- see
`M7_AUTONOMOUS_REMEDIATION_EVIDENCE.md` for the full honest accounting.

## Recorded iterations

| # | finding_id | gap_id | files_changed | tests_run | regression_signature | final_disposition |
|---|---|---|---|---|---|---|
| 1 | F1 | GAP-V2-009 | model_result.py | test_unsupported_result_version_is_not_schema_validated | 740fbe6 | CLOSED |
| 2 | F2 | GAP-V2-009 | model_result.py | 4 tests (fabricated-evidence + 3 returned-artifacts-scope tests) | 740fbe6 | CLOSED |
| 3 | F3 | GAP-V2-010 | model_handoff.py | test_handoff_task_id_scope_mismatch_is_a_real_parse_error | 740fbe6 | CLOSED |
| 4 | F4 | GAP-V2-011 | model_handoff_workflow.py | test_malformed_stored_handoff_is_rejected_not_a_crash | 740fbe6 | CLOSED |
| 5 | F5 | GAP-V2-011 | model_handoff_workflow.py | 2 tests (duplicate-import no-op + registry-write-failure ordering) | 740fbe6 | CLOSED |
| 6 | F6 | GAP-V2-012 | model_handoff.py, model_result.py | 2 tests (embedded-newline + embedded-heading-injection) | 740fbe6 | CLOSED |

Every row's `re_review_task_id=M7-V1-CODEX-REVIEW-002` (the real
generated re-review handoff, `WAITING_FOR_HUMAN_TRANSPORT`; see
`M7_CODEX_RE_REVIEW_HANDOFF_EVIDENCE.md`).

## Status

`LOOP_EVIDENCE_TRACE_MECHANISM_STATUS=WIRED_AND_TESTED_AND_EXERCISED_ONCE`
(the 6 rows above are a real exercise of the mechanism, not merely unit
tests against synthetic `tmp_path` data). `AUTOMATIC_PER_ITERATION_
RECORDING=NOT_YET_WIRED` -- no production call site invokes
`append_iteration_trace()` automatically during a real remediation; this
task's own 6 rows were written by an explicit, one-time script.
