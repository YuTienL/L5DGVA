# M8 Constitution Qualification Plan (CAP-M4.5-003)

Preflight evidence only -- FIND, not FIX. No production code touched, no
hook/CI config changed.

## Real module identity

- `dv_harness/constitution_gate.py` (90 lines) -- the entire real
  implementation. Single function `check_constitution_intact(root)`
  (line 55-89), returns a frozen `ConstitutionCheckResult(status,
  reasons)` (line 49-52). Never raises.
- Canonical text: `docs/architecture/L5DGVA_CONSTITUTION.md` (269 lines).
- Tests: `dv_harness_tests/test_l5dgva_constitution.py`, 10 real tests,
  no mocking, reads the real on-disk files.
- No CLI verb exists (`grep -n constitution dv_harness/cli.py` -> 0
  hits).

## What the gate actually checks (its own real rules, not invented ones)

Deliberately narrow, textual/positional intactness only, never
behavioral:

1. `docs/architecture/L5DGVA_CONSTITUTION.md` exists (line 64-65).
2. Text contains the literal string `"Article 0"` (line 68-69).
3. Text contains all 5 `CONSTITUTIONAL_DIMENSIONS` (line 30-36, checked
   70-72): `LOCATION_INDEPENDENT`, `EVIDENCE_GROUNDED`, `KNOWLEDGE_
   DRIVEN`, `CONTINUOUS_EVOLUTION`, `END_TO_END_DV_ALIGNMENT`.
4. Text contains `ANTI_DRIFT_MARKER = "ARCHITECTURE_CONFLICT"` (line 38,
   checked 73-74).
5. `CLAUDE.md` exists (line 77-78).
6. `CLAUDE.md` contains both `"Article 0"` and the literal constitution
   doc path (line 81-82).
7. `CLAUDE.md`'s `"Article 0"` occurrence appears BEFORE `"Core
   Operating Rules"` (a position check, line 84-87).

## Rule -> Capability -> Evidence -> Required Evidence -> Exit Test

