---
name: root-cause-evidence-builder
description: Produce a compact root-cause evidence chain including first bad event, causal path and counter-evidence.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# root-cause-evidence-builder

Produce a compact root-cause evidence chain including first bad event, causal path and counter-evidence.

## Rules
- Evidence first.
- Do not guess missing architecture/spec behavior.
- Preserve Spec→vPlan→Architecture→Test→Observability→Execution traceability.
- Report counter-evidence and unresolved unknowns.
