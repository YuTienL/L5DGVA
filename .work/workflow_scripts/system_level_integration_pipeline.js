export const meta = {
  name: 'system-level-integration-pipeline',
  description: 'Install System-Level Verification Integration discovery/planning/reporting (SYS-1..38) as real, reuse-first tooling extending create_environment.py / soc_environment_composer.py / connectivity.py / knowledge_center.py -- discovery/planning/reporting ONLY, per the master prompt\'s own SYS-39/SYS-40 mandatory human-review gate before any real system-level UVM/command.txt implementation',
  phases: [
    { title: 'Audit', detail: '8 parallel audits of SYS-1..38 against real code' },
    { title: 'Build', detail: 'sequential, reuse-first build of the discovery/planning/reporting machinery' },
    { title: 'Review', detail: 'independent re-verification incl. the SYS-39/40 stop-before-implementation gate' },
  ],
}

const CONTEXT = `
This implements ONLY SYS-1 through SYS-38 (discovery, analysis, planning,
reporting) from the "FIRST-CLASS DOMAIN EXTENSION -- SYSTEM-LEVEL
VERIFICATION INTEGRATION WORKFLOW" section (SYS-1..42) at the end of
D:/DV/Task/DV_Agent_Harness_L5/DV_Agent_Harness_L5_ULTIMATE_COMPLETE_Master_Prompt_AMBA4_CCE_Research_SystemLevel.md
(read it yourself for your scope's exact wording -- lines 4274-4519; a diff
confirmed everything before line 4274 is byte-identical to the AMBA4/CCE
master prompt already handled by a separate, out-of-scope workflow, so this
scope starts clean at the "FIRST-CLASS DOMAIN EXTENSION" heading).

Mission stated by the doc: build a System-Level Verification Environment by
REUSING user-selected, existing Subsystem-Level Verification Environments
(PCIe, USB, MIPI-CSI2, MIPI-DSI, Ethernet, CAN-FD, eMMC/MMC, SDIO, SD,
AMBA/SoC Bus, etc). The user decides which subsystems participate; the
Harness must never assume all available subsystems should be integrated.

The document's OWN gate is explicit and non-negotiable, quoted verbatim:

SYS-39 (PHASE-1 STOP CONDITION):
"After analysis report exactly:
SYSTEM-LEVEL INTEGRATION DISCOVERY COMPLETE
SELECTED SUBSYSTEM EXISTENCE CHECK COMPLETE
KNOWLEDGE CENTER CHECK COMPLETE
SUBSYSTEM ARCHITECTURE ANALYSIS COMPLETE
SUBSYSTEM command.txt ANALYSIS COMPLETE
VIP / AGENT DEDUPLICATION COMPLETE
SYSTEM command.txt PLAN COMPLETE
SYSTEM-LEVEL IMPLEMENTATION NOT STARTED
AWAITING USER APPROVAL
STOP."

SYS-40 (PHASE-2 IMPLEMENTATION -- ONLY AFTER APPROVAL):
"After explicit approval: create/update System-Level env; reuse selected
subsystem envs; create/update System Resource Registry; resolve approved
shared agents; implement System virtual sequencer/router; command
routing/adapters; generate System command.txt; connect subsystem
scoreboards; add cross-subsystem correlation; integrate build/filelists/
config; static checks; build; verify; WAVE=1; fsdbreport; targeted/System
regression; benchmark; signoff evidence; PR; Human Review. Never direct-push
main."

This workflow's scope is bounded to building the DISCOVERY/ANALYSIS/
PLANNING/REPORTING machinery for SYS-1..38 only. NEVER generate a real
System-Level UVM environment, a real System command.txt, a real System
Virtual Sequencer, or any real command routing/adapter. NEVER modify a real
generated subsystem environment outside its own SUBSYSTEM_MODE flow. NEVER
auto-apply anything downstream of a SYSTEM_RESOURCE_REGISTRY entry into a
real bind/UVM/command.txt artifact. A synthetic fixture (fake registry
entries, a fake command.txt pair, a fake address map) is fine for testing
your own discovery/dedup/planning logic; writing real System-Level UVM
source or a real System command.txt anywhere outside a throwaway test
fixture is not in scope, full stop -- that is SYS-40, gated on a SEPARATE,
explicit human approval this workflow does not obtain.

REUSE-FIRST is this document's own repeated instruction (preamble: "SEARCH
EXISTING L5 FIRST before adding Agent/Skill/Node/state/schema", and the
SYS-42 GOLDEN RULE opens "REUSE BEFORE REBUILD... DETECT DUPLICATE ACTIVE
VIPs BEFORE SYSTEM BUILD"), and this project has an extremely strong,
independently-verified history this session of exactly the opposite failure
mode (parallel tiered-confidence classifiers, duplicate memory mechanisms,
a second AMBA signal table) being caught as a real defect. Real,
already-confirmed overlap points (re-verify with your own grep/read, do not
just cite this list):

- CLAUDE.md's "Environment Generation Mode" section: SUBSYSTEM_MODE vs
  SYSTEM_LEVEL_MODE is already dispatched at the real generation entry
  point. tools/generate_protocol_uvm_environment.py routes through
  dv_harness/uvm_generator/create_environment.py, which resolves the mode
  via dv_harness/environment_mode_router.py's resolve_environment_mode()
  (single subsystem -> SUBSYSTEM_MODE, two-or-more -> SYSTEM_LEVEL_MODE),
  dispatches to ProtocolEnvGenerator or
  soc_environment_composer.compose_soc_environment(), composes ONLY from
  the REAL registry (environment_mode_router.read_registered_subsystem_entries(),
  written solely by dv_harness/engine.py's _persist_subsystem_registry_entry()
  on a gate-validated SIGNOFF PASS via
  tools/verification_flow/subsystem_environment_registration_gate.py), and
  REFUSES with create_environment.SubsystemModeRequiredError naming the
  missing subsystems rather than composing a partial subset -- this is
  effectively SYS-1's "require explicit user selection" plus part of
  SYS-2's existence-check discipline already enforced as code, not prose.
  dv_harness_tests/test_system_level_soc_composition_wiring.py and
  dv_harness_tests/test_environment_mode_router.py prove this end to end.
- dv_harness/uvm_generator/soc_environment_composer.py:
  cross_subsystem_scenarios() / end_to_end_scoreboard() / system_coverage()
  raise NotImplementedError ON PURPOSE, with an explicit comment: a
  subsystem_environment_registry entry carries only identity/qualification
  metadata (name, release_sha, qualification_state, interface/clock-reset
  compatibility flags), never sequence-body semantics, so a generic composer
  has no primary source to draw protocol-BEHAVIOR content from -- this is
  exactly the "No Golden-Reference Content Mining" rule applied to
  system-level composition. This is very likely close to exactly what
  SYS-26/27/30 (scoreboard integration, cross-subsystem checking, scenario
  model) ask for: a real cross-subsystem topology descriptor
  (address/interrupt/DMA maps) that does not exist yet. Building that
  DESCRIPTOR SCHEMA and a planning/reporting layer over it is in scope;
  actually filling in cross_subsystem_scenarios()/end_to_end_scoreboard()/
  system_coverage() with real protocol-behavior content is NOT -- that
  crosses into SYS-40 territory the moment it emits real sequence bodies.
- This repo's OWN .dv-harness/soc-composer/subsystem_environment_registry.json
  (the real runtime file _persist_subsystem_registry_entry() writes to) does
  not exist on disk yet -- only a _template.json sibling
  ({"subsystems": []}) and .dv-harness/soc-composer/soc_request_template.json /
  soc_composition_manifest_template.json. This repo legitimately has no
  multi-subsystem project of its own, so the real registry is empty by
  honest absence, not a bug. Re-verify this is still true.
- .dv-harness/system-level/composition_policy.json, .dv-harness/universal-
  protocol-platform/system_level/system_level_selection_policy.json, and
  tools/real_env/system_level_validator.py (86 lines, real, referenced by
  gates.py/engine.py/qualification.py, cross-checks a claimed subsystem set
  against the real persisted registry via a --registered flag) are real,
  wired policy/gate scaffolding for SYS-1/2/4/15/37-shaped concerns.
  .dv-harness/workflow/system_level_composition.schema.json,
  system_level_resource_contention.schema.json, and
  system_level_traceability.schema.json are illustrative EXAMPLE-VALUE JSON
  files (literal placeholder strings like "PCIe"/"path"/"sha"/"SC1"/"TC1")
  with NO Python code anywhere that reads or validates against them
  (grep confirmed zero .py references) -- they are DORMANT shape hints for
  SYS-15/16/24/34, not live schemas. Re-verify this dormancy rather than
  assuming a schema file's existence means it is enforced.
- dv_harness/connectivity.py (this session's own AMBA4 fabric-discovery
  effort already extended it): PROTOCOL_FINGERPRINTS now includes real
  AMBA4 sub-protocol signal sets (AHB/AHB-Lite/APB2/APB3/APB4/AXI3/AXI4/
  AXI4-Lite/AXI4-Stream), classify_amba_protocol() classifies from real RTL
  port-name evidence, determine_fabric_interface_roles() gives the
  dual FABRIC_SIDE_ROLE/EXTERNAL_ENDPOINT_ROLE perspective SYS-9's resource
  inventory and SYS-11's relationship classification need, and
  build_protocol_interface_count_table() / verify_matrix_self_check_identity()
  / cross_check_amba_table_against_matrix() are real per-protocol counting
  and identity-check primitives. verify_matrix_self_check_identity() proves
  sum(verified interfaces) == sum(VIP instances) + sum(exemptions) WITHIN
  one connectivity matrix -- confirm whether this covers SYS-10's mandate
  (duplicate VIP/agent detection ACROSS multiple subsystem environments,
  e.g. the same physical CPU AXI Master appearing in both a PCIe and a USB
  subsystem's own matrix) or only within-one-environment counting; it is
  very likely only the latter, making cross-subsystem dedup a genuine new
  layer that should CALL these primitives per-subsystem and reconcile
  their outputs, not re-derive the arithmetic.
- dv_harness/source_authority.py: a real, tested 9-level Source Authority
  Order with resolve_conflict()/escalate_conflict()/
  assert_both_evidence_paths_present(), already wired as the mechanism two
  other detectors (reference_pattern_audit.py, address_map_verifier.py)
  escalate disagreements through into the real question queue. SYS-19/22
  (system command.txt reuse, command collision detection) should escalate
  through this same mechanism rather than inventing a second conflict
  resolver.
- dv_harness/reference_pattern_audit.py: extract_register_writes() /
  discover_paired_blocks() / find_symmetry_asymmetries() / escalate_asymmetries()
  do real host-vs-DUT register-write-asymmetry analysis over reference
  pattern files (command.txt-adjacent, not full command.txt grammar
  parsing) and already escalate through source_authority.py. This is a
  partial, not full, answer to SYS-7's mandatory command.txt analysis --
  confirm exactly what it covers (register-write pairing) vs. what SYS-7
  additionally requires (sequence mapping, dependencies, ordering,
  interrupt waits, VIP sequence invocation, termination, loops).
- dv_harness/knowledge_center.py's KnowledgeCenterClient (add/search/
  deprecate/confirm/db_info, real cross-user/cross-project remote-exec-backed
  store) is the real, already-wired mechanism SYS-3/SYS-34 should read/write
  through -- never a parallel Knowledge Center.
- dv_harness/uvm_generator/address_map_verifier.py's verify_address_map()
  (3-source corroboration: decoder + BFM histogram + doc, escalates through
  source_authority.py) and dv_harness/uvm_generator/amba_fabric_generator.py's
  compute_address_regions() (overlap/gap/coverage algorithm) are real and
  directly relevant to SYS-28's ADDRESS MAP ANALYSIS -- reuse, do not
  recompute differently. dv_harness/phy_boundary.py, dv_harness/sys_regmap.py,
  dv_harness/init_seq.py exist for IP-level PHY-boundary/mode-bit-precondition
  concerns; confirm whether any of their primitives generalize to SYS-29's
  cross-subsystem clock/reset domain comparison or whether that is a
  genuinely new capability.
- dv_harness/memory_router.py / dv_harness/memory_vault.py: the 5-tier
  Memory system with per-protocol/per-subsystem scoping and
  promote_to_organizational()'s confirmation-count gate may relate to
  SYS-35 (subsystem version pinning) and SYS-14 (preserve subsystem
  ownership) -- confirm whether subsystem version/SHA pinning already has a
  natural home there or needs a new field.
- A prior fresh audit this session ("Generic multi-protocol DV Harness
  scope") and this session's own AMBA4 fabric-discovery workflow both found
  AMBA4/system-level composition genuinely PARTIALLY_WIRED at best (real
  mode dispatch + registry gate exist; real cross-subsystem topology
  discovery and dedup do not) -- re-verify this framing rather than
  assuming it.

Verdict format per SYS-N requirement, one of:
- WIRED_AND_FIRING: real, callable, evidenced end-to-end.
- PARTIALLY_WIRED: real code exists and covers part of the requirement --
  name exactly what's missing.
- DORMANT: real code/schema/policy exists but has no real caller for this
  purpose (e.g. the three workflow/*.schema.json files above).
- NEVER_BUILT: no real implementation exists, a genuine gap.
Cite real file:line or real command output for every verdict. Audit only --
do not modify any file in this phase.
`

