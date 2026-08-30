---
name: edp-complete-env-generator
description: Generate and close eDP env with AUX/link-training/main-link/video hooks.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the edp environment-build capability of edp-environment-builder
     (.claude/skills/PROTOCOL_BUILDERS/), which is the variant wired into
     .dv-harness/builder/protocol_builder_registry.json ("edp" entry). This
     file is not referenced by that registry, by any router SKILL.md, or by
     .claude/agents/*.md as of this audit. Prefer edp-environment-builder;
     this file is not deleted pending owner review. -->
# edp-complete-env-generator

Generate and close eDP env with AUX/link-training/main-link/video hooks.

## Rules
- Current DUT/spec/VIP evidence is mandatory.
- No guessed VIP APIs.
- Generated source must be compile/smoke-closed before qualification.
- Generator capability must not be confused with production qualification.
