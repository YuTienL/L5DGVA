---
name: regression-architecture-calibrator
description: Use compile/smoke/regression/log/VIP-trace/waveform results to detect wrong architecture assumptions, calibrate the DUT model, patch vPlan/environment/tests/checkers and rerun.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# regression-architecture-calibrator

Use compile/smoke/regression/log/VIP-trace/waveform results to detect wrong architecture assumptions, calibrate the DUT model, patch vPlan/environment/tests/checkers and rerun.

## Mandatory
- Current RTL/spec evidence wins over memory and prior notes.
- Do not finalize vPlan/environment topology before architecture-impacting unknowns are resolved or explicitly BLOCKED.
- Dynamic architecture assumptions must be regression-calibrated.
- A regression failure may indicate a wrong verification environment assumption, not automatically a DUT bug.
- Patch the architecture model, vPlan, environment, testcase or checker according to evidence, then rerun.
