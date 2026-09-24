# L5DGVA_MODEL_RESULT_V1

## RESULT_VERSION
1.0

## TASK_ID
M7-V1-CODEX-REVIEW-002

## PRODUCER_MODEL
codex

## TASK_TYPE
review-route

## RESULT_STATUS
FAIL

## CLAIMS
- CLAIM: F1 is only partially closed: unsupported RESULT_VERSION is rejected, but the handoff's EXPECTED_OUTPUT_SCHEMA is still not validated.
- CLAIM: F2 is not closed: existing out-of-scope evidence, free-form fabricated evidence, and evidence containing both a real and a nonexistent claimed path can still be accepted.
- CLAIM: Returned-artifact scope enforcement, including the narrow caller-derived self-reference exemption, rejects other forbidden artifact paths as intended.
- CLAIM: F3 is only partially closed: parsed SCOPE/TASK_ID disagreement is rejected, but build_handoff() still constructs a handoff whose scope.task_id disagrees with task_id.
- CLAIM: F4 is closed for OSError and HandoffParseError raised while loading a stored handoff.
- CLAIM: F5 is only partially closed: completed-import replay is idempotent and registry append precedes RESULT_CONSUMED, but failures after question consumption or after registry append remain non-atomic and retryable.
- CLAIM: F6 is not closed for the actual untrusted human-mediated input path: a raw RESULT_V1 document can still inject a duplicate section and forge RESULT_STATUS=PASS.
- CLAIM: F6 is also not closed as an exact round trip for unrestricted strings because carriage returns and leading/trailing whitespace are lost.
- CLAIM: F7 is only partially closed: 16 adversarial tests were added, but they omit the still-open counterexamples found by this re-review.

## FINDINGS
- FINDING R1 (CRITICAL, F6 NOT CLOSED): Escaping only in to_markdown() does not protect from_markdown() from externally authored Markdown, which is the real human-mediated trust boundary. dv_harness/model_result.py:138-147 still accepts every line beginning with "## " as a section and silently overwrites duplicate section keys. A focused raw-Markdown probe inserted "## RESULT_STATUS" followed by "PASS" inside FINDINGS after the genuine FAIL section; from_markdown() returned result_status="PASS". The new test at dv_harness_tests/test_model_handoff_v1.py:623-630 passes only because it first routes the malicious string through to_markdown(), which escapes it; it does not test untrusted raw Markdown.
- FINDING R2 (HIGH, F2 NOT CLOSED): dv_harness/model_result.py:409-419 verifies only path existence, not evidence scope or membership in INPUT_EVIDENCE_REFS. A focused probe cited the real but forbidden dv_harness/engine.py:1 while FILES_REFERENCED was empty; scope_validated=true, evidence_validated=true, and accepted=true. Thus the original out-of-scope-evidence bypass remains.
- FINDING R3 (HIGH, F2 NOT CLOSED): The path checker accepts evidence when any claimed path exists. At dv_harness/model_result.py:415, `any(...is_file() for c in claims)` means an evidence string claiming both dv_harness/model_result.py and no/such/file.py passes with fabricated_evidence empty. Evidence without a regex-recognized path is deliberately accepted as unverifiable at lines 412-419; the original literal counterexample "fabricated:anything" therefore still yields accepted=true. The test at lines 453-460 changes that counterexample to "fabricated:anything.py" and does not cover the original or mixed-claim cases.
- FINDING R4 (MEDIUM, F3 PARTIALLY CLOSED): dv_harness/model_handoff.py:365-372 now rejects a serialized SCOPE/TASK_ID mismatch, but build_handoff() at lines 166-209 still has no `scope.task_id == task_id` check. A focused probe called build_handoff(task_id="TASK", scope.task_id="SCOPE-OTHER") and received a handoff retaining scope.task_id="SCOPE-OTHER". The sole new F3 test at dv_harness_tests/test_model_handoff_v1.py:561-567 covers parsing only.
- FINDING R5 (HIGH, F5 PARTIALLY CLOSED): dv_harness/model_handoff_workflow.py:251 invokes _consume_result() before _append_registry() and before RESULT_CONSUMED. If registry append fails, state remains RESULT_ACCEPTED but the question-queue side effect may already have occurred; retry re-enters _consume_result(). Conversely, if registry append succeeds at line 259 and the state save at lines 261-263 fails, retry appends another registry row because the replay guard only recognizes RESULT_CONSUMED. The new failure test at lines 638-652 covers state honesty when registry append fails, but not duplicate semantic effects or failure after a successful append. This is an INFERENCE from verified operation ordering; QuestionQueueStore internals were forbidden from inspection.
- FINDING R6 (MEDIUM, F6 NOT FULLY CLOSED): _escape_md_line() at dv_harness/model_result.py:103-112 and dv_harness/model_handoff.py:236-243 escapes LF but not CR, while splitlines() treats CR as a line boundary. Both parsers also call strip() on section and item content. A focused serializer round-trip changed findings (" lead trail ", "a\rb") into ("lead trail", "a", "b"). The claimed exact inverse for unrestricted strings is therefore false even on the serializer-generated path.
- FINDING R7 (MEDIUM, F1 PARTIALLY CLOSED): dv_harness/model_result.py:363-369 correctly checks RESULT_VERSION, but schema_ok does not compare handoff.expected_output_schema with the supported L5DGVA_MODEL_RESULT_V1 schema. A focused probe used expected_output_schema="OTHER_SCHEMA" and still observed schema_validated=true. This is narrower than original F1's stated schema concern.
- FINDING R8 (MEDIUM, F7 PARTIALLY CLOSED): The 16 named tests exist, including coverage for version rejection, path-shaped nonexistent evidence, returned-artifact enforcement/self-reference, parse-time scope mismatch, malformed stored handoff, completed replay, registry-failure state ordering, serializer-mediated LF/header escaping, and governance refs. They do not cover raw duplicate-section injection, evidence scope, mixed real/fabricated path claims, the original extensionless fabricated evidence case, construction-time scope mismatch, CR/whitespace round trips, or partial-consumption retry behavior.

