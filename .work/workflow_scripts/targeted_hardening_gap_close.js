export const meta = {
  name: 'targeted-hardening-gap-close',
  description: 'Close the confirmed real gaps from the TARGETED_HARDENING (sections 217-247) completeness audit -- real implementation, explicitly authorized by the user',
  phases: [
    { title: 'Build', detail: 'sequential, reuse-first close pass' },
    { title: 'Review', detail: 'independent re-verification' },
  ],
}

const CONTEXT = `
This closes confirmed real gaps from a fresh, thorough completeness audit run
earlier this session against D:/DV/Task/DV_Agent_Harness_L5/v50/, covering
sections 217-247 ("TARGETED FINAL HARDENING EXTENSIONS") of
D:/DV/Task/DV_Agent_Harness_L5/CLAUDE_L5_SPEC_TO_SYSTEM_UVM_TARGETED_HARDENING.md.
That document's own final section ends with the explicit human-approval-required
stop condition ("IMPLEMENTATION NOT STARTED UNLESS EXPLICITLY APPROVED /
AWAITING USER REVIEW / APPROVAL"). The user has now explicitly authorized
implementation of the gaps below in this session
("開啟多個Agent 將所有缺口和問題都補上實做").

This project has an extremely strong, repeatedly-enforced norm against
building parallel/duplicate mechanisms (CLAUDE.md's "Methodology
Consolidation Rule"). Before building anything, independently re-verify the
gap is real with your own grep/read commands (audits can go stale) and find
the closest existing real mechanism to extend. Read
D:/DV/Task/DV_Agent_Harness_L5/v50/CLAUDE.md first in every close-pass.

Check git status/git diff before touching any shared file (dv_harness/gates.py,
dv_harness/dashboard.py, dv_harness/waiver_store.py, dv_harness/signoff_export.py,
dv_harness/coverage_analysis.py, tools/verification_flow/*_gate.py,
dv_harness/cli.py -- a separate concurrently-running close-pass this session
also touches dashboard.py, capability_evolution.py, engine.py, models.py) --
use the hand-scoped patch technique (git diff > patch, trim to your hunk,
git apply --cached --check then --cached) rather than a broad git add.

CRITICAL, non-negotiable: never weaken any existing human-approval gate or
governance boundary. Never trigger a real production build/regression/LSF
submission -- test only against synthetic/local fixtures. If a gap is a much
larger effort than expected once you're in the code (very likely for the
low-power and UVM-lint items especially), scope down to a real, honest,
smaller-but-still-genuine version rather than leaving it half-built, and
report EXACTLY what you built vs. deferred.
`

phase('Build')

