# L5DGVA DV Verification Environment Lifecycle Integration Prompt

## 0. Mission

Integrate **DV Verification Environment Lifecycle Management** as a
mandatory Canonical L5DGVA capability and add a **Native Claude CLI Fast
Maintenance Path** so bounded interactive maintenance does not always
invoke the full L5DGVA orchestration stack.

This task is REQUIREMENTS / ARCHITECTURE / ROADMAP /
MASTER-CONTROL-PLANE reconciliation only. Preserve current M5 execution.
Do not implement M10.5 now.

Freeze: 1. L5DGVA-generated verification environments are
lifecycle-managed DV assets, not disposable outputs. 2. DE owns Design
Intent and Design Fix. 3. DV owns Verification Architecture,
Verification Environment, maintenance, closure and Verification Signoff.
4. Native Claude CLI is a lightweight interaction/execution path, not a
second product, authority model, Knowledge Brain or verification engine.
5. Fast Path and Full L5DGVA share project identity, evidence,
ownership, provenance, change, validation and signoff contracts. 6. Use
**MINIMUM_SUFFICIENT_EXECUTION**: the lightest safe mechanism with
sufficient evidence. 7. Fast means less orchestration overhead, not
weaker governance.

## 1. Preflight / Safety

Verify Canonical repo identity; record PROCESS_CWD, REPO_ROOT,
CURRENT_BRANCH, CURRENT_HEAD and git status; read CLAUDE.md, Article 0,
Master Capability/Wave/Blocker/Program/E2E artifacts, DE/DV HITL,
M4.5/M4.6 and current M5 queue/status; verify Parent/v50/b7a/b7b/b8
unchanged.

Do not start M10.5/another wave, modify frozen sources, consume
Reference USB, start C6/Platform Upgrade, duplicate Master authority, or
dump this detailed spec into CLAUDE.md. Wrong repo =\>
`WRONG_L5_REPOSITORY` and STOP.

## 2. Article 0 Extension

Add only compact ALWAYS_ON discoverability if M4.6 requires it. Detailed
lifecycle rules remain TASK_SCOPED. Canonical concept:
`CREATE_LIFECYCLE + MAINTAIN_LIFECYCLE + MINIMUM_SUFFICIENT_EXECUTION`.
Preserve Minimum Sufficient Context.

## 3. Authority Model

Freeze DESIGN_AUTHORITY=DE; VERIFICATION_AUTHORITY=DV;
VERIFICATION_ENVIRONMENT_AUTHORITY=DV;
VERIFICATION_SIGNOFF_AUTHORITY=DV; SHARED_AUTHORITY=DE+DV only for
genuine cross-domain decisions. Native Claude CLI and L5DGVA agents are
execution mechanisms, never human authorities.

## 4. Design-Defect Invariant

If RCA identifies DUT/RTL/design defect, neither Fast Path nor Full
L5DGVA may alter the verification environment merely to hide defective
DUT behavior. Route
`RCA → DESIGN → DE → RTL/Spec fix → new design revision → change impact → DV environment update → regression/coverage/re-signoff`.
Temporary workarounds require explicit waiver/provenance/scope/removal
condition/signoff impact.

## 5. CREATE_LIFECYCLE

OpenSpec → Discovery → Knowledge → Clarification → Verification
Architecture → vPlan → Generation → Execution → Regression → RCA →
Coverage Closure → Traceability/Waiver → Signoff → Learning.

## 6. MAINTAIN_LIFECYCLE

Qualified Environment → Attach → Rehydrate → Semantic Drift/Change →
Debug/Evidence → RCA → Role Routing → Impact → Change Request/Plan →
Ownership → Change Workspace → Controlled Modification/Semantic Merge →
Selective Regression → Coverage Delta → Evidence Invalidation →
Re-Signoff → Qualified Snapshot → Learning.

## 7. Dual Maintenance Modes

**FAST_MAINTENANCE_MODE:** Native Claude CLI inside the DV project for
bounded/local debug, small sequence/test/checker/scoreboard/config
fixes, evidence inspection and focused validation.

**FULL_L5DGVA_MAINTENANCE_MODE:** full orchestration for
architecture/topology changes, multi-subsystem impact, unclear
ownership, low confidence, complex RCA, broad regeneration, coverage
closure, protected artifacts, broad evidence invalidation or
signoff-critical work.

