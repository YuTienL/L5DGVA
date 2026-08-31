---
name: emmc-real-env-generator
description: Generate eMMC Host/Device UVM environment.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the emmc environment-build capability of emmc-environment-builder
     (.claude/skills/PROTOCOL_BUILDERS/), which is the variant wired into
     .dv-harness/builder/protocol_builder_registry.json ("emmc" entry). This
     file is not referenced by that registry, by any router SKILL.md, or by
     .claude/agents/*.md as of this audit. Prefer emmc-environment-builder;
     this file is not deleted pending owner review. -->
# emmc-real-env-generator

Generate eMMC Host/Device UVM environment.

Current evidence is mandatory. Memory/CLAUDE.md are hints only.
Real VIP API names must be discovered before production compile.
