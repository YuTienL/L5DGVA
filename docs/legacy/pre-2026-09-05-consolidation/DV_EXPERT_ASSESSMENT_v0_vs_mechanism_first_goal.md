> **Superseded.** See START_HERE.md for the current canonical entry point and accurate current numbers/claims.

# DV 專家架構評估 — v0(原始基準)vs. 已確認的 Mechanism-First 目標

評估對象：`D:\DV\Task\DV_Agent_Harness_L5\v0`(未經這次會話任何修改的原始套件,946 個檔案)。
評分基準：這次會話與專案負責人反覆確認過的完整 mechanism-first 流程(Five Source Discovery →
DE Baseline Reproduction/BASELINE_LOCKED → RTL-First Architecture Discovery → Architecture
Calibration/LOCK → Protocol Capability Discovery → Requirement Extraction/Waiver → vPlan →
Verification Architecture/Mechanism Planning/Observability → Test Generation → Build/Verify
(command.txt↔sim.log Semantic Check/FALSE PASS Defense/TRUE_PASS)→ LSF Regression → Coverage
Closure → Failure Recovery(RCA/DUT-TB-VIP-TOOL 歸因/Replay/Fix/Non-Regression)→ System-Level →
DV Expert Feedback Closed Loop → Requirement Closure → Promotion Readiness → SIGNOFF)。

v0 與 v50 修改前的狀態完全一致(已用檔案 diff 確認),所以以下每一項都是這次會話實際發現、
並在 v50 修正過的具體證據,不是重新臆測。

## 1. 執行引擎與目標的落差:24-stage vs 35-stage

`dv_harness/models.py` 的 `Stage` enum 是一條線性的 24 個階段(`ENV_CHECK→INTAKE→DISCOVERY→
PROJECT_MODEL→REQUIREMENTS_TRACEABILITY→...→SIGNOFF`),**完全沒有**：
`DE_BASELINE_REPRODUCTION`、`ARCH_DISCOVERY`、`ARCH_CALIBRATION`、`PROTOCOL_CAPABILITY`、
`VERIFICATION_ARCHITECTURE`、`COVERAGE_CLOSURE`、`SYSTEM_LEVEL`、`EXPERT_FEEDBACK_LOOP`、
`PROMOTION_READINESS`、`BUILD_DEBUG`、`INFRA_RECOVERY`。

`COMMAND_PATTERN` 在 vPlan 之後才做(REUSE/EXTEND/GENERATE 分類);vPlan 在 `PROJECT_MODEL` 之後
立刻進行,**沒有**DE Baseline Reproduction、Architecture Discovery/Calibration、Protocol
Capability Discovery 這些前置步驟。換句話說,v0 的引擎連「RTL-first」都稱不上——它從沒讀過
RTL 就先跳去建 vPlan 了,這與目標架構的核心哲學(先用 RTL 建立可信的 architecture model 再談
vPlan)直接矛盾。

**結論：v0 的執行引擎只實作了目標流程中約 55%(24/~35+)的階段,而且順序本身就跟目標哲學相反。**

## 2. 157 個 gate 全部是死程式碼

`tools/verification_flow/` 底下有 157 支獨立、可執行、契約清楚的 gate 腳本(`false_pass_
resistance_gate`、`simulation_semantic_validation_gate`、`mechanism_readiness_gate`、
`rtl_first_architecture_discovery_gate`……),`.dv-harness/workflow/hard_gate_registry.json` 也
正確登記了全部 157 個。**但 `dv_harness/*.py` 沒有任何一行程式碼呼叫過它們**——`grep -rn` 整個
`dv_harness/` 目錄找不到任何一個 gate 檔名。

這代表 v0 的 `engine.py::run_stage()` 把「Claude subprocess 呼叫成功」直接等同「DV PASS」——
跟目標架構最重視的「LSF DONE ≠ DV PASS」原則,以及 FALSE PASS Defense/TRUE_PASS 這整套機制,
完全沒有被強制執行。v0 沒辦法真正做到目標流程裡「command.txt↔sim.log Semantic Check →
FALSE PASS Defense → TRUE_PASS」這一段,因為沒有任何程式碼會去驗證 agent 自稱的 PASS 是否
有證據支撐。

## 3. 核心引擎有兩個會讓 CLI 完全跑不起來的既有 bug

- `engine.py` 匯入 `stage_profile.extract_provider_usage`,但這個函式在 `stage_profile.py`
  裡根本不存在 → `python -m dv_harness.cli status` 會直接 `ImportError` 崩潰。
- 就算修好上面那個,`engine.py` 呼叫 `StageExecutionProfiler.add_agent_run()` 用的參數跟它
  真正的函式簽名也對不上,第一次真的跑 stage 就會 `TypeError`。

也就是說：**v0 這套 harness 從未真正執行過任何一個 stage**——不是「還沒跑過真實 DUT」這種程度
的未驗證,而是連空跑一次 `dv-harness status` 都會崩潰。目標架構裡描述的整個 autonomous
workflow,在 v0 的實作層級上完全不可能發生。

## 4. Memory Router 宣告了但沒人用

