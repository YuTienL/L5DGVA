# L5DGVA Golden Operational Workflow

Registered/reconciled from `docs/architecture/L5DGVA_INTEGRATION_PRIME_DIRECTIVE.md`'s
own `Golden Operational Workflow` section. One generic workflow — DE/DV are
authority roles participating in it, never separate engines
(`ONE_GENERIC_DE_DV_WORKFLOW = YES`, already frozen in
`MASTER_PROGRAM_STATUS.md`). This document does not implement any missing
stage; it names the stage sequence and cites, per stage, the real current
producer/consumer evidence already established by prior waves.

```
User / Project
-> OpenSpec Intake
-> Auto Discovery
-> Field Resolution
-> ClarificationService when unresolved
-> QuestionOwner (DE / DV / SHARED)
-> HumanGate
-> Human Answer
-> Field Resolution
-> EffectiveValue
-> Dispatch
-> Task Boundary
-> VerificationLevel
-> IP / SUBSYSTEM / SYSTEM_LEVEL
-> Verification Generation
-> EDA Execution
-> Regression
-> RCA
-> DESIGN / VERIFICATION / SHARED routing
-> Coverage Closure
-> Requirements Traceability / Waiver
-> Verification Signoff
-> Experience / Evidence
-> KC Candidate / Promotion
-> Knowledge Brain
-> Next Run
```

## Per-stage real evidence (reused, not re-audited this task)

| Stage | Real producer/consumer today | Maturity (see `L5DGVA_CAPABILITY_MATURITY_AND_ISLAND_POLICY.md`) |
|---|---|---|
| OpenSpec Intake | `lifecycle.py` CREATE/ADOPT/RESUME + `intake_routing.py`/`environment_mode_router.py` (SUBSYSTEM/SYSTEM_LEVEL only — IP_MODE has no router entry point, `CAP-M5M6-VLEVEL-001`) | WIRED (SUBSYSTEM/SYSTEM_LEVEL); ROADMAP_DEFINED (IP_MODE) |
| Auto Discovery | `intake_field_resolution.resolve_field()`'s producer chain | FOUNDATION, reused |
| Field Resolution | `intake_field_resolution.resolve_field()` / `evaluate_question_gate()` | IMPLEMENTED, WIRED (via `clarification_service.resolve_or_ask()` and `start_lifecycle()`), **TRIGGERED only when a caller supplies real `field_controls`** — see capability-island finding below |
| ClarificationService | `dv_harness/clarification_service.py` (`CAP-M6-CLARSVC-001`, CLOSED) | IMPLEMENTED, WIRED, TESTED (13/13 + 268/268 focused regression) |
| QuestionOwner (DE/DV/SHARED) | `classify_question_owner()` | IMPLEMENTED, WIRED, TESTED |
| HumanGate | `question_queue.py` `status`/`answer` gate inside `start_lifecycle()`; `human_gate_state()` projection helper has 0 production callers (disclosed) | WIRED (gate mechanism), FOUNDATION (named projection helper) |
| Human Answer -> Field Resolution | `resolve_or_ask()`'s `human_answer=` re-entry into `resolve_field()` | IMPLEMENTED, WIRED, TESTED |
| EffectiveValue | `intake_field_resolution.EffectiveValue` | IMPLEMENTED, WIRED, TESTED |
| Dispatch | `start_lifecycle()` -> `_start_dispatch()` -> `loop()`/`run_stage()` | IMPLEMENTED, WIRED, TESTED (`CAP-M6-DISPATCH-001`, CLOSED) |
| Task Boundary | `task_boundary_conformance.py` via `_intake_first_guard()` | IMPLEMENTED, WIRED, TESTED |
| VerificationLevel | `verification_level.py` — **absent from canonical**; `level`/`protocols` accepted and stored by `start_lifecycle()` but never interpreted | ROADMAP_DEFINED (`CAP-M5M6-VLEVEL-001`, open) |
| IP / SUBSYSTEM / SYSTEM_LEVEL | `environment_mode_router.py` — SUBSYSTEM/SYSTEM_LEVEL real; IP_MODE has no concept at all | WIRED (2 of 3 modes); ROADMAP_DEFINED (IP_MODE) |
| Verification Generation | `create_environment.py` / `ProtocolEnvGenerator` / `soc_environment_composer.py` | WIRED, 1-2 disclosed latent defects (`CAP-M5-ARCH-001/002`), **not reachable from `start_lifecycle()`'s own dispatch path today — see capability-island finding below** |
| EDA Execution | `remote_hop`/`remote_relay`/`remote_exec` transport | WIRED (transport), execution-profile-scoped |
| Regression | `regression_reporter.py` / `lsf-watch` | WIRED |
| RCA | `debug-agent` family + evidence gates | WIRED, PARTIAL depth (see `analysis_debug`/`issue_triage` gating) |
| DESIGN/VERIFICATION/SHARED routing | RCA role-routing capabilities (`CAP-HITL-006` `RCA_ROLE_ROUTING`) | ROADMAP_DEFINED, not implemented |
| Coverage Closure | `coverage_analysis.py`, `coverage_closure_loop_leg_matrix.py` | PARTIAL |
| Requirements Traceability / Waiver | `requirement_traceability_registry.py` | IMPLEMENTED, WIRED |
| Verification Signoff | `signoff_evidence_truth_gate.py`, `qualified_conclusion.py` | WIRED, gated |
| Experience / Evidence | Job/Project Memory tiers | PARTIAL (`CAP-CE-008` PROJECT_EXPERIENCE_EXTRACTION PARTIAL) |
| KC Candidate / Promotion | `memory_router.route_and_store()` | **BROKEN on every tree** — `CAP-M8-EXPLOOP-001`, confirmed pre-existing defect, not a migration omission |
| Knowledge Brain | 5-tier Memory + Obsidian vault | PARTIAL (external loop OPERATIONAL, internal loop PARTIAL/ABSENT — `MASTER_CONTINUOUS_EVOLUTION_STATUS.md`) |
| Next Run | Continuous-evolution loop closure | Depends on the two items above; not closed |

