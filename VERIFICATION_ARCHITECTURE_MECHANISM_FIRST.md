> **The entry point is START_HERE.md.** This page is the detailed verification-workflow-order reference it links to -- see also SENIOR_DV_ENGINEER_FINAL_ARCHITECTURE.md and FINAL_PACKAGE_INDEX.md.

# DV Agent Harness L5 — Verification Architecture & Mechanism Before Test Generation

## Correct Senior-DV order

> Corrected 2026-08-28: vPlan is drafted incrementally starting in step 1
> (v0.1 from Requirement Extraction) but its detailed, locked version comes
> AFTER DUT Architecture Discovery/Calibration and Protocol Capability
> Discovery, not before — see dv_harness/models.py's Stage enum, the actual
> executing order, confirmed with the project owner 2026-08-27/28.

1. Requirement / Spec Intake (Five Source Discovery + DE Baseline
   Reproduction; vPlan v0.1 draft started here)
2. DUT Architecture Discovery & Calibration (RTL-first, BASELINE_LOCKED →
   Architecture LOCK)
3. Protocol Capability Discovery
4. vPlan (finalized/LOCKed here, informed by steps 1-3)
5. Verification Architecture & Mechanism Planning
6. Test / Sequence / Scenario Generation
7. Build / Smoke / Regression
8. Coverage & Quality Analysis
9. Failure Triage & Attribution
10. Waveform Root Cause / First Bad Event
11. Fix & Verification Environment Calibration
12. DV Expert Feedback
13. Experience Learning

## Why mechanism planning comes first

A testcase has no verification value unless the environment already knows:
- what to observe,
- how to predict the expected result,
- where to compare,
- what protocol/semantic rules to check,
- what temporal invariants to assert,
- and what coverage proves the requirement was exercised.

Therefore the planning order is:

Spec Requirement
→ vPlan Requirement
→ DUT Architecture Node / Data Path / State
→ Monitor / Predictor / Scoreboard / Checker / Assertion / Coverage Plan
→ Test / Sequence / Scenario
→ Regression Evidence.

Mechanism implementation remains iterative. Test generation and regression may expose observability gaps, which feed back into mechanism calibration.
