---
name: mipi-csi2-production-builder
description: Build CSI-2 TX/RX D-PHY/C-PHY environments from current evidence with lane/VC/data-type/packet/ECC/CRC qualification.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the mipi-csi environment-build capability of mipi-csi-environment-builder
     (.claude/skills/PROTOCOL_BUILDERS/), which is the variant wired into
     .dv-harness/builder/protocol_builder_registry.json ("mipi-csi" entry). This
     file is not referenced by that registry, by any router SKILL.md, or by
     .claude/agents/*.md as of this audit. Prefer mipi-csi-environment-builder;
     this file is not deleted pending owner review. -->
# mipi-csi2-production-builder

Build CSI-2 TX/RX D-PHY/C-PHY environments from current evidence with lane/VC/data-type/packet/ECC/CRC qualification.

## Mandatory truth rules
- Inspect current RTL/spec/VIP evidence.
- Old notes and memory are context, not proof.
- Unknown protocol details remain hypotheses.
- Compile/simulation claims require actual execution evidence.
- BUILDER_AVAILABLE is never equivalent to PRODUCTION_QUALIFIED.
