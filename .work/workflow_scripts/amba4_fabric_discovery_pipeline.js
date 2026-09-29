export const meta = {
  name: 'amba4-fabric-discovery-pipeline',
  description: 'Install AMBA4 SoC bus-fabric discovery + VIP bind planning (AMBA-1..29) as real, reuse-first tooling extending connectivity.py -- discovery/planning/reporting ONLY, per the master prompt\'s own AMBA-30/31 mandatory human-review gate before any real UVM/bind implementation',
  phases: [
    { title: 'Audit', detail: '7 parallel audits of AMBA-1..29 against real code' },
    { title: 'Build', detail: 'sequential, reuse-first build of the discovery/planning/reporting machinery' },
    { title: 'Review', detail: 'independent re-verification incl. the AMBA-30 stop-before-implementation gate' },
  ],
}

const CONTEXT = `
This implements ONLY AMBA-1 through AMBA-29 (discovery, tracing, planning,
reporting) from the "FIRST-CLASS DOMAIN EXTENSION -- AMBA4 SoC BUS FABRIC
DISCOVERY + VIP BIND PLANNING" section (AMBA-1..32) at the end of
D:/DV/Task/DV_Agent_Harness_L5/DV_Agent_Harness_L5_ULTIMATE_COMPLETE_Master_Prompt_AMBA4_CCE_Research.md
(read it yourself for your scope's exact wording -- lines 3634-4271).

The document's OWN gate is explicit and non-negotiable:
- AMBA-30 (MANDATORY REVIEW GATE): after discovery, STOP and report; do not
  generate/modify production UVM before a human reviews the plan.
- AMBA-31 (IMPLEMENTATION AFTER EXPLICIT APPROVAL): only after a human
  approves does AMBA_PORT_REGISTRY -> VIP config -> binds -> UVM ->
  build/verify/run happen.
This workflow's scope is bounded to building the DISCOVERY/TRACING/PLANNING/
REPORTING machinery only. NEVER write a real bind statement into any real or
synthetic generated UVM environment. NEVER auto-apply anything downstream of
AMBA_PORT_REGISTRY. A synthetic RTL fixture for testing is fine; a real bind
statement anywhere outside a throwaway test fixture is not.

REUSE-FIRST is this document's own repeated instruction (AMBA-0 preamble:
"SEARCH EXISTING L5 FIRST before adding new Agent/Skill/Node/state/schema"),
and this project has an extremely strong, independently-verified history
this session of exactly the opposite failure mode (parallel tiered-confidence
classifiers, duplicate memory mechanisms) being caught as a real defect.
Real, already-confirmed overlap points (re-verify with your own grep/read,
do not just cite this list):

- dv_harness/connectivity.py: BindTier (T1_ALREADY_DECIDED..T4_UNDECIDABLE),
  classify_bind_tier(), PROTOCOL_FINGERPRINTS (signal-set based protocol ID
  -- currently covers USB/PCIe/CSI-2/etc., NOT yet AHB/AHB-Lite/APB/APB3/
  APB4/AXI3/AXI4/AXI4-Lite/ACE-Lite/AXI4-Stream -- AMBA-4's exact signal
  lists, e.g. HADDR/HTRANS/HWRITE.../PADDR/PSEL.../AW-W-B-AR-R channels/
  TVALID/TREADY..., are a real, concrete extension target here, not a new
  classifier), capture_dut_instance_tree(), grep_existing_binds(),
  verify_self_check_identity() (the Sum(interfaces)=Sum(VIP)+Sum(exemptions)
  equation -- AMBA-6's port-counting table is the same shape), the checker/
  scoreboard table generator with REQUIRED_HUMAN_INPUT sentinel, and the
  per-row lock/diff confirmation store.
- dv_harness/uvm_generator/amba_fabric_generator.py (422 lines, real, tested
  -- dv_harness_tests/test_amba_fabric_generator.py): already computes REAL
  algorithms for address-decode overlap/gap/full-coverage check
  (compute_address_regions), an ID-width formula (compute_id_width), and
  per-pair scoreboard-matrix resolution (build_scoreboard_matrix) -- and
  emits SV skeletons from an ALREADY-KNOWN topology. It does NOT discover
  that topology from real RTL connectivity -- it takes masters/slaves/
  connectivity as INPUT PARAMETERS. This is the exact missing half AMBA-1..29
  fills: AMBA-1..29 is upstream discovery (real RTL -> discovered topology),
  amba_fabric_generator.py is downstream generation (known topology -> SV
  skeleton). Reuse its address-decode/ID-width/scoreboard-matrix algorithms
  directly for AMBA-23/AMBA-25 -- do not recompute them differently.
- tools/verification_flow/fabric_topology_completeness_gate.py: a real,
  already-wired validator expecting a topology JSON with top-level
  masters/slaves/scoreboard_matrix/address_map keys (read it yourself for
  the exact shape). AMBA-16/18/19/22's output artifacts should be schema-
  COMPATIBLE with this validator, not a competing new schema.
- dv_harness/protocol_capability.py: already registers a real
  "AMBA4_MULTI_MASTER_MULTI_SLAVE" capability wired to amba_fabric_generator
  + tools/generate_amba_fabric_environment.py.
- dv_harness/uvm_generator/address_map_verifier.py: real 3-source address-
  map corroboration (decoder + BFM histogram + doc), directly relevant to
  AMBA-23's ADDRESS MAP CROSS-CHECK.
- dv_harness/connectivity_check.py (built 2026-09-04, TODAY): the real
  STANDING runner wiring connectivity.py's 3 gates into 'just
  connectivity-check', triggered on RTL change -- the natural place an
  AMBA-specific fabric-discovery pass should plug into, not a separate
  standalone script nothing calls.
- .claude/skills/CORE/branch-mapper/SKILL.md's "AMBA-as-Primary-DUT
  Master/Slave Redefinition" section (2026-09-01) is EXPLICITLY marked
  "UNTESTED, awaiting a real AMBA-fabric pilot project to validate" --
  AMBA-26 (L5 BRANCH MAPPING) is very likely meant to finally close this
  exact placeholder. Confirm and update that skill file's status once real,
  tested code exists, rather than leaving a now-stale "untested" label.
- A prior fresh audit this session ("Generic multi-protocol DV Harness
  scope") found AMBA4 specifically UNTESTED_PLACEHOLDER (doc-level guidance
  only, never exercised against a real AMBA4 DUT) -- this workflow is very
  likely the mechanism that closes that exact gap for real. Re-verify this
  framing rather than assuming it.

Verdict format per AMBA-N requirement, one of:
- WIRED_AND_FIRING: real, callable, evidenced end-to-end.
- PARTIALLY_WIRED: real code exists and covers part of the requirement --
  name exactly what's missing.
- DORMANT: real code exists but has no real caller for this purpose.
- NEVER_BUILT: no real implementation exists, a genuine gap.
Cite real file:line or real command output for every verdict. Audit only --
do not modify any file in this phase.
`

