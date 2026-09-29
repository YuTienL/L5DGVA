# L5DGVA Process Run Request Contract

Per `L5DGVA_CONTROLLED_PROCESS_EXECUTION_AND_MODEL_WORKER_GOVERNANCE_
REQUIREMENTS.md`'s "Canonical Process Run Request." Every field the
governance doc names already has a real, existing home in
`agent_execution_backend.AgentRunRequest` -- this contract is a mapping,
not a new schema.

| Governance field | Real field (`AgentRunRequest`) | Notes |
|---|---|---|
| `PROCESS_RUN_ID` | `agent_run_id` | |
| `TASK_ID` | `task_id` | |
| `PARENT_WORKFLOW_ID` | `parent_workflow_id` | |
| `ACTION_ID` | `action_id` | idempotency key (`active_run_for_action()`) |
| `ACTION_TYPE` | `action_type` | |
| `REQUESTED_BACKEND` / `SELECTED_BACKEND` | `backend`, reconciled through `resolve_execution_backend()`'s own `BackendResolution.requested_backend`/`selected_backend` | see `M7_EXECUTION_BACKEND_FALLBACK_RECONCILIATION.md` |
| `ROLE` | `role` | |
| `OBJECTIVE` | `objective` | |
| `REPO_ID` / `CANONICAL_REPO_ROOT_ID` | `working_directory`, verified through `controlled_process_executor.verify_canonical_repository_identity()` | new this dispatch -- see below |
| `CURRENT_HEAD` | `current_head` | |
| `WORKING_DIRECTORY` | `working_directory` | |
| `TASK_SCOPE` / `ALLOWED_FILES` / `FORBIDDEN_FILES` | `task_scope` (a real `TaskBoundary`) | `task_boundary_conformance.py`, unchanged |
| `FROZEN_SOURCES` | `frozen_sources` | |
| `INPUT_EVIDENCE_REFS` | `input_evidence_refs` | |
| `REQUIRED_GOVERNANCE_REFS` | `required_governance_refs` | |
| `TOOL_EXECUTION_PROFILE` | `tool_execution_profile`, now also resolvable from a governance-doc SEMANTIC name via `controlled_process_executor.semantic_profile_tool_execution_profile()` | new this dispatch |
| `MUTATION_ALLOWED` | `mutation_allowed` | |
| `MUTATION_LEASE_REQUIRED` | derived: `mutation_allowed=True` always acquires `agent_execution_backend.acquire_mutation_lease()` inside `launch_worker()` | unchanged |
| `EXPECTED_OUTPUT` / `EXPECTED_OUTPUT_SCHEMA` | `expected_output` (schema is fixed: `AGENT_RUN_RESULT_SCHEMA`) | |
| `VALIDATION_REQUIREMENTS` | `validation_requirements` | |
| `TIMEOUT_POLICY` | `timeout_policy_seconds` | |
| `RETRY_POLICY` | `retry_policy_max_attempts`, `attempt_number`, `previous_attempt`, `retry_reason` | |
| `RECOVERY_POLICY` | `active_run_for_action()` + `launch_worker()`'s own idempotency refusal | |
| `HUMAN_AUTHORITY_CONSTRAINTS` | `human_authority_constraints`, checked by `blocking_human_gate()` | |
| `RESUME_CONTRACT` | `resume_contract` | |

## What is genuinely new

Only the Repository Identity Gate
(`controlled_process_executor.verify_canonical_repository_identity()`/
`require_canonical_repository_identity()`) and the Semantic Profile
resolver (`semantic_profile_tool_execution_profile()`) are new code this
dispatch. Every other Process Run Request field already had a real,
tested home in `AgentRunRequest` before this dispatch -- this contract
exists to make that mapping explicit and auditable, not to duplicate it.
