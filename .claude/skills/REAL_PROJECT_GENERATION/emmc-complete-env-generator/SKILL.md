---
name: emmc-complete-env-generator
description: Generate and close eMMC env with identify/select/read/write/mode hooks.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the emmc environment-build capability of emmc-environment-builder
     (.claude/skills/PROTOCOL_BUILDERS/), which is the variant wired into
     .dv-harness/builder/protocol_builder_registry.json ("emmc" entry). This
     file is not referenced by that registry, by any router SKILL.md, or by
     .claude/agents/*.md as of this audit. Prefer emmc-environment-builder;
     this file is not deleted pending owner review. -->
# emmc-complete-env-generator

Generate and close eMMC env with identify/select/read/write/mode hooks.

## Rules
- Current DUT/spec/VIP evidence is mandatory.
- No guessed VIP APIs.
- Generated source must be compile/smoke-closed before qualification.
- Generator capability must not be confused with production qualification.
