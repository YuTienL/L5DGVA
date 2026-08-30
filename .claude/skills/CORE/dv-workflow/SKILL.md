---
name: dv-workflow
description: Final industrial command-driven SoC-aware protocol-agnostic DV workflow for DE and general DV engineers.
argument-hint: "[request]"
---
# Command-Driven SoC-Aware Industrial DV Workflow

User request: $ARGUMENTS

## Fundamental principles

1. User-facing execution API is `command.txt` / scenario commands.
2. Existing DE commands are capability baseline/reference, not verification scope.
3. vPlan determines what must be verified.
4. DUT SoC hierarchy and interface topology determine verification boundaries.
5. VIP type/role/count/bind points are derived, never guessed from protocol alone.
6. TB architecture is BLOCK + branch_a* + branch_fw + branch_b*.
7. branch_a count follows DUT ports; branch_b count follows VIP ports/instances; branch_fw supports N:M.
8. Reuse existing command/VIP capability first, extend second, generate last.
9. Ask user only after repository evidence is exhausted.
10. PASS requires compile + target test + relevant regression + review/signoff evidence.

## End-to-end architecture

DE / DV USER
   |
USER REQUEST
   |
INTAKE
   |
+-- Existing DE command.txt
+-- RTL / parameters / defines
+-- UVM / VIP config
+-- tests / sequences
+-- docs/spec
+-- vPlan
+-- build/regression
+-- Git evidence
   |
DUT / SoC HIERARCHY DISCOVERY
   |
DUT PORT INVENTORY
   |
INTERFACE TOPOLOGY
   |
PROTOCOL ROUTER / PROFILE
   |
VIP TOPOLOGY PLANNER
   |
+-- VIP TYPE
+-- VIP ROLE
+-- VIP COUNT
+-- ACTIVE/PASSIVE/MONITOR_ONLY
+-- BIND POINT
   |
TB TOPOLOGY PLANNER
   |
+-- branch_a0..N (DUT ports)
+-- branch_fw (N:M framework/routing/dispatch)
+-- branch_b0..M (VIP ports)
   |
PROJECT MODEL + CONFIDENCE
   |
DV READINESS
   |
vPlan
   |
REQUIRED SCENARIOS
   |
COMMAND CAPABILITY / GAP ANALYSIS
   |
REUSE / EXTEND / GENERATE
   |
command.txt
   |
Command Parser / Handler
   |
branch_fw
   |
Command -> VIP Sequence Mapping
   |
VIP Sequence
   |
DUT
   |
Checker + Coverage
   |
Compile -> Target Test -> Regression -> Review -> Signoff

## Evidence priority

1. Existing DE command.txt / command examples / scenario files
2. Command parser / grammar / handlers
3. Command -> VIP sequence / branch_fw mapping
4. Existing project files
5. RTL / parameters / defines / hierarchy
6. Existing UVM / VIP config
7. Existing tests / sequences
8. Design documentation/specification
9. Existing vPlan / testcase spreadsheet
10. Build / regression scripts
11. Git history / comments
12. Ask user

Current executable RTL/configuration beats stale history/comments.

## READY / PARTIAL / BLOCKED

READY:
execute.

PARTIAL:
auto-fill recoverable artifacts, recalculate readiness, then ask only remaining blocking ambiguity.

BLOCKED:
do not guess; ask 1-3 minimum high-value blocking questions.

## Default protocols

USB Host: USB2 FS/HS, USB3 Gen1/Gen2
USB Device: USB2 FS/HS, USB3 Gen1/Gen2
PCIe: Gen2/3/4/5/6
MIPI CSI-2
MIPI DSI
Ethernet
CAN-FD
AMBA SoC Bus: APB2/APB3/AHB/AHB-Lite/AXI3/AXI4/ACE-Lite/AXI-Stream

Normalize obvious contextual typos such as AMAB4 -> AMBA and AIX4 -> AXI4.


## DE + DV usability contract

This workflow is designed for both Design Engineers and Verification Engineers.

A valid initial request may be as small as:
- "Verify USB Host."
- "Create PCIe DV."
- "Run this command.txt."
- "Why did this scenario fail?"
- "Analyze this SoC verification completeness."

The workflow must discover what it needs before asking the user.

DE-facing output should prioritize command.txt, configuration, expected behavior and actionable failures.
DV-facing output may additionally expose topology, VIP/UVM, vPlan, coverage and regression internals.

The command language is shared and stable. Advanced DV-only capabilities may be tagged DV_ONLY rather than creating a second incompatible interface.

## Mandatory project artifacts

