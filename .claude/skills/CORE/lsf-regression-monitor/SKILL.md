---
name: lsf-regression-monitor
description: 監控 LSF regression job 狀態、runtime、memory、queue 與 infrastructure failure，維護 job table。
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# LSF Regression Monitor

維護：
`.dv-workflow/lsf_jobs.csv`

欄位：
JOB_ID,TESTCASE,SEED,QUEUE,STATUS,RUNTIME,MEMORY_REQ,MEMORY_MAX,RUN_DIR,LOG,RESULT,FAILURE_CLASS,SOURCE

辨識：
PEND
RUN
DONE
EXIT
KILLED
MEMLIMIT
TIMEOUT
LICENSE_WAIT
UNKNOWN

規則：
- DONE 不等於 testcase PASS，仍需 parse simulation result。
- EXIT 不直接等於 DUT FAIL。
- MEMLIMIT / LICENSE_WAIT / queue/environment 問題標記 INFRA。
- 對長時間 regression，定期更新 job table。


# v16.1 Change-Only + Per-Job Monitoring

## Change-Only Notification

內部可持續檢查所有 submitted jobs，但 user-facing report 只在下列欄位變化時通知：
- PEND -> RUN
- RUN -> DONE/EXIT
- simulation UNKNOWN -> PASS/FAIL
- UVM_ERROR count 0 -> >0
- UVM_FATAL count 0 -> >0
- first assertion failure
- first simulator crash/fatal
- Early-Kill triggered
- root cause status changed
- fix proposal produced
- rerun result changed

相同狀態不得重複回報。

## Per-Job Agent

每一個 LSF Job 建立獨立 monitor state：
`.dv-harness/lsf/jobs/<JOB_ID>.json`

每個 job agent：
- 用 `bjobs`/project wrapper 查自己的 LSF 狀態。
- 增量讀 `sim.log`，保存 byte offset 或 line offset。
- 不需要每輪重讀整份 log。
- 執行 signature scan + semantic log analysis。
- 更新 Blackboard regression/job/<JOB_ID>。

## Full Job Report

Regression Agent 隨時可產生所有 jobs 的完整 snapshot：
JOB_ID | Pattern | LSF | SIM | UVM_ERROR | UVM_FATAL | EarlyKill | RootCause | FixProposal

但「變化通知」與「完整 snapshot」分開。
