---
name: amba-fabric-planner
description: 推導 AMBA M×N Master/Slave topology、VIP roles/counts、resource scopes、routing 與 concurrency policy。
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# AMBA M×N Fabric Planner

Inputs:
hierarchy.json
dut_ports.csv
interface_inventory.csv
address map / bridge/interconnect evidence
protocol profile
verification boundary

Produce:
`.dv-workflow/amba_fabric.csv`
`.dv-workflow/amba_resource_map.csv`

Global serialization forbidden.
Different resources default parallel.
Same-resource contention handled locally.
AXI/ACE preserve protocol concurrency.
APB shared VIP may locally serialize.
AXI-Stream uses stream-local flow-control.
