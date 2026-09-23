# M5 Capability Pool Closure — Final Report

Closure-debt recovery discovered by M5.9, not a new roadmap cohort.

```
M5_STATUS = IN_PROGRESS
M5_POOL_CLOSURE_STATUS = PARTIAL (2 of 6 closed; 4 remain OPEN,
            correctly not force-closed)

START_HEAD = 4bf5080
END_HEAD = <set by this task's own commit, see git log>

CAP_POOL_001 = OPEN (blocked on eight_engine_runtime_proof_matrix.py, out of scope)
CAP_POOL_003 = OPEN (blocked on a 3-level chain, out of scope)
CAP_POOL_004 = OPEN (blocked on l5dgva_gap_queue.py, out of scope)
CAP_POOL_008 = CLOSED (migrated, 9/9 tests pass)
CAP_POOL_011 = OPEN (blocked on eight_engine_runtime_proof_matrix.py, shared with CAP-POOL-001)
CAP_POOL_012 = CLOSED (migrated, 28/28 new tests pass)

CAP_POOL_CAPABILITIES_REVIEWED = 6
CAP_POOL_CAPABILITIES_MIGRATED = 2 (CAP-POOL-008, CAP-POOL-012)
CAP_POOL_CAPABILITIES_SUPERSEDED = 0
CAP_POOL_FOUNDATION_CLOSED = 0 (both closures are full CLOSED, not FOUNDATION_CLOSED --
            neither had a Cohort-4-style "real M6 wiring owner" pattern;
            both are simply unwired-by-design, same posture as their
            Parent source)
CAP_POOL_OPEN = 4
CAP_POOL_UNKNOWN = 0

M5_CAPABILITIES_OPEN = 4 (down from 6 after M5.9)
M5_CAPABILITIES_UNKNOWN = 0

CALLERS_ANALYZED = 9 (2 own-module + 2 own-test-file + gates.py dependency +
            design_architecture_ir.py/verible_parser.py cited-future-consumers +
            .claude/skills + graph.py/engine.py zero-match checks)
PUBLIC_SIGNATURE_BREAKS_UNRESOLVED = 0
SOURCE_CAPABILITY_LOSS = 0

REGRESSION_CAUSED_BY_POOL_CLOSURE = 0
UNKNOWN_REGRESSION_FAILURES = 0
            (349 individual test results across all regression steps,
            0 failures -- see M5_POOL_CLOSURE_TEST_EVIDENCE.md)

MASTER_CAPABILITY_MATRIX_ROWS = 133 (excl. header)
MASTER_CAPABILITY_MATRIX_MALFORMED_ROWS = 0
MASTER_CAPABILITY_MATRIX_DUPLICATE_IDS = 0

AUTHORITATIVE_MASTER_P0_BLOCKER_COUNT = 5 (unchanged)
M6_CORE_BLOCKERS = 3 (unchanged)

M5_READY_FOR_FINAL_CLOSURE_REGRESSION = NO

NEXT_RECOMMENDED_GATE = a dedicated future task registering and
            migrating the 4 newly-identified missing dependency modules
            (eight_engine_runtime_proof_matrix.py, l5dgva_gap_queue.py,
            l5dgva_workitem_projection.py,
            l5dgva_directive_registry.py), which this task's own
            dependency-graph finding shows would close all 4 remaining
            CAP-POOL items together

M5_FINAL_REGRESSION_STARTED = NO
M6_STARTED = NO
M10_5_STARTED = NO
M14_STARTED = NO

REFERENCE_USB_ENV_CONSUMED = NO
```

## What this task actually closed

**`CAP-POOL-008`** (`l5dgva_v5_ss84_phase_entry_protocol_schema.py`):
migrated verbatim. Its one real dependency (`gates.py`'s `STAGE_GATES`
dict) was already present in canonical. The module's own cited
STAGE_GATES-name-coverage finding (12 of 15 material phases matched) was
independently re-derived against canonical's own smaller registry (4
fewer gate entries than Parent's) before trusting it — confirmed
identical, not assumed.

**`CAP-POOL-012`** (`rtl_filelist_parser.py`): migrated verbatim from its
only real source location — an UNTRACKED file in B7A's own worktree,
disclosed provenance caveat and all. Both real dependencies
(`design_architecture_ir.py`, `verible_parser.py`) were already present
in canonical. No test file existed anywhere for this module; a brand-new
28-test suite was authored from its own documented `.f` syntax support,
independently confirming the module behaves exactly as its own
docstring claims.

## What remains genuinely open, and why

`CAP-POOL-001`/`CAP-POOL-003`/`CAP-POOL-004`/`CAP-POOL-011` are real,
un-migrated Parent code, each blocked on a real, named, evidenced Parent
dependency module that is itself absent from canonical and outside this
task's registered 6-item scope. This task's own dependency-graph
analysis found new, actionable evidence: the 4 blockers reduce to just 2
underlying missing modules
(`eight_engine_runtime_proof_matrix.py` blocks `POOL-001`+`POOL-011`;
`l5dgva_gap_queue.py` roots the chain blocking `POOL-003`+`POOL-004`) —
migrating those 2 (plus 2 intermediate chain modules for `POOL-003`)
in a future dedicated task would close all 4 remaining items together.

This task deliberately did **not** migrate those 4 additional
dependency modules — doing so would have violated the explicit scope
fence ("Scope is limited to: CAP-POOL-001/003/004/008/011/012... Do not
absorb unrelated Parent modules").

## Required artifacts (all 8 produced)

1. `M5_POOL_CLOSURE_CAPABILITY_MAP.csv`
2. `M5_POOL_CLOSURE_DEPENDENCY_GRAPH.md`
3. `M5_POOL_CLOSURE_SOURCE_BEHAVIOR_MATRIX.csv`
4. `M5_POOL_CLOSURE_CALLER_SWEEP.csv`
5. `M5_POOL_CLOSURE_BATCH_PLAN.md`
6. `M5_POOL_CLOSURE_TEST_EVIDENCE.md`
7. `M5_POOL_CLOSURE_FINAL_REPORT.md` (this file)
8. `M5_FINAL_PRE_CLOSURE_AUDIT.md`

## STOP

Per standing instruction: do not start the M5 final regression
automatically. `M5_STATUS` remains `IN_PROGRESS`. Do not start M6,
M10.5, or M14.
