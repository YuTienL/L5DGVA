---
name: scoreboard-checker-assertion-analyzer
description: Analyze calibrated DUT architecture, vPlan, regression evidence and coverage gaps to decide where scoreboards, semantic checkers and assertions are required.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# scoreboard-checker-assertion-analyzer

Analyze calibrated DUT architecture, vPlan, regression evidence and coverage gaps to decide where scoreboards, semantic checkers and assertions are required.

Mandatory:
- Analyze calibrated architecture first.
- Inventory existing scoreboards/checkers/assertions before adding new ones.
- End-to-end compare → scoreboard; semantic rule → checker; local/temporal invariant → assertion.
- Preserve vPlan/feature/evidence traceability.
- Do not assert guessed behavior.
