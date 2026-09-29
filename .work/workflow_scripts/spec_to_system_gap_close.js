export const meta = {
  name: 'spec-to-system-gap-close',
  description: 'Close the highest-value confirmed real gaps from the SPEC-TO-SYSTEM UVM generation factory audit (sections 181-216) -- real implementation, explicitly authorized by the user',
  phases: [
    { title: 'Build', detail: 'sequential, reuse-first close pass' },
    { title: 'Review', detail: 'independent re-verification' },
  ],
}

const CONTEXT = `
This closes the highest-value confirmed real gaps from a fresh, thorough
completeness audit run earlier this session against
D:/DV/Task/DV_Agent_Harness_L5/v50/, covering sections 181-216 of
D:/DV/Task/DV_Agent_Harness_L5/CLAUDE_DV_Agent_Harness_L5_SPEC_TO_SYSTEM_UVM_COMPLETE.md
(the "Spec-to-System VIP-Based UVM Generation Factory" -- Flow A: spec ->
subsystem UVM; Flow B: subsystem UVM -> system-level UVM). That document's own
final section ends with the explicit human-approval-required stop condition
("IMPLEMENTATION NOT STARTED UNLESS EXPLICITLY APPROVED / AWAITING USER
REVIEW / APPROVAL"). The user has now explicitly authorized implementation of
the gaps below ("開啟多個Agent 將所有缺口和問題都補上實做").

THE HEADLINE FINDING this close-pass exists to fix: there are TWO DISCONNECTED
implementation tracks for Flow B (subsystem -> system-level). Track A
(dv_harness/environment_mode_router.py -> uvm_generator/create_environment.py
-> uvm_generator/soc_environment_composer.py) is real and engine-wired but has
never fired in production and composes blind to cross-subsystem findings.
Track B is a large, separately-built, well-tested "SYS-1..40" family
(subsystem_discovery.py, system_resource_inventory.py, system_readiness.py,
system_topology_analysis.py, system_command_plan.py, system_scheduling_plan.py,
system_regression_plan.py, system_failure_triage.py, system_phase1_report.py,
etc. -- ~360-440 real tests) that does real, evidence-grounded cross-subsystem
analysis (shared-resource conflict detection, active-driver-ownership
blocking, address/clock-reset reconciliation) but is reachable ONLY via
human-typed CLI verbs, is never imported by engine.py, and -- most
seriously -- is never imported by ANY of the 14 real
tools/verification_flow/system_level_*.py gate scripts that actually decide
SYSTEM_LEVEL PASS/FAIL (those gates were confirmed to be pure JSON-shape
checks over agent-self-attested evidence text, zero dv_harness imports). This
means a composed system environment can currently pass every SYSTEM_LEVEL
gate on hand-typed evidence alone, with zero real cross-subsystem
verification and zero real compile ever having run.

This project has an extremely strong, repeatedly-enforced norm against
building parallel/duplicate mechanisms (CLAUDE.md's "Methodology
Consolidation Rule"). Before building anything, independently re-verify the
gap is real with your own grep/read commands (audits can go stale) and find
the closest existing real mechanism to extend. Read
D:/DV/Task/DV_Agent_Harness_L5/v50/CLAUDE.md first in every close-pass.

Check git status/git diff before touching any shared file (dv_harness/gates.py,
dv_harness/system_readiness.py, dv_harness/system_resource_inventory.py,
dv_harness/uvm_generator/soc_environment_composer.py,
tools/verification_flow/system_level_*.py, dv_harness/env_manifest.py,
dv_harness/golden_flow_readiness.py, dv_harness/cli.py -- THREE separate
concurrently-running close-passes this session also touch dashboard.py,
capability_evolution.py, engine.py, models.py, gates.py, waiver_store.py,
signoff_export.py, coverage_analysis.py) -- use the hand-scoped patch
technique (git diff > patch, trim to your hunk, git apply --cached --check
then --cached) rather than a broad git add.

DO NOT touch dv_harness/dashboard.py in this pass -- three other concurrent
close-passes this session are actively modifying it; a Generation Center GUI
card is a real, confirmed gap (section 214) but is explicitly deferred to a
later, dedicated pass to avoid a 4-way collision on that one file.

CRITICAL, non-negotiable: never weaken any existing human-approval gate
(HumanApprovalRequiredError, ProductionWriteNotAuthorizedError,
ControlPlane.approve, SYS-39/40's own human-approval-required stop before
generating actual system command.txt / scenario bodies / shared driver code).
Never trigger a real production build/regression/LSF submission -- test only
against synthetic/local fixtures. The active-driver-ownership ARBITRATION
(picking a winner between two conflicting drivers) must remain a human
decision -- you are wiring the existing DETECTION into the real gates, never
adding automatic arbitration. If a gap is a much larger effort than expected
once you're in the code, scope down to a real, honest, smaller-but-still-
genuine version rather than leaving it half-built, and report EXACTLY what
you built vs. deferred.
`

