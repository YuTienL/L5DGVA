---
name: timing-corner-generator
description: Generate timing-edge cases around legal min/max windows, timeout boundaries and sequencing transitions.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# timing-corner-generator

Generate timing-edge cases around legal min/max windows, timeout boundaries and sequencing transitions.

## Rules
- Evidence first.
- Do not guess missing architecture/spec behavior.
- Preserve Spec→vPlan→Architecture→Test→Observability→Execution traceability.
- Report counter-evidence and unresolved unknowns.
