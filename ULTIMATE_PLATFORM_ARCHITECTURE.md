> **Superseded.** This document describes an earlier edition. See START_HERE.md for the current canonical entry point and SENIOR_DV_ENGINEER_FINAL_ARCHITECTURE.md for the current architecture.

# AI Agent Harness L5 — Ultimate Block/IP → Subsystem → Full SoC Verification Platform

## Product Goal
同一套 AI Agent Harness L5，只要替換：
- DUT RTL / source
- Design / Protocol Spec
- PHY documents
- Programming Guide / Register Spec
- VIP package / examples / manual / source / class reference

即可沿同一個受治理的 workflow 建立、驗證、除錯與收斂：
Block/IP → Subsystem → Multi-Subsystem → Full SoC Verification Environment。

## Unified Lifecycle

INPUT DISCOVERY
→ DOCUMENT EXTRACTION / INDEX / VERSION TRACEABILITY
→ DUT / PROTOCOL / ROLE / TOPOLOGY DISCOVERY
→ MULTI-AGENT EVIDENCE ACQUISITION
→ INDEPENDENT SYNTHESIS
→ EVIDENCE TRUTH GATE
→ ENVIRONMENT MANIFEST
→ GENERIC UVM INFRASTRUCTURE
→ PROTOCOL PLUGIN BUILDERS
→ SOC COMPOSITION
→ COMPILE
→ SMOKE SIMULATION (FSDB OFF)
→ SELF-REPAIR
→ BASELINE READY
→ SINGLE VERIFY
→ LSF REGRESSION
→ ONE JOB = ONE AGENT
→ TARGETED FIRST-FAILURE WAVEFORM RERUN WHEN NEEDED
→ BATCH CLOSURE
→ FINAL DEEP AUDIT
→ SIGNOFF-READY

## Common UVM Infrastructure
- tb_top / env
- configuration framework
- agent registry
- virtual sequencer
- dependency/barrier
- scenario registry
- sequence library
- RAL
- scoreboard/reference-model framework
- assertion framework
- functional coverage framework
- error injection
- smoke/regression test registry
- Git / exact SHA / evidence provenance
- stage execution profile

## Protocol Builder Family
- PCIe
- Ethernet
- MIPI CSI-2
- MIPI DSI
- CAN / CAN-FD
- AMBA4 SoC Multi-Master × Multi-Slave
- eMMC
- SD / SDIO
- eDP / DisplayPort
- UCIe
- USB 2.0 / USB 3.x
- Generic protocol adapter

## Full-SoC Composition
Protocol environments are not isolated generators.
The SoC composer integrates generated protocol blocks using:
- address-map registry
- clock/reset domains
- interrupt topology
- DMA/data paths
- memory model
- shared-resource model
- cross-protocol virtual sequences
- dependency/barrier graph
- end-to-end scoreboard
- performance/latency/throughput checks
- power/reset/recovery scenarios
- SoC coverage model


## USB UVM Reference Base

The existing USB UVM environment is bundled as a Golden Reference Base.

It is used to bootstrap generic UVM environment generation through:
Reference Pattern Extraction
-> Generic/Protocol-Specific Classification
-> Protocol Isolation Gate
-> Target Protocol Builder

This accelerates new environment generation while preventing USB-specific assumptions from leaking into PCIe/Ethernet/MIPI/etc.
