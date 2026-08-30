---
name: sd-sdio-real-env-generator
description: Generate SD/SDIO Host/Card/Function UVM environment.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the sd environment-build capability of sd-environment-builder
     (.claude/skills/PROTOCOL_BUILDERS/), which is the variant wired into
     .dv-harness/builder/protocol_builder_registry.json ("sd" entry). This
     file is not referenced by that registry, by any router SKILL.md, or by
     .claude/agents/*.md as of this audit. Prefer sd-environment-builder;
     this file is not deleted pending owner review. -->
# sd-sdio-real-env-generator

Generate SD/SDIO Host/Card/Function UVM environment.

Current evidence is mandatory. Memory/CLAUDE.md are hints only.
Real VIP API names must be discovered before production compile.
