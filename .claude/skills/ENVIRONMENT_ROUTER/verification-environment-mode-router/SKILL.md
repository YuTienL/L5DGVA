---
name: verification-environment-mode-router
description: Route environment creation into SUBSYSTEM_MODE or SYSTEM_LEVEL_MODE based on explicit user intent.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Verification Environment Mode Router

Before environment generation, determine exactly one mode:

SUBSYSTEM_MODE:
Generate/build a subsystem verification environment such as PCIe, USB, Ethernet, MIPI, CAN-FD, AMBA4, eMMC, SD/SDIO, eDP, UCIe or a new interface.

SYSTEM_LEVEL_MODE:
Select completed subsystem environments from the registry and compose a System-Level/Full-SoC environment.

Do not mix both flows implicitly.