Hierarchy and topology:
hierarchy.json
dut_ports.csv
interface_inventory.csv
vip_topology.csv
vip_binding.csv
tb_topology.json
branch_a.csv
branch_fw.csv
branch_b.csv

Verification intent:
project_model.json
evidence.csv
vplan.csv

Command capability:
command_inventory.csv
command_gap.csv
command_mapping.csv

Execution/signoff:
readiness.json
validation.json

## Final traceability

SPEC/REQ
-> DUT/PORT/BOUNDARY
-> VP_ID
-> SCENARIO
-> COMMAND_ID
-> branch_fw route
-> VIP_SEQUENCE
-> DUT
-> CHECKER
-> COVERAGE
-> TEST/REGRESSION
-> SIGNOFF


# 強制工業鐵則與 PC/Server 執行契約

本 Workflow 必須載入 `CORE/iron-rules`。

PC 是 Development / AI Orchestration Plane。
Linux Server 是 Verification Execution Plane。

Claude Code 標準啟動：
`claude --dangerously-skip-permissions`

正式流程：
PC 修改
→ 修改區域註解清理
→ diff review
→ PUSH
→ Server exact-commit sync
→ BUILD (Coverage OFF)
→ VERIFY (Coverage OFF)
→ WAVE=1 RUN (time 0 → simulation end, Coverage OFF)
→ fsdbreport
→ Review
→ Signoff

branch-B / VIP pattern 修改前，必須完成 VIP examples/manual/source/class-reference/project-usage 查證。

branch-A / branch_fw 修改前，必須完成 DUT RTL/hierarchy/PHY/programming/integration/config 查證。

禁止過度抽象命名。

任何必要階段未完成，不得 PASS。


# Tool Usage Verification Gate

任何工具使用方式不確定時，不得直接猜 command。

查證順序：
project existing usage
-> local official manual/help/reference
-> official online documentation
-> reliable technical web sources
-> user clarification / BLOCKED

此規則特別適用於：
fsdbreport、VCS、Verdi、VIP utility、LSF、coverage、waveform、simulator options。

工具查證未完成且 command semantics 仍不明確時，不得進入正式 BUILD / VERIFY / WAVE / SIGNOFF。

**Confirmed drift (2026-08-29):** this rule was actually practiced, not
just stated — a real debug session ran `fsdbreport -h` and
`fsdb2vcd 2>&1 | head -N` to learn actual tool usage before scripting
against either tool, matching this gate's stated "local official
manual/help/reference" step exactly, for these two specific tools.
The real follow-on usage pattern (windowed, headless, no Verdi GUI):
```
fsdb2vcd f.fsdb -o out.vcd -bt <t0> -et <t1> -s <hier_scope> -level 1
fsdbreport f.fsdb -period <T> -level 1 -csv
```
run repeatedly on a narrow time window + hierarchy scope (not the whole
dump), cross-checking the two tools' output against each other — used
in practice on PHY-level OTG/VBUS-style signals (`OTGSESSVLD`, `VBUS`,
`TERMSEL`, `XCVRSEL`, `OPMODE`, `SUSPENDM`) entirely headlessly. Re-derive
the actual signal/hierarchy names from current RTL before reuse per the
Evidence Truth Rule — the technique generalizes, the exact signal names
above do not.


# FINAL DE + DV INDUSTRIAL EXECUTION MODEL

## 使用者體驗
一般 DE/DV engineer 可以只說要驗證什麼，不必先知道：
DUT hierarchy、VIP 種類/數量、bind point、branch 數量、UVM sequence、vPlan 格式、server path、tool option。

Workflow 應先自行查 evidence，只有真正 blocking ambiguity 才問最少問題。

## PC / Server 分工
PC/Windows：
Claude Code、分析、修改、vPlan、command generation、review、push。

Claude 標準啟動：
`claude --dangerously-skip-permissions`

Linux Server：
VCS/Verdi/VIP、build、verify、run、LSF、FSDB、fsdbreport。

## Verification architecture
User Request
→ Intake
→ Existing command capability
→ DUT/SoC hierarchy
→ DUT ports
→ Interface topology
→ Protocol profile
→ VIP type/role/count/bind
→ TB topology: BLOCK / branch_a* / branch_fw / branch_b*
→ Project Model + Confidence + Readiness
→ vPlan
→ Required scenarios
→ Command gap: REUSE / EXTEND / GENERATE
→ command.txt
→ parser/handler
→ branch_fw
→ VIP sequence
→ DUT
→ checker/coverage
→ Remote Intake
→ PUSH
→ Server BUILD
→ VERIFY
→ WAVE=1
→ fsdbreport
→ Review
→ Signoff

