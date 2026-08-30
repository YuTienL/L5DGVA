---
name: iron-rules
description: DE/DV 工業驗證流程不可違反的強制鐵則，涵蓋中文輸出、dangerously-skip-permissions、push/build/verify/WAVE/fsdbreport、修改前查證、命名、註解清理與 Coverage 預設策略。
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# DE / DV Workflow 強制鐵則

以下規則是強制要求。

## 鐵則 1：使用者可見輸出一律中文

- 狀態、問題、分析、下一步、Readiness、驗證結果、Signoff 一律中文。
- command、signal、class、module、path、tool error、VIP API 名稱保留原文。
- 程式碼 identifier 不強制翻譯。

## 鐵則 2：Claude Code 啟動固定使用 dangerously-skip-permissions

PC 端標準啟動：

`claude --dangerously-skip-permissions`

目的：
- 不因 shell/file permission prompt 中斷長時間 DV workflow。
- 讓多 Agent、push、remote build、verify、regression、waveform 分析能連續執行。

即使使用 `--dangerously-skip-permissions`，仍必須遵守 project safety hooks 與本文件的 destructive-operation 禁令。

不得因為權限跳過而自動執行未要求的：
- git reset --hard
- git clean -f
- git push --force
- 大範圍刪除
- 破壞 unrelated user changes

## 鐵則 3：正式驗證順序固定

任何需要 Server 驗證的修改：

PUSH
→ BUILD
→ VERIFY
→ RUN WAVE=1
→ FSDBREPORT ANALYSIS
→ SIGNOFF

不得只因 BUILD PASS 或 VERIFY PASS 提前宣告完成。

## 鐵則 4：每次檔案修改，同步清除過時/多餘/不相關註解

針對此次修改影響區域，檢查並移除：
- 過時註解
- 已失效說明
- 與現況不一致說明
- 重複/多餘註解
- 被移除功能留下的註解
- 誤導性的 FIXME/TODO/NOTE

只移除可確認失效或與此次修改直接相關的內容。
不可藉機大量重寫無關文件。
仍有價值的設計理由、限制、workaround 說明必須保留。

## 鐵則 5：branch-B / VIP pattern 修改前必須先查 VIP evidence

修改任何：
- branch-B
- VIP pattern
- VIP sequence
- VIP adapter
- VIP config
- command→VIP mapping

之前，依序查：

1. VIP examples
2. VIP 使用手冊 / User Guide
3. VIP source code
4. VIP class/API reference
5. 現有 project VIP 使用方式

必須記錄：
- 查了哪些 reference
- 使用哪個 class/API/sequence
- 有何限制
- 為何選擇該方式

若 evidence 不足且會影響正確性，不得猜測實作。

## 鐵則 6：branch-A / branch_fw 修改前必須先查 DUT evidence

修改任何：
- branch-A
- branch_fw
- DUT-side adapter
- DUT interface mapping
- toward-DUT command dispatch

之前，依序查：

1. DUT RTL source
2. SoC hierarchy / DUT port mapping
3. PHY documents
4. Programming Guide
5. Register / Integration Guide
6. active defines / parameters / design config
7. 其它相關設計資料

必須確認：
- hierarchy
- port
- role
- interface boundary
- clock/reset
- PHY requirement
- programming/config dependency

禁止只依 signal/module 名稱猜功能。

## 鐵則 7：禁止過度抽象命名

避免無實際語意的名稱，例如：
data, info, tmp, thing, obj, item1, handler1, process_data, do_work,
generic_seq, common_test, misc, helper（若無法看出責任）。

名稱需表達實際 protocol / role / function，例如：
- pcie_gen5_ep_mem_write_seq
- usb3_host_bulk_out_cmd_handler
- axi4_ddr_write_scoreboard
- csi2_rx_ecc_error_checker
- canfd_busoff_recovery_test
- usb_host0_branch_a
- pcie_rc_vip0_branch_b

若 repository 既有 coding convention 有更嚴格規則，遵守既有規則。

## 鐵則 8：四步驗證主流程

### Step 1 — PUSH
PC：
- review diff
- 確認無 unrelated change
- 確認註解清理
- push intended branch/commit
- 記錄 commit hash

### Step 2 — BUILD
Server：
- checkout/sync exact pushed commit
- verify remote HEAD == expected commit
- canonical build
- Coverage OFF
- BUILD PASS 才進下一步

### Step 3 — VERIFY
Server：
- targeted testcase/scenario
- Coverage OFF
- VERIFY PASS 才進 WAVE run

### Step 4 — WAVE=1 RUN + FSDBREPORT
Server：
- 同一代表性 testcase/scenario
- WAVE=1
- Coverage OFF
- waveform 從 time=0 dump 到 simulation end
- 跑完後使用 fsdbreport 分析波形
- fsdbreport 必須確認 scenario 的關鍵 signal/event/transaction

完成條件：
PUSH PASS
BUILD PASS
VERIFY PASS
WAVE=1 RUN PASS
FSDBREPORT ANALYSIS PASS

任一階段 FAIL，不得 SIGNOFF PASS。

## 鐵則 9：WAVE=1 預設完整 simulation waveform

WAVE=1 預設：
- start = time 0
- end = simulation end
- 不自動縮短 dump window
- 不自動改成 trigger-based partial dump

只有 user 明確要求才能改變。
若現有 WAVE=1 flow 不符合，必須明確指出差異。

## 鐵則 10：Coverage 預設關閉

預設 Coverage OFF。

只有：
- user 明確要求
- coverage closure
- vPlan coverage/signoff 明確要求

才允許開啟。

一般 debug / build / targeted verify / WAVE run 不自動開 Coverage。

## Signoff Gate

PASS 必須同時滿足：
- 必要 reference/evidence 已查
- 命名符合語意
- 修改區域過時/多餘/不相關註解已清理
- PUSH PASS
- remote exact commit verified
- BUILD PASS
- VERIFY PASS
- WAVE=1 完整 run PASS
- fsdbreport 分析完成且符合預期
- Coverage 維持 OFF，除非工作明確要求打開
- Review 無 BLOCKER

缺任何一項，不得報 PASS。


## 鐵則 11：工具使用不清楚時，先查手冊，再查網路

任何工具、command、option、API、script 使用方式不確定時，例如：

- fsdbreport
- VCS
- Verdi
- Synopsys VIP utilities
- bsub / LSF
- simulator options
- coverage tools
- waveform tools
- protocol-specific utility
- project-local helper script

禁止憑記憶或猜測直接執行。

強制查證順序：

1. Project 內既有 script / examples / wrapper
2. 本地安裝的官方 User Guide / Tool Reference / man page / help
3. VIP/tool 官方 class/API reference
4. 官方網站文件 / 官方 knowledge base
5. 網路上的可信技術資料
6. 若仍不清楚，停止並明確標示 BLOCKED 或詢問使用者

例如 `fsdbreport`：
先查現有 project 使用方式與本地 Verdi/FSDB 使用手冊，
再查官方文件，
最後才查網路相關範例或技術文章。

每次採用非 project 現有用法時，應記錄：
- 查證來源
- 使用的 command/option
- 適用版本
- 為什麼此用法適合目前 workflow

不得因為 `--dangerously-skip-permissions` 而略過工具使用方式查證。


## 鐵則 12：Linux Server 執行環境必須由 evidence 或使用者確認

Server 驗證前必須明確：
1. SSH 到哪一台 Linux Server
2. 使用哪個 user account
3. 使用哪種 shell
4. 登入後依序 source 哪些 environment
5. 在哪個 Linux path 工作
6. build / verify / run 若使用不同 path，分別確認

Workflow 先查 project evidence；若無法唯一確定，向使用者詢問。

禁止猜 server、account、source flow、workdir。

Password：
- 可以由登入程式互動要求使用者輸入
- 不回顯、不記錄、不保存、不 commit、不 push
- 不寫入 `.claude` / `.dv-workflow` / JSON / log / script

SSH context 未確認，不得開始正式 BUILD。


## 鐵則 13：Reference Environment Path 必須確認

若 Workflow 要使用既有 USB UVM Reference Environment：

必須明確取得：
- Linux Server
- `REFERENCE_ENV_PATH`
- Reference branch/tag/commit（若適用）
- Reference access mode，預設 READ_ONLY
- `WORK_ENV_PATH`

若 project evidence 無法唯一確認，必須詢問使用者。

禁止：
- 猜 Reference path
- 猜 Reference server
- 把 Reference path 當 Work path
- 未經使用者明確要求修改 Reference Environment
- 將 USB-specific implementation 當成所有 protocol 的 universal template

Reference Environment 只提供 architecture/pattern/reference evidence。
目前 DUT 的 hierarchy、VIP type/count/bind、protocol behavior、vPlan、command gap 必須重新推導。


## 鐵則 14：禁止 Global Scheduler 造成跨 Port 互卡，採 Resource-Scoped M×N Concurrency

禁止使用單一 Global Scheduler 讓不相關 Port / VIP / Slave resource 互相等待。

預設原則：
- 每個 resource / VIP / port 有自己的 queue / dispatch / flow-control context。
- 不同 resource 的 transaction 應能平行執行。
- 只有競爭同一 shared resource 時，才允許該 resource scope 內 arbitration / serialization。
- 不得因一個 APB/AXI/USB/PCIe port stall 而阻塞不相關 protocol/resource。

APB：共享單一 VIP 時可 N:1，採 resource-local serialization。
AHB/AHB-Lite：依 bus ownership/arbitration semantics 建模，只在 shared resource 競爭時仲裁。
AXI3/AXI4：支援 Multi-Master × Multi-Slave M×N，保留 AW/W/B/AR/R channel independence、AXI ID、outstanding、ordering、burst、backpressure。
ACE-Lite：M×N + 實際存在的 coherency-lite/domain/barrier semantics。
AXI-Stream：per-stream queue / TVALID-TREADY flow-control，不套 memory-mapped global arbitration。

branch_fw 是 N:M routing / mapping / adaptation / command dispatch / resource-local arbitration，
不是 Central Global Scheduler。


## 鐵則 15：Functional Failure 必須完成 Failure Recovery Loop

Functional/Unknown Failure：
Log Analysis + FSDB/fsdbreport Evidence
→ Root Cause
→ Fix
→ BUILD
→ VERIFY
→ Rerun Regression。

若再次 failure，重新進入 loop。
禁止只 rerun、不分析、不驗證 fix。


