---
name: plan-and-execute
description: DV Agent Harness v16 core capability.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# plan-and-execute
複雜 Node 先拆 Plan。只有 NEW_EVIDENCE、NEW_FINDING、FAILED_STEP、BLOCKED_DEPENDENCY、SCOPE_CHANGE、CHANGE_IMPACT_EXPANSION 可 replan，且保存 reason/evidence/revision。