These are two execution modes of ONE maintenance architecture.

## 8. Fast Path Eligibility

Create `FAST_PATH_ELIGIBILITY`. Fast Path requires valid project
identity/rehydration, known ownership, bounded scope, no unresolved
design-intent issue, no unauthorized protected-artifact edit, no broad
topology/architecture change, adequate confidence, available focused
validation, definable rollback and understood signoff impact. Thresholds
belong to policy/config.

## 9. Escalation to Full L5DGVA

Create `FAST_PATH_ESCALATION_TO_L5DGVA`. Support triggers equivalent to
SCOPE_EXPANDED, MULTI_SUBSYSTEM_IMPACT, ARCHITECTURE_CHANGE,
TOPOLOGY_CHANGE, DESIGN_INTENT_REQUIRED, SHARED_AUTHORITY_REQUIRED,
OWNERSHIP_UNKNOWN, PROTECTED_ARTIFACT, LOW_CONFIDENCE, RCA_UNRESOLVED,
COVERAGE_CLOSURE_REQUIRED, BROAD_EVIDENCE_INVALIDATION,
SIGNOFF_IMPACT_HIGH, SEMANTIC_MERGE_COMPLEX,
REGRESSION_SELECTION_UNCERTAIN, POLICY_REQUIRED_FULL_L5DGVA.

Escalation preserves session evidence; do not restart from zero.

## 10. Fast-to-Full Context Handoff

Create `FAST_TO_FULL_CONTEXT_HANDOFF`: PROJECT_ID, CHANGE_ID/FAILURE_ID,
intent, affected artifacts, ownership, evidence refs,
hypotheses/refutations, confidence, proposed changes, validation already
run, remaining failures, rollback state and authority decisions.

## 11. Native Claude Project Entry

Target DV UX may support:

    cd <verification-environment>
    claude

and/or `l5dgva attach`.

Native Claude must discover project-local L5DGVA identity/bootstrap and
must not require launch from Canonical source repo.

## 12. Project Bootstrap / Identity / Rehydration

A compact project-local bootstrap tells Claude this is L5DGVA-managed;
locate identity/manifest/ownership/snapshot; rehydrate before editing;
obey ownership; use evidence-grounded RCA; create a change record;
validate before apply; escalate when Fast eligibility fails; preserve
invalidation/re-signoff obligations. Never copy the full Canonical
CLAUDE.md into each project.

Metadata supports PROJECT_ID, VERIFICATION_LEVEL, PROTOCOLS,
GENERATION_ID, SCHEMA_VERSION, PROJECT_ROOT, MANIFEST_REF,
OWNERSHIP_REF, LAST_QUALIFIED_SNAPSHOT_REF, CREATION_PROVENANCE,
CURRENT_LIFECYCLE_STATE. No credentials or absolute bootstrap paths.

Rehydration reconstructs current context from identity, manifests,
ownership, provenance, snapshot, RTL/spec/OpenSpec/vPlan/files/evidence.
Rehydration is not regeneration.

## 13. VerificationEnvironmentIR

Define/reuse a machine-readable IR for DUT, level,
interfaces/protocols/topology, VIPs, agents, sequencers, scenarios,
FW/IRQ, checkers, scoreboards, assertions, coverage, tests, config,
clocks/resets, connections, requirements, vPlan, traceability,
ownership, provenance and qualified evidence. M9 owns generic
representation foundations; M10.5 operationalizes maintenance.

## 14. Artifact Provenance / Ownership

Track ARTIFACT_ID, PATH, ORIGIN, GENERATION_ID, SOURCE_INPUTS/HASHES,
GENERATOR_VERSION, LAST_MODIFIED_BY, LAST_CHANGE_ID, OWNERSHIP_CLASS,
SNAPSHOT_REF, EVIDENCE_REFS.

Ownership: L5_MANAGED, USER_MANAGED, SHARED_MANAGED, GENERATED_REGION,
PROTECTED. USER_MANAGED normally means DV/project customization.

