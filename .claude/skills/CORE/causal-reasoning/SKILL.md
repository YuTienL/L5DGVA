---
name: causal-reasoning
description: 利用 DUT/VIP/IRQ/DMA/bus/dataflow dependency 建立 causal path，縮小 root-cause region。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# causal-reasoning
利用 DUT/VIP/IRQ/DMA/bus/dataflow dependency 建立 causal path，縮小 root-cause region。
Memory 只能作 prior；current evidence 才能更新本次 root-cause confidence。
所有 inference 必須輸出 evidence / counter-evidence / missing-evidence / next-action。
