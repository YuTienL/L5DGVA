---
name: sd-sdio-production-builder
description: Build SD/SDIO Host/Device environments with SD memory and SDIO function discovery, command/data and mode qualification.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the sd environment-build capability of sd-environment-builder
     (.claude/skills/PROTOCOL_BUILDERS/), which is the variant wired into
     .dv-harness/builder/protocol_builder_registry.json ("sd" entry). This
     file is not referenced by that registry, by any router SKILL.md, or by
     .claude/agents/*.md as of this audit. Prefer sd-environment-builder;
     this file is not deleted pending owner review. -->
# sd-sdio-production-builder

Build SD/SDIO Host/Device environments with SD memory and SDIO function discovery, command/data and mode qualification.

## Mandatory truth rules
- Inspect current RTL/spec/VIP evidence.
- Old notes and memory are context, not proof.
- Unknown protocol details remain hypotheses.
- Compile/simulation claims require actual execution evidence.
- BUILDER_AVAILABLE is never equivalent to PRODUCTION_QUALIFIED.
