---
name: mipi-csi2-complete-env-generator
description: Generate and close CSI-2 env including PHY/lane/VC/DT/packet/ECC/CRC hooks.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the mipi-csi environment-build capability of mipi-csi-environment-builder
     (.claude/skills/PROTOCOL_BUILDERS/), which is the variant wired into
     .dv-harness/builder/protocol_builder_registry.json ("mipi-csi" entry). This
     file is not referenced by that registry, by any router SKILL.md, or by
     .claude/agents/*.md as of this audit. Prefer mipi-csi-environment-builder;
     this file is not deleted pending owner review. -->
# mipi-csi2-complete-env-generator

Generate and close CSI-2 env including PHY/lane/VC/DT/packet/ECC/CRC hooks.

## Rules
- Current DUT/spec/VIP evidence is mandatory.
- No guessed VIP APIs.
- Generated source must be compile/smoke-closed before qualification.
- Generator capability must not be confused with production qualification.