Policy: L5_MANAGED may controlled-regenerate; USER_MANAGED never
silently overwrite; SHARED_MANAGED requires semantic merge;
GENERATED_REGION only regenerates managed region; PROTECTED requires
explicit authority; UNKNOWN ownership escalates.

## 15. CAP-M5-TOPTB-001

Map CAP-M5-TOPTB-001 only as possible foundation for ownership,
user-modification preservation, safe regeneration, semantic merge and
protected artifacts. Do not change its current M5 disposition.
Foundation != operational lifecycle capability.

## 16. Debug / Failure Evidence / RCA

Fast target:
`DV → project → claude → rehydrate → inspect log/FSDB/coverage/regression → hypotheses → evidence/refutation → root cause → bounded proposed change → focused validation`.

Structured failure evidence supports FAILURE_ID, TEST, SEED, BUILD_ID,
EXECUTION_ID, FAILURE_SIGNATURE, LOG_REFS, FSDB_REFS, COVERAGE_REFS,
RTL_REVISION, ENV_REVISION, CONFIGURATION, EVIDENCE_HASHES,
COLLECTION_TIME.

RCA must not directly mutate qualified files. RCA → Root
Cause/Confidence/Authority → Change Request.

## 17. Change Request / Role Routing

Change Request supports CHANGE_ID, ROOT_CAUSE/DOMAIN,
AFFECTED_ARTIFACTS, EVIDENCE_REFS, CONFIDENCE, PROPOSED_CHANGE,
EXPECTED_BEHAVIOR, IMPACT, RISK, AUTHORITY_ROLE, APPROVAL_STATE,
ROLLBACK_PLAN.

DESIGN defect → DE. VERIFICATION defect → DV/L5DGVA. SHARED ambiguity →
DE+DV. TOOL/ENVIRONMENT → automatic handling first then escalation.

## 18. Semantic Change / Impact

Track RTL_CHANGE, SPEC_CHANGE, OPENSPEC_CHANGE, INTERFACE_CHANGE,
REGISTER_CHANGE, PROTOCOL_CHANGE, TOPOLOGY_CHANGE, VIP_CHANGE,
VPLAN_CHANGE, COVERAGE_CHANGE, FW_CHANGE, CONFIG_CHANGE,
USER_REQUESTED_CHANGE, BUG_FIX, TOOLCHAIN_CHANGE.

`VERIFICATION_CHANGE_IMPACT_ANALYSIS` maps changes to requirements,
vPlan, artifacts, tests, coverage, evidence and waivers. Do not reduce
this to raw git diff.

## 19. Change Plan / Workspace

Change Request → Impact → Plan → Ownership → HumanGate if needed →
Working Change.

`CHANGE_WORKSPACE` isolates request, impact, evidence, proposed semantic
change/patch, validation and rollback while preserving qualified
baseline. Fast and Full modes use compatible records.

## 20. Controlled Modification

Fast Path may edit only through controlled-change policy: record change
identity/before-state; obey ownership; keep working change distinct from
qualified baseline; validate; record result; support rollback; escalate
if scope/risk expands.

## 21. Safe Regeneration / UVM Semantic Merge

Use A=previous generated, B=current DV-modified, C=new generated
candidate. Preserve A→B user/project delta while incorporating verified
A→C generator delta.

Long-term target is UVM-aware symbol/semantic merge, potentially using
Verible AST/exported JSON + UVM-aware models + ownership/provenance.
Generated/user regions may be an intermediate safety mechanism, not the
final architecture.

## 22. Review / Apply / Rollback

Future UX may expose equivalent operations `change review`,
`change apply`, `change rollback`. Native Claude may perform equivalent
Fast interactions. Both modes write compatible provenance/evidence
records. Apply after required validation/authority; rollback restores
known state or explicitly blocks if unsafe.

## 23. Selective Regression

Impact selects affected tests + dependency tests + smoke with rationale.
Fast Path may run focused regression for bounded changes; escalate when
insufficient for qualification/signoff.

## 24. Coverage Delta / Evidence Invalidation

Track Before → Change → After → Delta → new/regressed holes → closure.
Affected evidence uses equivalent states VALID, INVALIDATED, REVERIFY,
NEW, WAIVED. Fast Path cannot bypass required re-signoff.

## 25. Incremental Re-Signoff / Snapshot

