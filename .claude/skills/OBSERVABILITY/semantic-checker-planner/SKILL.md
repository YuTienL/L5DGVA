---
name: semantic-checker-planner
description: Identify protocol/state/configuration/address/interrupt/response semantics that require explicit checkers.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# semantic-checker-planner

Identify protocol/state/configuration/address/interrupt/response semantics that require explicit checkers.

Mandatory:
- Analyze calibrated architecture first.
- Inventory existing scoreboards/checkers/assertions before adding new ones.
- End-to-end compare → scoreboard; semantic rule → checker; local/temporal invariant → assertion.
- Preserve vPlan/feature/evidence traceability.
- Do not assert guessed behavior.
