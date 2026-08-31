---
name: mipi-csi2-real-env-generator
description: Generate CSI-2 UVM environment from current PHY/lane/VC/DT evidence.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the mipi-csi environment-build capability of mipi-csi-environment-builder
     (.claude/skills/PROTOCOL_BUILDERS/), which is the variant wired into
     .dv-harness/builder/protocol_builder_registry.json ("mipi-csi" entry). This
     file is not referenced by that registry, by any router SKILL.md, or by
     .claude/agents/*.md as of this audit. Prefer mipi-csi-environment-builder;
     this file is not deleted pending owner review. -->
# mipi-csi2-real-env-generator

Generate CSI-2 UVM environment from current PHY/lane/VC/DT evidence.

Current evidence is mandatory. Memory/CLAUDE.md are hints only.
Real VIP API names must be discovered before production compile.
