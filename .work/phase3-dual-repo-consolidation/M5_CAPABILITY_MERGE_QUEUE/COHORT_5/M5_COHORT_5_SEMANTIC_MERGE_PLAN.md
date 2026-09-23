# M5 Cohort 5 — Semantic Merge Plan

## CAP-M5-COV-001 — functional_coverage_signoff.py (+ coverage_analysis.py dependency)

**Decision: migrate both modules' additive content, essentially verbatim,
with one disclosed comment correction.**

1. `coverage_analysis.py`: append the `Coverage Kind Classification`
   section verbatim (`COVERAGE_KIND_FUNCTIONAL`, `COVERAGE_KIND_CODE`,
   `COVERAGE_KIND_CLASSES`, `CODE_COVERAGE_METRIC_NAMES`,
   `classify_coverage_kind()`, `tag_categories_by_kind()`), with the
   `urg_summary_reduce.py`-imports-this-tuple claim corrected to disclose
   the real (not-yet-consolidated) state.
2. `functional_coverage_signoff.py`: apply the 4 real diff hunks exactly
   (docstring addition; `excluded_code_coverage_bins` computation +
   `base` dict key; conditional reason string; report-rendering markdown
   section) — verified byte-equivalent to Parent's logic via
   `diff --strip-trailing-cr` post-migration (only cosmetic
   docstring-placement/if-block-order differences remain).
3. Tests: append the 4 new tests to canonical's existing
   `test_functional_coverage_signoff.py` (11 pre-existing tests
   untouched); create `test_functional_coverage_signoff_false_pass_
   replay.py` as a new file (self-contained, no adaptation needed);
   append the 6 new `classify_coverage_kind`/`tag_categories_by_kind`
   tests to `test_coverage_analysis.py`.

**Not done this Cohort** (M5_FOUNDATION vs. M10_OPERATIONAL_COVERAGE_
CLOSURE boundary, instruction item 5): no vPlan-to-coverage-closure
traceability change, no coverage-waiver-workflow change, no coverage-delta
mechanism, no incremental re-signoff mechanism. `excluded_code_coverage_
bins` is additive reporting data only — any future M10 coverage-closure
consumer can read it without needing anything further from this Cohort.

## CAP-M5-DSI-001 — design_source_inventory.py

**Decision: no migration. SUPERSEDED disposition.** Canonical's current
behavior (per-fact-type contextual authority via
`contextual_source_precedence.py`) is a strict superset of Parent's
older, simpler model. Nothing is copied from Parent; nothing in
canonical is changed. The original M4-era "judgment call" framing is
corrected with full evidence: it was an artifact of incomplete
investigation (M4's own finding explicitly scoped to
`design_source_inventory.py` alone, without reading
`contextual_source_precedence.py`), not a genuine 50/50 design choice.

## CAP-ATL-001/002/003/008 + CAP-POOL-001/003/004/008/011/012 — reassignment, not implementation

**Decision: REGISTER + OWNER_ASSIGN + DEFER, per instruction item 3.**
None of these 10 items is implemented this Cohort. `PRIMARY_OWNER_WAVE`
is reassigned from `M5` to `M6` in both master CSVs
(`MASTER_CAPABILITY_STATUS_MATRIX.csv`, `MASTER_WAVE_OWNERSHIP_MATRIX.
csv`), `SECONDARY_DEPENDENCY` names the specific coupling reason for
each, and `NOTES` discloses this Cohort's own reassignment explicitly
(never silently reworded to look pre-existing or backdated). This is a
disclosed SCOPE-CLOSURE judgment call this Cohort is authorized to make
per its own instruction, not a unilateral technical merge decision —
flagged clearly in the final report for explicit review.

## Capability-loss check

`SOURCE_CAPABILITY_LOSS = 0` for COV-001 (every ported behavior verified
identical via re-run tests). `N/A` for DSI-001 (nothing migrated FROM
Parent; canonical's own real capability is unchanged and unaffected).
`N/A` for the 10 reassigned items (no code exists for any of them in
either Parent-as-migration-target or canonical; a wave-ownership
reassignment carries no capability with it).
