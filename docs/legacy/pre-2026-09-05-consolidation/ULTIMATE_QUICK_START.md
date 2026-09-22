> **Superseded.** This document describes an earlier edition. See START_HERE.md for the current canonical entry point and SENIOR_DV_ENGINEER_FINAL_ARCHITECTURE.md for the current architecture.

# Ultimate Quick Start

## Goal Example
「針對這個 DUT，讀取 RTL + Spec + VIP，建立可 compile/smoke-test 的 UVM verification environment。」

Harness must:
1. Declare LOCAL_ANALYSIS or REMOTE_EXECUTION.
2. Discover DUT / documents / VIP.
3. Detect protocol(s), roles, topology and boundaries.
4. Launch protocol-specific evidence agents.
5. Produce Environment Manifest.
6. Generate common UVM infrastructure.
7. Invoke protocol builder(s).
8. If subsystem/SoC: invoke SoC composer.
9. Compile.
10. Smoke simulation with FSDB OFF.
11. Self-repair failures.
12. Promote only evidence-backed PASS baseline.
13. Run LSF regression.
14. Close findings.
15. Final deep audit.

## Supported Builder Family
PCIe / Ethernet / MIPI CSI-2 / MIPI DSI / CAN-FD /
AMBA4 Multi-Master × Multi-Slave / eMMC / SD-SDIO /
eDP-DisplayPort / UCIe / USB 2.0-3.x / Generic.
