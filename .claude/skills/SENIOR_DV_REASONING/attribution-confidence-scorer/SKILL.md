---
name: attribution-confidence-scorer
description: Assign LOW/MEDIUM/HIGH/VERIFIED confidence and explain what evidence is still missing.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# attribution-confidence-scorer

Assign LOW/MEDIUM/HIGH/VERIFIED confidence and explain what evidence is still missing.

## Rules
- Evidence first.
- Do not guess missing architecture/spec behavior.
- Preserve Spec→vPlan→Architecture→Test→Observability→Execution traceability.
- Report counter-evidence and unresolved unknowns.