Previous Signoff → Impact → Invalidation → Required Regression →
Coverage Closure → Traceability → Waiver Review → Incremental Re-Signoff
→ New Qualified Snapshot. DV remains Verification Signoff Authority.

Snapshot references design/env revisions, manifests, vPlan, regression
evidence, coverage, waivers, tool/config, hashes, signoff and
provenance.

## 26. Maintenance Traceability

Extend Requirement → vPlan → Test/Scenario →
Checker/Assertion/Scoreboard → Coverage → Regression Evidence → Waiver →
Human Decision → Signoff → Qualified Snapshot → Change → Impact →
Reverification → Re-Signoff.

## 27. Maintenance / Native-Claude Learning

M8 learns from predicted-vs-actual impact, RCA outcomes, merge
conflicts, ownership conflicts, regression selection, coverage delta,
invalidation correctness, re-signoff and DV decisions.

Native Claude sessions may generate experience candidates from
clarifications, successful/failed fixes, escalation reasons, focused
regression selection, repeated corrections, ownership conflicts and
rollback outcomes.

Raw chat is not authoritative knowledge. Distill evidence-grounded
outcomes through the existing single Knowledge Brain. Obsidian remains
adapter/interface, not sole authority.

## 28. Execution / Location / Security

Fast Path may invoke approved focused local/remote execution; Full mode
uses target ExecutionService. Do not hard-code hosts.

Moved/copied projects remain attachable after config resolution. No
runtime dependency on Canonical/Parent/v50 paths, usernames or hosts.

Future controlled modification acceptance includes path validation,
project boundary, symlink/path-traversal handling where relevant, atomic
writes, partial-write recovery, backup/rollback, secret exclusion and
overwrite protection.

## 29. Auditability

Every change records execution mode FAST/FULL, proposer, evidence,
authority, affected artifacts, before/after identity, tests, coverage
impact, invalidation, approval, apply result, rollback and resulting
snapshot.

## 30. Capability Matrix Additions

Add/reconcile without duplicates: -
DV_VERIFICATION_ENVIRONMENT_LIFECYCLE_MANAGEMENT -
NATIVE_CLAUDE_FAST_MAINTENANCE - MINIMUM_SUFFICIENT_EXECUTION -
FAST_PATH_ELIGIBILITY - FAST_PATH_ESCALATION_TO_L5DGVA -
FAST_TO_FULL_CONTEXT_HANDOFF - PROJECT_ATTACH_AND_REHYDRATION -
PROJECT_LOCAL_IDENTITY - PROJECT_CONTEXT_BOOTSTRAP -
ENVIRONMENT_REOPEN_IMPORT - VERIFICATION_ENVIRONMENT_IR -
GENERATED_ARTIFACT_PROVENANCE - ARTIFACT_OWNERSHIP_MODEL -
QUALIFIED_ENVIRONMENT_SNAPSHOT - SEMANTIC_CHANGE_DETECTION -
DEBUG_EXISTING_ENVIRONMENT - FAILURE_EVIDENCE_COLLECTION -
RCA_TO_CHANGE_REQUEST - VERIFICATION_CHANGE_IMPACT_ANALYSIS -
VERIFICATION_CHANGE_PLAN - CHANGE_WORKSPACE -
CONTROLLED_ENVIRONMENT_MODIFICATION - SAFE_INCREMENTAL_REGENERATION -
UVM_SEMANTIC_MERGE - USER_MODIFICATION_PRESERVATION -
CHANGE_REVIEW_APPLY - CHANGE_ROLLBACK - SELECTIVE_REGRESSION -
COVERAGE_DELTA_ANALYSIS - EVIDENCE_INVALIDATION -
INCREMENTAL_RESIGNOFF - MAINTENANCE_TRACEABILITY -
MAINTENANCE_EXPERIENCE_LEARNING - CHANGE_IMPACT_PREDICTION_LEARNING -
SEMANTIC_MERGE_EXPERIENCE_LEARNING

For each record CURRENT_STATE, PRIMARY_OWNER_WAVE, DEPENDENCIES,
PRIORITY, BLOCKER, EVIDENCE, ARTICLE0_DIMENSION. Distinguish
ROADMAP_DEFINED / FOUNDATION / IMPLEMENTED / WIRED / OPERATIONAL /
QUALIFIED using existing taxonomy.

