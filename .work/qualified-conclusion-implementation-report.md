# Qualified Conclusion Implementation Report

## What was built

The AI-mechanism architecture audit found that this harness had no first-class "Qualified
Conclusion" verdict type, even though both real ingredients it needs already existed and were
wired: `dv_harness/gates.py`'s `evaluate_stage_evidence_with_detail()` (exposed via
`react_loop.py`, itself factored through `gates._evaluate_stage_evidence_core`) produces a real
per-stage gate verdict from actual `run_gate()` subprocess script invocations, and
`dv_harness/inference.py`'s `score_confidence()` independently recomputes a confidence level from
real citation counts pulled out of the agent's own evidence block -- never trusting the agent's
self-reported `confidence` field. Nothing composed the two into one object a consumer could gate
trust on.

Three things were added:

1. **`dv_harness/qualified_conclusion.py`** (new module) -- a real
   `@dataclass QualifiedConclusion(hypothesis, evidence_refs, execution_result, gate_verdict,
   inference_confidence, is_qualified)` plus the pure function
   `build_qualified_conclusion(gate_result, confidence_result, execution_evidence) ->
   QualifiedConclusion`. It follows the house DSL typed-error convention from
   `dv_harness/uvm_generator/generator.py` (`InvalidGateVerdictError`,
   `InvalidConfidenceResultError`, `InvalidExecutionEvidenceError`, each a `ValueError` subclass
   with a SCREAMING_SNAKE_CASE `reason` + a concrete `detail` dict) for genuinely malformed
   caller input, while treating a legitimate `GATE_FAIL` or `LOW`-confidence result as an ordinary,
   non-error outcome (`is_qualified=False`). `QualifiedConclusion.as_dict()` wraps
   `dataclasses.asdict` for `Blackboard.write()`.

2. **`dv_harness/engine.py` wiring** -- `_score_root_cause_confidence()` (the real RE_AUDIT
   confidence-scoring call site, previously ending at its `root_cause_confidence` Blackboard
   write around the old line 557) now also calls `build_qualified_conclusion()` with the stage's
   gate verdict, the just-computed `confidence_result`, and the same `root_cause_evidence_gate`
   evidence block already validated, then persists the result to a new `"qualified_conclusion"`
   Blackboard topic via the real `Blackboard.write()` method, and records a
   `QUALIFIED_CONCLUSION_BUILT` event (or `QUALIFIED_CONCLUSION_BUILD_FAILED` on a best-effort
   failure, mirroring every other side effect in that method -- never downgrading an
   already-earned stage PASS). The method gained an explicit `verdict: str = "PASS"` parameter
   (its one real call site in `run_stage()`, at what is now line 917, was updated to pass the
   verdict it already computed) rather than hardcoding `"PASS"` inline, so the method stays
   correct if a future caller ever invokes it from a different verdict context.

3. **`dv_harness/dashboard.py` rendering** -- the pre-existing but content-less "Hypothesis &
   Review" card (`hypothesisReviewCard`) was the one natural hook: it already exists as a
   dedicated entry point for hypothesis/review data and links to Attribution/DV Review. Added a
   `_qualified_conclusion(root)` reader (same direct-file-read pattern as the existing
   `_failure_attribution`/`_blackboard_topics` helpers), wired it into `/api/state` as
   `state["qualified_conclusion"]`, and added a small tile section to the card's JS renderer that
   labels the result **"Qualified Conclusion"** when `is_qualified` is true and **"AI Opinion (not
   yet qualified)"** when false -- plus the gate verdict, confidence level, and hypothesis text.

## Rulings made

- **RULING**: `is_qualified = True` iff `gate_verdict in ("NO_GATE_REQUIRED", "PASS")` AND
  `inference_confidence["level"] != "LOW"`, per the task spec. `QUALIFYING_GATE_VERDICTS` in the
  new module mirrors `gates.evaluate_stage_evidence()`'s own documented promotion rule ("Only
  NO_GATE_REQUIRED/PASS may promote a stage to Status.PASS") rather than being re-decided
  independently; it is a local constant (not imported from `gates.py`, which exports no such
  constant today) with an explicit comment that it must be kept in sync if that rule ever changes.
