---
name: coverage-quality-analyzer
description: Detect false confidence where coverage is hit without meaningful checking or requirement evidence.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# coverage-quality-analyzer

Detect false confidence where coverage is hit without meaningful checking or requirement evidence.

## Rules
- Evidence first.
- Do not guess missing architecture/spec behavior.
- Preserve Spec→vPlan→Architecture→Test→Observability→Execution traceability.
- Report counter-evidence and unresolved unknowns.
