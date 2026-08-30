> See START_HERE.md for the canonical entry point and current mechanism overview; this page remains accurate for its specific topic.

# vPlan Intake Wizard

## Step 1 — Choose scope
First ask:
1. Are we generating a Subsystem vPlan or System-Level / Full-SoC vPlan?
2. What is the target name?
3. For System-Level, exactly which completed subsystems are selected?

## Step 2 — Derive the next questions from scope
Subsystem:
- protocol / role / topology / boundary
- target spec revision
- DUT supported and explicitly unsupported features
- interface, PHY, clock/reset, register/programming information
- RTL interface evidence
- VIP evidence
- existing verification assets

System-Level:
- subsystem identities and qualification states
- system use cases / end-to-end scenarios
- cross-subsystem data paths
- boot/configuration dependencies
- clock/reset/power dependencies
- address map, DMA and interrupt routing
- concurrency/performance/QoS
- unsupported subsystem combinations

## Step 3 — Build evidence database
Normalize all supplied files into:
Spec Requirement DB
+ DUT Support Matrix
+ Interface/PHY DB
+ Register/Programming DB
+ VIP Capability DB
+ Existing Verification Asset DB
+ Waiver DB
+ System Scenario DB.

## Step 4 — Readiness Gate
Do not create the final vPlan if essential source evidence is still missing.
Return:
READY_FOR_VPLAN
or
COLLECTING with exact missing items.

## Step 5 — vPlan + Feature Mapping
When ready:
Spec Requirement → Feature → Subsystem Owner/Participants → vPlan Requirement
→ Testcase/Sequence → Checker/Assertion → Coverage → Evidence → Verified/Waived.

## Goal
100% Spec Coverage Accounting:
VERIFIED + approved design-spec-backed WAIVED + validated NOT_APPLICABLE = all requirements.
