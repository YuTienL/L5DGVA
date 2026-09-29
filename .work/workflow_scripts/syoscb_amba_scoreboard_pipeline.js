export const meta = {
  name: 'syoscb-amba-scoreboard-pipeline',
  description: 'Install AMBA SoC bus multi-master/multi-slave scoreboard planning (SYOSCB-1..30) as real, reuse-first discovery/planning/reporting tooling extending connectivity.py / amba_fabric_generator.py / address_map_verifier.py / amba_port_registry.py / amba_scoreboard_env.py / knowledge_center.py -- per this section\'s own SYOSCB-33/34 mandatory human-review gate, STOPS before any real uvm_syoscb vendoring, VIP integration, or build/VCS run',
  phases: [
    { title: 'Audit', detail: '8 parallel audits of SYOSCB-1..30 against real code and the real third-party source directory' },
    { title: 'Build', detail: 'sequential, reuse-first build of the Phase-1-only planning/reporting machinery' },
    { title: 'Review', detail: 'independent re-verification incl. the SYOSCB-33/34 stop-before-vendoring/build gate' },
  ],
}

const CONTEXT = `
This implements ONLY SYOSCB-1 through SYOSCB-30 (source audit, capability
planning, IR/predictor/matching-policy design, reporting) from the
"FIRST-CLASS DOMAIN EXTENSION -- AMBA SOC BUS MULTI-MASTER / MULTI-SLAVE
SCOREBOARD / SYOSIL uvm_syoscb-1.0.2.4 REUSE + INTEGRATION" section
(SYOSCB-1..39) at the end of
D:/DV/Task/DV_Agent_Harness_L5/DV_Agent_Harness_L5_ULTIMATE_COMPLETE_Master_Prompt_SystemLevel_AMBA4_SyoSil_CCE_Research.md
(read it yourself for the exact wording -- lines ~4524-5589).

The document's OWN gate is explicit and non-negotiable:
- SYOSCB-33 (PHASE-1 HUMAN REVIEW GATE): after audit/discovery/planning STOP
  and report AMBA FABRIC DISCOVERY COMPLETE / AMBA PORT REGISTRY COMPLETE /
  VIP BIND PLAN COMPLETE / SYOSIL SOURCE AUDIT COMPLETE / SYOSIL INTEGRATION
  PLAN COMPLETE / AMBA SCOREBOARD ARCHITECTURE COMPLETE / PRODUCER-QUEUE
  MAPPING PLAN COMPLETE / AMBA ADAPTER PLAN COMPLETE / ROUTE PREDICTOR PLAN
  COMPLETE / IMPLEMENTATION NOT STARTED / AWAITING USER APPROVAL. "Do not
  modify production L5 before approval."
- SYOSCB-34 (PHASE-2 IMPLEMENTATION -- ONLY AFTER APPROVAL): only after
  explicit approval does copying the COMPLETE uvm_syoscb-1.0.2.4 directory
  into the repo, build/filelist updates, the SyoSil baseline compile, real
  adapter/IR/predictor/topology CODE, VIP monitor connection, targeted and
  stress tests, and a real build/verify/run/WAVE/fsdbreport/regression pass
  happen.
This workflow's scope is bounded to building the AUDIT/PLANNING/REPORTING
machinery only. NEVER copy/vendor the real uvm_syoscb-1.0.2.4 directory into
the repository. NEVER write real SystemVerilog scoreboard/adapter/predictor
code that gets wired into any real or generated UVM environment. NEVER run a
real VCS/UVM build or baseline test. A synthetic fixture used only inside a
throwaway unit test for this workflow's OWN new Python tooling is fine; a real
uvm_syoscb build or a real bind statement anywhere outside that is not.

REAL, JUST-CONFIRMED FACT (do not re-litigate, but re-verify with your own
command if you want independent proof): the real uvm_syoscb-1.0.2.4 SOURCE
DIRECTORY DOES EXIST on this machine, at exactly the path SYOSCB-1/38/39
name as mandatory:

  D:\\DV\\Scoreboard\\uvm_syoscb-1.0.2.4

Confirmed this session via \`ls -la D:/DV/Scoreboard\` and
\`find D:/DV/Task/DV_Agent_Harness_L5 -iname "*syoscb*"\` (zero hits under the
project tree, including v50/). Real facts already gathered from the source
directory (234 files under it): VERSION.txt reads exactly \`1.0.2.4\`;
LICENSE.txt is the real Apache License 2.0 text; NOTICE.txt/README.txt/
RELEASE_NOTES.txt are present; src/ has 16 real \`.svh\`/\`.sv\` files including
cl_syoscb.svh, cl_syoscb_cfg.svh, cl_syoscb_cfg_pl.svh, cl_syoscb_compare*.svh
(cl_syoscb_compare_base/io/iop/ooo -- io=in-order, iop=in-order-per-producer,
ooo=out-of-order, matching SYOSCB-17's three named compare concepts to real
class names), cl_syoscb_item.svh, cl_syoscb_queue*.svh (queue + 2 iterator
variants + std queue), cl_syoscb_report_catcher.svh, cl_syoscb_subscriber.svh,
pk_syoscb.sv; tb/ has a real testbench (cl_scbtest_env.svh, scbtest_top.sv,
scbtest.mk, a test/ subdir); Makefile.vendor.{cadence,mentor,synopsys} exist;
docs/ has an ESNUG paper plus html/pdf reference docs. So SYOSCB-1's own
"REQUIRED SOURCE DIRECTORY AUDIT" is NOT a NOT_AVAILABLE case for the source
itself -- the real source is inspectable read-only, right now, without
copying it anywhere. What genuinely IS NOT_AVAILABLE without Phase-2 approval
is: the source integrated/vendored INTO this repository (SYOSCB-2, not done,
must not be done here), and anything requiring a real VCS/UVM build against
it (SYOSCB-25 build/filelist/compile-order check, SYOSCB-26 baseline
compile/run) -- those need a real toolchain invocation this workflow's scope
explicitly excludes. Audit agents must read the REAL source tree read-only
(list files, read VERSION.txt/LICENSE.txt/class headers/public API
signatures) to answer SYOSCB-1's checklist honestly -- never fabricate class
names or API signatures for a library that is sitting right there to be read.

REUSE-FIRST is this document's own repeated instruction (SYOSCB-31: "SEARCH
EXISTING L5 FIRST before adding new Agent/Skill/Node/database/memory
framework"; SYOSCB-4: "Do not fork upstream unnecessarily"), and this
project has an extremely strong, independently-verified history this session
of exactly the opposite failure mode (parallel tiered-confidence classifiers,
duplicate memory mechanisms, a would-be scoreboard super-agent) being caught
as a real defect. Real, already-confirmed overlap points (re-verify with your
own grep/read, do not just cite this list):

- dv_harness/amba_fabric_discovery.py (2838 lines, real, this session's
  AMBA-7..20 work): fabric-port endpoint tracing, VIP bind matrix, unresolved
  ports, topology tree, VIP instance plan, TraceTerminationStatus 10-value
  enum, assert_no_bind_statement() (proves a planning artifact never renders
  emittable SV). This is SYOSCB-7's "REUSE THE EXISTING AMBA FABRIC DISCOVERY
  WORKFLOW" -- the AMBA_PORT_REGISTRY it feeds is exactly the thing SYOSCB-7
  says must not be re-asked of the user.
- dv_harness/amba_port_registry.py (500 lines, real, this session's AMBA-22
  work): build_amba_port_registry() assembles a 19-field row (port_id,
  fabric_port, protocol, fabric_role, endpoint_role, endpoint_hierarchy,
  vip_bind_hierarchy, vip_mode, clock, reset, address_width, data_width,
  id_width, user_widths, scoreboard_channel, trace_status, readiness,
  confidence, source_evidence) by JOINING amba_fabric_discovery's matrix +
  amba_scoreboard_env's ingress map -- never re-deriving anything a second
  way. project_to_fabric_topology() projects it into
  tools/verification_flow/fabric_topology_completeness_gate.py's exact
  masters/slaves/scoreboard_matrix/address_map schema via
  amba_fabric_generator.build_scoreboard_matrix()/compute_address_regions().
  This is SYOSCB-14's "AMBA_PORT_REGISTRY -> Dynamic Scoreboard Topology
  Generator -> Producer/Queue/Route Mapping" already half-built -- confirm
  exactly how much of SYOSCB-14/15/16 this already covers vs. what a SyoSil
  producer/queue CONFIG layer on top of it would still need.
- dv_harness/amba_scoreboard_env.py (755 lines, real, this session's AMBA-21
  work): analyze_scoreboard_environment() reads an existing UVM
  scoreboard/reference environment's class source READ-ONLY (via
  vip_symbol_index, declarations/locations only, never method bodies),
  classifies each class's role (SCOREBOARD/SUBSCRIBER/PREDICTOR/
  REFERENCE_MODEL/ADAPTER) at BindTier T2/T3/T4 confidence, discovers
  analysis-port ingress points, and reports every ordering/outstanding-
  transaction/address-map assumption as REQUIRED_HUMAN_INPUT with cited
  candidate declarations (never a guessed value, because those live in method
  bodies this module deliberately never retains). map_vip_monitors_to_
  scoreboard_ingress() maps a planned VIP to a real ingress or reports
  AMBIGUOUS/NOT_FOUND/NO_ENVIRONMENT. assert_sources_unmodified() makes
  "read-only" checkable via sha256, not just promised. This is SYOSCB-24
  "EXISTING SCOREBOARD REFERENCE ENVIRONMENT" already built for real --
  confirm whether it also already substantially covers SYOSCB-15 (MASTER ->
  PRODUCER MAPPING) and SYOSCB-21's own result-taxonomy needs, or whether
  those are a genuinely separate layer (SyoSil producer/queue registration is
  NOT the same thing as "which class in an existing env is a scoreboard").
- dv_harness/uvm_generator/amba_fabric_generator.py (422 lines, real, tested
  in dv_harness_tests/test_amba_fabric_generator.py): compute_id_width(),
  compute_address_regions() (real overlap/gap/full-coverage address-decode
  algorithm), build_scoreboard_matrix() (per-pair scoreboard-matrix
  resolution from masters/slaves/connectivity). SYOSCB-12 (Route/Transform
  Predictor: address decode, ID remap, width/burst transform, bridge
  behavior, ordering-domain expectation) and SYOSCB-13 (Address Map Evidence)
  should reuse these algorithms directly rather than recomputing differently
  -- confirm the exact remaining gap (ID remap / width-burst TRANSFORM
  prediction, as opposed to static ID-width/address-region computation, is
  very likely genuinely new).
- dv_harness/uvm_generator/address_map_verifier.py (340 lines, real): 3-source
  address-map corroboration (decoder + BFM histogram + doc) -- SYOSCB-13's
  ADDRESS MAP EVIDENCE requirement almost certainly reuses this directly.
- dv_harness/connectivity.py (4511 lines, real): BindTier T1-T4
  classify_bind_tier(), REQUIRED_HUMAN_INPUT sentinel,
  SCOREBOARD_PLAN_FIELDS (endpoint_pairs/matching_key/ordering/
  ordering_tolerance_depth/transformation_rules/legal_drop_conditions/
  reset_flush_behavior/orphan_unmatched_threshold/orphan_unmatched_timeout --
  this is ALREADY an L5-owned protocol-agnostic scoreboard-plan schema)
  unfilled_plan_fields()/find_required_human_input_paths() (row-lock
  confirm-gate), render_markdown_table(). SYOSCB-18 (AXI matching must not be
  raw object compare -- route/master/ID/ordering-domain/burst-aware match
  key) and SYOSCB-21 (result taxonomy) map directly onto
  SCOREBOARD_PLAN_FIELDS' matching_key/ordering/transformation_rules and this
  should extend that schema, not invent a second one.
- dv_harness/knowledge_center.py (351 lines, real): KnowledgeCenterClient,
  SUBSYSTEM_RECORD_FIELDS (21-field typed accessor pattern over the SAME
  add/search verbs, "never create a parallel Knowledge Center" already
  enforced by this exact pattern) is the template SYOSCB-3's COMPONENT/
  VERSION/SOURCE_REFERENCE/ROLE/INTEGRATION_POLICY/L5_DESTINATION/
  BUILD_STATUS/KNOWN_LIMITATIONS/PROVENANCE registration should follow.
- .claude/agents/ (24 files, listed this session): confirmed NO existing
  scoreboard-named agent (grep for "score" across filenames found none).
  SYOSCB-32 ("DO NOT CREATE A SCOREBOARD SUPER-AGENT") is therefore easy to
  honor by simply not adding one -- extend existing mechanisms/modules/tests
  only, never propose a new autonomous top-level agent in this pass.

Verdict format per SYOSCB-N requirement, one of:
- WIRED_AND_FIRING: real, callable, evidenced end-to-end.
- PARTIALLY_WIRED: real code exists and covers part of the requirement --
  name exactly what's missing.
- DORMANT: real code exists but has no real caller for this purpose.
- NEVER_BUILT: no real implementation exists, a genuine gap.
- NOT_AVAILABLE: genuinely blocked by something Phase-1 cannot supply (the
  real uvm_syoscb source VENDORED INTO THE REPO, a real VCS/UVM toolchain
  run) -- name exactly what is missing and why it is a Phase-2-only item per
  SYOSCB-33/34, never blur this with NEVER_BUILT (which means "buildable now,
  nobody built it" -- NOT_AVAILABLE means "cannot be built in this phase at
  all").
Cite real file:line or real command output for every verdict, including
actually reading real files under D:/DV/Scoreboard/uvm_syoscb-1.0.2.4 where
relevant (read-only; never copy anything out of it). Audit only -- do not
modify any file in this phase, and do not copy anything from
D:/DV/Scoreboard into the repository.
`

