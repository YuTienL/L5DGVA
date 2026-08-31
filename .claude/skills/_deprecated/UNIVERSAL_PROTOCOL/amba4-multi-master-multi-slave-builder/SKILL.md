---
name: amba4-multi-master-multi-slave-builder
description: Build configurable AMBA4 multi-master x multi-slave environments with address map, IDs, outstanding, ordering, QoS, exclusive, backpressure and concurrency.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---

<!-- NOTICE (added during industrial-grade audit, 2026-08-28): this skill
     duplicates the AMBA4 Multi-Master x Multi-Slave environment-build capability
     of amba4-soc-environment-builder (.claude/skills/PROTOCOL_BUILDERS/), which
     is the variant wired into .dv-harness/builder/protocol_builder_registry.json
     ("amba4-soc" entry). This file is not referenced by that registry, by any
     router SKILL.md, or by .claude/agents/*.md as of this audit. Prefer
     amba4-soc-environment-builder; this file is not deleted pending owner review. -->
# amba4-multi-master-multi-slave-builder

Build configurable AMBA4 multi-master x multi-slave environments with address map, IDs, outstanding, ordering, QoS, exclusive, backpressure and concurrency.

## Mandatory truth rules
- Inspect current RTL/spec/VIP evidence.
- Old notes and memory are context, not proof.
- Unknown protocol details remain hypotheses.
- Compile/simulation claims require actual execution evidence.
- BUILDER_AVAILABLE is never equivalent to PRODUCTION_QUALIFIED.
