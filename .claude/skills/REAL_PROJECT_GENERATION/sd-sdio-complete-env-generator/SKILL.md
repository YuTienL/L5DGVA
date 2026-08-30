---
name: sd-sdio-complete-env-generator
description: Generate and close SD/SDIO env with memory/function access flows.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the sd environment-build capability of sd-environment-builder
     (.claude/skills/PROTOCOL_BUILDERS/), which is the variant wired into
     .dv-harness/builder/protocol_builder_registry.json ("sd" entry). This
     file is not referenced by that registry, by any router SKILL.md, or by
     .claude/agents/*.md as of this audit. Prefer sd-environment-builder;
     this file is not deleted pending owner review. -->
# sd-sdio-complete-env-generator

Generate and close SD/SDIO env with memory/function access flows.

## Rules
- Current DUT/spec/VIP evidence is mandatory.
- No guessed VIP APIs.
- Generated source must be compile/smoke-closed before qualification.
- Generator capability must not be confused with production qualification.