## What this reconciliation did NOT do

- Did not implement `VerificationLevel`, IP_MODE, `RCA_ROLE_ROUTING`,
  `EXPERIENCE_READY` event wiring, or any other missing stage.
- Did not re-audit RCA/Coverage/Signoff/Experience depth beyond citing
  already-accepted evidence (`MASTER_END_TO_END_DV_STATUS.md`,
  `MASTER_CONTINUOUS_EVOLUTION_STATUS.md`).
- Did not merge `intake_state.py` into this workflow's own Field
  Resolution stage — that reconciliation (`CAP-M6-CLARSVC-001`) already
  disclosed and preserved that separation.

## Golden-Workflow-relevant capability island found this reconciliation (not fixed here)

`ClarificationService` (`Field Resolution -> ClarificationService ->
QuestionOwner -> HumanGate -> Human Answer -> Field Resolution ->
EffectiveValue -> Dispatch`) is real, wired and tested **inside
`start_lifecycle()`'s own dispatch path** — but `start_lifecycle()`'s
`field_controls` parameter defaults to `()` and neither the `start` CLI
command nor `dashboard.py`'s launcher passes any real `FieldControl` list
today (confirmed by direct grep: `dv_harness/cli.py:6402`,
`dv_harness/dashboard.py:8856`, neither includes `field_controls=`).
Separately, `Verification Generation` (`create_environment.py` /
`ProtocolEnvGenerator`) is reached through its own call path
(`tools/generate_protocol_uvm_environment.py`), not through
`engine.py`'s `run_stage()`/`loop()` — confirmed by direct grep
(`create_environment`/`environment_mode_router` appear in `engine.py` only
as read-only evidence-reporting call sites, never as a stage dispatch).

Net effect: today, a real DE/DV user driving `l5dgva start` never actually
has a live DUT/env/vip field routed through the real, tested
`ClarificationService` before generation — the mechanism and the
generation dispatch are two disconnected islands. See
`L5DGVA_CAPABILITY_MATURITY_AND_ISLAND_POLICY.md`'s worked example for the
full TRIGGER/INPUT/PRODUCER/CAPABILITY/OUTPUT/CONSUMER/NEXT_STAGE/
EVIDENCE/FAILURE_PATH/HUMAN_AUTHORITY classification. Disposition per the
Connect-Before-Expand gate: `REGISTER_AND_DEFER_WITH_OWNER` (M6/M9 — the
same wave that must connect `VerificationLevel`/IP_MODE into
`start_lifecycle()`'s dispatch is the natural point to also route real
intake `field_controls` and to converge `create_environment.py`'s call
path onto `run_stage()`), not a Golden-Workflow blocker requiring
immediate interruption of other in-flight work, since no current wave's
own closure depends on it today.
