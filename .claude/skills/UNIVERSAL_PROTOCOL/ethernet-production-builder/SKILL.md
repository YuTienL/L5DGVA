---
name: ethernet-production-builder
description: Build Ethernet MAC/PCS/PMA verification environments from discovered interface/speed/VIP evidence and qualify frame traffic/checking.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the ethernet environment-build capability of ethernet-environment-builder
     (.claude/skills/PROTOCOL_BUILDERS/), which is the variant wired into
     .dv-harness/builder/protocol_builder_registry.json ("ethernet" entry). This
     file is not referenced by that registry, by any router SKILL.md, or by
     .claude/agents/*.md as of this audit. Prefer ethernet-environment-builder;
     this file is not deleted pending owner review. -->
# ethernet-production-builder

Build Ethernet MAC/PCS/PMA verification environments from discovered interface/speed/VIP evidence and qualify frame traffic/checking.

## Mandatory truth rules
- Inspect current RTL/spec/VIP evidence.
- Old notes and memory are context, not proof.
- Unknown protocol details remain hypotheses.
- Compile/simulation claims require actual execution evidence.
- BUILDER_AVAILABLE is never equivalent to PRODUCTION_QUALIFIED.
