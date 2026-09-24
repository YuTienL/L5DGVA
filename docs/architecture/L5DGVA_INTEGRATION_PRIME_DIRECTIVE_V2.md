# L5DGVA Integration Prime Directive V2

## Authority and Purpose

After formal adoption, V2 supersedes the prior detailed
`L5DGVA_INTEGRATION_PRIME_DIRECTIVE.md`; V1 remains historical evidence.
V2 complements Article 0, Constitution, OpenSpec, DE/DV HITL, security,
and Master control-plane authority.

## Prime Directive

> **Prioritize connecting and correcting existing but fragmented
> capabilities into the first complete, executable, human-in-the-loop,
> evidence-grounded L5DGVA workflow. Any current-scope defect, missing
> implementation, broken connection, false capability claim, contract
> mismatch, or required Golden-Workflow gap discovered during
> integration must be root-caused, corrected, integrated, tested,
> regression-checked, and evidence-verified before the affected
> capability or workflow may be declared closed.**

``` text
P1 CONNECT BEFORE EXPAND
P2 OPERATIONAL BEFORE CLAIMED
P3 CLOSE THE LOOP
P4 NO CAPABILITY ISLANDS
P5 FIND → FIX → VERIFY
```

## P1 --- Connect Before Expand

Connect existing verified capabilities before non-blocking expansion.
Interrupt closure only for a current Golden-Workflow/correctness
blocker, safety/security requirement, capability-loss prevention,
mandatory current-slice dependency, or approved human/constitutional
requirement. Otherwise REGISTER → OWNER → DEFER → CONTINUE E2E CLOSURE.
Capability count is not an integration KPI.

## P2 --- Operational Before Claimed

``` text
ROADMAP_DEFINED → FOUNDATION → IMPLEMENTED → WIRED → TRIGGERED → CONSUMED → PRODUCTION_CONNECTED → OPERATIONAL → QUALIFIED
```

Production-connected means real supported user/project data flows
through the capability and its output is consumed by the required next
stage.

Invariants: `FOUNDATION != OPERATIONAL`; `IMPLEMENTED != WIRED`;
`WIRED != PRODUCTION_CONNECTED`; `TESTED != CONSUMED`;
`MODULE_EXISTS != RUNTIME_USED`;
`INTERNAL_CALLER != PRODUCTION_CONSUMER`.

## P3 --- Close the Loop

``` text
Input → Discovery → Resolution → HITL → Decision → Execution → Evidence → Validation → Closure → Learning → Reuse
```

`QUESTION_ANSWERED != FIELD_RESOLVED`;
`REGRESSION_RUN != FAILURE_CLASSIFIED`;
`COVERAGE_REPORTED != COVERAGE_CLOSED`;
`KC_STORED != CLOSED_LOOP_LEARNING`; `KC_RETRIEVED != KC_CONSUMED`.

## P4 --- No Capability Islands

Every implemented capability must identify TRIGGER, INPUT, PRODUCER,
OUTPUT, CONSUMER, NEXT_STAGE, EVIDENCE, FAILURE_PATH, HUMAN_AUTHORITY,
PRODUCTION_ENTRY_PATH. Missing intended production
producer/trigger/consumer =\> `CAPABILITY_ISLAND=YES`. Temporary islands
require explicit owner/wave and cannot be called operational.
Current-Golden-Workflow islands fall under P5.

## P5 --- Find → Fix → Verify

Current-scope/correctness issues must not merely be documented.

``` text
DISCOVER → CLASSIFY → ROOT CAUSE → FIX/INTEGRATE → FOCUSED TEST
→ PRODUCER→CONSUMER TEST → PRODUCTION DATAFLOW TEST → E2E VALIDATION
→ REGRESSION → EVIDENCE REVIEW → CORRECTNESS VERIFIED → CLOSE
```

Fix now for: existing capability defects; missing current-scope
implementation; false implementation/wiring claims; broken
producer-consumer edges; current Golden-Workflow islands;
contract/schema defects affecting current correctness; false PASS;
capability loss; uncontrolled governance bypass; current-scope
evidence-integrity defects.

A true future-wave capability may be `REGISTER_AND_DEFER_WITH_OWNER`
only when not required for current correctness/qualification and not
hiding a false current claim.

Every gap gets exactly one disposition:

``` text
FIX_NOW_CURRENT_SCOPE
FIX_NOW_CORRECTNESS_BLOCKER
FIX_NOW_CAPABILITY_LOSS
FIX_NOW_SAFETY_SECURITY
REGISTER_AND_DEFER_WITH_OWNER
SUPERSEDED_WITH_EVIDENCE
NOT_APPLICABLE_WITH_EVIDENCE
HUMAN_DECISION_REQUIRED
```

`DOCUMENT_ONLY` is invalid for a current-scope correctness defect.

## Correctness and Closure

Unit tests alone are insufficient. Evaluate as applicable:
IMPLEMENTATION_CORRECTNESS, CONTRACT_CORRECTNESS, SCHEMA_CORRECTNESS,
CALLER_CORRECTNESS, WIRING_CORRECTNESS, PRODUCER_CONSUMER_CORRECTNESS,
PRODUCTION_DATAFLOW_CORRECTNESS, HITL_CORRECTNESS,
HUMAN_AUTHORITY_CORRECTNESS, EVIDENCE_CORRECTNESS,
FAILURE_PATH_CORRECTNESS, E2E_CORRECTNESS, REGRESSION_CORRECTNESS.

Require as applicable:

``` text
ROOT_CAUSE_COMPLETE=YES
FIX_COMPLETE=YES
CONTRACT_VALIDATED=YES
CALLERS_VALIDATED=YES
WIRING_VALIDATED=YES
PRODUCTION_DATAFLOW_VALIDATED=YES
HITL_VALIDATED=YES_OR_NA
EVIDENCE_VALIDATED=YES
FAILURE_PATH_VALIDATED=YES_OR_NA
E2E_VALIDATED=YES
REGRESSION_VALIDATED=YES
UNKNOWN_RUNTIME_CALLERS=0
UNKNOWN_REGRESSION_FAILURES=0
SOURCE_CAPABILITY_LOSS=0
```

For an island require `CAPABILITY_ISLAND=NO`.

## Golden Operational Workflow

``` text
User/Project → OpenSpec Intake → Auto Discovery → Field Resolution
→ ClarificationService → QuestionOwner (DE/DV/SHARED) → HumanGate
→ Human Answer → Field Resolution → EffectiveValue → Dispatch
→ Task Boundary → VerificationLevel → IP/SUBSYSTEM/SYSTEM_LEVEL
→ Verification Generation → EDA Execution → Regression → RCA
→ Coverage Closure → Requirements Traceability/Waiver → Verification Signoff
→ Experience/Evidence → KC Candidate/Promotion → Knowledge Brain → Next Run
```

One generic workflow; DE/DV are authority roles, not separate engines.

## Structural vs Production Connectivity

Track `STRUCTURAL_CONNECTED_STAGES` and `PRODUCTION_CONNECTED_STAGES`.
Unit/mock/internal-helper paths do not prove production connectivity.

## M6 Operational Slice

``` text
Intake → Field Resolution → Clarification → QuestionOwner → HumanGate
→ EffectiveValue → Dispatch → Task Boundary → VerificationLevel
→ IP/SUBSYSTEM/SYSTEM_LEVEL
```

Track `M6_VERTICAL_SLICE_CONNECTED_STAGES` and
`M6_PRODUCTION_CONNECTED_STAGES`. M6 closure depends on real production
edges, not closed rows.

## E2E KPIs

Track TOTAL_REQUIRED_STAGES, STRUCTURAL_CONNECTED_STAGES,
PRODUCTION_CONNECTED_STAGES, WIRED_STAGES, TRIGGERED_STAGES,
CONSUMED_STAGES, OPERATIONAL_STAGES, HITL_CONNECTED_STAGES,
EVIDENCE_CONNECTED_STAGES, CAPABILITY_ISLANDS,
CURRENT_SCOPE_DEFECTS_OPEN, UNCONTROLLED_BYPASSES,
UNKNOWN_RUNTIME_CALLERS, UNKNOWN_FAILURE_PATHS with evidence.

## Runtime / HITL / Evidence

Low-level bypasses must be explicit, non-default, scoped, auditable and
unable to masquerade as qualified execution. Target
`UNCONTROLLED_BYPASSES=0`.

Preserve DESIGN_AUTHORITY=DE, VERIFICATION_AUTHORITY=DV,
VERIFICATION_ENVIRONMENT_AUTHORITY=DV,
VERIFICATION_SIGNOFF_AUTHORITY=DV, SHARED only for genuine cross-domain
decisions.

