################################################################
開啟多Agnet  再次確認 DV Agent Harness L5 系統，具備如下能力:

#1. 把驗證知識變成可執行的資產

#2. 跨 run 的時間維度

#3. Harness 自身的可靠性

#4. 組織面的三件事 : 
責任歸屬 -
agent 開的 PR 若造成 escape，責任在誰？建議明訂：agent 是工具，PR 的 approver 承擔與人工 PR 相同的責任。這件事不先講清楚，沒人敢按 approve，L5 會卡在 L3。
信任的漸進 -
從最無風險的任務開始累積紀錄：log triage、報告生成、coverage 摘要。這些錯了成本很低。等分類準確率的數據出來，再往 stimulus 修改移動。
知識不對稱 -
harness 跑得越好，新人越少有機會親手 debug 一個 fail。建議刻意保留一部分 fail 不自動處理，作為訓練用途 —— 這對你 DV team 的長期能力比短期效率更重要。

#5. 資產處理表
資產	抽取成	主要餵給	重抽觸發
DUT RTL	hierarchy.json（scope tree）、port/param 表	bind path、VIP 數量	RTL commit
PHY model	phy_boundary.json：PHY?controller 介面型別、serial/parallel 分界	bind location 決策	PHY 版本更新
top testbench	既有 bind 清單、clock/reset 來源、既有 VIP 實例	T1 已定案事實	每次 commit
whole chip script	run_profile.json：compile 選項、define、plusarg、UVM_TESTNAME 慣例	agent 的執行動詞	手動
reference command.txt	同上，且為唯一權威	執行方式	手動
whole chip database	不抽取，只查詢（ucli scope -tree、waveform API）	連通性驗證	—
DUT register file	RAL model + regmap.json	scoreboard 的 address decode、init sequence	register file 更新
Global register file	sys_regmap.json：clock/reset/mux/pinmux 控制位	模式決定位，見下	同上
DUT controller doc	intent.md：狀態機、模式、合法 drop/反壓條件	scoreboard 的順序性與豁免條件	手動
IP programming guide	init_seq.yaml：暫存器寫入順序與等待條件	directed test、connectivity check	手動
IP user guide / digital+analog doc	constraints.md：timing、電氣限制、不可測項	豁免清單	手動
VIP document	vip_ref/<protocol>.md（distill 過）	config 欄位語意、內建 check 清單	VIP 版本更新
VIP source	不進 context，只做符號索引（class/method 名稱與檔案行號）	需要時 targeted read	VIP 版本更新
VIP example	pattern/<protocol>/：可執行的最小骨架	環境生成的模板	VIP 版本更新

#6. 衝突時的權威順序
1. elaboration / 實際模擬結果
2. reference command.txt
3. DUT RTL
4. register file（DUT → Global）
5. top testbench 既有 bind
6. controller doc / programming guide
7. IP user guide
8. VIP example
9. VIP document

#7. context 預算規則
永遠不進 context：VIP source 全文、PDF 原檔、whole chip database、完整 regression log
常駐：hierarchy.json 摘要層、phy_boundary.json、run_profile.json、CLAUDE.md 索引
按需載入：vip_ref/、intent.md、regmap.json 的單筆查詢
全部走前面談的 MCP 查詢介面，不讓 agent 自由讀檔

#8. 讓環境自我描述
原則：agent 不該靠 LLM 記憶回答 VIP 或 DUT 的事實，也不該每次重新 parse RTL。中間要有一層自動生成的 manifest。

#9. 三個層次的事實來源：

VIP 層

svt_*_configuration 的實際欄位值：跑一個 zero-time 的 dump test，在 end_of_elaboration_phase 把 config 物件 sprint() 或轉 JSON 輸出。這比讀 user guide 可靠，因為它反映的是這個環境實際套用的值，不是文件上的預設值
VIP 版本、release note、支援的 feature matrix：從 $DESIGNWARE_HOME 目錄與 version 檔抽
User guide PDF：一次性離線 distill 成 reference 檔，不要放進 runtime context

DUT 層

port / parameter：slang 或 verible-verilog-syntax --export_json
register map：RAL 或 IP-XACT 轉 JSON，不要讓 agent 讀 Excel 原檔
address map、clock/reset 拓樸：從既有的 SoC spec pipeline 出

Env 層

