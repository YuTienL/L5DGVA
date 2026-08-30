---
name: usb-production-builder
description: Build USB2/USB3 Host/Device environments from current evidence; cover attach/enumeration, transfer types and USB3 link behavior as applicable.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the usb environment-build capability of usb-environment-builder
     (.claude/skills/PROTOCOL_BUILDERS/), which is the variant wired into
     .dv-harness/builder/protocol_builder_registry.json ("usb" entry). This
     file is not referenced by that registry, by any router SKILL.md, or by
     .claude/agents/*.md as of this audit. Prefer usb-environment-builder;
     this file is not deleted pending owner review. -->
# usb-production-builder

Build USB2/USB3 Host/Device environments from current evidence; cover attach/enumeration, transfer types and USB3 link behavior as applicable.

## Mandatory truth rules
- Inspect current RTL/spec/VIP evidence.
- Old notes and memory are context, not proof.
- Unknown protocol details remain hypotheses.
- Compile/simulation claims require actual execution evidence.
- BUILDER_AVAILABLE is never equivalent to PRODUCTION_QUALIFIED.
