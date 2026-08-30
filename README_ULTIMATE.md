> **Superseded.** This document describes an earlier edition. See START_HERE.md for the current canonical entry point and SENIOR_DV_ENGINEER_FINAL_ARCHITECTURE.md for the current architecture.

# DV Agent Harness L5 — Ultimate Clean Complete Edition

## 核心定位
Evidence-First + Expert-in-the-Loop + Closed-Loop DV Automation。

同一平台可：
- 產生 IP/Block 或 PCIe、USB、Ethernet、MIPI CSI-2/DSI、AMBA4 MM×MS、eDP、eMMC、SD/SDIO、UCIe Subsystem Environment。
- 選擇已完成且可追溯的 Subsystem，組成 System-Level / Full-SoC Environment。
- 透過 Remote Control 從 PC/Web 控制 Linux Server compile/simulation/regression/debug。
- 接收 DV Expert Review 建議，先視為 Hypothesis，再以 Current Evidence 驗證、Impact、Patch/Regenerate、Requalify。
- 學習未來 New Interface / New Specification Revision。

## Golden Flow
Intent → Execution Mode Declaration → Evidence Acquisition → DUT/Spec/VIP Analysis
→ Protocol Semantic Model → VIP Binding / Native UVC → UVM Generation
→ Compile Closure → Protocol Smoke → First-Failure Debug
→ Targeted Waveform Rerun (if needed) → Regression/Coverage → Qualification
→ DV Expert Review → Feedback Validation → Impact Analysis
→ Patch/Regenerate → Requalification → Registry → System-Level Composition。

## Truth
Generated/Supported 不等於 Production Qualified；真實 qualification 必須有 DUT/VIP/tool execution evidence。
