> **Superseded.** This file's "canonical baseline" claim predates the current canonical set. See START_HERE.md for the current canonical entry point.

# AI Agent Harness L5 — Final Complete Canonical Baseline

This is the single canonical package for the AI Agent Harness L5 verification platform.

## Scope
Block/IP -> Subsystem -> Multi-Subsystem -> Full SoC

## Startup Rule
Every workflow must first declare one mode:

LOCAL_ANALYSIS
「這個是純本地讀檔分析（不碰伺服器、不跑 VCS）。」

REMOTE_EXECUTION
「這個需要連伺服器/跑模擬。」

MIXED
Split into explicit LOCAL_ANALYSIS and REMOTE_EXECUTION phases.

## Evidence Truth
CLAUDE.md, Memory, historical findings, previous agent summaries and guesses are not Current Evidence.

Current engineering truth comes from:
- current RTL/source inspection
- current waveform/FSDB measurement
- current sim.log/assertion/scoreboard/transaction evidence
- current register/programming state
- versioned PHY/programming/VIP documentation
- reproducible rerun evidence

## Simulation Default
Normal simulation/regression:
- FSDB OFF
- VIP trace/report MAY be enabled
- sim.log/UVM/assertion/scoreboard evidence retained

If simulation FAILS:
- analyze low-cost evidence first
- if signal-level evidence is needed, rerun with targeted FSDB
- user confirms waveform scope + level/depth
- stop the debug rerun at the first relevant failure/error/fatal/missing/mismatch
- do not waste time running the full testcase unless required

## Core Architecture
Goal / Requirements
-> Route + Skill Resolver
-> Graph Orchestrator
-> Plan-and-Execute
-> Multi-Agent Evidence Acquisition
-> Blackboard
<-> Claude Project Memory + Verification Memory
-> Independent Synthesis
-> Autonomous Inference
-> Evidence-Grounded ReAct
-> Implementation / Review
-> Git / Exact SHA
-> VCS / Verdi / FSDB
-> LSF One Job = One Agent
-> Batch Closure
-> Final Deep Audit
-> SIGNOFF-READY
