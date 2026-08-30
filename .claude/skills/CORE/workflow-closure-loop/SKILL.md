---
name: workflow-closure-loop
description: Workflow 分析完成後，將所有 actionable 問題與建議一次納入修正，全部完成後重新詳細驗證，直到 closure。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Workflow Closure Loop

Workflow 不得以「列出問題/建議」作為完成。

## Phase 1 — Discover
完整分析後建立 Finding Registry：

每一項記錄：
- FINDING_ID
- CATEGORY
- SEVERITY
- DESCRIPTION
- EVIDENCE
- AFFECTED_FILE / MODULE / FLOW
- RECOMMENDATION
- ACTIONABLE
- BLOCKED_REASON
- STATUS

分類至少：
BLOCKER
HIGH
MEDIUM
LOW
IMPROVEMENT

## Phase 2 — Consolidate
把所有 actionable findings 一次整理成 Implementation Plan。

原則：
- 所有此次 workflow scope 內可修問題一起修
- 不只修第一個 blocker
- 不只修讓 testcase PASS 的最小 patch
- 相關 architectural / robustness / maintainability 建議若屬本次 scope，也一併完成
- 不修改 unrelated scope
- BLOCKED 項目需明確記錄缺少什麼 evidence / user input / external dependency

## Phase 3 — Implement All
依 dependency/order 執行全部修正。

每次檔案修改仍遵守：
- stale/unrelated comment cleanup
- semantic naming
- VIP/DUT evidence gates
- Git discipline
- no unrelated user changes

## Phase 4 — Re-Verify Everything
所有修改完成後，不得直接宣告完成。

重新執行 Detailed Confirmation：

1. Static/source review
2. Config/schema check
3. Build
4. Targeted verify
5. Relevant single simulations
6. Representative WAVE=1
7. fsdbreport
8. LSF regression（若 scope 需要）
9. Regression monitor/report
10. Git/server exact SHA
11. Signoff review

## Phase 5 — Second-Pass Audit
重新跑原始 Workflow Audit。

確認：
- 原 finding 全部 CLOSED / BLOCKED / ACCEPTED
- 沒有 regression introduced
- 沒有新增 cross-port / cross-instance / cross-subsystem issue
- architecture still符合 Generic Subsystem→SoC model

若第二輪發現新 actionable finding：
→ 回到 Consolidate
→ Implement All
→ Re-Verify
→ Re-Audit

## Completion Definition

只有以下狀態可結束：

CLOSED:
所有 actionable findings 已修正且 re-verify/re-audit PASS。

BLOCKED:
剩餘項目因明確 external dependency/user info 無法完成。

ACCEPTED_RISK:
只有使用者/owner 明確接受的 residual risk。

禁止：
- 問題清單產生後就停止
- 修一半就報 PASS
- 建議留給「之後再做」但仍宣稱 closure
- re-verify 只跑原本失敗 testcase，不做相關 regression/audit
