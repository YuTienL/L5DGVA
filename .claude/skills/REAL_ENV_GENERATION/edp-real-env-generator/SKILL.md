---
name: edp-real-env-generator
description: Generate eDP Source/Sink UVM environment.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the edp environment-build capability of edp-environment-builder
     (.claude/skills/PROTOCOL_BUILDERS/), which is the variant wired into
     .dv-harness/builder/protocol_builder_registry.json ("edp" entry). This
     file is not referenced by that registry, by any router SKILL.md, or by
     .claude/agents/*.md as of this audit. Prefer edp-environment-builder;
     this file is not deleted pending owner review. -->
# edp-real-env-generator

Generate eDP Source/Sink UVM environment.

Current evidence is mandatory. Memory/CLAUDE.md are hints only.
Real VIP API names must be discovered before production compile.
