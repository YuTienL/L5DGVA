# L5DGVA_MODEL_RESULT_V1

<!-- L5DGVA_VALUE_ENCODING=escaped-v1 -->

## RESULT_VERSION
1.0

## TASK_ID
M7-V1-CODEX-REVIEW-003

## PRODUCER_MODEL
codex

## TASK_TYPE
review-route

## RESULT_STATUS
FAIL

## CLAIMS
- CLAIM: R1 is closed for duplicate and unknown raw sections; raw RESULT_STATUS forgery now fails closed.
- CLAIM: R2 and R3 are closed for ordinary canonical citation paths, but path normalization is missing and permits read-boundary traversal through dot-dot segments.
- CLAIM: R4 is closed at construction and parse time.
- CLAIM: R5 is closed for the tested sequential retry failures, but conflict identity remains narrower than result identity because it compares only status and result pathname.
- CLAIM: R6 is closed for tested list values, CR, LF, Unicode boundaries, and edge whitespace, but the shared codec is not lossless for empty scalar strings.
- CLAIM: R7 is closed by explicit EXPECTED_OUTPUT_SCHEMA validation.
- CLAIM: R8 is substantially closed by adversarial coverage, but the new traversal, same-path replacement, empty-scalar, and invalid-title cases are untested.
- CLAIM: GAP-V2-013 is not closed because lexical scope classification occurs before canonical path normalization for citations, FILES_REFERENCED, RETURNED_ARTIFACTS, and handoff boundary inputs.

## FINDINGS
- FINDING N1 (CRITICAL, NEW): Path traversal bypasses the declared read/output boundaries. model_result.py passes raw path strings to filesystem existence checks and classify_path without first resolving and proving they remain beneath the repository root or canonical declared path. A focused probe with an allowed directory prefix accepted the citation `dv_harness/../README.md:1` as verified evidence with scope_validated=true and accepted=true, although its normalized target is outside the allowed directory. A second probe against the actual REVIEW-003 handoff accepted RETURNED_ARTIFACTS=`dv_harness/model_result.py/../../dv_harness/engine.py` with scope_validated=true and accepted=true; the lexical string begins with an allowed file prefix but normalizes to a forbidden target. The same unnormalized classification pattern is used for FILES_REFERENCED. This directly violates GAP-V2-013 and the RETURN_CONTRACT.
- FINDING N2 (HIGH, R5 NARROWER THAN REQUIRED): Partial-consumption conflict detection does not identify the result content. model_handoff_workflow.py compares only result_status and the resolved result pathname against an existing registry row. If the same result file is edited after registry append but before the final state save/retry, while retaining the same status, the retry is not a CONSUMPTION_CONFLICT. It validates and consumes the replacement content, while the existing registry row and stable question key are reused. The registry stores no digest. Thus sequential retries are idempotent for a pathname/status pair, not for an immutable result. This is an INFERENCE from the verified persisted fields and branch conditions; no destructive failure injection was performed in the canonical repository.
- FINDING N3 (MEDIUM, R6 PARTIALLY CLOSED): md_kv_codec.render_scalar maps both None and the empty string to `(none)`, and parse_scalar maps that token to None. A focused probe round-tripped a ModelResultV1 with result_version="" and observed result_version become null. This contradicts the codec's documented claim that ESCAPED encoding is an exact lossless inverse for any Python string. The new parameterized exactness test varies only list fields; its handoff scalar test explicitly excludes the empty string and `(none)`.
- FINDING N4 (MEDIUM, NEW FAIL-CLOSED STRUCTURE GAP): The document title is not structurally validated. model_result.from_markdown and model_handoff.from_markdown only search for the schema token as a substring anywhere in the document, while md_kv_codec.split_sections permits any number of arbitrary `# ` preamble lines. A focused probe replaced the canonical result title with `# WRONG-L5DGVA_MODEL_RESULT_V1`; parsing succeeded. Duplicate/unknown H2 sections now fail closed, but the document identity itself does not.
- FINDING N5 (MEDIUM, NEW): Boundary declarations themselves are not canonicalized before contradiction checks or construction of read_boundary. A handoff can therefore express traversal-bearing ALLOWED_FILES, INPUT_EVIDENCE_REFS, or FORBIDDEN_FILES whose lexical classification differs from the resolved filesystem target. N1 demonstrates the downstream impact. build_handoff's new contradiction check also classifies the unnormalized input string, so it is not a complete prevention boundary.
- FINDING N6 (MEDIUM, NEXT_ACTION FAILURE PATH): import_result persists NEXT_ACTION only after _import_result_inner returns. An OSError during question lookup/storage, registry access/append, or final state persistence escapes before execution_contract.persist_next_action is called. Some of those paths have already changed state to RESULT_ACCEPTED. Therefore the stated rule that every state-changing outcome persists NEXT_ACTION is not enforced for partial-consumption failures. Existing next-action tests cover returned CONSUMED/REJECTED outcomes, not exceptions after state mutation.

