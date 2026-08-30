> **Superseded.** This document describes an earlier edition. See START_HERE.md for the current canonical entry point and SENIOR_DV_ENGINEER_FINAL_ARCHITECTURE.md for the current architecture.

# LSF Per-Job Agent Monitoring v16.1

## 核心行為

Regression submit
-> 收集所有 JOB_ID
-> 每個 JOB_ID 建立獨立 Job Agent
-> 查 LSF status
-> 增量分析自己的 sim.log
-> 更新完整 job state
-> state changed? 才通知使用者
-> terminal anomaly?
   - NO: 繼續 monitor
   - YES: 保存 evidence -> bkill exact job -> debug-agent -> root cause -> fix proposal

## 重要差異

「所有 jobs 都監控」與「只有變化才通知」同時成立。

## Early-Fail

預設：
- UVM_FATAL: stop
- UVM_ERROR > 0: stop
- fatal assertion: stop
- simulator fatal/crash: stop
- explicit FAIL: stop

可以在：
`.dv-harness/lsf/early_fail_policy.json`
調整。

## Job Isolation

每個 job state：
`.dv-harness/lsf/jobs/<JOB_ID>.json`

每個 job 必須綁定自己的：
pattern / options / run_dir / sim.log / Git SHA / Server SHA。

## 安全 Kill

只允許：
`bkill <EXACT_JOB_ID>`
或 project-approved exact-job wrapper。

不允許 wildcard kill。
