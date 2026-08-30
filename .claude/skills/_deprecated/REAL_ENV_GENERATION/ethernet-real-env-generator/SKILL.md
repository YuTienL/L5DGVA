---
name: ethernet-real-env-generator
description: Generate Ethernet UVM environment from current MAC/PCS/PMA/PHY evidence.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the ethernet environment-build capability of ethernet-environment-builder
     (.claude/skills/PROTOCOL_BUILDERS/), which is the variant wired into
     .dv-harness/builder/protocol_builder_registry.json ("ethernet" entry). This
     file is not referenced by that registry, by any router SKILL.md, or by
     .claude/agents/*.md as of this audit. Prefer ethernet-environment-builder;
     this file is not deleted pending owner review. -->
# ethernet-real-env-generator

Generate Ethernet UVM environment from current MAC/PCS/PMA/PHY evidence.

Current evidence is mandatory. Memory/CLAUDE.md are hints only.
Real VIP API names must be discovered before production compile.
