---
name: soc-system-level-env-composer
description: Compose selected validated subsystem environments into one System-Level/SoC UVM environment without regenerating subsystem internals.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# soc-system-level-env-composer

Core rule: use completed BASELINE_READY/VERIFIED subsystem environments as reusable blocks.
System-Level composition must add integration, not silently regenerate the subsystem environment.
All selections and compatibility decisions must be grounded in current evidence and user requirements.
