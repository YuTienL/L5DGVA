# Gap close — VKA Section 3: 資源與成本的自主管理 (test selection / seed strategy / tiered regression)

**Status: DONE** — all three audited items (3a, 3b, 3c) were confirmed BLOCKED against
current code and are now real, wired and tested.

Date: 2026-09-04. Scope: exactly Section 3, nothing else.

---

## Re-verification of the audit before building

Every BLOCKED claim in the incoming audit was re-checked against current code, not assumed:

- `grep` for `compute_impact|impact_scope|impacted_testcases|select_regression_subset|RegressionTier|regression_tier`
  across `*.py`/`*.md` returned **zero matches** — confirmed no impact computation and no tier concept existed.
- `tools/verification_flow/regression_selection_completeness_gate.py` (read in full, pre-change): only
  non-empty-category checks, a free-text `change_impact_evidence_id` presence check, and the fix-cycle
  reverify precondition. Never touched a diff.
- `tools/verification_flow/coverage_hole_regeneration_gate.py` (read in full, pre-change): the single
  `if h.get("root_cause_classification") in ("MISSING_TEST","INSUFFICIENT_CONSTRAINT","UNREACHABLE_STIMULUS")`
  branch forced **all three** classes down `regenerated_testcase_ids` + `rerun_evidence`. Confirmed miswired
  exactly as the audit described.
- `dv_harness/escalation_notify.py:99-123` — one flat `uvm_fatal_burst_threshold: int = 3`, applied
  identically regardless of run kind. Confirmed.

**One audit detail corrected:** the audit said the skill's CSV outputs "do not exist on disk", based on
`find .dv-workflow`. They do exist — at `.dv-harness/change_impact.csv` and
`.dv-harness/regression_selection.csv` (and `.dv-harness/requirements.csv`), all **header-only**: a declared
schema with no producer. That made the finding *stronger*, not weaker, and it fixed the output paths for
this work — the new code writes those exact existing files with their exact existing headers rather than
inventing a parallel artifact.

---

## 3a — Test selection by RTL-diff impact scope (was BLOCKED → now real)

**New: `dv_harness/change_impact.py`** — the missing producer for the whole
CHANGE → DESIGN → REQUIREMENT/VPLAN/PATTERN/COVERAGE → SELECTION chain, computed from real data only:

1. `changed_files()` — real `git diff --name-only <base>..<head>` (never a stub; every non-`REAL_DIFF`
   status propagates to LOW confidence rather than looking like "nothing changed").
2. `file_to_module_map()` — changed file → RTL module via the **real `rtl_modules` rows** in the DuckDB
   evidence store (written by `evidence_db.insert_rtl_parse()` from real verible `--export_json` output).
   Joins on both full path and basename, because the DB records server-absolute paths while git emits
   repo-relative ones.
3. `load_trace_registry()` — the project's own `.dv-harness/requirements.csv`
   (`REQ_ID,…,PATTERN_ID,…,COVERAGE_ID,…`). Linkage is read, never invented.
4. `select_regression()` — TARGETED (patterns of matched rows) / DEPENDENCY (patterns sharing a SCOPE with a
   matched row) / SAFETY (project's fixed smoke set) / MANDATORY_SIGNOFF (project's declared list, never
   derived so no impact computation can subtract from it).
5. `compute_and_write()` — writes `.dv-harness/change_impact.csv`, `.dv-harness/regression_selection.csv`
   and `.dv-harness/regression/computed_selection.json`.

The skill's honesty rules are **code, not prose**: a HIGH-risk file that traces to no requirement (or a diff
that could not be computed at all) sets `expand_to_full_regression`, pushing the entire known pattern universe
into DEPENDENCY. This mechanism's failure mode is "runs too much", never "silently skipped the test".

**Invocation (the part the audit specifically called out as missing):**
`dv_harness/engine.py` `_computed_regression_selection()` runs at `Stage.REGRESSION_SELECT` inside
`_gather_stage_context()`, writes the artifacts, and appends the computed sets to the real prompt.

