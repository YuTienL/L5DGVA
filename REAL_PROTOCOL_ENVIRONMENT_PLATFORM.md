> **See CREATE_ENVIRONMENT.md** for the current, consolidated procedural guide covering this topic.

# DV Agent Harness L5 — Real Protocol Environment Platform

## Goal
Generate real UVM verification environments for:
PCIe, USB, Ethernet, MIPI CSI-2, MIPI DSI,
AMBA4 Multi-Master × Multi-Slave, eDP, eMMC, SD/SDIO, UCIe,
plus future New Interface / New Specification revisions.

## Real Generation Flow
Current DUT RTL
+ Current Spec / PHY / Register docs
+ Current VIP install/docs/examples/source/class reference
→ DUT Interface Extractor
→ VIP API Learner
→ Multi-Agent Evidence Synthesis
→ Protocol Semantic Model
→ VIP Binder or Native UVC
→ Real UVM Code Generator
→ Compile Closure
→ Smoke Closure
→ Qualification
→ Registry
→ Subsystem reuse / System-Level composition.

## Important Truth
This package now includes the machinery needed to perform real project generation.
It still cannot truthfully mark any protocol PRODUCTION_QUALIFIED without access to the real project and successful execution evidence.
