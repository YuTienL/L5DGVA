---
name: dut-tb-boundary-analyzer
description: Trace sequence→driver→pins/interface→DUT internal→DUT output→monitor→checker/scoreboard to localize which side first diverges.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# dut-tb-boundary-analyzer

Trace sequence→driver→pins/interface→DUT internal→DUT output→monitor→checker/scoreboard to localize which side first diverges.

## Rules
- Evidence first.
- Do not guess missing architecture/spec behavior.
- Preserve Spec→vPlan→Architecture→Test→Observability→Execution traceability.
- Report counter-evidence and unresolved unknowns.
