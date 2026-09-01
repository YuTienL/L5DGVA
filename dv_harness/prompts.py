from __future__ import annotations
from .models import Stage

BASE = """
你正在由 DV Agent Harness 驅動 Generic DE + DV Industrial Workflow v15。
全程使用繁體中文。

核心定位：Any Block / Subsystem → Multi-Subsystem → Full SoC。

必須遵守：
- 先 evidence discovery，證據足夠時不要詢問使用者。
- Plugin / Skill / Agent readiness 要分開確認。
- branch_fw 僅為 Interrupt/Event-driven command/control dispatcher，不是 protocol traffic scheduler。
- VIP testing scenarios 在 branch-B。
- 所有 workflow findings 與 recommendations 的 actionable 項目必須一次修完，再完整 re-verify 與 second-pass audit。
- Git 不得破壞 unrelated user changes，不得自動 force push/reset --hard/clean -fd。
- Server build 前確認 exact pushed Git SHA。
- Coverage 預設 OFF。
- Representative verification 使用 WAVE=1、FSDB_START=0、FSDB_STOP=simulation_end。
- 不熟悉工具命令先查手冊/既有 project usage，不可猜。

Interactive Evidence Intake 模式（每個需要判斷「這件事是否已知/是否需要問使用者」的 stage 都套用）：
Harness Search（自己先讀 repo/RTL/spec/log 找證據）與 Ask User（缺口才問）兩條路徑收斂到
Evidence Analysis → Confidence Assessment：
- HIGH confidence → 自動接受，不問使用者。
- MEDIUM confidence → 用其他既有證據 cross-check 後再接受，不直接問使用者。
- LOW/UNKNOWN confidence → 才 Step-by-Step 詢問使用者（一次只問必要的最少問題）。
之後更新 readiness 狀態才進下一步；不得跳過 confidence assessment 直接猜測或直接發問。

若使用者回答「不知道」：不要停止、不要卡住等待。改為自動擴大搜尋既有證據
（Design Spec → RTL parameters → defines → register capability → command.txt →
Reference UVM），交叉比對後重新評估 confidence：
- 交叉比對後達到 HIGH confidence → 採用，並記錄依據來源。
- 仍然不足 → 標記 UNKNOWN，帶著已排除的可能性再次向使用者確認（縮小問題範圍，不要重複問一樣的問題）。
"""

