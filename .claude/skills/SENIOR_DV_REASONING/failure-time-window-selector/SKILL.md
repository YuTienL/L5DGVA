---
name: failure-time-window-selector
description: Select a focused pre-failure and post-failure waveform window, expanding only when causal evidence requires it.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# failure-time-window-selector

Select a focused pre-failure and post-failure waveform window, expanding only when causal evidence requires it.

## Rules
- Evidence first.
- Do not guess missing architecture/spec behavior.
- Preserve Spec→vPlan→Architecture→Test→Observability→Execution traceability.
- Report counter-evidence and unresolved unknowns.
