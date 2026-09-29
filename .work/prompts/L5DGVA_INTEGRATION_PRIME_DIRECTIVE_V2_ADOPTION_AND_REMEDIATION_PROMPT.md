# L5DGVA Integration Prime Directive V2 Adoption and Remediation Prompt

## Mission

Adopt `L5DGVA_INTEGRATION_PRIME_DIRECTIVE_V2.md`, supersede V1 as active
detailed authority, and apply **P5 FIND → FIX → VERIFY** to
current-scope integration defects.

This is governance reconciliation plus current-scope remediation. It is
not permission to pull future-wave features forward.

Do not start later waves. Do not consume Reference USB. Do not modify
Parent/v50/b7a/b7b/b8.

## Preflight

Verify Canonical repo identity and record PROCESS_CWD, REPO_ROOT,
CURRENT_BRANCH, CURRENT_HEAD, WORKING_TREE_STATUS. Read V2 completely,
V1, CLAUDE.md, Constitution/Article 0, Master
Capability/Wave/Blocker/Program/E2E artifacts, current M6 reports,
CAP-M6-DISPATCH-001, CAP-M6-CLARSVC-001, Golden Workflow, governance
registry and anti-drift policy. Verify frozen sources unchanged.

## Adopt / Supersede

Set:

``` text
L5DGVA_INTEGRATION_PRIME_DIRECTIVE_V2.md = ACTIVE_DETAILED_AUTHORITY
L5DGVA_INTEGRATION_PRIME_DIRECTIVE.md = SUPERSEDED_HISTORICAL
```

Do not delete V1 evidence and do not leave both active.

Add only compact ALWAYS_ON P1--P5 discoverability to CLAUDE.md plus a
task-scoped reference to V2. Do not copy V2 wholesale. Preserve Article
0 and M4.6 Minimum Sufficient Context.

## Governance Registry and Maturity

Register V2 in the existing governance registry for integration,
remediation, defects, capability maturity/islands, architecture
expansion, M6--M13 execution, runtime wiring, production connectivity
and status reporting. Do not create a second registry.

Reconcile/reuse:

``` text
ROADMAP_DEFINED → FOUNDATION → IMPLEMENTED → WIRED → TRIGGERED → CONSUMED → PRODUCTION_CONNECTED → OPERATIONAL → QUALIFIED
```

Do not duplicate equivalent existing taxonomy.

## P5 Current-Scope Gap Audit

Audit the current approved M6 Golden-Workflow scope, not all future
roadmap features. Every gap receives exactly one disposition:

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

`DOCUMENT_ONLY` is invalid for current-scope correctness defects.

## Re-verify Known Findings

Do not trust prior reports blindly. Verify from real production code: 1.
Whether real production `field_controls` reach ClarificationService. 2.
Whether supported generation dispatch consumes the governed
`start_lifecycle()` path. 3. Whether ClarificationService is a
production capability island. 4. Whether `human_gate_state()` having
zero production callers is only a projection detail or a real workflow
gap. 5. Whether CAP-M6-DISPATCH-001 P0 bookkeeping is stale after
closure.

For each record PRODUCER, OUTPUT, CONSUMER, INPUT,
PRODUCTION_ENTRY_PATH, CALLERS, RUNTIME_EVIDENCE, TEST_EVIDENCE,
CURRENT_STATUS, DISPOSITION.

## Remediate Current Defects

For every re-verified current-scope defect execute:

``` text
RCA
→ minimal correct fix/integration
→ focused test
→ producer/consumer test
→ production-dataflow validation
→ applicable HITL/evidence validation
→ E2E validation
→ regression
→ evidence review
```

Do not merely register/defer a current Golden-Workflow defect.

Do not implement CAP-M5M6-VLEVEL-001 or M7--M14 work unless separately
authorized. True future enhancements are registered/deferred with owner.

## Architecture Constraints

Preserve:

``` text
User Entry
→ start_lifecycle
→ Intake / Field Resolution / HITL
→ Dispatch
→ Task Boundary
→ [future VerificationLevel seam]
→ Generation capability
```

Do not make `create_environment.py` a second workflow orchestrator or
recursively restart lifecycle.

Preserve ONE_CLARIFICATION_SERVICE,
ONE_CANONICAL_FIELD_RESOLUTION_ENGINE, AUTO_DISCOVERY_FIRST,
MINIMAL_STRUCTURED_CLARIFICATION. If production field_controls are
missing, wire the existing Canonical source/projection rather than
inventing a second field model. Human answers return through Field
Resolution.

## Structural vs Production Connectivity

Track both:

``` text
STRUCTURAL_CONNECTED_STAGES
PRODUCTION_CONNECTED_STAGES
```

Production-connected requires real supported user/project data flowing
through and onward. Unit/mock/internal-helper connectivity is
insufficient.

For each claimed production-connected edge record producer, real data,
consumer, next-stage consumption, supported entry point, and evidence.

## HITL and Evidence

Validate DE/DV/SHARED authority where applicable. Preserve EvidenceRefs
and Confidence/ValidationState/ConfirmationState separation. Verify
blocking/resume behavior when clarification is required.

An internal projection/helper with zero production callers is not
automatically a defect; determine whether the underlying governed
mechanism is production-consumed. Classify with evidence.

## Bookkeeping Correctness

