# Gap-close pass: AI mechanism #9 — Evidence-Grounded AI (Hypothesis + Evidence + Result + Gate = Conclusion)

**Date:** 2026-09-04
**Verdict:** NO_ACTION_NEEDED
**Code changed:** none
**Test summary:** re-ran the cited suites for real — `test_qualified_conclusion_closure_gate.py` **8 passed in 381.30s** (drives real `DVHarness.run_stage("RE_AUDIT")` through all 11 real gate subprocesses), plus `test_qualified_conclusion.py` + `test_root_cause_evidence_gate.py` **45 passed in 23.84s**.

## Why no action

The audit reported WIRED_AND_FIRING with no real gap named. I re-verified every cited
piece of evidence myself rather than trusting the audit text or CLAUDE.md's own claims.
All of it holds.

### The four ingredients, re-verified independently

1. **Hypothesis + Evidence (structural, not a boolean).**
   `tools/verification_flow/root_cause_evidence_gate.py` is registered as a real
   subprocess gate on every `RE_AUDIT` attempt — confirmed by reading
   `dv_harness/gates.py`'s `STAGE_GATES["RE_AUDIT"]`, whose first entry is
   `("root_cause_evidence_gate", "root_cause_evidence_gate.py", "--root-cause")`.
   The three structural refusal codes the audit named are real and present in the
   script: `INSUFFICIENT_HYPOTHESES` (line 154), `ROOT_CAUSE_NOT_IN_HYPOTHESES`
   (line 190), `NO_ALTERNATIVE_HYPOTHESIS_REFUTED` (line 199), each a `FAIL` status
   feeding a real `sys.exit(main())` (line 207) — exit-code-driven, not a "gate ran" flag.

2. **Execution result.**
   `dv_harness/qualified_conclusion.py`'s `QualifiedConclusion.execution_result` is
   populated with `dict(execution_evidence)` — the actual evidence-block dict the gate
   validated, not a summary. Its docstring states this traceability requirement explicitly.

3. **Hard Gate.**
   `dv_harness/engine.py:1759` — `qc = build_qualified_conclusion(verdict, confidence_result, block)`,
   reached only from `_score_root_cause_confidence()`, whose sole call site is
   `engine.py:3652`, sitting inside the `if verdict == "PASS":` branch (line 3639) —
   i.e. only on a genuine gate-verified PASS. `is_qualified` requires both a
   promotion-worthy gate verdict (`QUALIFYING_GATE_VERDICTS`) **and** a non-LOW level
   from `inference.score_confidence()`, which recomputes from real citation counts and
   never reads the agent's self-reported `confidence` field.

4. **Structural prevention of reaching CLOSED without it.**
   `dv_harness/policy.py`'s `can_signoff()` returns `False` when a recorded
   `qualified_conclusion` says `is_qualified: false`. Its one production caller is
   `engine.py:4315`, inside `loop()` under `if stage == Stage.SIGNOFF.value:` — and
   critically it runs **before** the `result = self.run_stage(user_goal)` on the next
   line, so a refusal means the SIGNOFF stage agent is never dispatched at all.

### Independent checks I performed (not taken from the audit or CLAUDE.md)

- **Re-derived the graph check from the shipped JSON myself.** Loaded
  `.dv-harness/graph/main_graph.json` (nodes are keyed `id`, not `stage`) and confirmed
  `qualified_conclusion` appears in `blackboard_read` for `REQUIREMENT_CLOSURE`,
  `PROMOTION_READINESS` and `SIGNOFF` — `True / True / True`. Also confirmed exactly one
  edge into SIGNOFF: `{'source': 'PROMOTION_READINESS', 'target': 'SIGNOFF', 'condition': 'PASS'}`.
- **Ran the real closure suite** rather than trusting the audit's number: 8 passed in
  381.30s. The slow runtime is itself evidence it drives real gate subprocesses.
- **Verified the zero-dispatch assertion is real**, not a return-value check:
  `test_loop_refuses_signoff_while_the_recorded_conclusion_is_not_qualified` asserts
  `adapter.calls == []` with the message "SIGNOFF must never have been dispatched", and
  separately pins that `require_second_pass_audit` is *not* what stopped it
  (`RE_AUDIT` status is asserted `PASS`, and `can_signoff(state, cfg)` without the
  blackboard is asserted `True` while `can_signoff(state, cfg, blackboard)` is `False`).
- **Confirmed the tests are not self-referential fixtures**: the RE_AUDIT gate payloads
  are imported from `test_inference_engine_wiring` (`_install_re_audit_gates`,
  `_re_audit_pass_text`, `_root_cause_evidence_gate_block`) rather than copied, so they
  cannot drift from the gate scripts.
- **Bypass-path search**: no `exemptions.yaml` exists in the repo (only a schema), and no
  exemption entry for `root_cause_evidence_gate` anywhere under `.dv-harness/` — the only
  matches are memory records and the `hard_gate_registry.json` entry that registers it.

## Residuals examined and deliberately not "fixed"

Two narrowings exist. Neither is a defect in this mechanism's wiring, and changing either
would have been out of scope for a gap-close pass.

1. **`can_signoff()` refuses only on a record that exists and says `is_qualified: false`.**
   A project that never wrote one is not blocked by this specific check (it is still gated
   by the separate, pre-existing `require_second_pass_audit`). This is a deliberate scoping
   decision, disclosed in a long comment in `policy.py` and asserted by its own test,
   `test_absence_of_a_conclusion_record_is_not_a_refusal` — blocking on absence would make
   every pre-existing project unclosable.

2. **`dv-harness run-stage <STAGE>` (`cli.py:2609`) calls `run_stage()` directly and so does
   not consult `can_signoff()`.** I checked whether this was a #9-specific hole and it is
   not: that manual path bypasses *all four* of `can_signoff()`'s checks, including the
   pre-existing `require_exact_server_sha`, `require_all_actionable_findings_closed` and
   `require_second_pass_audit`. It is a pre-existing, architecture-wide property of the
   deliberate human-driven single-stage escape hatch (the same category as `set-stage` and
   `mark`, which also let a human set status directly), not a gap introduced by or specific
   to this mechanism. Closing it would change the semantics of that escape hatch for four
   unrelated policy checks — a separate design decision, not this mechanism's wiring.

The existing kill-switch `policy.require_qualified_conclusion` (default `True`) is covered
by its own test, `test_require_qualified_conclusion_false_disables_the_check`.

## Files touched

None. No commit made — there is no code change to commit for this mechanism.

Note for the pass coordinator: `dv_harness/engine.py` carries uncommitted changes from
other concurrent workstreams (203 insertions / 114 deletions at the time of this pass). I
confirmed via `git diff` that **none** of those hunks touch `build_qualified_conclusion`,
`qualified_conclusion` or `can_signoff`, so this mechanism's wiring is unaffected by the
concurrent edits and my verification reflects current tree state.
