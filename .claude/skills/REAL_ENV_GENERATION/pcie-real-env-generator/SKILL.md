---
name: pcie-real-env-generator
description: Generate PCIe UVM environment then qualify link training/enumeration/basic traffic.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the PCIe environment-build capability of pcie-environment-builder
     (.claude/skills/PROTOCOL_BUILDERS/), which is the variant wired into
     .dv-harness/builder/protocol_builder_registry.json ("pcie" entry). This
     file is not referenced by that registry, by any router SKILL.md, or by
     .claude/agents/*.md as of this audit. Prefer pcie-environment-builder;
     this file is not deleted pending owner review. -->
# pcie-real-env-generator

Generate PCIe UVM environment then qualify link training/enumeration/basic traffic.

Current evidence is mandatory. Memory/CLAUDE.md are hints only.
Real VIP API names must be discovered before production compile.
