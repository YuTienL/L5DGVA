# L5DGVA Capability Maturity and Capability-Island Policy

Reconciled from `docs/architecture/L5DGVA_INTEGRATION_PRIME_DIRECTIVE.md`'s
`OPERATIONAL BEFORE CLAIMED` and `NO CAPABILITY ISLANDS` sections, and from
`docs/architecture/L5DGVA_CONSTITUTION.md`'s existing **Capability
Operationalization Standard**. This document reconciles the two into one
ladder — it does not invent a second, competing one.

## Maturity ladder (reconciled, not duplicated)

```
ROADMAP_DEFINED -> FOUNDATION -> IMPLEMENTED -> WIRED -> TRIGGERED -> CONSUMED -> OPERATIONAL -> QUALIFIED
```

| Value | Meaning | Relationship to the existing Constitution vocabulary |
|---|---|---|
| `ROADMAP_DEFINED` | Requirement + owner wave named, nothing built | New rung, below the Constitution's own `IMPLEMENTED` |
| `FOUNDATION` | A reusable contract/module exists that a future capability can build on, but is not itself the target capability | New rung, distinguishes e.g. `intake_field_resolution.py` (FOUNDATION for many M6 items) from the item itself |
| `IMPLEMENTED` | Code/artifact exists | = Constitution's `IMPLEMENTED` |
| `WIRED` | A real producer/consumer connection exists in source | = Constitution's `WIRED` |
| `TRIGGERED` | A real runtime invocation has been observed/tested, not merely importable | = Constitution's `TRIGGERED` |
| `CONSUMED` | A downstream stage actually consumes the output | = Constitution's `CONSUMED` |
| `OPERATIONAL` | The intended end-to-end behavior works, with gates/evidence, in the real production call path (not only a test harness) | New, stricter than `TRIGGERED`+`CONSUMED` alone — requires the *production* call path, not just a test proving the function works in isolation |
| `QUALIFIED` | An accepted qualification (e.g. a Golden E2E run) proves it | = Constitution's `TESTED`, elevated to a product-level qualification claim |

Invariants (reconciled, both documents already agreed on these; restated
once, not duplicated per-document):

```
FOUNDATION != OPERATIONAL
IMPLEMENTED != WIRED
TESTED != CONSUMED
MODULE_EXISTS != RUNTIME_USED
ROADMAP_DEFINED != IMPLEMENTED
```

**Worked distinction, from this task's own evidence**: `clarification_service.py`
is `IMPLEMENTED, WIRED, TRIGGERED, TESTED` — 13/13 dedicated tests plus
268/268 focused regression, and genuinely called by `start_lifecycle()`.
It is **not** `OPERATIONAL` in the sense this ladder requires, because no
real production caller (`start` CLI, dashboard launcher) supplies it a real
`field_controls` list yet — `TRIGGERED`+`TESTED` in a test harness is not
the same claim as `OPERATIONAL` in the live production call path. This is
the concrete difference the ladder exists to prevent conflating.

## CAPABILITY_ISLAND definition

A capability is `CAPABILITY_ISLAND = YES` unless it can name all ten of:

```
TRIGGER        -- what real event/user action initiates it
INPUT          -- what real data it consumes
PRODUCER       -- what real upstream capability supplies that input
CAPABILITY     -- the capability itself
OUTPUT         -- what real data it produces
CONSUMER       -- what real downstream capability consumes that output
NEXT_STAGE     -- what Golden-Workflow stage follows
EVIDENCE       -- what real evidence exists (test, log, event) that the
                  above connections are real, not assumed
FAILURE_PATH   -- what happens, and who is told, when it fails
HUMAN_AUTHORITY -- which authority role (DESIGN/VERIFICATION/SHARED) owns
                  a human decision here, if any
```

Temporary islands require an explicit owner wave and cannot be called
`OPERATIONAL` while they remain islands, however complete their own
internal implementation is.

## Worked example (this reconciliation's own finding, not fixed here)

`ClarificationService`, classified against the ten fields:

