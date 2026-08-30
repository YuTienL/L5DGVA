---
name: failure-signature-extractor
description: Normalize fatal/error/assertion/scoreboard/VIP/timeout symptoms into a failure signature and failure time window.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# failure-signature-extractor

Normalize fatal/error/assertion/scoreboard/VIP/timeout symptoms into a failure signature and failure time window.

## Rules
- Evidence first.
- Do not guess missing architecture/spec behavior.
- Preserve Spec→vPlan→Architecture→Test→Observability→Execution traceability.
- Report counter-evidence and unresolved unknowns.