## 鐵則 16：Single Simulation PASS 自動 Promotion 到 Regression

新的或修復後的 single simulation，只有完成：
PASS + Checker + WAVE=1 + fsdbreport + reproducibility
後，才自動加入/更新 Regression List。

保存完整 pattern、command、simulation options、DUT/VIP config、seed policy 與 metadata。
必須 signature 去重。
Regression 預設 Coverage=OFF、WAVE=0。


## 鐵則 17：UVM Environment 必須支援 User-Defined Pattern 與 Make API

一般 DE/DV engineer 可以透過 `make`：
新增、驗證、執行、列出、加入/移除 regression pattern。

USER pattern 與 DV Workflow pattern 共用同一 Pattern Registry。
任何新 pattern 都必須經 schema/duplicate/single-sim/WAVE/fsdbreport gate 後才能進正式 Regression。


## 鐵則 18：統一 Simulation Option Model

所有 Pattern / Single Simulation / Regression 至少支援：

WAVE=0/1
PA=0/1
FSDB_START
FSDB_STOP
TIMEOUT

優先級：
Make/CLI override > Pattern manifest > Regression group > Project default。

正式代表性 waveform verify：
WAVE=1, FSDB_START=0, FSDB_STOP=simulation_end, Coverage=OFF。

一般 regression：
WAVE=0, PA=0, Coverage=OFF，TIMEOUT 由 pattern 決定。


## 鐵則 19：branch_fw 必須是 Interrupt/Event-Driven Dispatcher

branch_fw 由 DUT/SoC interrupt 或明確 event 觸發。
它負責 interrupt/event decode、scenario/command mapping、branch-B dispatch、ack/clear/timeout，
不是 Central/Global Scheduler。

branch_fw 修改前必須先查 DUT RTL、interrupt controller/register map、programming guide 與相關文件。


## 鐵則 20：VIP Testing Scenario 必須位於 branch-B

branch_b0/1/2... 是 VIP testing scenario / pattern / sequence 的正式承載層。
branch-B 數量由 VIP port/instance/topology 決定，不要求與 branch-A 1:1。

vPlan/command/pattern 必須可追到 branch-B 與實際 VIP sequence/API。
任何 branch-B 修改前必須完成 VIP evidence lookup。


## 鐵則 21：Git Sync → Commit → Push 必須可追溯且不可破壞使用者變更

Workflow 開始前先確認 repository / branch / remote / local changes / remote status。

禁止自動：
git reset --hard
git clean -fd
git push --force
擅自丟棄/stash使用者未確認的變更。

Commit/Push 必須只包含本次 intended scope。


## 鐵則 22：Server 驗證必須使用剛 Push 的 Exact Git Commit

PUSH 後：
Linux Server checkout/sync
→ `git rev-parse HEAD`
→ 必須等於 PC 記錄的 expected commit SHA。

若存在 submodule：
superproject SHA + 每個 submodule SHA 都必須記錄與比對。

SHA 不一致不得 BUILD/SIGNOFF。


## 鐵則 23：DevOps Pipeline 必須 Carry Evidence, Not Assumptions

每個 pipeline stage 必須保存可追溯 evidence：
Git SHA
build log
verify result
LSF jobs
failure classification
wave/fsdbreport evidence
regression report
signoff disposition。

不得只用「job成功」推論功能驗證 PASS。


## 鐵則 24：Workflow 啟動前必須先完成 Claude CLI Environment Readiness

正式執行 DV Workflow 前先確認：
Claude CLI version/path
Superpowers plugin
dv-workflow
task-required protocol profiles
Core skills
7 Agents
settings/settings.local
plugin errors
skill scope/inventory。

READY → 直接執行。
PARTIAL → 可做的先做，再處理缺口。
BLOCKED → 只詢問/修復 minimum required dependency。

禁止把 plugin enabled、skill directory exists、agent exists 三者互相等同。


## 鐵則 25：Workflow 發現的所有問題與建議必須一次完成修正，再重新詳細確認

Workflow 分析完成後：

1. 收集全部 findings / recommendations。
2. 所有本次 scope 內 actionable 項目必須一起納入修改。
3. 不可只修第一個 failure 或只做最小 patch。
4. 全部修改完成後，重新做一次完整 detailed verification。
5. 再重新跑一次原始 audit，確認沒有遺漏與新增問題。
6. 若重新 audit 又發現 actionable issue，必須再次修正與驗證，直到 closure。

只有：
CLOSED / BLOCKED / ACCEPTED_RISK
可以作為最終狀態。

BLOCKED 必須指出缺少的 user input / document / environment / external dependency。
ACCEPTED_RISK 必須有明確 owner/user disposition。


## 鐵則 26：Generic Scope 優先
所有架構與宣傳/報告都以 Any Subsystem → Full SoC 為主軸。
USB/PCIe/Ethernet/AMBA/MIPI/CAN-FD 只能作 protocol profile/example，不得把單一 protocol 當 Workflow 中心。


## 鐵則 27：command.txt 必須由 vPlan 與 Evidence 驅動
既有 DE command.txt 先 REUSE/EXTEND；缺少的 command 由 vPlan gap GENERATE。
必須保留 vPlan→command→handler→VIP sequence→checker/coverage→pattern/regression traceability。


## 鐵則 28：branch_fw 不得被當成 Protocol Traffic Scheduler
branch_fw 僅負責 Interrupt/Event-driven control/command dispatch。
AMBA M×N、USB/PCIe/Ethernet 等 traffic concurrency 由各 branch-B scenario、VIP 與 protocol-specific resource model 處理。


## 鐵則 29：Requirement 必須可追溯到 Verification Evidence
Spec/Design Requirement 必須能追到 vPlan、scenario、command/pattern、checker/coverage、regression result。
Critical/High requirement 無 evidence 不得 Signoff。


## 鐵則 30：SoC 驗證不能只等於各 Protocol Testcase 相加
Subsystem/Multi-Subsystem/SoC scope 必須分析 cross-subsystem、cross-protocol、shared-resource、concurrency、end-to-end scenario。


## 鐵則 31：每次 Git Change 必須做 Verification Change Impact
修改後必須映射到 requirement/vPlan/pattern/coverage/regression。
Regression selection 至少包含 TARGETED + DEPENDENCY + SAFETY。
Impact confidence 不足時擴大 regression，不得冒險縮小。


## 鐵則 32：Harness 管 State，DV Workflow 管 Verification Intelligence
Harness 負責 stage/retry/resume/history/governance。
Claude Agents/Skills 負責 hierarchy、vPlan、VIP/UVM、debug、coverage、regression、signoff 技術判斷。
禁止在 Harness 裡複製一套 DV reasoning。


## 鐵則 33：Agent Stage Result 必須可持久化與恢復
每個 stage 必須留下 evidence/artifact/state。
Claude session 中斷後不得因缺少口頭 context 無法繼續。


## 鐵則 34：Claude Transport Success 不等於 Verification PASS
claude/SDK return code=0 只代表 agent invocation 成功。
BUILD/VERIFY/REGRESSION/SIGNOFF 必須依 project evidence 判斷 PASS/FAIL。


## 鐵則 35：Graph 是全局唯一流程控制骨架
Agent/ReAct 不得跳過 Graph 自行改變全局 stage。


## 鐵則 36：Plan 必須 Evidence-Driven
複雜 Node 先 plan；replan 需 trigger、reason、evidence。


## 鐵則 37：Multi-Agent Parallel 必須有 Dependency 與 Ownership
不可因平行化造成同檔覆蓋或流程錯序。


## 鐵則 38：Blackboard 是 Shared Verification Truth
跨 Agent 關鍵事實必須寫入 Blackboard。


## 鐵則 39：ReAct 只做 Local Decision
ReAct 不取代 Graph/Plan；保存 engineering reasoning summary，不保存私有 chain-of-thought。


## 鐵則 40：Skill Resolver 只載入必要能力
避免所有 Skills 同時進 context。


## 鐵則 41：Graph Node Completion 必須 Evidence Gate
Transport success 不等於 verification PASS。


## 鐵則 42：每個 LSF Job 必須有獨立 Job Agent Context
所有 submitted jobs 都必須被追蹤。
每個 JOB_ID 的 sim.log、pattern、options、run_dir、Git SHA、Server SHA 不得和其他 job 混用。


## 鐵則 43：Regression 對使用者只回報真正狀態變化
Harness 內部持續更新所有 jobs 狀態，但相同 fingerprint 不重複通知。
變化通知不能取代完整 regression snapshot/report。


## 鐵則 44：sim.log Terminal Failure 可提早停止 Exact Job
UVM_FATAL、UVM_ERROR 超過 policy threshold、fatal assertion、simulator crash 或 project-defined terminal signature 經 evidence 確認後，可以提早停止該 exact JOB_ID。
禁止 wildcard/user-wide/queue-wide kill。


## 鐵則 45：Early Kill 後必須立即 Root Cause + Fix Proposal
Early Kill 不是完成。
Job 停止後必須由 debug-agent 分析 sim.log/FSDB/DUT/VIP/UVM，建立 finding、root cause、confidence 與具體修改方法，再進 closure workflow。


## 鐵則 46：Human Override 永遠有效
使用者可隨時 PAUSE、REDIRECT、STOP、TAKEOVER；介入必須持久化。

## 鐵則 47：User Constraint 高優先級
FREEZE/DO NOT MODIFY/ALLOW WRITE 等限制必須被所有 Agents 遵守。

## 鐵則 48：低 Confidence 不得高風險修改
UNKNOWN/LOW root cause 不得直接觸發高影響 DUT RTL 修改。

## 鐵則 49：Critical Action 必須 Approval Gate
高風險 Git、mass kill、shared infra、signoff policy 等不得靜默自動執行。

## 鐵則 50：Independent Review 不得自我背書
重大 root cause/closure 可由 review-agent 獨立挑戰。

## 鐵則 51：L5 目標是 SIGNOFF-READY
Harness 自主推進到 evidence-closed SIGNOFF-READY；最終組織簽核依公司流程。

## 鐵則 52：Auto 必須可觀察可解釋
任何時間都能回答 STATUS、WHY、EVIDENCE、NEXT ACTION、SOURCE MODIFIED。

## 鐵則 53：定期完整 Job Snapshot
Regression 執行期間依 policy 固定週期回報所有 submitted jobs，即使沒有狀態變化。

