---
name: architecture-aware-env-generator
description: Use the verified DUT architecture model to configure UVM topology, agent roles, virtual sequencers, scoreboards, reset/clock handling, address maps and scenario dependencies.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# architecture-aware-env-generator

Use the verified DUT architecture model to configure UVM topology, agent roles, virtual sequencers, scoreboards, reset/clock handling, address maps and scenario dependencies.

## Mandatory
- Current RTL/spec evidence wins over memory and prior notes.
- Do not finalize vPlan/environment topology before architecture-impacting unknowns are resolved or explicitly BLOCKED.
- Dynamic architecture assumptions must be regression-calibrated.
- A regression failure may indicate a wrong verification environment assumption, not automatically a DUT bug.
- Patch the architecture model, vPlan, environment, testcase or checker according to evidence, then rerun.
