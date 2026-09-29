# M5 to M6 Handoff Readiness

Computed only because M5 closure succeeded on every gate this task checked.
This section does not start M6.

## M6 core blockers (structural, `PRIORITY.strip() == 'P0'` exact match, `PRIMARY_OWNER_WAVE == 'M6'`)

```
M6_CORE_BLOCKERS = 3
```

| Capability | State | Real blocker | Secondary dependency |
|---|---|---|---|
| `CAP-M6-DISPATCH-001` | PARTIAL (conflict named and understood) | `HUMAN_DECISION_REQUIRED`: which dispatch mechanism (`start_lifecycle` vs. `loop`/`run_stage`) becomes canonical | — |
| `CAP-M6-CLARSVC-001` | BLOCKED (decision made, design/build pending) | Feature-level capability comparison + build not yet done | `M7` (build continuation) |
| `CAP-M5M6-VLEVEL-001` | BLOCKED (`GENERICITY_FOUNDATION_GAP`) | Depends on `question_queue.py` (diverged, M3-excluded) + `environment_mode_router.py` has no `IP_MODE` concept today | `CAP-M6-CLARSVC-001`; `CAP-M5-ENV-001` (question_queue N-way merge) |

(`CAP-POOL-005` is a disclosed cross-reference to `CAP-M5M6-VLEVEL-001`, not
a 4th independent blocker — see the P0-count correction in
`M5_FINAL_REPORT.md`.)

## M6 foundations available (real, tested, present in canonical, explicitly deferred-to by name)

```
M6_FOUNDATIONS_AVAILABLE = 2
```

- `CAP-ATL-004` → `dv_harness/task_boundary_conformance.py` (330 lines, 19/19
  tests). `FOUNDATION_CLOSED_WITH_EXPLICIT_FUTURE_OWNER = CAP-M6-DISPATCH-001`.
  The algorithm is real and tested; only CLI/engine wiring is deferred.
- `CAP-ATL-007` → `dv_harness/intake_field_resolution.py`. `FOUNDATION_CLOSED_
  WITH_EXPLICIT_FUTURE_OWNER = CAP-M6-CLARSVC-001`. The resolution algorithm
  (`_decide()`, 9-level source-authority arbitration, human-answer override)
  is real and ported with zero logic changes; reconciliation with canonical's
  existing, different `intake_state.IntakeFieldRecord`/`IntakeFieldStatus`
  model is explicitly `CAP-M6-CLARSVC-001`'s own job, not pre-empted here.

This batch's own 8 new modules (`l5dgva_gap_queue.py` through
`l5dgva_kc_extraction.py`) are **not** claimed as M6 foundations — no
`CAP-M6-*` row names any of them as a dependency, and they serve a different
track (L5DGVA engine-telemetry/KC-extraction concepts), not the dispatch/
clarification-service track M6's 3 core blockers are about. Listing them
here would be an unevidenced claim, not a real handoff fact.

## M6 foundations missing

```
M6_FOUNDATIONS_MISSING = 3
```

- A real, merged `question_queue.py` (currently diverged, M3-excluded) —
  blocks `CAP-M5M6-VLEVEL-001`.
- An `IP_MODE` concept in `environment_mode_router.py` (does not exist
  today) — blocks `CAP-M5M6-VLEVEL-001`.
- M7's own build continuation for `CAP-M6-CLARSVC-001`'s feature-level
  capability comparison — an M7-scoped dependency, not something M5 or this
  regression task can close.

## M6 wiring obligations (real, not implied)

- `CAP-ATL-004`'s CLI verb (`task-boundary-conformance`) exists in canonical
  but is not called from any real dispatch path — `CAP-M6-DISPATCH-001`'s
  own resolution decides where that call site belongs.
- `CAP-ATL-007`'s `intake_field_resolution.py` model runs in isolation from
  canonical's existing `intake_state.py` model — `CAP-M6-CLARSVC-001` owns
  reconciling the two, not merging them prematurely.
- A human decision (`HUMAN_DECISION_REQUIRED`) is the actual next action for
  `CAP-M6-DISPATCH-001` — no further evidence-gathering closes it; this is
  a genuine decision gate, not a research gap.

M6 is not started by this task. `M6_STARTED = NO`.
