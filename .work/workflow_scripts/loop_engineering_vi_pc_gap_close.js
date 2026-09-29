export const meta = {
  name: 'loop-engineering-vi-pc-gap-close',
  description: 'Close the confirmed real gaps from the LOOP_ENGINEERING, VERIFICATION_INTELLIGENCE, and PRODUCTION_COMPLETE master-prompt completeness audits -- real implementation, explicitly authorized by the user',
  phases: [
    { title: 'Build', detail: 'sequential, reuse-first close pass' },
    { title: 'Review', detail: 'independent re-verification' },
  ],
}

const CONTEXT = `
This closes confirmed real gaps from three fresh, thorough completeness audits
run earlier this session against D:/DV/Task/DV_Agent_Harness_L5/v50/, each
against one of the master-prompt family's newest members:
CLAUDE_DV_Agent_Harness_L5_ULTIMATE_COMPLETE_LOOP_ENGINEERING.md,
..._VERIFICATION_INTELLIGENCE.md, and ..._PRODUCTION_COMPLETE.md.

Every audit's own document ends with an explicit human-approval-required stop
condition ("IMPLEMENTATION NOT STARTED / AWAITING USER APPROVAL"). The user has
now explicitly authorized implementation of the gaps below in this session
("開啟多個Agent 將所有缺口和問題都補上實做").

This project has an extremely strong, repeatedly-enforced norm against
building parallel/duplicate mechanisms (see CLAUDE.md's "Methodology
Consolidation Rule"). Before building anything, independently re-verify the
gap is real with your own grep/read commands (audits can go stale between
being written and being closed) and find the closest existing real mechanism
to extend, per CLAUDE.md's own "SEARCH EXISTING L5 FIRST... default ENHANCE"
policy quoted throughout this file. Read the relevant section(s) of
D:/DV/Task/DV_Agent_Harness_L5/v50/CLAUDE.md first in every close-pass --
it documents in detail which of these mechanisms already exist (e.g. Status
enum at dv_harness/models.py:74, retry/budget in engine.py and config.py,
trend_analysis.py's day-over-day detectors, question_queue.py's 4 metrics,
preflight.py's license/queue checks, capability_evolution.py's 11-state
machine and its new run_controlled_experiment()) so you extend rather than
duplicate.

Check git status/git diff before touching any shared file (dv_harness/models.py,
dv_harness/engine.py, dv_harness/config.py, dv_harness/dashboard.py,
dv_harness/capability_evolution.py, dv_harness/cli.py -- other close-passes in
this same sequential loop touch these too) -- use the hand-scoped patch
technique (git diff > patch, trim to your hunk, git apply --cached --check
then --cached) rather than a broad git add.

CRITICAL, non-negotiable across every gap below: never weaken any existing
human-approval gate (HumanApprovalRequiredError, ProductionWriteNotAuthorizedError,
ControlPlane.approve(), policy.can_signoff(), the PR-only main/master
governance). Never trigger a real production build/regression/LSF submission
as part of closing any of these gaps -- test only against synthetic/local
fixtures. If a gap turns out to be a much larger effort than expected once
you're in the code (this is likely for several of these -- they are large,
cross-cutting capabilities), scope down to a real, honest, smaller-but-still-
genuine version rather than leaving it half-built, and report EXACTLY what you
built vs. deferred. A well-scoped-down real mechanism beats an overreaching
half-built one.

Do NOT touch dv_harness/golden_flow_readiness.py -- that gap is being closed by
a separate, already-running close-pass this session; building it here would
collide.
`

phase('Build')

