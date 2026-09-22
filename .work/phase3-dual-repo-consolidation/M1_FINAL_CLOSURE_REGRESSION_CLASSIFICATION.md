# M1 Final Closure Regression — Completion Evidence, Two-Level Differential, Classification

## Process-discipline correction, disclosed

The first launch of this final regression (task `bdhbtiuyz`, against HEAD
`f88ddd5`) was killed and discarded before completion: a commit
(`9a5c3ee`, adding `M1D_CANONICAL_ROOT_NORMALIZATION.md`) landed while it was
running, a real `REGRESSION_HEAD_MISMATCH` by the letter of the rule. The
diff was a single `.work/*.md` doc, never collected by pytest — functionally
inert — but per "do not silently accept the result," it was not treated as
authoritative. Relaunched clean (task `bmwxj3npn`) against the now-stable
HEAD, with zero working-tree changes for its entire duration (verified
below).

## Completion evidence (real, this launch)

```
FINAL_CANONICAL_HEAD = 9a5c3eeb2a894c86d9c85186d58aa46002c5ef9c
FINAL_CANONICAL_BRANCH = canonical/m1-bootstrap
EXACT_PYTEST_COMMAND = python -m pytest -q --tb=no -o cache_dir=.pytest_cache_m1d
                        (from D:\DV\Task\L5_DGVA)
COLLECTED_TESTS = 13785 (confirmed via a fresh --collect-only run against
                          the same HEAD, and independently as the sum
                          13728+28+28+1 below)
PASSED_TESTS = 13728
FAILED_TESTS = 28
SKIPPED_TESTS = 28
XFAILED_TESTS = 1
XPASSED_TESTS = 0
DURATION = 4055.55s (1:07:35)
REAL_CHILD_EXIT_CODE = 1 (pytest's normal "N failed" code)
COMPLETION_MARKER = final summary line present ("28 failed, 13728 passed,
                     28 skipped, 1 xfailed, 1 warning in 4055.55s")
TIMEOUT_STATUS = NO
CRASH_STATUS = NO (zero Traceback/INTERNALERROR/Fatal Python error lines in
               the full output; the one UnicodeDecodeError present is
               inside a caught PytestUnhandledThreadExceptionWarning in
               test_pueue_client.py, a pre-existing, already-seen warning,
               not an interpreter crash)
```

**HEAD-freeze re-confirmed after completion**: `git rev-parse HEAD` ==
`9a5c3eeb2a894c86d9c85186d58aa46002c5ef9c` (unchanged), `git status --short`
shows zero tracked-file changes (only the pre-existing `.dv-harness/events.jsonl`
churn and the regression's own untracked output log) for this run's entire
duration.

## Two-level differential (script-computed by test identity, not eyeballed)

### A. FINAL_M1 vs PRE_M1D_CANONICAL_REFERENCE (`M1_full_regression_output.txt`, 27 failed)

```
COMMON_FAILURES = 27 (all of the pre-M1D run's failures reproduce exactly)
NEW_FAILURES = 1: test_gui_intake_control_plane.py::test_real_server_post_answer_without_token_is_rejected_NEGATIVE_CONTROL
GONE_FAILURES = 0
```

### B. FINAL_M1 vs FROZEN_V50_EXACT_BASELINE (`_h2_6_final_run.log`, 21 failed)

```
COMMON_FAILURES = 21 (the original v50 baseline failures, unchanged)
NEW_FAILURES = 7: the same 6 already diagnosed in M1_FULL_REGRESSION_CLASSIFICATION.md
                  (3x test_sim_scripts_makefile_mechanisms.py,
                   3x test_syoscb_result_taxonomy.py) + the 1 new one above
GONE_FAILURES = 0
```

No `SIGNATURE_CHANGED_FAILURES`: the 27/21 COMMON sets are identical test
IDs with no code overlap between M1/M1D's own changes and any of those
test's target modules (re-confirmed the same way as the pre-M1D pass).

## The 1 new-since-pre-M1D failure — full investigation

`test_gui_intake_control_plane.py::test_real_server_post_answer_without_token_is_rejected_NEGATIVE_CONTROL`

- **Code-overlap check**: `dv_harness/gui_intake_control_plane.py` imports
  `dashboard_auth`, `env_manifest`, `intake_state` — none touched by any
  M1/M1D commit. The test file itself imports `env_manifest`,
  `gui_intake_control_plane`, `question_queue` — same, zero overlap.
- **Isolated rerun**: `pytest .../test_gui_intake_control_plane.py::test_real_server_post_answer_without_token_is_rejected_NEGATIVE_CONTROL`
  alone → **1 passed**.
- **Whole-file rerun** (rules out within-file ordering/shared state):
  `pytest .../test_gui_intake_control_plane.py` → **28 passed** (all tests
  in the file, including this one).
- **Mechanism**: the test exercises a real `ThreadingHTTPServer` + real
  socket client (`http.client`) with `threading`/`time` — a timing-sensitive
  real-server test. It only fails embedded in the full ~13785-test,
  67-minute run, never standalone or file-scoped — consistent with
  resource/scheduling pressure from the many subprocess-heavy tests earlier
  in the same run (pueue/multi-agent/LSF-adjacent suites, already a known
  slow cluster in this codebase), not a functional defect in the module
  under test.
- **Classification: `TEST_INFRASTRUCTURE`** (a load-sensitive real-server
  timing flake, evidenced by isolation + zero code overlap + a real,
  incriminating mechanism -- never asserted from intuition alone).

## Result

```
REGRESSION_CAUSED_BY_M1 = 0
REGRESSION_CAUSED_BY_M1D = 0
PRE_EXISTING = 21 (unchanged from the v50 baseline)
TEST_INFRASTRUCTURE = 7 (6 previously diagnosed + 1 newly diagnosed above)
ENVIRONMENT = 0
UNKNOWN_REGRESSION_FAILURES = 0
```

Per the closure blocking rule: `REGRESSION_CAUSED_BY_M1 = 0`,
`REGRESSION_CAUSED_BY_M1D = 0`, `UNKNOWN_REGRESSION_FAILURES = 0` — M1 may
close.
