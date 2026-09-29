# L5DGVA Result-Driven Autonomous Closed-Loop Integration Prompt

## Mission

Adopt `L5DGVA_RESULT_DRIVEN_AUTONOMOUS_CLOSED_LOOP_REQUIREMENTS.md` as a
platform-level L5DGVA requirement and integrate it into Prime Directive
V2, Master capability/roadmap/control-plane artifacts, M7 architecture,
and the current real Codex-result workflow.

Add:

``` text
P6 RESULT → ACTION → AUTONOMOUS CLOSURE
```

The human remains transport and authority, not workflow scheduler.

This task includes governance reconciliation and implementation of the
M7 foundation required by the already-consumed real Codex result.

Do not start M8 or later waves. Do not consume Reference USB. Do not
modify Parent/v50/b7a/b7b/b8.

## 1. Preflight

Record PROCESS_CWD, REPO_ROOT, CURRENT_BRANCH, CURRENT_HEAD,
WORKING_TREE_STATUS.

Read completely: -
`L5DGVA_RESULT_DRIVEN_AUTONOMOUS_CLOSED_LOOP_REQUIREMENTS.md` - Prime
Directive V2 - M7 structured multi-model architecture/current
implementation artifacts - preserved original Codex RESULT_V1 for
`M7-V1-CODEX-REVIEW-001` - current Gap Register - Task/Agent lifecycle -
question_queue/HumanGate - Task Boundary - evidence/governance
contracts - M6 final qualification/non-regression contract - Master
capability/wave/status artifacts.

Verify frozen sources unchanged.

## 2. Preserve Real Codex Evidence

Freeze:

``` text
TASK_ID=M7-V1-CODEX-REVIEW-001
CODEX_ROUND_TRIP=QUALIFIED
CODEX_OUTPUT_CONSUMED=YES
RESULT_STATUS=FAIL
HUMAN_DECISION_REQUIRED=NO
```

Preserve original RESULT_V1 verbatim. Do not rewrite it.

Preserve registered GAP-V2-009/010/011/012. Do not assume Codex is
correct; independently reproduce each finding before fixing.

## 3. Adopt P6

Reconcile Prime Directive V2 with:

``` text
P6 RESULT → ACTION → AUTONOMOUS CLOSURE
```

Meaning: once a valid result is consumed, L5DGVA automatically
classifies and executes the next permitted action. It must not stop
merely to ask the human to schedule already-authorized remediation.

Keep CLAUDE.md compact: add only minimum ALWAYS_ON discoverability and
task-scoped reference. Do not duplicate Article 0 or existing authority
rules.

## 4. Register/Reconcile Capability Family

Register/reconcile:

``` text
RESULT_DRIVEN_AUTONOMOUS_CLOSED_LOOP
RESULT_TO_ACTION_ROUTING
AUTO_REMEDIATION_ELIGIBILITY
AUTONOMOUS_REMEDIATION_EXECUTION
AUTONOMOUS_REMEDIATION_VERIFICATION
AUTONOMOUS_REVIEW_LOOP
HUMAN_ESCALATION_POLICY
LOOP_TERMINATION_POLICY
LOOP_BUDGET_POLICY
LOOP_EVIDENCE_TRACEABILITY
LOOP_RESUME_RECOVERY
```

Reuse existing mechanisms when equivalent. Do not create duplicate
engines. Assign owner waves from real dependency/implementation state;
M7-required foundation belongs in M7.

## 5. Result-to-Action Router

Implement/reuse a Canonical result-to-action router whose input is a
validated and consumed Canonical result.

It must map Prime Directive dispositions to execution classes:

``` text
AUTO_REMEDIATION_ELIGIBLE
HUMAN_GATE_REQUIRED
DEFERRED_WITH_OWNER
CLOSE_WITH_EVIDENCE
BLOCKED
```

Do not hard-code Codex-specific behavior.

## 6. Auto-Remediation Eligibility

Default auto-remediation candidates:

``` text
FIX_NOW_CURRENT_SCOPE
FIX_NOW_CORRECTNESS_BLOCKER
FIX_NOW_CAPABILITY_LOSS
```

only if remediation stays within approved scope, does not alter
protected architecture authority, require DE/DV/signoff authority,
expand security/access scope, modify frozen sources, or require a new
human decision, and has an evidence-backed validation path.

For FIX_NOW_SAFETY_SECURITY perform an explicit existing-policy
authority check.

## 7. Human Escalation

Route to HumanGate for:

