---
name: expected-observed-diff-analyzer
description: Compare expected and observed transaction/state/data behavior at each causal boundary.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# expected-observed-diff-analyzer

Compare expected and observed transaction/state/data behavior at each causal boundary.

## Rules
- Evidence first.
- Do not guess missing architecture/spec behavior.
- Preserve Spec→vPlan→Architecture→Test→Observability→Execution traceability.
- Report counter-evidence and unresolved unknowns.