## 鐵則 54：定期快照與即時 Alert 並存
Periodic Snapshot 提供全局；Change-Only Alert 對重大狀態變化立即通知，兩者不得互相取代。

## 鐵則 55：LSF DONE 不等於 DV PASS
DONE 後必須完成 sim.log、UVM_ERROR/UVM_FATAL、completion signature、timeout/assertion/scoreboard 分析才可判 PASS。

## 鐵則 56：LSF Status 與 DV Analysis Status 分離
Job state/report 必須分開呈現 scheduler state 與 verification result，禁止混成單一狀態造成誤判。

## 鐵則 57：Snapshot 不得阻塞 GAV
定期回報只提供 observability；除非命中 Approval Gate/User Control，不得因回報而停止 autonomous workflow。

## 鐵則 58：Memory 是 Prior Knowledge，不是 Current Evidence
歷史 memory 只能提供候選假設與優先順序，不能直接證明本次 root cause。

## 鐵則 59：只有驗證 Closure 才能寫入 Engineering Memory
Finding 未 CLOSED/VERIFIED、single sim 未 PASS、regression 未 PASS、re-audit 未 CLEAN 不得 promotion。

## 鐵則 60：Blackboard 與 Memory 必須分離
Blackboard 保存 current truth；Memory 保存 historical verified knowledge。

## 鐵則 61：Job Memory 必須以 JOB_ID 隔離
不同 LSF jobs 的 log、pattern、root cause、fix 不得混用。

## 鐵則 62：Memory Reuse 必須重新驗證 Context Compatibility
Protocol、mode、tool/VIP version、DUT topology/context 不一致時 confidence 必須下降或拒絕 reuse。

## 鐵則 63：Memory 不得保存 Credential
Password、token、license secret、private credential 禁止進任何長期 memory。

## 鐵則 64：錯誤或過時 Memory 必須可淘汰
Outdated/obsolete/bad-reuse memory 必須支援 DEPRECATED/QUARANTINED 並保留 audit history。

## 鐵則 65：成功經驗必須可 Consolidate 與下次 Retrieve
Verified fix closure 後轉成 structured reusable memory，下次相似問題優先檢索。

## 鐵則 66：所有 LSF Submitted Jobs 必須 Per-Job Agent 監控且只在變化時通知

Regression submit 後：
1. 必須取得所有 submitted JOB_ID。
2. 每個 JOB_ID 必須建立獨立 Job Agent / Job Context。
3. 每個 Job Agent 必須持續且盡快檢查：
   - exact LSF job status
   - exact run directory
   - exact sim.log
   - UVM_ERROR / UVM_FATAL
   - assertion / simulator crash / timeout / explicit FAIL
4. Harness 內部持續更新所有 jobs 完整狀態。
5. User-facing notification 只有在狀態 fingerprint 真正改變時才回報，避免重複通知。
6. 定期完整 Snapshot 仍需依 periodic policy 回報全部 jobs，不能被 change-only notification 取代。
7. LSF DONE 不等於 DV PASS；DONE job 必須完成 sim.log 分析才可判定 PASS / FAIL / UNKNOWN。
8. 每個 Job Agent 若發現問題，必須產生 evidence、root-cause status 與修改方法 / fix proposal。


## 鐵則 67：單一 Job 出現可確認異常或 UVM_ERROR 時可 Early Stop 並立即分析修正

每個 Job Agent 分析自己的 sim.log。

若出現以下任一已確認 terminal evidence：
- UVM_ERROR 超過 policy threshold（預設 > 0）
- UVM_FATAL > 0
- fatal assertion
- simulator fatal / crash
- explicit testcase FAIL
- project-defined terminal error signature
- 已確認 unrecoverable deadlock / no-progress condition

則允許：
DETECT
-> VALIDATE exact JOB_ID / run_dir / sim.log
-> SAVE evidence
-> MARK EARLY_FAIL
-> bkill EXACT_JOB_ID
-> VERIFY job stopped
-> debug-agent root-cause analysis
-> fix proposal
-> finding registry
-> IMPLEMENT
-> CHANGE_IMPACT
-> Git push
-> Server exact SHA
-> Build
-> Verify
-> WAVE=1 / fsdbreport
-> Rerun / Regression
-> Re-Audit / Closure

限制：
- 只能 kill exact JOB_ID。
- 嚴禁 wildcard kill、user-wide kill、queue-wide kill。
- warning、benign allowlist、單純字串含 error 但無 terminal evidence，不可直接 kill。
- 其他正常 jobs 必須繼續執行，不可因單一 job fail 停止整批 regression。


## 鐵則 68：Current Findings 必須先完整 Batch Closure
Workflow 啟動後先深度確認目前所有 actionable findings；形成完整 Finding Registry，將 current findings 一批修正、review、Git、Server SHA、build、single verify 後才進 regression。

## 鐵則 69：同一 Regression Batch 必須固定 Verification Baseline SHA
同批所有 LSF jobs 必須綁定同一 Git SHA、Server SHA、build identity、config identity；regression 執行期間禁止任意切換 baseline。

## 鐵則 70：所有 Jobs Closure 後才 Batch-Fix Regression New Findings
每個 job 可 early-kill、root-cause、fix proposal，但 regression 期間的新問題先進 New-Finding Queue；等本批所有 jobs 有 final disposition 後才集中修改，然後新 baseline 重跑。

## 鐵則 71：所有 Findings Closure 後必須重新啟動 Full Deep Workflow
所有 current/new findings 修完且 regression closure 後，重新從零深度分析所有 source files、command.txt、UVM/VIP、branch architecture、scoreboards、coverage、performance、scripts、Git/DevOps、Linux/Claude CLI environment、VCS/Verdi/FSDB、LSF、requirements/vPlan/scenarios、Memory；只有 Final Deep Audit CLEAN 才可 SIGNOFF-READY。

## 鐵則 72：Multi-Agent Parallel Evidence Acquisition + Independent Synthesis
任何重要 DUT / PHY / Register / VIP / branch / testcase / sequence / scoreboard 問題分析或修改前，必須啟動 Multi-Agent 平行查詢 DUT RTL source、PHY Documents、Programming Guide/Register、VIP Examples/Manual/Source/Class Reference；所有 evidence 寫入 Blackboard，再由獨立 Synthesis Agent 彙整 Supporting Evidence、Counter Evidence、Conflict、Missing Evidence、Root Cause、Solution、Change Impact 與 Verification Plan 後才允許 Implement。


## 鐵則 73：Stage Execution Profile 必須分離 Wall Clock 與 Aggregate Agent Runtime
每個 Graph Node / Stage 都必須記錄 AI Execution Telemetry。Stage Wall Clock = 使用者實際等待時間；Aggregate Agent Runtime = 該 Stage 內所有 Agent runtime 加總。平行 Agent runtime 不得直接當成 Stage Wall Clock。Token 只記 provider 真實回報，不得估算。必須可統計 Tool Calls、Retries、Findings、Parallel Saving、Parallelism Efficiency 與 Token Efficiency。


## 鐵則 74：Claude Native Memory 與 Verification Memory 必須分工

Claude/project memory 用於穩定的 project instructions、coding conventions、workflow rules、directory/tool notes 與 user preferences。
Blackboard 保存 current verification truth。
Verification Memory 保存 structured, evidence-closed engineering knowledge。

任何 Verification Root Cause 不得只依賴 Claude/project memory。
Memory 只能作 prior knowledge，必須以 current evidence 重新驗證。
Credential/password/token/secret 禁止進任何長期 Memory。


## 鐵則 75：Document Evidence 必須 Extraction、Versioning 與 Traceability

任何由 PHY document、Programming Guide、Register Guide、VIP Manual、VIP Examples、VIP Source、Class Reference 或其他工程文件所得的結論，都必須能回溯：

Document
-> Version / SHA256
-> Page / Section / Source Location
-> Extracted Evidence
-> Agent Finding
-> Root Cause / Solution

未變更文件應重用已驗證 extraction/index；文件 SHA/version 改變時只重新抽取受影響文件。
Register evidence 必須結構化保存 address/bit-range/field/access/reset-value/source location。


## 鐵則 76：CLAUDE.md、Memory、歷史結論與推測都不是 Current Evidence

對任何問題分析、Root Cause、Fix Proposal、Change Impact 或 Signoff 判斷：

1. 不得直接相信 CLAUDE.md 的紀錄。
2. 不得直接相信 Verification Memory / Project Memory / Engineering Memory 的歷史紀錄。
3. 不得直接相信前一輪 Agent 的結論、摘要或推測。
4. 不得把「合理推測」、「歷史上常見」、「看起來像」、「應該是」當作工程事實。
5. 任何結論若沒有 Current Evidence，只能標示為 HYPOTHESIS / UNVERIFIED。

要把一個問題從 Hypothesis 升級為 Verified Root Cause，至少必須取得一項或多項可直接驗證的 Current Evidence，例如：
- 實際查看 DUT RTL / source code，並定位到具體 module / instance / signal / logic path。
- 實際查看並量測 waveform / FSDB / fsdbreport，確認 timing、state、data、handshake、interrupt、DMA、register 或 protocol 行為。
- 實際分析 sim.log / assertion / scoreboard / coverage / transaction evidence。
- 實際讀取 register value / programming sequence / initialization result。
- 實際對照 PHY specification / Programming Guide / Register definition / VIP manual / VIP source / class reference。
- 實際重跑 testcase 並得到可重現結果。

CLAUDE.md、Memory、歷史 finding、歷史 bug、Agent summary 只能用來：
- 提供 search direction
- 提高某 hypothesis 的 priority
- 提醒可能的 known issue
- 建議下一個 evidence acquisition action

它們不能直接：
- 證明 current root cause
- 直接觸發 DUT RTL 高風險修改
- 取代 waveform / source / log evidence
- 取代 regression / re-audit
- 直接宣告 PASS / CLOSED / SIGNOFF-READY

Root Cause Confidence 必須由 Current Evidence 決定，而不是由文字紀錄的可信度決定。

若 Source 與 CLAUDE.md / Memory 衝突：
Current RTL / Current Waveform / Current Log / Current Register Evidence 優先。
CLAUDE.md / Memory 必須標示為 STALE / CONFLICTED / NEEDS_UPDATE。


## 鐵則 77：Workflow 啟動前必須宣告 Execution Mode