phase('Audit')

const auditFabricLocateEnumerateClassify = agent(`${CONTEXT}

## Your scope: AMBA-1, AMBA-2, AMBA-3, AMBA-4 (required input, locate fabric instance, enumerate interfaces, protocol classification from RTL evidence)

Check connectivity.py's capture_dut_instance_tree() and PROTOCOL_FINGERPRINTS against these 4 requirements exactly. Specifically: does PROTOCOL_FINGERPRINTS (or anything else) currently define signal sets for AHB/AHB-Lite/APB/APB3/APB4/AXI3/AXI4/AXI4-Lite/ACE-Lite/AXI4-Stream (AMBA-4's exact evidence lists: HADDR/HTRANS/HWRITE/HSIZE/HBURST/HPROT/HWDATA/HRDATA/HREADY/HREADYOUT/HRESP/HSEL/HMASTER/HMASTLOCK/HSPLIT for AHB; PADDR/PSEL/PENABLE/PWRITE/PWDATA/PRDATA base + PREADY/PSLVERR for APB3 + PSTRB/PPROT for APB4; AW/W/B/AR/R channels + WID for AXI3-vs-AXI4; reduced subset for AXI4-Lite; AXI+coherency signals for ACE-Lite; TVALID/TREADY/TDATA/TSTRB/TKEEP/TLAST/TID/TDEST/TUSER for AXI4-Stream)? Confirm honestly -- this is very likely NEVER_BUILT (USB/PCIe/CSI-2 fingerprints exist, AMBA sub-protocol fingerprints almost certainly don't), but verify rather than assume.

Report your verdict per the required format for AMBA-1/2/3/4 separately, with a concrete list of exactly which AMBA sub-protocol signal sets are missing from PROTOCOL_FINGERPRINTS.`, {label: 'audit:locate-enumerate-classify', phase: 'Audit'})

