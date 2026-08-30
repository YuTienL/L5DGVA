---
name: scoreboard-reference-model-auditor
description: Audit scoreboard/reference-model assumptions, ordering, matching keys, reset flushing and prediction logic before blaming DUT.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# scoreboard-reference-model-auditor

Audit scoreboard/reference-model assumptions, ordering, matching keys, reset flushing and prediction logic before blaming DUT.

## Rules
- Evidence first.
- Do not guess missing architecture/spec behavior.
- Preserve Spec→vPlan→Architecture→Test→Observability→Execution traceability.
- Report counter-evidence and unresolved unknowns.
