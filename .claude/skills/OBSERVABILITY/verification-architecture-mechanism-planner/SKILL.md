---
name: verification-architecture-mechanism-planner
description: Plan monitors, predictors/reference models, scoreboards, semantic checkers, assertions and coverage points after DUT architecture discovery and before testcase generation.
allowed-tools: Read Grep Glob Edit Write PowerShell Skill
---
# verification-architecture-mechanism-planner

Mandatory order:
vPlan → DUT Architecture Discovery → Verification Architecture & Mechanism Planning → Test Generation.

For every requirement/feature:
1. identify observability points,
2. decide expected-model strategy,
3. decide scoreboard/checker/assertion responsibility,
4. decide coverage proof,
5. only then generate tests/scenarios.

Implementation may be refined after regression, but the verification mechanism architecture must exist before testcase generation.