phase('Audit')

const auditSelectionExistenceReadiness = agent(`${CONTEXT}

## Your scope: SYS-1, SYS-2, SYS-3, SYS-4 (user controls system composition, subsystem existence check mandatory, knowledge center check, subsystem readiness gate)

Check dv_harness/environment_mode_router.py's resolve_environment_mode() /
read_registered_subsystem_entries(), dv_harness/uvm_generator/create_environment.py's
SubsystemModeRequiredError / EnvironmentModeUnresolvedError,
tools/verification_flow/subsystem_environment_registration_gate.py, and
tools/real_env/system_level_validator.py against these 4 requirements
exactly. Specifically: does anything today DISCOVER and PRESENT a candidate
subsystem list with SUBSYSTEM / ENVIRONMENT PATH / KNOWLEDGE CENTER STATUS /
READINESS / PROTOCOL / VERSION-SHA columns (SYS-1's exact requirement)
before requiring selection, or does the real code only react to a caller's
already-made selection (>=2 subsystems -> SYSTEM_LEVEL_MODE) without ever
offering a discovery-and-present step? Does anything classify a subsystem
EXISTS_READY / EXISTS_PARTIAL / EXISTS_BLOCKED / EXISTS_UNKNOWN / NOT_FOUND
(SYS-2's exact enum), or does the real registry gate only pass/fail
(present-with-required-fields) without this 5-way classification? Does
dv_harness/knowledge_center.py's KnowledgeCenterClient get queried anywhere
in this path for SYS-3's fields (SUBSYSTEM_ID/PROTOCOL/ROLE/VERSION/GIT_SHA/
ENVIRONMENT_PATH/... /CONFIDENCE), or is it wired for other purposes only?
Does anything classify overall subsystem READINESS as READY/PARTIAL/
BLOCKED/UNKNOWN (SYS-4) from the multi-factor list the doc gives (RTL, UVM
env, VIP, build, tests, sequences, scoreboard, command.txt, clock/reset,
top hierarchy, config, PASS evidence, regression evidence), or does
qualification_state (SMOKE_QUALIFIED/REGRESSION_QUALIFIED/PRODUCTION_QUALIFIED)
answer a different, narrower question?

Report your verdict per the required format for SYS-1 through SYS-4
separately, with a concrete list of exactly which columns/enum values/
fields are missing from each real mechanism.`, {label: 'audit:selection-existence-readiness', phase: 'Audit'})