const auditRoleCounting = agent(`${CONTEXT}

## Your scope: AMBA-5, AMBA-6 (dual-perspective master/slave role, interface counting table)

AMBA-5 requires BOTH FABRIC_SIDE_ROLE and EXTERNAL_ENDPOINT_ROLE reported per interface, never just "Master"/"Slave" alone -- this session already established (for the USB/generic case) that role must be determined from port DIRECTION, never from naming. AMBA-6 requires a mandatory per-protocol Slave/Master/Total interface-count table before any endpoint tracing, plus TOTAL FABRIC SLAVE/MASTER/AMBA PORTS -- structurally the same shape as connectivity.py's verify_self_check_identity() count equation.

Check: does connectivity.py (or anything) currently determine ANY interface's role from port direction with a dual fabric-side/endpoint-side distinction? Does verify_self_check_identity() generalize to an arbitrary per-protocol table, or is it USB/single-DUT-shaped only? Report your verdict per the required format for AMBA-5 and AMBA-6 separately, and describe concretely what generalizing verify_self_check_identity() into AMBA-6's table would require.`, {label: 'audit:role-counting', phase: 'Audit'})

const auditEndpointTracing = agent(`${CONTEXT}

## Your scope: AMBA-7 through AMBA-14 (fabric-port endpoint tracing: wrappers/muxes/arbiters/bridges, VIP placement priority P1-P4, slave-to-master and master-to-slave tracing, protocol bridge rule, multiple-source/destination handling, 10-state termination status enum)

This is very likely the single largest genuinely NEW gap -- a graph-traversal algorithm that follows a fabric port's real RTL connectivity THROUGH wrappers/muxes/arbiters/decoders/bridges/CDC blocks/register slices/width or ID or protocol converters/nested interconnect to find the real initiating master or destination slave, handling MULTIPLE_SOURCE/MULTIPLE_DESTINATION/PROTOCOL_BRIDGE_FOUND/TRACE_BLOCKED/AMBIGUOUS as distinct terminal states (AMBA-14's exact 10-value enum). Check: does anything in dv_harness/ or tools/ do multi-hop RTL connectivity tracing THROUGH intermediate structural elements (not just direct port-to-port matching)? verible_parser.py's AST output and slang-based parsing (connectivity.py's capture_dut_instance_tree) may supply the raw connectivity graph this needs -- confirm whether a traversal algorithm consuming that graph exists anywhere, or whether only single-hop matching exists today.

Report your verdict per the required format for AMBA-7 through AMBA-14, grouped (tracing mechanism / VIP placement priority / bridge handling / multi-source-destination / termination enum), and describe concretely what a new traversal module would need to consume (verible AST? a slang connectivity graph? something not yet extracted at all?).`, {label: 'audit:endpoint-tracing', phase: 'Audit'})

