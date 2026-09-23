# M5 Final Closure Regression — Raw Results

## Checkpoint

```
PROCESS_CWD = /d/DV/Task/L5_DGVA
REPO_ROOT   = D:/DV/Task/L5_DGVA
CURRENT_BRANCH = canonical/m4-dependency-closure
REGRESSION_HEAD = 789be4d1665f6c70eab90d64e30cb17db61ca7f6
```

`git status --short` immediately before launch: only `.dv-harness/events.jsonl`
modified (the established, permitted auto-generated telemetry exception —
append-only `CLI_ACCESS` records dated before this session, confirmed by
`git diff` to carry no config/behavioral content; cannot affect test
behavior). `WORKING_TREE_PRODUCTION_CHANGES = 0`.

**Disclosed timing deviation from Section 2's freeze**: after launching the
regression, one new file (`M5_FINAL_CAPABILITY_PRESERVATION_AUDIT.md`) was
written to `.work/phase3-dual-repo-consolidation/M5_POOL_CLOSURE/` while the
run was in progress. This file is outside `dv_harness/` and
`dv_harness_tests/` — nothing pytest collects or `dv_harness` imports — so it
structurally could not have affected the run. `git rev-parse HEAD` after
completion confirms `REGRESSION_HEAD` unchanged (`789be4d1...`).
`REGRESSION_HEAD_MISMATCH = NO`. No further working-tree writes were made
until the regression had fully completed.

## Invocation

```
python3 -u -m pytest dv_harness_tests/ -v --durations=25
```

No `pytest-timeout` plugin is installed in this environment (confirmed
before launch); none was installed to add one, per this task's own
qualification-only scope. No per-test hard timeout was therefore possible;
Section 7's hang discipline (identify current test / process state / CPU
evidence / elapsed time before classifying a stall) was applied instead via
live monitoring.

## Hang discipline applied (Section 7)

The regression was watched via a background monitor polling the live log's
last line every 30s from launch (00:08:28) to completion (01:04:56,
`3386.51s` / `0:56:26` later). Progress advanced through the alphabetized
test-file order continuously — no single test name repeated across two
consecutive 30s polls at any point in the run. Two points were flagged for
extra scrutiny given a prior, separate full-suite attempt (outside this
regression's own scope) had previously hung: `test_pueue_client.py::
TestRealPueueIntegration::test_real_version` and `test_self_test_gate_e2e.py`
— both cleared within one 30s poll interval each, confirming they were not
the prior hang's cause. `HANG_STATUS = NO`.

## Result

```
COLLECTED (pytest's own "collected N items / M skipped" header) = 13399 items / 29 collection-skipped
FINAL SUMMARY (pytest's own structured end-of-run line, authoritative for outcome tallies):
  = 40 failed, 13318 passed, 69 skipped, 1 xfailed, 1 warning in 3386.51s (0:56:26) =

PASSED   = 13318
FAILED   = 40   (structurally re-counted: `grep -c "^FAILED "` = 40, exact match)
SKIPPED  = 69
XFAILED  = 1
ERRORS   = 0    (no `^ERROR ` structured lines in the short-summary section)

START_TIME (process launch) = 00:08:28 (2026-09-24)
END_TIME (process exit, per monitor)  = ~01:04:56 (2026-09-24)
DURATION = 3386.51s (0:56:26), per pytest's own reported wall-clock

CHILD_EXIT_CODE = 1 (inferred from pytest's documented exit-code contract —
  1 means "tests were collected and run but some failed" — consistent with
  the real completed summary line above; the exact code was not separately
  captured via `$?` since the process ran via `nohup ... &`, disclosed here
  rather than silently assumed equivalent to a captured value)
CRASH_STATUS = NO (completed to its own structured summary line, no
  INTERNALERROR / traceback-outside-a-test-case observed)
TIMEOUT_STATUS = NO (no external timeout was applied or triggered; the run
  completed under its own natural duration)
HANG_STATUS = NO (continuous per-test progress observed throughout; see
  hang-discipline section above)
```

**Discrepancy disclosed, not silently reconciled**: pytest's collection
header reports `13399 items / 29 skipped` at collection time, while the
final outcome tally (40+13318+69+1 = 13428) is a different total. This
reflects two different pytest counting mechanisms (collection-time
skip/dropout vs. runtime skip/xfail outcomes) and was not force-reconciled
to a single number; the final structured summary line is treated as
authoritative for PASSED/FAILED/SKIPPED/XFAILED since those are pytest's own
real, executed-test outcome counts.

See `M5_FINAL_CLOSURE_FAILURE_CLASSIFICATION.md` for the full per-failure
classification of all 40 `FAILED` entries.
