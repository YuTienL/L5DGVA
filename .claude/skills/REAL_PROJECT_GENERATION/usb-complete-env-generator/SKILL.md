---
name: usb-complete-env-generator
description: Generate and close USB2/USB3 env while reusing only generic USB reference architecture patterns.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the usb environment-build capability of usb-environment-builder
     (.claude/skills/PROTOCOL_BUILDERS/), which is the variant wired into
     .dv-harness/builder/protocol_builder_registry.json ("usb" entry). This
     file is not referenced by that registry, by any router SKILL.md, or by
     .claude/agents/*.md as of this audit. Prefer usb-environment-builder;
     this file is not deleted pending owner review. -->
# usb-complete-env-generator

Generate and close USB2/USB3 env while reusing only generic USB reference architecture patterns.

## Rules
- Current DUT/spec/VIP evidence is mandatory.
- No guessed VIP APIs.
- Generated source must be compile/smoke-closed before qualification.
- Generator capability must not be confused with production qualification.