**Enforcement:** `regression_selection_completeness_gate.py` now, when a computed artifact exists,
(a) requires the declared `change_impact_evidence_id` to **equal** the computed one — the link is checkable
instead of free text — and (b) fails `COMPUTED_SELECTION_TESTS_DROPPED` if the agent's four categories omit
any computed test. Add-only, never drop. With no computed artifact the gate is byte-for-byte its old self
(proven by a dedicated test).

**Bug the end-to-end test found and fixed:** harness metadata paths (`.dv-harness/`, `.claude/`, `docs/`, …)
were scored MEDIUM-risk-and-untraceable, so a commit that merely edited `requirements.csv` forced a full
regression. Now classified LOW (`_METADATA_ROOTS`), with real design/testbench source keeping HIGH/MEDIUM.

## 3b — Seed strategy differentiation (was BLOCKED → now real)

**Extended `dv_harness/coverage_analysis.py`** (chosen over a new parallel module, per the task's preference):

- `count_seed_attempts()` — **distinct** `seed` values per pattern from the real `jobs` rows in the evidence
  DB. This is the per-bin attempt tracking that did not exist in any form before.
- `patterns_for_coverage_id()` — COVERAGE_ID → PATTERN_ID through the same real traceability registry 3a uses
  (one loader, not two).
- `classify_coverage_hole()` — the differentiated verdict, adding the fourth class the enum was missing,
  `INSUFFICIENT_SEED_ATTEMPTS`, with `recommended_action` one of
  `GENERATE_TESTCASE_AND_RERUN` / `ADJUST_CONSTRAINT_AND_RERUN` / `ADD_SEEDS_AND_RERUN` /
  `ESCALATE_TO_QUESTION_QUEUE`. Precedence: an under-sampled bin **cannot** support an unreachability or
  constraint verdict, so the agent's claim is downgraded to "add seeds" — the "沒跑夠 → 加 seed" branch the
  audit found missing entirely.
- `escalate_unreachable_stimulus()` / `escalate_unreachable_holes()` — routes a genuinely
  `UNREACHABLE_STIMULUS` bin to `dv_harness/question_queue.py` as a **Tier-3 cannot-assume** question owned
  by the *designer*, setting `affects_pass_fail_verdict` + `affects_spec_intent` (two of the queue's three
  hard-coded Tier-3 triggers — both literally true for "may this bin be closed unhit?"). Idempotent by
  inheriting the queue's own question_key/decisions-store "asked once, never re-asked" guarantee.

**Gate rewired** (`coverage_hole_regeneration_gate.py`): each class now requires the remediation that can
actually close *that* class — regeneration for MISSING_TEST/INSUFFICIENT_CONSTRAINT (unchanged),
`added_seed_evidence` for INSUFFICIENT_SEED_ATTEMPTS, and a **real** `escalation_question_id` verified
against `.dv-harness/question_queue/questions.json` for UNREACHABLE_STIMULUS. An unrecognised class is now a
hard FAIL instead of slipping through unremediated.

**Engine performs the escalation**: `DVHarness._escalate_unreachable_coverage_holes()` runs on the
COVERAGE_CLOSURE response *before* gate evaluation, so an agent that honestly classifies a bin unreachable
gets the correct action taken for it and the gate then verifies it landed.

**Bug the end-to-end test found and fixed:** with no evidence DB (the common case today — the store is
opt-in) every pattern reports 0 seeds, and treating that as a measurement made the seed rule fire for every
hole and permanently suppress the escalation path this feature exists to open. `seed_history_available()`
now distinguishes "measured zero" from "never measured"; the seed gate is skipped in the latter, with the
reason recorded in `basis`. Reporting 0 from a store that was never written is not a measurement.

## 3c — Tiered regression escalation (was BLOCKED → now real)

**New: `dv_harness/regression_tiers.py`** — `RegressionTier` SMOKE/NIGHTLY/WEEKLY, each owning exactly three
knobs: which selection classes it admits, a time budget, and its own `uvm_fatal_burst_threshold`.

| tier | cadence | budget | UVM_FATAL | classes |
|---|---|---|---|---|
| SMOKE | per-change | 10 min | 1 | SAFETY, MANDATORY_SIGNOFF |
| NIGHTLY | daily | 240 min | 3 (= the historical flat default) | TARGETED, DEPENDENCY, SAFETY, MANDATORY |
| WEEKLY | weekly | 1440 min | 5 | full universe + all four |

Threshold direction is justified in the module docstring: the existing "3 or more suggests a systemic cause"
argument is a statement about the *fraction* of a batch, so holding an absolute count fixed across batch
sizes was the actual error. SMOKE (a handful of always-pass sanity patterns) escalates on one; WEEKLY (full
universe) does not treat 3 isolated fatals as a burst. All overridable via
`config.json: regression_tiers.<TIER>`.

Deliberately **not** conflated with `qualification.py`'s SMOKE/REGRESSION/PRODUCTION_QUALIFIED ladder — that
is a protocol *maturity* state machine, untouched here and sharing no code.

**Wired through, not just defined:**
- `escalation_notify.EscalationNotifier.uvm_fatal_burst(..., tier=, threshold=)` — flat behaviour unchanged
  when both are None.
- `regression_reporter._escalate_uvm_fatal_burst_if_needed()` reads the active-tier record and applies that
  tier's threshold. No record → flat threshold → identical to before.
- `dv-harness regression-tier list|plan|start|status|clear` — `start` resolves the tier's test list from the
  computed change-impact selection and writes `.dv-harness/regression/active_tier.json`.
- justfile: `regression-smoke` / `regression-nightly` / `regression-weekly` / `regression-tier-status`.

**Honest disclosure kept in the justfile**: those recipes are the trigger point, not a scheduler. Nothing in
this repo installs a cron entry or scheduled task; the concrete crontab / `schtasks` lines are documented for
a human to install. Claiming an installed schedule that does not exist would be fabricated evidence.

---

## Files changed

New:
- `dv_harness/change_impact.py`
- `dv_harness/regression_tiers.py`
- `dv_harness_tests/test_resource_cost_autonomy.py`

Modified (hand-scoped edits only, on files other workflows are concurrently touching):
- `dv_harness/engine.py` — `_computed_regression_selection()`, `_escalate_unreachable_coverage_holes()`,
  two call sites.
- `dv_harness/coverage_analysis.py` — seed-strategy section appended.
- `dv_harness/escalation_notify.py` — per-tier threshold parameters on `uvm_fatal_burst()`.
- `dv_harness/regression_reporter.py` — active-tier lookup at the one existing escalation call site.
- `dv_harness/cli.py` — `regression-tier` parser + dispatch.
- `dv_harness/prompts.py` — COVERAGE_CLOSURE stage text for the 4 differentiated classes.
- `tools/verification_flow/regression_selection_completeness_gate.py` — no-shrink + evidence-id match.
- `tools/verification_flow/coverage_hole_regeneration_gate.py` — differentiated remediation per class.
- `justfile` — tiered regression recipes + cadence documentation.

## Test summary

`dv_harness_tests/test_resource_cost_autonomy.py`: **22 passed** — all end-to-end over real `git init`
repositories with real commits/SHAs, a real DuckDB store written through the real production path
(`regression_reporter._write_reconciliation_evidence_if_configured` from a real `lsf_client.JobState`), real
gate **subprocesses**, a real schema-validated `QuestionQueueStore`, and the real `DVHarness.run_stage()`
path with only the LLM adapter faked. Two real defects in this change were found by these tests and fixed
(harness-metadata risk classification; fabricated under-sampled verdict with no run history).

Regression suites re-run for everything touched (engine gates/routing, coverage analysis, escalation notify
+ wiring, regression reporter, question queue, hard-gate script smoke, stage evidence checklists, stage
instruction/gate completeness, justfile, evidence DB, trend analysis) plus
`dv-harness self-audit` → `{"total": 23, "pass": 7, "fail": 0, "no_source_data": 16}`.
