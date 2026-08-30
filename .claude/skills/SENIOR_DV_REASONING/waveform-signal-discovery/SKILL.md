---
name: waveform-signal-discovery
description: Derive candidate waveform signals from architecture nodes, protocol state, checker failure and causal dependencies.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# waveform-signal-discovery

Derive candidate waveform signals from architecture nodes, protocol state, checker failure and causal dependencies.

## Rules
- Evidence first.
- Do not guess missing architecture/spec behavior.
- Preserve Spec→vPlan→Architecture→Test→Observability→Execution traceability.
- Report counter-evidence and unresolved unknowns.