- **RULING**: `build_qualified_conclusion`'s `gate_result` parameter is the **stage-level** verdict
  string (`evaluate_stage_evidence_with_detail()`'s first return value: `PASS`/`GATE_FAIL`/etc.),
  not a single `GateSignature`'s per-gate `ok` boolean. The task's own phrasing ("gate verdict")
  and the only place this composition is actually usable inside `run_stage()` (which has the
  stage-level `verdict` string in scope, not an isolated per-gate signature) both point the same
  way; a stage can have many gates, and it is the stage's overall verdict that determines whether
  the stage promoted at all.
- **RULING**: `_score_root_cause_confidence()` gained an explicit `verdict` parameter defaulting to
  `"PASS"` instead of hardcoding the literal, since its one real caller only ever invokes it inside
  `run_stage()`'s `if verdict == "PASS":` branch today. This keeps the existing call sites and the
  three pre-existing tests in `test_inference_engine_wiring.py` (which call the method directly
  with two positional args) working unchanged, while making the method itself correct rather than
  silently wrong if a future caller ever passes a non-PASS verdict -- proven directly by a new test
  that calls it with `verdict="GATE_FAIL"` and confirms `is_qualified=False` despite HIGH-recomputed
  confidence.
- **RULING**: `hypothesis` falls back from `execution_evidence["root_cause"]` (the real
  `root_cause_evidence_gate` field name) to `execution_evidence["hypothesis"]` for forward
  compatibility with any other evidence-block shape that might compose a `QualifiedConclusion` in
  the future, then to `""` if neither is present -- never raises on a sparse/empty block, since an
  empty hypothesis with `is_qualified=True` is still meaningful data (a stage passed with high
  confidence but genuinely produced no root-cause text).
- **RULING**: `evidence_refs` is built the same citation-normalization rule
  `engine.py::_score_root_cause_confidence._cite_count()` already uses (list -> its items, dict ->
  its values, truthy scalar -> one-item list, falsy -> empty), applied to both
  `supporting_evidence` and `causal_chain`, rather than a new ad hoc scheme -- keeps the new
  module's semantics identical to the existing, already-reviewed counting logic it sits next to.
- **RULING**: the dashboard hook is additive-only inside the existing `hypothesisReviewCard` (new
  `_qualified_conclusion()` reader function, new `state["qualified_conclusion"]` key, new
  `qualtiles` div + its render block) rather than a new top-level card, per the task's "don't force
  it if there's no clean hook" guidance -- this card was already a purpose-built, empty pointer for
  exactly this kind of hypothesis/verdict data.

## Tests

New file `dv_harness_tests/test_qualified_conclusion.py` (34 tests, all passing):
- The three task-specified scenarios directly: PASS+HIGH -> qualified; GATE_FAIL -> not qualified
  regardless of confidence (tested at HIGH); PASS+LOW -> not qualified.
- A full boundary sweep: every `QUALIFYING_GATE_VERDICTS` value crossed with HIGH/MEDIUM (always
  qualified) and LOW (never qualified), and every non-qualifying verdict crossed with all three
  confidence levels (never qualified).
- Field composition: hypothesis fallback, `execution_result` is a real copy (never the same object,
  never mutated), `evidence_refs` normalization across list/dict/scalar shapes, empty-evidence
  behavior, `as_dict()` JSON-serializability.
- Typed-error paths: unknown gate verdict, malformed/non-dict confidence result, non-dict execution
  evidence -- each raising its specific typed error with the expected `reason`/`detail`.
- Real `engine.py` wiring: `DVHarness._score_root_cause_confidence()` actually persists a
  `qualified_conclusion` Blackboard record on both a HIGH-confidence PASS and a LOW-confidence
  PASS (the "AI Opinion" case), records the `QUALIFIED_CONCLUSION_BUILT` event, stays a no-op when
  no `root_cause_evidence_gate` block is present (matching the existing backward-compatibility
  contract for `root_cause_confidence`), and correctly reports `is_qualified=False` when called
  with an explicit non-default `verdict="GATE_FAIL"` despite independently-recomputed HIGH
  confidence.

Full existing suite run for regressions: `python -m pytest dv_harness_tests/` -- **1507 passed**,
0 failed, 0 skipped, ~10 minutes. A targeted subset
(`test_inference.py`, `test_inference_engine_wiring.py`, `test_engine_gates_and_routing.py`,
`test_dashboard_interactive.py`) was also run in isolation first (273 passed) to get faster
feedback before the full run. No pre-existing test needed modification; no pre-existing bug was
found during this work.

## Concerns / residual gaps

- The real `run_stage()` call site only ever invokes `_score_root_cause_confidence()` (and
  therefore only ever builds a `QualifiedConclusion`) when the stage's own gate verdict is already
  `PASS` (see the `if verdict == "PASS":` guard around the call). So in practice, today, every
  wired `qualified_conclusion` Blackboard record will have `gate_verdict="PASS"` and the only
  variable left to determine `is_qualified` is the confidence level -- the `GATE_FAIL` branch of
  `build_qualified_conclusion()` is real, tested, and reachable (both as a direct unit-test call
  and via the `verdict` parameter's non-default use), but is not yet exercised by any live
  non-test code path. This matches the actual current shape of `run_stage()`'s control flow rather
  than a gap in the new code: a `GATE_FAIL`/`DV_REVIEW_PENDING`/etc. stage attempt never reaches
  this method at all today, so there is nothing to compose. If a future change wires this into a
  broader call site (e.g. surfacing a `QualifiedConclusion` for a stage that did NOT reach PASS),
  the pure function is already correct for that case with no further work needed.
- `QualifiedConclusion` is currently produced only for RE_AUDIT's `root_cause_evidence_gate`
  finding (the one stage that already had `score_confidence()` wired per the 2026-08-28
  architecture audit). Extending this to other hypothesis-producing stages/gates was out of scope
  for this task (the task named exactly this one real call site) and is a reasonable, low-risk
  future extension of `build_qualified_conclusion()` itself, which takes no RE_AUDIT-specific
  parameters.
- The dashboard rendering is a minimal tile addition (verdict label, gate verdict, confidence
  level, hypothesis text) rather than a rich dedicated visualization -- consistent with the
  existing "Hypothesis & Review" card's own minimal-pointer style, and with the task's explicit
  "don't force it" guidance.
