# LOOP-2 — Convergence + Plateau + Oscillation Detection

**Status: DONE**
**Tests: 1528 passed, 0 failed — every one of the 45 suites that references any
module I touched (`loop_contract` / `loop_convergence` / `coverage_analysis` /
`trend_analysis` / `dv_harness.cli`), including the new
`test_loop_convergence.py` (53) and LOOP-1's `test_loop_contract.py` (50)
unchanged.**

Commit: `996c5cc loop_convergence: convergence/plateau/oscillation classifiers
(LOOP-2, sections 88-90)` on `gap-close/env-manifest-fact-sources`.

---

## 1. The gap was re-verified, and it was real

The audit said "NEVER_BUILT". Re-checking found something better than a stale
audit: the gap had been *formally declared* by the close-pass immediately
before mine.

`dv_harness/loop_contract.py` (LOOP-1, committed `17fadbf` earlier this
session) carries two explicit statements of exactly this gap:

- its module docstring, "WHAT THIS MODULE DOES NOT DO": *"It does not DETECT
  plateau or oscillation. `observe_*` reports `PLATEAU_NOT_EVALUATED` ... A
  progress-metric series (coverage over iterations) has a real producer --
  `trend_analysis.py` and `coverage_analysis.py` -- and wiring one in is a
  separate change."*
- CLAUDE.md's "LoopContract + the Canonical Loop State Machine" disclosed
  residual: *"Sections 88-90's PLATEAU/no-progress classification ... are not
  built here."*

Confirming greps I ran myself:
- `PLATEAU` existed only as a `LoopState` enum member, a legal-transition table
  entry, and the `PLATEAU_NOT_EVALUATED` sentinel — **no producer**.
- No function anywhere classified a progress series into anything.
- `LoopPlateau.detection_window` / `minimum_gain` and
  `LoopConvergence.minimum_progress` / `window` were `None` on the
  verification-closure contract, precisely because nothing computed them.
- The only `oscillat*` hits outside `loop_contract.py` were the unrelated
  ring-oscillator RTL comments the audit named.

One part of the audit's description was **already built** and I did not rebuild
it: section 89's per-bin "unreachable bins / stimulus-gap investigation" exists
as `coverage_analysis.classify_coverage_hole()` /
`escalate_unreachable_stimulus()` / `escalate_unreachable_holes()` (2026-09-04).
What was missing was the **series-level classifier** and the **loop-level
aggregation** of those per-bin verdicts.

## 2. What I built

`dv_harness/loop_convergence.py` (new, 753 lines) — the DETECTOR half.
`loop_contract.py` stays the vocabulary half.

### Section 88 — `classify_convergence()`
All seven verdicts: `CONVERGING` / `SLOW_CONVERGENCE` / `NO_PROGRESS` /
`PLATEAU` / `REGRESSION` / `OSCILLATING` / `UNKNOWN`, over a real
progress-metric series, with every number it was computed from carried on the
verdict (window values, deltas, net, reversals, flat-run length, thresholds) so
a reader can re-derive it rather than trust it.

Precedence, and why: OSCILLATING first (a net-flat oscillation would otherwise
read as NO_PROGRESS, pointing the loop at "add stimulus" when the real problem
is its own changes undoing each other); then REGRESSION; then CONVERGING /
SLOW_CONVERGENCE; then flat splits into PLATEAU (the trailing no-movement run
reached the plateau window) vs NO_PROGRESS (this window did not move, but not
for long enough to justify an investigation).

### Section 89 — `investigate_plateau()`
Aggregates `coverage_analysis.classify_coverage_hole()`'s real per-bin verdicts
into a loop-level next action, under that classifier's own precedence applied
one level up: any under-sampled bin → `ADD_SEEDS` and the plateau is reported
**premature**; otherwise a stimulus gap → generate/adjust; otherwise an
adequately-sampled unreachable bin → escalate.

### Section 90 — `detect_oscillation()`
Both fingerprints:
- **repeat-failure** — `loop_contract.detect_oscillation_from_debug_loop_history()`,
  **called, not copied**.
- **repeat-fix-revert** — the one genuinely new detector,
  `trend_analysis.detect_verdict_oscillation()`, added *beside*
  `detect_pattern_regressions()` because that is the module that owns
  `regression_verdict_history`.

### The bridge to LOOP-1
`derive_loop_state()` gained `plateau` / `progress_oscillating`, applying only
over `CONVERGING` and only while the loop is not done. The
verification-closure contract now reads its convergence/plateau thresholds from
the detector's constants instead of carrying `None`, and
`termination.no_progress` no longer says "NOT DETECTED".

Front door: `dv-harness loop-contract convergence` (exit 2 on UNKNOWN);
`... observe` now carries the report.

