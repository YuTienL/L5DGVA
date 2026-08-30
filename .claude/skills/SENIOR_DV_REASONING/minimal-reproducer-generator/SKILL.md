---
name: minimal-reproducer-generator
description: Reduce a failing regression into the smallest stable reproducer while preserving the first bad event.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# minimal-reproducer-generator

Reduce a failing regression into the smallest stable reproducer while preserving the first bad event.

## Rules
- Evidence first.
- Do not guess missing architecture/spec behavior.
- Preserve Spec→vPlan→Architecture→Test→Observability→Execution traceability.
- Report counter-evidence and unresolved unknowns.
