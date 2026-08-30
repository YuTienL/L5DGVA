---
name: ethernet-profile
description: Ethernet DV profile discovering MAC/PCS/PMA/PHY boundary, speed/interface, frame behavior, flow control and optional VLAN/PTP/FEC/autoneg/training features.
allowed-tools: Read Grep Glob PowerShell
---
# Ethernet Profile

Detect:
- DUT boundary/layer: MAC/PCS/PMA/PHY/bridge
- supported speed set
- interface: MII/GMII/RGMII/SGMII/XGMII/USXGMII/serial/other
- clocking
- frame limits/jumbo
- preamble/SFD/addressing
- CRC/FCS
- IPG
- pause/flow control
- VLAN/multicast/filtering if enabled
- PTP if enabled
- PCS/FEC/autoneg/training only if in scope
- error injection/recovery

Do not assume optional Ethernet features are enabled.