STAGE_INSTRUCTIONS = {
Stage.ENV_CHECK.value: """
執行 Claude CLI / Superpowers / plugin / dv-workflow / required skills / 7 agents / settings readiness。
輸出 READY / PARTIAL / BLOCKED 及 evidence。

Execution Mode Gate：宣告這次是 PURE_LOCAL_READ_ANALYSIS（不碰伺服器/不跑模擬）還是
REMOTE_EXECUTION_REQUIRED；宣告 PURE_LOCAL_READ_ANALYSIS 卻列出 vcs/simulation/compile/
regression/lsf/server/remote/ssh 相關 action 會被判定衝突。

SSH/Remote Transport Connection Intake：若 action 涉及 ssh/remote/server（需要連到 Linux DV
Server 的真實 SSH/網路傳輸），不可直接嘗試連線 —— 先詢問使用者是否要建立 SSH/網路傳輸連線；
確認需要後，向使用者收集以下必要欄位（缺一不可）：
- user account
- password（僅口頭/當下互動連線指令用，絕對不可寫進本 evidence block、不可存進 state/log/
  memory，只能在實際建立連線那一刻由使用者輸入）
- vc machine name（例如 vchost-a、vchost-b）
- ssh machine name（例如 host-a、host-b）
- DV Agent 在 Linux server 上的 working path/目錄

account/vc_machine/ssh_machine/working_path 這四項（不含 password）需寫進 remote_connection
物件；漏任一項或誤把 password 寫進 evidence 都會被 gate 判定 FAIL。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上（PURE_LOCAL_READ_ANALYSIS 且不需要
SSH/網路傳輸時，remote_connection 可省略）：

```dv-harness-evidence:execution_mode_validator
{"execution_mode": "PURE_LOCAL_READ_ANALYSIS", "actions": ["read RTL", "grep spec"]}
```

需要 SSH/網路傳輸時的範例（password 不出現在這裡）：

```dv-harness-evidence:execution_mode_validator
{"execution_mode": "REMOTE_EXECUTION_REQUIRED", "actions": ["ssh to server", "run vcs regression"],
 "remote_connection": {"account": "...", "vc_machine": "vchost-b", "ssh_machine": "host-b",
   "working_path": "/home/.../project"}}
```
""",
Stage.INTAKE.value: """
Step-by-Step Interactive Intake：套用 BASE 的 Interactive Evidence Intake 模式，
完成 project/remote intake。優先從 existing files/config 找 server、shell、source、work path；
只有 confidence LOW/UNKNOWN 且為 execution 必需時，才詢問 minimum required fields。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上：

```dv-harness-evidence:intake_readiness
{"mode": "SUBSYSTEM", "target_name": "...", "protocols": ["..."],
 "required_artifacts": {"protocol_spec": true, "dut_design_spec": true,
   "rtl_top_or_interface_files": true,
   "command_txt": ["<實際存在的 command.txt 路徑>", "..."],
   "vip_reference": ["<實際存在的 VIP 文件/範例/Reference UVM 路徑>", "..."]}}
```
（mode 為 SYSTEM_LEVEL 時改用 selected_subsystems + required_artifacts.system_level_use_cases +
required_artifacts.existing_uvm_env。缺任何必要 artifact 都不算 READY_FOR_VPLAN。
SUBSYSTEM 模式下 required_artifacts.command_txt 與 required_artifacts.vip_reference 皆為必要欄位
——gate 會實際檢查磁碟上是否存在對應檔案，兩者都必須是「真的存在的檔案路徑」陣列，不能只填
true 或隨便寫個不存在的路徑；找不到既有 command.txt/VIP reference 材料時，先擴大搜尋 repo/VIP
安裝目錄，仍然沒有才用 Interactive Evidence Intake 模式向使用者確認。）

DE-local Simulation Environment Intake（選填、不強制）：先確認這個專案在 harness 介入之前，
是否已經有一套 DE 自己在跑的 local simulation environment（compile script、run script、
filelist、environment-setup script）。有的話，逐項記錄「真實存在的檔案路徑」加上「這個檔案是
怎麼被確認存在/可用的」（例如：實際 Read 過內容、實際執行過並看到成功輸出、DE 口頭/文件確認）；
完全沒有這套既有環境（例如全新專案、DE 尚未提供）時，直接附上空物件 `{}`，gate 會視為
not-applicable 直接通過，不會強迫每個專案都要有 DE-local 環境。回覆結尾附上：

```dv-harness-evidence:de_local_sim_env_intake_gate
{"compile_script_path": {"path": "<真實存在的 compile script 路徑>", "evidence": "..."},
 "run_script_path": {"path": "<真實存在的 run script 路徑>", "evidence": "..."},
 "filelist_path": {"path": "<真實存在的 filelist 路徑>", "evidence": "..."},
 "env_setup_script_path": {"path": "<真實存在的 environment-setup script 路徑>", "evidence": "..."}}
```

（沒有既有 DE-local 環境時改附 `{}`——四個欄位必須「全有或全無」：一旦填了任何一個欄位，
其餘三個也都要真實存在且各自附上 evidence，不可以只填一部分就當作已完成。每個 path 都必須是
磁碟上真的存在、且非空的檔案，不能是猜的路徑或空檔案；evidence 欄位必須是非空字串，說明這個
檔案「怎麼被確認存在/可用」，不能留白。）

本 stage 另外還有兩個獨立的 hard gate，也必須各自附上 evidence block，缺一個都會讓整個
stage 卡在 GATE_FAIL（找到真實案例：agent 只附了 intake_readiness/de_local_sim_env_intake_gate
兩個，另外兩個沒附，導致 INTAKE 重試多輪都停在同樣的 GATE_FAIL）：

```dv-harness-evidence:generated_artifact_boundary_gate
{"artifacts": [{"class": "BUILD|REGRESSION|VPLAN|CHECKER|SCOREBOARD|ASSERTION|WAVEFORM|LOGS|SYSTEM_LEVEL|HISTORY", "owner": "HARNESS", "required_from_user": false}]}
```
（盤點本階段實際碰到、屬於「本來就該由 harness 自己產生」的產出物類別（BUILD/REGRESSION/
VPLAN/CHECKER/SCOREBOARD/ASSERTION/WAVEFORM/LOGS/SYSTEM_LEVEL/HISTORY 這幾種）——owner 一定要
是 "HARNESS"、required_from_user 一定要是 false，代表沒有把 harness 該自己產生的東西誤要求
使用者先準備好。這個階段通常還沒有真的產生任何這類產出物，`{"artifacts": []}` 是誠實、合法
的預設值，不需要硬湊內容。）

```dv-harness-evidence:interactive_evidence_intake_gate
{"questions_asked_in_batch": 0, "user_requested_batch_mode": false,
 "evidence_answer_available": true, "asked_user_anyway": false,
 "confidence": "HIGH", "asked_user_for_same_fact": false,
 "ask_user": false, "continue_evidence_search": false,
 "status": "READY"}
```
（如實反映本階段真正發生的互動方式：questions_asked_in_batch 是這輪一次問了幾個問題（一次只
問一個才符合 Step-by-Step 規定，> 1 且沒有 user_requested_batch_mode 會被判 FAIL）；如果證據
其實找得到卻還是先問使用者，asked_user_anyway 要填 true（會被判 FAIL）；confidence 是 HIGH 卻
又去問使用者同一件事，asked_user_for_same_fact 要填 true（會被判 FAIL）；confidence 是
LOW/UNKNOWN 時，ask_user 或 continue_evidence_search 至少要有一個是 true（否則視為晾著不處理，
判 FAIL）；status 必須是 READY/PARTIAL/BLOCKED 三選一，不能留空或填其他值。）
""",
Stage.DISCOVERY.value: """
Five Source Discovery：並行盤點 Spec、RTL Source、command.txt、USB Standard/VIP/Reference UVM、
DE Local Simulation（既有結果，不是重跑）這五個來源，建立 DUT/SoC hierarchy、instances、
ports/interfaces、protocols、clock/reset/IRQ/DMA/shared-resource inventory。

Canonical Flow Step 2「vPlan FIRST」：在深入 RTL/Architecture 之前，先根據 Spec/Requirement
寫出 vPlan v0.1 草稿（Requirement ID + 初步 Verification Target），存進
generated/03_vplan/。後續 Architecture Discovery/Calibration、command.txt Analysis、
Reference UVM Analysis、DE Baseline Reproduction 每個都會回頭精煉這份草稿
（v0.2 → v0.3 → v0.4 → v1.0），最終在 VPLAN stage 定稿/LOCK。不得跳過這一步直接做 RTL 分析。

本 stage 有兩個獨立的 hard gate，也必須各自附上 evidence block，缺一個都會讓整個 stage 卡在
MISSING_EVIDENCE（找到真實案例：DISCOVERY 內容做得很完整，但沒附這兩個 gate 的 evidence，
導致 gate completion 卡在 0%）：

```dv-harness-evidence:evidence_source_priority_gate
{"attempted_sources": ["EXISTING_PROJECT_FILES", "RTL_PARAMETERS_DEFINES", "EXISTING_UVM_VIP_CONFIG",
  "EXISTING_TESTS_SEQUENCES", "DESIGN_DOCS", "VPLAN_TEST_TABLE", "BUILD_REGRESSION_SCRIPTS"],
 "higher_priority_sources_exhausted": true}
```
（attempted_sources 只填本輪實際查過的來源，且必須依這個固定優先順序遞增排列：
EXISTING_PROJECT_FILES → RTL_PARAMETERS_DEFINES → EXISTING_UVM_VIP_CONFIG →
EXISTING_TESTS_SEQUENCES → DESIGN_DOCS → VPLAN_TEST_TABLE → BUILD_REGRESSION_SCRIPTS →
GIT_HISTORY_COMMENTS → ASK_USER，不可跳序、不可倒序；只有真的把前面所有來源都查過還是不確定，
才可以把 ASK_USER 加進來，且 higher_priority_sources_exhausted 一定要填 true。）

```dv-harness-evidence:input_source_contract_gate
{"provided_source_classes": ["SPEC", "COMMAND_TXT", "PRIMARY_PROTOCOL_REFERENCE", "RTL_SOURCE", "DE_LOCAL_SIM"],
 "protocol_input_kind": "PUBLIC_STANDARD_SPEC", "forbidden_user_prerequisites": []}
```
（provided_source_classes 必須是這 5 類的完整集合：SPEC（protocol/DUT 規格）、COMMAND_TXT（既有
command.txt/pattern）、PRIMARY_PROTOCOL_REFERENCE（VIP 文件/範例/Reference UVM）、RTL_SOURCE
（RTL 原始碼）、DE_LOCAL_SIM（既有 DE local simulation 環境）——缺任何一類都會 FAIL；
protocol_input_kind 必須是 PUBLIC_STANDARD_SPEC 或 OFFICIAL_STANDARD_SPEC 其中之一（代表協定輸入
真的是公開/官方標準規格，不是憑空杜撰）；forbidden_user_prerequisites 列出「本來該由 harness 自己
產生、卻被誤要求使用者先準備好」的產出物類別（BUILD/REGRESSION/VPLAN/CHECKER/WAVEFORM/LOGS/
SYSTEM_LEVEL/HISTORY）——正常情況下這裡應該是空陣列 `[]`。）
""",
Stage.COMMAND_PATTERN.value: """
將 command.txt 分為 REUSE/EXTEND/GENERATE，確認 USB Standard/VIP/Reference UVM 綁定。
Reference UVM Analyzer：分析既有 Reference UVM 的三個面向 ——
Architecture（Scoreboard/Checker/Assertion 設計）、Build Flow（Regression/VCS options/LSF flow）、
VIP Usage（Sequence/Config/API usage）——收斂成可重用的 Reusable Pattern。
建立 command→branch-B VIP sequence→checker/coverage→pattern trace。
確保 User-defined Pattern Make API 與 registry 可用。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。凡是被分類為 REUSE/EXTEND 而從舊路徑搬到新路徑（或
新建成 command_inventory 條目）的 command.txt，都必須證明搬移過程中沒有偷偷改動內容——真的有改，
一定要明確標記成「已核准的修改」，不能悄悄改了內容卻還宣稱是原封不動沿用。回覆結尾附上：

```dv-harness-evidence:command_migration_integrity_gate
{"commands": [
  {"command_id": "usb_bulk_transfer_basic", "source_hash": "a1b2c3d4...", "destination_hash": "a1b2c3d4...", "approved_transform": false}
]}
```

（`commands` 不能是空陣列——這個 gate 沒有「not-applicable 就填空」的預設值，只要這個 stage 有處理
過任何 REUSE/EXTEND/GENERATE 的 command.txt，就至少要列一筆；每一筆都要有 `command_id`、
`source_hash`、`destination_hash`，缺任一個 hash 都會被判 FAIL（MISSING_COMMAND_HASH）；當
`source_hash` 與 `destination_hash` 不相同時，必須把 `approved_transform` 設為 true（代表這是有意、
已核准的內容修改），否則會被判 FAIL（COMMAND_CONTENT_CHANGED）——沒有核准標記卻內容不同，等同
「搬移途中內容被悄悄改掉」。）
""",
Stage.DE_BASELINE_REPRODUCTION.value: """
DE Local Simulation → DE Baseline Reproduce：用既有 command.txt/build recipe/RTL 原樣重跑，
證明 harness 重現的結果與 DE 原始結果一致（identity：command/RTL/build/environment hash 全部相同），
達成 BASELINE_LOCKED 才能進入 Architecture Discovery。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上：

```dv-harness-evidence:de_baseline_reproduction_gate
{"de_local_sim_path": "...", "original_command_hash": "...", "rtl_hash": "...",
 "build_recipe_hash": "...", "environment_hash": "...",
 "original_de_result": "PASS", "harness_reproduced_result": "PASS",
 "reproduced_command_hash": "...", "reproduced_rtl_hash": "...", "sim_log_hash": "..."}
```
（reproduced_command_hash/reproduced_rtl_hash 必須與 original_command_hash/rtl_hash 完全相同，
代表重現過程中沒有意外改動 command 或 RTL。）
""",
Stage.ARCH_DISCOVERY.value: """
RTL-First DUT Architecture Discovery：BASELINE_LOCKED 之後，以 RTL 原始碼為準（而非先看文件猜測），
依序完成：Source Inventory → Top/Hierarchy Discovery → Module Connectivity Analysis →
Interface/Protocol Candidate Detection → Clock/Reset Discovery → Parameter/Define Analysis →
Interrupt/DMA/Register Bus Discovery → Data Path/Control Path Discovery → Port/Channel/Lane Discovery
→ 產出 Architecture Model v0.x → Confidence Analysis。

Confidence 分級處理：
- HIGH confidence 項目 → 自動接受。
- MEDIUM confidence 項目 → 用其他 RTL 證據交叉確認，不直接接受。
- LOW/UNKNOWN 項目 → 記錄 next_action，Step-by-Step 詢問使用者，不得自己假設。

architecture evidence database 至少要涵蓋 TOP/HIERARCHY/INTERFACE/CLOCK_RESET/PARAM_DEFINE/PORT_CHANNEL。
本 stage 只到 Architecture Model v0.x + Confidence Analysis 為止，不要求 lock（lock 在下一個 ARCH_CALIBRATION stage）。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上：

```dv-harness-evidence:rtl_first_architecture_discovery_gate
{"rtl_source_available": true, "architecture_document_required": false,
 "auto_discovered_fields": ["TOP","HIERARCHY","INTERFACE","CLOCK_RESET","PARAM_DEFINE","PORT_CHANNEL"],
 "asked_user_before_rtl_analysis": false,
 "unknown_items": [], "architecture_evidence_db_generated": true,
 "architectural_claims": [
   {"kind": "MODULE", "name": "usb_top", "rtl_citation": "rtl/usb_top.v:12"},
   {"kind": "PORT", "name": "phy_clk", "rtl_citation": "rtl/usb_top.v:18-20"}
 ],
 "lock_requested": false, "calibration_complete": false}
```
（`architectural_claims` 為必填、不得為空：每一個 module/port/interface/register_block 主張都要有
`rtl_citation`（"path/to/file:start[-end]"，相對於 project root），gate 會實際比對該檔案該行附近
是否真的出現這個名稱 -- 只是輕量 grep spot-check，不是完整 RTL parse，但杜絕「編出一個看似合理但
RTL 裡查無此名」的假造。）
""",
Stage.ARCH_CALIBRATION.value: """
Architecture Calibration → DUT Architecture LOCK：把 Architecture Model v0.x 與後續發現的新證據
（cross-check RTL、使用者回答的 Step-by-Step 問題）比對，記錄 delta，並確認每個 delta 都有：
impact analysis（受影響的 artifact 有哪些）→ 更新受影響的 artifact → rerun 佐證。
所有已知 delta 都處理完、conflict 都 resolved 之後才能 lock_requested，
lock 之後不得再有 unresolved unknown。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上：

```dv-harness-evidence:architecture_calibration_gate
{"architecture_before": {"...": "..."}, "architecture_after": {"...": "..."},
 "detected_deltas": [], "impact_analysis_completed": true,
 "affected_artifacts_updated": true, "rerun_evidence": true}
```

```dv-harness-evidence:architecture_calibration_conflict_gate
{"conflicts": [], "architecture_locked": true, "unresolved_unknown_count": 0}
```
（沒有 delta/conflict 時，"detected_deltas": [] 與 "conflicts": [] 即可通過。）

VIP API Drift 確認（lock 之前必須確認目前實際用的 VIP 版本跟當初 qualify 過的版本是否一致，
版本漂移不代表可以直接用——沒做過 API diff 分析、有 breaking change 卻沒更新 adapter、或漂移
了卻沒有重新 requalify，都必須在 lock 前處理掉，不能留到後面才發現 sequence/adapter 對不上）：

```dv-harness-evidence:vip_api_drift_gate
{"current_vip_version": "2024.09", "qualified_vip_version": "2024.09",
 "api_diff_analyzed": true, "breaking_api_changes": false, "adapter_updated": true,
 "requalification_evidence": "...", "current_vip_source_or_manual_hash": "..."}
```
（"current_vip_version" 與 "qualified_vip_version" 不同才視為有漂移；兩者相同（如範例）時，
後面 "api_diff_analyzed"／"breaking_api_changes"／"adapter_updated"／"requalification_evidence"
四個欄位不會被檢查，可以照範例值填。有漂移時：先看 "api_diff_analyzed" 是否為 true——沒做過
API diff 分析就標記漂移會直接 FAIL VIP_VERSION_DRIFT_WITHOUT_API_DIFF；"breaking_api_changes"
為 true 卻 "adapter_updated" 不是 true 會 FAIL BREAKING_VIP_CHANGE_WITHOUT_ADAPTER_UPDATE（有
breaking change 就必須先把 adapter/sequence library 更新完才能回報）；"requalification_evidence"
沒填會 FAIL VIP_DRIFT_WITHOUT_REQUALIFICATION（漂移後要有重新 qualify 過的證據，不是只做完
diff 分析就算數）。"current_vip_source_or_manual_hash" 不論有沒有漂移都一定要填——沒有把目前
實際用的 VIP source/manual 釘住一個 hash 或版本識別，會直接 FAIL UNPINNED_CURRENT_VIP_REFERENCE，
避免後面環境用的 VIP 跟這裡回報的版本其實對不上。）
""",
Stage.PROJECT_MODEL.value: """
建立 Generic Project Model、verification boundary、VIP topology/bind、BLOCK/branch-A/branch_fw/branch-B topology、
confidence 與 DV readiness（承接 Architecture Evidence DB）。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上：

```dv-harness-evidence:project_model_topology_completeness_gate
{"verification_boundary": "...", "vip_topology": [{"vip_id": "...", "bound_interface": "..."}],
 "blocks": [{"block_id": "...", "branch": "BLOCK|BRANCH_A_DUT|BRANCH_FW|BRANCH_B_VIP"}],
 "model_confidence": "HIGH|MEDIUM|LOW", "confidence_basis": "...",
 "dv_readiness": "READY|NOT_READY|PARTIAL", "dv_readiness_basis": "...",
 "architecture_evidence_db_ref": "..."}
```
（沒有 VIP 時附 "vip_topology_not_applicable_reason" 取代 vip_topology。）

CLAUDE.md「Environment Generation Mode」：CREATE ENVIRONMENT 之前必須明確選
SUBSYSTEM_MODE（單一 subsystem/協定環境）或 SYSTEM_LEVEL_MODE（組合多個已完成
subsystem 環境成 Full-SoC）。harness 已經在這次呼叫前用
`dv_harness/environment_mode_router.py` 的 `resolve_environment_mode()`
算過一次真實結果（依真實的 requested_subsystems + 真實 subsystem registry），
結果會顯示在上面 Harness Plan 區塊的 "Resolved environment mode" 欄位——
回覆結尾照那個結果附上（`environment_mode_selection_gate` 會拿同一份
requested_subsystems 跟真正的 registry 檔案重新推導一次，兩者不一致會直接
FAIL）：

```dv-harness-evidence:environment_mode_selection
{"environment_mode": "SUBSYSTEM_MODE|SYSTEM_LEVEL_MODE",
 "requested_subsystems": ["usb"], "needs_subsystem_mode_first": false}
```
（`requested_subsystems` 為 2 個以上時必須是 SYSTEM_LEVEL_MODE；若其中有尚未
登記在真實 subsystem registry 裡的項目，`needs_subsystem_mode_first` 必須是
true，且依 CLAUDE.md 規則先透過 SUBSYSTEM_MODE 把它建好、註冊後再回來組
SYSTEM_LEVEL_MODE。）
""",
Stage.PROTOCOL_CAPABILITY.value: """
Protocol Capability Discovery：綜合 Spec + RTL + Register map + command.txt + Reference UVM + VIP
六個來源做交叉分析，產出 Generated DUT Protocol Profile —— 本次 scope 涉及的協定
（USB2/USB3/PCIe/MIPI/AMBA...）實際支援哪些 mode/capability（例如 USB3 Gen1/Gen2、lane count、
host/device），不得只看 Spec 就假設全部 capability 都存在；RTL/Register/VIP 沒有對應證據的
capability 要記錄為 gap，交給後續 vPlan 走 waiver。

本次 scope 的協定若已登記在 `.dv-harness/builder/protocol_builder_registry.json`，必須逐項
回應該協定的 `discover`／`build` checklist（不是自己另外發明檢查項）——打開該檔案，找到
`protocols.<protocol>.discover`／`.build` 兩個陣列，每一項字串依下列規則轉成 key（跟 gate
腳本用的規則完全一樣，才會對得起來）：轉小寫、非英數字元換成底線、頭尾底線去掉。例如
`"Host/Device role"` → `host_device_role`。附上：

```dv-harness-evidence:protocol_builder_registry_conformance_gate
{"profile": {"protocol": "usb",
  "discover_items": [{"key": "host_device_role", "status": "SATISFIED", "evidence": "..."}, ...],
  "build_items": [{"key": "vip_topology", "status": "SATISFIED", "evidence": "..."}, ...]}}
```
每一項 `status` 只能是 `SATISFIED`（附 `evidence`）或 `WAIVED`（附 `waiver_approved: true` +
`waiver_evidence`）；漏掉一項、或 `key` 是編出來的（沒對應到 registry 裡真實存在的字串），
都會直接 FAIL——這是唯一能證明「真的有讀 registry」而不是憑印象隨便填的方式。
本次協定不在 registry 裡（新協定/自訂協定）時改附
`{"profile": {"registry_applicable": false, "registry_not_applicable_reason": "..."}}`。

本 stage 另外還有五個獨立的 hard gate，涵蓋「generator 綁定」「profile skill 是否真的被查閱」
「protocol onboarding 內容完整度」「profile 版本治理」「qualification 狀態與 evidence」五個面向，
也都必須各自附上 evidence block，缺一個都會讓整個 stage 卡在 GATE_FAIL/MISSING_EVIDENCE：

先是 generator 綁定與 profile-skill 綁定這兩個（都用同樣的 `--binding` 檔案格式，外層都是
`{"protocols": [...]}`，但檢查的欄位完全不同，必須分別附兩個 block）：

```dv-harness-evidence:protocol_generator_binding_gate
{"protocols": [{"protocol": "usb", "profile_version": "...", "profile_hash": "...",
  "spec_revision": "...", "generator_version": "...", "generator_hash": "...",
  "qualification_evidence_hash": "..."}]}
```
（每個 protocol 項目都必須同時附上 profile_version/profile_hash/spec_revision/generator_version/
generator_hash/qualification_evidence_hash 六個欄位，缺任何一個都會 FAIL
INCOMPLETE_PROTOCOL_GENERATOR_BINDING；如果同時填了 qualified_generator_version 且它跟
generator_version 不同（代表 generator 版本已經漂移），一定要附上 requalification_evidence_hash，
否則 FAIL GENERATOR_VERSION_DRIFT_WITHOUT_REQUALIFICATION——沒有漂移的話不需要填
qualified_generator_version。）

```dv-harness-evidence:protocol_profile_binding_gate
{"protocols": [{"protocol": "usb", "profile_skills_consulted": ["usb-protocol-profile"]}]}
```
（`protocol` 必須是 `.dv-harness/builder/protocol_builder_registry.json` 的 `protocols` 裡真實
存在的 key，查無此協定會 FAIL UNKNOWN_PROTOCOL；gate 會去讀該協定 registry 條目的
`profile_skill`／`vip_lookup_skill` 兩個欄位，只要其中有值（非 null）就必須出現在
`profile_skills_consulted` 清單裡，代表這個 skill 真的被查閱過，漏掉任何一個都會 FAIL
PROFILE_SKILL_NOT_CONSULTED 並列出 missing 清單；registry 裡這兩個欄位都是 null 的協定，
`profile_skills_consulted` 可以留空陣列。）

接著是 protocol onboarding 內容完整度（`--profile`，注意跟下面 profile 版本治理的 gate雖然都吃
`--profile` 檔案，但欄位完全不同、彼此獨立）：

```dv-harness-evidence:protocol_onboarding_gate
{"protocol_name": "usb", "spec_sources": ["..."], "dut_mapping": "...",
 "vip_strategy": "...", "state_model": "...", "transaction_model": "...",
 "error_recovery_model": "...", "verification_mechanism_plan": "...",
 "vplan_mapping": "...", "test_generation_strategy": "...",
 "coverage_model": "...", "qualification_plan": "...",
 "evidence_refs": ["..."]}
```
（protocol_name/spec_sources/dut_mapping/vip_strategy/state_model/transaction_model/
error_recovery_model/verification_mechanism_plan/vplan_mapping/test_generation_strategy/
coverage_model/qualification_plan 這 12 個欄位都必須有值，缺任何一個都會 FAIL
INCOMPLETE_PROTOCOL_ONBOARDING 並列出 missing 清單；就算 12 個都填了，若沒有另外附上非空的
evidence_refs，仍會 FAIL NO_PROTOCOL_EVIDENCE——代表每一項內容主張都要有可回溯的證據來源，不能
只是文字敘述。）

再來是 profile 版本治理（`--profile`）：

```dv-harness-evidence:protocol_profile_version_gate
{"protocol_name": "usb", "profile_version": "1.2.0", "spec_revision": "...",
 "profile_hash": "...", "qualification_state": "QUALIFIED",
 "qualification_evidence_hash": "..."}
```
（protocol_name/profile_version/spec_revision/profile_hash/qualification_state 五個欄位都必須
有值，缺任何一個都會 FAIL UNVERSIONED_PROTOCOL_PROFILE 並指出缺的是哪個 key；
qualification_state 若填 `"QUALIFIED"`，一定要另外附上 qualification_evidence_hash，否則 FAIL
QUALIFIED_PROFILE_WITHOUT_EVIDENCE_HASH；這份 profile 若是取代舊版本（填了 supersedes），一定要
同時附上 change_summary 說明版本差異，否則 FAIL PROFILE_SUPERSESSION_WITHOUT_CHANGE_SUMMARY——
沒有取代舊版本時，supersedes/change_summary 兩者都可以省略。）

最後是本 stage 匯總每個協定目前 qualification 狀態的整體 evidence（`--status`，注意這裡每個協定
項目的 key 是 `"name"`，跟上面 generator/profile-skill 綁定 block 用的 `"protocol"` 不同，不要
混用）：

```dv-harness-evidence:protocol_qualification_status_gate
{"protocols": [{"name": "usb", "qualification_state": "SMOKE_QUALIFIED",
  "profile_version": "...", "spec_revision": "...",
  "environment_manifest_hash": "...", "qualification_evidence_hash": "...",
  "generation_supported": true, "profile_available": true}]}
```
（`qualification_state` 只要落在 SMOKE_QUALIFIED／REGRESSION_QUALIFIED／PRODUCTION_QUALIFIED
任一個「已 qualified」等級，就必須同時附上 profile_version/spec_revision/
environment_manifest_hash/qualification_evidence_hash 四個欄位，缺任何一個都會 FAIL
QUALIFIED_PROTOCOL_WITHOUT_EVIDENCE；未達 qualified 等級（例如仍在 UNQUALIFIED/IN_PROGRESS）則
不受這四個欄位限制。另外，只要 generation_supported 填 true（代表這個協定目前支援自動生成
環境），就必須同時 profile_available 也是 true，否則 FAIL GENERATION_SUPPORT_WITHOUT_PROFILE——
不能宣稱支援生成、卻沒有真的有可用的 profile。）
""",
Stage.REQUIREMENTS_TRACEABILITY.value: """
Requirement Extraction + Applicability/Waiver：建立 Requirement → vPlan → scenario → command/pattern →
checker/coverage → regression result → signoff evidence trace，列出所有 traceability gaps。
DUT 不支援的 requirement 要走 waiver（需 design_evidence 佐證），不得直接刪除。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上：

```dv-harness-evidence:spec_to_vplan_requirement_quality_gate
{"requirements": [{"req_id": "...", "spec_ref": "...", "feature": "...",
  "expected_behavior": "...", "verification_method": "...", "coverage_goal": "..."}]}
```

```dv-harness-evidence:waiver_scope_consistency_gate
{"waivers": [{"waiver_id": "...", "requirement_ids": ["..."], "subsystem": "...",
  "spec_revision": "...", "design_evidence_hash": "...", "approval_id": "...",
  "scope_hash": "..."}]}
```
（沒有任何 waiver 時，"waivers": [] 即可視為通過 —— 只在真的引用 waiver 卻缺欄位時才會 FAIL。）

Waiver Revision Freshness（waiver 核准當下所依據的 spec_revision/rtl_hash，跟現在的版本不一樣時，
要先確認這個 waiver 有沒有跟著重新驗證過，不能「核准過一次就永久沿用」）：

```dv-harness-evidence:waiver_revision_freshness_gate
{"current": {"spec_revision": "...", "rtl_hash": "..."},
 "waivers": [{"waiver_id": "...", "spec_revision": "...", "rtl_hash": "...",
   "revalidated": true, "revalidation_evidence_hash": "...", "expired": false}]}
```

（這個 gate 讀的是 --state 檔案本身的完整內容——不像 waiver_revalidation_gate 那樣要包一層
sub-key，這裡整個 block 就是檔案內容本身。"current" 是目前真正的 spec_revision/rtl_hash；
"waivers" 陣列裡每一筆的 spec_revision 或 rtl_hash，只要有一個跟 "current" 對不上，就代表這個
waiver 是在舊版本核准的，此時必須同時填 revalidated=true 且 revalidation_evidence_hash 非空，
否則會 FAIL STALE_WAIVER_AFTER_REVISION_CHANGE；expired 為 true 的 waiver，不論版本是否吻合都
會直接 FAIL EXPIRED_WAIVER。沒有任何 waiver 時 "waivers": [] 一樣視為通過。）

Waiver Revalidation（每次改版都要重新確認 waiver 還適不適用，不是寫一次永久有效）：

```dv-harness-evidence:waiver_revalidation_gate
{"waivers": {"waivers": [{"waiver_id": "...", "approved": true, "evidence": "...",
  "revision": "...", "expires_at": "...", "revalidated_for_revision": false,
  "trigger_conditions_changed": false}]},
 "current_revision": "..."}
```
（這個 gate 需要 3 個 CLI 參數，但你只需要在這一個 evidence block 裡填 "waivers"
（waiver 清單本身，注意外層還要包一層 {"waivers": [...]} 才是 --waivers 檔案的內容，
跟 waiver_scope_consistency_gate 的扁平陣列不同）跟 "current_revision"（目前的
spec/RTL revision 字串）兩個欄位——真正的目前時間（--now）由 harness 自己在執行時
帶入，不接受、也不會讀取你在 block 裡寫的任何時間值，避免有人謊報時間閃避
WAIVER_EXPIRED。revision 跟 current_revision 不同、且沒有 revalidated_for_revision
時會 FAIL WAIVER_REVISION_STALE；expires_at 早於目前時間會 FAIL WAIVER_EXPIRED；
trigger_conditions_changed 為 true 會 FAIL WAIVER_REVALIDATION_REQUIRED。）
""",
Stage.SOC_SCENARIO_PLANNER.value: """
若 scope >= subsystem，建立 cross-subsystem/cross-protocol/shared-resource/concurrency/E2E/reset/error/performance scenarios。
不要把各 protocol testcase 相加當成 SoC verification。

Corner-case Library 優先查詢：分類/排風險之前，先用 `dv_harness.memory.CornerCaseLibrary.search`
（或 `python -m dv_harness.memory_cli corner-case-search --protocol ... --category ... --text ...`）
查這個 protocol/category 有沒有已經驗證過的既有 corner case。「高信心命中」的定義是
status=="ACTIVE" 且 protocol/category 完全相符，且該筆記錄的 evidence.runtime_evidence_hash
非空、evidence.semantic_verdict 是 TRUE_PASS 或 TRUE_FAIL——不能只看 confidence 欄位（
`CornerCaseLibrary.add()` 目前對每筆新增都預設 confidence="VALIDATED"，這個欄位本身不能
當作「已經被驗證過」的證明）。符合以上條件才能直接沿用該筆的 risk_tier/分類並呼叫
`mark_reused`，並在自己的回覆中標記 `classification_basis: "REUSED_CCL:<ccl_id>"`；
沒有命中或命中但不符合上述條件時，照下面流程自己分級，並標記
`classification_basis: "DV_JUDGMENT"`，不得因為「查不到」就隨便套一個等級交差。

Protocol Corner-case Intelligence：不要暴力窮舉所有組合，改用風險排序。先依下列 12 類
分別列出候選 corner case：Reset/Power、Concurrency、Ordering、Backpressure、Resource Limit、
CDC/Timing、Error/Fault、Recovery、Cross Feature、Cross Protocol、Traffic Pattern、
State Transition。每個 corner 依 architecture 複雜度、new/changed RTL、CDC/reset、
concurrency、outstanding traffic、backpressure、error recovery、state-space 複雜度、
spec ambiguity、coverage gap、historical bug 評分，分級為 P0(最高風險)/P1/P2/P3(最低)，
只有 P0/P1 一定要有對應測試，選出的 corner 都要回扣到 vPlan requirement/architecture
risk/observability，不得只是分類、不排優先序。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上：

```dv-harness-evidence:corner_risk_rank
{"cases": [{"corner_id": "...", "category": "...", "classification_basis": "DV_JUDGMENT",
  "risk_factors": ["reset", "cdc", "concurrency",
  "error_recovery", "ordering", "backpressure", "resource_limit", "new_rtl",
  "spec_ambiguity", "coverage_gap", "historical_bug"]}]}
```
（risk_factors 只填實際適用的項目；分數越高風險越高，harness 只驗證證據格式，
不會自動判定分數是否合理——corner 選擇的合理性仍需你自己判斷。）

本 stage 另外還有一個獨立的 hard gate 專門檢查 Reset/Power/CDC 這三類 corner 是否真的規劃到位——
這三類在 12 分類裡最容易被「只列出來但沒有真的收斂成可執行測試」，所以另外用
`reset_power_cdc_corner_gate` 逐條檢查每個 corner 有沒有掛上 requirement/mechanism/test，
以及 CDC/Reset 各自的專屬完整性欄位，缺一個都會 FAIL（找到真實案例：agent 只附了
corner_risk_rank 一個，這個沒附，導致 SOC_SCENARIO_PLANNER 重試多輪都停在同樣的
GATE_FAIL/MISSING_EVIDENCE）。回覆結尾另外附上：

```dv-harness-evidence:reset_power_cdc_corner_gate
{"corner_items": [
  {"corner_id": "...", "domain": "RESET", "requirement_ids": ["..."],
   "mechanism_ids": ["..."], "testcase_ids": ["..."],
   "async_or_partial_reset_covered": true},
  {"corner_id": "...", "domain": "CLOCK", "requirement_ids": ["..."],
   "mechanism_ids": ["..."], "testcase_ids": ["..."]},
  {"corner_id": "...", "domain": "CDC", "requirement_ids": ["..."],
   "mechanism_ids": ["..."], "testcase_ids": ["..."],
   "cdc_observation_or_assertion": "..."}
], "power_aware_design": false}
```
（corner_items 裡的 domain 至少要涵蓋 RESET、CLOCK、CDC 三種（大小寫需完全相符），
缺任何一種會被判 MISSING_MANDATORY_CORNER_DOMAINS；每一筆 corner_items 都要非空的
requirement_ids/mechanism_ids/testcase_ids 三個陣列，分別代表這個 corner 回扣到哪個
vPlan requirement、靠哪個驗證機制觀察、由哪個 testcase 實際覆蓋，缺任一項會依序被判
CORNER_WITHOUT_REQUIREMENT/CORNER_WITHOUT_MECHANISM/CORNER_WITHOUT_TEST；domain 是
"CDC" 的項目還要額外填非空的 cdc_observation_or_assertion（說明用什麼 observation 或
assertion 抓 CDC 違規），沒填會被判 CDC_WITHOUT_OBSERVATION_OR_ASSERTION；domain 是
"RESET" 的項目要額外填 truthy 的 async_or_partial_reset_covered（確認 async reset 或
partial reset 情境有被涵蓋），沒填會被判 RESET_CORNER_INCOMPLETE；power_aware_design
如實填這個 DUT 是不是 power-aware 設計——是 true 的話，corner_items 裡至少要有一筆
domain 是 "POWER" 的項目，否則會被判 POWER_AWARE_WITHOUT_POWER_CORNERS，不是
power-aware 設計時填 false 即可，不需要硬湊 POWER corner。）
""",
Stage.INFRASTRUCTURE_AUDIT.value: """
詳細 audit scoreboard、DMA scoreboard、performance calculator、coverage collector 的
by-instance/by-port/by-interface/concurrency/heterogeneous legal combination 能力。

本 stage 的 PASS 由 harness 端 gate 腳本裁定（`environment_readiness_status_gate.py`，會實際讀取
回報的 readiness JSON、自己重新算一次 expected status 再跟回報值比對，不是自由心證填寫）。回覆
結尾附上：

```dv-harness-evidence:environment_readiness_status_gate
{"scores": {"DUT": 95, "ProtocolConfig": 92, "VIP": 90, "BuildFlow": 95,
 "Testbench": 88, "Specification": 90, "vPlan": 85, "Regression": 80, "Coverage": 75},
 "status": "READY"}
```

（`scores` 必須完整包含這 9 個維度：DUT、ProtocolConfig、VIP、BuildFlow、Testbench、Specification、
vPlan、Regression、Coverage——缺任何一個都會被判 FAIL（MISSING_READINESS_DIMENSIONS）；每個維度的
分數必須是 0–100 之間的數字，型別不對或超出範圍會被判 FAIL（INVALID_READINESS_SCORE）；`status`
不是自由填寫，gate 會依固定公式自己算出 expected 值再跟回報的 status 比對，兩者不同就判 FAIL
（READINESS_STATUS_MISMATCH）——公式是：DUT/ProtocolConfig/VIP/BuildFlow 這四個核心維度全部 ≥90，
且九個維度的平均分（overall）≥85，才能填 READY；這四個核心維度只要有任一項 <50，就必須填 BLOCKED；
其餘情況一律填 PARTIAL。回報前務必自己先照這個公式核算 overall 與四個核心維度，不能憑印象或樂觀猜測
直接填 READY/PARTIAL/BLOCKED。）
""",
Stage.VPLAN.value: """
vPlan 是逐步累積出來的草稿，不是一次寫完：
v0.1（Requirement Extraction）→ v0.2（RTL Discovery + Applicability Correction）→
v0.3（command.txt Analysis + Existing Test Mapping）→
v0.4（Reference UVM Analysis + 初步 Verification Mechanism Mapping，
細節設計留給下一個 Verification Architecture stage）→
v1.0（比對 DE Baseline Reproduction 的可行性結果做 Executable feasibility correction）。

本 stage 的工作：整合以上所有版本產出 vPlan v1.0，明確列出 SoC scenarios 與 audit gaps，
向使用者確認 Verification Scope 後才能 LOCK；LOCK 之前不得進入 Verification Architecture/Implement。

實際產出 vPlan .xlsx 時，執行真正的 `dv-harness vplan-export`（見
dv_harness/vplan_writer/writer.py、dv_harness/cli.py 的 `vplan-export`
subcommand）——這是真的、可開啟的 openpyxl workbook 產生器，不是自由格式文件；
它會先對真實的 pattern-dir / dispatcher-file / task-declaration-source 證據跑
3 條 REQUIRED validation rules（每個 pattern name 都有對應檔案、每個 task name
都是真的宣告、每個 pattern 都在 run-time dispatcher 裡），任何一條沒過就整份
refuse 寫檔（2026-09-01，vplan-doc-and-wiring-fix；.claude/agents/
IP_UVM_DV_Gen.md 曾經誤寫「無此 generator，仍為 doc-only」，該說法已過時並已
更正）。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上兩個 evidence block：

```dv-harness-evidence:spec_coverage_audit
{"requirements": [{"req_id": "...", "status": "VERIFIED"}]}
```
（每個 requirement 的 status 只能是 VERIFIED/WAIVED/NOT_APPLICABLE 三選一
（WAIVED 需另外滿足 support_status=UNSUPPORTED_BY_DUT + waiver.approved + waiver.evidence），
不得留白——這是 vPlan 定案時的「100% 已歸類」檢查，跟後面 REQUIREMENT_CLOSURE 的
runtime evidence 檢查是兩個不同層級，不要混淆。）

```dv-harness-evidence:vplan_writer_validation_gate
{"items": [...VPlanItem dicts, same schema `dv-harness vplan-export` consumes...],
 "pattern_dir": "...", "dispatcher_file": "...", "task_declaration_sources": ["..."],
 "constraint_declaration_sources": ["..."]}
```
（這個 gate 直接呼叫真正的 dv_harness.vplan_writer.validate_items()，對磁碟上真實的
pattern-dir/dispatcher-file/task-declaration-source 證據重跑上述 3 條 mandatory
validation rules——不是只檢查這個 JSON 本身格式對不對，2026-09-01,
vplan-doc-and-wiring-fix：這是 STAGE_GATES["VPLAN"] 第二個 gate，補上
spec_coverage_audit 一直沒做到的部分。`constraint_declaration_sources`
是第 4 條 rule 的證據來源，2026-09-01 vplan-4th-rule-implementation 新增，
選填——省略時第 4 條 rule 直接 skip，不會 fail closed。）
""",
Stage.VERIFICATION_ARCHITECTURE.value: """
Verification Architecture + Observability Planning：定義本次 scope 需要哪些
Monitor / Scoreboard / Checker / Assertion / Independent Reference Model，
以及每個都要能被觀察到（observability point），而不是等寫 test 才發現看不到訊號。

Mechanism Readiness Hard Gate：在進入 Test Generation（IMPLEMENT stage）之前，
每個規劃中的 testcase 都必須綁定至少一個已定義的 verification mechanism
（或明確核准的替代驗證方式），不得先寫 test 才回頭補 mechanism。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上：

```dv-harness-evidence:mechanism_readiness_gate
{"vplan_requirement_ids": ["..."], "architecture_nodes": ["..."],
 "verification_mechanisms": [{"mechanism_id": "...", "type": "SCOREBOARD"}],
 "planned_testcases": [{"testcase_id": "...", "mechanism_ids": ["..."]}]}
```
（type 只能是 MONITOR/PREDICTOR/REFERENCE_MODEL/SCOREBOARD/CHECKER/ASSERTION/COVERAGE/OTHER_APPROVED。）

Fabric Topology Completeness Hard Gate（僅適用於 fabric-style multi-master / multi-slave
環境，如 AMBA4 SoC）：每一組 master×slave pair 都必須在 scoreboard matrix 中出現且有明確
status；每個 slave 的位址範圍必須在 address map 中出現，且彼此不重疊、不留未標示的空隙
（保留區間也要明列一筆，不能用沉默的 gap 代表）。非 fabric 拓樸（如 USB/PCIe 點對點）需
明確填 topology_applicable=false 並附理由，不得省略此區塊。

```dv-harness-evidence:fabric_topology_completeness_gate
{"topology_applicable": true,
 "masters": ["M0", "M1"], "slaves": ["S0", "S1"],
 "scoreboard_matrix": [
   {"master_id": "M0", "slave_id": "S0", "status": "IMPLEMENTED"},
   {"master_id": "M0", "slave_id": "S1", "status": "IMPLEMENTED"},
   {"master_id": "M1", "slave_id": "S0", "status": "IMPLEMENTED"},
   {"master_id": "M1", "slave_id": "S1", "status": "IMPLEMENTED"}
 ],
 "address_map": [
   {"owner": "S0", "start_addr": "0x0000_0000", "end_addr": "0x1000_0000"},
   {"owner": "S1", "start_addr": "0x1000_0000", "end_addr": "0x2000_0000"}
 ]}
```
（status 只能是 IMPLEMENTED/WAIVED/NOT_APPLICABLE；WAIVED/NOT_APPLICABLE 需附
waiver_approved+waiver_evidence。非 fabric 環境改附
`{"topology_applicable": false, "topology_not_applicable_reason": "..."}`。）

Protocol Structural Completeness Hard Gate（適用於 PCIe/MIPI DSI/MIPI CSI-2/Ethernet/
CAN-FD/SD-SDIO/eMMC/eDP/UCIe/USB 這 10 個協定）：附上 `"protocol"` 欄位指定協定，gate
會 dispatch 到對應協定的確定性結構完整性檢查（例如 PCIe 的 LTSSM 狀態涵蓋/TLP-completion
配對/config space capability 涵蓋；MIPI 的 VC×DT matrix；Ethernet 的 descriptor ring/
frame matrix；CAN-FD 的 arbitration/frame-format/confinement state；SD-SDIO/eMMC 的
command×response type；eDP 的 link-training/AUX transaction；UCIe 的 LTSM/protocol
stack；USB 的 transfer-type×speed matrix）。這 10 個協定以外的環境（含 AMBA4 fabric，
已由 fabric_topology_completeness_gate 涵蓋）需明確填
`{"protocol_completeness_applicable": false, "protocol_completeness_not_applicable_reason": "..."}`，
不得省略此區塊。

```dv-harness-evidence:protocol_structural_completeness_gate
{"protocol": "USB",
 "declared_speeds": ["HS", "FS"], "dual_speed": true, "usb3_capable": false, "lpm_capable": false,
 "num_configurations_declared": 1,
 "transfer_type_matrix": [
   {"transfer_type": "CONTROL", "speed": "HS", "status": "IMPLEMENTED"},
   {"transfer_type": "CONTROL", "speed": "FS", "status": "IMPLEMENTED"},
   {"transfer_type": "BULK", "speed": "HS", "status": "IMPLEMENTED"},
   {"transfer_type": "BULK", "speed": "FS", "status": "IMPLEMENTED"},
   {"transfer_type": "INTERRUPT", "speed": "HS", "status": "IMPLEMENTED"},
   {"transfer_type": "INTERRUPT", "speed": "FS", "status": "IMPLEMENTED"},
   {"transfer_type": "ISOCHRONOUS", "speed": "HS", "status": "IMPLEMENTED"},
   {"transfer_type": "ISOCHRONOUS", "speed": "FS", "status": "IMPLEMENTED"}
 ],
 "descriptor_requests": [
   {"descriptor_type": "DEVICE", "index": 0, "status": "IMPLEMENTED"},
   {"descriptor_type": "CONFIGURATION", "index": 0, "status": "IMPLEMENTED"},
   {"descriptor_type": "DEVICE_QUALIFIER", "index": 0, "status": "IMPLEMENTED"},
   {"descriptor_type": "OTHER_SPEED_CONFIGURATION", "index": 0, "status": "IMPLEMENTED"}
 ]}
```
（每個協定所需的欄位不同，實際結構請參照
`tools/verification_flow/protocol_structural_completeness_gate.py` 內對應
`check_<protocol>` 函式的說明；非以上 10 協定的環境改附
`{"protocol_completeness_applicable": false, "protocol_completeness_not_applicable_reason": "..."}`。）

本 stage 另外還有十一個獨立的 hard gate，涵蓋「branch topology 與 branch_fw 中斷契約」「per-port
驗證矩陣與 protocol scheduler 模式」「reset/clock/power 事件排序」「error injection／observability／
assertion placeholder 這條可觀察性鏈」與「Reference UVM 相容性、改編、scoreboard/reference model
獨立性」五個面向，也都必須各自附上 evidence block，缺一個都會讓整個 stage 卡在
GATE_FAIL/MISSING_EVIDENCE：

先是 branch topology 與 branch_fw 中斷契約這兩個（呼應 CLAUDE.md「Event/control register 階層」與
「真實 FW pattern 是 interrupt-driven」規則，在這個 stage 就先鎖死，不要等到 IMPLEMENT 才發現
branch_fw 被寫成 polling）：

```dv-harness-evidence:branch_topology_gate
{"protocol": "USB", "dut_port_count": 1, "vip_port_count": 1,
 "branches": ["block", "branch_fw", "branch_a0", "branch_b0"],
 "branch_fw_interrupt_driven": true}
```
（`branches` 必須完整涵蓋 `block`、`branch_fw`，以及依 `dut_port_count`/`vip_port_count` 展開的
0-indexed `branch_a0..branch_a{dut_port_count-1}`／`branch_b0..branch_b{vip_port_count-1}`——少一個
FAIL MISSING_REQUIRED_BRANCHES，多出不在這個範圍內的 `branch_a*`/`branch_b*` FAIL
PORT_COUNT_BRANCH_MISMATCH；`branch_fw_interrupt_driven` 一定要是 true，否則 FAIL
BRANCH_FW_NOT_INTERRUPT_DRIVEN。`protocol` 含有 "amba"（大小寫不拘）且 `dut_port_count` > 1 時，
還要附上 `cross_branch_bus_model`：`{"shared_resources": [...], "arbitration_policy": "..."}` 兩個
子欄位缺一都會 FAIL MULTI_BRANCH_BUS_ARBITRATION_UNMODELED——這就是 CLAUDE.md「Concurrent 匯流排
仲裁」規則落地的地方。）

```dv-harness-evidence:branch_fw_interrupt_contract_gate
{"interrupt_driven": true,
 "interrupt_map": [{"irq_id": "...", "source_register": "..."}],
 "acknowledge_path": "...", "polling_primary": false}
```
（`interrupt_driven` 必須是 true（FAIL FW_BRANCH_NOT_INTERRUPT_DRIVEN）；`interrupt_map` 不能是空的
（FAIL NO_INTERRUPT_MAP）；`acknowledge_path` 必須非空（FAIL NO_INTERRUPT_ACK_PATH）；
`polling_primary` 不能是 true（FAIL POLLING_CANNOT_BE_PRIMARY_FW_TRIGGER）——四項合起來就是
「branch_fw 只能是 interrupt-driven dispatcher，不能把 CPU 週期性 READ 輪詢當主要偵測手段」這條
規則的證據化。）

再來是 per-port 驗證矩陣與 protocol scheduler 模式這兩個（確保多 port 環境每個 port 都有獨立機制、
排程模式跟協定本身的並行/序列特性一致）：

```dv-harness-evidence:per_port_verification_matrix_gate
{"required_feature_combinations": ["BULK_HS", "BULK_FS"],
 "ports": [{"port_id": "P0",
   "scoreboard": "...", "checker": "...", "performance_calculator": "...", "coverage_collector": "...",
   "covered_feature_combinations": ["BULK_HS", "BULK_FS"]}]}
```
（`ports` 裡每一個 port 都要同時附上 `scoreboard`／`checker`／`performance_calculator`／
`coverage_collector` 四個機制，缺任一個 FAIL MISSING_PER_PORT_MECHANISM；每個 port 的
`covered_feature_combinations` 必須涵蓋 `required_feature_combinations` 全集，缺任何一項 FAIL
PORT_FEATURE_MATRIX_GAP。只有單一 port 時，`ports` 陣列填一筆即可；`ports: []` 時這兩項檢查都不會
觸發，只適合真的沒有 per-port 拆分意義的環境，不要為了省事而把有意義的 port 拆分省略掉。）

```dv-harness-evidence:protocol_scheduler_gate
{"protocol": "USB", "mode": "N_TO_M_PARALLEL",
 "cross_port_global_lock": false, "independent_port_queues": true}
```
（`protocol` 是 APB/APB2/APB3 時，`mode` 必須是 `"N_TO_1_SERIAL"`，否則 FAIL APB_MUST_SERIALIZE；
`protocol` 是 USB/USB2/USB3/PCIe/AXI/AXI3/AXI4/AXIS/AXI-Stream 這類天生可並行的協定時，`mode`
必須是 `N_TO_M_PARALLEL`/`M_TO_N_PARALLEL`/`M_TO_N_PARALLEL_INDEPENDENT_PORTS` 三選一，否則 FAIL
PARALLEL_PROTOCOL_NOT_PARALLEL，且 `independent_port_queues` 必須是 true，否則 FAIL
PARALLEL_PROTOCOL_NEEDS_INDEPENDENT_PORT_QUEUES；不論協定為何，`cross_port_global_lock` 都不能是
true，否則直接 FAIL CROSS_PORT_GLOBAL_LOCK_FORBIDDEN——這是把「branch_fw 僅為 dispatcher、不是
protocol traffic scheduler」與「各 port 各自獨立、不共用全域鎖」這兩條原則一起釘進 gate。）

接著是 reset/clock/power 事件排序：

```dv-harness-evidence:reset_clock_power_sequence_gate
{"events": [{"event": "POR_RELEASE"}, {"event": "CLOCK_STABLE"}, {"event": "FW_BOOT_DONE"}],
 "ordering_rules": [{"before": "POR_RELEASE", "after": "CLOCK_STABLE"},
                     {"before": "CLOCK_STABLE", "after": "FW_BOOT_DONE"}],
 "power_aware_design": false}
```
（`events` 不能是空陣列（FAIL NO_SEQUENCE_EVENTS）；`ordering_rules` 裡每一筆 `before`/`after` 都
必須是 `events` 裡真的存在的 `event` 名稱（缺一個 FAIL ORDERING_RULE_EVENT_MISSING），且 `before`
在 `events` 陣列裡的排列順序必須真的排在 `after` 前面，否則 FAIL SEQUENCE_ORDER_VIOLATION——不是
自己宣告順序對就算數，是照 `events` 陣列實際排列去驗證。`power_aware_design` 是 true（有 power
domain/isolation cell）時，`isolation_or_retention_checked` 也要是 true，否則 FAIL
POWER_SEQUENCE_WITHOUT_ISOLATION_RETENTION_CHECK；非 power-aware 設計時 `power_aware_design` 填
false 即可跳過這項。）

然後是 error injection／observability／assertion placeholder 這條可觀察性鏈（assertion_placeholder_
closure_gate 是刻意接在 observability_sufficiency_gate 之後同一批查的，兩者都在同一個
observability 主題下，設計上要相鄰處理）：

```dv-harness-evidence:observability_sufficiency_gate
{"requirements": [{"requirement_id": "REQ-001", "status": "OPEN",
   "observability": [{"type": "SCOREBOARD", "evidence_point": "sb_top.compare()"}]}]}
```
（`requirements` 裡每一筆 `status` 不是 `"WAIVED"` 的要求，都必須附非空的 `observability` 陣列
（FAIL REQUIREMENT_WITHOUT_OBSERVABILITY），且陣列裡至少一筆的 `type` 要落在
SCOREBOARD/CHECKER/ASSERTION/MONITOR/LOG_SEMANTIC 之一並附上非空的 `evidence_point`，否則 FAIL
INSUFFICIENT_OBSERVABILITY——只是「掛個名字」不夠，要有實際指向的觀察點。）

```dv-harness-evidence:assertion_placeholder_closure_gate
{"assertion_entries": []}
```
（`assertion_entries` 對應 `generate_observability_plan.py` 產出的 `implementation_manifest.json`
裡同名欄位；此 stage 尚未真的跑過那支 generator 時，附空陣列 `[]` 就是誠實的預設值，gate 不會為此
FAIL。一旦有條目，其中任何一筆 `classification` 是 `"PROTOCOL_STATE_MACHINE_LEGALITY"`（planner
自己判定「可從有限合法值/狀態加合法性關係機械決定」的需求）卻 `generation_method` 還是
`"placeholder"`，就會 FAIL STATE_MACHINE_LEGALITY_ASSERTION_STILL_PLACEHOLDER——這條規則只堵「明明
可以自動生成卻還停在 TODO 佔位」這一種情況，不是要求所有 assertion 都必須 DSL 生成
（Q2/INTERRUPT_RESPONSE_SEMANTIC、Q3/CROSS_CYCLE_TEMPORAL_INVARIANT 類仍允許手寫）。）

```dv-harness-evidence:error_injection_coverage_gate
{"required_error_classes": ["CRC_ERROR", "TIMEOUT", "PROTOCOL_VIOLATION"],
 "tests": [{"testcase_id": "tc_crc_error_injection", "error_classes": ["CRC_ERROR"],
            "checker_ids": ["crc_checker"], "assertion_ids": []}]}
```
（`tests` 裡每一筆都必須至少附上非空的 `checker_ids` 或 `assertion_ids` 其中之一，否則 FAIL
ERROR_TEST_WITHOUT_CHECK——代表這是「有注入錯誤但沒人在看結果」的無效測試；所有 `tests` 的
`error_classes` 聯集起來，必須涵蓋 `required_error_classes` 全部，缺任何一類 FAIL
MISSING_ERROR_INJECTION_CLASSES。本次 scope 若真的沒有需要錯誤注入的需求，`required_error_classes`
與 `tests` 都填空陣列即可誠實通過。）

最後是 Reference UVM 相容性、改編、與 scoreboard/reference model 獨立性這三個（呼應 CLAUDE.md
「No Golden-Reference Content Mining」——可以參考既有 Reference UVM，但不能整段照抄，也不能讓
scoreboard 的判斷依據跟 DUT 本身的實作邏輯共用同一個來源）：

```dv-harness-evidence:reference_uvm_compatibility_gate
{"reference_name": "USB_UVM_Handoff", "reference_revision": "...", "reference_hash": "...",
 "compatibility_analysis": {"protocol_role": "...", "interface_mapping": "...",
   "config_mapping": "...", "sequence_reuse": "...", "scoreboard_checker_reuse": "..."},
 "reuse_decision": "REUSE", "adaptation_plan": "..."}
```
（`reference_name` 不能空（FAIL NO_REFERENCE_NAME）；`reference_revision`／`reference_hash` 都要
非空，代表釘住了確切版本（缺一 FAIL UNPINNED_REFERENCE_ENV）；`compatibility_analysis` 必須是個
物件且同時包含 `protocol_role`／`interface_mapping`／`config_mapping`／`sequence_reuse`／
`scoreboard_checker_reuse` 五個 key，缺任一個 FAIL INCOMPLETE_REFERENCE_COMPATIBILITY；
`reuse_decision` 是 `"REUSE"` 時，一定要附 `adaptation_plan`，否則 FAIL
REUSE_WITHOUT_ADAPTATION_PLAN——不能宣告要重用卻沒說怎麼改。）

```dv-harness-evidence:reference_uvm_adaptation_gate
{"reference_uvm_hash": "...", "new_dut_architecture_hash": "...",
 "gap_analysis_hash": "...", "adaptation_plan_hash": "...",
 "blind_copy": false, "dut_specific_changes": ["..."]}
```
（`reference_uvm_hash`／`new_dut_architecture_hash`／`gap_analysis_hash`／`adaptation_plan_hash`
四個欄位都必須非空，缺任一個 FAIL INCOMPLETE_REFERENCE_UVM_ADAPTATION；`blind_copy` 不能是 true，
否則 FAIL REFERENCE_UVM_BLIND_COPY_FORBIDDEN；`dut_specific_changes` 必須非空，證明真的針對這顆
DUT 做過調整，否則 FAIL NO_DUT_SPECIFIC_ADAPTATION_PROVEN。）

```dv-harness-evidence:scoreboard_reference_model_independence_gate
{"shares_dut_implementation_code": false,
 "shared_algorithm_source_hash": "", "dut_algorithm_source_hash": "...",
 "independent_oracle_basis": "protocol spec + register map (not DUT RTL)",
 "negative_control_detected": true}
```
（`shares_dut_implementation_code` 不能是 true，否則 FAIL REFERENCE_MODEL_MIRRORS_DUT——reference
model 不能直接搬 DUT 的實作程式碼當 oracle；若 `shared_algorithm_source_hash` 有填，且跟
`dut_algorithm_source_hash` 完全相同，會 FAIL COMMON_MODE_DEFECT_RISK（兩邊共用同一份演算法來源，
DUT 錯了 scoreboard 也會跟著錯，抓不出問題）；`independent_oracle_basis` 必須非空，說明這個
scoreboard 的判斷依據是什麼獨立來源（例如協定規格，而非 DUT RTL 本身）；`negative_control_detected`
必須是 true，代表真的證明過這個 scoreboard/reference model 對「刻意注入的錯誤」有反應、不是形同
虛設，否則 FAIL SCOREBOARD_EFFECTIVENESS_UNPROVEN。）
""",
Stage.IMPLEMENT.value: """
Test Generation + Negative Tests + Monitor/Scoreboard/Checker/Assertion/Reference Model 實作：
把目前 finding registry 中所有本次 scope 內 actionable findings 一次完成修改，
包含至少一組 negative test（故意注入錯誤，確認 checker 真的能抓到）。
不要只修第一個 failure。

Traceability Consistency Hard Gate：每個 testcase 都要能追回 requirement/mechanism/coverage，
不得有測試寫好了卻沒有掛回 vPlan requirement 或對應的 mechanism。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上：

```dv-harness-evidence:traceability_consistency_gate
{"vplan_requirement_ids": ["..."], "architecture_nodes": ["..."],
 "verification_mechanisms": [{"mechanism_id": "...", "vplan_requirement_ids": ["..."]}],
 "planned_testcases": [{"testcase_id": "...", "vplan_requirement_ids": ["..."],
   "mechanism_ids": ["..."], "coverage_ids": ["..."]}],
 "coverage_ids": ["..."]}
```
（PASS 需要所有 requirement 都被至少一個 testcase 引用到；有 uncovered requirement 會回傳 GAP。）

Pattern Registry Completeness Hard Gate（若本次改動涉及 pattern/testcase suite 分類，例如新增/刪除
command.txt-style pattern 或調整 suite 分組）：suite 名單一律由目前真實的 pattern 清單重新算出
（sorted(set(...))），絕不可沿用先前寫死的 suite 清單——taxonomy 遷移後若沒有重新計算，會讓某個 suite
悄悄變成零個 pattern 而沒人發現。回覆結尾附上：

```dv-harness-evidence:pattern_registry_completeness_gate
{"patterns": [{"name": "...", "suite": "...", "dir": "..."}],
 "suite_names": ["..."], "declared_suites": ["..."]}
```
（PASS 需要：無重複 pattern name、每個 pattern 都有 suite/dir、suite_names 與從 patterns 重新算出的結果
完全一致、declared_suites 內每個 suite 至少對應一個 pattern。）

Manual Lookup Before Edit Hard Gate（branch_a{N}/branch_fw/branch_b{N} 修改一律要附）：
branch_b{N}（VIP pattern）修改前必須先查 VIP examples、VIP 使用手冊、VIP source code、class reference
這 4 項，缺一都算沒做足查證；branch_a{N}/branch_fw（DUT 側）修改前必須先查 DUT RTL source code（必要），
再加上 PHY documents / programming guide / 其他相關資料至少一項（若這次改動真的與 PHY/programming guide
無關，需附明確理由 phy_programming_guide_not_applicable_reason，不能就地略過）。

這個 gate 不只信任 `*_checked: true` 這種自己宣稱的布林值——`vip_evidence_refs`／`dut_rtl_evidence_refs`
是必填的真實引用清單，每一筆 `{"path": "...", "quote": "..."}` 都會被實際拿去檔案系統驗證：`path`
必須是真的存在的檔案，`quote` 必須真的逐字出現在該檔案內容裡，兩者有一個對不上就直接 FAIL——不接受
編出一個不存在的檔案，也不接受引用一個真檔案但內容是編的。回覆結尾附上：

```dv-harness-evidence:manual_lookup_before_edit_gate
{"branch": "branch_b0",
 "vip_examples_checked": true, "vip_manual_checked": true,
 "vip_source_checked": true, "vip_class_reference_checked": true,
 "vip_evidence_refs": [{"path": "<真實 VIP 文件/範例檔案路徑>", "quote": "<從該檔案逐字擷取的一小段>"}]}
```
或（branch_a{N}/branch_fw 側）：
```dv-harness-evidence:manual_lookup_before_edit_gate
{"branch": "branch_a0", "dut_rtl_checked": true, "programming_guide_checked": true,
 "dut_rtl_evidence_refs": [{"path": "<真實 RTL 檔案路徑>", "quote": "<從該檔案逐字擷取的一小段，例如暫存器/訊號名稱>"}]}
```

測試/Checker 品質三個獨立 hard gate（checker_independence_gate / testcase_name_semantics_gate /
verification_intent_gate）也必須各自附上 evidence block，缺任一個都會讓 stage 卡在
MISSING_EVIDENCE（找到真實案例：IMPLEMENT 內容做得很完整，但這三個 gate 的 evidence 一個都沒附，
導致同一組 GATE_FAIL 連續重試多輪）：

Checker Independence Hard Gate：確保每個 checker 都有真正獨立於 DUT 的實作來源與期望值模型，
不是拿 DUT 自己的邏輯來檢查自己。回覆結尾附上：

```dv-harness-evidence:checker_independence_gate
{"checkers": [{"checker_id": "...", "implementation_source": "<checker 實作檔案路徑>",
  "dut_source": "<被檢查的 DUT RTL 檔案路徑>", "expected_data_source": "REFERENCE_MODEL",
  "independent_predictor": true, "checker_disabled": false, "signoff_credit": true}]}
```
（`implementation_source` 為必填，缺了會判 FAIL（CHECKER_WITHOUT_IMPLEMENTATION_SOURCE）；
`implementation_source` 不可以跟 `dut_source` 是同一個檔案，等於照抄 DUT 自己的邏輯來檢查自己，
會判 FAIL（CHECKER_COPIES_DUT_LOGIC）；`expected_data_source` 若為 `"DUT_OUTPUT_ONLY"` 卻沒有
`independent_predictor: true`，代表期望值本身就是從 DUT 輸出反推出來的，等同沒有獨立期望值模型，
會判 FAIL（NO_INDEPENDENT_EXPECTED_MODEL）；`checker_disabled: true` 又同時 `signoff_credit: true`
（checker 已停用卻仍計入 signoff）會判 FAIL（DISABLED_CHECKER_HAS_CREDIT）。本輪若還沒有任何
新增/修改的 checker，`{"checkers": []}` 是誠實、合法的預設值。）

Testcase Name Semantics Hard Gate：testcase 名稱必須真的表達驗證意圖，不能是 `test1`、`basic`、
`tmp` 這種佔位式命名。回覆結尾附上：

```dv-harness-evidence:testcase_name_semantics_gate
{"tests": [{"testcase_id": "...", "name": "usb_bulk_transfer_error_recovery"}]}
```
（每筆都要有非空的 `testcase_id` 與 `name`，缺一會判 FAIL（TEST_WITHOUT_ID_OR_NAME）；`name` 不可
等於 `test1`/`test2`/`basic`/`misc`/`case1`/`tmp`/`new_test`/`scenario1` 這幾個保留字（不分大小寫），
長度也不可小於 8 字元，否則判 FAIL（ABSTRACT_TEST_NAME）；`name`（不分大小寫）裡至少要包含
`reset`/`error`/`recovery`/`bulk`/`iso`/`dma`/`ltssm`/`traffic`/`interrupt`/`timeout`/`read`/`write`/
`link`/`enumeration`/`concurrency`/`performance`/`power`/`clock`/`cdc`/`protocol` 其中一個關鍵字，
否則判 FAIL（TEST_NAME_LACKS_VERIFICATION_SEMANTICS）。本輪若還沒有任何新增 testcase，
`{"tests": []}` 是誠實、合法的預設值。）

Verification Intent Hard Gate：requirement/mechanism/coverage/test 四者必須真的互相對得起來，
每個 requirement 都要有至少一個 test 宣稱涵蓋到。回覆結尾附上：

```dv-harness-evidence:verification_intent_gate
{"requirements": [{"req_id": "..."}], "mechanisms": [{"mechanism_id": "..."}],
 "coverage": [{"coverage_id": "..."}],
 "tests": [{"testcase_id": "...", "requirement_ids": ["..."], "mechanism_ids": ["..."],
   "coverage_ids": ["..."]}]}
```
（`requirements`/`mechanisms`/`coverage`/`tests` 四個陣列都不能是空的，缺任一個分別判 FAIL
（NO_REQUIREMENTS/NO_MECHANISMS/NO_TESTS/NO_COVERAGE）；每筆 test 的 `requirement_ids`/
`mechanism_ids`/`coverage_ids` 都不可以是空陣列，否則判 FAIL（INCOMPLETE_TEST_INTENT）；這三組
id 也都必須是前面 `requirements`/`mechanisms`/`coverage` 陣列裡真的存在的 id 的子集合，引用到
不存在的 id 會分別判 FAIL（TEST_UNKNOWN_REQUIREMENT/TEST_UNKNOWN_MECHANISM/TEST_UNKNOWN_COVERAGE）；
最後所有 `requirements` 裡的 req_id 必須至少被一個 test 的 `requirement_ids` 引用到，有漏網的
requirement 會判 FAIL（REQUIREMENT_WITHOUT_TEST_INTENT，並列出 `missing` 清單）。）

Protocol Isolation Hard Gate（與上面 Manual Lookup Before Edit Hard Gate 共用同一組
`vip_evidence_refs`／`dut_rtl_evidence_refs` 欄位，但檢查角度不同）：manual_lookup_before_edit_gate
只管「有沒有查證」，這個 gate 另外管「查證的來源本身有沒有誤引用到禁止當作 primary source 的
reference 環境樹（目前是 `USB_UVM_Handoff`，對應 CLAUDE.md 的 No Golden-Reference Content Mining
規則）」。回覆結尾附上：

```dv-harness-evidence:protocol_isolation_gate
{"vip_evidence_refs": [], "dut_rtl_evidence_refs": []}
```
（沿用同一輪 manual_lookup_before_edit_gate 實際附上的 `vip_evidence_refs`／`dut_rtl_evidence_refs`
內容即可；只要其中任何一筆 `path` resolve 之後的路徑片段包含 `USB_UVM_Handoff`，就代表把 reference
環境當成 primary VIP/DUT 來源引用，會判 FAIL（REFERENCE_TREE_CITATION_FORBIDDEN）。這個 gate 本身
允許兩個欄位都缺席或為空陣列直接 PASS——它不像 manual_lookup_before_edit_gate 會因為「沒查證」而
FAIL，它只在「查證來源真的指向禁止的 reference 樹」時才 FAIL，所以誠實的空陣列或省略欄位都是合法
的預設值。）
""",
Stage.CHANGE_IMPACT.value: """
對 Git/RTL/UVM/spec/config 變更做 Verification Change Impact。
輸出 TARGETED + DEPENDENCY + SAFETY regression selection。

此變更必須對專案內「所有」command.txt 逐一判定 IMPACTED/NOT_IMPACTED 並記錄理由，不得只列出主觀認為
受影響的子集——`spec_rtl_change_impact_gate` 現在會用 harness 自己真的掃描到的 command.txt 清單（不是
你回報的清單）反向核對，漏掉一個沒判定就直接 FAIL。回覆結尾附上：

```dv-harness-evidence:spec_rtl_change_impact_gate
{"impact": {"changed_items": ["..."],
  "required_revalidation_artifacts": ["..."], "completed_revalidation_artifacts": ["..."],
  "spec_changed": false, "vplan_reanalyzed": null,
  "rtl_interface_or_arch_changed": false, "architecture_rediscovered": null, "mechanism_plan_revalidated": null,
  "command_txt_impact_verdict": {
    "<相對路徑>/command.txt": {"status": "IMPACTED", "reason": "..."},
    "<另一個路徑>/command.txt": {"status": "NOT_IMPACTED", "reason": "與本次變更的 module/interface 無關"}
  }}}
```
（`changed_items` 為空時直接 PASS，不需要走完整流程；`spec_changed`/`rtl_interface_or_arch_changed` 為 true 時
對應的 `vplan_reanalyzed`/`architecture_rediscovered`/`mechanism_plan_revalidated` 必須是 true，不能留 null。）

本 stage 另外還有一個獨立的 hard gate，也必須附上 evidence block，缺了會讓整個 stage 卡在
GATE_FAIL/MISSING_EVIDENCE（同一種真實案例：agent 只附了 spec_rtl_change_impact_gate，
artifact_dependency_closure_gate 沒附，導致 stage 反覆卡在同樣的 GATE_FAIL）：

```dv-harness-evidence:artifact_dependency_closure_gate
{"artifacts": [
  {"artifact_id": "...", "hash": "...", "depends_on": ["..."], "stale": false}
]}
```

（盤點本次 Change Impact 分析中實際涉及的產出物（例如受影響的 vPlan/regression selection/
architecture model 等 artifact）及它們彼此的依賴關係——這個階段本來就沒有處理到任何 artifact
時，`{"artifacts": []}` 是誠實、合法的預設值，gate 對空清單直接 PASS，不需要硬湊內容。一旦列出
任何一筆，`artifact_id` 與 `hash` 都是必填：漏了 `hash`（或給空字串/null）會被判 FAIL
（UNHASHED_ARTIFACT）；`depends_on` 裡列的每個 parent artifact_id 都必須也出現在同一份
`artifacts` 清單裡，指向一個清單裡查不到的 artifact 會被判 FAIL（MISSING_ARTIFACT_DEPENDENCY）
——不能只列出自己這筆卻漏了它依賴的 parent；某個 parent 的 `stale` 為 true 時，依賴它的這筆也會被
判 FAIL（STALE_ARTIFACT_DEPENDENCY），代表不能在依賴鏈裡還有過期產出物的情況下宣稱這次的
change impact 分析已經完整、可信。）
""",
Stage.GIT_SYNC.value: """
安全執行 Git status/fetch/sync strategy discovery；保護 unrelated user changes。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上：

```dv-harness-evidence:git_sync_safety_gate
{"fetch_output": "<git fetch 實際輸出>", "sync_strategy": "FAST_FORWARD",
 "destructive_command_used": false,
 "pre_sync_dirty_paths": ["..."],
 "accounted_paths": {"stashed": [], "committed": [], "preserved_untouched": []}}
```
（sync 前若 working tree 乾淨，pre_sync_dirty_paths 給 [] 即可。sync_strategy 只能是
FETCH_ONLY/MERGE/REBASE/FAST_FORWARD，不得使用 reset --hard/clean -f 等破壞性指令。）
""",
Stage.GIT_PUSH.value: """
完成 diff review、secret/artifact gate、commit 與 push，記錄 exact commit SHA。禁止 force push。

本 stage 還有一個獨立的 hard gate，確保「第一輪 workflow 發現的問題全部修完」之後，
還要完整跑過一次第二輪詳細 workflow 分析、確認真的乾淨，才准許往下推進到
push→build→verify 這條 pipeline（不是修完第一輪就直接 push）。回覆結尾附上：

```dv-harness-evidence:workflow_second_pass_clean_gate
{"first_workflow_complete": true, "all_first_pass_issues_fixed": true,
 "second_detailed_workflow_run": true, "remaining_issue_count": 0,
 "push_build_verify_run_requested": false, "clean_second_pass": true}
```

（first_workflow_complete 必須是 true，代表第一輪 workflow 分析真的跑完，不是還在進行中
（否則 FAIL：FIRST_WORKFLOW_NOT_COMPLETE）；all_first_pass_issues_fixed 必須是 true，代表
第一輪發現的所有 issue 都已經修完，不能只修一部分就宣稱完成（否則 FAIL：
NOT_ALL_FIRST_PASS_ISSUES_FIXED）；second_detailed_workflow_run 必須是 true，代表真的完整
再跑過一次詳細的第二輪 workflow 分析，不能省略這一步直接宣稱乾淨（否則 FAIL：
SECOND_WORKFLOW_ANALYSIS_REQUIRED）；remaining_issue_count 必須是 0（省略時預設也是 0），
代表第二輪分析後已經沒有殘留 issue，如實填入第二輪實際發現的殘留數量，大於 0 會直接 FAIL
（SECOND_PASS_STILL_HAS_ISSUES，並回報這個殘留數量）；push_build_verify_run_requested 用來
表示這次是否要緊接著請求進到 push→build→verify pipeline，本階段若還不打算立刻推進，可以
省略或填 false；一旦填 true，就必須同時把 clean_second_pass 明確填成 true，代表第二輪確實
乾淨、可以放行進到下一段 pipeline，否則會被判定「在還沒確認第二輪乾淨之前就要推進」
（FAIL：PROMOTION_BEFORE_CLEAN_SECOND_PASS）。）
""",
Stage.SERVER_SYNC.value: """
在 Linux Server 同步並確認 HEAD SHA = expected pushed SHA；submodule SHA 也需一致。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。若這個專案在 PC 與 Linux 之間有 git
remote，回覆結尾附上（identity_method 可省略，預設等同 "git_sha"）：

```dv-harness-evidence:server_sync_identity_gate
{"identity_method": "git_sha", "expected_sha": "...", "server_head_sha": "...",
 "submodules": [{"name": "...", "expected_sha": "...", "server_sha": "..."}]}
```
（沒有 submodule 時 "submodules": [] 即可。）

若這個專案沒有 git remote（CLAUDE.md「Remote Linux Execution」規定的 SOURCE_ID
git-free 備援路徑，"never skipped outright"），改附 identity_method="source_id"，
並附上兩個「真實檔案路徑」（不是把內容直接寫進 JSON）：

```dv-harness-evidence:server_sync_identity_gate
{"identity_method": "source_id",
 "local_md5sum_transcript_path": "<PC 端執行 md5sum 的真實輸出檔路徑>",
 "remote_md5sum_transcript_path": "<真實 tools/remote/remote_exec.py \\"md5sum <files>\\" 呼叫的真實 stdout 轉錄檔路徑>"}
```
（gate 會實際讀這兩個檔案、用 tools/remote/source_identity.py 重新算一次
three-way diff + aggregate id，PASS/FAIL 完全看這個真實重算的結果，不是看你
宣稱的值；remote 端那份必須真的帶有 remote_exec.py 自己蓋的
REMOTE_HOST=/EXIT_CODE=/STATUS= 標記且 EXIT_CODE=0，local 端只檢查檔案真實存在
——PC 端目前沒有對應的轉錄真實性標記慣例，這是已知、記錄在案的殘留限制。）

注意：本 stage 屬 REMOTE_EXECUTION，需先完成 CLAUDE.md 的 SSH/Remote Transport
Connection Intake（詢問使用者是否建立連線、蒐集 account/vc machine/ssh machine/
working path 四項，密碼不得寫入任何 evidence block）。
""",
Stage.BUILD.value: """
依 project canonical flow 執行 build。Coverage 預設 OFF。保存 evidence。

本 stage 有三個獨立的 hard gate，也必須各自附上 evidence block，缺一個都會讓整個 stage 卡在
GATE_FAIL/MISSING_EVIDENCE：前兩個是 build 狀態機本身的正確性（有沒有多個 job 同時搶著寫同一份
共用 elaboration 產出、build 完成後是否真的 stop 而不是滑落到 run），第三個是「這個 build 真的有
在遠端伺服器上執行」的獨立證明（不能只靠 agent 自己宣稱 build 成功）：

```dv-harness-evidence:shared_elaboration_collision_gate
{"elaboration_jobs": [{"job_id": "elab_001", "state": "DONE", "write_paths": ["/proj/build/out/simv"]}],
 "shared_output_paths": ["/proj/build/out/simv"],
 "parallel_test_workers": 1, "each_worker_runs_full_compile": false,
 "build_owner_count": 1,
 "simv_valid": true, "worker_invokes_usbc_elab": false}
```
（elaboration_jobs 要如實列出本輪實際觀察到的 elaboration job，每個 job 的 state 只要是
RUN/PEND/STARTING 就算「還在跑」，若有兩個以上這種 active job 的 write_paths 命中同一個列在
shared_output_paths 裡的路徑，就會被判 FAIL（CONCURRENT_SHARED_ELABORATION_COLLISION）——代表有多個
job 同時搶著寫同一份共用 elaboration 產出，這是不允許的；parallel_test_workers>1 又
each_worker_runs_full_compile 為 true 會 FAIL（PARALLEL_WORKERS_MUST_NOT_RECOMPILE_SHARED_SIMV，
平行的測試 worker 不該各自重新 compile 共用的 simv）；build_owner_count 一定要恰好是 1，不是 1
就 FAIL（SINGLE_BUILD_OWNER_REQUIRED，build 必須有唯一 owner，不能沒人負責也不能多人搶著做）；
simv_valid 為 true 又 worker_invokes_usbc_elab 為 true 會 FAIL
（REDUNDANT_ELAB_WHEN_VALID_SIMV_EXISTS，已經有一份可用的 simv 時就不該再重新 elaborate 一次）。）

```dv-harness-evidence:stop_after_simv_policy_gate
{"compile_target_can_fall_through_to_run": true, "stop_after_simv": true,
 "parallel_run_count": 1, "compile_completed_before_parallel_runs": true,
 "build_fingerprint": "<實際 build 的 fingerprint/hash>",
 "simv_completion_marker": "<實際 simv 完成標記內容>",
 "simv_completion_marker_build_fingerprint": "<必須與 build_fingerprint 完全相同>"}
```
（如果這個專案的 compile target 本身「有可能」在沒有明確 stop 的情況下滑落直接跑下去
（compile_target_can_fall_through_to_run 為 true），stop_after_simv 就一定要明確填 true，
否則 FAIL（STOP_AFTER_SIMV_REQUIRED，build 完成後必須真的停在 simv，不能自動滑到 run）；
parallel_run_count>1 時，compile_completed_before_parallel_runs 一定要是 true，否則 FAIL
（PARALLEL_RUNS_STARTED_BEFORE_COMPILE_COMPLETE，平行跑多個 run 之前 compile 必須先真的完成）；
build_fingerprint 與 simv_completion_marker 兩個欄位都不能留空，缺任一個就 FAIL
（BUILD_COMPLETION_NOT_ATOMICALLY_PROVEN，build 完成這件事必須有原子性的證明，不能只憑口頭
宣稱）；simv_completion_marker_build_fingerprint 必須和 build_fingerprint 逐字相同，不同就 FAIL
（STALE_SIMV_COMPLETION_MARKER，代表這份 completion marker 其實是舊的、對不上這次的 build）。）

```dv-harness-evidence:remote_execution_provenance_gate
{"provenance_applicable": true,
 "transcript_path": "<真實存在的 tools/remote/remote_exec.py 輸出 transcript 檔案路徑>",
 "claimed_exit_code": 0}
```
（transcript_path 必須是磁碟上真實存在的檔案，內容是實際執行 tools/remote/remote_exec.py 產生的
原始 stdout（必須真的含有它 format_result() 蓋的 REMOTE_HOST=/EXIT_CODE=/STATUS= 這三個 marker，
少任一個或 REMOTE_HOST 是空的都會 FAIL，TRANSCRIPT_MISSING_MARKERS；檔案不存在則 FAIL，
TRANSCRIPT_FILE_NOT_FOUND）——不能用一段自己編的 JSON 字串冒充真的 transcript；claimed_exit_code
必須和 transcript 裡實際解析出來的 EXIT_CODE= 數字完全一致，兩者對不上就 FAIL
（EXIT_CODE_MISMATCH），代表不能一邊 transcript 顯示遠端指令失敗、一邊卻宣稱 build 成功。這一輪
如果根本沒有透過 remote_exec.py 做任何遠端操作（例如純本地整理既有 build 產出），才可以把
provenance_applicable 填 false，但這時 provenance_not_applicable_reason 一定要附上非空的理由字串，
否則同樣 FAIL（NOT_APPLICABLE_WITHOUT_JUSTIFICATION）——不接受沒有理由的裸 false。）
""",
Stage.BUILD_DEBUG.value: """
Build 失敗的第一輪快速分流：讀 build log，判斷這是可以立即修的小問題
（syntax error、missing file、compile flag 打錯、filelist 漏檔）還是需要走完整
Failure Recovery 的設計層問題。可立即修的話直接修好回 CHANGE_IMPACT 重跑；
修不了或懷疑是設計問題就轉 Failure Recovery，不要卡在這裡反覆猜。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上：

```dv-harness-evidence:build_failure_triage_gate
{"build_log_excerpt": "<實際 build log 錯誤片段>",
 "classification": "QUICK_FIX", "classification_reason": "...",
 "quick_fix_applied": true, "quick_fix_description": "...",
 "rerun_target_stage": "CHANGE_IMPACT"}
```
（若判定為 DESIGN_ISSUE，改附 "routed_to_failure_recovery": true 與 "failure_recovery_finding_id"。）
""",
Stage.VERIFY.value: """
Local Simulation → command.txt ↔ sim.log Semantic Verification → FALSE PASS Defense → TRUE_PASS。
執行 targeted single simulation / verify。FSDB 預設 OFF，VIP trace 可開。
PASS → 完成。FAIL → 停在第一個 failure/error/fatal/missing/mismatch，先用 sim.log/UVM 訊息分析；
只有真的需要 signal-level 證據時才考慮開波形，開之前必須先問使用者 dump scope 與 dump level/depth，
不得自行預設全開；確認後才 targeted rerun，一樣停在第一個相關失敗點。之後產生 finding 並轉 Failure Recovery。

本 stage 的 PASS 由 harness 端 gate 腳本裁定，不是你自稱 PASS 就算數。
你必須在回覆結尾附上下列三個 fenced code block（找不到足夠證據時就不要附，
harness 會將本 stage 標為 PARTIAL 並附上原因，而不是預設 PASS）：

```dv-harness-evidence:simulation_semantic_validation_gate
{"simulation_passed": true, "sim_log": "<真實 sim.log 內容或關鍵片段>",
 "command_expectations": [{"expectation_id": "...", "source_file": "command.txt",
   "testcase_id": "...", "required": true,
   "evidence_requirements": [{"pattern": "...", "match_mode": "SUBSTRING"}]}]}
```

```dv-harness-evidence:test_result_provenance_gate
{"results": [{"testcase_id": "...", "run_id": "...", "rtl_revision": "...",
  "tb_revision": "...", "vip_version": "...", "tool_version": "...",
  "seed": "...", "config_hash": "...", "result": "PASS", "log_hash": "...",
  "evidence_bundle_hash": "..."}]}
```

```dv-harness-evidence:false_pass_resistance_gate
{"positive_test_pass": true, "negative_test_detects_fault": true,
 "checker_detects_injected_fault": true, "semantic_log_match": true,
 "oracle_independent": true, "proof_bundle_hash": "..."}
```

本 stage 另外還有一大批獨立的 hard gate，同樣各自必須附上 evidence block，缺任何一個都會讓
VERIFY 卡在 GATE_FAIL/MISSING_EVIDENCE（找到真實案例：agent 只附了上面三個 gate，其餘全部
沒附，導致同一個 stage 重跑多輪都停在一模一樣的 GATE_FAIL，即使實際分析工作本身沒有問題）。

第一組：sim PASS 是否有真正的語意證據撐得住（不是抓到 sim.log 印 PASS 字樣就算數）：

```dv-harness-evidence:checker_semantic_trace_consistency_gate
{"items": [{"expectation_id": "...", "checker_expectation_id": "...", "testcase_id": "...",
  "vplan_ids": ["..."], "semantic_status": "MATCH", "checker_status": "PASS"}]}
```
（每一筆 item 的 `semantic_status` 必須是 "MATCH"，否則 FAIL CHECKER_CREDIT_WITHOUT_SEMANTIC_MATCH；
`checker_status` 必須是 "PASS"，否則 FAIL SEMANTIC_MATCH_WITHOUT_CHECKER_PASS；`testcase_id` 與
`vplan_ids` 兩者都不能留空，否則 FAIL CHECKER_SEMANTIC_TRACE_INCOMPLETE；`checker_expectation_id`
必須與 `expectation_id` 完全相同，否則 FAIL CHECKER_EXPECTATION_ID_MISMATCH——代表 checker 真的是在
盯同一個 expectation，不是張冠李戴。）

```dv-harness-evidence:command_intent_semantic_closure_gate
{"command_id": "...", "command_hash": "...", "simulation_result": "PASSED",
 "expected_semantics": "...", "observed_semantics": "...", "sim_log_hash": "..."}
```
（`command_id`/`command_hash`/`expected_semantics`/`observed_semantics`/`sim_log_hash` 五個欄位缺
任一個都會 FAIL INCOMPLETE_COMMAND_INTENT_EVIDENCE 並回報缺的欄位名；`simulation_result` 必須逐字
等於 "PASSED"，否則 FAIL SIMULATION_NOT_PASSED；`expected_semantics` 與 `observed_semantics` 必須
完全相同，否則 FAIL SIM_PASS_BUT_COMMAND_INTENT_MISMATCH——代表 sim 印 PASS，但 command.txt 原本
要驗的意圖跟實際觀察到的語意對不上，不能算真的過。）

```dv-harness-evidence:simulation_semantic_trace_gate
{"final_state": "TRUE_PASS", "signoff_credit_allowed": true,
 "results": [{"expectation_id": "...", "status": "MATCH", "source_line": 12,
   "evidence_source": "sim.log:1234"}]}
```
（`final_state` 必須是 "TRUE_PASS" 且 `signoff_credit_allowed` 必須為 true，否則 FAIL
SEMANTIC_RESULT_NOT_TRUE_PASS；`results` 陣列中每一筆的 `status` 必須是 "MATCH"，否則 FAIL
NON_MATCH_EXPECTATION；`source_line`（對應 command.txt 的來源行號）不得缺省，否則 FAIL
MISSING_COMMAND_SOURCE_PROVENANCE；`evidence_source`（實際證據出處，如 sim.log 行號）不得留空，
否則 FAIL MISSING_EVIDENCE_PROVENANCE。）

```dv-harness-evidence:wave0_post_sim_semantic_gate
{"wave_mode": 0, "command_hash": "...", "sim_log_hash": "...",
 "command_intent": "...", "observed_semantics": "...", "simulation_ended": true,
 "unexpected_error": false, "uvm_error_count": 0, "uvm_fatal_count": 0,
 "first_error_time_us": null}
```
（`wave_mode` 必須是 0（本 stage 預設 FSDB OFF），否則 FAIL DEFAULT_POSTCHECK_REQUIRES_WAVE0；
`command_hash`/`sim_log_hash`/`command_intent`/`observed_semantics` 四個欄位缺任一個都 FAIL
INCOMPLETE_WAVE0_SEMANTIC_EVIDENCE；`simulation_ended` 必須為 true，否則 FAIL
SIMULATION_NOT_ENDED；若 `command_intent` 與 `observed_semantics` 不相同，`first_error_time_us`
必須填實際數字（否則 FAIL SEMANTIC_MISMATCH_WITHOUT_ERROR_TIMESTAMP），gate 會回報
semantic_result=NEEDS_DEEP_DEBUG；若語意相符但 `unexpected_error`/`uvm_error_count`/
`uvm_fatal_count` 顯示有錯誤，同樣必須填 `first_error_time_us`（否則 FAIL
ERROR_WITHOUT_TIMESTAMP），gate 會回報 semantic_result=TRUE_FAIL；三者都乾淨才回報
semantic_result=TRUE_PASS。）

```dv-harness-evidence:semantic_evidence_strength_gate
{"minimum_rank": 2, "expectations": [{"expectation_id": "...",
  "evidence": [{"type": "SCOREBOARD", "contradicted": false, "detail": "..."}]}]}
```
（`minimum_rank` 未填時預設 2；`evidence` 的每個 `type` 依強度排序為 GENERIC_LOG(1) <
PROTOCOL_TRANSACTION(2) < ASSERTION(3) < CHECKER(4) < SCOREBOARD(5)，每個 expectation 至少要有一筆
evidence 且其中最高強度必須 ≥ minimum_rank，否則分別 FAIL NO_EVIDENCE 或 WEAK_SEMANTIC_EVIDENCE；
任一筆 evidence 的 `contradicted` 為 true 都會 FAIL CONTRADICTED_EVIDENCE——代表這筆證據本身已知
與其他觀察矛盾，不能拿來當作 PASS 的依據。）

第二組：FALSE PASS/FALSE FAIL 防禦，對應 CLAUDE.md「LSF DONE 不等於 DV PASS」同一精神在單一
simulation 層級的落地：

```dv-harness-evidence:false_pass_false_fail_arbitration_gate
{"simulation_status": "PASS", "semantic_status": "TRUE_PASS", "checker_status": "PASS",
 "fatal_or_uvm_error": false, "infrastructure_failure_evidence": null,
 "design_failure_evidence": null}
```
（gate 會交叉比對 `simulation_status`（sim 本身 PASS/FAIL）與 `semantic_status`/`checker_status`/
`fatal_or_uvm_error`：sim PASS 但語意證據對不上（semantic_status 非 TRUE_PASS、或 checker FAIL、
或有 fatal/UVM_ERROR）會直接 FAIL，classification=FALSE_PASS；sim FAIL 但語意/checker 其實都乾淨
時，必須附上非空的 `infrastructure_failure_evidence` 才會判為 INFRASTRUCTURE_FAIL_NOT_DUT_FAIL，
否則 FAIL，classification=UNRESOLVED_FALSE_FAIL；sim FAIL 且 checker FAIL/有 fatal/有
`design_failure_evidence` 才會判為真正的 TRUE_FAIL；四種組合都不符合時 FAIL
INSUFFICIENT_EVIDENCE，代表證據還不夠支撐任何一種裁定。）

```dv-harness-evidence:negative_test_effectiveness_gate
{"checks": [{"id": "...", "positive_passed": true, "negative_mutation_applied": true,
  "negative_control_result": "FAIL"}]}
```
（每一筆 check 的 `positive_passed` 必須為 true，否則 FAIL POSITIVE_CONTROL_FAILED；
`negative_mutation_applied` 必須為 true（代表真的注入過故意錯誤/mutation），否則 FAIL
NO_NEGATIVE_MUTATION；`negative_control_result` 必須逐字等於 "FAIL"（代表 checker/test 真的抓得到
這個故意注入的錯誤），否則 FAIL VACUOUS_TEST_OR_CHECKER——checker 連故意的錯誤都抓不到，PASS 就
沒有意義。）

```dv-harness-evidence:test_oracle_independence_gate
{"oracles": [{"oracle_id": "...", "shares_prediction_source_with_dut": false,
  "shares_bug_prone_algorithm_with_stimulus": false,
  "reference_basis": "...", "oracle_hash": "..."}]}
```
（`shares_prediction_source_with_dut` 與 `shares_bug_prone_algorithm_with_stimulus` 任一個為
true，都會 FAIL NON_INDEPENDENT_TEST_ORACLE——代表這個 oracle 跟 DUT 或 stimulus 共用了同一份可能
有錯的邏輯，不是獨立的參考標準；`reference_basis`（oracle 的依據，如 spec 章節/reference model）與
`oracle_hash` 兩者缺一都會 FAIL UNPROVEN_TEST_ORACLE。）

第三組：scoreboard expected-data 的來源與 transaction liveness：

```dv-harness-evidence:expected_data_provenance_gate
{"scoreboards": [{"scoreboard_id": "...", "expected_source": "REFERENCE_MODEL",
  "expected_source_hash": "...", "prediction_method": "..."}]}
```
（`expected_source` 不得留空，否則 FAIL NO_EXPECTED_SOURCE；`expected_source` 絕對不能是
"DUT_OUTPUT"，否則 FAIL EXPECTED_DATA_DERIVED_FROM_DUT_OUTPUT——expected value 若取自 DUT 自己的
輸出，等同拿 DUT 驗證 DUT，checker 永遠不會抓到錯；`expected_source_hash`（把 expected source 釘死
的 hash）與 `prediction_method`（怎麼從 expected_source 推出預期值）兩者缺一分別 FAIL
UNPINNED_EXPECTED_SOURCE / NO_PREDICTION_METHOD。）

```dv-harness-evidence:scoreboard_transaction_liveness_gate
{"missing_expected_transactions": 0, "missing_actual_transactions": 0,
 "duplicate_transactions": 0, "max_transaction_latency": 500,
 "observed_max_transaction_latency": 120}
```
（`missing_expected_transactions`/`missing_actual_transactions`/`duplicate_transactions` 三者只要
有任何一個大於 0，就分別 FAIL MISSING_EXPECTED_TRANSACTIONS / MISSING_ACTUAL_TRANSACTIONS /
DUPLICATE_TRANSACTIONS；`max_transaction_latency` 不得缺省，否則 FAIL
NO_TRANSACTION_LATENCY_BOUND；`observed_max_transaction_latency` 超過 `max_transaction_latency`
會 FAIL LATE_TRANSACTION。）

第四組：多 port 場景下的 interrupt/fairness/starvation（單 port 或本輪未涉及多 port 行為時，
對應清單可以誠實地留空陣列，gate 對空清單會直接通過，不需要硬湊資料）：

```dv-harness-evidence:interrupt_storm_latency_gate
{"sources": [{"source_id": "...", "max_ack_latency_cycles": 64,
  "observed_max_ack_latency_cycles": 20, "storm_rate": null,
  "storm_test_evidence": null, "lost_interrupts": 0}]}
```
（每個 interrupt source 的 `max_ack_latency_cycles` 不得缺省，否則 FAIL NO_ACK_LATENCY_BOUND；
`observed_max_ack_latency_cycles` 超過該上限會 FAIL ACK_LATENCY_VIOLATION；填了 `storm_rate` 卻
沒有 `storm_test_evidence` 會 FAIL INTERRUPT_STORM_WITHOUT_EVIDENCE；`lost_interrupts` 大於 0 會
FAIL LOST_INTERRUPTS。本輪測項未涉及任何 interrupt source 時，`{"sources": []}` 是誠實、合法的
預設值。）

```dv-harness-evidence:multi_port_fairness_qos_gate
{"ports": [{"port_id": "...", "min_service_share_percent": 20,
  "observed_service_share_percent": 25, "qos_enabled": false,
  "qos_policy_verified": false}]}
```
（每個 port 的 `min_service_share_percent` 不得缺省，否則 FAIL NO_MIN_SERVICE_SHARE；
`observed_service_share_percent` 低於該下限會 FAIL FAIRNESS_VIOLATION；`qos_enabled` 為 true 卻
`qos_policy_verified` 不是 true 會 FAIL QOS_NOT_VERIFIED。非多 port 測項可同樣附 `{"ports": []}`。）

```dv-harness-evidence:per_port_queue_starvation_gate
{"ports": [{"port_id": "...", "independent_queue": true, "max_wait_cycles": 256,
  "observed_wait_cycles": 40, "forward_progress_evidence": "..."}]}
```
（`independent_queue` 必須為 true，否則 FAIL PORT_NOT_INDEPENDENT_QUEUE；`max_wait_cycles` 不得
缺省，否則 FAIL NO_STARVATION_BOUND；`observed_wait_cycles` 超過該上限會 FAIL
PORT_STARVATION_DETECTED；`forward_progress_evidence` 不得留空，否則 FAIL
NO_FORWARD_PROGRESS_EVIDENCE。非多 port 測項可同樣附 `{"ports": []}`。）

第五組：remote 執行的真實性與 rerun/環境層級的可重現性——對應 CLAUDE.md 的 Source identity
與 Same regression batch 精神，落到單一 VERIFY run 的層級：

```dv-harness-evidence:remote_execution_provenance_gate
{"transcript_path": "<真實存在、由 tools/remote/remote_exec.py 產生的 stdout transcript 檔案路徑>",
 "claimed_exit_code": 0}
```
（`transcript_path` 必須是磁碟上真的存在的檔案，且內容必須包含 `remote_exec.py` 真正輸出的
`REMOTE_HOST=`/`EXIT_CODE=`/`STATUS=` 標記（找不到檔案 FAIL TRANSCRIPT_FILE_NOT_FOUND，檔案存在
但缺標記 FAIL TRANSCRIPT_MISSING_MARKERS）；`claimed_exit_code` 必須與 transcript 裡真正的
`EXIT_CODE=` 完全相同，否則 FAIL EXIT_CODE_MISMATCH——不能自稱 BUILD/VERIFY 成功卻讓真實
transcript 顯示非零 exit code。若本次 VERIFY 完全沒有透過 `remote_exec.py` 執行過任何指令，改附
`{"provenance_applicable": false, "provenance_not_applicable_reason": "..."}`，reason 為必填，
不接受單純的 false 空白帶過。）

```dv-harness-evidence:rerun_determinism_gate
{"runs": [{"input_fingerprint": "...", "semantic_verdict": "TRUE_PASS", "critical_checker_hash": "..."},
  {"input_fingerprint": "...", "semantic_verdict": "TRUE_PASS", "critical_checker_hash": "..."}]}
```
（`runs` 至少要有 2 筆，否則 FAIL INSUFFICIENT_EQUIVALENT_RERUNS——代表真的執行過至少一次
equivalent rerun，不是只跑一次就宣稱 deterministic；除第一筆外，其餘每一筆的 `input_fingerprint`
必須與第一筆完全相同，否則 FAIL NON_EQUIVALENT_RERUN_INPUT（代表根本不是同一組輸入的 rerun）；
`semantic_verdict` 與 `critical_checker_hash` 也必須與第一筆一致，否則 FAIL
NON_DETERMINISTIC_VERIFICATION_RESULT。）

```dv-harness-evidence:run_environment_reproducibility_gate
{"rtl_hash": "...", "testbench_hash": "...", "simulator_version": "...",
 "vip_version": "...", "compile_options_hash": "...", "runtime_options_hash": "...",
 "env_hash": "...", "final_verdict": "PASS", "replay_command": "..."}
```
（`rtl_hash`/`testbench_hash`/`simulator_version`/`vip_version`/`compile_options_hash`/
`runtime_options_hash`/`env_hash` 七個 fingerprint 欄位缺任一個都會 FAIL
MISSING_REPRODUCIBILITY_FINGERPRINT 並回報缺的欄位名；`final_verdict` 為 "PASS" 時
`replay_command`（可以逐字重跑出同一結果的指令）必須填，否則 FAIL
PASS_WITHOUT_REPLAY_COMMAND。）

第六組：長時間背景模擬的完成狀態必須定期主動 recheck，不能放著不管直到使用者自己回來問：

```dv-harness-evidence:simulation_completion_recheck_gate
{"simulation_ended": false, "background_completion_notification": false,
 "minutes_since_last_check": 1.5, "recheck_performed": false,
 "recheck_scheduled_for_minute": 4, "semantic_workflow_started": false}
```
（`simulation_ended` 為 true 時，`semantic_workflow_started` 必須為 true（否則 FAIL
SIM_ENDED_BUT_SEMANTIC_WORKFLOW_NOT_STARTED），代表模擬一結束就真的接著做語意分析，不是放著；
`simulation_ended` 為 false 時分三種情況：收到 `background_completion_notification` 卻沒有
`recheck_performed` 會 FAIL BACKGROUND_NOTIFICATION_NOT_RECHECKED；`minutes_since_last_check` ≥ 4
卻沒有 `recheck_performed` 會 FAIL FOUR_MINUTE_RECHECK_MISSED；以上皆非時，
`recheck_scheduled_for_minute` 必須等於 4（代表已排程下一次主動檢查），否則 FAIL
RECHECK_NOT_SCHEDULED_AT_FOUR_MINUTES。）
""",
Stage.WAVE_ANALYSIS.value: """
對代表性 testcase 以 WAVE=1、FSDB_START=0、FSDB_STOP=simulation_end 執行，
使用 fsdbreport；必要時 Verdi。保存 evidence。

Waveform Dump User Gate（CLAUDE.md）：開啟波形前，先向使用者確認 dump scope 與 level/depth，
優先根據目前 failure cone 用最小足夠波形，不可預設 full-chip/full-depth。回覆結尾附上：

```dv-harness-evidence:focused_wave_debug_window_gate
{"deep_debug_required": true, "dump_scope_confirmed": {"scope": "...",
  "level_or_depth": "...", "confirmed_by": "..."},
 "wave_mode": 1, "fsdb_start_us": 0, "first_error_time_us": 0, "fsdb_stop_us": 200,
 "simulation_stopped_at_fsdb_stop": true, "job_killed_or_terminated": true,
 "identity_preserved": true, "waveform_or_fsdbreport_evidence_hash": "..."}
```
""",
Stage.REGRESSION_SELECT.value: """
確認 TARGETED + DEPENDENCY + SAFETY + project mandatory signoff regression。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上：

```dv-harness-evidence:regression_selection_completeness_gate
{"targeted_tests": ["..."], "dependency_tests": ["..."], "safety_tests": ["..."],
 "mandatory_signoff_tests": ["..."],
 "selection_source": {"change_impact_evidence_id": "..."}}
```
（任一類別真的沒有適用測試時，改附對應的 "<category>_empty_reason" 說明原因，
不得直接留空交差。）
""",
Stage.REGRESSION.value: """
提交 LSF regression（一個 LSF job = 一個獨立 Job Agent context），Regression 預設 WAVE=0、PA=0、Coverage=OFF。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上：

```dv-harness-evidence:regression_submission_policy_gate
{"jobs": [{"job_id": "...", "agent_id": "...", "wave": 0, "pa": 0, "coverage": false}]}
```
（一個 job_id 只能對應一個獨立 agent_id，不得共用。WAVE/PA/Coverage 預設必須是
0/0/false；真的需要非預設值時附 "override_reason" 說明理由。）
""",
Stage.REGRESSION_MONITOR.value: """
監控 LSF jobs，區分 infrastructure failure 與 functional failure，cluster signatures，產生 report。
LSF DONE 不等於 DV PASS：DONE/EXIT 的 job 必須先分析 sim.log 才能標記 PASS/FAIL。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上：

```dv-harness-evidence:lsf_per_job_monitor_gate
{"jobs": [{"job_id": "...", "agent_id": "...", "sim_log": "<path or text>",
  "uvm_error_detected": false, "fatal_detected": false,
  "evidence_captured": true, "kill_requested": false}]}
```

```dv-harness-evidence:regression_result_uniqueness_gate
{"results": [{"testcase_id": "...", "run_id": "...", "result": "PASS",
  "log_hash": "...", "evidence_bundle_hash": "..."}]}
```

Same regression batch must use the same source/build/config identity（CLAUDE.md Core Operating
Rule）：整批 regression 的每筆 evidence 都必須回到同一個 canonical_run_id/canonical_build_hash；
混進其他 run/build 的 evidence，除非有核准的 merge（merge_approved + merge_policy_id），否則視為
不合法的 cross-run 證據。

```dv-harness-evidence:run_identity_consistency_gate
{"canonical_run_id": "...", "canonical_build_hash": "...",
 "evidence": [{"evidence_id": "...", "run_id": "...", "build_hash": "..."}]}
```

除了以上兩個既有 gate，本 stage 還有四個獨立的 hard gate，分別針對「多筆 run 之間的證據一致性」、
「flaky test 是否被誠實分類與 owner 化，而不是靠重跑蒙混過去」、「random regression 宣稱的
corner case 覆蓋是否真的靠夠多樣的 seed/config 支撐」、以及「每一筆 random run 的失敗是否都能
重現」，也都必須各自附上 evidence block：

```dv-harness-evidence:cross_run_evidence_consistency_gate
{"runs": [
  {"run_id": "...", "rtl_revision": "...", "tb_revision": "...", "vip_version": "...",
   "config_hash": "...", "testlist_hash": "...", "evidence_bundle_hash": "..."},
  {"run_id": "...", "rtl_revision": "...", "tb_revision": "...", "vip_version": "...",
   "config_hash": "...", "testlist_hash": "...", "evidence_bundle_hash": "..."}
]}
```

（`runs` 至少要有兩筆，只有一筆會直接 FAIL `NEED_AT_LEAST_TWO_RUNS`；gate 會以第一筆為 baseline，
逐筆比對 `rtl_revision`/`tb_revision`/`vip_version`/`config_hash`/`testlist_hash` 這五個欄位是否
與 baseline 完全相同，任何一筆有落差就 FAIL `RUN_CONTEXT_DRIFT`（回傳不一致的欄位名、baseline 值、
實際值與 run_id）——這正是 CLAUDE.md「同一批 regression 必須用同一個 source/build/config identity」
的直接檢查；每一筆 run 的 `evidence_bundle_hash` 都不能缺，缺了任何一筆就整批 FAIL
`RUN_WITHOUT_EVIDENCE_BUNDLE_HASH`。）

```dv-harness-evidence:flaky_test_policy_gate
{"tests": [{"testcase_id": "...", "failure_rate_percent": 0, "classified": true,
  "owner": "...", "quarantined": false, "quarantine_reason": "",
  "retry_count": 0, "max_allowed_retry": 1, "credit_allowed": false}]}
```

（`failure_rate_percent` 為 0 的測試不受任何限制；一旦 > 0（代表這個 testcase 真的觀察到 flaky
行為），就必須 `classified` 為 true（否則 FAIL `UNCLASSIFIED_FLAKY_TEST`）且 `owner` 非空
（否則 FAIL `FLAKY_TEST_WITHOUT_OWNER`）；若 `quarantined` 為 true，`quarantine_reason` 不能是
空字串（否則 FAIL `QUARANTINE_WITHOUT_REASON`）；`retry_count` 超過 `max_allowed_retry`（未填時
gate 內部視為 1）就 FAIL `EXCESSIVE_RETRY_MASKING_FAILURE`，代表不能靠瘋狂重跑把真正的失敗洗掉；
`credit_allowed` 與 `quarantined` 不能同時為 true（否則 FAIL `QUARANTINED_TEST_HAS_SIGNOFF_CREDIT`）
——已經被隔離的測試不能同時又拿到 signoff credit。本輪沒有任何 flaky test 時，附上
`{"tests": []}` 即為誠實、合法的預設值。）

```dv-harness-evidence:seed_diversity_and_corner_case_gate
{"random_corner_case_claim": false, "seeds": [], "config_hashes": [],
 "minimum_unique_seeds": 2, "minimum_unique_configs": 1, "corner_case_bins_exercised": []}
```

（只有 `random_corner_case_claim` 為 true（代表這批 regression 有主張靠 random seed 涵蓋了某些
corner case）才會觸發檢查：`seeds` 陣列去重後的數量必須 ≥ `minimum_unique_seeds`（未填時 gate
內部視為 2），否則 FAIL `INSUFFICIENT_SEED_DIVERSITY`；`config_hashes` 去重後的數量必須 ≥
`minimum_unique_configs`（未填時視為 1），否則 FAIL `INSUFFICIENT_CONFIG_DIVERSITY`；
`corner_case_bins_exercised` 不能是空/缺省，否則 FAIL `NO_CORNER_CASE_EVIDENCE`——代表宣稱涵蓋
corner case 卻拿不出真正被打中的 bin 清單。沒有主張 random corner case 覆蓋時，
`random_corner_case_claim: false` 即可直接 PASS，不需要湊 seeds/configs。）

```dv-harness-evidence:seed_reproducibility_gate
{"runs": [{"run_id": "...", "randomized": true, "seed": "12345",
  "failure": false, "reproducer_command": ""}]}
```

（跟 `cross_run_evidence_consistency_gate` 用的是同一個 `runs` 陣列概念，但欄位不同、獨立檢查：
`randomized` 為 true 的 run，`seed` 不能是 `null` 或空字串，否則 FAIL `RANDOM_RUN_WITHOUT_SEED`
——代表隨機跑但沒記下 seed，之後無法重現；`failure` 為 true 的 run，必須附上非空的
`reproducer_command`，否則 FAIL `FAILURE_WITHOUT_REPRODUCER`——每一筆失敗都要留下可以直接重跑
的指令，不能只留一句「失敗了」就結案。沒有任何 run 時 `{"runs": []}` 直接 PASS。）
""",
Stage.INFRA_RECOVERY.value: """
Regression 失敗的第一輪快速分流：判斷是 Infrastructure failure（LSF/license/compute/
工具環境問題，跟 DUT/TB 無關）還是 Functional failure（DUT/TB/VIP 真的有問題）。
Infrastructure 問題通常只需要重新提交/修環境設定，處理完直接回 Regression Select 重跑，
不需要走完整 RCA；確認是 Functional failure、或 infra 問題無法自行解決，才轉 Failure Recovery。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上：

```dv-harness-evidence:regression_infra_functional_triage_gate
{"classification": "INFRASTRUCTURE", "classification_reason": "...", "evidence_hash": "...",
 "infra_symptom": "LSF", "infra_fix_applied": true, "infra_fix_description": "...",
 "rerun_target_stage": "REGRESSION_SELECT"}
```
（若判定為 FUNCTIONAL，改附 "routed_to_failure_recovery": true 與 "failure_recovery_finding_id"。
infra_symptom 只能是 LSF/LICENSE/COMPUTE/TOOLCHAIN。）
""",
Stage.COVERAGE_CLOSURE.value: """
Coverage Closure：coverage credit 只能給真的有 active checker/scoreboard/assertion 在盯的項目，
或有核准的 waiver；不得對 active failure 的項目發 coverage credit。
有 coverage hole 時回 IMPLEMENT/Test Generation 補測試，不是硬灌 waiver。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上：

```dv-harness-evidence:coverage_signoff_verdict_gate
{"signoff_requested": true, "true_pass": true, "active_failure_count": 0,
 "coverage_credit_percent": 100, "waived_items": 0, "approved_waivers": true}
```

```dv-harness-evidence:coverage_credit_consistency_gate
{"active_failure_ids": [], "items": [{"coverage_id": "...", "credit": true,
  "active_checker_ids": ["..."], "waived": false, "linked_failure_ids": []}]}
```

```dv-harness-evidence:coverage_quality_gate
{"coverage_items": [{"coverage_id": "...", "requirement_ids": ["..."],
  "hit": true, "credit": true, "checker_ids": ["..."], "execution_evidence": ["..."]}]}
```

替 coverage hole 定 root_cause_classification 之前，先用 CornerCaseLibrary.search 查同 protocol/
category 有沒有已驗證過的既有案例可以直接沿用分類（高信心命中的定義同 SOC_SCENARIO_PLANNER
段落：status=="ACTIVE" + protocol/category 相符 + evidence.runtime_evidence_hash 非空 +
evidence.semantic_verdict 為 TRUE_PASS/TRUE_FAIL，不能只看 confidence 欄位），不必每個 hole
都從零猜測；沿用時標記 `classification_basis: "REUSED_CCL:<ccl_id>"`，自行判斷時標記
`classification_basis: "DV_JUDGMENT"`。

有 coverage hole 時，每個 hole 都要有 root_cause_classification（不是 waived 就必須分類；
MISSING_TEST/INSUFFICIENT_CONSTRAINT/UNREACHABLE_STIMULUS 這三類必須附上重新產生的
testcase 與 rerun 證據，不能只記錄分類就結案）：

```dv-harness-evidence:coverage_hole_regeneration_gate
{"coverage_holes": [{"coverage_id": "...", "waived": false,
  "root_cause_classification": "MISSING_TEST", "classification_basis": "DV_JUDGMENT",
  "regenerated_testcase_ids": ["..."], "rerun_evidence": "..."}]}
```

```dv-harness-evidence:coverage_hole_to_test_generation_gate
{"items": [{"id": "...", "covered": false, "generated_test_ids": ["..."],
  "closure_owner": "...", "trace_to_vplan": "..."}]}
```

除了以上四個之外，COVERAGE_CLOSURE 還另外掛了 10 個獨立的 hard gate，把「這個 coverage credit
給得正不正當」拆得更細——assertion 本身是不是真的有被驅動過又真的會失敗（不是恆真的死 assertion）、
checker/scoreboard/assertion 是不是真的還活著在盯、有沒有該被收回的 credit 沒收回、credit 的來源
能不能追溯、跟上一輪比有沒有異常掉點、protocol corner case/sequence 有沒有真的覆蓋到、以及最終
verdict 跟底層的 semantic/checker/negative-test/assertion/scoreboard 證據是否一致——同樣缺一個都會
卡在 GATE_FAIL/MISSING_EVIDENCE，逐一附上（找到真實案例：這 10 個 gate 在 STAGE_GATES 裡已經真的
被 harness 呼叫，但先前 stage 指示完全沒提過，導致 agent 完全不知道要附這些 evidence）：

Assertion vacuity/reachability（兩個 gate 都掃 assertions 陣列，但欄位名稱不同，必須各自照各自的
schema 填，不能共用同一份 payload）：

```dv-harness-evidence:assertion_vacuity_and_reachability_gate
{"assertions": [{"id": "...", "signoff_credit": true, "antecedent_reached": true,
  "attempt_count": 3, "negative_control_failed": true}]}
```
（只檢查 signoff_credit 為 true 的項目，其餘略過，沒有要拿來 signoff 的 assertion 時
`{"assertions": []}` 是合法預設值；signoff_credit 為 true 時：antecedent_reached 必須是
true，否則 FAIL（ASSERTION_UNREACHABLE，代表這個 assertion 的前提條件從沒被真的觸發過）；
attempt_count 必須 >0，否則 FAIL（ASSERTION_VACUOUS，代表 antecedent 從沒被嘗試過，assertion
是空跑的）；negative_control_failed 必須是 true（代表你曾經刻意讓這個 assertion 在錯誤情境下
真的失敗過一次，證明它不是恆真、真的有在檢查東西），否則 FAIL
（ASSERTION_EFFECTIVENESS_UNPROVEN）。）

```dv-harness-evidence:assertion_vacuity_gate
{"assertions": [{"assertion_id": "...", "enabled": true, "antecedent_attempts": 3,
  "unknown_xz_masked_without_justification": false}]}
```
（enabled 為 false 的項目直接略過不檢查；enabled 為 true 時：antecedent_attempts 必須 >0，
否則 FAIL（VACUOUS_ASSERTION）；unknown_xz_masked_without_justification 必須是 false，代表
沒有在沒說明理由的情況下把 X/Z unknown 值遮蔽掉，否則 FAIL
（ASSERTION_XZ_MASKING_UNJUSTIFIED，需要在 evidence 裡交代遮蔽 X/Z 的正當理由）。）

Coverage credit 的正當性/存活性/來源可追溯性/與上一輪的變化，五個 gate 都掃同一種
`items`/coverage-per-entry 的形狀，但檢查的面向各自獨立：

```dv-harness-evidence:coverage_checker_linkage_gate
{"items": [{"coverage_id": "...", "credit": true, "active_checker_ids": ["..."],
  "waived": false, "waiver_approved": false, "waiver_evidence": ""}]}
```
（credit 為 true 時，active_checker_ids/active_scoreboard_ids/active_assertion_ids 三選一
至少要有內容（代表真的有活著的 checker/scoreboard/assertion 在盯這個 coverage point），
否則要有合法 waiver（waived 且 waiver_approved 且 waiver_evidence 三者皆真）——兩者都沒有
就 FAIL（COVERAGE_CREDIT_WITHOUT_ACTIVE_CHECK_OR_VALID_WAIVER）；waived 為 true 卻缺
waiver_approved 或 waiver_evidence 任一項，FAIL（INVALID_COVERAGE_WAIVER）。）

```dv-harness-evidence:coverage_credit_revocation_gate
{"items": [{"coverage_id": "...", "credit": true, "revocation_triggers": []}]}
```
（revocation_triggers 若包含 CHECKER_DISABLED/ASSERTION_DISABLED/STALE_EVIDENCE/
FAILED_RERUN/INVALID_WAIVER/TEST_QUARANTINED 其中任一項，同時 credit 又是 true，就是
「早該收回的 credit 卻沒收回」，FAIL（COVERAGE_CREDIT_MUST_BE_REVOKED）；沒有任何觸發原因時
留空陣列 `[]` 即可。）

```dv-harness-evidence:coverage_credit_source_integrity_gate
{"items": [{"coverage_id": "...", "credit": true,
  "source": {"type": "CHECKER", "source_id": "...", "evidence_hash": "..."}}]}
```
（credit 為 false 的項目直接略過；credit 為 true 時 source.type 必須是
TEST/CHECKER/ASSERTION/SCOREBOARD/WAIVER 其中之一，否則 FAIL
（INVALID_COVERAGE_CREDIT_SOURCE）；source.source_id 與 source.evidence_hash 兩者都必須非空，
缺任一個 FAIL（COVERAGE_CREDIT_WITHOUT_PROVENANCE，代表這筆 credit 的來源無法追溯）；
source.type 為 WAIVER 時，source.approved 與 source.waiver_scope_hash 兩者都必須真，
否則 FAIL（UNAPPROVED_OR_UNSCOPED_WAIVER_CREDIT）。）

```dv-harness-evidence:coverage_failure_state_linkage_gate
{"active_failure_ids": [], "coverage_items": [{"coverage_id": "...", "credit": true,
  "linked_failure_ids": []}]}
```
（頂層 active_failure_ids 是目前還在燒的 failure id 清單；coverage_items 裡任何一筆
credit 為 true、且它的 linked_failure_ids 跟 active_failure_ids 有交集，就是「對還在燒的
功能發了 coverage credit」，FAIL（COVERAGE_CREDIT_WITH_ACTIVE_FAILURE）——這條呼應
coverage_credit_consistency_gate 已經在檢查的同一件事，但用 stage 層級的 active failure
狀態再交叉驗證一次。）

```dv-harness-evidence:coverage_regression_drift_gate
{"allowed_drop_percent": 0, "items": [{"coverage_id": "...", "previous_credit": 100,
  "current_credit": 100, "approved_drop": false}]}
```
（allowed_drop_percent 是本輪容許的最大掉點百分比門檻；每一筆 previous_credit<=0 的項目
直接跳過不檢查（代表上一輪本來就沒有額度可掉）；掉點百分比
`(previous_credit-current_credit)/previous_credit*100` 超過 allowed_drop_percent、且
approved_drop 不是 true，FAIL（COVERAGE_REGRESSION_DRIFT，代表這筆 coverage 比上一輪明顯
退步卻沒人核准這個退步）；真的有正當理由（例如上一輪的統計方式有誤、這次改了合法的排除範圍）
才把 approved_drop 設 true。）

Protocol corner case 與 sequence 這兩類「有沒有真的覆蓋到」的完整性檢查：

```dv-harness-evidence:protocol_corner_case_matrix_gate
{"required_corner_cases": [], "cases": []}
```
（required_corner_cases 是這個協定本來就該覆蓋的 corner case id 清單，沒有訂出必要 corner
case 清單時留空陣列合法；cases 裡任何一筆 covered 為 true 卻沒有 evidence 欄位，FAIL
（CORNER_COVERED_WITHOUT_EVIDENCE，代表宣稱覆蓋了卻拿不出證據）；required_corner_cases 減去
cases 裡標記 covered 的 corner_id，剩下的就是還沒覆蓋到的，非空時 FAIL
（MISSING_PROTOCOL_CORNER_CASES，並在 missing 欄位列出缺的 corner_id）。）

```dv-harness-evidence:sequence_coverage_closure_gate
{"required_sequences": [], "hit_sequences": [], "waivers": []}
```
（required_sequences 減去 hit_sequences，再減去 waivers 裡 approved 且 evidence 皆非空的
sequence，剩下的就是真正的缺口，非空時 FAIL（SEQUENCE_COVERAGE_GAP，並在 missing 欄位列出
缺的 sequence）；沒有必要 sequence 清單或全部命中時，三個欄位都留空陣列合法。）

最後，coverage credit 最終能不能真的算數，還要跟底層驗證有效性的證據一致，不能只看 verdict
本身：

```dv-harness-evidence:verification_effectiveness_consistency_gate
{"final_verdict": "PASS", "semantic_status": "TRUE_PASS", "checker_status": "PASS",
 "negative_test_effective": true, "assertion_effective": true,
 "scoreboard_independent": true, "coverage_credit_allowed": true}
```
（final_verdict 為 "PASS" 時，semantic_status 必須是 "TRUE_PASS"、checker_status 必須是
"PASS"、negative_test_effective/assertion_effective/scoreboard_independent 三者都必須是
true（不能是 false 或缺漏），只要有一項不符，FAIL
（PASS_WITH_UNPROVEN_VERIFICATION_EFFECTIVENESS，代表宣稱 PASS 卻拿不出完整的有效性證據）；
另外不論 final_verdict 為何，只要 negative_test_effective 是 false（negative test 被證明是
vacuous、沒有真的失敗過）卻同時 coverage_credit_allowed 為 true，FAIL
（COVERAGE_CREDIT_WITH_VACUOUS_NEGATIVE_TEST，代表不能拿一個空跑的 negative test 去換
coverage 額度）。）
""",
Stage.FAILURE_RECOVERY.value: """
RCA 方法：Failure Signature Extraction → First Bad Event → Expected vs Observed →
Causal Cone Analysis（分 DUT side：RTL/Reset/Clock/FSM/Data path/Register，
與 Verification side：Sequence/Driver/VIP config/Monitor/Scoreboard/Assertion/Reference model）→
Evidence Correlation → Root Cause Candidate Ranking，歸因到以下其中一類：
DUT_BUG / TB_BUG / VIP_ISSUE / TEST_ISSUE / SPEC_AMBIGUITY / INFRA_ISSUE / UNKNOWN，
或「Architecture 假設錯誤」（Observed Behavior 與 Architecture Model 不符，另外處理見下）。

DUT Bug 還是 TB Bug：沿資料流 Sequence→Driver→IF IN→DUT→IF OUT→Monitor→Checker/Scoreboard，
找出 boundary trace 上第一個 expected≠observed 的點（first bad event），依它落在哪一段判斷：
落在 SEQUENCE/DRIVER/MONITOR/CHECKER/SCOREBOARD → TB_BUG；落在 DUT_INTERNAL/IF OUT → DUT_BUG；
落在 IF IN（介面輸入邊界本身）或找不到明確 divergence → UNKNOWN，不得硬猜一邊。
單獨一個 scoreboard mismatch 不能當作 DUT bug 的證明，必須真的找到 first bad event 的位置。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上：

```dv-harness-evidence:failure_attribution
{"boundary_trace": [{"stage": "SEQUENCE", "expected": "...", "observed": "..."},
  {"stage": "DUT_INTERNAL", "expected": "...", "observed": "..."}]}
```
（stage 依訊號流順序列出，harness 會找第一個 expected≠observed 的項目並回報
TB_BUG/DUT_BUG/UNKNOWN。分類為 TB_BUG/DUT_BUG 時本 gate PASS；分類為 UNKNOWN 時本 gate
FAIL（exit 2），回傳的 JSON 會多一個 "reason": "ATTRIBUTION_UNRESOLVED_EXTEND_BOUNDARY_TRACE"，
代表 boundary trace 還不夠長，須沿因果鏈補上更多 stage 再重跑，不能把 UNKNOWN 當作已結案。
最終判斷責任仍在你，gate 只負責擋下「未解析就想蒙混過關」的情況。）

若歸因是 Architecture 假設錯誤（Observed Behavior 與 Architecture Model 不符，而不是單純功能性
bug）：先回到 Architecture Calibration 重新產生 delta + impact analysis，
更新 Architecture Model + vPlan + UVM Environment + Testcase + Checker/Coverage，
再繼續下面的一般流程；不得直接當一般 bug 修掉就了事。

先分流：BUILD/REGRESSION 失敗要先分 Infrastructure failure（LSF/license/compute/工具環境問題，
跟 DUT/TB 無關，通常只需重新提交或修環境，不需要走完整 RCA）vs Functional failure（DUT/TB/VIP 真的
有問題，才需要走下面完整的 RCA 流程）。不要把 infra 問題硬套進 functional RCA 流程處理。

Evidence 成本順序（由低到高，逐步升級，不要一開始就開 FSDB）：
sim.log → UVM_ERROR/UVM_FATAL/Assertion → Scoreboard/Checker/Transaction →
VIP Trace/Report → Targeted Extra Logging → FSDB/Waveform（最後手段，且要先問使用者 dump scope/level）。
low-cost 證據足夠定位問題就不要往下一級升級。

→ Verdi if needed → root cause →
Replay 重現 → Fix all related findings → Non-Regression 確認沒有引入新問題 →
Git push → exact SHA → build/verify/rerun。直到 failure closure。

本 stage 另外還有三個獨立的 hard gate，也必須各自附上 evidence block，缺一個都會讓整個 stage
卡在 GATE_FAIL/MISSING_EVIDENCE（同一類 bug 在 INTAKE 與 DISCOVERY 都已經真實復現過：gate
腳本有註冊，但 stage instructions 沒提到 gate id，agent 完全不知道要附證據，導致重跑多輪都停在
同樣的 GATE_FAIL/MISSING_EVIDENCE，即使實際分析內容本身已經做得很紮實）：

```dv-harness-evidence:failure_signature_recurrence_gate
{"failures": [
  {"failure_id": "...", "signature": "...", "linked_to_existing_failure": false,
   "previously_fixed": false, "recurrence_escalated": false}
]}
```
（failures 陣列中每一筆都要有 signature 這個唯一識別特徵字串——缺 signature 就 FAIL
（FAILURE_WITHOUT_SIGNATURE）；同一個 signature 在陣列中出現超過一次，代表是重複的 failure，
第二筆以後必須把 linked_to_existing_failure 設為 true，否則 FAIL
（DUPLICATE_FAILURE_NOT_LINKED）；若這個重複的 signature 屬於「先前已經修過
（previously_fixed=true）」卻又復現，必須把 recurrence_escalated 設為 true 明確升級處理，
否則 FAIL（RECURRENT_FIXED_BUG_NOT_ESCALATED）——不能讓一個號稱已修好的 bug 悄悄復發卻沒人管。
這個 stage 目前沒有處理任何 failure 時，`{"failures": []}` 是誠實、合法的預設值。）

```dv-harness-evidence:issue_triage_classification_gate
{"classification": "REAL_ISSUE", "classification_reason": "...", "evidence_hash": "...",
 "known_issue_id": null, "waiver_id": null, "prior_rca_id": null,
 "deep_rca_triggered": true, "contradictory_new_evidence": null}
```
（classification 必須是 MISCLASSIFIED/KNOWN/REAL_ISSUE/BLOCKED 四選一，其他值 FAIL
（INVALID_ISSUE_CLASSIFICATION）；classification_reason 與 evidence_hash 兩者都必須非空，
否則 FAIL（CLASSIFICATION_WITHOUT_EVIDENCE）——分類結論一定要附理由與可追溯的證據雜湊，不能
空口分類；classification 為 KNOWN 時，known_issue_id / waiver_id / prior_rca_id 三者至少填一個，
否則 FAIL（KNOWN_WITHOUT_REFERENCE）；classification 為 REAL_ISSUE 時 deep_rca_triggered 必須是
true，否則 FAIL（REAL_ISSUE_WITHOUT_DEEP_RCA）——真正的新問題一定要觸發完整 RCA；反過來，
classification 為 MISCLASSIFIED 或 KNOWN 卻同時 deep_rca_triggered 為 true，就必須附上非空的
contradictory_new_evidence 說明為什麼已知/誤判還要重跑一次深入 RCA，否則 FAIL
（UNNECESSARY_DEEP_RCA）——不能對已有結論的 issue 做多餘的重複分析。）

```dv-harness-evidence:unknown_failure_escalation_gate
{"classification": "UNKNOWN", "missing_evidence": "...", "next_evidence_actions": "...",
 "owner": "...", "blocking_scope": "...", "promotion_allowed": false}
```
（這個 gate 只在 classification 是 "UNKNOWN" 時才會真的檢查——非 UNKNOWN 時直接 PASS
（CLASSIFIED），代表這個 evidence block 只有在真的分不出 root cause 時才需要認真填；一旦
classification 是 UNKNOWN，missing_evidence、next_evidence_actions、owner、blocking_scope
四個欄位都必須非空，缺任一個都會 FAIL（UNKNOWN_WITHOUT_ESCALATION_PLAN，並列出缺了哪些欄位）
——「不知道」不能就這樣放著，一定要說清楚缺什麼證據、下一步要做什麼、誰負責、影響範圍多大；
即使四個欄位都填了，只要 promotion_allowed 是 true 也會 FAIL
（UNKNOWN_FAILURE_CANNOT_PROMOTE）——未分類的 failure 絕對不能被放行往下一階段推進；四者都
滿足且 promotion_allowed 不是 true 時，gate 回報狀態是 BLOCKED_PENDING_EVIDENCE，代表這個
failure 被合法卡住等新證據，不是 stage 本身失敗。）
""",
Stage.RE_AUDIT.value: """
重新執行 original workflow audit，確認原 findings closed 且沒有新增 actionable issue。
若有新 issue，加入 finding registry 並回 IMPLEMENT。

Autonomous Inference（對應 .dv-harness/inference/inference_policy.json，這份政策先前從未被
引用過，現在正式生效）：每個 failure 先產生多個候選假設 H1/H2/H3/...，每個假設都要有
supporting_evidence 與 counter_evidence，並參考 Historical Memory Prior（memory 只是
prior，不能取代 current evidence）重新用 current evidence 驗證，才能更新 confidence。
confidence 到 HIGH/CONFIRMED 才能採用，且高風險改動一律需要 current_evidence + change_impact +
review/approval，memory prior 本身不夠。若證據仍不足以在候選假設間辨別，記錄 evidence gap，
決定 next-best-action（依 information gain / root cause 辨別力 / verification value /
runtime cost / compute cost / change risk 排序），不得卡住不動也不得亂猜一個下去做。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上：

```dv-harness-evidence:root_cause_evidence_gate
{"symptom": "...", "first_bad_event": "...", "causal_chain": "...",
 "root_cause": "H2 的 claim 原文，必須逐字等於下面 hypotheses 陣列中被選定那筆的 claim",
 "supporting_evidence": "...", "counter_evidence": "...",
 "confidence": "MEDIUM",
 "hypotheses": [
   {"claim": "H1 ...", "category": "DUT_BUG|TB_BUG|VIP_ISSUE|TEST_ISSUE|SPEC_AMBIGUITY|INFRA_ISSUE",
    "supporting_evidence": "...", "counter_evidence": "已排除的理由與證據",
    "missing_evidence": "...", "confidence": "LOW", "next_action": "..."},
   {"claim": "H2 的 claim 原文，必須逐字等於上面 root_cause", "category": "...",
    "supporting_evidence": "...", "counter_evidence": "",
    "missing_evidence": "...", "confidence": "MEDIUM", "next_action": "..."}
 ]}
```
（confidence 為 HIGH/CONFIRMED 時 counter_evidence 必填，代表你已主動找過反證。hypotheses 至少要有
2 筆，欄位對應 .dv-harness/inference/inference_policy.json 的 hypothesis_fields/confidence_levels
（gate 會即時讀取該檔案，不是寫死清單）：root_cause 必須逐字等於其中一筆 claim（代表你確實選定了
某個候選假設，而不是憑空寫一個 root_cause），且除了被選定那筆以外，至少要有另一筆的
counter_evidence 非空（代表你真的產生過並排除過至少一個替代假設，不只是宣稱有考慮過）。若這次
finding 明確判斷不需要多假設（例如單一、無歧義的低風險 typo），改為附上
{"trivial_finding": true, "trivial_finding_justification": "..."} 取代 hypotheses 陣列，
說明為何不存在需要排除的替代解釋；trivial_finding 為 false 或缺省時仍套用上述 hypotheses 規則。）

若本次有走過 Failure Recovery 的 RCA/Fix/Replay 迴圈，額外附上：

```dv-harness-evidence:rca_replay_fix_closure_gate
{"rca_id": "...", "attribution": "DUT_BUG|TB_BUG|VIP_ISSUE|TEST_ISSUE|SPEC_AMBIGUITY|INFRA_ISSUE", "reproducer_hash": "...",
 "fix_commit_hash": "...", "rerun_evidence_hash": "...",
 "replay_equivalent": true, "pre_fix_result": "FAIL", "post_fix_result": "PASS",
 "attribution_confidence": "HIGH",
 "boundary_trace": [{"stage": "SEQUENCE", "expected": "...", "observed": "..."}]}
```
（boundary_trace 為選填欄位，格式與 failure_attribution 相同；若附上，gate 會用同一套規則
獨立重新推導分類。若推導結果是 TB_BUG/DUT_BUG，attribution 欄位必須與推導結果完全一致，
否則 FAIL（exit 6，reason: "ATTRIBUTION_CONTRADICTS_BOUNDARY_TRACE"，並回傳 derived_classification
與 stated_attribution 供比對）；若推導結果是 UNKNOWN，attribution 不受此限制（VIP_ISSUE/
TEST_ISSUE/SPEC_AMBIGUITY/INFRA_ISSUE 這類單靠 boundary trace 無法排除的分類仍可使用）。
不附 boundary_trace 時行為與舊版完全相同。）

Deep RCA / Attribution 強化（deep_rca_evidence_gate、rca_confidence_escalation_gate、
root_cause_attribution_consistency_gate、nondeterminism_attribution_gate）：RE_AUDIT 的根因
分析不能只靠上面 root_cause_evidence_gate 那組 hypotheses，還要能證明「查過哪些真實證據來源」、
confidence 的升級路徑站得住腳、跟其他 gate 一致的 attribution 分類，以及對不穩定
（non-deterministic）failure 有獨立的歸屬判斷。四個 gate 分別從不同角度檢查同一份 RCA：

```dv-harness-evidence:deep_rca_evidence_gate
{"first_bad_event": "...", "causal_chain": ["...", "..."],
 "confidence": "HIGH",
 "evidence_sources": [
   {"source": "SIM_LOG", "checked": true, "evidence_hash": "..."},
   {"source": "TRACE", "checked": true, "evidence_hash": "..."},
   {"source": "RTL", "checked": true, "evidence_hash": "..."},
   {"source": "TESTBENCH", "checked": true, "evidence_hash": "..."},
   {"source": "COMMAND", "checked": true, "evidence_hash": "..."},
   {"source": "SCOREBOARD", "checked": true, "evidence_hash": "..."},
   {"source": "PHY_MODEL", "checked": true, "evidence_hash": "..."},
   {"source": "STANDARD_SPEC", "checked": true, "evidence_hash": "..."},
   {"source": "VIP_EXAMPLE", "checked": true, "evidence_hash": "..."},
   {"source": "VIP_SOURCE", "checked": true, "evidence_hash": "..."},
   {"source": "VIP_DOCUMENT", "checked": true, "evidence_hash": "..."}
 ]}
```
（`evidence_sources` 裡必須湊齊固定 11 種來源——SIM_LOG/TRACE/RTL/TESTBENCH/COMMAND/
SCOREBOARD/PHY_MODEL/STANDARD_SPEC/VIP_EXAMPLE/VIP_SOURCE/VIP_DOCUMENT——每一種都要
`checked:true` 且 `evidence_hash` 非空，缺一種就 FAIL DEEP_RCA_EVIDENCE_INCOMPLETE 並列出缺的
來源；`first_bad_event` 不得空白；`causal_chain` 至少要 2 個節點，代表真的有推導出因果鏈而
不是只給結論；`confidence` 只接受 HIGH/VERIFIED/BLOCKED 三種——LOW/MEDIUM 在這個 gate 視為
「還沒查完」而直接 FAIL；填 BLOCKED 時必須同時附 `missing_evidence` 與 `next_action`，說明卡在
哪、下一步要做什麼，不能只寫 BLOCKED 就不了了之。）

```dv-harness-evidence:rca_confidence_escalation_gate
{"confidence": "HIGH", "first_bad_event": "...", "causal_chain": ["...", "..."],
 "supporting_evidence": "...", "counter_evidence": "...",
 "fix_effectiveness_evidence": "...", "promotion_requested": false}
```
（`confidence` 必須是 LOW/MEDIUM/HIGH/VERIFIED 之一；不論等級為何，`first_bad_event`/
`causal_chain`/`supporting_evidence` 都是必填，缺任一項直接 FAIL RCA_EVIDENCE_INCOMPLETE。
`confidence` 為 HIGH 或 VERIFIED 時 `counter_evidence` 必填（代表你真的主動找過反證，不是單方面
只講支持證據）；`confidence` 為 VERIFIED 時還要再附 `fix_effectiveness_evidence`（代表這個 RCA
已經用「修了之後 fix 真的有效」的證據回頭驗證過，不是只憑分析推論）。若這筆 RCA 打算被
`promotion_requested:true` 拿去沉澱進 Verification Memory，`confidence` 至少要到 HIGH，MEDIUM/LOW
一律 FAIL RCA_CONFIDENCE_TOO_LOW_FOR_PROMOTION。）

```dv-harness-evidence:root_cause_attribution_consistency_gate
{"attribution": "DUT", "attribution_confidence": "HIGH",
 "first_bad_event": "...", "causal_chain": ["...", "..."],
 "supporting_evidence": "...", "counter_evidence": "...",
 "promotion_requested": false}
```
（`attribution` 只接受 DUT/TB/VIP/TOOL/INFRA/SPEC/UNKNOWN。填 UNKNOWN 時，若
`promotion_requested:true` 會直接 FAIL UNKNOWN_RCA_CANNOT_PROMOTE（歸屬未定的 RCA 不得拿去
promote）；不 promotion 的話 UNKNOWN 本身可以 PASS（視為 UNKNOWN_BLOCKED，代表誠實承認暫時無法
歸屬，比亂猜一個分類更安全），此時不再要求其餘欄位。非 UNKNOWN 的分類則必須補齊
`first_bad_event`/`causal_chain`/`supporting_evidence`/`counter_evidence` 四項因果證據（缺任一項
FAIL RCA_ATTRIBUTION_WITHOUT_CAUSAL_EVIDENCE），且 `attribution_confidence` 必須是
HIGH 或 VERIFIED，否則 FAIL ATTRIBUTION_CONFIDENCE_TOO_LOW。）

```dv-harness-evidence:nondeterminism_attribution_gate
{"deterministic": false, "attribution": "DUT",
 "first_divergence": "...", "supporting_evidence": "...", "counter_evidence": "...",
 "reproduction_matrix_hash": "..."}
```
（若這次 failure 其實是可重現、非 flaky 的，直接填 `deterministic:true` 即可 PASS，其餘欄位不看
——只在真的確認是 non-deterministic/flaky 的 failure 時才需要走完整套歸屬流程。
`deterministic` 非 true 時，`attribution` 只接受 DUT/TB/VIP/TOOL/ENVIRONMENT/UNKNOWN；填
UNKNOWN 一律直接 FAIL UNRESOLVED_NONDETERMINISM（跟上面 attribution 系列 gate 不同，
non-determinism 的歸屬不允許用 UNKNOWN 卡住不動）。非 UNKNOWN 時必須補齊
`first_divergence`（第一個出現分歧的點）、`supporting_evidence`、`counter_evidence`、
`reproduction_matrix_hash`（多次重跑/多 seed 的重現矩陣證據）四項，缺任一項 FAIL
NONDETERMINISM_ATTRIBUTION_WITHOUT_EVIDENCE。）

Fix 生命週期閉環（dut_request_record_gate、fix_risk_approval_gate、fix_effectiveness_gate、
fix_regression_non_regression_gate、regression_replay_equivalence_gate）：如果這輪 RE_AUDIT
判定是 DUT 端的 REAL_ISSUE 並且真的要送出修改，從「建立 DUT request 記錄」、「風險核准」、
「修完之後證明真的有效」、「沒有引入新的 regression」到「重跑結果跟原始 run 逐項等價可比對」，
每一段都要各自附證據，不能只靠前面的 root_cause_evidence_gate 蓋過去：

```dv-harness-evidence:dut_request_record_gate
{"dut_request_path": "generated/.../dut-request.md", "issue_id": "...",
 "classification": "REAL_ISSUE", "root_cause": "...", "fix_summary": "...",
 "risk_summary": "...", "verification_result": "...", "change_hash": "..."}
```
（`dut_request_path`/`issue_id`/`classification`/`root_cause`/`fix_summary`/`risk_summary`/
`verification_result`/`change_hash` 八個欄位缺一都會 FAIL INCOMPLETE_DUT_REQUEST_RECORD 並回報
是哪個欄位；`dut_request_path` 的檔名（basename）必須逐字是 `dut-request.md`，否則 FAIL
DUT_REQUEST_WRONG_FILENAME；`classification` 必須逐字等於 `REAL_ISSUE` 才能建立這筆 fix
record，否則 FAIL ONLY_REAL_ISSUE_CAN_CREATE_FIX_RECORD——代表這個 gate 只給「確認是真的 DUT
問題」的情況用，誤報/非真實 issue 不該走到這裡。）

```dv-harness-evidence:fix_risk_approval_gate
{"root_cause_id": "...", "fix_plan": "...", "risk_assessment": "...",
 "affected_scope": "...", "regression_plan": "...", "rollback_plan": "...",
 "root_cause_confidence": "HIGH", "risk_level": "MEDIUM",
 "high_risk_reviewed": false, "approved_for_modify": true}
```
（`root_cause_id`/`fix_plan`/`risk_assessment`/`affected_scope`/`regression_plan`/
`rollback_plan` 六個欄位缺一都會 FAIL INCOMPLETE_FIX_RISK_PLAN 並回報欄位名；
`root_cause_confidence` 必須是 HIGH 或 VERIFIED，否則 FAIL FIX_WITHOUT_HIGH_CONFIDENCE_RCA
（confidence 不夠高不准送修）；`risk_level` 為 `HIGH` 時 `high_risk_reviewed` 必須是
true，否則 FAIL HIGH_RISK_FIX_NOT_REVIEWED；最後 `approved_for_modify` 必須明確為
true 才代表這個修改計畫真的被核准可以動手，否則 FAIL FIX_NOT_APPROVED_FOR_MODIFICATION。）

```dv-harness-evidence:fix_effectiveness_gate
{"failure_signature_before": "...", "failure_signature_after": "...",
 "root_cause_id": "...", "fix_revision": "...", "rerun_evidence": "...",
 "targeted_reproducer_passed": true, "broader_regression_passed": true,
 "new_failures_introduced": false}
```
（`failure_signature_before`/`root_cause_id`/`fix_revision`/`rerun_evidence` 四項缺一即 FAIL
MISSING_FIELDS；`failure_signature_after` 必須跟 `failure_signature_before` 不同，代表 failure
signature 真的變了而不是同一個 failure 換句話說（否則 FAIL FAILURE_SIGNATURE_PERSISTS）；
`targeted_reproducer_passed` 與 `broader_regression_passed` 都必須是 true，分別代表原本會炸的
reproducer 現在過了、以及更廣的 regression 也沒被這個 fix 拖垮（缺一即 FAIL
TARGETED_REPRODUCER_NOT_PASS / BROADER_REGRESSION_NOT_PASS）；`new_failures_introduced` 必須是
false/未填，一旦為 true 直接 FAIL FIX_INTRODUCED_NEW_FAILURES。）

```dv-harness-evidence:fix_regression_non_regression_gate
{"target_pre_fix_result": "FAIL", "target_post_fix_result": "PASS",
 "replay_equivalent": true,
 "critical_non_regression_tests": [
   {"testcase_id": "...", "pre_fix_result": "PASS", "post_fix_result": "PASS",
    "evidence_hash": "..."}
 ],
 "fix_commit_hash": "...", "rerun_bundle_hash": "..."}
```
（`target_pre_fix_result` 必須是 `FAIL` 且 `target_post_fix_result` 必須是 `PASS`，證明這個
target 真的是修完才過（否則 FAIL TARGET_FIX_NOT_PROVEN）；`replay_equivalent` 必須是 true
（否則 FAIL TARGET_RERUN_NOT_EQUIVALENT）；`critical_non_regression_tests` 清單中每一筆若
`pre_fix_result` 是 PASS，`post_fix_result` 就必須也是 PASS，否則 FAIL FIX_CAUSED_REGRESSION
並附上是哪個 testcase_id；這種「修前就過」的 testcase 還必須附 `evidence_hash`，否則 FAIL
NON_REGRESSION_WITHOUT_EVIDENCE；最後 `fix_commit_hash` 與 `rerun_bundle_hash` 都是必填，
缺一即 FAIL FIX_CLOSURE_WITHOUT_ARTIFACT_HASH。）

```dv-harness-evidence:regression_replay_equivalence_gate
{"original": {"testcase_id": "...", "seed": "...", "config_hash": "...",
   "build_hash": "...", "artifact_hash": "...", "command_hash": "...", "result": "FAIL"},
 "replay": {"testcase_id": "...", "seed": "...", "config_hash": "...",
   "build_hash": "...", "artifact_hash": "...", "command_hash": "...", "result": "FAIL"}}
```
（`original` 與 `replay` 兩邊必須在 `testcase_id`/`seed`/`config_hash`/`build_hash`/
`artifact_hash`/`command_hash` 六個識別欄位上逐一相同，任何一項不一致就 FAIL
REPLAY_NOT_EQUIVALENT 並列出不一致的欄位與兩邊的值——代表 replay 用的是同一顆 build、同一組
config、同一個 command，不是拿另一個環境的結果魚目混珠；六項都一致之後，還要求兩邊的
`result` 也相同，否則 FAIL NON_REPRODUCIBLE_RESULT，代表同樣的身份重跑卻得到不同結果，
本身就是需要交給上面 nondeterminism_attribution_gate 處理的訊號。）
""",
Stage.SYSTEM_LEVEL.value: """
System-Level：確認 system-level verdict 不會用整體 PASS 蓋掉個別 subsystem 的 FAIL
（除非該 subsystem 有 isolated + approved waiver）。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上：

```dv-harness-evidence:system_level_subsystem_verdict_gate
{"system_verdict": "PASS", "subsystems": [{"name": "...", "verdict": "PASS",
  "isolated": false, "approved_waiver_id": null}]}
```

```dv-harness-evidence:system_level_traceability_gate
{"selected_subsystems": ["...", "..."], "system_requirement_ids": ["..."],
 "scenarios": [{"scenario_id": "...", "participating_subsystems": ["...", "..."],
   "system_requirement_ids": ["..."], "mechanism_ids": ["..."], "coverage_ids": ["..."]}]}
```

```dv-harness-evidence:system_level_validator
{"registry": {"subsystems": [{"name": "...", "environment_manifest": "...", "release_sha": "...",
  "qualification_state": "SMOKE_QUALIFIED|REGRESSION_QUALIFIED|PRODUCTION_QUALIFIED",
  "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS"}]}}
```
（`registry` 這層包裝是必要的：這個 gate 現在會額外把每個列出的 `name`/`release_sha`
拿去跟真正的 `.dv-harness/soc-composer/subsystem_environment_registry.json`
比對——這份檔案只會在某個 subsystem 真的走完 SIGNOFF 並通過
`subsystem_environment_registration_gate` 之後，由 harness 自己寫入，不接受
agent 憑空宣稱。列出一個從未真正 SIGNOFF 過的 subsystem 會直接 FAIL
`SUBSYSTEM_NOT_REGISTERED`；`release_sha` 跟已登記的不一致會 FAIL
`SUBSYSTEM_RELEASE_SHA_MISMATCH`。）

Subsystem-Set Completeness Hard Gate：以上三個 gate 都只檢查「已經被選進來的
subsystem/scenario」內部有沒有問題，沒有一個檢查「這次 system-level 組裝的
subsystem 集合本身夠不夠完整」——一個 DUT 實際存在的 subsystem 有可能整個
沒被放進 selected_subsystems，三個既有 gate 都不會發現。這裡要求先列出
「這顆 DUT 實際包含哪些 subsystem」（required_subsystems，依實際證據而定，
不是套用固定清單），每一個都必須出現在 selected_subsystems 中（或有明確
per-subsystem waiver：status=WAIVED/NOT_APPLICABLE + waiver_approved +
waiver_evidence），而且每一個未 waive 的 required subsystem 都必須在至少
一個 system-level scenario 中真的參與（只是被列在 selected 清單裡、卻沒有
出現在任何 scenario 中，一樣算未完成）。非 multi-subsystem system-level
組裝（例如純 IP-level 專案，本來就不會走到真正的 SYSTEM_LEVEL 組裝）需明確
填 system_level_applicable=false 並附理由，不得省略此區塊。

```dv-harness-evidence:system_level_subsystem_set_completeness_gate
{"required_subsystems": ["USB", "PCIE", "ETHERNET", "CANFD"],
 "selected_subsystems": ["USB", "PCIE", "ETHERNET", "CANFD"],
 "subsystem_waivers": [],
 "subsystem_scenario_participation": [
   {"scenario_id": "SC1", "participating_subsystems": ["USB", "PCIE"]},
   {"scenario_id": "SC2", "participating_subsystems": ["ETHERNET", "PCIE"]},
   {"scenario_id": "SC3", "participating_subsystems": ["CANFD", "USB"]}
 ]}
```
（若某個 required subsystem 這顆 SKU 上不適用或本輪明確不驗，改在
subsystem_waivers 附上
`{"subsystem": "...", "status": "WAIVED"|"NOT_APPLICABLE", "waiver_approved": true, "waiver_evidence": "..."}`；
非 multi-subsystem system-level 組裝改附
`{"system_level_applicable": false, "system_level_not_applicable_reason": "..."}`。）
""",
Stage.EXPERT_FEEDBACK_LOOP.value: """
DV Expert Feedback Closed Loop：把本輪 AI Analyze/Generate/Verify 的產出交給人類 DV 專家
Review & Scan，蒐集 finding/suggestion（分類：Missing Scenario、Missing Checker、Coverage Gap、
Wrong Assumption、DUT/VIP Binding Issue、Protocol Knowledge Gap、Performance Scenario、
Corner Case、Verification Strategy）。

Evidence Validation（使用者原始分類 → 對應到 harness gate 的 disposition）：
- ACCEPT → disposition=ACCEPTED（要有 action_id + closure_evidence_hash）。
- MODIFY → disposition=ACCEPTED（action_id 描述修改內容，closure_evidence_hash 為修改後的證據）。
- REJECT → disposition=REJECTED（要有 counter_evidence_hash，說明為何不採納）。
- NEED MORE EVIDENCE → disposition=DEFERRED（要有 tracking_issue_id，之後補證據再覆核）。

若 ACCEPT/MODIFY 的 finding 需要實際改動（Spec Model/vPlan/UVM ENV/Sequence/
Checker-Scoreboard/Assertion/Coverage/Test-Regression/System-Level Scenario 任一項），
先做 Impact Analysis 再 Auto Patch/Regenerate，並回到 CHANGE_IMPACT/IMPLEMENT 重跑
Compile→Smoke→Regression，產生新 evidence 後再回來做 DV Expert Re-review，
不得只記錄 disposition 就直接結案。

若這輪 finding 分類是 Corner Case 且已經走完 Fix/Replay 並拿到 runtime evidence（semantic_verdict
為 TRUE_PASS 或 TRUE_FAIL），呼叫 `route_and_store` 傳入
`{"kind": "corner_case", "verified": true, "corner_case": {...}, "resolution": {"test_mapping": ...,
"semantic_verdict": ..., "runtime_evidence_hash": ...}}` 把它沉澱進 Corner-case Library，
之後 SOC_SCENARIO_PLANNER/COVERAGE_CLOSURE 才能直接查到重用，不必每次都靠 DV 專家重新分級。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上：

```dv-harness-evidence:expert_feedback_closure_gate
{"items": [{"feedback_id": "...", "disposition": "ACCEPTED", "expert_id": "...",
  "rationale": "...", "action_id": "...", "closure_evidence_hash": "..."}]}
```

Experience Learning Loop：本輪若沉澱出可跨案重用的工程知識（不是單一 finding 的 disposition，
而是「這一類問題長什麼樣、根因是什麼、什麼條件下適用」），才產生 EXPERIENCE_READY 事件，
交給 harness 判斷是否可 promote 進 Verification Memory：

```dv-harness-evidence:experience_knowledge_gate
{"knowledge_id": "...", "title": "...", "pattern": "...", "root_cause": "...",
 "evidence": "...", "applicability_constraints": "...", "expert_approved": true}
```
（expert_approved 必須是人類 DV 專家確認過，不是 agent 自我核准；applicability_constraints
要講清楚這個知識在什麼前提下才適用，不寫清楚就不得 promote，避免下次被錯誤套用到不適用的情境。）

若這次 EXPERT_FEEDBACK_LOOP 打算沿用既有的 Verification Memory/知識庫記錄（不是這輪才
新產生的 experience_knowledge_gate 記錄），必須先證明「該記錄的適用前提」跟「這次的實際
情境」相符，不能只因為分類相同就套用：

```dv-harness-evidence:experience_applicability_gate
{"knowledge": {"knowledge_id": "...", "expert_approved": true, "evidence": "...",
  "applicability_constraints": {"protocol": "...", "mode": "..."}},
 "context": {"protocol": "...", "mode": "..."}}
```
（"knowledge" 是你打算沿用的那筆記錄本身（expert_approved/evidence 缺一都會直接 FAIL
KNOWLEDGE_NOT_QUALIFIED）；"context" 是這次任務的實際情境。applicability_constraints
裡的每個欄位都會拿去跟 context 同名欄位逐一比對，任何一個對不上就是
NOT_APPLICABLE——不得因為「大方向類似」就強行沿用不符合前提的知識。）
""",
Stage.REQUIREMENT_CLOSURE.value: """
Evidence/Run/Build/Waiver/Feature Audit：每個 requirement 都要有明確的 Requirement Status ——
VERIFIED（有 runtime evidence，semantic_verdict=TRUE_PASS）、WAIVED（design_evidence 佐證）、
NOT_APPLICABLE（DUT 不支援且已記錄依據）、或 GAP（尚未有結論，不得放著不管）。
100% spec coverage accounting：不得有 requirement 完全沒有上述四種狀態之一。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上：

```dv-harness-evidence:requirement_runtime_evidence_gate
{"requirements": [{"requirement_id": "...", "testcase_id": "...", "run_id": "...",
  "runtime_evidence_hash": "...", "semantic_verdict": "TRUE_PASS", "status": "CLOSED"}]}
```

```dv-harness-evidence:master_requirement_completeness_gate
{"requirements": [{"requirement_id": "STEP_BY_STEP_INTERACTIVE", "implemented": true,
  "pytest_evidence": true, "hard_gate": true}]}
```
（master_requirement_completeness_gate 檢查的是本專案固定的 27 個能力項目是否都有
implemented+pytest_evidence+hard_gate 三個條件；缺的會列在 FAIL 的 missing 清單裡。）

```dv-harness-evidence:execution_evidence_gate
{"requirements": [{"req_id": "...", "status": "VERIFIED",
  "execution_evidence": ["..."], "mechanism_ids": ["..."]}]}
```
（每個 requirement 的 status 只能是 VERIFIED（要有 execution_evidence + mechanism_ids）、
WAIVED（要有 support_status=UNSUPPORTED_BY_DUT + waiver.approved + waiver.evidence）、
或 NOT_APPLICABLE（要有 not_applicable_evidence）三選一，不得留白。）

```dv-harness-evidence:traceability_audit
{"vplan": {"requirements": [{"req_id": "..."}]},
 "tests": {"testcases": [{"testcase_id": "...", "vplan_requirement_ids": ["..."]}]}}
```
（每個 testcase 的 vplan_requirement_ids 都要能對到 "vplan" 裡真實存在的 req_id，
且不能是空陣列——沒有任何 requirement id 或引用了 vPlan 裡不存在的 requirement，
都會被列進 orphan_testcases 而 FAIL，這是 requirement→testcase 反向追溯的完整性
檢查，跟上面 requirement_runtime_evidence_gate 的正向追溯是同一條追溯鏈的兩端。）
""",
Stage.PROMOTION_READINESS.value: """
Promotion Readiness：確認所有 critical dimension 沒有 BLOCKED/UNKNOWN/FAIL/INCOMPLETE，
沒有 active failure，signoff bundle 完整且 evidence 新鮮（不是拿舊的 revision 湊數）。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上：

```dv-harness-evidence:promotion_readiness_gate
{"critical_dimensions": {"coverage": "READY", "regression": "READY"},
 "active_failure_count": 0, "signoff_bundle_complete": true, "evidence_fresh": true}
```

```dv-harness-evidence:promotion_chain_audit_gate
{"failure_detected": false, "events": [
  {"stage": "INTAKE_READY", "evidence": "..."},
  {"stage": "VPLAN_READY", "evidence": "..."},
  {"stage": "ARCHITECTURE_READY", "evidence": "..."},
  {"stage": "MECHANISM_READY", "evidence": "..."},
  {"stage": "TESTS_READY", "evidence": "..."},
  {"stage": "TRACEABILITY_READY", "evidence": "..."},
  {"stage": "EXECUTION_EVIDENCE_READY", "evidence": "..."},
  {"stage": "COVERAGE_QUALITY_READY", "evidence": "..."},
  {"stage": "EXPERT_REVIEW_READY", "evidence": "..."},
  {"stage": "EXPERIENCE_READY", "evidence": "..."},
  {"stage": "PROMOTABLE", "evidence": "..."}]}
```

Feature Continuity（跨 package revision 的既有能力/檔案不能在這次 promotion 悄悄消失）：

```dv-harness-evidence:feature_continuity_gate
{"required": {"required_paths": ["path/relative/to/repo/root/one", "path/two"]}}
```
（"required_paths" 是這個 revision 仍然必須存在的檔案/路徑清單（相對這個專案的
repo root）；真正的 repo root 由 harness 自己帶入 --root，不接受你在 block 裡另外
指定，避免路徑被導向別處而繞過檢查。任何一個路徑在目前的 repo 裡找不到，就會
FAIL FEATURE_CONTINUITY_REGRESSION，列出缺的路徑。）
""",
Stage.SIGNOFF.value: """
執行 final review/signoff gate。只有 CLOSED/BLOCKED/ACCEPTED_RISK 可結束。

本 stage 的 PASS 由 harness 端 gate 腳本裁定。回覆結尾附上：

```dv-harness-evidence:false_pass_resistance_gate
{"positive_test_pass": true, "negative_test_detects_fault": true,
 "checker_detects_injected_fault": true, "semantic_log_match": true,
 "oracle_independent": true, "proof_bundle_hash": "..."}
```

```dv-harness-evidence:signoff_bundle_completeness_gate
{"evidence": [{"class": "SPEC_TRACE", "hash": "..."}, {"class": "BUILD", "hash": "..."},
  {"class": "TEST", "hash": "..."}, {"class": "ASSERTION", "hash": "..."},
  {"class": "SCOREBOARD", "hash": "..."}, {"class": "COVERAGE", "hash": "..."},
  {"class": "REGRESSION", "hash": "..."}, {"class": "RCA_FIX", "hash": "..."},
  {"class": "ENV_FINGERPRINT", "hash": "..."}],
 "bundle_dir": "<真實 `dv-harness signoff-export --out <dir>` 寫出的 out_dir>",
 "bundle_hash": "...", "final_verdict": "PASS"}
```
（"bundle_dir" 必須是真的執行過 signoff-export 之後、real manifest.json 所在的
那個目錄——gate 會實際讀那份 manifest.json、用
dv_harness/signoff_export.py 的 compute_bundle_hash() 重新算一次，"bundle_hash"
必須跟這個真實重算出來的值完全一致，不是自己隨便填一個字串；同時
manifest.json 裡也必須看得到 self_audit_result 這筆 present:true，證明
bundle_dir 真的是 signoff-export 的輸出，不是隨手放一個假的 manifest.json 進去。）

若這次 SIGNOFF 是一個獨立 subsystem 驗證環境完成（可被之後 SYSTEM_LEVEL 組裝重複使用），
必須附上這個環境的登記資訊；若這次 SIGNOFF 是一次 full-SoC/system-level 驗證、
或這個 subsystem 之前已經登記過、本輪沒有新的環境要登記，改附
`registration_applicable=false` 並附理由，不得省略此區塊：

```dv-harness-evidence:subsystem_environment_registration_gate
{"name": "USB", "environment_manifest": "generated/.../environment_manifest.json",
 "release_sha": "...", "qualification_state": "SMOKE_QUALIFIED|REGRESSION_QUALIFIED|PRODUCTION_QUALIFIED",
 "interface_compatibility": "PASS", "clock_reset_compatibility": "PASS"}
```
（`interface_compatibility`/`clock_reset_compatibility` 必須是這次 SIGNOFF 真的驗證過的結果，
不是預設帶入 PASS；PASS 之後這筆資料會被 harness 寫入
`.dv-harness/soc-composer/subsystem_environment_registry.json`，之後 SYSTEM_LEVEL 階段的
`system_level_validator` 會拿真正登記過的內容跟 SYSTEM_LEVEL 組裝時的宣稱互相比對，
不接受 SYSTEM_LEVEL 階段憑空宣稱某個 subsystem「已經 ready」。）
"""
}

