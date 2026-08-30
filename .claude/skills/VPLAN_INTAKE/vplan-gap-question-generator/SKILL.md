---
name: vplan-gap-question-generator
description: Detect missing or ambiguous vPlan inputs and ask only the next necessary user questions instead of guessing.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# vplan-gap-question-generator

Detect missing or ambiguous vPlan inputs and ask only the next necessary user questions instead of guessing.

Mandatory:
- Ask progressively; do not dump every question at once.
- Reuse already-provided evidence; never ask for the same information twice.
- Missing evidence is a readiness gap, not permission to guess.
- Final vPlan generation starts only after readiness gate passes or gaps are explicitly accepted as BLOCKED.
- System-Level vPlan must be based on the exact selected subsystem composition.