每一次啟動 workflow，在任何分析、工具執行、server access、build 或 simulation 之前，
第一個使用者可見的狀態訊息必須明確宣告本次 Execution Mode。

### LOCAL_ANALYSIS
必須明確說：
「這個是純本地讀檔分析（不碰伺服器、不跑 VCS）。」

此模式允許：
- 讀取本地 RTL / UVM / scripts / command.txt / documents
- 靜態 source analysis
- 本地文件 extraction / index
- 本地 Git metadata 檢查（不得 network fetch/pull/push）
- 建立 hypothesis / findings / fix proposal

此模式禁止：
- SSH / remote server access
- Git pull/fetch/push 等 network operation
- VCS compile / simulation
- LSF submit / bkill
- 遠端 waveform generation
- 將「未實際跑 simulation」描述成 simulation evidence

### REMOTE_EXECUTION
必須明確說：
「這個需要連伺服器/跑模擬。」

並在執行前列出預計會使用的外部動作，例如：
- server / SSH
- Git pull/fetch/push
- build
- VCS
- FSDB / waveform
- LSF regression

### MIXED
若 workflow 同時需要本地分析與遠端執行，不得混成單一模糊狀態。
必須切成明確 phase：
Phase A = LOCAL_ANALYSIS
Phase B = REMOTE_EXECUTION

每次 phase transition 都必須再次宣告 mode。

### Truth Rule
LOCAL_ANALYSIS 的 finding 不得被誤標成 runtime/simulation verified。
REMOTE_EXECUTION 才能產生 build/simulation/LSF/waveform runtime evidence。
任何 mode 不清楚時，workflow 必須停在 PRE-FLIGHT，不得自行假設已連 server 或已跑 VCS。


## 鐵則 78：Waveform Dump Scope / Level 必須由 User 確認

任何需要啟動 waveform dump 的 simulation，在修改 dump 設定或執行 VCS 前，
Harness 必須明確詢問 User 並確認：

- Dump Scope：哪個 hierarchy / module / instance / interface？
- Dump Level / Depth：需要幾層或何種 depth？

不得未經確認就預設 Full SoC / Full Depth。

若 User 不確定，Harness 應先依 Current Evidence / failure cone 提出「最小足夠 waveform」建議，
並說明為何選擇該 scope/level；若證據不足，再逐步擴大。

LOCAL_ANALYSIS 只能提出 dump scope/level 建議；
只有 REMOTE_EXECUTION 實際產生並量測 waveform 後，才能稱為 waveform evidence。


## 鐵則 79：Simulation 預設禁止 FSDB Dump，VIP Trace/Report 可獨立啟用

所有一般 simulation 與 regression 的預設模式：

- FSDB / waveform dump = OFF
- VIP trace/report = 可依需要啟用
- sim.log / UVM report / assertion / scoreboard evidence = 正常保留

不得因為啟動 simulation 就自動打開 FSDB。

問題分析應優先使用低成本 evidence：
sim.log -> UVM/assertion -> scoreboard/transaction -> VIP trace/report -> targeted logging -> FSDB。

只有當 signal-level waveform evidence 確實需要時，才可升級為 FSDB debug mode；
此時必須先執行 waveform-dump-scope-planner，詢問 User 確認 dump scope 與 level/depth。

LSF regression 預設所有 jobs 都不得 dump FSDB。
若只有特定 failing job 需要 waveform，應只針對該 testcase/job 建立 waveform-debug rerun，
不得未經明確批准把 FSDB 全域打開。

VIP trace/report 可在 FSDB 關閉時獨立啟用，但必須先確認目前 VIP/project 真正支援的設定方式，
不得自行猜測 VIP option。VIP trace/report 不等同於 signal-level waveform evidence。


## 鐵則 80：FAILED Simulation 必須採 First-Failure Waveform Rerun

一般 simulation 第一次執行預設 FSDB OFF。

若 simulation FAILED：
1. 先分析第一次 run 的 sim.log / UVM / assertion / scoreboard / VIP trace evidence。
2. 確認需要 signal-level evidence 後，啟動 dedicated debug rerun。
3. debug rerun 必須經 waveform-dump-scope-planner 確認 dump scope 與 level/depth。
4. debug rerun 應在第一個與目標 failure 相關的 failure / error / fatal / missing / mismatch 時間點停止。
5. 不得無意義地把整個 testcase 全部跑完。

可作為 first-failure stop 的事件包含：
- UVM_ERROR
- UVM_FATAL
- explicit FAIL
- assertion failure
- scoreboard mismatch
- transaction mismatch
- expected item missing
- response missing / failure timeout
- protocol checker failure
- project-defined terminal error signature

Benign warning / allowlisted message 不可誤觸發 early stop。

必要時允許在 first failure time 後保留極小 POST_FAIL_MARGIN，
用來捕捉 failure 前後的 handshake / state / transaction context。

目標：
Minimum Rerun Runtime
+
Minimum Waveform Scope
+
Minimum Waveform Depth
+
Sufficient Root-Cause Evidence。


## 鐵則 81：Remote Control 只能作為 Human Control Transport，不得繞過 Harness Governance

Claude Web/App Remote Control 是 Human Control Plane transport。
不得繞過 Execution Mode Gate、Evidence Truth Gate、Human Approval Gate、Git/Exact SHA Gate、
Waveform Scope/Level User Gate、LSF Exact-Job Safety、Batch Closure 或 Final Deep Audit。

所有 workflow state 以 Blackboard / current runtime evidence 為準，Web chat transcript 不是 system of record。
Linux credentials / SSH private keys 不得傳到 Web/App 或寫入 Verification Memory。


## 鐵則 82：Protocol Builder 必須使用該 Protocol 的 Current Evidence，不得跨協定套用推測

建立 PCIe / Ethernet / MIPI CSI / MIPI DSI / CAN-FD / AMBA4 / eMMC / SD / eDP / UCIe / USB
Verification Environment 時，必須讀取該 DUT 的 current RTL/source、相關 Spec/PHY/Programming/Register 文件、
VIP manual/examples/source/class reference。

USB environment/database 可以作為 common UVM architecture pattern 的參考，
但 USB protocol-specific topology、signal、sequence、register、checker、timing 或 VIP configuration
不得被當成 PCIe/Ethernet/MIPI/... 的真實依據。

所有 protocol-specific environment generation 必須先通過 Evidence Truth Gate 與 Independent Synthesis。


## 鐵則 83：USB UVM Reference Base 只能重用 Generic Architecture，不得跨協定繼承 Protocol Truth

USB UVM Environment 可以作為 AI Agent Harness L5 的 Reference Base / Golden Reference Pattern。

允許重用：
- UVM layering / directory/package architecture
- config_db pattern
- virtual sequencer / sequence library
- scenario registry / dependency barrier
- scoreboard framework
- DMA scoreboard framework
- performance calculator framework
- coverage collector framework
- build/run/regression interface
- LSF / failure replay / Git evidence patterns

禁止跨協定直接重用：
- USB-specific signal
- LFPS / TS1 / TS2 / USB LTSSM
- USB endpoint / transfer-type semantics
- USB register assumptions
- USB VIP API/class/config assumptions
- USB timing / packet semantics / checker semantics

建立 PCIe / Ethernet / MIPI / CAN-FD / AMBA4 / eMMC / SD / eDP / UCIe 等環境時，
所有 protocol-specific implementation 必須重新以 Target DUT + Target Spec + Target VIP Current Evidence 產生。

USB Reference Base 只能當作 Architecture Template，不能當成 Target Protocol Truth。


## 鐵則 84：新增規格/介面必須走 Plugin Onboarding，不得直接硬編碼進 Harness Core

任何新的標準、interface、PHY、internal bus 或 proprietary protocol，
必須透過 Protocol Plugin Contract 加入。

必須具備：
- Current DUT / Spec / Register / PHY / VIP evidence
- protocol/plugin manifest
- role/topology/boundary definition
- builder skill
- checker/scoreboard semantics
- coverage/assertion plan
- smoke tests
- compatibility gate
- compile/smoke/self-test evidence

不得因名稱相似就沿用既有 protocol-specific assumptions。
未通過 compatibility/self-test 的 plugin 不得標示 production-ready。


## 鐵則 85：System-Level Environment 必須由 User Requirement 選擇已驗證 Subsystem Environment 後再組合

建立 SoC/System-Level verification environment 時：
1. 先理解 User 的 SoC verification goal / use-case。
2. 從 Subsystem Environment Registry 選出真正需要的已完成環境。
3. 優先 reuse BASELINE_READY / VERIFIED subsystem environments。
4. 不得因為 registry 裡有某 subsystem 就全部自動加入。
5. 必須先做 compatibility analysis，再產生 SoC integration layer。
6. Subsystem-local environment/scoreboard/coverage 應保持原本邊界，System-Level 只新增跨 subsystem integration。
7. 每個 reused subsystem 必須保存 environment path / release / SHA / interface / dependency provenance。
8. 若 selected subsystem environment stale/incompatible，必須明確回報並重新驗證，不可默默重建或假設相容。

SoC composition 的核心是「選擇 + 組合 + 系統級驗證」，不是把所有 subsystem 重新生成一次。


## 鐵則 86：建立 Verification Environment 前必須先決定 SUBSYSTEM_MODE 或 SYSTEM_LEVEL_MODE

任何 CREATE ENVIRONMENT workflow 在產生 UVM code 或 SoC composition 前，必須明確選定：

SUBSYSTEM_MODE
= 產生/建立單一或特定 subsystem verification environment。

SYSTEM_LEVEL_MODE
= 依 User Requirement 選擇並 reuse 已完成 subsystem environments，再組成 System-Level / Full-SoC environment。

不得把兩種 flow 混成不明確狀態。

SYSTEM_LEVEL_MODE 缺少必要 subsystem 時：
必須明確回報 -> 切到 SUBSYSTEM_MODE 補建 -> compile/smoke/self-repair -> register BASELINE_READY ->
回到 SYSTEM_LEVEL_MODE -> compatibility analysis -> SoC composition。

已完成且相容的 subsystem environment 不得無理由重新生成。


## 鐵則 87：Builder Available 不等於 Production Qualified

任何 protocol/interface 只有真正經 current DUT + current Spec + current VIP/native UVC evidence、compile、smoke、protocol bring-up、traffic/checker/scoreboard 與 qualification regression 後，才可標示 PRODUCTION_QUALIFIED。


