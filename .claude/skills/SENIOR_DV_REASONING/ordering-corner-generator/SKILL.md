---
name: ordering-corner-generator
description: Generate ordering/reordering/outstanding transaction corner cases appropriate to the protocol and DUT.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# ordering-corner-generator

Generate ordering/reordering/outstanding transaction corner cases appropriate to the protocol and DUT.

## Rules
- Evidence first.
- Do not guess missing architecture/spec behavior.
- Preserve Spec→vPlan→Architecture→Test→Observability→Execution traceability.
- Report counter-evidence and unresolved unknowns.
