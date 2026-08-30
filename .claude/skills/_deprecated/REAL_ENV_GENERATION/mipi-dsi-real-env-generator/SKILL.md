---
name: mipi-dsi-real-env-generator
description: Generate DSI UVM environment from current command/video/PHY evidence.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the mipi-dsi environment-build capability of mipi-dsi-environment-builder
     (.claude/skills/PROTOCOL_BUILDERS/), which is the variant wired into
     .dv-harness/builder/protocol_builder_registry.json ("mipi-dsi" entry). This
     file is not referenced by that registry, by any router SKILL.md, or by
     .claude/agents/*.md as of this audit. Prefer mipi-dsi-environment-builder;
     this file is not deleted pending owner review. -->
# mipi-dsi-real-env-generator

Generate DSI UVM environment from current command/video/PHY evidence.

Current evidence is mandatory. Memory/CLAUDE.md are hints only.
Real VIP API names must be discovered before production compile.