## 鐵則 88：New Interface / New Spec 必須可學習、可生成、可 Qualification

未知 interface/spec 必須經 Interface Discovery、Evidence Synthesis、Plugin/Native-UVC Generation、Compatibility Gate 與 Qualification；成功後才可加入 registry 供未來 reuse。


## 鐵則 89：Qualification Claim 必須可追溯

所有 qualification status 必須保存 DUT identity、spec revision、VIP/tool version、Git/release identity、test evidence 與結果；沒有 evidence 不得宣稱 PASS。


## 鐵則 90：System-Level 優先使用 Qualified Subsystem

System-Level composition 應優先選擇已驗證/已 qualification 的 subsystem environment；不足者必須明確降級或回到 SUBSYSTEM_MODE 補建與 qualification。


## 鐵則 91：所有內建 Protocol 必須有 Protocol-Specific Builder 與 Qualification Suite

PCIe、USB、Ethernet、MIPI CSI-2、MIPI DSI、AMBA4 Multi-Master × Multi-Slave、eDP、eMMC、SD/SDIO、UCIe 必須各自保存 discovery、smoke、coverage 與 qualification requirements，不得只靠 generic template 宣稱完成。


## 鐵則 92：New Interface 必須能在有 VIP 與無 VIP 兩種情境建立

有 VIP 時建立 evidence-backed VIP adapter；沒有 VIP 時可生成 Native UVC，但都必須 qualification。


## 鐵則 93：New Specification Revision 必須做 Spec Diff 與 Impact Analysis

不得把舊 Builder 未經確認直接套用新 revision；受影響的 transaction/driver/monitor/sequence/checker/RAL/coverage/assertion/test 必須更新並 re-qualify。


## 鐵則 94：Protocol-Specific Truth 不得跨 Protocol 污染

USB reference 只能 reuse generic UVM engineering patterns；PCIe/Ethernet/MIPI/AMBA/eDP/eMMC/SD/SDIO/UCIe 的 protocol truth 必須來自各自 current evidence。


## 鐵則 95：Production Qualification 必須由 Registry 與 Evidence 決定

任何文件、海報、CLAUDE.md、memory 或 agent output 都不得覆蓋 qualification registry 的 evidence requirement。


## 鐵則 96：Universal Protocol Platform 必須支援 Subsystem 到 Full SoC Reuse

Qualified subsystem environment 必須可註冊、版本化、相容性檢查並由 SYSTEM_LEVEL_MODE 選擇組成 Full-SoC；缺少者回到 SUBSYSTEM_MODE 補建。


## 鐵則 97：Builder 必須真正輸出 UVM Source

必須能輸出 env/config/vseq/scoreboard/coverage/tests/tb_top/filelist/manifest，不得只描述流程。


## 鐵則 98：VIP Binding 必須來自 Current VIP Evidence

production compile 前，VIP package/class/config/API/interface 名稱必須由實際 VIP evidence 驗證。


## 鐵則 99：沒有 VIP 必須支援 Native UVC

New Interface 若無合適 VIP，必須可由 semantic model 生成 native UVC 並 qualification。


## 鐵則 100：Generated Env 必須 Compile/Smoke Self-Repair

產生 source 後必須走 compile/fix/recompile/smoke/fix/rerun，直到 pass 或明確 blocker。


## 鐵則 101：Protocol Semantic Model 是 Protocol-Specific Code Generation Truth

跨 protocol reference 只能重用 generic architecture；protocol semantics 必須來自 target current evidence。


## 鐵則 102：System-Level 只 reuse 可追溯 Subsystem

每個 subsystem 必須有 manifest/release/SHA/qualification status。


## 鐵則 103：Generate Capable 不等於 Production Qualified

平台可真正產生 UVM source，但 production-qualified 仍需 real DUT/VIP/tool compile/simulation/regression evidence。


## 鐵則 104：真實 Environment Generation 必須先 Extract DUT Interface

不得在未讀 current RTL ports/parameters 的情況下直接產生 protocol binding。


## 鐵則 105：真實 VIP Integration 必須先 Learn VIP API

package/class/config/analysis_port 等必須從 current VIP install/manual/example/source/class reference 驗證。


## 鐵則 106：Semantic Model 必須可追溯到 Evidence

每個 role/topology/boundary/config/transaction/checker assumption 必須能指回 RTL/Spec/VIP/Register/PHY evidence。


## 鐵則 107：Protocol Generator 必須有 Protocol-Specific Smoke

PCIe/USB/Ethernet/MIPI/AMBA/eDP/eMMC/SD-SDIO/UCIe 不得共用一個 generic smoke 宣稱完成。


## 鐵則 108：Compile Closure 不得用 Placeholder API 宣稱 PASS

placeholder VIP names 僅供 skeleton/example；production compile 前必須完成真實 binding。


## 鐵則 109：New Interface 必須支援 VIP Adapter 與 Native UVC 兩條實作路徑

有 VIP 走 adapter；無 VIP 走 native UVC；兩者都必須 qualification。


## 鐵則 110：System-Level 只可組合有 Manifest 與身份的 Subsystem Env

至少要有 environment manifest、release/SHA、qualification status 與 compatibility evidence。


## 鐵則 111：所有內建 Protocol 必須共用 Real Code Generation Engine

PCIe/Ethernet/MIPI/AMBA/eDP/eMMC/SD-SDIO/UCIe/USB 都必須能輸出實際 UVM source。


## 鐵則 112：New Interface 必須支援 VIP Adapter 與 Native UVC

有 VIP 走實際 API binding；無 VIP 生成完整 Native UVC。


## 鐵則 113：New Spec Revision 必須 Diff + Regenerate + Requalify

受影響的 semantic model、driver/monitor/sequence/checker/coverage/test 必須更新。


## 鐵則 114：AMBA4 MM×MS 不得被全域序列化

必須保留真正 parallel masters/slaves、ordering、outstanding、backpressure 行為。


## 鐵則 115：Protocol-specific Smoke 不得用 Generic Smoke 取代

每個 protocol 都要自己的 bring-up/traffic/checker gate。


## 鐵則 116：System-Level 只 reuse 可追溯 Subsystem Env

必須有 environment manifest、release/SHA、qualification/evidence identity。


## 鐵則 117：DV Expert Suggestion ≠ Fact

專家建議必須先視為 Hypothesis，經 current evidence 驗證。


## 鐵則 118：Expert Feedback 必須可追溯

保留 feedback ID、scope、reason、evidence、decision、impact、closure。


## 鐵則 119：Knowledge Promotion 必須隔離層級

Project workaround 不得直接污染 Protocol/Platform knowledge。


## 鐵則 120：Simulation 預設 FSDB OFF

正常 simulation 不 dump FSDB，可 enable VIP trace/report。


## 鐵則 121：Failure 才做 Targeted Waveform Rerun

需要 waveform 時先詢問 user scope 與 level，停在第一個 meaningful failure 附近。


## 鐵則 122：Workflow 必須宣告 Execution Mode

明確區分純本地讀檔與連 server/VCS。


## 鐵則 123：Memory/CLAUDE.md 不得取代 Evidence

RTL/waveform 問題必須實際查看 source/量測 waveform。


## 鐵則 124：Feedback 修改後必須 Requalify

compile/smoke/regression/coverage closure 後再交專家 re-review。

## 鐵則 125：Command Catalog 重構必須先分析再搬移

整理 project 內所有 `command.txt` 時，必須先完成 inventory、內容分析、verification level/item 分類、dry-run move plan、reference scan 與 duplicate disposition；不得只依舊目錄名稱直接搬移。刪除舊目錄前必須證明沒有有效 command/artifact/reference，否則標記 RETAIN_REVIEW。所有 move 後必須重做 reference validation 與 pytest/catalog validation。


## 鐵則 126：先 vPlan，後 Testcase

所有 testcase 生成前必須先建立 current-spec-based vPlan。


## 鐵則 127：Testcase 必須 Trace 到 vPlan Requirement

每個 testcase 必須引用一個或多個 requirement ID。


## 鐵則 128：Spec Coverage 目標為 100% Requirement Accounting

100% = VERIFIED + approved WAIVED + validated NOT_APPLICABLE。


## 鐵則 129：DUT Unsupported Waiver 必須有 Current Design Spec Evidence

只有 design spec 明確說明 DUT 不支援才可 WAIVED。


## 鐵則 130：UNKNOWN Gap 不得自動 Waive

推測、不確定或只因 RTL 沒找到都不能直接 waiver。


## 鐵則 131：Spec Revision 必須更新 vPlan 並 Requalify

新 spec revision 必須做 diff/impact/regeneration/requalification。


## 鐵則 132：vPlan 建立前必須先做 Intake Readiness

必須先確認 Subsystem/System-Level scope 與必要 evidence，資料不足時只回報 gap，不得猜測後直接產 final vPlan。


## 鐵則 133：System-Level vPlan 必須由使用者選定的 Subsystem 組合推導

不得用 generic Full-SoC 模板取代實際選定 subsystem composition。


## 鐵則 134：vPlan 問題必須逐步詢問

一次只問目前 readiness gap 所需的下一批關鍵資料，已提供的資訊不得重問。


## 鐵則 135：Spec Feature 必須建立 Feature Mapping

每個規格功能要連到 requirement、subsystem ownership/participation、test/checker/assertion/coverage 與 waiver/evidence。


## 鐵則 136：vPlan/Env 前必須做 DUT Architecture Discovery

會影響 topology、role、clock/reset、address/data path 的架構事實必須先由 current evidence 探索。


## 鐵則 137：Regression Failure 不得先假設是 DUT Bug

必須先分類 DUT、架構模型、VIP binding、環境 topology、checker/reference、test configuration 等可能來源。


## 鐵則 138：DUT Architecture 必須 Regression Calibration

compile/smoke/regression/waveform 與 architecture model 不一致時，必須校正模型並做 impact/rerun。


## 鐵則 139：Architecture UNKNOWN 必須保持 UNKNOWN

沒有 current evidence 的連接、role、dependency 不得用推測補成事實。


## 鐵則 140：Architecture Calibration 必須回饋 vPlan 與 Env

架構模型改變時必須重新檢查受影響 requirement、testcase、checker、coverage 與 system scenario。


## 鐵則 141：Observability 必須在 Architecture Calibration 後分析

