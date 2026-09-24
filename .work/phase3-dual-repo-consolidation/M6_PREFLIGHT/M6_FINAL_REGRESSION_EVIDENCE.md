# M6 Final Operational Slice Qualification -- Regression Evidence

## Scope: the real M6-slice caller population, not a blanket sweep

A naive `grep -rl "engine.py"` (etc.) across `dv_harness_tests/*.py`
returns 176 files -- almost all false positives (`from dv_harness.engine
import DVHarness` is used by nearly every test file in this large
project's own generic fixture setup, unrelated to the M6 slice). The
REAL, precise caller population for the M6 10-stage slice is the 29-file
set both `CAP-M5M6-VLEVEL-001` and `M6-TASK-BOUNDARY-PRODUCTION-001`
independently derived (real symbol-level callers of `engine.py`
`start_lifecycle()`, `cli.py`, `dashboard.py`, `clarification_service.py`,
`generation_field_controls.py`, `verification_level.py`,
`environment_mode_router.py`, `create_environment.py`,
`task_boundary_conformance.py`), extended by 2 more files this task added
for completeness (`test_intake_field_resolution.py`,
`test_question_queue.py` -- the foundational Field Resolution/
Clarification engines stages 2-6 depend on but that neither prior task's
own narrower touched-module set included): **31 files total**.

## Two independent runs against the frozen candidate

```
M6_QUALIFICATION_CANDIDATE_SHA = 2bd986f5e05fb5ee0c01d1c5c29d41a44c5b859f
CURRENT_BRANCH = canonical/m4-dependency-closure
```

| Run | Task ID | COLLECTED | PASSED | FAILED | SKIPPED | XFAILED | DURATION | CHILD_EXIT_CODE | CRASH | TIMEOUT | HANG |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | bcag6ey11 | 881 | 881 | 0 | 0 | 0 | 447.91s | 0 | NO | NO | NO |
| 2 | bwjof0zvx | 881 | 881 | 0 | 0 | 0 | 438.88s | 0 | NO | NO | NO |

Identical result both times -- `881 passed`, byte-for-byte the same test
population, against the identical, unchanging tree.

```
REGRESSION_CAUSED_BY_M6 = 0
UNKNOWN_REGRESSION_FAILURES = 0
```

Compared by identity: zero failures in either run means there is no
failure signature to compare against the established pre-existing-failure
baseline -- both runs are unambiguously clean.

## Source immutability (re-verified before and after both runs)

```
SOURCE_A_CHANGED (Parent, D:\DV\Task\DV_Agent_Harness_L5) = NO
  (3e9dd7360f584078ed8f4b04120c9844acabd97b, unchanged)
SOURCE_B_CHANGED (v50) = NO
  (f3fd17326cf3654aca6fd83fad991a3f247e6682, unchanged)
B7A_CHANGED (D:/wt/b7a) = NO
  (7b2a65a4dc2d40d493451b409669c90ed0b3d9a5, unchanged)
B7B_CHANGED (D:/wt/b7b) = NO
  (c7c7fa09e9ee8336ba102b4495f4b8808408fe0b, unchanged)
B8_CHANGED (D:/wt/b8) = NO
  (c9cdd06ce586d44f4c0cef00310c10f95ea59f93, unchanged)
REFERENCE_USB_ENV_CONSUMED = NO
```

## Working-tree/HEAD integrity throughout the qualification freeze

`git rev-parse HEAD` returned `2bd986f5e05fb5ee0c01d1c5c29d41a44c5b859f`
identically before Run 1, between Run 1 and Run 2, and after Run 2. The
only working-tree change observed throughout (`git status --short`) was
`.dv-harness/events.jsonl`, a runtime CLI-access log written by unrelated
background activity on this machine -- never a production/test/
governance/control-plane file, and never modified by this qualification
pass itself. New report artifacts (this file and its siblings) were
written to the established `M6_PREFLIGHT/` output location only, per this
task's own explicit "reports/logs... cannot affect runtime behavior"
carve-out.

```
QUALIFICATION_HEAD_MISMATCH = NO
```

## Constitution gate

```
ConstitutionCheckResult(status='PASS', reasons=[])
```
(re-run immediately after both regression executions)
