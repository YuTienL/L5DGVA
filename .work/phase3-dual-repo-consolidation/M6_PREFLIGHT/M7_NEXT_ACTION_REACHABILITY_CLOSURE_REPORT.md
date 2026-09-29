# M7 Next-Action Reachability Closure Report

Continues (does not replace) the prior turn's own
`M7_NEXT_ACTION_REACHABILITY_AUDIT.md`, reconciled into
`L5DGVA_CONTROLLED_PROCESS_EXECUTION_AND_MODEL_WORKER_GOVERNANCE_
REQUIREMENTS.md`'s own exact classification vocabulary in
`docs/architecture/canonical_detailed_governance/
L5DGVA_NEXT_ACTION_REACHABILITY_MATRIX.csv`.

## Independently re-verified, not blindly trusted

```
TASK_ID = M7-V1-CODEX-REVIEW-007
STATE = RESULT_CONSUMED           (real, re-read from state.json)
RESULT_STATUS = PASS              (real, re-read)
ACCEPTED_RESULT_SHA256 = e14c2ef27fdeb4d800b5f96c9be543f508189c8af859a162914ead3c1d2a1b28  (matches exactly)
```

`next_action.json` at the start of this dispatch STILL showed
`EVALUATE_CANONICAL_TASK_COMPLETION`/`auto_actionable=true` -- confirming
the dispatch's own premise: "no downstream completion-evaluation/branch-
closure/next-gate artifact was observed after this persisted action" was
partially accurate. `canonical_completion_evaluation.json` (the real
evaluation) DID already exist, persisted by the prior turn's own fix --
but `next_action.json` had never been updated to reflect that the action
was executed. This is the real gap this closure report exists to record
and fix.

## Reproduce: exact classified cause

```
RESULT_CONSUMED_CLEAN -> EVALUATE_CANONICAL_TASK_COMPLETION
```

Classified: `OUTPUT_UNCONSUMED` (a narrower, more precise classification
than a bare `RESOLVED_BUT_NOT_EXECUTED` for the specific state found this
dispatch) -- the action WAS executed (a real `canonical_completion_
evaluation.json` existed, produced by the prior turn) and its
recommendation WAS acted on (the real ChatGPT handoff was already
exported) -- but the execution's own outcome was never written back to
the SOURCE task's own `next_action.json`, so a reader of that one file
alone could not tell the difference between "never executed" and
"executed, but not recorded." Fixed this dispatch:
`execution_contract.record_completion_evaluation_next_action()`.

## Full reachability audit -- UPDATED, ChatGPT REVIEW-001 (CG-1/CG-2) gap-close

ChatGPT's own real architecture-governance round trip
(`M7-V1-CHATGPT-ARCHITECTURE-REVIEW-001`) independently re-derived this
audit and found it self-inconsistent: `AUTO_ACTIONABLE_UNREACHABLE=0` was
claimed while 3 `FOUNDATION_ONLY` actions genuinely had no executor
(CG-1), and `WORKFLOW_AUTONOMY=OPERATIONAL` overclaimed a route as
reachable merely because the interactive session could manually execute
it, while `resolve_execution_backend()` had no real production caller at
all (CG-2). Both findings independently re-verified and fixed -- see
`M7_CHATGPT_REVIEW_001_FINDINGS_REMEDIATION_REPORT.md`. Real new
executors: `execution_contract.classify_scope_violation()`/`diagnose_
validation_failure()`, `agent_execution_backend.build_retry_agent_run_
request()`, and a real, minimal `execution_contract.dispatch_next_
action()` Action Dispatcher giving `resolve_execution_backend()` its
first genuine production call site.