phase('Build')

const gaps = [
  `SPEC-1 (Wire Track A/Track B + wire both into the real SYSTEM_LEVEL gates --
   the headline finding): confirmed that dv_harness/uvm_generator/
   soc_environment_composer.py (Track A, engine-wired) never imports the
   real "SYS-1..40" cross-subsystem analysis family (Track B:
   system_resource_inventory.py's apply_active_driver_conflict_rule(),
   system_readiness.py's derive_system_readiness(), system_topology_analysis.py's
   reconcile_address_maps()/compare_clock_reset_domains()), and that NONE of
   the 14 real tools/verification_flow/system_level_*.py gate scripts (e.g.
   system_level_deadlock_livelock_gate.py, system_level_resource_contention_gate.py,
   system_level_composition_gate.py) import any dv_harness analysis module --
   they only validate agent-self-attested JSON shape. This is the single
   highest-value fix in the whole audit. Build: (a) have
   compose_soc_environment() (or its caller) consult Track B's real
   analysis output (subsystem registry entries' resource/topology/ownership
   findings) before/during composition rather than composing blind to it;
   (b) modify at least the system_level_resource_contention_gate.py and
   system_level_composition_gate.py (the two most directly relevant of the
   14) to actually CALL system_resource_inventory.py's real conflict
   detection / system_readiness.py's real derivation as part of their
   verdict, rather than trusting only the agent-supplied JSON block -- an
   agent-typed "no conflict" claim that contradicts the real Track-B
   analysis must be caught, not silently accepted. Preserve the existing
   requirement that an ACTIVE_DRIVER_CONFLICT/DRIVER_CONFLICT finding stops
   at BLOCKED and requires human arbitration -- do not add automatic
   conflict resolution. Write a real test proving a hand-typed "all clear"
   evidence block is REJECTED by the gate when the real Track-B analysis
   over the same subsystems detects a genuine conflict.`,

  `SPEC-2 (System Build & Proof smoke-proof ladder, section 206): confirmed
   NEVER_BUILT -- system_readiness.py's derive_system_readiness() is a
   static metadata rollup (its own docstring says so: "authorizes nothing...
   no System-Level filelist exists to compile"), and no code anywhere
   executes the document's actual ladder (Build->Elaborate->Boot/Reset/
   Init->Shared-Resource-Access->One-Subsystem->Two-Subsystem-Interaction->
   End-to-End-Scenario->WAVE=1/fsdbreport->Scoreboard/Assertion->
   SYSTEM_READY). Build a real, honestly-scoped smoke-proof driver that
   reuses the EXISTING per-subsystem real mechanisms at each rung it can
   (connectivity.py's run_gate1_elaboration_check()/run_gate2_against_live_simv()
   for Build/Elaborate, fsdb_report.py's run_fsdbreport() for the WAVE step,
   evidence_db.py for scoreboard/assertion evidence) applied across the
   composed system_tb_top.sv Track A produces, rather than inventing a
   parallel compile/elaborate mechanism. Where a rung genuinely requires
   real VCS/hardware this environment may not have, honestly report
   NOT_AVAILABLE per the project's existing convention (same as
   connectivity.py's gates already do) rather than fabricating a PASS.
   Also add real duplicate-package/config_db-conflict/factory-collision/
   virtual-interface-conflict detection as a static check over the composed
   files (this part IS fully buildable without real VCS -- it's a text/AST
   check for duplicate class names, duplicate config_db set paths, etc.
   across the merged subsystem files). Write real tests against a synthetic
   multi-subsystem fixture, including one with a real injected duplicate
   config_db path that the check catches.`,

  `SPEC-3 (Canonical Requirement Contract + status vocabulary, section 184):
   confirmed NEVER_BUILT -- 0 hits for "Canonical Requirement Contract"
   repo-wide; the closest existing schema
   (tools/verification_flow/spec_to_vplan_requirement_quality_gate.py) has a
   materially smaller field set (missing Protocol/Configuration/
   Precondition/Observability/Checker/Coverage Intent/Priority/Criticality)
   and no COMPLETE/PARTIAL/AMBIGUOUS/CONTRADICTORY/UNKNOWN status
   vocabulary. Build a real dv_harness/requirement_contract.py schema
   (dataclass + JSON schema, following env_manifest.py's schema-versioning
   convention) with the document's 14 named fields (ID/Source/Feature/
   Protocol/Configuration/Precondition/Stimulus/Expected Result/
   Observability/Checker/Coverage Intent/Priority/Criticality/Confidence/
   Status) and the 5-value status enum. Extend (never replace)
   spec_to_vplan_requirement_quality_gate.py to validate against this
   richer contract when a requirement record declares itself in this shape,
   preserving its existing behavior for requirements in the older shape.
   Write real tests covering all 5 status values and a requirement missing
   a required field being correctly rejected/flagged.`,

  `SPEC-4 (VIPApiCard evidence-gated artifact + "unprovable API -> BLOCKED"
   enforcement, section 187): confirmed NEVER_BUILT as CODE -- the
   Need-Op->Example->Manual/Source/Class-Ref->Extract->Validate->VIPApiCard->
   Sequence flow exists only as prose instruction in
   .claude/skills/CORE/vip-scenario-branch/SKILL.md and pcie-environment-
   builder/SKILL.md, trusted entirely to an LLM's judgment with no coded
   enforcement -- confirmed no code path rejects/flags an unprovable VIP API
   call. dv_harness/vip_symbol_index.py is the closest real cousin (indexes
   class/method declarations + file:line for navigation, never validates a
   call's actual signature against what it indexed). Build a real
   VIPApiCard record (the artifact: which VIP class/method was cited, the
   real file:line vip_symbol_index.py resolved it to, a validation status)
   and a real validate_vip_api_usage() check that, given a generated
   sequence's VIP API calls and vip_symbol_index.py's real index, flags any
   call to a class/method NOT found in the index as UNPROVABLE/BLOCKED
   rather than letting it through silently. Reuse vip_symbol_index.py's
   real indexing, don't rebuild it. Write a real test: a call to a real
   indexed method passes; a call to a fabricated method name is BLOCKED.`,

  `SPEC-5 (Generation Readiness Matrix, section 211): confirmed NEVER_BUILT
   as a rendered artifact (confirmed via negative grep for "generation
   readiness"/"GF-AT-" -- only self-references inside this spec and inside
   golden_flow_readiness.py's own docstring for its OWN different section-47
   matrix). golden_flow_readiness.py (real, committed) is the exact right
   PATTERN to reuse: a ROWS tuple of row-specs each declaring dotted-path
   fact_source readers, assert_fact_sources_resolvable() proving every
   reader still imports, status vocabulary borrowed not re-minted, and
   Next-Best-Action via the real inference.next_best_action(). Build a
   SEPARATE dv_harness/generation_readiness.py (never overload
   golden_flow_readiness.py with a second, differently-shaped matrix) with
   this document's specific 20 rows (Spec Parsing/Requirement IR through
   System Build/Smoke Proof), wiring in env_manifest.py, protocol_capability.py,
   connectivity.py, qualification.py, system_resource_inventory.py,
   system_readiness.py, system_topology_analysis.py as the real per-row
   fact_source readers -- reuse those modules' real data, never re-derive.
   Add a CLI subcommand following cli.py's existing conventions (e.g.
   alongside golden-flow-readiness). Write a real test proving all fact
   sources resolve and the matrix renders honest NOT_AVAILABLE/UNKNOWN for
   rows whose backing mechanism (e.g. the SPEC-2 smoke-proof ladder, if not
   yet landed when you run) doesn't exist yet -- never fabricate a row's
   status.`,

  `SPEC-6 (small, precise fix -- REMOVE_DUPLICATE vocabulary value, section 198):
   confirmed the Shared Resource/VIP Resolver's real decision vocabulary in
   dv_harness/system_resource_registry.py (REUSE_SHARED/KEEP_INDEPENDENT/
   PASSIVE_ONLY/RECONFIGURE/MERGE_ACCESS_PATH/BLOCKED/UNKNOWN) is genuinely
   missing REMOVE_DUPLICATE -- the closest existing value is PASSIVE_ONLY
   for a MONITOR_ONLY_DUPLICATE classification, which is a different
   decision (keep it as a passive monitor vs. remove it entirely). Add
   REMOVE_DUPLICATE as a real, distinct decision value with its own
   real classification logic (when a duplicate resource is genuinely
   redundant with zero unique observability/control value, as opposed to
   PASSIVE_ONLY's "duplicate but still useful as a monitor"), wired through
   wherever the existing 6 values are consumed (system_resource_registry.py,
   any caller in system_resource_inventory.py/system_readiness.py). Small,
   bounded fix -- write a real test distinguishing when a duplicate should
   classify as REMOVE_DUPLICATE vs. PASSIVE_ONLY.`,

  `SPEC-7 (per-artifact generation provenance tuple, section 210): confirmed
   PARTIALLY_WIRED -- env_manifest.py carries schema_version (line ~1098,1286)
   and tool_version (~711) but has no agent/skill identifier, input_ir
   reference, or repository_sha/git_sha field anywhere, and
   git_governance.py has no per-artifact SHA-stamping function (only
   push/merge branch-protection). Extend env_manifest.py's existing
   provenance fields (never invent a parallel provenance record) to also
   carry: which agent/skill produced the artifact (a string identifier,
   following whatever convention .claude/agents/*.md profiles already use
   for self-identification), a reference to the input that drove generation
   (a requirement-contract ID once SPEC-3 lands, or a path/hash if SPEC-3
   isn't landed yet when you build this), and the real current git SHA
   (reuse the existing git-SHA-reading utility already used elsewhere in
   this codebase for source-identity verification -- grep for it rather
   than reimplementing). Write a real test proving a generated manifest
   carries all of: schema_version, tool_version, agent identifier, and a
   real git SHA matching the actual repo HEAD at generation time.`,
]

