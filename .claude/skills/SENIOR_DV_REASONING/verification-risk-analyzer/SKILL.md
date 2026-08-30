---
name: verification-risk-analyzer
description: Create P0/P1/P2/P3 verification risk ranking from current evidence.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# verification-risk-analyzer

Create P0/P1/P2/P3 verification risk ranking from current evidence.

## Rules
- Evidence first.
- Do not guess missing architecture/spec behavior.
- Preserve Spec→vPlan→Architecture→Test→Observability→Execution traceability.
- Report counter-evidence and unresolved unknowns.
