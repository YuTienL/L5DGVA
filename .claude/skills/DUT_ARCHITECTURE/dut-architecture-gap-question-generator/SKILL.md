---
name: dut-architecture-gap-question-generator
description: Identify unknown architecture facts that materially affect verification and progressively ask the user only for the missing files/data needed to resolve them.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# dut-architecture-gap-question-generator

Identify unknown architecture facts that materially affect verification and progressively ask the user only for the missing files/data needed to resolve them.

## Mandatory
- Current RTL/spec evidence wins over memory and prior notes.
- Do not finalize vPlan/environment topology before architecture-impacting unknowns are resolved or explicitly BLOCKED.
- Dynamic architecture assumptions must be regression-calibrated.
- A regression failure may indicate a wrong verification environment assumption, not automatically a DUT bug.
- Patch the architecture model, vPlan, environment, testcase or checker according to evidence, then rerun.