``` text
HUMAN_DECISION_REQUIRED
DESIGN_AUTHORITY_REQUIRED
VERIFICATION_AUTHORITY_REQUIRED
VERIFICATION_SIGNOFF_REQUIRED
ARCHITECTURE_AUTHORITY_REQUIRED
SECURITY_SCOPE_EXPANSION
ACCESS_AUTHORIZATION_REQUIRED
AMBIGUOUS_HIGH_IMPACT_DECISION
POLICY_REQUIRES_HUMAN_APPROVAL
```

Do not use HUMAN_DECISION_REQUIRED as a generic uncertainty fallback.

## 8. State Machine

Implement/reconcile states:

``` text
RESULT_AVAILABLE
RESULT_VALIDATING
RESULT_REJECTED
RESULT_ACCEPTED
RESULT_CONSUMED
ACTION_CLASSIFYING
AUTO_REMEDIATION_READY
AUTO_REMEDIATION_RUNNING
AUTO_REMEDIATION_VERIFYING
RE_REVIEW_REQUIRED
RE_REVIEW_HANDOFF_READY
WAITING_FOR_HUMAN_TRANSPORT
HUMAN_GATE_REQUIRED
WAITING_FOR_HUMAN_DECISION
RESUMING
CLOSED
BLOCKED
```

Reuse existing lifecycle persistence. Do not create a second lifecycle
engine.

## 9. Autonomous Remediation Executor

For eligible findings automatically execute:

``` text
REPRODUCE
→ ROOT CAUSE
→ PLAN MINIMAL FIX
→ IMPLEMENT
→ FOCUSED TEST
→ CONTRACT VALIDATION
→ PRODUCER/CONSUMER VALIDATION
→ E2E VALIDATION where applicable
→ REGRESSION
→ EVIDENCE UPDATE
→ RE-REVIEW / RE-QUALIFICATION
```

Do not ask the human "continue?" between these authorized stages.

## 10. Current Codex Findings

Immediately apply P6 to the already-consumed result.

Independently reproduce Codex F1-F7 and reconcile them to
GAP-V2-009/010/011/012.

For each report:

``` text
FINDING_ID
CLAIM
REPRODUCTION
EXPECTED_BEHAVIOR
ACTUAL_BEHAVIOR
ROOT_CAUSE
GAP_ID
DISPOSITION
AUTO_REMEDIATION_ELIGIBILITY
```

Allowed finding dispositions: CONFIRMED, PARTIALLY_CONFIRMED,
NOT_REPRODUCED, FALSE_POSITIVE, SUPERSEDED.

No finding may be silently dropped.

## 11. Validation Correctness / GAP-V2-009

Investigate weak schema/version/evidence validation and the disclosed
absence of dedicated governance validation.

Derive requirements from HANDOFF_V1, RESULT_V1, EvidenceRefs, Task Scope
and governance registry.

If REQUIRED_GOVERNANCE_REFS is empty, use explicit NOT_APPLICABLE
semantics rather than falsely claiming a validation check ran.

If refs are present, validate them against the real registry/authority.

## 12. Identity/Scope Integrity / GAP-V2-010

External results are untrusted input.

Required ordering:

``` text
RAW RESULT
→ PARSE
→ VALIDATE IDENTITY
→ VALIDATE CONTRACT
→ VALIDATE SCOPE
→ VALIDATE EVIDENCE
→ VALIDATE GOVERNANCE
→ CLASSIFY
→ CONSUME
```

Do not normalize conflicting TASK_ID, producer, task type, scope, or
authority fields before validation.

## 13. Atomicity / Replay / GAP-V2-011

Require: - malformed stored handoff does not unexpectedly crash
orchestration; - failed validation creates no consumed entry; - partial
consumption cannot leave contradictory state; - accepted-result
re-import is deterministic; - duplicate import creates no duplicate
semantic consumption; - interrupted import cannot leave half-consumed
state.

Reuse existing persistence/state mechanisms where possible.

## 14. Markdown Fidelity / GAP-V2-012

Test serialize → human transport → parse with embedded newlines,
`##`-like content, special Markdown, empty sections, multiline
evidence/findings, and Codex's actual probes.

Preserve semantic content. Do not simply ban useful Markdown unless the
contract requires it.

## 15. Human Decision Routing

Re-test:

``` text
RESULT_STATUS=HUMAN_DECISION_REQUIRED
+ valid human-decision payload
→ question_queue / HumanGate

RESULT_STATUS=FAIL
+ HUMAN_DECISION_REQUIRED=NO
→ no fabricated human question
```

Preserve correct existing behavior.

## 16. Loop Termination Policy

Implement/reconcile policy inputs:

``` text
MAX_REMEDIATION_ITERATIONS
MAX_RETRY_PER_FINDING
NO_PROGRESS_DETECTION
REPEATED_FAILURE_SIGNATURE
REPEATED_FINDING_SIGNATURE
REGRESSION_EXPANSION_DETECTION
SCOPE_EXPANSION_DETECTION
EVIDENCE_STAGNATION
HUMAN_ESCALATION_THRESHOLD
```

Use configurable/evidence-backed thresholds. Do not invent arbitrary
fixed numbers solely for closure.

## 17. Loop Budget / Observability

Where measurable track:

``` text
ITERATION_COUNT
MODEL_INVOCATIONS
TEST_RUN_COUNT
REGRESSION_RUN_COUNT
WALL_TIME
CONTEXT_BYTES
TOKEN_USAGE_IF_AVAILABLE
RETRY_COUNT
```

Budget exhaustion becomes BLOCKED/HUMAN escalation, never PASS.

## 18. Evidence Traceability

Every autonomous iteration records:

``` text
SOURCE_RESULT_ID
FINDING_ID
GAP_ID
ACTION_CLASSIFICATION
ELIGIBILITY_DECISION
ROOT_CAUSE
FILES_CHANGED
TESTS_RUN
REGRESSION_SIGNATURE
EVIDENCE_REFS
RE_REVIEW_TASK_ID
ITERATION_NUMBER
FINAL_DISPOSITION
```

## 19. Resume / Recovery

Persist enough state to support:

``` text
STOP → Persist → Human/External Action → Resume → Continue
```

After a human-mediated RESULT_V1 is imported/consumed, automatically
resume action routing unless a HumanGate is reached.

## 20. Re-review Loop

After successful remediation determine the required reviewer.

For this Codex-originated review, automatically prepare a Codex
re-review HANDOFF_V1.

Then set:

``` text
RE_REVIEW_HANDOFF_READY
WAITING_FOR_HUMAN_TRANSPORT
```

and STOP, because actual external Codex execution requires human
transport.

Do not require the human to tell Claude what remediation to perform
before this point.

## 21. Re-import Original Codex Result

After fixes, test the exact preserved original result in a controlled
replay context.

Do not edit it.

Verify: - same Task ID attribution; - legitimate FAIL verdict remains
FAIL; - findings remain intact; - corrected validation behavior; -
deterministic/replay-safe consumption; - no duplicate semantic
consumption.

## 22. Adversarial Tests

Cover at minimum: - valid result; - wrong Task ID; - wrong producer; -
wrong task type; - scope mismatch; - forbidden file; - unsupported
HANDOFF_VERSION; - unsupported RESULT_VERSION; - missing required
field; - malformed evidence ref; - missing/invalid governance ref; -
empty governance refs/N/A; - malformed stored handoff; - embedded
newline; - embedded `##` heading; - duplicate import; - replay after
success; - interrupted/failed consumption; - invalid result causes no
canonical consumption; - Human Decision routing; - FAIL without Human
Decision; - auto-remediation eligibility; - HumanGate eligibility; -
no-progress escalation; - resume after transport.

## 23. M6 Non-Regression

Require M6 Golden Path preservation:

``` text
STRUCTURAL=10/10
PRODUCTION=10/10
EVIDENCE=10/10
QUALIFIED=10/10
HITL_QUALIFICATION=PASS
M6_GOLDEN_PATH_PRESERVED=YES
```

## 24. Prime Directive V2 / P6 Gap Discipline

Any new current-scope defect discovered in this task follows FIND → FIX
→ VERIFY and, if auto-eligible, proceeds without a user scheduling
prompt.

True Human Authority decisions still stop.

Do not start ChatGPT round trip while Codex remediation/re-review is
incomplete.

## 25. Master / Roadmap Reconciliation

Update existing Prime Directive, governance registry, Master Capability
Status Matrix, Master Wave Ownership Matrix, Master End-to-End status,
Master Program Status, M7 roadmap and capability artifacts as required.

Use structural CSV parsing.

Require:

``` text
MALFORMED_ROWS=0
DUPLICATE_CAPABILITY_IDS=0
P0_COUNT_AMBIGUITY=0
```

Do not create a competing control plane.

## 26. Required Artifacts

Produce/update in approved locations: -
`L5DGVA_RESULT_DRIVEN_AUTONOMOUS_CLOSED_LOOP_ADOPTION_REPORT.md` -
`M7_RESULT_TO_ACTION_ROUTING.md` -
`M7_AUTO_REMEDIATION_ELIGIBILITY.md` -
`M7_AUTONOMOUS_REMEDIATION_EVIDENCE.md` -
`M7_LOOP_TERMINATION_AND_BUDGET_POLICY.md` -
`M7_LOOP_EVIDENCE_TRACE.md` -
`M7_CODEX_FINDINGS_REMEDIATION_REPORT.md` -
`M7_CODEX_RE_REVIEW_HANDOFF_EVIDENCE.md`

