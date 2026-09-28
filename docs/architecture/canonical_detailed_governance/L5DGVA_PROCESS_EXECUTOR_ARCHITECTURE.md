# L5DGVA Process Executor Architecture

Per `L5DGVA_CONTROLLED_PROCESS_EXECUTION_AND_MODEL_WORKER_GOVERNANCE_
REQUIREMENTS.md`. The required pipeline:

``` text
Canonical Result -> Validate/Consume -> Next Action Resolver
-> Action Dispatcher -> Execution Backend Router
-> L5DGVA Controlled Process Executor -> bounded authorized execution
-> Structured Result/Evidence -> Canonical Ingestion -> Next Action Resolver
```

## Mapped onto real, existing code (no second orchestration engine)

| Pipeline stage | Real module/function | Status |
|---|---|---|
| Canonical Result -> Validate/Consume | `model_handoff_workflow.import_result()` / `result_ingestion.ingest_result_file()` | pre-existing, live-qualified (4+ real round trips) |
| Next Action Resolver | `execution_contract.resolve_next_action()` / `NEXT_ACTION_TABLE` | pre-existing |
| Action Dispatcher | the orchestrating Claude Code session itself, reading `next_action.json` and calling the matched real executor -- see `M7_NEXT_ACTION_REACHABILITY_CLOSURE_REPORT.md`'s reachability audit for which actions have one | real, evidenced, NOT a headless background process (disclosed, not overclaimed) |
| Execution Backend Router | `agent_execution_backend.resolve_execution_backend()` | pre-existing (built for the M7 convergence pass) |
| L5DGVA Controlled Process Executor | `agent_execution_backend.launch_worker()` (Claude-worker case, host-blocked); the orchestrating session itself (`CURRENT_SESSION_EXECUTOR` case, the real, live production path today) | pre-existing |
| Repository Identity Gate (new) | `controlled_process_executor.require_canonical_repository_identity()` | new this dispatch -- see below |
| Semantic Execution Profiles (new) | `controlled_process_executor.semantic_profile_tool_execution_profile()`, `safe_test_temp_cleanup()` | new this dispatch |
| Structured Result/Evidence | `agent_execution_backend.AgentRunResult` / `read_audit_trace()` | pre-existing |
| Canonical Ingestion (of a worker's own result) | `agent_execution_backend.monitor_and_ingest()` | pre-existing |
| Next Action Resolver (closing the loop) | `execution_contract.evaluate_canonical_task_completion()` + `record_completion_evaluation_next_action()` | new this session (M7 convergence + this dispatch's own loop-closing fix) |

## What is genuinely new this dispatch

1. **Repository Identity Gate** (`controlled_process_executor.
   verify_canonical_repository_identity()`/
   `require_canonical_repository_identity()`): fails closed unless a
   launch target genuinely IS the Canonical repository -- never a
   relative `.dv-harness` path match, which this program's own real
   Codex-review scratch artifacts (nested throwaway git repos under
   `.dv-harness/model_handoffs/*/.probe_tmp/*/work/` and `.pytest_tmp/*/
   work/`, both real, observed, still on disk) would satisfy just as well
   as the real root. Live-verified: the real Canonical root matches
   itself; a real nested probe repo under this exact program's own
   scratch tree does NOT match.

2. **Semantic Execution Profiles** (`controlled_process_executor.
   semantic_profile_tool_execution_profile()`): maps every profile NAME
   the governance doc lists onto the REAL, existing
   `safe_tool_profile.ToolExecutionProfile` primitive -- never a second
   tool-scoping mechanism.

3. **`SAFE_TEST_TEMP_CLEANUP`** (`controlled_process_executor.
   safe_test_temp_cleanup()`): a bounded, pre-authorized cleanup for
   exactly the registered-to-task scratch directories this program's own
   real Codex reviews produce. `dry_run=True` by default; this module
   never invokes the real deletion on the specific directories this
   session already had an "Irreversible Local Destruction" classifier
   denial for -- see the function's own docstring for the full reasoning.

4. **`execution_contract.record_completion_evaluation_next_action()`**: a
   real, found-live loop-closing gap -- `evaluate_canonical_task_
   completion()`'s own output was persisted, but the SOURCE task's own
   `next_action.json` was never updated to reflect that its action had
   been executed, leaving it indistinguishable from "not yet executed" to
   a later reader. Fixed and applied live to `M7-V1-CODEX-REVIEW-007`'s
   own record this dispatch.

## What remains deliberately NOT built (disclosed, not silently dropped)

A literal, headless "Action Dispatcher" process that polls
`next_action.json` files and auto-invokes matching Python callables was
NOT built. The REAL, evidenced dispatch mechanism today is the
orchestrating Claude Code session itself, reading persisted state and
calling the real executor directly -- proven across every real action this
program has executed. Building a separate, always-running dispatcher
process would be a genuinely new architecture decision (a background
service, its own lifecycle, its own failure modes) that neither this
dispatch's own governance doc ("do not create a second orchestration
engine") nor its integration prompt ("do not build unsupported provider
automation merely for elegance") calls for, given the current, real,
human-supervised-session model already satisfies `HUMAN_IS_WORKFLOW_
SCHEDULER=NO` (the human never schedules a step; the session acts on
persisted state without being asked).
