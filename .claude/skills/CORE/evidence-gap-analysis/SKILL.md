---
name: evidence-gap-analysis
description: 列出每個 hypothesis 尚缺少的 evidence 與可證偽條件。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# evidence-gap-analysis
列出每個 hypothesis 尚缺少的 evidence 與可證偽條件。
Memory 只能作 prior；current evidence 才能更新本次 root-cause confidence。
所有 inference 必須輸出 evidence / counter-evidence / missing-evidence / next-action。