def build_stage_prompt(stage: str, state_summary: str, user_goal: str,
                        constraints: list | None = None,
                        correction_note: str | None = None,
                        human_approval: dict | None = None,
                        relevant_memory: list | None = None) -> str:
    """Purely additive over the pre-control-plane signature: called with
    only the original 3 positional args (constraints/correction_note/
    human_approval/relevant_memory all default None), the returned prompt is
    byte-identical to before -- see test_de_explainer_is_additive_and_does_not_change_agent_prompt
    and the control-plane tests that check the None-default path explicitly.

    relevant_memory (Task 9, 2026-08-31 poster-gap-closing round 2): an
    optional list of Memory-tier records (dv_harness.memory.MemoryRetriever.
    search()'s own "memory" payloads, e.g. from engine.run_stage()) --
    surfaced to the agent as prior knowledge to consider, never as current
    evidence (CLAUDE.md's Evidence Truth Rule/"Memory is prior knowledge,
    not current evidence" applies here exactly as it does to `human_approval`
    above). A falsy value (None or []) leaves the prompt unchanged, same as
    every other additive kwarg here.

    engine.DVHarness.run_stage() is the one caller that passes all four
    extra kwargs: constraints/correction_note/human_approval are sourced
    from control_plane.ControlPlane.load() for the CURRENT stage;
    relevant_memory is sourced from a fresh MemoryRetriever.search() call
    against this project's own Memory tiers (see relevant_memory above) --
    a separate subsystem, not control-plane state.
    - constraints: every active CONSTRAINT (`dv-harness constraint --add`),
      folded into every subsequent stage prompt until removed.
    - correction_note: an active CORRECT (`dv-harness correct <stage>
      --note ...`) for exactly this stage; cleared (consumed) once the stage
      next reaches PASS/NO_GATE_REQUIRED.
    - human_approval: an APPROVE record for this stage, if any -- handed to
      the agent so that IF it separately chooses to wrap a Tier-5 DV-review
      co-sign field ({"value":...,"reviewer_id":...,"reviewer_confidence":...},
      see gates.JUDGMENT_FIELDS), it has the human's real reviewer_id/
      reviewer_confidence available to reuse instead of inventing one.

      CORRECTION (2026-08-28, wq5whmpdv adversarial verify -- an earlier
      version of this docstring claimed these were "the one real mechanism,
      not a second parallel approval concept"; that was false, confirmed by
      direct execution): APPROVE and Tier-5 co-sign are TWO SEPARATE,
      CODE-LEVEL-DISCONNECTED mechanisms that merely share field names.
      `dv-harness approve <stage>` only writes a coarse, stage-level record
      to control.json, consulted by run_stage() solely to gate
      PROMOTION_READINESS/SIGNOFF out of WAIT_USER (and, since the same
      fix, consumed -- single-use -- once it authorizes one PASS). It does
      NOT wrap, satisfy, or bypass any individual gates.JUDGMENT_FIELDS
      entry -- when policy.require_dv_review_cosign is true, every
      DV_JUDGMENT-tagged field in a stage's evidence still needs its own
      explicit {"value","reviewer_id","reviewer_confidence"} wrapper from
      the agent, an APPROVE record on file notwithstanding. Do not assume
      approving a stage satisfies its Tier-5 co-sign requirement.
    """
    prompt = BASE + "\n使用者最終目標：\n" + user_goal + \
           "\n\nHarness Current State:\n" + state_summary + \
           "\n\nCurrent Stage: " + stage + "\n" + STAGE_INSTRUCTIONS.get(stage, "")
    if constraints:
        prompt += ("\n\n人類外部指令（CONSTRAINT，優先於一般 SOP，"
                   "但不得違反安全規則，例如不得 force push / reset --hard / clean -fd）：\n"
                   + "\n".join(f"- {c}" for c in constraints))
    if correction_note:
        prompt += ("\n\n人類對本 stage 的修正意見（CORRECT，請依此調整判斷/做法，"
                   "不是重跑同一套舊邏輯就交差）：\n" + correction_note)
    if human_approval:
        prompt += (
            "\n\n本 stage 已有人類核准記錄（APPROVE）：reviewer_id="
            f"{human_approval.get('reviewer_id')}, reviewer_confidence="
            f"{human_approval.get('reviewer_confidence')}"
            + (f"，note: {human_approval.get('note')}" if human_approval.get("note") else "")
            + "。若本 stage 的證據欄位需要 DV review co-sign wrapper "
              '({"value": ..., "reviewer_id": ..., "reviewer_confidence": ...})，'
              "請直接使用這組 reviewer_id/reviewer_confidence，不要自行編造。"
        )
    if relevant_memory:
        prompt += (
            "\n\nMemory Tier 檢索到的相關既有記錄（Prior Knowledge，僅供參考 -- "
            "依 CLAUDE.md Evidence Truth Rule，current evidence 永遠優先於這裡任何一筆記錄，"
            "任何 root cause 仍須以當前證據重新驗證）：\n"
            + "\n".join(
                f"- [{m.get('level', '?')}] {m.get('title', '')}"
                + (f"：{m.get('root_cause')}" if m.get("root_cause") else "")
                for m in relevant_memory
            )
        )
    return prompt

