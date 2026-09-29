# M7 Codex REVIEW-003 Findings Remediation Report

`TASK_ID=M7-V1-CODEX-REVIEW-003`, `RESULT_STATUS=FAIL`, auto-ingested and
consumed (see `M7_REVIEW_003_LIVE_INGESTION_EVIDENCE.md`); original
`RESULT_V1.md` sha256 `484b535b90c6298e4a28079ceae1eb8039b885ec9dfa6df7a9298a2947bc42c4`,
never edited. Every finding was independently reproduced on the current
code (`repro_n1_n6.py`, throwaway repos) before any change.

## Reproduction (pre-fix)

| ID | Codex claim | Pre-fix reproduction | Confirmed |
|---|---|---|---|
| N1 CRITICAL | Traversal bypasses read/output boundaries | `dv_harness/../README.md:1` accepted as verified evidence (allowed dir prefix); `.../model_result.py/../../dv_harness/engine.py` returned artifact classified in-scope. Extra: `dv_harness/ENGINE.PY` (case) and `dv_harness/engine.py.` (trailing dot) aliases of the forbidden file were `accepted=True` on this case-insensitive Windows filesystem -- wider than Codex reported | YES + extended |
| N2 HIGH | Conflict identity is status+path, not content | same path, same status, different content after a lost final state save -> `RESULT_CONSUMED` (replacement content consumed) | YES |
| N3 MEDIUM | Empty scalar becomes None | `result_version=""` -> `None` | YES |
| N4 MEDIUM | Title not structurally validated | `# WRONG-L5DGVA_MODEL_RESULT_V1`, a second title and a duplicate encoding marker were all accepted | YES |
| N5 MEDIUM | Boundary declarations not canonicalized | `ALLOWED_FILES=dv_harness/../README.md` built; contradiction check bypassed by `a.py/../engine.py` | YES |
| N6 MEDIUM | NEXT_ACTION not persisted on mid-consumption exception | exception after `RESULT_ACCEPTED` -> `next_action.json` absent | YES |

Also confirmed from Codex's UNKNOWN list: concurrent imports had no guard.

## Fixes (commit `a2dc1e1`), all `FIX_NOW_CORRECTNESS_BLOCKER`, all `route_action()` = AUTO_REMEDIATION_ELIGIBLE

| ID | Root cause | Fix | Tests (`test_model_handoff_review003_remediation.py`) |
|---|---|---|---|
| N1 | Scope classification ran on the raw string; authorization was a lexical prefix match | `canonical_repo_path()` (collapse `.`/`..`, reject absolute/UNC/drive/NTFS-stream/escaping/invalid characters, drop trailing dots/spaces) and `real_repo_relative()` (true-cased, symlink-resolved identity for existing paths); `_classify_canonical()` fails closed if EITHER view is out of bounds; applied to FILES_REFERENCED, RETURNED_ARTIFACTS, citations, governance refs and the own-result exemption | `test_canonical_repo_path_*`, `test_citation_traversing_*`, `test_returned_artifact_that_normalizes_*`, `test_files_referenced_that_normalizes_*`, `test_absolute_or_escaping_*`, `test_trailing_dot_alias_*`, `test_case_alias_*`, `test_symlink_inside_*`, `test_nonexistent_traversal_target_*`, `test_own_result_exemption_*` |
| N5 | Declarations were trusted as written | `unsafe_declarations()`: unsafe OR non-canonical ALLOWED/FORBIDDEN/INPUT paths are rejected at build (`UNSAFE_PATH_DECLARATION`) and parse -- never silently rewritten; contradiction check runs on canonical paths; `read_boundary()` canonicalizes | `test_traversal_bearing_boundary_declarations_*`, `test_traversal_bearing_declaration_in_a_stored_handoff_*` |
| N2 | Identity was pathname+status; file read twice | SHA-256 of the bytes that are parsed (single read) stored in state (`result_sha256`, `accepted_result_sha256`) and registry (`result_sha256`, additive migration); conflict = digest mismatch; a different file replayed after consumption is flagged `RESULT_CONTENT_DIFFERS_FROM_CONSUMED` | `test_registry_and_state_record_*`, `test_same_path_same_status_*`, `test_conflict_is_detected_from_the_registry_digest_alone`, `test_replay_with_a_different_file_*`, `test_registry_gets_the_digest_column_*`, `test_the_hashed_bytes_are_the_parsed_bytes` |
| N3 | `render_scalar` mapped None and "" to `(none)` | `(empty)` token (escaped encoding only; literal text "(empty)"/"(none)" escaped); raw documents stay verbatim | `test_empty_and_none_scalars_*`, `test_literal_token_text_*`, `test_empty_scalar_in_a_handoff_*` |
| N4 | Schema token matched as a substring; any number of `# ` lines tolerated | Exactly one canonical `# TITLE` first; marker only in the slot right after it; `DUPLICATE_TITLE`/`DUPLICATE_ENCODING_MARKER`; wrong title -> `NOT_A_*_DOCUMENT` | `test_wrong_title_*`, `test_schema_token_only_inside_content_*`, `test_second_title_*`, `test_duplicate_encoding_marker_*`, `test_marker_before_the_title_*`, `test_marker_text_inside_a_value_*` |
| N6 | `persist_next_action` ran only on normal return | Exceptions persist `IMPORT_INTERRUPTED -> AUTO_RETRY_INTERRUPTED_IMPORT` first (a secondary failure never masks the original); per-task `import.lock` (stale-lock recovery, released in `finally`) refuses concurrent imports; manual ingestion shares the watcher's `ingestion.lock` | `test_exception_mid_consumption_*`, `test_retry_after_the_interruption_*`, `test_failure_of_the_next_action_write_*`, `test_concurrent_import_*`, `test_stale_lock_*`, `test_the_lock_is_released_*`, `test_manual_ingestion_is_refused_while_*` |

Defence in depth is deliberate: for existing files the real-path layer
alone would catch most traversal; `test_nonexistent_traversal_target_*`
isolates the canonical layer, and mutation controls (lexical scope; no digest
conflict; no empty token) each fail the suite.

## Verification

- 75 new tests (`test_model_handoff_review003_remediation.py`); 341 tests
  passed across M7 handoff/result, both remediation files, execution contract,
  router, result ingestion, governance registry, reference graph and Prime
  Directive discoverability. Production artifacts still hold: stored REVIEW-001/
  002/003 handoffs parse under the stricter rules, and the real REVIEW-002 and
  REVIEW-003 results still validate unmodified against their own handoffs.
- Constitution gate PASS; five frozen sources unchanged.

## Disclosed limits / design decisions for independent review

1. An accepted-but-unconsumed task cannot swap in *different* content (a
   corrected result needs a new task): fail-closed, no automatic recovery path.
2. Legacy registry rows have an empty digest; identity for them stays
   status+path (no backfill, to avoid asserting a hash that was never recorded).
3. Case aliasing is closed by the real-filesystem layer only when the target
   exists; for a nonexistent case-variant path the lexical (case-sensitive)
   comparison applies (fail-closed toward OUTSIDE unless allowed by exact case).
4. `question_queue.py` is still untouched; question de-duplication remains a
   consumer-side workaround.

Status: `FIXED_AND_VERIFIED_BY_AUTHOR`; `PENDING_INDEPENDENT_REREVIEW`
(`M7-V1-CODEX-REVIEW-004`).