const auditPerSubsystemAnalysis = agent(`${CONTEXT}

## Your scope: SYS-5, SYS-6, SYS-7, SYS-8 (one analysis workflow per subsystem, verification architecture analysis, command.txt analysis mandatory, subsystem command contract)

SYS-5 requires an independent workflow per selected subsystem (parallel
allowed, no cross-contamination before each completes). SYS-6 requires
determining DUT hierarchy, UVM top/env, agents, VIPs, active/passive,
sequencers/drivers/monitors, scoreboards/reference models, coverage,
assertions, config objects, virtual interfaces, clock/reset, interrupts,
DMA, register model, address map, and build/run/regression/waveform flows
from SOURCE/CONFIG evidence, not documentation alone. SYS-7 requires
locating and analyzing the REAL command.txt per subsystem: syntax, grammar,
operations, init/config/traffic commands, sequence mapping, arguments,
dependencies, ordering, delays/waits, interrupt waits, register access, DMA
ops, VIP sequence invocation, expected responses, error handling,
termination, reset handling, loops -- identifying COMMAND PRODUCER/
CONSUMER/PARSER/DISPATCHER/TARGET VIP-SEQUENCE/DEPENDENCIES, without
modifying command.txt. SYS-8 requires representing each command.txt as a
SubsystemCommandContract schema (subsystem_id, source_command_file,
command_name, command_category, arguments, target_agent/vip/sequence,
required_resources, preconditions, postconditions, ordering_constraints,
clock_domain, reset_dependency, interrupt_dependency, address_dependency,
shared_resource_dependency, parallel_safe, serialization_required, evidence).

Check dv_harness/reference_pattern_audit.py's extract_register_writes()/
discover_paired_blocks()/find_symmetry_asymmetries() precisely: does it
parse command.txt GRAMMAR (commands, arguments, sequence mapping, ordering,
loops) or only extract register-write pairs for host/DUT symmetry checking
-- these are different things and the gap between them matters for SYS-7.
Check the .claude/skills/PROTOCOL_BUILDERS/*/SKILL.md and
dv_harness/uvm_generator/*.py for anything that already builds a
per-subsystem architecture-analysis report matching SYS-6's exact field
list (env_manifest.py's env_topology layer may be relevant -- check it).
Search the whole repo for any existing "command contract" or equivalent
schema (SubsystemCommandContract or a synonym) before concluding SYS-8 is
NEVER_BUILT.

Report your verdict per the required format for SYS-5 through SYS-8
separately.`, {label: 'audit:per-subsystem-analysis', phase: 'Audit'})

