---
name: new-spec-complete-env-upgrader
description: Diff a new spec revision, update affected semantics/source and force requalification.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# new-spec-complete-env-upgrader

Diff a new spec revision, update affected semantics/source and force requalification.

## Rules
- Current DUT/spec/VIP evidence is mandatory.
- No guessed VIP APIs.
- Generated source must be compile/smoke-closed before qualification.
- Generator capability must not be confused with production qualification.
