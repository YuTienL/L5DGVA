---
name: regression-status-reporter
description: 將 per-job Blackboard state 彙整成工程師可讀的定期快照與重大事件即時警報。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Regression Status Reporter
雙通道：Periodic Full Snapshot + Change-Only Immediate Alert。
Job table 至少顯示 JOB_ID、Pattern/組合、LSF Status、DV Analysis、UVM_ERROR、UVM_FATAL、Agent Action/Note。
DONE + 待查不得標示 PASS。EXIT + UVM_ERROR=0 仍需查 LSF exit reason、sim.log、timeout、crash、license/infrastructure。