Scoreboard/Checker/Assertion placement 必須根據校正後 architecture、vPlan 與 regression evidence。


## 鐵則 142：Scoreboard/Checker/Assertion 必須分工

End-to-end compare 用 scoreboard；semantic rule 用 checker；local/temporal invariant 用 assertion。


## 鐵則 143：新增機制前必須 Inventory

不得重複建立已有 scoreboard/checker/assertion，除非有不同診斷目的。


## 鐵則 144：Assertion 不得建立在推測行為上

沒有 current RTL/spec/waveform evidence 的 temporal property 不得宣稱為 DUT invariant。


## 鐵則 145：Observability Gap 必須 Regression Closure

加入機制後必須 compile/smoke/regression 驗證其診斷與 coverage 效果。


## 鐵則 146：Failure Attribution 必須以 First Bad Event 為核心

Final scoreboard/assertion error 只是 symptom；必須追到最早 expected/observed divergence。


## 鐵則 147：DUT Bug 與 TB Bug 必須雙邊查證

Sequence/driver/interface/DUT/monitor/checker/scoreboard boundary 必須依 evidence 檢查。


## 鐵則 148：Waveform Root Cause 必須建立 Causal Chain

從 symptom 往前追 protocol state、transaction、signal、clock/reset/config prerequisite，不能只列相關 signal。


## 鐵則 149：Corner Case 不得暴力窮舉

必須用 architecture/state/concurrency/reset/error/history/coverage risk 做 P0-P3 排序。


## 鐵則 150：Coverage Hit 不等於 Verification Proof

Requirement 必須有有效 checker/scoreboard/assertion 或其他 evidence 才能形成可信 closure。


## 鐵則 151：Debug 經驗必須轉成可重用 Knowledge

只有 evidence-backed 且 expert-approved 的 root cause/corner pattern 才能進 experience DB。


## 鐵則 152：Historical Knowledge 必須通過 Applicability Gate

Protocol/version/topology/feature 前提不匹配時不得套用舊經驗。


## 鐵則 153：Verification Mechanism Planning 必須在 Test Generation 前

DUT Architecture Discovery 後，先規劃 Monitor/Predictor/Scoreboard/Checker/Assertion/Coverage，再產生 testcase/sequence/scenario。


## 鐵則 154：Testcase 必須有可判定結果的 Mechanism

除非使用其它經批准 verification method，testcase 必須對應有效 checker/scoreboard/assertion/reference/coverage evidence。


## 鐵則 155：Mechanism Planning 先行，但 Implementation 可迭代

Regression 發現 observability gap 時可補強 mechanism，但不能先大量產 test 再事後才決定如何判定正確性。


## 鐵則 156：Test Generation 必須通過 Mechanism Readiness Gate

planned testcase 產生前，必須已有 vPlan requirement、architecture mapping 與可判定結果的 verification mechanism；沒有 mechanism 不得放行。


## 鐵則 157：Testcase 必須引用存在的 Mechanism ID

不得讓 testcase 指向不存在或尚未規劃的 scoreboard/checker/assertion/reference/coverage mechanism。


## 鐵則 158：Requirement Traceability 必須通過 Consistency Gate

每個 in-scope requirement 必須有 architecture mapping，並且至少有有效 testcase/mechanism path；orphan requirement/test/mechanism 不得進 closure。


## 鐵則 159：Coverage/Mechanism/Test Reference 不得懸空

Testcase 指向不存在的 requirement、mechanism 或 coverage ID 必須直接 FAIL。


## 鐵則 160：Traceability 不等於 Closure

Requirement 即使已有 Test/Mechanism/Coverage trace，也必須有 execution evidence 才能標 VERIFIED。


## 鐵則 161：Coverage Hit 不得直接給 Credit

Coverage bin hit 若沒有 checker/scoreboard/assertion 或 approved evidence，不得算 verification closure。


## 鐵則 162：High-Confidence Root Cause 必須檢查 Counter-Evidence

Root cause 要升到 HIGH/VERIFIED 必須記錄 first bad event、causal chain、supporting evidence 與 counter-evidence review。


## 鐵則 163：Closed Loop Promotion 必須通過全部前置 Gate

Intake/vPlan/Architecture/Mechanism/Test/Execution Evidence/Coverage Quality 任一未 READY，該 scope 不得 promotion。


## 鐵則 164：Failure 修正後必須 Rerun 才能 Promotion

有 failure 時，必須完成 RCA、fix/calibration 並取得 rerun evidence；不能修完就直接宣告 closure。


## 鐵則 165：Expert Feedback 與 Experience Loop 必須有結案狀態

Promotion 前需完成 expert feedback review，且 experience capture 必須 CAPTURED 或合理 NOT_APPLICABLE。


## 鐵則 166：System-Level Scenario 必須真正跨 Subsystem

System-Level composition 不得只是把多個 subsystem env 放在一起；每個 system scenario 必須引用至少兩個已選 subsystem。


## 鐵則 167：Remote Control 是 Supervisory Layer 不是第三種 Env Mode

Remote Control 只能監督/控制 Subsystem 或 System-Level flow，不得被建模為平行 environment mode。


## 鐵則 168：Experience Knowledge 必須有 Evidence + Expert Approval + Applicability

Debug/feedback 經驗只有在 evidence 完整、expert-approved 且 applicability constraints 明確時才能進 Experience DB。


## 鐵則 169：command.txt 舊目錄刪除必須通過 Lifecycle Gate

所有 command 完成分類/搬移，且 reference scan clean + safe_to_delete=true 才能刪除舊目錄。


## 鐵則 170：Promotion Chain 必須可稽核且順序一致

每個 READY/PROMOTION stage 必須有 evidence record，且 stage 不得逆序、重複或跳過 mandatory gate。


## 鐵則 171：System-Level Requirement 必須跨 Subsystem Traceable

每個 system-level requirement 必須至少由一個真正跨 subsystem scenario、mechanism 與 coverage path 覆蓋。


## 鐵則 172：Remote Control 的 Mutating Action 必須留下 Audit Evidence

REDIRECT/APPROVE/REJECT/STOP/TAKEOVER 必須記錄 actor、target stage、reason 與 evidence snapshot。


## 鐵則 173：Historical Experience 套用前必須做 Runtime Applicability Check

即使 knowledge 已 expert-approved，也必須確認 protocol/version/role/topology 等 applicability constraints 與目前 project 相符。


## 鐵則 174：Signoff Evidence 必須 Fresh 且有 Provenance

Evidence 必須綁定 current revision、source、timestamp、content hash；舊 revision evidence 未經核准不得用於 signoff。


## 鐵則 175：Qualified Release 必須可 Reproduce

RTL/TB/VIP/tool/config/testlist/seed/evidence bundle 必須被 pin/hashed，Production promotion 還需 promotion-chain hash。


## 鐵則 176：Gate State 必須符合 Dependency

任何 READY/PROMOTABLE stage 不得在必要 upstream gate 尚未通過時被標記成功。


## 鐵則 177：System-Level Composition 必須 Pin 每個 Subsystem Release

System-Level 必須固定 subsystem release SHA、manifest hash、qualification evidence hash 與 composition hash。


## 鐵則 178：Remote Action 必須防 Replay

每個 remote action 需唯一 nonce；重複 nonce 必須視為 replay 並拒絕。


## 鐵則 179：Cross-Run Evidence 必須 Context Consistent

比較多次 regression/重跑 evidence 時，RTL/TB/VIP/config/testlist context 必須一致，否則不得當成同一驗證結論。


## 鐵則 180：Waiver 必須可失效並重新驗證

Waiver 必須有 revision/expiry/trigger-change 管理；revision 改變、期限到期或條件改變時不得沿用舊 waiver。


## 鐵則 181：Coverage Regression Drift 必須阻止 Signoff

已取得的 verification coverage credit 若無核准卻明顯下降，必須視為 regression 並阻止 promotion。


## 鐵則 182：Fix Effectiveness 必須同時驗證 Reproducer 與 Broader Regression

修正 root cause 後不只 targeted case 要 PASS，也要確認 broader regression 沒引入新 failure。


## 鐵則 183：System-Level Subsystem Change 必須觸發 Impacted Scenario Rerun

任一 subsystem release 改變時，所有參與該 subsystem 的 system-level scenario 必須重新執行。


## 鐵則 184：Promotion 必須可 Rollback

已 promotion 的 scope 若出現 stale evidence、critical failure、coverage regression、invalid waiver 或 subsystem release change，必須撤銷或重新驗證。


## 鐵則 185：New Protocol Onboarding 必須完整建立 Verification Intelligence

新 interface/spec 必須具備 spec/dut/vip/state/transaction/error-recovery/mechanism/vPlan/test/coverage/qualification 模型與 evidence 才能進 qualification。


## 鐵則 186：Verification Intent 必須 Requirement→Mechanism→Test→Coverage 完整

任何 testcase 缺 requirement/mechanism/coverage 連結，或任何 requirement 無 test intent，均不得放行。


## 鐵則 187：LSF 每個 Job 必須有獨立 Monitor Agent 與 Evidence Capture

發現 UVM_ERROR/FATAL 後，kill 前必須先保存必要 evidence，kill action 必須有原因。


## 鐵則 188：Remote Control 必須遵守合法 State Transition

STOPPED/PAUSED/RUNNING/TAKEOVER 之間的 action 必須符合 state machine，禁止非法 resume/redirect 等操作。


## 鐵則 189：command.txt Migration 必須保持內容完整性

搬移後 source/destination hash 必須一致，除非有 approved transform。


## 鐵則 190：Rollback 後不得仍標 PROMOTED

一旦 rollback_applied，promotion state 必須撤銷並標記 revalidation required。


## 鐵則 191：Test Result 必須完整 Provenance

每個 PASS/FAIL 必須綁定 testcase/run/RTL/TB/VIP/tool/seed/config/log/evidence bundle，不可有無來源結果。


## 鐵則 192：Flaky Test 不得靠無限制 Retry 掩蓋

Flaky test 必須分類、owner、quarantine policy；quarantined test 不得取得 signoff credit。


## 鐵則 193：Coverage Credit 必須可撤銷

Checker/assertion disabled、stale evidence、failed rerun、invalid waiver、quarantined test 等情況必須撤回已取得 credit。


## 鐵則 194：Protocol Profile 必須版本化

Protocol profile 必須有 profile version/spec revision/hash/qualification evidence，更新版必須記錄 supersession change。


