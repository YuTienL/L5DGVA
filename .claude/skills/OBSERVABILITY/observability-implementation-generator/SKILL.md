---
name: observability-implementation-generator
description: Generate implementation plans and source skeletons for recommended scoreboards, checkers and assertions.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# observability-implementation-generator

Generate implementation plans and source skeletons for recommended scoreboards, checkers and assertions.

Mandatory:
- Analyze calibrated architecture first.
- Inventory existing scoreboards/checkers/assertions before adding new ones.
- End-to-end compare → scoreboard; semantic rule → checker; local/temporal invariant → assertion.
- Preserve vPlan/feature/evidence traceability.
- Do not assert guessed behavior.
