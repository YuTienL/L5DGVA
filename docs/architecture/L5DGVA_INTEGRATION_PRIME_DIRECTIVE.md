# L5DGVA Integration Prime Directive

## Purpose

Governs the Canonical L5DGVA integration phase and complements Article
0, Constitution, OpenSpec, DE/DV HITL, security, and Master
control-plane authority.

## Prime Directive

> **Prioritize connecting existing but fragmented capabilities into the
> first complete, executable, human-in-the-loop, evidence-grounded
> L5DGVA workflow. Until that workflow is operational, measure
> integration progress primarily by real runtime connectivity and
> closed-loop execution---not by newly added capability count.**

``` text
CONNECT BEFORE EXPAND
→ OPERATIONAL BEFORE CLAIMED
→ CLOSE THE LOOP
→ NO CAPABILITY ISLANDS
```

## CONNECT BEFORE EXPAND

Connect existing verified capabilities before non-blocking expansion.
New capability work may interrupt closure only for a Golden-Workflow
blocker, safety/security need, capability-loss prevention, mandatory
current-slice dependency, or approved human/constitutional requirement.
Otherwise register a future owner and continue E2E closure.

## OPERATIONAL BEFORE CLAIMED

Maturity:

``` text
ROADMAP_DEFINED → FOUNDATION → IMPLEMENTED → WIRED → TRIGGERED → CONSUMED → OPERATIONAL → QUALIFIED
```

ROADMAP_DEFINED=requirement/owner; FOUNDATION=reusable contract;
IMPLEMENTED=code/artifact; WIRED=producer/consumer connection;
TRIGGERED=real runtime invocation; CONSUMED=downstream consumes output;
OPERATIONAL=intended E2E behavior works with gates/evidence;
QUALIFIED=accepted qualification proves it.

Invariants:

``` text
FOUNDATION != OPERATIONAL
IMPLEMENTED != WIRED
TESTED != CONSUMED
MODULE_EXISTS != RUNTIME_USED
ROADMAP_DEFINED != IMPLEMENTED
```

## CLOSE THE LOOP

Core workflow:

``` text
Input → Discovery → Resolution/Reasoning → HITL → Decision → Execution → Evidence → Validation → Closure → Learning → Reuse
```

`KC_STORED != CLOSED_LOOP_LEARNING`; `KC_RETRIEVED != KC_CONSUMED`;
`REGRESSION_RUN != FAILURE_CLASSIFIED`;
`COVERAGE_REPORTED != COVERAGE_CLOSED`;
`QUESTION_ANSWERED != FIELD_RESOLVED`.

## NO CAPABILITY ISLANDS

Every implemented capability must eventually identify TRIGGER, INPUT,
PRODUCER, CAPABILITY, OUTPUT, CONSUMER, NEXT_STAGE, EVIDENCE,
FAILURE_PATH, HUMAN_AUTHORITY. Unknown/unwired intended producer or
consumer =\> `CAPABILITY_ISLAND=YES`. Temporary islands require explicit
owner/wave and cannot be called operational.

## Golden Operational Workflow

``` text
User / Project
→ OpenSpec Intake
→ Auto Discovery
→ Field Resolution
→ ClarificationService when unresolved
→ QuestionOwner (DE / DV / SHARED)
→ HumanGate
→ Human Answer
→ Field Resolution
→ EffectiveValue
→ Dispatch
→ Task Boundary
→ VerificationLevel
→ IP / SUBSYSTEM / SYSTEM_LEVEL
→ Verification Generation
→ EDA Execution
→ Regression
→ RCA
→ DESIGN / VERIFICATION / SHARED routing
→ Coverage Closure
→ Requirements Traceability / Waiver
→ Verification Signoff
→ Experience / Evidence
→ KC Candidate / Promotion
→ Knowledge Brain
→ Next Run
```

One generic workflow; DE/DV are authority roles, not separate engines.

## M6 Operational Slice

``` text
Intake → Field Resolution → Clarification → QuestionOwner → HumanGate → EffectiveValue → Dispatch → Task Boundary → VerificationLevel → IP / SUBSYSTEM / SYSTEM_LEVEL
```

Track `M6_VERTICAL_SLICE_CONNECTED_STAGES`. Count a stage only when its
output is consumed by the next required runtime stage. Module
existence/import/isolated tests are insufficient.

