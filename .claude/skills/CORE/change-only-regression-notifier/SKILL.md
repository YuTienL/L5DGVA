---
name: change-only-regression-notifier
description: Regression 監控只在 job/simulation/root-cause 狀態真正變化時產生 user-facing 通知，同時維持所有 jobs 完整狀態。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Change-Only Regression Notifier

兩層輸出：

A. Internal Full State
所有 jobs 每輪更新 state。

B. User Change Event
只有 state fingerprint 改變才產生通知。

Fingerprint 建議：
LSF_STATUS
SIM_STATUS
UVM_ERROR_COUNT
UVM_FATAL_COUNT
FAIL_SIGNATURE
EARLY_KILL
ROOT_CAUSE_STATUS
FIX_PROPOSAL_STATUS

通知內容要包含：
- 哪個 JOB_ID
- 哪個 pattern
- 從什麼狀態變成什麼狀態
- 是否 early kill
- sim.log evidence
- 下一個動作

避免每次 polling 都重複印相同表格。


# v19.1 Fast Change Notification
監控循環應盡可能快速，但避免重複刷屏。
Internal monitoring frequency 與 User notification 是兩件事：
- Internal: 持續快速檢查
- User: fingerprint 改變才立即回報
- Periodic Snapshot: 固定週期完整回報