const auditResourceDedup = agent(`${CONTEXT}

## Your scope: SYS-9, SYS-10, SYS-11, SYS-12, SYS-13, SYS-14 (subsystem resource inventory, duplicate VIP/agent detection mandatory, resource relationship classification, active driver conflict rule, shared VIP promotion, preserve subsystem ownership)

Check dv_harness/connectivity.py's PROTOCOL_FINGERPRINTS,
classify_amba_protocol(), determine_fabric_interface_roles(),
build_protocol_interface_count_table(), verify_matrix_self_check_identity(),
and the T1-T4 bind-tier classifier against these 6 requirements. Specifically:
does ANY real code today enumerate a resource inventory (SYS-9's field list:
RESOURCE_ID/TYPE/PROTOCOL/ROLE/HIERARCHY/ACTIVE-PASSIVE/CONFIGURATION/
OWNER_SUBSYSTEM/SHAREABLE/EXCLUSIVE/CLOCK/RESET/ADDRESS DOMAIN/DEPENDENCIES/
EVIDENCE/CONFIDENCE) ACROSS multiple subsystem environments at once, or does
every existing primitive operate within ONE environment's own connectivity
matrix only? This distinction is exactly SYS-10's mandatory duplicate
detection: confirm concretely whether verify_matrix_self_check_identity()'s
sum(interfaces)=sum(VIP)+sum(exemptions) equation could catch a CPU AXI
Master VIP appearing independently in both a PCIe subsystem's matrix and a
USB subsystem's matrix (it almost certainly cannot, since it never sees two
matrices at once) -- name precisely what a cross-subsystem duplicate
detector would need to consume from each subsystem's real connectivity
artifacts. Check whether anything classifies SAME_PHYSICAL_RESOURCE /
SHARED_LOGICAL_RESOURCE / INDEPENDENT_RESOURCE / MONITOR_ONLY_DUPLICATE /
CONFIGURATION_CONFLICT / DRIVER_CONFLICT / UNKNOWN (SYS-11), whether
anything stops two active agents driving one physical interface
(SYS-12's ACTIVE DRIVER CONFLICT RULE -- connectivity.py's own bind-tier
gates are a plausible analog for WITHIN one environment; check whether they
generalize), and whether anything evaluates promoting a resource to
System-Level shared ownership vs. keeping it subsystem-local (SYS-13/14).

Report your verdict per the required format for SYS-9 through SYS-14
separately, and describe concretely what a cross-subsystem resource
inventory/dedup module would need as input from each subsystem (their real
connectivity matrices? env.manifest.json? something not yet extracted?).`, {label: 'audit:resource-dedup', phase: 'Audit'})

