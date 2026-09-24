# M7 Autonomous Remediation Evidence

Honest accounting of HOW GAP-V2-009/010/011/012 (Codex F1-F6) were
actually remediated in this task, since the P6 infrastructure
(`dv_harness/result_action_router.py`) that would formally classify and
gate this loop was built partway through the same task.

## What actually ran

1. Each of F1-F6 was independently reproduced with a real Python probe
   against the current code (never trusted from Codex's own claim).
2. Each was fixed with a minimal, targeted code change (git commit
   `740fbe6`).
3. A real regression false-positive was discovered DURING remediation
   (the GAP-V2-010 `RETURNED_ARTIFACTS` scope-check extension rejected
   the original, already-consumed, legitimate Codex `RESULT_V1.md`
   because it self-cites its own storage path) and closed with a
   principled, narrow, caller-derived exemption -- not by weakening the
   fix (`test_unrelated_forbidden_returned_artifact_still_rejected_
   despite_self_reference_exemption` proves the exemption does not
   reopen the bypass for any other path).
4. 16 new adversarial regression tests were added (closing F7).
5. Full related suite (`model_handoff`/`model_result`/`task_boundary`,
   93 tests) + the full `test_model_handoff_v1.py` file (51 tests) +
   the new `test_result_action_router.py` (30 tests) all pass.
6. Constitution gate PASS (re-run after each commit). All 5 frozen
   reference sources re-verified unchanged before each commit.
7. Gap Register CSV updated: GAP-V2-009/010/011/012 all CLOSED with
   real `ROOT_CAUSE`/`FIX`/`TEST_REF` evidence, CSV structural integrity
   re-checked (0 malformed rows, 0 duplicate IDs).
8. A real Codex re-review handoff (`M7-V1-CODEX-REVIEW-002`) was
   generated and reached `WAITING_FOR_HUMAN_TRANSPORT` -- the genuine
   stop condition for this sub-task.

## What did NOT run

This was executed as direct, manual Prime Directive V2 **P5**
FIND->FIX->VERIFY -- not through the **P6** `result_action_router.py`
module's own `route_action()`/`check_loop_termination()`/
`append_iteration_trace()` machinery, because that module was built
DURING this same task (after the F1-F6 fixes already landed) as the
reusable infrastructure future autonomous remediation should run
through. Concretely:

- No `LoopBudget`/`LoopTerminationPolicy` governed this remediation in
  real time -- there was no risk of budget exhaustion in practice (6
  findings, 2 commits, no repeated-failure/repeated-finding pattern),
  but no code path actually checked that.
- The 6 `IterationTrace` records in
  `.dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-001/loop_evidence_trace.jsonl`
  were written AFTER the fact (once the module existed), from the real,
  already-verified facts of the completed work -- not recorded live,
  iteration by iteration, by an autonomous loop.
- `route_action()` was never actually invoked against F1-F6's real
  dispositions during the fix; `M7_AUTO_REMEDIATION_ELIGIBILITY.md`
  shows what it WOULD have returned (all 6 `AUTO_REMEDIATION_ELIGIBLE`),
  computed and verified after the fact, not as a live gate.

## Why this is disclosed rather than reframed

Per the Evidence Truth Rule and this project's own "never fabricate to
hit 100%" standing instruction: claiming this remediation was driven
live by infrastructure that did not yet exist when the remediation
happened would be a false claim. The real, verifiable facts are: the
defects are genuinely fixed and tested; the NEW P6 infrastructure is
real, tested, and demonstrated once against this task's own real data;
and the infrastructure is not yet the thing that actually drove this
particular remediation. `PRODUCTION_CALL_SITE_WIRING=NOT_YET_WIRED` is
the accurate status for `result_action_router.py`, consistently repeated
in `M7_RESULT_TO_ACTION_ROUTING.md`, `M7_AUTO_REMEDIATION_ELIGIBILITY.md`,
`M7_LOOP_TERMINATION_AND_BUDGET_POLICY.md`, and `M7_LOOP_EVIDENCE_TRACE.md`.

## Next required step (not done in this task)

Wire a real call site -- most naturally inside
`model_handoff_workflow.import_result()`'s post-consumption path, or a
new `process_findings()` helper in `result_action_router.py` itself --
that: (a) turns a consumed result's `FINDINGS` into real
`RemediationCandidate`s, (b) calls `route_action()`, (c) for each
`AUTO_REMEDIATION_ELIGIBLE` finding runs the real P5 loop under
`check_loop_termination()`'s live governance, and (d) calls
`append_iteration_trace()` once per real iteration, live. Until that
call site exists, this module is real, tested, correct infrastructure
that is not yet load-bearing in production -- per the Methodology
Consolidation Rule, that wiring gap is registered here rather than
silently left implicit.