## 鐵則 195：System-Level Dependency Graph 不得有 Cycle

Subsystem dependency 必須是可解析圖；cycle 必須在 composition 前阻擋。


## 鐵則 196：Release Promotion 必須有 Attestation

最終 release 必須綁定 release hash、promotion chain hash、evidence bundle hash 與 attestation signature。


## 鐵則 197：Spec/RTL Change 必須重新做 Verification Change Impact

Spec 變更需重分析 vPlan；RTL interface/architecture 變更需重做 architecture discovery、mechanism revalidation 並重跑受影響 tests。


## 鐵則 198：Architecture Calibration Delta 必須更新 Environment 並 Rerun

Architecture rediscovery 發現 delta 時，不得只更新文件；必須完成 impact analysis、affected artifacts update 與 rerun evidence。


## 鐵則 199：USB UVM Reference Base 必須 Pin Revision 並做 Compatibility Analysis

Reference environment 只能當 evidence/reference base；reuse 前必須固定 revision/hash 並分析 role/interface/config/sequence/checker 相容性。


## 鐵則 200：Protocol Support 狀態必須由 Qualification Evidence 支撐

不得僅因 generator/profile 存在就宣稱 REGRESSION/PRODUCTION qualified；需 manifest/profile/spec/qualification evidence hash。


## 鐵則 201：UNKNOWN Failure 必須阻擋 Promotion

Failure attribution 若仍 UNKNOWN，必須列出 missing evidence、next evidence actions、owner 與 blocking scope，直到取得足夠 evidence。


## 鐵則 202：Reset/Clock/CDC 必須納入 Mandatory Corner Qualification

Verification plan 必須顯式涵蓋 reset、clock 與 CDC；power-aware DUT 還必須包含 power-state/transition corner。


## 鐵則 203：Checker/Reference Model 必須對 DUT 邏輯保持獨立性

不得直接複製 DUT algorithm 當 expected model；checker disabled 時不得保留 signoff credit。


## 鐵則 204：Coverage Hole 必須驅動 Root-Cause 與 Test Regeneration

Coverage hole 若非合法 waiver，必須分類原因；缺 test/constraint/stimulus 時要生成新 testcase 並 rerun。


## 鐵則 205：VIP/API Version Drift 必須重新 Qualification

VIP version/API/source/manual 改變時必須做 API diff、必要 adapter update 與 requalification evidence。


## 鐵則 206：Recurring Failure Signature 必須關聯與升級

相同 failure signature 不得重複開新問題而不關聯；已修問題再次出現必須升級 recurrence。


## 鐵則 207：Block/Branch Topology 必須依 DUT/VIP Port Count 自動對齊

必須生成 block、branch_a*、branch_fw、branch_b*；port 數量改變時 topology 必須同步更新。


## 鐵則 208：APB 必須 Serialize；USB/PCIe/AXI 必須允許 Independent-Port Parallel

禁止跨 port global lock；parallel protocol 必須使用 independent port queues。


## 鐵則 209：Per-Port Scoreboard/Checker/Performance/Coverage 必須完整

每個 port 都必須具有獨立 verification mechanism，且涵蓋 required protocol/speed/transfer combinations。


## 鐵則 210：One-Click Pipeline 順序不得改變

固定 push→build→verify→run(WAVE=1)→fsdbreport analysis，任一步失敗必須停止 promotion。


## 鐵則 211：Runtime Default 必須 WAVE=1、Coverage=OFF、FSDB time0→sim end

TIMEOUT 可控；除非使用者明確 override，預設不得改變。


## 鐵則 212：Reset/Clock/Power Sequence 必須符合 Ordering Contract

Reset deassert、clock stable、power/isolation/retention 事件必須符合明確 ordering rule。


## 鐵則 213：branch_fw 必須 Interrupt-Driven 且具 Ack Path

Firmware branch 不得以 polling 為主要觸發；interrupt map 與 acknowledge path 必須存在。


## 鐵則 214：Independent Port Queue 必須有 Forward-Progress/Starvation Bound

每個 port 必須有 max wait bound 與 forward-progress evidence，避免 hidden starvation。


## 鐵則 215：Scoreboard Expected Data 必須有獨立 Provenance

Expected data 不得由 DUT output 回灌；reference/predictor source 必須被 pin/hash。


## 鐵則 216：Coverage Credit 必須連結 Active Check 或 Valid Waiver

Checker/scoreboard/assertion 全部 inactive 時不得保留 credit，除非 waiver 合法。


## 鐵則 217：System-Level Shared Resource 必須有 Contention Policy 與 Tests

DDR/IRQ/DMA/interconnect 等共享資源出現在 scenario 時，必須驗證 arbitration/contention。


## 鐵則 218：Pipeline Stage Artifact Handoff 必須可追蹤

每個 stage 的 input 必須來自前一 stage 的 output，不得跳接或使用不存在 artifact。


## 鐵則 219：Reset/Clock/Power Sequence Coverage 必須 Closure

必要 sequencing scenario 必須 hit 或具有有效 waiver。


## 鐵則 220：Interrupt Storm 與 Ack Latency 必須驗證

高 interrupt rate 下不得 lost interrupt，且需符合 ack latency bound。


## 鐵則 221：Multi-Port Parallel Flow 必須驗證 Fairness/QoS

需要 service-share 與 QoS proof。


## 鐵則 222：Scoreboard 必須檢查 Transaction Liveness

Missing/duplicate/late transaction 必須阻止 signoff。


## 鐵則 223：Active Failure 必須撤銷相關 Coverage Credit

linked failure 未 closure 時不得保留 credit。


## 鐵則 224：System-Level 必須驗證 Deadlock/Livelock 與 Forward Progress

需 assertion 與 stress evidence。


## 鐵則 225：One-Click Pipeline 必須保持 Artifact Hash Continuity

每 stage input hash 必須等於前 stage output hash。


## 鐵則 226：所有 Hard Gate 必須有 Executable Tool 與 Pytest Coverage

Manifest/Workflow 宣告的 hard gate 不得只存在於文件；必須可執行且至少被 pytest/meta-test 覆蓋。


## 鐵則 227：Assertion 必須防 Vacuity

Enabled assertion 必須有 antecedent attempts，禁止 vacuous pass 或無理由 X/Z masking。


## 鐵則 228：Negative/Error Injection 必須有完整 Error-Class Coverage

Required error classes 必須有對應 stimulus 與 checker/assertion，不得只測 positive path。


## 鐵則 229：Random Regression 必須可用 Seed 重現

每個 randomized run 必須記錄 seed；failure 必須產生 reproducer command。


## 鐵則 230：Protocol Corner Cases 必須有 Evidence-backed Matrix

Required corner cases 必須逐項 covered 並帶 evidence，否則不得 signoff。


## 鐵則 231：vPlan Requirement 必須具有可驗證語意

每個 requirement 必須含 spec ref、feature、expected behavior、verification method、coverage goal；ambiguity 必須解析。


## 鐵則 232：Testcase/Sequence Naming 禁止抽象命名

名稱必須描述 verification intent。


## 鐵則 233：READY/PARTIAL/BLOCKED 必須由 Readiness Score 一致推導

不得主觀宣告 READY。


## 鐵則 234：Evidence Source 必須依優先序探索後才 Ask User

高優先 evidence 未探索前不得直接詢問使用者。


## 鐵則 235：修改 VIP/DUT 分支前必須先查對應 Reference

Branch-B 查 VIP；Branch-A/branch_fw 查 DUT references。


## 鐵則 236：Hard-Gate Canonical Naming 必須支援 Legacy Alias

Manifest/workflow/registry/tool 的歷史命名差異必須用明確 alias map 解析，不能誤判 orphan。


## 鐵則 237：Built-in Protocol Family 必須都有 Qualification Path

PCIe/Ethernet/MIPI CSI-2/MIPI DSI/AMBA4/eDP/eMMC/SD-SDIO/UCIe/USB 必須有 qualification evidence。


## 鐵則 238：Pytest Collection 必須健康

collect-only 不得 timeout/import mismatch，tests* 必須 namespace 隔離。


## 鐵則 239：System-Level/Remote/LSF Control Plane 必須完整覆蓋

System/Remote/LSF 主要 hard gates 不得缺失。


## 鐵則 240：command.txt Cleanup 前必須 Reference Scan Clean

仍有外部 reference 時不得刪除舊目錄。


## 鐵則 241：Cross-Protocol Scenario 必須描述真正 Interaction Point

多 protocol system scenario 必須標示 interaction point，並有 requirement/mechanism/coverage/evidence trace。


## 鐵則 242：Coverage Credit 必須同時符合 Check/Waiver/Failure 一致性

有 active failure 時不得保留 credit；waiver 與 active check 不得矛盾共存。


## 鐵則 243：RCA Confidence 必須與 Evidence Sufficiency 對應

HIGH/VERIFIED 必須具 counter-evidence；VERIFIED 還需 fix-effectiveness evidence；LOW/MEDIUM 不得 promotion。


## 鐵則 244：Regression Result 必須唯一且不可衝突

同 testcase/run_id 不得出現互相矛盾的 PASS/FAIL 或不同 evidence hash。


## 鐵則 245：System-Level Cross-Domain Scenario 必須驗證 Resource/IRQ/Reset/Power 聯動

涉及 shared resource、interrupt、reset、power 時要有 contention/latency/recovery check 與 evidence。


## 鐵則 246：Hard Gate 必須有明確 Input/Output Contract

每個 gate 必須綁定 input schema、required fields、allowed/emitted statuses，禁止隱性 contract 漂移。


## 鐵則 247：Requirement 到 RCA 必須保持 End-to-End Trace

Requirement→Mechanism→Test→Coverage→Result 必須完整；FAIL result 必須繼續 trace 到 RCA。


## 鐵則 248：Protocol Profile 必須與 Generator Version 綁定

Profile/spec/generator/hash/qualification evidence 必須成套；generator 版本漂移要重新 qualification。


## 鐵則 249：System-Level Scenario 必須 Pin Subsystem Release 與 Evidence

Scenario release snapshot 必須與實際 subsystem release SHA 一致，並帶 evidence bundle hash。


## 鐵則 250：Signoff Snapshot 必須 Immutable

Release/promotion/evidence/manifest/attestation 必須共同形成 snapshot hash；signoff 後 mutation 必須阻止。


