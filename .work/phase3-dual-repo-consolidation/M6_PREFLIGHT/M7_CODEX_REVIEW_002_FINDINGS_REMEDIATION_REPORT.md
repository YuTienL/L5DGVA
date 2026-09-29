# M7 Codex REVIEW-002 Findings Remediation Report

`TASK_ID=M7-V1-CODEX-REVIEW-002` (re-review of the GAP-V2-009/010/011/012
remediation). Returned `RESULT_STATUS=FAIL`, imported as
`RESULT_REJECTED (SCOPE_VIOLATION)`, then -- after the validator/handoff
defects below were fixed -- re-imported UNMODIFIED
(`RESULT_V1.md` sha256 `cbb3865c00a14450686e177caebd64b3270db56266abad2e6f3008c03ce71eba`,
verified identical before and after) and consumed with `FAIL` preserved.

## Honest correction of the previous task

The previous task marked GAP-V2-009/010/011/012 CLOSED. For the raw
external-input path (R1) and several variants (R2/R3/R4/R5/R6/R7) that
status was overstated: the earlier tests only exercised strings the local
serializer had already escaped. All four gaps were reopened in
`L5DGVA_CURRENT_SCOPE_GAP_REGISTER.csv` before any fix and a new
`GAP-V2-013` was registered. A prior "CLOSED" is never treated as
evidence that a defect is absent.

## Independent reproduction (pre-fix, current production code)

Codex's probes were re-run by the author, not taken on trust
(`repro_r1_r8.py`, throwaway git repos for anything that mutates state).

| ID | Claim | Pre-fix reproduction | Confirmed |
|---|---|---|---|
| R1 (CRITICAL) | Raw FAIL document with a second `RESULT_STATUS` section is parsed as PASS | `parsed result_status = PASS`; unknown sections silently accepted; duplicate `TASK_ID` in a handoff silently overwrote | YES |
| R2 (HIGH) | Evidence citing a real but forbidden file is accepted | `accepted=True scope_validated=True` for `dv_harness/engine.py:1` with empty FILES_REFERENCED | YES |
| R3 (HIGH) | `any()` path semantics + free-form-only evidence accepted | mixed `module_a.py and no/such/file.py` -> `accepted=True fabricated=[]`; `"fabricated:anything"` -> `accepted=True` | YES |
| R4 (MEDIUM) | `build_handoff` accepts `scope.task_id != task_id` | constructed with `scope.task_id=SCOPE-OTHER task_id=TASK` | YES |
| R5 (HIGH) | Consumption not retry-safe | failed registry append then retry: questions 1 -> 2; state-save failure after append then retry: registry rows for the task = 2 | YES (both variants) |
| R6 (MEDIUM) | CR / edge whitespace not preserved | `[" lead trail ","a\rb"]` -> `["lead trail","a","b"]`; handoff objective whitespace changed | YES |
| R7 (MEDIUM) | `EXPECTED_OUTPUT_SCHEMA` never validated | `expected_output_schema="OTHER_SCHEMA"` -> `schema_validated=True` | YES |
| R8 (MEDIUM) | Tests omit the counterexamples | confirmed by inspection; all R1-R7 counterexamples absent | YES |

Also reproduced: the three reported scope violations (see
`M7_CODEX_REVIEW_002_RESULT_REJECTION_ANALYSIS.md`).

## Findings table