## Remote Intake Gate
先查 project；不足才問：
SSH Server / User Account / Shell / source commands / Linux workdir。
密碼永不落盤。

## 修改前 Evidence Gate
branch-B/VIP：
VIP examples → manual → source → class/API reference → project usage。

branch-A/branch_fw：
DUT RTL → hierarchy/ports → PHY docs → programming/integration/register guide → active config。

## Tool Knowledge Gate
不清楚工具用法：
project usage → local official manual/help → official reference → official online docs → credible web → BLOCKED/user。
禁止猜 syntax。

## Source Hygiene
每次修改同步清理修改區域中已失效、重複、多餘、不相關、誤導註解。
禁止過度抽象命名。

## Execution Gate
PUSH → BUILD → VERIFY → WAVE=1 → fsdbreport。
WAVE=1：time=0 到 simulation end。
Coverage：預設 OFF。
缺任一必要 evidence/stage，不得 PASS。


# Reference Environment Final Gate

當使用 USB UVM Reference Environment：

USER REQUEST
→ Remote Intake
→ 確認 REFERENCE_ENV_PATH
→ Reference Preflight (READ_ONLY)
→ Extract Reference Model
→ Current DUT/SoC Hierarchy Discovery
→ Current DUT Port / Interface Topology
→ Protocol Profile
→ VIP Type/Role/Count/Bind
→ TB Topology
→ Project Model / Readiness
→ vPlan
→ Command Gap
→ REUSE / EXTEND / GENERATE
→ WORK_ENV_PATH Implementation
→ PUSH
→ Server exact commit
→ BUILD
→ VERIFY
→ WAVE=1
→ fsdbreport
→ Review / Signoff

Reference 不可直接決定目前 DUT topology。
Reference 不可取代目標 protocol 官方資料與 DUT evidence。


# AMBA M×N Industrial Rule
AMBA4 SoC Bus 以 Multi-Master × Multi-Slave M×N 為核心模型。
Hierarchy → Master/Slave inventory → resource topology → VIP topology → M×N branch mapping → resource-local arbitration → vPlan cross-traffic → command generation → concurrent verify。
禁止為簡化 implementation 建立跨所有 port 的 Global Scheduler。


# LSF Regression + Verdi Industrial Closure

正式驗證閉環：

PUSH
→ BUILD
→ TARGET VERIFY
→ LSF REGRESSION
→ LSF MONITOR
→ RESULT CLASSIFICATION
→ FAILURE CLUSTERING
→ representative WAVE=1
→ fsdbreport
→ 必要時 Verdi
→ fix/rerun
→ regression report
→ review
→ signoff

LSF Regression 預設 Coverage OFF / WAVE=0。
只有代表性 testcase 進 WAVE=1 full simulation。

Regression PASS 的定義：
- functional failures = 0，或有明確 signoff disposition
- infrastructure failures 已解決/隔離
- monitor/report 完整
- waveform evidence 完成


# Pattern + Failure Recovery + Simulation Option Closure

新增/修復 scenario：

vPlan
→ command
→ pattern
→ single simulation
→ FAIL ? Failure Recovery Loop
→ PASS
→ WAVE=1/fsdbreport
→ Pattern Promotion
→ Regression List
→ LSF Regression
→ monitor/report
→ failure? recovery loop
→ signoff

User 可透過 Make API 管理 pattern。
Pattern/DV Workflow 共用 registry。

Simulation Options：
WAVE / PA / FSDB_START / FSDB_STOP / TIMEOUT。


# v8 Branch Architecture

BLOCK：
branch-A = DUT side
branch_fw = interrupt/event-driven dispatcher
branch-B = VIP testing scenario layer

核心 execution：
DUT IRQ/Event
→ branch_fw
→ command/pattern mapping
→ branch-B VIP scenario
→ VIP sequence
→ DUT response
→ checker
→ clear/ack
→ PASS/FAIL。

FAIL 進 Failure Recovery Loop。
PASS 經正式 evidence gate 後 Promotion 到 Regression。


# v9 Generic Any-Subsystem-to-SoC Positioning

本 Workflow 的產品定位：

ANY BLOCK / SUBSYSTEM
→ MULTI-SUBSYSTEM
→ FULL SoC LEVEL VERIFICATION

USB / PCIe / Ethernet / AMBA / MIPI / CAN-FD 僅為 protocol profiles。