## 31. Roadmap Ownership

Update: - M5: semantic-merge/top-TB/user-preservation foundations
only. - M6: VerificationLevel, ClarificationService, DE/DV HITL,
HumanGate, root-cause routing foundations. - M7: ChatGPT/Claude/Codex
orchestration and structured Fast↔Full context-handoff infrastructure
where appropriate. - M8: Knowledge Brain +
maintenance/interaction/prediction/merge learning. - M9: generic
IP/Subsystem/System-Level + VerificationEnvironmentIR foundations. -
M10: vPlan/coverage/traceability/waiver/signoff foundations. - **M10.5:
primary owner of DV Verification Environment Lifecycle Management and
Native Claude Fast Maintenance operationalization.** - M11: USB Golden
qualifies Create, Maintain, Native Fast Path and Fast→Full escalation. -
M12: productization/UX. - M13: strict-superset/final qualification
includes lifecycle and Fast Path.

Do not redirect current execution away from M5.

## 32. M11 USB Golden Expansion

Qualification must include: A. from-scratch generation through signoff;
B. existing qualified environment after RTL/spec change: attach, detect,
impact, preserve DV customization, modify, selective regression,
coverage delta, re-signoff; C. bounded maintenance defect solved through
Native Claude Fast Path; D. Fast Path task correctly escalating to Full
L5DGVA with context/evidence preserved.

Do not consume Reference USB during this reconciliation.

## 33. E2E / UX Requirements

Update Master E2E with CREATE_LIFECYCLE and MAINTAIN_LIFECYCLE. For
Maintain stages record CURRENT_STATUS, FOUNDATION/OPERATIONAL,
DEPENDENCIES, OWNER_WAVE, HUMAN_ROLE, AUTOMATION_OWNER,
FAST_PATH_ELIGIBLE, FULL_L5DGVA_REQUIRED_CONDITIONS, EVIDENCE.

Future DV UX may include equivalents of: `l5dgva create`, `attach`,
`status`, `debug`, `impact`, `change plan/review/apply/rollback`,
`verify`, `signoff`, plus direct `claude` inside a managed project.

Do not freeze exact CLI syntax if existing CLI governance prefers
another form.

## 34. Required Artifacts

Produce/update under approved work area, not repo root: -
DV_VERIFICATION_ENVIRONMENT_LIFECYCLE_ARCHITECTURE.md -
NATIVE_CLAUDE_FAST_MAINTENANCE_ARCHITECTURE.md -
FAST_PATH_ELIGIBILITY_AND_ESCALATION.md -
FAST_TO_FULL_CONTEXT_HANDOFF_CONTRACT.md -
PROJECT_ATTACH_REHYDRATION_REQUIREMENTS.md -
ARTIFACT_OWNERSHIP_REQUIREMENTS.md -
VERIFICATION_ENVIRONMENT_MAINTENANCE_CAPABILITY_MATRIX.csv -
MAINTAIN_LIFECYCLE_E2E_MATRIX.csv - M10_5_ROADMAP_REQUIREMENTS.md -
USB_GOLDEN_MAINTENANCE_QUALIFICATION_REQUIREMENTS.md

Update existing Master Capability Status Matrix, Master Wave Ownership
Matrix, Master End-to-End DV Status and Master Program Status. Do not
create competing authority.

## 35. Validation Gates

