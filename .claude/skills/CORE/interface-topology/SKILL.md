---
name: interface-topology
description: Builds protocol/interface topology from SoC hierarchy, DUT ports, bridges, clock/reset domains and verification boundaries.
allowed-tools: Read Grep Glob PowerShell
---
# Interface Topology

Classify every relevant interface:
protocol, version/mode, role, active/passive candidate, boundary, peer, clock/reset domain.

Recognize protocol-specific boundaries such as:
USB: UTMI/ULPI/PIPE/serial/custom
PCIe: AXI/controller/PIPE/serial
Ethernet: MAC/PCS/PMA/PHY and MII/GMII/RGMII/SGMII/XGMII/USXGMII/serial
MIPI: packet/D-PHY/C-PHY
AMBA: APB/AHB/AXI/ACE-Lite/AXI-Stream
CAN-FD: controller/bus/transceiver abstraction

For AMBA, reconstruct masters, slaves, bridges/interconnect and protocol conversions.

Produce `.dv-workflow/interface_inventory.csv`.
