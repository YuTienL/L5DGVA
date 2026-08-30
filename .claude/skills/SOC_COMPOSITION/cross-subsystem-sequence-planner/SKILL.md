---
name: cross-subsystem-sequence-planner
description: Build cross-subsystem scenarios and dependency/barrier plans while preserving natural concurrency.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# cross-subsystem-sequence-planner

Core rule: use completed BASELINE_READY/VERIFIED subsystem environments as reusable blocks.
System-Level composition must add integration, not silently regenerate the subsystem environment.
All selections and compatibility decisions must be grounded in current evidence and user requirements.
