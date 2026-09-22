> See START_HERE.md for the canonical entry point and current mechanism overview; this page remains accurate for its specific topic.

# DUT Architecture Discovery & Regression Calibration

## Flow
Current RTL / Design Spec / Register / Clock-Reset / Address Map / Interface Docs
→ DUT Architecture Discovery
→ Architecture Model
→ vPlan Feature/Requirement Mapping
→ Architecture-Aware UVM Environment
→ Compile / Smoke / Regression
→ Evidence
→ Compare Observed Behavior vs Architecture Model
→ Correct Wrong Assumptions
→ Impact Analysis
→ Patch Architecture Model + vPlan + Env + Tests + Checkers
→ Rerun
→ Architecture Confidence Promotion.

## Key principle
A failure is not automatically a DUT bug.
First classify whether the failure comes from:
- DUT implementation,
- wrong architecture assumption,
- wrong VIP binding/configuration,
- wrong verification environment topology,
- wrong checker/reference model,
- incomplete vPlan requirement,
- test stimulus/configuration.

The architecture model is continuously calibrated by real verification evidence.
