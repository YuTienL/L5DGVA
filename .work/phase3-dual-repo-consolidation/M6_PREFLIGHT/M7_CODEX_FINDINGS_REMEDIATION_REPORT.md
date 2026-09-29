# M7 Codex Findings Remediation Report

`TASK_ID=M7-V1-CODEX-REVIEW-001`. Source: the real, preserved, never-edited
`.dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-001/RESULT_V1.md`
(`CODEX_ROUND_TRIP=QUALIFIED`, `CODEX_OUTPUT_CONSUMED=YES`,
`RESULT_STATUS=FAIL`). Per Prime Directive V2 P5/P6: every finding below
was independently reproduced against the real code with a real Python
probe before any fix was written -- Codex's own claim was never trusted
as-is. `DISPOSITION` and `AUTO_REMEDIATION_ELIGIBILITY` use the real
`dv_harness/result_action_router.py` vocabulary.

## Findings

| FINDING_ID | CLAIM | REPRODUCTION | EXPECTED_BEHAVIOR | ACTUAL_BEHAVIOR (pre-fix) | ROOT_CAUSE | GAP_ID | DISPOSITION | AUTO_REMEDIATION_ELIGIBILITY |
|---|---|---|---|---|---|---|---|---|
| F1 | `schema_validated` never checks `RESULT_VERSION` | In-memory probe: built a `ModelResultV1` with `result_version="9.9"`, called `validate_result()` | An unsupported `RESULT_VERSION` must fail `schema_validated` | `schema_validated=True`, `accepted=True` | `validate_result()` computed `schema_ok` from `producer_model in TARGET_MODELS` only | GAP-V2-009 | FIX_NOW_CORRECTNESS_BLOCKER | AUTO_REMEDIATION_ELIGIBLE (no reject reason: no human authority/protected-architecture/scope/security/frozen-source/new-human-decision implication) |
| F2 | Evidence/scope validation can be bypassed (fabricated `EVIDENCE_REFS`; `RETURNED_ARTIFACTS` never scope-checked) | Probe A: `evidence_refs=("fabricated:anything",)`, empty `files_referenced` -> `accepted=True`. Probe B: forbidden path named only in `returned_artifacts` -> `scope_validated=True` (invisible to enforcement) | A fabricated evidence path must fail `evidence_validated`; an out-of-scope `RETURNED_ARTIFACTS` entry must fail `scope_validated` | Both probes accepted | `evidence_ok` was `bool(evidence_refs)` only (no resolution); scope loop iterated `files_referenced` only | GAP-V2-009 (evidence half), GAP-V2-010 (scope half) | FIX_NOW_CORRECTNESS_BLOCKER | AUTO_REMEDIATION_ELIGIBLE |
| F3 | `SCOPE`'s embedded `task_id` is silently discarded in favor of the top-level `TASK_ID` | Round-trip probe: `TASK_ID=TASK`, serialized `scope.task_id=SCOPE-OTHER` -> parsed `scope.task_id` became `TASK` | A `TASK_ID`/`SCOPE` disagreement must be a real parse error, never silently normalized | Silently normalized, no error, no finding | `from_markdown()` never compared the SCOPE-embedded task_id against the top-level `TASK_ID` field before assigning | GAP-V2-010 | FIX_NOW_CORRECTNESS_BLOCKER | AUTO_REMEDIATION_ELIGIBLE |
| F4 | A damaged stored `HANDOFF_V1.md` escapes the structured import contract | Corrupted the persisted handoff file, called `import_result()` | A malformed stored handoff must return `ImportOutcome(RESULT_REJECTED, ...)`, never raise | Uncaught `OSError`/`HandoffParseError` propagated out of `import_result()` | `_load_handoff()` was called before the result-read exception handler, with no guard of its own | GAP-V2-011 | FIX_NOW_CORRECTNESS_BLOCKER | AUTO_REMEDIATION_ELIGIBLE |
| F5 | No replay-safety/atomicity guard; consumption can double-fire; state ordering is crash-unsafe | Traced code path: no state check before `_consume_result()`; `state=RESULT_CONSUMED` saved at lines 215-217, `_append_registry()` at line 218 (after) | Duplicate import of an already-consumed task_id -> zero duplicate consumption; a crash between marking consumed and registry-append must leave an honest, inspectable intermediate state | A second `import_result()` call re-invoked `_consume_result()`/`_append_registry()`; a failure between the two save points left a false `RESULT_CONSUMED` with no registry row | No `prior_state.state == STATE_RESULT_CONSUMED` short-circuit; state save preceded the always-fires registry consumer | GAP-V2-011 | FIX_NOW_CORRECTNESS_BLOCKER | AUTO_REMEDIATION_ELIGIBLE |
| F6 | Parsers/serializers are not exact inverses for embedded newline / `## `-shaped content | Reproduced Codex's own claim, then independently extended it: a `FINDING` value containing an embedded `\n## RESULT_STATUS\nPASS` line silently forged the parsed `RESULT_STATUS` on round-trip (a real PASS-verdict-injection, more severe than Codex's own example) | Every field value/list item must round-trip byte-identical, and can never be misread as a new `## ` section header | Content injected into an unrelated field could create/overwrite a real field, up to forging `RESULT_STATUS` | `_parse_sections()` treats every line starting with `## ` as a new section; `_render_value()`/`_parse_value()` never escaped embedded newlines | GAP-V2-012 | FIX_NOW_CORRECTNESS_BLOCKER (upgraded from Codex's own MEDIUM once the RESULT_STATUS-forgery variant was found -- a verdict-forging defect is a correctness blocker, not a cosmetic one) | AUTO_REMEDIATION_ELIGIBLE |
| F7 | No test coverage for unsupported `RESULT_VERSION`, `SCOPE`/`TASK_ID` mismatch, bogus evidence, evidence/returned-artifact scope bypass, malformed stored handoffs, replayed imports, registry-write failure ordering, or delimiter-bearing Markdown values | Confirmed by reading `dv_harness_tests/test_model_handoff_v1.py` as it stood before this task: none of the above cases existed | The defect classes F1-F6 describe must each have a real, passing adversarial regression test | Zero coverage for any of the eight named cases | Test suite only exercised the happy path + a small set of basic mismatch cases that predate F1-F6's discovery | (none -- a test-coverage finding, not a code defect) | NOT_APPLICABLE_WITH_EVIDENCE (a test-coverage gap, not an independent code defect requiring its own GAP-ID) | CLOSE_WITH_EVIDENCE |

## F7 closure evidence

16 new adversarial tests were added to `dv_harness_tests/test_model_handoff_v1.py`,
covering every named case:

- `test_unsupported_result_version_is_not_schema_validated` (F1)
- `test_fabricated_evidence_ref_is_rejected_when_root_supplied`,
  `test_real_evidence_ref_file_is_accepted_when_root_supplied`,
  `test_free_form_evidence_with_no_path_claim_is_unverifiable_not_fabricated`,
  `test_forbidden_returned_artifact_is_a_scope_violation_even_with_no_files_referenced`,
  `test_self_referential_returned_artifact_does_not_trip_scope_via_full_import`,
  `test_unrelated_forbidden_returned_artifact_still_rejected_despite_self_reference_exemption` (F2)
- `test_handoff_task_id_scope_mismatch_is_a_real_parse_error` (F3)
- `test_malformed_stored_handoff_is_rejected_not_a_crash` (F4)
- `test_duplicate_import_after_consumption_is_a_real_no_op`,
  `test_registry_write_failure_leaves_state_at_accepted_not_a_false_consumed` (F5)
- `test_embedded_newline_in_a_finding_round_trips_verbatim_as_one_item`,
  `test_embedded_heading_like_content_cannot_forge_result_status` (F6)
- `test_governance_validation_is_not_applicable_when_none_required`,
  `test_governance_validation_rejects_an_invalid_ref`,
  `test_governance_validation_accepts_a_real_existing_ref` (GAP-V2-009 governance half, not separately claimed by Codex but discovered as the same class of gap during remediation)

`dv_harness_tests/test_model_handoff_v1.py`: 51/51 pass.
`dv_harness_tests/test_result_action_router.py`: 30/30 pass.

## Disposition summary

| DISPOSITION | Count |
|---|---|
| FIX_NOW_CORRECTNESS_BLOCKER | 6 (F1-F6) |
| NOT_APPLICABLE_WITH_EVIDENCE | 1 (F7, closed via test addition, not a code fix) |

`CODEX_FINDINGS_TOTAL=7`. `CONFIRMED=7`, `PARTIALLY_CONFIRMED=0`,
`NOT_REPRODUCED=0`, `FALSE_POSITIVE=0`, `SUPERSEDED=0`. No finding
disappeared silently; every one has a real fix-or-test-addition and a
real, currently-passing regression test.

## GAP status (see `.work/phase3-dual-repo-consolidation/M6_PREFLIGHT/L5DGVA_CURRENT_SCOPE_GAP_REGISTER.csv`)

- GAP-V2-009: CLOSED
- GAP-V2-010: CLOSED
- GAP-V2-011: CLOSED
- GAP-V2-012: CLOSED

`CURRENT_SCOPE_GAPS_OPEN=0` for this task's own scope.