核心流程：
User Request
→ Intake
→ Reference Environment（若使用）
→ Hierarchy / Verification Boundary
→ Instance / Port / Interface Inventory
→ Protocol Profiles
→ VIP Topology / Binding
→ TB Topology
→ Generic Infrastructure Audit
→ Project Model / Readiness
→ vPlan
→ command.txt / Pattern
→ Single Simulation
→ Failure Recovery
→ LSF Regression / Monitor / Report
→ WAVE / fsdbreport / Verdi
→ Review / Signoff

Generic Infrastructure Audit 固定稽核：
Scoreboard
DMA Scoreboard
Performance Calculator
Coverage Collector
的 by-port/by-interface/by-instance、concurrency、heterogeneous-combination 能力。

Protocol-specific legal combinations 由 profile 提供，不寫死在 Core。


# v10 Git + DevOps Lifecycle

Generic DV Workflow 正式加入 Git / DevOps：

GIT PULL/SYNC
→ BRANCH
→ MODIFY
→ REVIEW
→ COMMIT
→ PUSH
→ SERVER EXACT SHA CHECK
→ BUILD
→ VERIFY
→ LSF REGRESSION
→ MONITOR
→ FAILURE RECOVERY
→ REPORT
→ SIGNOFF
→ optional TAG/RELEASE

開始前先 discovery existing CI/DevOps。
已有 pipeline 優先 extend，不重新發明。


# v11 Claude CLI Startup Gate

Workflow Entry：

USER REQUEST
→ CLAUDE ENVIRONMENT READINESS
→ READY / PARTIAL / BLOCKED
→ PROJECT INTAKE
→ Generic Subsystem-to-SoC DV Workflow。

Readiness 固定檢查：
Claude CLI
Superpowers
dv-workflow
Core Skills
Task Protocol Profiles
7 Agents
settings.json
settings.local.json
plugin errors
user/project skill scope。


# v12 Mandatory Workflow Closure Loop

任何 workflow：

ANALYZE
→ FIND ALL ISSUES & RECOMMENDATIONS
→ CONSOLIDATE ALL ACTIONABLE ITEMS
→ IMPLEMENT ALL IN-SCOPE FIXES
→ BUILD / VERIFY / WAVE / REGRESSION
→ DETAILED RE-CHECK
→ RE-RUN ORIGINAL AUDIT
→ NEW ISSUE?
   ├─ YES → FIX LOOP
   └─ NO  → SIGNOFF

不得在 finding list 產生後停止。
不得只修到 single simulation PASS 就結束。


# v13 One-Click Master Contract

dv-workflow 的 default behavior = one-click-dv-workflow。

使用者不需要知道內部 Skills/Agents 名稱。
Lead 自動 orchestrate：
Claude readiness → intake → discovery → hierarchy → protocol/VIP/TB → readiness
→ generic audits → vPlan → command/pattern → implement all → Git/DevOps
→ server exact SHA → build/verify → WAVE/fsdbreport → LSF regression
→ failure closure → second-pass audit → signoff。

核心產品定位永遠是：
Generic Any Subsystem → Full SoC Level Verification。


# command.txt Traceability Contract

DE existing command.txt 是可重用輸入，不是唯一 source of truth。
依 vPlan/project evidence 將 command 分類：
REUSE / EXTEND / GENERATE。

每個 generated/extended command 必須可追溯：
vPlan item
→ command.txt
→ command handler
→ branch-B scenario / VIP sequence
→ checker/scoreboard
→ coverage
→ testcase/pattern
→ regression result。


# branch_fw Control Path Rule

branch_fw = DUT Interrupt/Event-driven firmware command dispatcher/control path。
不是 AMBA traffic scheduler、不是 global scheduler、不是跨 port traffic arbiter。

VIP testing scenarios 位於 branch-B。
Protocol traffic semantics/resource scheduling 由 branch-B + protocol VIP/resource model 負責。


# v14 Verification Intelligence

Generic Core 必須包含：
- requirements-traceability
- soc-scenario-planner
- verification-change-impact

Signoff 需同時回答：
1. Requirement 是否 verified？
2. Subsystem/SoC E2E scenario 是否完整？
3. 此 Git change 是否跑了足夠且可解釋的 regression？


# v15 Harness-Aware Workflow

若由 DV Agent Harness 啟動：
- current stage 由 Harness 決定。
- technical execution 仍遵守所有 v14 skills/iron rules。
- 每 stage 輸出要可持久化、可 resume、可 audit。
- Transport/API success 不等於 verification PASS。
- Failure、finding、requirement、Git SHA、regression selection、signoff evidence 都要寫入 artifact。
