---
name: vplan-evidence-database-builder
description: Build the evidence database used by vPlan generation from specs, design docs, registers, PHY/interface docs, VIP evidence, RTL, existing tests/commands/regressions/coverage and waivers.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# vplan-evidence-database-builder

Build the evidence database used by vPlan generation from specs, design docs, registers, PHY/interface docs, VIP evidence, RTL, existing tests/commands/regressions/coverage and waivers.

Mandatory:
- Ask progressively; do not dump every question at once.
- Reuse already-provided evidence; never ask for the same information twice.
- Missing evidence is a readiness gap, not permission to guess.
- Final vPlan generation starts only after readiness gate passes or gaps are explicitly accepted as BLOCKED.
- System-Level vPlan must be based on the exact selected subsystem composition.
