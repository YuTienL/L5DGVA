# DV Agent Harness L5 -- 完整詳細使用與操作手冊

本文件為 DV Agent Harness L5 的完整詳細使用與操作手冊，彙整並取代（supersede）原先的
`docs/DV_Agent_Harness_L5_Detailed_User_Guide_TC.pdf`（2026-08-27 版），並將該版本發布之後、
截至 2026-09-06 為止新增與擴充的全部機制、模組與操作方式一併納入。全書依主題分為十六章，
涵蓋核心架構、UVM 環境生成、AMBA 匯流排分析、系統級驗證整合、Spec-to-VPlan 編譯、DE
Command/Runtime 架構、智慧收案、模擬與 LSF Regression、Loop Engineering、驗證智慧、覆蓋率
結案與治理、供應鏈風險、共用知識中心與第三方元件治理，以及 Human Control Plane、Dashboard
與完整 CLI 參考。各章內容均直接對照 `dv_harness/` 原始碼與 `CLAUDE.md` 之揭露文字撰寫，如遇
本文件與更早版本文件有所出入，應以本文件為準。

## 目錄

1. [導論與核心架構總覽 (Graph / Blackboard / Memory / ReAct / Autonomous Inference)](#1-導論與核心架構總覽-graph--blackboard--memory--react--autonomous-inference)
2. [VIP/UVM 驗證環境生成 (Subsystem-Mode / System-Level Mode, VIP 綁定與結構檢查)](#2-vipuvm-驗證環境生成-subsystem-mode--system-level-mode-vip-綁定與結構檢查)
3. [AMBA M x N 匯流排拓樸與交易分析 (Fabric Discovery / Port Registry / Transaction / Route-Transform)](#3-amba-m-x-n-匯流排拓樸與交易分析-fabric-discovery--port-registry--transaction--route-transform)
4. [AMBA 驗證進階議題 (功能覆蓋率 / 排序網域 / 仲裁 / 安全 / QoS / 效能)](#4-amba-驗證進階議題-功能覆蓋率--排序網域--仲裁--安全--qos--效能)
5. [系統級 (Subsystem-to-System) 驗證：拓樸整合、資源仲裁、失效傳播與系統結案](#5-系統級-subsystem-to-system-驗證拓樸整合資源仲裁失效傳播與系統結案)
6. [Spec-to-VPlan 編譯流程 (需求萃取、衝突偵測、風險評分、vPlan 完整性)](#6-spec-to-vplan-編譯流程-需求萃取衝突偵測風險評分vplan-完整性)
7. [DE Command / Runtime 架構 (指令風格學習、分支所有權、事件登錄、Pattern IR)](#7-de-command--runtime-架構指令風格學習分支所有權事件登錄pattern-ir)
8. [智慧收案 (Intake) 與提問優先序](#8-智慧收案-intake-與提問優先序)
9. [模擬、除錯與 LSF Regression](#9-模擬除錯與-lsf-regression)
10. [Loop Engineering (收斂偵測、預算、斷路器、遙測)](#10-loop-engineering收斂偵測預算斷路器遙測)
11. [驗證智慧 (跨專案挖掘、信心校準、驗證策略建議、影子驗證)](#11-驗證智慧跨專案挖掘信心校準驗證策略建議影子驗證)
12. [覆蓋率結案、Waiver、Signoff 與 Golden Scenario](#12-覆蓋率結案waiversignoff-與-golden-scenario)
13. [治理、Git 保護與供應鏈風險](#13-治理git-保護與供應鏈風險)
14. [共用知識中心與第三方元件治理 (SyoSil / ATB)](#14-共用知識中心與第三方元件治理-syosil--atb)
15. [Human Control Plane、Dashboard 與 GUI](#15-human-control-planedashboard-與-gui)
16. [完整 CLI 指令參考與端到端使用範例](#16-完整-cli-指令參考與端到端使用範例)

---

## 1. 導論與核心架構總覽 (Graph / Blackboard / Memory / ReAct / Autonomous Inference)

DV Agent Harness L5 是一套以「證據優先」為最高原則的驗證流程自動化框架。整個系統的行為並非交由 LLM 自由發揮，而是由五個彼此獨立、各司其職的機制共同組成一套可稽核的執行骨架：**Graph**（工作流程權威）、**Blackboard**（當前驗證真相）、**Memory**（歷史工程知識）、**ReAct 內迴圈**（單一 stage 內的反思式重試）、以及 **Autonomous Inference**（Hypothesis → Evidence → Confidence → Gap → Next-Best-Action 的量化推理）。`CLAUDE.md` 的 Core Operating Rules 開宗明義寫著：「Graph is the global workflow authority. Blackboard stores current verification truth. Verification Memory stores historical verified engineering knowledge... Memory is prior knowledge, not current evidence.」本章即以這五者為主軸，說明它們在 `dv_harness/` 原始碼中的實際落地方式，以及各自明確揭露的邊界。

### Graph：全域工作流程權威

`dv_harness/models.py` 定義了 `Stage`（如 `ENV_CHECK`、`DISCOVERY`、`DE_BASELINE_REPRODUCTION`、`VPLAN`、`IMPLEMENT`、`BUILD`、`VERIFY`、`REGRESSION`、`FAILURE_RECOVERY`、`SIGNOFF` 等，涵蓋從 intake 到簽核的完整驗證生命週期）與 `Status`（`NOT_STARTED`、`RUNNING`、`PASS`、`FAIL`、`PARTIAL`、`BLOCKED`、`RETRY`、`WAIT_USER`、`CLOSED`、`ACCEPTED_RISK`）。`HarnessState`/`StageState` 是持久化在 `state.json` 中的執行狀態，包含 `current_stage`、`overall_status`、每個 stage 的 `attempts`（受 `policy.max_stage_retries` 限制的重試計數，範圍侷限在單一 graph node，一旦換 stage 便歸零）。

真正決定「下一步該去哪」的是 `dv_harness/policy.py` 的 `graph_next(current, status, root)`：它讀取 `.dv-harness/graph/main_graph.json` 的邊定義來路由，只有在沒有 graph 檔案或找不到對應邊時才退回到 `next_stage()` 這個線性的 `ORDER` 陣列。`engine.py` 的 `DVHarness.run_stage()`／`loop()` 是實際驅動者：每次呼叫 `run_stage()` 執行一個 stage 一次，讀出 `ss["status"]`，若是 `FAIL` 且重試已耗盡則呼叫 `graph_next` 走向該 stage 的 FAIL 邊；`policy.can_signoff(state, cfg, blackboard)` 則是 `SIGNOFF` 之前的硬性關卡——即便所有 gate 都通過，只要 Blackboard 上記錄的 `qualified_conclusion` 標示 `is_qualified: false`，或 `require_second_pass_audit` 未滿足，signoff 仍會被 BLOCKED，且**沒有**自動改道，必須交由人類決策。

值得注意的揭露事項：`planner.py`、`react.py`、`router.py`、`multi_agent.py`、`skill_resolver.py` 這幾個模組雖然存在且經過 2026-08-28 架構稽核確認「正確」，但從未被任何實際執行路徑 import 過；已刪除的 `graph_runtime.py` 同樣是「真實但未接線」的殘留。`engine.py` 選擇直接在 `run_stage()` 內重用這些底層模組（`GraphDefinition`、`Blackboard`、`RouteResolver`、`PlanStore`、`MultiAgentOrchestrator`、`ReactRecorder`、`SkillResolver`），而非整包導入那套從未接線的 GraphRuntime——這是一個「模組真實存在但曾經未被呼叫」的典型案例，讀者在查找某個機制是否「真正生效」時，務必以 `engine.py` 的實際 import 與呼叫點為準，而非模組本身是否存在。

### Blackboard：當前驗證真相

`dv_harness/blackboard.py` 的 `Blackboard` 類別是一個以 topic 為單位、寫入 `.dv-harness/blackboard/<topic>.json` 的鍵值儲存區，`write()` 自 2026-09-04 起改為透過 `storage._atomic_replace()` 做 atomic replace（先寫暫存檔再 `os.replace()`），`read()` 對 Windows 上常見的 `PermissionError` 與部分損毀的 JSON 具備重試機制——但若整個重試預算耗盡仍讀不到合法內容，會直接拋出例外，而非悄悄回傳 `default`，因為「回報一個無法讀取的 topic 為『不存在』，等同於把『沒有紀錄驗證真相』偽裝成事實，這正是 Blackboard 絕不能犯的錯誤」。

Blackboard 上有若干具名的結構化 topic，例如 `findings`（open/closed 缺陷登記表，`engine.py` 的 `_sync_findings_state()` 會把計數鏡射回 `HarnessState`）、`debug_loop_history`（每一輪完整的 Fix→Push→Build→Verify 迴圈紀錄，用來回答「這個失敗已經跑過幾輪除錯」這種跨 stage 節點的問題，因為單一 stage 的 `attempts` 欄位無法回答這個問題）、以及 `qualified_conclusion`（`RE_AUDIT`/`RCA_JOIN` 通過 gate 驗證後，由 `engine._score_root_cause_confidence()` 寫入的「結論品質」記錄）。

CLAUDE.md 的「Blackboard Topics Written Outside the Graph」章節特別揭露：`env_manifest`、`open_questions_decisions`、`connectivity_gates` 這三個 topic 原本只能透過人工呼叫的 CLI/runner（`dv-harness env-manifest generate`、`just connectivity-check`）才會刷新，2026-09-04 之後 `engine.run_stage()` 才新增 `_refresh_declared_subsystem_topics()`，依照 graph node 自己宣告的 `blackboard_read` 欄位（而非寫死的 stage 清單）在進入 stage 前主動刷新這三者，讓純自動化的 `loop()` 也能產生它們。這是一個很好的範例，說明本專案如何持續把「原本只在人工路徑上才會發生的機制」逐步接上自動化路徑。

### Memory：五層歷史工程知識

`dv_harness/memory.py` 定義了 `MEMORY_LEVELS = ["working", "job", "project", "engineering", "organizational"]` 五個層級，每筆紀錄寫入前都會先經過 `_guard_record_before_write()`——先做 `memory_security.redact_record()` 秘密偵測與遮蔽，再做 `memory_artifact_policy.enforce_record_artifact_policy()` 大型內容截斷，且順序刻意固定為「先遮蔽、後截斷」，避免截斷把一段跨行的 SSH 私鑰切斷而讓遮蔽規則失效。`memory_router.py` 的 `route_and_store()` 依照紀錄的 `kind` 決定該落在哪一層；晉升規則是嚴格單向的：Engineering → Organizational **只能**經由 `promote_to_organizational()`，且必須同時滿足三個條件——質性上 CLOSED/VERIFIED、`inference.score_confidence()` 給出 HIGH、以及 `confirmation_count >= ORGANIZATIONAL_MIN_CONFIRMATIONS`（硬編碼為 2，意即需要第二次獨立的運行重新推導出同一個 root_cause，而非同一次運行被計數兩次）。CLAUDE.md 明白寫著：「Memory is prior knowledge, not current evidence... Never promote an unverified hypothesis straight to Engineering or Organizational Memory.」

Memory 與 Blackboard 的分野在此清楚體現：Memory 是「先前知識」，任何從 Memory 檢索到的候選假說在使用前都必須用當前的 RTL/VIP/sim.log/波形證據重新驗證，絕不可直接當作已確認的 root cause——這正是 Evidence Truth Rule 對 Engineering Memory Policy 的具體套用。

### ReAct 內迴圈：`react_loop.py`

`dv_harness/react_loop.py` 的 `InnerReactLoop` 是一個**存在於單一 stage 呼叫內部**的 Reason-Act-Observe-Reflect-RePlan 迴圈，介於「adapter 呼叫產生 `result.text`」與「賦值 `ss['status']`」之間，並不取代 `engine.loop()` 的外層重試機制——`loop()` 依然每個 outer attempt 呼叫一次 `run_stage()`，並照舊讀取 `ss["status"]`。是否啟用受兩個條件同時控制：graph node 自身的 `react` 布林欄位（預設 `True`）與 `cfg["policy"]["enable_inner_react_loop"]`（全域開關，預設 `True`）；只要有一個為否，該 stage 就完全不進入這個模組，走回原本的 PARTIAL + `replan_stage()` 路徑。

`build_menu()` 產生的每一個 `MenuOption`（動作種類為 `RETRY_TARGETED`、`REQUEST_EVIDENCE`、`REROUTE`、`CONVERGE_TERMINATE`、`CONVERGE_NO_NEW_INFORMATION` 之一）都必須源自真實的 registry/graph/gate 資料，絕非 LLM 自行編造；其中 `REROUTE` 選項只有在真的存在對應的 `graph.GraphDefinition` 節點時才會被提供，一個幻覺出來的目標節點會被直接捨棄。

### Autonomous Inference：`inference.py` 的量化推理

`dv_harness/inference.py` 把過去只存在於 skill 散文中的 Hypothesis → Evidence → Confidence → Gap → Next-Best-Action 流程，變成真正的可執行 Python 運算。`score_confidence(independent_sources_count, evidence_refs_verified, counter_evidence_count, multi_agent_consensus_count)` 依公式 `base = min(sources,3)*2 + (2 if verified else 0) - counter*3`（若多代理共識 ≥2 再加 2）換算成 `HIGH`/`MEDIUM`/`LOW` 三級，並設有安全下限：只要存在未處理的反證（`counter_evidence_count > 0`），即使分數達標也不得回報 `HIGH`，會被強制降為 `MEDIUM` 並標記 `capped_by_counter_evidence`。`identify_gap()` 是一個純粹的集合差集運算（required 減去 supplied，大小寫敏感、不做模糊比對）。`next_best_action(protocol, gaps, root, gap_action_catalog=None)` 則對照 `protocol_builder_registry.json` 給出具體下一步建議，2026-09-04 起新增的 `gap_action_catalog` 參數讓非 DV 領域的呼叫者（例如 `capability_evolution.py`、`golden_flow_readiness.py`）可以重用同一套「Gap → Action」引擎邏輯，而不必各自重寫一份。

CLAUDE.md 特別強調此模組**刻意不與**另外兩個外觀相似的分級機制共用詞彙：`connectivity.classify_bind_tier()`（T1~T4，依證據「種類」而非「數量」排序，一個已存在的 bind 天生就贏過任何量的結構匹配）與 `question_queue.classify_tier()`（SELF_RESOLVE/SAFE_TO_ASSUME/CANNOT_ASSUME，Tier 3 是「必須由人決定」的升級路徑，而非低分）。`score_confidence()` 計的是證據「數量」的加法排序，兩者語義根本不同，硬套會讓「一個已存在的 bind」與「結構性匹配」得出相同的 MEDIUM 分數，抹去了原本刻意保留的優先序差異——這是本專案「刻意不整合看似相似機制」的一個具代表性案例。

### 三層記憶查詢與人機邊界的收斂

除了上述五個核心機制，`dv_harness/question_queue.py` 的三級「詢問人類」協定（SELF_RESOLVE / SAFE_TO_ASSUME / CANNOT_ASSUME）與 `dv_harness/source_authority.py` 的九層「來源權威順序」（1. 實際模擬結果最高 …… 9. VIP 文件最低）共同構成了本系統遇到證據衝突或需要人類決策時的收斂路徑：`source_authority.resolve_conflict()` 只回答「兩者互相矛盾時該採用哪個值」，同層級衝突（`UNDECIDABLE_SAME_AUTHORITY`）或任何解出的衝突都會經由 `escalate_conflict()` 送入 question queue 成為一個 Tier-3 阻斷式問題，而非由系統自行仲裁孰是孰非。這正呼應了 Core Operating Rules 的最後一條精神：「Human Override is always valid」——上述所有機制（Graph 路由、Blackboard 記錄、Memory 晉升、ReAct 動作選單、Inference 信心分級）最終都設計為在遇到無法自動判定的節點時，明確地把決定權交還給人類，而不是用一個看似合理的猜測掩蓋這個邊界。

