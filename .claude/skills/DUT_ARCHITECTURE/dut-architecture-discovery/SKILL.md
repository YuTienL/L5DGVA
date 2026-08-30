---
name: dut-architecture-discovery
description: Discover the actual DUT architecture from current RTL/spec/register/clock-reset/address-map/interface and existing verification evidence before finalizing vPlan or environment assumptions.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# dut-architecture-discovery

Discover the actual DUT architecture from current RTL/spec/register/clock-reset/address-map/interface and existing verification evidence before finalizing vPlan or environment assumptions.

## Mandatory
- Current RTL/spec evidence wins over memory and prior notes.
- Do not finalize vPlan/environment topology before architecture-impacting unknowns are resolved or explicitly BLOCKED.
- Dynamic architecture assumptions must be regression-calibrated.
- A regression failure may indicate a wrong verification environment assumption, not automatically a DUT bug.
- Patch the architecture model, vPlan, environment, testcase or checker according to evidence, then rerun.