`.dv-harness/inference/inference_policy.json` 完整定義了 hypothesis_fields、confidence_levels
(LOW/MEDIUM/HIGH/CONFIRMED)、`counter_evidence_required: true`——這正是目標架構「Autonomous
Inference：H1/H2/H3 → Supporting/Counter Evidence → Confidence Update → Evidence Gap →
Next-Best-Action」的政策文件。`dv_harness/memory_router.py::route_memory()` 也把 Working/Job/
Project/Engineering/Organizational Memory 的分類邏輯寫好了。**但兩者都只是宣告,從未被任何
執行路徑引用**——`memory_cli.py` 跟 `MemoryConsolidator` 都繞過 router 直接寫死儲存層級,
`MemoryRetriever.search()` 的排序也漏了 Recency(而且 index 裡連 `created_at` 都沒存)。

目標架構裡「Verification Memory 形成真正學習閉環」這句話,在 v0 裡只有骨架,沒有神經連接。

## 5. LSF Regression 完全沒有真實整合

`.dv-harness/lsf/jobs/` 只有一份 README,沒有任何程式碼呼叫 `bsub`/`bjobs`/`bkill`。目標架構
反覆強調的「一個 LSF job = 一個獨立 Job Agent context」「LSF DONE ≠ DV PASS」這兩條核心規則,
在 v0 裡完全沒有對應的執行機制——`regression_reporter.py` 只是被動讀取 agent 自己寫的 JSON,
沒有任何獨立管道去驗證那些 JSON 內容是不是真的。

## 6. 文件本身自相矛盾,而且是 v0 原生就有的問題(不是這次會話造成的)

`VERIFICATION_ARCHITECTURE_MECHANISM_FIRST.md`(自稱 canonical source of truth)、
`SENIOR_DV_ENGINEER_FINAL_ARCHITECTURE.md`、`FINAL_PACKAGE_INDEX.md`、
`.dv-harness/workflow/verification_flow_v13.json` 這四份文件,在 v0 裡就已經寫著
「vPlan FIRST → DUT Architecture Discovery」——跟你明確確認過的正確順序(Architecture
Discovery/Calibration 在前,vPlan 定案在後)相反。`verification_flow_v13.json` 內部自己還有
矛盾：`ordered_steps` 說 Architecture Discovery 是 step 3,但 `v48_rule` 的文字卻說是
「Step 5」。這代表 v0 從一開始文件品質就有內部不一致,不是版本演進中才劣化的。

再加上根目錄 54 份高度重疊的 `.md`(v14/v16/v19/ULTIMATE/FINAL 各版本互相矛盾),沒有任何一份
標示 superseded。

## 7. Dashboard 只是靜態 JSON,看不出任何目標架構關心的東西

`dv_harness/dashboard.py` 原本只顯示 `project/scope/current_stage/overall_status/git_sha/
server_sha/findings_open/closure_iteration` 加一個沒有顏色分類的 stage 列表——完全看不到
graph 進度、LSF job 統計、findings 分項,也沒有任何「YOU ARE HERE」的概念。

## 8. `examples/`、`generated/` 是 100% 假資料

`examples/periodic_job_snapshot/*.json` 看起來像真的 regression 記錄,但每一筆的
`uvm_error_count`/`uvm_fatal_count` 都是 `null`;`examples/generated_pcie_uvm_env/` 是一個從沒
綁定過真實 DUT、也從沒編譯執行過的 UVM 骨架。這違反了目標架構自己最核心的 Evidence Truth
Rule——如果有人誤把這些當成「這套系統已經在 PCIe/USB 上跑出結果」的證據,會得到完全錯誤的結論。

## 總結:v0 對照 mechanism-first 目標的可行性評分

| 面向 | v0 現況 | 對照目標的落差 |
|---|---|---|
| Stage 覆蓋率 | 24/~35 stage,順序與哲學相反 | 嚴重 |
| Gate 強制力 | 157 個都是死程式碼 | 嚴重(false-PASS 風險無防護) |
| 引擎可執行性 | CLI 從未成功跑過一個 stage | 致命(阻擋一切) |
| Memory 學習閉環 | 宣告完整,零連接 | 嚴重 |
| LSF 整合 | 零真實呼叫 | 嚴重 |
| 文件一致性 | 內部自相矛盾 + 54 份重疊文件 | 中度(誤導風險高於功能風險) |
| Dashboard | 無法反映任何 mechanism-first 概念 | 輕度 |
| 範例資料真實性 | 100% 假資料 | 中度(容易被誤用當證據) |

**結論**：v0 這個原始基準package，架構設計文件(mechanism-first 哲學、gate 契約、memory
層級、LSF 政策)本身的**構想**是站得住腳、也相當完整的,但**實作與構想的落差極大**——核心
執行引擎不但沒有涵蓋目標流程過半的關鍵步驟,連最基本的「跑起來不崩潰」都做不到。這不是
「需要微調」的程度，而是需要把這次會話在 v50 做的整套工程(35-stage 重排、gate 接線、CLI
致命 bug 修復、memory router 接線、lsf_client.py 新增、文件順序矛盾修正)重新做一次，v0 才
會是一個真正對齊 mechanism-first 目標、可執行的系統。
