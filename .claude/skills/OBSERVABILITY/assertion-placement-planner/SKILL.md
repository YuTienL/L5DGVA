---
name: assertion-placement-planner
description: Identify local temporal, handshake, reset/clock, state-transition, stability, FIFO and illegal-condition properties best implemented as assertions.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# assertion-placement-planner

Identify local temporal, handshake, reset/clock, state-transition, stability, FIFO and illegal-condition properties best implemented as assertions.

Mandatory:
- Analyze calibrated architecture first.
- Inventory existing scoreboards/checkers/assertions before adding new ones.
- End-to-end compare → scoreboard; semantic rule → checker; local/temporal invariant → assertion.
- Preserve vPlan/feature/evidence traceability.
- Do not assert guessed behavior.