uvm_top.print_topology() 加 +UVM_CONFIG_DB_TRACE：一次 smoke run 就能拿到完整 component hierarchy 與所有 config_db 的 set/get 配對。這是最被低估的自我描述手段，agent 問「這個 agent 是 active 還是 passive」不該用猜的
testlist、vPlan、coverage model 對應關係

這些統一生成成 env.manifest.json，由腳本產出、可 diff、進 git。你既有的 JSON IR pipeline 已經是這個形狀，可以直接擴充而不是另起爐灶。

#10. 查詢介面用 MCP，不用讀檔

manifest 有了之後，不要讓 agent 自由 grep。包成內部 MCP server，暴露固定動詞：

get_vip_config(protocol, instance)
get_dut_port(module, pattern)
get_register(name)
get_topology(path)
query_regression(filter)

好處有三：查詢可稽核、結果 schema 固定、權限可控（唯讀工具就是唯讀）。而且 context 只裝回應，不裝整份檔案。

CLAUDE.md 只放索引與規則（有哪些 protocol、manifest 在哪、哪些路徑唯讀），細節放 skills 與 reference，需要時才載入。多協定環境建議每個 protocol 一份 CLAUDE.md。

#11. 、問人的協定

L5 的預設是不即時問。三層處置：

可自查 → 查，不問
查不到但可安全假設 → 記錄 assumption、標註在報告、繼續跑。判準：這個假設錯了，最壞後果是浪費一次 regression
不可假設 → 停下，寫入 question queue，escalate

#12. 三個設計要點：

給選項，不要開放式提問。agent 應該先做完功課、提出 2–3 個候選與建議，人只需選一個。這是把回覆成本從五分鐘壓到十秒的關鍵
標 owner 做路由。VIP 問題給你或 Synopsys AE，DUT 問題給 designer，env 問題給 DV owner。不分流就會全部落在一個人身上
批次成 digest，一天一次或跑完 escalate 一次，不要即時 ping

回答用同格式回寫，agent 從該 session resume 繼續。


#13. 答案要沉澱

每個被回答的問題必須寫回 manifest 或 decisions.md，附上日期與依據。沒有這一步，同一個問題下週會再被問一次，L5 就退化成一個很吵的 L3。

#14. 四個指標
自查解決率 — agent 自己找到答案的比例，目標 > 90%
阻塞問題數/週 — 這是人力成本的直接代理
重複提問率 — 大於 0 就代表沉澱機制沒運作
assumption 被推翻率 — 太高表示第 2 類的判準放太寬

要不要我把 env.manifest.json 的 schema 和 question queue 的完整格式寫出來？或者先做那支 zero-time 的 topology / config dump test，那是整套機制裡最快能看到成效的一塊。

尤其是 bind location , 和 VIP 種類和數量所對應的 DUT instance hierarchy path 及 checker , scoreboard 作法分析後的規劃建議和確認

這一塊是整個 harness 最容易「安靜失敗」的地方：bind path 寫錯但 elaboration 過了，monitor 收不到任何 transaction，regression 全綠。所以設計重點不是讓 agent 猜得準，而是讓錯誤無法安靜通過。

#15. 事實抽取：connectivity manifest

agent 規劃前必須先有這四份機器可讀輸入：

來源	取法	得到
DUT instance tree	simv -ucli -do "scope -tree"，或 slang --ast-json	完整 hierarchy path
interface 訊號集	module port list	協定指紋比對用
既有 bind	全 repo grep -n "^\s*bind "	已定案的事實
VIP 實例	uvm_top.print_topology() + +UVM_CONFIG_DB_TRACE	VIP 數量與 virtual interface 綁定

config_db trace 特別重要：它會顯示每個 set 有沒有對應的 get。有 set 無 get 的 vif 就是接錯的直接證據，不必等模擬跑完。

#16. 匹配要分信心層級

要求 agent 對每一列輸出 tier 與證據，不接受無證據的結論：

T1 已定案 — 既有 bind 或 config_db 已指定 path。直接採用，不重新推導
T2 結構匹配 — port 訊號集符合協定指紋（AXI 必須齊 AWVALID/AWREADY/WLAST/BRESP...；CSI-2 必須有 DPHY lane 與 clock lane）。高信心，可自動採用但列入報告
T3 命名啟發 — 只靠 u_usb3_top、i_pcie_x2 這類命名推得。一律需人確認，不可自動採用
T4 無法決定 — 進 question queue

