---
name: protocol-state-reconstructor
description: Reconstruct protocol state/state-transition history from transaction and signal evidence.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# protocol-state-reconstructor

Reconstruct protocol state/state-transition history from transaction and signal evidence.

## Rules
- Evidence first.
- Do not guess missing architecture/spec behavior.
- Preserve Spec→vPlan→Architecture→Test→Observability→Execution traceability.
- Report counter-evidence and unresolved unknowns.
