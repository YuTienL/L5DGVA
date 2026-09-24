# M7 Auto-Remediation Eligibility

Real code: `dv_harness/result_action_router.py::evaluate_auto_remediation_eligibility()`,
`RemediationCandidate`, `REJECT_REASONS`. Tests:
`dv_harness_tests/test_result_action_router.py` (eligibility section,
9 tests covering all 6 reject reasons individually + the 3 default
auto-eligible dispositions + the unknown-disposition rejection).

## Default eligible dispositions

`DEFAULT_AUTO_ELIGIBLE_DISPOSITIONS = {FIX_NOW_CURRENT_SCOPE,
FIX_NOW_CORRECTNESS_BLOCKER, FIX_NOW_CAPABILITY_LOSS}` -- matches the
dispatch's own default candidate list exactly. `FIX_NOW_SAFETY_SECURITY`
is a real `FIX_NOW_*` disposition but is deliberately excluded and always
routes to `HUMAN_GATE_REQUIRED` in `route_action()`, regardless of what
`auto_eligible_dispositions` set a caller passes.

## Reject reasons (any ONE forces HUMAN_GATE_REQUIRED)

`REQUIRES_HUMAN_AUTHORITY`, `PROTECTED_ARCHITECTURE_CHANGE`,
`SCOPE_EXPANSION`, `SECURITY_EXPANSION`, `FROZEN_SOURCE_MODIFICATION`,
`NEW_HUMAN_DECISION`. These are real, caller-supplied booleans on
`RemediationCandidate` -- this module never infers them from a finding's
prose/severity text; a caller (the per-task findings-table producer) is
responsible for setting each one from real evidence about the SPECIFIC
fix a finding needs, matching the Prime Directive V2 P6 safety invariants
(`AUTO_BYPASS_HUMAN_AUTHORITY=NO`, etc.).

## Applied to this task's own GAP-V2-009/010/011/012

All four gaps/six findings (F1-F6) were, in retrospect, real
`FIX_NOW_CORRECTNESS_BLOCKER` dispositions with all six eligibility
booleans `False`:

- not `requires_human_authority` -- a validation-tightening bug fix, no
  new human decision authority needed
- not `is_protected_architecture_change` -- the HANDOFF_V1/RESULT_V1
  Markdown contract shape itself is unchanged; only parsing/validation
  strictness changed
- not `is_scope_expansion` -- fix stayed inside the four
  `ALLOWED_FILES` the original Codex handoff declared, plus its own test
  file
- not `is_security_expansion` -- closes real bypasses, does not add new
  privileged capability
- not `modifies_frozen_source` -- none of the 5 frozen reference sources
  (parent/v50/b7a/b7b/b8) were touched (re-verified unchanged this task)
- not `raises_new_human_decision` -- no new `HUMAN_DECISION_REQUIRED`
  surface was introduced

All six would therefore have classified `AUTO_REMEDIATION_ELIGIBLE` had
`route_action()` existed and been wired at the time -- consistent with,
not contradicting, the manual P5 FIND->FIX->VERIFY execution this task
actually used (see `M7_AUTONOMOUS_REMEDIATION_EVIDENCE.md`).

## Status

`AUTO_REMEDIATION_ELIGIBILITY_STATUS=WIRED_AND_TESTED`,
`PRODUCTION_CALL_SITE_WIRING=NOT_YET_WIRED` (same honest status as
`M7_RESULT_TO_ACTION_ROUTING.md` -- the two are the same module).