const gaps = [
  `TH-1 (UVM Structural Lint, section 220): confirmed NEVER_BUILT -- no
   deterministic pre-simulation parser lint of GENERATED UVM code exists.
   verible_parser.py parses RTL only; bind_verification_lint.py lints report
   TEXT, not UVM source. Build a real, bounded structural lint that parses
   the UVM code this project's own generator (dv_harness/uvm_generator/*)
   produces (or a real example under examples/generated_*_uvm_env/) and
   checks for real, checkable structural defects: factory registration
   (uvm_component_utils/uvm_object_utils present for every component class),
   phase-method signature correctness, config_db set/get path consistency
   (a get with no matching set anywhere, or vice versa), TLM port/export
   connection completeness (a port declared but never .connect()'d),
   objection raise/drop balance in run_phase. Reuse env_manifest.py's
   verible-based parsing approach rather than hand-rolling a second SV
   parser if verible is usable for this; if not, scope to a regex/AST-lite
   check for a clearly-documented subset and say so honestly. Write real
   tests against a real generated example environment (or a small synthetic
   UVM fixture you construct) with both a clean pass and an injected defect
   that the lint catches.`,

  `TH-2 (Low-Power Integration, section 224): confirmed NEVER_BUILT -- no
   UPF/power-intent extraction, isolation/retention/clock-gating/wake-up
   checking exists anywhere (reset_clock_power_sequence_gate.py and
   reset_power_cdc_corner_gate.py are self-attested reset/CDC checks, not
   power-intent). This project has no real UPF file or low-power DUT of its
   own. Scope honestly: build a real UPF-parsing/power-intent-extraction
   module (a real, minimal UPF file parser -- UPF is a documented, stable
   Tcl-based format, parse a real bounded subset: create_power_domain,
   set_isolation, set_retention, create_supply_port/net) that can extract a
   structured power-intent model from a REAL synthetic UPF fixture you
   construct for the test (clearly labeled as a test fixture, not a real
   DUT's UPF). If integrating this into an actual gate/check is out of
   reach without a real low-power DUT, stop at the parser + structured model
   and report that honestly as the real, bounded scope achieved -- do not
   fabricate a gate that "checks" power intent against nothing.`,

  `TH-3 (Golden Scenario / Reference Capsule, section 225): confirmed
   NEVER_BUILT, and confirmed DISTINCT from golden_flow_readiness.py (a
   different mechanism despite the similar name) and from
   CAT_KNOWN_GOOD_SUBSYSTEM_TESTS. Build a real, minimal "golden scenario"
   store: a schema for a proven-good test/scenario record (protocol, test
   name, last-verified-PASS git SHA + date, the real evidence_db record it
   was verified against, a freshness/staleness flag derived from real git
   history -- e.g. STALE if the DUT RTL or VIP config has changed since the
   recorded SHA). Reuse evidence_db.py's real evidence store as the backing
   data source rather than inventing a parallel evidence format. Write a
   real test that records a golden scenario against a real (synthetic
   fixture) evidence_db entry, then detects staleness after a simulated RTL
   change.`,

  `TH-4 (Agent Benchmark Dataset Governance, section 226): confirmed
   NEVER_BUILT -- capability_evolution.run_controlled_experiment() is
   per-candidate execution, not a versioned eval corpus. Build a real,
   minimal benchmark-dataset registry: a versioned set of real
   (synthetic/fixture, clearly labeled) test cases with expected
   outcomes, a way to run an agent/mechanism against the current version
   of the dataset and record pass/fail per case, and basic train/test
   leakage tracking (has this exact case ever been used to tune the thing
   being evaluated). Reuse run_controlled_experiment()'s isolated-fixture
   execution approach as the runner, don't build a second one. Write a real
   test proving a dataset version bump is detected and an eval run against
   two different dataset versions produces two distinguishable results.`,

  `TH-5 (Configuration Variant Explosion Control, section 232): confirmed
   NEVER_BUILT -- regression_tiers.py/change_impact.py answer "which tests
   to run", never "which config combinations to cover" out of a combinatorial
   space. Build a real pairwise (or n-wise, your call once you're in the
   code -- pairwise is almost certainly the right honest scope) config
   combination selector: given a real set of named config dimensions and
   their legal values (e.g. from this project's own manifest/config schema
   shapes), generate a reduced covering set of combinations guaranteeing
   every pairwise value combination appears at least once, rather than the
   full cross product. Use a real, standard pairwise-coverage algorithm
   (not a fabricated heuristic) -- cite which one you used and why. Write a
   real test proving the reduced set achieves full pairwise coverage against
   a real small config-dimension fixture, and is meaningfully smaller than
   the full cross product for a non-trivial dimension count.`,

  `TH-6 (Multi-user coordination detection, section 239): confirmed
   NEVER_BUILT for detection specifically -- the transport/auth layer
   (USAGE_MULTI_USER_SAFETY.md's rules, GUI-19's dashboard_auth.py token
   gate) is real and this gap does NOT ask you to touch that. Build real
   detectors for: (a) stale-SHA conflict (two users' in-flight work based on
   different git SHAs touching the same file), (b) duplicate-regression
   submission (two users about to submit the same regression/pattern against
   the same commit), (c) shared-resource reservation conflict (two users'
   concurrent work claiming the same AMBA fabric port / VIP instance /
   license-scarce resource). Reuse existing real per-project state
   (state.json, events.jsonl, the AgentTaskStore.acquire() claim mechanism
   already used for parallel_group fan-out) as your data source rather than
   inventing a new coordination store. This is inherently a
   multi-session/multi-user scenario -- construct a real test with two
   simulated concurrent sessions/state snapshots to prove detection fires.`,

  `TH-7 (Waiver Expiration / Revalidation, section 237): confirmed
   PARTIALLY_WIRED -- dv_harness/waiver_store.py exists with a schema
   mismatch against the document's status vocabulary, and 3 real gates
   (waiver_revalidation_gate.py and 2 others -- grep for "waiver" across
   tools/verification_flow/) exist but are DISCONNECTED from the store (per
   the store's own docstring, which already discloses this). Wire them
   together: the store should be the real source of truth the gates read
   from (not a separate self-attested check), and align the store's status
   vocabulary with what section 237 and the existing gates actually need.
   This is a wiring/integration task more than new-mechanism-building --
   scope it as such. Write a real test proving a waiver recorded in the
   store is read and enforced by the real gate (an expired waiver causes the
   gate to correctly re-flag the issue it was waiving).`,

  `TH-8 (Signoff Freeze / Baseline, section 238): confirmed PARTIALLY_WIRED
   -- dv_harness/signoff_export.py is a real gate-aware bundle+hash export
   but is missing most of section 238's named fields and has no post-freeze
   invalidation trigger (something changing after a signoff was frozen
   should be detectable). Extend signoff_export.py (never build a parallel
   exporter) with the missing fields and a real invalidation check (compare
   a frozen bundle's recorded hashes/SHAs against current real state; flag
   INVALIDATED if they diverge). Write a real test: freeze a signoff bundle
   against a synthetic fixture, then change the fixture, then confirm the
   invalidation check fires.`,

  `TH-9 (Self-attested vs. independently-derived gate evidence -- the
   audit's own flagged "most consequential gap type"): several real gates
   (system_level_deadlock_livelock_gate.py, system_level_resource_contention_gate.py,
   per_port_queue_starvation_gate.py, and others named in the audit) accept
   a fenced JSON evidence block an AGENT typed, with no independent
   derivation -- meaning a headline claim like "deadlock freedom" can
   currently be produced by an agent's own unverified assertion. This is a
   genuine, disclosed risk, not a clean single-file gap -- your job is NOT
   to build a formal deadlock checker (out of reach without a real formal
   tool), but to make the SELF-ATTESTED nature of this evidence impossible
   to silently mistake for independently-derived evidence: add a real,
   enforced \`evidence_provenance\` field (values like
   AGENT_SELF_ATTESTED / TOOL_DERIVED / SIMULATION_DERIVED) to the shared
   gate-evidence schema these gates use, require it to be present, and make
   dashboard.py / signoff_export.py / any summary view render
   AGENT_SELF_ATTESTED evidence with a clearly visible caveat rather than
   presenting it identically to tool-derived evidence. Read
   tools/verification_flow/*_gate.py first to find the real shared schema
   these gates already use, and extend that, never invent a parallel one.
   Write a real test proving a gate lacking evidence_provenance is rejected,
   and that an AGENT_SELF_ATTESTED result renders its caveat in at least one
   real consumer (dashboard.py or signoff_export.py).`,
]

