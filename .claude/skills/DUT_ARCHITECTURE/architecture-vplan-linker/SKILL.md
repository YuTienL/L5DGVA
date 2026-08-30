---
name: architecture-vplan-linker
description: Connect vPlan requirements and features to concrete DUT architecture nodes, interfaces, clock/reset domains, data paths, registers and dependencies.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# architecture-vplan-linker

Connect vPlan requirements and features to concrete DUT architecture nodes, interfaces, clock/reset domains, data paths, registers and dependencies.

## Mandatory
- Current RTL/spec evidence wins over memory and prior notes.
- Do not finalize vPlan/environment topology before architecture-impacting unknowns are resolved or explicitly BLOCKED.
- Dynamic architecture assumptions must be regression-calibrated.
- A regression failure may indicate a wrong verification environment assumption, not automatically a DUT bug.
- Patch the architecture model, vPlan, environment, testcase or checker according to evidence, then rerun.
