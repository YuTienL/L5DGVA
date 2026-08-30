---
name: result-collector
description: 收集 Linux Server 的 build/verify/WAVE/fsdbreport/LSF 結果到 PC project model。
allowed-tools: Read Grep Glob PowerShell
---
# Result Collector

收集：
- remote host
- branch/commit
- build result/log
- verify result/log
- WAVE=1 result
- FSDB server path
- fsdbreport report/findings
- runtime
- LSF job ID/status if applicable
- normalized failure signatures

不要預設把巨大 FSDB 複製回 PC。
優先保存 Server path + fsdbreport evidence。

更新 `.dv-workflow/validation.json`。


# LSF/Verdi Result Collection

另外收集：
- lsf_jobs.csv
- regression_results.csv
- failure_clusters.csv
- regression_summary.json
- regression_report.md
- representative FSDB server path
- fsdbreport report
- Verdi debug notes（若使用）

巨大 FSDB 不預設搬回 PC。
