# M7 V1 -- Structured Multi-Model MD Handoff -- Final Qualification Report

```
M7_STATUS = IN_PROGRESS
```

Cohorts 1-2 (`Structured Handoff + Result Contracts`,
`Result Ingestion + Validation + Canonical Consumption`) are real, built,
and tested -- 35/35 passing tests, 0 failures. Cohorts 3-4 (the real
Codex/ChatGPT round trips) are correctly at
`WAITING_FOR_HUMAN_TRANSPORT`, not fabricated. Cohorts 5-6 were not
started this pass, correctly deferred since both depend on a real round
trip completing first (`M7_IMPLEMENTATION_COHORT_PLAN.md`'s own
dependency graph). Per this task's own explicit instruction ("Do not
weaken closure merely because manual transport requires human action"),
`M7_STATUS` is reported as `IN_PROGRESS`, not inflated to
`READY_FOR_APPROVAL` -- section 29's own closure conditions
(`CODEX_ROUND_TRIP=QUALIFIED`, `CHATGPT_ROUND_TRIP=QUALIFIED`,
`CODEX_OUTPUT_CONSUMED=YES`, `CHATGPT_OUTPUT_CONSUMED=YES`) are
genuinely unmet, and this report does not claim otherwise.

```
MULTI_MODEL_LOGICAL_ORCHESTRATION = OPERATIONAL
MULTI_MODEL_TRANSPORT = HUMAN_MEDIATED_MD
TRANSPORT_AUTOMATION_REQUIRED = NO

STRUCTURED_HANDOFF   = OPERATIONAL
STRUCTURED_RESULT    = OPERATIONAL
RESULT_INGESTION     = OPERATIONAL
RESULT_VALIDATION    = OPERATIONAL
RESULT_CONSUMPTION   = OPERATIONAL

CODEX_ROUND_TRIP    = WAITING_FOR_HUMAN_TRANSPORT
CHATGPT_ROUND_TRIP  = WAITING_FOR_HUMAN_TRANSPORT
CODEX_OUTPUT_CONSUMED   = NO
CHATGPT_OUTPUT_CONSUMED = NO

MINIMUM_SUFFICIENT_CONTEXT = OPERATIONAL (real byte-proxy metrics;
  see M7_MINIMUM_SUFFICIENT_CONTEXT_BASELINE.md)
CONTEXT_REDUCTION_MEASURED = YES (structured handoff vs. full-CLAUDE.md-
  dump baseline, real byte comparison)
TOKEN_USAGE_OBSERVABILITY = PARTIAL (unchanged from M7 Preflight --
  Claude-side telemetry real, never combined with this pipeline's own
  metrics)
TOKEN_REDUCTION_MEASURED = NO
TOKEN_REDUCTION_EFFECT = NOT_MEASURED

M6_GOLDEN_PATH_PRESERVED = YES

CURRENT_SCOPE_GAPS_FOUND = 2
CURRENT_SCOPE_GAPS_FIXED = 2
CURRENT_SCOPE_GAPS_OPEN  = 0

UNKNOWN_RUNTIME_CALLERS = 0
UNCONTROLLED_BYPASSES = 0
UNKNOWN_REGRESSION_FAILURES = 0
SOURCE_CAPABILITY_LOSS = 0

AUTHORITATIVE_MASTER_P0_BLOCKER_COUNT = 2
REFERENCE_USB_ENV_CONSUMED = NO

NEXT_RECOMMENDED_GATE = WAITING_FOR_HUMAN_TRANSPORT:
  1) paste .dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-001/HANDOFF_V1.md
     into Codex, save the real reply as a RESULT_V1 markdown file, run
     `python -m dv_harness.model_handoff_workflow import --task-id
     M7-V1-CODEX-REVIEW-001 --result-file <saved path>`;
  2) same for .dv-harness/model_handoffs/M7-V1-CHATGPT-DECISION-001/
     HANDOFF_V1.md with ChatGPT;
  3) once both round trips reach RESULT_CONSUMED, Cohorts 3-4 can be
     marked QUALIFIED and Cohorts 5-6 (Minimum Sufficient Context +
     Observability combination, Multi-Model Logical Orchestration
     Qualification) become unblocked.
```

## Current-scope defects found and fixed this pass (P5 FIND->FIX->VERIFY,
never DOCUMENT_ONLY)

Both found while writing this cohort's own real tests, both fixed within
this same task, both re-verified by a passing test:

1. **`_consume_result()`'s own `grounding_evidence` construction used an
   invalid key** (`{"evidence_refs": ...}` instead of the real, only-
   accepted `{"summary": str, "evidence_path": str}` shape
   `question_queue.normalize_grounding_evidence()` enforces) --
   discovered by `test_human_decision_required_routes_through_the_real_
   question_queue` failing with a real `QuestionValidationError`. Fixed
   by constructing the correct shape from the result's own decisions
   text + first evidence ref.
2. **`ModelResultV1`/`ModelHandoffV1` did not normalize list-vs-tuple
   Sequence fields**, so a caller passing a plain list (as this task's
   own tests naturally did) produced a dataclass whose fields compared
   unequal to the tuple-shape `from_markdown()` always returns --
   discovered by `test_valid_result_round_trips_through_markdown`
   failing on a list-vs-tuple equality mismatch. Fixed via a real
   `__post_init__` normalization on both frozen dataclasses.

## Disclosed, deferred (not a defect, out of M7 V1's own scope)

- `RESULT_VERSION` is parsed and checked to be present, but not yet
  cross-validated against the matching handoff's own `HANDOFF_VERSION`
  (a real, disclosed V1 simplification -- both are currently fixed at
  `"1.0"`, so this has no current behavioral effect; a future version
  bump would need this check added).
- No automatic escalation-to-human path beyond the existing
  `HUMAN_DECISION_REQUIRED` -> `QuestionQueueStore` route was built (a
  human re-running `import` with a corrected result file is the only
  "regenerate/retry" mechanism this cohort provides).
- `FILES_READ` (dispatch section 21's own metric list) is not
  separately instrumented -- a real, scoped, un-built addition.
- No cross-provider Model Task Router extension was built (M7 Preflight's
  own Cohort 5 in the ORIGINAL 7-cohort plan, now folded into this
  dispatch's own C5/C6) -- explicitly out of THIS dispatch's own C1-C2
  scope, correctly deferred, not silently dropped.

## Master control-plane

```
MASTER_CAPABILITY_MATRIX_MALFORMED_ROWS = 0
MASTER_CAPABILITY_MATRIX_DUPLICATE_IDS = 0
P0_COUNT_AMBIGUITY = 0
AUTHORITATIVE_MASTER_P0_BLOCKER_COUNT = 2 (unchanged: CAP-M8-EXPLOOP-001,
  CAP-CE-018, neither M7-owned)
```

## STOP

Per this task's own explicit instruction (section 31): both real
handoffs generated, both paths reported, both set to
`WAITING_FOR_HUMAN_TRANSPORT`, both STOPPED there. No Codex/ChatGPT
output is fabricated anywhere in this record. `M8` and later waves are
NOT started. `REFERENCE_USB_ENV_CONSUMED` remains NO.
