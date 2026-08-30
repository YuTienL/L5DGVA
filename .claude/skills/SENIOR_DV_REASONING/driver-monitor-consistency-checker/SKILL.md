---
name: driver-monitor-consistency-checker
description: Verify that intended sequence stimulus equals driver output and monitor decode is consistent with observed interface behavior.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# driver-monitor-consistency-checker

Verify that intended sequence stimulus equals driver output and monitor decode is consistent with observed interface behavior.

## Rules
- Evidence first.
- Do not guess missing architecture/spec behavior.
- Preserve Spec→vPlan→Architecture→Test→Observability→Execution traceability.
- Report counter-evidence and unresolved unknowns.
