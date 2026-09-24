# CAP-M6-DISPATCH-001 — Implementation Report

Executed under the approved `DEC-M6-DISPATCH-001 = OPTION_A` decision.
Adopts the verified behavior/architecture contract from Parent's real
`start_lifecycle()`/`_intake_first_guard()` -- never a blind whole-file
copy; adapted to canonical's real `Stage`/`Milestone` sets and reusing
canonical's own real `lifecycle.py`/`intake_field_resolution.py`/
`task_boundary_conformance.py` foundations verbatim.

```
CAP_M6_DISPATCH_001_STATUS = IMPLEMENTED

START_HEAD = ae4a797c34c33b4db9789df4b1379ecb69e7976d
END_HEAD   = <filled by the commit this report is included in>

START_LIFECYCLE_ENTRY = WIRED
CLI_LIFECYCLE_CONVERGENCE = YES
DASHBOARD_LIFECYCLE_CONVERGENCE = YES

DIRECT_RUNTIME_BYPASSES = 2
AUTHORIZED_LOW_LEVEL_BYPASSES = 2
UNKNOWN_RUNTIME_CALLERS = 0
PUBLIC_SIGNATURE_BREAKS = 0

TASK_BOUNDARY_FOUNDATION_REUSED = YES
FIELD_RESOLUTION_FOUNDATION_REUSED = YES

REGRESSION_CAUSED_BY_M6_DISPATCH = 0
UNKNOWN_REGRESSION_FAILURES = 0

M6_VERTICAL_SLICE_CONNECTED_STAGES_BEFORE = 0
M6_VERTICAL_SLICE_CONNECTED_STAGES_AFTER = 6

M6_CORE_BLOCKERS_REMAINING = 2   (CAP-M6-CLARSVC-001, CAP-M5M6-VLEVEL-001 --
                                   CAP-M6-DISPATCH-001 itself is no longer
                                   an open blocker: the decision is made
                                   AND implemented)

REFERENCE_USB_ENV_CONSUMED = NO
NEXT_RECOMMENDED_GATE = CAP-M6-CLARSVC-001 (its own architecture is already
                          decided, D2; the ClarificationService build itself
                          can now target the real interface boundary
                          start_lifecycle() exposes -- file_clarification()
                          call sites, intake_clarification_ids lifecycle
                          fact -- rather than an undesigned one)
```

## What was built

### `dv_harness/engine.py`

- `DVHarness._lifecycle_bypass: Optional[str] = None` — new instance
  attribute, set only by an explicit bypass (`start_lifecycle(advanced=True)`
  or `run-stage --advanced`), never a default.
- `_POST_INTAKE_MILESTONES` — module-level constant, the `lifecycle.
  Milestone` values a stage is allowed to run beyond.
