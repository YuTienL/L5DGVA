> **Superseded.** This document describes an earlier edition. See START_HERE.md for the current canonical entry point and SENIOR_DV_ENGINEER_FINAL_ARCHITECTURE.md for the current architecture.

# DE + DV Industrial Workflow v8 — 一頁式架構

```text
User / DE / DV
      ↓
dv-workflow
      ↓
Intake + Reference USB UVM + SoC Hierarchy
      ↓
Protocol / DUT Port / VIP Topology
      ↓
BLOCK
├─ branch-a0..N : DUT side
├─ branch_fw    : Interrupt/Event-driven Dispatcher
└─ branch-b0..M : VIP Testing Scenarios
      ↓
Project Model + Readiness
      ↓
vPlan
      ↓
command.txt / Pattern
      ↓
Single Simulation
      ├─ FAIL → Log + FSDB/fsdbreport → Verdi → Fix → Build → Verify → Rerun
      └─ PASS → WAVE evidence → Auto Promotion
                                ↓
                         Regression List
                                ↓
                         LSF Regression
                                ↓
                      Monitor / Cluster / Report
                                ↓
                             Signoff
```

## branch_fw
IRQ/Event → decode → map → branch-B → VIP scenario → response → clear/ack。
不是 Global Scheduler。

## branch-B
VIP testing scenario / pattern / sequence layer。
數量由 VIP port/instance/topology 決定。

## Simulation Options
WAVE=0/1
PA=0/1
FSDB_START
FSDB_STOP
TIMEOUT

## Defaults
Regression: WAVE=0, PA=0, Coverage=OFF
Representative verify: WAVE=1, FSDB_START=0, FSDB_STOP=simulation_end, Coverage=OFF