## EVIDENCE_REFS
- EVIDENCE: dv_harness/model_result.py:138-147 stores sections in a dict and overwrites duplicate names without rejection.
- EVIDENCE: dv_harness/model_result.py:169-201 parses raw RESULT_V1 sections without requiring escaped provenance or rejecting duplicates/unknown headers.
- EVIDENCE: dv_harness/model_result.py:363-369 checks RESULT_VERSION but not handoff.expected_output_schema.
- EVIDENCE: dv_harness/model_result.py:371-391 scope-checks FILES_REFERENCED and RETURNED_ARTIFACTS, but not EVIDENCE_REFS.
- EVIDENCE: dv_harness/model_result.py:404-421 accepts free-form unverifiable evidence and uses an any-existing-path condition for multi-path evidence.
- EVIDENCE: dv_harness/model_handoff.py:166-209 does not validate scope.task_id against task_id during construction.
- EVIDENCE: dv_harness/model_handoff.py:355-378 rejects parse-time SCOPE/TASK_ID disagreement, although its regex uses match rather than fullmatch.
- EVIDENCE: dv_harness/model_handoff_workflow.py:192-205 implements completed-state replay and structured stored-handoff parse rejection.
- EVIDENCE: dv_harness/model_handoff_workflow.py:247-263 orders question consumption, registry append, then RESULT_CONSUMED persistence.
- EVIDENCE: dv_harness_tests/test_model_handoff_v1.py:441-652 contains the 16 remediation tests claimed by the remediation report.
- EVIDENCE: Focused raw-input probe output: {"parsed_result_status":"PASS","parsed_findings":["legitimate finding"]} after inserting a second RESULT_STATUS section inside FINDINGS of an externally authored FAIL document.
- EVIDENCE: Focused validation probe observed accepted=true for existing forbidden evidence dv_harness/engine.py:1, accepted=true for "fabricated:anything", accepted=true for a combined real and nonexistent path claim, schema_validated=true with expected_output_schema="OTHER_SCHEMA", and successful construction with task_id="TASK" plus scope.task_id="SCOPE-OTHER".
- EVIDENCE: Focused round-trip probe observed findings [" lead trail ","a\rb"] parse as ["lead trail","a","b"].