Preserve Auto-Discovery First, Minimal Structured Clarification,
EvidenceRefs, evidence-grounded RCA, and DeclaredValue,
AutoDiscoveredValue, DerivedValue, EffectiveValue, Confidence,
ValidationState, ConfirmationState, EvidenceRefs. Human answers return
through Field Resolution.

## Integration vs Expansion

Existing/current defect or false claim? FIND→FIX→VERIFY. Required for
current Golden Workflow? FIND→FIX→VERIFY.
Capability-loss/safety/false-PASS? FIND→FIX→VERIFY. True future
enhancement? REGISTER+OWNER+DEFER. Do not hide current defects behind
future ownership; do not pull unrelated future features forward.

## Frontends / Knowledge / Lifecycle

Native Claude Fast Path and Full L5DGVA share identity, evidence,
ownership, provenance, Field Resolution, HumanGate and signoff. Excel,
Native Claude CLI, L5DGVA CLI and Web UI are frontends to the same
Canonical Intake → Field Resolution → OpenSpec.

Learning closes only when
`Experience → KC Candidate → Promotion → Stored → Retrieved → Consumed → Behavior Changed → Outcome Re-qualified`.

Generated verification environments are lifecycle-managed DV assets;
CREATE and MAINTAIN converge on the same evidence/authority/signoff
system.

## Roadmap

M6=production connectivity; M7=multi-model orchestration;
M8=retrieval/consumption learning; M9=generic levels;
M10=vPlan/Coverage/Traceability/Signoff; M10.5=maintenance; M11=USB
Golden qualification; M12=frontends/productization;
M13=strict-superset/final qualification; M14=post-M13 productivity
benchmark.

## Reporting

Every integration report states: gap; current/future scope; disposition;
RCA; fix; real producer→consumer edge; production-dataflow evidence;
HITL/human-authority validation; evidence correctness; E2E validation;
regression/classification; remaining islands/bypasses;
structural/production stage counts; next blocking edge.

## Anti-Patterns

Reject document-only current defects, IMPLEMENTED-as-OPERATIONAL,
internal wiring as production connectivity, future owner hiding current
defects, unrelated future scope pulled forward, duplicate
engines/Sources of Truth, runtime-bypassable governance, disconnected
HITL, knowledge storage without consumption, coverage without closure,
signoff without traceability.

## Governance Placement

Keep only compact ALWAYS_ON P1--P5 summary in CLAUDE.md/Constitution and
register this detailed V2 task-scoped. After adoption: -
`L5DGVA_INTEGRATION_PRIME_DIRECTIVE_V2.md = ACTIVE_DETAILED_AUTHORITY` -
`L5DGVA_INTEGRATION_PRIME_DIRECTIVE.md = SUPERSEDED_HISTORICAL`

## Core Invariants

``` text
CONNECT_BEFORE_EXPAND=YES
OPERATIONAL_BEFORE_CLAIMED=YES
CLOSE_THE_LOOP=YES
NO_CAPABILITY_ISLANDS=TARGET
FIND_FIX_VERIFY=YES
CURRENT_SCOPE_DEFECTS_MUST_BE_REMEDIATED=YES
FUTURE_SCOPE_EXPANSION_MUST_NOT_BE_PULLED_FORWARD=YES
ONE_GENERIC_DE_DV_WORKFLOW=YES
ONE_CANONICAL_INTAKE_ENGINE=YES
ONE_CANONICAL_FIELD_RESOLUTION_ENGINE=YES
ONE_CANONICAL_OPENSPEC_MODEL=YES
ONE_KNOWLEDGE_BRAIN=YES
AUTO_DISCOVERY_FIRST=YES
MINIMAL_STRUCTURED_CLARIFICATION=YES
EVIDENCE_GROUNDED=YES
HUMAN_AUTHORITY_PRESERVED=YES
UNCONTROLLED_BYPASSES_TARGET=0
UNKNOWN_RUNTIME_CALLERS_TARGET=0
UNKNOWN_REGRESSION_FAILURES_TARGET=0
```

## Final Objective

> Can a real DE/DV user enter one governed L5DGVA workflow and have
> existing capabilities execute, interact, produce evidence, correct
> discovered integration defects, close verification, learn, and improve
> the next run without manual orchestration between disconnected
> islands?
