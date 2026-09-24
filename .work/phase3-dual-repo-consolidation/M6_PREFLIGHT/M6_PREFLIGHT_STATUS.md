# M6 Preflight Status

`M6_STATUS = PREFLIGHT`. Analysis / decision-preparation only — no
production code touched. M5 is frozen `CLOSED` at
`M5_QUALIFIED_CHECKPOINT_SHA = 789be4d1665f6c70eab90d64e30cb17db61ca7f6`.
This preflight starts from that same canonical HEAD; no file under
`dv_harness/` or `dv_harness_tests/` was modified by this task.

## M6 scope, reconciled fresh from the Master control plane

`MASTER_CAPABILITY_STATUS_MATRIX.csv`, structurally parsed
(`csv.DictReader`): **20 rows carry `PRIMARY_OWNER_WAVE == M6`.**

| Bucket | Count | IDs |
|---|---|---|
| P0 core blockers | 3 | `CAP-M6-DISPATCH-001`, `CAP-M6-CLARSVC-001`, `CAP-M5M6-VLEVEL-001` |
| P0 cross-reference (not independently counted) | 1 | `CAP-POOL-005` (see `CAP-M5M6-VLEVEL-001`) |
| Dispatch-dependent wiring (P1/P2, `SECONDARY_DEPENDENCY = CAP-M6-DISPATCH-001`) | 6 | `CAP-M3-001`, `CAP-M4.5-001`, `CAP-M6-LIFECYCLE-001`, `CAP-ATL-001`, `CAP-ATL-002`, `CAP-ATL-003`, `CAP-ATL-008` (7, see note) |
| Independent, not dispatch-dependent | 1 | `CAP-M4-002` |
| DE/DV Role-Based HITL roadmap (architecture-only this program) | 7 | `CAP-HITL-001..007` |
| VerificationLevel-dependent, low priority | 1 | `CAP-POOL-009` |

(The "6" row above lists 7 IDs — `CAP-ATL-008` was undercounted in the
first pass and corrected here; all 7 really do carry
`SECONDARY_DEPENDENCY = CAP-M6-DISPATCH-001`.) Total: 3 + 1 + 7 + 1 + 7 + 1
= 20. ✓.

**Why `CAP-M6-DISPATCH-001` is the highest-leverage of the three blockers**:
7 of the other 19 M6-owned rows name it directly as their own
`SECONDARY_DEPENDENCY` — more than any other row, including the other two
P0 blockers. Resolving it does not by itself close any of those 7, but it
removes the one open architectural question all 7 are actually waiting on.

## The three core blockers — one-line current state (detail in `M6_CORE_BLOCKER_MAP.md`)

| ID | State |
|---|---|
| `CAP-M6-DISPATCH-001` | PARTIAL — `loop()`/`run_stage()` are real, wired, operational; the INTAKE_FIRST/lifecycle-gate wrapper pattern Parent already built (`start_lifecycle()`) does not exist in canonical at all |
| `CAP-M6-CLARSVC-001` | BLOCKED — architecture already decided (M-1 D2: one `ClarificationService`); feature-level comparison + build not started |
| `CAP-M5M6-VLEVEL-001` | BLOCKED — `verification_level.py` is ABSENT from canonical (confirmed: no such file); `environment_mode_router.py` has no `IP_MODE` branch (confirmed: only `SUBSYSTEM_MODE`/`SYSTEM_LEVEL_MODE` exist) |

## Master control-plane structural validation (Section 14)

```
python -c "import csv; ..." against MASTER_CAPABILITY_STATUS_MATRIX.csv:
  ROWS = 157
  MALFORMED_ROWS = 0
  DUPLICATE_CAPABILITY_IDS = 0
  P0_COUNT (exact PRIORITY=='P0' match, respecting CAP-POOL-005's own
    disclosed cross-ref exclusion) = 5
  P0_COUNT_AMBIGUITY = 0

MASTER_WAVE_OWNERSHIP_MATRIX.csv:
  ROWS = 145
  MALFORMED_ROWS = 0
  DUPLICATE_CAPABILITY_IDS = 0
```

Both structurally clean, unchanged since the M5 Final Closure Regression's
own last check.

## What this preflight found that changes the shape of the decision

Investigating `CAP-M6-DISPATCH-001` from real code (not carried forward
from the blocker register's one-line description) found the blocker's own
`start_lifecycle(...)` naming is not a paraphrase or a hypothetical — it is
a **real, already-built method in Parent's `engine.py`**
(`DVHarness.start_lifecycle()`, ~70 lines, called from both Parent's
`cli.py` and `dashboard.py`) that canonical has never migrated. Canonical's
`cli.py`'s `start` command and `dashboard.py`'s background-run launcher
both call `DVHarness.loop()`/`.run_stage()` **directly** — the same two
methods Parent's `start_lifecycle()` itself delegates to internally via a
private `_start_dispatch()` helper, but canonical has no equivalent
unifying entry point, and no `ROUTING_STAGE`/`_intake_first_guard()`/
`_run_intake_routing_stage()` machinery inside `run_stage()` at all (all
confirmed absent by direct grep against canonical's `engine.py`). See
`M6_DISPATCH_001_HUMAN_DECISION.md` for the full evidence and the real
decision this leaves open.

## Report

```
M6_STATUS = PREFLIGHT
M6_CORE_BLOCKERS = 3
M6_FOUNDATIONS_AVAILABLE = 2   (CAP-ATL-004, CAP-ATL-007 -- both FOUNDATION_
                                 CLOSED_WITH_EXPLICIT_FUTURE_OWNER, real+tested)
M6_FOUNDATIONS_MISSING = 3     (a merged question_queue.py; an IP_MODE branch
                                 in environment_mode_router.py; M7's own build
                                 continuation for CAP-M6-CLARSVC-001)
CAP_M6_DISPATCH_001 = HUMAN_DECISION_REQUIRED
HUMAN_DECISIONS_REQUIRED = 1
M6_VERTICAL_SLICE_DEFINED = YES (see M6_OPERATIONAL_VERTICAL_SLICE.md)
M6_PRODUCTION_IMPLEMENTATION_STARTED = NO
M5_STATUS = CLOSED
REFERENCE_USB_ENV_CONSUMED = NO
NEXT_GATE = CAP-M6-DISPATCH-001 human decision (see M6_DISPATCH_001_HUMAN_DECISION.md)
```
