---
name: fsm-transition-analyzer
description: Validate observed FSM transitions and transition prerequisites against current design/spec evidence.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# fsm-transition-analyzer

Validate observed FSM transitions and transition prerequisites against current design/spec evidence.

## Rules
- Evidence first.
- Do not guess missing architecture/spec behavior.
- Preserve Spec→vPlan→Architecture→Test→Observability→Execution traceability.
- Report counter-evidence and unresolved unknowns.
