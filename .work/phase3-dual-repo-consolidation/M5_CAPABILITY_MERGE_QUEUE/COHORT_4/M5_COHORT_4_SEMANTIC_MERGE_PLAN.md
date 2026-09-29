# M5 Cohort 4 — Semantic Merge Plan

## task_boundary_conformance.py

**Decision: migrate essentially verbatim, with one disclosed docstring
correction.** The module is entirely self-contained beyond two functions
(`change_impact._git()`, `change_impact.resolve_sha()`), both confirmed
byte-identical between Parent and canonical in their shared prefix (the
only diff between the two `change_impact.py` files is an ADDITIVE tail
section in canonical, after the shared functions). No algorithm change of
any kind.

The one deliberate edit: the module's own docstring point 3 (originally
"It is not wired into any stage gate, engine.py or cli.py") is corrected,
because real Parent evidence found this Cohort shows it IS wired there
(`cli.py`'s `task-boundary-conformance` verb) — carrying the stale claim
into canonical would misrepresent Parent's own current state. The
corrected docstring instead honestly states canonical's OWN status (not
wired, deliberately, pending `CAP-M6-DISPATCH-001`) and cites the real
Parent wiring as the reason CLI replication was considered and rejected
this Cohort.

**Tests**: ported verbatim (19/19, self-contained, no adaptation needed —
every test builds its own throwaway git repo in `tmp_path`).

**Not done this Cohort**: no `cli.py` verb, no gate wiring, no `engine.py`
hook — all explicitly deferred to `CAP-M6-DISPATCH-001`.

## intake_field_resolution.py

**Decision: adapt, not blind-copy.** Two deliberate departures from
Parent, both disclosed in the migrated module's own docstring and in
`M5_COHORT_4_SOURCE_BEHAVIOR_MATRIX.csv`:

1. `OPENSPEC_FIELD_ATTRIBUTES` is defined locally in the canonical module
   (value verified identical to Parent's real constant) rather than
   imported from Parent's `irq_openspec_preflight_gate.py` (905 lines,
   out of scope).
2. `CLOSED_TECHNICAL_GAPS["STRUCTURED_CLARIFICATION_CONTEXT_NOT_
   PERSISTED"]` is re-classified to `KNOWN_TECHNICAL_GAPS` (OPEN) in
   canonical, because its Parent-side closure depends on
   `intake_clarification.py`/`intake_resume.py`, neither of which exists
   in canonical.

Every dataclass, enum, and the `_decide()` resolution algorithm itself are
ported with **zero logic changes** — verified by re-running the identical
(ported) test assertions and getting identical pass/fail results in both
trees.

**Not done this Cohort** (per explicit instruction):
- No reconciliation with canonical's existing `intake_state.
  IntakeFieldRecord`/`IntakeFieldStatus` model — both now coexist as two
  real, separate, unlinked systems. Reconciling or routing new work
  through the richer model is M6's job (`ClarificationService`).
- No `ClarificationService` implementation.
- No wiring into any canonical caller — the module has zero canonical
  callers as of this migration, same FOUNDATION status as `CAP-VELM-*`
  capabilities before their own owner wave builds on them.
- Parent's 9 sibling intake-pipeline modules are not touched, read in
  full, or migrated.

## Capability-loss check

Every one of Parent's 8 OpenSpec attributes, every enum value, every
resolution-algorithm branch, and every real test assertion survives the
port unchanged. `SOURCE_CAPABILITY_LOSS = 0` for the ported ALGORITHM
content. The two disclosed departures are deliberate SCOPE adaptations
(dropping a Parent-only 905-line dependency; correcting a false
already-closed claim), not capability loss.

## What M6 inherits from this Cohort (forward-looking, not implemented here)

A real, tested, evidence-grounded field-resolution contract
(`intake_field_resolution.py`) and a real, tested, evidence-grounded
task-scope contract (`task_boundary_conformance.py`), both importable and
both compatible with the DE/DV Role-Based HITL model (task boundary) and
the OpenSpec 8-field contract (field resolution) — ready for M6 to wire
into `ClarificationService`/`cli.py` dispatch once those are built, without
needing to re-derive either contract's semantics from Parent again.
