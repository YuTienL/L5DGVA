export const meta = {
  name: 'gui-gap-close',
  description: 'Close the 4 confirmed real GUI gaps from the ULTIMATE_COMPLETE_GUI.md audit: AMBA fabric/scoreboard view, Research/CCE center, Memory/Obsidian knowledge center, and RBAC/auth on the dashboard -- real implementation, per the document\'s own Phase-2 gate now explicitly authorized by the user',
  phases: [
    { title: 'Build', detail: 'sequential, reuse-first close pass -- add real dashboard cards/endpoints + real auth' },
    { title: 'Review', detail: 'independent re-verification, including a real dashboard smoke test' },
  ],
}

const CONTEXT = `
This closes 4 real, already-confirmed gaps from a fresh, thorough completeness
audit of D:/DV/Task/DV_Agent_Harness_L5/CLAUDE_DV_Agent_Harness_L5_ULTIMATE_COMPLETE_GUI.md
against D:/DV/Task/DV_Agent_Harness_L5/v50/dv_harness/dashboard.py, run earlier
this session. The audit found the dashboard genuinely mature (9 of 20 GUI
requirements WIRED_AND_FIRING, 7 PARTIALLY_WIRED) but 4 real, clean gaps:

1. GUI-09 (AMBA Fabric / VIP Bind / Scoreboard view): zero "amba" hits in
   dashboard.py, yet the backend is substantial and real --
   dv_harness/amba_fabric_discovery.py (140KB), amba_port_registry.py,
   amba_scoreboard_env.py, amba_route_transform_predictor.py,
   amba_transaction_ir.py, amba_fabric_analysis.py, amba_discovery_report.py
   all exist. Close: add a real dashboard card + a real GET /api/amba
   endpoint reading AMBA_PORT_REGISTRY output and per-port scoreboard
   evidence from these real modules.

2. GUI-10 (Research / Continuous Capability Evolution center): zero
   research/capability-evolution hits in dashboard.py, yet
   dv_harness/capability_evolution.py (67KB) is real, .claude/skills/
   research-ingestion/SKILL.md and .claude/agents/research-architect.md
   are real, and it's gated through ControlPlane.approve(RESEARCH_CAPABILITY_EVOLUTION).
   Close: add a real card showing real CapabilityEvolutionCandidate records
   (KEEP/ENHANCE/ADD/EXPERIMENT/REJECT status) with real
   Approve/Reject/Hold buttons wired through the SAME control-plane dispatch
   mechanism dashboard.py already uses for other gates (_dispatch_control()) --
   never a parallel approval mechanism.

3. GUI-11 (Memory + Obsidian Knowledge Center): dashboard.py has zero
   Working/Job/Project/Engineering/Organizational tier display -- the
   existing "Shared Knowledge Center" card is a different thing (cross-project
   DB status). Real capability exists: dv_harness/memory_vault.py,
   docs/OBSIDIAN_INTEGRATION.md, a real populated vault at
   .dv-harness/vault/06_Agent_Memory/Engineering/*.md. Close: add a real
   card showing real per-tier record counts (dv_harness/memory.py's
   MemoryStore) and a way to browse/search real vault notes, reusing
   memory_vault.py's real search()/list functions -- never re-implementing
   markdown parsing in dashboard.py.

4. GUI-19 (Security / RBAC / Confirmation): dashboard.py's serve()
   (do_GET/do_POST) has NO authentication or permission check anywhere,
   despite exposing mutating actions (APPROVE, signoff-export, waiver
   authoring, control-plane TAKEOVER). Default bind is 127.0.0.1
   (dv_harness/config.py:42), which limits network exposure but is not
   access control -- any local process/user can hit these endpoints. Close:
   add a real, minimal permission-check layer in front of every mutating
   POST endpoint (a real token/role check -- e.g. a per-session token issued
   at dashboard startup and required on mutating requests, or an
   OS-user-based check appropriate for a localhost-only tool). Read-only
   GET endpoints do not need to be gated as strictly, but every action that
   can APPROVE/co-sign/export-signoff/take over control MUST require it.
   This is a real security fix -- do not build a decorative checkbox that
   doesn't actually block anything; write a real test that an unauthenticated
   mutating request is genuinely rejected.

This project has an extremely strong, repeatedly-enforced norm against
building parallel/duplicate mechanisms. For each gap, reuse dashboard.py's
existing card/endpoint patterns (read dashboard.py's existing cards first --
e.g. how the "Coverage Analysis" or "Signoff Export" cards are structured --
and follow the same conventions) and the real backend modules named above,
rather than inventing new patterns.

The GUI spec's own stop condition (quoted from the document, §83): "STOP
unless the user has explicitly authorized implementation." The user has now
explicitly authorized implementation of exactly these 4 gaps in this
session. Scope is bounded to these 4 -- do not attempt the 7 PARTIALLY_WIRED
items or anything else from the wider document in this pass.

Check git status/git diff on dashboard.py and config.py before touching them
(other work may be concurrent) -- use the hand-scoped patch technique for
shared files.
`