## E2E KPIs

Track TOTAL_REQUIRED_STAGES, CONNECTED_STAGES, WIRED_STAGES,
TRIGGERED_STAGES, CONSUMED_STAGES, OPERATIONAL_STAGES,
HITL_CONNECTED_STAGES, EVIDENCE_CONNECTED_STAGES, CAPABILITY_ISLANDS,
UNCONTROLLED_BYPASSES, UNKNOWN_RUNTIME_CALLERS, UNKNOWN_FAILURE_PATHS,
each with evidence.

## Runtime Bypass

Low-level bypasses must be explicit, non-default, scoped, auditable,
justified, and unable to masquerade as qualified normal execution.
Target `UNCONTROLLED_BYPASSES=0`.

## HITL Authority

Preserve DESIGN_AUTHORITY=DE, VERIFICATION_AUTHORITY=DV,
VERIFICATION_ENVIRONMENT_AUTHORITY=DV,
VERIFICATION_SIGNOFF_AUTHORITY=DV, SHARED_AUTHORITY=DE+DV only for
genuine cross-domain decisions. Automation cannot silently replace human
authority. SHARED is not an uncertainty fallback.

## Evidence / OpenSpec

Preserve Auto-Discovery First, EvidenceRefs, evidence/refutation RCA,
and:

``` text
DeclaredValue
AutoDiscoveredValue
DerivedValue
EffectiveValue
Confidence
ValidationState
ConfirmationState
EvidenceRefs
```

Human answers return through Field Resolution; they do not directly
overwrite EffectiveValue.

## Expansion Gate

If a discovered capability is required to close the current Golden
Workflow, integrate now. Otherwise register a future owner and continue
E2E closure.

## Roadmap

M6=Intake/HITL/Dispatch/VerificationLevel connectivity; M7=multi-model
orchestration; M8=retrieval/consumption learning; M9=generic
IP/Subsystem/System-Level; M10=vPlan/Coverage/Traceability/Signoff;
M10.5=maintenance + Native Claude Fast Path; M11=USB Golden E2E/learning
qualification; M12=productization/frontends; M13=strict-superset/final
qualification; M14=post-M13 Junior Native Claude vs Junior L5DGVA
benchmark.

## Native Claude / Frontends

Native Claude Fast Path and Full L5DGVA share identity, evidence,
ownership, provenance, Field Resolution, HumanGate and signoff. Excel,
Native Claude CLI, L5DGVA CLI and Web UI are frontends to the same
Canonical Intake → Field Resolution → OpenSpec authority.

## Continuous Evolution

Learning closes only when:

``` text
Experience → KC Candidate → Promotion → Stored → Retrieved → Consumed → Behavior Changed → Outcome Re-qualified
```

Stored-but-unused knowledge is not operational learning.

## Verification Environment Lifecycle

Generated verification environments are lifecycle-managed DV assets, not
disposable outputs. CREATE and MAINTAIN converge on the same
evidence/authority/signoff system.

## Progress Reporting

Every integration report answers: what became connected; which
producer→consumer edges became real; which stages advanced maturity;
remaining islands/bypasses; connected human gates; produced/consumed
evidence; Golden Workflow connected-stage count; why any new capability
was necessary now; and the next blocking edge.

## Anti-Patterns

Capability/module/test/document/agent/graph-node/ROADMAP_DEFINED counts
are not operational progress by themselves. Avoid architecture expansion
without blocker evidence, duplicate engines/Sources of Truth,
runtime-bypassable governance, disconnected HITL, knowledge storage
without consumption, coverage without closure, signoff without
traceability.

## Governance Placement

Keep only a compact ALWAYS_ON summary in CLAUDE.md/Constitution when
required. Keep this detailed directive task-scoped and retrievable. Do
not copy it wholesale into CLAUDE.md.

## Core Invariants

``` text
CONNECT_BEFORE_EXPAND=YES
OPERATIONAL_BEFORE_CLAIMED=YES
CLOSE_THE_LOOP=YES
NO_CAPABILITY_ISLANDS=TARGET
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
```

## Final Objective

> **Can a real DE/DV user enter one governed L5DGVA workflow and have
> existing capabilities execute, interact, produce evidence, close
> verification, learn, and improve the next run without manual
> orchestration between disconnected islands?**
