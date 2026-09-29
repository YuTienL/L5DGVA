export const meta = {
  name: 'three-loop-gap-close',
  description: 'Close the 3 confirmed real gaps from the ULTIMATE_COMPLETE 3-loop architecture audit: cross-loop coupling (DORMANT), real controlled-experiment execution for Capability Evolution, and an auto-generated Golden-Flow readiness matrix -- implementation explicitly authorized by the user',
  phases: [
    { title: 'Build', detail: 'sequential, reuse-first close pass' },
    { title: 'Review', detail: 'independent re-verification' },
  ],
}

const CONTEXT = `
This closes 3 real, already-confirmed gaps from a fresh, thorough completeness
audit of D:/DV/Task/DV_Agent_Harness_L5/CLAUDE_DV_Agent_Harness_L5_ULTIMATE_COMPLETE.md
against D:/DV/Task/DV_Agent_Harness_L5/v50/, run earlier this session:

1. Cross-loop coupling (\u00a753.4) -- DORMANT. Verification Closure Loop,
   Project Learning Loop, and Capability Evolution Loop are each real and
   individually WIRED_AND_FIRING, but the COUPLING between them is not:
   dv_harness/router.py's resolve_intent() (research routing) is confirmed
   never called from dv_harness/engine.py's run_stage() -- research/CCE is
   reachable only via a human typing 'dv-harness research <doc>', never
   triggered automatically by repeated verification evidence. Close: add a
   real hook (most naturally in memory_router.py's promotion path, since
   that's where repeated Project/Engineering Memory patterns already
   surface, or a new post-stage check in engine.py) that detects a repeated,
   unresolved failure/gap pattern (define a concrete, evidence-based
   threshold -- e.g. N>=2 independent Job Memory records sharing the same
   real failure_signature with no verified_fix) and automatically files a
   real CapabilityEvolutionCandidate at the DISCOVERED stage (never
   auto-advancing past DISCOVERED/PROPOSED -- EXPERIMENT_APPROVED and beyond
   remain strictly human-gated, per capability_evolution.py's existing
   HumanApprovalRequiredError). This closes the AUTOMATIC-DISCOVERY half of
   the coupling without weakening the human-approval boundary at all.

2. Real controlled-experiment execution (\u00a753.3) -- capability_evolution.py's
   benchmark_plan_complete / candidate["benchmark_plan"] are currently
   self-attested TEXT FIELDS, not code that actually drives a bounded
   experiment (isolated branch/worktree -> build -> verify -> benchmark ->
   before/after compare). grep confirms zero real benchmark-execution
   function exists. Close: add a real run_controlled_experiment() function
   to dv_harness/capability_evolution.py that, given an
   EXPERIMENT_APPROVED candidate, drives the EXISTING dv_harness/engine.py
   stage runner against an ISOLATED target (a synthetic/test project fixture
   for this close-pass's own verification -- NEVER a real production
   build/regression run as part of closing this gap) and populates the
   benchmark fields from real gate-verified before/after evidence rather
   than an agent-typed string. Test this against a synthetic fixture only.

3. Auto-generated Golden-Flow Readiness Matrix (\u00a747/49/55) -- NEVER_BUILT as
   an auto-generated artifact. The per-domain facts it would aggregate are
   all individually real and queryable (dashboard.py's existing readers,
   gates.py's STAGE_GATES, protocol_capability.py, qualification.py,
   env_manifest.py's testplan_correspondence) but nothing renders them into
   the document's specified one-command readiness table. Close: add a real
   dv_harness/golden_flow_readiness.py that queries these EXISTING real
   sources (never re-deriving data dashboard.py or gates.py could just
   supply) and renders the document's row shape, plus a CLI subcommand
   (following cli.py's existing subcommand conventions).

This project has an extremely strong, repeatedly-enforced norm against
building parallel/duplicate mechanisms. Reuse capability_evolution.py's
existing state machine (item 1, 2), engine.py's existing stage runner
(item 2), and dashboard.py/gates.py's existing real data sources (item 3)
-- never invent parallel infrastructure.

Check git status/git diff before touching any shared file (dv_harness/router.py,
dv_harness/engine.py, dv_harness/capability_evolution.py, dv_harness/cli.py --
other work, including a concurrent GUI-gap-close pass touching dashboard.py,
may be active) -- use the hand-scoped patch technique.

Item 2 in particular must NEVER trigger a real production build/regression
run as part of THIS close-pass -- test only against a synthetic/local
project fixture.
`

