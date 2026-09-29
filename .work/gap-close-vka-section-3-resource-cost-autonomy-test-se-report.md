# Section 3 — 資源與成本的自主管理 (Resource/Cost Autonomy) — Gap-Close Pass

**Verdict: NO_ACTION_NEEDED** (already closed; audit finding handed to this pass was stale)

Re-verified 2026-09-04 against current HEAD. No file modified in this pass.

## Headline

The audit finding driving this task marked all three items **BLOCKED** and said the
closing code did not exist. That finding is **stale**. Commit `a8d97f2` ("Close Section 3
resource/cost autonomy: RTL-diff test selection, seed strategy, regression tiers") already
built all three, and it **is reachable from current HEAD**:

```
$ git merge-base --is-ancestor a8d97f2 HEAD && echo YES
YES
$ git branch --contains a8d97f2
* gap-close/env-manifest-fact-sources
  master
```

I did not take the commit message as evidence. Every verdict below is re-derived from
reading the current code, running the real test suite, and driving the real CLI myself.

## Item 3a: Test selection by RTL-diff impact scope — **READY**

The audit's four "what's missing" points, each re-checked against current code:

1. **Runs `git diff` against a base SHA** — `dv_harness/change_impact.py` (715 lines).
   Proven live below: it resolved a real base/head SHA pair from this repo's actual history.
2. **Maps changed files to hierarchy/requirement/pattern IDs** — resolves against the real
   `rtl_modules` evidence-DB table and the real `.dv-harness/requirements.csv` registry.
   Covered by `test_3a_rtl_module_join_uses_real_verible_parse_rows`.
3. **Programmatically emits targeted/dependency/safety sets** — `change_impact.csv` /
   `regression_selection.csv` (the two files the audit correctly found header-only) now
   have a real producer.
4. **Invoked at `REGRESSION_SELECT`** — `dv_harness/engine.py:790`
   (`_computed_regression_selection`) and `engine.py:2553`, which fires on
   `stage == Stage.REGRESSION_SELECT.value`. Covered end-to-end by
   `test_3a_run_stage_computes_the_selection_and_shows_it_to_the_agent`.

The gate is no longer pure attestation: it enforces an asymmetric add-only rule (the agent
may add tests, never drop a computed one) — `test_3a_gate_rejects_a_selection_that_drops_a_computed_test`.

**Live verification I ran myself** (not from the test suite):

```
$ python -m dv_harness regression-tier plan NIGHTLY --base-sha HEAD~2
{ "tier": "NIGHTLY", ..., "change_impact_evidence_id": "CI-9d4a166e894804b2" }
```

and the artifact it really wrote:

```
BASE_SHA,HEAD_SHA,CHANGED_FILE,IMPACTED_AREA,REQ_ID,...,RISK,CONFIDENCE
04dbf11...,c9a1ed7...,.work/gap-close-...-report.md,...,LOW,HIGH
```

Two real changed files, correctly scored LOW risk / HIGH confidence, and correctly **not**
expanded to full regression because the diff was documentation-only. That is real
computation over a real diff, matching `test_3a_doc_only_change_does_not_expand`.

## Item 3b: Seed strategy differentiation — **READY**

The audit's central complaint — that the gate forced all three root-cause classes down the
same "regenerate a testcase" path, actively defeating the differentiation — is fixed.

- Per-bin distinct-seed-attempt tracking from real `jobs` rows —
  `test_3b_seed_attempts_come_from_real_job_rows`.
- The missing "hasn't run enough yet" class exists: `INSUFFICIENT_SEED_ATTEMPTS`
  (`dv_harness/coverage_analysis.py:269`), routed to *add seeds*, not a new testcase —
  `test_3b_under_sampled_bin_routes_to_add_seeds_not_a_new_testcase`.
- `UNREACHABLE_STIMULUS` now escalates to the real question queue
  (`coverage_analysis.py:496,528,540`; `CLASSES_REQUIRING_HUMAN_ESCALATION` at line 290)
  rather than demanding a testcase it provably cannot close —
  `test_3b_adequately_sampled_unreachable_bin_escalates_to_the_real_question_queue`.
- The blanket requirement is gone but not over-corrected: the two classes that genuinely
  need regeneration still require it —
  `test_3b_gate_no_longer_demands_a_testcase_for_an_unreachable_bin` **and**
  `test_3b_gate_keeps_the_regeneration_requirement_for_the_two_classes_that_need_it`.
- Notably, the classification is no longer purely agent free-text: a zero-seed report from
  an unwritten store is refused as a measurement —
  `test_3b_no_seed_history_does_not_fabricate_an_under_sampled_verdict`.

## Item 3c: Tiered regression escalation — **READY**

`RegressionTier` SMOKE/NIGHTLY/WEEKLY exists (`dv_harness/regression_tiers.py:117`) and is
wired through escalation, not just declared. **Live output I ran:**

```
$ python -m dv_harness regression-tier list
TIER     CADENCE                              BUDGET(min)  UVM_FATAL  CLASSES
SMOKE    per-change (pre-submit / post-push)  10           1          SAFETY,MANDATORY_SIGNOFF
NIGHTLY  daily                                240          3          TARGETED,DEPENDENCY,SAFETY,MANDATORY_SIGNOFF
WEEKLY   weekly                               1440         5          FULL+TARGETED,DEPENDENCY,SAFETY,MANDATORY_SIGNOFF
```

This is exactly the "fast subset on a short budget with a looser threshold vs. expanded set
with a stricter one" the audit said had no code path. Distinct test sets, distinct time
budgets, distinct `uvm_fatal_burst_threshold` per tier.

- Threshold really changes escalation behavior (not cosmetic) —
  `test_3c_per_tier_uvm_fatal_threshold_actually_changes_whether_escalation_fires`
  and `test_3c_reconciliation_cycle_applies_the_active_tier_threshold`;
  wired at `escalation_notify.py:224-246` and `regression_reporter.py:177-192`.
- Scheduling/cadence is documented as real external triggers (cron + `schtasks`) with
  recipes at `justfile:272-296`.
- Backward-compatible: NIGHTLY keeps the historical flat threshold of 3, so an un-migrated
  project behaves as before.
- Fails safe: `test_3c_unknown_tier_is_a_hard_error_never_a_silent_default`.

## Test summary

`dv_harness_tests/test_resource_cost_autonomy.py` — **22 passed** (258s). Genuinely
end-to-end, not mocked: **0** occurrences of `mock`/`monkeypatch`, **22** real `subprocess`
invocations over real git repos, a real DuckDB store and real gate subprocesses.

Regression check across every suite touching the changed modules —
`test_coverage_analysis.py`, `test_escalation_notify.py`, `test_escalation_wiring.py`,
`test_regression_reporter.py`, `test_regression_list_manager.py` — **99 passed** (98s).
Confirms no drift from the concurrently-active workflows in this repo.

## Housekeeping

Driving the CLI live as evidence caused it to write its real artifacts, which dirtied two
tracked files (`.dv-harness/change_impact.csv`, `.dv-harness/regression_selection.csv`) and
created `.dv-harness/regression/`. Since this pass was audit-scoped and other agents are
active in this repo, I reverted all three; the working tree is clean with respect to them.

## Note for the orchestrator

The stale audit is worth flagging: it was presented as "real evidence gathered just now",
but its central grep claim (`compute_impact`/`impact_scope`/`select_regression_subset`
returning zero matches) does not hold against the tree it was supposedly gathered from —
`dv_harness/change_impact.py` and `dv_harness/regression_tiers.py` were already committed
and reachable. Had I acted on the finding as written, I would have rebuilt all three
mechanisms in parallel with working ones.
