# L5DGVA Agent Run Request Contract

Code: `dv_harness/agent_execution_backend.py::AgentRunRequest`,
`build_agent_run_request()`.

## Fields (all 21 required logical fields present)

| Field | Type | Source |
|---|---|---|
| `AGENT_RUN_ID` | UUID4 str | generated fresh per request, never caller-supplied |
| `TASK_ID` | str | the M7 (or other) task this run serves |
| `PARENT_WORKFLOW_ID` | str | e.g. the Codex review task that produced the triggering result |
| `ACTION_ID` | str | the Next-Action-Resolver-derived action identity (idempotency key) |
| `ACTION_TYPE` | str | free text, e.g. `REMEDIATE_FINDINGS` |
| `BACKEND` | str | `"claude"` (only `SUPPORTED_BACKENDS` member today) |
| `ROLE` | str | e.g. `"implementation"` |
| `OBJECTIVE` | str | rendered into the worker's own prompt (`_render_objective_prompt`) |
| `CURRENT_HEAD` | str | real `git rev-parse HEAD`, never a literal |
| `WORKING_DIRECTORY` | str | the Canonical repo root by default (never a frozen source -- see below) |
| `TASK_SCOPE` | `TaskBoundary` | reused verbatim, never re-implemented |
| `ALLOWED_FILES` / `FORBIDDEN_FILES` | derived | `task_scope.allowed_path_prefixes` / `.forbidden_paths` |
| `FROZEN_SOURCES` | tuple[str] | e.g. Parent/v50/b7a/b7b/b8 paths -- always additionally forbidden, on top of `task_scope`, in `enforce_worker_scope()` |
| `INPUT_EVIDENCE_REFS` | tuple[str] | shared read-only evidence, rendered into the prompt |
| `REQUIRED_GOVERNANCE_REFS` | tuple[str] | task-scoped governance citations |
| `EXPECTED_OUTPUT` | str | rendered into the prompt |
| `VALIDATION_REQUIREMENTS` | tuple[str] | rendered into the prompt |
| `TOOL_EXECUTION_PROFILE` | str | a `safe_tool_profile.py` profile name |
| `TIMEOUT_POLICY` | float seconds | task/profile-driven, never a CLI-side timeout |
| `RETRY_POLICY` | int `max_attempts` | drives `AGENT_RUN_FAILED_RETRY_ELIGIBLE` vs `_ESCALATE` |
| `MUTATION_ALLOWED` | bool | `False` skips the mutation lease entirely (read-only parallelism) |
| `HUMAN_AUTHORITY_CONSTRAINTS` | tuple[str] | checked by `blocking_human_gate()` before any launch |
| `RESUME_CONTRACT` | str | where/how the structured result will be found |

Identity/retry: `ATTEMPT_NUMBER`, `PREVIOUS_ATTEMPT`, `RETRY_REASON` are
real fields on every request -- a retry passes `previous_attempt=<agent_run_id>`
and a real reason string, never launched as an unrelated fresh task
(`test_same_action_not_double_launched` exercises the retry-request shape
directly).

## Minimum Sufficient Execution Context

`build_agent_run_request()`'s own docstring states the discipline reused
from M7's handoff builder verbatim: "objective + exact scope + Canonical
state + relevant evidence + task-scoped governance + expected output --
never a full chat-history or whole-governance-corpus dump."
`context_size_bytes()` gives the same real-byte-count proxy metric
`model_handoff.context_size_bytes()` already established, never a
provider token count this module cannot observe.

## Reuse

`TASK_SCOPE` is a real `task_boundary_conformance.TaskBoundary`, not a
new/parallel scope type -- the SAME object `model_result.validate_result()`
and `model_handoff.read_boundary()` use elsewhere in this M7 chain.
