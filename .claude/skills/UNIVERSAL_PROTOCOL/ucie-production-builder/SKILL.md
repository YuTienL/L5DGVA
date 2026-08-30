---
name: ucie-production-builder
description: Build UCIe die-to-die environments from discovered protocol/adapter/PHY boundaries and qualify link/transaction/flow-control/recovery.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the ucie environment-build capability of ucie-environment-builder
     (.claude/skills/PROTOCOL_BUILDERS/), which is the variant wired into
     .dv-harness/builder/protocol_builder_registry.json ("ucie" entry). This
     file is not referenced by that registry, by any router SKILL.md, or by
     .claude/agents/*.md as of this audit. Prefer ucie-environment-builder;
     this file is not deleted pending owner review. -->
# ucie-production-builder

Build UCIe die-to-die environments from discovered protocol/adapter/PHY boundaries and qualify link/transaction/flow-control/recovery.

## Mandatory truth rules
- Inspect current RTL/spec/VIP evidence.
- Old notes and memory are context, not proof.
- Unknown protocol details remain hypotheses.
- Compile/simulation claims require actual execution evidence.
- BUILDER_AVAILABLE is never equivalent to PRODUCTION_QUALIFIED.