## COUNTER_EVIDENCE
- COUNTER_EVIDENCE: F1's primary unsupported-version case is closed by dv_harness/model_result.py:366-369 and covered at dv_harness_tests/test_model_handoff_v1.py:441-447.
- COUNTER_EVIDENCE: Returned artifacts are scope-classified at dv_harness/model_result.py:383-388; the self-reference exemption is derived from the actual result path at dv_harness/model_handoff_workflow.py:227-238 and does not exempt a second unrelated forbidden path in the provided test.
- COUNTER_EVIDENCE: F3's persisted-Markdown mismatch is closed by dv_harness/model_handoff.py:365-372 and its test at lines 561-567.
- COUNTER_EVIDENCE: F4 is closed by the guarded _load_handoff() call at dv_harness/model_handoff_workflow.py:200-205 and the test at lines 573-585.
- COUNTER_EVIDENCE: A task already persisted as RESULT_CONSUMED is replayed as a no-op at dv_harness/model_handoff_workflow.py:192-195, and registry append now precedes RESULT_CONSUMED at lines 253-263.
- COUNTER_EVIDENCE: Serializer-generated LF and heading-like strings round-trip in the two supplied F6 tests because to_markdown() escapes backslashes and LF.
- COUNTER_EVIDENCE: All 16 remediation test functions claimed in M7_CODEX_FINDINGS_REMEDIATION_REPORT.md are present in the current authorized test file.

## UNKNOWN_ITEMS
- UNKNOWN: The full 51-test runtime result could not be independently reproduced in this restricted environment. With bytecode/cache writes disabled and an explicit C:\tmp base, pytest reported 8 passed and 43 setup errors because it lacked permission to create the base directory; these are environmental setup errors, not assertion failures.
- UNKNOWN: QuestionQueueStore retry/deduplication behavior was not inspected because dv_harness/question_queue.py is explicitly forbidden.
- UNKNOWN: No state-save failure was injected after a successful registry append; the duplicate-row risk in R5 is an inference from the verified ordering and replay condition.

## FILES_REFERENCED
- dv_harness/model_handoff.py
- dv_harness/model_result.py
- dv_harness/model_handoff_workflow.py
- dv_harness_tests/test_model_handoff_v1.py
- .dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-001/RESULT_V1.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/M7_CODEX_FINDINGS_REMEDIATION_REPORT.md
- .work/phase3-dual-repo-consolidation/M6_PREFLIGHT/L5DGVA_CURRENT_SCOPE_GAP_REGISTER.csv

## VALIDATION_PERFORMED
- Read the complete re-review HANDOFF_V1 and every INPUT_EVIDENCE_REF authorized by it.
- Independently re-derived F1-F6 against current code rather than accepting remediation-report conclusions.
- Confirmed all 16 named adversarial test functions are present and mapped them to the original coverage gaps.
- Ran the authorized pytest file with PYTHONDONTWRITEBYTECODE=1 and cache disabled; 8 non-fixture tests passed, while 43 fixture tests encountered environmental temp-directory setup errors.
- Ran focused, non-mutating probes for raw RESULT_STATUS section injection, unsupported evidence scope, extensionless/free-form fabricated evidence, mixed real/fabricated path claims, EXPECTED_OUTPUT_SCHEMA mismatch, construction-time SCOPE/TASK_ID mismatch, and CR/whitespace round-trip fidelity.
- No production files were modified and no fixes were performed.

## RECOMMENDED_ACTIONS
- Make raw parsing reject duplicate and unknown sections and enforce an unambiguous encoding for field payloads; do not rely on the local serializer to sanitize untrusted external-model Markdown.
- Scope-classify every path claimed by EVIDENCE_REFS, require every claimed path to exist, and define an acceptance policy for unverifiable free-form evidence instead of treating it as validated.
- Reject scope.task_id != task_id in build_handoff(), not only in from_markdown().
- Make canonical consumption transactionally retry-safe across question creation, registry append, and final state persistence, including recovery after partial success.
- Escape and restore CR as well as LF and preserve leading/trailing whitespace, or explicitly constrain and validate the schema's allowed string domain.
- Validate EXPECTED_OUTPUT_SCHEMA during result ingestion and add regression tests for every counterexample in R1-R7.

## HUMAN_DECISIONS_REQUIRED
(none)

## SCOPE_EXCEPTIONS
(none)

## RETURNED_ARTIFACTS
- .dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-002/RESULT_V1.md
