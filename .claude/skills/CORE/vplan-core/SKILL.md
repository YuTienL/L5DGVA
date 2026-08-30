---
name: vplan-core
description: Protocol-agnostic verification-plan and traceability generator linking features to scenarios, stimulus, checkers, coverage, testcase and status.
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# vPlan Core

Maintain `.dv-workflow/vplan.csv`.

Columns:
REQ_ID,PROTOCOL,FEATURE,SCENARIO,TYPE,PRECONDITION,STIMULUS,EXPECTED,CHECKER,COVERAGE,TESTCASE,PRIORITY,STATUS,SOURCE

Types:
positive / negative / corner / error-injection / stress / recovery / interoperability.

Extend existing plans; do not casually replace them.
For tiny fixes, update only affected traceability.


# AMBA M×N vPlan 要求
依實際 M×N 建立 parallel traffic、same-target contention、cross-traffic、all-master/all-slave、outstanding/ID/ordering/backpressure/burst/error/bridge/reset-recovery scenarios。


# Interrupt / branch-B Traceability

vPlan scenario 若涉及 firmware/interrupt flow，必須記錄：
trigger condition
IRQ/event source
status/mask/clear
branch_fw expected reaction
command/pattern
branch-B target
VIP sequence/API
expected DUT/VIP response
timeout
interrupt clear/ack
simultaneous/pending interrupt scenario