See `docs/architecture/canonical_detailed_governance/
L5DGVA_NEXT_ACTION_REACHABILITY_MATRIX.csv` (13 rows, the governance
doc's own exact vocabulary). Summary, corrected:

```
AUTO_ACTIONABLE_ACTIONS   = 9  (9 WIRED + 0 FOUNDATION_ONLY)
AUTO_ACTIONABLE_WIRED     = 9
AUTO_ACTIONABLE_GATES     = 3  (2 HUMAN_AUTHORITY_GATE + 1 HUMAN_TRANSPORT_GATE)
AUTO_ACTIONABLE_UNREACHABLE = 0   (RESOLVED_BUT_NOT_EXECUTED + OUTPUT_UNCONSUMED +
                                   FOUNDATION_ONLY, all now 0 after this update)
FOUNDATION_ONLY (disclosed, deferred, never live-triggered) = 0
```

No `RESOLVED_BUT_NOT_EXECUTED`, `OUTPUT_UNCONSUMED`, `FOUNDATION_ONLY`, or
`UNKNOWN` action remains. The 3 actions previously `FOUNDATION_ONLY`
(`AUTO_CLASSIFY_SCOPE_VIOLATION`, `AUTO_DIAGNOSE_VALIDATION_FAILURE`,
`AUTO_RETRY_AGENT_RUN`) each now have a real, callable, tested executor
that performs genuinely mechanical work (extraction of already-computed
`ValidationOutcome` fields, or bounded reuse of the existing
`AgentRunRequest`/`launch_worker()` primitives) -- never invented
domain-design judgment. None has ever misfired or been live-triggered by
a real result in this program's history; that remains honestly disclosed.

## Fixed this dispatch (this turn)

1. `execution_contract.classify_scope_violation()` / `diagnose_
   validation_failure()`, `agent_execution_backend.build_retry_agent_
   run_request()`: real executors for the 3 previously `FOUNDATION_ONLY`
   actions (ChatGPT REVIEW-001 CG-1).
2. `execution_contract.dispatch_next_action()`: the real, minimal Action
   Dispatcher, giving `resolve_execution_backend()` its first genuine
   production call site (ChatGPT REVIEW-001 CG-2). Live-verified against
   both `M7-V1-CODEX-REVIEW-007` and `M7-V1-CHATGPT-ARCHITECTURE-
   REVIEW-001`.
3. `model_handoff_workflow._cited_existing_question_id()`: prevents a
   duplicate HumanGate question for an already-tracked decision (ChatGPT
   REVIEW-001 CG-5).

## Fixed the prior turn (unchanged, carried forward)

1. `controlled_process_executor.py` (new module): Repository Identity
   Gate, Semantic Execution Profiles, `SAFE_TEST_TEMP_CLEANUP`.
2. `execution_contract.record_completion_evaluation_next_action()`: closes
   the real `OUTPUT_UNCONSUMED` gap found above, applied live to
   `M7-V1-CODEX-REVIEW-007`'s own record.

## Replay result

See `M7_COMPLETION_EVALUATION_EVIDENCE.md` for the full real replay.
Summary: `TASK_COMPLETE`, `BRANCH_READY_FOR_CLOSURE`, 1 outstanding
non-blocking Human Authority item (Q-ENV-57D420FA, R005-2/R006-4,
unchanged), `M7_NOT_COMPLETE:CHATGPT_ROUND_TRIP_NOT_CONSUMED`, next
approved gate `GENERATE_CHATGPT_ARCHITECTURE_GOVERNANCE_HANDOFF` --
already real and exported (`M7-V1-CHATGPT-ARCHITECTURE-REVIEW-001`,
`WAITING_FOR_HUMAN_TRANSPORT`), confirmed idempotent and unchanged by this
dispatch's fresh re-evaluation.

## UPDATED -- the real common root cause behind BOTH live ChatGPT
## counterexamples, and the corrected reachability numbers (REVIEW-002)

The "9/9 WIRED" claim above was itself falsified by a SECOND independent
live ChatGPT round trip (`M7-V1-CHATGPT-ARCHITECTURE-REVIEW-002`).
Independently reproduced, not trusted: `grep -rn "dispatch_next_action"
dv_harness | grep -v __pycache__ | grep -v dv_harness_tests` returned ONLY
the function's own definition line -- `dispatch_next_action()` had ZERO
real production callers. It was resolvable and testable, but nothing in
production code ever actually invoked it; a real, persisted
`auto_actionable=true`/`next_action_owner=L5DGVA` action
(`AUTO_GENERATE_CORRECTION_REQUEST_HANDOFF` for REVIEW-002,
`AUTO_REMEDIATE_CONFIRMED_FINDINGS` for REVIEW-001) stayed
`RESOLVED_BUT_NOT_EXECUTED` until a human/interactive session manually
called it. The prior turn's own Action Dispatcher fix connected the
DISPATCHER to the BACKEND ROUTER (`resolve_execution_backend()`'s first
production call site) but never connected the RESOLVER'S OWN OUTPUT
(`next_action.json`) to the DISPATCHER in the real automatic flow -- a
deeper, distinct gap from the one fixed then.

**Fix**: `result_ingestion.resume_after_import()` -- the real,
pre-existing, always-called auto-resume function (invoked after every real
import, `AUTO` watcher and `MANUAL` trigger alike) -- is now `dispatch_
next_action()`'s first genuine production caller. Any `auto_actionable`
L5DGVA-owned action is dispatched automatically the moment a result is
auto-resumed; a dispatch failure is caught and emits `ACTION_DISPATCH_
FAILED` rather than crashing auto-resume itself; state is re-read AFTER
dispatch (never the pre-dispatch snapshot), since a state-only executor may
have already moved the task on.

**A second, real defect found live while qualifying the fix**: `next_
action.json` for the source task was left stale after a successful
dispatch (state.json correctly advanced, but the persisted next-action
record still showed the pre-dispatch pending action forever -- the exact
"OUTPUT_UNCONSUMED" class of gap this report already closed once for
`EVALUATE_CANONICAL_TASK_COMPLETION`). Fixed the same way: `dispatch_next_
action()`'s `AUTO_GENERATE_CORRECTION_REQUEST_HANDOFF` branch now persists
a terminal `NextActionRecord` (`EXECUTED:WAITING_FOR_HUMAN_TRANSPORT`,
`next_action_owner=HUMAN`, `stop_reason=HUMAN_TRANSPORT_REQUIRED`) after a
real successful export, mirroring `record_completion_evaluation_next_
action()`'s own pattern.

**A third, real defect found live while inspecting the regenerated
correction handoff's own content** (never assumed correct merely because
the state transition succeeded): `model_handoff_workflow.build_correction_
request_handoff()` only ever looked for a `value`/`at` pair in `exc.
detail` -- the shape `MALFORMED_ESCAPE` happens to raise. REVIEW-002's real
rejection was `MALFORMED_LIST_ITEM`, which raises `{"line": ...}`, not
`{"value", "at"}` -- so the generated correction request cited NO
offending content at all, and a hardcoded `known_facts` string literally
claimed "after a real MALFORMED_ESCAPE quarantine" regardless of the real
reason. Fixed generically (provider/reason-agnostic, not a REVIEW-002
special case): every key genuinely present in `exc.detail` is now cited,
with established human-readable names for known keys (`value`->
`OFFENDING_VALUE`, `at`->`POSITION_IN_VALUE`, `line`->`OFFENDING_LINE`,
`missing`->`MISSING_FIELDS`) and a generic `DETAIL_<KEY>=` fallback for any
other key; `known_facts` now cites the real `reason` variable. Live-
requalified against the SAME real, untouched, still-quarantined
`RESULT_V1.md` (state.json/next_action.json reverted via the real
`_load_state`/`_save_state`/`resolve_next_action`/`persist_next_action`
primitives to re-derive from the same real evidence -- never a fabricated
or hand-edited correction) with the TRUE original (pre-any-correction,
git-`HEAD`-committed) `HANDOFF_V1.md` restored as the base object, so the
final regenerated correction is a single clean layer, not a correction-of-
a-correction. Final `HANDOFF_V1.md` confirmed: exactly one `CORRECTION
REQUIRED` occurrence, `REJECTION_REASON=MALFORMED_LIST_ITEM`,
`OFFENDING_LINE='branch closure report now explicitly scopes CLOSED to the
REVIEW-004'`, one correct `KNOWN_FACTS` bullet (no stale `MALFORMED_
ESCAPE` duplicate).

