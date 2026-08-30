---
name: inference-confidence-gate
description: LOW/MEDIUM/HIGH/CONFIRMED 分級，未達 gate 不得高風險修改。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# inference-confidence-gate
LOW/MEDIUM/HIGH/CONFIRMED 分級，未達 gate 不得高風險修改。
Memory 只能作 prior；current evidence 才能更新本次 root-cause confidence。
所有 inference 必須輸出 evidence / counter-evidence / missing-evidence / next-action。