phase('Audit')

const auditSourcePolicy = agent(`${CONTEXT}

## Your scope: SYOSCB-1, SYOSCB-2, SYOSCB-3, SYOSCB-4 (required source directory audit, complete directory integration policy, Knowledge Center registration, do-not-fork-unnecessarily policy)

Actually read (read-only, do not copy) as much of D:/DV/Scoreboard/uvm_syoscb-1.0.2.4 as you need to answer SYOSCB-1's checklist for real: list src/*.svh and tb/* files, read VERSION.txt, LICENSE.txt, NOTICE.txt, README.txt, RELEASE_NOTES.txt, and skim the public class/interface declarations in a few of the cl_syoscb_*.svh files (compare_base/io/iop/ooo especially -- these are SYOSCB-17's compare-strategy candidates) to report their real class names, macros and public API shape. Do not guess -- this real source is sitting on disk right now. Report package files/scoreboard classes/config classes/queue implementations/producer APIs/subscriber-TLM structure/compare algorithms/macros/tests/examples/scripts/documentation/compile order/UVM dependencies/license-copyright-provenance/version metadata, per SYOSCB-1's own list, each with real evidence (file, line where feasible).

For SYOSCB-2: search the actual v50 repository layout for an existing third-party/external/reference vendoring convention (e.g. is there already a third_party/ or external/ or vendor/ directory anywhere in v50?) and report what the real convention is or that none exists yet -- do NOT actually copy uvm_syoscb-1.0.2.4 into the repo; that is a SYOSCB-34/Phase-2 action.

For SYOSCB-3: read dv_harness/knowledge_center.py's SUBSYSTEM_RECORD_FIELDS pattern and confirm it is the correct template to follow for a COMPONENT=uvm_syoscb registration record (do not write to the live remote Knowledge Center -- that requires the SSH/Remote Transport Connection Intake gate in CLAUDE.md and is out of scope here; just confirm the pattern and what fields a registration payload builder function would need).

For SYOSCB-4: there is no upstream patch to evaluate yet (nothing has been vendored); report this policy as fully addressable by a Phase-2-time decision procedure, not something to design new machinery for now.

Report your verdict per the required format for SYOSCB-1/2/3/4 separately.`, {label: 'audit:source-policy', phase: 'Audit'})

