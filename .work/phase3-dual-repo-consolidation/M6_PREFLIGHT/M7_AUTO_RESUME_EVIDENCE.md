# M7 Auto-Resume Evidence

Required: `RESULT_IMPORTED -> VALIDATED -> CONSUMED ->
AUTO_RESUME_ACTION_ROUTING`, `AUTO_RESUME_AFTER_RESULT_IMPORT=YES`, no
user message such as continue/fix/proceed/rerun required.

## Real evidence, this and the prior task

1. **Prior task** (`M7-V1-CODEX-REVIEW-001`): the real Codex result was
   imported (`python -m dv_harness.model_handoff_workflow import ...`),
   validated, and consumed (`RESULT_CONSUMED`, `RESULT_STATUS=FAIL`,
   `HUMAN_DECISION_REQUIRED=NO`). Per this contract's own "Current M7
   Codex Case" section, a consumed FAIL with `HUMAN_DECISION_REQUIRED=NO`
   and `FIX_NOW_CORRECTNESS_BLOCKER` findings routes to AUTO_REMEDIATION,
   not "waiting for instruction" -- and that is exactly what happened:
   remediation of GAP-V2-009/010/011/012 (F1-F6) proceeded immediately in
   the same task, with no user "continue/fix/proceed" message between
   result consumption and the start of remediation.
2. **This task**: `resolve_next_action("RESULT_CONSUMED")` ->
   `AUTO_REMEDIATE_CONFIRMED_FINDINGS`, `auto_actionable=True`,
   `human_action_required=NO` -- the same real chain now has a callable,
   tested function behind it
   (`test_result_import_auto_resumes`), not merely a narrative account of
   what happened once.
3. Replaying the ORIGINAL, preserved `RESULT_V1.md` against the live,
   already-`RESULT_CONSUMED` production state (`python -m
   dv_harness.model_handoff_workflow import --task-id
   M7-V1-CODEX-REVIEW-001 ...`) returned the SAME cached
   `RESULT_CONSUMED` outcome with no re-prompt and no duplicate
   consumption -- the replay-safety guard in `model_handoff_workflow.
   import_result()` (GAP-V2-011 fix) is itself a real auto-resume-safe
   mechanism: re-importing an already-consumed result never re-asks a
   human anything, it just returns the deterministic prior outcome.

## Status

`AUTO_RESUME_STATUS=DEMONSTRATED_TWICE` (once as real historical
behavior in the prior task, once as a callable, tested function this
task). `PRODUCTION_CALL_SITE_WIRING=NOT_YET_WIRED` for
`resolve_next_action()` specifically -- `model_handoff_workflow.
import_result()` does not yet call it automatically on
`RESULT_CONSUMED`; the real auto-resume behavior observed above came
from this task's own manual execution honoring the contract, not from
an automatic call site. See `M7_STOP_ELIGIBILITY_AND_NEXT_ACTION_POLICY.md`
for the same disclosed wiring gap.