log(`Building ${gaps.length} confirmed spec-to-system gaps sequentially. dashboard.py is explicitly OUT OF SCOPE for this pass (3 other concurrent close-passes touch it).`)

const closeResults = []
for (const [i, name] of gaps.entries()) {
  const label = name.slice(0, name.indexOf(':')).trim() || `gap-${i}`
  const fixResult = await agent(`Working directory: D:\\DV\\Task\\DV_Agent_Harness_L5\\v50

## Background

${CONTEXT}

You are handling exactly ONE gap: **${name}**

Read D:/DV/Task/DV_Agent_Harness_L5/v50/CLAUDE.md first (at least the sections
relevant to your gap's neighboring mechanisms: Environment Generation Mode,
Per-Protocol Capability, the Engineering Discipline Rules). Check git
status/git diff on any file you plan to touch FIRST -- other close-passes in
this same sequential loop, AND three separate concurrently-running workflows
this session (touching dashboard.py, capability_evolution.py, engine.py,
models.py, gates.py, waiver_store.py, signoff_export.py, coverage_analysis.py,
tools/verification_flow/*.py), may have already changed shared files. Re-read
fresh if so, and use the hand-scoped patch technique (git diff > patch, trim
to your hunk, git apply --cached --check then --cached) rather than a broad
git add. Do NOT touch dv_harness/dashboard.py -- explicitly out of scope for
this pass.

## Your task

1. Independently re-verify this gap is real (grep/read) before building.
2. Build the real mechanism described above, reusing existing real code
   wherever named -- never a parallel/duplicate mechanism.
3. Preserve every existing human-approval gate exactly as-is, including
   SYS-39/40's stop-before-generating-real-system-artifacts boundary and the
   active-driver-conflict human-arbitration requirement. Never trigger a
   real production build/regression/LSF submission -- test only against
   synthetic/local fixtures.
4. Write real tests proving the mechanism works, not just that an isolated
   function returns a value.
5. Run the full relevant test suite for what you touched and confirm pass.
6. Commit your change for real with a clear, scoped commit message.
7. If this gap is a much larger effort than expected once you're in the
   code, scope down to a real, honest, smaller-but-still-genuine version
   rather than leaving something half-built or fabricating a result --
   report exactly what you built vs. deferred and why.

Write a report to .work/gap-close-sts-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}-report.md.
Report DONE / PARTIAL / BLOCKED, with a one-line test summary.`, {label: `close:${label}`, phase: 'Build', model: 'claude-opus-5'})
  closeResults.push([label, fixResult])
  log(`Closed pass done for ${label}.`)
}

