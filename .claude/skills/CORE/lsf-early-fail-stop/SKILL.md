---
name: lsf-early-fail-stop
description: sim.log 出現已確認的 terminal failure 時，安全停止單一 exact LSF job，保存 evidence 並轉 Failure Triage。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# LSF Early-Fail Stop

前置 Gate：
- exact JOB_ID known
- exact run_dir known
- exact sim.log confirmed
- terminal signature evidence captured
- allowlist checked

預設 terminal triggers：
UVM_FATAL > 0
UVM_ERROR > 0
explicit FAIL
fatal assertion
simulator fatal/crash
project-configured terminal signature

執行：
1. snapshot bjobs
2. save failure evidence
3. bkill EXACT_JOB_ID
4. verify job state changed
5. update Blackboard
6. dispatch debug-agent
7. preserve other jobs

Kill 失敗：
- 不重複無限 bkill
- 標記 KILL_FAILED
- 回報 exact job / command / LSF response


# v19.1 UVM_ERROR Early Stop
依 `.dv-harness/lsf/early_fail_policy.json`：
預設 UVM_ERROR threshold = 0。
因此第一個真實 UVM_ERROR 即可進 terminal validation gate。
驗證不是 benign/allowlisted 且 exact job/log mapping 正確後，可停止 exact JOB_ID。