Use structural CSV parsing. Reconcile stale closed-blocker bookkeeping
only if current Canonical blocker policy/evidence requires it. Do not
manipulate counts to expected values. Report exact capability IDs behind
authoritative P0 count.

Require MALFORMED_ROWS=0, DUPLICATE_CAPABILITY_IDS=0,
P0_COUNT_AMBIGUITY=0.

## Correctness Closure

For each fixed current-scope gap require as applicable:

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

A current-scope capability island must become `CAPABILITY_ISLAND=NO`
before the affected workflow is closed.

## Testing

Test first where production behavior changes. Include as applicable: -
real field-controls propagation; - auto-resolved no-question path; -
unresolved clarification; - QuestionOwner/HumanGate; - answer → Field
Resolution → EffectiveValue; - CLI production propagation; - dashboard
production propagation; - governed generation dispatch; - no lifecycle
recursion; - authorized low-level bypass preservation; - newly
discovered current-scope defects.

Do not use CPU usage alone to classify a hang. Identify the active
test/process and compare historical behavior.

## Anti-Drift and Master Control Plane

Reconcile maturity including PRODUCTION_CONNECTED and capability-island
policy. Add/reconcile small machine-checkable anti-drift checks so
IMPLEMENTED/TESTED cannot be called OPERATIONAL without required
evidence and current-scope defects cannot silently become document-only.

Update existing CLAUDE.md, Constitution cross-reference, governance
registry, Master Capability Status Matrix, Master Wave Ownership Matrix,
Master End-to-End DV Status and Master Program Status only as required.
Do not create a competing control plane.

## Required Artifacts

Produce/update in approved locations, not repository root: -
`L5DGVA_INTEGRATION_PRIME_DIRECTIVE_V2_ADOPTION_REPORT.md` -
`L5DGVA_CURRENT_SCOPE_GAP_REGISTER.csv` -
`L5DGVA_FIND_FIX_VERIFY_EVIDENCE.md` -
`L5DGVA_PRODUCTION_CONNECTIVITY_STATUS.md`

Record every current-scope gap, disposition, RCA, fix evidence and
closure status.

## Validation

Require:

``` text
PRIME_DIRECTIVE_V2=ADOPTED
PRIME_DIRECTIVE_V1=SUPERSEDED_HISTORICAL
CONNECT_BEFORE_EXPAND=YES
OPERATIONAL_BEFORE_CLAIMED=YES
CLOSE_THE_LOOP=YES
NO_CAPABILITY_ISLANDS=TARGET
FIND_FIX_VERIFY=YES
CURRENT_SCOPE_DEFECTS_DOCUMENT_ONLY=0
CLAUDE_MD_FULL_DIRECTIVE_DUPLICATED=NO
ARTICLE_0_PRESERVED=YES
STRUCTURAL_CONNECTIVITY_TRACKED=YES
PRODUCTION_CONNECTIVITY_TRACKED=YES
UNKNOWN_RUNTIME_CALLERS=0
UNKNOWN_REGRESSION_FAILURES=0
SOURCE_CAPABILITY_LOSS=0
UNCONTROLLED_BYPASSES=0
REFERENCE_USB_ENV_CONSUMED=NO
```

Run applicable
Constitution/Anti-Drift/governance/reference-graph/control-plane tests
plus focused/broader regression required by actual fixes.

## Final Report

Report:

``` text
PRIME_DIRECTIVE_V2_ADOPTION_STATUS=READY_FOR_APPROVAL / PARTIAL / BLOCKED
PRIME_DIRECTIVE_V2=ADOPTED / PARTIAL
PRIME_DIRECTIVE_V1=SUPERSEDED_HISTORICAL / STILL_ACTIVE
CURRENT_SCOPE_GAPS_FOUND=<count>
CURRENT_SCOPE_GAPS_FIXED=<count>
CURRENT_SCOPE_GAPS_OPEN=<count>
FUTURE_SCOPE_GAPS_DEFERRED=<count>
CAPABILITY_ISLANDS_BEFORE=<count>
CAPABILITY_ISLANDS_AFTER=<count>
STRUCTURAL_CONNECTED_STAGES=<count>
PRODUCTION_CONNECTED_STAGES=<count>
UNKNOWN_RUNTIME_CALLERS=<count>
UNCONTROLLED_BYPASSES=<count>
REGRESSION_CAUSED_BY_REMEDIATION=<count>
UNKNOWN_REGRESSION_FAILURES=<count>
SOURCE_CAPABILITY_LOSS=<count>
MASTER_CAPABILITY_MATRIX_ROWS=<count>
MASTER_CAPABILITY_MATRIX_MALFORMED_ROWS=0
MASTER_CAPABILITY_MATRIX_DUPLICATE_IDS=0
AUTHORITATIVE_MASTER_P0_BLOCKER_COUNT=<count>
CURRENT_PROGRAM_POSITION=<position>
NEXT_RECOMMENDED_GATE=<exact gate>
REFERENCE_USB_ENV_CONSUMED=NO
```

## STOP

After V2 adoption, current-scope remediation, validation,
artifact/control-plane updates, and final report: STOP.

Do not automatically start CAP-M5M6-VLEVEL-001 or any later wave. If a
remaining current-scope correctness defect exists, report its exact
blocker and do not claim the affected workflow closed.
