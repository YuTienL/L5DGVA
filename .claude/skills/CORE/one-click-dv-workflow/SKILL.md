---
name: one-click-dv-workflow
description: 一鍵啟動 Generic Any Subsystem → Full SoC 工業級 DE+DV workflow，從 Claude readiness、intake、hierarchy、vPlan、實作、Git、Server verify、LSF regression 到 closure/signoff。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# One-Click Industrial DE + DV Workflow

## 使用者入口
一般 DE/DV engineer 只需描述目標，例如：
`/dv-workflow 詳細分析並完成這個 subsystem 的 USB verification`
`/dv-workflow 對整個 SoC 做 verification readiness、補齊缺口並完成驗證`

Workflow 自動依序：

1. Claude Environment Readiness
2. Remote/Project Intake
3. Existing Project Discovery
4. Reference Environment Discovery（若有）
5. DUT/SoC Hierarchy + Verification Boundary
6. Protocol Router + Protocol Profiles
7. VIP Type/Role/Count/Bind Topology
8. TB Topology: BLOCK / branch-A / branch_fw / branch-B
9. Project Model + Confidence + DV Readiness
10. Generic Infrastructure Audit
11. vPlan Gap Analysis / Generation
12. command.txt REUSE / EXTEND / GENERATE
13. Pattern Registry / Make API
14. Implement ALL actionable findings
15. Git Sync / Branch / Commit / Push
16. Linux Server Exact SHA Gate
17. BUILD
18. Targeted VERIFY
19. Representative WAVE=1 + fsdbreport
20. PASS Pattern Auto Promotion
21. LSF Regression
22. LSF Monitor / Failure Classification / Report
23. Failure Recovery: log → FSDB → fsdbreport → Verdi → fix → verify → rerun
24. Detailed Re-Check
25. Re-run Original Audit
26. Iterate until CLOSED / BLOCKED / ACCEPTED_RISK
27. Verification Signoff

## Scope
同一 Core 支援：
Block/IP → Subsystem → Multi-Subsystem → Full SoC。

Protocol 只是 Profile，不是 Core：
USB Host/Device USB2 FS/HS, USB3 Gen1/Gen2
PCIe Gen2/3/4/5/6
Ethernet
AMBA: APB2/APB3/AHB/AHB-Lite/AXI3/AXI4/ACE-Lite/AXI-Stream
MIPI CSI-2
MIPI DSI
CAN-FD

## READY/PARTIAL/BLOCKED
READY：直接執行。
PARTIAL：能生成/分析的先完成，再問剩餘 ambiguity。
BLOCKED：只問 minimum required information。

## Evidence Priority
1 Existing project files
2 RTL / parameters / defines
3 Existing UVM / VIP config
4 Existing tests / sequences
5 Design documentation
6 vPlan / testcase spreadsheet
7 Build / regression scripts
8 Git history / comments
9 Ask user

禁止在可由 evidence 解決時先問使用者。


# v14 Requirements / SoC Scenario / Change Impact

One-click workflow 新增三個 mandatory intelligence stages：

A. Requirements Traceability
Project Model 後建立 Requirement → vPlan → Test → Checker/Coverage → Result → Signoff trace。

B. SoC Scenario Planner
當 scope = subsystem / multi-subsystem / SoC 時，建立 cross-subsystem / cross-protocol / shared-resource / E2E scenarios。

C. Verification Change Impact
Git 修改前後建立 change impact，決定 Targeted + Dependency + Safety regression。

更新主流程：

Project Model
→ Requirements Traceability
→ SoC Scenario Planner
→ Generic Infrastructure Audit
→ vPlan
→ command/pattern
→ implementation
→ Git Change Impact
→ Commit/Push
→ Build/Verify
→ Smart Regression Selection
→ LSF Regression
→ Requirement Closure
→ Workflow Closure
→ Signoff。