const gaps = [
  // --- LOOP_ENGINEERING gaps ---
  `LOOP-1 (LoopContract schema + loop state machine extension): LOOP_ENGINEERING.md
   section 85 requires a LoopContract YAML/dataclass schema (loop_id, loop_type,
   owner, budgets, convergence, plateau, oscillation, termination, etc.) --
   confirmed zero hits repo-wide for "LoopContract"/"loop_contract". Section 86
   requires a canonical loop state machine (CREATED->READY->RUNNING->VERIFYING->
   CONVERGING/PLATEAU/OSCILLATING/RETRY_WAIT/BLOCKED/HUMAN_GATE->SUCCESS/FAILED/
   BUDGET_EXHAUSTED/STOPPED/CANCELLED, +RESUMING/STALE) -- the real
   dv_harness/models.py:74 Status enum (NOT_STARTED/RUNNING/PASS/FAIL/PARTIAL/
   BLOCKED/RETRY/WAIT_USER/CLOSED/ACCEPTED_RISK) genuinely covers HUMAN_GATE (via
   WAIT_USER) but has zero PLATEAU/OSCILLATING/BUDGET_EXHAUSTED/CANCELLED/
   RESUMING states (grep confirms 0 hits for BUDGET_EXHAUSTED repo-wide). Build a
   real dv_harness/loop_contract.py dataclass/schema that the three existing loop
   drivers (engine.py, memory_router.py, capability_evolution.py) can populate
   from their own existing state, and extend the state vocabulary (a new
   LoopState enum feeding into or alongside Status, since Status already serves
   stage-gate semantics the new values do not all apply to -- your call on the
   cleanest integration once you've read models.py and engine.py's usage of
   Status). This is foundational for LOOP-2 and LOOP-4 below -- do this one
   first.`,

  `LOOP-2 (Convergence + Plateau + Oscillation detection): LOOP_ENGINEERING.md
   sections 88-90 require classifiers for coverage convergence
   (CONVERGING/SLOW_CONVERGENCE/NO_PROGRESS/PLATEAU/REGRESSION/OSCILLATING/
   UNKNOWN), plateau detection (unreachable bins/stimulus-gap investigation), and
   oscillation/no-progress detection (fingerprint-based repeat-failure/
   repeat-fix-revert). Confirmed NEVER_BUILT -- grep for "plateau"/"oscillat"
   across all .py files returns only unrelated hardware clock-oscillator hits in
   amba_fabric_analysis.py and canfd_arbitration_generator.py. Real, reusable raw
   material exists: dv_harness/trend_analysis.py's detect_pattern_regressions(),
   detect_runtime_anomalies(), day_over_day() do real day-over-day LSF/regression
   trend deltas. Build real classifiers that reuse trend_analysis.py's data
   rather than re-deriving it, emitting the LOOP-1 state values (PLATEAU/
   OSCILLATING/etc.) when detected. Note: capability_evolution.py's
   repeated_unresolved_failure_patterns() (closed today for a different, narrower
   gap -- cross-loop coupling) is adjacent but purpose-built for filing a
   capability candidate, not for this generic loop classifier -- reuse its
   signature-matching approach/utilities where sensible, don't just call it.`,

  `LOOP-3 (Unified Loop Budget Engine + failure-type taxonomy + circuit breaker):
   LOOP_ENGINEERING.md sections 91/93 require a unified budget engine (wall time,
   LSF jobs, license usage, token cost, failed experiments -- spanning all three
   loops, with exhaustion VISIBLE and never silently reset) and a failure-type
   taxonomy (TRANSIENT/DETERMINISTIC/RESOURCE/LICENSE/ENVIRONMENT/TEST/DUT/
   VIP/INFRASTRUCTURE/UNKNOWN) feeding a circuit breaker. Confirmed
   PARTIALLY_WIRED/NEVER_BUILT: real scattered budgets exist
   (config.py:38 inner_react_max_iterations, engine.py's max_stage_retries,
   context_budget.py's MAX_PACK_BYTES) but no unified engine; zero hits for
   "circuit_breaker" repo-wide; only one unrelated "TRANSIENT" hit
   (connectivity.py:3287, a docstring). Build a real, unified budget-tracking
   mechanism (reusing the existing scattered budgets as its inputs, not
   replacing them) and a real failure-classifier module the existing retry logic
   in engine.py can call to decide retry-vs-stop, wired to trip into the
   LOOP-1 BUDGET_EXHAUSTED state on exhaustion. Also closes the adjacent
   LOOP_ENGINEERING section 92 gap (license-aware PRIORITIZATION/deferral of
   low-value work under a real preflight.py-derived resource-pressure signal --
   the existing check-before-submit half is already real in preflight.py, only
   the prioritization half is missing).`,

  `LOOP-4 (Loop telemetry events + GUI Loop Engineering Center): LOOP_ENGINEERING.md
   section 108 names 19 specific loop telemetry event types (LOOP_CREATED,
   LOOP_PLATEAU_DETECTED, LOOP_BUDGET_EXHAUSTED, etc.) -- confirmed 0/19 exist
   anywhere in the real events.jsonl producers. Section 107 requires a GUI Loop
   Engineering Center (a Loop | State | Iteration | Verified Gain | Budget |
   Plateau | Oscillation | Next Action table with drill-down) -- confirmed
   dashboard.py's only "loop" hits are the pre-existing single-run/continuous-run
   toggle (dashboard.py:333, ~2576-3279), not an observability table. This gap
   depends on LOOP-1/LOOP-2/LOOP-3 already having landed (read their reports in
   .work/ first, or re-check git log, before starting) -- emit the real named
   events from StateStore.event() (dv_harness/storage.py:64, the SAME
   .dv-harness/events.jsonl every other subsystem this session writes to) at the
   real transition points LOOP-1/2/3 added, and add a real dashboard card
   reading them, following dashboard.py's existing card/endpoint conventions
   (read the GUI-09/10/11 cards added earlier this session for the pattern to
   match). Read dv_harness/dashboard.py's git log from today first to see the
   established convention for these new cards. Honest empty state if a loop
   never fires the events, never fabricated data.`,

  // --- VERIFICATION_INTELLIGENCE gaps (5 NEVER_BUILT) ---
  `VI-1 (Confidence Calibration Engine): VERIFICATION_INTELLIGENCE.md's completeness
   audit flagged this NEVER_BUILT. Confirm independently first (grep for
   "calibrat" across the repo). The real dv_harness/inference.py
   score_confidence() already produces a confidence tier (LOW/MEDIUM/HIGH/
   CONFIRMED per qualified_conclusion.py) for root-cause conclusions -- a
   calibration engine's job is to check, over real historical
   verified/rejected outcomes (Engineering/Organizational Memory records,
   already real per memory.py), whether a given confidence tier's stated
   reliability actually matches its real track record, and surface a
   calibration report/adjustment when it doesn't. Build a real, honest module
   that computes this from real MemoryStore records (never synthetic data
   presented as real), with an honest "insufficient history" result when too
   few verified/rejected records exist yet to calibrate against (this repo's
   own real history may well be exactly this case -- report the honest
   NOT_AVAILABLE/insufficient-data state if so, rather than fabricating a
   calibration off too little evidence).`,

  `VI-2 (Cross-Project Pattern Mining): NEVER_BUILT per the audit. Confirm
   independently first. The real per-project Engineering/Organizational Memory
   tiers (memory.py, memory_router.py) and the Vault (memory_vault.py) already
   accumulate verified root-cause/fix knowledge -- but this project's harness has
   no multi-project registry to mine ACROSS (single project, single repo, as
   CLAUDE.md's own "Environment Generation Mode" section discloses for a
   related mechanism -- "this harness repo itself has no RTL tree of its own").
   Build the real MECHANISM (a real cross-project pattern-mining function that
   would, given N real per-project memory stores, surface recurring
   root-cause/fix patterns across them) honestly scoped to what this repo can
   actually prove: test it against multiple real (not fabricated) memory-store
   fixtures you construct for the test, and report honestly that no second real
   project exists yet to mine in production -- do not synthesize a second fake
   "project" against this repo's own real audit trail to manufacture a
   production-looking result.`,

  `VI-3 (Shadow / Digital-Twin Validation): NEVER_BUILT per the audit. Confirm
   independently first (grep for "shadow"/"digital_twin"/"digital twin"). This is
   likely the largest-scope item in this whole close-pass -- read the relevant
   VERIFICATION_INTELLIGENCE.md section in full (search the file for "shadow" or
   "twin") before starting, to understand exactly what's specified. If, once you
   understand the real scope, it requires infrastructure this repo cannot
   honestly stand up (e.g. an actual parallel/shadow simulation environment),
   scope down to the real, bounded, genuinely-buildable slice -- e.g. a real
   comparison/diff mechanism between two independently-produced evidence sets
   for the same DUT state, reusing engine.py's existing stage-runner and
   evidence_db.py's real evidence store rather than inventing a parallel
   evidence system -- and report clearly what you built vs. what remains
   genuinely out of reach without real hardware/license resources this repo does
   not have. A clear, honest BLOCKED-with-reasoning report is a valid, useful
   outcome for this specific gap if the real scope demands resources unavailable
   here.`,

  `VI-4 (Verification Strategy Optimizer): NEVER_BUILT per the audit -- a
   mechanism to recommend which verification strategy (simulation vs. formal vs.
   PSS vs. emulation/ZeBu vs. HAPS) fits a given verification goal. Confirm
   independently first. This repo's real, provable capability is simulation-based
   (LSF/VCS regression, per lsf_client.py/preflight.py) -- there is no real
   formal/PSS/emulation backend integrated anywhere in this harness (confirm via
   grep before assuming). Build a real, honestly-scoped recommendation module
   that reasons over real signals this harness DOES have (coverage-closure
   difficulty from trend_analysis.py, bug/failure density from evidence_db.py,
   protocol_capability.py's real per-protocol capability status) to recommend a
   strategy, but must NOT claim it can actually dispatch to a formal/PSS/
   emulation backend that does not exist here -- the recommendation output must
   honestly name which strategies this harness can currently execute
   (simulation) vs. which it can only recommend-in-principle (formal/PSS/
   emulation), never presenting a recommendation as an executable capability
   this harness lacks.`,

  `VI-5 (Global Resource / License Orchestrator): NEVER_BUILT per the audit,
   overlapping LOOP-3's license-prioritization half above -- coordinate with
   that gap (read its report/diff first if it has already landed by the time you
   start, to avoid duplicating the same preflight.py-derived prioritization
   logic). This item's distinguishing scope beyond LOOP-3 is GLOBAL
   cross-project/cross-job resource orchestration (deciding across MULTIPLE
   concurrent jobs/projects which gets license/queue priority), not just a
   single loop's own budget awareness. Confirm independently what's real today:
   preflight.py's check_license()/check_queue_health() (real lmutil/bqueues
   parsing) and lsf_client.py's submission gating are real per-job checks with
   no cross-job arbitration. Build a real orchestrator module that reuses these
   existing real checks as its data source and adds the missing cross-job
   priority-ranking/deferral decision, honestly scoped to what can be tested
   without a real multi-job LSF farm (use fixture/mock LSF state for the test,
   clearly labeled as such).`,

  // --- PRODUCTION_COMPLETE gaps (9 NEVER_BUILT) ---
  `PC-1 (Schema-compatibility classifier): NEVER_BUILT per the audit. Confirm
   independently first (grep for "schema_compat"/"backward_compat" across the
   repo -- note env_manifest.py's "schema 1.1" versioning and env_manifest
   schema.json's REQUIRED-key breaking-bump precedent, which is the real prior
   art to follow the shape of, not duplicate). Build a real classifier that,
   given two versions of one of this project's real JSON-schema-backed artifacts
   (env.manifest.json, capability_evolution_candidate.schema.json, the
   connectivity manifest, etc.), classifies the change as
   BACKWARD_COMPATIBLE/BREAKING/UNKNOWN by comparing the actual schema files
   (added optional field vs. removed/retyped required field, etc.) -- reusing
   Python's/jsonschema's real schema introspection, never a hand-rolled diff
   heuristic pretending to understand JSON Schema semantics it doesn't actually
   check.`,

  `PC-2 (Platform observability + SLO/error-budget + platform health-state):
   three related NEVER_BUILT items from the audit -- group them, they share one
   real underlying data source. Confirm independently first (grep for
   "SLO"/"error_budget"/"health_state" across the repo). Real, scattered signals
   this harness already produces: StateStore.event()'s real events.jsonl audit
   trail, trend_analysis.py's regression/runtime anomaly detection,
   preflight.py's license/queue health checks, connectivity_check.py's gate
   statuses. Build a real, honest platform-health aggregator that reads these
   EXISTING real sources (never inventing new synthetic metrics) into a
   health-state summary (e.g. HEALTHY/DEGRADED/CRITICAL per subsystem) and a
   real SLO/error-budget tracker for one concrete, already-measurable SLO this
   harness can honestly compute today (e.g. stage-gate PASS rate over a rolling
   window, from real evidence_db.py data) -- do not fabricate SLOs for
   capabilities (uptime, latency) this harness has no real telemetry for.`,

  `PC-3 (Change-budget / blast-radius gate): NEVER_BUILT per the audit. Confirm
   independently first (grep for "blast_radius"/"change_budget"). The real
   prior art to extend, not duplicate: git_governance.py's existing
   main/master push-protection gate, and the gh/PR-only governance policy
   documented in CLAUDE.md. Build a real gate that estimates a change's
   "blast radius" from real signals (files touched, whether they're shared
   across subsystems per this project's own module dependency structure,
   whether the change touches a gate/policy file itself) and requires
   additional real confirmation/review above some threshold -- wire it as an
   additional check alongside (never replacing) the existing git-guard hooks,
   never weakening their existing behavior.`,

  `PC-4 (Mutation testing / bug injection): NEVER_BUILT per the audit. Confirm
   independently first (grep for "mutation_test"/"bug_inject"). Build a real,
   bounded mutation-testing harness scoped to this project's OWN Python test
   suite (dv_harness_tests/) -- e.g. reusing or wrapping a real, standard
   mutation-testing approach (AST-level small mutations: flip a comparison
   operator, off-by-one a boundary constant) applied to a small, explicitly
   chosen real dv_harness/*.py module, run against that module's real existing
   test file, reporting real mutants killed/survived. This is explicitly
   testing-infrastructure-on-this-repo's-own-code, never DUT/RTL-level fault
   injection (which would need a real RTL/simulation target this repo does not
   have) -- scope it there and say so in your report.`,

  `PC-5 (Dependency / supply-chain governance): NEVER_BUILT per the audit.
   Confirm independently first (grep for "supply_chain"/"dependency_audit").
   Build a real module that inventories this project's actual real
   dependencies (pyproject.toml, any requirements files, VIP
   package/version info already surfaced by env_manifest.py's
   scan_designware_home()) and checks them against a real, simple policy
   (e.g. pinned-version enforcement, a real vulnerability-advisory lookup if a
   real offline-checkable source is available, otherwise an honest
   NOT_AVAILABLE for that specific check rather than a fabricated clean
   result) -- never claim a security scan happened when no real check ran.`,

  `PC-6 (Multi-user ownership / authorization matrix): NEVER_BUILT per the
   audit. Confirm independently first (grep for "ownership_matrix"/
   "authorization_matrix"). Real prior art to extend: the GUI-19 per-session
   token gate added earlier this session (dashboard.py, commit 08a61df) is a
   real authentication mechanism but has no per-ACTION per-ROLE authorization
   matrix (who may APPROVE vs. who may only VIEW). Build a real, minimal
   role/permission matrix (e.g. VIEWER/OPERATOR/APPROVER) that the existing
   GUI-19 token-gate mechanism can consult before allowing a mutating action,
   reusing that gate's existing token infrastructure rather than building a
   parallel auth system -- read dashboard.py's real GUI-19 implementation
   first (git show 08a61df) before starting. Write a real test proving a
   VIEWER-role token is rejected on a mutating endpoint a real APPROVER-role
   token is accepted on.`,
]

