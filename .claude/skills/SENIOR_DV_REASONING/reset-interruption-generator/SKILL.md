---
name: reset-interruption-generator
description: Generate reset assertion/deassertion during active, idle, error and recovery states when supported by spec/design.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# reset-interruption-generator

Generate reset assertion/deassertion during active, idle, error and recovery states when supported by spec/design.

## Rules
- Evidence first.
- Do not guess missing architecture/spec behavior.
- Preserve Spec→vPlan→Architecture→Test→Observability→Execution traceability.
- Report counter-evidence and unresolved unknowns.
