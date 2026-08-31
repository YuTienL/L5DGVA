---
name: usb-real-env-generator
description: Generate USB2/USB3 Host/Device UVM environments from current evidence.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the usb environment-build capability of usb-environment-builder
     (.claude/skills/PROTOCOL_BUILDERS/), which is the variant wired into
     .dv-harness/builder/protocol_builder_registry.json ("usb" entry). This
     file is not referenced by that registry, by any router SKILL.md, or by
     .claude/agents/*.md as of this audit. Prefer usb-environment-builder;
     this file is not deleted pending owner review. -->
# usb-real-env-generator

Generate USB2/USB3 Host/Device UVM environments from current evidence.

Current evidence is mandatory. Memory/CLAUDE.md are hints only.
Real VIP API names must be discovered before production compile.
