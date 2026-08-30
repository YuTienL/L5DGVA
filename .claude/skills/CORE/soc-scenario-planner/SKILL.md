---
name: soc-scenario-planner
description: 從 Block/Subsystem 到 Full SoC 建立跨 subsystem、跨 protocol、共享資源與 end-to-end 的 system-level verification scenarios。
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# SoC Scenario Planner

## 核心
SoC verification 不是把各 protocol testcase 相加。

必須建立：
Producer
→ Interface/Protocol
→ Interconnect
→ Shared Resource/Memory/DMA
→ Processing
→ Consumer
→ Interrupt/Event/Firmware
→ End-to-End Checker

## Discovery
分析：
- subsystem instances
- producer/consumer
- data/control paths
- DMA/memory paths
- interrupt/event paths
- shared resources
- clock/reset boundaries
- protocol conversion
- concurrent traffic
- dependencies
- error/recovery paths

## Scenario Classes

### Functional E2E
例：
Input subsystem → DMA → DDR → processing → output subsystem

### Cross-Protocol
USB ↔ AXI
PCIe ↔ AXI
Ethernet ↔ DMA/DDR
CSI-2 ↔ ISP/DDR ↔ DSI
CAN-FD ↔ SoC bus/CPU

實際 scenario 必須由 project evidence 決定，不因例子自動生成不存在的 path。

### Concurrency
多 subsystem 同時 traffic。
檢查 bandwidth、resource contention、ordering、isolation、starvation。

### Reset/Recovery
traffic 中 reset/re-init/recovery。

### Error Propagation
protocol error / DMA error / timeout / resource error 到 system response。

### Performance
end-to-end throughput / latency / bottleneck。

## Scenario Record
SCENARIO_ID
SCOPE
SOURCE_SUBSYSTEM
DEST_SUBSYSTEM
INTERMEDIATE_PATH
PROTOCOLS
SHARED_RESOURCES
TRIGGER
PRECONDITION
TRAFFIC
CONCURRENCY
EXPECTED_DATA
EXPECTED_EVENTS
CHECKERS
COVERAGE
PATTERNS
PRIORITY
EVIDENCE
STATUS

## branch_fw Rule
branch_fw 僅是 IRQ/Event command/control dispatch。
不得被建模成 SoC traffic scheduler。

## Output
`.dv-workflow/soc_scenarios.csv`
`.dv-workflow/soc_scenario_gap_report.md`

所有 scenario gap 送入 vPlan + workflow closure。
