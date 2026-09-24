# M7 V1 -- L5DGVA_MODEL_RESULT_V1 Contract

Real, implemented contract: `dv_harness/model_result.py`.

## Fields

| Field | Purpose | Implementation |
|---|---|---|
| `RESULT_VERSION` | protocol version, checked but not yet cross-validated against `HANDOFF_VERSION` (a real, disclosed V1 simplification -- see `M7_FINAL_QUALIFICATION_REPORT.md`'s own gap list) | `model_result.RESULT_VERSION` |
| `TASK_ID` | round-trip identity | validated against the matching handoff's own `task_id` |
| `PRODUCER_MODEL` | which model actually produced this | validated against the matching handoff's own `target_model` |
| `TASK_TYPE` | round-trip compatibility | validated equal to the handoff's own `task_type` (exact match, never "close enough") |
| `RESULT_STATUS` | one of `PASS`/`FAIL`/`PARTIAL`/`BLOCKED`/`HUMAN_DECISION_REQUIRED`/`INSUFFICIENT_EVIDENCE`/`INVALID_SCOPE`/`INVALID_RESULT` | `model_result.RESULT_STATUSES` -- an unrecognized value is a real `ResultParseError`, never silently accepted |
| `CLAIMS` / `FINDINGS` | the model's own assertions | kept SEPARATE from `EVIDENCE_REFS` -- "a model result is not evidence merely because a model produced it" |
| `EVIDENCE_REFS` | what actually backs a claim/finding | required whenever `CLAIMS`/`FINDINGS` is non-empty (`evidence_validated`) |
| `COUNTER_EVIDENCE` / `UNKNOWN_ITEMS` | preserved, never dropped | never resolved by majority vote -- both sides of a disagreement stay on the record |
| `FILES_REFERENCED` | scope enforcement input | checked against the handoff's own `TaskBoundary` via `task_boundary_conformance.classify_path()`, reused verbatim |
| `VALIDATION_PERFORMED` | what the producer model itself claims to have checked | free-form list, carried through, never itself trusted as THIS project's own validation |
| `RECOMMENDED_ACTIONS` | free-form | carried through to the Canonical Consumer |
| `HUMAN_DECISIONS_REQUIRED` | routes to the real HITL mechanism | see `M7_RESULT_INGESTION_AND_CONSUMPTION.md` |
| `SCOPE_EXCEPTIONS` | a producer's own declared exceptions to scope | carried through, NEVER auto-honored -- an actual `FILES_REFERENCED` violation still fails `scope_validated` regardless of what `SCOPE_EXCEPTIONS` claims |
| `RETURNED_ARTIFACTS` | any files/content the producer model returns | carried through |

## Round-trip validation chain (`validate_result()`)

Six real, independent checks, each with its own boolean outcome (never
collapsed into one opaque pass/fail):

```
task_id_validated       -- TASK_ID == handoff.task_id
producer_validated      -- PRODUCER_MODEL == handoff.target_model
task_type_validated     -- TASK_TYPE == handoff.task_type
scope_validated         -- every FILES_REFERENCED entry classifies
                            WITHIN_DECLARED_BOUNDARY against the
                            handoff's own TaskBoundary
schema_validated        -- RESULT_STATUS already real (from_markdown()
                            enforces this) AND PRODUCER_MODEL is a real
                            target model
evidence_validated       -- CLAIMS/FINDINGS non-empty implies
                            EVIDENCE_REFS non-empty
```

`ValidationOutcome.accepted` is `True` only when ALL SIX are `True` --
never a majority, never a weighted score. Model confidence is never read
by this function; only structural, evidence-backed facts.

## Test evidence

`dv_harness_tests/test_model_handoff_v1.py`: valid round-trip, malformed
markdown, missing required fields, invalid `RESULT_STATUS`, task ID
mismatch, producer mismatch, scope violation (including a file that is
BOTH plausible-sounding and forbidden), missing evidence for real
claims, and the negative case (no claims/findings needs no evidence) --
all real, passing tests, not merely described.
