# L5DGVA Integration Prime Directive Adoption Prompt

## Mission

Adopt and reconcile `L5DGVA_INTEGRATION_PRIME_DIRECTIVE.md` into
Canonical L5DGVA governance and Master control-plane artifacts. This is
governance/roadmap/control-plane reconciliation only.

Do NOT interrupt current M6. Do NOT implement a new capability family.
Do NOT start later waves. Do NOT consume Reference USB.

## Preflight

Verify Canonical repo identity and record PROCESS_CWD, REPO_ROOT,
CURRENT_BRANCH, CURRENT_HEAD, WORKING_TREE_STATUS. Read the complete
Prime Directive, CLAUDE.md, Constitution/Article 0, Master
Capability/Wave/Blocker/Program/E2E artifacts, current M6
vertical-slice/status artifacts, governance registry, anti-drift and
reference-graph policy. Verify Parent/v50/b7a/b7b/b8 unchanged.

## Preserve Approved State

Do not reopen M5 CLOSED, CAP-M6-DISPATCH-001, current CAP-M6-CLARSVC-001
gate/status, DE/DV HITL, OpenSpec eight-field model, VELM, Native Claude
Fast Maintenance, Structured Excel Intake, USB Excel/KC roadmap, or
M14-after-M13.

## Adopt Principles

Reconcile `CONNECT BEFORE EXPAND`, `OPERATIONAL BEFORE CLAIMED`,
`CLOSE THE LOOP`, `NO CAPABILITY ISLANDS`. Progress is runtime
connectivity and closed-loop execution, not capability count.

## CLAUDE.md / Constitution

Do NOT copy the full directive into CLAUDE.md. Add/reconcile only a
compact ALWAYS_ON discoverability statement consistent with M4.6 Minimum
Sufficient Context and point to the detailed task-scoped directive.

Place the directive beneath and consistently with Article 0;
cross-reference rather than duplicate existing constitutional text.
Preserve LOCATION_INDEPENDENT, EVIDENCE_GROUNDED, KNOWLEDGE_DRIVEN,
CONTINUOUSLY_EVOLVING, DE/DV authority and anti-drift.

## Governance Registry

Register the detailed directive using the existing registry. Trigger it
for integration, capability migration/maturity, architecture expansion,
roadmap reconciliation, M6--M13 execution, operational workflow,
vertical slice, capability island, runtime wiring and status reporting.
Do not create a second registry.

## Capability Maturity / Island Policy

Reconcile/reuse:

``` text
ROADMAP_DEFINED → FOUNDATION → IMPLEMENTED → WIRED → TRIGGERED → CONSUMED → OPERATIONAL → QUALIFIED
```

Preserve FOUNDATION!=OPERATIONAL, IMPLEMENTED!=WIRED, TESTED!=CONSUMED,
MODULE_EXISTS!=RUNTIME_USED.

Define/reconcile CAPABILITY_ISLAND using TRIGGER, INPUT, PRODUCER,
CAPABILITY, OUTPUT, CONSUMER, NEXT_STAGE, EVIDENCE, FAILURE_PATH,
HUMAN_AUTHORITY. Do not fix all historical islands in this task;
establish measurement and owner obligations.

## Golden Workflow

Register/reconcile:

``` text
OpenSpec Intake → Auto Discovery → Field Resolution → ClarificationService → QuestionOwner → HumanGate → EffectiveValue → Dispatch → Task Boundary → VerificationLevel → IP/SUBSYSTEM/SYSTEM_LEVEL → Verification Generation → EDA Execution → Regression → RCA → Coverage Closure → Traceability/Waiver → Signoff → Experience/KC → Knowledge Brain → Next Run
```

Do not implement missing stages here.

## M6 Vertical Slice / KPIs

Preserve actual measured M6 state; do not replace it with target values.
Track `M6_VERTICAL_SLICE_CONNECTED_STAGES`; count a stage only when its
output is consumed by the next required runtime stage.

Add/reconcile tracking for TOTAL_REQUIRED_STAGES, CONNECTED_STAGES,
WIRED_STAGES, TRIGGERED_STAGES, CONSUMED_STAGES, OPERATIONAL_STAGES,
HITL_CONNECTED_STAGES, EVIDENCE_CONNECTED_STAGES, CAPABILITY_ISLANDS,
UNCONTROLLED_BYPASSES, UNKNOWN_RUNTIME_CALLERS, UNKNOWN_FAILURE_PATHS.
Reuse existing Master status.

## Connect-Before-Expand Gate

Future discovered capabilities receive exactly one disposition:
REQUIRED_NOW_FOR_GOLDEN_WORKFLOW, SAFETY_OR_CAPABILITY_LOSS_REQUIRED, or
REGISTER_AND_DEFER_WITH_OWNER.

## Runtime / HITL / Evidence