Require: - CREATE_LIFECYCLE_DEFINED = YES - MAINTAIN_LIFECYCLE_DEFINED =
YES - DV_OWNS_VERIFICATION_ENVIRONMENT = YES -
NATIVE_CLAUDE_FAST_MAINTENANCE = ROADMAP_DEFINED -
MINIMUM_SUFFICIENT_EXECUTION = DEFINED - FAST_PATH_ELIGIBILITY =
DEFINED - FAST_PATH_ESCALATION = DEFINED - FAST_TO_FULL_CONTEXT_HANDOFF
= DEFINED - FAST_AND_FULL_SHARE_GOVERNANCE = YES -
FAST_PATH_BYPASSES_ARTIFACT_OWNERSHIP = NO - FAST_PATH_BYPASSES_EVIDENCE
= NO - FAST_PATH_BYPASSES_SIGNOFF = NO -
ONE_GENERIC_MAINTENANCE_WORKFLOW = YES -
SEPARATE_DE_DV_MAINTENANCE_ENGINES = NO - ARTIFACT_OWNERSHIP_MODEL =
ROADMAP_DEFINED - USER_MANAGED_OVERWRITE_ALLOWED = NO -
SAFE_INCREMENTAL_REGENERATION = ROADMAP_DEFINED - UVM_SEMANTIC_MERGE =
ROADMAP_DEFINED - SELECTIVE_REGRESSION = ROADMAP_DEFINED -
COVERAGE_DELTA = ROADMAP_DEFINED - EVIDENCE_INVALIDATION =
ROADMAP_DEFINED - INCREMENTAL_RESIGNOFF = ROADMAP_DEFINED -
MAINTENANCE_EXPERIENCE_LEARNING = ROADMAP_DEFINED -
PROJECT_LOCATION_INDEPENDENT = REQUIRED -
M4_6_CONTEXT_ARCHITECTURE_PRESERVED = YES - CURRENT_M5_GATE_PRESERVED =
YES - PRODUCTION_IMPLEMENTATION_STARTED = NO -
REFERENCE_USB_ENV_CONSUMED = NO

Run applicable Constitution/Anti-Drift,
governance-registry/reference-graph and Master-control-plane consistency
tests. Do not run full product regression unless current governance
requires it for roadmap-only changes.

## 36. Final Report

Report: - DV_ENV_LIFECYCLE_INTEGRATION_STATUS = READY_FOR_APPROVAL /
PARTIAL / BLOCKED - CREATE_LIFECYCLE = DEFINED / PARTIAL -
MAINTAIN_LIFECYCLE = DEFINED / PARTIAL - NATIVE_CLAUDE_FAST_MAINTENANCE
= ROADMAP_DEFINED / PARTIAL / NOT_DEFINED - MINIMUM_SUFFICIENT_EXECUTION
= DEFINED / PARTIAL - FAST_PATH_ELIGIBILITY = DEFINED / PARTIAL -
FAST_PATH_ESCALATION_TO_L5DGVA = DEFINED / PARTIAL -
FAST_TO_FULL_CONTEXT_HANDOFF = DEFINED / PARTIAL -
VERIFICATION_ENVIRONMENT_AUTHORITY = DV - PROJECT_ATTACH_AND_REHYDRATION
= ROADMAP_DEFINED / PARTIAL - ARTIFACT_OWNERSHIP_MODEL = ROADMAP_DEFINED
/ PARTIAL - SAFE_INCREMENTAL_REGENERATION = ROADMAP_DEFINED / PARTIAL -
UVM_SEMANTIC_MERGE = ROADMAP_DEFINED / PARTIAL - SELECTIVE_REGRESSION =
ROADMAP_DEFINED / PARTIAL - COVERAGE_DELTA_ANALYSIS = ROADMAP_DEFINED /
PARTIAL - EVIDENCE_INVALIDATION = ROADMAP_DEFINED / PARTIAL -
INCREMENTAL_RESIGNOFF = ROADMAP_DEFINED / PARTIAL -
MAINTENANCE_EXPERIENCE_LEARNING = ROADMAP_DEFINED / PARTIAL -
MASTER_CAPABILITIES_ADDED_OR_RECONCILED = `<count>`{=html} -
P0_BLOCKERS_BEFORE = `<count>`{=html} - P0_BLOCKERS_AFTER =
`<count>`{=html} - CURRENT_PROGRAM_POSITION = `<position>`{=html} -
CURRENT_M5_GATE_PRESERVED = YES / NO - NEXT_RECOMMENDED_GATE =
`<gate>`{=html} - M10_5_STARTED = NO - REFERENCE_USB_ENV_CONSUMED = NO -
PLATFORM_UPGRADE_STARTED = NO

## 37. STOP

After all required roadmap/control-plane artifacts are reconciled and
validated, STOP.

Do not implement Native Claude Fast Maintenance. Do not implement M10.5.
Do not start another wave. Resume the previously approved M5 sequence
only after explicit review.
