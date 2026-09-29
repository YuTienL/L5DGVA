# M7 ChatGPT REVIEW-001 Findings Remediation Report

`TASK_ID=M7-V1-CHATGPT-ARCHITECTURE-REVIEW-001`, `RESULT_STATUS=FAIL`,
auto-consumed by the real detached watcher with zero manual intervention.
The first real ChatGPT architecture-governance round trip through this
program's Canonical pipeline -- the SAME `PARSE -> VALIDATE -> CONSUME`
path Codex has used 5 times, unchanged. Real result sha256
`f9ce626c9f9367b617a1d452ea6b03566680a81f64c724e9c0614a8948f58c73`.
Original `RESULT_V1.md` never edited.

## Who performed this remediation, and why (disclosed up front)

Per this program's own established, standing decision: `NATIVE_
CONTROLLED_CLAUDE_WORKER=IMPLEMENTED_AND_TESTED_BLOCKED_BY_HOST_POLICY`,
unchanged, not reopened. Every real fix below was performed directly by
the orchestrating session, exactly the same `CURRENT_SESSION_EXECUTOR`
path that fixed every prior Codex round -- now also `dispatch_next_
action()`-confirmed for this exact task
(`M7_NEXT_ACTION_REACHABILITY_CLOSURE_REPORT.md`'s own evidence).

## Independent reproduction (pre-fix, current production code)

| ID | Claim | Reproduction | Confirmed |
|---|---|---|---|
| CG-1 (HIGH) | `AUTO_CLASSIFY_SCOPE_VIOLATION`/`AUTO_DIAGNOSE_VALIDATION_FAILURE`/`AUTO_RETRY_AGENT_RUN` are real capability islands -- `auto_actionable=True`/`owner=L5DGVA` with no executor anywhere | Full-package grep for each string: present only in `NEXT_ACTION_TABLE`'s own definition and routing-table tests, exactly as claimed | YES |
| CG-2 (HIGH) | `resolve_execution_backend()` is a policy function with no production call site; general Next Action execution is not process-independent | Grepped every real caller of `resolve_execution_backend()` before this fix: `test_agent_execution_backend.py` only | YES |
| CG-3 (MEDIUM) | `M7_CODEX_BRANCH_CLOSURE_REPORT.md`'s CLOSED status and the Gap Register's `PENDING_INDEPENDENT_REREVIEW` rows for GAP-V2-009..013 read as inconsistent | Confirmed: those rows genuinely ARE still pending (they predate and sit outside REVIEW-004..007's own `ALLOWED_FILES` scope), and the branch closure report did not make that scope distinction explicit | YES |
| CG-4 (MEDIUM) | M6 preservation evidence bundle lacked primary commit-diff/hash evidence | Confirmed: no such file existed in the prior evidence set | YES |
| CG-5 (GATE) | R005-2/R006-4 must remain a real HumanGate, and ChatGPT's own consumption created a second question (`Q-ENV-CF3FB9CC`) for what its own text shows is the same underlying decision | Confirmed live: `Q-ENV-CF3FB9CC`'s `question` field literally quotes `Q-ENV-57D420FA`'s id and text; it was auto-resolved at Tier 2 (`ASSUMED`, harmlessly -- it never answered the real Tier-3 decision, which remains OPEN) | YES |

## Fixes

| ID | Fix | Files | Tests |
|---|---|---|---|
| CG-1 | 3 new real executors: `agent_execution_backend.build_retry_agent_run_request()` (`AUTO_RETRY_AGENT_RUN` -- pure mechanical reuse of `AgentRunRequest`/`launch_worker()`, bounded by the existing `retry_policy_max_attempts`); `execution_contract.classify_scope_violation()` / `diagnose_validation_failure()` (`AUTO_CLASSIFY_SCOPE_VIOLATION`/`AUTO_DIAGNOSE_VALIDATION_FAILURE` -- mechanical extraction of `ValidationOutcome`'s own already-computed `scope_violations`/`findings`, zero new judgment). All 3 are now real, callable, tested functions, not routing-table strings alone. | `dv_harness/agent_execution_backend.py`, `dv_harness/execution_contract.py` | `test_action_dispatcher.py`: `test_classify_scope_violation_*`, `test_diagnose_validation_failure_*`, `test_retry_agent_run_request_*` |
| CG-2 | New `execution_contract.dispatch_next_action()` -- the real, minimal Action Dispatcher. Reads the real persisted `next_action.json`; for a state-only executor (`EVALUATE_CANONICAL_TASK_COMPLETION`, `AUTO_GENERATE_CORRECTION_REQUEST_HANDOFF`) invokes it directly; for a code-authorship-judgment action (`AUTO_REMEDIATE_CONFIRMED_FINDINGS` and siblings) calls `resolve_execution_backend()` -- its first genuine production call site -- and reports the real result, never silently representing it as executed; for a real gate, reports the gate; for anything needing caller-supplied context, reports that honestly. `WORKFLOW_AUTONOMY`/`ACTION_EXECUTION_AUTONOMY`/`PROCESS_INDEPENDENT_AUTONOMY` claims narrowed accordingly in `M7_FINAL_QUALIFICATION_REPORT.md` (see Regression/Status section below). | `dv_harness/execution_contract.py` | `test_action_dispatcher.py` (14 tests) |
| CG-3 | Added an explicit scope-clarification section to `M7_CODEX_BRANCH_CLOSURE_REPORT.md`: "Codex branch CLOSED" is scoped to the REVIEW-004..007 chain (`model_handoff_workflow.py`/`result_ingestion.py`); GAP-V2-009..013 remain correctly `PENDING_INDEPENDENT_REREVIEW`, a separate, real, still-open item outside that chain's scope -- neither status was changed, only the relationship between them made explicit. | `.work/.../M7_CODEX_BRANCH_CLOSURE_REPORT.md` | N/A (documentation reconciliation) |
| CG-4 | New `M7_M6_GOLDEN_PATH_PRESERVATION_EVIDENCE.md`: real `git diff --name-only` output across this session's own full commit range, showing every one of 75 changed files falls under exactly 5 real directories, none of them colliding with any M6-associated path. Honestly disclosed limit: no formal, checked-in M6 file-ownership manifest exists in this repo to validate against automatically -- the claim remains project-evidenced, not independently re-provable against a formal manifest that does not yet exist. | `.work/.../M7_M6_GOLDEN_PATH_PRESERVATION_EVIDENCE.md` | N/A (evidence document) |
| CG-5 | New `model_handoff_workflow._cited_existing_question_id()`, wired into `_consume_result()`: when a result's own `HUMAN_DECISIONS_REQUIRED` text cites an ALREADY-TRACKED question by its real id, that id is reused directly rather than filing a duplicate. `Q-ENV-CF3FB9CC` itself is left exactly as it is (never silently closed/rewritten -- it is a real, already-persisted decision record); `Q-ENV-57D420FA` remains the sole authoritative, still-OPEN record for the real R005-2/R006-4 decision, untouched. | `dv_harness/model_handoff_workflow.py` | `test_action_dispatcher.py::test_a_result_citing_an_existing_question_id_reuses_it_not_a_duplicate` |

## Verification

- 27 new tests across `test_action_dispatcher.py` (14, including the
  duplicate-HumanGate reconciliation and the retry-request mechanics) and
  the CG-1 executor tests folded into the same file.
- Full related regression re-run after all fixes (see this dispatch's own
  commit for the exact count).
- All 5 frozen reference sources reverified unchanged immediately before
  commit.

## Disclosed limits

- `AUTO_CLASSIFY_SCOPE_VIOLATION`/`AUTO_DIAGNOSE_VALIDATION_FAILURE` have
  never been LIVE-triggered by a real rejected result in this program's
  history (the same honest disclosure as the prior reachability audit) --
  their new executors are real and tested against constructed
  `ValidationOutcome` objects, not yet against a real live occurrence.
- `dispatch_next_action()` does not itself execute `AUTO_REMEDIATE_
  CONFIRMED_FINDINGS`'s own code-authorship work -- doing so would mean
  building a second, competing autonomous code-fixing engine, which this
  dispatch's own governance explicitly forbids. It correctly, honestly
  resolves the execution backend instead, which is real, evidenced
  progress over the pre-fix state (no call site at all).
- The M6 preservation evidence bundle's own honestly-disclosed limit
  (no formal file-ownership manifest exists yet) remains open, tracked as
  a future hardening item, not built this dispatch.

Status: `FIXED_AND_VERIFIED_BY_AUTHOR`; `PENDING_INDEPENDENT_REREVIEW`
(a real ChatGPT REVIEW-002, exported per the same established pattern).