T3 是最常出錯的一層。多實例 IP（4-lane CSI、雙 port USB）、generate block 產生的 path、wrapper 層數不一致，都會讓命名看起來對但 path 錯。


#17. 數量對應的自檢等式

VIP 數量錯配的三個典型來源：

多實例：VIP 數應等於 active interface 數，不是 IP 數
interconnect：一個 AXI fabric 上 passive monitor 數 ≠ master agent 數，路徑組合數才是 scoreboard 的比對維度
role 反轉：DUT 為 initiator 時 VIP 應為 slave/responder。agent 必須從 port direction 判定，不從命名判定

要求 agent 產出這張矩陣，並附上自檢：

DUT instance | interface | direction | role  | VIP type | count | active/passive | bind target | tier

自檢等式：Σ(需驗證 interface) = Σ(VIP instance) + Σ(明列豁免)。左右不等時必須逐條說明缺口原因（例如「此 port tie-off，不驗」），不允許差額無解釋。

#18. bind location 的固定規則

寫進 CLAUDE.md 當硬規則，不讓 agent 自行決定：

bind 到 module 會套用到該 module 的所有 instance — IP level 適用，SoC level 通常不是你要的。SoC 一律用 instance path
所有 bind 陳述集中在獨立的 *_bind.sv，放 tb 目錄。RTL 檔案是唯讀清單成員，agent 不得在 RTL 內插入 bind
clock 與 reset 顯式從 bind 的 port list 傳入，禁止用 hierarchical reference 跨層抓。跨層抓在 gate-level 或換 wrapper 後必然壞掉
路徑中含 generate / for loop 的，必須展開成明確 index，不接受萬用字元

#19. 三道機器閘門（送人審之前）

這是整個流程的核心。agent 的規劃必須先通過這三關，人看到的才是「已驗證的方案」而不是「我的猜測」：

Elaboration 檢查 — vcs -elab_only 或 slang。bind path 不存在會直接報錯，成本最低，先跑
靜態連通性 — zero-time run。每個 bind 點檢查：clock 有 toggle、reset 有 deassert、必要訊號非 X。無活動的 interface 標紅
交易活性 — 一支最短 directed test，確認每個 VIP monitor 至少收到 1 筆 transaction。收到 0 筆的 monitor 就是接錯

#20. checker / scoreboard 的規劃表

要求 agent 把每一條檢查歸入三類，不允許模糊：

Protocol check → 用 VIP 內建，不自己寫。agent 的任務是列出哪些內建 check 被關閉及理由 — 這份清單本身就是 review 重點
Data integrity → scoreboard
System level → 跨 interface path scoreboard、performance、DECERR

每個 scoreboard 必須逐項填滿以下欄位，留空即自動成為 question queue 條目：

比對端點（source port / sink port，含 hierarchy path）
匹配鍵（ID / tag / address / frame number）
順序性（in-order、out-of-order 及容許 window 深度）
轉換規則（width conversion、packetization、byte enable）
合法的 drop / 反壓情況
reset 時的 flush 行為
orphan 與 unmatched 的門檻與判定時機

實務上 scoreboard 假 pass 幾乎都出在「順序性」與「合法 drop」這兩欄沒定義清楚 — 比不到就當沒發生。所以這兩欄建議設為強制人審，不接受 agent 的預設值。

#21 確認的顆粒度與鎖定
人的確認是逐列（per-interface / per-scoreboard），不是整份 approve。整份 approve 在二十個 interface 的規模下等於沒審
確認結果寫回 manifest：confirmed_by、confirmed_date、evidence
已確認列鎖定，agent 不得變更；要改必須提出 diff 並重新確認
RTL 更新後重跑抽取，只有 diff 出來的列需要重新確認。這是讓確認成本不隨時間線性累積的關鍵

呈現形式建議三件套：connectivity matrix（表）、hierarchy 圖（標出 bind 點與 VIP 掛載位置）、question queue。前兩者讓人一眼看出錯配，第三者是唯一需要人動腦的部分。

#22  要採用 D:DV/Task/USB_UVM_Handoff/sim/scripts/Makefile 中的 4 階段 VCS compilation flow 和 partition compilation 機制

#23  要採用 VIP 和 Verdi PA (protocol analyzer) 機制，可以參考 D:DV/Task/USB_UVM_Handoff/sim/scripts/Makefile  