phase('Build')

const gaps = [
  'Gap 1: cross-loop coupling -- auto-file a CapabilityEvolutionCandidate at DISCOVERED on a repeated unresolved failure pattern, never auto-advancing past human-gated stages',
  'Gap 2: real run_controlled_experiment() in capability_evolution.py, driving engine.py\'s real stage runner against a synthetic fixture, replacing the self-attested benchmark_plan text field',
  'Gap 3: dv_harness/golden_flow_readiness.py aggregating existing real per-domain sources into the document\'s Golden-Flow Readiness Matrix shape + a CLI subcommand',
]

log('Building the 3 confirmed three-loop gaps sequentially.')

const closeResults = []
for (const name of gaps) {
  const fixResult = await agent(`Working directory: D:\\DV\\Task\\DV_Agent_Harness_L5\\v50

## Background

${CONTEXT}

You are handling exactly ONE gap: **${name}**

Check git status/git diff on any file you plan to touch FIRST -- other close-passes in this same sequential loop, and a concurrent GUI-gap-close workflow touching dashboard.py, may have already changed shared files. Re-read fresh if so, and use the hand-scoped patch technique (git diff > patch, trim to your hunk, git apply --cached --check then --cached) rather than a broad git add.

## Your task

1. Build the real mechanism described above for your gap.
2. Reuse existing real code (capability_evolution.py's state machine, engine.py's stage runner, dashboard.py/gates.py's data readers) -- never a parallel mechanism.
3. Preserve every existing human-approval gate exactly as-is -- do not weaken HumanApprovalRequiredError / EXPERIMENT_APPROVED / production-write gating in any way. Gap 1 specifically must only ever auto-file at DISCOVERED, never auto-advance further.
4. Gap 2 specifically: never trigger a real production build/regression run as part of closing this gap -- test only against a synthetic/local fixture project.
5. Write real tests proving the mechanism works end-to-end (not just that the underlying function works in isolation).
6. Run the full relevant test suite (at minimum dv_harness_tests/test_capability_evolution*.py and anything else you touched) and confirm pass.
7. Commit your change for real with a clear, scoped commit.
8. If something is a much larger effort than expected once you're in the code, scope down to a real, honest, smaller-but-still-genuine version rather than leaving it half-built, and report exactly what you built vs. deferred.

Write a report to .work/gap-close-3loop-${name.slice(0, 6).toLowerCase()}-report.md. Report DONE / PARTIAL / BLOCKED, with a one-line test summary.`, {label: `close:${name}`, phase: 'Build', model: 'claude-opus-5'})
  closeResults.push([name, fixResult])
  log(`Closed pass done for ${name}.`)
}

phase('Review')

const review = await agent(`Independently review this "close the 3 confirmed three-loop architecture gaps" effort for DV Agent Harness L5. Do not accept any report's own claim without independent re-verification.

Read every close-pass report in full first (search .work/ for files matching gap-close-3loop-*-report.md).

Raw returned results:
${closeResults.map(([name, result]) => `#### ${name}\n${result}`).join('\n\n')}

Verify independently:
1. For every close-pass reporting DONE or PARTIAL: did the fix actually work, verified by you running something real?
2. CRITICAL top-priority check: for Gap 1 and Gap 2, confirm NO human-approval gate was weakened and NO real production build/regression run was triggered as part of this pass -- grep the diffs for any change to HumanApprovalRequiredError/EXPERIMENT_APPROVED gating logic, and confirm Gap 2's test only ran against a synthetic fixture.
3. Run the full project test suite (python -m pytest dv_harness_tests/ -q) and report the real pass/fail count.
4. Check git hygiene across all commits this pass made.

Report a clear verdict per gap (GENUINELY_CLOSED / PARTIALLY_CLOSED / STILL_GAP) plus an overall verdict (APPROVED / NEEDS_FIX).`, {label: 'final-review', phase: 'Review', model: 'claude-opus-5'})

return { closeResults: Object.fromEntries(closeResults), review }
