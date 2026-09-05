---
name: periodic-regression-snapshot
description: 定期產生所有 LSF jobs 完整狀態快照，即使沒有變化也回報；LSF 與 DV analysis status 分離。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Periodic Regression Snapshot
預設每 5 分鐘產生一次完整 snapshot，可由專案設定調整
（`.dv-harness/lsf/periodic_snapshot_policy.json` 的 `default_interval_minutes`，
與 `regression_reporter.DEFAULT_INTERVAL_MINUTES` 一致）。
self_check_list #41 要求 job / simulation log 狀態最慢每 10 分鐘要重新確認一次
（`regression_reporter.SPEC_MAX_INTERVAL_MINUTES`），所以任何調整後的 interval
都必須 <= 10 分鐘。此處原本寫 30 分鐘，已超出該上限。
Snapshot 不得暫停 GAV execution。
固定包含 Summary、All Jobs、Attention、Active Analysis、Next Actions。
LSF DONE 只能代表 scheduler execution ended normally，必須再分析 sim.log 才能得到 DV PASS/FAIL/UNKNOWN。
