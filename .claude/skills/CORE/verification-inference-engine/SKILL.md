---
name: verification-inference-engine
description: 整合 current evidence、Blackboard、verified Memory，自動建立可稽核 hypotheses 與下一步驗證策略。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# verification-inference-engine
整合 current evidence、Blackboard、verified Memory，自動建立可稽核 hypotheses 與下一步驗證策略。
Memory 只能作 prior；current evidence 才能更新本次 root-cause confidence。
所有 inference 必須輸出 evidence / counter-evidence / missing-evidence / next-action。