log(`Building ${gaps.length} confirmed gaps sequentially (many share dv_harness/models.py, engine.py, dashboard.py, capability_evolution.py -- strictly sequential to avoid collisions).`)

const closeResults = []
for (const [i, name] of gaps.entries()) {
  const label = name.slice(0, name.indexOf(':')).trim() || `gap-${i}`
  const fixResult = await agent(`Working directory: D:\\DV\\Task\\DV_Agent_Harness_L5\\v50

## Background

${CONTEXT}

You are handling exactly ONE gap: **${name}**

Read D:/DV/Task/DV_Agent_Harness_L5/v50/CLAUDE.md first (at least the sections
relevant to your gap's neighboring mechanisms) to understand what already
exists and avoid duplicating it. Check git status/git diff on any file you
plan to touch FIRST -- other close-passes in this same sequential loop may
have already changed shared files (dv_harness/models.py, engine.py,
dashboard.py, capability_evolution.py, cli.py, config.py). Re-read fresh if
so, and use the hand-scoped patch technique (git diff > patch, trim to your
hunk, git apply --cached --check then --cached) rather than a broad git add.

## Your task

1. Independently re-verify this gap is real (grep/read) before building --
   audits can go stale.
2. Build the real mechanism described above for your gap, reusing existing
   real code wherever named -- never a parallel/duplicate mechanism.
3. Preserve every existing human-approval gate exactly as-is. Never trigger a
   real production build/regression/LSF submission as part of closing this
   gap -- test only against synthetic/local fixtures.
4. Write real tests proving the mechanism works, not just that an isolated
   function returns a value.
5. Run the full relevant test suite for what you touched and confirm pass.
6. Commit your change for real with a clear, scoped commit message.
7. If this gap is a much larger effort than expected once you're in the
   code, scope down to a real, honest, smaller-but-still-genuine version
   (or a clearly-reasoned BLOCKED, for VI-3 specifically if warranted)
   rather than leaving something half-built or fabricating a result --
   report exactly what you built vs. deferred and why.

Write a report to .work/gap-close-final-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}-report.md.
Report DONE / PARTIAL / BLOCKED, with a one-line test summary.`, {label: `close:${label}`, phase: 'Build', model: 'claude-opus-5'})
  closeResults.push([label, fixResult])
  log(`Closed pass done for ${label}.`)
}

