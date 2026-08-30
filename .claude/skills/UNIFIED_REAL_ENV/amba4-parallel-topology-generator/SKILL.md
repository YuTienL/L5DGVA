---
name: amba4-parallel-topology-generator
description: Preserve true Multi-Master × Multi-Slave parallel traffic and scoreboard topology.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the AMBA4 Multi-Master x Multi-Slave environment-build capability
     of amba4-soc-environment-builder (.claude/skills/PROTOCOL_BUILDERS/), which
     is the variant wired into .dv-harness/builder/protocol_builder_registry.json
     ("amba4-soc" entry). This file is not referenced by that registry, by any
     router SKILL.md, or by .claude/agents/*.md as of this audit. Prefer
     amba4-soc-environment-builder; this file is not deleted pending owner review. -->
# amba4-parallel-topology-generator

Preserve true Multi-Master × Multi-Slave parallel traffic and scoreboard topology.

Current evidence is mandatory. No guessed VIP API is allowed for production binding.