const auditRegistryMatrices = agent(`${CONTEXT}

## Your scope: SYS-15, SYS-16, SYS-17 (SYSTEM_RESOURCE_REGISTRY, subsystem integration matrix, VIP/agent deduplication matrix)

SYS-15 requires a registry (resource_id, resource_type, protocol,
physical_hierarchy, role, owner, consumer_subsystems, active_passive,
shared, exclusive, clock, reset, address_domain, source_environment,
source_config, conflict_status, reuse_decision, evidence, confidence) as
the authority for System-Level resource composition. SYS-16 requires a
mandatory table: Subsystem | Environment | command.txt | Readiness | VIPs |
Scoreboard | Shared Resources | Conflicts | Integration Status. SYS-17
requires a mandatory table: Resource | Subsystem A | Subsystem B | Physical
Interface | Relationship | Active Driver Conflict | Decision (REUSE_SHARED/
KEEP_INDEPENDENT/PASSIVE_ONLY/RECONFIGURE/MERGE_ACCESS_PATH/BLOCKED/
UNKNOWN) | System Owner.

Check .dv-harness/soc-composer/subsystem_environment_registry_template.json
(the shape: currently just {"subsystems": []} with 6 identity/qualification
fields, NOT SYS-15's 18-field resource-level registry -- confirm this
precisely; the SUBSYSTEM registry and the RESOURCE registry are different
things at different granularity) and .dv-harness/workflow/
system_level_composition.schema.json /
system_level_resource_contention.schema.json (confirm these are real
DORMANT example-value files with zero Python readers, as CONTEXT states --
re-verify with your own grep, do not trust the claim). Check whether
connectivity.py's existing table-rendering functions (the ones producing
the connectivity matrix / amba_interface_counts.md) could be parameterized
for SYS-16/17's exact column sets, or need new rendering functions built
alongside them.

Report your verdict per the required format for SYS-15 through SYS-17
separately.`, {label: 'audit:registry-matrices', phase: 'Audit'})

const auditArchitectureCommandIR = agent(`${CONTEXT}

## Your scope: SYS-18, SYS-19, SYS-20, SYS-21, SYS-22 (system-level architecture, system command.txt reuse-do-not-reinvent, backward compatibility, system command IR, command collision detection)

Check dv_harness/uvm_generator/soc_environment_composer.py's
compose_soc_environment() and _soc_tb_top() against SYS-18's preferred
logical structure (System Control / Shared SoC Resources / per-selected-
subsystem env). Check whether ANYTHING today derives a System-Level
command.txt from selected subsystem command CONTRACTS via routing/
namespacing (SYS-19/20 -- "reuse, do not reinvent", "route existing
subsystem commands through a System Command Router/adapter without forcing
wholesale rewrites") -- this almost certainly does not exist since SYS-8's
SubsystemCommandContract itself is likely not built yet (see the
per-subsystem-analysis audit's finding, cite it if available). Check
whether a System Command IR schema (system_command_id, source_subsystem,
source_command, command_category, target_resource/sequence, arguments,
dependencies, preconditions/postconditions, parallel_group,
serialization_group, shared_resource, priority, timeout,
completion_condition, evidence -- SYS-21) exists anywhere, and whether
dv_harness/source_authority.py's resolve_conflict()/escalate_conflict()
mechanism is reusable for SYS-22's command collision detection (duplicate
init/reset/clock setup, conflicting register writes, competing active VIP
traffic, ordering conflicts, shared-resource contention) or whether
collision detection needs new domain logic layered on top of that
mechanism's real escalation plumbing.

Report your verdict per the required format for SYS-18 through SYS-22
separately.`, {label: 'audit:architecture-command-ir', phase: 'Audit'})

const auditSchedulingScoreboardCrossCheck = agent(`${CONTEXT}

## Your scope: SYS-23, SYS-24, SYS-25, SYS-26, SYS-27 (initialization deduplication, shared resource scheduling, parallelism model, scoreboard integration, cross-subsystem checking)

Check dv_harness/uvm_generator/soc_environment_composer.py's
cross_subsystem_scenarios() / end_to_end_scoreboard() / system_coverage()
(confirm they still raise NotImplementedError ON PURPOSE, per CONTEXT, and
re-read their real docstrings for exactly why) against SYS-26 (default to
REUSE of existing subsystem scoreboards under a System Scoreboard/
Correlation Layer, never a monolithic replacement) and SYS-27 (cross-
subsystem flows like PCIe->DDR->USB, CSI2->Memory->DSI, only checks
supported by actual SoC architecture). Check .dv-harness/workflow/
system_level_resource_contention.schema.json's shape (shared_resources,
scenarios with arbitration_or_contention_policy, contention_testcase_ids)
against SYS-24's shared resource scheduling requirement -- confirm it is
DORMANT (no Python reader) as CONTEXT states. Check whether anything
classifies commands SYSTEM_ONCE/SUBSYSTEM_ONCE/SCENARIO_ONCE/REPEATABLE/
SHARED_RESOURCE_COMMAND (SYS-23) or relationships PARALLEL_SAFE/
SERIALIZE_RESOURCE/ORDER_DEPENDENT/INTERRUPT_DEPENDENT/
CLOCK_DOMAIN_DEPENDENT/UNKNOWN (SYS-25).

Report your verdict per the required format for SYS-23 through SYS-27
separately, and explicitly flag: is closing SYS-26/27 for real (writing
actual cross-subsystem scoreboard/check CONTENT) in scope for THIS
discovery/planning/reporting-only effort, or does it require real
protocol-behavior content that only SYS-40 (post-approval implementation)
may produce? (It is the latter -- state this clearly in your verdict so the
Build phase does not accidentally cross the line.)`, {label: 'audit:scheduling-scoreboard-crosscheck', phase: 'Audit'})

