> **The entry point is START_HERE.md.** This page is the detailed architecture reference it links to -- see also FINAL_PACKAGE_INDEX.md (package index), VERIFICATION_ARCHITECTURE_MECHANISM_FIRST.md (workflow-order source).

# DV Agent Harness L5 — Senior DV Engineering Reasoning & Closed-Loop Verification Platform

## Product Goal
The target is not "AI that writes UVM". The target is a verification platform that approaches a true senior DV engineer's working method:
understand the specification and DUT, plan verification, choose risk, build observability, run evidence-driven regressions, distinguish DUT/TB/VIP/test/spec failures, find the first bad event, close coverage, and convert expert/debug experience into reusable verification knowledge.

## User-visible operating model

### Environment Mode
1. **Subsystem Environment** — generate one selected PCIe/USB/Ethernet/MIPI/AMBA/eDP/eMMC/SD/SDIO/UCIe/etc. environment.
2. **System-Level / Full-SoC Environment** — user selects qualified subsystem environments; Harness derives cross-subsystem scenarios, dependencies, end-to-end scoreboards/checkers/assertions and system-level vPlan.

### Remote Control Layer
Remote Control is a supervisory layer over either Environment Mode:
STATUS / WHY / EVIDENCE / REVIEW / PAUSE / RESUME / REDIRECT / APPROVE / REJECT / STOP / TAKEOVER.

## Golden closed loop

```text
User Goal / Scope
  ↓
Progressive Intake Wizard
  ↓
Evidence DB + Readiness Gate
  ↓
DUT Architecture Discovery
  ↓
vPlan FIRST + Feature/Requirement Mapping
  ↓
Risk & Protocol Corner-Case Analysis
  ↓
Architecture-Aware UVM Environment
  ↓
Scoreboard / Checker / Assertion Observability Plan
  ↓
Test / Sequence / Scenario Generation
  ↓
Compile → Smoke → Regression
  ↓
Failure?
  ├─ No → Coverage Quality / Spec Coverage Closure
  └─ Yes
       ↓
     Failure Triage & Attribution
       ↓
     DUT / TB / VIP / TEST / SPEC / INFRA / UNKNOWN
       ↓
     Waveform + Transaction Root Cause
       ↓
     First Bad Event + Causal Chain
       ↓
     Correct DUT / Env / VIP Config / Test / Checker / vPlan
       ↓
     Architecture Regression Calibration
       ↓
     Rerun
       ↺
  ↓
DV Expert Review / Feedback
  ↓
Experience Knowledge Capture
  └──────────────────────────────────────────────↺
```

## Definition of 100% Spec Coverage
100% means every in-scope requirement is accounted for by VERIFIED, approved evidence-backed WAIVED, or validated NOT_APPLICABLE status.
Test existence or coverpoint hit alone is not final coverage credit.


## Canonical Flow Update — Mechanism Before Test Generation
Requirement/Spec Intake (vPlan v0.1 draft starts here) → DUT Architecture Discovery & Calibration → Protocol Capability Discovery → vPlan (finalized/LOCKed) → Verification Architecture & Mechanism Planning → Test / Sequence / Scenario Generation → Regression → Coverage → Triage → Root Cause → Calibration → Expert Feedback → Experience Learning. (Corrected 2026-08-28 — see VERIFICATION_ARCHITECTURE_MECHANISM_FIRST.md; architecture discovery precedes vPlan finalization, not the reverse.)
