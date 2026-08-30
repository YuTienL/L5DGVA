---
name: amba4-mmxms-complete-env-generator
description: Generate configurable AMBA4 MM×MS env including topology, address map, parallel traffic, ordering, QoS, exclusive, backpressure and scoreboard matrix.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the AMBA4 Multi-Master x Multi-Slave environment-build capability
     of amba4-soc-environment-builder (.claude/skills/PROTOCOL_BUILDERS/), which
     is the variant wired into .dv-harness/builder/protocol_builder_registry.json
     ("amba4-soc" entry). This file is not referenced by that registry, by any
     router SKILL.md, or by .claude/agents/*.md as of this audit. Prefer
     amba4-soc-environment-builder; this file is not deleted pending owner review. -->
# amba4-mmxms-complete-env-generator

Generate configurable AMBA4 MM×MS env including topology, address map, parallel traffic, ordering, QoS, exclusive, backpressure and scoreboard matrix.

## Rules
- Current DUT/spec/VIP evidence is mandatory.
- No guessed VIP APIs.
- Generated source must be compile/smoke-closed before qualification.
- Generator capability must not be confused with production qualification.
