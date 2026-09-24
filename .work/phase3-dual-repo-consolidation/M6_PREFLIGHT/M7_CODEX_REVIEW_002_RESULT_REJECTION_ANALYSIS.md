# M7 Codex REVIEW-002 -- Result Rejection Analysis

Canonical state on resume: `TASK_ID=M7-V1-CODEX-REVIEW-002`,
`STATE=RESULT_REJECTED`, `scope_validated=False`, finding
`SCOPE_VIOLATION`, `accepted=False`. Applied: Human Non-Scheduler
Execution Contract + P6. No human scheduling input was requested.

## 1. What the exact HANDOFF_V1 authorized

Read from `.dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-002/HANDOFF_V1.md`:

- `SCOPE`: `task_id=M7-V1-CODEX-REVIEW-002; require_new_file=False`
- `ALLOWED_FILES`: `model_handoff.py`, `model_result.py`,
  `model_handoff_workflow.py`, `test_model_handoff_v1.py`
- `FORBIDDEN_FILES`: `engine.py`, `cli.py`, `task_boundary_conformance.py`,
  `question_queue.py`
- `INPUT_EVIDENCE_REFS`: the four allowed files **plus** the three paths
  below
- `RETURN_CONTRACT`: `L5DGVA_MODEL_RESULT_V1 markdown, same TASK_ID`
  (no statement about what may be cited)
- Inherited canonical scope contract
  (`L5DGVA_M7_STRUCTURED_MULTI_MODEL_MD_HANDOFF_ARCHITECTURE.md`, "Scope and
  Security"): tracks `ALLOWED_FILES`, `FORBIDDEN_FILES`, `FILES_SHARED`,
  `EVIDENCE_SHARED`; "M7 must not bypass M6 Task Boundary". Shared files are
  a named, tracked category -- not implied by relevance.

Authorization was derived ONLY from these explicit declarations. A file
being relevant to the re-review was never treated as authorization.

## 2. Per-violation classification (independent)

| # | Path | ALLOWED_FILES | INPUT_EVIDENCE_REFS | RETURN_CONTRACT | Classification |
|---|---|---|---|---|---|
| 1 | `.dv-harness/model_handoffs/M7-V1-CODEX-REVIEW-001/RESULT_V1.md` | no | **yes (explicit)** | silent | VALIDATOR_SCOPE_INTERPRETATION_DEFECT (primary) + HANDOFF_SCOPE_CONTRACT_DEFECT (contributing) |
| 2 | `.work/.../M7_CODEX_FINDINGS_REMEDIATION_REPORT.md` | no | **yes (explicit)** | silent | same |
| 3 | `.work/.../L5DGVA_CURRENT_SCOPE_GAP_REGISTER.csv` | no | **yes (explicit)** | silent | same |

Not `REAL_EXTERNAL_RESULT_SCOPE_VIOLATION`: the handoff itself told Codex
to read all three. Not `RESULT_RETURN_ARTIFACT_EXCEPTION_DEFECT`: none was
a `RETURNED_ARTIFACTS` entry (the result's own path in that field was
correctly exempted). Reproduced: the production validator reported exactly
these three, checking `FILES_REFERENCED` against `ALLOWED_FILES`, a
MODIFICATION boundary, while the handoff generator let
`INPUT_EVIDENCE_REFS` extend beyond it. The REVIEW-001 handoff had
`INPUT_EVIDENCE_REFS == ALLOWED_FILES`, which is why the ambiguity never
surfaced before.

Fix is generic (GAP-V2-013), not a patch of this handoff and not a widened
allow-list: READ authorization = `ALLOWED_FILES` + `INPUT_EVIDENCE_REFS` -
`FORBIDDEN_FILES`; OUTPUT authorization (`RETURNED_ARTIFACTS`) stays
`ALLOWED_FILES` only; `build_handoff()` rejects a handoff that both shares
and forbids a path; `RETURN_CONTRACT` now states the rule to the model.
Negative controls: a file in neither list is still rejected; an input file
returned as an artifact is still rejected; a forbidden file listed in a
stored handoff's inputs is still rejected.

## 3. The `evidence_unverifiable` entries

| Entry | Ingestion-time classification | After independent reproduction |
|---|---|---|
| "Focused raw-input probe output: {parsed_result_status: PASS ...}" | EXPECTED_UNVERIFIABLE_EXTERNAL_CLAIM (transient probe output has no path to verify) | **PARSER_DEFECT confirmed (R1)** |
| "Focused round-trip probe observed findings [...] parse as [...]" | EXPECTED_UNVERIFIABLE_EXTERNAL_CLAIM | **MARKDOWN_ROUND_TRIP_DEFECT confirmed (R6)** |
| (only visible after the new grammar) "Focused validation probe observed accepted=true for existing forbidden evidence ..." | narrative; mentions forbidden `engine.py` as a probe subject | claims confirmed: R2, R3, R4, R7. The mention is disclosed in `evidence_narrative_mentions`; it is not a citation, and `FILES_REFERENCED` does not list `engine.py`, so it is not classified as a real scope violation |

"Unverifiable" never meant "false": each claim was independently
reproduced and every one was true. It also never meant "verified":
unverifiable narrative cannot back a verdict by itself (new rule).

## 4. Parser / round-trip probes (item 6-8), current production code

Pre-fix, all reproduced (see `M7_CODEX_REVIEW_002_FINDINGS_REMEDIATION_REPORT.md`):

- raw document with a second `RESULT_STATUS` section inside `FINDINGS` ->
  `result_status == "PASS"`. Treated as a current-scope correctness /
  security-boundary defect and NOT closed on the strength of the earlier
  GAP-V2-012 "CLOSED".
- `[" lead trail ","a\rb"]` -> `["lead trail","a","b"]`: violates RESULT_V1
  semantic fidelity (items split, whitespace lost). Fixed.

## 5. Decision among the contract's branches

- Branch 11 (result genuinely violated scope, implementation correct):
  **not applicable** -- the implementation was not correct.
- Branch 12 (handoff omitted needed evidence): **partially** -- the
  handoff generation mechanism lacked a read-authorization definition;
  fixed in the mechanism, and a new handoff with a new Task ID
  (`M7-V1-CODEX-REVIEW-003`) is generated because the code under review
  changed materially.
- Branch 13 (validator wrong): **yes** -- fixed generically with positive
  and negative controls; the original REVIEW-002 result was re-imported
  unmodified (hash verified identical) and is now accepted and consumed
  with `RESULT_STATUS=FAIL` preserved and no duplicate consumption.
- Branch 14 (new parser/fidelity defect): **yes** -- gaps reopened,
  remediated, adversarially tested.

Next action persisted by the workflow for the consumed FAIL result:
`AUTO_REMEDIATE_CONFIRMED_FINDINGS` (`next_action.json`); remediation,
focused validation, regression and re-review preparation then ran without
a scheduling prompt.
