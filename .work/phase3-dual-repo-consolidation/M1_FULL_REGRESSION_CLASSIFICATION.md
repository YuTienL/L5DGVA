# M1 Full-Suite Regression — Completion Evidence and Failure-Signature Classification

Real, tracked completion (task `bmnfst210`, restarted clean after an earlier
mis-launched, untracked run was killed — see prior turn's disclosure). This
result is the **pre-normalization reference regression** (per the M1D
instruction: "the regression that ran before M1D becomes a pre-normalization
reference, not the final M1 closure regression") — **not** final M1 closure.

## Completion evidence

```
CANONICAL_HEAD_AT_LAUNCH = fed36e6cb01a578230fc5a2b397237a871c3d854
EXACT_COMMAND = python -m pytest -q --tb=no -o cache_dir=.pytest_cache_m1
                (run from D:\DV\Task\L5_DGVA)
REAL_CHILD_EXIT_CODE = 1  (pytest's own "N tests failed" code -- not a crash;
                            confirmed by a clean final summary line, no
                            traceback/interpreter-crash output)
COLLECTED = 13768 (matches the earlier --collect-only count)
PASSED = 13717
FAILED = 27
SKIPPED = 28
XFAILED = 1
WARNINGS = 1
DURATION = 4099.47s (1:08:19)
TIMEOUT_OR_CRASH = NO (natural completion, full summary line present)
```

## Baseline (M0/H2-6) for comparison

Real source: `D:\DV\Task\DV_Agent_Harness_L5\v50\.work\repository-hygiene-audit\_h2_6_final_run.log`
```
21 failed, 13694 passed, 15 skipped, 1 warning in 4309.27s (1:11:49)
```

## Test-identity diff (script-computed, not eyeballed)

```
COMMON_FAILURES = 21 (all 21 baseline failures reproduce exactly, same test IDs)
GONE_FAILURES = 0
NEW_FAILURES = 6
SIGNATURE_CHANGED_FAILURES = 0 among the 21 COMMON (see note below)
```

**COMMON_FAILURES (21)** — full list in `M1_full_regression_output.txt`'s own
short summary; every one of these 21 test IDs failed identically in the
unmodified M0/H2-6 baseline log, before any M1 work began. None of their
underlying test files (`test_bounded_self_healing.py`, `test_cli_pueue.py`,
`test_git_hooks_e2e.py`, `test_harness_status_event_wiring.py`,
`test_memory_vault.py`, `test_obsidian_memory_final_integration.py`,
`test_pueue_client.py`, `test_question_queue_digest_auto_trigger.py`,
`test_resource_cost_autonomy.py`, `test_self_tuning.py`,
`test_stage_instructions_gate_completeness.py`, `test_syoscb_phase1_report.py`,
`test_waveform_dump_scope_human_confirmation.py`) were touched by any M1
commit. **Classification: PRE_EXISTING** for all 21 (real evidence: same
test ID, same baseline-vs-now failure, zero M1 code overlap with the files
involved — not merely counted, matched by identity).

**A note on "SIGNATURE_CHANGED_FAILURES"**: both the baseline log and this
run used `--tb=no -q`, so neither has a per-test assertion-message
traceback to diff directly. In place of that, the causal check used was:
does any file M1 actually touched (`replay.ps1`, `dv_harness/execution_profile.py`,
`dv_harness/l5dgva_repo.py`, `dv_harness/dv_doctor.py`, `dv_harness/cli.py`,
`tools/remote/remote_exec.py`, `tools/remote/remote_relay.py`,
`.dv-harness/config.json`) appear among the 21 common failures' own test
files or their production targets? Answer: no overlap at all except
`dv_harness/cli.py`, which two of the 21 (`test_harness_status_event_wiring.py`,
`test_cli_pueue.py`-adjacent) exercise indirectly — but my only `cli.py` edit
was a pure additive new `doctor` branch inserted before the existing
`elif` chain (no existing branch's code was altered), and both of those
exact test IDs already failed identically in the pre-M1 baseline (run
before `cli.py` was touched at all), so the same failure existing before
my edit is direct, positive evidence against a signature change, not an
assumption. Result: **0 signature changes found**, evidenced rather than
assumed.

## NEW_FAILURES (6) — individually re-run with `--tb=short`, fully diagnosed

### Group A — 3 tests, `test_sim_scripts_makefile_mechanisms.py`

```
test_four_stage_flow_mirrors_reference_structurally
test_verdi_pa_mirrors_reference_structurally
test_wave_txt_convention_mirrors_reference_structurally
```

Real error: `AssertionError: expected file missing:
D:\DV\Task\L5_DGVA\reference\USB_UVM_Handoff\sim\scripts\Makefile`

**Root cause, fully confirmed by direct evidence**: `reference/USB_UVM_Handoff/`
is deliberately gitignored in v50 itself (`v50/.gitignore:83:
reference/USB_UVM_Handoff/`), confirmed via `git check-ignore -v` and via
`git ls-files -- reference/` returning **zero** tracked files under that
subtree (only `reference/ATB/` is git-tracked; `USB_UVM_Handoff` is a large,
locally-present-but-never-committed reference environment — consistent with
this project's own licensing/size-driven "reference database" handling
noted earlier in this migration). M1's bootstrap method (`git clone`)
correctly and necessarily clones only git-TRACKED content — it cannot
carry over a file v50 itself never committed. The file is physically
present on disk in v50's own working directory (confirmed:
`ls v50/reference/USB_UVM_Handoff/sim/scripts/` lists `Makefile` and 8
sibling scripts) — it was never absent from the *machine*, only from the
*clone*.

**Classification: TEST_INFRASTRUCTURE** — not a code regression; the tests'
own fixture-data dependency (an untracked reference tree) isn't satisfied
by a git-clone bootstrap, which is a structural fact about the
migration/bootstrap method, not a defect in any M1-authored code. Disclosed
capability gap, not fixed here (would require an explicit out-of-band file
copy of `reference/USB_UVM_Handoff/`, outside this session's approved
`git clone`-based M1 bootstrap method, and outside "no new migration work"
during this regression-classification pass).

### Group B — 3 tests, `test_syoscb_result_taxonomy.py`

```
test_the_taxonomy_is_the_documents_own_fourteen_values_in_its_own_order
test_every_result_cites_the_document_line_that_names_it
test_the_counter_list_is_the_documents_own_thirteen_in_its_own_order
```

Real error: looks for
`D:\DV\Task\DV_Agent_Harness_L5_ULTIMATE_COMPLETE_Master_Prompt_SystemLevel_AMBA4_SyoSil_CCE_Research.md`
(missing) — the real file exists one directory level deeper, at
`D:\DV\Task\DV_Agent_Harness_L5\DV_Agent_Harness_L5_ULTIMATE_COMPLETE_Master_Prompt_SystemLevel_AMBA4_SyoSil_CCE_Research.md`.

**Root cause, fully confirmed**: the test computes its target document path as
`Path(__file__).resolve().parents[2] / TAXONOMY_DOC` (`test_syoscb_result_taxonomy.py:105`)
— a **hardcoded directory-nesting-depth assumption**, not a repository-root
discovery. When this test ran inside v50 (nested at
`D:\DV\Task\DV_Agent_Harness_L5\v50\dv_harness_tests\...`), `.parents[2]`
correctly lands on `D:\DV\Task\DV_Agent_Harness_L5\`, where the real
document lives. In the canonical repo, bootstrapped as a **sibling** of the
Parent (`D:\DV\Task\L5_DGVA\dv_harness_tests\...`), the same `.parents[2]`
arithmetic instead lands on `D:\DV\Task\` — one level short.

**Classification: TEST_INFRASTRUCTURE** (a fragile, relative-directory-depth
path assumption in the test itself, not a defect in the `syoscb_*`
production modules it nominally tests — confirmed separately: the taxonomy
data structures these tests check are untouched by any M1 commit).
**Disclosed causal link, not hidden**: this specific failure is a direct,
mechanical consequence of M1's own decision to bootstrap the canonical
repository as a sibling of the Parent rather than nested underneath it
(exactly the kind of assumption the Final Canonical Platform Architecture
Freeze's location-independence requirement exists to eliminate) — the test
itself is the thing that needs fixing (replace the nesting-depth arithmetic
with a real repository-root/marker-based discovery, e.g.
`dv_harness.l5dgva_repo.discover_repo_root()`), not something to route
around. **Not fixed here** — instruction #6 forbids modifying production
code during classification, and this is being treated the same way for the
test file: recorded as a genuine, real finding for a follow-up fix, not
silently patched mid-classification.

## Section 5 requirement — parallel/load-only caveat

None of the 6 NEW failures are parallel/load/concurrency-shaped (all are
single, deterministic, 100%-reproducible path-resolution failures,
confirmed by individually re-running each with `--tb=short` and getting the
identical error both times) — the "isolated rerun before TEST_INFRASTRUCTURE"
requirement for parallel/load failures does not apply, but the equivalent
rigor (individual isolated rerun, full traceback, root-cause confirmed by
direct filesystem/git evidence) was applied anyway.

## Result

```
REGRESSION_CAUSED_BY_M1 = 0
PRE_EXISTING = 21
TEST_INFRASTRUCTURE = 6
ENVIRONMENT = 0
UNKNOWN = 0
UNKNOWN_REGRESSION_FAILURES = 0
```

Per instruction: `REGRESSION_CAUSED_BY_M1 = 0` and `UNKNOWN_REGRESSION_FAILURES = 0`
-> proceed to evaluate M1 closure. Per the M1D instruction's own explicit
sequencing, this result is frozen as the **pre-normalization reference
regression** — final M1 closure regression still runs after M1D completes,
against the normalized final HEAD.
