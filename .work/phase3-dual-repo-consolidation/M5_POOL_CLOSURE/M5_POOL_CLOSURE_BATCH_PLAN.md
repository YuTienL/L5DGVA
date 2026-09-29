# M5 Pool Closure — Batch Plan

## Batch 1 (this task): CAP-POOL-008, CAP-POOL-012 — CLOSED

Per instruction item 6's explicit directive ("Begin with CAP-POOL-008,
CAP-POOL-012 because M5.9 established that both are currently
unblocked"). Both confirmed genuinely unblocked via direct dependency
read before migrating (not assumed from the M5.9 citation alone):

- `CAP-POOL-008`: one real dependency, `gates.py`'s `STAGE_GATES` dict —
  confirmed present in canonical, confirmed the module's own cited
  "12 matched/3 not matched" finding holds identically against
  canonical's own (smaller) registry.
- `CAP-POOL-012`: two real dependencies, `design_architecture_ir.py` and
  `verible_parser.py` — both confirmed present in canonical; the module
  itself is stdlib-only otherwise.

Migrated in a single commit (both capabilities are small, independent,
and unblocked — no reason to further split a 2-item batch per the
instruction's own "do not automatically implement all six in one commit"
concern, which is about NOT bulk-migrating all 6 including the 4 blocked
ones, not about splitting an already-minimal 2-item unblocked batch).

## Batch 2: CAP-POOL-001, CAP-POOL-003, CAP-POOL-004, CAP-POOL-011 — NOT ATTEMPTED THIS TASK

Dependencies recomputed after Batch 1 closed (instruction item 6's own
"After those are resolved, recompute dependencies for..." step) — see
`M5_POOL_CLOSURE_DEPENDENCY_GRAPH.md`. All 4 remain genuinely blocked on
real, named, evidenced Parent modules that are NOT among this task's 6
registered items:

- `CAP-POOL-001`/`CAP-POOL-011` share one blocker: `eight_engine_runtime_
  proof_matrix.py` (ABSENT from canonical).
- `CAP-POOL-003`/`CAP-POOL-004` share a deeper chain rooted at
  `l5dgva_gap_queue.py` (ABSENT from canonical).

Per instruction item 2's explicit scope fence ("Do not absorb unrelated
Parent modules") and item 3 ("Do not create a new architecture family"),
this task does not migrate those 4 additional dependency modules to
unblock Batch 2. This is disclosed as a genuine, evidenced remaining
obligation, not silently dropped — see
`M5_POOL_CLOSURE_DEPENDENCY_GRAPH.md`'s own recommendation for a future
dedicated task scoped to include the 4 missing dependencies.

## Order rationale (not numeric ID order)

The instruction explicitly forbids migrating in numeric ID order "merely
for convenience." This plan's order (`008`, `012` first; `001`/`003`/
`004`/`011` deferred) is entirely evidence-driven: the two migrated items
are the two the dependency graph proves are unblocked; the four deferred
items are the four the same graph proves are blocked on real, external,
out-of-scope Parent modules. Numeric ID order was never the basis for
this sequencing.
