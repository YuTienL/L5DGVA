---
name: mipi-dsi-production-builder
description: Build DSI Host/Device environments from current evidence with command/video mode, PHY, packet/ECC/CRC qualification.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the mipi-dsi environment-build capability of mipi-dsi-environment-builder
     (.claude/skills/PROTOCOL_BUILDERS/), which is the variant wired into
     .dv-harness/builder/protocol_builder_registry.json ("mipi-dsi" entry). This
     file is not referenced by that registry, by any router SKILL.md, or by
     .claude/agents/*.md as of this audit. Prefer mipi-dsi-environment-builder;
     this file is not deleted pending owner review. -->
# mipi-dsi-production-builder

Build DSI Host/Device environments from current evidence with command/video mode, PHY, packet/ECC/CRC qualification.

## Mandatory truth rules
- Inspect current RTL/spec/VIP evidence.
- Old notes and memory are context, not proof.
- Unknown protocol details remain hypotheses.
- Compile/simulation claims require actual execution evidence.
- BUILDER_AVAILABLE is never equivalent to PRODUCTION_QUALIFIED.
