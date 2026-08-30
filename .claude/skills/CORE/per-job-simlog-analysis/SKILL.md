---
name: per-job-simlog-analysis
description: 針對單一 simulation job 的 sim.log 做增量、語意化、證據化分析，分類 UVM、assertion、simulator、VIP、DUT 與 infrastructure 問題。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Per-Job sim.log Analysis

每個 Job 使用獨立 log cursor。

分析分類：
- UVM_FATAL
- UVM_ERROR
- UVM_WARNING
- assertion
- simulator fatal/crash
- VIP protocol error
- DUT functional mismatch
- scoreboard mismatch
- timeout/deadlock
- infrastructure/license
- expected/allowlisted message

輸出：
signature
first occurrence
last occurrence
count
context lines
classification
severity
terminal
evidence
confidence
recommended next action

有 terminal anomaly：
-> Early-Fail Stop
-> Debug Agent

非 terminal：
-> 持續 monitor。


# v19.1 Mandatory Fix Proposal Output
發現異常後的輸出不能只到 classification。
若可形成 root-cause candidate，必須產生：
root_cause_hypothesis
evidence
confidence
proposed_fix
affected_area
change_impact
recommended_rerun
