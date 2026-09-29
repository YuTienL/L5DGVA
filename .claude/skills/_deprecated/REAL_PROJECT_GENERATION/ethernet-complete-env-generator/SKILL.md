---
name: ethernet-complete-env-generator
description: Generate and close Ethernet env including link/frame/checking/coverage hooks.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the ethernet environment-build capability of ethernet-environment-builder
     (.claude/skills/PROTOCOL_BUILDERS/), which is the variant wired into
     .dv-harness/builder/protocol_builder_registry.json ("ethernet" entry). This
     file is not referenced by that registry, by any router SKILL.md, or by
     .claude/agents/*.md as of this audit. Prefer ethernet-environment-builder;
     this file is not deleted pending owner review. -->
# ethernet-complete-env-generator

Generate and close Ethernet env including link/frame/checking/coverage hooks.

## Rules
- Current DUT/spec/VIP evidence is mandatory.
- No guessed VIP APIs.
- Generated source must be compile/smoke-closed before qualification.
- Generator capability must not be confused with production qualification.