const auditBindValidationOutputs = agent(`${CONTEXT}

## Your scope: AMBA-15 through AMBA-20 (VIP bind validation 13-point checklist, fabric-port-to-VIP-bind matrix, unresolved-port table, topology summary, topology tree, VIP instance plan)

Check connectivity.py's existing checker/scoreboard table generator and per-row lock/diff confirmation store against these 6 required output artifacts. AMBA-15's 13-point validation checklist (hierarchy exists, AMBA signals exist, interface complete, protocol identified, roles identified, clock known, reset known, address/data/ID widths known, USER widths known, parameterization known, bind/observe accessibility) overlaps heavily with connectivity.py's existing bind-tier evidence requirements -- confirm how much is already covered vs. AMBA-specific (width/parameterization fields especially). AMBA-16's matrix and AMBA-19's topology tree are new OUTPUT FORMATS even if the underlying tier/confidence data is reused -- check whether connectivity.py's existing table-rendering code can be parameterized for these new column sets or needs new rendering functions.

Report your verdict per the required format for AMBA-15 through AMBA-20 separately.`, {label: 'audit:bind-validation-outputs', phase: 'Audit'})

const auditScoreboardRegistry = agent(`${CONTEXT}

## Your scope: AMBA-21, AMBA-22 (scoreboard reference environment analysis, AMBA_PORT_REGISTRY)

AMBA-21 requires inspecting a user-supplied UVM scoreboard/reference environment (transaction classes, analysis ports/exports, predictors, ordering/outstanding-transaction assumptions) WITHOUT modifying it during discovery, then mapping each proposed VIP monitor to the correct scoreboard ingress. AMBA-22 requires drafting a registry (port_id/fabric_port/protocol/fabric_role/endpoint_role/endpoint_hierarchy/vip_bind_hierarchy/vip_mode/clock/reset/address_width/data_width/id_width/user_widths/scoreboard_channel/trace_status/readiness/confidence/source_evidence) to drive later VIP/UVM construction.

Check: does anything in dv_harness/ (generator.py's scoreboard-wiring analysis, address_map_verifier.py, connectivity.py's checker/scoreboard table) already do read-only UVM-scoreboard-structure inspection, or would this be new? Check whether amba_fabric_generator.py's build_scoreboard_matrix() output shape is directly reusable as (or convertible to) AMBA_PORT_REGISTRY rows, or whether it's a structurally different thing (topology-known generation input vs. discovery-derived registry).

Report your verdict per the required format for AMBA-21 and AMBA-22 separately.`, {label: 'audit:scoreboard-registry', phase: 'Audit'})

const auditAddressClockScaling = agent(`${CONTEXT}

## Your scope: AMBA-23, AMBA-24, AMBA-25 (address map cross-check, clock/reset domain analysis, scoreboard+port scaling)

Check dv_harness/uvm_generator/address_map_verifier.py's real verify_address_map() (3-source corroboration: decoder + BFM histogram + doc) against AMBA-23's requirement (RTL decoder / fabric config / address-map package / CSR defs / firmware headers / memory-map docs as SUPPORTING evidence only, physical RTL connectivity remains mandatory) -- confirm this is directly reusable, or name the gap. Check amba_fabric_generator.py's compute_address_regions() (real overlap/gap/coverage algorithm) against AMBA-23 too. For AMBA-24 (clock hierarchy/frequency, reset hierarchy/polarity/sync-async, CDC/bridge path, fabric-side-vs-endpoint-side-of-CDC determination): check whether connectivity.py's zero-time connectivity gate (clock toggle/reset deassert checking) already captures any of this, or whether static CDC/clock-domain analysis is a wholly separate, unaddressed capability. For AMBA-25 (variable fabric size, mixed protocols, registry-driven per-port scoreboard architecture): check amba_fabric_generator.py's build_scoreboard_matrix() for direct reuse.

Report your verdict per the required format for AMBA-23, AMBA-24, AMBA-25 separately.`, {label: 'audit:address-clock-scaling', phase: 'Audit'})