**Corrected Next Action Reachability Matrix** (`L5DGVA_NEXT_ACTION_
REACHABILITY_MATRIX.csv`), under the stricter definition the user's own
dispatch required -- Resolver + Callable Executor + real Production Caller
+ Output Consumer ALL real; current-session/test-only invocation does NOT
qualify; `BACKEND_RESOLVED != EXECUTED` preserved, never conflated:

```
WIRED (genuinely full end-to-end, real production caller confirmed live) = 2
  EVALUATE_CANONICAL_TASK_COMPLETION
  AUTO_GENERATE_CORRECTION_REQUEST_HANDOFF

WIRED_BACKEND_RESOLUTION_ONLY (dispatch mechanism production-wired via
resume_after_import(); the code-authorship/test-running WORK itself still
requires the current-session executor -- a real, disclosed boundary) = 4
  AUTO_REMEDIATE_CONFIRMED_FINDINGS
  RUN_FOCUSED_VALIDATION
  RUN_REQUIRED_REGRESSION
  PREPARE_REQUIRED_RE_REVIEW

REQUIRES_CALLER_CONTEXT (corrected DOWN from the prior "9/9 WIRED" claim --
dispatch_next_action() cannot derive the real ValidationOutcome/
AgentRunRequest these need from root+task_id alone; never fabricated to
force a WIRED classification) = 3
  AUTO_CLASSIFY_SCOPE_VIOLATION
  AUTO_DIAGNOSE_VALIDATION_FAILURE
  AUTO_RETRY_AGENT_RUN

GATES (never auto-executed, confirmed by test) = 3
  RESULT_CONSUMED_HUMAN_DECISION -> HUMAN_AUTHORITY_REQUIRED
  RE_REVIEW_HANDOFF_READY -> HUMAN_TRANSPORT_REQUIRED
  AGENT_RUN_FAILED_ESCALATE / AGENT_RUN_HUMAN_DECISION_REQUIRED /
    AGENT_RUN_TIMEOUT_ESCALATE -> HUMAN_AUTHORITY_REQUIRED

AUTO_RETRY_INTERRUPTED_IMPORT: unchanged, WIRED via a distinct mechanism
(import_result()'s own documented idempotent replay), never routed through
dispatch_next_action() at all -- not part of this correction.
```

