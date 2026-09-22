# M1 — v50 Baseline Preservation Qualification

Per instruction #14. Compares failure identity/signature, not merely counts,
against the accepted M0/H2-6 baseline (21 failed / 13694 passed / 15 skipped).

## Targeted category evidence (real, completed)

```
dv_harness_tests/test_graph_parallel_dispatch.py
dv_harness_tests/test_graph_runtime_removed.py
dv_harness_tests/test_skill_resolver.py
dv_harness_tests/test_agent_dispatch_map.py
dv_harness_tests/test_agent_roster_doc.py
dv_harness_tests/test_cli_memory_commands.py
dv_harness_tests/test_cli_git_guard.py
dv_harness_tests/test_cli_blackboard.py
dv_harness_tests/test_knowledge_center.py
dv_harness_tests/test_memory_vault.py
dv_harness_tests/test_memory_doctor.py
dv_harness_tests/test_intake_baseline.py
dv_harness_tests/test_intake_state.py
dv_harness_tests/test_verification_intake_contract.py
  -> 299 passed, 1 failed (56.6s)
```

**The one failure** (`test_memory_vault.py::test_detect_obsidian_cli_real_probe_reports_not_installed_on_this_machine`)
was re-run against **unmodified v50 HEAD directly** (not this canonical repo)
and **fails identically there too** — same assertion, same message. Root
cause: the test hardcodes "Obsidian CLI is not installed on this machine,"
true when the test was written (2026-09-03) but no longer true on this
machine today (confirmed independently: this session's own `dv-harness
doctor` reports `OBSIDIAN_CLI_STATUS: AVAILABLE`). **Pre-existing
environment-state flake, not an M1 regression** — signature-matched against
the source baseline, not just counted.

**M1's own new test suites** (`test_l5dgva_repo.py`, `test_execution_profile.py`,
`test_dv_doctor.py`, `test_security_preservation_gate.py`): 42 passed, 1
tracked xfail — see their own commits for detail.

**C1-C5 / `lifecycle.py` (16-milestone Standard Flow) caveat, disclosed**: no
test file matching this naming exists in this v50-derived checkout. Traced
the reason: the "C1-C5 Standard Flow" work referenced in this session's own
recent history (`intake_clarification.py`, `intake_resume.py`,
`intake_workbook.py`, the `standard-flow(wave2-c5*)` commits) belongs to the
**Parent** repository's own `feature/l5-standard-flow` branch, not to v50 at
all — confirmed by `ls dv_harness_tests/` finding none of
`test_intake_clarification.py`/`test_intake_resume.py`/`test_intake_workbook.py`
in this checkout. **C1-C5 qualification is therefore N/A for M1's own
v50-baseline-preservation purpose** — there is nothing of that capability in
v50's baseline to regress. This is a real, disclosed fact, not a gap this
canonical repo introduced; Parent-side C1-C5 capability migration is
explicitly excluded from M1 scope by the governing instructions themselves.

## Full-suite regression (13768 tests collected)

Launched in the background at the start of this M1 continuation
(`.work/phase3-dual-repo-consolidation/M1_full_regression_output.txt`)
against the final integrated M1 HEAD. **Status at the time of this M1
report: still running (last observed ~28% complete)** — genuinely slow
(subprocess-heavy modules: LSF/multi-agent/regression-reporter tests), not
hung (process liveness re-confirmed repeatedly via `ps`). Per instruction
#14's own explicit rule ("wrapper exit is not completion evidence"), this is
honestly reported as **IN_PROGRESS**, not claimed complete. It will continue
running; a definitive full-suite failure-signature comparison against the
M0/H2-6 baseline will be produced once it finishes, and reported then.

```
V50_BASELINE_QUALIFICATION = PARTIAL (targeted categories: QUALIFIED;
                                        full-suite: IN_PROGRESS, not yet complete)
```