log(`Building ${gaps.length} confirmed TARGETED_HARDENING gaps sequentially (several share dv_harness/gates.py, dashboard.py, waiver_store.py, signoff_export.py -- strictly sequential to avoid collisions, and a SEPARATE concurrently-running close-pass this session also touches dashboard.py/capability_evolution.py/engine.py).`)

const closeResults = []
for (const [i, name] of gaps.entries()) {
  const label = name.slice(0, name.indexOf(':')).trim() || `gap-${i}`
  const fixResult = await agent(`Working directory: D:\\DV\\Task\\DV_Agent_Harness_L5\\v50

## Background

${CONTEXT}

You are handling exactly ONE gap: **${name}**

Read D:/DV/Task/DV_Agent_Harness_L5/v50/CLAUDE.md first (at least the sections
relevant to your gap's neighboring mechanisms). Check git status/git diff on
any file you plan to touch FIRST -- other close-passes in this same
sequential loop, AND a separate concurrently-running workflow this session
(touching dashboard.py, capability_evolution.py, engine.py, models.py,
loop_budget.py, confidence_calibration.py, cross_project_mining and others),
may have already changed shared files. Re-read fresh if so, and use the
hand-scoped patch technique (git diff > patch, trim to your hunk, git apply
--cached --check then --cached) rather than a broad git add.

## Your task

1. Independently re-verify this gap is real (grep/read) before building.
2. Build the real mechanism described above, reusing existing real code
   wherever named -- never a parallel/duplicate mechanism.
3. Preserve every existing human-approval gate exactly as-is. Never trigger a
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

Write a report to .work/gap-close-th-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}-report.md.
Report DONE / PARTIAL / BLOCKED, with a one-line test summary.`, {label: `close:${label}`, phase: 'Build', model: 'claude-opus-5'})
  closeResults.push([label, fixResult])
  log(`Closed pass done for ${label}.`)
}

phase('Review')

const review = await agent(`Independently review this "close the TARGETED_HARDENING gaps" effort for DV Agent Harness L5. Do not accept any report's own claim without independent re-verification -- run real commands yourself.

Read every close-pass report in full first (search .work/ for files matching gap-close-th-*-report.md).

Raw returned results, for cross-reference:
${closeResults.map(([name, result]) => `#### ${name}\n${result}`).join('\n\n')}

Verify independently:
1. For every close-pass reporting DONE or PARTIAL: did the fix actually work, verified by you running something real?
2. CRITICAL: grep every diff this pass made for any change to human-approval-gate logic or governance boundaries -- confirm none were weakened. Confirm no gap triggered a real production build/regression/LSF submission.
3. Spot-check at least 2 of the "NEVER_BUILT" claims independently (your own grep/git log) to confirm they really were absent before this pass, not already-real mechanisms an agent duplicated.
4. TH-9 specifically: confirm the evidence_provenance field is genuinely enforced (a gate result lacking it is genuinely rejected, not just documented) and that the caveat genuinely renders somewhere real.
5. Run the full project test suite (python -m pytest dv_harness_tests/ -q) and report the real pass/fail count.
6. Check git hygiene across all commits this pass made.

Report a clear verdict per gap (GENUINELY_CLOSED / PARTIALLY_CLOSED / STILL_GAP / HONESTLY_BLOCKED) plus an overall verdict (APPROVED / NEEDS_FIX), with concrete evidence-cited findings.`, {label: 'final-review', phase: 'Review', model: 'claude-opus-5'})

return { closeResults: Object.fromEntries(closeResults), review }