| ID | ROOT_CAUSE | GAP | DISPOSITION | AUTO_REMEDIATION | FIX | Regression tests (`dv_harness_tests/test_model_handoff_review002_remediation.py`) |
|---|---|---|---|---|---|---|
| R1 | Parser was written as the exact inverse of the local serializer; the trust boundary is the PARSER (external model + human transport). Section map was a dict (last header wins), unknown headers ignored, continuation lines split into phantom items. Two duplicated copies of the codec. | GAP-V2-012 (reopened) | FIX_NOW_CORRECTNESS_BLOCKER (security boundary) | ELIGIBLE | New shared `md_kv_codec.py`; duplicate/unknown section, stray preamble and wrapped list lines are fail-closed errors in both encodings | `test_raw_duplicate_*`, `test_unknown_section_*`, `test_duplicate_section_in_a_handoff_*`, `test_stray_preamble_*`, `test_wrapped_list_*` |
| R6 | Escape covered only `\` and LF; parser used `splitlines()`+`strip()`; `unescape` was applied to raw external text | GAP-V2-012 | FIX_NOW_CORRECTNESS_BLOCKER | ELIGIBLE | Explicit `ENCODING_MARKER`: ESCAPED docs are a lossless inverse for any string; RAW docs are verbatim, never unescaped | `test_result_list_and_scalar_fields_round_trip_exactly`, `test_handoff_scalar_and_list_fields_round_trip_exactly`, `test_seeded_fuzz_round_trip_is_exact`, `test_raw_external_document_values_are_never_unescaped`, `test_malformed_escape_*`, `test_crlf_*` |
| R2 | Existence check only; evidence never classified against scope | GAP-V2-009 | FIX_NOW_CORRECTNESS_BLOCKER | ELIGIBLE | Citation entries' path tokens are classified against the read boundary | `test_citing_a_forbidden_file_*`, `test_citing_a_real_file_outside_the_read_boundary_*` |
| R3 | `any()` over path claims; prose-only evidence counted as valid | GAP-V2-009 | FIX_NOW_CORRECTNESS_BLOCKER | ELIGIBLE | Evidence grammar (citation vs narrative); all citation paths must exist; verdict results need >=1 verified citation; strict path-token regex (no `e.g.`, `handoff.expected_output_schema`) | `test_mixed_real_and_nonexistent_*`, `test_original_extensionless_fabricated_evidence_*`, `test_free_form_evidence_alone_*`, `test_narrative_mention_*`, `test_prose_tokens_are_not_path_claims` |
| R7 | `schema_ok` ignored `handoff.expected_output_schema` | GAP-V2-009 | FIX_NOW_CORRECTNESS_BLOCKER | ELIGIBLE | `SUPPORTED_EXPECTED_OUTPUT_SCHEMA` check -> `UNSUPPORTED_EXPECTED_OUTPUT_SCHEMA` | `test_unsupported_expected_output_schema_*` |
| R4 | Identity check existed only in `from_markdown` | GAP-V2-010 | FIX_NOW_CORRECTNESS_BLOCKER | ELIGIBLE | `build_handoff` raises `TASK_ID_SCOPE_MISMATCH`; SCOPE regex `fullmatch` | `test_build_handoff_rejects_scope_task_id_mismatch`, `test_scope_field_regex_must_fully_match` |
| R5 | Question filing, registry append and state save were three non-idempotent steps; `QuestionQueueStore` returns the same id for a repeated `question_key` but persists a duplicate row | GAP-V2-011 | FIX_NOW_CORRECTNESS_BLOCKER | ELIGIBLE | Question looked up by `question_key` before filing; registry append skipped when the task already has a row; conflicting retry -> `CONSUMPTION_CONFLICT`; `question_id` persisted before append | `test_failed_registry_append_then_retry_*`, `test_state_save_failure_after_registry_append_*`, `test_retry_with_a_different_result_*` |
| R8 | Test gap | GAP-V2-009..013 | closed by the above tests | -- | 76 new tests + 6 next-action tests | (all of the above) |
| (scope) | HANDOFF listed INPUT_EVIDENCE_REFS but only ALLOWED_FILES was recognised as authorization | GAP-V2-013 (new) | FIX_NOW_CORRECTNESS_BLOCKER | ELIGIBLE | `read_boundary()`; `RETURN_CONTRACT` states the rule; build-time contradiction check | `test_files_referenced_from_input_evidence_refs_*`, `test_files_referenced_in_neither_*`, `test_input_evidence_file_is_not_a_permitted_returned_artifact`, `test_forbidden_wins_*`, `test_build_handoff_rejects_input_evidence_that_is_also_forbidden`, `test_real_returned_review_002_result_validates_*` |

Not touched: `question_queue.py` (M6 mechanism; the duplicate-row behaviour
is worked around at the consumer, disclosed above), `task_boundary_conformance.py`,
`engine.py`, `cli.py`, and all five frozen sources.

## Design decisions the author made (disclosed for independent review)

1. **Two encodings.** Raw external documents are never unescaped, so
   external text such as `a\rb` is not transformed; escaped documents are
   lossless. Trade-off: a raw document cannot carry edge whitespace.
2. **Strictness rejects instead of repairing.** A wrapped bullet or a
   quoted `## HEADING` inside an external result rejects the whole result
   (fallback: request a corrected result). Fail-closed by design.
3. **Citation vs narrative.** A path mentioned mid-sentence in a probe
   description is disclosed, never verified and never rejected; only
   entries that *begin* with a path are citations. A hallucinated path
   buried in narrative is therefore disclosed rather than rejected --
   the verdict-backing rule (>=1 verified citation) is what bounds it.
4. **Read vs output boundary.** Reading is authorized by
   ALLOWED_FILES + INPUT_EVIDENCE_REFS; returning an artifact only by
   ALLOWED_FILES (+ the result's own path).

## Status

`FIXED_AND_VERIFIED` by the author (pre-fix counterexample + adversarial
test per finding); `PENDING_INDEPENDENT_REREVIEW` -> `M7-V1-CODEX-REVIEW-003`.
