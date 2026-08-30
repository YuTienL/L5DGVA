---
name: subsystem-to-soc-verification
description: Generic DV Workflow 的核心定位：任何 Block / Subsystem / Multi-Subsystem 到 Full SoC Level 的通用驗證。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Any Subsystem → Full SoC Verification

Generic DV Workflow 第一原則：

Block / IP
→ Subsystem
→ Multi-Subsystem
→ Full SoC

全部使用同一套 Workflow。

USB、PCIe、Ethernet、AMBA、MIPI、CAN-FD 都只是 Protocol Profiles，
不是 Core Workflow 本身。

Core 固定處理：
- project intake
- reference environment
- DUT/SoC hierarchy discovery
- verification boundary
- instance/port/interface inventory
- protocol routing
- VIP type/role/count/bind
- BLOCK / branch-A / branch_fw / branch-B topology
- project model / confidence / readiness
- vPlan
- pattern / command.txt
- generic infrastructure audit
- single simulation
- failure recovery
- LSF regression/monitor/report
- waveform/fsdbreport/Verdi
- review/signoff

SoC Level 必須額外分析：
- multi-protocol
- multi-instance
- multi-clock/reset domains
- interrupt/event dependencies
- shared memory / DMA
- shared resources
- end-to-end datapaths
- cross-subsystem scenarios
- heterogeneous configurations
- concurrency
- system-level performance
- system-level coverage
- failure correlation
