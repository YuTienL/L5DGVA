---
name: tb-topology-planner
description: Synthesizes the required block/branch_a*/branch_fw/branch_b* testbench topology from DUT and VIP port inventories.
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# Testbench Topology Planner

Canonical architecture:

BLOCK
  |
  +-- branch_a0..N  = DUT-side branches; count follows relevant DUT ports
  |
  +-- branch_fw     = framework/routing/adaptation/scenario-dispatch layer
  |
  +-- branch_b0..M  = VIP-side branches; count follows required VIP ports/instances

A-side and B-side are not assumed 1:1.
Support N:M mapping.

`branch_fw` responsibilities may include:
- routing
- adaptation
- protocol configuration
- command dispatch
- transaction mapping
- synchronization/barriers
- monitor aggregation

Produce:
`.dv-workflow/tb_topology.json`
`.dv-workflow/branch_a.csv`
`.dv-workflow/branch_fw.csv`
`.dv-workflow/branch_b.csv`

Never generate branch counts before hierarchy, DUT-port and VIP topology are known.


# Resource-Scoped Concurrency
branch_fw 不得設計成 Global Scheduler。
AMBA 支援 Multi-Master × Multi-Slave M×N。
每個 shared Slave/target 建立 local arbitration；不同 target 預設 parallel。
AXI/ACE 保留 channel/ID/outstanding/order；APB shared resource 可 local serialize；AXI-Stream 使用 stream-local flow-control。


# BLOCK / branch-A / branch_fw / branch-B 最終語意

BLOCK
├── branch_a0..N : DUT-side port/interface adaptation
├── branch_fw    : Interrupt/Event-driven firmware command dispatcher
└── branch_b0..M : VIP testing scenarios / patterns / sequences

branch-A 數量依 DUT port/topology。
branch-B 數量依 VIP port/instance/topology。
A 與 B 不要求 1:1。

branch_fw：
IRQ/Event → decode/map → branch-B dispatch。
不做全域 scheduler。
