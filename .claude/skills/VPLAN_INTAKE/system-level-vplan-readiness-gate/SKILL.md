---
name: system-level-vplan-readiness-gate
description: For selected subsystem composition, require subsystem identity/qualification plus cross-subsystem use-case, clock/reset, address, interrupt, power and dependency evidence before system-level vPlan creation.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# system-level-vplan-readiness-gate

For selected subsystem composition, require subsystem identity/qualification plus cross-subsystem use-case, clock/reset, address, interrupt, power and dependency evidence before system-level vPlan creation.

Mandatory:
- Ask progressively; do not dump every question at once.
- Reuse already-provided evidence; never ask for the same information twice.
- Missing evidence is a readiness gap, not permission to guess.
- Final vPlan generation starts only after readiness gate passes or gaps are explicitly accepted as BLOCKED.
- System-Level vPlan must be based on the exact selected subsystem composition.