const auditRoleLimitsReuseProtocols = agent(`${CONTEXT}

## Your scope: SYOSCB-5, SYOSCB-6, SYOSCB-7, SYOSCB-8 (role of SyoSil in L5, explicit SyoSil limitations, reuse the existing AMBA fabric discovery workflow, supported AMBA protocols)

Cross-check SYOSCB-5's list of SyoSil generic capabilities (multiple queues, multiple producers, UVM/TLM input, in-order/out-of-order/producer-aware comparison, generic sequence-item comparison) against the real class files under D:/DV/Scoreboard/uvm_syoscb-1.0.2.4/src (read-only) -- confirm which real classes back which claimed capability (e.g. cl_syoscb_queue_std.svh for queue management, cl_syoscb_compare_io/iop/ooo.svh for the three compare modes). For SYOSCB-6, confirm from the real source that nothing in it references AMBA/AXI/AHB/APB signal or protocol semantics (grep the src/ tree for AXI/AHB/APB/burst/ID-tag tokens) -- this is expected to confirm SyoSil is genuinely generic with zero AMBA awareness. For SYOSCB-7, verify concretely that dv_harness/amba_fabric_discovery.py + amba_port_registry.py + amba_scoreboard_env.py (all real, already built this session) together supply everything SYOSCB-7 says must not be re-asked of the user (master/slave counts, port protocols, source/destination endpoints, VIP bind hierarchy, clock/reset, port widths) -- cite the exact fields on AMBA_PORT_REGISTRY's 19-column schema that answer each item. For SYOSCB-8, check dv_harness/connectivity.py's PROTOCOL_FINGERPRINTS / AMBA4_PROTOCOLS (built by the earlier AMBA4 workflow this session) against SYOSCB-8's exact protocol list (AHB, AHB-Lite, APB, APB3, APB4, AXI3, AXI4, AXI4-Lite, ACE-Lite, AXI4-Stream) and report which are and are not currently classifiable.

Report your verdict per the required format for SYOSCB-5/6/7/8 separately.`, {label: 'audit:role-limits-reuse-protocols', phase: 'Audit'})

