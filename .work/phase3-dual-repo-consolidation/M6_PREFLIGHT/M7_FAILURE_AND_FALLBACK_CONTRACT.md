# M7 V1 -- Failure and Fallback Contract

Supersedes the M7 Preflight's own `M7_FAILURE_AND_FALLBACK_CONTRACT.md`
(design-only) with REAL, tested code -- every failure class dispatch
section 20 names, plus this project's own required M6-pattern reuse
(degrade-never-raise, real structured errors, never a silent PASS).

## Failure classes, real behavior, real test

| Failure class | Real behavior | Test |
|---|---|---|
| Missing result | `RESULT_FILE_UNREADABLE`, `RESULT_REJECTED`, never a crash | `test_missing_result_file_is_a_real_rejection_not_a_crash` |
| Malformed Markdown | `ResultParseError("NOT_A_RESULT_DOCUMENT")` before validation ever runs | `test_malformed_markdown_is_a_real_parse_error_not_a_silent_default` |
| Wrong Task ID | `task_id_validated=False`, `ValidationOutcome.accepted=False` | `test_task_id_mismatch_is_not_accepted` |
| Wrong producer | `producer_validated=False` | `test_producer_mismatch_is_not_accepted` |
| Incompatible task type | `task_type_validated=False` (exact-match only, never "close enough") | `test_incompatible_task_type_is_not_accepted` |
| Invalid schema | `ResultParseError("MISSING_REQUIRED_FIELDS")` / `("INVALID_RESULT_STATUS")` | `test_missing_required_result_fields_is_a_real_parse_error`, `test_invalid_result_status_is_a_real_parse_error` |
| Forbidden file reference | `scope_validated=False`, `scope_violations` names the exact path+classification | `test_scope_violation_is_not_accepted`, `test_forbidden_file_reference_is_flagged_even_if_also_plausible` |
| Missing evidence | `evidence_validated=False` whenever real claims/findings exist with zero `evidence_refs` | `test_missing_evidence_for_real_claims_is_not_accepted` |
| Unavailable target model | `HandoffBuildError("INVALID_TARGET_MODEL")` at BUILD time (never even reaches export) | `test_build_handoff_rejects_invalid_target_model` |
| Disagreement | Not auto-resolved -- `COUNTER_EVIDENCE`/`UNKNOWN_ITEMS` preserved verbatim through parse/validate/consume; never majority-voted (no vote-counting code exists anywhere in `model_result.py`) | structural (no code path resolves disagreement; `CLAIMS` vs `COUNTER_EVIDENCE` stay separate fields end to end) |
| Human copy/paste error | Surfaces as one of the above (malformed Markdown, wrong Task ID, etc.) -- there is no SEPARATE "human error" code path, by design: a human's mistake and a model's own malformed output are indistinguishable to, and handled identically by, the real ingestion pipeline | same tests as the corresponding failure class |

```
NO_FAILURE_SILENTLY_BECOMES_PASS = confirmed by construction:
  ValidationOutcome.accepted is a real AND of 6 independent booleans;
  import_result() checks .accepted before EVER calling _consume_result();
  there is no code path that reaches RESULT_CONSUMED without passing
  through RESULT_ACCEPTED first.
```

## Fallback behavior

Per dispatch section 20 ("Fallback may regenerate handoff, request
correction, return to Claude-only execution, escalate to human, or mark
BLOCKED"): M7 V1 implements the simplest safe fallback -- a rejected
result leaves the task's own state at `RESULT_REJECTED`, `WAITING_FOR_
HUMAN_TRANSPORT`'s own handoff artifact is untouched and can be
re-copied, and a human can re-attempt transport (request a corrected
result) or abandon the multi-model path and continue Claude-only (the
task was never blocked from proceeding without this optional review in
the first place -- M7 V1 is additive, never a hard dependency the M6
Golden Workflow itself requires). No automatic escalation-to-human
mechanism beyond the existing `HUMAN_DECISION_REQUIRED` ->
`QuestionQueueStore` path was built this cohort (a real, disclosed scope
limit -- see `M7_FINAL_QUALIFICATION_REPORT.md`'s own gap list).

## Human authority preserved (dispatch section 18, re-verified against
the real code)

```
DESIGN_AUTHORITY = DE
VERIFICATION_AUTHORITY = DV
VERIFICATION_SIGNOFF_AUTHORITY = DV
```

Confirmed by direct source read: `_consume_result()` routes EVERY
`HUMAN_DECISION_REQUIRED` result through `QuestionQueueStore.
add_question(domain="env", ...)` -- the SAME real `authority_role`
classification mechanism (`clarification_service.classify_question_
owner()`) the qualified M6 Golden Workflow itself uses. No code in
`model_handoff.py`/`model_result.py`/`model_handoff_workflow.py` ever
sets a `RESULT_STATUS` to `PASS`/auto-accepts a change on a model's own
say-so -- `RESULT_CONSUMED` means "reached a real Canonical Consumer,"
never "was approved by Codex/ChatGPT."

## Independent review context (dispatch section 15/17)

`INDEPENDENCE_REQUIREMENT` is a real, free-text field
`build_handoff()` passes through unmodified -- confirmed by
`test_independent_review_handoff_carries_no_prior_verdict_field`: a
handoff's own `known_facts` defaults to empty, proving `build_handoff()`
never auto-injects an implementation conclusion the caller did not
explicitly supply.
