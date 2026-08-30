---
name: first-bad-event-finder
description: Find the earliest divergence between expected and observed behavior; never use the final error as the root cause by default.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# first-bad-event-finder

Find the earliest divergence between expected and observed behavior; never use the final error as the root cause by default.

## Rules
- Evidence first.
- Do not guess missing architecture/spec behavior.
- Preserve Spec→vPlan→Architecture→Test→Observability→Execution traceability.
- Report counter-evidence and unresolved unknowns.