## 鐵則 251：Built-in Protocol 必須有 Test/Coverage/Result Evidence

內建 protocol family 不只要有 profile/generator，也必須有 testcase_ids、coverage_ids 與 result evidence。


## 鐵則 252：每個 Hard Gate 必須有 Positive 與 Negative Test

只測 FAIL 或只測 PASS 都不足以視為 gate 已被驗證。


## 鐵則 253：Control Plane 必須做 Bidirectional 測試

System-Level/Remote/LSF/command lifecycle 的 accept/reject path 都必須有測試。


## 鐵則 254：Signoff Snapshot 必須 Cross-Check Trace/Coverage/Result/RCA/Evidence

Snapshot 所引用的 trace/coverage/result/RCA/evidence hash 必須與當前 closure state 完全一致。


## 鐵則 255：Qualification State 必須與 Test/Coverage/Evidence 數據一致

PRODUCTION_QUALIFIED 必須 100% coverage 且有 passing tests/evidence；REGRESSION/SMOKE 也必須滿足各自最低條件。


## 鐵則 256：每個 Hard Gate 必須有可追蹤 Validation Evidence

Gate coverage ledger 必須記錄正/負向 test IDs、evidence hashes 與最後驗證 revision。


## 鐵則 257：Workflow / Registry 不得存在 Orphan Gate

任何 workflow gate/validator/audit 都必須存在 tool 並登錄 registry；gate_id 不得重複。


## 鐵則 258：Protocol Qualification 必須按 Ladder 升級

SMOKE→REGRESSION→PRODUCTION 必須逐級留下 evidence，不得跳級宣告。


## 鐵則 259：Workflow Schema 必須有 Canonical Catalog

保留的 schema 必須明確 catalog；刪除 schema 必須先證明無 reference 與 migration 完成。


## 鐵則 260：Simulation PASSED 後必須做 command.txt ↔ sim.log Semantic Validation

Simulator/UVM PASS 只是必要條件；必須由 Simulation Semantic Validation Agent 將 command.txt 的每個必要驗證意圖對照 sim.log evidence。缺少、矛盾或不可觀測時禁止 regression credit/signoff。
## 鐵則 261：Simulation PASS 後必須驗證 command.txt Semantic Intent 與 sim.log Evidence

Simulation/UVM PASSED 只代表模擬流程沒有被既有 fatal/error 判死；必須解析 command.txt 的驗證意圖並逐項證明 sim.log 存在相符 evidence。MISSING、CONTRADICTED 或 UNOBSERVABLE 都不得給 regression credit/signoff。

## 鐵則 262：Semantic TRUE_PASS 必須具有 command.txt 與 sim.log 雙向 Provenance

每個 semantic expectation 必須可追溯到 command.txt source line，MATCH evidence 必須標示 sim.log provenance；duplicate expectation ID、模糊 substring false-positive、缺 provenance 都不得給 signoff credit。


## 鐵則 263：Hard Gate 必須通過 CLI Runtime Contract 與 Agent/Skill Binding Audit

Hard gate 不只要存在與 compile，必須有可執行 CLI contract；workflow 引用的 Agent/Skill 必須存在且 Skill 具完整 frontmatter。弱直接測試覆蓋的 gate 必須由 runtime contract regression 補強。


## 鐵則 264：Simulation Result 必須做 False PASS / False FAIL Arbitration

Simulator PASS/FAIL 必須與 semantic/checker/fatal/infrastructure evidence 聯合判斷，禁止單一 status 決定 DUT 結論。


## 鐵則 265：Semantic TRUE_PASS 必須達到最低 Evidence Strength

generic log 不足以證明重要功能；優先採 scoreboard/checker/assertion/protocol transaction evidence。


## 鐵則 266：DUT/TB/VIP/TOOL Root Cause Attribution 必須有高可信 Causal Evidence

歸因需 first bad event、causal chain、supporting/counter evidence；低 confidence 不得 promotion。


## 鐵則 267：Regression Replay 必須保持 Seed/Config/Build/Artifact/Command 等價

重現驗證若 inputs/hash 漂移，不得宣稱 failure 已重現或修復。


## 鐵則 268：System-Level Cross-Domain Scenario 必須有完整 Evidence Bundle

Shared Resource/Interrupt/Reset/Power 涉及的 domain 必須各自有 evidence、release snapshot hash 與 bundle hash。


## 鐵則 269：Final Verification Verdict 必須跨 Simulation/Semantic/Checker/Failure State 一致

Final PASS 必須 simulation PASS、semantic TRUE_PASS、checker PASS、無 active failure 且 signoff credit allowed。


## 鐵則 270：Checker Evidence 必須與同一 Semantic Expectation Trace 一致

Checker/scoreboard/assertion expectation ID 必須對應相同 command/testcase/vPlan semantic expectation。


## 鐵則 271：RCA Fix Closure 必須由等價 Replay 證明

RCA attribution、reproducer、fix commit、pre/post result 與 rerun evidence 必須完整且 replay equivalent。


## 鐵則 272：Coverage 與 Signoff Verdict 必須一致

Signoff 需要 TRUE_PASS、無 active failure、100% credit 或 approved waiver。


## 鐵則 273：System-Level PASS 不得遮蔽 Subsystem FAIL

除非 subsystem isolated 且有 approved waiver，否則 system PASS 不得掩蓋 subsystem failure。


## 鐵則 274：Verification Mechanism 必須用 Negative Control 證明會抓到錯誤

Test/checker/scoreboard 不能只證明正常 case PASS；必須注入可控錯誤並證明會 FAIL，避免 vacuous PASS。


## 鐵則 275：Assertion Signoff Credit 必須 Non-Vacuous 且 Reachable

Assertion antecedent 必須真正到達、attempt count > 0，並由 negative control 證明 assertion 有效。


## 鐵則 276：Scoreboard Reference Model 必須具 Independent Oracle

Reference model 不得直接複製 DUT implementation 或共用同一演算法來源造成 common-mode defect。


## 鐵則 277：Coverage Hole 必須 Closed Loop 回 Test Generation

非 waived vPlan/coverage hole 必須建立 testcase、owner 與 trace，直到 covered 或 approved waiver。


## 鐵則 278：Random Corner-Case Claim 必須有 Seed/Config Diversity Evidence

聲稱 random/corner-case verification 時必須符合最低 unique seed/config 並有 corner-case bin evidence。


## 鐵則 279：預設 WAVE=0，Simulation 結束後必做 command.txt ↔ sim.log Semantic Postcheck

不得以 simulator/UVM PASSED 單獨判定 TRUE_PASS。必須完整檢查 sim.log 是否符合 command.txt 驗證意圖；有問題必須記錄第一個有意義的錯誤/分歧 simulation 時間點。


## 鐵則 280：需要深入波形 Debug 時只做 Focused WAVE=1

只有 log/semantic 分析判定需要 waveform 時才重跑 WAVE=1。FSDB_START=0；FSDB_STOP=第一錯誤時間+200us；到達 stop 必須停止 simulation 並 kill/terminate job，再以 fsdbreport/waveform workflow 分析。


## 鐵則 281：所有 Workflow 結束後必須先修完全部問題，再做第二次完整詳細 Workflow

第一輪 workflow 的所有問題、缺失、矛盾與建議必須全部修正。修正後必須再次啟動完整 workflow 詳細分析；若仍有遺漏就再次全部修正並重跑，直到第二次分析 clean。


## 鐵則 282：只有 Clean Second Pass 才允許 push → build → verify → run

任何 workflow 尚未結束、第一輪問題尚未全部修完、第二輪詳細分析尚未 clean，都禁止進入 push/build/verify/run promotion。


## 鐵則 283：Simulation 未結束時 4 分鐘後或收到背景完成通知時必須再次確認

若 simulation 尚未結束，不得提前進入 semantic closure。必須在 **4 分鐘後**再次確認，或在收到 background/job completion notification 時**立即再次確認**，兩者以先發生者為準。確認 simulation 已結束後，立即啟動 command.txt ↔ sim.log semantic workflow；若有問題則記錄第一錯誤/分歧 simulation 時間點，進入 RCA；需要 fsdbreport/waveform 深入 debug 時，使用 WAVE=1、FSDB_START=0、FSDB_STOP=錯誤時間+200us，停止 simulation、kill/terminate job，並重新啟動 workflow。


## 鐵則 284：Compile/Elaboration 必須 Single Owner，禁止平行 testcase 重複 make compile

Regression 中多個 usbrun.sh 不得各自觸發完整 make compile/usbc.elab。Compile/elab 必須由單一 build owner 完成，之後所有 testcase 共用經 build fingerprint 驗證的 simv。


## 鐵則 285：STOP_AFTER_SIMV 必須防止 Build Target Fall-Through

若 make/compile target 可能在 simv 建好後繼續進入 simulation，build owner 必須設定 STOP_AFTER_SIMV=1 或等效 hard stop。未設定時禁止啟動 parallel runs。


## 鐵則 286：禁止多個 usbc.elab 同時寫同一 output/csrc、output/simv.daidir、output/simv

任何共用 VCS build artifact 只能有單一 writer。若真的需要 per-test compile，必須使用完全隔離且帶 build/test identity 的 output path；共享路徑平行 elaboration 一律禁止。


## 鐵則 287：Failure 必須先分類 MISCLASSIFIED / KNOWN / REAL_ISSUE

任何 simulation/debug 問題先經 issue_triage。MISCLASSIFIED 與 KNOWN 不得直接進入深度 RCA，除非出現新的矛盾證據；REAL_ISSUE 才啟動 deeper multi-agent analysis。


## 鐵則 288：REAL_ISSUE 深度 RCA 必須使用完整 Evidence Set

除 sim.log、trace、RTL、testbench、command.txt 外，必須加入 scoreboard report、PHY model、Standard spec、VIP examples、VIP source code、VIP/user documents；需要時加入 FSDB/fsdbreport。


## 鐵則 289：修改前必須先完成 Fix + Risk Review

Root cause 必須為 HIGH/VERIFIED。修改前需產生 fix plan、risk assessment、affected scope、regression plan、rollback plan；高風險修改需額外 review。


## 鐵則 290：真正問題修改與驗證後必須寫入 dut-request.md

dut-request.md 必須記錄 issue classification、root cause、evidence、fix summary、risk summary、verification result、change hash 與後續 regression/rollback 資訊。