The prior "`AUTO_ACTIONABLE_WIRED = 9`" summary is retracted as overclaimed
against the corrected definition: 3 of those 9 never had a real production
path to the context they need and are honestly `REQUIRES_CALLER_CONTEXT`;
4 more are WIRED only at the dispatch/backend-resolution layer, with the
actual work still current-session-executor -- a real boundary, not a
capability gap, but not the same claim as "9/9 fully autonomous."

**Anti-drift tests** (`dv_harness_tests/test_auto_resume_dispatch.py`, 12
tests, all passing): auto-resume dispatches an auto-actionable L5DGVA-owned
action via the real `resume_after_import()` path (never a manual dispatch
call standing in for it); a persisted Next Action cannot remain pending
forever after a real auto-resume; `AUTO_GENERATE_CORRECTION_REQUEST_
HANDOFF` and `AUTO_REMEDIATE_CONFIRMED_FINDINGS` both reach dispatch through
the real production caller; a static AST check locks in that `dispatch_
next_action()` has a real non-test caller in `result_ingestion.py` (the
exact class of check that exposed the original gap); the 3 context-required
actions are never falsely classified WIRED; `BACKEND_RESOLVED` is never
reported as `EXECUTED`; a duplicate resume event does not double-dispatch
(the loop-closing fix's own `auto_actionable=False` naturally prevents it;
a direct dispatcher-level race is separately covered); Human Authority/
Transport gate actions are never even attempted for dispatch.

**Live qualification** (dispatch section 5's own required stimulus -- the
REAL persisted REVIEW-002 state, never a manually edited/replaced
`RESULT_V1.md`): `resume_after_import(root, "M7-V1-CHATGPT-ARCHITECTURE-
REVIEW-002")` invoked directly against the real, untouched quarantine.
Required transition achieved exactly as specified: `RESULT_REJECTED_
MALFORMED -> AUTO_GENERATE_CORRECTION_REQUEST_HANDOFF -> correction handoff
generated -> WAITING_FOR_HUMAN_TRANSPORT`, zero manual `dispatch_next_
action()` call, zero human/interactive-session involvement. Re-verified a
second time after the `next_action.json`/correction-content fixes, using
the real `_load_state`/`_save_state`/`resolve_next_action`/`persist_next_
action` primitives (never hand-authored JSON) to re-derive from the SAME
real, untouched `RESULT_V1.md` quarantine and the TRUE original committed
`HANDOFF_V1.md` as base -- confirming the final artifact on disk is both
functionally correct (state transition) and CONTENT-correct (right
rejection reason, offending line cited, no stale duplicate fact).

Preserved throughout, unchanged: `L5DGVA_OWNS_PROCESS_AUTHORITY=YES` /
`MODEL_OWNS_PROCESS_AUTHORITY=NO`; `NATIVE_CONTROLLED_CLAUDE_WORKER=
IMPLEMENTED_AND_TESTED_BLOCKED_BY_HOST_POLICY` (not reopened);
`M6_GOLDEN_PATH_PRESERVED=YES` (no M6-owned file touched); `Q-ENV-
57D420FA` (R005-2/R006-4) remains genuinely OPEN and untouched; M8 not
started; Reference USB not consumed; provider-independent throughout (the
fix lives in `result_ingestion.py`/`model_handoff_workflow.py`'s own
generic, reason-keyed logic, never a REVIEW-002-specific branch).