const auditAdapterIrReconstruction = agent(`${CONTEXT}

## Your scope: SYOSCB-9, SYOSCB-10, SYOSCB-11 (AMBA protocol adapter layer, AMBA transaction IR, AXI logical transaction reconstruction)

Check whether any existing L5/VIP adapter code normalizes VIP-specific transaction objects into a common representation (search dv_harness/uvm_generator/ and any generated environment's adapter files) before assuming SYOSCB-9 is NEVER_BUILT. For SYOSCB-10, check dv_harness/connectivity.py's SCOREBOARD_PLAN_FIELDS and amba_port_registry.py's 19-field row against SYOSCB-10's proposed IR field list (protocol, master_port_id, slave_port_id, source/destination_hierarchy, transaction_type, address, data, byte_enable, burst_type/len/size, transaction_id, original_id, fabric_id, response, sequence_number, timestamp, route_id, clock_domain, expected_actual, source_evidence) -- report concretely which fields already exist under a different name/location vs. which would be genuinely new. For SYOSCB-11 (AW/W/B/AR/R reconstruction, multiple outstanding transactions, same-ID ordering, different-ID legal reordering, WLAST/RLAST, backpressure): confirm this is very likely NEVER_BUILT (no evidence anywhere in this repo of AXI channel-level transaction reconstruction logic), but verify by grepping for AW/AR/WLAST/RLAST/outstanding tokens across dv_harness/ first.

Report your verdict per the required format for SYOSCB-9/10/11 separately, with a concrete list of which IR fields are genuinely new vs. reusable from amba_port_registry.py's existing 19 columns.`, {label: 'audit:adapter-ir-reconstruction', phase: 'Audit'})

const auditPredictorAddressScoreboardModel = agent(`${CONTEXT}

## Your scope: SYOSCB-12, SYOSCB-13, SYOSCB-14, SYOSCB-15, SYOSCB-16 (route/transform predictor, address map evidence, multi-master/multi-slave scoreboard model, master->producer mapping, destination/ordering-domain->queue mapping)

Check dv_harness/uvm_generator/amba_fabric_generator.py's compute_address_regions()/compute_id_width()/build_scoreboard_matrix() (real, tested) against SYOSCB-12's route/transform predictor requirements -- these functions answer "which addresses belong to which slave" and "what ID width is needed", which is real but is NOT the same as predicting an ID REMAP or a burst SPLIT/MERGE transform; confirm this distinction precisely rather than assuming full coverage. Check dv_harness/uvm_generator/address_map_verifier.py's verify_address_map() (3-source corroboration) against SYOSCB-13 directly. Check dv_harness/amba_port_registry.py's build_amba_port_registry()/project_to_fabric_topology() against SYOSCB-14 (avoid one-scoreboard-per-NxM-path, prefer AMBA_PORT_REGISTRY -> Dynamic Scoreboard Topology Generator) -- this is very likely already substantially covered; name exactly what a SyoSil-specific producer/queue CONFIGURATION layer on top of it would still need (SYOSCB-15/16). For SYOSCB-15 (Master -> SyoSil Producer) and SYOSCB-16 (destination/ordering-domain -> SyoSil Queue): read D:/DV/Scoreboard/uvm_syoscb-1.0.2.4/src/cl_syoscb_cfg.svh and cl_syoscb_cfg_pl.svh read-only to report the REAL producer/queue configuration API shape (do not guess or invent method names) -- confirm whether the real API is compatible with a mapping built purely from AMBA_PORT_REGISTRY rows.

Report your verdict per the required format for SYOSCB-12/13/14/15/16 separately.`, {label: 'audit:predictor-address-scoreboard-model', phase: 'Audit'})

