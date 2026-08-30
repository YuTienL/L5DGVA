---
name: vplan-intake-wizard
description: Interactively collect the exact documents/data needed before generating a subsystem or system-level vPlan. Ask progressively based on selected scope, protocol and selected subsystems.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# vplan-intake-wizard

Interactively collect the exact documents/data needed before generating a subsystem or system-level vPlan. Ask progressively based on selected scope, protocol and selected subsystems.

Mandatory:
- Ask progressively; do not dump every question at once.
- Reuse already-provided evidence; never ask for the same information twice.
- Missing evidence is a readiness gap, not permission to guess.
- Final vPlan generation starts only after readiness gate passes or gaps are explicitly accepted as BLOCKED.
- System-Level vPlan must be based on the exact selected subsystem composition.