#24  要採用 dump fsdb  機制 (wave.txt)，可以參考 D:DV/Task/USB_UVM_Handoff/sim/scripts/Makefile 

#25  要先確認原來的 DE所使用的 CPUREAD task 是否做 read byte shift 的額外動作 (由其是 address 不 align 的時後)

#26  產生的環境是要給不懂 UVM 的 DE來使用的。DE 只了會用一般 verilog task 來組合 command.tx

#27  CPUREAD, CPUWRITE 要換成task 呼叫 APB Sequence 

#28 從使用者提供 Spec / RTL / command.txt / VIP reference / DE 原始 simulation environment 開始，由 AI Step-by-Step 互動理解 DUT 與驗證需求，

#29 自動建立 vPlan、產生/補強 VIP-based UVM environment、Build、Simulation、Debug、Regression、Coverage，最後完成 Signoff；遇到任何 failure 能自主找 Root Cause、修改、重跑，直到驗證 closure

#30 Protocol Scope "做成 Generic DV Harness，而不是 USB-only"
USB Host
 ├─ USB2 HS/FS
 └─ USB3 Gen1/Gen2

USB Device
 ├─ USB2 HS/FS
 └─ USB3 Gen1/Gen2

PCIe
 └─ Gen2/3/4/5/6

MIPI
 ├─ CSI-2
 └─ DSI

Ethernet

CAN-FD

AMBA4 SoC
 ├─ APB
 ├─ AHB / AHB-Lite
 ├─ AXI3
 ├─ AXI4
 ├─ ACE-Lite
 └─ AXI-Stream
 
#31 DV Agent Harness L5 內部的 AI 架構 + AI 機制，如下這些:
a: Autonomous Inference Engine             
b: Graph Orchestrator                      
c: Multi-Agent Orchestrator                
d: Route & Skill Resolver                  
e: Plan-and-Execute / ReAct Engine         
f: Blackboard / Evidence Engine            
g: 5-Level Memory Engine                   
h: Qualification / Signoff Engine      

#32 執行過程要能顯示目前DV Agent Harness L5 目前所在階段和目前該階段還有哪些待完成項目及距離完成的百分比

#33 執行過程要能顯示目前DV Agent Harness L5 個階段開始要用一個明顯的Logo 顯示同時要顯示所需要的文件，檔案和相關資料清單和完整度百分比。另外要提醒使用者那些相目需要在提供供詳細資料

#34.執行過程要能顯示目前DV Agent Harness L5 個階段結束要用一個明顯的Logo 顯示同時要顯示輸出的檔案和相關資料清單和完整度百分比，並顯示總執行時間 (含各個Agents) 和所耗掉的 token 數量

#35 同時儲存 #33,#34 顯示 reports  

#36 Graph 控制流程、ReAct 持續推理、多 Agent 平行協作、Blackboard 維持單一真相、Evidence 約束 AI 判斷、五層記憶累積工程知識，並透過 Autonomous Inference 驅動 Build→Simulation→Debug→Regression→Signoff 閉環的自主式 DV AI 驗證系統
┌─────────────────────────────────────────────┐
│             DV AGENT HARNESS L5             │
│                                             │
│  ? Autonomous Inference Engine             │
│  ? Graph Orchestrator                      │
│  ? Multi-Agent Orchestrator                │
│  ? Route & Skill Resolver                  │
│  ? Plan-and-Execute / ReAct Engine         │
│  ? Blackboard / Evidence Engine            │
│  ? 5-Level Memory Engine                   │
│  ? Qualification / Signoff Engine          │
│                                             │
│              ↓ Execution Plane ↓            │
│ Spec → vPlan → UVM → Build → Sim → Debug   │
│             → Regression → Signoff          │
└─────────────────────────────────────────────┘

#37 多人同時使用  DV Agetn Harness L5 系統過程中，任何更新都要同步 佈建在 linux server 端: /home/vlan063/AI/Agent

#38 多人同時使用  DV Agetn Harness L5 系統過程中，有缺乏和不足的功能和skill 都要 蒸餾成 DV Agetn Harness L5 的功能和skills; 要具備學習能力同時寫回  linux server 端: /home/vlan063/AI/DB

#39 在整個互動過程中，有缺乏和不足的功能和skill 都要 蒸餾成 DV Agetn Harness L5 的功能和skills; 要具備學習能力
a. 要寫回  linux server 端: /home/vlan063/AI/DB
b. 最後完整的 DV Agetn Harness L5 系統要佈建在 linux server 端: /home/vlan063/AI/Agent