const auditCompareMatchingTransformBridge = agent(`${CONTEXT}

## Your scope: SYOSCB-17, SYOSCB-18, SYOSCB-19, SYOSCB-20 (compare strategy, AXI matching must not be raw object compare, fabric transformation model, protocol bridge handling)

Read D:/DV/Scoreboard/uvm_syoscb-1.0.2.4/src/cl_syoscb_compare_base.svh, cl_syoscb_compare_io.svh, cl_syoscb_compare_iop.svh, cl_syoscb_compare_ooo.svh read-only and report their REAL class names, extends relationships and any real public compare-strategy configuration knobs you can see from declarations (do not invent SyoSil API calls -- SYOSCB-17 explicitly says "Use actual class/config names from source"). Cross-reference SYOSCB-17's per-protocol compare-strategy starting policy (APB/APB3/APB4/AHB-Lite -> In-Order; AHB Multi-Master -> producer-aware; AXI4-Lite -> address/order aware; AXI3/AXI4 -> ID+route+ordering+OOO aware; ACE-Lite -> AXI+coherency; AXI4-Stream -> stream/packet/order aware) against connectivity.py's SCOREBOARD_PLAN_FIELDS' \`ordering\` field -- confirm whether a per-protocol default-policy TABLE (as opposed to a single ordering value) currently exists anywhere, or is a genuine gap. For SYOSCB-18, check connectivity.py's \`matching_key\`/\`transformation_rules\` SCOREBOARD_PLAN_FIELDS entries against SYOSCB-18's required match-key composition (route + master + AXI ID + read/write domain + ordering domain + sequence/burst info) -- report whether the schema already has the RIGHT FIELDS even if nothing yet populates them with real AMBA-derived values. For SYOSCB-19/20 (fabric transformation model, protocol bridge boundaries e.g. AXI->APB): check amba_fabric_discovery.py's protocol-bridge handling (it already tracks an AMBA-11 "second side" of a bridge as distinct evidence per amba_port_registry.py's amba11_second_side field) against these two requirements.

Report your verdict per the required format for SYOSCB-17/18/19/20 separately.`, {label: 'audit:compare-matching-transform-bridge', phase: 'Audit'})

const auditTaxonomyVisibilityModeExistingEnv = agent(`${CONTEXT}

## Your scope: SYOSCB-21, SYOSCB-22, SYOSCB-23, SYOSCB-24 (required scoreboard result taxonomy, scoreboard-by-port visibility, VIP mode compatibility, existing scoreboard reference environment)

Check connectivity.py's SCOREBOARD_PLAN_FIELDS and any existing result/verdict enum in dv_harness/ (grep for MATCH/MISMATCH/ROUTE_ERROR/ORDERING_ERROR-shaped constants) against SYOSCB-21's required 14-value taxonomy (MATCH, DATA_MISMATCH, ADDRESS_MISMATCH, RESPONSE_MISMATCH, ROUTE_ERROR, ORDERING_ERROR, MISSING_TRANSACTION, UNEXPECTED_TRANSACTION, DUPLICATE_TRANSACTION, ID_MAPPING_ERROR, BURST_ERROR, PROTOCOL_TRANSFORM_ERROR, TIMEOUT, UNKNOWN) -- report exactly which values already exist under some name (e.g. GateStatus's PASS/FAIL/NOT_AVAILABLE/PENDING/NOT_YET_RUN is a DIFFERENT taxonomy for a different purpose, do not conflate them) vs. which are a genuine gap. For SYOSCB-22 (per-port visibility: transaction/read/write/burst counts, responses, errors, matches, mismatches, missing/unexpected, ordering/route errors, latency): check amba_port_registry.py's per-row structure for whether it is already the right SHAPE to carry these counters (even if nothing populates them yet, since no real transactions have run). For SYOSCB-23 (VIP mode: passive monitor default, inspect SYSTEM_RESOURCE_REGISTRY before any active driver): check dv_harness/system_resource_inventory.py (real, from the concurrent System-Level Verification Integration workflow this session) for whether it already provides exactly this check. For SYOSCB-24: re-verify dv_harness/amba_scoreboard_env.py's analyze_scoreboard_environment()/map_vip_monitors_to_scoreboard_ingress() (already built this session for AMBA-21) directly satisfies SYOSCB-24's requirement to inspect an existing scoreboard env's transaction types/analysis ports/adapters/predictors/reference models/per-port structure/address-map/ordering/outstanding assumptions and map KEEP/ENHANCE/REUSE/REPLACE/EXPERIMENT/REJECT -- report precisely whether the KEEP/ENHANCE/REUSE/REPLACE/EXPERIMENT/REJECT disposition vocabulary itself exists yet or only the underlying classification/ingress-mapping does.

Report your verdict per the required format for SYOSCB-21/22/23/24 separately.`, {label: 'audit:taxonomy-visibility-mode-existing-env', phase: 'Audit'})