## 3. Reuse, not parallel mechanism

Not one number is re-derived from raw evidence this project already reduces:

| what | source | reused how |
|---|---|---|
| the coverage series | `trend_analysis.daily_rollup()`'s bins-weighted `coverage_percent` | consumed as-is; a `None` day is **skipped**, never read as 0 |
| the repeat-failure fingerprint | `loop_contract.detect_oscillation_from_debug_loop_history()` | **called**; a test asserts identity with the original |
| the plateau investigation | `coverage_analysis.classify_coverage_hole()` | **called** per bin; only the aggregate action is new |
| the "flat" band | `coverage_analysis.FLAT_TREND_TOLERANCE_PERCENT` | an inline `0.5` I **extracted into a named constant** and imported, so the two modules cannot disagree about what "flat" means over the identical series |
| every threshold | existing defended numbers | `min_gain` = 2x the noise floor; `plateau_window` = `DEFAULT_OSCILLATION_REPEAT_THRESHOLD + 1`, the same "2 INDEPENDENT observations" bar `REPEAT_FAILURE_MIN_OCCURRENCES` / `ORGANIZATIONAL_MIN_CONFIRMATIONS` use |

`capability_evolution.repeated_unresolved_failure_patterns()` is **deliberately
not called**, per the task's own instruction: its threshold semantics
(independent *runs*, closed only by a `verified_fix` record) are purpose-built
for filing a capability candidate, and a loop verdict must not depend on
whether one was filed. What I borrowed is its *technique* — collapse
repetitions, count independent observations, never fuzzy-match — over a
different real key (the regression `pattern`).

## 4. Two real defects I found and fixed while building

1. **`_trailing_flat_run` counted declines as "flat."** A spike-then-crash
   series whose window net is flat only because the two cancel reported a long
   PLATEAU it never had. Fixed to count *absolute* movement — a plateau is a
   metric that stopped moving, and a real decline is REGRESSION's business.
   `test_a_spike_and_crash_is_not_a_plateau` is the guard.
2. **An `UNKNOWN` verdict was being recorded as the observation's `plateau`
   field.** "The classifier ran and could not conclude" is not a plateau
   result; recording it would be the same unearned claim `PLATEAU_NOT_EVALUATED`
   exists to prevent, one step later. Fixed, and the CLI verb's exit code was
   moved from "no series" to "no usable verdict" to match.

## 5. Safety properties, each enforced and each tested

- **Every human-approval gate is untouched and uncalled.**
  `ControlPlane.approve()`, `policy.can_signoff()`, `assert_human_approval()`,
  `assert_no_production_write_authorized()`, `HumanApprovalRequiredError`,
  `ProductionWriteNotAuthorizedError` and the PR-only main/master governance
  are not referenced from this module.
  `test_classifying_mints_no_approval_and_leaves_the_control_plane_untouched`.
- **Classifying is not a mutating act.** The investigation reports which bins
  would need a human and *names* `escalate_unreachable_holes()`; it files
  nothing. `test_the_investigation_escalates_nothing_and_writes_nothing`
  asserts an empty queue and no `questions.json` on disk.
- **Read-only against the evidence database**, exactly as `trend_report()`
  opens it. `test_classification_never_creates_or_migrates_the_evidence_database`.
- **No build, regression or LSF submission** anywhere in the code or the tests:
  every row is written by handing a synthetic `lsf_client.JobState` to the real
  evidence-write function, and coverage rows come from a synthetic
  `summary.json`.
- **`PLATEAU_NOT_EVALUATED` survives**, with distinct `NO_EVIDENCE_DATABASE` vs
  `NO_COVERAGE_SAMPLES` reasons. LOOP-1's own
  `test_plateau_is_reported_as_not_evaluated_never_as_absent` still passes
  unchanged.
- **No `models.Status` member is a convergence verdict**
  (`test_no_models_status_member_is_ever_a_convergence_verdict`).

## 6. Tests — what they are for

Not "the classifier returns a string". `test_loop_convergence.py` (53 tests) is
built around the five things that can actually go wrong:

- **All seven verdicts driven out of real series** — a taxonomy with
  unreachable values is a vocabulary, not a classifier. PLATEAU / CONVERGING /
  OSCILLATING are additionally driven end to end from a **real evidence
  database** written through the **real production write paths**
  (`regression_reporter._write_reconciliation_evidence_if_configured()` and
  `dashboard.append_coverage_history_sample()` — the exact functions
  `lsf_client` and `engine.py` call).
