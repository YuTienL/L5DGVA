---
name: bug-attribution-engine
description: Rank DUT/TB/VIP/test/spec/infra root-cause classes from evidence and counter-evidence.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# bug-attribution-engine

Rank DUT/TB/VIP/test/spec/infra root-cause classes from evidence and counter-evidence.

## Rules
- Evidence first.
- Do not guess missing architecture/spec behavior.
- Preserve Spec→vPlan→Architecture→Test→Observability→Execution traceability.
- Report counter-evidence and unresolved unknowns.
