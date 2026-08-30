---
name: observability-traceability-linker
description: Link every scoreboard/checker/assertion to architecture nodes, vPlan requirements, features, coverage and regression evidence.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# observability-traceability-linker

Link every scoreboard/checker/assertion to architecture nodes, vPlan requirements, features, coverage and regression evidence.

Mandatory:
- Analyze calibrated architecture first.
- Inventory existing scoreboards/checkers/assertions before adding new ones.
- End-to-end compare → scoreboard; semantic rule → checker; local/temporal invariant → assertion.
- Preserve vPlan/feature/evidence traceability.
- Do not assert guessed behavior.
