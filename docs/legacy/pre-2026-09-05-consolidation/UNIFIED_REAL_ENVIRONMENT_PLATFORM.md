> **See CREATE_ENVIRONMENT.md** for the current, consolidated procedural guide covering this topic.

# DV Agent Harness L5 — Unified Real Environment Platform

Built-in real-generation framework:
PCIe, Ethernet, MIPI CSI-2, MIPI DSI,
AMBA4 Multi-Master × Multi-Slave, eDP, eMMC, SD/SDIO, UCIe, USB.

Future:
New Interface / Proprietary Interface / New PHY / New Specification Revision.

Common flow:
Current DUT + Spec + PHY/Register Docs + VIP
→ DUT Interface Discovery
→ VIP API Learning
→ Protocol Semantic Model
→ VIP Binding or Native UVC
→ UVM Code Generation
→ Compile Closure
→ Protocol-Specific Smoke
→ Failure Repair / Rerun
→ Qualification
→ Subsystem Registry
→ System-Level / Full-SoC Composer.

Truth:
GENERATOR_AVAILABLE != PRODUCTION_QUALIFIED.