phase('Review')

const review = await agent(`Independently review this "close the LOOP_ENGINEERING + VERIFICATION_INTELLIGENCE + PRODUCTION_COMPLETE gaps" effort for DV Agent Harness L5. Do not accept any report's own claim without independent re-verification -- run real commands yourself.

Read every close-pass report in full first (search .work/ for files matching gap-close-final-*-report.md).

Raw returned results, for cross-reference:
${closeResults.map(([name, result]) => `#### ${name}\n${result}`).join('\n\n')}

Verify independently:
1. For every close-pass reporting DONE or PARTIAL: did the fix actually work, verified by you running something real (tests, a real function call, a real dashboard hit if applicable)?
2. CRITICAL top-priority check across ALL gaps: grep every diff this pass made for any change to HumanApprovalRequiredError/ProductionWriteNotAuthorizedError/ControlPlane.approve/policy.can_signoff/git-guard main-master-protection logic -- confirm none were weakened. Confirm no gap triggered a real production build/regression/LSF submission.
3. Spot-check at least 3 of the "NEVER_BUILT" claims independently (your own grep) to confirm they really were absent before this pass started (via git log/diff), not already-real mechanisms an agent duplicated.
4. Run the full project test suite (python -m pytest dv_harness_tests/ -q) and report the real pass/fail count.
5. Check git hygiene across all commits this pass made (scoped commits, no stray unrelated file bundling, no secrets).

Report a clear verdict per gap (GENUINELY_CLOSED / PARTIALLY_CLOSED / STILL_GAP / HONESTLY_BLOCKED) plus an overall verdict (APPROVED / NEEDS_FIX), with concrete evidence-cited findings.`, {label: 'final-review', phase: 'Review', model: 'claude-opus-5'})

return { closeResults: Object.fromEntries(closeResults), review }