const auditBuildBaselineTestsStress = agent(`${CONTEXT}

## Your scope: SYOSCB-25, SYOSCB-26, SYOSCB-27, SYOSCB-28 (build/VCS integration check, SyoSil baseline test, required AMBA scoreboard tests, stress test)

These four items are the ones most likely to be genuinely NOT_AVAILABLE in this phase, and your job is to confirm that honestly rather than assume it or fabricate a result. SYOSCB-25 (filelists/compile order/include dirs/UVM-VCS compatibility/package-class-naming conflicts/macro conflicts/factory registration/TLM connectivity) and SYOSCB-26 (prove the copied SyoSil framework itself builds/runs in the L5 VCS environment, with build command/UVM version/VCS version/PASS-FAIL/warnings/errors/runtime/evidence) both REQUIRE the source to be vendored into the repo first (SYOSCB-2/34, Phase-2-gated) AND a real VCS/UVM toolchain invocation -- check whether a VCS/UVM toolchain is even reachable from this local machine (this project's CLAUDE.md describes remote Linux DV server execution via tools/remote/remote_exec.py, gated by an explicit SSH/Remote Transport Connection Intake the user must confirm each session) and report the real, current state (has such a session been established this run? almost certainly not, since this is a Phase-1 planning dispatch) rather than assuming success or failure. SYOSCB-27/28 (targeted and stress AMBA scoreboard tests) cannot be written as REAL scoreboard tests without a real scoreboard implementation to test -- but a TEST PLAN (what test cases would need to exist, mapped onto amba_fabric_generator.py's already-real master/slave/scoreboard-matrix shapes) is legitimate Phase-1 planning output. Draft that plan's outline (do not write actual SV/UVM test files).

Report your verdict per the required format for SYOSCB-25/26/27/28 separately -- NOT_AVAILABLE is the expected, honest verdict for 25/26 (name exactly what would need to happen first: vendor the source, then run a real VCS/UVM baseline compile on a real or remote toolchain), while 27/28 can be PARTIALLY_WIRED or NEVER_BUILT if a scoped test-plan OUTLINE (not real tests) is a legitimate Phase-1 deliverable -- justify which you pick.`, {label: 'audit:build-baseline-tests-stress', phase: 'Audit'})

const auditArchReportSearchNoAgent = agent(`${CONTEXT}

## Your scope: SYOSCB-29, SYOSCB-30, SYOSCB-31, SYOSCB-32 (required architecture representation, required Phase-1 report, search existing L5 first, do not create a scoreboard super-agent)

For SYOSCB-29: check whether any existing renderer in dv_harness/ (connectivity.py's render_markdown_table, amba_fabric_discovery.py's tree/report renderers, amba_port_registry.py's render_amba_port_registry_report) could be extended/composed into SYOSCB-29's required tree (DV Agent Harness L5 -> AMBA SoC Fabric Verification -> Fabric Discovery -> VIP Bind Planning -> AMBA Transaction Normalization [10 adapters] -> AMBA Route/Transform Predictor -> AMBA Scoreboard [Expected/Actual/SyoSil UVM SCB] -> Evidence) or whether a new, clearly-scoped rendering function is needed -- report concretely. For SYOSCB-30: check the 29-item Phase-1 report list against what amba_fabric_discovery.py + amba_port_registry.py + amba_scoreboard_env.py's existing render_*_report() functions already assemble (items 6-16 especially, the AMBA fabric/port/VIP-bind items, are very likely already produced by the AMBA4 workflow's own report) vs. what is new to SYOSCB (items 2-4 SyoSil source/license/location, 17-23 SyoSil capability/limitation/IR/adapter/predictor/producer-queue/matching-policy plans, 24-26 scoreboard-test/VCS plans, 27 readiness). For SYOSCB-31: this is the same "search existing first" instruction as every other section this session (AMBA-0's preamble, the AI-mechanism gap-close passes) -- confirm the audit agents above actually did this (they were instructed to) rather than treating it as a separate new mechanism to build. For SYOSCB-32: confirm (re-verify, do not just cite) that .claude/agents/ genuinely has no scoreboard-named or SyoSil-named agent file, and that this workflow's own Build phase does not propose adding one -- flag as CRITICAL if you find any hint anywhere in the audit reports of a proposed new autonomous top-level agent for this feature.

Report your verdict per the required format for SYOSCB-29/30/31/32 separately.`, {label: 'audit:arch-report-search-noagent', phase: 'Audit'})

const results = await parallel([
  () => auditSourcePolicy, () => auditRoleLimitsReuseProtocols, () => auditAdapterIrReconstruction,
  () => auditPredictorAddressScoreboardModel, () => auditCompareMatchingTransformBridge,
  () => auditTaxonomyVisibilityModeExistingEnv, () => auditBuildBaselineTestsStress,
  () => auditArchReportSearchNoAgent,
])
const [sourcePolicyR, roleLimitsReuseProtocolsR, adapterIrReconstructionR, predictorAddressScoreboardModelR,
  compareMatchingTransformBridgeR, taxonomyVisibilityModeExistingEnvR, buildBaselineTestsStressR,
  archReportSearchNoAgentR] = results