#40 增加多個Agent 同時啟動分別做這些資料和檔案內容的轉換和抽取，這樣方便  VIP based verification 環境查看和分析。
a. VIP document, user guide 
b. VIP source code , reference class 
c. VIP examples , environment, cobfiguration, interface, scoreboard, sequence, sequence_item, test, constraint, coverage, callback
d. DUT document, DUT registers documents (doc, excel)
e. IP document, IP user guide
f. programming guide, programming document
g. DUT RTL files, DUT source code, interrupts, registers
h. IP source code, model
i. Top testbench, running script, file list
j. Reference command.txt
k. standard spec. (inetrface spec): AMBA, USB, PCIE, MIPI-CSI2, MIPI-DSI, eMMC/MMC, SD/SDIO. CDN-FD, Ethernet 

#41 建立背景觀察各個 job 和 simulation log 的狀態的機制。每隔10分鐘自動確認


################################################################
開啟多Agnet  再次確認 DV Agent Harness L5 系統 實作「根據新的外部知識 + 內部 DV Evidence，自動發現自身能力缺口、提出強化方案、設計實驗、Benchmark，再經 Human Gate 決定是否升級到 Production」整合並確實符合如下架構:
External Research / Standards / Vendor Reports
                    +
Internal DV Evidence
Regression / Coverage / Failure History
User Corrections / Agent Performance
                    ↓
        Evidence + Provenance
                    ↓
       Autonomous Inference
                    ↓
      Capability Gap Detection
                    ↓
         research-architect
                    ↓
 KEEP / ENHANCE / ADD / EXPERIMENT / REJECT
                    ↓
      Capability Evolution Candidate
                    ↓
         Controlled Experiment
                    ↓
 VCS / Formal / Coverage / LSF / fsdbreport
                    ↓
        Before/After Benchmark
                    ↓
 PROMOTE / REVISE / HOLD / REJECT
                    ↓
             Human Gate
                    ↓
              Production
                    ↓
 Engineering Memory + Architecture History

################################################################
開啟多Agnet  再次確認 DV Agent Harness L5 系統 實作 「Claude CLI + Obsidian CLI + Git/Markdown Hybrid Engineering Memory」整合並確實符合如下架構:
Claude CLI
    │
    ▼
DV Agent Harness L5
    │
    ├── Analysis Agent
    ├── Debug Agent
    ├── Execution Agent
    ├── Regression Agent
    ├── Signoff Agent
    └── Memory Agent
             │
             ├── Direct File Access
             │
             └── Obsidian CLI
                    │
                    ▼
              DV-Knowledge
              Git Repository
                    │
       Markdown + YAML + Wiki Links
       
#################################################################
開啟多Agnet 再次確認 DV Agent Harness L5 系統 實作 "production-grade execution governance" 並確實符合如下架構:

                    Engineer
                       │
                       ▼
                  Claude CLI
                       │
              ┌────────▼────────┐
              │   L5 Harness    │
              │ Graph/Planner   │
              └────────┬────────┘
                       │
       ┌───────────────┼────────────────┐
       ▼               ▼                ▼
   Knowledge        Governance       Execution
    Layer             Layer            Layer
       │               │                │
 Obsidian CLI       gh / git         just
 Markdown/Git       PR Gate          pueue
 DuckDB              Audit             │
       │               │                ▼
       │               │        Preflight Agent
       │               │          ├─ lmstat
       │               │          ├─ disk
       │               │          ├─ env
       │               │          ├─ queue
       │               │          └─ host
       │               │                │
       │               │                ▼
       │               │          LSF / Slurm
       │               │          bsub / sbatch
       │               │                │
       │               │                ▼
       │               │          VCS / Verdi
       │               │          ZeBu / HAPS
       │               │                │
       └───────────────┼────────────────┘
                       ▼
                 Evidence Layer
          ┌────────────┼────────────┐
          ▼            ▼            ▼
        logs          FSDB       coverage
          │            │            │
          └──────? Distillation ?────┘
                       │
                vip_distill.py
                       │
              verible JSON / parsers
                       │
                       ▼
                    DuckDB
                       │
            ┌──────────┴──────────┐
            ▼                     ▼
      Debug / RCA            Memory Agent
                                  │
                          Obsidian Knowledge
                                  │
                          Git / PR / Audit