```
TRIGGER        = a caller invoking start_lifecycle() with an unresolved
                 FieldControl
INPUT          = a FieldControl + evidence producers
PRODUCER       = intake_field_resolution.resolve_field() /
                 evaluate_question_gate()
CAPABILITY     = clarification_service.resolve_or_ask()
OUTPUT         = a ClarificationOutcome (resolved EffectiveValue, or a
                 filed question with a real, persisted authority_role)
CONSUMER       = start_lifecycle()'s own dispatch-blocking logic
NEXT_STAGE     = Dispatch (if resolved) / HumanGate (if not)
EVIDENCE       = 13/13 test_clarification_service.py +
                 268/268 focused regression + M6_CLARSVC_001_TEST_
                 EVIDENCE.md
FAILURE_PATH   = WAIT_USER AgentResult, blocked_by="clarification",
                 resumes once question_queue.py records a real answer
HUMAN_AUTHORITY = classify_question_owner() -- DESIGN/VERIFICATION/SHARED,
                 evidence-based, never a lazy SHARED fallback
```

All ten fields ARE nameable — so `ClarificationService` itself is **not**
a capability island by this definition; it is a real, connected capability
with a known consumer (`start_lifecycle()`).

The island is one level up: **nothing today supplies `start_lifecycle()`
a real `field_controls` list**, and **`create_environment.py`'s own
generation dispatch does not call `start_lifecycle()` at all** (confirmed
by direct grep of `engine.py` — `create_environment`/
`environment_mode_router` appear there only as read-only evidence-reporting
call sites). Classified:

```
TRIGGER        = UNKNOWN -- no real caller populates field_controls today
INPUT          = the real DUT/env/vip facts a project's intake would need
PRODUCER       = UNKNOWN -- no producer wired to start_lifecycle()'s own
                 field_controls parameter
CAPABILITY     = the Field-Resolution-through-EffectiveValue chain
                 (real, tested in isolation)
OUTPUT         = would be an EffectiveValue set, if triggered
CONSUMER       = start_lifecycle()'s own dispatch (real) but NOT
                 create_environment.py's generation dispatch (separate
                 call path, confirmed unconnected)
NEXT_STAGE     = Dispatch on one path; Verification Generation on the
                 other -- the two paths do not currently meet
FAILURE_PATH   = UNKNOWN -- no real caller means no real failure path has
                 ever been exercised in production
HUMAN_AUTHORITY = defined in the abstract (classify_question_owner()) but
                 never reaches a live production HumanGate this way
```

`CAPABILITY_ISLAND = YES` for this connection. Per the Connect-Before-
Expand gate: `REGISTER_AND_DEFER_WITH_OWNER` (owner: whichever wave wires
real intake `field_controls` into `start_lifecycle()` and/or converges
`create_environment.py`'s dispatch onto `run_stage()` — natural candidate
is the same wave that closes `CAP-M5M6-VLEVEL-001`, since VerificationLevel
routing and real field-control population are the same "make `start_
lifecycle()` the actual live entry point for generation" problem). Not
`SAFETY_OR_CAPABILITY_LOSS_REQUIRED` (no existing capability regresses by
deferring this), not `REQUIRED_NOW_FOR_GOLDEN_WORKFLOW` (no in-flight
wave's own closure currently depends on it).

## Measurement and owner obligations (this task's own scope)

This document does **not** attempt to classify every existing capability
against the ten-field test — that would be a full capability-island audit,
out of scope for a governance/roadmap reconciliation task. What it
establishes:

1. The ten-field test itself, as the reusable classification method.
2. One concrete, fully-worked example (above), found as a direct
   by-product of this reconciliation's own preflight (not invented to
   pad this document).
3. The obligation, going forward: any wave that closes a P0/P1 blocker
   and claims a stage `OPERATIONAL` must classify it against these ten
   fields in its own closure report, the same way `CAP-M6-CLARSVC-001`'s
   own implementation report already did for the dispatch-blocking
   mechanism.
4. `CAPABILITY_ISLANDS_IDENTIFIED` (see
   `L5DGVA_INTEGRATION_KPI_REQUIREMENTS.md`) is honestly reported as
   `1 (this reconciliation's own finding) + NOT_YET_AUDITED (remainder)`,
   never rounded up to a false "0" or down to a false "audited: none
   found."