phase('Review')

const review = await agent(`Independently review this "close the SPEC-TO-SYSTEM generation factory gaps" effort for DV Agent Harness L5. Do not accept any report's own claim without independent re-verification -- run real commands yourself.

Read every close-pass report in full first (search .work/ for files matching gap-close-sts-*-report.md).

Raw returned results, for cross-reference:
${closeResults.map(([name, result]) => `#### ${name}\n${result}`).join('\n\n')}

Verify independently:
1. For every close-pass reporting DONE or PARTIAL: did the fix actually work, verified by you running something real?
2. CRITICAL top priority: for SPEC-1, confirm a hand-typed "all clear" evidence block really IS rejected now when real Track-B analysis detects a genuine conflict -- run this yourself, don't trust the report. Confirm active-driver-conflict resolution is STILL a human decision (no automatic arbitration was added).
3. Grep every diff this pass made for any change to human-approval-gate logic, SYS-39/40's stop condition, or governance boundaries -- confirm none were weakened. Confirm no gap triggered a real production build/regression/LSF submission.
4. Confirm dv_harness/dashboard.py was NOT touched by this pass.
5. Run the full project test suite (python -m pytest dv_harness_tests/ -q) and report the real pass/fail count.
6. Check git hygiene across all commits this pass made.

Report a clear verdict per gap (GENUINELY_CLOSED / PARTIALLY_CLOSED / STILL_GAP / HONESTLY_BLOCKED) plus an overall verdict (APPROVED / NEEDS_FIX), with concrete evidence-cited findings.`, {label: 'final-review', phase: 'Review', model: 'claude-opus-5'})

return { closeResults: Object.fromEntries(closeResults), review }
