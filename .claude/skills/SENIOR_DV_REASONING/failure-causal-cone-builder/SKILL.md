---
name: failure-causal-cone-builder
description: Build the minimal backward causal cone from a failure symptom through prerequisites and architecture dependencies.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# failure-causal-cone-builder

Build the minimal backward causal cone from a failure symptom through prerequisites and architecture dependencies.

## Rules
- Evidence first.
- Do not guess missing architecture/spec behavior.
- Preserve Spec→vPlan→Architecture→Test→Observability→Execution traceability.
- Report counter-evidence and unresolved unknowns.