phase('Build')

const buildOrder = [
  ['SYOSCB-1/3: real read-only SyoSil source auditor module (inspect D:/DV/Scoreboard/uvm_syoscb-1.0.2.4, report class/config/queue/compare/macro/test/doc/license/version/provenance facts) + a KnowledgeCenterClient-pattern registration-payload builder (built and tested, not live-written to the remote KC)', sourcePolicyR],
  ['SYOSCB-9/10: AMBA Transaction IR field extension on amba_port_registry.py\'s row shape (add only the genuinely-new SYOSCB-10 fields the audit named, e.g. burst_type/burst_len/burst_size/response/sequence_number/route_id/clock_domain/expected_actual -- never re-add a field the registry already carries under another name) + adapter-layer plan document (no real adapter SV code)', adapterIrReconstructionR],
  ['SYOSCB-12/13: Route/Transform Predictor plan module extending amba_fabric_generator.py\'s real compute_address_regions()/compute_id_width()/build_scoreboard_matrix() with an ID-remap/width-burst-transform DETECTION helper (structural: does the discovered topology imply a transform, not a live prediction against real traffic) + SYOSCB-13 address-map-evidence cross-check reusing address_map_verifier.py directly', predictorAddressScoreboardModelR],
  ['SYOSCB-14/15/16: dynamic scoreboard topology / producer-queue mapping planner extending amba_port_registry.py -- master-endpoint-to-producer-id and destination/ordering-domain-to-queue-id mapping computed FROM the real AMBA_PORT_REGISTRY rows, citing (never guessing) the real SyoSil cfg/cfg_pl API shape the audit read from source', predictorAddressScoreboardModelR],
  ['SYOSCB-17/18: per-protocol compare-strategy policy TABLE (protocol -> starting ordering policy, per SYOSCB-17\'s own list) + a route/master/ID/ordering-domain/burst-aware match-key SCHEMA extending connectivity.py\'s SCOREBOARD_PLAN_FIELDS matching_key/transformation_rules -- schema and default-policy table only, never a real compare against real transactions', compareMatchingTransformBridgeR],
  ['SYOSCB-21/22: the 14-value scoreboard result taxonomy as a real enum/constant module (extending connectivity.py\'s existing constant-table convention, distinct from GateStatus) + per-port visibility counter SHAPE added to the AMBA_PORT_REGISTRY row (all counters start at a real zero/UNKNOWN sentinel, since no real transaction has run)', taxonomyVisibilityModeExistingEnvR],
  ['SYOSCB-29/30: architecture-representation renderer (the SYOSCB-29 tree) + the 29-item Phase-1 report assembler, composing amba_fabric_discovery.py/amba_port_registry.py/amba_scoreboard_env.py\'s existing render_*_report() functions plus this pass\'s own new sections rather than re-rendering any of them a second way', archReportSearchNoAgentR],
]

log('Audit phase complete. Building the Phase-1-only planning/reporting machinery sequentially (dependency order: source-audit/registration -> transaction IR -> route/transform predictor -> scoreboard/producer/queue model -> compare/matching policy -> result taxonomy/visibility -> architecture representation/Phase-1 report), reusing real existing code at every step, never vendoring uvm_syoscb-1.0.2.4 into the repo and never writing real scoreboard/adapter SV code wired into any environment.')

const buildResults = []
for (const [name, report] of buildOrder) {
  const buildResult = await agent(`Working directory: D:/DV/Task/DV_Agent_Harness_L5/v50

## Background

${CONTEXT}

This is a sequential build pass, step **${name}**, installing SYOSCB AMBA scoreboard PLANNING machinery. Prior steps in this same sequence may have already added real code you should build on (check git log/git diff for this session's own recent commits under this same effort before assuming a prerequisite is missing).

NOTE: other agents/workflows may be concurrently active in this repo. Check git status/git diff on any shared file (especially connectivity.py, amba_port_registry.py, amba_fabric_discovery.py, amba_scoreboard_env.py, CLAUDE.md) BEFORE touching it, and use the hand-scoped patch technique (git diff > patch, trim to your hunk, git apply --cached --check then --cached) for EVERY file, never a broad git add.

Its real, current audit finding for this scope (read carefully, this is real evidence gathered just now):

${report}

## Your task

1. If the audit found this already WIRED_AND_FIRING: do nothing, just re-confirm the cited evidence.
2. Otherwise build it for real, reusing existing code (connectivity.py, amba_fabric_discovery.py, amba_port_registry.py, amba_scoreboard_env.py, amba_fabric_generator.py, address_map_verifier.py, knowledge_center.py) per the audit's own concrete recommendation. Prefer extending an existing module directly over a new parallel module UNLESS the audit found the capability is genuinely structurally new -- in that case a new, clearly-scoped module (e.g. dv_harness/syoscb_integration_plan.py) that IMPORTS and composes the existing real primitives is correct, not a copy of their logic.
3. HARD CONSTRAINTS, non-negotiable: (a) never copy, vendor or otherwise write any file from D:/DV/Scoreboard/uvm_syoscb-1.0.2.4 into this repository -- read it read-only for evidence only; (b) never write real SystemVerilog scoreboard/adapter/predictor code that gets wired into any real or generated UVM environment; (c) never invoke or simulate a real VCS/UVM build. A synthetic Python-level fixture used ONLY inside your own new unit test (e.g. a fake AMBA_PORT_REGISTRY) is fine and expected.
4. Write real tests proving your piece actually works, including at least one case where required evidence is genuinely missing (report REQUIRED_HUMAN_INPUT/UNKNOWN honestly rather than only a clean happy path) -- this project's own hard-won lesson is that an untested happy-path-only mechanism is not real coverage.
5. Run the full relevant test suite for whatever you touched and confirm pass.
6. Commit your change for real with a clear, scoped commit.

Write a report to .work/gap-close-syoscb-${name.replace(/[^a-zA-Z0-9]+/g, '-').toLowerCase().slice(0, 40)}-report.md. Report DONE (with what changed) / NO_ACTION_NEEDED / NEEDS_SEPARATE_EFFORT / BLOCKED, with a one-line test summary if you made a change.`, {label: `build:${name}`, phase: 'Build', model: 'claude-opus-5'})
  buildResults.push([name, buildResult])
  log(`Build step done: ${name}`)
}

