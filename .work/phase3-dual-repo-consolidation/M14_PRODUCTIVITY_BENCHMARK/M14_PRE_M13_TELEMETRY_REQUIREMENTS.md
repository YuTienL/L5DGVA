# M14 — Pre-M13 Telemetry Requirements (future obligations only)

Status: registration of **future measurement obligations and owner
dependencies only**. No telemetry is implemented by this reconciliation.
`M7`–`M13` MUST NOT run M14 early, and any telemetry those waves
eventually add must not materially distort either benchmark arm's real
task performance (an instrumentation overhead that changes which arm
looks faster would invalidate the whole benchmark).

## 1. Reuse-first check (per Methodology Consolidation Rule)

`dv_harness/loop_telemetry.py` already exists in canonical and is the
nearest real precedent for "non-invasive measurement of an execution
loop" — a future M14 telemetry foundation should extend/reuse its
shape rather than build a second, competing telemetry mechanism,
consistent with this project's standing "no second engine" discipline.
This reconciliation does not modify `loop_telemetry.py` (roadmap-only
scope) — the reuse relationship is registered here as a dependency for
whichever wave (M7 or later) actually builds `CAP-M14-004`.

## 2. Non-invasive telemetry foundations, by owner wave

| Telemetry category | Example signals | Candidate owner wave | Why that wave |
|---|---|---|---|
| Timestamps | Task start/end, stage-transition timestamps | M6 (lifecycle wiring) | `lifecycle.py`'s own transition table already timestamps milestones; a task-level timestamp is the natural extension once `dv-harness start`'s `INTAKE_ROUTING` and `lifecycle.json` transitions are wired |
| Human-interaction counts | `HUMAN_CLARIFICATION_COUNT`, `MANUAL_CODE_FIX_COUNT` | M6 (ClarificationService) | `ClarificationService`'s own build is the real producer of a clarification-count signal — must exist before it can be counted |
| AI-interaction counts | `NUMBER_OF_AI_INTERACTIONS`, `AI_INTERACTION_TIME`, `CONTEXT_REEXPLANATION_COUNT` | M7 (multi-model orchestration + Token Observability) | M7 is already the named owner of "Token Observability" in the existing roadmap — the same instrumentation layer is the natural home for interaction counting |
| Build/simulation iterations | `BUILD_ITERATIONS`, `SIMULATION_ITERATIONS` | M9 (ExecutionService/RemoteEDABackend TARGET) | Build/sim dispatch does not have a real, operational owner until M9's ExecutionService target lands |
| RCA iterations | `RCA_ITERATIONS` | M8 (Knowledge Brain / Continuous Project Experience Learning) | RCA iteration counting is a natural byproduct of M8's own experience-learning event stream, which already needs to observe RCA cycles to learn from them |
| Test/regression selections | `REGRESSION_SELECTION_EFFICIENCY`, `BUILD_ITERATIONS` cross-reference | M10 (vPlan -> Coverage Closure -> Traceability -> Waiver -> Signoff) | Regression selection is native to M10's own signoff-evidence pipeline |
| Coverage progression | `FUNCTIONAL_COVERAGE`, `CODE_COVERAGE`, `TIME_TO_COVERAGE_TARGET` | M10 | Same reasoning — M10 already owns coverage-closure tracking |
| Evidence/signoff events | `TIME_TO_SIGNOFF`, `SIGNOFF_EVIDENCE_COMPLETENESS`, `RE_SIGNOFF_TIME` | M10 / M10.5 | M10 owns first-pass signoff; M10.5 owns re-signoff under `MAINTAIN_LIFECYCLE` |
| Maintenance-change events | `MAINTENANCE_CHANGE_TIME`, `USER_CUSTOMIZATION_PRESERVATION` | M10.5 | `MAINTAIN_LIFECYCLE`'s own 18 stages are the only real owner of a maintenance-change event stream |

## 3. Constraints on any future telemetry implementation

1. **Non-invasive**: telemetry collection must not change the task's
   own execution path, timing-sensitive behavior, or resource budget in
   a way that would make one arm systematically look different from how
   it performs unobserved.
2. **No early M14**: none of the waves above may use their own
   telemetry foundation to run an actual A-vs-B comparison, publish a
   productivity claim, or otherwise start M14 ahead of M13's
   completion — the foundation is collection-capability only, inert
   until M14 itself activates it.
3. **No implementation this task**: this reconciliation is
   documentation-only. `CAP-M14-004` (`BENCHMARK_TELEMETRY_FOUNDATION`)
   is registered as `ROADMAP_DEFINED`, `IMPLEMENTED=NO`, and stays that
   way until the owner wave in the table above actually builds it.

## 4. Explicit non-goal

This document does not commit any of M7–M13 to build ALL of the
telemetry categories above by name — it records where each category's
*most natural* owner would be if and when that wave chooses to build a
non-invasive telemetry foundation, per Section 7 of the parent
requirements document ("M7-M13 MAY provide... telemetry foundations,"
not MUST). Each owner wave's own future planning decides whether and
how to act on this table.
