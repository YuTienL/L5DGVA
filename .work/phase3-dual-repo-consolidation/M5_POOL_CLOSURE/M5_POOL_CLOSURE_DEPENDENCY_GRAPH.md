# M5 Pool Closure — Dependency Graph

## The six-capability graph

```
CAP-POOL-008 (l5dgva_v5_ss84_phase_entry_protocol_schema.py)
  depends on: gates.py (PRESENT in canonical)
  status: UNBLOCKED

CAP-POOL-012 (rtl_filelist_parser.py)
  depends on: design_architecture_ir.py (PRESENT), verible_parser.py (PRESENT)
  status: UNBLOCKED

CAP-POOL-001 (engine_maturity_state.py)
  depends on: eight_engine_runtime_proof_matrix.py (ABSENT from canonical)
  status: BLOCKED_BY_EXISTING_CANONICAL_FOUNDATION -- more precisely,
          blocked by a MISSING canonical foundation (a real Parent module
          not yet migrated, not registered as one of this task's 6 items)

CAP-POOL-011 (eight_engine_telemetry_rollup.py)
  depends on: loop_telemetry.py (PRESENT), eight_engine_runtime_proof_matrix.py (ABSENT)
  status: same blocker as CAP-POOL-001 (shared dependency)

CAP-POOL-003 (l5dgva_directive_blackboard_work_queue.py)
  depends on: blackboard.py (PRESENT), l5dgva_directive_registry.py (ABSENT)
  l5dgva_directive_registry.py depends on: l5dgva_workitem_projection.py (ABSENT)
  l5dgva_workitem_projection.py depends on: l5dgva_gap_queue.py (ABSENT)
  status: BLOCKED, 3-level chain

CAP-POOL-004 (l5dgva_kc_extraction.py)
  depends on: l5dgva_gap_queue.py (ABSENT -- same root as CAP-POOL-003's chain)
  status: BLOCKED, shares its root dependency with CAP-POOL-003
```

## Classification (instruction item 5 vocabulary)

| ID | Classification | Mandatory UNKNOWN? |
|---|---|---|
| `CAP-POOL-008` | `UNBLOCKED` | No -- resolved this task |
| `CAP-POOL-012` | `UNBLOCKED` | No -- resolved this task |
| `CAP-POOL-001` | `BLOCKED_BY_FUTURE_WAVE` (its missing dependency is a real, un-migrated Parent module outside this task's registered 6-item scope -- migrating it requires a NEW capability registration, not something this task can absorb per instruction item 2) | No -- the blocker itself is known, named, and evidenced; not an UNKNOWN |
| `CAP-POOL-011` | `BLOCKED_BY_FUTURE_WAVE` (identical blocker to POOL-001) | No |
| `CAP-POOL-003` | `BLOCKED_BY_FUTURE_WAVE` (3-level chain, all missing dependencies real/named/evidenced) | No |
| `CAP-POOL-004` | `BLOCKED_BY_FUTURE_WAVE` (shares its root with POOL-003's chain) | No |

No capability in this batch is `UNKNOWN` — every blocker is a real, named,
evidenced Parent module confirmed absent from canonical via direct
search, not a gap in this investigation's own knowledge.

## The dependency graph's real shape: a shared missing-foundation cluster

```
eight_engine_runtime_proof_matrix.py (ABSENT)
  <- CAP-POOL-001 (engine_maturity_state.py)
  <- CAP-POOL-011 (eight_engine_telemetry_rollup.py)

l5dgva_gap_queue.py (ABSENT, self-contained)
  <- l5dgva_workitem_projection.py (ABSENT)
       <- l5dgva_directive_registry.py (ABSENT)
            <- CAP-POOL-003 (l5dgva_directive_blackboard_work_queue.py)
  <- CAP-POOL-004 (l5dgva_kc_extraction.py) [direct]
```

This is new evidence from this task, not previously known: **migrating
`eight_engine_runtime_proof_matrix.py` once unblocks both POOL-001 and
POOL-011; migrating `l5dgva_gap_queue.py` once unblocks POOL-004 directly
and is the root of POOL-003's own 3-level chain.** A future dedicated
task scoped to include these 3 additional Parent modules
(`eight_engine_runtime_proof_matrix.py`, `l5dgva_gap_queue.py`,
`l5dgva_workitem_projection.py`, `l5dgva_directive_registry.py` -- 4
modules, not 3; corrected count) could close all 4 remaining POOL items
in one coordinated effort, rather than 4 separate investigations.

## Why this task does not migrate those 4 missing dependencies itself

Instruction item 2's explicit scope fence: "Scope is limited to:
CAP-POOL-001/003/004/008/011/012... Do not absorb unrelated Parent
modules." `eight_engine_runtime_proof_matrix.py`, `l5dgva_gap_queue.py`,
`l5dgva_workitem_projection.py`, and `l5dgva_directive_registry.py` are
none of the 6 registered items -- migrating them here would be exactly
the scope creep the instruction forbids, however tempting the "just one
more file" logic might be. They are disclosed as a real, evidenced,
actionable next step for a future task, not migrated now.
