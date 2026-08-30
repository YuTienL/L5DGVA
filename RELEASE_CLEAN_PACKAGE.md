> **Superseded.** See START_HERE.md for the current canonical entry point and accurate current numbers/claims.

# DV Agent Harness L5 v50 — Release Clean Package

This is the runtime/release distribution.

Removed:
- pytest development suites (`tests`, `tests_v*`, `tests_*`)
- `pytest.ini`
- pytest caches / `__pycache__`
- `PYTEST_*` reports
- `REG*` validation records
- pytest hard-gate coverage ledger
- validation/self-test-only reports

Retained:
- Agents
- Skills
- Workflow definitions
- Runtime hard gates
- Schemas/configuration
- User and project documentation
- LSF/remote/runtime support
- WAVE=0 semantic postcheck / focused WAVE=1 debug
- health monitoring / issue triage / analysis_debug
- compile-once-run-many / STOP_AFTER_SIMV protection
- `dut-request.md` template and RCA/risk workflow
