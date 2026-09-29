# CAP-M5-COV-001 — functional_coverage_signoff.py — Analysis

## The exact accepted contract (from `M4_M5_PREREQUISITE_MATRIX.csv`, not inferred from the ID/name)

The original M4-wave finding: "distinguish
`ALL_DECLARED_CATEGORIES_ARE_CODE_COVERAGE` from
`NO_DECLARED_COVERAGE_GOAL`; v50 always returns the latter for both" —
flagged as `PARTIAL (which return value is canonically correct for which
real input condition requires a human/DV-domain judgment call --
explicitly not a foundation question M4 can resolve alone)`.

## Why the "judgment call" framing no longer holds, given fuller evidence

M4's own finding was scoped to reading `functional_coverage_signoff.py`
alone, without investigating WHY Parent's version could tell the two
conditions apart. This Cohort's deeper read found the real mechanism:
Parent's `functional_coverage_signoff.py` change depends on a **second**
Parent-side addition, `coverage_analysis.classify_coverage_kind()` — a
real, evidenced, tested classifier absent from canonical
(`coverage_analysis.py` diff: canonical 1034 lines, Parent 1129 lines,
purely additive). Once that dependency is read, the "judgment call"
resolves to a plain fact question with a real, cited, verifiable answer:

- `classify_coverage_kind()` classifies a coverage category name as
  `CODE` when it is literally one of `CODE_COVERAGE_METRIC_NAMES =
  ("line", "cond", "fsm", "tgl", "branch")` — the exact 5 metrics VCS's
  own `-cm` option is fixed to by this project's real Makefile
  (`CM_OPTS := line+cond+fsm+tgl+branch`), otherwise `FUNCTIONAL`.
- The two reason strings are not competing "correct answers" to choose
  between — they answer two genuinely DIFFERENT real conditions:
  `NO_DECLARED_COVERAGE_GOAL` when nothing was declared at all;
  `ALL_DECLARED_CATEGORIES_ARE_CODE_COVERAGE` when something WAS
  declared, but every declared name turns out to be code coverage, not
  functional. Canonical's pre-migration behavior collapsed both into the
  first string, losing real diagnostic information.

This is evidence that SETTLES the question rather than one requiring a
human preference between two equally valid options — confirmed by:
Parent's own real, cited audit finding (`.dv-harness/
l5dgva_audit_result_E.md`: "coverage_analysis.py has no code-coverage
(UCIS/URG) parser at all; no code-enforced distinguishing rule"), a real
documented false-PASS incident (a project whose evidence DB records only
a pure code-coverage category could reach
`FUNCTIONAL_COVERAGE_SIGNOFF_READY = True` with zero functional coverage
ever measured), and a real governance-failure replay test proving the
incident is reproducible on the actual code path (ported as
`test_functional_coverage_signoff_false_pass_replay.py`).

## SOURCE_INPUTS / CANONICAL_CURRENT_BEHAVIOR / SOURCE_VERIFIED_BEHAVIOR

| Field | Value |
|---|---|
| `SOURCE_INPUTS` | Parent HEAD `3e9dd736` (`dv_harness/coverage_analysis.py`, `dv_harness/functional_coverage_signoff.py`); v50 confirmed content-identical to canonical pre-migration (diff was pure CRLF/LF, verified via `diff --strip-trailing-cr`) |
| `CANONICAL_CURRENT_BEHAVIOR` (pre-migration) | `declared_names` never filtered by kind; empty-after-scope-resolution always reports `"NO_DECLARED_COVERAGE_GOAL"`; no `excluded_code_coverage_bins` key |
| `SOURCE_VERIFIED_BEHAVIOR` (Parent) | Real, tested (17+14 relevant tests re-run in Parent's own tree, all pass), real cited audit-gap closure, purely additive to both files |

## CALLERS (real, scoped sweep — see `M5_COHORT_5_CALLER_SWEEP.csv` for full detail)

3 real production callers of `analyze_functional_coverage_signoff()`:
`exec_eng_dashboard.py`, `gui_vip_coverage_wizard.py`,
`signoff_blocker_list.py`. All three read `report.get("reason")` as an
opaque passthrough/display string — none string-match the specific
literal `"NO_DECLARED_COVERAGE_GOAL"` (confirmed by grep: that literal
appears exactly once in all of canonical, the module's own source line).
293/293 of these 3 callers' own test suites (plus `spec_vplan_readiness_
gate.py`/`question_queue.py`, cited in the same docstring family) pass
unchanged after migration.

## SCHEMAS / TESTS / DEPENDENCIES / PUBLIC_CONTRACTS / OWNER_BOUNDARY

- `SCHEMAS`: no JSON Schema exists for this module's report shape anywhere in canonical or Parent — no schema-break risk.
- `TESTS`: 76/76 pass after migration (11 pre-existing canonical + 4 new in `test_functional_coverage_signoff.py`; 2 new files — `test_functional_coverage_signoff_false_pass_replay.py`; 6 new in `test_coverage_analysis.py`).
- `DEPENDENCIES`: `coverage_analysis.classify_coverage_kind()`/`COVERAGE_KIND_CODE`/`CODE_COVERAGE_METRIC_NAMES` (new, migrated this Cohort); `evidence_db.EvidenceStore`/`default_db_path` (pre-existing, unmodified).
- `PUBLIC_CONTRACTS`: `analyze_functional_coverage_signoff()`'s own signature is UNCHANGED — only its return dict gains one additive key (`excluded_code_coverage_bins`) and one reason-string branch. `PUBLIC_SIGNATURE_BREAK = 0`, `RETURN_SCHEMA_BREAK = 0` (additive only, no schema exists to break), `CALLER_COMPATIBILITY = confirmed safe`.
- `OWNER_BOUNDARY`: `M5_FOUNDATION` per instruction item 5 — this Cohort migrates the CLASSIFICATION capability and its consumption in the signoff READER only. It does NOT implement the full `M10_OPERATIONAL_COVERAGE_CLOSURE` architecture (vPlan-to-coverage-closure traceability, coverage waivers workflow, coverage delta, incremental re-signoff) — those remain M10's job, and nothing in this migration's shape conflicts with or pre-empts them; `excluded_code_coverage_bins` is additive reporting data any future M10 coverage-closure consumer can read without change.

## One correction made during migration (comment hygiene / Evidence Truth Rule)

Parent's own docstring/test comments claim
`tools/coverage/urg_summary_reduce.py`'s `CODE_COVERAGE_METRICS` constant
"imports this tuple by identity rather than re-declaring it." Direct read
of that file (both in Parent and canonical) shows this is **not true** —
it still locally re-declares an identical-value tuple, importing only
`parse_coverage_summary`/`CoverageAnalysisError` from `coverage_analysis`.
Corrected in the migrated docstring/comment to disclose this as a real,
open (not-yet-closed) consolidation opportunity rather than propagate a
false already-done claim.
