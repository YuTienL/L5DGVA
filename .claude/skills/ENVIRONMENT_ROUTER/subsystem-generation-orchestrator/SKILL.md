---
name: subsystem-generation-orchestrator
description: Orchestrate protocol/subsystem-specific environment generation from DUT+Spec+VIP through baseline-ready registration.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Subsystem Generation Orchestrator

Flow:
User Goal
-> Evidence Acquisition
-> Protocol Builder
-> Environment Manifest
-> UVM Generation
-> Compile
-> Smoke
-> Self-Repair
-> BASELINE_READY
-> Register in Subsystem Environment Registry
