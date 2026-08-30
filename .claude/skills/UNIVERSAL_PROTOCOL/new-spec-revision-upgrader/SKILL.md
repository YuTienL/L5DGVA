---
name: new-spec-revision-upgrader
description: Diff a new specification revision against a qualified baseline, update only impacted verification components and force re-qualification.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# new-spec-revision-upgrader

Diff a new specification revision against a qualified baseline, update only impacted verification components and force re-qualification.

## Mandatory truth rules
- Inspect current RTL/spec/VIP evidence.
- Old notes and memory are context, not proof.
- Unknown protocol details remain hypotheses.
- Compile/simulation claims require actual execution evidence.
- BUILDER_AVAILABLE is never equivalent to PRODUCTION_QUALIFIED.
