---
name: waveform-hypothesis-tester
description: Generate competing root-cause hypotheses and test each against waveform/log/transaction evidence.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# waveform-hypothesis-tester

Generate competing root-cause hypotheses and test each against waveform/log/transaction evidence.

## Rules
- Evidence first.
- Do not guess missing architecture/spec behavior.
- Preserve Spec→vPlan→Architecture→Test→Observability→Execution traceability.
- Report counter-evidence and unresolved unknowns.