Do not place reports in repository root.

## 27. Closure Requirements for This Integration Task

Require:

``` text
P6_RESULT_ACTION_AUTONOMOUS_CLOSURE=ADOPTED
RESULT_DRIVEN_AUTONOMOUS_CLOSED_LOOP=IMPLEMENTED_FOR_M7_FOUNDATION
RESULT_TO_ACTION_ROUTING=OPERATIONAL
AUTO_REMEDIATION_ELIGIBILITY=OPERATIONAL
AUTONOMOUS_REMEDIATION_EXECUTION=OPERATIONAL
AUTONOMOUS_REMEDIATION_VERIFICATION=OPERATIONAL
HUMAN_ESCALATION_POLICY=OPERATIONAL
LOOP_TERMINATION_POLICY=OPERATIONAL
LOOP_EVIDENCE_TRACEABILITY=OPERATIONAL
LOOP_RESUME_RECOVERY=OPERATIONAL_OR_EVIDENCE_BACKED_PARTIAL

HUMAN_IS_TRANSPORT_AND_AUTHORITY=YES
HUMAN_IS_WORKFLOW_SCHEDULER=NO

CURRENT_SCOPE_GAPS_OPEN=0
UNKNOWN_RUNTIME_CALLERS=0
UNCONTROLLED_BYPASSES=0
UNKNOWN_REGRESSION_FAILURES=0
SOURCE_CAPABILITY_LOSS=0
M6_GOLDEN_PATH_PRESERVED=YES
REFERENCE_USB_ENV_CONSUMED=NO
```

Do not force OPERATIONAL if evidence only supports PARTIAL; report
honestly and name the exact blocker.

## 28. Final Report

Report:

``` text
P6_ADOPTION_STATUS=READY_FOR_APPROVAL / PARTIAL / BLOCKED
RESULT_DRIVEN_AUTONOMOUS_CLOSED_LOOP=<status>
RESULT_TO_ACTION_ROUTING=<status>
AUTO_REMEDIATION_ELIGIBILITY=<status>
AUTONOMOUS_REMEDIATION_EXECUTION=<status>
AUTONOMOUS_REMEDIATION_VERIFICATION=<status>
AUTONOMOUS_REVIEW_LOOP=<status>
HUMAN_ESCALATION_POLICY=<status>
LOOP_TERMINATION_POLICY=<status>
LOOP_BUDGET_POLICY=<status>
LOOP_EVIDENCE_TRACEABILITY=<status>
LOOP_RESUME_RECOVERY=<status>

HUMAN_IS_TRANSPORT_AND_AUTHORITY=YES/NO
HUMAN_IS_WORKFLOW_SCHEDULER=NO/YES

CODEX_FINDINGS_TOTAL=7
CODEX_FINDINGS_CONFIRMED=<count>
CODEX_FINDINGS_PARTIAL=<count>
CODEX_FINDINGS_FALSE_POSITIVE=<count>

GAP_V2_009=<status>
GAP_V2_010=<status>
GAP_V2_011=<status>
GAP_V2_012=<status>

CURRENT_SCOPE_GAPS_OPEN=<count>
ORIGINAL_CODEX_RESULT_PRESERVED=YES/NO
ORIGINAL_CODEX_RESULT_REPLAY=<status>
DUPLICATE_SEMANTIC_CONSUMPTION=<count>

M6_GOLDEN_PATH_PRESERVED=YES/NO
REGRESSION_CAUSED_BY_REMEDIATION=<count>
UNKNOWN_REGRESSION_FAILURES=<count>
SOURCE_CAPABILITY_LOSS=<count>

RE_REVIEW_HANDOFF_READY=YES/NO
WAITING_FOR_HUMAN_TRANSPORT=YES/NO

AUTHORITATIVE_MASTER_P0_BLOCKER_COUNT=<count>
REFERENCE_USB_ENV_CONSUMED=NO

NEXT_REQUIRED_HUMAN_ACTION=
TRANSPORT_CODEX_RE_REVIEW_HANDOFF
or exact HumanGate/blocker.
```

## 29. STOP CONDITION

Proceed automatically through governance adoption, result
classification, eligible remediation, tests, regression, evidence
update, and re-review handoff generation.

Do **not** stop merely to ask the human whether to continue an
already-authorized remediation.

STOP only when: 1. a genuine HumanGate is reached; 2. an external-model
handoff is ready and human transport is required; or 3. a blocker
prevents safe continuation.

Do not start ChatGPT round trip automatically. Do not start M8.
