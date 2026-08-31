---
name: protocol-router
description: Detects and routes the primary DV protocol/profile from user intent and repository evidence, including mixed-protocol SoC projects and common aliases/typos.
allowed-tools: Read Grep Glob PowerShell
---
# Protocol Router

Primary routes:

USB -> `USB/usb-profile`
PCIe -> `PCIe/pcie-profile`
Ethernet -> `Ethernet/ethernet-profile`
AMBA -> `AMBA/amba-profile`
MIPI CSI-2 -> `MIPI/csi2-profile`
MIPI DSI -> `MIPI/dsi-profile`
CAN-FD -> `CAN/canfd-profile`
eMMC/MMC -> `PROTOCOL_BUILDERS/emmc-environment-builder`
SD/SDIO -> `PROTOCOL_BUILDERS/sd-environment-builder`

## Profile/VIP-Lookup Binding

After detecting the protocol, read `.dv-harness/builder/protocol_builder_registry.json`'s
entry for it and resolve `profile_skill` and `vip_lookup_skill` (either may
be `null` -- several protocols have no profile skill yet). For every
non-null value, actually read that skill file before proceeding, and
record every consulted skill name in the DISCOVERY/PROTOCOL_CAPABILITY
stage evidence block under `profile_skills_consulted`. This is enforced by
`protocol_profile_binding_gate` at the PROTOCOL_CAPABILITY stage -- it
cross-checks your list against the registry's real values, not your
self-report alone.

USB profile must further resolve Host vs Device.

AMBA profile must further resolve:
APB2/APB3/AHB/AHB-Lite/AXI3/AXI4/ACE-Lite/AXI-Stream.

Normalize:
USB3 / SuperSpeed / SS
PCI Express -> PCIe
CSI2 / CSI-2
CANFD / CAN FD
AMAB4 -> AMBA when contextual
AIX4 -> AXI4 when contextual
AXIS / AXI Stream -> AXI-Stream
MMC -> eMMC/MMC
SDIO -> SD/SDIO

For mixed-protocol SoCs, choose the protocol implicated by:
user intent -> failing test -> active config -> modified files -> subsystem boundary.

Do not make AMBA the primary protocol merely because another DUT uses an AXI/APB backend.

If unresolved after evidence inspection, ask one routing question only.
