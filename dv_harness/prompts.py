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
""",
Stage.INFRASTRUCTURE_AUDIT.value: """
詳細 audit scoreboard、DMA scoreboard、performance calculator、coverage collector 的
by-instance/by-port/by-interface/concurrency/heterogeneous legal combination 能力。
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
