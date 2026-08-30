---
name: hypothesis-generation
description: 針對 failure 產生多個互斥/競爭 root-cause hypotheses，禁止單一路徑先入為主。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# hypothesis-generation
針對 failure 產生多個互斥/競爭 root-cause hypotheses，禁止單一路徑先入為主。
Memory 只能作 prior；current evidence 才能更新本次 root-cause confidence。
所有 inference 必須輸出 evidence / counter-evidence / missing-evidence / next-action。
