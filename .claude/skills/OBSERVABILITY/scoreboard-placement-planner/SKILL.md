---
name: scoreboard-placement-planner
description: Identify transaction/data-path boundaries that need end-to-end comparison, request-response matching, ordering/routing checking or data-integrity tracking.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# scoreboard-placement-planner

Identify transaction/data-path boundaries that need end-to-end comparison, request-response matching, ordering/routing checking or data-integrity tracking.

Mandatory:
- Analyze calibrated architecture first.
- Inventory existing scoreboards/checkers/assertions before adding new ones.
- End-to-end compare → scoreboard; semantic rule → checker; local/temporal invariant → assertion.
- Preserve vPlan/feature/evidence traceability.
- Do not assert guessed behavior.
