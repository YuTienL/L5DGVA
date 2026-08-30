---
name: observability-gap-closure-engine
description: Use regression and coverage to detect missing observability, refine mechanisms, rerun and verify closure.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# observability-gap-closure-engine

Use regression and coverage to detect missing observability, refine mechanisms, rerun and verify closure.

Mandatory:
- Analyze calibrated architecture first.
- Inventory existing scoreboards/checkers/assertions before adding new ones.
- End-to-end compare → scoreboard; semantic rule → checker; local/temporal invariant → assertion.
- Preserve vPlan/feature/evidence traceability.
- Do not assert guessed behavior.
