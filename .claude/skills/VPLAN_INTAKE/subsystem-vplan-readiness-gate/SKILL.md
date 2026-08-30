---
name: subsystem-vplan-readiness-gate
description: Determine whether a subsystem has sufficient Spec/DUT/interface/VIP/evidence inputs to begin trustworthy vPlan generation.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# subsystem-vplan-readiness-gate

Determine whether a subsystem has sufficient Spec/DUT/interface/VIP/evidence inputs to begin trustworthy vPlan generation.

Mandatory:
- Ask progressively; do not dump every question at once.
- Reuse already-provided evidence; never ask for the same information twice.
- Missing evidence is a readiness gap, not permission to guess.
- Final vPlan generation starts only after readiness gate passes or gaps are explicitly accepted as BLOCKED.
- System-Level vPlan must be based on the exact selected subsystem composition.