phase('Build')

const gaps = [
  'GUI-09: AMBA Fabric / VIP Bind / Scoreboard dashboard card + GET /api/amba endpoint',
  'GUI-10: Research / Continuous Capability Evolution center card + endpoints + Approve/Reject/Hold wired through _dispatch_control()',
  'GUI-11: Memory + Obsidian Knowledge Center card (5-tier counts + vault note browse/search)',
  'GUI-19: real permission/token check in front of every mutating POST endpoint, with a real rejection test',
]

log('Building the 4 confirmed GUI gaps sequentially (dashboard.py is shared across all 4, so strictly sequential to avoid collisions).')

const closeResults = []
for (const name of gaps) {
  const fixResult = await agent(`Working directory: D:\\DV\\Task\\DV_Agent_Harness_L5\\v50

## Background

${CONTEXT}

You are handling exactly ONE gap: **${name}**

Read dv_harness/dashboard.py in full first (or at minimum its card-rendering and endpoint-registration structure) to match its existing conventions exactly. Check git status/git diff dv_harness/dashboard.py dv_harness/config.py before touching them -- other close-passes in this same sequential loop, and possibly other concurrent session work, may have already changed them since you started; re-read fresh if so, and use the hand-scoped patch technique (git diff > patch, trim to your hunk, git apply --cached --check then --cached) rather than a broad git add.

## Your task

1. Build the real card + real backend-reading endpoint (or, for GUI-19, the real permission-check layer) as described in the background above.
2. Reuse existing real backend modules -- never re-derive data dashboard.py could just read from the real source module.
3. Write real tests: for GUI-09/10/11, a test that the new endpoint returns real data (or an honest empty/NOT_AVAILABLE state when the backing data doesn't exist) -- follow dashboard.py's own established "never fabricate, show honest empty state" convention already used by its Coverage/Self-Audit cards. For GUI-19, a test that PROVES an unauthenticated mutating request is genuinely rejected (not just that the code path exists).
4. Run the full relevant test suite (at minimum dv_harness_tests/test_dashboard*.py) and confirm pass.
5. Commit your change for real with a clear, scoped commit.
6. If something turns out to be a much larger effort than expected once you're in the code, you may scope down to a real, honest, smaller-but-still-genuine version (e.g. a read-only view before a full interactive one) rather than leaving it half-built -- but do not silently skip the gap; report exactly what you built and what you deferred.

Write a report to .work/gap-close-gui-${name.slice(0, 7).toLowerCase()}-report.md. Report DONE (with what changed) / PARTIAL (with what you built vs deferred) / BLOCKED, with a one-line test summary.`, {label: `close:${name}`, phase: 'Build', model: 'claude-opus-5'})
  closeResults.push([name, fixResult])
  log(`Closed pass done for ${name}.`)
}

phase('Review')

const review = await agent(`Independently review this "close the 4 confirmed GUI gaps" effort for DV Agent Harness L5. Do not accept any report's own claim without independent re-verification -- run real commands yourself.

Read every close-pass report in full first (search .work/ for files matching gap-close-gui-*-report.md).

Raw returned results, for cross-reference:

### Close-pass results
${closeResults.map(([name, result]) => `#### ${name}\n${result}`).join('\n\n')}

Verify independently:
1. For every close-pass reporting DONE or PARTIAL: did the fix actually work? Actually start the dashboard server (python -m dv_harness.dashboard, or however dashboard.py is normally launched -- check cli.py for the real launch command) against a synthetic/test project state if needed, and hit the new endpoints for real (curl or a Python requests call) to confirm they return real data or an honest empty state, not an error.
2. For GUI-19 specifically (top priority): actually attempt an unauthenticated mutating request (e.g. a real POST to /api/control or /api/waiver without whatever credential the fix requires) and confirm it is genuinely rejected. This is a security fix -- "the code looks like it should reject it" is not sufficient, you must observe a real rejection.
3. Run the full project test suite (python -m pytest dv_harness_tests/ -q) and report the real pass/fail count.
4. Check git hygiene across all commits this pass made.

Report a clear verdict per gap (GENUINELY_CLOSED / PARTIALLY_CLOSED / STILL_GAP) plus an overall verdict (APPROVED / NEEDS_FIX), with concrete evidence-cited findings.`, {label: 'final-review', phase: 'Review', model: 'claude-opus-5'})

return { closeResults: Object.fromEntries(closeResults), review }
