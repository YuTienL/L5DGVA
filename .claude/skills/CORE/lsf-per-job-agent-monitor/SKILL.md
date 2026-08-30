---
name: lsf-per-job-agent-monitor
description: 對每個 LSF submitted job 派生獨立 monitor agent，追蹤 bjobs 與 sim.log，更新 Blackboard，僅在狀態變化時通知。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# LSF Per-Job Agent Monitor

Regression submit 後，對所有 job IDs 逐一建立 Job Agent。

每個 Job Agent 的 isolation key = JOB_ID。

固定 context：
- job_id
- pattern
- options
- run_dir
- sim_log
- git_sha
- server_sha
- submit_time

## Monitor Cycle

1. Query exact job state.
2. Incrementally inspect only new sim.log content.
3. Count UVM_ERROR / UVM_FATAL.
4. Detect fatal/assert/crash/signature.
5. Update per-job state.
6. Compare against previous state.
7. Only emit notification event if state changed.
8. If terminal error confirmed, call lsf-early-fail-stop.
9. Spawn/route exact job context to debug-agent.

所有 jobs 都要有 state，即使沒有變化。
只有 user-facing notification 採 change-only。


# v19.1 Mandatory All-Job Monitoring
此 Skill 為 Regression 強制能力，不是 optional。
所有 submitted JOB_ID 都必須建立 Job Agent。
每個 Job Agent 只分析自己的 sim.log。
Change-only notification 與 Periodic Full Snapshot 必須同時存在。