## EVIDENCE_REFS
- dv_harness/model_result.py:202-221
- dv_harness/model_result.py:323-395
- dv_harness/model_handoff.py:81-104
- dv_harness/model_handoff.py:214-226
- dv_harness/model_handoff_workflow.py:251-307
- dv_harness/model_handoff_workflow.py:353-388
- dv_harness/md_kv_codec.py:125-128
- dv_harness/md_kv_codec.py:155-192
- dv_harness_tests/test_model_handoff_review002_remediation.py:150-183
- dv_harness_tests/test_model_handoff_review002_remediation.py:188-288
- dv_harness_tests/test_model_handoff_review002_remediation.py:305-358
- dv_harness_tests/test_execution_contract.py:292-349

## COUNTER_EVIDENCE
- COUNTER_EVIDENCE: Raw duplicate RESULT_STATUS, duplicate handoff fields, unknown sections, stray non-title preamble text, and wrapped list continuations are rejected by the shared codec and corresponding tests.
- COUNTER_EVIDENCE: Ordinary forbidden, out-of-boundary, mixed real/nonexistent, and free-form-only verdict evidence cases are rejected or disclosed according to the documented citation-versus-narrative policy.
- COUNTER_EVIDENCE: build_handoff now rejects scope.task_id mismatch and directly contradictory forbidden input evidence; SCOPE parsing uses fullmatch.
- COUNTER_EVIDENCE: Sequential registry-append and final-state-save failure tests demonstrate one question and one registry row on retry for unchanged result content.
- COUNTER_EVIDENCE: CR, LF, Unicode line boundaries, edge whitespace, literal escape sequences, heading-like list content, and empty list items pass seeded and parameterized codec tests.
- COUNTER_EVIDENCE: EXPECTED_OUTPUT_SCHEMA is now included in schema_validated.
- COUNTER_EVIDENCE: The authorized regression run completed with 174 passed tests across test_model_handoff_v1.py, test_model_handoff_review002_remediation.py, and test_execution_contract.py.

## UNKNOWN_ITEMS
- UNKNOWN: Concurrent imports remain susceptible to check-then-act races in question lookup and registry append, but concurrency was not dynamically exercised.
- UNKNOWN: QuestionQueueStore internals were not inspected because dv_harness/question_queue.py is forbidden; conclusions about question reuse rely only on the authorized consumer code and disclosed handoff fact.
- UNKNOWN: No partial-consumption write failure was injected into the canonical repository; N2 and N6 are derived from current operation ordering and persisted identity fields.

## FILES_REFERENCED
- dv_harness/md_kv_codec.py
- dv_harness/model_handoff.py
- dv_harness/model_result.py
- dv_harness/model_handoff_workflow.py
- dv_harness_tests/test_model_handoff_v1.py
- dv_harness_tests/test_model_handoff_review002_remediation.py
- dv_harness/execution_contract.py
- dv_harness_tests/test_execution_contract.py
- .dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-002/RESULT_V1.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_CODEX_REVIEW_002_FINDINGS_REMEDIATION_REPORT.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_CODEX_REVIEW_002_RESULT_REJECTION_ANALYSIS.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_RESULT_V1_CONTRACT.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_HANDOFF_V1_CONTRACT.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/L5DGVA_CURRENT_SCOPE_GAP_REGISTER.csv

## VALIDATION_PERFORMED
- Read the complete HANDOFF_V1 and all authorized INPUT_EVIDENCE_REFS.
- Independently re-derived R1-R8 and GAP-V2-013 against current implementation rather than accepting remediation-report conclusions.
- Ran pytest with a writable external temporary directory and bytecode/cache writes disabled: 174 tests passed across all three handoff-authorized suites.
- Probed raw hand-authored duplicate-section behavior and confirmed duplicate RESULT_STATUS is rejected.
- Probed citation and returned-artifact traversal with dot-dot segments and confirmed both can be accepted outside their normalized authorization boundary.
- Probed ESCAPED scalar empty-string fidelity and confirmed empty string becomes None.
- Probed an invalid document title containing the schema token and confirmed it is accepted.
- Reviewed sequential retry, registry identity, question-key lookup, and NEXT_ACTION persistence ordering without modifying production files.
- No production files were modified and no fixes were performed.

## RECOMMENDED_ACTIONS
- Canonicalize every declared and returned repository path against the repository root, reject absolute paths and dot-dot escapes, then perform scope comparison on canonical root-relative paths. Apply this consistently to ALLOWED_FILES, FORBIDDEN_FILES, INPUT_EVIDENCE_REFS, FILES_REFERENCED, citation tokens, governance refs, RETURNED_ARTIFACTS, and the own-result exemption.
- Persist a result content digest in state and registry and use it for replay/conflict identity; do not equate pathname plus status with an immutable result.
- Give empty scalar strings a distinct escaped representation or explicitly reject them at schema construction so None and empty remain distinguishable.
- Require exactly one canonical title and exactly one encoding marker in its defined position for ESCAPED documents; reject schema-token substring matches in arbitrary titles or content.
- Wrap partial-consumption failures in a persisted recovery outcome with a deterministic NEXT_ACTION before propagating or returning the error.
- Add adversarial regression tests for normalized traversal, same-path changed-content retry, empty scalar fidelity, invalid titles, marker placement, and NEXT_ACTION after partial-consumption exceptions.

## HUMAN_DECISIONS_REQUIRED
(none)

## SCOPE_EXCEPTIONS
(none)

## RETURNED_ARTIFACTS
- .dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-003/RESULT_V1.md