| Rule | M8 Capability | Current evidence | Required evidence | Exit test |
|---|---|---|---|---|
| Constitution doc exists at canonical path | CAP-M4.5-003 | Verified live: present, 269 lines | No change -- satisfied | `test_constitution_document_exists_at_the_canonical_path` (exists, passes) |
| Doc names "Article 0" + all 5 dimensions | CAP-M4.5-003 | Verified live: all 5 tokens present | No change -- satisfied | `test_constitution_document_contains_article_0_and_all_five_dimensions` (exists, passes) |
| Doc names Anti-Drift Rule + `ARCHITECTURE_CONFLICT` marker | CAP-M4.5-003 | Verified live: both present (doc line 181-188) | No change -- satisfied | `test_constitution_document_contains_the_anti_drift_rule` (exists, passes) |
| CLAUDE.md carries the Article 0 pointer | CAP-M4.5-003 | `check_constitution_intact('.')` -> PASS, 0 reasons, run live this task | No change -- satisfied | `test_claude_md_carries_the_article_0_pointer` (exists, passes) |
| CLAUDE.md's Article 0 precedes Core Operating Rules | CAP-M4.5-003 | Verified via same live PASS run | No change -- satisfied | `test_claude_md_article_0_section_precedes_core_operating_rules` (exists, passes) |
| Gate is automatically invoked (not only on-demand) | CAP-M4.5-003 (the row's own `BLOCKER`) | **NOT SATISFIED**: no CLI verb; not one of `self_audit.py`'s 23 gates (0 "constitution" hits); `tools/git-hooks/pre-push` runs only `import-sanity,self-audit` (line 123), not the full suite; only incidental coverage via `.github/workflows/dv-harness-ci.yml:105`'s full `pytest -q` on push/PR/nightly-cron -- and whether any Actions run has genuinely fired on this private, unauthenticated-`gh` repo is itself unverifiable from this machine | A named CI step or a `dv-harness constitution-check` verb wired into self-audit/pre-push/session-start, PLUS confirmation the CI workflow has actually executed at least once | No existing test proves "runs automatically" -- would need a new test asserting the verb/step exists and is referenced by name, analogous to `test_self_test_gate_e2e.py`'s CI-disclosure-token pattern |
| `L5DGVA_CONSTITUTIONAL_COMPLIANCE = PASS` (13 named final-acceptance sub-criteria) | CAP-M4.5-003 (final), overlapping CAP-M8-EXPLOOP-001 (internal loop), CAP-M8-MAKC-001 (knowledge consumption), CAP-M4.6-002 (discoverability) | **NOT SATISFIED, NOT CODED**: exhaustive grep for `L5DGVA_CONSTITUTIONAL_COMPLIANCE`/`HIGHEST_PRINCIPLE_COMPLIANCE`/`CANONICAL_CAPABILITY_STRICT_SUPERSET` in `dv_harness/` finds only `constitution_gate.py`'s own `FINAL_COMPLIANCE_STATUS_INTERMEDIATE = "NOT_YET_QUALIFIED"` (line 46) -- a fixed sentinel string, not a computed composite | A real `FINAL_COMPLIANCE_GATE`-style function computing each of the 13 named sub-criteria (`L5DGVA_CONSTITUTION.md` lines 215-232) from real evidence sources and compositing them, PLUS the underlying capabilities (CAP-M8-EXPLOOP-001/002, CAP-M8-MAKC-001) actually becoming real -- a multi-capability dependency chain, not a single-module fix | `test_final_constitutional_compliance_is_not_yet_pass_status_is_a_distinct_value` exists today but only proves the intermediate constant `!= "PASS"` -- no real composite evaluator test exists because no evaluator exists. A real exit test would assert a computed `FinalComplianceResult`'s per-sub-criterion values against live evidence, analogous to `l5dgva_governing_objective_verdict.py`'s existing pattern elsewhere in this codebase |
| Silent weakening detection | CAP-M4.5-003 | Verified live: 3 real tamper-simulation tests pass, `tmp_path`-based | No change -- satisfied | `test_check_constitution_intact_fails_when_constitution_doc_is_missing`, `..._when_claude_md_pointer_is_missing`, `..._when_a_dimension_is_silently_removed` (all exist, all pass) |

## Automatic invocation: PARTIAL

Evidence FOR partial (not full NO): `.github/workflows/dv-harness-ci.yml`
line 105 collects `test_l5dgva_constitution.py` incidentally as part of
the full suite -- real, but not a dedicated named step, and whether it
has genuinely executed on GitHub Actions for this repo is unverifiable
from this machine (private repo, unauthenticated `gh`).

Evidence AGAINST full YES: `tools/git-hooks/pre-push` (the repo's live
`core.hooksPath`) runs only `import-sanity,self-audit` -- a deliberately
fast subset excluding the constitution test at push time; `self_audit.py`
has zero constitution references; no `dv-harness` CLI subcommand exists;
no session-start hook references it. Matches the Capability Matrix's own
disclosed blocker text verbatim.

## Final compliance gate definition: NOT FOUND, aspirational label only

Confirmed by exhaustive grep -- only `constitution_gate.py`'s own
`FINAL_COMPLIANCE_STATUS_INTERMEDIATE` sentinel exists, never a computed
evaluator. The Constitution doc itself is explicit this is deliberately
un-computed at intermediate waves ("Migration-Wave Scoping" section: no
single wave may satisfy Article 0 in full); `constitution_gate.py`'s own
docstring states textual-intactness checking is its whole job, distinct
from the final-product gate.

## Real current gate output (run live this task)

```
>>> from dv_harness import constitution_gate as cg
>>> cg.check_constitution_intact('.')
status: PASS
reasons: []
```

## Verdict

`CAP-M4.5-003` status: `INSTALLED, ENFORCED` for textual intactness
(real, PASS, live-confirmed), `NOT_YET_QUALIFIED` for `FINAL_
COMPLIANCE` (no coded evaluator exists at all -- a real M8-owned gap, not
merely "not run yet"). Automatic invocation is genuinely PARTIAL, not a
simple YES/NO. This is a multi-capability composite: the 13 named final-
acceptance sub-criteria structurally depend on CAP-M8-EXPLOOP-001,
CAP-M8-MAKC-001, and CAP-M4.6-002 all becoming real -- Constitution
final-compliance is not a standalone fix, it is the rollup of the rest of
M8's own scope.
