---
name: regression-report
description: 將 LSF job、simulation result、failure cluster 與 coverage/wave evidence彙整成中文 regression summary/report。
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# Regression Report

輸出：
`.dv-workflow/regression_results.csv`
`.dv-workflow/failure_clusters.csv`
`.dv-workflow/regression_summary.json`
`.dv-workflow/regression_report.md`

分類：
PASS
FUNCTIONAL_FAIL
INFRA_FAIL
PENDING
UNKNOWN

報告至少包含：
- Total
- PASS
- FUNCTIONAL_FAIL
- INFRA_FAIL
- Pending
- Pass rate
- Failure clusters
- representative testcase/seed
- root-cause status
- rerun status
- remaining blocker

使用中文呈現，tool/test/signature 保留原文。