const auditAddressClockScenarioFailure = agent(`${CONTEXT}

## Your scope: SYS-28, SYS-29, SYS-30, SYS-31, SYS-32 (address map analysis, clock/reset integration, system-level scenario model, subsystem failure isolation, system failure triage)

Check dv_harness/uvm_generator/address_map_verifier.py's verify_address_map()
(3-source corroboration, escalates through source_authority.py) and
dv_harness/uvm_generator/amba_fabric_generator.py's compute_address_regions()
against SYS-28's exact requirement (register/memory/DMA/APB/AXI ranges,
shared memory, interrupt mapping; ADDRESS_OVERLAP_VALID/
ADDRESS_OVERLAP_CONFLICT/SHARED_MEMORY/UNKNOWN) -- confirm direct
reusability or name the gap (these tools operate on ONE subsystem/fabric's
own address space; SYS-28 is about reconciling MULTIPLE subsystems' address
domains against each other). Check dv_harness/phy_boundary.py,
dv_harness/sys_regmap.py, dv_harness/init_seq.py for anything that compares
CLOCK SOURCE/FREQUENCY or RESET SOURCE/POLARITY/SEQUENCING across more than
one subsystem (SYS-29) -- these tools are almost certainly single-subsystem/
single-PHY-boundary scoped; confirm. Check whether anything preserves
SYSTEM SCENARIO/SUBSYSTEM/COMMAND/VIP-AGENT/RESOURCE/UVM_ERROR/LOG/
WAVEFORM/ROOT-CAUSE HYPOTHESIS/CONFIDENCE as distinct dimensions on a
failure record rather than collapsing to one generic "System failure"
(SYS-31), and whether the existing L5 failure-triage mechanism (see
CLAUDE.md's memory/debug-flow sections, dv_harness.inference module) can be
reused for SYS-32's local-vs-cross-subsystem-vs-genuine-integration-bug
classification, or needs a system-level wrapper.

Report your verdict per the required format for SYS-28 through SYS-32
separately.`, {label: 'audit:address-clock-scenario-failure', phase: 'Audit'})

const auditRegressionKcVersionReadiness = agent(`${CONTEXT}

## Your scope: SYS-33, SYS-34, SYS-35, SYS-36, SYS-37, SYS-38 (system regression, knowledge center update, subsystem version pinning, change impact, system environment readiness, required Phase-1 output)

Check whether anything builds a System Regression PLAN (not run -- SYS-33
is Phase-1 planning, per SYS-40's own placement of actual regression
execution in Phase-2) from known-good subsystem tests, selected command
sequences, cross-subsystem scenarios, shared-resource contention, boot/
config, interrupt, DMA, stress/concurrency -- never a blind concatenation
of all subsystem regressions. Check dv_harness/knowledge_center.py's
add()/search()/confirm() against SYS-34's exact field list (System
composition, subsystem versions/SHAs, paths, shared-resource decisions,
dedup decisions, command mappings, System command.txt [a PLAN reference
only in Phase-1], limitations, PASS/regression evidence, architecture
decisions) -- is this a natural fit or does it need a new record kind?
Check whether subsystem_environment_registry's real release_sha field
(confirmed real in the registration gate) already satisfies SYS-35's
version-pinning requirement, and whether dv_harness's existing
verification-change-impact mechanism (.dv-harness/change_impact.csv,
requirements.csv) generalizes to SYS-36's "subsystem Git change ->
verification-change-impact -> affected System resources/commands/
scenarios/scoreboards -> targeted System regression" flow. Check
tools/real_env/system_level_validator.py and .dv-harness/system-level/
composition_policy.json against SYS-37's READY/PARTIAL/BLOCKED/UNKNOWN
system-environment-readiness derivation. Finally, for SYS-38's REQUIRED
PHASE-1 OUTPUT (the exact 22-item ordered list): confirm no existing report
assembler in this repo already produces this exact structure end to end
(it almost certainly does not, since most of its 22 inputs are themselves
not yet built per the other audit groups' findings) -- name what a report
ASSEMBLY module (composing the OTHER build steps' outputs into one ordered
document, stopping per SYS-39) would need to import.

Report your verdict per the required format for SYS-33 through SYS-38
separately.`, {label: 'audit:regression-kc-version-readiness', phase: 'Audit'})

const results = await parallel([
  () => auditSelectionExistenceReadiness, () => auditPerSubsystemAnalysis, () => auditResourceDedup,
  () => auditRegistryMatrices, () => auditArchitectureCommandIR, () => auditSchedulingScoreboardCrossCheck,
  () => auditAddressClockScenarioFailure, () => auditRegressionKcVersionReadiness,
])
const [selectionExistenceReadinessR, perSubsystemAnalysisR, resourceDedupR, registryMatricesR,
  architectureCommandIrR, schedulingScoreboardCrossCheckR, addressClockScenarioFailureR,
  regressionKcVersionReadinessR] = results

phase('Build')

