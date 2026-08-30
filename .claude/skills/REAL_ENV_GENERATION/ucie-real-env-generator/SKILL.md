---
name: ucie-real-env-generator
description: Generate UCIe UVM environment from current protocol/adapter/PHY evidence.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the ucie environment-build capability of ucie-environment-builder
     (.claude/skills/PROTOCOL_BUILDERS/), which is the variant wired into
     .dv-harness/builder/protocol_builder_registry.json ("ucie" entry). This
     file is not referenced by that registry, by any router SKILL.md, or by
     .claude/agents/*.md as of this audit. Prefer ucie-environment-builder;
     this file is not deleted pending owner review. -->
# ucie-real-env-generator

Generate UCIe UVM environment from current protocol/adapter/PHY evidence.

Current evidence is mandatory. Memory/CLAUDE.md are hints only.
Real VIP API names must be discovered before production compile.
