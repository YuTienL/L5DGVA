---
name: dut-topology-model-builder
description: Build a traceable architecture model covering hierarchy, interfaces, DUT roles, bus topology, clocks/resets/power, address maps, interrupts, DMA, data/control paths and feature dependencies.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# dut-topology-model-builder

Build a traceable architecture model covering hierarchy, interfaces, DUT roles, bus topology, clocks/resets/power, address maps, interrupts, DMA, data/control paths and feature dependencies.

## Mandatory
- Current RTL/spec evidence wins over memory and prior notes.
- Do not finalize vPlan/environment topology before architecture-impacting unknowns are resolved or explicitly BLOCKED.
- Dynamic architecture assumptions must be regression-calibrated.
- A regression failure may indicate a wrong verification environment assumption, not automatically a DUT bug.
- Patch the architecture model, vPlan, environment, testcase or checker according to evidence, then rerun.
