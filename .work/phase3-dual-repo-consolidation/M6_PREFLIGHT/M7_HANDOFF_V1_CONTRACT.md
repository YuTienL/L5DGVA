# M7 V1 -- L5DGVA_MODEL_HANDOFF_V1 Contract

Real, implemented contract: `dv_harness/model_handoff.py`. Every field
below is either a REAL, already-existing Canonical value reused
verbatim, or one of the 2 genuinely net-new fields the M7 Preflight's
own `M7_STRUCTURED_HANDOFF_CONTRACT.md` already identified as missing --
see that module's own docstring for the full field-by-field reuse
mapping (repeated here only as a compact table).

| Field | Reused from | Implementation |
|---|---|---|
| `HANDOFF_VERSION` | new, small constant (`"1.0"`) | `model_handoff.HANDOFF_VERSION` |
| `TASK_ID` | caller-declared, same identity concept `TaskBoundary.task_id` already carries | required, non-blank enforced |
| `TASK_TYPE` | `router.DEFAULT_ROUTES`' own real task-type vocabulary | free-form string, not re-validated against the table (a future cohort's own decision, not required for V1) |
| `SOURCE_MODEL` | fixed | always `"claude"` (`model_handoff.SOURCE_MODELS`) |
| `TARGET_MODEL` | fixed, closed enum | `codex` \| `chatgpt` (`model_handoff.TARGET_MODELS`) -- an invalid value is a real `HandoffBuildError` |
| `PROJECT_ID` | caller-declared | required |
| `CURRENT_HEAD` | `git rev-parse HEAD`, the same real fact `engine.py`'s own `self.state.git_sha` carries | resolved automatically by `build_handoff()`, never caller-supplied (an unresolvable HEAD is a real `HandoffBuildError`, never silently blank) |
| `OBJECTIVE` | caller-declared | required, non-blank enforced |
| `SCOPE` / `ALLOWED_FILES` / `FORBIDDEN_FILES` | `task_boundary_conformance.TaskBoundary` (CAP-ATL-004), reused verbatim, never re-implemented | `ModelHandoffV1.scope`/`.allowed_files`/`.forbidden_files` |
| `INPUT_EVIDENCE_REFS` | the real `evidence_refs` pattern (28 modules) | caller-supplied, already-scoped list |
| `REQUIRED_GOVERNANCE_REFS` | `governance_registry.get_entries_by_trigger()` | derived via `governance_trigger=`, never a CLAUDE.md dump |
| `KNOWN_FACTS` / `OPEN_QUESTIONS` | caller-declared | free-form lists |
| `INDEPENDENCE_REQUIREMENT` | new (the mechanism for dispatch section 15/"Independent Review") | free text; `build_handoff()` never auto-populates it with an implementation conclusion |
| `EXPECTED_OUTPUT_TYPE` | **net-new** (`M7_STRUCTURED_HANDOFF_CONTRACT.md`'s own finding) | closed enum: `review_findings` \| `research_synthesis` \| `code_change` \| `decision_analysis` \| `structured_issue` |
| `EXPECTED_OUTPUT_SCHEMA` | **net-new** | defaults to `"L5DGVA_MODEL_RESULT_V1"` |
| `VALIDATION_REQUIREMENTS` | caller-declared | free-form list |
| `HUMAN_DECISION_REQUIRED` | the same boolean-ish signal `AgentResult(ok=False, raw={"blocked_by": ...})` already produces | boolean |
| `RETURN_CONTRACT` | fixed default naming `L5DGVA_MODEL_RESULT_V1` | string |

## Markdown serialization

One `## FIELD_NAME` H2 section per field, in the exact order the
dispatch's own section 6 lists them -- `model_handoff.to_markdown()`/
`from_markdown()` are exact inverses (round-trip tested,
`test_valid_handoff_round_trips_through_markdown`). List-valued fields
render as `- item` bullets; an empty list renders as the literal
`(none)`, never a blank section (so a parser can distinguish "empty
list" from "field missing entirely").

## Construction discipline

`build_handoff()` is the ONLY supported constructor for a real handoff
(direct `ModelHandoffV1(...)` construction is used only by this
module's own tests, never a production path) -- it:

1. Refuses an invalid `target_model`/`expected_output_type`/blank
   `task_id`/blank `objective` with a real, structured
   `HandoffBuildError`, never a silent default.
2. Resolves `CURRENT_HEAD` from a real `git rev-parse HEAD` -- an
   unresolvable HEAD (not a git repo, or git unavailable) is itself a
   real `HandoffBuildError`, never a fabricated SHA.
3. Derives `REQUIRED_GOVERNANCE_REFS` from `governance_registry.py`'s
   own real, scoped retrieval -- degrade-never-raise on a missing/
   malformed registry (an empty list, not a crash), matching
   `task_boundary_conformance.py`'s own established discipline.

## Minimum Sufficient Context

`context_size_bytes(handoff)` returns real byte counts
(`handoff_bytes`, `governance_context_bytes_proxy`, `files_referenced`)
-- explicitly labeled proxies, never a fabricated token count. See
`M7_MINIMUM_SUFFICIENT_CONTEXT_BASELINE.md`.

## Scope semantics added by M7-V1-CODEX-REVIEW-002 remediation (GAP-V2-010/013)

Authoritative code: `dv_harness/model_handoff.py` (`read_boundary()`,
`DEFAULT_RETURN_CONTRACT`).

- `ALLOWED_FILES` = the MODIFICATION boundary (and the permitted
  `RETURNED_ARTIFACTS`).
- READ authorization = `ALLOWED_FILES` + `INPUT_EVIDENCE_REFS` -
  `FORBIDDEN_FILES` (forbidden always wins). Authorization comes only from
  these explicit lists, never from a file merely being relevant.
- `build_handoff()` rejects `scope.task_id != task_id`
  (`TASK_ID_SCOPE_MISMATCH`) and any `INPUT_EVIDENCE_REFS` entry that is
  also forbidden (`INPUT_EVIDENCE_REFS_FORBIDDEN`), so a handoff cannot
  contradict itself.
- `RETURN_CONTRACT` states this rule to the target model verbatim.
- Import is retry-safe: one question per `question_key`, one registry row
  per task, a conflicting retry is `CONSUMPTION_CONFLICT`.

## Declaration rules added by M7-V1-CODEX-REVIEW-003 remediation (GAP-V2-013)

`ALLOWED_FILES`, `FORBIDDEN_FILES` and `INPUT_EVIDENCE_REFS` must be safe AND
already canonical root-relative paths: `..`/`.` segments, doubled slashes,
trailing dots/spaces, absolute/UNC/drive paths and invalid characters are
rejected at build (`UNSAFE_PATH_DECLARATION`) and at parse -- never silently
rewritten, so what a reader sees is exactly what is enforced. The contradiction
check (input evidence that is also forbidden) runs on canonical paths.
Exporting a handoff registers its expected result for automatic ingestion.
