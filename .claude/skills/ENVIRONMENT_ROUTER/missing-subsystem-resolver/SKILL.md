---
name: missing-subsystem-resolver
description: Detect required subsystem environments missing from the registry, build them through SUBSYSTEM_MODE, then return to the System-Level composition flow.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# Missing Subsystem Resolver

Do not silently omit required subsystems.
If a required subsystem is absent/stale/incompatible:
1. report it,
2. route to SUBSYSTEM_MODE,
3. build/verify/register it,
4. return to SYSTEM_LEVEL_MODE,
5. rerun compatibility analysis.
