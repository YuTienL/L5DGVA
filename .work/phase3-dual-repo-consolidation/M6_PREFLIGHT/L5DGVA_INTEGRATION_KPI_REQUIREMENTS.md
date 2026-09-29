# L5DGVA Integration KPI Requirements

Reconciled from the Prime Directive's `E2E KPIs` section. Defines each KPI
and states its **current real value where already measured this program**
(reused from Master status / `M6_VERTICAL_SLICE_STATUS.md`, never
re-derived from scratch this task) or `NOT_YET_AUDITED` where no accepted
artifact covers it yet. Progress is measured by these, not by capability
count.

## Definitions

| KPI | Definition |
|---|---|
| `TOTAL_REQUIRED_STAGES` | The number of stages in the Golden Operational Workflow that a given scope (e.g. the M6 slice) must connect |
| `CONNECTED_STAGES` | Stages whose output is genuinely consumed by the next required runtime stage (module existence/import/isolated test is insufficient) |
| `WIRED_STAGES` | Stages with a real producer/consumer connection in source, whether or not yet triggered in production |
| `TRIGGERED_STAGES` | Stages with an observed/tested real runtime invocation |
| `CONSUMED_STAGES` | Stages whose output a downstream stage actually consumes |
| `OPERATIONAL_STAGES` | Stages proven to work end-to-end in the real production call path, with gates/evidence |
| `HITL_CONNECTED_STAGES` | Stages where a human-in-the-loop gate (QuestionOwner/HumanGate or equivalent) is genuinely reachable, not merely defined |
| `EVIDENCE_CONNECTED_STAGES` | Stages that produce real, cited evidence (test/log/event), not merely a status claim |
| `CAPABILITY_ISLANDS` | Count of capabilities/connections that fail the ten-field `CAPABILITY_ISLAND` test in `L5DGVA_CAPABILITY_MATURITY_AND_ISLAND_POLICY.md` |
| `UNCONTROLLED_BYPASSES` | Runtime paths that reach `loop()`/`run_stage()` without going through `start_lifecycle()` and are NOT one of the explicit, audited, `LIFECYCLE_BYPASS`-recording bypasses |
| `UNKNOWN_RUNTIME_CALLERS` | Callers of a changed public function/signature not accounted for by a caller sweep |
| `UNKNOWN_FAILURE_PATHS` | Capabilities whose failure/error behavior has never been exercised or documented |

## Current real values (reused evidence, this task)

```
M6_VERTICAL_SLICE_TOTAL_REQUIRED_STAGES = 10
  (Intake, Field Resolution, Clarification, QuestionOwner, HumanGate,
   EffectiveValue, Dispatch, Task Boundary, VerificationLevel,
   IP/SUBSYSTEM/SYSTEM_LEVEL -- M6_VERTICAL_SLICE_STATUS.md)

M6_VERTICAL_SLICE_CONNECTED_STAGES = 8  (of 10; unchanged by this task,
  reused from M6_VERTICAL_SLICE_STATUS.md -- this task performed no new
  implementation that would move this number)

M6_VERTICAL_SLICE_WIRED_STAGES = 8  (same 8; QuestionOwner/HumanGate/
  Field-Resolution/Clarification/EffectiveValue/Dispatch/Task-Boundary/
  Intake all have real source-level connections)

M6_VERTICAL_SLICE_TRIGGERED_STAGES = 8  (all 8 connected stages have a
  real passing test exercising the real runtime call, not merely import)

M6_VERTICAL_SLICE_CONSUMED_STAGES = 8  (same 8 -- each one's output is
  consumed by the next stage in start_lifecycle()'s own dispatch)

M6_VERTICAL_SLICE_OPERATIONAL_STAGES = 0  (disclosed, not rounded up --
  every one of the 8 connected stages is only reachable when a caller
  supplies field_controls/task_boundary explicitly; no production CLI/
  dashboard caller does so today, per the capability-island finding in
  L5DGVA_GOLDEN_OPERATIONAL_WORKFLOW.md. WIRED+TRIGGERED+TESTED in a test
  harness is not OPERATIONAL in the production call path -- see the
  maturity-ladder distinction in L5DGVA_CAPABILITY_MATURITY_AND_ISLAND_
  POLICY.md)

M6_VERTICAL_SLICE_HITL_CONNECTED_STAGES = 2  (QuestionOwner, HumanGate --
  both newly connected this program by CAP-M6-CLARSVC-001)

M6_VERTICAL_SLICE_EVIDENCE_CONNECTED_STAGES = 8  (all 8 connected stages
  cite a real passing test by name in M6_CLARSVC_001_TEST_EVIDENCE.md /
  M6_DISPATCH_001 test evidence)

CAPABILITY_ISLANDS_IDENTIFIED = 1 (this reconciliation's own finding: the
  field_controls/create_environment.py disconnect) + NOT_YET_AUDITED
  (remainder of the platform -- see L5DGVA_CAPABILITY_MATURITY_AND_ISLAND_
  POLICY.md's own disclosed scope boundary)

UNCONTROLLED_BYPASSES = 0  (DIRECT_RUNTIME_BYPASSES = 2 --
  `run-stage` CLI subcommand, capability_evolution.py's controlled-
  experiment harness -- both remain subject to _intake_first_guard() and
  are not "uncontrolled"; AUTHORIZED_LOW_LEVEL_BYPASSES = 2, both
  explicit/scoped/auditable via LifecycleStore.record_bypass(), per
  CAP-M6-DISPATCH-001's own implementation report)

UNKNOWN_RUNTIME_CALLERS = 0  (CAP-M6-DISPATCH-001 caller sweep: 0;
  CAP-M6-CLARSVC-001 caller sweep, 22 rows: 0)

UNKNOWN_FAILURE_PATHS = NOT_YET_AUDITED  (no accepted artifact has swept
  every registered capability's failure behavior; not attempted this task)
```

## Connect-Before-Expand disposition taxonomy (reused, per stage/finding)

Every future discovered capability (including the one this task itself
found) receives exactly one of:

```
REQUIRED_NOW_FOR_GOLDEN_WORKFLOW      -- a current wave's own closure
                                          directly depends on it
SAFETY_OR_CAPABILITY_LOSS_REQUIRED    -- deferring it would regress an
                                          existing verified capability or
                                          create a safety/security gap
REGISTER_AND_DEFER_WITH_OWNER         -- registered with a named owner
                                          wave, continue current E2E
                                          closure work first
```

This task's own finding (`field_controls`/`create_environment.py`
disconnect) is classified `REGISTER_AND_DEFER_WITH_OWNER` — see
`L5DGVA_GOLDEN_OPERATIONAL_WORKFLOW.md`'s worked example for the
rationale.

## What this task did not do

- Did not build a new KPI-tracking mechanism/dashboard/CSV — these values
  are reused/computed by hand this wave from already-accepted evidence,
  consistent with the directive's own "Reuse existing Master status"
  instruction. A future wave may wire a real, automated KPI producer;
  registering that need here is itself `REGISTER_AND_DEFER_WITH_OWNER`,
  not built now.
- Did not audit `UNKNOWN_FAILURE_PATHS` or the platform-wide
  `CAPABILITY_ISLANDS` count beyond the one concrete finding above.
