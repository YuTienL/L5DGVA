---
name: multi-agent-orchestrator
description: DV Agent Harness v16 core capability.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# multi-agent-orchestrator
dv-lead 為 supervisor。管理 delegation、parallel、dependency、merge、file/resource ownership。不可亂 parallel implement->push->server->build->verify。

## 這個 Harness 有三種真實的「平行」，先選對一種（2026-09-03 更新）

以下三種都是真的、都已經在跑，差別在誰負責調度。選錯的代價不是效能，是稽核時對不上帳。

**(A) 引擎內建的 graph fan-out（`dv_harness` 的 Python 引擎自己跑 thread）** —— 2026-08-29 起真實存在，
2026-09-03 起涵蓋 RCA。`main_graph.json` 裡標了同一個 `parallel_group` 的節點，會由
`dv_harness/engine.py` 的 `_advance_with_fanout()` 用真正的 `ThreadPoolExecutor` 併發派工，
`AgentTaskStore.create_task()/start_task()/complete_task()` 的記帳由引擎自己完成，你不必也不應該手動補。
目前有兩組：

- `ANALYSIS_G1`：`PROTOCOL_CAPABILITY` PASS 後分岔成 REQUIREMENTS_TRACEABILITY /
  SOC_SCENARIO_PLANNER / INFRASTRUCTURE_AUDIT，匯流到 `ANALYSIS_JOIN`（synthetic node，
  引擎直接穿過去到 VPLAN，不執行）。
- `RCA_G1`：`FAILURE_RECOVERY` 在 `issue_triage_classification_gate` 判為 `REAL_ISSUE` 時（且只在
  這個條件下）分岔成 RCA_RTL_EVIDENCE / RCA_LOG_EVIDENCE / RCA_VIP_SPEC_EVIDENCE
  （分別跑 `rtl-evidence-agent` / `log-evidence-agent` / `vip-spec-evidence-agent`），匯流到
  `RCA_JOIN`——這個 join 是**真的會執行的 stage**（`analysis_debug` 主演，過
  `root_cause_evidence_gate`），它會自己去 `blackboard read` 三個 branch 的 topic 再做獨立綜合，
  結果寫進 `rca_evidence_fusion`。這就是 CLAUDE.md「Important DUT/PHY/Register/VIP changes require
  Multi-Agent evidence acquisition plus independent synthesis」在引擎裡的實作。
  判為 MISCLASSIFIED/KNOWN/BLOCKED 時不分岔，走原本的 FAILURE_RECOVERY -> CHANGE_IMPACT 單線。

**(B) Workflow script 的 `parallel()`（Workflow tool 自己併發跑 `agent()`）** ——
`.claude/workflows/rca-multi-agent-fusion.js`。跟 (A) 是同一套三個 agent profile、同一個
`rca_evidence_fusion` blackboard topic，但由你在對話裡指名呼叫，適用於「graph 目前不在
FAILURE_RECOVERY，但手上就是有一個需要多角度證據的 failure」。兩條路徑刻意共用同一份記錄，
不要另外發明第三個 topic。

**(C) 你自己用 Agent tool 一次訊息裡放多個呼叫** —— 最靈活，但引擎完全不知情：
`dv_harness/multi_agent.py`／`AgentTaskStore` 這時只做記帳，不會自己去平行執行任何東西，
所以下面第 3 點的手動記帳只在這一種情況下需要你做。凡是 (A) 或 (B) 能涵蓋的，優先用它們——
用 (C) 重做一次 (A) 已經有的東西，稽核時會被判成「只有記帳、沒有接進真實路徑」。

**(C) 的具體做法**：

1. **判斷是否可平行**：一組 task 之間如果彼此沒有真正的資料相依（例如 Multi-Agent Evidence Acquisition
   裡的 RTL Agent / PHY-Spec Agent / Register Agent / VIP Agent，各自讀不同來源、互不等對方結果），
   才可以標成同一個 `parallel_group`。凡是 A 的輸出是 B 的輸入（例如
   implement→push→server→build→verify 這種嚴格前後鏈），一律 sequential，不得平行——這是本 skill
   原本就講的規則，沒有改變。

2. **真的平行分派**：確認可平行後，**在同一個 assistant turn 裡，一次呼叫多個 Agent tool invocation**
   （就是你現在自己在這個 session 裡已經在用的手法——本次 session 稍早的 poster-compare-batch1..5、
   audit-intake-guidance/audit-evidence-to-content-path/audit-new-protocol-onboarding 都是這樣一次
   平行開好幾個的真實案例）。不要一個一個序列呼叫再等結果，那不是平行，只是看起來有很多個 agent。

3. **記帳要跟真實動作一致（只有 (C) 需要手動做；(A) 引擎已經幫你做完了）**：分派的同時，對每個 task 呼叫
   `AgentTaskStore.create_task(agent, route, skills, parent_plan, parallel_group="<同一個群組id>", depends_on=[...])`，
   讓 `.dv-harness/agents/tasks.json` 真實反映「這幾個 task_id 是同一批平行派工」，而不是留空
   `parallel_group`——記帳跟實際動作對不上，稽核時會被當成只有記帳、沒有真的平行。

4. **資源衝突交給 `acquire()`**：多個平行 task 如果可能寫到同一份檔案/資源，各自呼叫
   `AgentTaskStore.acquire(res, task_id, agent)`，拿不到（回傳 `False`）的 task 要讓路或改成
   sequential 排在後面，不可以硬寫造成互相覆蓋。

5. **join**：全部平行 task 完成後，你（orchestrator）要親自讀完每個 task 的結果再往下一步走
   （independent-evidence-synthesis／counter-evidence-review 那一關），不能只挑其中一個結果代表全部。
