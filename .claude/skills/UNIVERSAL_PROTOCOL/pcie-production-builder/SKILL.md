---
name: pcie-production-builder
description: Build PCIe RC/EP/PHY environments from current RTL/spec/VIP evidence; cover topology, link training, enumeration, config/BAR/interrupt and TLP traffic.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the PCIe environment-build capability of pcie-environment-builder
     (.claude/skills/PROTOCOL_BUILDERS/), which is the variant wired into
     .dv-harness/builder/protocol_builder_registry.json ("pcie" entry). This
     file is not referenced by that registry, by any router SKILL.md, or by
     .claude/agents/*.md as of this audit. Prefer pcie-environment-builder;
     this file is not deleted pending owner review. -->
# pcie-production-builder

Build PCIe RC/EP/PHY environments from current RTL/spec/VIP evidence; cover topology, link training, enumeration, config/BAR/interrupt and TLP traffic.

## Mandatory truth rules
- Inspect current RTL/spec/VIP evidence.
- Old notes and memory are context, not proof.
- Unknown protocol details remain hypotheses.
- Compile/simulation claims require actual execution evidence.
- BUILDER_AVAILABLE is never equivalent to PRODUCTION_QUALIFIED.