- `_intake_first_guard(self, stage)` — new method, called from inside
  `run_stage()` itself (right after the dry-run check, before the DEGRADED
  gate) so **every** caller of `run_stage()` is gated identically, per item
  3 of the approval ("direct loop()/run_stage() execution must not remain
  an ordinary bypass"). A structural no-op when no lifecycle file exists
  (item 4: existing callers unaffected) or for `ENV_CHECK`/`INTAKE`
  themselves.
- `_lifecycle_store()` / `_lifecycle_entry_plan()` / `_start_dispatch()` —
  small real helpers, adapted from Parent's own equivalents to canonical's
  real `Stage` enum (canonical's real first stage is `ENV_CHECK`; Parent's
  `INTAKE_ROUTING` concept does not exist in canonical and was correctly
  left out of scope — see `M6_OPERATIONAL_VERTICAL_SLICE.md`'s disclosed
  correction).
- `start_lifecycle(self, user_goal, *, loop=False, dry_run=False, level=None,
  protocols=(), field_controls=(), task_boundary=None, advanced=False)` —
  the new canonical entry point. Composes, without duplicating:
  - `lifecycle.LifecycleStore` (CREATE/ADOPT_LEGACY/RESUME, real milestone
    transitions);
  - `intake_field_resolution.resolve_field()` /
    `evaluate_question_gate()` / `file_clarification()` (CAP-ATL-007,
    reused verbatim — item 8) for the unresolved-field → real question
    queue hand-off (item 17's "expose/consume the interface boundary"
    without building `ClarificationService`);
  - `task_boundary_conformance.check_working_tree_conformance()`
    (CAP-ATL-004, reused verbatim — item 6/8);
  - `level`/`protocols` stored as real `lifecycle._FACT_KEYS` facts,
    never interpreted (item 18: VerificationLevel stays out of scope).

### `dv_harness/cli.py`

- `start`: gains `--advanced`/`--level`/`--protocols`; now calls
  `h.start_lifecycle(...)` instead of `h.loop()`/`h.run_stage()` directly.
- `run-stage`: gains `--advanced` (item 15's explicit, recorded bypass for
  this one, still-real low-level path — item 3 means it must not be an
  *ordinary* bypass, not that it must be deleted, per item 14).

### `dv_harness/dashboard.py`

- `_start_background_run()`: now calls `h.start_lifecycle(goal, loop=loop)`
  instead of `h.loop()`/`h.run_stage()` directly. No `--advanced`/`--level`/
  `--protocols` surface exists in the dashboard UI yet — a real, disclosed
  follow-up, not silently assumed unnecessary.

## Complete caller sweep (item 12/13)

| Caller | Classification |
|---|---|
| `cli.py` `start --loop` | `MIGRATE_TO_START_LIFECYCLE` — done |
| `cli.py` `start` (non-loop) | `MIGRATE_TO_START_LIFECYCLE` — done |
| `dashboard.py` `_start_background_run` (loop branch) | `MIGRATE_TO_START_LIFECYCLE` — done |
| `dashboard.py` `_start_background_run` (non-loop branch) | `MIGRATE_TO_START_LIFECYCLE` — done |
| `cli.py` `run-stage` subcommand | `REMAIN_DIRECT_FOR_EXPLICIT_LOW_LEVEL/TEST_USE` — gained `--advanced` bypass policy |
| `capability_evolution.py:2473` (`run_controlled_experiment()`) | `REMAIN_DIRECT_FOR_EXPLICIT_LOW_LEVEL/TEST_USE` — its own synthetic experiment roots never create a lifecycle, confirmed unaffected by the real regression run |
| `engine.py:5866` (`loop()`'s fan-out branch retry) | `REMAIN_INTERNAL_PRIMITIVE` |
| `engine.py:6042` (dry-run helper) | `REMAIN_INTERNAL_PRIMITIVE` |
| `engine.py:6149` (`loop()`'s own per-iteration call) | `REMAIN_INTERNAL_PRIMITIVE` |
| 46 `dv_harness_tests/*.py` files | `REMAIN_DIRECT_FOR_EXPLICIT_LOW_LEVEL/TEST_USE` (bulk) — none create a lifecycle file, confirmed structurally unaffected |

`UNKNOWN_RUNTIME_CALLERS = 0`. `DIRECT_RUNTIME_BYPASSES = 2` counts the two
real, non-test, non-internal callers that reach `run_stage()`/`loop()`
without going through `start_lifecycle()` (`run-stage` CLI subcommand,
`capability_evolution.py`'s controlled-experiment harness) — both remain
subject to `_intake_first_guard()`'s own embedded check, so neither is an
*ordinary*, ungated bypass; `run-stage` additionally gained the explicit
`--advanced` escape hatch. `AUTHORIZED_LOW_LEVEL_BYPASSES = 2` counts the
two CLI-level bypass entry points (`start --advanced`, `run-stage
--advanced`), both sharing the one real `self._lifecycle_bypass` /
`LifecycleStore.record_bypass()` mechanism — explicit, non-default,
auditable, scoped, and structurally unable to masquerade as normal
qualified execution (it always writes a real `LIFECYCLE_BYPASS` /
`lifecycle.json` bypass entry).

## Test-first evidence (item 16)

`dv_harness_tests/test_start_lifecycle_dispatch.py` — 23 new tests, all
required families covered: normal intake-first execution, unresolved-field
path, resolved-field path, lifecycle gate rejection, allowed/invalid
transition, CLI convergence, dashboard convergence, backward-compatible
caller behavior, explicit low-level bypass (both `start_lifecycle
(advanced=True)` and the CLI `run-stage --advanced` flag), plus Task
Boundary Gate coverage. 23/23 pass.

## Full regression (all 47 dispatch-touching files, including the new one)

```
python -m pytest <47 files touching .loop(/.run_stage(> -v
=> 5 failed, 1146 passed, 10 skipped in 1143.38s (0:19:03)
```

All 5 failures are byte-identical, by test ID, to 5 of the 40 `PRE_EXISTING`
failures already classified in the M5 Final Closure Regression's own
`M5_FINAL_CLOSURE_FAILURE_CLASSIFICATION.md` (`test_question_queue_digest_
auto_trigger.py`, `test_resource_cost_autonomy.py`, and 3 in
`test_waveform_dump_scope_human_confirmation.py` — a real, pre-existing
`question_queue.py` digest/filing behavior producing more question records
than a shared test scenario expects). None of the 5 failing files touch
`lifecycle.py`, `start_lifecycle()`, or the new `_intake_first_guard()`.
`REGRESSION_CAUSED_BY_M6_DISPATCH = 0`, `UNKNOWN_REGRESSION_FAILURES = 0`.

Two real end-to-end paths through the now-guarded `run_stage()` were
individually confirmed passing (not merely inferred from the aggregate
count): `test_qualified_conclusion_closure_gate.py::test_loop_reaches_
signoff_once_the_conclusion_qualifies` (a real `loop()` run all the way to
SIGNOFF) and `test_signoff_stage_gate_e2e.py::test_run_stage_signoff_
passes_all_nine_real_gates_end_to_end`.

**Disclosed process note**: the first attempt at this same regression
(`-q` mode) was killed based on a CPU-usage heuristic without verifying
which specific test was in progress — a real process error, since several
of these 47 files (e.g. `pueue` subprocess tests) are legitimately slow
without being hung. Re-run in `-v` mode with real per-test hang discipline
(no test name repeated across consecutive polls) produced the real result
above; the first, killed attempt's `[exited with code 0]` was not treated
as evidence of anything.

## Governance gates

```
dv_harness.constitution_gate.check_constitution_intact('.')
  => ConstitutionCheckResult(status='PASS', reasons=[])
```

All 5 frozen sources (Parent/v50/b7a/b7b/b8) re-verified unchanged
immediately before this report's own commit.

## What remains genuinely open (not started here, per items 17-20)

- `CAP-M6-CLARSVC-001` (`ClarificationService` build) — its own capability,
  architecture already decided (D2), not touched.
- `CAP-M5M6-VLEVEL-001` (`VerificationLevel`) — `level`/`protocols` are
  accepted and stored as real lifecycle facts by `start_lifecycle()`, never
  interpreted; `verification_level.py` itself was not created.
- `QuestionOwner`/`HumanGate` (`CAP-HITL-005`/`006`) — still
  `ROADMAP_DEFINED`; no routing/gate mechanism was built for them.
- The dashboard UI's own `--advanced`/`--level`/`--protocols` surface — a
  real, disclosed follow-up.
- `M10.5`/`M11`/`M12`/`M13`/`M14` — not started. `REFERENCE_USB_ENV_CONSUMED = NO`.