const buildOrder = [
  ['SYS-1..4: subsystem discovery-and-present list (SUBSYSTEM/PATH/KC STATUS/READINESS/PROTOCOL/SHA) + 5-way EXISTS_* classification + READY/PARTIAL/BLOCKED/UNKNOWN readiness gate, extending environment_mode_router.py + knowledge_center.py + system_level_validator.py', selectionExistenceReadinessR],
  ['SYS-5..8: per-subsystem architecture-analysis report (SYS-6 field list) + command.txt grammar/dependency/ordering analysis extending reference_pattern_audit.py (never modifying command.txt) + SubsystemCommandContract schema', perSubsystemAnalysisR],
  ['SYS-9..14: cross-subsystem resource inventory + duplicate VIP/agent detection + relationship classification + active-driver-conflict rule + shared-VIP-promotion evaluation, extending connectivity.py primitives (never re-deriving its arithmetic)', resourceDedupR],
  ['SYS-15..17: SYSTEM_RESOURCE_REGISTRY (18-field, resource-granularity, distinct from the existing subsystem-granularity registry) + SUBSYSTEM INTEGRATION MATRIX + VIP/AGENT DEDUPLICATION MATRIX renderers, extending connectivity.py table rendering', registryMatricesR],
  ['SYS-18..22: system architecture report + System command.txt PLAN (routing/namespacing plan only, never a real emitted command.txt) + System Command IR schema + command-collision detection extending source_authority.py escalation', architectureCommandIrR],
  ['SYS-23..27: initialization-dedup classification + shared-resource-scheduling plan + parallelism-relationship classification + scoreboard-integration PLAN (reuse-plan only, never real scoreboard content) + cross-subsystem-checking PLAN, referencing the intentional NotImplementedError boundary in soc_environment_composer.py without crossing it', schedulingScoreboardCrossCheckR],
  ['SYS-28..32: cross-subsystem address-map reconciliation (reuse address_map_verifier.py/amba_fabric_generator.py) + cross-subsystem clock/reset comparison + scenario-model PLAN + failure-isolation record shape + failure-triage classification extending existing L5 triage', addressClockScenarioFailureR],
  ['SYS-33..38: system regression PLAN (never executed) + Knowledge Center update extending knowledge_center.py + version-pinning via release_sha + change-impact extension + system-readiness derivation + the SYS-38 22-item report assembler that composes the output of every prior step and STOPS per SYS-39', regressionKcVersionReadinessR],
]

log('Audit phase complete. Building the discovery/analysis/planning/reporting machinery sequentially (dependency order: selection/existence/readiness -> per-subsystem analysis -> resource dedup -> registry/matrices -> architecture/command-IR -> scheduling/scoreboard-plan -> address/clock/scenario/failure -> regression/KC/readiness/report-assembly), reusing real existing code at every step, never generating real System-Level UVM/command.txt content and never modifying a real generated environment outside the SYS-40 human-approval gate.')

const buildResults = []
for (const [name, report] of buildOrder) {
  const buildResult = await agent(`Working directory: D:/DV/Task/DV_Agent_Harness_L5/v50

## Background

${CONTEXT}

This is a sequential build pass, step **${name}**, installing System-Level
Verification Integration discovery/analysis/planning/reporting machinery.
Prior steps in this same sequence may have already added real code you
should build on (check git log/git diff for this session's own recent
commits under this same effort before assuming a prerequisite is missing).

NOTE: other agents/workflows may be concurrently active in this repo.
connectivity.py, CLAUDE.md, source_authority.py, knowledge_center.py, and
soc_environment_composer.py in particular may be touched by concurrent
work. Check git status/git diff on any file BEFORE touching it, and use the
hand-scoped patch technique (git diff > patch, trim to your hunk, git apply
--cached --check then --cached) for EVERY file, never a broad git add.

Its real, current audit finding for this scope (read carefully, this is
real evidence gathered just now):

${report}

## Your task

1. If the audit found this already WIRED_AND_FIRING: do nothing, just
   re-confirm the cited evidence.
2. Otherwise build it for real, reusing existing code (environment_mode_router.py,
   create_environment.py, soc_environment_composer.py, connectivity.py,
   knowledge_center.py, source_authority.py, reference_pattern_audit.py,
   address_map_verifier.py, amba_fabric_generator.py, phy_boundary.py, per
   the audit's own concrete recommendation). Prefer extending an existing
   module directly over a new parallel module UNLESS the audit found the
   capability is genuinely structurally new (e.g. a cross-subsystem
   resource registry operating on MULTIPLE subsystems' evidence at once
   has no natural single-subsystem home) -- in that case a new, clearly-
   scoped module under dv_harness/ or dv_harness/uvm_generator/ that
   IMPORTS and composes the real existing primitives is correct, not a
   copy of their logic.
3. HARD CONSTRAINT, non-negotiable, this is the single most important rule
   in this entire build: NEVER generate real System-Level UVM source, a
   real System command.txt, a real System Virtual Sequencer, or any real
   command routing/adapter as part of this build. NEVER write real
   cross-subsystem scoreboard/checker CONTENT into soc_environment_composer.py's
   cross_subsystem_scenarios()/end_to_end_scoreboard()/system_coverage()
   functions or anywhere else -- those remain NotImplementedError (or a
   planning-only descriptor schema ABOUT what they would need) through
   this entire effort; filling them with real protocol-behavior content is
   SYS-40 territory, gated on a separate explicit human approval this
   workflow does not obtain. A synthetic fixture (fake registry entries, a
   fake pair of command.txt files, a fake address map, a fake connectivity
   matrix) used ONLY inside your own new test file is fine and expected;
   writing real System-Level UVM/command.txt content anywhere outside a
   throwaway test fixture must not happen. This step builds discovery/
   analysis/planning/reporting tooling ONLY, per the master prompt's own
   SYS-39/SYS-40 gate.
4. Write real tests (synthetic multi-subsystem registry/command.txt/
   address-map fixtures, at minimum two subsystems with at least one
   genuine ambiguous/conflicting case -- e.g. two subsystems both claiming
   an active CPU AXI Master, or two address ranges that overlap) proving
   your piece actually works. An untested happy-path-only implementation is
   not real coverage for a dedup/conflict-detection mechanism -- this
   project's own hard-won lesson from the AMBA4 effort earlier this session.
5. Run the full relevant test suite for whatever you touched and confirm
   pass.
6. Commit your change for real with a clear, scoped commit.

Write a report to .work/gap-close-system-level-${name.replace(/[^a-zA-Z0-9]+/g, '-').toLowerCase().slice(0, 40)}-report.md.
Report DONE (with what changed) / NO_ACTION_NEEDED / NEEDS_SEPARATE_EFFORT /
BLOCKED, with a one-line test summary if you made a change.`, {label: `build:${name}`, phase: 'Build', model: 'claude-opus-5'})
  buildResults.push([name, buildResult])
  log(`Build step done: ${name}`)
}

