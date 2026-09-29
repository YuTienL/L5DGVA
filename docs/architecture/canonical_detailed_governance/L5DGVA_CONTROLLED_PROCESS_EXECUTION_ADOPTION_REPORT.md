# L5DGVA Controlled Process Execution Adoption Report

Adopts `L5DGVA_CONTROLLED_PROCESS_EXECUTION_AND_MODEL_WORKER_GOVERNANCE_
REQUIREMENTS.md` against the real, current repository state.

## Prime Invariants -- evaluated against real evidence

```
L5DGVA_OWNS_PROCESS_AUTHORITY = YES   (see L5DGVA_PROCESS_EXECUTION_AUDIT_EVIDENCE.md)
MODEL_OWNS_PROCESS_AUTHORITY = NO     (Codex/ChatGPT return parsed, validated
                                       RESULT_V1 text only; never direct mutation)
HUMAN_IS_WORKFLOW_SCHEDULER = NO      (M7_HUMAN_NON_SCHEDULER_QUALIFICATION.md,
                                       unchanged; this dispatch added 0 new
                                       scheduler interventions)
HUMAN_IS_AUTHORITY = YES
HUMAN_TRANSPORT_ALLOWED = YES
INTERACTIVE_TERMINAL_INJECTION = FORBIDDEN   (unchanged, unviolated)
ARBITRARY_SHELL_AUTHORIZATION = FORBIDDEN    (no blanket PowerShell grant added --
                                              SAFE_TEST_TEMP_CLEANUP is a bounded
                                              Python function, never a shell grant)
SELF_PERMISSION_ESCALATION = FORBIDDEN       (host-permission investigation not
                                              reopened; no settings self-modification)
CONNECT_BEFORE_EXPAND = YES
OPERATIONAL_BEFORE_CLAIMED = YES
CLOSE_THE_LOOP = YES         (found and fixed a real, live loop-closing gap
                              this dispatch -- see M7_NEXT_ACTION_REACHABILITY_
                              CLOSURE_REPORT.md)
```

## Capability Family -- real status

| Capability | Status |
|---|---|
| `L5DGVA_CONTROLLED_PROCESS_EXECUTION` | Adopted this dispatch -- `controlled_process_executor.py` (new, thin composition layer) |
| `PROCESS_EXECUTOR_ROUTER` | Reused: `agent_execution_backend.resolve_execution_backend()` |
| `POWERSHELL_EXECUTOR` | Reused: `safe_tool_profile.py`'s `ToolExecutionProfile`, extended with named semantic profiles (`controlled_process_executor.SEMANTIC_PROFILE_NAMES`) |
| `CLAUDE_EXECUTOR` | Reused: `agent_execution_backend.launch_worker()` (host-blocked; `CURRENT_SESSION_EXECUTOR` is the real live path) |
| `CODEX_EXECUTOR` / `NATIVE_COMMAND_EXECUTOR` | Not built -- human-mediated Codex/ChatGPT transport retained per this dispatch's own explicit scope (section 10) |
| `PROCESS_RUN_REQUEST` / `PROCESS_RUN_IDENTITY` | Reused: `AgentRunRequest` -- see `L5DGVA_PROCESS_RUN_REQUEST_CONTRACT.md` |
| `PROCESS_LAUNCH_POLICY` | New: Repository Identity Gate (`require_canonical_repository_identity()`) |
| `PROCESS_MONITOR` | Reused: `agent_execution_backend.monitor_and_ingest()` |
| `PROCESS_RESULT_CONTRACT` / `PROCESS_RESULT_INGESTION` | Reused: `AgentRunResult`, `model_handoff_workflow.import_result()` |
| `PROCESS_TIMEOUT` / `PROCESS_CANCEL` | Reused: `timeout_policy_seconds`, `monitor_and_ingest()`'s own terminate/kill path |
| `PROCESS_RECOVERY` | Reused: `active_run_for_action()`, `AGENT_RUN_RECOVERY` |
| `PROCESS_IDEMPOTENCY` | Reused: `ACTION_ID`-keyed `active_run_for_action()` |
| `PROCESS_AUDIT_TRACE` | Reused: `read_audit_trace()` |
| `CANONICAL_MUTATION_LEASE` | Reused: `acquire_mutation_lease()`/`release_mutation_lease()`, R006-1/R007-1-hardened this program |
| `PROCESS_SCOPE_ENFORCEMENT` | Reused: `task_boundary_conformance.py`, `enforce_worker_scope()` |
| `EXECUTION_BACKEND_REACHABILITY_AUDIT` | New this dispatch: `L5DGVA_NEXT_ACTION_REACHABILITY_MATRIX.csv` |

## Current M7 Scope -- honored

Next Action -> Executor reachability closed first (see the M7-specific
closure report). Human-mediated Codex/ChatGPT transport preserved --
no provider transport automation was built. M8 not started. Reference USB
not consumed. Claude host-permission work not reopened.

See `L5DGVA_PROCESS_EXECUTION_AUDIT_EVIDENCE.md` for the real evidence
behind every claim above, and `M7_NEXT_ACTION_REACHABILITY_CLOSURE_
REPORT.md` / `M7_COMPLETION_EVALUATION_EVIDENCE.md` for the M7-specific
replay.