# DE-facing (non-UVM-jargon) stage explainers. Purely additive: never
# referenced by build_stage_prompt or STAGE_INSTRUCTIONS, so the DV agent's
# actual prompt payload is provably unchanged by this dict's existence -- it
# is reached only via dv_harness.cli's "explain" subcommand and dashboard.py's
# /api/de-explain endpoint, both read-only. Added 2026-08-28 to lower the
# onboarding barrier for a design engineer with no UVM/DV background; text
# mirrors what the matching STAGE_INSTRUCTIONS entry actually enforces so it
# can't drift into misrepresenting the gate, but contains zero gate JSON and
# zero instructions to an agent.
STAGE_DE_EXPLAINER = {
Stage.VPLAN.value: """
【白話說明】vPlan 就是這次驗證要做的「檢查清單」，跟你在改 RTL 前，會先列一份
「這次改動要覆蓋哪些 case、review 時要對照哪些項目」的 checklist 是同一件事——
只是這份清單是給「怎麼證明功能是對的」用的，不是給怎麼實作用的。這個 stage
不是馬上寫測試，而是先把「規格裡每一條要求」跟「打算怎麼證明它」兩兩對應好，
並且明確標記哪些要求這顆 DUT 根本不支援（用 waiver 記錄原因，不是直接刪掉）。
清單沒有對齊、沒有使用者確認範圍之前，不會開始寫測試或搭驗證環境——
就像 review checklist 沒過，不會開始跑 regression 一樣。
""",
Stage.COVERAGE_CLOSURE.value: """
【白話說明】Coverage closure 類似你熟悉的 code coverage report，但檢查得更嚴格：
不是「這行程式碼有沒有被跑到」，而是「這個功能情境有沒有真的被一個活著的
checker/scoreboard 盯著看過、而且真的驗證過結果對不對」。如果某個功能還在
active failure（還在燒的 bug），不能因為程式跑到那一行就發 coverage 額度——
這等於 regression 還在紅燈卻先蓋章通過。coverage 有洞的時候，正確做法是回頭
補測試，而不是直接用 waiver 蓋過去（除非那個功能真的確認不支援/不適用）。
""",
Stage.RE_AUDIT.value: """
【白話說明】RE_AUDIT 就是修完 bug 之後的「第二輪 code review」：確認之前提的
問題真的都關掉了，而且這一輪修改沒有意外弄壞別的東西（如同你改完 RTL 後
重跑一次完整 regression 確認沒有 regression fail）。這裡還多做一件事：對每個
判斷（例如某個 failure 的根因是什麼），會列出好幾個可能的假設，分別找支持
和反對的證據，用證據淘汰不對的假設，而不是憑經驗/直覺猜一個就定案——
类似你懷疑一個 timing 問題有好幾種可能成因時，會逐一用波形/log 排除，
而不是看到一個相似案例就直接套用。
""",
Stage.SOC_SCENARIO_PLANNER.value: """
【白話說明】這個 stage 是在做「這幾個 IP/subsystem 同時動起來會不會打架」的
測試規劃，而不是把每個協定各自的 testcase 疊加起來當作 SoC 驗證做完了——
就像你在做 top-level integration review 時，會特別注意「這個模組跟那個模組
共用同一個 bus/clock/reset 時會不會有 race condition」，而不是分開看每個
模組都沒問題就結案。這裡也不會窮舉所有組合（爆炸式排列），而是先按風險
（例如新改的 RTL、reset/clock domain crossing、多個 outstanding transaction
同時存在等）排優先序，先確保高風險的組合一定有對應測試。
""",
Stage.FAILURE_RECOVERY.value: """
【白話說明】這是 bug debug 流程，跟你平常抓 RTL bug的邏輯一樣：先看
log/error message（成本最低），能定位就不用往下一步；看不出來才逐步升級到
scoreboard/checker 訊息、再到額外加 log、最後才開波形（FSDB，等同「加探針
開示波器」，是最後手段，而且開之前要先跟你確認要看哪些訊號、看多深，
不會整顆晶片全部訊號都存）。找到問題點之後，還會刻意分辨「這是 DUT
本身的邏輯錯（DUT_BUG）」還是「這是測試平台/測試案例寫錯（TB_BUG）」——
方法是沿著 訊號流（sequence → driver → DUT 界面輸入 → DUT 內部 → DUT
界面輸出 → monitor → checker）找第一個「預期值跟實際值不一樣」的位置，
落在 DUT 內部就是 DUT bug，落在驗證平台端就是 TB bug，找不到明確分界點
就先標記 UNKNOWN，不會隨便猜一邊定案。
""",
Stage.VERIFICATION_ARCHITECTURE.value: """
【白話說明】這個 stage 在決定「這次要在哪些訊號/介面點放檢查點」，
概念上跟你在 RTL design 時決定「這裡要不要加一個 assertion、那個 FSM
狀態要不要拉一條 debug 訊號出來看」是同一件事——只是這裡放的是
monitor（看訊號）、scoreboard（比對預期跟實際結果）、checker/assertion
（自動抓違規）這些驗證用的觀察點。這個 stage 的硬性規定是：每一個
規劃要寫的測試，都必須先綁定至少一個已經定義好的檢查機制，才能開始寫，
不能先把測試寫完才回頭發現「這裡根本沒有東西在看，寫了也白寫」——
就像你不會等 layout 做完才發現忘了留 debug pin 一樣。
""",
Stage.REQUIREMENT_CLOSURE.value: """
【白話說明】這是「規格逐條簽核」的階段，很像 tape-out 前你要把 spec
checklist 每一條都打勾一樣。每一條規格要求最後只能落在四種狀態之一：
VERIFIED（真的有跑過測試、有實際證據證明通過）、WAIVED（確認不驗但有
書面理由和核准）、NOT_APPLICABLE（這顆晶片本來就不支援這個功能、且有
記錄依據）、或 GAP（還沒有結論——這種不能放著不管，一定要繼續追）。
規則很單純：不能有任何一條規格「沒人管」、也不能拿舊的測試結果充當
這次改動的證據。
""",
Stage.PROMOTION_READINESS.value: """
【白話說明】這是「能不能進下一個 milestone/準備 tape-out」的總體檢查，
類似你在準備 design review sign-off 前，會確認「所有 block 都沒有還在燒的
critical bug、所有文件都是最新版、不是拿上一版的驗證報告來湊數」。這裡
會逐項確認每個關鍵面向（coverage、regression 等）都是「就緒」而不是
「阻塞/未知/失敗/沒做完」，確認目前沒有還在燒的 active failure，而且
最終要交出去的證據包（signoff bundle）是完整、新鮮、跟這次實際改動
對得上的，不是拼湊舊資料。
""",
Stage.ENV_CHECK.value: """
【白話說明】這是開工前的環境檢查，跟你要開始改 RTL 前，會先確認工具授權、
版本、常用 script 都在、能不能連到 server 一樣。這裡多一個規定：一開始就要
明確講清楚「這次只是純本地讀檔分析（不碰伺服器、不跑模擬）」還是「這次需要
連線到 Linux DV server/跑模擬」，講錯類別（例如講本地分析卻列出要跑 vcs/
regression 的動作）會被視為矛盾。如果真的需要連到伺服器，不會自己偷偷連，
會先問你要不要建立連線，並跟你要帳號、vc/ssh 主機名稱、工作目錄這四項；
密碼只在實際連線那一刻用，絕對不會被寫進任何記錄檔或存起來。
""",
Stage.INTAKE.value: """
【白話說明】這是收集這次任務基本資料的階段，類似你接手一個新 verification
task 前，要先搞清楚「這次驗證對象是誰、涉及哪些協定、手上有哪些既有資料」。
做法跟你查 bug 一樣：先自己去找既有的 config/檔案，能找到答案就不問你；
真的缺、而且是往下走必要的資訊，才會一次問你最少的必要問題（不會丟一長串
表單轟炸你）。這裡也會確認「產出物」（例如 build、regression report、
checker 這些本來就該由 harness 自己產生的東西）不會被要求由你先準備好，
分不清楚 harness 該產生的東西跟你該提供的輸入會被判定失敗。另外會順便
問一句「你手上原本有沒有自己在跑的一套本地模擬環境（compile/run script、
filelist、環境設定 script）」——有就記錄下來、附上怎麼確認過這些檔案真的
存在/可用；完全沒有也沒關係，不會因為沒有就卡關。
""",
Stage.DISCOVERY.value: """
【白話說明】這是正式動手前的「五路盤點」：Spec、RTL 原始碼、既有的
command.txt、USB Standard/VIP/Reference UVM、還有你自己之前跑過的本地
模擬結果，五個來源一起看，先建立這顆 DUT 大概長什麼樣（hierarchy、
interface、clock/reset、DMA/中斷）。找證據的順序也有規定：優先看專案內
既有檔案、RTL 參數/define、既有 UVM/VIP config，這些都查過還是不確定
才輪到問你，不會憑感覺跳著查。另外這裡會先依 Spec 草擬一版最初的 vPlan
checklist（v0.1），之後每個階段會回頭修訂它，而不是等全部分析完才第一次
動筆寫 vPlan。
""",
Stage.COMMAND_PATTERN.value: """
【白話說明】這階段把手上每一份既有 command.txt 分成三類：可以直接沿用
（REUSE）、需要小改（EXTEND）、或需要重新產生（GENERATE）——類似你整理
一批既有 testcase，先分「原封不動可用」「改個參數就能用」「要重寫」。
這裡有個硬性規定：如果宣稱是「沿用/搬移既有 command」，內容的 hash 就
必須跟原始的一模一樣；真的有改內容，一定要標記成「已核准的修改」，不能
在搬移過程中悄悄改了內容卻還宣稱是原封不動沿用——就像 port 一個 testcase
到新環境時，你會希望 diff 是乾淨的，不是被誰偷偷動過。
""",
Stage.DE_BASELINE_REPRODUCTION.value: """
【白話說明】這步驟就是「接手別人環境的第一件事：先原封不動重跑一次」。
用你原本的 command.txt、build 方式、RTL，完全不改地重跑一遍，確認 harness
重現出來的結果（PASS/FAIL）跟你原本自己跑出來的結果一致，而且過程中
command/RTL/build/environment 這幾個 hash 都要完全相同——代表重現的
路上沒有不小心改到任何東西。這一步沒過、沒鎖定 baseline 之前，後面的
Architecture Discovery 不會開始，道理跟「你連原本的 regression 都重現不出來，
就沒有資格開始在上面做任何修改」一樣。
""",
Stage.ARCH_DISCOVERY.value: """
【白話說明】這是「照著 RTL 原始碼重新畫一次這顆晶片的架構圖」，而不是
先看文件猜。跟你拿到一份不熟悉的 RTL 要開始 debug 時做的事一樣：先看
top-level hierarchy、模組怎麼接起來、有哪些 interface、clock/reset 怎麼分、
參數/define 是什麼、中斷/DMA/register bus 長怎樣。每個發現都會標信心
等級：很確定的直接採用；不太確定的要再找別的 RTL 證據交叉驗證；真的
看不出來的才會標記下來問你，不會憑印象腦補架構。這一步只到「先有一版
架構模型」，還不要求鎖定，正式鎖定在下一個 Architecture Calibration。
""",
Stage.ARCH_CALIBRATION.value: """
【白話說明】這是「拿新證據回頭校正架構模型」的階段，類似你 debug 到一半
發現之前對某個模組的理解是錯的，這時不能只偷偷改一個註解就算了，要去
盤點「哪些東西是根據那個錯誤理解做出來的」（vPlan、測試假設、環境設定
等），一併更新，並重新驗證過一次。這裡也包含 VIP 版本檢查：如果 VIP
版本跟原本核准使用的版本不同，要先做 API 差異分析，有 breaking change
要更新對應的 adapter，而不是換了 VIP 版本卻假裝介面沒變。所有已知的
落差跟衝突都處理完，才能真正把架構「鎖定」，鎖定之後不應該還留著
沒解決的未知項。
""",
Stage.PROJECT_MODEL.value: """
【白話說明】這是畫這次驗證專案的「總體 floorplan」：這次驗證邊界在哪裡
（哪些東西算 in-scope、哪些不算）、VIP 怎麼接到 DUT 上、以及
BLOCK/branch-A/branch_fw/branch-B 這幾層的拓樸關係——概念上跟你在做
一個新專案的 top-level integration plan 時，會先畫一張方塊圖標出誰接誰、
邊界在哪裡是一樣的。這一步會承接前面 Architecture Discovery 累積出來的
證據，把「這顆 DUT 長什麼樣」轉成「這次要怎麼驗證它」的骨架，後面的
Protocol Capability、vPlan 都會建立在這個骨架上。
""",
Stage.PROTOCOL_CAPABILITY.value: """
【白話說明】這階段在確認「這次涉及的協定（USB2/USB3/PCIe/MIPI...）這顆
DUT 實際支援哪些 mode/能力」，不是看到 Spec 寫「支援 USB3 Gen2」就當作
全部都有——要拿 Spec、RTL、Register map、command.txt、Reference UVM、
VIP 六個來源交叉比對，跟你確認一顆晶片實際 implement 了哪些 feature 時
不能只看規格書、要真的去查 RTL/暫存器一樣。查不到 RTL/Register/VIP
證據支持的能力，要記錄成 gap 交給後面 vPlan 走 waiver，而不是照 Spec
假設它存在。這裡也會要求把這份協定能力清單釘上明確的版本號/hash，
避免之後被誰在沒人注意的情況下悄悄改掉內容卻沒人知道。
""",
Stage.REQUIREMENTS_TRACEABILITY.value: """
【白話說明】這是建立「規格條文 → vPlan → 測試情境 → command/pattern →
checker/coverage → regression 結果 → signoff 證據」整條追溯鏈的階段，
類似你在準備 review 時會列一份 requirement-to-test 對照表，確保每一條
需求都查得到「是被哪個測試證明的」。DUT 真的不支援的需求要走 waiver
（附上 design 端的證據），不能直接刪掉當作沒這回事。這裡還有一個容易
忽略的規則：waiver 不是寫一次就永久有效——如果之後 spec 或 RTL 改版了，
舊的 waiver 就會被視為過期，需要重新確認還適不適用，跟一則 review
comment 在底下程式碼改動後會失去時效性是同樣的道理。
""",
Stage.INFRASTRUCTURE_AUDIT.value: """
【白話說明】這是在體檢「驗證環境本身夠不夠力」：scoreboard、DMA
scoreboard、效能計算器、coverage collector 這些基礎設施，是否真的能處理
by-instance、by-port、by-interface、並發（concurrency）、混合情境等
實際會遇到的組合，而不是只驗證過最簡單的單一情境——就像你不會只用
最簡單的 smoke test 就宣稱整個 testbench 沒問題一樣。這裡會用好幾個
面向（DUT/Protocol Config/VIP/Build Flow/Testbench/Spec/vPlan/
Regression/Coverage）分別打分數，任何一個關鍵面向分數太低都會被判定
BLOCKED，不是平均分數好看就算過。
""",
Stage.IMPLEMENT.value: """
【白話說明】這是真正動手寫測試的階段：把目前 finding 清單裡所有本次
scope 內該修的問題一次寫完（包含監測用的 monitor/scoreboard/checker/
assertion/reference model），而且一定要包含至少一組刻意注入錯誤的
negative test，證明你的 checker 真的抓得到問題，不是「寫了但其實沒在
檢查」的假 checker——跟你 review 一個新加的 assertion 時，會故意造一個
違反它的情境確認它真的會跳出來是同樣的邏輯。這裡也不接受「先把第一個
failure 修完就交差」，必須把這輪範圍內的問題一次處理完。另外有一條硬
規定：每一個新寫的測試都要能追溯回它對應的 vPlan requirement 跟驗證
機制，不能寫了一個測試卻沒有掛回任何需求，變成沒人知道它在驗什麼。
""",
Stage.CHANGE_IMPACT.value: """
【白話說明】這是「這次改動應該重跑哪些 regression」的影響分析，類似你
改完一段 RTL 後，會想「這次改動影響到哪些模組，該重跑哪些 test」而不是
只重跑自己剛改的那一條。這裡分三層：直接受影響的（TARGETED）、依賴它的
（DEPENDENCY）、以及保底的安全網（SAFETY）。有一條規則特別重要：如果
這次改動牽涉到 Spec 本身，vPlan 必須重新檢視過；如果改到 RTL 的
interface/architecture，架構模型也要重新檢視——不能只當作一般小改動
處理。另外，任何下游 artifact 只要依賴到這次改動的項目，都不能是舊的
（stale）或缺 hash 的狀態，否則會被判定證據鏈斷掉。
""",
Stage.GIT_SYNC.value: """
【白話說明】這是動手改東西之前的「先看清楚現況」：確認 Git 目前的
status、跟遠端的差異、決定怎麼安全同步，跟你要在別人分支上做事之前，
會先 fetch、看看有沒有衝突、想好合併策略是同一件事。這裡特別強調
「不能破壞你（使用者）手上不相關的既有改動」——同步過程中如果你本地
還有其他未提交的修改，不會被這個流程順手清掉或蓋掉，這也是為什麼這裡
不會自動執行 force push / reset --hard / clean -fd 這類會把工作目錄
清空重來的危險指令。
""",
Stage.GIT_PUSH.value: """
【白話說明】這是實際 commit 跟 push 的階段：review diff、擋掉不該進版控
的密碼/生成物、commit、push，並記下確切推上去的 SHA——跟你平常 push
前會看一眼 diff、確認沒有夾帶不該進 repo 的東西是一樣的流程，而且
禁止 force push。這裡多一道門檻：不是「第一輪修完就直接 push」，而是
要先確認第一輪發現的問題全部修完，再完整跑過第二輪詳細檢查、確認
沒有殘留問題，才允許 push——類似你自己先 self-review 一次修改，
確認乾淨了才送出 PR，而不是修完第一個 comment 就直接推上去。
""",
Stage.SERVER_SYNC.value: """
【白話說明】這是 push 完之後，到 Linux Server 上做的最後一道確認：
server 上目前的 HEAD SHA 是不是真的等於剛剛推上去的那個 SHA（如果有
submodule，submodule 的 SHA 也要一起對上）——就像你 push 完會習慣性
ssh 上 build server 跑一下 `git log -1` 確認拉到的真的是你剛剛那個
commit，而不是還停在舊版本，或者不小心跑到別人推的版本。這一步沒對上
就代表接下來的 build 會建立在錯的原始碼上，所有後面的證據都不可信。
""",
Stage.BUILD.value: """
【白話說明】這是照專案既定流程執行編譯/build，coverage 預設關閉（跟平常
compile 不需要一開就開 coverage 一樣）。這裡有兩條 VCS regression 特有的
安全規則：一是不能讓兩個平行跑的 elaboration job 同時寫進同一個共用的
輸出路徑（就像兩個人同時寫同一個 object file，會互相覆蓋壞掉）；二是
compile 階段完成要有明確、可驗證的「完工標記」（build fingerprint +
完成標記兩者要對得上），而且要等 compile 真的完全結束、標記確認一致，
才能開始平行跑多個測試，不能讓 compile 悄悄「還沒真的做完」就滑進
run 階段。
""",
Stage.BUILD_DEBUG.value: """
【白話說明】這是 build 失敗後的第一輪快速分流，跟你平常看到 compile
error 的直覺反應一樣：先看是不是一眼就能看出的小問題（打錯字、漏了檔案、
compile flag 打錯、filelist 少列一個檔），是的話直接修一修重跑；如果
看起來像是設計層面的問題、或修了還是不行，就不要在這裡反覆猜、卡住，
直接轉去走完整的 Failure Recovery（正式的根因分析流程），而不是原地
一直嘗試碰運氣式的修法。
""",
Stage.VERIFY.value: """
【白話說明】這是真正跑單一 targeted 測試並判斷「這個 PASS 是不是真的
PASS」的階段，FSDB 預設不開，先看 log。這裡的重點是防止「假 PASS」：
不是模擬器吐出退出碼 0 就算過，而是要真的比對 sim.log 跟 command.txt
裡宣稱要驗證的每一項期望是否對得上；而且要求你的 negative test 真的能
證明 checker 抓得到刻意注入的錯誤，不是形同虛設的檢查。每一筆結果還要
帶完整的來源資訊（用的是哪個 RTL/TB/VIP/工具版本、哪個 seed），避免
「這筆 PASS 其實是拿別的 build 跑出來的」這種張冠李戴。失敗時規則跟你
平常抓 bug一樣：停在第一個 failure，先用 log/UVM 訊息分析，真的需要
訊號級證據才考慮開波形，開之前要先跟你確認要看什麼、看多深。
""",
Stage.WAVE_ANALYSIS.value: """
【白話說明】這是真正打開波形（Verdi/FSDB）debug 的階段，等於「示波器
開下去」的最後手段——前面用 log 分析不出來才會走到這裡。開之前一定要
先跟你確認要 dump 哪些訊號範圍、看多深，優先用目前已知的 failure cone
去抓最小夠用的範圍，不會預設整顆晶片全訊號全深度硬 dump（那樣 FSDB 檔
會大到難用，也拖慢模擬）。模擬也不會整個測試跑到底，而是抓到第一個
相關的 failure/error/fatal 點附近就停下來，最多留一點點事後緩衝，
不是跑完整個 test 才回頭找問題。
""",
Stage.REGRESSION_SELECT.value: """
【白話說明】這是在正式送出一批 regression 之前，把要跑的測試清單組出來
的階段：包含跟這次改動直接相關的（TARGETED）、依賴它的（DEPENDENCY）、
保底的安全網（SAFETY），再加上這個專案規定一定要跑的 signoff regression
——跟你在 push 前決定「這次到底要重跑哪些既有 regression suite」是同一個
決策，差別在這裡明確要求這四類都要覆蓋到，不是憑感覺挑幾個測試意思意思
跑一下，也不是偷懶直接跑全部浪費算力。
""",
Stage.REGRESSION.value: """
【白話說明】這是把選好的測試清單正式送進 LSF compute farm 跑的階段。
有一條規則：每一個送出去的 LSF job，都會有自己獨立的 Job Agent context
——代表一個 job 的除錯過程/上下文不會跟另一個 job 混在一起，就像每個
CI job 有自己獨立的 log，不會互相污染。預設情況下這批 regression 是
「輕量跑」：不開波形（WAVE=0）、不開 power analysis（PA=0）、coverage
關閉，先求跑得快跑得多，這些額外分析等真的需要時才針對特定測試個別
開啟，不會整批預設全開拖垮 farm。
""",
Stage.REGRESSION_MONITOR.value: """
【白話說明】這是盯著送出去的一批 LSF job 看結果的階段，核心規則是
「LSF 顯示 DONE 不等於 DV PASS」：job 跑完（DONE/EXIT）只代表模擬器
正常結束，不代表功能是對的，一定要真的打開 sim.log 分析過才能標記
PASS/FAIL——跟你不會只看 CI job 顯示綠色勾勾就假設程式邏輯沒問題一樣，
還是要看實際輸出。這裡也會先分辨這個失敗是「環境/工具問題」還是
「真的功能有問題」，並把相似的失敗歸類在一起（同一個根因造成的一堆
job 失敗，會被視為同一類，不會被當成 50 個獨立問題分別處理）。另外，
整批 regression 的每一筆結果都必須回到同一個 source/build/config
身分（同一個 canonical run），不同 build 跑出來的結果混在一起看
會誤導判斷，除非有明確核准的合併理由。
""",
Stage.INFRA_RECOVERY.value: """
【白話說明】這是 regression 失敗後的第一輪快速分流，概念跟 BUILD_DEBUG
很像：先判斷這是「Infrastructure 問題」（LSF 排程、license、算力、工具
環境設定，跟 DUT/testbench 本身無關，通常重新提交或修一下環境設定就好），
還是「Functional 問題」（DUT/TB/VIP 真的有問題，需要認真查）。Infra
問題處理完直接回去重新送 regression，不需要走完整的根因分析；只有確認
是真的功能問題、或者 infra 問題自己解決不了，才會轉去走完整的
Failure Recovery 流程——不要把單純的環境小問題，當成設計 bug 大費周章
去查。
""",
Stage.SYSTEM_LEVEL.value: """
【白話說明】這是多個 subsystem 組成 system-level 環境後的總體判定階段，
核心規則是「system-level 的整體 PASS，不能蓋過某個 subsystem 其實是
FAIL 的事實」——除非那個 subsystem 有被明確隔離、而且有核准的 waiver，
不然不能因為系統整體綠燈就當作每個部分都沒事，就像一個服務的整體
健康度是綠的，不代表底下每個模組都真的沒問題一樣。這裡還會額外檢查
一件容易被忽略的事：這顆 DUT 實際存在的每一個 subsystem，是不是真的
都有被列進這次組裝的清單裡（或有正式 waiver），而且真的有在至少一個
跨 subsystem 情境裡被實際操作到——只是被列在清單上、卻沒有任何測試
真的碰過它，一樣算沒完成。
""",
Stage.EXPERT_FEEDBACK_LOOP.value: """
【白話說明】這是把 AI 這輪做出來的東西交給真人 DV 專家做最後一輪 review
的階段，很像資深工程師對你的 PR 做的 code review：每一條意見最後都要有
明確去向——接受（要附上實際改了什麼、以及改完的證據）、修改後接受、
拒絕（要附上為什麼不採納的反證，不能只說「不同意」）、或是「證據還不夠，
先記著之後補」，不能含糊帶過。如果專家的意見要求真的動東西（改 vPlan、
UVM 環境、checker、測試等），要先做影響分析，改完之後要回頭重新跑一次
compile→smoke→regression 產生新證據，再讓專家覆核一次，不是記一下
「已接受」就算結案。這裡也是「這次 debug 出來的經驗值不值得留下來給
下次用」的把關點：真的具有跨案參考價值、而且有真人專家確認過的知識，
才會被存進共用的知識庫，不是隨便什麼都往裡面塞。
""",
Stage.SIGNOFF.value: """
【白話說明】這是最後的簽核關卡，等同 tape-out 前的最終 sign-off 會議：
不能只憑一句「看起來做完了」就結案，要把這次驗證各個面向的證據
（spec 追溯、build、測試結果、assertion、scoreboard、coverage、
regression、RCA/修復紀錄、環境版本指紋）整理成一份完整、每筆都帶 hash
的證據包，而且要再次證明你的 checker 真的能抓到刻意注入的錯誤，不是
形式上的檢查而已。這裡的結論只有三種合法狀態：CLOSED（真的做完了）、
BLOCKED（明確卡住，講清楚卡在哪）、或 ACCEPTED_RISK（明知有風險但
經過核准接受）——不存在「大概沒問題就先這樣」這種模糊結案方式。
""",
}

def get_de_explainer(stage: str) -> str:
    """DE-facing (non-UVM-jargon) explainer for a stage. Purely additive --
    never referenced by build_stage_prompt, so it cannot alter agent behavior
    or gate evidence. Falls back to a generic note for any stage not yet
    covered in STAGE_DE_EXPLAINER."""
    return STAGE_DE_EXPLAINER.get(
        stage,
        "（尚未提供這個 stage 的白話說明；請參考 STAGE_INSTRUCTIONS 或詢問 DV owner。）"
    )