const auditBranchMappingConfidenceReadiness = agent(`${CONTEXT}

## Your scope: AMBA-26, AMBA-27, AMBA-28, AMBA-29 (L5 branch mapping, evidence+confidence rule, discovery report order, per-port readiness)

Check .claude/skills/CORE/branch-mapper/SKILL.md's "AMBA-as-Primary-DUT Master/Slave Redefinition" section (2026-09-01, explicitly marked UNTESTED placeholder) against AMBA-26's exact branch-a1..N (fabric-facing physical interfaces) / branch-b1..M (VIP endpoint/scenario branches) / branch_fw mapping -- confirm whether AMBA-26 is a formalization of that exact placeholder or something new, and whether the placeholder's own content already matches AMBA-26's rule or needs correction. Check connectivity.py's HIGH/MEDIUM/LOW/UNKNOWN-shaped confidence handling against AMBA-27's exact 4-level scheme (HIGH=direct RTL connectivity, MEDIUM=strong structural with one unresolved abstraction, LOW=incomplete/naming-heavy, UNKNOWN=cannot prove) -- these look very close to connectivity.py's own T1-T4 tiers re-expressed; confirm the mapping precisely. For AMBA-28 (exact 17-item discovery report order) and AMBA-29 (per-port READY/PARTIAL/BLOCKED/UNKNOWN readiness rolling into overall readiness): check whether connectivity.py's existing report-rendering functions could be reordered/extended into this exact 17-item structure, or need a new report-assembly function.

Report your verdict per the required format for AMBA-26 through AMBA-29 separately, and explicitly flag whether branch-mapper/SKILL.md's "UNTESTED" status can honestly be updated once real code exists.`, {label: 'audit:branch-mapping-confidence-readiness', phase: 'Audit'})

const auditGenericProtocolCrossCheck = agent(`${CONTEXT}

## Your scope: cross-check against the prior "Generic multi-protocol DV Harness scope" audit's AMBA4 finding

Earlier this session, a fresh re-audit of DV Agent Harness L5's generic (non-USB) protocol readiness found AMBA4 specifically classified UNTESTED_PLACEHOLDER: "only doc-level guidance exists [branch-mapper/SKILL.md's AMBA-as-Primary-DUT section], never exercised against a real AMBA4 DUT." Independently re-verify this finding is still accurate as of right now (grep/read for real, don't trust the citation) -- has anything changed since then (e.g. amba_fabric_generator.py, protocol_capability.py's AMBA4_MULTI_MASTER_MULTI_SLAVE registration, connectivity_check.py, all of which are real and already exist)? Give an honest, current, evidence-based verdict on whether AMBA4 support today is genuinely still UNTESTED_PLACEHOLDER, or whether it should be reclassified as PARTIALLY_GENERIC given amba_fabric_generator.py's real (if generation-only, not discovery) capability. This cross-check matters because the AMBA-1..29 discovery machinery this workflow is about to build is specifically what would close the remaining gap between "PARTIALLY_GENERIC (generation exists)" and "GENERIC_READY (discovery + generation both exist and have been exercised against something real)".

Report a clear verdict with concrete evidence, not a restatement of the old finding.`, {label: 'audit:generic-protocol-cross-check', phase: 'Audit'})

const results = await parallel([
  () => auditFabricLocateEnumerateClassify, () => auditRoleCounting, () => auditEndpointTracing,
  () => auditBindValidationOutputs, () => auditScoreboardRegistry, () => auditAddressClockScaling,
  () => auditBranchMappingConfidenceReadiness, () => auditGenericProtocolCrossCheck,
])
const [locateEnumerateClassifyR, roleCountingR, endpointTracingR, bindValidationOutputsR,
  scoreboardRegistryR, addressClockScalingR, branchMappingConfidenceReadinessR, genericProtocolCrossCheckR] = results

phase('Build')

