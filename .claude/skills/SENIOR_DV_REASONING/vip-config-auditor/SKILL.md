---
name: vip-config-auditor
description: Check VIP role/mode/version/configuration, callbacks, protocol options and binding against the current DUT topology.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# vip-config-auditor

Check VIP role/mode/version/configuration, callbacks, protocol options and binding against the current DUT topology.

## Rules
- Evidence first.
- Do not guess missing architecture/spec behavior.
- Preserve Spec→vPlan→Architecture→Test→Observability→Execution traceability.
- Report counter-evidence and unresolved unknowns.