phase('Review')

const review = await agent(`${CONTEXT}

Independently review this "install System-Level Verification Integration
discovery/analysis/planning/reporting machinery (SYS-1..38), reuse-first,
Phase-1-only" effort. Do not accept any report's own claim without
independent re-verification -- run real commands yourself.

Read every audit report and every build-step report in full first (search
.work/ for files matching gap-close-system-level-*-report.md).

Raw returned results, for cross-reference:

### Audits
${[
  ['selection-existence-readiness', selectionExistenceReadinessR], ['per-subsystem-analysis', perSubsystemAnalysisR],
  ['resource-dedup', resourceDedupR], ['registry-matrices', registryMatricesR],
  ['architecture-command-ir', architectureCommandIrR], ['scheduling-scoreboard-crosscheck', schedulingScoreboardCrossCheckR],
  ['address-clock-scenario-failure', addressClockScenarioFailureR], ['regression-kc-version-readiness', regressionKcVersionReadinessR],
].map(([n, r]) => `#### ${n}\n${r}`).join('\n\n')}

### Build steps
${buildResults.map(([name, result]) => `#### ${name}\n${result}`).join('\n\n')}

Verify independently:
1. For every build step reporting DONE: did it actually work (run its new
   test yourself), and does its test genuinely cover a cross-subsystem
   ambiguous/conflicting case, not just a clean happy path over one
   subsystem?
2. THE MOST IMPORTANT CHECK, more important than anything else in this
   review: grep the entire diff/commit history this pass produced for (a)
   any real System-Level UVM source file, (b) any real System command.txt
   content, (c) any real content written into
   cross_subsystem_scenarios()/end_to_end_scoreboard()/system_coverage()
   other than a still-raising NotImplementedError or a planning/descriptor
   schema ABOUT what they need, (d) any modification to a real GENERATED
   subsystem environment outside its own SUBSYSTEM_MODE flow. This effort's
   hard constraint was discovery/analysis/planning/reporting ONLY per
   SYS-39/40 -- confirm zero violations of that boundary, and flag any as
   CRITICAL if found, with the exact file/commit.
3. Confirm no parallel/duplicate mechanism was built where connectivity.py's
   real fingerprints/tier classifier/matrix machinery, source_authority.py's
   real conflict resolver, or knowledge_center.py's real client should have
   been reused instead -- and confirm no SECOND SYSTEM_RESOURCE_REGISTRY-
   shaped file was created alongside the existing subsystem_environment_registry
   template without a clearly documented reason they are different
   granularities.
4. Actually exercise the new discovery/dedup/planning pipeline end-to-end
   yourself against a real or synthetic multi-subsystem fixture (build one
   if none exists, e.g. two toy subsystems sharing one CPU AXI Master and
   one overlapping address range) and confirm it produces something
   resembling SYS-16's integration matrix, SYS-17's dedup matrix, and a
   SYS-38-shaped Phase-1 report ending in the exact SYS-39 stop-condition
   text.
5. Run the full project test suite (python -m pytest dv_harness_tests/ -q)
   and report the real pass/fail count.
6. Check git hygiene across all commits this pass made.

Report a clear verdict per SYS sub-area (GENUINELY_CLOSED / STILL_GAP /
CORRECTLY_DEFERRED-per-SYS-39/40) plus an overall verdict (APPROVED /
NEEDS_FIX), with concrete evidence-cited findings. Be exhaustive about the
Phase-1/Phase-2 boundary check specifically -- that is this effort's single
most important safety constraint.`, {label: 'review', phase: 'Review', model: 'claude-opus-5'})

return {
  audits: {
    selectionExistenceReadinessR, perSubsystemAnalysisR, resourceDedupR, registryMatricesR,
    architectureCommandIrR, schedulingScoreboardCrossCheckR, addressClockScenarioFailureR,
    regressionKcVersionReadinessR,
  },
  buildResults: Object.fromEntries(buildResults),
  review,
}