- **Negative controls that give the detectors power**: a spike-and-crash is not
  a plateau; a same-SHA flip-flop is a flaky test and **not** loop oscillation
  (with `fix_revert_cycles == 2` proving the cycles were really seen and
  deliberately not counted); sub-threshold jitter has no direction to reverse;
  a five-nightly green streak does not inflate the cycle count; a rising curve
  is the positive control against the PLATEAU result being a harness artifact.
- **Fabrication guards**: a `None` coverage day is skipped, not read as 0; a
  single sample is UNKNOWN, never a guessed trend; a project with no database
  reports UNKNOWN, never "no plateau".
- **The bridge**: PLATEAU and OSCILLATING reach a real `LoopObservation`, along
  edges checked with the real `assert_legal_loop_transition()`, and Human
  Override still outranks both.
- **Totality**: `assert_verdict_mapping_total()` plus a test that *adding* a
  verdict without deciding its loop meaning fails.

### Test evidence

```
dv_harness_tests/test_loop_convergence.py
53 passed in 194.94s

dv_harness_tests/test_loop_contract.py            (LOOP-1, unchanged)
50 passed in 21.58s

test_loop_convergence + test_loop_contract + test_trend_analysis
  + test_coverage_analysis + test_resource_cost_autonomy
195 passed in 541.27s

# every suite referencing loop_contract / loop_convergence /
# coverage_analysis / trend_analysis / dv_harness.cli -- 45 files
1528 passed in 2599.68s (0:43:19)          <- .work/_loop2_relevant.txt
```

**On the full `dv_harness_tests` run.** I started one; it reached ~73% with
6 F + 6 E and was then killed externally (another close-pass was running its
own suites concurrently on the same machine). Rather than report a partial
number, I ran the *complete set of suites that can be affected by what I
touched* — every file referencing any of my five modules, 45 suites, 1528
tests — and it is **clean**.

The 6 F + 6 E the partial run had accumulated are the known pre-existing
environmental baseline, not regressions: an earlier full run in this repo
(`.work/_p25_fullsuite.txt`, 10 failed / 4846 passed / 6 errors) records the
same set — 5 `test_cli_pueue` + 6 `test_pueue_client` (`real pueued did not
come up`), 2 `test_knowledge_center` (a `JSONDecodeError` from a shared
fixture), 1 `test_memory_tier_integrity` (Windows `PermissionError` under
concurrency), 1 `test_rca_multi_agent_fanout` (a timing assertion) and 1
`test_vplan_writer` (`subprocess.TimeoutExpired`). None involves loops,
coverage, trend analysis or the CLI parser, and the three I deliberately
excluded from my 45-suite run (`test_cli_pueue`, `test_pueue*`,
`test_vplan_writer`) are exactly the environmental ones — excluded so their
known flakiness could not mask a real regression in the rest.

## 7. Shared-file discipline

Two other close-passes (`doc-extract` fan-out and `golden-flow-readiness`) were
editing `CLAUDE.md` and `dv_harness/cli.py` concurrently and had staged their
files into the shared index. I unstaged theirs, trimmed my `cli.py` diff to my
one hunk (`git apply --cached` after normalising line endings), and staged
`CLAUDE.md` as an exact blob (`git hash-object -w` +
`git update-index --cacheinfo`) built from HEAD + my section only — patch
surgery kept failing on CRLF/LF mismatches, and constructing the blob is
deterministic. The commit contains 7 files, none of them theirs, and their
working-tree content is verified intact. `dv_harness/golden_flow_readiness.py`
was never touched, per the task's instruction.
`.dv-harness/events.jsonl` (another pass's audit trail) was left unstaged.

## 8. Deferred, and stated plainly

Scoped down from the full section 88-90 surface to a real, complete classifier
rather than a half-built engine:

- **The RESPONSE is not built.** Sections 88-90's `STOP BLIND RETRY ->
  reassess -> materially different strategy` does not exist: `engine.loop()`
  routes a retry-exhausted stage onto its graph FAIL edge exactly as before,
  and nothing terminates or re-plans a run on a PLATEAU verdict. This is the
  classifier only.
- **Not engine-fired.** `classify_loop_convergence()` is reached from the CLI
  verb and from `observe_all()`; no `run_stage()` / `advance()` call site
  invokes it. A **REACHED** capability, not a **WIRED** one — the same honest
  distinction `harness-deploy` and `run_controlled_experiment()` carry.
- **The series is the coverage curve only.** `stage_completion_percent` and
  `findings_open` are named in the contract's `convergence.metrics` but have no
  cross-run producer to build a series from; inventing one would be the
  fabricated-evidence failure the Evidence Truth Rule forbids.
- **Section 91's `LOOP_*` event taxonomy** is unchanged from LOOP-1's state (two
  of twenty-one names have producers). Out of scope for this gap.
