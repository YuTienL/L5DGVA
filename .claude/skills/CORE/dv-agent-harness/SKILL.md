---
name: dv-agent-harness
description: 與外部 DV Agent Harness state machine 協作，確保每個 stage 有 deterministic output、evidence、finding disposition、resume/retry 與 closure。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# DV Agent Harness Contract

Harness 負責：
- stage/state
- retry/resume
- history/audit trail
- finding/requirement/regression state
- Git/server/LSF identity
- dashboard/API

Claude DV Workflow 負責：
- technical reasoning
- project discovery
- verification planning
- implementation
- debug/root cause
- verification evidence
- closure recommendation

每個 stage 必須：
1. 讀取目前 project/harness state。
2. 完成本 stage technical work。
3. 更新對應 `.dv-workflow/` / `.dv-harness/` artifacts。
4. 所有結論附 evidence。
5. 不能把 transport success 當 verification PASS。
6. 遇到 external dependency 才標 BLOCKED/WAIT_USER。
7. 可恢復執行，不依賴未保存的口頭上下文。

Harness 不重新實作 DV intelligence。
DV Workflow 不重新實作 persistent orchestration。
