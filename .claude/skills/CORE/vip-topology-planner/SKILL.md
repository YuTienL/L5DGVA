---
name: vip-topology-planner
description: Derives VIP type, complementary role, count, mode and bind point from DUT hierarchy, port inventory, protocol profile and verification scope.
allowed-tools: Read Grep Glob PowerShell
---
# VIP Topology Planner

VIP requirement =
DUT instance + DUT port + protocol + DUT role + interface boundary + verification scope.

Examples:
USB Host DUT -> Device VIP
USB Device DUT -> Host VIP
PCIe EP -> RC VIP
PCIe RC -> EP VIP
CSI-2 RX -> TX VIP
CSI-2 TX -> RX VIP
DSI Host/TX -> Peripheral/RX VIP
AXI Master -> Slave VIP
AXI Slave -> Master VIP
CAN-FD controller -> peer node/bus VIP

Determine independently:
- VIP_TYPE
- VIP_ROLE
- VIP_COUNT
- ACTIVE / PASSIVE / MONITOR_ONLY
- BIND_POINT
- DUT_PORT
- VIP_PORT
- CLOCK / RESET
- protocol configuration
- source/confidence

Do not assume one protocol equals one VIP.
Do not assume every internal AMBA interface requires an active VIP.
Do not bind until the verification boundary is established.

Produce `.dv-workflow/vip_topology.csv` and `.dv-workflow/vip_binding.csv`.
