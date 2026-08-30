---
name: periodic-regression-snapshot
description: 定期產生所有 LSF jobs 完整狀態快照，即使沒有變化也回報；LSF 與 DV analysis status 分離。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Periodic Regression Snapshot
預設每 30 分鐘產生一次完整 snapshot，可由專案設定調整。
Snapshot 不得暫停 GAV execution。
固定包含 Summary、All Jobs、Attention、Active Analysis、Next Actions。
LSF DONE 只能代表 scheduler execution ended normally，必須再分析 sim.log 才能得到 DV PASS/FAIL/UNKNOWN。
