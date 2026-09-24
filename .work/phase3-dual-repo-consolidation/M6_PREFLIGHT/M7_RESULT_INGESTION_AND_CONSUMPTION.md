# M7 V1 -- Result Ingestion and Consumption

Real, implemented pipeline: `dv_harness/model_handoff_workflow.
import_result()`.

## The real chain

```
RESULT_RETURNED (a real file path a human saved)
  -> PARSED (model_result.from_markdown(), a real ResultParseError on
     failure, never a silent default)
  -> TASK_ID_VALIDATED / PRODUCER_VALIDATED / TASK_TYPE_VALIDATED /
     SCOPE_VALIDATED / SCHEMA_VALIDATED / EVIDENCE_VALIDATED
     (model_result.validate_result(), 6 independent real checks)
  -> RESULT_CLASSIFIED (RESULT_ACCEPTED if all 6 pass, else
     RESULT_REJECTED -- state persisted either way)
  -> CANONICAL_CONSUMER (only reached from RESULT_ACCEPTED)
  -> RESULT_CONSUMED
```

A parse failure or a failed validation transitions straight to
`RESULT_REJECTED` and STOPS -- consumption is never reached. This is
proven, not merely claimed:
`test_rejected_result_is_never_consumed` asserts the registry file
itself never gets created for a rejected result.

## The real Canonical Consumer (2 real paths, both fire on every
ACCEPTED result)

1. **Registry append** (`_append_registry()`): a real, structural,
   append-only CSV row (`.dv-harness/model_handoffs/registry.csv`) for
   EVERY consumed result -- `task_id`, `target_model`, `task_type`,
   `state`, `result_status`, both file paths, the real git HEAD at
   consumption time, and the filed question's own id if one was filed.
   This is the "evidence store"/"capability-status update" consumer the
   architecture doc names -- real, not a printed line.
2. **Question filing** (`_consume_result()`, conditional): when the
   result declares `HUMAN_DECISIONS_REQUIRED` or carries
   `RESULT_STATUS = HUMAN_DECISION_REQUIRED`, a REAL question is filed
   through `question_queue.QuestionQueueStore.add_question()` -- the
   SAME production HITL mechanism the M6 Golden Workflow's own HumanGate
   stage already uses (`domain="env"`, matching every other
   VERIFICATION-authority question this project already files). This is
   deliberately NOT a second, parallel human-decision channel
   (dispatch section 18).

A result with neither a real registry row nor (when applicable) a real
filed question would be a capability island (dispatch section 12's own
definition) -- proven not to happen by
`test_valid_result_reaches_real_consumption` (registry row asserted) and
`test_human_decision_required_routes_through_the_real_question_queue`
(question asserted, read back from the real `QuestionQueueStore`, not
merely returned in-memory).

## Scope enforcement at ingestion (dispatch section 19)

`SCOPE_VALIDATED` is not a formality -- `test_scope_violation_is_not_
accepted`/`test_forbidden_file_reference_is_flagged_even_if_also_
plausible` prove a genuinely out-of-scope `FILES_REFERENCED` entry
forces `RESULT_REJECTED`, even when OTHER referenced files are
in-scope and the result otherwise looks legitimate.

## State persistence and resumability

Every transition is written to a real, on-disk JSON file
(`.dv-harness/model_handoffs/<task_id>/state.json`) BEFORE the next step
runs -- `current_state()` reads this same file, so a caller resuming in
a fresh process (a genuinely different Python invocation, proven by
`test_resume_reads_real_persisted_state_a_second_process_could_read`)
sees the real, current state. This module makes no claim of durability
beyond "a real file, read back correctly" -- it does not claim
`lifecycle.py`'s own richer milestone/transition-history guarantees.
