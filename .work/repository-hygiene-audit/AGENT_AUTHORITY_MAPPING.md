# Agent Authority Mapping — Gate 2

**Execution mode: LOCAL_ANALYSIS.**

## Headline finding: this reconciliation already exists as a real, machine-checked repo artifact

`.claude/agents/ROSTER.md` already contains a section titled "Answers to the asserted role taxonomy" that does exactly the reconciliation this gate asks for — it was written specifically to stop this correspondence from being "rebuilt by hand" on every audit (its own words, citing a 2026-09-04 re-audit that had to do exactly that). `dv_harness_tests/test_agent_roster_doc.py` holds the agent list against `dv_harness/stats_snapshot.list_agent_files()`, and `dv_harness_tests/test_agent_dispatch_map.py` holds every Dispatch value against the real `dv_harness/agent_dispatch.agent_dispatch_map()` derivation. This is not this review's own analysis — it is a live, tested claim already in the repo, reproduced below rather than re-derived, per the project's own Evidence Truth Rule (prefer the real, checked artifact over a fresh restatement).

## The stale model (exact source text)

`.claude/INDUSTRIAL_DV_WORKFLOW.md:34` header: `## Seven agents`.

`.claude/tools/check-claude-dv-env.ps1:62-64` and `.claude/tools/dv-preflight.ps1:4-10` both hardcode this exact 7-name list:
```
dv-lead, analysis-agent, implementation-agent, build-agent,
debug-agent, regression-agent, review-agent
```
`dv-preflight.ps1:25` prints `"7 agents present; core SoC/VIP/TB/command workflow present."` and `check-claude-dv-env.ps1:93` divides its found-count by a hardcoded `/7`.

## The real model: 23 agents, 14 GRAPH_DISPATCHED

`ROSTER.md` line 45: "Counts by dispatch status: GRAPH_DISPATCHED 14, SUBGRAPH_DISPATCHED 0, WORKFLOW_DISPATCHED 0, NOT_DISPATCHED 9." All 7 of the stale list's names **are** among the real 23 (they are real agents — the stale list is not wrong about their existence, only about there being *only* seven).

## Logical role → physical agent(s) → gap, per the repo's own reconciliation

Per instruction, the 7 asserted roles below are treated strictly as **logical orchestration roles**, not as a claim that 7 new physical agents should exist.

### Roles the repo deliberately does NOT bind to any dispatched agent (4 of 7)

| # | Logical role | Physical agent(s) | Gap? |
|---|---|---|---|
| 1 | Project-management / workflow-control | **None** — ordinary Python: `dv_harness/engine.py`'s state machine + `dv_harness/planner.py`'s decomposition (deterministic/replayable/testable, which an LLM persona is not). `dv-lead` is real but owns only 3 nodes (`ENV_CHECK`, `ANALYSIS_JOIN`, `WAIT_USER`) and is explicitly **not** the workflow controller. | No gap — a deliberate design choice, not an omission. |
| 2 | Architecture-owning | **None** — `ARCH_DISCOVERY`/`ARCH_CALIBRATION`/`VERIFICATION_ARCHITECTURE` dispatch to read-only `analysis-agent` on purpose (these stages emit evidence; the engine, not an agent, writes the resulting Blackboard topics). Architecture that becomes real files is generated under `implementation-agent`/`IP_UVM_DV_Gen`. | No gap — giving this a writer persona would widen write scope for no functional gain (repo's own stated rationale). |
| 3 | Verification-planning | **None** — `VPLAN` dispatches to read-only `analysis-agent`; the vPlan artifact itself is real library code (`dv_harness/vplan_writer/`). Coverage stays deliberately split: vPlan defines intent, `regression-agent` closes it at `COVERAGE_CLOSURE`. | No gap — an intentional separation, not an omission. |
| 4 | Knowledge / memory-tier | `memory-agent` exists as a real profile but is `NOT_DISPATCHED` by design — memory work fires as engine-internal `memory_router.route_and_store()`/`promote_to_organizational()` calls (`dv_harness/engine.py:14`), per CLAUDE.md's Engineering Memory Policy. | No gap — `memory-agent`'s profile exists to document/constrain the tier for manual work, not to be a stage persona. |

### Roles a real dispatched agent performs, under a different name (3 of 7)

| # | Logical role | Physical agent | Real graph nodes | Gap? |
|---|---|---|---|---|
| 5 | Code / RTL / script implementation | **`implementation-agent`** | `COMMAND_PATTERN`, `GIT_PUSH`, `GIT_SYNC`, `IMPLEMENT` | No gap — this is the roster's primary controlled writer (no `disallowedTools`), and its node set deliberately never reaches `SIGNOFF`. |
| 6 | Simulation / job / regression-execution | **`regression-agent`** | `COVERAGE_CLOSURE`, `INFRA_RECOVERY`, `REGRESSION`, `REGRESSION_SELECT` + 4 `lsf_per_job_monitor_template.json` subgraph nodes | No gap — of the 7 asserted roles, this is the one whose real agent matches the asserted scope essentially one-for-one (repo's own assessment, and nothing found in this review contradicts it). |
| 7 | Qualification / signoff / evidence-closure | **`review-agent`** | `EXPERT_FEEDBACK_LOOP`, `PROMOTION_READINESS`, `REQUIREMENT_CLOSURE`, `RE_AUDIT`, `SIGNOFF`, `SYSTEM_LEVEL` | No gap — `review-agent` declares `disallowedTools: Edit, Write`, making its signoff genuinely independent (it cannot have written what it signs off). |

## Separation-of-duties evidence

Independent of role naming, tool-scope enforcement is real and directly inspectable: `analysis-agent` and `review-agent` both declare `disallowedTools: Edit, Write`; every node set that reaches `SIGNOFF` runs through one of those two; `implementation-agent`'s node set never reaches `SIGNOFF`. This is the actual mechanism enforcing separation of duties — not the role names themselves.

## Conclusion for this gate

**No gap exists between the "proposed 7 logical orchestration roles" and the real 23-agent model.** All 7 are already answered, 4 as deliberate non-agent design choices and 3 as work a real `GRAPH_DISPATCHED` agent already owns under its real name. The only real defect is the two **stale files** (`.claude/INDUSTRIAL_DV_WORKFLOW.md`, plus `check-claude-dv-env.ps1`/`dv-preflight.ps1`'s hardcoded 7-name/`/7` checks) that still assert a "seven agents, full stop" model contradicted by the repo's own tested `ROSTER.md`. This is a **content correction**, not a physical-agent gap, and is unchanged from the Phase-1 finding in `05_AUTHORITY_GRAPH.md`/`02_ROOT_CLASSIFICATION.md` — no new agent is proposed, and none of the three stale files was edited by this review (out of the allowed-writes scope for this task).
