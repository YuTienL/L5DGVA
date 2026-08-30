---
name: multi-agent-orchestrator
description: DV Agent Harness v16 core capability.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# multi-agent-orchestrator
dv-lead 為 supervisor。管理 delegation、parallel、dependency、merge、file/resource ownership。不可亂 parallel implement->push->server->build->verify。

## BUG FIX（2026-08-29，poster-compliance-audit「真正平行派工」缺失）

**這個系統的「平行」是真的由你（承接 dv-lead/analysis-agent 這個角色的 Claude session）用 Agent tool
一次訊息裡放多個呼叫來實現的，不是 `dv_harness` 的 Python 引擎內部有 thread/async 在跑。**
`dv_harness/multi_agent.py`／`AgentTaskStore` 只做記帳（記錄哪些 task 屬於同一個 `parallel_group`、
`depends_on` 是什麼、`acquire()` 檔案/資源鎖定避免同一個資源被兩個 task 同時寫），不會自己去平行執行
任何東西——這件事本來就該由你，這個正在跑的 orchestrating agent，親自做到。

**具體做法**：

1. **判斷是否可平行**：一組 task 之間如果彼此沒有真正的資料相依（例如 Multi-Agent Evidence Acquisition
   裡的 RTL Agent / PHY-Spec Agent / Register Agent / VIP Agent，各自讀不同來源、互不等對方結果），
   才可以標成同一個 `parallel_group`。凡是 A 的輸出是 B 的輸入（例如
   implement→push→server→build→verify 這種嚴格前後鏈），一律 sequential，不得平行——這是本 skill
   原本就講的規則，沒有改變。

2. **真的平行分派**：確認可平行後，**在同一個 assistant turn 裡，一次呼叫多個 Agent tool invocation**
   （就是你現在自己在這個 session 裡已經在用的手法——本次 session 稍早的 poster-compare-batch1..5、
   audit-intake-guidance/audit-evidence-to-content-path/audit-new-protocol-onboarding 都是這樣一次
   平行開好幾個的真實案例）。不要一個一個序列呼叫再等結果，那不是平行，只是看起來有很多個 agent。

3. **記帳要跟真實動作一致**：分派的同時，對每個 task 呼叫
   `AgentTaskStore.create_task(agent, route, skills, parent_plan, parallel_group="<同一個群組id>", depends_on=[...])`，
   讓 `.dv-harness/agents/tasks.json` 真實反映「這幾個 task_id 是同一批平行派工」，而不是留空
   `parallel_group`——記帳跟實際動作對不上，稽核時會被當成只有記帳、沒有真的平行。

4. **資源衝突交給 `acquire()`**：多個平行 task 如果可能寫到同一份檔案/資源，各自呼叫
   `AgentTaskStore.acquire(res, task_id, agent)`，拿不到（回傳 `False`）的 task 要讓路或改成
   sequential 排在後面，不可以硬寫造成互相覆蓋。

5. **join**：全部平行 task 完成後，你（orchestrator）要親自讀完每個 task 的結果再往下一步走
   （independent-evidence-synthesis／counter-evidence-review 那一關），不能只挑其中一個結果代表全部。
