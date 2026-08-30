> **The entry point is START_HERE.md.** This page is the detailed package index it links to -- see also SENIOR_DV_ENGINEER_FINAL_ARCHITECTURE.md (architecture), VERIFICATION_ARCHITECTURE_MECHANISM_FIRST.md (workflow-order source).

# DV Agent Harness L5 — Final Senior-DV Package Index

- Edition: `SENIOR_DV_ENGINEER_FINAL`
- Positioning: **Senior DV Engineering Reasoning & Closed-Loop Verification Platform**
- Skills: **315**
- Primary Agents: **15**
- Iron Rules: **290**

## Major capability groups
1. Subsystem Environment Mode
2. System-Level / Full-SoC composition from selected qualified subsystems
3. Remote Control supervisory layer
4. USB UVM reference base and reusable verification references
5. Built-in multi-protocol support + New Interface/New Specification onboarding
6. Progressive vPlan Intake Wizard + Readiness Gate
7. vPlan-first testcase generation + 100% Spec Coverage Accounting
8. command.txt verification taxonomy and clean migration
9. DUT Architecture Discovery
10. Regression Architecture Calibration
11. Scoreboard / Checker / Assertion Analyzer
12. Failure Triage & DUT-vs-TB Attribution
13. Waveform Root Cause / First Bad Event
14. Protocol Corner-Case Intelligence
15. Verification Risk Ranking
16. Coverage Quality Analysis
17. DV Expert Feedback Closed Loop
18. Evidence-backed Experience Knowledge Loop
19. pytest-based self-validation and packaging integrity checks


## Canonical Flow Update — Mechanism Before Test Generation
Requirement/Spec Intake (vPlan v0.1 draft starts here) → DUT Architecture Discovery & Calibration → Protocol Capability Discovery → vPlan (finalized/LOCKed) → Verification Architecture & Mechanism Planning → Test / Sequence / Scenario Generation → Regression → Coverage → Triage → Root Cause → Calibration → Expert Feedback → Experience Learning. (Corrected 2026-08-28 — see VERIFICATION_ARCHITECTURE_MECHANISM_FIRST.md; architecture discovery precedes vPlan finalization, not the reverse.)
