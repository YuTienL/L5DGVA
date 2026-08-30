---
name: architecture-confidence-promoter
description: Promote architecture facts from hypothesis to calibrated/verified only when current evidence supports them; preserve unresolved UNKNOWN facts explicitly.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# architecture-confidence-promoter

Promote architecture facts from hypothesis to calibrated/verified only when current evidence supports them; preserve unresolved UNKNOWN facts explicitly.

## Mandatory
- Current RTL/spec evidence wins over memory and prior notes.
- Do not finalize vPlan/environment topology before architecture-impacting unknowns are resolved or explicitly BLOCKED.
- Dynamic architecture assumptions must be regression-calibrated.
- A regression failure may indicate a wrong verification environment assumption, not automatically a DUT bug.
- Patch the architecture model, vPlan, environment, testcase or checker according to evidence, then rerun.
