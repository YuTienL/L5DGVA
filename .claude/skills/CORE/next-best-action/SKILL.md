---
name: next-best-action
description: 以 information gain、root-cause discrimination、runtime cost、change risk 選擇下一個動作。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# next-best-action
以 information gain、root-cause discrimination、runtime cost、change risk 選擇下一個動作。
Memory 只能作 prior；current evidence 才能更新本次 root-cause confidence。
所有 inference 必須輸出 evidence / counter-evidence / missing-evidence / next-action。
