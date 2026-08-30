---
name: hypothesis-ranking
description: 依 supporting evidence、counter evidence、context match、memory prior 與 confidence 排序 hypotheses。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# hypothesis-ranking
依 supporting evidence、counter evidence、context match、memory prior 與 confidence 排序 hypotheses。
Memory 只能作 prior；current evidence 才能更新本次 root-cause confidence。
所有 inference 必須輸出 evidence / counter-evidence / missing-evidence / next-action。