phase('Review')

const review = await agent(`${CONTEXT}

Independently review this "install AMBA SoC bus multi-master/multi-slave scoreboard planning machinery reusing the real uvm_syoscb-1.0.2.4 source as evidence (SYOSCB-1..30), reuse-first, audit/planning/reporting only" effort. Do not accept any report's own claim without independent re-verification -- run real commands yourself.

Read every audit report and every build-step report in full first (search .work/ for files matching gap-close-syoscb-*-report.md).

Raw returned results, for cross-reference:

### Audits
${[
  ['source-policy', sourcePolicyR], ['role-limits-reuse-protocols', roleLimitsReuseProtocolsR],
  ['adapter-ir-reconstruction', adapterIrReconstructionR],
  ['predictor-address-scoreboard-model', predictorAddressScoreboardModelR],
  ['compare-matching-transform-bridge', compareMatchingTransformBridgeR],
  ['taxonomy-visibility-mode-existing-env', taxonomyVisibilityModeExistingEnvR],
  ['build-baseline-tests-stress', buildBaselineTestsStressR],
  ['arch-report-search-noagent', archReportSearchNoAgentR],
].map(([n, r]) => `#### ${n}\n${r}`).join('\n\n')}

### Build steps
${buildResults.map(([name, result]) => `#### ${name}\n${result}`).join('\n\n')}

Verify independently:
1. For every build step reporting DONE: did it actually work (run its new test yourself), and does its test genuinely cover a missing/unresolved-evidence case, not just a clean happy path?
2. THE MOST IMPORTANT CHECK: confirm nothing in this pass's diff/commit history copied any file out of D:/DV/Scoreboard/uvm_syoscb-1.0.2.4 into the repository (grep the diffs for any path containing "syoscb" landing under v50/ or elsewhere in the repo, and confirm D:/DV/Scoreboard itself was never written to), and confirm nothing wrote real SystemVerilog scoreboard/adapter/predictor code wired into any real or generated UVM environment, and confirm no real VCS/UVM build was invoked. This effort's hard constraint was audit/planning/reporting ONLY -- flag any violation as CRITICAL.
3. Confirm no parallel/duplicate scoreboard-plan schema was built where connectivity.py's real SCOREBOARD_PLAN_FIELDS / amba_port_registry.py's real 19-field registry should have been extended instead.
4. Confirm no new autonomous top-level "scoreboard agent" was created anywhere (SYOSCB-32) -- re-check .claude/agents/ yourself.
5. Actually exercise whatever new Python tooling this pass added, end to end against a real or synthetic AMBA_PORT_REGISTRY, and confirm it produces the SYOSCB-29 architecture representation and a SYOSCB-30-shaped Phase-1 report (or names concretely which of the 29 items remain unaddressed and why).
6. Run the full project test suite (python -m pytest dv_harness_tests/ -q) and report the real pass/fail count.
7. Check git hygiene across all commits this pass made.
8. Re-confirm for yourself (do not just trust the audit) that D:/DV/Scoreboard/uvm_syoscb-1.0.2.4 is real and was only ever read, never modified or copied, by running your own read-only check against it.

Report a clear verdict per SYOSCB sub-area (GENUINELY_CLOSED / STILL_GAP / CORRECTLY_DEFERRED-per-SYOSCB-33/34) plus an overall verdict (APPROVED / NEEDS_FIX), with concrete evidence-cited findings. Be exhaustive about the no-vendoring / no-real-SV / no-real-build boundary check specifically -- that is this effort's single most important safety constraint.`, {label: 'review', phase: 'Review', model: 'claude-opus-5'})

return {
  audits: {
    sourcePolicyR, roleLimitsReuseProtocolsR, adapterIrReconstructionR, predictorAddressScoreboardModelR,
    compareMatchingTransformBridgeR, taxonomyVisibilityModeExistingEnvR, buildBaselineTestsStressR,
    archReportSearchNoAgentR,
  },
  buildResults: Object.fromEntries(buildResults),
  review,
}