const buildOrder = [
  ['AMBA-4 protocol fingerprints: extend connectivity.py PROTOCOL_FINGERPRINTS with AHB/AHB-Lite/APB/APB3/APB4/AXI3/AXI4/AXI4-Lite/ACE-Lite/AXI4-Stream signal sets', locateEnumerateClassifyR],
  ['AMBA-5/6: dual fabric-side/endpoint-side role classification + per-protocol interface-count table, generalizing verify_self_check_identity()', roleCountingR],
  ['AMBA-7..14: the fabric-port endpoint-tracing algorithm (the core new module) -- wrappers/muxes/arbiters/bridges, VIP placement priority, multi-source/destination, 10-state termination enum', endpointTracingR],
  ['AMBA-15..20: VIP bind validation checklist + fabric-port-to-VIP-bind matrix + unresolved-port table + topology summary/tree + VIP instance plan (extend connectivity.py table rendering)', bindValidationOutputsR],
  ['AMBA-21/22: scoreboard reference environment analysis (read-only) + AMBA_PORT_REGISTRY (schema-compatible with fabric_topology_completeness_gate.py)', scoreboardRegistryR],
  ['AMBA-23/24/25: address-map cross-check (reuse address_map_verifier.py) + clock/reset domain analysis + scoreboard/port scaling (reuse amba_fabric_generator.py algorithms)', addressClockScalingR],
  ['AMBA-26..29: L5 branch mapping (update branch-mapper SKILL.md UNTESTED status if warranted) + confidence rule + 17-item discovery report assembly + per-port/overall readiness', branchMappingConfidenceReadinessR],
]

log('Audit phase complete. Building the discovery/planning/reporting machinery sequentially (dependency order: fingerprints -> roles/counting -> tracing -> outputs -> registry -> address/clock -> branch-mapping/report), reusing real existing code at every step, never writing a real bind statement into any real environment.')

const buildResults = []
for (const [name, report] of buildOrder) {
  const buildResult = await agent(`Working directory: D:/DV/Task/DV_Agent_Harness_L5/v50

## Background

${CONTEXT}

This is a sequential build pass, step **${name}**, installing AMBA4 fabric-discovery machinery. Prior steps in this same sequence may have already added real code you should build on (check git log/git diff for this session's own recent commits under this same effort before assuming a prerequisite is missing).

NOTE: MANY other agents/workflows are concurrently active in this repo (a 14-AI-mechanism workflow, an Obsidian-memory workflow, a Capability-Evolution Stage 0+1 workflow, a live USB build). connectivity.py, CLAUDE.md, and branch-mapper/SKILL.md in particular may be touched by those concurrently. Check git status/git diff on any file BEFORE touching it, and use the hand-scoped patch technique (git diff > patch, trim to your hunk, git apply --cached --check then --cached) for EVERY file, never a broad git add.

Its real, current audit finding for this scope (read carefully, this is real evidence gathered just now):

${report}

## Your task

1. If the audit found this already WIRED_AND_FIRING: do nothing, just re-confirm the cited evidence.
2. Otherwise build it for real, reusing existing code (connectivity.py, amba_fabric_generator.py, address_map_verifier.py, fabric_topology_completeness_gate.py's schema) per the audit's own concrete recommendation. Prefer extending connectivity.py directly over a new parallel module UNLESS the audit found the capability (e.g. the AMBA-7..14 endpoint-tracing graph traversal) is genuinely structurally new -- in that case a new, clearly-scoped module (e.g. dv_harness/amba_fabric_discovery.py) that IMPORTS and composes connectivity.py's/amba_fabric_generator.py's real primitives is correct, not a copy of their logic.
3. HARD CONSTRAINT, non-negotiable: never write a real bind statement into any real or synthetic GENERATED UVM environment as part of this build. A synthetic RTL/topology fixture used ONLY inside your own new test file is fine and expected (you need one to prove the tracing/discovery logic works); writing an actual 'bind' SV statement anywhere outside that throwaway test fixture is out of scope and must not happen. This step builds discovery/planning/reporting tooling ONLY, per the master prompt's own AMBA-30/AMBA-31 gate.
4. Write real tests (a synthetic multi-master/multi-slave fabric fixture, at minimum) proving your piece actually works -- exercise both a clean-topology case and at least one genuinely ambiguous/unresolved case (AMBA-14's MULTIPLE_SOURCE/BLOCKED/AMBIGUOUS states are exactly this project's own hard-won lesson: an untested "happy path only" tracer is not real coverage).
5. Run the full relevant test suite for whatever you touched and confirm pass.
6. Commit your change for real with a clear, scoped commit.

Write a report to .work/gap-close-amba4-${name.replace(/[^a-zA-Z0-9]+/g, '-').toLowerCase().slice(0, 40)}-report.md. Report DONE (with what changed) / NO_ACTION_NEEDED / NEEDS_SEPARATE_EFFORT / BLOCKED, with a one-line test summary if you made a change.`, {label: `build:${name}`, phase: 'Build', model: 'claude-opus-5'})
  buildResults.push([name, buildResult])
  log(`Build step done: ${name}`)
}