Preserve CAP-M6-DISPATCH-001 authorized low-level bypass policy unless
evidence changes it; target UNCONTROLLED_BYPASSES=0. Preserve
DE/DV/SHARED authority, Auto-Discovery First, Minimal Structured
Clarification, OpenSpec eight-field model, EvidenceRefs and
evidence-grounded RCA. Human answers return through Canonical Field
Resolution.

## Roadmap Reconciliation

Reconcile M6--M13 priorities to the directive without rewriting approved
scope. Preserve M14 after M13.

## Anti-Drift

Add/reconcile a small machine-checkable anti-drift rule, consistent with
existing governance, so reports cannot claim OPERATIONAL merely from
IMPLEMENTED/TESTED and Prime Directive discoverability cannot silently
disappear. Do not build a large new governance subsystem.

## Required Artifacts

Produce/update in approved governance/work area: -
L5DGVA_INTEGRATION_PRIME_DIRECTIVE_ADOPTION_REPORT.md -
L5DGVA_GOLDEN_OPERATIONAL_WORKFLOW.md -
L5DGVA_CAPABILITY_MATURITY_AND_ISLAND_POLICY.md -
L5DGVA_INTEGRATION_KPI_REQUIREMENTS.md

Update existing CLAUDE.md, Constitution/architecture cross-reference,
governance registry, Master Capability Status Matrix, Master Wave
Ownership Matrix, Master End-to-End DV Status and Master Program Status
only as required. Do not place reports in repo root.

## Validation

Require:

``` text
INTEGRATION_PRIME_DIRECTIVE=ADOPTED
CONNECT_BEFORE_EXPAND=YES
OPERATIONAL_BEFORE_CLAIMED=YES
CLOSE_THE_LOOP=YES
NO_CAPABILITY_ISLANDS=TARGET
GOLDEN_OPERATIONAL_WORKFLOW=DEFINED
CAPABILITY_MATURITY_MODEL=DEFINED_OR_REUSED
CAPABILITY_ISLAND_POLICY=DEFINED
END_TO_END_OPERATIONAL_CONNECTIVITY_KPI=DEFINED
CLAUDE_MD_FULL_DIRECTIVE_DUPLICATED=NO
ARTICLE_0_PRESERVED=YES
CURRENT_M6_GATE_PRESERVED=YES
M6_PRODUCTION_IMPLEMENTATION_CHANGED=NO
M10_5_STARTED=NO
M11_STARTED=NO
M12_STARTED=NO
M13_STARTED=NO
M14_STARTED=NO
REFERENCE_USB_ENV_CONSUMED=NO
```

Use structural CSV parsing. Require MALFORMED_ROWS=0,
DUPLICATE_CAPABILITY_IDS=0, P0_COUNT_AMBIGUITY=0. Run applicable
Constitution/Anti-Drift/governance/reference-graph/control-plane tests.
Do not run full product regression unless governance requires it for
roadmap-only changes.

## Final Report

Report:

``` text
PRIME_DIRECTIVE_ADOPTION_STATUS=READY_FOR_APPROVAL / PARTIAL / BLOCKED
INTEGRATION_PRIME_DIRECTIVE=ADOPTED / PARTIAL
CONNECT_BEFORE_EXPAND=YES / NO
OPERATIONAL_BEFORE_CLAIMED=YES / NO
CLOSE_THE_LOOP=YES / NO
NO_CAPABILITY_ISLANDS=TARGET / NOT_DEFINED
GOLDEN_OPERATIONAL_WORKFLOW=DEFINED / PARTIAL
CAPABILITY_MATURITY_MODEL=<status>
CAPABILITY_ISLAND_POLICY=<status>
END_TO_END_OPERATIONAL_CONNECTIVITY_KPI=<status>
M6_VERTICAL_SLICE_CONNECTED_STAGES=<actual current count>
CAPABILITY_ISLANDS_IDENTIFIED=<count or NOT_YET_AUDITED>
UNCONTROLLED_BYPASSES=<count or current evidenced value>
CLAUDE_MD_FULL_DIRECTIVE_DUPLICATED=NO
MASTER_CAPABILITY_MATRIX_ROWS=<count>
MASTER_CAPABILITY_MATRIX_MALFORMED_ROWS=0
MASTER_CAPABILITY_MATRIX_DUPLICATE_IDS=0
AUTHORITATIVE_MASTER_P0_BLOCKER_COUNT=<count>
CURRENT_PROGRAM_POSITION=<position>
CURRENT_M6_GATE_PRESERVED=YES / NO
NEXT_RECOMMENDED_GATE=<current M6 gate>
M6_PRODUCTION_IMPLEMENTATION_CHANGED=NO
M10_5_STARTED=NO
M11_STARTED=NO
M12_STARTED=NO
M13_STARTED=NO
M14_STARTED=NO
REFERENCE_USB_ENV_CONSUMED=NO
```

## STOP

After reconciliation/validation, STOP. Do not implement the Prime
Directive as a new engine. Do not resume/start M6 implementation
automatically. Wait for explicit review.
