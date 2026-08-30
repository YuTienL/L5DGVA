---
name: edp-production-builder
description: Build eDP Source/Sink/AUX environments with link training, lane/rate and basic video transport qualification.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the edp environment-build capability of edp-environment-builder
     (.claude/skills/PROTOCOL_BUILDERS/), which is the variant wired into
     .dv-harness/builder/protocol_builder_registry.json ("edp" entry). This
     file is not referenced by that registry, by any router SKILL.md, or by
     .claude/agents/*.md as of this audit. Prefer edp-environment-builder;
     this file is not deleted pending owner review. -->
# edp-production-builder

Build eDP Source/Sink/AUX environments with link training, lane/rate and basic video transport qualification.

## Mandatory truth rules
- Inspect current RTL/spec/VIP evidence.
- Old notes and memory are context, not proof.
- Unknown protocol details remain hypotheses.
- Compile/simulation claims require actual execution evidence.
- BUILDER_AVAILABLE is never equivalent to PRODUCTION_QUALIFIED.
