# L5DGVA Autonomous Agent Execution Backend -- Adoption Report

Sources read in full before any change:
`docs/architecture/canonical_detailed_governance/
L5DGVA_AUTONOMOUS_AGENT_EXECUTION_BACKEND_REQUIREMENTS.md` (platform
requirement) and `.work/prompts/
L5DGVA_AUTONOMOUS_AGENT_EXECUTION_BACKEND_INTEGRATION_PROMPT.md`
(implementation/validation/live-qualification contract). Extends P6.

## Outcome in one paragraph

`dv_harness/agent_execution_backend.py` + `dv_harness/safe_tool_profile.py`
implement a real, tested, live-discovered mechanism for L5DGVA to launch
and govern a controlled `claude` CLI subprocess itself (`--restricted`, a
named tool profile, `--json-schema`-shaped structured output; never
interactive-terminal injection), with a real Canonical Mutation Lease, real
Task-Boundary scope enforcement over the worker's own claims, real startup
recovery, and 6 new events wired into the SAME Next Action Resolver table.
It was live-qualified with 6 real subprocess runs in a throwaway directory
(including a real mutation and a real sandbox-escape refusal). The one
thing NOT proven this task is a live-fired production run against a real
M7 result: a real attempt was made against the real REVIEW-004 FAIL, and it
was refused by this Claude Code installation's own auto-mode permission
classifier ("Create Unsafe Agents") before any subprocess started -- a
genuine `SAFE_EXECUTION_BLOCKED` condition, not something this task can
resolve by writing more code, and not retried through any other tool per
that denial's own explicit instructions.

## Capability status (honest)

| Capability | Status |
|---|---|
| AUTONOMOUS_AGENT_EXECUTION_BACKEND | IMPLEMENTED_AND_TESTED; live-qualified via 6 real CLI runs; **one real production launch attempt was blocked by the host's own permission classifier** |
| AGENT_EXECUTION_BACKEND_ROUTER | IMPLEMENTED (`build_worker_argv()` dispatches on `BACKEND`; only `"claude"` implemented, extension point kept open per "keep future backend extension possible without building unused providers now") |
| CLAUDE_EXECUTION_BACKEND | IMPLEMENTED_AND_LIVE_QUALIFIED (see `M7_CLAUDE_WORKER_LIVE_QUALIFICATION.md`) |
| AGENT_RUN_REQUEST | IMPLEMENTED_AND_TESTED (all 21 required fields; `L5DGVA_AGENT_RUN_REQUEST_CONTRACT.md`) |
| MINIMUM_EXECUTION_CONTEXT | IMPLEMENTED (`context_size_bytes()`, same discipline as M7's own handoff builder) |
| AGENT_WORKER_LAUNCH | IMPLEMENTED_AND_TESTED; **PRODUCTION_LAUNCH_BLOCKED_BY_HOST_PERMISSION_CLASSIFIER** |
| AGENT_RUN_MONITOR | IMPLEMENTED_AND_TESTED (heartbeat, timeout, never-low-CPU-hang-detection) |
| AGENT_RUN_RESULT_INGESTION | IMPLEMENTED_AND_TESTED (structured JSON-schema result, never trusted for its own identity, re-classified against Task Boundary) |
| AGENT_RUN_RECOVERY | IMPLEMENTED_AND_TESTED (3 real scenarios: still-active, result-ingested-on-recovery, crashed-no-result) |
| AGENT_RUN_IDEMPOTENCY | IMPLEMENTED_AND_TESTED (live-PID-checked `active_run_for_action()`) |
| CANONICAL_MUTATION_LEASE | IMPLEMENTED_AND_TESTED (ownership-token + liveness-gated recovery, never elapsed time alone) |
| STATUS_REPORTER_IS_READ_ONLY | YES (proven for both `agent_execution_backend.status_report()` and `result_ingestion.status_report()` by a real before/after file-content+mtime diff test) |

## Reuse-before-create (see `L5DGVA_AGENT_EXECUTION_BACKEND_ARCHITECTURE.md`
## for the full table)

Next Action Resolver, Task Boundary, and the lifecycle/checkpoint
persistence CONVENTION were reused verbatim. The lock creation primitive
was ADAPTED (not reused as-is) because its existing staleness policy
(elapsed time alone) is exactly what this requirement forbids for a
mutation lease. `multi_agent.py`'s own orchestrator was inspected and
correctly NOT reused -- it is an intra-process blackboard-topic lock for
parallel fan-out branches of one process, a different resource entirely
from a repo-wide subprocess-launch mutation lease. Preauthorized Safe Tool
Execution was a genuine `MISSING` and was built (`safe_tool_profile.py`).

## A real, current-scope defect fixed along the way

`execution_contract.can_i_stop()` reported `HUMAN_ACTION_REQUIRED=YES` for
`TASK_COMPLETE` (found while re-inspecting live REVIEW-003 status during
this task's own preflight) -- a completed task needs nothing from anyone.
Fixed: only the two real gates (`HUMAN_AUTHORITY_REQUIRED`/
`HUMAN_TRANSPORT_REQUIRED`) now report `YES`.

## Live qualification, honestly

1. **Synthetic, pre-implementation CLI discovery** (6 real subprocess
   runs): read-only, disallowed-tool, failure classification, timeout,
   real mutation, real sandbox-escape refusal. All real, all successful in
   demonstrating the intended safety properties.
2. **Real M7 chain, first half**: the detached watcher (armed 3 days
   earlier) autonomously detected, stability-confirmed, hashed, imported,
   consumed, and resolved `AUTO_REMEDIATE_CONFIRMED_FINDINGS` for the real
   `M7-V1-CODEX-REVIEW-004` FAIL result -- fully unattended, zero manual
   intervention, proving `REAL EXTERNAL RESULT -> AUTO INGEST -> NEXT
   ACTION RESOLVER` live.
3. **Real M7 chain, second half (blocked)**: a real `AgentRunRequest` was
   built from that exact resolved next action and `launch_worker()` was
   invoked for real. The host Claude Code installation's own auto-mode
   permission classifier refused it (`"Create Unsafe Agents"`) before any
   subprocess started. Zero side effects (no `.dv-harness/agent_runs/`
   directory was even created).
4. Consequently, R004-1..R004-4 (the findings the blocked worker would
   have fixed) were fixed directly by the orchestrating session instead,
   using the same direct-editing mechanism already sanctioned throughout
   this whole multi-task chain, and a real Codex re-review handoff
   (`M7-V1-CODEX-REVIEW-005`) was generated and armed.

## What this means going forward

`AUTONOMOUS_AGENT_EXECUTION_BACKEND` is real, tested, and ready code -- but
whether it can ever actually fire a production launch on THIS host depends
on a permission this task cannot grant itself. This is the honest
`NEXT_REQUIRED_HUMAN_ACTION` for this specific capability: a human decides
whether/how to authorize this class of action for this Claude Code
installation (e.g. a Bash permission rule, or a different execution
environment), or explicitly directs that remediation continue via the
already-proven direct-editing path instead.
