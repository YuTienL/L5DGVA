# CAP-M6-CLARSVC-001 — `question_queue.py` N-Way Analysis

Required before building `ClarificationService` (dispatch Section 2). This
is a fresh, real re-investigation — never trusted from the Master Blocker
Register's own text, which (before this task) still read: `CAP-M5M6-
VLEVEL-001` blocked on "`question_queue.py` (diverged, M3-excluded)".

## Method

Real, structural comparison across all 5 registered sources: line counts,
`diff -w` (whitespace-insensitive) byte comparison, and a `comm`-based
function/class-signature diff — never a text summary trusted from an older
report.

## Result 1 — canonical / v50 / b7a / b7b / b8 are functionally identical

```
canonical  D:\DV\Task\L5_DGVA\dv_harness\question_queue.py                2718 lines
v50        D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness\question_queue.py 2718 lines
b7a        D:\wt\b7a\dv_harness\question_queue.py                         2718 lines
b7b        D:\wt\b7b\dv_harness\question_queue.py                         2718 lines
b8         D:\wt\b8\dv_harness\question_queue.py                         2718 lines
```

`diff -q canonical b7a` / `b7b` / `b8` → **no output** (byte-identical).
`diff -q canonical v50` → differs; `diff -w -q` (ignoring whitespace) →
**no output**. The only difference is line-ending convention (CRLF/LF);
content is identical. **No real N-way merge exists among these 4 sources —
they already ARE the same file.**

## Result 2 — canonical is a confirmed strict superset of Parent

```
Parent  D:\DV\Task\DV_Agent_Harness_L5\dv_harness\question_queue.py  1591 lines
```

`comm`-based `^def |^class ` signature diff, both directions:

- **In canonical but NOT in Parent (13 real symbols)**: `build_escalation_
  package`, `CosignNotApplicableError`, `_explain_tier_reason`,
  `render_escalation_package_markdown`, `derive_suggested_answer_from_
  design_source_inventory`, `derive_suggested_answer_from_env_manifest`,
  `file_signoff_evidence_question`, `list_clarification_requests`,
  `normalize_grounding_evidence`, `normalize_suggested_answer`, `render_
  clarification_markdown`, `request_clarification`, `build_suggest_then_
  confirm_options`.
- **In Parent but NOT in canonical: 0 symbols.**

Canonical's real capability is a **strict superset** of Parent's — every
function/class Parent has, canonical also has (confirmed present, not just
name-matched — both files were read directly).

## Result 3 — test evidence confirms the superset, not just the symbol list

```
Parent's own test suite, run in Parent's own frozen tree:   67 passed
Canonical's own test suite, run in canonical's own tree:   166 passed
```

Canonical's real, passing test count is more than double Parent's — real,
executed evidence that canonical's additional 13 functions are not dead
code, they are tested capability Parent genuinely lacks.

## Disposition

```
QUESTION_QUEUE_FOUNDATION = ALREADY_RESOLVED
```

There is no N-way merge left to perform on `question_queue.py` itself. The
Master Blocker Register's `CAP-M5M6-VLEVEL-001` row's own blocker text
("depends on `question_queue.py` (diverged, M3-excluded)") is **stale** —
disclosed and corrected in `MASTER_CAPABILITY_STATUS_MATRIX.csv` by this
task (see `M6_CLARSVC_001_IMPLEMENTATION_REPORT.md`'s own control-plane
section), not silently left wrong.

## `intake_state.py` reconciliation (CAP-ATL-007's own named job for this capability)

`CAP-ATL-007`'s own `MASTER_CAPABILITY_STATUS_MATRIX.csv` row explicitly
deferred reconciling `intake_field_resolution.py` with canonical's existing,
different, parallel `intake_state.IntakeFieldRecord`/`IntakeFieldStatus`
model to this capability. Read directly (not assumed): `intake_state.py` is
a real, already-working, NARROW join of `env.manifest.json` facts +
`question_queue.py` decisions (read-only, via `find_decision()`) +
`connectivity.py` bind tiers into one `UvmGenerationReadiness` refusal gate,
with its own distinct 8-value status vocabulary (`AUTO_RESOLVED`/`USER_
CONFIRMED`/`PARTIAL`/`CONTRADICTED`/`MISSING`/`BLOCKED`/`UNKNOWN`/`NOT_
APPLICABLE`) — genuinely different in both PURPOSE (UVM-generation-readiness
over env/connectivity facts) and SHAPE from `intake_field_resolution.py`'s
generic OpenSpec 8-attribute engine. It never calls `resolve_field()`.

**Disposition (a real decision, not silence and not a forced merge)**:
`ClarificationService` is built exclusively on `intake_field_resolution.py`'s
engine — satisfying "do not create a second Field Resolution engine" by
reusing the one generic engine that exists, rather than merging two
genuinely different-purpose modules (a large, separately-scoped, riskier
task this capability does not need to gamble on to close its own real job).
`intake_state.py` remains the real, unmodified, unmerged mechanism for its
own UVM_GENERATION_READY domain. No test or production caller anywhere in
this codebase expects the two to share one type (confirmed via the caller
sweep — see `M6_CLARSVC_001_CALLER_SWEEP.csv`); `test_intake_state.py`'s own
119 tests were re-run unchanged and pass, confirming this task did not
disturb it.
