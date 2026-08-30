---
name: project-model
description: Evidence-backed SoC/DV project model with hierarchy, topology, VIP/TB/command models, confidence and blocking status.
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# Project Model

Maintain `.dv-workflow/project_model.json` and `.dv-workflow/evidence.csv`.

Every important fact:
Item,Value,Source,Confidence,Blocking,Notes

Confidence:
HIGH explicit authoritative evidence
MEDIUM strong current inference
LOW weak/ambiguous/stale evidence
UNKNOWN no reliable evidence

Never silently promote LOW/UNKNOWN.

Model sections:
- DUT / SoC hierarchy
- DUT port inventory
- protocol configuration
- interface/verification boundaries
- VIP topology/binding
- TB topology: block/branch_a/branch_fw/branch_b
- existing command capability
- vPlan-required scenarios
- command gap/mapping
- build/test/regression
- checker/coverage
- assumptions/open questions

Blocking means the ambiguity materially changes topology, binding, protocol behavior, command semantics, expected results or verification scope.


# Reference Environment Model

Project Model 必須能記錄：

reference_environment:
- enabled
- type = USB_UVM
- server
- path
- mode = READ_ONLY
- branch/tag/commit
- authoritative = false
- extracted_patterns
- source/confidence

Reference evidence 不能覆蓋當前 DUT/RTL/config 的 authoritative evidence。


# AMBA Fabric Model
記錄 M/N、Master/Slave inventory、address map、shared resource scope、VIP topology、arbitration scope、concurrency policy、AXI outstanding/ID/order limits、AXI-Stream flow-control。


# Generic System Scope Model

記錄：
verification_scope = block / subsystem / multi-subsystem / soc
subsystems
instances
ports/interfaces
protocols
verification boundaries
clock/reset domains
interrupt/event dependencies
shared resources
DMA paths
end-to-end datapaths
cross-subsystem scenarios
system-level performance dimensions
system-level coverage dimensions