phase('Review')

const review = await agent(`${CONTEXT}

Independently review this "install AMBA4 fabric-discovery + VIP-bind-planning machinery (AMBA-1..29), reuse-first, discovery/planning/reporting only" effort. Do not accept any report's own claim without independent re-verification -- run real commands yourself.

Read every audit report and every build-step report in full first (search .work/ for files matching gap-close-amba4-*-report.md).

Raw returned results, for cross-reference:

### Audits
${[
  ['locate-enumerate-classify', locateEnumerateClassifyR], ['role-counting', roleCountingR],
  ['endpoint-tracing', endpointTracingR], ['bind-validation-outputs', bindValidationOutputsR],
  ['scoreboard-registry', scoreboardRegistryR], ['address-clock-scaling', addressClockScalingR],
  ['branch-mapping-confidence-readiness', branchMappingConfidenceReadinessR],
  ['generic-protocol-cross-check', genericProtocolCrossCheckR],
].map(([n, r]) => `#### ${n}\n${r}`).join('\n\n')}

### Build steps
${buildResults.map(([name, result]) => `#### ${name}\n${result}`).join('\n\n')}

Verify independently:
1. For every build step reporting DONE: did it actually work (run its new test yourself), and does its test genuinely cover an ambiguous/unresolved case, not just a clean happy path?
2. THE MOST IMPORTANT CHECK: grep the entire diff/commit history this pass produced for any real 'bind' SV statement written outside a test fixture. This effort's hard constraint was discovery/planning/reporting ONLY -- confirm zero violations of that boundary, and flag any as CRITICAL if found.
3. Confirm no parallel/duplicate classifier was built where connectivity.py's real T1-T4/PROTOCOL_FINGERPRINTS/verify_self_check_identity machinery should have been reused instead.
4. Actually exercise the new discovery pipeline end-to-end yourself against a real or synthetic multi-master/multi-slave AMBA fixture (build one if none exists) and confirm it produces AMBA-16's matrix, AMBA-17's unresolved-port table, AMBA-19's topology tree, and AMBA-22's registry, in roughly AMBA-28's report order.
5. Run the full project test suite (python -m pytest dv_harness_tests/ -q) and report the real pass/fail count.
6. Check git hygiene across all commits this pass made.

Report a clear verdict per AMBA sub-area (GENUINELY_CLOSED / STILL_GAP / CORRECTLY_DEFERRED-per-AMBA-30/31) plus an overall verdict (APPROVED / NEEDS_FIX), with concrete evidence-cited findings. Be exhaustive about the bind-statement boundary check specifically -- that is this effort's single most important safety constraint.`, {label: 'review', phase: 'Review', model: 'claude-opus-5'})

return {
  audits: {
    locateEnumerateClassifyR, roleCountingR, endpointTracingR, bindValidationOutputsR,
    scoreboardRegistryR, addressClockScalingR, branchMappingConfidenceReadinessR, genericProtocolCrossCheckR,
  },
  buildResults: Object.fromEntries(buildResults),
  review,
}
